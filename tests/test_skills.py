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
    assert "Never the audio of `gen.mp4` or of the source file" in body
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
    assert "his hook in the first second" in prompt and "eye close-up with the glint" in prompt


def test_the_values_the_skill_names_are_the_ones_the_database_accepts():
    sql = (ROOT / "supabase" / "migrations" / "0007_characters_view.sql").read_text()
    body = text("daily-run")
    for value in ("cameo", "featured", "star"):
        assert f"'{value}'" in sql and f"`{value}`" in body
    for value in ("dropin", "recreate"):
        assert f"'{value}'" in sql
    assert "owner_note" in sql and "owner_mode" in sql and "owner_presence" in sql
