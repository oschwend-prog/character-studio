"""The migrations and the dataclasses must not drift apart.

There is no local Postgres, so these tests read ``supabase/migrations/*.sql`` as text:
every dataclass field must have a column (a column may come from 0001's ``create table`` or from a
later migration's ``alter table ... add column``), every CHECK list must equal the enum, the
migrations must stay inside schema ``studio``, RLS must be on for every table, and the seed must
match the in-code defaults.
"""

import json
import re
from pathlib import Path
from typing import get_args

import pytest

from studio import models
from studio.models import (
    DEFAULT_CADENCE,
    Account,
    Body,
    Character,
    Clip,
    ClipState,
    Favorite,
    LedgerEntry,
    Mode,
    Platform,
    Post,
    PostStatus,
    Review,
    Run,
    RunKind,
    RunStatus,
    Settings,
    Snapshot,
    Source,
    SourceKind,
)

MIGRATIONS = Path(__file__).resolve().parents[1] / "supabase" / "migrations"
MIGRATION = MIGRATIONS / "0001_studio.sql"
SQL = MIGRATION.read_text()  # 0001: the tables, RLS, policies, seed, buckets
KPI_MIGRATION = MIGRATIONS / "0002_snapshot_kpis.sql"
ALL_SQL = "\n".join(f.read_text() for f in sorted(MIGRATIONS.glob("*.sql")))  # every migration, in order

TABLES = {
    "settings": Settings,
    "characters": Character,
    "accounts": Account,
    "sources": Source,
    "clips": Clip,
    "posts": Post,
    "snapshots": Snapshot,
    "ledger": LedgerEntry,
    "favorites": Favorite,
    "runs": Run,
    "reviews": Review,
}
ALL_TABLES = list(TABLES)


def table_body(name: str) -> str:
    m = re.search(rf"create table studio\.{name} \((.*?)\n\);", SQL, re.S)
    assert m, f"no create table studio.{name}"
    return m.group(1)


def columns(name: str) -> set[str]:
    """Columns of studio.<name>: its ``create table`` plus every ``alter table ... add column``."""
    skip = {"unique", "primary", "check", "constraint", "foreign"}
    cols = set()
    for line in table_body(name).splitlines():
        m = re.match(r"^  ([a-z_]+)\s+\S", line)
        if m and m.group(1) not in skip:
            cols.add(m.group(1))
    cols |= set(
        re.findall(
            rf"alter table studio\.{name}\s+add column (?:if not exists )?([a-z_]+)", ALL_SQL
        )
    )
    return cols


def check_values(table: str, column: str) -> set[str]:
    m = re.search(rf"\b{column}\s+in\s*\(([^)]*)\)", table_body(table))
    assert m, f"no CHECK list for {table}.{column}"
    return set(re.findall(r"'([^']*)'", m.group(1)))


def test_every_table_exists_with_rls_and_the_owner_policy():
    for name in ALL_TABLES:
        table_body(name)
        assert f"alter table studio.{name}" in SQL and "enable row level security" in SQL
        assert re.search(rf"create policy owner_all on studio\.{name}\s", SQL), name
    assert SQL.count("alter table") == len(ALL_TABLES) == 11  # 0001 only: RLS, one per table
    # the owner expression, exactly, in both USING and WITH CHECK of every policy
    assert SQL.count("auth.jwt()->>'email' = 'o.schwend@gmail.com'") == 2 * len(ALL_TABLES)
    assert "grant select, insert, update, delete on all tables in schema studio to authenticated" in SQL


@pytest.mark.parametrize("table", TABLES)
def test_dataclass_fields_have_columns(table):
    from dataclasses import fields

    missing = {f.name for f in fields(TABLES[table])} - columns(table)
    assert not missing, f"studio.{table} lacks columns for {sorted(missing)}"


@pytest.mark.parametrize(
    ("table", "column", "allowed"),
    [
        ("accounts", "platform", set(Platform)),
        ("accounts", "mode", set(get_args(models.AccountMode))),
        ("sources", "kind", set(SourceKind)),
        ("sources", "body", set(Body)),
        ("clips", "mode", set(Mode)),
        ("clips", "state", set(ClipState)),
        ("posts", "status", set(PostStatus)),
        ("ledger", "kind", set(get_args(models.LedgerKind))),
        ("favorites", "origin", set(get_args(models.FavoriteOrigin))),
        ("favorites", "status", set(get_args(models.FavoriteStatus))),
    ],
)
def test_check_constraints_match_the_enums(table, column, allowed):
    assert check_values(table, column) == {str(v) for v in allowed}


def test_character_bodies_check_matches_enum():
    m = re.search(r"bodies <@ array\[([^\]]*)\]", table_body("characters"))
    assert m
    assert set(re.findall(r"'([^']*)'", m.group(1))) == {str(b) for b in Body}


def test_keys_and_indexes():
    assert "unique (clip_id, account_id)" in table_body("posts")
    assert "on studio.posts (status, scheduled_for)" in SQL
    assert "on studio.clips (state)" in SQL
    assert "primary key (post_id, captured_at)" in table_body("snapshots")
    assert "check (id = 1)" in table_body("settings")


def test_seed_matches_in_code_defaults():
    settings = Settings()
    m = re.search(
        r"insert into studio\.settings \(id, monthly_cap_credits, kill_switch, cadence\)\s*"
        r"values \(\s*1, (\d+), (true|false),\s*'(\{.*?\})'::jsonb\s*\)",
        SQL,
        re.S,
    )
    assert m
    assert int(m.group(1)) == settings.monthly_cap_credits == 6000
    assert (m.group(2) == "true") == settings.kill_switch
    assert json.loads(m.group(3)) == settings.cadence == DEFAULT_CADENCE


# The only statements of the migrations that remove anything: 0007 and then 0008 replace decide_pick by a function with
# more (defaulted) parameters, and a second overload would make the call ambiguous for PostgREST. No data goes.
SANCTIONED_DROP = "drop function if exists studio.decide_pick(uuid, text, text, text);"
SANCTIONED_DROP_0008 = "drop function if exists studio.decide_pick(uuid, text, text, text, text, text, text, text);"


def test_migrations_are_additive_and_stay_inside_schema_studio():
    statements_only = re.sub(r"--[^\n]*", "", ALL_SQL)  # the words in a comment are not statements
    assert statements_only.count(SANCTIONED_DROP) == 1 and statements_only.count(SANCTIONED_DROP_0008) == 1
    remaining = statements_only.replace(SANCTIONED_DROP, "").replace(SANCTIONED_DROP_0008, "")
    # words inside a string literal are data, not statements: 0012's key 'drop' (proposal.drop, 'owner-drop:', 'drop-make')
    remaining = re.sub(r"'(?:[^']|'')*'", "''", remaining)
    assert not re.search(r"\b(drop|truncate)\b", remaining, re.I)
    assert not re.search(r"\balter\s+column\b|\brename\b", ALL_SQL, re.I)
    # the only references outside schema studio: auth.jwt() for RLS, the Storage buckets, and (0004)
    # one read policy on storage.objects so the owner's browser can sign URLs for the clips bucket
    outside = set(re.findall(r"\b(?:public|auth|storage|extensions)\.[a-z_]+", ALL_SQL))
    assert outside == {"auth.jwt", "storage.buckets", "storage.objects"}
    # every created / altered table, index and policy is in studio
    for stmt in re.findall(
        r"^(?:create table|alter table|create index \w+ on)\s+(\S+)", ALL_SQL, re.M
    ):
        assert stmt.startswith("studio."), stmt
    assert re.findall(r"create schema (?:if not exists )?(\w+)", ALL_SQL) == ["studio"]


def test_snapshot_dataclass_carries_the_kpi_columns_of_0002():
    from dataclasses import fields

    kpis = {"skip_rate", "watched_pct"}
    assert kpis <= {f.name for f in fields(Snapshot)}
    assert kpis <= columns("snapshots")
    assert Snapshot(post_id="p").skip_rate is None and Snapshot(post_id="p").watched_pct is None


def test_0002_adds_the_two_snapshot_kpi_columns_and_nothing_else():
    sql = KPI_MIGRATION.read_text()
    statements = [
        s.strip() for s in re.sub(r"--[^\n]*", "", sql).split(";") if s.strip()
    ]
    assert statements == [
        "alter table studio.snapshots add column if not exists skip_rate double precision",
        "alter table studio.snapshots add column if not exists watched_pct double precision",
    ]  # nullable, no default: a metric the platform did not report stays NULL, never 0


def test_private_buckets_are_created():
    assert "('sources', 'sources', false), ('clips', 'clips', false)" in SQL


def test_0003_makes_character_and_platform_unique_for_the_account_upsert():
    sql = (MIGRATIONS / "0003_accounts_unique_platform.sql").read_text()
    statements = [s.strip() for s in re.sub(r"--[^\n]*", "", sql).split(";") if s.strip()]
    assert [" ".join(s.split()) for s in statements] == [
        "create unique index if not exists accounts_character_platform_key "
        "on studio.accounts (character_slug, platform)"
    ]  # the ON CONFLICT target of PostgresStore.upsert_account


def test_run_kinds_and_statuses_are_the_ones_the_log_and_health_know():
    # studio.runs has no CHECK on kind/status: the enums are the only gate, so pin them.
    assert {str(k) for k in RunKind} == {"daily", "weekly", "publish", "metrics"}
    assert {str(s) for s in RunStatus} == {"ok", "budget_stop", "error"}
    assert "check" not in table_body("runs")  # if a CHECK is ever added it must match the enums


# ---- 0004: the terminal's views and owner RPCs ------------------------------------------------------

TERMINAL_SQL = (MIGRATIONS / "0004_terminal_rpc.sql").read_text()
TERMINAL_VIEWS = ["v_channels", "v_queue", "v_library", "v_budget", "v_picks", "v_pick_history", "v_health"]
TERMINAL_RPCS = [
    "approve_clip", "reject_clip", "regenerate_clip", "set_budget", "set_account_mode",
    "decide_pick", "add_owner_link",
]
TERMINAL_HELPERS = ["num", "cadence_days", "upcoming_slot", "next_slot", "dropin_ratio", "accounts_for_clip", "approved_posts"]


def _function_sql(name: str) -> str:
    m = re.search(
        rf"create or replace function studio\.{name}\((.*?)\$\$;", TERMINAL_SQL, re.S
    )
    assert m, f"no function studio.{name}"
    return m.group(0)


def test_0004_views_are_security_invoker_and_granted_to_authenticated_only():
    for view in TERMINAL_VIEWS:
        assert re.search(
            rf"create or replace view studio\.{view}\s+with \(security_invoker = true\) as", TERMINAL_SQL
        ), view  # RLS of the owner applies through every view
        assert re.search(rf"grant select on studio\.{view} to authenticated;", TERMINAL_SQL), view
    assert not re.search(r"\banon\b", TERMINAL_SQL)  # nothing is ever granted to the anon role


def test_0004_functions_run_as_the_caller_with_an_empty_search_path():
    for name in TERMINAL_RPCS + TERMINAL_HELPERS:
        body = _function_sql(name)
        assert "security definer" not in body, name  # RLS decides, never the function owner
        assert "set search_path = ''" in body, name
        assert re.search(rf"revoke all on function studio\.{name}\(", TERMINAL_SQL), name
        assert re.search(rf"grant execute on function studio\.{name}\(.*?\) to authenticated;", TERMINAL_SQL), name
    for name in TERMINAL_RPCS:
        assert "security invoker" in _function_sql(name), name


def test_0004_approve_mirrors_schedule_clip():
    body = _function_sql("approve_clip")
    assert "clip_id uuid, caption text default null, hook text default null, schedule_at timestamptz default null" in body
    assert "for update" in body  # the state checked is the state written
    assert "studio.accounts_for_clip(" in body and "studio.upcoming_slot(" in body
    assert "'awaiting_approval', 'approved'" in body
    assert "state = 'scheduled'" in body
    rule = _function_sql("accounts_for_clip")
    assert "c.mode = 'recreate'" in rule and "studio.dropin_ratio(a.id, c.id) < a.dropin_share" in rule
    ratio = _function_sql("dropin_ratio")
    assert "order by p.scheduled_for desc, p.id desc" in ratio and "limit 10" in ratio  # ROLLING_WINDOW


def test_0004_autopilot_is_locked_below_six_approved_posts_in_the_database_too():
    body = _function_sql("set_account_mode")
    assert "studio.approved_posts(" in body and "< 6" in body
    assert "6 as autopilot_min_approved" in TERMINAL_SQL  # the view tells the UI the same bar


def test_0004_owner_decisions_are_recorded_like_studio_fav_decide():
    body = _function_sql("decide_pick")
    assert "'by', 'owner'" in body and "- 'hold_reason'" in body
    assert "('queued', 'made')" in body
    link = _function_sql("add_owner_link")
    assert "'owner'" in link and "'approved'" in link


def test_0004_realtime_and_storage_are_guarded_and_idempotent():
    for table in ("clips", "posts", "favorites"):
        assert f"alter publication supabase_realtime add table studio.{table}" in TERMINAL_SQL
    assert "bucket_id = 'clips'" in TERMINAL_SQL and "for select to authenticated" in TERMINAL_SQL
    assert "not exists (select 1 from pg_policies" in TERMINAL_SQL


# ---- 0005: terminal fixes (review round 1) ------------------------------------------------------------

FIXES_SQL_PATH = MIGRATIONS / "0005_terminal_fixes.sql"


def _fixes_function(name: str) -> str:
    m = re.search(rf"create or replace function studio\.{name}\((.*?)\$\$;", FIXES_SQL_PATH.read_text(), re.S)
    assert m, f"no function studio.{name} in 0005"
    return m.group(0)


def test_0005_approve_refuses_a_clip_without_a_master_and_never_stores_an_empty_caption():
    body = _fixes_function("approve_clip")
    assert "clip_id uuid, caption text default null, hook text default null, schedule_at timestamptz default null" in body
    assert "studio.queue_block_reason(c.id)" in body
    assert "nullif(btrim(approve_clip.caption), '')" in body and "nullif(btrim(approve_clip.hook), '')" in body
    helper = _fixes_function("queue_block_reason")
    assert "master_path" in helper and "no master file yet" in helper
    for name in ("approve_clip", "queue_block_reason"):
        body = _fixes_function(name)
        assert "security invoker" in body and "set search_path = ''" in body and "security definer" not in body
    sql = FIXES_SQL_PATH.read_text()
    assert "revoke all on function studio.queue_block_reason(uuid) from public;" in sql
    assert "grant execute on function studio.queue_block_reason(uuid) to authenticated;" in sql


def test_0005_v_queue_keeps_its_columns_and_appends_the_block_reason():
    sql = FIXES_SQL_PATH.read_text()
    old = re.search(r"create or replace view studio\.v_queue .*?from studio\.clips c", TERMINAL_SQL, re.S).group(0)
    new = re.search(r"create or replace view studio\.v_queue .*?from studio\.clips c", sql, re.S).group(0)
    assert "with (security_invoker = true)" in new
    cols = lambda text: re.findall(r"\bas (\w+),?\s*$", text, re.M)  # noqa: E731
    assert cols(new)[: len(cols(old))] == cols(old), "create or replace view may only append columns"
    assert cols(new)[-1] == "blocked_reason"
    assert "grant select on studio.v_queue to authenticated;" in sql


# ---- 0006: one slot rule, and a unique key on reviews --------------------------------------------------

SLOT_SQL_PATH = MIGRATIONS / "0006_slot_and_reviews.sql"
SLOT_SQL = SLOT_SQL_PATH.read_text()


def _slot_function(name: str) -> str:
    m = re.search(rf"create or replace function studio\.{name}\((.*?)\$\$;", SLOT_SQL, re.S)
    assert m, f"no function studio.{name} in 0006"
    return m.group(0)


def test_0006_free_slot_mirrors_planning_free_slot():
    body = _slot_function("free_slot")
    # the same statuses as studio.planning.TAKEN_STATUSES, the same day as publish's cap (claimed_at, else slot)
    assert "p.status in ('scheduled', 'posting', 'posted', 'needs_check')" in body
    assert "coalesce(p.claimed_at, p.scheduled_for) at time zone 'Europe/London'" in body
    assert "studio.upcoming_slot(" in body and "studio.cadence_days(" in body  # starts where upcoming_slot does
    assert "p.clip_id <> free_slot.exclude_clip_id" in body  # a clip's own half-written posts are left out
    assert "for i in 0..55 loop" in body  # FREE_SLOT_LOOKAHEAD_DAYS = 56
    assert "no free posting day" in body
    for name in ("free_slot", "next_free_slot"):
        fn = _slot_function(name)
        assert "security invoker" in fn and "set search_path = ''" in fn and "security definer" not in fn
    from studio.planning import FREE_SLOT_LOOKAHEAD_DAYS, TAKEN_STATUSES

    assert FREE_SLOT_LOOKAHEAD_DAYS == 56
    assert sorted(s.value for s in TAKEN_STATUSES) == ["needs_check", "posted", "posting", "scheduled"]


def test_0006_approve_clip_takes_its_default_slot_from_free_slot_and_keeps_everything_else():
    body = _slot_function("approve_clip")
    assert "clip_id uuid, caption text default null, hook text default null, schedule_at timestamptz default null" in body
    assert "coalesce(approve_clip.schedule_at, studio.free_slot(c.character_slug, targets, c.id, now()))" in body
    assert "studio.upcoming_slot(" not in body  # no second rule: an explicit schedule_at is the only other source
    # carried over from 0005 unchanged
    assert "studio.queue_block_reason(c.id)" in body and "for update" in body
    assert "nullif(btrim(approve_clip.caption), '')" in body and "nullif(btrim(approve_clip.hook), '')" in body
    assert "'awaiting_approval', 'approved'" in body and "state = 'scheduled'" in body
    assert "security invoker" in body and "set search_path = ''" in body and "security definer" not in body


def test_0006_v_queue_keeps_every_column_and_shows_the_free_slot():
    new = re.search(r"create or replace view studio\.v_queue .*?from studio\.clips c", SLOT_SQL, re.S).group(0)
    old = re.search(r"create or replace view studio\.v_queue .*?from studio\.clips c", FIXES_SQL_PATH.read_text(), re.S).group(0)
    cols = lambda text: re.findall(r"\bas (\w+),?\s*$", text, re.M)  # noqa: E731
    assert cols(new) == cols(old), "the view must keep exactly the columns of 0005"
    assert "studio.next_free_slot(c.id, now()) as next_slot" in new and "with (security_invoker = true)" in new


def test_0006_reviews_get_a_unique_key_after_the_old_duplicates_are_folded():
    assert re.search(
        r"create unique index if not exists reviews_week_character_slug_key\s+on studio\.reviews \(week, character_slug\);",
        SLOT_SQL,
    )  # the ON CONFLICT target of PostgresStore.upsert_review
    assert SLOT_SQL.index("delete from studio.reviews") < SLOT_SQL.index("create unique index")  # dedupe first
    assert "(r.created_at, r.id) > (keep.created_at, keep.id)" in SLOT_SQL  # the oldest row survives


def test_0006_grants_the_new_functions_to_authenticated_only():
    for sig in ("free_slot(text, uuid[], uuid, timestamptz)", "next_free_slot(uuid, timestamptz)"):
        assert f"revoke all on function studio.{sig} from public;" in SLOT_SQL
        assert f"grant execute on function studio.{sig} to authenticated;" in SLOT_SQL
    assert "grant select on studio.v_queue to authenticated;" in SLOT_SQL


# ---- 0007: characters view, the Make-it sheet, the Scanner card -------------------------------------------

CHAR_PATH = MIGRATIONS / "0007_characters_view.sql"
CHAR_SQL = CHAR_PATH.read_text()
CHAR_CODE = re.sub(r"--[^\n]*", "", CHAR_SQL)  # statements without their comments


def test_0007_adds_the_two_json_columns_the_python_side_writes():
    assert "alter table studio.characters add column if not exists setup jsonb not null default '{}'::jsonb;" in CHAR_SQL
    assert "alter table studio.runs add column if not exists details jsonb not null default '{}'::jsonb;" in CHAR_SQL
    assert {"setup"} <= columns("characters") and {"details"} <= columns("runs")  # models.Character.setup / Run.details


def test_0007_v_characters_lists_every_character_with_its_accounts():
    view = re.search(r"create or replace view studio\.v_characters .*?order by ch\.slug;", CHAR_SQL, re.S).group(0)
    assert "with (security_invoker = true)" in view  # the owner's RLS on characters and accounts applies
    for col in ("ch.slug", "ch.name", "ch.status", "ch.bodies", "ch.setup"):
        assert col in view
    assert "from studio.characters ch" in view and "left join" not in view  # a character with no account is still a row
    # the same notion of "connected" as v_channels: a missing or empty Postiz id is not a connection
    assert "'has_postiz', coalesce(a.postiz_integration_id, '') <> ''" in view
    assert "'platform', a.platform" in view and "'handle', a.handle" in view and "'mode', a.mode" in view
    assert "coalesce((" in view and "'[]'::jsonb) as accounts" in view
    assert "grant select on studio.v_characters to authenticated;" in CHAR_SQL
    assert not re.search(r"\banon\b", CHAR_CODE)


def test_0007_picks_views_keep_every_column_and_append_the_owner_instructions():
    cols = lambda text: re.findall(r"\bas (\w+),?\s*$", text, re.M)  # noqa: E731
    for view, base in (("v_picks", "from studio.favorites f"), ("v_pick_history", "from studio.favorites f")):
        new = re.search(rf"create or replace view studio\.{view} .*?{base}", CHAR_SQL, re.S).group(0)
        old = re.search(rf"create or replace view studio\.{view} .*?{base}", TERMINAL_SQL, re.S).group(0)
        assert "with (security_invoker = true)" in new
        assert cols(new)[: len(cols(old))] == cols(old), f"{view}: create or replace view may only append columns"
        assert cols(new)[len(cols(old)) :] == ["owner_note", "owner_mode", "owner_presence"]
        for key in ("owner_note", "owner_mode", "owner_presence"):
            assert f"f.proposal ->> '{key}' as {key}" in new
        assert f"grant select on studio.{view} to authenticated;" in CHAR_SQL


def _decide_pick() -> str:
    m = re.search(r"create or replace function studio\.decide_pick\((.*?)\$\$;", CHAR_SQL, re.S)
    assert m
    return m.group(0)


def test_0007_decide_pick_has_one_signature_and_keeps_the_function_rules():
    body = _decide_pick()
    sig = (
        "pick_id uuid,\n  decision text,\n  reason text default null,\n  character_slug text default null,\n"
        "  also_character text default null,\n  owner_note text default null,\n  owner_mode text default null,\n"
        "  owner_presence text default null\n"
    )
    assert sig in body  # the old four parameters first, in order, then the four new ones, all optional
    assert "security invoker" in body and "set search_path = ''" in body and "security definer" not in body
    # the 4-argument function of 0004 goes, so PostgREST resolves ONE function for every call
    assert SANCTIONED_DROP in CHAR_SQL and CHAR_SQL.index(SANCTIONED_DROP) < CHAR_SQL.index("create or replace function studio.decide_pick")
    assert "revoke all on function studio.decide_pick(uuid, text, text, text, text, text, text, text) from public;" in CHAR_SQL
    assert "grant execute on function studio.decide_pick(uuid, text, text, text, text, text, text, text) to authenticated;" in CHAR_SQL


def test_0007_decide_pick_keeps_every_refusal_and_effect_of_0004():
    old = _function_sql("decide_pick")
    new = _decide_pick()
    for message in re.findall(r"raise exception '([^']*)'", old):
        assert f"raise exception '{message}'" in new, f"the refusal {message!r} of 0004 is gone"
    for part in (
        "'by', 'owner'", "- 'hold_reason'", "('queued', 'made')", "for update",
        "when f.status in ('approved', 'analysed') then f.status", "when decide_pick.decision = 'skip' then 'skipped'",
    ):
        assert part in old and part in new, part


def test_0007_decide_pick_stores_the_owner_instructions_in_the_proposal():
    body = _decide_pick()
    assert "char_length(clean_note) > 280" in body and "nullif(btrim(decide_pick.owner_note), '')" in body
    assert "jsonb_build_object('owner_note', clean_note)" in body
    assert "clean_mode not in ('dropin', 'recreate')" in body and "jsonb_build_object('owner_mode', clean_mode)" in body
    assert "clean_presence not in ('cameo', 'featured', 'star')" in body
    # his part only counts in a Drop-in, whether the mode is given now or was stored earlier
    assert "coalesce(clean_mode, f.proposal ->> 'owner_mode') = 'dropin'" in body
    assert "jsonb_build_object('owner_presence', clean_presence)" in body
    assert "if decide_pick.decision = 'approve' then" in body  # a skip carries no instructions
    assert "proposal = (fa.proposal - 'hold_reason') || owner || jsonb_build_object('decision', record_)" in body


def test_0007_both_files_one_idempotent_sibling_for_the_other_character():
    body = _decide_pick()
    assert "also is not null and decide_pick.decision <> 'approve'" in body  # approve only
    assert "if also = new_slug then" in body and "unknown character" in body  # known, and not the chosen one
    # reuse before insert: the same url under that character, never the pick itself, oldest first, locked
    assert "fa.url = f.url and fa.character_slug = also and fa.id <> f.id" in body and "limit 1 for update" in body
    insert = re.search(r"insert into studio\.favorites\s*\((.*?)\)\s*values\s*\((.*?)\)\s*returning", body, re.S)
    assert insert
    cols = [c.strip() for c in insert.group(1).split(",")]
    assert cols == ["url", "platform", "creator_handle", "views", "outlier_x", "origin", "character_slug", "proposal", "scores", "total_score", "status"]
    assert [v.strip() for v in insert.group(2).split(",")][-1] == "'approved'"
    assert "to_jsonb(f) || jsonb_build_object('sibling', to_jsonb(sib))" in body  # both rows come back
    assert "if sib.status not in ('queued', 'made') then" in body  # a sibling already in production is left alone


def test_0007_realtime_follows_characters_accounts_and_runs_without_touching_anything_else():
    for table in ("characters", "accounts", "runs"):
        assert f"tablename = '{table}') then\n      alter publication supabase_realtime add table studio.{table};" in CHAR_SQL
    assert "if exists (select 1 from pg_publication where pubname = 'supabase_realtime')" in CHAR_SQL


def test_0007_stays_inside_schema_studio_and_grants_nothing_to_anon():
    assert not re.search(r"\banon\b", CHAR_CODE)
    assert re.findall(r"\b(?:public|auth|storage|extensions)\.[a-z_]+", CHAR_CODE) == []
    for stmt in re.findall(r"^(?:create table|alter table|create index \w+ on)\s+(\S+)", CHAR_CODE, re.M):
        assert stmt.startswith("studio."), stmt


# ---- 0008: Drop-in first -----------------------------------------------------------------------------------

DROPIN_PATH = MIGRATIONS / "0008_dropin_first.sql"
DROPIN_SQL = DROPIN_PATH.read_text()
DROPIN_CODE = re.sub(r"--[^\n]*", "", DROPIN_SQL)
OLD_DECIDE_ARGS = "uuid, text, text, text, text, text, text, text"
NEW_DECIDE_ARGS = "uuid, text, text, text, text, text, text, text, text[], text"


def _dropin_function(name: str) -> str:
    m = re.search(rf"create or replace function studio\.{name}\((.*?)\$\$;", DROPIN_SQL, re.S)
    assert m, f"no function studio.{name} in 0008"
    return m.group(0)


def test_0008_adds_the_minors_check_to_sources_and_the_model_writes_it():
    assert "alter table studio.sources add column if not exists has_minors boolean;" in DROPIN_SQL  # nullable: null = not checked
    assert "has_minors" in columns("sources")  # models.Source.has_minors has its column
    assert Source(kind="owner_inbox", body="biped", bodies=1, duration_s=5.0).has_minors is None


def test_0008_a_share_of_one_is_no_cap_in_accounts_for_clip_as_in_planning():
    body = _dropin_function("accounts_for_clip")
    old = _function_sql("accounts_for_clip")
    assert "(c.mode = 'recreate' or a.dropin_share >= 1 or studio.dropin_ratio(a.id, c.id) < a.dropin_share)" in body
    assert "returns setof studio.accounts" in body and "security invoker" in body and "set search_path = ''" in body
    # nothing else of the rule moved: same joins, same connected test, same order
    for part in ("join studio.accounts a on a.character_slug = c.character_slug", "coalesce(a.postiz_integration_id, '') <> ''",
                 "order by a.character_slug, a.platform"):
        assert part in old and part in body, part


def test_0008_decide_pick_replaces_the_8_argument_function_with_one_that_adds_props_and_music():
    body = _dropin_function("decide_pick")
    assert (
        "owner_presence text default null,\n  owner_props text[] default null,\n  owner_music text default null\n)" in body
    )  # the eight parameters of 0007 first, in order, then the two new ones, both optional
    assert "security invoker" in body and "set search_path = ''" in body and "security definer" not in body
    assert SANCTIONED_DROP_0008 in DROPIN_SQL
    assert DROPIN_SQL.index(SANCTIONED_DROP_0008) < DROPIN_SQL.index("create or replace function studio.decide_pick")
    assert f"revoke all on function studio.decide_pick({NEW_DECIDE_ARGS}) from public;" in DROPIN_SQL
    assert f"grant execute on function studio.decide_pick({NEW_DECIDE_ARGS}) to authenticated;" in DROPIN_SQL
    assert OLD_DECIDE_ARGS + ")" not in DROPIN_CODE.replace(SANCTIONED_DROP_0008, "")  # the old signature is only dropped


def test_0008_decide_pick_keeps_every_refusal_and_effect_of_0007():
    new = _dropin_function("decide_pick")
    old = _decide_pick()
    for message in re.findall(r"raise exception '([^']*)'", old):
        assert f"raise exception '{message}'" in new, f"the refusal {message!r} of 0007 is gone"
    for part in (
        "'by', 'owner'", "- 'hold_reason'", "('queued', 'made')", "for update", "char_length(clean_note) > 280",
        "clean_mode not in ('dropin', 'recreate')", "clean_presence not in ('cameo', 'featured', 'star')",
        "coalesce(clean_mode, f.proposal ->> 'owner_mode') = 'dropin'", "jsonb_build_object('owner_presence', clean_presence)",
        "when f.status in ('approved', 'analysed') then f.status", "when decide_pick.decision = 'skip' then 'skipped'",
        "if decide_pick.decision = 'approve' then", "proposal = (fa.proposal - 'hold_reason') || owner || jsonb_build_object('decision', record_)",
        "fa.url = f.url and fa.character_slug = also and fa.id <> f.id", "limit 1 for update",
        "to_jsonb(f) || jsonb_build_object('sibling', to_jsonb(sib))", "if sib.status not in ('queued', 'made') then",
    ):
        assert part in old and part in new, part
    cols_old = re.search(r"insert into studio\.favorites\s*\((.*?)\)", old, re.S).group(1)
    assert re.search(r"insert into studio\.favorites\s*\((.*?)\)", new, re.S).group(1) == cols_old  # the sibling copies the same columns


def test_0008_gadgets_are_at_most_three_items_of_one_to_forty_characters_and_blank_keeps_what_is_stored():
    body = _dropin_function("decide_pick")
    assert "clean_props jsonb := '[]'::jsonb;" in body
    assert "coalesce(jsonb_agg(btrim(p) order by ord), '[]'::jsonb)" in body  # trimmed, order kept
    assert "if jsonb_array_length(clean_props) > 3 then" in body and "owner_props takes at most 3 items" in body
    assert "t is null or char_length(t) not between 1 and 40" in body and "each of owner_props must be 1 to 40 characters" in body
    # written only when approving, and only when something is left after trimming (an empty array keeps what is stored)
    approve = body.split("if decide_pick.decision = 'approve' then", 1)[1].split("record_ :=", 1)[0]
    assert "if jsonb_array_length(clean_props) > 0 then" in approve
    assert "owner := owner || jsonb_build_object('owner_props', clean_props);" in approve
    assert "owner_props" not in body.split("record_ :=", 1)[1].replace("owner || jsonb", "")  # nowhere else is it written


def test_0008_music_is_one_of_three_arms_and_original_is_refused_for_a_recreate():
    body = _dropin_function("decide_pick")
    assert "clean_music not in ('in_app', 'original', 'ai_beat')" in body and "owner_music must be in_app, original or ai_beat" in body
    assert "nullif(btrim(decide_pick.owner_music), '')" in body
    # a Recreate has no original audio: refused whether the mode is given now or was stored earlier, before anything is written
    refusal = "if clean_music = 'original' and coalesce(clean_mode, f.proposal ->> 'owner_mode') = 'recreate' then"
    assert refusal in body and "owner_music original needs the dropin mode" in body
    assert body.index(refusal) < body.index("update studio.favorites fa")
    approve = body.split("if decide_pick.decision = 'approve' then", 1)[1].split("record_ :=", 1)[0]
    assert "if clean_music is not null then" in approve and "jsonb_build_object('owner_music', clean_music)" in approve
    from studio.models import MUSIC_ARMS

    assert set(MUSIC_ARMS) == {"in_app", "original", "ai_beat"}  # the same three the Python side knows


def test_0008_both_hands_the_sibling_the_same_props_and_music():
    body = _dropin_function("decide_pick")
    # `owner` carries every instruction of the call; the sibling is updated or inserted with it, or copies the proposal
    assert body.count("|| owner ||") == 2  # the pick itself and an existing sibling
    assert "f.proposal, f.scores" in body  # a new sibling copies the pick's proposal, which already holds `owner`


def test_0008_attach_clip_stores_the_path_of_the_owners_upload_in_the_proposal():
    body = _dropin_function("attach_clip")
    assert "attach_clip(pick_id uuid, storage_path text)" in body and "returns jsonb" in body
    assert "security invoker" in body and "set search_path = ''" in body and "security definer" not in body
    # the path must be exactly what the browser writes for THIS pick, so nothing else of the bucket can be linked
    assert "clean !~ ('^owner/' || attach_clip.pick_id::text || '/[^/[:space:]]+$')" in body
    assert "storage_path must be owner/<pick id>/<file>" in body
    assert "unknown pick" in body and "no_data_found" in body and "for update" in body
    assert "('queued', 'made')" in body and "too late to attach a clip" in body
    assert "proposal = fa.proposal || jsonb_build_object('owner_clip_path', clean)" in body
    assert "source_id = case when fa.proposal ->> 'owner_clip_path' is distinct from clean then null else fa.source_id end" in body
    assert "return to_jsonb(f);" in body
    assert "revoke all on function studio.attach_clip(uuid, text) from public;" in DROPIN_SQL
    assert "grant execute on function studio.attach_clip(uuid, text) to authenticated;" in DROPIN_SQL


def test_0008_the_owner_may_insert_and_read_only_under_sources_owner():
    for name, action, clause in (
        ("odd_eyes_owner_uploads_sources", "for insert", "with check"),
        ("odd_eyes_owner_reads_sources", "for select", "using"),
    ):
        m = re.search(rf"create policy {name} on storage\.objects {action} to authenticated\s+{clause} \((.*?)\);", DROPIN_SQL, re.S)
        assert m, name
        rule = m.group(1)
        assert "bucket_id = 'sources'" in rule and "name like 'owner/%'" in rule
        assert "(select auth.jwt() ->> 'email') = 'o.schwend@gmail.com'" in rule  # the owner rule of 0004's clips policy
        assert f"policyname = '{name}'" in DROPIN_SQL  # idempotent: created only when missing
    assert "to_regclass('storage.objects') is not null" in DROPIN_SQL
    assert not re.search(r"create policy [^;]*?\bfor (update|delete|all)\b", DROPIN_CODE)  # no rewrite or removal of objects
    assert not re.search(r"\banon\b", DROPIN_CODE)
    # the bucket rule it mirrors
    assert "(select auth.jwt() ->> 'email') = 'o.schwend@gmail.com'" in TERMINAL_SQL


def test_0008_picks_views_keep_every_column_and_append_the_card():
    cols = lambda text: re.findall(r"\bas (\w+),?\s*$", text, re.M)  # noqa: E731
    appended = [
        "owner_props", "owner_music", "owner_clip_path", "tier", "theme", "posted_at", "gallery", "thumbnail_url", "preview_url",
    ]
    for view in ("v_picks", "v_pick_history"):
        new = re.search(rf"create or replace view studio\.{view} .*?from studio\.favorites f", DROPIN_SQL, re.S).group(0)
        old = re.search(rf"create or replace view studio\.{view} .*?from studio\.favorites f", CHAR_SQL, re.S).group(0)
        assert "with (security_invoker = true)" in new
        assert cols(new)[: len(cols(old))] == cols(old), f"{view}: create or replace view may only append columns"
        assert cols(new)[len(cols(old)) :] == appended
        for key in ("owner_music", "owner_clip_path", "tier", "theme", "thumbnail_url", "preview_url", "posted_at"):
            assert f"f.proposal ->> '{key}' as {key}" in new
        assert "f.proposal -> 'owner_props' as owner_props" in new  # a JSON array, as the terminal wants it
        assert "'higgsfield_library'" in new and "preset_id" in new and "as gallery" in new
        assert f"grant select on studio.{view} to authenticated;" in DROPIN_SQL
    # the where clauses and joins of 0007 are unchanged
    assert "where f.status = 'new'" in DROPIN_SQL and "where f.status <> 'new'" in DROPIN_SQL


def test_0008_stays_inside_schema_studio_apart_from_its_storage_policies_and_grants_nothing_to_anon():
    assert not re.search(r"\banon\b", DROPIN_CODE)
    assert set(re.findall(r"\b(?:public|auth|storage|extensions)\.[a-z_]+", DROPIN_CODE)) == {"auth.jwt", "storage.objects"}
    for stmt in re.findall(r"^(?:create table|alter table|create index \w+ on)\s+(\S+)", DROPIN_CODE, re.M):
        assert stmt.startswith("studio."), stmt
    assert not re.search(r"\b(truncate|delete|update studio\.(?!favorites))\b", DROPIN_CODE, re.I)
    assert not re.search(r"\balter\s+column\b|\brename\b", DROPIN_CODE, re.I)


# ---- 0009: the analyst's data on every pick card -----------------------------------------------------------

ANALYST_PATH = MIGRATIONS / "0009_analyst.sql"
ANALYST_SQL = ANALYST_PATH.read_text()
ANALYST_CODE = re.sub(r"--[^\n]*", "", ANALYST_SQL)
ANALYST_COLUMNS = ["velocity", "engagement", "saturation_count", "trait_matches", "why", "analysis"]


def test_0009_picks_views_keep_every_column_and_append_the_analysts_fields():
    cols = lambda text: re.findall(r"\bas (\w+),?\s*$", text, re.M)  # noqa: E731
    for view in ("v_picks", "v_pick_history"):
        new = re.search(rf"create or replace view studio\.{view} .*?from studio\.favorites f", ANALYST_SQL, re.S).group(0)
        old = re.search(rf"create or replace view studio\.{view} .*?from studio\.favorites f", DROPIN_SQL, re.S).group(0)
        assert "with (security_invoker = true)" in new
        assert cols(new)[: len(cols(old))] == cols(old), f"{view}: create or replace view may only append columns"
        assert cols(new)[len(cols(old)) :] == ANALYST_COLUMNS
        # numbers go through studio.num (a non-number is null, never 0); objects and arrays stay JSON, text stays text
        assert "studio.num(f.proposal -> 'velocity') as velocity" in new
        assert "studio.num(f.proposal -> 'saturation_count') as saturation_count" in new
        assert "f.proposal -> 'engagement' as engagement" in new
        assert "f.proposal -> 'trait_matches' as trait_matches" in new
        assert "f.proposal ->> 'why' as why" in new
        assert "f.proposal -> 'analysis' as analysis" in new
        assert f"grant select on studio.{view} to authenticated;" in ANALYST_SQL
    # the where clauses and joins of 0008 are unchanged
    assert "where f.status = 'new'" in ANALYST_CODE and "where f.status <> 'new'" in ANALYST_CODE
    assert "left join studio.clips c on c.id = f.clip_id" in ANALYST_CODE


def test_0009_changes_nothing_but_the_two_views():
    statements = [s.strip() for s in ANALYST_CODE.split(";") if s.strip()]
    kinds = sorted(re.match(r"(create or replace view studio\.\w+|grant select on studio\.\w+)", s).group(1) for s in statements)
    assert kinds == [
        "create or replace view studio.v_pick_history", "create or replace view studio.v_picks",
        "grant select on studio.v_pick_history", "grant select on studio.v_picks",
    ]  # fmt: skip
    assert not re.search(r"\b(drop|truncate|delete|insert|update|alter)\b", ANALYST_CODE, re.I)
    assert not re.search(r"\banon\b", ANALYST_CODE)
    assert re.findall(r"\b(?:public|auth|storage|extensions)\.[a-z_]+", ANALYST_CODE) == []


def test_0009_every_column_it_exposes_is_a_field_the_cli_validates():
    import inspect

    from studio import favorites

    source = inspect.getsource(favorites._validate_analyst_fields) + inspect.getsource(favorites.validate_card)
    for column in ANALYST_COLUMNS:
        assert f'"{column}"' in source, f"{column}: exposed by the views but not validated by studio.favorites"


# ---- 0010: the long list and the "In the works" tracker ---------------------------------------------------------------

TRACKER_PATH = MIGRATIONS / "0010_tracker.sql"
TRACKER_SQL = TRACKER_PATH.read_text()
TRACKER_CODE = re.sub(r"--[^\n]*", "", TRACKER_SQL)
LONGLIST_COLUMNS = [
    "recognisability", "original_views", "original_url", "source_status", "audio_risk", "est_credits", "season", "checks",
    "source_candidates",
]  # fmt: skip
TRACKER_COLUMNS = [
    "pick_id", "character_slug", "character_name", "url", "platform", "creator_handle", "views", "outlier_x", "tier", "theme",
    "concept", "hook", "thumbnail_url", "preview_url", "gallery", "posted_at", "velocity", "proposed_mode", "owner_mode",
    "owner_presence", "owner_music", "owner_clip_path", "status", "decision", "approved_at", "note", "source_id", "analysis",
    "fetch_failed", "clip_id", "clip_state", "clip_mode", "clip_state_since", "clip_failure", "credits_spent", "post_id",
    "post_status", "post_scheduled_for", "post_posted_at", "post_url", "post_error", "latest_views", "caption", "hashtags",
    "first_comment",
]  # fmt: skip


def _view(sql: str, name: str) -> str:
    return re.search(rf"create or replace view studio\.{name} .*?from studio\.favorites f", sql, re.S).group(0)


def _select_list(view: str) -> list[str]:
    """Every output column of a view's select list, in order (`f.url` -> url, `x as y` -> y), an item running over several
    lines included: the list is split at the commas outside parentheses and quotes."""
    body = view.split("select", 1)[1].rsplit("from studio.favorites f", 1)[0]
    items, depth, quoted, current = [], 0, False, ""
    for ch in body:
        if ch == "'":
            quoted = not quoted
        elif not quoted and ch == "(":
            depth += 1
        elif not quoted and ch == ")":
            depth -= 1
        if ch == "," and depth == 0 and not quoted:
            items.append(current)
            current = ""
        else:
            current += ch
    items.append(current)
    out = []
    for item in items:
        item = " ".join(item.split())
        m = re.search(r"\bas (\w+)$", item) or re.fullmatch(r"\w+\.(\w+)", item)
        assert m, f"cannot read the column of {item!r}"
        out.append(m.group(1))
    return out


def test_0010_picks_views_keep_every_column_and_append_the_long_list():
    cols = lambda text: re.findall(r"\bas (\w+),?\s*$", text, re.M)  # noqa: E731
    for view in ("v_picks", "v_pick_history"):
        new, old = _view(TRACKER_SQL, view), _view(ANALYST_SQL, view)
        assert "with (security_invoker = true)" in new
        assert new.startswith(old.rsplit("\nfrom studio.favorites f", 1)[0]), f"{view}: 0009's select list must stay as it is"
        assert cols(new)[: len(cols(old))] == cols(old), f"{view}: create or replace view may only append columns"
        assert cols(new)[len(cols(old)) :] == LONGLIST_COLUMNS
        # numbers through studio.num (a non-number is null, never 0), texts as text, the two lists only when they are arrays
        for key in ("recognisability", "original_views", "est_credits"):
            assert f"studio.num(f.proposal -> '{key}') as {key}" in new
        for key in ("original_url", "source_status", "audio_risk", "season"):
            assert f"f.proposal ->> '{key}' as {key}" in new
        for key in ("checks", "source_candidates"):
            assert f"case when jsonb_typeof(f.proposal -> '{key}') = 'array' then f.proposal -> '{key}' end as {key}" in new
        assert f"grant select on studio.{view} to authenticated;" in TRACKER_SQL
    # the where clauses and joins of 0009 are unchanged
    assert "where f.status = 'new'" in TRACKER_CODE and "where f.status <> 'new'" in TRACKER_CODE
    assert "left join studio.clips c on c.id = f.clip_id" in TRACKER_CODE


def test_0010_is_views_and_grants_only():
    statements = [s.strip() for s in TRACKER_CODE.split(";") if s.strip()]
    kinds = sorted(re.match(r"(create or replace view studio\.\w+|grant select on studio\.\w+)", s).group(1) for s in statements)
    assert kinds == [
        "create or replace view studio.v_pick_history", "create or replace view studio.v_picks", "create or replace view studio.v_queue",
        "create or replace view studio.v_tracker",
        "grant select on studio.v_pick_history", "grant select on studio.v_picks", "grant select on studio.v_queue",
        "grant select on studio.v_tracker",
    ]  # fmt: skip
    assert not re.search(r"\b(drop|truncate|delete|insert|update|alter|create table|create function)\b", TRACKER_CODE, re.I)
    assert not re.search(r"\banon\b", TRACKER_CODE)
    assert re.findall(r"\b(?:public|auth|storage|extensions)\.[a-z_]+", TRACKER_CODE) == []
    assert "grant select on studio.v_tracker to authenticated;" in TRACKER_SQL


def test_0010_every_long_list_column_is_a_field_the_cli_validates():
    import inspect

    from studio import favorites

    source = inspect.getsource(favorites._validate_longlist_fields) + "".join(map(repr, favorites.LONGLIST_TEXT_KEYS))
    for column in LONGLIST_COLUMNS:
        assert f'"{column}"' in source or f"'{column}'" in source, f"{column}: exposed by the views but not validated"


def test_0010_tracker_has_its_columns_in_order_and_runs_as_the_caller():
    tracker = _view(TRACKER_SQL, "v_tracker")
    assert tracker.startswith("create or replace view studio.v_tracker with (security_invoker = true) as")
    assert _select_list(tracker) == TRACKER_COLUMNS


def test_0010_tracker_follows_an_approved_pick_until_a_week_after_its_post():
    tail = TRACKER_CODE.split("create or replace view studio.v_tracker", 1)[1]
    where = tail.split("\nwhere ", 1)[1].split(";", 1)[0]
    assert "f.status in ('approved', 'analysed', 'queued')" in where
    assert "f.status = 'made'" in where and "interval '7 days'" in where
    # a made pick with no post yet (awaiting approval) must stay: the cut-off is null-safe
    assert "not coalesce(p.status = 'posted' and coalesce(p.claimed_at, p.scheduled_for) < now() - interval '7 days', false)" in where
    assert "'new'" not in where and "'skipped'" not in where


def test_0010_tracker_joins_the_newest_clip_its_credits_its_post_and_the_latest_views():
    tail = TRACKER_CODE.split("create or replace view studio.v_tracker", 1)[1]
    # the clip: by favorites.clip_id or the clip's features.fav_id (a Regenerate or a remake), the newest one
    assert "where x.id = f.clip_id or x.features ->> 'fav_id' = f.id::text" in tail
    assert "order by x.created_at desc, x.id desc" in tail
    # credits: every settled ledger entry of every clip of the pick
    assert "where l.kind = 'settle' and (y.id = f.clip_id or y.features ->> 'fav_id' = f.id::text)" in tail
    assert "coalesce(sp.spent, 0) as credits_spent" in tail
    # the post: the latest slot, a failed / needs_check post first among the posts of one slot
    assert "order by q.scheduled_for desc" in tail
    assert "case q.status when 'failed' then 0 when 'needs_check' then 1" in tail
    assert "case when p.status = 'posted' then coalesce(p.claimed_at, p.scheduled_for) end as post_posted_at" in tail
    # the views of the post's latest snapshot, never a sum that hides a missing reading
    assert "select s.views from studio.snapshots s where s.post_id = p.id order by s.captured_at desc limit 1" in tail
    # the failure reason and the best-effort state time
    assert "coalesce(nullif(btrim(c.reject_reason), ''), qp.problems, nullif(btrim(c.qa ->> 'error'), '')) as clip_failure" in tail
    assert "greatest(c.created_at, cl.last_entry, cp.last_claim) as clip_state_since" in tail
    assert "f.created_at as approved_at" in tail  # no decision time is stored (decide / decide_pick record none)


def test_0010_v_queue_keeps_every_column_of_0006_and_appends_the_first_comment():
    cols = lambda text: re.findall(r"\bas (\w+),?\s*$|^  \w+\.(\w+),?\s*$", text, re.M)  # noqa: E731
    view = lambda sql: re.search(r"create or replace view studio\.v_queue .*?where c\.state = 'awaiting_approval';", sql, re.S).group(0)  # noqa: E731
    old_sql = (MIGRATIONS / "0006_slot_and_reviews.sql").read_text()
    new, old = view(TRACKER_SQL), view(old_sql)
    names = lambda text: [a or b for a, b in cols(text)]  # noqa: E731
    assert names(new)[: len(names(old))] == names(old), "create or replace view may only append columns"
    assert names(new)[len(names(old)) :] == ["first_comment"]
    assert "c.features ->> 'first_comment' as first_comment" in new
    # everything else of 0006's view is unchanged: the source joins, the pick, the free slot, the block reason, the filter
    assert new.replace(",\n  c.features ->> 'first_comment' as first_comment", "") == old
    assert "grant select on studio.v_queue to authenticated;" in TRACKER_SQL


def test_0010_tracker_carries_the_post_text_and_the_first_comment_of_its_clip():
    tail = TRACKER_CODE.split("create or replace view studio.v_tracker", 1)[1]
    assert "select x.id, x.state, x.mode, x.created_at, x.reject_reason, x.qa, x.caption, x.hashtags, x.features" in tail
    assert "c.features ->> 'first_comment' as first_comment" in tail


# ---- 0011: when the owner decided ---------------------------------------------------------------------------------------

DECISION_PATH = MIGRATIONS / "0011_decision_time.sql"
DECISION_SQL = DECISION_PATH.read_text()
DECISION_CODE = re.sub(r"--[^\n]*", "", DECISION_SQL)
_DECIDE_PICK = re.compile(r"create or replace function studio\.decide_pick\(.*?\n\$\$;", re.S)


def test_0011_is_decide_pick_v_tracker_and_their_grants_only():
    code = _DECIDE_PICK.sub("", DECISION_CODE)
    statements = [s.strip() for s in code.split(";") if s.strip()]
    kinds = sorted(
        re.match(r"(create or replace view studio\.\w+|grant select on studio\.\w+|revoke all on function studio\.\w+|grant execute on function studio\.\w+)", s).group(1)
        for s in statements
    )
    assert kinds == [
        "create or replace view studio.v_tracker", "grant execute on function studio.decide_pick", "grant select on studio.v_tracker",
        "revoke all on function studio.decide_pick",
    ]  # fmt: skip
    assert DECISION_CODE.count("create or replace function") == 1
    assert not re.search(r"\b(drop|truncate|delete|insert|update|alter|create table)\b", code, re.I)
    assert not re.search(r"\banon\b", DECISION_CODE)
    assert re.findall(r"\b(?:public|auth|storage|extensions)\.[a-z_]+", DECISION_CODE) == []


def test_0011_decide_pick_is_0008s_word_for_word_but_stores_when_the_owner_decided():
    old, new = _DECIDE_PICK.search(DROPIN_SQL).group(0), _DECIDE_PICK.search(DECISION_SQL).group(0)
    record = "jsonb_build_object('decision', decide_pick.decision, 'by', 'owner', 'reason', clean"
    assert f"  record_ := {record});" in old
    assert f"  record_ := {record}, 'at', now());" in new
    assert new.replace(", 'at', now());", ");") == old  # the signature, the refusals, the "Both" sibling and the writes are 0008's
    assert "security invoker" in new and "set search_path = ''" in new and "security definer" not in new
    for line in (
        f"revoke all on function studio.decide_pick({NEW_DECIDE_ARGS}) from public;",
        f"grant execute on function studio.decide_pick({NEW_DECIDE_ARGS}) to authenticated;",
    ):
        assert line in DROPIN_SQL and line in DECISION_SQL, line
    assert "drop function" not in DECISION_CODE  # the same signature: replaced in place, still one function for PostgREST


def test_0011_v_tracker_is_0010s_with_approved_at_from_the_decision_and_decided_at_appended():
    old, new = _view(TRACKER_SQL, "v_tracker"), _view(DECISION_SQL, "v_tracker")
    assert new.startswith("create or replace view studio.v_tracker with (security_invoker = true) as")
    assert _select_list(new) == TRACKER_COLUMNS + ["decided_at"]  # 0010's columns in order, one appended
    assert "  coalesce(da.decided_at, f.created_at) as approved_at," in new and "  da.decided_at as decided_at\n" in new
    # nothing else of 0010's view changed: the joins after the two new laterals, the where clause
    whole_old = re.search(r"create or replace view studio\.v_tracker .*?interval '7 days', false\)\);", TRACKER_SQL, re.S).group(0)
    whole_new = re.search(r"create or replace view studio\.v_tracker .*?interval '7 days', false\)\);", DECISION_SQL, re.S).group(0)
    lateral = re.search(r"cross join lateral \(select f\.proposal #>> '\{decision,at\}' as decided\) dt\ncross join lateral \(\n.*?\n\) da\n", whole_new, re.S)
    assert lateral, "the decision time is read in two laterals: the text, then the checked time"
    back = (
        whole_new.replace(lateral.group(0), "")
        .replace("  coalesce(da.decided_at, f.created_at) as approved_at,", "  f.created_at as approved_at,")
        .replace(",\n  da.decided_at as decided_at\n", "\n")
    )
    assert back == whole_old
    assert "grant select on studio.v_tracker to authenticated;" in DECISION_SQL


def test_0011_only_a_valid_iso_decision_time_is_cast_and_anything_else_falls_back_to_the_filing_time():
    block = re.search(r"\) dt\ncross join lateral \(\n(.*?)\n\) da", DECISION_SQL, re.S).group(1)
    shape = re.search(r"when dt\.decided ~ '(.*?)'\s+then case", block, re.S)
    assert shape, "the cast is guarded by the shape of the text"
    pattern = re.compile(shape.group(1))
    for good in ("2026-10-05T15:20:00.123456+01:00", "2026-10-05T14:20:00+00:00", "2026-02-28T23:59:59Z"):
        assert pattern.fullmatch(good), good
    for bad in ("2026-13-05T15:20:00+01:00", "2026-10-05 15:20", "yesterday", "2026-10-05", "0000-01-01T00:00:00Z", "2026-10-05T24:00:00Z"):
        assert not pattern.fullmatch(bad), bad
    # a day the month does not have (30 February) is checked before the cast, inside the guarded branch
    inner = block.split("then case", 1)[1]
    assert "make_date(substr(dt.decided, 1, 4)::int, substr(dt.decided, 6, 2)::int, 1) + interval '1 month' - interval '1 day'" in inner
    assert inner.index("<=") < inner.index("then dt.decided::timestamptz")
    assert block.count("::timestamptz") == 1  # the only cast, the last thing evaluated


# ---- 0012: Drop a video -----------------------------------------------------------------------------------------------------

DROPVIDEO_PATH = MIGRATIONS / "0012_drop_a_video.sql"
DROPVIDEO_SQL = DROPVIDEO_PATH.read_text()
DROPVIDEO_CODE = re.sub(r"--[^\n]*", "", DROPVIDEO_SQL)


def _function(sql: str, name: str) -> str:
    return re.search(rf"create or replace function studio\.{name}\(.*?\n\$\$;", sql, re.S).group(0)


def test_0012_creates_add_drop_request_job_and_v_tracker_and_nothing_else():
    code = re.sub(r"create or replace function studio\.\w+\(.*?\n\$\$;", "", DROPVIDEO_CODE, flags=re.S)
    code = re.sub(r"do \$\$.*?\n\$\$;", "", code, flags=re.S)
    statements = [s.strip() for s in code.split(";") if s.strip()]
    kinds = sorted(
        re.match(r"(create or replace view studio\.\w+|grant select on studio\.\w+|revoke all on function studio\.\w+|grant execute on function studio\.\w+)", s).group(1)
        for s in statements
    )
    assert kinds == [
        "create or replace view studio.v_tracker", "grant execute on function studio.add_drop", "grant execute on function studio.request_job",
        "grant execute on function studio.set_drop_footage", "grant select on studio.v_tracker", "revoke all on function studio.add_drop",
        "revoke all on function studio.request_job", "revoke all on function studio.set_drop_footage",
    ]  # fmt: skip
    assert DROPVIDEO_CODE.count("create or replace function") == 3
    assert re.findall(r"create or replace function studio\.(\w+)", DROPVIDEO_CODE) == ["add_drop", "request_job", "set_drop_footage"]
    assert not re.search(r"\b(truncate|delete|alter|create table|drop function|drop view|drop table)\b", DROPVIDEO_CODE, re.I)
    # the two do-blocks: pg_net only where the database has it, and the anon revoke only where the role exists
    assert "pg_available_extensions where name = 'pg_net'" in DROPVIDEO_CODE
    assert "create extension if not exists pg_net with schema extensions;" in DROPVIDEO_CODE
    assert "rolname = 'anon'" in DROPVIDEO_CODE and "revoke all on function studio.request_job(uuid, text, jsonb) from anon" in DROPVIDEO_CODE
    assert "grant execute on function studio.request_job(uuid, text, jsonb) to anon" not in DROPVIDEO_CODE
    # outside schema studio: only the owner rule, the Vault view and pg_net's http_post (and pg_catalog lookups)
    outside = set(re.findall(r"\b(?:public|auth|storage|extensions|vault|net)\.[a-z_]+", DROPVIDEO_CODE))
    assert outside == {"auth.jwt", "vault.decrypted_secrets", "net.http_post"}


def test_0012_request_job_is_a_security_definer_with_a_fixed_path_and_the_owner_check_first():
    body = _function(DROPVIDEO_SQL, "request_job")
    assert "request_job(pick_id uuid, kind text, adjust jsonb default null)" in body and "returns jsonb" in body
    assert "security definer" in body and "set search_path = ''" in body and "security invoker" not in body
    owner = "if coalesce((select auth.jwt() ->> 'email'), '') <> 'o.schwend@gmail.com' then"
    assert body.index(owner) < body.index("select * into f") < body.index("update studio.favorites")  # checked before anything
    assert "insufficient_privilege" in body
    assert "request_job.kind not in ('process', 'make')" in body
    assert "for update" in body and "is not a dropped video" in body and "is already made" in body
    # every studio object is schema-qualified (the empty search_path would not find it otherwise)
    for name in re.findall(r"\b(from|update|into)\s+(\w+)\.", body):
        assert name[1] in ("studio", "vault", "pg_catalog"), name


def test_0012_make_it_is_the_one_writer_of_make_requested_and_checks_the_adjust():
    body = _function(DROPVIDEO_SQL, "request_job")
    assert "'make_requested', jsonb_build_object('at', now(), 'by', 'owner')" in body
    assert "state_ not in ('ready', 'failed') or not (d ? 'credits') or not (d ? 'source_id')" in body
    assert "k not in ('star', 'part', 'gadgets', 'hook', 'start_s', 'length_s', 'crop_x')" in body
    assert "between 1 and 80" in body and "('cameo', 'featured', 'star')" in body and "jsonb_array_length(v) > 3" in body
    assert "length_ < 6 or length_ > 16" in body and "start_ + length_ > dur + 0.15" in body
    assert "between 0 and 1" in body
    # the same keys and limits as the CLI's own check (studio.drop.validate_adjust), so neither side can drift
    from studio import drop

    assert drop.ADJUST_KEYS == ("star", "part", "gadgets", "hook", "start_s", "length_s", "crop_x")
    assert (drop.MASTER_MIN_S, drop.MASTER_MAX_S) == (6.0, 16.0) and drop.PARTS == ("cameo", "featured", "star")
    # a check runs from these states, and an upload must be attached first
    assert "state_ not in ('uploading', 'checking', 'waiting', 'failed')" in body
    assert "the upload has not finished" in body


def test_0012_the_dispatch_never_exposes_the_token():
    body = _function(DROPVIDEO_SQL, "request_job")
    dispatch = body.split("-- the GitHub dispatch", 1)[1]
    assert "select s.decrypted_secret into token from vault.decrypted_secrets s where s.name = 'github_dispatch_token'" in dispatch
    assert "url := 'https://api.github.com/repos/oschwend-prog/character-studio/dispatches'" in dispatch
    assert "'event_type', 'drop-' || request_job.kind" in dispatch and "'client_payload', jsonb_build_object('pick_id', f.id::text)" in dispatch
    assert "'Authorization', 'Bearer ' || token" in dispatch
    assert "exception when others then\n    dispatched := false;" in dispatch  # a failure is swallowed: no message carries it
    tail = body.split("token := null;", 1)[1]
    assert "token" not in tail and "return to_jsonb(f) || jsonb_build_object('dispatched', dispatched);" in tail
    assert body.count("token") == dispatch.count("token") + body.split("-- the GitHub dispatch", 1)[0].count("token")
    assert "raise" not in dispatch and "notice" not in dispatch.lower()


def test_0012_add_drop_mirrors_the_cli_and_runs_as_the_caller():
    body = _function(DROPVIDEO_SQL, "add_drop")
    assert "add_drop(character_slug text, link text default null)" in body
    assert "security invoker" in body and "set search_path = ''" in body and "security definer" not in body
    assert "'owner-drop:' || new_id::text, 'drop', 'owner'" in body
    assert "jsonb_build_object('state', 'uploading', 'kind', 'file'" in body and "jsonb_build_object('state', 'checking', 'kind', 'link'" in body
    assert "'approved'" in body and "'by', 'owner'" in body and "'at', now()" in body
    assert "f.status in ('queued', 'made')" in body and "'duplicate', true" in body
    from studio import drop, favorites

    assert favorites.DROP_URL_PREFIX == "owner-drop:" and favorites.DROP_PLATFORM == "drop"
    assert set(drop.DROP_STATES) >= {"uploading", "checking", "waiting", "ready", "blocked", "making", "made", "failed"}


def test_0012_v_tracker_is_0011s_with_the_drop_card_appended():
    old, new = _view(DECISION_SQL, "v_tracker"), _view(DROPVIDEO_SQL, "v_tracker")
    assert new.startswith("create or replace view studio.v_tracker with (security_invoker = true) as")
    assert _select_list(new) == TRACKER_COLUMNS + ["decided_at", "drop_card", "make_requested_at"]
    whole_old = re.search(r"create or replace view studio\.v_tracker .*?interval '7 days', false\)\);", DECISION_SQL, re.S).group(0)
    whole_new = re.search(r"create or replace view studio\.v_tracker .*?interval '7 days', false\)\);", DROPVIDEO_SQL, re.S).group(0)
    appended = (
        ",\n  case when jsonb_typeof(f.proposal -> 'drop') = 'object' then (f.proposal -> 'drop') - 'deconstruct' - 'make' - 'job' end as drop_card,"
        "\n  f.proposal #>> '{make_requested,at}' as make_requested_at\n"
    )
    assert appended in whole_new and whole_new.replace(appended, "\n") == whole_old  # nothing else of 0011's view changed
    assert "grant select on studio.v_tracker to authenticated;" in DROPVIDEO_SQL


def test_0012_the_own_footage_toggle_is_the_owners_and_defaults_to_a_downloaded_clip():
    """Owner 2026-10-06: a drop is "own footage" (the owner's recording or footage used with permission) or a "downloaded clip"
    (the default); it is for reporting later and changes nothing about the generation."""
    body = _function(DROPVIDEO_SQL, "set_drop_footage")
    assert "set_drop_footage(pick_id uuid, own_footage boolean)" in body
    assert "security invoker" in body and "set search_path = ''" in body and "security definer" not in body
    assert "own_footage must be true or false" in body and "is not a dropped video" in body and "for update" in body
    assert "jsonb_set(fa.proposal, '{drop,own_footage}', to_jsonb(set_drop_footage.own_footage))" in body
    add = _function(DROPVIDEO_SQL, "add_drop")
    assert add.count("'own_footage', false") == 2  # a file and a link both start as a downloaded clip
    assert "own_footage" not in _function(DROPVIDEO_SQL, "request_job")  # the generation never reads it
    from studio import drop

    assert "own_footage" not in drop.swap_prompt.__code__.co_names


# ---- 0013: the character of a dropped video ------------------------------------------------------------------------------------

DROPCHAR_PATH = MIGRATIONS / "0013_drop_character.sql"
DROPCHAR_SQL = DROPCHAR_PATH.read_text()
DROPCHAR_CODE = re.sub(r"--[^\n]*", "", DROPCHAR_SQL)


def test_0013_is_add_drop_set_drop_character_and_their_grants_only():
    code = re.sub(r"create or replace function studio\.\w+\(.*?\n\$\$;", "", DROPCHAR_CODE, flags=re.S)
    code = re.sub(r"do \$\$.*?\n\$\$;", "", code, flags=re.S)
    statements = [s.strip() for s in code.split(";") if s.strip()]
    kinds = sorted(
        re.match(r"(grant execute on function studio\.\w+|revoke all on function studio\.\w+)", s).group(1) for s in statements
    )
    assert kinds == [
        "grant execute on function studio.add_drop", "grant execute on function studio.set_drop_character",
        "revoke all on function studio.add_drop", "revoke all on function studio.set_drop_character",
    ]  # fmt: skip
    assert re.findall(r"create or replace function studio\.(\w+)", DROPCHAR_CODE) == ["add_drop", "set_drop_character"]
    assert "create or replace view" not in DROPCHAR_CODE  # v_tracker's drop_card already carries recommended and character_by
    assert not re.search(r"\b(truncate|delete|alter|create table|drop function|drop view|drop table)\b", DROPCHAR_CODE, re.I)
    assert "revoke all on function studio.set_drop_character(uuid, text) from anon" in DROPCHAR_CODE
    assert "to anon" not in DROPCHAR_CODE
    # outside schema studio: only the owner rule (the Vault and pg_net stay inside request_job)
    outside = set(re.findall(r"\b(?:public|auth|storage|extensions|vault|net)\.[a-z_]+", DROPCHAR_CODE))
    assert outside == {"auth.jwt"}


def test_0013_add_drop_keeps_its_signature_and_takes_no_character_as_the_studios_choice():
    old, new = _function(DROPVIDEO_SQL, "add_drop"), _function(DROPCHAR_SQL, "add_drop")
    assert "add_drop(character_slug text default null, link text default null)" in new  # the same (text, text): replaced in place
    assert "security invoker" in new and "set search_path = ''" in new and "security definer" not in new
    # no character: a provisional one, never a paused one, a person's character first (the seeded swap rule, else two legs only)
    provisional = re.search(r"if slug_ is null then\n(.*?)\n    by_ := 'studio';", new, re.S).group(1)
    assert "where ch.status <> 'paused'" in provisional
    assert "(ch.setup #> '{swap,stars}') ? 'person'" in provisional
    assert "'biped' = any (ch.bodies) and not 'quadruped' = any (ch.bodies)" in provisional
    assert "order by" in provisional and "ch.slug\n     limit 1;" in provisional
    assert "every one is paused" in provisional
    # who chose is recorded on both kinds of drop; everything else of 0012's drop object is unchanged
    for kind in ("'state', 'uploading', 'kind', 'file'", "'state', 'checking', 'kind', 'link'"):
        assert f"jsonb_build_object({kind}, 'at', now(), 'reason', null, 'own_footage', false" in old
        assert re.search(rf"jsonb_build_object\({kind}, 'at', now\(\), 'reason', null, 'own_footage', false,\s+'character_by', by_\)", new)
    assert "by_ text := 'owner';" in new
    # a link without a character matches every pick of the URL; with one, that character's pick as before
    assert "where fa.url = clean and (by_ = 'studio' or fa.character_slug = slug_)" in new
    assert "f.status in ('queued', 'made')" in new and "'duplicate', true" in new
    for line in ("'owner-drop:' || new_id::text, 'drop', 'owner', slug_", "unknown character %", "not a canonical TikTok"):
        assert line in new, line
    # the canonical links are 0012's, character for character
    links = lambda body: re.search(r"plat := case\n.*?\n  end;", body, re.S).group(0)  # noqa: E731
    assert links(new) == links(old)
    for line in ("revoke all on function studio.add_drop(text, text) from public;", "grant execute on function studio.add_drop(text, text) to authenticated;"):
        assert line in DROPVIDEO_SQL and line in DROPCHAR_SQL


def test_0013_set_drop_character_is_a_definer_with_the_owner_check_first():
    body = _function(DROPCHAR_SQL, "set_drop_character")
    assert "set_drop_character(pick_id uuid, character_slug text)" in body and "returns jsonb" in body
    assert "security definer" in body and "set search_path = ''" in body and "security invoker" not in body
    owner = "if coalesce((select auth.jwt() ->> 'email'), '') <> 'o.schwend@gmail.com' then"
    assert owner in _function(DROPVIDEO_SQL, "request_job")  # the same rule as request_job, word for word
    assert body.index(owner) < body.index("select * into f") < body.index("update studio.favorites")  # checked before anything
    assert "insufficient_privilege" in body
    for name in re.findall(r"\b(from|update|into)\s+(\w+)\.", body):  # schema-qualified (the empty search_path finds nothing)
        assert name[1] in ("studio", "pg_catalog"), name


def test_0013_set_drop_character_refuses_a_paused_or_unknown_character_and_a_drop_past_make_it():
    body = _function(DROPCHAR_SQL, "set_drop_character")
    assert "not exists (select 1 from studio.characters ch where ch.slug = slug_)" in body and "unknown character %" in body
    assert "ch.status = 'paused'" in body and "is paused: he takes no new videos" in body
    assert "for update" in body and "is not a dropped video" in body
    assert "f.status in ('queued', 'made')" in body
    assert "state_ not in ('uploading', 'checking', 'waiting', 'ready', 'blocked', 'failed')" in body
    from studio import drop

    assert set(drop.DROP_STATES) - {"uploading", "checking", "waiting", "ready", "blocked", "failed"} == {"making", "made"}


def test_0013_set_drop_character_clears_the_old_characters_check_and_asks_for_it_again():
    body = _function(DROPCHAR_SQL, "set_drop_character")
    cleared = "(d - 'hooks' - 'hook' - 'part' - 'gadgets' - 'window' - 'seconds' - 'credits' - 'deconstruct' - 'adjust')"
    assert cleared in body and "jsonb_build_object('character_by', 'owner')" in body
    for kept in ("source_id", "star", "preview_path", "recommended", "own_footage", "job", "requested"):
        assert f"'{kept}'" not in body, kept  # what does not depend on the character stays (and the running job's lease)
    assert "set character_slug = slug_," in body
    assert "proposal = (fa.proposal - 'hook' - 'make_requested') || jsonb_build_object('drop', d)" in body  # Make it was his
    assert "jsonb_build_object('state', 'checking', 'reason', null, 'at', now())" in body
    # an upload without its file stays uploading (its own request_job starts the check); else request_job dispatches it
    assert "if state_ <> 'uploading' or coalesce(f.proposal ->> 'owner_clip_path', '') <> '' then" in body
    assert body.count("return studio.request_job(f.id, 'process');") == 1
    assert body.index("update studio.favorites fa\n     set character_slug") < body.index("return studio.request_job(f.id, 'process');")
    # the token is request_job's alone: no Vault, no pg_net, no dispatch here
    assert "vault" not in body and "net.http_post" not in body and "token" not in body
    # the same character again only records the owner's choice
    assert "if f.character_slug is not distinct from slug_ then" in body
    assert "jsonb_set(fa.proposal, '{drop,character_by}', to_jsonb('owner'::text))" in body
    assert "'dispatched', false" in body
    # request_job takes a drop at checking (the state set first): the reuse is valid
    assert "state_ not in ('uploading', 'checking', 'waiting', 'failed')" in _function(DROPVIDEO_SQL, "request_job")
    # the CLI's own words: who chose
    from studio import drop

    assert drop.CHARACTER_BY == ("owner", "studio")
