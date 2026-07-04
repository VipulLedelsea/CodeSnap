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
      <div class="report-actions">${dl}</div>
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

async function loadReports() {
  const box = $("reports");
  box.innerHTML = `<p style="color:var(--muted)">Loading…</p>`;
  try {
    const res = await fetch("/api/reports");
    const data = await res.json();
    const list = data.reports || [];
    if (!list.length) {
      box.innerHTML = `<div class="empty">No results yet. Start a capture session to create your first report.</div>`;
      return;
    }
    box.innerHTML = list.map(reportCard).join("");
  } catch (e) {
    box.innerHTML = `<div class="empty">Couldn't load results. Is the server running?</div>`;
  }
}

$("refreshBtn").addEventListener("click", loadReports);
let sessionRunning = false;
let lastEventCount = 0;

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
    setRunning(d.running);
    if ((d.events || []).length !== lastEventCount) {
      lastEventCount = (d.events || []).length;
      loadReports();
    }
  } catch (e) {}
}

function setRunning(running) {
  sessionRunning = running;
  const b = $("startBtn");
  $("status").textContent = running ? "Session running" : "Ready";
  b.textContent = running ? "Stop session" : "Start capture";
  b.classList.toggle("stop", running);
  $("statusFeed").style.display = running ? "block" : "none";
}

$("startBtn").addEventListener("click", async () => {
  if (sessionRunning) {
    await fetch("/api/session/stop", { method: "POST" });
    toast("Session stopped.");
  } else {
    await fetch("/api/session/start", { method: "POST" });
    toast("Session launched — switch to your editor and press Cmd+Shift+1.");
  }
  pollStatus();
});

$("refreshBtn").addEventListener("click", loadReports);

loadReports();
setInterval(pollStatus, 1500);
pollStatus();
