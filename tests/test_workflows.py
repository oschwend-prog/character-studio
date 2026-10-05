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
# publish: every 15 minutes through the posting window 17:00-20:59 UTC (Biscuit 19:00 and Reginald 19:30
# London are 18:00 / 18:30 UTC in BST and 19:00 / 19:30 UTC in GMT) + a 3-hourly catch-up for the times the
# owner picks himself. That is 24 runs a day, not 96: GitHub's free minutes are 2,000 a month.
SPEC = {
    "publish": (("*/15 17-20 * * *", "40 */3 * * *"), "uv run studio publish due", True),
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


def test_publish_has_a_three_hourly_catch_up_for_owner_chosen_times():
    catch_up = SPEC["publish"][0][1].split()
    assert catch_up[1] == "*/3" and len(_hours(catch_up[1])) == 8


def test_health_is_every_three_hours_and_the_estimate_fits_the_free_minutes():
    assert SPEC["health"][0][0].split()[1] == "*/3"
    runs_per_day = {
        "publish": 4 * len(_hours(SPEC["publish"][0][0].split()[1])) + len(_hours("*/3")),
        "metrics": len(_hours("*/6")),
        "health": len(_hours("*/3")),
    }
    assert runs_per_day == {"publish": 24, "metrics": 4, "health": 8}
    billed = {"publish": 1.5, "metrics": 1.5, "health": 1.0}  # minutes a run bills: setup + uv sync + the command
    monthly_minutes = sum(runs_per_day[w] * billed[w] * 30 for w in runs_per_day)
    assert monthly_minutes == 1500, monthly_minutes  # the estimate docs/launch/go-live.md states; free tier is 2,000


def test_go_live_documents_the_pinned_version_and_the_monthly_minutes():
    doc = (Path(__file__).resolve().parents[1] / "docs" / "launch" / "go-live.md").read_text(encoding="utf-8")
    assert f"postiz@{POSTIZ_VERSION}" in doc and "VERIFY at go-live" in doc
    assert "1,500 minutes" in doc and "2,000" in doc
