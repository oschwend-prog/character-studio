# Daily-run dry rehearsal (2026-10-05, Task 13)

The `/daily-run` command sequence of `.claude/skills/daily-run/SKILL.md`, run through the real `studio` CLI against a
`MemoryStore` (every module's `open_store` patched; `master upload` writes to a `LocalStorage` folder). **No MCP call and no
Higgsfield credit was used.** The real rehearsal (Genjutsu renders, ~260 credits) is Task 16.

What is real and what is a stand-in:

| Real | Stand-in (labelled where it appears) |
|---|---|
| every `bin/studio` command, its JSON and exit code; the state machine; the budget ledger; `qa tech` / `qa frames` / `master build` / `master upload` | vidIQ scan and breakdown (a fixture row and a fixture breakdown), Higgsfield stills / drivers / Genjutsu (a `testsrc2` clip with a sine tone), the close-up (a flat PNG), `humanizer`, `last30days`, `curl` downloads |
| the 17 batch-1 picks loaded from `docs/launch/viral-picks-2026-10-04.md` | fake handles and Postiz ids in a *rehearsal copy* of refs.json (status `live`), fixture URLs `@rehearsal.fixture` |

The real clock is Mon 5 Oct 2026 (nothing is due on a Monday), so the clock of `plan`, `budget` and `review` is pinned to
Tue 6 Oct 2026 08:00 London. Paths are shortened to `$WORK`. Long outputs are cut or reduced to the fields that matter
(marked "selected fields"). Outputs of the form `exit N (EXPECTED M)` would flag a surprise; there are none.

## Result

The whole chain `plan -> scan -> pick -> reserve -> (generate) -> settle -> qa -> master -> upload -> awaiting_approval -> fav made`
runs end to end on the real code. The ledger ends at 181 settled (the reservation of 160 replaced by the actual) and
`clip.credits_reserved` / `credits_actual` carry 160 / 181. Gaps the rehearsal exposed are listed at the end.


## 0. Seed as shipped (what the repo does today)

`studio seed` reads `characters/*/refs.json`: both characters are `designing`, no account has a handle yet.
`$ bin/studio seed`
exit 0
```json
{
  "characters": [
    {
      "slug": "biscuit",
      "name": "Biscuit",
      "status": "designing",
      "bodies": [
        "biped",
        "quadruped"
      ]
    },
    {
[... 32 more lines]
```
`$ bin/studio seed status`
exit 0
```json
[
  {
    "slug": "biscuit",
    "name": "Biscuit",
    "status": "designing",
    "live": false,
    "bodies": [
      "biped",
      "quadruped"
    ],
    "accounts": []
  },
[... 11 more lines]
```

Skill step 1.2 therefore drops every due clip (no character is `live`) and goes straight to the run log. Everything below uses a *rehearsal copy* of the refs: status `live`, fake handles and fake Postiz ids, in a MemoryStore only.

## 1. Plan

`$ bin/studio seed --characters-dir $WORK/characters`  (rehearsal refs: live + fake handles)
exit 0
```json
{
  "characters": [
    {
      "slug": "biscuit",
      "name": "Biscuit",
      "status": "live",
      "bodies": [
        "biped",
        "quadruped"
      ]
    },
    {
      "slug": "reginald",
      "name": "Reginald",
[... 42 more lines]
```
`$ bin/studio seed picks /Users/olivierschwend/Claude/Projects/character-studio/docs/launch/viral-picks-2026-10-04.md`
exit 0
```json
{
  "picks": 17,
  "created": 17,
  "existing": 0,
  "approved": 7,
  "held": 10
}
```
`$ bin/studio seed picks /Users/olivierschwend/Claude/Projects/character-studio/docs/launch/viral-picks-2026-10-04.md`  (second run: idempotent)
exit 0
```json
{
  "picks": 17,
  "created": 0,
  "existing": 17,
  "approved": 0,
  "held": 0
}
```
`$ bin/studio seed status`
exit 0
```json
[
  {
    "slug": "biscuit",
    "name": "Biscuit",
    "status": "live",
    "live": true,
    "bodies": [
      "biped",
      "quadruped"
    ],
    "accounts": [
      {
[... 41 more lines]
```
`$ bin/studio plan today`  (clock pinned to Tue 2026-10-06 08:00 London)
exit 0
```json
{
  "date": "2026-10-06",
  "weekday": "tue",
  "month": "2026-10",
  "kill_switch": false,
  "cap": 6000,
  "committed": 0,
  "remaining": 6000,
  "estimated": 320,
  "due": [
    {
      "character_slug": "biscuit",
      "mode": "recreate",
      "slot": "2026-10-06T19:00:00+01:00",
      "est_credits": 160,
      "source_candidates": []
    },
    {
      "character_slug": "reginald",
      "mode": "recreate",
      "slot": "2026-10-06T19:30:00+01:00",
      "est_credits": 160,
      "source_candidates": []
    }
  ],
  "deferred_over_cap": []
}
```

Skill 1.2: Reginald's refs.json has `closeup: null` (generated in the Task 16 rehearsal), so his clip is dropped; only Biscuit continues.
`$ bin/studio clip list --character biscuit`  (step 1.3: nothing planned yet, EXCLUDE = {})
exit 0
```json
[]
```

## 2. Scan (vidIQ is an MCP call: replaced by a fixture row)

Scan-day arithmetic for Tue 2026-10-06 (ISO week 41): slot = 4*41 + 0 = 164; two live characters sorted by slug (biscuit, reginald): character = 164 mod 2 = 0 -> biscuit, query = rotation[(164 div 2) mod 4] = rotation[2] (`hook`: "small dog in an outfit stares into the camera, then hits every beat of a high-energy track").
The outlier below is a FIXTURE, not a real video; it stands in for one vidIQ result.

`$ bin/studio fav pick --url https://www.tiktok.com/@rehearsal.fixture/video/1000000000000000001 --platform tiktok --views 900000 --outlier-x 40 --creator @rehearsal.fixture --character biscuit --proposal {"mode": "recreate", "hook": "fixture hook", "prop": "shades", "concept": "fixture concept"} --freshness 7 --fit 8 --feasibility 8 --saturation 6`  (fixture outlier, analyst band; selected fields)
exit 0
```json
{
  "id": "ca671490-5aa2-4195-a246-bab0b6fa34fc",
  "character_slug": "biscuit",
  "status": "new",
  "scores": {
    "virality": 5.3,
    "reach": 3.5,
    "freshness": 7.0,
    "fit": 8.0,
    "feasibility": 8.0,
    "saturation": 6.0
  },
  "total_score": 65.0
}
```
`$ bin/studio fav decide ca671490-5aa2-4195-a246-bab0b6fa34fc`  (the standing rule)
exit 4
```json
{
  "ok": false,
  "needs": "analyst",
  "id": "ca671490-5aa2-4195-a246-bab0b6fa34fc",
  "total_score": 65.0,
  "feasibility": 8.0,
  "message": "favourite ca671490-5aa2-4195-a246-bab0b6fa34fc needs an analyst decision (total 65.0, feasibility 8.0) - rerun with --decision approve|skip --reason '...' --by analyst"
}
```
`$ bin/studio fav decide ca671490-5aa2-4195-a246-bab0b6fa34fc --decision skip --reason fixture: rehearsal row, not a real trend --by analyst`  (exit 4 -> analyst decides with a one-line reason; selected fields)
exit 0
```json
{
  "id": "ca671490-5aa2-4195-a246-bab0b6fa34fc",
  "status": "skipped",
  "proposal": {
    "mode": "recreate",
    "hook": "fixture hook",
    "prop": "shades",
    "concept": "fixture concept",
    "decision": {
      "decision": "skip",
      "by": "analyst",
      "reason": "fixture: rehearsal row, not a real trend"
    }
  }
}
```
`$ bin/studio fav pick --url https://www.tiktok.com/@rehearsal.fixture/video/1000000000000000002 --platform tiktok --views 500000 --outlier-x 12 --character biscuit --proposal {"mode": "recreate", "needs": "multi-body"} --freshness 7 --fit 8 --feasibility 8 --saturation 6`  (a misspelt needs is refused at the door)
exit 2
```
error: proposal.needs must be one of or a list of {multi_body, talking_lane}, got 'multi-body'
```

## 3. Concept

`$ bin/studio fav list --next 8`  (approved picks, oldest first; selected fields)
exit 0
```json
[
  {
    "id": "21bdc2d5-03d3-4a65-99c4-f588be7ca663",
    "character_slug": "reginald",
    "status": "approved",
    "total_score": 92.0
  },
  {
    "id": "4acffc54-0945-46b6-86cc-8193d1613b2a",
    "character_slug": "reginald",
    "status": "approved",
    "total_score": 88.0
  },
  {
    "id": "522e81cf-5057-4a84-84dd-4817581281cd",
    "character_slug": "biscuit",
    "status": "approved",
    "total_score": 85.0
  },
  {
    "id": "83da6efa-1200-42cf-908d-33a62e3a7ea4",
    "character_slug": "biscuit",
    "status": "approved",
    "total_score": 80.0
  },
  {
    "id": "4ea3467f-bc63-45af-91fe-a3af289d6c2a",
    "character_slug": "biscuit",
[... 235 more lines]
```

Biscuit's first pick: `he hits every single beat` (https://www.tiktok.com/@tillandsialover/video/7688386199270001953), status `approved`.

Stand-in for vidIQ `watch_shortform_content` (10 credits): a fixture breakdown.

`$ bin/studio fav mark 522e81cf-5057-4a84-84dd-4817581281cd --status analysed --breakdown FIXTURE breakdown. 0-2 s: static medium shot, kitchen at night. 2-8 s: upright paw hits on every snare. 8-10 s: final hit, hold. Camera static. Hook text top-centre. Audio: beat only.`  (selected fields)
exit 0
```json
{
  "id": "522e81cf-5057-4a84-84dd-4817581281cd",
  "status": "analysed",
  "breakdown_md": "FIXTURE breakdown. 0-2 s: static medium shot, kitchen at night. 2-8 s: upright paw hits on every snare. 8-10 s: final hit, hold. Camera static. Hook text top-centre. Audio: beat only."
}
```
`$ bin/studio source list --rank --character biscuit --mode dropin`  (no clean source: Recreate)
exit 0
```json
[]
```
`$ bin/studio source list --rank --character biscuit --mode recreate`  (empty: a pick in Recreate gets a synthetic driver anyway)
exit 0
```json
[]
```

## 4. Assets (Higgsfield is an MCP call: replaced by fixtures)

`budget status` guard before any spend:

`$ bin/studio budget status`
exit 0
```json
{
  "month": "2026-10",
  "cap": 6000,
  "committed": 0,
  "settled": 0,
  "reserved": 0,
  "remaining": 6000,
  "kill_switch": false
}
```

Round A (scene still + Seedance driver) is skipped here: no credits, no MCP. The driver job id below is a placeholder.

`$ bin/studio source add --kind synthetic --url higgsfield-job:00000000-0000-0000-0000-0000000000d1 --body biped --bodies 1 --duration 10`  (selected fields)
exit 0
```json
{
  "id": "f7431ba7-69fa-490b-b6cd-66eedae6cd9e",
  "kind": "synthetic",
  "url": "higgsfield-job:00000000-0000-0000-0000-0000000000d1",
  "body": "biped",
  "bodies": 1,
  "dropin_eligible": false
}
```

## 5. Create and reserve

`$ bin/studio clip new --character biscuit --mode recreate --source f7431ba7-69fa-490b-b6cd-66eedae6cd9e --features {"format_id": "B3", "hook_pattern": "gesture-routine", "hook_text": "he hits every single beat", "prop": "gold chain", "setting": "kitchen at night", "motion_type": "gesture", "audio_arm": "own_beat", "bodies_in_frame": 1, "seamless_loop": true, "eye_closeup_end": true, "trend_name": "evergreen", "fav_id": "522e81cf-5057-4a84-84dd-4817581281cd"}`  (selected fields)
exit 0
```json
{
  "id": "5c06b623-6a4c-4e7f-963f-a4d64193b29e",
  "state": "planned",
  "mode": "recreate",
  "source_id": "f7431ba7-69fa-490b-b6cd-66eedae6cd9e",
  "hf_job_id": null,
  "credits_reserved": 0,
  "credits_actual": null,
  "master_path": null,
  "hook": null,
  "caption": null,
  "hashtags": []
}
```
`$ bin/studio fav mark 522e81cf-5057-4a84-84dd-4817581281cd --status queued --clip 5c06b623-6a4c-4e7f-963f-a4d64193b29e`  (selected fields)
exit 0
```json
{
  "id": "522e81cf-5057-4a84-84dd-4817581281cd",
  "character_slug": "biscuit",
  "status": "queued",
  "total_score": 85.0,
  "clip_id": "5c06b623-6a4c-4e7f-963f-a4d64193b29e"
}
```
`$ bin/studio budget status`
exit 0
```json
{
  "month": "2026-10",
  "cap": 6000,
  "committed": 0,
  "settled": 0,
  "reserved": 0,
  "remaining": 6000,
  "kill_switch": false
}
```
`$ bin/studio budget reserve 160 --clip 5c06b623-6a4c-4e7f-963f-a4d64193b29e`  (est_credits from the plan)
exit 0
```json
{
  "id": "ec0d9d8b-3e97-47b6-8046-c1a56ad912b5",
  "clip_id": "5c06b623-6a4c-4e7f-963f-a4d64193b29e",
  "month": "2026-10",
  "kind": "reserve",
  "credits": 160,
  "created_at": "2026-10-06T08:00:00+01:00"
}
```
`$ bin/studio clip set 5c06b623-6a4c-4e7f-963f-a4d64193b29e --state generating --credits-reserved 160`  (selected fields)
exit 0
```json
{
  "id": "5c06b623-6a4c-4e7f-963f-a4d64193b29e",
  "state": "generating",
  "mode": "recreate",
  "source_id": "f7431ba7-69fa-490b-b6cd-66eedae6cd9e",
  "hf_job_id": null,
  "credits_reserved": 160,
  "credits_actual": null,
  "master_path": null,
  "hook": null,
  "caption": null,
  "hashtags": []
}
```

## 6. Genjutsu (MCP stand-in: a local synthetic clip)

`gen.mp4` is a 10 s 1080x1920 test pattern with a sine tone (stands in for the Genjutsu render).

`$ bin/studio budget settle 5c06b623-6a4c-4e7f-963f-a4d64193b29e 181`  (actual = driver 70 + still 1 + Genjutsu 110, from get_cost preflights)
exit 0
```json
{
  "id": "dd2093c5-773f-4d74-9d20-cba28ff070a2",
  "clip_id": "5c06b623-6a4c-4e7f-963f-a4d64193b29e",
  "month": "2026-10",
  "kind": "settle",
  "credits": 181,
  "created_at": "2026-10-06T08:00:00.000001+01:00"
}
```
`$ bin/studio clip set 5c06b623-6a4c-4e7f-963f-a4d64193b29e --state generated --hf-job-id 00000000-0000-0000-0000-0000000000a1 --credits-actual 181`  (selected fields)
exit 0
```json
{
  "id": "5c06b623-6a4c-4e7f-963f-a4d64193b29e",
  "state": "generated",
  "mode": "recreate",
  "source_id": "f7431ba7-69fa-490b-b6cd-66eedae6cd9e",
  "hf_job_id": "00000000-0000-0000-0000-0000000000a1",
  "credits_reserved": 160,
  "credits_actual": 181,
  "master_path": null,
  "hook": null,
  "caption": null,
  "hashtags": []
}
```

## 7. QA

`$ bin/studio qa tech $WORK/renders/5c06b623-6a4c-4e7f-963f-a4d64193b29e/gen.mp4`  (selected fields)
exit 0
```json
{
  "width": 1080,
  "height": 1920,
  "fps": 30.0,
  "duration_s": 10.0,
  "has_audio": true,
  "problems": [],
  "ok": true
}
```
`$ bin/studio qa frames $WORK/renders/5c06b623-6a4c-4e7f-963f-a4d64193b29e/gen.mp4 --out $WORK/renders/5c06b623-6a4c-4e7f-963f-a4d64193b29e/frames.jpg --n 6`
exit 0
```json
{
  "out": "$WORK/renders/5c06b623-6a4c-4e7f-963f-a4d64193b29e/frames.jpg",
  "frames": 6,
  "frame_width": 270,
  "sheet_width": 1620
}
```

Visual QA (ODD EYES sides, outfit, hands, leakage) needs a real render: not applicable to a test pattern.

`$ bin/studio clip set 5c06b623-6a4c-4e7f-963f-a4d64193b29e --state qa_passed --qa {"tech": "ok", "visual": "n/a (dry rehearsal)"}`  (selected fields)
exit 0
```json
{
  "id": "5c06b623-6a4c-4e7f-963f-a4d64193b29e",
  "state": "qa_passed",
  "mode": "recreate",
  "source_id": "f7431ba7-69fa-490b-b6cd-66eedae6cd9e",
  "hf_job_id": "00000000-0000-0000-0000-0000000000a1",
  "credits_reserved": 160,
  "credits_actual": 181,
  "master_path": null,
  "hook": null,
  "caption": null,
  "hashtags": []
}
```

## 8. Master and queue

A placeholder PNG stands in for the Biscuit close-up (the real one is a Higgsfield job image). Spec, with `slowmo` placed late (near the end beat, at 8.0 s of 10 s):
```json
{"dance": "$WORK/renders/5c06b623-6a4c-4e7f-963f-a4d64193b29e/gen.mp4", "closeup": "$WORK/renders/closeups/biscuit.png", "closeup_center": [536, 732], "blue_eye_xy": [301, 960], "hook1": ["he hits every", "single beat"], "hook2": ["find one he missed."], "hook2_until_s": 4.0, "audio": "$WORK/renders/5c06b623-6a4c-4e7f-963f-a4d64193b29e/gen.mp4", "audio_offset_s": 0, "out": "$WORK/renders/5c06b623-6a4c-4e7f-963f-a4d64193b29e/master.mp4", "preset": "veryfast", "enhancements": [{"type": "zoom_hit", "at_s": 3.0}, {"type": "slowmo", "at_s": 8.0, "dur_s": 1.0, "factor": 0.5}]}
```

`$ bin/studio master build --spec $WORK/renders/5c06b623-6a4c-4e7f-963f-a4d64193b29e/spec.json`  (selected fields)
exit 0
```json
{
  "width": 1080,
  "height": 1920,
  "fps": 30.0,
  "duration_s": 12.5,
  "lufs": -13.9,
  "true_peak": -1.5,
  "video_profile": "High",
  "problems": [],
  "ok": true
}
```
`$ bin/studio master upload 5c06b623-6a4c-4e7f-963f-a4d64193b29e $WORK/renders/5c06b623-6a4c-4e7f-963f-a4d64193b29e/master.mp4`
exit 0
```json
{
  "clip": "5c06b623-6a4c-4e7f-963f-a4d64193b29e",
  "master_path": "biscuit/5c06b623-6a4c-4e7f-963f-a4d64193b29e.mp4",
  "bucket": "clips"
}
```
`$ bin/studio clip set 5c06b623-6a4c-4e7f-963f-a4d64193b29e --state mastered --hook he hits every single beat --caption tracksuit on. worries off. 💙 --hashtag #dachshund --hashtag #dancingdog`  (selected fields)
exit 0
```json
{
  "id": "5c06b623-6a4c-4e7f-963f-a4d64193b29e",
  "state": "mastered",
  "mode": "recreate",
  "source_id": "f7431ba7-69fa-490b-b6cd-66eedae6cd9e",
  "hf_job_id": "00000000-0000-0000-0000-0000000000a1",
  "credits_reserved": 160,
  "credits_actual": 181,
  "master_path": "biscuit/5c06b623-6a4c-4e7f-963f-a4d64193b29e.mp4",
  "hook": "he hits every single beat",
  "caption": "tracksuit on. worries off. 💙",
  "hashtags": [
    "#dachshund",
    "#dancingdog"
  ]
}
```
`$ bin/studio clip set 5c06b623-6a4c-4e7f-963f-a4d64193b29e --state awaiting_approval`  (selected fields)
exit 0
```json
{
  "id": "5c06b623-6a4c-4e7f-963f-a4d64193b29e",
  "state": "awaiting_approval",
  "mode": "recreate",
  "source_id": "f7431ba7-69fa-490b-b6cd-66eedae6cd9e",
  "hf_job_id": "00000000-0000-0000-0000-0000000000a1",
  "credits_reserved": 160,
  "credits_actual": 181,
  "master_path": "biscuit/5c06b623-6a4c-4e7f-963f-a4d64193b29e.mp4",
  "hook": "he hits every single beat",
  "caption": "tracksuit on. worries off. 💙",
  "hashtags": [
    "#dachshund",
    "#dancingdog"
  ]
}
```
`$ bin/studio fav mark 522e81cf-5057-4a84-84dd-4817581281cd --status made`  (selected fields)
exit 0
```json
{
  "id": "522e81cf-5057-4a84-84dd-4817581281cd",
  "character_slug": "biscuit",
  "status": "made",
  "total_score": 85.0,
  "clip_id": "5c06b623-6a4c-4e7f-963f-a4d64193b29e"
}
```

An out-of-order move is refused by the state machine (re-roll rule and table both live in code):

`$ bin/studio clip set 5c06b623-6a4c-4e7f-963f-a4d64193b29e --state generating`
exit 2
```
error: clip 5c06b623-6a4c-4e7f-963f-a4d64193b29e: awaiting_approval -> generating is not allowed (from awaiting_approval: approved, rejected)
```

## 9. Log

`$ bin/studio run log --kind daily --status ok --summary dry rehearsal`  (Task 14 implements it; referenced as-is by the skill)
exit 2
```
Usage: studio [OPTIONS] COMMAND [ARGS]...
Try 'studio --help' for help.
╭─ Error ──────────────────────────────────────────────────────────────────────╮
│ No such command 'run'.                                                       │
╰──────────────────────────────────────────────────────────────────────────────╯
```
`$ bin/studio budget status`  (ledger after the run)
exit 0
```json
{
  "month": "2026-10",
  "cap": 6000,
  "committed": 181,
  "settled": 181,
  "reserved": 0,
  "remaining": 5819,
  "kill_switch": false
}
```

## Weekly review sequence (same harness)

`$ bin/studio metrics pull`  (needs POSTIZ_API_KEY and the postiz binary (MemoryStore run has neither))
exit 2
```
error: POSTIZ_API_KEY is not set. Run through bin/studio (Keychain item cs-postiz-api-key).
```
`$ bin/studio metrics ingest-ig []`  (no vidIQ rows in a dry run)
exit 0
```json
{
  "ingested": [],
  "unchanged": [],
  "unmatched": [],
  "empty": [],
  "skipped": 0,
  "outlier_x": []
}
```
`$ bin/studio review data`
exit 0
```json
{
  "as_of": "2026-10-06T08:00:00+01:00",
  "bars": {
    "hit_outlier_x": 3,
    "format": {
      "keep_median": 1.5,
[... 144 more lines]
```
`$ bin/studio review save --week 2026-10-05 --character biscuit --bar-status not_yet --report-file x.md`  (not implemented yet)
exit 2
```
Usage: studio review [OPTIONS] COMMAND [ARGS]...
Try 'studio review --help' for help.
╭─ Error ──────────────────────────────────────────────────────────────────────╮
│ No such command 'save'.                                                      │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## Findings

Fixed in this task (found while writing the skill or the rehearsal):

1. **`master build` only rendered locally**: nothing uploaded the master or set `clip.master_path`, so no clip could reach the
   queue or be published. Added `studio master upload <clip> <file> [--loop]`: re-checks the file against the master spec, uploads
   to bucket `clips` at `<character>/<clip id>.mp4` (what publishing signs), sets `master_path`.
2. **A misspelt `proposal.needs` auto-approved a blocked pick** (fail-open): `fav pick` / `add_pick` now reject anything but
   `multi_body` / `talking_lane` (shown above: exit 2).
3. `budget reserve|settle` write the ledger only, so `clip.credits_reserved` / `credits_actual` stayed 0 / null. The skill now sets
   them with `clip set --credits-reserved` / `--credits-actual`.

Open, not fixed here (each needs a decision or belongs to a later task):

1. **`bin/studio run log` (Task 14) and `bin/studio review save` do not exist.** The skills call both as specified. Nothing writes
   the `reviews` table yet; suggest adding `review save` next to `run log` (both need a Store method for their table).
2. **No CLI creates `posts`**, so a clip can only wait in `awaiting_approval` for the terminal's `approve_clip` RPC (Task 15).
   The skill stops there for every account, `auto` included; the brief's "scheduled if the account is auto" needs a post-creating command first.
3. **`clip.source_id` is fixed at creation**, so a synthetic driver has to be rendered, and `source add`-ed, *before* `clip new`
   and `budget reserve` (which needs the clip id). The skill guards the spend with `budget status` first (`kill_switch`, `remaining`
   against the plan's `estimated`) and `budget settle` books the driver's credits afterwards. A run that dies between the driver and the
   reserve leaves those credits unbooked; the run summary compares the ledger with `balance`.
4. **No CLI hands an `owner_inbox` source (a bucket path) to Higgsfield** (no signed-URL command), so Drop-in from the inbox cannot
   run yet; the skill takes the next row.
5. Skipped by design: visual QA of a real render (ODD EYES sides, outfit, hands, leakage), the MCP calls, the Genjutsu `preset`
   suggestion path, `jobs_wait` URL -> `curl`, the `jobs_wait` call with `timeout_seconds: 0` for resolving the close-up job id.
   All of these are Task 16.
6. As shipped, both characters are `designing`, so a scheduled `/daily-run` does nothing but log. Go-live = set `status: "live"` and the
   handles / Postiz ids in refs.json, then `bin/studio seed`. Reginald's `closeup` is null until the rehearsal generates it; the skill
   skips him until then. After the owner's top-up, D2 ("Biscuit #2, after the debut") would be produced before the planned debut under
   "picks first" unless the debut clip already exists: make the Task 16 debut re-render the first clip.
