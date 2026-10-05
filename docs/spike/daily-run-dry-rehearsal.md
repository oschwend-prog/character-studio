# Daily-run dry rehearsal (Task 13, redone in fix round 1)

The `/daily-run` command sequence of `.claude/skills/daily-run/SKILL.md`, run through the real `studio` CLI against a
`MemoryStore` (every module's `open_store` patched; `master upload` writes to a `LocalStorage` folder). **No MCP call and no
Higgsfield credit was used.** The real rehearsal (Genjutsu renders, ~260 credits) is Task 16.

What is real and what is a stand-in:

| Real | Stand-in (labelled where it appears) |
|---|---|
| every `bin/studio` command, its JSON and exit code; the state machine; the budget ledger; `qa tech` / `qa frames` / `master build` / `master upload` | vidIQ scan and breakdown (a fixture row and a fixture breakdown), the `get_cost` preflights (numbers from the spike), Higgsfield stills / drivers / Genjutsu (a `testsrc2` clip with a sine tone), the close-up (a flat PNG), `humanizer`, `last30days`, `curl` downloads, the agent's Write tool (the harness writes the text files) |
| the 17 batch-1 picks loaded from `docs/launch/viral-picks-2026-10-04.md` | fake handles and Postiz ids in a *rehearsal copy* of refs.json (status `live`), fixture URLs `@rehearsal.fixture` |

The real clock is Mon 5 Oct 2026 (nothing is due on a Monday), so the clock of `plan`, `budget` and `review` is pinned to
Tue 6 Oct 2026 08:00 London. Paths are shortened to `$WORK`. Long outputs are cut or reduced to the fields that matter
(marked "selected fields"). An output marked `(EXPECTED n)` would flag a surprise; there are none. Free text (proposal, breakdown,
reason, features, hook, caption, qa, note) always goes through a `--*-file` option, never inline.

## Result

The whole chain `scan -> plan -> pick -> clip new -> preflight -> reserve -> (assets) -> source link -> generating -> settle ->
qa -> master -> upload -> awaiting_approval -> fav made` runs end to end on the real code, in the order the skill now prescribes: the
clip exists and its credits are reserved *before* any paid job, and a synthetic driver's source is linked afterwards while the clip is
still `planned`. The ledger ends at 181 settled (the reservation of 191 replaced by the actual); `clip.credits_reserved` /
`credits_actual` carry 191 / 181. A second clip shows the crash recovery (planned, open reservation, over 2 h old: released, dropped,
its pick back to `approved`). Gaps the rehearsal exposed are listed at the end.


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

Skill step 3.2 therefore drops every due clip (no character is `live`) and goes straight to the run log. Everything below uses a *rehearsal copy* of the refs: status `live`, fake handles and fake Postiz ids, in a MemoryStore only.

## 1. Orient and recover

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

Crash recovery finds nothing on a fresh store:

`$ bin/studio clip list --state generating`
exit 0
```json
[]
```
`$ bin/studio clip list --state planned`
exit 0
```json
[]
```
`$ bin/studio fav list --status queued`
exit 0
```json
[]
```

## 2. Scan (before the plan; vidIQ is an MCP call: replaced by a fixture row)

Tue 2026-10-06 is ISO week 41: slot = 4*41 + 0 = 164; two live characters sorted by slug (biscuit, reginald): character = 164 mod 2 = 0 -> biscuit, query = rotation[(164 div 2) mod 4] = rotation[2]. Over two weeks both characters reach all four queries (even weeks 0,1 / odd weeks 2,3 for each).
`excludeContentIds` comes from `fav seen` (newest 100 ids, newest first):

`$ bin/studio fav seen --limit 100`
exit 0
```json
[
  "DcWMn6QOckQ",
  "Dc_RQsIMoxO",
  "7671329075935415574",
  "7669427457178488086",
  "7671687450737118478",
  "7676630835327405326",
  "DdtbbsNrvu",
  "Dc1ZM7LIKMg",
  "Dc_OfoQIii5",
[... 9 more lines]
```

The outlier below is a FIXTURE, not a real video; it stands in for one vidIQ result. The proposal goes through a file (`renders/tmp/p.json`), never inline.

`$ bin/studio fav pick --url https://www.tiktok.com/@rehearsal.fixture/video/1000000000000000001 --platform tiktok --views 900000 --outlier-x 40 --creator @rehearsal.fixture --character biscuit --proposal-file $WORK/renders/tmp/p.json --freshness 7 --fit 8 --feasibility 8 --saturation 6`  (fixture outlier, analyst band; selected fields)
exit 0
```json
{
  "id": "34302653-78b0-491d-92d1-181bb22056fd",
  "character_slug": "biscuit",
  "status": "new",
  "proposal": {
    "mode": "recreate",
    "hook": "fixture hook; it's \"quoted\" $(nope)",
    "prop": "shades",
    "concept": "fixture concept"
  },
  "total_score": 65.0
}
```
`$ bin/studio fav decide 34302653-78b0-491d-92d1-181bb22056fd`  (the standing rule)
exit 4
```json
{
  "ok": false,
  "needs": "analyst",
  "id": "34302653-78b0-491d-92d1-181bb22056fd",
  "total_score": 65.0,
  "feasibility": 8.0,
  "message": "favourite 34302653-78b0-491d-92d1-181bb22056fd needs an analyst decision (total 65.0, feasibility 8.0) - rerun with --decision approve|skip --reason '...' --by analyst"
}
```
`$ bin/studio fav decide 34302653-78b0-491d-92d1-181bb22056fd --decision skip --reason-file $WORK/renders/tmp/reason.txt --by analyst`  (exit 4 -> analyst decides, reason from a file; selected fields)
exit 0
```json
{
  "id": "34302653-78b0-491d-92d1-181bb22056fd",
  "status": "skipped",
  "proposal": {
    "mode": "recreate",
    "hook": "fixture hook; it's \"quoted\" $(nope)",
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
`$ bin/studio fav pick --url https://www.tiktok.com/@rehearsal.fixture/video/1000000000000000002 --platform tiktok --views 500000 --outlier-x 12 --character biscuit --proposal-file $WORK/renders/tmp/bad.json --freshness 7 --fit 8 --feasibility 8 --saturation 6`  (a misspelt needs is refused at the door)
exit 2
```
error: proposal.needs must be one of or a list of {multi_body, talking_lane}, got 'multi-body'
```

## 3. Plan

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

Skill 3.2: Reginald's refs.json has `closeup: null` (generated in the Task 16 rehearsal), so his clip is dropped; only Biscuit continues.
`$ bin/studio clip list --character biscuit`  (step 3.3: nothing planned yet, EXCLUDE = {})
exit 0
```json
[]
```

## 4. Concept

`$ bin/studio fav list --next 1 --character biscuit`  (her own queue: every character gets its pick; selected fields)
exit 0
```json
[
  {
    "id": "8979b533-4fd9-473e-a130-af799f2e47c4",
    "character_slug": "biscuit",
    "status": "approved",
    "total_score": 85.0
  }
]
```
`$ bin/studio fav list --next 1 --character reginald`  (selected fields)
exit 0
```json
[
  {
    "id": "bd1fba0c-df3f-4c2f-a4a5-b46451b4d329",
    "character_slug": "reginald",
    "status": "approved",
    "total_score": 92.0
  }
]
```

Stand-in for vidIQ `watch_shortform_content` (10 credits): a fixture breakdown, passed through a file.

`$ bin/studio fav mark 8979b533-4fd9-473e-a130-af799f2e47c4 --status analysed --breakdown-file $WORK/renders/tmp/b.md`  (selected fields)
exit 0
```json
{
  "id": "8979b533-4fd9-473e-a130-af799f2e47c4",
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

## 5. Create, preflight, reserve

`$ bin/studio clip new --character biscuit --mode recreate --features-file $WORK/renders/tmp/f.json`  (planned, no source yet (a synthetic driver does not exist); selected fields)
exit 0
```json
{
  "id": "3317f5ad-1f89-4e4f-89c0-28a6daf4f5d6",
  "state": "planned",
  "mode": "recreate",
  "source_id": null,
  "hf_job_id": null,
  "credits_reserved": 0,
  "credits_actual": null,
  "master_path": null,
  "hook": null,
  "caption": null,
  "hashtags": []
}
```
`$ bin/studio fav mark 8979b533-4fd9-473e-a130-af799f2e47c4 --status queued --clip 3317f5ad-1f89-4e4f-89c0-28a6daf4f5d6`  (selected fields)
exit 0
```json
{
  "id": "8979b533-4fd9-473e-a130-af799f2e47c4",
  "character_slug": "biscuit",
  "status": "queued",
  "total_score": 85.0,
  "clip_id": "3317f5ad-1f89-4e4f-89c0-28a6daf4f5d6",
  "note": null
}
```

Preflight (`get_cost: true`, an MCP call: stand-in numbers from the spike): scene still 1 + Seedance driver 70 + Genjutsu estimated 12 credits x 10 s = 120. Sum P = 191; the plan estimate for Recreate is 160, so the reserve is max(160, 191) = 191.

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
`$ bin/studio budget reserve 191 --clip 3317f5ad-1f89-4e4f-89c0-28a6daf4f5d6`  (max(plan estimate for the ACTUAL mode, preflight sum))
exit 0
```json
{
  "id": "ce8624e7-2e21-492d-9287-2a52a2b22d80",
  "clip_id": "3317f5ad-1f89-4e4f-89c0-28a6daf4f5d6",
  "month": "2026-10",
  "kind": "reserve",
  "credits": 191,
  "created_at": "2026-10-06T08:00:00+01:00"
}
```
`$ bin/studio clip set 3317f5ad-1f89-4e4f-89c0-28a6daf4f5d6 --credits-reserved 191`  (selected fields)
exit 0
```json
{
  "id": "3317f5ad-1f89-4e4f-89c0-28a6daf4f5d6",
  "state": "planned",
  "mode": "recreate",
  "source_id": null,
  "hf_job_id": null,
  "credits_reserved": 191,
  "credits_actual": null,
  "master_path": null,
  "hook": null,
  "caption": null,
  "hashtags": []
}
```

## 6. Assets (Higgsfield is an MCP call: replaced by fixtures)

Round A (scene still, Seedance driver) is skipped: no MCP, no credits. The driver job id is a placeholder. The clip is still `planned` and holds an open reservation, so the source can be linked now:

`$ bin/studio source add --kind synthetic --url higgsfield-job:00000000-0000-0000-0000-0000000000d1 --body biped --bodies 1 --duration 10`  (selected fields)
exit 0
```json
{
  "id": "feb0193d-ea0d-4890-9ca2-58ed4b61a0a8",
  "kind": "synthetic",
  "url": "higgsfield-job:00000000-0000-0000-0000-0000000000d1",
  "body": "biped",
  "bodies": 1,
  "dropin_eligible": false
}
```
`$ bin/studio clip set 3317f5ad-1f89-4e4f-89c0-28a6daf4f5d6 --source-id feb0193d-ea0d-4890-9ca2-58ed4b61a0a8`  (selected fields)
exit 0
```json
{
  "id": "3317f5ad-1f89-4e4f-89c0-28a6daf4f5d6",
  "state": "planned",
  "mode": "recreate",
  "source_id": "feb0193d-ea0d-4890-9ca2-58ed4b61a0a8",
  "hf_job_id": null,
  "credits_reserved": 191,
  "credits_actual": null,
  "master_path": null,
  "hook": null,
  "caption": null,
  "hashtags": []
}
```

## 7. Genjutsu (MCP stand-in: a local synthetic clip)

Exact preflight now that the driver exists: Genjutsu 110 + still 1 + driver 70 = 181 <= 191 reserved: no top-up.

`$ bin/studio clip set 3317f5ad-1f89-4e4f-89c0-28a6daf4f5d6 --state generating`  (selected fields)
exit 0
```json
{
  "id": "3317f5ad-1f89-4e4f-89c0-28a6daf4f5d6",
  "state": "generating",
  "mode": "recreate",
  "source_id": "feb0193d-ea0d-4890-9ca2-58ed4b61a0a8",
  "hf_job_id": null,
  "credits_reserved": 191,
  "credits_actual": null,
  "master_path": null,
  "hook": null,
  "caption": null,
  "hashtags": []
}
```
`$ bin/studio clip set 3317f5ad-1f89-4e4f-89c0-28a6daf4f5d6 --source-id feb0193d-ea0d-4890-9ca2-58ed4b61a0a8`  (the source is fixed again once the clip left planned)
exit 2
```
error: the source can only change while the clip is planned (clip 3317f5ad-1f89-4e4f-89c0-28a6daf4f5d6 is generating)
```

`gen.mp4` is a 10 s 1080x1920 test pattern with a sine tone (stands in for the Genjutsu render).

`$ bin/studio budget settle 3317f5ad-1f89-4e4f-89c0-28a6daf4f5d6 181`  (the summed actual of ALL the clip's jobs)
exit 0
```json
{
  "id": "2f52ca0c-ddde-4d88-80b7-a0f892f49da4",
  "clip_id": "3317f5ad-1f89-4e4f-89c0-28a6daf4f5d6",
  "month": "2026-10",
  "kind": "settle",
  "credits": 181,
  "created_at": "2026-10-06T08:00:00.000001+01:00"
}
```
`$ bin/studio clip set 3317f5ad-1f89-4e4f-89c0-28a6daf4f5d6 --state generated --hf-job-id 00000000-0000-0000-0000-0000000000a1 --credits-actual 181`  (selected fields)
exit 0
```json
{
  "id": "3317f5ad-1f89-4e4f-89c0-28a6daf4f5d6",
  "state": "generated",
  "mode": "recreate",
  "source_id": "feb0193d-ea0d-4890-9ca2-58ed4b61a0a8",
  "hf_job_id": "00000000-0000-0000-0000-0000000000a1",
  "credits_reserved": 191,
  "credits_actual": 181,
  "master_path": null,
  "hook": null,
  "caption": null,
  "hashtags": []
}
```

## 8. QA

`$ bin/studio qa tech $WORK/renders/3317f5ad-1f89-4e4f-89c0-28a6daf4f5d6/gen.mp4`  (selected fields)
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
`$ bin/studio qa frames $WORK/renders/3317f5ad-1f89-4e4f-89c0-28a6daf4f5d6/gen.mp4 --out $WORK/renders/3317f5ad-1f89-4e4f-89c0-28a6daf4f5d6/frames.jpg --n 6`
exit 0
```json
{
  "out": "$WORK/renders/3317f5ad-1f89-4e4f-89c0-28a6daf4f5d6/frames.jpg",
  "frames": 6,
  "frame_width": 270,
  "sheet_width": 1620
}
```

Visual QA (ODD EYES sides, outfit, hands, leakage) needs a real render: not applicable to a test pattern. The QA record is a file:

`$ bin/studio clip set 3317f5ad-1f89-4e4f-89c0-28a6daf4f5d6 --state qa_passed --qa-file $WORK/renders/tmp/qa.json`  (selected fields)
exit 0
```json
{
  "id": "3317f5ad-1f89-4e4f-89c0-28a6daf4f5d6",
  "state": "qa_passed",
  "mode": "recreate",
  "source_id": "feb0193d-ea0d-4890-9ca2-58ed4b61a0a8",
  "hf_job_id": "00000000-0000-0000-0000-0000000000a1",
  "credits_reserved": 191,
  "credits_actual": 181,
  "master_path": null,
  "hook": null,
  "caption": null,
  "hashtags": [],
  "qa": {
    "tech": "ok",
    "problems": [],
    "visual": "n/a (dry rehearsal)"
  }
}
```

## 9. Master and queue

A placeholder PNG stands in for the Biscuit close-up (the real one is a Higgsfield job image). Spec, with `slowmo` placed late (near the end beat, at 8.0 s of 10 s):
```json
{"dance": "$WORK/renders/3317f5ad-1f89-4e4f-89c0-28a6daf4f5d6/gen.mp4", "closeup": "$WORK/renders/closeups/biscuit.png", "closeup_center": [536, 732], "blue_eye_xy": [301, 960], "hook1": ["he hits every", "single beat"], "hook2": ["find one he missed."], "hook2_until_s": 4.0, "audio": "$WORK/renders/3317f5ad-1f89-4e4f-89c0-28a6daf4f5d6/gen.mp4", "audio_offset_s": 0, "out": "$WORK/renders/3317f5ad-1f89-4e4f-89c0-28a6daf4f5d6/master.mp4", "preset": "veryfast", "enhancements": [{"type": "zoom_hit", "at_s": 3.0}, {"type": "slowmo", "at_s": 8.0, "dur_s": 1.0, "factor": 0.5}]}
```

`$ bin/studio master build --spec $WORK/renders/3317f5ad-1f89-4e4f-89c0-28a6daf4f5d6/spec.json`  (selected fields)
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
`$ bin/studio master upload 3317f5ad-1f89-4e4f-89c0-28a6daf4f5d6 $WORK/renders/3317f5ad-1f89-4e4f-89c0-28a6daf4f5d6/master.mp4`
exit 0
```json
{
  "clip": "3317f5ad-1f89-4e4f-89c0-28a6daf4f5d6",
  "master_path": "biscuit/3317f5ad-1f89-4e4f-89c0-28a6daf4f5d6.mp4",
  "bucket": "clips"
}
```
`$ bin/studio clip set 3317f5ad-1f89-4e4f-89c0-28a6daf4f5d6 --state mastered --hook-file $WORK/renders/tmp/hook.txt --caption-file $WORK/renders/tmp/caption.txt --hashtag #dachshund --hashtag #dancingdog`  (selected fields)
exit 0
```json
{
  "id": "3317f5ad-1f89-4e4f-89c0-28a6daf4f5d6",
  "state": "mastered",
  "mode": "recreate",
  "source_id": "feb0193d-ea0d-4890-9ca2-58ed4b61a0a8",
  "hf_job_id": "00000000-0000-0000-0000-0000000000a1",
  "credits_reserved": 191,
  "credits_actual": 181,
  "master_path": "biscuit/3317f5ad-1f89-4e4f-89c0-28a6daf4f5d6.mp4",
  "hook": "he hits every single beat",
  "caption": "tracksuit on. worries off. 💙",
  "hashtags": [
    "#dachshund",
    "#dancingdog"
  ]
}
```
`$ bin/studio clip set 3317f5ad-1f89-4e4f-89c0-28a6daf4f5d6 --state awaiting_approval`  (selected fields)
exit 0
```json
{
  "id": "3317f5ad-1f89-4e4f-89c0-28a6daf4f5d6",
  "state": "awaiting_approval",
  "mode": "recreate",
  "source_id": "feb0193d-ea0d-4890-9ca2-58ed4b61a0a8",
  "hf_job_id": "00000000-0000-0000-0000-0000000000a1",
  "credits_reserved": 191,
  "credits_actual": 181,
  "master_path": "biscuit/3317f5ad-1f89-4e4f-89c0-28a6daf4f5d6.mp4",
  "hook": "he hits every single beat",
  "caption": "tracksuit on. worries off. 💙",
  "hashtags": [
    "#dachshund",
    "#dancingdog"
  ]
}
```
`$ bin/studio fav mark 8979b533-4fd9-473e-a130-af799f2e47c4 --status made`  (selected fields)
exit 0
```json
{
  "id": "8979b533-4fd9-473e-a130-af799f2e47c4",
  "character_slug": "biscuit",
  "status": "made",
  "total_score": 85.0,
  "clip_id": "3317f5ad-1f89-4e4f-89c0-28a6daf4f5d6",
  "note": null
}
```

## Crash recovery (a second clip whose run died)

A second Biscuit pick is queued, its clip created and reserved, then the run 'dies' in Round A (planned, open reservation). Three hours later (the clip's `created_at` is moved back: stand-in for the clock) the next run's step 1 cleans up:

`$ bin/studio fav list --next 1 --character biscuit`  (selected fields)
exit 0
```json
[
  {
    "id": "48381ba8-7b00-479e-b617-59b6e6521d1f",
    "character_slug": "biscuit",
    "status": "approved"
  }
]
```
`$ bin/studio clip new --character biscuit --mode recreate --features-file $WORK/renders/tmp/f2.json`  (selected fields)
exit 0
```json
{
  "id": "33ae00b4-1e2b-414f-96f3-bea149a6b075",
  "state": "planned"
}
```
`$ bin/studio fav mark 48381ba8-7b00-479e-b617-59b6e6521d1f --status queued --clip 33ae00b4-1e2b-414f-96f3-bea149a6b075`  (selected fields)
exit 0
```json
{
  "id": "48381ba8-7b00-479e-b617-59b6e6521d1f",
  "character_slug": "biscuit",
  "status": "queued",
  "total_score": 80.0,
  "clip_id": "33ae00b4-1e2b-414f-96f3-bea149a6b075",
  "note": null
}
```
`$ bin/studio budget reserve 160 --clip 33ae00b4-1e2b-414f-96f3-bea149a6b075`
exit 0
```json
{
  "id": "0a9090d9-6c21-4a98-9fcb-ddd44162316e",
  "clip_id": "33ae00b4-1e2b-414f-96f3-bea149a6b075",
  "month": "2026-10",
  "kind": "reserve",
  "credits": 160,
  "created_at": "2026-10-06T08:00:00+01:00"
}
```
`$ bin/studio clip set 33ae00b4-1e2b-414f-96f3-bea149a6b075 --credits-reserved 160`  (selected fields)
exit 0
```json
{
  "id": "33ae00b4-1e2b-414f-96f3-bea149a6b075",
  "state": "planned",
  "credits_reserved": 160
}
```
`$ bin/studio budget status`  (160 reserved by the dead clip is part of `committed`)
exit 0
```json
{
  "month": "2026-10",
  "cap": 6000,
  "committed": 341,
  "settled": 181,
  "reserved": 160,
  "remaining": 5659,
  "kill_switch": false
}
```
`$ bin/studio clip list --state planned`  (step 1.2: created over 2 h ago, credits_reserved > 0; selected fields)
exit 0
```json
[
  {
    "id": "33ae00b4-1e2b-414f-96f3-bea149a6b075",
    "state": "planned",
    "credits_reserved": 160,
    "created_at": "2026-10-06T05:00:00+01:00"
  }
]
```
`$ bin/studio budget release 33ae00b4-1e2b-414f-96f3-bea149a6b075`
exit 0
```json
{
  "id": "2ed8f1ac-a785-4921-a7e3-5418f1088508",
  "clip_id": "33ae00b4-1e2b-414f-96f3-bea149a6b075",
  "month": "2026-10",
  "kind": "release",
  "credits": 160,
  "created_at": "2026-10-06T08:00:00.000001+01:00"
}
```
`$ bin/studio clip set 33ae00b4-1e2b-414f-96f3-bea149a6b075 --state dropped`  (selected fields)
exit 0
```json
{
  "id": "33ae00b4-1e2b-414f-96f3-bea149a6b075",
  "state": "dropped",
  "credits_reserved": 160
}
```
`$ bin/studio fav list --status queued`  (step 1.3; selected fields)
exit 0
```json
[
  {
    "id": "48381ba8-7b00-479e-b617-59b6e6521d1f",
    "status": "queued",
    "clip_id": "33ae00b4-1e2b-414f-96f3-bea149a6b075"
  }
]
```
`$ bin/studio fav mark 48381ba8-7b00-479e-b617-59b6e6521d1f --status approved --note-file $WORK/renders/tmp/note.txt`  (selected fields)
exit 0
```json
{
  "id": "48381ba8-7b00-479e-b617-59b6e6521d1f",
  "character_slug": "biscuit",
  "status": "approved",
  "total_score": 80.0,
  "clip_id": "33ae00b4-1e2b-414f-96f3-bea149a6b075",
  "note": "clip 33ae00b4-1e2b-414f-96f3-bea149a6b075 dropped: run crashed in round A (no QA failure)"
}
```
`$ bin/studio budget status`  (the reservation is released: only the 181 settled remain)
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

## 10. Log

`$ bin/studio run log --kind daily --status ok --summary-file $WORK/renders/tmp/summary.txt`  (Task 14 implements it (with --summary-file); referenced as-is by the skill)
exit 2
```
Usage: studio [OPTIONS] COMMAND [ARGS]...
Try 'studio --help' for help.
╭─ Error ──────────────────────────────────────────────────────────────────────╮
│ No such command 'run'.                                                       │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## Weekly review sequence (same harness)

`$ bin/studio metrics pull`  (needs POSTIZ_API_KEY and the postiz binary: the skill notes the exit 2 and continues)
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
4. **A synthetic driver's spend used to come before any reservation** (`clip.source_id` was fixed at creation). `clip set --source-id`
   now works while the clip is `planned` (refused afterwards, unknown sources refused), so the order is clip, preflight, reserve,
   then spend.
5. **Free text never goes through the shell**: `--proposal-file`, `--breakdown-file`, `--note-file`, `--reason-file`, `--features-file`,
   `--hook-file`, `--caption-file`, `--qa-file`, source flag `--reason-file`.
6. `fav list --next 1 --character X` (a queue per character, so nobody is starved) and `fav seen` (newest 100 platform ids for vidIQ's
   `excludeContentIds`).

Open, not fixed here (each needs a decision or belongs to a later task):

1. **`bin/studio run log` (Task 14) and `bin/studio review save` do not exist.** The skills call both as specified; `run log` is called
   with `--summary-file F` (Task 14 should accept `--summary` and `--summary-file`). Nothing writes the `reviews` table yet; suggest
   adding `review save` next to `run log` (both need a Store method for their table).
2. **No CLI creates `posts`**, so a clip can only wait in `awaiting_approval` for the terminal's `approve_clip` RPC (Task 15).
   The skill stops there for every account, `auto` included; the brief's "scheduled if the account is auto" needs a post-creating command first.
3. **No CLI hands an `owner_inbox` source (a bucket path) to Higgsfield** (no signed-URL command), so Drop-in from the inbox cannot
   run yet; the skill takes the next row.
4. Skipped by design: visual QA of a real render (ODD EYES sides, outfit, hands, leakage), the MCP calls and the `get_cost` preflights,
   the Genjutsu `preset` suggestion path, `jobs_wait` URL -> `curl`, the `jobs_wait` call with `timeout_seconds: 0` for resolving the
   close-up job id, how a scheduled task really fires the skill. All of these are Task 16.
5. As shipped, both characters are `designing`, so a scheduled `/daily-run` does nothing but log. Go-live = set `status: "live"` and the
   handles / Postiz ids in refs.json, then `bin/studio seed`. Reginald's `closeup` is null until the rehearsal generates it; the skill
   skips him until then. After the owner's top-up, D2 ("Biscuit #2, after the debut") would be produced before the planned debut under
   "picks first" unless the debut clip already exists: make the Task 16 debut re-render the first clip.
