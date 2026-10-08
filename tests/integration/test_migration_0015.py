"""Migration 0015 against a real Postgres: copy_drop, the family rule and the score in set_drop_character, the family's days in
free_slot (and through it next_free_slot and approve_clip), and v_views_daily.

Skipped unless ``DATABASE_URL_TEST`` is set; see ``test_pgstore.py`` for what the database needs. The schema is built from every
migration, renamed ``studio_test``, and dropped afterwards (``conftest.py`` removes the renamed cron job). No dispatch leaves the
database: the test database may be the live shared project, whose Vault HOLDS ``github_dispatch_token``, so ``_ddl`` points every
Vault lookup of the TEST schema at a secret name that does not exist (request_job then finds no token and sends nothing:
``dispatched`` is false), on top of the schema name changing the repository in the URL. The owner's RPCs need Supabase's
``auth.jwt()``: those tests are skipped on a database without it. The Python/SQL parity of the family's days is pinned in
``test_pgstore.py`` (the same data through ``planning`` and ``studio.free_slot``).
"""

import json
import os
import re
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path

import psycopg
import pytest
from psycopg.rows import dict_row

DSN = os.environ.get("DATABASE_URL_TEST")
pytestmark = pytest.mark.skipif(not DSN, reason="DATABASE_URL_TEST is not set")

SCHEMA = "studio_test"
MIGRATIONS = Path(__file__).resolve().parents[2] / "supabase" / "migrations"
OWNER = json.dumps({"email": "o.schwend@gmail.com"})
TOKEN = "'github_dispatch_token'"
NO_TOKEN = "'github_dispatch_token_absent_in_tests'"
PERSON = {"kind": "person", "body": "biped"}
DOG = {"kind": "dog", "body": "quadruped"}


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
            f"insert into {SCHEMA}.characters (slug, name, bodies, status, setup) values "
            """('reginald', 'Reginald', '{biped}', 'live', '{"stars": ["person"]}'), """
            """('lenny', 'Lenny Gold', '{biped}', 'live', '{"stars": ["person"]}'), """
            """('franz', 'Franz', '{biped,quadruped}', 'live', '{"stars": ["dog", "person"]}'), """
            """('dj', 'The DJ', '{biped}', 'designing', '{"stars": ["person"]}'), """
            """('biscuit', 'Biscuit', '{quadruped}', 'paused', '{"stars": ["dog"]}'), """
            """('oldie', 'Oldie', '{biped}', 'live', '{}')"""  # seeded before terminal v3: no setup.stars
        )
        yield conn
        conn.execute(f"drop schema if exists {SCHEMA} cascade")


def has_auth(db) -> bool:
    return db.execute("select to_regprocedure('auth.jwt()') is not null as ok").fetchone()["ok"]


@pytest.fixture
def owner_db(db):
    if not has_auth(db):
        pytest.skip("no auth.jwt() on this database")
    return db


def as_owner(db, sql: str, args=(), who: str = OWNER):
    with db.transaction():
        db.execute("select set_config('request.jwt.claims', %s, true)", [who])
        return db.execute(sql, args).fetchone()


def copy(db, pick_id, slug):
    return as_owner(db, f"select {SCHEMA}.copy_drop(%s, %s) as r", [pick_id, slug])["r"]


def pick(db, pick_id) -> dict:
    return db.execute(f"select * from {SCHEMA}.favorites where id = %s", [pick_id]).fetchone()


def count_picks(db) -> int:
    return db.execute(f"select count(*) as n from {SCHEMA}.favorites").fetchone()["n"]


def checked(db, slug="reginald", state="ready", star=None, storage_path="owner/x/1.mp4", fetched=None, **drop_over) -> str:
    """A drop whose check ended ``state`` (the copy rules only read the card): its full-clip source, the star, a section, a score."""
    src = db.execute(
        f"insert into {SCHEMA}.sources (kind, storage_path, body, duration_s) values ('owner_inbox', %s, 'biped', 20) returning id",
        [storage_path],
    ).fetchone()["id"]
    pick_id = str(uuid.uuid4())
    drop = {
        "state": state, "kind": "file", "at": "2026-10-08T09:00:00+01:00", "reason": None, "own_footage": True,
        "character_by": "owner", "star": star or PERSON, "source_id": str(src), "window": {"start_s": 0.0, "length_s": 9.0},
        "hooks": ["a"], "score": {"total": 78, "potential": 7, "swap": 9, "reason": "x"}, **drop_over,
    }  # fmt: skip
    proposal = {"decision": {"decision": "approve", "by": "owner"}, "drop": drop}
    if fetched is not None:
        proposal["fetched"] = fetched
    db.execute(
        f"insert into {SCHEMA}.favorites (id, url, platform, origin, character_slug, creator_handle, proposal, status, source_id) "
        "values (%s, %s, 'drop', 'owner', %s, '@dancer.one', %s, 'approved', %s)",
        [pick_id, f"owner-drop:{pick_id}", slug, json.dumps(proposal), src],
    )
    return pick_id


def set_drop(db, pick_id, **fields):
    db.execute(
        f"update {SCHEMA}.favorites set proposal = jsonb_set(proposal, '{{drop}}', (proposal -> 'drop') || %s::jsonb) where id = %s",
        [json.dumps(fields), pick_id],
    )


def refused(db, pick_id, slug, line, error=psycopg.errors.CheckViolation):
    before = count_picks(db)
    with pytest.raises(error) as e:
        copy(db, pick_id, slug)
    assert e.value.diag.message_primary == line
    assert count_picks(db) == before  # nothing is filed


# ---- copy_drop ---------------------------------------------------------------------------------------------------------------


def test_copy_files_a_version_that_shares_the_roots_clip_and_asks_for_its_check(owner_db):
    db = owner_db
    marker = {"at": "2026-10-08T08:00:00+00:00", "url": "https://www.tiktok.com/@dancer.one/video/1", "purged_at": "2026-10-09"}
    root = checked(db, fetched=marker)
    before = pick(db, root)
    out = copy(db, root, "lenny")
    assert set(out) == {"pick_id", "dispatched"} and out["dispatched"] is False  # no token in the test schema: nothing is sent
    v = pick(db, out["pick_id"])
    assert str(v["id"]) != root and v["url"] == f"owner-drop:{v['id']}" and v["platform"] == "drop" and v["origin"] == "owner"
    assert v["status"] == "approved" and v["character_slug"] == "lenny" and v["source_id"] == before["source_id"]
    assert v["creator_handle"] == "@dancer.one" and v["proposal"]["decision"]["by"] == "owner"
    d = v["proposal"]["drop"]
    at = d["at"]
    assert d == {
        "state": "checking", "kind": "file", "at": at, "reason": None, "own_footage": True, "character_by": "owner",
        "copy_of": root, "requested": {"process": at},
    }  # fmt: skip  # no score, window or hooks of the root's: the version's own check gives its own
    assert v["proposal"]["fetched"] == {k: x for k, x in marker.items() if k != "purged_at"}
    assert pick(db, root) == before  # the root is left as it was
    own = checked(db, own_footage=False)
    assert pick(db, copy(db, own, "franz")["pick_id"])["proposal"]["drop"]["own_footage"] is False
    plain = checked(db)  # no fetched marker on the root: none on the version
    assert "fetched" not in pick(db, copy(db, plain, "lenny")["pick_id"])["proposal"]


def test_a_copy_of_a_copy_points_at_the_root_and_a_fourth_member_is_refused(owner_db):
    db = owner_db
    root = checked(db, state="made")
    v1 = copy(db, root, "lenny")["pick_id"]
    v2 = copy(db, v1, "franz")["pick_id"]  # from the version's card: still the root's family
    assert pick(db, v2)["proposal"]["drop"]["copy_of"] == root and pick(db, v2)["source_id"] == pick(db, root)["source_id"]
    refused(db, v2, "oldie", "a clip goes to at most 3 characters")  # the 4th, from a version's card
    refused(db, root, "oldie", "a clip goes to at most 3 characters")
    refused(db, root, "reginald", "Reginald already has a version of this clip")
    refused(db, v1, "lenny", "Lenny Gold already has a version of this clip")
    db.execute(f"update {SCHEMA}.favorites set status = 'skipped' where id = %s", [v1])  # a skipped version is no member
    again = copy(db, root, "lenny")["pick_id"]
    assert pick(db, again)["proposal"]["drop"]["copy_of"] == root
    refused(db, root, "oldie", "a clip goes to at most 3 characters")


def test_copy_refusals_are_the_clis_lines(owner_db):
    db = owner_db
    for state in ("uploading", "checking", "waiting", "blocked", "failed"):
        refused(db, checked(db, state=state), "lenny", "the clip is not checked yet")
    no_source = checked(db)
    db.execute(f"update {SCHEMA}.favorites set source_id = null, proposal = proposal #- '{{drop,source_id}}' where id = %s", [no_source])
    refused(db, no_source, "lenny", "the clip is not checked yet")
    gone = checked(db, state="made")
    db.execute(f"update {SCHEMA}.sources set storage_path = null where id = (select source_id from {SCHEMA}.favorites where id = %s)", [gone])
    refused(db, gone, "lenny", "the clip's file is gone (deleted after posting): drop it again")
    empty = checked(db, storage_path="")
    refused(db, empty, "lenny", "the clip's file is gone (deleted after posting): drop it again")
    refused(db, checked(db), "nobody", "unknown character 'nobody'", psycopg.errors.InvalidParameterValue)
    refused(db, checked(db, slug="franz", star=DOG), "biscuit", "Biscuit is paused", psycopg.errors.InvalidParameterValue)
    not_a_drop = db.execute(
        f"insert into {SCHEMA}.favorites (url, platform, character_slug, status) values ('https://x', 'tiktok', 'reginald', 'approved') returning id"
    ).fetchone()["id"]
    refused(db, not_a_drop, "lenny", f"the original clip {not_a_drop} is gone")
    with pytest.raises(psycopg.errors.NoDataFound):
        copy(db, str(uuid.uuid4()), "lenny")
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        as_owner(db, f"select {SCHEMA}.copy_drop(%s, 'lenny') as r", [checked(db)], who=json.dumps({"email": "someone@else.com"}))


def test_from_a_versions_card_the_refusal_says_what_is_true_of_the_original(owner_db):
    db = owner_db
    root = checked(db)
    v = copy(db, root, "lenny")["pick_id"]
    for state, line in (
        ("checking", "the original clip is being checked again: try in a few minutes"),
        ("waiting", "the original clip is being checked again: try in a few minutes"),
        ("blocked", "the original clip can't be used any more"),
        ("failed", "the original clip can't be used any more"),
    ):
        set_drop(db, root, state=state)
        refused(db, v, "franz", line)
    refused(db, root, "franz", "the clip is not checked yet")  # from the root's own card: as before


def test_like_for_like_reads_setup_stars_and_the_bodies_with_the_clis_lines(owner_db):
    from studio import drop

    db = owner_db
    stars = {"lenny": ["person"], "franz": ["dog", "person"], "biscuit": ["dog"]}
    bodies = {"lenny": ["biped"], "franz": ["biped", "quadruped"], "oldie": ["biped"]}
    names = {"lenny": "Lenny Gold", "franz": "Franz", "oldie": "Oldie"}

    def python_line(star, slug):  # the CLI's own words for the same star and character
        return drop.like_for_like(star, {"swap": {"stars": stars[slug]}, "bodies": bodies[slug]}, names[slug])

    cases = [
        (DOG, "lenny"),  # a dog to a person's character
        ({"kind": "person", "body": "quadruped"}, "lenny"),  # the right kind, a body he does not have
        ({"kind": "none"}, "lenny"),  # nobody to replace
        ({"kind": "animal", "body": "quadruped"}, "franz"),  # "Franz replaces a dog or a person"
    ]
    for star, slug in cases:
        line = python_line(star, slug)
        assert line is not None
        refused(db, checked(db, star=star), slug, line)
    assert "Franz replaces a dog or a person, this clip's star is a small animal" in python_line(*cases[3])
    assert python_line(DOG, "franz") is None and copy(db, checked(db, slug="lenny", star=DOG), "franz")["pick_id"]
    # a character seeded before terminal v3 (no setup.stars): only his body is checked
    assert copy(db, checked(db, star={"kind": "dog", "body": "biped"}), "oldie")["pick_id"]
    refused(db, checked(db, star={"kind": "dog", "body": "quadruped"}), "oldie", "the wrong star: Oldie has no quadruped body")


def test_two_taps_at_once_cannot_make_a_fourth_member(owner_db):
    """Each copy locks the family's root row before counting: the second waits for the first, then counts 3 and is refused."""
    db = owner_db
    root = checked(db)
    copy(db, root, "lenny")  # two members
    first = psycopg.connect(DSN, row_factory=dict_row)
    second = psycopg.connect(DSN, row_factory=dict_row)
    result: dict = {}

    def tap_two():
        try:
            second.execute("select set_config('request.jwt.claims', %s, true)", [OWNER])
            result["r"] = second.execute(f"select {SCHEMA}.copy_drop(%s, 'oldie') as r", [root]).fetchone()["r"]
            second.commit()
        except psycopg.Error as e:
            second.rollback()
            result["error"] = e

    try:
        first.execute("select set_config('request.jwt.claims', %s, true)", [OWNER])
        made = first.execute(f"select {SCHEMA}.copy_drop(%s, 'franz') as r", [root]).fetchone()["r"]  # holds the root's lock
        tap = threading.Thread(target=tap_two)
        tap.start()
        time.sleep(1.5)
        assert tap.is_alive()  # waiting on the root row
        first.commit()
        tap.join(timeout=30)
        assert not tap.is_alive()
    finally:
        first.close()
        second.close()
    assert "r" not in result and isinstance(result["error"], psycopg.errors.CheckViolation)
    assert result["error"].diag.message_primary == "a clip goes to at most 3 characters"
    members = db.execute(
        f"select count(*) as n from {SCHEMA}.favorites where id = %s or proposal #>> '{{drop,copy_of}}' = %s", [root, root]
    ).fetchone()["n"]
    assert members == 3 and pick(db, made["pick_id"])["character_slug"] == "franz"


def test_only_the_signed_in_owner_may_call_copy_drop(db):
    for role, allowed in (("authenticated", True), ("anon", False)):
        if not db.execute("select 1 from pg_roles where rolname = %s", [role]).fetchone():
            continue
        for fn in ("copy_drop(uuid, text)", "set_drop_character(uuid, text)"):
            ok = db.execute("select has_function_privilege(%s, %s, 'execute') as ok", [role, f"{SCHEMA}.{fn}"]).fetchone()["ok"]
            assert ok is allowed, (role, fn)
    for fn in ("family_days(uuid)", "family_root_id(jsonb, uuid)", "free_slot(text, uuid[], uuid, timestamptz)"):
        if db.execute("select 1 from pg_roles where rolname = 'authenticated'").fetchone():
            assert db.execute("select has_function_privilege('authenticated', %s, 'execute') as ok", [f"{SCHEMA}.{fn}"]).fetchone()["ok"]


# ---- set_drop_character: the score and the family ---------------------------------------------------------------------------


def test_set_drop_character_strips_the_score_and_refuses_a_character_the_family_has(owner_db):
    db = owner_db
    root = checked(db)
    v = copy(db, root, "lenny")["pick_id"]
    set_drop(db, v, state="ready", score={"total": 61}, credits=91, source_id=str(pick(db, root)["source_id"]))
    with pytest.raises(psycopg.errors.CheckViolation) as e:
        as_owner(db, f"select {SCHEMA}.set_drop_character(%s, 'reginald') as r", [v])
    assert e.value.diag.message_primary == "Reginald already has a version of this clip"
    with pytest.raises(psycopg.errors.CheckViolation):
        as_owner(db, f"select {SCHEMA}.set_drop_character(%s, 'lenny') as r", [root])  # the root onto a version's character
    r = as_owner(db, f"select {SCHEMA}.set_drop_character(%s, 'franz') as r", [v])["r"]
    d = r["proposal"]["drop"]
    assert r["character_slug"] == "franz" and d["state"] == "checking" and r["dispatched"] is False
    assert "score" not in d and "credits" not in d and d["copy_of"] == root  # still the root's version
    # a skipped member is no member: the root may take its character
    db.execute(f"update {SCHEMA}.favorites set status = 'skipped' where id = %s", [v])
    assert as_owner(db, f"select {SCHEMA}.set_drop_character(%s, 'franz') as r", [root])["r"]["character_slug"] == "franz"
    # a drop of no family: the score goes too (by-hand changes included)
    lone = checked(db)
    after = as_owner(db, f"select {SCHEMA}.set_drop_character(%s, 'lenny') as r", [lone])["r"]
    assert "score" not in after["proposal"]["drop"] and after["proposal"]["drop"]["state"] == "checking"
    # the same character again: only recorded as the owner's choice, never refused by his own family
    assert as_owner(db, f"select {SCHEMA}.set_drop_character(%s, 'lenny') as r", [lone])["r"]["dispatched"] is False


# ---- free_slot: a family's posts 14 days apart --------------------------------------------------------------------------------


def london(day: int, hour: int, minute: int = 0) -> datetime:
    from studio.config import LONDON

    return datetime(2026, 10, day, hour, minute, tzinfo=LONDON)


def account(db, slug, platform, connected=True) -> str:
    return db.execute(
        f"insert into {SCHEMA}.accounts (character_slug, platform, handle, postiz_integration_id, dropin_share) "
        "values (%s, %s, %s, %s, 1) returning id",
        [slug, platform, f"@{slug}.{platform}", f"pz-{slug}-{platform}" if connected else None],
    ).fetchone()["id"]


def clip_for(db, pick_id, slug, state="awaiting_approval") -> str:
    clip = db.execute(
        f"insert into {SCHEMA}.clips (character_slug, mode, state, master_path, features) values (%s, 'dropin', %s, %s, %s) returning id",
        [slug, state, f"{slug}/m.mp4", json.dumps({"fav_id": pick_id})],
    ).fetchone()["id"]
    db.execute(f"update {SCHEMA}.favorites set clip_id = %s where id = %s", [clip, pick_id])
    return clip


def post(db, clip, acct, when, status="scheduled", claimed_at=None):
    db.execute(
        f"insert into {SCHEMA}.posts (clip_id, account_id, scheduled_for, status, claimed_at) values (%s, %s, %s, %s, %s)",
        [clip, acct, when, status, claimed_at],
    )


def test_free_slot_next_free_slot_and_approve_clip_skip_the_familys_days(owner_db):
    db = owner_db
    db.execute(
        f"""update {SCHEMA}.settings set cadence = '{{"reginald": {{"days": ["tue", "wed", "thu"], "slot": "19:30"}},
        "lenny": {{"days": ["tue", "wed", "thu"], "slot": "12:30"}}}}'::jsonb where id = 1"""
    )
    reg_tt = account(db, "reginald", "tiktok")
    lenny_tt, lenny_ig = account(db, "lenny", "tiktok"), account(db, "lenny", "instagram")
    root = checked(db, state="made")
    v = copy(db, root, "lenny")["pick_id"]
    root_clip, v_clip = clip_for(db, root, "reginald", "scheduled"), clip_for(db, v, "lenny")
    post(db, root_clip, reg_tt, london(6, 19, 30))  # the root goes out on Tue 6 Oct, on ANOTHER character's account
    tue = london(6, 8)

    def free(clip_id, accounts=(lenny_tt, lenny_ig)):
        return db.execute(f"select {SCHEMA}.free_slot('lenny', %s::uuid[], %s, %s) as s", [list(accounts), clip_id, tue]).fetchone()["s"]

    assert free(v_clip) == london(20, 12, 30)  # Tue 20 Oct: the first cadence day 14 days on (Wed 7 .. Mon 19 are within 13)
    assert free(None) == london(6, 12, 30)  # no clip being scheduled: no family
    plain = clip_for(db, checked(db, slug="lenny"), "lenny")
    assert free(plain) == london(6, 12, 30)  # a clip of no family is not held back by them
    days = db.execute(f"select {SCHEMA}.family_days(%s) as d", [v_clip]).fetchone()["d"]
    assert len(days) == 27 and min(days).isoformat() == "2026-09-23" and max(days).isoformat() == "2026-10-19"
    assert db.execute(f"select {SCHEMA}.family_days(%s) as d", [root_clip]).fetchone()["d"] == []  # its own posts: no family
    assert db.execute(f"select {SCHEMA}.next_free_slot(%s, %s) as s", [v_clip, tue]).fetchone()["s"] == london(20, 12, 30)
    # a failed post never took a day; a posted one dated by claimed_at (London) does
    db.execute(f"update {SCHEMA}.posts set status = 'failed' where clip_id = %s", [root_clip])
    assert free(v_clip) == london(6, 12, 30)
    db.execute(
        f"update {SCHEMA}.posts set status = 'posted', claimed_at = %s where clip_id = %s",
        [datetime.fromisoformat("2026-10-07T23:30:00+00:00"), root_clip],  # 00:30 BST on Thu 8 Oct
    )
    assert free(v_clip) == london(22, 12, 30)  # 8 Oct + 14 = Thu 22 Oct
    # approve_clip's default slot is free_slot over the clip's accounts from now(): the family's days hold there too
    expected = db.execute(
        f"select {SCHEMA}.free_slot('lenny', %s::uuid[], %s, now()) as s", [[lenny_tt, lenny_ig], v_clip]
    ).fetchone()["s"]
    out = as_owner(db, f"select {SCHEMA}.approve_clip(%s) as r", [v_clip])["r"]
    assert datetime.fromisoformat(out["scheduled_for"]) == expected and len(out["posts"]) == 2
    assert abs((expected.astimezone(london(8, 12).tzinfo).date() - london(8, 12).date()).days) >= 14


def test_a_skipped_members_posts_still_hold_the_familys_days(db):
    db.execute(f"""update {SCHEMA}.settings set cadence = cadence || '{{"lenny": {{"days": ["tue", "wed", "thu"], "slot": "12:30"}}}}' where id = 1""")
    lenny_tt, franz_tt = account(db, "lenny", "tiktok"), account(db, "franz", "tiktok")
    root = checked(db, state="made")
    ids = [str(uuid.uuid4()), str(uuid.uuid4())]
    for pid, slug, status in ((ids[0], "franz", "skipped"), (ids[1], "lenny", "approved")):
        db.execute(
            f"insert into {SCHEMA}.favorites (id, url, platform, origin, character_slug, proposal, status) values (%s, %s, 'drop', 'owner', %s, %s, %s)",
            [pid, f"owner-drop:{pid}", slug, json.dumps({"drop": {"state": "made", "copy_of": root}}), status],
        )
    franz_clip, lenny_clip = clip_for(db, ids[0], "franz", "scheduled"), clip_for(db, ids[1], "lenny")
    post(db, franz_clip, franz_tt, london(13, 19))
    got = db.execute(f"select {SCHEMA}.free_slot('lenny', %s::uuid[], %s, %s) as s", [[lenny_tt], lenny_clip, london(6, 8)]).fetchone()["s"]
    assert got == london(27, 12, 30)  # Tue 27 Oct: 13 Oct + 14 (the skipped Franz's post holds 30 Sep .. 26 Oct)


# ---- v_views_daily ----------------------------------------------------------------------------------------------------------


def snap(db, post_id, at: str, views, follows=None):
    db.execute(
        f"insert into {SCHEMA}.snapshots (post_id, captured_at, views, follows) values (%s, %s, %s, %s)",
        [post_id, datetime.fromisoformat(at), views, follows],
    )


def test_v_views_daily_sums_each_posts_daily_increase_per_character(db):
    reg_tt, reg_ig, lenny_tt = account(db, "reginald", "tiktok"), account(db, "reginald", "instagram"), account(db, "lenny", "tiktok")
    reg_clip = db.execute(f"insert into {SCHEMA}.clips (character_slug, mode, state) values ('reginald', 'dropin', 'posted') returning id").fetchone()["id"]
    lenny_clip = db.execute(f"insert into {SCHEMA}.clips (character_slug, mode, state) values ('lenny', 'dropin', 'posted') returning id").fetchone()["id"]
    ids = {}
    for key, clip, acct in (("tt", reg_clip, reg_tt), ("ig", reg_clip, reg_ig), ("lenny", lenny_clip, lenny_tt)):
        ids[key] = db.execute(
            f"insert into {SCHEMA}.posts (clip_id, account_id, scheduled_for, status) values (%s, %s, '2026-10-06T18:30:00Z', 'posted') returning id",
            [clip, acct],
        ).fetchone()["id"]
    # Reginald's TikTok post: Tue 6 (two snapshots: the latest counts), Wed 7, and a snapshot at 23:30 UTC on the 7th = Thu 8 in London
    snap(db, ids["tt"], "2026-10-06T19:00:00+00:00", 100, 1)
    snap(db, ids["tt"], "2026-10-06T22:00:00+00:00", 150, 2)
    snap(db, ids["tt"], "2026-10-07T12:00:00+00:00", 400, 5)
    snap(db, ids["tt"], "2026-10-07T23:30:00+00:00", 900, None)  # follows not measured: the last known stays the base
    # Reginald's Instagram post: first measured Wed 7, then Thu 8 (a later snapshot of the day without views is ignored)
    snap(db, ids["ig"], "2026-10-07T09:00:00+00:00", 50)
    snap(db, ids["ig"], "2026-10-08T09:00:00+00:00", 80)
    snap(db, ids["ig"], "2026-10-08T10:00:00+00:00", None)
    # Lenny's post: Tue 6 and Thu 8 (no snapshot on Wed: Thursday's increase is over Tuesday's)
    snap(db, ids["lenny"], "2026-10-06T20:00:00+00:00", 30, 0)
    snap(db, ids["lenny"], "2026-10-08T20:00:00+00:00", 70, 3)
    rows = db.execute(f"select character_slug, day::text as day, views, follows from {SCHEMA}.v_views_daily order by 1, 2").fetchall()
    assert [tuple(r.values()) for r in rows] == [
        ("lenny", "2026-10-06", 30, 0),
        ("lenny", "2026-10-08", 40, 3),
        ("reginald", "2026-10-06", 150, 2),
        ("reginald", "2026-10-07", 250 + 50, 3),
        ("reginald", "2026-10-08", 500 + 30, 0),
    ]
    total = db.execute(f"select sum(views) as v from {SCHEMA}.v_views_daily where character_slug = 'reginald'").fetchone()["v"]
    assert total == 900 + 80  # the gains add up to each post's latest total
    cols = db.execute(
        "select column_name, data_type from information_schema.columns where table_schema = %s and table_name = 'v_views_daily' "
        "order by ordinal_position", [SCHEMA],
    ).fetchall()
    assert [(c["column_name"], c["data_type"]) for c in cols] == [
        ("character_slug", "text"), ("day", "date"), ("views", "bigint"), ("follows", "bigint"),
    ]  # fmt: skip
    opts = db.execute(f"select reloptions from pg_class where oid = '{SCHEMA}.v_views_daily'::regclass").fetchone()["reloptions"]
    assert "security_invoker=true" in opts
    for role, allowed in (("authenticated", True), ("anon", False)):
        if db.execute("select 1 from pg_roles where rolname = %s", [role]).fetchone():
            ok = db.execute("select has_table_privilege(%s, %s, 'select') as ok", [role, f"{SCHEMA}.v_views_daily"]).fetchone()["ok"]
            assert ok is allowed, role


# ---- add_drop: the provisional character reads who he replaces where the seed writes it --------------------------------------


def test_a_drop_without_a_character_waits_under_the_same_character_as_pythons_provisional(db):
    """The roster from the real refs.json, with characters.setup exactly as the seed writes it (setup.stars): add_drop() and
    studio.drop.provisional choose the same character, Franz (the first by slug who replaces a person). 0013 read
    setup.swap.stars, which the seed never writes, and fell back to the bodies: Lenny."""
    from studio import drop, seed
    from studio.models import Body, Character
    from studio.store import MemoryStore

    refs = seed.load_refs()
    assert all("stars" in seed.character_setup(r) and "swap" not in seed.character_setup(r) for r in refs)
    db.execute(f"delete from {SCHEMA}.characters")
    for ref in refs:
        db.execute(
            f"insert into {SCHEMA}.characters (slug, name, bodies, status, setup) values (%s, %s, %s, %s, %s)",
            [ref["slug"], ref["name"], ref["bodies"], ref["status"], json.dumps(seed.character_setup(ref))],
        )

    def python(paused=()):
        store = MemoryStore(characters=[
            Character(slug=r["slug"], name=r["name"], status="paused" if r["slug"] in paused else r["status"],
                      bodies=[Body(b) for b in r["bodies"]])
            for r in refs
        ])  # fmt: skip
        return drop.provisional(store)

    def sql():
        f = db.execute(f"select {SCHEMA}.add_drop() as r").fetchone()["r"]
        assert f["proposal"]["drop"]["character_by"] == SCHEMA  # 'studio' in the migration: _ddl swaps the word everywhere
        return f["character_slug"]

    assert sql() == python() == "franz"
    db.execute(f"update {SCHEMA}.characters set status = 'paused' where slug = 'franz'")
    assert sql() == python(paused=("franz",)) == "lenny"  # the next by slug who replaces a person
    # a character seeded before terminal v3 with 0013's key only: still read
    db.execute(f"""update {SCHEMA}.characters set setup = '{{"swap": {{"stars": ["dog"]}}}}' where slug = 'lenny'""")
    assert sql() == "reginald"
