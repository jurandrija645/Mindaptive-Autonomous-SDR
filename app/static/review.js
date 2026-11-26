"use strict";

// ---------- Pregled: the morning review of every conversation after a positive reply ----------
//
// app/daily_review.py serves one report per day, built on Andrija's machine by
// LeadsFinder/scripts/analysis/daily_review.py. Loaded after app.js and crm.js and uses their
// helpers ($, el, apiGet, state, setMode). The header's third workspace button swaps the whole
// page for #review-page. Every text from a lead or from us is set with textContent, never HTML.

const REVIEW_MODE_KEY = "responder.mode";

const rv = {
  days: [],
  day: "",
  report: null,
  section: "waiting",
  onlyProblems: false,
  search: "",
  open: new Set(),   // refs whose whole thread is shown
};

const RV_SECTIONS = [
  ["waiting", "Čeka nas"],
  ["replies", "Odgovori"],
  ["followups", "Naše poruke"],
  ["due", "Ide danas"],
  ["booked", "Bukirano"],
  ["negatives", "Negativni"],
];

const RV_KIND = {
  campaign: "Kampanja",
  answer: "Naš odgovor",
  followup: "Follow-up",
  open: "Lead",
  no: "Lead · ne",
  auto: "Automatski odgovor",
};

function rvEl(tag, cls, text) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text !== undefined && text !== null) n.textContent = String(text);
  return n;
}

function openReview() {
  if (typeof cancelLeadRequest === "function") cancelLeadRequest();
  if (typeof closeMobileMenu === "function") closeMobileMenu(true);
  state.mode = "review";
  try { localStorage.setItem(REVIEW_MODE_KEY, "review"); } catch (_) { /* private window */ }
  document.body.classList.remove("crm-mode");
  document.body.classList.add("review-mode");
  $("mode-outreach-btn").classList.remove("active");
  $("mode-crm-btn").classList.remove("active");
  $("mode-review-btn").classList.add("active");
  $("view-switch").hidden = true;
  $("crm-subnav").hidden = true;
  $("subnav").hidden = true;
  $("rescan-btn").hidden = true;
  document.querySelector(".layout").hidden = true;
  $("crm-page").hidden = true;
  $("review-page").hidden = false;
  loadReview();
}

async function loadReview(day) {
  const page = $("review-page");
  if (!rv.report) page.replaceChildren(rvEl("p", "muted rv-loading", "Učitavam pregled…"));
  try {
    const days = await apiGet("/api/daily-review/days");
    rv.days = days.days || [];
    if (!rv.days.length) {
      page.replaceChildren(rvEl("p", "muted rv-loading",
        "Još nema nijednog pregleda. Generira ga LeadsFinder/scripts/analysis/daily_review.py na Andrijinom računalu."));
      return;
    }
    rv.day = day || rv.day || rv.days[0].day;
    rv.report = await apiGet("/api/daily-review?day=" + encodeURIComponent(rv.day));
    renderReview();
  } catch (e) {
    console.error(e);
    page.replaceChildren(rvEl("p", "rv-error", "Pregled se nije učitao: " + (e.message || e)));
  }
}

function rvThread(ref) {
  return (rv.report.threads || {})[ref] || { messages: [], flags: [] };
}

function rvMatches(ref) {
  const t = rvThread(ref);
  if (rv.onlyProblems && !rvHasProblem(t)) return false;
  if (!rv.search) return true;
  const hay = [t.name, t.company, t.email, t.campaign].join(" ").toLowerCase();
  return hay.includes(rv.search.toLowerCase());
}

function rvHasProblem(t) {
  return (t.flags && t.flags.length) || (t.qa && t.qa.score <= 3);
}

function renderReview() {
  const r = rv.report;
  const page = $("review-page");
  const wrap = rvEl("div", "rv-wrap");

  // Head: day picker and when it was made.
  const head = rvEl("div", "rv-head");
  const title = rvEl("h2", "rv-title", "Pregled razgovora");
  const pick = rvEl("select", "rv-day");
  for (const d of rv.days) {
    const o = rvEl("option", null, `${d.day} · ${d.summary.replies_positive ?? "?"} pozitivnih`);
    o.value = d.day;
    if (d.day === rv.day) o.selected = true;
    pick.appendChild(o);
  }
  pick.addEventListener("change", () => { rv.report = null; rv.open.clear(); loadReview(pick.value); });
  const meta = rvEl("span", "muted rv-meta",
    `Dan: ${r.day} · generirano ${r.generated_at_hr || r.generated_at} (stanje "Čeka nas" i "Ide danas" je iz tog trenutka)`);
  const reload = rvEl("button", "btn-secondary", "Osvježi");
  reload.type = "button";
  reload.addEventListener("click", () => loadReview(rv.day));
  head.append(title, pick, reload, meta);
  wrap.appendChild(head);

  // Tiles.
  const s = r.summary || {};
  const tiles = rvEl("div", "rv-tiles");
  const tile = (label, value, sub, cls) => {
    const t = rvEl("div", "rv-tile" + (cls ? " " + cls : ""));
    t.append(rvEl("div", "rv-tile-value", value ?? "—"), rvEl("div", "rv-tile-label", label));
    if (sub) t.appendChild(rvEl("div", "rv-tile-sub muted", sub));
    return t;
  };
  tiles.append(
    tile("pozitivnih odgovora", s.replies_positive, `${s.replies_first ?? 0} prvi put`),
    tile("odgovoreno", s.answered, s.median_response_h != null ? `medijan ${s.median_response_h} h` : ""),
    tile("naših poruka nakon odgovora", s.followups_sent, `${s.leads_followed_up ?? 0} leadova`),
    tile("čeka nas sada", s.waiting_now, "", s.waiting_now ? "rv-tile-warn" : ""),
    tile("ide danas", s.due_today),
    tile("bukirano", s.booked, "Calendly", s.booked ? "rv-tile-good" : "rv-tile-bad"),
    tile("razgovora s problemom", s.with_flags, `${s.qa_low ?? 0} loše ocijenjenih`, s.with_flags ? "rv-tile-warn" : ""),
  );
  wrap.appendChild(tiles);

  // Section tabs and filters.
  const bar = rvEl("div", "rv-bar");
  const counts = {
    waiting: (r.waiting || []).length, replies: (r.replies || []).length, followups: (r.followups || []).length,
    due: (r.due || []).length, booked: (r.booked || []).length, negatives: (r.negatives || []).length,
  };
  for (const [key, label] of RV_SECTIONS) {
    const b = rvEl("button", "view-tab" + (rv.section === key ? " active" : ""), `${label} (${counts[key]})`);
    b.type = "button";
    b.addEventListener("click", () => { rv.section = key; renderReview(); });
    bar.appendChild(b);
  }
  const prob = rvEl("label", "rv-check");
  const cb = document.createElement("input");
  cb.type = "checkbox";
  cb.checked = rv.onlyProblems;
  cb.addEventListener("change", () => { rv.onlyProblems = cb.checked; renderReview(); });
  prob.append(cb, document.createTextNode(" samo s problemima"));
  const search = rvEl("input", "lead-search rv-search");
  search.placeholder = "Traži firmu, ime, email…";
  search.value = rv.search;
  search.addEventListener("input", () => {
    rv.search = search.value;
    clearTimeout(rv.searchTimer);
    rv.searchTimer = setTimeout(() => { renderReview(); const n = document.querySelector(".rv-search"); if (n) { n.focus(); n.setSelectionRange(n.value.length, n.value.length); } }, 250);
  });
  bar.append(prob, search);
  wrap.appendChild(bar);

  const list = rvEl("div", "rv-list");
  const help = {
    waiting: "Ljudi čija je zadnja poruka njihova i nitko im još nije odgovorio. Uz svakoga piše zašto čeka.",
    replies: "Svaki odgovor pozitivnog leada tog dana: što su napisali, sve što smo mi poslali nakon toga i koliko brzo. Ispod je Sonnetova ocjena cijelog razgovora.",
    followups: "Svaka poruka koju smo tog dana poslali nekome tko nam je već odgovorio (odgovori, demoi, follow-upi).",
    due: "Što automatika (ljestvica nakon demoa i follow-upi u razgovoru) treba poslati danas. Procjena po pravilima rasporeda.",
    booked: "Sastanci bukirani preko Calendlyja tog dana.",
    negatives: "Odgovori koji nisu pozitivni (ne, krivi čovjek, ugašena firma), samo za pregled.",
  };
  list.appendChild(rvEl("p", "muted rv-help", help[rv.section]));

  let shown = 0;
  if (rv.section === "waiting") {
    for (const w of r.waiting || []) {
      if (!rvMatches(w.ref)) continue;
      shown++;
      list.appendChild(rvCard(w.ref, (box) => {
        box.appendChild(rvLine(`Čeka ${w.hours} h (od ${w.at})`, w.hours >= 20 ? "rv-bad" : ""));
        if (w.why && w.why.length) box.appendChild(rvLine("Zašto: " + w.why.join(" · "), "muted"));
        box.appendChild(rvMsg({ type: "them", kind: "open", at: w.at, text: w.text, text_hr: w.text_hr }));
      }));
    }
  } else if (rv.section === "replies") {
    for (const x of r.replies || []) {
      if (!rvMatches(x.ref)) continue;
      shown++;
      list.appendChild(rvCard(x.ref, (box) => {
        const resp = x.response_h == null ? "još bez našeg odgovora" : `prvi naš odgovor nakon ${x.response_h} h`;
        box.appendChild(rvLine((x.first_reply ? "Prvi odgovor na kampanju · " : "Odgovor u razgovoru · ") + resp,
          x.response_h == null ? "rv-bad" : ""));
        for (const m of x.their) box.appendChild(rvMsg({ type: "them", kind: m.kind, at: m.at, text: m.text, text_hr: m.text_hr }));
        for (const m of x.ours_after) box.appendChild(rvMsg({ type: "us", kind: m.kind, at: m.at, text: m.text, text_hr: m.text_hr }));
      }));
    }
  } else if (rv.section === "followups") {
    for (const f of r.followups || []) {
      if (!rvMatches(f.ref)) continue;
      shown++;
      list.appendChild(rvCard(f.ref, (box) => {
        const since = f.days_since_their_last == null ? "" : ` · ${f.days_since_their_last} d od njihove zadnje poruke`;
        box.appendChild(rvLine(`Tog dana poslano: ${f.sent.length} · zadnjih 7 dana: ${f.ours_last7} · ukupno nakon kampanje: ${f.ours_total}${since}`,
          f.ours_last7 >= 4 || f.sent.length >= 2 ? "rv-bad" : ""));
        for (const m of f.sent) box.appendChild(rvMsg({ type: "us", kind: m.kind, at: m.at, text: m.text, text_hr: m.text_hr }));
      }));
    }
  } else if (rv.section === "due") {
    for (const d of r.due || []) {
      if (!rvMatches(d.ref)) continue;
      shown++;
      list.appendChild(rvCard(d.ref, (box) => {
        box.appendChild(rvLine(`${d.overdue ? "Kasni, trebalo je ići " : "Ide oko "}${d.at} · ${d.what}`, d.overdue ? "rv-bad" : ""));
        const t = rvThread(d.ref);
        const last = (t.messages || []).filter((m) => m.kind !== "auto").slice(-1)[0];
        if (last) box.appendChild(rvMsg(last));
      }));
    }
  } else if (rv.section === "booked") {
    for (const b of r.booked || []) {
      shown++;
      const c = rvEl("div", "rv-card");
      c.append(rvEl("div", "rv-card-title", `${b.name || ""} · ${b.email || ""}`),
        rvLine(`${b.event || "Sastanak"} · ${b.when} · ${b.status === "active" ? "aktivan" : "otkazan"}`));
      list.appendChild(c);
    }
  } else if (rv.section === "negatives") {
    for (const n of r.negatives || []) {
      if (rv.search && ![n.name, n.company, n.email].join(" ").toLowerCase().includes(rv.search.toLowerCase())) continue;
      shown++;
      const c = rvEl("div", "rv-card");
      c.append(rvEl("div", "rv-card-title", `${n.company || n.name || n.email} · ${n.email} · ${n.category || "bez kategorije"}`),
        rvMsg({ type: "them", kind: "no", at: n.at, text: n.text, text_hr: n.text_hr }));
      list.appendChild(c);
    }
  }
  if (!shown) list.appendChild(rvEl("p", "muted rv-empty", "Ništa za prikazati."));
  wrap.appendChild(list);
  page.replaceChildren(wrap);
}

function rvLine(text, cls) {
  return rvEl("div", "rv-line" + (cls ? " " + cls : ""), text);
}

function rvMsg(m) {
  const us = m.type === "us";
  const box = rvEl("div", "rv-msg " + (us ? "rv-us" : "rv-them") + (m.kind === "auto" ? " rv-auto" : ""));
  const label = us ? (RV_KIND[m.kind] || "Mi") : (RV_KIND[m.kind] || "Lead");
  const who = m.from && us ? ` · ${m.from}` : "";
  // Croatian first (owner, 26 Nov 2026: the threads are in languages the team does not read);
  // the original is one click away.
  const hr = m.text_hr && m.text_hr.trim() && m.text_hr.trim() !== (m.text || "").trim() ? m.text_hr : "";
  box.append(rvEl("div", "rv-msg-head", `${m.at} · ${label}${who}`), rvEl("div", "rv-msg-text", hr || m.text || "(prazno)"));
  if (hr) {
    const orig = rvEl("div", "rv-msg-text rv-orig", m.text);
    orig.hidden = true;
    const btn = rvEl("button", "link-btn rv-orig-btn", "Original");
    btn.type = "button";
    btn.addEventListener("click", () => {
      orig.hidden = !orig.hidden;
      btn.textContent = orig.hidden ? "Original" : "Sakrij original";
    });
    box.append(btn, orig);
  }
  return box;
}

function rvCard(ref, fill) {
  const t = rvThread(ref);
  const card = rvEl("div", "rv-card" + (rvHasProblem(t) ? " rv-card-problem" : ""));
  const top = rvEl("div", "rv-card-top");
  const name = [t.company, t.name].filter(Boolean).join(" · ") || t.email;
  top.appendChild(rvEl("div", "rv-card-title", name));
  const sub = [t.email, t.campaign, t.category].filter(Boolean).join(" · ");
  top.appendChild(rvEl("div", "muted rv-card-sub", sub));
  if (t.owner) top.appendChild(rvEl("span", "rv-chip rv-chip-owner", "Andrijin (CRM)"));
  if (t.qa) top.appendChild(rvEl("span", "rv-chip rv-score-" + t.qa.score, `ocjena ${t.qa.score}/5`));
  const links = rvEl("div", "rv-links");
  for (const [label, url] of [["demo", t.demo_url], ["ponuda", t.offer_url], ["loom", t.loom_url]]) {
    if (!url) continue;
    const a = rvEl("a", null, label);
    a.href = url;
    a.target = "_blank";
    a.rel = "noopener";
    links.appendChild(a);
  }
  top.appendChild(links);
  card.appendChild(top);

  const body = rvEl("div", "rv-card-body");
  fill(body);
  card.appendChild(body);

  if ((t.flags && t.flags.length) || t.qa) {
    const rev = rvEl("div", "rv-review");
    if (t.flags && t.flags.length) {
      rev.appendChild(rvEl("div", "rv-review-title", "Pravila"));
      const ul = rvEl("ul", "rv-flags");
      for (const f of t.flags) ul.appendChild(rvEl("li", null, f));
      rev.appendChild(ul);
    }
    if (t.qa) {
      rev.appendChild(rvEl("div", "rv-review-title", "Sonnet o cijelom razgovoru"));
      if (t.qa.stage_hr) rev.appendChild(rvLine("Gdje je: " + t.qa.stage_hr));
      if (t.qa.mistakes && t.qa.mistakes.length) {
        const ul = rvEl("ul", "rv-flags");
        for (const f of t.qa.mistakes) ul.appendChild(rvEl("li", null, f));
        rev.appendChild(ul);
      }
      if (t.qa.missed_hr) rev.appendChild(rvLine("Propustili smo: " + t.qa.missed_hr));
      if (t.qa.next_hr) rev.appendChild(rvLine("Sljedeća poruka: " + t.qa.next_hr));
    }
    card.appendChild(rev);
  }

  const toggle = rvEl("button", "link-btn rv-toggle",
    rv.open.has(ref) ? "Sakrij cijeli razgovor" : `Cijeli razgovor (${(t.messages || []).length} poruka)`);
  toggle.type = "button";
  const full = rvEl("div", "rv-full");
  full.hidden = !rv.open.has(ref);
  const fillFull = () => {
    full.replaceChildren(...(t.messages || []).map(rvMsg));
  };
  if (!full.hidden) fillFull();
  toggle.addEventListener("click", () => {
    if (rv.open.has(ref)) rv.open.delete(ref); else rv.open.add(ref);
    full.hidden = !rv.open.has(ref);
    if (!full.hidden) fillFull();
    toggle.textContent = full.hidden ? `Cijeli razgovor (${(t.messages || []).length} poruka)` : "Sakrij cijeli razgovor";
  });
  card.append(toggle, full);
  return card;
}

// ---------- boot ----------

$("mode-review-btn").addEventListener("click", openReview);
try {
  if (localStorage.getItem(REVIEW_MODE_KEY) === "review") openReview();
} catch (_) { /* storage unavailable */ }
