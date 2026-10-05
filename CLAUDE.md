# ODD EYES Character Studio

Machine that turns trends into approved, posted 1080p AI-character clips (Biscuit, Reginald)
on TikTok + Instagram Reels, with a terminal to approve, track spend and see results.

## How it works
- Thin agent, thick code. The Python `studio` CLI owns ALL state (Supabase Postgres schema `studio` + Storage) and every deterministic step.
- **All state goes through `bin/studio`.** Never write to the DB or Storage any other way. Run it as `bin/studio <cmd>`.
- Agent/skills only do MCP + judgement work (Higgsfield, vidIQ, visual QA, captions) and call the CLI.
- Dev: `uv run pytest -q`. Python 3.12 (uv), typer, psycopg 3, pydantic 2, ffmpeg 8 (no drawtext: overlays are PIL PNGs).

## Global Constraints
- Repo `~/Claude/Projects/character-studio`, private GitHub `oschwend-prog/character-studio`. Commit email = GitHub no-reply. Every commit ends with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Media never in git (`renders/`, `inbox/`, `*.mp4`, `*.png` outside `assets/`). Media lives in Supabase Storage.
- Secrets never in files. Local: Keychain items `cs-database-url`, `cs-supabase-url`, `cs-supabase-service-key`, `cs-postiz-api-key` (read by `bin/studio`). CI: GitHub secrets. Terminal: Vercel env `VITE_SUPABASE_*`.
- Master: 1080x1920, 30 fps, H.264 High, ~15 Mbps, AAC 320k 48 kHz, -14 LUFS +/-1, true peak <= -1 dBFS, 7-16 s (eye loops 6-8 s).
- ODD EYES: character's RIGHT eye (viewer's left) ice-blue, LEFT eye (viewer's right) amber; every master ends on the eye close-up glint + sting; two-dot bug top-right at (972,268) r=15, `#8FD3FF` / `#FFB040`.
- Viral modes: `dropin` and `recreate`. Drop-in needs a source with `has_watermark=false`, `has_overlay=false`, `other_people=0`, `kind != 'synthetic'`.
- Never: scrape/download from TikTok/Instagram; post third-party audio; post without the AI label; post more than 2x per account per day; spend past the monthly cap (default 6,000 Higgsfield credits).
- Slots (Europe/London, `zoneinfo`, never naive datetimes): Biscuit 19:00, Reginald 19:30; weeks 1-2 Tue/Wed/Thu, from week 3 Mon-Fri.
- KPI bars are binding and must not be renegotiated after seeing data (see plan header).

## Where things live
- Spec: `docs/superpowers/specs/2026-10-04-character-studio-design.md`; plan: `docs/superpowers/plans/2026-10-04-character-studio-slice1.md` (Global Constraints + Review Focus at the top).
- Character bibles: `characters/<name>/bible.md`. Strategy: `docs/launch/`, `docs/research/`, `docs/spike/`.
- Scan settings: `config/scan.json`. Avatars: `assets/avatars/`.
- Per character `characters/<slug>/refs.json` (Higgsfield masters, close-up, accounts, `status`): `bin/studio seed` upserts characters + accounts from it (go-live = `status: live` + handles + Postiz ids, then re-seed); `bin/studio seed picks <doc>` loads a Viral Picks batch.
- Go-live: owner's ordered checklist `docs/launch/go-live.md`; `bin/studio golive check` lists what is still ❌ with a one-line fix each (exit 0 only when ready).
- Automation: `.claude/skills/daily-run` and `.claude/skills/weekly-review` (run by the scheduled tasks), allow list in `.claude/settings.json`. Dry run of the daily sequence: `docs/spike/daily-run-dry-rehearsal.md`. **Pending owner step:** review `.claude/settings.json.proposed` (an explicit allowlist of the tools the two skills call, no whole-server allow; deny rules for every publish/upload/update/account-linking tool of the Higgsfield and vidIQ MCPs) and, if approved, `cp .claude/settings.json.proposed .claude/settings.json`.
