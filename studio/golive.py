"""``studio golive check``: every non-MCP prerequisite for going live, as a ✅/❌ checklist.

Run it through ``bin/studio`` (which exports the Keychain secrets) from anywhere: it works on this
checkout. It prints one line per check, a one-line fix under every ❌ and exits 0 only when nothing
failed. A ➖ (skipped) is not a failure: it is a check that cannot apply on this machine (the Postiz
CLI is only installed in CI until the rehearsal).

What is checked, in the order the owner's checklist (``docs/launch/go-live.md``) turns them green:

* Keychain items ``cs-database-url``, ``cs-supabase-url``, ``cs-supabase-service-key``,
  ``cs-postiz-api-key``: present or absent. The probe never reads a value.
* The database is reachable, schema ``studio`` has the tables and objects of migrations 0001-0012.
* The Supabase Data API exposes schema ``studio`` (the terminal and the owner RPCs need it).
* Characters: at least one is ``live``; each launch character has masters, a close-up and an account
  with a Postiz integration id (``characters/*/refs.json`` plus the database).
* GitHub: the four secrets exist and the publish / metrics / health workflows are enabled.
* Drop a video (plan 2026-10-06): the GitHub secrets of the cloud jobs (``HF_API_KEY_ID``, ``HF_API_KEY_SECRET``,
  ``GEMINI_API_KEY``), the ``studio-drop`` workflow enabled, and the Supabase Vault secret ``github_dispatch_token`` that lets
  the owner's button start it (only its presence is read, never its value).
* The ``postiz`` CLI is on PATH and ``postiz auth:status`` succeeds.
* ``.claude/settings.json`` carries the deny rules of ``.claude/settings.json.proposed``.
* No ``.env`` or other secret file is tracked in git.

Every outside call is a field of :class:`Env` (``run``, ``http``, ``keychain``, ``db``, ``which``), so
the tests drive each check with fakes. Secrets never reach the output: error text from a driver or a
service is scrubbed of the configured values (and of any ``user:password@`` in a URL) before it is shown.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, Literal
from urllib.parse import unquote, urlsplit

import httpx
import psycopg
import typer

from studio.config import Settings, load
from studio.seed import load_refs

DEFAULT_ROOT = Path(__file__).resolve().parents[1]

# (GitHub secret / environment variable, Keychain item that `bin/studio` reads it from)
SECRETS: tuple[tuple[str, str], ...] = (
    ("DATABASE_URL", "cs-database-url"),
    ("SUPABASE_URL", "cs-supabase-url"),
    ("SUPABASE_SERVICE_KEY", "cs-supabase-service-key"),
    ("POSTIZ_API_KEY", "cs-postiz-api-key"),
)
# Where the owner finds each value (shown in the fix line; no value is ever shown).
KEYCHAIN_SOURCE = {
    "cs-database-url": "Supabase project hkcafvzjwkeibbmvskko > Connect > session pooler string",
    "cs-supabase-url": "Supabase > Settings > API > Project URL",
    "cs-supabase-service-key": "Supabase > Settings > API > service_role key",
    "cs-postiz-api-key": "Postiz > Settings > Public API",
}
WORKFLOWS = ("publish", "metrics", "health", "studio-drop")
# The cloud jobs of "Drop a video": GitHub secrets only (they never sit on the Mac), each with where the owner makes it.
DROP_SECRETS: tuple[tuple[str, str], ...] = (
    ("HF_KEY", "console.higgsfield.ai > API keys: the whole id:secret value the console copies, shown once"),
    ("GEMINI_API_KEY", "aistudio.google.com > Get API key"),
)
# The older pair that stands in for HF_KEY (the cloud job and the client accept either).
HF_PAIR = ("HF_API_KEY_ID", "HF_API_KEY_SECRET")
VAULT_SECRET = "github_dispatch_token"
# Only whether the Vault holds a secret of that name: the value is never selected.
VAULT_SQL = "select count(*) from vault.secrets where name = 'github_dispatch_token'"

# What each migration leaves behind in schema studio: (kind, name). tests/test_golive.py pins these to
# the text of supabase/migrations/*.sql, so a new migration or object cannot be forgotten here.
MIGRATION_MARKERS: dict[str, tuple[tuple[str, str], ...]] = {
    "0001": tuple(
        ("table", t)
        for t in (
            "settings", "characters", "accounts", "sources", "clips", "posts",
            "snapshots", "ledger", "runs", "reviews", "favorites",
        )
    ),
    "0002": (("column", "skip_rate"), ("column", "watched_pct")),  # on studio.snapshots
    "0003": (("index", "accounts_character_platform_key"),),
    "0004": tuple(
        [
            ("function", f)
            for f in (
                "num", "cadence_days", "upcoming_slot", "next_slot", "dropin_ratio", "accounts_for_clip",
                "approved_posts", "approve_clip", "reject_clip", "regenerate_clip", "set_budget",
                "set_account_mode", "decide_pick", "add_owner_link",
            )
        ]
        + [
            ("view", v)
            for v in ("v_channels", "v_queue", "v_library", "v_budget", "v_health", "v_picks", "v_pick_history")
        ]
    ),
    # 0005 re-creates approve_clip and v_queue; queue_block_reason is what tells it apart from 0004.
    "0005": (("function", "queue_block_reason"), ("function", "approve_clip"), ("view", "v_queue")),
    # 0006 re-creates approve_clip and v_queue on the free-slot rule and keys reviews on (week, character).
    "0006": (
        ("function", "free_slot"), ("function", "next_free_slot"), ("function", "approve_clip"),
        ("view", "v_queue"), ("index", "reviews_week_character_slug_key"),
    ),
    # 0007: characters.setup and runs.details (columns), the Characters view, the picks views with the owner's
    # instructions and decide_pick with its four new parameters (the one function of that name).
    "0007": (
        ("column", "setup"), ("column", "details"), ("view", "v_characters"), ("view", "v_picks"),
        ("view", "v_pick_history"), ("function", "decide_pick"),
    ),
    # 0008 (Drop-in first): sources.has_minors (the column the CLI now writes), accounts_for_clip with "a share of 1 is
    # no cap", decide_pick with owner_props / owner_music (the one function of that name), attach_clip (the owner's own
    # clip for a Drop-in) and the picks views with the card appended.
    "0008": (
        ("column", "has_minors"), ("function", "accounts_for_clip"), ("function", "decide_pick"),
        ("function", "attach_clip"), ("view", "v_picks"), ("view", "v_pick_history"),
    ),
    # 0009 (the analyst's data): only the two picks views, with six columns appended. The last of them, `analysis`, is the
    # marker that tells 0009 from 0008 (the probe reads it from the view's own columns).
    "0009": (("view", "v_picks"), ("view", "v_pick_history"), ("column", "analysis")),
    # 0010 (the long list, "In the works" and the first comment): the picks views with nine more columns, the last of them
    # `source_candidates` (read from v_picks' own columns), the new tracker view and v_queue with `first_comment` appended
    # (read from v_queue's own columns).
    "0010": (
        ("view", "v_picks"), ("view", "v_pick_history"), ("view", "v_tracker"), ("view", "v_queue"),
        ("column", "source_candidates"), ("column", "first_comment"),
    ),
    # 0011 (when the owner decided): decide_pick and v_tracker re-created; the column v_tracker appends, `decided_at`, is what
    # tells 0011 from 0010 (the function and the view already exist after 0010).
    "0011": (("function", "decide_pick"), ("view", "v_tracker"), ("column", "decided_at")),
    # 0012 (Drop a video): add_drop, request_job (the owner's button: pg_net + the Vault token), set_drop_footage (the own-footage
    # toggle) and v_tracker with the drop's
    # card appended (drop_card, then make_requested_at: the last appended column tells it from 0011).
    "0012": (
        ("function", "add_drop"), ("function", "request_job"), ("function", "set_drop_footage"), ("view", "v_tracker"),
        ("column", "make_requested_at"),
    ),
}

PROBE_SQL = """
select case c.relkind when 'v' then 'view' else 'table' end, c.relname::text
from pg_class c join pg_namespace n on n.oid = c.relnamespace
where n.nspname = 'studio' and c.relkind in ('r', 'p', 'v')
union all
select 'column', a.attname::text
from pg_attribute a
join pg_class c on c.oid = a.attrelid
join pg_namespace n on n.oid = c.relnamespace
where n.nspname = 'studio' and a.attnum > 0 and not a.attisdropped
  and ((c.relname = 'snapshots') or (c.relname = 'characters' and a.attname = 'setup')
       or (c.relname = 'runs' and a.attname = 'details') or (c.relname = 'sources' and a.attname = 'has_minors')
       or (c.relname = 'v_picks' and a.attname in ('analysis', 'source_candidates'))
       or (c.relname = 'v_queue' and a.attname = 'first_comment')
       or (c.relname = 'v_tracker' and a.attname in ('decided_at', 'make_requested_at')))
union all
select 'index', indexname::text from pg_indexes where schemaname = 'studio'
union all
select 'function', p.proname::text
from pg_proc p join pg_namespace n on n.oid = p.pronamespace
where n.nspname = 'studio'
"""

CHARACTERS_SQL = """
select c.slug, c.status, a.platform, a.postiz_integration_id
from studio.characters c
left join studio.accounts a on a.character_slug = c.slug
order by c.slug, a.platform
"""

# Tracked files that look like secrets, matched on the file name. Examples and public keys are fine.
_SECRET_NAME = re.compile(
    r"\.env(\..+)?|.*\.env|.*\.(pem|key|p12|pfx)|id_(rsa|dsa|ecdsa|ed25519)|\.netrc"
    r"|(credentials?|secrets?)(\.(json|ya?ml|txt|toml|ini))?|service[-_]account.*\.json",
    re.IGNORECASE,
)
_SAFE_NAMES = {".env.example", ".env.sample", ".env.template", ".env.dist"}

Status = Literal["pass", "fail", "skip"]
ICON: dict[str, str] = {"pass": "✅", "fail": "❌", "skip": "➖"}


@dataclass(frozen=True)
class Check:
    """One line of the checklist. ``fix`` is a single line (empty on a pass)."""

    id: str
    title: str  # "<group>: <what>", printed after the icon
    status: Status
    detail: str = ""
    fix: str = ""


Runner = Callable[[Sequence[str]], "subprocess.CompletedProcess[str]"]
HttpGet = Callable[[str, Mapping[str, str]], tuple[int, str]]


@dataclass
class Env:
    """Every outside call the checks make. ``build_env`` wires the real ones; tests wire fakes."""

    root: Path
    settings: Settings
    run: Runner  # run(args) -> CompletedProcess; raises FileNotFoundError when the program is missing
    http: HttpGet  # http(url, headers) -> (status, body)
    keychain: Callable[[str], bool]  # keychain(item) -> is the item present? (never returns a value)
    db: Callable[[str, str], list[tuple]]  # db(dsn, sql) -> rows
    which: Callable[[str], str | None]


# ---- the real adapters -----------------------------------------------------------------------------


def shell_runner(root: Path) -> Runner:
    """Run a command in the repo root, capturing text, never reading stdin, with a timeout."""

    def run(args: Sequence[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            list(args), cwd=root, capture_output=True, text=True, errors="replace",
            timeout=60, stdin=subprocess.DEVNULL,
        )  # fmt: skip

    return run


def keychain_probe(run: Runner) -> Callable[[str], bool]:
    """Is the Keychain item there? ``security find-generic-password -s ITEM`` without ``-w``/``-g`` prints
    the item's attributes and never its secret, so nothing sensitive is read and no prompt appears."""

    def present(item: str) -> bool:
        try:
            return run(["security", "find-generic-password", "-s", item]).returncode == 0
        except (OSError, subprocess.SubprocessError):
            return False

    return present


def http_get(
    url: str, headers: Mapping[str, str], *, transport: httpx.BaseTransport | None = None, timeout: float = 15.0
) -> tuple[int, str]:
    """GET without following redirects; ``(status, body text)``."""
    with httpx.Client(transport=transport, timeout=timeout, follow_redirects=False) as client:
        response = client.get(url, headers=dict(headers))
    return response.status_code, response.text


def db_query(dsn: str, sql: str) -> list[tuple]:
    """Rows of one SELECT on a short-lived connection (``prepare_threshold=None``: works through the pooler)."""
    with psycopg.connect(dsn, connect_timeout=15, autocommit=True, prepare_threshold=None) as conn:
        return [tuple(row) for row in conn.execute(sql).fetchall()]  # type: ignore[arg-type]


def build_env(root: Path | None = None) -> Env:
    root = Path(root) if root is not None else DEFAULT_ROOT
    run = shell_runner(root)
    return Env(
        root=root, settings=load(), run=run, http=http_get, keychain=keychain_probe(run),
        db=db_query, which=shutil.which,
    )  # fmt: skip


# ---- helpers ---------------------------------------------------------------------------------------


def _secret_values(settings: Settings) -> list[str]:
    values = [settings.database_url, settings.supabase_service_key, settings.postiz_api_key]
    found = [v for v in values if v]
    if settings.database_url:
        try:
            password = urlsplit(settings.database_url).password
        except ValueError:
            password = None
        if password:
            found += [password, unquote(password)]
    return sorted(set(found), key=len, reverse=True)  # longest first: a DSN before its own password


def scrub(text: str, settings: Settings) -> str:
    """``text`` with every configured secret (and any ``user:password@`` in a URL) replaced by ``***``."""
    for value in _secret_values(settings):
        text = text.replace(value, "***")
    return re.sub(r"(://[^:/@\s]+):[^@\s]+@", r"\1:***@", text)


def _line(text: str, settings: Settings, limit: int = 200) -> str:
    """The first non-empty line of ``text``, scrubbed and shortened."""
    first = next((ln.strip() for ln in text.splitlines() if ln.strip()), "")
    first = scrub(first, settings)
    return first if len(first) <= limit else first[: limit - 3] + "..."


def _error(exc: BaseException, settings: Settings) -> str:
    return _line(f"{type(exc).__name__}: {exc}", settings)


def _more(items: Sequence[str], shown: int = 3) -> str:
    head = ", ".join(items[:shown])
    return head + (f" +{len(items) - shown} more" if len(items) > shown else "")


class _CommandFailed(Exception):
    """A command that is missing, timed out or exited non-zero; the message is scrubbed and one line."""


def _call(env: Env, args: Sequence[str]) -> subprocess.CompletedProcess[str]:
    program = args[0]
    try:
        proc = env.run(args)
    except FileNotFoundError:
        raise _CommandFailed(f"{program} is not installed") from None
    except subprocess.TimeoutExpired:
        raise _CommandFailed(f"{program} timed out") from None
    except OSError as e:
        raise _CommandFailed(f"{program}: {_error(e, env.settings)}") from None
    if proc.returncode != 0:
        said = _line(proc.stderr or proc.stdout or "", env.settings)
        raise _CommandFailed(said or f"{program} exited {proc.returncode}")
    return proc


def _query(env: Env, sql: str) -> tuple[list[tuple] | None, str]:
    """``(rows, "")`` or ``(None, why)``. The reason is scrubbed."""
    dsn = env.settings.database_url
    if not dsn:
        return None, "DATABASE_URL is not set"
    try:
        return env.db(dsn, sql), ""
    except Exception as e:  # a driver can raise anything; every one is a failed check, never a crash
        return None, _error(e, env.settings)


NO_DSN_FIX = (
    'security add-generic-password -s cs-database-url -a "$USER" -w  (then run through bin/studio, which exports it)'
)
BAD_DSN_FIX = (
    "check the session-pooler string in Keychain item cs-database-url (Supabase > Connect), "
    "and that the project is not paused"
)


# ---- (a) Keychain ----------------------------------------------------------------------------------


def check_keychain(env: Env) -> list[Check]:
    out = []
    for _, item in SECRETS:
        title = f"keychain: {item}"
        if env.keychain(item):
            out.append(Check(f"keychain:{item}", title, "pass", "present"))
        else:
            fix = f'security add-generic-password -s {item} -a "$USER" -w  (value: {KEYCHAIN_SOURCE[item]})'
            out.append(Check(f"keychain:{item}", title, "fail", "missing", fix))
    return out


# ---- (b) database ----------------------------------------------------------------------------------


def _migration_file(root: Path, number: str) -> str:
    found = sorted((root / "supabase" / "migrations").glob(f"{number}_*.sql"))
    return f"supabase/migrations/{found[0].name}" if found else f"supabase/migrations/{number}_*.sql"


def check_database(env: Env) -> list[Check]:
    schema_title = f"database: schema studio, migrations {min(MIGRATION_MARKERS)}-{max(MIGRATION_MARKERS)}"
    rows, why = _query(env, PROBE_SQL)
    if rows is None:
        fix = BAD_DSN_FIX if env.settings.database_url else NO_DSN_FIX
        return [
            Check("database", "database: reachable", "fail", why, fix),
            Check("schema", schema_title, "fail", "not checked: the database is not reachable", "fix `database: reachable` first"),
        ]  # fmt: skip
    have = {(str(kind), str(name)) for kind, name in rows}
    problems, files = [], []
    for number, markers in MIGRATION_MARKERS.items():
        missing = [f"{kind} {name}" for kind, name in markers if (kind, name) not in have]
        if missing:
            problems.append(f"migration {number}: missing {_more(missing)}")
            files.append(_migration_file(env.root, number))
    reachable = Check("database", "database: reachable", "pass", "connected, schema probe answered")
    if not problems:
        return [reachable, Check("schema", schema_title, "pass", "all tables, columns, indexes, functions and views are there")]
    fix = f"apply {', '.join(files)} in order (Supabase MCP apply_migration, or the SQL editor)"
    return [reachable, Check("schema", schema_title, "fail", "; ".join(problems), fix)]


# ---- (c) Data API ----------------------------------------------------------------------------------


def check_data_api(env: Env) -> Check:
    title, cid = "data api: schema studio exposed", "dataapi"
    url, key = env.settings.supabase_url, env.settings.supabase_service_key
    if not url or not key:
        missing = [n for n, v in (("SUPABASE_URL", url), ("SUPABASE_SERVICE_KEY", key)) if not v]
        return Check(
            cid, title, "fail", f"{' and '.join(missing)} not set",
            'store Keychain items cs-supabase-url and cs-supabase-service-key (go-live step 4), then run through bin/studio',
        )  # fmt: skip
    endpoint = f"{url.rstrip('/')}/rest/v1/settings?select=id"
    headers = {"apikey": key, "Authorization": f"Bearer {key}", "Accept-Profile": "studio"}
    try:
        status, body = env.http(endpoint, headers)
    except Exception as e:  # httpx raises a family of errors; all of them mean "could not ask"
        return Check(
            cid, title, "fail", f"request failed: {_error(e, env.settings)}",
            "check Keychain item cs-supabase-url (https://<ref>.supabase.co) and the connection",
        )  # fmt: skip
    if status == 200:
        return Check(cid, title, "pass", "GET /rest/v1/settings with Accept-Profile: studio answered 200")
    if "PGRST106" in body or "schema must be one of" in body:
        return Check(
            cid, title, "fail", f"HTTP {status}: schema studio is not exposed by the Data API",
            "Supabase dashboard > Settings > API > Exposed schemas: add studio and save (go-live step 5)",
        )  # fmt: skip
    if status == 403 and ("42501" in body or "permission denied" in body.lower()):
        # PostgREST resolves the schema (PGRST106 when it is not exposed) before the role's privileges, so a
        # privilege error proves the schema is exposed. The migrations grant studio to `authenticated` only.
        return Check(
            cid, title, "pass",
            "schema exposed (service_role has no table grant, which is fine: the app uses authenticated)",
        )  # fmt: skip
    if status == 401:
        return Check(
            cid, title, "fail", f"HTTP {status}: the service key was rejected",
            "re-store cs-supabase-service-key from Supabase > Settings > API (the service_role key, not anon)",
        )  # fmt: skip
    return Check(
        cid, title, "fail", f"HTTP {status}: {_line(body, env.settings, 120)}",
        "check migration 0001 is applied, the schema is exposed and the project is not paused",
    )  # fmt: skip


# ---- (d) characters --------------------------------------------------------------------------------


def check_characters(env: Env) -> list[Check]:
    out: list[Check] = []
    rows, why = _query(env, CHARACTERS_SQL)
    db_fix = "fix `database: reachable` first"
    statuses: dict[str, str] = {}
    connected: dict[str, int] = {}
    for slug, status, _platform, integration_id in rows or []:
        statuses[slug] = status
        connected[slug] = connected.get(slug, 0) + (1 if integration_id else 0)

    live_title = "characters: at least one live"
    if rows is None:
        out.append(Check("characters:live", live_title, "fail", "database not reachable: see database: reachable", db_fix))
    elif not statuses:
        out.append(Check("characters:live", live_title, "fail", "no characters in the database yet", "bin/studio seed (go-live step 3)"))
    elif live := sorted(s for s, st in statuses.items() if st == "live"):
        out.append(Check("characters:live", live_title, "pass", f"live: {', '.join(live)}"))
    else:
        seen = ", ".join(f"{s}={st}" for s, st in sorted(statuses.items()))
        out.append(
            Check(
                "characters:live", live_title, "fail", f"none live ({seen})",
                'set "status": "live" in characters/<slug>/refs.json, then bin/studio seed (go-live step 9)',
            )  # fmt: skip
        )

    refs_title = "characters: refs.json valid"
    try:
        refs = load_refs(env.root / "characters")
    except ValueError as e:
        out.append(
            Check(
                "characters:refs", refs_title, "fail", _line(str(e).replace(f"{env.root}/", ""), env.settings, 240),
                "fix the characters/<slug>/refs.json named above (every body needs a Higgsfield master job id), then bin/studio seed",
            )  # fmt: skip
        )
        return out
    out.append(Check("characters:refs", refs_title, "pass", ", ".join(r["slug"] for r in refs)))

    for ref in refs:
        slug = ref["slug"]
        if ref["status"] == "paused":  # deliberately off: not part of the launch
            continue
        title = f"characters: {slug} ready"
        problems: list[str] = []
        fixes: list[str] = []
        if not ref.get("closeup"):
            problems.append("no close-up")
            fixes.append(f"generate the close-up (go-live step 10) and set closeup in characters/{slug}/refs.json")
        if rows is None:
            problems.append("accounts unknown (database not reachable)")
            fixes.append(db_fix)
        elif slug not in statuses:
            problems.append("not in the database yet")
            fixes.append("bin/studio seed")
        elif not connected.get(slug):
            problems.append("no account with a postiz_integration_id")
            fixes.append(
                f"connect the account in Postiz, put its id in characters/{slug}/refs.json, then bin/studio seed"
            )
        if problems:
            out.append(Check(f"characters:{slug}", title, "fail", "; ".join(problems), "; ".join(fixes)))
        else:
            n = connected[slug]
            out.append(
                Check(
                    f"characters:{slug}", title, "pass",
                    f"masters {'+'.join(ref['bodies'])}, close-up, {n} account{'s' if n != 1 else ''} with a Postiz id",
                )  # fmt: skip
            )
    return out


# ---- (e) GitHub ------------------------------------------------------------------------------------


def _gh_json(env: Env, args: Sequence[str]) -> list[dict[str, Any]]:
    proc = _call(env, args)
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        raise _CommandFailed(f"unexpected output from {' '.join(args[:3])}") from None
    if not isinstance(data, list) or not all(isinstance(d, dict) for d in data):
        raise _CommandFailed(f"unexpected output from {' '.join(args[:3])}")
    return data


def _gh_fix(why: str) -> str:
    return "brew install gh, then gh auth login" if "not installed" in why else "gh auth login"


def check_github(env: Env) -> list[Check]:
    out: list[Check] = []
    try:
        present = {str(d.get("name")) for d in _gh_json(env, ["gh", "secret", "list", "--json", "name"])}
    except _CommandFailed as e:
        out.append(Check("github:secrets", "github: secrets", "fail", f"gh secret list failed: {e}", _gh_fix(str(e))))
    else:
        for name, item in SECRETS:
            title = f"github: secret {name}"
            if name in present:
                out.append(Check(f"github:{name}", title, "pass", "set"))
            else:
                fix = f'printf %s "$(security find-generic-password -s {item} -w)" | gh secret set {name}'
                out.append(Check(f"github:{name}", title, "fail", "missing", fix))
        for name, where in DROP_SECRETS:
            title = f"github: secret {name}"
            if name in present or (name == "HF_KEY" and all(p in present for p in HF_PAIR)):
                out.append(Check(f"github:{name}", title, "pass", "set"))
            else:
                fix = f"gh secret set {name}  (paste the value when asked; it comes from {where})"
                out.append(Check(f"github:{name}", title, "fail", "missing (Drop a video waits at Checking / Make it)", fix))
    try:
        workflows = _gh_json(env, ["gh", "workflow", "list", "--all", "--json", "name,state,path"])
    except _CommandFailed as e:
        out.append(Check("github:workflows", "github: workflows", "fail", f"gh workflow list failed: {e}", _gh_fix(str(e))))
        return out
    for wf in WORKFLOWS:
        title, cid = f"github: workflow {wf} enabled", f"github:workflow:{wf}"
        found = next(
            (w for w in workflows if Path(str(w.get("path", ""))).stem == wf or str(w.get("name", "")).lower() == wf),
            None,
        )
        if found is None:
            out.append(Check(cid, title, "fail", "not found in the repo", f"push .github/workflows/{wf}.yml to the default branch"))
        elif found.get("state") == "active":
            out.append(Check(cid, title, "pass", "active"))
        else:
            out.append(Check(cid, title, "fail", f"state: {found.get('state')}", f"gh workflow enable {wf}.yml"))
    return out


def check_vault(env: Env) -> Check:
    """The Vault secret the owner's button uses to start the cloud job (migration 0012): present or not, never read."""
    title, cid = f"drop: vault secret {VAULT_SECRET}", "drop:vault"
    rows, why = _query(env, VAULT_SQL)
    if rows is None:
        return Check(
            cid, title, "fail", f"could not look: {why}",
            "fix `database: reachable` first" if not env.settings.database_url or "vault" not in why.lower()
            else "Supabase > Project Settings > Vault: enable it (Supabase projects have it by default)",
        )  # fmt: skip
    if rows and rows[0] and int(rows[0][0] or 0) > 0:
        return Check(cid, title, "pass", "present (the value is not read)")
    return Check(
        cid, title, "fail", "missing: drops are picked up by the 2-hourly sweep only",
        f"a fine-grained GitHub token for this repo only (Contents: read and write) into Supabase > Vault as {VAULT_SECRET}",
    )  # fmt: skip


# ---- (f) postiz CLI --------------------------------------------------------------------------------


def check_postiz(env: Env) -> Check:
    title, cid = "postiz: CLI installed and authenticated", "postiz"
    if env.which("postiz") is None:
        return Check(
            cid, title, "skip", "the postiz CLI is not installed here (CI installs it for publishing)",
            "npm i -g postiz  (needed for the rehearsal checks in go-live step 10)",
        )  # fmt: skip
    if not env.settings.postiz_api_key:
        return Check(
            cid, title, "fail", "POSTIZ_API_KEY is not set",
            "store Keychain item cs-postiz-api-key (go-live step 4), then run through bin/studio",
        )  # fmt: skip
    try:
        _call(env, ["postiz", "auth:status"])
    except _CommandFailed as e:
        return Check(
            cid, title, "fail", f"postiz auth:status failed: {e}",
            "re-store cs-postiz-api-key from Postiz > Settings > Public API, then run through bin/studio",
        )  # fmt: skip
    return Check(cid, title, "pass", "postiz auth:status OK")


# ---- (g) .claude/settings.json ---------------------------------------------------------------------


class _BadShape(ValueError):
    """A settings file that parses as JSON but is not shaped like Claude Code settings."""


def _rules(path: Path, key: str) -> list[str]:
    """The ``permissions.<key>`` strings of a settings file; [] when it has no ``permissions`` at all.

    ``_BadShape`` (with a one-line reason) for a file that is not an object, a ``permissions`` that is not
    an object, or a ``<key>`` that is not a list.
    """
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise _BadShape(f"{path.name} is not an object")
    perms = data.get("permissions")
    if perms is None:
        return []
    if not isinstance(perms, dict):
        raise _BadShape(f"{path.name}: permissions is not an object")
    rules = perms.get(key, [])
    if not isinstance(rules, list):
        raise _BadShape(f"{path.name}: permissions.{key} is not a list")
    return [r for r in rules if isinstance(r, str)]


def _deny_rules(path: Path) -> list[str]:
    return _rules(path, "deny")


_BLANKET_UV = re.compile(r"Bash\(uv(?:\s+run)?(?::\*|\s+\*)\)")


def _too_broad(allow: Sequence[str]) -> list[str]:
    """Allow rules that are not explicit: a whole MCP server, or any ``uv run`` command.

    ``mcp__<server>`` and ``mcp__<server>__*`` (or any ``*`` in an ``mcp__`` rule) let every tool of a server
    run unattended, including the ones it adds later; the unattended runs may call only the tools their
    skills name. ``Bash(uv run:*)`` runs any code in the project. Neither is used by the skills.
    """
    broad = []
    for rule in allow:
        if rule.startswith("mcp__"):
            _server, _, tool = rule[len("mcp__"):].partition("__")
            if not tool or "*" in rule:
                broad.append(rule)
        elif _BLANKET_UV.fullmatch(rule.strip()):
            broad.append(rule)
    return broad


def check_permissions(env: Env) -> Check:
    title, cid = "permissions: proposal applied (explicit allows, deny rules)", "permissions"
    cp = "cp .claude/settings.json.proposed .claude/settings.json"
    proposed_path = env.root / ".claude" / "settings.json.proposed"
    settings_path = env.root / ".claude" / "settings.json"
    if not proposed_path.is_file():
        return Check(
            cid, title, "fail", ".claude/settings.json.proposed not found",
            "restore it: git checkout -- .claude/settings.json.proposed",
        )  # fmt: skip
    if not settings_path.is_file():
        return Check(cid, title, "fail", ".claude/settings.json not found", f"read the proposal, then {cp}")
    try:
        wanted = _deny_rules(proposed_path)
        have = set(_deny_rules(settings_path))
        broad_proposed = _too_broad(_rules(proposed_path, "allow"))
        broad_applied = _too_broad(_rules(settings_path, "allow"))
    except _BadShape as e:
        return Check(cid, title, "fail", str(e), "repair the file (the proposal is in git), then " + cp)
    except (OSError, ValueError) as e:
        return Check(
            cid, title, "fail", f"settings.json or its proposal is not valid JSON ({type(e).__name__})",
            "repair the file (the proposal is in git), then " + cp,
        )  # fmt: skip
    if not wanted:
        return Check(
            cid, title, "fail", ".claude/settings.json.proposed lists no deny rules (nothing to check against)",
            "restore it: git checkout -- .claude/settings.json.proposed",
        )  # fmt: skip
    if broad_proposed:
        return Check(
            cid, title, "fail",
            f"the proposal itself is not an explicit allowlist (a whole MCP server or uv run): {_more(broad_proposed)}",
            "restore it: git checkout -- .claude/settings.json.proposed",
        )  # fmt: skip
    missing = [r for r in wanted if r not in have]
    problems = []
    if missing:
        problems.append(f"missing {len(missing)} deny rule{'s' if len(missing) != 1 else ''}: {_more(missing)}")
    if broad_applied:
        problems.append(
            f"settings.json allows more than the explicit tools the skills call (whole MCP server or uv run): "
            f"{_more(broad_applied)}"
        )
    if problems:
        return Check(
            cid, title, "fail", "; ".join(problems),
            f"read the diff (diff .claude/settings.json .claude/settings.json.proposed), then {cp}",
        )  # fmt: skip
    return Check(cid, title, "pass", f"all {len(wanted)} deny rules present, allow rules are explicit")


# ---- (h) tracked secret files ----------------------------------------------------------------------


def check_repo_secrets(env: Env) -> Check:
    title, cid = "repo: no secret files tracked", "repo:secrets"
    try:
        listing = _call(env, ["git", "ls-files", "-z"]).stdout
    except _CommandFailed as e:
        return Check(cid, title, "fail", f"git ls-files failed: {e}", "run it from the repo checkout")
    tracked = [p for p in listing.split("\0") if p]
    bad = [
        p for p in tracked
        if (name := p.rsplit("/", 1)[-1]).lower() not in _SAFE_NAMES and _SECRET_NAME.fullmatch(name)
    ]  # fmt: skip
    if bad:
        return Check(
            cid, title, "fail", f"tracked: {_more(bad, 5)}",
            "git rm --cached <file>, add it to .gitignore, and rotate the secret it held",
        )  # fmt: skip
    return Check(cid, title, "pass", f"{len(tracked)} tracked files, none look like secrets")


# ---- the run and the CLI ---------------------------------------------------------------------------


def run_checks(env: Env) -> list[Check]:
    return [
        *check_keychain(env),
        *check_database(env),
        check_data_api(env),
        *check_characters(env),
        *check_github(env),
        check_vault(env),
        check_postiz(env),
        check_permissions(env),
        check_repo_secrets(env),
    ]


def render(checks: Sequence[Check]) -> str:
    """The checklist as text: blank line between groups, a ``fix:`` line under every ❌ and ➖."""
    lines = ["ODD EYES go-live check", ""]
    group = None
    for c in checks:
        this = c.title.split(":", 1)[0]
        if group is not None and this != group:
            lines.append("")
        group = this
        lines.append(f"{ICON[c.status]} {c.title}" + (f" - {c.detail}" if c.detail else ""))
        if c.fix and c.status != "pass":
            lines.append(f"     fix: {c.fix}")
    passed = sum(c.status == "pass" for c in checks)
    skipped = sum(c.status == "skip" for c in checks)
    failed = sum(c.status == "fail" for c in checks)
    summary = f"{len(checks)} checks: {passed} pass" + (f", {skipped} skipped" if skipped else "") + f", {failed} to fix."
    lines += ["", summary]
    if failed:
        lines.append("Not ready yet: fix the failed checks above (steps in docs/launch/go-live.md), then run bin/studio golive check again.")
    else:
        lines.append("Ready to go live.")
    return "\n".join(lines)


app = typer.Typer(
    help="Go-live readiness. `studio golive check` prints a checklist of every prerequisite with a fix "
    "for each failure; exit 0 only when all pass, 1 when something needs fixing.",
    no_args_is_help=True,
)


@app.command("check")
def check_command(
    root: Annotated[Path | None, typer.Option(help="Repo root to check (default: this checkout).")] = None,
) -> None:
    """Check keychain, database, Data API, characters, GitHub, Postiz CLI, permissions and tracked files."""
    checks = run_checks(build_env(root))
    typer.echo(render(checks))
    if any(c.status == "fail" for c in checks):
        raise typer.Exit(1)
