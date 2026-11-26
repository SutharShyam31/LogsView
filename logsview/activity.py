import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from flask import request, has_request_context

LOG_FILE = Path(__file__).resolve().parent.parent / "activity.log"
_lock = threading.Lock()


def _ip() -> str:
    if not has_request_context():
        return ""
    return request.remote_addr or ""


def record(username: str, action: str, details: dict | None = None) -> None:
    entry = {
        "ts": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        "username": username or "",
        "action": action,
        "details": details or {},
    }
    line = json.dumps(entry, ensure_ascii=False)
    with _lock:
        with LOG_FILE.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")


def list_entries(limit: int = 500) -> list[dict]:
    if not LOG_FILE.exists():
        return []
    with LOG_FILE.open("r", encoding="utf-8") as fh:
        lines = fh.readlines()
    entries: list[dict] = []
    for line in reversed(lines[-limit:]):
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return entries


def ip_detail() -> dict:
    return {"ip": _ip()} if _ip() else {}
