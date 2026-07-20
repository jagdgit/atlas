"use strict";
/* Atlas Console (S23) — a zero-build vanilla SPA over the /v1 REST API. */

const KEY_STORE = "atlas_api_key";

const state = {
  key: localStorage.getItem(KEY_STORE) || "",
  view: "overview",
  sessionId: null,
  jobId: null,
  missionId: null,
  missionPoll: null,
  sending: false,
  jobPoll: null,
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
    const detail = (data && (data.detail || data.error)) || `HTTP ${res.status}`;
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
  if (view !== "missions") stopMissionPoll();
  if (view !== "overview") { stopOpsPoll(); stopOpsStream(); }
  if (view !== "engineering") stopEngStream();
  if (view === "overview") loadOverview();
  else if (view === "chat") renderSessionSidebar();
  else if (view === "missions") loadMissions();
  else if (view === "engineering") loadEngineering();
  else if (view === "jobs") loadJobs();
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

/* ---------- engineering (Phase B · §B.7) ---------- */
async function loadEngineering() {
  startEngStream();
  try {
    const data = await api("/v1/engineering/repositories?limit=100");
    renderRepoList(data.repositories || []);
    if (state.repoId) showRepoDetail(state.repoId);
  } catch (err) { toast(err.message); }
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

async function ingestRepo(source, embed) {
  const body = /^(https?:\/\/|git@)/.test(source) ? { url: source } : { path: source };
  body.embed = !!embed;
  try {
    toast("Ingesting… this can take a moment");
    const out = await api("/v1/engineering/ingest", { method: "POST", body });
    if (out.outcome !== "ok") { toast("Ingest failed: " + (out.reason || "unknown")); return; }
    $("#eng-source").value = "";
    await loadEngineering();
    if (out.repository && out.repository.id) showRepoDetail(out.repository.id);
    toast("Repository ingested");
  } catch (err) { toast(err.message); }
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

// Keep polling through transient errors (a slow LLM planning step or a single
// failed/late GET must NOT freeze the status at "planning" forever). Only give up
// after several consecutive failures; otherwise re-render each tick until the job
// reaches a terminal state.
const JOB_POLL_MAX_FAILURES = 8;
function startJobPoll(id) {
  stopJobPoll();
  state.jobPollFailures = 0;
  state.jobPoll = setInterval(async () => {
    if (state.view !== "jobs") return stopJobPoll();
    try {
      const d = await api(`/v1/jobs/${id}`);
      state.jobPollFailures = 0;
      renderJobDetail(d);
      loadJobs();
      if (!jobIsActive(d.job)) stopJobPoll();
    } catch (_) {
      // Tolerate transient failures; only stop after a sustained outage.
      state.jobPollFailures = (state.jobPollFailures || 0) + 1;
      if (state.jobPollFailures >= JOB_POLL_MAX_FAILURES) stopJobPoll();
    }
  }, 2000);
}
function stopJobPoll() {
  if (state.jobPoll) { clearInterval(state.jobPoll); state.jobPoll = null; }
  state.jobPollFailures = 0;
}

/* ---------- missions (Phase A · §A.7) ---------- */
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
  sel.innerHTML = "";
  for (const t of missionTemplates) {
    sel.append(el("option", { value: t.name },
      `${t.name} (v${t.template_version})`));
  }
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

async function instantiateMission(template, title) {
  try {
    const view = await api("/v1/missions/instantiate", {
      method: "POST", body: { template, title: title || null },
    });
    $("#mission-title").value = "";
    await loadMissions();
    showMissionDetail(view.mission.id);
    toast("Mission instantiated");
  } catch (err) { toast(err.message); }
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

  const actions = el("div", { class: "job-actions" });
  for (const a of (MISSION_ACTIONS[m.status] || [])) {
    actions.append(el("button", { onclick: () => missionAction(m.id, a) }, a));
  }
  actions.append(el("button", { onclick: () => showMissionDetail(m.id) }, "Refresh"));
  box.append(actions);

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
  card.append(el("summary", {},
    el("span", { class: "intent", text: w.type }),
    el("span", { class: "badge " + w.status, text: w.status }),
    el("span", { class: "cap muted small", text: `health ${w.health} · v${w.worker_version}`
      + (w.restart_count ? ` · ${w.restart_count} restart(s)` : "") }),
  ));
  const body = el("div", { class: "step-body" });
  body.append(el("div", { class: "muted small", text: `id ${w.id}` }));

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
  cards.append(opsCard("UPS", ups.present ? "on battery" : "not present"));

  cards.append(opsCard("jobs", `${counts.jobs_active || 0} active · ${counts.jobs_total || 0} total`));
  cards.append(opsCard("missions", counts.missions || 0));
  cards.append(opsCard("workers", counts.workers || 0));
  cards.append(opsCard("last backup", backup.last || "none"));
  cards.append(opsCard("live clients", snap.sse_subscribers || 0));
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
  $("#mission-form").addEventListener("submit", (e) => {
    e.preventDefault();
    const tpl = $("#mission-template").value;
    if (tpl) instantiateMission(tpl, $("#mission-title").value.trim());
  });
  $("#system-refresh").addEventListener("click", loadSystem);
  $("#overview-refresh").addEventListener("click", refreshOps);
  $("#eng-refresh").addEventListener("click", loadEngineering);
  $("#eng-form").addEventListener("submit", (e) => {
    e.preventDefault();
    const src = $("#eng-source").value.trim();
    if (src) ingestRepo(src, $("#eng-embed").checked);
  });

  if (state.key) {
    tryConnect(state.key).then((ok) => { if (!ok) { $("#login").classList.remove("hidden"); } });
  } else {
    $("#login").classList.remove("hidden");
  }
}

document.addEventListener("DOMContentLoaded", init);
