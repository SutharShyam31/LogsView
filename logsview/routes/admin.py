import re
from concurrent.futures import ThreadPoolExecutor
from flask import Blueprint, jsonify, request, abort, render_template, session
from config import Settings, load_servers, load_servers_raw, save_servers
from logsview.crypto import encrypt
from logsview.ssh_client import SSHClient
from logsview.pm2_adapter import PM2Adapter
from logsview.docker_adapter import DockerAdapter
from logsview import user_store, activity
from logsview.auth import login_required


def _actor() -> str:
    return session.get("username", "")

admin_bp = Blueprint("admin", __name__)

KEY_RE = re.compile(r"[^a-z0-9-]+")


def _slugify(name: str) -> str:
    slug = KEY_RE.sub("-", name.strip().lower()).strip("-")
    return slug or "server"


def _unique_key(base: str, existing_keys: set[str]) -> str:
    if base not in existing_keys:
        return base
    i = 2
    while f"{base}-{i}" in existing_keys:
        i += 1
    return f"{base}-{i}"


@admin_bp.get("/api/admin/servers")
@login_required(role="devops")
def list_servers_admin():
    return jsonify(load_servers(include_secrets=False))


def _encrypt_auth(entry: dict, password: str, key: str, key_passphrase: str) -> None:
    key_str = (key or "").strip()
    if key_str:
        entry["encrypted_key"] = encrypt(key_str)
        if key_passphrase:
            entry["encrypted_key_passphrase"] = encrypt(key_passphrase)
    elif password:
        entry["encrypted_password"] = encrypt(password)
    else:
        raise ValueError("either password or private key is required")


@admin_bp.post("/api/admin/servers")
@login_required(role="devops")
def add_server():
    data = request.get_json(silent=True) or {}
    label = (data.get("label") or "").strip()
    host = (data.get("host") or "").strip()
    username = (data.get("username") or "").strip()
    port = int(data.get("port") or 22)
    pm2_path = (data.get("pm2_path") or "").strip() or None
    bastion = data.get("bastion") or None

    if not label or not host or not username:
        abort(400, description="label, host, username required")

    servers = load_servers_raw()
    new_key = _unique_key(_slugify(label), {s.get("key", "") for s in servers})
    entry = {"key": new_key, "label": label, "host": host, "port": port, "username": username}
    if pm2_path:
        entry["pm2_path"] = pm2_path
    try:
        _encrypt_auth(entry, data.get("password") or "", data.get("key") or "", data.get("key_passphrase") or "")
    except ValueError as exc:
        abort(400, description=str(exc))

    if isinstance(bastion, dict) and (bastion.get("host") or "").strip():
        b_host = bastion["host"].strip()
        b_username = (bastion.get("username") or "").strip()
        if not b_username:
            abort(400, description="bastion username required")
        b_entry = {"host": b_host, "port": int(bastion.get("port") or 22), "username": b_username}
        try:
            _encrypt_auth(b_entry, bastion.get("password") or "", bastion.get("key") or "", bastion.get("key_passphrase") or "")
        except ValueError as exc:
            abort(400, description=f"bastion: {exc}")
        entry["bastion"] = b_entry

    servers.append(entry)
    save_servers(servers)
    key = new_key
    activity.record(_actor(), "add_server", {
        "key": key, "label": label, "host": host,
        "auth_mode": "key" if entry.get("encrypted_key") else "password",
        "bastion": entry.get("bastion", {}).get("host", "") if "bastion" in entry else "",
    })
    return jsonify({"ok": True})


@admin_bp.delete("/api/admin/servers/<key>")
@login_required(role="devops")
def delete_server(key: str):
    servers = load_servers_raw()
    before = len(servers)
    servers = [s for s in servers if s.get("key") != key]
    if len(servers) == before:
        abort(404, description=f"server '{key}' not found")
    save_servers(servers)
    activity.record(_actor(), "delete_server", {"key": key})
    return jsonify({"ok": True})


@admin_bp.get("/api/admin/users")
@login_required(role="devops")
def list_users_admin():
    users = user_store.list_users()
    counts = user_store.role_counts()
    return jsonify({"users": users, "counts": counts})


@admin_bp.post("/api/admin/users")
@login_required(role="devops")
def add_user_admin():
    data = request.get_json(silent=True) or {}
    username = data.get("username") or ""
    role = (data.get("role") or "developer").strip()
    try:
        user_store.add_user(
            username=username,
            password=data.get("password") or "",
            role=role,
        )
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    activity.record(_actor(), "add_user", {"username": username, "role": role})
    return jsonify({"ok": True})


@admin_bp.patch("/api/admin/users/<username>")
@login_required(role="devops")
def update_user_admin(username: str):
    data = request.get_json(silent=True) or {}
    role = data.get("role")
    password = data.get("password")
    try:
        user_store.update_user(username, role=role, password=password)
    except KeyError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 404
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    changed = []
    if role is not None:
        changed.append("role")
    if password is not None:
        changed.append("password")
    details = {"username": username, "fields": ",".join(changed)}
    if role is not None:
        details["role"] = role
    activity.record(_actor(), "update_user", details)
    return jsonify({"ok": True})


@admin_bp.delete("/api/admin/users/<username>")
@login_required(role="devops")
def delete_user_admin(username: str):
    try:
        user_store.delete_user(username)
    except KeyError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 404
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    activity.record(_actor(), "delete_user", {"username": username})
    return jsonify({"ok": True})


def _probe_server(server: dict) -> dict:
    key = server.get("key") or server.get("label") or server.get("host") or "unknown"
    out = {
        "key": key,
        "label": server.get("label", key),
        "host": server["host"],
        "username": server.get("username", ""),
        "pm2": [],
        "docker": [],
        "reachable": True,
        "error": None,
    }
    try:
        if Settings.mock_mode:
            pm2 = PM2Adapter(mock=True)
            docker = DockerAdapter(mock=True)
        else:
            ssh = SSHClient(
                host=server["host"],
                port=server.get("port", 22),
                username=server["username"],
                password=server.get("password"),
                key=server.get("private_key"),
                key_passphrase=server.get("key_passphrase"),
                bastion=server.get("bastion") if isinstance(server.get("bastion"), dict) else None,
            )
            pm2 = PM2Adapter(ssh_client=ssh, pm2_path=server.get("pm2_path"))
            docker = DockerAdapter(ssh_client=ssh)
        out["pm2"] = [p["name"] for p in pm2.list_processes() if p.get("name")]
        out["docker"] = [c["name"] for c in docker.list_containers() if c.get("name")]
    except Exception as exc:
        out["reachable"] = False
        out["error"] = str(exc)
    return out


@admin_bp.get("/api/admin/access/<username>")
@login_required(role="devops")
def get_access(username: str):
    try:
        grants = user_store.get_grants(username)
    except KeyError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 404
    servers = load_servers(include_secrets=not Settings.mock_mode)
    with ThreadPoolExecutor(max_workers=max(1, min(5, len(servers)))) as pool:
        inventories = list(pool.map(_probe_server, servers)) if servers else []
    for inv in inventories:
        inv["grants"] = grants.get(inv["key"], {"pm2": [], "docker": []})
    return jsonify({
        "username": username,
        "inventory": inventories,
    })


@admin_bp.put("/api/admin/access/<username>")
@login_required(role="devops")
def set_access(username: str):
    data = request.get_json(silent=True) or {}
    allowed = data.get("allowed") or {}
    try:
        user_store.set_grants(username, allowed)
    except KeyError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 404
    servers_count = len(allowed)
    grants_count = sum(len(v.get("pm2", [])) + len(v.get("docker", [])) for v in allowed.values())
    activity.record(_actor(), "set_user_access", {
        "username": username,
        "servers": servers_count,
        "grants": grants_count,
    })
    return jsonify({"ok": True})


@admin_bp.get("/api/admin/activity")
@login_required(role="devops")
def list_activity():
    try:
        limit = int(request.args.get("limit", 500))
    except ValueError:
        limit = 500
    return jsonify(activity.list_entries(limit=max(1, min(2000, limit))))


@admin_bp.post("/api/admin/servers/test")
@login_required(role="devops")
def test_connection():
    data = request.get_json(silent=True) or {}
    host = (data.get("host") or "").strip()
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""
    key = data.get("key") or ""
    key_passphrase = data.get("key_passphrase") or ""
    port = int(data.get("port") or 22)
    raw_bastion = data.get("bastion") or None
    if not host or not username or (not password and not key.strip()):
        return jsonify({"ok": False, "error": "host, username, and (password or private key) are required"}), 400
    bastion = None
    if isinstance(raw_bastion, dict) and (raw_bastion.get("host") or "").strip():
        b_pw = raw_bastion.get("password") or ""
        b_key = raw_bastion.get("key") or ""
        if not raw_bastion.get("username") or (not b_pw and not b_key.strip()):
            return jsonify({"ok": False, "error": "bastion username and (password or key) required when bastion host is set"}), 400
        bastion = {
            "host": raw_bastion["host"].strip(),
            "port": int(raw_bastion.get("port") or 22),
            "username": raw_bastion["username"].strip(),
            "password": b_pw or None,
            "private_key": b_key or None,
            "key_passphrase": raw_bastion.get("key_passphrase") or None,
        }
    ssh = SSHClient(
        host=host, port=port, username=username,
        password=password or None, key=key or None, key_passphrase=key_passphrase or None,
        bastion=bastion,
    )
    probe_cmd = (
        'bash -lc "'
        'uname -a; echo ---; '
        'export NVM_DIR=\\\"\\$HOME/.nvm\\\"; '
        '[ -s \\\"\\$NVM_DIR/nvm.sh\\\" ] && . \\\"\\$NVM_DIR/nvm.sh\\\" >/dev/null 2>&1; '
        'if ! command -v pm2 >/dev/null 2>&1; then '
        'for d in /root/.nvm/versions/node/*/bin /home/*/.nvm/versions/node/*/bin /usr/local/bin /usr/bin; do '
        '[ -x \\\"\\$d/pm2\\\" ] && export PATH=\\\"\\$d:\\$PATH\\\" && break; '
        'done; fi; '
        'command -v pm2 >/dev/null 2>&1 && echo PM2=\\$(command -v pm2) || echo PM2=NOT_FOUND; '
        'command -v docker >/dev/null 2>&1 && echo DOCKER=\\$(command -v docker) || echo DOCKER=NOT_FOUND"'
    )
    try:
        ssh.connect()
        result = ssh.run(probe_cmd)
        ssh.close()
        return jsonify({
            "ok": True,
            "via_bastion": bool(bastion),
            "exit_code": result.exit_code,
            "probe": result.stdout.strip(),
        })
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 200
