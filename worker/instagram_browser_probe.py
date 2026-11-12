#!/usr/bin/env python3
"""One-profile, logged-out Chromium diagnostic. No login, cookies, stealth, or retries."""
from __future__ import annotations

import json
import os
import re
import sys
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

USERNAME = os.getenv("TARGET_USERNAME", "pickleballdotcom").strip().lstrip("@").lower()
if not re.fullmatch(r"[a-z0-9._]{1,30}", USERNAME):
    raise SystemExit("TARGET_USERNAME must be one valid Instagram username.")

PROFILE_URL = f"https://www.instagram.com/{USERNAME}/"
POST_RE = re.compile(r"^/(?:p|reel)/[A-Za-z0-9_-]+/?$")
BLOCK_TERMS = (
    "log in to instagram", "log into instagram", "please wait",
    "challenge_required", "suspicious login", "try again later",
)

def main() -> int:
    report = {
        "username": USERNAME,
        "requested_url": PROFILE_URL,
        "mode": "fresh logged-out Chromium context",
        "final_url": None,
        "http_status": None,
        "page_title": None,
        "og_title": None,
        "og_description": None,
        "og_image_present": False,
        "visible_post_links": [],
        "classification": "unknown",
        "notes": [],
    }

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1365, "height": 900},
            locale="en-US",
            timezone_id="America/New_York",
        )
        page = context.new_page()
        try:
            response = page.goto(PROFILE_URL, wait_until="domcontentloaded", timeout=60000)
            report["http_status"] = response.status if response else None
            page.wait_for_timeout(3500)
            report["final_url"] = page.url
            report["page_title"] = page.title()
            report["og_title"] = page.locator('meta[property="og:title"]').get_attribute("content")
            report["og_description"] = page.locator('meta[property="og:description"]').get_attribute("content")
            report["og_image_present"] = bool(page.locator('meta[property="og:image"]').get_attribute("content"))
            hrefs = page.locator('a[href*="/p/"], a[href*="/reel/"]').evaluate_all(
                "(els) => els.map(a => { try { return new URL(a.href).pathname; } catch { return ''; } })"
            )
            report["visible_post_links"] = list(dict.fromkeys(h for h in hrefs if POST_RE.fullmatch(h)))[:12]
            body = (page.locator("body").inner_text(timeout=10000) or "")[:2500]
            lower = body.lower()
            final_path = urlparse(page.url).path.lower()
            if "/accounts/login" in final_path or any(term in lower for term in BLOCK_TERMS):
                report["classification"] = "login_or_access_interstitial"
            elif report["visible_post_links"] or report["og_title"] or report["og_description"]:
                report["classification"] = "public_profile_content_rendered"
            elif response and response.status in (401, 403, 429):
                report["classification"] = "access_denied_or_rate_limited"
            elif response and response.status >= 400:
                report["classification"] = "http_error"
            else:
                report["classification"] = "page_loaded_but_no_profile_metadata"
            report["body_preview"] = re.sub(r"\\s+", " ", body)[:700]
        except PlaywrightTimeoutError as exc:
            report["classification"] = "navigation_timeout"
            report["notes"].append(str(exc)[:300])
        except Exception as exc:
            report["classification"] = "browser_error"
            report["notes"].append(f"{type(exc).__name__}: {exc}"[:400])
        finally:
            context.close()
            browser.close()

    print("BROWSER_PROBE_RESULT=" + json.dumps(report, ensure_ascii=False))
    print("This diagnostic does not authenticate, solve challenges, or retry blocked requests.")
    return 0

if __name__ == "__main__":
    sys.exit(main())
