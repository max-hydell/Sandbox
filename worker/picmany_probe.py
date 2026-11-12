#!/usr/bin/env python3
"""Inspect PicMany's public page structure for a single username.

Uses a normal logged-out browser session. No Instagram login, cookies, stealth,
challenge handling, proxy rotation, or request-limit bypass.
"""
from __future__ import annotations
import json, os, re, sys
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

USERNAME=os.getenv("TARGET_USERNAME","pickleballdotcom").strip().lstrip("@").lower()
if not re.fullmatch(r"[a-z0-9._]{1,30}", USERNAME):
    raise SystemExit("TARGET_USERNAME must be one valid username.")
BASE=f"https://picmany.com/{USERNAME}/"

def snapshot(page, label):
    return page.evaluate("""(label) => {
      const clean = s => (s || '').replace(/\\s+/g,' ').trim().slice(0,500);
      const links = [...document.querySelectorAll('a[href]')].map(a => ({
        text: clean(a.innerText || a.getAttribute('aria-label')), href: a.href
      })).slice(0,100);
      const media = [...document.querySelectorAll('img,video,source')].map(el => ({
        tag: el.tagName.toLowerCase(), alt: clean(el.getAttribute('alt')),
        src: el.currentSrc || el.src || el.getAttribute('src') || '',
        poster: el.poster || ''
      })).filter(x => x.src || x.poster).slice(0,100);
      const tabs = [...document.querySelectorAll('a,button,[role=tab]')].map(el => ({
        text: clean(el.innerText || el.getAttribute('aria-label')),
        href: el.href || '', role: el.getAttribute('role') || ''
      })).filter(x => /posts|reels|stories|highlights/i.test(x.text)).slice(0,30);
      return {label,title:document.title,url:location.href,links,media,tabs,
        text_preview:clean(document.body?.innerText).slice(0,4500)};
    }""", label)

def main():
    result={"username":USERNAME,"profile_url":BASE,"mode":"public PicMany page inspection",
            "sections":[],"scripts":[],"resource_hints":[],"navigation_errors":[]}
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True)
        context=browser.new_context(locale="en-US",timezone_id="America/New_York")
        page=context.new_page()
        page.set_default_timeout(5000)
        page.on("requestfailed", lambda req: result["navigation_errors"].append(
            {"url":req.url[:300],"error":(req.failure or "")[:200]}))
        try:
            response=page.goto(BASE,wait_until="domcontentloaded",timeout=45000)
            result["http_status"]=response.status if response else None
            # Do not wait for networkidle: analytics/long-poll requests may never settle.
            try: page.wait_for_load_state("load",timeout=5000)
            except PlaywrightTimeoutError: result["navigation_errors"].append({"note":"load event timeout; continuing"})
            page.wait_for_timeout(1800)
            result["final_url"]=page.url
            result["sections"].append(snapshot(page,"profile"))
            result["scripts"]=page.locator("script[src]").evaluate_all("(els)=>els.map(e=>e.src).slice(0,60)")
            result["resource_hints"]=page.locator('link[rel=preload],link[rel=prefetch],link[rel=preconnect]').evaluate_all(
                "(els)=>els.map(e=>({rel:e.rel,href:e.href,as:e.as||''})).slice(0,60)")
            # Click only visible tabs whose accessible label clearly matches.
            for word in ("posts","reels","stories","highlights"):
                candidates=page.locator("a,button,[role=tab]").filter(has_text=re.compile(rf"^{word}$",re.I))
                try:
                    if candidates.count():
                        candidates.first.click(timeout=2500)
                        page.wait_for_timeout(1000)
                        result["sections"].append(snapshot(page,word))
                except PlaywrightTimeoutError:
                    result["navigation_errors"].append({"tab":word,"note":"tab click timeout"})
        except Exception as e:
            result["error"]=f"{type(e).__name__}: {str(e)[:500]}"
            result["final_url"]=page.url
            try: result["sections"].append(snapshot(page,"partial"))
            except Exception: pass
        finally:
            context.close(); browser.close()
    print("PICMANY_PROBE_RESULT="+json.dumps(result,ensure_ascii=False))
    return 0

if __name__=="__main__":
    sys.exit(main())
