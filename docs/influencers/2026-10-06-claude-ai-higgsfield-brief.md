# AI Influencers — Master Brief (from claude.ai / Higgsfield sessions)

> **For Claude Code:** This is the full state of the AI-influencer work done in claude.ai with Higgsfield (Oct 2026). Merge it with whatever already exists in this repo. Where the two disagree, flag the conflict to Olivier rather than silently picking one. Then make this the single source of truth (e.g. reference it from CLAUDE.md).

---

## 1. The idea

A roster of recurring **AI virtual influencer characters**, built in Higgsfield and posted to **Instagram and TikTok**. Each character is original IP: an archetype, never a likeness of a real person.

**Core strategy:** recreate *already-viral* Instagram/TikTok formats with these characters. Copy the **format** (hook, beat, sound, structure), **never the literal footage**. The footage rule covers legal exposure and platform re-upload detection.

**Legal line (held repeatedly, non-negotiable):** no real-person photos as references, and no cloning a real actor's or character's voice or likeness. That rules out Ari Gold, Entourage footage and Jeremy Piven, whatever the tool (Higgsfield, ElevenLabs or anything else). The *energy* of an archetype is fine; the person is not.

---

## 2. Characters

### 2.1 Lenny Gold: manic Hollywood super-agent (COMPLETE)
- **Look (locked):** slicked black pompadour, square jaw, deep tan, navy pinstripe suit with wide shoulders, gold watch, phone to ear.
- **Content template (locked) — "explode in, collapse out":**
  - First ~3s: mid-tantrum on the phone; it should sound like the middle of a fight.
  - Middle: rides whatever trend the clip is recreating.
  - Last ~2s: fury drops into smug calm, he fixes his tie and delivers a catchphrase.
  - The tonal whiplash *is* the joke.
- **Catchphrases:** "You're welcome" (after doing a favour) and "Call my assistant" (dismissive).
- **Voice (locked):** Higgsfield preset **Emmett** (rough, barking), `voice_id 3c7d32be-0182-5c5e-aa6a-663409bfbb26`, model `seed_audio`, `speech_rate: 2` (must be an integer). Cillian was tried first and rejected as too slow and polite.
- **Signature rant script:**
  > Nonono — don't you DARE put me on hold! Twenty years in this business, sweetheart, TWENTY! I don't wait. For ANYBODY. You tell him — the offer is off the table at noon. NOON! ...Eh. Relax. He calls back in five minutes. They always do. You're welcome.

### 2.2 Franz: aristocratic miniature dachshund (COMPLETE, voice in testing)
- **Look (locked):** cream long-haired mini dachshund, big dark eyes, smug old-money expression, **navy polo with no logos**, warm minimalist interior. The base version has no gadgets.
- **Personality:** outraged tiny aristocrat who thinks he's royalty; permanently unimpressed.
- **Movement language:**
  - Default: stiff, dignified gala-trot, chin up, never rushes.
  - Provoked: sudden frantic little-legged scramble with ears flying, then he recovers his composure.
  - Can dance (signature bit): starts above it all, then betrays himself into tiny disco.
  - Not athletic; a single stair defeats him.
- **Styling:** European casual-luxury (polo-and-loafers, understated). Prop library:
  - Tech: sunglasses (near-signature), phone, over-ear headphones, tablet.
  - Athleisure: headband, bracelets, sneakers, shorts.
- **Voice (testing):** Higgsfield preset **Alistair** (plummy, posh, deadpan), `voice_id d9d5c263-f84e-4752-97b5-3750fcc6fd2f`. Test line:
  > One does not simply walk. One arrives. I have never taken a staircase in my life — that is what people are for. Now. Someone fetch my water. The small bowl. The crystal one.

### 2.3 Borat-type: clueless foreign correspondent (NOT STARTED)
- Bad jokes, wild dancing, oblivious charm. **Unnamed, no look yet.**
- Name ideas floated: Borys, Vlad Bogdan, Dmitri the Magnificent, Grigor.

---

## 3. Production pipeline

**Trend-recreation engine:**
1. **Scout** a viral format.
2. **Deconstruct** it into a 5-part *format recipe*:
   - the hook (first 3s)
   - the beat map (structure and timing)
   - the sound
   - the hook-to-payoff logic (why it works)
   - the character translation (how the character's template absorbs it)
3. **Recast** the character via Soul/Element plus motion transfer.
4. **Ship** with voiceover and in-character captions to TikTok/Reels.

**Clip intake (manual gate, permanent):** collect reel/TikTok links through the week. Then do one ~10-minute weekly batch: download via snapinsta.app (or igram.io) and upload all MP4s to Higgsfield together. Automated grabbing is blocked: Instagram returns HTML to `media_import_url` and direct fetch is robots-disallowed. Never enter an Instagram login on downloader sites.

**Four-layer infrastructure (priority order):**
1. Character library
2. Content engine
3. Channel layer (Higgsfield can publish to TikTok directly)
4. Calendar: 3–4 posts/week per character

---

## 4. Technical recipes (Higgsfield)

- **Higgsfield is cloud-generation only.** It has no desktop tools (no Premiere, AE, Blender or Photoshop).
- **Lenny images:** `generate_image`, model `soul_2`, with the soul_id below.
- **Franz images/video:** embed `<<<a28cc772-0227-4ed1-b6a2-1c84fe3b78f2>>>` **inside `params.prompt`**, never in `params.medias`.
  - Image models that accept it: `nano_banana_pro` (runs as `nano_banana_2`), `nano_banana_2`, `gpt_image_2`, `seedream_v4_5`, `seedream_v5_lite`, `cinematic_studio_2_5`.
  - Video models that accept it: `cinematic_studio_video_v2`, `cinematic_studio_3_0`, `seedance_2_0`, `kling3_0`.
- **Motion transfer (the working route):**
  - Model `hf_mult_motion_control`, with `declined_preset_id: "24bae836-2c4a-48e0-89b6-49fcc0b21612"` to bypass a false preset match.
  - Inputs are a character still plus the uploaded reference reel.
  - Pure text-to-video was abandoned because bodies warped.
- **Franz motion prompts need a dog-anatomy guard:** "adapt the movement naturally to a real dog's body… long low body and short legs… no human limbs, no distortion."
- **Voice onto video:** `voice_change` with the clip's job_id and a preset voice_id. It takes about 1 minute.
- **Billing:** spend credits, not free gens (`use_unlim: false`).
- **Timing:** motion-transfer renders can take 10+ minutes. Poll with `jobs_wait` (15s max).

---

## 5. Asset register

Higgsfield user: `user_3FpDaPTqXIGIuGg9Gh73nLwPXRT`. All URLs share the prefix `https://d8j0ntlcm91z4.cloudfront.net/user_3FpDaPTqXIGIuGg9Gh73nLwPXRT/`.

### Lenny
| Asset | ID / file |
|---|---|
| Trained Soul | `soul_id cdc73565-fa87-47f6-bca4-bb1e7884e483` (soul_2) |
| Master sheet (seed 778903) | `hf_20261005_175640_93d2d266-9278-4c72-a932-e084c1b31bed.png` |
| Full-body dance-ready still (9:16) | `hf_20261005_192347_05c16541-867c-4f41-8526-cc948766f41a.png` |
| Motion recast, silent | `hf_20261005_193526_07f294d3-ac35-4f8d-b7aa-614fc34ddc01.mp4` |
| **Recast + Emmett voice (first full clip)** | `hf_20261006_042935_f6bf6513-4045-40cc-a0f7-4576743238c4.mp4` |
| Emmett rant audio | `hf_20261006_042740_4e7bea3d-b933-4df1-9fee-4d2d49835f44.wav` |
| Older: original sheet, crowd ref, crowd-bow video | `1cfb5c85…`, `cf4242ec…`, `4a7ec81c…` |

**Caption picked for the first clip:** "When they put me on hold for the third time"

### Franz
| Asset | ID / file |
|---|---|
| Element | `a28cc772-0227-4ed1-b6a2-1c84fe3b78f2` |
| Master look | `hf_20261005_185241_94ac099b-4268-4b99-b36d-03cab38eb01e.png` |
| Motion recast (silent) | `hf_20261005_194731_3897d093-4196-41b2-ac37-0132728fb7c9.mp4` |
| Alistair voice test | `hf_20261006_043131_892db83e-6d5e-4b2e-abca-ad998634b223.wav` |
| 6-pose sheet | front `5f2a9b92`, profile `9f565adb`, full-body `2ef41ae7`, haughty `38ea3c74`, happy `b10cf4b7`, scared `028fb465` |
| Prop library | sunglasses `be42f42e`, phone `6012cd3a`, headphones `57ab3fed`, tablet `ef2aa6b3`, headband+sneakers `8f97e211`, shorts+bracelets+sneakers `ddb387bf` |

---

## 6. Status and next steps

1. **Done:** first end-to-end Lenny clip (character + motion + voice). Verdict: works; captions still to be burned in.
2. Approve or replace Franz's Alistair voice, then voice-merge it onto his recast.
3. Run the full engine on one genuinely hot clip as the real proof of concept. vidIQ trend scouting needs its own credits.
4. Name and design the Borat-type character.
5. **Open question:** do the characters share one universe or stay as standalone brands?
6. **Merge this brief with the Claude Code project** and keep one master.
