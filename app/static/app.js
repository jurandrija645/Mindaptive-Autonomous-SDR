"use strict";

// The inbox statuses, in the order db.list_inbox ranks them (most urgent
// first). This is the single source of truth for the status filter too: the
// keys are its checkboxes, in this order, and the values are their labels.
// reply/followup/waiting are the app's own sub-states (Smartlead has no
// equivalent — see detector.decide); everything else here mirrors a
// Smartlead category 1:1 (scheduler._KNOWN_CATEGORY_SLUGS). A lead whose
// Smartlead category isn't one of these known ones still gets a chip — see
// leadCategoryLabel, which falls back to lead.smartlead_category verbatim.
const CHIP = {
  reply: "Awaiting your reply",
  followup: "Follow-up due",
  auto_reply: "Auto-reply — nudge",
  waiting: "In conversation",
  not_interested: "Not interested",
  do_not_contact: "Do not contact",
  wrong_person: "Wrong person",
  opted_out: "Opted out",
  bounced: "Bounced",
  booked: "Meeting booked ✅",
};
const CATEGORY_ORDER = Object.keys(CHIP);
const STATUS_FILTER_KEY = "responder.statusFilter";

// How hot the lead is (app/lead_temperature.py) — a different axis from CHIP
// above, which says what the thread needs next. This one says whether they
// asked to talk, and it's what the inbox sorts on first: every 🔥 lead is above
// everything else in the list, regardless of category.
const TEMP = {
  hot: "🔥 Very hot",
  warm: "🌤 Warm",
  cold: "❄️ Cold",
};
const TEMP_ORDER = ["hot", "warm", "cold"];

const state = {
  view: "inbox",        // "inbox" | "scheduled" | "archive"
  allLeads: [],          // full inbox as loaded from the server, unfiltered
  leads: [],              // filtered view actually rendered (search + category)
  searchQuery: "",
  categoryFilter: loadStatusFilter(),  // hoisted; reads the saved selection
  snoozedCount: 0,       // archive view only: state.leads[0..snoozedCount) are snoozed, rest archived
  selected: -1,
  detail: null,          // current lead detail {lead, thread, draft}
  categoryList: null,    // live Smartlead categories, for the "Change status" dropdown
  selectedImage: null,   // <img> in the editor currently targeted by the resize bar
  nameNote: null,        // "renamed here only" note from the last ✎ Rename, cleared on lead switch
  draftNote: null,       // warning about the draft just created (e.g. a template still in English)
  google: null,          // /api/google/status: whether the LinkedIn export button can be drawn
  exportNote: null,      // outcome of the last Export for LinkedIn, cleared on lead switch
  exportRunning: false,  // an export is in flight for the currently open lead
  templates: null,       // message templates from /api/templates, loaded when the modal opens
  models: [],            // /api/models catalog: Anthropic + OpenRouter, with prices
  defaultModel: null,    // id of the model used when nothing is explicitly picked
  roles: [],             // per-task model assignments shown in the Models panel
  // ---- campaigns view ----
  accounts: null,        // [{slug,label}] Smartlead accounts, loaded once
  account: null,         // slug of the account whose campaigns are shown
  campaigns: [],         // /api/campaigns list with headline stats
  selectedCampaign: null,
  campaignTab: "overview", // "overview" | "report" | "conversations"
  convoFilter: "",       // lead category filter on the Conversations sub-tab
  convoBrowseOpen: false, // raw-thread section stays open across filter clicks
  campaignPoll: null,    // setTimeout handle polling a running analysis
};

const DEFAULT_CATEGORIES = [
  "Not Interested", "Meeting Request", "Do Not Contact", "Information Request",
  "Out Of Office", "Wrong Person", "Uncategorizable by Ai", "Sender Originated Bounce",
  "Meeting-Booked", "Interested for Video", "Auto-Reply", "Lead Opted Out",
  "We opted Out", "Contact later", "Redirect", "Lead Done", "Interested for Toolkit",
  "Interested for Calculator",
];

const PAUSE_CATEGORIES = new Set(["Not Interested", "Do Not Contact", "Wrong Person", "Lead Opted Out", "We opted Out"]);

// The model list is served by the backend (GET /api/models, built by
// app/models_registry.py) rather than hardcoded here: it spans two providers
// (Anthropic and OpenRouter), carries live per-million-token prices, and its
// default is a stored setting Andrew changes from this dropdown — none of which
// a static array can express. state.models holds the catalog,
// state.defaultModel the currently-set default.
async function loadModels() {
  try {
    const data = await apiGet("/api/models");
    state.models = data.models || [];
    state.defaultModel = data.default || null;
    state.roles = data.roles || [];
  } catch (e) {
    state.models = [];
    state.defaultModel = null;
    state.roles = [];
    console.error("could not load the model list", e);
  }
  refreshModelSelects();
}

// Price per million tokens, as shown in the dropdown. Sub-dollar prices get a
// second decimal ($0.14) — rounding DeepSeek's input price to "$0" would hide
// exactly the difference the picker exists to show.
function formatPrice(value) {
  if (value === null || value === undefined) return "?";
  return value < 1 ? `$${value.toFixed(2)}` : `$${value.toFixed(2).replace(/\.00$/, "")}`;
}

function modelOptionLabel(m) {
  const price = `${formatPrice(m.input_per_mtok)}/${formatPrice(m.output_per_mtok)} per M`;
  const flags = [];
  if (m.id === state.defaultModel) flags.push("default");
  if (!m.available) flags.push("no API key");
  const suffix = flags.length ? ` — ${flags.join(", ")}` : "";
  return `${m.label} · ${price}${suffix}`;
}

// Rebuilds every model <select> on screen, preserving each one's current
// choice. Called after the catalog loads and after the default changes.
function refreshModelSelects() {
  document.querySelectorAll("select.model-select").forEach((select) => {
    const previous = select.value;
    fillModelSelect(select, previous);
  });
  document.querySelectorAll(".btn-set-default").forEach(syncSetDefaultButton);
}

// Models are grouped into <optgroup>s by provider — that grouping IS the
// "which provider is this?" answer the dropdown has to give at a glance, and
// it survives the browser's native select rendering on mobile, which arbitrary
// styling does not.
function fillModelSelect(select, preferredValue) {
  select.innerHTML = "";
  const groups = [
    { provider: "anthropic", label: "Anthropic (web research + caching)" },
    { provider: "openrouter", label: "OpenRouter (cheaper, no web research)" },
  ];
  let hasPreferred = false;
  groups.forEach((group) => {
    const models = state.models.filter((m) => m.provider === group.provider);
    if (!models.length) return;
    const optgroup = document.createElement("optgroup");
    optgroup.label = group.label;
    models.forEach((m) => {
      const o = document.createElement("option");
      o.value = m.id;
      o.textContent = modelOptionLabel(m);
      // A model whose provider key isn't configured stays visible but
      // unpickable, so it's obvious the option exists and what's missing.
      o.disabled = !m.available;
      if (m.id === preferredValue && m.available) hasPreferred = true;
      optgroup.appendChild(o);
    });
    select.appendChild(optgroup);
  });
  if (!state.models.length) {
    const o = document.createElement("option");
    o.textContent = "Loading models…";
    select.appendChild(o);
    return;
  }
  select.value = hasPreferred ? preferredValue : state.defaultModel || "";
  if (!select.value) {
    const first = state.models.find((m) => m.available);
    if (first) select.value = first.id;
  }
}

function syncSetDefaultButton(btn) {
  const select = document.getElementById(btn.dataset.selectId);
  const isDefault = select && select.value === state.defaultModel;
  btn.disabled = !select || !select.value || isDefault;
  btn.textContent = isDefault ? "★ Default" : "☆ Set as default";
  btn.title = isDefault
    ? "This model is already the default for auto-drafts and new sessions"
    : "Use this model by default (auto-drafts, and the pre-selected option here)";
}

// ---- Models panel ----
//
// One dropdown per AI task, so "which model writes my drafts" and "which model
// translates a thread I'm only reading" are separate decisions. Each row can
// also be left on "Follows …", which is a live link to another task rather than
// a copy of its current value — clear the drafting model later and everything
// inheriting from it moves too.

function closeModelsModal() {
  const overlay = $("models-modal-overlay");
  if (overlay) overlay.remove();
  document.body.style.overflow = "";
  document.removeEventListener("keydown", onModelsModalKeydown);
}

function onModelsModalKeydown(e) {
  if (e.key === "Escape") closeModelsModal();
}

async function openModelsModal() {
  if ($("models-modal-overlay")) return;
  // Always re-read: prices refresh, and another tab may have changed a role.
  await loadModels();

  const overlay = el("div", "modal-overlay");
  overlay.id = "models-modal-overlay";
  overlay.addEventListener("click", (e) => {
    if (e.target === overlay) closeModelsModal();
  });

  const modal = el("div", "modal models-modal");
  const header = el("div", "modal-header");
  const heading = el("div", "modal-heading");
  heading.appendChild(el("h3", null, "AI models"));
  heading.appendChild(
    el("div", "modal-sub", "Pick which model does what. Prices are per million tokens — input / output.")
  );
  header.appendChild(heading);
  const closeBtn = el("button", "modal-close", "×");
  closeBtn.type = "button";
  closeBtn.setAttribute("aria-label", "Close");
  closeBtn.addEventListener("click", closeModelsModal);
  header.appendChild(closeBtn);
  modal.appendChild(header);

  // Roles and the footnote share one scrolling, padded body — .modal itself is
  // overflow:hidden with a max-height, so anything appended straight to it is
  // clipped once the panel is taller than the window.
  const body = el("div", "models-body");
  const list = el("div", "models-roles");
  (state.roles || []).forEach((role) => list.appendChild(renderRoleRow(role)));
  body.appendChild(list);

  body.appendChild(
    el(
      "div",
      "models-note",
      "Overnight batch pre-generation always runs on an Anthropic model — it uses " +
        "Anthropic's Batch API, which can't accept an OpenRouter model. If your " +
        "drafting model is an OpenRouter one, batches fall back to ANTHROPIC_MODEL."
    )
  );
  modal.appendChild(body);

  overlay.appendChild(modal);
  document.body.appendChild(overlay);
  document.body.style.overflow = "hidden";
  document.addEventListener("keydown", onModelsModalKeydown);
}

function renderRoleRow(role) {
  const row = el("div", "models-role");
  const head = el("div", "models-role-head");
  head.appendChild(el("div", "models-role-label", role.label));
  const status = el("div", "models-role-status");
  head.appendChild(status);
  row.appendChild(head);
  row.appendChild(el("div", "models-role-desc", role.description));

  const controls = el("div", "models-role-controls");
  const select = document.createElement("select");
  select.className = "model-select";
  fillModelSelect(select, role.model);
  controls.appendChild(select);

  // "Follows X" is only offered where a fallback actually exists, so the option
  // never appears on a task that has nowhere to inherit from.
  let inheritBtn = null;
  if (role.inherits_from) {
    inheritBtn = el("button", "btn-secondary btn-inherit", `Follow ${role.inherits_from}`);
    inheritBtn.type = "button";
    controls.appendChild(inheritBtn);
  }
  row.appendChild(controls);

  const paint = () => {
    status.textContent = role.explicit
      ? "set explicitly"
      : role.inherits_from
        ? `follows ${role.inherits_from}`
        : "default";
    status.className = "models-role-status" + (role.explicit ? " is-explicit" : "");
    if (inheritBtn) inheritBtn.disabled = !role.explicit;
  };
  paint();

  const save = async (model) => {
    select.disabled = true;
    if (inheritBtn) inheritBtn.disabled = true;
    try {
      const data = await apiPost("/api/models/role", { role: role.role, model });
      state.models = data.models || state.models;
      state.defaultModel = data.default || state.defaultModel;
      state.roles = data.roles || state.roles;
      // Re-render the whole list: changing one role can move every role that
      // inherits from it, and showing that immediately is the point.
      const list = document.querySelector(".models-roles");
      if (list) {
        list.innerHTML = "";
        (state.roles || []).forEach((r) => list.appendChild(renderRoleRow(r)));
      }
      refreshModelSelects();
    } catch (e) {
      alert("Couldn't save that model: " + e.message);
      select.disabled = false;
      paint();
    }
  };

  select.addEventListener("change", () => save(select.value));
  if (inheritBtn) inheritBtn.addEventListener("click", () => save(null));
  return row;
}

async function setDefaultModel(select, btn) {
  const model = select.value;
  if (!model) return;
  btn.disabled = true;
  try {
    const data = await apiPost("/api/models/default", { model });
    state.models = data.models || state.models;
    state.defaultModel = data.default || model;
    refreshModelSelects();
  } catch (e) {
    alert("Couldn't set the default model: " + e.message);
    syncSetDefaultButton(btn);
  }
}

// Canned, pre-approved message templates now live server-side (SQLite, editable
// from the modal) and are fetched into state.templates on demand — see
// /api/templates. Picking one skips the full Claude drafter (system prompt,
// knowledge base, web tools) entirely and just runs one cheap translation call
// server-side (/quick-draft). {name} and {company} are filled in client-side
// (quickFollowup) before that call.

async function loadCategories() {
  try {
    const data = await apiGet("/api/categories");
    state.categoryList = data.categories.filter((c) => c !== "Interested");
  } catch (e) {
    state.categoryList = DEFAULT_CATEGORIES;
  }
}

const $ = (id) => document.getElementById(id);

const MOBILE_MQ = window.matchMedia("(max-width: 768px)");

function isMobileLayout() {
  return MOBILE_MQ.matches;
}
function showMobileDetail() {
  if (isMobileLayout()) document.body.classList.add("showing-detail");
}
function showMobileList() {
  document.body.classList.remove("showing-detail");
}
function goBackToMobileList() {
  state.selected = -1;
  state.detail = null;
  renderList();
  $("detail-body").hidden = true;
  $("detail-empty").hidden = false;
  showMobileList();
}

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

// Calendar dates in the browser's own timezone. todayStr() rounds through UTC,
// so "tomorrow" computed off it is today for anyone east of UTC in the small
// hours — fine for a comparison, wrong for a date we're about to store.
function localDateStr(d) {
  const pad = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

function dateInDays(n) {
  const d = new Date();
  d.setDate(d.getDate() + n);
  return localDateStr(d);
}

// "2026-08-06" -> "Thu, 6 Aug" (with the year when it isn't this one). Parsed
// field by field because new Date("2026-08-06") is UTC midnight, i.e. the day
// before for anyone west of UTC.
function formatDayLabel(str) {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(str || "");
  if (!m) return str || "";
  const d = new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]));
  const opts = { weekday: "short", day: "numeric", month: "short" };
  if (d.getFullYear() !== new Date().getFullYear()) opts.year = "numeric";
  return d.toLocaleDateString(undefined, opts);
}

// UTC ISO string -> "YYYY-MM-DDTHH:MM" in the browser's local time, the only
// format <input type="datetime-local"> accepts as a value.
function toLocalInputValue(iso) {
  const d = new Date(iso);
  if (isNaN(d)) return "";
  const pad = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function currentLead() {
  return state.leads[state.selected];
}

async function apiGet(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}
async function apiSend(method, url, body) {
  const r = await fetch(url, {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {}),
  });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.error || "Request failed");
  return data;
}
const apiPost = (url, body) => apiSend("POST", url, body);
const apiPatch = (url, body) => apiSend("PATCH", url, body);
const apiDelete = (url) => apiSend("DELETE", url);

// ---------- inbox / archive list loading ----------
async function loadInbox() {
  const data = await apiGet("/api/inbox");
  // A loadInbox() started before a tab switch (e.g. the one fired at page load)
  // can resolve after the user has already moved to another view. Don't let it
  // repaint #lead-list over that view.
  if (state.view !== "inbox") return data;
  state.allLeads = data.leads;
  state.snoozedCount = 0;
  applyFilter();
  $("scan-status").textContent = data.scan_running ? "↻ scanning…" : "";
  return data;
}

// Campaign is in the haystack because it's now on every row: a name you can
// see is a name you'll type, and "airports" or "dental" is how you'd ask for a
// niche when the company names give no hint of it.
function matchesSearch(lead, query) {
  if (!query) return true;
  const haystack = `${lead.name || ""} ${lead.company || ""} ${lead.email || ""} ${lead.campaign_name || ""}`.toLowerCase();
  return haystack.includes(query);
}

function applyFilter() {
  const query = state.searchQuery.trim().toLowerCase();
  // Search first, so the dropdown's counts describe the list you're actually
  // looking at: with a search active, "Meeting booked (0)" means none of the
  // matches are booked, not that no booked lead exists.
  const matched = state.allLeads.filter((l) => matchesSearch(l, query));
  state.leads = matched.filter((l) => {
    const cat = leadCategory(l);
    // A category with no checkbox in the filter panel — a custom Smartlead
    // category the app doesn't have a fixed slug for — is never hidden by
    // the filter; there would be no box to tick to bring it back.
    return !CATEGORY_ORDER.includes(cat) || state.categoryFilter.has(cat);
  });
  renderStatusFilter(matched);
  renderList();
}

// ---------- status filter ----------
// The checkbox dropdown above the lead list. Its rows are rendered from CHIP so
// the labels and colours can't drift from the ones on the lead rows, and the
// selection is persisted — a filter you set once survives the 60s auto-refresh
// and a browser reload.

function leadCategory(lead) {
  return lead.category || "waiting";
}

// The chip text for a lead's category. Known categories (CHIP above) get
// their fixed label; anything else — a custom Smartlead category with no
// dedicated slug — falls back to Smartlead's own name for it verbatim
// (lead.smartlead_category), which is what makes the app 1:1 with Smartlead
// even for a category nobody's told the dashboard about yet.
function leadCategoryLabel(lead) {
  return CHIP[lead.category] || lead.smartlead_category || CHIP.waiting;
}

// Categories that existed before "Not interested" got its own chip (it used
// to silently render as "In conversation"). A browser with an old saved
// filter selection has no way to have deliberately unchecked a box that
// didn't exist yet — see loadStatusFilter.
const _LEGACY_CATEGORY_ORDER = ["reply", "followup", "auto_reply", "waiting", "booked"];

function loadStatusFilter() {
  try {
    const saved = JSON.parse(localStorage.getItem(STATUS_FILTER_KEY) || "null");
    const known = Array.isArray(saved) ? saved.filter((c) => CATEGORY_ORDER.includes(c)) : [];
    // An empty saved selection deliberately restores to "show everything":
    // opening the dashboard to an empty inbox reads as a broken app, not as a
    // filter left switched off yesterday.
    if (known.length) {
      const result = new Set(known);
      // A category added after this browser last saved a selection defaults
      // to shown — an old filter must not silently start hiding a whole new
      // bucket of leads just because it predates that checkbox.
      CATEGORY_ORDER.forEach((c) => {
        if (!_LEGACY_CATEGORY_ORDER.includes(c)) result.add(c);
      });
      return result;
    }
  } catch (e) {
    /* unreadable storage — fall through to showing everything */
  }
  return new Set(CATEGORY_ORDER);
}

function saveStatusFilter() {
  try {
    localStorage.setItem(STATUS_FILTER_KEY, JSON.stringify([...state.categoryFilter]));
  } catch (e) {
    /* private mode / quota — the filter still works for this session */
  }
}

function setStatus(cat, on) {
  if (on) state.categoryFilter.add(cat);
  else state.categoryFilter.delete(cat);
  saveStatusFilter();
  applyFilter();
}

function setAllStatuses(on) {
  state.categoryFilter = new Set(on ? CATEGORY_ORDER : []);
  saveStatusFilter();
  applyFilter();
}

function statusFilterLabel() {
  const chosen = CATEGORY_ORDER.filter((c) => state.categoryFilter.has(c));
  if (chosen.length === CATEGORY_ORDER.length) return "All statuses";
  if (chosen.length === 0) return "No statuses — nothing shown";
  if (chosen.length === 1) return CHIP[chosen[0]];
  return `${chosen.length} of ${CATEGORY_ORDER.length} statuses`;
}

function renderStatusFilter(leads) {
  const counts = {};
  leads.forEach((l) => {
    const c = leadCategory(l);
    counts[c] = (counts[c] || 0) + 1;
  });

  const box = $("status-menu-items");
  box.innerHTML = "";
  CATEGORY_ORDER.forEach((cat) => {
    const row = el("label", "status-option");
    const cb = el("input");
    cb.type = "checkbox";
    cb.checked = state.categoryFilter.has(cat);
    cb.addEventListener("change", () => setStatus(cat, cb.checked));
    row.appendChild(cb);
    row.appendChild(el("i", `dot dot-${cat}`));
    row.appendChild(el("span", "status-option-label", CHIP[cat]));
    row.appendChild(el("span", "status-option-count", String(counts[cat] || 0)));
    box.appendChild(row);
  });
  $("status-filter-label").textContent = statusFilterLabel();
}

function openStatusMenu(open) {
  $("status-menu").hidden = !open;
  $("status-filter-btn").setAttribute("aria-expanded", open ? "true" : "false");
}

async function loadArchive() {
  const data = await apiGet("/api/archive");
  state.snoozedCount = data.snoozed.length;
  state.leads = data.snoozed.concat(data.archived);
  state.selected = -1;
  renderList();
  $("detail-body").hidden = true;
  $("detail-empty").hidden = false;
  showMobileList();
  return data;
}

async function loadScheduled() {
  const data = await apiGet("/api/scheduled");
  state.snoozedCount = 0;
  state.leads = data.scheduled;
  state.selected = -1;
  renderList();
  $("detail-body").hidden = true;
  $("detail-empty").hidden = false;
  showMobileList();
  return data;
}

// ---------- stats view ----------
const KIND_LABELS = {
  reply: "Replies to leads",
  followup: "Follow-ups",
  autoreply: "Auto-reply nudges",
  manual: "Manual messages",
};

const KIND_DESC = {
  reply: "Fast responses sent to leads who wrote back.",
  followup: "Nudges sent to leads who had gone quiet.",
  autoreply: "Bumps sent after an auto-reply / out-of-office.",
  manual: "Messages you wrote or sent by hand.",
};

// Stats is a single dashboard, not a list of leads. Render it in the main
// detail pane (like Campaigns) and leave the sidebar as a short signpost so it
// doesn't show stale lead rows from whatever view was open before.
async function loadStats() {
  const list = $("lead-list");
  list.innerHTML = "";
  $("inbox-count").textContent = "Stats";
  $("inbox-empty").hidden = false;
  $("inbox-empty").innerHTML =
    "Your numbers are on the right — a summary of the last 30 days plus a few live pipeline counts.";

  const data = await apiGet("/api/metrics");
  renderStats(data);
  $("detail-empty").hidden = true;
  $("detail-body").hidden = false;
  showMobileDetail();
  return data;
}

function renderStats(m) {
  const body = $("detail-body");
  body.innerHTML = "";

  const head = el("div", "stats-head");
  head.appendChild(el("h2", null, "Stats"));
  head.appendChild(el("div", "muted", `Activity over the last ${m.days} days, plus live pipeline counts.`));
  body.appendChild(head);

  const dash = el("div", "stats-dash");
  body.appendChild(dash);

  const section = (title, note) => {
    const s = el("section", "stats-section");
    s.appendChild(el("h3", null, title));
    if (note) s.appendChild(el("p", "stats-note", note));
    dash.appendChild(s);
    return s;
  };
  const tiles = (parent) => {
    const row = el("div", "stat-tiles");
    parent.appendChild(row);
    return row;
  };
  const tile = (parent, num, label, sub) => {
    const t = el("div", "stat-tile");
    t.appendChild(el("div", "stat-tile-num", String(num)));
    t.appendChild(el("div", "stat-tile-label", label));
    if (sub) t.appendChild(el("div", "stat-tile-sub", sub));
    parent.appendChild(t);
  };
  const table = (parent, rows) => {
    const t = el("table", "stats-table");
    const tb = el("tbody");
    rows.forEach(([label, value, hint]) => {
      const tr = el("tr");
      const tdL = el("td", "stats-td-label");
      tdL.appendChild(el("div", "stats-label-main", label));
      if (hint) tdL.appendChild(el("div", "stats-hint", hint));
      tr.appendChild(tdL);
      tr.appendChild(el("td", "stats-td-value", String(value)));
      tb.appendChild(tr);
    });
    t.appendChild(tb);
    parent.appendChild(t);
  };
  const nameOf = (b) => `${b.name}${b.company ? " · " + b.company : ""}`;

  // ---- Meetings booked ----
  const booked = section("Meetings booked", null);
  const bt = tiles(booked);
  tile(bt, m.booked_total, "Booked all-time");
  tile(bt, m.booked_recent, `Booked in last ${m.days} days`);

  const recent = m.recent_booked || [];
  // Collapse a run of identical timestamps into one row. A big cluster sharing
  // one exact time is the initial import: every lead already sitting in
  // Smartlead's "Meeting-Booked" category when tracking switched on got stamped
  // at the same instant, so that date is "first seen by this tool", not the
  // real meeting date. Showing 30+ identical dates reads as fake data.
  const groups = [];
  recent.forEach((b) => {
    const last = groups[groups.length - 1];
    if (last && last.at === b.booked_at) last.names.push(b);
    else groups.push({ at: b.booked_at, names: [b] });
  });
  const hasBatch = groups.some((g) => g.names.length >= 3);
  if (hasBatch) {
    booked.appendChild(el("p", "stats-note",
      "Dates show when this tool first saw the booking, not when the meeting was set. " +
      "Meetings already marked “Meeting-Booked” in Smartlead before tracking started all share one timestamp — that is the import moment. New bookings get an accurate date."));
  }
  if (recent.length) {
    const wrap = el("div", "booked-list");
    groups.forEach((g) => {
      if (g.names.length >= 3) {
        const b = el("div", "booked-batch");
        b.appendChild(el("div", "booked-batch-head", `${g.names.length} existing bookings · first tracked ${g.at}`));
        b.appendChild(el("div", "booked-batch-names", g.names.map(nameOf).join(", ")));
        wrap.appendChild(b);
      } else {
        g.names.forEach((n) => {
          const row = el("div", "booked-row");
          row.appendChild(el("span", "booked-name", `✅ ${nameOf(n)}`));
          row.appendChild(el("span", "booked-date", n.booked_at || ""));
          wrap.appendChild(row);
        });
      }
    });
    booked.appendChild(wrap);
  }

  // ---- Messages sent ----
  const sent = section("Messages sent", `In the last ${m.days} days.`);
  tile(tiles(sent), m.sent_total, "Total sent");
  const sentRows = Object.entries(m.sent_by_kind || {})
    .map(([k, v]) => [KIND_LABELS[k] || k, v, KIND_DESC[k] || null]);
  if (sentRows.length) table(sent, sentRows);

  // ---- Follow-up effectiveness ----
  const funnel = section("Are the follow-ups working?", null);
  const rate = m.followups_sent ? Math.round((100 * m.followup_replies) / m.followups_sent) : null;
  const ft = tiles(funnel);
  tile(ft, rate != null ? `${rate}%` : "—", "Follow-ups that got a reply", `${m.followup_replies} of ${m.followups_sent}`);
  tile(ft, m.avg_reply_hours != null ? `${m.avg_reply_hours}h` : "—", "Avg time to answer a lead", "From their reply to our send");

  // ---- Live pipeline ----
  const pipe = section("Pipeline right now", "Live counts — not limited to the last 30 days.");
  table(pipe, [
    ["Follow-ups due (not yet drafted)", m.open_candidates, "Leads waiting for a follow-up to be generated."],
    ["Drafts awaiting your review", m.pending_drafts, "Generated and waiting for you to send or edit."],
    ["Scheduled sends", m.scheduled_drafts, "Approved drafts queued to go out."],
  ]);

  // ---- Drafts by model ----
  const modelRows = Object.entries(m.drafts_by_model || {});
  if (modelRows.length) {
    const ms = section("Drafts generated by model", `In the last ${m.days} days.`);
    table(ms, modelRows.map(([k, v]) => [k, v, null]));
  }
}

// ---------- campaigns ----------

// Verdict labels come from campaign_analytics.verdict(). "Not enough data" is
// deliberately neutral grey, never a colour that reads as a result — with ~40
// human replies split across six variants, most rows land there and a green
// chip would invite acting on noise.
const VERDICT_LABEL = {
  solid_above: "Solid — above average",
  solid_below: "Solid — below average",
  leaning_above: "Leaning above",
  leaning_below: "Leaning below",
  not_enough_data: "Not enough data",
};

const pct = (n) => `${(100 * (n || 0)).toFixed(2)}%`;

function verdictChip(verdict) {
  const chip = el("span", `verdict verdict-${verdict || "not_enough_data"}`);
  chip.textContent = VERDICT_LABEL[verdict] || verdict || "—";
  return chip;
}

async function loadCampaigns() {
  const list = $("lead-list");
  list.innerHTML = "";
  $("inbox-count").textContent = "Campaigns";
  $("inbox-empty").hidden = true;
  list.appendChild(el("li", "list-section", "Loading campaigns…"));

  // Load the account list once, so the switcher knows what's available.
  if (state.accounts === null) {
    try {
      state.accounts = (await apiGet("/api/accounts")).accounts || [];
    } catch (e) {
      state.accounts = [];
    }
    if (!state.account && state.accounts.length) state.account = state.accounts[0].slug;
  }

  const url = state.account ? `/api/campaigns?account=${encodeURIComponent(state.account)}` : "/api/campaigns";
  const data = await apiGet(url);
  if (state.view !== "campaigns") return data; // switched away while loading
  state.account = data.account || state.account;
  state.campaigns = data.campaigns || [];
  state.selectedCampaign = null;
  $("detail-body").hidden = true;
  $("detail-empty").hidden = false;
  renderCampaignList();
  return data;
}

function accountSwitcher() {
  // Only worth showing when there's more than one account to switch between.
  if (!state.accounts || state.accounts.length < 2) return null;
  const row = el("li", "account-switch");
  row.appendChild(el("span", "account-label", "Account"));
  const select = el("select", "account-select");
  state.accounts.forEach((a) => {
    const opt = el("option", null, a.label);
    opt.value = a.slug;
    if (a.slug === state.account) opt.selected = true;
    select.appendChild(opt);
  });
  select.addEventListener("change", () => {
    state.account = select.value;
    loadCampaigns().catch((e) => console.error(e));
  });
  row.appendChild(select);
  return row;
}

function renderCampaignList() {
  const list = $("lead-list");
  list.innerHTML = "";
  $("inbox-count").textContent = `Campaigns (${state.campaigns.length})`;

  const switcher = accountSwitcher();
  if (switcher) list.appendChild(switcher);

  const active = state.campaigns.filter((c) => c.status === "ACTIVE");
  const rest = state.campaigns.filter((c) => c.status !== "ACTIVE");
  const addGroup = (title, items) => {
    if (!items.length) return;
    list.appendChild(el("li", "list-section", title));
    items.forEach((c) => list.appendChild(campaignRow(c)));
  };
  addGroup("Active", active);
  addGroup("Completed / drafted", rest);
}

function campaignRow(campaign) {
  const li = el("li", "lead-row campaign-row");
  if (state.selectedCampaign === campaign.id) li.classList.add("selected");
  li.appendChild(el("div", "lead-name", campaign.name));
  const meta = el("div", "campaign-meta");
  meta.appendChild(el("span", "campaign-stat", `${(campaign.sent || 0).toLocaleString()} sent`));
  meta.appendChild(el("span", "campaign-stat", `${campaign.replies || 0} replies`));
  if (campaign.interested) meta.appendChild(el("span", "campaign-stat good", `${campaign.interested} interested`));
  if (campaign.bounce_rate > 0.03) {
    meta.appendChild(el("span", "campaign-stat bad", `${pct(campaign.bounce_rate)} bounce`));
  }
  li.appendChild(meta);
  if (campaign.report_at) li.appendChild(el("div", "campaign-analyzed", `Analyzed ${campaign.report_at}`));
  li.addEventListener("click", () => selectCampaign(campaign));
  return li;
}

async function selectCampaign(campaign) {
  state.selectedCampaign = campaign.id;
  state.campaignTab = state.campaignTab || "overview";
  renderCampaignList();
  $("detail-empty").hidden = true;
  $("detail-body").hidden = false;
  showMobileDetail();
  await renderCampaignDetail(campaign);
}

async function renderCampaignDetail(campaign) {
  const body = $("detail-body");
  body.innerHTML = "";

  const head = el("div", "campaign-head");
  head.appendChild(el("h2", null, campaign.name));
  const sub = el("div", "muted", `${campaign.status} · ${(campaign.sent || 0).toLocaleString()} sent · ${campaign.leads || 0} leads`);
  head.appendChild(sub);
  body.appendChild(head);

  const tabs = el("div", "campaign-tabs");
  [["overview", "Overview"], ["report", "AI analysis"], ["conversations", "Conversations"]].forEach(([key, label]) => {
    const btn = el("button", "campaign-tab" + (state.campaignTab === key ? " active" : ""), label);
    btn.type = "button";
    btn.addEventListener("click", () => {
      state.campaignTab = key;
      renderCampaignDetail(campaign);
    });
    tabs.appendChild(btn);
  });
  body.appendChild(tabs);

  const pane = el("div", "campaign-pane");
  body.appendChild(pane);
  pane.appendChild(el("p", "muted", "Loading…"));

  if (state.campaignTab === "overview") await renderCampaignOverview(pane, campaign);
  else if (state.campaignTab === "report") await renderCampaignReport(pane, campaign);
  else await renderCampaignConversations(pane, campaign);
}

function metricTable(rows, columns, extraClass) {
  const table = el("table", "metric-table" + (extraClass ? ` ${extraClass}` : ""));
  const thead = el("thead");
  const hrow = el("tr");
  columns.forEach((c) => hrow.appendChild(el("th", null, c.label)));
  thead.appendChild(hrow);
  table.appendChild(thead);
  const tbody = el("tbody");
  rows.forEach((row) => {
    const tr = el("tr");
    columns.forEach((c) => {
      const td = el("td");
      const value = c.render(row);
      if (value instanceof Node) td.appendChild(value);
      else td.textContent = value;
      tr.appendChild(td);
    });
    tbody.appendChild(tr);
  });
  table.appendChild(tbody);
  return table;
}

// "Leads" is deliberately omitted — delivered is the denominator every rate
// here uses, and the extra column pushed the confidence chip (the column that
// decides whether a row is actionable at all) off the right edge of the pane.
const RATE_COLUMNS = [
  { label: "Delivered", render: (r) => (r.delivered || 0).toLocaleString() },
  { label: "Replies", render: (r) => String(r.replies || 0) },
  { label: "Reply %", render: (r) => pct(r.reply_rate) },
  { label: "Positive", render: (r) => String(r.positives || 0) },
  { label: "Confidence", render: (r) => verdictChip(r.reply_verdict) },
];

const ROLE_LABELS = {
  subject: "Subject lines", cta: "Calls to action", offer: "Offers",
  pitch: "Pitches", painpoint: "Pain points", socialproof: "Social proof",
  icebreaker: "Icebreakers", greeting: "Greetings", signoff: "Sign-offs",
};
const ROLE_SINGULAR = {
  subject: "subject line", cta: "CTA", offer: "offer", pitch: "pitch",
  painpoint: "pain point", socialproof: "social proof", icebreaker: "icebreaker",
};

// Status comes from campaign_analytics.recommendations(). The wording matters:
// "leading" must never look like a decided result, because it isn't one.
const STATUS_LABEL = {
  clear: "Decided — use this",
  leaning: "Ahead, not proven",
  unresolved: "Not resolved yet",
  untested: "Never tested",
};

async function renderCampaignOverview(pane, campaign) {
  const data = await apiGet(`/api/campaigns/${campaign.id}`);
  pane.innerHTML = "";
  if (!data.synced) {
    pane.appendChild(el("p", "muted", data.message));
    pane.appendChild(analyzeButton(campaign));
    return;
  }

  const o = data.summary.overall;
  const cards = el("div", "stat-cards");
  const card = (label, value, note) => {
    const c = el("div", "stat-card");
    c.appendChild(el("div", "stat-card-value", value));
    c.appendChild(el("div", "stat-card-label", label));
    if (note) c.appendChild(el("div", "stat-card-note", note));
    cards.appendChild(c);
  };
  card("Leads reached", (o.delivered || 0).toLocaleString(), `${o.bounced || 0} bounced`);
  card("Human replies", String(o.replies || 0), pct(o.reply_rate));
  card("Interested", String(o.positives || 0), `${pct(o.positive_rate)} of leads · ${pct(o.positive_per_reply)} of replies`);
  card("Meetings booked", String(o.booked || 0), `${o.robot_replies || 0} auto-replies excluded`);
  pane.appendChild(cards);
  pane.appendChild(el("p", "muted small", `Synced ${data.synced_at}. Open and click tracking are off for these campaigns, so replies are the only signal shown.`));

  renderDeliverability(pane, data.deliverability);
  renderRecommendations(pane, data.recommendations);
  renderVariantEmails(pane, data.variants);
  renderComponents(pane, data.slots || {});

  pane.appendChild(el("h3", null, "Which step earns the reply"));
  pane.appendChild(
    metricTable(data.reply_by_step, [
      { label: "Step", render: (r) => (r.step === 1 ? "1 (first email)" : `${r.step} (follow-up ${r.step - 1})`) },
      { label: "Leads reached", render: (r) => (r.reached || 0).toLocaleString() },
      { label: "Replies", render: (r) => String(r.replies || 0) },
      { label: "Positive", render: (r) => String(r.positives || 0) },
      { label: "Reply %", render: (r) => pct(r.reply_rate) },
    ])
  );

  const subjects = el("details", "extra-block");
  subjects.appendChild(el("summary", null, `Every subject line as sent (${(data.subjects || []).length})`));
  subjects.appendChild(el("p", "muted small", "One row per rendered subject, including every translation of it. The comparison worth reading is the subject-line block above, which pools them."));
  subjects.appendChild(
    metricTable(data.subjects, [
      { label: "Subject as sent", render: (r) => truncate(r.subject, 70) },
      ...RATE_COLUMNS,
    ], "wrap-first")
  );
  pane.appendChild(subjects);
}

// Who hosts the recipients' mailboxes, and whether that is what held the
// campaign back. Sits above the copy analysis on purpose: if a whole slice of
// the audience replied worse under identical emails, that is the first thing to
// know, because rewriting copy that was never the problem is the most expensive
// mistake this tab can lead someone into.
const ESP_STATUS_LABEL = {
  provider_drag: "Where it was sent held it back",
  provider_gap: "One slice behaved differently",
  no_provider_effect: "Not a provider problem",
};

function renderDeliverability(pane, data) {
  if (!data || !data.resolved) {
    if (data && data.reason) {
      pane.appendChild(el("h3", null, "Where the mail was going"));
      pane.appendChild(el("p", "muted small", data.reason));
    }
    return;
  }
  pane.appendChild(el("h3", null, "Where the mail was going"));

  const groups = (data.groups || []).filter((g) => g.group !== "unknown");
  const bar = el("div", "esp-bar");
  groups.forEach((g) => {
    if (!g.share) return;
    const seg = el("div", `esp-seg esp-${g.group}`);
    seg.style.width = `${(100 * g.share).toFixed(2)}%`;
    seg.title = `${g.label}: ${(100 * g.share).toFixed(1)}% of checked recipients`;
    if (g.share > 0.12) seg.textContent = `${Math.round(100 * g.share)}% ${g.label}`;
    bar.appendChild(seg);
  });
  pane.appendChild(bar);

  const checked = el("p", "muted small");
  checked.textContent =
    `${(data.classified || 0).toLocaleString()} of ${(data.leads || 0).toLocaleString()} recipients checked` +
    (data.unknown ? ` · ${data.unknown.toLocaleString()} domains could not be looked up` : "") +
    ". Read from each domain's real MX record, so it is where the mail actually lands, not what the list claimed.";
  pane.appendChild(checked);

  const d = data.diagnosis || {};
  if (d.headline) {
    const box = el("div", `esp-verdict esp-verdict-${d.status}`);
    const head = el("div", "esp-verdict-head");
    head.appendChild(el("span", `esp-status status-${d.status}`, ESP_STATUS_LABEL[d.status] || d.status));
    box.appendChild(head);
    box.appendChild(el("div", "esp-headline", d.headline));
    if (d.detail) box.appendChild(el("p", "esp-detail", d.detail));
    // A "not enough campaigns yet" note is a promise, not a result — it gets the
    // muted treatment so it can't be misread as evidence.
    if (d.history) {
      const cls = d.history_status === "not_enough_data" ? "muted small" : "esp-history";
      box.appendChild(el("p", cls, d.history));
    }
    if (d.caveat) box.appendChild(el("p", "muted small esp-caveat", d.caveat));
    pane.appendChild(box);
  }

  // Providers, not just the three-way group split: "Other" is 79% of the German
  // campaigns, and a bar that says only that answers nothing.
  const rows = (data.providers || []).filter((r) => r.sent >= 20);
  if (rows.length) {
    const table = el("details", "extra-block");
    table.appendChild(el("summary", null, `Every provider in this list (${rows.length})`));
    table.appendChild(
      el("p", "muted small", "Slices under 20 recipients are hidden. Confidence is judged against this campaign's own reply rate, and a slice too small to call says so.")
    );
    table.appendChild(
      metricTable(rows, [
        { label: "Provider", render: (r) => r.label },
        { label: "Recipients", render: (r) => (r.sent || 0).toLocaleString() },
        { label: "Share", render: (r) => pct(r.share) },
        { label: "Bounced", render: (r) => pct(r.bounce_rate) },
        { label: "Replies", render: (r) => String(r.replies || 0) },
        { label: "Reply %", render: (r) => pct(r.reply_rate) },
        { label: "Positive", render: (r) => String(r.positives || 0) },
        { label: "Confidence", render: (r) => verdictChip(r.reply_verdict) },
      ], "wrap-first")
    );
    pane.appendChild(table);
  }

  renderProviderHistory(pane, data.history);
}

// The part that only gets better with use: every campaign ever analyzed, pooled
// by provider. This is what lets a future campaign be told "it isn't the copy".
function renderProviderHistory(pane, history) {
  if (!history || !history.campaigns) return;
  const block = el("details", "extra-block");
  const one = history.campaigns === 1;
  block.appendChild(
    el("summary", null, `What ${history.campaigns} analyzed campaign${one ? " says" : "s say"} about providers`)
  );
  block.appendChild(
    el("p", "muted small", "Pooled across every campaign analyzed so far, this one excluded so it is not compared against itself. It grows as more campaigns are analyzed.")
  );
  const groups = (history.groups || []).filter((g) => g.group !== "unknown");
  if (groups.length) {
    block.appendChild(
      metricTable(groups, [
        { label: "Provider", render: (r) => r.label },
        { label: "Delivered", render: (r) => (r.delivered || 0).toLocaleString() },
        { label: "Bounced", render: (r) => pct((r.bounce || {}).rate) },
        { label: "Replies", render: (r) => String(r.replies || 0) },
        { label: "Reply %", render: (r) => pct((r.reply || {}).rate) },
        { label: "Positive %", render: (r) => pct((r.positive || {}).rate) },
      ])
    );
  }
  const split = history.split;
  if (split && split.note) block.appendChild(el("p", "esp-history", split.note));
  pane.appendChild(block);
}

// The answer, at the top, before any table: which component is decided, which
// is still open, and what the next run should look like. All of it computed in
// campaign_analytics.recommendations — the AI tab explains these, it does not
// produce them, so this panel is here even before an AI report exists.
function renderRecommendations(pane, rec) {
  if (!rec || !(rec.findings || []).length) return;
  pane.appendChild(el("h3", null, "What to do next"));

  const list = el("div", "rec-list");
  rec.findings.forEach((f) => {
    const row = el("div", `rec-row rec-${f.status}`);
    const head = el("div", "rec-head");
    head.appendChild(el("span", "rec-role", ROLE_LABELS[f.role] || f.role));
    head.appendChild(el("span", `rec-status status-${f.status}`, STATUS_LABEL[f.status] || f.status));
    head.appendChild(el("span", "muted small", `judged on ${f.metric}`));
    row.appendChild(head);
    if (f.winner_text) {
      const best = el("div", "rec-copy");
      best.appendChild(el("span", "rec-copy-label", "Best so far"));
      best.appendChild(el("span", "rec-copy-text", `“${f.winner_text}”`));
      row.appendChild(best);
    }
    row.appendChild(el("div", "rec-action", f.action));
    list.appendChild(row);
  });
  pane.appendChild(list);

  const plan = rec.next_test;
  if (!plan) return;
  const box = el("div", "next-test");
  box.appendChild(el("h4", null, "The next run"));
  if (plan.hold_fixed && plan.hold_fixed.length) {
    const fixed = el("div", "next-test-block");
    fixed.appendChild(el("div", "next-test-label", "Hold these fixed"));
    plan.hold_fixed.forEach((item) => {
      const line = el("div", "next-test-item");
      line.appendChild(el("span", "rec-role", ROLE_SINGULAR[item.role] || item.role));
      line.appendChild(el("span", "rec-copy-text", item.text ? `“${item.text}”` : item.token));
      fixed.appendChild(line);
    });
    box.appendChild(fixed);
  }
  if (plan.vary) {
    const vary = el("div", "next-test-block");
    vary.appendChild(el("div", "next-test-label", `Vary only the ${ROLE_SINGULAR[plan.vary] || plan.vary}`));
    (plan.arms || []).forEach((arm, i) => {
      const line = el("div", "next-test-item");
      line.appendChild(el("span", "rec-role", `Arm ${String.fromCharCode(65 + i)}`));
      line.appendChild(el("span", "rec-copy-text", arm.text ? `“${arm.text}”` : arm.token));
      vary.appendChild(line);
    });
    box.appendChild(vary);
  }
  box.appendChild(el("p", "muted small", plan.why));
  if (plan.per_arm_sends) {
    box.appendChild(
      el("p", "next-test-size", `Needs roughly ${plan.per_arm_sends.toLocaleString()} sends per arm before the result can be read — at the ${pct(plan.baseline)} baseline this campaign actually has.`)
    );
  }
  pane.appendChild(box);
}

// The variant table used to print `subjectLine2 + icebreaker2 + Pitch2 + CTA1`,
// which is a list of variable names, not a message. These are the emails.
function renderVariantEmails(pane, variants) {
  const rows = (variants || []).filter((v) => (v.email || {}).body || (v.email || {}).subject);
  pane.appendChild(el("h3", null, "The emails, ranked"));
  pane.appendChild(el("p", "muted small", "Attributed across the whole sequence — a reply to follow-up #2 still belongs to the variant that opened the thread."));
  if (!rows.length) {
    pane.appendChild(el("p", "muted small", "The message text isn't available yet — re-run Analyze to pull the campaign's variables."));
    pane.appendChild(
      metricTable(variants || [], [
        { label: "Variant", render: (r) => r.variant_label },
        ...RATE_COLUMNS,
      ])
    );
    return;
  }

  rows.forEach((v) => {
    const cardEl = el("details", "variant-card");
    const summary = el("summary");
    summary.appendChild(el("span", "variant-label", v.variant_label || "—"));
    summary.appendChild(el("span", "variant-subject", v.email.subject || "(no subject)"));
    const nums = el("span", "variant-nums");
    nums.appendChild(el("span", "variant-num", `${pct(v.reply_rate)} reply`));
    nums.appendChild(el("span", "variant-num", `${v.replies || 0} replies`));
    nums.appendChild(el("span", "variant-num", `${v.positives || 0} interested`));
    summary.appendChild(nums);
    summary.appendChild(verdictChip(v.reply_verdict));
    cardEl.appendChild(summary);

    const body = el("div", "variant-body");
    body.appendChild(el("div", "variant-meta", `${(v.delivered || 0).toLocaleString()} delivered · ${v.replies || 0} replies (${pct(v.reply_rate)}) · ${v.positives || 0} interested (${pct(v.positive_per_reply)} of replies)`));
    if (v.email.translated) {
      body.appendChild(el("div", "muted small", "Shown in English — this campaign went out in other languages too."));
    }
    const mail = el("div", "email-preview");
    mail.appendChild(el("div", "email-subject", `Subject: ${v.email.subject || "—"}`));
    mail.appendChild(el("div", "email-body", v.email.body || ""));
    body.appendChild(mail);

    if ((v.email.slot_breakdown || []).length) {
      const parts = el("div", "slot-parts");
      parts.appendChild(el("div", "next-test-label", "Which part is which"));
      v.email.slot_breakdown.forEach((s) => {
        const line = el("div", "slot-part");
        line.appendChild(el("span", `slot-tag slot-${s.role}`, ROLE_SINGULAR[s.role] || s.role));
        line.appendChild(el("span", "slot-token", s.token));
        line.appendChild(el("span", "slot-text", s.personalized ? `${s.text} (varies per lead)` : s.text));
        parts.appendChild(line);
      });
      body.appendChild(parts);
    }
    cardEl.appendChild(body);
    pane.appendChild(cardEl);
  });
}

// Per-component ranking. Two things changed here and both matter: the row shows
// the sentence rather than the token, and each role is scored on the number that
// can actually judge it (see campaign_analytics.ROLE_STAGE).
function renderComponents(pane, slots) {
  const STAGE_NOTE = {
    attention: "Judged on reply rate — this is what the reader sees before deciding to answer, so replies measure it. (Open tracking is off, so replies are the only proxy for “this got read”.)",
    conversion: "Judged on how many of the replies it drew were positive — only someone already reading gets this far, so its reply rate would just re-measure the subject line above it.",
  };
  pane.appendChild(el("h3", null, "By message component"));
  pane.appendChild(el("p", "muted small", "Each row pools every variant using that component, so these rest on a bigger sample than the per-email numbers above."));

  Object.entries(slots).forEach(([role, entries]) => {
    if (!entries.length) return;
    const stage = (entries[0] || {}).stage || "conversion";
    pane.appendChild(el("h4", null, ROLE_LABELS[role] || role));
    pane.appendChild(el("p", "muted small", STAGE_NOTE[stage]));

    const columns = [
      {
        label: "What it says",
        render: (r) => {
          const wrap = el("div", "slot-cell");
          wrap.appendChild(el("div", "slot-cell-text", r.text ? `“${r.text}”` : r.slot));
          const note = [r.slot];
          if ((r.used_by || []).length) note.push(`used by ${r.used_by.join(", ")}`);
          if (r.personalized) note.push("varies per lead");
          wrap.appendChild(el("div", "slot-cell-note", note.join(" · ")));
          return wrap;
        },
      },
      { label: "Delivered", render: (r) => (r.delivered || 0).toLocaleString() },
      { label: "Replies", render: (r) => `${r.replies || 0} (${pct(r.reply_rate)})` },
      { label: "Interested", render: (r) => `${r.positives || 0} (${pct(r.positive_per_reply)} of replies)` },
      { label: "Confidence", render: (r) => verdictChip(r.judged_verdict) },
    ];
    const ranked = [...entries].sort((a, b) => (b.judged_rate || 0) - (a.judged_rate || 0));
    pane.appendChild(metricTable(ranked, columns, "wrap-first"));
  });
}

function truncate(text, n) {
  const s = String(text || "");
  return s.length > n ? s.slice(0, n - 1) + "…" : s;
}

function analyzeButton(campaign, label) {
  const btn = el("button", "btn-primary", label || "Analyze this campaign");
  btn.type = "button";
  btn.addEventListener("click", async () => {
    btn.disabled = true;
    btn.textContent = "Starting…";
    await apiPost(`/api/campaigns/${campaign.id}/analyze`, { name: campaign.name, account: state.account });
    state.campaignTab = "report";
    renderCampaignDetail(campaign);
  });
  return btn;
}

async function renderCampaignReport(pane, campaign) {
  const data = await apiGet(`/api/campaigns/${campaign.id}/report`);
  pane.innerHTML = "";

  if (data.running || data.status === "running") {
    pane.appendChild(el("p", "analysis-running", data.stage || "Analyzing…"));
    pane.appendChild(el("p", "muted small", "This pulls the campaign's send history and reads every real reply — it takes a few minutes. You can switch tabs and come back."));
    clearTimeout(state.campaignPoll);
    state.campaignPoll = setTimeout(() => {
      if (state.view === "campaigns" && state.selectedCampaign === campaign.id && state.campaignTab === "report") {
        renderCampaignDetail(campaign);
      }
    }, 5000);
    return;
  }

  if (data.status === "failed") {
    pane.appendChild(el("p", "error-text", `Analysis failed: ${data.error || "unknown error"}`));
    pane.appendChild(analyzeButton(campaign, "Try again"));
    return;
  }

  if (!data.directives_md) {
    pane.appendChild(el("p", "muted", "Not analyzed yet. This reads the campaign's variants, its send results and every real reply, then writes the short brief for how to write the next one."));
    pane.appendChild(analyzeButton(campaign));
    return;
  }

  const bar = el("div", "report-bar");
  bar.appendChild(el("span", "muted small", `Generated ${data.generated_at} · ${data.model || ""}`));
  bar.appendChild(analyzeButton(campaign, "Re-analyze"));
  pane.appendChild(bar);

  // Deliberately the only thing on this tab. The long-form breakdown lives in
  // Overview (numbers) and Conversations (replies); this is the instruction
  // sheet you keep open while writing the next campaign.
  pane.appendChild(markdownBlock(data.directives_md));
}

// Minimal markdown -> HTML for the report bodies. Everything is escaped first,
// so model output can never inject markup; only the handful of constructs the
// report prompt actually asks for are then re-enabled.
function markdownBlock(md) {
  const box = el("div", "report-md");
  const html = escapeHtml(md)
    .replace(/^#### (.*)$/gm, "<h5>$1</h5>")
    .replace(/^### (.*)$/gm, "<h4>$1</h4>")
    .replace(/^## (.*)$/gm, "<h3>$1</h3>")
    .replace(/^# (.*)$/gm, "<h3>$1</h3>")
    .replace(/^\s*[-*] (.*)$/gm, "<li>$1</li>")
    .replace(/^\s*(\d+)\. (.*)$/gm, "<li>$2</li>")
    .replace(/(<li>[\s\S]*?<\/li>)(?!\s*<li>)/g, "<ul>$1</ul>")
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\n{2,}/g, "</p><p>");
  box.innerHTML = `<p>${html}</p>`;
  return box;
}

// This tab used to be a list of every thread, which answered no question — you
// still had to read 40 conversations to learn anything. The list is still here,
// but underneath the thing it was standing in for: what the conversations that
// went well have in common, and what the ones that died have in common.
async function renderCampaignConversations(pane, campaign) {
  const data = await apiGet(`/api/campaigns/${campaign.id}/responders`);
  pane.innerHTML = "";
  const people = data.responders || [];
  if (!people.length) {
    pane.appendChild(el("p", "muted", "No real replies stored yet. Auto-replies and out-of-office are deliberately excluded — run Analyze to pull the conversations."));
    pane.appendChild(analyzeButton(campaign));
    return;
  }

  renderConversationInsights(pane, data.insights || {});

  if (data.conversation_md) {
    pane.appendChild(el("h3", null, "What wins them and what loses them"));
    pane.appendChild(markdownBlock(data.conversation_md));
  } else {
    pane.appendChild(el("p", "muted small", "The written analysis of these replies hasn't been generated yet."));
    pane.appendChild(analyzeButton(campaign, "Analyze the replies"));
  }

  const browse = el("details", "extra-block");
  browse.appendChild(el("summary", null, `Read the threads (${people.length})`));
  const categories = [...new Set(people.map((p) => p.category).filter(Boolean))].sort();
  const filter = el("div", "convo-filter");
  const mkFilter = (label, value) => {
    const btn = el("button", "chip-filter" + ((state.convoFilter || "") === value ? " active" : ""), label);
    btn.type = "button";
    btn.addEventListener("click", () => {
      state.convoFilter = value;
      state.convoBrowseOpen = true;
      renderCampaignDetail(campaign);
    });
    filter.appendChild(btn);
  };
  mkFilter(`All (${people.length})`, "");
  categories.forEach((c) => mkFilter(`${c} (${people.filter((p) => p.category === c).length})`, c));
  browse.appendChild(filter);

  const shown = state.convoFilter ? people.filter((p) => p.category === state.convoFilter) : people;
  shown.forEach((person) => browse.appendChild(conversationCard(person)));
  // Keep it open across the re-render a category filter click causes, otherwise
  // filtering would slam the section shut on every click.
  browse.open = !!state.convoBrowseOpen;
  browse.addEventListener("toggle", () => { state.convoBrowseOpen = browse.open; });
  pane.appendChild(browse);
}

function renderConversationInsights(pane, insights) {
  if (!insights.analysed) {
    pane.appendChild(el("p", "muted small", "The replies haven't been read yet — run Analyze to extract what each conversation was about."));
    return;
  }

  const cards = el("div", "stat-cards");
  const card = (label, value, note) => {
    const c = el("div", "stat-card");
    c.appendChild(el("div", "stat-card-value", value));
    c.appendChild(el("div", "stat-card-label", label));
    if (note) c.appendChild(el("div", "stat-card-note", note));
    cards.appendChild(c);
  };
  card("Real replies read", String(insights.analysed), `${insights.total} threads stored`);
  card("Went positive", String(insights.won), pct(insights.win_rate));
  card("Went nowhere", String(insights.lost), "declines and dead ends");
  card("Answered more than once", String(insights.multi_turn), "a conversation, not a one-liner");
  pane.appendChild(cards);

  const splitTable = (title, note, rows, valueLabel) => {
    if (!rows || !rows.length) return;
    pane.appendChild(el("h4", null, title));
    if (note) pane.appendChild(el("p", "muted small", note));
    pane.appendChild(
      metricTable(rows, [
        { label: valueLabel, render: (r) => humanizeKey(r.value) },
        { label: "Total", render: (r) => String(r.total) },
        { label: "Went positive", render: (r) => String(r.won) },
        { label: "Went nowhere", render: (r) => String(r.lost) },
        {
          label: "",
          render: (r) => {
            const bar = el("div", "split-bar");
            const won = el("span", "split-won");
            won.style.width = `${Math.round(100 * r.win_rate)}%`;
            bar.appendChild(won);
            return bar;
          },
        },
      ], "wrap-first")
    );
  };

  pane.appendChild(el("h3", null, "What the replies were"));
  splitTable("How they answered", "The intent behind each reply, and how often that intent ended somewhere good.", insights.intents, "Intent");
  splitTable("Why they said no", "Most common objection first. This is the list to write answers for.", insights.objections, "Objection");
  splitTable("What they asked us for", "Assets leads actually requested.", insights.magnets, "Asset");

  if ((insights.by_step || []).length) {
    pane.appendChild(el("h4", null, "Which email started the conversation"));
    pane.appendChild(
      metricTable(insights.by_step, [
        { label: "Step", render: (r) => (r.step === 1 ? "1 (first email)" : `${r.step} (follow-up ${r.step - 1})`) },
        { label: "Replies", render: (r) => String(r.replies) },
        { label: "Went positive", render: (r) => String(r.won) },
        { label: "Hit rate", render: (r) => pct(r.win_rate) },
      ])
    );
  }

  const quoteBlock = (title, note, rows, cls) => {
    if (!rows || !rows.length) return;
    pane.appendChild(el("h4", null, title));
    if (note) pane.appendChild(el("p", "muted small", note));
    const box = el("div", `quote-list ${cls}`);
    rows.forEach((q) => {
      const item = el("div", "quote-item");
      item.appendChild(el("div", "quote-text", `“${q.quote}”`));
      const meta = [q.company, q.category, q.step ? `after email ${q.step}` : null].filter(Boolean);
      item.appendChild(el("div", "quote-meta", meta.join(" · ")));
      box.appendChild(item);
    });
    pane.appendChild(box);
  };

  quoteBlock("What they reacted to when it went well", "The line from our email each of these leads answered.", insights.winning_triggers, "quotes-good");
  quoteBlock("What they reacted to when it died", "Same thing, from the conversations that went nowhere.", insights.losing_triggers, "quotes-bad");
  quoteBlock("What confused them", "Misreadings and doubts — each one is a sentence worth rewriting.", insights.friction, "quotes-neutral");

  if ((insights.salvageable || []).length) {
    pane.appendChild(el("h4", null, "Worth another angle"));
    pane.appendChild(el("p", "muted small", "Declines that a different approach could still win, with the angle."));
    const box = el("div", "quote-list quotes-neutral");
    insights.salvageable.forEach((s) => {
      const item = el("div", "quote-item");
      item.appendChild(el("div", "quote-text", s.angle));
      item.appendChild(el("div", "quote-meta", [s.company, s.category].filter(Boolean).join(" · ")));
      box.appendChild(item);
    });
    pane.appendChild(box);
  }
}

// The extraction fields are machine-shaped enums ("already_have_solution").
function humanizeKey(value) {
  const s = String(value || "—").replace(/_/g, " ");
  return s.charAt(0).toUpperCase() + s.slice(1);
}

function conversationCard(person) {
  const card = el("details", "convo-card");
  const summary = el("summary");
  summary.appendChild(el("span", "convo-company", person.company || person.email || "Lead"));
  summary.appendChild(el("span", `convo-cat cat-${(person.category || "").replace(/\W+/g, "-").toLowerCase()}`, person.category || "—"));
  if (person.magnet) summary.appendChild(el("span", "convo-magnet", `wanted the ${person.magnet}`));
  if (person.replied_after_step) {
    summary.appendChild(el("span", "convo-step", person.replied_after_step === 1 ? "replied to email 1" : `replied after follow-up ${person.replied_after_step - 1}`));
  }
  if (person.variant) summary.appendChild(el("span", "convo-variant", `variant ${person.variant}`));
  card.appendChild(summary);

  (person.turns || []).forEach((turn) => {
    const bubble = el("div", `convo-turn convo-${turn.who}`);
    const who = turn.who === "us" ? (turn.step ? `Us — email ${turn.step}` : "Us") : "Them";
    bubble.appendChild(el("div", "convo-who", who));
    bubble.appendChild(el("div", "convo-text", turn.text));
    card.appendChild(bubble);
  });

  if (person.extract) {
    const e = person.extract;
    const box = el("div", "convo-extract");
    const bits = [];
    if (e.intent) bits.push(`Intent: ${e.intent}`);
    if (e.objection_type) bits.push(`Objection: ${e.objection_type}`);
    if (e.tone) bits.push(`Tone: ${e.tone}`);
    if (e.salvageable) bits.push("Salvageable");
    box.appendChild(el("div", "muted small", bits.join(" · ")));
    if (e.salvage_angle) box.appendChild(el("div", "small", e.salvage_angle));
    card.appendChild(box);
  }
  return card;
}

const VIEW_LOADERS = {
  inbox: loadInbox, scheduled: loadScheduled, archive: loadArchive,
  stats: loadStats, campaigns: loadCampaigns,
};

function setView(view) {
  state.view = view;
  clearTimeout(state.campaignPoll);
  $("status-filter").hidden = view !== "inbox";
  openStatusMenu(false);
  $("rescan-btn").hidden = view !== "inbox";
  // Campaigns and Stats don't list leads, so the lead search box would do nothing.
  document.querySelector(".search-row").classList.toggle("hidden", view === "campaigns" || view === "stats");
  $("view-inbox-btn").classList.toggle("active", view === "inbox");
  $("view-scheduled-btn").classList.toggle("active", view === "scheduled");
  $("view-archive-btn").classList.toggle("active", view === "archive");
  $("view-campaigns-btn").classList.toggle("active", view === "campaigns");
  $("view-stats-btn").classList.toggle("active", view === "stats");
  state.selected = -1;
  $("detail-body").hidden = true;
  $("detail-empty").hidden = false;
  showMobileList();
  VIEW_LOADERS[view]().catch((e) => console.error(e));
}

function renderList() {
  const list = $("lead-list");
  list.innerHTML = "";
  const archiveMode = state.view === "archive";
  const scheduledMode = state.view === "scheduled";
  const viewLabel = archiveMode ? "Archive" : scheduledMode ? "Scheduled" : "Inbox";

  $("inbox-count").textContent = `${viewLabel} (${state.leads.length})`;
  $("inbox-empty").hidden = state.leads.length > 0;
  $("inbox-empty").innerHTML = archiveMode
    ? "Nothing archived or snoozed."
    : scheduledMode
    ? "Nothing scheduled. Drafts you schedule from a lead's page will show up here."
    // There are leads, just none the filter lets through — say so, rather than
    // sending Andrew off to run a rescan that would change nothing.
    : state.allLeads.length > 0
    ? "No leads match the current status filter or search."
    : 'No leads yet. Click <strong>Rescan now</strong> — it checks every “Interested” lead and takes a couple of minutes.';

  // The inbox arrives with every hot lead first (db.list_inbox), so the two
  // headings are just the place the run ends — no client-side sorting, and
  // nothing to keep in step with the server's ordering.
  const inboxMode = !archiveMode && !scheduledMode;
  const hotCount = inboxMode ? state.leads.filter(isHot).length : 0;

  state.leads.forEach((lead, i) => {
    if (archiveMode && i === 0 && state.snoozedCount > 0) {
      list.appendChild(el("li", "list-section", "Snoozed — hidden until due"));
    }
    if (archiveMode && i === state.snoozedCount) {
      list.appendChild(el("li", "list-section", "Archived"));
    }
    if (hotCount > 0 && i === 0) {
      list.appendChild(el("li", "list-section section-hot", "🔥 Very hot — they asked to talk"));
    }
    if (hotCount > 0 && i === hotCount) {
      list.appendChild(el("li", "list-section", "Everyone else"));
    }

    const rowClass = archiveMode || scheduledMode ? "archive-row" : "cat-" + leadCategory(lead);
    const row = el("li", `lead-row ${rowClass}`);
    if (inboxMode && isHot(lead)) row.classList.add("is-hot");
    if (i === state.selected) row.classList.add("selected");
    row.dataset.index = i;

    const top = el("div", "lead-top");
    if (lead.language) top.appendChild(el("span", "lang-badge", lead.language));
    top.appendChild(el("span", "lead-name", lead.name));
    if (lead.company) top.appendChild(el("span", "lead-company", "· " + lead.company));
    if (state.view === "inbox" && lead.has_draft) top.appendChild(el("span", "ready-dot"));
    row.appendChild(top);

    // Which campaign this lead came from. It decides the niche, the language
    // and (for a template-driven client) which approved reply applies, so it
    // belongs on the row itself rather than one click away in the detail pane.
    if (lead.campaign_name) {
      const tag = el("span", "campaign-tag", lead.campaign_name);
      tag.title = lead.campaign_name; // the pill ellipsizes; hover gives the rest
      const tagLine = el("div", "campaign-line");
      tagLine.appendChild(tag);
      row.appendChild(tagLine);
    }

    if (archiveMode) {
      const isSnoozed = i < state.snoozedCount;
      const reason = isSnoozed ? `Snoozed until ${formatDayLabel(lead.snooze_until)}` : archiveLabel(lead.archive_reason);
      row.appendChild(el("div", "lead-preview", reason));
      const quickBtn = el("button", "btn-secondary row-action", isSnoozed ? "Follow up now" : "Restore");
      quickBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        const endpoint = isSnoozed ? "unsnooze" : "unarchive";
        withRowRemoval(() => apiPost(`/api/leads/${lead.campaign_id}/${lead.lead_id}/${endpoint}`, {}), i);
      });
      row.appendChild(quickBtn);
    } else if (scheduledMode) {
      row.appendChild(el("div", "lead-preview", `Scheduled for ${lead.scheduled_at}`));
      if (lead.preview) row.appendChild(el("div", "lead-preview", lead.preview));
      const actions = el("div", null);
      const sendBtn = el("button", "btn-secondary row-action", "Send now");
      sendBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        withRowRemoval(() => apiPost(`/api/drafts/${lead.draft_id}/send`, {}), i);
      });
      const cancelBtn = el("button", "btn-secondary row-action", "Cancel");
      cancelBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        withRowRemoval(() => apiPost(`/api/drafts/${lead.draft_id}/skip`, {}), i);
      });
      actions.appendChild(sendBtn);
      actions.appendChild(cancelBtn);
      row.appendChild(actions);
    } else {
      const meta = el("div", "lead-meta");
      meta.appendChild(tempChip(lead));
      const cat = leadCategory(lead);
      meta.appendChild(el("span", `state-chip cat-${cat}`, leadCategoryLabel(lead)));
      if (lead.last_message_at) meta.appendChild(el("span", "lead-time", lead.last_message_at));
      row.appendChild(meta);
      if (lead.preview) row.appendChild(el("div", "lead-preview", lead.preview));
    }

    row.addEventListener("click", () => selectLead(i));
    list.appendChild(row);
  });
}

// Whether the Export for LinkedIn button can be drawn at all: this client needs
// a spreadsheet configured (LINKEDIN_SHEET_ID) and Google connected. Loaded once
// at boot and re-read after the OAuth round trip, since that returns to /.
async function loadGoogleStatus() {
  try {
    state.google = await apiGet("/api/google/status");
  } catch (e) {
    state.google = null;  // leaves the button undrawn rather than broken
    console.error(e);
  }
}

// ---------- detail ----------
async function selectLead(i) {
  if (i < 0 || i >= state.leads.length) return;
  state.selected = i;
  state.nameNote = null;  // belongs to the rename that was just done, not to the next lead
  state.draftNote = null;
  state.exportNote = null;
  state.exportRunning = false;
  renderList();
  const row = document.querySelector(`.lead-row[data-index="${i}"]`);
  if (row) row.scrollIntoView({ block: "nearest" });

  const lead = state.leads[i];
  $("detail-empty").hidden = true;
  const body = $("detail-body");
  body.hidden = false;
  body.innerHTML = '<div class="loading-note"><span class="spinner"></span>Loading conversation…</div>';
  showMobileDetail();

  try {
    const data = await apiGet(`/api/leads/${lead.campaign_id}/${lead.lead_id}`);
    state.detail = data;
    renderDetail();
    if (data.generating) pollGeneration(lead.campaign_id, lead.lead_id);
  } catch (e) {
    body.innerHTML = "";
    if (isMobileLayout()) {
      const backBtn = el("button", "btn-back", "← Back");
      backBtn.type = "button";
      backBtn.addEventListener("click", goBackToMobileList);
      body.appendChild(backBtn);
    }
    body.appendChild(el("div", "error-note", `Couldn't load this lead: ${e.message}`));
  }
}

function renderDetail() {
  const { lead, thread } = state.detail;
  const body = $("detail-body");
  body.innerHTML = "";

  const header = el("div", "detail-header");
  if (isMobileLayout()) {
    const backBtn = el("button", "btn-back", "← Back");
    backBtn.type = "button";
    backBtn.addEventListener("click", goBackToMobileList);
    header.appendChild(backBtn);
  }
  const nameWrap = el("span", "detail-name-wrap");
  nameWrap.appendChild(el("h2", null, lead.name));
  const editNameBtn = el("button", "btn-edit-name", "✎ Rename");
  editNameBtn.type = "button";
  editNameBtn.title = "Edit first name";
  editNameBtn.setAttribute("aria-label", "Edit this lead's first name");
  editNameBtn.addEventListener("click", editLeadName);
  nameWrap.appendChild(editNameBtn);
  header.appendChild(nameWrap);
  if (lead.language) {
    header.appendChild(
      el("span", "lang-badge-prominent", `🌐 ${lead.language_name || lead.language}`)
    );
  }
  header.appendChild(tempChip(lead));
  const headCat = leadCategory(lead);
  const headLabel = leadCategoryLabel(lead);
  header.appendChild(el("span", `state-chip cat-${headCat}`, headLabel));
  // Only worth a second badge when the chip is showing something other than
  // Smartlead's own words for it (an app-only sub-state like "Awaiting your
  // reply", or a friendlier label than the raw category name) — otherwise
  // it's the same text twice, which is what leadCategoryLabel's fallback to
  // smartlead_category already produces for a category with no chip label.
  if (lead.smartlead_category && lead.smartlead_category !== headLabel) {
    const badge = el("span", "smartlead-cat-badge", `Smartlead: ${lead.smartlead_category}`);
    badge.title = "The category Smartlead itself currently has this lead filed under";
    header.appendChild(badge);
  }
  body.appendChild(header);
  // Company/email and the campaign share one .detail-sub block so the two
  // lines sit together, rather than each carrying the class's bottom margin.
  const sub = el("div", "detail-sub");
  sub.appendChild(el("div", null, [lead.company, lead.email].filter(Boolean).join(" · ")));
  if (lead.campaign_name) {
    const line = el("div", "campaign-line");
    line.appendChild(el("span", null, "Campaign:"));
    const tag = el("span", "campaign-tag", lead.campaign_name);
    tag.title = lead.campaign_name;
    line.appendChild(tag);
    sub.appendChild(line);
  }
  body.appendChild(sub);
  if (lead.email_display_name && lead.email_display_name !== lead.name) {
    body.appendChild(el("div", "detail-sub muted", `Smartlead shows their inbox name as "${lead.email_display_name}"`));
  }
  if (state.nameNote) {
    body.appendChild(el("div", "detail-sub name-note", state.nameNote));
  }

  body.appendChild(renderResearchPanel(lead));
  body.appendChild(renderLeadActionsBar(lead));

  // thread — each message has an "English" checkbox (per-message, so a click
  // only pays for what's actually read), plus a "Show whole thread in English"
  // checkbox that batches whatever isn't already cached into a single call. A
  // message that already has a cached translation (m.english) defaults to
  // English; toggling never re-calls the API for something already fetched.
  const threadActions = el("div", "thread-actions");
  const threadToggle = el("label", "thread-lang-toggle");
  const threadCb = el("input", "thread-lang-cb");
  threadCb.type = "checkbox";
  threadCb.id = "thread-english-toggle";
  threadToggle.appendChild(threadCb);
  threadToggle.appendChild(document.createTextNode(" Show whole thread in English"));
  threadCb.addEventListener("change", () => setThreadLang(threadCb));
  threadActions.appendChild(threadToggle);
  body.appendChild(threadActions);

  const tc = el("div", "thread");
  tc.id = "thread";
  thread.forEach((m, idx) => {
    const wrap = el("div", `msg ${m.who}`);
    const meta = el("div", "msg-meta");
    meta.appendChild(document.createTextNode(`${m.name} · ${m.time} `));
    // The mailbox this message actually came from: for a lead's reply that's
    // often a real person answering a cold email sent to a generic info@.
    if (m.from_email) meta.appendChild(el("span", "msg-from", m.from_email));
    const toggle = el("label", "msg-lang-toggle");
    const cb = el("input", "msg-lang-cb");
    cb.type = "checkbox";
    toggle.appendChild(cb);
    toggle.appendChild(document.createTextNode(" English"));
    meta.appendChild(toggle);
    wrap.appendChild(meta);
    const bubble = el("div", "bubble");
    bubble.dataset.index = idx;
    bubble.dataset.original = m.html;
    const hasEnglish = !!m.english;
    if (hasEnglish) bubble.dataset.translatedHtml = m.english;
    bubble.dataset.mode = hasEnglish ? "en" : "orig";
    bubble.innerHTML = hasEnglish ? m.english : m.html;
    cb.checked = hasEnglish;
    cb.addEventListener("change", () => setMessageLang(bubble, cb, idx));
    wrap.appendChild(bubble);
    tc.appendChild(wrap);
  });
  body.appendChild(tc);
  syncThreadToggle();

  renderDraftSection(body);
}

function archiveLabel(reason) {
  if (!reason || reason === "manual") return "Archived";
  return reason; // an actual Smartlead category name, e.g. "Wrong Person"
}

// ---------- lead temperature (cold / warm / very hot) ----------

function leadTemp(lead) {
  return TEMP[lead.temperature] ? lead.temperature : "cold";
}

function isHot(lead) {
  // Must mirror db.list_inbox's sort exactly: `temperature = 'hot' AND status
  // != 'booked'`. A booked lead's meeting is the outcome, so it's excluded
  // from the hot tier there — but this used to check temperature alone, so a
  // hot-then-booked lead was counted as hot here while the server had
  // already sorted it further down. The mismatch inflated hotCount in
  // renderList, which pushed the "Everyone else" divider one row too far and
  // put the next lead in line — a warm or cold one, whatever actually sat at
  // that position — visibly under the "🔥 Very hot" header.
  return leadTemp(lead) === "hot" && lead.category !== "booked";
}

// The rating, with *why* it was rated that on hover — a 🔥 that can't be
// questioned is a 🔥 that gets ignored, and the reason is one line the
// classifier already wrote (or "set by hand" when Andrew overrode it).
function tempChip(lead) {
  const temp = leadTemp(lead);
  const chip = el("span", `temp-chip temp-${temp}`, TEMP[temp]);
  const why = lead.temperature_reason || "";
  chip.title = why ? `${TEMP[temp]} — ${why}` : TEMP[temp];
  return chip;
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

// The LinkedIn export lives above the archived/snoozed early returns on
// purpose: a lead that went quiet and got archived or snoozed is exactly the
// one worth chasing on LinkedIn, and both of those branches return early.
function renderExportControl() {
  const g = state.google;
  if (!g || !g.configured) return null;

  if (!g.connected) {
    const link = el("a", "btn-secondary btn-link", "Connect Google Sheets");
    link.href = g.connect_url;
    link.title = "Authorize this app to write to your LinkedIn outreach sheet";
    return link;
  }

  const wrap = el("span", "export-linkedin");
  const btn = el("button", "btn-secondary");
  btn.type = "button";
  btn.title = "Add this lead to the LinkedIn outreach sheet, in their sender's tab";
  if (state.exportRunning) {
    btn.disabled = true;
    btn.appendChild(el("span", "spinner"));
    btn.appendChild(document.createTextNode("Exporting…"));
  } else {
    btn.textContent = "Export for LinkedIn";
    btn.addEventListener("click", exportLeadForLinkedIn);
  }
  wrap.appendChild(btn);

  if (state.exportNote) {
    const { kind, text } = state.exportNote;
    const cls = kind === "error" ? "error-note" : kind === "warn" ? "status-banner warn" : "status-banner";
    wrap.appendChild(el("span", cls, text));
  }
  return wrap;
}

async function exportLeadForLinkedIn() {
  const { cid, lid } = currentLeadIds();
  state.exportNote = null;
  state.exportRunning = true;
  refreshLeadActions();
  try {
    await apiPost(`/api/leads/${cid}/${lid}/export-linkedin`, {});
  } catch (e) {
    state.exportRunning = false;
    state.exportNote = { kind: "error", text: e.message };
    refreshLeadActions();
    return;
  }
  pollExport(cid, lid);
}

// Polls until the background export finishes. Bails out if the user has moved
// to another lead — the note belongs to the lead it was started from.
async function pollExport(cid, lid) {
  let data;
  try {
    data = await apiGet(`/api/leads/${cid}/${lid}/export-linkedin`);
  } catch (e) {
    data = { running: false, error: e.message };
  }
  const open = currentLead();
  if (!open || open.campaign_id !== cid || open.lead_id !== lid) return;

  if (data.running) {
    setTimeout(() => pollExport(cid, lid), 2000);
    return;
  }
  state.exportRunning = false;
  const r = data.result;
  if (data.error) {
    state.exportNote = { kind: "error", text: data.error };
  } else if (r && r.status === "duplicate") {
    state.exportNote = {
      kind: "warn",
      text: `Already in the ${r.tab} tab${r.row ? ` (row ${r.row})` : ""} — nothing added`,
    };
  } else if (r) {
    const linkedin = r.linkedin_found ? "" : ", no LinkedIn URL found";
    state.exportNote = {
      kind: "ok",
      text: `Added to the ${r.tab} tab${r.row ? ` (row ${r.row})` : ""}${linkedin}`,
    };
  } else {
    state.exportNote = { kind: "error", text: "The export finished with no result." };
  }
  refreshLeadActions();
}

// Swap just the actions bar, never re-render the whole detail pane: the draft
// editor lives further down it and holds unsaved typing, so a full renderDetail
// to show a spinner would throw away whatever Andrew was in the middle of
// writing. Same hot-swap the research panel uses after a regenerate.
function refreshLeadActions() {
  const old = $("lead-actions");
  if (old && state.detail) old.replaceWith(renderLeadActionsBar(state.detail.lead));
}

function renderLeadActionsBar(lead) {
  const bar = el("div", "lead-actions");
  bar.id = "lead-actions";

  const exportControl = renderExportControl();
  if (exportControl) bar.appendChild(exportControl);

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
    bar.appendChild(el("span", "status-banner", `Snoozed until ${formatDayLabel(lead.snooze_until)}`));
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

  bar.appendChild(renderTemperatureSelect(lead));

  bar.appendChild(renderCategorySelect(lead));

  bar.appendChild(renderSnoozeControl());

  return bar;
}

// The common snooze lengths, one click each. Every option spells out the date
// it lands on, so the choice is made and applied in a single step: the control
// used to be a button that opened a date field that needed a Confirm — three
// interactions to set a date that's reversible from the Archive view anyway.
const SNOOZE_PRESETS = [
  { label: "Tomorrow", days: 1 },
  { label: "In 3 days", days: 3 },
  { label: "In a week", days: 7 },
  { label: "In 2 weeks", days: 14 },
  { label: "In a month", days: 30 },
];

function renderSnoozeControl() {
  const wrap = el("div", "snooze-control");

  const select = el("select", "cat-select snooze-select");
  select.title = "Hide this lead from the inbox until a date";
  const placeholder = document.createElement("option");
  placeholder.textContent = "Snooze until…";
  placeholder.value = "";
  placeholder.disabled = true;
  placeholder.selected = true;
  select.appendChild(placeholder);
  SNOOZE_PRESETS.forEach((preset) => {
    const date = dateInDays(preset.days);
    const opt = document.createElement("option");
    opt.value = date;
    opt.textContent = `${preset.label} · ${formatDayLabel(date)}`;
    select.appendChild(opt);
  });
  const customOpt = document.createElement("option");
  customOpt.value = "custom";
  customOpt.textContent = "Pick a date…";
  select.appendChild(customOpt);

  const picker = el("span", "snooze-picker");
  picker.hidden = true;
  const dateInput = el("input");
  dateInput.type = "date";
  // Tomorrow, not today: a snooze until today is already due, so it would only
  // bounce the lead back to the top of the inbox it was being hidden from.
  dateInput.min = dateInDays(1);
  const cancelBtn = el("button", "btn-secondary", "Cancel");

  select.addEventListener("change", () => {
    const value = select.value;
    select.value = "";
    if (value === "custom") {
      select.hidden = true;
      picker.hidden = false;
      dateInput.focus();
      // Opens the browser's own calendar right away, so "Pick a date…" costs
      // one click like the presets do. Not every browser allows it from a
      // change event; the field is focused either way.
      if (dateInput.showPicker) {
        try { dateInput.showPicker(); } catch (e) { /* ignore */ }
      }
      return;
    }
    if (value) snoozeLead(value);
  });
  // Picking a day in the calendar is the confirmation — there's no second
  // button to hunt for.
  dateInput.addEventListener("change", () => {
    if (dateInput.value) snoozeLead(dateInput.value);
  });
  cancelBtn.addEventListener("click", () => {
    picker.hidden = true;
    select.hidden = false;
  });

  picker.appendChild(dateInput);
  picker.appendChild(cancelBtn);
  wrap.appendChild(select);
  wrap.appendChild(picker);
  return wrap;
}

function currentLeadIds() {
  const lead = currentLead();
  return { cid: lead.campaign_id, lid: lead.lead_id };
}

// Andrew's manual fix for a wrong/imported first name — see the muted
// "Smartlead shows their inbox name as ..." line rendered next to it, which
// is what this is meant to be checked against.
//
// The rename also goes back to Smartlead (see main.api_set_lead_name). That
// half can fail on its own while the local rename stands, so the server says
// which happened and the answer is shown under the name rather than thrown as
// an alert: nothing is broken, but "renamed here only" is not the same as
// "renamed", and silently treating them alike is what made the two drift.
async function editLeadName() {
  const lead = state.detail.lead;
  const next = window.prompt("Edit this lead's first name:", lead.name || "");
  if (next == null) return;
  const trimmed = next.trim();
  if (!trimmed || trimmed === lead.name) return;
  const { cid, lid } = currentLeadIds();
  let result;
  try {
    result = await apiPost(`/api/leads/${cid}/${lid}/name`, { name: trimmed });
  } catch (e) {
    alert("Couldn't update name: " + e.message);
    return;
  }
  state.nameNote = (result && result.warning) || null;
  lead.name = trimmed;
  const row = currentLead();
  if (row) row.name = trimmed;
  renderList();
  renderDetail();
}

// Andrew's override of the automatic rating. Picking one locks it, so the next
// scan can't quietly overrule him — the same deal as ✎ Rename and name_locked.
// "Let the AI decide" hands it back and re-rates on the spot.
function renderTemperatureSelect(lead) {
  const select = el("select", "cat-select temp-select");
  const temp = leadTemp(lead);
  select.title = lead.temperature_locked
    ? "You set this rating by hand — the scan won't change it"
    : "How hot this lead is, rated from their own messages";
  TEMP_ORDER.forEach((value) => {
    const opt = document.createElement("option");
    opt.value = value;
    opt.textContent = TEMP[value];
    opt.selected = value === temp;
    select.appendChild(opt);
  });
  const auto = document.createElement("option");
  auto.value = "auto";
  auto.textContent = "↻ Let the AI decide";
  select.appendChild(auto);
  select.addEventListener("change", () => setTemperature(select.value));
  return select;
}

async function setTemperature(value) {
  const { cid, lid } = currentLeadIds();
  let result;
  try {
    result = await apiPost(`/api/leads/${cid}/${lid}/temperature`, { temperature: value });
  } catch (e) {
    alert("Couldn't change how hot this lead is: " + e.message);
    renderDetail();  // put the dropdown back to what's actually stored
    return;
  }
  const lead = state.detail.lead;
  lead.temperature = result.temperature;
  lead.temperature_reason = result.reason || "set by hand";
  lead.temperature_locked = !!result.locked;
  const row = currentLead();
  if (row) {
    row.temperature = lead.temperature;
    row.temperature_reason = lead.temperature_reason;
    row.temperature_locked = lead.temperature_locked;
  }
  renderDetail();
  // The inbox is sorted by this, so the list has to be re-fetched rather than
  // repainted: a lead that just turned 🔥 belongs at the top of it, not in the
  // position it held a second ago. autoRefreshInbox re-finds the open lead
  // afterwards, which a bare loadInbox would not — state.selected is an index.
  autoRefreshInbox().catch((e) => console.error(e));
}

function renderCategorySelect(lead) {
  const select = el("select", "cat-select");
  const current = lead && lead.smartlead_category;
  select.title = current
    ? `Currently in Smartlead: ${current} — change status`
    : "Change status in Smartlead";
  const placeholder = document.createElement("option");
  placeholder.textContent = current ? `Change status (currently: ${current})` : "Change status…";
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

// Mirrors app.scheduler.norm_category_name — the account's real category is
// "Meeting-Booked" but config/humans write it differently; compare ignoring
// case and punctuation so either form is recognised here.
function normCategoryName(s) {
  return (s || "").toLowerCase().replace(/[^a-z0-9]/g, "");
}
const BOOKED_CATEGORY_NORM = "meetingbooked";

async function changeCategory(name) {
  const booking = normCategoryName(name) === BOOKED_CATEGORY_NORM;
  const pauseNote = PAUSE_CATEGORIES.has(name) ? " and pause their sequence" : "";
  const consequence = booking ? "" : " This removes them from your inbox.";
  if (!confirm(`Set Smartlead category to "${name}"${pauseNote}?${consequence}`)) return;
  const { cid, lid } = currentLeadIds();

  if (!booking) {
    await withRowRemoval(() => apiPost(`/api/leads/${cid}/${lid}/category`, { category_name: name }));
    return;
  }

  // A booked lead stays in the inbox with the green "Meeting booked ✅" badge
  // instead of being archived like every other category (main.api_set_category
  // records the booking via db.mark_lead_booked rather than archiving). Update
  // the row in place rather than fading it out via withRowRemoval, or it
  // disappears from view until the next scan un-archives it again.
  const lead = currentLead();
  try {
    await apiPost(`/api/leads/${cid}/${lid}/category`, { category_name: name });
  } catch (e) {
    alert(e.message);
    return;
  }
  lead.category = "booked";
  lead.archived_at = null;
  lead.archive_reason = null;
  lead.snooze_until = null;
  applyFilter();
  const idx = state.leads.indexOf(lead);
  if (idx === -1) {
    // Filtered out by the status filter or search — same empty-selection
    // path withRowRemoval takes when a row's removal empties the list.
    state.selected = -1;
    renderList();
    $("detail-body").hidden = true;
    $("detail-empty").hidden = false;
    showMobileList();
    return;
  }
  state.selected = idx;
  renderList();
  renderDetail();
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
  select.className = "model-select";
  fillModelSelect(select, state.defaultModel);
  modelLabel.appendChild(select);
  wrap.appendChild(modelLabel);

  // Trying models is the point of the picker, so promoting the one that worked
  // to "always use this" is one click right next to it, not a settings page.
  const setDefaultBtn = el("button", "btn-secondary btn-set-default");
  setDefaultBtn.type = "button";
  setDefaultBtn.dataset.selectId = "gen-model-select";
  setDefaultBtn.addEventListener("click", () => setDefaultModel(select, setDefaultBtn));
  syncSetDefaultButton(setDefaultBtn);
  wrap.appendChild(setDefaultBtn);

  const wsLabel = el("label", "gen-websearch");
  const wsCheckbox = document.createElement("input");
  wsCheckbox.type = "checkbox";
  wsCheckbox.id = "gen-websearch-toggle";
  wsCheckbox.checked = !state.detail.lead.research_summary;
  wsLabel.appendChild(wsCheckbox);
  wsLabel.appendChild(document.createTextNode(" Web search"));
  wrap.appendChild(wsLabel);

  // Web search only exists on the Anthropic path (OpenRouter drafts have no
  // tools — see app/openrouter.py), so the toggle follows the picked model
  // rather than silently doing nothing.
  const syncWebSearch = () => {
    const picked = state.models.find((m) => m.id === select.value);
    const supported = !picked || picked.web_search;
    wsCheckbox.disabled = !supported;
    if (!supported) wsCheckbox.checked = false;
    wsLabel.title = supported
      ? ""
      : "This model has no web research — it writes from the thread and any research already saved for this lead.";
    wsLabel.classList.toggle("is-disabled", !supported);
  };
  select.addEventListener("change", () => {
    syncSetDefaultButton(setDefaultBtn);
    syncWebSearch();
  });
  syncWebSearch();

  return wrap;
}

function renderQuickFollowups() {
  const wrap = el("div", "quick-followups");
  wrap.appendChild(el("div", "quick-followups-label", "Skip generation and use a pre-written template:"));
  const btn = el("button", "btn-secondary btn-templates", "Choose a template…");
  btn.type = "button";
  btn.addEventListener("click", openTemplatesModal);
  wrap.appendChild(btn);
  return wrap;
}

function closeTemplatesModal() {
  const overlay = $("templates-modal-overlay");
  if (overlay) overlay.remove();
  document.body.style.overflow = "";
  document.removeEventListener("keydown", onTemplatesModalKeydown);
}

function onTemplatesModalKeydown(e) {
  if (e.key === "Escape") closeTemplatesModal();
}

// {name}/{company} are stored raw and only resolved for display — the edit form
// deliberately shows the raw placeholders so they survive a round of editing.
// Values come from the server (`lead.placeholders`, built by
// message_templates.placeholders_for) so this preview is the exact string that
// gets sent — the two used to be computed separately and only agreed by
// accident. Anything in braces that isn't in the map is DELETED rather than
// left alone: a template using a placeholder this app doesn't know about used
// to mail the lead `{companyNickname}` verbatim.
function fillPlaceholders(text) {
  const values = ((state.detail || {}).lead || {}).placeholders || {};
  return String(text || "")
    .replace(/\{([A-Za-z0-9_]+)\}/g, (_, key) => (key in values ? values[key] : ""))
    .replace(/[ \t]{2,}/g, " ")
    .replace(/ +([,.!?])/g, "$1")
    .trim();
}

async function openTemplatesModal() {
  if ($("templates-modal-overlay")) return;

  const overlay = el("div", "modal-overlay");
  overlay.id = "templates-modal-overlay";
  overlay.addEventListener("click", (e) => {
    if (e.target === overlay) closeTemplatesModal();
  });

  const modal = el("div", "modal templates-modal");
  const header = el("div", "modal-header");
  const heading = el("div", "modal-heading");
  heading.appendChild(el("h3", null, "Message templates"));
  heading.appendChild(
    el("div", "modal-sub", "Drop one straight in as a draft — no AI call. {name} and {company} are filled in automatically.")
  );
  header.appendChild(heading);
  const closeBtn = el("button", "modal-close", "×");
  closeBtn.type = "button";
  closeBtn.setAttribute("aria-label", "Close");
  closeBtn.addEventListener("click", closeTemplatesModal);
  header.appendChild(closeBtn);
  modal.appendChild(header);

  const list = el("div", "templates-list");
  list.id = "templates-list";
  list.innerHTML = '<div class="loading-note"><span class="spinner"></span>Loading templates…</div>';
  modal.appendChild(list);

  const footer = el("div", "modal-footer");
  const addBtn = el("button", "btn-secondary", "+ New template");
  addBtn.type = "button";
  addBtn.addEventListener("click", () => {
    const form = renderTemplateForm(null);
    $("templates-list").appendChild(form);
    form.scrollIntoView({ block: "nearest" });
    form.querySelector("input").focus();
  });
  footer.appendChild(addBtn);
  modal.appendChild(footer);

  overlay.appendChild(modal);
  document.body.appendChild(overlay);
  document.body.style.overflow = "hidden";
  document.addEventListener("keydown", onTemplatesModalKeydown);

  try {
    const data = await apiGet("/api/templates");
    state.templates = data.templates;
    renderTemplatesList();
  } catch (e) {
    list.innerHTML = `<div class="error-note">Couldn't load templates: ${e.message}</div>`;
  }
}

function renderTemplatesList() {
  const list = $("templates-list");
  if (!list) return;
  list.innerHTML = "";
  if (!state.templates.length) {
    list.appendChild(el("div", "template-empty", "No templates yet — add one below."));
    return;
  }
  state.templates.forEach((tpl, i) => {
    list.appendChild(renderTemplateCard(tpl, i, state.templates.length));
  });
}

function renderTemplateCard(tpl, index, total) {
  const card = el("div", "template-card");
  const head = el("div", "template-head");
  head.appendChild(el("div", "template-label", tpl.label || "Untitled template"));

  const actions = el("div", "template-actions");
  const useBtn = el("button", "btn-send btn-quick", "Use");
  useBtn.type = "button";
  useBtn.addEventListener("click", () => {
    closeTemplatesModal();
    quickFollowup(tpl.text);
  });
  actions.appendChild(useBtn);

  const iconBtn = (glyph, title, handler, disabled) => {
    const b = el("button", "btn-icon", glyph);
    b.type = "button";
    b.title = title;
    b.setAttribute("aria-label", title);
    b.disabled = !!disabled;
    if (!disabled) b.addEventListener("click", handler);
    actions.appendChild(b);
  };
  iconBtn("✎", "Edit", () => card.replaceWith(renderTemplateForm(tpl)));
  iconBtn("▲", "Move up", () => moveTemplate(tpl.id, "up"), index === 0);
  iconBtn("▼", "Move down", () => moveTemplate(tpl.id, "down"), index === total - 1);
  iconBtn("🗑", "Delete", () => deleteTemplate(tpl));
  head.appendChild(actions);
  card.appendChild(head);

  // Clamped to a few lines so a long template doesn't push the rest off screen;
  // clicking the preview expands it in place.
  const preview = el("div", "template-preview", fillPlaceholders(tpl.text));
  preview.title = "Click to expand";
  preview.addEventListener("click", () => preview.classList.toggle("expanded"));
  card.appendChild(preview);
  return card;
}

// One form for both "edit" (tpl given) and "new" (tpl null) — same fields, the
// only difference is PATCH vs POST and what replaces it on cancel.
function renderTemplateForm(tpl) {
  const form = el("div", "template-card template-form");

  const labelInput = el("input");
  labelInput.type = "text";
  labelInput.placeholder = "Name (optional, e.g. 'Breakup — closing this file')";
  labelInput.value = tpl ? tpl.label : "";
  form.appendChild(labelInput);

  const textArea = el("textarea");
  textArea.placeholder = "Message text. Use {name} and {company} as placeholders.";
  textArea.value = tpl ? tpl.text : "";
  form.appendChild(textArea);

  const err = el("div", "error-note");
  err.hidden = true;
  form.appendChild(err);

  const row = el("div", "template-form-actions");
  const saveBtn = el("button", "btn-send btn-quick", "Save");
  saveBtn.type = "button";
  saveBtn.addEventListener("click", async () => {
    const text = textArea.value.trim();
    if (!text) {
      err.textContent = "Template text is required.";
      err.hidden = false;
      return;
    }
    saveBtn.disabled = true;
    const payload = { label: labelInput.value.trim(), text };
    try {
      const data = tpl
        ? await apiPatch(`/api/templates/${tpl.id}`, payload)
        : await apiPost("/api/templates", payload);
      state.templates = data.templates;
      renderTemplatesList();
    } catch (e) {
      saveBtn.disabled = false;
      err.textContent = `Couldn't save: ${e.message}`;
      err.hidden = false;
    }
  });
  row.appendChild(saveBtn);

  const cancelBtn = el("button", "btn-secondary btn-quick", "Cancel");
  cancelBtn.type = "button";
  cancelBtn.addEventListener("click", () => (tpl ? renderTemplatesList() : form.remove()));
  row.appendChild(cancelBtn);
  form.appendChild(row);
  return form;
}

async function moveTemplate(id, direction) {
  try {
    const data = await apiPost(`/api/templates/${id}/move`, { direction });
    state.templates = data.templates;
    renderTemplatesList();
  } catch (e) {
    alert("Couldn't reorder: " + e.message);
  }
}

async function deleteTemplate(tpl) {
  const name = tpl.label || fillPlaceholders(tpl.text).slice(0, 40) + "…";
  if (!window.confirm(`Delete this template?\n\n${name}`)) return;
  try {
    const data = await apiDelete(`/api/templates/${tpl.id}`);
    state.templates = data.templates;
    renderTemplatesList();
  } catch (e) {
    alert("Couldn't delete: " + e.message);
  }
}

async function quickFollowup(template) {
  const { cid, lid } = currentLeadIds();
  const firstName = (state.detail.lead.name || "").split(" ")[0] || "there";
  const company = state.detail.lead.company || "your business";
  const text = template.replace(/\{name\}/g, firstName).replace(/\{company\}/g, company);
  const section = $("draft-section");
  section.innerHTML = '<div class="loading-note"><span class="spinner"></span>Adding follow-up…</div>';
  let data;
  try {
    // Send the Generate dropdown's current pick so a template is localized by
    // the same model that would have written the draft. The server falls back
    // to the "Translating templates" role when this is absent.
    const modelSel = $("gen-model-select");
    data = await apiPost(`/api/leads/${cid}/${lid}/quick-draft`, {
      text,
      model: modelSel ? modelSel.value : undefined,
    });
  } catch (e) {
    section.innerHTML = `<div class="error-note">Could not add follow-up: ${e.message}</div>`;
    return;
  }
  // Set when the template went out in English and shouldn't have — the one
  // failure this path has, and the only one it can't show as an error, since a
  // draft was still created and looks perfectly fine until you read it.
  state.draftNote = data.warning || null;
  state.detail = data;
  renderList();
  const body = $("detail-body");
  const oldPanel = $("research-panel");
  if (oldPanel) oldPanel.replaceWith(renderResearchPanel(state.detail.lead));
  $("draft-section").remove();
  renderDraftSection(body);
}

async function composeDraft() {
  const { cid, lid } = currentLeadIds();
  state.draftNote = null;
  const section = $("draft-section");
  section.innerHTML = '<div class="loading-note"><span class="spinner"></span>Opening a blank draft…</div>';
  let data;
  try {
    data = await apiPost(`/api/leads/${cid}/${lid}/compose`, {});
  } catch (e) {
    section.innerHTML = `<div class="error-note">Could not open a draft: ${e.message}</div>`;
    return;
  }
  state.detail = data;
  renderList();
  $("draft-section").remove();
  renderDraftSection($("detail-body"));
  const editor = $("draft-editor");
  if (editor) {
    editor.focus();
    // A blank manual draft opens with just the signature already in the box —
    // put the caret at the very start so typing lands before it, not after.
    placeCursorAtStart(editor);
  }
}

function placeCursorAtStart(editor) {
  const range = document.createRange();
  range.setStart(editor, 0);
  range.collapse(true);
  const sel = window.getSelection();
  sel.removeAllRanges();
  sel.addRange(range);
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

// ---------- images ----------
// Widest an image should ever render in an email client. Also the reference
// width "100%" means in the resize bar, so a huge screenshot doesn't count as
// 100% at 3000px and blow the layout out in Outlook.
const MAX_EMAIL_IMG_WIDTH = 600;
const IMAGE_URL_RE = /^https?:\/\/\S+\.(png|jpe?g|gif|webp)(\?\S*)?$/i;
// A whole-clipboard bare URL (nothing else pasted alongside it).
const PLAIN_URL_RE = /^(https?:\/\/|www\.)\S+$/i;

function imageBaseWidth(img) {
  return Math.min(img.naturalWidth || MAX_EMAIL_IMG_WIDTH, MAX_EMAIL_IMG_WIDTH);
}

// Outlook ignores CSS width on images, so the pixel size has to go on the
// width *attribute* as well; the inline max-width keeps it from overflowing
// narrow/mobile clients that do honour CSS.
function setImageWidth(img, pct) {
  const px = Math.max(40, Math.round((imageBaseWidth(img) * pct) / 100));
  img.dataset.widthPct = String(pct);
  img.setAttribute("width", String(px));
  img.style.width = px + "px";
  img.style.height = "auto";
  img.style.maxWidth = "100%";
  onEditorInput();
  positionImageBar();
}

function insertImageAtCursor(url) {
  const editor = $("draft-editor");
  editor.focus();
  const marker = "pending-img-" + Date.now();
  document.execCommand(
    "insertHTML",
    false,
    `<img id="${marker}" src="${escapeHtml(url)}" style="max-width:100%;height:auto;">&nbsp;`
  );
  const img = document.getElementById(marker);
  if (!img) return;
  img.removeAttribute("id");
  // naturalWidth is 0 until the image has actually loaded, so the default
  // sizing has to wait for it — otherwise every image would come in at 600px.
  const apply = () => {
    setImageWidth(img, 100);
    selectEditorImage(img);
  };
  if (img.complete && img.naturalWidth) apply();
  else img.addEventListener("load", apply, { once: true });
  onEditorInput();
}

async function uploadAndInsertImage(file) {
  const editor = $("draft-editor");
  if (editor) editor.classList.add("uploading");
  try {
    const fd = new FormData();
    fd.append("file", file);
    const r = await fetch("/api/uploads", { method: "POST", body: fd });
    const data = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(data.error || "Upload failed");
    insertImageAtCursor(data.url);
  } catch (e) {
    alert("Couldn't upload that image: " + e.message);
  } finally {
    if (editor) editor.classList.remove("uploading");
  }
}

function pickImageFile() {
  const input = document.createElement("input");
  input.type = "file";
  input.accept = "image/png,image/jpeg,image/gif,image/webp";
  input.addEventListener("change", () => {
    if (input.files && input.files[0]) uploadAndInsertImage(input.files[0]);
  });
  input.click();
}

function firstImageFile(list) {
  return Array.from(list || []).find((f) => f && f.type && f.type.startsWith("image/")) || null;
}

// Paste: a screenshot straight off the clipboard gets uploaded and hosted
// here; a bare image URL (the old imgur "open image in new tab, copy address"
// route) becomes a real <img> instead of a line of link text, so it can be
// resized like any other image.
async function onEditorPaste(e) {
  const items = Array.from((e.clipboardData && e.clipboardData.items) || []);
  const fileItem = items.find((i) => i.kind === "file" && i.type.startsWith("image/"));
  if (fileItem) {
    const file = fileItem.getAsFile();
    if (file) {
      e.preventDefault();
      await uploadAndInsertImage(file);
      return;
    }
  }
  const text = ((e.clipboardData && e.clipboardData.getData("text/plain")) || "").trim();
  if (IMAGE_URL_RE.test(text)) {
    e.preventDefault();
    insertImageAtCursor(text);
    return;
  }
  // A pasted calendly/any other link should land as a clickable anchor, not
  // as plain text the lead has to copy out by hand.
  if (PLAIN_URL_RE.test(text) && !e.clipboardData.getData("text/html")) {
    e.preventDefault();
    const href = /^https?:/i.test(text) ? text : "https://" + text;
    document.execCommand(
      "insertHTML",
      false,
      `<a href="${escapeHtml(href)}" target="_blank" rel="noopener">${escapeHtml(text)}</a>&nbsp;`
    );
    onEditorInput();
  }
}

function onEditorDrop(e) {
  const file = firstImageFile(e.dataTransfer && e.dataTransfer.files);
  if (!file) return;
  e.preventDefault();
  uploadAndInsertImage(file);
}

// ---------- image resize bar ----------
// A floating bar pinned above whichever image is selected. Presets cover the
// common cases in one click; the slider is the "drag to size" fallback.
function ensureImageBar() {
  let bar = $("image-bar");
  if (bar) return bar;
  bar = el("div", "image-bar");
  bar.id = "image-bar";
  bar.addEventListener("mousedown", (e) => e.preventDefault()); // keep editor selection

  [["S", 25], ["M", 50], ["L", 75], ["Full", 100]].forEach(([label, pct]) => {
    const b = el("button", "image-bar-btn", label);
    b.type = "button";
    b.title = `Resize to ${pct}%`;
    b.addEventListener("click", () => {
      if (state.selectedImage) setImageWidth(state.selectedImage, pct);
    });
    bar.appendChild(b);
  });

  const slider = el("input");
  slider.type = "range";
  slider.id = "image-bar-slider";
  slider.min = "10";
  slider.max = "100";
  slider.className = "image-bar-slider";
  slider.addEventListener("input", () => {
    if (state.selectedImage) setImageWidth(state.selectedImage, Number(slider.value));
  });
  bar.appendChild(slider);

  const pctLabel = el("span", "image-bar-pct", "100%");
  pctLabel.id = "image-bar-pct";
  bar.appendChild(pctLabel);

  const del = el("button", "image-bar-btn image-bar-del", "Remove");
  del.type = "button";
  del.addEventListener("click", () => {
    if (!state.selectedImage) return;
    state.selectedImage.remove();
    deselectEditorImage();
    onEditorInput();
  });
  bar.appendChild(del);

  document.body.appendChild(bar);
  return bar;
}

function selectEditorImage(img) {
  if (state.selectedImage && state.selectedImage !== img) {
    state.selectedImage.classList.remove("img-selected");
  }
  state.selectedImage = img;
  img.classList.add("img-selected");
  const bar = ensureImageBar();
  bar.style.display = "flex";
  const pct = Number(img.dataset.widthPct || 100);
  $("image-bar-slider").value = String(pct);
  $("image-bar-pct").textContent = pct + "%";
  positionImageBar();
}

function deselectEditorImage() {
  if (state.selectedImage) state.selectedImage.classList.remove("img-selected");
  state.selectedImage = null;
  const bar = $("image-bar");
  if (bar) bar.style.display = "none";
}

function positionImageBar() {
  const img = state.selectedImage;
  const bar = $("image-bar");
  if (!img || !bar || !img.isConnected) return;
  const pct = Number(img.dataset.widthPct || 100);
  $("image-bar-pct").textContent = pct + "%";
  const r = img.getBoundingClientRect();
  bar.style.top = Math.max(8, r.top - bar.offsetHeight - 8) + "px";
  bar.style.left = Math.max(8, r.left) + "px";
}

function onEditorClick(e) {
  if (e.target && e.target.tagName === "IMG" && state.editMode === "original") {
    selectEditorImage(e.target);
  } else {
    deselectEditorImage();
  }
}

document.addEventListener("click", (e) => {
  const bar = $("image-bar");
  const editor = $("draft-editor");
  if (!state.selectedImage) return;
  if ((bar && bar.contains(e.target)) || (editor && editor.contains(e.target))) return;
  deselectEditorImage();
});
window.addEventListener("scroll", positionImageBar, true);
window.addEventListener("resize", positionImageBar);

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
  const underlineBtn = el("button", "toolbar-btn toolbar-underline", "U");
  underlineBtn.type = "button";
  underlineBtn.title = "Underline";
  underlineBtn.addEventListener("click", () => runEditorCommand("underline"));
  const bulletBtn = el("button", "toolbar-btn", "• List");
  bulletBtn.type = "button";
  bulletBtn.title = "Bullet list";
  bulletBtn.addEventListener("click", () => runEditorCommand("insertUnorderedList"));
  const numberBtn = el("button", "toolbar-btn", "1. List");
  numberBtn.type = "button";
  numberBtn.title = "Numbered list";
  numberBtn.addEventListener("click", () => runEditorCommand("insertOrderedList"));
  const linkBtn = el("button", "toolbar-btn", "Link");
  linkBtn.type = "button";
  linkBtn.title = "Insert link";
  linkBtn.addEventListener("click", insertLink);
  const imgBtn = el("button", "toolbar-btn", "Image");
  imgBtn.type = "button";
  imgBtn.title = "Insert an image — or just paste/drag one into the message. Click an inserted image to resize it.";
  imgBtn.addEventListener("click", pickImageFile);
  const clearBtn = el("button", "toolbar-btn", "Clear formatting");
  clearBtn.type = "button";
  clearBtn.title = "Remove formatting";
  clearBtn.addEventListener("click", () => runEditorCommand("removeFormat"));
  [boldBtn, italicBtn, underlineBtn, bulletBtn, numberBtn, linkBtn, imgBtn, clearBtn].forEach((b) => bar.appendChild(b));
  return bar;
}

function renderDraftSection(body) {
  const draft = state.detail.draft;
  deselectEditorImage(); // any previously selected <img> is about to be discarded
  const section = el("div");
  section.id = "draft-section";

  if (!draft) {
    // This lead has no draft, so there is nothing to revise. Clearing is not
    // cosmetic: generate() now sends the editor's content as the draft being
    // edited, and these persist across leads — without this, a first
    // generation for one lead would be handed the previous lead's message.
    state.originalHtml = "";
    state.englishHtml = null;
    if (state.detail.generating) {
      section.innerHTML = '<div class="loading-note"><span class="spinner"></span>Writing the draft — researching the lead, this can take a few minutes…</div>';
      body.appendChild(section);
      return;
    }
    const prompt = el("div", "generate-prompt");
    prompt.appendChild(renderQuickFollowups());
    prompt.appendChild(renderGenControls());
    const genRow = el("div", "gen-btn-row");
    const gbtn = el("button", "btn-send", "Generate draft");
    gbtn.addEventListener("click", () => generate($("gen-note-input").value));
    genRow.appendChild(gbtn);
    const wbtn = el("button", "btn-secondary", "Write directly");
    wbtn.type = "button";
    wbtn.title = "Skip AI generation — start from a blank message";
    wbtn.addEventListener("click", composeDraft);
    genRow.appendChild(wbtn);
    prompt.appendChild(genRow);
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
  // body_html is the message body only. The signature is shown as a separate,
  // read-only preview below the editor (rendered once, visible in both the
  // Original and English tabs) and appended unchanged at send time — it's never
  // translated and never part of what the editor sends to translate/localize.
  const bodyHtml = draft.body_html || "";
  state.originalHtml = bodyHtml;
  state.englishHtml = null;

  const box = el("div", "draft-box");
  box.appendChild(el("h3", null, "Draft reply"));

  if (draft.status === "scheduled" && draft.scheduled_at) {
    box.appendChild(el("span", "status-banner", `Scheduled for ${draft.scheduled_at}`));
  }

  // Belongs to the draft that was just created, so it sits above the editor
  // rather than with the lead's own details. textContent via el(), never HTML:
  // it can quote a provider's error text.
  if (state.draftNote) {
    box.appendChild(el("div", "draft-note", state.draftNote));
  }

  // The thread above is refetched live, so it already shows anything sent from
  // Smartlead directly — but this draft was written before that message
  // existed and may well be answering something already said.
  if (draft.thread_moved_on) {
    box.appendChild(el("span", "status-banner warn",
      "Written before the newest message in this thread — reread it above, or regenerate."));
  }

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
  editor.innerHTML = bodyHtml;
  editor.addEventListener("input", onEditorInput);
  editor.addEventListener("paste", onEditorPaste);
  editor.addEventListener("dragover", (e) => e.preventDefault());
  editor.addEventListener("drop", onEditorDrop);
  editor.addEventListener("click", onEditorClick);
  box.appendChild(editor);

  // Read-only signature preview — always visible (both tabs), never edited or
  // translated. It ships verbatim at send time (scheduler.compose_send_body).
  if (draft.signature_html) {
    const sigWrap = el("div", "sig-preview");
    sigWrap.appendChild(el("div", "sig-preview-label", "Signature — added automatically, not editable"));
    const sigBody = el("div", "sig-preview-body");
    sigBody.innerHTML = draft.signature_html;
    sigWrap.appendChild(sigBody);
    box.appendChild(sigWrap);
  } else {
    // Rendering nothing here used to be indistinguishable from "no signature
    // configured", so an unsigned send looked normal right up until it landed.
    box.appendChild(el("span", "status-banner warn",
      "No signature could be resolved for this thread — this email would go out unsigned."));
  }

  const applyRow = el("div", "apply-row");
  applyRow.id = "apply-row";
  applyRow.hidden = true;
  const applyBtn = el("button", "btn-send", "Apply to draft");
  applyBtn.id = "apply-btn";
  applyBtn.type = "button";
  applyBtn.addEventListener("click", applyEnglishEdit);
  applyRow.appendChild(applyBtn);
  applyRow.appendChild(el("span", "muted", "Rewrites the outgoing message in the lead's language, using the model selected below."));
  box.appendChild(applyRow);

  box.appendChild(renderQuickFollowups());
  box.appendChild(renderGenControls());

  box.appendChild(renderRecipients(draft));
  box.appendChild(renderAttachments(draft));

  const actions = el("div", "actions");
  const sendBtn = el("button", "btn-send", "Send now");
  sendBtn.id = "send-btn";
  sendBtn.addEventListener("click", () => sendDraft(draft.id));
  actions.appendChild(sendBtn);

  const dt = el("input");
  dt.type = "datetime-local";
  dt.id = "schedule-at";
  // Follow-ups arrive with a server-suggested send time (next weekday ~9am in
  // the lead's campaign timezone) so "Schedule" is one click, not a decision.
  if (draft.suggested_schedule_at) dt.value = toLocalInputValue(draft.suggested_schedule_at);
  actions.appendChild(dt);
  const schedBtn = el("button", "btn-secondary", "Schedule");
  schedBtn.id = "schedule-btn";
  schedBtn.addEventListener("click", () => scheduleDraft(draft.id));
  actions.appendChild(schedBtn);

  const noteInput = el("input");
  noteInput.type = "text";
  noteInput.id = "regen-note";
  // The note is now an edit instruction against the draft on screen, not a hint
  // for a rewrite from scratch, so the placeholder says what it does.
  noteInput.placeholder = "What to change (e.g. shorten the 2nd paragraph). Empty = new draft.";
  actions.appendChild(noteInput);
  const regenBtn = el("button", "btn-secondary", "Regenerate");
  regenBtn.id = "regen-btn";
  regenBtn.title = "With an instruction: edits this draft, keeping everything else. Without one: writes a different draft.";
  regenBtn.addEventListener("click", () => generate(noteInput.value));
  actions.appendChild(regenBtn);

  const templatesBtn = el("button", "btn-secondary", "Use a template…");
  templatesBtn.type = "button";
  templatesBtn.title = "Replace this draft with a pre-written template";
  templatesBtn.addEventListener("click", openTemplatesModal);
  actions.appendChild(templatesBtn);

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

// Who this send actually reaches, shown right above Send/Schedule so a message
// is never fired at an address that wasn't checked first. Both fields are sent
// to Smartlead explicitly (to_email / cc on reply-email-thread), so what's
// shown here IS what gets used — To defaults to the address the lead last
// wrote from, which for outreach to a generic info@ is the real person who
// answered, not the imported address.
function renderRecipients(draft) {
  const r = draft.recipients || {};
  const wrap = el("div", "recipients");

  const row = (label, id, value, placeholder) => {
    const line = el("div", "recipient-row");
    line.appendChild(el("span", "recipient-label", label));
    const input = el("input");
    input.type = "text";
    input.id = id;
    input.value = value || "";
    input.placeholder = placeholder;
    line.appendChild(input);
    wrap.appendChild(line);
  };
  row("To", "recipient-to", r.to, "Recipient address");
  row("Cc", "recipient-cc", r.cc, "Add people, comma-separated");

  const notes = [];
  if (r.lead_email && r.to && r.lead_email.toLowerCase() !== r.to.toLowerCase()) {
    notes.push(`Replying to the address they actually wrote from (imported as ${r.lead_email}).`);
  }
  if (r.auto_cc && !r.cc_is_override) notes.push("Cc carried over from this thread.");
  if (notes.length) wrap.appendChild(el("div", "recipient-note muted", notes.join(" ")));
  return wrap;
}

function currentRecipients() {
  const to = $("recipient-to");
  const cc = $("recipient-cc");
  const out = {};
  if (to) out.to = to.value;
  if (cc) out.cc = cc.value;
  return out;
}

// ---- attachments ----
//
// Files ride along as slugs; the server resolves each one back to a real
// file_url out of the library (main._attachment_updates). Sending the URL from
// here instead would let a client point Smartlead's fetcher at any address it
// liked, so the client deliberately never handles one.

function currentAttachments() {
  // Only send the key when the draft card is actually on screen — an absent
  // key means "leave the column alone", and [] means "he removed them".
  if (!$("attachments-row")) return {};
  return { attachments: (state.attachments || []).map((a) => a.slug) };
}

function renderAttachments(draft) {
  state.attachments = (draft.attachments || []).slice();
  const wrap = el("div", "attachments");
  wrap.id = "attachments-row";
  const line = el("div", "attachment-row");
  line.appendChild(el("span", "recipient-label", "Files"));
  const chips = el("div", "attachment-chips");
  chips.id = "attachment-chips";
  line.appendChild(chips);
  wrap.appendChild(line);

  const addBtn = el("button", "btn-secondary btn-attach", "+ Attach a file");
  addBtn.type = "button";
  addBtn.id = "attach-btn";
  addBtn.addEventListener("click", openLibraryModal);
  line.appendChild(addBtn);

  renderAttachmentChips();
  return wrap;
}

function renderAttachmentChips() {
  const chips = $("attachment-chips");
  if (!chips) return;
  chips.innerHTML = "";
  const list = state.attachments || [];
  if (!list.length) {
    chips.appendChild(el("span", "muted", "None"));
    return;
  }
  list.forEach((a) => {
    const chip = el("span", "attachment-chip");
    const link = el("a", null, a.file_name);
    link.href = a.file_url || a.url;
    link.target = "_blank";
    link.rel = "noopener";
    link.title = `${a.file_name} — ${formatBytes(a.file_size)}`;
    chip.appendChild(link);
    const rm = el("button", "attachment-remove", "×");
    rm.type = "button";
    rm.title = "Remove from this email";
    rm.addEventListener("click", () => {
      state.attachments = (state.attachments || []).filter((x) => x.slug !== a.slug);
      renderAttachmentChips();
    });
    chip.appendChild(rm);
    chips.appendChild(chip);
  });
}

function formatBytes(n) {
  if (!n) return "";
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${Math.round(n / 1024)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

async function openLibraryModal() {
  if ($("library-modal-overlay")) return;

  const overlay = el("div", "modal-overlay");
  overlay.id = "library-modal-overlay";
  overlay.addEventListener("click", (e) => {
    if (e.target === overlay) closeLibraryModal();
  });

  const modal = el("div", "modal templates-modal");
  const header = el("div", "modal-header");
  const heading = el("div", "modal-heading");
  heading.appendChild(el("h3", null, "Attach a file"));
  heading.appendChild(
    el("div", "modal-sub", "Files kept on the server, ready to reuse. Upload once, attach any time after.")
  );
  header.appendChild(heading);
  const closeBtn = el("button", "modal-close", "×");
  closeBtn.type = "button";
  closeBtn.setAttribute("aria-label", "Close");
  closeBtn.addEventListener("click", closeLibraryModal);
  header.appendChild(closeBtn);
  modal.appendChild(header);

  const list = el("div", "templates-list");
  list.id = "library-list";
  list.innerHTML = '<div class="loading-note"><span class="spinner"></span>Loading files…</div>';
  modal.appendChild(list);

  const footer = el("div", "modal-footer");
  const upload = el("input");
  upload.type = "file";
  upload.id = "library-upload";
  upload.hidden = true;
  upload.addEventListener("change", onLibraryUpload);
  footer.appendChild(upload);
  const uploadBtn = el("button", "btn-secondary", "+ Upload a new file");
  uploadBtn.type = "button";
  uploadBtn.addEventListener("click", () => upload.click());
  footer.appendChild(uploadBtn);
  footer.appendChild(el("span", "muted", "PDF, Office docs and images, up to 25 MB."));
  modal.appendChild(footer);

  overlay.appendChild(modal);
  document.body.appendChild(overlay);
  document.body.style.overflow = "hidden";
  document.addEventListener("keydown", onLibraryModalKeydown);

  await loadLibrary();
}

function onLibraryModalKeydown(e) {
  if (e.key === "Escape") closeLibraryModal();
}

function closeLibraryModal() {
  const overlay = $("library-modal-overlay");
  if (overlay) overlay.remove();
  document.body.style.overflow = "";
  document.removeEventListener("keydown", onLibraryModalKeydown);
}

async function loadLibrary() {
  try {
    const data = await apiGet("/api/library");
    renderLibraryList(data.files || []);
  } catch (err) {
    const list = $("library-list");
    if (list) list.innerHTML = `<div class="status-banner warn">Could not load the file library: ${err.message}</div>`;
  }
}

function renderLibraryList(files) {
  const list = $("library-list");
  if (!list) return;
  list.innerHTML = "";
  if (!files.length) {
    list.appendChild(el("div", "muted", "Nothing here yet — upload a file to start the library."));
    return;
  }
  const attached = new Set((state.attachments || []).map((a) => a.slug));
  files.forEach((f) => {
    const row = el("div", "library-item");
    const info = el("div", "library-info");
    const name = el("div", "library-name", f.file_name);
    info.appendChild(name);
    const meta = [formatBytes(f.file_size)];
    // "Shipped" files come from clients/<slug>/source-docs in the repo, so
    // they're on every container already and can't be deleted from here.
    if (f.source === "shipped") meta.push("built in");
    info.appendChild(el("div", "library-meta muted", meta.filter(Boolean).join(" · ")));
    row.appendChild(info);

    const isOn = attached.has(f.slug);
    const pick = el("button", isOn ? "btn-secondary" : "btn-send", isOn ? "Attached" : "Attach");
    pick.type = "button";
    pick.disabled = isOn;
    pick.addEventListener("click", () => {
      if ((state.attachments || []).some((a) => a.slug === f.slug)) return;
      state.attachments = (state.attachments || []).concat([
        {
          slug: f.slug,
          file_name: f.file_name,
          file_url: f.url,
          file_type: f.file_type,
          file_size: f.file_size,
        },
      ]);
      renderAttachmentChips();
      // Close on pick: attaching one file is the whole job nine times out of
      // ten, and leaving the picker open made the common case two clicks.
      closeLibraryModal();
    });
    row.appendChild(pick);

    if (f.source === "uploaded") {
      const del = el("button", "btn-danger", "Delete");
      del.type = "button";
      del.title = "Remove from the library for good";
      del.addEventListener("click", async () => {
        if (!confirm(`Delete "${f.file_name}" from the library?\n\nEmails already sent with it will stop showing the file.`)) return;
        try {
          const data = await apiDelete(`/api/library/${encodeURIComponent(f.slug)}`);
          state.attachments = (state.attachments || []).filter((a) => a.slug !== f.slug);
          renderAttachmentChips();
          renderLibraryList(data.files || []);
        } catch (err) {
          alert(`Could not delete: ${err.message}`);
        }
      });
      row.appendChild(del);
    }
    list.appendChild(row);
  });
}

async function onLibraryUpload(e) {
  const file = e.target.files && e.target.files[0];
  if (!file) return;
  e.target.value = "";
  const list = $("library-list");
  if (list) list.innerHTML = '<div class="loading-note"><span class="spinner"></span>Uploading…</div>';
  const form = new FormData();
  form.append("file", file);
  try {
    const res = await fetch("/api/library", { method: "POST", body: form });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Upload failed");
    renderLibraryList(data.files || []);
  } catch (err) {
    if (list) list.innerHTML = `<div class="status-banner warn">${err.message}</div>`;
  }
}

// The selection outline on a clicked image is a class on the <img> itself, so
// it would otherwise ride along into body_html and out to the lead. Strip it
// on the way out — this is the only place editor HTML is read for storage.
function editorSerialize(editor) {
  if (!editor.querySelector(".img-selected")) return editor.innerHTML;
  const clone = editor.cloneNode(true);
  clone.querySelectorAll(".img-selected").forEach((n) => {
    n.classList.remove("img-selected");
    if (!n.className) n.removeAttribute("class");
  });
  return clone.innerHTML;
}

function onEditorInput() {
  const editor = $("draft-editor");
  if (state.editMode === "original") {
    state.originalHtml = editorSerialize(editor);
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
  deselectEditorImage(); // the English tab replaces the editor's contents
  if (!opts.skipStash) {
    if (state.editMode === "original") state.originalHtml = editorSerialize(editor);
    else state.englishHtml = editor.innerHTML;
  }
  state.editMode = mode;
  $("tab-original").classList.toggle("active", mode === "original");
  $("tab-english").classList.toggle("active", mode === "english");
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
  const modelSel = $("gen-model-select");
  btn.disabled = true;
  btn.textContent = "Rewriting in the lead's language…";
  try {
    const data = await apiPost(`/api/drafts/${state.detail.draft.id}/localize`, {
      english_html: englishHtml,
      model: modelSel ? modelSel.value : undefined,
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
// Each bubble caches its own translation (dataset.translatedHtml) so flipping a
// message back and forth never re-calls the API. A message that arrived with a
// cached translation (m.english) starts in English. The per-message and
// whole-thread checkboxes share this same per-bubble state.
function threadBubbles() {
  return Array.from(document.querySelectorAll("#thread .bubble"));
}

function showBubbleOriginal(bubble) {
  bubble.innerHTML = bubble.dataset.original;
  bubble.dataset.mode = "orig";
}

function showBubbleEnglish(bubble) {
  bubble.innerHTML = bubble.dataset.translatedHtml;
  bubble.dataset.mode = "en";
}

// Keep the whole-thread checkbox in sync: checked only when every message is
// currently showing English.
function syncThreadToggle() {
  const tcb = $("thread-english-toggle");
  if (!tcb) return;
  const bubbles = threadBubbles();
  tcb.checked = bubbles.length > 0 && bubbles.every((b) => b.dataset.mode === "en");
}

// Per-message toggle. Unchecked → original; checked → English (fetched + cached
// on first use, free thereafter).
async function setMessageLang(bubble, cb, index) {
  if (!cb.checked) {
    showBubbleOriginal(bubble);
    syncThreadToggle();
    return;
  }
  if (!bubble.dataset.translatedHtml) {
    const { cid, lid } = currentLeadIds();
    cb.disabled = true;
    try {
      const data = await apiPost(`/api/leads/${cid}/${lid}/translate`, { index });
      bubble.dataset.translatedHtml = data.html;
    } catch (e) {
      cb.checked = false;
      cb.disabled = false;
      alert("Translation failed: " + e.message);
      return;
    }
    cb.disabled = false;
  }
  showBubbleEnglish(bubble);
  syncThreadToggle();
}

// Whole-thread toggle. Reuses each bubble's cached translation, so only the
// messages still missing one are requested — in a single batched call.
async function setThreadLang(tcb) {
  const bubbles = threadBubbles();
  if (!bubbles.length) return;
  const setRowChecks = (checked) =>
    bubbles.forEach((b) => {
      const cb = b.parentElement.querySelector(".msg-lang-cb");
      if (cb) cb.checked = checked;
    });

  if (!tcb.checked) {
    bubbles.forEach(showBubbleOriginal);
    setRowChecks(false);
    return;
  }

  const needed = [];
  bubbles.forEach((b, i) => {
    if (!b.dataset.translatedHtml) needed.push(i);
  });

  tcb.disabled = true;
  try {
    if (needed.length) {
      const { cid, lid } = currentLeadIds();
      const data = await apiPost(`/api/leads/${cid}/${lid}/translate-thread`, { indices: needed });
      data.indices.forEach((idx, k) => {
        bubbles[idx].dataset.translatedHtml = data.htmls[k];
      });
    }
    bubbles.forEach(showBubbleEnglish);
    setRowChecks(true);
  } catch (e) {
    alert("Translation failed: " + e.message);
    tcb.checked = false;
  } finally {
    tcb.disabled = false;
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
      // textContent, not innerHTML: this can now be the provider's own error
      // text, relayed from OpenRouter, which is not ours to trust as markup.
      s.appendChild(el("div", "error-note", errorMessage));
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
    // Say what actually went wrong when the server knows. "Could not generate a
    // draft for this lead" was the only thing this ever printed — the same
    // sentence for a model that ran out of reasoning budget, a missing API key
    // and a lead with no thread, none of which have the same fix.
    finish(
      data,
      data.draft
        ? null
        : data.generation_error || "Could not generate a draft for this lead.",
    );
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

  // Read the editor BEFORE the innerHTML wipe below destroys it. This is what
  // the model revises when a steering note is given — including any edits made
  // by hand, which a regenerate used to silently discard. Empty on a first
  // generation, where there is nothing to revise.
  const baseDraft = editorHtml();

  // The note describes the draft being replaced, not the one coming.
  state.draftNote = null;

  const section = $("draft-section");
  section.innerHTML = '<div class="loading-note"><span class="spinner"></span>Writing the draft — researching the lead, this can take a few minutes…</div>';
  try {
    await apiPost(`/api/leads/${cid}/${lid}/generate`, {
      steering_note: note || "",
      base_draft: baseDraft || "",
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

// Unlike skip/stop/schedule (withRowRemoval, which fades the row out and
// auto-advances to the next lead), sending stays put on the same lead —
// Andrew wants to keep working this thread, not get bounced to whichever
// lead happens to be next in the list.
async function sendDraft(id) {
  const { cid, lid } = currentLeadIds();
  try {
    await apiPost(`/api/drafts/${id}/send`, {
      body_html: editorHtml(),
      ...currentRecipients(),
      ...currentAttachments(),
    });
  } catch (e) {
    alert(e.message);
    return;
  }
  const data = await apiGet(`/api/leads/${cid}/${lid}`);
  state.detail = data;
  const row = state.leads.find((l) => l.campaign_id === cid && l.lead_id === lid);
  if (row) {
    row.category = "waiting";
    row.has_draft = false;
  }
  renderList();
  renderDetail();
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
    // datetime-local values are browser-local wall time with no zone marker;
    // the server treats naive timestamps as UTC, so convert explicitly here —
    // otherwise every schedule silently fires hours late (browser-local vs UTC).
    const atUtc = new Date(at).toISOString();
    await apiPost(`/api/drafts/${id}/schedule`, {
      body_html: editorHtml(),
      scheduled_at: atUtc,
      ...currentRecipients(),
      ...currentAttachments(),
    });
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
      showMobileList();
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

$("status-filter-btn").addEventListener("click", (e) => {
  e.stopPropagation();
  openStatusMenu($("status-menu").hidden);
});
// Ticking a box re-renders the menu's rows (the counts move), which destroys the
// element that was clicked — so by the time that click reaches the document it
// is no longer inside #status-filter and the outside-click handler below would
// close the menu on every single toggle. Stop it here instead.
$("status-menu").addEventListener("click", (e) => e.stopPropagation());
$("status-all-btn").addEventListener("click", () => setAllStatuses(true));
$("status-none-btn").addEventListener("click", () => setAllStatuses(false));
document.addEventListener("click", () => openStatusMenu(false));
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") openStatusMenu(false);
});

// ---------- init ----------
function onMobileMqChange() {
  if (!isMobileLayout()) showMobileList();
}
if (MOBILE_MQ.addEventListener) {
  MOBILE_MQ.addEventListener("change", onMobileMqChange);
} else if (MOBILE_MQ.addListener) {
  MOBILE_MQ.addListener(onMobileMqChange);
}

// Paint the restored filter (counts all zero) before the inbox arrives, so the
// button states which statuses are on even if that first load fails.
renderStatusFilter([]);

$("rescan-btn").addEventListener("click", rescan);
$("models-btn").addEventListener("click", openModelsModal);
$("view-inbox-btn").addEventListener("click", () => setView("inbox"));
$("view-scheduled-btn").addEventListener("click", () => setView("scheduled"));
$("view-stats-btn").addEventListener("click", () => setView("stats"));
$("view-archive-btn").addEventListener("click", () => setView("archive"));
$("view-campaigns-btn").addEventListener("click", () => setView("campaigns"));
loadInbox().catch((e) => {
  $("scan-status").textContent = "load failed";
  console.error(e);
});
loadCategories();
loadModels();
loadGoogleStatus();

// Quietly re-pull the inbox so a reply that just arrived (webhook, or the
// periodic backend scan) shows up without a manual Rescan or F5. List-only:
// loadInbox -> renderList rebuilds #lead-list and never touches the open draft
// editor (#detail-body), so nothing you're typing is disturbed. We keep the
// selected lead highlighted across the refresh by matching on its id, not its
// (possibly shifted) list index. Runs only on the inbox view and only when the
// tab is visible.
//
// 15s, not the 60s this started at: a reply is the one thing in this app worth
// seeing the moment it lands, and /api/inbox is a single SQLite read. The
// paused-while-hidden rule is what makes that cheap — nobody is polling a
// background tab — but it also means coming back to the tab could cost a full
// interval, so a return to visibility refreshes straight away instead.
const INBOX_REFRESH_MS = 15000;
function leadKey(l) {
  return l ? `${l.campaign_id}/${l.lead_id}` : null;
}
async function autoRefreshInbox() {
  if (state.view !== "inbox" || document.hidden) return;
  const curKey = leadKey(state.selected >= 0 ? state.leads[state.selected] : null);
  try {
    await loadInbox();
  } catch (e) {
    return; // transient — try again next tick
  }
  if (curKey) {
    const idx = state.leads.findIndex((l) => leadKey(l) === curKey);
    if (idx !== state.selected) {
      state.selected = idx;
      renderList();
    }
  }
}
setInterval(autoRefreshInbox, INBOX_REFRESH_MS);
document.addEventListener("visibilitychange", () => {
  if (!document.hidden) autoRefreshInbox();
});
window.addEventListener("focus", autoRefreshInbox);
