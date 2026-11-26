"""Encrypt a server password and write it back to servers.yaml.

Usage:
    python scripts/set_server_password.py <server-key> <password>
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import yaml
from logsview.crypto import encrypt


def main():
    if len(sys.argv) != 3:
        print("usage: python scripts/set_server_password.py <server-key> <password>")
        sys.exit(1)
    key, password = sys.argv[1], sys.argv[2]
    path = ROOT / "servers.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    servers = data.get("servers", [])
    for server in servers:
        if server.get("key") == key:
            server["encrypted_password"] = encrypt(password)
            path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
            print(f"Password set for '{key}'")
            return
    print(f"Server key '{key}' not found in servers.yaml")
    sys.exit(1)


if __name__ == "__main__":
    main()
