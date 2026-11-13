#!/usr/bin/env python3
"""Free, anonymous, read-only Instagram source comparison lab.

No login, cookies, proxies, CAPTCHA solving, media downloads, or database writes.
Writes diagnostics only to ./artifacts for inspection.
"""
import html
import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from urllib.parse import urlparse

import requests

USERNAME = re.sub(r"[^A-Za-z0-9._]", "", os.getenv("TARGET_USERNAME", "nate_bestic"))
BASE = Path("artifacts")
BASE.mkdir(exist_ok=True)
PROFILE = f"https://www.instagram.com/{USERNAME}/"
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/130.0.0.0 Safari/537.36"
results = []

def add(method, status, detail, **extra):
    row = {"method": method, "status": status, "detail": str(detail)[:1200], **extra}
    results.append(row)
    print(json.dumps(row, ensure_ascii=False), flush=True)

def run_cmd(method, args, timeout=120):
    try:
        p = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        out = p.stdout or ""
        err = p.stderr or ""
        (BASE / f"{method.lower().replace(' ', '_')}.stdout.txt").write_text(out[:500000], encoding="utf-8")
        (BASE / f"{method.lower().replace(' ', '_')}.stderr.txt").write_text(err[:30000], encoding="utf-8")
        lines = [x for x in out.splitlines() if x.strip()]
        add(method, "success" if p.returncode == 0 and lines else "failed",
            f"exit={p.returncode}; stdout_lines={len(lines)}; stderr={err[-500:]}", output_preview=lines[:12])
    except subprocess.TimeoutExpired:
        add(method, "timeout", f"Timed out after {timeout}s")
    except Exception as exc:
        add(method, "error", repr(exc))

def requests_probe():
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Accept": "text/html,application/xhtml+xml"})
    try:
        r = s.get(PROFILE, timeout=25, allow_redirects=True)
        body = r.text
        (BASE / "instagram_requests.html").write_text(body[:1_000_000], encoding="utf-8")
        links = re.findall(r'href=["\'](/' + re.escape(USERNAME) + r'/p/[^"\']+)', body, re.I)
        login = bool(re.search(r"accounts/login|Log into Instagram|name=[\"']password", body, re.I))
        add("Instagram direct HTML", "posts_found" if links else ("login_wall" if login else "no_posts"),
            f"HTTP {r.status_code}; final_url={r.url}; chars={len(body)}; target_post_links={len(set(links))}; login_ui={login}",
            final_url=r.url, post_links=list(dict.fromkeys(links))[:12], login_ui=login)
    except Exception as exc:
        add("Instagram direct HTML", "error", repr(exc))

def picmany_probe():
    endpoints = {
        "PicMany posts": f"https://picmany.com/api/profile/{USERNAME}/cards/posts",
        "PicMany reels": f"https://picmany.com/api/profile/{USERNAME}/cards/reels",
        "PicMany stories": f"https://picmany.com/api/profile/{USERNAME}/stories",
    }
    for name, url in endpoints.items():
        try:
            r = requests.get(url, headers={"User-Agent": UA, "Accept": "*/*"}, timeout=20)
            body = r.text
            (BASE / (name.lower().replace(" ", "_") + ".txt")).write_text(body[:200000], encoding="utf-8")
            count = len(re.findall(r"<article\b|media-card|\"shortcode\"|\"code\"", body, re.I))
            state = "blocked" if r.status_code in (401,403,429,503) else ("has_cards_or_ids" if count else "empty_or_changed_format")
            add(name, state, f"HTTP {r.status_code}; chars={len(body)}; card/id markers={count}; content_type={r.headers.get('content-type')}")
        except Exception as exc:
            add(name, "error", repr(exc))

def instaloader_probe():
    run_cmd("Instaloader anonymous", [
        "python", "-c",
        "import instaloader,json; "
        "L=instaloader.Instaloader(quiet=True,download_pictures=False,download_videos=False,"
        "download_video_thumbnails=False,save_metadata=False,compress_json=False); "
        "p=instaloader.Profile.from_username(L.context," + repr(USERNAME) + "); "
        "it=p.get_posts(); "
        "items=[]; "
        "exec('for x in it:\\n items.append({\"shortcode\":x.shortcode,\"date\":x.date_utc.isoformat(),\"typename\":x.typename})\\n if len(items)>=12: break'); "
        "print(json.dumps({\"mediacount\":p.mediacount,\"posts\":items}))"
    ], timeout=100)

def gallery_dl_rs_probe():
    # -j prints extraction metadata; it does not download media files.
    run_cmd("gallery-dl-rs native", [
        "/tmp/gallery-dl-rs/target/release/gallery-dl-rs",
        "--extractor", "native", "-j", "--range", "1-12", PROFILE
    ], timeout=120)

def ytdlp_probe():
    # Metadata-only probe; --skip-download prevents media retrieval.
    run_cmd("yt-dlp metadata-only", [
        "python", "-m", "yt_dlp", "--skip-download", "--dump-single-json",
        "--no-warnings", PROFILE
    ], timeout=60)

def browser_probe():
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 1000}, user_agent=UA)
            events = []
            page.on("response", lambda r: events.append({"status": r.status, "url": r.url[:350]}) if "instagram.com" in r.url else None)
            page.on("requestfailed", lambda r: events.append({"failed": r.url[:350], "error": r.failure}))
            try:
                response = page.goto(PROFILE, wait_until="domcontentloaded", timeout=45000)
                page.wait_for_timeout(5000)
                page.screenshot(path=str(BASE / "instagram_browser.png"), full_page=True)
                info = page.evaluate("""() => ({
                  url: location.href, title: document.title,
                  text: (document.body?.innerText || '').slice(0,5000),
                  anchors: [...document.querySelectorAll('a[href]')].map(a=>a.getAttribute('href')).filter(h=>h && h.includes('/p/')).slice(0,30),
                  images: [...document.images].slice(0,30).map(i=>({alt:i.alt,src:i.currentSrc||i.src})),
                  htmlLength: document.documentElement.outerHTML.length
                })""")
                (BASE / "instagram_browser_dom.json").write_text(json.dumps(info, indent=2), encoding="utf-8")
                add("Playwright anonymous browser", "posts_found" if info["anchors"] else ("login_wall" if "login" in info["url"].lower() or "Log in" in info["text"] else "no_posts"),
                    f"HTTP {response.status if response else 'no response'}; final_url={info['url']}; title={info['title']}; post_anchors={len(info['anchors'])}; images={len(info['images'])}",
                    browser_info=info, network_events=events[:100])
            except Exception as exc:
                add("Playwright anonymous browser", "navigation_error", repr(exc), network_events=events[:100])
                try: page.screenshot(path=str(BASE / "instagram_browser_error.png"), full_page=True)
                except Exception: pass
            browser.close()
    except Exception as exc:
        add("Playwright anonymous browser", "not_available", repr(exc))

def make_report():
    doc = {"username": USERNAME, "profile_url": PROFILE, "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "mode": "anonymous_read_only", "login_used": False, "cookies_used": False,
           "proxy_used": False, "captcha_bypass": False, "media_downloads": False,
           "database_writes": False, "results": results}
    (BASE / "results.json").write_text(json.dumps(doc, indent=2, ensure_ascii=False), encoding="utf-8")
    rows = "".join(f"<tr><td>{html.escape(x['method'])}</td><td>{html.escape(x['status'])}</td><td><pre>{html.escape(x['detail'])}</pre></td></tr>" for x in results)
    page = f"""<!doctype html><meta charset="utf-8"><title>Sandbox source test report</title>
<style>body{{font:15px system-ui;margin:32px;background:#101722;color:#e8edf5}}table{{border-collapse:collapse;width:100%}}td,th{{padding:12px;border:1px solid #435064;text-align:left;vertical-align:top}}pre{{white-space:pre-wrap;max-width:800px}}a{{color:#8bc5ff}}</style>
<h1>Sandbox free-source test report</h1><p>Target: <b>@{html.escape(USERNAME)}</b> · anonymous / read-only · {doc['created_utc']}</p>
<p>No login, cookies, proxy, CAPTCHA bypass, media downloads, or database writes.</p>
<table><tr><th>Method</th><th>Outcome</th><th>Diagnostic</th></tr>{rows}</table>
<p>Files: results.json, screenshots, page HTML snapshot, command stdout/stderr logs.</p>"""
    (BASE / "report.html").write_text(page, encoding="utf-8")

if __name__ == "__main__":
    print(json.dumps({"target": USERNAME, "mode": "anonymous_read_only", "media_downloads": False, "database_writes": False}))
    requests_probe()
    picmany_probe()
    instaloader_probe()
    ytdlp_probe()
    gallery_dl_rs_probe()
    browser_probe()
    make_report()
    print("REPORT_READY artifacts/report.html")
