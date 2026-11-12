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
        card_start = low.find("<article")
        card_end = low.find("</article>", card_start)
        if card_start >= 0:
            result["first_card_html"] = re.sub(r"\\s+", " ", sample[card_start:card_end+10 if card_end >= 0 else card_start+2500])[:2500]
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


# Verify the exact cursor parameter the importer intends to use. Only one next-page
# request per section is made, and only when PicMany advertises a cursor.
class CardLinks(HTMLParser):
    def __init__(self):
        super().__init__(); self.links=[]
    def handle_starttag(self, tag, attrs):
        if tag=="a":
            href=dict(attrs).get("href","")
            if href.startswith(("/p/","/reel/","/tv/")): self.links.append(href)

def probe_pagination(section):
    base=f"https://picmany.com/api/profile/{quote(USERNAME)}/cards/{section}"
    row={"name":f"pagination_{section}","base_url":base}
    try:
        with urlopen(Request(base,headers=HEADERS),timeout=20) as response:
            first=response.read(MAX_BYTES).decode("utf-8","replace")
        cursor_match=re.search(r"""data-next=["']([^"']+)["']""",first)
        if not cursor_match:
            row["result"]="no_next_cursor_advertised"
            return row
        cursor=cursor_match.group(1)
        parser=CardLinks();parser.feed(first)
        first_links=list(dict.fromkeys(parser.links))
        from urllib.parse import urlencode
        next_url=base+"?"+urlencode({"cursor":cursor})
        with urlopen(Request(next_url,headers=HEADERS),timeout=20) as response:
            second=response.read(MAX_BYTES).decode("utf-8","replace")
            row["next_status"]=response.status
            row["next_content_type"]=response.headers.get("Content-Type")
        parser2=CardLinks();parser2.feed(second)
        second_links=list(dict.fromkeys(parser2.links))
        row.update({
            "result":"cursor_request_tested",
            "first_page_item_links":len(first_links),
            "second_page_item_links":len(second_links),
            "overlap_count":len(set(first_links)&set(second_links)),
            "new_second_page_links":len(set(second_links)-set(first_links)),
            "second_page_has_cursor":bool(re.search(r"""data-next=["']([^"']+)["']""",second)),
            "query_parameter_tested":"cursor",
        })
    except HTTPError as exc:
        row.update({"result":"http_error","status":exc.code,"body_preview":exc.read(300).decode("utf-8","replace")})
    except Exception as exc:
        row.update({"result":"error","error":str(exc)[:250]})
    return row

for section in ("posts","reels"):
    time.sleep(2)
    results.append(probe_pagination(section))

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
