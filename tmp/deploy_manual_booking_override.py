import pathlib, shutil, subprocess, tempfile, py_compile, datetime

root = pathlib.Path('/root/mindaptive-responder')
container = subprocess.check_output(['docker', 'compose', 'ps', '-q', 'app'], cwd=root, text=True).strip()
assert container
stage = pathlib.Path(tempfile.mkdtemp(prefix='manual-booking-deploy-'))
names = ['scheduler.py', 'main.py', 'db.py', 'static/app.js']
for name in names:
    dest = stage / 'live' / name
    dest.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(['docker', 'cp', f'{container}:/srv/app/{name}', str(dest)], check=True)
    src = stage / 'source' / name
    src.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(root / 'app' / name, src)

def replace(s, old, new):
    if s.count(old) != 1:
        raise RuntimeError(f'Expected one occurrence: {old[:100]!r}, found {s.count(old)}')
    return s.replace(old, new, 1)

for version in ('live', 'source'):
    p = stage / version / 'scheduler.py'
    s = p.read_text()
    s = replace(s, 'def _send_due_draft(draft: dict) -> str:', 'def _send_due_draft(draft: dict, *, manual_click: bool = False) -> str:')
    s = replace(s, '    is_aftercare = draft.get("kind") == "aftercare"\n', '''    is_aftercare = draft.get("kind") == "aftercare"
    manual_booking_override = manual_click and draft.get("kind") not in ("sequence", "aftercare")
    def manual_suppressed():
        email = (draft.get("lead_email") or "").strip().lower()
        with db.db_session() as conn:
            return bool(conn.execute("SELECT 1 FROM leads_state WHERE (lead_id = ? OR (? != '' AND lower(trim(email)) = ?)) AND status IN ('blacklisted', 'stopped') LIMIT 1", (lead_id, email, email)).fetchone())
    if manual_booking_override and manual_suppressed():
        with db.db_session() as conn:
            db.update_draft(conn, draft["id"], status="stale", send_error="Contact is stopped or opted out.")
        return "stale"
''')
    s = replace(s, 'if not is_aftercare and booking_guard.is_locally_booked(', 'if not is_aftercare and not manual_booking_override and booking_guard.is_locally_booked(')
    s = replace(s, 'elif not booking_guard.allow_send(lead_id, campaign_id, lead_email):', 'elif not manual_booking_override and not booking_guard.allow_send(lead_id, campaign_id, lead_email):')
    s = replace(s, '    resp = smartlead.reply_to_thread(\n', '''    if manual_booking_override and manual_suppressed():
        with db.db_session() as conn:
            db.update_draft(conn, draft["id"], status="stale", send_error="Contact is stopped or opted out.")
        return "stale"
    resp = smartlead.reply_to_thread(
''')
    s = s.replace('if draft["kind"] == "auto_response":\n        from app import auto_replies', 'if draft["kind"] == "auto_response" and not manual_booking_override:\n        from app import auto_replies')
    s = s.replace('if draft["kind"] == "auto_response" and not auto_replies.enabled():', 'if draft["kind"] == "auto_response" and not manual_booking_override and not auto_replies.enabled():')
    p.write_text(s)
    p = stage / version / 'main.py'; s = p.read_text()
    s = replace(s, 'scheduler._send_due_draft, dict(_get_draft_dict(draft_id))', 'scheduler._send_due_draft, dict(_get_draft_dict(draft_id)), manual_click=True')
    p.write_text(s)
    p = stage / version / 'db.py'; s = p.read_text()
    s = replace(s, '        if aftercare.approval_for(conn, draft) is None:\n', '        if draft["kind"] == "manual" and draft["status"] == "pending":\n            continue\n        if aftercare.approval_for(conn, draft) is None:\n')
    p.write_text(s)
    p = stage / version / 'static/app.js'; s = p.read_text()
    s = replace(s, '    if (result.status !== "sent") {\n', '    if (result.status !== "sent") {\n      alert(`Message was not sent (status: ${result.status}). Please review the conversation.`);\n')
    s = replace(s, '  state.detail.lead.category = "waiting";', '  if (state.detail.lead.category !== "booked") state.detail.lead.category = "waiting";')
    s = replace(s, '    row.category = "waiting";', '    if (row.category !== "booked") row.category = "waiting";')
    p.write_text(s)
    for f in ('scheduler.py', 'main.py', 'db.py'):
        py_compile.compile(str(stage / version / f), doraise=True)

backup = root / ('manual-booking-backup-' + datetime.datetime.now().strftime('%Y%m%d%H%M%S'))
backup.mkdir()
for version in ('live', 'source'):
    for name in names:
        dest = backup / version / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        if version == 'live':
            subprocess.run(['docker', 'cp', f'{container}:/srv/app/{name}', str(dest)], check=True)
        else:
            shutil.copy2(root / 'app' / name, dest)
for name in names:
    shutil.copy2(stage / 'source' / name, root / 'app' / name)
    subprocess.run(['docker', 'cp', str(stage / 'live' / name), f'{container}:/srv/app/{name}'], check=True)
subprocess.run(['docker', 'restart', container], check=True)
print('Deployed isolated changes. Backup:', backup)
