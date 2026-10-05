"""Migration 0010 against a real Postgres: the long list's columns and the "In the works" tracker.

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

LONGLIST = {
    "recognisability": 9,
    "original_views": 6083137818,
    "original_url": "https://www.youtube.com/watch?v=9bZkp7q19f0",
    "source_status": "needs a clean clip (recreate fallback)",
    "audio_risk": "chart song: Instagram may mute it, fallback in-app",
    "est_credits": 160,
    "season": "24-31 Oct",
    "checks": ["not in the same fortnight as Reginald's"],
    "source_candidates": [{"id": "0r55UgS2yOo", "views": 4591225, "why": "solo tutorial"}],
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


def add_pick(db, status="new", url=URL, proposal=None, clip_id=None) -> str:
    row = db.execute(
        f"insert into {SCHEMA}.favorites (url, platform, creator_handle, views, outlier_x, character_slug, proposal, scores, "
        "total_score, status, clip_id) values (%s, 'tiktok', '@tillandsialover', 3100000, 40, 'biscuit', %s::jsonb, "
        "'{\"fit\": 8}'::jsonb, 80, %s, %s) returning id",
        [url, json.dumps(proposal or {"mode": "dropin"}), status, clip_id],
    ).fetchone()
    return str(row["id"])


def add_clip(db, state="planned", features=None, qa=None, reject_reason=None, ago="1 hour") -> str:
    row = db.execute(
        f"insert into {SCHEMA}.clips (character_slug, mode, state, features, qa, reject_reason, created_at) "
        f"values ('biscuit', 'dropin', %s, %s::jsonb, %s::jsonb, %s, now() - %s::interval) returning id",
        [state, json.dumps(features or {}), json.dumps(qa or {}), reject_reason, ago],
    ).fetchone()
    return str(row["id"])


def add_account(db, platform="tiktok") -> str:
    row = db.execute(
        f"insert into {SCHEMA}.accounts (character_slug, platform, handle) values ('biscuit', %s, %s) returning id",
        [platform, f"@biscuit.{platform}"],
    ).fetchone()
    return str(row["id"])


def add_post(db, clip, account, status="scheduled", slot="now() + interval '1 day'", claimed=None, error=None) -> str:
    row = db.execute(
        f"insert into {SCHEMA}.posts (clip_id, account_id, scheduled_for, status, claimed_at, error) "
        f"values (%s, %s, {slot}, %s, {claimed or 'null'}, %s) returning id",
        [clip, account, status, error],
    ).fetchone()
    return str(row["id"])


def tracker(db) -> dict[str, dict]:
    return {str(r["pick_id"]): r for r in db.execute(f"select * from {SCHEMA}.v_tracker").fetchall()}


def test_the_picks_views_carry_the_long_list_and_null_a_malformed_value(db):
    pick = add_pick(db, proposal={"mode": "recreate", **LONGLIST})
    (p,) = db.execute(f"select * from {SCHEMA}.v_picks where id = %s", [pick]).fetchall()
    assert (p["recognisability"], p["original_views"], p["est_credits"]) == (9, 6083137818, 160)
    assert p["checks"] == LONGLIST["checks"] and p["source_candidates"][0]["id"] == "0r55UgS2yOo"
    assert p["season"] == "24-31 Oct" and p["original_url"].startswith("https://www.youtube.com/")
    odd = add_pick(db, url=URL + "o", proposal={"recognisability": "high", "checks": "one string", "source_candidates": {}})
    (q,) = db.execute(f"select recognisability, checks, source_candidates from {SCHEMA}.v_picks where id = %s", [odd]).fetchall()
    assert (q["recognisability"], q["checks"], q["source_candidates"]) == (None, None, None)
    decided = add_pick(db, status="approved", url=URL + "h", proposal={"mode": "recreate", **LONGLIST})
    (h,) = db.execute(f"select * from {SCHEMA}.v_pick_history where id = %s", [decided]).fetchall()
    assert h["recognisability"] == 9 and h["checks"] == LONGLIST["checks"]


def test_the_tracker_lists_approved_picks_until_a_week_after_the_post(db):
    acc = add_account(db)
    new = add_pick(db, url=URL + "n")
    skipped = add_pick(db, status="skipped", url=URL + "s")
    approved = add_pick(db, status="approved", url=URL + "a")
    waiting = add_clip(db, state="awaiting_approval")
    made_waiting = add_pick(db, status="made", url=URL + "w", clip_id=waiting)
    fresh = add_clip(db, state="posted")
    add_post(db, fresh, acc, status="posted", slot="now() - interval '2 days'", claimed="now() - interval '2 days'")
    made_fresh = add_pick(db, status="made", url=URL + "f", clip_id=fresh)
    old = add_clip(db, state="posted", ago="20 days")
    add_post(db, old, acc, status="posted", slot="now() - interval '9 days'", claimed="now() - interval '9 days'")
    made_old = add_pick(db, status="made", url=URL + "o", clip_id=old)
    rows = tracker(db)
    assert approved in rows and made_waiting in rows and made_fresh in rows
    assert new not in rows and skipped not in rows and made_old not in rows
    assert rows[made_waiting]["post_id"] is None  # no post yet, and still listed
    assert rows[made_fresh]["post_status"] == "posted" and rows[made_fresh]["post_posted_at"] is not None


def test_the_tracker_shows_the_newest_clip_its_credits_and_the_post_that_needs_a_look(db):
    acc_tt, acc_ig = add_account(db, "tiktok"), add_account(db, "instagram")
    first = add_clip(db, state="rejected", reject_reason="regenerate: slower", ago="2 days")
    pick = add_pick(db, status="made", url=URL + "r", clip_id=first)
    again = add_clip(db, state="scheduled", features={"fav_id": pick, "regenerate_of": first})
    for clip, credits in ((first, 120), (again, 95)):
        db.execute(f"insert into {SCHEMA}.ledger (clip_id, month, kind, credits) values (%s, '2026-10', 'reserve', 160)", [clip])
        db.execute(f"insert into {SCHEMA}.ledger (clip_id, month, kind, credits) values (%s, '2026-10', 'settle', %s)", [clip, credits])
    add_post(db, again, acc_tt, status="posted", slot="now() - interval '1 hour'", claimed="now() - interval '1 hour'")
    bad = add_post(db, again, acc_ig, status="needs_check", slot="now() - interval '1 hour'", error="Postiz timed out")
    db.execute(f"insert into {SCHEMA}.snapshots (post_id, views, captured_at) values (%s, 10, now() - interval '2 hours')", [bad])
    db.execute(f"insert into {SCHEMA}.snapshots (post_id, views, captured_at) values (%s, 99, now())", [bad])
    row = tracker(db)[pick]
    assert str(row["clip_id"]) == again and row["clip_state"] == "scheduled"  # the remake, not the rejected first try
    assert row["credits_spent"] == 215  # both attempts' settles, never the reserves
    assert str(row["post_id"]) == bad and row["post_status"] == "needs_check" and row["post_error"] == "Postiz timed out"
    assert row["latest_views"] == 99


def test_the_tracker_says_why_a_clip_failed_and_when_its_state_last_moved(db):
    qa = add_clip(db, state="qa_failed", qa={"problems": ["the quiff moves at 4 s", "smile at 6 s"]}, ago="8 hours")
    db.execute(f"insert into {SCHEMA}.ledger (clip_id, month, kind, credits, created_at) values (%s, '2026-10', 'settle', 160, now() - interval '7 hours')", [qa])
    pick = add_pick(db, status="queued", url=URL + "q", clip_id=qa)
    row = tracker(db)[pick]
    assert row["clip_failure"] == "the quiff moves at 4 s / smile at 6 s"
    hours = db.execute("select extract(epoch from now() - %s::timestamptz) / 3600 as h", [row["clip_state_since"]]).fetchone()["h"]
    assert 6.9 < float(hours) < 7.1  # the settle, not the clip's creation
    plain = add_pick(db, status="approved", url=URL + "p", proposal={"mode": "dropin", "owner_mode": "recreate", "owner_music": "ai_beat"})
    p = tracker(db)[plain]
    assert (p["clip_id"], p["clip_failure"], p["credits_spent"], p["owner_mode"], p["owner_music"]) == (None, None, 0, "recreate", "ai_beat")
    assert p["approved_at"] is not None
