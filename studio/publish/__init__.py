"""``studio publish``: send due posts through Postiz (``due``), or show what would go (``--dry-run``).

The logic lives in ``studio.publish.base`` (claim, cap, retry, stale handling) and
``studio.publish.postiz`` (the CLI adapter); this module is only the command line.

``studio publish due`` prints the run summary as JSON on stdout. Exit 0 when the run did its job
(posts that failed or need a check are in the summary, and ``studio health`` raises them); exit 1 when
an outcome could not be recorded (the post stays ``posting`` and becomes ``needs_check``); exit 2 for
something the caller must fix (no ``DATABASE_URL``, Supabase or ``POSTIZ_API_KEY``, no ``postiz`` CLI).
``--dry-run`` claims and writes nothing, needs neither Storage nor Postiz, and prints what would go.
"""

from __future__ import annotations

from shutil import which
from typing import Annotated

import typer

from studio.cli_support import emit, fail, open_storage, open_store
from studio.config import load, now_london
from studio.publish.base import (
    PublishResult,
    Publisher,
    UncertainPublish,
    preview_due,
    publish_due,
)
from studio.publish.postiz import PostizError, PostizPublisher

__all__ = [
    "PostizError",
    "PostizPublisher",
    "PublishResult",
    "Publisher",
    "UncertainPublish",
    "app",
    "preview_due",
    "publish_due",
]

app = typer.Typer(
    help="Publish due posts via Postiz. Prints JSON; exit 1 = an outcome was not recorded, "
    "exit 2 = something to fix.",
    no_args_is_help=True,
)


@app.command("due")
def due_command(
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Claim and write nothing; print what would be posted."),
    ] = False,
) -> None:
    """Post every due, scheduled post (at most 2 per account per London day)."""
    store = open_store()
    now = now_london()
    if dry_run:
        emit(preview_due(store, now))
        return
    storage = open_storage()
    if not load().postiz_api_key:
        fail(
            "POSTIZ_API_KEY is not set. Run through bin/studio (it reads the Keychain item "
            "cs-postiz-api-key) or export it."
        )
    if which("postiz") is None:
        fail("the postiz CLI is not on PATH. Install it with: npm i -g postiz")
    summary = publish_due(store, storage, PostizPublisher(), now)
    emit(summary)
    if summary["errors"]:
        raise typer.Exit(1)
