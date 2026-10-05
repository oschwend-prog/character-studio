"""Migration 0007 against a real Postgres: decide_pick (the "Make it" sheet), v_characters, the owner columns.

Skipped unless ``DATABASE_URL_TEST`` is set; see ``test_pgstore.py`` for what the database needs. The schema is built
from every migration, renamed ``studio_test``, and dropped afterwards. Calls go through the function exactly as
PostgREST makes them (named arguments), once as the table owner and once as the signed-in ``authenticated`` role.
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
OWNER_JWT = json.dumps({"email": "o.schwend@gmail.com"})


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


URL = "https://www.instagram.com/reel/Dde-rPWCOC6/"


def add_pick(db, slug="reginald", status="new", url=URL, proposal=None) -> str:
    row = db.execute(
        f"insert into {SCHEMA}.favorites (url, platform, creator_handle, views, outlier_x, character_slug, proposal, scores, "
        "total_score, status) values (%s, 'instagram', '@eatfryhaven', 43400000, 1392.8, %s, %s::jsonb, "
        "'{\"fit\": 10}'::jsonb, 92, %s) returning id",
        [url, slug, json.dumps(proposal or {"mode": "recreate", "hook": "first day"}), status],
    ).fetchone()
    return str(row["id"])


def decide(db, pick_id, decision="approve", **named):
    """The call as PostgREST makes it: named arguments, only the ones the client sends."""
    args = {"pick_id": pick_id, "decision": decision, **named}
    sql = ", ".join(f"{k} := %({k})s" for k in args)
    return db.execute(f"select {SCHEMA}.decide_pick({sql}) as r", args).fetchone()["r"]


def favorites(db):
    return db.execute(f"select * from {SCHEMA}.favorites order by created_at, id").fetchall()


def test_there_is_exactly_one_decide_pick_so_postgrest_resolves_it():
    with psycopg.connect(DSN, autocommit=True) as conn:
        conn.execute(f"drop schema if exists {SCHEMA} cascade")
        conn.execute(_ddl())
        n = conn.execute(
            "select count(*) from pg_proc p join pg_namespace n on n.oid = p.pronamespace "
            "where n.nspname = %s and p.proname = 'decide_pick'", [SCHEMA],
        ).fetchone()[0]
        conn.execute(f"drop schema if exists {SCHEMA} cascade")
    assert n == 1


def test_the_call_of_0004_still_works_unchanged(db):
    pick = add_pick(db)
    out = decide(db, pick, reason=None, character_slug="reginald")
    assert out["status"] == "approved" and out["character_slug"] == "reginald"
    decision = out["proposal"]["decision"]
    assert {k: v for k, v in decision.items() if k != "at"} == {"decision": "approve", "by": "owner", "reason": None}
    assert decision["at"]  # migration 0010: decide_pick stores when the owner decided
    assert "sibling" not in out and not {"owner_note", "owner_mode", "owner_presence"} & set(out["proposal"])


def test_the_owners_note_mode_and_presence_are_stored_in_the_proposal(db):
    pick = add_pick(db)
    out = decide(db, pick, owner_note="  slow-mo on the drop  ", owner_mode="dropin", owner_presence="star")
    assert out["proposal"]["owner_note"] == "slow-mo on the drop"  # trimmed
    assert (out["proposal"]["owner_mode"], out["proposal"]["owner_presence"]) == ("dropin", "star")
    assert out["proposal"]["hook"] == "first day"  # everything else in the proposal survives


def test_presence_is_ignored_unless_the_mode_is_dropin(db):
    recreate = decide(db, add_pick(db, url=URL + "a"), owner_mode="recreate", owner_presence="star")
    analyst = decide(db, add_pick(db, url=URL + "b"), owner_presence="cameo")
    assert "owner_presence" not in recreate["proposal"] and recreate["proposal"]["owner_mode"] == "recreate"
    assert "owner_presence" not in analyst["proposal"] and "owner_mode" not in analyst["proposal"]


def test_a_blank_value_keeps_what_is_stored_and_a_skip_stores_no_instructions(db):
    pick = add_pick(db, proposal={"owner_note": "keep me", "owner_mode": "dropin"})
    kept = decide(db, pick, owner_note="   ", owner_mode="")
    assert (kept["proposal"]["owner_note"], kept["proposal"]["owner_mode"]) == ("keep me", "dropin")
    skipped = decide(db, add_pick(db, url=URL + "s"), "skip", reason="seen it everywhere", owner_note="ignored")
    assert skipped["status"] == "skipped" and "owner_note" not in skipped["proposal"]


@pytest.mark.parametrize(
    ("named", "message"),
    [
        ({"owner_note": "x" * 281}, "280"),
        ({"owner_mode": "star"}, "owner_mode"),
        ({"owner_mode": "dropin", "owner_presence": "lead"}, "owner_presence"),
        ({"also_character": "nobody", "character_slug": "reginald"}, "unknown character"),
        ({"also_character": "reginald", "character_slug": "reginald"}, "different character"),
    ],
)
def test_bad_instructions_are_refused_before_anything_is_written(db, named, message):
    pick = add_pick(db)
    before = favorites(db)
    with pytest.raises(psycopg.errors.Error, match=message):
        decide(db, pick, **named)
    assert favorites(db) == before


def test_exactly_280_characters_are_accepted(db):
    assert len(decide(db, add_pick(db), owner_note="x" * 280)["proposal"]["owner_note"]) == 280


def test_every_refusal_of_0004_is_kept(db):
    pick = add_pick(db)
    with pytest.raises(psycopg.errors.Error, match="decision must be approve or skip"):
        decide(db, pick, "hold")
    with pytest.raises(psycopg.errors.Error, match="unknown pick"):
        decide(db, "00000000-0000-0000-0000-000000000000")
    with pytest.raises(psycopg.errors.Error, match="choose a character"):
        decide(db, add_pick(db, slug=None, url=URL + "n"))
    with pytest.raises(psycopg.errors.Error, match="unknown character"):
        decide(db, pick, character_slug="nobody")
    made = add_pick(db, status="made", url=URL + "m")
    with pytest.raises(psycopg.errors.Error, match="too late to decide"):
        decide(db, made)
    with pytest.raises(psycopg.errors.Error, match="only applies when approving"):
        decide(db, pick, "skip", also_character="biscuit")


def test_both_files_one_sibling_for_the_other_character_and_returns_both_rows(db):
    pick = add_pick(db, proposal={"mode": "recreate", "hook": "first day", "hold_reason": "x"})
    out = decide(db, pick, character_slug="reginald", also_character="biscuit", owner_note="slow-mo", owner_mode="dropin")
    sibling = out["sibling"]
    assert out["character_slug"] == "reginald" and sibling["character_slug"] == "biscuit"
    assert sibling["id"] != out["id"] and sibling["status"] == "approved"
    for key in ("url", "platform", "creator_handle", "views", "outlier_x", "origin", "scores", "total_score"):
        assert sibling[key] == out[key], key
    assert sibling["proposal"] == out["proposal"]  # the note, the mode and the decision travel with it
    assert sibling["proposal"]["owner_note"] == "slow-mo" and "hold_reason" not in sibling["proposal"]
    assert [r["character_slug"] for r in favorites(db)] == ["reginald", "biscuit"]


def test_both_is_idempotent_a_second_call_reuses_the_sibling(db):
    pick = add_pick(db)
    first = decide(db, pick, character_slug="reginald", also_character="biscuit")
    again = decide(db, pick, character_slug="reginald", also_character="biscuit", owner_note="new note")
    assert again["sibling"]["id"] == first["sibling"]["id"]
    assert len(favorites(db)) == 2
    assert again["sibling"]["proposal"]["owner_note"] == "new note"  # the owner's latest instruction reaches it


def test_an_existing_sibling_is_approved_when_it_was_new_or_skipped_and_left_alone_when_in_production(db):
    pick = add_pick(db)
    new = add_pick(db, slug="biscuit", status="new")
    assert decide(db, pick, also_character="biscuit")["sibling"]["id"] == new
    assert favorites(db)[1]["status"] == "approved"
    db.execute(f"update {SCHEMA}.favorites set status = 'made' where id = %s", [new])
    out = decide(db, pick, also_character="biscuit", owner_note="late")
    assert out["sibling"]["status"] == "made" and "owner_note" not in out["sibling"]["proposal"]
    assert len(favorites(db)) == 2


def test_a_row_for_the_same_video_under_the_same_character_is_not_a_sibling(db):
    pick = add_pick(db)
    other = add_pick(db, slug="reginald", url=URL)  # same url, same character as the pick itself: not "the other one"
    out = decide(db, pick, also_character="biscuit")
    assert out["sibling"]["character_slug"] == "biscuit" and out["sibling"]["id"] != other
    assert len(favorites(db)) == 3


def test_v_characters_lists_every_character_with_its_accounts_and_the_setup(db):
    db.execute(
        f"update {SCHEMA}.characters set status = 'live', setup = %s::jsonb where slug = 'biscuit'",
        [json.dumps({"closeup": True, "planned_handles": {"tiktok": "@b", "instagram": None}})],
    )
    db.execute(
        f"insert into {SCHEMA}.accounts (character_slug, platform, handle, postiz_integration_id) values "
        "('biscuit', 'tiktok', '@b', 'pz-1'), ('biscuit', 'instagram', 'b', ''), ('reginald', 'tiktok', '@r', null)"
    )
    rows = {r["slug"]: r for r in db.execute(f"select * from {SCHEMA}.v_characters").fetchall()}
    assert set(rows) == {"biscuit", "reginald"}  # a character with no account is still a row
    b = rows["biscuit"]
    assert (b["name"], b["status"], b["bodies"], b["setup"]["closeup"]) == ("Biscuit", "live", ["quadruped"], True)
    assert b["accounts"] == [  # ordered by platform; an empty id is not a connection
        {"platform": "instagram", "handle": "b", "has_postiz": False, "mode": "approval"},
        {"platform": "tiktok", "handle": "@b", "has_postiz": True, "mode": "approval"},
    ]
    assert rows["reginald"]["accounts"] == [{"platform": "tiktok", "handle": "@r", "has_postiz": False, "mode": "approval"}]
    assert rows["reginald"]["setup"] == {}


def test_v_picks_and_the_history_show_the_owners_instructions(db):
    pick = add_pick(db)
    decide(db, pick, owner_note="slow-mo", owner_mode="dropin", owner_presence="cameo")
    (h,) = db.execute(f"select * from {SCHEMA}.v_pick_history").fetchall()
    assert (h["owner_note"], h["owner_mode"], h["owner_presence"]) == ("slow-mo", "dropin", "cameo")
    fresh = add_pick(db, url=URL + "z", proposal={"owner_mode": "recreate"})
    (p,) = db.execute(f"select * from {SCHEMA}.v_picks where id = %s", [fresh]).fetchall()
    assert (p["owner_note"], p["owner_mode"], p["owner_presence"]) == (None, "recreate", None)


def test_runs_keep_their_details(db):
    db.execute(f"insert into {SCHEMA}.runs (kind, status) values ('daily', 'ok')")
    db.execute(f"insert into {SCHEMA}.runs (kind, status, details) values ('daily', 'ok', %s::jsonb)", [json.dumps({"scan": {"outliers": 3}})])
    rows = db.execute(f"select details from {SCHEMA}.runs order by started_at, id").fetchall()
    assert sorted(json.dumps(r["details"]) for r in rows) == ['{"scan": {"outliers": 3}}', "{}"]


def test_the_signed_in_owner_may_decide_and_another_user_sees_nothing(db):
    pick = add_pick(db)
    db.execute("set role authenticated")
    try:
        db.execute("select set_config('request.jwt.claims', %s, false)", [json.dumps({"email": "someone@else.com"})])
        with pytest.raises(psycopg.errors.Error, match="unknown pick"):
            decide(db, pick)  # RLS hides the row from anyone but the owner: the function runs as the caller
        db.execute("select set_config('request.jwt.claims', %s, false)", [OWNER_JWT])
        out = decide(db, pick, character_slug="reginald", also_character="biscuit", owner_note="hi")
        assert out["sibling"]["character_slug"] == "biscuit"
        assert db.execute(f"select count(*) as n from {SCHEMA}.v_characters").fetchone()["n"] == 2
    finally:
        db.execute("reset role")
