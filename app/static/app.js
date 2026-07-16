"use strict";

const state = {
  view: "inbox",        // "inbox" | "archive"
  allLeads: [],          // full inbox as loaded from the server, unfiltered
  leads: [],              // filtered view actually rendered (search + category)
  searchQuery: "",
  categoryFilter: new Set(["reply", "followup", "auto_reply", "waiting"]),
  snoozedCount: 0,       // archive view only: state.leads[0..snoozedCount) are snoozed, rest archived
  selected: -1,
  detail: null,          // current lead detail {lead, thread, draft}
  categoryList: null,    // live Smartlead categories, for the "Change status" dropdown
};

const CHIP = {
  reply: "Awaiting your reply",
  followup: "Follow-up due",
  auto_reply: "Auto-reply — nudge",
  waiting: "In conversation",
};

const DEFAULT_CATEGORIES = [
  "Not Interested", "Meeting Request", "Do Not Contact", "Information Request",
  "Out Of Office", "Wrong Person", "Uncategorizable by Ai", "Sender Originated Bounce",
  "Meeting-Booked", "Interested for Video", "Auto-Reply", "Lead Opted Out",
  "We opted Out", "Contact later", "Redirect", "Lead Done", "Interested for Toolkit",
  "Interested for Calculator",
];

const PAUSE_CATEGORIES = new Set(["Not Interested", "Do Not Contact", "Wrong Person", "Lead Opted Out", "We opted Out"]);

// Keep in sync with drafter.ALLOWED_MODELS. Haiku listed first so it's the
// <select>'s default (browsers pre-select the first <option>) — cheapest
// model, used unless explicitly switched to something else.
const MODEL_OPTIONS = [
  { value: "claude-haiku-4-5", label: "Haiku 4.5 (default, cheap/fast)" },
  { value: "claude-sonnet-5", label: "Sonnet 5" },
  { value: "claude-opus-4-8", label: "Opus 4.8 (best quality)" },
];

// Canned, pre-approved follow-up one-liners. Picking one skips the full
// Claude drafter (system prompt, knowledge base, web tools) entirely and just
// runs one cheap translation call server-side — see /quick-draft.
const QUICK_FOLLOWUPS = [
  "Wanted to make sure you saw this, let me know either way",
  "Hey {name}, I'm locking in projects for next week, let me know if you'd like to move forward or if the timing changed",
  "{name} - just bumping this up in case it got buried. No rush at all",
  "Hey {name}, just checking in on this. Let me know if there's anything I can help clarify.",
  "Hi {name}, closing this file, it seems that now is not the right time. No worries though, it happens. Wishing you and your company all the best.",
  "{name} - please give me your thoughts on this",
];

async function loadCategories() {
  try {
    const data = await apiGet("/api/categories");
    state.categoryList = data.categories.filter((c) => c !== "Interested");
  } catch (e) {
    state.categoryList = DEFAULT_CATEGORIES;
  }
}

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
  state.allLeads = data.leads;
  state.snoozedCount = 0;
  applyFilter();
  $("scan-status").textContent = data.scan_running ? "↻ scanning…" : "";
  return data;
}

function matchesSearch(lead, query) {
  if (!query) return true;
  const haystack = `${lead.name || ""} ${lead.company || ""} ${lead.email || ""}`.toLowerCase();
  return haystack.includes(query);
}

function applyFilter() {
  const query = state.searchQuery.trim().toLowerCase();
  state.leads = state.allLeads.filter(
    (l) => state.categoryFilter.has(l.category) && matchesSearch(l, query)
  );
  renderList();
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
      const reason = isSnoozed ? `Snoozed until ${lead.snooze_until}` : archiveLabel(lead.archive_reason);
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
    if (data.generating) pollGeneration(lead.campaign_id, lead.lead_id);
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

  body.appendChild(renderResearchPanel(lead));
  body.appendChild(renderLeadActionsBar(lead));

  // thread — each message gets its own Translate button (per-message, not
  // the whole thread at once) so a click only pays for what's actually read.
  const tc = el("div", "thread");
  tc.id = "thread";
  thread.forEach((m, idx) => {
    const wrap = el("div", `msg ${m.who}`);
    const meta = el("div", "msg-meta");
    meta.appendChild(document.createTextNode(`${m.name} · ${m.time} `));
    const tbtn = el("button", "btn-translate-msg", "Translate");
    tbtn.type = "button";
    meta.appendChild(tbtn);
    wrap.appendChild(meta);
    const bubble = el("div", "bubble");
    bubble.dataset.index = idx;
    bubble.dataset.original = m.html;
    bubble.dataset.mode = "orig";
    bubble.innerHTML = m.html;
    tbtn.addEventListener("click", () => toggleMessageTranslate(bubble, tbtn, idx));
    wrap.appendChild(bubble);
    tc.appendChild(wrap);
  });
  body.appendChild(tc);

  renderDraftSection(body);
}

function archiveLabel(reason) {
  if (!reason || reason === "manual") return "Archived";
  return reason; // an actual Smartlead category name, e.g. "Wrong Person"
}

// Captured once during drafting (Claude's <lead_research> block, see
// drafter.py) and reused on later drafts instead of re-researching the
// lead's website — shown here so it's always visible next to the thread.
function renderResearchPanel(lead) {
  const panel = el("div", "research-panel");
  panel.id = "research-panel";
  const head = el("div", "research-head");
  head.appendChild(el("span", "research-title", "About this lead"));
  if (lead.researched_at) head.appendChild(el("span", "muted research-time", lead.researched_at));
  panel.appendChild(head);
  panel.appendChild(
    el(
      "div",
      "research-body",
      lead.research_summary || "No research yet — gathered automatically the first time a draft is generated for this lead."
    )
  );
  return panel;
}

function renderLeadActionsBar(lead) {
  const bar = el("div", "lead-actions");

  if (lead.archive_reason) {
    const label = archiveLabel(lead.archive_reason);
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

  bar.appendChild(renderCategorySelect());

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

function renderCategorySelect() {
  const select = el("select", "cat-select");
  select.title = "Change status in Smartlead";
  const placeholder = document.createElement("option");
  placeholder.textContent = "Change status…";
  placeholder.value = "";
  placeholder.disabled = true;
  placeholder.selected = true;
  select.appendChild(placeholder);
  (state.categoryList || DEFAULT_CATEGORIES).forEach((name) => {
    const opt = document.createElement("option");
    opt.value = name;
    opt.textContent = name;
    select.appendChild(opt);
  });
  select.addEventListener("change", () => {
    const name = select.value;
    select.value = "";
    if (name) changeCategory(name);
  });
  return select;
}

async function changeCategory(name) {
  const pauseNote = PAUSE_CATEGORIES.has(name) ? " and pause their sequence" : "";
  if (!confirm(`Set Smartlead category to "${name}"${pauseNote}? This removes them from your inbox.`)) return;
  const { cid, lid } = currentLeadIds();
  await withRowRemoval(() => apiPost(`/api/leads/${cid}/${lid}/category`, { category_name: name }));
}

async function archiveLead() {
  const { cid, lid } = currentLeadIds();
  await withRowRemoval(() => apiPost(`/api/leads/${cid}/${lid}/archive`, {}));
}

async function snoozeLead(dateStr) {
  const { cid, lid } = currentLeadIds();
  await withRowRemoval(() => apiPost(`/api/leads/${cid}/${lid}/snooze`, { until: dateStr }));
}

// Shared by the "Generate draft" prompt and the "Regenerate" row (never both
// on screen at once, so the element ids are safe to reuse). Web search
// defaults off once we already have research for this lead — it was only
// ever a prompt-level suggestion before, so Claude could still burn tokens
// re-running it; now the toggle controls whether the tools are even sent.
function renderGenControls() {
  const wrap = el("div", "gen-controls");

  const modelLabel = el("label", "gen-model");
  const select = document.createElement("select");
  select.id = "gen-model-select";
  MODEL_OPTIONS.forEach((opt) => {
    const o = document.createElement("option");
    o.value = opt.value;
    o.textContent = opt.label;
    select.appendChild(o);
  });
  modelLabel.appendChild(select);
  wrap.appendChild(modelLabel);

  const wsLabel = el("label", "gen-websearch");
  const wsCheckbox = document.createElement("input");
  wsCheckbox.type = "checkbox";
  wsCheckbox.id = "gen-websearch-toggle";
  wsCheckbox.checked = !state.detail.lead.research_summary;
  wsLabel.appendChild(wsCheckbox);
  wsLabel.appendChild(document.createTextNode(" Web search"));
  wrap.appendChild(wsLabel);

  return wrap;
}

function renderQuickFollowups() {
  const wrap = el("div", "quick-followups");
  wrap.appendChild(el("div", "quick-followups-label", "Quick follow-up (skips generation, just translates):"));
  const list = el("div", "quick-followups-list");
  QUICK_FOLLOWUPS.forEach((tpl) => {
    const label = tpl.length > 50 ? tpl.slice(0, 47) + "…" : tpl;
    const btn = el("button", "btn-secondary btn-quick", label);
    btn.type = "button";
    btn.title = tpl;
    btn.addEventListener("click", () => quickFollowup(tpl));
    list.appendChild(btn);
  });
  wrap.appendChild(list);
  return wrap;
}

async function quickFollowup(template) {
  const { cid, lid } = currentLeadIds();
  const firstName = (state.detail.lead.name || "").split(" ")[0] || "there";
  const text = template.replace(/\{name\}/g, firstName);
  const section = $("draft-section");
  section.innerHTML = '<div class="loading-note"><span class="spinner"></span>Adding follow-up…</div>';
  let data;
  try {
    data = await apiPost(`/api/leads/${cid}/${lid}/quick-draft`, { text });
  } catch (e) {
    section.innerHTML = `<div class="error-note">Could not add follow-up: ${e.message}</div>`;
    return;
  }
  state.detail = data;
  renderList();
  const body = $("detail-body");
  const oldPanel = $("research-panel");
  if (oldPanel) oldPanel.replaceWith(renderResearchPanel(state.detail.lead));
  $("draft-section").remove();
  renderDraftSection(body);
}

// ---------- editor formatting ----------
function escapeHtml(s) {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

function runEditorCommand(cmd, value) {
  const editor = $("draft-editor");
  editor.focus();
  document.execCommand(cmd, false, value);
  onEditorInput();
}

function insertLink() {
  const editor = $("draft-editor");
  editor.focus();
  const url = window.prompt("Link URL (include https://):");
  if (!url) return;
  const sel = window.getSelection();
  if (!sel || sel.isCollapsed || !editor.contains(sel.anchorNode)) {
    document.execCommand("insertHTML", false, `<a href="${escapeHtml(url)}" target="_blank" rel="noopener">${escapeHtml(url)}</a>`);
  } else {
    document.execCommand("createLink", false, url);
  }
  onEditorInput();
}

function insertImageUrl() {
  const editor = $("draft-editor");
  editor.focus();
  const url = window.prompt("Image URL (must already be hosted somewhere public — this inserts a link to it, not an upload):");
  if (!url) return;
  document.execCommand("insertHTML", false, `<img src="${escapeHtml(url)}" style="max-width:100%;">`);
  onEditorInput();
}

function renderEditorToolbar() {
  const bar = el("div", "editor-toolbar");
  bar.id = "editor-toolbar";
  const boldBtn = el("button", "toolbar-btn toolbar-bold", "B");
  boldBtn.type = "button";
  boldBtn.title = "Bold";
  boldBtn.addEventListener("click", () => runEditorCommand("bold"));
  const italicBtn = el("button", "toolbar-btn toolbar-italic", "I");
  italicBtn.type = "button";
  italicBtn.title = "Italic";
  italicBtn.addEventListener("click", () => runEditorCommand("italic"));
  const linkBtn = el("button", "toolbar-btn", "Link");
  linkBtn.type = "button";
  linkBtn.title = "Insert link";
  linkBtn.addEventListener("click", insertLink);
  const imgBtn = el("button", "toolbar-btn", "Image");
  imgBtn.type = "button";
  imgBtn.title = "Insert image from a URL";
  imgBtn.addEventListener("click", insertImageUrl);
  [boldBtn, italicBtn, linkBtn, imgBtn].forEach((b) => bar.appendChild(b));
  return bar;
}

function renderDraftSection(body) {
  const draft = state.detail.draft;
  const section = el("div");
  section.id = "draft-section";

  if (!draft) {
    if (state.detail.generating) {
      section.innerHTML = '<div class="loading-note"><span class="spinner"></span>Writing the draft — researching the lead, this can take a few minutes…</div>';
      body.appendChild(section);
      return;
    }
    const prompt = el("div", "generate-prompt");
    if (state.detail.lead.category === "followup") {
      prompt.appendChild(renderQuickFollowups());
    }
    prompt.appendChild(renderGenControls());
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

  // Fresh editor state for this draft. englishHtml stays null until the
  // English tab is actually opened, so it's always translated from whatever
  // is currently in the Original box rather than a stale generation-time value.
  state.editMode = "original";
  state.originalHtml = draft.body_html;
  state.englishHtml = null;

  const box = el("div", "draft-box");
  box.appendChild(el("h3", null, "Draft reply"));

  const tabs = el("div", "edit-tabs");
  const origTab = el("button", "edit-tab active", "Original");
  origTab.id = "tab-original";
  origTab.type = "button";
  const enTab = el("button", "edit-tab", "English");
  enTab.id = "tab-english";
  enTab.type = "button";
  origTab.addEventListener("click", () => setEditMode("original"));
  enTab.addEventListener("click", () => setEditMode("english"));
  tabs.appendChild(origTab);
  tabs.appendChild(enTab);
  box.appendChild(tabs);

  // Formatting only applies on the Original tab — the English tab is a
  // plain-text round trip through Sonnet (api_draft_localize strips HTML
  // before translating back), so bold/links typed there wouldn't survive
  // "Apply to draft" anyway. Hidden, not removed, so setEditMode can toggle it.
  box.appendChild(renderEditorToolbar());

  const editor = el("div", "draft-editor");
  editor.id = "draft-editor";
  editor.contentEditable = "true";
  editor.innerHTML = draft.body_html;
  editor.addEventListener("input", onEditorInput);
  box.appendChild(editor);

  const applyRow = el("div", "apply-row");
  applyRow.id = "apply-row";
  applyRow.hidden = true;
  const applyBtn = el("button", "btn-send", "Apply to draft");
  applyBtn.id = "apply-btn";
  applyBtn.type = "button";
  applyBtn.addEventListener("click", applyEnglishEdit);
  applyRow.appendChild(applyBtn);
  applyRow.appendChild(el("span", "muted", "Rewrites the outgoing message in the lead's language (Sonnet)."));
  box.appendChild(applyRow);

  if (draft.signature_html) {
    const sig = el("div", "signature-preview");
    sig.id = "signature-preview";
    sig.innerHTML = draft.signature_html;
    box.appendChild(sig);
  }

  box.appendChild(renderGenControls());

  const actions = el("div", "actions");
  const sendBtn = el("button", "btn-send", "Send now");
  sendBtn.id = "send-btn";
  sendBtn.addEventListener("click", () => sendDraft(draft.id));
  actions.appendChild(sendBtn);

  const dt = el("input");
  dt.type = "datetime-local";
  dt.id = "schedule-at";
  actions.appendChild(dt);
  const schedBtn = el("button", "btn-secondary", "Schedule");
  schedBtn.id = "schedule-btn";
  schedBtn.addEventListener("click", () => scheduleDraft(draft.id));
  actions.appendChild(schedBtn);

  const noteInput = el("input");
  noteInput.type = "text";
  noteInput.id = "regen-note";
  noteInput.placeholder = "Steer regeneration (optional)";
  actions.appendChild(noteInput);
  const regenBtn = el("button", "btn-secondary", "Regenerate");
  regenBtn.id = "regen-btn";
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

function onEditorInput() {
  const editor = $("draft-editor");
  if (state.editMode === "original") {
    state.originalHtml = editor.innerHTML;
    state.englishHtml = null; // invalidate — refetch fresh next time English is viewed
  } else {
    state.englishHtml = editor.innerHTML;
  }
}

function toggleActionButtons(enabled) {
  ["send-btn", "schedule-btn", "regen-btn"].forEach((id) => {
    const b = $(id);
    if (b) b.disabled = !enabled;
  });
}

async function setEditMode(mode, opts = {}) {
  if (mode === state.editMode) return;
  const editor = $("draft-editor");
  if (!opts.skipStash) {
    if (state.editMode === "original") state.originalHtml = editor.innerHTML;
    else state.englishHtml = editor.innerHTML;
  }
  state.editMode = mode;
  $("tab-original").classList.toggle("active", mode === "original");
  $("tab-english").classList.toggle("active", mode === "english");
  if ($("signature-preview")) $("signature-preview").hidden = mode === "english";
  $("apply-row").hidden = mode !== "english";
  if ($("editor-toolbar")) $("editor-toolbar").hidden = mode !== "original";
  toggleActionButtons(mode === "original");

  if (mode === "english" && state.englishHtml == null) {
    editor.setAttribute("contenteditable", "false");
    editor.innerHTML = '<span class="muted"><span class="spinner"></span>Translating…</span>';
    try {
      const data = await apiPost(`/api/drafts/${state.detail.draft.id}/translate`, {
        original_html: state.originalHtml,
      });
      state.englishHtml = data.english_html;
    } catch (e) {
      editor.innerHTML = `<span class="error-note">Translation failed: ${e.message}</span>`;
      editor.setAttribute("contenteditable", "true");
      return;
    }
    editor.setAttribute("contenteditable", "true");
  }

  editor.innerHTML = mode === "original" ? state.originalHtml : state.englishHtml;
}

async function applyEnglishEdit() {
  const editor = $("draft-editor");
  const englishHtml = editor.innerHTML;
  const btn = $("apply-btn");
  btn.disabled = true;
  btn.textContent = "Rewriting in the lead's language…";
  try {
    const data = await apiPost(`/api/drafts/${state.detail.draft.id}/localize`, {
      english_html: englishHtml,
    });
    state.detail.draft = data.draft;
    state.originalHtml = data.draft.body_html;
    state.englishHtml = englishHtml; // exactly what was just approved
    await setEditMode("original", { skipStash: true });
  } catch (e) {
    alert("Couldn't rewrite the draft: " + e.message);
  } finally {
    btn.disabled = false;
    btn.textContent = "Apply to draft";
  }
}

// ---------- translate ----------
// Per-message: each bubble caches its own translation on first click (in
// dataset.translatedHtml) so re-toggling the same message never re-calls
// the API. Only ever translates the one message clicked, not the thread.
async function toggleMessageTranslate(bubble, btn, index) {
  if (bubble.dataset.mode === "en") {
    bubble.innerHTML = bubble.dataset.original;
    bubble.dataset.mode = "orig";
    btn.textContent = "Translate";
    return;
  }
  const { cid, lid } = currentLeadIds();
  btn.disabled = true;
  btn.textContent = "Translating…";
  try {
    if (!bubble.dataset.translatedHtml) {
      const data = await apiPost(`/api/leads/${cid}/${lid}/translate`, { index });
      bubble.dataset.translatedHtml = data.html;
    }
    bubble.innerHTML = bubble.dataset.translatedHtml;
    bubble.dataset.mode = "en";
    btn.textContent = "Show original";
  } catch (e) {
    btn.textContent = "Translate";
    alert("Translation failed: " + e.message);
  } finally {
    btn.disabled = false;
  }
}

// ---------- generate / regenerate ----------
// generate_for_lead calls Claude with web search/fetch tools and can take
// minutes — long enough to hit Cloudflare's ~100s tunnel timeout if held
// open as a single request (confirmed via a real 524 in production). The
// backend now kicks it off in a background thread and reports progress via
// `generating` on GET /api/leads/{cid}/{lid}; poll that instead of awaiting
// one long POST. Keyed by lead so generating on one lead doesn't stop a poll
// already running for another.
const genPolls = new Map();

function pollGeneration(cid, lid) {
  const key = `${cid}:${lid}`;
  if (genPolls.has(key)) return;

  const finish = (data, errorMessage) => {
    clearInterval(genPolls.get(key));
    genPolls.delete(key);
    const lead = state.leads.find((l) => l.campaign_id === cid && l.lead_id === lid);
    if (lead && data && data.draft) lead.has_draft = true;

    const cur = currentLeadIds();
    if (!cur || cur.cid !== cid || cur.lid !== lid) {
      if (lead) renderList();
      return; // user is looking at a different lead now — don't touch its DOM
    }
    const body = $("detail-body");
    const oldSection = $("draft-section");
    if (errorMessage) {
      const s = el("div");
      s.id = "draft-section";
      s.innerHTML = `<div class="error-note">${errorMessage}</div>`;
      if (oldSection) oldSection.replaceWith(s); else body.appendChild(s);
      return;
    }
    state.detail = data;
    renderList();
    const oldPanel = $("research-panel");
    if (oldPanel) oldPanel.replaceWith(renderResearchPanel(state.detail.lead));
    if (oldSection) oldSection.remove();
    renderDraftSection(body);
  };

  const interval = setInterval(async () => {
    let data;
    try {
      data = await apiGet(`/api/leads/${cid}/${lid}`);
    } catch (e) {
      finish(null, `Generation failed: ${e.message}`);
      return;
    }
    if (data.generating) return;
    finish(data, data.draft ? null : "Could not generate a draft for this lead.");
  }, 3000);
  genPolls.set(key, interval);
}

async function generate(note) {
  const { cid, lid } = currentLeadIds();
  // Read the model/web-search controls before wiping the section's innerHTML below.
  const modelSel = $("gen-model-select");
  const wsCheckbox = $("gen-websearch-toggle");
  const model = modelSel ? modelSel.value : "";
  const useWebSearch = wsCheckbox ? wsCheckbox.checked : true;

  const section = $("draft-section");
  section.innerHTML = '<div class="loading-note"><span class="spinner"></span>Writing the draft — researching the lead, this can take a few minutes…</div>';
  try {
    await apiPost(`/api/leads/${cid}/${lid}/generate`, {
      steering_note: note || "",
      model: model || undefined,
      use_web_search: useWebSearch,
    });
  } catch (e) {
    section.innerHTML = `<div class="error-note">Generation failed: ${e.message}</div>`;
    return;
  }
  pollGeneration(cid, lid);
}

// ---------- draft actions ----------
function editorHtml() {
  // Always the Original (native-language) content — never whatever happens to
  // be displayed in the shared editor at the moment, since that could be the
  // English tab. Send/Schedule are also disabled while on the English tab.
  return state.originalHtml || "";
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

// ---------- search + category filter ----------
$("lead-search").addEventListener("input", (e) => {
  state.searchQuery = e.target.value;
  applyFilter();
});

document.querySelectorAll(".legend-item").forEach((item) => {
  item.addEventListener("click", () => {
    const cat = item.dataset.category;
    if (state.categoryFilter.has(cat)) {
      state.categoryFilter.delete(cat);
      item.classList.add("off");
    } else {
      state.categoryFilter.add(cat);
      item.classList.remove("off");
    }
    applyFilter();
  });
});

// ---------- init ----------
$("rescan-btn").addEventListener("click", rescan);
$("archive-toggle-btn").addEventListener("click", () => setView(state.view === "archive" ? "inbox" : "archive"));
loadInbox().catch((e) => {
  $("scan-status").textContent = "load failed";
  console.error(e);
});
loadCategories();
