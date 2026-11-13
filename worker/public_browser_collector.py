#!/usr/bin/env python3
"""Scheduled, anonymous, read-only browser inspection of public Instagram posts.

This is an extraction feasibility test, not a production importer:
- no login, cookies, saved browser profile, proxy, CAPTCHA solving, or access bypass
- no media downloads and no Supabase/database writes
- only records post links and media URLs that the public page renders normally
"""
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

USERNAME = re.sub(r"[^A-Za-z0-9._]", "", os.getenv("TARGET_USERNAME", "nate_bestic"))[:30]
if not USERNAME:
    raise SystemExit("TARGET_USERNAME is empty after validation")

OUT = Path("artifacts/public-browser")
OUT.mkdir(parents=True, exist_ok=True)
PROFILE_URL = f"https://www.instagram.com/{USERNAME}/"
MAX_POSTS = 12
network_events = []


def is_login_wall(page):
    current = page.url.lower()
    try:
        text = page.locator("body").inner_text(timeout=4000)[:2500].lower()
    except Exception:
        text = ""
    return (
        "accounts/login" in current
        or "challenge/" in current
        or "captcha" in text
        or "log in to instagram" in text
        or "log in or sign up" in text
    )


def rendered_media(page):
    return page.evaluate("""() => {
      const absolute = value => {
        try { return value ? new URL(value, location.href).href : null; }
        catch (_) { return null; }
      };
      const images = [...document.images].map(img => ({
        tag: "img",
        alt: img.alt || "",
        currentSrc: absolute(img.currentSrc),
        src: absolute(img.getAttribute("src")),
        width: img.naturalWidth || img.width || 0,
        height: img.naturalHeight || img.height || 0
      })).filter(x => x.currentSrc || x.src);
      const videos = [...document.querySelectorAll("video")].map(video => ({
        tag: "video",
        currentSrc: absolute(video.currentSrc),
        src: absolute(video.getAttribute("src")),
        sources: [...video.querySelectorAll("source")].map(s => absolute(s.src)).filter(Boolean),
        poster: absolute(video.poster),
        width: video.videoWidth || 0,
        height: video.videoHeight || 0
      }));
      return {images, videos, title: document.title, url: location.href,
              text: (document.body?.innerText || "").slice(0, 1800)};
    }""")


def main():
    result = {
        "username": USERNAME,
        "profile_url": PROFILE_URL,
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
        "mode": "anonymous_public_browser_read_only",
        "login_used": False,
        "cookies_imported": False,
        "saved_browser_profile": False,
        "proxy_or_captcha_bypass": False,
        "media_downloads": False,
        "database_writes": False,
        "posts": [],
        "network_events": network_events,
    }

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1440, "height": 1000},
            locale="en-US",
            timezone_id="America/New_York",
        )
        page = context.new_page()
        page.on("response", lambda response: network_events.append({
            "status": response.status,
            "host": urlparse(response.url).hostname,
            "url": response.url[:500],
        }) if any(host in (urlparse(response.url).hostname or "") for host in
                  ("instagram.com", "cdninstagram.com", "fbcdn.net")) else None)
        page.on("requestfailed", lambda request: network_events.append({
            "failed": True,
            "host": urlparse(request.url).hostname,
            "error": request.failure,
            "url": request.url[:500],
        }) if any(host in (urlparse(request.url).hostname or "") for host in
                  ("instagram.com", "cdninstagram.com", "fbcdn.net")) else None)

        try:
            response = page.goto(PROFILE_URL, wait_until="domcontentloaded", timeout=45000)
            page.wait_for_timeout(5000)
            result["profile_http_status"] = response.status if response else None
            result["profile_final_url"] = page.url
            result["profile_title"] = page.title()
            result["profile_login_wall"] = is_login_wall(page)
            page.screenshot(path=str(OUT / "profile.png"), full_page=True)

            if not result["profile_login_wall"]:
                profile_data = page.evaluate("""username => {
                  const links = [...document.querySelectorAll('a[href]')];
                  const prefix = '/' + username + '/p/';
                  return [...new Set(links.map(a => a.getAttribute('href'))
                    .filter(h => h && h.startsWith(prefix))
                    .map(h => new URL(h, location.origin).href.split('?')[0]))].slice(0, 12);
                }""", USERNAME)
                result["profile_post_links"] = profile_data

                for index, permalink in enumerate(profile_data, start=1):
                    post = {
                        "index": index,
                        "permalink": permalink,
                        "status": "pending",
                    }
                    try:
                        post_response = page.goto(permalink, wait_until="domcontentloaded", timeout=35000)
                        page.wait_for_timeout(2500)
                        post["http_status"] = post_response.status if post_response else None
                        post["final_url"] = page.url
                        post["login_wall"] = is_login_wall(page)
                        if post["login_wall"]:
                            post["status"] = "login_wall"
                        else:
                            media = rendered_media(page)
                            post["title"] = media["title"]
                            post["images"] = media["images"]
                            post["videos"] = media["videos"]
                            post["status"] = "media_elements_found" if media["images"] or media["videos"] else "no_rendered_media"
                            page.screenshot(path=str(OUT / f"post-{index:02d}.png"), full_page=True)
                    except PlaywrightTimeoutError:
                        post["status"] = "navigation_timeout"
                    except Exception as exc:
                        post["status"] = "error"
                        post["error"] = repr(exc)[:1000]
                    result["posts"].append(post)

            result["summary"] = {
                "post_links_found": len(result.get("profile_post_links", [])),
                "posts_opened": len(result["posts"]),
                "posts_with_rendered_media": sum(
                    1 for post in result["posts"]
                    if post.get("status") == "media_elements_found"
                ),
                "images_found": sum(len(post.get("images", [])) for post in result["posts"]),
                "videos_found": sum(len(post.get("videos", [])) for post in result["posts"]),
            }
        except Exception as exc:
            result["fatal_error"] = repr(exc)[:1500]
            try:
                page.screenshot(path=str(OUT / "profile-error.png"), full_page=True)
            except Exception:
                pass
        finally:
            result["network_events"] = network_events[:250]
            context.close()
            browser.close()

    result["overall_status"] = (
        "login_wall" if result.get("profile_login_wall")
        else "media_found" if result.get("summary", {}).get("posts_with_rendered_media", 0)
        else "no_media_found"
    )
    (OUT / "report.json").write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({
        "username": USERNAME,
        "overall_status": result["overall_status"],
        "summary": result.get("summary"),
        "profile_login_wall": result.get("profile_login_wall"),
        "report": str(OUT / "report.json"),
        "media_downloads": False,
        "database_writes": False,
    }, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
