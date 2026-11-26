"""Portfolio screenshots for LogsView — drives a headless Chromium via Playwright.

Run from the project root:
    $env:PLAYWRIGHT_BROWSERS_PATH="D:\\playwright-browsers"
    .\.venv\Scripts\python.exe scripts\screenshot.py

Assumes a logsview instance is already running at BASE_URL and that USERNAME exists
with role=devops. Images are saved to images/ with the names referenced in README.md.
"""

from pathlib import Path
from playwright.sync_api import sync_playwright

BASE_URL = "http://127.0.0.1:5051"
USERNAME = "shyam2"
PASSWORD = "Shyam@123"

OUT_DIR = Path(__file__).resolve().parent.parent / "images"
OUT_DIR.mkdir(exist_ok=True)

VIEWPORT = {"width": 1440, "height": 900}


def shot(page, name: str) -> None:
    path = OUT_DIR / name
    page.screenshot(path=str(path), full_page=True)
    print(f"  -> {path.name}")


def main() -> None:
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        ctx = browser.new_context(viewport=VIEWPORT, device_scale_factor=1)
        page = ctx.new_page()

        print("login page")
        page.goto(f"{BASE_URL}/login")
        page.wait_for_selector("input[name='username']")
        shot(page, "login.png")

        print("logging in")
        page.fill("input[name='username']", USERNAME)
        page.fill("input[name='password']", PASSWORD)
        page.click("button[type='submit']")
        page.wait_for_url(f"{BASE_URL}/")

        print("dashboard — waiting for services to load")
        page.wait_for_selector("#server-select option", state="attached")
        # kick off services load
        try:
            page.click("#btn-reload", timeout=3000)
        except Exception:
            pass
        page.wait_for_timeout(1500)
        shot(page, "dashboard.png")

        print("logs view — clicking a PM2 process")
        clicked = False
        for sel in [".service-item", ".pm2-item", "[data-process]", ".process-card", "li.svc"]:
            if page.locator(sel).count() > 0:
                page.locator(sel).first.click()
                clicked = True
                break
        if not clicked:
            # fallback: try clicking first thing that looks like a name
            try:
                page.get_by_text("api-server", exact=False).first.click(timeout=2000)
                clicked = True
            except Exception:
                pass
        page.wait_for_timeout(1500)
        shot(page, "logs.png")

        print("admin — servers tab")
        page.goto(f"{BASE_URL}/admin")
        page.wait_for_selector(".admin-nav-item[data-tab='servers']")
        page.click(".admin-nav-item[data-tab='servers']")
        page.wait_for_timeout(800)
        shot(page, "admin-servers.png")

        print("admin — users tab")
        page.click(".admin-nav-item[data-tab='users']")
        page.wait_for_timeout(800)
        shot(page, "admin-users.png")

        print("admin — access tab")
        page.click(".admin-nav-item[data-tab='access']")
        page.wait_for_timeout(800)
        # try to pick first non-devops user so grants panel renders
        try:
            page.locator("select#access-user option").nth(1).click(timeout=1500)
        except Exception:
            pass
        page.wait_for_timeout(600)
        shot(page, "admin-access.png")

        print("admin — activity tab")
        page.click(".admin-nav-item[data-tab='activity']")
        page.wait_for_timeout(800)
        shot(page, "admin-activity.png")

        ctx.close()
        browser.close()
    print("done.")


if __name__ == "__main__":
    main()
