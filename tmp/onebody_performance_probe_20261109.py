import cProfile
import io
import json
import pstats
import time
from pathlib import Path

import httpx

from app import db, main
from app.config import settings

result = {}
with db.db_session() as conn:
    result['database'] = {'bytes': Path(settings.db_path).stat().st_size,
        'leads': conn.execute('SELECT COUNT(*) FROM leads_state').fetchone()[0],
        'cached_threads': conn.execute('SELECT COUNT(*) FROM lead_threads').fetchone()[0]}
    chosen = [dict(r) for r in conn.execute(
        "SELECT lead_id,campaign_id,name FROM leads_state WHERE name IN ('Hannah Speller','Konstantin Kissimov')")]
    result['largest_threads'] = [dict(r) for r in conn.execute(
        'SELECT lead_id,campaign_id,length(thread_json) AS raw_bytes FROM lead_threads ORDER BY raw_bytes DESC LIMIT 5')]
profile = cProfile.Profile()
profile.enable()
start = time.perf_counter()
inbox = main._inbox_payload()
result['inbox_internal_ms'] = round((time.perf_counter()-start)*1000,2)
profile.disable()
stream = io.StringIO()
pstats.Stats(profile,stream=stream).sort_stats('cumulative').print_stats(15)
result['inbox_profile'] = stream.getvalue()
result['visible_leads'] = len(inbox)
result['http'] = []
with httpx.Client(base_url='http://127.0.0.1:8080',timeout=60,follow_redirects=True) as client:
    client.post('/login',data={'password':settings.app_password}).raise_for_status()
    paths = ['/api/inbox']*3 + [f"/api/leads/{r['campaign_id']}/{r['lead_id']}" for r in chosen for _ in range(2)]
    for path in paths:
        start = time.perf_counter()
        response = client.get(path)
        elapsed = (time.perf_counter()-start)*1000
        response.raise_for_status()
        record = {'path':path,'ms':round(elapsed,2),'bytes':len(response.content)}
        data = response.json()
        if 'thread' in data:
            record.update({'messages':len(data['thread']),
                'html_bytes':sum(len(m['html']) for m in data['thread']),
                'image_count':sum(m['html'].count('<img') for m in data['thread'])})
        result['http'].append(record)
    Path('/tmp/onebody-perf-inbox.json').write_text(json.dumps({'leads':inbox}))
result['host_load'] = Path('/proc/loadavg').read_text().strip()
result['host_memory'] = [line for line in Path('/proc/meminfo').read_text().splitlines() if line.startswith(('MemTotal:','MemAvailable:','SwapTotal:','SwapFree:'))]
print(json.dumps(result))
