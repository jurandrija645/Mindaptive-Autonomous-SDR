import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

root = Path(__file__).resolve().parent.parent
fixture = json.loads((root/'tmp/onebody-perf-fixture-20261109.json').read_text())
fixture['detail']['draft'] = fixture['detail'].get('draft') or {
    'id':-1,'kind':'reply','status':'pending','body_html':'<p>Thanks, Hannah.</p>',
    'signature_html':'','attachments':[],'recipients':{'to':'test@example.com'},'review_warning':None,
}
bootstrap = '''
localStorage.clear();
window.__fixture=FIXTURE;
window.__requests=[];
window.fetch=async function(url,options){
 if(options?.method && options.method !== 'GET') throw new Error('Diagnostic fixture forbids live writes');
 window.__requests.push(String(url));
 let data={};
 if(String(url)==='/api/inbox') data={...window.__fixture.inbox,scan_running:false};
 else if(String(url).startsWith('/api/leads/')) {
  const parts=String(url).split('/');
  const lead=window.__fixture.inbox.leads.find(l=>String(l.campaign_id)===parts[3] && String(l.lead_id)===parts[4]);
  data={...window.__fixture.detail,lead:{...window.__fixture.detail.lead,...lead,archived_at:null,archive_reason:null}};
 }
 else if(String(url)==='/api/archive') data={snoozed:[],archived:[]};
 else if(String(url)==='/api/categories') data={categories:[]};
 else if(String(url)==='/api/models') data={models:[],roles:[]};
 else if(String(url)==='/api/sequences/triggers') data={triggers:[]};
 else if(String(url)==='/api/auto-replies') data={enabled:false};
 return new Response(JSON.stringify(data),{headers:{'Content-Type':'application/json'}});
};
window.EventSource=class {close(){}};
window.setInterval=function(){return 0;};
'''.replace('FIXTURE',json.dumps({'inbox':fixture['inbox'],'detail':fixture['detail']}).replace('<','\\u003c'))

runner = '''
(async()=>{
 const report={userAgent:navigator.userAgent,leads:0,measurements:[],longtasks:[]};
 const obs=new PerformanceObserver(list=>report.longtasks.push(...list.getEntries().map(e=>({start:e.startTime,duration:e.duration}))));
 obs.observe({type:'longtask',buffered:true});
 const frame=()=>new Promise(resolve=>requestAnimationFrame(resolve));
 const flush=async()=>{await frame();await frame();};
 const timed=async(name,fn)=>{const start=performance.now();await fn();const sync=performance.now()-start;void document.body.offsetHeight;const layout=performance.now()-start;await flush();report.measurements.push({name,js_ms:sync,layout_ms:layout,paint_ms:performance.now()-start});};
 try {
  await flush();
  report.leads=state.leads.length;
  report.dom_nodes=document.querySelectorAll('*').length;
  for(let i=0;i<3;i++) await timed('list_rebuild',()=>renderList());
  for(let i=0;i<3;i++) await timed('unchanged_refresh',()=>autoRefreshInbox());
  for(let i=0;i<3;i++) await timed('select_lead',()=>selectLead(i));
  const note=document.getElementById('regen-note');
  note.focus();
  for(const char of 'please shorten this reply') await timed('regen_input',()=>{
   note.dispatchEvent(new KeyboardEvent('keydown',{key:char,bubbles:true}));
   note.value+=char;
   note.dispatchEvent(new InputEvent('input',{data:char,inputType:'insertText',bubbles:true}));
  });
  report.regen_input_requests=window.__requests.length;
  const search=document.getElementById('lead-search');
  for(const char of 'andrew') await timed('search_'+char,()=>{search.value+=char;search.dispatchEvent(new Event('input',{bubbles:true}));});
  report.empty_dom_nodes=document.querySelectorAll('*').length;
  for(const char of 'test') await timed('regen_input_filtered',()=>{note.value+=char;note.dispatchEvent(new InputEvent('input',{data:char,bubbles:true}));});
  report.checks=await window.runDashboardChecks();
 }catch(error){report.error=String(error.stack||error);}
 const pre=document.createElement('pre');pre.id='performance-report';pre.textContent=JSON.stringify(report,null,2);document.body.prepend(pre);
 await new Promise((resolve)=>{const req=new XMLHttpRequest();req.open('POST','/results');req.onload=resolve;req.onerror=resolve;req.send(JSON.stringify(report));});
})();
'''
html = fixture['html'].replace('<head>','<head><meta http-equiv="Content-Security-Policy" content="default-src \'self\'; script-src \'self\' \'unsafe-inline\'; style-src \'self\' \'unsafe-inline\'; img-src data:; connect-src \'self\'">\n<script src="/bootstrap.js"></script>')
html = html.replace('</body>','<script src="/browser-checks.js" defer></script><script src="/perf-run.js" defer></script></body>')

class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):
        pass
    def do_GET(self):
        path = urlsplit(self.path).path
        if path == '/': data,kind=html.encode(),'text/html'
        elif path=='/bootstrap.js': data,kind=bootstrap.encode(),'application/javascript'
        elif path=='/perf-run.js': data,kind=runner.encode(),'application/javascript'
        elif path=='/browser-checks.js': data,kind=(root/'tests/dashboard_browser_checks.js').read_bytes(),'application/javascript'
        elif path in ('/static/app.js','/static/crm.js','/static/style.css'):
            data=(root/'app'/path.lstrip('/')).read_bytes()
            kind='text/css' if path.endswith('.css') else 'application/javascript'
        else:
            self.send_error(404);return
        self.send_response(200);self.send_header('Content-Type',kind+'; charset=utf-8');self.end_headers();self.wfile.write(data)
    def do_POST(self):
        if self.path!='/results':self.send_error(404);return
        data=self.rfile.read(int(self.headers.get('Content-Length','0')))
        parsed=json.loads(data)
        (root/'tmp/onebody-browser-perf-20261109.json').write_text(json.dumps(parsed,indent=2))
        self.send_response(204);self.end_headers()

print('Local diagnostic fixture ready on http://127.0.0.1:8766',flush=True)
ThreadingHTTPServer(('127.0.0.1',8766),Handler).serve_forever()
