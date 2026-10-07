# Marketing skills in the studio (owner 2026-10-07)

Which of the installed skills the studio uses, where, and when. The automation runs only what is wired into
`.claude/skills/daily-run` and `.claude/skills/weekly-review`; the rest are run on demand when the owner asks.

## Wired in (automatic)
| Skill / tool | Where | What it does for us |
|---|---|---|
| `viral-hook-creator` | daily run, step 9.4 and the drops by hand | 3 hook candidates per video; reads `FOUNDER_CONTEXT.md` (42-character pill, the voices, the hit patterns) |
| `humanizer` | daily run, captions | keeps the caption natural |
| `last30days` | weekly review, step 4, only with a ScrapeCreators key and its cookie-free setup | what people say per niche (owner 2026-10-07: cloud scraping is fine, never the Mac's browser or cookies) |
| social-data tools (`keyword_posts`, `topic_posts`, `keyword_time_series`, `post`) | weekly review, step 4 | the week's top TikTok and Instagram posts per niche ("clips to save" for the owner) and mentions of our characters. Replaces vidIQ for finding hits (owner 2026-10-07) |
| `social-media-monitor` (method) | weekly review, step 4 | sentiment, recurring questions, offence flags |
| `online-reputation-management` | weekly review, step 4, only on a flag | a reply plan for the owner; we never reply ourselves |

## On demand (the owner asks)
| Skill | When |
|---|---|
| `campaign-plan` | a launch (Franz's new look, each new character) or a brand campaign brief |
| `brand`, `brandkit` | a character's media kit and brand guidelines (from about 5,000 followers or the `promote` bar) |
| `influencer-outreach`, `tiktok-creator-marketplace`, `tiktok-influencer-marketing` | pitching brands, the TikTok Creator Marketplace profile, collabs |
| `tiktok-shop-affiliate-program`, `tiktok-shop-content-strategy` | affiliate income (e.g. Franz with pet products) from about 1,000 TikTok followers |
| Higgsfield `virality_predictor` | a score (hook strength, retention risk) for a finished video before it posts; price to be checked before it is wired in |

## Not used
- `scrapling`: scraping breaks the never-scrape rule and the platforms' terms.
- `brand-monitoring`: its script searches the web on its own; the social-data tools cover mentions.
- The Etsy, Shopify, Amazon, eBay and Walmart skills: shop selling, not channels.

The tool allowlist for the automation is the owner's file: the additions are in `.claude/settings.json.proposed`.
