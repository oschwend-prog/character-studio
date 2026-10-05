"""Source library: the clips that drive our videos, their checks and their ranking.

Every driving clip (Higgsfield library imports, owner inbox clips, our own synthetic drivers) is
catalogued here with the checks that decide whether it may be used as a **Drop-in** (our
character swapped into the actual clip):

* ``has_watermark`` / ``has_overlay`` / ``has_minors`` / ``other_people`` start as ``None`` ("not checked yet");
  an unchecked source is never Drop-in eligible, and neither is a ``synthetic`` one.
* **Owner decision 2026-10-05** ("Drop-in is the default for every video"): a source may be used for a Drop-in
  when it is not synthetic, shows no platform watermark or other creator's handle (``has_watermark``), no
  burned-in text overlay (``has_overlay``) and **no child** (``has_minors``, migration 0008). ``other_people``
  (people in the background, who are replaced or left as the scene) is still recorded and shown but no longer
  blocks a Drop-in; the real star is always replaced by our character, in the visual QA of the output.
* ``flag_dirty`` is the late alarm (output QA spotted a leaked watermark): it sets
  ``has_watermark=True``, so the source drops out of Drop-in ranking at once.
* **Recreate** only borrows the moves and replaces everything else, so any source whose body
  type fits the character may drive it: watermarked, unchecked and synthetic ones included.

We never scrape or download from TikTok or Instagram: a platform page URL is not a source
(``add_source`` refuses it). Favourites (``studio.favorites``) are the lane for those links. The one owner-allowed exception
(2026-10-05) is ``studio.fetch``: the public clip of ONE approved pick, fetched once with yt-dlp into our own Storage and
deleted after posting; what it stores is a bucket path, never a platform URL.

``rank_sources`` orders the usable sources by how well the clips made from them performed
(median ``features['outlier_x']``, best first, never-measured last), newest source first on ties.

**Owner inbox.** ``ingest_inbox`` takes every video the owner dropped in ``inbox/`` (mp4, mov,
webm; other files, dotfiles and the ``done/`` folder are ignored), uploads it to the ``sources``
bucket as ``owner_inbox/<uuid><ext>``, catalogues it as an ``owner_inbox`` source and moves the
file to ``inbox/done/`` (never overwriting a file already there). The source's ``url`` and
``storage_path`` both hold that bucket path (never a platform URL). It is ``biped``, one body and
unchecked, so it is not Drop-in eligible until Claude has looked at it and run ``source check``.
A file that cannot be ingested (not a readable video, or the upload failed) stays in ``inbox/``;
the others still go through and ``IngestError`` reports both.

**The owner's own clip for a pick.** A Drop-in needs the actual video file, and we never download from TikTok or
Instagram, so the owner attaches it on the terminal's Make-it sheet: the browser uploads it to bucket ``sources`` at
``owner/<pick id>/<timestamp>.<ext>`` and the ``studio.attach_clip`` RPC (migration 0008) stores that path as
``proposal.owner_clip_path``. ``ingest_owner_clip`` (``studio source ingest-owner --pick <id>``) then reads that object
from our own Storage, probes it (duration), and catalogues it as an ``owner_inbox`` source with ``storage_path``
and the pick's creator as ``credit_handle``, unchecked (it is not Drop-in eligible until the visual check) and
links the pick (``source_id``). Idempotent: the same path is one source, shared by a "Both" sibling pick.

**Trim before generating** (owner decision 2026-10-05: Genjutsu is paid per second). ``trim_source`` (``studio source
trim <id> --start S --duration D [--file LOCAL]``) cuts the best 6-9 s window (16 s at most) out of a source with
ffmpeg (free, audio kept: a Drop-in keeps the original clip audio) and catalogues the result as a new
``owner_inbox`` source in Storage, ready for ``source url`` and Higgsfield's ``media_import_url``. It inherits the
parent's checks (watermark, overlay, people, children), credit handle, trend and body, so look at the whole clip
first, then trim. A source that is not in Storage (a Genjutsu library one) is trimmed from ``--file``, its
downloaded preview. The parent is left alone.

**Fetching the clip of an approved pick** is ``studio.fetch`` (``studio source fetch --pick <id>``, and ``studio source purge
--clip <id>`` to delete it again after posting): see that module for the rules (approved picks only, one at a time,
public, no login, yt-dlp failure = the pick becomes a Recreate). The result is an ordinary unchecked ``owner_inbox`` source.

**Looking at a clip before it is used** (owner request 2026-10-05). ``analyze_source`` (``studio source analyze <source id |
file> [--out sheet.png]``) runs the free local analysis of ``studio.media.analyze`` on a file or on a source in Storage
(downloaded to a temporary folder and removed again): motion energy per half second, cuts, the beat, the best 6-9 s window and
a 3 x 3 contact sheet (default ``renders/<source id or file name>/analysis.png``), as JSON. The agent looks at the sheet
(people, subject, camera, watermark, overlay, children), records the checks with ``source check`` and the clip check with
``fav mark --analysis-file``, and trims to the window.

**Handing a stored source to Higgsfield.** ``signed_source_url`` signs a source that lives in Storage
(``storage_path`` in the ``sources`` bucket: an owner inbox clip) for ``expires_s`` seconds (default one
hour), the URL the daily run gives to ``media_import_url``. ``studio source url <id> [--expires N]``
prints that URL and nothing else. A library or synthetic source has no ``storage_path``: its ``url`` is
already something Higgsfield can fetch.

CLI (``studio source ...``) prints JSON on stdout (``url`` prints the bare URL); exit 2 for anything the
caller must fix.
"""

from __future__ import annotations

import dataclasses
import math
import re
import shutil
import statistics
import tempfile
import uuid
from enum import Enum
from pathlib import Path
from typing import Annotated, Any, TypeVar
from urllib.parse import urlsplit

import typer

from studio.cli_support import EXIT_USAGE, emit, fail, open_storage, open_store, text_option
from studio.media.analyze import AnalysisError, analyze_clip
from studio.media.clipwork import ClipworkError, trim_clip
from studio.media.qa import QAError, probe
from studio.models import Body, Character, Mode, Source, SourceKind
from studio.storage import Storage, StorageError
from studio.store import Store

# Hosts we never take a source from; subdomains count (www., m., vm., vt., ...). Includes the platforms'
# video CDNs: a file served from one is a download from the platform, with its watermark and soundtrack.
PLATFORM_DOMAINS = frozenset({
    "tiktok.com", "instagram.com", "vm.tiktok.com", "instagr.am",
    "tiktokcdn.com", "tiktokv.com", "cdninstagram.com", "fbcdn.net",
})  # fmt: skip

# The owner's drop folder: resolved from the package location, never from the working directory.
DEFAULT_INBOX = Path(__file__).resolve().parents[1] / "inbox"
RENDERS_DIR = Path(__file__).resolve().parents[1] / "renders"  # never in git: where an analysis puts its contact sheet
INBOX_VIDEO_SUFFIXES = frozenset({".mp4", ".mov", ".webm"})
SOURCES_BUCKET = "sources"
INBOX_PREFIX = "owner_inbox"
DEFAULT_URL_EXPIRES_S = 3600
# What the terminal's "Attach clip" writes: bucket sources, owner/<pick id>/<file>; the sheet allows 60 s.
OWNER_CLIP_PATH = re.compile(r"owner/[0-9a-fA-F-]{36}/[^/\s]+")
OWNER_CLIP_MAX_S = 60.0

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
    """May this source be used for a Drop-in? Not synthetic, and the three blocking checks were run and are clean.

    Blocking: ``has_watermark``, ``has_overlay`` and ``has_minors`` must each be ``False`` (``None`` = not
    checked yet = not eligible). ``other_people`` does not gate any more (owner decision 2026-10-05).
    """
    return (
        s.kind is not SourceKind.synthetic
        and s.has_watermark is False
        and s.has_overlay is False
        and s.has_minors is False
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
    storage_path: str | None = None,
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
            storage_path=storage_path,
        )
    )


def record_checks(
    store: Store,
    id: str,
    has_watermark: bool,
    has_overlay: bool,
    other_people: int,
    has_minors: bool,
) -> Source:
    """Store the result of the visual checks (6 frames: watermark, overlay, other people, a child).

    ``has_minors`` has no default on purpose: a check that forgets the child question must fail loudly,
    never record a source as clean. People in the background (``other_people``) are only counted.
    """
    if other_people < 0:
        raise ValueError(f"other_people must be 0 or more, got {other_people!r}")
    return store.update_source(
        id,
        has_watermark=bool(has_watermark),
        has_overlay=bool(has_overlay),
        other_people=other_people,
        has_minors=bool(has_minors),
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
    with store.transaction():  # one connection for the source list and every per-source clip read
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


# ---- owner inbox -------------------------------------------------------------------------------


class IngestError(RuntimeError):
    """Some inbox files could not be ingested. ``ingested`` is what did go through, ``problems`` says
    which files stayed in the inbox and why (one ``"<file>: <reason>"`` line each)."""

    def __init__(self, problems: list[str], ingested: list[Source]) -> None:
        super().__init__("; ".join(problems))
        self.problems = problems
        self.ingested = ingested


def _is_inbox_video(path: Path) -> bool:
    return (
        path.is_file()
        and not path.name.startswith(".")  # .DS_Store, macOS ._sidecars
        and path.suffix.lower() in INBOX_VIDEO_SUFFIXES
    )


def _move_to_done(path: Path) -> None:
    done = path.parent / "done"
    done.mkdir(exist_ok=True)
    dest, n = done / path.name, 1
    while dest.exists():  # the same file name dropped twice: keep both
        n += 1
        dest = done / f"{path.stem}-{n}{path.suffix}"
    shutil.move(path, dest)


def ingest_inbox(store: Store, storage: Storage, inbox_dir: Path | str) -> list[Source]:
    """Upload, catalogue and file away every video in ``inbox_dir``; the new sources, name order.

    Each file is probed (``studio.media.qa.probe``) before anything is uploaded, uploaded to
    bucket ``sources`` at ``owner_inbox/<uuid4><ext>``, recorded as an ``owner_inbox`` source
    (``biped``, 1 body, checks left ``None``) and only then moved to ``done/``. A missing folder
    holds nothing. Raises ``IngestError`` after the whole folder was handled if any file stayed.
    """
    inbox = Path(inbox_dir)
    if not inbox.is_dir():
        return []
    ingested: list[Source] = []
    problems: list[str] = []
    for path in sorted(p for p in inbox.iterdir() if _is_inbox_video(p)):
        try:
            duration = probe(path, loudness=False).duration_s
        except QAError as e:
            problems.append(f"{path.name}: {e}")
            continue
        if not duration > 0:
            problems.append(f"{path.name}: the video has no readable duration")
            continue
        key = f"{INBOX_PREFIX}/{uuid.uuid4()}{path.suffix.lower()}"
        try:
            storage.upload(SOURCES_BUCKET, key, path)
        except StorageError as e:
            problems.append(f"{path.name}: {e}")
            continue
        source = add_source(
            store, SourceKind.owner_inbox, key, Body.biped, 1, duration, storage_path=key
        )
        ingested.append(source)
        try:
            _move_to_done(path)
        except OSError as e:
            problems.append(
                f"{path.name}: ingested as source {source.id} but could not be moved to done/ ({e}); "
                "move it by hand or the next run ingests it again"
            )
    if problems:
        raise IngestError(problems, ingested)
    return ingested


def ingest_owner_clip(
    store: Store, storage: Storage, pick_id: str, *, body: Body | str = Body.biped, bodies: int = 1
) -> Source:
    """Catalogue the clip the owner attached to a pick as an ``owner_inbox`` source and link the pick to it.

    ``KeyError`` for an unknown pick; ``ValueError`` for a pick with no ``owner_clip_path``, a path the terminal
    could not have written, a file that is not a readable video or is longer than 60 s; ``StorageError`` when
    the object is not in the ``sources`` bucket. Idempotent (see the module doc).
    """
    pick = store.get_favorite(pick_id)
    if pick is None:
        raise KeyError(pick_id)
    path = pick.proposal.get("owner_clip_path")
    if not isinstance(path, str) or not path:
        raise ValueError(f"no clip attached to pick {pick_id}: the owner attaches it on the Make-it sheet")
    if not OWNER_CLIP_PATH.fullmatch(path):
        raise ValueError(f"owner_clip_path {path!r} is not a path the terminal writes (owner/<pick id>/<file>)")
    source = next(iter(store.list_sources(storage_path=path)), None)
    if source is None:
        with tempfile.TemporaryDirectory(prefix="studio-owner-clip-") as tmp:
            local = storage.download(SOURCES_BUCKET, path, Path(tmp) / Path(path).name)
            try:
                duration = probe(local, loudness=False).duration_s
            except QAError as e:
                raise ValueError(f"the attached clip is not a readable video: {e}") from None
        if not duration > 0:
            raise ValueError("the attached clip is not a readable video: it has no duration")
        if duration > OWNER_CLIP_MAX_S + 1:
            raise ValueError(f"the attached clip is {duration:.0f} s long: the sheet takes at most {OWNER_CLIP_MAX_S:.0f} s")
        source = add_source(
            store, SourceKind.owner_inbox, path, body, bodies, duration,
            credit_handle=pick.creator_handle, storage_path=path,
        )
    if pick.source_id != source.id:
        store.update_favorite(pick.id, source_id=source.id)
    return source


def trim_source(
    store: Store,
    storage: Storage,
    source_id: str,
    start_s: float,
    duration_s: float,
    *,
    file: Path | str | None = None,
    crop_x: float | None = None,
) -> Source:
    """Cut a window out of a source and catalogue it as a new ``owner_inbox`` source (see the module doc).

    ``KeyError`` for an unknown source; ``ValueError`` for a window that makes no sense, a source that is not in
    Storage (and no ``file``), or a missing ``file``; ``QAError`` / ``ClipworkError`` / ``StorageError`` when the
    clip cannot be read, cut or stored. Nothing is catalogued unless the whole job worked.
    """
    parent = next(iter(store.list_sources(id=source_id)), None)
    if parent is None:
        raise KeyError(source_id)
    with tempfile.TemporaryDirectory(prefix="studio-trim-source-") as tmp:
        work = Path(tmp)
        if file is not None:
            local = Path(file)
            if not local.is_file():
                raise ValueError(f"no such file: {local}")
        elif parent.storage_path:
            local = storage.download(SOURCES_BUCKET, parent.storage_path, work / f"parent{Path(parent.storage_path).suffix or '.mp4'}")
        else:
            raise ValueError(
                f"source {source_id} is not in Storage (a library source is used through its own url): "
                "download its preview and pass it with --file"
            )
        trimmed = trim_clip(local, work / "window.mp4", start_s, duration_s, crop_x=crop_x)
        seconds = probe(trimmed, loudness=False).duration_s
        key = f"{INBOX_PREFIX}/{uuid.uuid4()}.mp4"
        storage.upload(SOURCES_BUCKET, key, trimmed)
    return store.add_source(
        Source(
            kind=SourceKind.owner_inbox, url=key, storage_path=key, preset_id=parent.preset_id, body=parent.body,
            bodies=parent.bodies, duration_s=seconds, has_watermark=parent.has_watermark, has_overlay=parent.has_overlay,
            other_people=parent.other_people, has_minors=parent.has_minors, trend=parent.trend,
            credit_handle=parent.credit_handle,
        )
    )


def analyze_source(
    store: Store | None, storage: Storage | None, target: str, out: Path | str | None = None
) -> dict[str, Any]:
    """The local analysis of ``target``: a video file, or the id of a source that lives in Storage.

    A file needs neither the database nor Storage (``store`` and ``storage`` may be None). ``KeyError`` for an id that names
    no source; ``ValueError`` for something that is neither a file nor an id, for a source
    that is not in Storage (a library source: pass its downloaded preview as a file), and a bad sheet extension;
    ``QAError`` / ``AnalysisError`` / ``StorageError`` when the clip cannot be read, analysed or fetched.
    """
    local = Path(target)
    if local.is_file():
        source_id, name = None, local.stem
    else:
        try:
            source_id = str(uuid.UUID(target))
        except ValueError:
            raise ValueError(f"{target!r} is neither a video file nor a source id") from None
        if store is None or storage is None:
            raise ValueError(f"source {source_id}: the database and Storage are needed to fetch it")
        source = next(iter(store.list_sources(id=source_id)), None)
        if source is None:
            raise KeyError(target)
        if not source.storage_path:
            raise ValueError(
                f"source {source_id} is not in Storage (a library source is used through its own url): "
                "download its preview and pass the file instead"
            )
        name = source_id
    sheet = Path(out) if out is not None else RENDERS_DIR / name / "analysis.png"
    if source_id is None:
        result = analyze_clip(local, sheet)
    else:
        with tempfile.TemporaryDirectory(prefix="studio-analyze-") as tmp:
            suffix = Path(source.storage_path).suffix or ".mp4"
            fetched = storage.download(SOURCES_BUCKET, source.storage_path, Path(tmp) / f"source{suffix}")
            result = analyze_clip(fetched, sheet)
            result["file"] = source.storage_path  # the Storage key, not the temporary copy that is gone now
    return {"target": target, "source_id": source_id, **result}


def signed_source_url(
    store: Store, storage: Storage, source_id: str, expires_s: int = DEFAULT_URL_EXPIRES_S
) -> str:
    """A time-limited URL for a source stored in the ``sources`` bucket.

    ``KeyError`` for an unknown source; ``ValueError`` for a source with no ``storage_path`` or a
    non-positive ``expires_s``; ``StorageError`` when the object is missing or the signing fails.
    """
    if expires_s <= 0:
        raise ValueError(f"expires must be a positive number of seconds, got {expires_s!r}")
    source = next((s for s in store.list_sources() if s.id == source_id), None)
    if source is None:
        raise KeyError(source_id)
    if not source.storage_path:
        raise ValueError(
            f"source {source_id} has no storage_path: it is not in Storage "
            "(a library or synthetic source is used through its own url)"
        )
    return storage.signed_url(SOURCES_BUCKET, source.storage_path, expires_s)


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
    trend: Annotated[str | None, typer.Option(help="Trend tag (a short token; free text: --trend-file).")] = None,
    trend_file: Annotated[
        Path | None,
        typer.Option("--trend-file", help="The trend tag, read from a file (use for any text from a creator or a tool)."),
    ] = None,
    credit_handle: Annotated[
        str | None, typer.Option(help="Creator handle to credit in the caption.")
    ] = None,
) -> None:
    """Catalogue a source (unchecked: not Drop-in eligible until `source check`)."""
    trend = text_option(trend, trend_file, "trend")
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
        bool,
        typer.Option("--watermark/--no-watermark", help="A platform watermark or another creator's handle is visible."),
    ],
    overlay: Annotated[
        bool, typer.Option("--overlay/--no-overlay", help="A burned-in text overlay is visible.")
    ],
    other_people: Annotated[
        int,
        typer.Option(min=0, help="People besides the main subject (background people are fine: only counted)."),
    ],
    minors: Annotated[
        bool, typer.Option("--minors/--no-minors", help="A child is visible anywhere in the clip (blocks the Drop-in).")
    ],
) -> None:
    """Record the visual checks of a source (watermark, overlay, other people, a child)."""
    store = open_store()
    try:
        s = record_checks(store, id, watermark, overlay, other_people, minors)
    except KeyError:
        fail(f"unknown source {id}")
    except ValueError as e:
        fail(str(e))
    emit(_source_json(s))


@app.command("flag")
def flag_command(
    id: Annotated[str, typer.Argument(help="Source id.")],
    reason: Annotated[
        str | None, typer.Option(help="What was seen, e.g. 'watermark in output frame 40'.")
    ] = None,
    reason_file: Annotated[
        Path | None, typer.Option("--reason-file", help="The same, read from a file (use for free text).")
    ] = None,
) -> None:
    """Flag a source dirty (watermark found downstream): it stops being Drop-in eligible."""
    reason = text_option(reason, reason_file, "reason") or ""
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


@app.command("ingest-inbox")
def ingest_inbox_command(
    inbox: Annotated[
        Path | None,
        typer.Option(help="Folder to ingest (default: the repo's inbox/, whatever the cwd)."),
    ] = None,
) -> None:
    """Upload the videos in the owner inbox as unchecked `owner_inbox` sources, then file them in done/."""
    store = open_store()
    storage = open_storage()
    if inbox is not None and not inbox.is_dir():
        fail(f"no such folder: {inbox}")
    try:
        made = ingest_inbox(store, storage, DEFAULT_INBOX if inbox is None else inbox)
    except IngestError as e:
        emit([_source_json(s) for s in e.ingested])
        for problem in e.problems:
            typer.echo(f"error: {problem}", err=True)
        raise typer.Exit(EXIT_USAGE) from None
    emit([_source_json(s) for s in made])


@app.command("ingest-owner")
def ingest_owner_command(
    pick: Annotated[str, typer.Option("--pick", help="Pick id: its owner_clip_path (Make-it > Attach clip) is read.")],
    body: Annotated[Body, typer.Option(help="Body type of the main performer in the clip.")] = Body.biped,
    bodies: Annotated[int, typer.Option(min=1, help="How many bodies are in the clip.")] = 1,
) -> None:
    """Catalogue the clip the owner attached to a pick as an unchecked `owner_inbox` source and link the pick."""
    store = open_store()
    storage = open_storage()
    try:
        s = ingest_owner_clip(store, storage, pick, body=body, bodies=bodies)
    except KeyError:
        fail(f"unknown pick {pick}")
    except (ValueError, StorageError) as e:
        fail(str(e))
    emit(_source_json(s, pick_id=pick))


@app.command("trim")
def trim_command(
    id: Annotated[str, typer.Argument(help="Source id to cut a window from.")],
    start: Annotated[float, typer.Option("--start", help="Where the window begins, in seconds.")],
    duration: Annotated[
        float,
        typer.Option("--duration", help="Window length in seconds (classics 12-14 s, other clips 7-9 s, 16 s the maximum)."),
    ],
    file: Annotated[
        Path | None,
        typer.Option("--file", help="The clip to cut, for a source that is not in Storage (a downloaded library preview)."),
    ] = None,
    crop_x: Annotated[
        float | None,
        typer.Option(
            "--crop-x",
            help="For a landscape clip: cut the full-height 9:16 window centred at this fraction of the width "
            "(0 = left edge, 0.5 = middle, 1 = right edge), around the star.",
        ),
    ] = None,
) -> None:
    """Cut the best window out of a source (audio kept) as a new `owner_inbox` source: what Genjutsu is given."""
    store = open_store()
    storage = open_storage()
    try:
        child = trim_source(store, storage, id, start, duration, file=file, crop_x=crop_x)
    except KeyError:
        fail(f"unknown source {id}")
    except (ValueError, QAError, ClipworkError, StorageError) as e:
        fail(str(e))
    emit(_source_json(child, parent_id=id))


@app.command("analyze")
def analyze_command(
    target: Annotated[str, typer.Argument(help="A source id (a clip in Storage) or the path of a video file.")],
    out: Annotated[
        Path | None,
        typer.Option("--out", help="Where to write the 3 x 3 contact sheet (.png or .jpg; default renders/<id>/analysis.png)."),
    ] = None,
) -> None:
    """Analyse a clip for free: motion, cuts, beat, the best 6-9 s window and a contact sheet to look at (JSON)."""
    on_disk = Path(target).is_file()  # a file needs no database and no Storage
    store = None if on_disk else open_store()
    storage = None if on_disk else open_storage()
    try:
        emit(analyze_source(store, storage, target, out))
    except KeyError:
        fail(f"unknown source {target}")
    except (ValueError, QAError, AnalysisError, StorageError) as e:
        fail(str(e))


@app.command("url")
def url_command(
    id: Annotated[str, typer.Argument(help="Source id (an owner inbox clip stored in Storage).")],
    expires: Annotated[
        int, typer.Option(min=1, help="Seconds the link stays valid.")
    ] = DEFAULT_URL_EXPIRES_S,
) -> None:
    """Print a signed URL for a stored source: the input of Higgsfield's media_import_url."""
    store = open_store()
    storage = open_storage()
    try:
        url = signed_source_url(store, storage, id, expires)
    except KeyError:
        fail(f"unknown source {id}")
    except (ValueError, StorageError) as e:
        fail(str(e))
    typer.echo(url)
