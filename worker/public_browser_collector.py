#!/usr/bin/env python3
"""Anonymous, read-only Instagram browser diagnostics with full-session evidence.

No login, cookies, saved browser profile, proxy, CAPTCHA solving, media downloads,
or database writes. Video/screenshots document only what the public browser sees.
"""
import json
import os
import re
import shutil
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
events = []
screenshots = []


def stamp():
    return datetime.now(timezone.utc).isoformat()


def screenshot(page, name):
    path = OUT / name
    try:
        page.screenshot(path=str(path), full_page=True, animations="disabled", timeout=15000)
        screenshots.append({"time": stamp(), "file": str(path), "url": page.url})
    except Exception as exc:
        events.append({"time": stamp(), "type": "screenshot_error", "file": name, "error": repr(exc)})


def is_login_wall(page):
    current = page.url.lower()
    try:
        text = page.locator("body").inner_text(timeout=4000)[:3000].lower()
    except Exception:
        text = ""
    return (
        "accounts/login" in current
        or "challenge/" in current
        or "captcha" in text
        or "log in to instagram" in text
        or "log in or sign up" in text
    )


def main():
    result = {
        "username": USERNAME,
        "profile_url": PROFILE_URL,
        "started_at_utc": stamp(),
        "mode": "anonymous_public_browser_read_only",
        "login_used": False,
        "cookies_imported": False,
        "saved_browser_profile": False,
        "proxy_or_captcha_bypass": False,
        "media_downloads": False,
        "database_writes": False,
        "posts": [],
    }
    video_path = None
    trace_path = OUT / "playwright-trace.zip"

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1440, "height": 1000},
            record_video_dir=str(OUT / "video-temp"),
            record_video_size={"width": 1440, "height": 1000},
            locale="en-US",
            timezone_id="America/New_York",
        )
        context.tracing.start(screenshots=True, snapshots=True, sources=True)
        page = context.new_page()
        page_video = page.video

        def on_response(response):
            host = urlparse(response.url).hostname or ""
            if any(domain in host for domain in ("instagram.com", "cdninstagram.com", "fbcdn.net")):
                item = {"time": stamp(), "type": "response", "status": response.status,
                        "host": host, "url": response.url[:700]}
                events.append(item)
                print(json.dumps(item), flush=True)

        def on_request_failed(request):
            host = urlparse(request.url).hostname or ""
            if any(domain in host for domain in ("instagram.com", "cdninstagram.com", "fbcdn.net")):
                item = {"time": stamp(), "type": "request_failed", "host": host,
                        "error": request.failure, "url": request.url[:700]}
                events.append(item)
                print(json.dumps(item), flush=True)

        page.on("response", on_response)
        page.on("requestfailed", on_request_failed)
        page.on("console", lambda msg: events.append({
            "time": stamp(), "type": "console", "level": msg.type, "text": msg.text[:1000]
        }) if msg.type == "error" else None)
        page.on("pageerror", lambda exc: events.append({
            "time": stamp(), "type": "page_error", "error": repr(exc)[:1200]
        }))

        try:
            events.append({"time": stamp(), "type": "browser_started", "url": PROFILE_URL})
            screenshot(page, "00-before-navigation.png")
            response = page.goto(PROFILE_URL, wait_until="domcontentloaded", timeout=45000)
            result["profile_http_status"] = response.status if response else None
            result["profile_initial_url"] = page.url
            screenshot(page, "01-after-domcontentloaded.png")

            # Observe the page in timed intervals to show redirects, overlays, and delayed UI.
            for seconds, name in [(2, "02-after-2-seconds.png"),
                                  (5, "03-after-5-seconds.png"),
                                  (10, "04-after-10-seconds.png")]:
                page.wait_for_timeout((seconds - (2 if seconds == 2 else 5 if seconds == 5 else 10)) * 1000
                                      if False else (2000 if seconds == 2 else 3000 if seconds == 5 else 5000))
                events.append({"time": stamp(), "type": "checkpoint", "label": name,
                               "url": page.url, "title": page.title()})
                screenshot(page, name)

            result["profile_final_url"] = page.url
            result["profile_title"] = page.title()
            result["profile_login_wall"] = is_login_wall(page)
            result["profile_body_text"] = page.locator("body").inner_text(timeout=5000)[:3000]
            screenshot(page, "05-login-wall-or-profile-diagnosis.png")

            if not result["profile_login_wall"]:
                links = page.evaluate("""username => {
                  const prefix = '/' + username + '/p/';
                  return [...new Set([...document.querySelectorAll('a[href]')]
                    .map(a => a.getAttribute('href'))
                    .filter(h => h && h.startsWith(prefix))
                    .map(h => new URL(h, location.origin).href.split('?')[0]))].slice(0, 12);
                }""", USERNAME)
                result["profile_post_links"] = links
                for index, permalink in enumerate(links[:MAX_POSTS], start=1):
                    post = {"index": index, "permalink": permalink, "started_at_utc": stamp()}
                    try:
                        post_response = page.goto(permalink, wait_until="domcontentloaded", timeout=35000)
                        page.wait_for_timeout(2500)
                        post["http_status"] = post_response.status if post_response else None
                        post["final_url"] = page.url
                        post["login_wall"] = is_login_wall(page)
                        screenshot(page, f"post-{index:02d}-loaded.png")
                        if post["login_wall"]:
                            post["status"] = "login_wall"
                        else:
                            post["media"] = page.evaluate("""() => ({
                              images: [...document.images].map(i => ({
                                src: i.currentSrc || i.src, alt: i.alt || '',
                                width: i.naturalWidth || 0, height: i.naturalHeight || 0
                              })).filter(i => i.src),
                              videos: [...document.querySelectorAll('video')].map(v => ({
                                src: v.currentSrc || v.src, poster: v.poster || '',
                                width: v.videoWidth || 0, height: v.videoHeight || 0
                              }))
                            })""")
                            post["status"] = "media_found" if (
                                post["media"]["images"] or post["media"]["videos"]
                            ) else "no_rendered_media"
                            screenshot(page, f"post-{index:02d}-media-state.png")
                    except PlaywrightTimeoutError:
                        post["status"] = "navigation_timeout"
                        screenshot(page, f"post-{index:02d}-timeout.png")
                    except Exception as exc:
                        post["status"] = "error"
                        post["error"] = repr(exc)[:1000]
                        screenshot(page, f"post-{index:02d}-error.png")
                    post["finished_at_utc"] = stamp()
                    result["posts"].append(post)
            else:
                events.append({"time": stamp(), "type": "login_wall_detected",
                               "url": page.url, "title": page.title()})

        except Exception as exc:
            result["fatal_error"] = repr(exc)[:1500]
            screenshot(page, "99-fatal-error.png")
        finally:
            result["finished_at_utc"] = stamp()
            result["summary"] = {
                "post_links_found": len(result.get("profile_post_links", [])),
                "posts_opened": len(result["posts"]),
                "posts_with_media": sum(1 for x in result["posts"] if x.get("status") == "media_found"),
                "images_found": sum(len(x.get("media", {}).get("images", [])) for x in result["posts"]),
                "videos_found": sum(len(x.get("media", {}).get("videos", [])) for x in result["posts"]),
            }
            result["overall_status"] = (
                "login_wall" if result.get("profile_login_wall")
                else "media_found" if result["summary"]["posts_with_media"]
                else "no_media_found"
            )
            result["screenshots"] = screenshots
            result["event_count"] = len(events)
            (OUT / "events.json").write_text(json.dumps(events, indent=2), encoding="utf-8")
            (OUT / "report.json").write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
            context.tracing.stop(path=str(trace_path))
            context.close()
            browser.close()
            if page_video:
                try:
                    video_path = Path(page_video.path())
                except Exception:
                    video_path = None

    # Playwright finalizes video when the context closes. Move it to a stable artifact name.
    if video_path and video_path.exists():
        shutil.move(str(video_path), str(OUT / "full-session.webm"))
    temp_dir = OUT / "video-temp"
    if temp_dir.exists():
        shutil.rmtree(temp_dir, ignore_errors=True)

    print(json.dumps({
        "username": USERNAME,
        "overall_status": result["overall_status"],
        "summary": result["summary"],
        "profile_final_url": result.get("profile_final_url"),
        "screenshots": len(screenshots),
        "video": str(OUT / "full-session.webm") if (OUT / "full-session.webm").exists() else None,
        "trace": str(trace_path),
        "events": str(OUT / "events.json"),
        "media_downloads": False,
        "database_writes": False,
    }), flush=True)


if __name__ == "__main__":
    main()
