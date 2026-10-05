# Final fix wave: report

Branch `build/slice1`, from `a6ec880`. 14 commits (list at the end). Everything is test-first unless an item says otherwise.
Where section A and section B overlapped, A won (R-A1: no `--force`; M-11: raise over 2,200, never trim; M-12: 408 and 409).
`.claude/settings.json` was never touched. `.claude/settings.json.proposed` was rewritten (R-A2). No live database, no
network call to Higgsfield, vidIQ, Postiz, TikTok or Instagram; the one network use was `npm view postiz version` (R-A4).
`bin/store-secrets` appeared untracked during the work (not mine); it is not committed.

Evidence format: `file:line` of the change, the test that covers it, and the red run (what failed before the fix) then green.

---------------------------------------------------------------------------------------------------------------------
## Section B

### B1 metrics (also A M-8)
- 7 d window gives up at age > 14 d, reported under `abandoned`, not fetched, exit 0.
  Change: `studio/metrics.py:94` (`ABANDON_AFTER`), `:392` (`_report_abandoned`), `:437` (the age gate in `pull`), docstring and
  `.github/workflows/metrics.yml` comment. Tests: `tests/test_metrics.py:278` (15 d: `abandoned`, `fake.calls == []`, `errors == []`),
  `:290` (exactly 14 d still pulled), `:323` (older than 28 d: not even a `snapshots_for` query), `:1103` (CLI exit 0).
  Red: `assert fake.calls == []` failed (the pull still fetched a `missing` reply and logged "missing"); green after the gate. The
  existing parametrized case `(30 * D, "7d")` was changed to `(14 * D, "7d")`.
- M-8 "skip posts > 14 d before any snapshots_for query": done for posts older than 28 d (`ABANDON_REPORT_FOR`, `metrics.py:96`).
  DEVIATION, on purpose: a literal "no snapshot query for any post > 14 d" would make `abandoned` unreportable without false
  positives (every measured old post would be listed forever and the summary would grow with the library). So a post aged 14 to 28 d
  gets one `snapshots_for` lookup (reported only when it holds no 7 d snapshot), a post older than 28 d costs no query at all and is
  not reported. Work per run is bounded by the last 28 days of posts. Red: the 3 new tests failed before the refinement
  (`test_a_post_older_than_the_report_horizon...`, `..._inside_the_report_horizon...`, `..._outlier_heal_loop`). Also: past 14 d a post's
  clip is no longer refreshed from the pull (an ingest still refreshes it).

### B2 publishing
- Fresh `posting` posts count toward the 2/day cap: `studio/publish/base.py:148` (`_posted_counts(store, day, now)`), used by
  `publish_due` and `preview_due` (a stale `posting` post is still counted exactly once, as `needs_check`).
  Tests: `tests/test_publish.py:566` (+ `:579`, `:588`, `:598` another account, `:606` stale counted once, `:616` dry run).
  Red: 4 failures (`test_a_fresh_posting_post_counts...`, `two_fresh...`, `one_fresh...`, `dry_run_counts...`); green after.
- HTTP 408 uncertain (A: and 409): `studio/publish/postiz.py:88` regex `API Error \((?!408\)|409\))4\d\d\)`.
  Tests: `tests/test_publish.py:970` (408), 409 test just below it, the two end-to-end `needs_check`-never-retried cases, and 408/409 added to
  the uncertain parametrization. Red (old regex patched back in): `PostizError` instead of `UncertainPublish` for both.
- Caption limit: A overrides B (raise, not trim). `studio/captions.py:42` `compose_content` raises `ValueError` when the composed
  text is over 2,200 (UTF-16 units, the stricter count). See M-11 below.
- `clip schedule` refuses approval-mode accounts: A overrides B (no `--force`). See M-2.
- Re-scheduling an already `scheduled` clip returns its posts, exit 0: `studio/clips.py:273`. Tests `tests/test_schedule.py:311`
  (+ `:322` no check even if an account is now in approval mode, `:333` scheduled with zero posts is still refused), CLI
  `test_cli_rescheduling_a_scheduled_clip_exits_0_with_its_existing_posts`. Red: the idempotency test failed with "only a mastered or
  approved clip can be scheduled", exit 2.

### B3 reviews
- Migration `supabase/migrations/0006_slot_and_reviews.sql:195`: `create unique index ... reviews_week_character_slug_key on
  studio.reviews (week, character_slug)`, after folding duplicate rows (oldest survives, the one the old save kept rewriting).
  The real key is `(week, character_slug)`, not `(kind, period_start)`: that is what the table has. NOT applied live.
- `studio/pgstore.py:438` `upsert_review` is now one `INSERT ... ON CONFLICT (week, character_slug) DO UPDATE` (was a
  select-for-update + update/insert). `MemoryStore.upsert_review` already upserted. Tests: `tests/test_pgstore_unit.py:484`
  (single statement, conflict target, id/created_at untouched, FK -> ValueError), `tests/test_schema.py` 0006 pins,
  `tests/integration/test_pgstore.py` (skipped here) `test_review_upsert_is_keyed_on_week_and_character_by_the_database`.
  Red: the two rewritten unit tests failed against the old lookup+write code.
- `golive` markers for 0006 (`studio/golive.py`), the drift guard `test_the_markers_cover_exactly_what_the_migration_files_create`
  was red until they were added.

### B4 master build
- `spec_from_json` rejects a str (or non-str items) for hook1/hook2: `studio/media/master.py:618`. Test `tests/test_master.py:531`
  (12 parametrized cases). Red: `DID NOT RAISE ValueError` for the str case.
- hook2 window checked without a close-up: `master.py:504` (`any(line.strip() ...) and hook2_until_s <= intro_len`).
  Test `tests/test_master.py:547`. Red (old condition `closeup and spec.hook2 and ...` put back): the test failed, the master was built.
- End beat in a built master: `tests/test_master.py:493` renders a master (red close-up, blue dance, silent beat) and asserts the last
  0.7 s is the close-up (colour), has bright glint pixels around `blue_eye_xy` and none elsewhere, and that the sting is 20x louder than
  the silent beat after the dance ends. Mutation-checked: no sting, no glint, and outro = dance each make it fail (3 of 3). A first
  version of the test had a path collision with `spec_for` (it overwrote my close-up); caught by the mutation run, fixed before commit.

### B5 favourites
- Already fixed before this wave: `studio/favorites.py:172` `validate_needs`, called at `:164` and in `_add_pick`; tests
  `tests/test_favorites.py:756-800` cover unknown token, dict, int, list with a bad item, CLI. Evidence commit `4242e3e`.
- Hardening added (the other doors): a malformed `needs` that is stored anyway (old row, hand edit) no longer fails open or raises
  `TypeError`: `_needs` returns `MALFORMED_NEEDS` so the rule holds the pick (`favorites.py:156`); `mark_favorite` validates a
  `proposal` it is given (`:485`). Tests `tests/test_favorites.py:799` (6 cases, also `fav list` exit 0), `:818`. The old
  `(95, 9, "something_else", "approve")` edge case, which pinned the fail-open, is now `"hold"`. Red: 5 failures.

### B6 daily-run skill + CLAUDE.md (`.claude/skills/daily-run/SKILL.md`, `CLAUDE.md:29`)
Every bullet, with the A items it merges with:
- Re-roll sets `--state generating` once: step 8.4 "then step 7 for that clip WITHOUT its own `clip set --state generating`".
- Refused top-up reserve: step 7.1 "settle what was spent, drop the clip, return the pick, `budget_stop`".
- Crash recovery: step 1.2 iterates `bin/studio budget open` (see M-4): settle the charged amount first, release only when proven uncharged.
- `--trend`: added `--trend-file` to `source add` (the CLI had none); `fav pick` url and creator come from the proposal file (M-7).
- Pick return: "analysed when `breakdown_md` is set, else approved", defined once under Hard limits and used at 1.3, 5.3, 6.3, 7.1.
- `credits_actual` cumulative over a re-roll: step 7.3 and 8.4.
- Zero live characters: step 1.1 skips scan and plan, logs "no live characters" in step 10, exits cleanly.
- Guardrail: names `media_import_url` as the one permitted upload (our own Storage signed URL or a library URL).
- `curl -L --create-dirs`: every download in the skill, URL single-quoted, a URL containing `'` is never fetched.
- CLAUDE.md: "user-invoked" dropped, and the pending-owner-step text now describes the explicit allowlist.
- Permission note: see "Permission suggestions" below (A's R-A2 allowed me to edit the proposal, I did).
Tests: `tests/test_skills.py` (new). 52 parametrized cases check that every `bin/studio ...` command and every `--option` cited in
both skills exists in the Typer app; others pin the allowlist against the tools the skills call, the guardrail wording, the file-based
third-party text, the single `generating` call, the cumulative `credits_actual`. Red: my first draft of the skill failed 3 of them
(two allowed tools, `show_generation_by_ids` and `models_explore`, were never mentioned; fixed by naming them where they are used).

### B7 terminal Queue
- `terminal/src/lib/rules.ts:107` `nextCurrentId` gains `lastIndex`; a removed current id -> `ids[min(lastIndex, len-1)]`, null when
  empty, deep link priority and "keep a valid current id" unchanged. `terminal/src/pages/Queue.tsx:26` tracks the viewed position in a
  ref. Tests `terminal/src/lib/fixes.test.ts:30-45`: approving 2 of 3 lands on the former 3rd (now 2 of 2), removing the last lands on
  the new last, empty -> null, clamping, deep link still wins. Red: 3 failures (old code returned the first clip). `npm test` 64 passing,
  `npm run build` green.

---------------------------------------------------------------------------------------------------------------------
## Section A

### M-1 Kill switch stops posting
`studio/publish/base.py:217` (`publish_due`: after reconcile and stale flagging, `kill_switch` -> `paused: true`, nothing claimed) and
`:378` (`preview_due`, `paused` key, nothing would post). Docstrings updated. Tests `tests/test_publish.py:639` (on: posts stay `scheduled`,
never claimed), `:650` (reconcile and stale flagging still run), `:661` (off: normal, `paused: false`), `:668` (wait through the pause, go
out when lifted), `:678` (dry run). Red: 4 failures (`KeyError: 'paused'`, posts published). Terminal copy (`rules.ts:135`
`KILL_SWITCH_COPY`, used by `Budget.tsx` and `Today.tsx`): "Stop all new spend and posting", "nothing is generated or posted"; test
`fixes.test.ts:148`.

### M-2 `clip schedule` bypasses approval
`studio/clips.py:251` `schedule_clip` (no `force`), CLI at the bottom of the file. A `mastered` clip is refused when ANY account in
`accounts_for_clip` has `mode != 'auto'` (message names the handles and says "set the clip to awaiting_approval", `:295`); a clip with
no `master_path` is refused (`:280`, mirrors 0005 `queue_block_reason`); an already `scheduled` clip returns its posts, exit 0 (`:273`).
An `approved` clip is not checked for mode (it is the owner's yes, as in the RPC). Tests: `tests/test_schedule.py:382` (refused, no
`--force` in the message), `:393` (one account in approval mode refuses the whole call), `:404` (approved passes), `:412` (unconnected or
skipped accounts do not count), `:439` (no `force` parameter), `:444` (no master), CLI `--force` is an unknown option (exit 2), idempotent
CLI. Red: 6 failures. I had first built a `--force` flag (B2 wording); removed per R-A1 before any commit.

### M-3 One slot rule, Python and SQL
- `studio/planning.py:158` `taken_days`, `:177` `free_slot`: first cadence slot from `upcoming_slot(now)` on a London day on which no
  target account has a post in scheduled/posting/posted/needs_check (day = `claimed_at` else `scheduled_for`; the clip's own posts left out;
  56-day look-ahead then `ValueError`). `schedule_clip` uses it for the default time; `--at` stays the owner's choice.
- Publish deferral = first free cadence day after today: `studio/publish/base.py:124` `_deferred_slot`, two deferrals in one run never share
  a day; `next_slot` is now a thin wrapper over `free_slot` (consolidated).
- SQL: `supabase/migrations/0006_slot_and_reviews.sql:25` `studio.free_slot`, `next_free_slot`, `:96` `approve_clip` replaced (default slot
  `coalesce(schedule_at, studio.free_slot(...))`, everything else from 0005 unchanged), `v_queue` re-created with the same columns and
  `next_slot` = `next_free_slot`. Not applied live (R-A3: one file, `studio_0006`). I have no local Postgres: the SQL was written
  against the 0004/0005 patterns and pinned by text tests; the integration test `test_free_slot_in_sql_agrees_with_planning_free_slot`
  (skipped here, needs `DATABASE_URL_TEST`) compares the SQL answer with the Python one and should be run when the controller applies it.
- Tests: `tests/test_schedule.py:99-196` (`free_slot`, `taken_days`), `:342` (two approvals land on different days, three on Tue/Wed/Thu),
  `:353`, `:363`, `:370`; `tests/test_publish.py:691-725` (deferral); `tests/test_schema.py` 0006 block (free_slot mirrors Python,
  approve_clip uses it and nothing else, v_queue columns, grants); terminal copy `SLOT_RULE` ("first free slot", `rules.ts:128`).
  Red: ImportError for `free_slot`, then 3 publish failures.

### M-4 Daily-run money accounting
`studio/budget.py:231` `open_reservations` + `:369` `studio budget open` (read-only JSON: clip_id, state, character, clip_created_at,
held, months, oldest_reserved_at, age_hours; 12-month look-back, sums per clip, sorted by real instant). Skill step 1.2 iterates it for
anything over 2 h: settle the charged sum found through `transactions`/`show_generations` since `clip_created_at`, else settle `held`,
release only when proven uncharged, then `generating` -> `gen_failed`, `planned`/`qa_failed` -> `dropped`. 7.1, 8.4, picks to `analysed`
with a breakdown, cumulative `credits_actual`, zero live characters, `qa frames` on the master before upload (9.3). Tests
`tests/test_budget.py:428-505` (9 tests incl. a reservation made after a settle, month boundary, ghost clip, read-only CLI),
`tests/test_skills.py`. Red: 7 failures (no such function/command).

### M-5 Legal music for Drop-in / library drivers
Skill 6.1: a library or inbox driver gets a `seedance_2_5` t2v beat render (480p, 10 s, `generate_audio: true`, music brief only),
preflighted and reserved (5.2), marked "VERIFY at rehearsal"; never `gen.mp4`'s or a source file's audio. Code `studio/media/master.py:653`
`audio_problem`, `:706` `_check_audio_rights`, `build_command --clip`: `master build` refuses (exit 2, nothing rendered) when `audio` is the
same file as `dance` (same path, or same bytes) or sits under an `inbox` folder, unless the clip (`--clip` or `clip_id` in the spec, both
must agree) is a `recreate` clip whose source is `synthetic`. No clip given -> the exception is not provable -> refused. The store is only
opened when the audio is the dance or in an inbox, so an ordinary build needs no database. Tests `tests/test_master.py:594-` (11: copy of
the file, five non-exempt mode/kind combinations, the legal synthetic case, `clip_id` from the spec, disagreement, unknown clip, inbox,
separate beat render OK). Red (refusal patched out): the dance-audio test failed.
NOTE: "resolves to a source file" is implemented as the inbox folder plus same-file/same-bytes as the dance; the code cannot know where
the agent saved a downloaded library source. The skill therefore says not to download sources at all for audio.

### M-6 Permission proposal
`.claude/settings.json.proposed` rewritten as an explicit allowlist: the 12 Higgsfield tools and 6 vidIQ tools listed in A, no
whole-server allow, `Bash(uv run:*)`, ffmpeg and ffprobe dropped, the 8 denies kept plus 6 more (below). `studio/golive.py:573`
`_too_broad`, `:591` `check_permissions` now FAIL on `mcp__<server>`, `mcp__<server>__*`, any `*` in an `mcp__` allow and `Bash(uv run:*)`
(also `uv run *`, `uv:*`) in `settings.json` AND in the proposal itself (title is now "permissions: proposal applied (explicit allows,
deny rules)"; go-live.md updated). Skill guardrail (SKILL.md:7) names `media_import_url` as the one permitted upload. Tests
`tests/test_golive.py:667-735` (blanket server forms, uv run forms, explicit tools pass, blanket in the proposal, the real shipped
proposal is explicit and keeps the 8 denies and names every tool the skills call). Red: 10 failures. `settings.json` still has the old
blanket allows: the check will be red until the owner applies the proposal (expected: that is the point).

### M-7 Untrusted text inline in shell
`studio/sources.py:339` `source add --trend-file`; `studio/favorites.py:528` `fav pick` takes url and creator from the proposal JSON
(`--url`/`--creator` now optional, must agree if both are given, and are removed from the stored proposal); skill writes them to files and
single-quotes URLs; `curl -L --create-dirs` everywhere (renders/<id>/, renders/closeups/, renders/lib/). Tests `tests/test_sources.py:400-`,
`tests/test_favorites.py:611-` (incl. `$(...)` and backticks stored verbatim), `tests/test_skills.py`. Red: 13 failures.

### M-8: see B1.

### M-9 Resolve a stuck post
`studio/publish/resolve.py` + `studio/publish/__init__.py:84` `studio publish resolve <post>` with exactly one of
`--live --platform-post-id ID [--url]` (-> posted; the clip moves to posted when it was the last unsettled post), `--retry [--at]`
(needs_check/failed only, clip must still be scheduled; -> scheduled, attempts 0), `--drop --reason-file F` (deletes the never-posted row,
refused when it has a platform id or a snapshot; a clip left without posts goes `scheduled -> rejected` with the reason, which needed
`S.scheduled: {posted, rejected}` in `clips.ALLOWED`). `Store.delete_post` added (memory, Postgres; the surface test now counts 32).
go-live.md step 12 has the line. Tests `tests/test_publish.py:1341-1467` (17). Red: 17 failures.

### M-10 Actions minutes + pinned Postiz
`.github/workflows/publish.yml:19-20` `*/15 17-20 * * *` plus `40 */3 * * *` (24 runs a day instead of 96), `health.yml:13`
`23 */3 * * *`, `postiz@2.0.16` in publish.yml and metrics.yml (`npm view postiz version` on 2026-10-05; go-live step 3 says
"VERIFY at go-live"). go-live.md states about 1,500 of the 2,000 free minutes a month and that a time the owner picks outside the evening
window posts within about 3 hours (also in the terminal, `SCHEDULE_NOTE`). Workflows left disabled; `gh` never run. Tests
`tests/test_workflows.py` (crons, pin, never `latest`, both slots covered in GMT and BST, the minute estimate, the doc states it).
Red: 6 failures.

### M-11 AI disclosure
`studio/captions.py:42` `compose_content` appends `AI_DISCLOSURE` unless that EXACT string is in the caption, and raises `ValueError` over
2,200 (UTF-16 units; the message gives the composed length). The Postiz adapter uses it (a ValueError is a plain failed attempt, retried,
then `failed`), and `clip set --caption/--hashtag` runs the same check against the stored half (`studio/clips.py:425`). Tests
`tests/test_publish.py:1166-1235` ("AI-generated? Never." still gets the disclosure, exact string not repeated, 2,200 boundary, hashtags and
emoji counted, end to end over-long -> failed after 3), `tests/test_clips.py:461-486` (4). Red: import error then assertion failures.
CONCERN: the terminal's approve RPC accepts an edited caption of any length (no SQL check), so an over-long edited caption is only
caught at publish time (post `failed`, `publish resolve` available).

### M-12 = B2 cap + 408 + 409. Done (see B2).
### M-13 = B4 string hooks. Done (see B4).

### Cheap extras
- terminal Login `shouldCreateUser: false` (`Login.tsx:23`), test `fixes.test.ts` (reads the source).
- `studio/sources.py:62` PLATFORM_DOMAINS + tiktokcdn.com, tiktokv.com, cdninstagram.com, fbcdn.net; tests `tests/test_sources.py:435-`
  (6 CDN URLs, a lookalike host is not one, the CLI refuses a CDN url).
- go-live.md step 5: the sign-up switch is project-wide for the shared faceless-youtube Supabase project.
- `studio/planning.py:313` `plan_today` skips characters whose status is not `live` and lists them as `skipped_not_live`;
  tests `tests/test_planning.py:619-` (3). `make_store` in that file now seeds `status="live"`.

---------------------------------------------------------------------------------------------------------------------
## Permission suggestions (report only for `settings.json`)
- `.claude/settings.json` is unchanged and still blanket-allows both MCP servers and `Bash(uv run:*)`; `golive check` will fail until the
  owner reviews the diff and runs `cp .claude/settings.json.proposed .claude/settings.json`.
- Deny rules I added to the PROPOSAL (tighter only): Higgsfield `participate_in_contest`, `create_website`, `tiktok_connect`,
  `tiktok_reconnect`; vidIQ `vidiq_authorize_with_youtube`, `vidiq_connect_youtube_channel`. The weekly review skill's guardrail was not
  changed.
- If the skills ever call a tool that is not on the allowlist the unattended run stalls on a prompt (the 09-19 lesson), so any new tool
  needs a line in the proposal AND a mention in the skill: `tests/test_skills.py` fails for an allowed-but-unused tool and for a cited
  command or option that does not exist.

## Concerns
1. Migration 0006 is untested against a real Postgres (none available). The Python and SQL rules are pinned by text tests and the skipped
   integration test; run `DATABASE_URL_TEST=... uv run pytest tests/integration` when applying it as `studio_0006`.
2. `upsert_review` now needs the unique index: it breaks (ON CONFLICT without a matching constraint) until 0006 is applied, so apply 0006
   before the next `review save`.
3. M-8 deviation described under B1 (28-day horizon instead of a literal 14-day skip).
4. A caption edited in the terminal has no length check in the approve RPC (see M-11).
5. M-5: audio-rights detection is by same file/bytes and `inbox/` path, not by knowing every source file the agent may download.
6. The Higgsfield Seedance t2v beat render (skill 6.1) is untested and flagged "VERIFY at rehearsal": its audio length, whether it is
   music-only, and its cost (`get_cost`) are unknown until a rehearsal.
7. The task text said the baseline was 1238 passed; the suite actually had 1250 passed, 8 skipped before my first change.

## Commits (oldest first)
```
a1405d5 fix(metrics): the 7 d window gives up at post age > 14 d and reports the post as abandoned, not errors (a deleted post no longer keeps the Action red)
a1346ff fix(schedule): clip schedule refuses a mastered clip for an approval-mode account or without a master and is idempotent; one free-slot rule (planning.free_slot, migration 0006 approve_clip); reviews unique key + upsert; caption limit at clip set; Store.delete_post
f2ceb06 fix(publish): kill switch stops posting; fresh posting posts count toward the daily cap; 408/409 are uncertain; deferrals land on a free day; exact AI disclosure with a 2,200 limit; publish resolve
df891aa fix(metrics): bound a pull's work to the last 28 days of posts (an abandoned post is reported for 14 more days, then skipped before any snapshot query)
8aef194 fix(master): hooks must be lists of lines, the hook2 window is checked without a close-up, the end beat is tested in a built master, and the beat can never be the source's soundtrack
8f46aaf fix(favorites): a malformed proposal.needs that is stored anyway holds the pick (fail closed), and mark_favorite validates a proposal it is given
1b04e9a fix(budget): budget open lists clips that still hold credits (read-only), so crash recovery can find a reservation nothing closed
87de887 fix(sources): third-party text goes through files (source add --trend-file, fav pick reads url and creator from the proposal file); platform CDN hosts count as platform pages
52eb5eb fix(planning): plan_today skips characters whose status is not live (and says so)
38ea74f fix(golive): the permission proposal is an explicit allowlist (no whole-server allow, no uv run, ffmpeg or ffprobe), and golive check fails on a blanket allow
8e83918 fix(ci): publish runs 24 times a day (every 15 min in the 17:00-20:59 UTC window + a 3-hourly catch-up), health every 3 hours, the Postiz CLI is pinned to 2.0.16; go-live states the monthly minutes, the pin, the project-wide sign-up switch and publish resolve
497810f fix(skill): daily-run money accounting, a legal beat for Drop-in, third-party text through files, and a test that pins every cited command to the CLI
46dbd6c fix(terminal): the queue shows the clip that took the removed one's place; kill switch, slot and schedule copy state the real rules; sign-in never creates a user
```

## Final test counts
- Python: `uv run pytest -q` -> 1497 passed, 11 skipped (baseline before this wave: 1250 passed, 8 skipped; the 3 new skips are the
  integration tests I added, they need `DATABASE_URL_TEST`).
- Terminal: `npm test` -> 64 passed (baseline 55); `npm run build` green.
- `git status`: clean apart from the untracked `bin/store-secrets` (not mine, not committed).
