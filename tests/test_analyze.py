"""``studio.media.analyze`` and ``studio source analyze``: the free local analysis of a clip.

Real ffmpeg on tiny synthetic clips: a white box that sits still and then swings about (motion in a known window), a click
track at a known tempo (the beat), a hard cut between two backdrops (a change of shot).
"""

from __future__ import annotations

import json
import math
import struct
import subprocess
import wave
from pathlib import Path

import pytest
from PIL import Image
from typer.testing import CliRunner

from studio import sources
from studio.cli import app
from studio.media import analyze
from studio.media.analyze import AnalysisError, analyze_clip, best_window
from studio.media.qa import QAError, contact_sheet
from studio.models import Body, Source, SourceKind
from studio.storage import LocalStorage
from studio.store import MemoryStore


def ffmpeg(*args: str) -> None:
    proc = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y", *args],
        capture_output=True, text=True, stdin=subprocess.DEVNULL,
    )  # fmt: skip
    assert proc.returncode == 0, proc.stderr[-600:]


def click_track(path: Path, bpm: float, seconds: float, offset: float = 0.25, rate: int = 44100) -> Path:
    """A WAV of short 1.5 kHz bursts on a beat (``offset`` seconds in, then every 60 / bpm seconds), silence between."""
    period = 60.0 / bpm
    samples = [0] * int(seconds * rate)
    t = offset
    while t < seconds - 0.05:
        start = int(t * rate)
        for n in range(int(0.03 * rate)):
            samples[start + n] = int(22000 * math.sin(2 * math.pi * 1500 * n / rate) * (1 - n / (0.03 * rate)))
        t += period
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"".join(struct.pack("<h", s) for s in samples))
    return path


def make_clip(
    path: Path,
    segments: list[tuple[str, float, tuple[float, float] | None]],
    *,
    audio: Path | None = None,
    size: str = "160x284",
) -> Path:
    """Backdrops in a row; ``(colour, seconds, (from, to))``: a white box swings about between from and to seconds of the
    segment and sits still the rest of it (``None``: it never moves). A colour change between segments is a hard cut."""
    parts, joined = [], []
    for i, (colour, secs, moving) in enumerate(segments):
        gate = f"between(t,{moving[0]},{moving[1]})" if moving else "0"
        parts.append(
            f"color=c={colour}:s={size}:r=30:d={secs}[b{i}];color=c=white:s=40x40:r=30:d={secs}[w{i}];"
            f"[b{i}][w{i}]overlay=x='100+60*sin(12*t)*{gate}':y=120[v{i}]"
        )
        joined.append(f"[v{i}]")
    graph = ";".join(parts) + f";{''.join(joined)}concat=n={len(segments)}:v=1:a=0[v]"
    args = ["-filter_complex", graph]
    if audio:
        args += ["-i", str(audio)]
    args += ["-map", "[v]"]
    if audio:
        args += ["-map", "0:a", "-c:a", "aac", "-b:a", "128k", "-shortest"]
    args += ["-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(path)]
    ffmpeg(*args)
    return path


@pytest.fixture(scope="module")
def tmp(tmp_path_factory) -> Path:
    return tmp_path_factory.mktemp("analyze")


@pytest.fixture(scope="module")
def dance(tmp) -> Path:
    """14 s: the box is still, swings between 4 s and 10 s, is still again; a click track at 120 bpm (first click at 0.25 s)."""
    return make_clip(tmp / "dance.mp4", [("0x202020", 14, (4, 10))], audio=click_track(tmp / "clicks.wav", 120, 14))


@pytest.fixture(scope="module")
def silent_dance(tmp) -> Path:
    return make_clip(tmp / "silent.mp4", [("0x202020", 14, (4, 10))])


@pytest.fixture(scope="module")
def result(dance, tmp) -> dict:
    return analyze_clip(dance, tmp / "sheet.png")


# ---- motion energy -------------------------------------------------------------------------------------------------


def test_motion_energy_is_low_while_the_picture_is_still_and_high_while_it_moves(result):
    energy = result["motion"]["energy"]
    assert result["motion"]["step_s"] == 0.5 and len(energy) == 28  # 14 s in half seconds
    still = energy[1:7] + energy[22:27]  # 0.5-3.5 s and 11-13.5 s
    moving = energy[9:19]  # 4.5-9.5 s
    assert max(still) < 0.5 and min(moving) > 3.0
    assert result["motion"]["peak"] == max(energy) and result["motion"]["cuts"] == []  # fast movement is not a cut


def test_a_hard_change_of_backdrop_is_a_cut_at_the_right_second(tmp):
    clip = make_clip(tmp / "cut.mp4", [("0x202020", 5, (0, 5)), ("0xd0d0d0", 5, (0, 5))])
    energy, cuts = analyze.motion_profile(clip, 10.0)
    assert len(cuts) == 1 and abs(cuts[0] - 5.0) <= 0.2
    assert max(energy) < 12  # the cut itself is not movement: it never makes its half second the liveliest


# ---- the beat -------------------------------------------------------------------------------------------------------


def test_the_tempo_is_found_within_a_few_bpm(result):
    assert result["has_audio"] is True
    assert result["audio"]["bpm"] == pytest.approx(120.0, abs=3.0)


def test_the_beats_land_on_the_clicks(result):
    beats = result["audio"]["beats"]
    assert len(beats) >= 20 and result["audio"]["beat_count"] >= 20
    clicks = [0.25 + 0.5 * k for k in range(26)]
    for b in beats[:24]:
        assert min(abs(b - c) for c in clicks) < 0.04, b


@pytest.mark.parametrize("bpm", [96, 140])
def test_other_tempos_are_found_too(tmp, bpm):
    clip = make_clip(tmp / f"t{bpm}.mp4", [("0x202020", 12, None)], audio=click_track(tmp / f"c{bpm}.wav", bpm, 12, offset=0.1))
    got = analyze_clip(clip, tmp / f"s{bpm}.png")["audio"]["bpm"]
    assert got == pytest.approx(bpm, abs=bpm * 0.03)


def test_a_slow_pulse_is_folded_into_the_dance_range(tmp):
    clip = make_clip(tmp / "t60.mp4", [("0x202020", 14, None)], audio=click_track(tmp / "c60.wav", 60, 14, offset=0.1))
    assert analyze_clip(clip, tmp / "s60.png")["audio"]["bpm"] == pytest.approx(120.0, abs=4.0)  # 60 reads as 120


def test_no_audio_and_a_silent_track_have_no_tempo_rather_than_a_made_up_one(tmp, silent_dance):
    no_audio = analyze_clip(silent_dance, tmp / "n.png")
    assert (no_audio["has_audio"], no_audio["audio"]["bpm"], no_audio["audio"]["beats"]) == (False, None, [])
    silence = tmp / "silence.wav"
    with wave.open(str(silence), "wb") as w:
        w.setnchannels(1), w.setsampwidth(2), w.setframerate(44100), w.writeframes(b"\x00\x00" * 44100 * 8)  # noqa: E701
    clip = make_clip(tmp / "quiet.mp4", [("0x202020", 8, None)], audio=silence)
    quiet = analyze_clip(clip, tmp / "q.png")
    assert quiet["has_audio"] is True and quiet["audio"]["bpm"] is None and quiet["audio"]["beats"] == []


def test_a_steady_tone_is_not_a_beat(tmp):
    clip = tmp / "tone.mp4"
    ffmpeg(
        "-f", "lavfi", "-i", "color=c=0x202020:s=160x284:r=30:d=10", "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100:duration=10",
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(clip),
    )  # fmt: skip
    assert analyze_clip(clip, tmp / "tone.png")["audio"]["bpm"] is None


# ---- the best window ------------------------------------------------------------------------------------------------


def test_the_best_window_is_the_six_to_nine_seconds_that_hold_the_movement(result):
    w = result["best_window"]
    assert 6.0 <= w["duration_s"] <= 9.0
    assert abs(w["start_s"] - 4.0) <= 0.5 and abs(w["end_s"] - 10.0) <= 0.5
    assert w["aligned_to_beats"] is True and w["cuts_inside"] == 0
    assert w["motion"] > 3.0


def test_without_a_beat_the_window_is_chosen_by_motion_alone(tmp, silent_dance):
    w = analyze_clip(silent_dance, tmp / "silent.png")["best_window"]
    assert (w["start_s"], w["end_s"], w["aligned_to_beats"]) == (4.0, 10.0, False)  # the shortest window that holds it all


def test_a_window_that_can_start_on_a_hard_cut_does_not_straddle_it():
    # the same movement all along, one cut at 3 s: windows that straddle it are discounted, one that starts on it is not
    w = best_window([4.0] * 28, [3.0], [], None, 14.0)
    assert (w["start_s"], w["end_s"], w["cuts_inside"]) == (3.0, 9.0, 0)
    straddling = best_window([4.0] * 28, [3.0], [], None, 6.0)  # nowhere else to go: it has to hold the cut
    assert straddling["cuts_inside"] == 1 and straddling["motion"] == 4.0


def test_a_cut_is_not_movement_and_does_not_make_its_half_second_the_liveliest(tmp):
    clip = make_clip(tmp / "cutmotion.mp4", [("0x202020", 5, None), ("0xd0d0d0", 9, None)])  # nothing moves, one cut at 5 s
    energy, cuts = analyze.motion_profile(clip, 14.0)
    assert len(cuts) == 1 and abs(cuts[0] - 5.0) <= 0.2 and max(energy) < 0.5


def test_a_clip_shorter_than_six_seconds_is_its_own_window(tmp):
    clip = make_clip(tmp / "short.mp4", [("0x202020", 4, (0, 4))])
    w = analyze_clip(clip, tmp / "short.png")["best_window"]
    assert w["start_s"] == 0.0 and w["end_s"] == pytest.approx(4.0, abs=0.1) and "whole clip" in w["note"]


def test_best_window_prefers_the_shorter_one_when_everything_is_equal_and_never_leaves_the_clip():
    flat = [2.0] * 40  # 20 s of identical motion
    w = best_window(flat, [], [], None, 20.0)
    assert (w["start_s"], w["duration_s"]) == (0.0, 6.0)
    end = best_window([0.0] * 30 + [5.0] * 10, [], [], None, 20.0)  # the action is the last 5 s
    assert end["end_s"] == 20.0 and 6.0 <= end["duration_s"] <= 9.0


def test_a_beat_moves_the_edges_onto_beats_only_when_the_length_stays_in_range():
    beats = [0.1 + 0.5 * k for k in range(40)]
    energy = [0.0] * 8 + [5.0] * 12 + [0.0] * 20  # action 4-10 s
    w = best_window(energy, [], beats, 120.0, 20.0)
    assert w["aligned_to_beats"] is True
    on_a_beat = lambda t: min((t - 0.1) % 0.5, 0.5 - (t - 0.1) % 0.5) < 1e-6  # noqa: E731
    assert on_a_beat(w["start_s"]) and on_a_beat(w["end_s"])
    assert 6.0 <= w["duration_s"] <= 9.0


# ---- the contact sheet -----------------------------------------------------------------------------------------------


def test_the_contact_sheet_is_a_three_by_three_png(result):
    sheet = result["contact_sheet"]
    assert (sheet["cols"], sheet["rows"], len(sheet["times"])) == (3, 3, 9)
    assert sheet["times"][0] == 0 and sheet["times"] == sorted(sheet["times"]) and sheet["times"][-1] < 14.0
    with Image.open(sheet["path"]) as img:
        assert img.format == "PNG" and img.size[0] == 3 * 320 and img.size[1] >= 3 * 500  # 160x284 cells scaled to 320 wide


def test_contact_sheet_refuses_a_bad_size_or_file(tmp, dance):
    with pytest.raises(ValueError):
        contact_sheet(dance, tmp / "x.gif")
    with pytest.raises(ValueError):
        contact_sheet(dance, tmp / "x.png", cols=0)
    with pytest.raises(QAError):
        contact_sheet(tmp / "missing.mp4", tmp / "x.png")


# ---- what the result carries --------------------------------------------------------------------------------------------


def test_the_result_is_json_with_the_probe_the_motion_the_audio_and_the_window(result):
    json.dumps(result)  # serialisable as is
    assert result["duration_s"] == pytest.approx(14.0, abs=0.1) and (result["width"], result["height"]) == (160, 284)
    assert {"file", "fps", "has_audio", "source_problems", "motion", "audio", "best_window", "contact_sheet"} <= set(result)
    assert any("resolution" in p for p in result["source_problems"])  # 160 px wide is under the 480 px a source needs


def test_errors_are_named_not_crashes(tmp):
    with pytest.raises(QAError):
        analyze_clip(tmp / "nope.mp4", tmp / "x.png")
    text = tmp / "note.txt"
    text.write_text("not a video")
    with pytest.raises(QAError):
        analyze_clip(text, tmp / "x.png")


def test_a_clip_over_three_minutes_is_refused(tmp, monkeypatch, dance):
    from studio.media.qa import TechReport

    long = TechReport(width=1080, height=1920, fps=30, duration_s=200.0, video_kbps=None, has_audio=False, lufs=None, true_peak=None)
    monkeypatch.setattr(analyze, "probe", lambda p, loudness=False: long)
    with pytest.raises(AnalysisError, match="at most 180"):
        analyze_clip(dance, tmp / "x.png")


# ---- the CLI --------------------------------------------------------------------------------------------------------


def run(*args: str):
    return CliRunner().invoke(app, ["source", "analyze", *args])


@pytest.fixture
def cli_store(monkeypatch):
    store = MemoryStore()
    monkeypatch.setattr(sources, "open_store", lambda: store)
    return store


@pytest.fixture
def cli_storage(monkeypatch, tmp_path):
    storage = LocalStorage(tmp_path / "store")
    monkeypatch.setattr(sources, "open_storage", lambda: storage)
    return storage


def test_cli_analyses_a_file_and_prints_json(cli_store, tmp_path, silent_dance):
    out = tmp_path / "sheet.png"
    r = run(str(silent_dance), "--out", str(out))
    assert r.exit_code == 0, r.output
    data = json.loads(r.stdout)
    assert data["best_window"]["start_s"] == 4.0 and data["contact_sheet"]["path"] == str(out) and out.is_file()
    assert data["source_id"] is None


def test_cli_analyses_a_stored_source_by_id_and_names_it(cli_store, cli_storage, tmp_path, silent_dance):
    cli_storage.upload("sources", "owner_inbox/x.mp4", silent_dance)
    s = cli_store.add_source(Source(kind=SourceKind.owner_inbox, url="owner_inbox/x.mp4", storage_path="owner_inbox/x.mp4", body=Body.biped, bodies=1, duration_s=14.0))
    out = tmp_path / "id.png"
    r = run(s.id, "--out", str(out))
    assert r.exit_code == 0, r.output
    data = json.loads(r.stdout)
    assert data["source_id"] == s.id and out.is_file() and data["best_window"]["end_s"] == 10.0


def test_cli_default_sheet_goes_to_renders_by_id(cli_store, cli_storage, tmp_path, silent_dance, monkeypatch):
    monkeypatch.setattr(sources, "RENDERS_DIR", tmp_path / "renders")
    r = run(str(silent_dance))
    assert r.exit_code == 0, r.output
    assert json.loads(r.stdout)["contact_sheet"]["path"] == str(tmp_path / "renders" / "silent" / "analysis.png")  # <file stem>


def test_cli_exit_codes(cli_store, cli_storage, tmp_path, silent_dance):
    assert run(str(tmp_path / "nope.mp4")).exit_code == 2  # no such file, and not a source id either
    assert run("00000000-0000-4000-8000-000000000000").exit_code == 2  # unknown source
    text = tmp_path / "t.mp4"
    text.write_text("not a video")
    bad = run(str(text), "--out", str(tmp_path / "t.png"))
    assert bad.exit_code == 2 and "error:" in bad.output
    library = cli_store.add_source(Source(kind=SourceKind.higgsfield_library, url="https://cdn.example/x.mp4", body=Body.biped, bodies=1, duration_s=8.0))
    r = run(library.id)
    assert r.exit_code == 2 and "not in Storage" in r.output and "file" in r.output  # a library source: pass its downloaded preview
    gone = cli_store.add_source(Source(kind=SourceKind.owner_inbox, url="owner_inbox/gone.mp4", storage_path="owner_inbox/gone.mp4", body=Body.biped, bodies=1, duration_s=8.0))
    assert run(gone.id).exit_code == 2  # the object is not in Storage
    assert run(str(silent_dance), "--out", str(tmp_path / "x.gif")).exit_code == 2
