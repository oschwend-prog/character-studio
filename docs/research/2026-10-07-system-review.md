# ODD EYES: independent system review, 7 Oct 2026

**What this is:** a step-back review of the whole studio against the owner's goal (his words, 7 Oct): "state of the art tech
... top quality and best info research autonomously and learning to get the best views over time. The engine is constantly
recalibrating to scan and find new videos, analyse them ...". Long term: fully autonomous, 10-12 characters, one per niche,
few approvals, money from brand placements, nothing that needs his Mac or a browser.

**How:** read-only. I read the rules, the roster, the roadmap, the v3 spec and plan, the three research docs, the channel
strategy, the module docstrings, every workflow, both skills, the migration headers, `config/scan.json`, the refs.json files,
the scheduled-task list and the recent GitHub runs. I ran web searches for the state of the art (sources at the end). No
code, config, docs or git state was changed; no generation, publishing or paid tool was called. This file is the only output.

**Labels:** **[E]** = evidence (a file:line, a command result or a named source). **[I]** = my inference.
**Effort:** **S** = config, text or a small function (hours). **M** = a new CLI command, job or client (1-3 days). **L** = a
new subsystem (a week or more).

**Note on timing:** while I was reviewing, a new local commit landed (`7a5b9f1`, "the hits job files its best hits as drops
each day"). It is included below.

---

## Summary (read this first)

1. **Verdict:** the *make and post* half is strong, safe and mostly in the cloud; the *find, measure and learn* half is not closed yet, so the engine cannot "recalibrate" today.
2. Finding is stalled: the daily scan needs vidIQ (3 credits until 4 Nov) and the cloud hits job is still a plan. Measuring is thin: no skip rate, follows or non-follower reach in the cloud.
3. Learning is cut off: every drop is tagged with the same format and hook pattern, so the binding bars cannot tell anything apart. The weekly review's lessons stay on the Mac and nothing in the cloud check reads them.
4. The daily run and the weekly review are Claude Desktop tasks on the Mac (today's run fired 70 minutes late). The health check raises an alarm whenever the Mac sleeps.
5. **The 5 most important changes, in priority order:**
6. **(1) Measure properly from the first post (M).** Pull Instagram's own insights from the cloud (skip rate, follows, follow type, reach, watch time, followers per day). Send the per-post AI label (`is_ai_generated`, in Meta's API since 22 Jun 2026). Tag every clip with a fixed vocabulary: hook pattern, caption line-1 pattern, first-comment kind, trend stage, sound, length, clip score, hit-rules version and reuse family.
7. **(2) Move the brain off the Mac (M).** A pure-Python `studio daily` workflow (recovery, purge, sweep, hits, run log). The weekly review as a GitHub workflow: Python numbers plus a headless Claude write-up that opens a pull request. The owner already runs this pattern in `crypto-tool` (`alphaloop-content.yml`).
8. **(3) Close the learning loop with simple, honest methods (M).** Pre-register a test of the clip score before it steers spend. Run a bandit over the free choices (which hook, which caption line 1, which first comment). Version `config/hit_rules.md`, and change it only by a weekly pull request that carries the evidence (n ≥ 5). Use the owner's taps as labels.
9. **(4) Search wider than keywords (M).** Add TikTok's trending feed and popular videos, rising sounds (then "videos using this sound"), Instagram trending reels and rising creators, all through ScrapeCreators. Classify the results from their text with Gemini. Each week, group them into clusters and report the strong ones no character covers: candidate niches for the next character.
10. **(5) Quality bake-off when the credits return (S-M, about 600-900 credits).** Test Genjutsu Object swap, Kling 3.0 Motion Control and Wan 2.2 Animate (replacement mode) on the same 3 clips, the tall Franz included. Add two cheap automatic checks: identity similarity to the master, and a Gemini pass over the whole video, not just 6 frames.
11. **Fix this week, no credits needed:** cloud code is 7 commits behind local (the default branch is `build/slice1` and the commits are unpushed). The kill bar can never fire while no TikTok account is connected. The Instagram originality guard reads a field nothing writes. The dispatch token can write code. A wide-open `Bash(yt-dlp:*)` allow sits uncommitted in `.claude/settings.json`.
12. **Cost:** about 130-160 credits per posted video, so $5-8 at $0.033-0.05 a credit. At 10-12 characters posting 5 a week that is about 34-41K credits, about $1.1-2.0K a month, plus about $150-250 for the rest of the stack. Even 3 characters on the week-3 rhythm outgrow the 6,000 cap (about 8-10K needed).
13. **Biggest risk:** auto-filing third-party clips (`7a5b9f1`) plus reusing one clip on up to 3 accounts in one Accounts Centre. Instagram now judges originality per account per month and shows the original instead of near-copies. Keep a growing share of Recreates and own footage, which is also what brands will pay for.
14. **Coherence:** the docs have drifted. Gallery backups, the eye end beat and Franz's crown are still in the skill. CLAUDE.md's new auto-file line sits next to its "never download on the automation's own initiative" line. The "three characters fit under 6,000" credit maths is wrong. Section G lists 14 items.
15. **Sequence:** this week, measurement, tags, the cloud daily job, the hits job, the drift fixes and the owner's decisions. Weeks of 12 and 19 Oct, the bake-off, the weekly review in the cloud, the bandit, TikTok. Nov-Dec, score validation, then automatic Make under a price limit, niche discovery, a growing owned-footage share.

---

## A. The loop: does find → check → make → post → measure → learn → find exist?

### A1. Where each step runs today

| Step | Runs where | State | Evidence |
|---|---|---|---|
| Find: the owner's own clips | Terminal upload or link to Supabase, then GitHub Actions | **Cloud, works** | `studio/drop.py` docstring; `studio-drop.yml` |
| Find: the owner's iCloud folder | macOS LaunchAgent every 5 min (`com.oddeyes.clip-sync`) | **Mac only** | `studio/clipfolder.py` docstring; CLAUDE.md "Clips folder" |
| Find: the scan | Daily run on the Mac, through vidIQ | **Stalled**: vidIQ has 3 credits until 4 Nov; the search needs 5 | [E] hit-patterns §"Limits"; daily-run `SKILL.md:46` |
| Find: cloud hits job | Planned (`studio-hits.yml`, plan Task 6); now also auto-files 3 a day per character (`7a5b9f1`) | **Not built** | v3 plan Task 6; no `studio/hits.py` |
| Check and score | GitHub Actions: ffmpeg analysis + Gemini 3.8 Flash deconstruct + `drop_score` | **Cloud, works** (score uncommitted) | `studio/drop.py:430`; `git diff --stat` |
| Check: a link the cloud cannot fetch | State `waiting`, retried by the **Mac** daily run | **Mac only** until the ScrapeCreators fallback | [E] `studio/drop.py:17` |
| Choose what to make | The owner taps Make it | Manual by design (launch phase) | daily-run `SKILL.md` "Launch phase" |
| Make + QA + master | GitHub Actions (Higgsfield API, Gemini frame QA, ffmpeg) | **Cloud, works** | `studio-drop.yml`; drop.py "Make" |
| Approve | The owner (autopilot per account after 6 approved posts) | Manual by design | `docs/launch/go-live.md:94`; `studio/clips.py:343` |
| Post | GitHub Actions via Postiz; pg_cron timer (0014) as primary trigger | **Cloud, works**; a `repository_dispatch` publish already ran at 20:50 UTC on 7 Oct, so 0014 looks live although CLAUDE.md still lists it as pending | [E] `gh run list` |
| Measure: counts | GitHub Actions `metrics pull` (Postiz: views, likes, comments, shares, saves) | **Cloud, partial** | [E] `studio/metrics.py:111-117` |
| Measure: skip rate, watch time | vidIQ ingest inside the **weekly review on the Mac** | **Mac only**, and keys still "VERIFY" | [E] `metrics.py` "Instagram insights"; weekly-review step 2 |
| Measure: followers, follows, non-follower reach | Nothing writes them | **Missing** | [E] `models.py:236-237` fields; only `review.py` reads `non_follower_pct` |
| Learn | Weekly review on the Mac: verdicts by code, playbook written, "the commit stays local" | **Cut off** | [E] weekly-review `SKILL.md:22-23` |
| Learning reaches the next choice | The cloud check reads the bible voice, traits and `config/hit_rules.md`; nothing reads `playbook.md` in the drop path | **Not wired** | [E] `studio/gemini.py:94, 489`; `playbook.md` only in daily-run `SKILL.md:68` (steps 3-9, skipped in launch phase) |

### A2. What breaks the loop

- **[E] The Mac is still in the loop three times.** The daily run and the weekly review are Claude Desktop scheduled
  tasks (`studio-daily-run` 08:00, `studio-weekly-review` Mon 09:00). Today's daily run started at 09:17 for an 08:00
  slot. The iCloud folder agent is a LaunchAgent. Unfetchable links wait for the Mac.
- **[E] The health check is tied to the Mac.** `studio health` fails when no daily run finished in 26 h
  (`studio/health.py:54`). A sleeping Mac means an alarm email. In launch phase the Mac run does very little, so the
  alarm watches the wrong thing.
- **[E] The owner has already solved this elsewhere.** His own scheduled-task list shows four jobs moved to GitHub Actions
  after "the local run missed its window (Mac asleep, fired 5h late)". `crypto-tool/.github/workflows/alphaloop-content.yml`
  runs `claude -p` headless with `CLAUDE_CODE_OAUTH_TOKEN`. The same pattern fits here.
- **[E] Cloud code is behind local code.** GitHub's default branch is `build/slice1`. Local is 7 commits ahead and has
  uncommitted Task 1 work (the score, the hit rules, Franz's new voice). The cloud check runs what is pushed, so none of
  that is live yet.

### A3. What has to move to the cloud, and how

| Job | Today | Move to | How | Effort | Unlocks |
|---|---|---|---|---|---|
| Daily run (launch phase) | Claude on the Mac | **`studio daily`**, a pure-Python workflow at 07:30 London | One CLI command that runs, in order: budget recovery (open reservations older than 2 h, checked against the Higgsfield API job status), `source purge --pending`, `drop sweep`, `hits pull` (+ auto-file), and `run log --kind daily`. In launch phase no judgement is left: Gemini already writes the hooks and captions in the cloud | M | The health check means something; no Mac |
| Weekly review | Claude on the Mac with the vidIQ and LunarCrush MCPs | **`studio-weekly.yml`**: Python numbers + headless Claude write-up | Step 1: `metrics pull` + a new `metrics ig-pull` (Instagram API, A/B1) + `review data`. Step 2: `claude -p` reads the JSON and writes the report, the playbook and a proposed `hit_rules.md` change, then opens a **pull request** (`gh pr create`). Merging the PR is the owner's approval. Trend reads come from the `studio.hits` table, not from MCP tools | M | Learning reaches the cloud check; the owner approves with one merge |
| Unfetchable links | Mac yt-dlp | ScrapeCreators single-post fallback | Already in plan Task 6 | S | No `waiting` state for the Mac |
| iCloud folder | LaunchAgent | **iOS Shortcut** "Send to ODD EYES" in the Share Sheet | The Shortcut posts the file to a Supabase Edge Function that calls `add_drop` and stores the file in `sources/owner/`. Keep the LaunchAgent as an optional extra | S-M | Saving a clip from the phone works with the Mac off |
| Anything needing Claude judgement later | — | Headless Claude in Actions, or a **Claude Code routine** | Routines run on Anthropic's cloud on a schedule with granted MCP connectors (research preview since Apr 2026, [WEB: makerkit, datacamp]). Prefer Actions for now: same secrets, same logs, the owner's own precedent | — | — |

**[I] The rule of thumb:** deterministic steps in Python (cheap, testable, no model drift). Judgement in Gemini inside
the check, which already works. Claude only for the weekly narrative and for rule proposals, always through a PR.

---

## B. Learning and recalibration

### B1. Do our own results change future choices today? No.

- **[E] Every drop gets the same tags.** `studio/drop.py:1018-1019` writes `format_id: "drop_object_swap"`,
  `hook_pattern: "drop"`, `seamless_loop: False` and `audio_arm: "original_audio"` for every drop. The launch phase makes
  only drops. So the binding format bar (keep at median outlier_x ≥ 1.5 over ≥ 5), the hook bar (2 hits in 10 uses) and
  `feature_lifts` (`studio/review.py:160`) see one format and one hook. They can never separate a winner from a loser.
- **[E] The clip score is not on the clip.** `drop.score` lives in the pick's `proposal`, not in `clip.features`, and
  `feature_lifts` reads only `REQUIRED_FEATURES` (`review.py:163`). Nothing can test whether the score predicts views.
- **[E] The score weights are a guess.** `total = round(10 × (0.6 × potential + 0.4 × swap))`. `potential` is one
  Gemini judgement (`drop.py:430-450`). The 5 Oct audit's own rule was "never let an unvalidated score steer spend"
  (audit #20). The score now ranks what the owner is invited to pay for.
- **[E] The lessons do not travel.** Weekly-review step 7 commits `playbook.md` locally and never pushes
  (`SKILL.md:23`). The drop prompt never reads `playbook.md`. Pick-weight calibration is "a proposal for the owner; apply
  nothing" (`SKILL.md:21`). `config/hit_rules.md` changes only by hand, and clips do not record which version they were
  made under.
- **[E] Key outcome data is missing** (A1): skip rate and watch time only through the Mac's vidIQ ingest, follows and
  non-follower reach never.
- **[E] Two bars are inert.** The character **kill** bar needs a median "on BOTH platforms" (`review.py:18, 92`), and no
  character has a TikTok account connected (every refs.json: `tiktok.postiz_integration_id: null`). So no character can
  be killed, which breaks the roadmap's "one new character a month, under the kill bar replaced". The **Instagram
  guard** reads `non_follower_pct`, which nothing writes, while every account sits at `dropin_share: 1.0`.

### B2. The data to capture (fix first, it cannot be recovered later)

**Per clip, set at creation** (extend `_features` in `drop.py` and `REQUIRED_FEATURES` where it should be binding).
Fixed vocabularies, so values repeat often enough to reach n ≥ 5:
- `hook_pattern`: one of the 7 names in hit-patterns §4.3 (`ego-claim`, `when-relatable`, `false-premise`,
  `understatement`, `mid-deal`, `trend-label`, `myth-bust`). Gemini labels each of its 3 hooks; the clip records the
  one used (`hook_index`, and `hook_by: gemini|owner`).
- `caption_line1_pattern` (`label-first` / `joke-first`), `first_comment_kind` (`vote` / `request` / `question`).
- `trend_name`, `trend_stage` (`rising` / `peak` / `fading` / `classic`), `days_since_trend_peak`; `sound_name`,
  `sound_rising` (bool).
- `length_s`, `classic`, `people_in_frame`, `camera`; `score_total`, `score_potential`, `score_swap`.
- `hit_rules_version` (a hash or a number in the file header), `family_id` and `version_index` (reuse), `source_kind`
  (`owner_saved` / `auto_filed` / `own_footage` / `recreate`), `series` and `episode`.

**Per post, from Instagram's own API (cloud):** Meta added Reels skip rate (15 Apr 2026), follow type and follows/unfollows
(23 Jan 2026), and insights via Instagram Login (Aug 2026) [WEB: Supermetrics changelog]. Media follows
(`media_follows`) and `media_reel_skip_rate` are named in practitioner docs [WEB: inro]. **Verify the exact metric names
on one post** before building. Pull at 1 h, 24 h, 72 h, 7 d like `metrics pull` does. Also store account followers once a
day.

**Per owner action:** Make it, Not for us, dismiss, reject at approval. These are free labels of his taste.

### B3. The simplest sound way to make the scoring learn (small samples, binding bars)

**[I] The volume sets the method.** Weeks 1-2: 3 Instagram accounts × 3 posts = 9 posts a week. From week 3: 15 a week
(if credits allow, see E). That is about 100 measured posts by the end of November. `outlier_x` needs 3 earlier 7-day
figures per account, so the first values arrive around day 14. This is far too little for machine learning, but enough
for four simple tools, layered:

1. **Keep the pre-registered bars for keep/kill** (unchanged, binding). They work once the tags differ (B2).
2. **Test the clip score before it steers money (S).** Pre-register now, before any data: after 30 posts with
   `outlier_x`, compute the Spearman rank correlation (ρ) of `score_total` with `outlier_x`, and also of `potential` and
   `swap` separately. ρ ≥ 0.25 → keep the weights. Below → the terminal labels the score "unproven", and the weights are
   refit once (rank regression on the two parts) and proposed by PR. This is the audit's #20 rule applied to our own score.
3. **A bandit over the free choices (M).** The hook, caption line 1 and first comment cost 0 credits to vary. Each has a
   few arms (7 hook patterns, 2 caption patterns, 3 comment kinds).
   - The method is Thompson sampling: each arm keeps a success count; at each post you draw from each arm's odds and use the best draw. Choices that are working get used more, but every option still gets tried.
   - A success is a post above its account's median views at 72 h, so you get an answer in 3 days instead of 7.
   - Keep a floor of 15% for every arm. Store the arm state in a small table `studio.arms`.
   - Gemini already writes 3 hooks, so the bandit only picks which one goes on screen.
   - With 15 posts a week, a 3-arm choice settles in about 6-10 weeks [I].
   - Once an account is eligible, Instagram Trial Reels give a clean A/B on the same video (audit #4).
4. **Rules change by evidence and PR, never silently (S).**
   - Give `config/hit_rules.md` a version and numbered rules.
   - The weekly cloud job computes each rule's lift (median outlier_x of clips that followed it vs those that did not, n ≥ 5 on each side). Claude drafts a PR that promotes, rewords or retires a rule with the numbers in the description.
   - Merging the PR is the owner's approval. This is the "constantly recalibrating" engine, with a paper trail.
5. **Later, at about 150+ posts (M):** a hierarchical Bayesian regression of log views on a handful of tags, pooled
   across characters (the `pymc` skill is installed). It shrinks noisy per-character results toward the studio average,
   which is the right behaviour at small n.

**What the loop should recalibrate, and what it should not:**

| Lever | Learns from | How | Owner approval |
|---|---|---|---|
| Clip score weights | Score vs outlier_x (B3.2) | PR after the pre-registered test | Merge |
| Hook / caption / comment choice | Bandit (B3.3) | Automatic within arms the owner approved | None per post |
| Hit rules (the Gemini rubric) | Rule lifts (B3.4) | Weekly PR | Merge |
| Trend keywords and categories | Hits that get tapped, pass the check and win (C3) | Weekly PR to `config/scan.json` `hits.keywords` | Merge |
| Which clips to make | Score + owner taps | Ranking now; automatic Make later under a price limit (sequence) | Per video now |
| Posting times | — | **Not learned**: the slots are the owner's | — |
| KPI bars | — | **Never**: binding | — |

---

## C. Scanning breadth

### C1. Today

- **[E] The daily scan is stalled until 4 Nov.** One vidIQ outlier search per weekday, the live characters in turn, one
  theme each; vidIQ has 3 credits.
- **[E] The weekly review's LunarCrush calls are thin.** "limited data mode", at most 4 posts per query, 7 of 25 calls
  failed (hit-patterns "Limits").
- **[E] The planned hits job is keyword-per-character.** At most 3 keywords per live character, TikTok keyword search,
  Instagram reels search, plus Instagram trending once a day, with a 25-credit daily cap (v3 spec §10). It is a good
  start, but it only finds what we already know to ask for.

### C2. How to find general hits and new categories (within the rules)

All through ScrapeCreators' API from GitHub Actions: metadata only, no Mac, no browser, no cookies. Clips still enter one
at a time through the drop fetch.

| Layer | What it adds | ScrapeCreators source | Daily calls (12 characters) |
|---|---|---|---|
| 1. Character keywords | What fits each niche (planned) | TikTok keyword search, IG reels search | ~72 |
| 2. **Trending feeds** | General hits nobody searched for | TikTok `get-trending-feed` (GB, US), TikTok popular videos, IG trending reels [WEB: ScrapeCreators] | ~6 |
| 3. **Rising sounds** | The sound is the trend (rule S2 automated) | Popular songs, song details over time, then "TikToks using this song" sorted by likes [WEB: ScrapeCreators] | ~10-20 |
| 4. **Rising creators** | Small accounts with big reach in our niches (rule P3) | Popular creators filtered by country and engagement [WEB: ScrapeCreators] | ~2 (weekly) |
| 5. **Events calendar** | "Looks live" (PFW, Halloween, finals, Christmas) | A small `config/events.yaml`: keyword boosts 7 days before | 0 |

- **Classify from text, cheaply.** For each new hit, one Gemini Flash call on its text: caption, hashtags, sound,
  duration. It returns a category, which character could take it (like for like), "looks solo / looks multi-person" and
  "another creator's own character skit" (rule P6). The thumbnail is stored and never fetched, which keeps today's rule.
  Ask the owner whether fetching a thumbnail for classification is acceptable; it would improve the solo/multi guess a
  lot.
- **Find new categories.** Weekly, embed the week's hits (Gemini embeddings on caption + hashtags + sound) and cluster
  them. Report clusters with high median reach (views ÷ followers) and growth that **no live character covers**. Those
  are niche candidates for the "one new character a month" funnel, now chosen with data instead of taste alone.
- **Retire dead keywords.** A keyword whose hits get no owner taps and no passing checks in 2 weeks is dropped by the
  weekly PR. Trending hashtags and sounds from layers 2-3 propose new ones.
- **Cost:** about 90-110 calls a day, about 3,000 a month. That is about $6 a month at the $47 / 25,000-credit pack, plus
  1-2 credits per single-post download. Raise `hits.daily_credit_cap` from 25 to about 120.
- **[I] Auto-filing (`7a5b9f1`) needs a label and a comparison.** Tag auto-filed clips `source_kind: auto_filed`, and
  have the weekly review compare their check pass rate and results with the owner's own picks. If they do no worse,
  autonomy grows with evidence. If they do worse, lower the per-character cap.

---

## D. Quality

### D1. What is good

- **[E] Genjutsu Object swap fits the "reads as filmed" rule.** It keeps the original shot, light and camera and replaces
  one element. It launched on 1 Sep 2026, takes 3-30 s references and up to 40 reference images [WEB: Higgsfield,
  creativeainews].
- **[E] The automated checks are strong.**
  - Free local analysis: cuts, beat, best window.
  - A section kept clear of text and watermarks.
  - Gemini deconstruct, with a second chance on rule breaks.
  - Frame QA: eyes, leftover people, watermark.
  - One automatic re-roll, then stop.
  - Masters at fixed technical specs: −14 LUFS, true peak.
  - Per-character style kits.
- **[E] Gemini 3.8 Flash (the default model) is current.** Google's Flash tier launched 2 Sep 2026, with video input
  [WEB: bibigpt, ai.google.dev].

### D2. Gaps and better options

| Gap | Evidence | Recommendation | Effort | Unlocks |
|---|---|---|---|---|
| One generator, never compared | Every video goes through Genjutsu; no bake-off on record | **Bake-off on 3 clips** (one dog, one person, one tall-Franz-for-a-person). Genjutsu Object swap vs **Kling 3.0 Motion Control** (Mar 2026, several reference images for face consistency [WEB: atlascloud, beehiiv]; Higgsfield already lists `kling3_0`) vs **Wan 2.2 Animate replacement mode** (open weights, Apache 2.0, a relighting LoRA for scene light [WEB: comfy.org, runware]). Judge blind: owner + Gemini rubric (identity, anatomy, eyes, motion, background intact) | S-M (~600-900 credits) | A second provider (no single point of failure) and the best tool per clip type |
| Tall Franz replacing people | Genjutsu "has answered a dog-for-person swap by adding the dog and keeping the people" (`AI_INFLUENCERS.md:45`) | Include it in the bake-off. Motion transfer from a still of tall Franz (Kling MC / Wan animation mode) may keep his short-legged body better than a swap that follows human legs [I] | in bake-off | Franz's whole "replaces people" lane |
| The odd eyes rarely show | Full-body 1080×1920 frames show eyes at a few pixels; no end close-up since 5 Oct; "the odd eyes don't read at thumbnail size" (`AI_INFLUENCERS.md:182`) | Make the **cover image** an eye close-up with the series title (Postiz passes thumbnails, audit #9). It does not touch the "ends on the dance" rule. For human characters, an optional deterministic iris recolour (face landmarks with iris points) when the face is large enough [I] | S (cover), M (recolour) | The brand signature becomes visible on the grid |
| Frame QA sees 6 still frames | `qa frames --n 6` (daily-run `SKILL.md`) | Also send Gemini the low-res **whole video** for flicker, limb pops and identity drift. Add a numeric **identity score** (face-embedding similarity to the master for Reginald and Lenny; an image-embedding similarity for Franz), with a threshold set from the first 10 approved clips | S-M | Fewer bad clips reach the owner; QA learns a threshold |
| No upscale or detail pass | Genjutsu output is the master | Test **Topaz Starlight Precise 2.5** or Astra 2 on 2 clips (diffusion restoration of faces, fur and fabric, API available [WEB: magnific, fal]) or Higgsfield's `upscale_video`. Use it only on classics if it wins | S | Sharper faces on the clips that matter most |
| Signature move missing from swaps | Object swap keeps the clip's moves; the signature move "would be a short 1-2 s tag, at extra cost" (`AI_INFLUENCERS.md:184-185`) | Render each character's signature move **once** (the Wiggle, the Glove Tug, the Tie Snap) and reuse it in the style kit's `entrance` | S (~150 credits each, once) | Every clip becomes "a Franz" at no extra cost per video |

---

## E. Tech choices and cost

### E1. Keep, add or replace

| Piece | Verdict | Why |
|---|---|---|
| Gemini 3.8 Flash (check, frame QA) | **Keep** | Current, native video + audio, pennies per clip [E] |
| gpt_image_2_5 (stills) | **Keep** | The owner's standard; the stills are a small cost |
| Higgsfield Genjutsu | **Keep + add a second path** | Strong for swaps; but the sole generator and the holder of every identity asset. The bake-off picks a backup (Kling via Higgsfield, or Wan Animate via fal/Runware) |
| vidIQ | **Demote** | 3 credits until 4 Nov; its unique value (outlier vs the creator's median) is replaced by reach = views ÷ followers |
| LunarCrush | **Drop for discovery** | Limited mode, 4 posts a query, many errors [E]; the 5 Oct audit already said skip it |
| ScrapeCreators | **Add (planned) and widen** (C2) | Cheap, cloud, metadata; also the fetch fallback |
| Postiz | **Keep, Pro tier at 10-12 characters** | $49/month for 30 channels [WEB: Postiz docs]. Gap: Instagram's per-post `is_ai_generated` (in Meta's API since 22 Jun 2026 [WEB: Meta changelog]) is not sent by our code and was not sent by Postiz on 5 Oct (audit #8). Verify Postiz today; if still missing, upstream a patch (AGPL) or post Instagram directly through the Graph API |
| Instagram Graph API (own Meta app) | **Add** | The only cloud source for skip rate, follows, follow type, watch time and followers (B2). Instagram Login, own professional accounts. Long-lived tokens need a refresh every 60 days: automate it |
| Supabase | **Keep, own project later** | It shares the "faceless-youtube" project with another app [E: migration headers]. One outage or bad migration hits both. Move to its own Pro project before 10 characters |
| GitHub Actions | **Keep, budget minutes** | See E3 |
| Vercel | **Keep** | If the terminal is on the Hobby plan, Vercel's terms limit Hobby to non-commercial use [I: check the plan] |
| Claude (headless in Actions) | **Add** for the weekly write-up and rule PRs | The owner's own pattern; runs on his subscription token |

### E2. Cost per video and per month

**Assumptions:**
- **[E] Credit price:** $0.033-0.043 on Higgsfield Ultra [WEB: krea, creatify]; the repo assumes about $0.05 (`channel-strategy.md` §6).
- **[E] Credits per video:** Drop-in `ceil(s × 11) + 3`, so 102 credits for 9 s and 152 for a 13.5 s classic; a Recreate is 160 (CLAUDE.md).
- **[I] Mix from week 3:** 3 Drop-ins + 2 Recreates a week (`roadmap.md:20-23`), which averages about 130 credits a video.
- **[I] Waste:** about 20% (one automatic re-roll, owner rejections), which brings it to about 156 credits per posted video.

| | Credits | $ (0.033-0.05 a credit) |
|---|---|---|
| Per posted video | ~156 | **~$5.10-7.80** |
| Per character per month (5 a week ≈ 21.7 posts) | ~3,400 | ~$110-170 |
| 3 characters per month | ~10,200 | ~$340-510 |
| 10-12 characters per month | ~34,000-41,000 | **~$1,120-2,030** |

| Rest of the stack per month at 10-12 characters [I] | $ |
|---|---|
| Gemini (checks of ~250 made + ~500 auto-filed clips, frame QA) | ~10-25 |
| ScrapeCreators (C2 + single-post downloads) | ~10 |
| Postiz Pro | 49 |
| GitHub Actions above the free minutes (E3) | ~20-60 |
| Supabase Pro + storage | ~25-50 |
| Vercel Pro (if needed) | 20 |
| **Total stack** | **~$135-215** |

**[I] All-in:** about $1.3-2.3K a month, about $5.5-8.8 per posted video. The roadmap's brand prices ($200-400 a placement
at 10K followers, 1 sponsored post in 4-5) give about $0.8-1.6K a month per character at 10K followers. So two
characters with steady deals carry the studio. Revenue follows the one or two breakouts, so the kill bar must work.

**[E] The cap maths in the roadmap is off.** `roadmap.md:25` says "three fit under the 6,000 cap" at 91 credits a video.
With the planned 2 Recreates a week and normal waste, three characters on Mon-Fri need about 8-10K. Raise the cap (or
the plan) before week 3, 19 Oct, or the plan will stop mid-week.

### E3. GitHub Actions minutes [I]

A rough count of today's jobs:
- publish: 26 scheduled runs a day plus dispatches, about 1.5 min each, about 1,200 min a month;
- metrics: about 240 min;
- health: about 240 min;
- drop sweeps: about 360 min;
- CI: about 3 min a push;
- each make polls Higgsfield **inside the job for up to 25 minutes** (`drop.py:56`).

That is about 4,000 min a month now and about 10,000 at 12 characters. The private-repo free allowance is 2,000-3,000 min
a month, shared with the owner's other private repos, which also run nightly jobs. If the account's Actions spending limit
is $0, jobs stop when the minutes run out, and **publishing stops with them**. Check the billing page and set a budget
(S). Make the make job submit and exit, with the sweep polling (S-M). That roughly halves the minutes.

---

## F. Risks

| # | Risk | Evidence | Severity | Mitigation | Effort |
|---|---|---|---|---|---|
| 1 | **Instagram originality, per account per month** | Since 30 Apr 2026 Meta judges what an account posts over a month. Mostly reposted or "not meaningfully transformed" means no recommendations to non-followers. Near-copies are matched, and the **original is shown instead** of the copy [WEB: Tubefilter, PetaPixel, Planoly]. Our Drop-ins keep the original's background, camera and sound | **High** | Grow the share of Recreates and own footage, which the roadmap already plans for week 3. Give the guard real data (B2). Watch non-follower reach per account weekly | M |
| 2 | **Reuse across accounts in one Accounts Centre** | v3 spec §4: one clip, up to 3 characters, 14 days apart; a different section "when there is one" | **High** | Cap families at **2** until per-account reach data shows no penalty. Require a different section (not optional). Prefer reuse of classics, where many versions exist anyway [I] | S |
| 3 | **Auto-filing third-party clips at scale** (`7a5b9f1`) | About 65 clips a month for three characters; the fetch includes ScrapeCreators' hosted download | Medium-high | Keep the Make-it tap; tag `auto_filed`; purge after posting (exists); log takedown and copyright notices per account and treat 2 in 30 days as a kill-switch trigger [I] | S |
| 4 | **Copyright in input footage** | Higgsfield grants rights in outputs, not inputs (audit #1). Brand deals need "a Recreate or own footage, never a swap into someone else's clip" (`roadmap.md:121-122`) | High for money | Build the owned inventory now: Recreates, the signature-move library, owner-filmed clips | M |
| 5 | **Instagram AI labels** | Per-post `is_ai_generated` exists since 22 Jun 2026 [WEB: Meta]; not in `studio/`. The profile label for AI people has applied since 31 Aug 2026 (`go-live.md:13`) | Medium | Send the per-post flag; add "AI info shows" to the go-live check | S-M |
| 6 | **The kill bar cannot fire** | `review.py:18, 92` + no TikTok accounts | Medium (cost) | **Owner decision now, before any 7-day data** (so it is not a renegotiation): an Instagram-only kill rule until TikTok is connected, or connect TikTok before week 3 | S |
| 7 | **The guard has no input** | `non_follower_pct` never written | Medium | Instagram API (B2) | M |
| 8 | **Credits booked by estimate** | "the API reports no cost: the estimate ... is booked" (`drop.py:57`); strand B spend is outside the ledger (C12) | Medium | A daily reconciliation of the ledger against the Higgsfield balance or transactions; alert at more than 5% gap | S-M |
| 9 | **The dispatch token can write code** | `repository_dispatch` needs a token with Contents: write [WEB: GitHub docs]; it lives in Supabase Vault | Medium | Switch `request_job` and `publish_tick` to `workflow_dispatch`, which needs only **Actions: write** [WEB: GitHub docs]. A database leak then cannot push code | S |
| 10 | **Over-wide local allow** | `.claude/settings.json:30` (uncommitted): `Bash(yt-dlp:*)` lets any yt-dlp call through, against "no yt-dlp of your own" (daily-run `SKILL.md:13`). `bin/studio source fetch` runs yt-dlp itself and does not need it | Medium | Remove the line | S |
| 11 | **Single points of failure** | The Mac (A); Higgsfield; Postiz; GitHub's scheduler (skipped 2 h on 7 Oct, `0014` header); one Supabase project shared with another app; one Gemini key | Medium | A (cloud); a second generator (D); `workflow_dispatch` + pg_cron for every timed job; own Supabase project | M |
| 12 | **Cost runaway** | The cap, the kill switch and reserve-before-spend are good [E]. The risks are the cap rising to ~40K without per-character limits, and zombie characters (risk 6) | Medium | A per-character monthly credit limit in `studio.settings`; a cost-per-1K-views line per character in the weekly review | S |
| 13 | **Account bans** | Several AI-character accounts in one Accounts Centre, posting via the official API | Low-medium | No cross-account engagement automation (already a rule). Space crossovers. Keep each account's own voice and content | — |

---

## G. Coherence: drift between docs, plan and code

| # | Where | Says | Conflicts with | Fix |
|---|---|---|---|---|
| 1 | CLAUDE.md:19-20, daily-run `SKILL.md:19, 60`, `scan.json` `access`/`free_sources_daily`, `channel-strategy.md:22` | Genjutsu gallery backups; "Genjutsu gallery first" | Owner 7 Oct (memory `feedback_no_gallery_backup`): never file gallery backups | Remove Part B and the "gallery first" lines |
| 2 | CLAUDE.md:24 vs :25 | "the daily cloud hits job may file its best new hits as drops on its own" | "Never: download clips from TikTok/Instagram on the automation's own initiative" | Reword :25 so the two read as one rule (auto-file is the one allowed exception, with its cap) |
| 3 | daily-run `SKILL.md:21` | "Transform: ... the ODD EYES end beat" | No end close-up, glint or sting since 5 Oct (CLAUDE.md:17) | Delete the phrase |
| 4 | daily-run `SKILL.md:108` | Franz QA: "four paws, no human limbs ... the tiny gold crown" | Tall upright Franz; cap, not crown (owner 7 Oct) | Rewrite the Franz QA line |
| 5 | `channel-strategy.md:26, 62` | "ODD EYES close-up end beat"; Sunday 18:00 Trial Reels | No end beat; slots are Mon-Fri only | Mark as superseded |
| 6 | `AI_INFLUENCERS.md:10` | B characters "are not seeded ... no `characters/lenny` or `characters/franz` folders" | Both are live with refs.json and Instagram connected | Update §0 and §7 |
| 7 | `roadmap.md:3, 27-66` | "get Biscuit + Reginald running"; the Outsider as character 3; the Singer keeps "the eye-glint end beat" | Roster of 6 Oct; no end beat | Archive the old sections under a dated heading |
| 8 | `roadmap.md:25` | Three characters fit under 6,000 | E2 maths: about 8-10K | Correct |
| 9 | CLAUDE.md "Pending (publish timer)" | 0014 never applied | A `repository_dispatch` publish ran at 20:50 UTC on 7 Oct | Check `cron.job` and update the line |
| 10 | Cloud vs local | Default branch `build/slice1` | Local is 7 commits ahead + uncommitted Task 1 | Push after Task 1's review; add a "pushed?" line to the golive check |
| 11 | `refs.json` (franz) | Handle `franz.unimpressed` | Happy show-off (7 Oct); `AI_INFLUENCERS.md:49` says rename to `franz.dachshund` | Owner step: rename, then re-seed |
| 12 | Two hook writers | The cloud check (Gemini, `hit_rules.md`) | The daily run's `viral-hook-creator` (`FOUNDER_CONTEXT.md` → hit-patterns doc) | `config/hit_rules.md` is the one source; `FOUNDER_CONTEXT.md` points to it |
| 13 | Feature tags | Playbook §5.1 lists about 30 tags; the weekly review promises lifts per format and hook | Drops write constants (`drop.py:1018`) | B2 |
| 14 | Instagram guard, kill bar | Binding rules in channel-strategy §3.3 and `review.py` | No data (guard), no TikTok (kill) | F6, F7 |

---

## Proposed sequence

### This week (8-11 Oct): no Higgsfield credits needed

| # | Do | Effort | Unlocks |
|---|---|---|---|
| 1 | Finish and review Task 1, then **push** (cloud runs it) | S | The score, the hit rules and Franz's voice go live |
| 2 | **Tags (B2)** in `drop._features`: hook pattern from Gemini's labels, the score parts, the hit-rules version, family, source kind, trend stage, sound, length | S | Every post from now on can be learned from |
| 3 | **Owner decisions** before any 7-day data: an Instagram-only kill rule (or TikTok first); a reuse family cap of 2 or 3; the auto-filing cap; a thumbnail fetch for classification yes/no; raise the credit cap for week 3 | S (owner) | The funnel and the budget work as designed |
| 4 | **Instagram API insights client** (own Meta app, Instagram Login): skip rate, follows, follow type, reach, watch time, daily followers; verify metric names on one post. Send `is_ai_generated` per post (Postiz or direct) | M | Guard, floors, learning; label compliance |
| 5 | **Security and ops:** `workflow_dispatch` with an Actions-only token; remove `Bash(yt-dlp:*)`; check Actions billing and set a budget | S | Lower blast radius; publishing cannot stall on minutes |
| 6 | **Hits job** (plan Task 6) with layers 2-3 of C2 (trending feed, rising sounds) and `source_kind: auto_filed` | M | Clip supply without vidIQ |
| 7 | **Drift fixes** (G1-G12) | S | The automation reads one truth |
| 8 | Write the **bake-off protocol** (3 clips, rubric, blind order) and pre-register the **score test** (B3.2) | S | Ready for credits on Monday |

### Next two weeks (12-25 Oct): credits back

| # | Do | Effort | Unlocks |
|---|---|---|---|
| 1 | **Quality bake-off** (D2), tall Franz included; adopt a primary and a backup per clip type | S-M (~600-900 credits) | Top quality with evidence; no single generator |
| 2 | **`studio daily` in the cloud**; the health check reads it; disable the Mac task (keep as fallback, as in the owner's other projects) | M | No Mac in the daily loop |
| 3 | **Weekly review in the cloud**: Python numbers + headless Claude → PR with the report, playbooks and a `hit_rules.md` proposal | M | Learning reaches the check; one-merge approvals |
| 4 | **Bandit** over hook, caption line 1 and first comment (B3.3) | M | Automatic improvement at 0 credits |
| 5 | Make job **submit-and-exit**; daily **credit reconciliation** | S-M | Minutes halved; the ledger matches reality |
| 6 | **TikTok** via Postiz (roadmap phase 2) | S (owner) + S | Twice the data; the kill bar works as written |
| 7 | Signature-move clips, once per character; eye close-up **covers** | S (~450 credits) | Brand recognition at no per-video cost |

### Next two months (Nov-Dec)

| # | Do | Effort | Unlocks |
|---|---|---|---|
| 1 | Run the **pre-registered score test** at 30 posts; keep or refit the weights by PR | S | A score you can trust with money |
| 2 | Then **automatic Make under rules**: score ≥ the validated threshold, price ≤ a per-video limit, budget left, at most N a day per character; autopilot posting per account after 6 approved posts (exists) | M | Minimal approvals (roadmap phase 3) |
| 3 | **Niche discovery** (C2 clusters) feeds characters 4-5 with data | M | The 10-12 roster is chosen by evidence |
| 4 | **Owned inventory share** to about 40% (Recreates, own footage, signature series) | M | Brand-sellable videos; lower originality risk |
| 5 | A hierarchical model at 150+ posts; the events calendar | M | Sharper learning; "looks live" |
| 6 | Supabase on its own project; Postiz Pro; per-character credit limits; a media kit when an account passes 5K | M | Ready for 10-12 characters and brand deals |

---

## Sources

**Repo and environment (read 7 Oct 2026):**
- Docs and config: `CLAUDE.md`, `docs/AI_INFLUENCERS.md`, `docs/roadmap.md`, the v3 spec and plan, `docs/research/*`, `docs/launch/channel-strategy.md`, `docs/launch/marketing-skills.md`, `docs/launch/go-live.md`, `config/scan.json`, `config/hit_rules.md`, `characters/*/refs.json`.
- Code: `studio/{drop,gemini,clipfolder,favorites,planning,metrics,review,fetch,sources,budget,health,clips,models}.py`, `studio/publish/postiz.py`.
- Automation: `.github/workflows/*.yml`, both skills, the migration headers 0001-0014.
- Commands: `gh run list`, `gh repo view`, `git log`, `git diff`, and the Claude Desktop scheduled-task list (which includes the owner's migrated `crypto-tool` jobs).

**Web:**
- Higgsfield Genjutsu: [Higgsfield blog](https://higgsfield.ai/blog/higgsfield-genjutsu), [creativeainews](https://www.creativeainews.com/blog/higgsfield-genjutsu-ai-video-motion-transfer-2026/)
- Kling 3.0 Motion Control: [atlascloud guide](https://www.atlascloud.ai/blog/guides/kling-ai-motion-control), [AI for Real Life #23](https://ai-for-real-life.beehiiv.com/p/issue-23-motion-control-changes-the-game), [creati.ai](https://creati.ai/ai-tools/kling-ai-motion-control/)
- Wan 2.2 Animate: [ComfyUI character replacement](https://comfy.org/workflows/use-cases/ai-character-replacement/), [Runware](https://runware.ai/models/wan2-2-animate)
- Gemini 3.8 Flash: [bibigpt explainer](https://growth.bibigpt.co/en/features/gemini-3-8-flash-explained), [Gemini API models](https://ai.google.dev/gemini-api/docs/models/gemini-3.7-flash?hl=zh-CN)
- Instagram API metrics: [Supermetrics Instagram Insights updates](https://docs.supermetrics.com/docs/instagram-insights-updates), [inro Reels insights 2026](https://www.inro.social/blog/instagram-reels-insights)
- Instagram `is_ai_generated`: [Meta Instagram Platform changelog](https://developers.facebook.com/documentation/instagram-platform/changelog)
- Instagram originality: [Tubefilter, 30 Apr 2026](https://tubefilter.com/2026/04/30/instagram-removes-algorithm-recommendations-repost-content-aggregator), [PetaPixel](https://petapixel.com/2026/04/30/new-instagram-policies-target-reposted-content/), [Planoly](https://planoly.com/blog/instagram-updates-its-original-content-policy)
- TikTok AI policy: [Cinerads, TikTok AI content policy 2026](https://www.cinerads.com/blog/tiktok-ai-content-policy)
- ScrapeCreators: [Trending Feed API](https://scrapecreators.com/tiktok/endpoints/trending-feed), [Top Search API](https://scrapecreators.com/tiktok/endpoints/top-search)
- Higgsfield pricing: [Krea](https://www.krea.ai/blog/higgsfield-pricing-explained-2026-unlimited-credits-and-real-monthly-costs), [Creatify](https://creatify.ai/blog/higgsfield-pricing-(2026)-plans-and-what-you-ll-actually-pay)
- Postiz pricing: [Postiz cloud plans](https://docs.postiz.com/cloud/plans)
- Topaz upscaling: [Magnific Topaz API](https://docs.magnific.com/api-reference/video/video-upscaler-topaz/overview), [fal, video upscalers 2026](https://fal.ai/learn/tools/video-to-video-upscalers)
- GitHub token permissions: [Permissions required for fine-grained tokens](https://docs.github.com/en/rest/authentication/permissions-required-for-fine-grained-personal-access-tokens)
- Claude Code routines: [makerkit guide](https://makerkit.dev/blog/tutorials/claude-code-routines-guide), [DataCamp](https://datacamp.com/tutorial/claude-code-routines)
