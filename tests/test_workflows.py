"""The scheduled workflows (publish, metrics, health), read as text.

No YAML parser is a dependency, so these tests pin the properties that matter with plain string
checks: the schedule, one non-cancelling concurrency group each, the secrets gate that makes every
workflow a clean no-op until the owner adds the secrets, and the command each one runs.
"""

import re
from datetime import date
from pathlib import Path

import pytest

WORKFLOWS = Path(__file__).resolve().parents[1] / ".github" / "workflows"
GATE = "if: steps.gate.outputs.configured == 'true'"
GATE_ALWAYS = "if: always() && steps.gate.outputs.configured == 'true'"  # `studio publish confirm` after the publish step: even when it failed
SECRETS = ("DATABASE_URL", "SUPABASE_URL", "SUPABASE_SERVICE_KEY", "POSTIZ_API_KEY")
CONFIRM = "uv run studio publish confirm"  # ask Postiz whether the posts it accepted were really published (publish and metrics run it)
CONFIRM_SECRETS = {"DATABASE_URL", "POSTIZ_API_KEY"}  # it reads the database and Postiz; it touches no storage
RESHARE = "uv run studio publish reshare"  # the daily re-share of the best recent Reel as a Story (metrics runs it, after confirm)

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
    assert rest and all(
        GATE in block or (GATE_ALWAYS in block and f"run: {CONFIRM}" in block) for block in rest
    ), "a step would run without the secrets"


@pytest.mark.parametrize("name", SPEC)
def test_secrets_reach_only_the_gate_and_the_command_that_needs_them(name):
    blocks = steps(name)
    command = next(block for block in blocks if f"run: {SPEC[name][1]}" in block)
    for secret in SECRETS:
        assert f"{secret}: ${{{{ secrets.{secret} }}}}" in command
    confirm = [block for block in blocks if f"run: {CONFIRM}" in block]
    assert len(confirm) == (1 if name in ("publish", "metrics") else 0)
    for block in confirm:  # the confirm step gets the two secrets it needs and nothing else
        assert set(re.findall(r"secrets\.([A-Z_]+)", block)) == CONFIRM_SECRETS
    reshare = [block for block in blocks if f"run: {RESHARE}" in block]
    assert len(reshare) == (1 if name == "metrics" else 0)
    for block in reshare:  # the re-share signs the Story video: it gets all four secrets, like the command it sits beside
        assert set(re.findall(r"secrets\.([A-Z_]+)", block)) == set(SECRETS)
    for block in blocks[1:]:  # checkout, setup-uv, setup-node, npm: no secrets in their environment
        if block is not command and block not in confirm and block not in reshare:
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

DROP_SECRETS = (
    "DATABASE_URL", "SUPABASE_URL", "SUPABASE_SERVICE_KEY", "HF_KEY", "HF_API_KEY_ID", "HF_API_KEY_SECRET", "GEMINI_API_KEY",
    "SCRAPECREATORS_API_KEY",  # the one-post fallback of a dropped link yt-dlp cannot fetch (plan Task 6)
)


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


def test_a_sweep_runs_three_identical_workers_in_parallel_and_one_pick_or_a_key_check_runs_one():
    """A sweep checked its clips one after another (about 5 minutes each) and hit the 60-minute limit after ~11: the repo is public,
    so Actions minutes are free, and three workers share the drops (the lease keeps them off each other's)."""
    t = text("studio-drop")
    assert re.search(
        r"(?m)^    strategy:\n      fail-fast: false\n      matrix:\n        worker: "
        r"\$\{\{ fromJSON\(\(github\.event_name == 'repository_dispatch' \|\| inputs\.job == 'check-keys'\) && '\[1\]' \|\| '\[1,2,3\]'\) \}\}$",
        t,
    )
    assert t.count("matrix:") == 1 and t.count("fail-fast: false") == 1  # one list for the one job; a failed worker stops no other
    command = steps("studio-drop")[-1]
    # each worker tells the lease who it is: studio.drop.job_id() appends it to the run id (gh-<run>-<attempt>-w<worker>)
    assert "STUDIO_WORKER: ${{ matrix.worker }}" in command
    assert t.count("matrix.worker") == 1
    assert "env:" not in t.split("    steps:")[0].split("jobs:")[1]  # still no job-level env (the worker number is the step's)
    # nothing else about the job changed: the 60-minute limit, the never-cancelling per-pick group, the secrets gate
    assert re.search(r"(?m)^    timeout-minutes: 60$", t)
    assert re.search(r"(?m)^concurrency:\n  group: studio-drop-\$\{\{ github\.event\.client_payload\.pick_id \|\| 'sweep' \}\}\n  cancel-in-progress: false$", t)
    assert "uv run studio drop pending --count" in t and "steps.pending.outputs.count != '0'" in t  # the "nothing pending" early stop


def test_a_sweep_starts_with_auto_make_on_worker_one_before_the_pending_count_and_a_failure_never_stops_the_sweep():
    """Owner decision 2026-10-14, "the studio makes them": `studio drop auto-make` asks for the clip of every coming slot. It runs before
    the pending count (what it asks for is counted, so the same sweep installs ffmpeg and makes it), on the first matrix entry only, and
    only for a sweep (never for a dispatched pick or the key check)."""
    blocks = steps("studio-drop")
    heads = [b.splitlines()[0] for b in blocks]
    auto = blocks[heads.index("name: Make for the coming slots")]
    assert heads.index("name: Make for the coming slots") < heads.index("name: Anything pending")
    assert GATE.split(" == ")[0] in auto and "steps.job.outputs.command == 'sweep'" in auto
    assert "strategy.job-index == 0" in auto  # worker 1 only: two runs of it would only repeat each other
    assert "uv run studio drop auto-make" in auto and "--dry-run" not in auto
    assert "if ! uv run studio drop auto-make; then" in auto and "::error" in auto  # an annotation, and the sweep goes on
    assert "ffmpeg" not in auto  # it needs no media tools: the early stop of an idle sweep still saves the install
    t = text("studio-drop")
    assert t.count("studio drop auto-make") >= 2 and "Auto-make (owner decision 2026-10-14" in t  # described in the header comment


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
        if block.startswith("name: Make for the coming slots"):  # auto-make: the database, and Higgsfield's free balance read
            assert names == {"DATABASE_URL", "HF_KEY", "HF_API_KEY_ID", "HF_API_KEY_SECRET"}, names
            continue
        assert names <= {"DATABASE_URL", "SCRAPECREATORS_API_KEY"}, block[:60]  # the pending count: the database, and the key
    pending = next(b for b in blocks if b.startswith("name: Anything pending"))
    # the count sees the key as the sweep does: a waiting auto-filed link counts only while the day's downloads allow
    assert set(re.findall(r"secrets\.([A-Z_]+)", pending)) == {"DATABASE_URL", "SCRAPECREATORS_API_KEY"}
    assert "env:" not in text("studio-drop").split("    steps:")[0].split("jobs:")[1]
    assert set(re.findall(r"secrets\.([A-Z_]+)", text("studio-drop"))) == set(DROP_SECRETS)


# ---- publish: started by the database timer (migration 0014), with GitHub's own schedule as the fallback ------------------------


def test_publish_is_started_by_the_database_timers_dispatch_and_keeps_the_schedule_as_the_fallback():
    """GitHub's scheduler skipped every run between 18:53 and 21:00 London on 2026-10-07 (the 19:30 post went out late): a pg_cron
    job (studio.publish_tick) sends a repository_dispatch of type `publish` when a post is due. The schedule stays."""
    t = text("publish")
    assert re.search(r"(?m)^  repository_dispatch:\n    types: \[publish\]$", t)
    assert re.search(r"(?m)^  workflow_dispatch:", t)
    assert re.findall(r"- cron: '([^']+)'", t) == list(SPEC["publish"][0])  # the fallback is unchanged
    # the dispatch and the schedule share the one non-cancelling group: they never post in parallel
    assert re.search(r"(?m)^concurrency:\n  group: publish\n  cancel-in-progress: false$", t)
    # the event type is the one the migration's dispatch_publish() sends
    migration = (Path(__file__).resolve().parents[1] / "supabase" / "migrations" / "0014_publish_timer.sql").read_text(encoding="utf-8")
    assert "jsonb_build_object('event_type', 'publish')" in migration
    # a dispatch carries no payload the job needs: the command is the same for every trigger and nothing reads client_payload
    assert "client_payload" not in "\n".join(line for line in t.splitlines() if not line.lstrip().startswith("#"))


# ---- publish and metrics: `studio publish confirm` (did Postiz really publish what it accepted?) ----------------------------


def test_publish_confirms_after_publishing_even_when_the_publish_step_did_nothing_or_failed():
    """A post is `posted` once Postiz accepts it and Postiz can still fail (Franz, 2026-10-13: state ERROR): the confirm step runs
    last, with always(), so it also runs after a failed or empty publish step. It is not continue-on-error: a failed database
    write must show. A Postiz hiccup exits 0 on its own."""
    blocks = steps("publish")
    confirm = blocks[-1]
    assert confirm.startswith("name: Confirm what Postiz published") and GATE_ALWAYS in confirm
    assert f"run: {CONFIRM}" in confirm and "continue-on-error" not in confirm
    assert text("publish").index("run: uv run studio publish due") < text("publish").index(f"run: {CONFIRM}")
    assert text("publish").count(f"run: {CONFIRM}") == 1
    install = f"run: npm i -g postiz@{POSTIZ_VERSION}"
    assert text("publish").index(install) < text("publish").index(f"run: {CONFIRM}")  # the Postiz CLI is there first


def test_metrics_confirms_before_pulling_and_never_fails_the_job_for_it():
    blocks = steps("metrics")
    confirm, pull = blocks[-3], blocks[-1]
    assert confirm.startswith("name: Confirm what Postiz published") and f"run: {CONFIRM}" in confirm
    assert GATE in confirm and "continue-on-error: true" in confirm
    assert "run: uv run studio metrics pull" in pull
    assert text("metrics").count(f"run: {CONFIRM}") == 1
    assert text("metrics").index(f"npm i -g postiz@{POSTIZ_VERSION}") < text("metrics").index(f"run: {CONFIRM}")


def test_metrics_re_shares_a_story_between_the_confirm_and_the_pull_and_never_fails_the_job_for_it():
    """Owner 2026-10-14: once per London day per account the best recent Reel is shown again as a Story. It runs after the confirm
    (which is what puts a url on a live Reel, and a failed one out of the running) and before the pull, with the Postiz CLI
    installed, gated on the secrets, and with continue-on-error: a Postiz hiccup must never turn the metrics job red."""
    blocks = steps("metrics")
    confirm, reshare, pull = blocks[-3], blocks[-2], blocks[-1]
    assert confirm.startswith("name: Confirm what Postiz published") and "run: uv run studio metrics pull" in pull
    assert reshare.startswith("name: Re-share the best recent Reel as a Story")
    assert f"run: {RESHARE}" in reshare and GATE in reshare and "continue-on-error: true" in reshare
    assert "--dry-run" not in reshare  # it really posts
    t = text("metrics")
    assert t.count(f"run: {RESHARE}") == 1
    assert t.index(f"run: {CONFIRM}") < t.index(f"run: {RESHARE}") < t.index("run: uv run studio metrics pull")
    assert t.index(f"npm i -g postiz@{POSTIZ_VERSION}") < t.index(f"run: {RESHARE}")
    assert "studio publish reshare" in t.split("name: metrics")[0]  # the header comment says what the step is for


# ---- studio-hits: the cloud hits job (terminal v3 spec section 10, plan Task 6) ------------------------------------------------------

HITS_SECRETS = {"DATABASE_URL", "SUPABASE_URL", "SUPABASE_SERVICE_KEY", "SCRAPECREATORS_API_KEY", "LUNARCRUSH_API_KEY"}


def hits_job(job: str) -> str:
    """One job of studio-hits.yml, as raw text (from its `  <job>:` line to the next job or the end)."""
    body = text("studio-hits").split("\njobs:\n", 1)[1]
    parts = re.split(r"(?m)^  (?=[a-z]+:$)", body)
    return next(p for p in parts if p.startswith(f"{job}:"))


def hits_steps(job: str) -> list[str]:
    body = hits_job(job).split("    steps:\n", 1)[1]
    return [b for b in re.split(r"(?m)^      - ", body) if b.strip()]


def hits_step(name: str) -> str:
    return next(b for job in ("hits", "wake") for b in hits_steps(job) if b.startswith(f"name: {name}"))


def test_hits_runs_daily_at_0530_utc_and_by_hand_one_run_at_a_time():
    t = text("studio-hits")
    assert re.search(r"(?m)^name: studio-hits$", t)
    assert re.findall(r"- cron: '([^']+)'", t) == ["30 5 * * *"]  # 06:30 London in BST, 05:30 in GMT
    assert "06:30 London" in t and "GMT" in t  # the winter shift is written down
    assert re.search(r"(?m)^  workflow_dispatch:$", t) and "repository_dispatch" not in t
    assert re.search(r"(?m)^concurrency:\n  group: studio-hits\n  cancel-in-progress: false$", t)
    assert re.search(r"(?m)^permissions:\n  contents: read\n\njobs:", t)  # the workflow itself writes nothing
    assert re.findall(r"(?m)^  ([a-z]+):$", t.split("\njobs:\n", 1)[1]) == ["hits", "wake"]
    assert re.search(r"(?m)^    runs-on: ubuntu-24\.04$", hits_job("hits")) and "astral-sh/setup-uv@" in hits_job("hits")


def test_only_the_wake_job_may_start_a_workflow_and_it_has_nothing_else():
    hits, wake = hits_job("hits"), hits_job("wake")
    assert "permissions:" not in hits and "actions: write" not in hits  # the job with the secrets: contents read only
    assert re.search(r"(?m)^    permissions:\n      actions: write\n    steps:", wake)  # its whole token: start a workflow
    assert re.search(r"(?m)^    needs: hits$", wake)
    assert "if: ${{ !cancelled() && needs.hits.outputs.filed != '' && needs.hits.outputs.filed != '0' }}" in wake
    assert "filed: ${{ steps.pull.outputs.filed }}" in hits  # the pull's count reaches the wake job
    assert "checkout" not in wake and "secrets." not in wake and "setup-uv" not in wake
    (step,) = hits_steps("wake")
    assert step.startswith("name: Wake the drop sweep") and "run: gh workflow run studio-drop.yml -f job=sweep" in step
    assert "GH_TOKEN: ${{ github.token }}" in step and "GH_REPO: ${{ github.repository }}" in step


def test_hits_is_gated_on_the_database_secret_and_its_checkout_keeps_no_credentials():
    blocks = hits_steps("hits")
    gate, rest = blocks[0], blocks[1:]
    assert "id: gate" in gate and '[ -z "${DATABASE_URL:-}" ]' in gate and "exit 1" not in gate
    assert 'echo "secrets not configured — skipping"' in gate
    assert rest and all("steps.gate.outputs.configured == 'true'" in b for b in rest)
    checkout = next(b for b in blocks if b.startswith("uses: actions/checkout@"))
    assert re.search(r"(?m)^        with:\n          persist-credentials: false$", checkout)


def test_hits_pulls_files_then_deletes_unused_clips():
    pull = hits_step("Pull the hits")
    assert "id: pull" in pull and "uv run studio hits pull" in pull
    assert "SCRAPECREATORS_API_KEY" in pull and "::notice::" in pull  # a missing key is a notice, never a failure
    assert "LUNARCRUSH_API_KEY: ${{ secrets.LUNARCRUSH_API_KEY }}" in pull  # the trend gate's key: this step only
    assert re.search(r'if \[ -z "\$\{LUNARCRUSH_API_KEY:-\}" \]; then\n\s+echo "::notice::LUNARCRUSH_API_KEY is not set', pull)
    assert "echo \"filed=$(jq '.filed | length'" in pull
    purge = hits_step("Delete the clips nobody used")
    assert "run: uv run studio source purge --stale" in purge
    assert "!cancelled()" in purge  # retention runs even when the pull failed
    names = [b.split("\n", 1)[0] for b in hits_steps("hits") if b.startswith("name: ")]
    assert names == ["name: Check secrets", "name: Pull the hits and file the best", "name: Delete the clips nobody used"]
    for job in ("hits", "wake"):
        for block in hits_steps(job):
            run = block.split("run:", 1)[1] if "run:" in block else ""
            assert "${{" not in run, block[:60]  # nothing reaches a script but through env


def test_the_lunarcrush_key_reaches_the_pull_step_only_and_the_header_explains_the_gate():
    t = text("studio-hits")
    assert t.count("secrets.LUNARCRUSH_API_KEY") == 1 and "LUNARCRUSH_API_KEY" in hits_step("Pull the hits")
    assert "LUNARCRUSH_API_KEY" not in hits_step("Delete the clips nobody used") and "LUNARCRUSH_API_KEY" not in hits_job("wake")
    header = t.split("\nname: studio-hits", 1)[0]
    for phrase in ("gh secret set LUNARCRUSH_API_KEY", "the owner pastes it", "without it the trend gate is off", "auto_file_max_waiting",
                   "lunar-probe"):
        assert phrase in header, phrase


def test_hits_secrets_reach_only_the_steps_that_need_them():
    t = text("studio-hits")
    assert set(re.findall(r"secrets\.([A-Z_]+)", t)) == HITS_SECRETS and "POSTIZ" not in t and "HF_" not in t and "GEMINI" not in t
    for job in ("hits", "wake"):
        assert "env:" not in hits_job(job).split("    steps:")[0]  # no job-level env
    assert "env:" not in t.split("\njobs:\n")[0]  # no workflow-level env
    pull, purge = hits_step("Pull the hits"), hits_step("Delete the clips nobody used")
    assert set(re.findall(r"secrets\.([A-Z_]+)", pull)) == {"DATABASE_URL", "SCRAPECREATORS_API_KEY", "LUNARCRUSH_API_KEY"}
    assert set(re.findall(r"secrets\.([A-Z_]+)", purge)) == {"DATABASE_URL", "SUPABASE_URL", "SUPABASE_SERVICE_KEY"}
    for block in hits_steps("hits"):
        if block.startswith("uses:"):
            assert "secrets." not in block


# ---- studio-weekly: the weekly review in the cloud (learning plan build item 10, Task 16) -------------------------------------------------


def weekly_job(job: str) -> str:
    """One job of studio-weekly.yml, as raw text (from its `  <job>:` line to the next job or the end)."""
    body = text("studio-weekly").split("\njobs:\n", 1)[1]
    parts = re.split(r"(?m)^  (?=[a-z]+:$)", body)
    return next(p for p in parts if p.startswith(f"{job}:"))


def weekly_steps(job: str) -> list[str]:
    body = weekly_job(job).split("    steps:\n", 1)[1]
    return [b for b in re.split(r"(?m)^      - ", body) if b.strip()]


def weekly_step(name: str) -> str:
    return next(b for job in ("review", "propose", "confirm") for b in weekly_steps(job) if b.startswith(f"name: {name}"))


def test_weekly_runs_on_monday_morning_utc_and_by_hand_with_an_optional_week_one_run_at_a_time():
    t = text("studio-weekly")
    assert re.search(r"(?m)^name: studio-weekly$", t)
    assert re.findall(r"- cron: '([^']+)'", t) == ["15 6 * * 1"]  # Monday 06:15 UTC
    assert "07:15 London in British Summer Time" in t and "GMT" in t  # the winter shift is written down
    dispatch = t.split("  workflow_dispatch:\n", 1)[1].split("\nconcurrency:", 1)[0]
    assert re.search(r"(?m)^      week:\n        description: .*\n        required: false\n        default: ''$", dispatch)
    assert "repository_dispatch" not in t
    assert re.search(r"(?m)^concurrency:\n  group: studio-weekly\n  cancel-in-progress: false$", t)
    assert re.search(r"(?m)^permissions:\n  contents: read\n\njobs:", t)  # the workflow itself writes nothing
    assert re.findall(r"(?m)^  ([a-z]+):$", t.split("\njobs:\n", 1)[1]) == ["review", "propose", "confirm"]
    assert re.search(r"(?m)^    runs-on: ubuntu-24\.04$", weekly_job("review")) and "astral-sh/setup-uv@" in weekly_job("review")


def test_weekly_review_job_is_gated_on_the_database_secret_and_its_checkout_keeps_no_credentials():
    blocks = weekly_steps("review")
    gate, rest = blocks[0], blocks[1:]
    assert "id: gate" in gate and '[ -z "${DATABASE_URL:-}" ]' in gate and "exit 1" not in gate
    assert 'echo "secrets not configured — skipping"' in gate
    assert rest and all("steps.gate.outputs.configured == 'true'" in b for b in rest)
    checkout = next(b for b in blocks if b.startswith("uses: actions/checkout@"))
    assert re.search(r"(?m)^        with:\n          persist-credentials: false$", checkout)
    assert "permissions:" not in weekly_job("review")  # the job with the secret: contents read only (the workflow's)


def test_weekly_review_runs_the_command_into_weekly_out_and_says_whether_there_is_anything_to_propose():
    review = weekly_step("Review the week")
    assert "id: review" in review and "uv run studio review weekly --out-dir weekly-out" in review
    assert "WEEK: ${{ inputs.week }}" in review and '--week "$WEEK"' in review  # the input reaches the script only through env
    assert "find weekly-out -type f" in review and 'echo "propose=true" >> "$GITHUB_OUTPUT"' in review and 'echo "propose=false" >> "$GITHUB_OUTPUT"' in review
    assert "propose: ${{ steps.review.outputs.propose }}" in weekly_job("review")
    upload = weekly_step("Keep the proposal files")
    assert "steps.review.outputs.propose == 'true'" in upload and "uses: actions/upload-artifact@" in upload
    assert "name: weekly-out" in upload and "path: weekly-out" in upload and "secrets." not in upload
    for job in ("review", "propose", "confirm"):
        for block in weekly_steps(job):
            run = block.split("run:", 1)[1] if "run:" in block else ""
            assert "${{" not in run, block[:60]  # nothing reaches a script but through env


def test_weekly_secret_reaches_only_the_gate_the_review_step_and_the_link_step():
    t = text("studio-weekly")
    assert set(re.findall(r"secrets\.([A-Z_]+)", t)) == {"DATABASE_URL"}  # not even the Supabase keys: the review reads the database only
    assert "env:" not in t.split("\njobs:\n")[0]  # no workflow-level env
    for job in ("review", "propose", "confirm"):
        assert "env:" not in weekly_job(job).split("    steps:")[0]  # no job-level env
    holders = [b.split("\n", 1)[0] for job in ("review", "propose", "confirm") for b in weekly_steps(job) if "secrets." in b]
    assert holders == ["name: Check secrets", "name: Review the week", "name: Record the proposal link"]
    for block in weekly_steps("review"):
        if block.startswith("uses:"):
            assert "secrets." not in block


def test_only_the_propose_job_may_write_and_it_has_no_secret_and_no_database():
    propose = weekly_job("propose")
    assert re.search(r"(?m)^    needs: review$", propose)
    assert "if: ${{ !cancelled() && needs.review.outputs.propose == 'true' }}" in propose
    assert re.search(r"(?m)^    permissions:\n      contents: write\n      pull-requests: write\n    steps:", propose)  # its whole token
    assert "secrets." not in propose and "DATABASE_URL" not in propose and "setup-uv" not in propose and "uv run" not in propose
    names = [b.split("\n", 1)[0] for b in weekly_steps("propose")]
    assert names[:2] == ["uses: actions/checkout@v4", "uses: actions/download-artifact@v4"] and names[2] == "name: Open the pull request"
    assert re.search(r"(?m)^        with:\n          ref: build/slice1$", weekly_steps("propose")[0])  # the PR is made against the working branch
    assert "name: weekly-out" in weekly_steps("propose")[1]


def test_weekly_propose_commits_as_the_bot_on_a_branch_per_week_and_opens_the_pull_request_with_the_digest():
    step = weekly_step("Open the pull request")
    assert "GH_TOKEN: ${{ github.token }}" in step and "GH_REPO: ${{ github.repository }}" in step
    assert 'git config user.name "github-actions[bot]"' in step and "41898282+github-actions[bot]@users.noreply.github.com" in step
    assert 'branch="weekly/$monday"' in step and 'git checkout -B "$branch"' in step
    assert "cp -R weekly-out/. ." in step and "git add docs/weekly" in step
    assert 'gh pr create --base build/slice1 --head "$branch"' in step and '--body-file "docs/weekly/$monday.md"' in step
    assert "git push origin main" not in step and "--base main" not in step


def test_weekly_propose_stages_only_the_playbooks_and_the_weekly_doc():
    step = weekly_step("Open the pull request")
    assert "git add docs/weekly" in step and "git add characters/*/playbook.md" in step
    assert not re.search(r"git add (-A|--all|\.|characters)(\s|$)", step)  # nothing else the artifact might carry reaches the commit


def test_weekly_propose_does_not_fail_on_a_rerun_with_nothing_new_to_commit():
    step = weekly_step("Open the pull request")
    assert 'git diff --cached --quiet || git commit -m "chore: weekly review $monday (playbooks and proposals)"' in step
    assert not re.search(r"(?m)^\s*git commit ", step)  # a bare commit exits 1 when the files equal the base


def test_weekly_propose_pushes_with_a_lease_after_a_fetch_not_a_blind_force():
    step = weekly_step("Open the pull request")
    assert 'git fetch origin "+refs/heads/$branch:refs/remotes/origin/$branch"' in step
    assert 'git push --force-with-lease origin "$branch"' in step
    assert "--force origin" not in step
    assert step.index("git fetch origin") < step.index("git push --force-with-lease")


def test_weekly_propose_updates_the_body_of_a_pull_request_that_is_already_open():
    step = weekly_step("Open the pull request")
    assert 'gh pr list --head "$branch"' in step and "--state open" in step
    assert 'gh pr edit "$open_pr" --body-file "docs/weekly/$monday.md"' in step
    assert step.index("gh pr edit") < step.index("gh pr create")  # an open one is edited, a missing one is created
    assert "setting off or PR already open" in step.split("gh pr create", 1)[1]


def test_weekly_a_refused_pull_request_prints_the_compare_link_and_the_job_still_passes():
    step = weekly_step("Open the pull request")
    after = step.split("gh pr create", 1)[1]
    assert "else" in after and "compare/build/slice1...${branch}?expand=1" in step  # the same address the digest's proposal_url holds
    assert '>> "$GITHUB_STEP_SUMMARY"' in after and "exit 1" not in after and "exit 1" not in step
    from studio import weekly as weekly_module

    assert weekly_module.proposal_url(date(2026, 10, 12)) == "https://github.com/oschwend-prog/character-studio/compare/build/slice1...weekly/2026-10-12?expand=1"


# ---- studio-weekly: superseded weekly/* branches (Task 16 parked, Task 20) -----------------------------------------------------------------


def run_block(step: str) -> str:
    """The `run: |` script of a step, dedented as bash sees it."""
    body = step.split("run: |\n", 1)[1]
    lines = body.split("\n")
    return "\n".join(line[10:] if line.startswith("          ") else line for line in lines)


def prune_function(step: str) -> str:
    found = re.search(r"(?ms)^prune_old_weekly_branches\(\) \{\n.*?^\}\n", run_block(step))
    assert found, "the propose step has no prune_old_weekly_branches function"
    return found.group(0)


def test_weekly_propose_script_is_valid_bash():
    import subprocess

    script = run_block(weekly_step("Open the pull request"))
    done = subprocess.run(["bash", "-n"], input=script, capture_output=True, text=True, check=False)
    assert done.returncode == 0, done.stderr


def test_weekly_the_review_hands_its_run_id_on_and_the_link_is_recorded_only_after_the_branch_is_pushed():
    review = weekly_step("Review the week")
    assert 'jq -r \'.run_id // empty\' "$RUNNER_TEMP/weekly.json"' in review and 'echo "run_id=$run_id" >> "$GITHUB_OUTPUT"' in review
    assert "[0-9a-f]{8}-[0-9a-f]{4}" in review  # only a UUID reaches the output
    assert "run_id: ${{ steps.review.outputs.run_id }}" in weekly_job("review")
    confirm = weekly_job("confirm")
    assert re.search(r"(?m)^    needs: \[review, propose\]$", confirm)
    assert "if: ${{ !cancelled() && needs.propose.result == 'success' }}" in confirm  # a failed or skipped propose job: no link
    assert "permissions:" not in confirm and "astral-sh/setup-uv@" in confirm  # contents read only (the workflow's); no push right
    checkout = next(b for b in weekly_steps("confirm") if b.startswith("uses: actions/checkout@"))
    assert re.search(r"(?m)^        with:\n          persist-credentials: false$", checkout)
    step = weekly_step("Record the proposal link")
    assert "DATABASE_URL: ${{ secrets.DATABASE_URL }}" in step and "RUN_ID: ${{ needs.review.outputs.run_id }}" in step
    assert 'uv run studio review confirm-proposal --run-id "$RUN_ID"' in step and "${{" not in run_block(step)
    assert "git " not in run_block(step) and "gh " not in run_block(step)
    # the propose job stays the only one that writes to the repository and still has no secret
    assert "confirm-proposal" not in weekly_job("propose") and "confirm-proposal" not in weekly_job("review")


def test_weekly_propose_prunes_old_weekly_branches_after_the_push_and_touches_only_weekly_refs():
    step = weekly_step("Open the pull request")
    assert "prune_old_weekly_branches ||" in step and step.index("git push --force-with-lease") < step.index("prune_old_weekly_branches ||")
    func = prune_function(step)
    assert "refs/heads/weekly/*" in func and 'git push origin --delete "refs/heads/$old"' in func
    assert "build/slice1" not in func and "main" not in func  # the base branch is never named, let alone deleted
    assert "--force" not in func


def _prune(tmp_path, remote: list[str], *, current: str, open_prs: dict[str, str], failing: tuple[str, ...] = ()) -> list[str]:
    """Run the step's prune function in bash with `git` and `gh` replaced by loggers; the branches it asked to delete."""
    import subprocess

    log = tmp_path / "calls.log"
    log.write_text("")
    listing = "".join(f"{i:040x}\trefs/heads/{name}\n" for i, name in enumerate(remote, 1))
    answers = "\n".join(f'    "{name}") echo "{n}" ;;' for name, n in open_prs.items())
    bad = "\n".join(f'    "{name}") return 1 ;;' for name in failing)
    script = f"""
git() {{
  case "$1" in
    ls-remote) printf '%s' '{listing}' ;;
    push) echo "push $*" >> '{log}' ;;
  esac
}}
gh() {{
  head=""; while [ $# -gt 0 ]; do if [ "$1" = "--head" ]; then head="$2"; fi; shift; done
  case "$head" in
{bad}
{answers}
    *) echo 0 ;;
  esac
}}
branch='{current}'
{prune_function(weekly_step("Open the pull request"))}
prune_old_weekly_branches
"""
    done = subprocess.run(["bash", "-euo", "pipefail", "-c", script], capture_output=True, text=True, check=False)
    assert done.returncode == 0, done.stderr
    return [line.split("--delete ", 1)[1] for line in log.read_text().splitlines() if line.startswith("push ")]


WEEKLY_REMOTE = [f"weekly/2026-{m}-{d}" for m, d in (("10", "12"), ("10", "05"), ("09", "28"), ("09", "21"), ("09", "14"), ("09", "07"), ("08", "31"))]


def test_the_prune_keeps_the_newest_four_and_deletes_older_ones_without_an_open_pull_request(tmp_path):
    remote = [*WEEKLY_REMOTE, "build/slice1", "main", "weekly/notes", "weekly/2026-9-1", "claude/learning-loop-2"]
    deleted = _prune(tmp_path, remote, current="weekly/2026-10-12", open_prs={"weekly/2026-09-14": "1"})
    assert deleted == ["refs/heads/weekly/2026-09-07", "refs/heads/weekly/2026-08-31"]  # 09-14 has an open PR; the newest four stay


def test_the_prune_does_nothing_with_four_or_fewer_weekly_branches(tmp_path):
    assert _prune(tmp_path, WEEKLY_REMOTE[:4], current="weekly/2026-10-12", open_prs={}) == []


def test_the_prune_never_deletes_the_branch_pushed_in_this_run_even_when_it_is_an_old_week(tmp_path):
    deleted = _prune(tmp_path, WEEKLY_REMOTE, current="weekly/2026-08-31", open_prs={})
    assert "refs/heads/weekly/2026-08-31" not in deleted and deleted == ["refs/heads/weekly/2026-09-14", "refs/heads/weekly/2026-09-07"]


def test_the_prune_keeps_a_branch_whose_pull_requests_could_not_be_checked(tmp_path):
    deleted = _prune(tmp_path, WEEKLY_REMOTE, current="weekly/2026-10-12", open_prs={}, failing=("weekly/2026-09-07",))
    assert deleted == ["refs/heads/weekly/2026-09-14", "refs/heads/weekly/2026-08-31"]
