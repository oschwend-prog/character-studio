"""Migration 0012 against a real Postgres: add_drop files a drop, request_job is the owner's button and v_tracker shows the card.

Skipped unless ``DATABASE_URL_TEST`` is set; see ``test_pgstore.py`` for what the database needs. The schema is built from every
migration, renamed ``studio_test``, and dropped afterwards. request_job needs Supabase's ``auth.jwt()`` (it reads the claims of
``request.jwt.claims``): those tests are skipped on a database without it. No dispatch leaves the database here: the Vault holds
no ``github_dispatch_token`` in a test project (``dispatched`` is false). NOT run when this file was written (no Postgres on the
machine): ``tests/test_schema.py`` pins the text, this file pins the behaviour once a database is at hand.
"""

import json
import os
import re
from pathlib import Path

import psycopg
import pytest
from psycopg.rows import dict_row

DSN = os.environ.get("DATABASE_URL_TEST")
pytestmark = pytest.mark.skipif(not DSN, reason="DATABASE_URL_TEST is not set")

SCHEMA = "studio_test"
MIGRATIONS = Path(__file__).resolve().parents[2] / "supabase" / "migrations"
OWNER = json.dumps({"email": "o.schwend@gmail.com"})
TIKTOK = "https://www.tiktok.com/@dancer.one/video/7688386199270001953"


def _ddl() -> str:
    text = "\n".join(f.read_text() for f in sorted(MIGRATIONS.glob("*.sql")))
    return re.sub(r"\bstudio\b", SCHEMA, text)


@pytest.fixture
def db():
    with psycopg.connect(DSN, autocommit=True, row_factory=dict_row) as conn:
        conn.execute(f"drop schema if exists {SCHEMA} cascade")
        conn.execute(_ddl())
        conn.execute(f"insert into {SCHEMA}.characters (slug, name, bodies) values ('reginald', 'Reginald', '{{biped}}')")
        yield conn
        conn.execute(f"drop schema if exists {SCHEMA} cascade")


def has_auth(db) -> bool:
    return db.execute("select to_regprocedure('auth.jwt()') is not null as ok").fetchone()["ok"]


def as_owner(db, sql: str, args=(), who: str = OWNER):
    with db.transaction():
        db.execute("select set_config('request.jwt.claims', %s, true)", [who])
        return db.execute(sql, args).fetchone()


def test_add_drop_files_a_file_and_a_link(db):
    f = db.execute(f"select {SCHEMA}.add_drop('reginald') as r").fetchone()["r"]
    assert f["url"] == f"owner-drop:{f['id']}" and f["platform"] == "drop" and f["status"] == "approved"
    assert f["proposal"]["drop"]["state"] == "uploading" and f["proposal"]["decision"]["by"] == "owner"
    link = db.execute(f"select {SCHEMA}.add_drop('reginald', %s) as r", [TIKTOK]).fetchone()["r"]
    assert link["creator_handle"] == "@dancer.one" and link["proposal"]["drop"]["state"] == "checking" and not link["duplicate"]
    again = db.execute(f"select {SCHEMA}.add_drop('reginald', %s) as r", [TIKTOK]).fetchone()["r"]
    assert again["id"] == link["id"] and again["duplicate"]
    with pytest.raises(psycopg.errors.InvalidParameterValue):
        db.execute(f"select {SCHEMA}.add_drop('reginald', 'https://vm.tiktok.com/x/')")


def test_request_job_is_the_owners_and_make_it_needs_a_priced_drop(db):
    if not has_auth(db):
        pytest.skip("no auth.jwt() on this database")
    pick = db.execute(f"select {SCHEMA}.add_drop('reginald', %s) as r", [TIKTOK]).fetchone()["r"]["id"]
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        as_owner(db, f"select {SCHEMA}.request_job(%s, 'process') as r", [pick], who=json.dumps({"email": "someone@else.com"}))
    r = as_owner(db, f"select {SCHEMA}.request_job(%s, 'process') as r", [pick])["r"]
    assert r["proposal"]["drop"]["state"] == "checking" and r["dispatched"] is False and "token" not in json.dumps(r)
    with pytest.raises(psycopg.errors.CheckViolation):  # not checked and priced yet
        as_owner(db, f"select {SCHEMA}.request_job(%s, 'make') as r", [pick])
    db.execute(
        f"update {SCHEMA}.favorites set proposal = jsonb_set(proposal, '{{drop}}', proposal -> 'drop' || "
        "'{\"state\": \"ready\", \"credits\": 91, \"source_id\": \"s\", \"duration_s\": 12, \"window\": {\"start_s\": 1, \"length_s\": 8}}') "
        "where id = %s", [pick],
    )
    with pytest.raises(psycopg.errors.InvalidParameterValue):
        as_owner(db, f"select {SCHEMA}.request_job(%s, 'make', %s) as r", [pick, json.dumps({"length_s": 30})])
    r = as_owner(db, f"select {SCHEMA}.request_job(%s, 'make', %s) as r", [pick, json.dumps({"part": "star", "start_s": 2, "length_s": 9})])["r"]
    assert r["proposal"]["make_requested"]["by"] == "owner" and r["proposal"]["drop"]["state"] == "making"
    assert r["proposal"]["drop"]["adjust"] == {"part": "star", "start_s": 2, "length_s": 9}
    row = db.execute(f"select drop_card, make_requested_at from {SCHEMA}.v_tracker where pick_id = %s", [pick]).fetchone()
    assert row["drop_card"]["state"] == "making" and row["make_requested_at"]
