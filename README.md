# Instagram Feed Sandbox

## Public PicMany importer

Sandbox now imports public profile cards from PicMany using ordinary HTTP GET requests. It checks the public Stories JSON endpoint and the public Posts/Reels card endpoints, parses the visible card data, follows the supplied pagination cursor, deduplicates by owner + content shortcode, and stores available image thumbnails in the existing private Supabase Storage bucket.

The importer is currently **manual-only** while the PicMany response formats are validated against live accounts. It does not use Instagram login, private content, browser automation, cookies, challenge handling, proxy rotation, or rate-limit bypasses. Temporary 5xx responses are retried with backoff; a 429 stops the run rather than attempting to evade the limit.

### Required GitHub secret

The repository needs `SUPABASE_SERVICE_ROLE_KEY` under **Settings → Secrets and variables → Actions**. Use the Sandbox project's service-role/secret key. Never expose it in frontend code or commit it.

### Test the importer

1. Open the repository's **Actions** tab.
2. Select **Fetch public PicMany posts**.
3. Click **Run workflow**.
4. For a single-account test, enter a username that is already in the Sandbox watchlist. Leave it blank to process the normal batch.
5. Review the import log and confirm the run summary and newly inserted rows in Supabase.

The workflow runs parser regression tests before it imports anything. The scheduled cron remains disabled until the live importer has been confirmed against actual PicMany responses.

### Current coverage and limitations

- Posts and Reels: public card HTML, thumbnails, captions, timestamps, and pagination.
- Stories: best-effort JSON parsing; the exact response schema must be confirmed against the live endpoint before relying on it.
- Highlights: not enabled yet because no confirmed Highlights endpoint/response was supplied.
- Video playback/download: not yet implemented; Reels currently appear with their available thumbnail and link to PicMany.
- Stories are marked to expire 24 hours after their published timestamp and are hidden from the live feed after expiry.
- PicMany can change its public page structure, return temporary errors, or limit requests. The importer is best-effort and respects 429 responses.

## Frontend

The app uses Supabase email magic-link authentication, per-user RLS, feed/archive/profile views, likes, and signed URLs for private media. Configure `VITE_SUPABASE_URL` and `VITE_SUPABASE_ANON_KEY` for the frontend. Never expose the service-role key in the browser.
