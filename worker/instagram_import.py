#!/usr/bin/env python3
"""Public-only Instagram importer. No login, private access, or rate-limit bypass."""
from __future__ import annotations
import os, sys, time, logging
from datetime import datetime, timezone
import requests, instaloader
from instaloader.exceptions import ConnectionException, InstaloaderException, LoginRequiredException, ProfileNotExistsException

SUPABASE_URL=os.environ["SUPABASE_URL"].rstrip("/")
SERVICE_KEY=os.environ["SUPABASE_SERVICE_ROLE_KEY"]
API=f"{SUPABASE_URL}/rest/v1"
CUTOFF=datetime(2026,8,1,tzinfo=timezone.utc)
MAX_ACCOUNTS=int(os.getenv("MAX_ACCOUNTS_PER_RUN","12"))
MAX_POSTS=int(os.getenv("MAX_POSTS_PER_PROFILE","12"))
BUCKET="instagram-media"
HEADERS={"apikey":SERVICE_KEY,"Authorization":f"Bearer {SERVICE_KEY}","Content-Type":"application/json"}
logging.basicConfig(level=logging.INFO,format="%(asctime)s %(levelname)s %(message)s")
log=logging.getLogger("sandbox-importer")
http=requests.Session()

class RateLimitPause(Exception):
    pass

class StopOnLongWait(instaloader.RateController):
    def sleep(self, secs):
        if secs > 60:
            raise RateLimitPause('Instagram requested a long cooldown; stopping this run to respect the limit.')
        time.sleep(secs)

def rest(method,table,params=None,payload=None,prefer=None):
    h=dict(HEADERS)
    if prefer: h["Prefer"]=prefer
    r=requests.request(method,f"{API}/{table}",headers=h,params=params,json=payload,timeout=45)
    if not r.ok: raise RuntimeError(f"Supabase {method} {table} failed ({r.status_code}): {r.text[:500]}")
    return r.json() if r.text else None

def upload(owner_id,account_id,shortcode,index,url):
    try:
        r=http.get(url,timeout=30,stream=True); r.raise_for_status()
        chunks=[]; total=0
        for chunk in r.iter_content(65536):
            if chunk:
                total+=len(chunk)
                if total>18*1024*1024: return None
                chunks.append(chunk)
        body=b"".join(chunks)
        if not body: return None
        path=f"{owner_id}/{account_id}/{shortcode}/{index}.jpg"
        u=requests.post(f"{SUPABASE_URL}/storage/v1/object/{BUCKET}/{path}",
          headers={"apikey":SERVICE_KEY,"Authorization":f"Bearer {SERVICE_KEY}","Content-Type":r.headers.get("Content-Type","image/jpeg"),"x-upsert":"true"},
          data=body,timeout=60)
        if u.status_code not in (200,201):
            log.warning("Storage upload failed %s: %s",shortcode,u.text[:200]); return None
        return path
    except requests.RequestException as e:
        log.warning("Media download failed %s: %s",shortcode,e); return None

def media_urls(post):
    images=[]; video=None
    try:
        if post.typename=="GraphSidecar":
            for node in post.get_sidecar_nodes():
                if getattr(node,"is_video",False): video=getattr(node,"video_url",None) or video
                else: images.append(getattr(node,"display_url",None))
        elif post.is_video:
            images.append(post.url); video=post.video_url
        else: images.append(post.url)
    except Exception as e: log.warning("Media enumeration failed %s: %s",post.shortcode,e)
    return [u for u in images if u],video

def save_post(account,post,existing):
    code=post.shortcode
    if code in existing: return False
    posted=post.date_utc.replace(tzinfo=timezone.utc)
    if posted<CUTOFF: return False
    urls,video=media_urls(post)
    paths=[]
    for i,url in enumerate(urls[:10]):
        p=upload(account["owner_id"],account["id"],code,i,url)
        if p: paths.append(p)
    kind="reel" if post.is_video else ("carousel" if post.typename=="GraphSidecar" else "post")
    row={"owner_id":account["owner_id"],"account_id":account["id"],"shortcode":code,
      "post_url":f"https://www.instagram.com/p/{code}/","posted_at":posted.isoformat(),
      "media_type":kind,"caption":(post.caption or "")[:5000],"image_paths":paths,"is_new":True,"liked":False}
    rest("POST","posts",{"on_conflict":"owner_id,shortcode"},row,"resolution=ignore-duplicates,return=minimal")
    existing.add(code)
    return True

def check_account(loader,account):
    try:
        profile=instaloader.Profile.from_username(loader.context,account["username"])
        if profile.is_private: return 0,"private","Private account — skipped by automatic checks."
        rows=rest("GET","posts",{"select":"shortcode","owner_id":f"eq.{account['owner_id']}","account_id":f"eq.{account['id']}"}) or []
        existing={x["shortcode"] for x in rows}; added=seen=0
        for post in profile.get_posts():
            if post.date_utc.replace(tzinfo=timezone.utc)<CUTOFF: break
            seen+=1
            if save_post(account,post,existing): added+=1
            if seen>=MAX_POSTS: break
        return added,"active",None
    except ProfileNotExistsException:
        return 0,"not_found","Instagram profile was not found or is unavailable."
    except RateLimitPause:
        raise
    except (LoginRequiredException,ConnectionException) as e:
        return 0,"error",f"Instagram blocked the request or required login: {str(e)[:350]}"
    except InstaloaderException as e:
        return 0,"error",str(e)[:450]
    except Exception as e:
        log.exception("Unexpected error checking @%s",account["username"])
        return 0,"error",str(e)[:450]

def main():
    target_username=os.getenv("TARGET_USERNAME","").strip().lstrip("@").lower()
    if target_username:
        if not target_username.replace("_","").replace(".","").isalnum():
            raise ValueError("TARGET_USERNAME must be a single Instagram username.")
        accounts=rest("GET","accounts",{"select":"id,owner_id,username,status,last_checked_at",
          "username":f"eq.{target_username}","status":"not.eq.private","limit":"1"}) or []
        if not accounts:
            raise RuntimeError(f"Target account @{target_username} was not found or is marked private; no other accounts were selected.")
        log.info("Single-account test mode: only @%s will be checked.",target_username)
    else:
        accounts=rest("GET","accounts",{"select":"id,owner_id,username,status,last_checked_at","status":"not.eq.private",
          "order":"last_checked_at.asc.nullsfirst,created_at.asc","limit":str(MAX_ACCOUNTS)}) or []
    if not accounts: log.info("No eligible accounts."); return
    loader=instaloader.Instaloader(quiet=True,download_pictures=False,download_videos=False,
      download_video_thumbnails=False,save_metadata=False,compress_json=False,
      max_connection_attempts=1,rate_controller=lambda ctx: StopOnLongWait(ctx))
    owners={}
    for a in accounts: owners.setdefault(a["owner_id"],[]).append(a)
    for owner,group in owners.items():
        run=rest("POST","runs",payload={"owner_id":owner,"trigger":os.getenv("RUN_TRIGGER","scheduled"),
          "accounts_checked":0,"new_posts_found":0,"status":"running"},prefer="return=representation")
        run_id=run[0]["id"] if run else None; checked=found=0; notes=[]; partial=False
        for a in group:
            log.info("Checking @%s",a["username"])
            try:
                added,status,error=check_account(loader,a)
            except RateLimitPause as e:
                added,status,error=0,'error',str(e)
                partial=True
                checked+=1
                rest('PATCH','accounts',{'id':f"eq.{a['id']}"},{'status':status,
                  'last_checked_at':datetime.now(timezone.utc).isoformat(),'last_error':error},'return=minimal')
                notes.append(f"@{a['username']}: stopped for rate limit ({error})")
                log.warning('%s No further Instagram requests will be made in this run.',error)
                break
            checked+=1; found+=added
            if status=='error': partial=True
            rest('PATCH','accounts',{'id':f"eq.{a['id']}"},{'status':status,
              'last_checked_at':datetime.now(timezone.utc).isoformat(),'last_error':error},'return=minimal')
            notes.append(f"@{a['username']}: {status}, {added} new"+(f" ({error})" if error else ''))
            time.sleep(4)
        if run_id:
            rest("PATCH","runs",{"id":f"eq.{run_id}"},{"finished_at":datetime.now(timezone.utc).isoformat(),
              "accounts_checked":checked,"new_posts_found":found,"status":"partial" if partial else "completed",
              "notes":"\n".join(notes)[:8000]},"return=minimal")
        log.info("Batch complete: %s checked, %s new posts",checked,found)

if __name__=="__main__":
    try: main()
    except Exception:
        log.exception("Worker failed"); sys.exit(1)
