"""Migration 0008 against a real Postgres: decide_pick with gadgets and music, attach_clip, the share-of-one rule, the card views.

Skipped unless ``DATABASE_URL_TEST`` is set; see ``test_pgstore.py`` for what the database needs. The schema is built from
every migration, renamed ``studio_test``, and dropped afterwards. Calls go through the functions exactly as PostgREST makes
them (named arguments). NOT run when this file was written (no Postgres on the machine): the schema tests in
``tests/test_schema.py`` pin the text, this file pins the behaviour once a database is at hand.
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
URL = "https://www.instagram.com/reel/Dde-rPWCOC6/"


def _ddl() -> str:
    text = "\n".join(f.read_text() for f in sorted(MIGRATIONS.glob("*.sql")))
    return re.sub(r"\bstudio\b", SCHEMA, text)


@pytest.fixture
def db():
    with psycopg.connect(DSN, autocommit=True, row_factory=dict_row) as conn:
        conn.execute(f"drop schema if exists {SCHEMA} cascade")
        conn.execute(_ddl())
        conn.execute(
            f"insert into {SCHEMA}.characters (slug, name, bodies) values "
            "('biscuit', 'Biscuit', '{quadruped}'), ('reginald', 'Reginald', '{biped}')"
        )
        yield conn
        conn.execute(f"drop schema if exists {SCHEMA} cascade")


def add_pick(db, slug="reginald", status="new", url=URL, proposal=None) -> str:
    row = db.execute(
        f"insert into {SCHEMA}.favorites (url, platform, creator_handle, views, outlier_x, character_slug, proposal, scores, "
        "total_score, status) values (%s, 'instagram', '@eatfryhaven', 43400000, 1392.8, %s, %s::jsonb, "
        "'{\"fit\": 10}'::jsonb, 92, %s) returning id",
        [url, slug, json.dumps(proposal or {"mode": "recreate", "hook": "first day"}), status],
    ).fetchone()
    return str(row["id"])


def decide(db, pick_id, decision="approve", **named):
    args = {"pick_id": pick_id, "decision": decision, **named}
    sql = ", ".join(f"{k} := %({k})s" for k in args)
    return db.execute(f"select {SCHEMA}.decide_pick({sql}) as r", args).fetchone()["r"]


def attach(db, pick_id, path):
    return db.execute(f"select {SCHEMA}.attach_clip(%s::uuid, %s) as r", [pick_id, path]).fetchone()["r"]


def test_there_is_still_exactly_one_decide_pick_and_it_takes_ten_arguments():
    with psycopg.connect(DSN, autocommit=True) as conn:
        conn.execute(f"drop schema if exists {SCHEMA} cascade")
        conn.execute(_ddl())
        rows = conn.execute(
            "select p.pronargs from pg_proc p join pg_namespace n on n.oid = p.pronamespace "
            "where n.nspname = %s and p.proname = 'decide_pick'", [SCHEMA],
        ).fetchall()
        conn.execute(f"drop schema if exists {SCHEMA} cascade")
    assert [r[0] for r in rows] == [10]


def test_the_calls_of_0007_still_work_unchanged(db):
    out = decide(db, add_pick(db), owner_note="slow-mo", owner_mode="dropin", owner_presence="star")
    assert out["proposal"]["owner_presence"] == "star" and "owner_props" not in out["proposal"]


def test_gadgets_are_trimmed_stored_as_an_array_and_a_blank_keeps_what_is_stored(db):
    pick = add_pick(db)
    out = decide(db, pick, owner_props=["  tiny gold chain ", "aviator shades"])
    assert out["proposal"]["owner_props"] == ["tiny gold chain", "aviator shades"]
    kept = decide(db, pick, owner_props=[])
    assert kept["proposal"]["owner_props"] == ["tiny gold chain", "aviator shades"]
    replaced = decide(db, pick, owner_props=["bucket hat"])
    assert replaced["proposal"]["owner_props"] == ["bucket hat"]
    skipped = decide(db, add_pick(db, url=URL + "s"), "skip", reason="seen it", owner_props=["x"])
    assert "owner_props" not in skipped["proposal"]


@pytest.mark.parametrize(
    ("props", "message"),
    [(["a", "b", "c", "d"], "at most 3"), ([""], "1 to 40"), (["  "], "1 to 40"), (["x" * 41], "1 to 40")],
)
def test_bad_gadgets_are_refused_before_anything_is_written(db, props, message):
    pick = add_pick(db)
    with pytest.raises(psycopg.errors.Error, match=message):
        decide(db, pick, owner_props=props)
    assert db.execute(f"select status from {SCHEMA}.favorites where id = %s", [pick]).fetchone()["status"] == "new"


def test_music_is_validated_and_original_is_refused_for_a_recreate(db):
    out = decide(db, add_pick(db), owner_mode="dropin", owner_music="original")
    assert out["proposal"]["owner_music"] == "original"
    recreate = decide(db, add_pick(db, url=URL + "r"), owner_mode="recreate", owner_music="ai_beat")
    assert recreate["proposal"]["owner_music"] == "ai_beat"
    with pytest.raises(psycopg.errors.Error, match="original needs the dropin mode"):
        decide(db, add_pick(db, url=URL + "q"), owner_mode="recreate", owner_music="original")
    stored = add_pick(db, url=URL + "t", proposal={"owner_mode": "recreate"})
    with pytest.raises(psycopg.errors.Error, match="original needs the dropin mode"):  # the stored mode counts too
        decide(db, stored, owner_music="original")
    with pytest.raises(psycopg.errors.Error, match="owner_music"):
        decide(db, add_pick(db, url=URL + "x"), owner_music="spotify")


def test_both_hands_the_sibling_the_same_gadgets_and_music(db):
    out = decide(
        db, add_pick(db), character_slug="reginald", also_character="biscuit", owner_props=["handbell"], owner_music="in_app",
    )
    assert out["sibling"]["proposal"]["owner_props"] == ["handbell"]
    assert out["sibling"]["proposal"]["owner_music"] == "in_app"


def test_attach_clip_stores_the_owners_upload_path_and_refuses_anything_else(db):
    pick = add_pick(db)
    path = f"owner/{pick}/1759660000000.mp4"
    out = attach(db, pick, path)
    assert out["proposal"]["owner_clip_path"] == path and out["proposal"]["hook"] == "first day"
    for bad in ("", "inbox/a.mp4", f"owner/{pick}/", f"owner/{pick}/a/b.mp4", "owner/00000000-0000-0000-0000-000000000000/a.mp4"):
        with pytest.raises(psycopg.errors.Error):
            attach(db, pick, bad)
    made = add_pick(db, status="made", url=URL + "m")
    with pytest.raises(psycopg.errors.Error, match="too late"):
        attach(db, made, f"owner/{made}/a.mp4")
    with pytest.raises(psycopg.errors.Error, match="unknown pick"):
        attach(db, "00000000-0000-0000-0000-000000000000", "owner/00000000-0000-0000-0000-000000000000/a.mp4")


def test_a_share_of_one_takes_a_dropin_whatever_the_ratio(db):
    db.execute(
        f"insert into {SCHEMA}.accounts (character_slug, platform, handle, postiz_integration_id, dropin_share) values "
        "('reginald', 'instagram', 'r', 'pz-1', 1.0), ('reginald', 'tiktok', '@r', 'pz-2', 0.4)"
    )
    clip = db.execute(f"insert into {SCHEMA}.clips (character_slug, mode) values ('reginald', 'dropin') returning id").fetchone()["id"]
    for i in range(10):
        past = db.execute(f"insert into {SCHEMA}.clips (character_slug, mode) values ('reginald', 'dropin') returning id").fetchone()["id"]
        for platform in ("instagram", "tiktok"):
            account = db.execute(f"select id from {SCHEMA}.accounts where platform = %s", [platform]).fetchone()["id"]
            db.execute(
                f"insert into {SCHEMA}.posts (clip_id, account_id, scheduled_for) values (%s, %s, now() - make_interval(days => %s))",
                [past, account, i + 1],
            )
    rows = db.execute(f"select platform from {SCHEMA}.accounts_for_clip(%s)", [clip]).fetchall()
    assert [r["platform"] for r in rows] == ["instagram"]  # the 0.4 share is a cap, the 1.0 share is not


def test_the_views_carry_the_card(db):
    card = {
        "mode": "recreate", "tier": "iconic", "theme": "deadpan at work", "posted_at": "2025-06-01", "preset_id": "hf-1",
        "thumbnail_url": "https://t.example/a.jpg", "preview_url": "https://t.example/a.mp4",
    }
    pick = add_pick(db, proposal=card)
    decide(db, add_pick(db, url=URL + "h", proposal=card), owner_props=["tiny crown"], owner_music="in_app")
    (p,) = db.execute(f"select * from {SCHEMA}.v_picks where id = %s", [pick]).fetchall()
    assert (p["tier"], p["theme"], p["posted_at"], p["gallery"]) == ("iconic", "deadpan at work", "2025-06-01", True)
    assert (p["thumbnail_url"], p["preview_url"]) == ("https://t.example/a.jpg", "https://t.example/a.mp4")
    assert p["owner_props"] is None and p["owner_music"] is None
    plain = add_pick(db, url=URL + "p")
    (q,) = db.execute(f"select gallery, tier from {SCHEMA}.v_picks where id = %s", [plain]).fetchall()
    assert (q["gallery"], q["tier"]) == (False, None)
    (h,) = db.execute(f"select * from {SCHEMA}.v_pick_history").fetchall()
    assert h["owner_props"] == ["tiny crown"] and h["owner_music"] == "in_app" and h["tier"] == "iconic"


def test_sources_have_a_minors_check_that_starts_unchecked(db):
    row = db.execute(
        f"insert into {SCHEMA}.sources (kind, body, duration_s) values ('owner_inbox', 'biped', 8) returning has_minors"
    ).fetchone()
    assert row["has_minors"] is None
