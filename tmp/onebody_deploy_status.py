import json
from app import db
with db.db_session() as conn:
    auto = db.get_setting(conn, 'onebody_auto_replies')
    rows = conn.execute("SELECT status, count(*) AS n FROM drafts WHERE kind='aftercare' GROUP BY status").fetchall()
print(json.dumps({'auto_replies': auto, 'aftercare': {r['status']: r['n'] for r in rows}}))
