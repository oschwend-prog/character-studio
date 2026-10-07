# Terminal v3: ranked clips, reuse across characters, the studio at a glance (design)

**Owner, 2026-10-07** (in order): "in the terminal under new clips show per character what clips are a good choice, what needs
approving, maybe rank them so it's easy for me to approve the top choices for rendering"; "we could even use our clips for
various characters ... maybe there are other subtle adjustments we could do per character"; "it should be very user
friendly. also we need a summary overview with all characters and available videos, generated videos, posted ones, views
total and per day, month etc"; "the marketing should go live now that we start posting". He approved the design in chat
("yes go, write the spec and build it"). Builds on terminal v2 (`2026-10-07-terminal-v2-design.md`) and "Drop a video"
(`../plans/2026-10-06-drop-a-video.md`); the hit rules come from `docs/research/2026-10-07-hit-patterns.md`.

## 1. Principles (every screen)
- Plain words, no studio jargon ("Ready to make", not "drops at state ready").
- One main button per card. Anything that costs credits shows the price first and asks once more with the total.
- Numbers always next to a comparison (last week, the bar) or a plain explanation.
- Every empty state says what will appear and how to fill it.
- Phone first: big tap targets, no sideways page scroll (a wide table scrolls inside its own box, name column pinned).

## 2. Structure (where everything lives)
| Tab | Job | Built now |
|---|---|---|
| **Today** (home) | Everything that needs the owner, ranked | **Studio at a glance** (section 5.1), **Make these** (5.2), **Approve these** (5.3), problems and tonight (as today) |
| **Clips** | The saved clips, ranked per character | **By character** view, the new default (section 6); **All clips** = today's list with its filters |
| **Videos** | Making, to approve, scheduled, posted | unchanged |
| **Characters** | Each character as a channel and a brand | unchanged now (test progress page later) |
| More | Settings, Scan, Budget | unchanged |

Later, once numbers exist (about week 2-3): a **Results** tab (views per channel, top videos, what works, weekly review,
trends, clips to save, money) and the Characters test progress. Not in this build.

## 3. The clip score (the free check)
Every check that ends `ready` stores `drop.score = {"total": 0-100, "potential": 0-10, "swap": 0-10, "reason": "<one line>"}`.

- **potential** (Gemini, new deconstruct field `potential: {score: integer 0-10, reason: one line of at most 80 characters}`):
  how likely this clip, with our character swapped in, gets views. The prompt gives the rubric: the star moves in the first
  second and pays off by second 3; a recognisable moment or a trend many people do; a hook that lands in one glance; the
  clip's own sound is a rising trend sound; not another creator's own character skit. The rubric text is the "What gets
  views now" block, read from `config/hit_rules.md` (owner-editable, at most 20 lines; seeded from the hit-patterns doc's
  rules 1, 3, 4, 5, 6, 9). The same block also steers the hooks (rule 6: at most 7 words, one claim the clip proves within
  3 s, one hook in three names the trend) and the first comment (rule 8: a two-option vote for the next clip, in his voice).
- **swap** (deterministic, from the check): one person in frame 3 (two 1, more 0), full body 2, static camera 2 (handheld
  1), the window keeps clear of every text/watermark span with room to spare 1, the clip has sound 1, a classic 1; capped at 10.
- **total** = round(10 x (0.6 x potential + 0.4 x swap)). **reason** = the potential reason.
- A blocked or failed check has no score. A clip checked before this build has none until it is checked again:
  `studio drop recheck --all-ready` (a `ready` drop with no Make it goes back to `checking`; the cloud sweep takes it; free).
- **Franz's voice.** His bible's `## Voice (captions)` and first comment are rewritten for the happy show-off (owner
  2026-10-07: proud, upbeat, first person, short bouncy lines, "Sausage coming through!", never posh, no crown), because the
  check feeds that section to Gemini; `config/scan.json`'s Franz profile drops "posh". The old voice stays in the bible's
  history notes.

## 4. Reuse: one clip, up to three characters
- **Who may take it.** From a drop whose check finished (`ready`, `making` or `made`), the owner files a **version** for
  another character: like for like (the star's kind must be one the character replaces: a person to Reginald, Lenny and every
  later person character; a dog to Franz), not paused, not already in the family. A **family** is the root drop plus its
  versions (`drop.copy_of` = the root's pick id; a version of a version points at the root), skipped picks not counted; at
  most **3** members (`MAX_FAMILY = 3`).
- **What a version is.** A new pick (url `owner-drop:<new id>`, platform `drop`, origin `owner`, status `approved`,
  `character_slug` = the new character, `source_id` = the root's full-clip source: nothing is uploaded again) whose drop starts
  at `checking` with `character_by: "owner"`, `copy_of`, `own_footage` copied from the root, and `requested.process` stamped.
  The normal free check then runs for the new character: his hooks, caption, first comment, gadgets and his own price.
- **A different section when there is one.** The check of a version first looks for a window that does not overlap the
  windows of the family's other members; when the clip has no such clean window it takes the best one as usual.
- **Two weeks apart.** When a family member is scheduled (Python `free_slot` and SQL `studio.free_slot`, kept in parity), no
  day within 13 days of another member's post (scheduled, posting, posted or needs_check, any account) is free.
- **The file stays** while any member is still to be made (`fetch._still_needed` already keeps a source another unfinished
  pick uses: a test pins it for versions).
- **Make it** stays per version, the owner's tap.
- **Entry points.** CLI `studio drop copy <pick> --character <slug>`; RPC `studio.copy_drop(pick_id uuid, character_slug
  text)` (migration 0015, the same rules, then the same dispatch as `request_job(..., 'process')`); terminal: "Use for another
  character" on a clip card, a menu of only the allowed characters.

## 5. Today
### 5.1 Studio at a glance (first block)
One row per live character plus **All** (a table on a wide screen, one card per character on a phone; tap a row: that
character's clips). Columns, in plain words:
- **Ready to make** (checked clips filed for him, no Make it yet), **Being made**, **To approve**, **Scheduled**, **Posted**;
- **Views**: today, 7 days, 30 days, all time (from `v_views_daily`, section 7); **Follows** gained in 7 days;
- **Next post** (day and time); **Runway**: ready clips ÷ his posts per week, "≈ 2 weeks" ("—" with no cadence);
- **Test status**: his Instagram channel's bar (not yet / on track / promote / at risk), from `v_channels.bar_status`;
- **Hits** (his hit rate) and **Best this week** (his most viewed video posted in the last 7 days, tap to play).
Under it a **views per day** chart for the last 30 days, one colour per character, with a period switch (7 days, 30 days,
all time). Before any views: "Views appear here after the first posts are measured (the stats pull runs daily)."

### 5.2 Make these
Per character, his top 3 `ready` clips by `score.total` (no score: after the scored ones, newest first): preview,
rank, score, reason, price. Each has a tick box; a bar at the bottom: **"Make 3 selected · 291 credits"**. Tapping it opens
a confirm with the total, the month's budget left and the cap, then calls `request_job(pick, 'make')` for each, one by one,
reporting each result. Nothing is ticked by default.

### 5.3 Approve these
The clips awaiting approval (the queue), newest first, each with its thumbnail, character, hook and a **Review** button
that opens the existing approval screen. Empty: "Nothing to approve. Finished videos land here."

## 6. Clips: By character (default view)
A section per live character: "Needs you" first (clips filed under him by the studio that wait for a character choice),
then his `ready` clips ranked 1, 2, 3... by score with the score, the reason, the price and a **Top pick** badge on the first
three; then making and done; blocked and failed folded into one closed row at the bottom ("3 clips can't be used: see why").
Each ready clip has a tick box (the same bar as 5.2) and "Use for another character" when a like-for-like character is
free. A clip that has versions shows them ("Also: Lenny, ready"). The **All clips** switch shows today's long list unchanged.

## 7. Data (migration 0015, schema `studio` only, additive)
- `studio.copy_drop(pick_id uuid, character_slug text) returns jsonb` (section 4).
- `studio.free_slot`: the family spacing (section 4), in parity with `studio.planning.free_slot`.
- View `studio.v_views_daily(character_slug, day, views, follows)`: per London day, the views and follows gained by that
  character's posts (the increase of each post's latest snapshot of the day over its latest snapshot before that day),
  readable by the terminal's role like the other `v_*` views.
- `v_tracker.drop_card` already carries `proposal.drop`, so `score`, `copy_of` and versions reach the terminal with no view change.

## 8. Marketing live
- The cloud check writes hooks, captions and first comments with the hit rules (section 3), so every new drop follows them.
- **Scraping (owner amendment 2026-10-07):** "let it scrape if necessary. I just don't want it to need the Mac running and
  browsing to get it done". Research data (trends, hits, engagement) may come from cloud scraping APIs (ScrapeCreators,
  Apify) called from the cloud; never through the Mac's browser, browser cookies or a logged-in session. Clip downloads keep
  their rule (one dropped or approved pick at a time).
- Weekly review: trends come from the social-data tools (`keyword_time_series`, `topic_posts`); `last30days` only once a
  ScrapeCreators key exists and only in its cookie-free setup (no X cookies, no browser).
- **Next build (not this one): a cloud hits job.** A scheduled GitHub workflow pulls the top TikTok and Instagram posts per
  niche keyword through ScrapeCreators (owner step: the account, 10k free calls, and the GitHub secret
  `SCRAPECREATORS_API_KEY`), stores them in schema `studio`, and the terminal shows them as "Worth saving" and trends: no Mac.
- The owner's step: merge the new allow entries into `.claude/settings.json` (the scheduled runs are unattended).
- Not in this build: every Reel also to Stories (needs the Postiz story setting and the AI label checked first).

## 9. Testing
- Python: the score (fixtures for each swap point, the total, the cap, no score on a block), the hit-rules block in the
  prompt, `potential` validation, recheck, copy rules (each refusal, the family cap, like for like, root resolution, the
  window preference, the source kept for a version), the family spacing in `free_slot` (parity cases with SQL).
- SQL: `copy_drop` and `free_slot` in the integration tests (`tests/integration`), `v_views_daily` on a fixture.
- Terminal: pure helpers (ranking, top 3, runway, overview totals, views per day by period, reuse targets, selection total)
  with Vitest; demo data for every new block; build green; checked at 375 px and desktop.
