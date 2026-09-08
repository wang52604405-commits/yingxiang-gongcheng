"""Loopback-only disposable dashboard acceptance fixture, NEVER deploy."""
import sys
from pathlib import Path
from datetime import datetime, timedelta, timezone
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_admin_ops import AdminOpsTest, test_connection
from server.admin_ops import record_activity

if __name__ == '__main__':
    fixture = AdminOpsTest()
    fixture.setUp()
    current = datetime.now(timezone.utc)
    with test_connection() as conn:
        conn.execute("UPDATE accounts SET display_name='本地模拟验收'")
        conn.execute("UPDATE admin_metrics_meta SET value=? WHERE key='started_at'",
                     ((current-timedelta(days=6)).isoformat(),))
    for offset in range(7):
        for account_id in ([2,3] if offset % 2 == 0 else [2]):
            record_activity({'id':account_id,'role':'user','status':'active','_token_scope':'desktop'},
                            (current-timedelta(days=offset)).timestamp())
    try:
        fixture.app.run(host='127.0.0.1',port=8770,debug=False,use_reloader=False)
    finally:
        fixture.cleanup()
