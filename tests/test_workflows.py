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

# name -> (cron, command, needs the Node + Postiz CLI)
SPEC = {
    "publish": ("*/15 * * * *", "uv run studio publish due", True),
    "metrics": ("7 */6 * * *", "uv run studio metrics pull", True),
    "health": ("23 * * * *", "uv run studio health", False),
}


def text(name: str) -> str:
    return (WORKFLOWS / f"{name}.yml").read_text(encoding="utf-8")


def steps(name: str) -> list[str]:
    """The step blocks of the workflow's only job, as raw text."""
    body = text(name).split("    steps:\n", 1)[1]
    return [s for s in re.split(r"(?m)^      - ", body) if s.strip()]


@pytest.mark.parametrize("name", SPEC)
def test_schedule_and_manual_trigger(name):
    cron = SPEC[name][0]
    t = text(name)
    assert f"- cron: '{cron}'" in t
    assert len(re.findall(r"- cron:", t)) == 1
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
    cron, command, node = SPEC[name]
    t = text(name)
    assert t.count(f"run: {command}") == 1
    if node:
        assert "actions/setup-node@" in t and "node-version: '20'" in t
        assert t.index("run: npm i -g postiz") < t.index(f"run: {command}")  # installed before it is used
    else:
        code = "\n".join(line for line in t.splitlines() if not line.lstrip().startswith("#"))
        assert "setup-node" not in code and "postiz" not in code.lower().replace("postiz_api_key", "")
