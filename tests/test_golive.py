"""``studio golive check``: every non-MCP go-live prerequisite, with every outside call faked.

A ``World`` is a fully ready studio (all checks pass); each test breaks one thing and looks at the
single check that should flip. Nothing here touches the network, Keychain, GitHub or a database.
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import httpx
import pytest
from typer.testing import CliRunner

from studio import golive
from studio.cli import app
from studio.config import Settings

ROOT = Path(__file__).resolve().parents[1]

DSN = "postgresql://postgres.abc:s3cretDBpassw0rd@aws-0-eu-west-2.pooler.supabase.com:5432/postgres"
SB_URL = "https://abcdefgh.supabase.co"
SB_KEY = "sb-service-key-DO-NOT-LEAK-0123456789"
PZ_KEY = "postiz-key-DO-NOT-LEAK-9876543210"
SECRETS = (DSN, "s3cretDBpassw0rd", SB_KEY, PZ_KEY)

PROPOSED = {
    "permissions": {
        "allow": ["Bash(bin/studio:*)", "Edit(renders/**)"],
        "deny": ["mcp__hf__tiktok_prepare_publish", "mcp__vidiq__vidiq_instagram_publish_reel"],
    }
}


def cp(stdout: str = "", rc: int = 0, stderr: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess([], rc, stdout, stderr)


def refs(slug: str, *, closeup: str | None = "cu-1", bodies=("biped",), status="designing", masters=None) -> dict:
    return {
        "slug": slug,
        "name": slug.title(),
        "status": status,
        "bodies": list(bodies),
        "masters": masters if masters is not None else {b: f"{slug}-{b}-job" for b in bodies},
        "closeup": closeup,
        "accounts": [
            {"platform": "tiktok", "handle": None, "postiz_integration_id": None},
            {"platform": "instagram", "handle": None, "postiz_integration_id": None},
        ],
    }


def probe_rows(skip: set[tuple[str, str]] = frozenset()) -> list[tuple[str, str]]:
    """Every object the migrations create, as the probe query would return them."""
    return [m for marks in golive.MIGRATION_MARKERS.values() for m in marks if m not in skip]


@dataclass
class World:
    """The fakes behind one ``golive.Env``. Mutate the fields, then ``run()``."""

    root: Path
    keychain_items: set[str] = field(default_factory=lambda: {item for _, item in golive.SECRETS})
    probe: list[tuple[str, str]] = field(default_factory=probe_rows)
    people: list[tuple] = field(
        default_factory=lambda: [
            ("franz", "live", "instagram", "ig-int-1"),
            ("franz", "live", "tiktok", "tt-int-1"),
            ("reginald", "live", "instagram", "ig-int-2"),
            ("reginald", "live", "tiktok", "tt-int-2"),
        ]
    )
    db_error: Exception | None = None
    vault: list[tuple] | Exception = field(default_factory=lambda: [(1,)])
    http_reply: tuple[int, str] | Exception = (200, "[]")
    gh_secrets: list[str] = field(default_factory=lambda: [name for name, _ in (*golive.SECRETS, *golive.DROP_SECRETS)])
    gh_workflows: list[dict] = field(
        default_factory=lambda: [
            {"name": n, "path": f".github/workflows/{n}.yml", "state": "active"}
            for n in ("ci", "publish", "metrics", "health", "studio-drop")
        ]
    )
    gh_result: subprocess.CompletedProcess[str] | Exception | None = None  # overrides both gh calls
    tracked: list[str] = field(default_factory=lambda: ["README.md", "studio/cli.py", "characters/franz/refs.json"])
    git_result: subprocess.CompletedProcess[str] | Exception | None = None
    postiz_installed: bool = True
    postiz_status: subprocess.CompletedProcess[str] = field(default_factory=cp)
    settings: Settings = field(
        default_factory=lambda: Settings(
            database_url=DSN, supabase_url=SB_URL, supabase_service_key=SB_KEY, postiz_api_key=PZ_KEY
        )
    )
    calls: list[list[str]] = field(default_factory=list)
    http_calls: list[tuple[str, dict[str, str]]] = field(default_factory=list)

    def env(self) -> golive.Env:
        return golive.Env(
            root=self.root,
            settings=self.settings,
            run=self._run,
            http=self._http,
            keychain=lambda item: item in self.keychain_items,
            db=self._db,
            which=lambda name: f"/usr/local/bin/{name}" if name != "postiz" or self.postiz_installed else None,
        )

    def run(self) -> dict[str, golive.Check]:
        return {c.id: c for c in golive.run_checks(self.env())}

    def _run(self, args):
        args = list(args)
        self.calls.append(args)
        head = args[:3]
        if head[:2] == ["gh", "secret"] or head[:2] == ["gh", "workflow"]:
            if isinstance(self.gh_result, Exception):
                raise self.gh_result
            if self.gh_result is not None:
                return self.gh_result
            if head[1] == "secret":
                return cp(json.dumps([{"name": n} for n in self.gh_secrets]))
            return cp(json.dumps(self.gh_workflows))
        if head[:2] == ["git", "ls-files"]:
            if isinstance(self.git_result, Exception):
                raise self.git_result
            return self.git_result or cp("".join(f + "\0" for f in self.tracked))
        if head[:2] == ["postiz", "auth:status"] or head[:1] == ["postiz"]:
            return self.postiz_status
        raise AssertionError(f"unexpected command {args}")

    def _http(self, url, headers):
        self.http_calls.append((url, dict(headers)))
        if isinstance(self.http_reply, Exception):
            raise self.http_reply
        return self.http_reply

    def _db(self, dsn, sql):
        assert dsn == self.settings.database_url
        if self.db_error:
            raise self.db_error
        if sql == golive.PROBE_SQL:
            return list(self.probe)
        if sql == golive.CHARACTERS_SQL:
            return list(self.people)
        if sql == golive.VAULT_SQL:
            if isinstance(self.vault, Exception):
                raise self.vault
            return list(self.vault)
        raise AssertionError(f"unexpected query {sql!r}")


@pytest.fixture
def world(tmp_path) -> World:
    chars = tmp_path / "characters"
    for slug, data in {
        "franz": refs("franz", bodies=("biped", "quadruped")),
        "reginald": refs("reginald"),
    }.items():
        (chars / slug).mkdir(parents=True)
        (chars / slug / "refs.json").write_text(json.dumps(data))
    claude = tmp_path / ".claude"
    claude.mkdir()
    (claude / "settings.json.proposed").write_text(json.dumps(PROPOSED))
    (claude / "settings.json").write_text(json.dumps(PROPOSED))
    migrations = tmp_path / "supabase" / "migrations"
    migrations.mkdir(parents=True)
    for n, name in (("0001", "studio"), ("0002", "snapshot_kpis"), ("0003", "accounts_unique"), ("0004", "terminal_rpc")):
        (migrations / f"{n}_{name}.sql").write_text("-- fake")
    return World(root=tmp_path)


def failing(checks: dict[str, golive.Check]) -> set[str]:
    return {k for k, c in checks.items() if c.status == "fail"}


def write_refs(world: World, slug: str, data: dict) -> None:
    (world.root / "characters" / slug / "refs.json").write_text(json.dumps(data))


def write_settings(world: World, data: dict) -> None:
    (world.root / ".claude" / "settings.json").write_text(json.dumps(data))


# ---- the whole thing -------------------------------------------------------------------------------


def test_a_ready_studio_passes_every_check(world):
    checks = world.run()
    assert failing(checks) == set()
    assert all(c.status == "pass" for c in checks.values()), {k: c.status for k, c in checks.items()}
    assert len(checks) >= 20  # the checklist is itemised, not one lump


def test_every_failed_check_has_a_one_line_fix_and_every_id_is_unique(world, tmp_path):
    world.keychain_items = set()
    world.db_error = RuntimeError("down")
    world.http_reply = (500, "boom")
    world.gh_result = cp("", 1, "gh: not logged in")
    world.postiz_status = cp("", 1, "nope")
    world.tracked = [".env"]
    (world.root / ".claude" / "settings.json").unlink()
    ids = [c.id for c in golive.run_checks(world.env())]
    assert len(ids) == len(set(ids))
    checks = world.run()
    bad = [c for c in checks.values() if c.status == "fail"]
    assert len(bad) >= 10
    for c in bad:
        assert c.fix and "\n" not in c.fix, c.id


# ---- (a) Keychain ----------------------------------------------------------------------------------


def test_keychain_reports_each_item_present(world):
    checks = world.run()
    for _, item in golive.SECRETS:
        assert checks[f"keychain:{item}"].status == "pass"


def test_a_missing_keychain_item_fails_with_the_command_to_store_it(world):
    world.keychain_items.discard("cs-postiz-api-key")
    checks = world.run()
    assert failing(checks) == {"keychain:cs-postiz-api-key"}
    assert 'security add-generic-password -s cs-postiz-api-key -a "$USER" -w' in checks["keychain:cs-postiz-api-key"].fix


def test_the_real_keychain_probe_asks_only_whether_the_item_exists():
    seen = []

    def run(args):
        seen.append(list(args))
        return cp("keychain: ...attributes only...", 0)

    assert golive.keychain_probe(run)("cs-database-url") is True
    assert seen == [["security", "find-generic-password", "-s", "cs-database-url"]]  # no -w, no -g: never reads the secret
    assert golive.keychain_probe(lambda a: cp("", 44, "not found"))("cs-database-url") is False

    def broken(args):
        raise FileNotFoundError("security")

    assert golive.keychain_probe(broken)("cs-database-url") is False


# ---- (b) database ----------------------------------------------------------------------------------


def test_database_and_schema_pass_when_everything_is_applied(world):
    checks = world.run()
    assert checks["database"].status == "pass"
    assert checks["schema"].status == "pass"
    assert "0001" in checks["schema"].title and "0016" in checks["schema"].title


def test_no_database_url_fails_both_and_points_at_the_keychain(world):
    world.settings = world.settings.model_copy(update={"database_url": None})
    checks = world.run()
    assert {"database", "schema"} <= failing(checks)
    assert "cs-database-url" in checks["database"].fix and "bin/studio" in checks["database"].fix


def test_an_unreachable_database_fails_without_echoing_the_password(world):
    world.db_error = RuntimeError(f"connection failed: could not parse {DSN}")
    checks = world.run()
    assert {"database", "schema"} <= failing(checks)
    text = " ".join(f"{c.detail} {c.fix}" for c in checks.values())
    for secret in SECRETS:
        assert secret not in text
    assert "***" in checks["database"].detail


def test_a_missing_table_fails_the_schema_check_naming_it(world):
    world.probe = probe_rows({("table", "favorites")})
    checks = world.run()
    assert failing(checks) == {"schema"}
    assert "favorites" in checks["schema"].detail and "0001" in checks["schema"].detail
    assert "0001_studio.sql" in checks["schema"].fix


@pytest.mark.parametrize(
    "missing, migration",
    [
        (("column", "skip_rate"), "0002"),
        (("column", "watched_pct"), "0002"),
        (("index", "accounts_character_platform_key"), "0003"),
        (("function", "approve_clip"), "0004"),
        (("view", "v_health"), "0004"),
        (("function", "queue_block_reason"), "0005"),
        (("function", "free_slot"), "0006"),
        (("index", "reviews_week_character_slug_key"), "0006"),
        (("view", "v_characters"), "0007"),
        (("column", "setup"), "0007"),
        (("column", "details"), "0007"),
        (("column", "has_minors"), "0008"),
        (("function", "attach_clip"), "0008"),
        (("column", "analysis"), "0009"),
        (("view", "v_tracker"), "0010"),
        (("column", "source_candidates"), "0010"),
        (("column", "first_comment"), "0010"),
        (("column", "decided_at"), "0011"),
        (("function", "request_job"), "0012"),
        (("function", "add_drop"), "0012"),
        (("function", "set_drop_footage"), "0012"),
        (("column", "make_requested_at"), "0012"),
        (("function", "set_drop_character"), "0013"),
        (("table", "timer_state"), "0014"),
        (("function", "dispatch_publish"), "0014"),
        (("function", "publish_tick"), "0014"),
        (("function", "copy_drop"), "0015"),
        (("function", "family_days"), "0015"),
        (("view", "v_views_daily"), "0015"),
        (("table", "hits"), "0016"),
        (("table", "hits_spend"), "0016"),
        (("view", "v_hits"), "0016"),
        (("function", "set_hit_status"), "0016"),
        (("function", "set_drop_keep"), "0016"),
    ],
)
def test_each_migration_is_detected_by_its_own_objects(world, missing, migration):
    world.probe = probe_rows({missing})
    checks = world.run()
    assert failing(checks) == {"schema"}
    assert migration in checks["schema"].detail
    assert f"{migration}_" in checks["schema"].fix


def test_an_empty_schema_lists_all_four_migrations(world):
    world.probe = []
    schema = world.run()["schema"]
    assert schema.status == "fail"
    for n in ("0001", "0002", "0003", "0004"):
        assert n in schema.detail


def test_the_markers_cover_exactly_what_the_migration_files_create():
    """Drift guard: a new migration or object must get a marker, or the go-live check goes blind."""
    files = {p.name[:4]: p.read_text() for p in sorted((ROOT / "supabase" / "migrations").glob("*.sql"))}
    assert set(files) == set(golive.MIGRATION_MARKERS), "a migration has no go-live markers (or the reverse)"
    for n, marks in golive.MIGRATION_MARKERS.items():
        text = files[n]
        created: set[tuple[str, str]] = set()
        for m in re.finditer(r"create table (?:if not exists )?studio\.(\w+)", text):
            created.add(("table", m.group(1)))
        for m in re.finditer(r"create (?:or replace )?view studio\.(\w+)", text):
            created.add(("view", m.group(1)))
        for m in re.finditer(r"create or replace function studio\.(\w+)", text):
            created.add(("function", m.group(1)))
        for m in re.finditer(r"create (?:unique )?index (?:if not exists )?(\w+)", text):
            created.add(("index", m.group(1)))
        for m in re.finditer(r"alter table studio\.(?:snapshots|characters|runs|sources) add column if not exists (\w+)", text):
            created.add(("column", m.group(1)))
        if n >= "0009":
            # a migration that appends columns to views of an earlier one: the last column it appends is its marker (the probe
            # reads it from the view's own columns). "Appended" = not in the same view of any earlier migration; a view that is
            # new in this migration is its own marker.
            for m in re.finditer(r"create or replace view studio\.(\w+) .*?from studio\.favorites f", text, re.S):
                columns = lambda t: re.findall(r"\bas (\w+),?\s*$", t, re.M)  # noqa: E731
                before = [
                    o
                    for k, other in files.items()
                    if k < n
                    for o in re.finditer(rf"create or replace view studio\.{m.group(1)} .*?from studio\.favorites f", other, re.S)
                ]
                earlier = {c for o in before for c in columns(o.group(0))}
                appended = [c for c in columns(m.group(0)) if c not in earlier]
                if before and appended:
                    created.add(("column", appended[-1]))
        if n == "0001":  # the first migration's snapshot columns are not markers; its tables are
            created = {c for c in created if c[0] == "table"}
            marks = {m for m in marks if m[0] == "table"}
        assert created >= set(marks), f"{n}: marker not created by the file: {set(marks) - created}"
        if n != "0001":
            assert set(marks) >= created, f"{n}: object without a marker: {created - set(marks)}"


# ---- (c) Data API ----------------------------------------------------------------------------------


def test_the_data_api_check_asks_for_schema_studio_with_the_service_key(world):
    checks = world.run()
    assert checks["dataapi"].status == "pass"
    (url, headers), = world.http_calls
    assert url == f"{SB_URL}/rest/v1/settings?select=id"
    assert headers["Accept-Profile"] == "studio"
    assert headers["apikey"] == SB_KEY and headers["Authorization"] == f"Bearer {SB_KEY}"


def test_a_trailing_slash_on_the_supabase_url_is_harmless(world):
    world.settings = world.settings.model_copy(update={"supabase_url": SB_URL + "/"})
    world.run()
    assert world.http_calls[0][0] == f"{SB_URL}/rest/v1/settings?select=id"


def test_schema_not_exposed_is_named_with_the_dashboard_path(world):
    world.http_reply = (
        406,
        '{"code":"PGRST106","message":"The schema must be one of the following: public, graphql_public"}',
    )
    c = world.run()["dataapi"]
    assert c.status == "fail"
    assert "not exposed" in c.detail
    assert "Exposed schemas" in c.fix and "studio" in c.fix


def test_a_rejected_key_and_other_http_errors_fail(world):
    world.http_reply = (401, '{"message":"Invalid API key"}')
    c = world.run()["dataapi"]
    assert c.status == "fail" and "401" in c.detail and "cs-supabase-service-key" in c.fix
    world.http_reply = (503, "upstream down")
    c = world.run()["dataapi"]
    assert c.status == "fail" and "503" in c.detail


def test_exposed_schema_without_a_service_role_grant_passes(world):
    """403 / 42501 comes from the role check, which PostgREST runs only after the schema was found."""
    world.http_reply = (403, '{"code":"42501","message":"permission denied for schema studio"}')
    c = world.run()["dataapi"]
    assert c.status == "pass"
    assert "schema exposed" in c.detail and "authenticated" in c.detail
    world.http_reply = (403, "permission denied for schema studio")  # no JSON code, same meaning
    assert world.run()["dataapi"].status == "pass"


def test_only_a_401_blames_the_key_and_another_403_does_not(world):
    world.http_reply = (401, '{"message":"Invalid API key"}')
    c = world.run()["dataapi"]
    assert c.status == "fail" and "rejected" in c.detail and "cs-supabase-service-key" in c.fix
    world.http_reply = (403, '{"message":"Forbidden by a network restriction"}')
    c = world.run()["dataapi"]
    assert c.status == "fail" and "403" in c.detail
    assert "rejected" not in c.detail and "cs-supabase-service-key" not in c.fix


def test_not_exposed_wins_over_a_status_that_looks_like_auth(world):
    world.http_reply = (403, '{"code":"PGRST106","message":"The schema must be one of the following: public"}')
    c = world.run()["dataapi"]
    assert c.status == "fail" and "not exposed" in c.detail


def test_a_network_error_fails_and_is_scrubbed(world):
    world.http_reply = httpx.ConnectError(f"cannot reach {SB_URL} with {SB_KEY}")
    c = world.run()["dataapi"]
    assert c.status == "fail"
    assert SB_KEY not in c.detail + c.fix


@pytest.mark.parametrize("field_name", ["supabase_url", "supabase_service_key"])
def test_missing_supabase_settings_fail_without_a_request(world, field_name):
    world.settings = world.settings.model_copy(update={field_name: None})
    c = world.run()["dataapi"]
    assert c.status == "fail" and world.http_calls == []
    assert "cs-supabase" in c.fix


# ---- (d) characters --------------------------------------------------------------------------------


def test_characters_pass_when_live_with_masters_closeup_and_postiz_ids(world):
    checks = world.run()
    assert checks["characters:live"].status == "pass"
    assert "franz" in checks["characters:live"].detail
    assert checks["characters:franz"].status == "pass"
    assert checks["characters:reginald"].status == "pass"
    assert checks["characters:refs"].status == "pass"


def test_no_live_character_fails_and_says_how_to_flip_one(world):
    world.people = [(s, "designing", p, i) for s, _, p, i in world.people]
    c = world.run()["characters:live"]
    assert c.status == "fail"
    assert "none" in c.detail and "designing" in c.detail
    assert "refs.json" in c.fix and "bin/studio seed" in c.fix


def test_one_live_character_is_enough_for_the_live_check(world):
    world.people = [(s, "live" if s == "franz" else "designing", p, i) for s, _, p, i in world.people]
    assert world.run()["characters:live"].status == "pass"


def test_characters_not_in_the_database_yet_say_to_seed(world):
    world.people = []
    checks = world.run()
    assert checks["characters:live"].status == "fail"
    assert "seed" in checks["characters:live"].fix
    assert checks["characters:franz"].status == "fail" and "seed" in checks["characters:franz"].fix


def test_a_character_without_a_closeup_fails_naming_it(world):
    write_refs(world, "reginald", refs("reginald", closeup=None))
    checks = world.run()
    assert failing(checks) == {"characters:reginald"}
    assert "close-up" in checks["characters:reginald"].detail
    assert "characters/reginald/refs.json" in checks["characters:reginald"].fix


def test_a_character_without_a_master_fails_in_the_refs_check(world):
    write_refs(world, "franz", refs("franz", bodies=("biped", "quadruped"), masters={"biped": "x", "quadruped": None}))
    checks = world.run()
    assert "characters:refs" in failing(checks)
    assert "quadruped" in checks["characters:refs"].detail
    assert "refs.json" in checks["characters:refs"].fix


def test_a_character_with_no_postiz_integration_id_fails(world):
    world.people = [(s, st, p, None if s == "reginald" else i) for s, st, p, i in world.people]
    c = world.run()["characters:reginald"]
    assert c.status == "fail"
    assert "postiz_integration_id" in c.detail
    assert "Postiz" in c.fix and "bin/studio seed" in c.fix


def test_one_connected_account_is_enough(world):
    world.people = [(s, st, p, None if (s, p) == ("reginald", "instagram") else i) for s, st, p, i in world.people]
    assert world.run()["characters:reginald"].status == "pass"


def test_a_character_with_no_account_rows_fails(world):
    world.people = [p for p in world.people if p[0] != "reginald"] + [("reginald", "live", None, None)]
    assert world.run()["characters:reginald"].status == "fail"


def test_a_paused_character_is_left_out_of_the_readiness_rows(world):
    write_refs(world, "reginald", refs("reginald", closeup=None, status="paused"))
    checks = world.run()
    assert "characters:reginald" not in checks
    assert failing(checks) == set()


def test_invalid_refs_json_fails_one_row_and_no_character_rows(world):
    (world.root / "characters" / "franz" / "refs.json").write_text("{not json")
    checks = world.run()
    assert "characters:refs" in failing(checks)
    assert not any(k.startswith("characters:") and k not in {"characters:refs", "characters:live"} for k in checks)


def test_a_database_failure_still_checks_masters_and_closeup(world):
    world.db_error = RuntimeError("down")
    write_refs(world, "reginald", refs("reginald", closeup=None))
    checks = world.run()
    assert checks["characters:live"].status == "fail" and "not reachable" in checks["characters:live"].detail
    assert "close-up" in checks["characters:reginald"].detail
    assert "not reachable" in checks["characters:franz"].detail


# ---- (e) GitHub ------------------------------------------------------------------------------------


def test_github_secrets_and_workflows_pass_when_present_and_enabled(world):
    checks = world.run()
    for name, _ in golive.SECRETS:
        assert checks[f"github:{name}"].status == "pass"
    for wf in ("publish", "metrics", "health"):
        assert checks[f"github:workflow:{wf}"].status == "pass"
    assert ["gh", "secret", "list", "--json", "name"] in world.calls
    assert ["gh", "workflow", "list", "--all", "--json", "name,state,path"] in world.calls


def test_a_missing_github_secret_fails_with_the_set_command(world):
    world.gh_secrets.remove("POSTIZ_API_KEY")
    checks = world.run()
    assert failing(checks) == {"github:POSTIZ_API_KEY"}
    fix = checks["github:POSTIZ_API_KEY"].fix
    assert "gh secret set POSTIZ_API_KEY" in fix and "cs-postiz-api-key" in fix
    assert "-w" in fix and "|" in fix  # piped from the Keychain, never typed or echoed


def test_a_disabled_workflow_fails_with_the_enable_command(world):
    for wf in world.gh_workflows:
        if wf["name"] == "publish":
            wf["state"] = "disabled_manually"
    checks = world.run()
    assert failing(checks) == {"github:workflow:publish"}
    assert "disabled_manually" in checks["github:workflow:publish"].detail
    assert "gh workflow enable publish.yml" in checks["github:workflow:publish"].fix


def test_a_workflow_missing_from_the_repo_fails(world):
    world.gh_workflows = [w for w in world.gh_workflows if w["name"] != "health"]
    c = world.run()["github:workflow:health"]
    assert c.status == "fail" and "not found" in c.detail


def test_workflows_are_matched_by_file_name_as_well_as_title(world):
    world.gh_workflows = [
        {"name": "Publish due posts", "path": ".github/workflows/publish.yml", "state": "active"},
        {"name": "metrics", "path": ".github/workflows/metrics.yml", "state": "active"},
        {"name": "health", "path": ".github/workflows/health.yml", "state": "active"},
    ]
    assert world.run()["github:workflow:publish"].status == "pass"


def test_gh_failing_gives_one_row_per_call_not_a_pile(world):
    world.gh_result = cp("", 4, "To get started with GitHub CLI, please run:  gh auth login")
    checks = world.run()
    gh = {k for k in checks if k.startswith("github:")}
    assert gh == {"github:secrets", "github:workflows"}
    assert failing(checks) == gh
    assert "gh auth login" in checks["github:secrets"].detail and "gh auth login" in checks["github:secrets"].fix


def test_gh_not_installed_fails_cleanly(world):
    world.gh_result = FileNotFoundError("gh")
    checks = world.run()
    assert failing(checks) == {"github:secrets", "github:workflows"}
    assert "not installed" in checks["github:secrets"].detail


def test_gh_garbage_output_fails_cleanly(world):
    world.gh_result = cp("this is not json")
    assert failing(world.run()) == {"github:secrets", "github:workflows"}


# ---- (f) postiz CLI --------------------------------------------------------------------------------


def test_postiz_cli_authenticated_passes(world):
    c = world.run()["postiz"]
    assert c.status == "pass"
    assert ["postiz", "auth:status"] in world.calls


def test_postiz_not_installed_is_skipped_not_failed(world):
    world.postiz_installed = False
    checks = world.run()
    assert checks["postiz"].status == "skip"
    assert "npm i -g postiz" in checks["postiz"].fix
    assert failing(checks) == set()
    assert ["postiz", "auth:status"] not in world.calls


def test_postiz_auth_failure_fails(world):
    world.postiz_status = cp("", 1, "Unauthorized")
    c = world.run()["postiz"]
    assert c.status == "fail" and "Unauthorized" in c.detail and "cs-postiz-api-key" in c.fix


def test_postiz_without_an_api_key_fails_without_calling_it(world):
    world.settings = world.settings.model_copy(update={"postiz_api_key": None})
    c = world.run()["postiz"]
    assert c.status == "fail" and "POSTIZ_API_KEY" in c.detail
    assert ["postiz", "auth:status"] not in world.calls


# ---- (g) .claude/settings.json ---------------------------------------------------------------------


def test_permissions_pass_when_the_proposal_was_applied_even_with_extra_rules(world):
    extra = json.loads(json.dumps(PROPOSED))
    extra["permissions"]["deny"].append("Bash(rm -rf:*)")
    extra["permissions"]["allow"].append("Bash(ls:*)")
    write_settings(world, extra)
    assert world.run()["permissions"].status == "pass"


def test_a_missing_deny_rule_fails_naming_it_and_giving_the_cp_command(world):
    write_settings(world, {"permissions": {"allow": PROPOSED["permissions"]["allow"], "deny": ["mcp__hf__tiktok_prepare_publish"]}})
    c = world.run()["permissions"]
    assert c.status == "fail"
    assert "mcp__vidiq__vidiq_instagram_publish_reel" in c.detail
    assert "cp .claude/settings.json.proposed .claude/settings.json" in c.fix


def test_settings_with_allow_rules_but_no_deny_rules_fail_naming_every_deny_rule(world):
    """The shape the repo ships before the owner applies the proposal."""
    write_settings(world, {"permissions": {"allow": PROPOSED["permissions"]["allow"]}})
    c = world.run()["permissions"]
    assert c.status == "fail"
    for rule in PROPOSED["permissions"]["deny"]:
        assert rule in c.detail


@pytest.mark.parametrize("which", ["settings.json", "settings.json.proposed"])
def test_a_missing_settings_file_fails(world, which):
    (world.root / ".claude" / which).unlink()
    c = world.run()["permissions"]
    assert c.status == "fail" and which in c.detail


def test_settings_without_permissions_fail_listing_the_missing_rules(world):
    write_settings(world, {})
    c = world.run()["permissions"]
    assert c.status == "fail" and PROPOSED["permissions"]["deny"][0] in c.detail


@pytest.mark.parametrize("bad", [{"permissions": ["deny"]}, {"permissions": {"deny": "x"}}, ["not", "an", "object"]])
def test_a_settings_file_of_the_wrong_shape_fails_with_a_clear_message(world, bad):
    write_settings(world, bad)
    c = world.run()["permissions"]  # no AttributeError
    assert c.status == "fail"
    assert "settings.json" in c.detail and ("not an object" in c.detail or "not a list" in c.detail)


@pytest.mark.parametrize("proposal", [{"permissions": {"deny": []}}, {"permissions": {"allow": ["Bash(ls:*)"]}}, {}])
def test_a_proposal_with_no_deny_rules_fails_instead_of_passing_vacuously(world, proposal):
    (world.root / ".claude" / "settings.json.proposed").write_text(json.dumps(proposal))
    c = world.run()["permissions"]
    assert c.status == "fail"
    assert "no deny rules" in c.detail and "git checkout -- .claude/settings.json.proposed" in c.fix


@pytest.mark.parametrize(
    "rule",
    [
        "mcp__53354c6e-fbc1-47dd-ac53-ad2126ec66bd",  # a whole server, bare
        "mcp__53354c6e-fbc1-47dd-ac53-ad2126ec66bd__*",  # a whole server, wildcard
        "mcp__hf__*",
        "mcp__hf__generate_*",  # a partial wildcard is still not an explicit allowlist
        "mcp__plugin_claude-mem_mcp-search",
    ],
)
def test_a_blanket_mcp_server_allow_fails_the_permissions_check(world, rule):
    """An allowlist must name each tool: a whole-server allow lets every future tool of it run unattended."""
    write_settings(world, {"permissions": {**PROPOSED["permissions"],
                                           "allow": [*PROPOSED["permissions"]["allow"], rule]}})  # fmt: skip
    c = world.run()["permissions"]
    assert c.status == "fail" and rule in c.detail and "explicit" in c.detail
    assert "cp .claude/settings.json.proposed .claude/settings.json" in c.fix


@pytest.mark.parametrize("rule", ["Bash(uv run:*)", "Bash(uv run *)", "Bash(uv:*)"])
def test_a_blanket_uv_run_allow_fails_the_permissions_check(world, rule):
    write_settings(world, {"permissions": {**PROPOSED["permissions"],
                                           "allow": [*PROPOSED["permissions"]["allow"], rule]}})  # fmt: skip
    c = world.run()["permissions"]
    assert c.status == "fail" and rule in c.detail


def test_explicit_mcp_tool_allows_pass(world):
    allow = [
        *PROPOSED["permissions"]["allow"],
        "mcp__53354c6e-fbc1-47dd-ac53-ad2126ec66bd__generate_video",
        "mcp__5d0eb7b3-1f89-4c02-b145-8199ffc4ed25__vidiq_balance",
        "Bash(uv run --version)",  # a fixed command is not a blanket
    ]
    write_settings(world, {"permissions": {**PROPOSED["permissions"], "allow": allow}})
    assert world.run()["permissions"].status == "pass"


def test_a_blanket_allow_in_the_proposal_itself_fails_too(world):
    """The shipped proposal must not ask for it either: the fix is to restore the proposal, not to cp it."""
    bad = {"permissions": {**PROPOSED["permissions"], "allow": [*PROPOSED["permissions"]["allow"], "mcp__hf"]}}
    (world.root / ".claude" / "settings.json.proposed").write_text(json.dumps(bad))
    write_settings(world, bad)
    c = world.run()["permissions"]
    assert c.status == "fail" and "mcp__hf" in c.detail and "proposal" in c.detail
    assert "git checkout -- .claude/settings.json.proposed" in c.fix


def test_the_shipped_proposal_is_an_explicit_allowlist_with_the_backstop_denies():
    """The real file, read as the check reads it: no blanket allow, every tool of the skills named, denies kept."""
    data = json.loads((ROOT / ".claude" / "settings.json.proposed").read_text())
    allow, deny = data["permissions"]["allow"], data["permissions"]["deny"]
    assert golive._too_broad(allow) == []
    hf, vidiq = "mcp__53354c6e-fbc1-47dd-ac53-ad2126ec66bd__", "mcp__5d0eb7b3-1f89-4c02-b145-8199ffc4ed25__"
    for tool in ("generate_video", "generate_video_batch", "generate_image", "generate_image_batch", "jobs_wait",
                 "media_import_url", "get_presets", "show_generations", "show_generation_by_ids", "transactions",
                 "balance", "models_explore"):  # fmt: skip
        assert hf + tool in allow, tool
    for tool in ("vidiq_balance", "vidiq_instagram_tiktok_outlier_search", "vidiq_watch_shortform_content",
                 "vidiq_job_poll", "vidiq_instagram_connected_accounts", "vidiq_instagram_owner_insights"):  # fmt: skip
        assert vidiq + tool in allow, tool
    for gone in ("Bash(uv run:*)", "Bash(ffmpeg:*)", "Bash(ffprobe:*)"):
        assert gone not in allow
    for rule in (hf + "tiktok_prepare_publish", hf + "execute_preset", hf + "deploy_website", hf + "publish_website",
                 vidiq + "vidiq_instagram_publish_reel", vidiq + "vidiq_video_upload", vidiq + "vidiq_update_video",
                 vidiq + "vidiq_update_video_thumbnail"):  # fmt: skip
        assert rule in deny, rule  # the 8 original denies stay as the backstop
    assert not (set(allow) & set(deny))  # nothing is both allowed and denied


def test_unreadable_settings_json_fails(world):
    (world.root / ".claude" / "settings.json").write_text("{nope")
    c = world.run()["permissions"]
    assert c.status == "fail" and "settings.json" in c.detail


# ---- (h) tracked secret files ----------------------------------------------------------------------


def test_clean_tree_passes(world):
    c = world.run()["repo:secrets"]
    assert c.status == "pass"
    assert ["git", "ls-files", "-z"] in world.calls


@pytest.mark.parametrize(
    "path",
    [
        ".env",
        "terminal/.env.local",
        "terminal/.env.production",
        "marketing/POSTING.env",
        "keys/server.pem",
        "deploy/private.key",
        "certs/bundle.p12",
        "home/.ssh/id_rsa",
        "config/secrets.json",
        "config/credentials.yml",
        "gcp/service-account-prod.json",
        ".netrc",
    ],
)
def test_a_tracked_secret_file_fails_and_is_named(world, path):
    world.tracked.append(path)
    c = world.run()["repo:secrets"]
    assert c.status == "fail" and path in c.detail
    assert "git rm --cached" in c.fix


@pytest.mark.parametrize(
    "path",
    ["terminal/.env.example", ".env.sample", "docs/secrets.md", "docs/keys-to-the-kingdom.md", "id_rsa.pub", "studio/environment.py"],
)
def test_examples_docs_and_public_keys_are_not_secret_files(world, path):
    world.tracked.append(path)
    assert world.run()["repo:secrets"].status == "pass"


def test_git_failing_fails_the_check(world):
    world.git_result = cp("", 128, "fatal: not a git repository")
    c = world.run()["repo:secrets"]
    assert c.status == "fail" and "not a git repository" in c.detail
    world.git_result = FileNotFoundError("git")
    assert world.run()["repo:secrets"].status == "fail"


def test_the_real_runner_is_bound_to_the_repo_root(world, monkeypatch):
    """gh and git must look at the repo, never at the caller's working directory."""
    seen = {}

    def fake_run(args, **kwargs):
        seen.update(kwargs, args=list(args))
        return cp("ok")

    monkeypatch.setattr(golive.subprocess, "run", fake_run)
    assert golive.shell_runner(world.root)(["git", "ls-files", "-z"]).stdout == "ok"
    assert seen["cwd"] == world.root and seen["text"] is True and seen["timeout"] > 0
    assert seen["capture_output"] is True and seen["stdin"] == subprocess.DEVNULL


# ---- the real HTTP adapter (httpx mock transport, no network) --------------------------------------


def test_http_adapter_returns_status_and_body_and_never_follows_redirects():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["accept-profile"] == "studio"
        return httpx.Response(406, text='{"code":"PGRST106"}')

    status, body = golive.http_get("https://x.supabase.co/rest/v1/settings?select=id", {"Accept-Profile": "studio"}, transport=httpx.MockTransport(handler))
    assert (status, body) == (406, '{"code":"PGRST106"}')


# ---- the CLI ---------------------------------------------------------------------------------------


def invoke(world: World, monkeypatch, *args: str):
    monkeypatch.setattr(golive, "build_env", lambda root=None: world.env())
    return CliRunner().invoke(app, ["golive", *args])


def test_golive_is_a_registered_group_with_a_check_command():
    r = CliRunner().invoke(app, ["golive", "--help"])
    assert r.exit_code == 0 and "check" in r.output


def test_cli_prints_ticks_and_exits_0_when_everything_passes(world, monkeypatch):
    r = invoke(world, monkeypatch, "check")
    assert r.exit_code == 0, r.output
    assert "✅" in r.output and "❌" not in r.output
    assert "keychain: cs-database-url" in r.output
    assert "ready" in r.output.lower()


def test_cli_prints_a_cross_and_a_fix_line_and_exits_1_on_any_failure(world, monkeypatch):
    world.keychain_items.discard("cs-supabase-service-key")
    r = invoke(world, monkeypatch, "check")
    assert r.exit_code == 1
    assert "❌ keychain: cs-supabase-service-key" in r.output
    assert 'fix: security add-generic-password -s cs-supabase-service-key -a "$USER" -w' in r.output
    assert "1 to fix" in r.output


def test_cli_a_skipped_check_does_not_fail_the_run(world, monkeypatch):
    world.postiz_installed = False
    r = invoke(world, monkeypatch, "check")
    assert r.exit_code == 0
    assert "➖ postiz" in r.output and "1 skipped" in r.output


def test_cli_never_prints_a_secret_value_even_when_errors_carry_them(world, monkeypatch):
    world.db_error = RuntimeError(f"bad dsn {DSN}")
    world.http_reply = httpx.ConnectError(f"{SB_URL} {SB_KEY}")
    world.postiz_status = cp(f"key {PZ_KEY} rejected", 1, f"{PZ_KEY}")
    world.gh_result = cp("", 1, f"token {SB_KEY} invalid")
    r = invoke(world, monkeypatch, "check")
    assert r.exit_code == 1
    for secret in SECRETS:
        assert secret not in r.output, secret


def test_cli_works_from_the_real_repo_with_nothing_configured(monkeypatch):
    """No secrets, no network: build_env on the real repo, with every outside call refused."""
    for var in ("DATABASE_URL", "SUPABASE_URL", "SUPABASE_SERVICE_KEY", "POSTIZ_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    refused = []

    def run(args):
        refused.append(list(args))
        raise FileNotFoundError(args[0])

    def http(url, headers):
        raise AssertionError("no URL is configured, so no request may be made")

    def db(dsn, sql):
        raise AssertionError("no DSN is configured, so no connection may be made")

    base = golive.build_env()
    env = golive.Env(
        root=base.root, settings=base.settings, run=run, http=http, keychain=lambda item: False, db=db, which=lambda n: None
    )
    monkeypatch.setattr(golive, "build_env", lambda root=None: env)
    r = CliRunner().invoke(app, ["golive", "check"])
    assert r.exit_code == 1
    assert "❌" in r.output and "database" in r.output and "keychain: cs-database-url" in r.output


# ---- the owner's checklist stays true to the check -------------------------------------------------

_GROUPS = ("keychain:", "database:", "data api:", "characters:", "github:", "drop:", "postiz:", "permissions:", "repo:")


def test_go_live_doc_is_short_and_every_check_it_names_is_a_real_check(world):
    doc = (ROOT / "docs" / "launch" / "go-live.md").read_text()
    assert len(doc.splitlines()) <= 150
    titles = {c.title for c in golive.run_checks(world.env())}
    named = {m for m in re.findall(r"`([^`]+)`", doc) if m.startswith(_GROUPS)}
    assert len(named) >= 12
    assert named <= titles, f"go-live.md names checks that do not exist: {sorted(named - titles)}"
    for title in titles:
        assert title in doc or title.startswith("github: workflow health") or title.startswith("github: secret"), title


def test_claude_md_points_at_the_go_live_doc_and_stays_short():
    text = (ROOT / "CLAUDE.md").read_text()
    assert len(text.splitlines()) <= 40
    assert "docs/launch/go-live.md" in text and "studio golive check" in text



# ---- Drop a video: the cloud jobs' secrets, the workflow and the Vault token (plan 2026-10-06) ---------------------------------


def test_the_drop_secrets_the_workflow_and_the_vault_token_pass_when_present(world):
    checks = world.run()
    for name, _ in golive.DROP_SECRETS:
        assert checks[f"github:{name}"].status == "pass"
    assert checks["github:workflow:studio-drop"].status == "pass"
    assert checks["drop:vault"].status == "pass" and checks["drop:vault"].title == "drop: vault secret github_dispatch_token"


def test_a_missing_drop_secret_fails_with_a_prompting_set_command(world):
    world.gh_secrets.remove("GEMINI_API_KEY")
    checks = world.run()
    assert failing(checks) == {"github:GEMINI_API_KEY"}
    fix = checks["github:GEMINI_API_KEY"].fix
    assert fix.startswith("gh secret set GEMINI_API_KEY ") and "aistudio.google.com" in fix  # gh asks for it: never typed inline


def test_a_missing_vault_token_fails_and_the_value_is_never_selected(world):
    world.vault = [(0,)]
    checks = world.run()
    assert failing(checks) == {"drop:vault"}
    assert "github_dispatch_token" in checks["drop:vault"].fix and "Contents: read and write" in checks["drop:vault"].fix
    assert "decrypted" not in golive.VAULT_SQL and "secret," not in golive.VAULT_SQL and golive.VAULT_SQL.startswith("select count(*)")
    world.vault = RuntimeError('relation "vault.secrets" does not exist')
    assert world.run()["drop:vault"].status == "fail"
