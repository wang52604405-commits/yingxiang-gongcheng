"""Read-only production metrics check; does not load credentials or issue tokens."""
import json
import os
import sqlite3
import sys
os.environ['ALBUM_SERVER_SECRET'] = 'read-only-metrics-validation'
sys.path.insert(0, '/opt/album-auth')
from server.admin_ops import dashboard

conn = sqlite3.connect('file:/opt/album-auth/data/server.db?mode=ro', uri=True)
conn.row_factory = sqlite3.Row
try:
    data = dashboard(conn)
    print(json.dumps({key:data[key] for key in ['day','started_at','today_active',
        'registered_today','uploaded_today','errors_today']}))
finally:
    conn.close()
