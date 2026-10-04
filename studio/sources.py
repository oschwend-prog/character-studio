"""Source library: the clips that drive our videos, their checks and their ranking.

Every driving clip (Higgsfield library imports, owner inbox clips, our own synthetic drivers) is
catalogued here with the checks that decide whether it may be used as a **Drop-in** (our
character swapped into the actual clip):

* ``has_watermark`` / ``has_overlay`` / ``other_people`` start as ``None`` ("not checked yet");
  an unchecked source is never Drop-in eligible, and neither is a ``synthetic`` one.
* ``flag_dirty`` is the late alarm (output QA spotted a leaked watermark): it sets
  ``has_watermark=True``, so the source drops out of Drop-in ranking at once.
* **Recreate** only borrows the moves and replaces everything else, so any source whose body
  type fits the character may drive it: watermarked, unchecked and synthetic ones included.

We never scrape or download from TikTok or Instagram: a platform page URL is not a source
(``add_source`` refuses it). Favourites (``studio.favorites``) are the lane for those links.

``rank_sources`` orders the usable sources by how well the clips made from them performed
(median ``features['outlier_x']``, best first, never-measured last), newest source first on ties.

CLI (``studio source ...``) prints JSON on stdout; exit 2 for anything the caller must fix.
``ingest-inbox`` arrives with Storage (Task 9).
"""

from __future__ import annotations

import dataclasses
import math
import statistics
from enum import Enum
from typing import Annotated, Any, TypeVar
from urllib.parse import urlsplit

import typer

from studio.cli_support import emit, fail, open_store
from studio.models import Body, Character, Mode, Source, SourceKind
from studio.store import Store

# Hosts we never take a source from; subdomains count (www., m., vm., vt., ...).
PLATFORM_DOMAINS = frozenset({"tiktok.com", "instagram.com", "vm.tiktok.com", "instagr.am"})

_E = TypeVar("_E", bound=Enum)


def _enum(cls: type[_E], value: Any, what: str) -> _E:
    try:
        return cls(value)
    except ValueError:
        allowed = [m.value for m in cls]
        raise ValueError(f"{what} must be one of {allowed}, got {value!r}") from None


def _host(url: str) -> str:
    raw = url.strip()
    parts = urlsplit(raw if "://" in raw else f"//{raw}")
    return (parts.hostname or "").lower().rstrip(".")


def is_platform_page(url: str) -> bool:
    """True for a TikTok / Instagram page URL (any subdomain, scheme optional)."""
    host = _host(url)
    return any(host == d or host.endswith(f".{d}") for d in PLATFORM_DOMAINS)


def dropin_eligible(s: Source) -> bool:
    """May this source be used for a Drop-in? Only when every check was run and came back clean."""
    return (
        s.kind is not SourceKind.synthetic
        and s.has_watermark is False
        and s.has_overlay is False
        and s.other_people == 0
    )


def add_source(
    store: Store,
    kind: SourceKind | str,
    url: str | None,
    body: Body | str,
    bodies: int,
    duration_s: float,
    preset_id: str | None = None,
    trend: str | None = None,
    credit_handle: str | None = None,
) -> Source:
    """Catalogue a new source, unchecked (so not Drop-in eligible until ``record_checks``)."""
    kind = _enum(SourceKind, kind, "kind")
    body = _enum(Body, body, "body")
    if bodies < 1:
        raise ValueError(f"bodies must be at least 1, got {bodies!r}")
    if not duration_s > 0:
        raise ValueError(f"duration_s must be positive, got {duration_s!r}")
    url = (url or "").strip() or None
    if url is not None and is_platform_page(url):
        raise ValueError("platform page URLs are not sources")
    return store.add_source(
        Source(
            kind=kind,
            url=url,
            preset_id=preset_id,
            body=body,
            bodies=bodies,
            duration_s=float(duration_s),
            trend=trend,
            credit_handle=credit_handle,
        )
    )


def record_checks(
    store: Store, id: str, has_watermark: bool, has_overlay: bool, other_people: int
) -> Source:
    """Store the result of the visual checks (6 frames: watermark, overlay, other people)."""
    if other_people < 0:
        raise ValueError(f"other_people must be 0 or more, got {other_people!r}")
    return store.update_source(
        id,
        has_watermark=bool(has_watermark),
        has_overlay=bool(has_overlay),
        other_people=other_people,
    )


def flag_dirty(store: Store, id: str, reason: str) -> Source:
    """A watermark showed up downstream: the source is no longer Drop-in eligible.

    ``reason`` is required so the caller has to say what was seen, but ``sources`` has no notes
    column to keep it in: the CLI echoes it, nothing persists it.
    """
    if not reason.strip():
        raise ValueError("reason is required: say what was seen (e.g. 'watermark in output frame 40')")
    return store.update_source(id, has_watermark=True)


def _outlier_x(features: dict[str, Any]) -> float | None:
    value = features.get("outlier_x")
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    return float(value)


def median_outlier_x(store: Store, source_id: str) -> float | None:
    """Median ``features['outlier_x']`` of the clips made from the source; ``None`` if unmeasured."""
    values = [
        x
        for clip in store.list_clips(source_id=source_id)
        if (x := _outlier_x(clip.features)) is not None
    ]
    return statistics.median(values) if values else None


def _created_ts(s: Source) -> float:
    return s.created_at.timestamp() if s.created_at else 0.0


def _rank(
    store: Store, character: Character, mode: Mode | str, exclude_ids: set[str]
) -> list[tuple[Source, float | None]]:
    mode = _enum(Mode, mode, "mode")
    bodies = set(character.bodies)
    pool = [
        s
        for s in store.list_sources()
        if s.id not in exclude_ids
        and s.body in bodies
        and (mode is Mode.recreate or dropin_eligible(s))
    ]
    scored = [(s, median_outlier_x(store, s.id)) for s in pool]
    scored.sort(key=lambda p: (p[1] is None, -(p[1] or 0.0), -_created_ts(p[0])))
    return scored


def rank_sources(
    store: Store, character: Character, mode: Mode | str, exclude_ids: set[str]
) -> list[Source]:
    """Usable sources for this character and mode, best first.

    Usable = not excluded, body type among the character's, and (Drop-in only) clean per
    ``dropin_eligible``. Order: median outlier_x of the clips made from it (descending, sources
    with no measured clip last), then ``created_at`` descending.
    """
    return [s for s, _ in _rank(store, character, mode, exclude_ids)]


# ---- CLI -----------------------------------------------------------------------------------

app = typer.Typer(
    help="Source library: add, check, flag, list and rank driving clips. "
    "Prints JSON; exit 2 = caller error.",
    no_args_is_help=True,
)


def _source_json(s: Source, **extra: Any) -> dict[str, Any]:
    return {**dataclasses.asdict(s), "dropin_eligible": dropin_eligible(s), **extra}


@app.command("add")
def add_command(
    kind: Annotated[SourceKind, typer.Option(help="Where the clip comes from.")],
    body: Annotated[Body, typer.Option(help="Body type of the main subject.")],
    bodies: Annotated[int, typer.Option(min=1, help="How many bodies are in the clip.")],
    duration: Annotated[float, typer.Option(min=0.001, help="Clip length in seconds.")],
    url: Annotated[
        str | None, typer.Option(help="Where it was found (never a TikTok/Instagram page).")
    ] = None,
    preset_id: Annotated[str | None, typer.Option(help="Higgsfield preset id, if any.")] = None,
    trend: Annotated[str | None, typer.Option(help="Trend tag.")] = None,
    credit_handle: Annotated[
        str | None, typer.Option(help="Creator handle to credit in the caption.")
    ] = None,
) -> None:
    """Catalogue a source (unchecked: not Drop-in eligible until `source check`)."""
    store = open_store()
    try:
        s = add_source(store, kind, url, body, bodies, duration, preset_id, trend, credit_handle)
    except ValueError as e:
        fail(str(e))
    emit(_source_json(s))


@app.command("check")
def check_command(
    id: Annotated[str, typer.Argument(help="Source id.")],
    watermark: Annotated[
        bool, typer.Option("--watermark/--no-watermark", help="A platform watermark is visible.")
    ],
    overlay: Annotated[
        bool, typer.Option("--overlay/--no-overlay", help="A creator handle or UI overlay is visible.")
    ],
    other_people: Annotated[
        int, typer.Option(min=0, help="Identifiable people besides the main subject.")
    ],
) -> None:
    """Record the visual checks of a source."""
    store = open_store()
    try:
        s = record_checks(store, id, watermark, overlay, other_people)
    except KeyError:
        fail(f"unknown source {id}")
    except ValueError as e:
        fail(str(e))
    emit(_source_json(s))


@app.command("flag")
def flag_command(
    id: Annotated[str, typer.Argument(help="Source id.")],
    reason: Annotated[str, typer.Option(help="What was seen, e.g. 'watermark in output frame 40'.")],
) -> None:
    """Flag a source dirty (watermark found downstream): it stops being Drop-in eligible."""
    store = open_store()
    try:
        s = flag_dirty(store, id, reason)
    except KeyError:
        fail(f"unknown source {id}")
    except ValueError as e:
        fail(str(e))
    emit(_source_json(s, flag_reason=reason))


@app.command("list")
def list_command(
    rank: Annotated[
        bool, typer.Option("--rank", help="Best usable sources first (needs --character and --mode).")
    ] = False,
    character: Annotated[str | None, typer.Option(help="With --rank: character slug.")] = None,
    mode: Annotated[Mode | None, typer.Option(help="With --rank: dropin or recreate.")] = None,
    exclude: Annotated[
        list[str] | None, typer.Option("--exclude", help="With --rank: source id to skip (repeatable).")
    ] = None,
    dropin_only: Annotated[
        bool, typer.Option("--dropin-eligible", help="Only sources that may be used for a Drop-in.")
    ] = False,
) -> None:
    """List sources; with --rank, the ranked pick list for a character and mode."""
    store = open_store()
    if not rank:
        if character or mode or exclude:
            fail("--character, --mode and --exclude only apply with --rank")
        rows = [(s, None) for s in store.list_sources()]
    else:
        if not (character and mode):
            fail("--rank needs --character and --mode")
        char = next((c for c in store.characters() if c.slug == character), None)
        if char is None:
            fail(f"unknown character {character!r}")
        rows = _rank(store, char, mode, set(exclude or ()))
    out = [
        _source_json(s, **({"median_outlier_x": m} if rank else {}))
        for s, m in rows
        if not dropin_only or dropin_eligible(s)
    ]
    emit(out)
