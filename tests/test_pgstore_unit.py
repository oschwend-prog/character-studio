"""PostgresStore without a database: a recording fake stands in for psycopg.

Checks the properties that matter and can be seen in the SQL: the claim is one atomic
UPDATE ... RETURNING, a transaction shares one connection and locks the settings row,
filters/values are bound parameters, rows convert back to the dataclasses, and the
store has the same surface as the Store protocol and MemoryStore.
"""

import inspect
import uuid
from datetime import datetime, timedelta
from decimal import Decimal

import psycopg
import pytest
from psycopg.types.json import Jsonb

from studio.config import LONDON
from studio.models import Clip, ClipState, Favorite, Mode, Post, PostStatus
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
    assert len(proto_methods) == 24  # 23 data methods + transaction()
    for name in proto_methods:
        expected = inspect.signature(getattr(Store, name))
        for impl in (MemoryStore, PostgresStore):
            actual = inspect.signature(getattr(impl, name))
            assert [(p.name, p.kind) for p in actual.parameters.values()] == [
                (p.name, p.kind) for p in expected.parameters.values()
            ], f"{impl.__name__}.{name} differs from Store.{name}"
