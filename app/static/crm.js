"use strict";

// ---------- CRM: the pipeline after a booked meeting (app/crm.py) ----------
//
// Loaded after app.js and uses its helpers ($, el, apiGet, apiPost, apiPatch,
// apiDelete, state, renderContactChannels, formatDayLabel, closeMobileMenu).
// The header's Outreach / CRM switch swaps the whole two-pane layout for
// #crm-page, which shows either the board or one deal's record.

const CRM_MODE_KEY = "responder.mode";

const crm = {
  board: null,        // /api/crm/board payload
  search: "",
  dealId: null,       // open record, or null for the board
  detail: null,       // /api/crm/deals/{id} payload
  lead: null,         // /api/leads/{cid}/{lid} payload for the open record (research + thread)
  dragId: null,
};

function setMode(mode) {
  if (typeof closeMobileMenu === "function") closeMobileMenu(true);
  state.mode = mode === "crm" ? "crm" : "outreach";
  const inCrm = state.mode === "crm";
  try { localStorage.setItem(CRM_MODE_KEY, state.mode); } catch (_) { /* private window */ }
  document.body.classList.toggle("crm-mode", inCrm);
  $("mode-outreach-btn").classList.toggle("active", !inCrm);
  $("mode-crm-btn").classList.toggle("active", inCrm);
  $("view-switch").hidden = inCrm;
  $("rescan-btn").hidden = inCrm || state.view !== "inbox";
  $("followup-settings-btn").hidden = inCrm;
  document.querySelector(".layout").hidden = inCrm;
  $("crm-page").hidden = !inCrm;
  if (inCrm) {
    if (crm.dealId) openCrmDeal(crm.dealId);
    else loadCrmBoard();
  } else if (state.view === "inbox") {
    loadInbox().catch((e) => console.error(e));
  }
}

// Called from the inbox's lead detail ("Add to CRM" / "Open in CRM").
function openCrmDealFromLead(dealId) {
  crm.dealId = dealId;
  setMode("crm");
}

function renderCrmLeadButton() {
  const deal = state.detail && state.detail.crm_deal;
  if (deal) {
    const btn = el("button", "btn-secondary crm-lead-btn in-crm", `In CRM · ${deal.stage_label} ↗`);
    btn.type = "button";
    btn.title = "Open this lead's CRM record";
    btn.addEventListener("click", () => openCrmDealFromLead(deal.id));
    return btn;
  }
  const btn = el("button", "btn-send crm-lead-btn", "+ Add to CRM");
  btn.type = "button";
  btn.title = "Put this lead on the CRM board, in the Meeting booked column";
  btn.addEventListener("click", async () => {
    const ids = currentLeadIds();
    btn.disabled = true;
    try {
      const data = await apiPost("/api/crm/deals", { campaign_id: ids.cid, lead_id: ids.lid });
      const stage = (data.stages || []).find((s) => s.key === data.deal.stage);
      state.detail.crm_deal = { id: data.id, stage: data.deal.stage, stage_label: stage ? stage.label : data.deal.stage };
      refreshLeadActions();
    } catch (e) {
      btn.disabled = false;
      alert("Couldn't add to CRM: " + e.message);
    }
  });
  return btn;
}

// ---------- small helpers ----------

function crmMoney(v) {
  if (v === null || v === undefined || v === "") return "";
  return Number(v).toLocaleString(undefined, { maximumFractionDigits: 2 });
}

function crmDaysSince(iso) {
  const t = new Date(iso).getTime();
  if (isNaN(t)) return null;
  return Math.max(0, Math.floor((Date.now() - t) / 86400000));
}

function crmWhen(iso) {
  const d = new Date(iso);
  if (isNaN(d)) return "";
  return d.toLocaleString(undefined, { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" });
}

function crmDueClass(due) {
  if (!due) return "";
  const today = localDateStr(new Date());
  if (due < today) return "overdue";
  if (due === today) return "due-today";
  return "";
}

function crmSection(title, extra) {
  const sec = el("section", "crm-section");
  const head = el("div", "crm-section-head");
  head.appendChild(el("h3", null, title));
  if (extra) head.appendChild(extra);
  sec.appendChild(head);
  return sec;
}

function crmInput(type, placeholder, cls) {
  const i = el("input", cls || "crm-input");
  i.type = type;
  if (placeholder) i.placeholder = placeholder;
  return i;
}

// ---------- board ----------

async function loadCrmBoard() {
  crm.dealId = null;
  crm.detail = null;
  const page = $("crm-page");
  if (!crm.board) page.innerHTML = '<div class="loading-note"><span class="spinner"></span>Loading pipeline…</div>';
  try {
    crm.board = await apiGet("/api/crm/board");
  } catch (e) {
    page.innerHTML = "";
    page.appendChild(el("div", "error-note", "Couldn't load the pipeline: " + e.message));
    return;
  }
  if (state.mode === "crm" && !crm.dealId) renderCrmBoard();
}

function crmMatches(deal) {
  const q = crm.search.trim().toLowerCase();
  if (!q) return true;
  return [deal.name, deal.company, deal.email, deal.campaign_name]
    .some((v) => (v || "").toLowerCase().includes(q));
}

function renderCrmBoard() {
  const page = $("crm-page");
  page.innerHTML = "";
  const { stages, deals } = crm.board;

  const bar = el("div", "crm-toolbar");
  bar.appendChild(el("h2", null, "Pipeline"));
  const search = crmInput("search", "Search deals…", "crm-input crm-search");
  search.value = crm.search;
  search.addEventListener("input", () => {
    crm.search = search.value;
    renderCrmColumns();
  });
  bar.appendChild(search);
  const add = el("button", "btn-send", "+ New deal");
  add.type = "button";
  add.addEventListener("click", () => toggleNewDealForm(page));
  bar.appendChild(add);
  page.appendChild(bar);

  const hint = el("div", "crm-hint muted small",
    "Every Meeting-booked lead lands in the first column on its own. Drag a card to move it, click it to open the record.");
  page.appendChild(hint);

  const boardEl = el("div", "crm-board");
  boardEl.id = "crm-board";
  page.appendChild(boardEl);
  renderCrmColumns();
  return { stages, deals };
}

function toggleNewDealForm(page) {
  const existing = $("crm-new-deal");
  if (existing) { existing.remove(); return; }
  const form = el("form", "crm-new-deal");
  form.id = "crm-new-deal";
  const name = crmInput("text", "Name");
  const company = crmInput("text", "Company");
  const email = crmInput("email", "Email (optional)");
  const stage = el("select", "crm-input");
  crm.board.stages.forEach((s) => stage.appendChild(new Option(s.label, s.key)));
  const save = el("button", "btn-send", "Create");
  save.type = "submit";
  [name, company, email, stage, save].forEach((n) => form.appendChild(n));
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    save.disabled = true;
    try {
      const data = await apiPost("/api/crm/deals", {
        name: name.value, company: company.value, email: email.value, stage: stage.value,
      });
      openCrmDeal(data.id);
    } catch (err) {
      save.disabled = false;
      alert(err.message);
    }
  });
  page.querySelector(".crm-toolbar").after(form);
  name.focus();
}

function renderCrmColumns() {
  const boardEl = $("crm-board");
  if (!boardEl) return;
  boardEl.innerHTML = "";
  const { stages, deals, today } = crm.board;
  stages.forEach((stage) => {
    const col = el("div", `crm-col crm-stage-${stage.key}`);
    const inStage = deals.filter((d) => d.stage === stage.key);
    const shown = inStage.filter(crmMatches);
    const head = el("div", "crm-col-head");
    head.appendChild(el("span", "crm-col-title", stage.label));
    head.appendChild(el("span", "crm-col-count", String(inStage.length)));
    col.appendChild(head);
    const total = inStage.reduce((sum, d) => sum + (Number(d.value) || 0), 0);
    if (total) col.appendChild(el("div", "crm-col-total muted small", `Total ${crmMoney(total)}`));

    const list = el("div", "crm-col-list");
    list.dataset.stage = stage.key;
    shown.forEach((d) => list.appendChild(renderCrmCard(d, today)));
    if (!shown.length) list.appendChild(el("div", "crm-col-empty muted small", crm.search ? "No matches" : "Drop a card here"));
    wireCrmDrop(list);
    col.appendChild(list);
    boardEl.appendChild(col);
  });
}

function renderCrmCard(deal, today) {
  const card = el("div", "crm-card");
  card.draggable = true;
  card.dataset.id = deal.id;
  card.tabIndex = 0;
  const top = el("div", "crm-card-top");
  top.appendChild(el("span", "crm-card-name", deal.name));
  if (deal.value) top.appendChild(el("span", "crm-card-value", crmMoney(deal.value)));
  card.appendChild(top);
  if (deal.company) card.appendChild(el("div", "crm-card-company", deal.company));
  if (deal.next_todo) {
    const due = deal.next_todo.due_date;
    const next = el("div", `crm-card-next ${crmDueClass(due)}`);
    next.textContent = `→ ${deal.next_todo.title}${due ? " · " + formatDayLabel(due) : ""}`;
    card.appendChild(next);
  }
  const meta = el("div", "crm-card-meta muted small");
  const days = crmDaysSince(deal.stage_changed_at);
  if (days !== null) meta.appendChild(el("span", null, days === 0 ? "moved today" : `${days}d in stage`));
  if (deal.open_todos) meta.appendChild(el("span", null, `${deal.open_todos} to-do${deal.open_todos === 1 ? "" : "s"}`));
  if (!deal.lead_id) meta.appendChild(el("span", null, "added by hand"));
  card.appendChild(meta);

  card.addEventListener("click", () => openCrmDeal(deal.id));
  card.addEventListener("keydown", (e) => { if (e.key === "Enter") openCrmDeal(deal.id); });
  card.addEventListener("dragstart", (e) => {
    crm.dragId = deal.id;
    card.classList.add("dragging");
    e.dataTransfer.effectAllowed = "move";
    e.dataTransfer.setData("text/plain", String(deal.id));
  });
  card.addEventListener("dragend", () => {
    card.classList.remove("dragging");
    crm.dragId = null;
    document.querySelectorAll(".crm-col-list.drop-target").forEach((n) => n.classList.remove("drop-target"));
    document.querySelectorAll(".crm-drop-marker").forEach((n) => n.remove());
  });
  return card;
}

// The card the dragged one should land in front of: the first whose middle is
// below the pointer. null = end of the column.
function crmCardAfter(list, y) {
  const cards = [...list.querySelectorAll(".crm-card:not(.dragging)")];
  return cards.find((c) => {
    const box = c.getBoundingClientRect();
    return y < box.top + box.height / 2;
  }) || null;
}

function wireCrmDrop(list) {
  list.addEventListener("dragover", (e) => {
    if (crm.dragId === null) return;
    e.preventDefault();
    list.classList.add("drop-target");
    const after = crmCardAfter(list, e.clientY);
    let marker = document.querySelector(".crm-drop-marker");
    if (!marker) marker = el("div", "crm-drop-marker");
    if (after) list.insertBefore(marker, after);
    else list.appendChild(marker);
  });
  list.addEventListener("dragleave", (e) => {
    if (!list.contains(e.relatedTarget)) {
      list.classList.remove("drop-target");
      const marker = list.querySelector(".crm-drop-marker");
      if (marker) marker.remove();
    }
  });
  list.addEventListener("drop", async (e) => {
    e.preventDefault();
    const id = crm.dragId;
    if (id === null) return;
    const after = crmCardAfter(list, e.clientY);
    const beforeId = after ? Number(after.dataset.id) : null;
    const stage = list.dataset.stage;

    // Optimistic: reorder locally, repaint, then tell the server.
    const deals = crm.board.deals;
    const moving = deals.find((d) => d.id === id);
    if (!moving) return;
    const changedStage = moving.stage !== stage;
    deals.splice(deals.indexOf(moving), 1);
    moving.stage = stage;
    if (changedStage) moving.stage_changed_at = new Date().toISOString();
    const anchor = beforeId !== null ? deals.findIndex((d) => d.id === beforeId) : -1;
    if (anchor >= 0) deals.splice(anchor, 0, moving);
    else deals.push(moving);
    renderCrmColumns();
    try {
      await apiPost(`/api/crm/deals/${id}/move`, { stage, before_id: beforeId });
    } catch (err) {
      alert("Couldn't move the deal: " + err.message);
      loadCrmBoard();
    }
  });
}

// ---------- one deal's record ----------

async function openCrmDeal(id) {
  crm.dealId = id;
  const page = $("crm-page");
  page.innerHTML = '<div class="loading-note"><span class="spinner"></span>Loading record…</div>';
  page.scrollTop = 0;
  try {
    crm.detail = await apiGet(`/api/crm/deals/${id}`);
  } catch (e) {
    page.innerHTML = "";
    page.appendChild(el("div", "error-note", "Couldn't load this deal: " + e.message));
    return;
  }
  crm.lead = null;
  renderCrmRecord();
  const deal = crm.detail.deal;
  if (deal.lead_id && deal.campaign_id) {
    try {
      const lead = await apiGet(`/api/leads/${deal.campaign_id}/${deal.lead_id}`);
      if (crm.dealId !== id) return;
      crm.lead = lead;
    } catch (e) {
      crm.lead = { error: e.message };
    }
    if (crm.dealId === id) renderCrmLeadSections();
  }
}

// Every mutating item route returns the whole fresh record.
async function crmMutate(promise) {
  try {
    crm.detail = await promise;
    renderCrmRecord({ keepLead: true });
  } catch (e) {
    alert(e.message);
  }
}

function renderCrmRecord({ keepLead = false } = {}) {
  const page = $("crm-page");
  const scroll = page.scrollTop;
  page.innerHTML = "";
  const { deal, items, stages } = crm.detail;

  const back = el("button", "btn-secondary crm-back", "← Pipeline");
  back.type = "button";
  back.addEventListener("click", () => loadCrmBoard());
  page.appendChild(back);

  // header: name, company, stage, value
  const head = el("div", "crm-record-head");
  const titles = el("div", "crm-record-titles");
  titles.appendChild(el("h2", null, deal.name));
  const sub = [deal.company, deal.email].filter(Boolean).join(" · ");
  if (sub) titles.appendChild(el("div", "muted", sub));
  if (deal.campaign_name) {
    const line = el("div", "campaign-line");
    line.appendChild(el("span", null, "Campaign:"));
    line.appendChild(el("span", "campaign-tag", deal.campaign_name));
    titles.appendChild(line);
  }
  head.appendChild(titles);

  const controls = el("div", "crm-record-controls");
  const stageLabel = el("label", "crm-field");
  stageLabel.appendChild(el("span", null, "Stage"));
  const stageSel = el("select", `crm-input crm-stage-select crm-stage-${deal.stage}`);
  stages.forEach((s) => stageSel.appendChild(new Option(s.label, s.key, false, s.key === deal.stage)));
  stageSel.addEventListener("change", () => {
    crmMutate(apiPatch(`/api/crm/deals/${deal.id}`, { stage: stageSel.value }));
  });
  stageLabel.appendChild(stageSel);
  controls.appendChild(stageLabel);

  const valueLabel = el("label", "crm-field");
  valueLabel.appendChild(el("span", null, "Deal value"));
  const value = crmInput("number", "0");
  value.step = "any";
  value.min = "0";
  value.value = deal.value ?? "";
  value.addEventListener("change", () => {
    crmMutate(apiPatch(`/api/crm/deals/${deal.id}`, { value: value.value }));
  });
  valueLabel.appendChild(value);
  controls.appendChild(valueLabel);
  head.appendChild(controls);
  page.appendChild(head);

  const since = crmDaysSince(deal.stage_changed_at);
  const facts = [];
  if (since !== null) facts.push(`In this stage ${since === 0 ? "since today" : `for ${since} day${since === 1 ? "" : "s"}`}`);
  if (deal.booked_at) facts.push(`Meeting booked ${crmWhen(deal.booked_at)}`);
  facts.push(`In CRM since ${crmWhen(deal.created_at)}`);
  page.appendChild(el("div", "crm-facts muted small", facts.join(" · ")));

  const grid = el("div", "crm-record-grid");
  const main = el("div", "crm-record-main");
  const side = el("div", "crm-record-side");
  grid.appendChild(main);
  grid.appendChild(side);
  page.appendChild(grid);

  main.appendChild(renderCrmTodos(deal, items));
  main.appendChild(renderCrmJournal(deal, items));
  side.appendChild(renderCrmContacts(deal, items));
  side.appendChild(renderCrmLinks(deal, items));

  const leadWrap = el("div", "crm-lead-sections");
  leadWrap.id = "crm-lead-sections";
  main.appendChild(leadWrap);

  const remove = el("button", "btn-danger crm-remove", "Remove from CRM");
  remove.type = "button";
  remove.addEventListener("click", async () => {
    if (!confirm(`Remove ${deal.name} from the CRM board? The lead stays in Outreach, and adding it back keeps its notes.`)) return;
    try {
      await apiDelete(`/api/crm/deals/${deal.id}`);
      loadCrmBoard();
    } catch (e) {
      alert(e.message);
    }
  });
  side.appendChild(remove);

  if (keepLead) renderCrmLeadSections();
  else if (deal.lead_id) leadWrap.appendChild(el("div", "loading-note", "Loading research and the cold-email thread…"));
  page.scrollTop = scroll;
}

function renderCrmTodos(deal, items) {
  const todos = items.filter((i) => i.kind === "todo");
  const open = todos.filter((t) => !t.done)
    .sort((a, b) => (a.due_date || "9999").localeCompare(b.due_date || "9999") || a.id - b.id);
  const done = todos.filter((t) => t.done);
  const sec = crmSection("Next steps · to-do");

  const form = el("form", "crm-add-row");
  const title = crmInput("text", "What needs to happen next?");
  const due = crmInput("date");
  due.title = "Due date (optional)";
  const add = el("button", "btn-send", "Add");
  add.type = "submit";
  [title, due, add].forEach((n) => form.appendChild(n));
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    if (!title.value.trim()) return;
    crmMutate(apiPost(`/api/crm/deals/${deal.id}/items`, { kind: "todo", title: title.value, due_date: due.value }));
  });
  sec.appendChild(form);

  const list = el("ul", "crm-todo-list");
  if (!open.length) list.appendChild(el("li", "muted small crm-empty", "Nothing planned. Add the next move above."));
  open.forEach((t) => list.appendChild(renderCrmTodo(t)));
  sec.appendChild(list);

  if (done.length) {
    const det = el("details", "crm-done");
    det.appendChild(el("summary", "muted small", `${done.length} done`));
    const dl = el("ul", "crm-todo-list");
    done.forEach((t) => dl.appendChild(renderCrmTodo(t)));
    det.appendChild(dl);
    sec.appendChild(det);
  }
  return sec;
}

function renderCrmTodo(t) {
  const li = el("li", `crm-todo ${t.done ? "done" : ""}`);
  const cb = el("input");
  cb.type = "checkbox";
  cb.checked = !!t.done;
  cb.addEventListener("change", () => crmMutate(apiPatch(`/api/crm/items/${t.id}`, { done: cb.checked })));
  li.appendChild(cb);
  li.appendChild(el("span", "crm-todo-title", t.title));
  const due = crmInput("date", null, `crm-input crm-todo-due ${t.done ? "" : crmDueClass(t.due_date)}`);
  due.value = t.due_date || "";
  due.title = "Due date";
  due.addEventListener("change", () => crmMutate(apiPatch(`/api/crm/items/${t.id}`, { due_date: due.value })));
  li.appendChild(due);
  li.appendChild(crmDeleteBtn(t.id, "Delete this to-do"));
  return li;
}

function crmDeleteBtn(itemId, label) {
  const x = el("button", "crm-x", "×");
  x.type = "button";
  x.title = label;
  x.setAttribute("aria-label", label);
  x.addEventListener("click", () => {
    if (!confirm(label + "?")) return;
    crmMutate(apiDelete(`/api/crm/items/${itemId}`));
  });
  return x;
}

function renderCrmJournal(deal, items) {
  const sec = crmSection("Journal");
  const form = el("form", "crm-note-form");
  const text = el("textarea", "crm-input crm-note-input");
  text.rows = 3;
  text.placeholder = "What happened? Call notes, what they said, what you agreed…";
  const add = el("button", "btn-send", "Add note");
  add.type = "submit";
  form.appendChild(text);
  form.appendChild(add);
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    if (!text.value.trim()) return;
    crmMutate(apiPost(`/api/crm/deals/${deal.id}/items`, { kind: "note", body: text.value }));
  });
  text.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) form.requestSubmit();
  });
  sec.appendChild(form);

  const entries = items.filter((i) => i.kind === "note" || i.kind === "event");
  const list = el("ul", "crm-journal");
  if (!entries.length) list.appendChild(el("li", "muted small crm-empty", "No entries yet."));
  entries.forEach((n) => {
    const li = el("li", `crm-entry crm-entry-${n.kind}`);
    const meta = el("div", "crm-entry-meta muted small", crmWhen(n.created_at));
    if (n.kind === "note") meta.appendChild(crmDeleteBtn(n.id, "Delete this note"));
    li.appendChild(meta);
    li.appendChild(el("div", "crm-entry-body", n.body));
    list.appendChild(li);
  });
  sec.appendChild(list);
  return sec;
}

function renderCrmContacts(deal, items) {
  const sec = crmSection("Contacts");
  const list = el("ul", "crm-contact-list");
  if (deal.email) {
    const li = el("li", "crm-contact");
    li.appendChild(el("div", "crm-contact-name", `${deal.name} (lead)`));
    const a = el("a", "small", deal.email);
    a.href = `mailto:${deal.email}`;
    li.appendChild(a);
    list.appendChild(li);
  }
  items.filter((i) => i.kind === "contact").reverse().forEach((c) => {
    const li = el("li", "crm-contact");
    const top = el("div", "crm-contact-name", c.title || "(no name)");
    if (c.body) top.appendChild(el("span", "muted small", ` · ${c.body}`));
    top.appendChild(crmDeleteBtn(c.id, "Delete this contact"));
    li.appendChild(top);
    if (c.email) {
      const a = el("a", "small", c.email);
      a.href = `mailto:${c.email}`;
      li.appendChild(a);
    }
    if (c.phone) {
      const a = el("a", "small", c.phone);
      a.href = `tel:${c.phone.replace(/[^0-9+]/g, "")}`;
      li.appendChild(a);
    }
    list.appendChild(li);
  });
  sec.appendChild(list);

  const det = el("details", "crm-add-details");
  det.appendChild(el("summary", "link-btn", "+ Add contact"));
  const form = el("form", "crm-stack-form");
  const name = crmInput("text", "Name");
  const role = crmInput("text", "Role (e.g. Owner, Office manager)");
  const email = crmInput("email", "Email");
  const phone = crmInput("tel", "Phone");
  const save = el("button", "btn-send", "Save contact");
  save.type = "submit";
  [name, role, email, phone, save].forEach((n) => form.appendChild(n));
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    crmMutate(apiPost(`/api/crm/deals/${deal.id}/items`, {
      kind: "contact", title: name.value, body: role.value, email: email.value, phone: phone.value,
    }));
  });
  det.appendChild(form);
  sec.appendChild(det);
  return sec;
}

function renderCrmLinks(deal, items) {
  const sec = crmSection("Links");
  const list = el("ul", "crm-link-list");
  items.filter((i) => i.kind === "link").reverse().forEach((l) => {
    const li = el("li", "crm-link");
    const a = el("a", null, l.title || l.url);
    a.href = l.url;
    a.target = "_blank";
    a.rel = "noopener noreferrer";
    li.appendChild(a);
    li.appendChild(crmDeleteBtn(l.id, "Delete this link"));
    list.appendChild(li);
  });
  if (!list.children.length) list.appendChild(el("li", "muted small crm-empty", "Proposal, contract, their website, call recording…"));
  sec.appendChild(list);

  const form = el("form", "crm-stack-form");
  const url = crmInput("text", "https://…");
  const label = crmInput("text", "Label (optional)");
  const save = el("button", "btn-secondary", "Add link");
  save.type = "submit";
  [url, label, save].forEach((n) => form.appendChild(n));
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    if (!url.value.trim()) return;
    crmMutate(apiPost(`/api/crm/deals/${deal.id}/items`, { kind: "link", url: url.value, title: label.value }));
  });
  sec.appendChild(form);
  return sec;
}

// Research + the cold-email thread come from the same payload the inbox uses,
// so the record shows exactly what Outreach shows.
function renderCrmLeadSections() {
  const wrap = $("crm-lead-sections");
  if (!wrap) return;
  wrap.innerHTML = "";
  const data = crm.lead;
  if (!data) return;
  if (data.error) {
    wrap.appendChild(el("div", "error-note", "Couldn't load the lead's research and thread: " + data.error));
    return;
  }
  const { lead, thread } = data;

  const research = crmSection("Research");
  const channels = lead.contact_channels && typeof renderContactChannels === "function"
    ? renderContactChannels(lead.contact_channels) : null;
  if (channels) research.appendChild(channels);
  if (lead.research_summary) {
    research.appendChild(el("div", "crm-sub-title muted small", `Website research${lead.researched_at ? " · " + lead.researched_at : ""}`));
    research.appendChild(el("div", "research-body", lead.research_summary));
  }
  if (lead.contact_research) {
    research.appendChild(el("div", "crm-sub-title muted small", `Contact research${lead.contact_researched_at ? " · " + lead.contact_researched_at : ""}`));
    research.appendChild(el("div", "research-body", lead.contact_research));
  }
  if (!lead.research_summary && !lead.contact_research && !channels) {
    research.appendChild(el("div", "muted small", "No research on file for this lead yet."));
  }
  wrap.appendChild(research);

  const convo = el("details", "crm-section crm-thread");
  convo.open = true;
  convo.appendChild(el("summary", "crm-thread-summary", `Cold-email conversation (${thread.length} message${thread.length === 1 ? "" : "s"})`));
  const tc = el("div", "thread");
  thread.forEach((m) => {
    const msg = el("div", `msg ${m.who}`);
    const meta = el("div", "msg-meta");
    meta.appendChild(document.createTextNode(`${m.name} · ${m.time} `));
    if (m.from_email) meta.appendChild(el("span", "msg-from", m.from_email));
    msg.appendChild(meta);
    const bubble = el("div", "bubble");
    // Server-cleaned HTML (app/email_clean.py), same as the inbox thread.
    bubble.innerHTML = m.english || m.html;
    msg.appendChild(bubble);
    tc.appendChild(msg);
  });
  if (!thread.length) tc.appendChild(el("div", "muted small", "No messages found."));
  convo.appendChild(tc);
  wrap.appendChild(convo);
}

// ---------- boot ----------

$("mode-outreach-btn").addEventListener("click", () => setMode("outreach"));
$("mode-crm-btn").addEventListener("click", () => {
  crm.dealId = null;
  setMode("crm");
});
try {
  if (localStorage.getItem(CRM_MODE_KEY) === "crm") setMode("crm");
} catch (_) { /* storage unavailable: start in Outreach */ }
