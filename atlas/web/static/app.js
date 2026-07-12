"use strict";
/* Atlas Console (S23) — a zero-build vanilla SPA over the /v1 REST API. */

const KEY_STORE = "atlas_api_key";

const state = {
  key: localStorage.getItem(KEY_STORE) || "",
  view: "chat",
  sessionId: null,
  jobId: null,
  sending: false,
  jobPoll: null,
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
  if (view === "chat") renderSessionSidebar();
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

/* ---------- jobs ---------- */
async function loadJobs() {
  try {
    const data = await api("/v1/jobs?limit=50");
    renderJobsList(data.jobs || []);
  } catch (err) { toast(err.message); }
}

function renderJobsList(jobs) {
  const list = $("#jobs-list");
  list.innerHTML = "";
  if (!jobs.length) { list.append(el("div", { class: "muted", style: "padding:18px", text: "No jobs yet." })); return; }
  for (const j of jobs) {
    list.append(el("div", {
      class: "job-row" + (j.id === state.jobId ? " active" : ""),
      onclick: () => showJobDetail(j.id),
    },
      el("div", { class: "obj", text: j.objective }),
      el("div", {},
        el("span", { class: "badge " + j.status, text: j.status.replace(/_/g, " ") }),
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
    const active = ["queued", "running"].includes(d.job.status);
    if (active) startJobPoll(id); else stopJobPoll();
  } catch (err) { toast(err.message); }
}

function stepDuration(s) {
  if (!s.started_at || !s.completed_at) return "";
  const ms = new Date(s.completed_at) - new Date(s.started_at);
  if (!(ms >= 0)) return "";
  return ms < 1000 ? `${ms}ms` : ms < 90000 ? `${(ms / 1000).toFixed(1)}s` : `${Math.round(ms / 60000)}m`;
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
  box.append(el("div", { class: "obj-title", text: job.objective }));
  box.append(el("div", {},
    el("span", { class: "badge " + job.status, text: job.status.replace(/_/g, " ") }),
    el("span", { class: "muted small", text: `  ${d.progress.done}/${d.progress.total} done`
      + (d.progress.blocked ? ` · ${d.progress.blocked} blocked` : "")
      + (d.progress.failed ? ` · ${d.progress.failed} failed` : "") }),
  ));

  box.append(el("h3", { class: "section-h", text: `Steps executed (${d.steps.length})` }));
  const steps = el("div", { class: "steps" });
  for (const s of d.steps) steps.append(renderStepCard(s));
  box.append(steps);

  for (const b of (d.blocked || [])) {
    box.append(el("div", { class: "chips" },
      el("span", { class: "chip gap", text: `step ${b.ordinal} needs: ${b.needs || b.capability}` })));
  }

  const actions = el("div", { class: "job-actions" });
  if (job.status === "completed_with_blocks")
    actions.append(el("button", { onclick: () => jobAction(job.id, "resume") }, "Resume"));
  if (["queued", "running"].includes(job.status))
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

function startJobPoll(id) {
  stopJobPoll();
  state.jobPoll = setInterval(async () => {
    if (state.view !== "jobs") return stopJobPoll();
    try {
      const d = await api(`/v1/jobs/${id}`);
      renderJobDetail(d);
      loadJobs();
      if (!["queued", "running"].includes(d.job.status)) stopJobPoll();
    } catch (_) { stopJobPoll(); }
  }, 2000);
}
function stopJobPoll() {
  if (state.jobPoll) { clearInterval(state.jobPoll); state.jobPoll = null; }
}

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
  $("#system-refresh").addEventListener("click", loadSystem);

  if (state.key) {
    tryConnect(state.key).then((ok) => { if (!ok) { $("#login").classList.remove("hidden"); } });
  } else {
    $("#login").classList.remove("hidden");
  }
}

document.addEventListener("DOMContentLoaded", init);
