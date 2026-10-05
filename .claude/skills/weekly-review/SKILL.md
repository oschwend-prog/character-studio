---
name: weekly-review
description: ODD EYES weekly review (scheduled task): metrics, lifts, playbooks and the KPI bars.
disable-model-invocation: true
---
# Weekly review

Work from the repo root. Every state change goes through `bin/studio` (JSON on stdout). Exit codes: 0 ok, 1 a pull failed, 2 caller error (fix the call). The review reports; cadence, cap, status and the bars stay the owner's. Whatever happens, finish with step 8.

1. `bin/studio metrics pull`. Exit 1 → note which pull failed and carry on with what exists.
2. Instagram owner insights (free): vidIQ `instagram_connected_accounts`. For each account with `accessLevel: "owner"` call `instagram_owner_insights` with its `platformAccountId`, write the rows to `renders/ig-insights.json`, run `bin/studio metrics ingest-ig renders/ig-insights.json`. A `public_fallback` account has no owner insights: report it, ingest nothing.
3. `bin/studio review data`. This is the whole evidence: `bars`, `clips`, `lifts`, `formats`, `hooks`, `characters`, `accounts`, `ig_guard`. It applies the Instagram guard itself: each `ig_guard` entry with `applied: true` had its `dropin_share` cut to 0.20; report it with its reach drop.
4. Trend read: run the `last30days` skill once per niche, queries from each bible's scan profile (Biscuit: dog and pet dance trends; Reginald: deadpan, British humour and dance trends). Keep at most 5 bullets per niche: what is rising, what peaked, what to try next week.
5. Per character write the report from the `review data` payload only:
   - Bar: `characters[].bar` (`not_yet`, `continue`, `promote`, `kill`) with `posts`, `age_days`, `median_views_7d`, `max_views`. Quote the thresholds from `bars`, never from memory. The verdict is the code's.
   - Formats with `keep` or `kill` verdicts, proven hooks, lifts with their `n`, the character's accounts (`non_follower_pct`, `skip_rate`, `watched_pct`), the Instagram guard, the trend bullets.
   - Pick calibration: once 20 pick-made clips (`features.fav_id`) have an `outlier_x`, compare each pick sub-score (`bin/studio fav list --status made`) with it and propose new weights as a proposal for the owner; apply nothing.
6. Playbook: update `characters/<slug>/playbook.md` (create it when missing). A rule enters only with at least 5 posts behind it (`n` of a lift, a `keep` or `kill` format, a `proven` hook) and carries its numbers and the date. Anything with fewer posts goes under "Watching".
7. `bin/studio review save --week <Monday as YYYY-MM-DD> --character <slug> --bar-status <not_yet|continue|promote|kill> --report-file <path to the markdown report>` per character. Then `git add characters/*/playbook.md` and `git commit -m "chore: weekly review <date>"`. The commit stays local.
8. `bin/studio run log --kind weekly --status ok|error --summary "<text>"`: the bar per character, guard cuts, what was skipped and why.
