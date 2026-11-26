from datetime import datetime, timedelta, timezone
from logsview.pm2_adapter import filter_by_date


MOCK_CONTAINERS = [
    {"id": "a1b2c3d4e5f6", "name": "postgres-db", "status": "Up 2 days", "image": "postgres:15"},
    {"id": "b2c3d4e5f6a1", "name": "redis-cache", "status": "Up 5 hours", "image": "redis:7-alpine"},
    {"id": "c3d4e5f6a1b2", "name": "nginx-proxy", "status": "Up 2 days", "image": "nginx:alpine"},
    {"id": "d4e5f6a1b2c3", "name": "old-worker", "status": "Exited (0) 3 hours ago", "image": "node:20-alpine"},
]


def _mock_docker_lines(name: str, count: int) -> list[str]:
    samples = [
        "[{name}] listening on 0.0.0.0:5432",
        "[{name}] accepted connection from 10.0.0.12",
        "[{name}] query executed in 18ms",
        "[{name}] WARN: connection pool 80% full",
        "[{name}] client disconnected",
    ]
    now = datetime.now(timezone.utc)
    out = []
    for i in range(count):
        offset = timedelta(days=(count - 1 - i) // 15, minutes=i * 9)
        ts = (now - offset).strftime("%Y-%m-%dT%H:%M:%S.000000000Z")
        out.append(f"{ts} " + samples[i % len(samples)].format(name=name))
    return out


class DockerAdapter:
    def __init__(self, ssh_client=None, mock: bool = False):
        self.ssh = ssh_client
        self.mock = mock

    def list_containers(self) -> list[dict]:
        if self.mock:
            return list(MOCK_CONTAINERS)
        cmd = "docker ps -a --format '{{.ID}}|{{.Names}}|{{.Status}}|{{.Image}}'"
        result = self.ssh.run(cmd)
        if result.exit_code != 0:
            return []
        out = []
        for line in result.stdout.splitlines():
            parts = line.split("|")
            if len(parts) < 4:
                continue
            out.append({"id": parts[0], "name": parts[1], "status": parts[2], "image": parts[3]})
        return out

    def get_logs(self, container_id: str, lines: int = 100, date_from: str | None = None, date_to: str | None = None) -> list[str]:
        if self.mock:
            name = next((c["name"] for c in MOCK_CONTAINERS if c["id"] == container_id), container_id[:12])
            all_lines = _mock_docker_lines(name, max(lines, 200))
            filtered = filter_by_date(all_lines, date_from, date_to)
            return filtered[-lines:]
        import shlex
        parts = ["docker", "logs", "--timestamps"]
        if date_from:
            parts += ["--since", f"{date_from}Z" if "T" in date_from else date_from]
        if date_to:
            to_val = f"{date_to}Z" if "T" in date_to else f"{date_to}T23:59:59Z"
            parts += ["--until", to_val]
        parts += ["--tail", str(lines), shlex.quote(container_id)]
        cmd = " ".join(parts) + " 2>&1"
        result = self.ssh.run(cmd, timeout=60)
        return result.stdout.splitlines()
