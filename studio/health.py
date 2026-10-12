"""The watchdog: ``studio health`` (every 3 hours, GitHub Actions) and the run log it reads (``studio run log``).

``check(store, now)`` returns the problems, one human sentence each; no problem, no output. A failing
scheduled workflow emails the owner through GitHub's own notifications, so ``studio health`` just exits 1
with the problems printed. The four checks, in this order:

1. **The daily run (only with ``--daily-run``).** Off by default since 12 Oct 2026: the owner turned the Mac's
   daily run off and the cloud jobs (hits, drop sweep, publish, metrics) do the work, so requiring a daily run
   kept the check red for good. ``check(..., daily_run=True)`` / ``studio health --daily-run`` brings it back
   (turn it on when the Mac's daily run is on again). When on, some ``runs`` row of kind ``daily`` must have
   *finished* within the last 26 h (``DAILY_MAX_AGE``, inclusive) without ending in ``error``. A run that never
   reported an end does not count, nor does one that crashed (``status='error'``: the skill logs it when a step
   crashed), so a bad night is not hidden behind its own log line for a day. ``ok`` and ``budget_stop`` both
   count: stopping on the cap is a normal outcome. Other kinds (weekly, publish, metrics) never count.
2. **Posts.** Every post in ``failed`` or ``needs_check`` is a problem of its own, named with its
   account's handle and the stored error. These never clear themselves: ``needs_check`` is a human's call
   (is the post live?) and ``failed`` ran out of attempts.
2b. **Stories** (the reach pack: a Story is not a post row, it is ``features['story']`` on its clip, ``studio.publish.base``).
   A Story still ``posting`` more than ``STORY_STALE_AFTER`` (30 minutes) after its claim (``at``; an unreadable one counts as
   old), or in ``needs_check`` (it may be live), or ``failed`` (Postiz refused it: it is not live, and had Postiz refused every
   one nobody would notice), is a problem of its own, named with the Reel's account. A Story is never sent again, so there is
   nothing to settle in the studio: the line asks the owner to look in the app (a failed one: to post it by hand if he wants
   it). It is shown while the Story could still be live, ``STORY_CHECK_WINDOW`` (24 hours, a Story's life) after its claim;
   after that there is nothing left to check and the line goes away by itself.
3. **The budget.** Credits committed this London month (settled + still reserved, ``budget.committed``)
   at or past ``CAP_WARN_PCT`` (80 %) of ``Settings.monthly_cap_credits``. Exact integer arithmetic, no
   rounding: 4,800 of 6,000 is a problem, 4,799 is not. A cap of 0 has no percentage and is not flagged.

``studio run log --kind daily|weekly|publish|metrics --status ok|budget_stop|error [--summary TEXT |
--summary-file PATH] [--details-file PATH] [--started-at ISO] [--finished-at ISO | --open]`` appends one
``runs`` row. The end defaults to now and the start to the end; a time without an offset is read as
Europe/London. The skills pass the summary through ``--summary-file`` (free text never goes through the shell).

``--details-file`` is a JSON object stored in ``runs.details`` (migration 0007): the structured numbers the
terminal's Scanner card shows. ``{"scan": {queries, outliers, picks_added, auto_approved, held, skipped,
vidiq_credits}}`` says what a scan did; ``{"vidiq_credits": n}`` is the vidIQ spend of a run that did not
scan. Known keys are type-checked (``validate_details``), others are kept as they are. There is no inline
``--details``: the details may hold text that came from a tool.

``--open`` logs a run that has started and not ended (``finished_at`` stays empty): the daily run writes
one first, so the terminal can say "Scanning now", and its closing row (same ``--started-at``, printed by
the first call) ends it. An open row never counts as a finished run for the check above, so a run that
dies without its closing row is reported exactly as a missing run is.

CLI output is JSON on stdout. Exit codes: ``health`` 0 healthy, 1 problems, 2 caller error (no
``DATABASE_URL``); ``run log`` 0 written, 2 caller error.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Annotated, Any

import typer

from studio.budget import committed, month_key
from studio.cli_support import emit, fail, open_store, parse_when, text_option
from studio.config import LONDON, now_london
from studio.models import PostStatus, Run, RunKind, RunStatus
from studio.store import Store, require_aware

DAILY_MAX_AGE = timedelta(hours=26)
STORY_STALE_AFTER = timedelta(minutes=30)  # like a post's claim (studio.publish.base.STALE_AFTER)
STORY_CHECK_WINDOW = timedelta(hours=24)  # a Story lives 24 hours: after that there is nothing on Instagram to check
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


def _story_problems(store: Store, now: datetime) -> list[str]:
    """Stories stuck in ``posting`` past ``STORY_STALE_AFTER``, in ``needs_check`` or ``failed``, while they could still be live
    (a failed one: while a Story's 24 hours are not over)."""
    handles = {a.id: a.handle for a in store.accounts()}
    problems: list[str] = []
    for clip in store.list_clips():
        marker = clip.features.get("story")
        if not isinstance(marker, dict) or marker.get("status") not in ("posting", "needs_check", "failed"):
            continue
        try:
            at = datetime.fromisoformat(str(marker.get("at")))
            at = at if at.tzinfo is not None else None
        except ValueError:
            at = None
        if at is not None and now - at > STORY_CHECK_WINDOW:
            continue
        status = marker["status"]
        if status == "posting" and at is not None and now - at <= STORY_STALE_AFTER:
            continue  # in flight: the run that claimed it is sending it
        reel = next(iter(store.list_posts(id=marker["post_id"])), None) if isinstance(marker.get("post_id"), str) else None
        handle = handles.get(reel.account_id, "an unknown account") if reel is not None else "an unknown account"
        error = " ".join(str(marker.get("error") or "").split())[:_ERROR_CHARS]
        when = f"since {_local(at)}" if at is not None else "since an unknown time"
        advice = (
            "It was not posted and is never sent again; post it by hand in the Instagram app if you want it"
            if status == "failed"
            else "Look in the Instagram app whether it is live; it is never sent again"
        )
        problems.append(f"the Story of clip {clip.id} on {handle} is {status} {when}" + (f": {error}" if error else "") + f". {advice}")
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


def check(store: Store, now: datetime, *, daily_run: bool = False) -> list[str]:
    """The problems found at ``now`` (aware), empty when all is well. Read-only.

    ``daily_run`` adds the check that a daily run finished in the last 26 h; it is off by default because the
    Mac's daily run is off (the cloud jobs do the work).
    """
    require_aware(now, "health.check(now)")
    found = [
        _daily_run_problem(store, now) if daily_run else None,
        *_post_problems(store),
        *_story_problems(store, now),
        _budget_problem(store, now),
    ]
    return [p for p in found if p is not None]


# ---- CLI -----------------------------------------------------------------------------------------


def health_command(
    daily_run: Annotated[
        bool,
        typer.Option(
            "--daily-run",
            help="Also require a daily run in the last 26 h (turn on when the Mac's daily run is on again).",
        ),
    ] = False,
) -> None:
    """Check failed posts, stuck Stories and the budget (and with --daily-run the daily run); exit 1 with the problems when any is found."""
    problems = check(open_store(), now_london(), daily_run=daily_run)
    emit({"ok": not problems, "problems": problems})
    if problems:
        raise typer.Exit(1)


SCAN_COUNTERS = ("outliers", "picks_added", "auto_approved", "held", "skipped", "vidiq_credits")


def _count(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def validate_details(details: Any) -> dict[str, Any]:
    """``details`` as the object ``runs.details`` takes; ``ValueError`` names what the Scanner card could not read.

    ``scan`` (when present) is an object whose counters are whole numbers of 0 or more and whose ``queries``
    is a list of strings; a top-level ``vidiq_credits`` is a count too. Anything else is kept untouched.
    """
    if not isinstance(details, dict):
        raise ValueError(f"details must be a JSON object, got {type(details).__name__}")
    if "vidiq_credits" in details and not _count(details["vidiq_credits"]):
        raise ValueError(f"details.vidiq_credits must be a whole number of 0 or more, got {details['vidiq_credits']!r}")
    if "scan" in details:
        scan = details["scan"]
        if not isinstance(scan, dict):
            raise ValueError(f"details.scan must be an object, got {scan!r}")
        queries = scan.get("queries", [])
        if not isinstance(queries, list) or not all(isinstance(q, str) for q in queries):
            raise ValueError("details.scan.queries must be a list of strings")
        for key in SCAN_COUNTERS:
            if key in scan and not _count(scan[key]):
                raise ValueError(f"details.scan.{key} must be a whole number of 0 or more, got {scan[key]!r}")
    return details


def _read_details(file: Path | None) -> dict[str, Any]:
    if file is None:
        return {}
    text = text_option(None, file, "details") or ""
    try:
        return validate_details(json.loads(text))
    except json.JSONDecodeError as e:
        fail(f"--details-file {file} is not valid JSON: {e}")
    except ValueError as e:
        fail(str(e))


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
    details_file: Annotated[
        Path | None,
        typer.Option(
            "--details-file",
            help='A JSON object of structured numbers, e.g. {"scan": {"outliers": 9, "picks_added": 4}} (a file, never inline).',
        ),
    ] = None,
    started_at: Annotated[
        str | None, typer.Option("--started-at", help="ISO 8601 start (default: now; no offset = London).")
    ] = None,
    finished_at: Annotated[
        str | None, typer.Option("--finished-at", help="ISO 8601 end (default: now; no offset = London).")
    ] = None,
    open_: Annotated[
        bool, typer.Option("--open", help="The run has started and not ended: no end time is stored (its closing row ends it).")
    ] = False,
) -> None:
    """Record a scheduled run (the daily-run and weekly-review skills call this last)."""
    text = text_option(summary, summary_file, "summary")
    details = _read_details(details_file)
    if open_ and finished_at is not None:
        fail("--open and --finished-at cannot be combined: an open run has no end yet")
    now = now_london()
    given_start = parse_when(started_at, "--started-at") if started_at is not None else None
    given_end = parse_when(finished_at, "--finished-at") if finished_at is not None else None
    end = None if open_ else (given_end if given_end is not None else now)
    start = given_start if given_start is not None else (now if end is None else end)  # only an end given: an instant
    if end is not None and end < start:
        fail(f"--finished-at ({end.isoformat()}) is before --started-at ({start.isoformat()})")
    emit(open_store().add_run(Run(kind=kind, status=status, started_at=start, finished_at=end, summary=text, details=details)))
