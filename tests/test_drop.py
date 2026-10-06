"""``studio drop``: a video the owner drops is checked for free, then made (paid) only after the owner's Make it.

Real ffmpeg on small synthetic clips; Gemini, Higgsfield and yt-dlp are fakes (no request leaves the machine). What matters:
no credits without ``proposal.make_requested``; the cap and the kill switch refuse; the submit is never repeated blindly; the
like-for-like, child-as-the-star, watermark and burned-in-text checks block (children elsewhere in the clip do not); one
automatic re-roll then stop; the master ends on the dance with the clip's own sound and the hook on screen; every step
resumes where the clip is.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from datetime import timedelta
from pathlib import Path

import pytest
from typer.testing import CliRunner

from studio import budget, drop
from studio.cli import app
from studio.config import now_london
from studio.drop import DropError, add_drop, attach_file, drop_window, make_drop, pending, process_drop, validate_adjust
from studio.favorites import next_favorites
from studio.gemini import GeminiBlocked, GeminiError
from studio.higgsfield_api import PollTimeout, RequestStatus, Submitted, SubmitUncertain
from studio.media.qa import probe
from studio.models import Body, Character, ClipState, Settings
from studio.storage import LocalStorage
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
        "caption": {"title": "Shoulder shimmy · butler edition", "joke": "The corridor has been informed.",
                    "send": "Send this to your butler.", "question": "Which eye did you notice first?", "tease": "Next week: the stairs."},
        "first_comment": "Requests for next week may be left below. Within reason.",
        "hashtags": ["#shouldershimmy", "#butler", "#deadpan", "#oddeyes"], "notes": "",
        "watermark_spans": [], "burned_in_text_spans": [],
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
    assert store.get_favorite(pid).proposal["drop"]["crop_x"] == 0.3


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


def test_make_it_swaps_qas_masters_and_waits_for_the_owners_ok(world, portrait, gen_out):
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
    assert sub["prompt"].startswith("Replace the man in the grey suit with the butler from the reference images.")
    assert "black umbrella" in sub["prompt"] and len(sub["prompt"]) < 400
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
    assert clip.caption.splitlines()[0] == "Shoulder shimmy · butler edition" and clip.hook == "The household is unaware."
    assert clip.caption.splitlines()[2] == "Send this to your butler."  # the first engagement kind
    assert clip.hashtags == ["#shouldershimmy", "#butler", "#deadpan", "#oddeyes"]
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
