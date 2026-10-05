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


def test_migrations_are_additive_and_stay_inside_schema_studio():
    assert not re.search(r"\b(drop|truncate)\b", ALL_SQL, re.I)
    assert not re.search(r"\balter\s+column\b|\brename\b", ALL_SQL, re.I)
    # the only references outside schema studio: auth.jwt() for RLS, the Storage buckets
    outside = set(re.findall(r"\b(?:public|auth|storage|extensions)\.[a-z_]+", ALL_SQL))
    assert outside == {"auth.jwt", "storage.buckets"}
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
