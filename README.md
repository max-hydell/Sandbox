# Instagram Feed Sandbox

An independent web app for organizing posts from public Instagram profiles. This repository and its Supabase project are isolated from other projects.

## Current implementation

- Supabase email magic-link authentication
- Per-user RLS-protected watchlist, post, and run data
- Add/remove one or many profile usernames
- Feed, archive grid, local likes, and settings screens
- Private media bucket support using expiring signed URLs
- Responsive dark UI

## Run locally

1. Copy `.env.example` to `.env.local`.
2. Set `VITE_SUPABASE_URL` and `VITE_SUPABASE_ANON_KEY` to the values from the **Sandbox** Supabase project.
3. Install and run:

   ```sh
   npm install
   npm run dev
   ```

4. For a production build: `npm run build`.

Never put a Supabase service-role key or database password in frontend environment variables.

## Supabase

The initial schema and RLS policies are already deployed to project `ocjepneqzdoharttxgxk` in the Sandbox organization. The app expects the `accounts`, `posts`, `runs`, and `notification_log` tables and private `instagram-media` bucket.

Configure Supabase Auth's Site URL and redirect URLs for the local development URL and the eventual production domain. Enable email OTP/magic links.

## Important platform limitation

Instagram does not provide an unrestricted public endpoint for continuously reading arbitrary profiles while logged out. This app does **not** log into Instagram, bypass private-account controls, evade rate limits, or use hidden/private APIs. Automatic discovery, reliable carousel/reel extraction, and scheduled checking are not implemented yet. A username in the watchlist is not proof that its posts have been fetched. Those features require a permitted data source or an explicitly supported import workflow.

The original feed's 55-account / 45-post dataset and media files have not been imported because the source export and original media blobs were not supplied to this repository. No historical data has been fabricated.
