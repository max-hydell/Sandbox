# Instagram Feed Sandbox

## Automatic public-profile importer

GitHub Actions runs this worker every 6 hours and supports manual runs. It uses Instaloader without an Instagram login. Each run checks up to 12 eligible watchlist profiles, imports up to 12 posts per profile dated on or after August 1, 2026, saves available image/carousel media to the existing private Supabase bucket, and records account status and run history. Accounts marked private are excluded. Posts are deduplicated by the existing unique owner_id + shortcode key.

### Required GitHub secret (one-time setup)

1. Open https://github.com/max-hydell/Sandbox
2. Click **Settings**.
3. In the left sidebar, open **Secrets and variables → Actions**.
4. Under **Repository secrets**, click **New repository secret**.
5. Enter the name exactly: **SUPABASE_SERVICE_ROLE_KEY**
6. In the Secret field, paste the service-role secret key from the Sandbox Supabase project. In Supabase, open **Project Settings → API Keys** and copy the **service_role** secret key (or the newer secret key beginning sb_secret_). Do not use the publishable/anon key.
7. Click **Add secret**.

Never send this key in chat, put it in frontend variables, add it to source code, or commit it. It has elevated database access.

### Run once to test

1. Open the repository's **Actions** tab.
2. Select **Fetch public Instagram posts**.
3. Click **Run workflow → Run workflow**.
4. Open the run and inspect the **Import recent public posts** step.
5. When successful, the log ends with a batch-complete message. Refresh the Sandbox app to see imported posts.

The schedule runs every six hours. There are 46 non-private profiles; with 12 checked per run, one full rotation takes about 24 hours. A blocked account is marked error and retried in a later cycle.

### Limitations

Instaloader is unofficial, not an Instagram-approved API. Instagram may change its site, require login, throttle, or block requests. This worker does not log in, bypass access controls, evade rate limits, or fetch private content. This is best-effort automation, not guaranteed service.

## Frontend

The app uses Supabase email magic-link authentication, per-user RLS, feed/archive/profile views, likes, and signed URLs for private media. Configure VITE_SUPABASE_URL and VITE_SUPABASE_ANON_KEY for the frontend. Never expose the service-role key in the browser.
