# Growth and monetization while the credits are out (28 Oct 2026)

**Where we are.** 3 characters live, Instagram only. 9 Reels, 31 Stories (7 after a Reel, 24 daily re-shares), about 1,365 Reel
views, median about 130 per Reel. Only 1 Reel since 15 Oct: the Higgsfield API wallet is empty, so every cloud make gets HTTP 403.
87 approved drops are waiting. Trial Reels were switched on for all three on 28 Oct (owner).

## 1. The finding that matters most: originality

- Instagram (Apr 2026): accounts that mostly repost other people's work lose recommendation eligibility. Crediting the creator
  does not make a post original. An edit that adds something may count, but no platform says whether a character swap on the
  original audio is enough. [ig-orig] [ig-rec] [tc]
- The same gate sits in front of every payout programme: YouTube's reused-content rule ("even if you have permission"), TikTok's
  originality rule for the For You feed and Creator Rewards, Facebook's unoriginal-content rule, Snapchat's re-upload ban.
- Our format (Drop-in default, owner 2026-10-05) puts our character into someone else's viral clip, with their audio and their
  credit. That is likely part of why reach stays near 130, and it is the gate for every monetization route below.
- **Owner decision** (it touches the open "footage" conflict in `docs/AI_INFLUENCERS.md`): keep Drop-in as the default for
  everything, or make a fixed share of the videos fully original once credits return (own scenes, Recreate with an AI beat,
  recurring character bits). The KPI bars stay as they are either way.

## 2. Credit-free growth moves, ranked

**Owner 2026-10-28: Instagram first, TikTok later.** Done or started that night: Trial Reels on; the 9 posted clips reposted as
Trial Reel variants (new hook and cover, no credits); daily comment drafts; the profile pass (owner applies it); Launchpoint
profiles drafted (`docs/launch/launchpoint-profiles.md`).

| # | Move | Claude does | Owner does |
|---|---|---|---|
| 1 | **TikTok for all three.** The posting code is ready (`TIKTOK_SETTINGS`, AI flag on). | Re-seed with the ids, check the first post | Create the 3 accounts (handles in `characters/*/social.md`), switch the AI label on, connect each in Postiz, send the integration ids |
| 2 | **Daily comment drafts.** 5 fresh niche posts per character from cloud data, with in-voice comments, plus replies to comments on our own posts. | Build the daily-run step, draft every day | Post them in the app (about 10 min). Claude never posts a comment |
| 3 | **Profile pass.** Bios, display names, 3 pinned Reels, highlights. | Draft the text | Apply it in the app |
| 4 | **YouTube Shorts, Facebook Reels, Threads** from the same masters. Threads also takes in-character text posts: original content at zero credits. | Add the platforms to the studio (enum, Postiz settings: YouTube needs a title, type and kids flag) | Create the channels and Pages, connect them in Postiz |
| 5 | **Re-master variants** for the other platforms (new hook text and cover) from the existing generations. Instagram keeps unique versions. | `bin/studio master build`, free | Nothing |

Not now: posting-time tuning (9 posts give no signal).

## 3. Monetization, in the order it can happen

| Route | Bar (UK) | Pay | When |
|---|---|---|---|
| Amazon Associates UK (Franz, pet supplies) | Application, `#ad` disclosure | 3% on pet supplies [amz] | Now (the owner applies) |
| TikTok Shop UK affiliate | 500 TikTok followers, 18+ [tts] | Seller-set commission | Weeks after TikTok starts |
| UGC and brand work with ORIGINAL character content | No audience bar | About £50-250 a video (agency blog figures) [ugc] | Now, with a media kit (Claude drafts, the owner sends the pitches) |
| YouTube Shorts fan funding and Shopping | 500 subs, 3 uploads, 3M Shorts views in 90 days [yt500] | Fan funding, Shopping | 12+ months unless a breakout |
| Ad-revenue programmes | TikTok Rewards: 10k followers, 100k views/30 days, **60 s+ videos** [ttcr]. YouTube ad share: 1k subs + 10M Shorts views/90 days [ypp]. Facebook: invite-only. Snapchat: 50k followers, **30 s+** [snap] | Small per 1,000 views | 6-18 months, original content only |
| Clipping campaigns (Ssemble Clip Rewards, Whop Content Rewards) | Public account | About $1 per 1,000 views [ssr] | Not on the character accounts: it counts as aggregation |

## 4. Ssemble (app.ssemble.com)

An AI clipper that turns long-form video (YouTube, Twitch, podcasts) into shorts and posts them. Its money side, Clip Rewards,
pays clippers about $1 per 1,000 views to spread campaigns that a creator or brand funds. **Not a fit now:** we already make
finished 8-15 s clips, our swaps are not anyone's campaign content, and paying for distribution at a 130-view median is early.
Its API makes shorts only (no posting, no analytics). Revisit if the characters ever have long-form content. [ss] [ssr] [ssapi]

## 5. Decisions for the owner

1. Originality: Drop-in for everything, or a share of fully original videos (section 1).
2. TikTok: create the three accounts (the top owner step).
3. AI label on YouTube and Facebook: Postiz has no synthetic-content flag for YouTube. A caption line plus the profile, or the
   toggle by hand in YouTube Studio?
4. The 2-posts-a-day cap: per platform account? Do Stories and Threads text posts count?
5. Third-party music on YouTube and Facebook: accept the mute or claim risk, or post those clips on TikTok only?
6. Allowlist (your `.claude/settings.json`): `crosspost`, `content-engine`, `brand-voice` for scheduled drafts; and deny vidIQ's
   `vidiq_reply_to_comment` and `vidiq_generate_comment_replies` so "we never reply ourselves" is enforced, not just written.
7. Lenny's `a3bb5db5` ends with a middle finger: check it before it goes to any new platform.
8. Higgsfield top-up: it has to go into the API wallet (the cloud's), not the app wallet.

## Sources (all https://)

- [ig-orig] creators.instagram.com/original-content-guidelines/
- [ig-rec] creators.instagram.com/recommendations-and-Originality
- [tc] techcrunch.com/2026/04/30/instagram-restricts-reach-of-content-aggregators-in-new-crackdown/
- [ttcr] tiktok.com/legal/page/global/tiktok-creator-rewards-program-eea/en (EEA text; the UK page did not load)
- [ypp] support.google.com/youtube/answer/72851 · [yt500] support.google.com/youtube/answer/13429240
- [snap] help.snapchat.com/hc/en-gb/articles/14669003687444
- [tts] seller-uk.tiktok.com/university/essay?knowledge_id=8093609689663234
- [amz] affiliate-program.amazon.co.uk/welcome/compensation
- [ugc] influee.co/gb/blog/ugc-price
- [ss] ssemble.com · [ssr] ssemble.com/clip-rewards · [ssapi] ssemble.com/docs
