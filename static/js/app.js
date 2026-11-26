const APP_EL = document.querySelector(".app");
const USER_ROLE = APP_EL ? (APP_EL.dataset.role || "developer") : "developer";
const IS_DEVOPS = USER_ROLE === "devops";

const state = {
  serverKey: null,
  serviceType: null,
  serviceId: null,
  serviceName: null,
  lines: 100,
  rawLines: [],
  level: "all",
  autoRefresh: false,
  autoRefreshTimer: null,
  dateFrom: null,
  dateTo: null,
  tailOn: true,
  liveOn: false,
  liveSource: null,
};

const TS_PATTERNS = [
  /\b(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2}):(\d{2})/,
  /\b(\d{4})-(\d{2})-(\d{2})/,
];

function parseLineDate(line) {
  for (const re of TS_PATTERNS) {
    const m = line.match(re);
    if (m) {
      const y = +m[1], mo = +m[2] - 1, d = +m[3];
      const h = m[4] ? +m[4] : 0, mi = m[5] ? +m[5] : 0, s = m[6] ? +m[6] : 0;
      const dt = new Date(Date.UTC(y, mo, d, h, mi, s));
      if (!isNaN(dt.getTime())) return dt;
    }
  }
  return null;
}

function inDateRange(line) {
  if (!state.dateFrom && !state.dateTo) return true;
  const dt = parseLineDate(line);
  if (!dt) return false;
  if (state.dateFrom && dt < state.dateFrom) return false;
  if (state.dateTo && dt > state.dateTo) return false;
  return true;
}

const $ = (s) => document.querySelector(s);

function escapeHtml(s) {
  return s.replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

function levelOf(line) {
  if (/\[ERROR\]|ERROR|FATAL|exception/i.test(line)) return "error";
  if (/\[WARN\]|WARN/i.test(line)) return "warn";
  return "info";
}

function colorize(line) {
  const esc = escapeHtml(line);
  return `<span class="lvl-${levelOf(line)}">${esc}</span>`;
}

function highlight(html, term) {
  if (!term) return html;
  const re = new RegExp(`(${term.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")})`, "gi");
  return html.replace(re, '<mark class="match">$1</mark>');
}

function renderLogs() {
  const term = $("#log-search").value.trim();
  const byDate = state.rawLines.filter(inDateRange);
  const byLevel = state.level === "all" ? byDate : byDate.filter((l) => levelOf(l) === state.level);
  const filtered = term ? byLevel.filter((l) => l.toLowerCase().includes(term.toLowerCase())) : byLevel;

  const viewer = $("#log-viewer");
  if (state.rawLines.length === 0) {
    viewer.innerHTML = `<div class="log-placeholder"><div class="icon">&#9646;</div><div class="title">Ready to Monitor</div><div class="sub">Select a service from the panels to view logs</div></div>`;
  } else if (filtered.length === 0) {
    viewer.innerHTML = `<div class="log-placeholder"><div class="title">No matching lines</div><div class="sub">Adjust the filter, date range, or search term.</div></div>`;
  } else {
    viewer.innerHTML = filtered.map((l) => highlight(colorize(l), term)).join("\n");
    if (state.tailOn) viewer.scrollTop = viewer.scrollHeight;
  }

  const c = { error: 0, warn: 0, info: 0 };
  byDate.forEach((l) => c[levelOf(l)]++);
  $("#count-error").textContent = `${c.error} Errors`;
  $("#count-warn").textContent = `${c.warn} Warnings`;
  $("#count-info").textContent = `${c.info} Info`;
  $("#count-total").textContent = `${byDate.length} Total`;

  renderDateStatus(byDate.length);
}

function fmtYMD(d) {
  return `${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, "0")}-${String(d.getUTCDate()).padStart(2, "0")}`;
}

function fmtISO(d) {
  // YYYY-MM-DDTHH:MM:SS (UTC, no timezone suffix)
  const p = (n) => String(n).padStart(2, "0");
  return `${d.getUTCFullYear()}-${p(d.getUTCMonth() + 1)}-${p(d.getUTCDate())}T${p(d.getUTCHours())}:${p(d.getUTCMinutes())}:${p(d.getUTCSeconds())}`;
}

const PRESET_SECONDS = {
  "5m": 5 * 60,
  "15m": 15 * 60,
  "1h": 60 * 60,
  "6h": 6 * 60 * 60,
  "24h": 24 * 60 * 60,
  "7d": 7 * 24 * 60 * 60,
};

const PRESET_LABEL = {
  "5m": "Last 5 minutes",
  "15m": "Last 15 minutes",
  "1h": "Last 1 hour",
  "6h": "Last 6 hours",
  "24h": "Last 24 hours",
  "7d": "Last 7 days",
};

function renderDateStatus(inRangeCount) {
  const el = $("#dr-status");
  const sel = $("#time-range").value;
  if (sel === "all" || (!state.dateFrom && !state.dateTo)) {
    el.textContent = "All time";
    el.classList.remove("active");
    return;
  }
  const from = state.dateFrom ? fmtISO(state.dateFrom) + "Z" : "...";
  const to = state.dateTo ? fmtISO(state.dateTo) + "Z" : "now";
  el.textContent = `${from} → ${to}  ·  ${inRangeCount}/${state.rawLines.length} in range`;
  el.classList.add("active");
}

function applyTimeRange() {
  const sel = $("#time-range").value;
  const custom = $("#custom-range");
  if (sel === "custom") {
    custom.hidden = false;
    return;
  }
  custom.hidden = true;

  if (sel === "all") {
    state.dateFrom = null;
    state.dateTo = null;
  } else if (PRESET_SECONDS[sel]) {
    const now = new Date();
    state.dateFrom = new Date(now.getTime() - PRESET_SECONDS[sel] * 1000);
    state.dateTo = null;
  }

  if (state.serviceType) {
    loadLogs(state.serviceType, state.serviceId, state.serviceName);
  } else {
    renderLogs();
  }
}

function applyCustomRange() {
  const fromRaw = $("#date-from").value;
  const toRaw = $("#date-to").value;
  state.dateFrom = fromRaw ? new Date(fromRaw + "Z") : null;
  state.dateTo = toRaw ? new Date(toRaw + "Z") : null;
  if (state.serviceType) {
    loadLogs(state.serviceType, state.serviceId, state.serviceName);
  } else {
    renderLogs();
  }
}

async function loadServices() {
  state.serverKey = $("#server-select").value;
  if (!state.serverKey) return;

  $("#pm2-list").innerHTML = '<div class="empty-box">Loading...</div>';
  $("#docker-list").innerHTML = '<div class="empty-box">Loading...</div>';

  const res = await fetch(`/api/servers/${state.serverKey}/services`);
  const data = await res.json();

  const pm2Running = data.pm2.filter((p) => p.status === "online").length;
  $("#pm2-count").textContent = `${pm2Running} / ${data.pm2.length}`;

  const dockerRunning = data.docker.filter((c) => /^Up/i.test(c.status)).length;
  $("#docker-count").textContent = `${dockerRunning} / ${data.docker.length}`;

  $("#pm2-list").innerHTML = data.pm2.length === 0
    ? '<div class="empty-box">No PM2 processes</div>'
    : renderPm2Group(data.pm2);

  $("#docker-list").innerHTML = data.docker.length === 0
    ? '<div class="empty-box">No services found</div>'
    : data.docker.map(renderDockerCard).join("");

  bindServiceClicks();
}

function renderPm2Group(list) {
  const running = list.filter((p) => p.status === "online");
  const stopped = list.filter((p) => p.status !== "online");
  let html = "";
  if (running.length) {
    html += `<div class="group-head"><span class="group-dot running"></span>Running<span class="group-count">${running.length}</span></div>`;
    html += running.map(renderPm2Card).join("");
  }
  if (stopped.length) {
    html += `<div class="group-head"><span class="group-dot" style="background:var(--error)"></span>Stopped<span class="group-count">${stopped.length}</span></div>`;
    html += stopped.map(renderPm2Card).join("");
  }
  return html;
}

function renderPm2Card(p) {
  const statusClass = p.status === "online" ? "status-running" : "status-stopped";
  const imageValue = p.interpreter_path ? escapeHtml(p.interpreter_path) : "none";
  const adminIcons = IS_DEVOPS ? `
      <button class="svc-icon-btn icon-restart" data-action="restart" data-id="${p.id}" data-name="${escapeHtml(p.name)}" title="Restart process">&#x21bb;</button>
      <button class="svc-icon-btn icon-stop" data-action="stop" data-id="${p.id}" data-name="${escapeHtml(p.name)}" title="Stop process">&#9632;</button>
    ` : "";
  return `
    <div class="service-card" data-type="pm2" data-id="${p.id}" data-name="${escapeHtml(p.name)}">
      <div class="service-card-head">
        <span class="service-icon">&#9889;</span>
        <span class="service-name">${escapeHtml(p.name)}</span>
      </div>
      <div class="service-meta">
        <div><b>ID:</b>${p.id}</div>
        <div><b>Status:</b><span class="${statusClass}">${p.status}</span></div>
        <div><b>Image:</b>Node.js - <span class="image-path">${imageValue}</span></div>
        <div><b>Memory:</b>${p.memory_mb} MB · <b>Restarts:</b>${p.restarts}</div>
      </div>
      <div class="svc-actions">
        <button class="svc-icon-btn icon-download" data-action="download" data-id="${p.id}" data-name="${escapeHtml(p.name)}" title="Download logs">&#128190;</button>
        <button class="svc-icon-btn icon-browse" data-action="browse" data-id="${p.id}" data-name="${escapeHtml(p.name)}" title="Browse log files">&#128193;</button>
        ${adminIcons}
      </div>
    </div>`;
}

function renderDockerCard(c) {
  const isUp = /^Up/i.test(c.status);
  const statusClass = isUp ? "status-running" : "status-exited";
  return `
    <div class="service-card" data-type="docker" data-id="${c.id}" data-name="${escapeHtml(c.name)}">
      <div class="service-card-head">
        <span class="service-icon docker">&#9873;</span>
        <span class="service-name">${escapeHtml(c.name)}</span>
      </div>
      <div class="service-meta">
        <div><b>ID:</b><span class="image-path">${c.id.slice(0, 12)}</span></div>
        <div><b>Status:</b><span class="${statusClass}">${escapeHtml(c.status)}</span></div>
        <div><b>Image:</b><span class="image-path">${escapeHtml(c.image)}</span></div>
      </div>
    </div>`;
}

function bindServiceClicks() {
  document.querySelectorAll(".service-card").forEach((el) => {
    el.addEventListener("click", (e) => {
      if (e.target.closest(".svc-icon-btn")) return;
      document.querySelectorAll(".service-card").forEach((s) => s.classList.remove("active"));
      el.classList.add("active");
      loadLogs(el.dataset.type, el.dataset.id, el.dataset.name);
    });
  });

  document.querySelectorAll(".svc-icon-btn").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      const { action, id, name } = btn.dataset;
      if (action === "download") downloadServiceLogs(id, name);
      else if (action === "browse") browseServiceFiles(id, name);
      else if (action === "restart") restartProcess(id, name);
      else if (action === "stop") stopProcess(id, name);
    });
  });
}

async function downloadServiceLogs(id, name) {
  const res = await fetch(`/api/servers/${state.serverKey}/logs/pm2/${id}?lines=10000`);
  const data = await res.json();
  const blob = new Blob([(data.lines || []).join("\n")], { type: "text/plain" });
  downloadBlob(blob, `${name}.log`);
}

async function browseServiceFiles(id, name) {
  const res = await fetch(`/api/servers/${state.serverKey}/pm2/${id}/files`);
  if (!res.ok) {
    alert(`Could not list files: ${res.status}`);
    return;
  }
  const data = await res.json();
  const files = data.files || [];
  const body = files.length === 0
    ? '<div style="color:var(--muted);padding:12px 0">No log files found for this process.</div>'
    : `<table class="modal-table">
         <thead><tr><th>File</th><th style="text-align:right">Size</th></tr></thead>
         <tbody>${files.map((f) => `
           <tr><td class="row-mono">${escapeHtml(f.name)}</td><td style="text-align:right" class="row-mono">${f.size_kb} KB</td></tr>
         `).join("")}</tbody>
       </table>`;
  openModal(`Log files — ${name}`, body);
}

async function restartProcess(id, name) {
  if (!confirm(`Restart PM2 process '${name}' (id ${id})?`)) return;
  const res = await fetch(`/api/servers/${state.serverKey}/pm2/${id}/restart`, { method: "POST" });
  const data = await res.json();
  flashCardMsg(id, data.ok ? "Restarted" : `Failed: ${data.output || res.statusText}`);
  setTimeout(loadServices, 800);
}

async function stopProcess(id, name) {
  if (!confirm(`Stop PM2 process '${name}' (id ${id})?`)) return;
  const res = await fetch(`/api/servers/${state.serverKey}/pm2/${id}/stop`, { method: "POST" });
  const data = await res.json();
  flashCardMsg(id, data.ok ? "Stopped" : `Failed: ${data.output || res.statusText}`);
  setTimeout(loadServices, 800);
}

function flashCardMsg(id, msg) {
  const card = document.querySelector(`.service-card[data-type="pm2"][data-id="${id}"]`);
  if (!card) return;
  let flash = card.querySelector(".svc-flash");
  if (!flash) {
    flash = document.createElement("div");
    flash.className = "svc-flash";
    card.appendChild(flash);
  }
  flash.textContent = msg;
  clearTimeout(flash._t);
  flash._t = setTimeout(() => flash.remove(), 2000);
}

function openModal(title, bodyHtml) {
  let modal = document.getElementById("lv-modal");
  if (!modal) {
    modal = document.createElement("div");
    modal.id = "lv-modal";
    modal.className = "lv-modal";
    modal.innerHTML = `
      <div class="lv-modal-backdrop"></div>
      <div class="lv-modal-card">
        <div class="lv-modal-head"><h3 id="lv-modal-title"></h3><button class="lv-modal-close">&times;</button></div>
        <div class="lv-modal-body" id="lv-modal-body"></div>
      </div>`;
    document.body.appendChild(modal);
    modal.querySelector(".lv-modal-close").addEventListener("click", () => (modal.hidden = true));
    modal.querySelector(".lv-modal-backdrop").addEventListener("click", () => (modal.hidden = true));
  }
  document.getElementById("lv-modal-title").textContent = title;
  document.getElementById("lv-modal-body").innerHTML = bodyHtml;
  modal.hidden = false;
}

async function loadLogs(type, id, name) {
  state.serviceType = type;
  state.serviceId = id;
  state.serviceName = name;
  state.lines = parseInt($("#lines-select").value, 10);
  $("#logs-title-text").textContent = `Logs — ${name}`;
  $("#log-viewer").innerHTML = '<div class="log-placeholder"><div class="title">Loading...</div></div>';
  const params = new URLSearchParams({ lines: String(state.lines) });
  if (state.dateFrom) params.set("from", fmtYMD(state.dateFrom));
  if (state.dateTo) params.set("to", fmtYMD(state.dateTo));
  const res = await fetch(`/api/servers/${state.serverKey}/logs/${type}/${id}?${params.toString()}`);
  const data = await res.json();
  state.rawLines = data.lines || [];
  renderLogs();
}

function flashNotice(msg) {
  const btn = $("#btn-copy");
  const original = btn.textContent;
  btn.textContent = msg;
  setTimeout(() => (btn.textContent = original), 1200);
}

$("#server-select").addEventListener("change", loadServices);
$("#lines-select").addEventListener("change", () => {
  if (state.serviceType) loadLogs(state.serviceType, state.serviceId, state.serviceName);
});
$("#log-search").addEventListener("input", renderLogs);
$("#btn-search").addEventListener("click", renderLogs);
$("#btn-clear").addEventListener("click", () => { $("#log-search").value = ""; renderLogs(); });

$("#time-range").addEventListener("change", applyTimeRange);
$("#btn-apply-custom").addEventListener("click", applyCustomRange);

function setTail(on) {
  state.tailOn = on;
  const btn = $("#btn-tail");
  btn.textContent = `Tail: ${on ? "ON" : "OFF"}`;
  btn.classList.toggle("active", on);
  if (on) {
    const v = $("#log-viewer");
    v.scrollTop = v.scrollHeight;
  }
}

function setLive(on) {
  state.liveOn = on;
  const btn = $("#btn-live");
  btn.classList.toggle("live-on", on);
  btn.classList.toggle("live-off", !on);
  btn.textContent = `Live: ${on ? "ON" : "OFF"}`;

  if (on) {
    if (!state.serviceType) {
      flashNotice("Pick a service first");
      setLive(false);
      return;
    }
    openLiveStream();
  } else {
    closeLiveStream();
  }
}

function openLiveStream() {
  closeLiveStream();
  const url = `/api/servers/${state.serverKey}/logs/${state.serviceType}/${state.serviceId}/stream`;
  const es = new EventSource(url);
  state.liveSource = es;
  es.addEventListener("line", (ev) => {
    state.rawLines.push(ev.data);
    if (state.rawLines.length > 5000) state.rawLines = state.rawLines.slice(-5000);
    renderLogs();
  });
  es.addEventListener("error", () => {
    closeLiveStream();
    const btn = $("#btn-live");
    btn.classList.remove("live-on");
    btn.classList.add("live-off");
    btn.textContent = "Live: OFF";
    state.liveOn = false;
    flashNotice("Live stream ended");
  });
}

function closeLiveStream() {
  if (state.liveSource) {
    state.liveSource.close();
    state.liveSource = null;
  }
}

$("#btn-tail").addEventListener("click", () => setTail(!state.tailOn));
$("#btn-live").addEventListener("click", () => setLive(!state.liveOn));

document.querySelectorAll(".filter-chip").forEach((chip) => {
  chip.addEventListener("click", () => {
    document.querySelectorAll(".filter-chip").forEach((c) => c.classList.remove("active"));
    chip.classList.add("active");
    state.level = chip.dataset.level;
    renderLogs();
  });
});

$("#btn-reload").addEventListener("click", loadServices);
$("#btn-refresh").addEventListener("click", () => {
  if (state.serviceType) loadLogs(state.serviceType, state.serviceId, state.serviceName);
});

$("#btn-autorefresh").addEventListener("click", () => {
  state.autoRefresh = !state.autoRefresh;
  const btn = $("#btn-autorefresh");
  if (state.autoRefresh) {
    btn.textContent = "Auto-Refresh: ON";
    btn.classList.remove("btn-outline-info");
    btn.classList.add("btn-primary");
    state.autoRefreshTimer = setInterval(() => {
      if (state.serviceType) loadLogs(state.serviceType, state.serviceId, state.serviceName);
    }, 5000);
  } else {
    btn.textContent = "Auto-Refresh: OFF";
    btn.classList.add("btn-outline-info");
    btn.classList.remove("btn-primary");
    clearInterval(state.autoRefreshTimer);
  }
});

$("#btn-copy").addEventListener("click", async () => {
  if (!state.rawLines.length) return;
  await navigator.clipboard.writeText(state.rawLines.join("\n"));
  flashNotice("Copied!");
});

$("#btn-export-txt").addEventListener("click", () => {
  if (!state.rawLines.length) return;
  const blob = new Blob([state.rawLines.join("\n")], { type: "text/plain" });
  downloadBlob(blob, `${state.serviceName || "logs"}.txt`);
});

$("#btn-export-json").addEventListener("click", () => {
  if (!state.rawLines.length) return;
  const payload = { server: state.serverKey, service: state.serviceName, type: state.serviceType, lines: state.rawLines };
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
  downloadBlob(blob, `${state.serviceName || "logs"}.json`);
});

function downloadBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url; a.download = filename; a.click();
  URL.revokeObjectURL(url);
}

const adminBtn = $("#btn-admin");
if (adminBtn) adminBtn.addEventListener("click", () => { window.location.href = "/admin"; });

["btn-clear-cache", "btn-download", "btn-search-all", "btn-show-errors", "btn-activity", "btn-expand"].forEach((id) => {
  const el = $("#" + id);
  if (el) el.addEventListener("click", () => flashNotice("Coming soon"));
});

if ($("#server-select").value) loadServices();
