# ODD EYES: measurement and learning plan (8 Oct 2026)

**What this is:** how the studio measures every post, tags it so we can learn from it, tests ideas honestly at small
numbers, and changes its own rules over time. It works inside the binding KPI bars (`channel-strategy.md` §3.3,
`studio/review.py`) and never changes them. **Status:** draft for the owner. The tests in section 3 are pre-registered
(written before any 7-day figure exists); they freeze when the owner approves this file.

**Labels:** **[E]** = evidence (a file:line, a function or a named source). **[I]** = my inference.
**Effort:** **S** = config, text or a small function (hours). **M** = a new command, job or client (1-3 days). **L** = a
new subsystem (a week or more). Line numbers in `studio/drop.py` move while it is being edited, so the function is named too.

---

## Summary (read this first)

1. **One number decides: `outlier_x`**, a post's views at 7 days divided by the median 7-day views of its account's last 15 posts. A hit is 3 or more. The binding bars stay exactly as written; this plan only adds how we read, tag and test.
2. **Every post is read four times:** at 1 h (is it alive?), 24 h, 72 h (the first real read; never delete or repost before it) and 7 days (the verdict).
3. **Today the cloud only gets counts** from Postiz (views, likes, comments, shares, saves). Skip rate, watch time, non-follower reach, follows and followers per day are missing, so the Instagram guard and the mechanism floors cannot work yet. Plan Task 9 (Instagram's own API) fixes this; it waits for the owner's Meta app.
4. **Every clip today carries the same format and hook tags**, so the bars cannot tell anything apart. The first build is 13 fixed tags written when a clip is made (section 2). Data not tagged now is lost for good.
5. **Six tests are pre-registered here** (section 3): the clip score, a hook bandit, Trial Reels, own series against swaps, length, and vote against question.
6. **Honest about size:** at 20 posts we can only see big effects (a doubling, or a rank correlation of 0.45 or more). We cannot see a 20-30 % gain or name a hook winner per character within 6 weeks.
7. **Code changes nothing on its own** except the binding Instagram guard and the bandit's choice among hooks the owner approved. Every rule change goes through a weekly pull request with its numbers; merging it is the owner's approval.
8. **Early warnings:** 0 views at 3 h on 2 posts in a row means an Account Status check; the guard; a skip-rate jump; data gaps.
9. **The owner reads one weekly digest:** 5 lines per character. The Results tab comes later.
10. **Owner decisions are needed before 14 Oct** (Reginald's first 7-day figure): the kill bar without TikTok, Trial Reels as a test, the 1-in-3 own series, the length test, the exploration picks and the floor procedure (end of section 7).

---

## 1. What we measure and when

### 1.1 The four reading times

| When | What we look at | What we do with it |
|---|---|---|
| **1 h** | Health only: the post is live and public, the AI line is in the caption, the first comment is up, the Story went out (once plan Task 8 exists) | Fix a broken post. Judge nothing |
| **3 h** | Views above 0 | The "no distribution" warning (section 5, rule 1) |
| **24 h** | Views, skip rate | The breakout check (section 5, rule 5) |
| **72 h** | Views, `x72` (below), skip rate, viewer comments | The bandit's win or loss, the quick tests (C, F). **Never delete or repost a slow post before 72 h** [E: hit-patterns §4.8: the two biggest dog hits peaked 39-41 h after posting] |
| **7 d** | `outlier_x` and every rate | All bars and all test verdicts |

- [E] The pull runs every 6 hours at :07 (`.github/workflows/metrics.yml:16`), so today the "1 h" reading is really a 1-7 h reading (audit #17). The windows themselves are in `studio/metrics.py` `WINDOWS`.
- [I] A timed pull 1 h and 3 h after each slot is cheap and fixes this (build item 4).

### 1.2 The primary metric: `outlier_x`

- **Definition** [E: `studio/metrics.py:28-38`, `channel-strategy.md:40`]: the post's views at 7 days ÷ the median 7-day views of the account's last 15 earlier posts. It needs at least 3 earlier figures (`MIN_PRIORS = 3`, `metrics.py:97`). Missing data gives "no value", never 0. A clip posted on two accounts takes the better of its two values.
- **Hit** = `outlier_x` ≥ 3 [E: `review.py:80`].
- **What follows from it** [I]:
  - The first 3 posts on each account never get an `outlier_x`. Each account's first value arrives 7 days after its 4th post (around 21 Oct for Reginald).
  - On a brand-new account the baseline is tiny, so early hits are cheap: 120 views against a median of 30 is a 4× "hit". The digest always prints raw views next to `outlier_x`.
  - Once TikTok is connected, taking the better of two platforms flatters a clip [E: audit #4]. The digest shows the per-platform values beside it (tracked only; the binding figure is unchanged).
- **Early read `x72` (not binding):** the same formula with 72-hour views instead of 7-day views. Only the bandit and the quick reads use it; no bar ever does.

### 1.3 Secondary metrics, per post

"Per 1K" means per 1,000 views, using the views of the same reading.

| Metric | What it is | Its job | Source today | After Task 9 |
|---|---|---|---|---|
| Shares per 1K | shares (sends) ÷ views × 1,000 | The top signal for reach to strangers on Reels [E: `channel-strategy.md:43`] | Postiz (`POSTIZ_METRIC_LABELS`, `metrics.py:111`; label unverified, `:110`) | Instagram API |
| Saves per 1K | saves ÷ views × 1,000 | "Worth keeping" | Postiz (the "Saves" label unverified) | Instagram API |
| Viewer comments per 1K | comments minus our own (the first comment, our replies) ÷ views × 1,000 | Thread depth | Postiz, but it counts our own comment too [I] | Instagram API |
| **Skip rate** | share of viewers who scroll away within the first 3 s [E: hit-patterns §2.5]. Practitioners call 30-40 % healthy and over 50 % a reach loss [E-weak, no official figure] | **The hook's grade** | vidIQ owner insights, only inside the weekly review on the Mac, keys still "VERIFY" (`metrics.py:129, 148`; weekly-review `SKILL.md` step 2) | Instagram API (the metric name to verify on one post) [E: system-review §B2] |
| Watched % | average watch time ÷ the master's length; over 100 % means replays | Completion and loops | vidIQ (Mac) | Instagram API average watch time ÷ our own `length_s` |
| Non-follower reach % | reach from non-followers ÷ all reach | Reach health; feeds the binding guard | **Missing.** Nothing writes `non_follower_pct` [E: `models.py:237`; system-review §B1] | Instagram API (follow-type breakdown) |
| Follows per 1K | follows the post brought ÷ views × 1,000 | Turns viewers into an audience | **Missing** [E: audit #2] | Instagram API |
| Reach | unique accounts reached | Check on views | Postiz returns it for Instagram but it is not mapped [E: audit #2] | Instagram API |

### 1.4 Per account

- **Followers per day (net):** **missing** today. Postiz `analytics:platform` could give it now [E: audit #2a]; after Task 9, one Instagram reading of the follower count a day [I: verify the field].
- **Weekly, per channel** [E: `channel-strategy.md` §3.2]: followers and net growth, median `outlier_x`, hit rate, best post, non-follower reach %, cost per 1K views (credits ÷ views × 1,000), cost per follower.
- **Monthly, for brand deals later** [I]: median views of the last 10 Reels, engagement rate, audience country and age (Instagram usually shows demographics only above about 100 followers: verify). These are the media-kit numbers; collecting them from the start means they exist when a brand asks.

### 1.5 TikTok

- Not connected yet [E: system-review §B1, every `refs.json` has `tiktok.postiz_integration_id: null`].
- When it is: Postiz gives views, likes, comments and shares only. Watch time and the For You share need TikTok Studio by hand (a 5-minute weekly form), because TikTok's watch-time API needs a Business account, which loses the music library [E: audit #2]. TikTok has no Trial Reels [E: audit #4].

---

## 2. The tags every post must carry

**Why first** [E]: `drop._features` (`drop.py`, ~l.1207) writes the same `format_id: "drop_object_swap"`, `hook_pattern: "drop"`,
`audio_arm: "original_audio"` and `seamless_loop: False` on every drop. The format bar, the hook bar and `feature_lifts` (which
reads only `REQUIRED_FEATURES`, `review.py:160-181`, `clips.py:107-121`) see one format and one hook. The clip score sits on the
pick (`proposal.drop.score`), not on the clip [E: system-review §B1].

**Rules:**
- Fixed vocabularies, so values repeat often enough to reach n ≥ 5.
- Set once, when the clip is made; never guessed later [E: `clips.py:25-28`]. "none" is a value; a missing tag is an error.
- The new keys join the set that `new_clip` requires (or a `LEARN_FEATURES` set that `feature_lifts` reads), so a clip can never be made untagged.

| # | Tag (feature key) | Fixed values | Written where | Today |
|---|---|---|---|---|
| 1 | Character | `franz`, `reginald`, `lenny` | `clip.character_slug`, at creation | Exists |
| 2 | Format (`format_id`): how the video was made | `swap_trend`, `swap_classic`, `swap_other`, `recreate`, `own_footage` | `drop._features`, from the check's `classic` and `moment_name` and the pick's source; the Recreate path writes `recreate` | Constant `drop_object_swap` |
| 3 | Hook pattern (`hook_pattern`) | The 7 names of hit-patterns §4.3: `ego-claim`, `when-relatable`, `false-premise`, `understatement`, `mid-deal`, `trend-label`, `myth-bust`; plus `hook_index` and `hook_by` (`bandit` / `owner`) | Gemini labels each candidate (new `pattern` per hook in `DECONSTRUCT_SCHEMA`, `gemini.py:472`); the bandit picks; `drop._features` stores | Constant `drop` |
| 4 | Caption line 1 (`caption_line1`) | `label-first`, `joke-first` | `caption_text` (`drop.py`, ~l.690: title, then joke) | Always label-first, not tagged |
| 5 | First-comment kind (`first_comment_kind`) | `vote`, `question`, `none`; plus `first_comment_posted` (yes/no) | The kind at make; "posted" by the publisher (plan Task 8) | Not tagged. Gemini writes a vote (`gemini.py:598`), it is stored on the clip (`clips.set_first_comment`), but the publisher does not post it [E: no `first_comment` in `studio/publish/`] |
| 6 | Trend stage (`trend_stage`) | `rising`, `peak`, `fading`, `classic`, `none`; plus `days_since_trend_peak` | At filing (the hits job or one trend-curve call, hit-patterns rule P5), copied to the clip at make | Missing |
| 7 | Sound type (`sound_type`) | `own_trend_sound`, `own_other`, `ai_beat`, `in_app` (silent master), `none`; plus `sound_rising` (yes/no) | The check (`trend_sound`, proposed in hit-patterns §7.1) and the music mode | Partly: constant `audio_arm`, and `music` |
| 8 | Length bucket (`length_bucket`) | `under_8`, `8_10` (8.0-10.9 s), `11_16`; plus the exact `length_s` | The master build, from the master's real length | Missing. The weekly-review skill uses other buckets (under 9, 9-12, 12-16, `SKILL.md:19`): align it to these |
| 9 | Clip score bucket (`score_bucket`) | `none`, `under_50`, `50_64`, `65_79`, `80_up`; plus `score_total`, `score_potential`, `score_swap` | Copied from `drop.score` at make | Missing on the clip |
| 10 | Part (`part`) | `cameo`, `featured`, `star` | `drop._features` | Exists as `presence` (rename or alias) |
| 11 | Reuse family (`family_id`, `version_index`) | The root pick's id; 1 = the root, 2-3 = versions | From `drop.copy_of` (v3 plan Task 2) | Missing on the clip |
| 12 | Trial Reel (`trial_reel`) | yes/no (Instagram only); plus `graduated` when the API reports it | The publisher (plan Task 8, later Task 9 part B) | Missing |
| 13 | Series (`series`, `episode`) | `sausage_vs_trend`, `household_unaware`, `on_hold`, `classics`, `halloween_countdown` (hit-patterns §4.7), or `none`; the episode number | The Make-it sheet or the plan | Missing |

**Also needed to learn honestly:**
- `hit_rules_version`: the version of `config/hit_rules.md` the clip was checked under (the file has no version yet [E: `config/hit_rules.md:1-10`]).
- `source_kind`: `owner_saved`, `auto_filed`, `own_footage`, `recreate` [E: system-review §B2].
- `test_arms`: what each running test assigned, e.g. `{"hook": "ego-claim", "comment": "vote", "trial": true, "length": "8_10"}`; and `explore_pick` (yes/no, test A).
- The existing `engagement_kind` (`send` / `question` / `tease`, the caption's last line, rotated per character [E: `drop.py` `next_engagement`, ~l.696]) stays.

**Where each is written, in pipeline order:**
1. **Check** (cloud, `studio/drop.py` + `studio/gemini.py`): score, hook candidates with their patterns, the question variant of the first comment, trend stage, sound. Stored in `proposal.drop`.
2. **Make** (`drop._features` → `clips.new_clip`): every clip tag above, the test arms, the score.
3. **Master**: `length_s` and `length_bucket`.
4. **Schedule and publish** (`clips.schedule_clip`, `studio/publish/postiz.py`): `trial_reel`, `first_comment_posted`.
5. **The Recreate path** (daily run and planning) writes the same vocabulary.

---

## 3. Pre-registered tests (first 6 weeks: 12 Oct to 22 Nov)

### 3.0 Rules for every test

- **Pre-registered** means the hypothesis, the metric, the minimum sample and the decision rule are written down before the data exists, so nobody can move the goalposts after seeing results. A change is a new dated version and applies only to later posts.
- **One observation = one posted clip on Instagram.** A clip's versions for other characters count separately and are flagged.
- **Missing data is left out**, never counted as 0 [E: `review.py:26-29`].
- **Each test has its own coin.** The coin is balanced in blocks of 4 (two of each arm in a random order), seeded per test from the clip id, and recorded in `test_arms`. Never two plain alternations (A, B, A, B): they would line up with each other and with the caption rotation that already exists [E: `next_engagement`].
- **Tests run at the same time.** Because each coin is separate, the other tests average out in each comparison [I]. Interactions (hook × trend) are not read.
- **No peeking.** The digest shows running counts marked "not a verdict" until the minimum sample. Decisions happen only at the pre-registered looks.
- **A test never overrides a bar.** A format the bar kills stays killed.
- **Medians and ratios of medians**, pooled across characters when the metric is already relative to the account (`outlier_x`, `x72`).
- **The default wins ties.** When a read is inconclusive, the current rule stays.
- A test starts on the day its preconditions are met. If its minimum sample is not reached by 22 Nov it continues and is read when it is.

### 3.1 What 20 posts can and cannot tell us [I]

- **Expected volume:** about 6 posts per character in weeks 1-2, then 3-5 a week, so 18-31 posts each by 22 Nov. `outlier_x` exists from the 4th post on, 7 days later: about 12-23 values per character, 35-65 pooled, by mid-November. Only drops carry a clip score, so test A has fewer.
- **Learnable at about 20:** whether an account is distributed at all; the baselines for the mechanism floors; very large effects (one arm's median at least 2× the other's, in the same direction on most accounts); a strong score correlation.
- **Not learnable at about 20:** a 20-30 % gain; a hook winner per character; interactions; weekday or time effects (not tested anyway: the slots are the owner's [E: weekly-review `SKILL.md:19`]); anything about TikTok.
- **Two numbers to keep in mind:**
  - A rank correlation (Spearman ρ: does a higher score go with a higher result, from −1 to +1) that is truly 0 still lands anywhere between −0.45 and +0.45 one time in twenty at n = 20, and between −0.31 and +0.31 at n = 40 (the standard critical values).
  - Telling a 30 % win rate from a 50 % one, reliably, takes about 90 posts per arm (a standard two-proportion sample size, 80 % power).
- This is why the binding bars use medians, n ≥ 5 to keep and n ≥ 8 to kill [E: `review.py:82-83`], and why most tests below end "inconclusive, keep the default" at 20.

### 3.2 Test A: does the clip score predict `outlier_x`?

- **Why:** the score now ranks what the owner is invited to pay for, and its weights are a guess: `total = round(10 × (0.6 × potential + 0.4 × swap))`, `potential` being one Gemini judgement [E: `drop.py` `drop_score`, ~l.530; system-review §B1]. The audit's rule: never let an unvalidated score steer spend [E: audit #20].
- **Hypothesis:** a higher `score_total` goes with a higher `outlier_x` (Spearman ρ above 0).
- **Unit:** posted drops with both a `score_total` (from the check) and an `outlier_x`, pooled across characters.
- **Exploration picks (owner decision):** if only top-3 clips are made, their scores sit in a narrow band, and even a good score shows no correlation (a known effect of a restricted range) [I]. So 1 made clip in 4 comes from below the median score of that character's ready clips, tagged `explore_pick`. The cost: those clips are expected to do worse.
- **Looks and decision rule:**
  - **Interim at n = 20:** ρ ≥ 0.45 → **validated**. ρ ≤ 0 → **failed**. Otherwise **unproven**, continue.
  - **Final at n = 40:** ρ ≥ 0.31 → **validated**; below → **failed**.
  - If the middle 80 % of the scores spans fewer than 15 points, the test is **uninformative**: say so, do not fail the score, raise the exploration picks.
  - Report only, no decision: ρ for `potential` and `swap` separately, and the median `outlier_x` per score bucket.
- **If validated:** the terminal drops the "unproven" label and the score may rank "Make these". Automatic Make under a price limit becomes a later proposal for the owner [E: system-review sequence Nov-Dec #2].
- **If failed:**
  1. The terminal labels the score "unproven: does not predict views yet". "Make these" sorts by trend freshness first (rising, peak, classic), the score second [I].
  2. If `potential` or `swap` alone passes the same threshold, a PR proposes using that part alone.
  3. The potential rubric in `config/hit_rules.md` is rewritten from the tag lifts that do show (PR).
  4. The new score is tested again on the next 40 posts. A score cannot be validated on the posts it was fitted to.
- **Note:** this replaces the system review's proposal (ρ ≥ 0.25 after 30 posts, §B3.2), which was never adopted. At n = 30, a ρ of 0.25 cannot be told apart from 0 [I].

### 3.3 Test B: which hook pattern, chosen by a simple bandit

- **Why it is free:** the hook costs 0 credits to vary, and Gemini already writes 3 hooks per clip [E: `gemini.py:472`].
- **Arms per character** (the "Fits" column of hit-patterns §4.3):
  - Franz: `ego-claim`, `when-relatable`, `myth-bust`, `trend-label`
  - Reginald: `false-premise`, `understatement`, `trend-label`
  - Lenny: `mid-deal`, `when-relatable`, `ego-claim`, `trend-label`
  - `trend-label` is available only when the clip has a moment name; otherwise the draw is among the others.
  - Change needed: Gemini writes one hook per arm (3-4, not always 3) and labels each.
- **How it works, in plain words:** each hook pattern keeps a tally of wins and losses for that character. Before a post, the bandit draws one random number per pattern from a curve shaped by its tally. A pattern with many wins tends to draw high. A pattern with few uses has a wide curve and sometimes draws highest, so it keeps being tried. The highest draw goes on screen. Winners get used more, and the others are never dropped by accident. (This is Thompson sampling; each curve is a Beta(wins + 1, losses + 1) distribution.)
- **Win:** the post's views at 72 h beat the median 72-hour views of the account's last 15 earlier posts (at least 3 needed) [E: system-review §B3.3]. A post with no 72-hour reading is neither a win nor a loss.
- **Guard rails:**
  1. **Warm-up:** until an account has 3 earlier 72-hour readings, the patterns rotate in a fixed order and nothing is tallied.
  2. **Floor:** part of every draw is random, so each arm gets at least 15 % of posts (3 arms) or 12 % (4 arms).
  3. **Ceiling:** no arm above 60 % of a character's posts until he has 30 tallied posts (no lock-in on early luck).
  4. **The owner's hook always wins.** That post is tagged `hook_by: owner` and does not change the tally (it still counts for the binding hook bar).
  5. **Scope:** it only picks among hooks already written and checked (at most 7 words, true to the clip). It never touches the clip choice, the slot, the price or a bar.
  6. A win is recorded once, at 72 h, and never revised.
  7. An off switch per character.
- **Pre-registered switch to skip rate:** when Task 9 gives a skip rate for at least 90 % of the last 2 weeks' posts, a second tally starts with win = skip rate below the account's median of its last 15 posts. Skip rate grades the hook more directly than views [I]. The first tally is kept for reference.
- **Arms change only by PR:** retire an arm after at least 10 tallied uses with 20 % wins or fewer and a median `outlier_x` of 0.7 or less (the format kill line); add an arm only from outside evidence (a research doc).
- **The binding bar is separate:** a pattern is "proven" at 2 or more hits in its last 10 uses [E: `review.py:85`; `channel-strategy.md:52`]. The verdict is the code's and is reported as it is.
- **What 6 weeks can show:** about 6-8 tallied uses per arm per character, enough to see only a gross gap (1 win in 7 against 5 in 7). Shared arms pooled across characters (`trend-label` for all three; `ego-claim` and `when-relatable` for Franz and Lenny) get 12-20 uses. Expect a near-even split at week 6 and a real tilt around weeks 12-14 [I].

### 3.4 Test C: Trial Reels against normal Reels on new accounts

- **What a Trial Reel is:** a Reel shown to non-followers first and shared with followers only if it does well (`graduation_strategy: SS_PERFORMANCE`); it stays off the profile grid until then [E: audit #4; v3 spec §11.5].
- **Preconditions:** the owner says yes (morning report decision 5, pending); the account can post Trial Reels (the follower minimum is unclear, 200 or 1,000 by source [E-weak: audit #4], so check in the app); plan Task 8's trial switch, with its Postiz keys verified on one post.
- **Hypothesis:** on an Instagram account under 1,000 followers, a Trial Reel gets more views in 72 h than a normal Reel and does not cut follows.
- **Assignment:** per account, the block coin (2 trial and 2 normal in every 4 posts).
- **Primary:** views at 72 h. Per account: the median of the trial posts ÷ the median of the normal posts. Pooled: the median of the three accounts' ratios.
- **Secondary:** follows per 1K (an empty grid may cost follows [I]); the non-follower reach count; graduated or not; 7-day views.
- **Minimum:** 10 trial and 10 normal, at least 3 of each per account.
- **Decision:**
  - Ratio ≥ 1.5 on at least 2 of 3 accounts, and trial follows per 1K at least half of normal's → Trial for every post on accounts under 1,000 followers; test again at 1,000.
  - Pooled ratio ≤ 1.0 → Trial off (normal Reels build the grid).
  - In between → continue to 15 and 15; still in between → off (the default).
- **Notes [I]:**
  - Trial posts stay in the `outlier_x` baseline: a post is a post, and the binding definition does not change. If trial views differ a lot, the baseline moves; the digest says so.
  - On an account with 1 follower almost every viewer is a non-follower already, so the gap may be small. The test answers a practical question (does the trial path get more distribution?), not why.
  - The morning report suggests Trial on for every post until about 1,000 followers. That leaves no comparison and teaches nothing; this test is the middle way.

### 3.5 Test D: own series against swaps

- **Definitions:** **own** = a numbered episode of the character's own series made by Recreate or own footage. **Swap** = a Drop-in on someone else's clip (a swap may carry a series name; here it still counts as a swap).
- **Why:** Instagram judges originality per account per month and shows the original instead of near-copies [E: system-review §F1; audit #1]. Brands pay for footage we own [E: system-review §F4]. It costs more: a Recreate is 160 credits, a Drop-in about 91-100 [E: CLAUDE.md cost model].
- **Preconditions:** the owner says yes to 1 in 3 (morning report suggestion 3) and the credits exist.
- **Assignment:** 1 post in 3 per character is own; its weekday rotates each week so it never sits on the same day.
- **Hypotheses:** (1) **views:** own posts reach at least 0.8× the swaps' median `outlier_x`; (2) **audience:** own posts bring more follows per 1K than swaps; (3) **risk:** no account with an own share of 1 in 3 or more shows a guard-level drop.
- **Primary:** median `outlier_x`, own against swap. **Secondary:** follows per 1K, non-follower reach %, cost per 1K views, viewer comments per 1K.
- **Minimum:** 8 own posts per character (the format kill bar needs 8 [E: `review.py:83`]); a pooled read at 15 own posts.
- **Decision:**
  - Own ≥ 1.0× swaps on `outlier_x`, and follows per 1K at least the swaps' → propose 1 in 2.
  - Own between 0.8× and 1.0× → keep 1 in 3.
  - Own below 0.8×, but follows per 1K at least 1.5× the swaps' → keep 1 in 3 (it builds the audience).
  - Own below 0.8× on both → keep 1 in 3 as insurance and propose a new series idea.
  - Each series is a format, so the binding format bar applies (keep at a median of 1.5 or more over 5 or more; kill at 0.7 or less over 8 or more). A killed series is replaced by another own series, not by swaps.
- **The risk side:** the binding guard acts on its own (a drop of 40 % or more → `dropin_share` 0.20 [E: `review.py:94-95`]). With 3 accounts we cannot measure how much swapping is too much; we can only see a break [I].

### 3.6 Test E: 8-10 s against 12-15 s

- **Today:** classics run 12-15 s and other clips 8-10 s (owner, 5 Oct) [E: CLAUDE.md]. Length and "classic" move together, so comparing them today says nothing about length [I].
- **Preconditions:** the owner says yes, because the test goes against his 8-10 s for non-classics and costs more. A Drop-in costs ceil(seconds × 11) + 3 [E: CLAUDE.md]: 9 s is 102 credits, 13.5 s about 152, so about +50 per long clip and about +500 for the test.
- **Eligible:** non-classic drops whose clip has a clean 12-15 s section that still pays off within 3 s [E: `config/hit_rules.md:1`].
- **Assignment:** the block coin among eligible clips: long (12-15 s) or standard (8-10 s).
- **Primary:** `outlier_x`. **Secondary:** watched % (completion and replays) and cost per 1K views.
- **Minimum:** 10 and 10 pooled, at least 3 per character.
- **Decision:** long ≥ 1.3× standard on median `outlier_x`, and cost per 1K views no more than 20 % worse → propose 12-15 s for every clip with a clean section. Long ≤ 1.0× → keep 8-10 s. In between → keep 8-10 s (the default).
- **If the owner says no:** classics against others is reported as a description only, with no conclusion on length.
- **Outside evidence:** on TikTok, 7 s clips complete more often but 15 s clips earn more watch time per view [E-weak: hit-patterns §2.5].

### 3.7 Test F: first comment as a vote or a question

- **Today:** hit rule 10 says the first comment is a two-option vote for the next clip [E: `config/hit_rules.md:10`]. Gemini writes it (`gemini.py:598`) and it is stored on the clip, but the publisher does not post it yet (plan Task 8).
- **Preconditions:** the first comment is posted within 5 minutes of the Reel (Task 8, or the owner by hand) and pinned. Gemini also writes a question variant (the caption already has a `question` field, `gemini.py:475`).
- **Hypothesis:** a vote gets more viewer comments per 1K views than an open question.
- **Assignment:** the block coin, per character.
- **Primary:** viewer comments per 1K views at 72 h, pooled per arm (all viewer comments ÷ all views × 1,000). Per-post counts are mostly 0-3 at our sizes, so medians would be 0 [I]. Our own comments (the first comment and our replies) are taken off.
- **Secondary:** the share of posts with at least one viewer comment; follows per 1K; whether the winning option was then made (closing the loop) [E: hit-patterns rule F1].
- **Minimum:** 10 and 10 pooled.
- **Decision:** vote ≥ 1.5× question → keep rule 10. Question ≥ 1.5× vote → a PR changes rule 10. Otherwise keep the vote (the default).
- **Honest:** with a few hundred views a post, expect "too few to call" at 20 [I]. It gets sharper as views grow.
- **Next in line (after week 6):** caption line 1, label-first against joke-first [E: hit-patterns rule C3], and the caption's last line (send, question or tease), which already rotates and can be read the same way once tagged.

### 3.8 The mechanism floors (a binding step that needs a procedure)

- **Binding text:** the mechanism targets (watch ratio, 3 s hold, sends per 1K, follows per 1K) are "measured as a baseline in weeks 1-2, then fixed as numeric floors before week 3" [E: `channel-strategy.md:55`]. Week 3 starts Mon 19 Oct.
- **The gap:** skip rate, watch time and follows are not in the cloud. Unless Task 9 lands by about 15 Oct, weeks 1-2 give no baseline for three of the four [E: audit #2].
- **Procedure (for the owner to approve now, before the data):**
  - On Sun 18 Oct, per character: each floor = the median of his weeks 1-2 posts (sends per 1K, follows per 1K, watched %). The skip-rate ceiling = his median skip rate.
  - Fewer than 4 readings for a character → use the studio-wide median.
  - Fewer than 6 readings studio-wide → the floor is fixed on the day the 6th reading arrives, and that date is written down.
  - This fills a procedural gap. It does not change a bar.
- **What floors do:** they diagnose. A post below two of them is flagged with what failed (hook, hold, sends, follows). They never kill anything; only the bars do.

---

## 4. Decision rules and cadence

### 4.1 Who changes what

| Lever | How it changes | Who approves |
|---|---|---|
| Instagram guard (`dropin_share` to 0.20) | Automatically, by code, at the weekly review | Nobody: it is binding [E: `review.py:94-95, 394-406`] |
| An "unoriginal content" notice | The owner ticks "notice seen" → the same cut | The owner's tick [E: `channel-strategy.md:54`; audit #1c] |
| The hook shown on screen | The bandit, per post, among approved arms | None per post |
| The test assignments | The coins, per post | Approved once, with this plan |
| The score's label (unproven, validated, failed) | Automatically, at the pre-registered looks | None |
| Bar verdicts (format keep or kill, hook proven, character promote or kill) | Computed by code [E: `review.py`] | The verdict is the code's; acting on it (stop a format, replace a character) is the owner's |
| `config/hit_rules.md` | A weekly PR carrying its numbers | Merge |
| Score weights | A PR after test A | Merge |
| Bandit arms (add or retire) | A PR | Merge |
| Trial Reels, own-series share, clip length | A proposal after tests C, D, E | The owner |
| Scan keywords | A PR to `config/scan.json` [E: system-review §B3 table] | Merge |
| Slots, cadence, the credit cap, the roster | Never by data | The owner only |
| The KPI bars and the `outlier_x` definition | **Never** | Binding [E: `review.py:3-7, 78`] |

### 4.2 Cadence

- **Per post:** the 1 h and 3 h health pulls; the 24 h, 72 h and 7 d reads.
- **Daily (cloud):** the metrics pull (Postiz, then the Instagram API), the follower reading, the early warnings, the bandit tally for posts that reached 72 h.
- **Weekly (Monday, cloud):** `review data` → the digest → PRs (hit rules, playbooks, bandit arms). A week runs Monday to Sunday, London time.
- **At set points:** the floors on 18 Oct; test A at 20 and 40; tests C-F at their minimum; the character bar opens at 20 posts or 4 weeks, whichever comes first [E: `review.py:89-90`] (Reginald: 4 Nov).
- **Monthly:** cost per 1K views and per follower; the swap share per account (originality); the brand-readiness numbers.
- **Why the PR route** [E]: today the weekly review runs on the Mac, its playbook commit "stays local" (`SKILL.md:23`), and the drop prompt never reads the playbook (system-review §B1). The one file the cloud check does read is `config/hit_rules.md` (`gemini.py:566`). So a lesson reaches production only through that file, and a PR is how it gets there with a paper trail.

### 4.3 How a rule enters and leaves `config/hit_rules.md`

- **Today:** 10 unnumbered lines from outside research, no version [E: `config/hit_rules.md:1-10`]; the spec caps it at 20 lines [E: v3 spec §3].
- **Format:** line 1 is `v<N> · <date>`; each rule is `R<n>` and its text. Gemini reads the file as it is, so the evidence lives in the PR and in a history log next to it, not in the rule lines. Every clip records `hit_rules_version`.
- **A rule enters when all four hold:**
  1. a tag measures it (followed or not);
  2. at least 5 measured clips on each side [E: `LIFT_MIN_N = 5`, `review.py:87`; `SKILL.md:22`];
  3. the clips that follow it have a median `outlier_x` at least 1.5× the others' (the format keep line), and at least one of them is a hit;
  4. the next week's posts, added in, still show at least 1.2× (a second look).
  Then Claude drafts a PR: the rule text, n, medians, lift, clip ids, dates and the version bump. Merging is the owner's approval.
- **A rule leaves when:** at least 8 clips on each side show a lift of 0.7 or less (the kill line); or it was about a trend that has faded; or a planned test beats it (as test F might). A PR again.
- **A rule everybody follows cannot be measured by lift** (there is no "not followed" side). It can only be changed by a planned test, as in test F. Most of today's 10 rules are like this [I].
- **Room:** at 20 lines, the rule with the weakest evidence goes first. Rules from outside research stay until our own data argues against them, and are marked as such so the review knows they are unproven by us.
- **Under 5 posts** goes to "Watching" in the character's playbook, never into the rules [E: `SKILL.md:22`].

---

## 5. Early-warning rules

| # | Signal | Fires when | Checked | Action | Source today |
|---|---|---|---|---|---|
| 1 | **No distribution** | A post has 0 views at its 3 h reading, on 2 posts in a row on the same account | 3 h pull | Alert the owner: open Account Status (can the account be recommended?), check the AI label, a muted song, that the post is public. Autopilot for that account goes back to approve-first until he clears it. Never delete or repost before 72 h | The owner's own eye; the timed pull is build item 4. Reginald's first Reel (0 views at 3 h, 1 follower) is one of the two [E: morning report §1.2] |
| 2 | **Instagram guard (binding)** | Non-follower reach % down 40 % or more week on week | Weekly | `dropin_share` → 0.20 automatically, reported | Cannot fire: nothing writes `non_follower_pct` until Task 9 [E] |
| 2b | New-account reach [I] | Under about 1,000 followers the % sits near 100 % by arithmetic, so the guard can hardly fire. Also watch the count: the median non-follower reach per post down 50 % or more week on week | Weekly | A warning only, not a bar: nothing changes by itself | Task 9 |
| 3 | **Unoriginal notice** | Account Status shows an "unoriginal content" or limited-reach notice | The owner | The same cut as the guard (binding) [E: `channel-strategy.md:54`] | A terminal tick (build item 12) |
| 4 | **Skip-rate jump** | A character's weekly median skip rate up 10 points or more against his previous 2 weeks, or 2 posts in a row above 60 % | Daily | Flag. All characters at once → suspect the master (first frame, pill timing) before the hooks. One character → look at his hook patterns | Task 9 (vidIQ weekly on the Mac until then) |
| 5 | **Breakout (good news)** | 24 h views at least 3× the account's median 24 h views | 24 h | Propose a part 2 for the next free slot (tracked, not a bar) [E: audit #5c] | Postiz (every 6 h) |
| 6 | **Data gaps** | A metrics pull fails twice in a row; Postiz `missing` on a post for over 24 h; no 7-day reading by day 9 | Daily | Alert: that post's `outlier_x` would be missing [E: `metrics.py` docstring] | Partly: `missing` and errors are already listed |
| 7 | **Takedowns** | 2 copyright or takedown notices on one account within 30 days | The owner | Propose the kill switch for swaps on that account [E: system-review §F3] | The owner |
| 8 | **Follower loss** | Net followers below 0 three days running | Daily | Check: a purge, or a post that annoyed people | Task 9, or Postiz platform analytics |

---

## 6. What the owner sees

### 6.1 One weekly digest

- **Where:** Monday, from the cloud weekly review, on the terminal's Today page and as the description of the weekly PR.
- **Studio header (2 lines):** credits this month against the cap; cost per 1K views; warnings that fired; PRs waiting for a merge.
- **Then 5 lines per character:**
  1. **Result:** posts; median `outlier_x` (or why there is none yet); hits; best post with its raw views; against last week.
  2. **Audience:** followers (net change); follows per 1K; non-follower reach %; the guard's state.
  3. **Hook:** median skip rate against his ceiling; the bandit's leading pattern with its n.
  4. **Tests:** n so far against n needed for the tests that touch him; "not a verdict" until then.
  5. **Next:** one STOP and one DO MORE backed by numbers, or "too few to call"; any decision he must make.
- **Rules:** every number sits next to a comparison [E: v3 spec §1]; n is always shown; under 10 measured posts, line 5 says "too few to call" [E: `SKILL.md:19`].
- **Example (made-up numbers):**

```
Reginald · week of 19 Oct · bar: not yet (9 of 20 posts, day 15 of 28)
1 Result    5 posts · median outlier_x 1.1 (last week: none yet) · 1 hit · best "First day as head butler." 2,300 views (4.2x, small base)
2 Audience  61 followers (+40) · 3.8 follows per 1K · non-follower reach 97 % · guard: no change
3 Hook      skip rate 41 % (ceiling 45 %) · leading: false-premise, 3 wins of 4 (too few to call)
4 Tests     trial vs normal 3 v 2 (need 10 v 10) · vote vs question 2 v 3 · score test 14 of 20
5 Next      too few to call · needs you: nothing
```

### 6.2 The Results tab (later; v3 spec §2 puts it at about week 2-3)

Per character:
- `outlier_x` per post over time (dots, with lines at 1 and 3), raw views on tap.
- The bar: progress to 20 posts or 4 weeks, the thresholds, the verdict.
- The funnel per post: views → skip rate → watched % → shares and saves per 1K → follows per 1K, each against its floor.
- The tests board: each test, n so far against n needed, the current read marked "not a verdict", the decision date.
- The hook arms: share of posts and win rate per pattern.
- The hit rules: version history with the numbers behind each rule.
- Money: cost per 1K views, cost per follower, credits per hit; the media-kit numbers once an account passes 5,000 followers [E: `SKILL.md:20`].

---

## 7. What to build, in order

| # | Build | Effort | Already covered by | Unlocks |
|---|---|---|---|---|
| 1 | Push the local work; re-check every ready drop so each has a score | S | v3 plan controller step 4; system-review "this week" #1 | Test A can start |
| 2 | **Tags at creation** (section 2): Gemini labels hook patterns, writes one hook per arm and a question comment; `drop._features` writes every tag, the test arms and the score; the new keys become required; the Recreate path too | S-M | system-review §B2 and "this week" #2 (no plan task yet: propose v3 Task 10) | Every test and every lift |
| 3 | `config/hit_rules.md` gets a version and numbered rules; `hit_rules_version` on each clip | S | system-review §B3.4 | Rule lifts |
| 4 | Timed pulls 1 h and 3 h after each slot (a pg_cron tick like `studio-publish-tick` in 0014); warnings 1, 5 and 6 in `studio health` | S-M | audit #17 (in part) | Early warnings |
| 5 | Metrics: 72-hour views and `x72`, per-platform `outlier_x`, viewer comments without ours, the per-1K rates | S | — | Test B, tests C and F |
| 6 | **Instagram API stats:** reach, follow type, follows, saves, shares, skip rate, watch time, followers per day; writes `non_follower_pct` | M | **v3 plan Task 9 part A** (waits for the owner's Meta app) | The guard, the floors, warnings 2-4 and 8, follows |
| 6b | Stopgap until then: Postiz `analytics:platform` for followers per day; map Instagram `reach` | S | audit #2a-b | Followers before Task 9 |
| 7 | A test registry, `config/experiments.json` (arms, block coins, seeds, minimum n, status), and the assignment at make | S | — | Tests B-F |
| 8 | **Reach pack:** the first comment posted, the Trial switch, the Story | M | **v3 plan Task 8** | Tests C and F |
| 9 | The bandit: table `studio.arms`, the draw with floor and ceiling, the win at 72 h | M | system-review §B3.3 (sequence 12-25 Oct #4) | Test B |
| 10 | The weekly review in the cloud: numbers, the digest, PRs for hit rules, playbooks and arms | M | system-review §A3 (`studio-weekly.yml`) | Lessons reach the check |
| 11 | The score test and its label in the terminal | S | system-review §B3.2 | Test A's outcome is visible |
| 12 | Owner ticks: "unoriginal notice seen", "Trial Reels available" | S | audit #1c | Warning 3; test C's precondition |
| 13 | The Results tab | M-L | v3 spec §2 ("later") | The owner's view |
| 14 | TikTok: connect it; the 5-minute weekly numbers form | S (owner) + M | audit #2c; system-review sequence 12-25 Oct #6 | The kill bar as written; twice the data |

**Order:** items 1-3 this week, because tags cannot be added to posts afterwards [E: system-review §B2: "fix first, it cannot be
recovered later"]. Items 4-7 next. Items 8-11 around 19 Oct. Items 12-14 after that.

### Owner decisions, before 14 Oct (Reginald's first 7-day figure)

Deciding these before any 7-day data keeps them from being renegotiations.
1. **The kill bar without TikTok.** It needs a median on both platforms, so it cannot fire while TikTok is not connected [E: `review.py:18, 92`; system-review §F6]. Either an Instagram-only kill rule, or TikTok connected before the bar opens (about 4 Nov).
2. **Trial Reels:** run test C (half the posts), or all on, or off.
3. **Own series, 1 post in 3** (credits).
4. **The length test** (about +500 credits; goes against 8-10 s for non-classics).
5. **Exploration picks** for test A (1 made clip in 4 from below the median score).
6. **The floor procedure** in section 3.8.
7. **Approve this pre-registration** (it freezes sections 3 and 4.3).

---

## Sources read

`CLAUDE.md`; `docs/superpowers/plans/2026-10-04-character-studio-slice1.md` (header); `docs/launch/channel-strategy.md`;
`docs/research/2026-10-07-system-review.md` (summary, §A-B, §F-G, sequence); `docs/research/2026-10-07-hit-patterns.md`;
`docs/research/2026-10-05-best-practice-audit.md` (verdict, gap table, §6); `docs/superpowers/specs/2026-10-07-terminal-v3-design.md`;
`docs/superpowers/plans/2026-10-07-terminal-v3.md` (Tasks 1-9); `docs/launch/2026-10-08-morning-report.md`;
`.claude/skills/weekly-review/SKILL.md`; `config/hit_rules.md`; `studio/metrics.py`, `studio/review.py`, `studio/clips.py`,
`studio/models.py`, `studio/health.py` (docstrings and constants); `studio/drop.py` (`drop_score`, `next_engagement`,
`caption_text`, `_features`); `studio/gemini.py` (deconstruct schema and prompt); `.github/workflows/metrics.yml`.
No code, config or git state was changed; no paid or publishing tool was called.
