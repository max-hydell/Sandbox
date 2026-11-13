#!/usr/bin/env python3
"""Read-only test: can Browserless retrieve the newest Instagram feed IDs?

No Instagram credentials, cookies, scrolling, pagination, Supabase writes, or media downloads.
"""
import json, os, re, sys
from playwright.sync_api import sync_playwright

token=os.environ["BROWSERLESS_TOKEN"]
username=re.sub(r"[^A-Za-z0-9._]", "", os.getenv("TARGET_USERNAME","pickleballdotcom"))
url=f"wss://production-sfo.browserless.io?token={token}"
profile=f"https://www.instagram.com/{username}/"

def emit(**data):
    print(json.dumps(data, ensure_ascii=False))

with sync_playwright() as p:
    browser=p.chromium.connect_over_cdp(url, timeout=30000)
    try:
        context=browser.contexts[0] if browser.contexts else browser.new_context()
        page=context.new_page()
        response=page.goto(profile, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(3500)
        final_url=page.url
        html=page.content()
        # Instagram's logged-out profile bootstrap serializes Polaris post objects.
        ids=list(dict.fromkeys(re.findall(r'"id"\\s*:\\s*"(POLARIS_[^"]+)"', html)))
        cursors=list(dict.fromkeys(re.findall(r'"end_cursor"\\s*:\\s*"([^"]+)"', html)))
        login_wall=("accounts/login" in final_url.lower() or
                    "See photos, videos and more" in html or
                    "Log in" in page.locator("body").inner_text()[:1200])
        result={
          "test":"browserless_latest_12_read_only",
          "username":username,
          "http_status":response.status if response else None,
          "final_url":final_url,
          "login_wall_detected":login_wall,
          "unique_post_ids_found":len(ids),
          "post_ids":ids[:12],
          "pagination_cursor_present":bool(cursors),
          "database_writes":False,
          "scrolling":False,
          "result":"PASS" if len(ids)>=1 and not ("accounts/login" in final_url.lower()) else "FAIL"
        }
        emit(**result)
        if result["result"]!="PASS": sys.exit(2)
    finally:
        browser.close()
