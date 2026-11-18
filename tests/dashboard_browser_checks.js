/* Browser regressions for the dashboard's local, network-isolated fixture.
   Loaded by tmp/onebody_perf_server_20261109.py; never calls a live API. */
window.runDashboardChecks = async function () {
  const passed = [];
  const assert = (condition, message) => { if (!condition) throw new Error(message); };
  const copy = (value) => JSON.parse(JSON.stringify(value));
  const originalInbox = copy(window.__fixture.inbox);
  const baseFetch = window.fetch;
  const response = (value) => new Response(JSON.stringify(value));
  const pause = (ms = 0) => new Promise((resolve) => setTimeout(resolve, ms));
  const frames = async () => { await new Promise(requestAnimationFrame); await new Promise(requestAnimationFrame); };
  const rows = () => [...document.querySelectorAll('#lead-list .lead-row')];
  const rowFor = (lead) => rows().find((row) => leadKey(state.leads[Number(row.dataset.index)]) === leadKey(lead));
  const reset = async () => {
    window.fetch = baseFetch;
    cancelLeadRequest();
    clearTimeout(leadSearchTimer);
    window.__fixture.inbox = copy(originalInbox);
    state.view = 'inbox'; state.mode = 'outreach'; state.searchQuery = '';
    state.categoryFilter = new Set(CATEGORY_ORDER); state.campaignFilter = null;
    state.smartleadCategoryFilter = null; state.dateFrom = null; state.dateTo = null;
    state.sortOrder = 'default'; state.selected = -1; state.detail = null;
    inboxDataSignature = null; inboxRendered = false;
    document.getElementById('lead-search').value = '';
    await loadInbox();
  };
  const check = async (name, test) => { await reset(); await test(); passed.push(name); };
  try {
    await check('selecting a lead preserves every sidebar row', async () => {
      const before = rows();
      await selectLead(0);
      assert(rows().every((row, i) => row === before[i]), 'Selection rebuilt sidebar rows');
      await selectLead(1);
      assert(document.querySelectorAll('#lead-list .selected').length === 1, 'Wrong selection count');
      assert(rowFor(state.leads[1]).classList.contains('selected'), 'Wrong highlighted lead');
    });
    await check('unchanged refresh performs no sidebar DOM mutations', async () => {
      const mutations = [];
      const observer = new MutationObserver((records) => mutations.push(...records));
      observer.observe(document.getElementById('lead-list'), {subtree:true, childList:true, attributes:true});
      await loadInbox();
      assert(mutations.length + observer.takeRecords().length === 0, 'Unchanged poll mutated the sidebar');
      observer.disconnect();
    });
    await check('one changed lead replaces only its own row', async () => {
      const before = rows();
      window.__fixture.inbox.leads[0].preview = 'New reply received';
      await loadInbox();
      assert(rows().filter((row, i) => row !== before[i]).length === 1, 'Unchanged rows were replaced');
      assert(rows()[0].textContent.includes('New reply received'), 'New reply not displayed');
    });
    await check('background updates preserve unsaved draft, instructions and focus', async () => {
      await selectLead(0);
      const editor = document.getElementById('draft-editor');
      const note = document.getElementById('regen-note');
      editor.innerHTML = '<p>Unsaved handwritten message</p>'; onEditorInput();
      note.value = 'Keep my instructions'; note.focus();
      window.__fixture.inbox.leads[2].preview = 'Changed in the background';
      await loadInbox();
      assert(document.getElementById('draft-editor') === editor && editor.innerHTML.includes('Unsaved'), 'Editor was replaced');
      assert(note.value === 'Keep my instructions' && document.activeElement === note, 'Instructions/focus lost');
      assert(state.originalHtml.includes('Unsaved'), 'Handwritten body lost');
    });
    await check('filtering never retargets the visible draft actions', async () => {
      await selectLead(0);
      const key = leadKey(state.detail.lead);
      state.searchQuery = 'zzzz-no-such-person'; applyFilter();
      assert(state.selected === -1 && state.leads.length === 0, 'Filter failed');
      const ids = currentLeadIds();
      assert(`${ids.cid}/${ids.lid}` === key, 'Actions retargeted a different person');
      state.searchQuery = ''; applyFilter();
      assert(leadKey(currentLead()) === key, 'Selection not restored by identity');
    });
    await check('reordered cached rows click their current lead', async () => {
      const lead = state.leads[0], node = rowFor(lead);
      [state.leads[0], state.leads[1]] = [state.leads[1], state.leads[0]];
      renderList();
      assert(rowFor(lead) === node && node.dataset.index === '1', 'Row was not reused at the new position');
      node.click(); await frames();
      assert(leadKey(state.detail.lead) === leadKey(lead), 'Reused row clicked its old index');
    });
    await check('overlapping refreshes share one request; a webhook queues one follow-up', async () => {
      let requests = 0, release;
      window.fetch = (url, options) => {
        if (url !== '/api/inbox') return baseFetch(url, options);
        requests += 1;
        if (requests > 1) return Promise.resolve(response(window.__fixture.inbox));
        return new Promise((resolve) => { release = resolve; });
      };
      const a = loadInbox(), b = loadInbox(), c = autoRefreshInbox(true), d = autoRefreshInbox(true);
      assert(requests === 1, 'Refreshes overlapped');
      release(response(window.__fixture.inbox));
      await Promise.all([a,b,c,d]); await pause();
      if (inboxRequest) await inboxRequest;
      assert(requests === 2, 'Webhook update was lost or requested repeatedly');
    });
    await check('a pending refresh preserves a newer user selection', async () => {
      let release;
      window.fetch = (url, options) => url === '/api/inbox'
        ? new Promise((resolve) => { release = resolve; }) : baseFetch(url, options);
      const pending = loadInbox();
      await selectLead(1);
      const key = leadKey(state.detail.lead);
      window.__fixture.inbox.leads[2].preview = 'New server data';
      release(response(window.__fixture.inbox)); await pending;
      assert(leadKey(currentLead()) === key, 'Refresh restored the old selection');
    });
    await check('late responses and errors cannot overwrite a newer conversation', async () => {
      const pending = [];
      window.fetch = (url, options) => {
        if (!String(url).startsWith('/api/leads/')) return baseFetch(url, options);
        return new Promise((resolve, reject) => pending.push({url, options, resolve, reject}));
      };
      const a = selectLead(0), b = selectLead(1);
      assert(pending[0].options.signal.aborted, 'Previous request was not aborted');
      const current = copy(window.__fixture.detail);
      current.lead = {...current.lead, ...state.leads[1]};
      pending[1].resolve(response(current)); await b;
      pending[0].reject(new Error('Old network failure')); await a;
      assert(leadKey(state.detail.lead) === leadKey(state.leads[1]), 'Old request replaced current conversation');
      const c = selectLead(0), d = selectLead(1);
      pending[3].resolve(response(current)); await d;
      const old = copy(current); old.lead = {...old.lead, ...state.leads[0]};
      pending[2].resolve(response(old)); await c;
      assert(leadKey(state.detail.lead) === leadKey(state.leads[1]), 'Late successful response replaced current lead');
    });
    await check('changing views cancels a pending conversation', async () => {
      let release, signal;
      window.fetch = (url, options) => String(url).startsWith('/api/leads/')
        ? new Promise((resolve) => { release = resolve; signal = options.signal; }) : baseFetch(url, options);
      const pending = selectLead(0);
      setView('archive');
      release(response(window.__fixture.detail)); await pending; await pause();
      assert(signal.aborted && state.view === 'archive' && !state.detail, 'Conversation leaked into another view');
    });
    await check('rapid search typing waits for the final query', async () => {
      const search = document.getElementById('lead-search'), count = state.leads.length;
      for (const value of ['z','zz','zzz-no-such-person']) {
        search.value = value; search.dispatchEvent(new Event('input', {bubbles:true}));
      }
      assert(state.leads.length === count, 'Search did synchronous work on every key');
      await pause(180);
      assert(state.leads.length === 0, 'Debounced query was not applied');
    });
    await check('scheduled and archive list controls still render', async () => {
      const lead = state.leads[0];
      state.view = 'scheduled'; state.leads = [{...lead, draft_id:44, scheduled_at:'Tomorrow'}]; renderList();
      assert(!document.getElementById('lead-list').classList.contains('inbox-list'), 'Inbox containment leaked to scheduled view');
      assert(rows()[0].textContent.includes('Send now') && rows()[0].textContent.includes('Cancel'), 'Scheduled actions missing');
      state.view = 'archive'; state.snoozedCount = 0; renderList();
      assert(rows()[0].textContent.includes('Restore'), 'Archive actions missing');
    });
    await check('row removal keeps a different newly selected conversation open', async () => {
      await selectLead(0); const removedKey = leadKey(state.detail.lead);
      await withRowRemoval(async () => {});
      await selectLead(1); const selectedKey = leadKey(state.detail.lead);
      await pause(380);
      assert(!state.leads.some((lead) => leadKey(lead) === removedKey), 'Wrong row removed');
      assert(leadKey(state.detail.lead) === selectedKey && leadKey(currentLead()) === selectedKey, 'Removal changed newer selection');
    });
    await check('offscreen rows use browser layout containment', async () => {
      assert(getComputedStyle(rows()[0]).contentVisibility === 'auto', 'Offscreen layout containment not active');
    });
  } finally {
    window.fetch = baseFetch;
    await reset();
  }
  return passed;
};
