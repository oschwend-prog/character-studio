"""Plumbing shared by every CLI sub-app: the store, JSON output and caller errors.

Exit codes used across the CLI: 0 ok, 2 anything the caller must fix (no ``DATABASE_URL``,
unknown id, bad value), 3 refused by the budget (see ``studio.budget``). An unexpected crash
exits 1, so it is never mistaken for either.
"""

from __future__ import annotations

import dataclasses
import json
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any, NoReturn

import typer

from studio.config import LONDON, load
from studio.pgstore import PostgresStore
from studio.storage import Storage, SupabaseStorage
from studio.store import Store

EXIT_USAGE = 2


def fail(message: str) -> NoReturn:
    """Print ``error: <message>`` on stderr and exit 2 (the caller must fix something)."""
    typer.echo(f"error: {message}", err=True)
    raise typer.Exit(EXIT_USAGE)


def text_option(value: str | None, file: Path | None, name: str) -> str | None:
    """The text of ``--<name>`` or ``--<name>-file`` (never both; exit 2 if both).

    Free text (a breakdown, a hook, a caption, a reason, a JSON blob) belongs in a file the caller
    wrote with a file tool and passes with ``--<name>-file``: the shell never sees it, so a quote,
    ``$(...)`` or backtick in text that came from a third party cannot become a command. The file is
    read as UTF-8 and exactly one trailing newline is dropped.
    """
    if value is not None and file is not None:
        fail(f"use --{name} or --{name}-file, not both")
    if file is None:
        return value
    try:
        text = file.read_text(encoding="utf-8")
    except FileNotFoundError:
        fail(f"no such file: {file}")
    except (OSError, UnicodeDecodeError) as e:
        fail(f"cannot read {file}: {e}")
    return text[:-1] if text.endswith("\n") else text


def parse_when(value: str, option: str) -> datetime:
    """``value`` (an ISO 8601 date-time) as an aware datetime; exit 2 naming ``option`` when it is not one.

    A time with an offset or ``Z`` is taken as given. One without is the owner's wall clock and is
    read as Europe/London (BST or GMT as of that date), so no naive datetime ever reaches a store.
    """
    try:
        moment = datetime.fromisoformat(value.strip())
    except ValueError:
        fail(f"{option} must be an ISO 8601 date-time like 2026-10-06T19:00 or 2026-10-06T19:00:00+01:00, got {value!r}")
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=LONDON)


def open_store() -> Store:
    """The production store, or a clear error + exit 2 when ``DATABASE_URL`` is not set."""
    url = load().database_url
    if not url:
        fail(
            "DATABASE_URL is not set. Run through bin/studio (it reads the Keychain item "
            "cs-database-url) or export DATABASE_URL."
        )
    return PostgresStore(url)


def open_storage() -> Storage:
    """Supabase Storage, or a clear error + exit 2 when ``SUPABASE_URL`` / ``SUPABASE_SERVICE_KEY`` is unset.

    The error names the variables, never their values (the service key is a secret).
    """
    settings = load()
    url, key = settings.supabase_url, settings.supabase_service_key
    if not url or not key:
        missing = [n for n, v in (("SUPABASE_URL", url), ("SUPABASE_SERVICE_KEY", key)) if not v]
        fail(
            f"{' and '.join(missing)} not set. Run through bin/studio (it reads the Keychain items "
            "cs-supabase-url and cs-supabase-service-key) or export them."
        )
    return SupabaseStorage(url, key)


def _json_default(value: Any) -> Any:
    if isinstance(value, (datetime, date)):  # a datetime is a date: both end up as ISO text
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, Enum):
        return value.value
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return dataclasses.asdict(value)
    raise TypeError(f"cannot serialise {type(value).__name__} to JSON")


def emit(payload: Any) -> None:
    """Print ``payload`` (dict, list or dataclass) as indented JSON on stdout."""
    typer.echo(json.dumps(payload, indent=2, default=_json_default))
