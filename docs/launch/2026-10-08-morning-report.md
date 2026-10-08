# Morning report, Thursday 8 October 2026

*Written overnight while you slept. Updated as the work finished; the last section is what needs you.*

## 1. Your decisions this morning (2 minutes each)
1. **GitHub Actions is blocked: fix billing first** (github.com → profile menu → Settings → Billing and licensing).
   - The account used up its 2,000 free Actions minutes for October, and since 04:35 London GitHub refuses every cloud job:
     the clip checks, the publish job and the hits job.
   - About 1,800 of those minutes went on the automatic test run after every push. The tests now run in the cloud only
     when code changes, one run at a time (they also run on the Mac before every commit).
   - Fix a failed payment if there is one, then set an Actions budget of about **$15 a month**. My estimate of the real
     need is under $10 a month above the free minutes.
   - Until then nothing posts (Franz 19:00, Reginald 19:30), the 15 clips waiting for their free check stay "checking",
     and the first Hot right now list cannot come in.
2. **A posting backup on the Mac, yes or no.** It runs the same publish step from the Mac every 5 minutes. It posts only
   what you approved, at its slot, and never while the kill switch is on. It cannot post twice: the database claims each
   post once. Not installed: it needs your yes.
3. **Approve Franz's first video** (Videos, or the approval list on Today). Tall Franz in the night street dance, 6 s, the
   "Sausage coming through." pill, a zoom hit on his big move, the pinned-comment vote. Slot: **19:00 today** (needs 1 or 2).
4. **Reginald's Reel shows 0 views** (Instagram's own count, 3 h after posting; 1 follower). On your phone: Reginald →
   Settings → **Account Status**. If anything says his content can't be recommended, that is the cause; tell me what it says.
5. **Log back in to Instagram in Chrome** (my account switch last night logged it out; I won't switch accounts again).
6. **Meta developer app for Instagram's own API** (about 10 minutes, I guide you): it gives us the per-post AI label, the
   cover frame and real stats from the cloud. Build step 9 starts as soon as it exists.
7. **Turn on billing for the Gemini key** (Google AI Studio → your key's project → Billing). Last night the free tier hit
   its daily limit after about 50 video checks; 11 checks failed on it. Paid, one check costs well under 1p.
8. **ScrapeCreators credits:** the daily hits job is capped at 45 credits a day. The 100 free credits last about 2 days; the
   $47 pack (25,000 credits, they never expire) lasts well over a year. Buy it when you are happy with the first lists.
9. **Trial Reels**, yes or no (Instagram shows a new Reel to non-followers first; it stays off the grid until it graduates).
10. **Higgsfield's Creator Partnership Program**: apply (a free monthly plan for tagging Higgsfield, no quotas, no
    exclusivity). Credits are our tightest limit, so this is worth more than Earn. Details in section 8.

## 2. What is done (overnight, every step reviewed, about 2,700 tests green)
- **Clip score 0-100** on every clip (Gemini's "will it get views" with the hit rules + how easy the swap is), hit rules in
  every check (7-word hooks that the clip proves, a vote as the pinned comment), Franz's happy show-off voice.
- **One clip, up to 3 characters** ("Use for another character"), each version checked in its own voice, posts of the same
  clip kept 14 days apart (database + scheduler).
- **Suggestions spread across characters** (the check sees who has few clips) and **fresh hooks** (it sees the last 10).
- **Tall Franz is official**: references, character file, QA rules, terminal; a performance line for funnier moves; "star".
- **Learning tags on every video** (hook pattern, trend, length, score, family ...) so the studio can learn what works.
- **Database updates 0015 and 0016 applied live** (checked byte for byte).
- **Terminal**: Studio at a glance (per character: ready, to approve, views today / 7 / 30 days, next post, runway, test
  status), Make these (tick the top clips, one confirm with the total and budget), Approve these, Clips by character
  (ranked, Top pick badges, reuse, folded problems), Hot right now + Worth saving, a Keep toggle. Phone first.
- **The ScrapeCreators hits job** (daily 06:30, no Mac): searches per character + a general lane, scores the hits, files
  the best as clips (3 a day per character + 3 general), cleans up unused clips after 30 days (60 for yours), credit caps.
- **The reach pack** (first comment posted with the Reel, every Reel also as a Story, series hashtags, collab posts, a Trial
  Reels switch): see section 3 for its state.
- Marketing skills wired in, a measurement and learning plan, an independent system review.

## 3. Your clips, ranked per character
**Not ranked yet: the free check runs in the cloud, and the cloud is blocked (decision 1).** State at 09:45:
- **20 clips wait for their check** ("checking" in the terminal). Of these:
  - 15 are the 11 that hit Gemini's free limit last night plus 4 that were ready with a score. I sent those 4 back this
    morning so they get the new hit rules and the character spread.
  - The other 5 were already waiting.
  - Side effect: until the check runs, Make these shows nothing ready. Their earlier scores were Reginald 80 and 58,
    Lenny 72 and 68.
- **9 are blocked** (burned-in text or another creator's watermark): not usable as Drop-ins.
- **1 failed paid make** (25889785, Reginald, yellow jumpsuit; Higgsfield answered 401 on 7 Oct). It needs your OK
  before any retry.
- Most of these were filed under Lenny before the spread rule existed. The new check re-suggests the character per clip
  (Franz now also takes people), so expect a fairer split once it runs.

Once billing is fixed, the 2-hourly sweep checks all 20 within about 2 hours (free). The ranked list then appears under
Make these on Today, with the top picks per character.

## 4. Hot right now and Worth saving
**Not filled yet.** The hits job (`studio-hits.yml`, daily 06:30 London) has not had its first run: it is in the cloud
too. After the billing fix I run it once by hand. It searches per character plus the general lane, scores what it finds,
files the best 3 a day per character plus 3 general as clips (free check), and shows the rest under Hot right now on the
Clips page.

## 5. The independent review: the 5 changes that matter most
Full text: `docs/research/2026-10-07-system-review.md`.
1. **Measure properly from the first post:** Instagram's own numbers from the cloud (views, reach, follows, how fast people
   scroll away), the per-post AI label, and real tags on every clip (hook pattern, trend, score) so we can learn what works.
   → build step 9 (Instagram API) plus tags in the check.
2. **Move the daily and weekly runs off your Mac** into the cloud (GitHub), like your crypto project already does.
3. **Make the scoring learn:** test the score against real results before it steers spend; try hook and caption options
   automatically; change the hit rules only with evidence.
4. **Search wider:** trending feeds, rising sounds and rising creators (the hits job's general lane does the first part).
5. **A quality bake-off** when credits return: Genjutsu vs Kling 3.0 vs Wan Animate on the same 3 clips, tall Franz included.

Also from the review: 3 characters posting Monday to Friday need about 8-10K credits a month, more than the 6,000 cap
(my earlier "5,900" assumed 8-second videos only).

## 6. My suggestions (in order)
1. **TikTok accounts this week.** TikTok gives brand-new accounts far more reach to strangers than Instagram does; every
   video then posts to both for the same credits. Your step on the phone, about 5 minutes per character (I guide you).
2. **Trial Reels on for the new Instagram accounts** until about 1,000 followers each (decision 5 above).
3. **1 video in 3 is the character's own series**, not a swap: lowers the "reused content" risk the review flags, and it is
   what brands sponsor and LaunchPoint pays for (about 160 credits instead of about 100).
4. **The characters help each other:** follow each other, comment in character on each other's posts, a weekly collab post
   ("same dance, who did it best?") that shows on both profiles.
5. **An intro Reel pinned on each profile** ("Meet Franz: Sausage coming through") when credits return.
6. **The credit plan before 19 Oct:** 3 characters Monday to Friday need about 8-10K credits a month (cap 6,000). My advice:
   3 a week per character until the first hit, then scale.

## 7. The learning plan (new, `docs/launch/measurement-and-learning-plan.md`)
How the studio learns from its numbers, written down BEFORE any results so we can't fool ourselves:
- one deciding number per post (views at 7 days against the account's usual), read at 24 h, 72 h and 7 days;
- 13 tags on every video (hook pattern, trend stage, length, score, family, trial reel ...) so we can see what works:
  **today every drop video carries the same tags, so this is built first** (build step 10, tonight);
- six tests fixed in advance (does the score predict views; which hook style; Trial Reels; own series vs swaps; length;
  vote vs question), honest about what ~20 posts can show (only big effects);
- early warnings (e.g. 0 views at 3 h twice in a row → check Account Status).

**Your decisions before 14 Oct** (Reginald's first 7-day number): the kill bar while TikTok is missing (Instagram-only, or
TikTok connected first); Trial Reels as a half-and-half test or all on; 1 in 3 own series; a length test (+~500 credits);
1 made clip in 4 picked from below the median score (so we can tell whether the score works); approve the plan.

## 8. Your research questions (this morning; full reports in `docs/research/`)
**Video tools** (`2026-10-08-video-tools.md`):
- **CapCut can't be automated.** It has no editing API, its export needs the desktop app, and its terms ban scripts. The
  tutorial you sent is not Claude driving CapCut: Claude writes files (a colour file, subtitles) and Remotion graphics, and
  the person imports them into CapCut by hand. At most CapCut is your manual polish for a rare hero video, and never with
  its library music (not cleared for commercial use).
- **Remotion fits later, as an overlay only.** It renders a transparent animated layer (kinetic hook, series card);
  ffmpeg composites it and keeps the sound, loudness and checks as today. It is free for a company of up to 3 people.
  Node is already on the Mac.
- **MoneyPrinterTurbo** makes faceless stock-footage videos (script, voice, B-roll), so the pipeline does not fit us.
  Two small pieces are worth borrowing: a subtitle "pop" easing and a colour tag.
- **The quick win is in our own editor:** zoom pulses on the beat (we already detect beats) and word-by-word hook
  pop-ins for every character. Each is a tagged A/B test, never switched on blind. My next build step after this one.

**Viral comps** (`2026-10-08-viral-comps.md`): Jean Phil (`@jean_philanthrope`, ~267K TikTok, ~238K IG) and Abu
Shalab (`@abu.shalab`, ~409K TikTok, ~510K IG) are made the way we make our videos: real phone footage with one fixed AI
character swapped in. What made them big:
1. Each clip is the character's own two-beat bit: something ordinary, then the signature move.
2. Daily or more: Jean Phil's TikTok engagement fell 90% once he slowed down.
3. Captions of 2-7 words in the character's voice. Abu's biggest is a "false brag" (24M engagements).
4. Other people's remixes multiplied them.

Never copy: their meme coins, posing as real people, or a culture's dress as the joke.

**Data and money** (`2026-10-08-tools-data-earn.md`):
- **LunarCrush's free tier** (100 calls a day) can give each trend's peak date. That fills our empty trend tags and
  enforces the "still fresh" rule. Step: a free key, tested first.
- **Apify: no.** About $25-165 a month against about $2-4 for ScrapeCreators, and its LLM clip analysers repeat our free
  Gemini check.
- **Ghostfeed:** one idea worth copying: pause auto-filing when 20 or more clips are waiting.
- **Higgsfield Earn is real, but the guide's "$1 per 1,000 views" is not Higgsfield's figure.** It pays per approved
  campaign video at confidential rates, on Instagram, YouTube and X (not TikTok). Drop-ins on other people's clips should
  never be submitted, only Recreates and own footage.
- **Higgsfield's Creator Partnership Program** (a free monthly plan for tagging Higgsfield) is worth more to us: decision 10.

**Your prompt kit** is saved word for word in `docs/influencers/prompt-kit.md`, with our rules added (odd eyes in every
prompt plus a "matching eye colours" negative, no brands, Franz's dog version). The swap prompt gets the guide's two
lines in the final review.
