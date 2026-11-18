import concurrent.futures
import json
import pathlib
import shutil
import classify as audit

BASE = pathlib.Path(__file__).resolve().parent
records = json.loads((BASE / 'records-with-links.json').read_text(encoding='utf-8'))
live = json.loads((BASE / 'live-categories.json').read_text())
enhanced = set(json.loads((BASE / 'link-enhanced-keys.json').read_text()))
positive = {'Interested', 'Information Request', 'Meeting Request', 'DirectInterestedIn55', 'Meeting Booked'}
selected = [r for i, r in enumerate(records) if r['key'] in enhanced or i < 12 or live[str(r['campaign_id'])][str(r['lead_id'])]['category'] in positive]
audit.OUT = BASE / 'critical-review'
audit.OUT.mkdir(exist_ok=True)
shutil.copyfile(BASE / 'live-categories.json', audit.OUT / 'live-categories.json')
audit.SYSTEM += '''
Additional precision for the completed-handover decision: The owner does NOT require the lead to have booked before marking Lead Done. Do not use 'has not booked yet' as a reason to keep Interested when we already sent every requested item. The full history matters: a later generic bump does not undo an earlier complete handover. If we sent a working-for-that-time booking link AND code and answered the lead's actual questions, and then we wrote last without promising further action, Lead Done is normally appropriate. An optional 'let me know if you need help' is not an outstanding task or unanswered question. In contrast, a latest unanswered question about insurance, appointment availability, refund, code failure, location details or sharing with colleagues remains unfinished, even if a link/code was sent earlier. Do not infer a booking, and do not weaken opt-out/negative/current booked statuses. Booking links in [booking link: URL] are actual email anchors; signature links alone are NOT a requested handover. For Lead Done, cite fulfillment evidence, not just a later nudge. All decisions are proposals only, owner approval is still required.'''
print('Critical second pass leads:', len(selected), flush=True)
batches = [(i // 10, selected[i:i+10]) for i in range(0, len(selected), 10)]
with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
    futures = [pool.submit(audit.classify, i, rows) for i, rows in batches]
    for n, f in enumerate(concurrent.futures.as_completed(futures), 1):
        f.result()
        print(f'Critical pass {n}/{len(batches)} batches', flush=True)
decisions = [d for i, _ in batches for d in json.loads((audit.OUT / f'batch-{i:03d}.json').read_text(encoding='utf-8'))['decisions']]
(BASE / 'critical-decisions.json').write_text(json.dumps(decisions, ensure_ascii=False, indent=2), encoding='utf-8')
