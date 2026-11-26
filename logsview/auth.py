import time
from collections import defaultdict
from functools import wraps
from flask import session, redirect, request, jsonify, abort

MAX_FAILED_ATTEMPTS = 5
BLOCK_WINDOW_SECONDS = 300

_failed_attempts: dict[str, list[float]] = defaultdict(list)


def _prune(ip: str) -> None:
    cutoff = time.time() - BLOCK_WINDOW_SECONDS
    _failed_attempts[ip] = [t for t in _failed_attempts[ip] if t > cutoff]


def is_login_blocked(ip: str) -> bool:
    _prune(ip)
    return len(_failed_attempts[ip]) >= MAX_FAILED_ATTEMPTS


def record_failed_login(ip: str) -> None:
    _prune(ip)
    _failed_attempts[ip].append(time.time())


def reset_login_attempts(ip: str) -> None:
    _failed_attempts.pop(ip, None)


def current_user() -> dict | None:
    username = session.get("username")
    if not username:
        return None
    return {"username": username, "role": session.get("role", "developer")}


def login_required(role: str | None = None):
    def decorator(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            user = current_user()
            if not user:
                if request.path.startswith("/api/"):
                    return jsonify({"error": "unauthorized"}), 401
                return redirect("/login")
            if role and user["role"] != role:
                if request.path.startswith("/api/"):
                    return jsonify({"error": "forbidden"}), 403
                abort(403, description=f"role '{role}' required")
            return fn(*args, **kwargs)
        return wrapped
    return decorator
