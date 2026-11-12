#!/usr/bin/env python3
"""PicMany public-profile importer for Sandbox.

Uses only ordinary public GET requests to PicMany's public pages/endpoints.
No Instagram login, cookies, proxy rotation, challenge bypass, or rate-limit evasion.
"""
from __future__ import annotations
import json, logging, os, re, sys, time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from urllib.parse import urljoin\nfrom html import unescape
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

SUPABASE_URL=os.environ["SUPABASE_URL"].rstrip("/")
SERVICE_KEY=os.environ["SUPABASE_SERVICE_ROLE_KEY"]
API=f"{SUPABASE_URL}/rest/v1"
PICMANY="https://picmany.com"
CUTOFF=datetime(2026,8,1,tzinfo=timezone.utc)
MAX_ACCOUNTS=int(os.getenv("MAX_ACCOUNTS_PER_RUN","8"))
MAX_ITEMS=int(os.getenv("MAX_ITEMS_PER_PROFILE","30"))
MAX_PAGES=int(os.getenv("MAX_PAGES_PER_SECTION","4"))
DELAY=float(os.getenv("PICMANY_REQUEST_DELAY","3"))
BUCKET="instagram-media"
DB_HEADERS={"apikey":SERVICE_KEY,"Authorization":f"Bearer {SERVICE_KEY}","Content-Type":"application/json"}
logging.basicConfig(level=logging.INFO,format="%(asctime)s %(levelname)s %(message)s")
log=logging.getLogger("sandbox-picmany")

class SourceUnavailable(Exception): pass
class RateLimited(Exception): pass

def make_session():
    s=requests.Session()
    s.headers.update({"User-Agent":"Sandbox-Public-Feed/1.0 (personal authorized integration)","Accept":"text/html,application/json;q=0.9,*/*;q=0.8","Referer":"https://picmany.com/"})
    retry=Retry(total=3,connect=3,read=2,status=3,backoff_factor=2,
      status_forcelist=(500,502,503,504),allowed_methods=frozenset(["GET"]),
      respect_retry_after_header=True,raise_on_status=False)
    s.mount("https://",HTTPAdapter(max_retries=retry))
    return s
http=make_session()

def rest(method,table,params=None,payload=None,prefer=None):
    h=dict(DB_HEADERS)
    if prefer:h["Prefer"]=prefer
    r=requests.request(method,f"{API}/{table}",headers=h,params=params,json=payload,timeout=40)
    if not r.ok:raise RuntimeError(f"Supabase {method} {table} failed ({r.status_code}): {r.text[:400]}")
    return r.json() if r.text else None

def get_public(url, *, json_expected=False):
    time.sleep(DELAY)
    r=http.get(url,timeout=(10,35))
    if r.status_code==429: raise RateLimited(f"PicMany returned 429 for {url}")
    if r.status_code>=500: raise SourceUnavailable(f"PicMany returned {r.status_code} for {url}")
    if r.status_code in (401,403): raise SourceUnavailable(f"PicMany denied public request ({r.status_code}) for {url}")
    r.raise_for_status()
    if json_expected and "json" not in r.headers.get("Content-Type","").lower():
        try:return r.json()
        except ValueError:raise SourceUnavailable(f"Expected JSON from {url}, received {r.headers.get('Content-Type')}")
    return r

def parse_date(value):
    if not value:return None
    try:
        d=datetime.fromisoformat(str(value).replace("Z","+00:00"))
        return (d if d.tzinfo else d.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)
    except (ValueError,TypeError):return None

class CardsParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True);self.cards=[];self.card=None;self.capture=None;self.buf=[];self.in_body=False
    def handle_starttag(self,tag,attrs):
        a=dict(attrs); cls=a.get("class","").split()
        if tag=="article" and "media-card" in cls:
            self.card={"href":None,"image":None,"caption":"","username":None,"date":None,"kind":"post"}
            self.cards.append(self.card)
        if not self.card:return
        if tag=="a" and self.card["href"] is None and a.get("href","").startswith(("/p/","/reel/","/tv/")):
            self.card["href"]=a["href"]
            if a["href"].startswith("/reel/"):self.card["kind"]="reel"
        if tag=="img" and not self.card["image"]:
            self.card["image"]=a.get("src") or a.get("data-src")
        if tag=="time":
            self.card["date"]=a.get("datetime") or a.get("title")
        if tag=="a" and "by" in cls:
            self.capture="username";self.buf=[]
        elif tag=="p" and "body" not in cls:
            self.capture="caption";self.buf=[]
    def handle_endtag(self,tag):
        if self.capture and ((self.capture=="username" and tag=="a") or (self.capture=="caption" and tag=="p")):
            val=" ".join("".join(self.buf).split())
            if self.capture=="username":self.card["username"]=val.lstrip("@") or None
            else:self.card["caption"]=val
            self.capture=None;self.buf=[]
        if tag=="article":self.card=None;self.capture=None
    def handle_data(self,data):
        if self.card and self.capture:self.buf.append(data)

def parse_cards(html, username):
    p=CardsParser();p.feed(html)
    out=[]
    for c in p.cards:
        href=c.get("href")
        if not href:continue
        slug=href.rstrip("/").split("/")[-1]
        dt=parse_date(c.get("date"))
        if not slug or not re.fullmatch(r"[A-Za-z0-9_-]+",slug):continue
        out.append({"shortcode":slug,"post_url":urljoin(PICMANY,href),"posted_at":dt.isoformat() if dt else None,
          "media_type":c["kind"],"caption":c.get("caption") or "","image_url":urljoin(PICMANY,c["image"]) if c.get("image") else None,
          "username":c.get("username") or username})
    return out

def fetch_cards(username, section):
    cursor=None; all_items=[]; seen=set()
    for _ in range(MAX_PAGES):
        url=f"{PICMANY}/api/profile/{username}/cards/{section}"
        if cursor:url+=f"?cursor={requests.utils.quote(cursor,safe='')}"
        response=get_public(url)
        html=response.text
        batch=parse_cards(html,username)
        for item in batch:
            if item["shortcode"] not in seen:
                seen.add(item["shortcode"]);all_items.append(item)
        m=re.search(r'data-next=["\']([^"\']+)["\']',html)
        cursor=unescape(m.group(1)) if m else None
        if not cursor or len(all_items)>=MAX_ITEMS:break
    return all_items[:MAX_ITEMS]

def story_items(payload):
    """Extract story-like records from PicMany JSON without assuming one envelope shape."""
    if not isinstance(payload,dict):return []
    candidates=[]
    def walk(x,depth=0):
        if depth>6:return
        if isinstance(x,dict):
            keys={k.lower() for k in x}
            media=any(k in keys for k in ("imageurl","displayurl","thumbnailurl","videourl","mediaurl","url"))
            ident=any(k in keys for k in ("id","shortcode","pk"))
            if media and ident:candidates.append(x)
            for v in x.values():walk(v,depth+1)
        elif isinstance(x,list):
            for v in x:walk(v,depth+1)
    walk(payload)
    out=[];seen=set()
    for x in candidates:
        low={k.lower():v for k,v in x.items()}
        sid=str(low.get("shortcode") or low.get("id") or low.get("pk") or "")
        if not sid or sid in seen:continue
        seen.add(sid)
        media=low.get("imageurl") or low.get("displayurl") or low.get("thumbnailurl") or low.get("mediaurl") or low.get("videourl")
        dt=parse_date(low.get("publishedat") or low.get("takenat") or low.get("timestamp") or low.get("createdat"))
        out.append({"shortcode":f"story_{sid}","post_url":low.get("permalink") or "",
          "posted_at":dt.isoformat() if dt else datetime.now(timezone.utc).isoformat(),
          "media_type":"story","caption":str(low.get("caption") or "")[:5000],
          "image_url":media if isinstance(media,str) else None})
    return out

def upload_media(owner_id,account_id,code,url):
    if not url:return None
    try:
        r=get_public(url)
        body=r.content
        if not body or len(body)>18*1024*1024:return None
        ctype=r.headers.get("Content-Type","image/jpeg").split(";")[0]
        ext={"image/png":"png","image/webp":"webp","image/jpeg":"jpg","image/gif":"gif"}.get(ctype)
        if not ext:return None
        path=f"{owner_id}/{account_id}/{code}/0.{ext}"
        u=requests.post(f"{SUPABASE_URL}/storage/v1/object/{BUCKET}/{path}",
          headers={"apikey":SERVICE_KEY,"Authorization":f"Bearer {SERVICE_KEY}","Content-Type":ctype,"x-upsert":"true"},data=body,timeout=60)
        if u.status_code not in (200,201):log.warning("Storage upload failed %s: %s",code,u.text[:160]);return None
        return path
    except (requests.RequestException,SourceUnavailable,RateLimited) as e:
        log.warning("Media not copied for %s: %s",code,e);return None

def save_item(account,item,existing):
    code=item["shortcode"]
    if code in existing:return False
    posted=parse_date(item.get("posted_at"))
    if posted and posted<CUTOFF:return False
    path=upload_media(account["owner_id"],account["id"],code,item.get("image_url"))
    row={"owner_id":account["owner_id"],"account_id":account["id"],"shortcode":code,
      "post_url":item.get("post_url") or None,"posted_at":posted.isoformat() if posted else datetime.now(timezone.utc).isoformat(),
      "media_type":item["media_type"],"caption":item.get("caption","")[:5000],
      "image_paths":[path] if path else [],"is_new":True,"liked":False,\n      "expires_at":(posted.replace(tzinfo=timezone.utc) if posted else datetime.now(timezone.utc)).isoformat() if item["media_type"]=="story" else None}
    rest("POST","posts",{"on_conflict":"owner_id,shortcode"},row,"resolution=ignore-duplicates,return=minimal")
    existing.add(code);return True

def check_account(account):
    username=account["username"].lower()
    rows=rest("GET","posts",{"select":"shortcode","owner_id":f"eq.{account['owner_id']}","account_id":f"eq.{account['id']}"}) or []
    existing={r["shortcode"] for r in rows};found=0;notes=[]
    # Stories endpoint is best-effort; if PicMany returns an unsupported envelope, do not fabricate records.
    try:
        payload=get_public(f"{PICMANY}/api/profile/{username}/stories",json_expected=True)
        for item in story_items(payload)[:MAX_ITEMS]:
            if save_item(account,item,existing):found+=1
        notes.append("stories checked")
    except (requests.RequestException,SourceUnavailable,RateLimited,ValueError) as e:
        notes.append(f"stories unavailable: {str(e)[:180]}")
        if isinstance(e,RateLimited):raise
    for section in ("posts","reels"):
        try:
            for item in fetch_cards(username,section):
                if save_item(account,item,existing):found+=1
            notes.append(f"{section} checked")
        except RateLimited:raise
        except (requests.RequestException,SourceUnavailable) as e:
            notes.append(f"{section} unavailable: {str(e)[:180]}")
    return found,notes

def main():
    target=os.getenv("TARGET_USERNAME","").strip().lstrip("@").lower()
    if target and not re.fullmatch(r"[a-z0-9._]{1,30}",target):raise ValueError("Invalid TARGET_USERNAME")
    params={"select":"id,owner_id,username,status,last_checked_at","status":"not.eq.private",
      "order":"last_checked_at.asc.nullsfirst,created_at.asc","limit":str(1 if target else MAX_ACCOUNTS)}
    if target:params["username"]=f"eq.{target}"
    accounts=rest("GET","accounts",params) or []
    if target and not accounts:raise RuntimeError(f"@{target} is not in the watchlist; no other accounts were selected.")
    if not accounts:log.info("No eligible accounts.");return
    for account in accounts:
        run=rest("POST","runs",payload={"owner_id":account["owner_id"],"trigger":os.getenv("RUN_TRIGGER","manual"),
          "accounts_checked":0,"new_posts_found":0,"status":"running"},prefer="return=representation")
        run_id=run[0]["id"] if run else None;status="active";err=None;found=0;notes=[]
        try:
            log.info("Checking @%s via PicMany",account["username"])
            found,notes=check_account(account)
        except RateLimited as e:
            status="error";err=str(e);notes.append("Stopped immediately after rate limit response.")
        except Exception as e:
            status="error";err=str(e)[:450];log.exception("Failed @%s",account["username"])
        rest("PATCH","accounts",{"id":f"eq.{account['id']}"},{"status":status,
          "last_checked_at":datetime.now(timezone.utc).isoformat(),"last_error":err}, "return=minimal")
        if run_id:rest("PATCH","runs",{"id":f"eq.{run_id}"},{"finished_at":datetime.now(timezone.utc).isoformat(),
          "accounts_checked":1,"new_posts_found":found,"status":"partial" if err else "completed",
          "notes":"; ".join(notes)[:8000]}, "return=minimal")
        log.info("@%s: %s new items; %s",account["username"],found,"; ".join(notes))
        if err and "429" in err:break

if __name__=="__main__":
    try:main()
    except Exception:log.exception("Importer failed");sys.exit(1)
