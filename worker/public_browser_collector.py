#!/usr/bin/env python3
"""Public Instagram profile/post collector.

Reads only what Instagram renders to an ordinary logged-out browser. It does not
import/export cookies, log in, use proxies, solve challenges, or evade rate limits.
It records metadata and media URLs; it does not download media or write to a DB.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

USERNAME_RE = re.compile(r"^[A-Za-z0-9._]{1,30}$")
MAX_POSTS = int(os.getenv("MAX_POSTS", "12"))
MAX_CAROUSEL_SLIDES = int(os.getenv("MAX_CAROUSEL_SLIDES", "20"))
POST_WAIT_MS = int(os.getenv("POST_WAIT_MS", "1800"))
OUT = Path(os.getenv("OUTPUT_DIR", "artifacts/public-browser"))
PROFILE_URL_TEMPLATE = "https://www.instagram.com/{username}/"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_username(value: str) -> str:
    value = value.strip().lstrip("@")
    if not USERNAME_RE.fullmatch(value):
        raise ValueError("Username must contain only letters, numbers, periods, or underscores (1-30 chars).")
    return value


def belongs_to_profile(href: str, username: str) -> bool:
    try:
        path = urlparse(href).path.strip("/").split("/")
        return len(path) >= 2 and path[0].lower() == username.lower() and path[1] in {"p", "reel", "tv"} and bool(path[2] if len(path) > 2 else "")
    except Exception:
        return False


def unique(values):
    seen, output = set(), []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            output.append(value)
    return output


def main():
    parser = argparse.ArgumentParser(description="Inspect public Instagram posts anonymously.")
    parser.add_argument("--username", default=os.getenv("TARGET_USERNAME", "nate_bestic"))
    parser.add_argument("--headed", action="store_true", help="Show Chromium locally.")
    parser.add_argument("--max-posts", type=int, default=MAX_POSTS)
    args = parser.parse_args()
    username = normalize_username(args.username)
    max_posts = max(1, min(args.max_posts, 30))
    OUT.mkdir(parents=True, exist_ok=True)

    result = {
        "username": username,
        "requested_profile_url": PROFILE_URL_TEMPLATE.format(username=username),
        "started_at_utc": utc_now(),
        "mode": "anonymous_public_browser",
        "headed": bool(args.headed),
        "login_used": False,
        "cookies_imported": False,
        "cookies_exported": False,
        "media_downloads": False,
        "database_writes": False,
        "posts": [],
        "warnings": [],
    }
    events = []
    screenshots = []
    rate_limited = False

    def record_screenshot(page, filename):
        try:
            path = OUT / filename
            page.screenshot(path=str(path), full_page=True, animations="disabled", timeout=12000)
            screenshots.append(str(path))
        except Exception as exc:
            result["warnings"].append(f"Screenshot {filename} failed: {str(exc)[:200]}")

    def login_wall(page):
        url = page.url.lower()
        try:
            text = page.locator("body").inner_text(timeout=2500).lower()[:2500]
        except Exception:
            text = ""
        return (
            "/accounts/login" in url
            or "/challenge/" in url
            or "log in to instagram" in text
            or "log in or sign up" in text
        )

    def close_signup_overlay(page):
        # Dismiss only a visible, ordinary close control on the signup modal.
        selectors = [
            '[role="dialog"] button[aria-label="Close"]',
            '[role="dialog"] [aria-label="Close"]',
            'button[aria-label="Close"]',
        ]
        for selector in selectors:
            try:
                locator = page.locator(selector).first
                if locator.is_visible(timeout=700):
                    locator.click(timeout=1500)
                    page.wait_for_timeout(400)
                    events.append({"time": utc_now(), "type": "signup_overlay_closed", "selector": selector})
                    return True
            except Exception:
                pass
        return False

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not args.headed)
        context = browser.new_context(
            viewport={"width": 1440, "height": 1000},
            locale="en-US",
            timezone_id="America/New_York",
        )
        context.tracing.start(screenshots=True, snapshots=True, sources=True)
        page = context.new_page()
        page.set_default_timeout(8000)

        def on_response(response):
            nonlocal rate_limited
            host = urlparse(response.url).hostname or ""
            if "instagram.com" in host or "cdninstagram.com" in host or "fbcdn.net" in host:
                item = {"time": utc_now(), "status": response.status, "url": response.url[:900]}
                events.append(item)
                if response.status == 429:
                    rate_limited = True
                    result["warnings"].append("Instagram returned HTTP 429. Collection stopped immediately; no retry was attempted.")

        page.on("response", on_response)
        page.on("requestfailed", lambda req: events.append({
            "time": utc_now(), "type": "request_failed", "url": req.url[:900], "error": req.failure
        }) if "instagram.com" in (urlparse(req.url).hostname or "") else None)

        try:
            record_screenshot(page, "00-before-navigation.png")
            response = page.goto(result["requested_profile_url"], wait_until="domcontentloaded", timeout=45000)
            result["profile_http_status"] = response.status if response else None
            page.wait_for_timeout(2500)
            result["profile_final_url"] = page.url
            result["profile_title"] = page.title()
            result["profile_login_wall"] = login_wall(page)
            record_screenshot(page, "01-profile-loaded.png")

            if not result["profile_login_wall"] and not rate_limited:
                result["signup_overlay_dismissed"] = close_signup_overlay(page)
                page.wait_for_timeout(800)
                record_screenshot(page, "02-profile-after-overlay.png")
                result["profile_text_excerpt"] = page.locator("body").inner_text(timeout=5000)[:4000]

                links = page.evaluate("""username => {
                    const prefix = '/' + username.toLowerCase() + '/';
                    return [...document.querySelectorAll('a[href]')]
                      .map(a => a.href)
                      .filter(h => {
                        try {
                          const u = new URL(h);
                          const p = u.pathname.split('/').filter(Boolean);
                          return u.hostname.endsWith('instagram.com') &&
                            p.length >= 2 && ('/' + p[0].toLowerCase() + '/') === prefix &&
                            ['p','reel','tv'].includes(p[1]) && !!p[2];
                        } catch { return false; }
                      });
                }""", username)
                profile_links = unique([u.split("?")[0].rstrip("/") + "/" for u in links])
                result["profile_post_links"] = profile_links[:max_posts]

                for index, permalink in enumerate(result["profile_post_links"], start=1):
                    if rate_limited:
                        break
                    post = {"index": index, "permalink": permalink, "opened_at_utc": utc_now()}
                    try:
                        response = page.goto(permalink, wait_until="domcontentloaded", timeout=35000)
                        page.wait_for_timeout(POST_WAIT_MS)
                        post["http_status"] = response.status if response else None
                        post["final_url"] = page.url
                        post["login_wall"] = login_wall(page)
                        if rate_limited:
                            post["status"] = "rate_limited"
                            result["posts"].append(post)
                            break
                        if post["login_wall"]:
                            post["status"] = "login_wall"
                            result["posts"].append(post)
                            break

                        post["metadata"] = page.evaluate("""() => {
                          const meta = (selector) => document.querySelector(selector)?.content || null;
                          const article = document.querySelector('article') || document.querySelector('main') || document.body;
                          const times = [...article.querySelectorAll('time[datetime]')].map(x => x.dateTime).filter(Boolean);
                          const captionCandidates = [
                            meta('meta[property="og:description"]'),
                            meta('meta[name="description"]'),
                            article.innerText
                          ].filter(Boolean);
                          const images = [...article.querySelectorAll('img')].map(img => ({
                            url: img.currentSrc || img.src || null,
                            alt: img.alt || '',
                            width: img.naturalWidth || 0,
                            height: img.naturalHeight || 0
                          })).filter(x => x.url && (x.width >= 120 || x.height >= 120));
                          const videos = [...article.querySelectorAll('video')].map(v => ({
                            url: v.currentSrc || v.src || null,
                            poster: v.poster || null,
                            width: v.videoWidth || 0,
                            height: v.videoHeight || 0
                          }));
                          return {
                            title: document.title,
                            description: captionCandidates[0] || null,
                            caption_text: captionCandidates[2] ? captionCandidates[2].slice(0, 5000) : null,
                            posted_at: times[0] || null,
                            canonical_url: document.querySelector('link[rel="canonical"]')?.href || location.href,
                            og_image: meta('meta[property="og:image"]'),
                            images, videos
                          };
                        }""")
                        post["carousel_slides"] = []
                        seen_slide_urls = set()
                        for slide_number in range(MAX_CAROUSEL_SLIDES):
                            slide_data = page.evaluate("""() => {
                              const article = document.querySelector('article') || document.querySelector('main') || document.body;
                              const imgs = [...article.querySelectorAll('img')].map(i => ({
                                url: i.currentSrc || i.src || null, alt: i.alt || '',
                                width: i.naturalWidth || 0, height: i.naturalHeight || 0
                              })).filter(i => i.url && (i.width >= 250 || i.height >= 250));
                              const next = [...article.querySelectorAll('button,[role="button"]')].find(b => {
                                const label = ((b.getAttribute('aria-label') || '') + ' ' +
                                  (b.getAttribute('title') || '')).toLowerCase();
                                return label.includes('next');
                              });
                              return {images: imgs, hasNext: !!next};
                            }""")
                            for img in slide_data["images"]:
                                if img["url"] not in seen_slide_urls:
                                    seen_slide_urls.add(img["url"])
                                    post["carousel_slides"].append(img)
                            if not slide_data["hasNext"]:
                                break
                            try:
                                next_button = page.locator('article button[aria-label*="Next" i], article [role="button"][aria-label*="Next" i], article button[title*="Next" i]').first
                                if not next_button.is_visible(timeout=500):
                                    break
                                next_button.click(timeout=1200)
                                page.wait_for_timeout(500)
                            except Exception:
                                break

                        post["status"] = "media_found" if (
                            post["metadata"].get("images") or post["metadata"].get("videos")
                            or post["carousel_slides"]
                        ) else "post_opened_no_media"
                        record_screenshot(page, f"post-{index:02d}.png")
                    except PlaywrightTimeoutError:
                        post["status"] = "navigation_timeout"
                    except Exception as exc:
                        post["status"] = "error"
                        post["error"] = repr(exc)[:800]
                    post["finished_at_utc"] = utc_now()
                    result["posts"].append(post)
                    if rate_limited:
                        break

        except Exception as exc:
            result["fatal_error"] = repr(exc)[:1200]
        finally:
            result["finished_at_utc"] = utc_now()
            result["rate_limited"] = rate_limited
            result["screenshots"] = screenshots
            result["summary"] = {
                "post_links_found": len(result.get("profile_post_links", [])),
                "posts_opened": len(result["posts"]),
                "posts_with_media": sum(1 for x in result["posts"] if x.get("status") == "media_found"),
                "image_urls_found": sum(len(x.get("metadata", {}).get("images", [])) for x in result["posts"]),
                "carousel_slide_urls_found": sum(len(x.get("carousel_slides", [])) for x in result["posts"]),
                "video_urls_found": sum(len(x.get("metadata", {}).get("videos", [])) for x in result["posts"]),
            }
            result["overall_status"] = (
                "rate_limited" if rate_limited else
                "login_wall" if result.get("profile_login_wall") else
                "media_found" if result["summary"]["posts_with_media"] else
                "no_media_found"
            )
            (OUT / "report.json").write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
            (OUT / "events.json").write_text(json.dumps(events, indent=2), encoding="utf-8")
            context.tracing.stop(path=str(OUT / "playwright-trace.zip"))
            context.close()
            browser.close()

    print(json.dumps({
        "username": username,
        "overall_status": result.get("overall_status"),
        "summary": result.get("summary"),
        "profile_url": result.get("profile_final_url"),
        "rate_limited": result.get("rate_limited"),
        "report": str(OUT / "report.json"),
        "events": str(OUT / "events.json"),
        "media_downloads": False,
        "database_writes": False,
    }), flush=True)
    if rate_limited:
        raise SystemExit("Instagram returned HTTP 429; stopping without retry.")


if __name__ == "__main__":
    main()
