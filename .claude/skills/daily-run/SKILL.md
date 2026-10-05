---
name: daily-run
description: ODD EYES daily run (scheduled task): plan, scan, produce, QA and queue today's clips.
disable-model-invocation: true
---
# Daily run

Work from the repo root. Every state change goes through `bin/studio` (JSON on stdout). Exit codes: 0 ok, 1 a check failed (read the JSON), 2 caller error (fix the call), 3 budget refused, 4 `fav decide` needs an analyst. MCP: Higgsfield and vidIQ. Pass `use_unlim: false` on every generation. Files live in `renders/<clip id>/`.
Hard limits: at most the clips in `plan today`; one re-roll per clip; no new reserve or submit after a budget refusal. Whatever happens, finish with step 9.

## 1. Plan
1. `bin/studio plan today`. Empty `due` or `kill_switch: true` → step 9 (`ok`).
2. `bin/studio seed status`. Drop due clips whose character has `live: false`, and those whose `characters/<slug>/refs.json` has `closeup: null` (every master ends on the eye close-up). Nothing left → step 9.
3. Per due character run `bin/studio clip list --character X`. A clip already `planned` today (London date), or `gen_failed` from an earlier day, is reused: its `features` hold the concept, it keeps its source (no new driver) and `clip new` is skipped. Collect the `source_id` of that character's clips from the last 30 days as `EXCLUDE`.

## 2. Scan (a failure here never blocks production; note it for step 9)
Only on Tue, Thu, Sat, Sun: at most 4 scans a week. Settings live in `config/scan.json`. Before any vidIQ spend call `vidiq_balance`: a scan needs 5 credits, a breakdown 10 plus a 20-credit floor.
1. `slot` = 4 × ISO week number + (Tue 0, Thu 1, Sat 2, Sun 3). With the live characters sorted by slug (N of them): character = index `slot mod N`, query = its `rotation[(slot div N) mod 4]`.
2. vidIQ `instagram_tiktok_outlier_search`: the entry's `query` and `embeddingType`, the character's `audienceQuery`, the file's `defaults` (`posted_within_days` becomes `datePostedAfter`, today minus N days as `YYYY-MM-DDT00:00:00Z`), `excludeContentIds` = ids and shortcodes from the URLs of `bin/studio fav list --status all`.
3. Keep an outlier that passes `global_reject_rules` and the character's `fit_rules` (brand safety is pass/fail; a fail is never stored). File each: `bin/studio fav pick --url U --platform P --views V --outlier-x X --creator @h --character C --proposal '{"mode","hook","prop","concept","needs"?}' --freshness F --fit T --feasibility S --saturation A`.
   Judge 0-10: freshness 10 rising now, 6 evergreen, 3 past peak. Fit = match with the character's premise. Feasibility 10 solo, full body, static camera; 6 two bodies; 4 three or more bodies; 3 needs the talking lane. Saturation 10 fresh, 5 template everywhere. `needs` takes only `multi_body` or `talking_lane`.
4. `bin/studio fav decide <id>` on each pick just filed (`duplicate: false`): the standing rule. Exit 4 → `fav decide <id> --decision approve|skip --reason "<one line>" --by analyst` (approve when we can make it now and it fits the brand).
5. Free reads: Genjutsu `get_presets` (`source: genjutsu`, categories `genjutsu-trending`, `genjutsu-new`). For at most 3 new clips: `curl` the preview, `bin/studio qa frames F --out renders/lib.jpg`, look at the 6 frames (watermark, overlay, other people, bodies, body type), `bin/studio source add --kind higgsfield_library --url U --preset-id I --body B --bodies N --duration S --trend T`, then `bin/studio source check <id> --no-watermark --no-overlay --other-people 0` (`--watermark`, `--overlay` and the real count when seen). `tiktok_music_trending`: when `tiktok_accounts` lists a connector, put the top 3 sounds in the summary.

## 3. Concept (Approved Viral Picks are produced before planned concepts)
1. `bin/studio fav list --next 8`. Per due clip take the first pick whose `character_slug` matches.
2. A pick still `approved`: vidIQ `watch_shortform_content` (10 credits; poll `vidiq_job_poll`) with the prompt "Beat-by-beat: choreography, setting, camera, hook text, audio type." Then `bin/studio fav mark <id> --status analysed --breakdown "<markdown>"`. Without the credits, brief from `proposal.concept` and leave it `approved`.
3. The pick's `proposal` (hook, prop, concept, enhancement) is the clip's concept. Choose 1-3 enhancements (`slowmo`, `zoom_hit`, `impact_sfx`, `text_pop`, `title_card`).
4. No pick for that character → the first row of `docs/launch/channel-strategy.md` section 5 for it whose hook is not a `hook_text` of its clips.
5. Mode = the plan's. Drop-in only with a source that passed the visual checks (no watermark, overlay or other people): `bin/studio source list --rank --character X --mode dropin --exclude <EXCLUDE ids>`, first row; a pick is Drop-in only when its `source_id` is in that list. Recreate: a pick gets a synthetic driver briefed from its breakdown; a planned concept takes the first row of `source list --rank --character X --mode recreate --exclude ...`, or a synthetic driver when the list is empty. A source `url` that is a bucket path (`owner_inbox`) cannot be handed to Higgsfield yet: take the next row.

## 4. Assets (every clip together)
1. `bin/studio budget status`: `kill_switch` true or `remaining` below the plan's `estimated` → step 9 (`budget_stop`).
2. Cost: `generate_video` or `generate_image` with `get_cost: true` returns the credits without submitting. Preflight each job right before submitting it and keep the number. A clip's actual = the sum over its completed jobs (a failed job is refunded; a driver shared by two clips counts half to each).
3. Submit all jobs first (`generate_image_batch`, `generate_video_batch`), then `jobs_wait` in groups of 12 (a render takes about 6 minutes):
   - Scene still (Recreate only): `seedream_v4_5`, `quality: high`, `aspect_ratio: 9:16`, reference = `masters[body]` of refs.json (role `image_references`); prompt = setting + prop, one-piece outfit.
   - Synthetic driver (only for a clip that needs one): `seedance_2_5`, `mode: t2v`, `resolution: 480p`, `duration` 9-10, `aspect_ratio: 9:16`, `generate_audio: true`. Prompt = sharp, slick choreography (from the breakdown or concept) + the bible's music brief: afro-house for Biscuit; for Reginald an orchestral swell into afro-house.
4. Per synthetic driver: `bin/studio source add --kind synthetic --url "higgsfield-job:<job id>" --body B --bodies N --duration S`. A library `url` goes through `media_import_url` first; its audio is never used.

## 5. Create and reserve (per clip)
1. `bin/studio clip new --character X --mode M --source <id> --features '{...}'`. Required tags: `format_id` (code from channel-strategy section 1), `hook_pattern` (reuse earlier clips' wording), `hook_text`, `prop` ("none" if none), `setting`, `motion_type`, `audio_arm` (own_beat, trend_sound, owner_song), `bodies_in_frame`, `seamless_loop`, `eye_closeup_end` (true), `trend_name` ("evergreen" if none). Add `fav_id` for a pick, then `bin/studio fav mark <pick> --status queued --clip <clip>`.
2. `bin/studio budget status`, note `committed`. Then `bin/studio budget reserve <est_credits from the plan> --clip <clip>`. Exit 3 → this and later clips stay `planned`; step 9 with `budget_stop`. Exit 2 → fix the call. `reserve` is not idempotent (two reserves add up): when it prints no JSON, run `budget status` and repeat only if `committed` did not rise.
3. `bin/studio clip set <id> --state generating --credits-reserved <est>`.

## 6. Genjutsu (every reserved clip together)
1. Preflight each job (`get_cost`, step 4.2), then `generate_video_batch`: `hf_mult_motion_control` for Recreate, `hf_mult_replace_object` for Drop-in, `resolution: 1080p`; medias = the scene still (Recreate) or `masters[body]` (Drop-in keeps the source's own setting) as `image_references` + the driver or source video as `video_references` (a `higgsfield-job:` source is its job id). When the reply suggests a preset, resubmit with `declined_preset_id`. `jobs_wait` until all are terminal.
2. Per clip: a failed job → `bin/studio clip set <id> --state gen_failed`, then `budget settle` for the completed jobs, or `budget release` when none completed. Success → `bin/studio budget settle <clip> <actual>` and `clip set <id> --state generated --hf-job-id <job> --credits-actual <actual>`.

## 7. QA (per clip)
1. `curl -L -o renders/<id>/gen.mp4 "<url from jobs_wait>"`.
2. `bin/studio qa tech renders/<id>/gen.mp4`. Exit 1 prints JSON with `ok: false` and a `problems` list: read it, it is the verdict.
3. `bin/studio qa frames renders/<id>/gen.mp4 --out renders/<id>/frames.jpg --n 6`, then look at the sheet:
   - ODD EYES: the character's RIGHT eye (viewer's left) is ice-blue, the LEFT eye (viewer's right) amber.
   - Outfit and identity match the master; no exposed belly.
   - Hands and paws: clean digits, no melting, extra limbs or flicker.
   - Reginald: deadpan, no smile; the quiff stays rigid.
   - Nothing leaked from the source: no driver person, watermark, overlay or handle.
4. Fail → `bin/studio clip set <id> --state qa_failed --qa '{"tech":...,"visual":"<what>"}'`. Leakage from a Drop-in source → `bin/studio source flag <source> --reason "<what was seen>"`. Re-roll once: `budget reserve` (status check first), `clip set <id> --state generating`, step 6 for that clip, then step 7 again. A second failure → `clip set <id> --state dropped`.
5. Pass → `bin/studio clip set <id> --state qa_passed --qa '{...}'`.

## 8. Master and queue (per clip)
1. Write `renders/<id>/spec.json` (fields of `MasterSpec`, studio/media/master.py): `dance` gen.mp4; `closeup` = the refs.json `closeup` job downloaded once to `renders/closeups/<slug>.png` (`jobs_wait` with `timeout_seconds: 0` returns its URL); `closeup_center` and `blue_eye_xy` from refs.json; `hook1`, `hook2`, `hook2_until_s`; `audio` = gen.mp4 for a synthetic driver (it carries our beat), else a `generate_audio` track from the bible's music brief; `audio_offset_s`; `out` = `renders/<id>/master.mp4`; `enhancements`. Place any `slowmo` near the end beat: slowmo is video-only, so the picture would lag the beat after it.
2. `bin/studio master build --spec renders/<id>/spec.json` (`--loop` for an eye loop). Exit 1 → read `problems`, fix the spec once, rebuild.
3. Caption in the bible voice, at most 5 hashtags, passed through the `humanizer` skill. A Drop-in caption ends with `trend: <credit_handle>`. Publishing adds the AI disclosure.
4. `bin/studio master upload <id> renders/<id>/master.mp4` (`--loop` for an eye loop), then `bin/studio clip set <id> --state mastered --hook "<hook>" --caption "<caption>" --hashtag "#a" --hashtag "#b"`, then `clip set <id> --state awaiting_approval`. A pick → `bin/studio fav mark <pick> --status made`.

## 9. Log
`bin/studio run log --kind daily --status ok|budget_stop|error --summary "<text>"`: clips made (id, character, pick), credits settled against `balance`, scan result, anything skipped and why. `budget_stop` after a refusal, `error` when a step crashed (name it).
