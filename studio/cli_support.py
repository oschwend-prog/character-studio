"""Plumbing shared by every CLI sub-app: the store, JSON output and caller errors.

Exit codes used across the CLI: 0 ok, 2 anything the caller must fix (no ``DATABASE_URL``,
unknown id, bad value), 3 refused by the budget (see ``studio.budget``). An unexpected crash
exits 1, so it is never mistaken for either.
"""

from __future__ import annotations

import dataclasses
import json
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any, NoReturn

import typer

from studio.config import load
from studio.pgstore import PostgresStore
from studio.storage import Storage, SupabaseStorage
from studio.store import Store

EXIT_USAGE = 2


def fail(message: str) -> NoReturn:
    """Print ``error: <message>`` on stderr and exit 2 (the caller must fix something)."""
    typer.echo(f"error: {message}", err=True)
    raise typer.Exit(EXIT_USAGE)


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
    if isinstance(value, datetime):
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
