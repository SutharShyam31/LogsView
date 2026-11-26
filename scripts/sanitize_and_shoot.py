"""One-shot: swap real users.dat/servers.yaml/activity.log for fake data,
re-screenshot the 3 views that leaked real info, restore originals.

Run from project root:
    $env:PLAYWRIGHT_BROWSERS_PATH="D:\\playwright-browsers"
    .\.venv\Scripts\python.exe scripts\sanitize_and_shoot.py
"""

import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

USERS_DAT = ROOT / "users.dat"
SERVERS_YAML = ROOT / "servers.yaml"
ACTIVITY_LOG = ROOT / "activity.log"
BACKUP_SUFFIX = ".real-backup"

FAKE_USERS = [
    ("demo-admin", "DemoAdmin@123", "devops"),
    ("alex-dev", "AlexDev@123", "developer"),
    ("maya-qa", "MayaQa@123", "developer"),
    ("ravi-frontend", "RaviFe@123", "developer"),
]

FAKE_SERVERS_YAML = """servers:
  - key: webapp-prod
    label: Web App Prod
    host: 10.20.30.40
    port: 22
    username: ubuntu
    encrypted_password: gAAAAAB_placeholder_token_webapp_prod_pw
  - key: worker-prod
    label: Worker Prod
    host: 10.20.30.41
    port: 22
    username: ubuntu
    encrypted_password: gAAAAAB_placeholder_token_worker_prod_pw
    bastion:
      host: bastion.example.internal
      port: 22
      username: ops
      encrypted_password: gAAAAAB_placeholder_bastion_pw
  - key: staging-db
    label: Staging DB
    host: 10.20.30.50
    port: 22
    username: ubuntu
    encrypted_password: gAAAAAB_placeholder_token_staging_db_pw
"""

FAKE_ACTIVITY_LINES = [
    {"ts": "2026-11-20 09:12:04", "username": "demo-admin", "action": "login", "details": {"role": "devops", "ip": "10.0.0.15"}},
    {"ts": "2026-11-20 09:14:22", "username": "demo-admin", "action": "add_server", "details": {"key": "webapp-prod", "label": "Web App Prod", "host": "10.20.30.40", "auth_mode": "password", "bastion": ""}},
    {"ts": "2026-11-20 09:16:11", "username": "demo-admin", "action": "add_server", "details": {"key": "worker-prod", "label": "Worker Prod", "host": "10.20.30.41", "auth_mode": "password", "bastion": "bastion.example.internal"}},
    {"ts": "2026-11-20 09:19:48", "username": "demo-admin", "action": "add_server", "details": {"key": "staging-db", "label": "Staging DB", "host": "10.20.30.50", "auth_mode": "password", "bastion": ""}},
    {"ts": "2026-11-20 09:22:30", "username": "demo-admin", "action": "add_user", "details": {"username": "alex-dev", "role": "developer"}},
    {"ts": "2026-11-20 09:23:10", "username": "demo-admin", "action": "add_user", "details": {"username": "maya-qa", "role": "developer"}},
    {"ts": "2026-11-20 09:24:02", "username": "demo-admin", "action": "add_user", "details": {"username": "ravi-frontend", "role": "developer"}},
    {"ts": "2026-11-20 09:26:55", "username": "demo-admin", "action": "set_user_access", "details": {"username": "alex-dev", "servers": 2, "grants": 3}},
    {"ts": "2026-11-20 09:28:14", "username": "demo-admin", "action": "set_user_access", "details": {"username": "maya-qa", "servers": 1, "grants": 2}},
    {"ts": "2026-11-21 08:03:41", "username": "alex-dev", "action": "login", "details": {"role": "developer", "ip": "10.0.0.22"}},
    {"ts": "2026-11-21 10:14:52", "username": "alex-dev", "action": "logout", "details": {"ip": "10.0.0.22"}},
    {"ts": "2026-11-21 11:40:03", "username": "maya-qa", "action": "login", "details": {"role": "developer", "ip": "10.0.0.31"}},
    {"ts": "2026-11-22 09:11:28", "username": "demo-admin", "action": "login", "details": {"role": "devops", "ip": "10.0.0.15"}},
    {"ts": "2026-11-22 09:15:02", "username": "demo-admin", "action": "set_user_access", "details": {"username": "ravi-frontend", "servers": 1, "grants": 1}},
    {"ts": "2026-11-23 08:30:11", "username": "ravi-frontend", "action": "login", "details": {"role": "developer", "ip": "10.0.0.47"}},
    {"ts": "2026-11-23 08:54:19", "username": "ravi-frontend", "action": "logout", "details": {"ip": "10.0.0.47"}},
]


def backup_originals():
    for p in (USERS_DAT, SERVERS_YAML, ACTIVITY_LOG):
        if p.exists():
            dst = p.with_suffix(p.suffix + BACKUP_SUFFIX)
            shutil.copy2(p, dst)
            print(f"  backed up {p.name} -> {dst.name}")


def restore_originals():
    for p in (USERS_DAT, SERVERS_YAML, ACTIVITY_LOG):
        src = p.with_suffix(p.suffix + BACKUP_SUFFIX)
        if src.exists():
            shutil.copy2(src, p)
            src.unlink()
            print(f"  restored {p.name}")


def write_fake_users():
    if USERS_DAT.exists():
        USERS_DAT.unlink()
    # user_store reads module-level USERS_FILE; reload after unlink to re-init
    from importlib import reload
    import logsview.user_store as us
    reload(us)
    for username, password, role in FAKE_USERS:
        us.add_user(username, password, role)
    # give alex-dev grants on 2 servers, maya-qa on 1, ravi-frontend on 1
    us.set_grants("alex-dev", {
        "webapp-prod": {"pm2": ["api-server", "worker-queue"], "docker": []},
        "worker-prod": {"pm2": ["*"], "docker": []},
    })
    us.set_grants("maya-qa", {
        "staging-db": {"pm2": [], "docker": ["postgres-db", "redis-cache"]},
    })
    us.set_grants("ravi-frontend", {
        "webapp-prod": {"pm2": ["api-server"], "docker": []},
    })
    print("  wrote fake users.dat")


def write_fake_servers():
    SERVERS_YAML.write_text(FAKE_SERVERS_YAML, encoding="utf-8")
    print("  wrote fake servers.yaml")


def write_fake_activity():
    with ACTIVITY_LOG.open("w", encoding="utf-8") as fh:
        for entry in FAKE_ACTIVITY_LINES:
            fh.write(json.dumps(entry) + "\n")
    print("  wrote fake activity.log")


def shoot():
    from playwright.sync_api import sync_playwright

    BASE = "http://127.0.0.1:5051"
    OUT = ROOT / "images"
    VIEWPORT = {"width": 1440, "height": 900}

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        ctx = browser.new_context(viewport=VIEWPORT, device_scale_factor=1)
        page = ctx.new_page()

        print("  logging in as demo-admin")
        page.goto(f"{BASE}/login")
        page.wait_for_selector("input[name='username']")
        page.fill("input[name='username']", "demo-admin")
        page.fill("input[name='password']", "DemoAdmin@123")
        page.click("button[type='submit']")
        page.wait_for_url(f"{BASE}/")

        print("  admin tabs")
        page.goto(f"{BASE}/admin")
        page.wait_for_selector(".admin-nav-item[data-tab='servers']")

        page.click(".admin-nav-item[data-tab='servers']")
        page.wait_for_timeout(900)
        page.screenshot(path=str(OUT / "admin-servers.png"), full_page=True)
        print("    -> admin-servers.png")

        page.click(".admin-nav-item[data-tab='users']")
        page.wait_for_timeout(900)
        page.screenshot(path=str(OUT / "admin-users.png"), full_page=True)
        print("    -> admin-users.png")

        page.click(".admin-nav-item[data-tab='activity']")
        page.wait_for_timeout(900)
        page.screenshot(path=str(OUT / "admin-activity.png"), full_page=True)
        print("    -> admin-activity.png")

        ctx.close()
        browser.close()


def wait_for_port(port: int, timeout: float = 15.0) -> bool:
    import socket
    end = time.time() + timeout
    while time.time() < end:
        s = socket.socket()
        s.settimeout(0.5)
        try:
            s.connect(("127.0.0.1", port))
            s.close()
            return True
        except OSError:
            time.sleep(0.3)
    return False


def start_mock_instance():
    import os
    env = os.environ.copy()
    env["FLASK_SECRET_KEY"] = "sanitize-shoot-ephemeral-key"
    env["LOGSVIEW_MOCK_MODE"] = "true"
    env["LOGSVIEW_HOST"] = "127.0.0.1"
    env["LOGSVIEW_PORT"] = "5051"
    proc = subprocess.Popen(
        [str(ROOT / ".venv" / "Scripts" / "python.exe"), "app.py"],
        cwd=str(ROOT),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if not wait_for_port(5051, 15):
        proc.terminate()
        raise RuntimeError("mock instance failed to start on 5051")
    print(f"  mock instance up on 5051 (pid {proc.pid})")
    return proc


def main():
    print("[1/6] backing up real files")
    backup_originals()
    try:
        print("[2/6] writing fake users")
        write_fake_users()
        print("[3/6] writing fake servers.yaml and activity.log")
        write_fake_servers()
        write_fake_activity()
        print("[4/6] starting mock instance on :5051")
        proc = start_mock_instance()
        try:
            print("[5/6] taking screenshots")
            shoot()
        finally:
            print("  stopping mock instance")
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
    finally:
        print("[6/6] restoring real files")
        restore_originals()
    print("done.")


if __name__ == "__main__":
    main()
