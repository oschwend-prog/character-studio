"""``studio drop``: a video the owner drops is checked for free, then made (paid) only after the owner's Make it.

Real ffmpeg on small synthetic clips; Gemini, Higgsfield and yt-dlp are fakes (no request leaves the machine). What matters:
no credits without ``proposal.make_requested``; the cap and the kill switch refuse; the submit is never repeated blindly; the
like-for-like, child-as-the-star, watermark and burned-in-text checks block (children elsewhere in the clip do not); one
automatic re-roll then stop; the master ends on the dance with the clip's own sound and the hook on screen; every step
resumes where the clip is.
"""

from __future__ import annotations

import dataclasses
import json
import shutil
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from typer.testing import CliRunner

from studio import budget, clips, drop, gemini, sources
from studio.cli import app
from studio.config import now_london
from studio.drop import DropError, add_drop, attach_file, drop_window, make_drop, pending, process_drop, validate_adjust
from studio.favorites import next_favorites
from studio.gemini import GeminiBlocked, GeminiError
from studio.higgsfield_api import PollTimeout, RequestStatus, Submitted, SubmitUncertain
from studio.media.qa import probe
from studio.models import Body, Character, Clip, ClipState, Favorite, Mode, Settings
from studio.storage import LocalStorage, StorageError
from studio.store import MemoryStore

NOW = now_london()
TIKTOK = "https://www.tiktok.com/@dancer.one/video/7688386199270001953"


def deconstruct(**over) -> dict:
    base = {
        "people_count": 1,
        "star": {"kind": "person", "body": "biped", "description": "the man in the grey suit", "x_center": 0.5, "full_body": True, "child": False},
        "minors": False, "watermark": False, "burned_in_text": False, "camera": "static",
        "setting": "an office corridor", "what_happens": "a man in a suit does the shoulder shimmy down the corridor",
        "classic": False, "moment_name": "shoulder shimmy", "suggested_part": "featured", "gadgets": ["black umbrella"],
        "hooks": ["The household is unaware.", "Breakfast is at eight.", "Kindly do not tell the Duchess."],
        "hook_patterns": ["understatement", "false-premise", "trend-label"],  # Reginald's three arms, once each (a test with B on checks it)
        "caption": {"title": "Shoulder shimmy · butler edition", "joke": "The corridor has been informed.",
                    "send": "Send this to your butler.", "question": "Which eye did you notice first?", "tease": "Next week: the stairs."},
        "first_comment": "Requests for next week may be left below. Within reason.",
        "first_comment_question": "What should the household attempt next week?",
        "hashtags": ["#shouldershimmy", "#butler", "#deadpan", "#oddeyes"], "notes": "",
        "watermark_spans": [], "burned_in_text_spans": [],
        "potential": {"score": 7, "reason": " a shimmy many people do, moving from the first second "},
    }
    base.update(over)
    if "recommended" not in over:  # like for like among the test roster (biscuit: a dog or an animal; reginald: a person)
        dog = base["star"]["kind"] in ("dog", "animal")
        base["recommended"] = {"slug": "biscuit" if dog else "reginald", "reason": "dog star: Biscuit's moves" if dog else "office shimmy: Reginald's deadpan"}
    return base


QA_PASS = {"character_visible": True, "leftover_person": False, "watermark": False, "eyes_ok": True, "problems": [], "verdict": "pass"}
QA_FAIL = {**QA_PASS, "leftover_person": True, "verdict": "fail", "problems": ["the original man is still dancing at 3 s"]}


class FakeGemini:
    """``generate_json`` answers from a queue (a dict or an exception), and records what was sent."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.calls: list[dict] = []

    def generate_json(self, media, mime, prompt, schema, *, check=None):
        self.calls.append({"media": Path(media), "mime": mime, "prompt": prompt, "schema": schema, "size": Path(media).stat().st_size})
        a = self.answers.pop(0)
        if isinstance(a, Exception):
            raise a
        if check is not None:
            assert check(a) == [], check(a)
        return a


class FakeHF:
    """``submit_object_swap`` / ``wait`` / ``download`` like ``HiggsfieldClient``: the output is a synthetic clip."""

    def __init__(self, output: Path, *results, submit_errors=()):
        self.output = output
        self.results = list(results) or [RequestStatus(status="completed", video_url="https://cdn.example/out.mp4")]
        self.submit_errors = list(submit_errors)
        self.submits: list[dict] = []
        self.waits: list[str] = []
        self.downloads: list[str] = []

    def submit_object_swap(self, *, video_url, image_urls, prompt, resolution, idempotency_key):
        self.submits.append({"video_url": video_url, "image_urls": image_urls, "prompt": prompt, "resolution": resolution, "key": idempotency_key})
        if self.submit_errors:
            raise self.submit_errors.pop(0)
        n = len(self.submits)
        return Submitted(request_id=f"REQ{n}", status_url=f"https://api.higgsfield.ai/requests/REQ{n}/status", status="queued")

    def wait(self, status_url, timeout_s=None):
        self.waits.append(status_url)
        r = self.results.pop(0)
        if isinstance(r, Exception):
            raise r
        return r

    def download(self, url, dest):
        self.downloads.append(url)
        Path(dest).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(self.output, dest)
        return Path(dest)


def make_store(**settings) -> MemoryStore:
    store = MemoryStore(settings=Settings(**settings) if settings else None)
    store.add_character(Character(slug="biscuit", name="Biscuit", bodies=[Body.biped, Body.quadruped]))
    store.add_character(Character(slug="reginald", name="Reginald", bodies=[Body.biped]))
    return store


@pytest.fixture
def world(tmp_path):
    return make_store(), LocalStorage(tmp_path / "storage")


def drop_file(store, storage, clip: Path, slug="reginald"):
    """What the terminal does for a file: add_drop, the upload to sources/owner/<pick>/, attach_clip, request_job process."""
    pick, dup = add_drop(store, slug, None, NOW)
    assert not dup and pick.proposal["drop"]["state"] == "uploading"
    path = f"owner/{pick.id}/1759700000000.mp4"
    storage.upload("sources", path, clip)
    f = store.get_favorite(pick.id)
    store.update_favorite(pick.id, proposal={**f.proposal, "owner_clip_path": path, "drop": {**f.proposal["drop"], "state": "checking"}})
    return pick.id


def tap_make(store, pick_id, adjust=None, at=None):
    """What request_job(pick, 'make') writes: the owner's record, the Adjust and the state."""
    f = store.get_favorite(pick_id)
    d = {**f.proposal["drop"], "state": "making"}
    if adjust is not None:
        d["adjust"] = adjust
    store.update_favorite(pick_id, proposal={**f.proposal, "drop": d, "make_requested": {"at": (at or NOW).isoformat(), "by": "owner"}})


def ffmpeg(*args):
    p = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y", *args], capture_output=True, text=True)
    assert p.returncode == 0, p.stderr[-400:]


@pytest.fixture
def portrait(synth_video):
    """A short vertical clip: its window is the whole 7 s (shorter than the 8-10 s target), which keeps the encodes quick."""
    return synth_video(w=540, h=960, dur=7)


@pytest.fixture
def gen_out(synth_video):
    """What the fake Object swap returns: 6.5 s, the shortest a master may be (6 s) with a margin."""
    return synth_video(w=540, h=960, dur=6.5)


@pytest.fixture
def fast_master(monkeypatch, synth_video):
    """The master build replaced by a copy of a ready 1080x1920 master (the real build runs in the main path and the
    lost-audio test): the other make tests are about the steps around it. The specs it was given are kept."""
    ready = synth_video(w=1080, h=1920, dur=7)
    specs = []

    def build(spec):
        specs.append(spec)
        Path(spec.out).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ready, spec.out)
        return Path(spec.out)

    monkeypatch.setattr(drop, "build_master", build)
    return specs


def ready_drop(store, storage, clip, slug="reginald", **look):
    pid = drop_file(store, storage, clip, slug)
    out = process_drop(store, storage, pid, gemini_client=FakeGemini(deconstruct(**look)), now=NOW, job="t")
    assert out.state == "ready", out
    return pid


# ---- process: free, and it ends ready or with one line why not -------------------------------------------------------------


def test_a_dropped_file_is_checked_priced_and_ready_with_a_preview(world, synth_video):
    store, storage = world
    portrait = synth_video(w=540, h=960, dur=10)
    pid = drop_file(store, storage, portrait)
    g = FakeGemini(deconstruct())
    out = process_drop(store, storage, pid, gemini_client=g, now=NOW, job="t")
    assert out.ok and out.state == "ready"
    pick = store.get_favorite(pid)
    d = pick.proposal["drop"]
    assert d["state"] == "ready" and d["reason"] is None and "job" not in d  # the lease is given back
    assert 8.0 <= d["window"]["length_s"] <= 10.0 and d["window"]["start_s"] + d["window"]["length_s"] <= 10.05
    assert d["credits"] == drop.estimate_credits("dropin", d["window"]["length_s"], "original")
    assert d["crop_x"] is None  # a vertical clip is not cropped
    assert d["hook"] == "The household is unaware." and d["part"] == "featured" and d["gadgets"] == ["black umbrella"]
    assert d["preview_path"] == f"owner/{pid}/preview.jpg" and (Path(storage.root) / "sources" / d["preview_path"]).is_file()
    assert pick.proposal["hook"] == d["hook"] and pick.proposal["concept"].startswith("a man in a suit")
    assert pick.proposal["analysis"]["people_count"] == 1 and pick.proposal["analysis"]["minors"] is False
    src = next(iter(store.list_sources(id=pick.source_id)))
    assert (src.has_watermark, src.has_overlay, src.has_minors, src.other_people) == (False, False, False, 0)
    # only the clip (a small proxy, not the original) and our prompt went to Gemini
    (call,) = g.calls
    assert call["mime"] == "video/mp4" and call["media"].name == "proxy.mp4" and "Reginald" in call["prompt"]
    assert call["size"] < portrait.stat().st_size
    assert pick.status == "approved" and store.list_clips() == []  # nothing made, nothing reserved
    assert store.ledger_month(NOW.strftime("%Y-%m")) == []


def test_a_classic_gets_the_longer_section(world, synth_video):
    store, storage = world
    clip = synth_video(w=540, h=960, dur=16)
    pid = ready_drop(store, storage, clip, classic=True, moment_name="Singin' in the Rain")
    assert 12.0 <= store.get_favorite(pid).proposal["drop"]["window"]["length_s"] <= 15.0


def test_a_landscape_clip_is_cropped_around_the_star(world, synth_video):
    store, storage = world
    pid = ready_drop(store, storage, synth_video(w=960, h=540, dur=10), star={**deconstruct()["star"], "x_center": 0.3})
    d = store.get_favorite(pid).proposal["drop"]
    assert d["crop_x"] == 0.3
    # the card's cover and watch copy are the same 9:16 crop around the star
    assert probe(Path(storage.root) / "sources" / d["preview_video_path"], loudness=False).width == 540


# ---- what the owner sees on a clip card (terminal v3 Task 11): a cover and a short watch copy of the section, never a reason to fail


def moov_first(path: Path) -> bool:
    """faststart: the MP4's ``moov`` box comes before its ``mdat`` (a phone starts playing before the whole file is in)."""
    data, i, names = Path(path).read_bytes(), 0, []
    while i + 8 <= len(data):
        size = int.from_bytes(data[i : i + 4], "big")
        names.append(data[i + 4 : i + 8])
        size = int.from_bytes(data[i + 8 : i + 16], "big") if size == 1 else (len(data) - i if size == 0 else size)
        if size < 8:
            break
        i += size
    return b"moov" in names and b"mdat" in names and names.index(b"moov") < names.index(b"mdat")


def test_the_check_writes_the_cards_cover_and_a_short_watch_copy_of_the_section(world, synth_video):
    from PIL import Image

    store, storage = world
    pid = ready_drop(store, storage, synth_video(w=540, h=960, dur=10))
    d = store.get_favorite(pid).proposal["drop"]
    assert d["cover_path"] == f"owner/{pid}/cover.jpg" and d["preview_video_path"] == f"owner/{pid}/preview.mp4"  # next to the strip
    assert d["preview_path"] == f"owner/{pid}/preview.jpg"
    root = Path(storage.root) / "sources"
    with Image.open(root / d["cover_path"]) as img:
        assert img.format == "JPEG" and img.size == (540, 960)
    r = probe(root / d["preview_video_path"], loudness=False)
    assert (r.width, r.height) == (540, 960) and r.video_codec == "h264"
    assert r.duration_s == pytest.approx(d["window"]["length_s"], abs=0.1)  # the section only
    assert r.has_audio and r.audio_codec == "aac"  # the clip's own sound
    assert moov_first(root / d["preview_video_path"])


def test_the_watch_copy_of_a_silent_clip_is_silent(world, synth_video):
    store, storage = world
    pid = ready_drop(store, storage, synth_video(w=540, h=960, dur=7, audio=False))
    d = store.get_favorite(pid).proposal["drop"]
    assert not probe(Path(storage.root) / "sources" / d["preview_video_path"], loudness=False).has_audio


class FlakyStorage(LocalStorage):
    """Our own Storage refusing the card's cover and watch copy (and nothing else)."""

    def upload(self, bucket, path, file):
        if path.endswith(("/cover.jpg", "/preview.mp4")):
            raise StorageError(f"storage POST {bucket}/{path} failed: 503", 503)
        return super().upload(bucket, path, file)


def test_a_cover_or_watch_copy_that_fails_never_fails_the_check(world, portrait, monkeypatch, caplog, tmp_path):
    store, storage = world
    pid = ready_drop(store, storage, portrait)  # a first check made both
    assert store.get_favorite(pid).proposal["drop"]["preview_video_path"]

    def boom(*a, **k):
        raise drop.clipwork.ClipworkError("ffmpeg failed (1): no")

    def full(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(drop.clipwork, "preview_video", boom)
    monkeypatch.setattr(drop.clipwork, "cover_frame", full)
    drop.request_recheck(store, pid, NOW)
    with caplog.at_level("WARNING", logger="studio.drop"):
        out = process_drop(store, storage, pid, gemini_client=FakeGemini(deconstruct()), now=NOW, job="t")
    d = store.get_favorite(pid).proposal["drop"]
    assert out.ok and out.state == d["state"] == "ready" and d["reason"] is None
    assert d.get("cover_path") is None and d.get("preview_video_path") is None  # null: never the last check's paths
    assert d["preview_path"] == f"owner/{pid}/preview.jpg" and d["credits"] > 0  # the rest of the check is as always
    assert "the watch copy" in caplog.text and "the cover" in caplog.text and "ffmpeg failed" in caplog.text
    # our Storage refusing them is no reason either
    monkeypatch.undo()
    flaky = FlakyStorage(tmp_path / "flaky")
    other = drop_file(store, flaky, portrait)
    out = process_drop(store, flaky, other, gemini_client=FakeGemini(deconstruct()), now=NOW, job="t")
    d = store.get_favorite(other).proposal["drop"]
    assert out.state == "ready" and d.get("cover_path") is None and d.get("preview_video_path") is None and d["preview_path"]


def strip_watch(store, storage, pick_id):
    """A drop checked before Task 11: no cover, no watch copy (on the card or in Storage)."""
    f = store.get_favorite(pick_id)
    d = {k: v for k, v in f.proposal["drop"].items() if k not in ("cover_path", "preview_video_path")}
    store.update_favorite(pick_id, proposal={**f.proposal, "drop": d})
    for name in ("cover.jpg", "preview.mp4"):
        storage.delete("sources", f"owner/{pick_id}/{name}")


def test_drop_previews_backfills_the_clips_checked_before_and_only_those(monkeypatch, tmp_path, portrait):
    store, storage = make_store(), LocalStorage(tmp_path / "s")
    monkeypatch.setattr(drop, "open_store", lambda: store)
    monkeypatch.setattr(drop, "open_storage", lambda: storage)

    def paid(*a, **k):
        pytest.fail("drop previews is free: no Gemini, no Higgsfield")

    monkeypatch.setattr(drop.gemini.GeminiClient, "from_env", paid)
    monkeypatch.setattr(drop.HiggsfieldClient, "from_env", paid)
    old = ready_drop(store, storage, portrait)
    strip_watch(store, storage, old)
    made = ready_drop(store, storage, portrait)
    tap_make(store, made)  # making: its card still shows, so it gets them too
    strip_watch(store, storage, made)
    has_them = ready_drop(store, storage, portrait)
    untouched = store.get_favorite(has_them)
    checking = drop_file(store, storage, portrait)  # no section yet: the check makes them
    gone = ready_drop(store, storage, portrait)
    strip_watch(store, storage, gone)
    store.update_source(store.get_favorite(gone).source_id, storage_path=None)  # its clip was deleted
    removed = ready_drop(store, storage, portrait)
    strip_watch(store, storage, removed)
    store.update_favorite(removed, status="skipped")  # removed by the owner: no card, and retention never sweeps it
    r = CliRunner().invoke(app, ["drop", "previews", "--missing"])
    assert r.exit_code == 0, r.output
    assert json.loads(r.output) == {"made": [old, made], "skipped": []}
    root = Path(storage.root) / "sources"
    for pid in (old, made):
        d = store.get_favorite(pid).proposal["drop"]
        assert d["cover_path"] == f"owner/{pid}/cover.jpg" and d["preview_video_path"] == f"owner/{pid}/preview.mp4"
        assert (root / d["cover_path"]).is_file() and (root / d["preview_video_path"]).is_file()
        rep = probe(root / d["preview_video_path"], loudness=False)
        assert (rep.width, rep.height) == (540, 960) and rep.duration_s == pytest.approx(d["window"]["length_s"], abs=0.1)
    assert store.get_favorite(made).proposal["drop"]["state"] == "making" and store.get_favorite(made).proposal["make_requested"]
    assert store.get_favorite(has_them) == untouched
    for pid in (gone, removed):
        assert "preview_video_path" not in store.get_favorite(pid).proposal["drop"]
    assert "cover_path" not in store.get_favorite(checking).proposal["drop"]
    r = CliRunner().invoke(app, ["drop", "previews", "--missing"])
    assert json.loads(r.output) == {"made": [], "skipped": []}  # nothing missing any more
    # one named pick: made again when it has them; a reason when it cannot, exit 2
    r = CliRunner().invoke(app, ["drop", "previews", "--pick", has_them])
    assert r.exit_code == 0 and json.loads(r.output) == {"made": [has_them], "skipped": []}
    for pid, reason in ((checking, "no section"), (gone, "not in Storage"), ("nope", "unknown pick nope")):
        r = CliRunner().invoke(app, ["drop", "previews", "--pick", pid])
        assert r.exit_code == 2, r.output
        (skip,) = json.loads(r.output)["skipped"]
        assert skip["pick_id"] == pid and reason in skip["reason"]
    for args in ([], ["--pick", old, "--missing"]):
        r = CliRunner().invoke(app, ["drop", "previews", *args])
        assert r.exit_code == 2 and "--pick" in r.output and "--missing" in r.output


@pytest.mark.parametrize(
    ("look", "reason"),
    [
        ({"star": {"kind": "person", "body": "biped", "description": "the boy in the middle", "x_center": 0.5, "full_body": True, "child": True}},
         "the star is a child: our character only replaces an adult"),
        ({"watermark": True}, "every usable section: paste the link instead"),  # a flag with no span: the whole clip
        ({"burned_in_text": True}, "text or a watermark is on screen in every usable section"),
        ({"burned_in_text_spans": [{"start_s": 0, "end_s": 7}]}, "every usable section: Genjutsu would keep it"),
        ({"star": {"kind": "dog", "body": "quadruped", "description": "the dog", "x_center": 0.5, "full_body": True, "child": False}}, "Reginald replaces a person"),
        ({"star": {"kind": "none", "body": "biped", "description": "nobody", "x_center": 0.5, "full_body": False, "child": False}}, "nobody to replace"),
    ],
)
def test_a_clip_we_cannot_use_is_blocked_with_one_line(world, portrait, look, reason):
    store, storage = world
    pid = drop_file(store, storage, portrait)
    out = process_drop(store, storage, pid, gemini_client=FakeGemini(deconstruct(**look)), now=NOW, job="t")
    d = store.get_favorite(pid).proposal["drop"]
    assert out.state == d["state"] == "blocked" and reason in d["reason"]
    assert "credits" not in d and "window" not in d


def test_children_elsewhere_in_the_clip_do_not_block_it_and_are_recorded(world, portrait):
    """Owner 2026-10-06: "children are fine in a clip; only the star we replace must be an adult"."""
    store, storage = world
    pid = ready_drop(store, storage, portrait, minors=True)
    pick = store.get_favorite(pid)
    assert pick.proposal["drop"]["state"] == "ready" and pick.proposal["drop"]["reason"] is None
    assert pick.proposal["analysis"]["minors"] is True  # recorded on the clip check card
    assert next(iter(store.list_sources(id=pick.source_id))).has_minors is True


def test_biscuit_takes_a_dog_star_and_refuses_a_person(world, portrait):
    store, storage = world
    dog = {"kind": "dog", "body": "quadruped", "description": "the dachshund on the rug", "x_center": 0.5, "full_body": True, "child": False}
    pid = ready_drop(store, storage, portrait, slug="biscuit", star=dog)
    assert store.get_favorite(pid).proposal["drop"]["star"]["body"] == "quadruped"
    assert next(iter(store.list_sources(id=store.get_favorite(pid).source_id))).body is Body.quadruped
    other = drop_file(store, storage, portrait, slug="biscuit")
    out = process_drop(store, storage, other, gemini_client=FakeGemini(deconstruct()), now=NOW, job="t")
    assert out.state == "blocked" and "Biscuit replaces a dog or a small animal, this clip's star is a person" in out.reason


def test_a_video_under_six_seconds_is_blocked(world, synth_video):
    store, storage = world
    pid = drop_file(store, storage, synth_video(w=540, h=960, dur=5))
    out = process_drop(store, storage, pid, gemini_client=FakeGemini(), now=NOW, job="t")
    assert out.state == "blocked" and "at least 6 s" in out.reason


def test_without_the_gemini_key_it_waits_and_the_deconstruct_by_hand_finishes_it(world, portrait):
    store, storage = world
    pid = drop_file(store, storage, portrait)
    out = process_drop(store, storage, pid, gemini_client=None, now=NOW, job="t")
    d = store.get_favorite(pid).proposal["drop"]
    assert out.state == d["state"] == "checking" and "Gemini key" in d["reason"] and d["source_id"]
    assert out.detail["best_window"]["start_s"] >= 0  # the free analysis is there for the run that looks by hand
    out = process_drop(store, storage, pid, gemini_client=None, deconstruct_answer=deconstruct(), now=NOW, job="t")
    assert out.state == "ready" and len(store.list_sources()) == 1  # the same source, not a second one
    with pytest.raises(DropError, match="breaks the rules"):
        pid2 = drop_file(store, storage, portrait)
        process_drop(store, storage, pid2, gemini_client=None, deconstruct_answer=deconstruct(hooks=["one"]), now=NOW, job="t")


def test_a_gemini_failure_is_recorded_and_a_block_is_final(world, portrait):
    store, storage = world
    pid = drop_file(store, storage, portrait)
    out = process_drop(store, storage, pid, gemini_client=FakeGemini(GeminiError("HTTP 503")), now=NOW, job="t")
    assert not out.ok and out.state == "failed" and "tap Try again" in out.reason
    pid2 = drop_file(store, storage, portrait)
    out = process_drop(store, storage, pid2, gemini_client=FakeGemini(GeminiBlocked("SAFETY")), now=NOW, job="t")
    assert out.state == "blocked"


def test_an_unfinished_upload_waits(world):
    store, storage = world
    pick, _ = add_drop(store, "reginald", None, NOW)
    out = process_drop(store, storage, pick.id, gemini_client=FakeGemini(), now=NOW, job="t")
    assert out.state == "uploading" and "upload" in out.reason and store.list_sources() == []


def test_a_link_the_cloud_cannot_fetch_waits_for_the_mac_and_is_never_a_recreate(world):
    store, storage = world
    pick, dup = add_drop(store, "reginald", TIKTOK, NOW)
    assert not dup and pick.creator_handle == "@dancer.one" and pick.proposal["drop"]["state"] == "checking"

    def fail_runner(cmd):
        return subprocess.CompletedProcess(cmd, 1, "", "ERROR: [TikTok] login required")

    out = process_drop(store, storage, pick.id, gemini_client=FakeGemini(), runner=fail_runner, now=NOW, job="t")
    f = store.get_favorite(pick.id)
    assert out.state == f.proposal["drop"]["state"] == "waiting" and "the Mac's daily run tries again" in out.reason
    assert "fetch_failed" not in f.proposal and f.proposal.get("mode") != "recreate"
    assert [p["pick_id"] for p in pending(store)] == []
    assert pending(store, include_waiting=True) == [{"pick_id": pick.id, "job": "process", "state": "waiting"}]


def test_a_link_that_is_fetched_is_checked_like_a_file(world, portrait):
    store, storage = world
    pick, _ = add_drop(store, "reginald", TIKTOK, NOW)

    def runner(cmd):
        template = cmd[cmd.index("-o") + 1]
        target = Path(template.replace("%(ext)s", "mp4"))
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(portrait, target)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    out = process_drop(store, storage, pick.id, gemini_client=FakeGemini(deconstruct(watermark=True)), runner=runner, now=NOW, job="t")
    assert out.state == "blocked" and "we cannot use this clip" in out.reason  # a link's watermark: no "paste the link"
    for leftover in (Path(drop.fetch.FETCHED_DIR) / f"{pick.id}.mp4",):
        leftover.unlink(missing_ok=True)


def test_a_second_run_on_the_same_drop_is_busy(world, portrait):
    store, storage = world
    pid = drop_file(store, storage, portrait)
    assert drop.claim(store, pid, "process", "other-run", NOW)
    out = process_drop(store, storage, pid, gemini_client=FakeGemini(deconstruct()), now=NOW, job="t")
    assert out.detail["busy"] and out.state == "checking"
    assert pending(store) == []  # the lease hides it from the sweep
    later = NOW + timedelta(minutes=drop.LEASE_MINUTES + 1)
    assert [p["job"] for p in pending(store, now=later)] == ["process"]  # an abandoned lease expires


# ---- three sweep workers in parallel (task 12): each has its own job id, so the lease tells them apart ---------------------------


def test_the_job_id_carries_the_sweep_worker_so_two_workers_of_one_run_differ(monkeypatch):
    monkeypatch.setenv("GITHUB_RUN_ID", "123")
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "2")
    monkeypatch.delenv("STUDIO_WORKER", raising=False)
    assert drop.job_id() == "gh-123-2"  # no STUDIO_WORKER (a test, a hand run): the bare run id
    ids = []
    for worker in ("1", "2", "3"):
        monkeypatch.setenv("STUDIO_WORKER", worker)
        ids.append(drop.job_id())
    assert ids == ["gh-123-2-w1", "gh-123-2-w2", "gh-123-2-w3"]
    # the workflow exports STUDIO_WORKER on every run, so a dispatched run (one pick, matrix value 1) is "-w1" on GitHub: harmless
    monkeypatch.setenv("STUDIO_WORKER", "1")
    assert drop.job_id() == "gh-123-2-w1"
    monkeypatch.setenv("STUDIO_WORKER", "  ")
    assert drop.job_id() == "gh-123-2"  # an empty value is no worker
    monkeypatch.delenv("GITHUB_RUN_ID")
    monkeypatch.setenv("STUDIO_WORKER", "2")
    assert "-w2" not in drop.job_id()  # off GitHub the machine and the process already tell runs apart


def test_a_drop_that_still_needs_its_clip_downloaded_is_told_from_one_that_does_not(world, portrait):
    """Final review M6: which rows a sweep worker other than the first leaves alone."""
    store, storage = world
    link, _ = add_drop(store, "reginald", TIKTOK, NOW)  # a pasted link: its clip is still to be downloaded
    assert drop.needs_fetch(store, link) is True
    auto, _ = add_drop(store, None, TIKTOK.replace("7688386199270001953", "7688386199270009999"), NOW, auto_filed=True, hit={"id": "h", "lane": "reginald"})
    assert drop.needs_fetch(store, auto) is True
    pid = drop_file(store, storage, portrait)  # an owner's upload: nothing to download
    assert drop.needs_fetch(store, store.get_favorite(pid)) is False
    unfinished, _ = add_drop(store, "reginald", None, NOW)  # a file drop whose upload is still to come
    assert drop.needs_fetch(store, unfinished) is False
    src = sources.add_source(store, "owner_inbox", None, "biped", 1, 20.0, storage_path="fetched/x.mp4")
    store.update_favorite(link.id, source_id=src.id)  # a link whose clip is already in storage is checked from there
    assert drop.needs_fetch(store, store.get_favorite(link.id)) is False


def test_pending_leaves_out_the_rows_that_need_a_download_when_asked(world, portrait):
    store, storage = world
    link, _ = add_drop(store, "reginald", TIKTOK, NOW)
    upload = drop_file(store, storage, portrait)
    ready = ready_drop(store, storage, portrait)
    tap_make(store, ready)
    both = {p["pick_id"]: p["job"] for p in pending(store, now=NOW)}
    assert both == {link.id: "process", upload: "process", ready: "make"}
    assert pending(store, now=NOW, fetches=False) == [p for p in pending(store, now=NOW) if p["pick_id"] != link.id]  # same order


@pytest.mark.parametrize(("worker", "takes"), [("1", True), ("2", False), ("3", False), (None, True), ("  ", True)])
def test_only_the_first_sweep_worker_takes_a_drop_that_needs_a_download(monkeypatch, tmp_path, portrait, worker, takes):
    """CLAUDE.md: an auto-filed clip is fetched ONE at a time. Three workers list the same rows; workers 2 and 3 go on to the rest."""
    store, storage = sweep_world(monkeypatch, tmp_path)
    link, _ = add_drop(store, "reginald", TIKTOK, NOW)
    upload = drop_file(store, storage, portrait)
    if worker is None:
        monkeypatch.delenv("STUDIO_WORKER", raising=False)
    else:
        monkeypatch.setenv("STUDIO_WORKER", worker)
    ran = []
    monkeypatch.setattr(drop, "process_drop", lambda s, st, pick_id, **kw: ran.append(pick_id) or drop.Outcome(pick_id, "ready"))
    r = CliRunner().invoke(app, ["drop", "sweep"])
    assert r.exit_code == 0, r.output
    assert sorted(ran) == sorted([link.id, upload] if takes else [upload])
    assert drop.takes_downloads() is takes


def test_a_failed_check_with_its_clip_already_in_storage_is_retaken_by_any_worker(monkeypatch, tmp_path, portrait):
    store, storage = sweep_world(monkeypatch, tmp_path)
    pid = failed_check(store, storage, portrait, TIMEOUT_REASON)  # an uploaded clip: nothing to download
    monkeypatch.setenv("STUDIO_WORKER", "3")
    ran = []
    monkeypatch.setattr(drop, "process_drop", lambda s, st, pick_id, **kw: ran.append(pick_id) or drop.Outcome(pick_id, "ready"))
    assert CliRunner().invoke(app, ["drop", "sweep"]).exit_code == 0 and ran == [pid]


def test_two_workers_of_the_same_run_never_take_the_same_drop(world, portrait):
    store, storage = world
    pid = drop_file(store, storage, portrait)
    assert drop.claim(store, pid, "process", "gh-9-1-w1", NOW)
    assert not drop.claim(store, pid, "process", "gh-9-1-w2", NOW)  # the second worker is refused
    assert drop.claim(store, pid, "process", "gh-9-1-w1", NOW)  # the same worker keeps its own lease (unchanged)
    out = process_drop(store, storage, pid, gemini_client=FakeGemini(deconstruct()), now=NOW, job="gh-9-1-w3")
    assert out.detail["busy"] and out.ok and out.state == "checking"


def sweep_world(monkeypatch, tmp_path, store=None):
    """The CLI's `drop sweep` on this store: no Gemini or Higgsfield client, no ScrapeCreators, the London clock at NOW."""
    store, storage = store or make_store(), LocalStorage(tmp_path / "s")
    monkeypatch.setattr(drop, "open_store", lambda: store)
    monkeypatch.setattr(drop, "open_storage", lambda: storage)
    monkeypatch.setattr(drop, "now_london", lambda: NOW)
    monkeypatch.setattr(drop, "_media", lambda store_: None)
    monkeypatch.setattr(drop.gemini.GeminiClient, "from_env", classmethod(lambda cls, env=None, **kw: None))
    monkeypatch.setattr(drop.HiggsfieldClient, "from_env", classmethod(lambda cls, env=None, **kw: None))
    return store, storage


def test_a_pick_another_worker_holds_is_busy_and_never_fails_the_sweep(monkeypatch, tmp_path, portrait):
    store, storage = sweep_world(monkeypatch, tmp_path)
    pid = drop_file(store, storage, portrait)
    real = drop.pending

    def listed_then_taken(*a, **kw):
        rows = real(*a, **kw)
        assert drop.claim(store, pid, "process", "gh-9-1-w2", NOW)  # worker 2 takes it after this worker listed it
        return rows

    monkeypatch.setattr(drop, "pending", listed_then_taken)
    monkeypatch.setenv("GITHUB_RUN_ID", "9")
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "1")
    monkeypatch.setenv("STUDIO_WORKER", "1")
    r = CliRunner().invoke(app, ["drop", "sweep"])
    assert r.exit_code == 0, r.output  # busy is not a failure
    (row,) = json.loads(r.output)["results"]
    assert row["busy"] is True and row["ok"] is True and row["state"] == "checking"


def test_a_drop_another_worker_finished_meanwhile_is_skipped_not_a_failure(monkeypatch, tmp_path, portrait):
    """Three workers list the same drops and walk them in the same order: by the time one reaches a drop another has finished,
    the drop is `ready` and a check refuses it (DropError). That is no failure of the sweep."""
    store, storage = sweep_world(monkeypatch, tmp_path)
    pid = ready_drop(store, storage, portrait)
    stale = [{"pick_id": pid, "job": "process", "state": "checking"}]  # what this worker listed before the other one finished it
    monkeypatch.setattr(drop, "pending", lambda *a, **kw: stale)
    ran = []
    monkeypatch.setattr(drop, "process_drop", lambda *a, **kw: ran.append(a) or drop.Outcome(pid, "ready"))
    r = CliRunner().invoke(app, ["drop", "sweep"])
    assert r.exit_code == 0, r.output
    (row,) = json.loads(r.output)["results"]
    assert row["pick_id"] == pid and row["ok"] is True and row["moved_on"] is True and ran == []
    # a hand-run check of a ready drop is still refused
    with pytest.raises(DropError, match="ready"):
        process_drop(store, storage, pid, gemini_client=FakeGemini(), now=NOW, job="t")


def test_a_check_another_worker_finishes_between_listing_and_claiming_is_not_run_twice(world, portrait, monkeypatch):
    store, storage = world
    pid = ready_drop(store, storage, portrait)
    real, reads = drop._load, []

    def load(store_, pick_id):
        pick = real(store_, pick_id)
        reads.append(pick_id)
        if len(reads) == 1:  # the read before the claim still sees the state the drop had when it was listed
            return dataclasses.replace(pick, proposal={**pick.proposal, "drop": {**pick.proposal["drop"], "state": "checking"}})
        return pick

    monkeypatch.setattr(drop, "_load", load)
    g = FakeGemini()
    out = process_drop(store, storage, pid, gemini_client=g, now=NOW, job="gh-9-1-w1")
    assert out.ok and out.detail["busy"] and out.state == "ready" and g.calls == []  # not looked at a second time
    assert "job" not in store.get_favorite(pid).proposal["drop"]  # the lease is given back


def test_an_expiry_is_taken_by_one_worker_only(monkeypatch, tmp_path):
    store, _ = sweep_world(monkeypatch, tmp_path)
    old = auto_link(store, NOW - timedelta(days=3), tried=[(NOW - timedelta(days=3)).date().isoformat()])
    stale = [{"pick_id": old.id, "job": "expire", "state": "waiting"}]
    monkeypatch.setattr(drop, "pending", lambda *a, **kw: [*stale, *stale])  # two workers reach it, one after the other
    r = CliRunner().invoke(app, ["drop", "sweep"])
    assert r.exit_code == 0, r.output
    first, second = json.loads(r.output)["results"]
    assert first["skipped"] is True and first["job"] == "expire" and first["ok"] is True  # expire_unfetched's own answer
    assert second["ok"] is True and second["moved_on"] is True  # the second finds it already skipped by the first
    assert store.get_favorite(old.id).status == "skipped" and "job" not in store.get_favorite(old.id).proposal["drop"]


def test_a_drop_is_never_in_the_daily_runs_queue(world, portrait):
    store, storage = world
    pid = ready_drop(store, storage, portrait)
    assert pid not in {f.id for f in next_favorites(store, 10)}


def test_add_drop_files_a_file_and_dedupes_a_link_per_character(world):
    store, _ = world
    a, _ = add_drop(store, "reginald", None, NOW)
    assert a.proposal["drop"]["own_footage"] is False  # owner 2026-10-06: a downloaded clip unless the owner says otherwise
    assert a.url == f"owner-drop:{a.id}" and a.platform == "drop" and a.origin == "owner" and a.status == "approved"
    assert a.proposal["decision"]["by"] == "owner" and a.proposal["decision"]["at"]
    first, dup1 = add_drop(store, "reginald", TIKTOK, NOW)
    again, dup2 = add_drop(store, "reginald", TIKTOK + "?is_from_webapp=1", NOW)
    other, dup3 = add_drop(store, "biscuit", TIKTOK, NOW)
    assert (dup1, dup2, dup3) == (False, True, False) and again.id == first.id and other.id != first.id
    with pytest.raises(ValueError):
        add_drop(store, "nobody", None, NOW)
    with pytest.raises(ValueError, match="short links"):
        add_drop(store, "reginald", "https://vm.tiktok.com/abc/", NOW)


def test_a_link_dropped_again_keeps_the_earlier_drops_keys_and_the_new_keys_win_like_migration_0017(world):
    """Final review M2: the CLI's duplicate path files the same drop as the terminal's studio.add_drop (0017), not a replacement."""
    store, _ = world
    first, _ = add_drop(store, "reginald", TIKTOK, NOW)
    earlier = {
        "state": "ready", "hooks": ["a", "b"], "window": {"start_s": 1, "length_s": 8}, "adjust": {"hook": "x"}, "own_footage": True,
        "score": 81, "hit_rules_version": 3, "auto_filed": True, "hit": {"id": "h", "lane": "general"}, "fetch_days": ["2026-10-10"],
        "trend_stage": "rising", "days_since_trend_peak": 4, "sound_rising": True,  # the hits job's LunarCrush reading at filing (task 18)
        "job": {"holder": "run-7", "at": NOW.isoformat()}, "reason": "old", "character_by": "studio",
    }
    store.update_favorite(first.id, proposal={**first.proposal, "hold_reason": "x", "drop": {**first.proposal["drop"], **earlier}})
    later = NOW + timedelta(hours=1)
    again, dup = add_drop(store, "reginald", TIKTOK, later)
    d = again.proposal["drop"]
    assert dup and again.id == first.id and again.status == "approved" and "hold_reason" not in again.proposal
    assert d["hooks"] == ["a", "b"] and d["window"] == {"start_s": 1, "length_s": 8} and d["adjust"] == {"hook": "x"}  # kept
    assert d["job"] == earlier["job"]  # a live worker's lease stays
    for gone in drop.MERGE_STRIP:  # describes the earlier drop, not this one
        assert gone not in d, gone
    assert set(drop.MERGE_STRIP) == {"score", "hit_rules_version", "auto_filed", "hit", "fetch_days", *drop.TREND_TAGS}
    assert d["state"] == "checking" and d["kind"] == "link" and d["reason"] is None and d["own_footage"] is False  # the new keys win
    assert d["character_by"] == "owner" and d["at"] == later.isoformat() and again.proposal["decision"]["at"] == later.isoformat()


def test_a_new_drops_own_tags_win_over_the_strip_and_a_drop_that_is_no_object_counts_as_empty(world):
    store, _ = world
    first, _ = add_drop(store, "reginald", TIKTOK, NOW)
    store.update_favorite(first.id, proposal={**first.proposal, "drop": {**first.proposal["drop"], "auto_filed": True, "score": 5}})
    again, _ = add_drop(
        store, "reginald", TIKTOK, NOW, auto_filed=True, hit={"id": "h2", "lane": "reginald"}, trend={"trend_stage": "peak", "sound_rising": False},
    )
    assert again.proposal["drop"]["auto_filed"] is True and again.proposal["drop"]["hit"] == {"id": "h2", "lane": "reginald"}
    assert again.proposal["drop"]["trend_stage"] == "peak" and again.proposal["drop"]["sound_rising"] is False  # the new reading wins
    assert "score" not in again.proposal["drop"]
    for junk in (None, [], "text", 7):  # a drop the studio never wrote: replaced, not merged
        store.update_favorite(first.id, proposal={**again.proposal, "drop": junk})
        out, dup = add_drop(store, "reginald", TIKTOK, NOW)
        assert dup and isinstance(out.proposal["drop"], dict) and out.proposal["drop"]["state"] == "checking", junk
        assert set(out.proposal["drop"]) == {"state", "kind", "at", "reason", "own_footage", "character_by"}, junk


def test_a_saved_file_is_dropped_from_the_mac_exactly_as_the_terminal_does(world, tmp_path):
    # owner 2026-10-06: "let's make some with the videos I saved" (inbox/drops): upload to sources/owner/<pick>/, attach
    store, storage = world
    clip = tmp_path / "SnapInsta-Ai_1_2.mp4"
    clip.write_bytes(b"\x00\x00\x00\x18ftypmp42 a saved clip")
    pick, _ = add_drop(store, "reginald", None, NOW)
    path = attach_file(store, storage, pick.id, clip, NOW)
    assert path == f"owner/{pick.id}/{int(NOW.timestamp() * 1000)}.mp4"
    assert store.get_favorite(pick.id).proposal["owner_clip_path"] == path
    back = storage.download("sources", path, tmp_path / "back.mp4")
    assert back.read_bytes() == clip.read_bytes()
    assert [p["pick_id"] for p in pending(store)] == [pick.id]  # an uploading drop with its file attached is taken by the next run
    with pytest.raises(DropError, match="not a video"):
        attach_file(store, storage, pick.id, tmp_path / "notes.txt", NOW)
    link, _ = add_drop(store, "reginald", TIKTOK, NOW)
    with pytest.raises(DropError, match="file drop"):
        attach_file(store, storage, link.id, clip, NOW)


def test_request_check_is_what_request_job_process_writes_once_the_file_is_attached(world, tmp_path):
    """The terminal's last step after its upload (``studio.request_job(pick, 'process')``, migration 0012); the clips folder takes it
    after ``attach_file`` too, so the drop leaves Uploading and the cloud sweep and the terminal see a drop waiting for its check."""
    store, storage = world
    clip = tmp_path / "a.mp4"
    clip.write_bytes(b"\x00\x00\x00\x18ftypmp42 a saved clip")
    pick, _ = add_drop(store, None, None, NOW)
    with pytest.raises(DropError, match="upload has not finished"):  # request_job's own refusal: no file attached yet
        drop.request_check(store, pick.id, NOW)
    attach_file(store, storage, pick.id, clip, NOW)
    assert store.get_favorite(pick.id).proposal["drop"]["state"] == "uploading"  # attaching alone does not ask for the check
    later = NOW + timedelta(minutes=3)
    out = drop.request_check(store, pick.id, later)
    d = out.proposal["drop"]
    assert d["state"] == "checking" and d["reason"] is None and d["at"] == later.isoformat() and d["requested"] == {"process": later.isoformat()}
    assert d["kind"] == "file" and d["character_by"] == "studio" and out.proposal["owner_clip_path"]  # nothing else is touched
    assert store.get_favorite(pick.id).proposal["drop"] == d
    again = drop.request_check(store, pick.id, later + timedelta(minutes=1))  # asking again is fine (the Try again button): the time moves
    assert again.proposal["drop"]["state"] == "checking" and again.proposal["drop"]["requested"]["process"] == (later + timedelta(minutes=1)).isoformat()
    # request_job's states: uploading, checking, waiting or failed; never a ready, blocked, making or made drop
    for state in ("ready", "blocked", "making", "made"):
        f = store.get_favorite(pick.id)
        store.update_favorite(pick.id, proposal={**f.proposal, "drop": {**f.proposal["drop"], "state": state}})
        with pytest.raises(DropError, match=f"is {state}"):
            drop.request_check(store, pick.id, NOW)
    for state in ("waiting", "failed"):
        f = store.get_favorite(pick.id)
        store.update_favorite(pick.id, proposal={**f.proposal, "drop": {**f.proposal["drop"], "state": state}})
        assert drop.request_check(store, pick.id, NOW).proposal["drop"]["state"] == "checking"
    store.update_favorite(pick.id, status="made")
    with pytest.raises(DropError, match="already made"):
        drop.request_check(store, pick.id, NOW)
    with pytest.raises(KeyError):
        drop.request_check(store, "nope", NOW)


def test_cli_drop_add_with_a_file_asks_for_the_check_like_the_terminal(monkeypatch, tmp_path):
    store = make_store()
    storage = LocalStorage(tmp_path / "storage")
    monkeypatch.setattr(drop, "open_store", lambda: store)
    monkeypatch.setattr(drop, "open_storage", lambda: storage)
    clip = tmp_path / "saved.mp4"
    clip.write_bytes(b"\x00\x00\x00\x18ftypmp42 a saved clip")
    r = CliRunner().invoke(app, ["drop", "add", "--file", str(clip)])
    assert r.exit_code == 0, r.output
    out = json.loads(r.output)
    assert out["owner_clip_path"] and out["drop"]["state"] == "checking" and out["drop"]["requested"]["process"]
    assert store.get_favorite(out["pick_id"]).proposal["drop"]["state"] == "checking"


# ---- the window --------------------------------------------------------------------------------------------------------------


def analysis(energy, cuts=(), beats=(), step=0.5):
    return {"motion": {"step_s": step, "energy": list(energy), "cuts": list(cuts)}, "audio": {"beats": list(beats)}}


def test_the_window_stays_in_one_shot_and_takes_the_liveliest_part():
    energy = [1.0] * 20 + [5.0] * 20 + [1.0] * 20  # 30 s, the lively part 10-20 s
    w = drop_window(analysis(energy, cuts=[9.0, 21.0]), classic=False, duration=30.0)
    assert 9.0 <= w["start_s"] and w["start_s"] + w["length_s"] <= 21.0 and 8.0 <= w["length_s"] <= 10.0
    classic = drop_window(analysis([2.0] * 60, cuts=[2.0]), classic=True, duration=30.0)
    assert 12.0 <= classic["length_s"] <= 15.0 and classic["start_s"] >= 2.0


def test_a_short_shot_shortens_the_window_but_never_under_six_seconds():
    w = drop_window(analysis([2.0] * 40, cuts=[7.0, 14.0]), classic=True, duration=20.0)
    assert w["length_s"] in (6.0, 6.5, 7.0) and (w["start_s"] >= 7.0 - 1e-9 or w["start_s"] + w["length_s"] <= 7.0 + 1e-9)
    tiny = drop_window(analysis([2.0] * 20, cuts=[3.0, 6.0]), classic=False, duration=10.0)
    assert tiny["length_s"] >= 6.0
    with pytest.raises(ValueError, match="at least 6 s"):
        drop_window(analysis([1.0] * 8), classic=False, duration=4.0)


def test_the_window_snaps_to_the_beat_when_it_stays_in_range():
    beats = [i * 0.5 + 0.12 for i in range(60)]
    w = drop_window(analysis([2.0] * 60, beats=beats), classic=False, duration=30.0)
    assert any(abs(w["start_s"] - b) < 1e-6 for b in beats) and 8.0 <= w["length_s"] <= 10.0


def test_drop_window_leaves_room_for_the_pause(monkeypatch):
    """Reginald's pause adds 0.4 s before the dance: his section is at most 16 - 0.4 s, so the master stays within 16 s."""
    flat = analysis([2.0] * 80)  # 40 s, one shot
    for classic in (True, False):
        assert drop_window(flat, classic=classic, duration=40.0, lead_s=0.4)["length_s"] + 0.4 <= drop.MASTER_MAX_S
    monkeypatch.setattr(drop, "WINDOW_CLASSIC", (14.0, 16.0))  # a longer classic target: then the cap is what holds
    assert drop_window(flat, classic=True, duration=40.0)["length_s"] == 16.0
    assert drop_window(flat, classic=True, duration=40.0, lead_s=0.4)["length_s"] == 15.5
    beats = [i * 0.5 + 0.1 for i in range(80)]
    snapped = drop_window(analysis([2.0] * 80, beats=beats), classic=True, duration=40.0, lead_s=0.4)
    assert snapped["length_s"] <= 15.6 + 1e-9  # snapping to the beat never takes the room back


def test_the_check_gives_the_pause_its_room_by_the_characters_kit(world, portrait, monkeypatch):
    store, storage = world
    asked = []
    real = drop.drop_window

    def spy(*args, **kw):
        asked.append(kw.get("lead_s", 0.0))
        return real(*args, **kw)

    monkeypatch.setattr(drop, "drop_window", spy)
    reginald = ready_drop(store, storage, portrait)  # Reginald: hook_edit pause
    dog = {"kind": "dog", "body": "quadruped", "description": "the dachshund on the rug", "x_center": 0.5, "full_body": True, "child": False}
    biscuit = ready_drop(store, storage, portrait, slug="biscuit", star=dog)  # Biscuit: no kit
    assert asked == [0.4, 0.0]
    # the card carries the longest section Make it will take for him, so the terminal's Adjust refuses the rest before Make it
    assert store.get_favorite(reginald).proposal["drop"]["max_length_s"] == 15.6
    assert store.get_favorite(biscuit).proposal["drop"]["max_length_s"] == 16.0


# ---- the owner's Adjust --------------------------------------------------------------------------------------------------------


def test_the_adjust_is_checked_again_and_fails_closed():
    d = {"duration_s": 20.0, "window": {"start_s": 2.0, "length_s": 9.0}, "width": 1920, "height": 1080}
    assert validate_adjust({"start_s": 4, "length_s": 12, "crop_x": 0.4, "part": "star", "gadgets": ["gold chain"]}, d) == {
        "start_s": 4.0, "length_s": 12.0, "crop_x": 0.4, "part": "star", "gadgets": ["gold chain"],
    }
    for bad, msg in (
        ({"length_s": 5}, "6-16 s"), ({"length_s": 17}, "6-16 s"), ({"start_s": 15, "length_s": 9}, "runs past the end"),
        ({"part": "lead"}, "adjust.part"), ({"gadgets": ["a", "b", "c", "d"]}, "at most 3"), ({"hook": "x" * 81}, "1-80"),
        ({"crop_x": 1.5}, "from 0 to 1"), ({"colour": "red"}, "unknown key"), ("start", "an object"),
    ):
        with pytest.raises(ValueError, match=msg):
            validate_adjust(bad, d)
    with pytest.raises(ValueError, match="already vertical"):
        validate_adjust({"crop_x": 0.5}, {**d, "width": 1080, "height": 1920})


def test_a_pause_characters_section_is_capped_so_the_master_stays_within_16_s():
    """Reginald's pause adds 0.4 s: the owner's section is at most 16 - 0.4 s for him, and still 16 s for a character without one."""
    d = {"duration_s": 30.0, "window": {"start_s": 2.0, "length_s": 9.0}}
    lead = drop.style_lead_s({"hook_edit": "pause"})
    assert lead == 0.4
    assert validate_adjust({"start_s": 0, "length_s": 15.6}, d, lead_s=lead) == {"start_s": 0.0, "length_s": 15.6}
    with pytest.raises(ValueError, match=r"6-15\.6 s.*0\.4 s.*within 16 s"):
        validate_adjust({"start_s": 0, "length_s": 15.7}, d, lead_s=lead)
    with pytest.raises(ValueError, match=r"6-15\.6 s"):
        validate_adjust({"start_s": 0, "length_s": 16}, d, lead_s=lead)
    assert validate_adjust({"start_s": 0, "length_s": 16}, d) == {"start_s": 0.0, "length_s": 16.0}  # no pause: today's 16 s
    assert drop.effective({**d, "adjust": {"length_s": 15.6}}, lead_s=lead)["length_s"] == 15.6
    with pytest.raises(ValueError, match=r"6-15\.6 s"):  # the same rule for the length the Adjust leaves alone
        validate_adjust({"start_s": 1}, {**d, "window": {"start_s": 2.0, "length_s": 15.8}}, lead_s=lead)


# ---- make: only after the owner's Make it --------------------------------------------------------------------------------------


def make(store, storage, pid, hf, g, **kw):
    return make_drop(store, storage, pid, hf=hf, gemini_client=g, now=kw.pop("now", NOW), job="t", preset="veryfast", **kw)


def test_no_make_it_no_credits(world, portrait, gen_out):
    store, storage = world
    pid = ready_drop(store, storage, portrait)
    hf = FakeHF(gen_out)
    with pytest.raises(DropError, match="no Make it from the owner"):
        make(store, storage, pid, hf, FakeGemini())
    f = store.get_favorite(pid)  # a forged state without the owner's record is refused too
    store.update_favorite(pid, proposal={**f.proposal, "drop": {**f.proposal["drop"], "state": "making"}, "make_requested": {"at": "yesterday", "by": "owner"}})
    with pytest.raises(DropError, match="no Make it"):
        make(store, storage, pid, hf, FakeGemini())
    store.update_favorite(pid, proposal={**f.proposal, "make_requested": {"at": NOW.isoformat(), "by": "owner"}})  # still ready
    with pytest.raises(DropError, match="is ready"):
        make(store, storage, pid, hf, FakeGemini())
    assert hf.submits == [] and store.list_clips() == [] and store.ledger_month(NOW.strftime("%Y-%m")) == []


def test_make_it_swaps_qas_masters_and_waits_for_the_owners_ok(world, portrait, gen_out, monkeypatch):
    monkeypatch.setattr("studio.media.master.stories_enabled", lambda: True)  # the Story video is built only with reach.stories on
    store, storage = world
    pid = ready_drop(store, storage, portrait)
    tap_make(store, pid)
    hf, g = FakeHF(gen_out), FakeGemini(QA_PASS)
    out = make(store, storage, pid, hf, g)
    assert out.ok and out.state == "made", out
    pick = store.get_favorite(pid)
    (clip,) = store.list_clips()
    assert clip.state is ClipState.awaiting_approval and pick.status == "made" and pick.clip_id == clip.id
    assert pick.proposal["drop"]["state"] == "made"
    # the one Object swap: our section, the character's images, a SHORT like-for-like prompt, 1080p, the key stored first
    (sub,) = hf.submits
    refs = {r["slug"]: r for r in drop.seed.load_refs()}
    assert sub["image_urls"] == drop.seed.reference_images(refs["reginald"], "biped") and sub["resolution"] == "1080p"
    assert sub["prompt"].startswith(  # the owner's two lines follow the first line, ahead of his part and gadgets
        "Replace the man in the grey suit with the butler from the reference images. Use the reference images for the character "
        "only. Keep the original's camera movement, framing, lighting and colour grading, and match its colour grading. "
        "He follows the original performer's motion exactly; the scene stays the same."
    )
    assert "black umbrella" in sub["prompt"] and len(sub["prompt"]) < 500
    assert sub["key"] == f"drop-{clip.id}-1" and pick.proposal["drop"]["make"]["idempotency_key"] == sub["key"]
    child = next(iter(store.list_sources(id=clip.source_id)))
    r = probe(Path(storage.root) / "sources" / child.storage_path, loudness=False)
    assert r.width * r.height >= 409_600 and abs(child.duration_s - pick.proposal["drop"]["window"]["length_s"]) < 0.3
    # money: one reserve, one settle of the estimate for the trimmed seconds
    ledger = store.ledger_month(NOW.strftime("%Y-%m"))
    assert [e.kind for e in ledger] == ["reserve", "settle"]
    est = drop.estimate_credits("dropin", child.duration_s, "original")
    assert ledger[0].credits == ledger[1].credits == est == clip.credits_actual
    # the master: uploaded, the post text of the deconstruct, the first comment, the owner's music rule
    assert clip.master_path == f"reginald/{clip.id}.mp4" and (Path(storage.root) / "clips" / clip.master_path).is_file()
    master = probe(Path(storage.root) / "clips" / clip.master_path)
    assert (master.width, master.height) == (1080, 1920) and master.has_audio and abs(master.lufs - -14) <= 1
    # and its labelled Story video next to it (a Story shows no caption: the AI label is in the picture)
    assert clip.features["story_path"] == f"reginald/{clip.id}-story.mp4"
    story = probe(Path(storage.root) / "clips" / clip.features["story_path"], loudness=False)
    assert (story.width, story.height) == (1080, 1920) and abs(story.duration_s - master.duration_s) <= 0.1
    assert clip.caption.splitlines()[0] == "Shoulder shimmy · butler edition" and clip.hook == "The household is unaware."
    assert clip.caption.splitlines()[2] == "Send this to your butler."  # the first engagement kind
    assert clip.hashtags == ["#shouldershimmy", "#butler", "#deadpan", "#oddeyes", "#asyouwere"]  # + Reginald's series tag
    assert clip.features["first_comment"].startswith("Requests for next week") and clip.features["music"] == "original"
    assert clip.features["fav_id"] == pid and clip.features["eye_closeup_end"] is False and clip.qa["problems"] == []
    assert g.calls[0]["mime"] == "image/jpeg"  # the frame QA saw a sheet of OUR output
    # asked again (a second tap or a sweep): nothing more is made or spent
    with pytest.raises(DropError, match="is made"):
        make(store, storage, pid, hf, g)
    assert len(hf.submits) == 1


def test_the_next_drop_of_the_character_rotates_the_engagement_line(world, portrait, gen_out, fast_master):
    store, storage = world
    for expected in ("Send this to your butler.", "Which eye did you notice first?"):
        pid = ready_drop(store, storage, portrait)
        tap_make(store, pid)
        assert make(store, storage, pid, FakeHF(gen_out), FakeGemini(QA_PASS)).state == "made"
        clip = store.get_clip(store.get_favorite(pid).clip_id)
        assert clip.caption.splitlines()[2] == expected


def make_clip(store, storage, pid, gen_out):
    tap_make(store, pid)
    assert make(store, storage, pid, FakeHF(gen_out), FakeGemini(QA_PASS)).state == "made"
    return store.get_clip(store.get_favorite(pid).clip_id)


def test_the_series_tag_is_written_into_the_clips_hashtags_when_it_is_made(world, portrait, gen_out, fast_master):
    """Stored = previewed = posted: the character's ``style.series_tag`` joins the hashtags at Make it, after the deconstruct's
    3-4 tags, so the terminal's post text already shows it and the publisher adds nothing."""
    store, storage = world
    clip = make_clip(store, storage, ready_drop(store, storage, portrait), gen_out)  # Reginald: #asyouwere
    assert clip.hashtags == ["#shouldershimmy", "#butler", "#deadpan", "#oddeyes", "#asyouwere"]
    drop.compose_content(clip.caption, clip.hashtags)  # and it is a post the publisher accepts as it stands


def test_the_series_tag_never_makes_a_sixth_hashtag(world, portrait, gen_out, fast_master):
    """A deconstruct stored before the 3-4 rule can carry 5 tags already: no room, so the clip keeps exactly those."""
    store, storage = world
    pid = ready_drop(store, storage, portrait)
    f = store.get_favorite(pid)
    full = ["#a", "#b", "#c", "#d", "#oddeyes"]
    d = {**f.proposal["drop"], "deconstruct": {**f.proposal["drop"]["deconstruct"], "hashtags": full}}
    store.update_favorite(pid, proposal={**f.proposal, "drop": d})
    assert make_clip(store, storage, pid, gen_out).hashtags == full


def test_the_same_clip_made_for_another_character_gets_that_characters_series_tag(world, portrait, gen_out, fast_master):
    """Made for Lenny (a version, or a drop the owner moved to him) it carries ``#yourewelcome``, never Reginald's tag."""
    store, storage = world
    store.add_character(Character(slug="lenny", name="Lenny Gold", bodies=[Body.biped]))
    tags = {}
    for slug in ("reginald", "lenny"):
        pid = ready_drop(store, storage, portrait, slug=slug, recommended={"slug": slug, "reason": "the shimmy suits him"})
        tags[slug] = make_clip(store, storage, pid, gen_out).hashtags
    assert tags["reginald"] == ["#shouldershimmy", "#butler", "#deadpan", "#oddeyes", "#asyouwere"]
    assert tags["lenny"] == ["#shouldershimmy", "#butler", "#deadpan", "#oddeyes", "#yourewelcome"]


def test_a_character_without_a_series_tag_keeps_the_deconstructs_hashtags(world, portrait, gen_out, fast_master):
    store, storage = world
    dog = {"kind": "dog", "body": "quadruped", "description": "the dachshund on the rug", "x_center": 0.5, "full_body": True, "child": False}
    pid = ready_drop(store, storage, portrait, slug="biscuit", star=dog)
    assert make_clip(store, storage, pid, gen_out).hashtags == ["#shouldershimmy", "#butler", "#deadpan", "#oddeyes"]


def test_a_made_drop_masters_in_its_characters_style(world, portrait, gen_out, fast_master):
    """The master is built with the character's kit (pill, entrance, hook edit, tone): the spec names him and carries his style."""
    store, storage = world
    refs = {r["slug"]: r for r in drop.seed.load_refs()}
    pid = ready_drop(store, storage, portrait)  # Reginald
    tap_make(store, pid)
    assert make(store, storage, pid, FakeHF(gen_out), FakeGemini(QA_PASS)).state == "made"
    (spec,) = fast_master
    assert spec.character == "reginald" and spec.style == refs["reginald"]["style"] and spec.style["hook_edit"] == "pause"


def test_a_character_without_a_kit_is_mastered_as_before(world, portrait, gen_out, fast_master):
    store, storage = world
    dog = {"kind": "dog", "body": "quadruped", "description": "the dachshund on the rug", "x_center": 0.5, "full_body": True, "child": False}
    pid = ready_drop(store, storage, portrait, slug="biscuit", star=dog)
    tap_make(store, pid)
    assert make(store, storage, pid, FakeHF(gen_out), FakeGemini(QA_PASS)).state == "made"
    (spec,) = fast_master
    assert spec.character == "biscuit" and spec.style is None  # no style block: the build finds no kit and masters as today


def test_a_reginald_make_it_cannot_pass_16_s_once_the_pause_is_added(world, synth_video):
    """The terminal accepts a 6-16 s section; for a pause character the CLI refuses more than 15.6 s before anything is spent."""
    store, storage = world
    store.add_character(Character(slug="franz", name="Franz", bodies=[Body.quadruped]))
    long_clip = synth_video(w=540, h=960, dur=18)
    dog = {"kind": "dog", "body": "quadruped", "description": "the dachshund on the rug", "x_center": 0.5, "full_body": True, "child": False}
    pid = ready_drop(store, storage, long_clip)  # Reginald: hook_edit pause
    tap_make(store, pid, adjust={"start_s": 0.0, "length_s": 15.8})
    out = make_drop(store, storage, pid, hf=None, gemini_client=None, now=NOW, job="t")
    assert out.state == "failed" and not out.ok and "the Adjust is not valid" in out.reason and "15.6 s" in out.reason
    assert store.list_clips() == [] and store.ledger_month(NOW.strftime("%Y-%m")) == []
    tap_make(store, pid, adjust={"start_s": 0.0, "length_s": 15.6})  # the longest that fits: accepted (waits for the key)
    out = make_drop(store, storage, pid, hf=None, gemini_client=None, now=NOW, job="t")
    assert out.state == "making" and "Higgsfield key" in out.reason
    franz = ready_drop(store, storage, long_clip, slug="franz", star=dog)  # Franz: no pause, so 16 s stays allowed
    tap_make(store, franz, adjust={"start_s": 0.0, "length_s": 16.0})
    out = make_drop(store, storage, franz, hf=None, gemini_client=None, now=NOW, job="t")
    assert out.state == "making" and "Higgsfield key" in out.reason


def test_the_owners_adjust_is_what_is_made(world, synth_video, gen_out, fast_master):
    store, storage = world
    pid = ready_drop(store, storage, synth_video(w=960, h=540, dur=14))
    tap_make(store, pid, adjust={"star": "the woman on the left", "part": "star", "gadgets": ["gold pocket watch"],
                                 "hook": "Tea is at four.", "start_s": 1.0, "length_s": 7.0, "crop_x": 0.2})
    hf = FakeHF(gen_out)
    assert make(store, storage, pid, hf, FakeGemini(QA_PASS)).state == "made"
    prompt = hf.submits[0]["prompt"]
    assert prompt.startswith("Replace the woman on the left with the butler") and "every beat" in prompt and "gold pocket watch" in prompt
    clip = store.get_clip(store.get_favorite(pid).clip_id)
    child = next(iter(store.list_sources(id=clip.source_id)))
    assert abs(child.duration_s - 7.0) < 0.3 and clip.hook == "Tea is at four."
    (spec,) = fast_master
    assert spec.closeup is None and spec.hook2 == ["Tea is at four."] and spec.music == "original" and spec.audio == spec.dance
    r = probe(Path(storage.root) / "sources" / child.storage_path, loudness=False)
    assert r.width < r.height  # the landscape clip was cropped to 9:16 (and scaled up to the minimum)


def test_the_kill_switch_and_the_cap_refuse_and_send_the_drop_back_to_ready(tmp_path, portrait, gen_out):
    for settings, word in (({"kill_switch": True}, "kill switch"), ({"monthly_cap_credits": 50}, "monthly cap")):
        store, storage = make_store(**settings), LocalStorage(tmp_path / word.replace(" ", "_"))
        pid = ready_drop(store, storage, portrait)
        tap_make(store, pid)
        hf = FakeHF(gen_out)
        out = make(store, storage, pid, hf, FakeGemini())
        pick = store.get_favorite(pid)
        assert not out.ok and out.detail["refused"] and word in out.reason
        assert pick.proposal["drop"]["state"] == "ready" and "make_requested" not in pick.proposal and pick.status == "approved"
        assert hf.submits == [] and store.ledger_month(NOW.strftime("%Y-%m")) == []
        assert [c.state for c in store.list_clips()] == [ClipState.dropped]


def test_one_automatic_reroll_after_a_failed_quality_check(world, portrait, gen_out, fast_master):
    store, storage = world
    pid = ready_drop(store, storage, portrait)
    tap_make(store, pid)
    hf = FakeHF(gen_out, RequestStatus(status="completed", video_url="https://cdn.example/1.mp4"),
                RequestStatus(status="completed", video_url="https://cdn.example/2.mp4"))
    out = make(store, storage, pid, hf, FakeGemini(QA_FAIL, QA_PASS))
    assert out.state == "made"
    clip = store.get_clip(store.get_favorite(pid).clip_id)
    assert clip.features["rerolls"] == 1 and [s["key"] for s in hf.submits] == [f"drop-{clip.id}-1", f"drop-{clip.id}-2"]
    kinds = [e.kind for e in store.ledger_month(NOW.strftime("%Y-%m"))]
    assert kinds == ["reserve", "settle", "reserve", "settle"]
    assert clip.credits_actual == 2 * drop.estimate_credits("dropin", next(iter(store.list_sources(id=clip.source_id))).duration_s)


def test_a_second_failed_quality_check_stops_and_flags_nothing_was_posted(world, portrait, gen_out):
    store, storage = world
    pid = ready_drop(store, storage, portrait)
    tap_make(store, pid)
    hf = FakeHF(gen_out, RequestStatus(status="completed", video_url="https://cdn.example/1.mp4"),
                RequestStatus(status="completed", video_url="https://cdn.example/2.mp4"))
    out = make(store, storage, pid, hf, FakeGemini(QA_FAIL, QA_FAIL))
    pick = store.get_favorite(pid)
    assert not out.ok and out.state == "failed" and "failed twice" in out.reason and "original man" in out.reason
    assert pick.status == "approved" and pick.proposal["drop"]["state"] == "failed" and len(hf.submits) == 2
    assert [c.state for c in store.list_clips()] == [ClipState.dropped]


def test_a_failed_job_is_released_and_the_drop_fails(world, portrait, gen_out):
    store, storage = world
    pid = ready_drop(store, storage, portrait)
    tap_make(store, pid)
    out = make(store, storage, pid, FakeHF(gen_out, RequestStatus(status="nsfw", error="moderation")), FakeGemini())
    assert out.state == "failed" and "nsfw" in out.reason
    assert [e.kind for e in store.ledger_month(NOW.strftime("%Y-%m"))] == ["reserve", "release"]
    assert budget.open_reservations(store, NOW) == []


def test_a_slow_job_is_polled_again_by_the_next_run_never_resubmitted(world, portrait, gen_out, fast_master):
    store, storage = world
    pid = ready_drop(store, storage, portrait)
    tap_make(store, pid)
    hf = FakeHF(gen_out, PollTimeout("still going", "https://api.higgsfield.ai/requests/REQ1/status", "in_progress"),
                RequestStatus(status="completed", video_url="https://cdn.example/1.mp4"))
    first = make(store, storage, pid, hf, FakeGemini(QA_PASS))
    assert first.state == "making" and "still working" in first.reason and len(hf.submits) == 1
    assert [p["job"] for p in pending(store)] == ["make"]
    second = make(store, storage, pid, hf, FakeGemini(QA_PASS))
    assert second.state == "made" and len(hf.submits) == 1 and hf.waits == [hf.waits[0]] * 2


def test_an_uncertain_submit_is_looked_up_with_the_same_key_and_body(world, portrait, gen_out, fast_master):
    store, storage = world
    pid = ready_drop(store, storage, portrait)
    tap_make(store, pid)
    hf = FakeHF(gen_out, submit_errors=[SubmitUncertain("timed out", "k")])
    first = make(store, storage, pid, hf, FakeGemini(QA_PASS))
    assert first.state == "making" and "same key" in first.reason and not first.ok
    second = make(store, storage, pid, hf, FakeGemini(QA_PASS))
    assert second.state == "made"
    a, b = hf.submits
    assert a == b  # the lookup: the identical body (the same signed URL) and the same Idempotency-Key


def test_without_the_higgsfield_key_nothing_is_reserved_and_the_drop_waits(world, portrait):
    store, storage = world
    pid = ready_drop(store, storage, portrait)
    tap_make(store, pid)
    out = make(store, storage, pid, None, FakeGemini())
    assert out.state == "making" and "Higgsfield key" in out.reason
    assert store.list_clips() == [] and store.ledger_month(NOW.strftime("%Y-%m")) == []


def test_by_hand_prepare_then_the_generated_file_and_the_qa_file(world, portrait, gen_out, fast_master):
    store, storage = world
    pid = ready_drop(store, storage, portrait)
    tap_make(store, pid)
    prepared = make(store, storage, pid, None, None, prepare=True)
    inputs = prepared.detail["inputs"]
    assert prepared.state == "making" and inputs["resolution"] == "1080p" and len(inputs["image_urls"]) == 3
    assert inputs["prompt"].startswith("Replace the man in the grey suit") and inputs["reserved"] > 0
    clip = store.get_clip(inputs["clip_id"])
    assert clip.state is ClipState.generating
    waiting = make(store, storage, pid, None, None, generated_file=gen_out, generated_credits=95)
    assert waiting.state == "making" and "--qa-file" in waiting.reason  # no Gemini: the frames by hand
    done = make(store, storage, pid, None, None, generated_file=gen_out, qa_answer={"pass": True, "problems": [], "visual": "eyes right"})
    assert done.state == "made"
    assert store.get_clip(clip.id).credits_actual == 95
    with pytest.raises(DropError, match="--credits only goes with"):
        make(store, storage, pid, None, None, generated_credits=10)


def test_a_lost_audio_track_is_put_back_from_the_section(world, portrait, synth_video):
    store, storage = world
    pid = ready_drop(store, storage, portrait)
    tap_make(store, pid)
    silent = synth_video(w=540, h=960, dur=6.5, audio=False)
    assert make(store, storage, pid, FakeHF(silent), FakeGemini(QA_PASS)).state == "made"
    clip = store.get_clip(store.get_favorite(pid).clip_id)
    assert probe(Path(storage.root) / "clips" / clip.master_path).has_audio


def test_a_crash_is_recorded_and_resumed_then_given_up_after_three(world, portrait, gen_out, monkeypatch):
    store, storage = world
    pid = ready_drop(store, storage, portrait)
    tap_make(store, pid)

    def boom(*a, **k):
        raise RuntimeError("ffmpeg vanished")

    monkeypatch.setattr(drop.sources, "trim_source", boom)
    for n in (1, 2):
        out = make(store, storage, pid, FakeHF(gen_out), FakeGemini())
        assert out.state == "making" and "the next run resumes" in out.reason and not out.ok, n
    out = make(store, storage, pid, FakeHF(gen_out), FakeGemini())
    assert out.state == "failed" and "stopped 3 times" in out.reason
    assert store.ledger_month(NOW.strftime("%Y-%m")) == []  # it stopped before any reserve


def test_pending_lists_what_a_run_should_take(world, portrait):
    store, storage = world
    checking = drop_file(store, storage, portrait)
    ready = ready_drop(store, storage, portrait)
    making = ready_drop(store, storage, portrait)
    tap_make(store, making)
    forged = ready_drop(store, storage, portrait)
    f = store.get_favorite(forged)
    store.update_favorite(forged, proposal={**f.proposal, "drop": {**f.proposal["drop"], "state": "making"}})  # no owner record
    rows = pending(store)
    assert {(r["pick_id"], r["job"]) for r in rows} == {(checking, "process"), (making, "make")}
    assert ready not in {r["pick_id"] for r in rows}


# ---- the CLI ------------------------------------------------------------------------------------------------------------------


def test_cli_make_refuses_without_the_owners_tap_and_pending_counts(monkeypatch, tmp_path, portrait):
    store, storage = make_store(), LocalStorage(tmp_path / "s")
    pid = ready_drop(store, storage, portrait)
    monkeypatch.setattr(drop, "open_store", lambda: store)
    monkeypatch.setattr(drop, "open_storage", lambda: storage)
    monkeypatch.delenv("HF_API_KEY_ID", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    r = CliRunner().invoke(app, ["drop", "make", pid])
    assert r.exit_code == 2 and "no Make it from the owner" in r.output
    r = CliRunner().invoke(app, ["drop", "pending", "--count"])
    assert r.exit_code == 0 and r.output.strip() == "0"
    tap_make(store, pid)
    r = CliRunner().invoke(app, ["drop", "pending"])
    assert json.loads(r.output) == [{"pick_id": pid, "job": "make", "state": "making"}]
    r = CliRunner().invoke(app, ["drop", "sweep"])
    assert r.exit_code == 0 and json.loads(r.output)["results"][0]["reason"].startswith("waiting for the Higgsfield key")
    r = CliRunner().invoke(app, ["drop", "make", "not-a-pick"])
    assert r.exit_code == 2 and "unknown pick" in r.output


def test_check_keys_asks_both_services_for_free_and_never_shows_a_key():
    import httpx

    urls: list[str] = []

    def higgsfield(request: httpx.Request) -> httpx.Response:
        urls.append(f"{request.method} {request.url}")
        return httpx.Response(404, json={"detail": "Request not found"})  # an unknown request: the key was accepted

    def google(request: httpx.Request) -> httpx.Response:
        urls.append(f"{request.method} {request.url}")
        return httpx.Response(400, json={"error": {"message": "API key not valid. Please pass a valid API key.", "status": "INVALID_ARGUMENT"}})

    env = {"HF_API_KEY_ID": "kid-9", "HF_API_KEY_SECRET": "very-secret", "GEMINI_API_KEY": "AIza-secret"}
    out = drop.check_keys(env, hf_transport=httpx.MockTransport(higgsfield), gemini_transport=httpx.MockTransport(google))
    assert out["higgsfield"] == "ok" and out["gemini"].startswith("invalid: HTTP 400")
    assert all(u.startswith("GET ") for u in urls) and len(urls) == 2  # two reads, nothing submitted
    assert not any(secret in json.dumps(out) for secret in ("kid-9", "very-secret", "AIza-secret"))


def test_cli_check_keys_exits_1_unless_both_keys_are_ok(monkeypatch):
    for name in ("HF_API_KEY_ID", "HF_API_KEY_SECRET", "GEMINI_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    r = CliRunner().invoke(app, ["drop", "check-keys"])
    assert r.exit_code == 1
    out = json.loads(r.output)
    assert out["higgsfield"].startswith("missing:") and out["gemini"].startswith("missing:")
    monkeypatch.setattr(drop, "check_keys", lambda: {"higgsfield": "ok", "gemini": "ok"})
    r = CliRunner().invoke(app, ["drop", "check-keys"])
    assert r.exit_code == 0 and json.loads(r.output) == {"higgsfield": "ok", "gemini": "ok"}


def test_the_prompts_view_of_each_roster_character_reads_its_bible():
    """Owner 2026-10-06 roster: the caption title's edition word comes from the bible (Lenny's swap noun is "Hollywood agent")."""
    for slug, noun, edition in (("franz", "dachshund", "dachshund"), ("reginald", "butler", "butler"), ("lenny", "Hollywood agent", "agent")):
        _, who = drop.character(slug)
        assert (who.noun, who.edition) == (noun, edition), slug
        assert who.voice and who.keywords and who.traits.get("never"), slug


def test_the_own_footage_flag_is_kept_through_the_check_and_never_reaches_the_swap(world, portrait):
    """Owner 2026-10-06: "own footage" (his recording, or footage used with permission) or a "downloaded clip" (the default): for
    reporting later, nothing in the generation reads it."""
    store, storage = world
    own, _ = add_drop(store, "reginald", None, NOW, own_footage=True)
    assert own.proposal["drop"]["own_footage"] is True
    pid = drop_file(store, storage, portrait)
    assert store.get_favorite(pid).proposal["drop"]["own_footage"] is False
    drop.set_own_footage(store, pid, True)
    out = process_drop(store, storage, pid, gemini_client=FakeGemini(deconstruct()), now=NOW, job="t")
    assert out.state == "ready" and store.get_favorite(pid).proposal["drop"]["own_footage"] is True
    drop.set_own_footage(store, pid, False)
    assert store.get_favorite(pid).proposal["drop"]["own_footage"] is False
    with pytest.raises(ValueError, match="true or false"):
        drop.set_own_footage(store, pid, "yes")
    scan_pick = store.add_favorite(drop.Favorite(url=TIKTOK, platform="tiktok", character_slug="reginald", status="approved"))
    with pytest.raises(DropError, match="not a dropped video"):
        drop.set_own_footage(store, scan_pick.id, True)


# ---- whose clip it is: the owner's choice or the studio's recommendation (owner 2026-10-06) -----------------------------------

DOG_STAR = {"kind": "dog", "body": "quadruped", "description": "the dachshund on the rug", "x_center": 0.5, "full_body": True, "child": False}
BISCUIT_LOOK = {
    "star": DOG_STAR, "hooks": ["main character energy", "the beat asked for me", "one take. obviously."], "gadgets": ["gold chain"],
    "caption": {"title": "Rug dance · dog edition", "joke": "I was stretching.", "send": "Send this to your dog.",
                "question": "Which eye first?", "tease": "Next week: the stairs."},
}


def studio_drop(store, storage, clip):
    """A file dropped with "Recommend": no character given, then uploaded and sent to the check."""
    pick, _ = add_drop(store, None, None, NOW)
    path = f"owner/{pick.id}/1759700000000.mp4"
    storage.upload("sources", path, clip)
    f = store.get_favorite(pick.id)
    store.update_favorite(pick.id, proposal={**f.proposal, "owner_clip_path": path, "drop": {**f.proposal["drop"], "state": "checking"}})
    return pick.id


def test_a_drop_without_a_character_waits_under_a_provisional_one(world):
    store, _ = world
    pick, dup = add_drop(store, None, None, NOW)
    assert not dup and pick.character_slug == "reginald"  # the first of the live roster (by slug) who replaces a person
    assert pick.proposal["drop"]["character_by"] == "studio"
    owners, _ = add_drop(store, "biscuit", None, NOW)
    assert owners.proposal["drop"]["character_by"] == "owner"
    # a link without a character takes the existing pick of that URL, whichever character it has, and keeps him
    first, _ = add_drop(store, "biscuit", TIKTOK, NOW)
    again, dup = add_drop(store, None, TIKTOK, NOW)
    assert dup and again.id == first.id and again.character_slug == "biscuit" and again.proposal["drop"]["character_by"] == "studio"
    # a paused character is never the provisional one, nor kept for a link
    store.upsert_character(Character(slug="reginald", name="Reginald", status="paused", bodies=[Body.biped]))
    assert add_drop(store, None, None, NOW)[0].character_slug == "biscuit"
    store.upsert_character(Character(slug="biscuit", name="Biscuit", status="paused", bodies=[Body.biped, Body.quadruped]))
    with pytest.raises(ValueError, match="every one is paused"):
        add_drop(store, None, None, NOW)


def test_the_studio_moves_its_drop_to_the_character_it_recommends_and_looks_again_in_his_voice(world, portrait):
    store, storage = world
    pid = studio_drop(store, storage, portrait)
    assert store.get_favorite(pid).character_slug == "reginald"
    rec = {"slug": "biscuit", "reason": "dog star on a rug: Biscuit's moves"}
    first = deconstruct(**BISCUIT_LOOK, recommended=rec)  # asked as the provisional Reginald
    second = deconstruct(**BISCUIT_LOOK, recommended={"slug": "biscuit", "reason": "a dog: Biscuit"})
    g = FakeGemini(first, second)
    out = process_drop(store, storage, pid, gemini_client=g, now=NOW, job="t")
    assert out.ok and out.state == "ready" and out.detail["character"] == "biscuit"
    pick = store.get_favorite(pid)
    d = pick.proposal["drop"]
    assert pick.character_slug == "biscuit" and d["character_by"] == "studio"
    assert d["recommended"] == rec  # the recommendation that moved it is the one the card shows
    assert d["gadgets"] == ["gold chain"] and d["hook"] == "main character energy"  # his own look, his gadgets
    assert len(g.calls) == 2 and "remade with Reginald" in g.calls[0]["prompt"] and "remade with Biscuit" in g.calls[1]["prompt"]
    for call in g.calls:  # the roster, each time: free, nothing reserved
        assert call["schema"]["properties"]["recommended"]["properties"]["slug"]["enum"] == ["biscuit", "reginald"]
    assert store.list_clips() == [] and store.ledger_month(NOW.strftime("%Y-%m")) == []


def test_a_studio_drop_already_under_its_recommendation_is_looked_at_once(world, portrait):
    store, storage = world
    pid = studio_drop(store, storage, portrait)
    g = FakeGemini(deconstruct())
    out = process_drop(store, storage, pid, gemini_client=g, now=NOW, job="t")
    assert out.state == "ready" and len(g.calls) == 1 and store.get_favorite(pid).character_slug == "reginald"


def test_the_owners_choice_is_never_overridden(world, portrait):
    store, storage = world
    pid = drop_file(store, storage, portrait)  # the owner chose Reginald
    g = FakeGemini(deconstruct(star=DOG_STAR))
    out = process_drop(store, storage, pid, gemini_client=g, now=NOW, job="t")
    pick = store.get_favorite(pid)
    assert out.state == "blocked" and "Reginald replaces a person" in out.reason and len(g.calls) == 1
    assert pick.character_slug == "reginald" and pick.proposal["drop"]["character_by"] == "owner"
    assert pick.proposal["drop"]["recommended"]["slug"] == "biscuit"  # the star on the menu points him to the right one


def test_a_drop_from_before_the_menu_counts_as_the_owners_choice(world, portrait):
    store, storage = world
    pid = drop_file(store, storage, portrait)
    f = store.get_favorite(pid)
    store.update_favorite(pid, proposal={**f.proposal, "drop": {k: v for k, v in f.proposal["drop"].items() if k != "character_by"}})
    out = process_drop(store, storage, pid, gemini_client=FakeGemini(deconstruct(star=DOG_STAR)), now=NOW, job="t")
    assert out.state == "blocked" and store.get_favorite(pid).character_slug == "reginald"


def test_the_deconstruct_by_hand_of_a_studio_drop_files_it_under_its_recommendation(world, portrait):
    store, storage = world
    pid = studio_drop(store, storage, portrait)
    out = process_drop(store, storage, pid, gemini_client=None, deconstruct_answer=deconstruct(**BISCUIT_LOOK), now=NOW, job="t")
    pick = store.get_favorite(pid)
    assert out.state == "ready" and pick.character_slug == "biscuit" and pick.proposal["drop"]["gadgets"] == ["gold chain"]
    other = studio_drop(store, storage, portrait)
    with pytest.raises(DropError, match="like for like"):  # a recommendation against the like-for-like rule is refused
        process_drop(store, storage, other, gemini_client=None,
                     deconstruct_answer=deconstruct(star=DOG_STAR, recommended={"slug": "reginald", "reason": "x"}), now=NOW, job="t")
    assert store.get_favorite(other).character_slug == "reginald"  # nothing moved before the refusal


def test_the_owner_changing_the_character_during_the_check_starts_it_again_for_him(world, portrait):
    store, storage = world
    pid = drop_file(store, storage, portrait)

    class OwnerTaps(FakeGemini):
        def generate_json(self, *a, **kw):
            if not self.calls:  # while Gemini looks, the owner picks Biscuit (what set_drop_character writes)
                f = store.get_favorite(pid)
                store.update_favorite(pid, character_slug="biscuit", proposal={**f.proposal, "drop": {**f.proposal["drop"], "character_by": "owner"}})
            return super().generate_json(*a, **kw)

    g = OwnerTaps(deconstruct(star=DOG_STAR), deconstruct(**BISCUIT_LOOK))
    out = process_drop(store, storage, pid, gemini_client=g, now=NOW, job="t")
    pick = store.get_favorite(pid)
    assert out.state == "ready" and pick.character_slug == "biscuit" and pick.proposal["drop"]["hook"] == "main character energy"
    assert len(g.calls) == 2 and "remade with Biscuit" in g.calls[1]["prompt"]


def test_cli_drop_add_without_a_character_lets_the_studio_recommend(monkeypatch, tmp_path):
    store = make_store()
    monkeypatch.setattr(drop, "open_store", lambda: store)
    r = CliRunner().invoke(app, ["drop", "add"])
    assert r.exit_code == 0, r.output
    out = json.loads(r.output)
    assert out["character"] == "reginald" and out["drop"]["character_by"] == "studio" and out["drop"]["state"] == "uploading"
    r = CliRunner().invoke(app, ["drop", "add", "--character", "biscuit", "--link", TIKTOK])
    assert r.exit_code == 0 and json.loads(r.output)["drop"]["character_by"] == "owner"
    r = CliRunner().invoke(app, ["drop", "add", "--character", "nobody"])
    assert r.exit_code == 2 and "unknown character" in r.output


# ---- only the section we use is judged (owner 2026-10-06) -----------------------------------------------------------------------


def test_text_or_a_watermark_is_padded_merged_and_fails_closed():
    look = {"watermark": False, "watermark_spans": [], "burned_in_text": True,
            "burned_in_text_spans": [{"start_s": 0, "end_s": 4.8}, {"start_s": 5, "end_s": 6}, {"start_s": 18, "end_s": 30}]}
    assert drop.avoid_spans(look, 20.0) == [
        {"start_s": 0.0, "end_s": 6.5, "what": "text"}, {"start_s": 17.5, "end_s": 20.0, "what": "text"},
    ]
    assert drop.avoid_spans({**look, "burned_in_text_spans": []}, 12.0) == [{"start_s": 0.0, "end_s": 12.0, "what": "text"}]
    stray = {"watermark": False, "watermark_spans": [{"start_s": 2, "end_s": 3}], "burned_in_text": False, "burned_in_text_spans": []}
    assert drop.avoid_spans(stray, 10.0) == [{"start_s": 1.5, "end_s": 3.5, "what": "watermark"}]  # a span counts even unflagged
    clean = {"watermark": False, "watermark_spans": [], "burned_in_text": False, "burned_in_text_spans": []}
    assert drop.avoid_spans(clean, 10.0) == []


def test_the_window_keeps_clear_of_text_and_shortens_or_gives_up_only_when_it_must():
    energy = [5.0] * 20 + [1.0] * 40  # 30 s, the liveliest part (0-10 s) carries a caption
    caption = [{"start_s": 0.0, "end_s": 10.5, "what": "text"}]
    w = drop_window(analysis(energy), classic=False, duration=30.0, avoid=caption)
    assert w["start_s"] >= 10.5 and 8.0 <= w["length_s"] <= 10.0
    assert drop_window(analysis(energy), classic=False, duration=30.0)["start_s"] < 10.5  # without it the caption part wins
    # only 7 s clear (12-19 s): a shorter section, never under 6 s
    tight = [{"start_s": 0.0, "end_s": 12.0, "what": "text"}, {"start_s": 19.0, "end_s": 30.0, "what": "watermark"}]
    w = drop_window(analysis([2.0] * 60), classic=True, duration=30.0, avoid=tight)
    assert 12.0 <= w["start_s"] and w["start_s"] + w["length_s"] <= 19.0 and 6.0 <= w["length_s"] <= 7.0
    with pytest.raises(drop.NoCleanSection):
        drop_window(analysis([2.0] * 60), classic=False, duration=30.0, avoid=[{"start_s": 0.0, "end_s": 25.0, "what": "text"}])
    beats = [i * 0.5 + 0.4 for i in range(60)]  # the nearest beat (10.4 s) would pull the section back onto the caption
    w = drop_window(analysis(energy, beats=beats), classic=False, duration=30.0, avoid=caption)
    assert w["start_s"] >= 10.5


def test_a_caption_only_at_the_start_leaves_a_clean_section_after_it(world, synth_video):
    store, storage = world
    pid = drop_file(store, storage, synth_video(w=540, h=960, dur=16))
    look = deconstruct(burned_in_text=True, burned_in_text_spans=[{"start_s": 0, "end_s": 5}])
    out = process_drop(store, storage, pid, gemini_client=FakeGemini(look), now=NOW, job="t")
    d = store.get_favorite(pid).proposal["drop"]
    assert out.state == d["state"] == "ready"
    assert d["avoid"] == [{"start_s": 0.0, "end_s": 5.5, "what": "text"}]
    assert d["window"]["start_s"] >= 5.5 and 8.0 <= d["window"]["length_s"] <= 10.0
    # the owner's Adjust may not pull the section back onto the caption, here and when Make it runs
    with pytest.raises(ValueError, match=r"shows text on screen \(0-5.5 s\)"):
        validate_adjust({"start_s": 2.0, "length_s": 8.0}, d)
    assert validate_adjust({"start_s": 6.0, "length_s": 8.0}, d) == {"start_s": 6.0, "length_s": 8.0}
    tap_make(store, pid, adjust={"start_s": 0.0, "length_s": 9.0})
    out = make_drop(store, storage, pid, hf=None, gemini_client=None, now=NOW, job="t")
    assert out.state == "failed" and "shows text on screen" in out.reason and store.list_clips() == []


def test_text_through_the_whole_clip_still_blocks_it(world, portrait):
    store, storage = world
    pid = drop_file(store, storage, portrait)
    look = deconstruct(burned_in_text=True, burned_in_text_spans=[{"start_s": 0, "end_s": 3}, {"start_s": 2.5, "end_s": 7}])
    out = process_drop(store, storage, pid, gemini_client=FakeGemini(look), now=NOW, job="t")
    d = store.get_favorite(pid).proposal["drop"]
    assert out.state == "blocked" and out.reason == "text or a watermark is on screen in every usable section: Genjutsu would keep it, drop a clean copy"
    (span,) = d["avoid"]
    assert span["start_s"] == 0.0 and span["end_s"] >= 6.9 and span["what"] == "text" and "credits" not in d


def test_the_cut_section_carries_its_own_clean_flags(world, synth_video, gen_out, fast_master):
    store, storage = world
    pid = drop_file(store, storage, synth_video(w=540, h=960, dur=16))
    look = deconstruct(burned_in_text=True, burned_in_text_spans=[{"start_s": 0, "end_s": 5}])
    process_drop(store, storage, pid, gemini_client=FakeGemini(look), now=NOW, job="t")
    parent = next(iter(store.list_sources(id=store.get_favorite(pid).source_id)))
    assert parent.has_overlay is True  # the clip has text somewhere
    tap_make(store, pid)
    assert make(store, storage, pid, FakeHF(gen_out), FakeGemini(QA_PASS)).state == "made"
    clip = store.get_clip(store.get_favorite(pid).clip_id)
    child = next(iter(store.list_sources(id=clip.source_id)))
    assert child.has_overlay is False and child.has_watermark is False  # the section Genjutsu was given has none


# ---- the clip score (terminal v3, spec section 3): free, stored only when the check ends ready --------------------------------

W = {"start_s": 5.0, "length_s": 8.0}  # the section 5-13 s


def swap_points(look, avoid=(), has_audio=True) -> int:
    return drop.drop_score(look, W, list(avoid), has_audio)["swap"]


def test_drop_score_points():
    base = deconstruct()  # one person, full body, static, clear, with sound, not a classic: 3 + 2 + 2 + 1 + 1
    assert swap_points(base) == 9
    # one person in frame 3, two 1, three or more 0
    assert [swap_points(deconstruct(people_count=n)) for n in (1, 2, 3, 7)] == [9, 7, 6, 6]
    # a dog star is the one in frame: alone 3, with a person beside it 1
    assert swap_points(deconstruct(star=DOG_STAR, people_count=0)) == 9
    assert swap_points(deconstruct(star=DOG_STAR, people_count=1)) == 7
    assert swap_points(deconstruct(star={**deconstruct()["star"], "full_body": False})) == 7  # full body 2
    assert [swap_points(deconstruct(camera=c)) for c in ("static", "handheld", "moving")] == [9, 8, 7]  # static 2, handheld 1
    # clear of every text or watermark span by 1 s or more 1, nearer 0
    for span, points in (
        ({"start_s": 0.0, "end_s": 4.0}, 9), ({"start_s": 0.0, "end_s": 4.5}, 8), ({"start_s": 14.0, "end_s": 20.0}, 9),
        ({"start_s": 13.5, "end_s": 20.0}, 8), ({"start_s": 6.0, "end_s": 7.0}, 8),
    ):
        assert swap_points(base, [{**span, "what": "text"}]) == points, span
    assert swap_points(base, [{"start_s": 0.0, "end_s": 1.0, "what": "text"}, {"start_s": 13.2, "end_s": 15.0, "what": "watermark"}]) == 8
    assert swap_points(base, has_audio=False) == 8  # sound 1
    assert swap_points(deconstruct(classic=True)) == 10  # a classic 1: every point, the cap
    worst = deconstruct(people_count=4, star={**deconstruct()["star"], "full_body": False}, camera="moving")
    assert swap_points(worst, [{"start_s": 0.0, "end_s": 30.0, "what": "text"}], has_audio=False) == 0


def test_drop_score_total():
    """total = round(10 x (0.6 x potential + 0.4 x swap)), reason = the potential's reason."""
    top = deconstruct(classic=True, potential={"score": 8, "reason": "a classic everyone knows"})
    assert drop.drop_score(top, W, [], True) == {"total": 88, "potential": 8, "swap": 10, "reason": "a classic everyone knows"}
    none = deconstruct(people_count=3, star={**deconstruct()["star"], "full_body": False}, camera="moving",
                       potential={"score": 0, "reason": "another creator's own skit"})
    assert drop.drop_score(none, W, [{"start_s": 5.0, "end_s": 6.0, "what": "text"}], False)["total"] == 0
    mid = deconstruct(potential={"score": 7, "reason": "x"}, camera="moving")  # swap 7
    assert drop.drop_score(mid, W, [], True)["total"] == round(10 * (0.6 * 7 + 0.4 * 7)) == 70
    assert drop.drop_score(deconstruct(potential={"score": 10, "reason": "x"}, classic=True), W, [], True)["total"] == 100


def test_ready_drop_stores_score(world, portrait):
    store, storage = world
    pid = ready_drop(store, storage, portrait)
    d = store.get_favorite(pid).proposal["drop"]
    # one person, full body, static, clear, with sound: swap 9; potential 7 -> round(10 x (4.2 + 3.6)) = 78
    assert d["score"] == {"total": 78, "potential": 7, "swap": 9, "reason": "a shimmy many people do, moving from the first second"}
    assert d["deconstruct"]["potential"]["reason"] == d["score"]["reason"]  # the reason is the potential's, trimmed
    assert d["score"] == drop.drop_score(d["deconstruct"], d["window"], d["avoid"], d["has_audio"])


def test_blocked_drop_has_no_score(world, portrait):
    store, storage = world
    pid = drop_file(store, storage, portrait)
    out = process_drop(store, storage, pid, gemini_client=FakeGemini(deconstruct(star=DOG_STAR)), now=NOW, job="t")
    assert out.state == "blocked" and "score" not in store.get_favorite(pid).proposal["drop"]
    pid = drop_file(store, storage, portrait)
    out = process_drop(store, storage, pid, gemini_client=FakeGemini(GeminiError("HTTP 503")), now=NOW, job="t")
    assert out.state == "failed" and "score" not in store.get_favorite(pid).proposal["drop"]


def to_checking_keeping_the_score(store, pid, slug=None):
    """What set_drop_character (migration 0013) writes: the owner's character, back to checking; it does not know the score."""
    f = store.get_favorite(pid)
    assert "score" in f.proposal["drop"]
    store.update_favorite(pid, character_slug=slug or f.character_slug,
                          proposal={**f.proposal, "drop": {**f.proposal["drop"], "state": "checking", "character_by": "owner"}})


def test_a_check_that_does_not_end_ready_leaves_no_old_score(world, portrait):
    """A scored drop the owner moved to another character is checked again: blocked, failed or waiting for the key, it keeps
    no score of the old look (only a check that ends ready has one)."""
    store, storage = world
    pid = ready_drop(store, storage, portrait)
    to_checking_keeping_the_score(store, pid)
    out = process_drop(store, storage, pid, gemini_client=FakeGemini(deconstruct(star=DOG_STAR)), now=NOW, job="t")
    assert out.state == "blocked" and "score" not in store.get_favorite(pid).proposal["drop"]
    pid = ready_drop(store, storage, portrait)
    to_checking_keeping_the_score(store, pid)
    out = process_drop(store, storage, pid, gemini_client=FakeGemini(GeminiError("HTTP 503")), now=NOW, job="t")
    assert out.state == "failed" and "score" not in store.get_favorite(pid).proposal["drop"]
    pid = ready_drop(store, storage, portrait)
    to_checking_keeping_the_score(store, pid)
    out = process_drop(store, storage, pid, gemini_client=None, now=NOW, job="t")
    assert out.state == "checking" and "Gemini key" in out.reason and "score" not in store.get_favorite(pid).proposal["drop"]
    pid = ready_drop(store, storage, portrait)
    to_checking_keeping_the_score(store, pid)
    out = process_drop(store, storage, pid, gemini_client=FakeGemini(RuntimeError("boom")), now=NOW, job="t")
    assert out.state == "failed" and "the check stopped" in out.reason and "score" not in store.get_favorite(pid).proposal["drop"]


def test_the_character_changing_on_every_look_leaves_no_old_score(world, portrait):
    store, storage = world
    pid = ready_drop(store, storage, portrait)
    to_checking_keeping_the_score(store, pid)

    class OwnerKeepsTapping(FakeGemini):
        def generate_json(self, *a, **kw):  # every look, the owner picks the other one (what set_drop_character writes)
            f = store.get_favorite(pid)
            other = "biscuit" if f.character_slug == "reginald" else "reginald"
            store.update_favorite(pid, character_slug=other, proposal={**f.proposal, "drop": {**f.proposal["drop"], "character_by": "owner"}})
            return super().generate_json(*a, **kw)

    look = deconstruct(**BISCUIT_LOOK)
    out = process_drop(store, storage, pid, gemini_client=OwnerKeepsTapping(*[look] * (drop.CHANGE_RESTARTS + 1)), now=NOW, job="t")
    assert not out.ok and "the character changed during every look" in out.reason
    assert "score" not in store.get_favorite(pid).proposal["drop"]


def test_a_failed_make_keeps_its_score_for_try_again(world, portrait, gen_out):
    store, storage = world
    pid = ready_drop(store, storage, portrait)
    tap_make(store, pid)
    out = make(store, storage, pid, FakeHF(gen_out, RequestStatus(status="nsfw", error="moderation")), FakeGemini())
    assert out.state == "failed" and store.get_favorite(pid).proposal["drop"]["score"]["total"] == 78


# ---- recheck: a ready drop checked again (free), never one the owner sent with Make it ------------------------------------------


def test_recheck_moves_ready_to_checking(world, portrait):
    store, storage = world
    pid = ready_drop(store, storage, portrait)
    f = store.get_favorite(pid)  # a drop checked before this build: ready with no score
    store.update_favorite(pid, proposal={**f.proposal, "drop": {k: v for k, v in f.proposal["drop"].items() if k != "score"}})
    later = NOW + timedelta(hours=1)
    out = drop.request_recheck(store, pid, later)
    d = out.proposal["drop"]
    assert d["state"] == "checking" and d["reason"] is None and d["at"] == later.isoformat() and d["requested"]["process"] == later.isoformat()
    assert store.get_favorite(pid).proposal["drop"] == d and out.status == "approved" and "make_requested" not in out.proposal
    assert pending(store, now=later) == [{"pick_id": pid, "job": "process", "state": "checking"}]  # the cloud sweep takes it
    g = FakeGemini(deconstruct())
    again = process_drop(store, storage, pid, gemini_client=g, now=later, job="t")
    assert again.state == "ready" and len(g.calls) == 1 and len(store.list_sources()) == 1  # the same source, looked at again
    assert store.get_favorite(pid).proposal["drop"]["score"]["total"] == 78
    assert store.list_clips() == [] and store.ledger_month(NOW.strftime("%Y-%m")) == []  # free
    # a scored drop asked again loses the old score until its new check ends
    assert "score" not in drop.request_recheck(store, pid, later).proposal["drop"]


def test_recheck_refuses_make_requested_making_made(world, portrait):
    store, storage = world
    pid = ready_drop(store, storage, portrait)
    tap_make(store, pid)  # the owner's Make it: a recheck would move a paid job
    f = store.get_favorite(pid)
    store.update_favorite(pid, proposal={**f.proposal, "drop": {**f.proposal["drop"], "state": "ready"}})  # even back at ready
    with pytest.raises(DropError, match="Make it"):
        drop.request_recheck(store, pid, NOW)
    f = store.get_favorite(pid)
    clean = {k: v for k, v in f.proposal.items() if k != "make_requested"}
    for state in ("making", "made"):
        store.update_favorite(pid, proposal={**clean, "drop": {**clean["drop"], "state": state}})
        with pytest.raises(DropError, match=f"is {state}"):
            drop.request_recheck(store, pid, NOW)
    for status in ("made", "queued"):
        store.update_favorite(pid, status=status, proposal={**clean, "drop": {**clean["drop"], "state": "ready"}})
        with pytest.raises(DropError, match=f"already {status}"):
            drop.request_recheck(store, pid, NOW)
    store.update_favorite(pid, status="approved")
    for state in ("uploading", "checking", "waiting", "blocked", "failed"):  # only a ready drop is checked again
        store.update_favorite(pid, proposal={**clean, "drop": {**clean["drop"], "state": state}})
        with pytest.raises(DropError, match="only a ready drop"):
            drop.request_recheck(store, pid, NOW)
    assert store.get_favorite(pid).proposal["drop"]["state"] == "failed"  # nothing moved
    with pytest.raises(KeyError):
        drop.request_recheck(store, "nope", NOW)


def test_cli_drop_recheck_one_or_every_ready_drop(monkeypatch, tmp_path, portrait):
    store, storage = make_store(), LocalStorage(tmp_path / "s")
    monkeypatch.setattr(drop, "open_store", lambda: store)
    a = ready_drop(store, storage, portrait)
    b = ready_drop(store, storage, portrait)
    made = ready_drop(store, storage, portrait)
    tap_make(store, made)  # making, with the owner's Make it: never rechecked
    queued = ready_drop(store, storage, portrait)
    store.update_favorite(queued, status="queued")  # ready, no Make it, but already queued: refused, named
    blocked = drop_file(store, storage, portrait)
    process_drop(store, storage, blocked, gemini_client=FakeGemini(deconstruct(star=DOG_STAR)), now=NOW, job="t")
    r = CliRunner().invoke(app, ["drop", "recheck", a])
    assert r.exit_code == 0, r.output
    assert json.loads(r.output) == {"rechecked": [a], "refused": []}
    r = CliRunner().invoke(app, ["drop", "recheck", made])
    assert r.exit_code == 2 and json.loads(r.output)["refused"][0]["pick_id"] == made
    assert "Make it" in json.loads(r.output)["refused"][0]["reason"]
    r = CliRunner().invoke(app, ["drop", "recheck", "--all-ready"])
    assert r.exit_code == 0, r.output
    out = json.loads(r.output)
    assert out["rechecked"] == [b] and [x["pick_id"] for x in out["refused"]] == [queued]
    assert store.get_favorite(made).proposal["drop"]["state"] == "making" and store.get_favorite(blocked).proposal["drop"]["state"] == "blocked"
    r = CliRunner().invoke(app, ["drop", "recheck", "nope"])
    assert r.exit_code == 2 and json.loads(r.output)["refused"] == [{"pick_id": "nope", "reason": "unknown pick nope"}]
    for args in ([], [a, "--all-ready"]):
        r = CliRunner().invoke(app, ["drop", "recheck", *args])
        assert r.exit_code == 2 and "a pick or --all-ready" in r.output
    r = CliRunner().invoke(app, ["drop", "recheck", "--help"], env={"COLUMNS": "200"})
    assert "scored or not" in r.output and "checked before the score" not in r.output  # it takes every ready drop without Make it


# ---- Franz takes a person too (owner 2026-10-07: "franz not only replaces dogs") ------------------------------------------------


def test_a_person_star_is_like_for_like_for_franz(world, portrait):
    ref, who = drop.character("franz")
    assert ref["swap"]["stars"] == ["dog", "person"] and who.stars == ("dog", "person") and "biped" in ref["bodies"]
    person = deconstruct()["star"]
    assert drop.like_for_like(person, ref, "Franz") is None and drop.like_for_like(DOG_STAR, ref, "Franz") is None
    assert "Franz replaces a dog or a person" in drop.like_for_like({**DOG_STAR, "kind": "animal"}, ref, "Franz")
    store, storage = world
    store.add_character(Character(slug="franz", name="Franz", bodies=[Body.biped, Body.quadruped]))
    pid = ready_drop(store, storage, portrait, slug="franz")  # the owner's choice: a man doing the shimmy, Franz upright
    d = store.get_favorite(pid).proposal["drop"]
    assert d["state"] == "ready" and d["star"]["body"] == "biped" and store.get_favorite(pid).character_slug == "franz"


# ---- reuse: one clip, up to three characters (terminal v3, spec section 4) ------------------------------------------------------


def with_lenny_and_franz(store, franz_status="live"):
    store.add_character(Character(slug="lenny", name="Lenny Gold", status="live", bodies=[Body.biped]))
    store.add_character(Character(slug="franz", name="Franz", status=franz_status, bodies=[Body.biped, Body.quadruped]))
    return store


def checked(store, slug="reginald", state="ready", star=None, own_footage=True, **drop_over):
    """A drop whose check ended ``state`` without a video (the copy rules only read the card): its full-clip source in Storage,
    the star, the section."""
    pick, _ = add_drop(store, slug, None, NOW, own_footage=own_footage)
    src = sources.add_source(store, "owner_inbox", None, "biped", 1, 20.0, storage_path=f"owner/{pick.id}/1.mp4")
    d = {
        **pick.proposal["drop"], "state": state, "star": star or deconstruct()["star"], "source_id": src.id,
        "window": {"start_s": 0.0, "length_s": 9.0}, "score": {"total": 78, "potential": 7, "swap": 9, "reason": "x"}, **drop_over,
    }
    return store.update_favorite(pick.id, source_id=src.id, proposal={**pick.proposal, "drop": d})


def test_copy_creates_version(world):
    store, _ = world
    with_lenny_and_franz(store)
    root = checked(store)
    store.update_favorite(root.id, creator_handle="@dancer.one")  # the original creator is credited on every version
    later = NOW + timedelta(minutes=5)
    v = drop.copy_drop(store, root.id, "lenny", now=later)
    assert v.id != root.id and v.url == f"owner-drop:{v.id}" and v.platform == "drop" and v.origin == "owner"
    assert v.status == "approved" and v.character_slug == "lenny" and v.source_id == root.source_id
    assert v.creator_handle == "@dancer.one" and v.proposal["decision"]["by"] == "owner"
    d = v.proposal["drop"]
    assert d == {
        "state": "checking", "kind": "file", "at": later.isoformat(), "reason": None, "own_footage": True,
        "character_by": "owner", "copy_of": root.id, "requested": {"process": later.isoformat()},
    }  # no score, window or hooks of the root's: the version's own free check gives it its own, in Lenny's voice
    assert store.get_favorite(v.id) == v and len(store.list_favorites()) == 2
    assert {"pick_id": v.id, "job": "process", "state": "checking"} in pending(store, now=later)  # the sweep takes it
    assert [m.id for m in drop.family(store, store.get_favorite(root.id))] == [root.id, v.id]
    assert [m.id for m in drop.family(store, v)] == [root.id, v.id]
    assert store.get_favorite(root.id).proposal["drop"] == root.proposal["drop"]  # the root is left as it was
    own = checked(store, own_footage=False)
    assert drop.copy_drop(store, own.id, "franz", now=later).proposal["drop"]["own_footage"] is False


def test_copy_of_copy_points_at_root(world):
    store, _ = world
    with_lenny_and_franz(store)
    root = checked(store, state="made")
    v1 = drop.copy_drop(store, root.id, "lenny", now=NOW)
    v2 = drop.copy_drop(store, v1.id, "franz", now=NOW)  # from the version's card: still the root's family
    assert v2.proposal["drop"]["copy_of"] == root.id and v2.source_id == root.source_id
    assert [m.id for m in drop.family(store, v2)] == [root.id, v1.id, v2.id] == [m.id for m in drop.family(store, v1)]


def refused(store, pick_id, slug, line):
    before = len(store.list_favorites())
    with pytest.raises(DropError) as e:
        drop.copy_drop(store, pick_id, slug, now=NOW)
    assert str(e.value) == line
    assert len(store.list_favorites()) == before  # nothing is filed


def test_copy_refusals(world):
    store, _ = world
    with_lenny_and_franz(store)
    for state in ("uploading", "checking", "waiting", "blocked", "failed"):
        refused(store, checked(store, state=state).id, "lenny", "the clip is not checked yet")
    no_source = checked(store)
    store.update_favorite(no_source.id, source_id=None, proposal={**no_source.proposal, "drop": {
        k: v for k, v in no_source.proposal["drop"].items() if k != "source_id"}})
    refused(store, no_source.id, "lenny", "the clip is not checked yet")
    dog = checked(store, slug="franz", star=DOG_STAR)
    refused(store, dog.id, "lenny", "the wrong star: Lenny Gold replaces a person, this clip's star is a dog")  # like_for_like's line
    root = checked(store)
    refused(store, root.id, "reginald", "Reginald already has a version of this clip")
    lenny = drop.copy_drop(store, root.id, "lenny", now=NOW)
    refused(store, lenny.id, "lenny", "Lenny Gold already has a version of this clip")
    franz = drop.copy_drop(store, root.id, "franz", now=NOW)
    refused(store, franz.id, "biscuit", "a clip goes to at most 3 characters")  # the 4th, from a version's card too
    store.update_favorite(lenny.id, status="skipped")  # a skipped version is no member: Lenny may have a new one
    again = drop.copy_drop(store, root.id, "lenny", now=NOW)
    assert [m.id for m in drop.family(store, root)] == [root.id, franz.id, again.id]
    refused(store, root.id, "biscuit", "a clip goes to at most 3 characters")
    paused = with_lenny_and_franz(make_store(), franz_status="paused")
    refused(paused, checked(paused).id, "franz", "Franz is paused")
    with pytest.raises(DropError, match="unknown character 'nobody'"):
        drop.copy_drop(store, checked(store).id, "nobody", now=NOW)
    with pytest.raises(KeyError):
        drop.copy_drop(store, "nope", "lenny", now=NOW)


def test_copy_refuses_a_clip_whose_file_is_gone(world):
    """The root's full clip was deleted after posting (``source purge``): a version could never be checked, so none is filed."""
    store, _ = world
    with_lenny_and_franz(store)
    root = checked(store, state="made")
    store.update_source(root.source_id, storage_path=None)
    refused(store, root.id, "lenny", "the clip's file is gone (deleted after posting): drop it again")


def test_cli_drop_copy(monkeypatch, world):
    store, _ = world
    with_lenny_and_franz(store)
    monkeypatch.setattr(drop, "open_store", lambda: store)
    root = checked(store)
    r = CliRunner().invoke(app, ["drop", "copy", root.id, "--character", "lenny"])
    assert r.exit_code == 0, r.output
    out = json.loads(r.output)
    assert out["copy_of"] == root.id and out["character"] == "lenny" and out["drop"]["state"] == "checking"
    assert store.get_favorite(out["pick_id"]).proposal["drop"]["copy_of"] == root.id
    r = CliRunner().invoke(app, ["drop", "copy", root.id, "--character", "lenny"])
    assert r.exit_code == 2 and "Lenny Gold already has a version of this clip" in r.output
    r = CliRunner().invoke(app, ["drop", "copy", "nope", "--character", "lenny"])
    assert r.exit_code == 2 and "unknown pick nope" in r.output


def two_halves(seconds: int, first: float = 5.0, second: float = 4.0) -> dict:
    """A free analysis of a clip of ``seconds`` whose first 10 s move more than the rest (0.5 s steps, no cuts, no beats)."""
    return {**analysis([first] * 20 + [second] * (2 * seconds - 20)), "best_window": {"start_s": 0.0, "end_s": 10.0}}


def test_version_prefers_other_window(world, synth_video, monkeypatch):
    store, storage = world
    with_lenny_and_franz(store)
    monkeypatch.setattr(drop, "analyze_clip", lambda clip, sheet: two_halves(21))
    root = ready_drop(store, storage, synth_video(w=320, h=568, dur=21))
    assert store.get_favorite(root).proposal["drop"]["window"] == {"start_s": 0.0, "length_s": 10.0}  # the liveliest part
    v = drop.copy_drop(store, root, "lenny", now=NOW)
    out = process_drop(store, storage, v.id, gemini_client=FakeGemini(deconstruct()), now=NOW, job="t")
    d = store.get_favorite(v.id).proposal["drop"]
    assert out.state == "ready" and d["window"] == {"start_s": 10.0, "length_s": 10.0}  # a different section of the clip
    assert d["avoid"] == [] and d["source_id"] == store.get_favorite(root).source_id  # the root's spans are no text to avoid
    assert len(store.list_sources()) == 1  # nothing was uploaded again
    w = drop.copy_drop(store, root, "franz", now=NOW)  # the third keeps clear of both when it can, else the best one
    assert process_drop(store, storage, w.id, gemini_client=FakeGemini(deconstruct()), now=NOW, job="t").state == "ready"
    assert store.get_favorite(w.id).proposal["drop"]["window"] == {"start_s": 0.0, "length_s": 10.0}


def test_version_falls_back_to_best_window(world, synth_video, monkeypatch):
    store, storage = world
    with_lenny_and_franz(store)
    monkeypatch.setattr(drop, "analyze_clip", lambda clip, sheet: two_halves(12, second=5.0))
    root = ready_drop(store, storage, synth_video(w=320, h=568, dur=12))
    window = store.get_favorite(root).proposal["drop"]["window"]
    v = drop.copy_drop(store, root, "lenny", now=NOW)
    out = process_drop(store, storage, v.id, gemini_client=FakeGemini(deconstruct()), now=NOW, job="t")
    d = store.get_favorite(v.id).proposal["drop"]
    assert out.state == "ready" and d["window"] == window  # no 6 s clear of the root's section: the best one, as usual
    assert d["avoid"] == [] and "score" in d


def test_unclean_reason_ignores_version_spans():
    version = {"start_s": 0.0, "end_s": 9.0, "what": "version"}
    text = {"start_s": 9.0, "end_s": 12.0, "what": "text"}
    assert drop._unclean_reason([version, text], False) == drop._unclean_reason([text], False)


def test_the_studio_never_moves_a_family_member_to_a_character_the_family_has(world, portrait):
    """A root filed with Recommend and checked again: the studio may not move it to a character who already has a version."""
    store, storage = world
    with_lenny_and_franz(store)
    pid = studio_drop(store, storage, portrait)  # waits under Franz, then the studio moves it to Reginald (two looks)
    assert process_drop(store, storage, pid, gemini_client=FakeGemini(deconstruct(), deconstruct()), now=NOW, job="t").state == "ready"
    assert store.get_favorite(pid).character_slug == "reginald"
    drop.copy_drop(store, pid, "lenny", now=NOW)
    drop.request_recheck(store, pid, now=NOW)
    look = deconstruct(recommended={"slug": "lenny", "reason": "office shimmy: Lenny's deal energy"})
    g = FakeGemini(look)
    out = process_drop(store, storage, pid, gemini_client=g, now=NOW, job="t")
    f = store.get_favorite(pid)
    assert out.state == "ready" and f.character_slug == "reginald" and len(g.calls) == 1  # no move, no second look
    assert f.proposal["drop"]["recommended"]["slug"] == "lenny"  # the card still says who would fit best


# ---- Franz performs as the star (owner 2026-10-08: refs.json swap_part and swap_performance) -----------------------------------


def test_the_swap_prompt_adds_the_characters_performance_line():
    base = drop.swap_prompt("the man in the grey suit", "butler", "featured", ["black umbrella"])
    assert drop.swap_prompt("the man in the grey suit", "butler", "featured", ["black umbrella"], performance=None) == base
    ref, _ = drop.character("franz")
    prompt = drop.swap_prompt("the man in the grey suit", "dachshund", "star", [], performance=ref["swap_performance"])
    assert prompt == (
        "Replace the man in the grey suit with the dachshund from the reference images. Use the reference images for the character "
        "only. Keep the original's camera movement, framing, lighting and colour grading, and match its colour grading. "
        f"He performs every beat with full energy; the scene stays the same. Performance: {ref['swap_performance']}."
    )
    assert drop.SWAP_KEEP_LINE in base and base.index(drop.SWAP_KEEP_LINE) < base.index("He follows")  # the line sits right after the first
    assert len(prompt) < 700  # still a SHORT prompt (Higgsfield takes 10,000)


def test_every_swap_prompt_carries_the_owners_two_lines_right_after_the_first():
    keep = (
        "Use the reference images for the character only. Keep the original's camera movement, framing, lighting and colour "
        "grading, and match its colour grading."
    )
    assert drop.SWAP_KEEP_LINE == keep
    first = "Replace the woman on the left with the butler from the reference images."
    parts = {
        "cameo": "Keep his motion minimal and natural; the scene stays the same.",
        "featured": "He follows the original performer's motion exactly; the scene stays the same.",
        "star": "He performs every beat with full energy; the scene stays the same.",
    }
    for part, line in parts.items():
        assert drop.swap_prompt("the woman on the left.", "butler", part, ["gold pocket watch"], "same moves, all Reginald") == (
            f"{first} {keep} {line} He wears or holds: gold pocket watch (no brand logos). Performance: same moves, all Reginald."
        )


def test_franz_is_made_as_the_star_with_his_performance_line(world, portrait, gen_out, fast_master):
    store, storage = world
    store.add_character(Character(slug="franz", name="Franz", bodies=[Body.biped, Body.quadruped]))
    ref, _ = drop.character("franz")
    pid = ready_drop(store, storage, portrait, slug="franz")  # the check suggests featured; his refs.json says star
    d = store.get_favorite(pid).proposal["drop"]
    assert d["deconstruct"]["suggested_part"] == "featured" and d["part"] == "star"  # the Adjust sheet's default is his
    tap_make(store, pid)
    hf = FakeHF(gen_out)
    assert make(store, storage, pid, hf, FakeGemini(QA_PASS)).state == "made"
    (sub,) = hf.submits
    assert "full energy" in sub["prompt"] and sub["prompt"].endswith(f"Performance: {ref['swap_performance']}.")
    assert store.get_clip(store.get_favorite(pid).clip_id).features["presence"] == "star"


def test_the_owners_part_wins_over_the_characters(world, portrait, gen_out, fast_master):
    store, storage = world
    store.add_character(Character(slug="franz", name="Franz", bodies=[Body.biped, Body.quadruped]))
    pid = ready_drop(store, storage, portrait, slug="franz")
    tap_make(store, pid, adjust={"part": "cameo"})
    hf = FakeHF(gen_out)
    assert make(store, storage, pid, hf, FakeGemini(QA_PASS)).state == "made"
    assert "motion minimal" in hf.submits[0]["prompt"] and "Performance:" in hf.submits[0]["prompt"]
    assert store.get_clip(store.get_favorite(pid).clip_id).features["presence"] == "cameo"


def test_a_check_made_before_the_characters_part_is_made_with_it(world, portrait, gen_out, fast_master):
    """A Franz drop checked before refs.json had swap_part keeps the suggested part on its card; Make it reads refs.json."""
    store, storage = world
    store.add_character(Character(slug="franz", name="Franz", bodies=[Body.biped, Body.quadruped]))
    pid = ready_drop(store, storage, portrait, slug="franz")
    f = store.get_favorite(pid)
    store.update_favorite(pid, proposal={**f.proposal, "drop": {**f.proposal["drop"], "part": "featured"}})
    tap_make(store, pid)
    hf = FakeHF(gen_out)
    assert make(store, storage, pid, hf, FakeGemini(QA_PASS)).state == "made"
    assert "full energy" in hf.submits[0]["prompt"]


def test_a_character_without_a_part_or_performance_is_made_as_before(world, portrait, gen_out, fast_master):
    store, storage = world
    pid = ready_drop(store, storage, portrait)  # Reginald: neither in his refs.json
    assert store.get_favorite(pid).proposal["drop"]["part"] == "featured"  # the check's suggestion
    tap_make(store, pid)
    hf = FakeHF(gen_out)
    assert make(store, storage, pid, hf, FakeGemini(QA_PASS)).state == "made"
    assert hf.submits[0]["prompt"] == drop.swap_prompt("the man in the grey suit", "butler", "featured", ["black umbrella"])


def test_the_prepared_mcp_inputs_carry_the_performance_line_too(world, portrait):
    store, storage = world
    store.add_character(Character(slug="franz", name="Franz", bodies=[Body.biped, Body.quadruped]))
    ref, _ = drop.character("franz")
    pid = ready_drop(store, storage, portrait, slug="franz")
    tap_make(store, pid)
    out = make_drop(store, storage, pid, hf=None, gemini_client=None, prepare=True, now=NOW, job="t")
    assert out.detail["inputs"]["prompt"].endswith(f"Performance: {ref['swap_performance']}.")


# ---- the balance of suggestions and fresh hooks (controller 2026-10-08) ---------------------------------------------------------


def a_drop(store, slug, state, status="approved", hook=None, at=None):
    pick, _ = add_drop(store, slug, None, NOW)
    d = {**pick.proposal["drop"], "state": state, **({"hook": hook} if hook else {})}
    return store.update_favorite(pick.id, status=status, created_at=at or NOW, proposal={**pick.proposal, "drop": d})


def test_the_roster_counts_each_characters_ready_clips(world):
    store, _ = world
    with_lenny_and_franz(store)
    for _ in range(2):
        a_drop(store, "lenny", "ready")
    a_drop(store, "reginald", "ready")
    a_drop(store, "reginald", "ready", status="skipped")  # skipped: no clip to make
    a_drop(store, "reginald", "blocked")
    a_drop(store, "reginald", "made", status="made")
    crew = {c.slug: c.ready_clips for c in drop.roster(store)}
    assert crew == {"biscuit": 0, "franz": 0, "lenny": 2, "reginald": 1}


def test_the_check_tells_gemini_how_many_ready_clips_each_character_has(world, portrait):
    store, storage = world
    with_lenny_and_franz(store)
    for _ in range(3):
        a_drop(store, "lenny", "ready")
    pid = drop_file(store, storage, portrait)
    g = FakeGemini(deconstruct())
    process_drop(store, storage, pid, gemini_client=g, now=NOW, job="t")
    prompt = g.calls[0]["prompt"]
    assert "- lenny: Lenny Gold, the Hollywood agent; replaces a person." in prompt and "Ready clips: 3." in prompt
    assert "prefer the one with fewer ready clips" in prompt


def test_the_check_lists_the_characters_latest_hooks(world, portrait):
    store, storage = world
    with_lenny_and_franz(store)
    for i in range(8):  # oldest first: hook 0 .. hook 7
        a_drop(store, "reginald", "ready", hook=f"Reginald hook {i}", at=NOW - timedelta(days=30 - i))
    for i in range(8, 12):
        store.add_clip(Clip(character_slug="reginald", mode=Mode.dropin, features={"hook_text": f"Reginald hook {i}"},
                            created_at=NOW - timedelta(days=30 - i)))
    store.add_clip(Clip(character_slug="reginald", mode=Mode.dropin, features={"hook_text": "reginald HOOK 11 "},
                        created_at=NOW - timedelta(days=1)))  # the same hook again, newest: once, in its newest place
    a_drop(store, "lenny", "ready", hook="Lenny closes the deal")  # another character's: not his
    pid = drop_file(store, storage, portrait)
    g = FakeGemini(deconstruct())
    process_drop(store, storage, pid, gemini_client=g, now=NOW, job="t")
    prompt = g.calls[0]["prompt"]
    assert "Angles already used: take a different one" in prompt and "closes the deal" not in prompt
    listed = prompt.split("Angles already used: take a different one", 1)[1].split("\n\n", 1)[0]
    assert [line[2:] for line in listed.strip().splitlines()[1:]] == [
        "reginald HOOK 11", *(f"Reginald hook {i}" for i in range(10, 1, -1)),
    ]  # at most 10, newest first


def test_no_used_hooks_no_list(world, portrait):
    store, storage = world
    pid = drop_file(store, storage, portrait)
    g = FakeGemini(deconstruct())
    process_drop(store, storage, pid, gemini_client=g, now=NOW, job="t")
    assert "Angles already used" not in g.calls[0]["prompt"]
    # a recheck does not count the drop's own old hook as used
    drop.request_recheck(store, pid, now=NOW)
    g = FakeGemini(deconstruct())
    process_drop(store, storage, pid, gemini_client=g, now=NOW, job="t")
    assert "Angles already used" not in g.calls[0]["prompt"]


# ---- fix round 1: a version keeps a full-length section; refusals say what is true ---------------------------------------------


def flat(seconds: int) -> dict:
    return analysis([2.0] * (2 * seconds))


def version_span(start: float, end: float) -> list[dict]:
    return [{"start_s": start, "end_s": end, "what": "version"}]


@pytest.mark.parametrize(("seconds", "classic"), [(17, False), (22, True), (26, True)])
def test_a_version_never_takes_a_shorter_cut_to_avoid_the_root(seconds, classic):
    """The family's sections are no text: only a clear section of the target length (12 s for a classic, 8 s for any other
    clip) moves a version; clear of the root only 7 s (17 s clip, 22 s classic) or 11 s (26 s classic) are left, so the
    version takes the root's full-length section."""
    best = drop_window(flat(seconds), classic=classic, duration=float(seconds))
    assert best == {"start_s": 0.0, "length_s": 15.0 if classic else 10.0}
    root = version_span(0.0, best["length_s"])
    got = drop._section(flat(seconds), classic=classic, duration=float(seconds), avoid=[], others=root, lead_s=0.0)
    assert got == best


def test_a_version_takes_the_other_strong_full_length_section():
    energy = [5.0] * 20 + [1.0] * 10 + [5.0] * 20 + [1.0] * 10  # 30 s: 0-10 s and 15-25 s move the most
    best = drop_window(analysis(energy), classic=False, duration=30.0)
    assert best == {"start_s": 0.0, "length_s": 10.0}
    got = drop._section(analysis(energy), classic=False, duration=30.0, avoid=[], others=version_span(0.0, 10.0), lead_s=0.0)
    assert got == {"start_s": 15.0, "length_s": 10.0}
    # the root's own section when the family takes every full-length part
    both = [*version_span(0.0, 10.0), *version_span(15.0, 25.0)]
    assert drop._section(analysis(energy), classic=False, duration=30.0, avoid=[], others=both, lead_s=0.0) == best


def test_a_shorter_best_section_lets_a_version_move_to_one_as_long():
    """Text leaves only 7 s clean sections (best = 7 s): a version moves to another clean section of the same length."""
    text = [{"start_s": 7.0, "end_s": 13.0, "what": "text"}]
    best = drop_window(flat(20), classic=False, duration=20.0, avoid=text)
    assert best == {"start_s": 0.0, "length_s": 7.0}
    got = drop._section(flat(20), classic=False, duration=20.0, avoid=text, others=version_span(0.0, 7.0), lead_s=0.0)
    assert got == {"start_s": 13.0, "length_s": 7.0}


def test_copy_from_a_version_says_what_is_true_of_the_original(world):
    store, _ = world
    with_lenny_and_franz(store)
    root = checked(store)
    v = drop.copy_drop(store, root.id, "lenny", now=NOW)
    for state, line in (
        ("checking", "the original clip is being checked again: try in a few minutes"),
        ("blocked", "the original clip can't be used any more"),
        ("failed", "the original clip can't be used any more"),
    ):
        f = store.get_favorite(root.id)
        store.update_favorite(root.id, proposal={**f.proposal, "drop": {**f.proposal["drop"], "state": state}})
        refused(store, v.id, "franz", line)
    refused(store, root.id, "franz", "the clip is not checked yet")  # from the root's own card: as before


def test_the_seeds_parts_are_the_drops_parts():
    assert drop.seed.SWAP_PARTS == drop.PARTS == drop.gemini.PARTS


# ---- the learning tags (docs/launch/measurement-and-learning-plan.md section 2, plan Task 10) ----------------------------------


def test_the_check_stores_the_hit_rules_version_it_ran_under(world, portrait, tmp_path, monkeypatch):
    store, storage = world
    rules = tmp_path / "hit_rules.md"
    rules.write_text("v7 · 2026-10-08\nR1 Score a clip high when its star moves in the first second.\n", encoding="utf-8")
    monkeypatch.setattr(gemini, "HIT_RULES_PATH", rules)
    pid = ready_drop(store, storage, portrait)
    assert store.get_favorite(pid).proposal["drop"]["hit_rules_version"] == "v7"
    pid = drop_file(store, storage, portrait)  # a check that does not end ready keeps none (like the score)
    process_drop(store, storage, pid, gemini_client=FakeGemini(deconstruct(star=DOG_STAR)), now=NOW, job="t")
    assert "hit_rules_version" not in store.get_favorite(pid).proposal["drop"]


def test_a_made_drop_clip_carries_every_learning_tag_from_its_vocabulary(world, portrait, gen_out, fast_master):
    store, storage = world
    pid = ready_drop(store, storage, portrait)
    d = store.get_favorite(pid).proposal["drop"]
    tap_make(store, pid)
    assert make(store, storage, pid, FakeHF(gen_out), FakeGemini(QA_PASS)).state == "made"
    f = store.get_clip(store.get_favorite(pid).clip_id).features
    # the master wrote its length too; the publisher's two tags (first_comment_posted, trial_reel) come when it is posted; the edit
    # record of tests G and H (zoom_pulses, hook_entrance) only when a test asked for an edit (every test is off here)
    assert (clips.LEARN_FEATURES - clips.PUBLISH_FEATURES - clips.EDIT_FEATURES) | clips.REQUIRED_FEATURES <= f.keys()
    assert not (clips.PUBLISH_FEATURES | clips.EDIT_FEATURES) & f.keys()
    assert clips.learn_problems(f) == []  # every value from its vocabulary
    score = d["score"]
    assert {k: f[k] for k in sorted(clips.LEARN_FEATURES - clips.PUBLISH_FEATURES - clips.EDIT_FEATURES - {"length_s"})} == {
        "caption_line1": "label-first", "days_since_trend_peak": None, "episode": None, "explore_pick": False,
        "family_id": pid, "first_comment_kind": "vote", "hit_rules_version": gemini.hit_rules_version(), "hook_by": "studio",
        "hook_index": 1, "length_bucket": "under_8", "part": "featured", "score_bucket": clips.score_bucket(score["total"]),
        "score_potential": score["potential"], "score_swap": score["swap"], "score_total": score["total"], "series": "none",
        "sound_rising": False, "sound_type": "own_trend_sound", "source_kind": "owner_saved", "test_arms": {},
        "trend_stage": "none", "version_index": 1,
    }
    assert abs(f["length_s"] - 7.0) < 0.1  # fast_master's 7 s master
    assert f["format_id"] == "swap_trend" and f["hook_pattern"] == "understatement"  # a named trend; the first hook's pattern
    assert f["presence"] == f["part"] and f["hook_text"] == "The household is unaware."  # the old key stays as an alias
    assert f["hit_rules_version"] != "none"  # the studio's file is versioned


LOOK = deconstruct()
SCORED = {"total": 78, "potential": 7, "swap": 9, "reason": "x"}


def tags(drop_over=None, look=None, adjust_hook=None, proposal=None, version_index=1, part="featured"):
    """``drop.learn_tags`` of a checked drop (pure): the check's card, the effective choices, the pick."""
    look = look or LOOK
    d = {"state": "ready", "classic": look["classic"], "hooks": look["hooks"], "hook": look["hooks"][0], "deconstruct": look,
         "has_audio": True, "score": SCORED, "hit_rules_version": "v1", **(drop_over or {})}
    if adjust_hook is not None:
        d["adjust"] = {"hook": adjust_hook}
    pick = Favorite(id="p1", url="owner-drop:p1", platform="drop", origin="owner", character_slug="reginald",
                    proposal={**(proposal or {}), "drop": d}, status="queued")
    eff = {"hook": adjust_hook or d["hook"], "part": part, "gadgets": []}
    return drop.learn_tags(pick, d, eff, version_index=version_index)


def test_the_format_trend_and_sound_follow_the_clip():
    assert {k: tags()[k] for k in ("format_id", "trend_stage", "sound_type")} == {
        "format_id": "swap_trend", "trend_stage": "none", "sound_type": "own_trend_sound"}
    classic = tags({"classic": True}, look={**LOOK, "classic": True})
    assert (classic["format_id"], classic["trend_stage"]) == ("swap_classic", "classic")
    plain = tags(look={**LOOK, "moment_name": ""})
    assert (plain["format_id"], plain["sound_type"]) == ("swap_other", "own_other")
    assert tags({"has_audio": False})["sound_type"] == "none"  # nothing to keep: no sound
    own = tags({"own_footage": True}, look={**LOOK, "classic": True})
    assert (own["format_id"], own["source_kind"]) == ("own_footage", "own_footage")  # how it was made wins over classic
    assert tags({"auto_filed": True})["source_kind"] == "auto_filed"  # the hits job's picks (plan Task 6)
    assert tags()["source_kind"] == "owner_saved"


def test_the_hits_job_fields_are_copied_when_the_check_has_them():
    got = tags({"trend_stage": "rising", "days_since_trend_peak": 3, "sound_rising": True})
    assert (got["trend_stage"], got["days_since_trend_peak"], got["sound_rising"]) == ("rising", 3, True)
    junk = tags({"trend_stage": "huge", "days_since_trend_peak": "3", "sound_rising": "yes"})
    assert (junk["trend_stage"], junk["days_since_trend_peak"], junk["sound_rising"]) == ("none", None, False)
    classic = tags({"classic": True, "trend_stage": "fading", "days_since_trend_peak": 9}, look={**LOOK, "classic": True})
    assert (classic["trend_stage"], classic["days_since_trend_peak"]) == ("classic", None)  # a classic never fades
    no_stage = tags({"days_since_trend_peak": 3})  # days without a stage: no peak to count from
    assert (no_stage["trend_stage"], no_stage["days_since_trend_peak"]) == ("none", None)
    assert clips.learn_problems(classic) == clips.learn_problems(no_stage) == []


def test_the_hook_used_is_tagged_with_its_pattern_and_who_chose_it():
    first = tags()
    assert (first["hook_pattern"], first["hook_index"], first["hook_by"]) == ("understatement", 1, "studio")
    second = tags(adjust_hook="  breakfast is AT eight. ")  # the owner picked the second candidate (case and spaces aside)
    assert (second["hook_pattern"], second["hook_index"], second["hook_by"]) == ("false-premise", 2, "owner")
    own = tags(adjust_hook="Tea is at four.")  # his own line: none of the three, so no pattern is guessed
    assert (own["hook_pattern"], own["hook_index"], own["hook_by"]) == ("owner", 0, "owner")
    same = tags(adjust_hook="The household is unaware.")  # he picked the first candidate on purpose: still his own choice
    assert (same["hook_pattern"], same["hook_index"], same["hook_by"]) == ("understatement", 1, "owner")


def test_a_drop_checked_before_the_labels_is_made_with_none():
    """A ready drop checked before this build: no pattern labels, no hit-rules version, no score. Its Make it still works and
    says "none" (never a guess); ``drop recheck --all-ready`` gives the others their labels before they are made."""
    old = {k: v for k, v in LOOK.items() if k not in ("hook_patterns", "first_comment_question")}
    got = tags({"score": None, "hit_rules_version": None}, look=old)
    assert (got["hook_pattern"], got["hook_index"], got["hit_rules_version"]) == ("none", 1, "none")
    assert (got["score_bucket"], got["score_total"], got["score_potential"], got["score_swap"]) == ("none", None, None, None)
    assert clips.learn_problems(got) == []


def test_the_score_family_part_series_and_comment_are_copied():
    got = tags(version_index=2, part="star", proposal={"series": "household_unaware", "episode": 4})
    assert (got["score_bucket"], got["score_total"], got["score_potential"], got["score_swap"]) == ("65_79", 78, 7, 9)
    assert (got["family_id"], got["version_index"], got["part"]) == ("p1", 2, "star")
    assert (got["series"], got["episode"]) == ("household_unaware", 4)
    assert tags(proposal={"series": "my own idea", "episode": 0})["series"] == "none"  # only a series of the list
    assert tags(look={**LOOK, "first_comment": ""})["first_comment_kind"] == "none"
    assert (tags()["first_comment_kind"], tags()["caption_line1"], tags()["test_arms"], tags()["explore_pick"]) == (
        "vote", "label-first", {}, False)


def test_a_version_is_tagged_with_its_root_and_its_place(world):
    store, _ = world
    with_lenny_and_franz(store)
    root = checked(store)
    v1 = drop.copy_drop(store, root.id, "lenny", now=NOW)
    v2 = drop.copy_drop(store, root.id, "franz", now=NOW + timedelta(minutes=1))
    assert [drop.version_index(store, store.get_favorite(p.id)) for p in (root, v1, v2)] == [1, 2, 3]
    assert drop.family_root_id(store.get_favorite(v2.id)) == root.id
    store.update_favorite(v1.id, status="skipped")  # a skipped version is no member: the next one moves up
    assert drop.version_index(store, store.get_favorite(v2.id)) == 2
    with pytest.raises(DropError, match="this clip's version was skipped: drop it again"):
        drop.version_index(store, store.get_favorite(v1.id))  # never an index past the family


def test_a_resumed_make_tags_the_hook_it_renders(world, portrait, gen_out, fast_master, monkeypatch):
    """A master that failed keeps its clip; the owner's new Adjust (a new hook) is what the resumed make renders, so the hook
    tags and ``hook_text`` follow the hook on screen, not the one the clip was created with."""
    store, storage = world
    pid = ready_drop(store, storage, portrait)
    tap_make(store, pid)
    fast = drop.build_master

    def broken(spec):
        raise RuntimeError("ffmpeg vanished")

    monkeypatch.setattr(drop, "build_master", broken)
    out = make(store, storage, pid, FakeHF(gen_out), FakeGemini(QA_PASS))
    assert out.state == "failed" and "the master build failed" in out.reason
    clip_id = store.get_favorite(pid).proposal["drop"]["make"]["clip_id"]
    before = store.get_clip(clip_id).features
    assert (before["hook_text"], before["hook_pattern"], before["hook_index"], before["hook_by"]) == (
        "The household is unaware.", "understatement", 1, "studio")
    monkeypatch.setattr(drop, "build_master", fast)
    tap_make(store, pid, adjust={"hook": "Breakfast is at eight."})  # Try again, with the second hook
    assert make(store, storage, pid, FakeHF(gen_out), FakeGemini()).state == "made"
    clip = store.get_clip(clip_id)
    assert clip.hook == "Breakfast is at eight." and fast_master[-1].hook2 == ["Breakfast is at eight."]
    f = clip.features
    assert (f["hook_text"], f["hook_pattern"], f["hook_index"], f["hook_by"]) == (
        "Breakfast is at eight.", "false-premise", 2, "owner")
    assert clips.learn_problems(f) == [] and f["length_bucket"] == "under_8"  # the rest of the tags kept


# ---- a link the cloud cannot fetch: ScrapeCreators' single-post copy (owner 2026-10-07; plan Task 6) --------------------------------


class FakeMedia:
    """``studio.hits.ScrapeCreators.download_post`` stand-in (no network): the clip for the ONE post, or an error."""

    def __init__(self, clip=None, error=None):
        self.clip, self.error, self.calls = clip, error, []

    def download_post(self, url, platform, dest):
        self.calls.append((url, platform))
        if self.error is not None:
            raise self.error
        Path(dest).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(self.clip, dest)
        return {"credits": 10, "media_url": "https://media.example/clip.mp4", "bytes": Path(dest).stat().st_size}


def blocked_ytdlp(cmd):
    return subprocess.CompletedProcess(cmd, 1, "", "ERROR: [TikTok] login required")


def test_a_link_yt_dlp_cannot_fetch_is_checked_from_scrapecreators_copy(world, portrait):
    store, storage = world
    pick, _ = add_drop(store, "reginald", TIKTOK, NOW)
    media = FakeMedia(portrait)
    out = process_drop(store, storage, pick.id, gemini_client=FakeGemini(deconstruct()), runner=blocked_ytdlp, now=NOW, job="t",
                       media_fallback=media)  # fmt: skip
    assert out.state == "ready", out
    assert media.calls == [(TIKTOK, "tiktok")]
    f = store.get_favorite(pick.id)
    assert f.proposal["fetched"]["via"] == "scrapecreators" and f.source_id == f.proposal["drop"]["source_id"]
    (Path(drop.fetch.FETCHED_DIR) / f"{pick.id}.mp4").unlink(missing_ok=True)


def test_without_the_key_a_link_waits_as_before_and_when_both_fail_it_waits_with_both_reasons(world):
    from studio.hits import ScrapeCreatorsError

    store, storage = world
    pick, _ = add_drop(store, "reginald", TIKTOK, NOW)
    out = process_drop(store, storage, pick.id, gemini_client=FakeGemini(), runner=blocked_ytdlp, now=NOW, job="t")
    assert out.state == "waiting" and "login required" in out.reason and "ScrapeCreators" not in out.reason
    media = FakeMedia(error=ScrapeCreatorsError("ScrapeCreators answered HTTP 404: post not found", 404))
    out = process_drop(store, storage, pick.id, gemini_client=FakeGemini(), runner=blocked_ytdlp, now=NOW, job="t", media_fallback=media)
    f = store.get_favorite(pick.id)
    assert out.state == f.proposal["drop"]["state"] == "waiting" and media.calls == [(TIKTOK, "tiktok")]
    assert "login required" in out.reason and "ScrapeCreators" in out.reason and "404" in out.reason
    assert out.reason.endswith("the Mac's daily run tries again") and f.proposal.get("mode") != "recreate"


def test_the_cloud_jobs_hand_the_check_the_scrapecreators_key_from_the_environment(monkeypatch, tmp_path):
    from studio import hits

    store, storage = make_store(), LocalStorage(tmp_path / "s")
    pick, _ = add_drop(store, "reginald", TIKTOK, NOW)
    monkeypatch.setattr(drop, "open_store", lambda: store)
    monkeypatch.setattr(drop, "open_storage", lambda: storage)
    monkeypatch.setattr(drop.gemini.GeminiClient, "from_env", classmethod(lambda cls, env=None, **kw: None))
    monkeypatch.setattr(drop.HiggsfieldClient, "from_env", classmethod(lambda cls, env=None, **kw: None))
    seen = []
    sentinel = FakeMedia(error=hits.ScrapeCreatorsError("no", 404))
    monkeypatch.setattr(hits.ScrapeCreators, "from_env", classmethod(lambda cls, env=None, **kw: sentinel))

    def fake_process(store_, storage_, pick_id, **kw):
        seen.append(kw.get("media_fallback"))
        return drop.Outcome(pick_id, "waiting", "x")

    monkeypatch.setattr(drop, "process_drop", fake_process)
    assert CliRunner().invoke(app, ["drop", "process", pick.id]).exit_code == 0
    assert CliRunner().invoke(app, ["drop", "sweep"]).exit_code == 0
    assert len(seen) == 2 and all(isinstance(m, hits.DownloadBudget) and m.client is sentinel and m.store is store for m in seen)
    assert seen[0].cfg["download_cap_per_day"] == 2  # config/scan.json's caps: at most 2 one-post downloads a London day


# ---- the hits job's tag and the owner's Keep (plan Task 6) ------------------------------------------------------------------------------


def test_a_version_of_an_auto_filed_clip_carries_the_tag(world):
    store, _ = world
    with_lenny_and_franz(store)
    root = checked(store, auto_filed=True)
    v = drop.copy_drop(store, root.id, "lenny", now=NOW)
    assert v.proposal["drop"]["auto_filed"] is True
    plain = checked(store)
    assert "auto_filed" not in drop.copy_drop(store, plain.id, "lenny", now=NOW).proposal["drop"]


def test_keep_is_the_owners_toggle_on_any_drop(world, monkeypatch):
    store, _ = world
    pick = checked(store)
    assert drop.set_keep(store, pick.id, True).proposal["drop"]["keep"] is True
    assert drop.set_keep(store, pick.id, False).proposal["drop"]["keep"] is False
    plain = store.add_favorite(Favorite(url="https://www.tiktok.com/@x/video/1", platform="tiktok", character_slug="reginald"))
    with pytest.raises(DropError):
        drop.set_keep(store, plain.id, True)
    monkeypatch.setattr(drop, "open_store", lambda: store)
    r = CliRunner().invoke(app, ["drop", "keep", pick.id])
    assert r.exit_code == 0, r.output
    assert json.loads(r.output) == {"pick_id": pick.id, "keep": True} and store.get_favorite(pick.id).proposal["drop"]["keep"] is True
    r = CliRunner().invoke(app, ["drop", "keep", pick.id, "--off"])
    assert r.exit_code == 0 and store.get_favorite(pick.id).proposal["drop"]["keep"] is False
    assert CliRunner().invoke(app, ["drop", "keep", plain.id]).exit_code == 2
    assert CliRunner().invoke(app, ["drop", "keep", "nope"]).exit_code == 2


def test_over_the_days_download_cap_the_link_waits_and_scrapecreators_is_not_asked(world, portrait):
    from studio import hits

    store, storage = world
    store.add_hit_spend(NOW.date(), download_credits=20, downloads=2)  # today's 2 one-post downloads are used
    pick, _ = add_drop(store, "reginald", TIKTOK, NOW)
    media = FakeMedia(portrait)
    budget = hits.DownloadBudget(media, store, {"hits": {"download_cap_per_day": 2}}, clock=lambda: NOW)
    out = process_drop(store, storage, pick.id, gemini_client=FakeGemini(), runner=blocked_ytdlp, now=NOW, job="t", media_fallback=budget)
    assert out.state == store.get_favorite(pick.id).proposal["drop"]["state"] == "waiting" and media.calls == []
    assert "login required" in out.reason and "download_cap_per_day" in out.reason and out.reason.endswith("tries again")
    assert store.get_hit_spend(NOW.date()).downloads == 2  # nothing more was spent


# ---- review fix round 1: an auto-filed link is only ever fetched in the cloud (controller ruling 2026-10-08) -----------------------


def auto_link(store, filed, *, state="waiting", tried=(), hit_id=None, url=TIKTOK):
    """A link the hits job filed ``filed`` (London), at ``state``, its failed fetches on the London days ``tried``."""
    pick, _ = add_drop(store, None, url, filed, auto_filed=True, hit={"id": hit_id or "no-such-hit", "lane": "general"})
    d = {**pick.proposal["drop"], "state": state, "reason": "x" if state == "waiting" else None}
    if tried:
        d["fetch_days"] = list(tried)
    return store.update_favorite(pick.id, proposal={**pick.proposal, "drop": d})


def test_an_auto_filed_link_is_never_offered_to_the_mac(world):
    store, _ = world
    waiting = auto_link(store, NOW, tried=[NOW.date().isoformat()])
    checking = auto_link(store, NOW, state="checking", url="https://www.tiktok.com/@dancer.two/video/2")
    asked = auto_link(store, NOW, state="making", url="https://www.tiktok.com/@dancer.three/video/3")
    store.update_favorite(asked.id, proposal={**asked.proposal, "make_requested": {"at": NOW.isoformat(), "by": "owner"}})
    own, _ = add_drop(store, "reginald", "https://www.tiktok.com/@owner.pasted/video/4", NOW)
    store.update_favorite(own.id, proposal={**own.proposal, "drop": {**own.proposal["drop"], "state": "waiting"}})
    mac = pending(store, include_waiting=True, now=NOW)
    assert {(p["pick_id"], p["job"]) for p in mac} == {(own.id, "process"), (asked.id, "make")}  # its make stays the owner's
    assert waiting.id not in {p["pick_id"] for p in mac} and checking.id not in {p["pick_id"] for p in mac}
    cloud = pending(store, now=NOW, auto_retry=True)
    assert {(p["pick_id"], p["job"]) for p in cloud} == {(checking.id, "process"), (asked.id, "make")}  # tried today already


def test_the_cloud_tries_a_waiting_auto_filed_link_on_later_days_while_downloads_allow_then_drops_it(world):
    store, _ = world
    pick = auto_link(store, NOW, tried=[NOW.date().isoformat()])
    jobs = lambda at, retry=True: [(p["pick_id"], p["job"]) for p in pending(store, now=at, auto_retry=retry)]  # noqa: E731
    assert jobs(NOW + timedelta(hours=3)) == []  # the same London day: not again
    assert jobs(NOW + timedelta(days=1)) == [(pick.id, "process")]
    assert jobs(NOW + timedelta(days=1), retry=False) == []  # today's one-post downloads are used: it waits for another day
    assert jobs(NOW + timedelta(days=2)) == [(pick.id, "process")]
    assert jobs(NOW + timedelta(days=3)) == jobs(NOW + timedelta(days=3), retry=False) == [(pick.id, "expire")]


def test_an_auto_filed_link_that_fails_waits_for_the_cloud_not_the_mac_and_counts_its_days(world):
    store, storage = world
    pick, _ = add_drop(store, None, TIKTOK, NOW, auto_filed=True, hit={"id": "h", "lane": "reginald"})
    out = process_drop(store, storage, pick.id, gemini_client=FakeGemini(), runner=blocked_ytdlp, now=NOW, job="t")
    d = store.get_favorite(pick.id).proposal["drop"]
    assert out.state == d["state"] == "waiting" and "Mac" not in out.reason and "the cloud tries again on a later day" in out.reason
    assert "dropped after 3 days" in out.reason and d["fetch_days"] == [NOW.date().isoformat()]
    later = NOW + timedelta(days=1)
    process_drop(store, storage, pick.id, gemini_client=FakeGemini(), runner=blocked_ytdlp, now=later, job="t")
    assert store.get_favorite(pick.id).proposal["drop"]["fetch_days"] == [NOW.date().isoformat(), later.date().isoformat()]


def test_after_three_london_days_an_unfetched_auto_filed_link_is_dropped_and_its_hit_dismissed(world):
    from studio.models import Hit

    store, _ = world
    hit, _ = store.upsert_hit(Hit(platform="tiktok", url=TIKTOK, status="dropped", created_at=NOW, last_seen=NOW))
    pick = auto_link(store, NOW, tried=[NOW.date().isoformat()], hit_id=hit.id)
    with pytest.raises(DropError):
        drop.expire_unfetched(store, pick.id, NOW + timedelta(days=2))  # still within its 3 days
    out = drop.expire_unfetched(store, pick.id, NOW + timedelta(days=3))
    after = store.get_favorite(pick.id)
    assert after.status == "skipped" and after.proposal["drop"]["reason"] == "couldn't be fetched in the cloud: dropped after 3 days"
    assert out["hit_id"] == hit.id and store.get_hit(hit.id).status == "dismissed"
    own, _ = add_drop(store, "reginald", "https://www.tiktok.com/@owner.pasted/video/4", NOW)
    with pytest.raises(DropError):
        drop.expire_unfetched(store, own.id, NOW + timedelta(days=9))  # the owner's own link is never dropped this way


def test_the_cloud_sweep_drops_the_stale_and_retries_the_due_only_while_downloads_allow(monkeypatch, tmp_path):
    store, storage = make_store(), LocalStorage(tmp_path / "s")
    old = auto_link(store, NOW - timedelta(days=3), tried=[(NOW - timedelta(days=3)).date().isoformat()])
    due = auto_link(store, NOW - timedelta(days=1), tried=[(NOW - timedelta(days=1)).date().isoformat()],
                    url="https://www.tiktok.com/@dancer.two/video/2")  # fmt: skip
    monkeypatch.setattr(drop, "open_store", lambda: store)
    monkeypatch.setattr(drop, "open_storage", lambda: storage)
    monkeypatch.setattr(drop, "now_london", lambda: NOW)
    monkeypatch.setattr(drop.gemini.GeminiClient, "from_env", classmethod(lambda cls, env=None, **kw: None))
    monkeypatch.setattr(drop.HiggsfieldClient, "from_env", classmethod(lambda cls, env=None, **kw: None))

    class Spent:
        def refusal(self):
            return "today's 2 one-post downloads are used (hits.download_cap_per_day)"

    monkeypatch.setattr(drop, "_media", lambda store_: Spent())
    seen = []
    monkeypatch.setattr(drop, "process_drop", lambda *a, **kw: seen.append(a[2]) or drop.Outcome(a[2], "waiting", "x"))
    r = CliRunner().invoke(app, ["drop", "sweep"])
    assert r.exit_code == 0, r.output
    assert [x["pick_id"] for x in json.loads(r.output)["results"]] == [old.id] and seen == []  # no retry today: downloads used
    assert store.get_favorite(old.id).status == "skipped"
    assert CliRunner().invoke(app, ["drop", "pending", "--count"]).output.strip() == "0"
    monkeypatch.setattr(drop, "_media", lambda store_: None)  # no key: yt-dlp alone may try again (free)
    assert CliRunner().invoke(app, ["drop", "pending", "--count"]).output.strip() == "1"
    assert CliRunner().invoke(app, ["drop", "sweep"]).exit_code == 0 and seen == [due.id]


# ---- a failed check that has a temporary cause retries itself (task 12) ----------------------------------------------------------

_QUOTA_429 = (
    'the look at the clip failed (Gemini answered HTTP 429: {\n  "error": {\n    "code": 429,\n    "message": "You exceeded your '
    'current quota, please check your plan and bil): tap Try again'
)
_TRANSIENT_REASONS = [  # the strings process_drop really records, and what the sweep makes of them
    ("the look at the clip failed (the Gemini call failed (ReadTimeout)): tap Try again", "timeout"),
    ("the look at the clip failed (the Gemini call failed (ConnectTimeout)): tap Try again", "timeout"),
    ("the look at the clip failed (Gemini timed out on every model (ReadTimeout)): tap Try again", "timeout"),
    (_QUOTA_429, "quota"),
    ("the look at the clip failed (Gemini answered HTTP 503: {\"error\": {\"message\": \"high demand\"}}): tap Try again", "busy"),
    ("the look at the clip failed (Gemini answered HTTP 500: internal): tap Try again", "busy"),
    ("the look at the clip failed (Gemini answered HTTP 502: bad gateway): tap Try again", "busy"),
    ("the look at the clip failed (Gemini answered HTTP 504: gateway timeout): tap Try again", "busy"),
    ("the look at the clip failed (Gemini answered HTTP 429: Resource has been exhausted): tap Try again", "busy"),  # a rate limit, not the day's
    ("the look at the clip failed (the model is busy right now): tap Try again", "busy"),
    # a per-minute rate limit: no daily-quota wording ("exceeded your current quota"), so busy, not a day's wait
    ('the look at the clip failed (Gemini answered HTTP 429: {"error": {"code": 429, "message": "Resource has been exhausted (e.g. '
     'check quota).", "status": "RESOURCE_EXHAUSTED"}}): tap Try again', "busy"),
    ("the look at the clip failed (Gemini answered HTTP 429: Quota exceeded for metric generate_content_free_tier_requests, limit: "
     "15 per minute): tap Try again", "busy"),
    # the daily wording, but the reason names a per-minute limit: still not the day's quota
    ("the look at the clip failed (Gemini answered HTTP 429: You exceeded your current quota ... GenerateRequestsPerMinutePerProject"
     "PerModel-FreeTier): tap Try again", "busy"),
    # a 429 the client told apart at raise time (final review M5): plain words, the tag the retry logic reads
    ("the look at the clip failed (Gemini's daily free quota is used up [quota:day]): it tries again after 08:00 London by itself", "quota"),
    ("the look at the clip failed (Gemini's per-minute limit [quota:minute]): it tries again on the next sweep by itself", "busy"),
    ("the look at the clip failed (Gemini's daily free quota is used up [quota:day]): its automatic retries are used up: tap Try again", "quota"),
    # the network dropped (httpx.NetworkError / ProtocolError): the sweep asks again
    ("the look at the clip failed (the Gemini call failed (ConnectError)): tap Try again", "busy"),
    ("the look at the clip failed (the Gemini call failed (RemoteProtocolError)): tap Try again", "busy"),
    ("the look at the clip failed (the Gemini call failed (ReadError)): tap Try again", "busy"),
    ("the look at the clip failed (the Gemini call failed (WriteError)): tap Try again", "busy"),
    ("the look at the clip failed (Connection reset by peer): tap Try again", "busy"),
    ("the look at the clip failed (network is unreachable): tap Try again", "busy"),
    # a failure that is ours or permanent stays the owner's
    ("the look at the clip failed (the Gemini call failed (UnsupportedProtocol)): tap Try again", None),
    ("the look at the clip failed (the Gemini call failed (DecodingError)): tap Try again", None),
    ("the look at the clip failed (Gemini answered HTTP 403: API key not valid): tap Try again", None),
    ("the look at the clip failed (Gemini answered HTTP 400: unsupported): tap Try again", None),
    ("the look at the clip failed (Gemini answered HTTP 404: no such model): tap Try again", None),
    ("the look at the clip failed (Gemini could not process the uploaded clip (state FAILED)): tap Try again", None),
    ("the check stopped: KeyError: 'x'", None),
    ("the master build failed (ValueError: bad): tap Make it again", None),
    ("", None),
]


@pytest.mark.parametrize(("reason", "kind"), _TRANSIENT_REASONS)
def test_transient_kind_reads_the_reasons_a_failed_check_records(reason, kind):
    assert drop.transient_kind(reason) == kind


def test_transient_kind_takes_no_other_input():
    assert drop.transient_kind(None) is None  # type: ignore[arg-type]
    assert drop.transient_kind(503) is None  # type: ignore[arg-type]


def test_the_quota_resets_at_the_latest_0800_london():
    from datetime import datetime
    from zoneinfo import ZoneInfo

    london = ZoneInfo("Europe/London")
    for now, reset in (
        (datetime(2026, 10, 12, 9, 0, tzinfo=london), datetime(2026, 10, 12, 8, 0, tzinfo=london)),
        (datetime(2026, 10, 12, 8, 0, tzinfo=london), datetime(2026, 10, 12, 8, 0, tzinfo=london)),  # at 08:00 sharp: that day's
        (datetime(2026, 10, 12, 7, 59, tzinfo=london), datetime(2026, 10, 11, 8, 0, tzinfo=london)),
        (datetime(2026, 10, 12, 0, 5, tzinfo=london), datetime(2026, 10, 11, 8, 0, tzinfo=london)),
        (datetime(2026, 10, 12, 23, 59, tzinfo=london), datetime(2026, 10, 12, 8, 0, tzinfo=london)),
        (datetime(2026, 10, 26, 8, 30, tzinfo=london), datetime(2026, 10, 26, 8, 0, tzinfo=london)),  # the clocks went back on the 25th
        (datetime(2026, 7, 1, 6, 30, tzinfo=ZoneInfo("UTC")), datetime(2026, 6, 30, 8, 0, tzinfo=london)),  # any zone in, London out
    ):
        assert drop.last_quota_reset(now) == reset, now
        assert drop.last_quota_reset(now).utcoffset() == reset.utcoffset()


def failed_check(store, storage, clip, reason, *, at=None, **drop_changes):
    """A dropped video whose check failed with ``reason`` (the state ``process_drop`` leaves), at ``at`` (default: now)."""
    pid = drop_file(store, storage, clip)
    f = store.get_favorite(pid)
    d = {**f.proposal["drop"], "state": "failed", "reason": reason, "at": (at or NOW).isoformat(), **drop_changes}
    store.update_favorite(pid, proposal={**f.proposal, "drop": d})
    return pid


TIMEOUT_REASON = _TRANSIENT_REASONS[0][0]


def test_pending_lists_a_check_that_timed_out_until_it_has_been_retried_twice(world, portrait):
    store, storage = world
    pid = failed_check(store, storage, portrait, TIMEOUT_REASON)
    # the row carries the failure as listed (drop.at, drop.auto_retry_at) so a worker can tell it from a later one
    assert pending(store, now=NOW) == [{"pick_id": pid, "job": "process", "state": "failed", "failed_at": NOW.isoformat(), "retried_at": ""}]
    d = store.get_favorite(pid).proposal["drop"]
    for used in (1, 2):
        store.update_favorite(pid, proposal={**store.get_favorite(pid).proposal, "drop": {**d, "auto_retries": used}})
        assert [p["pick_id"] for p in pending(store, now=NOW)] == ([pid] if used < 2 else [])  # at most 2 automatic retries
    assert pending(store, now=NOW, include_waiting=True) == []  # the Mac's daily run never takes it
    assert drop.AUTO_RETRY_MAX == 2


@pytest.mark.parametrize(("reason", "kind"), [r for r in _TRANSIENT_REASONS if r[1] in ("timeout", "busy")])
def test_every_timeout_and_busy_reason_is_pending_again(world, portrait, reason, kind):
    store, storage = world
    pid = failed_check(store, storage, portrait, reason)
    assert [p["pick_id"] for p in pending(store, now=NOW)] == [pid]
    assert drop.auto_retry_kind(store.get_favorite(pid), NOW) == kind


def test_a_check_that_will_never_work_stays_failed_for_the_owner(world, portrait):
    store, storage = world
    for reason, kind in _TRANSIENT_REASONS:
        if kind is None:
            failed_check(store, storage, portrait, reason)
    assert pending(store, now=NOW) == []
    failed_check(store, storage, portrait, None)  # no reason at all
    assert pending(store, now=NOW) == []


def test_a_failed_make_is_never_retried_by_itself_whatever_it_says(world, portrait):
    store, storage = world
    pid = ready_drop(store, storage, portrait)
    tap_make(store, pid)
    f = store.get_favorite(pid)
    for reason in (
        "Higgsfield answered HTTP 503: busy, timed out", "the master build failed (TimeoutError): tap Make it again",
        "the quality check failed twice: Gemini timed out", TIMEOUT_REASON.replace("the look at the clip failed", "the make failed"),
    ):
        store.update_favorite(pid, proposal={**f.proposal, "drop": {**f.proposal["drop"], "state": "failed", "reason": reason,
                                                                     "at": NOW.isoformat()}})
        assert pending(store, now=NOW) == [], reason
        assert drop.auto_retry_kind(store.get_favorite(pid), NOW) is None


def test_a_quota_failure_waits_for_the_quota_to_reset(world, portrait):
    from datetime import datetime
    from zoneinfo import ZoneInfo

    store, storage = world
    london = ZoneInfo("Europe/London")
    pid = failed_check(store, storage, portrait, _QUOTA_429, at=datetime(2026, 10, 11, 21, 40, tzinfo=london))
    evening = datetime(2026, 10, 11, 23, 0, tzinfo=london)
    before_reset = datetime(2026, 10, 12, 7, 59, tzinfo=london)
    after_reset = datetime(2026, 10, 12, 8, 0, tzinfo=london)
    assert pending(store, now=evening) == [] and pending(store, now=before_reset) == []  # the same Pacific day: the quota is still gone
    assert pending(store, now=after_reset) == [
        {"pick_id": pid, "job": "process", "state": "failed", "failed_at": datetime(2026, 10, 11, 21, 40, tzinfo=london).isoformat(),
         "retried_at": ""}  # fmt: skip
    ]
    # a failure after that morning's reset waits for the next one
    pid2 = failed_check(store, storage, portrait, _QUOTA_429, at=datetime(2026, 10, 12, 8, 30, tzinfo=london))
    noon = datetime(2026, 10, 12, 12, 0, tzinfo=london)
    assert [p["pick_id"] for p in pending(store, now=noon)] == [pid]
    assert pid2 in [p["pick_id"] for p in pending(store, now=datetime(2026, 10, 13, 8, 0, tzinfo=london))]
    # a quota retry is limited by the reset (once a day at most) and counted with the others, up to AUTO_RETRY_QUOTA_MAX
    for used, listed in ((0, True), (2, True), (drop.AUTO_RETRY_QUOTA_MAX, False), (5, False)):
        store.update_favorite(pid, proposal={**store.get_favorite(pid).proposal,
                                             "drop": {**store.get_favorite(pid).proposal["drop"], "auto_retries": used}})
        assert (pid in [p["pick_id"] for p in pending(store, now=after_reset)]) is listed, used
    store.update_favorite(pid, proposal={**store.get_favorite(pid).proposal,
                                         "drop": {**store.get_favorite(pid).proposal["drop"], "auto_retries": 0}})
    # a quota failure with no usable time is not guessed at
    pid3 = failed_check(store, storage, portrait, _QUOTA_429, at=None)
    f3 = store.get_favorite(pid3)
    store.update_favorite(pid3, proposal={**f3.proposal, "drop": {**f3.proposal["drop"], "at": "yesterday"}})
    assert pid3 not in [p["pick_id"] for p in pending(store, now=after_reset)]


def test_the_owners_try_again_starts_the_automatic_count_over(world, portrait):
    store, storage = world
    last = NOW - timedelta(hours=3)
    pid = failed_check(store, storage, portrait, TIMEOUT_REASON, auto_retries=2, auto_retry_at=last.isoformat(),
                       requested={"process": (last - timedelta(hours=1)).isoformat()})
    assert pending(store, now=NOW) == [] and drop.auto_retries_used(drop.drop_of(store.get_favorite(pid))) == 2
    f = store.get_favorite(pid)  # request_job / request_check stamp requested.process: that is the owner's tap, after the last retry
    d = {**f.proposal["drop"], "requested": {"process": (last + timedelta(hours=1)).isoformat()}}
    store.update_favorite(pid, proposal={**f.proposal, "drop": d})
    assert drop.auto_retries_used(d) == 0 and [p["pick_id"] for p in pending(store, now=NOW)] == [pid]
    for junk in (None, "x", True, -3, 1.5):  # a count the database should never hold counts as none
        assert drop.auto_retries_used({"auto_retries": junk}) == 0
    assert drop.auto_retries_used({"auto_retries": 1, "requested": "not a mapping"}) == 1


def test_a_leased_failed_check_is_not_listed(world, portrait):
    store, storage = world
    pid = failed_check(store, storage, portrait, TIMEOUT_REASON)
    assert drop.claim(store, pid, "process", "gh-1-1-w1", NOW)
    assert pending(store, now=NOW) == []


def test_a_timed_out_check_is_taken_again_and_counted(world, portrait):
    store, storage = world
    pid = drop_file(store, storage, portrait)
    timeout = gemini.GeminiTimeout("Gemini timed out on every model (ReadTimeout)", "ReadTimeout")
    out = process_drop(store, storage, pid, gemini_client=FakeGemini(timeout), now=NOW, job="t")
    assert out.state == "failed" and "Gemini timed out on every model (ReadTimeout)" in out.reason and "tap Try again" in out.reason
    d = store.get_favorite(pid).proposal["drop"]
    assert d["reason"].startswith(drop.CHECK_FAILED) and "auto_retries" not in d
    with pytest.raises(DropError, match="failed"):  # by hand a failed drop is still refused (the owner's Try again moves it to checking)
        process_drop(store, storage, pid, gemini_client=FakeGemini(), now=NOW, job="t")
    later = NOW + timedelta(minutes=30)
    g = FakeGemini(deconstruct())
    out = process_drop(store, storage, pid, gemini_client=g, now=later, job="gh-1-1-w2", auto_retry=True)
    assert out.ok and out.state == "ready" and len(g.calls) == 1
    d = store.get_favorite(pid).proposal["drop"]
    assert d["auto_retries"] == 1 and d["auto_retry_at"] == later.isoformat() and d["reason"] is None and "job" not in d
    assert "process" not in (d.get("requested") or {}) or d["requested"]["process"] != later.isoformat()  # not the owner's tap


def test_a_check_that_keeps_timing_out_is_retaken_twice_then_left_for_the_owner(world, portrait):
    store, storage = world
    pid = drop_file(store, storage, portrait)
    timeout = gemini.GeminiTimeout("the Gemini call failed (ReadTimeout)", "ReadTimeout")
    assert process_drop(store, storage, pid, gemini_client=FakeGemini(timeout), now=NOW, job="t").state == "failed"
    for n in (1, 2):
        assert [p["pick_id"] for p in pending(store, now=NOW)] == [pid]
        out = process_drop(store, storage, pid, gemini_client=FakeGemini(timeout), now=NOW + timedelta(hours=n), job="w", auto_retry=True)
        assert out.state == "failed" and not out.ok
        assert store.get_favorite(pid).proposal["drop"]["auto_retries"] == n
    assert pending(store, now=NOW + timedelta(hours=3)) == []  # two automatic retries spent: the owner's Try again is next
    g = FakeGemini()
    out = process_drop(store, storage, pid, gemini_client=g, now=NOW + timedelta(hours=3), job="w", auto_retry=True)
    assert out.ok and out.detail["busy"] and out.state == "failed" and g.calls == []  # a stale listing never runs a third time


def test_the_sweep_runs_a_failed_check_again_and_a_busy_one_is_no_failure(monkeypatch, tmp_path, portrait):
    store, storage = sweep_world(monkeypatch, tmp_path)
    pid = failed_check(store, storage, portrait, TIMEOUT_REASON)
    monkeypatch.setattr(drop.gemini.GeminiClient, "from_env", classmethod(lambda cls, env=None, **kw: FakeGemini(deconstruct())))
    r = CliRunner().invoke(app, ["drop", "sweep"])
    assert r.exit_code == 0, r.output
    (row,) = json.loads(r.output)["results"]
    assert row["job"] == "process" and row["pick_id"] == pid and row["state"] == "ready" and row["ok"] is True
    assert store.get_favorite(pid).proposal["drop"]["auto_retries"] == 1
    # the cloud's `drop pending --count` (the workflow's early stop) counts the same drops
    pid2 = failed_check(store, storage, portrait, TIMEOUT_REASON)
    r = CliRunner().invoke(app, ["drop", "pending", "--count"])
    assert r.output.strip() == "1"
    # another worker takes it between the listing and this worker's turn: skipped, no failure
    real = drop.pending

    def listed_then_taken(*a, **kw):
        rows = real(*a, **kw)
        assert drop.claim(store, pid2, "process", "gh-9-1-w2", NOW)
        return rows

    monkeypatch.setattr(drop, "pending", listed_then_taken)
    monkeypatch.setenv("GITHUB_RUN_ID", "9")
    monkeypatch.setenv("STUDIO_WORKER", "1")
    r = CliRunner().invoke(app, ["drop", "sweep"])
    assert r.exit_code == 0, r.output
    (row,) = json.loads(r.output)["results"]
    assert row["busy"] is True and row["ok"] is True and row["state"] == "failed"


def test_a_failed_check_moved_on_by_a_parallel_worker_is_skipped(monkeypatch, tmp_path, portrait):
    store, storage = sweep_world(monkeypatch, tmp_path)
    pid = failed_check(store, storage, portrait, TIMEOUT_REASON)
    (stale_row,) = pending(store, now=NOW)  # what this worker listed
    stale = [stale_row]
    f = store.get_favorite(pid)  # worker 2 already took it back to checking
    store.update_favorite(pid, proposal={**f.proposal, "drop": {**f.proposal["drop"], "state": "checking"}})
    monkeypatch.setattr(drop, "pending", lambda *a, **kw: stale)
    r = CliRunner().invoke(app, ["drop", "sweep"])
    assert r.exit_code == 0, r.output
    (row,) = json.loads(r.output)["results"]
    assert row["moved_on"] is True and row["ok"] is True


# ---- fix round 1 (task 12 review): one retake per sweep, a capped quota retry, a make re-read under the lease -----------------------

TIMEOUT = gemini.GeminiTimeout("Gemini timed out on every model (ReadTimeout)", "ReadTimeout")


def test_a_retake_that_fails_again_is_not_retaken_by_another_worker_of_the_same_sweep(world, portrait):
    """Three workers list the same failed drop. The first retakes it and Gemini times out again (drop.at moves, the drop is
    `failed` still); the second reaches it after that: it must not spend the second automatic retry in the same sweep."""
    store, storage = world
    pid = failed_check(store, storage, portrait, TIMEOUT_REASON)
    (row,) = pending(store, now=NOW)  # what every worker listed
    assert (row["failed_at"], row["retried_at"]) == (NOW.isoformat(), "")
    a, b = FakeGemini(TIMEOUT), FakeGemini(deconstruct())  # B would succeed if it were asked
    first = process_drop(store, storage, pid, gemini_client=a, now=NOW + timedelta(minutes=2), job="gh-9-1-w1", auto_retry=True, listed=row)
    assert first.state == "failed" and not first.ok and len(a.calls) == 1
    d = store.get_favorite(pid).proposal["drop"]
    assert d["auto_retries"] == 1 and d["state"] == "failed" and drop.auto_retry_kind(store.get_favorite(pid), NOW + timedelta(minutes=8))
    second = process_drop(store, storage, pid, gemini_client=b, now=NOW + timedelta(minutes=8), job="gh-9-1-w2", auto_retry=True, listed=row)
    assert second.ok and second.detail["busy"] and second.state == "failed" and b.calls == []
    d = store.get_favorite(pid).proposal["drop"]
    assert d["auto_retries"] == 1 and "job" not in d  # one retry for the whole sweep; the lease is given back
    # the next sweep (two hours on) lists the new failure and may use the second retry
    (later,) = pending(store, now=NOW + timedelta(hours=2))
    assert later["failed_at"] != row["failed_at"] and later["retried_at"] == (NOW + timedelta(minutes=2)).isoformat()
    again = process_drop(store, storage, pid, gemini_client=FakeGemini(TIMEOUT), now=NOW + timedelta(hours=2), job="gh-10-1-w1",
                         auto_retry=True, listed=later)
    assert not again.ok and store.get_favorite(pid).proposal["drop"]["auto_retries"] == 2
    assert pending(store, now=NOW + timedelta(hours=4)) == []  # the cap


def test_the_sweep_skips_a_failed_check_another_worker_retook_and_failed_again(monkeypatch, tmp_path, portrait):
    store, storage = sweep_world(monkeypatch, tmp_path)
    pid = failed_check(store, storage, portrait, TIMEOUT_REASON)
    (stale_row,) = pending(store, now=NOW)
    out = process_drop(store, storage, pid, gemini_client=FakeGemini(TIMEOUT), now=NOW + timedelta(minutes=2), job="gh-9-1-w1",
                       auto_retry=True, listed=stale_row)  # worker 1 retakes it; it fails again, still `failed`
    assert out.state == "failed" and store.get_favorite(pid).proposal["drop"]["state"] == "failed"
    assert drop._moved_on(store, stale_row) is True  # worker 2's listing is stale although the state is the same
    (fresh_row,) = pending(store, now=NOW + timedelta(hours=2))
    assert drop._moved_on(store, fresh_row) is False
    monkeypatch.setattr(drop, "pending", lambda *a, **kw: [stale_row])
    ran = []
    monkeypatch.setattr(drop, "process_drop", lambda *a, **kw: ran.append(a) or drop.Outcome(pid, "failed", ok=False))
    r = CliRunner().invoke(app, ["drop", "sweep"])
    assert r.exit_code == 0, r.output
    (row,) = json.loads(r.output)["results"]
    assert row["moved_on"] is True and row["ok"] is True and ran == [] and store.get_favorite(pid).proposal["drop"]["auto_retries"] == 1


def test_the_sweep_hands_the_listed_failure_to_the_retake(monkeypatch, tmp_path, portrait):
    store, storage = sweep_world(monkeypatch, tmp_path)
    pid = failed_check(store, storage, portrait, TIMEOUT_REASON)
    (listed,) = pending(store, now=NOW)
    seen = []
    monkeypatch.setattr(drop, "process_drop", lambda *a, **kw: seen.append(kw) or drop.Outcome(pid, "ready"))
    r = CliRunner().invoke(app, ["drop", "sweep"])
    assert r.exit_code == 0, r.output
    assert seen[0]["auto_retry"] is True and seen[0]["listed"] == listed
    ordinary = drop_file(store, storage, portrait)  # a plain checking drop: no failure to compare
    seen.clear()
    monkeypatch.setattr(drop, "pending", lambda *a, **kw: [{"pick_id": ordinary, "job": "process", "state": "checking"}])
    assert CliRunner().invoke(app, ["drop", "sweep"]).exit_code == 0
    assert seen[0]["auto_retry"] is False and seen[0]["listed"] is None


def test_a_quota_failure_is_retaken_once_a_day_three_times_then_left_for_the_owner(world, portrait):
    from datetime import datetime
    from zoneinfo import ZoneInfo

    store, storage = world
    london = ZoneInfo("Europe/London")
    quota = GeminiError(
        'Gemini answered HTTP 429: {\n  "error": {\n    "code": 429,\n    "message": "You exceeded your current quota, please check '
        'your plan and billing details."\n  }\n}', 429,
    )
    pid = failed_check(store, storage, portrait, _QUOTA_429, at=datetime(2026, 10, 11, 21, 40, tzinfo=london))
    retakes = 0
    for day in range(8):  # eight London mornings of the sweep after the quota reset
        morning = datetime(2026, 10, 12 + day, 9, 0, tzinfo=london)
        rows = pending(store, now=morning)
        if not rows:
            continue
        (row,) = rows
        out = process_drop(store, storage, pid, gemini_client=FakeGemini(quota), now=morning, job="gh-1-1-w1", auto_retry=True, listed=row)
        assert out.state == "failed" and not out.ok and drop.transient_kind(out.reason) == "quota"
        retakes += 1
        assert pending(store, now=morning + timedelta(hours=10)) == [], day  # failed again after the reset: waits for the next one
    assert retakes == drop.AUTO_RETRY_QUOTA_MAX == 3
    d = store.get_favorite(pid).proposal["drop"]
    assert d["auto_retries"] == 3 and d["state"] == "failed"
    after = datetime(2026, 10, 20, 9, 0, tzinfo=london)
    assert pending(store, now=after) == [] and drop.auto_retry_kind(store.get_favorite(pid), after) is None
    g = FakeGemini()  # a stale listing never runs a fourth time either
    stale = {"pick_id": pid, "job": "process", "state": "failed", "failed_at": d["at"], "retried_at": d["auto_retry_at"]}
    out = process_drop(store, storage, pid, gemini_client=g, now=after, job="gh-2-1-w1", auto_retry=True, listed=stale)
    assert out.ok and out.detail["busy"] and out.state == "failed" and g.calls == []
    # the owner's Try again starts the count over, quota included
    f = store.get_favorite(pid)
    store.update_favorite(pid, proposal={**f.proposal, "drop": {**d, "requested": {"process": datetime(2026, 10, 21, 8, 0, tzinfo=london).isoformat()}}})
    assert drop.auto_retries_used(store.get_favorite(pid).proposal["drop"]) == 0


def test_a_quota_failure_after_two_timeout_retakes_has_one_retake_left(world, portrait):
    from datetime import datetime
    from zoneinfo import ZoneInfo

    store, storage = world
    london = ZoneInfo("Europe/London")
    pid = failed_check(store, storage, portrait, _QUOTA_429, at=datetime(2026, 10, 11, 21, 40, tzinfo=london), auto_retries=2,
                       auto_retry_at=datetime(2026, 10, 11, 20, 0, tzinfo=london).isoformat())
    assert drop.auto_retry_kind(store.get_favorite(pid), datetime(2026, 10, 12, 9, 0, tzinfo=london)) == "quota"  # 2 of 3 used
    f = store.get_favorite(pid)
    store.update_favorite(pid, proposal={**f.proposal, "drop": {**f.proposal["drop"], "auto_retries": 3}})
    assert drop.auto_retry_kind(store.get_favorite(pid), datetime(2026, 10, 12, 9, 0, tzinfo=london)) is None


class NeverHF:
    """A Higgsfield client that fails the test when anything calls it."""

    def __getattr__(self, name):
        pytest.fail(f"Higgsfield was called ({name}): a stale listing paid twice")


@pytest.mark.parametrize("change", ["made by another worker", "Make it taken back"])
def test_a_make_that_is_no_longer_waiting_under_the_lease_is_busy_and_pays_nothing(world, portrait, monkeypatch, change):
    store, storage = world
    pid = ready_drop(store, storage, portrait)
    tap_make(store, pid)
    listed = store.get_favorite(pid)  # what the sweep listed and make_drop first reads: a make the owner asked for, waiting
    f = listed
    if change == "made by another worker":
        store.update_favorite(pid, proposal={**f.proposal, "drop": {**f.proposal["drop"], "state": "made"}})
    else:
        store.update_favorite(pid, proposal={k: v for k, v in f.proposal.items() if k != "make_requested"})
    real, reads = drop._load, []

    def load(store_, pick_id):
        reads.append(pick_id)
        return listed if len(reads) == 1 else real(store_, pick_id)  # the read before the claim is the stale one

    monkeypatch.setattr(drop, "_load", load)
    g = FakeGemini()
    out = make(store, storage, pid, NeverHF(), g)
    assert out.ok and out.detail["busy"] and g.calls == []
    # final review M7: a withdrawn make is not "made by another run"; an already-made video keeps its text
    assert out.reason == ("another run already made this video" if change == "made by another worker" else "this video is no longer waiting to be made")
    assert store.list_clips() == [] and store.ledger_month(NOW.strftime("%Y-%m")) == []  # nothing reserved, nothing generated
    assert "job" not in store.get_favorite(pid).proposal["drop"]  # the lease is given back


def test_a_make_the_owner_asked_for_still_runs_after_the_reread(world, portrait, gen_out, fast_master):
    store, storage = world
    pid = ready_drop(store, storage, portrait)
    tap_make(store, pid)
    out = make(store, storage, pid, FakeHF(gen_out), FakeGemini(QA_PASS))
    assert out.state == "made" and not (out.detail or {}).get("busy")


@pytest.mark.parametrize(
    ("error", "kind"),
    [
        ("connect", "busy"), ("protocol", "busy"), ("read", "busy"),  # the network dropped (httpx.ConnectError / ...)
        ("daily", "quota"), ("minute", "busy"), ("503", "busy"), ("timeout", "timeout"),
    ],
)
def test_the_reasons_the_real_client_writes_are_classified(world, portrait, error, kind):
    """The strings come out of ``GeminiClient`` over a mock transport and ``process_drop`` (nothing leaves the machine)."""
    import httpx

    def handler(request):
        if error == "connect":
            raise httpx.ConnectError("[Errno 8] nodename nor servname provided")
        if error == "protocol":
            raise httpx.RemoteProtocolError("Server disconnected without sending a response.")
        if error == "read":
            raise httpx.ReadError("connection reset")
        if error == "timeout":
            raise httpx.ReadTimeout("The read operation timed out")
        body = {
            "daily": {"error": {"code": 429, "message": "You exceeded your current quota, please check your plan and billing details.",
                                "status": "RESOURCE_EXHAUSTED"}},
            "minute": {"error": {"code": 429, "message": "Resource has been exhausted (e.g. check quota).", "status": "RESOURCE_EXHAUSTED"}},
            "503": {"error": {"code": 503, "message": "The model is overloaded. Please try again later.", "status": "UNAVAILABLE"}},
        }[error]
        return httpx.Response(int(body["error"]["code"]), json=body)

    client = gemini.GeminiClient("k", transport=httpx.MockTransport(handler), sleep=lambda s: None)
    store, storage = world
    pid = drop_file(store, storage, portrait)
    out = process_drop(store, storage, pid, gemini_client=client, now=NOW, job="t")
    assert out.state == "failed" and out.reason.startswith(drop.CHECK_FAILED), out.reason
    assert drop.transient_kind(out.reason) == kind, out.reason
    assert (drop.auto_retry_kind(store.get_favorite(pid), NOW + timedelta(days=1)) == kind)


def google_429(quota_id: str) -> dict:
    """What Google sends with an HTTP 429 RESOURCE_EXHAUSTED: the quota text, then the violation with its quota id."""
    metric = "generativelanguage.googleapis.com/generate_content_free_tier_requests"
    return {"error": {
        "code": 429,
        "message": (
            "You exceeded your current quota, please check your plan and billing details. For more information on this error, head "
            "to: https://ai.google.dev/gemini-api/docs/rate-limits. To monitor your current usage, head to: https://ai.dev/rate-limit. "
            f"\n* Quota exceeded for metric: {metric}, limit: 20, model: gemini-3.8-flash\nPlease retry in 27.7s."
        ),
        "status": "RESOURCE_EXHAUSTED",
        "details": [
            {"@type": "type.googleapis.com/google.rpc.QuotaFailure", "violations": [
                {"quotaMetric": metric, "quotaId": quota_id, "quotaDimensions": {"location": "global", "model": "gemini-3.8-flash"}}
            ]},
            {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "27s"},
        ],
    }}


QUOTA_BODIES = {
    "day": google_429("GenerateRequestsPerDayPerProjectPerModel-FreeTier"),
    "minute": google_429("GenerateRequestsPerMinutePerProjectPerModel-FreeTier"),
}


def quota_client(window: str) -> gemini.GeminiClient:
    import httpx

    body = QUOTA_BODIES[window]
    return gemini.GeminiClient("k", transport=httpx.MockTransport(lambda request: httpx.Response(429, json=body)), sleep=lambda s: None)


@pytest.mark.parametrize(("window", "kind", "words"), [("day", "quota", "08:00 London"), ("minute", "busy", "next sweep")])
def test_a_429_reason_is_plain_short_and_still_read_by_the_retry_logic(world, portrait, window, kind, words):
    """Final review M5 and the controller's 4b: the failed check of 12 Oct read 'Gemini answered HTTP 429: {\\n "error": ...' cut in the
    middle and 'tap Try again'. The window is told at raise time (the quota id sits beyond the 140 characters the reason keeps)."""
    store, storage = world
    pid = drop_file(store, storage, portrait)
    out = process_drop(store, storage, pid, gemini_client=quota_client(window), now=NOW, job="t")
    assert out.state == "failed" and not out.ok and out.reason.startswith(drop.CHECK_FAILED)
    assert f"[quota:{window}]" in out.reason and words in out.reason and "by itself" in out.reason
    assert "{" not in out.reason and "HTTP" not in out.reason and "tap Try again" not in out.reason and len(out.reason) <= 140
    assert drop.transient_kind(out.reason) == kind
    assert store.get_favorite(pid).proposal["drop"]["reason"] == out.reason
    again = drop.auto_retry_kind(store.get_favorite(pid), NOW + timedelta(days=1))
    assert again == kind  # a per-minute 429 is retaken on the next sweep (it is not held for the 08:00 reset)
    right_away = drop.auto_retry_kind(store.get_favorite(pid), NOW + timedelta(minutes=5))
    assert right_away == ("busy" if window == "minute" else None)  # the day's quota waits for the reset
    assert [p["pick_id"] for p in pending(store, now=NOW + timedelta(minutes=5))] == ([pid] if window == "minute" else [])


@pytest.mark.parametrize(("window", "used"), [("day", 3), ("minute", 2)])
def test_a_429_whose_retries_are_used_up_says_so_and_stays_red(world, portrait, window, used):
    store, storage = world
    pid = drop_file(store, storage, portrait)
    f = store.get_favorite(pid)
    store.update_favorite(pid, proposal={**f.proposal, "drop": {**f.proposal["drop"], "auto_retries": used}})
    out = process_drop(store, storage, pid, gemini_client=quota_client(window), now=NOW, job="t")
    assert not out.ok and "by itself" not in out.reason and out.reason.endswith("tap Try again") and f"[quota:{window}]" in out.reason
    assert out.red and not (out.detail or {}).get("will_retry")
    assert drop.transient_kind(out.reason) == ("quota" if window == "day" else "busy")


def test_other_check_failures_keep_their_text():
    """The reasons of everything but a told-apart 429 are what they were: the cut error text and 'tap Try again'."""
    for err in (gemini.GeminiError("Gemini answered HTTP 503: high demand", 503), gemini.GeminiError("Gemini answered HTTP 429: rate limited", 429)):
        reason, again = drop.check_failed_reason(err, {})
        assert reason == f"{drop.CHECK_FAILED} ({str(err)[:140]}): tap Try again" and again is False


def test_a_sweep_whose_only_failures_are_quota_429s_that_retry_by_themselves_exits_0(monkeypatch, tmp_path, portrait):
    """4c: red should mean a real problem. The drop is failed and says so (and its retry is booked), but the run is green."""
    for window in ("day", "minute"):
        store, storage = sweep_world(monkeypatch, tmp_path / window)
        pid = drop_file(store, storage, portrait)
        monkeypatch.setattr(drop.gemini.GeminiClient, "from_env", classmethod(lambda cls, env=None, **kw: quota_client(window)))
        r = CliRunner().invoke(app, ["drop", "sweep"])
        assert r.exit_code == 0, (window, r.output)
        (row,) = json.loads(r.output)["results"]
        assert row["pick_id"] == pid and row["state"] == "failed" and row["ok"] is False and row["will_retry"] is True
        assert store.get_favorite(pid).proposal["drop"]["state"] == "failed"


def test_a_sweep_keeps_exit_1_for_every_other_failure_even_next_to_a_quota_429(monkeypatch, tmp_path, portrait):
    store, storage = sweep_world(monkeypatch, tmp_path)
    quota = drop_file(store, storage, portrait)
    other = drop_file(store, storage, portrait)
    errors = {quota: quota_client("day"), other: FakeGemini(gemini.GeminiError("Gemini answered HTTP 503: high demand", 503))}
    seen = []

    def run(store_, storage_, pick_id, **kw):
        seen.append(pick_id)
        return real(store_, storage_, pick_id, **{**kw, "gemini_client": errors[pick_id]})

    real = drop.process_drop
    monkeypatch.setattr(drop, "process_drop", run)
    r = CliRunner().invoke(app, ["drop", "sweep"])
    assert r.exit_code == 1 and sorted(seen) == sorted([quota, other])
    rows = {x["pick_id"]: x for x in json.loads(r.output)["results"]}
    assert rows[quota]["will_retry"] is True and rows[other]["ok"] is False and "will_retry" not in rows[other]


def test_a_quota_429_whose_retries_are_used_up_keeps_exit_1(monkeypatch, tmp_path, portrait):
    store, storage = sweep_world(monkeypatch, tmp_path)
    pid = drop_file(store, storage, portrait)
    f = store.get_favorite(pid)
    store.update_favorite(pid, proposal={**f.proposal, "drop": {**f.proposal["drop"], "auto_retries": drop.AUTO_RETRY_QUOTA_MAX}})
    monkeypatch.setattr(drop.gemini.GeminiClient, "from_env", classmethod(lambda cls, env=None, **kw: quota_client("day")))
    r = CliRunner().invoke(app, ["drop", "sweep"])
    assert r.exit_code == 1 and "will_retry" not in json.loads(r.output)["results"][0]  # the owner's to look at: red


def test_a_503_alone_keeps_exit_1(monkeypatch, tmp_path, portrait):
    store, storage = sweep_world(monkeypatch, tmp_path)
    drop_file(store, storage, portrait)
    busy = gemini.GeminiError("Gemini answered HTTP 503: high demand", 503)
    monkeypatch.setattr(drop.gemini.GeminiClient, "from_env", classmethod(lambda cls, env=None, **kw: FakeGemini(busy)))
    assert CliRunner().invoke(app, ["drop", "sweep"]).exit_code == 1


def test_a_single_process_run_that_hits_a_retrying_quota_429_exits_0_and_any_other_failure_1(monkeypatch, tmp_path, portrait):
    store, storage = sweep_world(monkeypatch, tmp_path)
    pid = drop_file(store, storage, portrait)
    monkeypatch.setattr(drop.gemini.GeminiClient, "from_env", classmethod(lambda cls, env=None, **kw: quota_client("minute")))
    r = CliRunner().invoke(app, ["drop", "process", pid])
    assert r.exit_code == 0, r.output
    out = json.loads(r.output)
    assert out["state"] == "failed" and out["ok"] is False and out["will_retry"] is True
    pid2 = drop_file(store, storage, portrait)
    monkeypatch.setattr(drop.gemini.GeminiClient, "from_env", classmethod(lambda cls, env=None, **kw: FakeGemini(
        gemini.GeminiError("Gemini answered HTTP 403: API key not valid", 403))))
    r = CliRunner().invoke(app, ["drop", "process", pid2])
    assert r.exit_code == 1 and "will_retry" not in json.loads(r.output)


# ---- the check writes one hook per arm of the hook bandit (task 15 concern 1) ----------------------------------------------------------

B_DAY = datetime(2026, 10, 13, 12, 0, tzinfo=drop.LONDON)  # a Tuesday: test B has started (12 Oct)


def test_hook_arms_for_reads_the_bandits_arms_of_the_character(experiments_on):
    franz = drop.hook_arms_for("franz", B_DAY)
    assert franz == gemini.HookArms(("ego-claim", "when-relatable", "myth-bust", "trend-label"), needs_moment=("trend-label",))
    assert drop.hook_arms_for("reginald", B_DAY).patterns == ("false-premise", "understatement", "trend-label")
    assert drop.hook_arms_for("biscuit", B_DAY) is None  # no arms in the registry: three free hooks
    assert drop.hook_arms_for("franz", datetime(2026, 10, 11, 12, 0, tzinfo=drop.LONDON)) is None  # test B has not started


def test_no_arms_while_test_b_is_off_or_the_registry_is_broken(tmp_path, monkeypatch, caplog):
    assert drop.hook_arms_for("franz", B_DAY) is None  # the suite's registry has every test off
    bad = tmp_path / "experiments.json"
    bad.write_text("nope")
    monkeypatch.setattr(drop.experiments, "EXPERIMENTS_PATH", bad)
    with caplog.at_level("WARNING", logger="studio.drop"):
        assert drop.hook_arms_for("franz", B_DAY) is None  # a free look is never stopped by it: three free hooks (Make it stops itself)
    assert "test registry" in caplog.text


def test_the_check_asks_one_gemini_call_for_one_hook_per_arm_and_stores_them_in_the_same_shape(world, portrait, experiments_on):
    store, storage = world
    pid = drop_file(store, storage, portrait)  # Reginald: false-premise, understatement, trend-label (the clip has a moment name)
    patterns = ["understatement", "trend-label", "false-premise"]
    g = FakeGemini(deconstruct(hook_patterns=patterns))  # FakeGemini runs the check function: the arms are in it, or this raises
    out = process_drop(store, storage, pid, gemini_client=g, now=B_DAY, job="t")
    assert out.state == "ready" and len(g.calls) == 1
    d = store.get_favorite(pid).proposal["drop"]
    assert d["hooks"] == deconstruct()["hooks"] and d["deconstruct"]["hook_patterns"] == patterns  # the stored shape: lists, same order
    assert d["hook"] == d["hooks"][0]
    props = g.calls[0]["schema"]["properties"]
    assert props["hooks"]["minItems"] == props["hooks"]["maxItems"] == 3
    assert "ONE hook for each of these patterns: false-premise" in g.calls[0]["prompt"]


def test_a_check_with_four_arms_stores_four_hooks_and_the_adjust_sheet_gets_all_of_them(world, portrait, experiments_on):
    store, storage = world
    store.add_character(Character(slug="franz", name="Franz", bodies=[Body.biped, Body.quadruped]))
    pid = drop_file(store, storage, portrait, slug="franz")
    hooks = ["I invented this walk.", "When the hallway is your runway.", "They said a dog cannot do this.", "The shoulder shimmy, as ordered."]
    patterns = ["ego-claim", "when-relatable", "myth-bust", "trend-label"]
    star = {"kind": "dog", "body": "quadruped", "description": "the dachshund by the door", "x_center": 0.5, "full_body": True, "child": False}
    g = FakeGemini(deconstruct(star=star, hooks=hooks, hook_patterns=patterns, recommended={"slug": "franz", "reason": "dog star: Franz"}))
    out = process_drop(store, storage, pid, gemini_client=g, now=B_DAY, job="t")
    assert out.state == "ready", out.reason
    assert g.calls[0]["schema"]["properties"]["hooks"]["maxItems"] == 4
    d = store.get_favorite(pid).proposal["drop"]
    assert d["hooks"] == hooks and d["deconstruct"]["hook_patterns"] == patterns and d["hook"] == hooks[0]


def answering_client(*answers) -> tuple[gemini.GeminiClient, list]:
    """The real client over a mock transport answering with ``answers`` in turn (nothing leaves the machine); the list is the requests."""
    import httpx

    queue, seen = list(answers), []

    def handler(request):
        seen.append(request)
        body = {"candidates": [{"content": {"role": "model", "parts": [{"text": json.dumps(queue.pop(0))}]}, "finishReason": "STOP"}]}
        return httpx.Response(200, json=body)

    return gemini.GeminiClient("k", transport=httpx.MockTransport(handler), sleep=lambda s: None), seen


def test_a_first_answer_that_misses_an_arm_is_asked_again_and_a_second_miss_still_ends_ready(world, portrait, experiments_on):
    """Final review I1: the arm coverage fails open. The retry names the gap; if the model still misses, that arm has no candidate,
    the check ends ready (not failed, not red) and the draw falls through to an arm that has one."""
    store, storage = world
    pid = drop_file(store, storage, portrait)
    gap = deconstruct(hook_patterns=["understatement", "false-premise", "understatement"])  # no trend-label although the clip has a moment
    client, seen = answering_client(gap, gap)
    out = process_drop(store, storage, pid, gemini_client=client, now=B_DAY, job="t")
    assert out.ok and out.state == "ready" and len(seen) == 2  # asked once more, then taken as it is
    assert "hook_patterns must include trend-label" in json.loads(seen[1].content)["contents"][0]["parts"][1]["text"]
    d = store.get_favorite(pid).proposal["drop"]
    assert d["state"] == "ready" and d["reason"] is None and d["hooks"] == gap["hooks"]
    look = d["deconstruct"]
    state = drop.learn.BanditState(readings={"reginald": 20})
    registry = drop.experiments.load_experiments()
    chosen = {
        drop.learn.choose_hook(
            store, registry, "reginald", f"pick-{i}", look["hooks"], look["hook_patterns"], moment=True, now=B_DAY, state=state,
        ).pattern
        for i in range(60)
    }
    assert chosen == {"understatement", "false-premise"}  # trend-label has no candidate: the others are drawn, never "no choice"


def test_an_answer_with_every_arm_is_taken_at_once_and_a_broken_shape_still_fails_the_check(world, portrait, experiments_on):
    store, storage = world
    pid = drop_file(store, storage, portrait)
    good = deconstruct(hook_patterns=["understatement", "false-premise", "trend-label"])
    client, seen = answering_client(good)
    assert process_drop(store, storage, pid, gemini_client=client, now=B_DAY, job="t").state == "ready" and len(seen) == 1
    other = drop_file(store, storage, portrait)
    short = deconstruct(hooks=["One.", "Two."], hook_patterns=["understatement", "false-premise"])  # 2 hooks where 3 are asked
    client, seen = answering_client(short, short)
    out = process_drop(store, storage, other, gemini_client=client, now=B_DAY, job="t")
    assert out.state == "failed" and "hooks must be 3 lines" in out.reason and len(seen) == 2


def test_a_bandit_draw_always_finds_a_candidate_when_the_check_wrote_one_hook_per_arm(world, portrait, experiments_on):
    """The point of the change: with one hook per arm every arm has a candidate, so no clip falls back to the check's first hook."""
    store, storage = world
    pid = drop_file(store, storage, portrait)
    patterns = ["understatement", "trend-label", "false-premise"]
    process_drop(store, storage, pid, gemini_client=FakeGemini(deconstruct(hook_patterns=patterns)), now=B_DAY, job="t")
    look = store.get_favorite(pid).proposal["drop"]["deconstruct"]
    registry = drop.experiments.load_experiments()
    state = drop.learn.BanditState(readings={"reginald": 20})  # past the warm-up: a draw by the shares, not the fixed rotation
    chosen = {
        drop.learn.choose_hook(
            store, registry, "reginald", f"pick-{i}", look["hooks"], look["hook_patterns"], moment=True, now=B_DAY, state=state,
        ).pattern
        for i in range(60)
    }
    assert chosen == set(patterns)  # none is None, and every arm is drawn sometimes


# ---- tests G and H at the master: the clip's coins become the spec's edits; the master says what it applied ----------------------------


def make_reporting(world, portrait, gen_out, monkeypatch, synth_video, applied):
    """Make one drop with the master build replaced by a copy of a ready master that, like the real build, leaves ``applied`` in
    ``spec.applied`` (``None``: it reports nothing). Returns (store, the specs the build was given, the made clip)."""
    store, storage = world
    ready = synth_video(w=1080, h=1920, dur=7)
    specs = []

    def build(spec):
        specs.append(spec)
        if applied is not None:
            spec.applied = dict(applied)
        Path(spec.out).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ready, spec.out)
        return Path(spec.out)

    monkeypatch.setattr(drop, "build_master", build)
    pid = ready_drop(store, storage, portrait)
    tap_make(store, pid)
    assert make(store, storage, pid, FakeHF(gen_out), FakeGemini(QA_PASS)).state == "made"
    return store, specs, store.get_clip(store.get_favorite(pid).clip_id)


def reginalds_first_coins():
    from studio import experiments

    reg = experiments.load_experiments()
    return {t.key: experiments.block_arm(reg, t, "reginald", 0) for t in (reg.test("G"), reg.test("H"))}


def test_the_clips_two_coins_become_the_masters_edits_and_what_was_applied_is_written_on_the_clip(
    world, portrait, gen_out, monkeypatch, synth_video, experiments_on
):
    coins = reginalds_first_coins()  # the real make path hands them out: the clip carries zoom and word_pop
    store, specs, clip = make_reporting(world, portrait, gen_out, monkeypatch, synth_video, {"zoom_pulses": 4, "hook_entrance": "slam", "beats": 20})
    assert {k: clip.features["test_arms"][k] for k in ("zoom", "word_pop")} == coins
    assert specs[-1].edits == {"zoom_pulses": coins["zoom"], "word_pop": coins["word_pop"]}
    f = clip.features
    assert (f["zoom_pulses"], f["hook_entrance"], f["beats"]) == (4, "slam", 20)
    assert clips.learn_problems(f) == []


def test_a_master_that_found_no_beat_is_recorded_so_the_analysis_leaves_it_out(
    world, portrait, gen_out, monkeypatch, synth_video, experiments_on
):
    coins = reginalds_first_coins()
    _, specs, clip = make_reporting(world, portrait, gen_out, monkeypatch, synth_video, {"zoom_pulses": 0, "hook_entrance": "none", "beats": 0})
    assert specs[-1].edits is not None  # the arms asked, the master heard no beat and applied neither
    assert (clip.features["zoom_pulses"], clip.features["hook_entrance"], clip.features["beats"]) == (0, "none", 0)
    assert {k: clip.features["test_arms"][k] for k in ("zoom", "word_pop")} == coins  # the arm stays: it is what the coin said


def test_a_clip_without_the_two_coins_is_built_as_before_and_writes_no_edit_tags(world, portrait, gen_out, monkeypatch, synth_video):
    """Every test is off here (conftest): no coin, so no ``edits`` on the spec at all: the same master as before the tests."""
    _, specs, clip = make_reporting(world, portrait, gen_out, monkeypatch, synth_video, {"zoom_pulses": 9, "hook_entrance": "slam", "beats": 9})
    assert specs[-1].edits is None
    assert not clips.EDIT_FEATURES & clip.features.keys() and clip.features["test_arms"] == {}


def test_a_silent_masters_clip_takes_no_position_and_is_built_without_edits(world, portrait, experiments_on):
    store, storage = world
    pid = ready_drop(store, storage, portrait)
    f = store.get_favorite(pid)
    store.update_favorite(pid, proposal={**f.proposal, "owner_music": "in_app"})  # the owner adds the song in the app: silent master
    clip = drop._new_or_current_clip(store, store.get_favorite(pid), NOW)
    assert "zoom" not in clip.features["test_arms"] and "word_pop" not in clip.features["test_arms"]
    assert drop.edits_from_arms(clip.features["test_arms"]) is None  # so the master is built exactly as before


def test_an_edit_the_master_did_not_report_writes_nothing(world, portrait, gen_out, monkeypatch, synth_video, experiments_on):
    _, specs, clip = make_reporting(world, portrait, gen_out, monkeypatch, synth_video, None)
    assert specs[-1].edits is not None and specs[-1].applied == {}  # a build that says nothing (a fake, an older master)
    assert not clips.EDIT_FEATURES & clip.features.keys()
