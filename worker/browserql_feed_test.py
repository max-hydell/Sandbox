#!/usr/bin/env python3
"""Read-only BrowserQL diagnostic for the public Instagram profile grid."""
import html
import json
import os
import re
import sys
from html.parser import HTMLParser
import requests

username = re.sub(r"[^A-Za-z0-9._]", "", os.getenv("TARGET_USERNAME", "nate_bestic"))
token = os.environ["BROWSERLESS_TOKEN"]
profile_url = f"https://www.instagram.com/{username}/"
endpoint = "https://production-sfo.browserless.io/chromium/bql"

query = """
mutation PublicProfileHTML {
  goto(url: "%s", waitUntil: domContentLoaded) { status }
  waitForTimeout(time: 4000) { time }
  ifCloseSignup: if(selector: "svg[aria-label='Close']") {
    closeSignup: click(selector: "svg[aria-label='Close']", visible: true, timeout: 5000) { time }
  }
  waitAfterClose: waitForTimeout(time: 4000) { time }
  html { html }
}
""" % profile_url

response = requests.post(
    endpoint, params={"token": token},
    headers={"Content-Type": "application/json"},
    json={"query": query, "operationName": "PublicProfileHTML"},
    timeout=90,
)
response.raise_for_status()
payload = response.json()
if payload.get("errors"):
    raise RuntimeError(json.dumps(payload["errors"])[:2000])
data = payload.get("data") or {}
status = (data.get("goto") or {}).get("status")
page_html = ((data.get("html") or {}).get("html")) or ""
if not page_html:
    raise RuntimeError("BrowserQL returned empty HTML")

class GridParser(HTMLParser):
    def __init__(self, target):
        super().__init__(convert_charrefs=True)
        self.target = target
        self.anchor = None
        self.posts = []
        self.seen = set()
        self.hrefs = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "a":
            href = attrs.get("href", "")
            if re.search(r"/" + re.escape(self.target) + r"/p/", href):
                self.hrefs.append(href)
                match = re.search(r"/" + re.escape(self.target) + r"/p/([^/?#]+)/?", href)
                if match and match.group(1) not in self.seen:
                    self.anchor = {
                        "shortcode": match.group(1),
                        "permalink": f"https://www.instagram.com/{self.target}/p/{match.group(1)}/",
                        "alt": None, "thumbnail_url": None, "is_carousel": False,
                    }
                    self.seen.add(match.group(1))
        elif self.anchor is not None:
            if tag == "img":
                self.anchor["alt"] = attrs.get("alt")
                self.anchor["thumbnail_url"] = attrs.get("src")
            elif tag == "svg" and attrs.get("aria-label", "").lower() == "carousel":
                self.anchor["is_carousel"] = True

    def handle_endtag(self, tag):
        if tag == "a" and self.anchor is not None:
            alt = self.anchor["alt"] or ""
            dm = re.search(r"\bon\s+(.+?)\.?$", alt, re.I)
            self.anchor["date_from_alt"] = dm.group(1) if dm else None
            self.anchor["has_thumbnail"] = bool(self.anchor["thumbnail_url"])
            self.posts.append(self.anchor)
            self.anchor = None

parser = GridParser(username)
parser.feed(page_html)
posts = parser.posts
login_ui = bool(re.search(r"""Log into Instagram|name=["\']password["\']|accounts/login""", page_html, re.I))
login_wall = not parser.hrefs and login_ui
# Compact diagnostic snippets help distinguish login HTML from a rendered grid.
username_pos = page_html.lower().find(username.lower())
result = {
    "test": "browserql_public_profile_grid_diagnostic",
    "username": username,
    "http_status": status,
    "html_chars": len(page_html),
    "signup_modal_text_present": "See photos, videos and more" in page_html,
    "login_ui_present": login_ui,
    "login_wall_detected": login_wall,
    "profile_post_href_count": len(parser.hrefs),
    "sample_profile_hrefs": parser.hrefs[:8],
    "unique_profile_posts_found": len(posts),
    "posts": posts[:12],
    "username_occurrences": page_html.lower().count(username.lower()),
    "html_around_first_username": page_html[max(0, username_pos-250):username_pos+900] if username_pos >= 0 else None,
    "database_writes": False,
    "instagram_login_used": False,
    "media_downloads": False,
    "result": "PASS" if posts and any(p["has_thumbnail"] for p in posts) else "FAIL",
}
print(json.dumps(result, ensure_ascii=False, indent=2))
if result["result"] != "PASS":
    sys.exit(2)
