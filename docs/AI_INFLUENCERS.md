# AI Influencers: master document (single source of truth)

**Status:** merged 2026-10-06 from two strands of work in the same Higgsfield account (`user_3FpDaPTqXIGIuGg9Gh73nLwPXRT`):
- **A. The ODD EYES studio (this repo, Claude Code):** Biscuit, Reginald, the Outsider and the Singer. There is a pipeline, a database, a terminal and two finished videos.
- **B. The claude.ai / Higgsfield sessions:** Lenny Gold, Franz and a Borat-type. The original brief is kept verbatim in [influencers/2026-10-06-claude-ai-higgsfield-brief.md](influencers/2026-10-06-claude-ai-higgsfield-brief.md).

**How to use this file:**
- It is the one place to read about the whole roster, the strategy and the open decisions.
- Detailed binding rules for the running pipeline stay where they are and are linked below: `CLAUDE.md` Global Constraints, `.claude/skills/daily-run/SKILL.md`, `characters/<slug>/bible.md` and `refs.json`, `docs/roadmap.md`, `docs/launch/channel-strategy.md`.
- **Where the two strands disagree, nothing has been overwritten.** Section 1 lists each conflict for Olivier to decide. Until he does, the running pipeline (A) keeps its current rules, and B's characters are documented here only. They are not seeded into the studio database: no `characters/lenny` or `characters/franz` folders until he decides.

---

## 1. Open conflicts (Olivier decides)

| # | Topic | Brief (B) says | Repo (A) does today | Decision needed |
|---|---|---|---|---|
| C1 | **Literal footage** | Copy the **format** (hook, beat, sound, structure), **never the literal footage**: legal exposure and re-upload detection. | **Drop-in:** Genjutsu **Object swap** into the real viral clip, keeping its setting, camera, timing and **original sound** (owner 2026-10-05/06: "drop our characters straight into viral videos with their sound"). Wednesday was made this way. | Is Drop-in allowed, or Recreate-only (motion transfer)? This decides C2, C3 and C4. |
| C2 | **Recast method** | **Motion transfer** (`hf_mult_motion_control`) is "the working route"; pure text-to-video was abandoned. | **Object swap** (`hf_mult_replace_object`) is the default. Motion transfer only when there is no usable clip (Single Ladies was a motion transfer). The owner asked on 10-06 to use Genjutsu "the way it's supposed to": drop into clips. | One default or both: Object swap for owner-dropped clips, motion transfer for format recreations? |
| C3 | **Real people and famous footage** | No real-person photos as references, no actor likeness, which rules out e.g. Entourage footage. | Famous clips are allowed **as long as the real star is replaced**. The long list proposes official MV/film footage (Smooth Criminal, Weapon of Choice, Love Actually, Thriller), and Wednesday used a cosplayer's clip. No real-person *references* are ever used, so that part agrees. | May the source *footage* contain real people or official MV/film scenes, with the star replaced? |
| C4 | **Downloading clips** | Weekly ~10-min manual batch via **snapinsta.app / igram.io**, then a bulk upload to Higgsfield. Automated grabbing is "blocked / robots-disallowed". Never log in on downloader sites. | **No download websites** (safety rule). One owner-allowed path: `yt-dlp` inside `bin/studio source fetch` for one approved pick at a time, public, no login, no cookies. "Drop a video" (in build) adds phone uploads plus a cloud job. | Keep the yt-dlp and upload path and drop downloader sites? Is the robots.txt stance acceptable for yt-dlp fetches? |
| C5 | **Two cream long-haired mini dachshunds** | **Franz:** smug aristocrat, navy polo, big dark eyes, posh voice (Alistair), Element `a28cc772`. | **Biscuit:** cute bouncy dancer, baby-blue velour tracksuit, **odd eyes**, no voice, look C master `e07675a2`. | Keep both as distinct characters, merge them into one, or retire one? Same breed and colour risks confusing the audience. |
| C6 | **Posh British register twice** | Franz: plummy, posh, deadpan aristocrat. | Reginald: stone-faced English butler, deadpan, never speaks. | Fine as master and servant in one universe, or too close? Ties to C8. |
| C7 | **The Borat-type** | Clueless **foreign correspondent**: bad jokes, wild dancing. Names floated: Borys, Vlad Bogdan, Dmitri, Grigor. | **The Outsider:** an 1852 Victorian gentleman lost in 2026 London. The repo deliberately avoided a foreign angle: `docs/roadmap.md` says "never mocks a real nationality" and `config/scan.json` rejects national or ethnic stereotypes. | Which concept? Eastern-European-sounding names on a clueless-foreigner joke would break the repo's stereotype rule. |
| C8 | **One universe or standalone brands** | Open question. | Everything sits under one brand, **ODD EYES**: heterochromia (right eye ice-blue, left amber) and the two-dot bug on every video. | Do Lenny and Franz join ODD EYES (and get the odd eyes), or stay separate brands with their own accounts? |
| C9 | **Publishing** | "Higgsfield can publish to TikTok directly." | **Postiz** posts (IG connected; TikTok later). The daily-run guardrails forbid Higgsfield's `tiktok_*` publish tools. | Keep Postiz for all, or let Higgsfield publish TikTok for B's characters? |
| C10 | **Posting rhythm** | 3–4 posts a week per character. | Biscuit 19:00, Reginald 19:30 London; weeks 1–2 Tue/Wed/Thu, from week 3 Mon–Fri (5 a week); never more than 2 a day per account. | 3–4 a week, or 5 from week 3? |
| C11 | **Voice** | Every clip ships with a voiceover (Lenny: Emmett; Franz: Alistair, in test). | Biscuit and Reginald are silent and music-driven (Reginald never speaks); voices are planned for the Outsider (Slice 3 "talking lane"). | No conflict for existing characters. Should voiced characters join the studio pipeline (it has no voice step yet)? |
| C12 | **Credits** | Uses the same Higgsfield account. | Studio budget: monthly cap 6,000 credits, plus per-video approval by the owner. Both strands draw from **one shared balance** (≈ 750 left on 10-06). | One budget for both strands? B's spend isn't recorded in the studio ledger. |

Smaller differences, no decision needed (both are kept):
- **Character identity:** B uses Higgsfield **Soul** (`soul_2` + `soul_id`, Lenny) and **Elements** (`<<<id>>>` in the prompt, Franz). A uses master images plus character sheets as `image_references`. Elements may be worth trying for Biscuit and Reginald.
- **"Higgsfield has no desktop tools":** true for generation. The MCP does list after-effects and blender setup recipes, but we don't use them.

---

## 2. The roster

| Character | Strand | Archetype | Status | Details |
|---|---|---|---|---|
| **Biscuit** | A (ODD EYES) | Cute cream mini dachshund who out-dances you; baby-blue tracksuit, odd eyes | Live in the studio; first video (Single Ladies) in the Queue | [characters/biscuit/bible.md](../characters/biscuit/bible.md), `refs.json` |
| **Reginald "the Quiff"** | A (ODD EYES) | Stone-faced 74-year-old English butler, flawless deadpan dancer | Live in the studio; first video (Wednesday) in the Queue | [characters/reginald/bible.md](../characters/reginald/bible.md), `refs.json` |
| **The Outsider** | A | 1852 Victorian gentleman lost in 2026 London (talking lane) | Concept; waits on the voice pipeline | [roadmap.md](roadmap.md) |
| **The Singer** | A | Lip-syncs the greatest classics in the car, shower, while running (licensed in-app songs) | Concept | [roadmap.md](roadmap.md) |
| **Lenny Gold** | B | Manic Hollywood super-agent | Complete; first full clip done | §3.1 |
| **Franz** | B | Aristocratic mini dachshund, permanently unimpressed | Look complete, voice in test | §3.2 |
| **Borat-type** | B | Clueless foreign correspondent | Not started (see C7) | §3.3 |

---

## 3. Strand B characters (from the brief, kept as written)

### 3.1 Lenny Gold: manic Hollywood super-agent
- **Look (locked):** slicked black pompadour, square jaw, deep tan, navy pinstripe suit with wide shoulders, gold watch, phone to his ear.
- **Template "explode in, collapse out":**
  - First ~3 s: a mid-tantrum phone call.
  - Middle: rides the trend.
  - Last ~2 s: fury drops into smug calm, he fixes his tie and delivers a catchphrase. The tonal whiplash is the joke.
- **Catchphrases:** "You're welcome" and "Call my assistant".
- **Voice (locked):** Higgsfield preset **Emmett**, `voice_id 3c7d32be-0182-5c5e-aa6a-663409bfbb26`, model `seed_audio`, `speech_rate: 2` (an integer). Cillian was tried first and rejected.
- **Signature rant:** "Nonono — don't you DARE put me on hold! Twenty years in this business, sweetheart, TWENTY! I don't wait. For ANYBODY. You tell him — the offer is off the table at noon. NOON! ...Eh. Relax. He calls back in five minutes. They always do. You're welcome."
- **First clip caption:** "When they put me on hold for the third time" (captions still to be burned in).
- **Note:** Reginald also wears a black pompadour. They're different characters in different outfits, but worth keeping visually distinct if both join one universe (C8).

### 3.2 Franz: aristocratic miniature dachshund
- **Look (locked):** cream long-haired mini dachshund, big dark eyes, smug old-money expression, navy polo with no logos, warm minimalist interior. The base version has no gadgets.
- **Personality:** an outraged tiny aristocrat who thinks he's royalty.
- **Movement:**
  - Default: a stiff, dignified gala-trot, chin up, never rushes.
  - Provoked: a frantic little-legged scramble with ears flying, then he recovers his composure.
  - Can dance: starts above it all, then betrays himself into tiny disco.
  - A single stair defeats him.
- **Styling:** European casual-luxury.
  - Tech props: sunglasses (near-signature), phone, over-ear headphones, tablet.
  - Athleisure: headband, bracelets, sneakers, shorts.
- **Voice (testing):** Higgsfield preset **Alistair**, `voice_id d9d5c263-f84e-4752-97b5-3750fcc6fd2f`. Test line: "One does not simply walk. One arrives. I have never taken a staircase in my life — that is what people are for. Now. Someone fetch my water. The small bowl. The crystal one."

### 3.3 Borat-type: clueless foreign correspondent
- Bad jokes, wild dancing, oblivious charm. Unnamed, no look yet. Strand A's version is the Outsider (C7).

---

## 4. Strategy (both strands)

- **Shared ground:**
  - An original-IP roster on Instagram and TikTok that rides already-viral formats.
  - Archetypes, never a real person's likeness or voice.
  - AI disclosure on every post: A puts it in every caption (code-enforced), and Reginald's Instagram profile carries the AI label.
  - Hook in the first second.
  - Captions in the character's voice.
- **Strand A launch rule:** the first posts of a channel are absolute hits people know, mainstream "cool" classics the owner recognises (not internet memes). Scored Instagram/TikTok viral clips follow.
- **Lengths:** classics 12–15 s, other clips 8–10 s, 16 s maximum.
- **Ending:** no eye close-up, flash or sound at the end.
- **Captions:** the caption playbook in the daily-run skill: a searchable title line, the joke in the character's voice, one rotating engagement line, the credit, 3–5 hashtags and a first comment.
- **Paid amplification:** Launchpoint (creator campaigns at ~$1 per 1,000 views), only as a capped test after the week-3 review ([roadmap.md](roadmap.md)).
- **Strand B pipeline**, which strand A's "Drop a video" flow mirrors:
  1. Scout a viral format.
  2. **Deconstruct** it into a 5-part recipe: the hook (first 3 s), the beat map, the sound, the hook-to-payoff logic, and the character translation.
  3. Recast the character.
  4. Ship with a voiceover and in-character captions.
- **Strand A's "Drop a video"** (in build, [plan](superpowers/plans/2026-10-06-drop-a-video.md)):
  1. The owner drops videos or links.
  2. A free check, then a Gemini **deconstruct** (the same 5-part idea).
  3. The price is shown, and the owner taps **Make it**. No credits are spent without that tap.
  4. Genjutsu runs, then QA, then the video goes to the Queue.

## 5. Technical recipes (Higgsfield)

- **Genjutsu modes:**
  - **Object swap** keeps the shot and replaces the selected character or object.
  - **Motion transfer** keeps the motion, camera and timing and rebuilds the scene.
  - Reference video 4–30 s.
  - Short prompts in Higgsfield's style: "replace the man with the cat from @image1".
  - Swap **like for like** (a small dog can't replace a human dancer: Genjutsu inserts it instead).
- **MCP:**
  - Call `generate_video` with `hf_mult_replace_object` or `hf_mult_motion_control`, `resolution: 1080p`, `use_unlim: false`.
  - Pass `declined_preset_id: 24bae836-2c4a-48e0-89b6-49fcc0b21612` to bypass the false "IN THE DARK" preset match.
  - `get_cost: true` preflight is free.
  - Web media must go through `media_import_url`, as an HTTPS media file. Instagram links return HTML, so they don't work.
- **Public API:** `POST https://api.higgsfield.ai/higgsfield/genjutsu/object-swap/v1.0` (and `/motion-transfer/v1.0`).
  - Header: `Authorization: Key <id>:<secret>`.
  - Body: `video_url`, `image_urls` (1–8), `prompt`, `resolution`.
  - Poll `status_url` for the result.
- **Character identity:**
  - Lenny: `soul_2` with `soul_id cdc73565-fa87-47f6-bca4-bb1e7884e483`.
  - Franz: Element `<<<a28cc772-0227-4ed1-b6a2-1c84fe3b78f2>>>` **inside `params.prompt`**, never in `medias`.
    - Image models that accept it: `nano_banana_pro`, `nano_banana_2`, `gpt_image_2`, `seedream_v4_5`, `seedream_v5_lite`, `cinematic_studio_2_5`.
    - Video models that accept it: `cinematic_studio_video_v2`, `cinematic_studio_3_0`, `seedance_2_0`, `kling3_0`.
  - Biscuit and Reginald: master plus character sheet (job ids in `refs.json`) as `image_references`. Public CDN URLs are in `refs.json` `reference_urls` for the API.
- **Dog-anatomy guard** for a dog in motion transfer: "adapt the movement naturally to a real dog's body… long low body and short legs… no human limbs, no distortion." Without it the dog came out human-sized in Biscuit's Single Ladies.
- **Voice onto video:** `voice_change` with the clip's job_id and a preset voice_id, about 1 minute.
- **Costs and times:**
  - 1080p Genjutsu ≈ 11–12.5 credits per source second.
  - A Seedream still ≈ 1 credit.
  - Renders take about 12–16 minutes. Wait in the background, then do one `jobs_wait` (15 s max per call).

## 6. Asset register

All URLs share the prefix `https://d8j0ntlcm91z4.cloudfront.net/user_3FpDaPTqXIGIuGg9Gh73nLwPXRT/`.

**Biscuit (A):**
- Look C masters: biped `e07675a2`, quadruped `d863df81`.
- Sheets: biped `a81a474c`, quadruped `aad0f3d0`.
- Close-up: `4f7fc954`.
- Lookbooks: `docs/characters/`.

**Reginald (A):**
- Quiff B master `6c445225`, sheet `a0216125`, close-up `6bf83e23`.

**Finished videos (A):**
- Wednesday: clip `582b6328`, 88 credits.
- Single Ladies: clip `ae8bcab5`, 78 credits.
- Both are in the studio Queue and in Supabase Storage.

**Lenny (B):**
- Soul: `cdc73565-fa87-47f6-bca4-bb1e7884e483`.
- Master sheet (seed 778903): `hf_20261005_175640_93d2d266-9278-4c72-a932-e084c1b31bed.png`.
- Dance-ready still: `hf_20261005_192347_05c16541-867c-4f41-8526-cc948766f41a.png`.
- Silent recast: `hf_20261005_193526_07f294d3-ac35-4f8d-b7aa-614fc34ddc01.mp4`.
- **Recast + Emmett voice (first full clip):** `hf_20261006_042935_f6bf6513-4045-40cc-a0f7-4576743238c4.mp4`.
- Rant audio: `hf_20261006_042740_4e7bea3d-b933-4df1-9fee-4d2d49835f44.wav`.
- Older: `1cfb5c85…`, `cf4242ec…`, `4a7ec81c…`.

**Franz (B):**
- Element: `a28cc772-0227-4ed1-b6a2-1c84fe3b78f2`.
- Master: `hf_20261005_185241_94ac099b-4268-4b99-b36d-03cab38eb01e.png`.
- Silent recast: `hf_20261005_194731_3897d093-4196-41b2-ac37-0132728fb7c9.mp4`.
- Alistair test: `hf_20261006_043131_892db83e-6d5e-4b2e-abca-ad998634b223.wav`.
- Poses: front `5f2a9b92`, profile `9f565adb`, full-body `2ef41ae7`, haughty `38ea3c74`, happy `b10cf4b7`, scared `028fb465`.
- Props: sunglasses `be42f42e`, phone `6012cd3a`, headphones `57ab3fed`, tablet `ef2aa6b3`, headband+sneakers `8f97e211`, shorts+bracelets+sneakers `ddb387bf`.

## 7. Status and next steps (combined)

1. **Olivier: decide the conflicts in §1,** C1 (footage) and C5 (two dachshunds) first. Everything else follows from them.
2. **A:** post Wednesday and Single Ladies from the Queue. Finish "Drop a video" (owner keys: Higgsfield API, Gemini, GitHub dispatch token). Pick Reginald's next classic.
3. **B:**
   - Burn the captions into Lenny's first clip.
   - Approve or replace Franz's Alistair voice, then merge it onto his recast.
   - Run one genuinely hot clip through the engine as the real proof of concept. vidIQ scouting needs credits: there are 3 until 4 Nov.
4. **Roster:** settle the Borat-type / Outsider question (C7), and one universe versus standalone brands (C8).
5. **Once decided:**
   - Bring the chosen B characters into the studio pipeline: `characters/<slug>/` bible + `refs.json`, accounts, then seed.
   - Fold any rule changes into `CLAUDE.md`.
   - Update this file. It stays the single master.
