# ODD EYES roadmap (owner, 2026-10-05)

Order: get Biscuit + Reginald running on Instagram first, then expand.

## Now: launch (Instagram)
- Launch set: iconic all-time clips people recognise first (Single Ladies, Macarena, Wednesday, Gangnam),
  then the scored viral clips from the daily scan; Genjutsu gallery as backup.
- Drop-in first (Genjutsu replace-object), owner attaches screen-recorded clips in the terminal; music added
  in-app by the owner while posting is manual.
- Characters final: Biscuit = version C, Reginald = Quiff B. Gadgets with a "viral job" (lookbooks in
  `docs/characters/`).

## Next (once running)
1. **TikTok:** create `biscuit.moves` / `reginald.thebutler`, connect in Postiz as plain TikTok, seed.
2. **Automation on:** scheduled tasks `studio-daily-run` (08:00 London, Sonnet) + `studio-weekly-review`
   (Mon 09:00, Opus); re-enable the publish/metrics/health workflows; autopilot per channel after 6 approved posts.
3. **Audit quick wins** (`docs/research/2026-10-05-best-practice-audit.md`): post-by deadline ordering + fast
   sequels, keyword in caption line 1, first-hour comment drafts, covers, Trial Reels, Collab crossovers,
   follower / watch-time / non-follower-reach data feed (unblocks the week-3 bars and the IG guard).
4. **Credits plan:** decide top-ups vs Higgsfield Ultra after the first week's real re-roll rate.
5. **Income now: LaunchPoint "AI Invasion" creator campaign (owner 2026-10-06):** $1 per 1,000 verified views, up to $2,000 per video, for original AI-influencer videos made from footage we own (see docs/AI_INFLUENCERS.md section 4a). The owner signs up as a creator and shares the rules.
6. **Paid amplification (after the week-3 review, owner 2026-10-05):** [Launchpoint](https://www.launchpointhq.com/) runs
   creator campaigns from a brief (new videos by 100k+ vetted creators on IG/TikTok/YT, ~$1 per 1,000 verified views,
   e.g. 1.2M views for $1,200; Higgsfield is a customer). Only once a format has proven itself: a capped $300-500 test
   ("duet/react to Reginald's latest dance, tag @reginald.thebutler"), judged on follows per 1K views against organic.

## Character 3: the Outsider (Borat-type)
- An 1852 Victorian gentleman lost in 2026 London; original, never mocks a real nationality; deadpan
  formal register vs modern life ("1852 man orders a flat white").
- Needs the **talking lane**: a signature voice (Higgsfield `create_voice`), lip-synced talking clips,
  word-synced captions. Pre-approved picks O5 (origin episode, pin) and O1 are waiting in the terminal.

## Character 4: the Singer (music channel)
- A new ODD EYES character who sings the greatest classics in everyday places: in the car (carpool-karaoke
  energy), in the shower, while running, in the kitchen, on the bus. Each video = one iconic chorus, one
  place, one gag; series by decade/genre.
- **Rights-safe approach:** he **lip-syncs to the original recording added in-app** (Instagram / TikTok
  licensed music library). An AI-voiced cover needs separate song licences (mechanical + sync) - avoid unless
  licensed. No real singer's likeness or voice clone.
- Production: Higgsfield lip-sync / talking tools (verify which model syncs best to music), Genjutsu
  Drop-in for the car/shower/running scenes; the eye-glint end beat stays.
- Monetisation angle: music channels pull high shares; brand fits = cars, headphones, showers/bathroom,
  sportswear.
- First step when we get there: design 3 looks (1 credit each), pick, then a 5-clip test series.

## After launch: the ODD EYES terminal as a subscription (owner, 2026-10-06)
- Owner: "once done with this and live, we should also think about selling the odd eyes terminal on social media as
  subscription; like this people can easily create their own characters."
- Parked until the four characters are live. When we pick it up: who it is for (creators, small brands), what they get
  (character design with spec sheets, drop a clip -> Object swap -> caption pill -> post), pricing against the Higgsfield
  and Gemini costs per video, multi-user accounts (today the terminal is single-owner by design), each customer's own
  Higgsfield/Postiz keys, and platform rules on AI labels. Our own channels are the demo.
- Related parked idea: the 10-character library `docs/influencers/2026-10-06-character-library-v1.md`.

## Long term: a fully autonomous studio, one character per niche (owner, 2026-10-07)
- Owner: "this could run totally autonomously long term: a character per niche, scanning social media for adequate videos
  within that niche or that are matching, then generating the content and uploading it. It could even say, for example,
  right now it's PFW in Paris, so I will upload stories around that in Paris for that weekend, so it looks more live and cool."
- What it means for the studio (notes for when we pick it up, not decisions):
  - **One character per niche:** each character owns a niche (dogs, butlers/deadpan, Hollywood/business, DJ/club, fashion,
    sport ...) with its own scan profile (`config/scan.json` themes, the bible's `## Scan profile`) and fit scoring.
  - **Autonomous loop:** scan → pick the clips that fit the character → free check → Make it → master → post, with the
    owner's approval switched off per account only after the autopilot gate (6 approved posts, KPI bars binding) and the
    monthly credit cap as the hard brake. Today's launch phase (owner drops only, auto-approve off) is the first step.
  - **Event awareness ("looks live"):** an events calendar (fashion weeks, festivals, award shows, big matches, holidays) that
    steers the scan and the settings: e.g. Paris Fashion Week → the character "is in Paris" that weekend: Paris-set
    Recreates or Drop-ins of PFW clips, Stories from the city, captions in the moment. Needs: a calendar source, a
    Stories publishing path (Postiz/Instagram Stories), location-true settings without real-person likeness or brands.
  - **Guardrails stay:** AI label on everything, no real person's likeness, the never-scrape rule (the scan files picks;
    a fetch takes one approved pick), at most 2 posts per account per day, the credit cap.

## Next: every post also goes to Stories (owner, 2026-10-07)
- Owner: "also do stories or reels from the posted stories when uploading in the future".
- Plan: when a Reel is published, also publish it (or a 15 s cut of it) as an Instagram Story on the same account, with the
  caption pill and the AI label; Postiz supports an Instagram `post_type: story` (verify with `postiz integrations:settings`).
  Counts toward nothing in the 2-posts-a-day cap (Stories are not feed posts) but stays approval-gated like the Reel.
