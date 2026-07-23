const $ = (id) => document.getElementById(id);

function toast(msg) {
  const t = $("toast");
  t.textContent = msg;
  t.classList.add("show");
  setTimeout(() => t.classList.remove("show"), 2200);
}

function fmtSize(n) {
  if (n < 1024) return n + " B";
  if (n < 1024 * 1024) return (n / 1024).toFixed(1) + " KB";
  return (n / 1048576).toFixed(1) + " MB";
}

function escapeHtml(s) {
  return (s || "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function section(label, text, cls) {
  if (!text) return "";
  return `<div class="rsec ${cls||''}"><span class="rsec-label">${label}</span><div class="rsec-body">${escapeHtml(text)}</div></div>`;
}

function reportCard(r) {
  const time = (r.modified || "").replace("T", " ");
  if (r.kind === "report") {
    const dl = r.code_file
      ? `<a class="dl" href="/api/download/${encodeURIComponent(r.code_file)}" download>Download code</a>` : "";
    return `<div class="report">
      <div class="report-head">
        <span class="tag code">${escapeHtml(r.language || r.extension || "code")}</span>
        <span class="report-name">${escapeHtml(r.code_file || r.name)}</span>
        <span class="report-time">${time}</span>
      </div>
      ${section("Overview", r.overview, "overview")}
      ${section("Errors found", r.errors, "errors")}
      ${section("Tech-stack review", r.tech_stack, "tech")}
      <div class="rsec"><span class="rsec-label">Code</span>
        <pre class="code">${escapeHtml(r.code || "")}</pre></div>
      <div class="report-actions">${acts}</div>
    </div>`;
  }
  const body = r.content
    ? `<pre class="code">${escapeHtml(r.content)}</pre>`
    : `<p style="font-size:13px;color:var(--muted);margin:6px 0 0">${fmtSize(r.size)} · <a class="dl" href="/api/download/${encodeURIComponent(r.code_file||r.name)}" download>Download</a></p>`;
  return `<div class="report">
    <div class="report-head">
      <span class="tag ${r.kind}">${r.ext || r.kind}</span>
      <span class="report-name">${escapeHtml(r.name)}</span>
      <span class="report-time">${time}</span>
    </div>
    ${body}
  </div>`;
}

const _pending = {};

function _download(filename, text, mime) {
  const blob = new Blob([text], { type: mime || "text/plain" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url; a.download = filename;
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function downloadCode(name) {
  const r = _pending[name];
  if (!r) return;
  const fn = r.code_file || (name + "." + (r.extension || "txt"));
  _download(fn, r.code || "", "text/plain");
  toast("Code file saved to your Downloads.");
}

function downloadReport(name) {
  const r = _pending[name];
  if (!r) return;
  const lines = [
    "# Report — " + name,
    "",
    "**Language:** " + (r.language || r.extension || "n/a"),
    "",
    "## Overview",
    (r.overview || "(none)"),
    "",
    "## Errors found",
    (r.errors || "None"),
    "",
    "## Tech-stack review",
    (r.tech_stack || "n/a"),
    ""
  ];
  _download(name + "_report.md", lines.join("\n"), "text/markdown");
  toast("Report saved to your Downloads.");
}

function pendingCard(r) {
  const time = (r.modified || "").replace("T", " ");
  _pending[r.name] = r;
  const acts = `<button class="dl" onclick="downloadCode('${r.name}')">Save code</button>`
    + `<button class="dl secondary" onclick="downloadReport('${r.name}')">Save report</button>`;
  return `<div class="report pending">
    <div class="report-head">
      <span class="tag ready">Ready \u00b7 not saved</span>
      <span class="tag code">${escapeHtml(r.language || r.extension || "code")}</span>
      <span class="report-name">${escapeHtml(r.code_file || r.name)}</span>
      <span class="report-time">${time}</span>
    </div>
    ${section("Overview", r.overview, "overview")}
    ${section("Errors found", r.errors, "errors")}
    ${section("Tech-stack review", r.tech_stack, "tech")}
    <div class="rsec"><span class="rsec-label">Code</span>
      <pre class="code">${escapeHtml(r.code || "")}</pre></div>
    <div class="report-actions">${acts}</div>
  </div>`;
}

async function loadReports() {
  const box = $("reports");
  box.innerHTML = `<p style="color:var(--muted)">Loading…</p>`;
  let saved = [], pending = [], reachedServer = false;
  try {
    const res = await fetch("/api/reports");
    saved = (await res.json()).reports || [];
    reachedServer = true;
  } catch (e) { console.error("loadReports: /api/reports failed", e); }
  try {
    const res = await fetch("/api/pending");
    pending = (await res.json()).reports || [];
    reachedServer = true;
  } catch (e) { console.error("loadReports: /api/pending failed", e); }

  if (!reachedServer) {
    box.innerHTML = `<div class="empty">Couldn't load results. Is the server running?</div>`;
    return;
  }
  const html = [];
  for (const r of pending) {
    try { html.push(pendingCard(r)); } catch (e) { console.error("pendingCard failed", r, e); }
  }
  for (const r of saved) {
    try { html.push(reportCard(r)); } catch (e) { console.error("reportCard failed", r, e); }
  }
  box.innerHTML = html.length
    ? html.join("")
    : `<div class="empty">No results yet. Start a capture session to create your first report.</div>`;
}

$("refreshBtn").addEventListener("click", loadReports);
let sessionRunning = false;
let lastEventCount = 0;

const FLOW = [
  ["start","Start"],["capture","Capture"],["read","Read"],["classify","Classify"],
  ["check","Check"],["fix","Fix"],["save","Save"],["done","Done"]
];

function fmtDur(sec) {
  if (sec < 1) return "<1s";
  if (sec < 60) return Math.round(sec) + "s";
  const m = Math.floor(sec / 60);
  return m + "m " + Math.round(sec % 60) + "s";
}

let lastFlowEvents = [];

function renderFlow(events) {
  lastFlowEvents = events;
  const box = $("devflow");
  const nodes = [];
  if (events.some(e => e.kind === "start")) nodes.push({ label: "Start", stage: "start" });
  for (const e of events) { if (e.kind === "tool") nodes.push({ label: e.msg, stage: e.stage || "tool" }); }
  const done = events.some(e => e.kind === "done" || e.kind === "end");
  if (done) nodes.push({ label: "Done", stage: "done" });
  if (!nodes.length) { box.innerHTML = ""; return; }
  const activeIdx = done ? -1 : nodes.length - 1;
  box.innerHTML = nodes.map((n, i) => {
    let cls = "node n-" + (n.stage || "tool");
    if (i === activeIdx && sessionRunning) cls += " active";
    const arrow = i < nodes.length - 1 ? '<span class="arrow">\u2192</span>' : "";
    return `<span class="${cls}">${escapeHtml(n.label)}</span>${arrow}`;
  }).join("");
}

function renderStatus(events) {
  const box = $("statusFeed");
  if (!events.length) { box.innerHTML = ""; return; }
  box.innerHTML = events.slice(-8).map(e =>
    `<div class="ev"><span class="ev-dot"></span>${escapeHtml(e.msg)}</div>`).join("");
  box.scrollTop = box.scrollHeight;
}

async function pollStatus() {
  try {
    const r = await fetch("/api/session/status");
    const d = await r.json();
    renderStatus(d.events || []);
    renderFlow(d.events || []);
    setRunning(d.running);
    if ((d.events || []).length !== lastEventCount) {
      lastEventCount = (d.events || []).length;
      loadReports();
    }
  } catch (e) {}
}

function setRunning(running) {
  sessionRunning = running;
  const tt = $("teamToggle");
  if (tt) tt.disabled = running;
  const b = $("startBtn");
  $("status").textContent = running ? "Session running" : "Ready";
  b.textContent = running ? "Stop session" : "Start capture";
  b.classList.toggle("stop", running);
  $("statusFeed").style.display = running ? "block" : "none";
  $("devflow").style.display = running ? "flex" : "none";
}

$("startBtn").addEventListener("click", async () => {
  if (sessionRunning) {
    await fetch("/api/session/stop", { method: "POST" });
    toast("Session stopped.");
  } else {
    const team = $("teamToggle") && $("teamToggle").checked;
    await fetch("/api/session/start" + (team ? "?team=true" : ""), { method: "POST" });
    toast(team
      ? "Team session launched — switch to your editor and press Cmd+Shift+1."
      : "Session launched — switch to your editor and press Cmd+Shift+1.");
  }
  pollStatus();
});

$("refreshBtn").addEventListener("click", loadReports);

loadReports();
setInterval(pollStatus, 1500);
pollStatus();
window.addEventListener("resize", () => { if (sessionRunning) renderFlow(lastFlowEvents); });
window.downloadCode = downloadCode;
window.downloadReport = downloadReport;
