"""``studio publish``: send due posts through Postiz (``due``), or show what would go (``--dry-run``).

The logic lives in ``studio.publish.base`` (claim, cap, retry, stale handling) and
``studio.publish.postiz`` (the CLI adapter); this module is only the command line.

``studio publish due`` prints the run summary as JSON on stdout. Exit 0 when the run did its job
(posts that failed or need a check are in the summary, and ``studio health`` raises them); exit 1 when
an outcome could not be recorded (the post stays ``posting`` and becomes ``needs_check``); exit 2 for
something the caller must fix (no ``DATABASE_URL``, Supabase or ``POSTIZ_API_KEY``, no ``postiz`` CLI).
``--dry-run`` claims and writes nothing, needs neither Storage nor Postiz, and prints what would go.
With the kill switch on, ``due`` claims nothing and prints ``"paused": true``.

``studio publish resolve <post>`` settles a ``needs_check`` / ``failed`` post by hand, with exactly one
of ``--live --platform-post-id ID [--url U]``, ``--retry [--at ISO]``, ``--drop --reason-file F`` (see
``studio.publish.resolve``); exit 2 for a wrong call, nothing written.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from shutil import which
from typing import Annotated

import typer

from studio.cli_support import emit, fail, open_storage, open_store, parse_when, text_option
from studio.config import load, now_london
from studio.publish.base import (
    PublishResult,
    Publisher,
    UncertainPublish,
    preview_due,
    publish_due,
)
from studio.publish.postiz import PostizError, PostizPublisher
from studio.publish.resolve import resolve_drop, resolve_live, resolve_retry

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


@app.command("resolve")
def resolve_command(
    post: Annotated[str, typer.Argument(help="Post id (a needs_check or failed post).")],
    live: Annotated[bool, typer.Option("--live", help="It is live on the platform: record it as posted.")] = False,
    retry: Annotated[bool, typer.Option("--retry", help="It is NOT live: send it again.")] = False,
    drop: Annotated[bool, typer.Option("--drop", help="Forget it: delete the never-posted row.")] = False,
    platform_post_id: Annotated[
        str | None, typer.Option("--platform-post-id", help="With --live: the Postiz post id (metrics use it).")
    ] = None,
    url: Annotated[str | None, typer.Option(help="With --live: the post's public URL.")] = None,
    at: Annotated[
        str | None, typer.Option(help="With --retry: ISO 8601 time to send it (no offset = London).")
    ] = None,
    reason_file: Annotated[
        Path | None, typer.Option("--reason-file", help="With --drop: why, in a file (free text never inline).")
    ] = None,
) -> None:
    """Settle a needs_check / failed post by hand, after looking at the platform. Exactly one of
    --live, --retry, --drop."""
    if [live, retry, drop].count(True) != 1:
        fail("pass exactly one of --live, --retry, --drop")
    store = open_store()
    try:
        if live:
            if platform_post_id is None:
                fail("--platform-post-id is required with --live")
            emit(resolve_live(store, post, platform_post_id, url))
        elif retry:
            when: datetime | None = parse_when(at, "--at") if at is not None else None
            emit(resolve_retry(store, post, when))
        else:
            reason = text_option(None, reason_file, "reason")
            if reason is None:
                fail("--reason-file is required with --drop")
            emit(resolve_drop(store, post, reason))
    except KeyError:
        fail(f"unknown post {post}")
    except ValueError as e:
        fail(str(e))
