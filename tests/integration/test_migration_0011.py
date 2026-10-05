"""Migration 0011 against a real Postgres: decide_pick stores when the owner decided, and v_tracker counts from it.

Skipped unless ``DATABASE_URL_TEST`` is set; see ``test_pgstore.py`` for what the database needs. The schema is built from
every migration, renamed ``studio_test``, and dropped afterwards. NOT run when this file was written (no Postgres on the
machine): the schema tests in ``tests/test_schema.py`` pin the text, this file pins the behaviour once a database is at hand.
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
URL = "https://www.tiktok.com/@tillandsialover/video/7688386199270001953"



def _ddl() -> str:
    text = "\n".join(f.read_text() for f in sorted(MIGRATIONS.glob("*.sql")))
    return re.sub(r"\bstudio\b", SCHEMA, text)


@pytest.fixture
def db():
    with psycopg.connect(DSN, autocommit=True, row_factory=dict_row) as conn:
        conn.execute(f"drop schema if exists {SCHEMA} cascade")
        conn.execute(_ddl())
        conn.execute(f"insert into {SCHEMA}.characters (slug, name, bodies) values ('biscuit', 'Biscuit', '{{quadruped}}')")
        yield conn
        conn.execute(f"drop schema if exists {SCHEMA} cascade")


def add_pick(db, status="new", url=URL, proposal=None, clip_id=None) -> str:
    row = db.execute(
        f"insert into {SCHEMA}.favorites (url, platform, creator_handle, views, outlier_x, character_slug, proposal, scores, "
        "total_score, status, clip_id) values (%s, 'tiktok', '@tillandsialover', 3100000, 40, 'biscuit', %s::jsonb, "
        "'{\"fit\": 8}'::jsonb, 80, %s, %s) returning id",
        [url, json.dumps(proposal or {"mode": "dropin"}), status, clip_id],
    ).fetchone()
    return str(row["id"])


def tracker(db) -> dict[str, dict]:
    return {str(r["pick_id"]): r for r in db.execute(f"select * from {SCHEMA}.v_tracker").fetchall()}


def test_decide_pick_stores_when_the_owner_decided_and_the_tracker_counts_from_it(db):
    old = add_pick(db, url=URL + "d")
    db.execute(f"update {SCHEMA}.favorites set created_at = now() - interval '3 days' where id = %s", [old])
    out = db.execute(f"select {SCHEMA}.decide_pick(%s, 'approve') as r", [old]).fetchone()["r"]
    assert out["proposal"]["decision"]["at"]  # 'at', now(): an ISO time
    row = tracker(db)[old]
    assert row["decided_at"] == row["approved_at"]
    hours = db.execute("select extract(epoch from now() - %s::timestamptz) / 3600 as h", [row["approved_at"]]).fetchone()["h"]
    assert float(hours) < 1  # the decision, not the filing three days ago


def test_a_record_without_a_valid_time_falls_back_to_the_filing_time(db):
    for n, bad in enumerate((None, "yesterday", "2026-02-30T10:00:00+00:00", "2026-13-01T10:00:00Z", 42)):
        decision = {"decision": "approve", "by": "rule", "reason": None}
        if bad is not None:
            decision["at"] = bad
        pick = add_pick(db, status="approved", url=f"{URL}{n}", proposal={"mode": "dropin", "decision": decision})
        r = tracker(db)[pick]  # never an error for the whole view
        created = db.execute(f"select created_at from {SCHEMA}.favorites where id = %s", [pick]).fetchone()["created_at"]
        assert (r["approved_at"], r["decided_at"]) == (created, None), bad


def test_there_is_still_exactly_one_decide_pick(db):
    (row,) = db.execute(
        "select count(*) as n from pg_proc p join pg_namespace n on n.oid = p.pronamespace where n.nspname = %s and p.proname = 'decide_pick'",
        [SCHEMA],
    ).fetchall()
    assert row["n"] == 1
