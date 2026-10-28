"""``studio health`` and ``studio run log``: the hourly watchdog and the run log it reads."""

import json
from datetime import datetime, timedelta, timezone

import pytest
from typer.testing import CliRunner

from studio import health
from studio.cli import app
from studio.config import LONDON
from studio.health import CAP_WARN_PCT, DAILY_MAX_AGE, check
from studio.models import (
    Account,
    Character,
    Clip,
    Favorite,
    LedgerEntry,
    Mode,
    Platform,
    Post,
    PostStatus,
    Run,
    Settings,
)
from studio.store import MemoryStore

NOW = datetime(2026, 10, 7, 12, 0, tzinfo=LONDON)
MONTH = "2026-10"


def bare() -> MemoryStore:
    """Biscuit with a TikTok account; nothing logged, nothing spent."""
    return MemoryStore(
        characters=[Character(slug="biscuit", name="Biscuit")],
        accounts=[Account(character_slug="biscuit", platform=Platform.tiktok, handle="@biscuit")],
    )


def fresh() -> MemoryStore:
    """``bare()`` plus a healthy daily run an hour ago."""
    store = bare()
    store.add_run(Run(kind="daily", status="ok", started_at=NOW - timedelta(hours=2), finished_at=NOW - timedelta(hours=1)))
    return store


def daily(store: MemoryStore, *, ago: timedelta, status: str = "ok", finished: bool = True) -> None:
    done = NOW - ago
    store.add_run(
        Run(kind="daily", status=status, started_at=done - timedelta(minutes=30), finished_at=done if finished else None)
    )


def spend(store: MemoryStore, credits: int, month: str = MONTH) -> None:
    clip = store.add_clip(Clip(character_slug="biscuit", mode=Mode.recreate))
    store.ledger_add(LedgerEntry(clip_id=clip.id, month=month, kind="settle", credits=credits))


def add_post(store: MemoryStore, status: PostStatus, error: str | None = None) -> Post:
    clip = store.add_clip(Clip(character_slug="biscuit", mode=Mode.recreate))
    account = store.accounts("biscuit")[0]
    return store.add_post(
        Post(clip_id=clip.id, account_id=account.id, scheduled_for=NOW - timedelta(hours=3), status=status, error=error)
    )


# ---- the daily run ---------------------------------------------------------------------------------


def test_a_fresh_store_with_a_recent_daily_run_is_healthy():
    assert check(fresh(), NOW, daily_run=True) == []
    assert check(fresh(), NOW) == []


def test_health_flags_missing_daily_run():
    store = MemoryStore()
    problems = check(store, NOW, daily_run=True)
    assert len(problems) == 1 and "daily run" in problems[0] and "ever" in problems[0]

    daily(store, ago=timedelta(hours=26, minutes=1))  # one minute too old
    problems = check(store, NOW, daily_run=True)
    assert len(problems) == 1 and "26 h" in problems[0] and "last daily run" in problems[0]


def test_the_daily_run_is_not_required_by_default():
    """The Mac's daily run is off (12 Oct 2026): the default check no longer asks for one, however old or absent."""
    store = MemoryStore()  # no daily run ever logged
    assert check(store, NOW) == []
    daily(store, ago=timedelta(hours=40), status="error")  # a stale, crashed run is no problem either
    assert check(store, NOW) == []
    assert len(check(store, NOW, daily_run=True)) == 1  # the same store is red once the daily run is required again


def test_a_daily_run_exactly_26_hours_old_still_counts():
    store = MemoryStore()
    daily(store, ago=DAILY_MAX_AGE)
    assert check(store, NOW, daily_run=True) == []


def test_only_a_finished_daily_run_that_did_not_error_counts():
    store = MemoryStore()
    daily(store, ago=timedelta(hours=1), finished=False)  # started, never reported an end
    store.add_run(Run(kind="weekly", status="ok", finished_at=NOW - timedelta(hours=1)))  # other kinds do not count
    store.add_run(Run(kind="publish", status="ok", finished_at=NOW - timedelta(hours=1)))
    assert len(check(store, NOW, daily_run=True)) == 1

    daily(store, ago=timedelta(hours=1), status="error")  # it crashed: not a healthy day
    problems = check(store, NOW, daily_run=True)
    assert len(problems) == 1 and "error" in problems[0]

    daily(store, ago=timedelta(hours=1), status="budget_stop")  # stopping on the cap is a normal outcome
    assert check(store, NOW, daily_run=True) == []


def test_the_message_names_the_last_daily_run_when_there_was_one():
    store = MemoryStore()
    daily(store, ago=timedelta(hours=40), status="ok")
    daily(store, ago=timedelta(hours=30), status="error")
    (problem,) = check(store, NOW, daily_run=True)
    assert "error" in problem and "2026-10-06" in problem  # the newest one, with its London time


# ---- posts -----------------------------------------------------------------------------------------


def test_health_flags_needs_check():
    store = fresh()
    post = add_post(store, PostStatus.needs_check, "stuck in posting since x: not retried")
    (problem,) = check(store, NOW)
    assert post.id in problem and "@biscuit" in problem and "needs_check" in problem and "not retried" in problem


def test_health_flags_failed_posts_one_line_each():
    store = fresh()
    a = add_post(store, PostStatus.failed, "RuntimeError: boom")
    b = add_post(store, PostStatus.needs_check)
    problems = check(store, NOW)
    assert len(problems) == 2
    assert any(a.id in p and "failed" in p and "boom" in p for p in problems)
    assert any(b.id in p and "needs_check" in p for p in problems)


@pytest.mark.parametrize("status", [PostStatus.scheduled, PostStatus.posting, PostStatus.posted])
def test_ordinary_posts_are_not_problems(status):
    store = fresh()
    add_post(store, status)
    assert check(store, NOW) == []


# ---- Stories (the reach pack: a Story is a marker on its clip, features.story, never a post row) ---------------------------


def story(store: MemoryStore, status: str, ago: timedelta, **extra) -> Clip:
    """A clip whose Reel went out on Biscuit's account and whose Story is ``status``, claimed ``ago`` before NOW."""
    reel = add_post(store, PostStatus.posted)
    marker = {"post_id": reel.id, "status": status, "at": (NOW - ago).isoformat(), **extra}
    return store.update_clip(reel.clip_id, features={"story": marker})


def test_health_flags_a_story_stuck_in_posting_for_more_than_30_minutes():
    assert health.STORY_STALE_AFTER == timedelta(minutes=30)
    store = fresh()
    stuck = story(store, "posting", timedelta(minutes=31))
    story(store, "posting", timedelta(minutes=29))  # still in flight: another run is sending it
    (problem,) = check(store, NOW)
    assert stuck.id in problem and "Story" in problem and "posting" in problem and "@biscuit" in problem


def test_health_flags_a_story_that_needs_a_check():
    store = fresh()
    clip = story(store, "needs_check", timedelta(minutes=5), error="UncertainPublish: postiz posts:create timed out")
    (problem,) = check(store, NOW)
    assert clip.id in problem and "needs_check" in problem and "timed out" in problem and "never sent again" in problem


@pytest.mark.parametrize("status", ["posted", "skipped"])
def test_settled_stories_are_not_problems(status):
    store = fresh()
    story(store, status, timedelta(hours=2))
    assert check(store, NOW) == []


def test_health_flags_a_story_that_failed_while_it_could_still_have_gone_out():
    """Final review M4: a Story Postiz refused is recorded `failed`; if it refused every one, nobody would notice."""
    store = fresh()
    clip = story(store, "failed", timedelta(hours=2), error="PostizError: posts:create refused the Story (400)")
    (problem,) = check(store, NOW)
    assert clip.id in problem and "@biscuit" in problem and "failed" in problem and "refused the Story" in problem
    assert "never sent again" in problem and "live" not in problem  # nothing was posted: it is not asked whether it is live
    story(store, "failed", timedelta(hours=24, minutes=1))  # like the others, it goes away once a Story's life is over
    story(store, "failed", timedelta(minutes=1))  # a failed Story is not "in flight": flagged at once, no 30-minute grace
    assert len(check(store, NOW)) == 2


def test_a_story_older_than_its_24_hours_is_no_longer_flagged():
    """A Story lives 24 hours: after that there is nothing left on Instagram to check, and it is never sent again."""
    assert health.STORY_CHECK_WINDOW == timedelta(hours=24)
    store = fresh()
    story(store, "needs_check", timedelta(hours=24, minutes=1))
    story(store, "posting", timedelta(hours=25))
    assert check(store, NOW) == []
    story(store, "posting", timedelta(0), at="not a time")  # an unreadable claim time is flagged: nobody can tell its age
    assert len(check(store, NOW)) == 1


# ---- the monthly cap -------------------------------------------------------------------------------


def test_health_flags_80pct_cap():
    assert CAP_WARN_PCT == 80
    store = fresh()
    spend(store, 4799)  # 6000 * 0.8 = 4800
    assert check(store, NOW) == []
    spend(store, 1)
    (problem,) = check(store, NOW)
    assert "4800" in problem and "6000" in problem and "80%" in problem


def test_open_reservations_count_toward_the_cap_and_other_months_do_not():
    store = fresh()
    clip = store.add_clip(Clip(character_slug="biscuit", mode=Mode.recreate))
    store.ledger_add(LedgerEntry(clip_id=clip.id, month=MONTH, kind="reserve", credits=5000))
    assert len(check(store, NOW)) == 1  # committed = settled + still reserved

    other = fresh()
    spend(other, 5900, month="2026-09")  # last month's spend is closed history
    assert check(other, NOW) == []


def test_the_cap_comes_from_settings():
    store = fresh()
    store.set_settings(monthly_cap_credits=1000)
    spend(store, 800)
    (problem,) = check(store, NOW)
    assert "800" in problem and "1000" in problem


def test_the_month_is_the_london_month_not_the_utc_one():
    now = datetime(2026, 9, 30, 23, 30, tzinfo=timezone.utc)  # 00:30 on 1 October in London (BST)
    october, september = MemoryStore(), MemoryStore()
    for store, month in ((october, "2026-10"), (september, "2026-09")):
        store.add_run(Run(kind="daily", status="ok", finished_at=now - timedelta(hours=1)))
        spend(store, 5000, month=month)
    assert len(check(october, now)) == 1
    assert check(september, now) == []


def test_a_zero_cap_is_not_a_percentage_problem():
    store = MemoryStore(settings=Settings(monthly_cap_credits=0))
    store.add_run(Run(kind="daily", status="ok", finished_at=NOW - timedelta(hours=1)))
    assert check(store, NOW) == []


# ---- paid services out of credits (owner 2026-10-28) ----------------------------------------------


def pull_line(store: MemoryStore, *, ago: timedelta, stopped: str | None = "out_of_credits", calls: int = 0) -> None:
    """The ``hits`` run ``studio.hits.record_pull`` logs for a pull that started ``ago`` before NOW."""
    at = NOW - ago
    status = "error" if stopped == "out_of_credits" else "ok"
    pull = {"day": at.astimezone(LONDON).date().isoformat(), "calls": calls, "credits": calls, "kept": 0, "stopped": stopped,
            "errors": 1 if stopped else 0, "error": "ScrapeCreatorsError: HTTP 402" if stopped else None}  # fmt: skip
    store.add_run(Run(kind="hits", status=status, started_at=at, finished_at=at, details={"pull": pull}))


def test_health_flags_scrapecreators_out_of_credits_since_the_first_pull_it_stopped_on():
    store = fresh()
    pull_line(store, ago=timedelta(days=4), stopped=None, calls=25)  # it worked until then
    pull_line(store, ago=timedelta(days=3))
    pull_line(store, ago=timedelta(days=2))
    pull_line(store, ago=timedelta(hours=6))
    (problem,) = check(store, NOW)
    assert problem.startswith("ScrapeCreators out of credits since 2026-10-04: no hits pulled")
    assert "Top up at scrapecreators.com" in problem and "workflow run studio-hits.yml" in problem  # the one-line fix


def test_a_later_pull_that_works_clears_scrapecreators_and_a_new_stop_starts_a_new_since():
    store = fresh()
    pull_line(store, ago=timedelta(days=3))
    pull_line(store, ago=timedelta(days=2), stopped=None, calls=25)  # topped up
    assert check(store, NOW) == []
    pull_line(store, ago=timedelta(days=1))  # out again
    (problem,) = check(store, NOW)
    assert "since 2026-10-06" in problem


def test_a_pull_that_stopped_part_way_says_how_far_it_got():
    store = fresh()
    pull_line(store, ago=timedelta(hours=6), calls=3)
    (problem,) = check(store, NOW)
    assert "the last pull stopped after 3 calls" in problem and "no hits pulled" not in problem
    pull_line(store, ago=timedelta(hours=5), calls=1)
    (problem,) = check(store, NOW)
    assert "stopped after 1 call." in problem


def test_scrapecreators_is_no_problem_for_the_other_stops_the_other_lines_and_the_other_runs():
    store = fresh()
    pull_line(store, ago=timedelta(hours=6), stopped="cap", calls=25)  # the day's credit cap: normal
    pull_line(store, ago=timedelta(hours=5), stopped=None)
    store.add_run(Run(kind="hits", status="ok", started_at=NOW, details={"lunar": {"day": "2026-10-07", "calls": 4}}))  # LunarCrush bookkeeping
    store.add_run(Run(kind="hits", status="ok", started_at=NOW, details={"pull": "odd"}))
    store.add_run(Run(kind="daily", status="ok", started_at=NOW, details={"pull": {"stopped": "out_of_credits"}}))  # not the hits job's
    assert check(store, NOW) == []
    assert check(MemoryStore(), NOW) == []  # nothing logged yet (before the first pull this was recorded): no problem


def test_scrapecreators_reads_the_latest_pull_whatever_order_the_lines_were_written_in():
    store = fresh()
    pull_line(store, ago=timedelta(hours=6))  # written first, but newer than the working one
    pull_line(store, ago=timedelta(hours=30), stopped=None, calls=25)
    (problem,) = check(store, NOW)
    assert "since 2026-10-07" in problem
    pull_line(store, ago=timedelta(hours=1), stopped=None, calls=25)
    assert check(store, NOW) == []


def hf_drop(store: MemoryStore, state: str, *, ago: timedelta | None = None, **over) -> Favorite:
    """A dropped video; ``ago`` is how long before NOW the refusal stamp (``credits_refused_at``) was written, if any."""
    d = {"state": state, "kind": "file", "at": (NOW - timedelta(hours=1)).isoformat(), "reason": None, **over}
    if ago is not None:
        d["credits_refused_at"] = (NOW - ago).isoformat()
    return store.add_favorite(Favorite(
        url=f"owner-drop:{len(store.list_favorites())}", platform="drop", origin="owner", character_slug="biscuit", status="approved",
        proposal={"drop": d},
    ))  # fmt: skip


def accepted(store: MemoryStore, *, ago: timedelta, state: str = "made", request_id: str | None = "req-1") -> Favorite:
    """A make Higgsfield took: its submit was ``ago`` before NOW and it carries the request id Higgsfield answered with."""
    make = {"submitted_at": (NOW - ago).isoformat(), "request_id": request_id, "idempotency_key": "k"}
    return hf_drop(store, state, make=make)


def test_health_flags_the_higgsfield_api_wallet_empty_from_the_studios_refused_makes():
    store = fresh()
    hf_drop(store, "ready", ago=timedelta(hours=30))  # 06 Oct 06:00 London
    hf_drop(store, "ready", ago=timedelta(hours=2))
    (problem,) = check(store, NOW)
    assert problem.startswith("Higgsfield API wallet empty: 2 makes refused since 2026-10-06 06:00 (nothing was charged)")
    assert "into the API wallet, not the app wallet" in problem and "open.higgsfield.ai" in problem  # the one-line fix
    hf_drop(store, "ready", ago=timedelta(hours=3))
    (problem,) = check(store, NOW)
    assert "3 makes refused since 2026-10-06 06:00" in problem  # one problem for the service, not one per drop


def test_one_refused_make_is_singular():
    store = fresh()
    hf_drop(store, "ready", ago=timedelta(hours=2))
    (problem,) = check(store, NOW)
    assert "1 make refused since 2026-10-07 10:00" in problem


@pytest.mark.parametrize(
    "reason",
    [
        'Higgsfield refused the job: Higgsfield refused the submit: HTTP 403: {"detail": "not_enough_credits"}',
        'Higgsfield refused the job: Higgsfield refused the submit: HTTP 403: {"detail": "Insufficient credits"}',
        "Higgsfield refused the job: Higgsfield refused the submit: HTTP 403: {}",  # the status alone, as the terminal reads it
    ],
)
def test_the_owners_make_that_failed_for_credits_counts_with_its_own_time(reason):
    store = fresh()
    hf_drop(store, "failed", reason=reason, at=(NOW - timedelta(hours=5)).isoformat())
    (problem,) = check(store, NOW)
    assert "1 make refused since 2026-10-07 07:00" in problem


def test_a_failed_make_for_another_reason_is_not_a_wallet_problem():
    store = fresh()
    hf_drop(store, "failed", reason="Higgsfield refused the job: Higgsfield refused the submit: HTTP 400: bad image")
    hf_drop(store, "failed", reason="the frame check found a leftover person")
    hf_drop(store, "failed", reason="Higgsfield output download: HTTP 403")  # a signed link, not the wallet
    hf_drop(store, "ready", reason="Higgsfield said not enough credits at Wed 07 Oct 06:00")  # the card's line, with no stamp: not evidence
    assert check(store, NOW) == []


def test_a_make_higgsfield_accepted_after_the_refusals_clears_the_problem():
    store = fresh()
    hf_drop(store, "ready", ago=timedelta(hours=10))
    hf_drop(store, "failed", reason="Higgsfield refused the job: HTTP 403: not_enough_credits", at=(NOW - timedelta(hours=9)).isoformat())
    assert len(check(store, NOW)) == 1
    accepted(store, ago=timedelta(hours=8), state="making")  # the owner topped up and a submit went through
    assert check(store, NOW) == []
    hf_drop(store, "ready", ago=timedelta(hours=2))  # ... and it ran dry again later
    (problem,) = check(store, NOW)
    assert "1 make refused since 2026-10-07 10:00" in problem


def test_a_stale_stamp_on_a_drop_that_was_made_since_is_not_counted():
    """``credits_refused_at`` stays on a drop after it is made (the drop dict is merged): it is old news once a submit followed it."""
    store = fresh()
    hf_drop(store, "made", ago=timedelta(hours=20), make={"submitted_at": (NOW - timedelta(hours=10)).isoformat(), "request_id": "req-1"})
    assert check(store, NOW) == []


def test_a_make_by_hand_does_not_show_the_api_wallet_is_full():
    """The owner's by-hand makes go through the MCP (the app wallet): they carry no Higgsfield API request id and prove nothing."""
    store = fresh()
    hf_drop(store, "ready", ago=timedelta(hours=10))
    accepted(store, ago=timedelta(hours=2), request_id=None)
    accepted(store, ago=timedelta(hours=2), request_id="")
    hf_drop(store, "failed", make={"submitted_at": (NOW - timedelta(hours=2)).isoformat(), "request_id": "req-9"})  # not making/made
    (problem,) = check(store, NOW)
    assert "1 make refused" in problem


def test_a_refusal_is_news_for_48_hours():
    assert health.HF_REFUSAL_WINDOW == timedelta(hours=48)
    store = fresh()
    hf_drop(store, "ready", ago=health.HF_REFUSAL_WINDOW)
    assert len(check(store, NOW)) == 1  # exactly 48 h: still counted
    quiet = fresh()
    hf_drop(quiet, "ready", ago=health.HF_REFUSAL_WINDOW + timedelta(minutes=1))
    assert check(quiet, NOW) == []  # the newest refusal is older than that: nothing has been asked since, say nothing
    hf_drop(quiet, "ready", ago=timedelta(hours=1))
    (problem,) = check(quiet, NOW)
    assert "2 makes refused since 2026-10-05" in problem  # the old one still dates the start once there is a new one


def test_stamps_that_are_no_time_and_favorites_that_are_not_drops_are_ignored():
    store = fresh()
    hf_drop(store, "ready", credits_refused_at="yesterday")
    hf_drop(store, "ready", credits_refused_at="2026-10-07T10:00:00")  # no offset: not guessed
    hf_drop(store, "ready", credits_refused_at=12345)
    store.add_favorite(Favorite(url="https://example.test/a", platform="tiktok", proposal={"credits_refused_at": NOW.isoformat()}))
    store.add_favorite(Favorite(url="https://example.test/b", platform="tiktok", proposal={"drop": "odd"}))
    store.add_favorite(Favorite(url="https://example.test/c", platform="tiktok", proposal={"drop": {"state": "making", "make": "odd"}}))
    assert check(store, NOW) == []


def test_the_health_check_reads_what_the_drop_code_really_writes_for_a_credits_refusal():
    """Not a hand-made dict: ``drop._refused_for_credits`` (the studio's make) and ``drop._give_up`` (the owner's Make it)."""
    from studio import drop
    from studio.higgsfield_api import HiggsfieldError

    refusal = HiggsfieldError('Higgsfield refused the submit: HTTP 403: {"detail": "Insufficient credits"}', 403)
    store = fresh()
    studio, owner = (
        store.add_favorite(Favorite(
            url=f"owner-drop:{who}", platform="drop", origin="owner", character_slug="biscuit", status="approved",
            proposal={"make_requested": {"at": NOW.isoformat(), "by": who}, "drop": {"state": "making", "make": {"idempotency_key": "k"}}},
        ))  # fmt: skip
        for who in ("studio", "owner")
    )
    clip = store.add_clip(Clip(character_slug="biscuit", mode=Mode.recreate))
    drop._refused_for_credits(store, studio, clip, NOW - timedelta(hours=3), refusal)
    (problem,) = check(store, NOW)
    assert "1 make refused since 2026-10-07 09:00" in problem
    drop._give_up(store, owner, clip, NOW - timedelta(hours=2), f"Higgsfield refused the job: {refusal}")
    (problem,) = check(store, NOW)
    assert "2 makes refused since 2026-10-07 09:00" in problem


def test_each_service_out_of_credits_is_its_own_problem_after_the_budget():
    store = fresh()
    spend(store, 6000)
    pull_line(store, ago=timedelta(hours=6))
    hf_drop(store, "ready", ago=timedelta(hours=2))
    problems = check(store, NOW)
    assert [("credits committed" in p, "ScrapeCreators" in p, "Higgsfield" in p) for p in problems] == [
        (True, False, False), (False, True, False), (False, False, True),
    ]


def test_problems_come_in_a_stable_order_and_check_refuses_a_naive_now():
    store = bare()
    spend(store, 6000)
    add_post(store, PostStatus.failed)
    problems = check(store, NOW, daily_run=True)
    assert [("daily run" in p, "post " in p, "credits" in p) for p in problems] == [
        (True, False, False), (False, True, False), (False, False, True),
    ]
    assert [("daily run" in p, "post " in p, "credits" in p) for p in check(store, NOW)] == [
        (False, True, False), (False, False, True),  # without --daily-run the same order, minus the daily run
    ]
    with pytest.raises(ValueError, match="timezone-aware"):
        check(store, datetime(2026, 10, 7, 12, 0))


# ---- the CLI ---------------------------------------------------------------------------------------


@pytest.fixture
def cli_store(monkeypatch):
    store = fresh()
    monkeypatch.setattr(health, "open_store", lambda: store)
    return store


def run(*args: str):
    return CliRunner().invoke(app, list(args))


def test_cli_health_prints_json_and_exits_0_when_healthy(cli_store, monkeypatch):
    monkeypatch.setattr(health, "now_london", lambda: NOW)
    r = run("health")
    assert r.exit_code == 0, r.output
    assert json.loads(r.stdout) == {"ok": True, "problems": []}


def test_cli_health_prints_the_problems_and_exits_1(cli_store, monkeypatch):
    monkeypatch.setattr(health, "now_london", lambda: NOW)
    add_post(cli_store, PostStatus.needs_check, "check it")
    r = run("health")
    assert r.exit_code == 1
    out = json.loads(r.stdout)
    assert out["ok"] is False and len(out["problems"]) == 1 and "needs_check" in out["problems"][0]


def test_cli_health_exits_1_naming_each_service_out_of_credits(cli_store, monkeypatch):
    """The two silent failures of 11-28 Oct: every job green, health ok. Now `studio health` is red with one line per service."""
    monkeypatch.setattr(health, "now_london", lambda: NOW)
    pull_line(cli_store, ago=timedelta(hours=6))
    hf_drop(cli_store, "ready", ago=timedelta(hours=2))
    r = run("health")
    assert r.exit_code == 1
    out = json.loads(r.stdout)
    assert out["ok"] is False and len(out["problems"]) == 2
    assert out["problems"][0].startswith("ScrapeCreators out of credits since 2026-10-07: no hits pulled")
    assert out["problems"][1].startswith("Higgsfield API wallet empty: 1 make refused since 2026-10-07 10:00")


def test_cli_health_does_not_require_a_daily_run_by_default(monkeypatch):
    store = MemoryStore()  # no daily run ever logged
    monkeypatch.setattr(health, "open_store", lambda: store)
    monkeypatch.setattr(health, "now_london", lambda: NOW)
    r = run("health")
    assert r.exit_code == 0, r.output
    assert json.loads(r.stdout) == {"ok": True, "problems": []}


def test_cli_health_daily_run_flag_requires_a_daily_run(monkeypatch):
    store = MemoryStore()  # the same store as above: no daily run ever logged
    monkeypatch.setattr(health, "open_store", lambda: store)
    monkeypatch.setattr(health, "now_london", lambda: NOW)
    r = run("health", "--daily-run")
    assert r.exit_code == 1
    out = json.loads(r.stdout)
    assert out["ok"] is False and len(out["problems"]) == 1 and "daily run" in out["problems"][0]
    daily(store, ago=timedelta(hours=1))
    assert run("health", "--daily-run").exit_code == 0  # a finished daily run satisfies it


def test_cli_health_without_a_database_exits_2(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    r = run("health")
    assert r.exit_code == 2 and "DATABASE_URL" in r.output


# ---- studio run log --------------------------------------------------------------------------------


def test_run_log_writes_a_row_stamped_now(cli_store, monkeypatch):
    monkeypatch.setattr(health, "now_london", lambda: NOW)
    r = run("run", "log", "--kind", "weekly", "--status", "ok", "--summary", "biscuit: not_yet")
    assert r.exit_code == 0, r.output
    (row,) = cli_store.list_runs(kind="weekly")
    assert (row.status.value, row.summary, row.started_at, row.finished_at) == ("ok", "biscuit: not_yet", NOW, NOW)
    out = json.loads(r.stdout)
    assert (out["id"], out["kind"], out["status"]) == (row.id, "weekly", "ok")


def test_run_log_summary_from_a_file_is_taken_literally(cli_store, tmp_path):
    f = tmp_path / "s.md"
    nasty = "it's $(echo pwned) `x` \"q\" ; && | > \U0001F499\nline two"
    f.write_text(nasty + "\n", encoding="utf-8")
    r = run("run", "log", "--kind", "daily", "--status", "budget_stop", "--summary-file", str(f))
    assert r.exit_code == 0, r.output
    (row,) = cli_store.list_runs(kind="daily", status="budget_stop")
    assert row.summary == nasty


def test_run_log_refuses_both_summary_forms_a_missing_file_and_bad_values(cli_store, tmp_path):
    f = tmp_path / "s.md"
    f.write_text("x")
    both = run("run", "log", "--kind", "daily", "--status", "ok", "--summary", "a", "--summary-file", str(f))
    assert both.exit_code == 2 and "--summary" in both.output
    missing = run("run", "log", "--kind", "daily", "--status", "ok", "--summary-file", str(tmp_path / "no"))
    assert missing.exit_code == 2 and "no such file" in missing.output
    assert run("run", "log", "--kind", "hourly", "--status", "ok").exit_code == 2
    assert run("run", "log", "--kind", "daily", "--status", "fine").exit_code == 2
    assert run("run", "log", "--kind", "daily").exit_code == 2  # --status is required
    assert cli_store.list_runs(kind="weekly") == [] and len(cli_store.list_runs()) == 1  # only the seeded daily run


def test_run_log_started_and_finished_can_be_given(cli_store):
    r = run(
        "run", "log", "--kind", "metrics", "--status", "error",
        "--started-at", "2026-10-07T03:00:00+00:00", "--finished-at", "2026-10-07T03:07:00+00:00",
    )
    assert r.exit_code == 0, r.output
    (row,) = cli_store.list_runs(kind="metrics")
    assert row.started_at == datetime(2026, 10, 7, 3, 0, tzinfo=timezone.utc)
    assert row.finished_at - row.started_at == timedelta(minutes=7)


def test_run_log_refuses_a_run_that_ends_before_it_starts(cli_store):
    r = run(
        "run", "log", "--kind", "daily", "--status", "ok",
        "--started-at", "2026-10-07T04:00:00+00:00", "--finished-at", "2026-10-07T03:00:00+00:00",
    )
    assert r.exit_code == 2 and "before" in r.output
    assert run("run", "log", "--kind", "daily", "--status", "ok", "--started-at", "soon").exit_code == 2


def test_a_logged_daily_run_satisfies_health(cli_store, monkeypatch):
    stale = MemoryStore()
    monkeypatch.setattr(health, "open_store", lambda: stale)
    monkeypatch.setattr(health, "now_london", lambda: datetime.now(LONDON))
    assert run("health", "--daily-run").exit_code == 1  # nothing logged yet
    assert run("run", "log", "--kind", "daily", "--status", "ok", "--summary", "2 clips").exit_code == 0
    assert run("health", "--daily-run").exit_code == 0


# ---- run log --details-file and --open (migration 0007: the Scanner card's data) ---------------------------


SCAN = {
    "scan": {
        "queries": ["biscuit #2 concept", "reginald #1 concept"],
        "outliers": 9, "picks_added": 4, "auto_approved": 1, "held": 1, "skipped": 2, "vidiq_credits": 15,
    }
}


def details_file(tmp_path, payload) -> str:
    f = tmp_path / "details.json"
    f.write_text(payload if isinstance(payload, str) else json.dumps(payload), encoding="utf-8")
    return str(f)


def test_run_log_stores_the_structured_details_from_a_file(cli_store, tmp_path, monkeypatch):
    monkeypatch.setattr(health, "now_london", lambda: NOW)
    r = run("run", "log", "--kind", "daily", "--status", "ok", "--summary", "2 clips", "--details-file", details_file(tmp_path, SCAN))
    assert r.exit_code == 0, r.output
    (row,) = cli_store.list_runs(kind="daily", summary="2 clips")
    assert row.details == SCAN
    assert json.loads(r.stdout)["details"] == SCAN  # the printed row carries them too
    plain = run("run", "log", "--kind", "weekly", "--status", "ok")
    assert plain.exit_code == 0 and cli_store.list_runs(kind="weekly")[0].details == {}


def test_details_never_travel_inline_in_the_shell(cli_store, tmp_path):
    assert run("run", "log", "--kind", "daily", "--status", "ok", "--details", '{"scan": {}}').exit_code == 2  # no such option
    ok = tmp_path / "ok.json"
    ok.write_text("{}")
    assert run("run", "log", "--kind", "daily", "--status", "ok", "--details-file", str(ok)).exit_code == 0


@pytest.mark.parametrize(
    ("payload", "why"),
    [
        ("not json", "JSON"),
        ("[1, 2]", "object"),
        ({"scan": "5 picks"}, "scan"),
        ({"scan": {"queries": "biscuit"}}, "queries"),
        ({"scan": {"queries": [1]}}, "queries"),
        ({"scan": {"picks_added": -1}}, "picks_added"),
        ({"scan": {"outliers": 2.5}}, "outliers"),
        ({"scan": {"held": True}}, "held"),
        ({"scan": {"vidiq_credits": "15"}}, "vidiq_credits"),
        ({"vidiq_credits": -5}, "vidiq_credits"),
    ],
)
def test_run_log_refuses_details_the_terminal_could_not_read(cli_store, tmp_path, payload, why):
    before = len(cli_store.list_runs())
    r = run("run", "log", "--kind", "daily", "--status", "ok", "--details-file", details_file(tmp_path, payload))
    assert r.exit_code == 2 and why in r.output
    assert len(cli_store.list_runs()) == before  # nothing written


def test_run_log_details_file_missing_or_unreadable_is_a_caller_error(cli_store, tmp_path):
    r = run("run", "log", "--kind", "daily", "--status", "ok", "--details-file", str(tmp_path / "nope.json"))
    assert r.exit_code == 2 and "no such file" in r.output


def test_extra_keys_in_the_details_are_kept(cli_store, tmp_path):
    payload = {"scan": {"outliers": 1, "note": "free"}, "clips": [{"id": "c1"}]}
    assert run("run", "log", "--kind", "daily", "--status", "ok", "--details-file", details_file(tmp_path, payload)).exit_code == 0
    assert any(r.details == payload for r in cli_store.list_runs(kind="daily"))


def test_run_log_open_records_a_run_that_has_started_and_not_ended(cli_store, monkeypatch):
    monkeypatch.setattr(health, "now_london", lambda: NOW)
    r = run("run", "log", "--kind", "daily", "--status", "ok", "--open")
    assert r.exit_code == 0, r.output
    open_row = next(x for x in cli_store.list_runs(kind="daily") if x.finished_at is None)
    assert open_row.started_at == NOW
    out = json.loads(r.stdout)
    assert out["finished_at"] is None and out["started_at"] == NOW.isoformat()  # the skill keeps this for its closing row


def test_an_open_run_never_counts_as_a_finished_daily_run(monkeypatch):
    store = MemoryStore()
    monkeypatch.setattr(health, "open_store", lambda: store)
    monkeypatch.setattr(health, "now_london", lambda: NOW)
    assert run("run", "log", "--kind", "daily", "--status", "ok", "--open").exit_code == 0
    problems = check(store, NOW, daily_run=True)
    assert len(problems) == 1 and "never finished" in problems[0]  # the watchdog still says the run did not report in


def test_run_log_open_refuses_a_finish_time_and_takes_a_start_time(cli_store):
    both = run("run", "log", "--kind", "daily", "--status", "ok", "--open", "--finished-at", "2026-10-07T03:00:00+00:00")
    assert both.exit_code == 2 and "--open" in both.output
    ok = run("run", "log", "--kind", "daily", "--status", "ok", "--open", "--started-at", "2026-10-07T03:00:00+00:00")
    assert ok.exit_code == 0
    (row,) = [r for r in cli_store.list_runs(kind="daily") if r.finished_at is None]
    assert row.started_at == datetime(2026, 10, 7, 3, 0, tzinfo=timezone.utc)


def test_a_closing_row_with_the_same_start_shares_it_with_the_open_one(cli_store, tmp_path, monkeypatch):
    """The skill logs the open row first and the closing one last with --started-at <the first's started_at>."""
    monkeypatch.setattr(health, "now_london", lambda: NOW)
    first = json.loads(run("run", "log", "--kind", "daily", "--status", "ok", "--open").stdout)
    monkeypatch.setattr(health, "now_london", lambda: NOW + timedelta(minutes=40))
    closing = run(
        "run", "log", "--kind", "daily", "--status", "ok", "--started-at", first["started_at"],
        "--details-file", details_file(tmp_path, SCAN),
    )
    assert closing.exit_code == 0, closing.output
    rows = [r for r in cli_store.list_runs(kind="daily") if r.started_at == NOW]
    assert sorted(r.finished_at is None for r in rows) == [False, True]  # one open marker, one finished row
    (done,) = [r for r in rows if r.finished_at is not None]
    assert done.finished_at == NOW + timedelta(minutes=40) and done.details == SCAN
