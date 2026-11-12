import { createClient } from '@supabase/supabase-js';
import './style.css';

const SUPABASE_URL = import.meta.env.VITE_SUPABASE_URL;
const SUPABASE_KEY = import.meta.env.VITE_SUPABASE_ANON_KEY;
const supabase = SUPABASE_URL && SUPABASE_KEY ? createClient(SUPABASE_URL, SUPABASE_KEY) : null;
const $ = (s) => document.querySelector(s);
let session = null;
let activeTab = 'home';
let accounts = [];
let posts = [];
let busy = false;
let activeProfile = null;
const FEED_CUTOFF = new Date('2026-08-01T00:00:00');
const afterFeedCutoff = p => { const d = new Date(p.posted_at); return Number.isFinite(d.getTime()) && d >= FEED_CUTOFF; };
const feedPosts = () => posts.filter(p => afterFeedCutoff(p) && !(p.media_type === 'story' && p.expires_at && new Date(p.expires_at) <= new Date()));

const esc = (v='') => String(v).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const initials = (s='?') => esc(s.replace(/^@/,'').slice(0,2).toUpperCase());
const dateLabel = (v) => v ? new Date(v).toLocaleDateString(undefined,{month:'short',day:'numeric'}) : '';
const statusLabel = (s) => ({active:'Following',private:'Private',not_found:'Not found',error:'Check failed',pending:'Pending'})[s] || s;

function shell() {
  $('#app').innerHTML = `
    <header class="topbar"><div class="brand"><img class="brand-logo" src="${import.meta.env.BASE_URL}sandbox.png" alt="Sandbox logo"/><img class="brand-wordmark" src="${import.meta.env.BASE_URL}sandboxtext.png" alt="Sandbox"/></div><button id="refresh" class="icon-btn" aria-label="Refresh feed">↻</button></header>
    <main id="content"></main>
    <nav class="bottom-nav">
      <button data-tab="home" class="${activeTab==='home'?'selected':''}"><span>⌂</span>Home</button>
      <button data-tab="grid" class="${activeTab==='grid'?'selected':''}"><span>▦</span>Grid</button>
      <button data-tab="watchlist" class="${activeTab==='watchlist'?'selected':''}"><span>◎</span>Watchlist</button>
      <button data-tab="settings" class="${activeTab==='settings'?'selected':''}"><span>⚙</span>Settings</button>
    </nav>`;
  document.querySelectorAll('[data-tab]').forEach(b=>b.addEventListener('click',()=>{activeProfile=null;activeTab=b.dataset.tab;render();}));
  $('#refresh').addEventListener('click', refreshFeed);
  render();
}

function render() {
  document.querySelectorAll('[data-tab]').forEach(b=>b.classList.toggle('selected',b.dataset.tab===activeTab));
  const host = $('#content');
  if (!session) return renderAuth(host);
  if (activeProfile) return renderProfile(host);
  if (activeTab==='watchlist') return renderWatchlist(host);
  if (activeTab==='settings') return renderSettings(host);
  if (activeTab==='grid') return renderGrid(host);
  renderHome(host);
}

function renderAuth(host) {
  host.innerHTML = `<section class="auth-card"><div class="eyebrow">YOUR PRIVATE VIEW</div><h1>See the posts<br/>you care about.</h1><p>Follow public Instagram profiles in one clean feed. No Instagram login, no real engagement, and no private-account access.</p><form id="auth-form"><label>Email address</label><input id="email" type="email" placeholder="you@example.com" required/><button class="primary" type="submit">Send sign-in link</button></form><p id="auth-msg" class="muted">A magic link will sign you into your own private workspace.</p></section>`;
  $('#auth-form').addEventListener('submit', async e=>{e.preventDefault();const email=$('#email').value.trim();const {error}=await supabase.auth.signInWithOtp({email,options:{emailRedirectTo:location.origin+import.meta.env.BASE_URL}});$('#auth-msg').textContent=error?error.message:'Check your email for your sign-in link.';});
}

function renderHome(host) {
  host.innerHTML = `<section class="page-head"><div><div class="eyebrow">YOUR FEED</div><h1>Latest posts</h1><p>Posts and Stories published since August 1, 2026</p></div><span class="count">${feedPosts().filter(p=>!p.liked).length} POSTS</span></section>
  <div id="feed-list">${feedPosts().filter(p=>!p.liked).length?feedPosts().filter(p=>!p.liked).map(postCard).join(''):'<div class="empty"><div class="empty-icon">✓</div><h3>You’re all caught up</h3><p>New posts will appear once a supported public-post source adds them. Liked posts are kept in your archive.</p><button class="primary" id="go-watch">View profiles</button></div>'}</div>`;
  $('#go-watch')?.addEventListener('click',()=>{activeTab='watchlist';render();});
  bindPostActions();
  hydrateMedia();
}
function postCard(p) {
  const img = p.image_paths?.[0] ? p.image_paths[0] : p.image_url || '';
  return `<article class="post"><div class="post-head"><div class="avatar">${initials(p.username)}</div><div class="post-user"><button class="profile-link" data-profile="${esc(p.username)}">@${esc(p.username)}</button><small>${dateLabel(p.posted_at||p.discovered_at)}</small></div>${p.is_new?'<span class="new-pill">NEW</span>':''}<a class="open-link" href="${esc(p.post_url||'#')}" target="_blank" rel="noreferrer">↗</a></div>
  ${img?(p.image_paths?.[0]?'<img class="post-image" data-media-path="'+esc(img)+'" alt="Post by @'+esc(p.username)+'" loading="lazy"/>':'<img class="post-image" src="'+esc(img)+'" alt="Post by @'+esc(p.username)+'" loading="lazy"/>'):'<div class="media-placeholder">MEDIA NOT AVAILABLE</div>'}
  <div class="post-actions"><button data-like="${p.id}" class="like ${p.liked?'liked':''}">${p.liked?'♥':'♡'} <span>${p.liked?'Liked':'Like'}</span></button><span class="post-type">${esc(p.media_type||'post')}</span></div>
  <p class="caption"><b>@${esc(p.username)}</b> ${esc(p.caption||'')}</p></article>`;
}
async function hydrateMedia(){for(const img of document.querySelectorAll('[data-media-path]')){const {data,error}=await supabase.storage.from('instagram-media').createSignedUrl(img.dataset.mediaPath,3600);if(!error&&data?.signedUrl)img.src=data.signedUrl;}}
function bindPostActions(){
  document.querySelectorAll('[data-like]').forEach(b=>b.addEventListener('click',async()=>{const p=posts.find(x=>x.id===b.dataset.like);if(!p)return;const liked=!p.liked;const {error}=await supabase.from('posts').update({liked}).eq('id',p.id);if(!error){p.liked=liked;render();}}));
  document.querySelectorAll('[data-profile]').forEach(b=>b.addEventListener('click',()=>{activeProfile=b.dataset.profile;render();}));
}
function renderProfile(host) {
  const username = activeProfile;
  const account = accounts.find(a=>a.username.toLowerCase()===username.toLowerCase());
  const profilePosts = posts.filter(p=>p.username.toLowerCase()===username.toLowerCase());
  host.innerHTML = '<section class="page-head profile-head"><div><button class="back-link" id="back-feed">← Back</button><div class="eyebrow">PUBLIC PROFILE</div><h1>@'+esc(username)+'</h1><p>Posts published since August 1, 2026</p></div><span class="count">'+profilePosts.length+' POSTS</span></section>' +
    '<div class="profile-summary"><span class="avatar">'+initials(username)+'</span><div><b>@'+esc(username)+'</b><small>'+(account?statusLabel(account.status):'Saved profile')+'</small></div></div>' +
    '<div id="profile-posts">'+(profilePosts.length?profilePosts.map(postCard).join(''):'<div class="empty compact">No saved posts from this profile since August 1, 2026.</div>')+'</div>';
  $('#back-feed').addEventListener('click',()=>{activeProfile=null;render();});
  bindPostActions();
  hydrateMedia();
}
function renderGrid(host) {
  host.innerHTML=`<section class="page-head"><div><div class="eyebrow">ARCHIVE</div><h1>Post grid</h1><p>All saved posts, including liked posts</p></div><span class="count">${posts.length} POSTS</span></section><div class="grid-posts">${posts.map(p=>{const img=p.image_paths?.[0]?p.image_paths[0]:p.image_url||'';return `<a class="grid-tile" href="${esc(p.post_url||'#')}" target="_blank" rel="noreferrer">${img?(p.image_paths?.[0]?'<img data-media-path="'+esc(img)+'" loading="lazy"/>':'<img src="'+esc(img)+'" loading="lazy"/>'):'<div class="media-placeholder">NO MEDIA</div>'}${p.is_new?'<i>NEW</i>':''}</a>`}).join('')||'<div class="empty">No saved posts yet.</div>'}</div>`;
  hydrateMedia();
}
function renderWatchlist(host) {
  host.innerHTML=`<section class="page-head"><div><div class="eyebrow">PROFILES</div><h1>Watchlist</h1><p>Only public profiles can be checked.</p></div></section>
  <form id="add-form" class="add-form"><input id="username" placeholder="Instagram username" autocomplete="off" required/><button class="primary" type="submit">Add</button></form>
  <form id="bulk-form" class="bulk-form"><textarea id="bulk-usernames" rows="2" placeholder="Add multiple usernames, separated by commas or new lines"></textarea><button class="secondary" type="submit">Add multiple</button></form>
  <p class="muted source-note">Public profiles are checked through PicMany. New posts, Reels, and available Stories appear after a successful import.</p><div class="profile-list">${accounts.map(a=>`<div class="profile-row"><div class="avatar">${initials(a.username)}</div><div class="profile-info"><button class="profile-link" data-profile="${esc(a.username)}">@${esc(a.username)}</button><small>${statusLabel(a.status)} ${a.last_checked_at?'· Checked '+dateLabel(a.last_checked_at):''}</small></div><button class="remove" data-remove="${a.id}" aria-label="Remove @${esc(a.username)}">×</button></div>`).join('')||'<div class="empty compact">No profiles added yet.</div>'}</div><p id="watch-msg" class="muted"></p>`;
  $('#add-form').addEventListener('submit',async e=>{e.preventDefault();await addNames([$('#username').value]);});
  $('#bulk-form').addEventListener('submit',async e=>{e.preventDefault();await addNames($('#bulk-usernames').value.split(/[\s,]+/));});
  document.querySelectorAll('[data-profile]').forEach(b=>b.addEventListener('click',()=>{activeProfile=b.dataset.profile;render();}));
  document.querySelectorAll('[data-remove]').forEach(b=>b.addEventListener('click',async()=>{const {error}=await supabase.from('accounts').delete().eq('id',b.dataset.remove);if(error)alert(error.message);else await loadData();}));
}
async function addNames(names){const clean=[...new Set(names.map(x=>x.trim().replace(/^@/, '').toLowerCase()).filter(x=>/^[a-z0-9._]{1,30}$/.test(x)))];if(!clean.length)return;const {error}=await supabase.from('accounts').upsert(clean.map(username=>({owner_id:session.user.id,username,status:'pending'})),{onConflict:'owner_id,username',ignoreDuplicates:true});$('#watch-msg').textContent=error?error.message:`Added ${clean.length} profile(s). PicMany will check these public profiles on the next import run.`;await loadData();}
function renderSettings(host){host.innerHTML=`<section class="page-head"><div><div class="eyebrow">PREFERENCES</div><h1>Settings</h1><p>Your sandbox workspace</p></div></section><div class="settings-card"><div><b>Signed in</b><p>${esc(session.user.email)}</p></div><button class="secondary" id="signout">Sign out</button></div><div class="settings-card"><div><b>Privacy rules</b><p>Public profiles only. No Instagram login, private content, or real likes/comments/DMs.</p></div></div><div class="settings-card"><div><b>Workspace data</b><p>${accounts.length} profiles · ${posts.length} saved posts</p></div></div>`;
  $('#signout').addEventListener('click',async()=>{await supabase.auth.signOut();});
}
async function loadData(){if(!session)return;const [a,p]=await Promise.all([supabase.from('accounts').select('*').order('created_at',{ascending:false}),supabase.from('posts').select('*').order('posted_at',{ascending:false,nullsFirst:false}).order('discovered_at',{ascending:false})]);if(a.error||p.error){console.error(a.error||p.error);return;}accounts=a.data||[];posts=p.data||[];render();}
async function refreshFeed(){if(busy||!session)return;busy=true;const b=$('#refresh');if(b)b.textContent='…';await loadData();if(b)b.textContent='↻';busy=false;}

async function start(){
  if(!supabase){$('#app').innerHTML='<div class="setup"><h1>One quick setup step</h1><p>Add the sandbox Supabase URL and publishable key to your hosting environment as <code>VITE_SUPABASE_URL</code> and <code>VITE_SUPABASE_ANON_KEY</code>, then rebuild.</p></div>';return;}
  shell();
  const {data:{session:s}}=await supabase.auth.getSession();session=s;
  supabase.auth.onAuthStateChange((_event,s)=>{session=s;loadData();});
  if(session)await loadData();else render();
}
start();
