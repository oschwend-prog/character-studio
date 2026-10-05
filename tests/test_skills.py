"""The two skills (``.claude/skills/*/SKILL.md``) are instructions an unattended run follows to the letter,
so what they cite is checked against the code: every ``bin/studio`` command and option exists, every outside
tool they call is on the permission proposal's explicit allowlist (and nothing on its deny list is called),
and third-party text never travels inline in the shell.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
import typer.main

from studio.cli import app

ROOT = Path(__file__).resolve().parents[1]
SKILLS = {name: ROOT / ".claude" / "skills" / name / "SKILL.md" for name in ("daily-run", "weekly-review")}
PROPOSED = json.loads((ROOT / ".claude" / "settings.json.proposed").read_text())["permissions"]
HF = "mcp__53354c6e-fbc1-47dd-ac53-ad2126ec66bd__"
VIDIQ = "mcp__5d0eb7b3-1f89-4c02-b145-8199ffc4ed25__"


def text(name: str) -> str:
    return SKILLS[name].read_text(encoding="utf-8")


def spans(name: str) -> list[str]:
    return re.findall(r"`([^`\n]+)`", text(name))


def studio_calls(name: str) -> list[str]:
    """The ``bin/studio ...`` code spans, with the leading ``bin/studio `` removed."""
    return [s.split("bin/studio ", 1)[1] for s in spans(name) if s.startswith("bin/studio ")]


def resolve(call: str) -> tuple[Any, list[str], list[str]]:
    """(the command the words name, its path, the rest of the words)."""
    root = typer.main.get_command(app)
    cmd: Any = root
    words = call.split()
    path: list[str] = []
    while words and hasattr(cmd, "commands") and words[0] in cmd.commands:
        cmd = cmd.commands[words[0]]
        path.append(words.pop(0))
    return cmd, path, words


CALLS = [(n, c) for n in SKILLS for c in studio_calls(n)]


@pytest.mark.parametrize(("skill", "call"), CALLS, ids=[f"{n}:{c[:50]}" for n, c in CALLS])
def test_every_studio_command_and_option_the_skills_cite_exists(skill, call):
    cmd, path, rest = resolve(call)
    assert path, f"{skill}: `bin/studio {call}` names no command"
    assert not hasattr(cmd, "commands"), f"{skill}: `bin/studio {call}` stops at the group `{' '.join(path)}`"
    known = {o for p in cmd.params if hasattr(p, "secondary_opts") for o in (*p.opts, *p.secondary_opts)}
    for word in rest:
        if word.startswith("--"):
            option = word.split("=", 1)[0].rstrip(",.;:)")
            assert option in known, f"{skill}: `bin/studio {call}`: no option {option} on `studio {' '.join(path)}`"


def test_the_commands_this_wave_added_are_the_ones_the_skill_uses():
    cited = {" ".join(resolve(c)[1]) for c in studio_calls("daily-run")}
    assert {"budget open", "budget settle", "budget release", "budget reserve", "master build", "source add",
            "fav pick", "clip schedule", "qa frames"} <= cited  # fmt: skip
    daily = "\n".join(studio_calls("daily-run"))
    assert "--trend-file" in daily and not re.search(r"--trend\s", daily)  # a trend name is third-party text
    assert "master build --spec renders/<id>/spec.json --clip <id>" in daily


def tool_names(allow_or_deny: list[str]) -> set[str]:
    return {r.split("__", 2)[2] for r in allow_or_deny if r.startswith("mcp__") and r.count("__") >= 2}


def test_the_permission_allowlist_matches_the_tools_the_skills_call():
    """No tool in the allowlist that no skill calls (dead permission), none called that is not allowed."""
    allowed = tool_names(PROPOSED["allow"])
    denied = tool_names(PROPOSED["deny"])
    body = text("daily-run") + text("weekly-review")
    mentioned = {t for t in allowed if re.search(rf"(?<![\w]){re.escape(t.removeprefix('vidiq_'))}(?![\w])", body) or t in body}
    assert allowed <= mentioned, f"allowed but never mentioned by a skill: {sorted(allowed - mentioned)}"
    for tool in denied:
        if tool in ("execute_preset", "participate_in_contest"):
            continue  # named in the guardrail sentence, as things never to run
        assert tool not in body, f"a skill mentions the denied tool {tool}"
    assert not allowed & denied


def test_the_guardrail_names_the_one_permitted_upload_and_the_never_run_tools():
    for name in SKILLS:
        guard = next(line for line in text(name).splitlines() if line.startswith("Guardrails:"))
        assert "execute_preset" in guard
    daily = text("daily-run").split("Guardrails:", 1)[1].split("\n", 1)[0]
    assert "`media_import_url`" in daily and "own Storage signed URL" in daily
    assert "participate_in_contest" in daily


def test_third_party_text_is_never_put_inline_in_the_shell():
    body = text("daily-run")
    assert "--trend T" not in body and "--url U --platform" not in body
    for call in studio_calls("daily-run"):
        assert not re.search(r'--(?:url|creator)\s+"?<?(?:U|@)', call) or "source add" in call or "fav" not in call
    # a pick's url and creator ride in the proposal JSON file
    assert '"url": "<video URL>"' in body and '"creator": "@handle"' in body
    # every download creates its folder and quotes the URL
    for curl in re.findall(r"curl [^`]+", body):
        assert "--create-dirs" in curl and "-L" in curl, curl
        assert "'" in curl.split("-o", 1)[1], f"unquoted URL: {curl}"


def test_the_skill_has_no_second_generating_call_in_a_reroll_and_returns_picks_by_breakdown():
    body = text("daily-run")
    assert "WITHOUT its own `clip set --state generating`" in body
    assert re.search(r"`--status analysed` when its `breakdown_md` is set", body) or "--status analysed` when its `breakdown_md` is set" in body
    assert "cumulative over a re-roll" in body
    assert "no live characters" in body
    assert "`bin/studio budget open`" in body


def test_the_skill_names_a_beat_that_is_not_the_sources_soundtrack():
    body = text("daily-run")
    assert "Beat render" in body and "generate_audio: true" in body
    assert "Never the raw source file's audio (an inbox or library file)" in body  # the generation's own audio only for music `original`
    assert "`generate_audio` with" not in body.replace("generate_audio: true", "")  # the speech-only tool is not used


# ---- the owner's "Make it" sheet and the Scanner card: what the daily run reads and writes -----------------


def test_the_run_opens_a_log_row_first_and_closes_it_with_the_same_start_and_the_scan_numbers():
    body = text("daily-run")
    calls = studio_calls("daily-run")
    assert "run log --kind daily --status ok --open" in calls  # "Scanning now" while the row is open
    closing = next(c for c in calls if c.startswith("run log --kind daily --status ok|budget_stop|error"))
    for option in ("--summary-file", "--started-at", "--details-file renders/tmp/details.json"):
        assert option in closing, option
    assert body.index("--open") < body.index("1. `bin/studio seed status`")  # before anything can fail
    # the scan step writes the exact shape studio.health.validate_details accepts and the card reads
    assert '{"scan": {"queries": ["biscuit #2 concept"], "outliers": 9, "picks_added": 4, "auto_approved": 1, "held": 1, "skipped": 2, "vidiq_credits": 5}}' in body
    from studio.health import validate_details

    validate_details(json.loads(re.search(r"`(\{\"scan\": \{\"queries\".*?\}\})`", body).group(1)))
    assert 'write `{"vidiq_credits": 10}`' in body  # a day without a scan that bought a breakdown still counts toward the 150


def test_the_skill_follows_the_owners_note_mode_and_presence_inside_the_guardrails():
    body = text("daily-run")
    assert "`proposal.owner_note`, follow it (hook, caption, prop, timing) unless it breaks a guardrail" in body
    assert "say in the run log how it was applied" in body
    # mode: the owner's choice, but Drop-in still needs an eligible source (and the share rule) or it is made as Recreate
    assert "`proposal.owner_mode`" in body and "`recreate` → Recreate whatever the plan says" in body
    assert "Drop-in only when BOTH hold" in body and "make it as Recreate and say why in the run log" in body
    assert "The owner's choice never lifts a rule" in body
    # presence: mapped into the replace-object prompt, `featured` when absent
    prompt = body.split("`hf_mult_replace_object` for Drop-in", 1)[1].split("`jobs_wait`", 1)[0]
    assert "`proposal.owner_presence` (absent = `featured`)" in prompt
    assert "`cameo` = replace a secondary element" in prompt and "keep his motion minimal" in prompt
    assert "`featured` = replace the main performer and follow their motion" in prompt
    assert "`star` = replace the main performer and push the performance" in prompt
    assert "his hook in the first second" in prompt
    # owner 2026-10-05: no eye close-up, glint or sting at the end of a master
    assert "eye close-up with the glint" not in prompt


def test_the_values_the_skill_names_are_the_ones_the_database_accepts():
    sql = (ROOT / "supabase" / "migrations" / "0007_characters_view.sql").read_text()
    body = text("daily-run")
    for value in ("cameo", "featured", "star"):
        assert f"'{value}'" in sql and f"`{value}`" in body
    for value in ("dropin", "recreate"):
        assert f"'{value}'" in sql
    assert "owner_note" in sql and "owner_mode" in sql and "owner_presence" in sql


# ---- Drop-in first (owner decisions 2026-10-05): the playbook, the effective mode, music, gallery picks, the cards ------


def test_the_playbook_names_the_five_rules_in_the_owners_words():
    body = text("daily-run")
    playbook = body.split("## Drop-in playbook", 1)[1].split("## 1. Orient", 1)[0]
    for rule in ("Pick swap-friendly clips", "Trim before generating", "Transform", "Credit and cleanliness", "Music"):
        assert f"**{rule}" in playbook, rule
    assert "6-9 s" in playbook and "16 s the hard maximum" in playbook and "paid per second" in playbook
    assert "`original` is the default of a Drop-in" in playbook and "`in_app`" in playbook and "`ai_beat`" in playbook
    assert "Never put in audio that the clip did not carry" in playbook


def test_the_modes_the_skill_uses_are_the_effective_mode_and_never_wait_on_a_download():
    body = text("daily-run")
    assert "The one download from TikTok, Instagram or YouTube is `bin/studio source fetch --pick <id>`" in body  # owner allowed it 2026-10-05
    assert "for ONE APPROVED pick at a time, never in bulk" in body and "(no yt-dlp or `curl` of your own)" in body
    assert "never ask the owner for a clip" in body
    assert "**Effective mode.**" in body and "logs which one it used and why" in body
    step = body.split("5. **Effective mode.**", 1)[1].split("## 5. Create", 1)[0]
    # a usable source is a gallery preset or an attached clip; anything else is an automatic Recreate
    assert "a **gallery pick** (`proposal.preset_id`)" in step and "`proposal.owner_clip_path`" in step
    assert "`bin/studio source ingest-owner --pick <id>`" in body
    assert "automatic Recreate" in step and "Never ask the owner for a clip" in step
    assert "--other-people 0 --no-minors`" in step and "`--minors` when a child is visible" in step
    assert "`bin/studio source trim <id> --start S --duration D`" in step and "6-9 s" in step
    # a real pick without a clip is briefed from vidIQ's breakdown and driven by a synthetic Seedance driver
    assert "vidIQ `watch_shortform_content` on the pick's URL (10 credits" in body
    assert "Synthetic driver (only for a Recreate without a usable source)" in body and "`resolution: 480p`" in body


def test_the_reserve_follows_the_cost_model_and_the_music():
    body = text("daily-run")
    assert "`bin/studio plan estimate --mode M --seconds S --music MUSIC`" in body
    assert "Recreate 160; Drop-in ceil(S x 11) + 3, plus 30 for an `ai_beat`" in body
    assert "Recreate 160, Drop-in 115" not in body and "(Recreate 160, Drop-in" not in body.replace("Recreate 160; Drop-in", "")
    assert "(no watermark, overlay or other people)" not in body  # background people no longer block


def test_music_original_is_the_default_and_a_lost_audio_track_is_muxed_back():
    body = text("daily-run")
    assert "`original` for a Drop-in unless the pick's `proposal.owner_music` says `in_app` or `ai_beat`" in body
    assert "a Recreate: `ai_beat`" in body
    qa = body.split("## 8. QA", 1)[1].split("## 9.", 1)[0]
    assert "check `has_audio`" in qa and "`bin/studio master mux-audio renders/<id>/gen.mp4" in qa and "--start <the trim start in seconds>" in qa
    assert "aligned to the trimmed window" in qa
    master = body.split("## 9. Master", 1)[1].split("## 10.", 1)[0]
    assert '`music` = the clip\'s `music`' in master or "`music` = the clip's `music`" in master
    assert "for `original` the same file as `dance`" in master and "none for `in_app`" in master


def test_gadgets_are_worn_or_held_in_the_still_and_the_genjutsu_prompt_with_no_logo():
    body = text("daily-run")
    assert "`proposal.owner_props`" in body and "the character wears or holds them" in body
    assert "in the scene still prompt and in the Genjutsu prompt" in body and "never with a real brand logo" in body
    assert "Say in the run log how they were used" in body


def test_the_character_sheet_goes_to_genjutsu_with_the_master_and_the_gallery_is_the_backup():
    body = text("daily-run")
    assert "the character sheet `sheets[body]` of the character" in body and "as a second `image_references` entry" in body
    part_b = body.split("Part B, the Genjutsu gallery, ONLY as a backup", 1)[1].split("## 3. Plan", 1)[0]
    assert "`genjutsu-trending` and `genjutsu-new`" in part_b and "the best 2-4 for that character" in part_b
    assert '"tier": "gallery"' in part_b and '"preset_id"' in part_b and '"thumbnail_url"' in part_b and '"preview_url"' in part_b
    assert "--platform higgsfield" in part_b and "stored, never downloaded here" in part_b
    scan = body.split("## 2. Scan", 1)[1].split("Part B", 1)[0]
    assert '"theme"' in scan and '"posted_at"' in scan and '"thumbnail_url"' in scan
    assert '"tier": "viral_now"' not in scan and "leave `tier` OUT of the file" in scan  # a tier set on every pick would hide the rule
    assert "name the matching traits" in scan and "score against `traits`" in scan
    assert "no media is downloaded or rehosted" in scan


def test_scan_json_has_a_theme_per_rotation_entry_and_fit_rules_that_reference_the_traits():
    scan = json.loads((ROOT / "config" / "scan.json").read_text())
    for slug in ("biscuit", "reginald", "outsider"):
        rotation = scan["characters"][slug]["rotation"]
        themes = [r["theme"] for r in rotation]
        assert all(isinstance(t, str) and 0 < len(t) <= 60 for t in themes), slug
        assert len(set(themes)) == len(themes), slug  # a theme names one entry
    assert [r["theme"] for r in scan["characters"]["reginald"]["rotation"]][0] == "deadpan at work"
    assert "elder out-dances the young" in [r["theme"] for r in scan["characters"]["reginald"]["rotation"]]
    assert "pet with a human job" in [r["theme"] for r in scan["characters"]["biscuit"]["rotation"]]
    for slug in ("biscuit", "reginald"):
        assert any("traits card" in rule for rule in scan["characters"][slug]["fit_rules"]), slug
    assert "tier" in scan["pick_card_fields"] and "theme" in scan["pick_card_fields"] and "thumbnail_url" in scan["pick_card_fields"]


# ---- the analyst upgrade (owner request 2026-10-05): analyse before filing, fetch, look, check, trim, purge ----------------------


def json_span(name: str, marker: str) -> dict:
    """The JSON object in the code span that contains ``marker``."""
    span = next(s for s in spans(name) if marker in s and s.startswith("{"))
    return json.loads(span)


def test_the_scan_analyses_the_survivors_before_filing_and_inside_the_vidiq_budget():
    scan = text("daily-run").split("## 2. Scan", 1)[1].split("Part B", 1)[0]
    for part in (
        "`saturation_count`", "near-duplicates", "8 or more copies 3, 4-7 5, 1-3 8, none 10", "**Velocity**", "views per day since `posted_at`",
        "BEFORE filing", "**No watches**", "no vidIQ `watch_shortform_content` before filing", "`bin/studio source analyze`",
        "`watches_per_character`", "`breakdowns_per_week`", "`balance_floor`",
        "`trait_matches`", "`why`", "`engagement`", "never guess a count", "`config/scan.json` `tier_rules`",
    ):  # fmt: skip
        assert part in scan, part
    assert "the TOP 3 of each" not in scan and "--breakdown-file" not in scan  # no vidIQ watch is bought before filing any more
    assert scan.index("**Saturation**") < scan.index("**No watches**") < scan.index("**Fit**") < scan.index("File each:")
    budget = json.loads((ROOT / "config" / "scan.json").read_text())["budget"]
    for key in ("watches_per_character", "breakdowns_per_week", "balance_floor", "credits_per_watch", "credits_per_scan"):
        assert isinstance(budget[key], int), key


def test_the_scan_is_one_instagram_and_tiktok_search_each_weekday_inside_the_150_credit_plan():
    """Owner 2026-10-05: Instagram + TikTok viral clips only, one outlier search a weekday, the gallery only as a backup."""
    cfg = json.loads((ROOT / "config" / "scan.json").read_text())
    budget = cfg["budget"]
    assert budget["scan_days"] == ["Mon", "Tue", "Wed", "Thu", "Fri"] and budget["scans_per_week"] == 5
    assert (budget["breakdowns_per_week"], budget["watches_per_character"], budget["balance_floor"]) == (0, 0, 5)
    assert budget["scans_per_week"] * budget["credits_per_scan"] * 52 / 12 <= budget["vidiq_monthly_credits"]  # about 108 of 150
    assert cfg["defaults"]["resultsPerPlatform"] == 20  # the call costs the same whatever it returns
    body = text("daily-run")
    scan = body.split("## 2. Scan", 1)[1].split("Part B", 1)[0]
    for part in (
        "Instagram + TikTok viral clips only", "ONE search each weekday", "`vidiq_instagram_tiktok_outlier_search`", "One call a day, never a second",
        "`vidiq_balance` first", '`{"vidiq": "skipped, balance N, refills <date>"}`', "5 × ISO week number + (Mon 0, Tue 1, Wed 2, Thu 3, Fri 4)",
        "Biscuit and Reginald in turn", "rotates through its own themes", "YouTube is used only for the stats of an iconic moment",
        "**Launch rule**", "first posts are absolute hits people know", "**Owner-pasted links**", "always analysed and filed",
        "`bin/studio fav rescore <id> --freshness F --fit T --feasibility S --saturation A --proposal-file renders/tmp/p.json`",
    ):  # fmt: skip
        assert part in scan, part
    part_b = body.split("Part B, the Genjutsu gallery", 1)[1].split("## 3. Plan", 1)[0]
    assert part_b.startswith(", ONLY as a backup") and "fewer than 2 usable picks" in part_b and "could not run" in part_b
    concept = body.split("## 4. Concept", 1)[1].split("## 5. Create", 1)[0]
    assert "**Launch rule**" in concept and "`iconic`" in concept
    assert "Only while `config/scan.json` `budget.breakdowns_per_week` is above 0" in concept  # no breakdown is bought now
    from studio.health import validate_details

    validate_details({"vidiq": "skipped, balance 3, refills 2026-11-01"})  # the skipped-search record passes the door


def test_background_people_are_fine_and_only_a_second_dancing_star_waits_for_the_multi_body_test():
    cfg = json.loads((ROOT / "config" / "scan.json").read_text())
    for slug in ("biscuit", "reginald"):
        first = cfg["characters"][slug]["fit_rules"][0]
        assert "people in the background are fine" in first and "not a gate" in first, slug
        assert "a second dancing star is still filed with needs multi_body" in first, slug
        assert "replace or recreate" not in first and "2+ bodies" not in first, slug


def test_the_card_json_the_skill_shows_is_accepted_by_the_door():
    from studio.favorites import validate_analysis, validate_card, validate_needs

    for marker in ('"url": "<video URL>"', '"preset_id": "<preset id>"'):
        proposal = json_span("daily-run", marker)
        proposal.pop("url", None)
        proposal.pop("creator", None)
        validate_needs(proposal)
        for key, real in (("thumbnail_url", "https://t.example/a.jpg"), ("preview_url", "https://t.example/a.mp4")):
            if key in proposal:
                proposal[key] = real  # the skill shows a placeholder where a tool's URL goes
        validate_card(proposal)
        assert isinstance(proposal["trait_matches"], list) and isinstance(proposal["why"], str)
    scan_card = json_span("daily-run", '"url": "<video URL>"')
    assert {"engagement", "saturation_count", "trait_matches", "why", "theme", "posted_at"} <= set(scan_card)
    assert "tier" not in scan_card  # the category is worked out from the numbers, never copied from an example
    analysis = json_span("daily-run", '"people_count"')
    validate_analysis(analysis)
    assert set(analysis) == {"people_count", "main_subject", "camera", "watermark", "overlay", "minors", "best_window", "bpm", "notes"}


def test_the_clip_is_fetched_looked_at_checked_trimmed_and_purged_in_that_order():
    body = text("daily-run")
    step = body.split("5. **Effective mode.**", 1)[1].split("## 5. Create", 1)[0]
    assert step.index("**Fetch**") < step.index("**Look at the clip**") < step.index("Then **trim**")
    for part in (
        "`bin/studio source fetch --pick <id> --body B --bodies N`", "approved picks only, public, no login, no cookies, one clip",
        "Exit 0:", "`already: true`", "Exit 1: yt-dlp could not", "the pick was marked Recreate", "Exit 2: the call was refused or Storage failed",
        "`bin/studio source analyze <source id>`", "`renders/<id>/analysis.png`", "Read tool", "a child anywhere",
        "`bin/studio fav mark <pick> --analysis-file renders/tmp/a.json`", '"Clip check" row', "the analysis' `best_window`",
    ):  # fmt: skip
        assert part in step, part
    assert "no `preset_id`, no `owner_clip_path`, and the owner did not choose Recreate" in step  # the cases that need no fetch
    # the tidy-up: a sweep at the start of every run, and the clip itself once it is scheduled
    orient = body.split("## 1. Orient", 1)[1].split("## 2. Scan", 1)[0]
    assert "`bin/studio source purge --pending`" in orient and "never touched" in orient
    master = body.split("## 9. Master", 1)[1].split("## 10.", 1)[0]
    assert "`bin/studio source purge --clip <id>`" in master and "`scheduled`" in master


def test_the_fetch_never_runs_outside_the_cli_and_the_skill_never_names_a_social_download_tool():
    body = text("daily-run")
    assert "yt-dlp inside the CLI" in body
    assert not re.search(r"`yt-dlp[^`]*`", body)  # no yt-dlp command of its own: only the CLI wraps it
    for curl in re.findall(r"curl [^`]+", body):
        assert not re.search(r"tiktok|instagram|youtube", curl, re.I), curl


def test_the_breakdown_bought_before_filing_is_not_bought_twice():
    body = text("daily-run")
    assert "(watched before filing, step 2), has its breakdown: no second purchase" in body


def test_the_caption_follows_the_owners_formula_with_a_rotating_engagement_line_and_a_first_comment():
    """Owner 2026-10-05: title, joke, ONE rotating engagement line, credit; the disclosure is automatic; 3-5 clean hashtags."""
    master = text("daily-run").split("## 9. Master", 1)[1].split("## 10.", 1)[0]
    for part in (
        "searchable title of at most 40 characters", "`<famous moment or format> · dachshund edition`", "`· butler edition`",
        "`## Search keywords`", "a label, not the character speaking", "never mention dancing",
        "ONE engagement line, rotating per character", "a send trigger", "a question", "a series tease",
        "Read the character's last 2 captions (`bin/studio clip list --character X`", "never use the kind of the last post again",
        "`🎵 <song> – <artist>`", "` · dance: @<creator>`", "` · trend: <credit_handle>`", "` · original: <creator>`", "no handle known, no credit line",
        "Publishing adds the AI disclosure line", "never write it", "3-5", "#oddeyes", "never #fyp, #foryou, #foryoupage, #viral or #explore",
        "`humanizer` skill", "must fit 2,200 characters", "**First comment**", "at most 300 characters", "the owner pins it",
        "--first-comment-file renders/<id>/first_comment.txt", "Wednesday dance · butler edition", "Single Ladies · dachshund edition",
    ):  # fmt: skip
        assert part in master, part
    assert "at most 5 hashtags, the caption passed" not in master  # the old one-line rule is gone
    assert "`--first-comment-file`" in text("daily-run").split("## Drop-in playbook", 1)[0]  # free text goes through a file
