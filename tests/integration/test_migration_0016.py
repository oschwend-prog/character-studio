"""Migration 0016 against a real Postgres: studio.hits (its rules, RLS and grants), v_hits, set_hit_status, set_drop_keep, copy_drop
carrying auto_filed, and PostgresStore's hits methods.

Skipped unless ``DATABASE_URL_TEST`` is set; see ``test_pgstore.py`` for what the database needs. The schema is built from every
migration, renamed ``studio_test``, and dropped afterwards (``conftest.py`` removes the renamed cron job). No dispatch leaves the
database: as in ``test_migration_0015.py``, every Vault lookup of the TEST schema points at a secret name that does not exist, so
request_job (which copy_drop calls) finds no token and sends nothing. The owner's RPCs need Supabase's ``auth.jwt()``: those tests
are skipped on a database without it.
"""

import json
import os
import re
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import psycopg
import pytest
from psycopg.rows import dict_row

from studio.models import Hit
from studio.pgstore import PostgresStore

DSN = os.environ.get("DATABASE_URL_TEST")
pytestmark = pytest.mark.skipif(not DSN, reason="DATABASE_URL_TEST is not set")

SCHEMA = "studio_test"
MIGRATIONS = Path(__file__).resolve().parents[2] / "supabase" / "migrations"
OWNER = json.dumps({"email": "o.schwend@gmail.com"})
STRANGER = json.dumps({"email": "someone@else.com"})
TOKEN = "'github_dispatch_token'"
NO_TOKEN = "'github_dispatch_token_absent_in_tests'"
PERSON = {"kind": "person", "body": "biped"}
NOW = datetime(2026, 10, 8, 5, 30, tzinfo=timezone.utc)


def _ddl() -> str:
    text = "\n".join(f.read_text() for f in sorted(MIGRATIONS.glob("*.sql")))
    assert TOKEN in text  # what the next line neutralises is really there
    return re.sub(r"\bstudio\b", SCHEMA, text).replace(TOKEN, NO_TOKEN)


@pytest.fixture
def db():
    with psycopg.connect(DSN, autocommit=True, row_factory=dict_row) as conn:
        conn.execute(f"drop schema if exists {SCHEMA} cascade")
        ddl = _ddl()
        assert TOKEN not in ddl
        conn.execute(ddl)
        again = re.sub(r"\bstudio\b", SCHEMA, (MIGRATIONS / "0016_hits.sql").read_text())
        conn.execute(again)  # re-run safe: the table, its policy, the view, the functions and the grants all take a second run
        conn.execute(
            f"insert into {SCHEMA}.characters (slug, name, bodies, status, setup) values "
            """('reginald', 'Reginald', '{biped}', 'live', '{"stars": ["person"]}'), """
            """('lenny', 'Lenny Gold', '{biped}', 'live', '{"stars": ["person"]}')"""
        )
        yield conn
        conn.execute(f"drop schema if exists {SCHEMA} cascade")


@pytest.fixture
def owner_db(db):
    if not db.execute("select to_regprocedure('auth.jwt()') is not null as ok").fetchone()["ok"]:
        pytest.skip("no auth.jwt() on this database")
    return db


def as_who(db, sql: str, args=(), who: str = OWNER):
    with db.transaction():
        db.execute("select set_config('request.jwt.claims', %s, true)", [who])
        return db.execute(sql, args).fetchone()


def hit(db, url="https://www.tiktok.com/@a/video/1", score=50, status="new", character="reginald", **cols) -> str:
    fields = {"platform": "tiktok", "url": url, "score": score, "status": status, "character_slug": character, **cols}
    names = ", ".join(fields)
    marks = ", ".join(["%s"] * len(fields))
    return str(db.execute(f"insert into {SCHEMA}.hits ({names}) values ({marks}) returning id", list(fields.values())).fetchone()["id"])


def drop_pick(db, **drop_over) -> str:
    src = db.execute(
        f"insert into {SCHEMA}.sources (kind, storage_path, body, duration_s) values ('owner_inbox', 'owner_inbox/x.mp4', 'biped', 20) "
        "returning id"
    ).fetchone()["id"]
    pick_id = str(uuid.uuid4())
    d = {"state": "ready", "kind": "link", "reason": None, "own_footage": False, "character_by": "studio", "star": PERSON,
         "source_id": str(src), **drop_over}  # fmt: skip
    db.execute(
        f"insert into {SCHEMA}.favorites (id, url, platform, origin, character_slug, proposal, status, source_id) "
        "values (%s, %s, 'tiktok', 'owner', 'reginald', %s, 'approved', %s)",
        [pick_id, f"https://www.tiktok.com/@a/video/{uuid.uuid4().int % 10**12}", json.dumps({"drop": d}), src],
    )
    return pick_id


def pick(db, pick_id) -> dict:
    return db.execute(f"select * from {SCHEMA}.favorites where id = %s", [pick_id]).fetchone()


# ---- the table ------------------------------------------------------------------------------------------------------------------


def test_hits_keeps_one_row_per_url_and_refuses_values_the_code_never_writes(db):
    hit(db)
    with pytest.raises(psycopg.errors.UniqueViolation):
        hit(db)
    for bad in ({"platform": "youtube"}, {"score": 101}, {"status": "filed"}, {"views": -1}, {"caption": "x" * 301},
                {"character_slug": "nobody"}):  # fmt: skip
        args = {"url": f"https://www.tiktok.com/@b/video/{uuid.uuid4().int % 10**9}", **bad}
        with pytest.raises((psycopg.errors.CheckViolation, psycopg.errors.ForeignKeyViolation)):
            hit(db, **args)
    general = hit(db, url="https://www.instagram.com/reel/G/", platform="instagram", character=None)
    row = db.execute(f"select * from {SCHEMA}.hits where id = %s", [general]).fetchone()
    assert row["character_slug"] is None and row["status"] == "new" and row["created_at"] and row["last_seen"]


def test_v_hits_lists_the_new_hits_best_first_with_the_characters_name(db):
    low = hit(db, url="https://www.tiktok.com/@a/video/1", score=20)
    top = hit(db, url="https://www.tiktok.com/@a/video/2", score=90, character=None)
    hit(db, url="https://www.tiktok.com/@a/video/3", score=99, status="dismissed")
    hit(db, url="https://www.tiktok.com/@a/video/4", score=95, status="dropped")
    hit(db, url="https://www.tiktok.com/@a/video/5", score=100, posted_at=datetime.now(timezone.utc) - timedelta(days=20))  # weeks old
    recent = hit(db, url="https://www.tiktok.com/@a/video/6", score=50, posted_at=datetime.now(timezone.utc) - timedelta(days=13))
    rows = db.execute(f"select * from {SCHEMA}.v_hits").fetchall()
    assert [str(r["hit_id"]) for r in rows] == [top, recent, low]  # never the weeks-old one, whatever its score
    assert rows[0]["character_name"] is None and rows[1]["character_name"] == "Reginald" and "status" not in rows[0]


def test_the_terminal_reads_hits_and_changes_them_only_through_the_owners_rpcs(db):
    roles = {r["rolname"] for r in db.execute("select rolname from pg_roles where rolname in ('authenticated', 'anon')").fetchall()}
    if "authenticated" in roles:
        for priv, ok in (("select", True), ("insert", False), ("update", False), ("delete", False)):
            assert db.execute("select has_table_privilege('authenticated', %s, %s) as ok", [f"{SCHEMA}.hits", priv]).fetchone()["ok"] is ok
        assert db.execute("select has_table_privilege('authenticated', %s, 'select') as ok", [f"{SCHEMA}.v_hits"]).fetchone()["ok"]
        for fn in ("set_hit_status(uuid, text)", "set_drop_keep(uuid, boolean)", "copy_drop(uuid, text)"):
            assert db.execute("select has_function_privilege('authenticated', %s, 'execute') as ok", [f"{SCHEMA}.{fn}"]).fetchone()["ok"]
    if "anon" in roles:
        assert not db.execute("select has_table_privilege('anon', %s, 'select') as ok", [f"{SCHEMA}.hits"]).fetchone()["ok"]
        for fn in ("set_hit_status(uuid, text)", "set_drop_keep(uuid, boolean)", "copy_drop(uuid, text)"):
            assert not db.execute("select has_function_privilege('anon', %s, 'execute') as ok", [f"{SCHEMA}.{fn}"]).fetchone()["ok"]
    rls = db.execute(
        "select c.relrowsecurity as on_ from pg_class c join pg_namespace n on n.oid = c.relnamespace where n.nspname = %s and c.relname = 'hits'",
        [SCHEMA],
    ).fetchone()
    assert rls["on_"] is True
    policies = db.execute("select policyname from pg_policies where schemaname = %s and tablename = 'hits'", [SCHEMA]).fetchall()
    assert [p["policyname"] for p in policies] == ["owner_all"]  # once, though the migration ran twice


def test_the_days_spend_is_for_the_jobs_alone(db):
    roles = {
        r["rolname"] for r in db.execute("select rolname from pg_roles where rolname in ('authenticated', 'anon', 'service_role')").fetchall()
    }
    assert roles  # Supabase has all three; the test means nothing without them
    for role in roles:
        for priv in ("select", "insert", "update", "delete"):
            assert not db.execute("select has_table_privilege(%s, %s, %s) as ok", [role, f"{SCHEMA}.hits_spend", priv]).fetchone()["ok"]
    rls = db.execute(
        "select c.relrowsecurity as on_ from pg_class c join pg_namespace n on n.oid = c.relnamespace "
        "where n.nspname = %s and c.relname = 'hits_spend'", [SCHEMA],
    ).fetchone()
    assert rls["on_"] is True
    assert db.execute("select count(*) as n from pg_policies where schemaname = %s and tablename = 'hits_spend'", [SCHEMA]).fetchone()["n"] == 0
    with pytest.raises(psycopg.errors.CheckViolation):
        db.execute(f"insert into {SCHEMA}.hits_spend (day, downloads) values ('2026-10-08', -1)")


def test_the_two_indexes_exist(db):
    names = {r["indexname"] for r in db.execute("select indexname from pg_indexes where schemaname = %s and tablename = 'hits'", [SCHEMA])}
    assert {"hits_platform_creator_idx", "hits_status_score_idx"} <= names
    defs = {r["indexname"]: r["indexdef"] for r in db.execute("select indexname, indexdef from pg_indexes where schemaname = %s", [SCHEMA])}
    assert "(platform, creator_handle, created_at)" in defs["hits_platform_creator_idx"]
    assert "(status, score DESC)" in defs["hits_status_score_idx"]


def test_postgres_store_adds_to_the_days_spend(db):
    from datetime import date

    store = PostgresStore(DSN, schema=SCHEMA)
    day = date(2026, 10, 8)
    assert store.get_hit_spend(day).total == 0
    store.add_hit_spend(day, search_credits=25)
    after = store.add_hit_spend(day, download_credits=10, downloads=1)
    assert (after.search_credits, after.download_credits, after.downloads, after.total) == (25, 10, 1, 35) and after.updated_at
    assert store.get_hit_spend(day) == after and store.get_hit_spend(date(2026, 10, 9)).total == 0


# ---- the owner's buttons -------------------------------------------------------------------------------------------------------------


def test_set_hit_status_is_the_owners_alone(owner_db):
    db = owner_db
    h = hit(db)
    out = as_who(db, f"select {SCHEMA}.set_hit_status(%s, 'dismissed') as r", [h])["r"]
    assert out["status"] == "dismissed" and out["id"] == h
    assert as_who(db, f"select {SCHEMA}.set_hit_status(%s, ' dropped ') as r", [h])["r"]["status"] == "dropped"
    with pytest.raises(psycopg.errors.InvalidParameterValue):
        as_who(db, f"select {SCHEMA}.set_hit_status(%s, 'maybe') as r", [h])
    with pytest.raises(psycopg.errors.NoDataFound):
        as_who(db, f"select {SCHEMA}.set_hit_status(%s, 'new') as r", [str(uuid.uuid4())])
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        as_who(db, f"select {SCHEMA}.set_hit_status(%s, 'new') as r", [h], who=STRANGER)
    assert db.execute(f"select status from {SCHEMA}.hits where id = %s", [h]).fetchone()["status"] == "dropped"


def test_set_drop_keep_marks_a_drop_and_refuses_anything_else(owner_db):
    db = owner_db
    p = drop_pick(db)
    assert as_who(db, f"select {SCHEMA}.set_drop_keep(%s, true) as r", [p])["r"]["proposal"]["drop"]["keep"] is True
    assert as_who(db, f"select {SCHEMA}.set_drop_keep(%s, false) as r", [p])["r"]["proposal"]["drop"]["keep"] is False
    plain = db.execute(
        f"insert into {SCHEMA}.favorites (url, platform, character_slug, status) values ('https://x', 'tiktok', 'reginald', 'approved') returning id"
    ).fetchone()["id"]
    with pytest.raises(psycopg.errors.CheckViolation):
        as_who(db, f"select {SCHEMA}.set_drop_keep(%s, true) as r", [plain])
    with pytest.raises(psycopg.errors.InvalidParameterValue):
        as_who(db, f"select {SCHEMA}.set_drop_keep(%s, null) as r", [p])
    with pytest.raises(psycopg.errors.NoDataFound):
        as_who(db, f"select {SCHEMA}.set_drop_keep(%s, true) as r", [str(uuid.uuid4())])
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        as_who(db, f"select {SCHEMA}.set_drop_keep(%s, true) as r", [p], who=STRANGER)
    assert pick(db, p)["proposal"]["drop"]["keep"] is False


def test_copy_drop_carries_the_hits_jobs_tag_into_a_version(owner_db):
    db = owner_db
    tagged = drop_pick(db, auto_filed=True)
    out = as_who(db, f"select {SCHEMA}.copy_drop(%s, 'lenny') as r", [tagged])["r"]
    assert out["dispatched"] is False  # no token in the test schema: nothing is sent
    assert pick(db, out["pick_id"])["proposal"]["drop"]["auto_filed"] is True
    plain = drop_pick(db)
    v = pick(db, as_who(db, f"select {SCHEMA}.copy_drop(%s, 'lenny') as r", [plain])["r"]["pick_id"])
    assert "auto_filed" not in v["proposal"]["drop"]  # no tag on the root: none on the version (0015's version, word for word)


# ---- PostgresStore's hits methods -------------------------------------------------------------------------------------------------


def test_postgres_store_upserts_lists_and_updates_hits(db):
    store = PostgresStore(DSN, schema=SCHEMA)
    url = "https://www.tiktok.com/@a/video/77"
    first, created = store.upsert_hit(Hit(platform="tiktok", url=url, views=100, likes=10, keyword="dog dance", character_slug="reginald",
                                          score=40, posted_at=NOW, created_at=NOW, last_seen=NOW))  # fmt: skip
    assert created is True and first.id and first.views == 100
    store.update_hit(first.id, status="dismissed")
    later = NOW + timedelta(days=1)
    again, created = store.upsert_hit(Hit(platform="tiktok", url=url, views=900, keyword="trending", score=70, created_at=later,
                                          last_seen=later))  # fmt: skip
    assert created is False and again.id == first.id
    assert (again.views, again.likes, again.score, again.status, again.keyword, again.character_slug) == (
        900, 10, 70, "dismissed", "dog dance", "reginald")
    assert again.created_at == NOW and again.last_seen == later and again.posted_at == NOW
    assert [h.id for h in store.list_hits(status="dismissed")] == [first.id] and store.get_hit(first.id) == again
    assert store.get_hit(str(uuid.uuid4())) is None and store.get_hit("nope") is None
    with pytest.raises(KeyError):
        store.update_hit(str(uuid.uuid4()), status="new")
