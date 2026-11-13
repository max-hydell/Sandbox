#!/usr/bin/env python3
"""Non-destructive, no-login diagnostics for public Instagram feed sources.

No cookies, credentials, proxies, CAPTCHA solving, or rate-limit workarounds.
This script does not write to Supabase or download/store media.
"""
import json
import os
import re
import sys
from html import unescape

import requests

USERNAME = re.sub(r"[^A-Za-z0-9._]", "", os.getenv("TARGET_USERNAME", "pickleballdotcom"))
TIMEOUT = 20
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; SandboxPublicSourceDiagnostics/1.0)"}

def result(name, status, detail):
    print(json.dumps({"source": name, "status": status, "detail": detail}, ensure_ascii=False))

def request(url, name):
    try:
        response = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        if response.status_code in (401, 403, 429, 503):
            result(name, "blocked_or_limited", f"HTTP {response.status_code}; stopping without retries")
            return None
        response.raise_for_status()
        return response
    except Exception as exc:
        result(name, "error", str(exc)[:300])
        return None

def picmany():
    endpoints = {
        "PicMany stories": f"https://picmany.com/api/profile/{USERNAME}/stories",
        "PicMany posts": f"https://picmany.com/api/profile/{USERNAME}/cards/posts",
        "PicMany reels": f"https://picmany.com/api/profile/{USERNAME}/cards/reels",
    }
    for label, url in endpoints.items():
        response = request(url, label)
        if response is None:
            continue
        if "stories" in label.lower():
            try:
                data = response.json()
                items = data.get("data", {}).get("items", []) if isinstance(data, dict) else []
                result(label, "reachable", f"HTTP {response.status_code}; JSON; {len(items)} story items")
            except Exception:
                result(label, "unexpected_response", f"HTTP {response.status_code}; non-JSON response")
        else:
            cards = re.findall(r'<article\\b[^>]*class=["\\'][^"\\']*media-card', response.text, re.I)
            result(label, "reachable", f"HTTP {response.status_code}; {len(cards)} media cards in first page")

def instagram_logged_out():
    url = f"https://www.instagram.com/{USERNAME}/"
    response = request(url, "Instagram public profile HTML")
    if response is None:
        return
    html = response.text
    match = re.search(r'<meta[^>]+name=["\\']description["\\'][^>]+content=["\\']([^"\\']*)', html, re.I)
    description = unescape(match.group(1)) if match else ""
    if description and "log in" not in description.lower() and "create an account" not in description.lower():
        result("Instagram public profile HTML", "reachable", f"HTTP {response.status_code}; description metadata present ({len(description)} chars)")
    else:
        result("Instagram public profile HTML", "login_wall_or_missing_metadata", f"HTTP {response.status_code}; page length {len(html)}; no usable public description metadata")

def instaloader():
    try:
        import instaloader
        loader = instaloader.Instaloader(quiet=True, download_pictures=False, download_videos=False,
                                         download_video_thumbnails=False, save_metadata=False,
                                         compress_json=False, post_metadata_txt_pattern="")
        # Deliberately anonymous: no login, session file, cookies, or proxy.
        profile = instaloader.Profile.from_username(loader.context, USERNAME)
        result("Instaloader public profile", "reachable", f"profile loaded; posts={profile.mediacount}")
        count = 0
        try:
            for post in profile.get_posts():
                count += 1
                if count >= 3:
                    break
            result("Instaloader posts", "reachable" if count else "empty", f"read {count} post metadata records (max 3)")
        except Exception as exc:
            result("Instaloader posts", "error", str(exc)[:300])
        # Reels support depends on Instaloader version and Instagram's anonymous endpoint access.
        try:
            get_reels = getattr(profile, "get_reels", None)
            if get_reels is None:
                result("Instaloader reels", "unsupported_version", "installed Instaloader has no get_reels method")
            else:
                reels_count = 0
                for _ in get_reels():
                    reels_count += 1
                    if reels_count >= 3:
                        break
                result("Instaloader reels", "reachable" if reels_count else "empty", f"read {reels_count} reel metadata records (max 3)")
        except Exception as exc:
            result("Instaloader reels", "error", str(exc)[:300])
        result("Instaloader stories/highlights", "not_tested_login_required",
               "official Instaloader docs require login for stories and highlights; this test intentionally uses no login")
    except Exception as exc:
        result("Instaloader public profile", "error", str(exc)[:300])

if __name__ == "__main__":
    print(json.dumps({"test_username": USERNAME, "mode": "anonymous_read_only", "database_writes": False}))
    picmany()
    instagram_logged_out()
    instaloader()
