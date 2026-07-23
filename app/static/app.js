"use strict";

const state = {
  view: "inbox",        // "inbox" | "scheduled" | "archive"
  allLeads: [],          // full inbox as loaded from the server, unfiltered
  leads: [],              // filtered view actually rendered (search + category)
  searchQuery: "",
  categoryFilter: new Set(["reply", "followup", "auto_reply", "waiting", "booked"]),
  snoozedCount: 0,       // archive view only: state.leads[0..snoozedCount) are snoozed, rest archived
  selected: -1,
  detail: null,          // current lead detail {lead, thread, draft}
  categoryList: null,    // live Smartlead categories, for the "Change status" dropdown
  selectedImage: null,   // <img> in the editor currently targeted by the resize bar
  templates: null,       // message templates from /api/templates, loaded when the modal opens
  // ---- campaigns view ----
  campaigns: [],         // /api/campaigns list with headline stats
  selectedCampaign: null,
  campaignTab: "overview", // "overview" | "report" | "conversations"
  convoFilter: "",       // lead category filter on the Conversations sub-tab
  campaignPoll: null,    // setTimeout handle polling a running analysis
};

const CHIP = {
  reply: "Awaiting your reply",
  followup: "Follow-up due",
  auto_reply: "Auto-reply — nudge",
  waiting: "In conversation",
  booked: "Meeting booked ✅",
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
  const data = await apiGet("/api/campaigns");
  state.campaigns = data.campaigns || [];
  renderCampaignList();
  return data;
}

function renderCampaignList() {
  const list = $("lead-list");
  list.innerHTML = "";
  $("inbox-count").textContent = `Campaigns (${state.campaigns.length})`;

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
  card("Positive replies", String(o.positives || 0), pct(o.positive_rate));
  card("Auto-replies filtered out", String(o.robot_replies || 0), "excluded from all rates");
  pane.appendChild(cards);
  pane.appendChild(el("p", "muted small", `Synced ${data.synced_at}. Open and click tracking are off for these campaigns, so replies are the only signal shown.`));

  pane.appendChild(el("h3", null, "Message variants"));
  pane.appendChild(el("p", "muted small", "Attributed across the whole sequence — a reply to follow-up #2 still belongs to the variant that opened the thread."));
  pane.appendChild(
    metricTable(data.variants, [
      { label: "Variant", render: (r) => r.variant_label },
      { label: "Recipe", render: (r) => Object.values(r.recipe || {}).flat().join(" + ") || "—" },
      ...RATE_COLUMNS,
    ], "wrap-first")
  );

  const ROLE_LABELS = {
    subject: "Subject lines", cta: "Calls to action", offer: "Offers",
    pitch: "Pitches", painpoint: "Pain points", socialproof: "Social proof",
    icebreaker: "Icebreakers",
  };
  pane.appendChild(el("h3", null, "By message component"));
  pane.appendChild(el("p", "muted small", "Each row pools every variant using that component, so these rest on a bigger sample than the variant table above."));
  Object.entries(data.slots || {}).forEach(([role, entries]) => {
    if (!entries.length) return;
    pane.appendChild(el("h4", null, ROLE_LABELS[role] || role));
    pane.appendChild(
      metricTable(entries, [
        { label: "Component", render: (r) => r.slot },
        { label: "Used by", render: (r) => (r.used_by || []).join(", ") },
        { label: "Example text", render: (r) => truncate((r.examples || [])[0] || "", 55) },
        ...RATE_COLUMNS,
      ], "wrap-mid")
    );
  });

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

  pane.appendChild(el("h3", null, "Rendered subject lines"));
  pane.appendChild(
    metricTable(data.subjects, [
      { label: "Subject as sent", render: (r) => truncate(r.subject, 70) },
      ...RATE_COLUMNS,
    ], "wrap-first")
  );
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
    await apiPost(`/api/campaigns/${campaign.id}/analyze`, { name: campaign.name });
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

  if (!data.report_md && !data.conversation_md) {
    pane.appendChild(el("p", "muted", "Not analyzed yet. This reads the campaign's variants, its send results and every real reply, then writes up what's working and how to build the next run."));
    pane.appendChild(analyzeButton(campaign));
    return;
  }

  const bar = el("div", "report-bar");
  bar.appendChild(el("span", "muted small", `Generated ${data.generated_at} · ${data.model || ""}`));
  bar.appendChild(analyzeButton(campaign, "Re-analyze"));
  pane.appendChild(bar);

  if (data.report_md) {
    pane.appendChild(el("h3", null, "Variants — what's working and what to run next"));
    pane.appendChild(markdownBlock(data.report_md));
  }
  if (data.conversation_md) {
    pane.appendChild(el("h3", null, "What the replies actually say"));
    pane.appendChild(markdownBlock(data.conversation_md));
  }
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

async function renderCampaignConversations(pane, campaign) {
  const data = await apiGet(`/api/campaigns/${campaign.id}/responders`);
  pane.innerHTML = "";
  const people = data.responders || [];
  if (!people.length) {
    pane.appendChild(el("p", "muted", "No real replies stored yet. Auto-replies and out-of-office are deliberately excluded — run Analyze to pull the conversations."));
    pane.appendChild(analyzeButton(campaign));
    return;
  }

  const categories = [...new Set(people.map((p) => p.category).filter(Boolean))].sort();
  const filter = el("div", "convo-filter");
  const mkFilter = (label, value) => {
    const btn = el("button", "chip-filter" + ((state.convoFilter || "") === value ? " active" : ""), label);
    btn.type = "button";
    btn.addEventListener("click", () => {
      state.convoFilter = value;
      renderCampaignDetail(campaign);
    });
    filter.appendChild(btn);
  };
  mkFilter(`All (${people.length})`, "");
  categories.forEach((c) => mkFilter(`${c} (${people.filter((p) => p.category === c).length})`, c));
  pane.appendChild(filter);

  const shown = state.convoFilter ? people.filter((p) => p.category === state.convoFilter) : people;
  shown.forEach((person) => pane.appendChild(conversationCard(person)));
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
  $("legend").hidden = view !== "inbox";
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
    : 'No leads yet. Click <strong>Rescan now</strong> — it checks every “Interested” lead and takes a couple of minutes.';

  state.leads.forEach((lead, i) => {
    if (archiveMode && i === 0 && state.snoozedCount > 0) {
      list.appendChild(el("li", "list-section", "Snoozed — hidden until due"));
    }
    if (archiveMode && i === state.snoozedCount) {
      list.appendChild(el("li", "list-section", "Archived"));
    }

    const rowClass = archiveMode ? "archive-row" : scheduledMode ? "archive-row" : "cat-" + lead.category;
    const row = el("li", `lead-row ${rowClass}`);
    if (i === state.selected) row.classList.add("selected");
    row.dataset.index = i;

    const top = el("div", "lead-top");
    if (lead.language) top.appendChild(el("span", "lang-badge", lead.language));
    top.appendChild(el("span", "lead-name", lead.name));
    if (lead.company) top.appendChild(el("span", "lead-company", "· " + lead.company));
    if (state.view === "inbox" && lead.has_draft) top.appendChild(el("span", "ready-dot"));
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
  header.appendChild(el("span", `state-chip cat-${lead.category}`, CHIP[lead.category] || CHIP.waiting));
  body.appendChild(header);
  body.appendChild(el("div", "detail-sub", [lead.company, lead.email].filter(Boolean).join(" · ")));
  if (lead.email_display_name && lead.email_display_name !== lead.name) {
    body.appendChild(el("div", "detail-sub muted", `Smartlead shows their inbox name as "${lead.email_display_name}"`));
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

// Andrew's manual fix for a wrong/imported first name — see the muted
// "Smartlead shows their inbox name as ..." line rendered next to it, which
// is what this is meant to be checked against.
async function editLeadName() {
  const lead = state.detail.lead;
  const next = window.prompt("Edit this lead's first name:", lead.name || "");
  if (next == null) return;
  const trimmed = next.trim();
  if (!trimmed || trimmed === lead.name) return;
  const { cid, lid } = currentLeadIds();
  try {
    await apiPost(`/api/leads/${cid}/${lid}/name`, { name: trimmed });
  } catch (e) {
    alert("Couldn't update name: " + e.message);
    return;
  }
  lead.name = trimmed;
  const row = currentLead();
  if (row) row.name = trimmed;
  renderList();
  renderDetail();
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
function fillPlaceholders(text) {
  const firstName = (state.detail.lead.name || "").split(" ")[0] || "there";
  const company = state.detail.lead.company || "your business";
  return text.replace(/\{name\}/g, firstName).replace(/\{company\}/g, company);
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

async function composeDraft() {
  const { cid, lid } = currentLeadIds();
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
  noteInput.placeholder = "Steer regeneration (optional)";
  actions.appendChild(noteInput);
  const regenBtn = el("button", "btn-secondary", "Regenerate");
  regenBtn.id = "regen-btn";
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

// Unlike skip/stop/schedule (withRowRemoval, which fades the row out and
// auto-advances to the next lead), sending stays put on the same lead —
// Andrew wants to keep working this thread, not get bounced to whichever
// lead happens to be next in the list.
async function sendDraft(id) {
  const { cid, lid } = currentLeadIds();
  try {
    await apiPost(`/api/drafts/${id}/send`, { body_html: editorHtml(), ...currentRecipients() });
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
function onMobileMqChange() {
  if (!isMobileLayout()) showMobileList();
}
if (MOBILE_MQ.addEventListener) {
  MOBILE_MQ.addEventListener("change", onMobileMqChange);
} else if (MOBILE_MQ.addListener) {
  MOBILE_MQ.addListener(onMobileMqChange);
}

$("rescan-btn").addEventListener("click", rescan);
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
