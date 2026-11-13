#!/usr/bin/env python3
"""Read-only BrowserQL test for Instagram's logged-out public profile bootstrap.

Extracts the embedded post IDs and nearby timestamps from public profile HTML.
No Instagram credentials/cookies, interaction, scrolling, pagination, media downloads,
or Supabase writes.
"""
import json
import os
import re
import sys
import requests

username = re.sub(r"[^A-Za-z0-9._]", "", os.getenv("TARGET_USERNAME", "pickleballdotcom"))
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
html = ((data.get("html") or {}).get("html")) or ""
if not html:
    raise RuntimeError("BrowserQL returned no HTML: " + json.dumps(payload)[:1500])

# Keep the first occurrence/order of each post ID in the embedded bootstrap data.
ids = list(dict.fromkeys(re.findall(r'"id"\s*:\s*"(POLARIS_[^"]+)"', html)))
# Capture a timestamp only when it appears close to a matched post ID.
posts = []
for post_id in ids[:12]:
    pos = html.find(post_id)
    nearby = html[max(0, pos - 250):pos + 5000]
    ts_match = re.search(r'"(?:taken_at|taken_at_timestamp|taken_at_ts)"\s*:\s*(\d{9,13})', nearby)
    code_match = re.search(r'"code"\s*:\s*"([^"]+)"', nearby)
    posts.append({
        "id": post_id,
        "timestamp": int(ts_match.group(1)) if ts_match else None,
        "shortcode": code_match.group(1) if code_match else None,
    })

cursors = list(dict.fromkeys(re.findall(r'"end_cursor"\s*:\s*"([^"]+)"', html)))
login_wall = "accounts/login" in html.lower() or "Log into Instagram" in html
result = {
    "test": "browserql_public_profile_bootstrap_read_only",
    "username": username,
    "http_status": goto_status,
    "html_chars": len(html),
    "login_wall_detected": login_wall,
    "unique_post_ids_found": len(ids),
    "posts": posts,
    "pagination_cursor_present": bool(cursors),
    "database_writes": False,
    "instagram_login_used": False,
    "result": "PASS" if len(ids) >= 1 and not login_wall else "FAIL",
}
print(json.dumps(result, ensure_ascii=False, indent=2))
if result["result"] != "PASS":
    sys.exit(2)
