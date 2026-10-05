# Go-live checklist (owner, in order)

Run `bin/studio golive check` after any step: it prints a line per prerequisite (✅ done, ❌ with a one-line fix,
➖ not applicable here) and exits 0 only when nothing is ❌. Steps 1, 2, 8, 12 have no check line (they happen
outside the repo). Secrets only ever go into the Keychain or GitHub secrets: never into a file, a chat or a command line.

## 1. Top up Higgsfield credits
- [ ] Higgsfield > Plans & credits: buy about 1,800 credits (weeks 1-2 plus tests; the monthly cap is 6,000).
- [ ] Tell Claude: it reads the balance with the Higgsfield `balance` tool.

## 2. Create the social accounts
- [ ] Create 4 accounts: TikTok and Instagram for Biscuit and for Reginald. All 4 must be **Creator**, not Business.
- [ ] Instagram: on **Reginald's** account only, Edit profile, turn on the **AI-generated profile** label (Meta, 31 Aug 2026: required for profiles featuring an AI person; owner decision 2026-10-05: Biscuit's account has none). Every caption carries the AI disclosure (enforced in code); TikTok's per-post AI label is set by the publisher.
- [ ] Bios, handles and display names: `docs/launch/social-pages.md`. Avatars: `assets/avatars/biscuit.png`, `assets/avatars/reginald.png`.
- [ ] 2-factor on everywhere. Note the 4 final handles for step 3.

## 3. Postiz Cloud
- [ ] Sign up at postiz.com (Standard plan), Add channel x4: TikTok and Instagram for each character (for Instagram use the standalone login if both are offered).
- [ ] Settings > Public API: copy the key. Store it now (paste when prompted, input is hidden):
  `security add-generic-password -s cs-postiz-api-key -a "$USER" -w`
- [ ] Install the CLI at the pinned version and list the channel ids:
  `npm i -g postiz@2.0.16` then `POSTIZ_API_KEY="$(security find-generic-password -s cs-postiz-api-key -w)" postiz integrations:list`
  VERIFY at go-live: 2.0.16 is what `npm view postiz version` reported on 2026-10-05; the publish and metrics workflows install exactly this version (the parsers were written against its output). Bump it in both workflows and `tests/test_workflows.py` together, only after re-checking step 10's `integrations:settings` and `analytics:post` comparisons.
- [ ] Put each channel's id in `characters/<slug>/refs.json` (`postiz_integration_id`) with its `handle` (null until the account exists).
- [ ] `bin/studio seed` loads them. It needs step 4's database item, so run it at the end of step 4.
- Turns ✅: `keychain: cs-postiz-api-key`, `postiz: CLI installed and authenticated`.

## 4. Keychain items
- [ ] One command each, paste the value when prompted (`bin/studio` reads them; nothing is written to a file):
  - `security add-generic-password -s cs-database-url -a "$USER" -w`: Supabase project hkcafvzjwkeibbmvskko > Connect > **session pooler** string.
  - `security add-generic-password -s cs-supabase-url -a "$USER" -w`: Settings > API > Project URL.
  - `security add-generic-password -s cs-supabase-service-key -a "$USER" -w`: Settings > API > service_role key.
  - (`cs-postiz-api-key` was stored in step 3.)
- [ ] Now run `bin/studio seed` (step 3's last action) and `bin/studio seed status`.
- Turns ✅: `keychain: cs-database-url`, `keychain: cs-supabase-url`, `keychain: cs-supabase-service-key`, `database: reachable`, `database: schema studio, migrations 0001-0007` (if ❌ its fix names the migration file to apply).

## 5. Supabase dashboard
- [ ] Project Settings > Data API (older UI: Settings > API) > **Exposed schemas**: add `studio`, Save.
- [ ] Authentication > URL Configuration > Redirect URLs: add the terminal URL (you get it in step 8, come back for this).
- [ ] Authentication > Emails > **Magic Link** template: make sure the body includes `{{ .Token }}` (the 6-digit code) next to the link. The installed iPhone app signs in with the code; a link opened from Mail lands in Safari, which cannot finish an app sign-in.
- [ ] After your first sign-in to the terminal (step 8: the link in a browser, or the code in the installed app): Authentication > Sign In / Providers, turn **off** "Allow new users to sign up". Caution: this project (hkcafvzjwkeibbmvskko) is the shared faceless-youtube Supabase project, so the switch is project-wide: nobody new can sign up to anything else that uses it either.
- Turns ✅: `data api: schema studio exposed`.

## 6. GitHub secrets and workflows
- [ ] Set the 4 secrets, piped from the Keychain so no value is typed or shown. Run them inside the repo checkout (`cd ~/Claude/Projects/character-studio`): `gh` takes the repo from its git remote.
  - `printf %s "$(security find-generic-password -s cs-database-url -w)" | gh secret set DATABASE_URL`
  - `printf %s "$(security find-generic-password -s cs-supabase-url -w)" | gh secret set SUPABASE_URL`
  - `printf %s "$(security find-generic-password -s cs-supabase-service-key -w)" | gh secret set SUPABASE_SERVICE_KEY`
  - `printf %s "$(security find-generic-password -s cs-postiz-api-key -w)" | gh secret set POSTIZ_API_KEY`
- [ ] Enable publishing and metrics: `for w in publish metrics; do gh workflow enable $w.yml; done`
- [ ] **Hold `health.yml` until step 11**: it fails, and GitHub emails you every 3 hours, until the first daily run is logged.
- Expected GitHub Actions use: about 1,500 minutes a month of the 2,000 free (private repo): `publish` 24 runs a day (every 15 min from 17:00 to 20:59 UTC, which covers the 19:00 / 19:30 London slots in BST and GMT, plus a 3-hourly catch-up), `metrics` 4, `health` 8, about 1 to 1.5 billed minutes each. A time you choose yourself in the terminal outside that window posts within about 3 hours.
- Schedules run from the repo's default branch (today `build/slice1`); if you merge to `main` and change the default, they follow.
- Turns ✅: `github: secret DATABASE_URL`, `... SUPABASE_URL`, `... SUPABASE_SERVICE_KEY`, `... POSTIZ_API_KEY`, `github: workflow publish enabled`, `github: workflow metrics enabled`, `repo: no secret files tracked`.

## 7. Approve the permission proposal
- [ ] Read it: `diff .claude/settings.json .claude/settings.json.proposed`. It is an explicit allowlist: it names each Higgsfield and vidIQ tool the two skills call (no whole-server allow, no `uv run`), allows renders and playbook edits and the humanizer and last30days skills, and keeps a deny list of every publish, upload, update and account-linking tool as a backstop.
- [ ] If happy: `cp .claude/settings.json.proposed .claude/settings.json`
- Turns ✅: `permissions: proposal applied (explicit allows, deny rules)`. The check also fails while `settings.json` allows a whole MCP server or `Bash(uv run:*)`.

## 8. Vercel (the terminal)
- ✅ Done 2026-10-05: Vercel project `viral`, root `terminal`, production branch `build/slice1`, env `VITE_SUPABASE_URL` + `VITE_SUPABASE_ANON_KEY`; live at **https://viral-alpha-sandy.vercel.app**; Supabase redirect URL `https://viral-alpha-sandy.vercel.app/**` added.
- [ ] Vercel > Add New > Project > import `oschwend-prog/character-studio`. Root Directory `terminal`. Production branch `build/slice1` (or `main` after the merge).
- [ ] Environment variables: `VITE_SUPABASE_URL` (the project URL) and `VITE_SUPABASE_ANON_KEY` (the anon / publishable key, Settings > API; it is safe in a browser). Deploy.
- [ ] Open the URL, log in by magic link (only `o.schwend@gmail.com` can see data), then finish step 5's two items.

## 9. Flip the characters to live
- [ ] In `characters/biscuit/refs.json` and `characters/reginald/refs.json` set `"status": "live"` (there is no separate CLI; seeding is how status changes), with the handles and Postiz ids from step 3.
- [ ] `bin/studio seed`, then `bin/studio seed status` (each character shows `live: true`). Commit and push the refs files (ids are not secrets).
- The daily run skips Reginald until his close-up exists (step 10).
- Turns ✅: `characters: at least one live`, `characters: refs.json valid`, `characters: biscuit ready`.

## 10. Rehearsal (Claude runs it with you present, about 260 credits)
- [ ] Genjutsu multi-body test with 3 dancers: decides the held picks D1, D3, B4, B5, B6.
- [ ] Quiff Butler dance on the slick driver; generate Reginald's close-up and set `closeup` in his refs.json, re-seed.
- [ ] Cute-Biscuit debut re-render. Make it the first clip, or "picks first" would produce D2 before the debut.
- [ ] `postiz integrations:settings <id>` for one TikTok and one Instagram channel: compare with `TIKTOK_SETTINGS` / `INSTAGRAM_SETTINGS` in `studio/publish/postiz.py` (unknown keys are silently dropped).
- [ ] `postiz analytics:post <id> -d 7` on a real post: compare with `POSTIZ_METRIC_LABELS` / `POSTIZ_SERIES_MODE` in `studio/metrics.py` (cumulative or per-day).
- [ ] vidIQ Instagram insights (connect the 2 Instagram accounts to vidIQ first): compare the keys with the `IG_*` constants and check the `platform_post_id` match.
- [ ] Integration tests: `DATABASE_URL_TEST="$(security find-generic-password -s cs-database-url -w)" uv run pytest tests/integration -v` (builds and drops its own `studio_test` schema; never touches `studio`).
- Turns ✅: `characters: reginald ready`.

## 11. Scheduled tasks (Claude creates them from this project folder)
- [ ] `studio-daily-run`: daily 08:00 Europe/London, Sonnet, prompt `/daily-run`. `studio-weekly-review`: Mondays 09:00, Opus, prompt `/weekly-review`. Claude records both ids in `CLAUDE.md`.
- [ ] Claude triggers one daily run and checks it finishes without stalling on a permission prompt, and that `bin/studio health` exits 0 (a `daily` row in `runs`).
- [ ] Now enable the watchdog: `gh workflow enable health.yml`
- Turns ✅: `github: workflow health enabled`. Everything green means `bin/studio golive check` ends with "Ready to go live."

## 12. First posts
- [ ] Approve the first queued clips in the terminal (Today or Queue). Until an account has 6 approved posts, every post needs your approval.
- [ ] The next `publish.yml` run (every 15 min from 17:00 to 20:59 UTC, else within 3 hours) posts them at the slot (Biscuit 19:00, Reginald 19:30 London).
- [ ] A post stuck in `needs_check` or `failed` (the terminal and `bin/studio health` show it): look at the platform, then `bin/studio publish resolve <post-id> --live --platform-post-id <id>` (it is live), `--retry` (it is not, send it again) or `--drop --reason-file F` (forget it).
- [ ] Open each post on TikTok and Instagram: AI label visible, 1080p, post URL stored (Queue / Library).
