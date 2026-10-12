"""Migration 0017 against a real Postgres: add_drop keeps the earlier drop's keys when the same link is dropped again.

Skipped unless ``DATABASE_URL_TEST`` is set; see ``test_pgstore.py`` for what the database needs. The schema is built from every
migration, renamed ``studio_test``, and dropped afterwards. No dispatch leaves the database: ``_ddl`` points every Vault lookup of
the TEST schema at a secret name that does not exist (as ``test_migration_0015.py`` does). NOT run when this file was written (no
Postgres on the machine): ``tests/test_schema.py`` pins the text, this file pins the behaviour once a database is at hand.
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
TOKEN = "'github_dispatch_token'"
NO_TOKEN = "'github_dispatch_token_absent_in_tests'"
TIKTOK = "https://www.tiktok.com/@dancer.one/video/7688386199270001953"


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
        conn.execute(
            f"insert into {SCHEMA}.characters (slug, name, bodies, status) values "
            "('franz', 'Franz', '{quadruped}', 'live'), ('reginald', 'Reginald', '{biped}', 'live')"
        )
        yield conn
        conn.execute(f"drop schema if exists {SCHEMA} cascade")


def add_drop(db, slug, link):
    return db.execute(f"select {SCHEMA}.add_drop(%s, %s) as r", [slug, link]).fetchone()["r"]


def test_a_link_dropped_again_keeps_the_earlier_drops_keys_and_the_new_keys_win(db):
    first = add_drop(db, "reginald", TIKTOK)
    assert first["duplicate"] is False and first["proposal"]["drop"]["state"] == "checking"
    earlier = {"state": "ready", "hooks": ["a", "b"], "window": {"start_s": 1, "length_s": 8}, "adjust": {"hook": "x"}, "own_footage": True}
    db.execute(
        f"update {SCHEMA}.favorites set proposal = jsonb_set(proposal, '{{drop}}', (proposal -> 'drop') || %s::jsonb) where id = %s",
        [json.dumps(earlier), first["id"]],
    )
    again = add_drop(db, "reginald", TIKTOK)
    assert again["duplicate"] is True and again["id"] == first["id"]
    d = again["proposal"]["drop"]
    assert d["hooks"] == ["a", "b"] and d["window"] == {"start_s": 1, "length_s": 8} and d["adjust"] == {"hook": "x"}  # kept
    assert d["state"] == "checking" and d["own_footage"] is False and d["character_by"] == "owner" and d["reason"] is None  # new wins
    assert again["status"] == "approved" and again["proposal"]["decision"]["decision"] == "approve"


def test_a_drop_that_is_no_object_is_replaced_not_merged(db):
    first = add_drop(db, "franz", TIKTOK)
    db.execute(f"update {SCHEMA}.favorites set proposal = jsonb_set(proposal, '{{drop}}', 'null'::jsonb) where id = %s", [first["id"]])
    d = add_drop(db, "franz", TIKTOK)["proposal"]["drop"]
    assert isinstance(d, dict) and d["state"] == "checking" and d["kind"] == "link"  # not [null, {...}]


def test_a_made_pick_is_returned_untouched(db):
    first = add_drop(db, "reginald", TIKTOK)
    db.execute(f"update {SCHEMA}.favorites set status = 'made' where id = %s", [first["id"]])
    again = add_drop(db, "reginald", TIKTOK)
    assert again["duplicate"] is True and again["proposal"]["drop"] == first["proposal"]["drop"]
