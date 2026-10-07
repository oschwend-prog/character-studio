"""``studio.clipfolder``: the owner's iCloud clips folder becomes drops (Terminal v2, spec section A).

What matters: an iCloud placeholder or a half-copied file is never uploaded; the same clip copied twice makes one drop; a file that
fails validation (type, size) never leaves an orphan ``uploading`` pick; a failed upload leaves the file for the next run (and the
retry reuses the pick it made, it does not pile up new ones); one bad file never stops the others; ``Added/`` is never scanned.
Everything is local: ``MemoryStore`` + ``LocalStorage``, a fake ``fetch`` that records its calls and a fixed clock.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from studio import clipfolder, drop
from studio.cli import app
from studio.clipfolder import ADDED_DIR, SETTLE_SECONDS, file_hash, scan_folder, sync_folder
from studio.config import now_london
from studio.models import Body, Character
from studio.storage import LocalStorage, StorageError
from studio.store import MemoryStore

NOW = now_london()
CLOCK = 1_760_000_000.0  # the fixed "time.time()" of every run
MP4 = b"\x00\x00\x00\x18ftypmp42 a saved clip"
EVICTED = b"evicted: the content is not on this Mac"  # what the fake dataless flag below recognises by its size


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


# ---- evicted ("dataless") iCloud files, macOS 14+: the real name stays, the content is not on disk ----------------------------


@pytest.fixture
def evicted(monkeypatch):
    """Files whose content is ``EVICTED`` count as dataless (a real flag cannot be set on a temp file)."""
    monkeypatch.setattr(clipfolder, "_is_dataless", lambda st: st.st_size == len(EVICTED))


def test_dataless_is_the_macos_flag_in_st_flags(tmp_path):
    assert clipfolder.SF_DATALESS == 0x40000000
    assert clipfolder._is_dataless(SimpleNamespace(st_flags=0x40000000))
    assert clipfolder._is_dataless(SimpleNamespace(st_flags=0x40000000 | 0x20))  # with other flags
    assert not clipfolder._is_dataless(SimpleNamespace(st_flags=0x20))
    assert not clipfolder._is_dataless(SimpleNamespace(st_flags=0))
    assert not clipfolder._is_dataless(SimpleNamespace())  # no st_flags (Linux): never dataless
    real = tmp_path / "x.mp4"
    real.write_bytes(MP4)
    assert not clipfolder._is_dataless(real.stat())  # a file on disk


def test_an_evicted_video_is_fetched_and_skipped_not_hashed_or_uploaded(world, folder, ledger, evicted, monkeypatch):
    store, _ = world
    clip = put(folder, "evicted.mp4", EVICTED)
    hashed: list[str] = []
    real_hash = clipfolder.file_hash
    monkeypatch.setattr(clipfolder, "file_hash", lambda path: hashed.append(path.name) or real_hash(path))
    calls: list[Path] = []
    out = run(world, folder, ledger, fetch=calls.append)
    assert calls == [clip]  # asked iCloud to download it
    assert out == {"added": [], "skipped": [{"file": "evicted.mp4", "reason": "in iCloud, downloading"}], "failed": []}
    assert hashed == [] and drops(store) == [] and clip.exists() and not ledger.exists()  # never read, never uploaded
    # iCloud has downloaded it by the next run (no dataless flag any more): now it is taken
    monkeypatch.setattr(clipfolder, "_is_dataless", lambda st: False)
    out = run(world, folder, ledger, fetch=calls.append)
    assert [a["file"] for a in out["added"]] == ["evicted.mp4"] and calls == [clip] and len(drops(store)) == 1


def test_an_evicted_non_video_is_neither_fetched_nor_uploaded(world, folder, ledger, evicted):
    store, _ = world
    put(folder, "notes.txt", EVICTED)
    calls: list[Path] = []
    out = run(world, folder, ledger, fetch=calls.append)
    assert calls == [] and drops(store) == []
    assert out == {"added": [], "skipped": [{"file": "notes.txt", "reason": "not a video"}], "failed": []}


def test_an_evicted_video_over_the_limit_is_not_fetched(world, folder, ledger, evicted, monkeypatch):
    monkeypatch.setattr(drop, "CLIP_MAX_BYTES", len(EVICTED) - 1)  # its size is the real one: too big to ever take
    put(folder, "huge.mov", EVICTED)
    calls: list[Path] = []
    out = run(world, folder, ledger, fetch=calls.append)
    assert calls == [] and out["added"] == [] and [s["reason"] for s in out["skipped"]] == ["over 0 MB"]


def test_a_legacy_placeholder_of_a_non_video_is_not_fetched(world, folder, ledger):
    put(folder, ".notes.txt.icloud", b"bplist00")
    put(folder, "..icloud", b"bplist00")  # no name at all: a hidden file, not a placeholder
    calls: list[Path] = []
    out = run(world, folder, ledger, fetch=calls.append)
    assert calls == [] and out == {"added": [], "skipped": [{"file": "notes.txt", "reason": "not a video"}], "failed": []}


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


class CountingStorage(LocalStorage):
    """Storage that records every upload, and can be told to be killed (a ``BaseException`` no handler of the code catches) at one."""

    def __init__(self, root, die_on_upload=False):
        super().__init__(root)
        self.uploads = []
        self.die_on_upload = die_on_upload

    def upload(self, bucket, path, file):
        if self.die_on_upload:
            raise KeyboardInterrupt  # the process is killed from outside (launchctl bootout): no except clause of ours runs
        self.uploads.append(path)
        return super().upload(bucket, path, file)


def test_a_run_killed_between_add_drop_and_the_upload_is_taken_up_by_the_next_run(world, folder, ledger, tmp_path):
    store, _ = world
    clip = put(folder, "a.mp4")
    with pytest.raises(KeyboardInterrupt):
        run(world, folder, ledger, storage=CountingStorage(tmp_path / "killed", die_on_upload=True))
    (orphan,) = drops(store)  # the killed run left its pick, tagged with the clip's hash BEFORE the upload (no handler ran)
    assert orphan.proposal["drop"]["folder_hash"] == hashlib.sha256(MP4).hexdigest()
    assert orphan.proposal["drop"]["state"] == "uploading" and not orphan.proposal.get("owner_clip_path")
    assert clip.exists() and not ledger.exists()
    storage = CountingStorage(tmp_path / "back")
    again = run(world, folder, ledger, storage=storage)  # the next run finds that pick and finishes it: one drop in total
    assert again == {"added": [{"file": "a.mp4", "pick_id": orphan.id}], "skipped": [], "failed": []}
    (pick,) = drops(store)
    assert pick.id == orphan.id and pick.proposal["owner_clip_path"].startswith(f"owner/{orphan.id}/")
    assert len(storage.uploads) == 1 and names(folder) == [ADDED_DIR]
    assert list(json.loads(ledger.read_text())) == [file_hash(folder / ADDED_DIR / "a.mp4")]


@pytest.mark.parametrize("state", ["uploading", "checking"])  # checking: the cloud check already took the pick on
def test_a_run_killed_after_the_upload_before_the_ledger_makes_no_second_drop(world, folder, ledger, tmp_path, monkeypatch, state):
    store, _ = world
    clip = put(folder, "a.mp4")
    storage = CountingStorage(tmp_path / "storage2")
    real_write = clipfolder._write_ledger

    def killed(path, data):
        raise KeyboardInterrupt

    monkeypatch.setattr(clipfolder, "_write_ledger", killed)
    with pytest.raises(KeyboardInterrupt):
        run(world, folder, ledger, storage=storage)
    (attached,) = drops(store)  # uploaded and attached, but the ledger never heard of it and the file was not moved
    assert attached.proposal["owner_clip_path"] and clip.exists() and not ledger.exists() and len(storage.uploads) == 1
    if state != "uploading":
        store.update_favorite(attached.id, proposal={**attached.proposal, "drop": {**attached.proposal["drop"], "state": state}})
    monkeypatch.setattr(clipfolder, "_write_ledger", real_write)
    again = run(world, folder, ledger, storage=storage)  # the next run only writes the ledger and moves the file
    assert again == {"added": [{"file": "a.mp4", "pick_id": attached.id}], "skipped": [], "failed": []}
    assert [f.id for f in drops(store)] == [attached.id] and len(storage.uploads) == 1  # one drop, one upload
    assert drops(store)[0].proposal["drop"]["state"] == state and names(folder) == [ADDED_DIR]
    assert json.loads(ledger.read_text())[attached.proposal["drop"]["folder_hash"]]["pick_id"] == attached.id
    assert run(world, folder, ledger, storage=storage) == {"added": [], "skipped": [], "failed": []}  # and then it is quiet


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


# ---- the CLI: ``studio drop sync-folder`` and the nudge to the cloud check ----------------------------------------------------


class Nudge:
    """A stand-in for ``clipfolder.nudge_cloud``: counts the calls and answers ``error`` (None = it worked). Never runs ``gh``."""

    def __init__(self, error=None):
        self.error, self.calls = error, 0

    def __call__(self):
        self.calls += 1
        return self.error


@pytest.fixture
def nudge(monkeypatch):
    fake = Nudge()
    monkeypatch.setattr(clipfolder, "nudge_cloud", fake)
    return fake


@pytest.fixture
def cli(monkeypatch, world):
    """``cli(folder, ledger, *flags)`` runs the command against the in-memory store and the local storage."""
    store, storage = world
    monkeypatch.setattr(drop, "open_store", lambda: store)
    monkeypatch.setattr(drop, "open_storage", lambda: storage)

    def invoke(folder, ledger, *flags):
        return CliRunner().invoke(app, ["drop", "sync-folder", "--folder", str(folder), "--ledger", str(ledger), *flags])

    return invoke


def test_cli_sync_folder_adds_and_nudges_the_cloud_once(world, folder, ledger, cli, nudge):
    put(folder, "a.mp4", MP4 + b"a")
    put(folder, "b.mov", MP4 + b"b")
    r = cli(folder, ledger)
    assert r.exit_code == 0, r.output
    out = json.loads(r.output)
    assert len(out["added"]) == 2 and out["failed"] == [] and out["dispatched"] is True and out["dispatch_error"] is None
    assert nudge.calls == 1  # once for the run, not once per clip
    assert len(drops(world[0])) == 2 and names(folder) == [ADDED_DIR] and len(json.loads(ledger.read_text())) == 2
    # the next run finds nothing, so it does not wake the cloud again
    again = json.loads(cli(folder, ledger).output)
    assert again["added"] == [] and again["dispatched"] is False and again["dispatch_error"] is None and nudge.calls == 1


def test_cli_sync_folder_nothing_added_nudges_nothing(folder, ledger, cli, nudge):
    put(folder, "notes.txt", b"hello")
    r = cli(folder, ledger)
    assert r.exit_code == 0, r.output
    assert json.loads(r.output)["skipped"] == [{"file": "notes.txt", "reason": "not a video"}] and nudge.calls == 0


def test_cli_sync_folder_no_dispatch_adds_without_the_nudge(world, folder, ledger, cli, nudge):
    put(folder, "a.mp4")
    r = cli(folder, ledger, "--no-dispatch")
    assert r.exit_code == 0, r.output
    out = json.loads(r.output)
    assert len(out["added"]) == 1 and out["dispatched"] is False and out["dispatch_error"] is None and nudge.calls == 0


def test_cli_sync_folder_dry_run_writes_nothing(world, folder, ledger, nudge, monkeypatch):
    def forbidden(*a, **k):
        raise AssertionError("a dry run opens neither the store nor the storage")

    monkeypatch.setattr(drop, "open_store", forbidden)
    monkeypatch.setattr(drop, "open_storage", forbidden)
    ran: list[list[str]] = []
    monkeypatch.setattr(clipfolder.subprocess, "run", lambda cmd, **kw: ran.append(cmd))  # no brctl, no gh
    put(folder, "a.mp4", MP4 + b"a")
    put(folder, "b.mp4", MP4 + b"a")  # the same clip again: only one would be added
    (folder / "c.mov").write_bytes(MP4 + b"c")  # written just now (the command reads the real clock): still copying
    clip = (folder / "a.mp4").read_bytes()
    (folder / ".d.mov.icloud").write_bytes(b"x")  # a placeholder: a dry run does not even ask iCloud for it
    r = CliRunner().invoke(app, ["drop", "sync-folder", "--folder", str(folder), "--ledger", str(ledger), "--dry-run"])
    assert r.exit_code == 0, r.output
    out = json.loads(r.output)
    assert out["dry_run"] is True and out["would_add"] == [{"file": "a.mp4"}] and out["failed"] == []
    assert {"file": "b.mp4", "reason": "already added"} in out["skipped"]
    assert {"file": "c.mov", "reason": "still copying"} in out["skipped"]
    assert {"file": "d.mov", "reason": "in iCloud, downloading"} in out["skipped"]
    assert out["dispatched"] is False and nudge.calls == 0 and ran == []
    assert names(folder) == [".d.mov.icloud", "a.mp4", "b.mp4", "c.mov"] and (folder / "a.mp4").read_bytes() == clip
    assert not ledger.exists() and not ledger.parent.exists()  # no ledger, no lock file, not even the state folder


def test_cli_sync_folder_dry_run_knows_what_the_ledger_already_added(world, folder, ledger, cli, nudge):
    put(folder, "a.mp4")
    assert json.loads(cli(folder, ledger).output)["added"]
    put(folder, "a.mp4")  # the same clip saved again
    r = cli(folder, ledger, "--dry-run")
    assert r.exit_code == 0 and json.loads(r.output)["would_add"] == []
    assert json.loads(r.output)["skipped"] == [{"file": "a.mp4", "reason": "already added"}]


def test_cli_sync_folder_dry_run_with_an_unreadable_ledger_says_so(folder, ledger, cli, nudge):
    put(folder, "a.mp4")
    ledger.parent.mkdir(parents=True)
    ledger.write_text("{not json")
    r = cli(folder, ledger, "--dry-run")
    assert r.exit_code == 1 and "ledger" in r.output and "Traceback" not in r.output and (folder / "a.mp4").exists()


def test_cli_sync_folder_without_a_folder_says_how_to_install(tmp_path, ledger, cli, nudge):
    r = cli(tmp_path / "no such folder", ledger)
    assert r.exit_code == 2
    assert "bin/install-clip-sync" in r.output and "no clips folder at" in r.output and "no such folder" in r.output
    assert "Traceback" not in r.output and nudge.calls == 0 and not ledger.parent.exists()
    assert cli(tmp_path / "no such folder", ledger, "--dry-run").exit_code == 2  # the same answer for a dry run


def test_cli_sync_folder_that_is_a_file_is_not_a_clips_folder(tmp_path, ledger, cli, nudge):
    not_a_folder = tmp_path / "ODD EYES clips"
    not_a_folder.write_text("oops")
    r = cli(not_a_folder, ledger)
    assert r.exit_code == 2 and "bin/install-clip-sync" in r.output


def test_cli_sync_folder_defaults_are_the_owners_folder_and_ledger(monkeypatch, tmp_path, nudge):
    store = make_store()
    monkeypatch.setattr(clipfolder, "DEFAULT_FOLDER", tmp_path / "default folder")
    monkeypatch.setattr(clipfolder, "DEFAULT_LEDGER", tmp_path / "default state" / "ledger.json")
    monkeypatch.setattr(drop, "open_store", lambda: store)
    monkeypatch.setattr(drop, "open_storage", lambda: LocalStorage(tmp_path / "storage"))
    r = CliRunner().invoke(app, ["drop", "sync-folder"])
    assert r.exit_code == 2 and str(tmp_path / "default folder") in r.output
    (tmp_path / "default folder").mkdir()
    put(tmp_path / "default folder", "a.mp4")
    r = CliRunner().invoke(app, ["drop", "sync-folder"])
    assert r.exit_code == 0 and len(json.loads(r.output)["added"]) == 1
    assert (tmp_path / "default state" / "ledger.json").exists()


def test_cli_sync_folder_nudge_failure_is_only_reported(world, folder, ledger, cli, monkeypatch):
    nudge = Nudge("gh not found")
    monkeypatch.setattr(clipfolder, "nudge_cloud", nudge)
    put(folder, "a.mp4")
    r = cli(folder, ledger)
    assert r.exit_code == 0, r.output
    out = json.loads(r.output)
    assert len(out["added"]) == 1 and out["dispatched"] is False and out["dispatch_error"] == "gh not found" and nudge.calls == 1


def test_cli_sync_folder_another_run_holding_the_lock_is_skipped(world, folder, ledger, cli, nudge):
    put(folder, "a.mp4")
    ledger.parent.mkdir(parents=True)
    with (ledger.parent / (ledger.name + ".lock")).open("a") as held:  # the 5-minute agent is in the middle of a run
        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
        r = cli(folder, ledger)
        assert r.exit_code == 0, r.output
        assert json.loads(r.output) == {"skipped_run": "another sync is running"}
        assert drops(world[0]) == [] and names(folder) == ["a.mp4"] and nudge.calls == 0
    again = cli(folder, ledger)  # the other run is over: the lock is free
    assert again.exit_code == 0 and len(json.loads(again.output)["added"]) == 1


def test_cli_sync_folder_releases_the_lock_when_the_run_fails(folder, ledger, cli, nudge, monkeypatch):
    put(folder, "a.mp4")
    real = drop.add_drop

    def down(*a, **k):
        raise RuntimeError("database is down")

    monkeypatch.setattr(drop, "add_drop", down)
    assert cli(folder, ledger).exit_code == 1
    monkeypatch.setattr(drop, "add_drop", real)
    r = cli(folder, ledger)
    assert r.exit_code == 0 and len(json.loads(r.output)["added"]) == 1


def test_cli_sync_folder_a_database_error_is_one_line_not_a_traceback(world, folder, ledger, cli, nudge, monkeypatch):
    put(folder, "a.mp4")

    def boom(*a, **k):
        raise RuntimeError("connection to the database was lost\nserver closed the connection unexpectedly")

    monkeypatch.setattr(drop, "add_drop", boom)  # not a ValueError / StorageError / OSError: sync_folder lets it out
    r = cli(folder, ledger)
    assert r.exit_code == 1
    assert isinstance(r.exception, SystemExit) and "Traceback" not in r.output  # a clean exit, so the LaunchAgent log stays readable
    assert r.output.count("\n") == 1 and r.output.startswith("error:") and "connection to the database was lost" in r.output
    assert (folder / "a.mp4").exists() and nudge.calls == 0 and not ledger.exists()


def test_cli_sync_folder_an_unreadable_ledger_is_one_line_exit_1(world, folder, ledger, cli, nudge):
    put(folder, "a.mp4")
    ledger.parent.mkdir(parents=True)
    ledger.write_text("[1, 2]")
    r = cli(folder, ledger)
    assert r.exit_code == 1 and "ledger" in r.output and "Traceback" not in r.output and r.output.count("\n") == 1
    assert drops(world[0]) == [] and (folder / "a.mp4").exists() and nudge.calls == 0


def test_cli_sync_folder_a_folder_macos_refuses_to_list_is_one_line_exit_1(folder, ledger, cli, nudge, monkeypatch):
    def refused(*a, **k):
        raise PermissionError(1, "Operation not permitted", str(folder))

    monkeypatch.setattr(clipfolder, "scan_folder", refused)  # iCloud Drive privacy: listing the folder is refused
    r = cli(folder, ledger)
    assert r.exit_code == 1 and "Operation not permitted" in r.output and "Traceback" not in r.output and r.output.count("\n") == 1
    assert "bin/install-clip-sync" not in r.output  # it exists: installing again would not help
    assert cli(folder, ledger, "--dry-run").exit_code == 1


def test_cli_sync_folder_exits_1_only_when_every_file_failed(world, folder, ledger, tmp_path, monkeypatch, nudge):
    store, _ = world
    monkeypatch.setattr(drop, "open_store", lambda: store)
    put(folder, "a.mp4", MP4 + b"a")
    put(folder, "b.mp4", MP4 + b"b")

    def invoke(storage):
        monkeypatch.setattr(drop, "open_storage", lambda: storage)
        return CliRunner().invoke(app, ["drop", "sync-folder", "--folder", str(folder), "--ledger", str(ledger)])

    r = invoke(DownStorage(tmp_path / "down"))
    assert r.exit_code == 1  # nothing could be uploaded: the run says so
    out = json.loads(r.output)  # the JSON is still printed, for the log
    assert out["added"] == [] and len(out["failed"]) == 2 and out["dispatched"] is False and nudge.calls == 0
    r = invoke(DownStorage(tmp_path / "flaky", fail_first=1))
    assert r.exit_code == 0, r.output  # one went in: a partial run is not a failed one
    out = json.loads(r.output)
    assert [a["file"] for a in out["added"]] == ["b.mp4"] and [f["file"] for f in out["failed"]] == ["a.mp4"] and nudge.calls == 1


def test_every_file_failed_does_not_count_a_file_twice():
    def res(added=(), skipped=(), failed=()):
        return {
            "added": [{"file": n, "pick_id": "p"} for n in added],
            "skipped": [{"file": n, "reason": why} for n, why in skipped],
            "failed": [{"file": n, "error": "x"} for n in failed],
        }

    assert clipfolder.every_file_failed(res()) is False  # nothing to do is not a failure
    assert clipfolder.every_file_failed(res(failed=["a"])) is True
    assert clipfolder.every_file_failed(res(failed=["a", "b"])) is True
    assert clipfolder.every_file_failed(res(added=["a"], failed=["b"])) is False
    assert clipfolder.every_file_failed(res(added=["a"], failed=["a"])) is False  # uploaded, then the ledger or the move failed
    assert clipfolder.every_file_failed(res(failed=["a", "a"])) is True  # one file, however many ways it failed
    assert clipfolder.every_file_failed(res(skipped=[("b", "already added")], failed=["a"])) is False
    assert clipfolder.every_file_failed(res(skipped=[("b", "already added")], failed=["b"])) is False  # only its move failed
    assert clipfolder.every_file_failed(res(skipped=[("c", "still copying")], failed=["a"])) is True  # waiting is not a success


# ---- the nudge ---------------------------------------------------------------------------------------------------------------


def test_nudge_cloud_runs_the_sweep_workflow_from_the_repo(monkeypatch):
    seen = {}

    def fake_run(cmd, **kw):
        seen.update(cmd=cmd, **kw)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(clipfolder.subprocess, "run", fake_run)
    assert clipfolder.nudge_cloud() is None
    assert seen["cmd"] == ["gh", "workflow", "run", "studio-drop.yml", "-f", "job=sweep"]
    assert seen["cwd"] == Path(clipfolder.__file__).resolve().parents[1] and seen["cwd"].joinpath("bin", "studio").exists()
    assert 0 < seen["timeout"] <= 60 and seen["capture_output"] is True and seen["stdin"] == subprocess.DEVNULL


@pytest.mark.parametrize(
    ("failure", "expected"),
    [
        (FileNotFoundError("gh"), "gh not found"),
        (subprocess.TimeoutExpired("gh", 30), "gh timed out"),
        (PermissionError("gh: permission denied"), "gh could not run"),
    ],
)
def test_nudge_cloud_reports_a_gh_that_cannot_run_and_never_raises(monkeypatch, failure, expected):
    def broken(cmd, **kw):
        raise failure

    monkeypatch.setattr(clipfolder.subprocess, "run", broken)
    assert expected in clipfolder.nudge_cloud()


def test_nudge_cloud_reports_what_gh_said_when_it_fails(monkeypatch):
    def refused(cmd, **kw):
        return subprocess.CompletedProcess(cmd, 1, "", "HTTP 404: workflow studio-drop.yml not found\nsee gh help\n")

    monkeypatch.setattr(clipfolder.subprocess, "run", refused)
    why = clipfolder.nudge_cloud()
    assert "HTTP 404" in why and "\n" not in why  # one line

    def silent(cmd, **kw):
        return subprocess.CompletedProcess(cmd, 4, "", "")

    monkeypatch.setattr(clipfolder.subprocess, "run", silent)
    assert "4" in clipfolder.nudge_cloud()  # at least the exit status
