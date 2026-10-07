"""The owner's clips folder: videos saved into an iCloud Drive folder become drops (Terminal v2, spec section A).

The owner saves clips from the iPhone (Files, Safari downloads, Photos "Save to Files") or the Mac into one folder. ``sync_folder``
turns each new video in it into a **file drop**, exactly what ``studio drop add --file`` does (no character: the studio recommends
one after the check; ``drop.add_drop`` then ``drop.attach_file``), and moves the file into ``Added/`` so the owner sees what was
taken. ``sync_folder`` is given its store, storage, clock and iCloud fetch; the CLI command (``studio drop sync-folder``) and the
LaunchAgent that call it are elsewhere (tasks A2 and A3).

**Only the top level of the folder is read** (``Added/`` and every other sub-folder are never looked at; hidden files such as
``.DS_Store`` are not clips). What is not taken, and why (``skipped``, one ``{"file", "reason"}`` each):

* ``"in iCloud, downloading"``: the file is not on this Mac yet, so it is never hashed or uploaded (reading it would block while
  macOS downloads it inside the unattended agent). iCloud is asked to fetch it (``fetch``, ``brctl download``) and a later run
  takes it. Two shapes: a legacy placeholder (``.<name>.icloud``) and, on macOS 14+, an **evicted ("dataless") file**, which keeps
  its real name, size and mtime but has the ``SF_DATALESS`` flag in ``st_flags`` (``stat`` does not download it). Only a video
  (by extension, and under the size limit for a dataless file, whose size is the real one) is fetched, never ``notes.txt``.
* ``"still copying"``: written within the last ``SETTLE_SECONDS`` (a copy or an iCloud download still in progress).
* ``"not a video"`` / ``"over 200 MB"``: the extension and the size limit of ``drop`` (read at call time), checked BEFORE
  ``add_drop`` so a bad file never leaves an orphan ``uploading`` pick.
* ``"already added"``: its content hash (sha256) is in the ledger (the same clip copied again, or a move that failed last time):
  it only goes to ``Added/``.

**The ledger** (``clips-ledger.json`` under ``~/.local/state``, never in the repo) maps ``hash -> {"pick_id", "name", "at"}``,
written atomically (temp file + rename) after every file taken. A ledger that cannot be read stops the sync (``ValueError``)
rather than be forgotten: forgetting it would add the same clips twice.

**One file's trouble never stops the others.** A ``ValueError`` (``DropError`` included), ``StorageError`` or ``OSError`` on a file
goes to ``failed`` and the file stays where it is for the next run. The pick ``add_drop`` made for it is not left to pile up: it
is tagged with the file's hash (``drop['folder_hash']``) right after ``add_drop`` and BEFORE the upload, so even a run that is
killed from outside (``launchctl bootout``, a crash: no handler runs) leaves a pick the next run finds. The retry takes that pick up
again instead of making another; a pick that already has its clip attached (killed after the upload, before the ledger was written)
is not attached twice: the run only writes the ledger and moves the file. A move into ``Added/`` that fails after the upload is
reported in ``failed`` too, but the ledger already knows the clip: the next run only moves it. A missing or unreadable folder
raises (``OSError``): the caller reports it (iCloud signed out, macOS privacy).

``studio.drop`` is imported as a module and read at call time (``drop.CLIP_MAX_BYTES``, ``drop.add_drop``) so a test can patch it
and ``studio.drop`` may itself import this module for its CLI command.

**Around a run** (used by ``studio drop sync-folder``, the LaunchAgent every 5 minutes and the daily run): ``run_lock`` keeps two
runs from overlapping (an exclusive, non-blocking ``flock`` on ``<ledger>.lock``); ``preview_folder`` is the dry run (read-only);
``every_file_failed`` is the exit-code rule; ``nudge_cloud`` wakes the cloud check (``gh workflow run studio-drop.yml -f job=sweep``)
once something was added, and never raises.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import subprocess
import tempfile
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from studio import drop
from studio.favorites import DROP_PLATFORM
from studio.models import Favorite
from studio.storage import Storage, StorageError
from studio.store import Store

DEFAULT_FOLDER = Path.home() / "Library/Mobile Documents/com~apple~CloudDocs/ODD EYES clips"
ADDED_DIR = "Added"
DEFAULT_LEDGER = Path.home() / ".local/state/odd-eyes/clips-ledger.json"
SETTLE_SECONDS = 30  # a file written more recently than this is still being copied
ICLOUD_SUFFIX = ".icloud"  # a legacy placeholder: ``.<name>.icloud`` stands for ``<name>`` that is not downloaded yet
SF_DATALESS = 0x40000000  # st_flags of an evicted iCloud file (macOS 14+): the content is not on disk
BRCTL_TIMEOUT_S = 60
REPO_ROOT = Path(__file__).resolve().parents[1]
NUDGE_COMMAND = ["gh", "workflow", "run", "studio-drop.yml", "-f", "job=sweep"]  # the cloud check: ``studio drop sweep``
NUDGE_TIMEOUT_S = 30
_CHUNK = 1024 * 1024

Ledger = dict[str, dict[str, Any]]


def brctl_download(path: Path) -> None:
    """Ask iCloud to download ``path`` (``brctl download``). Fire and forget: errors (no ``brctl``, too slow) are ignored, the
    placeholder is simply still there on the next run."""
    try:
        subprocess.run(
            ["brctl", "download", str(path)], capture_output=True, stdin=subprocess.DEVNULL, timeout=BRCTL_TIMEOUT_S, check=False
        )
    except (OSError, subprocess.SubprocessError):
        pass


def file_hash(path: Path) -> str:
    """The sha256 of the file's content, streamed (a clip may be 200 MB)."""
    digest = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def _is_dataless(st: os.stat_result) -> bool:
    """An evicted iCloud file: real name, size and mtime, but no content on disk (macOS 14+). ``st_flags`` is macOS/BSD only."""
    return bool(getattr(st, "st_flags", 0) & SF_DATALESS)


def _is_video_name(name: str) -> bool:
    return Path(name).suffix.lower().lstrip(".") in drop.CLIP_EXTENSIONS


def _problem(path: Path, size: int) -> str | None:
    """Why this file can never be a drop (type, then size, as ``attach_file`` judges them), or None."""
    if not _is_video_name(path.name):
        return "not a video"
    if size > drop.CLIP_MAX_BYTES:
        return f"over {drop.CLIP_MAX_BYTES // (1024 * 1024)} MB"
    return None


def scan_folder(folder: Path, now: float, fetch: Callable[[Path], None]) -> tuple[list[Path], list[dict[str, str]]]:
    """The files of ``folder`` (top level only) ready to be taken, by name, and the skipped ones ``{"file", "reason"}``.
    ``now`` is epoch seconds; ``fetch(<folder>/<name>)`` is called for each video iCloud has not downloaded yet (a legacy
    ``.<name>.icloud`` placeholder or an evicted "dataless" file)."""
    ready: list[Path] = []
    skipped: list[dict[str, str]] = []
    for path in sorted(folder.iterdir()):
        if not path.is_file():  # Added/, any other folder, a broken link
            continue
        name = path.name
        if name.startswith(".") and name.endswith(ICLOUD_SUFFIX) and len(name) > len(ICLOUD_SUFFIX) + 1:
            real = name[1 : -len(ICLOUD_SUFFIX)]
            if _is_video_name(real):
                fetch(folder / real)
                skipped.append({"file": real, "reason": "in iCloud, downloading"})
            else:  # no point fetching notes.txt
                skipped.append({"file": real, "reason": "not a video"})
            continue
        if name.startswith("."):  # .DS_Store and the like are not clips
            continue
        try:
            stat = path.stat()
        except FileNotFoundError:  # taken away since the listing
            continue
        if now - stat.st_mtime < SETTLE_SECONDS:
            skipped.append({"file": name, "reason": "still copying"})
        elif (why := _problem(path, stat.st_size)) is not None:  # before any fetch: no download of what we would not take
            skipped.append({"file": name, "reason": why})
        elif _is_dataless(stat):  # evicted: asking for it is free, reading it would block on a download
            fetch(path)
            skipped.append({"file": name, "reason": "in iCloud, downloading"})
        else:
            ready.append(path)
    return ready, skipped


def _load_ledger(path: Path) -> Ledger:
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    try:
        ledger = json.loads(raw)
    except ValueError as e:
        raise ValueError(f"the clips ledger {path} is not valid JSON ({e}): fix or remove it") from e
    if not isinstance(ledger, dict):
        raise ValueError(f"the clips ledger {path} is not a JSON object: fix or remove it")
    return ledger


def _write_ledger(path: Path, ledger: Ledger) -> None:
    """Atomically: a temp file next to the ledger, then rename (its folders are created)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(ledger, f, indent=2, sort_keys=True)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _move_to_added(path: Path) -> Path:
    """Move the file into ``Added/`` beside it; a name clash gets `` (2)``, `` (3)`` ... before the extension."""
    added = path.parent / ADDED_DIR
    added.mkdir(exist_ok=True)
    target = added / path.name
    n = 2
    while target.exists():
        target = added / f"{path.stem} ({n}){path.suffix}"
        n += 1
    path.rename(target)
    return target


def _earlier_pick(store: Store, digest: str) -> Favorite | None:
    """The pick an earlier run of this very file left behind (see ``_add``): one that already has its clip attached (nothing
    left to do but the ledger) before one still ``uploading`` without a clip (to be attached now), or None."""
    waiting = None
    for f in store.list_favorites(platform=DROP_PLATFORM, origin="owner"):
        d = f.proposal.get("drop")
        if not (isinstance(d, dict) and d.get("kind") == "file" and d.get("folder_hash") == digest):
            continue
        if f.proposal.get("owner_clip_path"):
            return f
        if d.get("state") == "uploading" and waiting is None:
            waiting = f
    return waiting


def _add(store: Store, storage: Storage, path: Path, digest: str, now: datetime) -> str:
    """File the drop for this clip (no character: the studio recommends) and attach the file; the pick's id. The new pick is
    tagged with the file's hash BEFORE the upload (not only when it fails): a run killed from outside runs no handler, and without
    the tag its pick would stay an orphan ``uploading`` and the retry would make another. A reused pick that already has its clip
    is not attached again."""
    pick = _earlier_pick(store, digest)
    if pick is None:
        pick, _ = drop.add_drop(store, None, None, now)
        pick = store.update_favorite(pick.id, proposal={**pick.proposal, "drop": {**pick.proposal["drop"], "folder_hash": digest}})
    if not pick.proposal.get("owner_clip_path"):
        drop.attach_file(store, storage, pick.id, path, now)
    return pick.id


def sync_folder(
    store: Store, storage: Storage, folder: Path, ledger_path: Path, now: datetime, *,
    fetch: Callable[[Path], None] = brctl_download, clock: Callable[[], float] = time.time,
) -> dict[str, list[dict[str, str]]]:  # fmt: skip
    """Take every new video of ``folder`` as a file drop. Returns ``{"added": [{"file", "pick_id"}], "skipped": [{"file",
    "reason"}], "failed": [{"file", "error"}]}``; see the module docstring for the rules. ``now`` (aware) stamps the drops and
    the ledger; ``clock`` (epoch seconds) is what "still copying" is measured against."""
    ledger = _load_ledger(ledger_path)
    ready, skipped = scan_folder(folder, clock(), fetch)
    added: list[dict[str, str]] = []
    failed: list[dict[str, str]] = []
    for path in ready:
        name = path.name
        pick_id = None
        try:
            digest = file_hash(path)
            if digest not in ledger:
                if (why := _problem(path, path.stat().st_size)) is not None:  # again, and BEFORE add_drop: the file may have changed
                    skipped.append({"file": name, "reason": why})
                    continue
                pick_id = _add(store, storage, path, digest, now)
        except (ValueError, StorageError, OSError) as e:
            failed.append({"file": name, "error": str(e)})
            continue
        if pick_id is None:
            skipped.append({"file": name, "reason": "already added"})
        else:
            ledger[digest] = {"pick_id": pick_id, "name": name, "at": now.isoformat()}
            added.append({"file": name, "pick_id": pick_id})
            try:
                _write_ledger(ledger_path, ledger)
            except OSError as e:  # the file is moved all the same, so it is not added twice
                failed.append({"file": name, "error": f"added as pick {pick_id}, but the ledger was not written: {e}"})
        try:
            _move_to_added(path)
        except OSError as e:  # the ledger knows the clip: the next run only moves it
            failed.append({"file": name, "error": f"taken, but not moved to {ADDED_DIR}/: {e}"})
    return {"added": added, "skipped": skipped, "failed": failed}


# ---- around a run: the lock, the dry run, the exit-code rule, the nudge ---------------------------------------------------------


@contextmanager
def run_lock(ledger_path: Path) -> Iterator[bool]:
    """Hold an exclusive, non-blocking ``flock`` on ``<ledger>.lock`` (beside the ledger, its folders are created) for the whole
    ``with`` block; yields False, without waiting, when another run holds it. The lock goes with the process: a run that dies leaves
    nothing to clean up. Two runs can overlap (the 5-minute agent, a manual run, the daily run); without this they could both take
    the same clip before either wrote the ledger."""
    lock_path = ledger_path.with_name(ledger_path.name + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
            return
        try:
            yield True
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def preview_folder(
    folder: Path, ledger_path: Path, *, clock: Callable[[], float] = time.time
) -> dict[str, list[dict[str, str]]]:
    """The dry run of ``sync_folder``: ``{"would_add": [{"file"}], "skipped": [...], "failed": [{"file", "error"}]}`` with the same
    rules (scan, then the ledger by content hash, a clip that appears twice in the folder counts once), and no write of any kind:
    no store, no storage, no move, no ledger, and iCloud is not asked to download anything. Raises like ``sync_folder`` for a
    missing folder (``OSError``) or an unreadable ledger (``ValueError``)."""
    seen = set(_load_ledger(ledger_path))
    ready, skipped = scan_folder(folder, clock(), lambda path: None)
    would_add: list[dict[str, str]] = []
    failed: list[dict[str, str]] = []
    for path in ready:
        try:
            digest = file_hash(path)
        except OSError as e:
            failed.append({"file": path.name, "error": str(e)})
            continue
        if digest in seen:
            skipped.append({"file": path.name, "reason": "already added"})
        else:
            seen.add(digest)
            would_add.append({"file": path.name})
    return {"would_add": would_add, "skipped": skipped, "failed": failed}


def every_file_failed(result: dict[str, list[dict[str, str]]]) -> bool:
    """True when something failed and not one file got through: the exit-code rule of ``sync-folder`` (a partial run is not a failed
    one). Counted on distinct file names: a file in ``added`` (or "already added") was uploaded, so a ledger or move failure on it
    does not make it a failure; a file waiting (iCloud, still copying) is neither."""
    uploaded = {a["file"] for a in result["added"]} | {s["file"] for s in result["skipped"] if s["reason"] == "already added"}
    return bool({f["file"] for f in result["failed"]} - uploaded) and not uploaded


def nudge_cloud() -> str | None:
    """Wake the cloud check now instead of at the next 2-hourly sweep: ``gh workflow run studio-drop.yml -f job=sweep``, run from the
    repo (``gh`` finds the repository there). None when it worked, else a one-line reason (no ``gh``, not logged in, a workflow that
    is disabled, too slow). Never raises: a missed nudge only costs the wait for the sweep."""
    try:
        done = subprocess.run(
            NUDGE_COMMAND, cwd=REPO_ROOT, capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=NUDGE_TIMEOUT_S, check=False
        )
    except FileNotFoundError:
        return "gh not found"
    except subprocess.TimeoutExpired:
        return f"gh timed out after {NUDGE_TIMEOUT_S} s"
    except (OSError, subprocess.SubprocessError) as e:
        return f"gh could not run: {e}"
    if done.returncode == 0:
        return None
    said = " ".join((done.stderr or done.stdout or "").split())[:200]
    return said or f"gh exited with status {done.returncode}"
