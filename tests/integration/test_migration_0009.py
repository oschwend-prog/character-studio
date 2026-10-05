"""Migration 0009 against a real Postgres: the picks views carry the analyst's data.

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

ANALYST = {
    "velocity": 310000,
    "engagement": {"likes": 90000, "shares": 31000},
    "saturation_count": 3,
    "trait_matches": ["slick upright dance", "hits every beat"],
    "why": "One animal, static camera, full body.",
    "analysis": {"people_count": 1, "camera": "static", "watermark": False, "overlay": False, "minors": False},
}


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


def add_pick(db, status="new", url=URL, proposal=None) -> str:
    row = db.execute(
        f"insert into {SCHEMA}.favorites (url, platform, creator_handle, views, outlier_x, character_slug, proposal, scores, "
        "total_score, status) values (%s, 'tiktok', '@tillandsialover', 3100000, 40, 'biscuit', %s::jsonb, "
        "'{\"fit\": 8}'::jsonb, 80, %s) returning id",
        [url, json.dumps(proposal or {"mode": "dropin"}), status],
    ).fetchone()
    return str(row["id"])


def test_the_views_carry_the_analysts_data(db):
    pick = add_pick(db, proposal={"mode": "dropin", **ANALYST})
    (p,) = db.execute(f"select * from {SCHEMA}.v_picks where id = %s", [pick]).fetchall()
    assert p["velocity"] == 310000 and p["saturation_count"] == 3
    assert p["engagement"] == {"likes": 90000, "shares": 31000}
    assert p["trait_matches"] == ["slick upright dance", "hits every beat"]
    assert p["why"] == "One animal, static camera, full body."
    assert p["analysis"]["camera"] == "static" and p["analysis"]["minors"] is False
    decided = add_pick(db, status="approved", url=URL + "h", proposal={"mode": "dropin", **ANALYST})
    (h,) = db.execute(f"select * from {SCHEMA}.v_pick_history where id = %s", [decided]).fetchall()
    assert h["velocity"] == 310000 and h["trait_matches"] == ANALYST["trait_matches"] and h["analysis"] == ANALYST["analysis"]


def test_absent_or_malformed_values_come_back_null_never_zero(db):
    plain = add_pick(db)
    (q,) = db.execute(f"select * from {SCHEMA}.v_picks where id = %s", [plain]).fetchall()
    for column in ("velocity", "engagement", "saturation_count", "trait_matches", "why", "analysis"):
        assert q[column] is None, column
    odd = add_pick(db, url=URL + "o", proposal={"mode": "dropin", "velocity": "fast", "saturation_count": None})
    (r,) = db.execute(f"select velocity, saturation_count from {SCHEMA}.v_picks where id = %s", [odd]).fetchall()
    assert (r["velocity"], r["saturation_count"]) == (None, None)  # studio.num: a string is no number


def test_the_earlier_columns_are_still_there_in_the_same_order(db):
    names = [
        r["column_name"]
        for r in db.execute(
            "select column_name from information_schema.columns where table_schema = %s and table_name = 'v_picks' "
            "order by ordinal_position", [SCHEMA],
        ).fetchall()
    ]
    tail = ["gallery", "thumbnail_url", "preview_url", "velocity", "engagement", "saturation_count", "trait_matches", "why", "analysis"]
    assert names[-len(tail) :] == tail  # the card of 0008 first, then the analyst's six, appended
