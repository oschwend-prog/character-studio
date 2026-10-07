"""``studio.clipfolder``: the owner's iCloud clips folder becomes drops (Terminal v2, spec section A).

What matters: an iCloud placeholder or a half-copied file is never uploaded; the same clip copied twice makes one drop; a file that
fails validation (type, size) never leaves an orphan ``uploading`` pick; a failed upload leaves the file for the next run (and the
retry reuses the pick it made, it does not pile up new ones); one bad file never stops the others; ``Added/`` is never scanned.
Everything is local: ``MemoryStore`` + ``LocalStorage``, a fake ``fetch`` that records its calls and a fixed clock.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest

from studio import clipfolder, drop
from studio.clipfolder import ADDED_DIR, SETTLE_SECONDS, file_hash, scan_folder, sync_folder
from studio.config import now_london
from studio.models import Body, Character
from studio.storage import LocalStorage, StorageError
from studio.store import MemoryStore

NOW = now_london()
CLOCK = 1_760_000_000.0  # the fixed "time.time()" of every run
MP4 = b"\x00\x00\x00\x18ftypmp42 a saved clip"


def make_store() -> MemoryStore:
    store = MemoryStore()
    store.add_character(Character(slug="biscuit", name="Biscuit", bodies=[Body.biped, Body.quadruped]))
    store.add_character(Character(slug="reginald", name="Reginald", bodies=[Body.biped]))
    return store


@pytest.fixture
def world(tmp_path):
    return make_store(), LocalStorage(tmp_path / "storage")


@pytest.fixture
def folder(tmp_path) -> Path:
    d = tmp_path / "ODD EYES clips"
    d.mkdir()
    return d


@pytest.fixture
def ledger(tmp_path) -> Path:
    return tmp_path / "state" / "odd-eyes" / "clips-ledger.json"  # its folders do not exist yet


def put(folder: Path, name: str, data: bytes = MP4, *, age: float = 3600.0) -> Path:
    """A file in the folder last written ``age`` seconds before the fixed clock."""
    path = folder / name
    path.write_bytes(data)
    os.utime(path, (CLOCK - age, CLOCK - age))
    return path


def run(world, folder, ledger, fetch=None, storage=None):
    store, default_storage = world
    return sync_folder(store, storage or default_storage, folder, ledger, NOW, fetch=fetch or (lambda p: None), clock=lambda: CLOCK)


def drops(store) -> list:
    return [f for f in store.list_favorites() if "drop" in f.proposal]


def names(directory: Path) -> list[str]:
    return sorted(p.name for p in directory.iterdir())


# ---- the happy path ----------------------------------------------------------------------------------------------------------


def test_a_new_clip_is_dropped_and_moved_to_added(world, folder, ledger):
    store, storage = world
    clip = put(folder, "a.mp4")
    digest = hashlib.sha256(MP4).hexdigest()
    out = run(world, folder, ledger)
    picks = drops(store)
    assert len(picks) == 1
    pick = picks[0]
    assert out == {"added": [{"file": "a.mp4", "pick_id": pick.id}], "skipped": [], "failed": []}
    d = pick.proposal["drop"]
    assert d["kind"] == "file" and d["state"] == "uploading" and d["character_by"] == "studio"  # no character: the studio recommends
    path = pick.proposal["owner_clip_path"]
    assert path.startswith(f"owner/{pick.id}/") and path.endswith(".mp4")
    assert storage.download("sources", path, folder.parent / "back.mp4").read_bytes() == MP4
    assert not clip.exists() and names(folder) == [ADDED_DIR] and names(folder / ADDED_DIR) == ["a.mp4"]
    stored = json.loads(ledger.read_text())
    assert list(stored) == [digest] == [file_hash(folder / ADDED_DIR / "a.mp4")]
    assert stored[digest]["pick_id"] == pick.id and stored[digest]["name"] == "a.mp4" and stored[digest]["at"] == NOW.isoformat()
    assert names(ledger.parent) == [ledger.name]  # written through a temp file that is gone, in folders it created


def test_a_second_run_finds_nothing_to_do(world, folder, ledger):
    put(folder, "a.mp4")
    run(world, folder, ledger)
    assert run(world, folder, ledger) == {"added": [], "skipped": [], "failed": []}
    assert len(drops(world[0])) == 1


def test_the_extension_is_matched_in_any_case(world, folder, ledger):
    put(folder, "CLIP.MOV")
    out = run(world, folder, ledger)
    assert [a["file"] for a in out["added"]] == ["CLIP.MOV"]
    assert names(folder / ADDED_DIR) == ["CLIP.MOV"]


# ---- iCloud placeholders and files still being written -----------------------------------------------------------------------


def test_an_icloud_placeholder_is_fetched_not_uploaded(world, folder, ledger):
    store, _ = world
    placeholder = put(folder, ".b.mov.icloud", b"bplist00 not a video")
    calls: list[Path] = []
    out = run(world, folder, ledger, fetch=calls.append)
    assert calls == [folder / "b.mov"]
    assert out == {"added": [], "skipped": [{"file": "b.mov", "reason": "in iCloud, downloading"}], "failed": []}
    assert drops(store) == [] and placeholder.exists() and not ledger.exists()


def test_a_file_still_copying_waits(world, folder, ledger):
    store, _ = world
    clip = put(folder, "a.mp4", age=5)
    out = run(world, folder, ledger)
    assert out == {"added": [], "skipped": [{"file": "a.mp4", "reason": "still copying"}], "failed": []}
    assert drops(store) == [] and clip.exists()


def test_a_file_settles_after_thirty_seconds(folder):
    put(folder, "young.mp4", age=SETTLE_SECONDS - 1)
    put(folder, "settled.mp4", age=SETTLE_SECONDS)
    ready, skipped = scan_folder(folder, CLOCK, lambda p: None)
    assert [p.name for p in ready] == ["settled.mp4"]
    assert skipped == [{"file": "young.mp4", "reason": "still copying"}]


def test_the_scan_names_every_reason_in_a_stable_order(folder, monkeypatch):
    monkeypatch.setattr(drop, "CLIP_MAX_BYTES", 1024 * 1024)
    put(folder, "ok.mp4")
    put(folder, "notes.txt", b"hello")
    put(folder, "young.mov", age=2)
    put(folder, ".gone.m4v.icloud", b"x")
    put(folder, "huge.mp4", b"x" * (1024 * 1024 + 1))
    fetched: list[Path] = []
    ready, skipped = scan_folder(folder, CLOCK, fetched.append)
    assert [p.name for p in ready] == ["ok.mp4"]
    assert skipped == [
        {"file": "gone.m4v", "reason": "in iCloud, downloading"},
        {"file": "huge.mp4", "reason": "over 1 MB"},
        {"file": "notes.txt", "reason": "not a video"},
        {"file": "young.mov", "reason": "still copying"},
    ]
    assert fetched == [folder / "gone.m4v"]


def test_a_file_exactly_at_the_limit_is_taken(folder, monkeypatch):
    monkeypatch.setattr(drop, "CLIP_MAX_BYTES", 1024 * 1024)
    put(folder, "edge.mp4", b"x" * (1024 * 1024))
    put(folder, "over.mp4", b"x" * (1024 * 1024 + 1))
    ready, skipped = scan_folder(folder, CLOCK, lambda p: None)
    assert [p.name for p in ready] == ["edge.mp4"] and skipped == [{"file": "over.mp4", "reason": "over 1 MB"}]


# ---- the same clip twice -----------------------------------------------------------------------------------------------------


def test_the_same_clip_twice_makes_one_drop(world, folder, ledger):
    store, _ = world
    put(folder, "first.mp4")
    put(folder, "second.mp4")  # the same bytes under another name
    out = run(world, folder, ledger)
    assert len(drops(store)) == 1
    assert [a["file"] for a in out["added"]] == ["first.mp4"]
    assert out["skipped"] == [{"file": "second.mp4", "reason": "already added"}] and out["failed"] == []
    assert names(folder) == [ADDED_DIR] and names(folder / ADDED_DIR) == ["first.mp4", "second.mp4"]
    assert len(json.loads(ledger.read_text())) == 1


def test_a_clip_copied_again_later_is_not_added_twice(world, folder, ledger):
    store, _ = world
    put(folder, "a.mp4")
    run(world, folder, ledger)
    put(folder, "a.mp4")  # the same bytes, same name, after the first went to Added/
    out = run(world, folder, ledger)
    assert out == {"added": [], "skipped": [{"file": "a.mp4", "reason": "already added"}], "failed": []}
    assert len(drops(store)) == 1
    assert names(folder) == [ADDED_DIR] and names(folder / ADDED_DIR) == ["a (2).mp4", "a.mp4"]


def test_a_name_clash_in_added_gets_a_number(world, folder, ledger):
    put(folder, "a.mp4", MP4 + b"1")
    run(world, folder, ledger)
    put(folder, "a.mp4", MP4 + b"2")
    run(world, folder, ledger)
    put(folder, "a.mp4", MP4 + b"3")
    out = run(world, folder, ledger)
    assert len(out["added"]) == 1 and len(drops(world[0])) == 3
    assert names(folder / ADDED_DIR) == ["a (2).mp4", "a (3).mp4", "a.mp4"]


# ---- files that must never become a pick -------------------------------------------------------------------------------------


def test_a_bad_file_never_leaves_an_orphan_pick(world, folder, ledger, monkeypatch):
    store, _ = world
    monkeypatch.setattr(drop, "CLIP_MAX_BYTES", 1024 * 1024)
    put(folder, "notes.txt", b"not a video")
    put(folder, "big.mp4", b"x" * (1024 * 1024 + 1))
    out = run(world, folder, ledger)
    assert store.list_favorites() == []
    assert out["added"] == [] and out["failed"] == []
    assert {s["file"]: s["reason"] for s in out["skipped"]} == {"notes.txt": "not a video", "big.mp4": "over 1 MB"}
    assert names(folder) == ["big.mp4", "notes.txt"] and not ledger.exists()


def test_a_file_that_grew_past_the_limit_after_the_scan_is_skipped_before_add_drop(world, folder, ledger, monkeypatch):
    store, _ = world
    monkeypatch.setattr(drop, "CLIP_MAX_BYTES", 1024 * 1024)
    clip = put(folder, "a.mp4")
    real_hash = clipfolder.file_hash

    def grow_while_hashing(path):
        digest = real_hash(path)
        with path.open("ab") as f:  # more bytes arrive between the scan and add_drop
            f.write(b"x" * (1024 * 1024))
        return digest

    monkeypatch.setattr(clipfolder, "file_hash", grow_while_hashing)
    out = run(world, folder, ledger)
    assert store.list_favorites() == [] and out["added"] == [] and out["failed"] == []
    assert out["skipped"] == [{"file": "a.mp4", "reason": "over 1 MB"}] and clip.exists()


def test_files_in_added_are_ignored(world, folder, ledger):
    store, _ = world
    (folder / ADDED_DIR).mkdir()
    put(folder / ADDED_DIR, "old.mp4")
    (folder / "some folder").mkdir()
    put(folder / "some folder", "inside.mp4")
    put(folder, ".DS_Store", b"\x00\x00\x00\x01Bud1")
    out = run(world, folder, ledger)
    assert out == {"added": [], "skipped": [], "failed": []}
    assert store.list_favorites() == [] and not ledger.exists()
    assert names(folder / ADDED_DIR) == ["old.mp4"]


# ---- failures ----------------------------------------------------------------------------------------------------------------


class DownStorage(LocalStorage):
    """Storage that refuses the first ``fail_first`` uploads (None: every one)."""

    def __init__(self, root, fail_first=None):
        super().__init__(root)
        self.fail_first = fail_first
        self.calls = 0

    def upload(self, bucket, path, file):
        self.calls += 1
        if self.fail_first is None or self.calls <= self.fail_first:
            raise StorageError("storage is down", 503)
        return super().upload(bucket, path, file)


def test_a_failed_upload_leaves_the_file_for_the_next_run(world, folder, ledger, tmp_path):
    store, _ = world
    clip = put(folder, "a.mp4")
    out = run(world, folder, ledger, storage=DownStorage(tmp_path / "down"))
    assert out["added"] == [] and out["skipped"] == []
    assert out["failed"] == [{"file": "a.mp4", "error": "storage is down"}]
    assert clip.exists() and names(folder) == ["a.mp4"] and not ledger.exists()  # the ledger is unchanged: it was never written
    # the next run, with storage back, takes it; the pick the failed run made is reused, not duplicated
    again = run(world, folder, ledger)
    assert len(again["added"]) == 1 and again["failed"] == []
    picks = drops(store)
    assert len(picks) == 1 and picks[0].id == again["added"][0]["pick_id"] and picks[0].proposal["owner_clip_path"]
    assert names(folder) == [ADDED_DIR]


def test_a_failed_upload_that_keeps_failing_does_not_pile_up_picks(world, folder, ledger, tmp_path):
    store, _ = world
    put(folder, "a.mp4")
    down = DownStorage(tmp_path / "down")
    for _ in range(3):
        run(world, folder, ledger, storage=down)
    assert down.calls == 3 and len(drops(store)) == 1  # one pick waiting for its file, however many tries


def test_one_failing_file_does_not_stop_the_others(world, folder, ledger, tmp_path):
    store, _ = world
    put(folder, "a.mp4", MP4 + b"a")
    put(folder, "b.mp4", MP4 + b"b")
    out = run(world, folder, ledger, storage=DownStorage(tmp_path / "flaky", fail_first=1))
    assert [f["file"] for f in out["failed"]] == ["a.mp4"] and [a["file"] for a in out["added"]] == ["b.mp4"]
    assert names(folder) == [ADDED_DIR, "a.mp4"] and names(folder / ADDED_DIR) == ["b.mp4"]
    assert list(json.loads(ledger.read_text()).values())[0]["name"] == "b.mp4"


def test_a_file_that_cannot_be_read_is_a_failure_not_a_crash(world, folder, ledger, monkeypatch):
    put(folder, "a.mp4", MP4 + b"a")
    put(folder, "b.mp4", MP4 + b"b")
    real = clipfolder.file_hash

    def unreadable(path):
        if path.name == "a.mp4":
            raise PermissionError(1, "Operation not permitted")
        return real(path)

    monkeypatch.setattr(clipfolder, "file_hash", unreadable)
    out = run(world, folder, ledger)
    assert [f["file"] for f in out["failed"]] == ["a.mp4"] and "not permitted" in out["failed"][0]["error"]
    assert [a["file"] for a in out["added"]] == ["b.mp4"] and drops(world[0])[0].proposal["owner_clip_path"]


def test_no_character_taking_videos_is_a_failure_of_that_file(folder, ledger, tmp_path):
    store = MemoryStore()  # no characters: add_drop cannot pick a provisional one
    put(folder, "a.mp4")
    out = sync_folder(store, LocalStorage(tmp_path / "s"), folder, ledger, NOW, fetch=lambda p: None, clock=lambda: CLOCK)
    assert out["added"] == [] and out["failed"][0]["file"] == "a.mp4" and "paused" in out["failed"][0]["error"]
    assert (folder / "a.mp4").exists() and store.list_favorites() == []


def test_a_move_that_fails_after_the_upload_is_remembered_by_the_ledger(world, folder, ledger, monkeypatch):
    store, _ = world
    put(folder, "a.mp4")
    real_move = clipfolder._move_to_added

    def locked(path):
        raise PermissionError(1, "locked")

    monkeypatch.setattr(clipfolder, "_move_to_added", locked)
    out = run(world, folder, ledger)
    assert len(out["added"]) == 1 and out["failed"][0]["file"] == "a.mp4" and "Added/" in out["failed"][0]["error"]
    assert (folder / "a.mp4").exists() and len(json.loads(ledger.read_text())) == 1
    monkeypatch.setattr(clipfolder, "_move_to_added", real_move)  # the next run only moves it: no second drop
    out = run(world, folder, ledger)
    assert out == {"added": [], "skipped": [{"file": "a.mp4", "reason": "already added"}], "failed": []}
    assert len(drops(store)) == 1 and names(folder) == [ADDED_DIR]


def test_an_unreadable_ledger_stops_the_sync_instead_of_forgetting_what_was_added(world, folder, ledger):
    put(folder, "a.mp4")
    ledger.parent.mkdir(parents=True)
    ledger.write_text("{not json")
    with pytest.raises(ValueError, match="ledger"):
        run(world, folder, ledger)
    assert drops(world[0]) == [] and (folder / "a.mp4").exists()


def test_a_missing_folder_is_an_error_the_caller_sees(world, tmp_path, ledger):
    with pytest.raises(FileNotFoundError):
        run(world, tmp_path / "no such folder", ledger)


# ---- helpers -----------------------------------------------------------------------------------------------------------------


def test_file_hash_is_sha256_of_the_content(tmp_path):
    path = tmp_path / "x.mp4"
    data = os.urandom(3 * 1024 * 1024 + 17)  # several chunks
    path.write_bytes(data)
    assert file_hash(path) == hashlib.sha256(data).hexdigest()


def test_brctl_download_asks_icloud_and_never_raises(monkeypatch, tmp_path):
    seen: list[list[str]] = []

    def fake_run(cmd, **kw):
        seen.append(cmd)
        return subprocess.CompletedProcess(cmd, 1, "", "no such file")

    monkeypatch.setattr(clipfolder.subprocess, "run", fake_run)
    clipfolder.brctl_download(tmp_path / "b.mov")
    assert seen == [["brctl", "download", str(tmp_path / "b.mov")]]

    def missing(cmd, **kw):
        raise FileNotFoundError("brctl")

    monkeypatch.setattr(clipfolder.subprocess, "run", missing)
    clipfolder.brctl_download(tmp_path / "b.mov")  # not on this machine: ignored
    def slow(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd, 60)

    monkeypatch.setattr(clipfolder.subprocess, "run", slow)
    clipfolder.brctl_download(tmp_path / "b.mov")  # iCloud too slow: ignored


def test_the_defaults_are_the_owners_icloud_folder_and_a_state_ledger():
    assert clipfolder.DEFAULT_FOLDER == Path.home() / "Library/Mobile Documents/com~apple~CloudDocs/ODD EYES clips"
    assert clipfolder.DEFAULT_LEDGER == Path.home() / ".local/state/odd-eyes/clips-ledger.json"
    assert ADDED_DIR == "Added" and SETTLE_SECONDS == 30
