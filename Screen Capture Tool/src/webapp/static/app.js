const $ = (id) => document.getElementById(id);
if (window.mermaid) { try { mermaid.initialize({ startOnLoad: false, theme: "neutral", securityLevel: "loose" }); } catch (e) {} }

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
  return (s || "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function section(label, text, cls) {
  if (!text) return "";
  return `<div class="rsec ${cls||''}"><span class="rsec-label">${label}</span><div class="rsec-body">${escapeHtml(text)}</div></div>`;
}

function reportCard(r) {
  const time = (r.modified || "").replace("T", " ");
  if (r.kind === "report") {
    const isProj = String(r.language || "").toLowerCase() === "project";
    const dlCode = (!isProj && r.code_file)
      ? `<button class="dl" onclick="downloadSaved(this.dataset.f)" data-f="${escapeHtml(r.code_file)}">Download code</button>` : "";
    const dlReport = `<button class="dl secondary" onclick="downloadReport('${r.name}')">Download report</button>`;
    const codeSec = isProj
      ? `<div class="rsec"><span class="rsec-label">Files</span><div class="rsec-body" style="color:var(--muted)">Get the code for each file from the <b>Files</b> section below.</div></div>`
      : `<div class="rsec"><span class="rsec-label">Code</span><pre class="code">${escapeHtml(r.code || "")}</pre></div>`;
    return `<div class="report">
      <div class="report-head">
        <span class="tag code">${escapeHtml(isProj ? "Project" : (r.language || r.extension || "code"))}</span>
        <span class="report-name">${escapeHtml(r.code_file || r.name)}</span>
        <span class="report-time">${time}</span>
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
    : `<p style="font-size:13px;color:var(--muted);margin:6px 0 0">${fmtSize(r.size)} · <button class="dl" onclick="downloadSaved(this.dataset.f)" data-f="${escapeHtml(r.code_file||r.name)}">Download</button></p>`;
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
<title>${_esc(name)} — Code Capture report</title>
<style>
 body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;max-width:880px;margin:36px auto;padding:0 22px;color:#1d1d1f;line-height:1.6}
 h1{font-size:24px;margin:0 0 4px} h2{font-size:16px;margin:28px 0 6px;border-bottom:1px solid #ececef;padding-bottom:5px}
 .meta{color:#6e6e73;font-size:13px;margin:0 0 8px}
 pre{background:#f6f6f8;border:1px solid #e6e6ea;border-radius:10px;padding:12px 14px;overflow:auto;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:13px;white-space:pre-wrap}
 .err{color:#8a4a2c}
</style></head><body>
<h1>Code Capture report</h1>
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
  try {
    const r = await fetch("/api/session/status");
    const d = await r.json();
    renderStatus(d.events || []);
    renderFlow(d.events || []);
    setRunning(d.running);
    const evs = d.events || [];
    const analyzing = d.running && evs.some(e => e.kind === "tool") && !evs.some(e => e.kind === "done" || e.kind === "end");
    if (analyzing) startAnalyzing(); else stopAnalyzing();
    if ((d.events || []).length !== lastEventCount) {
      lastEventCount = (d.events || []).length;
      loadReports();
    }
  } catch (e) {}
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
let pickedRegion = null;   // "L,T,W,H" fractions string, or null = full screen

(function () {
  const modal = $("regionModal"), stage = $("regionStage"), shot = $("regionShot");
  const sel = $("regionSel"), msg = $("regionOverlayMsg");
  const useBtn = $("regionUse"), statusEl = $("regionStatus"), clearBtn = $("clearAreaBtn");
  if (!modal) return;

  let box = null, active = false;   // box = selection coords; active = mouse button held

  function openModal() { modal.style.display = "flex"; }
  function closeModal() { modal.style.display = "none"; box = null; active = false; }

  async function loadShot(delay) {
    shot.style.opacity = ".3";
    msg.textContent = delay ? "Bring your code to the front… snapping in " + delay + "s" : "Loading screenshot…";
    msg.style.display = "block";
    if (delay) { for (let s = delay; s > 0; s--) { msg.textContent = "Bring your code to the front… " + s; await new Promise(r => setTimeout(r, 1000)); } }
    try {
      const res = await fetch("/api/screen.png?notify=1&t=" + Date.now());
      if (!res.ok) throw new Error("screenshot failed");
      const blob = await res.blob();
      shot.src = URL.createObjectURL(blob);
      shot.onload = () => { shot.style.opacity = "1"; msg.style.display = "none"; };
    } catch (e) {
      msg.textContent = "Couldn't grab the screen — grant Screen Recording permission and retry.";
    }
    sel.style.display = "none"; useBtn.disabled = true; box = null; active = false;
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

  stage.addEventListener("mousedown", (e) => {
    active = true;
    box = { x0: e.clientX, y0: e.clientY, x1: e.clientX, y1: e.clientY };
    drawSel(); e.preventDefault();
  });
  window.addEventListener("mousemove", (e) => { if (active && box) { box.x1 = e.clientX; box.y1 = e.clientY; drawSel(); } });
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
  $("regionCancel").addEventListener("click", closeModal);
  $("regionUse").addEventListener("click", () => {
    if (!box) return;
    const f = fractions().map(v => v.toFixed(4));
    pickedRegion = f.join(",");
    statusEl.textContent = "Capturing a selected area only";
    clearBtn.style.display = "";
    closeModal();
    toast("Code area set — burst will capture just that box.");
  });
  clearBtn.addEventListener("click", () => {
    pickedRegion = null;
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
    const r = await fetch("/api/key?value=" + encodeURIComponent(v), { method: "POST" });
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
