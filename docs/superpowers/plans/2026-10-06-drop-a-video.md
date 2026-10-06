# Drop a video: owner-dropped clips animated into our characters (plan, 2026-10-06)

Owner (2026-10-05/06): "keep the terminal simpler. I will drop in videos and it will animate for our characters", "it
should happen even when the Mac is closed", and "always check with me if we generate new videos". Genjutsu is used the
way Higgsfield designed it: **Object swap** (the clip's setting, camera, timing and sound stay; the star is replaced),
like for like (Reginald replaces a human star, Biscuit a dog or small-animal star).

## The owner's flow (one box, one button)
1. In the terminal's **In the works** tab, a **Drop a video** box at the top: choose Biscuit or Reginald, pick one or more
   videos from the phone (or paste a link in the small field under it).
2. A card appears per video and moves by itself: Uploading → Checking → **Ready: about N credits** (a preview strip, who
   gets replaced, the section, the hook) with **Make it** and a small **Adjust** (who is replaced, his part, gadgets,
   hook, section start/length, crop).
3. **Make it** = the owner's approval for that one video (no credits are ever spent before it). The card then follows
   the existing 8 tracker steps (Generating → Quality check → Video built → Your OK → Scheduled → Posted).

## Architecture (cloud first, no Mac needed)
- **Upload**: the PWA uploads straight to Supabase Storage (`sources/owner/...`, policies exist since 0008) and files the
  drop as an owner pick (`attach_clip` / `add_owner_link` RPCs exist; a drop carries `proposal.drop = {state, ...}`).
- **Trigger**: a `studio.request_job(pick_id, kind)` RPC (kind `process` or `make`) records the request and fires a
  GitHub `repository_dispatch` through `pg_net` (token in Supabase Vault, `github_dispatch_token`); no Edge Function.
  A `studio-drop` GitHub Actions workflow also runs every 2 h as a safety net for anything left pending.
- **Process job** (free): download a pasted link with yt-dlp (cloud; a blocked link stays `waiting` and the daily run on
  the Mac retries it), probe, `source analyze` (cuts, beat, best window widened to 12-15 s inside one shot), a Gemini
  video **deconstruct** (JSON: people, the star and where, minors, watermark/handle, burned-in text, setting, what
  happens, suggested part, gadgets from the traits card, 3 hook lines in the bible voice, a playbook caption, the
  star's horizontal centre for a crop), the like-for-like check, the price (`plan estimate` for the window), then
  `drop.state = ready` (or `blocked` with the one-line reason: watermark → "paste the link instead", child, wrong star).
- **Make job** (paid, only after Make it): reserve credits (`budget reserve`, cap + kill switch respected), trim/crop the
  window, signed URL, **Higgsfield API** `POST https://api.higgsfield.ai/higgsfield/genjutsu/object-swap/v1.0`
  (`video_url`, `image_urls` = the character's master + sheet (+ close-up) public URLs from refs.json, a SHORT prompt
  "replace the <star> with the <butler|dog> from the reference images" + his part and gadgets, `resolution: 1080p`),
  poll `status_url` (≤ 25 min), download, settle the actual credits, `qa tech`, a Gemini frame QA (leftover person,
  watermark, eyes), master build (`closeup: null`, music `original`, hook on screen), upload, caption + first comment +
  hashtags from the deconstruct (playbook rules), `awaiting_approval`. One automatic re-roll on a QA fail, then stop.
- Everything still goes through `bin/studio` (CLI subcommands `drop process <pick>`, `drop make <pick>`); secrets only
  from env (GitHub secrets: `HF_API_KEY_ID`, `HF_API_KEY_SECRET`, `GEMINI_API_KEY`, plus the existing DB/Storage ones).

## Owner steps (keys only the owner can create)
1. Higgsfield API key at console.higgsfield.ai → GitHub secrets `HF_API_KEY_ID`, `HF_API_KEY_SECRET` (check how the API
   is billed: plan credits or separate API credits).
2. Gemini API key → GitHub secret `GEMINI_API_KEY`.
3. A fine-grained GitHub token for this repo only (Contents: read and write; corrected 2026-10-06: repository_dispatch needs Contents) → Supabase Vault secret `github_dispatch_token`.
Until they exist, drops wait at Checking / Make it and the next Claude run does the steps by hand.
