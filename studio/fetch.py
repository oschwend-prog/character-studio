"""The clip of an approved pick: fetched once, used, and deleted again (owner decisions 2026-10-05).

A Drop-in needs the actual video file. The owner allowed ``yt-dlp`` for it, within these limits (all enforced here):

* **Approved picks only**: a pick must be ``approved`` or ``analysed``. A new, skipped, queued or made one is refused before
  anything is downloaded, and so is a Genjutsu gallery pick (it has no page), a pick the owner wants as a Recreate, and one
  the owner attached a clip to (``source ingest-owner`` takes that).
* **One clip at a time**: ``studio source fetch --pick <id>`` takes one pick; the CLI refuses a second ``--pick``. The one
  URL handed to yt-dlp is the pick's canonical TikTok / Instagram / YouTube link, after ``--``.
* **Public, no login, no cookies**: the command is explicit (``--ignore-config --no-cookies --no-cookies-from-browser``, no
  username, password, netrc or proxy) and the tests pin the list of what must never appear in it.
* **Where it goes**: ``inbox/fetched/<pick id>.mp4`` (gitignored), probed (a readable video of at most 3 minutes), uploaded to
  our Storage bucket ``sources`` as an ``owner_inbox`` source (``owner_inbox/<uuid>.mp4``, credit handle = the pick's
  creator, checks unset: it is not Drop-in eligible until it has been looked at) and linked to the pick (``source_id``). The
  pick's ``proposal['fetched']`` records the source, the storage key and the time: that is what ``purge`` acts on.
* **When yt-dlp cannot do it** (not installed, a login wall, a private or removed video, a timeout, no usable file) the
  pick is marked ``recreate`` automatically: ``proposal['mode'] = 'recreate'`` and ``proposal['fetch_failed']`` says why.
  What the owner chose (``owner_mode``) is kept as chosen: the run's effective-mode rule makes it a Recreate because there is
  no usable source. The CLI exits 1 with that in its JSON. A failure of OUR Storage is not that: it is a ``StorageError``
  (exit 2) and the pick is left alone.
* **Idempotent and shared**: a pick that already carries a live fetched source is not downloaded again, and the other
  character's pick of the same video (the terminal's "Both") reuses the one download.

``purge_clip`` (``studio source purge --clip <id>``) deletes what was fetched once the clip's master is approved, scheduled
or posted (or the clip was dropped): the local file, the Storage object of the fetched source and of the trimmed one made
from it, and their contact sheets under ``renders/``. A source object another unfinished clip or pick still needs stays
until that one is done. It only ever touches what carries a ``fetched`` marker: the owner's own attached clips are theirs.
A pick that is itself still to be made (returned to ``approved`` after its clip was dropped) keeps its fetched clip for the
next attempt. ``studio source purge --pending`` is the daily tidy-up: every clip that is done and every skipped pick that
fetched one, in one sweep. Idempotent: a second run finds nothing to do.
"""

from __future__ import annotations

import subprocess
import uuid
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Annotated, Any

import typer

from studio import sources as sources_module
from studio.cli_support import emit, fail, open_storage, open_store
from studio.config import now_london
from studio.favorites import GALLERY_PLATFORM, is_gallery, parse_video_url
from studio.media.qa import QAError, probe
from studio.models import Body, Favorite, Source
from studio.sources import INBOX_PREFIX, SOURCES_BUCKET, _source_json, add_source
from studio.storage import Storage, StorageError
from studio.store import Store

FETCHED_DIR = Path(__file__).resolve().parents[1] / "inbox" / "fetched"  # gitignored with the rest of inbox/
FETCH_MAX_SECONDS = 180.0
FETCH_TIMEOUT_S = 300.0
FETCH_MAX_FILESIZE = "200M"
FETCHABLE_STATUSES = frozenset({"approved", "analysed"})
FETCH_PLATFORMS = frozenset({"tiktok", "instagram", "youtube"})
# A clip whose fetched source may go: its master is approved (or booked, or out), or it was dropped.
PURGE_CLIP_STATES = frozenset({"approved", "scheduled", "posted", "dropped"})
# A pick in one of these is still to be made (or made again): what it fetched stays for the next attempt.
TO_BE_MADE_STATUSES = frozenset({"new", "approved", "analysed"})

Runner = Callable[[Sequence[str]], "subprocess.CompletedProcess[str]"]


class FetchFailed(RuntimeError):
    """yt-dlp could not produce a usable clip: the pick falls back to a Recreate."""


def ytdlp_command(url: str, template: str) -> list[str]:
    """The whole yt-dlp command line for one public clip (never a shell string: a list of arguments)."""
    return [
        "yt-dlp",
        "--ignore-config",  # nothing from the owner's own yt-dlp configuration (cookies, accounts, proxies)
        "--no-cookies", "--no-cookies-from-browser",
        "--no-playlist", "--no-warnings", "--no-progress",
        "--socket-timeout", "30", "--retries", "2",
        "--max-filesize", FETCH_MAX_FILESIZE,
        "--match-filters", f"duration<={int(FETCH_MAX_SECONDS)}",
        "-f", "bv*[height<=1080]+ba/b[height<=1080]/b",
        "--merge-output-format", "mp4", "--remux-video", "mp4",
        "-o", template,
        "--", url,
    ]  # fmt: skip


def _run_ytdlp(cmd: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(cmd), capture_output=True, text=True, encoding="utf-8", errors="replace",
        stdin=subprocess.DEVNULL, timeout=FETCH_TIMEOUT_S, check=False,
    )  # fmt: skip


def _tail(text: str, lines: int = 2, limit: int = 300) -> str:
    return " | ".join(text.strip().splitlines()[-lines:])[:limit] or "no output"


def _live_fetched_source(store: Store, pick: Favorite) -> Source | None:
    """The source this pick's own fetch made, while its Storage object is still there (not purged)."""
    marker = pick.proposal.get("fetched")
    if not isinstance(marker, dict) or "purged_at" in marker or not pick.source_id:
        return None
    source = next(iter(store.list_sources(id=pick.source_id)), None)
    return source if source is not None and source.storage_path else None


def _result(pick: Favorite, source: Source, file: Path | None, *, already: bool) -> dict[str, Any]:
    return {
        **_source_json(source), "fetched": True, "already": already, "pick_id": pick.id, "source_id": source.id,
        "file": str(file) if file is not None and file.is_file() else None,
    }  # fmt: skip


def _fall_back_to_recreate(store: Store, pick: Favorite, reason: str) -> dict[str, Any]:
    proposal = {**pick.proposal, "mode": "recreate", "fetch_failed": {"reason": reason[:300], "at": now_london().isoformat()}}
    store.update_favorite(pick.id, proposal=proposal)
    return {"ok": False, "fetched": False, "pick_id": pick.id, "pick_marked": "recreate", "reason": reason[:300]}


def fetch_pick_clip(
    store: Store,
    storage: Storage,
    pick_id: str,
    *,
    runner: Runner | None = None,
    out_dir: Path | str | None = None,
    body: Body | str = Body.biped,
    bodies: int = 1,
) -> dict[str, Any]:
    """Fetch the clip of one approved pick (see the module doc); the JSON-ready result.

    ``KeyError`` for an unknown pick; ``ValueError`` for a pick that may not be fetched (status, gallery, owner choices, a
    URL that is not TikTok / Instagram / YouTube); ``StorageError`` when our own Storage refuses the upload. A yt-dlp
    failure is not an exception: the pick is marked ``recreate`` and ``{"fetched": False, "pick_marked": "recreate", ...}``
    comes back.
    """
    run = runner if runner is not None else _run_ytdlp
    folder = Path(out_dir) if out_dir is not None else FETCHED_DIR
    pick = store.get_favorite(pick_id)
    if pick is None:
        raise KeyError(pick_id)
    if pick.status not in FETCHABLE_STATUSES:
        raise ValueError(f"pick {pick.id} is {pick.status}: only an approved pick is fetched")
    if pick.platform == GALLERY_PLATFORM or is_gallery(pick.proposal):
        raise ValueError(f"pick {pick.id} is a Genjutsu gallery clip: it has no page to fetch (its preview is its source)")
    if pick.proposal.get("owner_mode") == "recreate":
        raise ValueError(f"pick {pick.id}: the owner chose Recreate, so no clip is needed")
    if pick.proposal.get("owner_clip_path"):
        raise ValueError(f"pick {pick.id}: the owner attached a clip: use `source ingest-owner --pick {pick.id}`")
    platform, canonical = parse_video_url(pick.url)
    if platform not in FETCH_PLATFORMS:  # parse_video_url only knows these three; kept explicit for the next platform
        raise ValueError(f"{pick.url!r} is not a supported video URL")

    if (existing := _live_fetched_source(store, pick)) is not None:
        return _result(pick, existing, folder / f"{pick.id}.mp4", already=True)
    for other in store.list_favorites(url=canonical):  # the other character's pick of the same video
        if other.id != pick.id and (shared := _live_fetched_source(store, other)) is not None:
            marker = {**other.proposal["fetched"]}
            store.update_favorite(pick.id, source_id=shared.id, proposal={**pick.proposal, "fetched": marker})
            return _result(pick, shared, folder / f"{other.id}.mp4", already=True)

    dest = folder / f"{pick.id}.mp4"
    folder.mkdir(parents=True, exist_ok=True)

    def clear() -> None:
        for leftover in folder.glob(f"{pick.id}.*"):  # the clip, a .part, a .ytdl: nothing half-done stays
            leftover.unlink(missing_ok=True)

    try:
        try:
            done = run(ytdlp_command(canonical, str(folder / f"{pick.id}.%(ext)s")))
        except FileNotFoundError:
            raise FetchFailed("yt-dlp is not installed") from None
        except subprocess.TimeoutExpired:
            raise FetchFailed(f"yt-dlp timed out after {FETCH_TIMEOUT_S:.0f} s") from None
        if done.returncode != 0:
            raise FetchFailed(f"yt-dlp failed ({done.returncode}): {_tail(done.stderr)}")
        if not dest.is_file():
            raise FetchFailed("yt-dlp produced no video (a private, removed or too long clip, or a login wall)")
        try:
            seconds = probe(dest, loudness=False).duration_s
        except QAError as e:
            raise FetchFailed(f"the download is not a readable video: {e}") from None
        if not seconds > 0:
            raise FetchFailed("the download has no readable duration")
        if seconds > FETCH_MAX_SECONDS:
            raise FetchFailed(f"the clip is {seconds:.0f} s long: at most {FETCH_MAX_SECONDS:.0f} s are fetched")
    except FetchFailed as e:
        clear()
        return _fall_back_to_recreate(store, pick, str(e))

    key = f"{INBOX_PREFIX}/{uuid.uuid4()}.mp4"
    try:
        storage.upload(SOURCES_BUCKET, key, dest)
    except (StorageError, OSError):
        clear()
        raise
    source = add_source(
        store, "owner_inbox", key, body, bodies, seconds, credit_handle=pick.creator_handle, storage_path=key
    )
    marker = {"source_id": source.id, "storage_path": key, "at": now_london().isoformat()}
    store.update_favorite(pick.id, source_id=source.id, proposal={**pick.proposal, "fetched": marker})
    return _result(pick, source, dest, already=False)


# ---- purge ----------------------------------------------------------------------------------------------------------------


def _done_pick(store: Store, pick: Favorite) -> bool:
    """Is nothing left to make from this pick (so its fetched clip is not needed any more)?"""
    marker = pick.proposal.get("fetched")
    if isinstance(marker, dict) and "purged_at" in marker:
        return True
    if pick.status == "skipped":
        return True
    clip = store.get_clip(pick.clip_id) if pick.clip_id else None
    return clip is not None and clip.state.value in PURGE_CLIP_STATES


def _still_needed(store: Store, source_id: str | None, pick: Favorite, clip_id: str) -> bool:
    """Does another unfinished pick or clip still use this source?"""
    if source_id is None:
        return False
    for other in store.list_favorites():
        if other.id == pick.id:
            continue
        marker = other.proposal.get("fetched")
        uses = other.source_id == source_id or (isinstance(marker, dict) and marker.get("source_id") == source_id)
        if uses and not _done_pick(store, other):
            return True
    return any(c.id != clip_id and c.state.value not in PURGE_CLIP_STATES for c in store.list_clips(source_id=source_id))


def _blank_result(**extra: Any) -> dict[str, Any]:
    return {"files_deleted": [], "storage_deleted": [], "storage_kept": [], "sheets_deleted": [], **extra}


def _purge_pick(
    store: Store, storage: Storage, pick: Favorite, marker: dict[str, Any], clip: Any, folder: Path, renders: Path, out: dict[str, Any]
) -> None:
    """Delete what one pick fetched: its local file and the Storage objects (and sheets) nothing else needs any more."""
    local = folder / f"{pick.id}.mp4"
    if local.is_file():
        local.unlink()
        out["files_deleted"].append(str(local))
    targets: list[tuple[str | None, str | None]] = [(marker.get("source_id"), marker.get("storage_path"))]
    if clip is not None and clip.source_id and clip.source_id != marker.get("source_id"):  # the trimmed child it was made from
        child = next(iter(store.list_sources(id=clip.source_id)), None)
        if child is not None and child.storage_path:
            targets.append((child.id, child.storage_path))
    for source_id, key in targets:
        if not key:
            continue
        if _still_needed(store, source_id, pick, clip.id if clip is not None else None):
            out["storage_kept"].append(key)
            continue
        storage.delete(SOURCES_BUCKET, key)
        out["storage_deleted"].append(key)
        if source_id is not None:
            store.update_source(source_id, storage_path=None)
            sheet = renders / source_id / "analysis.png"
            if sheet.is_file():
                sheet.unlink()
                out["sheets_deleted"].append(str(sheet))
                try:
                    sheet.parent.rmdir()  # only when nothing else is in it
                except OSError:
                    pass
    store.update_favorite(pick.id, proposal={**pick.proposal, "fetched": {**marker, "purged_at": now_london().isoformat()}})


def _live_marker(pick: Favorite) -> dict[str, Any] | None:
    marker = pick.proposal.get("fetched")
    return marker if isinstance(marker, dict) and "purged_at" not in marker else None


def purge_clip(
    store: Store,
    storage: Storage,
    clip_id: str,
    *,
    fetched_dir: Path | str | None = None,
    renders_dir: Path | str | None = None,
) -> dict[str, Any]:
    """Delete what was fetched for the pick(s) this clip was made from (see the module doc); the JSON-ready result.

    ``KeyError`` for an unknown clip; ``ValueError`` for a clip still being made or judged (``PURGE_CLIP_STATES`` are the ones
    that may go); ``StorageError`` when Storage refuses a delete (nothing is marked purged then, so a rerun finishes the job).
    A pick of the clip that is itself still to be made (``new``, ``approved`` or ``analysed``: it was returned after the clip
    was dropped) keeps its fetched clip for the next attempt.
    """
    folder = Path(fetched_dir) if fetched_dir is not None else FETCHED_DIR
    renders = Path(renders_dir) if renders_dir is not None else sources_module.RENDERS_DIR
    clip = store.get_clip(clip_id)
    if clip is None:
        raise KeyError(clip_id)
    if clip.state.value not in PURGE_CLIP_STATES:
        raise ValueError(
            f"clip {clip.id} is {clip.state.value}: what was fetched for it goes once its master is approved or posted "
            "(or the clip is dropped)"
        )
    picks = [p for p in store.list_favorites(clip_id=clip.id) if _live_marker(p) is not None]
    pending = [p for p in picks if p.status not in TO_BE_MADE_STATUSES]
    out = _blank_result(clip_id=clip.id, pick_ids=[p.id for p in pending], already=not pending)
    if len(pending) < len(picks):
        out["kept_for_retry"] = [p.id for p in picks if p.status in TO_BE_MADE_STATUSES]
    for pick in pending:
        _purge_pick(store, storage, pick, pick.proposal["fetched"], clip, folder, renders, out)
    return out


def purge_pending(
    store: Store, storage: Storage, *, fetched_dir: Path | str | None = None, renders_dir: Path | str | None = None
) -> dict[str, Any]:
    """Purge everything that is done with, in one sweep (the daily run's tidy-up; idempotent).

    Every clip in ``PURGE_CLIP_STATES`` that still has a fetched clip to delete, and every skipped pick that fetched one
    (it will never be made). Returns ``{"clips": [<purge_clip result>...], "skipped_picks": [...], "already": bool}``.
    """
    folder = Path(fetched_dir) if fetched_dir is not None else FETCHED_DIR
    renders = Path(renders_dir) if renders_dir is not None else sources_module.RENDERS_DIR
    clip_ids: list[str] = []
    skipped: list[Favorite] = []
    for pick in store.list_favorites():
        if _live_marker(pick) is None:
            continue
        if pick.status == "skipped":
            skipped.append(pick)
        elif pick.clip_id and pick.status not in TO_BE_MADE_STATUSES and pick.clip_id not in clip_ids:
            clip = store.get_clip(pick.clip_id)
            if clip is not None and clip.state.value in PURGE_CLIP_STATES:
                clip_ids.append(clip.id)
    results = [r for cid in clip_ids if not (r := purge_clip(store, storage, cid, fetched_dir=folder, renders_dir=renders))["already"]]
    picks_done: list[dict[str, Any]] = []
    for pick in skipped:
        out = _blank_result(pick_id=pick.id)
        _purge_pick(store, storage, pick, pick.proposal["fetched"], None, folder, renders, out)
        picks_done.append(out)
    return {"clips": results, "skipped_picks": picks_done, "already": not results and not picks_done}


# ---- CLI (registered on the `source` group by studio.cli) -------------------------------------------------------------


def fetch_command(
    pick: Annotated[
        list[str] | None,
        typer.Option("--pick", help="The ONE approved pick whose clip to fetch (never a batch)."),
    ] = None,
    body: Annotated[Body, typer.Option(help="Body type of the main performer in the clip.")] = Body.biped,
    bodies: Annotated[int, typer.Option(min=1, help="How many bodies are in the clip.")] = 1,
) -> None:
    """Fetch the public clip of an approved pick with yt-dlp (no login, no cookies) and catalogue it in Storage.

    Exit 0 fetched; 1 yt-dlp could not (the pick is marked Recreate: the JSON says so); 2 refused (not approved, a gallery
    pick, more than one --pick, ...).
    """
    if not pick or len(pick) != 1:
        fail("fetch takes exactly one --pick: clips are fetched one at a time, never in bulk")
    store = open_store()
    storage = open_storage()
    try:
        result = fetch_pick_clip(store, storage, pick[0], body=body, bodies=bodies)
    except KeyError:
        fail(f"unknown pick {pick[0]}")
    except (ValueError, StorageError, OSError) as e:
        fail(str(e))
    emit(result)
    if not result["fetched"]:
        raise typer.Exit(1)


def purge_command(
    clip: Annotated[
        str | None,
        typer.Option("--clip", help="The clip whose fetched source is deleted (after its master is approved or posted)."),
    ] = None,
    pending: Annotated[
        bool,
        typer.Option("--pending", help="Sweep every clip that is done (approved, scheduled, posted, dropped) and every skipped pick."),
    ] = False,
) -> None:
    """Delete fetched clips, their Storage objects and contact sheets once the clip is approved or posted (idempotent)."""
    if (clip is None) == (not pending):
        fail("give one of --clip <id> or --pending")
    store = open_store()
    storage = open_storage()
    try:
        emit(purge_pending(store, storage) if pending else purge_clip(store, storage, clip or ""))
    except KeyError:
        fail(f"unknown clip {clip}")
    except (ValueError, StorageError) as e:
        fail(str(e))
