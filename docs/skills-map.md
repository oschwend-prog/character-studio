# Skills & tools map — Character Studio (audited 2026-10-04)

Installed skills/MCP tools that earn a place, by pipeline stage. ★ = core, used every day by the automation.

| Stage | Skill / tool | Why |
|---|---|---|
| Trend research | ★ vidIQ `instagram_tiktok_outlier_search`, `trending_videos` | TikTok + Reels outliers vs creator median — the viral signal (5 credits/scan) |
| | ★ Higgsfield `get_presets` (Genjutsu Trending/New), `tiktok_music_trending` | Free daily motion + trending-sound feed (motion-only use) |
| | `last30days` | Weekly Reddit/X/web trend read inside the Monday review |
| | `research` (router), `social-media-monitor` | Ad-hoc deep dives; competitor/hashtag listening workflows |
| | `watch` | Turn a reference video into frames + transcript for analysis (research only, never reposting) |
| Character design | ★ Higgsfield `generate_image` (Seedream 4.5 = default, GPT Image 2 for hard poses), `nano-banana-pro` | Character stills, scene stills, per-video wardrobe (1–11 credits) |
| | Higgsfield `character-sheet` workflow, `show_reference_elements` | Turnarounds and identity lock if drift appears |
| | `ecc:brand-voice` | Locks each character's caption voice from approved examples |
| Hooks & captions | ★ `viral-hook-creator` | Proven hook patterns + trigger words (used for the launch plan) |
| | ★ `humanizer:humanizer` | Strips AI-sounding phrasing from captions |
| | `ecc:content-engine` | Platform-native content calendars / repurposing |
| Video generation | ★ Higgsfield `generate_video` → `hf_mult_motion_control` (Genjutsu), Seedance 2.5 t2v | Motion transfer at 1080p; synthetic driving dances with our own AI beat |
| | Higgsfield `virality_predictor`, `video_analysis_create` | Pre-post score + scene analysis (Slice 2, must prove it predicts real views) |
| Finishing | ★ ffmpeg master chain (from faceless-youtube) | 1080×1920/30 fps/~15 Mbps, −14 LUFS |
| | `hyperframes` / `hyperframes:embedded-captions`, `ecc:remotion-video-creation` | Branded hook-text overlays and motion graphics when ffmpeg drawtext isn't enough |
| | `hyperframes:music-to-video` | Beat-synced edits for the Artist lane (Slice 3) |
| Approval & posting | ★ `postiz:postiz` (Postiz CLI) | Direct posting to TikTok + Reels, scheduling, **post analytics** |
| | ★ `ecc:operator-approval-loop` | Pattern for approve-then-post with durable claims (no double posts) |
| | Higgsfield `tiktok_prepare_publish`, vidIQ `instagram_publish_reel` | Manual fallback posting paths |
| Learning loop | ★ `data:statistical-analysis`, `agentic-bundle-data-analytics:ab-test-setup` | Honest reads vs pre-registered bars; audio-arm and hook A/B tests |
| | vidIQ `instagram_owner_insights`, Postiz `analytics:*` | Real post/account stats |
| | `ecc:growth-log` | Turns each weekly review into reusable lessons |
| Automation | ★ Claude scheduled tasks (`mcp__scheduled-tasks`), `schedule` | Daily run + weekly review, created from this folder |
| | ★ `writing-for-agents`, `anthropic-skills:skill-creator` | Lean, unambiguous `/daily-run` and `/weekly-review` skills = token-cheap runs |
| | `ecc:continuous-agent-loop`, `ecc:eval-harness` | Quality gates, recovery, golden-set calibration of the visual QA |
| | `ecc:cost-aware-llm-pipeline` | Model routing (Sonnet daily / Opus weekly) and spend caps |
| Terminal | ★ `impeccable`, `dataviz`, `ui-ux-pro-max` | Dashboard design and charts in the owner's terminal style |
| Build process | ★ `superpowers:writing-plans` → `subagent-driven-development` + `test-driven-development` | Plan → build → review |
| Later (growth) | `tiktok-influencer-marketing`, `influencer-outreach` | Brand deals once a character has an audience |

## Deliberately NOT used
- `scrapling`, Bright Data scraping skills — scraping TikTok/Instagram breaches their terms; vidIQ provides the same signal legitimately.
- `ecc:social-publisher` (SocialClaw) — duplicate of Postiz.
- Higgsfield `hf_mult_replace_object` on third-party footage — it keeps their footage.
- LunarCrush MCP — useful social-sentiment data but needs a paid subscription; revisit only if vidIQ proves too thin.
