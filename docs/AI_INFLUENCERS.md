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

**Decided by Olivier on 2026-10-06** ("let's keep it simple"):
- **C1, C2, C3: footage.** The main way to make a video is to **download the footage and drop our characters in with Genjutsu Object swap, keeping the original shot**. Famous clips are fine, as long as the real star is replaced. Motion transfer is only the fallback when there is no usable clip.
- **Music:** the clip's original sound stays for now. Changing the music is an option for later.
- **C4: downloading.**
  - Olivier may download clips himself with a downloader site (e.g. snapinsta) and drop the files into the terminal.
  - The system's own automated sourcing keeps to `yt-dlp` and owner uploads: no third-party download sites inside the automation, which would mean downloading from untrusted sources.
  - Clips saved with the Instagram or TikTok app carry a watermark. The free check catches it.
- **C9: publishing.** "Our social media manager" will handle hosting, captions and timing later. The focus now is on getting the videos made.
- **C5: one dachshund, Franz.** Biscuit is retired. His finished Single Ladies video stays unposted (owner 2026-10-06); `biscuit.moves` becomes Franz's account. The studio swaps Franz in wherever a dog is the star.
- **C7: the Borat-type is from an invented country** (e.g. "the Republic of Gorvania": invented customs, accent and name). All the clueless charm, no real nationality mocked, and it's ownable IP. It **replaces the Outsider** (the 1852 Victorian), which is retired.

**The roster from 2026-10-06:**
- **Franz:** the dog.
- **Reginald:** the butler.
- **Lenny Gold:** the agent.
- **The Borat-type:** to design and name.
- **The Singer:** stays a later concept.
- **The DJ (owner, 2026-10-06): next new character, to design.** Confident, does the SAME signature moves to whatever music he
  plays, instantly recognisable, an exaggerated take on how DJs dress now (oversized heavyweight tee, baggy cargos, chunky
  sneakers, tinted sunglasses at night, headphones parked round the neck as the badge of the trade). Like for like: he
  replaces the DJ in DJ clips (the owner's saved #09, #11, #15 are DJ clips). Proposal and look tests in `characters/dj/`.

**Character decisions (owner, 2026-10-06):**
- Signature moves locked: Franz the Chin Lift, Reginald the Glove Tug, Lenny the Tie Snap.
- Catchphrases locked: Franz "That is what people are for.", Reginald "As you were.", Lenny "You're welcome."
- Reginald is mid-40s (not 74). Franz's voice is Alistair (approved).
- Instagram `biscuit.moves` is renamed to Franz (`franz.dachshund`, owner step); Biscuit's Single Ladies video stays unposted.
- Lenny's first full clip (charcoal suit) is remade in the chalk-stripe (price first).
- The masters of Franz, Lenny and Reginald are upscaled to 2K (identity unchanged); the Borat-type's was already 2K.
- Borat-type: the look stays as it is (owner accepts the likeness risk; he skips LaunchPoint). Name still open: it must be
  our own, not one letter from the film character's name and not a real nationality's surname (C7).
- Children are fine in a clip (crowds, families, spectators); only the star our character replaces must be an adult, which is
  also the like-for-like rule. Still rejected: sexualised content, and a child as the star or main subject.
- **C8 decided: one studio signature, separate brands.** ODD EYES on every character (his right eye, on the viewer's left,
  ice-blue; his left eye amber) and the two-dot mark on every video (`studio/media/master.py` adds it to every master, whatever
  the character). Each character is his own brand with his own accounts. Biscuit is retired (status `paused`, kept for history).
- **C10 decided: the slots.** Franz 19:00, Reginald 19:30, Lenny 12:30 (London); the same days for all: weeks 1-2 Tue/Wed/Thu,
  from week 3 Mon-Fri; at most 2 posts per account per day. The live cadence is set with `bin/studio plan cadence`.
- Nothing is generated now: infrastructure, process and characters are set up first.

Still open: C6 (posh British twice: Franz and Reginald), C11 (voice in the studio), C12 (shared credits), and the Borat-type's name
(he joins the studio, scan and terminal through `characters/<slug>/` once named, with no code change).


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
| C11 | **Voice** | Every clip ships with a voiceover (Lenny: Emmett; Franz: Alistair, approved 2026-10-06). | Biscuit and Reginald are silent and music-driven (Reginald never speaks); voices are planned for the Outsider (Slice 3 "talking lane"). | No conflict for existing characters. Should voiced characters join the studio pipeline (it has no voice step yet)? |
| C12 | **Credits** | Uses the same Higgsfield account. | Studio budget: monthly cap 6,000 credits, plus per-video approval by the owner. Both strands draw from **one shared balance** (≈ 750 left on 10-06). | One budget for both strands? B's spend isn't recorded in the studio ledger. |

Smaller differences, no decision needed (both are kept):
- **Character identity:** B uses Higgsfield **Soul** (`soul_2` + `soul_id`, Lenny) and **Elements** (`<<<id>>>` in the prompt, Franz). A uses master images plus character sheets as `image_references`. Elements may be worth trying for Biscuit and Reginald.
- **"Higgsfield has no desktop tools":** true for generation. The MCP does list after-effects and blender setup recipes, but we don't use them.

---

## 2. The roster

| Character | Strand | Archetype | Status | Details |
|---|---|---|---|---|
| ~~Biscuit~~ | A (ODD EYES) | Cute cream mini dachshund; **retired 2026-10-06** (one dachshund: Franz) | Single Ladies video in the Queue (owner to post or drop) | [characters/biscuit/bible.md](../characters/biscuit/bible.md), `refs.json` |
| **Reginald "the Quiff"** | A (ODD EYES) | Stone-faced mid-40s English butler, flawless deadpan dancer | Live in the studio; first video (Wednesday) in the Queue | [characters/reginald/bible.md](../characters/reginald/bible.md), `refs.json` |
| ~~The Outsider~~ | A | 1852 Victorian gentleman; **retired 2026-10-06**, replaced by the Borat-type | n/a | [roadmap.md](roadmap.md) |
| **The Singer** | A | Lip-syncs the greatest classics in the car, shower, while running (licensed in-app songs) | Concept | [roadmap.md](roadmap.md) |
| **Lenny Gold** | B | Manic Hollywood super-agent | Complete; first full clip done | §3.1 |
| **Franz** | B | Aristocratic mini dachshund, permanently unimpressed | Look complete, voice in test | §3.2 |
| **Borat-type** | B | Clueless correspondent from an **invented country** (C7 decided) | To design and name | §3.3 |

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

## 4a. Income lane: LaunchPoint "AI Invasion" (owner 2026-10-06)

LaunchPoint isn't only for buying reach: it runs **paid creator campaigns**. "AI Invasion" pays creators of AI-influencer videos **$1 per 1,000 verified views, up to $2,000 per video** (owner's source; Higgsfield is a LaunchPoint customer with 700+ creators and 350M+ views).

**Workflow:** read the campaign rules first, then make videos that fit them, post as the rules say, and submit through the campaign.

**Rules as reported, to verify inside the LaunchPoint creator app** (they're behind a login, so the owner has to sign up and read them):
- An original character: no celebrities, brands or movie characters.
- **Your own recordings, or footage you have permission to use.**
- LaunchPoint checks every post and catches copied videos and fake views before paying.

**What this means for us:**
- **Two lanes:**
  - Our **channel growth** lane keeps Drop-in into downloaded viral clips (owner decision, section 1).
  - The **income** lane needs **footage we own**. The simplest version: the owner (or friends) films short trend formats on a phone in real daylight in real places (the JeanPhil "reads as filmed" rule), and Genjutsu Object swap puts Reginald or Biscuit in. Image-to-video from our own character stills also counts as original.
- **Downloaded clips (e.g. snapinsta) won't pass** as campaign submissions: they're copied footage. Never submit them.
- **Owner step:** create the LaunchPoint creator account (Claude never creates accounts), open "AI Invasion", and share its rules (paste or screenshot, or let Claude read them in Chrome). Then we plan the first submission against the exact brief.

## 4b. Character design rules (the JeanPhil lesson, owner 2026-10-06)

JeanPhil: an AI Frenchman (blond bob, handlebar moustache, houndstooth suit, slow air-punches down a Paris pavement, "Oui Madame") reached ~100M views in a week, and within days had a coin and lawyers. The moat is **designing someone people want to see a second time**: a casting and writing problem, not a rendering one. Every character must pass these five rules:

1. **Reads from a thumbnail:** recognisable at 50 feet, muted, mid-scroll, from silhouette, hair and costume.
   - Reginald: the black pompadour quiff, round glasses, moustache, tails and white gloves.
   - Biscuit: a cream dachshund in the baby-blue velour tracksuit. The odd eyes don't read at thumbnail size, so the tracksuit carries him.
2. **One signature move, repeated:** every clip becomes "a Reginald", so the character becomes a format.
   - Proposals, owner to pick: Reginald **tugs his white gloves, deadpan** (or a tiny formal bow); Biscuit **flips his ears / lowers his aviators**.
   - Object swap keeps the clip's own moves, so the signature move would be a short 1-2 s tag, at extra cost: decide before adding.
3. **A free, quotable catchphrase:** viewers repeat it, which turns them into distributors.
   - Proposals: Reginald **"As you were."** (or "The household is unaware."); Biscuit **"obviously."**
   - Use it in every caption's joke line or first comment.
4. **Reads as filmed:** ordinary daylight, real places, handheld drift, so nobody starts inspecting the render. Drop-in into real footage gives us this for free. Prefer real-world clips over studio or AI-looking sources.
5. **Consistency = one reference image:** same face, same outfit, any place. That's our masters, sheets and `reference_urls`. Never redesign mid-run.

Also:
- **Protect the IP early:** a character that takes off outgrows its creator within days. The audit's owner item still applies: a UK IPO trademark search, then filing "ODD EYES" and the character names, and reserving the handles everywhere.
- **Test a new character cheaply:** image-to-video from one still before building a pipeline. This matters for strand B's characters and any new ones.

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

## 5b. Standard models (owner 2026-10-06)

**Images:** `gpt_image_2_5` for every character image. It's photoreal and follows the wardrobe detail.
- Comparisons: quality medium, 1k (0.5 credits).
- Final sheets: quality high, 2k (2.75 credits).

**Video, the standard way (owner 2026-10-06, corrected):** **Genjutsu Object swap** (`hf_mult_replace_object`) drops the character into the clip and keeps the original shot. Every video is made this way.
- Like for like: a person for a person, a dog for a dog.
- 1080p, short prompt, ≈ 11-12.5 credits per second.
- Get the price first (free), and generate only on the owner's go.

**Seedance 2.5** (`seedance_2_5`) is a secondary tool, used only where there is no clip to swap into:
- original clips from the character pictures (e.g. LaunchPoint "AI Invasion" own-content);
- extending a clip;
- edits.

Seedance details: `omni_reference`, `video_edit` and `video_extension` modes, 4-30 s, up to 1080p. Use **draft first** (`draft: true` gives a 480p draft, 12 s ≈ 36 credits), then finalize at 1080p (12 s ≈ 144 credits).

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
