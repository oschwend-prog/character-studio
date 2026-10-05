import json
from datetime import datetime, timedelta, timezone

import pytest
from typer.testing import CliRunner

from studio import budget
from studio.budget import (
    BudgetRefused,
    NoOpenReservation,
    committed,
    month_key,
    release,
    reserve,
    settle,
    spend,
)
from studio.cli import app
from studio.config import LONDON
from studio.models import Clip, Mode, Settings
from studio.store import MemoryStore

NOW = datetime(2026, 10, 6, 12, 0, tzinfo=LONDON)
MONTH = "2026-10"


def make_store(cap: int = 6000, kill_switch: bool = False) -> MemoryStore:
    return MemoryStore(settings=Settings(monthly_cap_credits=cap, kill_switch=kill_switch))


# ---- reserve: cap and kill switch -------------------------------------------------------


def test_reserve_under_cap_ok():
    store = make_store(cap=300)
    entry = reserve(store, "clip-a", 110, NOW)
    assert (entry.clip_id, entry.kind, entry.credits, entry.month) == ("clip-a", "reserve", 110, MONTH)
    assert entry.id is not None and entry.created_at == NOW
    assert committed(store, MONTH) == 110
    assert [e.id for e in store.ledger_month(MONTH)] == [entry.id]


def test_reserve_over_cap_refused():
    store = make_store(cap=200)
    reserve(store, "clip-a", 110, NOW)
    with pytest.raises(BudgetRefused) as exc:
        reserve(store, "clip-b", 110, NOW)
    assert exc.value.reason == "over_cap"
    assert (exc.value.cap, exc.value.committed, exc.value.requested) == (200, 110, 110)
    assert [e.clip_id for e in store.ledger_month(MONTH)] == ["clip-a"]  # nothing written
    assert committed(store, MONTH) == 110


def test_reserve_up_to_exactly_the_cap_is_allowed():
    store = make_store(cap=220)
    reserve(store, "clip-a", 110, NOW)
    reserve(store, "clip-b", 110, NOW)
    assert committed(store, MONTH) == 220
    with pytest.raises(BudgetRefused) as exc:
        reserve(store, "clip-c", 1, NOW)
    assert exc.value.reason == "over_cap"


def test_kill_switch_refuses():
    store = make_store(cap=6000, kill_switch=True)
    with pytest.raises(BudgetRefused) as exc:
        reserve(store, "clip-a", 10, NOW)
    assert exc.value.reason == "kill_switch"
    assert store.ledger_month(MONTH) == []


def test_kill_switch_is_reported_before_over_cap():
    store = make_store(cap=5, kill_switch=True)
    with pytest.raises(BudgetRefused) as exc:
        reserve(store, "clip-a", 10, NOW)
    assert exc.value.reason == "kill_switch"


def test_cap_is_re_read_from_settings_on_every_reserve():
    store = make_store(cap=200)
    reserve(store, "clip-a", 110, NOW)
    store.set_settings(monthly_cap_credits=100)  # owner lowers the cap below what is committed
    with pytest.raises(BudgetRefused) as exc:
        reserve(store, "clip-b", 1, NOW)
    assert exc.value.reason == "over_cap"
    store.set_settings(monthly_cap_credits=300)
    reserve(store, "clip-b", 110, NOW)
    store.set_settings(kill_switch=True)
    with pytest.raises(BudgetRefused):
        reserve(store, "clip-c", 1, NOW)


@pytest.mark.parametrize("bad", [0, -5, 1.5, "110", True, None])
def test_reserve_rejects_non_positive_or_non_int_credits(bad):
    store = make_store()
    with pytest.raises(ValueError):
        reserve(store, "clip-a", bad, NOW)
    assert store.ledger_month(MONTH) == []


# ---- settle / release ---------------------------------------------------------------------


def test_settle_replaces_reservation():
    store = make_store(cap=300)
    reserve(store, "clip-a", 110, NOW)
    entry = settle(store, "clip-a", 99, NOW + timedelta(minutes=5))
    assert (entry.kind, entry.credits, entry.month, entry.clip_id) == ("settle", 99, MONTH, "clip-a")
    assert committed(store, MONTH) == 99
    assert spend(store, MONTH).settled == 99 and spend(store, MONTH).reserved == 0
    assert [e.kind for e in store.ledger_month(MONTH)] == ["reserve", "settle"]


def test_settle_above_the_reservation_is_recorded_not_refused():
    # The credits are already spent: the ledger must say so even if that passes the cap.
    store = make_store(cap=100)
    reserve(store, "clip-a", 100, NOW)
    settle(store, "clip-a", 130, NOW)
    assert committed(store, MONTH) == 130


def test_settle_zero_is_allowed():
    store = make_store()
    reserve(store, "clip-a", 110, NOW)
    settle(store, "clip-a", 0, NOW)
    assert committed(store, MONTH) == 0


def test_release_frees_reservation():
    store = make_store(cap=300)
    reserve(store, "clip-a", 110, NOW)
    entry = release(store, "clip-a", NOW + timedelta(minutes=5))
    assert (entry.kind, entry.credits, entry.month) == ("release", 110, MONTH)
    assert committed(store, MONTH) == 0
    reserve(store, "clip-b", 300, NOW)  # the freed credits are available again
    assert committed(store, MONTH) == 300


def test_settle_and_release_still_work_with_the_kill_switch_on():
    store = make_store()
    reserve(store, "clip-a", 110, NOW)
    reserve(store, "clip-b", 110, NOW)
    store.set_settings(kill_switch=True)
    settle(store, "clip-a", 100, NOW)
    release(store, "clip-b", NOW)
    assert committed(store, MONTH) == 100


def test_settle_or_release_without_an_open_reservation_raises_and_writes_nothing():
    store = make_store()
    with pytest.raises(NoOpenReservation):
        settle(store, "clip-a", 50, NOW)
    with pytest.raises(NoOpenReservation):
        release(store, "clip-a", NOW)
    reserve(store, "clip-a", 110, NOW)
    settle(store, "clip-a", 99, NOW)
    with pytest.raises(NoOpenReservation):  # a double settle must not double count
        settle(store, "clip-a", 99, NOW)
    with pytest.raises(NoOpenReservation):
        release(store, "clip-a", NOW)
    assert committed(store, MONTH) == 99
    assert len(store.ledger_month(MONTH)) == 2


def test_reservations_of_other_clips_are_untouched_by_settle_and_release():
    store = make_store()
    reserve(store, "clip-a", 110, NOW)
    reserve(store, "clip-b", 120, NOW)
    reserve(store, "clip-c", 130, NOW)
    settle(store, "clip-a", 100, NOW)
    release(store, "clip-b", NOW)
    assert committed(store, MONTH) == 100 + 130
    assert (spend(store, MONTH).settled, spend(store, MONTH).reserved) == (100, 130)


def test_reroll_reserves_again_after_settle():
    store = make_store()
    reserve(store, "clip-a", 110, NOW)
    settle(store, "clip-a", 99, NOW + timedelta(minutes=10))
    reserve(store, "clip-a", 110, NOW + timedelta(minutes=20))  # one re-roll of the same clip
    assert committed(store, MONTH) == 99 + 110
    settle(store, "clip-a", 105, NOW + timedelta(minutes=30))
    assert committed(store, MONTH) == 99 + 105


def test_a_clip_can_hold_two_open_reservations_and_settle_closes_them_all():
    store = make_store()
    reserve(store, "clip-a", 50, NOW)
    reserve(store, "clip-a", 60, NOW)
    assert committed(store, MONTH) == 110  # conservative while both are open
    settle(store, "clip-a", 70, NOW)
    assert committed(store, MONTH) == 70


def test_settle_ordering_survives_clock_skew_and_identical_timestamps():
    store = make_store()
    reserve(store, "clip-a", 110, NOW)
    settle(store, "clip-a", 99, NOW - timedelta(seconds=30))  # settled from a slow clock
    reserve(store, "clip-b", 110, NOW)
    release(store, "clip-b", NOW)  # same timestamp as the reserve
    assert committed(store, MONTH) == 99
    stamps = [e.created_at for e in store.ledger_month(MONTH) if e.clip_id == "clip-a"]
    assert stamps == sorted(stamps) and len(set(stamps)) == 2


# ---- months (Europe/London) -----------------------------------------------------------------


def test_month_boundary():
    store = make_store()
    last_minutes = datetime(2026, 10, 31, 23, 30, tzinfo=LONDON)
    entry = reserve(store, "clip-a", 110, last_minutes)
    assert entry.month == "2026-10"
    assert committed(store, "2026-10") == 110
    assert committed(store, "2026-11") == 0
    first_minutes = datetime(2026, 11, 1, 0, 30, tzinfo=LONDON)
    assert reserve(store, "clip-b", 50, first_minutes).month == "2026-11"
    assert (committed(store, "2026-10"), committed(store, "2026-11")) == (110, 50)


def test_month_follows_london_time_not_utc_or_the_callers_zone():
    # 23:30 UTC on 30 June is already 00:30 on 1 July in London (BST).
    assert month_key(datetime(2026, 6, 30, 23, 30, tzinfo=timezone.utc)) == "2026-07"
    # 07:30 at +08:00 on 1 Nov is 23:30 on 31 Oct in London (GMT).
    plus8 = timezone(timedelta(hours=8))
    assert month_key(datetime(2026, 11, 1, 7, 30, tzinfo=plus8)) == "2026-10"
    assert month_key(datetime(2026, 1, 15, tzinfo=LONDON)) == "2026-01"


def test_month_key_rejects_naive_datetimes():
    with pytest.raises(ValueError):
        month_key(datetime(2026, 10, 6, 12, 0))
    with pytest.raises(ValueError):
        reserve(make_store(), "clip-a", 10, datetime(2026, 10, 6, 12, 0))


def test_settle_after_midnight_stays_in_the_month_of_the_reservation():
    store = make_store()
    reserve(store, "clip-a", 110, datetime(2026, 10, 31, 23, 30, tzinfo=LONDON))
    entry = settle(store, "clip-a", 99, datetime(2026, 11, 1, 0, 10, tzinfo=LONDON))
    assert entry.month == "2026-10"
    assert (committed(store, "2026-10"), committed(store, "2026-11")) == (99, 0)


def test_release_finds_a_reservation_from_an_earlier_month():
    store = make_store()
    reserve(store, "clip-a", 110, datetime(2026, 8, 14, 12, 0, tzinfo=LONDON))
    entry = release(store, "clip-a", NOW)
    assert entry.month == "2026-08" and committed(store, "2026-08") == 0


def test_a_new_month_starts_with_a_fresh_cap():
    store = make_store(cap=200)
    reserve(store, "clip-a", 200, datetime(2026, 10, 30, 12, 0, tzinfo=LONDON))
    with pytest.raises(BudgetRefused):
        reserve(store, "clip-b", 1, datetime(2026, 10, 31, 12, 0, tzinfo=LONDON))
    reserve(store, "clip-b", 200, datetime(2026, 11, 1, 12, 0, tzinfo=LONDON))


# ---- transaction discipline -----------------------------------------------------------------


class SpyStore(MemoryStore):
    """Records the order of the calls budget code makes, including transaction scope."""

    def __init__(self, **kw):
        super().__init__(**kw)
        self.calls: list[str] = []

    def transaction(self):
        spy = self

        class _Tx:
            def __enter__(self):
                spy.calls.append("begin")

            def __exit__(self, *exc):
                spy.calls.append("end")
                return False

        return _Tx()

    def get_settings(self):
        self.calls.append("get_settings")
        return super().get_settings()

    def ledger_month(self, month):
        self.calls.append("ledger_month")
        return super().ledger_month(month)

    def ledger_add(self, e):
        self.calls.append("ledger_add")
        return super().ledger_add(e)


def test_ledger_writers_lock_via_settings_inside_one_transaction():
    # PostgresStore takes the settings row FOR UPDATE on get_settings() inside a transaction,
    # so reading settings first, in the transaction, before touching the ledger serialises
    # concurrent reserve / settle / release calls.
    store = SpyStore(settings=Settings(monthly_cap_credits=1000))
    for op in (
        lambda: reserve(store, "clip-a", 10, NOW),
        lambda: settle(store, "clip-a", 9, NOW),
        lambda: reserve(store, "clip-b", 10, NOW),
        lambda: release(store, "clip-b", NOW),
    ):
        store.calls.clear()
        op()
        assert store.calls[0] == "begin" and store.calls[-1] == "end"
        assert store.calls[1] == "get_settings"
        assert store.calls.count("ledger_add") == 1 and store.calls[-2] == "ledger_add"
        assert store.calls.count("begin") == store.calls.count("end") == 1


def test_a_refused_reserve_writes_nothing_inside_its_transaction():
    store = SpyStore(settings=Settings(monthly_cap_credits=5))
    with pytest.raises(BudgetRefused):
        reserve(store, "clip-a", 10, NOW)
    assert "ledger_add" not in store.calls and store.calls[-1] == "end"


# ---- CLI -----------------------------------------------------------------------------------


@pytest.fixture
def cli_store(monkeypatch):
    store = make_store(cap=300)
    clip = store.add_clip(Clip(character_slug="biscuit", mode=Mode.recreate))
    monkeypatch.setattr(budget, "open_store", lambda: store)
    monkeypatch.setattr(budget, "now_london", lambda: NOW)
    store.clip_id = clip.id  # type: ignore[attr-defined]
    return store


def run(*args: str):
    return CliRunner().invoke(app, ["budget", *args])


def test_cli_status(cli_store):
    r = run("status")
    assert r.exit_code == 0
    assert json.loads(r.stdout) == {
        "month": MONTH, "cap": 300, "committed": 0, "settled": 0, "reserved": 0,
        "remaining": 300, "kill_switch": False,
    }
    assert json.loads(run("status", "--month", "2026-09").stdout)["month"] == "2026-09"


def test_cli_reserve_settle_release_roundtrip(cli_store):
    cid = cli_store.clip_id
    r = run("reserve", "110", "--clip", cid)
    assert r.exit_code == 0, r.output
    out = json.loads(r.stdout)
    assert (out["clip_id"], out["kind"], out["credits"], out["month"]) == (cid, "reserve", 110, MONTH)
    status = json.loads(run("status").stdout)
    assert (status["committed"], status["reserved"], status["remaining"]) == (110, 110, 190)

    r = run("settle", cid, "99")
    assert r.exit_code == 0, r.output
    assert json.loads(r.stdout)["kind"] == "settle"
    status = json.loads(run("status").stdout)
    assert (status["committed"], status["settled"], status["reserved"]) == (99, 99, 0)

    assert run("reserve", "50", "--clip", cid).exit_code == 0
    r = run("release", cid)
    assert r.exit_code == 0 and json.loads(r.stdout)["kind"] == "release"
    assert json.loads(run("status").stdout)["committed"] == 99


def test_cli_over_cap_exits_3_with_json_on_stdout(cli_store):
    r = run("reserve", "301", "--clip", cli_store.clip_id)
    assert r.exit_code == 3
    out = json.loads(r.stdout)
    assert out["ok"] is False and out["refused"] == "over_cap"
    assert (out["cap"], out["committed"], out["requested"]) == (300, 0, 301)
    assert cli_store.ledger_month(MONTH) == []


def test_cli_kill_switch_exits_3(cli_store):
    cli_store.set_settings(kill_switch=True)
    r = run("reserve", "10", "--clip", cli_store.clip_id)
    assert r.exit_code == 3 and json.loads(r.stdout)["refused"] == "kill_switch"
    assert json.loads(run("status").stdout)["kill_switch"] is True


def test_cli_unknown_clip_and_missing_reservation_exit_2(cli_store):
    r = run("reserve", "10", "--clip", "00000000-0000-0000-0000-000000000000")
    assert r.exit_code == 2 and "clip" in r.output
    r = run("settle", cli_store.clip_id, "10")
    assert r.exit_code == 2 and "reservation" in r.output
    r = run("release", cli_store.clip_id)
    assert r.exit_code == 2 and "reservation" in r.output
    assert cli_store.ledger_month(MONTH) == []


def test_cli_rejects_bad_numbers(cli_store):
    assert run("reserve", "0", "--clip", cli_store.clip_id).exit_code == 2
    assert run("reserve", "abc", "--clip", cli_store.clip_id).exit_code == 2
    assert run("settle", cli_store.clip_id, "-1").exit_code == 2
    assert run("status", "--month", "2026-13").exit_code == 2


def test_cli_without_database_url_prints_a_clear_error_and_exits_2(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    for args in (["status"], ["reserve", "10", "--clip", "x"], ["settle", "x", "1"], ["release", "x"]):
        r = run(*args)
        assert r.exit_code == 2, args
        assert "DATABASE_URL" in r.output
        assert r.exception is None or isinstance(r.exception, SystemExit)  # no traceback


def test_cli_budget_group_is_the_modules_own_app():
    groups = [g for g in app.registered_groups if g.name == "budget"]
    assert len(groups) == 1 and groups[0].typer_instance is budget.app
    r = CliRunner().invoke(app, ["budget", "--help"])
    assert r.exit_code == 0
    for cmd in ("status", "reserve", "settle", "release"):
        assert cmd in r.output


# ---- budget open: which clips still hold credits (crash recovery reads this) ------------------------------


def _clip(store, state="generating", **kw):
    return store.add_clip(Clip(character_slug="biscuit", mode=Mode.recreate, state=state, **kw))


def test_open_reservations_lists_a_held_clip_and_drops_it_once_settled_or_released():
    store = make_store()
    a, b = _clip(store), _clip(store, "planned")
    reserve(store, a.id, 160, NOW - timedelta(hours=5))
    reserve(store, b.id, 115, NOW - timedelta(hours=1))
    rows = budget.open_reservations(store, NOW)
    assert [(r["clip_id"], r["held"], r["state"]) for r in rows] == [(a.id, 160, "generating"), (b.id, 115, "planned")]
    assert rows[0]["oldest_reserved_at"] == (NOW - timedelta(hours=5)).isoformat()
    assert rows[0]["age_hours"] == 5.0 and rows[1]["age_hours"] == 1.0
    settle(store, a.id, 120, NOW)
    release(store, b.id, NOW)
    assert budget.open_reservations(store, NOW) == []


def test_two_reserves_add_up_and_the_oldest_time_is_the_first_still_open_one():
    store = make_store()
    a = _clip(store)
    reserve(store, a.id, 100, NOW - timedelta(hours=9))
    settle(store, a.id, 90, NOW - timedelta(hours=8))  # closed: not part of what is open now
    reserve(store, a.id, 40, NOW - timedelta(hours=3))  # the re-roll's reserve
    reserve(store, a.id, 20, NOW - timedelta(hours=2))  # a top-up
    (row,) = budget.open_reservations(store, NOW)
    assert row["held"] == 60 and row["oldest_reserved_at"] == (NOW - timedelta(hours=3)).isoformat()


def test_open_reservations_look_back_across_months_and_sum_per_clip():
    store = make_store()
    a = _clip(store)
    reserve(store, a.id, 100, datetime(2026, 8, 30, 12, 0, tzinfo=LONDON))
    reserve(store, a.id, 50, datetime(2026, 10, 1, 9, 0, tzinfo=LONDON))
    (row,) = budget.open_reservations(store, NOW)
    assert row["held"] == 150 and row["oldest_reserved_at"].startswith("2026-08-30")
    assert row["months"] == ["2026-08", "2026-10"]


def test_open_reservations_outside_the_lookback_are_not_listed():
    store = make_store()
    a = _clip(store)
    reserve(store, a.id, 100, datetime(2025, 6, 1, 12, 0, tzinfo=LONDON))  # > 12 months before NOW
    assert budget.open_reservations(store, NOW) == []


def test_open_reservations_carry_the_clip_context_and_sort_oldest_first():
    store = make_store()
    newer, older = _clip(store), _clip(store)
    reserve(store, newer.id, 10, NOW - timedelta(hours=1))
    reserve(store, older.id, 10, NOW - timedelta(hours=7))
    rows = budget.open_reservations(store, NOW)
    assert [r["clip_id"] for r in rows] == [older.id, newer.id]
    assert rows[0]["character"] == "biscuit" and rows[0]["clip_created_at"] == store.get_clip(older.id).created_at.isoformat()


def test_a_ledger_row_of_an_unknown_clip_is_still_listed_with_no_state():
    store = make_store()
    reserve(store, "ghost-clip", 30, NOW)
    (row,) = budget.open_reservations(store, NOW)
    assert row["clip_id"] == "ghost-clip" and row["state"] is None and row["held"] == 30


def test_open_reservations_needs_an_aware_now():
    with pytest.raises(ValueError):
        budget.open_reservations(make_store(), datetime(2026, 10, 6, 12, 0))


def test_cli_open_prints_the_list_and_writes_nothing(cli_store):
    assert json.loads(run("open").stdout) == []
    reserve(cli_store, cli_store.clip_id, 160, NOW - timedelta(hours=3))
    before = list(cli_store.ledger_month(MONTH))
    r = run("open")
    assert r.exit_code == 0, r.output
    (row,) = json.loads(r.stdout)
    assert row["clip_id"] == cli_store.clip_id and row["held"] == 160 and row["age_hours"] == 3.0
    assert cli_store.ledger_month(MONTH) == before  # read-only
    assert "open" in run("--help").output
