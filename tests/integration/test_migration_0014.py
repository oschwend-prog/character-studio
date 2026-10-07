"""Migration 0014 against a real Postgres: the publish timer (studio.publish_tick, studio.dispatch_publish, the cron job).

Skipped unless ``DATABASE_URL_TEST`` is set; see ``test_pgstore.py`` for what the database needs. The schema is built from every
migration, renamed ``studio_test``, and dropped afterwards (``conftest.py`` removes the renamed cron job). No dispatch leaves the
database: EVERY test that ticks replaces ``dispatch_publish()`` of the TEST schema by a stub (the "sent" one or the "no token" one), so the
real function, which reads the Vault's ``github_dispatch_token`` and posts it to GitHub, never runs here even when the test
database is the live shared project whose Vault holds the token. ``_rename`` changes the schema name only: the GitHub URL
(``.../character-studio/dispatches``) is left alone.
NOT run when this file was written (no Postgres on the machine): ``tests/test_schema.py`` pins the text, this file pins the
behaviour once a database is at hand.
"""

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
MIGRATION = MIGRATIONS / "0014_publish_timer.sql"

STUB = f"""
create or replace function {SCHEMA}.dispatch_publish() returns jsonb language sql as
$$ select jsonb_build_object('dispatched', true, 'request_id', 42) $$
"""

NO_TOKEN_STUB = f"""
create or replace function {SCHEMA}.dispatch_publish() returns jsonb language sql as
$$ select jsonb_build_object('dispatched', false, 'reason', 'no_token') $$
"""


def _rename(text: str) -> str:
    # the schema name only: not the "studio" of "character-studio" in the GitHub URL (a "-" right before it); the cron job's name
    # ("studio-publish-tick") IS renamed on purpose (conftest.py unschedules ``studio_test-publish-tick``)
    return re.sub(r"(?<!-)\bstudio\b", SCHEMA, text)


def _ddl() -> str:
    return _rename("\n".join(f.read_text() for f in sorted(MIGRATIONS.glob("*.sql"))))


@pytest.fixture
def db():
    with psycopg.connect(DSN, autocommit=True, row_factory=dict_row) as conn:
        conn.execute(f"drop schema if exists {SCHEMA} cascade")
        conn.execute(_ddl())
        conn.execute(f"insert into {SCHEMA}.characters (slug, name, bodies) values ('reginald', 'Reginald', '{{biped}}')")
        conn.execute(f"insert into {SCHEMA}.accounts (character_slug, platform, handle) values ('reginald', 'tiktok', '@reginald')")
        yield conn
        conn.execute(f"drop schema if exists {SCHEMA} cascade")


def add_post(db, *, due: bool = True, status: str = "scheduled") -> str:
    clip = db.execute(
        f"insert into {SCHEMA}.clips (character_slug, mode, state) values ('reginald', 'recreate', 'scheduled') returning id"
    ).fetchone()["id"]
    account = db.execute(f"select id from {SCHEMA}.accounts limit 1").fetchone()["id"]
    when = "now() - interval '1 minute'" if due else "now() + interval '2 hours'"
    return db.execute(
        f"insert into {SCHEMA}.posts (clip_id, account_id, scheduled_for, status) values (%s, %s, {when}, %s) returning id",
        [clip, account, status],
    ).fetchone()["id"]


def tick(db) -> dict:
    return db.execute(f"select {SCHEMA}.publish_tick() as r").fetchone()["r"]


def last_at(db):
    row = db.execute(f"select last_at from {SCHEMA}.timer_state where name = 'publish_dispatch'").fetchone()
    return row["last_at"] if row else None


def test_nothing_is_dispatched_when_no_post_is_due(db):
    db.execute(STUB)
    assert tick(db) == {"dispatched": False, "due": 0, "reason": "nothing_due"}
    add_post(db, due=False)  # scheduled, but for later
    add_post(db, due=True, status="posted")  # due time passed, but already out
    assert tick(db)["reason"] == "nothing_due" and last_at(db) is None


def test_a_due_post_dispatches_once_and_then_waits_nine_minutes(db):
    db.execute(STUB)
    add_post(db)
    first = tick(db)
    assert first["dispatched"] is True and first["due"] == 1 and first["request_id"] == 42
    stamp = last_at(db)
    assert stamp is not None
    again = tick(db)  # five minutes later is the same as now: inside the window
    assert again["dispatched"] is False and again["reason"] == "recent_dispatch" and again["due"] == 1
    db.execute(f"update {SCHEMA}.timer_state set last_at = now() - interval '11 minutes'")
    aged = last_at(db)
    assert tick(db)["dispatched"] is True  # the window passed and the post is still due: dispatched again
    assert last_at(db) > aged


def test_the_kill_switch_stops_the_timer_because_the_publisher_would_claim_nothing(db):
    db.execute(STUB)
    add_post(db)
    db.execute(f"update {SCHEMA}.settings set kill_switch = true where id = 1")  # the row 0001 seeds
    assert tick(db) == {"dispatched": False, "due": 1, "reason": "kill_switch"}
    assert last_at(db) is None


def test_a_dispatch_that_was_not_queued_does_not_start_the_nine_minute_window(db):
    db.execute(NO_TOKEN_STUB)  # never the real dispatch_publish(): the test database may be the live project, whose Vault HAS the token
    add_post(db)
    out = tick(db)
    assert out == {"dispatched": False, "due": 1, "reason": "no_token"}
    assert last_at(db) is None  # the next tick tries again


def test_nobody_but_the_owner_of_the_functions_may_call_them_or_read_the_timer(db):
    for role in ("anon", "authenticated", "service_role"):
        if not db.execute("select 1 from pg_roles where rolname = %s", [role]).fetchone():
            continue
        for fn in ("dispatch_publish()", "publish_tick()"):
            assert not db.execute("select has_function_privilege(%s, %s, 'execute') as ok", [role, f"{SCHEMA}.{fn}"]).fetchone()["ok"], (role, fn)
        assert not db.execute("select has_table_privilege(%s, %s, 'select') as ok", [role, f"{SCHEMA}.timer_state"]).fetchone()["ok"], role


def test_the_cron_job_is_scheduled_once_every_five_minutes_and_a_rerun_does_not_duplicate_it(db):
    if not db.execute("select to_regclass('cron.job') is not null as ok").fetchone()["ok"]:
        pytest.skip("no pg_cron on this database")
    name = f"{SCHEMA}-publish-tick"  # the migration's job name, with the schema renamed like everything else
    block = _rename(re.findall(r"do \$\$.*?\n\$\$;", MIGRATION.read_text(), re.S)[-1])  # the last do-block: the job
    assert "cron.schedule" in block
    for _ in range(2):  # applied twice
        db.execute(block)
    jobs = db.execute("select schedule, command from cron.job where jobname = %s", [name]).fetchall()
    assert jobs == [{"schedule": "*/5 * * * *", "command": f"select {SCHEMA}.publish_tick()"}]
