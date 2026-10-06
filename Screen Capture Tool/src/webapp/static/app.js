const $ = (id) => document.getElementById(id);

// Per-launch session token (embedded by the server in the page it serves). Every
// state-changing request must carry it, so other web pages can't drive this app.
const _CSRF = ((document.querySelector('meta[name="codesnap-token"]') || {}).content) || "";
const _nativeFetch = window.fetch.bind(window);
window.fetch = (input, init) => {
  init = init || {};
  const method = String(init.method || (input && input.method) || "GET").toUpperCase();
  if (_CSRF && method !== "GET" && method !== "HEAD") {
    const headers = new Headers(init.headers || (input && input.headers) || {});
    headers.set("X-CodeSnap-Token", _CSRF);
    init = Object.assign({}, init, { headers });
  }
  return _nativeFetch(input, init);
};
let _program = "";
let _captureKind = "code", _kindManual = false;
let _view = "codesnap";
if (window.mermaid) { try { mermaid.initialize({ startOnLoad: false, theme: "neutral", securityLevel: "strict" }); } catch (e) {} }

const ANALYZING_MSGS = [
  "Reading the captured frames\u2026",
  "Transcribing the code, exactly as written\u2026",
  "Checking it against the compiler\u2026",
  "Repairing any real errors\u2026",
  "Reviewing the tech stack\u2026",
  "Drawing the class, interaction & component diagrams\u2026",
  "Assembling your report\u2026",
];
let analyzingTimer = null, analyzingIdx = 0;
function startAnalyzing() {
  if (analyzingTimer) return;
  const box = document.getElementById("analyzing"); if (!box) return;
  box.style.display = "flex"; analyzingIdx = 0;
  const msg = document.getElementById("analyzingMsg");
  if (msg) msg.textContent = ANALYZING_MSGS[0];
  analyzingTimer = setInterval(function () {
    analyzingIdx = (analyzingIdx + 1) % ANALYZING_MSGS.length;
    const m = document.getElementById("analyzingMsg");
    if (m) m.textContent = ANALYZING_MSGS[analyzingIdx];
  }, 2600);
}
function stopAnalyzing() {
  const box = document.getElementById("analyzing"); if (box) box.style.display = "none";
  if (analyzingTimer) { clearInterval(analyzingTimer); analyzingTimer = null; }
}

// Turn a "diagrams" markdown blob (labels + ```mermaid blocks) into rendered HTML.
function renderMdText(t) {
  return t.split(/\n+/).map(function (line) {
    line = line.trim();
    if (!line) return "";
    var b = /^\*\*(.+?)\*\*$/.exec(line);
    if (b) return `<div class="dlabel">${escapeHtml(b[1])}</div>`;
    var i = /^_(.+?)_$/.exec(line);
    if (i) return `<div class="dnote">${escapeHtml(i[1])}</div>`;
    return `<div class="dnote">${escapeHtml(line.replace(/\*\*/g, ""))}</div>`;
  }).join("");
}

function diagramsSection(text) {
  if (!text || !text.trim()) return "";
  const parts = [];
  const re = /```mermaid\s*([\s\S]*?)```/g;
  let last = 0, m;
  while ((m = re.exec(text))) {
    const before = text.slice(last, m.index).trim();
    if (before) parts.push(renderMdText(before));
    parts.push(`<pre class="mermaid">${escapeHtml(m[1].trim())}</pre>`);
    last = re.lastIndex;
  }
  const tail = text.slice(last).trim();
  if (tail) parts.push(renderMdText(tail));
  return `<div class="rsec diagrams"><span class="rsec-label">Diagrams</span><div class="rsec-body">${parts.join("")}</div></div>`;
}

function renderMermaid() {
  if (!window.mermaid) return;
  const nodes = document.querySelectorAll('.mermaid:not([data-processed="true"])');
  if (!nodes.length) return;
  try { mermaid.run({ nodes }); } catch (e) { console.error("mermaid", e); }
}

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
  return String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

// Buttons carry data-act/data-name instead of inline onclick="...${value}...".
document.addEventListener("click", (ev) => {
  const b = ev.target.closest && ev.target.closest("[data-act]");
  if (!b) return;
  const name = b.dataset.name != null ? b.dataset.name : b.dataset.f;
  const fn = { saved: "downloadSaved", report: "downloadReport", code: "downloadCode" }[b.dataset.act];
  if (fn && window[fn]) window[fn](name);
});

function section(label, text, cls) {
  if (!text) return "";
  return `<div class="rsec ${cls||''}"><span class="rsec-label">${label}</span><div class="rsec-body">${escapeHtml(text)}</div></div>`;
}

function reportCard(r) {
  const time = (r.modified || "").replace("T", " ");
  if (r.kind === "report") {
    const isProj = String(r.language || "").toLowerCase() === "project";
    const dlCode = (!isProj && r.code_file)
      ? `<button class="dl" data-act="saved" data-f="${escapeHtml(r.code_file)}">Download code</button>` : "";
    const dlReport = `<button class="dl secondary" data-act="report" data-name="${escapeHtml(r.name)}">Download report</button>`;
    const codeSec = isProj
      ? `<div class="rsec"><span class="rsec-label">Files</span><div class="rsec-body" style="color:var(--muted)">Get the code for each file from the <b>Files</b> section below.</div></div>`
      : `<div class="rsec"><span class="rsec-label">Code</span><pre class="code">${escapeHtml(r.code || "")}</pre></div>`;
    return `<div class="report">
      <div class="report-head">
        <span class="tag code">${escapeHtml(isProj ? "Project" : (r.language || r.extension || "code"))}</span>
        <span class="report-name">${escapeHtml(r.code_file || r.name)}</span>
        <span class="report-time">${escapeHtml(time)}</span>
      </div>
      ${section("Overview", r.overview, "overview")}
      ${isProj ? "" : section("Errors found", r.errors, "errors")}
      ${section(isProj ? "Dependencies" : "Tech-stack review", r.tech_stack, "tech")}
      ${codeSec}
      ${diagramsSection(r.diagrams)}
      <div class="report-actions">${dlCode}${dlReport}</div>
    </div>`;
  }
  const body = r.content
    ? `<pre class="code">${escapeHtml(r.content)}</pre>`
    : `<p style="font-size:13px;color:var(--muted);margin:6px 0 0">${fmtSize(r.size)} · <button class="dl" data-act="saved" data-f="${escapeHtml(r.code_file||r.name)}">Download</button></p>`;
  return `<div class="report">
    <div class="report-head">
      <span class="tag ${escapeHtml(r.kind)}">${escapeHtml(r.ext || r.kind)}</span>
      <span class="report-name">${escapeHtml(r.name)}</span>
      <span class="report-time">${escapeHtml(time)}</span>
    </div>
    ${body}
  </div>`;
}

const _pending = {};
let _byName = {};   // every report (pending + saved + project) keyed by name

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
  saveFile(fn, r.code || "");
}

function _esc(s){ return String(s == null ? "" : s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;"); }
function _nl(s){ return _esc(s).replace(/\n/g,"<br>"); }
function buildReportHtml(name, r) {
  const lang = _esc(r.language || r.extension || "");
  const diagrams = String(r.diagrams || "");
  const mer = [...diagrams.matchAll(/```mermaid\n([\s\S]*?)```/g)].map(m => m[1]);
  const diagHtml = mer.length
    ? mer.map(b => `<pre class="mermaid">${_esc(b)}</pre>`).join("")
    : (diagrams ? `<pre>${_esc(diagrams)}</pre>` : "");
  const merScript = mer.length
    ? '<script src="https://cdnjs.cloudflare.com/ajax/libs/mermaid/10.9.1/mermaid.min.js"></script><script>try{mermaid.initialize({startOnLoad:true});}catch(e){}</script>'
    : "";
  return `<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>${_esc(name)} — CodeSnap report</title>
<style>
 body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;max-width:880px;margin:36px auto;padding:0 22px;color:#1d1d1f;line-height:1.6}
 h1{font-size:24px;margin:0 0 4px} h2{font-size:16px;margin:28px 0 6px;border-bottom:1px solid #ececef;padding-bottom:5px}
 .meta{color:#6e6e73;font-size:13px;margin:0 0 8px}
 pre{background:#f6f6f8;border:1px solid #e6e6ea;border-radius:10px;padding:12px 14px;overflow:auto;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:13px;white-space:pre-wrap}
 .err{color:#8a4a2c}
</style></head><body>
<h1>CodeSnap report</h1>
<p class="meta">${_esc(name)}${lang ? " · " + lang : ""}</p>
<h2>Overview</h2><p>${_nl(r.overview || "(none)")}</p>
<h2>Errors found</h2><p class="err">${_nl(r.errors || "None")}</p>
<h2>Code</h2><pre>${_esc(r.code || "")}</pre>
<h2>Tech-stack review</h2><p>${_nl(r.tech_stack || "n/a")}</p>
${diagHtml ? "<h2>Diagrams</h2>" + diagHtml : ""}
${merScript}
</body></html>`;
}
async function _svgToPng(svg) {
  return new Promise(resolve => {
    let w = 800, h = 450;
    const vb = svg.match(/viewBox="([\d.\- ]+)"/);
    if (vb) { const p = vb[1].trim().split(/\s+/).map(Number); if (p.length === 4 && p[2] && p[3]) { w = Math.ceil(p[2]); h = Math.ceil(p[3]); } }
    const img = new Image();
    img.onload = () => {
      const scale = 2, c = document.createElement("canvas");
      c.width = Math.max(1, w * scale); c.height = Math.max(1, h * scale);
      const ctx = c.getContext("2d"); ctx.scale(scale, scale);
      ctx.fillStyle = "#ffffff"; ctx.fillRect(0, 0, w, h);
      ctx.drawImage(img, 0, 0, w, h);
      resolve(c.toDataURL("image/png").split(",")[1]);
    };
    img.onerror = () => resolve(null);
    img.src = "data:image/svg+xml;base64," + btoa(unescape(encodeURIComponent(svg)));
  });
}
async function _reportImages(diagrams) {
  if (!window.mermaid) return [];
  const s = String(diagrams || "");
  const labels = [...s.matchAll(/\*\*(.+?)\*\*/g)].map(m => ({ pos: m.index, text: m[1].trim() }));
  const blocks = [...s.matchAll(/```mermaid\s*\n([\s\S]*?)```/g)].map(m => ({ pos: m.index, code: m[1].trim() }));
  const out = [];
  for (let i = 0; i < blocks.length; i++) {
    let label = "Diagram";
    for (const l of labels) { if (l.pos < blocks[i].pos) label = l.text; else break; }
    try {
      const { svg } = await mermaid.render("rpt_" + Date.now() + "_" + i, blocks[i].code);
      const png = await _svgToPng(svg);
      if (png) out.push({ label, data: png });
    } catch (e) { console.warn("diagram render failed", e); }
  }
  return out;
}
async function downloadReport(name) {
  const r = _byName[name] || _pending[name];
  const images = r ? await _reportImages(r.diagrams) : [];
  if (window.pywebview && window.pywebview.api && window.pywebview.api.save_report_docx) {
    const ok = await window.pywebview.api.save_report_docx(name, images);
    toast(ok ? ("Saved " + name + ".docx") : "Save cancelled.");
    return;
  }
  try {
    const res = await fetch("/api/report/docx", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name, images }) });
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const el = document.createElement("a");
    el.href = url; el.download = name + ".docx";
    document.body.appendChild(el); el.click(); el.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    toast("Report saved to Downloads.");
  } catch (e) { toast("Couldn't build the report."); }
}

function pendingCard(r) {
  const time = (r.modified || "").replace("T", " ");
  _pending[r.name] = r;
  const acts = `<button class="dl" data-act="code" data-name="${escapeHtml(r.name)}">Save code</button>`
    + `<button class="dl secondary" data-act="report" data-name="${escapeHtml(r.name)}">Save report</button>`;
  return `<div class="report pending">
    <div class="report-head">
      <span class="tag ready">Ready \u00b7 not saved</span>
      <span class="tag code">${escapeHtml(r.language || r.extension || "code")}</span>
      <span class="report-name">${escapeHtml(r.code_file || r.name)}</span>
      <span class="report-time">${escapeHtml(time)}</span>
    </div>
    ${section("Overview", r.overview, "overview")}
    ${section("Errors found", r.errors, "errors")}
    ${section("Tech-stack review", r.tech_stack, "tech")}
    <div class="rsec"><span class="rsec-label">Code</span>
      <pre class="code">${escapeHtml(r.code || "")}</pre></div>
    ${diagramsSection(r.diagrams)}
    <div class="report-actions">${acts}</div>
  </div>`;
}

async function loadReports() {
  const box = $("reports");
  const _sy = window.scrollY, _bt = box.scrollTop;          // preserve scroll across a refresh
  const _hadContent = box.children.length && !box.querySelector(".empty") && !box.querySelector("p");
  if (!_hadContent) box.innerHTML = `<p style="color:var(--muted)">Loading…</p>`;
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
  const all = [...pending, ...saved];
  const isProject = (r) => String(r.language || "").toLowerCase() === "project";
  _byName = {}; for (const r of all) _byName[r.name] = r;
  const nameToRep = _byName;

  // Names to hide from the top-level list.
  const hidden = new Set();
  // (a) While collecting in Project mode, every file captured AFTER entering the mode
  //     (not in the baseline) belongs to the project-in-progress — keep it in the Project
  //     panel, not down here. Baseline-based so it never lags the capture.
  if (_projMode && _projBaseline) {
    for (const r of all) if (!isProject(r) && !_projBaseline.has(r.name)) hidden.add(r.name);
  }

  // Render project cards FIRST. Only hide a project's members once its card has
  // rendered — so a bad project card can never make its members vanish too.
  // Build every card, tagging each with its timestamp so the final list stays in
  // chronological order (newest first) regardless of type — a single file captured
  // after a project sorts above it. Projects are built first only so we know which
  // member files to fold into their Files section.
  const rendered = [];   // { mod, html }
  for (const r of pending.concat(saved)) {
    if (!isProject(r)) continue;
    try {
      const card = projectCard(r, nameToRep, pending.indexOf(r) !== -1);
      rendered.push({ mod: r.modified || "", html: card });
      if (Array.isArray(r.members)) r.members.forEach(m => hidden.add(m.name));
    } catch (e) { console.error("project card failed", r, e); }
  }
  for (const r of pending) {
    if (isProject(r) || hidden.has(r.name)) continue;
    try { rendered.push({ mod: r.modified || "", html: pendingCard(r) }); } catch (e) { console.error("card failed", r, e); }
  }
  for (const r of saved) {
    if (isProject(r) || hidden.has(r.name)) continue;
    try { rendered.push({ mod: r.modified || "", html: reportCard(r) }); } catch (e) { console.error("card failed", r, e); }
  }
  rendered.sort((x, y) => (x.mod < y.mod ? 1 : x.mod > y.mod ? -1 : 0));   // newest first
  const html = rendered.map(x => x.html);
  box.innerHTML = html.length
    ? html.join("")
    : `<div class="empty">No results yet. Start a capture session to create your first report.</div>`;
  renderMermaid();
  box.querySelectorAll("details").forEach(d => d.addEventListener("toggle", () => { if (d.open) renderMermaid(); }));
  requestAnimationFrame(() => { window.scrollTo(0, _sy); box.scrollTop = _bt; });
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
    const cap = n.label && n.label.length ? n.label[0].toUpperCase() + n.label.slice(1) : n.label;
    return `<span class="${cls}">${escapeHtml(cap)}</span>${arrow}`;
  }).join("");
}

function renderStatus(events) {
  const box = $("statusFeed");
  if (!events.length) { box.innerHTML = ""; return; }
  const shown = events.filter(e => e.kind !== "tool").slice(-4);
  if (!shown.length) { box.innerHTML = ""; return; }
  box.innerHTML = shown.map(e =>
    `<div class="ev"><span class="ev-dot"></span>${escapeHtml(e.msg)}</div>`).join("");
  box.scrollTop = box.scrollHeight;
}

async function pollStatus() {
  if (pollStatus.pending) return;
  pollStatus.pending = true;
  const request = pollStatus.sequence = (pollStatus.sequence || 0) + 1;
  try {
    const r = await fetch("/api/session/status");
    const d = await r.json();
    if (request !== pollStatus.sequence) return;
    renderStatus(d.events || []);
    renderFlow(d.events || []);
    setRunning(d.running);
    const evs = d.events || [];
    const analyzing = d.running && evs.some(e => e.kind === "tool") && !evs.some(e => e.kind === "done" || e.kind === "end");
    if (analyzing) startAnalyzing(); else stopAnalyzing();
    const revision = JSON.stringify(d.events || []);
    if (revision !== lastEventCount) {
      lastEventCount = revision;
      loadReports();
      if (typeof loadProgram === "function" && _program) loadProgram(true);
    }
  } catch (e) {}
  finally { pollStatus.pending = false; }
}

function setRunning(running) {
  sessionRunning = running;
  const tt = $("singleToggle");
  if (tt) tt.disabled = running;
  const b = $("startBtn");
  $("status").textContent = running ? "Session running" : "Ready";
  b.textContent = running ? "Stop session" : "Start capture";
  b.classList.toggle("stop", running);
  $("statusFeed").style.display = running ? "block" : "none";
  $("devflow").style.display = running ? "flex" : "none";
  const fl = $("flowLabel"); if (fl) fl.style.display = running ? "flex" : "none";
}

// Pause-tolerance slider: max position (61) = Manual (never auto-stop -> idle_stop 0)
(function () {
  const tol = $("toleranceSlider"), lbl = $("toleranceLabel");
  if (!tol || !lbl) return;
  const upd = () => { lbl.textContent = (parseInt(tol.value, 10) >= 61) ? "Manual" : tol.value + "s"; };
  tol.addEventListener("input", upd); upd();
})();
function idleStopValue() {
  const tol = $("toleranceSlider");
  if (!tol) return null;
  const v = parseInt(tol.value, 10);
  return v >= 61 ? 0 : v;          // 0 = manual / never auto-stop
}

$("startBtn").addEventListener("click", async () => {
  if (sessionRunning) {
    await fetch("/api/session/stop", { method: "POST" });
    toast("Session stopped.");
  } else {
    const single = false;   // single-agent backup available via --single, not exposed in the UI
    const idle = idleStopValue();
    const params = new URLSearchParams();
    if (single) params.set("single", "true");
    if (idle !== null) params.set("idle_stop", String(idle));
    if (pickedRegion) params.set("region", pickedRegion);
    if (_projMode) params.set("project_mode", "true");
    if (_view === "review") {
      if (!_program) { toast("Pick or create a program first."); return; }
      params.set("program", _program);
    }
    if (_view === "review" && _captureKind !== "code") params.set("capture_kind", _captureKind);
    const captureDisplay = pickedRegion ? pickedRegionDisplay : _display;
    if (captureDisplay) params.set("display", captureDisplay);
    const qs = params.toString();
    await fetch("/api/session/start" + (qs ? "?" + qs : ""), { method: "POST" });
    const manual = idle === 0;
    toast((single ? "Single-agent (backup)" : "Team") + " session launched — switch to your editor and press Cmd+Shift+1"
      + (manual ? ". Manual mode: it won't auto-stop, press Cmd+Shift+1 again to finish." : "."));
  }
  pollStatus();
});

loadReports();
setInterval(pollStatus, 1500);
pollStatus();
window.addEventListener("resize", () => { if (sessionRunning) renderFlow(lastFlowEvents); });
window.downloadCode = downloadCode;
window.downloadReport = downloadReport;


// ── Pick code area (drag-select over a screenshot) ───────────────────────────
let pickedRegionDisplay = "";
let pickedRegion = null;   // "L,T,W,H" fractions string, or null = full screen

(function () {
  const modal = $("regionModal"), stage = $("regionStage"), shot = $("regionShot");
  const sel = $("regionSel"), msg = $("regionOverlayMsg");
  const useBtn = $("regionUse"), statusEl = $("regionStatus"), clearBtn = $("clearAreaBtn");
  if (!modal) return;

  let box = null, active = false;   // box = selection coords; active = mouse button held
  let marginMode = false, marginX = null, spacingReference = null;
  const marginLine = $("sourceMarginLine"), marginBtn = $("regionMargin"), spacingHint = $("regionSpacingHint");

  function openModal() { modal.style.display = "flex"; }
  function closeModal() { modal.style.display = "none"; box = null; active = false; }

  async function loadShot(delay) {
    shot.style.opacity = ".3";
    msg.textContent = delay ? "Bring your code to the front… snapping in " + delay + "s" : "Loading screenshot…";
    msg.style.display = "block";
    if (delay) { for (let s = delay; s > 0; s--) { msg.textContent = "Bring your code to the front… " + s; await new Promise(r => setTimeout(r, 1000)); } }
    try {
      const res = await fetch("/api/screen.png?notify=1" + (_display ? "&display=" + _display : "") + "&t=" + Date.now());
      if (!res.ok) throw new Error("screenshot failed");
      _shotDisplay = res.headers.get("X-CodeSnap-Display") || "";
      spacingReference = res.headers.get("X-CodeSnap-Spacing-Reference");
      const blob = await res.blob();
      shot.src = URL.createObjectURL(blob);
      shot.onload = () => { shot.style.opacity = "1"; msg.style.display = "none"; };
    } catch (e) {
      msg.textContent = "Couldn't grab the screen — grant Screen Recording permission and retry.";
    }
    sel.style.display = "none"; useBtn.disabled = true; box = null; active = false;
    marginMode=false; marginX=null; if (marginLine) marginLine.style.display="none";
  }

  function imgRect() { return shot.getBoundingClientRect(); }

  function drawSel() {
    if (!box) { sel.style.display = "none"; return; }
    const x = Math.min(box.x0, box.x1), y = Math.min(box.y0, box.y1);
    const w = Math.abs(box.x1 - box.x0), h = Math.abs(box.y1 - box.y0);
    const sr = stage.getBoundingClientRect();
    sel.style.display = "block";
    sel.style.left = (x - sr.left) + "px"; sel.style.top = (y - sr.top) + "px";
    sel.style.width = w + "px"; sel.style.height = h + "px";
    useBtn.disabled = (w < 8 || h < 8);
  }

  function drawMargin(x) {
    const sr = stage.getBoundingClientRect();
    marginLine.style.cssText = `display:block;position:absolute;width:2px;background:#ef4444;pointer-events:none;z-index:3;left:${x-sr.left}px;top:${Math.min(box.y0,box.y1)-sr.top}px;height:${Math.abs(box.y1-box.y0)}px`;
  }

  stage.addEventListener("mousedown", (e) => {
    if (marginMode && box) {
      const left=Math.min(box.x0,box.x1), right=Math.max(box.x0,box.x1);
      const top=Math.min(box.y0,box.y1), bottom=Math.max(box.y0,box.y1);
      if (e.clientX < left || e.clientX >= right || e.clientY < top || e.clientY >= bottom) { toast("Move the red line inside the selected code area, then click to lock it."); return; }
      marginX=e.clientX; marginMode=false;
      drawMargin(marginX);
      spacingHint.textContent="Red line locked at the start of the code, before any spaces. Choose Use this area to save. Reset after moving, zooming or scrolling sideways.";
      e.preventDefault(); return;
    }
    marginX=null; if (marginLine) marginLine.style.display="none";
    active = true;
    box = { x0: e.clientX, y0: e.clientY, x1: e.clientX, y1: e.clientY };
    drawSel(); e.preventDefault();
  });
  window.addEventListener("mousemove", (e) => {
    if (marginMode && box) {
      const left=Math.min(box.x0,box.x1), right=Math.max(box.x0,box.x1);
      const top=Math.min(box.y0,box.y1), bottom=Math.max(box.y0,box.y1);
      if (e.clientX >= left && e.clientX < right && e.clientY >= top && e.clientY < bottom) drawMargin(e.clientX);
      else marginLine.style.display="none";
    } else if (active && box) { box.x1 = e.clientX; box.y1 = e.clientY; drawSel(); }
  });
  window.addEventListener("mouseup", () => { active = false; });   // box stays put after release

  function fractions() {
    const r = imgRect();
    const x = Math.min(box.x0, box.x1), y = Math.min(box.y0, box.y1);
    const w = Math.abs(box.x1 - box.x0), h = Math.abs(box.y1 - box.y0);
    const L = clamp01((x - r.left) / r.width), T = clamp01((y - r.top) / r.height);
    const W = clamp01(w / r.width), H = clamp01(h / r.height);
    return [L, T, Math.min(W, 1 - L), Math.min(H, 1 - T)];
  }
  function clamp01(v) { return Math.max(0, Math.min(1, v)); }

  $("pickAreaBtn").addEventListener("click", () => { openModal(); loadShot(3); });
  $("regionRetake").addEventListener("click", () => loadShot(3));
  if (marginBtn) marginBtn.addEventListener("click", () => {
    if (!box || useBtn.disabled) { toast("Draw the source area first."); return; }
    marginMode=true;
    drawMargin(marginX === null ? Math.min(box.x0,box.x1) : marginX);
    spacingHint.textContent="Move your mouse over the code: the red line follows it. Line it up where each line can begin, before any spaces, then click to lock it. Keep the editor scrolled fully left.";
  });
  $("regionCancel").addEventListener("click", closeModal);
  $("regionUse").addEventListener("click", async () => {
    if (!box) return;
    const f = fractions();
    const region = f.join(",");
    const settings={region, display: _shotDisplay || _display};
    if (marginX !== null) {
      const r=imgRect();
      settings.spacing_origin=(((marginX-r.left)/r.width)-Number(f[0]))/Number(f[2]);
      settings.spacing_reference=spacingReference;
    } else settings.clear_spacing=true;
    try {
      await _json("/api/session/settings", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(settings) });
    } catch (error) { toast(error.message); return; }
    pickedRegion = region;
    pickedRegionDisplay = _shotDisplay || _display;
    statusEl.textContent = marginX !== null ? "Code area and source margin set" : "Capturing a selected area only — source margin unconfirmed";
    clearBtn.style.display = "";
    closeModal();
    toast("Code area set — the next capture will use this box on the selected screen.");
  });
  (async () => {
    try {
      const saved = await _json("/api/session/settings");
      if (saved && saved.region && !pickedRegion) {
        pickedRegion = saved.region;
        pickedRegionDisplay = saved.display ? String(saved.display) : (_display || "");
        statusEl.textContent = saved.margin ? "Code area and source margin set" : "Capturing a selected area only — source margin unconfirmed";
        clearBtn.style.display = "";
      }
    } catch (error) {}
  })();
  clearBtn.addEventListener("click", async () => {
    try {
      await _json("/api/session/settings", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({region: null, display: _display}) });
    } catch (error) { toast(error.message); return; }
    pickedRegion = null;
    pickedRegionDisplay = "";
    statusEl.textContent = "Capturing the full screen";
    clearBtn.style.display = "none";
  });
})();


// ── Settings: Liquid Glass + Dark mode (persisted) ───────────────────────────
(function () {
  const body = document.body;
  if (localStorage.getItem("cc-glass") === "0") body.classList.remove("glass");
  if (localStorage.getItem("cc-dark") === "1") body.classList.add("dark");
  const setGlass = $("setGlass"), setDark = $("setDark"), modal = $("settingsModal");
  if (setGlass) setGlass.checked = body.classList.contains("glass");
  if (setDark)  setDark.checked  = body.classList.contains("dark");
  if ($("settingsBtn")) $("settingsBtn").addEventListener("click", () => { if (modal) modal.style.display = "flex"; });
  if ($("settingsClose")) $("settingsClose").addEventListener("click", () => { if (modal) modal.style.display = "none"; });
  if (modal) modal.addEventListener("click", (e) => { if (e.target === modal) modal.style.display = "none"; });
  if (setGlass) setGlass.addEventListener("change", () => {
    body.classList.toggle("glass", setGlass.checked);
    localStorage.setItem("cc-glass", setGlass.checked ? "1" : "0");
  });
  if (setDark) setDark.addEventListener("change", () => {
    body.classList.toggle("dark", setDark.checked);
    localStorage.setItem("cc-dark", setDark.checked ? "1" : "0");
  });
})();


// Viewing a report may need the deep analysis to run first; that is a POST, never a side effect of the GET.
["progReportHtml", "progReportDocx", "progReportPdf", "progReportZip"].forEach(id => {
  const el = $(id); if (!el) return;
  el.addEventListener("click", async (ev) => {
    const href = el.getAttribute("href") || "";
    const base = href.replace(/\.(html|docx|pdf|zip)$/, "");
    if (el.classList.contains("disabled") || !base || base === href) return;
    ev.preventDefault();
    try { await fetch(`${base}/prepare`, { method: "POST" }); } catch (e) {}
    if (el.getAttribute("target") === "_blank") window.open(href, "_blank", "noopener"); else window.location.assign(href);
  });
});

// ── First-run API key onboarding ─────────────────────────────────────────────
async function checkApiKey() {
  const banner = $("keyBanner"); if (!banner) return;
  try {
    const r = await fetch("/api/key/status");
    const j = await r.json();
    banner.style.display = j.has_key ? "none" : "flex";
  } catch (e) { /* leave hidden on error */ }
}
if ($("keySave")) $("keySave").addEventListener("click", async () => {
  const v = ($("keyInput").value || "").trim();
  if (!v) { toast("Paste your key first."); return; }
  try {
    const r = await fetch("/api/key", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ value: v }) });
    const j = await r.json();
    if (j.ok) { $("keyBanner").style.display = "none"; $("keyInput").value = ""; toast("API key saved — you're ready to capture."); }
    else toast(j.error || "Couldn't save that key.");
  } catch (e) { toast("Couldn't reach the server."); }
});
checkApiKey();


// ── Project mode: pick captured files, build a cross-file dependency map ──────
function _attr(v){ return String(v||"").replace(/&/g,"&amp;").replace(/"/g,"&quot;").replace(/</g,"&lt;"); }
async function loadProjectPicker() {
  const box = $("projFiles"); if (!box) return;
  box.innerHTML = "Loading…";
  let items = [];
  try {
    const saved = (await (await fetch("/api/reports")).json()).reports || [];
    const pend  = (await (await fetch("/api/pending")).json()).reports || [];
    items = [...pend, ...saved].filter(r => r.kind === "report" && r.code &&
                                            String(r.language||"").toLowerCase() !== "project");
  } catch (e) {}
  if (!items.length) {
    box.innerHTML = `<p style="color:var(--muted);font-size:13px;margin:0">No captured files yet — capture some files first, then come back.</p>`;
    updateProjBuild(); return;
  }
  box.innerHTML = items.map(r => {
    const fn = r.code_file || (r.name + "." + (r.extension || "txt"));
    return `<label class="proj-file">
      <input type="checkbox" class="proj-check" data-report="${_attr(r.name)}">
      <input type="text" class="proj-name" value="${_attr(fn)}" spellcheck="false">
    </label>`;
  }).join("");
  box.querySelectorAll(".proj-check").forEach(c => c.addEventListener("change", updateProjBuild));
  updateProjBuild();
}
function updateProjBuild() {
  const n = document.querySelectorAll(".proj-check:checked").length;
  const btn = $("projBuild"); if (btn) btn.disabled = n < 2;
  const hint = $("projHint"); if (hint) hint.textContent = n < 2 ? "Select 2 or more captured files." : (n + " files selected.");
}
if ($("projPickBtn")) $("projPickBtn").addEventListener("click", () => {
  const p = $("projPicker"); const open = p.style.display === "none";
  p.style.display = open ? "block" : "none";
  if (open) loadProjectPicker();
});
if ($("projBuild")) $("projBuild").addEventListener("click", async () => {
  const items = [];
  document.querySelectorAll(".proj-file").forEach(row => {
    const chk = row.querySelector(".proj-check");
    if (chk && chk.checked) items.push({ report: chk.dataset.report, filename: (row.querySelector(".proj-name").value || "").trim() });
  });
  if (items.length < 2) return;
  const btn = $("projBuild"); btn.disabled = true; btn.textContent = "Analyzing…";
  try {
    const res = await fetch("/api/project/analyze", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ items }) });
    const jr = await res.json();
    if (jr.ok) { toast("Project map built — see Recent results."); $("projPicker").style.display = "none"; loadReports(); }
    else toast(jr.error || "Couldn't build the project map.");
  } catch (e) { toast("Couldn't reach the server."); }
  btn.disabled = false; btn.textContent = "Build map";
});


// ── Clear reports ────────────────────────────────────────────────────────────
if ($("clearBtn")) {
  let _clearArmed = false, _clearTimer = null;
  $("clearBtn").addEventListener("click", async () => {
    const b = $("clearBtn");
    if (!_clearArmed) {                       // first click: arm (confirm() isn't reliable in the app window)
      _clearArmed = true; b.textContent = "Confirm clear?";
      _clearTimer = setTimeout(() => { _clearArmed = false; b.textContent = "Clear"; }, 3000);
      return;
    }
    clearTimeout(_clearTimer); _clearArmed = false; b.textContent = "Clear";
    try {
      const r = await fetch("/api/reports/clear", { method: "POST" });
      const j = await r.json();
      toast("Cleared " + (j.removed || 0) + " file(s)."
        + (j.failed ? "  " + j.failed + " were busy — click Clear again." : ""));
      loadReports();
    } catch (e) { toast("Couldn't clear reports."); }
  });
}


// ── Project mode: live-collect captured files while you capture, then map ─────
let _projMode = false, _projBaseline = new Set(), _projTimer = null, _projFiles = [];
async function _fetchProjReports() {
  let items = [];
  try {
    const saved = (await (await fetch("/api/reports")).json()).reports || [];
    const pend  = (await (await fetch("/api/pending")).json()).reports || [];
    items = [...pend, ...saved].filter(r => r.kind === "report" && r.code &&
                                            String(r.language||"").toLowerCase() !== "project");
  } catch (e) {}
  return items;
}
async function refreshProjLive() {
  if (!_projMode) return;
  const all = await _fetchProjReports();
  _projFiles = all.filter(r => !_projBaseline.has(r.name));
  const box = $("projLiveFiles"); if (!box) return;
  box.innerHTML = _projFiles.length ? _projFiles.map(r => {
    const fn = r.code_file || (r.name + "." + (r.extension || "txt"));
    return `<div class="proj-file"><input type="text" class="proj-name" data-report="${_attr(r.name)}" value="${_attr(fn)}" spellcheck="false"></div>`;
  }).join("") : `<p style="color:var(--muted);font-size:13px;margin:0">No files captured yet — capture your first file.</p>`;
  const cnt = $("projLiveCount"); if (cnt) cnt.textContent = _projFiles.length + " file(s) captured.";
  const btn = $("projLiveBuild"); if (btn) btn.disabled = _projFiles.length < 2;
}
async function setProjectMode(on) {
  _projMode = on;
  if ($("projLive"))  $("projLive").style.display = on ? "block" : "none";
  if ($("projPicker")) $("projPicker").style.display = "none";
  document.querySelectorAll("#projSeg .seg-opt").forEach(b =>
    b.classList.toggle("active", (b.dataset.mode === "project") === on));
  if (sessionRunning) {           // relaunch so the worker actually switches mode (mode is fixed at launch)
    try {
      await fetch("/api/session/stop", { method: "POST" });
      const params = new URLSearchParams();
      const idle = idleStopValue(); if (idle !== null) params.set("idle_stop", String(idle));
      if (pickedRegion) params.set("region", pickedRegion);
      const screen = pickedRegion ? pickedRegionDisplay : _display;
      if (screen) params.set("display", screen);
      if (on) params.set("project_mode", "true");
      await fetch("/api/session/start" + (params.toString() ? "?" + params.toString() : ""), { method: "POST" });
      pollStatus();
    } catch (e) {}
  }
  if (on) {
    const all = await _fetchProjReports();
    _projBaseline = new Set(all.map(r => r.name));   // only files captured AFTER now count toward this project
    await refreshProjLive();
    if (!_projTimer) _projTimer = setInterval(refreshProjLive, 3000);
    toast("Project mode on — capture your files one at a time.");
  } else if (_projTimer) {
    clearInterval(_projTimer); _projTimer = null;
  }
}
document.querySelectorAll("#projSeg .seg-opt").forEach(b =>
  b.addEventListener("click", () => setProjectMode(b.dataset.mode === "project")));
if ($("projLiveBuild")) $("projLiveBuild").addEventListener("click", async () => {
  const items = [];
  $("projLiveFiles").querySelectorAll(".proj-name").forEach(inp => {
    items.push({ report: inp.dataset.report, filename: (inp.value || "").trim() });
  });
  if (items.length < 2) return;
  const btn = $("projLiveBuild"); btn.disabled = true; btn.textContent = "Analyzing…";
  try {
    const r = await fetch("/api/project/analyze", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ items }) });
    const j = await r.json().catch(() => ({}));
    if (r.ok && j.ok) {
      // reset the collection for the next project; the just-built project (language
      // "Project") is NOT in this baseline, so it stays visible in Recent results.
      const done = await _fetchProjReports();
      _projBaseline = new Set(done.map(x => x.name));
      await refreshProjLive();
      await loadReports();
      toast("Project map built — see Recent results.");
    } else {
      const msg = j.error || ("Build failed (HTTP " + r.status + ")");
      toast(msg);
      const st = $("projLiveCount"); if (st) st.textContent = msg;   // keep the reason visible
    }
  } catch (e) { toast("Couldn't reach the server — is it running?"); }
  btn.disabled = false; btn.textContent = "Build map";
});

if ($("projPickBtn")) $("projPickBtn").style.display = "none"; // retired on load — multiple files require Project mode


// ── Downloads: native Save dialog in the app window, blob fallback in a browser ──
async function saveFile(filename, content) {
  try {
    if (window.pywebview && window.pywebview.api && window.pywebview.api.save_text) {
      const ok = await window.pywebview.api.save_text(filename, content || "");
      toast(ok ? ("Saved " + filename) : "Save cancelled.");
      return;
    }
  } catch (e) {}
  _download(filename, content || "", "text/plain");   // real browser (dev)
  toast("Saved " + filename + " to Downloads.");
}
async function downloadSaved(name) {
  // `name` is the code filename. The code is already loaded in the report data, so
  // save that directly (works for pending, saved, and project-member files alike).
  const r = Object.values(_byName).find(x => x && (x.code_file === name || x.name === name));
  if (r && r.code) { await saveFile(name, r.code); return; }
  // Fallback: fetch the file from reports/ on disk — but never save an error body.
  try {
    const res = await fetch("/api/download/" + encodeURIComponent(name));
    if (!res.ok) { toast("Couldn't find that code file."); return; }
    await saveFile(name, await res.text());
  } catch (e) { toast("Couldn't load that file."); }
}
window.downloadSaved = downloadSaved;
window.saveFile = saveFile;


// ── Project report: one container + a dropdown of its member file reports ────
function projectCard(r, nameToRep, isPending) {
  const inner = isPending ? pendingCard(r) : reportCard(r);
  const members = Array.isArray(r.members) ? r.members : [];
  const memberHtml = members.map(m => {
    const mr = nameToRep[m.name];
    const label = escapeHtml(m.filename || m.name);
    const content = mr && mr.kind === "report" ? reportCard(mr)
      : `<p style="color:var(--muted);font-size:13px;padding:8px 4px">${label} — report no longer available</p>`;
    return `<details class="proj-member"><summary>${label}</summary>${content}</details>`;
  }).join("");
  return `<div class="project-report">${inner}
    <details class="proj-files"><summary>Files (${members.length})</summary>
      <div class="proj-files-body">${memberHtml}</div>
    </details></div>`;
}


// ── Program model: pick/create a program; every capture is added to it ──────
const PROG_KEY = "codesnap.program";
function _progStore(v) {
  try { if (v === undefined) return localStorage.getItem(PROG_KEY) || ""; localStorage.setItem(PROG_KEY, v); } catch (e) {}
  return "";
}
async function _json(url, opts) {
  const r = await fetch(url, opts);
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.error || j.detail || ("HTTP " + r.status));
  return j;
}
async function loadPrograms(select) {
  let list = [];
  try { list = (await _json("/api/programs")).programs || []; } catch (e) {}
  const sel = $("progSelect");
  sel.innerHTML = `<option value="">Single files (no program)</option>` +
    list.map(p => `<option value="${_attr(p.slug)}">${escapeHtml(p.name)}</option>`).join("");
  const want = select !== undefined ? select : _progStore();
  _program = list.some(p => p.slug === want) ? want : "";
  sel.value = _program;
  _progStore(_program);
  await loadProgram();
}
const STATE = {
  waiting: ["Waiting", "wait"], reading: ["Reading", "busy"], reviewing: ["Reviewing", "busy"],
  needs_recapture: ["Needs recapture", "bad"], failed: ["Couldn't read", "bad"], done: ["Done", "ok"],
};
const ISSUE = { cut: "lines cut off at the edge of the screen", break: "a gap between two screens, so lines may be missing",
  rows: "a line may have been skipped or added", mismatch: "some characters may be misread", partial: "the start or end of the file looks missing",
  compile: "it doesn't compile as read", model: "the reviewer found text that can't be right" };
const FIXED = { cut: "cut-off lines", break: "gaps between screens", rows: "skipped or extra lines", mismatch: "misread characters",
  partial: "missing start or end", compile: "compile errors", model: "unreadable text" };
function _issues(list) {
  const kinds = new Set(list.map(i => i.kind));
  const txt = list.filter(i => !(i.kind === "partial" && kinds.has("cut"))).map(i => (ISSUE[i.kind] || i.reason) + _lines(i.lines)).join("; ");
  return escapeHtml(txt.charAt(0).toUpperCase() + txt.slice(1));
}
function _lines(ls) { return ls && ls.length ? ` (line${ls.length > 1 || String(ls[0]).includes("–") ? "s" : ""} ${ls.slice(0, 6).join(", ")}${ls.length > 6 ? "…" : ""})` : ""; }
function renderProgress(d) {
  const p = d.progress || {};
  const box = $("progProgress");
  if (!p.total) { box.innerHTML = `<div class="pp-head"><b>No files yet</b><span>Start a capture — each start/stop becomes one file.</span></div>`; return; }
  const busy = p.reading + p.reviewing + p.waiting;
  const seg = (n, cls) => n ? `<i class="${cls}" style="flex:${n}"></i>` : "";
  const bits = [];
  if (p.reading) bits.push(`${p.reading} reading`);
  if (p.reviewing) bits.push(`${p.reviewing} being reviewed`);
  if (p.waiting) bits.push(`${p.waiting} waiting`);
  const attn = p.needs_recapture + p.failed;
  box.innerHTML = `<div class="pp-head">
      <b>${p.finished} of ${p.total} files processed</b>
      <span>${busy ? bits.join(" · ") + ` — ${p.to_go} to go` : "Nothing left to process"}${attn ? ` · <em>${attn} need${attn > 1 ? "" : "s"} recapture</em>` : ""}</span>
    </div>
    <div class="pp-bar">${seg(p.done, "ok")}${seg(p.needs_recapture + p.failed, "bad")}${seg(p.reviewing + p.reading, "busy")}${seg(p.waiting, "wait")}</div>`;
}
function _fileRow(a, pendingFor) {
  const st = a.rebuild ? "reading" : pendingFor ? pendingFor.state : a.state;
  const [label, cls] = a.rebuild ? ["Processing again", "busy"] : STATE[st] || [a.status, ""];
  const rc = a.recapture;
  let note = "";
  if (a.rebuild) note = `<div class="pf-note busy">${escapeHtml(a.rebuild.stage)}${a.rebuild.total ? ` — ${a.rebuild.done}/${a.rebuild.total} screenshots read` : ""}.</div>`;
  else if (pendingFor && st === "failed") note = `<div class="pf-note bad">Recapture couldn't be read: ${escapeHtml((pendingFor.pending || {}).error || "Reading failed.")} <button class="btn-link" data-act="retry" data-artifact-id="${pendingFor.id}" type="button">Retry</button></div>`;
  else if (pendingFor) note = `<div class="pf-note busy">Recapture in progress${pendingFor.pending && pendingFor.pending.frames ? ` — read ${pendingFor.pending.read || 0} of ${pendingFor.pending.frames} screenshots` : ""}.</div>`;
  else if (rc && rc.result === "fixed") note = `<div class="pf-note ok">✓ Fixed by the recapture (now v${rc.version})${rc.fixed.length ? " — no more " + [...new Set(rc.fixed.filter(i => !(i.kind === "partial" && rc.fixed.some(j => j.kind === "cut"))).map(i => FIXED[i.kind] || "problems"))].join(" or ") : ""}.</div>`;
  else if (rc && rc.result === "still") note = `<div class="pf-note bad">Recaptured as v${rc.version}, but it still needs work: ${_issues(rc.remaining).toLowerCase()}. <button class="btn-link" data-act="review-lines" type="button">Review with screenshots</button> <button class="btn-link" data-act="add" type="button">Capture those lines</button></div>`;
  else if (st === "needs_recapture") note = `<div class="pf-note bad">${_issues(a.quality.issues)}. <button class="btn-link" data-act="review-lines" type="button">Review with screenshots</button> <button class="btn-link" data-act="add" type="button">Capture those lines</button></div>`;
  else if (st === "failed" && a.pending && a.pending.error) note = `<div class="pf-note bad">${escapeHtml(a.pending.error)} <button class="btn-link" data-act="retry" type="button">Retry</button></div>`;
  const reading = st === "reading" && a.pending && a.pending.frames ? ` · ${a.pending.read || 0}/${a.pending.frames}` : "";
  return `
    <details class="prog-file" data-id="${a.id}" data-name="${_attr(a.name)}">
      <summary>
        <span class="pf-name">${escapeHtml(a.name)}</span>
        <span class="pf-meta">${escapeHtml(a.language || a.artifact_type || "")}${a.version > 1 ? " · v" + a.version : ""}</span>
        <span class="pf-state ${cls}">${label}${reading}</span>
        <span class="pf-menu" tabindex="0">⋯<span class="pf-acts">
          <button class="btn-link" data-act="rename" type="button">Rename</button>
          <button class="btn-link" data-act="remove" type="button">Remove from analysis</button>
          ${a.status === "captured" ? "" : `<button class="btn-link" data-act="recapture" type="button">Recapture</button>
          ${a.artifact_type === "ui_screen" ? "" : `<button class="btn-link" data-act="rebuild" type="button">Rebuild saved capture</button>`}
          <button class="btn-link" data-act="add" type="button">Add screenshots</button>`}
        </span></span>
        ${note}
      </summary>
      <div class="pf-detail"></div>
    </details>`;
}
let _progSig = "";
const _localRebuilds = new Map();
function _programRenderSignature(rows, recaps, d) {
  return JSON.stringify([rows.map(a => [a.id, a.name, a.language, a.artifact_type, a.version, a.state,
    a.recapture, a.quality, a.rebuild, a.pending]), recaps, d.recapture_target, d.session_running,
    d.waiting, d.coverage, d.revision]);
}
async function loadProgram(poll) {
  const body = $("progBody");
  if (!_program) { body.style.display = "none"; $("progSub").textContent = "Pick a program, or create one."; return; }
  const program = _program;
  if (poll && loadProgram.pending && loadProgram.pending.program === program) return;
  const request = loadProgram.sequence = (loadProgram.sequence || 0) + 1;
  const pending = loadProgram.pending = {program, request};
  let d;
  try { d = await _json("/api/programs/" + encodeURIComponent(program)); }
  catch (e) {
    if (program === _program && request === loadProgram.sequence) {
      if (!poll) toast(e.message);
      scheduleProgramPoll({session_running: true});
    }
    return;
  }
  finally { if (loadProgram.pending === pending) loadProgram.pending = null; }
  if (program !== _program || request !== loadProgram.sequence) return;
  const revision = `${program}:${d.revision || ""}`;
  const changed = loadProgram.revision !== revision;
  loadProgram.revision = revision;
  body.style.display = "block";
  $("progSub").textContent = d.program.description || `${d.progress.total} file${d.progress.total === 1 ? "" : "s"} in this program.`;
  d.artifacts.forEach(a => {
    const local = _localRebuilds.get(`${_program}:${a.name}`);
    if (local && !a.rebuild) {
      const p = d.progress;
      if (p[a.state] > 0) p[a.state]--;
      if (["done", "needs_recapture", "failed"].includes(a.state)) { p.finished--; p.to_go++; }
      p.reading++;
      p.pct = p.total ? Math.round(100 * p.finished / p.total) : 0;
      a.rebuild = local;
      a.state = "reading";
    }
  });
  renderProgress(d);
  const recaps = {};
  d.artifacts.forEach(a => { const t = a.pending && a.pending.recapture_of; if (t && d.artifacts.some(x => x.name === t && x.id !== a.id)) recaps[t] = a; });
  const rows = d.artifacts.filter(a => !(a.pending && recaps[a.pending.recapture_of] === a));
  const sig = _programRenderSignature(rows, recaps, d);
  scheduleProgramPoll(d);
  if (poll && sig === _progSig) return;
  _progSig = sig;
  const open = new Set([...document.querySelectorAll("#progFiles .prog-file[open]")].map(x => x.dataset.id));
  $("progFiles").innerHTML = rows.length ? rows.map(a => _fileRow(a, recaps[a.name])).join("")
    : `<p class="project-hint" style="margin:0">No files yet — start a capture. Each start/stop becomes one file.</p>`;
  renderCaptureBar(d);
  document.querySelectorAll("#progFiles [data-act]").forEach(b => b.addEventListener("click", ev => {
    ev.preventDefault(); ev.stopPropagation(); fileAction(b.closest(".prog-file"), b.dataset.act, b.dataset.artifactId);
  }));
  document.querySelectorAll("#progFiles .prog-file").forEach(el => {
    el.dataset.program = program;
    el.addEventListener("toggle", () => { if (el.open) loadArtifact(el); });
    if (open.has(el.dataset.id)) el.open = true;
  });
  const c = d.coverage;
  const mc = c.missing_counts || {};
  const nMiss = (mc.missing_code || 0) + (mc.external || 0);
  $("progMissingLabel").textContent = nMiss ? `${nMiss} things referenced but not captured (${mc.missing_code || 0} code, ${mc.external || 0} external)` : "Nothing referenced is missing";
  const order = { missing_code: 0, external: 1, library: 2 };
  const catLabel = { missing_code: "code", external: "external", library: "library" };
  const shown = c.missing.filter(m => m.category !== "library").sort((a, b) => order[a.category] - order[b.category]);
  $("progMissing").innerHTML = shown.length ? shown.slice(0, 80).map(m => {
    const by = (m.referenced_by || []).slice(0, 2).map(r => r.artifact || r.name).join(", ");
    return `<div class="pm"><span class="pm-cat ${_attr(m.category)}">${catLabel[m.category] || m.category}</span> <b>${escapeHtml(m.name)}</b> <small>${escapeHtml(m.kind)}${by ? " · used in " + escapeHtml(by) : ""}</small></div>`;
  }).join("") : "";
  if (poll && !changed) return;
  if ($("progFlowsBox").open) loadProgramFlows();
  if ($("progMapBox").open) loadProgramMap();
  if ($("progSecBox").open) loadProgramFindings();
  if ($("progAssessBox").open) loadAssessment();
  if ($("progDiagBox").open) loadDiagrams();
  if ($("progUiBox").open) loadUiReview();
  if ($("progFixBox").open) loadCorrections();
  const rb = `/api/programs/${encodeURIComponent(_program)}/report`;
  $("progReportHtml").href = `${rb}.html`;
  $("progReportDocx").href = `${rb}.docx`;
  $("progReportPdf").href = `${rb}.pdf`;
  $("progReportZip").href = `${rb}.zip`;
}
let _progPoll = null;
function scheduleProgramPoll(d) {
  if (_progPoll) clearTimeout(_progPoll);
  const busy = d.progress && (d.progress.to_go > 0) || d.session_running || d.recapture_target;
  _progPoll = setTimeout(() => { _progPoll = null; if (_view === "review" && _program && !document.hidden) loadProgram(true); else scheduleProgramPoll(d); }, busy ? 3000 : 10000);
}
let _display = "", _shotDisplay = "";
async function loadDisplays() {
  const sel = $("displaySelect");
  let list = [];
  try { list = (await _json("/api/displays")).displays || []; } catch (e) {}
  if (list.length < 2) { sel.style.display = "none"; _display = ""; return; }
  sel.innerHTML = `<option value="">Screen under the mouse</option>` + list.map(d =>
    `<option value="${d.index}">Screen ${d.index}${d.primary ? " (main)" : ""} — ${d.pixels[0]}×${d.pixels[1]}</option>`).join("");
  sel.style.display = "";
  sel.value = _display;
  sel.onchange = async () => { _display = sel.value; if (pickedRegion) $("clearAreaBtn").click(); else { try { await _json("/api/session/settings", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({region: null, display: _display}) }); } catch (error) { toast(error.message); return; } } toast(_display ? `Capturing screen ${_display}. Pick the code area again if you had one.` : "Capturing the screen under the mouse."); };
}
loadDisplays();
const DEEP_GROUPS = [["What it does", ["purpose", "control_flow"]], ["Business rules and calculations", ["business_rule", "calculation", "configuration"]],
  ["Data read and written", ["data_read", "data_write"]], ["Interfaces and dependencies", ["interface", "dependency"]], ["Screens", ["ui"]],
  ["Error handling", ["error_handling"]], ["Risks and defects", ["security", "data_integrity", "defect"]]];
function _deepHtml(dd, current, q) {
  const qi = q && q.status === "rescan" ? `<div class="pf-gap"><b>Rescan needed.</b> ${q.issues.map(i => escapeHtml(i.reason + (i.lines && i.lines.length ? " (lines " + i.lines.join(", ") + ")" : "") + ": " + i.advice)).join("<br>")}</div>` : "";
  if (!dd) return `<div class="pf-verify"><div class="pf-vhead">Line-by-line review</div>${qi}<div class="project-hint">Not run yet — it runs after each capture, or use “Analyse now”.</div></div>`;
  const cite = f => f.lines[0] === f.lines[1] ? `L${f.lines[0]}` : `L${f.lines[0]}–${f.lines[1]}`;
  const groups = DEEP_GROUPS.map(([t, cats]) => {
    const fs = (dd.facts || []).filter(f => cats.includes(f.category));
    return fs.length ? `<div class="dd-g"><div class="dd-t">${t}</div>${fs.map(f => `<div class="dd-f"><b>${cite(f)}</b> ${f.basis === "inferred" ? "<i>Inferred:</i> " : ""}${escapeHtml(f.statement)}${f.severity ? ` <span class="dd-sev ${_attr(f.severity)}">${escapeHtml(f.severity)}</span>` : ""}${f.review === "corrected" ? ' <small title="Corrected by the second review">(corrected)</small>' : ""}<br><code>${escapeHtml(f.quote || "")}</code></div>`).join("")}</div>` : "";
  }).join("");
  const unk = (dd.unknowns || []).length ? `<div class="dd-g"><div class="dd-t">Not shown in this file</div>${dd.unknowns.map(u => `<div class="dd-f">${u.line ? `<b>L${u.line}</b> ` : ""}${escapeHtml(u.what)}</div>`).join("")}</div>` : "";
  const held = (dd.unverifiable || []).length ? `<div class="project-hint">${dd.unverifiable.length} statement(s) held back: they rest only on lines the capture could not read.</div>` : "";
  return `<div class="pf-verify"><div class="pf-vhead">Line-by-line review${current ? "" : " (out of date — the file changed)"}</div>${qi}
    <div>${escapeHtml(dd.purpose || "")}</div>
    <div class="project-hint">${(dd.facts || []).length} statements passed both checks (quote found on the cited lines; confirmed by an independent second review)${dd.rejected ? ` · ${dd.rejected} rejected` : ""}${dd.corrected_lines ? ` · ${dd.corrected_lines} line reference(s) corrected` : ""} · ${escapeHtml(dd.model || "")}</div>
    ${held}${groups}${unk}</div>`;
}
function _checkHtml(v) {
  if (!v || !v.lines) return "";
  const span = g => g[0] === g[1] ? `line ${g[0]}` : `lines ${g[0]}–${g[1]}`;
  const gapLabel = v.gap_coordinate === "editor" ? "Not captured from the editor" : "Never on screen";
  const gaps = (v.gaps || []).length ? `<div class="pf-gap">${gapLabel}: ${(v.gaps || []).map(span).map(escapeHtml).join(", ")}. Scroll to them and use Add screenshots.</div>` : "";
  const flags = (v.flags || []).map(f => `<div class="pf-flag"><b>Final line ${f.line}</b>${f.source_line && f.source_line !== f.line ? ` <small>(editor line ${f.source_line})</small>` : ""} <code>${escapeHtml(f.text)}</code><small>${escapeHtml(f.reason)}</small></div>`).join("");
  return `<div class="pf-verify"><div class="pf-vhead">Transcription check</div><div>${escapeHtml(v.headline || "")}</div>${gaps}${flags}</div>`;
}
function _pbase() { return `/api/programs/${encodeURIComponent(_program)}`; }
function renderCaptureBar(d) {
  const bar = $("progCapBar");
  const t = d.recapture_target;
  const stuck = !d.session_running && d.artifacts.some(a => a.status === "captured" && !(a.pending && a.pending.analysing));
  bar.innerHTML = (t ? `<div class="cb recap">${t.mode === "append"
      ? `Your next capture adds to <b>${escapeHtml(t.name)}</b> — just capture the lines that were missing.`
      : `Your next capture replaces <b>${escapeHtml(t.name)}</b> (the current version is kept).`} <button class="btn-link" data-cb="cancel" type="button">Cancel</button></div>` : "")
    + (stuck ? `<div class="cb wait">Some captures are saved but not being read. <button class="btn-link" data-cb="process" type="button">Read them now</button></div>` : "");
  ["progReportHtml", "progReportDocx", "progReportPdf", "progReportZip"].forEach(id => { const el = $(id); if (el) el.classList.toggle("disabled", !!d.waiting); });
  bar.querySelectorAll("[data-cb]").forEach(b => b.addEventListener("click", async () => {
    try {
      if (b.dataset.cb === "cancel") { await _json(`${_pbase()}/recapture`, { method: "DELETE" }); toast("Recapture cancelled."); }
      else { const r = await _json(`${_pbase()}/pending/process`, { method: "POST" }); toast(r.note || "Nothing waiting."); }
    } catch (e) { toast(e.message); }
    loadProgram();
  }));
}
function pickImages() {
  return new Promise(resolve => {
    const inp = document.createElement("input");
    inp.type = "file"; inp.accept = "image/png,image/jpeg"; inp.multiple = true;
    inp.onchange = async () => {
      const read = f => new Promise(r => { const fr = new FileReader(); fr.onload = () => r(fr.result); fr.readAsDataURL(f); });
      const files = [...inp.files].sort((a, b) => a.name.localeCompare(b.name, undefined, { numeric: true }));
      resolve(await Promise.all(files.map(read)));
    };
    inp.click();
  });
}
async function fileAction(el, act, targetId) {
  const program = el.dataset.program || _program;
  const actionBase = `/api/programs/${encodeURIComponent(program)}`;
  const id = targetId || el.dataset.id, name = el.dataset.name;
  try {
    if (act === "review-lines") {
      const base = actionBase;
      const d = await _json(`${base}/artifacts/${id}`);
      if (!(d.review_lines || []).length) { toast("This warning needs additional screenshots; no single source line can resolve it."); return; }
      await openLineReview(base, id, d.review_lines);
      return;
    } else if (act === "remove") {
      if (!window.confirm(`Remove ${name} and its capture history from analysis? Its findings, screenshots and old report exports will be removed. Your original source file will stay on disk.`)) return;
      await _json(`${actionBase}/artifacts/${id}`, { method: "DELETE" });
      _progSig = "";
      toast("File removed. The report will rebuild from the remaining files.");
    } else if (act === "rename") {
      el.open = true;
      const v = await inlineAsk(el, [{ name: "name", label: "File name", value: name }]);
      if (!v || !v.name.trim() || v.name.trim() === name) return;
      await _json(`${actionBase}/artifacts/${id}/rename`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name: v.name.trim() }) });
      toast("Renamed.");
    } else if (act === "rebuild") {
      if (!window.confirm(`Rebuild ${name} from its saved screenshots? This uses cached text with no new API calls and keeps the previous version.`)) return;
      toast("Rebuilding from saved screenshots…");
      const base = actionBase;
      const key = `${program}:${name}`;
      _localRebuilds.set(key, { stage: "Sent for processing again", done: 0, total: 0 });
      _progSig = "";
      await loadProgram();
      try {
        const r = await _json(`${base}/artifacts/${id}/rebuild`, { method: "POST" });
        const flags = (r.verification.flags || []).length;
        const result = r.validation.checked && !r.validation.ok ? "Source check still reports errors." : flags ? `${flags} text warning(s) still need review.` : "Source checks complete.";
        toast(`Rebuilt ${r.lines} lines as v${r.version}. ${result} No API charge; previous version kept.`);
      } finally {
        _localRebuilds.delete(key);
        _progSig = "";
      }
    } else if (act === "recapture") {
      await _json(`${actionBase}/recapture`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ artifact_id: Number(id) }) });
      toast(`Next capture becomes a new version of ${name}. Start a capture when ready.`);
    } else if (act === "add") {
      el.open = true;
      const v = await inlineAsk(el, [{ name: "how", label: "Add screenshots by", options: ["capturing more of it", "choosing image files"] }]);
      if (!v) return;
      if (v.how.startsWith("capturing")) {
        await _json(`${actionBase}/recapture`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ artifact_id: Number(id), mode: "append" }) });
        toast(`Next capture adds to ${name} — capture the part that was missing.`);
      } else {
        const files = await pickImages();
        if (!files.length) return;
        const r = await _json(`${actionBase}/artifacts/${id}/screenshots`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ images: files }) });
        toast(`Added ${r.added} screenshot(s); re-reading ${name} from all ${r.frames}. ${r.note || ""}`);
      }
    } else if (act === "retry") {
      const r = await _json(`${actionBase}/artifacts/${id}/retry`, { method: "POST" });
      toast(r.note || "Queued.");
    }
  } catch (e) { toast(e.message); }
  loadProgram();
}
async function loadArtifact(el) {
  const program = el.dataset.program || _program;
  const base = `/api/programs/${encodeURIComponent(program)}`;
  const box = el.querySelector(".pf-detail");
  box.innerHTML = `<span class="project-hint">Loading…</span>`;
  let d;
  try { d = await _json(`${base}/artifacts/${el.dataset.id}`); }
  catch (e) { box.textContent = e.message; return; }
  if (program !== _program || !el.isConnected) return;
  const errs = d.artifact.validation_ok === 0 ? `<div class="project-hint">Compiler: ${escapeHtml((d.artifact.validation_errors || "").slice(0, 300))}</div>` : "";
  box.innerHTML = `
    <div class="pf-type">Type <select class="pf-type-select">${ARTIFACT_TYPES.map(t =>
      `<option value="${t}"${t === d.artifact.artifact_type ? " selected" : ""}>${TYPE_LABELS[t] || t}</option>`).join("")}</select></div>
    <div class="pf-rename"><input type="text" value="${_attr(d.artifact.name)}" spellcheck="false">
      <button class="btn-link pf-save" type="button">Rename</button>
      <button class="btn-link pf-re" type="button">Re-extract</button></div>
    ${errs}
    ${(d.review_lines || []).length ? `<div class="line-review-start"><button class="btn-secondary pf-review-lines" type="button">Review ${d.review_lines.length} line(s) with screenshots</button><span>See the saved evidence and answer one question at a time.</span></div>` : ""}
    ${_checkHtml(d.verification)}
    ${_deepHtml(d.deep, d.deep_current, d.quality)}
    ${profileHtml(d.profile)}
    <div class="pf-entities">${d.entities.map(e => `<div>${escapeHtml(e.name)} <i>${escapeHtml(e.kind)}${e.line_start ? " · L" + e.line_start : ""}</i></div>`).join("") || "<div><i>No entities extracted.</i></div>"}</div>
    <div class="pf-version">Same file captured earlier? Make this a new version of
      <select class="pf-vof"><option value="">choose a file…</option>${[...document.querySelectorAll("#progFiles .prog-file")].filter(x => x.dataset.id !== el.dataset.id).map(x => `<option value="${_attr(x.dataset.id)}">${escapeHtml(x.dataset.name)}</option>`).join("")}</select>
      <button class="btn-link pf-vof-go" type="button">Apply</button></div>
    <div class="pf-frames">${d.evidence.map(ev => `<a href="${base}/evidence/${ev.id}" target="_blank" rel="noopener"><img src="${base}/evidence/${ev.id}" alt="frame ${ev.ord + 1}" loading="lazy"></a>`).join("")}</div>`;
  if (box.querySelector(".pf-review-lines")) box.querySelector(".pf-review-lines").addEventListener("click", () => openLineReview(base, el.dataset.id, d.review_lines));
  box.querySelector(".pf-type-select").addEventListener("change", async (ev) => {
    try {
      const r = await _json(`${base}/artifacts/${el.dataset.id}/type`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ artifact_type: ev.target.value }) });
      toast(`Re-read as ${TYPE_LABELS[ev.target.value] || ev.target.value}: ${r.entities || 0} entities.`); loadProgram();
    } catch (e) { toast(e.message); }
  });
  box.querySelector(".pf-vof-go").addEventListener("click", async () => {
    const target = box.querySelector(".pf-vof").value;
    if (!target) { toast("Choose the file this capture is a new version of."); return; }
    try {
      const r = await _json(`${base}/artifacts/${el.dataset.id}/version-of`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ target_id: Number(target) }) });
      toast(`Saved as ${r.artifact.name} v${r.artifact.version}.`); loadProgram();
    } catch (e) { toast(e.message); }
  });
  box.querySelector(".pf-save").addEventListener("click", async () => {
    const name = box.querySelector("input").value.trim();
    try { await _json(`${base}/artifacts/${el.dataset.id}/rename`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name }) }); toast("Renamed."); loadProgram(); }
    catch (e) { toast(e.message); }
  });
  box.querySelector(".pf-re").addEventListener("click", async (ev) => {
    ev.target.textContent = "Extracting…";
    try { const r = await _json(`${base}/artifacts/${el.dataset.id}/reextract`, { method: "POST" }); toast(`${r.entities} entities, ${r.relations} relations.`); loadProgram(); }
    catch (e) { toast(e.message); ev.target.textContent = "Re-extract"; }
  });
}
function profileHtml(p) {
  if (!p) return "";
  const bits = [];
  if (p.dialect) bits.push(`<b>${escapeHtml(p.dialect)}</b>`);
  if (p.level_signal) bits.push(escapeHtml(p.level_signal));
  if (p.cobol_translated) bits.push(`<b>COBOL-translated .NET</b>`);
  if ((p.frameworks || []).length) bits.push("Frameworks: " + p.frameworks.map(escapeHtml).join(", "));
  if ((p.legacy_markers || []).length) bits.push("Legacy: " + p.legacy_markers.map(m => {
    const lines = (p.evidence || {})[m];
    return escapeHtml(m) + (lines && lines.length ? ` <small>(L${lines.join(", L")})</small>` : "");
  }).join("; "));
  if ((p.libraries || []).length) bits.push("Libraries: " + p.libraries.map(escapeHtml).join(", "));
  const st = p.settings || {};
  const flags = Object.keys(st).map(k => `${escapeHtml(k)}=${escapeHtml(String(st[k]))}`);
  if (flags.length) bits.push("Settings: " + flags.join(", "));
  return bits.length ? `<div class="pf-profile">${escapeHtml(p.language || "")} · ${bits.join(" · ")}</div>` : "";
}
async function loadProgramFlows() {
  const program = _program;
  const request = loadProgramFlows.sequence = (loadProgramFlows.sequence || 0) + 1;
  const box = $("progFlows");
  try {
    const d = await _json(`/api/programs/${encodeURIComponent(program)}/flows?limit=200`);
    if (program !== _program || request !== loadProgramFlows.sequence) return;
    if (!d.flows.length) { box.innerHTML = `<p class="project-hint">No flows yet — capture entry points (screens, endpoints, jobs) and the code they call.</p>`; return; }
    box.innerHTML = `<p class="project-hint">${d.total} flow(s)</p>` + d.flows.map(f =>
      `<div class="pf-flow"><b>${escapeHtml(f.entry)}</b> <small>${escapeHtml(f.entry_kind)}</small> → ${f.steps.map(s => escapeHtml(s.to)).join(" → ")} <small>(${escapeHtml(f.access || "")} ${escapeHtml(f.target_kind)})</small></div>`).join("");
  } catch (e) { if (program !== _program) return; box.textContent = e.message; }
}
const _SEV = ["critical", "high", "medium", "low", "info"];
let _findings = [];
function _secSummary(sum) {
  const bits = _SEV.filter(k => (sum.by_severity || {})[k]).map(k => `<span class="sev ${k}">${sum.by_severity[k]} ${k}</span>`);
  return bits.length ? bits.join(" ") : `<span class="project-hint">No findings.</span>`;
}
function _refTags(r) {
  const out = [];
  if (r.cve) out.push(r.cve);
  if (r.cwe) out.push(r.cwe);
  (r.nist || []).forEach(n => out.push("NIST " + n));
  if (r.ferpa) out.push("FERPA");
  if (r.mn_gdpa) out.push("MN ch.13");
  if (r.owasp) out.push(r.owasp.split(" ")[0]);
  return out.map(t => `<span class="ref">${escapeHtml(t)}</span>`).join("");
}
function findingList(box, rows, onUpdate) {
  const program = _program;
  const base = `/api/programs/${encodeURIComponent(_program)}`;
  box.innerHTML = rows.map(f => {
    const ev = (f.evidence || []).map(e => {
      const where = e.url ? `<a href="${_attr(e.url)}" target="_blank" rel="noopener">${escapeHtml(e.url)}</a>` : escapeHtml((e.file || "") + (e.screen ? " · " + e.screen : ""));
      return `<div class="sec-ev"><b>${where}${e.line ? ":" + e.line : ""}</b>${e.snippet ? ` <code>${escapeHtml(e.snippet)}</code>` : ""}${(e.screenshots || []).slice(0, 3).map(id => ` <a href="${base}/evidence/${id}" target="_blank" rel="noopener">frame</a>`).join("")}</div>`;
    }).join("");
    return `<details class="sec-f ${f.status === "dismissed" ? "dismissed" : ""}" data-id="${f.id}"><summary><span class="sev ${_attr(f.severity)}">${escapeHtml(f.severity)}</span> ${escapeHtml(f.title)}</summary>
      <div class="sec-d"><p>${escapeHtml(f.detail || "")}</p>${ev}
      <div class="sec-refs">${_refTags(f.refs || {})}</div>
      <div class="sec-src">Source: ${escapeHtml(f.source || "")}</div>
      <div class="sec-actions">${["open", "accepted", "dismissed", "fixed"].map(s => `<button class="btn-link${f.status === s ? " on" : ""}" data-status="${s}" type="button">${s}</button>`).join(" ")}
        <select class="sec-sev" title="Correct severity">${["", "critical", "high", "medium", "low", "info"].map(v => `<option value="${v}">${v ? v : "severity…"}</option>`).join("")}</select></div></div></details>`;
  }).join("");
  box.querySelectorAll(".sec-sev").forEach(sel => sel.addEventListener("change", async () => {
    const f = rows.find(x => String(x.id) === sel.closest(".sec-f").dataset.id);
    if (!sel.value || !f) return;
    await applyCorrections([{ op: "finding.severity", payload: { sig: `${f.rule || f.category}|${f.title}`, severity: sel.value } }], "severity corrected from findings list", program);
    if (program === _program) onUpdate({ ...f, severity: sel.value });
  }));
  box.querySelectorAll(".sec-actions button").forEach(b => b.addEventListener("click", async () => {
    const id = b.closest(".sec-f").dataset.id;
    try {
      const d = await _json(`${base}/findings/${id}/status`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ status: b.dataset.status }) });
      if (program === _program) onUpdate(d.finding);
    } catch (e) { alert(e.message); }
  }));
}
function renderFindings() {
  const box = $("progSec");
  const cat = $("progSecFilter").value;
  const rows = _findings.filter(f => !cat || f.category === cat)
    .sort((a, b) => _SEV.indexOf(a.severity) - _SEV.indexOf(b.severity));
  if (!rows.length) { box.innerHTML = `<p class="project-hint">${_findings.length ? "Nothing in this category." : "Not scanned yet — Run scan."}</p>`; return; }
  findingList(box, rows, nf => { _findings = _findings.map(f => f.id === nf.id ? nf : f); renderFindings(); });
}
const _UI_CATS = { accessibility: "Accessibility", usability: "Usability", ui_security: "UI security", website: "Website" };
let _uiFindings = [], _uiData = null;
function renderUiReview() {
  const box = $("progUi"), d = _uiData;
  if (!d) { box.innerHTML = ""; return; }
  const cat = $("progUiFilter").value;
  const sum = d.summary || {};
  $("progUiSummary").innerHTML = `UI, process &amp; website ` + Object.entries(_UI_CATS).filter(([k]) => (sum[k] || {}).total)
    .map(([k, v]) => `<span class="sev ${(sum[k].high ? "high" : "low")}">${sum[k].total} ${escapeHtml(v.toLowerCase())}</span>`).join(" ");
  const site = d.site;
  const siteHtml = site ? `<div class="ui-site"><b>${escapeHtml(site.final_url || site.start || "")}</b> · TLS ${escapeHtml((site.tls || {}).version || "none")} · ${(site.pages || []).filter(p => p.status && p.status < 400).length} page(s) · scanned ${escapeHtml((site.scanned || "").slice(0, 10))}${site.error ? ` · <span class="sev high">${escapeHtml(site.error)}</span>` : ""}</div>` : `<p class="project-hint">No live site scan yet — enter the program's URL and press Scan site.</p>`;
  const fl = d.flows || {};
  const journeys = (fl.journeys || []).slice(0, 12).map(j => `<div class="pf-flow">${j.steps.map(s => escapeHtml(s.screen) + (s.captured ? "" : " <small>(not captured)</small>")).join(" → ")}</div>`).join("")
    || `<p class="project-hint">No multi-screen journeys in the captured screens yet.</p>`;
  const extra = [fl.dead_ends && fl.dead_ends.length ? `Links to screens not captured: ${fl.dead_ends.map(escapeHtml).join(", ")}` : "",
    fl.orphans && fl.orphans.length ? `Standalone screens: ${fl.orphans.map(escapeHtml).join(", ")}` : ""].filter(Boolean).map(t => `<p class="project-hint">${t}</p>`).join("");
  box.innerHTML = `${siteHtml}<div class="prog-section-label">User journeys (${fl.screens || 0} screens)</div>${journeys}${extra}<div class="prog-section-label">Findings</div><div id="progUiList"></div>`;
  const rows = _uiFindings.filter(f => !cat || f.category === cat).sort((a, b) => _SEV.indexOf(a.severity) - _SEV.indexOf(b.severity));
  const list = $("progUiList");
  if (!rows.length) { list.innerHTML = `<p class="project-hint">${_uiFindings.length ? "Nothing in this category." : "Not reviewed yet — press Review UI."}</p>`; return; }
  findingList(list, rows, nf => { _uiFindings = _uiFindings.map(f => f.id === nf.id ? nf : f); renderUiReview(); });
}
async function loadUiReview() {
  const program = _program;
  const request = loadUiReview.sequence = (loadUiReview.sequence || 0) + 1;
  try {
    const d = await _json(`/api/programs/${encodeURIComponent(program)}/ui`);
    if (program !== _program || request !== loadUiReview.sequence) return;
    _uiData = d; _uiFindings = d.findings || [];
    if (d.site && d.site.start && !$("progUiUrl").value) $("progUiUrl").value = d.site.start;
    renderUiReview();
  } catch (e) { if (program !== _program) return; $("progUi").textContent = e.message; }
}
async function runUiReview(withSite) {
  const program = _program;
  const request = runUiReview.sequence = (runUiReview.sequence || 0) + 1;
  const btn = withSite ? $("progUiScan") : $("progUiRun");
  const url = $("progUiUrl").value.trim();
  if (withSite && !url) { toast("Enter the site URL first."); return; }
  const label = btn.textContent;
  btn.disabled = true; btn.textContent = withSite ? "Scanning site…" : "Reviewing…";
  try {
    const qs = new URLSearchParams();
    if (withSite) { qs.set("site_url", url); qs.set("max_pages", $("progUiPages").value || "10"); }
    await _json(`/api/programs/${encodeURIComponent(program)}/ui/review?${qs}`, { method: "POST" });
    if (program !== _program || request !== runUiReview.sequence) { btn.disabled = false; btn.textContent = label; return; }
    await loadUiReview();
  } catch (e) { if (program !== _program) { btn.disabled = false; btn.textContent = label; return; } $("progUi").textContent = e.message; }
  btn.disabled = false; btn.textContent = label;
}
function _impactHtml(impact, warnings) {
  return `<div class="fix-impact"><b>What changed</b><ul>${(impact || []).map(t => `<li>${escapeHtml(t)}</li>`).join("")}</ul>${(warnings || []).map(w => `<p class="project-hint">${escapeHtml(w)}</p>`).join("")}</div>`;
}
async function applyCorrections(ops, note, program = _program) {
  const d = await _json(`/api/programs/${encodeURIComponent(program)}/corrections`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ ops, note: note || "" }) });
  if (program !== _program) return d;
  $("progFixImpact").innerHTML = _impactHtml(d.impact, d.warnings);
  toast((d.impact || [])[0] || "Correction applied.");
  await loadCorrections();
  await loadProgram();
  if ($("progAssessBox").open) loadAssessment();
  return d;
}
async function loadCorrections() {
  const program = _program;
  const request = loadCorrections.sequence = (loadCorrections.sequence || 0) + 1;
  try {
    const d = await _json(`/api/programs/${encodeURIComponent(program)}/corrections`);
    if (program !== _program || request !== loadCorrections.sequence) return;
    const active = d.corrections.filter(c => c.active).length;
    $("progFixSummary").innerHTML = `Corrections &amp; feedback ${active ? `<span class="sev low">${active} active</span>` : ""}`;
    $("progFixLog").innerHTML = d.corrections.length ? d.corrections.slice().reverse().map(c => `<div class="fix-row ${c.active ? "" : "undone"}"><span>${escapeHtml(c.description)}</span>${c.note ? ` <small>— ${escapeHtml(c.note)}</small>` : ""} <small>${escapeHtml((c.created || "").slice(0, 16).replace("T", " "))}</small>${c.active && c.undoable ? ` <button class="btn-link fix-undo" data-id="${c.id}" type="button">undo</button>` : c.active ? "" : " <small>(undone)</small>"}</div>`).join("") : `<p class="project-hint">No corrections yet. Corrections survive re-capture, re-scan and re-assessment.</p>`;
    $("progFixLog").querySelectorAll(".fix-undo").forEach(b => b.addEventListener("click", async () => {
      try {
        const r = await _json(`/api/programs/${encodeURIComponent(program)}/corrections/${b.dataset.id}/undo`, { method: "POST" });
    if (program !== _program || request !== loadCorrections.sequence) return;
        $("progFixImpact").innerHTML = _impactHtml(r.impact, r.warnings);
        loadCorrections();
        await loadProgram();
        if ($("progFixSearch").value.trim().length >= 2) searchEntities();
        if ($("progAssessBox").open) loadAssessment();
      } catch (e) { if (program !== _program) return; toast(e.message); }
    }));
  } catch (e) { if (program !== _program) return; $("progFixLog").textContent = e.message; }
}
async function interpretCorrection() {
  const program = _program;
  const request = interpretCorrection.sequence = (interpretCorrection.sequence || 0) + 1;
  const text = $("progFixText").value.trim();
  if (!text) { toast("Describe the correction first."); return; }
  const btn = $("progFixInterpret"); btn.disabled = true; btn.textContent = "Interpreting…";
  try {
    const d = await _json(`/api/programs/${encodeURIComponent(program)}/corrections/interpret`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text }) });
    if (program !== _program || request !== interpretCorrection.sequence) { btn.disabled = false; btn.textContent = "Review correction"; return; }
    const box = $("progFixProposal");
    if (!d.changes.length) { box.innerHTML = `<p class="project-hint">${escapeHtml(d.unclear || "Couldn't map that to a change — try naming the program, table or finding.")}</p>`; }
    else {
      box.innerHTML = d.changes.map((c, i) => `<label class="fix-prop"><input type="checkbox" data-i="${i}" checked> ${escapeHtml(c.description)}${c.reason ? ` <small>— ${escapeHtml(c.reason)}</small>` : ""}</label>`).join("")
        + (d.rejected.length ? `<p class="project-hint">Skipped ${d.rejected.length}: ${d.rejected.map(r => escapeHtml(r.error)).join("; ")}</p>` : "")
        + `<button class="btn-primary" id="progFixApply" type="button">Apply selected</button>`;
      $("progFixApply").addEventListener("click", async () => {
        const ops = [...box.querySelectorAll("input[type=checkbox]:checked")].map(x => d.changes[+x.dataset.i]).map(c => ({ op: c.op, payload: c.payload }));
        if (!ops.length) { btn.disabled = false; btn.textContent = "Review correction"; return; }
        await applyCorrections(ops, text, program); box.innerHTML = ""; $("progFixText").value = "";
      });
    }
  } catch (e) { if (program !== _program) { btn.disabled = false; btn.textContent = "Review correction"; return; } $("progFixProposal").textContent = e.message; }
  btn.disabled = false; btn.textContent = "Review correction";
}
let _fixTimer = null;
function inlineAsk(container, fields) {
  return new Promise(resolve => {
    const form = document.createElement("div");
    form.className = "fix-ask";
    form.innerHTML = fields.map(f => f.options
      ? `<label>${escapeHtml(f.label)} <select data-n="${_attr(f.name)}">${f.options.map(o => `<option>${escapeHtml(o)}</option>`).join("")}</select></label>`
      : `<label>${escapeHtml(f.label)} <input data-n="${_attr(f.name)}" value="${_attr(f.value || "")}" spellcheck="false"></label>`).join(" ")
      + ` <button class="btn-primary" data-ok type="button">OK</button> <button class="btn-link" data-cancel type="button">Cancel</button>`;
    container.querySelectorAll(".fix-ask").forEach(x => x.remove());
    container.appendChild(form);
    const first = form.querySelector("input,select"); if (first) first.focus();
    const done = ok => {
      const out = {};
      form.querySelectorAll("[data-n]").forEach(i => { out[i.dataset.n] = i.value; });
      form.remove(); resolve(ok ? out : null);
    };
    form.querySelector("[data-ok]").addEventListener("click", () => done(true));
    form.querySelector("[data-cancel]").addEventListener("click", () => done(false));
    form.querySelectorAll("input").forEach(i => i.addEventListener("keydown", ev => { if (ev.key === "Enter") done(true); if (ev.key === "Escape") done(false); }));
  });
}
async function searchEntities() {
  const program = _program;
  const request = searchEntities.sequence = (searchEntities.sequence || 0) + 1;
  const q = $("progFixSearch").value.trim();
  const box = $("progFixResults");
  if (q.length < 2) { box.innerHTML = ""; return; }
  try {
    const d = await _json(`/api/programs/${encodeURIComponent(program)}/entities/search?q=${encodeURIComponent(q)}`);
    if (program !== _program || request !== searchEntities.sequence) return;
    box.innerHTML = d.entities.map((e, i) => {
      const flags = [e.attrs.no_pii ? "no student data" : "", e.attrs.pii ? "student data" : "", e.attrs.hardcoded_secret === false ? "not a secret" : ""].filter(Boolean);
      const acts = [`<button class="btn-link" data-act="rename" type="button">rename</button>`,
        ["table", "column", "field", "ui_element", "data_store", "screen"].includes(e.kind) ? `<button class="btn-link" data-act="${e.attrs.no_pii ? "pii" : "nopii"}" type="button">${e.attrs.no_pii ? "holds student data" : "no student data"}</button>` : "",
        e.kind === "config_item" && e.attrs.hardcoded_secret ? `<button class="btn-link" data-act="nosecret" type="button">not a secret</button>` : "",
        `<button class="btn-link" data-act="addrel" type="button">add relation</button>`,
        `<button class="btn-link" data-act="delete" type="button">not real — remove</button>`].join(" ");
      const rels = e.relations.map((r, j) => `<div class="fix-rel">${escapeHtml(r.from)} <b>${escapeHtml(r.kind)}</b> ${escapeHtml(r.to)}${r.origin === "corrected" ? " <small>(corrected)</small>" : ""} <button class="btn-link" data-rel="${j}" type="button">remove</button></div>`).join("");
      return `<details class="fix-ent" data-i="${i}"><summary><b>${escapeHtml(e.name)}</b> <small>${escapeHtml(e.kind)}${e.file ? " · " + escapeHtml(e.file) : ""}${e.origin === "placeholder" ? " · not captured" : ""}${flags.length ? " · " + flags.join(", ") : ""}</small></summary><div class="fix-acts">${acts}</div>${rels}</details>`;
    }).join("") || `<p class="project-hint">Nothing matches.</p>`;
    box.querySelectorAll(".fix-ent").forEach(el => {
      const e = d.entities[+el.dataset.i];
      el.querySelectorAll("[data-act]").forEach(b => b.addEventListener("click", async () => {
        const act = b.dataset.act;
        let ops = [];
        if (act === "rename") {
          const v = await inlineAsk(el.querySelector(".fix-acts"), [{ name: "name", label: "New name", value: e.name }]);
          if (!v || !v.name || v.name === e.name) return;
          ops = [{ op: "entity.rename", payload: { key: e.key, name: v.name } }];
        }
        if (act === "nopii") ops = [{ op: "entity.set_attrs", payload: { key: e.key, attrs: { no_pii: true } } }];
        if (act === "pii") ops = [{ op: "entity.set_attrs", payload: { key: e.key, attrs: { no_pii: false, pii: "student data (analyst)" } } }];
        if (act === "nosecret") ops = [{ op: "entity.set_attrs", payload: { key: e.key, attrs: { hardcoded_secret: false } } }];
        if (act === "delete") ops = [{ op: "entity.delete", payload: { key: e.key } }];
        if (act === "addrel") {
          const v = await inlineAsk(el.querySelector(".fix-acts"), [
            { name: "kind", label: `${e.name} …`, options: ["calls", "uses", "reads", "writes", "includes", "displays", "navigates_to", "connects_to", "depends_on", "inherits", "implements"] },
            { name: "to", label: "target name", value: "" }]);
          if (!v || !v.to) return;
          ops = [{ op: "relation.add", payload: { kind: v.kind, from_key: e.key, to_name: v.to.trim() } }];
        }
        try { await applyCorrections(ops, ""); searchEntities(); } catch (err) { toast(err.message); }
      }));
      el.querySelectorAll("[data-rel]").forEach(b => b.addEventListener("click", async () => {
        const r = e.relations[+b.dataset.rel];
        try { await applyCorrections([{ op: "relation.delete", payload: { kind: r.kind, from_key: r.from_key, to_key: r.to_key } }], ""); searchEntities(); } catch (err) { toast(err.message); }
      }));
    });
  } catch (e) { if (program !== _program) return; box.textContent = e.message; }
}
async function loadProgramFindings() {
  const program = _program;
  const request = loadProgramFindings.sequence = (loadProgramFindings.sequence || 0) + 1;
  try {
    const d = await _json(`/api/programs/${encodeURIComponent(program)}/findings`);
    if (program !== _program || request !== loadProgramFindings.sequence) return;
    _findings = d.findings.filter(f => ["security", "eol", "vulnerability", "privacy"].includes(f.category));
    $("progSecSummary").innerHTML = `Security &amp; end-of-life ${_secSummary(d.summary)}`;
    renderFindings();
  } catch (e) { if (program !== _program) return; $("progSec").textContent = e.message; }
}
async function runSecurityScan() {
  const program = _program;
  const request = runSecurityScan.sequence = (runSecurityScan.sequence || 0) + 1;
  const btn = $("progSecScan");
  btn.disabled = true; btn.textContent = "Scanning…";
  try {
    const online = $("progSecOnline").checked ? "true" : "false";
    await _json(`/api/programs/${encodeURIComponent(program)}/security/scan?online=${online}`, { method: "POST" });
    if (program !== _program || request !== runSecurityScan.sequence) { btn.disabled = false; btn.textContent = "Run scan"; return; }
    await loadProgramFindings();
  } catch (e) { if (program !== _program) { btn.disabled = false; btn.textContent = "Run scan"; return; } $("progSec").textContent = e.message; }
  btn.disabled = false; btn.textContent = "Run scan";
}
let _assess = null, _assessInputs = {};
function _bar(label, v) {
  const val = v == null ? 0 : v;
  const cls = v == null ? "na" : v >= 80 ? "good" : v >= 60 ? "fair" : v >= 40 ? "poor" : "crit";
  return `<div class="as-bar"><span class="as-bl">${escapeHtml(label)}</span><span class="as-track"><span class="as-fill ${cls}" style="width:${val}%"></span></span><b>${v == null ? "n/a" : v}</b></div>`;
}
function renderAssessment() {
  const box = $("progAssess"), a = _assess;
  if (!a) { box.innerHTML = `<p class="project-hint">Not assessed yet — Run assessment.</p>`; return; }
  const v = a.verdict || {}, sc = a.scores || {}, conf = a.confidence || {};
  $("progAssessSummary").innerHTML = `Assessment &amp; verdict <span class="as-chip ${_attr((v.bucket || "").replace(/ /g, "-"))}">${escapeHtml(v.label || "—")}</span>`;
  const dims = ["health", "tech_debt", "security", "supportability", "complexity", "coupling", "ux"];
  const cells = a.matrix.cells.map((row, ri) => `<tr><th>${5 - ri}</th>${row.map((names, ci) => {
    const lvl = (5 - ri) * (ci + 1) >= 20 ? "critical" : (5 - ri) * (ci + 1) >= 12 ? "high" : (5 - ri) * (ci + 1) >= 6 ? "medium" : "low";
    return `<td class="mx ${lvl}" title="${_attr(names.join(", "))}">${names.length || ""}</td>`; }).join("")}</tr>`).join("");
  const comps = a.components.map(c => {
    const inp = (_assessInputs.components || {})[c.name] || {};
    const opts = [1, 2, 3, 4, 5].map(n => `<option value="${n}" ${n === c.risk.impact ? "selected" : ""}>${n}</option>`).join("");
    return `<tr><td><b>${escapeHtml(c.name)}</b>${c.student_data ? ' <span class="ref">student data</span>' : ""}</td>
      <td>${c.overall}</td><td><span class="sev ${_attr(c.risk.level)}">${escapeHtml(c.risk.level)}</span> ${c.risk.likelihood}×${c.risk.impact}</td>
      <td><select class="as-imp" data-name="${_attr(c.name)}">${opts}</select><small>${c.risk.impact_source === "staff" ? "" : " default"}</small></td>
      <td>${c.disposition ? escapeHtml(c.disposition.label) : "<small>as program</small>"}</td>
      <td><input class="as-cots" data-name="${_attr(c.name)}" placeholder="COTS / retire note" value="${_attr(inp.cots || inp.retire || "")}"></td></tr>`;
  }).join("");
  const plan = (a.roadmap.phases || []).map(p => `<div class="as-phase"><div class="as-ph"><b>${escapeHtml(p.title)}</b> <small>${escapeHtml(p.window)} · ${p.low}–${p.high} person-weeks</small></div>
    ${p.items.map(i => `<div class="as-item">${escapeHtml(i.title)} <small>${i.low}–${i.high} pw${i.components.length ? " · " + escapeHtml(i.components.slice(0, 3).join(", ")) + (i.components.length > 3 ? "…" : "") : ""}</small></div>`).join("")}</div>`).join("");
  box.innerHTML = `
    <div class="as-verdict"><div><div class="as-big">${escapeHtml(v.label || "—")}</div><div class="as-bucket">${escapeHtml(v.bucket || "")} · confidence ${escapeHtml(conf.level || "")}</div></div>
      <div class="as-reasons"><p>${escapeHtml(v.meaning || "")}</p><ul>${(v.reasons || []).map(r => `<li>${escapeHtml(r)}</li>`).join("")}</ul>
      <small>${escapeHtml((conf.notes || []).join(" · "))}</small></div></div>
    <div class="as-grid"><div>${_bar("Overall", sc.overall && sc.overall.score)}${dims.map(d => _bar(a.labels[d], sc[d] && sc[d].score)).join("")}
      <p class="project-hint">Total risk: <span class="sev ${_attr(a.total_risk.level)}">${escapeHtml(a.total_risk.level)}</span> · ${a.grade_scale}</p></div>
      <div><table class="as-mx"><tr><th></th><th colspan="5">impact →</th></tr>${cells}<tr><th></th>${[1, 2, 3, 4, 5].map(n => `<th>${n}</th>`).join("")}</tr></table><small>likelihood ↑ · hover a cell for components</small></div></div>
    <div class="prog-section-label">Components</div>
    <table class="as-tbl"><tr><th>Component</th><th>Score</th><th>Risk</th><th>Impact</th><th>Disposition</th><th>Staff note</th></tr>${comps}</table>
    <div class="prog-section-label">Roadmap — ${a.roadmap.total.low}–${a.roadmap.total.high} person-weeks</div>${plan}`;
  box.querySelectorAll(".as-imp").forEach(el => el.addEventListener("change", () => saveAssessInput(el.dataset.name, { impact: +el.value })));
  box.querySelectorAll(".as-cots").forEach(el => el.addEventListener("change", () => {
    const val = el.value.trim();
    saveAssessInput(el.dataset.name, /^retire/i.test(val) ? { retire: val } : { cots: val });
  }));
}
async function saveAssessInput(name, vals) {
  const program = _program;
  const request = saveAssessInput.sequence = (saveAssessInput.sequence || 0) + 1;
  const cur = { ...((_assessInputs.components || {})[name] || {}) };
  if ("cots" in vals || "retire" in vals) { delete cur.cots; delete cur.retire; }
  const payload = { components: { [name]: { ...cur, ...vals } } };
  try {
    const d = await _json(`/api/programs/${encodeURIComponent(program)}/assessment/inputs`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
    if (program !== _program || request !== saveAssessInput.sequence) return;
    _assess = d.assessment; _assessInputs = d.inputs; renderAssessment();
  } catch (e) { if (program !== _program) return; alert(e.message); }
}
async function loadAssessment() {
  const program = _program;
  const request = loadAssessment.sequence = (loadAssessment.sequence || 0) + 1;
  try {
    const d = await _json(`/api/programs/${encodeURIComponent(program)}/assessment`);
    if (program !== _program || request !== loadAssessment.sequence) return;
    _assess = d.assessment; _assessInputs = d.inputs || {}; renderAssessment();
  } catch (e) { if (program !== _program) return; $("progAssess").textContent = e.message; }
}
async function runAssessment() {
  const program = _program;
  const request = runAssessment.sequence = (runAssessment.sequence || 0) + 1;
  const btn = $("progAssessRun");
  btn.disabled = true; btn.textContent = "Assessing…";
  try {
    const d = await _json(`/api/programs/${encodeURIComponent(program)}/assessment?online=${$("progSecOnline").checked}`, { method: "POST" });
    if (program !== _program || request !== runAssessment.sequence) { btn.disabled = false; btn.textContent = "Run assessment"; return; }
    _assess = d.assessment; _assessInputs = d.inputs || {}; renderAssessment();
    if ($("progSecBox").open) loadProgramFindings();
  } catch (e) { if (program !== _program) { btn.disabled = false; btn.textContent = "Run assessment"; return; } $("progAssess").textContent = e.message; }
  btn.disabled = false; btn.textContent = "Run assessment";
}
function showDiagram() {
  const id = $("progDiagSelect").value;
  const base = `/api/programs/${encodeURIComponent(_program)}/diagrams`;
  $("progDiag").innerHTML = id ? `<a href="${base}/${encodeURIComponent(id)}.svg" target="_blank" rel="noopener"><img src="${base}/${encodeURIComponent(id)}.svg?t=${Date.now()}" alt="diagram"></a>` : "";
}
async function loadDiagrams() {
  const program = _program;
  const request = loadDiagrams.sequence = (loadDiagrams.sequence || 0) + 1;
  const base = `/api/programs/${encodeURIComponent(program)}/diagrams`;
  $("progDiagVsdx").href = `${base}/export/vsdx`;
  $("progDiagDrawio").href = `${base}/export/drawio`;
  $("progDiagZip").href = `${base}/export/zip`;
  try {
    const d = await _json(base);
    if (program !== _program || request !== loadDiagrams.sequence) return;
    const keep = $("progDiagSelect").value;
    const label = { context: "Context", component: "Components", class: "Class", data: "Data model", sequence: "Interaction" };
    $("progDiagSelect").innerHTML = d.diagrams.map(x => `<option value="${_attr(x.id)}">${escapeHtml((label[x.kind] || x.kind) + " — " + x.title.split(" — ").slice(1).join(" — "))} (${x.nodes})</option>`).join("");
    if (keep && d.diagrams.some(x => x.id === keep)) $("progDiagSelect").value = keep;
    const c = d.coverage;
    $("progDiagSummary").innerHTML = `Diagrams <small class="project-hint">${d.diagrams.length} · ${c.shown}/${c.entities} entities shown</small>`;
    showDiagram();
  } catch (e) { if (program !== _program) return; $("progDiag").textContent = e.message; }
}
async function loadProgramMap() {
  const program = _program;
  const request = loadProgramMap.sequence = (loadProgramMap.sequence || 0) + 1;
  const box = $("progMap");
  try {
    const g = await _json(`/api/programs/${encodeURIComponent(program)}/graph`);
    if (program !== _program || request !== loadProgramMap.sequence) return;
    box.innerHTML = g.edges.length ? `<pre class="mermaid">${escapeHtml(g.mermaid)}</pre>` : `<p class="project-hint">No dependencies yet.</p>`;
    renderMermaid();
  } catch (e) { if (program !== _program) return; box.textContent = e.message; }
}
$("progSelect").addEventListener("change", async (e) => {
  _program = e.target.value; _progSig = ""; _progStore(_program);
  _assess = null; _assessInputs = {}; _findings = []; _uiFindings = [];
  ["progFiles", "progFlows", "progMap", "progSec", "progUi", "progAssess", "progDiag",
   "progFixLog", "progFixProposal", "progFixImpact", "progReportForm"].forEach(id => { $(id).innerHTML = ""; });
  if (_projMode) setProjectMode(false);
  await loadProgram();
  toast(_program ? "Captures will be added to this program." : "No program selected.");
});
$("progNewBtn").addEventListener("click", () => { $("progNew").style.display = "flex"; $("progNewName").focus(); });
$("progNewCancel").addEventListener("click", () => { $("progNew").style.display = "none"; });
async function createProgram() {
  const name = $("progNewName").value.trim();
  if (!name) return;
  try {
    const r = await _json("/api/programs", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name }) });
    $("progNew").style.display = "none"; $("progNewName").value = "";
    await loadPrograms(r.program.slug);
    toast("Program created.");
  } catch (e) { toast(e.message); }
}
$("progCreate").addEventListener("click", createProgram);
$("progNewName").addEventListener("keydown", (e) => { if (e.key === "Enter") createProgram(); });
$("progMapBox").addEventListener("toggle", () => { if ($("progMapBox").open) loadProgramMap(); });
$("progExport").addEventListener("click", async () => {
  try {
    const r = await fetch(`/api/programs/${encodeURIComponent(_program)}/export`);
    if (!r.ok) throw new Error("Export failed");
    await saveFile(_program + ".program.json", await r.text());
  } catch (e) { toast(e.message); }
});
$("progImport").addEventListener("click", async (ev) => {
  ev.target.textContent = "Importing…"; ev.target.disabled = true;
  try {
    const r = await _json(`/api/programs/${encodeURIComponent(_program)}/import`, { method: "POST" });
    toast(`Imported ${r.imported.length} file(s).`);
    await loadProgram();
  } catch (e) { toast(e.message); }
  ev.target.textContent = "Import past reports"; ev.target.disabled = false;
});
loadPrograms();

const ARTIFACT_TYPES = ["code", "sql", "db_schema", "config", "web", "api", "ui_screen", "job", "other"];
const TYPE_LABELS = { code: "Source code", sql: "SQL", db_schema: "DB schema", config: "Config", web: "Web page",
  api: "API definition", ui_screen: "App screen", job: "Batch job / SPSS", other: "Other" };
const KIND_HINT = { auto: "Works out whether it's code or an app screen", code: "Source code, SQL, config, web pages",
  screen: "A running app's screen: fields, buttons, messages (no data values)" };
document.querySelectorAll("#kindSeg .seg-opt").forEach(b => b.addEventListener("click", async (ev) => {
  if (ev.isTrusted) _kindManual = true;
  _captureKind = b.dataset.kind;
  document.querySelectorAll("#kindSeg .seg-opt").forEach(x => x.classList.toggle("active", x === b));
  $("kindHint").textContent = KIND_HINT[_captureKind];
  try { await fetch("/api/session/kind?kind=" + _captureKind, { method: "POST" }); } catch (e) {}
  if (sessionRunning && ev.isTrusted) toast({ auto: "Next capture works out what it is.", screen: "Next capture reads an app screen.", code: "Next capture reads code." }[_captureKind]);
}));

$("progFixBox").addEventListener("toggle", () => { if ($("progFixBox").open) loadCorrections(); });
$("progReportBox").addEventListener("toggle", () => { if ($("progReportBox").open) loadReportSettings(); });
async function loadReportSettings() {
  const program = _program;
  const request = loadReportSettings.sequence = (loadReportSettings.sequence || 0) + 1;
  const box = $("progReportForm");
  let d;
  try { d = await _json(`/api/programs/${encodeURIComponent(program)}/report-settings`);
    if (program !== _program || request !== loadReportSettings.sequence) return; } catch (e) { if (program !== _program) return; box.textContent = e.message; return; }
  box.innerHTML = `<p class="project-hint" style="margin:4px 0 8px">Shown in the Word/PDF report. Anything left empty is written as "Unknown" and listed as an open item.</p>
    <div class="rs-grid">${d.fields.map(f => `<label>${escapeHtml(f.label)}<input type="text" data-k="${_attr(f.key)}" value="${_attr(d.values[f.key] || "")}" spellcheck="false"></label>`).join("")}</div>
    <button class="btn-secondary" id="rsSave" type="button">Save report details</button>`;
  $("rsSave").addEventListener("click", async () => {
    const body = {};
    box.querySelectorAll("input[data-k]").forEach(i => { body[i.dataset.k] = i.value; });
    try { await _json(`/api/programs/${encodeURIComponent(program)}/report-settings`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    if (program !== _program || request !== loadReportSettings.sequence) return; toast("Report details saved — the report will be rebuilt."); }
    catch (e) { if (program !== _program) return; toast(e.message); }
  });
}
$("progFixInterpret").addEventListener("click", interpretCorrection);
$("progFixSearch").addEventListener("input", () => { clearTimeout(_fixTimer); _fixTimer = setTimeout(searchEntities, 250); });
$("progUiBox").addEventListener("toggle", () => { if ($("progUiBox").open) loadUiReview(); });
$("progUiRun").addEventListener("click", () => runUiReview(false));
$("progUiScan").addEventListener("click", () => runUiReview(true));
$("progUiFilter").addEventListener("change", renderUiReview);
$("progDiagBox").addEventListener("toggle", () => { if ($("progDiagBox").open) loadDiagrams(); });
$("progDiagSelect").addEventListener("change", showDiagram);
$("progAssessBox").addEventListener("toggle", () => { if ($("progAssessBox").open) loadAssessment(); });
$("progAssessRun").addEventListener("click", runAssessment);
$("progSecBox").addEventListener("toggle", () => { if ($("progSecBox").open) loadProgramFindings(); });
$("progSecScan").addEventListener("click", runSecurityScan);
$("progSecFilter").addEventListener("change", renderFindings);
$("progFlowsBox").addEventListener("toggle", () => { if ($("progFlowsBox").open) loadProgramFlows(); });
$("progRelink").addEventListener("click", async () => {
  try { const r = await _json(`/api/programs/${encodeURIComponent(_program)}/relink`, { method: "POST" });
        toast(`Linked: ${r.merged} merged, ${r.jcl + r.config + r.screens + r.translated} new links.`); loadProgram(); }
  catch (e) { toast(e.message); }
});

function _viewStore(v) {
  try { if (v === undefined) return localStorage.getItem("codesnap.view") || "codesnap"; localStorage.setItem("codesnap.view", v); } catch (e) {}
  return v || "codesnap";
}
function setView(v) {
  _view = v === "review" ? "review" : "codesnap";
  _viewStore(_view);
  document.querySelectorAll(".sidebar .nav-item[data-view]").forEach(n => n.classList.toggle("active", n.dataset.view === _view));
  $("viewReview").style.display = _view === "review" ? "" : "none";
  $("viewCodesnap").style.display = _view === "codesnap" ? "" : "none";
  $(_view === "review" ? "startSlotReview" : "startSlotCodesnap").after($("captureBlock"));
  document.querySelector(".kind-row").style.display = _view === "review" ? "" : "none";
  if (_view === "codesnap" && _captureKind !== "code") document.querySelector('#kindSeg .seg-opt[data-kind="code"]').click();
  if (_view === "review" && !_kindManual && _captureKind !== "auto") document.querySelector('#kindSeg .seg-opt[data-kind="auto"]').click();
  $("startSub").textContent = _view === "review"
    ? (_program ? "Each capture is added to the selected program." : "Pick or create a program above, then capture its files and screens.")
    : "Capture, scroll for more, and it builds the report.";
  document.title = _view === "review" ? "Ledelsea — Platform Holistic Review" : "Ledelsea — CodeSnap";
}
document.querySelectorAll(".sidebar .nav-item[data-view]").forEach(n => n.addEventListener("click", e => {
  e.preventDefault();
  setView(n.dataset.view);
}));
$("progSelect").addEventListener("change", () => { if (_view === "review") setView("review"); });
setView(location.hash === "#review" ? "review" : location.hash === "#codesnap" ? "codesnap" : _viewStore());


function _lineEditLabel(original, replacement) {
  if (original === replacement) return "Keep the current text";
  if (original.trim() === replacement.trim()) return "Use the spacing from the saved capture";
  let left = 0, right = 0;
  while (left < original.length && left < replacement.length && original[left] === replacement[left]) left++;
  while (right < original.length - left && right < replacement.length - left && original[original.length - 1 - right] === replacement[replacement.length - 1 - right]) right++;
  const before = original.slice(left, original.length - right);
  const after = replacement.slice(left, replacement.length - right);
  const short = text => text.length > 36 ? text.slice(0, 36) + "…" : text;
  if (!before) return `Add “${short(after)}”`;
  if (!after) return `Remove “${short(before)}”`;
  return `Change “${short(before)}” to “${short(after)}”`;
}

// Screenshot-led review stays open while program polling refreshes the file list.
async function openLineReview(base, artifactId, queue) {
  let dialog = document.getElementById("lineReviewDialog");
  if (dialog) dialog.remove();
  dialog = document.createElement("dialog");
  dialog.id = "lineReviewDialog";
  dialog.className = "line-review-dialog";
  document.body.appendChild(dialog);
  dialog.showModal();
  dialog.addEventListener("close", () => dialog.remove());
  let index = 0, generation = 0;
  const advance = async (resolved) => {
    if (resolved) queue.splice(index, 1);
    else index++;
    if (index >= queue.length) {
      dialog.innerHTML = `<div class="lr-head"><b>Review complete</b><button class="btn-secondary lr-close" type="button">Close</button></div><p>${queue.length ? "Unanswered lines remain flagged. You can review them again or add clearer screenshots." : "All questions in this review have been answered. Any remaining source or completeness errors stay visible on the file."}</p>`;
      dialog.querySelector(".lr-close").onclick = () => dialog.close();
      return;
    }
    await show();
  };
  const show = async () => {
    const token = ++generation;
    dialog.innerHTML = `<div class="lr-head"><b>Loading saved evidence…</b><button class="btn-secondary lr-close" type="button">Close</button></div>`;
    dialog.querySelector(".lr-close").onclick = () => dialog.close();
    let d;
    try { d = await _json(`${base}/artifacts/${artifactId}/review/${queue[index].line}`); }
    catch (error) {
      if (dialog.isConnected) dialog.insertAdjacentHTML("beforeend", `<p class="pf-note bad">${escapeHtml(error.message)}</p>`);
      return;
    }
    if (!dialog.isConnected || token !== generation) return;
    const choices = [...new Set([d.old_text, ...(d.readings || [])])];
    dialog.innerHTML = `<div class="lr-head"><b>${escapeHtml(d.name)} · line ${d.line}</b><button class="btn-secondary lr-close" type="button">Close</button></div>
      <p class="lr-count">Question ${index + 1} of ${queue.length} remaining</p>
      <p>${d.reasons.map(escapeHtml).join(" · ")}</p>
      <div class="lr-evidence"></div>
      <h3>${escapeHtml(d.question)}</h3>
      <p class="project-hint">Compare with the highlighted pixels. Saved readings are suggestions, not confirmed answers.</p>
      <div class="lr-choices" role="group" aria-label="Choose a correction">${choices.map((text, i) => `<button class="btn-secondary" data-choice="${i}" aria-pressed="${i === 0}" type="button">${escapeHtml(_lineEditLabel(d.old_text, text))}${i ? `<small>Alternate saved reading ${i}</small>` : ""}</button>`).join("")}<button class="btn-secondary lr-own" aria-pressed="false" type="button">Enter my own correction</button></div>
      <div class="lr-context-label">Edit line ${d.line} below · the neighbouring lines stay read-only</div>
      <div class="lr-code-block" role="group" aria-label="Edit source line with previous and following lines"><div class="lr-code-lines">${(d.context || [{line:d.line, text:d.old_text, focus:true}]).map(row => `<div class="lr-code-row${row.focus ? " focus" : ""}"><span class="lr-line-number">${row.line}</span>${row.focus ? `<textarea class="lr-text" aria-label="Complete source line" rows="1" wrap="off" spellcheck="false"></textarea>` : `<code>${escapeHtml(row.text) || " "}</code>`}</div>`).join("")}</div></div>
      <p class="project-hint">Selecting an option only previews it. Apply saves your answer; it can be undone.</p>
      <div class="lr-actions"><button class="btn-primary lr-save" type="button">Confirm selected text</button>${d.gap ? '<button class="btn-secondary lr-missing" type="button">Lines are missing here</button>' : ""}<button class="btn-link lr-skip" type="button">Can't tell — next</button></div>
      <div class="lr-result" role="status" aria-live="polite"></div>`;
    dialog.querySelector(".lr-close").onclick = () => dialog.close();
    const input = dialog.querySelector(".lr-text"); input.value = d.old_text;
    const codeLines = dialog.querySelector(".lr-code-lines");
    const fitLines = () => {
      const columns = text => [...text].reduce((column, char) => char === "\t" ? column + 4 - column % 4 : column + 1, 0);
      const width = Math.max(50, columns(input.value), ...(d.context || []).map(row => columns(row.text)));
      codeLines.style.width = `${width + 14}ch`;
    };
    fitLines();
    const updatePreview = (choice) => {
      fitLines();
      dialog.querySelectorAll("[data-choice]").forEach(button => button.setAttribute("aria-pressed", String(+button.dataset.choice === choice)));
      dialog.querySelector(".lr-own").setAttribute("aria-pressed", String(choice === -1));
      dialog.querySelector(".lr-save").textContent = input.value === d.old_text ? "Confirm selected text" : "Apply selected correction";
    };
    dialog.querySelectorAll("[data-choice]").forEach(button => button.onclick = () => {
      input.value = choices[+button.dataset.choice]; updatePreview(+button.dataset.choice);
    });
    dialog.querySelector(".lr-own").onclick = () => { updatePreview(-1); input.focus(); };
    input.addEventListener("beforeinput", event => { if (event.inputType === "insertLineBreak" || event.inputType === "insertParagraph") event.preventDefault(); });
    input.addEventListener("input", () => updatePreview(-1));
    const evidenceBox = dialog.querySelector(".lr-evidence");
    const screenshots = d.screenshots || [];
    const display = (selected) => {
      const ev = screenshots[selected];
      if (!ev) { evidenceBox.innerHTML = `<p class="pf-note bad">No saved screenshot could be reliably matched to this line. The warning stays unresolved unless you supply the exact text. Add a clearer screenshot if needed.</p>`; return; }
      const url = `${base}/evidence/${ev.id}`;
      const band = ev.band;
      const y = band ? Math.max(0, band[0] - 40) : 0;
      const h = band ? Math.min(ev.height - y, band[1] - band[0] + 80) : ev.height;
      const rect = band ? `<rect x="1" y="${band[0] - 3}" width="${ev.width - 2}" height="${band[1] - band[0] + 6}" fill="#facc1526" stroke="#facc15" stroke-width="2"/>` : "";
      evidenceBox.innerHTML = `<div class="lr-frames">${screenshots.map((shot, i) => `<button class="btn-secondary" data-frame="${i}" type="button" aria-pressed="${i === selected}">Screenshot ${shot.frame}</button>`).join("")}</div>
        ${band ? `<svg class="lr-zoom" viewBox="0 ${y} ${ev.width} ${h}" role="img" aria-label="Saved screenshot with line ${d.line} highlighted"><image href="${url}" width="${ev.width}" height="${ev.height}"/>${rect}</svg>` : `<p class="pf-note bad">The screenshot matches the source context, but its exact row could not be measured. No guessed highlight is shown.</p>`}
        <details ${band ? "" : "open"}><summary>Full saved screenshot</summary><svg class="lr-full" viewBox="0 0 ${ev.width} ${ev.height}" role="img" aria-label="Full saved screenshot"><image href="${url}" width="${ev.width}" height="${ev.height}"/>${rect}</svg><a href="${url}" target="_blank" rel="noopener">Open original screenshot</a></details>`;
      evidenceBox.querySelectorAll("[data-frame]").forEach(button => button.onclick = () => display(+button.dataset.frame));
    };
    display(0);
    dialog.querySelector(".lr-skip").onclick = () => advance(false);
    const missingButton = dialog.querySelector(".lr-missing");
    if (missingButton) missingButton.onclick = async () => {
      try {
        const answer = await _json(`${base}/artifacts/${artifactId}/review/${d.line}/missing`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text_hash: d.text_hash }) });
        toast(answer.message || "Marked. Record that part of the screen again.");
        _progSig = "";
        await loadProgram();
        await advance(true);
      } catch (error) { dialog.querySelector(".lr-result").textContent = error.message; }
    };
    const save = async (text) => {
      const buttons = dialog.querySelectorAll(".lr-actions button"); buttons.forEach(button => button.disabled = true);
      const result = dialog.querySelector(".lr-result"); result.textContent = "Saving your answer and checking the file…";
      try {
        const answer = await _json(`${base}/artifacts/${artifactId}/review/${d.line}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ old_text: d.old_text, new_text: text, text_hash: d.text_hash }) });
        _progSig = "";
        await loadProgram();
        if (!dialog.isConnected) return;
        const remaining = answer.review_lines || [];
        const issues = answer.remaining_issues || remaining.filter(item => item.line === d.line);
        if (issues.length || (answer.warnings || []).length) {
          const reasons = [...new Set(issues.flatMap(item => item.reasons || []))];
          result.textContent = `Review completed. Your ${text === d.old_text ? "confirmation" : "correction"} was saved and the file was checked again. ${reasons.length ? `Remaining file issue: ${reasons.join(" ")} ` : ""}${(answer.warnings || []).join(" ")}`;
          dialog.querySelector(".lr-skip").textContent = "Next question";
          dialog.querySelector(".lr-skip").disabled = false;
          dialog.querySelector(".lr-skip").onclick = () => advance(true);
          dialog.querySelector(".lr-save").textContent = "Completed";
          input.disabled = true;
          dialog.querySelectorAll("[data-choice], .lr-own").forEach(button => button.disabled = true);
        } else {
          toast("Review completed. This line’s text warning is resolved.");
          await advance(true);
        }
      } catch (error) {
        result.textContent = error.message;
        buttons.forEach(button => button.disabled = false);
      }
    };
    dialog.querySelector(".lr-save").onclick = () => save(input.value);
  };
  await show();
}


document.addEventListener("visibilitychange", () => {
  if (!document.hidden && _view === "review" && _program) loadProgram(true);
});
