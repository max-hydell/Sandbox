#!/usr/bin/env python3
"""Read-only Browserless connectivity test for public pages. No login or cookies."""
import json, os, re
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

TOKEN = os.environ["BROWSERLESS_TOKEN"]
USERNAME = re.sub(r"[^A-Za-z0-9._]", "", os.getenv("TARGET_USERNAME", "pickleballdotcom"))
ENDPOINT = f"wss://production-sfo.browserless.io?token={TOKEN}"

def emit(source, status, **details):
    print(json.dumps({"source": source, "status": status, **details}, ensure_ascii=False))

with sync_playwright() as p:
    browser = p.chromium.connect_over_cdp(ENDPOINT, timeout=30000)
    try:
        context = browser.contexts[0] if browser.contexts else browser.new_context()
        page = context.new_page()
        page.set_default_navigation_timeout(30000)
        for label, url in [
            ("Instagram public profile", f"https://www.instagram.com/{USERNAME}/"),
            ("PicMany public profile", f"https://picmany.com/{USERNAME}"),
        ]:
            try:
                response = page.goto(url, wait_until="domcontentloaded")
                page.wait_for_timeout(2500)
                title = awaitable = page.title()
                current_url = page.url
                body = (page.locator("body").inner_text(timeout=5000) or "")[:2500]
                status_code = response.status if response else None
                low = body.lower()
                if status_code in (401, 403, 429, 503) or any(x in low for x in ["rate limit", "try again later", "temporarily blocked", "access denied"]):
                    state = "blocked_or_limited"
                elif "login" in current_url.lower() and "instagram.com" in current_url.lower():
                    state = "login_wall"
                elif status_code and status_code < 400:
                    state = "reachable"
                else:
                    state = "unclear"
                emit(label, state, http_status=status_code, final_url=current_url, title=title, body_preview=body[:900])
            except PlaywrightTimeoutError as exc:
                emit(label, "navigation_timeout", error=str(exc)[:300], final_url=page.url)
            except Exception as exc:
                emit(label, "error", error=str(exc)[:400])
    finally:
        browser.close()
