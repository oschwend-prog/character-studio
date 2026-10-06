"""Migration 0013 against a real Postgres: a drop without a character, and the owner's character menu (set_drop_character).

Skipped unless ``DATABASE_URL_TEST`` is set; see ``test_pgstore.py`` for what the database needs. The schema is built from every
migration, renamed ``studio_test``, and dropped afterwards. set_drop_character needs Supabase's ``auth.jwt()``: those tests are
skipped on a database without it. No dispatch leaves the database (no ``github_dispatch_token`` in a test Vault: ``dispatched``
is false). NOT run when this file was written (no Postgres on the machine): ``tests/test_schema.py`` pins the text, this file
pins the behaviour once a database is at hand.
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
        conn.execute(
            f"insert into {SCHEMA}.characters (slug, name, bodies, status) values "
            "('franz', 'Franz', '{quadruped}', 'designing'), ('lenny', 'Lenny Gold', '{biped}', 'designing'), "
            "('reginald', 'Reginald', '{biped}', 'live'), ('biscuit', 'Biscuit', '{biped,quadruped}', 'paused')"
        )
        yield conn
        conn.execute(f"drop schema if exists {SCHEMA} cascade")


def has_auth(db) -> bool:
    return db.execute("select to_regprocedure('auth.jwt()') is not null as ok").fetchone()["ok"]


def as_owner(db, sql: str, args=(), who: str = OWNER):
    with db.transaction():
        db.execute("select set_config('request.jwt.claims', %s, true)", [who])
        return db.execute(sql, args).fetchone()


def test_a_drop_without_a_character_waits_under_the_first_who_replaces_a_person(db):
    f = db.execute(f"select {SCHEMA}.add_drop() as r").fetchone()["r"]
    assert f["character_slug"] == "lenny" and f["proposal"]["drop"]["character_by"] == "studio"  # by slug; Franz is four-legged
    # the seeded swap rule wins over the bodies
    db.execute(f"""update {SCHEMA}.characters set setup = '{{"swap": {{"stars": ["dog"]}}}}' where slug = 'lenny'""")
    assert db.execute(f"select {SCHEMA}.add_drop(null) as r").fetchone()["r"]["character_slug"] == "reginald"
    owners = db.execute(f"select {SCHEMA}.add_drop('franz') as r").fetchone()["r"]
    assert owners["proposal"]["drop"]["character_by"] == "owner"
    # a link without a character takes the pick of that URL, whichever character it is, and keeps him
    first = db.execute(f"select {SCHEMA}.add_drop('franz', %s) as r", [TIKTOK]).fetchone()["r"]
    again = db.execute(f"select {SCHEMA}.add_drop(null, %s) as r", [TIKTOK]).fetchone()["r"]
    assert again["id"] == first["id"] and again["duplicate"] and again["character_slug"] == "franz"
    db.execute(f"update {SCHEMA}.characters set status = 'paused' where slug <> 'biscuit'")
    with pytest.raises(psycopg.errors.InvalidParameterValue):
        db.execute(f"select {SCHEMA}.add_drop() as r")


def test_set_drop_character_is_the_owners_and_asks_for_the_check_again(db):
    if not has_auth(db):
        pytest.skip("no auth.jwt() on this database")
    pick = db.execute(f"select {SCHEMA}.add_drop('reginald', %s) as r", [TIKTOK]).fetchone()["r"]["id"]
    db.execute(
        f"update {SCHEMA}.favorites set proposal = proposal || jsonb_build_object('hook', 'x', 'make_requested', '{{}}'::jsonb, 'drop', "
        "proposal -> 'drop' || '{\"state\": \"ready\", \"credits\": 91, \"source_id\": \"s\", \"hooks\": [\"a\"], \"hook\": \"a\", "
        "\"window\": {\"start_s\": 1, \"length_s\": 8}, \"deconstruct\": {}, \"star\": {\"kind\": \"dog\"}, "
        "\"recommended\": {\"slug\": \"franz\", \"reason\": \"dog\"}}'::jsonb) where id = %s", [pick],
    )
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        as_owner(db, f"select {SCHEMA}.set_drop_character(%s, 'franz') as r", [pick], who=json.dumps({"email": "someone@else.com"}))
    for bad in ("biscuit", "nobody"):  # paused, unknown
        with pytest.raises(psycopg.errors.InvalidParameterValue):
            as_owner(db, f"select {SCHEMA}.set_drop_character(%s, %s) as r", [pick, bad])
    r = as_owner(db, f"select {SCHEMA}.set_drop_character(%s, 'franz') as r", [pick])["r"]
    d = r["proposal"]["drop"]
    assert r["character_slug"] == "franz" and d["character_by"] == "owner" and d["state"] == "checking" and r["dispatched"] is False
    assert d["requested"]["process"] and not {"hooks", "hook", "credits", "window", "deconstruct"} & set(d)
    assert d["star"] == {"kind": "dog"} and d["recommended"]["slug"] == "franz" and d["source_id"] == "s"
    assert "hook" not in r["proposal"] and "make_requested" not in r["proposal"]
    same = as_owner(db, f"select {SCHEMA}.set_drop_character(%s, 'franz') as r", [pick])["r"]
    assert same["dispatched"] is False and same["proposal"]["drop"]["state"] == "checking"
    db.execute(f"update {SCHEMA}.favorites set status = 'queued' where id = %s", [pick])
    with pytest.raises(psycopg.errors.CheckViolation):
        as_owner(db, f"select {SCHEMA}.set_drop_character(%s, 'lenny') as r", [pick])


def test_an_upload_without_its_file_keeps_uploading(db):
    if not has_auth(db):
        pytest.skip("no auth.jwt() on this database")
    pick = db.execute(f"select {SCHEMA}.add_drop() as r").fetchone()["r"]["id"]
    r = as_owner(db, f"select {SCHEMA}.set_drop_character(%s, 'franz') as r", [pick])["r"]
    assert r["proposal"]["drop"]["state"] == "uploading" and r["character_slug"] == "franz" and r["dispatched"] is False
