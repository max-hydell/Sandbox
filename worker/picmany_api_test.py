#!/usr/bin/env python3
"""Test whether PicMany's public Stories JSON endpoint is reachable by a plain HTTP client."""
import json
import os
import re
import sys
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

username = os.getenv("TARGET_USERNAME", "pickleballdotcom").strip().lstrip("@").lower()
if not re.fullmatch(r"[a-z0-9._]{1,30}", username):
    raise SystemExit("Invalid username")

url = f"https://picmany.com/api/profile/{username}/stories"
req = Request(url, headers={"Accept": "application/json", "User-Agent": "Sandbox-PicMany-Integration-Test/1.0"})
result = {"username": username, "url": url, "method": "GET", "client": "plain Python HTTP; no browser or cookies"}
try:
    with urlopen(req, timeout=25) as response:
        raw = response.read(2_000_000)
        result["http_status"] = response.status
        result["content_type"] = response.headers.get("Content-Type")
        try:
            payload = json.loads(raw)
            data = payload.get("data") or {}
            items = data.get("items") or []
            result["ok"] = payload.get("ok")
            result["item_count"] = len(items)
            result["pagination"] = data.get("pagination")
            result["meta"] = data.get("meta")
            result["sample_items"] = [
                {k: item.get(k) for k in ("id", "type", "publishedAt", "shortcode", "permalink", "videoUrl") if k in item}
                for item in items[:3]
            ]
            result["json_valid"] = True
        except Exception as exc:
            result["json_valid"] = False
            result["body_preview"] = raw[:500].decode("utf-8", "replace")
            result["parse_error"] = str(exc)[:200]
except HTTPError as exc:
    result["http_status"] = exc.code
    result["error"] = f"HTTP {exc.code}"
    result["body_preview"] = exc.read(500).decode("utf-8", "replace")
except (URLError, TimeoutError) as exc:
    result["error"] = str(exc)[:500]

print("PICMANY_API_TEST=" + json.dumps(result, ensure_ascii=False))
sys.exit(0)
