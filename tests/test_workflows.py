"""The scheduled workflows (publish, metrics, health), read as text.

No YAML parser is a dependency, so these tests pin the properties that matter with plain string
checks: the schedule, one non-cancelling concurrency group each, the secrets gate that makes every
workflow a clean no-op until the owner adds the secrets, and the command each one runs.
"""

import re
from pathlib import Path

import pytest

WORKFLOWS = Path(__file__).resolve().parents[1] / ".github" / "workflows"
GATE = "if: steps.gate.outputs.configured == 'true'"
SECRETS = ("DATABASE_URL", "SUPABASE_URL", "SUPABASE_SERVICE_KEY", "POSTIZ_API_KEY")

# The Postiz CLI version the workflows install (the exact one `npm view postiz version` reported on
# 2026-10-05). VERIFY at go-live (docs/launch/go-live.md step 3): bump it deliberately, never `latest`.
POSTIZ_VERSION = "2.0.16"

# name -> (crons, command, needs the Node + Postiz CLI)
# publish: every 15 minutes through the posting window 17:00-20:59 UTC (Franz 19:00 and Reginald 19:30
# London are 18:00 / 18:30 UTC in BST and 19:00 / 19:30 UTC in GMT), Lenny's 12:30 London at 11:30 and 12:30 UTC
# (BST and GMT) + a 3-hourly catch-up for the times the owner picks himself. That is 26 runs a day, not 96:
# GitHub's free minutes are 2,000 a month.
SPEC = {
    "publish": (("*/15 17-20 * * *", "30 11,12 * * *", "40 */3 * * *"), "uv run studio publish due", True),
    "metrics": (("7 */6 * * *",), "uv run studio metrics pull", True),
    "health": (("23 */3 * * *",), "uv run studio health", False),
}


def text(name: str) -> str:
    return (WORKFLOWS / f"{name}.yml").read_text(encoding="utf-8")


def steps(name: str) -> list[str]:
    """The step blocks of the workflow's only job, as raw text."""
    body = text(name).split("    steps:\n", 1)[1]
    return [s for s in re.split(r"(?m)^      - ", body) if s.strip()]


@pytest.mark.parametrize("name", SPEC)
def test_schedule_and_manual_trigger(name):
    crons = SPEC[name][0]
    t = text(name)
    assert re.findall(r"- cron: '([^']+)'", t) == list(crons)
    assert re.search(r"(?m)^  workflow_dispatch:", t)
    assert re.search(rf"(?m)^name: {name}$", t)


@pytest.mark.parametrize("name", SPEC)
def test_one_concurrency_group_named_after_the_workflow_that_never_cancels(name):
    t = text(name)
    assert re.search(rf"(?m)^concurrency:\n  group: {name}\n  cancel-in-progress: false$", t)
    assert "cancel-in-progress: true" not in t


@pytest.mark.parametrize("name", SPEC)
def test_runs_on_ubuntu_2404_with_uv_and_read_only_permissions(name):
    t = text(name)
    assert re.search(r"(?m)^    runs-on: ubuntu-24\.04$", t)
    assert "astral-sh/setup-uv@" in t
    assert re.search(r"(?m)^permissions:\n  contents: read$", t)


@pytest.mark.parametrize("name", SPEC)
def test_the_first_step_checks_database_url_and_every_other_step_waits_for_it(name):
    blocks = steps(name)
    gate, rest = blocks[0], blocks[1:]
    assert "id: gate" in gate and "DATABASE_URL: ${{ secrets.DATABASE_URL }}" in gate
    assert '[ -z "${DATABASE_URL:-}" ]' in gate
    assert 'echo "secrets not configured — skipping"' in gate
    assert 'echo "configured=false" >> "$GITHUB_OUTPUT"' in gate
    assert "exit 1" not in gate  # missing secrets are not a failure
    assert rest and all(GATE in block for block in rest), "a step would run without the secrets"


@pytest.mark.parametrize("name", SPEC)
def test_secrets_reach_only_the_gate_and_the_command_that_needs_them(name):
    blocks = steps(name)
    command = blocks[-1]
    assert SPEC[name][1] in command
    for secret in SECRETS:
        assert f"{secret}: ${{{{ secrets.{secret} }}}}" in command
    for block in blocks[1:-1]:  # checkout, setup-uv, setup-node, npm: no secrets in their environment
        assert "secrets." not in block
    assert "env:" not in text(name).split("    steps:")[0].split("jobs:")[1]  # no job-level env
    assert set(re.findall(r"secrets\.([A-Z_]+)", text(name))) <= set(SECRETS)


@pytest.mark.parametrize("name", SPEC)
def test_the_command_each_workflow_runs(name):
    crons, command, node = SPEC[name]
    t = text(name)
    assert t.count(f"run: {command}") == 1
    if node:
        assert "actions/setup-node@" in t and "node-version: '20'" in t
        install = f"run: npm i -g postiz@{POSTIZ_VERSION}"
        assert t.count(install) == 1 and "postiz@latest" not in t
        assert re.search(r"npm i -g postiz(?!@)", t) is None  # never an unpinned install
        assert t.index(install) < t.index(f"run: {command}")  # installed before it is used
    else:
        code = "\n".join(line for line in t.splitlines() if not line.lstrip().startswith("#"))
        assert "setup-node" not in code and "postiz" not in code.lower().replace("postiz_api_key", "")


# ---- the schedules stay inside GitHub's free minutes and still cover the slots ---------------------------


def _hours(field: str) -> set[int]:
    lo, _, hi = field.partition("-")
    if field.startswith("*/"):
        return set(range(0, 24, int(field[2:])))
    return set(range(int(lo), int(hi or lo) + 1))


def test_publish_runs_through_both_posting_windows_in_gmt_and_in_bst():
    """19:00 and 19:30 London are 18:00 / 18:30 UTC in BST and 19:00 / 19:30 UTC in GMT."""
    window = SPEC["publish"][0][0].split()
    assert window[2:] == ["*", "*", "*"] and window[0] == "*/15"
    hours = _hours(window[1])
    assert {18, 19} <= hours and min(hours) < 18 and max(hours) > 19  # a margin either side of both slots
    assert 0 in range(0, 60, 15) and 30 in range(0, 60, 15)  # a run lands on :00 and :30


def test_publish_runs_at_lennys_midday_slot_in_bst_and_in_gmt():
    """Lenny 12:30 London (owner 2026-10-06) is 11:30 UTC in BST and 12:30 UTC in GMT; the 12:40 UTC catch-up retries it."""
    midday = SPEC["publish"][0][1].split()
    assert midday[0] == "30" and midday[1] == "11,12" and midday[2:] == ["*", "*", "*"]
    assert 12 in _hours(SPEC["publish"][0][2].split()[1]) and SPEC["publish"][0][2].split()[0] == "40"


def test_publish_has_a_three_hourly_catch_up_for_owner_chosen_times():
    catch_up = SPEC["publish"][0][2].split()
    assert catch_up[1] == "*/3" and len(_hours(catch_up[1])) == 8


def test_health_is_every_three_hours_and_the_estimate_fits_the_free_minutes():
    assert SPEC["health"][0][0].split()[1] == "*/3"
    runs_per_day = {
        "publish": 4 * len(_hours(SPEC["publish"][0][0].split()[1])) + len(SPEC["publish"][0][1].split()[1].split(",")) + len(_hours("*/3")),
        "metrics": len(_hours("*/6")),
        "health": len(_hours("*/3")),
    }
    assert runs_per_day == {"publish": 26, "metrics": 4, "health": 8}
    billed = {"publish": 1.5, "metrics": 1.5, "health": 1.0}  # minutes a run bills: setup + uv sync + the command
    monthly_minutes = sum(runs_per_day[w] * billed[w] * 30 for w in runs_per_day)
    assert monthly_minutes == 1590, monthly_minutes  # the estimate docs/launch/go-live.md states; free tier is 2,000


def test_go_live_documents_the_pinned_version_and_the_monthly_minutes():
    doc = (Path(__file__).resolve().parents[1] / "docs" / "launch" / "go-live.md").read_text(encoding="utf-8")
    assert f"postiz@{POSTIZ_VERSION}" in doc and "VERIFY at go-live" in doc
    assert "1,590 minutes" in doc and "2,000" in doc


# ---- studio-drop: the cloud jobs of "Drop a video" (plan 2026-10-06) ------------------------------------------------------

DROP_SECRETS = ("DATABASE_URL", "SUPABASE_URL", "SUPABASE_SERVICE_KEY", "HF_KEY", "HF_API_KEY_ID", "HF_API_KEY_SECRET", "GEMINI_API_KEY")


def test_drop_runs_on_the_two_dispatch_types_a_two_hourly_sweep_and_by_hand():
    t = text("studio-drop")
    assert re.search(r"(?m)^name: studio-drop$", t)
    assert re.search(r"(?m)^  repository_dispatch:\n    types: \[drop-process, drop-make\]$", t)
    assert re.findall(r"- cron: '([^']+)'", t) == ["17 */2 * * *"]
    assert re.search(r"(?m)^  workflow_dispatch:", t)


def test_drop_is_one_job_per_pick_and_never_cancelled():
    t = text("studio-drop")
    assert re.search(
        r"(?m)^concurrency:\n  group: studio-drop-\$\{\{ github\.event\.client_payload\.pick_id \|\| 'sweep' \}\}\n  cancel-in-progress: false$", t
    )
    assert "cancel-in-progress: true" not in t
    assert re.search(r"(?m)^permissions:\n  contents: read$", t) and re.search(r"(?m)^    runs-on: ubuntu-24\.04$", t)


def test_drop_is_gated_on_the_secrets_like_the_other_workflows():
    blocks = steps("studio-drop")
    gate, rest = blocks[0], blocks[1:]
    assert "id: gate" in gate and '[ -z "${DATABASE_URL:-}" ]' in gate and "exit 1" not in gate
    assert all(GATE.split(" == ")[0] in block for block in rest), "a step would run without the secrets"


def test_the_pick_id_is_checked_and_never_pasted_into_a_script():
    t = text("studio-drop")
    code = "\n".join(line for line in t.splitlines() if not line.lstrip().startswith("#"))
    # the payload reaches a script only through env: no ${{ ... client_payload ... }} inside a run: block
    for block in steps("studio-drop"):
        run = block.split("run:", 1)[1] if "run:" in block else ""
        assert "${{" not in run, block[:60]
    assert "PICK_ID: ${{ github.event.client_payload.pick_id }}" in code
    assert "grep -Eqx '[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}'" in code
    assert 'uv run studio drop "$COMMAND" "$PICK"' in code and "uv run studio drop sweep" in code
    assert "drop-process) echo \"command=process\"" in code and "drop-make) echo \"command=make\"" in code


def test_a_manual_run_can_check_the_keys_for_free_instead_of_sweeping():
    """`gh workflow run studio-drop.yml -f job=check-keys`: the free key check, no ffmpeg, the input reaching the script by env."""
    t = text("studio-drop")
    assert re.search(
        r"(?m)^  workflow_dispatch:\n    inputs:\n      job:\n(?:        .*\n)*?        type: choice\n        options: \[sweep, check-keys\]\n        default: sweep$",
        t,
    )
    job = next(b for b in steps("studio-drop") if b.startswith("name: Read the job"))
    assert "JOB_INPUT: ${{ inputs.job }}" in job and '[ "$JOB_INPUT" = "check-keys" ]' in job and 'echo "command=check-keys"' in job
    assert job.index('"$EVENT" != "repository_dispatch"') < job.index("check-keys")  # a dispatch from the database never becomes a key check
    install = next(b for b in steps("studio-drop") if b.startswith("name: Install ffmpeg"))
    assert "steps.job.outputs.command != 'check-keys'" in install
    command = steps("studio-drop")[-1]
    assert 'elif [ "$COMMAND" = "check-keys" ]; then\n            uv run studio drop check-keys' in command


def test_drop_installs_ffmpeg_and_yt_dlp_only_when_there_is_work():
    t = text("studio-drop")
    assert "sudo apt-get update" in t and "sudo apt-get install -y ffmpeg fonts-dejavu-core fontconfig" in t
    assert "uv tool install 'yt-dlp[default,curl-cffi]'" in t and 'uv tool dir --bin >> "$GITHUB_PATH"' in t
    assert "uv run studio drop pending --count" in t
    install = next(b for b in steps("studio-drop") if b.startswith("name: Install ffmpeg"))
    assert "steps.pending.outputs.count != '0'" in install


def test_drop_secrets_reach_only_the_job_that_needs_them():
    blocks = steps("studio-drop")
    command = blocks[-1]
    for secret in DROP_SECRETS:
        assert f"{secret}: ${{{{ secrets.{secret} }}}}" in command
    assert "POSTIZ_API_KEY" not in text("studio-drop")  # nothing here posts
    for block in blocks[1:-1]:
        names = set(re.findall(r"secrets\.([A-Z_]+)", block))
        assert names <= {"DATABASE_URL"}, block[:60]  # the pending count reads the database, nothing else
    assert "env:" not in text("studio-drop").split("    steps:")[0].split("jobs:")[1]
    assert set(re.findall(r"secrets\.([A-Z_]+)", text("studio-drop"))) == set(DROP_SECRETS)
