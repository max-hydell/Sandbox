#!/usr/bin/env python3
"""One-shot, low-volume diagnostics for public Instagram/PicMany access.

No login, cookies, browser automation, challenge solving, proxying, or retries.
"""
import json
import os
import re
import time
from html.parser import HTMLParser
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

USERNAME = os.getenv("TARGET_USERNAME", "pickleballdotcom").strip().lstrip("@").lower()
if not re.fullmatch(r"[a-z0-9._]{1,30}", USERNAME):
    raise SystemExit("Invalid username")

HEADERS = {
    "User-Agent": "Sandbox-Public-Feed-Diagnostic/1.0 (+https://github.com/max-hydell/Sandbox)",
    "Accept": "text/html,application/json;q=0.9,*/*;q=0.5",
}
MAX_BYTES = 1_000_000

TESTS = [
    ("picmany_home", "https://picmany.com/"),
    ("picmany_profile", f"https://picmany.com/{quote(USERNAME)}/"),
    ("picmany_profile_api", f"https://picmany.com/api/profile/{quote(USERNAME)}"),
    ("picmany_stories_json", f"https://picmany.com/api/profile/{quote(USERNAME)}/stories"),
    ("picmany_posts_cards", f"https://picmany.com/api/profile/{quote(USERNAME)}/cards/posts"),
    ("picmany_reels_cards", f"https://picmany.com/api/profile/{quote(USERNAME)}/cards/reels"),
    ("instagram_public_profile", f"https://www.instagram.com/{quote(USERNAME)}/"),
    ("instagram_oembed", "https://www.instagram.com/api/v1/oembed/?url=" +
     quote(f"https://www.instagram.com/{USERNAME}/", safe="")),
]

def classify(status, headers, body):
    text = body[:12000].decode("utf-8", "replace").lower()
    cf = headers.get("cf-mitigated", "").lower()
    if cf == "challenge" or any(x in text for x in ("just a moment", "attention required", "challenge-platform", "/cdn-cgi/challenge")):
        return "challenge_or_bot_protection"
    if status == 429:
        return "rate_limited"
    if status in (401, 403):
        return "denied_or_requires_access"
    if status >= 500:
        return "server_error"
    if status >= 400:
        return "http_error"
    return "reachable"

def inspect_body(name, content_type, body):
    result = {}
    sample = body[:MAX_BYTES].decode("utf-8", "replace")
    result["bytes_read"] = len(body)
    result["body_preview"] = re.sub(r"\s+", " ", sample[:350]).strip()
    if "json" in (content_type or "").lower() or name.endswith("_json") or name.endswith("_api") or name == "instagram_oembed":
        try:
            data = json.loads(sample)
            result["json_valid"] = True
            if isinstance(data, dict):
                result["top_level_keys"] = list(data.keys())[:30]
                if isinstance(data.get("data"), dict):
                    inner = data["data"]
                    if isinstance(inner.get("items"), list):
                        result["item_count"] = len(inner["items"])
                    if isinstance(inner.get("pagination"), dict):
                        result["pagination"] = inner["pagination"]
                if isinstance(data.get("html"), str):
                    result["has_embed_html"] = bool(data["html"])
                if "ok" in data:
                    result["ok"] = data["ok"]
        except Exception:
            result["json_valid"] = False
    if "html" in (content_type or "").lower() or name.endswith("_cards") or name.endswith("_profile"):
        low = sample.lower()
        result["markers"] = {
            "media_card": "media-card" in low,
            "data_next": "data-next" in low,
            "post_links": "/p/" in low,
            "reel_links": "/reel/" in low,
            "login_wall": "login" in low and ("log in" in low or "accounts/login" in low),
        }
    return result

def run_one(name, url):
    req = Request(url, headers=HEADERS, method="GET")
    started = time.monotonic()
    item = {"name": name, "url": url, "method": "GET"}
    try:
        with urlopen(req, timeout=20) as response:
            body = response.read(MAX_BYTES)
            headers = response.headers
            status = response.status
            item.update({
                "status": status,
                "final_url": response.geturl(),
                "redirect_count": len(response.geturl() != url and [1] or []),
                "content_type": headers.get("Content-Type"),
                "server": headers.get("Server"),
                "cf_ray": headers.get("CF-Ray"),
                "cf_mitigated": headers.get("CF-Mitigated"),
                "classification": classify(status, headers, body),
            })
            item.update(inspect_body(name, headers.get("Content-Type", ""), body))
    except HTTPError as exc:
        body = exc.read(MAX_BYTES)
        headers = exc.headers
        item.update({
            "status": exc.code,
            "final_url": exc.geturl(),
            "content_type": headers.get("Content-Type"),
            "server": headers.get("Server"),
            "cf_ray": headers.get("CF-Ray"),
            "cf_mitigated": headers.get("CF-Mitigated"),
            "classification": classify(exc.code, headers, body),
        })
        item.update(inspect_body(name, headers.get("Content-Type", ""), body))
    except (URLError, TimeoutError, OSError) as exc:
        item.update({"classification": "network_error", "error": str(exc)[:250]})
    item["elapsed_ms"] = round((time.monotonic() - started) * 1000)
    return item

results = []
for index, (name, url) in enumerate(TESTS):
    if index:
        time.sleep(2)
    results.append(run_one(name, url))

summary = {
    "username": USERNAME,
    "client": "plain Python HTTP; no browser, login, cookies, retries, or challenge handling",
    "tests": results,
    "counts": {
        key: sum(1 for row in results if row.get("classification") == key)
        for key in sorted({row.get("classification", "unknown") for row in results})
    },
}
print("PICMANY_DIAGNOSTICS=" + json.dumps(summary, ensure_ascii=False))
