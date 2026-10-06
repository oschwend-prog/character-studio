# Brand profile: ODD EYES studio

Read first by the installed social skills (`hook-writer`, `instagram-reels-publishing`,
`tiktok-video-publishing`). The studio
runs several AI characters; each one is its own brand with its own account. The character bible
(`characters/<slug>/bible.md`) is the source of truth for that character and wins over this file and over any
skill's advice. Voice per character: `voice.md`.

## Identity
An AI-character studio. Original characters are dropped into famous, viral clips (Genjutsu Object swap: the
original shot is kept, the real star is replaced by our character) and posted as Instagram Reels first, TikTok
later. Entertainment, not a business selling anything.

## Roster (owner, 2026-10-06)
- **Franz**: the dachshund. Posh, dry, permanently unimpressed. Replaces a dog star. `characters/franz/`
- **Reginald**: the butler. Never speaks; deadpan in the caption. Replaces a human star. `characters/reginald/`
- **Lenny Gold**: the agent. Agent-speak, smug calm. Replaces a human star. `characters/lenny/`
- **The Borat-type**: from an invented country, not designed yet. `characters/borat-type/options.md`
- Biscuit: retired.

## Audience
Reels viewers who already know the moment (iconic and viral clips, classic songs). They share a clip because
it is THE famous moment with a funny character in it. Most reach is non-followers.

## Goal
Reach and sends (DM shares) first, then follows. The KPI bars in the plan header are binding: no skill's
benchmark, "best practice" or community number replaces them, before or after seeing data.

## Guardrails (hard, override any skill)
- Publishing: only through `bin/studio` and Postiz, run by the daily-run skill after the owner's approval.
  Never WoopSocial, `scheduling-and-queue` or any other publisher. A skill saying "WoopSocial publishes"
  means: hand the finished copy to `bin/studio`.
- AI disclosure on every post: `studio.captions` adds the line, the Instagram AI label is set. Never
  remove, soften or "humanize" it; no de-AI pass touches the disclosure.
- The caption formula in the bible (`## Voice (captions)`) is the owner's rule; skills refine wording inside
  it, never replace it. 3-5 hashtags; never #fyp, #foryou, #foryoupage, #viral or #explore.
- Credit the original creator and song; never keep another creator's watermark or handle.
- No scraping or downloading from TikTok or Instagram; no paid scraping keys (Apify and the like).
- No third-party audio we sourced ourselves; a drop-in keeps the clip's own sound. Trending audio is added
  by the owner in the Instagram app, never by us.
- Original characters only: no celebrity likeness, no real nationality or ethnic stereotype, real brands
  only as unnamed style references (never named in prompts, captions or on screen).
- The star we replace is always an adult; children elsewhere in a clip are fine.
- Never fabricate a metric. Numbers come from `bin/studio review data`, Postiz and the vidIQ owner insights.

## Operational defaults
- Format: 1080x1920, 9:16, 30 fps; classics 12-15 s, other clips 8-10 s, 16 s max. The master ends on the
  dance (no end close-up).
- Safe zone: keep hook text and faces out of the top ~250 px and bottom ~350 px of UI; the profile grid
  crops to 3:4 (1080x1440). The two-dot ODD EYES bug (972,268) is Reginald's only; Franz and Lenny carry no ODD EYES until the owner
  decides C8. Check the bug's position on the first real post.
- Language: English (British spelling for Reginald and Franz).
- Slots (Europe/London): set by the owner; never test the day or time.

## Show, don't tell
Example captions live in each bible (`## Voice (captions)`); the owner's approved captions are the posted
clips' `caption` (`bin/studio clip list --character <slug> --state posted`).
