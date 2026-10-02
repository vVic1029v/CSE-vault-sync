"""Authentication: cookie jar on disk, session check, SSO browser login.

Secrets live in _state/cookies.json (see .gitignore) or env vars — never in
the vault, never on the command line if you can avoid it.
"""

import json
import time
from pathlib import Path

from .config import BASE, UA
from .utils import log


def load_cookies(path):
    """Return the cookie list from disk, or None when missing/unreadable."""
    path = Path(path)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def save_cookies(cookies, path):
    """Persist the cookie list (overwrites)."""
    path = Path(path)
    path.write_text(json.dumps(cookies, indent=2), encoding="utf-8")


def build_client(cookies):
    """Return an httpx client carrying the given cookies for brightspace."""
    import httpx
    client = httpx.Client(headers={"User-Agent": UA}, timeout=60)
    for cookie in cookies if isinstance(cookies, list) else []:
        if cookie.get("name") and cookie.get("value") is not None:
            client.cookies.set(cookie.get("name"), cookie.get("value"),
                               domain="brightspace.tudelft.nl")
    return client


def session_ok(cookies, api_version):
    """True when the cookie jar still yields a live Brightspace session."""
    if not cookies:
        return False
    try:
        with build_client(cookies) as client:
            response = client.get(
                f"{BASE}/d2l/api/lp/{api_version}/users/whoami", timeout=30)
            return response.status_code == 200
    except Exception:
        return False


def _snap(page, shots_dir, name):
    try:
        page.screenshot(path=str(shots_dir / f"{name}.png"))
    except Exception:
        pass


def _fill_first_visible(page, selectors, value):
    """Fill the first visible selector; return True when one worked."""
    for sel in selectors:
        try:
            loc = page.locator(sel).first
            if loc.count() and loc.is_visible():
                loc.fill(value)
                return True
        except Exception:
            continue
    return False


def _click_first_visible(page, selectors, settle=True):
    """Click the first visible selector; return True when one worked."""
    for sel in selectors:
        try:
            loc = page.locator(sel).first
            if loc.count() and loc.is_visible():
                loc.click()
                if settle:
                    page.wait_for_load_state("domcontentloaded", timeout=30000)
                    time.sleep(2)
                return True
        except Exception:
            continue
    return False


def _wait_for_brightspace_session(page, ctx, logfile):
    """Click through consent screens until Brightspace session cookies land."""
    for _ in range(24):
        if "brightspace.tudelft.nl" in page.url:
            names = {c["name"] for c in ctx.cookies()}
            if "d2lSessionVal" in names or "d2lSecureSessionVal" in names:
                return True
        if not _click_first_visible(page, [
                "button:has-text('Accept')", "button:has-text('Agree')",
                "button:has-text('Allow')", "button:has-text('Continue')",
                "button:has-text('Proceed')", "input[type='submit']"]):
            time.sleep(5)
    return False


def playwright_login(netid, password, state_dir, logfile=None):
    """Run the TU Delft SSO login in headless Chromium.

    Returns the cookie list and persists storage_state.json + cookies.json.
    Screenshots (filled/final) land in _state/shots/ for debugging.
    """
    from playwright.sync_api import sync_playwright
    state_dir = Path(state_dir)
    state_dir.mkdir(parents=True, exist_ok=True)
    shots = state_dir / "shots"
    shots.mkdir(exist_ok=True)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        ctx = browser.new_context(user_agent=UA, locale="en-US")
        page = ctx.new_page()
        page.goto(f"{BASE}/", wait_until="domcontentloaded", timeout=60000)
        time.sleep(3)
        page.wait_for_selector("input[type='password']", timeout=60000)
        if not _fill_first_visible(page, [
                "input[name='username']", "input[name='j_username']",
                "input[id*='user' i]", "input[type='text']"], netid):
            browser.close()
            raise RuntimeError("username field not found on IdP page")
        page.locator("input[type='password']").first.fill(password)
        _snap(page, shots, "filled")
        if not _click_first_visible(page, [
                "button[type='submit']", "input[type='submit']",
                "button:has-text('Login')", "button:has-text('Log in')"],
                settle=False):
            page.keyboard.press("Enter")
        page.wait_for_load_state("domcontentloaded", timeout=60000)
        time.sleep(4)
        ok = _wait_for_brightspace_session(page, ctx, logfile)
        _snap(page, shots, "final")
        cookies = ctx.cookies()
        names = {c["name"] for c in cookies}
        ctx.storage_state(path=str(state_dir / "storage_state.json"))
        slim = [{"name": c["name"], "value": c["value"],
                 "domain": c.get("domain", ""), "path": c.get("path", "/")}
                for c in cookies]
        (state_dir / "cookies.json").write_text(json.dumps(slim, indent=2))
        browser.close()
        if not ok and "d2lSessionVal" not in names \
                and "d2lSecureSessionVal" not in names:
            raise RuntimeError(
                f"SSO did not yield a Brightspace session (at {page.url})")
        return slim
