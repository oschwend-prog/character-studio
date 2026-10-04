# ODD EYES Character Studio — Slice 1 (go live) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the machine that turns trends into approved, posted 1080p character clips for Biscuit and Reginald on TikTok + Instagram Reels, with a terminal to approve, track spend and see results.

**Architecture:** Thin agent, thick code. A Python `studio` CLI owns all state (Supabase Postgres schema `studio` + Storage) and every deterministic step (budget, source library, clip state machine, QA, mastering, publishing via Postiz, metrics). Two Claude scheduled tasks run short skills (`/daily-run` on Sonnet, `/weekly-review` on Opus) that do only MCP + judgement work (Higgsfield, vidIQ, visual QA, captions) and call the CLI. GitHub Actions run publishing, metrics and health without tokens. A Vite + React terminal on Vercel reads the same schema (RLS, owner only).

**Tech Stack:** Python 3.12 (uv), typer, psycopg 3, pydantic 2, Pillow, httpx, pytest · ffmpeg/ffprobe 8 (no drawtext — overlays are PIL PNGs) · Supabase (project `hkcafvzjwkeibbmvskko`, schema `studio`, buckets `sources`, `clips`) · Postiz CLI (`npm i -g postiz`) · Vite + React 18 + TypeScript + @supabase/supabase-js, Vitest · GitHub Actions · Vercel · Claude scheduled tasks.

**Spec:** `docs/superpowers/specs/2026-10-04-character-studio-design.md` (read with `docs/launch/channel-strategy.md`, `docs/research/2026-10-04-niche-playbook.md`, `docs/spike/2026-10-04-test-1.md`, `characters/*/bible.md`).

## Global Constraints

- Repo: `~/Claude/Projects/character-studio`, private GitHub `oschwend-prog/character-studio`. Commit email = GitHub no-reply. Every commit ends with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Media never in git (`renders/`, `inbox/`, `*.mp4`, `*.png` outside `assets/` are ignored). Media lives in Supabase Storage.
- Secrets never in files: local = macOS Keychain items `cs-database-url`, `cs-supabase-url`, `cs-supabase-service-key`, `cs-postiz-api-key` (read by `bin/studio`); CI = GitHub secrets `DATABASE_URL`, `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `POSTIZ_API_KEY`; terminal = Vercel env `VITE_SUPABASE_URL`, `VITE_SUPABASE_ANON_KEY`.
- Master spec: 1080×1920, 30 fps, H.264 High, ~15 Mbps (maxrate 18M, bufsize 30M), AAC 320k 48 kHz, integrated loudness −14 LUFS ±1, true peak ≤ −1 dBFS, 7–16 s (eye loops 6–8 s).
- ODD EYES: character's RIGHT eye (viewer's left) ice-blue, LEFT eye (viewer's right) amber; every master ends on the eye close-up glint + sting; two-dot bug top-right at (972,268) r=15, colours `#8FD3FF` / `#FFB040`.
- Viral modes: `dropin` (`hf_mult_replace_object`) and `recreate` (`hf_mult_motion_control`). Account Drop-in targets: TikTok 0.70, Instagram 0.40. Drop-in requires a source with `has_watermark=false`, `has_overlay=false`, `other_people=0`, `kind != 'synthetic'`.
- Never: scrape/download from TikTok/Instagram; post third-party audio; post without the AI label; post more than 2 times per account per day; spend past the monthly cap.
- Slots (Europe/London): Biscuit 19:00, Reginald 19:30; weeks 1–2 Tue/Wed/Thu; from week 3 Mon–Fri.
- KPI bars (binding): format keep median outlier_x ≥ 1.5 over ≥ 5 posts, kill ≤ 0.7 over ≥ 8; hook proven ≥ 2 hits in 10; hit = outlier_x ≥ 3; character promote median ≥ 5,000 or any ≥ 100,000; kill median < 500 on both platforms and none ≥ 10,000 (after 20 posts or 4 weeks); IG guard: non-follower reach % down ≥ 40 % week-on-week → account `dropin_share` set to 0.20.
- Default monthly cap: 6,000 Higgsfield credits (owner-editable in the terminal).

## Review Focus

1. **A crash between Postiz success and the DB write** must never double-post: a post stuck in `posting` > 30 min becomes `needs_check`, never auto-retried (test in Task 10).
2. **Budget race:** two reservations in parallel must not exceed the cap — reservation checks and inserts in one transaction with the settings row locked (`FOR UPDATE`) (test in Task 3, integration).
3. **Missing or delayed metrics** (Instagram delays owner metrics; Postiz returns `{"missing": true}`): outlier_x must be `None`, not 0, and excluded from medians (test in Task 11).
4. **A Drop-in source that later turns out dirty** (watermark spotted in output QA): the source is flagged `has_watermark=true`, becomes ineligible, and the clip falls back to `qa_failed` — never posted (test in Task 4 + Task 13 rehearsal).
5. **Clock edges:** London DST (25 Oct) and slot times — scheduling uses `zoneinfo("Europe/London")`, never naive datetimes (test in Task 6).

---

## File structure

```
character-studio/
  pyproject.toml  uv.lock  bin/studio  .gitignore  CLAUDE.md  .claude/settings.json
  studio/
    __init__.py
    cli.py            # typer app; subcommands wire to modules below
    config.py         # Settings from env (pydantic), London tz helpers
    models.py         # dataclasses/enums shared by all modules
    store.py          # Store protocol + MemoryStore (tests)
    pgstore.py        # PostgresStore (psycopg) implementing Store
    budget.py         # reserve/settle/release, cap, kill switch
    sources.py        # source library: add, checks, eligibility, ranking
    clips.py          # clip state machine + feature tags
    planning.py       # plan_today, mode choice, slot times
    media/qa.py       # ffprobe tech QA + frame sheet
    media/overlays.py # PIL: hook text, bug, sparkle PNGs; sting wav
    media/master.py   # ffmpeg timeline → master mp4
    storage.py        # Supabase Storage upload/download/signed URL
    publish/base.py   # Publisher protocol + publish_due()
    publish/postiz.py # Postiz CLI adapter
    metrics.py        # snapshots ingest + outlier_x
    review.py         # weekly lift table + bars
  supabase/migrations/0001_studio.sql  0002_terminal_rpc.sql
  characters/{biscuit,reginald}/refs.json
  .claude/skills/{daily-run,weekly-review}/SKILL.md
  .github/workflows/{ci,publish,metrics,health}.yml
  terminal/  (Vite app: src/pages/{Channels,Queue,Library,Budget}.tsx, src/lib/{supabase,format}.ts)
  tests/  (pytest; tests/integration/ needs DATABASE_URL_TEST)
```

---

### Task 1: Repo bootstrap, CLI skeleton, CI

**Files:** Create `pyproject.toml`, `bin/studio`, `studio/__init__.py`, `studio/cli.py`, `studio/config.py`, `CLAUDE.md`, `.github/workflows/ci.yml`, `tests/test_cli.py`; Modify `.gitignore`.

**Interfaces:**
- Produces: console script `studio` (typer app `studio.cli:app`); `config.load() -> Settings` with fields `database_url: str | None`, `supabase_url: str | None`, `supabase_service_key: str | None`, `postiz_api_key: str | None`, `tz: ZoneInfo = Europe/London`; `config.now_london() -> datetime` (aware).

- [ ] **Step 1: Write the failing test** `tests/test_cli.py::test_version_and_help`

```python
from typer.testing import CliRunner
from studio.cli import app
def test_version_and_help():
    r = CliRunner().invoke(app, ["--help"])
    assert r.exit_code == 0 and "budget" in r.output and "clip" in r.output
    r = CliRunner().invoke(app, ["version"])
    assert r.exit_code == 0 and r.output.strip() == "0.1.0"
```
- [ ] **Step 2:** `uv run pytest tests/test_cli.py -v` → FAIL (module missing).
- [ ] **Step 3: Implement.** `uv init --package --python 3.12`; deps `typer psycopg[binary] pydantic httpx pillow`; dev deps `pytest`. `cli.py`: typer app with empty sub-apps `budget`, `source`, `clip`, `plan`, `qa`, `master`, `publish`, `metrics`, `review`, `db`, and a `version` command printing `0.1.0`. `bin/studio`: bash wrapper exporting `DATABASE_URL`, `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `POSTIZ_API_KEY` from Keychain (`security find-generic-password -s <item> -w`) when unset, then `exec uv run --project "$(dirname "$0")/.." studio "$@"`. `.gitignore` adds `inbox/`, `*.mp4`, `*.mov`, `*.wav`, `.venv/`, `terminal/node_modules/`, `terminal/dist/`. `CLAUDE.md` (≤ 40 lines): project purpose, the Global Constraints above, "all state via `bin/studio`", where the spec/bibles live. `ci.yml`: on push/PR → `astral-sh/setup-uv`, `sudo apt-get install -y ffmpeg`, `uv run pytest -q`.
- [ ] **Step 4:** `uv run pytest -v` → PASS.
- [ ] **Step 5: Create the GitHub repo and push.** `gh repo create oschwend-prog/character-studio --private --source . --push`; confirm CI green with `gh run watch`.
- [ ] **Step 6: Commit** `feat: studio CLI skeleton, CI`.

### Task 2: Data model, MemoryStore and the Postgres schema

**Files:** Create `studio/models.py`, `studio/store.py`, `studio/pgstore.py`, `supabase/migrations/0001_studio.sql`, `tests/test_store_memory.py`, `tests/integration/test_pgstore.py`.

**Interfaces:**
- Produces (`models.py`): enums `Platform{tiktok,instagram}`, `Mode{dropin,recreate}`, `SourceKind{higgsfield_library,owner_inbox,synthetic}`, `Body{biped,quadruped}`, `ClipState{planned,generating,gen_failed,generated,qa_failed,qa_passed,mastered,awaiting_approval,approved,rejected,scheduled,posted,dropped}`, `PostStatus{scheduled,posting,posted,failed,needs_check}`; dataclasses `Character(slug,name,status,bodies:list[Body])`, `Account(id,character_slug,platform,handle,postiz_integration_id,mode:'approval'|'auto',dropin_share:float)`, `Source(id,kind,url,storage_path,preset_id,body,bodies:int,duration_s:float,has_watermark:bool|None,has_overlay:bool|None,other_people:int|None,trend:str|None,credit_handle:str|None,created_at)`, `Clip(id,character_slug,source_id,mode,state,hf_job_id,credits_reserved,credits_actual,qa:dict,master_path,hook,caption,hashtags:list[str],features:dict,reject_reason,created_at)`, `Post(id,clip_id,account_id,scheduled_for,status,claimed_at,attempts,platform_post_id,url,error)`, `Snapshot(post_id,captured_at,views,likes,comments,shares,saves,watch_time_s,follows,non_follower_pct)`, `Settings(monthly_cap_credits:int,kill_switch:bool)`, `Favorite(id,url,character_slug,note,status,breakdown_md,source_id,clip_id,created_at)`, `LedgerEntry(id,clip_id,month:str,kind:'reserve'|'settle'|'release',credits:int,created_at)`.
- Produces (`store.py`): `class Store(Protocol)` with `get_settings()`, `set_settings(**kw)`, `ledger_add(e)`, `ledger_month(month) -> list[LedgerEntry]`, `add_source(s)->Source`, `update_source(id,**kw)`, `list_sources(**filters)->list[Source]`, `add_clip(c)->Clip`, `get_clip(id)`, `update_clip(id,**kw)`, `list_clips(**filters)`, `add_post(p)`, `claim_due_posts(now)->list[Post]`, `update_post(id,**kw)`, `list_posts(**filters)`, `add_snapshot(s)`, `snapshots_for(post_id)`, `accounts(character_slug=None)`, `characters()`, `transaction()` (context manager; MemoryStore no-op). `MemoryStore` implements it with dicts and `uuid4` ids.
- Produces (`pgstore.py`): `PostgresStore(dsn)` implementing `Store` against schema `studio`; `claim_due_posts` = single `UPDATE … SET status='posting', claimed_at=now() WHERE status='scheduled' AND scheduled_for<=now RETURNING *`.

- [ ] **Step 1: Failing tests** `tests/test_store_memory.py`: `test_add_and_get_clip_roundtrip`, `test_claim_due_posts_only_takes_due_scheduled_once` (two posts, one due: first claim returns 1, second claim returns 0, status `posting`).
- [ ] **Step 2:** run → FAIL.
- [ ] **Step 3: Implement** models + MemoryStore; write `0001_studio.sql`: `create schema studio`; tables `settings` (single row id=1, `monthly_cap_credits int default 6000`, `kill_switch bool default false`, `cadence jsonb`), `characters`, `accounts`, `sources` (CHECK `kind in (...)`), `clips` (CHECK `state in (...)`, `mode in (...)`), `posts` (unique `(clip_id, account_id)`), `snapshots`, `ledger`, `runs(kind,started_at,finished_at,status,summary)`, `reviews(week,character_slug,report_md,bar_status)`, `favorites(id,url,platform,creator_handle,views,outlier_x,origin,character_slug,proposal jsonb,scores jsonb,total_score numeric,note,status,breakdown_md,source_id,clip_id,created_at)` — the **Viral Picks** table (CHECK `origin in ('scan','owner')`, `status in ('new','approved','skipped','analysed','queued','made')`; scan results arrive as `new`, only `approved` ones are produced); indexes on `posts(status,scheduled_for)`, `clips(state)`; RLS enabled on all tables with policy `owner_all` = `auth.jwt()->>'email' = 'o.schwend@gmail.com'`; grants to `authenticated`; seed settings row and cadence `{"biscuit":{"days":["tue","wed","thu"],"slot":"19:00"},"reginald":{"days":["tue","wed","thu"],"slot":"19:30"}}`. Implement `PostgresStore`.
- [ ] **Step 4:** `uv run pytest tests/test_store_memory.py -v` → PASS.
- [ ] **Step 5: Apply the migration** to project `hkcafvzjwkeibbmvskko` with the Supabase MCP `apply_migration` (name `studio_0001`); then `list_tables(schemas=["studio"])` shows 10 tables. Create Storage buckets `sources` and `clips` (private). Expose schema `studio` to the Data API: Management API `PATCH https://api.supabase.com/v1/projects/hkcafvzjwkeibbmvskko/postgrest` with `db_schema` = existing value + `,studio` (token from Keychain `supabase-access-token`); if unavailable, add an owner step to tick `studio` under Settings → API → Exposed schemas.
- [ ] **Step 6: Integration test** `tests/integration/test_pgstore.py::test_claim_is_atomic` (skipped unless `DATABASE_URL_TEST`): uses schema `studio_test` (same DDL); two threads call `claim_due_posts` on one due post → exactly one gets it. Run locally with the test DSN → PASS.
- [ ] **Step 7: Commit** `feat: studio schema, Store protocol, memory + postgres stores`.

### Task 3: Budget ledger, cap and kill switch

**Files:** Create `studio/budget.py`, `tests/test_budget.py`; Modify `studio/cli.py`.

**Interfaces:**
- Consumes: `Store`, `LedgerEntry`, `Settings`.
- Produces: `class BudgetRefused(Exception)` with `.reason: Literal['kill_switch','over_cap']`; `month_key(dt) -> 'YYYY-MM'`; `committed(store, month) -> int` (settled + open reservations); `reserve(store, clip_id, credits, now) -> LedgerEntry`; `settle(store, clip_id, actual, now)`; `release(store, clip_id, now)`; CLI `studio budget status|reserve|settle|release` printing JSON.

- [ ] **Step 1: Failing tests:** `test_reserve_under_cap_ok` (cap 300, reserve 110 → ok, committed 110) · `test_reserve_over_cap_refused` (cap 200, two reserves 110 → second raises `over_cap`, nothing written) · `test_kill_switch_refuses` · `test_settle_replaces_reservation` (reserve 110, settle 99 → committed 99) · `test_release_frees_reservation` (reserve 110, release → committed 0) · `test_month_boundary` (reservation dated 31 Oct 23:30 London counts for `2026-10`).
- [ ] **Step 2:** FAIL. **Step 3:** implement; `reserve` runs inside `store.transaction()` and re-reads settings (`PostgresStore` locks the settings row `FOR UPDATE`). **Step 4:** PASS.
- [ ] **Step 5: Integration** `tests/integration/test_budget_race.py::test_parallel_reserves_respect_cap` (cap 150, two threads reserve 110 → exactly one succeeds). PASS.
- [ ] **Step 6: Commit** `feat: budget ledger with cap and kill switch`.

### Task 4: Source library with Drop-in guardrails and ranking

**Files:** Create `studio/sources.py`, `tests/test_sources.py`; Modify `studio/cli.py`.

**Interfaces:**
- Produces: `dropin_eligible(s: Source) -> bool` (kind ≠ synthetic and `has_watermark is False` and `has_overlay is False` and `other_people == 0`); `add_source(store, kind, url, body, bodies, duration_s, preset_id=None, trend=None, credit_handle=None) -> Source` (rejects `kind` not in enum; rejects TikTok/Instagram page URLs — host in `{tiktok.com, instagram.com, vm.tiktok.com}` → `ValueError("platform page URLs are not sources")`); `record_checks(store, id, has_watermark, has_overlay, other_people)`; `flag_dirty(store, id, reason)` (sets `has_watermark=True`); `rank_sources(store, character: Character, mode: Mode, exclude_ids: set[str]) -> list[Source]` — eligible for the mode and the character's bodies, ordered by (median outlier_x of clips made from it, desc, None last), then `created_at` desc; `ingest_inbox(store, storage, inbox_dir) -> list[Source]` (uploads files in `inbox/` to bucket `sources`, records `owner_inbox`, moves files to `inbox/done/`). CLI `studio source add|check|flag|list|ingest-inbox`.
- **Favourites lane (owner request 2026-10-04: "copy my favourite videos"):** `add_favorite(store, url, character_slug, note=None) -> Favorite` — accepts full TikTok `/@user/video/<id>`, Instagram `/reel/<code>` or YouTube Shorts URLs (rejects `vm.tiktok.com` / `tiktok.com/t/` short links with a message asking for the full URL); `add_pick(store, url, platform, creator_handle, views, outlier_x, character_slug, proposal, origin='scan') -> Favorite` (dedupes on url); `score_pick(outlier_x, views, freshness, fit, feasibility, saturation) -> dict` returning the six sub-scores + `total` with the spec's v1 weights and formulas (virality/reach computed, the other four passed in 0–10); `add_pick` stores `scores` + `total_score`; `list_picks(store, status='new')` orders by `total_score` desc; `auto_decision(pick) -> Literal['approve','analyst','hold','skip']` (approve: total ≥ 80 and feasibility ≥ 7; hold: proposal.needs in {'multi_body','talking_lane'}; skip: total < 65; else analyst) and `decide(store, id, decision, reason, by: Literal['owner','analyst','rule'])`; `next_favorites(store, limit) -> list[Favorite]` (oldest **`approved`**/`analysed` first — `new` picks are never produced without approval); `mark_favorite(store, id, status, **fields)`. Favourites are **not** sources (we never download them): they carry a breakdown used to brief a synthetic driver (Recreate); a Drop-in happens only if the owner drops a clean file in `inbox/` (linked via `source_id`). CLI `studio fav add|list|mark`. Tests: `test_fav_accepts_full_urls_rejects_short_links`, `test_next_favorites_only_approved_oldest_first`, `test_pick_dedupes_on_url`, `test_score_pick_matches_batch1` (B1: outlier 1392.8, views 43.4M, 8/10/9/7 → total 92; O4: 3.8, 1.1M, 6/8/3/8 → 48), `test_list_picks_sorted_by_total`, `test_auto_decision_thresholds` (B1 → approve, D4 total 79 → analyst, D1 needs multi_body → hold, O4 total 48 → skip).

- [ ] **Step 1: Failing tests:** `test_unchecked_source_not_dropin_eligible` · `test_clean_library_source_dropin_eligible` · `test_synthetic_never_dropin_eligible` · `test_platform_page_url_rejected` (`https://www.tiktok.com/@x/video/1`) · `test_flag_dirty_makes_ineligible` · `test_rank_prefers_better_performing_source` (two eligible sources, clips from A median outlier_x 2.0, B 0.8 → A first) · `test_rank_filters_body_type` (quadruped source excluded for Reginald).
- [ ] **Step 2:** FAIL. **Step 3:** implement (`rank_sources` reads clip outlier_x via `store.list_clips(source_id=…)` → `features['outlier_x']`). **Step 4:** PASS. **Step 5: Commit** `feat: source library with drop-in guardrails`.

### Task 5: Clip state machine and feature tags

**Files:** Create `studio/clips.py`, `tests/test_clips.py`; Modify `studio/cli.py`.

**Interfaces:**
- Produces: `ALLOWED: dict[ClipState, set[ClipState]]` = planned→{generating,dropped}; generating→{generated,gen_failed}; gen_failed→{generating,dropped}; generated→{qa_passed,qa_failed}; qa_failed→{generating,dropped}; qa_passed→{mastered}; mastered→{awaiting_approval,scheduled}; awaiting_approval→{approved,rejected}; approved→{scheduled}; scheduled→{posted}; `class IllegalTransition(Exception)`; `transition(store, clip_id, to: ClipState, **fields) -> Clip`; `new_clip(store, character_slug, source_id, mode, features) -> Clip`; `REQUIRED_FEATURES` = `{"format_id","hook_pattern","hook_text","prop","setting","motion_type","audio_arm","bodies_in_frame","seamless_loop","eye_closeup_end","trend_name"}` — `new_clip` raises `ValueError` listing missing keys. CLI `studio clip new|set|show|list`.

- [ ] **Step 1: Failing tests:** `test_happy_path_to_awaiting_approval` · `test_illegal_jump_rejected` (planned→posted raises) · `test_reroll_from_qa_failed_allowed_once` (second `qa_failed→generating` raises `IllegalTransition("max one re-roll")`, tracked via `features['rerolls']`) · `test_missing_features_rejected`.
- [ ] **Step 2–4:** FAIL → implement → PASS. **Step 5: Commit** `feat: clip state machine with feature tags`.

### Task 6: Daily plan, mode choice and slots

**Files:** Create `studio/planning.py`, `tests/test_planning.py`; Modify `studio/cli.py`.

**Interfaces:**
- Consumes: `Store`, `budget.committed`, `sources.rank_sources`.
- Produces: `@dataclass DueClip(character_slug, mode: Mode, slot: datetime, est_credits: int, source_candidates: list[str])`; `plan_today(store, now: datetime) -> list[DueClip]` — a character is due when `now`'s London weekday is in its `cadence.days`, no clip for it already exists today beyond `planned`, and the kill switch is off; `est_credits` = 160 (recreate incl. 70 synthetic driver amortised) or 115 (dropin); stops adding when `committed + Σest > cap`. `choose_mode(store, character) -> Mode`: `dropin` if a dropin-eligible source exists and the character's TikTok account rolling Drop-in ratio over its last 10 clips < its `dropin_share`, else `recreate`. `slot_for(character_slug, day: date) -> datetime` (aware, Europe/London). `accounts_for_clip(store, clip) -> list[Account]`: all the character's accounts for `recreate`; for `dropin`, only accounts whose last-10 Drop-in ratio < `dropin_share`. CLI `studio plan today` prints JSON.

- [ ] **Step 1: Failing tests:** `test_due_on_cadence_day_only` (Tue due, Sat not) · `test_slot_is_london_time_across_dst` (`slot_for('biscuit', date(2026,10,27))` → 19:00 with UTC offset 0; 2026-10-20 → offset +1) · `test_plan_respects_cap` (cap leaves room for one clip → one DueClip) · `test_kill_switch_plans_nothing` · `test_dropin_chosen_when_clean_source_and_under_share` · `test_instagram_skipped_for_dropin_when_over_share` (IG last 10 = 5 drop-ins, share 0.4 → IG not in `accounts_for_clip`).
- [ ] **Step 2–4:** FAIL → implement → PASS. **Step 5: Commit** `feat: daily planning, mode choice, London slots`.

### Task 7: Technical QA and frame sheets

**Files:** Create `studio/media/__init__.py`, `studio/media/qa.py`, `tests/test_qa.py`, `tests/conftest.py`; Modify `studio/cli.py`.

**Interfaces:**
- Produces: `@dataclass TechReport(width,height,fps,duration_s,video_kbps,has_audio,lufs:float|None,true_peak:float|None,problems:list[str])` with `.ok`; `probe(path) -> TechReport` (ffprobe JSON; loudness via `ebur128=peak=true`); `check_master(r) -> list[str]` against Global Constraints; `check_source(r)` (≥ 480 px wide, 4–30 s, any fps 23–60); `frame_sheet(path, n=6, out) -> Path` (n evenly spaced frames at 270 px wide, hstacked). CLI `studio qa tech <file> [--master]` (exit 1 on problems) and `studio qa frames <file> --out <jpg>`.
- `conftest.py` fixture `synth_video(tmp_path, w=1080, h=1920, fps=30, dur=10, audio=True)` built with `ffmpeg -f lavfi testsrc2 + sine`.

- [ ] **Step 1: Failing tests:** `test_good_master_passes` (synthetic 1080×1920/30/10 s with audio normalised to −14) · `test_low_res_fails` (720×1280 → problem `resolution`) · `test_silent_fails` · `test_too_long_fails` (20 s) · `test_frame_sheet_has_n_frames` (output width = 6×270).
- [ ] **Step 2–4:** FAIL → implement → PASS. **Step 5: Commit** `feat: technical QA and frame sheets`.

### Task 8: Overlays and the master timeline

**Files:** Create `studio/media/overlays.py`, `studio/media/master.py`, `tests/test_master.py`; Modify `studio/cli.py`. Fonts are not committed (system licences): `overlays.font_path()` returns `/System/Library/Fonts/Supplemental/Arial Rounded Bold.ttf` on macOS, else the path from `fc-match -f '%{file}' 'DejaVu Sans:bold'`.

**Interfaces:**
- Produces (`overlays.py`): `hook_png(lines: list[str], out, y=350, size=96, font=None) -> Path` (white, 3 px dark stroke, blurred shadow — the debut style); `bug_png(out) -> Path` (two-dot ODD EYES mark at (972,268)); `sparkle_png(out, size=320) -> Path`; `sting_wav(out) -> Path` (0.6 s chime: 2093/3136/4186 Hz, decays 6/8/10, as in `scratchpad/debut/debut.sh`).
- Produces (`master.py`): `@dataclass MasterSpec(dance: Path, closeup: Path|None, closeup_center: tuple[int,int], blue_eye_xy: tuple[int,int], hook1: list[str], hook2: list[str], hook2_until_s: float, audio: Path, audio_offset_s: float, out: Path, intro_s=0.8, outro_s=0.7, intro_zoom=0.30, outro_zoom=1.30)`; `build_master(spec) -> Path` — the exact pipeline of `docs/spike` + `scratchpad/debut/debut.sh` (intro zoompan → dance normalised to 1080×1920@30 → outro still + sparkle fade → concat → hook1/hook2/bug overlays → audio: source beat from `audio_offset_s`, fade, sting at dance end, two-pass loudnorm to −14). When `closeup` is None the clip has no intro/outro (eye loops build their own). `MasterSpec.enhancements: list[dict]` supports `{"type":"slowmo","at_s","dur_s","factor"}` (setpts on that span, audio untouched), `{"type":"zoom_hit","at_s","scale":1.06}` (0.25 s punch-in), `{"type":"impact_sfx","at_s"}` (synthesised low thump mixed at −6 dB), `{"type":"text_pop","at_s","dur_s","text"}` (PIL PNG overlay), `{"type":"title_card","text"}` (first 0.6 s, brand serif); tests `test_slowmo_extends_duration` and `test_text_pop_visible_only_in_window`. CLI `studio master build --spec <json>`.

- [ ] **Step 1: Failing tests:** `test_master_meets_spec` (synth dance 9 s + synth closeup PNG + synth audio → `check_master(probe(out)) == []` and duration = 0.8 + 9 + 0.7 ± 0.05) · `test_hook_png_is_transparent_and_full_frame` (size 1080×1920, corner alpha 0) · `test_sting_length` (0.6 s ± 0.01).
- [ ] **Step 2–4:** FAIL → implement → PASS (CI installs `fonts-dejavu-core`). **Step 5: Commit** `feat: overlays and master timeline (ODD EYES end beat)`.

### Task 9: Supabase Storage

**Files:** Create `studio/storage.py`, `tests/test_storage.py`.

**Interfaces:**
- Produces: `class Storage(Protocol)`: `upload(bucket, path, file) -> str`, `download(bucket, path, dest) -> Path`, `signed_url(bucket, path, expires_s=86400) -> str`; `SupabaseStorage(url, service_key)` via httpx (`POST /storage/v1/object/{bucket}/{path}` with `x-upsert: true`; `POST /storage/v1/object/sign/{bucket}/{path}` → `signedURL`); `LocalStorage(root)` for tests.
- [ ] **Step 1:** `test_local_roundtrip`; `test_supabase_requests_shape` (httpx `MockTransport` asserts method, path, auth header `Bearer <key>`). **Step 2–4:** FAIL → implement → PASS. **Step 5: Commit** `feat: storage adapter`.

### Task 10: Publishing via Postiz (idempotent)

**Files:** Create `studio/publish/__init__.py`, `studio/publish/base.py`, `studio/publish/postiz.py`, `tests/test_publish.py`; Modify `studio/cli.py`.

**Interfaces:**
- Produces (`base.py`): `@dataclass PublishResult(platform_post_id: str, url: str|None)`; `class Publisher(Protocol)`: `publish(*, platform: Platform, integration_id: str, media_url: str, caption: str, hashtags: list[str], ai_label: bool) -> PublishResult`; `publish_due(store, storage, publisher, now) -> dict` — claims due posts, for each: signed URL of the clip master → `publisher.publish(...)` → `update_post(status='posted', platform_post_id, url)` and clip → `posted` when all its posts are posted; on exception: `attempts+1`, back to `scheduled` (`claimed_at=None`) if attempts < 3 else `failed`; before claiming, any post in `posting` with `claimed_at < now-30min` → `needs_check` (never retried automatically). Enforces ≤ 2 posted per account per London day (excess rescheduled to the next slot).
- Produces (`postiz.py`): `PostizPublisher(run=subprocess.run)` — runs `postiz upload <downloaded file>` (Postiz requires its own upload path; Rule 2 of the postiz skill) then `postiz posts:create` with content = caption + hashtags, media = the upload `.path`, integration id, and per-platform settings: TikTok `content_posting_method: "DIRECT_POST"`, AI-generated flag on, privacy public; Instagram post type Reel. **Before writing the adapter, run `postiz integrations:settings <id>` for one TikTok and one Instagram integration and pin the exact setting keys in module constants `TIKTOK_SETTINGS` / `INSTAGRAM_SETTINGS`** (Rule 4 of the skill: unknown settings are silently dropped). CLI `studio publish due [--dry-run]`.
- [ ] **Step 1: Failing tests** (fake publisher + MemoryStore + LocalStorage): `test_posts_due_and_marks_posted` · `test_failure_retries_then_fails_after_3` · `test_stale_posting_becomes_needs_check_not_retried` · `test_daily_cap_two_per_account` (3 due same day → 2 posted, 1 rescheduled to next slot) · `test_postiz_tiktok_uses_direct_post` (fake `run` captures argv; JSON settings contain `DIRECT_POST`).
- [ ] **Step 2–4:** FAIL → implement → PASS. **Step 5: Commit** `feat: idempotent publishing via Postiz`.

### Task 11: Metrics and outlier_x

**Files:** Create `studio/metrics.py`, `tests/test_metrics.py`; Modify `studio/cli.py`.

**Interfaces:**
- Produces: `outlier_x(views_7d: int|None, prior_views_7d: list[int|None]) -> float|None` — `None` if `views_7d is None` or fewer than 3 non-None priors; else `views_7d / median(last 15 non-None priors)`; `pull(store, postiz_run, now)` — for posted posts aged 1 h/24 h/72 h/7 d (±15 min windows) run `postiz analytics:post <id> -d 7`, write a `Snapshot`; `{"missing": true}` → no snapshot (log); at the 7 d pull write `clip.features['outlier_x']` (per account; clip value = max over accounts). `ingest_ig_insights(store, rows: list[dict])` — accepts vidIQ `instagram_owner_insights` rows (called by the weekly-review skill) mapping shares/saves/watch time/skip rate into snapshots. CLI `studio metrics pull`, `studio metrics ingest-ig <json>`.
- [ ] **Step 1: Failing tests:** `test_outlier_x_basic` (prior [100,200,300], views 600 → 3.0) · `test_outlier_x_none_when_missing` · `test_outlier_x_ignores_none_priors` · `test_outlier_x_uses_last_15_only` · `test_missing_analytics_writes_no_snapshot`.
- [ ] **Step 2–4:** FAIL → implement → PASS. **Step 5: Commit** `feat: metrics ingest and outlier_x`.

### Task 12: Weekly review data and bars

**Files:** Create `studio/review.py`, `tests/test_review.py`; Modify `studio/cli.py`.

**Interfaces:**
- Produces: `@dataclass Lift(feature, value, n, median_outlier_x, account_median)`; `feature_lifts(clips: list[Clip], min_n=5) -> list[Lift]` over `REQUIRED_FEATURES` keys; `format_verdicts(clips) -> dict[str, Literal['keep','kill','continue']]` (keep ≥ 1.5 over ≥ 5; kill ≤ 0.7 over ≥ 8); `hook_proven(clips) -> dict[str,bool]` (≥ 2 hits in last 10 uses); `character_bar(store, slug, now) -> Literal['promote','kill','continue','not_yet']` (20 posts or 4 weeks; thresholds from Global Constraints); `ig_guard(store, account, now) -> bool` (True → sets `dropin_share=0.20`); `review_payload(store, now) -> dict` (JSON consumed by the weekly-review skill). CLI `studio review data`.
- [ ] **Step 1: Failing tests:** `test_lift_needs_5_posts` · `test_format_keep_and_kill_thresholds` (exact boundary values 1.5/0.7 and n 5/8) · `test_hook_proven_two_hits_in_ten` · `test_character_bar_not_yet_before_20_posts_and_4_weeks` · `test_character_bar_kill_requires_both_platforms_low` · `test_ig_guard_cuts_share_on_40pct_drop`.
- [ ] **Step 2–4:** FAIL → implement → PASS. **Step 5: Commit** `feat: weekly review data and pre-registered bars`.

### Task 13: Seed characters + the daily-run and weekly-review skills

**Files:** Create `characters/biscuit/refs.json`, `characters/reginald/refs.json`, `.claude/skills/daily-run/SKILL.md`, `.claude/skills/weekly-review/SKILL.md`, `.claude/settings.json`, `tests/test_seed.py`; Modify `studio/cli.py` (`studio seed`).

**Interfaces:**
- `refs.json` schema: `{"slug","name","bodies":["biped",...],"masters":{"biped":"<higgsfield job id>","quadruped":"<id>|null"},"closeup":"<job id>","closeup_center":[x,y],"blue_eye_xy":[x,y],"avatar":"assets/avatars/<slug>.png","accounts":[{"platform","handle","postiz_integration_id","dropin_share"}]}`. Biscuit masters: biped `42f579b9-3da3-42ff-af47-98d758112743`, quadruped `d863df81-54f8-45df-9676-cf44338d07fa`, closeup `7798e2bc-d0bd-492d-8d7f-a96063150c4f` (center [536,732], blue eye at zoom 1.3 [301,960]). Reginald biped `6b1625b1-b2e3-4292-ba35-4aac86e6b6e4`, closeup = generate in rehearsal. Handles/integration ids filled after the owner creates accounts (null until then; accounts with null integration ids are skipped by planning).
- `studio seed` upserts characters + accounts from `refs.json`, and `studio seed picks docs/launch/viral-picks-2026-10-04.md` loads batch 1 (17 scored picks, status `new`).
- `/daily-run` SKILL.md (write with `writing-for-agents`; ≤ 120 lines; numbered, imperative): 1 `bin/studio plan today` → stop if empty. 1b **Approved Viral Picks first:** `bin/studio fav list --next 2`; for each `approved` pick run vidIQ `watch_shortform_content` (10 credits) with a prompt asking for beat-by-beat choreography, setting, camera, hook text and audio type → `bin/studio fav mark --status analysed --breakdown <md>`; a due clip for that character uses the favourite as its concept (synthetic driver briefed from the breakdown; Drop-in only with a linked clean inbox source) → `fav mark --status queued --clip <id>`. 2 Trends → **Viral Picks**: one vidIQ outlier scan from the character's bible scan profile; write every outlier that passes the brand-safety gate as a pick with `bin/studio fav pick` (url, platform, creator, views, outlier ×, character, proposal {mode, hook, prop, concept}, and the four judged sub-scores freshness/fit/feasibility/saturation per the spec rubric) — status `new`, shown in the terminal for approval — and also (skip on Mon/Wed/Fri to fit 150 credits/month: scans run Tue/Thu/Sat/Sun rotating), `tiktok_music_trending`, Genjutsu Trending/New galleries; `bin/studio source add` for new library candidates after `media_import_url` + visual checks of 6 frames (watermark, overlay, other people, bodies, body type) → `bin/studio source check`. 3 Pick per DueClip: run `bin/studio fav decide` on new picks with the delegated rule (record a one-line reason for analyst decisions); mode from the plan, best source from `bin/studio source list --rank --character X --mode M`; for Recreate without a fitting source, generate a synthetic driver (Seedance 2.5 t2v, 480p, 9–10 s, prompt from the bible's music brief + the chosen concept) and add it as `synthetic`. 4 Per-clip scene still (Seedream 4.5 high, character master + setting + prop from the concept table). 5 `bin/studio budget reserve` → `generate_video` (`hf_mult_motion_control` for recreate / `hf_mult_replace_object` for dropin, 1080p, `declined_preset_id` when a preset is suggested) → submit all clips first, then `jobs_wait` → `bin/studio budget settle`. 6 Download → `bin/studio qa tech` → `bin/studio qa frames` → visual QA (identity, ODD EYES sides, outfit continuity, hands/paws, deadpan for Reginald, rigid quiff, no source people/watermark leaked) → pass/fail (+ `source flag` if leakage) → one re-roll max. 7 `bin/studio master build` with the pick's 1–3 enhancements (hook from the concept, caption + 5 hashtags in the bible voice, run captions through `humanizer`). 8 `bin/studio clip set … state=mastered` → `awaiting_approval` (or `scheduled` if the account is `auto`). 9 Write a run summary with `bin/studio run log --kind daily --status ok|budget_stop|error --summary <text>` (implemented in Task 14 alongside `health`). Hard limits: never exceed `plan today`; one re-roll; stop on `BudgetRefused`.
- `/weekly-review` SKILL.md: `bin/studio metrics pull`; vidIQ `instagram_connected_accounts` → `instagram_owner_insights` → `bin/studio metrics ingest-ig`; `bin/studio review data`; `last30days` trend read for each niche; write `reviews` rows + update each `characters/*/playbook.md` (only rules with ≥ 5 posts), commit; apply `ig_guard`; report bar status.
- `.claude/settings.json` allow list (prefix form): `Bash(bin/studio:*)`, `Bash(uv run:*)`, `Bash(ffmpeg:*)`, `Bash(ffprobe:*)`, `Bash(curl:*)`, `Bash(git add:*)`, `Bash(git commit:*)`, `mcp__53354c6e-fbc1-47dd-ac53-ad2126ec66bd`, `mcp__5d0eb7b3-1f89-4c02-b145-8199ffc4ed25`. If the auto-mode classifier refuses to write it, stage it as `.claude/settings.json.proposed` and add an owner step to copy it.
- [ ] **Step 1: Failing test** `tests/test_seed.py::test_seed_creates_characters_and_skips_null_accounts`. **Step 2–4:** FAIL → implement → PASS.
- [ ] **Step 5: Rehearsal (real MCPs, ~260 credits, needs the owner's top-up):** run `/daily-run` by hand for both characters with `--dry-run` publishing: (a) **multi-body test** — synthetic 3-dancer driver + Biscuit master → Genjutsu recreate → record in `docs/spike/` whether 3 bodies hold identity; (b) Reginald Quiff on the slick driver; (c) Biscuit cute debut re-render. Pass = both clips reach `awaiting_approval` with QA reports, budget ledger equals the Higgsfield balance delta ±1.
- [ ] **Step 6: Commit** `feat: seed, daily-run and weekly-review skills, permissions`.

### Task 14: GitHub Actions — publish, metrics, health

**Files:** Create `.github/workflows/publish.yml`, `metrics.yml`, `health.yml`; Create `studio/health.py` + `tests/test_health.py`.

**Interfaces:**
- `health.check(store, now) -> list[str]`: problems when no `runs(kind='daily')` finished in the last 26 h, any post `failed` or `needs_check`, or month committed ≥ 80 % of cap. CLI `studio run log --kind --status --summary` (writes `runs`) and `studio health` exits 1 with problems printed (a failing scheduled workflow emails the owner via GitHub's own notification).
- `publish.yml`: `schedule: '*/15 * * * *'` + `workflow_dispatch`; setup uv + Node 20; `npm i -g postiz`; `uv run studio publish due`; env from secrets. `metrics.yml`: `'7 */6 * * *'` → `uv run studio metrics pull`. `health.yml`: `'23 * * * *'` → `uv run studio health`.
- [ ] **Step 1: Failing tests** `test_health_flags_missing_daily_run`, `test_health_flags_needs_check`, `test_health_flags_80pct_cap`. **Step 2–4:** FAIL → implement → PASS.
- [ ] **Step 5:** `gh secret set` the four secrets from Keychain; `gh workflow run publish.yml` with an empty queue → green.
- [ ] **Step 6: Commit** `feat: scheduled publish, metrics and health workflows`.

### Task 15: Terminal RPCs + Vite app

**Files:** Create `supabase/migrations/0002_terminal_rpc.sql`; `terminal/` (Vite React TS): `src/lib/supabase.ts`, `src/lib/format.ts`, `src/lib/format.test.ts`, `src/pages/{Channels,Queue,Library,Budget}.tsx`, `src/App.tsx`, `src/Login.tsx`.

**Interfaces:**
- `0002`: views `studio.v_channels` (per account: followers latest, posts, 7-day views, median outlier_x, hit rate, mode, dropin_share, character bar status), `v_queue` (clips `awaiting_approval` with signed-URL-ready `master_path`, hook, caption, hashtags, mode, source credit, cost, QA summary), `v_library` (all clips + posts + latest snapshot), `v_budget` (month committed, cap, per character, projected month-end = committed / day-of-month × days-in-month, kill switch). RPCs (`security invoker`, owner RLS): `studio.approve_clip(clip_id uuid, caption text, hook text, schedule_at timestamptz default null)` → clip `approved` then creates `posts` for `accounts_for_clip` logic mirrored in SQL (recreate → all accounts; dropin → accounts under share) at the next slot or `schedule_at`, sets clip `scheduled`; `studio.reject_clip(clip_id, reason)`; `studio.set_budget(cap int, kill boolean)`; `studio.set_account_mode(account_id, mode text, dropin_share numeric)`.
- `format.ts`: `formatCredits(n) -> "1,234 cr"`, `outlierBadge(x: number|null) -> {label, tone}` (≥3 "hit"/positive, ≥1.5 "good", ≤0.7 "weak", null "—").
- Pages: **Today** (home, see owner directive above), **Channels** (cards per account with the v_channels fields + mode toggle), **Queue** (video player via `storage.from('clips').createSignedUrl`, editable hook/caption, Approve / Schedule / Reject-with-reason / Regenerate → inserts a `clips` row note for the next daily run), **Library** (table with filters character/platform/state, outlier badge), **Budget** (committed vs cap bar, per character, projected month-end, kill switch, cap editor), **Viral Picks** (cards from `studio.favorites` with status `new`, **sorted by total score with the six sub-scores shown as small bars**: link that opens the original, platform, views, outlier ×, matched character, proposed version; **Approve** (with character override) / **Skip**; a paste box for the owner's own links (`origin='owner'`, auto-approved); approved/produced history with the resulting clip). Design: load `impeccable` + `dataviz` before writing UI; dark, dense terminal style consistent with the owner's other terminals.
- **Owner directive (2026-10-04): "as autonomous as possible, very easy to use for me, state of the art".** Therefore: (a) a **Today** home page (default route) — what posts today per channel, clips waiting (with one-tap **Approve all**), new Viral Picks count, spend vs cap, alerts from `health` — every action reachable in ≤ 2 taps; (b) **Autopilot** toggle per channel on Today and Channels (sets `accounts.mode='auto'`: clips that pass QA skip the approval queue; Viral Picks follow the delegated rule) — default ON for picks, OFF for posting until the first 6 posts per account are approved; (c) **mobile-first** layout (works one-handed on a phone) + **PWA** manifest/service worker so it installs to the home screen; (d) **Supabase Realtime** subscriptions on `clips`, `posts`, `favorites` so screens update live without refresh; (e) storage RLS policies on `storage.objects` (owner email) for the `clips` bucket so the browser can create signed URLs.
- Auth: Supabase magic link (`signInWithOtp`) for the owner email; all reads go through RLS.
- [ ] **Step 1: Failing test** `src/lib/format.test.ts` (`outlierBadge(3)` → hit, `(null)` → "—"; `formatCredits(1234)` → "1,234 cr"). **Step 2:** `npm test` FAIL. **Step 3:** implement lib + pages. **Step 4:** `npm test` PASS; `npm run build` succeeds.
- [ ] **Step 5:** apply `0002` via Supabase MCP; seed 3 fake clips in `studio_test`-like fixtures (or real rehearsal clips from Task 13) and verify in the browser preview: login → Queue shows a clip → Approve creates 2 posts (recreate) → Budget shows the ledger total. Screenshot for the owner.
- [ ] **Step 6: Deploy:** Vercel project `odd-eyes-terminal`, git-linked to the repo, root `terminal`, env `VITE_SUPABASE_URL` + `VITE_SUPABASE_ANON_KEY` (Vercel MCP `create_project` / `create_project_env`; if the token lacks write scope, owner imports the repo in the Vercel dashboard — 2 min). Verify on the production URL.
- [ ] **Step 7: Commit** `feat: terminal (channels, queue, library, budget)`.

### Task 16: Scheduled tasks and go-live

**Files:** Modify `docs/launch/channel-strategy.md` (§7 checklist ticks), `CLAUDE.md` (task ids).

- [ ] **Step 1:** From this project folder, create Claude scheduled tasks with `mcp__scheduled-tasks__create_scheduled_task`: `studio-daily-run` (daily 08:00 Europe/London, prompt `/daily-run`, model Sonnet) and `studio-weekly-review` (Mondays 09:00, prompt `/weekly-review`, model Opus). Record the ids in `CLAUDE.md`.
- [ ] **Step 2:** Trigger `studio-daily-run` once with `run_scheduled_task`; check `list_task_runs` shows a completed run with no permission stall, and `runs` has a `daily` row.
- [ ] **Step 3: Owner go-live gate** (blocking, owner actions): accounts created as Creator with AI labels; Postiz connected (integration ids pasted into `refs.json` → `bin/studio seed`); Instagram accounts connected to vidIQ; Higgsfield top-up; owner approves the first queued clips in the terminal.
- [ ] **Step 4:** Watch the first `publish.yml` run post both debut clips; confirm on TikTok and Instagram (URLs in `posts`), AI label visible, 1080p.
- [ ] **Step 5: Commit** `chore: go-live — scheduled tasks live`.

---

## Self-review notes

- Spec coverage: §4.3 CLI (Tasks 2–12), §4.4 daily run (13), §4.4b viral modes (4, 6, 13), §4.5 audio (8, 13), §4.6 terminal (15), §4.7 publishing (10, 14), §4.8 stats/learning (11, 12, 13), §4.9 bars (12), §5 data (2), §6 quality (7, 8, 13), §7 safeguards (3, 4, 10, 14), §8 errors (5, 10, 14), §12 risks (13 rehearsal, 10 Postiz settings pin, 16 scheduled-task check). Slice 2/3 items (auto-post switch UI is in 15; Outsider voice lane, Virality Predictor) are out of scope here.
- Owner-gated steps are explicit (top-up, accounts, Postiz, Vercel scope fallback, settings.json fallback).
