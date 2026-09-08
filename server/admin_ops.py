"""Admin operations and first-party, account-level online activity metrics.

No page URLs, IPs, request bodies or device identifiers are stored in metrics.
Activity measures authenticated connectivity, including background sync, not
time spent using the desktop application. Daily buckets use Asia/Shanghai.
"""
from datetime import datetime, timedelta, timezone
from contextlib import closing
import sqlite3
import time

from flask import g, jsonify, request
from . import config, db

CST = timezone(timedelta(hours=8))


def record_activity(user, now=None):
    if not user or user.get('role') == 'admin' or user.get('status') != 'active':
        return
    timestamp = int(time.time() if now is None else now)
    day = datetime.fromtimestamp(timestamp, CST).date().isoformat()
    channel = 'mobile' if user.get('_token_scope') == 'mobile' else 'desktop_web'
    # A metrics failure must not block customer requests. One row per account,
    # day and channel; at most one actual update per minute, shared by workers.
    with closing(sqlite3.connect(config.DB_PATH, timeout=0.2)) as conn:
        conn.execute(
            'INSERT INTO admin_usage_daily VALUES (?, ?, ?, ?, ?) '
            'ON CONFLICT(day, account_id, channel) DO UPDATE SET last_seen=excluded.last_seen '
            'WHERE admin_usage_daily.last_seen <= excluded.last_seen - 60',
            (day, user['id'], channel, timestamp, timestamp),
        )
        conn.commit()


def dashboard(conn, now=None):
    current = now or datetime.now(timezone.utc)
    today = current.astimezone(CST).date()
    start = today - timedelta(days=13)
    started = conn.execute("SELECT value FROM admin_metrics_meta WHERE key='started_at'").fetchone()[0]
    first_day = datetime.fromisoformat(started.replace('Z', '+00:00')).astimezone(CST).date()
    rows = conn.execute(
        'SELECT u.day, COUNT(DISTINCT u.account_id) AS active '
        'FROM admin_usage_daily u JOIN accounts a ON a.id=u.account_id '
        "WHERE u.day >= ? AND u.day <= ? AND a.role != 'admin' GROUP BY u.day",
        (start.isoformat(), today.isoformat()),
    ).fetchall()
    by_day = {row['day']: row['active'] for row in rows}
    trend = [{'day': (start + timedelta(days=i)).isoformat(),
              'active': by_day.get((start + timedelta(days=i)).isoformat(), 0)
              if start + timedelta(days=i) >= first_day else None} for i in range(14)]
    def count(sql, args=()):
        return conn.execute(sql, args).fetchone()[0]
    day = today.isoformat()
    recent = count(
        "SELECT COUNT(DISTINCT u.account_id) FROM admin_usage_daily u JOIN accounts a ON a.id=u.account_id "
        "WHERE u.last_seen >= ? AND u.last_seen <= ? AND a.role != 'admin' AND a.status='active'",
        (int(current.timestamp()) - 900, int(current.timestamp())),
    )
    week = count(
        "SELECT COUNT(DISTINCT u.account_id) FROM admin_usage_daily u JOIN accounts a ON a.id=u.account_id "
        "WHERE u.day BETWEEN ? AND ? AND a.role != 'admin'",
        ((today-timedelta(days=6)).isoformat(), day),
    )
    # Legacy accounts/errors use SQLite localtime (deployment is CST), while
    # mobile records use UTC ISO timestamps. Do not shift local dates twice.
    legacy_day = "CASE WHEN instr(created_at,'T')>0 THEN date(created_at,'+8 hours') ELSE date(created_at) END"
    registered = count(f"SELECT COUNT(*) FROM accounts WHERE role != 'admin' AND ({legacy_day})=?", (day,))
    uploaded = count("SELECT COUNT(*) FROM cloud_photos WHERE date(created_at,'+8 hours')=?", (day,))
    imported = count("SELECT COUNT(*) FROM cloud_photos WHERE date(desktop_imported_at,'+8 hours')=?", (day,))
    errors = count(f"SELECT COUNT(*) FROM client_error_logs WHERE ({legacy_day})=?", (day,))
    unresolved = count('SELECT COUNT(*) FROM client_error_logs WHERE resolved=0')
    channels = [dict(r) for r in conn.execute(
        "SELECT u.channel, COUNT(DISTINCT u.account_id) AS active FROM admin_usage_daily u "
        "JOIN accounts a ON a.id=u.account_id WHERE u.day=? AND a.role != 'admin' GROUP BY u.channel", (day,))]
    latest = [dict(r) for r in conn.execute(
        "SELECT a.id, a.username, a.display_name, a.status, MAX(u.last_seen) AS last_seen "
        "FROM admin_usage_daily u JOIN accounts a ON a.id=u.account_id "
        "WHERE u.day=? AND a.role != 'admin' GROUP BY a.id ORDER BY last_seen DESC LIMIT 12", (day,))]
    return {'day': day, 'timezone': 'Asia/Shanghai', 'generated_at': current.isoformat(),
            'started_at': started, 'today_active': by_day.get(day, 0), 'recent_active': recent,
            'week_active': week, 'registered_today': registered, 'uploaded_today': uploaded,
            'imported_today': imported, 'errors_today': errors, 'unresolved': unresolved,
            'trend': trend, 'channels': channels, 'latest': latest}


def register_admin_ops(app, require_admin, user_from_token):
    @app.after_request
    def collect_usage(response):
        if not request.path.startswith('/api/') or request.path.startswith('/api/admin/') or request.path == '/api/client-errors':
            return response
        if not 200 <= response.status_code < 300 or request.method == 'OPTIONS':
            return response
        try:
            user = getattr(g, 'activity_user', None)
            # Successful password/WeChat login may issue a token without first
            # entering the authenticated-request helper.
            if user is None and response.is_json and not response.is_streamed:
                data = response.get_json(silent=True)
                if isinstance(data, dict) and data.get('token'):
                    user = user_from_token(data['token'])
            record_activity(user)
        except Exception:
            app.logger.warning('Activity metric write skipped; customer response preserved')
        return response

    @app.get('/api/admin/dashboard')
    def admin_dashboard():
        if not require_admin():
            return jsonify(ok=False, error='需要管理员权限'), 403
        conn = db.connect()
        try:
            return jsonify(ok=True, dashboard=dashboard(conn))
        finally:
            conn.close()

    @app.post('/api/admin/accounts/<int:account_id>/status')
    def account_status(account_id):
        admin = require_admin()
        if not admin:
            return jsonify(ok=False, error='需要管理员权限'), 403
        data = request.get_json(silent=True)
        if not isinstance(data, dict) or not isinstance(data.get('status'), str) or data.get('status') not in {'active', 'disabled'}:
            return jsonify(ok=False, error='请选择停用或恢复'), 400
        status = data['status']
        note = str(data.get('note') or '').strip()
        if len(note) > 500:
            return jsonify(ok=False, error='备注不能超过500字'), 400
        conn = db.connect()
        try:
            conn.execute('BEGIN IMMEDIATE')
            account = conn.execute('SELECT id, role, status FROM accounts WHERE id=?', (account_id,)).fetchone()
            if not account:
                return jsonify(ok=False, error='账号不存在'), 404
            if account_id == admin['id'] or account['role'] == 'admin':
                return jsonify(ok=False, error='此入口不能停用或恢复管理员账号'), 400
            if account['status'] == status:
                return jsonify(ok=True, changed=False)
            conn.execute('UPDATE accounts SET status=? WHERE id=?', (status, account_id))
            # Revoke all old desktop/mobile tokens. Recovery requires a fresh
            # login and never revives old tokens or extends any license.
            conn.execute('INSERT INTO admin_account_access VALUES (?,1) ON CONFLICT(account_id) '
                         'DO UPDATE SET version=version+1', (account_id,))
            conn.execute('UPDATE accounts SET mobile_auth_version=COALESCE(mobile_auth_version,0)+1 WHERE id=?', (account_id,))
            conn.execute('INSERT INTO admin_account_audit(account_id,actor_id,status,note,created_at) VALUES (?,?,?,?,?)',
                         (account_id, admin['id'], status, note, datetime.now(timezone.utc).isoformat()))
            conn.commit()
            return jsonify(ok=True, changed=True)
        finally:
            conn.close()
