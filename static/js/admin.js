const $ = (s) => document.querySelector(s);
const $$ = (s) => document.querySelectorAll(s);

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

function switchTab(name) {
  $$(".admin-nav-item").forEach((b) => b.classList.toggle("active", b.dataset.tab === name));
  $$(".admin-tab").forEach((s) => (s.hidden = s.dataset.tab !== name));
}

$$(".admin-nav-item").forEach((b) => b.addEventListener("click", () => switchTab(b.dataset.tab)));

async function loadServers() {
  const res = await fetch("/api/admin/servers");
  const servers = await res.json();
  const tbody = $("#server-rows");
  $("#stat-servers").textContent = servers.length;
  $("#nav-servers-count").textContent = servers.length;
  if (servers.length === 0) {
    tbody.innerHTML = '<tr><td colspan="6" class="empty-row">No servers configured yet.</td></tr>';
    return;
  }
  tbody.innerHTML = servers.map((s) => {
    const bastion = s.bastion && s.bastion.host
      ? `<span class="row-mono">${escapeHtml(s.bastion.username || "")}@${escapeHtml(s.bastion.host)}</span>`
      : '<span style="color:var(--muted)">direct</span>';
    return `
    <tr>
      <td class="row-name">${escapeHtml(s.label)}</td>
      <td class="row-mono">${escapeHtml(s.host)}${s.port && s.port !== 22 ? ":" + s.port : ""}</td>
      <td class="row-mono">${escapeHtml(s.username)}</td>
      <td>${bastion}</td>
      <td class="row-mono">${escapeHtml(s.pm2_path || "auto-detect")}</td>
      <td style="text-align:right"><button class="btn-remove" data-key="${escapeHtml(s.key)}">Remove</button></td>
    </tr>`;
  }).join("");

  $$(".btn-remove").forEach((btn) => btn.addEventListener("click", async () => {
    if (!confirm(`Remove server '${btn.dataset.key}'? Any user access grants to it will be wiped.`)) return;
    const res = await fetch(`/api/admin/servers/${encodeURIComponent(btn.dataset.key)}`, { method: "DELETE" });
    if (res.ok) {
      loadServers();
    } else {
      alert("Remove failed");
    }
  }));
}

function setMsg(text, kind) {
  const el = $("#form-msg");
  el.textContent = text;
  el.className = "form-msg " + (kind || "");
}

function _authPayload(prefix) {
  const mode = document.querySelector(`input[name="${prefix}-auth"]:checked`).value;
  if (mode === "key") {
    return {
      key: $(`#${prefix}-key`).value,
      key_passphrase: $(`#${prefix}-key-passphrase`).value,
    };
  }
  return { password: $(`#${prefix}-password`).value };
}

async function readForm() {
  const body = {
    label: $("#srv-label").value.trim(),
    host: $("#srv-host").value.trim(),
    username: $("#srv-username").value.trim(),
    pm2_path: $("#srv-pm2path").value.trim(),
    ...(_authPayload("srv")),
  };
  if ($("#chk-bastion").checked) {
    body.bastion = {
      host: $("#bst-host").value.trim(),
      username: $("#bst-username").value.trim(),
      ...(_authPayload("bst")),
    };
  }
  return body;
}

function _bindAuthToggle(prefix) {
  document.querySelectorAll(`input[name="${prefix}-auth"]`).forEach((radio) => {
    radio.addEventListener("change", () => {
      $(`#${prefix}-auth-password`).hidden = radio.value !== "password";
      $(`#${prefix}-auth-key`).hidden = radio.value !== "key";
    });
  });
}
_bindAuthToggle("srv");
_bindAuthToggle("bst");

$("#chk-bastion").addEventListener("change", (e) => {
  $("#bastion-fields").hidden = !e.target.checked;
});

function _hasAuth(body) {
  return (body.password && body.password.length) || (body.key && body.key.trim().length);
}

$("#btn-test").addEventListener("click", async () => {
  const body = await readForm();
  if (!body.host || !body.username || !_hasAuth(body)) {
    setMsg("host, username, and (password or private key) required to test", "err");
    return;
  }
  if (body.bastion && (!body.bastion.host || !body.bastion.username || !_hasAuth(body.bastion))) {
    setMsg("bastion needs host, username, and (password or private key)", "err");
    return;
  }
  setMsg("Testing...", "");
  try {
    const res = await fetch("/api/admin/servers/test", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await res.json();
    if (data.ok) {
      setMsg(`OK — ${data.probe.split("\n")[0].slice(0, 80)}`, "ok");
    } else {
      setMsg(`Failed: ${data.error}`, "err");
    }
  } catch (e) {
    setMsg(`Error: ${e.message}`, "err");
  }
});

$("#btn-add-server").addEventListener("click", async () => {
  const body = await readForm();
  if (!body.label || !body.host || !body.username || !_hasAuth(body)) {
    setMsg("label, host, username, and (password or private key) required", "err");
    return;
  }
  if (body.bastion && (!body.bastion.host || !body.bastion.username || !_hasAuth(body.bastion))) {
    setMsg("bastion needs host, username, and (password or private key)", "err");
    return;
  }
  setMsg("Saving...", "");
  try {
    const res = await fetch("/api/admin/servers", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (res.ok) {
      setMsg("Server added", "ok");
      ["srv-label", "srv-host", "srv-username", "srv-password", "srv-key", "srv-key-passphrase", "srv-pm2path",
       "bst-host", "bst-username", "bst-password", "bst-key", "bst-key-passphrase"].forEach((id) => {
        const el = $("#" + id);
        if (el) el.value = "";
      });
      loadServers();
    } else {
      const err = await res.json().catch(() => ({}));
      setMsg(`Failed: ${err.description || res.statusText}`, "err");
    }
  } catch (e) {
    setMsg(`Error: ${e.message}`, "err");
  }
});

/* =============== USERS TAB =============== */

function setUserMsg(text, kind) {
  const el = $("#user-msg");
  el.textContent = text;
  el.className = "form-msg " + (kind || "");
}

function accessBadge(role, grantsCount) {
  if (role === "devops") return '<span class="access-pill all">Everything</span>';
  if (grantsCount > 0) return `<span class="access-pill some">${grantsCount} granted</span>`;
  return '<span class="access-pill none">No access</span>';
}

function roleCell(u) {
  if (u.role === "devops") return '<span class="role-pill">devops</span>';
  return `
    <select class="role-select" data-user="${escapeHtml(u.username)}">
      <option value="developer" selected>developer</option>
      <option value="devops">devops</option>
    </select>`;
}

async function loadUsers() {
  const res = await fetch("/api/admin/users");
  const data = await res.json();
  $("#stat-devops").textContent = data.counts.devops;
  $("#stat-developers").textContent = data.counts.developer;
  $("#nav-users-count").textContent = data.users.length;

  const tbody = $("#user-rows");
  if (!data.users.length) {
    tbody.innerHTML = '<tr><td colspan="4" class="empty-row">No users yet — create your first one above.</td></tr>';
    return;
  }
  tbody.innerHTML = data.users.map((u) => `
    <tr>
      <td class="row-name">${escapeHtml(u.username)}</td>
      <td>${roleCell(u)}</td>
      <td>${accessBadge(u.role, u.grants_count)}</td>
      <td>
        <div class="user-row-actions">
          <button class="btn-mini" data-act="reset" data-user="${escapeHtml(u.username)}">Reset password</button>
          ${u.role === "devops" ? "" : `<button class="btn-mini" data-act="access" data-user="${escapeHtml(u.username)}">Access</button>`}
          ${u.role === "devops" ? "" : `<button class="btn-mini btn-mini-danger" data-act="delete" data-user="${escapeHtml(u.username)}">Delete</button>`}
        </div>
      </td>
    </tr>`).join("");

  bindUserRowActions();
}

function bindUserRowActions() {
  $$(".role-select").forEach((sel) => sel.addEventListener("change", async () => {
    const username = sel.dataset.user;
    const role = sel.value;
    const res = await fetch(`/api/admin/users/${encodeURIComponent(username)}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ role }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      setUserMsg(`Role change failed: ${err.error || res.statusText}`, "err");
    } else {
      setUserMsg(`Role updated for ${username}`, "ok");
    }
    loadUsers();
  }));

  $$('[data-act="reset"]').forEach((btn) => btn.addEventListener("click", async () => {
    const username = btn.dataset.user;
    const pw = prompt(`New password for ${username} (min 6):`);
    if (pw === null) return;
    const res = await fetch(`/api/admin/users/${encodeURIComponent(username)}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ password: pw }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      setUserMsg(`Reset failed: ${err.error || res.statusText}`, "err");
    } else {
      setUserMsg(`Password reset for ${username}`, "ok");
    }
  }));

  $$('[data-act="access"]').forEach((btn) => btn.addEventListener("click", async () => {
    const username = btn.dataset.user;
    switchTab("access");
    await loadAccessUsers();
    const sel = $("#access-user");
    if ([...sel.options].some((o) => o.value === username)) {
      sel.value = username;
      onAccessUserChange();
    }
  }));

  $$('[data-act="delete"]').forEach((btn) => btn.addEventListener("click", async () => {
    const username = btn.dataset.user;
    if (!confirm(`Delete user '${username}'? This cannot be undone.`)) return;
    const res = await fetch(`/api/admin/users/${encodeURIComponent(username)}`, { method: "DELETE" });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      setUserMsg(`Delete failed: ${err.error || res.statusText}`, "err");
    } else {
      setUserMsg(`User '${username}' deleted`, "ok");
    }
    loadUsers();
  }));
}

$("#btn-add-user").addEventListener("click", async () => {
  const body = {
    username: $("#usr-username").value.trim(),
    password: $("#usr-password").value,
    role: $("#usr-role").value,
  };
  if (!body.username || !body.password) {
    setUserMsg("username and password required", "err");
    return;
  }
  setUserMsg("Creating...", "");
  const res = await fetch("/api/admin/users", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (res.ok) {
    setUserMsg(`User '${body.username}' created`, "ok");
    $("#usr-username").value = "";
    $("#usr-password").value = "";
    $("#usr-role").value = "developer";
    loadUsers();
  } else {
    const err = await res.json().catch(() => ({}));
    setUserMsg(`Failed: ${err.error || res.statusText}`, "err");
  }
});

/* =============== ACCESS TAB =============== */

const accessState = {
  username: null,
  inventory: [],
  selection: {},
};

function switchTabAndMaybePreselect() {
  const params = new URLSearchParams(window.location.search);
  const tab = params.get("tab");
  const user = params.get("user");
  if (tab) switchTab(tab);
  if (tab === "access" && user) {
    loadAccessUsers().then(() => {
      $("#access-user").value = user;
      onAccessUserChange();
    });
  }
}

async function loadAccessUsers() {
  const res = await fetch("/api/admin/users");
  const data = await res.json();
  const devs = data.users.filter((u) => u.role === "developer");
  const sel = $("#access-user");
  if (!devs.length) {
    sel.innerHTML = '<option disabled selected>No developer users yet</option>';
    return;
  }
  sel.innerHTML = devs
    .map((u) => `<option value="${escapeHtml(u.username)}">${escapeHtml(u.username)}</option>`)
    .join("");
}

async function fetchAccess(username) {
  const res = await fetch(`/api/admin/access/${encodeURIComponent(username)}`);
  return res.json();
}

function initSelectionFromInventory() {
  const sel = {};
  for (const srv of accessState.inventory) {
    const g = srv.grants || { pm2: [], docker: [] };
    sel[srv.key] = {
      pm2: new Set(g.pm2 || []),
      docker: new Set(g.docker || []),
    };
  }
  accessState.selection = sel;
}

function countGranted() {
  let total = 0;
  for (const srv of Object.values(accessState.selection)) {
    total += srv.pm2.size + srv.docker.size;
  }
  return total;
}

function countServices() {
  return accessState.inventory.reduce((n, srv) => n + srv.pm2.length + srv.docker.length, 0);
}

function renderAccessStats() {
  $("#access-stat-granted").textContent = countGranted();
  $("#access-stat-services").textContent = countServices();
  $("#access-stat-servers").textContent = accessState.inventory.length;

  const total = countGranted();
  const footer = $("#access-footer");
  footer.hidden = false;
  if (total === 0) {
    $("#access-footer-msg").innerHTML =
      '<span class="access-nothing-ticked">Nothing ticked</span> — this user would see an empty dashboard.';
  } else {
    $("#access-footer-msg").innerHTML =
      `<span class="access-some-ticked">${total} granted</span> across ${accessState.inventory.length} servers.`;
  }
}

function serverBadge(selected, totalCount) {
  if (totalCount === 0) return '<span class="server-block-badge none">No services</span>';
  if (selected === 0) return '<span class="server-block-badge none">No access</span>';
  if (selected === totalCount) return '<span class="server-block-badge all">Everything</span>';
  return `<span class="server-block-badge some">${selected} granted</span>`;
}

function renderChip(serverKey, type, name, checked) {
  const cls = checked ? "svc-chip checked" : "svc-chip";
  const nameCls = type === "docker" ? "svc-chip-name docker" : "svc-chip-name";
  return `
    <div class="${cls}" data-server="${escapeHtml(serverKey)}" data-type="${type}" data-name="${escapeHtml(name)}">
      <span class="${nameCls}">${escapeHtml(name)}</span>
      <span class="svc-chip-check"></span>
    </div>`;
}

function renderAccessBody() {
  const body = $("#access-body");
  if (accessState.inventory.length === 0) {
    body.innerHTML = '<div class="placeholder-card">No servers configured. Add a server in the Servers tab first.</div>';
    return;
  }
  body.innerHTML = accessState.inventory.map((srv) => {
    const srvSel = accessState.selection[srv.key] || { pm2: new Set(), docker: new Set() };
    const selectedCount = srvSel.pm2.size + srvSel.docker.size;
    const totalCount = srv.pm2.length + srv.docker.length;

    const pm2All = srv.pm2.length > 0 && srv.pm2.every((n) => srvSel.pm2.has(n));
    const dockerAll = srv.docker.length > 0 && srv.docker.every((n) => srvSel.docker.has(n));

    let groups = "";
    if (!srv.reachable) {
      groups = `<div class="svc-error">Unreachable: ${escapeHtml(srv.error || "ssh error")}</div>`;
    } else {
      const pm2Chips = srv.pm2.length
        ? `<div class="svc-grid">${srv.pm2.map((n) => renderChip(srv.key, "pm2", n, srvSel.pm2.has(n))).join("")}</div>`
        : '<div class="svc-empty">No PM2 processes on this server.</div>';
      const dockerChips = srv.docker.length
        ? `<div class="svc-grid">${srv.docker.map((n) => renderChip(srv.key, "docker", n, srvSel.docker.has(n))).join("")}</div>`
        : '<div class="svc-empty">No Docker containers on this server.</div>';

      groups = `
        <div class="svc-group">
          <div class="svc-group-head">
            <span class="svc-group-label">PM2 Apps</span>
            <div class="svc-group-toggle" data-grant-all="${escapeHtml(srv.key)}" data-type="pm2">
              <div class="toggle ${pm2All ? "on" : ""}"></div>
              <span class="svc-toggle-text">Grant all</span>
            </div>
          </div>
          ${pm2Chips}
        </div>
        <div class="svc-group">
          <div class="svc-group-head">
            <span class="svc-group-label">Docker Containers</span>
            <div class="svc-group-toggle" data-grant-all="${escapeHtml(srv.key)}" data-type="docker">
              <div class="toggle ${dockerAll ? "on" : ""}"></div>
              <span class="svc-toggle-text">Grant all</span>
            </div>
          </div>
          ${dockerChips}
        </div>`;
    }

    return `
      <div class="server-block">
        <div class="server-block-head">
          <div>
            <div class="server-block-name">${escapeHtml(srv.label || srv.key)}</div>
            <div class="server-block-host">${escapeHtml(srv.username || "")}@${escapeHtml(srv.host || "")}</div>
          </div>
          ${serverBadge(selectedCount, totalCount)}
        </div>
        ${groups}
      </div>`;
  }).join("");

  bindAccessChips();
}

function bindAccessChips() {
  $$(".svc-chip").forEach((chip) => chip.addEventListener("click", () => {
    const { server, type, name } = chip.dataset;
    const sel = accessState.selection[server];
    if (!sel) return;
    if (sel[type].has(name)) sel[type].delete(name);
    else sel[type].add(name);
    renderAccessBody();
    renderAccessStats();
  }));

  $$("[data-grant-all]").forEach((toggle) => toggle.addEventListener("click", () => {
    const serverKey = toggle.dataset.grantAll;
    const type = toggle.dataset.type;
    const srv = accessState.inventory.find((s) => s.key === serverKey);
    if (!srv) return;
    const sel = accessState.selection[serverKey];
    const names = srv[type];
    const allOn = names.length > 0 && names.every((n) => sel[type].has(n));
    if (allOn) {
      names.forEach((n) => sel[type].delete(n));
    } else {
      names.forEach((n) => sel[type].add(n));
    }
    renderAccessBody();
    renderAccessStats();
  }));
}

async function onAccessUserChange() {
  const username = $("#access-user").value;
  if (!username) return;
  accessState.username = username;
  $("#access-body").innerHTML = '<div class="placeholder-card">Loading services...</div>';
  const data = await fetchAccess(username);
  accessState.inventory = data.inventory || [];
  initSelectionFromInventory();
  renderAccessBody();
  renderAccessStats();
}

$("#access-user").addEventListener("change", onAccessUserChange);

$("#btn-access-reload").addEventListener("click", () => {
  if (accessState.username) onAccessUserChange();
});

$("#btn-access-revoke").addEventListener("click", () => {
  if (!accessState.username) return;
  if (!confirm(`Revoke ALL access for ${accessState.username}?`)) return;
  for (const srv of Object.values(accessState.selection)) {
    srv.pm2.clear();
    srv.docker.clear();
  }
  renderAccessBody();
  renderAccessStats();
});

$("#btn-access-save").addEventListener("click", async () => {
  if (!accessState.username) return;
  const allowed = {};
  for (const [serverKey, sel] of Object.entries(accessState.selection)) {
    const pm2 = [...sel.pm2];
    const docker = [...sel.docker];
    if (pm2.length || docker.length) {
      allowed[serverKey] = { pm2, docker };
    }
  }
  const btn = $("#btn-access-save");
  const original = btn.textContent;
  btn.textContent = "Saving...";
  const res = await fetch(`/api/admin/access/${encodeURIComponent(accessState.username)}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ allowed }),
  });
  if (res.ok) {
    btn.textContent = "Saved!";
    setTimeout(() => (btn.textContent = original), 1200);
  } else {
    btn.textContent = "Save failed";
    setTimeout(() => (btn.textContent = original), 1500);
  }
});

/* =============== ACTIVITY TAB =============== */

const DESTRUCTIVE_ACTIONS = new Set(["delete_server", "delete_user", "logout"]);
const NEUTRAL_ACTIONS = new Set([]);

function actionClass(action) {
  if (DESTRUCTIVE_ACTIONS.has(action)) return "act-action destructive";
  if (NEUTRAL_ACTIONS.has(action)) return "act-action neutral";
  return "act-action";
}

function renderDetails(details) {
  if (!details || typeof details !== "object") return "";
  const parts = [];
  for (const [k, v] of Object.entries(details)) {
    if (v === "" || v === null || v === undefined) continue;
    parts.push(`<span class="kv"><b>${escapeHtml(k)}=</b>${escapeHtml(String(v))}</span>`);
  }
  return parts.join("");
}

async function loadActivity() {
  const res = await fetch("/api/admin/activity?limit=500");
  const entries = await res.json();
  const tbody = $("#activity-rows");
  if (!entries.length) {
    tbody.innerHTML = '<tr><td colspan="4" class="empty-row">No activity recorded yet.</td></tr>';
    return;
  }
  tbody.innerHTML = entries.map((e) => `
    <tr>
      <td class="act-when">${escapeHtml(e.ts || "")}</td>
      <td class="act-user">${escapeHtml(e.username || "")}</td>
      <td><span class="${actionClass(e.action)}">${escapeHtml(e.action)}</span></td>
      <td class="act-details">${renderDetails(e.details)}</td>
    </tr>`).join("");
}

$("#btn-activity-refresh").addEventListener("click", loadActivity);

const _origSwitchTab = switchTab;
switchTab = function (name) {
  _origSwitchTab(name);
  if (name === "activity") loadActivity();
};

/* =============== INIT =============== */
loadServers();
loadUsers();
loadAccessUsers();
switchTabAndMaybePreselect();
