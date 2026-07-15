"use strict";

const state = {
  view: "inbox",        // "inbox" | "archive"
  leads: [],
  snoozedCount: 0,       // archive view only: state.leads[0..snoozedCount) are snoozed, rest archived
  selected: -1,
  detail: null,          // current lead detail {lead, thread, draft}
  translated: false,     // thread currently showing English
  englishSegments: null,
};

const CHIP = {
  reply: "Awaiting your reply",
  followup: "Follow-up due",
  waiting: "In conversation",
};

const $ = (id) => document.getElementById(id);

// ---------- helpers ----------
function el(tag, cls, text) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text != null) n.textContent = text;
  return n;
}

function todayStr() {
  return new Date().toISOString().slice(0, 10);
}

function currentLead() {
  return state.leads[state.selected];
}

async function apiGet(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}
async function apiPost(url, body) {
  const r = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {}),
  });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.error || "Request failed");
  return data;
}

// ---------- inbox / archive list loading ----------
async function loadInbox() {
  const data = await apiGet("/api/inbox");
  state.leads = data.leads;
  state.snoozedCount = 0;
  renderList();
  $("scan-status").textContent = data.scan_running ? "↻ scanning…" : "";
  return data;
}

async function loadArchive() {
  const data = await apiGet("/api/archive");
  state.snoozedCount = data.snoozed.length;
  state.leads = data.snoozed.concat(data.archived);
  state.selected = -1;
  renderList();
  $("detail-body").hidden = true;
  $("detail-empty").hidden = false;
  return data;
}

function setView(view) {
  state.view = view;
  $("legend").hidden = view === "archive";
  $("rescan-btn").hidden = view === "archive";
  $("archive-toggle-btn").textContent = view === "archive" ? "Back to inbox" : "Archive";
  state.selected = -1;
  $("detail-body").hidden = true;
  $("detail-empty").hidden = false;
  const load = view === "archive" ? loadArchive : loadInbox;
  load().catch((e) => console.error(e));
}

function renderList() {
  const list = $("lead-list");
  list.innerHTML = "";
  const archiveMode = state.view === "archive";

  $("inbox-count").textContent = `${archiveMode ? "Archive" : "Inbox"} (${state.leads.length})`;
  $("inbox-empty").hidden = state.leads.length > 0;
  $("inbox-empty").innerHTML = archiveMode
    ? "Nothing archived or snoozed."
    : 'No leads yet. Click <strong>Rescan now</strong> — it checks every “Interested” lead and takes a couple of minutes.';

  state.leads.forEach((lead, i) => {
    if (archiveMode && i === 0 && state.snoozedCount > 0) {
      list.appendChild(el("li", "list-section", "Snoozed — hidden until due"));
    }
    if (archiveMode && i === state.snoozedCount) {
      list.appendChild(el("li", "list-section", "Archived"));
    }

    const row = el("li", `lead-row ${archiveMode ? "archive-row" : "cat-" + lead.category}`);
    if (i === state.selected) row.classList.add("selected");
    row.dataset.index = i;

    const top = el("div", "lead-top");
    if (lead.language) top.appendChild(el("span", "lang-badge", lead.language));
    top.appendChild(el("span", "lead-name", lead.name));
    if (lead.company) top.appendChild(el("span", "lead-company", "· " + lead.company));
    if (!archiveMode && lead.has_draft) top.appendChild(el("span", "ready-dot"));
    row.appendChild(top);

    if (archiveMode) {
      const isSnoozed = i < state.snoozedCount;
      const reason = isSnoozed
        ? `Snoozed until ${lead.snooze_until}`
        : lead.archive_reason === "not_interested" ? "Not interested" : "Archived";
      row.appendChild(el("div", "lead-preview", reason));
      const quickBtn = el("button", "btn-secondary row-action", isSnoozed ? "Follow up now" : "Restore");
      quickBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        const endpoint = isSnoozed ? "unsnooze" : "unarchive";
        withRowRemoval(() => apiPost(`/api/leads/${lead.campaign_id}/${lead.lead_id}/${endpoint}`, {}), i);
      });
      row.appendChild(quickBtn);
    } else {
      const meta = el("div", "lead-meta");
      meta.appendChild(el("span", `state-chip cat-${lead.category}`, CHIP[lead.category] || CHIP.waiting));
      if (lead.last_message_at) meta.appendChild(el("span", "lead-time", lead.last_message_at));
      row.appendChild(meta);
      if (lead.preview) row.appendChild(el("div", "lead-preview", lead.preview));
    }

    row.addEventListener("click", () => selectLead(i));
    list.appendChild(row);
  });
}

// ---------- detail ----------
async function selectLead(i) {
  if (i < 0 || i >= state.leads.length) return;
  state.selected = i;
  state.translated = false;
  state.englishSegments = null;
  renderList();
  const row = document.querySelector(`.lead-row[data-index="${i}"]`);
  if (row) row.scrollIntoView({ block: "nearest" });

  const lead = state.leads[i];
  $("detail-empty").hidden = true;
  const body = $("detail-body");
  body.hidden = false;
  body.innerHTML = '<div class="loading-note"><span class="spinner"></span>Loading conversation…</div>';

  try {
    const data = await apiGet(`/api/leads/${lead.campaign_id}/${lead.lead_id}`);
    state.detail = data;
    renderDetail();
  } catch (e) {
    body.innerHTML = `<div class="error-note">Couldn't load this lead: ${e.message}</div>`;
  }
}

function renderDetail() {
  const { lead, thread } = state.detail;
  const body = $("detail-body");
  body.innerHTML = "";

  const header = el("div", "detail-header");
  header.appendChild(el("h2", null, lead.name));
  if (lead.language) header.appendChild(el("span", "lang-badge", lead.language));
  header.appendChild(el("span", `state-chip cat-${lead.category}`, CHIP[lead.category] || CHIP.waiting));
  body.appendChild(header);
  body.appendChild(el("div", "detail-sub", [lead.company, lead.email].filter(Boolean).join(" · ")));

  body.appendChild(renderLeadActionsBar(lead));

  // translate toggle
  const tools = el("div", "thread-tools");
  const tbtn = el("button", "btn-secondary", "Translate to English");
  tbtn.id = "translate-btn";
  tbtn.addEventListener("click", toggleTranslate);
  tools.appendChild(tbtn);
  body.appendChild(tools);

  // thread
  const tc = el("div", "thread");
  tc.id = "thread";
  thread.forEach((m, idx) => {
    const wrap = el("div", `msg ${m.who}`);
    wrap.appendChild(el("div", "msg-meta", `${m.name} · ${m.time}`));
    const bubble = el("div", "bubble");
    bubble.dataset.index = idx;
    bubble.dataset.original = m.html;
    bubble.innerHTML = m.html;
    wrap.appendChild(bubble);
    tc.appendChild(wrap);
  });
  body.appendChild(tc);

  renderDraftSection(body);
}

function renderLeadActionsBar(lead) {
  const bar = el("div", "lead-actions");

  if (lead.archive_reason) {
    const label = lead.archive_reason === "not_interested" ? "Marked Not Interested" : "Archived";
    bar.appendChild(el("span", "status-banner", label + (lead.archived_at ? " · " + lead.archived_at : "")));
    const restore = el("button", "btn-secondary", "Restore to inbox");
    restore.addEventListener("click", () => withRowRemoval(() => {
      const ids = currentLeadIds();
      return apiPost(`/api/leads/${ids.cid}/${ids.lid}/unarchive`, {});
    }));
    bar.appendChild(restore);
    return bar;
  }

  if (lead.snooze_until && lead.snooze_until > todayStr()) {
    bar.appendChild(el("span", "status-banner", `Snoozed until ${lead.snooze_until}`));
    const now = el("button", "btn-secondary", "Follow up now");
    now.addEventListener("click", () => withRowRemoval(() => {
      const ids = currentLeadIds();
      return apiPost(`/api/leads/${ids.cid}/${ids.lid}/unsnooze`, {});
    }));
    bar.appendChild(now);
    return bar;
  }

  const archiveBtn = el("button", "btn-secondary", "Archive");
  archiveBtn.addEventListener("click", archiveLead);
  bar.appendChild(archiveBtn);

  const niBtn = el("button", "btn-secondary", "Not interested");
  niBtn.addEventListener("click", markNotInterested);
  bar.appendChild(niBtn);

  const snoozeWrap = el("div", "snooze-control");
  const snoozeBtn = el("button", "btn-secondary", "Snooze…");
  const picker = el("span", "snooze-picker");
  picker.hidden = true;
  const dateInput = el("input");
  dateInput.type = "date";
  dateInput.min = todayStr();
  const confirmBtn = el("button", "btn-secondary", "Confirm");
  const cancelBtn = el("button", "btn-secondary", "Cancel");
  snoozeBtn.addEventListener("click", () => { picker.hidden = false; snoozeBtn.hidden = true; });
  cancelBtn.addEventListener("click", () => { picker.hidden = true; snoozeBtn.hidden = false; });
  confirmBtn.addEventListener("click", () => {
    if (!dateInput.value) { alert("Pick a date first."); return; }
    snoozeLead(dateInput.value);
  });
  picker.appendChild(dateInput);
  picker.appendChild(confirmBtn);
  picker.appendChild(cancelBtn);
  snoozeWrap.appendChild(snoozeBtn);
  snoozeWrap.appendChild(picker);
  bar.appendChild(snoozeWrap);

  return bar;
}

function currentLeadIds() {
  const lead = currentLead();
  return { cid: lead.campaign_id, lid: lead.lead_id };
}

async function markNotInterested() {
  if (!confirm("Mark as Not Interested in Smartlead and pause their sequence? This removes them from your inbox.")) return;
  const { cid, lid } = currentLeadIds();
  await withRowRemoval(() => apiPost(`/api/leads/${cid}/${lid}/not-interested`, {}));
}

async function archiveLead() {
  const { cid, lid } = currentLeadIds();
  await withRowRemoval(() => apiPost(`/api/leads/${cid}/${lid}/archive`, {}));
}

async function snoozeLead(dateStr) {
  const { cid, lid } = currentLeadIds();
  await withRowRemoval(() => apiPost(`/api/leads/${cid}/${lid}/snooze`, { until: dateStr }));
}

function renderDraftSection(body) {
  const draft = state.detail.draft;
  const section = el("div");
  section.id = "draft-section";

  if (!draft) {
    const prompt = el("div", "generate-prompt");
    const gbtn = el("button", "btn-send", "Generate draft");
    gbtn.addEventListener("click", () => generate($("gen-note-input").value));
    prompt.appendChild(gbtn);
    const note = el("label", "gen-note");
    const input = el("input");
    input.type = "text";
    input.id = "gen-note-input";
    input.placeholder = "Optional: steer the draft (e.g. focus on pricing objection)";
    note.appendChild(input);
    prompt.appendChild(note);
    section.appendChild(prompt);
    body.appendChild(section);
    return;
  }

  const box = el("div", "draft-box");
  box.appendChild(el("h3", null, "Draft reply"));

  const editor = el("div", "draft-editor");
  editor.id = "draft-editor";
  editor.contentEditable = "true";
  editor.innerHTML = draft.body_html;
  box.appendChild(editor);

  if (draft.body_translation) {
    const det = el("details", "translation");
    det.appendChild(el("summary", null, "English preview"));
    det.appendChild(el("div", "translation-body", draft.body_translation));
    box.appendChild(det);
  }

  const actions = el("div", "actions");
  const sendBtn = el("button", "btn-send", "Send now");
  sendBtn.addEventListener("click", () => sendDraft(draft.id));
  actions.appendChild(sendBtn);

  const dt = el("input");
  dt.type = "datetime-local";
  dt.id = "schedule-at";
  actions.appendChild(dt);
  const schedBtn = el("button", "btn-secondary", "Schedule");
  schedBtn.addEventListener("click", () => scheduleDraft(draft.id));
  actions.appendChild(schedBtn);

  const noteInput = el("input");
  noteInput.type = "text";
  noteInput.id = "regen-note";
  noteInput.placeholder = "Steer regeneration (optional)";
  actions.appendChild(noteInput);
  const regenBtn = el("button", "btn-secondary", "Regenerate");
  regenBtn.addEventListener("click", () => generate(noteInput.value));
  actions.appendChild(regenBtn);

  const skipBtn = el("button", "btn-secondary", "Skip");
  skipBtn.addEventListener("click", () => skipDraft(draft.id));
  actions.appendChild(skipBtn);

  const stopBtn = el("button", "btn-danger", "Stop following up");
  stopBtn.addEventListener("click", () => stopLead(draft.id));
  actions.appendChild(stopBtn);

  box.appendChild(actions);
  section.appendChild(box);
  body.appendChild(section);
}

// ---------- translate ----------
async function toggleTranslate() {
  const btn = $("translate-btn");
  const bubbles = document.querySelectorAll("#thread .bubble");
  if (state.translated) {
    bubbles.forEach((b) => (b.innerHTML = b.dataset.original));
    state.translated = false;
    btn.textContent = "Translate to English";
    return;
  }
  const { cid, lid } = currentLeadIds();
  btn.disabled = true;
  btn.textContent = "Translating…";
  try {
    if (!state.englishSegments) {
      const data = await apiPost(`/api/leads/${cid}/${lid}/translate`, {});
      state.englishSegments = data.segments;
    }
    bubbles.forEach((b) => {
      const seg = state.englishSegments[Number(b.dataset.index)];
      if (seg != null) b.innerHTML = seg;
    });
    state.translated = true;
    btn.textContent = "Show original";
  } catch (e) {
    btn.textContent = "Translate to English";
    alert("Translation failed: " + e.message);
  } finally {
    btn.disabled = false;
  }
}

// ---------- generate / regenerate ----------
async function generate(note) {
  const { cid, lid } = currentLeadIds();
  const section = $("draft-section");
  section.innerHTML = '<div class="loading-note"><span class="spinner"></span>Writing the draft — researching the lead, this can take up to a minute…</div>';
  try {
    const data = await apiPost(`/api/leads/${cid}/${lid}/generate`, { steering_note: note || "" });
    state.detail.draft = data.draft;
    currentLead().has_draft = true;
    renderList();
    const body = $("detail-body");
    $("draft-section").remove();
    renderDraftSection(body);
  } catch (e) {
    section.innerHTML = `<div class="error-note">Generation failed: ${e.message}</div>`;
  }
}

// ---------- draft actions ----------
function editorHtml() {
  const ed = $("draft-editor");
  return ed ? ed.innerHTML : "";
}

async function sendDraft(id) {
  await withRowRemoval(() => apiPost(`/api/drafts/${id}/send`, { body_html: editorHtml() }));
}
async function skipDraft(id) {
  await withRowRemoval(() => apiPost(`/api/drafts/${id}/skip`, {}));
}
async function stopLead(id) {
  if (!confirm("Stop all automated follow-ups for this lead?")) return;
  await withRowRemoval(() => apiPost(`/api/drafts/${id}/stop`, {}));
}
async function scheduleDraft(id) {
  const at = $("schedule-at").value;
  if (!at) { alert("Pick a date/time first."); return; }
  try {
    await apiPost(`/api/drafts/${id}/schedule`, { body_html: editorHtml(), scheduled_at: at });
    await withRowRemoval(async () => {});
  } catch (e) {
    alert("Schedule failed: " + e.message);
  }
}

// Run an action, then fade+remove the affected lead row. If it was the
// selected row, auto-advance selection to the next one; otherwise just
// shift the selection index to account for the removed row.
async function withRowRemoval(action, index = state.selected) {
  const i = index;
  try {
    await action();
  } catch (e) {
    alert(e.message);
    return;
  }
  const row = document.querySelector(`.lead-row[data-index="${i}"]`);
  if (row) row.classList.add("sent-out");
  setTimeout(() => {
    const wasSelected = i === state.selected;
    state.leads.splice(i, 1);
    if (i < state.snoozedCount) state.snoozedCount -= 1;

    if (!wasSelected) {
      if (i < state.selected) state.selected -= 1;
      renderList();
      return;
    }
    if (state.leads.length === 0) {
      state.selected = -1;
      renderList();
      $("detail-body").hidden = true;
      $("detail-empty").hidden = false;
      return;
    }
    const next = Math.min(i, state.leads.length - 1);
    selectLead(next);
  }, 320);
}

// ---------- rescan ----------
let scanPoll = null;
async function rescan() {
  const btn = $("rescan-btn");
  btn.disabled = true;
  try {
    await apiPost("/api/scan/trigger", {});
    $("scan-status").textContent = "↻ scanning…";
    if (scanPoll) clearInterval(scanPoll);
    scanPoll = setInterval(async () => {
      const data = await loadInbox();
      if (!data.scan_running) {
        clearInterval(scanPoll);
        scanPoll = null;
        btn.disabled = false;
        $("scan-status").textContent = "";
      }
    }, 4000);
  } catch (e) {
    btn.disabled = false;
    alert("Rescan failed: " + e.message);
  }
}

// ---------- keyboard ----------
document.addEventListener("keydown", (e) => {
  if (e.target && /^(INPUT|TEXTAREA)$/.test(e.target.tagName)) return;
  if (e.target && e.target.isContentEditable) return;
  if (e.key === "ArrowDown") {
    e.preventDefault();
    selectLead(state.selected < 0 ? 0 : Math.min(state.selected + 1, state.leads.length - 1));
  } else if (e.key === "ArrowUp") {
    e.preventDefault();
    selectLead(Math.max(state.selected - 1, 0));
  }
});

// ---------- init ----------
$("rescan-btn").addEventListener("click", rescan);
$("archive-toggle-btn").addEventListener("click", () => setView(state.view === "archive" ? "inbox" : "archive"));
loadInbox().catch((e) => {
  $("scan-status").textContent = "load failed";
  console.error(e);
});
