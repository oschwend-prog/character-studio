# ODD EYES: video tools (MoneyPrinterTurbo, Remotion, CapCut), 8 Oct 2026

**What this is:** an answer to the owner's request (8 Oct): "for sure get CapCut, node.js and Remotion and let's use this
properly ... if there are any renders with Remotion or quick cool cuts with CapCut that will increase the value of our
generations and views, then let's look into this", and "check [MoneyPrinterTurbo] ... to make our system better". He also
shared a tutorial: "Forget After Effects: Claude + CapCut Is the Only Editing Stack You Need" (YouTube `j4FzO2fF1kg`).

**How:** read-only. I read `CLAUDE.md`, the `studio/media/master.py` docstring, `analyze.py`, the v3 spec (sections 1 and 11),
the workflows and the earlier research docs. I read the MoneyPrinterTurbo and CapCut-automation repos through `gh api` (read
only), the Remotion and CapCut documents and terms on the web, and the tutorial's transcript and metadata through the YouTube
Data API. Nothing was installed, downloaded, generated, posted or committed. I ran `node -v` and probed one local master with
`ffprobe`. This file is the only output.

**Labels:** **[E]** = evidence (a file, a command result or a named source). **[S]** = a secondary or vendor source.
**[I]** = my inference. **Effort:** **S** = hours. **M** = 1-3 days. **L** = a week or more.

---

## Summary (read this first)

1. **The tutorial is not Claude driving CapCut.** Claude writes files (a colour LUT, an SRT) and renders motion graphics in **Remotion**; the person imports them into CapCut by hand. The automatable part is Remotion, not CapCut [E: transcript].
2. **CapCut cannot sit in our unattended pipeline.** It has no editing or rendering API. Its terms ban "automated scripts" that interact with the service. The open-source draft tools can only export through the Windows desktop app [E].
3. **CapCut is at most a manual polish step** for a rare hero video. Its library music is not cleared for commercial use, and its terms take a perpetual, sublicensable licence on content you submit [E].
4. **Remotion fits**, as an *overlay layer only*: it renders a transparent animated layer (kinetic hook, series card, character accents); ffmpeg composites it; audio, loudness and QA stay exactly as they are [I].
5. **Remotion licence:** free for a company of up to 3 people. Above that, automated rendering costs $0.01 a render with a **$100 a month minimum** [E]. HyperFrames (HeyGen, Apache 2.0) is the fee-free fallback [E].
6. **Node.js is ready:** v24.14.1 on the Mac; `publish.yml` and `metrics.yml` already set up Node 20. `studio-drop.yml`, where masters are built, has no Node step yet [E].
7. **MoneyPrinterTurbo (MIT, 129k stars)** is a topic-to-faceless-video generator: LLM script, TTS, stock B-roll, subtitles, background music. Its pipeline does not fit us. Two snippets are worth borrowing: a subtitle "spring pop" easing and BT.709 colour tagging [E].
8. **Most "cool cuts" we can do in ffmpeg now:** beat-locked zoom pulses and a flash on the drop. We already detect the beats (`analyze.py`). We also have a word-pop entrance, so far used only by the DJ [E].
9. **Expected view impact is modest** [I]. What decides views is the clip pick and the first-second hook (hit-patterns doc). Edits add polish and visible "transformation", which Instagram's 30 April 2026 originality rule asks for (best-practice audit #1). Treat every edit as a tagged A/B arm, never a blind switch-on.
10. **Ranking:** (1) beat-locked edits + word pop in ffmpeg/PIL, now, S. (2) Remotion overlay spike behind `--renderer remotion`, next, M. (3) CapCut manual polish for one hero a week, optional, owner only. **Never:** CapCut automation, CapCut music or templates, MPT's TTS/B-roll/BGM, side-by-side "original vs ours" cuts.

---

## 1. Where we are today (the baseline any tool must beat)

`studio master build` is ffmpeg plus PIL PNG overlays [E: `studio/media/master.py` docstring]:
- the caption pill per character kit;
- hook entrances: `fade_rise` (Franz), `slam` (Lenny), `word_pop` on the beat (the DJ), plus Reginald's `pause` hook edit;
- `zoom_hit`, `slowmo`, `impact_sfx`, `text_pop` and `title_card` enhancements;
- `push_in`, `punch_in`, `drop_flash` and `pause` hook edits, and a `tone` grade;
- the two-dot bug;
- two-pass loudnorm to -14 LUFS.

`analyze.py` already gives beats, bpm, the drop time and the best window, for free. Masters build in the cloud
(`studio-drop.yml`, ubuntu-24.04, 60 min timeout) and on the Mac.

One local master (`renders/06eb86e9-.../master.mp4`) is tagged BT.709 (inherited from the Genjutsu output). The older
Biscuit debut master is untagged. The bug decodes within about 7 levels of `#8FD3FF` / `#FFB040` [E: ffprobe + pixel sample].

So the question is not "can we edit", but "what would raise views beyond what this already does".

---

## 2. MoneyPrinterTurbo (harry0703/MoneyPrinterTurbo)

**What it is** [E: README and `app/services/*` via `gh api`, 8 Oct 2026]:
- **Repo:** MIT licence, about 129k stars, v1.3.8 (3 Oct 2026), actively pushed. Python with MoviePy, Pillow and ffmpeg.
- **Pipeline:** topic → LLM script (many providers) → voice-over (free Edge TTS by default; Azure, ElevenLabs, Gemini and others optional) → stock footage (Pexels, Pixabay, Coverr, or AI video from Seedance, MiniMax and others) → subtitles → background music → MoviePy composite.
- **Subtitles:** timed from TTS timestamps (`edge` mode) or from local `faster-whisper` (`large-v3`, about 3 GB). Styling covers font, position, colour, size, stroke and a rounded background box.
- **Subtitle animation:** a 0.18 s "spring pop" on each subtitle: `scale = 1 - e^(-6p)·cos(2.5πp)`, clamped 0.05-1.35, applied to the frame *and* its alpha mask so no black first frame appears (`video.py:130-204`).
- **Clip transitions:** fade in/out, slide in/out, zoom in/out (`utils/video_effects.py`).
- **Outputs:** 9:16 1080x1920, 16:9 and 1:1. BT.709 conversion and tags on every encode (`_BT709_VIDEO_FILTER`).
- **Batch:** a CLI `--batch-file` (JSON array or JSONL), task history, WebUI, REST API and an "AI agent" mode.
- **Publishing:** cross-posting to TikTok, Instagram and YouTube Shorts through the Upload-Post API (`upload_post.py`).

**Fit for us:** low. It makes *faceless narrated* videos from stock or AI footage. We make *character dance Drop-ins*
whose star, audio and timing come from a real clip.
- Its BGM step breaks our rule never to add third-party audio we sourced ourselves.
- Stock B-roll and TTS do not apply to a dance clip.
- Its batch, multi-aspect and publishing parts duplicate what we have (the `studio` CLI, the 1080x1920 master, Postiz).

**Worth borrowing (MIT, keep the notice in a comment):**

| Item | What we'd take | Effort | View impact |
|---|---|---|---|
| Spring-pop easing | The 5-line formula for our PIL entrance frames: a word or pill pops in with one overshoot instead of a linear slam. Usable for every kit's `word_pop` | S | Low [I] |
| BT.709 on the overlay step | `scale=out_color_matrix=bt709:out_range=tv` + `setparams` tags, so the RGBA pill and bug convert with the right matrix even when the source is untagged (the old Biscuit master was) | S | None on views; keeps brand colours exact |
| Upload-Post as a fallback publisher | Only if Postiz fails us. It is the same class of tool, and the best-practice audit already names Ayrshare as the fallback | M | None |

**Not worth taking:** the LLM script, TTS, stock-footage, BGM and transition engine (MoviePy is slower than our single
ffmpeg graph, and the transitions are for multi-shot montages, not one-shot dance clips).

Whisper subtitles matter only when a character *talks*: the Borat-type and the later concepts, not the dancers.

---

## 3. Remotion (React → video, Node.js)

### 3.1 What it would add over ffmpeg + PIL
PIL frames can already do a pill, a fade, a slam and a word pop. Remotion makes *motion design* cheap to write and to
change by prompt [I]:
- **Kinetic hook text:** per-word springs, scale, rotation, colour sweeps, emoji pops and a highlight running over the words on the beat. `@remotion/captions` (`createTikTokStyleCaptions`) pages word timings into TikTok-style caption groups [E: docs].
- **Data-driven series cards:** "Ep. 7" / "Day 4" badges or the series tag (`#sausagecomingthrough`), animated, filled from props per clip.
- **Per-character motion accents:** Franz's warm slide, Reginald's serif label that writes on, Lenny's gold slam with particles. These are React components that take the kit (`style` in `refs.json`) as props.
- **Covers:** `renderStill` for the 3:4 Instagram grid cover with the series title (best-practice audit #9).
- **Owner preview:** Remotion Studio previews a template live in the browser, and Claude edits it by prompt. This is what the tutorial shows.

What it does *not* add: anything to the clip pick, the swap, the audio or the hook wording. Those decide most views
(hit-patterns doc).

### 3.2 Licence and cost [E: LICENSE.md, remotion.pro/license]
- **Free** for "an individual", "a for-profit organization with up to 3 employees", non-profits, and while "evaluating".
  Commercial use is allowed.
- **Above 3 employees, a Company License:**
  - "Creators": $25 a month per seat, for people editing in Remotion Studio.
  - "Automators" (our case: renders from a pipeline): $0.01 a render, **$100 a month minimum** (10,000 renders included).
    "Developers working on automation projects do not require a Seat".
  - Enterprise: from $500 a month.
- At our volume (about 10-20 masters a week), the ≤3 tier costs nothing. Above 3 people it is a flat $100 a month for what
  is a few hundred renders [I].
- **Licence-free alternative:** **HyperFrames** (heygen-com/hyperframes; Apache 2.0, "no per-render fees or
  commercial-use thresholds"; about 58k stars, created March 2026). It writes the video as HTML + GSAP, renders in headless
  Chrome + FFmpeg, is deterministic, outputs MP4 or a transparent overlay, and needs Node ≥22 (npm `hyperframes` 0.8.141)
  [E]. Its Claude Code skills (`hyperframes:*`) are already installed in this setup, as is `ecc:remotion-video-creation`.
  Remotion is the more mature choice (v4.0.534, since 2021). HyperFrames is the swap if the licence ever bites [I].

### 3.3 Rendering: where and how fast
- **Options** [E: docs/ssr, compare-ssr]: Node/CLI (`npx remotion render`), GitHub Actions (an official workflow template), Lambda (distributed, fastest), Cloud Run, Vercel Sandbox, Docker.
- **Lambda** costs about $0.001-0.02 a render in Remotion's own examples (a 1-minute video: about $0.017, 19 s) [E]. It needs an AWS account and IAM set-up: not worth it for our volume [I].
- **GitHub Actions is enough** [I]. Our private-repo runner is **2 vCPU, 8 GB** [E: GitHub docs]. A Linux render needs the Chrome Headless Shell and 14 apt libraries on Ubuntu 24.04 (`libnss3`, `libgbm-dev`, `libasound2t64` and others) [E].
- **Speed:** no published benchmark for 1080x1920 on a 2-vCPU runner. My estimate: a 10 s text-and-shape overlay (300 frames) renders in tens of seconds, plus about 1 minute of set-up (npm install, browser), which caching shrinks [I]. This must be measured: `npx remotion benchmark`.
- **What slows renders:** blur, shadows, gradients and WebGL on GPU-less machines, and PNG frames (needed for alpha) [E: docs/performance]. Keep the overlays flat, and render only the frames that animate (`--frames`).
- **Transparent output** [E: docs]: ProRes 4444 (`--codec=prores --prores-profile=4444 --pixel-format=yuva444p10le --image-format=png`), VP8/VP9 WebM (`yuva420p`), or a PNG sequence (`--sequence`).
  - Prefer a **PNG sequence or ProRes 4444**.
  - WebM alpha needs ffmpeg's `libvpx-vp9` *decoder* chosen explicitly, or the alpha is silently lost [I: known ffmpeg behaviour; verify in the spike].
  - Remotion notes WebM flicker at chunk boundaries on Lambda.
- **Node.js:**
  - Mac: `node -v` → v24.14.1, npm in `/usr/local/bin` [E].
  - CI: `publish.yml` and `metrics.yml` use `actions/setup-node@v4` with Node 20. `studio-drop.yml`, where cloud masters are built, and `health.yml` have none [E]. Adding Node 22 there is one step.

### 3.4 The simplest way to plug it in
1. A `remotion/` folder in the repo: `package.json`, a `HookOverlay` composition (1080x1920, 30 fps), later `SeriesCard` and `Cover`.
   - Fonts come from `assets/fonts/` (OFL, already committed).
   - No media in git.
2. `studio master build --renderer remotion` (the default stays `pil`):
   - Python writes a props JSON: hook lines, the kit's `style`, the beats and drop time from `analyze`, the duration, the series number.
   - It runs `npx remotion render HookOverlay --props=<file> --sequence --image-format=png --muted`.
   - It adds the frames to the existing graph as one more windowed overlay *before* the bug, so the bug stays on top and nothing is zoomed or graded.
3. **Audio, loudness, length, the bug and `check_master` do not change.** If the Remotion render fails, the build falls back to the PIL path and records `overlay_renderer: pil` [I].
4. Tag it: `features.overlay_renderer` and an `edit` arm in `test_arms` (measurement plan, section 2), so `outlier_x` can say whether it helped. The KPI bars are untouched.
5. **Placement rules for every overlay:**
   - no pre-roll before the dance (it kills the first-second hook);
   - no end card (masters end on the dance, owner 2026-10-05);
   - keep clear of the bug at (972,268) and of Instagram's bottom ~350 px;
   - the pill band stays at y≈1300.

---

## 4. CapCut

### 4.1 Can it be driven by a program? [E unless marked]
- **No official editing API.** CapCut's API covers AI features (background removal, upscaling). "You cannot programmatically create videos, add scenes, overlay text, generate subtitles or render final MP4s" through it [S: json2video, a competitor]. Pippit, ByteDance's commerce tool, is a separate product.
- **Draft-JSON tools:**
  - **`pyJianYingDraft`** (Apache 2.0, about 4.5k stars) writes JianYing drafts on any OS. **Export only works on Windows**, through UI automation of JianYing ≤6. JianYing 7+ cannot be exported this way, and newer drafts' `draft_content.json` is often "not plain-text JSON". Its CapCut-international sibling, `pyCapCut`, has no licence file and is "in development".
  - **`VectCutAPI`** (ex-CapCutAPI, Apache 2.0) and **`capcut-mate`** (Apache 2.0) add HTTP/MCP servers. Their "cloud rendering" is their own hosted service (vectcut.com; capcut-mate's `gen_video` against `capcut-mate.jcaigc.cn` with an API key). That means sending our masters to an unknown third party.
  - `capcut-mcp` is archived.
- **CapCut's terms (last updated 15 Apr 2026)** ban using "automated scripts or other technologies to collect information from or otherwise interact with the Services". They also take a "non-exclusive, royalty-free, transferable, sub-licensable, perpetual and worldwide license" over User Content you submit. That is a poor fit for our characters' IP when cloud features are used [E: capcut.com/clause/terms-of-service].
- **Music and materials:**
  - Library music is personal or non-commercial. "Commercial Sounds" may be shown only on CapCut, TikTok and TikTok for Business.
  - Templates, effects and fonts are commercial only when they carry the "commercial use" mark [S: autoae.online; CapCut Materials License Agreement].
  - Either way, adding CapCut library music breaks our audio rule.
- **Watermark and price:**
  - Mobile free exports are clean.
  - Desktop and web free exports historically add a small logo; Standard ($10 a month) or Pro ($20 a month, $179.99 a year) removes it [S: fluxnote, June 2026].
  - CapCut is not installed on the Mac today [E: `/Applications`].

**Verdict:** not for the unattended cloud pipeline (no API, Windows-only export, a terms breach, third-party clouds). At most,
a **manual polish** by the owner for a rare hero video (an `iconic`-tier classic). The export must then go through
`studio master upload`, which re-checks the file against the master spec (loudness, length, size). Use no CapCut music,
use only "commercial"-marked materials, and keep the bug and the AI disclosure.

### 4.2 What the tutorial actually shows [E: transcript, 615,568 views on 8 Oct 2026]
1. Claude (chat) generates a **.cube LUT** ("clean soft pastel"), imported into CapCut's Adjustment → LUT at about 50%.
2. Claude writes an **SRT** of numbers 0 → 600, which CapCut turns into a counting-money effect (a compound clip, sped up 10x).
3. **Claude Code + Remotion** (`npx create-video@latest`; Node.js installed first; the Remotion best-practices skill):
   - a motion background;
   - animated UI boxes with a **transparent background**, imported over the footage in CapCut;
   - a word highlight that follows a read-out article;
   - a route map (an open-source map instead of Mapbox, with a Higgsfield image for the style).
4. Their prompt pattern: give a reference image and end with "ask me any clarifying questions".

**For us:** item 1 maps to ffmpeg's `lut3d` (a per-character LUT file could replace the `tone` presets). Item 3 is section 3.
Nothing needs CapCut itself.

### 4.3 "Quick cool cuts" for 8-15 s character dance clips

**Evidence is thin and mostly vendor-grade:**
- OpusClip's 13.5M-clip study counts *how often* an edit appears, not whether it lifts views. Captions appear in 80.2% of clips and animated captions in 78.6%, and those are mostly talking clips [S].
- CapCut's own 2026 trend pages name velocity (speed-ramp) edits, beat sync and glitch/RGB-split [S].

What matters for us:

| Cut | Do it with | Verdict for a Drop-in with its original audio |
|---|---|---|
| Zoom pulse / punch on beats (every 4th beat, the drop) | ffmpeg `zoom_hit` placed from `analyze` beats | **Do (now).** Picture only, so the dance stays in sync with its music |
| Flash or RGB-split on the drop | ffmpeg (`drop_flash` exists; `rgbashift`) | **Do for Lenny-type kits** (A/B arm); keep it subtle for Franz and Reginald |
| Word-by-word hook on the beat | PIL `word_pop` (exists, DJ only) + MPT spring easing; later Remotion | **Do (now) as an arm**; kits keep their own entrance by default |
| Series badge "Ep. N" / series tag | PIL static now; Remotion animated later | **Do.** Aids follows and binge [I]; corner badge, not a card |
| Camera shake on hits | ffmpeg crop offsets | Maybe, Lenny only |
| Colour LUT per character | ffmpeg `lut3d` | Later; brand look, low view impact |
| Velocity / speed ramp, freeze-frame mid-clip | — | **No** on original audio: the picture drifts off its own music (the `slowmo` docstring already warns). OK only on `ai_beat` Recreates |
| Intro sting or end card | — | **No:** it delays the hook and the owner banned end stings |
| Side-by-side "original vs ours" | — | **Never:** it reposts another creator's footage, the aggregator/unoriginal pattern |
| CapCut trend templates, library music | — | **Never** (licence + audio rule) |

---

## 5. Recommendation (ranked by expected view impact ÷ effort)

| Rank | Item | When | Impact on views | Effort | First concrete step |
|---|---|---|---|---|---|
| 1 | **Beat-locked picture edits:** auto `zoom_hit` on the drop and every 4th beat (cap 3 per clip), `drop_flash` as an arm | **Now** | Low-medium [I]; adds visible "transformation" | S | A `beat_hits` enhancement in `master.py` that turns `analyze` beats into `zoom_hit`s; a coin arm `edit: plain/beat` in `test_arms` |
| 2 | **Word pop for every kit as an arm** with MPT's spring easing (MIT note) | **Now** | Low-medium [I] | S | Port the easing into `entrance_frames('word_pop')`; arm `hook_entrance: kit/word_pop` |
| 3 | **Series badge** (static "Ep. N" + series tag, brand colours, top-left, clear of the bug) | **Now** | Low on views, positive on follows [I] | S | A per-character counter from posted clips; PIL badge; owner approves the look once |
| 4 | **Remotion overlay renderer** (`--renderer remotion`: kinetic hook, animated series card, per-character accents; later covers) | **Next** (after 1-3 have 2-3 weeks of tagged data) | Medium if motion polish lifts retention; unproven [I] | M | Confirm headcount ≤3 (free). Spike on the Mac: `remotion/` + `HookOverlay`, render one 10 s overlay of an existing master as a PNG sequence, composite, time it. Then a `workflow_dispatch` CI benchmark. HyperFrames if the licence bites |
| 5 | **BT.709 matrix + tags** on the master encode (from MPT) | Now (hygiene) | None on views | S | Add the matrix to the overlay conversion; check with `ffprobe` and a bug-pixel sample |
| 6 | **Per-character LUT** (`.cube`, `lut3d`) replacing `tone` presets | Later | Low | S | Claude writes one `.cube` per kit into `assets/luts/`; owner picks by eye |
| 7 | **CapCut manual polish** for one hero video a week | Optional, owner only | Unknown; manual time | Owner ~15 min each | Only if the owner wants it: install CapCut (Pro, to drop the desktop watermark); export, then `studio master upload` re-checks |
| — | **Never:** CapCut automation (draft JSON, UI scripts, VectCut/capcut-mate clouds); CapCut library music or unmarked templates; MPT's TTS/B-roll/BGM path; speed ramps on original audio; pre-roll or end stings; side-by-side with the original creator | — | — | — | — |

**Why this order** [I]: items 1-3 use data and code we already have, cost no credits, add no dependency and run in the
current cloud job. They also produce the tagged evidence that tells us whether motion polish moves `outlier_x` at all,
*before* we add Node, Chrome and a licence to the cloud master build. If the arms show no lift, Remotion stays a
nice-to-have for covers and series cards. If they lift, Remotion is the way to make the motion richer without
hand-coding PIL frames.

**Rules every item keeps:**
- 1080x1920 @ 30 fps, 6-16 s, -14 LUFS ±1, true peak ≤ -1 dBFS;
- the two-dot bug on top, untouched;
- masters end on the dance;
- no added third-party audio;
- the AI disclosure stays;
- no scraping;
- KPI bars unchanged;
- every new edit is a tagged arm, never a silent default.

---

## Sources
- MoneyPrinterTurbo, README, `app/services/video.py`, `subtitle.py`, `utils/video_effects.py`, `upload_post.py`, repo metadata (read via `gh api`, 8 Oct 2026): https://github.com/harry0703/MoneyPrinterTurbo
- Tutorial "Forget After Effects: Claude + CapCut Is the Only Editing Stack You Need" (title, views, transcript via the YouTube Data API): https://www.youtube.com/watch?v=j4FzO2fF1kg
- Remotion licence: https://github.com/remotion-dev/remotion/blob/main/LICENSE.md
- Remotion pricing: https://www.remotion.pro/license
- Remotion transparent videos: https://www.remotion.dev/docs/transparent-videos
- Remotion SSR options: https://www.remotion.dev/docs/ssr and comparison https://www.remotion.dev/docs/compare-ssr
- Remotion Lambda cost examples: https://www.remotion.dev/docs/lambda/cost-example
- Remotion performance: https://www.remotion.dev/docs/performance
- Remotion Linux dependencies: https://www.remotion.dev/docs/miscellaneous/linux-dependencies
- Remotion render CLI: https://www.remotion.dev/docs/cli/render
- `@remotion/captions` createTikTokStyleCaptions: https://www.remotion.dev/docs/captions/create-tiktok-style-captions
- Remotion Agent Skills: https://www.remotion.dev/docs/ai/skills
- npm registry (read 8 Oct 2026): `remotion` 4.0.534, `hyperframes` 0.8.141 (`engines.node >=22`)
- GitHub-hosted runner specs: https://docs.github.com/en/actions/reference/runners/github-hosted-runners
- HyperFrames: https://github.com/heygen-com/hyperframes
- pyJianYingDraft: https://github.com/GuanYixuan/pyJianYingDraft ; pyCapCut: https://github.com/GuanYixuan/pyCapCut
- VectCutAPI (ex-CapCutAPI): https://github.com/sun-guannan/VectCutAPI
- capcut-mate (and `docs/gen_video.md`): https://github.com/Hommy-master/capcut-mate
- capcut-mcp (archived): https://github.com/fancyboi999/capcut-mcp
- CapCut Terms of Service (updated 15 Apr 2026): https://www.capcut.com/clause/terms-of-service
- CapCut commercial use (Materials License, music): https://autoae.online/blog/is-capcut-free-for-commercial-use
- CapCut pricing and watermarks (June 2026): https://fluxnote.io/guides/capcut-questions-answered
- CapCut API scope (competitor page): https://json2video.com/how-to/capcut-api/
- CapCut 2026 editing trends (vendor): https://www.capcut.com/help/latest-capcut-editing-trends
- OpusClip 13.5M-clip editing study (prevalence, not causation): https://www.opus.pro/blog/video-editing-tips
- In repo: `studio/media/master.py`, `studio/media/analyze.py`, `docs/superpowers/specs/2026-10-07-terminal-v3-design.md`, `docs/research/2026-10-07-hit-patterns.md`, `docs/research/2026-10-05-best-practice-audit.md`, `docs/launch/measurement-and-learning-plan.md`, `.github/workflows/*.yml`
