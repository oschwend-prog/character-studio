"""The watchdog: ``studio health`` (hourly, GitHub Actions) and the run log it reads (``studio run log``).

``check(store, now)`` returns the problems, one human sentence each; no problem, no output. A failing
scheduled workflow emails the owner through GitHub's own notifications, so ``studio health`` just exits 1
with the problems printed. The three checks, in this order:

1. **The daily run.** Some ``runs`` row of kind ``daily`` must have *finished* within the last 26 h
   (``DAILY_MAX_AGE``, inclusive) without ending in ``error``. A run that never reported an end does not
   count, nor does one that crashed (``status='error'``: the skill logs it when a step crashed), so a bad
   night is not hidden behind its own log line for a day. ``ok`` and ``budget_stop`` both count: stopping
   on the cap is a normal outcome. Other kinds (weekly, publish, metrics) never count.
2. **Posts.** Every post in ``failed`` or ``needs_check`` is a problem of its own, named with its
   account's handle and the stored error. These never clear themselves: ``needs_check`` is a human's call
   (is the post live?) and ``failed`` ran out of attempts.
3. **The budget.** Credits committed this London month (settled + still reserved, ``budget.committed``)
   at or past ``CAP_WARN_PCT`` (80 %) of ``Settings.monthly_cap_credits``. Exact integer arithmetic, no
   rounding: 4,800 of 6,000 is a problem, 4,799 is not. A cap of 0 has no percentage and is not flagged.

``studio run log --kind daily|weekly|publish|metrics --status ok|budget_stop|error [--summary TEXT |
--summary-file PATH] [--started-at ISO] [--finished-at ISO]`` appends one ``runs`` row. The end
defaults to now and the start to the end; a time without an offset is read as Europe/London. The skills pass the summary through
``--summary-file`` (free text never goes through the shell).

CLI output is JSON on stdout. Exit codes: ``health`` 0 healthy, 1 problems, 2 caller error (no
``DATABASE_URL``); ``run log`` 0 written, 2 caller error.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Annotated

import typer

from studio.budget import committed, month_key
from studio.cli_support import emit, fail, open_store, parse_when, text_option
from studio.config import LONDON, now_london
from studio.models import PostStatus, Run, RunKind, RunStatus
from studio.store import Store, require_aware

DAILY_MAX_AGE = timedelta(hours=26)
CAP_WARN_PCT = 80
_ERROR_CHARS = 300


def _local(moment: datetime) -> str:
    return moment.astimezone(LONDON).strftime("%Y-%m-%d %H:%M")


def _daily_run_problem(store: Store, now: datetime) -> str | None:
    runs = store.list_runs(kind=RunKind.daily)
    cutoff = now - DAILY_MAX_AGE
    if any(
        r.finished_at is not None and r.finished_at >= cutoff and r.status is not RunStatus.error
        for r in runs
    ):
        return None
    if not runs:
        return "no daily run has ever been logged (the daily routine has not reported in)"
    last = max(runs, key=lambda r: r.finished_at or r.started_at)
    how = (
        f"{last.status.value} at {_local(last.finished_at)}"
        if last.finished_at is not None
        else f"started {_local(last.started_at)} and never finished"
    )
    hours = int(DAILY_MAX_AGE.total_seconds() // 3600)
    return f"no daily run finished without error in the last {hours} h (last daily run: {how})"


def _post_problems(store: Store) -> list[str]:
    handles = {a.id: a.handle for a in store.accounts()}
    problems: list[str] = []
    for status in (PostStatus.failed, PostStatus.needs_check):
        for post in store.list_posts(status=status):
            error = " ".join((post.error or "").split())[:_ERROR_CHARS]
            problems.append(
                f"post {post.id} on {handles.get(post.account_id, 'an unknown account')} "
                f"is {status.value}" + (f": {error}" if error else "")
            )
    return problems


def _budget_problem(store: Store, now: datetime) -> str | None:
    cap = store.get_settings().monthly_cap_credits
    month = month_key(now)
    used = committed(store, month)
    if cap > 0 and used * 100 >= cap * CAP_WARN_PCT:
        return (
            f"credits committed in {month}: {used} of {cap} ({used * 100 / cap:.0f}%), "
            f"at or past {CAP_WARN_PCT}% of the monthly cap"
        )
    return None


def check(store: Store, now: datetime) -> list[str]:
    """The problems found at ``now`` (aware), empty when all is well. Read-only."""
    require_aware(now, "health.check(now)")
    found = [_daily_run_problem(store, now), *_post_problems(store), _budget_problem(store, now)]
    return [p for p in found if p is not None]


# ---- CLI -----------------------------------------------------------------------------------------


def health_command() -> None:
    """Check the daily run, failed posts and the budget; exit 1 with the problems when any is found."""
    problems = check(open_store(), now_london())
    emit({"ok": not problems, "problems": problems})
    if problems:
        raise typer.Exit(1)


run_app = typer.Typer(
    help="The scheduled-run log: `run log` appends a line that `studio health` reads. Prints JSON.",
    no_args_is_help=True,
)


@run_app.command("log")
def log_command(
    kind: Annotated[RunKind, typer.Option(help="Which scheduled run this was.")],
    status: Annotated[RunStatus, typer.Option(help="ok, budget_stop (stopped on the cap) or error.")],
    summary: Annotated[str | None, typer.Option(help="One line of what happened.")] = None,
    summary_file: Annotated[
        Path | None, typer.Option("--summary-file", help="The summary, read from a file (use for free text).")
    ] = None,
    started_at: Annotated[
        str | None, typer.Option("--started-at", help="ISO 8601 start (default: now; no offset = London).")
    ] = None,
    finished_at: Annotated[
        str | None, typer.Option("--finished-at", help="ISO 8601 end (default: now; no offset = London).")
    ] = None,
) -> None:
    """Record a scheduled run (the daily-run and weekly-review skills call this last)."""
    text = text_option(summary, summary_file, "summary")
    now = now_london()
    given_start = parse_when(started_at, "--started-at") if started_at is not None else None
    given_end = parse_when(finished_at, "--finished-at") if finished_at is not None else None
    end = given_end if given_end is not None else now
    start = given_start if given_start is not None else end  # only an end given: an instant, not a negative span
    if end < start:
        fail(f"--finished-at ({end.isoformat()}) is before --started-at ({start.isoformat()})")
    emit(open_store().add_run(Run(kind=kind, status=status, started_at=start, finished_at=end, summary=text)))
