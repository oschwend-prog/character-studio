"""PostgresStore without a database: a recording fake stands in for psycopg.

Checks the properties that matter and can be seen in the SQL: the claim is one atomic
UPDATE ... RETURNING, a transaction shares one connection and locks the settings row,
filters/values are bound parameters, rows convert back to the dataclasses, and the
store has the same surface as the Store protocol and MemoryStore.
"""

import inspect
import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal

import psycopg
import pytest
from psycopg.types.json import Jsonb

from studio.config import LONDON
from studio.models import (
    Account,
    Character,
    Clip,
    ClipState,
    Favorite,
    Mode,
    Post,
    PostStatus,
    Review,
    Run,
    RunKind,
    RunStatus,
    Snapshot,
)
from studio.pgstore import PostgresStore
from studio.store import MemoryStore, Store

NOW = datetime(2026, 10, 6, 19, 0, tzinfo=LONDON)
DSN = "postgresql://user:pw@localhost/none"  # never connected to: psycopg.connect is faked


class FakeCursor:
    def __init__(self, db):
        self.db = db
        self.description = None
        self.connection = db

    def execute(self, query, params=()):
        self.db.statements.append((query.as_string(), list(params)))
        self._rows = self.db.responses.pop(0) if self.db.responses else []
        self.description = [object()] if self._rows else None

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._rows[0]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeDB:
    """One fake database; each psycopg.connect() returns a new FakeConnection on it."""

    def __init__(self):
        self.statements: list[tuple[str, list]] = []
        self.responses: list[list[dict]] = []
        self.connections: list[FakeConnection] = []

    def connect(self, *args, **kwargs):
        conn = FakeConnection(self)
        self.connections.append(conn)
        return conn

    def queue(self, *responses):
        self.responses.extend(responses)


class FakeTransaction:
    def __init__(self, conn):
        self.conn = conn

    def __enter__(self):
        self.conn.events.append("begin")
        return self

    def __exit__(self, exc_type, *rest):
        self.conn.events.append("rollback" if exc_type else "commit")
        return False


class FakeConnection:
    def __init__(self, db):
        self.db = db
        self.outcome = None  # what leaving `with psycopg.connect(...)` did
        self.events: list[str] = []  # explicit conn.transaction() blocks

    def cursor(self):
        return FakeCursor(self.db)

    def transaction(self):
        return FakeTransaction(self)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, *rest):
        self.outcome = "rollback" if exc_type else "commit"
        return False


@pytest.fixture
def db(monkeypatch):
    fake = FakeDB()
    monkeypatch.setattr(psycopg, "connect", fake.connect)
    return fake


def post_row(**over):
    row = {
        "id": uuid.uuid4(),
        "clip_id": uuid.uuid4(),
        "account_id": uuid.uuid4(),
        "scheduled_for": NOW - timedelta(minutes=1),
        "status": "posting",
        "claimed_at": NOW,
        "attempts": 0,
        "platform_post_id": None,
        "url": None,
        "error": None,
    }
    return row | over


def clip_row(**over):
    row = {
        "id": uuid.uuid4(),
        "character_slug": "biscuit",
        "source_id": None,
        "mode": "recreate",
        "state": "planned",
        "hf_job_id": None,
        "credits_reserved": 0,
        "credits_actual": None,
        "qa": {},
        "master_path": None,
        "hook": None,
        "caption": None,
        "hashtags": [],
        "features": {},
        "reject_reason": None,
        "created_at": NOW,
    }
    return row | over


def test_claim_due_posts_is_one_atomic_update(db):
    db.queue([post_row(), post_row(scheduled_for=NOW - timedelta(hours=1))])
    claimed = PostgresStore(DSN).claim_due_posts(NOW)

    assert len(db.statements) == 1  # one statement: no select-then-update race
    query, params = db.statements[0]
    assert query.startswith('update "studio"."posts" set status = \'posting\'')
    assert "where status = 'scheduled' and scheduled_for <= %s" in query
    assert "returning" in query
    assert params == [NOW, NOW]
    assert db.connections[0].outcome == "commit"
    assert [p.status for p in claimed] == [PostStatus.posting] * 2
    assert claimed[0].scheduled_for < claimed[1].scheduled_for  # sorted by slot


def test_delete_post_is_one_bound_delete_by_id_and_raises_for_a_missing_row(db):
    uid = uuid.uuid4()
    db.queue([{"id": uid}])
    PostgresStore(DSN).delete_post(str(uid))
    query, params = db.statements[0]
    assert query.startswith('delete from "studio"."posts" where id = %s') and "returning" in query
    assert params == [uid] and db.connections[0].outcome == "commit"
    db.queue([])
    with pytest.raises(KeyError):
        PostgresStore(DSN).delete_post(str(uuid.uuid4()))
    with pytest.raises(KeyError):
        PostgresStore(DSN).delete_post("not-a-uuid")


def test_claim_due_posts_refuses_naive_now(db):
    with pytest.raises(ValueError):
        PostgresStore(DSN).claim_due_posts(datetime(2026, 10, 6, 19, 0))
    assert db.statements == []


def test_transaction_shares_one_connection_and_locks_settings_row(db):
    settings_row = {"monthly_cap_credits": 6000, "kill_switch": False, "cadence": {}}
    db.queue([settings_row], [settings_row], [settings_row], [settings_row])
    store = PostgresStore(DSN)

    store.get_settings()  # outside a transaction: plain read, no lock
    assert not db.statements[0][0].endswith("for update")

    with store.transaction():
        store.get_settings()
        store.get_settings()
        with store.transaction():  # nested: joins the outer one
            store.get_settings()
    in_tx = [q for q, _ in db.statements[1:]]
    assert len(in_tx) == 3 and all(q.endswith("where id = 1 for update") for q in in_tx)
    assert len(db.connections) == 2  # one for the plain read, one for the whole transaction
    assert db.connections[0].events == []  # the plain read is not wrapped in a transaction block
    assert db.connections[1].events == ["begin", "commit"]  # one BEGIN ... COMMIT around all three


def test_transaction_rolls_back_on_error(db):
    store = PostgresStore(DSN)
    with pytest.raises(RuntimeError):
        with store.transaction():
            raise RuntimeError("boom")
    assert db.connections[0].events == ["begin", "rollback"]
    assert db.connections[0].outcome == "rollback"
    # and the store is usable again afterwards, outside any transaction
    db.queue([{"monthly_cap_credits": 1, "kill_switch": False, "cadence": {}}])
    store.get_settings()
    assert not db.statements[-1][0].endswith("for update")


def test_schema_name_is_configurable_and_validated(db):
    db.queue([])
    PostgresStore(DSN, schema="studio_test").list_clips()
    assert 'from "studio_test"."clips"' in db.statements[0][0]
    with pytest.raises(ValueError):
        PostgresStore(DSN, schema="studio; drop table x")


def test_list_filters_are_bound_parameters(db):
    db.queue([])
    PostgresStore(DSN).list_clips(state=ClipState.approved, source_id=None)
    query, params = db.statements[0]
    assert '"state" = %s' in query and '"source_id" is null' in query
    assert "approved" not in query and params == ["approved"]  # enum -> value, as a parameter
    assert query.endswith('order by "created_at", "id"')


def test_unknown_fields_fail_before_any_query(db):
    store = PostgresStore(DSN)
    with pytest.raises(TypeError):
        store.list_clips(bogus=1)
    with pytest.raises(TypeError):
        store.update_clip(str(uuid.uuid4()), bogus=1)
    with pytest.raises(ValueError):
        store.update_clip(str(uuid.uuid4()), id="x")
    with pytest.raises(ValueError):
        store.update_post(str(uuid.uuid4()), scheduled_for=datetime(2026, 10, 6, 19, 0))
    with pytest.raises(KeyError):
        store.update_clip("not-a-uuid", state="approved")
    assert store.get_clip("not-a-uuid") is None
    assert db.statements == [] and db.connections == []


def test_insert_leaves_ids_to_the_database_and_wraps_json(db):
    db.queue([clip_row()])
    created = PostgresStore(DSN).add_clip(
        Clip(character_slug="biscuit", mode=Mode.recreate, qa={"ok": True}, hashtags=["#a"])
    )
    query, params = db.statements[0]
    assert query.startswith('insert into "studio"."clips" (')
    assert '"id"' not in query.split("values")[0] and '"created_at"' not in query.split("values")[0]
    assert "returning" in query
    assert any(isinstance(p, Jsonb) for p in params)  # qa / features go in as jsonb
    assert "recreate" in params and ["#a"] in params  # enum -> value, list -> text[]
    assert isinstance(created.id, str) and created.created_at == NOW


def test_update_binds_values_and_converts_enums(db):
    db.queue([clip_row(state="approved")])
    uid = uuid.uuid4()
    got = PostgresStore(DSN).update_clip(str(uid), state=ClipState.approved, features={"x": 1})
    query, params = db.statements[0]
    assert query.startswith('update "studio"."clips" set "state" = %s, "features" = %s where id = %s')
    assert params[0] == "approved" and isinstance(params[1], Jsonb) and params[2] == uid
    assert got.state is ClipState.approved


def test_update_account_binds_the_share_and_returns_the_account(db):
    uid = uuid.uuid4()
    db.queue([{
        "id": uid, "character_slug": "biscuit", "platform": "instagram", "handle": "@b.ig",
        "postiz_integration_id": None, "mode": "approval", "dropin_share": 0.2,
        "created_at": NOW,
    }])
    got = PostgresStore(DSN).update_account(str(uid), dropin_share=0.2)
    query, params = db.statements[0]
    assert query.startswith('update "studio"."accounts" set "dropin_share" = %s where id = %s')
    assert params == [0.2, uid]
    assert isinstance(got, Account) and got.dropin_share == 0.2 and got.id == str(uid)


def test_update_account_of_unknown_id_raises_key_error(db):
    db.queue([])
    with pytest.raises(KeyError):
        PostgresStore(DSN).update_account(str(uuid.uuid4()), dropin_share=0.2)


def test_snapshot_insert_and_read_carry_skip_rate_and_watched_pct(db):
    pid = uuid.uuid4()
    row = {
        "post_id": pid, "captured_at": NOW, "views": 100, "likes": None, "comments": None,
        "shares": None, "saves": None, "watch_time_s": None, "follows": None,
        "non_follower_pct": None, "skip_rate": 0.37, "watched_pct": 41.2,
    }
    db.queue([row])
    got = PostgresStore(DSN).add_snapshot(
        Snapshot(post_id=str(pid), captured_at=NOW, views=100, skip_rate=0.37, watched_pct=41.2)
    )
    query, params = db.statements[0]
    assert '"skip_rate"' in query and '"watched_pct"' in query
    assert 0.37 in params and 41.2 in params
    assert (got.skip_rate, got.watched_pct) == (0.37, 41.2)


def test_update_of_unknown_id_raises_key_error(db):
    db.queue([])
    with pytest.raises(KeyError):
        PostgresStore(DSN).update_clip(str(uuid.uuid4()), state="approved")


def test_rows_convert_uuid_decimal_and_enums(db):
    fav_row = {
        "id": uuid.uuid4(), "url": "u", "platform": "tiktok", "creator_handle": None,
        "views": 1000, "outlier_x": Decimal("4.5"), "origin": "scan", "character_slug": "biscuit",
        "proposal": {}, "scores": {"v": 1}, "total_score": Decimal("92.5"), "note": None,
        "status": "new", "breakdown_md": None, "source_id": uuid.uuid4(), "clip_id": None,
        "created_at": NOW,
    }
    db.queue([fav_row])
    (fav,) = PostgresStore(DSN).list_favorites(status="new")
    assert isinstance(fav, Favorite)
    assert isinstance(fav.id, str) and isinstance(fav.source_id, str)
    assert fav.total_score == 92.5 and isinstance(fav.total_score, float)
    assert fav.outlier_x == 4.5 and isinstance(fav.outlier_x, float)

    db.queue([post_row(status="needs_check")])
    (p,) = PostgresStore(DSN).list_posts()
    assert isinstance(p, Post) and p.status is PostStatus.needs_check


def test_get_clip_with_unknown_uuid_returns_none(db):
    db.queue([])
    assert PostgresStore(DSN).get_clip(str(uuid.uuid4())) is None


def test_postgres_store_has_the_same_surface_as_the_protocol_and_memory_store():
    assert isinstance(PostgresStore(DSN), Store)  # no connection is made by the constructor
    proto_methods = [
        n for n, v in inspect.getmembers(Store, inspect.isfunction) if not n.startswith("_")
    ]
    assert len(proto_methods) == 38  # 37 data methods (6 for the hits and the day's spend of migration 0016) + transaction()
    for name in proto_methods:
        expected = inspect.signature(getattr(Store, name))
        for impl in (MemoryStore, PostgresStore):
            actual = inspect.signature(getattr(impl, name))
            assert [(p.name, p.kind) for p in actual.parameters.values()] == [
                (p.name, p.kind) for p in expected.parameters.values()
            ], f"{impl.__name__}.{name} differs from Store.{name}"


def test_upsert_character_is_one_insert_on_conflict_do_update(db):
    setup = {"closeup": True, "planned_handles": {"tiktok": "@biscuit.moves", "instagram": None}}
    db.queue([{"slug": "biscuit", "name": "Biscuit", "status": "live", "bodies": ["biped", "quadruped"], "setup": setup}])
    got = PostgresStore(DSN).upsert_character(
        Character(slug="biscuit", name="Biscuit", status="live", bodies=["biped", "quadruped"], setup=setup)
    )
    assert len(db.statements) == 1
    query, params = db.statements[0]
    assert query.startswith('insert into "studio"."characters" ("slug", "name", "status", "bodies", "setup") values')
    assert 'on conflict ("slug") do update set' in query
    for col in ("name", "status", "bodies", "setup"):  # the seed refreshes the setup too (migration 0007)
        assert f'"{col}" = excluded."{col}"' in query
    assert "returning" in query
    assert params[:4] == ["biscuit", "Biscuit", "live", ["biped", "quadruped"]]  # enums as text[], bound
    assert isinstance(params[4], Jsonb) and params[4].obj == setup  # setup goes in as jsonb
    assert db.connections[0].outcome == "commit"
    assert isinstance(got, Character) and got.status == "live" and got.bodies[0].value == "biped"
    assert got.setup == setup


def test_upsert_account_conflicts_on_character_and_platform_and_spares_mode_and_share(db):
    uid = uuid.uuid4()
    db.queue([{
        "id": uid, "character_slug": "biscuit", "platform": "instagram", "handle": "b.ig",
        "postiz_integration_id": "pz-1", "mode": "auto", "dropin_share": 0.2, "created_at": NOW,
    }])
    got = PostgresStore(DSN).upsert_account(
        Account(
            character_slug="biscuit", platform="instagram", handle="b.ig",
            postiz_integration_id="pz-1", dropin_share=0.4,
        )
    )
    query, params = db.statements[0]
    assert query.startswith('insert into "studio"."accounts" (')
    head = query.split("values")[0]
    assert '"id"' not in head and '"created_at"' not in head  # the database assigns both
    assert 'on conflict ("character_slug", "platform") do update set' in query
    update = query.split("do update set")[1].split("returning")[0]
    assert '"handle" = excluded."handle"' in update
    assert '"postiz_integration_id" = excluded."postiz_integration_id"' in update
    assert "dropin_share" not in update and '"mode"' not in update  # operational state survives
    assert "instagram" in params and 0.4 in params  # explicit share on first insert, bound
    assert (got.id, got.mode, got.dropin_share) == (str(uid), "auto", 0.2)


def test_upsert_account_turns_a_check_violation_into_a_value_error(db, monkeypatch):
    from psycopg.errors import CheckViolation

    def boom(self, query, params=()):
        raise CheckViolation("dropin_share out of range")

    monkeypatch.setattr(FakeCursor, "execute", boom)
    with pytest.raises(ValueError):
        PostgresStore(DSN).upsert_account(
            Account(character_slug="biscuit", platform="tiktok", handle="b", dropin_share=7)
        )


def test_upsert_account_turns_a_taken_handle_into_a_value_error(db, monkeypatch):
    from psycopg.errors import UniqueViolation

    def boom(self, query, params=()):
        raise UniqueViolation('duplicate key value violates unique constraint "accounts_platform_handle_key"')

    monkeypatch.setattr(FakeCursor, "execute", boom)
    with pytest.raises(ValueError, match="duplicate key"):
        PostgresStore(DSN).upsert_account(Account(character_slug="reginald", platform="tiktok", handle="@biscuit"))


# ---- runs and reviews ---------------------------------------------------------------------------

WEEK = date(2026, 10, 5)


def run_row(**over):
    row = {
        "id": uuid.uuid4(), "kind": "daily", "started_at": NOW, "finished_at": NOW,
        "status": "ok", "summary": None, "details": {},
    }
    return row | over


def review_row(**over):
    row = {
        "id": uuid.uuid4(), "week": WEEK, "character_slug": "biscuit", "report_md": "report",
        "bar_status": "continue", "created_at": NOW,
    }
    return row | over


def test_add_run_binds_enums_and_leaves_id_and_started_at_to_the_database(db):
    db.queue([run_row(status="budget_stop", summary="stopped")])
    got = PostgresStore(DSN).add_run(Run(kind="daily", status="budget_stop", finished_at=NOW, summary="stopped"))
    query, params = db.statements[0]
    assert query.startswith('insert into "studio"."runs" ("kind", "finished_at", "status", "summary", "details") values')
    assert "returning" in query
    assert params[:4] == ["daily", NOW, "budget_stop", "stopped"]
    assert isinstance(params[4], Jsonb) and params[4].obj == {}  # details: jsonb, empty unless the run logged some
    assert (got.kind, got.status, got.summary) == (RunKind.daily, RunStatus.budget_stop, "stopped")
    assert isinstance(got.id, str) and got.started_at == NOW and got.details == {}


def test_add_run_carries_the_structured_details_as_jsonb(db):
    scan = {"scan": {"queries": ["biscuit #1 format"], "outliers": 7, "picks_added": 3, "vidiq_credits": 5}}
    db.queue([run_row(details=scan)])
    got = PostgresStore(DSN).add_run(Run(kind="daily", status="ok", finished_at=NOW, details=scan))
    _, params = db.statements[0]
    assert isinstance(params[-1], Jsonb) and params[-1].obj == scan
    assert got.details == scan


def test_add_run_sends_started_at_when_given_and_refuses_a_naive_time(db):
    db.queue([run_row()])
    PostgresStore(DSN).add_run(Run(kind="weekly", status="ok", started_at=NOW))
    assert '"started_at"' in db.statements[0][0].split("values")[0]
    with pytest.raises(ValueError, match="timezone-aware"):
        PostgresStore(DSN).add_run(Run(kind="weekly", status="ok", finished_at=datetime(2026, 10, 6, 1, 0)))
    assert len(db.statements) == 1


def test_list_runs_filters_by_bound_enum_values_oldest_first(db):
    db.queue([run_row(), run_row()])
    runs = PostgresStore(DSN).list_runs(kind=RunKind.daily, finished_at=None)
    query, params = db.statements[0]
    assert '"kind" = %s' in query and '"finished_at" is null' in query and params == ["daily"]
    assert query.endswith('order by "started_at", "id"')
    assert [r.kind for r in runs] == [RunKind.daily] * 2


def test_upsert_review_is_one_insert_on_conflict_do_update_on_the_unique_key(db):
    """Migration 0006's unique index on (week, character_slug) is the conflict target: no lookup, no race."""
    uid = uuid.uuid4()
    db.queue([review_row(id=uid, report_md="v2", bar_status="promote")])
    got = PostgresStore(DSN).upsert_review(
        Review(week=WEEK, character_slug="biscuit", report_md="v2", bar_status="promote")
    )
    assert len(db.statements) == 1  # one statement: nothing between a lookup and a write to race on
    query, params = db.statements[0]
    head = query.split("values")[0]
    assert query.startswith('insert into "studio"."reviews" (') and '"id"' not in head and '"created_at"' not in head
    assert 'on conflict ("week", "character_slug") do update set' in query
    assert '"report_md" = excluded."report_md"' in query and '"bar_status" = excluded."bar_status"' in query
    assert '"week" = excluded' not in query and '"created_at" = excluded' not in query  # identity and age stay
    assert "returning" in query
    assert params == [WEEK, "biscuit", "v2", "promote"]
    assert db.connections[0].outcome == "commit"
    assert got.id == str(uid) and got.report_md == "v2" and got.bar_status == "promote"


def test_upsert_review_turns_an_unknown_character_into_a_value_error(db, monkeypatch):
    from psycopg.errors import ForeignKeyViolation

    def boom(self, query, params=()):
        raise ForeignKeyViolation('violates foreign key constraint "reviews_character_slug_fkey"')

    monkeypatch.setattr(FakeCursor, "execute", boom)
    with pytest.raises(ValueError, match="foreign key"):
        PostgresStore(DSN).upsert_review(Review(week=WEEK, character_slug="nobody", report_md="x"))
    assert db.connections[0].outcome == "rollback"


def test_list_reviews_orders_by_week_then_character(db):
    db.queue([review_row()])
    got = PostgresStore(DSN).list_reviews(character_slug="biscuit")
    query, params = db.statements[0]
    assert '"character_slug" = %s' in query and params == ["biscuit"]
    assert query.endswith('order by "week", "character_slug", "id"')
    assert got[0].week == WEEK and isinstance(got[0].id, str)


# ---- hits (migration 0016) ----------------------------------------------------------------------------------------------------


def hit_row(**over):
    row = {
        "id": uuid.uuid4(), "platform": "tiktok", "url": "https://www.tiktok.com/@a/video/1", "creator_handle": "@a",
        "followers": 50, "views": 900, "likes": 10, "comments": None, "shares": None, "saves": None, "posted_at": NOW,
        "caption": "c", "sound": None, "duration_s": 12.5, "thumbnail_url": None, "keyword": "dog dance", "character_slug": "franz",
        "reach": 18.0, "score": 70, "status": "new", "created_at": NOW, "last_seen": NOW,
    }  # fmt: skip
    return row | over


def test_upsert_hit_is_one_insert_on_conflict_on_the_url_that_never_touches_status_or_first_seen(db):
    from studio.models import Hit

    db.queue([{**hit_row(), "inserted": False}])
    got, created = PostgresStore(DSN).upsert_hit(Hit(platform="tiktok", url="https://www.tiktok.com/@a/video/1", views=900, score=70,
                                                     created_at=NOW, last_seen=NOW))  # fmt: skip
    assert len(db.statements) == 1
    query, params = db.statements[0]
    assert query.startswith('insert into "studio"."hits" as h (')
    assert 'on conflict ("url") do update set' in query and "returning" in query and "(xmax = 0) as inserted" in query
    for col in ("followers", "views", "likes", "comments", "shares", "saves", "posted_at", "caption", "sound", "duration_s", "thumbnail_url"):
        assert f'"{col}" = coalesce(excluded."{col}", h."{col}")' in query, col  # a number the API left out is kept
    for col in ("character_slug", "keyword"):
        assert f'"{col}" = coalesce(h."{col}", excluded."{col}")' in query, col  # who found it first stays
    for col in ("reach", "score", "last_seen"):
        assert f'"{col}" = excluded."{col}"' in query, col
    sets = query.split("do update set", 1)[1].split(" returning ", 1)[0]
    assert '"status"' not in sets and '"created_at"' not in sets and '"id"' not in sets
    assert "tiktok" in params and 900 in params  # bound, never pasted
    assert created is False and isinstance(got, Hit) and got.id and got.platform.value == "tiktok" and got.reach == 18.0


def test_list_and_update_hits_bind_their_values(db):
    db.queue([hit_row()], [hit_row(status="dismissed")])
    store = PostgresStore(DSN)
    assert [h.url for h in store.list_hits(status="new")] == ["https://www.tiktok.com/@a/video/1"]
    query, params = db.statements[0]
    assert '"status" = %s' in query and params == ["new"] and 'order by "created_at", "id"' in query
    hid = str(uuid.uuid4())
    assert store.update_hit(hid, status="dismissed").status == "dismissed"
    assert db.statements[1][0].startswith('update "studio"."hits" set "status" = %s where id = %s')



def test_add_hit_spend_is_one_increment_on_the_day_and_a_missing_day_is_zero(db):
    db.queue([], [{"day": date(2026, 10, 8), "search_credits": 3, "download_credits": 10, "downloads": 1, "updated_at": NOW}])
    store = PostgresStore(DSN)
    assert store.get_hit_spend(date(2026, 10, 8)).total == 0  # no row: nothing spent
    got = store.add_hit_spend(date(2026, 10, 8), download_credits=10, downloads=1)
    query, params = db.statements[1]
    assert query.startswith('insert into "studio"."hits_spend" as s (day, "search_credits", "download_credits", "downloads") values')
    assert "on conflict (day) do update set" in query and "updated_at = now()" in query
    for col in ("search_credits", "download_credits", "downloads"):
        assert f'"{col}" = s."{col}" + excluded."{col}"' in query, col  # added, never overwritten
    assert params == [date(2026, 10, 8), 0, 10, 1] and got.total == 13 and got.downloads == 1
    with pytest.raises(ValueError):
        store.add_hit_spend(date(2026, 10, 8), search_credits=-1)
    assert len(db.statements) == 2  # refused before any query
