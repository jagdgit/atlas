"use strict";
/* Atlas Console (S23) — a zero-build vanilla SPA over the /v1 REST API. */

const KEY_STORE = "atlas_api_key";

const state = {
  key: localStorage.getItem(KEY_STORE) || "",
  view: "overview",
  sessionId: null,
  jobId: null,
  missionId: null,
  programId: null,
  missionPoll: null,
  archivePoll: null,
  sending: false,
  jobPoll: null,
  jobPollGen: 0,
  jobPollFailures: 0,
  opsPoll: null,
  opsStream: null,
  repoId: null,
  engStream: null,
};

/* ---------- tiny DOM helper (textContent-only = XSS-safe) ---------- */
function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v == null) continue;
    if (k === "class") node.className = v;
    else if (k === "text") node.textContent = v;
    else if (k.startsWith("on") && typeof v === "function") node.addEventListener(k.slice(2), v);
    else node.setAttribute(k, v);
  }
  for (const c of children.flat()) {
    if (c == null) continue;
    node.append(c.nodeType ? c : document.createTextNode(String(c)));
  }
  return node;
}
const $ = (sel) => document.querySelector(sel);

/* ---------- API ---------- */
async function api(path, { method = "GET", body } = {}) {
  const res = await fetch(path, {
    method,
    headers: {
      "Authorization": `Bearer ${state.key}`,
      ...(body ? { "Content-Type": "application/json" } : {}),
    },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (res.status === 401) {
    signOut("Session rejected — please re-enter your API key.");
    throw new Error("unauthorized");
  }
  let data = null;
  try { data = await res.json(); } catch (_) { /* no body */ }
  if (!res.ok) {
    let detail = (data && (data.detail || data.error)) || `HTTP ${res.status}`;
    if (typeof detail !== "string") detail = JSON.stringify(detail);
    // FastAPI returns bare "Not Found" when a route isn't loaded (stale atlas serve).
    if (res.status === 404 && detail === "Not Found") {
      detail = "API route missing — restart `atlas serve` and hard-refresh /ui";
    }
    throw new Error(detail);
  }
  return data;
}

function toast(msg) {
  const t = $("#toast");
  t.textContent = msg;
  t.classList.remove("hidden");
  clearTimeout(toast._t);
  toast._t = setTimeout(() => t.classList.add("hidden"), 4000);
}

function esc(s) {
  return String(s == null ? "" : s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

/* ---------- auth ---------- */
function signOut(msg) {
  localStorage.removeItem(KEY_STORE);
  state.key = "";
  $("#app").classList.add("hidden");
  const login = $("#login");
  login.classList.remove("hidden");
  if (msg) showLoginError(msg);
}
function showLoginError(msg) {
  const e = $("#login-error");
  e.textContent = msg;
  e.classList.toggle("hidden", !msg);
}

async function tryConnect(key) {
  const prev = state.key;
  state.key = key;
  try {
    const status = await api("/v1/status");
    localStorage.setItem(KEY_STORE, key);
    $("#login").classList.add("hidden");
    $("#app").classList.remove("hidden");
    showLoginError("");
    applyStatus(status);
    switchView(state.view);
    loadSessions();
    return true;
  } catch (err) {
    state.key = prev;
    if (err.message !== "unauthorized") showLoginError("Could not connect: " + err.message);
    else showLoginError("Invalid API key.");
    return false;
  }
}

function applyStatus(status) {
  const dot = $("#conn-dot");
  const label = $("#conn-label");
  dot.className = "dot " + (status.degraded ? "warn" : status.healthy ? "ok" : "fail");
  label.textContent = `v${status.version} · ${status.severity_counts.ok} ok`
    + (status.severity_counts.degraded ? ` · ${status.severity_counts.degraded} degraded` : "")
    + (status.severity_counts.failed ? ` · ${status.severity_counts.failed} down` : "");
}

/* ---------- navigation ---------- */
function switchView(view) {
  state.view = view;
  document.querySelectorAll(".nav-btn").forEach((b) => b.classList.toggle("active", b.dataset.view === view));
  document.querySelectorAll(".view").forEach((v) => v.classList.add("hidden"));
  $(`#view-${view}`).classList.remove("hidden");
  const extra = $("#sidebar-extra");
  extra.innerHTML = "";
  stopJobPoll();
  if (view !== "jobs") stopJobStream();
  if (view !== "missions") stopMissionPoll();
  if (view !== "archive") stopArchivePoll();
  if (view !== "overview") { stopOpsPoll(); stopOpsStream(); }
  if (view !== "engineering") stopEngStream();
  if (view !== "learner") stopLearnerPoll();
  if (view === "overview") loadOverview();
  else if (view === "chat") renderSessionSidebar();
  else if (view === "programs") loadPrograms();
  else if (view === "learner") loadLearner();
  else if (view === "iip") loadIip();
  else if (view === "missions") loadMissions();
  else if (view === "archive") loadArchive();
  else if (view === "engineering") loadEngineering();
  else if (view === "personal") loadPersonal();
  else if (view === "jobs") { loadJobs(); startJobStream(); }
  else if (view === "system") loadSystem();
}

/* ---------- chat ---------- */
let sessions = [];

async function loadSessions() {
  try {
    const data = await api("/v1/chat/sessions?limit=50");
    sessions = data.sessions || [];
  } catch (err) { sessions = []; }
  if (state.view === "chat") renderSessionSidebar();
}

function renderSessionSidebar() {
  const extra = $("#sidebar-extra");
  extra.innerHTML = "";
  extra.append(el("button", { class: "newchat", onclick: () => startNewChat() }, "+ New chat"));
  extra.append(el("h3", { text: "Sessions" }));
  for (const s of sessions) {
    extra.append(el("button", {
      class: "session" + (s.id === state.sessionId ? " active" : ""),
      title: s.title || s.id,
      onclick: () => openSession(s.id),
    }, s.title || s.id.slice(0, 8)));
  }
}

function startNewChat() {
  state.sessionId = null;
  renderTranscript([]);
  renderSessionSidebar();
  $("#composer-input").focus();
}

async function openSession(id) {
  state.sessionId = id;
  renderSessionSidebar();
  try {
    const data = await api(`/v1/chat/sessions/${id}`);
    renderTranscript((data.messages || []).map((m) => ({
      role: m.role, answer: m.content, tool_calls: m.tool_calls || [],
    })));
  } catch (err) { toast(err.message); }
}

function renderTranscript(msgs) {
  const t = $("#transcript");
  t.innerHTML = "";
  if (!msgs.length) {
    t.append(el("div", { class: "empty-hint" },
      el("h2", { text: "Atlas" }),
      el("p", { class: "muted", text: "Ask a question, request research, or run a tool. Your conversation persists on the server." }),
    ));
    return;
  }
  for (const m of msgs) t.append(renderMessage(m));
  t.scrollTop = t.scrollHeight;
}

function renderMessage(m) {
  const wrap = el("div", { class: "msg " + (m.role === "user" ? "user" : "assistant") });
  wrap.append(el("div", { class: "role", text: m.role === "user" ? "you" : "atlas" }));
  wrap.append(el("div", { class: "bubble", text: m.answer || "" }));
  const calls = m.tool_calls || [];
  if (calls.length) {
    const chips = el("div", { class: "chips" });
    for (const c of calls) {
      const lbl = (c.action || c.intent || "step") + (c.outcome ? ` · ${c.outcome}` : "");
      chips.append(el("span", { class: "chip", text: lbl }));
    }
    wrap.append(chips);
  }
  for (const g of (m.capability_gaps || [])) {
    wrap.append(el("div", { class: "chips" },
      el("span", { class: "chip gap", text: "needs: " + (g.missing_capability || g.capability || "capability") })));
  }
  const cites = m.citations || [];
  if (cites.length) {
    const box = el("div", { class: "citations" });
    cites.forEach((c, i) => {
      const label = c.title || c.snippet || c.document_id || c.source_id || `source ${i + 1}`;
      const row = el("div", { class: "citation" });
      row.append(document.createTextNode(`[${c.index || i + 1}] `));
      if (c.url) row.append(el("a", { href: c.url, target: "_blank", rel: "noopener", text: label }));
      else row.append(document.createTextNode(label));
      box.append(row);
    });
    wrap.append(box);
  }
  return wrap;
}

async function sendMessage(text) {
  if (state.sending || !text.trim()) return;
  state.sending = true;
  $("#composer-send").disabled = true;
  const t = $("#transcript");
  if ($(".empty-hint")) t.innerHTML = "";
  t.append(renderMessage({ role: "user", answer: text }));
  const typing = el("div", { class: "msg assistant" },
    el("div", { class: "role", text: "atlas" }),
    el("div", { class: "bubble typing", text: "thinking…" }));
  t.append(typing);
  t.scrollTop = t.scrollHeight;
  try {
    const resp = await api("/v1/chat", { method: "POST", body: { message: text, session_id: state.sessionId } });
    state.sessionId = resp.session_id;
    typing.replaceWith(renderMessage({
      role: "assistant", answer: resp.answer, tool_calls: resp.tool_calls,
      citations: resp.citations, capability_gaps: resp.capability_gaps,
    }));
    t.scrollTop = t.scrollHeight;
    loadSessions();
  } catch (err) {
    typing.replaceWith(renderMessage({ role: "assistant", answer: "⚠ " + err.message }));
  } finally {
    state.sending = false;
    $("#composer-send").disabled = false;
  }
}

/* ---------- personal / owner dashboard (OI-C12) ---------- */
let personalTab = "skills";
let personalCache = null;

async function loadPersonal() {
  try {
    const d = await api("/v1/personal/dashboard?include_inferred=true");
    personalCache = d;
    renderPersonalDashboard(d);
  } catch (err) { toast(err.message); }
}

function personalIsNoiseDomain(name) {
  const d = String(name || "").toLowerCase();
  return d.startsWith("probe-") || d === "research" && false;
}

function personalIsNoiseFact(f) {
  const stmt = String(f.statement || f.key || "").trim();
  if (!stmt || stmt.toLowerCase() === "original") return true;
  if (/^skill-[a-f0-9]{8,}$/i.test(stmt)) return true;
  // Hash-suffixed celery/docker noise without a clean label
  if (/^(skilled in )?(celery|docker|redis|scala|rust|airflow|pg|role)-[a-f0-9]{6,}/i.test(stmt)
      && !/\b(FastAPI|python|typescript|Kafka)\b/i.test(stmt)) {
    return stmt.length > 40 || /-[a-f0-9]{6,}/i.test(stmt);
  }
  return false;
}

function personalUsefulFacts(facts) {
  return (facts || []).filter((f) => !personalIsNoiseFact(f));
}

function renderPersonalDashboard(d) {
  const covBox = $("#personal-coverage");
  const review = $("#personal-review");
  const body = $("#personal-body");
  if (!covBox || !body) return;
  covBox.innerHTML = "";
  if (review) review.innerHTML = "";
  body.innerHTML = "";

  const domains = ((d.coverage && d.coverage.domains) || [])
    .filter((row) => !personalIsNoiseDomain(row.domain));
  const overall = (d.coverage && d.coverage.overall) || {};
  covBox.append(el("div", { class: "panel-head" },
    el("h3", { class: "section-h", text: "Knowledge coverage" }),
    el("span", { class: "muted small",
      text: overall.coverage_pct != null
        ? ` overall ${overall.coverage_pct}% cov · ${overall.understanding_pct || 0}% understanding`
        : "" })));
  if (!domains.length) {
    covBox.append(el("div", { class: "muted", style: "padding:8px 22px",
      text: "No coverage rows yet — Owner Knowledge ticks fill this." }));
  } else {
    const list = el("div", { class: "cov-list" });
    // Prefer core domains first
    const order = ["personal", "code", "markets", "external", "skills"];
    const sorted = [...domains].sort((a, b) => {
      const ia = order.indexOf(String(a.domain || "").toLowerCase());
      const ib = order.indexOf(String(b.domain || "").toLowerCase());
      return (ia < 0 ? 99 : ia) - (ib < 0 ? 99 : ib);
    });
    for (const row of sorted.slice(0, 8)) {
      list.append(covBar(row.domain, row.coverage_pct, row.understanding_pct));
    }
    if (sorted.length > 8) {
      list.append(el("div", { class: "muted small", text: `+${sorted.length - 8} more domains hidden` }));
    }
    covBox.append(list);
  }

  const allFacts = []
    .concat(d.skills || [])
    .concat(d.timeline || [])
    .concat(d.professional || [])
    .concat(d.identity || []);
  const needs = personalUsefulFacts(allFacts).filter((f) => f.state === "inferred");
  if (review) {
    review.append(el("h3", { class: "section-h",
      text: `Needs your confirmation (${needs.length})` }));
    if (!needs.length) {
      review.append(el("div", { class: "muted", style: "padding:4px 22px 12px",
        text: "Nothing waiting — run Infer to propose facts, or they are already verified." }));
    } else {
      for (const f of needs.slice(0, 40)) {
        review.append(personalFactCard(f, { why: true, highlight: true }));
      }
      if (needs.length > 40) {
        review.append(el("div", { class: "muted small", style: "padding:8px 22px",
          text: `Showing 40 of ${needs.length} — confirm/reject to clear the queue.` }));
      }
    }
  }

  const counts = d.counts || {};
  const chips = el("div", { class: "status-cards", style: "padding:10px 22px 4px" },
    opsCard("skills", personalUsefulFacts(d.skills || []).length),
    opsCard("timeline", personalUsefulFacts(d.timeline || []).length),
    opsCard("professional", personalUsefulFacts(d.professional || []).length),
    opsCard("identity", personalUsefulFacts(d.identity || []).length),
    opsCard("to confirm", needs.length),
  );
  body.append(chips);
  renderPersonalTabBody(body, d, personalTab);
}

function renderPersonalTabBody(body, d, tab) {
  // Remove prior tab section (keep chips / draft)
  body.querySelectorAll(".personal-section, .personal-more, .career-panel").forEach((n) => n.remove());
  if (tab === "career") {
    body.append(renderCareerPanel(d.career || {}));
    return;
  }
  const map = {
    skills: d.skills || [],
    timeline: d.timeline || [],
    professional: d.professional || [],
    identity: d.identity || [],
  };
  const title = tab.charAt(0).toUpperCase() + tab.slice(1);
  const useful = personalUsefulFacts(map[tab] || []);
  // Prefer inferred first within tab, then verified
  useful.sort((a, b) => {
    const wa = a.state === "inferred" ? 0 : a.state === "verified" ? 1 : 2;
    const wb = b.state === "inferred" ? 0 : b.state === "verified" ? 1 : 2;
    return wa - wb;
  });
  const show = useful.slice(0, 50);
  body.append(personalFactSection(`${title}`, show, { why: true, total: useful.length }));
  if (useful.length > 50) {
    body.append(el("div", { class: "personal-more muted small",
      text: `Showing 50 of ${useful.length} cleaned facts (noisy hash labels hidden).` }));
  }
}

function renderCareerPanel(career) {
  const wrap = el("div", { class: "career-panel personal-section" });
  wrap.append(el("h3", { class: "section-h", text: "Career (suggestions only)" }));
  wrap.append(el("p", { class: "muted small", style: "padding:0 22px 8px;margin:0",
    text: "Atlas never edits LinkedIn or applies to jobs. You copy tips / apply yourself. Confirm CV facts first for better matches." }));

  const li = career.linkedin || {};
  const liBox = el("div", { class: "career-block" });
  liBox.append(el("h4", { class: "section-h", text: "LinkedIn improvements" }));
  liBox.append(el("div", { class: "muted small", style: "padding:0 22px 6px",
    text: li.note || "Suggestions only — Atlas will not write to LinkedIn." }));
  const tips = li.suggestions || [];
  if (!tips.length) {
    liBox.append(el("div", { class: "muted", style: "padding:4px 22px",
      text: li.error || "No suggestions yet — share resume + LinkedIn export path." }));
  } else {
    for (const t of tips.slice(0, 12)) {
      const row = el("div", { class: "career-tip" });
      row.append(el("span", { class: "badge " + (t.priority === "high" ? "warn" : "ok"),
        text: `${t.priority || "tip"} · ${t.area || ""}` }));
      row.append(el("div", { text: t.action || "" }));
      if (t.why) row.append(el("div", { class: "muted small", text: t.why }));
      liBox.append(row);
    }
  }
  if (li.draft_about) {
    liBox.append(el("div", { class: "muted small", style: "padding:8px 22px 0", text: "Draft About (paste yourself):" }));
    liBox.append(el("pre", { class: "career-draft", text: li.draft_about }));
  }
  const liRow = el("div", { class: "program-context-row", style: "padding:8px 22px" });
  const liPath = el("input", { placeholder: "LinkedIn export path or leave blank for profile-only tips", style: "flex:1" });
  const liBtn = el("button", {
    onclick: async () => {
      liBtn.disabled = true;
      try {
        const body = { include_inferred: true };
        const p = (liPath.value || "").trim();
        if (p.startsWith("http")) body.linkedin_url = p;
        else if (p) body.linkedin_path = p;
        const out = await api("/v1/personal/linkedin/suggestions", { method: "POST", body });
        if (personalCache) personalCache.career = { ...(personalCache.career || {}), linkedin: out };
        setPersonalTab("career");
        toast("LinkedIn suggestions refreshed");
      } catch (err) { toast(err.message); }
      finally { liBtn.disabled = false; }
    },
  }, "Refresh tips");
  liRow.append(liPath, liBtn);
  liBox.append(liRow);
  wrap.append(liBox);

  const jobs = (career.jobs || {}).jobs || [];
  const jobsBox = el("div", { class: "career-block" });
  jobsBox.append(el("h4", { class: "section-h", text: "Best open jobs for your profile" }));
  jobsBox.append(el("div", { class: "muted small", style: "padding:0 22px 6px",
    text: (career.jobs && career.jobs.note) || "Recommend-only — you apply yourself." }));
  if (!jobs.length) {
    jobsBox.append(el("div", { class: "muted", style: "padding:4px 22px",
      text: "No ranked jobs yet. Add a job_postings asset or share a jobs JSON export path below." }));
  } else {
    for (const j of jobs) {
      const row = el("div", { class: "career-job" });
      const title = [j.title, j.company].filter(Boolean).join(" · ");
      row.append(el("strong", { text: title || "(untitled)" }));
      const meta = [j.location, j.score != null ? `score ${j.score}` : null].filter(Boolean).join(" · ");
      if (meta) row.append(el("div", { class: "muted small", text: meta }));
      if (j.why) row.append(el("div", { class: "muted small", text: String(j.why).slice(0, 220) }));
      if (j.url) row.append(el("a", { href: j.url, target: "_blank", rel: "noopener", class: "link", text: "open listing" }));
      jobsBox.append(row);
    }
  }
  const feedRow = el("div", { class: "program-context-row", style: "padding:8px 22px" });
  const feedPath = el("input", { placeholder: "Optional jobs JSON export path", style: "flex:1" });
  const feedBtn = el("button", {
    onclick: async () => {
      feedBtn.disabled = true;
      try {
        const body = { limit: 10, include_inferred_skills: true };
        const p = (feedPath.value || "").trim();
        if (p) body.feed_path = p;
        const out = await api("/v1/personal/jobs", { method: "POST", body });
        if (personalCache) personalCache.career = { ...(personalCache.career || {}), jobs: out };
        setPersonalTab("career");
        toast((out.jobs || []).length ? `${out.jobs.length} job(s) ranked` : "No matches");
      } catch (err) { toast(err.message); }
      finally { feedBtn.disabled = false; }
    },
  }, "Rank jobs");
  feedRow.append(feedPath, feedBtn);
  jobsBox.append(feedRow);
  wrap.append(jobsBox);
  return wrap;
}

function setPersonalTab(tab) {
  personalTab = tab;
  document.querySelectorAll(".personal-tab").forEach((b) => {
    b.classList.toggle("active", b.dataset.tab === tab);
  });
  if (personalCache) {
    const body = $("#personal-body");
    if (body) renderPersonalTabBody(body, personalCache, tab);
  }
}

function covBar(domain, covPct, undPct) {
  const c = Math.max(0, Math.min(100, Number(covPct) || 0));
  const u = Math.max(0, Math.min(100, Number(undPct) || 0));
  const row = el("div", { class: "cov-row" });
  row.append(el("div", { class: "cov-label", text: domain }));
  const track = el("div", { class: "cov-track" });
  track.append(el("div", { class: "cov-fill cov",
    style: `background-size:${c}% 100%`, title: `coverage ${c}%` }));
  track.append(el("div", { class: "cov-fill und",
    style: `background-size:${u}% 100%`, title: `understanding ${u}%` }));
  row.append(track);
  row.append(el("div", { class: "cov-pct muted small", text: `${c}% / ${u}%` }));
  return row;
}

function personalFactSection(title, facts, opts) {
  const wrap = el("div", { class: "personal-section" });
  const total = (opts && opts.total != null) ? opts.total : facts.length;
  wrap.append(el("h3", { class: "section-h", text: `${title} (${total})` }));
  if (!facts.length) {
    wrap.append(el("div", { class: "muted", style: "padding:4px 22px 12px", text: "None yet." }));
    return wrap;
  }
  for (const f of facts) {
    wrap.append(personalFactCard(f, opts));
  }
  return wrap;
}

function personalFactCard(f, opts) {
  const card = el("div", {
    class: "personal-fact" + ((opts && opts.highlight && f.state === "inferred") ? " needs-confirm" : ""),
  });
  const head = el("div", { class: "personal-fact-head" });
  head.append(el("span", {
    class: "badge " + (f.state === "verified" ? "ok" : f.state === "rejected" ? "fail" : "warn"),
    text: f.state || "?",
  }));
  const skill = (f.value && f.value.proficiency) ? ` · ${f.value.proficiency}` : "";
  head.append(el("span", { class: "muted small",
    text: ` ${(f.category || "")}${skill}` }));
  card.append(head);
  card.append(el("div", { class: "personal-stmt", text: f.statement || f.key || f.id }));
  if (opts && opts.why) {
    const whyBits = [];
    if (f.source) whyBits.push(`source ${f.source}`);
    if (f.confidence) whyBits.push(f.confidence);
    const prov = f.provenance || {};
    if (prov.maturity) whyBits.push(`maturity ${prov.maturity}`);
    if (prov.proficiency) whyBits.push(prov.proficiency);
    if ((prov.sources || []).length) whyBits.push(`${prov.sources.length} evidence`);
    if (whyBits.length) {
      card.append(el("div", { class: "muted small", text: "why: " + whyBits.join(" · ") }));
    }
  }
  if (f.state === "inferred") {
    const actions = el("div", { class: "personal-actions" });
    actions.append(el("button", {
      class: "btn-confirm", type: "button",
      onclick: () => personalConfirm(f.id),
    }, "Confirm"));
    actions.append(el("button", {
      class: "btn-reject", type: "button",
      onclick: () => personalReject(f.id),
    }, "Reject"));
    card.append(actions);
  }
  return card;
}

async function personalConfirm(id) {
  try {
    await api(`/v1/personal/facts/${id}/confirm`, { method: "POST" });
    toast("Confirmed");
    loadPersonal();
  } catch (err) { toast(err.message); }
}

async function personalReject(id) {
  try {
    await api(`/v1/personal/facts/${id}/reject`, { method: "POST" });
    toast("Rejected");
    loadPersonal();
  } catch (err) { toast(err.message); }
}

async function personalInfer() {
  try {
    toast("Inferring profile…");
    const out = await api("/v1/personal/infer", { method: "POST" });
    toast(`Inferred skills=${out.skills || 0} timeline=${out.timeline || 0} professional=${out.professional || 0}`);
    loadPersonal();
  } catch (err) { toast(err.message); }
}

async function personalDraft() {
  try {
    const out = await api("/v1/personal/draft?kind=resume&include_inferred=false");
    const body = $("#personal-body");
    if (!body) return;
    let pre = body.querySelector(".personal-draft-md");
    if (!pre) {
      pre = el("pre", { class: "personal-draft-md career-draft" });
      body.prepend(pre);
    }
    pre.textContent = out.markdown || JSON.stringify(out, null, 2);
    toast("Resume draft ready (verified facts)");
  } catch (err) { toast(err.message); }
}

async function personalDraftLinkedIn() {
  try {
    const out = await api("/v1/personal/draft?kind=linkedin&include_inferred=true");
    const body = $("#personal-body");
    if (!body) return;
    let pre = body.querySelector(".personal-draft-md");
    if (!pre) {
      pre = el("pre", { class: "personal-draft-md career-draft" });
      body.prepend(pre);
    }
    pre.textContent = out.markdown || JSON.stringify(out, null, 2);
    setPersonalTab("career");
    toast("LinkedIn draft ready — paste yourself; Atlas will not post");
  } catch (err) { toast(err.message); }
}

/* ---------- engineering (Phase B · §B.7) ---------- */
async function loadEngineering() {
  startEngStream();
  try {
    const data = await api("/v1/engineering/repositories?limit=100");
    const repos = data.repositories || [];
    renderEngSummary(repos);
    renderRepoList(repos);
    if (state.repoId) showRepoDetail(state.repoId);
  } catch (err) { toast(err.message); }
}

function renderEngSummary(repos) {
  const box = $("#eng-summary");
  if (!box) return;
  box.innerHTML = "";
  const langs = new Set();
  for (const r of repos) {
    Object.keys(r.languages || {}).forEach((l) => langs.add(l));
  }
  box.append(el("div", { class: "learner-chip ok" },
    el("span", { class: "lbl", text: "Repositories" }),
    el("span", { class: "val", text: String(repos.length) }),
  ));
  box.append(el("div", { class: "learner-chip" },
    el("span", { class: "lbl", text: "Languages seen" }),
    el("span", { class: "val", text: String(langs.size) }),
  ));
  box.append(el("div", { class: "learner-chip" },
    el("span", { class: "lbl", text: "Tip" }),
    el("span", { class: "val", style: "font-size:13px;font-weight:500",
      text: repos.length ? "Select a repo → graph & findings" : "Ingest a path/URL to begin" }),
  ));
}

function renderRepoList(repos) {
  const list = $("#eng-list");
  list.innerHTML = "";
  if (!repos.length) {
    list.append(el("div", { class: "muted", style: "padding:18px",
      text: "No repositories learned yet — ingest one above." }));
    return;
  }
  for (const r of repos) {
    const langs = Object.keys(r.languages || {}).slice(0, 3).join(", ");
    list.append(el("div", {
      class: "job-row" + (r.id === state.repoId ? " active" : ""),
      onclick: () => showRepoDetail(r.id),
    },
      el("div", { class: "obj", text: r.name }),
      el("div", {},
        el("span", { class: "badge ok", text: langs || "code" }),
        el("span", { class: "muted small", text:
          `  ${r.symbol_count || 0} symbols`
          + (r.asset_version ? ` · asset v${r.asset_version}` : "") }),
      ),
    ));
  }
}

async function ingestRepo(source, embed, extra = {}) {
  const body = /^(https?:\/\/|git@)/.test(source) ? { url: source } : { path: source };
  body.embed = !!embed;
  if (extra.note) body.note = extra.note;
  if (extra.period_start) body.period_start = extra.period_start;
  if (extra.period_end) body.period_end = extra.period_end;

  const btn = $("#eng-ingest-btn");
  const status = $("#eng-status");
  const setStatus = (text, cls) => {
    if (!status) return;
    status.textContent = text;
    status.className = "eng-status small" + (cls ? " " + cls : "");
  };

  if (btn) btn.disabled = true;
  const started = Date.now();
  setStatus("Ingesting… please wait (large repos can take several minutes).", "eng-busy");
  toast("Ingest started…");

  try {
    const out = await api("/v1/engineering/ingest", { method: "POST", body });
    const secs = ((Date.now() - started) / 1000).toFixed(1);
    if (out.outcome !== "ok") {
      setStatus(`Failed (${secs}s): ${out.reason || "unknown error"}`, "eng-fail");
      toast("Ingest failed: " + (out.reason || "unknown"));
      return;
    }
    const name = (out.repository && out.repository.name) || source;
    const bits = [
      `Done (${secs}s): ${name}`,
      `findings=${out.findings || 0}`,
      `experiences=${out.experiences || 0}`,
    ];
    if (out.owner_context && out.owner_context.statement) {
      bits.push("timeline note saved — Confirm under Personal → Timeline");
    }
    setStatus(bits.join(" · "), "eng-ok");
    $("#eng-source").value = "";
    // keep note/period so user can reuse for related repos; clear note only
    if ($("#eng-note")) $("#eng-note").value = "";
    await loadEngineering();
    if (out.repository && out.repository.id) showRepoDetail(out.repository.id);
    toast("Repository ingested");
  } catch (err) {
    setStatus("Error: " + err.message, "eng-fail");
    toast(err.message);
  } finally {
    if (btn) btn.disabled = false;
  }
}

async function showRepoDetail(id) {
  state.repoId = id;
  document.querySelectorAll("#eng-list .job-row").forEach((r) => r.classList.remove("active"));
  try {
    const [detail, findings] = await Promise.all([
      api(`/v1/engineering/repositories/${id}`),
      api(`/v1/engineering/findings?repo_id=${id}&limit=200`),
    ]);
    let graph = null;
    try { graph = await api(`/v1/engineering/repositories/${id}/graph`); } catch (_) { graph = null; }
    renderRepoDetail(detail, graph, findings.findings || []);
  } catch (err) { toast(err.message); }
}

const FINDING_GROUPS = [
  ["structure", "Structure"],
  ["dependency", "Dependencies"],
  ["pattern", "Patterns"],
  ["design", "Design"],
  ["risk", "Risks"],
];

function renderRepoDetail(detail, graph, findings) {
  const box = $("#eng-detail");
  box.innerHTML = "";
  const r = detail.repository || {};
  box.append(el("div", { class: "obj-title", text: r.name || "repository" }));
  const langs = Object.entries(r.languages || {}).map(([k, v]) => `${k} ${v}`).join(" · ");
  box.append(el("div", { class: "muted small", text:
    `${r.file_count || 0} files · ${r.symbol_count || 0} symbols`
    + (r.asset_version ? ` · asset v${r.asset_version}` : "")
    + (r.repo_uid ? ` · uid ${String(r.repo_uid).slice(0, 8)}` : "") }));
  if (langs) box.append(el("div", { class: "muted small", text: langs }));
  if ((r.frameworks || []).length) {
    const chips = el("div", { class: "chips" });
    for (const f of r.frameworks) chips.append(el("span", { class: "chip", text: f }));
    box.append(chips);
  }

  const actions = el("div", { class: "job-actions" });
  actions.append(el("button", { onclick: () => designReview(r.id) }, "Run design review"));
  actions.append(el("button", { onclick: () => showRepoDetail(r.id) }, "Refresh"));
  box.append(actions);

  // Architecture graph summary
  box.append(el("h3", { class: "section-h", text: "Architecture graph" }));
  if (graph) {
    const c = graph.counts || {};
    const cards = el("div", { class: "status-cards" });
    for (const [k, v] of [["modules", c.modules], ["imports", c.import_edges],
                          ["calls", c.call_edges], ["entry points", c.entry_points]]) {
      cards.append(el("div", { class: "card" },
        el("div", { class: "k", text: k }), el("div", { class: "v", text: v ?? 0 })));
    }
    box.append(cards);
    const versions = detail.graph_versions || [];
    if (versions.length) {
      box.append(el("div", { class: "muted small", style: "margin-top:6px",
        text: `${versions.length} graph version(s); latest v${versions[0].version}` }));
    }
  } else {
    box.append(el("div", { class: "muted small", text: "No architecture graph yet." }));
  }

  // Findings grouped by claim type, each with the "why" (P9)
  box.append(el("h3", { class: "section-h", text: `Findings (${findings.length})` }));
  if (!findings.length) box.append(el("div", { class: "muted small", text: "No findings yet." }));
  for (const [type, label] of FINDING_GROUPS) {
    const group = findings.filter((f) => f.claim_type === type);
    if (!group.length) continue;
    box.append(el("h4", { class: "eng-group", text: `${label} (${group.length})` }));
    for (const f of group) box.append(renderFindingCard(f));
  }
}

function renderFindingCard(f) {
  const card = el("details", { class: "step" });
  card.append(el("summary", {},
    el("span", { class: "intent", text: f.statement || f.claim_type }),
    el("span", { class: "badge conf", text: f.confidence || "" }),
  ));
  const body = el("div", { class: "step-body" });
  const v = f.value || {}, p = f.provenance || {};
  if (v.rationale) body.append(el("div", { class: "step-desc muted", text: "Why: " + v.rationale }));
  if ((v.evidence || []).length) {
    body.append(el("div", { class: "step-label muted small", text: "evidence" }));
    const chips = el("div", { class: "chips" });
    for (const e of v.evidence) chips.append(el("span", { class: "chip", text: e }));
    body.append(chips);
  }
  if ((v.rejected_alternatives || []).length) {
    body.append(el("div", { class: "step-label muted small", text: "rejected alternatives" }));
    const chips = el("div", { class: "chips" });
    for (const a of v.rejected_alternatives) chips.append(el("span", { class: "chip gap", text: a }));
    body.append(chips);
  }
  const prov = [p.reader && `reader ${p.reader}${p.reader_version ? " v" + p.reader_version : ""}`,
                p.model && `model ${p.model}`, p.symbol && `symbol ${p.symbol}`]
    .filter(Boolean).join(" · ");
  if (prov) body.append(el("div", { class: "muted small", text: prov }));
  card.append(body);
  return card;
}

async function designReview(id) {
  try {
    toast("Running design review…");
    const out = await api(`/v1/engineering/design-review/${id}`, { method: "POST" });
    if (out.outcome !== "ok") { toast("Design review: " + (out.outcome || "unavailable")); }
    else toast(`Design review: ${out.design_findings} finding(s)`);
    showRepoDetail(id);
  } catch (err) { toast(err.message); }
}

// Live refresh: re-load the current repo when an engineering event arrives over SSE.
function startEngStream() {
  stopEngStream();
  const ctrl = new AbortController();
  state.engStream = ctrl;
  fetch("/v1/events/stream", {
    headers: { "Authorization": `Bearer ${state.key}` }, signal: ctrl.signal,
  }).then(async (res) => {
    if (!res.ok || !res.body) return;
    const reader = res.body.getReader();
    const dec = new TextDecoder();
    let buf = "";
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      let idx;
      while ((idx = buf.indexOf("\n\n")) >= 0) {
        const frame = buf.slice(0, idx); buf = buf.slice(idx + 2);
        if (/event:\s*(EngineeringIngested|DesignReviewed|WorkerTick)/.test(frame)) {
          if (state.view === "engineering") loadEngineering();
        }
      }
    }
  }).catch(() => { /* aborted on view switch */ });
}
function stopEngStream() {
  if (state.engStream) { try { state.engStream.abort(); } catch (_) {} state.engStream = null; }
}

/* ---------- jobs ---------- */
async function loadJobs() {
  try {
    const data = await api("/v1/jobs?limit=50");
    renderJobsList(data.jobs || []);
  } catch (err) { toast(err.message); }
}

function jobPhase(job) {
  return (job && job.phase) || "ready";
}

function jobIsActive(job) {
  if (!job) return false;
  if (["queued", "running"].includes(job.status)) return true;
  return ["planning_queued", "planning"].includes(jobPhase(job));
}

function jobStatusLabel(job) {
  const phase = jobPhase(job);
  if (["planning_queued", "planning"].includes(phase)) {
    return phase.replace(/_/g, " ");
  }
  return (job.status || "").replace(/_/g, " ");
}

function renderJobsList(jobs) {
  const list = $("#jobs-list");
  list.innerHTML = "";
  if (!jobs.length) { list.append(el("div", { class: "muted", style: "padding:18px", text: "No jobs yet." })); return; }
  for (const j of jobs) {
    const phase = jobPhase(j);
    const badgeClass = ["planning_queued", "planning"].includes(phase) ? phase : j.status;
    list.append(el("div", {
      class: "job-row" + (j.id === state.jobId ? " active" : ""),
      onclick: () => showJobDetail(j.id),
    },
      el("div", { class: "obj", text: j.objective }),
      el("div", {},
        el("span", { class: "badge " + badgeClass, text: jobStatusLabel(j) }),
        el("span", { class: "muted small", text: "  " + (j.created_at ? j.created_at.replace("T", " ").slice(0, 19) : "") }),
      ),
    ));
  }
}

async function createJob(objective) {
  try {
    const detail = await api("/v1/jobs", { method: "POST", body: { objective } });
    $("#job-objective").value = "";
    await loadJobs();
    showJobDetail(detail.job.id);
  } catch (err) { toast(err.message); }
}

async function showJobDetail(id) {
  state.jobId = id;
  document.querySelectorAll(".job-row").forEach((r) => r.classList.remove("active"));
  try {
    const d = await api(`/v1/jobs/${id}`);
    renderJobDetail(d);
    if (jobIsActive(d.job)) startJobPoll(id); else stopJobPoll();
  } catch (err) { toast(err.message); }
}

function stepDuration(s) {
  if (!s.started_at || !s.completed_at) return "";
  const ms = new Date(s.completed_at) - new Date(s.started_at);
  if (!(ms >= 0)) return "";
  return ms < 1000 ? `${ms}ms` : ms < 90000 ? `${(ms / 1000).toFixed(1)}s` : `${Math.round(ms / 60000)}m`;
}

function clockTime(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  return isNaN(d) ? "" : d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

/* Live "watch it work" feed (RL/C0): the newest events, most-recent first. */
function renderActivityFeed(activity, running) {
  const wrap = el("div", { class: "activity" });
  const head = el("h3", { class: "section-h", text: `Live activity (${activity.length})` });
  if (running) head.append(el("span", { class: "live-dot", title: "running" }));
  wrap.append(head);
  const feed = el("div", { class: "feed" });
  const recent = activity.slice(-40).reverse();
  for (const ev of recent) {
    const phase = ev.phase || "step";
    const row = el("div", { class: "feed-row" },
      el("span", { class: "feed-time muted small", text: clockTime(ev.ts) }),
      el("span", { class: "feed-phase phase-" + phase, text: phase }),
      el("span", { class: "feed-msg", text: ev.message || "" }),
    );
    feed.append(row);
  }
  wrap.append(feed);
  return wrap;
}

/* One expandable step: header (intent/capability/status) + a detail panel showing
   the tools it ran, the text it produced, and any sources it gathered. */
function renderStepCard(s) {
  const result = s.result || {};
  const calls = result.tool_calls || [];
  const citations = result.citations || [];
  const answer = result.answer || "";
  const dur = stepDuration(s);

  const card = el("details", { class: "step" });
  const summary = el("summary", {},
    el("span", { class: "ord", text: "#" + s.ordinal }),
    el("span", { class: "intent", text: s.intent }),
    el("span", { class: "cap muted small", text: s.capability }),
    el("span", { class: "badge " + s.status, text: s.status }),
    dur ? el("span", { class: "muted small dur", text: dur }) : null,
  );
  card.append(summary);

  const body = el("div", { class: "step-body" });
  if (s.description) body.append(el("div", { class: "step-desc muted", text: s.description }));
  if (s.depends_on != null) body.append(el("div", { class: "muted small", text: `depends on step #${s.depends_on}` }));

  if (calls.length) {
    const chips = el("div", { class: "chips" });
    for (const c of calls) {
      const lbl = (c.action || c.intent || "step") + (c.outcome ? ` · ${c.outcome}` : (c.ok === false ? " · failed" : ""));
      chips.append(el("span", { class: "chip", text: lbl }));
    }
    body.append(el("div", { class: "step-label muted small", text: "tools used" }), chips);
  }

  if (s.error) body.append(el("div", { class: "step-error", text: "error: " + s.error }));
  if (s.blocked_reason) body.append(el("div", { class: "chips" }, el("span", { class: "chip gap", text: "blocked: " + s.blocked_reason })));

  if (answer) {
    body.append(el("div", { class: "step-label muted small", text: "output" }));
    body.append(el("div", { class: "step-output", text: answer }));
  }

  if (citations.length) {
    body.append(el("div", { class: "step-label muted small", text: `sources gathered (${citations.length})` }));
    const box = el("div", { class: "citations" });
    citations.forEach((c, i) => {
      const lvl = c.evidence_level != null ? `L${c.evidence_level} ` : "";
      const label = lvl + (c.title || c.source_id || c.document_id || `source ${i + 1}`);
      const row = el("div", { class: "citation" });
      if (c.url) row.append(el("a", { href: c.url, target: "_blank", rel: "noopener", text: label }));
      else row.append(document.createTextNode(label));
      box.append(row);
    });
    body.append(box);
  }

  if (!calls.length && !answer && !citations.length && !s.error && !s.blocked_reason) {
    body.append(el("div", { class: "muted small", text: "No recorded output for this step." }));
  }
  card.append(body);
  return card;
}

function renderJobDetail(d) {
  const box = $("#job-detail");
  box.innerHTML = "";
  const job = d.job;
  const phase = jobPhase(job);
  const badgeClass = ["planning_queued", "planning"].includes(phase) ? phase : job.status;
  box.append(el("div", { class: "obj-title", text: job.objective }));
  box.append(el("div", {},
    el("span", { class: "badge " + badgeClass, text: jobStatusLabel(job) }),
    el("span", { class: "muted small", text: `  ${d.progress.done}/${d.progress.total} done`
      + (d.progress.blocked ? ` · ${d.progress.blocked} blocked` : "")
      + (d.progress.failed ? ` · ${d.progress.failed} failed` : "")
      + (phase && phase !== "ready" && phase !== job.status ? ` · ${phase.replace(/_/g, " ")}` : "") }),
  ));

  const running = jobIsActive(job);
  if ((d.activity || []).length) {
    box.append(renderActivityFeed(d.activity, running));
  } else if (["planning_queued", "planning"].includes(phase)) {
    box.append(el("div", { class: "muted small", style: "margin:10px 0",
      text: "Planning in progress — waiting for the JobPlanner…" }));
  }

  box.append(el("h3", { class: "section-h", text: `Steps executed (${d.steps.length})` }));
  const steps = el("div", { class: "steps" });
  if (!d.steps.length && ["planning_queued", "planning"].includes(phase)) {
    steps.append(el("div", { class: "muted small", text: "Steps will appear when planning finishes." }));
  }
  for (const s of d.steps) steps.append(renderStepCard(s));
  box.append(steps);

  for (const b of (d.blocked || [])) {
    box.append(el("div", { class: "chips" },
      el("span", { class: "chip gap", text: `step ${b.ordinal} needs: ${b.needs || b.capability}` })));
  }

  const usage = (d.usage && d.usage.human) || (job.result && job.result.usage && job.result.usage.human);
  if (usage) {
    box.append(el("div", { class: "muted small", style: "margin-top:10px", text: "Data usage: " + usage }));
  }

  // Steer a running / blocked job with extra guidance (queued between research rounds).
  if (["queued", "running", "completed_with_blocks"].includes(job.status)) {
    const steer = el("div", { class: "job-input" });
    steer.append(el("h3", { class: "section-h", text: "Add guidance" }));
    const ta = el("textarea", {
      rows: "2",
      placeholder: "e.g. focus on IEEE soiling-loss papers, ignore heliophysics…",
    });
    const send = el("button", {
      onclick: async () => {
        const text = (ta.value || "").trim();
        if (!text) return;
        send.disabled = true;
        try {
          await api(`/v1/jobs/${job.id}/input`, { method: "POST", body: { text } });
          ta.value = "";
          toast("Input queued for this job");
          showJobDetail(job.id);
        } catch (err) {
          toast(err.message);
        } finally {
          send.disabled = false;
        }
      },
    }, "Send to job");
    steer.append(ta, send);
    box.append(steer);
  }

  const actions = el("div", { class: "job-actions" });
  if (job.status === "completed_with_blocks")
    actions.append(el("button", { onclick: () => jobAction(job.id, "resume") }, "Resume"));
  if (jobIsActive(job))
    actions.append(el("button", { onclick: () => jobAction(job.id, "cancel") }, "Cancel"));
  actions.append(el("button", { onclick: () => showJobDetail(job.id) }, "Refresh"));
  box.append(actions);

  const report = job.result && job.result.report;
  const conf = job.result && job.result.overall_confidence;
  if (report || (job.result && job.result.answer)) {
    box.append(el("h3", { class: "section-h", text: "Report" },
      conf ? el("span", { class: "badge conf", text: conf }) : null));
    box.append(el("div", { class: "report", text: report || job.result.answer }));
  }
}

async function jobAction(id, action) {
  try {
    await api(`/v1/jobs/${id}/${action}`, { method: "POST" });
    await loadJobs();
    showJobDetail(id);
  } catch (err) { toast(err.message); }
}

// Sequential job polling (not setInterval+async). Overlapping GETs raced: a late
// "planning" response could overwrite a newer "running/completed" render and leave
// the UI stuck until manual refresh. One in-flight request at a time + generation
// guard discards stale responses.
const JOB_POLL_MAX_FAILURES = 8;
const JOB_POLL_MS = 1500;

function startJobPoll(id) {
  stopJobPoll();
  state.jobPollFailures = 0;
  state.jobPollGen = (state.jobPollGen || 0) + 1;
  const gen = state.jobPollGen;
  const tick = async () => {
    if (state.jobPollGen !== gen) return;
    if (state.view !== "jobs" || state.jobId !== id) {
      stopJobPoll();
      return;
    }
    try {
      const d = await api(`/v1/jobs/${id}`);
      if (state.jobPollGen !== gen || state.jobId !== id) return;
      state.jobPollFailures = 0;
      renderJobDetail(d);
      try { await loadJobs(); } catch (_) { /* list refresh is best-effort */ }
      if (!jobIsActive(d.job)) {
        stopJobPoll();
        return;
      }
    } catch (_) {
      state.jobPollFailures = (state.jobPollFailures || 0) + 1;
      if (state.jobPollFailures >= JOB_POLL_MAX_FAILURES) {
        stopJobPoll();
        return;
      }
    }
    if (state.jobPollGen !== gen) return;
    state.jobPoll = setTimeout(tick, JOB_POLL_MS);
  };
  state.jobPoll = setTimeout(tick, JOB_POLL_MS);
}

function stopJobPoll() {
  if (state.jobPoll) {
    clearTimeout(state.jobPoll);
    state.jobPoll = null;
  }
  // Bump generation so any in-flight tick abandons its render.
  state.jobPollGen = (state.jobPollGen || 0) + 1;
  state.jobPollFailures = 0;
}

// Push refresh for the open job (OI-UI0). Poll remains a fallback when SSE is quiet.
const JOB_SSE_EVENTS = /event:\s*(job\.activity|job\.step_blocked|job\.finalized)/;

function startJobStream() {
  stopJobStream();
  const ctrl = new AbortController();
  state.jobStream = ctrl;
  fetch("/v1/events/stream", {
    headers: { "Authorization": `Bearer ${state.key}` },
    signal: ctrl.signal,
  }).then(async (res) => {
    if (!res.ok || !res.body) return;
    const reader = res.body.getReader();
    const dec = new TextDecoder();
    let buf = "";
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      let idx;
      while ((idx = buf.indexOf("\n\n")) >= 0) {
        const frame = buf.slice(0, idx);
        buf = buf.slice(idx + 2);
        if (!JOB_SSE_EVENTS.test(frame)) continue;
        if (state.view !== "jobs") continue;
        try { await loadJobs(); } catch (_) { /* list refresh best-effort */ }
        if (state.jobId) {
          try {
            const d = await api(`/v1/jobs/${state.jobId}`);
            if (state.view === "jobs" && state.jobId) {
              renderJobDetail(d);
              if (jobIsActive(d.job)) startJobPoll(state.jobId);
              else stopJobPoll();
            }
          } catch (_) { /* detail refresh best-effort */ }
        }
      }
    }
  }).catch(() => { /* aborted on view switch */ });
}

function stopJobStream() {
  if (state.jobStream) {
    try { state.jobStream.abort(); } catch (_) {}
    state.jobStream = null;
  }
}

/* ---------- programs (MI.1) ---------- */
let programsCache = [];

async function loadPrograms() {
  try {
    const data = await api("/v1/programs");
    programsCache = data.programs || [];
    renderProgramsList(programsCache);
    const prefer = state.programId || "market_intelligence";
    const hit = programsCache.find((p) => p.id === prefer) || programsCache[0];
    if (hit) showProgramDetail(hit.id);
  } catch (err) { toast(err.message); }
}

function renderProgramsList(programs) {
  const list = $("#programs-list");
  if (!list) return;
  list.innerHTML = "";
  if (!programs.length) {
    list.append(el("div", { class: "muted", style: "padding:18px", text: "No Programs registered." }));
    return;
  }
  for (const p of programs) {
    list.append(el("div", {
      class: "job-row" + (p.id === state.programId ? " active" : ""),
      onclick: () => showProgramDetail(p.id),
    },
      el("div", { class: "obj", text: p.title }),
      el("div", {},
        el("span", { class: "badge " + (p.startable_count ? "active" : "draft"),
          text: p.startable_count ? `${p.startable_count} startable` : "stubs" }),
        el("span", { class: "muted small",
          text: `  ${p.members?.length || 0} missions · ${p.stub_count || 0} stub` }),
      ),
    ));
  }
}

async function showProgramDetail(id) {
  state.programId = id;
  document.querySelectorAll("#programs-list .job-row").forEach((r) => r.classList.remove("active"));
  // Mark active in list without refetching everyone.
  document.querySelectorAll("#programs-list .job-row").forEach((r, i) => {
    const p = programsCache[i];
    if (p) r.classList.toggle("active", p.id === id);
  });
  try {
    const p = await api(`/v1/programs/${id}`);
    renderProgramDetail(p);
  } catch (err) { toast(err.message); }
}

function renderLifecycleBoard(board, title) {
  const wrap = el("div", { class: "lifecycle-board" });
  if (title) wrap.append(el("h3", { class: "section-h", text: title }));
  const row = el("div", { class: "lifecycle-row" });
  for (const stage of (board || [])) {
    row.append(el("div", { class: "lifecycle-stage status-" + (stage.status || "n-a").replace("/", "-") },
      el("div", { class: "lifecycle-label", text: stage.label || stage.stage }),
      el("div", { class: "lifecycle-status", text: stage.status || "n/a" }),
    ));
  }
  wrap.append(row);
  return wrap;
}

function renderProgramDetail(p) {
  const box = $("#program-detail");
  if (!box) return;
  box.innerHTML = "";
  box.append(el("div", { class: "obj-title", text: p.title }));
  box.append(el("div", { class: "muted", style: "margin:6px 0 12px", text: p.description || "" }));
  if (p.domain_adapters && p.domain_adapters.length) {
    box.append(el("div", { class: "muted small", style: "margin-bottom:12px",
      text: "Domain adapters: " + p.domain_adapters.join(" · ") }));
  }

  box.append(renderLifecycleBoard(p.lifecycle, "Cognitive lifecycle"));

  const actions = el("div", { class: "job-actions" });
  const startBtn = el("button", {
    onclick: async () => {
      startBtn.disabled = true;
      try {
        const result = await api(`/v1/programs/${p.id}/start`, { method: "POST" });
        const n = (result.started || []).length;
        const skip = (result.skipped || []).length;
        toast(n ? `Started ${n} mission(s); ${skip} skipped/stub` : `Nothing new started (${skip} skipped/stub)`);
        await loadPrograms();
        showProgramDetail(p.id);
      } catch (err) { toast(err.message); }
      finally { startBtn.disabled = false; }
    },
  }, p.startable_count ? "Start Program" : "Start Program (stubs only)");
  actions.append(startBtn);
  actions.append(el("button", { onclick: () => showProgramDetail(p.id) }, "Refresh"));
  box.append(actions);

  // Context spike
  const ctx = el("div", { class: "program-context" });
  ctx.append(el("h3", { class: "section-h", text: "Context (MCA.1 spike)" }));
  const ctxRow = el("div", { class: "program-context-row" });
  const ctxInput = el("input", { placeholder: "Topic, e.g. inflation or Reliance", style: "flex:1" });
  const ctxBtn = el("button", {
    onclick: async () => {
      const q = (ctxInput.value || "").trim();
      if (!q) return;
      try {
        const data = await api(`/v1/programs/${p.id}/context?q=${encodeURIComponent(q)}&limit=8`);
        renderProgramContextResults(ctxResults, data);
      } catch (err) { toast(err.message); }
    },
  }, "Gather");
  ctxRow.append(ctxInput, ctxBtn);
  ctx.append(ctxRow);
  const ctxResults = el("div", { class: "program-context-results muted small" });
  ctx.append(ctxResults);
  box.append(ctx);

  // Program chat — share resume / past work once (Personal + Engineering).
  box.append(renderProgramChat(p));

  box.append(el("h3", { class: "section-h", text: "Program members" }));
  for (const m of (p.members || [])) {
    const card = el("div", { class: "program-member" });
    card.append(el("div", { class: "program-member-head" },
      el("strong", { text: m.role }),
      el("span", { class: "badge " + (m.status === "stub" ? "draft" : m.can_start ? "active" : "paused"),
        text: m.status }),
    ));
    card.append(el("div", { class: "muted small",
      text: `${m.template} · ${m.kind} · ${m.cadence}` }));
    if (m.description) card.append(el("div", { class: "muted small", text: m.description }));
    if (m.missions && m.missions.length) {
      for (const miss of m.missions) {
        card.append(el("div", { class: "small", style: "margin-top:4px" },
          el("a", {
            href: "#",
            class: "link",
            onclick: (e) => {
              e.preventDefault();
              switchView("missions");
              showMissionDetail(miss.id);
            },
          }, `${miss.title || miss.id} (${miss.status})`),
        ));
      }
    } else if (m.status === "stub") {
      card.append(el("div", { class: "muted small", text: "Disabled stub — ships in MI.2+" }));
    }
    // Mini lifecycle from member philosophy
    const lc = m.philosophy && m.philosophy.lifecycle;
    if (lc) {
      const board = Object.keys(lc).map((stage) => ({
        stage,
        label: stage.replace(/_/g, " "),
        status: lc[stage],
      }));
      // Keep canonical order if possible
      const order = ["observe","learn","assess_resources","decide","record_why","evaluate","reflect","improve"];
      board.sort((a, b) => order.indexOf(a.stage) - order.indexOf(b.stage));
      card.append(renderLifecycleBoard(board));
    }
    box.append(card);
  }
}

function renderProgramContextResults(box, data) {
  box.innerHTML = "";
  if (!data || !(data.items || []).length) {
    box.textContent = data?.note || "No matching context yet.";
    return;
  }
  box.append(el("div", { text: `${data.count} item(s) — ${data.note || ""}` }));
  for (const item of data.items) {
    const line = item.statement || item.content || JSON.stringify(item);
    box.append(el("div", { class: "program-context-item",
      text: `[${item.kind}] ${String(line).slice(0, 200)}` }));
  }
}

function renderProgramChat(p) {
  if (!state.programChat) state.programChat = {};
  if (!state.programChat[p.id]) {
    state.programChat[p.id] = { sessionId: null, messages: [] };
  }
  const chatState = state.programChat[p.id];
  const wrap = el("div", { class: "program-chat" });
  wrap.append(el("h3", { class: "section-h", text: "Program chat" }));
  wrap.append(el("p", { class: "muted small",
    text: "Share materials once — resume/docs for Personal; past-work repos feed Personal and Engineering together (no double upload)." }));

  const transcript = el("div", { class: "program-chat-transcript" });
  const paint = () => {
    transcript.innerHTML = "";
    if (!chatState.messages.length) {
      transcript.append(el("div", { class: "muted small",
        text: "Try: share /path/to/resume.pdf · learn from /path/to/my-project" }));
      return;
    }
    for (const m of chatState.messages) {
      transcript.append(el("div", { class: "program-chat-msg " + m.role },
        el("div", { class: "role", text: m.role === "user" ? "you" : "atlas" }),
        el("div", { class: "bubble", text: m.answer || m.text || "" }),
      ));
    }
    transcript.scrollTop = transcript.scrollHeight;
  };
  paint();
  wrap.append(transcript);

  const shareRow = el("div", { class: "program-context-row" });
  const pathInput = el("input", {
    placeholder: "Host path — resume.pdf or past-work repo",
    style: "flex:1",
  });
  const shareBtn = el("button", {
    onclick: async () => {
      const path = (pathInput.value || "").trim();
      if (!path) return;
      shareBtn.disabled = true;
      try {
        const data = await api(`/v1/programs/${p.id}/share`, {
          method: "POST",
          body: { path, process_now: true },
        });
        const feeds = (data.feeds || []).join(", ");
        chatState.messages.push({
          role: "assistant",
          answer: `Shared ${data.path} as ${data.kind} → ${feeds}. ${data.note || ""}`,
        });
        pathInput.value = "";
        paint();
        toast("Shared once for Personal" + (data.kind === "code" ? " + Engineering" : ""));
      } catch (err) { toast(err.message); }
      finally { shareBtn.disabled = false; }
    },
  }, "Share path");
  shareRow.append(pathInput, shareBtn);
  wrap.append(shareRow);

  const row = el("div", { class: "program-context-row" });
  const input = el("input", {
    placeholder: "Message — e.g. share /data/me/resume.pdf",
    style: "flex:1",
  });
  const send = async () => {
    const text = (input.value || "").trim();
    if (!text) return;
    input.value = "";
    chatState.messages.push({ role: "user", answer: text });
    paint();
    sendBtn.disabled = true;
    try {
      const resp = await api(`/v1/programs/${p.id}/chat`, {
        method: "POST",
        body: { message: text, session_id: chatState.sessionId },
      });
      if (resp.session_id) chatState.sessionId = resp.session_id;
      chatState.messages.push({ role: "assistant", answer: resp.answer || "" });
      paint();
    } catch (err) {
      chatState.messages.push({ role: "assistant", answer: "⚠ " + err.message });
      paint();
    } finally {
      sendBtn.disabled = false;
    }
  };
  const sendBtn = el("button", { onclick: send }, "Send");
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); }
  });
  row.append(input, sendBtn);
  wrap.append(row);
  return wrap;
}

/* ---------- learner dashboard ---------- */
let learnerPoll = null;

function stopLearnerPoll() {
  if (learnerPoll) { clearInterval(learnerPoll); learnerPoll = null; }
}

function startLearnerPoll() {
  stopLearnerPoll();
  const box = $("#learner-auto");
  if (box && !box.checked) return;
  learnerPoll = setInterval(() => {
    if (state.view !== "learner") return stopLearnerPoll();
    const auto = $("#learner-auto");
    if (auto && !auto.checked) return stopLearnerPoll();
    loadLearner({ quiet: true });
  }, 15000);
}

async function loadIip() {
  const failBox = $("#iip-failures");
  const uniBox = $("#iip-universes");
  const srcBox = $("#iip-sources");
  const capBox = $("#iip-capabilities");
  const methBox = $("#iip-methodology");
  const helpBox = $("#iip-help");
  if (!failBox) return;
  failBox.innerHTML = "<p class='muted'>Loading intelligence catalog…</p>";
  try {
    const data = await api("/v1/market/intelligence-catalog");
    const live = data.live || {};
    const failures = live.feed_failures || {};
    const items = failures.items || [];
    const byReason = failures.by_reason || {};
    let failHtml = "<div class='panel-head'><h3 class='section-h'>Web / feed failures</h3></div>";
    failHtml += `<p class='muted small'>${esc(failures.help || "")}</p>`;
    failHtml += `<p class='small'>Yahoo enabled: <strong>${live.yahoo_enabled ? "yes" : "no"}</strong>`;
    if (live.providers && live.providers.length) {
      failHtml += ` · providers: ${live.providers.map((p) => esc(p.name || p)).join(", ")}`;
    }
    failHtml += "</p>";
    if (Object.keys(byReason).length) {
      failHtml += "<ul class='small'>";
      Object.entries(byReason).slice(0, 8).forEach(([r, n]) => {
        failHtml += `<li><code>${esc(r)}</code> ×${n}</li>`;
      });
      failHtml += "</ul>";
    }
    if (!items.length) {
      failHtml += "<p class='muted small'>No recent fetch failures logged.</p>";
    } else {
      failHtml += "<ul class='small iip-fail-list'>";
      items.slice(0, 25).forEach((row) => {
        failHtml += `<li><span class='muted'>${esc((row.ts || "").slice(0, 19))}</span> `
          + `<strong>${esc(row.provider || "?")}</strong> ${esc(row.symbol || "")} — ${esc(row.reason || "")}</li>`;
      });
      failHtml += "</ul>";
    }
    failBox.innerHTML = failHtml;

    const uv = live.universes || {};
    let uniHtml = "<div class='panel-head'><h3 class='section-h'>Universes (IIP.1)</h3></div>";
    uniHtml += `<p class='muted small'>${esc(uv.note || "")} Union size: <strong>${uv.union_count || 0}</strong></p>`;
    uniHtml += "<div class='iip-uni-list'>";
    (uv.universes || []).forEach((u) => {
      const staged = u.staged ? ", staged" : "";
      uniHtml += `<label class='iip-uni-row'><input type='checkbox' class='iip-uni-cb' data-uni='${esc(u.id)}' `
        + `${u.enabled ? "checked" : ""} /> ${esc(u.label)} `
        + `<span class='muted small'>(${u.count || 0}${staged})</span></label>`;
      if (u.note) uniHtml += `<div class='muted small' style='margin:-2px 0 6px 24px'>${esc(u.note).slice(0, 160)}</div>`;
    });
    uniHtml += "</div>";
    uniBox.innerHTML = uniHtml;

    const discBox = $("#iip-discovery");
    const disc = live.discovery || {};
    let discHtml = "<div class='panel-head'><h3 class='section-h'>Latest discovery (IIP.2)</h3></div>";
    discHtml += `<p class='muted small'>${esc(disc.note || "Run discovery after enabling universes.")}</p>`;
    if (disc.ist_date) {
      discHtml += `<p class='small'>Date <strong>${esc(disc.ist_date)}</strong> · interesting `
        + `<strong>${disc.interesting_count || (disc.interesting || []).length}</strong>`
        + ` · scanned ${disc.scanned || "?"} · feed failures ${disc.feed_failures || 0}</p>`;
    }
    const interesting = disc.interesting || [];
    if (!interesting.length) {
      discHtml += "<p class='muted small'>No discovery run yet — click <em>Run discovery now</em>.</p>";
    } else {
      discHtml += "<ul class='small'>";
      interesting.slice(0, 20).forEach((r) => {
        discHtml += `<li><strong>${esc(r.symbol)}</strong> <code>${esc(r.mode)}</code> `
          + `<span class='muted'>${esc(r.horizon)}</span> — ${esc((r.why || "").slice(0, 160))}</li>`;
      });
      discHtml += "</ul>";
    }
    if (discBox) discBox.innerHTML = discHtml;

    const themeBox = $("#iip-themes");
    const themes = (live.themes && live.themes.themes) || [];
    let thHtml = "<div class='panel-head'><h3 class='section-h'>Macro themes</h3></div>";
    thHtml += `<p class='muted small'>${esc((live.themes && live.themes.note) || "")}</p><ul class='small'>`;
    themes.forEach((t) => {
      thHtml += `<li><strong>${esc(t.label)}</strong> (${t.count || 0} names) `
        + `<span class='muted'>${esc(t.horizon_default)}</span>`
        + `<div class='muted'>${esc(t.hypothesis || "")}</div></li>`;
    });
    thHtml += "</ul>";
    if (themeBox) themeBox.innerHTML = thHtml;

    const fundBox = $("#iip-fundamentals");
    const fund = live.fundamentals || {};
    let fundHtml = "<div class='panel-head'><h3 class='section-h'>Fundamentals import (IIP.3)</h3></div>";
    fundHtml += `<p class='muted small'>${esc(fund.guide || "")}</p>`;
    fundHtml += `<p class='small'>Store count: <strong>${fund.count || 0}</strong>`;
    if (fund.drop_dir) fundHtml += ` · drop dir <code>${esc(fund.drop_dir)}</code>`;
    fundHtml += "</p>";
    const fundRows = fund.rows || [];
    if (fundRows.length) {
      fundHtml += "<ul class='small'>";
      fundRows.slice(0, 15).forEach((r) => {
        fundHtml += `<li><strong>${esc(r.symbol)}</strong> `
          + `<code>${esc(r.evidence_sufficiency || "?")}</code> `
          + `ROE ${r.roe != null ? esc(String(r.roe)) : "—"} · `
          + `ROCE ${r.roce != null ? esc(String(r.roce)) : "—"} · `
          + `D/E ${r.debt_to_equity != null ? esc(String(r.debt_to_equity)) : "—"} `
          + `<span class='muted'>${esc(r.source || "")} ${esc(r.as_of || "")}</span></li>`;
      });
      fundHtml += "</ul>";
    } else {
      fundHtml += "<p class='muted small'>No imported fundamentals yet — paste CSV/JSON below.</p>";
    }
    fundHtml += "<label class='muted small' for='iip-fund-paste'>Paste Screener CSV or JSON rows</label>";
    fundHtml += "<textarea id='iip-fund-paste' rows='5' spellcheck='false' "
      + "placeholder='symbol,roe,roce,debt_to_equity,operating_margin,promoter_holding,pe&#10;INFY,28,32,0.1,24,60,25'></textarea>";
    fundHtml += "<div class='panel-actions' style='margin-top:8px'>";
    fundHtml += "<button id='iip-fund-import' class='btn' type='button'>Import paste</button> ";
    fundHtml += "<button id='iip-fund-drop' class='link' type='button'>Ingest drop folder</button>";
    fundHtml += "<label class='small' style='margin-left:12px'><input type='checkbox' id='iip-fund-ira' /> push to IRA</label>";
    fundHtml += "</div>";
    if (fundBox) fundBox.innerHTML = fundHtml;
    const fundImportBtn = $("#iip-fund-import");
    if (fundImportBtn) fundImportBtn.addEventListener("click", () => importIipFundamentals());
    const fundDropBtn = $("#iip-fund-drop");
    if (fundDropBtn) fundDropBtn.addEventListener("click", () => ingestIipFundamentalsDrop());

    const docsBox = $("#iip-documents");
    const docs = live.company_documents || {};
    let docsHtml = "<div class='panel-head'><h3 class='section-h'>Company documents (IIP.4)</h3></div>";
    docsHtml += `<p class='muted small'>${esc(docs.guide || "")}</p>`;
    docsHtml += `<p class='small'>Imported: <strong>${docs.count || 0}</strong>`;
    if (docs.drop_dir) docsHtml += ` · drop <code>${esc(docs.drop_dir)}</code>`;
    docsHtml += "</p>";
    const docRows = docs.documents || [];
    if (docRows.length) {
      docsHtml += "<ul class='small'>";
      docRows.slice(0, 12).forEach((r) => {
        docsHtml += `<li><strong>${esc(r.symbol)}</strong> <code>${esc(r.kind || "")}</code> `
          + `claims ${r.claims_count != null ? r.claims_count : "?"} `
          + `<span class='muted'>${esc(r.outcome || "")} ${esc(r.as_of || "")}</span></li>`;
      });
      docsHtml += "</ul>";
    } else {
      docsHtml += "<p class='muted small'>No company docs yet — paste text or host path below.</p>";
    }
    docsHtml += "<div class='iip-doc-form'>";
    docsHtml += "<input id='iip-doc-symbol' placeholder='Symbol e.g. INFY' /> ";
    docsHtml += "<select id='iip-doc-kind'>"
      + "<option value='annual'>annual (A)</option>"
      + "<option value='quarterly'>quarterly (B)</option>"
      + "<option value='presentation'>presentation (C)</option>"
      + "<option value='deck'>deck (C)</option>"
      + "<option value='transcript'>transcript (D)</option>"
      + "<option value='earnings_call'>earnings call (D)</option>"
      + "</select>";
    docsHtml += "<input id='iip-doc-path' placeholder='Host path to PDF (optional)' style='min-width:240px' />";
    docsHtml += "</div>";
    docsHtml += "<label class='muted small' for='iip-doc-text'>Or paste excerpt / transcript text</label>";
    docsHtml += "<textarea id='iip-doc-text' rows='4' spellcheck='false' "
      + "placeholder='Management guidance: we expect mid-teens revenue growth. Key risks include commodity prices. ROCE 22%. Debt to equity 0.2.'></textarea>";
    docsHtml += "<div class='panel-actions' style='margin-top:8px'>";
    docsHtml += "<button id='iip-doc-import' class='btn' type='button'>Import to IRA</button> ";
    docsHtml += "<button id='iip-doc-drop' class='link' type='button'>Ingest drop folder</button>";
    docsHtml += "</div>";
    if (docsBox) docsBox.innerHTML = docsHtml;
    const docImportBtn = $("#iip-doc-import");
    if (docImportBtn) docImportBtn.addEventListener("click", () => importIipDocument());
    const docDropBtn = $("#iip-doc-drop");
    if (docDropBtn) docDropBtn.addEventListener("click", () => ingestIipDocumentsDrop());

    const mkgBox = $("#iip-mkg");
    const mkg = live.mkg || {};
    const demo = live.mkg_demo || {};
    let mkgHtml = "<div class='panel-head'><h3 class='section-h'>Market Knowledge Graph (IIP.5)</h3></div>";
    mkgHtml += `<p class='muted small'>${esc(mkg.note || "Theme ↔ company ↔ policy edges (hermetic).")}</p>`;
    const st = mkg.stats || {};
    mkgHtml += `<p class='small'>Nodes <strong>${st.nodes || 0}</strong> · edges <strong>${st.edges || 0}</strong></p>`;
    const whyDemo = demo.why_own_waaree || {};
    if (whyDemo.summary) {
      mkgHtml += `<p class='small'><strong>Demo why-own WAAREE:</strong> ${esc(whyDemo.summary)}</p>`;
    }
    mkgHtml += "<div class='iip-doc-form'>";
    mkgHtml += "<input id='iip-mkg-symbol' placeholder='Symbol e.g. WAAREE' /> ";
    mkgHtml += "<button id='iip-mkg-why' class='btn' type='button'>Why own?</button> ";
    mkgHtml += "<select id='iip-mkg-theme'>";
    ["defence", "green_energy", "data_centers", "ev_battery", "ai_it", "railways", "healthcare", "power_grid"].forEach((t) => {
      mkgHtml += `<option value='${t}'>${t}</option>`;
    });
    mkgHtml += "</select> ";
    mkgHtml += "<button id='iip-mkg-benefits' class='link' type='button'>Who benefits?</button> ";
    mkgHtml += "<button id='iip-mkg-reseed' class='link' type='button'>Reseed</button>";
    mkgHtml += "</div>";
    mkgHtml += "<div id='iip-mkg-result' class='small muted' style='margin-top:8px'></div>";
    if (mkgBox) mkgBox.innerHTML = mkgHtml;
    const whyBtn = $("#iip-mkg-why");
    if (whyBtn) whyBtn.addEventListener("click", () => runIipMkgWhy());
    const benBtn = $("#iip-mkg-benefits");
    if (benBtn) benBtn.addEventListener("click", () => runIipMkgBenefits());
    const reseedBtn = $("#iip-mkg-reseed");
    if (reseedBtn) reseedBtn.addEventListener("click", () => runIipMkgReseed());

    const thesisBox = $("#iip-thesis");
    const ttLive = live.thesis_tracker || {};
    const priors = ttLive.priors || {};
    let thHtml = "<div class='panel-head'><h3 class='section-h'>Thesis Tracker (IIP.8)</h3></div>";
    thHtml += "<p class='muted small'>Hypothesis → assumptions → outcome → priors. "
      + "Weight shifts unlock at N≥20 closed paper outcomes.</p>";
    thHtml += `<p class='small'>Closed outcomes <strong>${priors.closed_outcomes || 0}</strong>`
      + ` · ready for weight shift: <strong>${priors.ready_for_weight_shift ? "yes" : "no"}</strong></p>`;
    const lessons = priors.failure_lessons || [];
    if (lessons.length) {
      thHtml += "<p class='muted small'>Recent failure lessons:</p><ul class='small'>";
      lessons.slice(0, 5).forEach((l) => { thHtml += `<li>${esc(l)}</li>`; });
      thHtml += "</ul>";
    }
    thHtml += "<div class='iip-doc-form'>";
    thHtml += "<input id='iip-thesis-symbol' placeholder='Symbol e.g. INFY' /> ";
    thHtml += "<button id='iip-thesis-open' class='btn' type='button'>Open from awareness</button> ";
    thHtml += "<button id='iip-thesis-load' class='link' type='button'>Load tracker</button>";
    thHtml += "</div>";
    thHtml += "<div id='iip-thesis-result' class='small muted' style='margin-top:8px'></div>";
    const rows = ttLive.trackers || [];
    if (rows.length) {
      thHtml += "<ul class='small' style='margin-top:8px'>";
      rows.slice(0, 12).forEach((r) => {
        thHtml += `<li><strong>${esc(r.symbol)}</strong> <code>${esc(r.status)}</code>`
          + ` · ${esc(r.decision || "?")} — ${esc(r.hypothesis || "")}</li>`;
      });
      thHtml += "</ul>";
    } else {
      thHtml += "<p class='muted small'>No trackers yet — open after a sim buy or via the form.</p>";
    }
    if (thesisBox) thesisBox.innerHTML = thHtml;
    const thOpen = $("#iip-thesis-open");
    if (thOpen) thOpen.addEventListener("click", () => runIipThesisOpen());
    const thLoad = $("#iip-thesis-load");
    if (thLoad) thLoad.addEventListener("click", () => runIipThesisLoad());

    const newsBox = $("#iip-news");
    const nf = live.news_feeds || {};
    const demoLinks = live.chart_links_demo || {};
    let newsHtml = "<div class='panel-head'><h3 class='section-h'>News feeds &amp; chart links (IIP.9)</h3></div>";
    newsHtml += "<p class='muted small'>RSS allow-list only (no HTML scrape). Feeds disabled by default — enable verified ids then Fetch.</p>";
    newsHtml += `<p class='small'>Allow-list feeds: <strong>${(nf.feeds || []).length}</strong> · enabled <strong>${nf.enabled_count || 0}</strong></p>`;
    const last = nf.last_fetch || {};
    if (last.fetched_at) {
      newsHtml += `<p class='muted small'>Last fetch ${esc(last.fetched_at)} · items ${last.item_count || 0}</p>`;
    }
    newsHtml += "<ul class='small'>";
    (nf.feeds || []).slice(0, 8).forEach((f) => {
      newsHtml += `<li><code>${esc(f.id)}</code> ${esc(f.label || "")} `
        + `<strong>${f.enabled ? "on" : "off"}</strong> · ${esc(f.kind || "news")}</li>`;
    });
    newsHtml += "</ul>";
    newsHtml += "<div class='iip-doc-form'>";
    newsHtml += "<input id='iip-rss-enable' placeholder='Enable ids e.g. pib_press' style='min-width:180px' /> ";
    newsHtml += "<button id='iip-rss-fetch' class='btn' type='button'>Fetch RSS</button> ";
    newsHtml += "<label class='small'><input type='checkbox' id='iip-rss-policy' /> into policy</label>";
    newsHtml += "</div>";
    newsHtml += "<div id='iip-news-result' class='small muted' style='margin-top:8px'></div>";
    if (demoLinks.tradingview) {
      newsHtml += `<p class='small' style='margin-top:10px'>Chart links demo (INFY): `
        + `<a href="${esc(demoLinks.tradingview)}" target="_blank" rel="noopener">TradingView</a>`
        + ` · <a href="${esc(demoLinks.yahoo)}" target="_blank" rel="noopener">Yahoo</a></p>`;
    }
    newsHtml += "<div class='iip-doc-form'>";
    newsHtml += "<input id='iip-chart-symbol' placeholder='Symbol for chart links' /> ";
    newsHtml += "<button id='iip-chart-load' class='link' type='button'>Chart links</button>";
    newsHtml += "</div>";
    newsHtml += "<div id='iip-chart-result' class='small muted' style='margin-top:6px'></div>";
    if (newsBox) newsBox.innerHTML = newsHtml;
    const rssBtn = $("#iip-rss-fetch");
    if (rssBtn) rssBtn.addEventListener("click", () => runIipRssFetch());
    const chartBtn = $("#iip-chart-load");
    if (chartBtn) chartBtn.addEventListener("click", () => runIipChartLinks());

    let srcHtml = "<div class='panel-head'><h3 class='section-h'>Websites &amp; data sources</h3></div><ul class='small'>";
    (data.sources || []).forEach((s) => {
      const link = s.url ? ` · <a href="${esc(s.url)}" target="_blank" rel="noopener">${esc(s.url)}</a>` : "";
      srcHtml += `<li><strong>${esc(s.name)}</strong> <code>${esc(s.status)}</code>${link}`
        + `<div class='muted'>${esc(s.purpose || "")}</div>`
        + `<div class='muted'>Needs: ${esc(s.needs || "—")} · ${esc(s.operator_help || "")}</div></li>`;
    });
    srcHtml += "</ul>";
    srcBox.innerHTML = srcHtml;

    let capHtml = "<div class='panel-head'><h3 class='section-h'>Capabilities</h3></div><ul class='small'>";
    (data.capabilities || []).forEach((c) => {
      capHtml += `<li><strong>${esc(c.name)}</strong> <code>${esc(c.status)}</code> — ${esc(c.description || "")}</li>`;
    });
    capHtml += "</ul>";
    capBox.innerHTML = capHtml;

    const meth = data.methodology || {};
    let methHtml = "<div class='panel-head'><h3 class='section-h'>Research methodology</h3></div>";
    methHtml += `<p class='small'><strong>${esc(meth.product || "")}</strong> · ${esc(meth.house || "")}</p>`;
    methHtml += "<p class='muted small'>Pipeline:</p><ol class='small'>";
    (meth.pipeline || []).forEach((p) => { methHtml += `<li>${esc(p)}</li>`; });
    methHtml += "</ol><p class='muted small'>Principles:</p><ul class='small'>";
    (meth.principles || []).forEach((p) => { methHtml += `<li>${esc(p)}</li>`; });
    methHtml += "</ul>";
    if (meth.research) {
      methHtml += `<p class='small'>Horizons: ${(meth.research.horizons || []).map(esc).join(", ")}</p>`;
      const dc = meth.research.dual_confidence || {};
      methHtml += `<p class='muted small'>Research confidence: ${esc(dc.research_confidence || "")}<br/>`
        + `Investment confidence: ${esc(dc.investment_confidence || "")}</p>`;
    }
    methBox.innerHTML = methHtml;

    let helpHtml = "<div class='panel-head'><h3 class='section-h'>How you can help Atlas</h3></div><ul class='small'>";
    (data.how_to_help || []).forEach((h) => { helpHtml += `<li>${esc(h)}</li>`; });
    helpHtml += "</ul>";
    helpBox.innerHTML = helpHtml;
  } catch (err) {
    failBox.innerHTML = `<p class='error'>Failed to load catalog: ${esc(err.message || err)}</p>`;
  }
}

async function saveIipUniverses() {
  const enabled = [...document.querySelectorAll(".iip-uni-cb:checked")].map((el) => el.dataset.uni);
  if (!enabled.length) {
    toast("Select at least one universe");
    return;
  }
  try {
    await api("/v1/market/universes/enabled", {
      method: "POST",
      body: { enabled },
    });
    toast("Universes saved — next Investment Universe tick will use the union");
    loadIip();
  } catch (err) {
    toast(err.message || String(err));
  }
}

async function importIipFundamentals() {
  const ta = $("#iip-fund-paste");
  const text = (ta && ta.value || "").trim();
  if (!text) {
    toast("Paste CSV or JSON first");
    return;
  }
  const pushIra = !!( $("#iip-fund-ira") && $("#iip-fund-ira").checked );
  const body = { push_to_ira: pushIra, auto_refresh: false };
  if (text.startsWith("{") || text.startsWith("[")) {
    try {
      body.json = JSON.parse(text);
    } catch (err) {
      toast("Invalid JSON: " + (err.message || err));
      return;
    }
  } else {
    body.csv = text;
    body.source = "screener_export";
  }
  try {
    const res = await api("/v1/market/fundamentals/import", { method: "POST", body });
    toast(`Imported ${res.imported || 0} · store ${res.store_count || 0}`
      + (res.ira ? ` · IRA ${res.ira.pushed || 0}` : ""));
    loadIip();
  } catch (err) {
    toast(err.message || String(err));
  }
}

async function ingestIipFundamentalsDrop() {
  try {
    const res = await api("/v1/market/fundamentals/import-drop", { method: "POST", body: {} });
    toast(`Drop ingest: ${res.imported || 0} rows from ${(res.files || []).length} file(s)`);
    loadIip();
  } catch (err) {
    toast(err.message || String(err));
  }
}

async function importIipDocument() {
  const symbol = ($("#iip-doc-symbol") && $("#iip-doc-symbol").value || "").trim();
  const kind = ($("#iip-doc-kind") && $("#iip-doc-kind").value) || "annual";
  const path = ($("#iip-doc-path") && $("#iip-doc-path").value || "").trim();
  const text = ($("#iip-doc-text") && $("#iip-doc-text").value || "").trim();
  if (!symbol) {
    toast("Symbol required");
    return;
  }
  if (!path && !text) {
    toast("Provide a host PDF path or paste text");
    return;
  }
  const body = { symbol, kind, push_to_ira: true, auto_refresh: true };
  if (path) body.path = path;
  if (text) body.text = text;
  try {
    const res = await api("/v1/market/company-documents/import", { method: "POST", body });
    toast(
      `${res.symbol || symbol} · ${res.claims_count || 0} claims · `
      + `coverage ${res.coverage_before ?? "?"}→${res.coverage_after ?? "?"}`
      + (res.lifted ? " · lifted" : "")
    );
    loadIip();
  } catch (err) {
    toast(err.message || String(err));
  }
}

async function ingestIipDocumentsDrop() {
  try {
    const res = await api("/v1/market/company-documents/import-drop", {
      method: "POST",
      body: { push_to_ira: true, auto_refresh: false },
    });
    const ira = res.ira || {};
    toast(`Docs: ${res.imported || 0} files · IRA ${ira.pushed || 0}`);
    loadIip();
  } catch (err) {
    toast(err.message || String(err));
  }
}

async function runIipMkgWhy() {
  const sym = ($("#iip-mkg-symbol") && $("#iip-mkg-symbol").value || "").trim() || "WAAREE";
  const out = $("#iip-mkg-result");
  try {
    const res = await api(`/v1/market/mkg/why-own/${encodeURIComponent(sym)}`);
    if (out) {
      out.innerHTML = `<strong>${esc(res.symbol || sym)}</strong> <code>${esc(res.status || "")}</code><br/>`
        + `${esc(res.summary || "")}<br/>`
        + `themes ${(res.themes || []).length} · policies ${(res.policies || []).length}`
        + ` · financial cites ${(res.financial_cites || []).length}`;
    }
  } catch (err) {
    toast(err.message || String(err));
  }
}

async function runIipMkgBenefits() {
  const theme = ($("#iip-mkg-theme") && $("#iip-mkg-theme").value) || "defence";
  const out = $("#iip-mkg-result");
  try {
    const res = await api(`/v1/market/mkg/who-benefits?theme_id=${encodeURIComponent(theme)}`);
    const names = (res.companies || []).slice(0, 12).map((c) => c.symbol).join(", ");
    if (out) {
      out.innerHTML = `<strong>${esc(theme)}</strong>: ${res.count || 0} companies<br/>${esc(names)}`;
    }
  } catch (err) {
    toast(err.message || String(err));
  }
}

async function runIipMkgReseed() {
  try {
    const res = await api("/v1/market/mkg/reseed", { method: "POST", body: {} });
    toast(`MKG reseeded · nodes ${(res.stats || {}).nodes} · edges ${(res.stats || {}).edges}`);
    loadIip();
  } catch (err) {
    toast(err.message || String(err));
  }
}

async function runIipThesisOpen() {
  const sym = ($("#iip-thesis-symbol") && $("#iip-thesis-symbol").value || "").trim() || "INFY";
  const out = $("#iip-thesis-result");
  try {
    const res = await api(`/v1/market/thesis-tracker/${encodeURIComponent(sym)}/open`, {
      method: "POST",
      body: { from_awareness: true, decision: "watch" },
    });
    const tr = res.tracker || {};
    if (out) {
      out.innerHTML = `<strong>${esc(tr.symbol || sym)}</strong> <code>${esc(tr.status)}</code>`
        + ` · ${esc(tr.decision || "")}<div>${esc((tr.hypothesis || "").slice(0, 200))}</div>`;
    }
    loadIip();
  } catch (err) {
    if (out) out.textContent = err.message || String(err);
    else toast(err.message || String(err));
  }
}

async function runIipThesisLoad() {
  const sym = ($("#iip-thesis-symbol") && $("#iip-thesis-symbol").value || "").trim() || "INFY";
  const out = $("#iip-thesis-result");
  try {
    const res = await api(`/v1/market/thesis-tracker/${encodeURIComponent(sym)}`);
    const tr = res.tracker || {};
    if (!tr || res.status === "absent") {
      if (out) out.textContent = res.note || "No tracker";
      return;
    }
    const assump = (tr.assumptions || []).map((a) => `${a.kind}:${a.status}`).join(", ");
    if (out) {
      out.innerHTML = `<strong>${esc(tr.symbol)}</strong> <code>${esc(tr.status)}</code>`
        + `<div>${esc((tr.hypothesis || "").slice(0, 200))}</div>`
        + `<div class='muted'>Assumptions: ${esc(assump || "—")}</div>`;
    }
  } catch (err) {
    if (out) out.textContent = err.message || String(err);
    else toast(err.message || String(err));
  }
}

async function runIipRssFetch() {
  const out = $("#iip-news-result");
  const raw = ($("#iip-rss-enable") && $("#iip-rss-enable").value || "").trim();
  const enable = raw ? raw.split(/[\s,]+/).filter(Boolean) : [];
  const intoPolicy = !!( $("#iip-rss-policy") && $("#iip-rss-policy").checked );
  try {
    const res = await api("/v1/market/news-feeds/fetch", {
      method: "POST",
      body: { enable, into_policy: intoPolicy },
    });
    const f = res.fetch || {};
    if (out) {
      out.textContent = `ok_feeds=${f.ok_feeds || 0} items=${f.item_count || 0}`
        + (intoPolicy ? " · merged into policy catalog" : "");
    }
    toast("RSS fetch done");
    loadIip();
  } catch (err) {
    if (out) out.textContent = err.message || String(err);
    else toast(err.message || String(err));
  }
}

async function runIipChartLinks() {
  const sym = ($("#iip-chart-symbol") && $("#iip-chart-symbol").value || "").trim() || "INFY";
  const out = $("#iip-chart-result");
  try {
    const res = await api(`/v1/market/chart-links/${encodeURIComponent(sym)}`);
    if (out) {
      out.innerHTML = `<a href="${esc(res.tradingview)}" target="_blank" rel="noopener">TradingView</a>`
        + ` · <a href="${esc(res.yahoo)}" target="_blank" rel="noopener">Yahoo</a>`
        + ` · <a href="${esc(res.screener)}" target="_blank" rel="noopener">Screener</a>`
        + `<div class='muted'>${esc(res.note || "")}</div>`;
    }
  } catch (err) {
    if (out) out.textContent = err.message || String(err);
  }
}

async function loadLearner(opts = {}) {
  const quiet = !!(opts && opts.quiet);
  const summary = $("#learner-summary");
  const planBox = $("#learner-plan");
  const wlBox = $("#learner-watchlist");
  const checkBox = $("#learner-checklist");
  const bookBox = $("#learner-book");
  if (!summary || !planBox) return;

  if (!quiet) {
    summary.innerHTML = "";
    planBox.innerHTML = "";
    planBox.append(el("div", { class: "learner-empty", text: "Loading…" }));
  }

  let status = null;
  let plan = null;
  let watch = null;
  let portfolios = null;
  let missions = null;

  const results = await Promise.allSettled([
    api("/v1/learner/status"),
    api("/v1/market/daily-plan?portfolio_key=india_equity_learner&capital=10000"),
    api("/v1/market/watchlist?limit=15"),
    api("/v1/market/portfolios"),
    api("/v1/missions?limit=100"),
  ]);
  if (results[0].status === "fulfilled") status = results[0].value;
  if (results[1].status === "fulfilled") plan = results[1].value;
  if (results[2].status === "fulfilled") watch = results[2].value;
  if (results[3].status === "fulfilled") portfolios = results[3].value;
  if (results[4].status === "fulfilled") missions = results[4].value;

  renderLearnerSummary(summary, { status, plan, watch });
  renderLearnerPlan(planBox, plan);
  renderLearnerWatchlist(wlBox, watch);
  renderLearnerChecklist(checkBox, status);
  renderLearnerBook(bookBox, { status, portfolios, missions, plan });
  loadInvestorEmailStatus();
  loadLearnerResearchList();
  startLearnerPoll();
}

async function loadInvestorEmailStatus() {
  const box = $("#learner-email-status");
  if (!box) return;
  try {
    const st = await api("/v1/market/investor-report/status");
    const ready = !!(st && st.ready);
    const recipients = ((st && st.recipients) || []).join(", ") || "(none)";
    const missing = (st && st.missing) || [];
    box.className = "learner-email-status small " + (ready ? "ok" : "warn");
    box.textContent = ready
      ? `Email ready → ${recipients}`
      : `Email not ready — missing: ${missing.join("; ") || "check .env"}`;
    const meta = $("#learner-email-meta");
    if (meta) {
      const smtp = (st && st.smtp) || {};
      meta.textContent = st && st.hint
        ? st.hint
        : `SMTP ${smtp.host || "?"} as ${smtp.from_addr || smtp.username || "?"}`;
    }
    const sendBtn = $("#learner-email-send");
    if (sendBtn) sendBtn.disabled = !ready;
    const sendEve = $("#learner-email-send-evening");
    if (sendEve) sendEve.disabled = !ready;
    const sendWeek = $("#learner-email-send-weekly");
    if (sendWeek) sendWeek.disabled = !ready;
  } catch (err) {
    box.className = "learner-email-status small warn";
    box.textContent = "Could not check email status — is Atlas restarted with investor_mailer?";
  }
}

async function previewInvestorEmail(kind) {
  const reportKind = (kind === "evening")
    ? "evening"
    : (kind === "weekly" ? "weekly" : "morning");
  const pre = $("#learner-email-preview-body");
  const meta = $("#learner-email-meta");
  const box = $("#learner-email-status");
  if (!pre) return;
  pre.hidden = false;
  pre.textContent = `Building ${reportKind} preview…`;
  try {
    const prev = await api(`/v1/market/investor-report/preview?kind=${reportKind}`);
    const to = ((prev && prev.recipients) || []).join(", ") || "(no recipients)";
    if (meta) {
      meta.textContent = `To: ${to}` + (prev.subject ? ` · Subject: ${prev.subject}` : "");
    }
    pre.textContent = [
      "Subject: " + ((prev && prev.subject) || "(none)"),
      "To: " + to,
      "",
      (prev && prev.body) || "(empty body — wait for daily plan / Investment Universe tick)",
    ].join("\n");
    if (box && prev && prev.ready === false) {
      box.className = "learner-email-status small warn";
      box.textContent = "Preview OK — but SMTP/receivers not ready to send yet.";
    }
  } catch (err) {
    pre.textContent = "Preview failed: " + (err && err.message ? err.message : String(err));
  }
}

async function sendInvestorEmail(kind) {
  const reportKind = (kind === "evening")
    ? "evening"
    : (kind === "weekly" ? "weekly" : "morning");
  const btn = reportKind === "evening"
    ? $("#learner-email-send-evening")
    : (reportKind === "weekly"
      ? $("#learner-email-send-weekly")
      : $("#learner-email-send"));
  const pre = $("#learner-email-preview-body");
  const box = $("#learner-email-status");
  const idleLabel = reportKind === "evening"
    ? "Send evening"
    : (reportKind === "weekly" ? "Send weekly" : "Send morning");
  if (btn) {
    btn.disabled = true;
    btn.classList.add("busy");
    btn.textContent = "Sending…";
  }
  try {
    const path = reportKind === "weekly"
      ? "/v1/market/investor-report/weekly?force=true"
      : `/v1/market/investor-report/${reportKind}?force=true`;
    const result = await api(path, { method: "POST" });
    if (pre) {
      pre.hidden = false;
      pre.textContent = [
        result.sent ? "SENT ✓" : "NOT SENT: " + (result.reason || "unknown"),
        "Subject: " + (result.subject || ""),
        "To: " + (((result.recipients) || []).join(", ") || "(none)"),
        "",
        result.body || "(no body returned)",
      ].join("\n");
    }
    if (box) {
      box.className = "learner-email-status small " + (result.sent ? "ok" : "warn");
      box.textContent = result.sent
        ? `Sent to ${((result.recipients) || []).join(", ")}`
        : `Send failed: ${result.reason || "smtp_send_failed"} — check App Password / Gmail SMTP`;
    }
  } catch (err) {
    if (box) {
      box.className = "learner-email-status small warn";
      box.textContent = "Send error: " + (err && err.message ? err.message : String(err));
    }
  } finally {
    if (btn) {
      btn.classList.remove("busy");
      btn.textContent = idleLabel;
      await loadInvestorEmailStatus();
    }
  }
}

function renderLearnerSummary(box, { status, plan, watch }) {
  box.innerHTML = "";
  const phase = (plan && plan.phase) || (watch && watch.extra && watch.extra.phase) || "—";
  const conf = (plan && plan.confidence) || "—";
  const nRanked = (watch && watch.count) || 0;
  const nCand = (plan && plan.candidates && plan.candidates.length) || 0;
  const capital = (plan && plan.capital) != null ? plan.capital : 10000;
  const learning = String(phase).toLowerCase() === "learning"
    || String(conf).toLowerCase().includes("very_low");

  const chips = [
    { lbl: "Universe", val: (watch && watch.index) || (plan && plan.index) || "NIFTY50" },
    { lbl: "Watchlist", val: nRanked ? `${nRanked} ranked` : "none yet" },
    { lbl: "Today's candidates", val: String(nCand), cls: nCand ? "ok" : "" },
    { lbl: "Phase", val: String(phase), cls: learning ? "warn" : "ok" },
    { lbl: "Confidence", val: String(conf), cls: learning ? "warn" : "" },
    { lbl: "Book capital", val: `₹${Number(capital).toLocaleString("en-IN")}` },
  ];
  for (const c of chips) {
    box.append(el("div", { class: "learner-chip" + (c.cls ? " " + c.cls : "") },
      el("span", { class: "lbl", text: c.lbl }),
      el("span", { class: "val", text: c.val }),
    ));
  }
  if (plan && plan.summary) {
    box.append(el("div", {
      class: "muted small",
      style: "flex:1 1 100%;padding:4px 2px 0",
      text: plan.summary,
    }));
  } else if (status && status.narrative) {
    box.append(el("div", {
      class: "muted small",
      style: "flex:1 1 100%;padding:4px 2px 0",
      text: status.narrative,
    }));
  }
}

function renderLearnerPlan(box, plan) {
  box.innerHTML = "";
  if (!plan || !(plan.candidates || []).length) {
    box.append(el("div", {
      class: "learner-empty",
      text: (plan && plan.notes && plan.notes[0])
        || "No daily plan yet — wait for Investment Universe to tick, or start India learner.",
    }));
    if (plan && (plan.notes || []).length) {
      for (const n of plan.notes.slice(0, 4)) {
        box.append(el("div", { class: "muted small", style: "margin-top:6px", text: n }));
      }
    }
    return;
  }
  box.append(el("div", {
    class: "muted small",
    style: "margin-bottom:8px",
    text: `Simulation sizing only (P10) · deploy ~${Math.round((plan.deploy_fraction || 0.4) * 100)}% of ₹${Number(plan.capital || 0).toLocaleString("en-IN")}`,
  }));
  for (const c of plan.candidates) {
    const why = (c.why || "").trim() || ((c.explanations || [])[0] || "");
    const whyText = typeof why === "string" ? why : (why && why.text) || "";
    const researchBits = [];
    if (c.research_coverage != null) researchBits.push(`cov ${c.research_coverage}%`);
    if (c.mvr_satisfied) researchBits.push("MVR✓");
    if (c.thesis_stance) researchBits.push(String(c.thesis_stance));
    const row = el("div", { class: "learner-row" },
      el("div", { class: "rank", text: String(c.rank || "·") }),
      el("div", {},
        el("div", { class: "sym", text: c.symbol + (c.name ? ` · ${c.name}` : "") }),
        whyText ? el("div", { class: "why", text: whyText }) : null,
        c.thesis_summary ? el("div", { class: "why", text: c.thesis_summary }) : null,
        researchBits.length
          ? el("div", { class: "why", text: "Research: " + researchBits.join(" · ") })
          : null,
      ),
      el("div", {
        class: "notional",
        text: c.suggested_notional != null
          ? `₹${Number(c.suggested_notional).toLocaleString("en-IN")}`
          : "—",
      }),
    );
    box.append(row);
  }
  if ((plan.avoids || []).length) {
    box.append(el("div", {
      class: "muted small",
      style: "margin-top:12px;margin-bottom:4px",
      text: "Avoid / weaker (relative)",
    }));
    for (const a of plan.avoids.slice(0, 5)) {
      const sym = typeof a === "string" ? a : (a.symbol || JSON.stringify(a));
      const why = typeof a === "object" ? (a.why || a.reason || "") : "";
      box.append(el("div", { class: "learner-row learner-avoid" },
        el("div", { class: "rank", text: "–" }),
        el("div", {},
          el("div", { class: "sym", text: sym }),
          why ? el("div", { class: "why", text: why }) : null,
        ),
        el("div", { class: "notional", text: "" }),
      ));
    }
  }
  for (const n of (plan.notes || []).slice(0, 3)) {
    box.append(el("div", { class: "muted small", style: "margin-top:8px", text: n }));
  }
}

function renderLearnerWatchlist(box, watch) {
  box.innerHTML = "";
  const rows = (watch && (watch.ranked || watch.watchlist)) || [];
  if (!rows.length) {
    box.append(el("div", {
      class: "learner-empty",
      text: (watch && watch.note) || "Watchlist empty — open Investment Universe journal or start India learner.",
    }));
    return;
  }
  box.append(el("div", {
    class: "muted small",
    style: "margin-bottom:8px",
    text: `${watch.index || "universe"} · showing ${rows.length} of ${watch.count || rows.length}`,
  }));
  rows.forEach((r, i) => {
    const why = (r.reason || r.why || "").trim();
    const sym = r.symbol || "";
    const researchBtn = el("button", {
      class: "link",
      type: "button",
      text: "Research",
      onclick: () => {
        const input = $("#learner-research-symbol");
        if (input) input.value = sym;
        startLearnerResearch(sym);
      },
    });
    box.append(el("div", { class: "learner-row" },
      el("div", { class: "rank", text: String(r.rank || i + 1) }),
      el("div", {},
        el("div", { class: "sym", text: sym + (r.name ? ` · ${r.name}` : "") }),
        why ? el("div", { class: "why", text: why }) : null,
        r.sector ? el("div", { class: "why", text: r.sector }) : null,
      ),
      el("div", { class: "notional learner-row-actions" },
        r.score != null ? el("span", { text: Number(r.score).toFixed(3) }) : null,
        researchBtn,
      ),
    ));
  });
}

async function loadLearnerResearchList(opts) {
  const quiet = !!(opts && opts.quiet);
  const box = $("#learner-research-body");
  const status = $("#learner-research-status");
  if (!box) return;
  try {
    const data = await api("/v1/market/research");
    const items = (data && data.items) || [];
    if (status && !quiet) {
      const detail = $("#learner-research-detail");
      if (!detail || !detail.childElementCount) {
        status.textContent = items.length
          ? `${items.length} symbol(s) researched`
          : "No research yet — enter a symbol or use Research on the watchlist.";
      }
    }
    box.innerHTML = "";
    if (!items.length) {
      box.append(el("div", {
        class: "learner-empty",
        text: "Studied / decided / learned will appear here after MVR runs.",
      }));
      return;
    }
    for (const aw of items.slice(0, 12)) {
      const mvr = aw.mvr_satisfied ? "MVR✓" : "MVR…";
      const thesis = (aw.thesis && aw.thesis.summary) || (aw.brief && aw.brief.thesis) || "";
      box.append(el("div", { class: "learner-row" },
        el("div", { class: "rank", text: mvr }),
        el("div", {},
          el("div", { class: "sym", text: aw.symbol || "" }),
          el("div", {
            class: "why",
            text: `cov ${aw.coverage}% · conf ${aw.confidence} · ${aw.phase || ""}`
              + (aw.thesis && aw.thesis.stance ? ` · ${aw.thesis.stance}` : ""),
          }),
          thesis ? el("div", { class: "why", text: String(thesis).slice(0, 160) }) : null,
        ),
        el("div", { class: "notional" },
          el("button", {
            class: "link",
            type: "button",
            text: "Open",
            onclick: () => showLearnerResearch(aw.symbol),
          }),
        ),
      ));
    }
  } catch (err) {
    if (status && !quiet) {
      status.textContent = "Research API unavailable — restart Atlas to load IRA.";
    }
  }
}

async function startLearnerResearch(symbol) {
  const status = $("#learner-research-status");
  const input = $("#learner-research-symbol");
  const sym = (symbol || (input && input.value) || "").trim();
  if (!sym) {
    if (status) status.textContent = "Enter a symbol (e.g. RELIANCE.NS or MTARTECH).";
    return;
  }
  if (status) status.textContent = `Running MVR for ${sym}…`;
  try {
    const result = await api(`/v1/market/research/${encodeURIComponent(sym)}`, {
      method: "POST",
      body: { mode: "mvr", force: true },
    });
    const aw = (result && result.awareness) || {};
    if (status) {
      status.textContent = result && result.ok === false
        ? `Research blocked: ${result.reason || "error"}`
        : `${aw.symbol || sym}: ${aw.phase || "done"} · cov ${aw.coverage}% · conf ${aw.confidence}`
          + (aw.mvr_satisfied ? " · MVR✓" : " · MVR incomplete");
    }
    await showLearnerResearch(aw.symbol || sym);
    await loadLearnerResearchList({ quiet: true });
    const detail = $("#learner-research-detail");
    if (detail && typeof detail.scrollIntoView === "function") {
      detail.scrollIntoView({ behavior: "smooth", block: "nearest" });
    }
  } catch (err) {
    if (status) {
      status.textContent = "Research failed: " + (err && err.message ? err.message : String(err));
    }
  }
}

function _snapNum(id) {
  const el = $(id);
  if (!el || el.value === "" || el.value == null) return null;
  const n = Number(el.value);
  return Number.isFinite(n) ? n : null;
}

async function applyLearnerResearchSnapshot() {
  const status = $("#learner-research-status");
  const input = $("#learner-research-symbol");
  const sym = ((input && input.value) || "").trim();
  if (!sym) {
    if (status) status.textContent = "Enter a symbol before applying a snapshot.";
    return;
  }
  const body = {
    pe: _snapNum("#snap-pe"),
    fcf: _snapNum("#snap-fcf"),
    price: _snapNum("#snap-price"),
    shares: _snapNum("#snap-shares"),
    roe: _snapNum("#snap-roe"),
    roic: _snapNum("#snap-roic"),
    debt_to_equity: _snapNum("#snap-de"),
    revenue_cagr: _snapNum("#snap-rev-cagr"),
    evidence_confidence: (($("#snap-confidence") || {}).value) || "verified",
    note: (($("#snap-note") || {}).value) || "",
    auto_refresh: true,
  };
  const fields = Object.entries(body).filter(([k, v]) =>
    k === "evidence_confidence" || k === "note" || k === "auto_refresh" ? false : v != null
  );
  if (!fields.length) {
    if (status) status.textContent = "Enter at least one number (PE, FCF, price, …).";
    return;
  }
  if (status) status.textContent = `Applying operator snapshot for ${sym}…`;
  try {
    const result = await api(`/v1/market/research/${encodeURIComponent(sym)}/snapshot`, {
      method: "POST",
      body,
    });
    const aw = (result && result.awareness) || {};
    const impacted = (result && result.impacted_sections) || [];
    if (status) {
      status.textContent = `${aw.symbol || sym}: snapshot applied · refreshed ${impacted.join(", ") || "sections"}`
        + ` · cov ${aw.coverage}% · conf ${aw.confidence}`
        + (aw.research_quality ? ` · quality ${aw.research_quality.level}` : "");
    }
    await showLearnerResearch(aw.symbol || sym);
    await loadLearnerResearchList({ quiet: true });
  } catch (err) {
    if (status) {
      status.textContent = "Snapshot failed: " + (err && err.message ? err.message : String(err));
    }
  }
}

async function applyLearnerFilingRefs() {
  const status = $("#learner-research-status");
  const input = $("#learner-research-symbol");
  const sym = ((input && input.value) || "").trim();
  const title = (($("#snap-filing-title") || {}).value || "").trim();
  if (!sym) {
    if (status) status.textContent = "Enter a symbol before attaching a filing.";
    return;
  }
  if (!title) {
    if (status) status.textContent = "Enter a filing title (e.g. Annual Report FY25).";
    return;
  }
  const kind = (($("#snap-filing-kind") || {}).value) || "annual";
  const url = (($("#snap-filing-url") || {}).value || "").trim();
  if (status) status.textContent = `Attaching filing ref for ${sym}…`;
  try {
    const result = await api(`/v1/market/research/${encodeURIComponent(sym)}/filings`, {
      method: "POST",
      body: {
        filings: [{ title, kind, url }],
        auto_refresh: true,
        note: "Operator filing ref from Market UI",
      },
    });
    const aw = (result && result.awareness) || {};
    const levels = (result && result.evidence_levels) || [];
    if (status) {
      status.textContent = `${aw.symbol || sym}: filing attached · levels ${levels.join(",") || "?"}`
        + ` · management evidence updated`;
    }
    await showLearnerResearch(aw.symbol || sym);
    await loadLearnerResearchList({ quiet: true });
  } catch (err) {
    if (status) {
      status.textContent = "Filing attach failed: "
        + (err && err.message ? err.message : String(err));
    }
  }
}

async function raiseLearnerCriticalFlag() {
  const status = $("#learner-research-status");
  const input = $("#learner-research-symbol");
  const sym = ((input && input.value) || "").trim();
  const text = (($("#snap-critical-text") || {}).value || "").trim();
  if (!sym) {
    if (status) status.textContent = "Enter a symbol before raising a critical flag.";
    return;
  }
  if (!text) {
    if (status) status.textContent = "Describe the critical evidence.";
    return;
  }
  const kind = (($("#snap-critical-kind") || {}).value) || "thesis_invalidating";
  if (status) status.textContent = `Raising critical flag on ${sym}…`;
  try {
    const result = await api(`/v1/market/research/${encodeURIComponent(sym)}/critical-flag`, {
      method: "POST",
      body: { text, kind },
    });
    const aw = (result && result.awareness) || {};
    if (status) {
      status.textContent = `${aw.symbol || sym}: critical flag raised · stance `
        + ((aw.thesis && aw.thesis.stance) || "?");
    }
    await showLearnerResearch(aw.symbol || sym);
    await loadLearnerResearchList({ quiet: true });
  } catch (err) {
    if (status) {
      status.textContent = "Critical flag failed: "
        + (err && err.message ? err.message : String(err));
    }
  }
}

async function applyLearnerManagementPack() {
  const status = $("#learner-research-status");
  const input = $("#learner-research-symbol");
  const sym = ((input && input.value) || "").trim();
  if (!sym) {
    if (status) status.textContent = "Enter a symbol before applying management pack.";
    return;
  }
  const ids = [
    "capital_allocation",
    "dilution",
    "related_party",
    "governance_red_flags",
    "roic_trend",
    "promoter_skin",
  ];
  const answers = {};
  for (const id of ids) {
    const el = $(`#mgmt-${id}`);
    const v = ((el && el.value) || "").trim();
    if (v) answers[id] = v;
  }
  if (!Object.keys(answers).length) {
    if (status) status.textContent = "Fill at least one management checklist field.";
    return;
  }
  if (status) status.textContent = `Applying management pack for ${sym}…`;
  try {
    const result = await api(`/v1/market/research/${encodeURIComponent(sym)}/management`, {
      method: "POST",
      body: {
        answers,
        operator_note: (($("#mgmt-note") || {}).value) || "",
        evidence_level: "F",
        auto_refresh: true,
      },
    });
    const aw = (result && result.awareness) || {};
    if (status) {
      status.textContent = `${aw.symbol || sym}: management pack · ${result.answered || 0} answered`
        + ` · cov ${aw.coverage}% · conf ${aw.confidence}`
        + (aw.research_quality ? ` · quality ${aw.research_quality.level}` : "");
    }
    await showLearnerResearch(aw.symbol || sym);
    await loadLearnerResearchList({ quiet: true });
  } catch (err) {
    if (status) {
      status.textContent = "Management pack failed: "
        + (err && err.message ? err.message : String(err));
    }
  }
}

async function showLearnerResearch(symbol) {
  const box = $("#learner-research-detail") || $("#learner-research-body");
  const status = $("#learner-research-status");
  if (!box || !symbol) return;
  try {
    const data = await api(
      `/v1/market/research/${encodeURIComponent(symbol)}?full=true`,
    );
    const aw = (data && data.awareness) || {};
    const dossier = (data && data.dossier) || {};
    const thesis = aw.thesis || {};
    const val = aw.valuation || {};
    const brief = aw.brief || {};
    const sections = dossier.sections || {};
    const risks = (((sections.risks || {}).fields || {}).top_risks) || [];
    const biz = (sections.business || {}).fields || {};
    const gaps = [...(aw.top_gaps || []), ...(aw.known_unknowns || [])].filter(Boolean);
    const gapQs = (aw.gap_questions || aw.open_questions || []).map((q) =>
      (typeof q === "string" ? q : (q.text || q.answer_note || ""))
    ).filter(Boolean);

    box.innerHTML = "";
    const add = (label, text, { force = false } = {}) => {
      const body = (text == null || text === "") ? (force ? "(not available)" : "") : String(text);
      if (!body && !force) return;
      box.append(el("div", { class: "learner-research-block" },
        label ? el("div", { class: "learner-research-label", text: label }) : null,
        el("div", { class: "why", text: body }),
      ));
    };

    const stance = (thesis.stance || brief.stance || "unknown").replace(/_/g, " ");
    const mos = val.margin_of_safety_pct;
    const mosLine = mos != null
      ? `MoS ${mos}% (${val.mos_method || "est."})`
      : "MoS unknown — no buy size from valuation";
    const conf = aw.confidence || "?";
    const cov = aw.coverage != null ? `${aw.coverage}%` : "?";
    const rq = (aw.research_quality && aw.research_quality.level) || "?";
    const verdictClass = (stance.includes("buy") && mos != null)
      ? "ok"
      : (conf === "very_low" || mos == null ? "warn" : "");
    box.append(el("div", {
      class: `learner-research-verdict${verdictClass ? ` ${verdictClass}` : ""}`,
      text: `${aw.symbol || symbol}: ${stance.toUpperCase()} · conf ${conf} · cov ${cov} · quality ${rq} · ${mosLine}`,
    }));

    add("MVR", (aw.mvr_satisfied ? "Satisfied — enough to continue researching (not enough to invest)." : "Incomplete")
      + (aw.mvr && (aw.mvr.missing || []).length ? ` Missing: ${aw.mvr.missing.join(", ")}` : ""),
      { force: true });
    add("Research quality", [
      String(rq).toUpperCase(),
      (aw.research_quality && aw.research_quality.meaning) || null,
      "Coverage ≠ confidence ≠ quality ≠ evidence sufficiency.",
    ].filter(Boolean).join("\n"), { force: true });
    const suf = aw.evidence_sufficiency || {};
    if (suf.cash_flow || suf.valuation) {
      add("Evidence sufficiency", [
        `Cash flow: ${suf.cash_flow || "—"}`,
        `Management: ${suf.management || "—"}`,
        `Valuation: ${suf.valuation || "—"}`,
        `Decision: ${suf.decision || "—"}`,
      ].join("\n"));
    }
    const cf = aw.critical_flags || {};
    if (cf.count) {
      add("Critical flags", [
        cf.note || "Critical evidence outweighs checklists.",
        ...((cf.active || []).slice(0, 4).map((f) =>
          `• [${f.kind}] ${f.text || ""}`
        )),
      ].join("\n"), { force: true });
    }
    const nextWork = aw.next_work || [];
    if (nextWork.length) {
      add("Next research work", nextWork.slice(0, 6).map((w) =>
        `• (${w.kind}) ${w.text || w.id || ""}${w.reason ? ` — ${w.reason}` : ""}`
      ).join("\n"));
    }
    add("Honesty", brief.honesty
      || "Hermetic / hint-based MVR — not live NSE filings. Coverage ≠ confidence.",
      { force: true });
    add("Business",
      [biz.name, biz.sector, biz.summary].filter(Boolean).join(" · ") || brief.business || "(no business sketch)",
      { force: true });
    add(`Thesis (${stance})`, thesis.summary || brief.thesis || "(none yet)", { force: true });
    if (thesis.base) add("Base case", thesis.base);
    if (thesis.falsifiers && thesis.falsifiers.length) {
      add("Falsifiers", thesis.falsifiers.slice(0, 5).join(" · "));
    }
    const drivers = aw.thesis_drivers || thesis.drivers || {};
    if ((drivers.positive || []).length || (drivers.concerns || []).length) {
      add("Thesis drivers", [
        (drivers.positive || []).length ? `Positive\n• ${drivers.positive.slice(0, 6).join("\n• ")}` : null,
        (drivers.concerns || []).length ? `Concerns\n• ${drivers.concerns.slice(0, 6).join("\n• ")}` : null,
        (drivers.unknowns || []).length ? `Unknown\n• ${drivers.unknowns.slice(0, 6).join("\n• ")}` : null,
        (drivers.primary_kpis || []).length
          ? `Sector KPIs\n• ${drivers.primary_kpis.slice(0, 6).join("\n• ")}`
          : null,
      ].filter(Boolean).join("\n\n"), { force: true });
    }
    const dist = aw.thesis_distinctiveness || thesis.distinctiveness || {};
    if (dist.score_pct != null) {
      add("Thesis distinctiveness", [
        `${dist.score_pct}%`
          + (dist.identifiable_without_name ? " — identifiable without company name" : " — still too generic"),
        dist.pack_id ? `Pack: ${dist.pack_id}` : null,
        (dist.hits || []).length ? `Hits: ${(dist.hits || []).slice(0, 6).join(", ")}` : null,
        dist.note || null,
      ].filter(Boolean).join("\n"), { force: true });
    }
    if (aw.pack || aw.sector_pack) {
      add("Sector pack", [
        aw.pack || (aw.sector_pack && aw.sector_pack.id) || "?",
        aw.sector_pack && aw.sector_pack.label ? aw.sector_pack.label : null,
      ].filter(Boolean).join(" · "));
    }
    const priors = aw.outcome_priors || {};
    if (priors.last_result) {
      add("Outcome priors", [
        `Last: ${priors.last_result}${priors.last_note ? ` — ${priors.last_note}` : ""}`,
        priors.ranking_penalty ? `Ranking penalty: ${priors.ranking_penalty}` : null,
        priors.ranking_bonus ? `Ranking bonus: ${priors.ranking_bonus}` : null,
      ].filter(Boolean).join("\n"));
    }
    const mgmtPack = aw.management_pack || ((sections.management || {}).fields || {}).pack || {};
    const mgmtItems = (mgmtPack.items || []).filter((i) => i && i.answer);
    if (mgmtItems.length) {
      add("Management pack", mgmtItems.slice(0, 8).map((i) =>
        `• ${i.label || i.id}: ${i.answer} [${i.status || "?"}]`
      ).join("\n"));
    }
    const miss = aw.missing_inputs || {};
    const fmtMiss = (arr) => (arr || []).map((m) => m.label || m.id).filter(Boolean);
    const crit = fmtMiss(miss.critical);
    const imp = fmtMiss(miss.important);
    const opt = fmtMiss(miss.optional);
    const missingIn = (val.missing_inputs || []).filter((m) => m && !m.present);
    add("Valuation", [
      `Method: ${val.method_label || val.method || "insufficient"}`,
      val.method_confidence ? `Method confidence: ${val.method_confidence}` : null,
      mosLine,
      val.pe != null ? `PE ${val.pe}` : "PE unknown",
      val.fair_pe != null ? `fair PE ≈ ${val.fair_pe}` : null,
      val.fcf != null ? `FCF seed ${val.fcf}` : "FCF unknown",
      (val.gaps || []).length ? `Gaps: ${(val.gaps || []).slice(0, 3).join("; ")}` : null,
      crit.length ? `Critical missing:\n• ${crit.join("\n• ")}` : null,
      imp.length ? `Important missing:\n• ${imp.join("\n• ")}` : null,
      opt.length ? `Optional missing:\n• ${opt.join("\n• ")}` : null,
      (!crit.length && !imp.length && missingIn.length)
        ? ("Missing:\n• " + missingIn.slice(0, 6).map((m) => m.label || m.id).join("\n• "))
        : null,
    ].filter(Boolean).join("\n"), { force: true });
    add("Risks",
      risks.length ? risks.slice(0, 6).join("\n• ").replace(/^/, "• ") : "(none listed)",
      { force: true });

    const qc = aw.questions_classified || {};
    const fmtQ = (arr) => (arr || []).slice(0, 6).map((q) =>
      (typeof q === "string" ? q : (q.text || q.answer_note || q.id || ""))
    ).filter(Boolean);
    const ans = fmtQ(qc.answered);
    const opn = fmtQ(qc.open);
    const blk = fmtQ(qc.blocked);
    const def = fmtQ(qc.deferred);
    if (ans.length || opn.length || blk.length || def.length) {
      add("Research questions", [
        ans.length ? `Answered ✓\n• ${ans.join("\n• ")}` : null,
        opn.length ? `Open\n• ${opn.join("\n• ")}` : null,
        blk.length ? `Blocked\n• ${blk.join("\n• ")}` : null,
        def.length ? `Deferred\n• ${def.join("\n• ")}` : null,
      ].filter(Boolean).join("\n\n"), { force: true });
    } else {
      add("Open / gap questions",
        gapQs.length ? gapQs.slice(0, 8).join("\n• ").replace(/^/, "• ") : "(none)",
        { force: true });
    }
    if (gaps.length) {
      add("Known unknowns", [...new Set(gaps)].slice(0, 10).join("\n• ").replace(/^/, "• "));
    }
    const bySec = aw.coverage_by_section || {};
    const secDepth = Object.keys(bySec).sort().map((k) => `${k} ${bySec[k]}%`);
    if (secDepth.length) {
      add("Coverage by section (depth)", secDepth.join(" · "));
    }
    if (aw.coverage_by_evidence != null || aw.coverage_by_reasoning != null) {
      add("Coverage layers", [
        `Evidence ${aw.coverage_by_evidence != null ? aw.coverage_by_evidence + "%" : "—"}`,
        `Reasoning ${aw.coverage_by_reasoning != null ? aw.coverage_by_reasoning + "%" : "—"}`,
        "High reasoning + low evidence = template risk.",
      ].join(" · "));
    }
    const secEv = aw.section_evidence || {};
    const evBits = Object.keys(secEv).filter((k) => (secEv[k].levels || []).length).map((k) =>
      `${k}=${(secEv[k].levels || []).join("+")}/${secEv[k].confidence || "?"}`
    );
    if (evBits.length) {
      add("Evidence levels (A–G)", evBits.slice(0, 10).join(" · "));
    }
    if ((brief.watch_items || []).length) {
      add("Watch next", brief.watch_items.slice(0, 8).join(" · "));
    }

    const timing = aw.timing || dossier.timing || {};
    if (timing && (timing.status || timing.label)) {
      const sig = timing.signals || {};
      add("Timing (not thesis)", [
        `Status: ${timing.status || "—"}`,
        timing.bias ? `Bias: ${timing.bias}` : null,
        sig.rsi != null ? `RSI ${Number(sig.rsi).toFixed(1)}` : null,
        (timing.notes || []).slice(0, 3).join("; ") || null,
        timing.honesty || "Technicals never replace MoS / thesis.",
      ].filter(Boolean).join("\n"));
    }
    const fund = aw.fundamentals_status || dossier.fundamentals_status || {};
    if (fund && (fund.used || (fund.tried || []).length)) {
      const tried = (fund.tried || []).map((t) => {
        if (!t) return null;
        return t.ok ? `${t.provider} ok` : `${t.provider} gap${t.gap ? ` (${t.gap})` : ""}`;
      }).filter(Boolean);
      add("Fundamentals providers",
        (fund.used ? `Used: ${fund.used}` : "No live profile — hermetic/hint only")
        + (tried.length ? `\nTried: ${tried.join(", ")}` : ""));
    }

    const mkg = aw.mkg || {};
    if (mkg.summary || (mkg.why_own && mkg.why_own.summary)) {
      const why = mkg.why_own || {};
      const themeN = (why.themes || []).length;
      const polN = (why.policies || []).length;
      add("MKG — Why own / watch",
        (mkg.summary || why.summary || "")
        + `\nThemes ${themeN} · policies ${polN} · status ${mkg.status || why.status || "?"}`);
      const hood = mkg.neighborhood || {};
      const nNodes = (hood.nodes || []).length;
      const nEdges = (hood.edges || []).length;
      if (nNodes || nEdges) {
        add("MKG neighborhood", `${nNodes} nodes · ${nEdges} edges (1-hop)`);
      }
    }

    const iscore = aw.investment_score || {};
    if (iscore.overall != null || iscore.research_confidence) {
      add("Investment score (IIP.6)",
        `Overall ${iscore.overall ?? "?"} (${iscore.score_band || "?"}) · `
        + `research conf ${iscore.research_confidence || "?"} · `
        + `investment conf ${iscore.investment_confidence || "?"} → ${iscore.path || "?"}`
        + (iscore.path_reason ? `\n${iscore.path_reason}` : "")
        + (iscore.priors_applied ? "\nPriors applied (IIP.8 weight shift)." : "")
        + "\nOverall ≠ buy. High research + low investment → watch.");
    }
    const ttrack = aw.thesis_tracker;
    if (ttrack && ttrack.status) {
      const assump = (ttrack.assumptions || []).slice(0, 4)
        .map((a) => `${a.kind || "?"}:${a.status || "?"}`).join(", ");
      add("Thesis Tracker (IIP.8)",
        `${ttrack.status} · ${ttrack.decision || "?"} — ${(ttrack.hypothesis || "").slice(0, 160)}`
        + (assump ? `\nAssumptions: ${assump}` : "")
        + ((ttrack.lessons || []).length
          ? `\nLessons: ${(ttrack.lessons || []).slice(0, 2).join(" · ")}` : ""));
    }
    const tpri = aw.thesis_priors || {};
    if (tpri.closed_outcomes != null) {
      add("Thesis priors",
        `Closed ${tpri.closed_outcomes} · weight shift ${tpri.ready_for_weight_shift ? "ready" : "locked (<20)"}`);
    }
    const links = aw.chart_links || {};
    if (links.tradingview) {
      add("Chart links (IIP.9)",
        `TradingView: ${links.tradingview}\nYahoo: ${links.yahoo}\n`
        + (links.note || "Non-primary — local OHLCV for technicals."));
    }
    add("Portfolio gate (IIP.7)",
      "Buys also need portfolio pre-trade: cash buffer, max names, name/sector concentration, "
      + "persona assets, investment-confidence floor — beside research gate.");

    add("Trail", `Memories ${aw.memories_count || 0} · Outcomes ${aw.outcomes_count || 0}`
      + (aw.pack ? ` · pack=${aw.pack}` : "")
      + ` · phase=${aw.phase || "—"}`);

    const secNames = Object.keys(sections);
    if (secNames.length) {
      box.append(el("div", {
        class: "muted small",
        style: "margin-top:10px",
        text: "Sections: " + secNames.map((n) => {
          const s = sections[n] || {};
          const g = (s.gaps || []).length ? `/${(s.gaps || []).length} gaps` : "";
          return `${n}=${s.status}/${s.confidence}${g}`;
        }).join(", "),
      }));
    }
    if (status) {
      status.textContent = `${aw.symbol || symbol}: detail loaded · conf ${aw.confidence}`
        + ` · cov ${aw.coverage}% · quality ${(aw.research_quality && aw.research_quality.level) || "?"}`;
    }
  } catch (err) {
    if (status) {
      status.textContent = "Could not load research: "
        + (err && err.message ? err.message : String(err));
    }
  }
}

function renderLearnerChecklist(box, status) {
  box.innerHTML = "";
  const hp = status && status.happy_path;
  const checks = (hp && (hp.checklist || hp.runtime_checklist || hp.items)) || [];
  if (checks.length) {
    for (const c of checks) {
      const done = !!(c.done || c.ok || c.status === "done" || c.status === "ok");
      const text = c.detail || c.text || c.label || c.id || JSON.stringify(c);
      box.append(el("div", { class: "learner-check" },
        el("span", { class: "mark " + (done ? "done" : "todo"), text: done ? "✓" : "○" }),
        el("span", { text }),
      ));
    }
  } else if (status && (status.bullets || []).length) {
    const ul = el("ul", { class: "learner-bullets" });
    for (const b of status.bullets) ul.append(el("li", { text: b }));
    box.append(ul);
  } else {
    box.append(el("div", {
      class: "learner-empty",
      text: "No learner status yet — create a goal or ask chat: learner status.",
    }));
  }
  if (status && status.narrative) {
    box.append(el("div", {
      class: "muted small",
      style: "margin-top:12px",
      text: status.narrative,
    }));
  }
  if (hp && (hp.next_actions || []).length) {
    box.append(el("div", {
      class: "muted small",
      style: "margin-top:10px;font-weight:600",
      text: "Next",
    }));
    for (const a of hp.next_actions.slice(0, 5)) {
      const text = typeof a === "string" ? a : (a.text || a.action || JSON.stringify(a));
      box.append(el("div", { class: "small", style: "padding:3px 0", text: "→ " + text }));
    }
  }
}

function renderLearnerBook(box, { status, portfolios, missions, plan }) {
  box.innerHTML = "";
  const books = (portfolios && (portfolios.portfolios || portfolios.items || portfolios)) || [];
  const list = Array.isArray(books) ? books : [];
  if (list.length) {
    box.append(el("div", { class: "muted small", style: "margin-bottom:6px", text: "Virtual portfolios" }));
    for (const p of list.slice(0, 8)) {
      const key = p.portfolio_key || p.name || p.id || "?";
      const cap = p.persona && p.persona.capital != null ? p.persona.capital : p.capital;
      const ac = p.asset_class || (p.persona && (p.persona.allowed_assets || [])[0]) || "";
      box.append(el("div", { class: "learner-row" },
        el("div", { class: "rank", text: "₹" }),
        el("div", {},
          el("div", { class: "sym", text: key }),
          el("div", { class: "why", text: [ac, p.label].filter(Boolean).join(" · ") }),
        ),
        el("div", {
          class: "notional",
          text: cap != null ? Number(cap).toLocaleString("en-IN") : "",
        }),
      ));
    }
  } else {
    box.append(el("div", {
      class: "learner-empty",
      text: "No virtual portfolio registry entries yet (India learner creates india_equity_learner).",
    }));
  }

  const ms = (missions && missions.missions) || [];
  const market = ms.filter((m) => {
    const t = (m.title || "").toLowerCase();
    const tpl = (m.template || m.mission_type || "").toLowerCase();
    return t.includes("market") || t.includes("investment") || t.includes("decision")
      || t.includes("portfolio") || t.includes("company") || t.includes("news")
      || ["investment_universe", "decision_simulation", "paper_trading", "market_observer",
          "company_intelligence", "news_intelligence", "portfolio_ledger", "investment_mentor",
          "event_research"].includes(tpl);
  });
  if (market.length) {
    box.append(el("div", {
      class: "muted small",
      style: "margin-top:14px;margin-bottom:6px",
      text: "Market missions — click to open journal",
    }));
    for (const m of market.slice(0, 12)) {
      const a = el("a", {
        href: "#",
        class: "link",
        style: "display:block;padding:4px 0;font-size:13px",
        onclick: (e) => {
          e.preventDefault();
          switchView("missions");
          showMissionDetail(m.id);
        },
      }, `${m.title || m.id} · ${m.status}`);
      box.append(a);
    }
  }

  const pkey = (plan && plan.portfolio_key) || "india_equity_learner";
  box.append(el("div", {
    class: "muted small",
    style: "margin-top:14px",
    text: `Tip: Decision Simulation is a separate mission from Investment Universe. Open it above, or chat “learner status”. Book key: ${pkey}.`,
  }));
}

let missionTemplates = [];

async function loadMissions() {
  try {
    const [ms, tpls] = await Promise.all([
      api("/v1/missions?limit=100"),
      api("/v1/templates"),
    ]);
    missionTemplates = tpls.templates || [];
    renderTemplateSelect();
    renderMissionsList(ms.missions || []);
    if (state.missionId) showMissionDetail(state.missionId);
  } catch (err) { toast(err.message); }
}

function renderTemplateSelect() {
  const sel = $("#mission-template");
  if (!sel) return;
  const prev = sel.value;
  sel.innerHTML = "";
  for (const t of missionTemplates) {
    sel.append(el("option", { value: t.name },
      `${t.name} (v${t.template_version})`));
  }
  if (prev && [...sel.options].some((o) => o.value === prev)) sel.value = prev;
  seedMissionConfigFromTemplate();
}

function seedMissionConfigFromTemplate() {
  const ta = $("#mission-config");
  const sel = $("#mission-template");
  if (!ta || !sel) return;
  const t = missionTemplates.find((x) => x.name === sel.value);
  const doc = t && t.default_config ? t.default_config : {};
  // Don't clobber in-progress edits unless empty / still matching a prior seed.
  if (!ta.dataset.touched || ta.value.trim() === "" || ta.dataset.seeded === "1") {
    ta.value = JSON.stringify(doc, null, 2);
    ta.dataset.seeded = "1";
    ta.dataset.touched = "";
  }
}

function parseMissionConfigOverrides() {
  const raw = ($("#mission-config")?.value || "").trim();
  if (!raw) return {};
  try { return JSON.parse(raw); }
  catch (_) { throw new Error("Config overrides must be valid JSON"); }
}

async function registerSampleMarketData() {
  const name = ($("#mission-feed-name")?.value || "").trim() || "demo-feed";
  const symbol = ($("#mission-feed-symbol")?.value || "").trim() || "DEMO";
  try {
    const info = await api("/v1/assets", {
      method: "POST",
      body: { kind: "market_data", name, symbol, generate_sample: true },
    });
    toast(`Registered feed ${info.name} (${info.symbol})`);
    // Merge into the config textarea if paper_trading-shaped.
    try {
      const cfg = parseMissionConfigOverrides();
      cfg.instruments = [{ symbol: info.symbol, asset: info.name }];
      const ta = $("#mission-config");
      if (ta) { ta.value = JSON.stringify(cfg, null, 2); ta.dataset.touched = "1"; }
      if ($("#mission-feed-name")) $("#mission-feed-name").value = info.name;
      if ($("#mission-feed-symbol")) $("#mission-feed-symbol").value = info.symbol;
    } catch (_) { /* ignore merge failures */ }
  } catch (err) { toast(err.message); }
}

async function instantiateMission(template, title) {
  try {
    const config_overrides = parseMissionConfigOverrides();
    const view = await api("/v1/missions/instantiate", {
      method: "POST",
      body: { template, title: title || null, config_overrides },
    });
    $("#mission-title").value = "";
    await loadMissions();
    showMissionDetail(view.mission.id);
    toast("Mission instantiated");
  } catch (err) { toast(err.message); }
}

function missionActive(m) {
  return ["active", "waiting"].includes(m.status);
}

function renderMissionsList(missions) {
  const list = $("#missions-list");
  list.innerHTML = "";
  if (!missions.length) {
    list.append(el("div", { class: "muted", style: "padding:18px", text: "No missions yet — instantiate one above." }));
    return;
  }
  for (const m of missions) {
    list.append(el("div", {
      class: "job-row" + (m.id === state.missionId ? " active" : ""),
      onclick: () => showMissionDetail(m.id),
    },
      el("div", { class: "obj", text: m.title }),
      el("div", {},
        el("span", { class: "badge " + m.status, text: m.status }),
        el("span", { class: "muted small", text: `  P${m.effective_priority} · ${m.scheduling_policy}` }),
      ),
    ));
  }
}

function missionDetailEditing() {
  const box = $("#mission-detail");
  if (!box) return false;
  const ae = document.activeElement;
  return !!(ae && box.contains(ae) && (ae.tagName === "TEXTAREA" || ae.tagName === "INPUT"));
}

function captureMissionUiState() {
  const drafts = {};
  const open = [];
  document.querySelectorAll("#mission-detail details[data-worker-id]").forEach((det) => {
    const wid = det.getAttribute("data-worker-id");
    if (det.open) open.push(wid);
    const ta = det.querySelector("textarea");
    if (ta && ta.value) drafts[wid] = ta.value;
  });
  return { drafts, open };
}

function restoreMissionUiState(ui) {
  if (!ui) return;
  document.querySelectorAll("#mission-detail details[data-worker-id]").forEach((det) => {
    const wid = det.getAttribute("data-worker-id");
    if ((ui.open || []).includes(wid)) det.open = true;
    const ta = det.querySelector("textarea");
    if (ta && ui.drafts && ui.drafts[wid] != null) ta.value = ui.drafts[wid];
  });
}

async function showMissionDetail(id, { preserve = false } = {}) {
  state.missionId = id;
  document.querySelectorAll("#missions-list .job-row").forEach((r) => r.classList.remove("active"));
  // Poll refresh must not collapse the worker card / wipe mid-typed input.
  if (preserve && missionDetailEditing()) return;
  const ui = preserve ? captureMissionUiState() : null;
  try {
    const d = await api(`/v1/missions/${id}`);
    renderMissionDetail(d);
    if (preserve) restoreMissionUiState(ui);
    if (missionActive(d.mission)) startMissionPoll(id); else stopMissionPoll();
  } catch (err) { toast(err.message); }
}

const MISSION_ACTIONS = {
  draft: ["activate", "archive"],
  active: ["pause", "complete", "archive"],
  waiting: ["resume", "pause", "archive"],
  paused: ["resume", "complete", "archive"],
  completed: ["archive"],
  archived: [],
};

async function missionAction(id, action) {
  try {
    await api(`/v1/missions/${id}/${action}`, { method: "POST", body: { reason: "operator " + action } });
    await loadMissions();
    showMissionDetail(id);
  } catch (err) { toast(err.message); }
}

async function workerAction(workerId, action) {
  try {
    await api(`/v1/workers/${workerId}/${action}`, { method: "POST", body: { reason: "operator " + action } });
    showMissionDetail(state.missionId);
  } catch (err) { toast(err.message); }
}

function renderMissionDetail(d) {
  const box = $("#mission-detail");
  box.innerHTML = "";
  const m = d.mission;
  box.append(el("div", { class: "obj-title", text: m.title }));
  box.append(el("div", {},
    el("span", { class: "badge " + m.status, text: m.status }),
    el("span", { class: "muted small", text:
      `  priority ${d.effective_priority} · ${m.scheduling_policy} · ${m.criticality}`
      + (m.max_concurrent_tasks != null ? ` · cap ${m.max_concurrent_tasks}` : "") }),
  ));
  if (m.objective) box.append(el("div", { class: "muted", style: "margin:6px 0", text: m.objective }));

  // Cognitive lifecycle (philosophy) — MI.1
  const phil = (m.success_criteria && m.success_criteria.philosophy) || null;
  if (phil && phil.lifecycle) {
    const order = ["observe","learn","assess_resources","decide","record_why","evaluate","reflect","improve"];
    const board = order.map((stage) => ({
      stage,
      label: stage.replace(/_/g, " "),
      status: phil.lifecycle[stage] || "n/a",
    }));
    box.append(renderLifecycleBoard(board, "Cognitive lifecycle"));
    box.append(el("div", { class: "muted small", style: "margin-bottom:8px",
      text: `Kind: ${phil.mission_kind || "?"} · never_stops=${phil.never_stops ? "yes" : "no"}` }));
  }

  const actions = el("div", { class: "job-actions" });
  for (const a of (MISSION_ACTIONS[m.status] || [])) {
    actions.append(el("button", { onclick: () => missionAction(m.id, a) }, a));
  }
  actions.append(el("button", { onclick: () => showMissionDetail(m.id) }, "Refresh"));
  box.append(actions);

  // Active config editor (versioned; PUT creates next version)
  const cfg = d.config || {};
  const cfgDoc = cfg.document || {};
  box.append(el("h3", { class: "section-h", text:
    cfg.version != null ? `Config (v${cfg.version} · ${cfg.schema_type || "?"})` : "Config" }));
  const cfgEdit = el("div", { class: "mission-config-edit" });
  const cfgTa = el("textarea", { rows: "8", spellcheck: "false" });
  cfgTa.value = JSON.stringify(cfgDoc, null, 2);
  const cfgSave = el("button", {
    class: "mission-config-save",
    onclick: async () => {
      let document;
      try { document = cfgTa.value.trim() ? JSON.parse(cfgTa.value) : {}; }
      catch (_) { toast("Config must be valid JSON"); return; }
      cfgSave.disabled = true;
      try {
        await api(`/v1/missions/${m.id}/config`, {
          method: "PUT",
          body: { document, change_note: "operator UI edit", activate: true },
        });
        toast("Config saved (new version)");
        showMissionDetail(m.id);
      } catch (err) { toast(err.message); }
      finally { cfgSave.disabled = false; }
    },
  }, "Save config");
  cfgEdit.append(cfgTa, cfgSave);
  if (!cfg.version) {
    cfgEdit.append(el("div", { class: "muted small", text: "No active config on this mission." }));
  }
  box.append(cfgEdit);

  // Workers
  box.append(el("h3", { class: "section-h", text: `Workers (${(d.workers || []).length})` }));
  const workers = el("div", { class: "steps" });
  if (!(d.workers || []).length) workers.append(el("div", { class: "muted small", text: "No workers." }));
  for (const w of (d.workers || [])) workers.append(renderWorkerCard(w));
  box.append(workers);

  // Journal ("Explain this" foundation, P9)
  box.append(el("h3", { class: "section-h", text: `Journal (${(d.journal || []).length})` }));
  const feed = el("div", { class: "feed" });
  for (const j of (d.journal || [])) {
    feed.append(el("div", { class: "feed-row" },
      el("span", { class: "feed-time muted small", text: clockTime(j.ts) }),
      el("span", { class: "feed-phase phase-step", text: j.action }),
      el("span", { class: "feed-msg", text: j.reason || "" }),
    ));
  }
  box.append(feed);
}

function renderWorkerCard(w) {
  const card = el("details", { class: "step", "data-worker-id": w.id });
  const progLabel = workerProgressLabel(w);
  card.append(el("summary", {},
    el("span", { class: "intent", text: w.type }),
    el("span", { class: "badge " + w.status, text: w.status }),
    el("span", { class: "cap muted small", text: `health ${w.health} · v${w.worker_version}`
      + (w.restart_count ? ` · ${w.restart_count} restart(s)` : "")
      + (progLabel ? ` · ${progLabel}` : "") }),
  ));
  const body = el("div", { class: "step-body" });
  body.append(el("div", { class: "muted small", text: `id ${w.id}` }));

  const roots = ((w.checkpoint || {}).roots) || [];
  if (roots.length) {
    for (const r of roots) body.append(renderArchiveRootProgress(r));
  } else if (w.checkpoint && w.checkpoint.progress) {
    body.append(el("div", { class: "muted small", text: "progress " + JSON.stringify(w.checkpoint.progress) }));
  }

  const wactions = el("div", { class: "job-actions" });
  if (["running", "recovering"].includes(w.status)) wactions.append(el("button", { onclick: () => workerAction(w.id, "pause") }, "Pause"));
  if (["paused"].includes(w.status)) wactions.append(el("button", { onclick: () => workerAction(w.id, "resume") }, "Resume"));
  if (!["stopped"].includes(w.status)) wactions.append(el("button", { onclick: () => workerAction(w.id, "stop") }, "Stop"));
  body.append(wactions);

  // Live operator input (Q4) — JSON object drained at the top of the next tick.
  const inp = el("div", { class: "job-input" });
  const hint = w.type === "paper_trading"
    ? '{"block_symbol": "AAA"} or {"unblock_symbol": "AAA"}'
    : '{"note": "operator guidance"}';
  const ta = el("textarea", { rows: "2", placeholder: "Live input as JSON, e.g. " + hint });
  const send = el("button", {
    onclick: async () => {
      let payload;
      try { payload = ta.value.trim() ? JSON.parse(ta.value) : {}; }
      catch (_) { toast("Input must be valid JSON"); return; }
      send.disabled = true;
      try {
        await api(`/v1/workers/${w.id}/input`, { method: "POST", body: { payload } });
        ta.value = ""; toast("Input queued for worker");
      } catch (err) { toast(err.message); } finally { send.disabled = false; }
    },
  }, "Send input");
  inp.append(ta, send);
  body.append(inp);
  card.append(body);
  return card;
}

function workerProgressLabel(w) {
  const roots = ((w.checkpoint || {}).roots) || [];
  if (!roots.length) return "";
  let done = 0, total = 0, complete = 0;
  for (const r of roots) {
    if (r.complete) complete += 1;
    if (typeof r.done === "number") done += r.done;
    if (typeof r.total === "number") total += r.total;
  }
  if (total > 0) return `${done}/${total} files`;
  if (complete) return `${complete}/${roots.length} roots done`;
  return `${roots.length} root(s)`;
}

function renderArchiveRootProgress(r) {
  const wrap = el("div", { class: "archive-root" });
  const done = typeof r.done === "number" ? r.done : 0;
  const total = typeof r.total === "number" ? r.total : 0;
  const scanning = !!r.scanning;
  const pct = total > 0 ? Math.min(100, Math.round((done / total) * 100)) : (r.complete ? 100 : 0);
  wrap.append(el("div", { class: "archive-root-name", text:
    (r.name || r.path || "root") + (r.kind ? ` · ${r.kind}` : "")
    + (r.complete ? " · complete" : (scanning ? " · scanning" : "")) }));
  const bar = el("div", { class: "archive-bar" });
  bar.append(el("span", { style: `width:${pct}%` }));
  wrap.append(bar);
  let meta = "";
  if (scanning) {
    meta = `scanning… walked ${(r.walked || 0).toLocaleString()} · matched ${total.toLocaleString()}`;
  } else if (total > 0) {
    meta = `${done} / ${total} (${pct}%)`;
    if (r.pending != null) meta += ` · ${r.pending} pending`;
  } else {
    meta = r.complete ? "complete" : "waiting…";
  }
  if (r.last_file) meta += ` · last ${r.last_file}`;
  if (r.path) meta += ` · ${r.path}`;
  wrap.append(el("div", { class: "archive-meta muted small", text: meta }));
  return wrap;
}

/* ---------- archive (Owner Knowledge ingest) ---------- */
let archiveCache = null;

async function loadArchive() {
  try {
    const d = await api("/v1/archive/status?limit=50");
    archiveCache = d;
    renderArchive(d);
    startArchivePoll();
  } catch (err) {
    toast(err.message);
    const box = $("#archive-list");
    if (box) box.innerHTML = "";
    setArchiveStatus("Could not load archive workers: " + err.message, "fail");
  }
}

function renderArchive(d) {
  const box = $("#archive-list");
  if (!box) return;
  box.innerHTML = "";
  const workers = d.workers || [];
  if (!workers.length) {
    box.append(el("div", { class: "muted", text:
      "No archive workers yet. Start one above (parallel = separate progress bar)." }));
    return;
  }
  for (const w of workers) box.append(renderArchiveWorkerCard(w));
  if (d.host_guard) {
    const hg = d.host_guard;
    box.append(el("div", { class: "muted small", style: "margin-top:8px", text:
      `Host guard: tick slots ${((hg.arbiter || {}).total_inflight) ?? "—"}/${hg.max_concurrent_ticks}`
      + ` · archive ${hg.archive_workers_running}/${hg.max_archive_workers}`
      + ` · queued ${hg.capacity_queued_workers || 0}`
      + (hg.last_defer_reason ? ` · last defer: ${hg.last_defer_reason}` : "")
      + " — slow but reliable; jobs wait for capacity." }));
  }
  if (d.note) {
    box.append(el("div", { class: "muted small", style: "margin-top:8px", text: d.note }));
  }
}

function archiveIngestComplete(w) {
  if (w && w.archive_ingest_complete) return true;
  const roots = ((w && w.checkpoint) || {}).roots || [];
  return roots.length > 0 && roots.every((r) => r.complete);
}

function archiveFmtWhen(iso) {
  if (!iso) return "";
  try {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return String(iso);
    return d.toLocaleString(undefined, { dateStyle: "short", timeStyle: "short" });
  } catch (_) {
    return String(iso);
  }
}

function archivePhaseLine(w) {
  const cp = (w && w.checkpoint) || {};
  const phase = cp.phase;
  const detail = (cp.phase_detail || "").trim();
  if (!phase && !detail) return "";
  const label = ({
    starting: "Starting",
    scanning: "Scanning",
    ingesting: "Ingesting",
    learning_code: "Learning code tree",
    reextract: "Re-extract",
    tick_complete: "Tick finished",
  })[phase] || (phase || "Working");
  return detail ? `${label}: ${detail}` : label;
}

function renderArchiveJobStatus(w) {
  const box = el("div", { class: "archive-job-status muted small" });
  const cfg = (w && w.configured_roots) || [];
  if (cfg.length) {
    box.append(el("div", { text:
      "Target: " + cfg.map((r) => `${r.name || r.path} (${r.kind || "document"})`).join(" · ")
    }));
  }
  const phase = archivePhaseLine(w);
  if (phase) {
    box.append(el("div", { text: phase }));
  } else if (w && w.queued_for_capacity) {
    box.append(el("div", { text:
      "Queued for host capacity" + (w.queue_reason ? ` — ${w.queue_reason}` : "")
    }));
  } else if (!(w && w.last_tick_at)) {
    box.append(el("div", { text:
      "Waiting for Host Guard to admit the first tick (archive slot / concurrent ticks)."
    }));
  } else {
    box.append(el("div", { text:
      "First tick in progress — large folders (tens of GB) can scan for a long time before root % appears."
    }));
  }
  const timing = [];
  if (w && w.last_tick_at) timing.push(`Last tick ${archiveFmtWhen(w.last_tick_at)}`);
  if (w && w.next_run_at) timing.push(`Next schedule ${archiveFmtWhen(w.next_run_at)}`);
  if (timing.length) box.append(el("div", { text: timing.join(" · ") }));
  const prog = ((w && w.checkpoint) || {}).progress || {};
  if (prog.files_seen || prog.files_pending || prog.files_done_tick) {
    box.append(el("div", { text:
      `Seen ${prog.files_seen || 0} · pending ${prog.files_pending || 0} · done this tick ${prog.files_done_tick || 0}`
    }));
  }
  return box;
}

function renderArchiveWorkerCard(w) {
  const card = el("div", { class: "archive-card", "data-worker-id": w.id });
  const head = el("div", { class: "archive-card-head" });
  const done = archiveIngestComplete(w);
  const displayStatus = done && w.status === "running"
    ? "ingest complete"
    : (done && w.status === "stopped" ? "complete" : (w.status || "?"));
  const badgeClass = done
    ? (w.status === "stopped" || w.status === "paused" ? "ok" : "ok")
    : (w.status || "");
  head.append(el("span", { class: "intent", text: w.type || "owner_knowledge" }));
  head.append(el("span", { class: "badge " + badgeClass, text: displayStatus }));
  const label = workerProgressLabel(w);
  const watchHint = done && w.status === "running"
    ? " · watching (Stop to free archive slot)"
    : "";
  head.append(el("span", { class: "muted small", text:
    `health ${w.health || "?"}` + (label ? ` · ${label}` : "") + watchHint
    + ` · ${String(w.id || "").slice(0, 8)}` }));
  card.append(head);

  const roots = ((w.checkpoint || {}).roots) || [];
  if (roots.length) {
    for (const r of roots) card.append(renderArchiveRootProgress(r));
  } else {
    card.append(renderArchiveJobStatus(w));
  }
  const phaseLine = archivePhaseLine(w);
  if (phaseLine && roots.length) {
    card.append(el("div", { class: "muted small archive-phase", text: phaseLine }));
  }

  const totals = ((w.checkpoint || {}).last_totals) || {};
  const learnedBits = [];
  if (totals.findings) learnedBits.push(`+${totals.findings} findings`);
  if (totals.experiences) learnedBits.push(`+${totals.experiences} experiences`);
  if (totals.documents) learnedBits.push(`${totals.documents} docs`);
  if (totals.conversations) learnedBits.push(`${totals.conversations} chats`);
  if (totals.code_repos) learnedBits.push(`${totals.code_repos} repos`);
  if (totals.candidates) learnedBits.push(`+${totals.candidates} candidates`);
  if (learnedBits.length) {
    card.append(el("div", { class: "archive-learned muted small", text:
      "Learned this job: " + learnedBits.join(" · ") }));
  } else if (done) {
    card.append(el("div", { class: "archive-learned muted small", text:
      "Ingest finished — open Personal / Engineering / mission journal to review what Atlas absorbed." }));
  }

  const actions = el("div", { class: "job-actions" });
  if (done && ["running", "recovering"].includes(w.status)) {
    actions.append(el("button", {
      onclick: () => archiveWorkerAction(w.id, "stop"),
    }, "Stop (free slot)"));
  }
  if (["running", "recovering"].includes(w.status) && !done) {
    actions.append(el("button", { onclick: () => archiveWorkerAction(w.id, "pause") }, "Pause"));
  }
  if (["paused"].includes(w.status)) {
    actions.append(el("button", { onclick: () => archiveWorkerAction(w.id, "resume") }, "Resume"));
  }
  if (!["stopped"].includes(w.status) && !(done && w.status === "running")) {
    actions.append(el("button", { onclick: () => archiveWorkerAction(w.id, "stop") }, "Stop"));
  }
  if (w.mission_id) {
    actions.append(el("button", {
      onclick: () => { switchView("missions"); showMissionDetail(w.mission_id); },
    }, "Open mission / journal"));
  }
  actions.append(el("button", {
    onclick: () => switchView("personal"),
  }, "View Personal learning"));
  actions.append(el("button", {
    onclick: () => switchView("engineering"),
  }, "View Engineering findings"));
  card.append(actions);
  return card;
}

async function archiveWorkerAction(workerId, action) {
  try {
    await api(`/v1/workers/${workerId}/${action}`, { method: "POST", body: { reason: "operator " + action } });
    await loadArchive();
  } catch (err) { toast(err.message); }
}

async function startArchiveIngest(opts) {
  const path = ($("#archive-path") && $("#archive-path").value.trim()) || "";
  const btn = $("#archive-start-btn");
  if (!path) {
    setArchiveStatus("Need a folder path — e.g. /media/…/Certificates", "fail");
    toast("Enter an archive path first");
    return;
  }
  if (btn) btn.disabled = true;
  setArchiveStatus("Assessing resources…", "busy");
  try {
    const body = {
      path,
      kind: ($("#archive-kind") && $("#archive-kind").value) || "document",
      parallel: !($("#archive-parallel") && !$("#archive-parallel").checked),
      note: ($("#archive-note") && $("#archive-note").value.trim()) || null,
      period_start: ($("#archive-period-start") && $("#archive-period-start").value.trim()) || null,
      period_end: ($("#archive-period-end") && $("#archive-period-end").value.trim()) || null,
    };
    if (opts && opts.confirm) {
      body.confirm = true;
      if (opts.confirmation_token) body.confirmation_token = opts.confirmation_token;
    }
    const out = await api("/v1/archive/ingest", { method: "POST", body });
    if (out.mode === "needs_confirmation" || (out.admission && out.admission.status === "needs_confirmation")) {
      const est = out.estimate || (out.admission && out.admission.estimate) || {};
      const files = est.file_count != null ? est.file_count : "?";
      const hours = est.duration_seconds != null ? (est.duration_seconds / 3600).toFixed(1) : "?";
      const growth = est.storage_growth_mb != null ? Math.round(est.storage_growth_mb) : "?";
      const token = out.confirmation_token || (out.admission && out.admission.confirmation_token);
      setArchiveStatus(
        `Needs confirmation · ~${files} files · ~${hours}h · ~${growth} MB growth — click Confirm to start`,
        "busy",
      );
      showArchiveConfirm(token, `~${files} files · ~${hours}h · ~${growth} MB`);
      toast("Large archive — confirm to proceed");
      return;
    }
    hideArchiveConfirm();
    const mode = out.mode || "started";
    if (mode === "rejected") {
      setArchiveStatus(out.note || "Rejected by Resource Planner", "fail");
      toast(out.note || "Rejected");
      return;
    }
    if (mode === "queued_for_capacity" || out.queued) {
      setArchiveStatus(
        `Queued until capacity frees · ${out.queue_reason || "host busy"} · mission ${String(out.mission_id || "").slice(0, 8)}`,
        "busy",
      );
    } else {
      setArchiveStatus(
        mode === "parallel_mission"
          ? `Started parallel job · mission ${String(out.mission_id || "").slice(0, 8)} · keep disk mounted`
          : `Root added to shared Personal Observer (${mode})`,
        "ok",
      );
    }
    toast(out.note || "Archive ingest accepted");
    await loadArchive();
  } catch (err) {
    setArchiveStatus(err.message || "Start failed", "fail");
    toast(err.message);
  } finally {
    if (btn) btn.disabled = false;
  }
}

function showArchiveConfirm(token, summary) {
  let bar = $("#archive-confirm-bar");
  if (!bar) {
    const status = $("#archive-status");
    bar = el("div", { id: "archive-confirm-bar", class: "archive-confirm-bar" });
    if (status && status.parentNode) status.parentNode.insertBefore(bar, status.nextSibling);
  }
  bar.innerHTML = "";
  bar.classList.remove("hidden");
  bar.append(
    el("span", { class: "muted small", text: `Confirm ingest (${summary || "large archive"})` }),
    el("button", {
      type: "button",
      id: "archive-confirm-btn",
      class: "link",
      text: "Confirm & start",
      onclick: () => startArchiveIngest({ confirm: true, confirmation_token: token }),
    }),
    el("button", {
      type: "button",
      class: "link muted",
      text: "Cancel",
      onclick: () => hideArchiveConfirm(),
    }),
  );
}

function hideArchiveConfirm() {
  const bar = $("#archive-confirm-bar");
  if (bar) {
    bar.innerHTML = "";
    bar.classList.add("hidden");
  }
}

function setArchiveStatus(text, kind) {
  const status = $("#archive-status");
  if (!status) return;
  status.textContent = text;
  status.className = "eng-status small"
    + (kind === "busy" ? " eng-busy" : kind === "ok" ? " eng-ok" : kind === "fail" ? " eng-fail" : " muted");
}

function startArchivePoll() {
  stopArchivePoll();
  state.archivePoll = setInterval(() => {
    if (state.view !== "archive") return stopArchivePoll();
    loadArchiveQuiet();
  }, 5000);
}
function stopArchivePoll() {
  if (state.archivePoll) { clearInterval(state.archivePoll); state.archivePoll = null; }
}
async function loadArchiveQuiet() {
  try {
    const d = await api("/v1/archive/status?limit=50");
    archiveCache = d;
    if (state.view === "archive") renderArchive(d);
  } catch (_) { /* keep last good render */ }
}

function startMissionPoll(id) {
  stopMissionPoll();
  state.missionPoll = setInterval(() => {
    if (state.view !== "missions") return stopMissionPoll();
    showMissionDetail(id, { preserve: true });
  }, 4000);
}
function stopMissionPoll() { if (state.missionPoll) { clearInterval(state.missionPoll); state.missionPoll = null; } }

/* ---------- system ---------- */
async function loadSystem() {
  try {
    const [status, health] = await Promise.all([api("/v1/status"), api("/v1/health")]);
    applyStatus(status);
    renderSystem(status, health);
  } catch (err) { toast(err.message); }
}

function renderSystem(status, health) {
  const cards = $("#status-cards");
  cards.innerHTML = "";
  const upt = status.uptime_seconds;
  const uptStr = upt == null ? "—" : upt < 90 ? `${Math.round(upt)}s` : upt < 5400 ? `${Math.round(upt / 60)}m` : `${(upt / 3600).toFixed(1)}h`;
  const items = [
    ["version", status.version],
    ["uptime", uptStr],
    ["services", status.services_total],
    ["ok", status.severity_counts.ok],
    ["degraded", status.severity_counts.degraded],
    ["failed", status.severity_counts.failed],
  ];
  for (const [k, v] of items) cards.append(el("div", { class: "card" }, el("div", { class: "k", text: k }), el("div", { class: "v", text: v })));

  const list = $("#health-list");
  list.innerHTML = "";
  const svcs = health.services || {};
  for (const name of Object.keys(svcs).sort()) {
    const s = svcs[name];
    list.append(el("div", { class: "health-row" },
      el("span", { class: "badge " + (s.severity || (s.healthy ? "ok" : "failed")), text: s.severity || (s.healthy ? "ok" : "failed") }),
      el("span", { class: "name", text: name }),
      el("span", { class: "detail", text: s.detail || "" }),
    ));
  }
}

/* ---------- overview / operations dashboard ---------- */
function fmtBytes(n) {
  if (n == null) return "—";
  const u = ["B", "KB", "MB", "GB", "TB", "PB"];
  let i = 0, v = n;
  while (v >= 1024 && i < u.length - 1) { v /= 1024; i++; }
  return `${v.toFixed(v < 10 && i > 0 ? 1 : 0)} ${u[i]}`;
}
function fmtPct(p) { return p == null ? "—" : `${p}%`; }
function fmtUptime(upt) {
  if (upt == null) return "—";
  if (upt < 90) return `${Math.round(upt)}s`;
  if (upt < 5400) return `${Math.round(upt / 60)}m`;
  if (upt < 172800) return `${(upt / 3600).toFixed(1)}h`;
  return `${(upt / 86400).toFixed(1)}d`;
}
function pctSeverity(p) { return p == null ? "" : p >= 92 ? "fail" : p >= 80 ? "warn" : ""; }

async function loadOverview() {
  startOpsStream();
  startOpsPoll();
  await refreshOps();
}

async function refreshOps() {
  try {
    const snap = await api("/v1/ops");
    if (snap.atlas) applyStatus(snap.atlas);
    renderOps(snap);
  } catch (err) { toast(err.message); }
}

function opsCard(k, v, sev) {
  return el("div", { class: "card" + (sev ? " " + sev : "") },
    el("div", { class: "k", text: k }), el("div", { class: "v", text: v }));
}

function renderOps(snap) {
  const cards = $("#ops-cards");
  cards.innerHTML = "";
  const a = snap.atlas || {}, host = snap.host || {}, counts = snap.counts || {};
  const cpu = host.cpu || {}, mem = host.memory || {}, disk = host.disk || {};
  const inet = host.internet || {}, temp = host.temperature || {}, ups = host.ups || {};
  const backup = snap.backup || {};

  const sc = a.severity_counts || { ok: 0, degraded: 0, failed: 0 };
  cards.append(opsCard("atlas", a.healthy ? (a.degraded ? "degraded" : "healthy") : "down",
    a.healthy ? (a.degraded ? "warn" : "") : "fail"));
  cards.append(opsCard("version", a.version || "—"));
  cards.append(opsCard("uptime", fmtUptime(a.uptime_seconds)));
  cards.append(opsCard("services", `${sc.ok} ok · ${sc.degraded} deg · ${sc.failed} down`,
    sc.failed ? "fail" : sc.degraded ? "warn" : ""));

  cards.append(opsCard("CPU", fmtPct(cpu.percent) + (cpu.count ? ` · ${cpu.count} cores` : ""),
    pctSeverity(cpu.percent)));
  cards.append(opsCard("RAM", `${fmtPct(mem.percent)} · ${fmtBytes(mem.used)}/${fmtBytes(mem.total)}`,
    pctSeverity(mem.percent)));
  cards.append(opsCard("disk", `${fmtPct(disk.percent)} · ${fmtBytes(disk.free)} free`,
    pctSeverity(disk.percent)));
  cards.append(opsCard("internet",
    inet.reachable == null ? "unknown" : inet.reachable ? "connected" : "disconnected",
    inet.reachable === false ? "warn" : ""));
  cards.append(opsCard("temp", temp.present ? `${temp.celsius}°C` : "not present",
    temp.present && temp.celsius >= 80 ? "warn" : ""));
  const pwr = snap.power || {};
  const upsCard = ups.present
    ? (ups.on_battery ? "on battery" : (ups.status || "present"))
    : (pwr.monitored ? (pwr.on_battery ? "on battery" : "AC / present") : "not monitored");
  cards.append(opsCard(
    "power",
    upsCard,
    (ups.on_battery || pwr.on_battery) ? "warn" : (!pwr.monitored && !ups.present ? "" : ""),
  ));

  cards.append(opsCard("jobs", `${counts.jobs_active || 0} active · ${counts.jobs_total || 0} total`));
  cards.append(opsCard("missions", counts.missions || 0));

  const ws = snap.worker_states || {};
  const wcounts = ws.counts || {};
  const inv = counts.workers != null ? counts.workers : (ws.inventory_running || 0);
  cards.append(opsCard(
    "workers (inventory)",
    `${inv} on · ${ws.active != null ? ws.active : "—"} classified`,
  ));

  const hg = snap.host_guard || {};
  const res = hg.resources || {};
  const arb = hg.arbiter || {};
  const tickMax = (arb.effective_global_max != null)
    ? arb.effective_global_max
    : (hg.max_concurrent_ticks || arb.global_max || "—");
  const tickHard = hg.max_concurrent_ticks || arb.global_max;
  const tickIn = arb.total_inflight != null ? arb.total_inflight : (wcounts.running_ticks || 0);
  const admit = res.tick_would_admit;
  cards.append(opsCard(
    "host guard",
    admit === false ? "deferring" : (res.throttled ? "throttled" : "ok"),
    admit === false || res.throttled ? "warn" : "",
  ));
  cards.append(opsCard(
    "tick slots",
    tickHard != null && tickHard !== tickMax
      ? `${tickIn} / ${tickMax} (hard ${tickHard})`
      : `${tickIn} / ${tickMax}`,
  ));
  const rtRes = arb.realtime_reserve_slots;
  const rtIn = arb.realtime_inflight;
  if (rtRes != null) {
    cards.append(opsCard(
      "realtime reserve",
      `${rtIn != null ? rtIn : 0} in · ${rtRes} reserved`,
      (tickIn >= tickMax - (rtRes || 0) && (rtIn || 0) === 0) ? "warn" : "",
    ));
  }
  const resv = snap.reservations || {};
  cards.append(opsCard(
    "leases",
    `${resv.holding_count != null ? resv.holding_count : 0} holding`,
    (resv.holding_count || 0) > 0 ? "ok" : "",
  ));
  const sp = snap.storage_pressure || {};
  cards.append(opsCard(
    "storage",
    sp.percent != null ? `${sp.percent}% · ${sp.level || "ok"}` : (sp.level || "—"),
    sp.level === "high" ? "fail" : sp.level === "warn" ? "warn" : "",
  ));
  const bud = snap.budgets || {};
  if (bud.effective_ticks != null) {
    cards.append(opsCard(
      "effective ticks",
      `${bud.effective_ticks} / hard ${bud.hard_tick_ceiling != null ? bud.hard_tick_ceiling : "—"}`
        + (bud.hysteresis && bud.hysteresis !== "steady" ? ` · ${bud.hysteresis}` : ""),
      bud.pressure ? "warn" : "",
    ));
  }
  const mp = snap.machine_profile || {};
  if (mp.suggested_profile) {
    const cfgP = mp.configured_profile || "—";
    cards.append(opsCard(
      "machine profile",
      `${cfgP} · suggest ${mp.suggested_profile}`,
      cfgP !== mp.suggested_profile ? "warn" : "",
    ));
  }
  const wa = snap.work_admission || {};
  if (wa.version) {
    cards.append(opsCard(
      "batch window",
      wa.enforce_batch_window
        ? (wa.in_batch_window ? "quiet hours · open" : "quiet hours · deferred")
        : "off (always allow)",
      wa.enforce_batch_window && !wa.in_batch_window ? "warn" : "",
    ));
  }
  cards.append(opsCard(
    "capacity queue",
    `${hg.capacity_queued_workers || 0} waiting · ${hg.deferred_ticks_total || 0} deferred`,
    (hg.capacity_queued_workers || 0) > 0 ? "warn" : "",
  ));
  cards.append(opsCard(
    "archive slots",
    `${hg.archive_workers_running || 0} / ${hg.max_archive_workers || 1}`,
  ));

  cards.append(opsCard("last backup", backup.last || "none"));
  cards.append(opsCard("live clients", snap.sse_subscribers || 0));

  renderOpsWorkerStates(ws);
  renderOpsMissionQueue(snap.mission_queue || {});
}

const OPS_STATE_LABELS = [
  ["running_ticks", "Running ticks"],
  ["holding_reservation", "Holding reservation"],
  ["ready", "Ready"],
  ["waiting_host", "Waiting Host"],
  ["waiting_schedule", "Waiting Schedule"],
  ["waiting_dependency", "Waiting Dependency"],
  ["sleeping", "Sleeping"],
  ["paused", "Paused"],
  ["starved", "Starved"],
  ["slow", "Slow"],
  ["completed", "Completed"],
];

function opsStateSeverity(key, n) {
  if (!n) return "";
  if (key === "starved" || key === "slow") return "fail";
  if (key === "waiting_host" || key === "waiting_dependency" || key === "holding_reservation") return "warn";
  if (key === "running_ticks") return "ok";
  return "";
}

function renderOpsWorkerStates(ws) {
  const box = $("#ops-worker-states");
  const notableBox = $("#ops-worker-notable");
  if (!box) return;
  box.innerHTML = "";
  const counts = (ws && ws.counts) || {};
  for (const [key, label] of OPS_STATE_LABELS) {
    const n = counts[key] || 0;
    const sev = opsStateSeverity(key, n);
    box.append(el("div", { class: "ops-state-chip" + (sev ? " " + sev : "") },
      el("div", { class: "k", text: label }),
      el("div", { class: "v", text: String(n) })));
  }
  if (!notableBox) return;
  notableBox.innerHTML = "";
  const notable = (ws && ws.notable) || [];
  if (!notable.length) {
    notableBox.append(el("div", { class: "muted small", text: "No starved, slow, or waiting-host workers." }));
    return;
  }
  for (const row of notable) {
    const title = row.mission_title || row.type || row.id || "worker";
    const age = row.starvation_age_seconds != null
      ? ` · age ${fmtUptime(row.starvation_age_seconds)}`
      : "";
    const tick = row.last_tick_ms != null
      ? ` · last tick ${Math.round(row.last_tick_ms)}ms (avg ${Math.round(row.avg_tick_ms || 0)}ms)`
      : "";
    const wait = row.wait_reason ? ` · ${row.wait_reason}` : "";
    const sev = opsStateSeverity(row.ops_state, 1) || "ok";
    notableBox.append(el("div", { class: "health-row" },
      el("span", { class: "badge " + sev, text: row.ops_state || "?" }),
      el("span", { class: "name", text: title }),
      el("span", { class: "detail", text: `${row.type || ""}${wait}${tick}${age}` })));
  }
}

const QUEUE_STATE_LABELS = [
  ["READY", "Ready"],
  ["WAITING_HOST", "Waiting Host"],
  ["WAITING_SCHEDULE", "Waiting Schedule"],
  ["WAITING_DEPENDENCY", "Waiting Dependency"],
  ["WAITING_OPERATOR", "Waiting Operator"],
  ["RUNNING", "Running"],
  ["PAUSED", "Paused"],
  ["BLOCKED", "Blocked"],
  ["COMPLETE", "Complete"],
  ["ARCHIVED", "Archived"],
];

function queueStateSeverity(key, n) {
  if (!n) return "";
  if (key === "WAITING_HOST" || key === "WAITING_DEPENDENCY" || key === "BLOCKED") return "warn";
  if (key === "RUNNING") return "ok";
  return "";
}

function renderOpsMissionQueue(mq) {
  const box = $("#ops-mission-queue");
  const notableBox = $("#ops-mission-queue-notable");
  if (!box) return;
  box.innerHTML = "";
  const counts = (mq && mq.counts) || {};
  for (const [key, label] of QUEUE_STATE_LABELS) {
    const n = counts[key] || 0;
    const sev = queueStateSeverity(key, n);
    box.append(el("div", { class: "ops-state-chip" + (sev ? " " + sev : "") },
      el("div", { class: "k", text: label }),
      el("div", { class: "v", text: String(n) })));
  }
  if (!notableBox) return;
  notableBox.innerHTML = "";
  const notable = (mq && mq.notable) || [];
  if (!notable.length) {
    notableBox.append(el("div", { class: "muted small", text: "No waiting-host or dependency-blocked missions." }));
    return;
  }
  for (const row of notable) {
    const owner = row.owner || {};
    const title = owner.mission_title || row.mission_id || "mission";
    const prog = owner.program ? ` · ${owner.program}` : "";
    const cls = row.service_class ? ` · ${row.service_class}` : "";
    const reason = row.reason ? ` · ${row.reason}` : "";
    const deps = (row.depends_on || []).length ? ` · depends ${row.depends_on.length}` : "";
    const sev = queueStateSeverity(row.state, 1) || "ok";
    notableBox.append(el("div", { class: "health-row" },
      el("span", { class: "badge " + sev, text: row.state || "?" }),
      el("span", { class: "name", text: title }),
      el("span", { class: "detail", text: `${String(row.mission_id || "").slice(0, 8)}${prog}${cls}${reason}${deps}` })));
  }
}

function pushActivity(type, payload) {
  const feed = $("#ops-activity");
  if (!feed) return;
  const hint = feed.querySelector(".empty-hint");
  if (hint) hint.remove();
  const when = new Date().toLocaleTimeString();
  const sev = /\.(failed|error)$/.test(type) ? "failed"
    : /\.(completed|done)$/.test(type) ? "ok" : "";
  const row = el("div", { class: "health-row" },
    el("span", { class: "badge " + (sev || "ok"), text: sev || "event" }),
    el("span", { class: "name", text: type }),
    el("span", { class: "detail", text: when }));
  feed.prepend(row);
  while (feed.children.length > 50) feed.lastChild.remove();
}

function startOpsPoll() {
  stopOpsPoll();
  state.opsPoll = setInterval(() => {
    if (state.view !== "overview") return stopOpsPoll();
    refreshOps();
  }, 5000);
}
function stopOpsPoll() { if (state.opsPoll) { clearInterval(state.opsPoll); state.opsPoll = null; } }

// Live event feed over SSE. EventSource can't set an Authorization header, so we read
// the stream with fetch() + a ReadableStream reader and parse the SSE frames ourselves.
function startOpsStream() {
  stopOpsStream();
  const feed = $("#ops-activity");
  if (feed && !feed.children.length) {
    feed.append(el("div", { class: "empty-hint" },
      el("p", { class: "muted", text: "Waiting for live events…" })));
  }
  const ctrl = new AbortController();
  state.opsStream = ctrl;
  fetch("/v1/events/stream", {
    headers: { "Authorization": `Bearer ${state.key}` },
    signal: ctrl.signal,
  }).then(async (res) => {
    if (!res.ok || !res.body) return;
    const reader = res.body.getReader();
    const dec = new TextDecoder();
    let buf = "";
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      let idx;
      while ((idx = buf.indexOf("\n\n")) >= 0) {
        handleSseFrame(buf.slice(0, idx));
        buf = buf.slice(idx + 2);
      }
    }
  }).catch(() => { /* aborted on view switch, or network dropped */ });
}
function handleSseFrame(frame) {
  if (!frame || frame.startsWith(":")) return;  // heartbeat / blank
  let type = "message", data = null;
  for (const line of frame.split("\n")) {
    if (line.startsWith("event:")) type = line.slice(6).trim();
    else if (line.startsWith("data:")) data = line.slice(5).trim();
  }
  let payload = {};
  try { payload = data ? JSON.parse(data) : {}; } catch (_) { /* ignore */ }
  pushActivity(type, payload);
}
function stopOpsStream() {
  if (state.opsStream) { try { state.opsStream.abort(); } catch (_) {} state.opsStream = null; }
}

/* ---------- wiring ---------- */
function init() {
  $("#login-form").addEventListener("submit", (e) => {
    e.preventDefault();
    const key = $("#login-key").value.trim();
    if (key) tryConnect(key);
  });
  $("#logout").addEventListener("click", () => signOut());

  document.querySelectorAll(".nav-btn").forEach((b) =>
    b.addEventListener("click", () => switchView(b.dataset.view)));

  const input = $("#composer-input");
  input.addEventListener("input", () => {
    input.style.height = "auto";
    input.style.height = Math.min(input.scrollHeight, 180) + "px";
  });
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      const text = input.value;
      input.value = ""; input.style.height = "auto";
      sendMessage(text);
    }
  });
  $("#composer").addEventListener("submit", (e) => {
    e.preventDefault();
    const text = input.value;
    input.value = ""; input.style.height = "auto";
    sendMessage(text);
  });

  $("#job-form").addEventListener("submit", (e) => {
    e.preventDefault();
    const obj = $("#job-objective").value.trim();
    if (obj) createJob(obj);
  });
  $("#jobs-refresh").addEventListener("click", loadJobs);
  $("#missions-refresh").addEventListener("click", loadMissions);
  const programsRefresh = $("#programs-refresh");
  if (programsRefresh) programsRefresh.addEventListener("click", loadPrograms);
  const learnerRefresh = $("#learner-refresh");
  if (learnerRefresh) learnerRefresh.addEventListener("click", () => loadLearner());
  const iipRefresh = $("#iip-refresh");
  if (iipRefresh) iipRefresh.addEventListener("click", () => loadIip());
  const iipSave = $("#iip-save-universes");
  if (iipSave) iipSave.addEventListener("click", () => saveIipUniverses());
  const iipRun = $("#iip-run-discovery");
  if (iipRun) iipRun.addEventListener("click", async () => {
    try {
      iipRun.disabled = true;
      iipRun.textContent = "Running…";
      await api("/v1/market/discovery/run", { method: "POST", body: { max_scan: 80 } });
      toast("Discovery finished — refresh list below");
      loadIip();
    } catch (err) {
      toast(err.message || String(err));
    } finally {
      iipRun.disabled = false;
      iipRun.textContent = "Run discovery now";
    }
  });
  const learnerAuto = $("#learner-auto");
  if (learnerAuto) learnerAuto.addEventListener("change", () => {
    if (learnerAuto.checked && state.view === "learner") startLearnerPoll();
    else stopLearnerPoll();
  });
  const emailPreview = $("#learner-email-preview");
  if (emailPreview) emailPreview.addEventListener("click", () => previewInvestorEmail("morning"));
  const emailPreviewEve = $("#learner-email-preview-evening");
  if (emailPreviewEve) emailPreviewEve.addEventListener("click", () => previewInvestorEmail("evening"));
  const emailPreviewWeek = $("#learner-email-preview-weekly");
  if (emailPreviewWeek) emailPreviewWeek.addEventListener("click", () => previewInvestorEmail("weekly"));
  const emailSend = $("#learner-email-send");
  if (emailSend) emailSend.addEventListener("click", () => sendInvestorEmail("morning"));
  const emailSendEve = $("#learner-email-send-evening");
  if (emailSendEve) emailSendEve.addEventListener("click", () => sendInvestorEmail("evening"));
  const emailSendWeek = $("#learner-email-send-weekly");
  if (emailSendWeek) emailSendWeek.addEventListener("click", () => sendInvestorEmail("weekly"));
  const researchGo = $("#learner-research-go");
  if (researchGo) researchGo.addEventListener("click", () => startLearnerResearch());
  const snapGo = $("#learner-research-snapshot-go");
  if (snapGo) snapGo.addEventListener("click", () => applyLearnerResearchSnapshot());
  const filingsGo = $("#learner-research-filings-go");
  if (filingsGo) filingsGo.addEventListener("click", () => applyLearnerFilingRefs());
  const critGo = $("#learner-research-critical-go");
  if (critGo) critGo.addEventListener("click", () => raiseLearnerCriticalFlag());
  const mgmtGo = $("#learner-research-mgmt-go");
  if (mgmtGo) mgmtGo.addEventListener("click", () => applyLearnerManagementPack());
  const researchInput = $("#learner-research-symbol");
  if (researchInput) researchInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      startLearnerResearch();
    }
  });
  $("#mission-form").addEventListener("submit", (e) => {
    e.preventDefault();
    const tpl = $("#mission-template").value;
    if (tpl) instantiateMission(tpl, $("#mission-title").value.trim());
  });
  const tplSel = $("#mission-template");
  if (tplSel) tplSel.addEventListener("change", () => {
    const ta = $("#mission-config");
    if (ta) { ta.dataset.seeded = "1"; ta.dataset.touched = ""; }
    seedMissionConfigFromTemplate();
  });
  const cfgTa = $("#mission-config");
  if (cfgTa) cfgTa.addEventListener("input", () => { cfgTa.dataset.touched = "1"; cfgTa.dataset.seeded = ""; });
  const feedBtn = $("#mission-feed-sample");
  if (feedBtn) feedBtn.addEventListener("click", registerSampleMarketData);
  $("#system-refresh").addEventListener("click", loadSystem);
  $("#overview-refresh").addEventListener("click", refreshOps);
  $("#personal-refresh")?.addEventListener("click", loadPersonal);
  $("#personal-infer")?.addEventListener("click", personalInfer);
  $("#personal-draft")?.addEventListener("click", personalDraft);
  $("#personal-draft-li")?.addEventListener("click", personalDraftLinkedIn);
  document.querySelectorAll(".personal-tab").forEach((btn) => {
    btn.addEventListener("click", () => setPersonalTab(btn.dataset.tab || "skills"));
  });
  $("#eng-refresh").addEventListener("click", loadEngineering);
  $("#archive-refresh")?.addEventListener("click", loadArchive);
  $("#archive-form")?.addEventListener("submit", (e) => {
    e.preventDefault();
    startArchiveIngest();
  });
  $("#eng-form").addEventListener("submit", (e) => {
    e.preventDefault();
    const src = $("#eng-source").value.trim();
    if (!src) {
      toast("Enter a repository path or git URL first");
      const status = $("#eng-status");
      if (status) {
        status.textContent = "Need a path or URL — e.g. /home/jagd/projects/my-app";
        status.className = "eng-status small eng-fail";
      }
      return;
    }
    ingestRepo(src, $("#eng-embed").checked, {
      note: ($("#eng-note") && $("#eng-note").value.trim()) || "",
      period_start: ($("#eng-period-start") && $("#eng-period-start").value.trim()) || "",
      period_end: ($("#eng-period-end") && $("#eng-period-end").value.trim()) || "",
    });
  });

  if (state.key) {
    tryConnect(state.key).then((ok) => { if (!ok) { $("#login").classList.remove("hidden"); } });
  } else {
    $("#login").classList.remove("hidden");
  }
}

document.addEventListener("DOMContentLoaded", init);
