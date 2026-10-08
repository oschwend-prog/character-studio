# ODD EYES: Ghostfeed, Apify, LunarCrush free data and Higgsfield Earn, 8 Oct 2026

**What this is:** answers to the owner's four asks of 8 Oct 2026: (1) Ghostfeed, what to copy; (2) Apify, add or not;
(3) LunarCrush's free last-24-hours data in the hits job; (4) Higgsfield Earn ("$1 per 1,000 views for videos made with a
character from Higgsfield AI Influencer"), checked and compared with LaunchPoint "AI Invasion".

**How:** read-only. Web search and page fetches (sources at the end); 8 LunarCrush MCP calls (2 refused by the rate limit); 2
read-only Higgsfield MCP calls (`apps_search "earn"`, `show_characters list`). No generation, no publishing, no paid call, no
sign-up, no code or config change. This file is the only output.

**Labels:** **[E]** = evidence (a named source, a tool result or a file:line). **[I]** = my inference.
**Effort:** **S** = config, text or a small function (hours). **M** = a new client, command or job (1-3 days). **L** = a new
subsystem (a week or more).

---

## Summary (read this first)

1. **LunarCrush's free mode is enough for the trend-curve rule, not for discovery.** In "limited data mode" a keyword gives 30 daily rows, per network, and a topic gives 24 hourly rows and a 24 h snapshot with a spike line. The limits are 4 calls a minute and 100 a day, shared with every other use of the owner's key. Our code already has empty slots for the result: `trend_stage`, `days_since_trend_peak` and `sound_rising` in `studio/drop.py` (the tag builder), and nothing fills them yet.
2. **Plan for LunarCrush (M):** a small LunarCrush client in the hits job checks each distinct trend name or sound at most once a London day (at most 40 calls). It applies the hit-patterns rule P5 before auto-filing and fills those three tags. **First step:** the owner makes a free API key. One test call from Python then shows whether the free key works outside Claude (LunarCrush's docs say free API keys get market data only).
3. **Higgsfield Earn is real, but "$1 per 1,000 views" is not on Higgsfield's own pages.** Higgsfield's own pages say: campaigns, a fixed payment per approved video plus 24-hour and day-7 bonuses, at most $1,000 on day 1 and $2,500 per video, and the rates are "confidential". The "$1 per 1,000" figure belongs to a $1M LaunchPoint pool for AI-character content (a third-party guide).
4. **Earn platforms:** Instagram (connects automatically), YouTube and X (by a code in the profile). **TikTok is not listed.** You get campaigns that match you. Each brief sets hashtags, mentions, a promo code or tracking link, a minimum length and a time window. An automatic check can reject a video, with one appeal. Payouts go through Garna.
5. **Do our characters qualify?** Probably yes: Higgsfield lets you use "a character you already have". Lenny already has a Higgsfield Soul 2 and Franz a Higgsfield Element. **Our footage does not:** Drop-ins on other people's viral clips are copied footage. Only Recreates, own footage and image-to-video from our stills should ever go to Earn or AI Invasion.
6. **Two Higgsfield moves worth making now (S, owner steps).** Sign up to Earn with one Instagram account and look at the campaigns offered. Apply to Higgsfield's **Creator Partnership Program**: "a full plan renewed every month", "no posting quotas, no exclusivity", in return for tagging Higgsfield. Credits are our tightest limit (130-160 a video against a 6,000 cap), so the free plan is worth more to us than Earn.
7. **Ghostfeed** (ghostfeed.ai) is a TikTok-first "AI UGC" factory for app marketers, at $29-99 a month. It has avatars, reaction videos, slideshows, "video cloning" (one clip put onto many avatars), TikTok scheduling, an MCP server, and a managed service built on bought iPhones and warmed accounts. **Do not use it as a tool.** Copy 5 of its processes (section 1.3). Do not copy its volume model or its "platforms can't distinguish" pitch.
8. **Apify: do not replace ScrapeCreators, and do not add it to the daily job.** At our volume Apify costs about $25-165 a month (it charges per result) against about $1.50-3 for ScrapeCreators (it charges per call). Its "LLM analyser" actors repeat our Gemini check, and they would download clips we have not filed. The only thing Apify has that we lack is TikTok Creative Center's breakout sounds: worth one free-plan test, not a build.
9. **Ranked recommendations:** (1) the LunarCrush P5 gate; (2) apply to Higgsfield's partner program; (3) a backpressure cap on auto-filing; (4) an Earn test lane with a campaign block in the reach pack; (5) a gate-style QA rubric and versioned persona bibles. Then the Apify sounds trial, one programme per video and rising-creator discovery (section 5).
10. **Open:** the free key outside Claude (step 2); the Earn Terms text (the page loads in the browser only, so this file quotes search snippets); AI Invasion's real rules (behind LaunchPoint's login). Also: Earn's terms forbid sharing communications with the Earn team, so briefs and rates stay out of git.

---

## 1. Ghostfeed

### 1.1 What it is [E: ghostfeed.ai, /pricing, /blog]

- **Pitch:** "an operating system for running AI UGC at scale", aimed at app and product marketers. Its line: "One video. Hundreds of posts."
- **Features:**
  - **UGC reactions:** avatar reaction videos.
  - **Slideshows:** from a TikTok slideshow URL or a topic.
  - **AI avatars:** from a description, or a clone of your own face.
  - **Video cloning:** "remixes one video onto different avatars, so you can A/B test hooks and captions at scale".
  - **A timeline editor.**
  - **Posting:** scheduling to several TikTok accounts per workspace. Instagram, YouTube and Facebook are "coming soon".
  - **An MCP server.** It can create, but it "cannot post" and "cannot delete anything". It signs in with Google, no API keys.
- **Pricing:**
  - Free: 1 slideshow project.
  - Starter: $29 a month, 150 credits.
  - Growth: $49 a month, 300 credits, 3 workspaces.
  - Agency: $99 a month, 700 credits, 10 workspaces.
  - On credit cost the site is inconsistent: "1 credit = 1 second" at $0.14-0.18, but $1-2 a second for MCP video models, by its MCP post.
- **Managed service** (at capacity): "We buy real iPhones and US SIMs, warm fresh iCloud, TikTok, and Instagram accounts", posting daily. Its warm-up advice: 3-5 days of scrolling before the first post.
- **Analytics:** no analytics dashboard is described [E: homepage]. Its blog has more process than the product shows.

### 1.2 Fit for us [I]

- **As a tool: no.**
  - It posts to TikTok only, and we post Instagram-first through Postiz.
  - Its strengths (talking avatars, slideshows, product demos) are not our format (a character swapped into a dance or moment).
  - Its video costs ($0.14-2 a second) are above Genjutsu's: a Drop-in costs about 91 credits for 8 s, or $0.38-0.57 a second at $0.033-0.05 a credit [E: CLAUDE.md cost model; system review E2].
- **Risks of its model:**
  - Phone farms and warmed accounts are the inauthentic-behaviour pattern that TikTok and Meta enforce against.
  - "Platforms can't distinguish" content runs against our AI-label rule (CLAUDE.md: never post without the AI label).
  - "Hundreds of posts" from one video runs against our 2-a-day cap and the originality risk the system review rates highest (§ summary 13: reuse across accounts in one Accounts Centre).
  - Its own compliance post says to label synthetic content and not to evade. The marketing on its homepage says the opposite [E: /blog/meta-ai-ugc-compliance vs homepage].

### 1.3 What to copy (all free, from its blog) [E: the Ghostfeed posts named; the fit is my inference]

| # | Ghostfeed process | Our gap or match | Copy as | Effort |
|---|---|---|---|---|
| G1 | **Backpressure:** "stop upstream generation if editorial review queues exceed capacity (e.g. max 20 clips awaiting human review)" (/blog/ai-reels-automation-architecture) | The hits job auto-files up to 3 per character plus 3 general a day, about 65 a month, whether or not the owner keeps up [E: v3 spec §10]. Nothing in `config/scan.json` or `studio/hits.py` caps the open queue [E: grep] | `hits.max_open_drops` (e.g. 20): auto-filing skips when that many drops are waiting to be made or approved. This saves ScrapeCreators downloads and keeps old trends from piling up | S |
| G2 | **Approval goes stale:** "approval becomes stale if captions, audio, or disclosures change post-approval" | We should check whether an Adjust or a new hook after approval sends the clip back to Approve [I: not verified in code] | One rule in the publish guard: a caption, music or label change after `approved_at` needs approval again | S |
| G3 | **Gate-style QA, "any zero blocks the asset. A total score does not average away six fingers"** (17 checks in 3 gates: before animation, after animation, before publishing) | Our frame QA scores 6 frames [E: system review D] | Add pass/fail gates to the Gemini frame-QA schema: identity at the worst angle, the first second at half speed, hands and paws, the background stays boring, the sound fits the body, the ending is intentional. Any fail blocks | S |
| G4 | **Persona bible as rules, not a fake life story:** truth boundaries, voice rules, **10 approved and 10 rejected examples**, emotional range with approved source frames, recurring formats, **versioning: which persona parts each output used** (/blog/ai-creator-persona-bible) | Our bibles have voice and traits; the check's hooks drifted (17 of 19 suggestions went to Lenny; 8 hooks were one line) [E: `studio/gemini.py` docstring] | Add 10 approved and 10 rejected hook lines to each `bible.md`, fed to the check. Add a `bible_version` learning tag next to `hit_rules_version` | S |
| G5 | **Views-collapse diagnosis in a fixed order**, with a 72 h window: account status, recommendation eligibility, when the drop started (last 20 posts), the format that died, originality and rights, AI and ad disclosure, account lane, 2-second hook, cadence, device and network (/blog/tiktok-account-health-views-collapse) | Our early warning (0 views at 3 h on 2 posts) says what to check first, but not in what order after that [E: learning plan §5] | Add the ordered list to `docs/launch/measurement-and-learning-plan.md` §5 as the runbook | S |
| (match) | **"Change one meaningful variable at a time"**, results joined back to the hypothesis (lineage); no Cartesian product | We already have this: learning tags, `family_id`, pre-registered tests, a bandit over approved hooks [E: learning plan] | Nothing new | — |
| (match) | **Video cloning:** one source onto many avatars | This is our "one clip, up to three characters" (v3 spec §4) | Keep our caps; do not pitch it as a way past duplicate detection | — |

---

## 2. Apify

### 2.1 Relevant actors [E: each actor page, 8 Oct 2026]

| Actor | What | Price | Health |
|---|---|---|---|
| `clockworks/tiktok-scraper` | TikTok by hashtag, keyword, profile or URL: plays, likes, shares, sound, author followers. Optional video download | from $1.70 per 1,000 results; downloads extra | 311K users, 99.3% runs succeed, 4.76/5 |
| `apify/instagram-reel-scraper` | Reels by username or URL: views, likes, music, transcript, downloads. **No keyword search** | from $1.00 per 1,000 ($2.60 on the free plan) | 159K users, 100%, 4.39/5 |
| `apify/instagram-hashtag-scraper` | Posts and reels by hashtag or keyword | from $1.90 per 1,000 | — |
| `clockworks/tiktok-trends-scraper` | TikTok **Creative Center**: top hashtags, **sounds (popular or breakout)**, creators, videos; by country; 7, 30 or 120 days. **Rank and rank change, no daily curve.** At most ~100 hashtags or sounds | $1.70 per 1,000 | 3.1K users, 99.7%, 4.78/5 |
| `ryanclinton/tiktok-scraper` | Breakouts, creator momentum, sound lifecycle (emerging, accelerating, peak, cooling) | $5 per 1,000 | 12 users, no ratings: too new |
| **"LLM analysers":** `grizzlygriff/video-llm-analyzer` (Claude, GPT or Gemini over frames plus transcript), `frameprobe/reel-teardown` (hook style, scenes, cut rate, on-screen text, a "worth copying" score), `tubetext/video-breakdown-ai` | Each **downloads** the video and runs an LLM over it | about $0.015 + the LLM per video; $0.01 + $0.04 per video; $0.03 per video | 116, 20 and few users; video-llm-analyzer succeeds 82.8% |

**Plans** [E: apify.com/pricing]:
- Free: $5 of usage a month.
- Starter: $19.
- Scale: $199.
- Unused credit does not roll over.

### 2.2 Cost at our volume [I, from the prices above]

**Our volume:** 25-50 searches a day plus about 2 downloads [E: `config/scan.json` hits block: cap 45 a day, 2 downloads].
- **ScrapeCreators charges per call:** about 1 credit a search and 10 a download, at $47 for 25,000 credits [E: v3 spec §10]. That is about 30-70 credits a day, or **about $1.70-4 a month**.
- **Apify charges per result:** one search returns about 20-30 items, so 500-1,500 results a day, or 15-45K a month. At $1.70-3.70 per 1,000 that is **about $25-165 a month**.
- The free $5 covers about 3-5 searches a day.

### 2.3 Reliability [E: ScrapeCreators' benchmark, 19 Aug 2026, written by its founder]

On 1,000 Instagram post URLs:
- First-try success: Apify 100%, ScrapeCreators 99.6% (100% after one retry).
- Speed: ScrapeCreators 2.9× faster.
- Cost per 1,000 successes: Apify $2.30, ScrapeCreators $1.88 ($47 pack).

Both are reliable enough. Our hits job already handles misses.

### 2.4 Legal and ToS posture

- [E] Meta v. Bright Data (N.D. Cal., 23 Jan 2024): logged-out scraping of public Instagram and Facebook data did not breach Meta's terms, because a logged-out scraper is not a "user".
- [E] Apify's own position: public data is legal to scrape; take care with personal data (GDPR still applies) and data behind a login; "do not re-publish or sell original works"; it is a neutral platform ("we are not your lawyers").
- Neither changes our own rules [I]:
  - Research **metadata** from cloud APIs is fine.
  - **Downloading clips** stays one owner-approved or auto-filed pick at a time (CLAUDE.md "Never").
  - The LLM-analyser actors would download every clip they analyse, including hits we never filed. That breaks the rule.

### 2.5 Recommendation: no to the daily job; one optional test [I]

- **Replace ScrapeCreators? No.** It costs 10-50× less at our volume, is faster, and is already built and tested.
- **Add the LLM analysers? No.** Our Gemini deconstruct already does hook, moment, watermark, spans, potential and the recommended character on the one clip we fetch [E: `studio/gemini.py` docstring], at pennies a clip.
- **One narrow trial (S, free plan):** run `clockworks/tiktok-trends-scraper` on **sounds, breakout, GB and US, 7 days** once a week (~200 results, about $0.35, well inside the free $5).
  - Our gap: ScrapeCreators **retired** TikTok popular hashtags on 16 Jul 2026 ("TikTok no longer makes the underlying popular-hashtag data available") [E: docs.scrapecreators.com]. No popular-sounds endpoint was found there [I].
  - The Creative Center hashtag lists may be broken in Apify for the same reason. Sounds may still work. Test before trusting [I].
  - Adopt only if a month of runs brings at least 3 usable new sounds a week that our trending feed missed. Then feed each sound to ScrapeCreators' `GET /v1/tiktok/song/videos` (1 credit) for clips.

---

## 3. LunarCrush's free data

### 3.1 What the free mode returns (the MCP capability check, 8 Oct 2026, 8 calls) [E: tool results]

| Call | What came back free ("Limited data mode" footer on every answer) |
|---|---|
| `topic "dachshund"` | **24 h snapshot.** Engagements 20.9M (24 h) against a daily average of 26.0M. Per-network split (TikTok 17.5M, YouTube 3.0M, Instagram 120K). Mentions 2,005. Creators 1,282, "up 9.30% from 1,173 in the previous 24 hours". **1-year high and low with dates** (high 69.9M on 2026-04-14). Sentiment 82%. **Top 4 creators of the last 24 h:** @king_odiee, 5,634 followers, 4.85M engagements (the 29.3M-view hit of hit-patterns §3). The 1-week, 1-month and 6-month change fields say "N/A" |
| `topic "patient zero"` (a sound in hit-patterns §6) | The same, plus an **Insights** line: "mentions hit 5824 which is 1016% higher than it's daily average". 1-year high 122.6M on 2026-09-28; the last 24 h 11.9M, about 10% of that high |
| `topic_time_series "dachshund" 1d` | **24 hourly rows** (interactions, posts created, creators) up to 08:00 today |
| `keyword_time_series "single ladies" 1m` (network tiktok) | **30 daily rows**, 9 Sep to 7 Oct, with **per-network columns** (`tiktok_interactions` etc.). The network filter seemed ignored: all networks came back. Today's part day is not included |
| `keyword_time_series "ramalama" 3m` | Daily rows from 18 Aug only, with gaps: longer history is thin |
| `list musicians` | Ranked topics (engagements, mentions, creators, sentiment, TopicRank). **No change or rising column** |
| Limits | "Rate Limit Minute: 4", "Rate Limit Day: 100". **A refused call still counts** (the day's remaining fell 73 → 72 on a refused call). When I started, about 22 of the day's 100 were already used by other sessions |

**What the curves say today** [E, TikTok interactions column]:
- **"Single ladies":** peak 3 Oct at 1,156,085; 7 Oct at 289,927 (25% of peak). The peak was 4 days before the latest full day, so it **passes P5 by (a) only**, as "fading". The 4 Oct audit called it peaked [E: hit-patterns §2.2]; the curve agrees.
- **"Patient zero":** peak 28 Sep, about 10% now, 10 days on: **fails P5**. Yet its mentions are 10× the daily average. A second wave or a different meaning of the phrase: read it with care [I].

**Caveats** [I]:
- LunarCrush tracks a **sample** of posts: 4-11 TikTok posts a day for "single ladies". A few posts drive each day's total, so smooth it with a 3-day mean.
- Phrases are ambiguous: the X column jumped to 3.3M on 7 Oct for "single ladies", which is likely not the dance. Read `tiktok_interactions` only, with the summed total as the fallback.
- **Source check:** LunarCrush's docs say free ("Hobby") API keys get "market data endpoints" only, and the pricing page says the free plan has "1-hour and 24-hour social intelligence on Discover" [E: lunarcrush.com/pricing, /developers/api/ai]. This MCP session clearly gets social data in limited mode. I found no public notice of the update the owner mentions. **Whether a free key works from GitHub Actions must be tested** (step 1 below).

### 3.2 How it fits the hits job (ScrapeCreators finds the clips, LunarCrush dates the trend) [I, built on E]

**Today:** `studio/drop.py` (the tag builder; docstring and code around lines 1319-1350) reads `drop.trend_stage`, `drop.days_since_trend_peak` and `drop.sound_rising`. It sets `none`, None and false because the hits job never writes them [E: `grep trend_stage studio/hits.py` is empty]. `studio/clips.py:151` says "None until the hits job measures it". The P5 rule (hit-patterns §5) and its test (outlier_x by peak-age bucket 0-3, 4-7, 8+ days) wait for exactly this.

**The build (M, about 1 day plus tests):**
1. **`studio/lunar.py`: a minimal client.**
   - It calls the hosted MCP endpoint `https://lunarcrush.ai/mcp` (JSON-RPC `tools/call`, `Authorization: Bearer`) [E: lunarcrush.com/developers/mcp]. The key is a GitHub secret, `LUNARCRUSH_API_KEY`.
   - Calls are 16 s apart (4 a minute). A refused call is never retried in the same minute.
   - **`hits.lunar_daily_cap` defaults to 40**, leaving 60 of the 100 for the owner's and the weekly review's MCP use.
   - The answers are Markdown tables: parse them into rows. Record today's answers as test fixtures (no network in tests).
2. **Trend key per hit:** the hit's `sound`, unless it is a generic "original sound - <handle>". Else a trend name in the caption that matches the character's keywords or `config/events.yaml`. Classics skip the check.
   - One check per distinct key per London day, cached in a small table (migration, additive, schema `studio`): `trend_checks(key, day, peak_day, peak_value, latest_value, ratio, days_since_peak, stage)`.
3. **`trend_curve(rows)`** on `keyword_time_series(key, interval=1m)`, with the 3-day mean of `tiktok_interactions`:
   - **peak:** the peak day is today or yesterday;
   - **rising:** the latest day is at or near the peak and the last 3 days climb;
   - **fading:** the peak was 7 or fewer days ago, or the latest day is at 50% or more of the peak;
   - **dead:** neither.
   - `days_since_trend_peak` = days since the peak day. **The P5 gate:** a dead trend is never auto-filed; a rising one gets a small score bonus.
4. **Write** `trend_stage`, `days_since_trend_peak` and `sound_rising` (true when the snapshot's Insights line shows a spike) onto the hit, and into `proposal.drop` when `add_drop` files it. The tags then flow into every clip with no change to `drop.py`.
5. **Light "rising" discovery** (from the same budget; metadata only):
   - (a) `topic` on each live character's 3 keywords plus the 4 general keywords (7 calls): keep the spike line and the **top-4 creators of the last 24 h**. For a creator with fewer than 50K followers and more than 1M engagements in 24 h, call ScrapeCreators' profile videos (1 credit, at most 3 a day) and score those posts as hits. Today this would have found @king_odiee.
   - (b) `list musicians` once a day: store the rank; an artist who climbs 10 or more places becomes a general keyword for that day.
   - (c) Each sound seen twice or more in the TikTok trending feed gets one `topic` call. A spike → `sound_rising`, and ScrapeCreators' `GET /v1/tiktok/song/videos` (1 credit) for clips using it.
   - **Budget:** about 7 + 1 + ≤15 trend checks + ≤10 sounds ≈ 33 calls, about 9 minutes at 16 s spacing. Run it as its own step after `hits pull`.
6. **Fallback if the free key cannot reach social data outside Claude:**
   - (i) Run the same check in the daily Claude task through the MCP (it works there today, but it puts a step back on the Mac).
   - (ii) Pay for Individual: $90 a month, 2,000 calls a day, full data [E: pricing].
   - My pick is (i) until the first 7-day figures show that trend age matters (the pre-registered P5 test). That keeps money out of it until there is evidence.

---

## 4. Higgsfield Earn

### 4.1 Facts

| Topic | Finding | Label |
|---|---|---|
| Exists, who runs it | Higgsfield's own programme, higgsfield.ai/earn. "Over $1M to 10,000+ creators", "90% approval", "50,000+ submissions" | [E: earn page via search] |
| "$1 per 1,000 views" | **Not on Higgsfield's pages.** Higgsfield: "Payout rates are confidential. Rates are set individually". A third-party guide: "Launchpoint has a $1 million rewards pool paying creators $1 for every 1,000 views on AI character content". LaunchPoint lists Higgsfield as a customer (700+ creators, 2,000+ accounts, 350M+ views) | [E: help centre; youmind guide; launchpointhq.com case study] |
| Pay structure | "3-tier rewards: receive a payment for every approved video, plus 24-hour and 7th-day bonuses". "An earning cap of $1,000 on the first day, with a maximum lifetime payout of $2,500 per video". A weekly creator pool capped at $100,000 overall. Money is claimable after the day-7 milestone; paid out "via Garna" | [E: earn page; help centre; sozee.ai] |
| Which characters | "Use a character you already have or create one in AI Influencer Studio". One review (Jan 2026) says the videos must be made with Higgsfield's tools | [E: help centre; joeyoungblood.com] |
| Platforms | "Active Instagram, YouTube, or Twitter (X) accounts". Instagram connects automatically; YouTube and X by a code in the profile. "Only one YouTube account can be connected". **TikTok is not listed** | [E: help centre; Higgsfield blog] |
| Joining | Log in with email, connect Instagram, put a code (e.g. "Higgs Influencer") in the bio for a while. No follower minimum. "Access … depends on your country" | [E: earn page; help centre] |
| Campaigns | Matched "based on audience, platform, and fit", so an empty list is normal. Each brief sets format, platform, "required hashtags and mentions" and a minimum video length. The video must go out "within the specified campaign window", "on an approved platform", and "include the required promo code or tracking link". Submit by pasting the post link in the dashboard | [E: help centre via search; Earn terms via search snippet; earn page] |
| Checks | "Automated content verification" of requirements and engagement. A video can be rejected "without manual review", "including … suspicious activity". "Each rejected submission is eligible for one appeal" | [E: Earn terms via search snippet; help centre] |
| Confidentiality | Participants may not "share, publish, screenshot, or otherwise disclose communications with the Earn team to any third party" without consent | [E: Earn terms via search snippet] |
| Exclusivity | None found for Earn. The partner program says "no posting quotas, no exclusivity" | [E: absence on the Earn pages; CPP blog] |
| AI or ad label | The Earn pages say nothing. A review: Earn content counts as "sponsored content and paid promotion" under FTC rules | [E: joeyoungblood.com] |
| Higgsfield MCP | No Earn tool (`apps_search "earn"` returned nothing). `show_characters` lists one Soul: **Lenny Gold (soul_2, ready)** | [E: tool results] |
| Bonus | Signing up to Earn reportedly came with a month of Higgsfield Ultimate free (one creator, Jan 2026) | [E, weak: skool.com post] |

The Earn Terms page (creators.higgsfield.ai/terms) builds its text in the browser, so a fetch got the title only. The quotes above come from search-engine snippets of that page. Read the full terms before the first submission.

### 4.2 Do we qualify? [I unless marked]

| Requirement | Our state | Gap or change |
|---|---|---|
| A character made with Higgsfield | Lenny has a Soul 2 [E]. Franz has a Higgsfield Element [E: `characters/franz/refs.json` `element_id`]. All masters and sheets are gpt_image_2_5 stills made in Higgsfield, and every video is a Genjutsu render [E: refs `_doc`] | Probably fine. If a brief demands an AI Influencer Studio character, make one per character there |
| Original footage | **Drop-ins swap our character into other people's clips** (CLAUDE.md default). The automatic check and the general terms' user-content section (§5) are built to catch copied content [E: LaunchPoint "copied videos get caught"; Earn "automated verification"] | **Submit only Recreates, own footage (the owner's phone clips) and image-to-video from our stills.** Never a Drop-in. The tag `source_kind` / `format_id` already tells them apart [E: `studio/drop.py`, the tag builder] |
| Platform | Instagram is our main channel; TikTok is not live yet | Instagram first; TikTok does not count for Earn |
| Posting through Postiz | Earn tracks the pasted link, so the posting tool does not matter | The caption must carry the brief's hashtags, @mentions and tracking link **at publish time**. Today the reach pack writes the caption, first comment and collaborators [E: v3 spec §11] but has no campaign fields |
| Window, length | Our masters run 6-16 s, posted at fixed slots | A brief's minimum length or window can clash with a slot. Check each brief |
| AI label | We always label [E: CLAUDE.md] | Keep it. **Add "#ad" (or Instagram's paid-partnership label) on paid campaign posts.** The owner is UK-based, and the ASA treats paid content under a brief as an ad [I: UK CAP code; FTC per joeyoungblood] |
| 2 posts per account a day | Binding [E: CLAUDE.md] | Earn posts count toward it |
| Confidentiality | Our docs live in git | Keep Earn briefs, rates and messages out of the repo. Store only the fields the post needs (hashtags, mentions, link, window) |

### 4.3 Earn compared with LaunchPoint "AI Invasion"

| | Higgsfield Earn | LaunchPoint "AI Invasion" (roadmap) |
|---|---|---|
| Rate | Confidential, per campaign: a fixed payment plus 24 h and day-7 bonuses [E] | $1 per 1,000 verified views [E: owner's source, `docs/AI_INFLUENCERS.md` §4a] |
| Cap per video | $1,000 on day 1, $2,500 in total [E] | $2,000 [E: same] |
| Platforms | Instagram, YouTube, X [E] | Instagram, TikTok, YouTube, Facebook, Snapchat (LaunchPoint in general) [E: launchpointhq.com] |
| Footage | Rules not public; the automatic check catches fraud [E] | "Your own recordings, or footage you have permission to use" [E: §4a, to be verified] |
| Fraud check | "Automated content verification" [E] | "Darwin": "Fake views and copied videos get caught before anyone is paid" [E] |
| Access | Self-serve; campaigns matched to you [E] | The owner signs up in LaunchPoint's creator app (behind a login) [E: §4a] |

**Reading** [I]: the owner's guide probably merges the two. Both are funded around Higgsfield. A video sent to both may be flagged as a duplicate claim. **Rule: one programme per video**, recorded on the clip (a new `income_programme` tag: `earn` / `launchpoint` / `none`).

### 4.4 Recommendation on Earn [I]

- **Apply now (S, owner).** Sign up at higgsfield.ai/earn with **one Instagram account** (the live one with the most followers), do the bio check, and **screenshot the campaigns offered**. It is free, has no exclusivity that we found, and may come with a month of Ultimate. If no campaign fits, nothing is lost.
- **Build only when a campaign fits (S-M):** a `campaign` block on a clip (hashtags, mentions, tracking link, window, minimum length, "#ad"). The reach pack appends it to the caption, and the publish guard refuses a post outside the window.
- **Produce for Earn only from own footage, Recreates or our stills.** The growth lane stays Drop-in by default (owner decision, CLAUDE.md).
- **Expect little at first:** at 5-20K views a Reel, $1 per 1,000 is about $5-20 a video [I]. Earn matters only with breakouts. **Higgsfield's Creator Partnership Program is likely worth more:** "a full plan renewed every month, plus additional credits", "no posting quotas, no exclusivity". The only ask is to "tag or mention Higgsfield when the tools are part of your work" [E: higgsfield.ai/blog/creator-partnership-program]. At 130-160 credits a video against a 6,000 cap, a free plan is a direct cost cut [E: system review E2].

---

## 5. Ranked recommendations (impact against effort)

| Rank | What | Impact | Effort | First concrete step |
|---|---|---|---|---|
| 1 | **LunarCrush P5 gate and trend tags in the hits job** (§3.2) | High: fills 3 empty learning tags; stops filing dead trends; makes the P5 test possible | M | Owner: make a free LunarCrush API key, then `gh secret set LUNARCRUSH_API_KEY`. Claude: one Python test call to `https://lunarcrush.ai/mcp` (`keyword_time_series "single ladies" 1m`) to confirm the free key gets social data outside Claude |
| 2 | **Apply to Higgsfield's Creator Partnership Program** | High: a monthly plan of credits, our tightest limit | S (owner) | Owner applies at higgsfield.ai/creator-partnership-program with the live accounts. If accepted, add "@higgsfield.ai" to the caption template and mention Higgsfield in each bio |
| 3 | **Backpressure on auto-filing** (G1) | Medium: saves downloads, keeps the queue fresh, protects the owner's time | S | Add `hits.max_open_drops: 20` to `config/scan.json`; in the auto-file step, skip when the count of open (unmade or unapproved) drops reaches it |
| 4 | **Earn test lane** (§4.4) | Medium: some income; teaches us what briefs ask for | S now, S-M later | Owner signs up at higgsfield.ai/earn with one Instagram account, does the bio check, and screenshots the campaign list and one brief |
| 5 | **Gate-style QA and versioned persona bibles** (G3, G4) | Medium: fewer bad clips; less hook drift; a `bible_version` tag to learn from | S | Add 10 approved and 10 rejected hook lines to `characters/lenny/bible.md` first (the drift was his) and pass them to the check |
| 6 | **Apify breakout-sounds trial** (§2.5) | Low-medium: may add rising sounds | S | Owner makes a free Apify account; Claude runs `clockworks/tiktok-trends-scraper` once (sounds, breakout, GB, 7 days, ~100 results ≈ $0.17) and compares it with a week of our trending feed |
| 7 | **One programme per video**, `income_programme` tag (§4.3) | Low now; protects payouts later | S | Add the tag to `LEARN_VALUES` in `studio/clips.py` when the first income clip is made |
| 8 | **Rising-creator discovery from LunarCrush's 24 h creators** (§3.2 step 5a) | Low-medium | S on top of rank 1 | After rank 1 works: 7 `topic` calls a day; profile pulls capped at 3 credits |
| — | Not recommended | Ghostfeed as a tool; Apify replacing ScrapeCreators; Apify LLM analysers; Drop-ins submitted to Earn or AI Invasion | — | — |

---

## Sources

**Ghostfeed**
- [Ghostfeed home](https://ghostfeed.ai/)
- [Ghostfeed pricing](https://ghostfeed.ai/pricing)
- [Ghostfeed blog index](https://ghostfeed.ai/blog)
- [AI Reels automation architecture](https://ghostfeed.ai/blog/ai-reels-automation-architecture)
- [Creative variation matrix](https://ghostfeed.ai/blog/ai-ugc-creative-variation-matrix)
- [17-check quality checklist](https://ghostfeed.ai/blog/ai-ugc-quality-checklist)
- [Persona bible](https://ghostfeed.ai/blog/ai-creator-persona-bible)
- [Ghostfeed MCP](https://ghostfeed.ai/blog/ghostfeed-mcp-claude)
- [Meta AI UGC compliance](https://ghostfeed.ai/blog/meta-ai-ugc-compliance)
- [TikTok account health](https://ghostfeed.ai/blog/tiktok-account-health-views-collapse)
- [Three-layer AI UGC stack](https://ghostfeed.ai/blog/three-layer-ai-ugc-stack)

**Apify and ScrapeCreators**
- [Apify pricing](https://apify.com/pricing)
- [clockworks/tiktok-scraper](https://apify.com/clockworks/tiktok-scraper)
- [apify/instagram-reel-scraper](https://apify.com/apify/instagram-reel-scraper)
- [apify/instagram-hashtag-scraper](https://apify.com/apify/instagram-hashtag-scraper)
- [clockworks/tiktok-trends-scraper](https://apify.com/clockworks/tiktok-trends-scraper)
- [ryanclinton/tiktok-scraper](https://apify.com/ryanclinton/tiktok-scraper)
- [Video → LLM Analyzer](https://apify.com/grizzlygriff/video-llm-analyzer)
- [frameprobe/reel-teardown](https://apify.com/frameprobe/reel-teardown)
- [tubetext/video-breakdown-ai](https://apify.com/tubetext/video-breakdown-ai) (from search results)
- [Apify blog: analyse social videos](https://blog.apify.com/analyze-social-media-videos-for-creative-intelligence/)
- [Apify blog: is web scraping legal](https://blog.apify.com/is-web-scraping-legal/)
- [Quinn Emanuel on Meta v. Bright Data](https://www.quinnemanuel.com/the-firm/news-events/client-alert-meta-v-bright-data-significant-decision-for-web-scraping-industry/)
- [ScrapeCreators benchmark vs Apify](https://scrapecreators.com/blog/apify-instagram-scraper-benchmark)
- [ScrapeCreators docs](https://docs.scrapecreators.com/)
- [ScrapeCreators popular hashtags (retired)](https://docs.scrapecreators.com/v1/tiktok/hashtags/popular)
- [ScrapeCreators popular creators](https://scrapecreators.com/tiktok/endpoints/get-popular-creators)

**LunarCrush**
- [LunarCrush pricing](https://lunarcrush.com/pricing)
- [LunarCrush API and AI docs](https://lunarcrush.com/developers/api/ai)
- [LunarCrush MCP](https://lunarcrush.com/developers/mcp)
- LunarCrush MCP tool results, 8 Oct 2026 (`topic`, `topic_time_series`, `keyword_time_series`, `list`)

**Higgsfield and LaunchPoint**
- [Higgsfield Earn](https://higgsfield.ai/earn)
- [Higgsfield help centre: partnership and creator programmes](https://higgsfield.ai/creator-hub/help-center/business/how-do-i-join-a-partnership-or-creator-program)
- [Higgsfield blog: Earn](https://higgsfield.ai/blog/Higgsfield-Earn-Talent-And-Collaboration-Monetization)
- [Higgsfield Creator Partnership Program](https://higgsfield.ai/blog/creator-partnership-program)
- [Higgsfield Earn Terms](https://creators.higgsfield.ai/terms) (quoted from search snippets)
- [Higgsfield AI Influencer](https://higgsfield.ai/ai-influencer)
- [Joe Youngblood on Earn](https://www.joeyoungblood.com/creator-marketing/higgsfield-launched-earn-a-way-for-creators-to-earn-money-with-generative-ai-videos/)
- [Sozee on Higgsfield monetization](https://www.sozee.ai/resources/higgsfield-ai-influencer-monetization/)
- [YouMind AI-influencer monetization guide](https://youmind.com/landing/x-viral-articles/ai-influencer-monetization-guide)
- [Skool post: paid by Earn](https://www.skool.com/aiography/i-made-an-ai-influencer-with-higgsfield-ai-got-paid)
- [LaunchPoint](https://www.launchpointhq.com/)
- [LaunchPoint × Higgsfield case study](https://www.launchpointhq.com/case-studies/higgsfield)
- Higgsfield MCP results, 8 Oct 2026 (`apps_search "earn"`, `show_characters list`)

**Repo**
- `CLAUDE.md`
- `docs/AI_INFLUENCERS.md` §4a
- `docs/superpowers/specs/2026-10-07-terminal-v3-design.md` §10-11
- `docs/research/2026-10-07-hit-patterns.md` (P5)
- `docs/research/2026-10-07-system-review.md` (E1, E2)
- `docs/launch/measurement-and-learning-plan.md`
- `studio/drop.py` (the tag builder), `studio/clips.py`, `studio/gemini.py`, `studio/hits.py`
- `config/scan.json`
- `characters/*/refs.json`
