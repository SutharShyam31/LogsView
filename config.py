import os
from pathlib import Path
import yaml
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


class Settings:
    secret_key = os.environ.get("FLASK_SECRET_KEY", "dev-insecure-key")
    mock_mode = _env_bool("LOGSVIEW_MOCK_MODE", True)
    host = os.environ.get("LOGSVIEW_HOST", "127.0.0.1")
    port = int(os.environ.get("LOGSVIEW_PORT", "5050"))
    servers_file = BASE_DIR / "servers.yaml"


def save_servers(servers: list[dict]) -> None:
    path = Settings.servers_file
    path.write_text(yaml.safe_dump({"servers": servers}, sort_keys=False), encoding="utf-8")


import re as _re


def _slug_for_key(s: str) -> str:
    slug = _re.sub(r"[^a-z0-9-]+", "-", (s or "").lower()).strip("-")
    return slug or "server"


def load_servers_raw() -> list[dict]:
    path = Settings.servers_file
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    servers = data.get("servers", [])
    changed = False
    seen: set[str] = set()
    for i, s in enumerate(servers):
        existing = s.get("key")
        if not existing:
            base = _slug_for_key(s.get("label") or s.get("host") or f"server-{i+1}")
            new_key = base
            n = 2
            while new_key in seen:
                new_key = f"{base}-{n}"
                n += 1
            s["key"] = new_key
            changed = True
        seen.add(s["key"])
    if changed:
        save_servers(servers)
    return servers


def load_servers(include_secrets: bool = False) -> list[dict]:
    path = Settings.servers_file
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    servers = data.get("servers", [])
    if not include_secrets:
        return [_strip_secrets(s) for s in servers]
    from logsview.crypto import decrypt
    out = []
    for s in servers:
        copy = dict(s)
        _decrypt_auth(copy)
        bastion = copy.get("bastion")
        if isinstance(bastion, dict):
            _decrypt_auth(bastion)
        out.append(copy)
    return out


_SECRET_KEYS = {
    "encrypted_password", "password",
    "encrypted_key", "private_key",
    "encrypted_key_passphrase", "key_passphrase",
}


def _decrypt_auth(entry: dict) -> None:
    from logsview.crypto import decrypt
    pw = entry.pop("encrypted_password", None)
    if pw:
        entry["password"] = decrypt(pw)
    pk = entry.pop("encrypted_key", None)
    if pk:
        entry["private_key"] = decrypt(pk)
    passp = entry.pop("encrypted_key_passphrase", None)
    if passp:
        entry["key_passphrase"] = decrypt(passp)


def _strip_secrets(server: dict) -> dict:
    copy = {k: v for k, v in server.items() if k not in _SECRET_KEYS}
    copy["auth_mode"] = "key" if server.get("encrypted_key") else "password"
    bastion = server.get("bastion")
    if isinstance(bastion, dict):
        copy["bastion"] = {k: v for k, v in bastion.items() if k not in _SECRET_KEYS}
        copy["bastion"]["auth_mode"] = "key" if bastion.get("encrypted_key") else "password"
    return copy
