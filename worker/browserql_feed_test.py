#!/usr/bin/env python3
"""Read-only BrowserQL test for public Instagram profile grid posts.

Instagram may render the profile grid behind a signup modal. The modal alone is
not treated as a login wall. This extracts only links whose path belongs to the
requested username. No login, cookies, modal interaction, media downloads,
pagination, or Supabase writes.
"""
import html as html_lib
import json
import os
import re
import sys
import requests

username = re.sub(r"[^A-Za-z0-9._]", "", os.getenv("TARGET_USERNAME", "nate_bestic"))
token = os.environ["BROWSERLESS_TOKEN"]
profile_url = f"https://www.instagram.com/{username}/"
endpoint = "https://production-sfo.browserless.io/chromium/bql"

query = """
mutation PublicProfileHTML {
  goto(url: "%s", waitUntil: domContentLoaded) {
    status
  }
  waitForTimeout(time: 3500) {
    time
  }
  html {
    html
  }
}
""" % profile_url

response = requests.post(
    endpoint,
    params={"token": token},
    headers={"Content-Type": "application/json"},
    json={"query": query, "operationName": "PublicProfileHTML"},
    timeout=90,
)
response.raise_for_status()
payload = response.json()
if payload.get("errors"):
    raise RuntimeError(json.dumps(payload["errors"])[:2000])

data = payload.get("data") or {}
goto_status = (data.get("goto") or {}).get("status")
page_html = ((data.get("html") or {}).get("html")) or ""
if not page_html:
    raise RuntimeError("BrowserQL returned no HTML: " + json.dumps(payload)[:1500])

# Profile grid entries are ordinary anchors, not necessarily POLARIS_* JSON IDs.
anchor_pattern = re.compile(
    r'<a\b(?=[^>]*\bhref=["\']/' + re.escape(username) +
    r'/p/([^/"\']+)/?["\'])[^>]*>(.*?)</a>',
    re.IGNORECASE | re.DOTALL,
)
posts = []
seen = set()
for match in anchor_pattern.finditer(page_html):
    shortcode, body = match.group(1), match.group(2)
    if shortcode in seen:
        continue
    seen.add(shortcode)
    img = re.search(r'<img\b([^>]*)>', body, re.IGNORECASE | re.DOTALL)
    attrs = img.group(1) if img else ""
    alt_match = re.search(r'\balt=["\']([^"\']*)["\']', attrs, re.IGNORECASE)
    src_match = re.search(r'\bsrc=["\']([^"\']+)["\']', attrs, re.IGNORECASE)
    alt = html_lib.unescape(alt_match.group(1)) if alt_match else None
    src = html_lib.unescape(src_match.group(1)) if src_match else None
    date_match = re.search(r'\bon\s+(.+?)\.?$', alt or "", re.IGNORECASE)
    posts.append({
        "shortcode": shortcode,
        "permalink": f"https://www.instagram.com/{username}/p/{shortcode}/",
        "alt": alt,
        "date_from_alt": date_match.group(1) if date_match else None,
        "thumbnail_url": src,
        "has_thumbnail": bool(src),
        "is_carousel": "aria-label=\\"Carousel\\"" in body or "aria-label='Carousel'" in body,
    })

# A signup modal can coexist with a fully rendered grid; only call it blocked
# when no posts for the requested profile are present and login UI is present.
login_ui_present = bool(re.search(
    r'Log into Instagram|name=["\']password["\']|accounts/login',
    page_html, re.IGNORECASE
))
login_wall = len(posts) == 0 and login_ui_present
result = {
    "test": "browserql_public_profile_grid_read_only",
    "username": username,
    "http_status": goto_status,
    "html_chars": len(page_html),
    "signup_modal_text_present": "See photos, videos and more" in page_html,
    "login_wall_detected": login_wall,
    "unique_profile_posts_found": len(posts),
    "posts": posts[:12],
    "database_writes": False,
    "instagram_login_used": False,
    "media_downloads": False,
    "result": "PASS" if posts and any(p["has_thumbnail"] for p in posts) else "FAIL",
}
print(json.dumps(result, ensure_ascii=False, indent=2))
if result["result"] != "PASS":
    sys.exit(2)
