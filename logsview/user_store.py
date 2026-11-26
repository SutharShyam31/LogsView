import json
from pathlib import Path
import bcrypt
from cryptography.fernet import Fernet, InvalidToken
from logsview.crypto import _load_or_create_key

USERS_FILE = Path(__file__).resolve().parent.parent / "users.dat"
ROLES = ("devops", "developer")
MIN_PASSWORD_LEN = 6


def _load() -> dict:
    if not USERS_FILE.exists():
        return {"users": {}}
    try:
        decrypted = Fernet(_load_or_create_key()).decrypt(USERS_FILE.read_bytes())
        return json.loads(decrypted.decode("utf-8"))
    except (InvalidToken, json.JSONDecodeError, ValueError):
        return {"users": {}}


def _save(data: dict) -> None:
    payload = json.dumps(data).encode("utf-8")
    USERS_FILE.write_bytes(Fernet(_load_or_create_key()).encrypt(payload))


def _hash(pw: str) -> str:
    return bcrypt.hashpw(pw.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def _grants_count(allowed: dict) -> int:
    total = 0
    for per_server in allowed.values():
        total += len(per_server.get("pm2", [])) + len(per_server.get("docker", []))
    return total


def _count_devops(users: dict) -> int:
    return sum(1 for u in users.values() if u.get("role") == "devops")


def list_users() -> list[dict]:
    data = _load()
    return [
        {
            "username": username,
            "role": info.get("role", "developer"),
            "grants_count": _grants_count(info.get("allowed", {})),
        }
        for username, info in sorted(data["users"].items())
    ]


def role_counts() -> dict:
    data = _load()
    counts = {"devops": 0, "developer": 0}
    for info in data["users"].values():
        role = info.get("role", "developer")
        if role in counts:
            counts[role] += 1
    return counts


def add_user(username: str, password: str, role: str) -> None:
    username = username.strip()
    if not username:
        raise ValueError("username required")
    if role not in ROLES:
        raise ValueError(f"role must be one of {ROLES}")
    if len(password) < MIN_PASSWORD_LEN:
        raise ValueError(f"password must be at least {MIN_PASSWORD_LEN} characters")
    data = _load()
    if username in data["users"]:
        raise ValueError(f"user '{username}' already exists")
    data["users"][username] = {"role": role, "password_hash": _hash(password), "allowed": {}}
    _save(data)


def delete_user(username: str) -> None:
    data = _load()
    if username not in data["users"]:
        raise KeyError(f"user '{username}' not found")
    if data["users"][username].get("role") == "devops" and _count_devops(data["users"]) <= 1:
        raise ValueError("cannot delete the last devops user")
    del data["users"][username]
    _save(data)


def update_user(username: str, role: str | None = None, password: str | None = None) -> None:
    data = _load()
    if username not in data["users"]:
        raise KeyError(f"user '{username}' not found")
    user = data["users"][username]
    if role is not None:
        if role not in ROLES:
            raise ValueError(f"role must be one of {ROLES}")
        if user.get("role") == "devops" and role != "devops" and _count_devops(data["users"]) <= 1:
            raise ValueError("cannot demote the last devops user")
        user["role"] = role
    if password is not None:
        if len(password) < MIN_PASSWORD_LEN:
            raise ValueError(f"password must be at least {MIN_PASSWORD_LEN} characters")
        user["password_hash"] = _hash(password)
    _save(data)


def get_grants(username: str) -> dict:
    data = _load()
    user = data["users"].get(username)
    if not user:
        raise KeyError(f"user '{username}' not found")
    return user.get("allowed", {})


def set_grants(username: str, allowed: dict) -> None:
    data = _load()
    if username not in data["users"]:
        raise KeyError(f"user '{username}' not found")
    cleaned: dict = {}
    for server_key, per_server in (allowed or {}).items():
        if not isinstance(per_server, dict):
            continue
        pm2_list = [str(x) for x in (per_server.get("pm2") or []) if x]
        docker_list = [str(x) for x in (per_server.get("docker") or []) if x]
        if pm2_list or docker_list:
            cleaned[server_key] = {"pm2": pm2_list, "docker": docker_list}
    data["users"][username]["allowed"] = cleaned
    _save(data)


def granted_names(username: str, server_key: str, service_type: str) -> list[str]:
    data = _load()
    user = data["users"].get(username)
    if not user:
        return []
    per_server = (user.get("allowed") or {}).get(server_key) or {}
    return list(per_server.get(service_type) or [])


def can_read(username: str, role: str, server_key: str, service_type: str, service_name: str) -> bool:
    if role == "devops":
        return True
    names = granted_names(username, server_key, service_type)
    return "*" in names or service_name in names


def verify_credentials(username: str, password: str) -> bool:
    data = _load()
    user = data["users"].get(username)
    if not user:
        return False
    stored = user.get("password_hash", "").encode("utf-8")
    try:
        return bcrypt.checkpw(password.encode("utf-8"), stored)
    except ValueError:
        return False
