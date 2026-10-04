# Character Studio — design spec

**Date:** 2026-10-04
**Owner:** Olivier Schwend
**Status:** Draft for owner review
**Repo:** `~/Claude/Projects/character-studio` (private GitHub `oschwend-prog/character-studio`)

---

## 1. Intent

Build a machine that runs AI-character channels on **TikTok and Instagram Reels**:

1. Design original AI characters with a signature look.
2. Detect what is going viral right now.
3. Put our character into those trends with **Higgsfield Genjutsu** (motion transfer) at **1080p, platform-ready quality**.
4. Post with one-click approval first, then fully automatically per channel once quality is proven.
5. Measure every post, learn which motions, hooks and posting times win, and get better every week.
6. Track all of it — channels, every clip generated, every clip posted, spend — in a **terminal** (web dashboard).

Goal: **go live fast** while AI-character content is hot, with high quality and low token cost.

### What the owner said vs what is assumed

| Owner decided | Assumed (correct me) |
|---|---|
| Concepts A (Animal), B (Nana), D (Artist), E (Deadpan Icon); start with **A = cream long-haired miniature dachshund mascot** and **E = The Butler** (deadpan funny dancer) | "Claude studio" = Claude Code + its scheduled routines |
| Trend check **every day** (plus a deeper weekly read) | |
| Platforms: TikTok + Instagram Reels (no YouTube) | Lean budget cap ≈ $210/mo for Slice 1 (owner can change in the terminal) |
| Posting: approve first, then auto per channel | Supabase: new `studio` schema inside the existing `faceless-youtube` project |
| Architecture: thin agent, thick code (approach 1) | Posting service: Upload-Post (Postiz as fallback) |
| Quality: high-definition, social-native | Characters are openly AI-generated (labelled), as Granny Spills is |
| Use the best available skills throughout | |

### Success criteria for Slice 1 (go-live)

1. Two characters (A, E) designed and approved by the owner.
2. The daily routine runs unattended **3 days in a row**, each run producing QA-passed 1080p clips in the queue, within the credit cap.
3. Approving a clip in the terminal posts it to TikTok + Reels within 15 minutes, with the AI-generated label set.
4. The terminal's spend figure matches the Higgsfield balance to within 1 credit.

### Non-goals (not in this project, or not yet)

- Characters B (Nana — talking clips) and D (Artist — music) → **Slice 3**.
- Comment / DM replies, brand deals, monetisation, YouTube.
- Creating social accounts (owner does this), scraping or downloading other creators' videos, famous IP or real people, meme coins.

---

## 2. Evidence behind the concepts (4 Oct 2026)

- **Animal loop dancers** are the strongest live format: rooster in shorts 4.8M views (30× creator median), guinea pig in curlers 3.7M (34×), yoga frog 1.2M (54×), cat dance 1.2M (375×). Formula: one signature outfit + one trending dance + perfect loop, 10–15 s, music only.
- **Jean Phil** (Sept 2026): instantly readable silhouette + one deadpan action at odds with the look + "real or AI?" debate → 145K Instagram followers in 3 days. (Partly a meme-coin pump — we copy the format, not that.)
- **Granny Spills**: 2.5M followers in 30 days. Openly AI, says ruthless things, signature pink outfit, *talks* — the reason Nana gets a talking lane in Slice 3.
- **Genjutsu itself is trending** (`#higgsfieldgenjutsu` clip: 1.2M views, 15×).
- **Risk signal:** an "exposing fake AI influencers" series (5.1M followers, 2.7–2.9M views per episode) targets AI accounts that lift human creators' videos. → We never post anyone else's footage, and we always label AI.

---

## 3. Architecture

```
            ┌──────── daily Claude scheduled task (Sonnet, ~08:00 UK) ────────────────┐
 vidIQ ──────┤ 1 plan    → studio CLI: who needs a clip today, credits left             │
 TikTok      │ 2 trends  → 1 vidIQ scan + TikTok trending sounds + Genjutsu Trending    │
 music chart │ 3 pick    → best motion clip per character (playbook, explore/exploit)   │
 Genjutsu    │ 4 make    → Genjutsu motion transfer, 1080p 10-15s (budget-reserved)     │
 library ────┤ 5 check   → technical QA (ffprobe) + visual QA (6 frames)                │
             │ 6 master  → 1080x1920/30fps/H.264 ~15 Mbps, -14 LUFS, hook text burned   │
             │ 7 caption → hook + caption + hashtags in the character's voice           │
             └─ 8 queue  → studio CLI: awaiting_approval (or scheduled if auto is on) ──┘
                                        │
   Terminal (Vercel) ── owner: Approve / Schedule / Edit / Reject / Regenerate
                                        ▼
   GitHub Actions (no tokens):  publish every 15 min → Upload-Post → TikTok + Reels
                                stats every 6 h → views, likes, comments, shares, follows
                                health hourly → email if the daily routine missed 26 h
                                        │
   Weekly review (Opus, Monday): stats → per-character playbook.md, kill/promote bars,
                                 report in terminal + email
```

### Why this is token-lean

- Claude only performs steps that need an MCP or judgement (trend pick, generation, visual QA, captions).
- Every DB read/write is one `studio` CLI command; Claude never writes SQL or reasons about state.
- The daily run is a fixed, short checklist skill on **Sonnet**; **Opus** runs once a week.
- Publishing, stats, health checks and budget reporting are plain code on GitHub Actions.
- One vidIQ scan per day maximum (5 vidIQ credits; the plan has 150/month).

---

## 4. Components

### 4.1 Repository layout

```
character-studio/
  CLAUDE.md                     # short project brief + hard rules (kept small: loaded every run)
  characters/<slug>/
    bible.md                    # look, personality, signature, voice, never-do list
    refs.json                   # Higgsfield element / reference image IDs (identity lock)
    playbook.md                 # learned rules, rewritten weekly by the review
  studio/                       # Python package + CLI (`studio …`)
    cli.py  db.py  budget.py  clips.py  motion.py
    qa.py                       # ffprobe technical checks + frame extraction
    master.py                   # ffmpeg mastering + hook-text burn-in
    publish.py  metrics.py  review_data.py
  .claude/skills/
    daily-run/SKILL.md          # the daily checklist (the routine prompt just invokes it)
    weekly-review/SKILL.md
    design-character/SKILL.md
  terminal/                     # Vite + React dashboard (Vercel)
  supabase/migrations/          # schema `studio`
  .github/workflows/            # ci, publish, metrics, health
  tests/
  docs/superpowers/{specs,plans}/
```

### 4.2 Characters (Slice 1: A and E)

- **A — the Mascot: a cream long-haired miniature dachshund.** Stands upright (human dance motion only transfers cleanly onto an upright body — every winning animal in the scan was upright and dressed) with **one signature accessory** that never changes. The long body on short legs is the built-in joke; the cream long coat flows on every move. Audience: broad, cute, highly shareable, strongest on Instagram. Competition: AI dachshund dance clips are already a TikTok template — we win by being a named, recurring character with a locked identity, not one-off template clips. Also suits pet trends in the Genjutsu library (e.g. "Pet Zoom Montage").
- **E — The Butler (deadpan funny dancer), "the Quiff" (owner pick 2026-10-04 over the 70s version).** Round, mid-40s English butler with a towering rigid black pompadour (running gag: the quiff never moves), tiny round glasses, thin curled pencil moustache, tails and white gloves; nails every trend perfectly and never breaks character — stately homes, London streets, carrying a silver tray. Comedy by contrast (the Jean Phil / Granny Spills mechanic), deliberately unlike Jean Phil (no houndstooth, no bob, no moustache). White gloves and coat-tails make motion read clearly. Never speaks in Slice 1. Audience: Gen Z comedy, strongest on TikTok. Can later "release his own tracks" and become the Artist (concept D) without a new account.
- The two characters reach different audiences, so the head-to-head is informative.
- Design flow (`design-character` skill): bible draft → Higgsfield **character-sheet** workflow, 4K reference renders (Nano Banana Pro) → owner picks 1 of 3–4 looks per character → saved as a Higgsfield reference element (identity lock) → `refs.json`.
- Final names, the dachshund's signature accessory, and exact looks are decided in that step.

### 4.2a Studio DNA — ODD EYES (owner decision 2026-10-04)

The studio is called **ODD EYES**. Every character, on every channel, shares one signature:
- **Heterochromia, always the same sides:** the character's RIGHT eye (viewer's left) is vivid ice-blue, the LEFT eye (viewer's right) is warm amber. Natural-looking, vivid, never glowing (no uncanny/creepy look).
- **End beat on every clip:** the last ~0.5 s is a look straight down the lens with a catch-light glint in the two-tone eyes, plus a short sound sting (the same across all channels — cross-channel recognition).
- **Mark:** two dots, ice-blue and amber, as a small corner bug and as the future studio avatar.
- **Lore:** characters share one world and cross over (Biscuit is the house dog where the Butler works). Running line for future characters: everyone with the eyes "isn't quite from here".
- Visual QA checks eye colours and sides on every clip; identity references always show both eyes clearly.

### 4.3 `studio` CLI (Python)

The only interface between Claude, Actions, the terminal backend and the database. Key commands:

| Command | Purpose |
|---|---|
| `studio plan today` | Characters due a clip, remaining budget, motions already used |
| `studio budget reserve <credits> --clip <id>` | Refuses if month spend + reservation would exceed the cap or if the kill switch is on |
| `studio budget settle <clip> <actual>` | Records the real cost from the Higgsfield job |
| `studio motion add/list` | Motion sources; **source must be `higgsfield_library` or `owner_inbox`** (enforced) |
| `studio clip add/update/status` | Clip state machine (below) |
| `studio qa tech <file>` | ffprobe checks; non-zero exit if below spec |
| `studio master <clip>` | ffmpeg master + hook-text burn-in, uploads to storage |
| `studio queue` | Moves a passed clip to `awaiting_approval` or `scheduled` (per channel mode) |
| `studio trends add` | Stores scan results (vidIQ outliers, trending sounds, gallery items) |

Clip state machine:

```
planned → generating → gen_failed (reservation released; retried once next run)
                     → generated → qa_failed (→ one re-roll → dropped)
                                 → qa_passed → mastered → awaiting_approval → approved → scheduled
                                                                            → rejected (reason stored)
scheduled → posting → posted | post_failed (retried 3x, then surfaced in terminal)
```

### 4.4 Daily routine (`daily-run` skill)

Runs as a **Claude scheduled task** (owner decision 2026-10-04: all automation lives in Claude's own scheduled tasks, so the terminal stays a thin display-and-approve layer). Tasks are created from the `character-studio` project folder so they appear under that project in the sidebar:

| Task | When | Model | Does |
|---|---|---|---|
| `studio-daily-run` | daily ~08:00 UK | Sonnet | the 8 steps below |
| `studio-weekly-review` | Monday ~09:00 UK | Opus | §4.8 review + `last30days` deep trend read + bar check |

Each task's prompt is one line that invokes the project skill (`/daily-run`, `/weekly-review`), so the instructions live in the repo, version-controlled. The project's `.claude/settings.json` ships **prefix-form allow rules** (`Bash(studio:*)`, `Bash(ffmpeg:*)`, `Bash(ffprobe:*)`, the Higgsfield and vidIQ MCP tools) so an unattended run never stalls on a permission prompt. Steps:

1. `studio plan today`; stop if nothing is due or the kill switch is on.
2. **Trends (every day), per character**: each character's `bible.md` holds its own scan profile — queries, hashtags and audience string. The dachshund scans **dog/pet trends** (dog dances, "dog vibing to the beat", pet POV skits, #dachshund #sausagedog #dogsoftiktok); The Butler scans human comedy and dance trends. One vidIQ outlier scan (rotating query per character niche; 5 vidIQ credits, the plan's 150/month covers one a day), TikTok trending sounds (`tiktok_music_trending`, free), Higgsfield Genjutsu *Trending* + *New* galleries (free). Store via `studio trends add`. Daily because dance trends peak and fade within 1–2 weeks — a week-2 clip loses to a week-1 clip. The deeper Reddit/X/web read (`last30days`) runs weekly inside the review.
3. **Pick** one motion per due clip. Every motion is tagged `body: biped | quadruped`; every character has one reference pose per body type it supports (dachshund: upright **and** four-legged; Butler: biped). A motion is only paired with a character pose of the same body type. The pick also matches the character's playbook and the day's trends; never repeats a motion for that character within 30 days. **Explore/exploit**: ~70% from proven playbook patterns, ~30% new motions/hooks, so learning never stalls.
4. **Generate**: `studio budget reserve` → `generate_video` with `hf_mult_motion_control`, character reference + driving video, 1080p → `jobs_wait` → `studio budget settle`.
5. **QA**: `studio qa tech` (resolution ≥ 1080×1920, 23–60 fps, duration 7–15 s, bitrate floor, audio present) → extract 6 frames → Claude checks identity vs reference, hands, face, flicker, melting, extra limbs. Fail → one re-roll; second fail → dropped and logged.
6. **Master** (`studio master`): 1080×1920, 30 fps, H.264 High ~15 Mbps, AAC 320k, loudness −14 LUFS (same chain as faceless-youtube `master.mjs`), hook text burned in with the character's font, inside TikTok/Reels safe zones.
7. **Caption**: hook line, caption and 3–5 hashtags in the character's voice (from `bible.md`); AI disclosure in caption and bio.
8. `studio queue`.

Hard limits per run: maximum clips = the day's plan; maximum one re-roll per clip; stop on any budget refusal.

### 4.4b Viral modes — Drop-in and Recreate (owner decision 2026-10-04: "hybrid but more drop-in")

| Mode | What | Genjutsu op | Default share |
|---|---|---|---|
| **Drop-in** | Our character swapped into the actual viral clip (original setting, camera, timing) | `hf_mult_replace_object` | TikTok ~70%, Instagram ~40% |
| **Recreate** | The viral clip's moves performed by our character in our own scene | `hf_mult_motion_control` | the rest |

Shares are per-account settings in the terminal. Drop-in guardrails (enforced by QA/CLI):
1. Our character replaces the **main subject**; the output may contain **no other identifiable real people** (else replace them too, or use Recreate).
2. **Clean source only:** no platform watermark, creator handle or UI overlay in the frame (TikTok-saved files carry a watermark → not usable for Drop-in; use for Recreate).
3. **Original audio always stripped**; our beat or a sound added in-app.
4. Caption **credits the trend source** ("trend: @creator") when known; takedown request → remove within 24 h.
5. **Instagram originality guard:** since 30 Apr 2026 Instagram stops recommending accounts that mostly repost others' content. The weekly review tracks non-follower reach per account; on a drop or an "unoriginal content" notice the account's Drop-in share is cut automatically to ≤ 20%.
6. Sources: Higgsfield Genjutsu Trending/New library clips (skip any with overlays) or clean clips supplied by the owner into `inbox/`. No scraping, no downloading from TikTok/Instagram.

**Source library (owner decision 2026-10-04):** every driving/source clip — Higgsfield library imports, owner inbox clips and our synthetic drivers — is stored in Supabase Storage (`sources` bucket) and catalogued in `studio.sources` with its checks (watermark, overlay, other people, number of bodies, body type), trend tag, credit handle and the **performance of every clip made from it** (median outlier_x). The daily run picks the best eligible source automatically; GitHub holds code and config only, never media.

**Viral Picks approval (owner decision 2026-10-04):** the daily scan does **not** generate straight away. Every viral candidate (vidIQ outliers, Higgsfield trending motions) lands in a **Viral Picks** list in the terminal with its URL, platform, views, outlier ×, matched character and the proposed version (mode, hook, prop). The owner approves or skips (optionally re-assigning the character). Production order per daily run: approved picks first (oldest first), then — only if none are approved — the concept plan in `docs/launch/channel-strategy.md`, so cadence never stalls. A deep breakdown (vidIQ `watch_shortform_content`, 10 credits) runs only after approval. The finished clip still goes through the normal approve-before-post queue.

**Pick scoring (owner decision 2026-10-04: "rate according to sub-scores, I'll approve later"):** every Viral Pick is stored with six sub-scores (0–10) and a total (0–100), and the terminal sorts by total.
- Computed by code: **virality** = log10(outlier ×)/3 × 10 (capped), **reach** = log10(views/100K)/log10(500) × 10 (capped).
- Judged by Claude in the daily run against a fixed rubric: **freshness** (10 = rising now, 6 = evergreen, 3 = past peak), **fit** with the character's premise, **feasibility** for our pipeline (10 = solo, full body, static camera; 6 = 2 bodies; 4 = 3+ bodies until the multi-body test passes; 3 = needs the talking lane), **saturation** (10 = fresh, 5 = template everywhere).
- **Brand safety** is a pass/fail gate (fails are never stored).
- Weights v1: virality 0.25 · reach 0.10 · freshness 0.15 · fit 0.20 · feasibility 0.20 · saturation 0.10.
- Calibration: once ≥ 20 approved picks have been produced and measured, the weekly review compares each sub-score with the clip's real outlier_x and may propose new weights — a proposal the owner approves, never an automatic change.

### 4.5 Audio

Posting through an API means the sound must be in the file. TikTok's trending sounds cannot be attached by API.

- **Default (fully automatic): original AI-generated music we own**, in the style of the owner's Spotify playlist (owner decision 2026-10-04). The synthetic driving video already carries its own AI beat (Seedance `generate_audio`); otherwise a dedicated AI track. Mixed at −14 LUFS. Never muted, never struck.
- **Owner's songs, legally (manual arm):** the clip goes to the owner's **TikTok drafts** / Instagram; the owner attaches the song from the platform's own licensed music library (~30 s each). The daily run suggests a song from the owner's playlist that fits the clip's tempo and vibe. The same arm covers trending sounds.
- **Never** extract audio from Spotify (DRM + Spotify terms) and never bake a commercial song into an uploaded file (muting / copyright strikes).
- **Accounts stay Creator, not Business:** TikTok and Instagram Business accounts only get a reduced commercial music library.
- The weekly review compares the arms; the data decides whether real songs justify the manual step.

### 4.6 Terminal (Vite + React on Vercel, Supabase magic-link auth, owner only)

Dark, dense style consistent with the owner's other terminals. Pages:

1. **Channels** — character × platform: followers, posts, 7-day views, median views/post, auto on/off, progress to the kill/promote bars.
2. **Queue** — video player, editable caption and hook, motion source, cost, QA notes; **Approve / Schedule / Edit / Reject (reason) / Regenerate**.
3. **Library** — every clip ever generated: status, cost, where posted, stats.
4. **Budget** — credits used vs cap, per character, projected month-end, **kill switch**, cap editor.
5. **Playbook & Runs** — current rules per character, weekly reports, daily-routine and Actions health.

### 4.7 Publishing (GitHub Action, every 15 min)

- Picks `scheduled` posts whose time has come → **Postiz** (`postiz upload` → `postiz posts:create`, TikTok `content_posting_method: DIRECT_POST`, honouring `postiz integrations:settings` rules) → TikTok + Instagram Reels (one clip, both platforms, no extra generation cost). Upload-Post API is the fallback adapter behind the same `Publisher` interface.
- AI-generated label set on TikTok (`is_aigc`); on Instagram via the API flag if available, otherwise "AI-generated character" in caption and bio.
- Idempotent: a post row is claimed before the API call and stores the platform post ID; a retry never double-posts (operator-approval-loop pattern: durable claim + receipt).
- Maximum 2 posts per account per day; default post times 12:00 and 19:00 UK, then learned per character.

### 4.8 Stats and learning

- **Stats Action (every 6 h)**: `postiz analytics:post` / `analytics:platform` → views, likes, comments, shares, saves, follower count per post/account → `metric_snapshots`.
- Each clip is tagged with features: motion preset, motion category, hook type, text overlay yes/no, audio arm, duration, post hour, platform.
- **Weekly review (Opus, Monday)**: per character, per feature, compares median views against the character's own baseline. A rule enters the playbook only if it shows up across **≥ 5 posts** (no single-viral-post overfitting). Rewrites `playbook.md`, commits it, posts a report to the terminal and by email.

### 4.9 Pre-registered bars (fixed before launch; never renegotiated after seeing data)

Judged per character after **20 posts or 4 weeks**, whichever comes first:

- **Promote** (raise cadence): median views/post ≥ 5,000 on either platform, **or** any post ≥ 100,000 views.
- **Kill / replace**: median views/post < 500 on both platforms **and** no post ≥ 10,000.
- Anything in between: continue to the next 20 posts, then judge again.

---

## 5. Data model (Supabase, schema `studio`, project `faceless-youtube`)

| Table | Key columns |
|---|---|
| `characters` | slug, name, concept, status (designing/live/paused/killed), refs |
| `accounts` | character, platform, handle, upload_post_profile, mode (approval/auto) |
| `motion_sources` | id, source (`higgsfield_library`/`owner_inbox` only — CHECK constraint), preset_id, video_url, category, first_seen |
| `trends` | date, source (vidiq/tiktok_music/genjutsu_gallery), payload, notes |
| `clips` | character, motion_source, state, higgsfield_job_id, credits_reserved, credits_actual, qa_report, master_path, hook, caption, features (jsonb), reject_reason |
| `posts` | clip, account, scheduled_for, claimed_at, platform_post_id, status, error |
| `metric_snapshots` | post, captured_at, views, likes, comments, shares, saves; account follower snapshots |
| `spend_ledger` | month, clip, credits, kind (reserve/settle/refund) |
| `settings` | monthly_cap_credits, kill_switch, posting windows |
| `runs` | kind (daily/weekly/publish/metrics), started, finished, status, summary |
| `reviews` | week, character, report_md, bar_status |

Video files: Supabase Storage bucket `clips` (private; signed URLs for the terminal and Upload-Post). Masters are deleted 30 days after posting except clips above the promote bar.

---

## 6. Quality (high-definition, social-native)

- **References:** 4K character sheets; identity locked via a saved Higgsfield reference element.
- **Generation:** Genjutsu at **1080p**, 9:16, 10–15 s.
- **Master spec:** 1080×1920, 30 fps, H.264 High profile, ~15 Mbps, AAC 320 kbps, −14 LUFS integrated, hook text inside safe zones (clear of the top ~15% and bottom ~25% UI areas).
- **Two-stage QA gate** (technical + visual) before anything reaches the queue.
- **Visual QA calibration:** a small golden set of known-good and known-bad clips (eval-harness pattern) checks that the visual QA rejects what the owner would reject; re-run when the QA prompt changes.
- Owner sees every clip during approval mode; rejection reasons feed back into QA and the playbook.

---

## 7. Safeguards (enforced in code)

1. **Hard credit cap** — `studio budget reserve` refuses over-cap spend; kill switch stops generation and posting.
2. **Source whitelist** — DB CHECK constraint + CLI validation: Higgsfield library, owner inbox, or our own synthetic drivers. No downloading/scraping of other creators' videos. Drop-in guardrails per §4.4b.
3. **AI label always on**; AI disclosure in every bio.
4. **No real people, no famous IP** in character design or prompts (never-do list in each bible).
5. **Posting limits** — ≤ 2 posts/account/day; publish job is idempotent.
6. **Health alerts** — email if the daily routine misses 26 h, if publishing fails 3× or if spend passes 80% of the cap.
7. **Secrets** — Upload-Post key and Supabase service key only in GitHub Actions secrets / Vercel env; never in the repo.

---

## 8. Error handling

| Failure | Behaviour |
|---|---|
| Higgsfield job fails / times out | Release the reservation, mark clip `gen_failed`, one retry next run |
| QA fails twice | Clip dropped, reason logged, motion marked "weak for this character" |
| Budget refusal | Routine stops cleanly, run marked `budget_stop`, terminal shows it |
| Upload-Post error | 3 retries with backoff, then `post_failed` surfaced in the terminal; never re-post a claimed post without a receipt check |
| Routine doesn't run | Health Action emails after 26 h; queue simply stays empty — nothing posts unapproved |
| Stats API gap | Snapshot skipped; review uses the latest available snapshot and flags staleness |

---

## 9. Skill map (best available skill per stage)

| Stage | Skills / tools |
|---|---|
| Build process | `superpowers:writing-plans` → `superpowers:subagent-driven-development` + `superpowers:test-driven-development`, `superpowers:verification-before-completion` |
| Character design | Higgsfield `character-sheet` workflow, `nano-banana-pro` (4K refs), Higgsfield reference elements; `ecc:brand-voice` for each character's caption voice |
| Trend research | vidIQ outlier search, Higgsfield Genjutsu Trending/New galleries, `tiktok_music_trending`; `last30days` for the weekly Reddit/X/web trend read |
| Hooks & captions | `viral-hook-creator`, `ecc:content-engine` |
| Generation | Higgsfield `/genjutsu` → `generate_video` with `hf_mult_motion_control` |
| Mastering & text | ffmpeg; `hyperframes:embedded-captions` / `hyperframes` for hook-text overlays; `ecc:video-editing` |
| QA & loop control | `ecc:continuous-agent-loop` (quality gates, recovery), `ecc:eval-harness` (golden-set calibration) |
| Approval & publish | `ecc:operator-approval-loop` pattern (durable claims, receipts); Upload-Post API; `postiz` skill as fallback |
| Routine authoring | `writing-for-agents` (lean, unambiguous routine skills), `anthropic-skills:skill-creator`, `schedule` (cloud routines) |
| Terminal | `impeccable` (design), `dataviz` (charts), `ui-ux-pro-max` |
| Weekly review | `data:statistical-analysis` for honest reads against the pre-registered bars |

Optional in Slice 2: Higgsfield **Virality Predictor** scores each clip before posting; the review checks whether its score actually predicts real views before it is allowed to influence picks.

---

## 10. Delivery slices

**Slice 1 — go live (A + E)**
- Claude builds: repo, schema + migrations, `studio` CLI with tests, `design-character` and `daily-run` skills, QA + mastering pipeline, terminal (Channels, Queue, Library, Budget), publish Action via Upload-Post, health Action, cloud routine.
- Owner does (~30 min): top up Higgsfield credits; create 2 Instagram accounts; switch all 4 accounts to Creator/Business; connect them to an Upload-Post paid plan; pick the two characters' looks.

**Slice 2 — learn and automate**
- Stats Action, weekly Opus review + playbooks, auto-post switch per channel, owner motion inbox, audio-arm experiment read, optional Virality Predictor.

**Slice 3 — new lanes**
- B (Nana): talking clips (voice + lip-sync) alongside trend clips.
- D (Artist): music generation + performance clips — preferably as The Butler releasing his own tracks (reuses his audience) rather than a new account.
- Season-two series format for whichever character wins.

---

## 11. Budget (Slice 1)

| Item | Monthly |
|---|---|
| Higgsfield: 2 characters × 3 posts/week ≈ 26 clips × ~144 credits incl. re-rolls ≈ 3,700 credits | ≈ $185 |
| Postiz Cloud (Standard) | ≈ $29 |
| vidIQ (existing plan, ≤ 30 scans) | $0 extra |
| Vercel / Supabase / GitHub Actions (existing accounts) | $0 extra |
| **Total** | **≈ $210** |

Moving both characters to daily posting ≈ $420/month — only after a promote bar is hit.

---

## 12. Risks to verify first (Slice 1, task 0 — before building on them)

1. **Scheduled tasks + connectors:** does a Claude scheduled task reach the Higgsfield and vidIQ connectors and run end-to-end with no prompt? Does it fire reliably (Mac awake / keep-awake setting)? Fallback: a Claude Code cloud routine on the same skill files.
2. **Genjutsu reality check:** real 1080p credit cost, quality on our two characters, and how well human motion transfers to the anthropomorphic animal.
3. **Upload-Post:** TikTok direct post, TikTok upload-to-drafts (needed for the audio experiment, §4.5), AI-label support on both platforms, analytics endpoint, media-by-URL.
4. **Higgsfield output URL lifetime** (decides how soon we must copy masters to storage).
5. **ffmpeg in the cloud routine environment** (install in the routine's setup if missing).

Each check gets a pass/fail recorded in `docs/` before the dependent tasks start.
