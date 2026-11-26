import re
from datetime import datetime, timedelta, timezone


MOCK_PROCESSES = [
    {"id": 0, "name": "api-server", "status": "online", "cpu": 3.2, "memory_mb": 145, "uptime_s": 172800, "restarts": 2},
    {"id": 1, "name": "worker-queue", "status": "online", "cpu": 1.8, "memory_mb": 89, "uptime_s": 18200, "restarts": 0},
    {"id": 2, "name": "cron-scheduler", "status": "stopped", "cpu": 0.0, "memory_mb": 0, "uptime_s": 0, "restarts": 5},
]

_DATETIME_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")
_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")


def _line_stamp(line: str) -> str | None:
    m = _DATETIME_RE.search(line)
    if m:
        return m.group(0)
    m = _DATE_RE.search(line)
    if m:
        return m.group(0) + "T00:00:00"
    return None


def _normalize_bound(s: str) -> str:
    s = s.rstrip("Z")
    if len(s) == 10:
        return s + "T00:00:00"
    return s[:19]


def filter_by_date(lines: list[str], date_from: str | None, date_to: str | None) -> list[str]:
    if not date_from and not date_to:
        return lines
    f = _normalize_bound(date_from) if date_from else None
    t = _normalize_bound(date_to) if date_to else None
    out = []
    for line in lines:
        ts = _line_stamp(line)
        if ts is None:
            continue
        if f and ts < f:
            continue
        if t and ts > t:
            continue
        out.append(line)
    return out


def _mock_log_lines(name: str, count: int) -> list[str]:
    samples = [
        "[INFO] {name}: request completed in 42ms",
        "[INFO] {name}: health check ok",
        "[WARN] {name}: slow query detected, 1.2s",
        "[INFO] {name}: cache hit ratio 87%",
        "[ERROR] {name}: upstream timeout, retrying",
        "[INFO] {name}: recovered after retry",
    ]
    now = datetime.now(timezone.utc)
    out = []
    for i in range(count):
        offset = timedelta(days=(count - 1 - i) // 20, minutes=i * 7)
        ts = (now - offset).strftime("%Y-%m-%dT%H:%M:%SZ")
        out.append(f"{ts} " + samples[i % len(samples)].format(name=name))
    return out


_PM2_SHELL_WRAPPER = (
    'bash -lc "'
    'export NVM_DIR=\\\"\\$HOME/.nvm\\\"; '
    '[ -s \\\"\\$NVM_DIR/nvm.sh\\\" ] && . \\\"\\$NVM_DIR/nvm.sh\\\" >/dev/null 2>&1; '
    'if ! command -v pm2 >/dev/null 2>&1; then '
    'for d in /root/.nvm/versions/node/*/bin /home/*/.nvm/versions/node/*/bin /usr/local/bin /usr/bin; do '
    '[ -x \\\"\\$d/pm2\\\" ] && export PATH=\\\"\\$d:\\$PATH\\\" && break; '
    'done; fi; '
    '{inner}"'
)


def _wrap_pm2(inner_cmd: str, explicit_path: str | None = None) -> str:
    if explicit_path:
        from pathlib import PurePosixPath
        node_dir = str(PurePosixPath(explicit_path).parent)
        safe_cmd = inner_cmd.replace("pm2", f'"{explicit_path}"', 1)
        return f'bash -lc "export PATH=\\\"{node_dir}:\\$PATH\\\"; {safe_cmd}"'
    return _PM2_SHELL_WRAPPER.format(inner=inner_cmd)


class PM2Adapter:
    def __init__(self, ssh_client=None, mock: bool = False, pm2_path: str | None = None):
        self.ssh = ssh_client
        self.mock = mock
        self.pm2_path = (pm2_path or "").strip() or None

    def list_processes(self) -> list[dict]:
        if self.mock:
            return list(MOCK_PROCESSES)
        result = self.ssh.run(_wrap_pm2("pm2 jlist", self.pm2_path), timeout=30)
        if result.exit_code != 0:
            return []
        import json
        # pm2 jlist sometimes prints banner/log lines before the JSON — find the first [
        raw_out = result.stdout
        start = raw_out.find("[")
        if start == -1:
            return []
        try:
            raw = json.loads(raw_out[start:])
        except json.JSONDecodeError:
            return []
        out = []
        for entry in raw:
            monit = entry.get("monit", {}) or {}
            pm2_env = entry.get("pm2_env", {}) or {}
            interp = pm2_env.get("exec_interpreter") or ""
            interpreter_path = interp if "/" in interp else None
            out.append({
                "id": entry.get("pm_id"),
                "name": entry.get("name"),
                "status": pm2_env.get("status", "unknown"),
                "cpu": monit.get("cpu", 0),
                "memory_mb": round((monit.get("memory", 0) or 0) / 1024 / 1024, 1),
                "uptime_s": int((pm2_env.get("pm_uptime", 0) or 0) / 1000),
                "restarts": pm2_env.get("restart_time", 0),
                "interpreter_path": interpreter_path,
            })
        return out

    def restart(self, process_id: int) -> dict:
        if self.mock:
            return {"ok": True, "output": f"[mock] pm2 restart {process_id}"}
        cmd = _wrap_pm2(f"pm2 restart {process_id}", self.pm2_path)
        result = self.ssh.run(cmd, timeout=45)
        return {"ok": result.exit_code == 0, "output": (result.stdout + result.stderr).strip()}

    def stop(self, process_id: int) -> dict:
        if self.mock:
            return {"ok": True, "output": f"[mock] pm2 stop {process_id}"}
        cmd = _wrap_pm2(f"pm2 stop {process_id}", self.pm2_path)
        result = self.ssh.run(cmd, timeout=30)
        return {"ok": result.exit_code == 0, "output": (result.stdout + result.stderr).strip()}

    def list_log_files(self, process_name: str) -> list[dict]:
        if self.mock:
            return [
                {"name": f"{process_name}-out.log", "size_kb": 142.3},
                {"name": f"{process_name}-error.log", "size_kb": 8.1},
            ]
        import shlex
        safe_name = shlex.quote(process_name)
        cmd = (
            f'bash -lc "ls -la $HOME/.pm2/logs/{safe_name}*.log 2>/dev/null | '
            f'awk \'{{print $5, $NF}}\'"'
        )
        result = self.ssh.run(cmd, timeout=15)
        out = []
        for line in result.stdout.splitlines():
            parts = line.strip().split(None, 1)
            if len(parts) != 2:
                continue
            try:
                size_bytes = int(parts[0])
            except ValueError:
                continue
            full_path = parts[1]
            out.append({
                "name": full_path.rsplit("/", 1)[-1],
                "size_kb": round(size_bytes / 1024, 1),
            })
        return out

    def get_logs(self, process_id: int, lines: int = 100, date_from: str | None = None, date_to: str | None = None) -> list[str]:
        if self.mock:
            name = next((p["name"] for p in MOCK_PROCESSES if p["id"] == process_id), f"pm2-{process_id}")
            all_lines = _mock_log_lines(name, max(lines, 200))
            filtered = filter_by_date(all_lines, date_from, date_to)
            return filtered[-lines:]
        fetch_lines = 10000 if (date_from or date_to) else lines
        inner = f"pm2 logs --nostream --lines {fetch_lines} {process_id}"
        cmd = _wrap_pm2(inner, self.pm2_path)
        result = self.ssh.run(cmd, timeout=60)
        raw = result.stdout.splitlines()
        if date_from or date_to:
            raw = filter_by_date(raw, date_from, date_to)
        return raw[-lines:] if len(raw) > lines else raw
