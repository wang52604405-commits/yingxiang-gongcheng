# -*- coding: utf-8 -*-
"""
工程影像管理平台 — 账号与授权中心服务器

启动：
  python -m server.app                          # 开发模式，127.0.0.1:5000
  ALBUM_SERVER_HOST=0.0.0.0 ALBUM_SERVER_PORT=80 python -m server.app

创建管理员：
  python -m server.app create-admin --username admin --password 强密码

接口：
  POST /api/register            注册客户账号
  POST /api/login               登录（返回 Bearer 令牌）
  GET  /api/me                  当前账号信息
  POST /api/activate            绑定本机并签发授权码（客户端调用）
  GET  /api/admin/accounts      管理后台：账号+授权+机器列表
  POST /api/admin/license       开通/修改授权
  POST /api/admin/revoke        吊销授权（全部机器下线）
  POST /api/admin/unbind        解绑某台机器
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import random
import re
import string
import sys
import time as _time
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from flask import Flask, jsonify, render_template, request, send_file, send_from_directory
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from werkzeug.security import check_password_hash, generate_password_hash

from . import config, db

# 简单内存限流：每 IP 每窗口最多允许的次数，防止暴力破解/灌账号
_rate_hits = defaultdict(list)
RATE_WINDOW = 60          # 窗口 60 秒
RATE_LIMIT = 20           # 窗口内最多 20 次


def _rate_limited():
    """按请求 IP 计数；超限返回 True。"""
    ip = str(request.remote_addr or "unknown")
    now = _time.time()
    hits = [t for t in _rate_hits[ip] if now - t < RATE_WINDOW]
    if len(hits) >= RATE_LIMIT:
        return True
    hits.append(now)
    _rate_hits[ip] = hits
    return False


# 验证码 TTL。存储用数据库（gunicorn 多 worker 共享），不用进程内存
CODE_TTL = 600


def _save_code(code_key: str, code: str) -> None:
    """保存验证码到数据库（多 worker 共享）。"""
    conn = db.connect()
    try:
        conn.execute(
            "INSERT INTO mail_codes (code_key, code, expires_at) VALUES (?, ?, ?) "
            "ON CONFLICT(code_key) DO UPDATE SET code = excluded.code, "
            "expires_at = excluded.expires_at, created_at = datetime('now', 'localtime')",
            (code_key, code, int(_time.time()) + CODE_TTL),
        )
        conn.commit()
    finally:
        conn.close()


def _consume_code(code_key: str, code: str) -> bool:
    """校验并一次性消费验证码；正确且未过期返回 True。"""
    conn = db.connect()
    try:
        row = conn.execute(
            "SELECT code, expires_at FROM mail_codes WHERE code_key = ?", (code_key,)
        ).fetchone()
        if not row:
            return False
        conn.execute("DELETE FROM mail_codes WHERE code_key = ?", (code_key,))
        conn.commit()
        if str(row["code"]) != code:
            return False
        if int(row["expires_at"]) < int(_time.time()):
            return False
        return True
    finally:
        conn.close()
# 邀请码字符集：去易混字符（0/O、1/I/L）
INVITE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
INVITE_CODE_LEN = 8
INVITE_MILESTONE = 10   # 每邀请 10 人，邀请人续期 1 个月
REWARD_MONTH_DAYS = 30


def _generate_invite_code(conn):
    """生成不重复的 8 位邀请码。"""
    for _ in range(50):
        code = "".join(random.choice(INVITE_ALPHABET) for _ in range(INVITE_CODE_LEN))
        exists = conn.execute(
            "SELECT 1 FROM accounts WHERE invite_code = ?", (code,)
        ).fetchone()
        if not exists:
            return code
    return "INV" + str(int(_time.time()))[-5:]


def _grant_or_extend_license(conn, account_id: int, days: int):
    """给账号追加 term 授权 days 天：已有授权则从当前到期时间往后延，否则新建。"""
    existing = conn.execute(
        "SELECT * FROM licenses WHERE account_id = ? ORDER BY id DESC LIMIT 1",
        (account_id,),
    ).fetchone()
    now = datetime.now(timezone.utc)
    if existing and existing["active"]:
        if existing["license_type"] == "lifetime":
            return  # 终身授权无需续期
        base = now
        if existing["expires_at"]:
            try:
                base = _parse_utc(existing["expires_at"])
                if base < now:
                    base = now
            except ValueError:
                base = now
        expires_at = (base + timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
        conn.execute(
            "UPDATE licenses SET valid_days = ?, expires_at = ?, active = 1, "
            "issued_at = ? WHERE id = ?",
            (max(int(existing["valid_days"] or 0), days), expires_at, _now(), existing["id"]),
        )
    else:
        expires_at = (now + timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
        conn.execute(
            "INSERT INTO licenses (account_id, license_type, valid_days, machine_limit, "
            "issued_at, expires_at, active) VALUES (?, 'term', ?, ?, ?, ?, 1)",
            (account_id, days, config.DEFAULT_MACHINE_LIMIT, _now(), expires_at),
        )


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_utc(value: str):
    """解析带 Z 后缀的 UTC 时间。Python 3.10 的 fromisoformat 不认 Z，
    用 strptime 显式解析并标记为 UTC，避免到期校验被静默跳过。"""
    return datetime.strptime(str(value), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def _b64u(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _b64u_decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _canonical(payload: dict) -> bytes:
    return json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


class LicenseSigner:
    """用服务器私钥签发 Ed25519 授权码（客户端内置公钥验签，格式兼容）。"""

    def __init__(self, path):
        self.path = path
        self._key = None

    def _load(self):
        if self._key is None:
            from cryptography.hazmat.primitives import serialization

            if not self.path.exists():
                raise RuntimeError(f"未找到授权私钥: {self.path}")
            self._key = serialization.load_pem_private_key(
                self.path.read_bytes(), password=None
            )
        return self._key

    def sign(self, payload: dict) -> str:
        canon = _canonical(payload)
        sig = self._load().sign(canon)
        signed = {"payload": payload, "signature": _b64u(sig)}
        raw = json.dumps(signed, ensure_ascii=False, separators=(",", ":")).encode(
            "utf-8"
        )
        return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


signer = LicenseSigner(config.PRIVATE_KEY_PATH)
serializer = URLSafeTimedSerializer(config.SECRET_KEY)


def _error(message: str, code: int = 400):
    return jsonify({"ok": False, "error": message}), code


def _token_for(user_id: int) -> str:
    return serializer.dumps({"uid": user_id}, salt="album-auth")


def _user_from_token(token: str):
    if not token:
        return None
    try:
        data = serializer.loads(
            token, max_age=config.TOKEN_MAX_AGE, salt="album-auth"
        )
    except (BadSignature, SignatureExpired):
        return None
    conn = db.connect()
    try:
        row = conn.execute(
            "SELECT * FROM accounts WHERE id = ?", (data.get("uid"),)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def _require_user():
    auth = request.headers.get("Authorization", "")
    token = auth[7:] if auth.startswith("Bearer ") else ""
    user = _user_from_token(token)
    if not user or user["status"] != "active":
        return None
    return user


def _require_admin():
    user = _require_user()
    if not user or user["role"] != "admin":
        return None
    return user


def _account_license(conn, account_id: int):
    return conn.execute(
        "SELECT * FROM licenses WHERE account_id = ? ORDER BY id DESC LIMIT 1",
        (account_id,),
    ).fetchone()


def _machine_count(conn, account_id: int):
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM machines WHERE account_id = ? AND active = 1",
        (account_id,),
    ).fetchone()
    return int(row["n"])


def _license_status_for(account: dict, machine_id: str = ""):
    conn = db.connect()
    try:
        lic = _account_license(conn, account["id"])
        machines = conn.execute(
            "SELECT machine_id, bound_at, last_seen FROM machines "
            "WHERE account_id = ? AND active = 1 ORDER BY bound_at",
            (account["id"],),
        ).fetchall()
        return {
            "account": account["username"],
            "role": account["role"],
            "has_license": lic is not None and bool(lic["active"]),
            "license_type": dict(lic).get("license_type") if lic else "",
            "expires_at": dict(lic).get("expires_at") if lic else "",
            "machine_limit": dict(lic).get("machine_limit") if lic else config.DEFAULT_MACHINE_LIMIT,
            "machine_count": _machine_count(conn, account["id"]),
            "machines": [dict(m) for m in machines],
            "bound_this_machine": machine_id in {m["machine_id"] for m in machines},
        }
    finally:
        conn.close()


def _sign_for(account: dict, machine_id: str, license_row) -> str:
    lic = dict(license_row)
    payload = {
        "app": config.APP_CODE,
        "account": account["username"],
        "machine_id": machine_id.upper(),
        "license_type": lic["license_type"],
        "issued_at": lic["issued_at"],
        "expires_at": lic["expires_at"] or "",
        "valid_days": int(lic["valid_days"] or 0),
        "version": 3,
    }
    return signer.sign(payload)


def create_app():
    app = Flask(__name__)
    app.config["SECRET_KEY"] = config.SECRET_KEY
    app.json.ensure_ascii = False

    db.init_db()
    if config.ADMIN_USERNAME and config.ADMIN_PASSWORD:
        _ensure_admin(config.ADMIN_USERNAME, config.ADMIN_PASSWORD)

    @app.get("/")
    def index():
        return render_template("member_center.html")

    @app.get("/cloud-preview")
    def cloud_preview_page():
        return render_template("cloud.html")

    @app.get("/admin")
    def admin_index():
        return render_template("admin.html")

    @app.post("/api/send-code")
    def send_code():
        """注册验证码（基础版）：生成 6 位验证码存内存返回给客户端，TTL 600 秒。"""
        if _rate_limited():
            return _error("操作过于频繁，请稍后再试", 429)
        data = request.get_json(silent=True) or {}
        account = str(data.get("account") or "").strip()
        if not (3 <= len(account) <= 64):
            return _error("账号长度需在 3~64 个字符之间")
        code = str(random.randint(100000, 999999))
        _save_code(f"reg:{account}", code)
        return jsonify({
            "ok": True,
            "code": code,
            "expires_in": CODE_TTL,
            "note": "基础版：验证码由服务器生成并返回（未接短信服务商）。",
        })

    @app.post("/api/register")
    def register():
        if _rate_limited():
            return _error("操作过于频繁，请稍后再试", 429)
        data = request.get_json(silent=True) or {}
        username = str(data.get("username") or "").strip()
        password = str(data.get("password") or "")
        invite_code = str(data.get("invite_code") or "").strip().upper()
        display_name = str(data.get("display_name") or "").strip()
        email = str(data.get("email") or "").strip()
        if not (3 <= len(username) <= 64):
            return _error("账号长度需在 3~64 个字符之间（可用手机号/QQ/邮箱）")
        if len(password) < 6:
            return _error("密码至少 6 位")
        # 免验证码注册（用户名+密码直接注册）

        conn = db.connect()
        try:
            exists = conn.execute(
                "SELECT 1 FROM accounts WHERE username = ?", (username,)
            ).fetchone()
            if exists:
                return _error("账号已存在")

            # 邀请码（可选）：查邀请人，写入 invites 表，并触发 10 人/月 续期奖励
            inviter = None
            if invite_code:
                inviter = conn.execute(
                    "SELECT * FROM accounts WHERE invite_code = ?", (invite_code,)
                ).fetchone()

            new_code = _generate_invite_code(conn)
            cur = conn.execute(
                "INSERT INTO accounts (username, password_hash, display_name, role, status, invite_code, inviter_id, email) "
                "VALUES (?, ?, ?, 'user', 'active', ?, ?, ?)",
                (username, generate_password_hash(password), display_name, new_code,
                 inviter["id"] if inviter else 0, email),
            )
            new_account_id = cur.lastrowid

            if inviter:
                # 记录邀请关系（一人一邀请，UNIQUE 防重）
                conn.execute(
                    "INSERT OR IGNORE INTO invites (inviter_id, invitee_account_id) VALUES (?, ?)",
                    (inviter["id"], new_account_id),
                )
                # 统计邀请人已注册人数，每满 10 人续期 1 个月（无限累加）
                row = conn.execute(
                    "SELECT COUNT(*) AS n FROM invites WHERE inviter_id = ?", (inviter["id"],)
                ).fetchone()
                count = int(row["n"])
                target = count // INVITE_MILESTONE
                reward = int(inviter["invite_reward_months"] or 0)
                if target > reward:
                    delta = target - reward
                    _grant_or_extend_license(conn, inviter["id"], delta * REWARD_MONTH_DAYS)
                    conn.execute(
                        "UPDATE accounts SET invite_reward_months = ? WHERE id = ?",
                        (target, inviter["id"]),
                    )

            conn.commit()
            return jsonify({
                "ok": True,
                "account": {"username": username, "invite_code": new_code},
                "invited_by": inviter["username"] if inviter else "",
            })
        finally:
            conn.close()

    @app.post("/api/forgot-password")
    def forgot_password():
        """找回密码：按账号查绑定邮箱，发验证码到邮箱。"""
        if _rate_limited():
            return _error("操作过于频繁，请稍后再试", 429)
        data = request.get_json(silent=True) or {}
        account = str(data.get("account") or "").strip()
        if not (3 <= len(account) <= 64):
            return _error("请输入正确的账号")
        conn = db.connect()
        try:
            row = conn.execute(
                "SELECT id, username, email FROM accounts WHERE username = ?", (account,)
            ).fetchone()
        finally:
            conn.close()
        if not row:
            return _error("账号不存在")
        email = str(row["email"] or "").strip()
        if not email:
            return _error("该账号未绑定邮箱，无法通过邮箱找回。请联系管理员重置密码")
        code = str(random.randint(100000, 999999))
        _save_code(f"reset:{account}", code)
        try:
            from . import mailer
            mailer.send_code_email(email, code)
        except ValueError as exc:
            return _error(str(exc))
        except Exception as exc:
            return _error(f"邮件发送失败：{exc}")
        return jsonify({
            "ok": True,
            "email": email[:3] + "***" + email[email.find("@"):],
            "expires_in": CODE_TTL,
        })

    @app.post("/api/reset-password")
    def reset_password():
        """用验证码重置密码。"""
        if _rate_limited():
            return _error("操作过于频繁，请稍后再试", 429)
        data = request.get_json(silent=True) or {}
        account = str(data.get("account") or "").strip()
        code = str(data.get("code") or "").strip()
        new_password = str(data.get("new_password") or "")
        if len(new_password) < 6:
            return _error("新密码至少 6 位")
        if not _consume_code(f"reset:{account}", code):
            return _error("验证码错误或已过期，请重新获取", 400)
        conn = db.connect()
        try:
            cur = conn.execute(
                "UPDATE accounts SET password_hash = ? WHERE username = ?",
                (generate_password_hash(new_password), account),
            )
            conn.commit()
            if cur.rowcount == 0:
                return _error("账号不存在")
        finally:
            conn.close()
        return jsonify({"ok": True, "message": "密码已重置，请用新密码登录"})

    @app.post("/api/login")
    def login():
        if _rate_limited():
            return _error("操作过于频繁，请稍后再试", 429)
        data = request.get_json(silent=True) or {}
        username = str(data.get("username") or "").strip()
        password = str(data.get("password") or "")
        conn = db.connect()
        try:
            row = conn.execute(
                "SELECT * FROM accounts WHERE username = ?", (username,)
            ).fetchone()
        finally:
            conn.close()
        if not row or not check_password_hash(row["password_hash"], password):
            return _error("账号或密码错误", 401)
        account = dict(row)
        if account["status"] != "active":
            return _error("账号已被停用", 403)
        return jsonify(
            {
                "ok": True,
                "token": _token_for(account["id"]),
                "account": {
                    "username": account["username"],
                    "display_name": account["display_name"],
                    "role": account["role"],
                },
            }
        )

    @app.get("/api/invite-status")
    def invite_status():
        user = _require_user()
        if not user:
            return _error("未登录或登录已过期", 401)
        conn = db.connect()
        try:
            row = conn.execute(
                "SELECT invite_code, invite_reward_months FROM accounts WHERE id = ?",
                (user["id"],),
            ).fetchone()
            invite_code = row["invite_code"] if row else ""
            reward_months = int(row["invite_reward_months"] or 0) if row else 0
            count_row = conn.execute(
                "SELECT COUNT(*) AS n FROM invites WHERE inviter_id = ?", (user["id"],)
            ).fetchone()
            registered_count = int(count_row["n"])
        finally:
            conn.close()
        next_milestone = INVITE_MILESTONE - (registered_count % INVITE_MILESTONE)
        return jsonify({
            "ok": True,
            "invite_code": invite_code,
            "registered_count": registered_count,
            "reward_months": reward_months,
            "next_milestone": next_milestone,  # 还差几人到下一个里程碑
            "milestone": INVITE_MILESTONE,
        })

    @app.get("/api/check-update")
    def check_update():
        current = str(request.args.get("current") or "").strip()
        version_file = config.DATA_DIR / "version.json"
        info = {}
        if version_file.exists():
            try:
                import json as _json

                info = _json.loads(version_file.read_text(encoding="utf-8"))
            except Exception:
                info = {}
        latest = str(info.get("version") or "")
        has_update = bool(latest and latest != current)
        return jsonify({
            "ok": True,
            "latest_version": latest,
            "changelog": info.get("changelog") or [],
            "fixes": info.get("fixes") or [],
            "download_url": info.get("download_url") or "",
            "has_update": has_update,
        })

    @app.post("/api/admin/version")
    def admin_version():
        if not _require_admin():
            return _error("需要管理员权限", 403)
        data = request.get_json(silent=True) or {}
        version = str(data.get("version") or "").strip()
        if not version:
            return _error("缺少版本号")
        info = {
            "version": version,
            "changelog": [str(x) for x in (data.get("changelog") or [])],
            "fixes": [str(x) for x in (data.get("fixes") or [])],
            "download_url": str(data.get("download_url") or "").strip(),
        }
        config.DATA_DIR.mkdir(parents=True, exist_ok=True)
        import json as _json

        (config.DATA_DIR / "version.json").write_text(
            _json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return jsonify({"ok": True, "info": info})

    @app.get("/download/update/<path:filename>")
    def download_update(filename):
        updates_dir = config.DATA_DIR / "updates"
        return send_from_directory(updates_dir, filename, as_attachment=True)

    @app.get("/api/me")
    def me():
        user = _require_user()
        if not user:
            return _error("未登录或登录已过期", 401)
        return jsonify(
            {
                "ok": True,
                "account": {
                    "username": user["username"],
                    "display_name": user["display_name"],
                    "role": user["role"],
                },
                "license": _license_status_for(user),
            }
        )

    @app.post("/api/activate")
    def activate():
        user = _require_user()
        if not user:
            return _error("未登录或登录已过期", 401)
        data = request.get_json(silent=True) or {}
        machine_id = str(data.get("machine_id") or "").strip().upper()
        if not machine_id:
            return _error("缺少机器 ID")

        conn = db.connect()
        try:
            lic = _account_license(conn, user["id"])
            is_member = bool(lic and lic["active"])
            if lic and lic["active"] and lic["license_type"] == "term" and lic["expires_at"]:
                try:
                    exp = _parse_utc(lic["expires_at"])
                    if datetime.now(timezone.utc) > exp:
                        # 到期：不再视为会员，但仍允许免费版激活绑定本机
                        is_member = False
                except ValueError:
                    pass

            # 免费版账号（无授权/到期）也能激活绑定本机，走免费版限制；会员才签发授权码
            machine_limit = int(lic["machine_limit"] or config.DEFAULT_MACHINE_LIMIT) if lic else config.DEFAULT_MACHINE_LIMIT
            bound = conn.execute(
                "SELECT id FROM machines WHERE account_id = ? AND machine_id = ?",
                (user["id"], machine_id),
            ).fetchone()
            if bound:
                conn.execute(
                    "UPDATE machines SET last_seen = ?, active = 1 WHERE id = ?",
                    (_now(), bound["id"]),
                )
            else:
                count = _machine_count(conn, user["id"])
                if count >= machine_limit:
                    return _error(
                        f"本账号已绑定 {count} 台电脑，达到上限 {machine_limit} 台，"
                        "请联系管理员解绑或升级",
                        403,
                    )
                conn.execute(
                    "INSERT INTO machines (account_id, machine_id, bound_at, last_seen) "
                    "VALUES (?, ?, ?, ?)",
                    (user["id"], machine_id, _now(), _now()),
                )
            conn.commit()
            code = _sign_for(user, machine_id, lic) if is_member else ""
            return jsonify(
                {
                    "ok": True,
                    "license_code": code,
                    "is_member": is_member,
                    "license": _license_status_for(user, machine_id),
                }
            )
        finally:
            conn.close()

    # ------------------------------------------------------------ 管理后台

    @app.get("/api/admin/accounts")
    def admin_accounts():
        if not _require_admin():
            return _error("需要管理员权限", 403)
        conn = db.connect()
        try:
            rows = conn.execute("SELECT * FROM accounts ORDER BY id").fetchall()
            result = []
            for row in rows:
                account = dict(row)
                # 邀请关系：谁通过该账号邀请码注册的（被邀请人列表）
                invitees = conn.execute(
                    "SELECT a.username FROM invites i JOIN accounts a ON a.id = i.invitee_account_id "
                    "WHERE i.inviter_id = ? ORDER BY i.created_at",
                    (account["id"],),
                ).fetchall()
                invitee_names = [r["username"] for r in invitees]
                # 该账号是被谁邀请的
                inviter_name = ""
                if account.get("inviter_id"):
                    inv_row = conn.execute(
                        "SELECT username FROM accounts WHERE id = ?", (account["inviter_id"],)
                    ).fetchone()
                    if inv_row:
                        inviter_name = inv_row["username"]
                result.append(
                    {
                        "account": account,
                        "license": _license_status_for(account),
                        "invite_code": account.get("invite_code", ""),
                        "invitees": invitee_names,
                        "invited_by": inviter_name,
                        "invite_count": len(invitee_names),
                    }
                )
            return jsonify({"ok": True, "accounts": result})
        finally:
            conn.close()

    @app.post("/api/admin/license")
    def admin_license():
        if not _require_admin():
            return _error("需要管理员权限", 403)
        data = request.get_json(silent=True) or {}
        account_id = int(data.get("account_id") or 0)
        license_type = str(data.get("license_type") or "term").strip().lower()
        if license_type not in {"term", "lifetime"}:
            return _error("授权类型无效")
        valid_days = max(0, int(data.get("valid_days") or 0))
        machine_limit = max(1, int(data.get("machine_limit") or config.DEFAULT_MACHINE_LIMIT))
        conn = db.connect()
        try:
            account = conn.execute(
                "SELECT * FROM accounts WHERE id = ?", (account_id,)
            ).fetchone()
            if not account:
                return _error("账号不存在", 404)
            issued_at = _now()
            expires_at = ""
            if license_type == "term" and valid_days > 0:
                expires_at = (
                    datetime.now(timezone.utc) + timedelta(days=valid_days)
                ).strftime("%Y-%m-%dT%H:%M:%SZ")
            existing = _account_license(conn, account_id)
            if existing:
                conn.execute(
                    "UPDATE licenses SET license_type = ?, valid_days = ?, "
                    "machine_limit = ?, issued_at = ?, expires_at = ?, active = 1 "
                    "WHERE id = ?",
                    (license_type, valid_days, machine_limit, issued_at, expires_at, existing["id"]),
                )
            else:
                conn.execute(
                    "INSERT INTO licenses (account_id, license_type, valid_days, "
                    "machine_limit, issued_at, expires_at, active) "
                    "VALUES (?, ?, ?, ?, ?, ?, 1)",
                    (account_id, license_type, valid_days, machine_limit, issued_at, expires_at),
                )
            conn.commit()
            return jsonify(
                {
                    "ok": True,
                    "license": _license_status_for(dict(account)),
                }
            )
        finally:
            conn.close()

    @app.post("/api/admin/revoke")
    def admin_revoke():
        if not _require_admin():
            return _error("需要管理员权限", 403)
        data = request.get_json(silent=True) or {}
        account_id = int(data.get("account_id") or 0)
        conn = db.connect()
        try:
            conn.execute(
                "UPDATE licenses SET active = 0 WHERE account_id = ?", (account_id,)
            )
            conn.execute(
                "UPDATE machines SET active = 0 WHERE account_id = ?", (account_id,)
            )
            conn.commit()
            return jsonify({"ok": True})
        finally:
            conn.close()

    @app.post("/api/admin/unbind")
    def admin_unbind():
        if not _require_admin():
            return _error("需要管理员权限", 403)
        data = request.get_json(silent=True) or {}
        account_id = int(data.get("account_id") or 0)
        machine_id = str(data.get("machine_id") or "").strip().upper()
        conn = db.connect()
        try:
            conn.execute(
                "UPDATE machines SET active = 0 "
                "WHERE account_id = ? AND machine_id = ?",
                (account_id, machine_id),
            )
            conn.commit()
            return jsonify({"ok": True})
        finally:
            conn.close()

    # ------------------------------------------------------------ 云预览（公网查看）

    @app.post("/api/cloud/sync")
    def cloud_sync():
        """客户端推送缩略图+编号（登录后按账号隔离存储）。"""
        user = _require_user()
        if not user:
            return _error("未登录或登录已过期", 401)
        data = request.get_json(silent=True) or {}
        projects = data.get("projects") if isinstance(data.get("projects"), list) else []
        if len(projects) > 200:
            return _error("单次同步项目数超限")
        conn = db.connect()
        try:
            for proj in projects:
                code = str(proj.get("project_code") or "").strip()
                if not code:
                    continue
                # upsert 项目
                exists = conn.execute(
                    "SELECT id FROM cloud_projects WHERE account_id = ? AND project_code = ?",
                    (user["id"], code),
                ).fetchone()
                if exists:
                    proj_id = exists["id"]
                    conn.execute(
                        "UPDATE cloud_projects SET project_name = ?, unit_name = ?, "
                        "part_name = ?, thumb_count = ?, synced_at = ? WHERE id = ?",
                        (str(proj.get("project_name") or "")[:200],
                         str(proj.get("unit_name") or "")[:200],
                         str(proj.get("part_name") or "")[:200],
                         int(proj.get("thumb_count") or 0), _now(), proj_id),
                    )
                else:
                    cur = conn.execute(
                        "INSERT INTO cloud_projects (account_id, project_code, project_name, "
                        "unit_name, part_name, thumb_count, synced_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (user["id"], code, str(proj.get("project_name") or "")[:200],
                         str(proj.get("unit_name") or "")[:200],
                         str(proj.get("part_name") or "")[:200],
                         int(proj.get("thumb_count") or 0), _now()),
                    )
                    proj_id = cur.lastrowid
                # 缩略图增量同步（photo_name + 模糊缩略图 base64）
                thumbs = proj.get("thumbs")
                if isinstance(thumbs, list):
                    for idx, thumb in enumerate(thumbs[:500]):
                        name = str(thumb.get("photo_name") or "").strip()
                        b64 = str(thumb.get("thumb_b64") or "").strip()
                        if not name or not b64 or len(b64) > 200_000:
                            continue
                        texists = conn.execute(
                            "SELECT id FROM cloud_thumbs WHERE project_id = ? AND photo_name = ?",
                            (proj_id, name),
                        ).fetchone()
                        if texists:
                            conn.execute(
                                "UPDATE cloud_thumbs SET thumb_b64 = ?, order_index = ?, synced_at = ? WHERE id = ?",
                                (b64, idx, _now(), texists["id"]),
                            )
                        else:
                            conn.execute(
                                "INSERT INTO cloud_thumbs (project_id, photo_name, thumb_b64, order_index, synced_at) "
                                "VALUES (?, ?, ?, ?, ?)",
                                (proj_id, name, b64, idx, _now()),
                            )
            conn.commit()
            return jsonify({"ok": True})
        finally:
            conn.close()

    @app.get("/api/cloud/projects")
    def cloud_projects():
        """当前账号的项目列表（编号+名称+缩略图数）。"""
        user = _require_user()
        if not user:
            return _error("未登录或登录已过期", 401)
        conn = db.connect()
        try:
            rows = conn.execute(
                "SELECT id, project_code, project_name, unit_name, part_name, thumb_count, synced_at "
                "FROM cloud_projects WHERE account_id = ? ORDER BY project_code",
                (user["id"],),
            ).fetchall()
            return jsonify({
                "ok": True,
                "projects": [dict(r) for r in rows],
            })
        finally:
            conn.close()

    @app.get("/api/cloud/thumbs")
    def cloud_thumbs():
        """当前账号某项目的缩略图列表（模糊图 base64 + 照片名）。"""
        user = _require_user()
        if not user:
            return _error("未登录或登录已过期", 401)
        project_id = int(request.args.get("project_id") or 0)
        conn = db.connect()
        try:
            owns = conn.execute(
                "SELECT id FROM cloud_projects WHERE id = ? AND account_id = ?",
                (project_id, user["id"]),
            ).fetchone()
            if not owns:
                return _error("项目不存在", 404)
            thumbs = conn.execute(
                "SELECT photo_name, thumb_b64, order_index FROM cloud_thumbs "
                "WHERE project_id = ? ORDER BY order_index, id",
                (project_id,),
            ).fetchall()
            return jsonify({
                "ok": True,
                "thumbs": [dict(t) for t in thumbs],
            })
        finally:
            conn.close()

    @app.post("/api/cloud/clear")
    def cloud_clear():
        """客户端可选：清除某个项目的云预览（保留编号，清缩略图）。"""
        user = _require_user()
        if not user:
            return _error("未登录或登录已过期", 401)
        data = request.get_json(silent=True) or {}
        project_id = int(data.get("project_id") or 0)
        conn = db.connect()
        try:
            conn.execute(
                "DELETE FROM cloud_thumbs WHERE project_id = ? AND project_id IN "
                "(SELECT id FROM cloud_projects WHERE id = ? AND account_id = ?)",
                (project_id, project_id, user["id"]),
            )
            conn.execute(
                "UPDATE cloud_projects SET thumb_count = 0 WHERE id = ? AND account_id = ?",
                (project_id, user["id"]),
            )
            conn.commit()
            return jsonify({"ok": True})
        finally:
            conn.close()

    return app


def _ensure_admin(username: str, password: str) -> None:
    conn = db.connect()
    try:
        exists = conn.execute(
            "SELECT 1 FROM accounts WHERE username = ?", (username,)
        ).fetchone()
        if not exists:
            conn.execute(
                "INSERT INTO accounts (username, password_hash, display_name, role, status) "
                "VALUES (?, ?, ?, 'admin', 'active')",
                (username, generate_password_hash(password), "管理员"),
            )
            conn.commit()
            print(f"[OK] 管理员账号已创建: {username}")
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="账号与授权中心")
    parser.add_argument("--host", default=os.environ.get("ALBUM_SERVER_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("ALBUM_SERVER_PORT", "5000")))
    sub = parser.add_subparsers(dest="cmd")
    p_admin = sub.add_parser("create-admin", help="创建管理员账号")
    p_admin.add_argument("--username", required=True)
    p_admin.add_argument("--password", required=True)
    args = parser.parse_args()
    if args.cmd == "create-admin":
        db.init_db()
        _ensure_admin(args.username, args.password)
        return
    app = create_app()
    app.run(host=args.host, port=args.port, debug=False)


if __name__ == "__main__":
    main()
