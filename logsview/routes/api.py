import re
import shlex
import time
from flask import Blueprint, jsonify, request, abort, session, Response, stream_with_context
from config import Settings, load_servers
from logsview.pm2_adapter import PM2Adapter
from logsview.docker_adapter import DockerAdapter
from logsview.ssh_client import SSHClient
from logsview.auth import login_required, current_user
from logsview import user_store

api_bp = Blueprint("api", __name__, url_prefix="/api")


def _find_server(key: str, include_secrets: bool = False) -> dict:
    for server in load_servers(include_secrets=include_secrets):
        if server.get("key") == key:
            return server
    abort(404, description=f"server '{key}' not found")


def _build_adapters(server: dict):
    if Settings.mock_mode:
        return PM2Adapter(mock=True), DockerAdapter(mock=True)
    ssh = SSHClient(
        host=server["host"],
        port=server.get("port", 22),
        username=server["username"],
        password=server.get("password"),
        key=server.get("private_key"),
        key_passphrase=server.get("key_passphrase"),
        bastion=server.get("bastion") if isinstance(server.get("bastion"), dict) else None,
    )
    return (
        PM2Adapter(ssh_client=ssh, pm2_path=server.get("pm2_path")),
        DockerAdapter(ssh_client=ssh),
    )


@api_bp.get("/servers")
@login_required()
def list_servers():
    return jsonify(load_servers())


def _filter_by_grants(server_key: str, services: dict) -> dict:
    user = current_user() or {}
    if user.get("role") == "devops":
        return services
    username = user.get("username", "")
    pm2_allowed = set(user_store.granted_names(username, server_key, "pm2"))
    docker_allowed = set(user_store.granted_names(username, server_key, "docker"))
    pm2_all = "*" in pm2_allowed
    docker_all = "*" in docker_allowed
    filtered_pm2 = services["pm2"] if pm2_all else [p for p in services["pm2"] if p.get("name") in pm2_allowed]
    filtered_docker = services["docker"] if docker_all else [c for c in services["docker"] if c.get("name") in docker_allowed]
    return {"pm2": filtered_pm2, "docker": filtered_docker}


@api_bp.get("/servers/<key>/services")
@login_required()
def list_services(key: str):
    server = _find_server(key, include_secrets=not Settings.mock_mode)
    pm2, docker = _build_adapters(server)
    services = {
        "pm2": pm2.list_processes(),
        "docker": docker.list_containers(),
    }
    return jsonify(_filter_by_grants(key, services))


_DATE_ARG_RE = re.compile(r"^\d{4}-\d{2}-\d{2}(T\d{2}:\d{2}:\d{2})?Z?$")


def _date_arg(name: str) -> str | None:
    val = (request.args.get(name) or "").strip()
    if not val:
        return None
    if not _DATE_ARG_RE.match(val):
        abort(400, description=f"'{name}' must be YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS")
    return val.rstrip("Z")


@api_bp.get("/servers/<key>/logs/<service_type>/<service_id>")
@login_required()
def get_logs(key: str, service_type: str, service_id: str):
    server = _find_server(key, include_secrets=not Settings.mock_mode)
    lines = int(request.args.get("lines", 100))
    date_from = _date_arg("from")
    date_to = _date_arg("to")
    pm2, docker = _build_adapters(server)
    if service_type == "pm2":
        try:
            pid = int(service_id)
        except ValueError:
            abort(400, description="pm2 service_id must be int")
        name = next((p["name"] for p in pm2.list_processes() if p.get("id") == pid), None)
        _guard_access(key, "pm2", name)
        log_lines = pm2.get_logs(pid, lines=lines, date_from=date_from, date_to=date_to)
    elif service_type == "docker":
        name = next((c["name"] for c in docker.list_containers() if c.get("id") == service_id), None)
        _guard_access(key, "docker", name)
        log_lines = docker.get_logs(service_id, lines=lines, date_from=date_from, date_to=date_to)
    else:
        abort(400, description="service_type must be pm2 or docker")
    return jsonify({
        "lines": log_lines,
        "range": {"from": date_from, "to": date_to},
    })


def _guard_access(server_key: str, service_type: str, service_name: str | None) -> None:
    user = current_user() or {}
    if user.get("role") == "devops":
        return
    if service_name is None or not user_store.can_read(user.get("username", ""), "developer", server_key, service_type, service_name):
        abort(403, description="access to this service is not granted")


@api_bp.get("/servers/<key>/pm2/<int:pid>/files")
@login_required()
def pm2_list_files(key: str, pid: int):
    server = _find_server(key, include_secrets=not Settings.mock_mode)
    pm2, _ = _build_adapters(server)
    name = next((p["name"] for p in pm2.list_processes() if p.get("id") == pid), None)
    _guard_access(key, "pm2", name)
    if not name:
        abort(404, description="process not found")
    return jsonify({"name": name, "files": pm2.list_log_files(name)})


def _devops_only():
    user = current_user() or {}
    if user.get("role") != "devops":
        abort(403, description="restart/stop requires devops role")


@api_bp.post("/servers/<key>/pm2/<int:pid>/restart")
@login_required()
def pm2_restart(key: str, pid: int):
    _devops_only()
    server = _find_server(key, include_secrets=not Settings.mock_mode)
    pm2, _ = _build_adapters(server)
    name = next((p["name"] for p in pm2.list_processes() if p.get("id") == pid), f"pm2-{pid}")
    result = pm2.restart(pid)
    user = current_user() or {}
    user_store  # noqa: silence
    from logsview import activity
    activity.record(user.get("username", ""), "pm2_restart", {"server": key, "process": name, "id": pid, "ok": result["ok"]})
    return jsonify(result)


@api_bp.post("/servers/<key>/pm2/<int:pid>/stop")
@login_required()
def pm2_stop(key: str, pid: int):
    _devops_only()
    server = _find_server(key, include_secrets=not Settings.mock_mode)
    pm2, _ = _build_adapters(server)
    name = next((p["name"] for p in pm2.list_processes() if p.get("id") == pid), f"pm2-{pid}")
    result = pm2.stop(pid)
    user = current_user() or {}
    from logsview import activity
    activity.record(user.get("username", ""), "pm2_stop", {"server": key, "process": name, "id": pid, "ok": result["ok"]})
    return jsonify(result)


def _sse_pack(event: str, data: str) -> str:
    safe = data.replace("\r", "")
    payload = "".join(f"data: {line}\n" for line in safe.split("\n"))
    return f"event: {event}\n{payload}\n"


@api_bp.get("/servers/<key>/logs/<service_type>/<service_id>/stream")
@login_required()
def stream_logs(key: str, service_type: str, service_id: str):
    server = _find_server(key, include_secrets=not Settings.mock_mode)
    pm2, docker = _build_adapters(server)

    if service_type == "pm2":
        try:
            pid = int(service_id)
        except ValueError:
            abort(400, description="pm2 service_id must be int")
        name = next((p["name"] for p in pm2.list_processes() if p.get("id") == pid), None)
        _guard_access(key, "pm2", name)
        cmd = f"pm2 logs --raw --lines 0 {pid}"
    elif service_type == "docker":
        name = next((c["name"] for c in docker.list_containers() if c.get("id") == service_id), None)
        _guard_access(key, "docker", name)
        cmd = f"docker logs --follow --timestamps --tail 0 {shlex.quote(service_id)} 2>&1"
    else:
        abort(400, description="service_type must be pm2 or docker")

    if Settings.mock_mode:
        return Response(stream_with_context(_mock_stream(name or service_id, service_type)), mimetype="text/event-stream")

    return Response(
        stream_with_context(_ssh_stream(server, cmd)),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _mock_stream(name: str, service_type: str):
    from datetime import datetime, timezone
    samples = [
        "[INFO] {n}: live tick",
        "[INFO] {n}: health check ok",
        "[WARN] {n}: memory 72%",
        "[ERROR] {n}: transient error, retrying",
    ]
    i = 0
    yield ": connected\n\n"
    try:
        while True:
            ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            line = f"{ts} " + samples[i % len(samples)].format(n=name)
            yield _sse_pack("line", line)
            i += 1
            time.sleep(1.2)
            if i % 12 == 0:
                yield ": keepalive\n\n"
    except GeneratorExit:
        return


def _ssh_stream(server: dict, cmd: str):
    sc = SSHClient(
        host=server["host"],
        port=server.get("port", 22),
        username=server["username"],
        password=server.get("password"),
        key=server.get("private_key"),
        key_passphrase=server.get("key_passphrase"),
        bastion=server.get("bastion") if isinstance(server.get("bastion"), dict) else None,
    )
    try:
        sc.connect()
    except Exception as exc:
        yield _sse_pack("line", f"[stream error] ssh connect: {exc}")
        return

    client = sc._client
    transport = client.get_transport()
    channel = transport.open_session()
    channel.exec_command(cmd)
    channel.settimeout(1.0)

    yield ": connected\n\n"
    buffer = ""
    last_keepalive = time.time()
    try:
        while True:
            if channel.exit_status_ready() and not channel.recv_ready():
                break
            try:
                data = channel.recv(4096).decode("utf-8", errors="replace")
                if data:
                    buffer += data
                    while "\n" in buffer:
                        line, buffer = buffer.split("\n", 1)
                        if line.strip():
                            yield _sse_pack("line", line)
            except Exception:
                pass

            if time.time() - last_keepalive > 15:
                yield ": keepalive\n\n"
                last_keepalive = time.time()
    except GeneratorExit:
        pass
    finally:
        try:
            channel.close()
            sc.close()
        except Exception:
            pass
