"""``studio.media.clipwork``: trim a source to its best window, and put a source's audio back under a Genjutsu output.

Owner decisions 2026-10-05: Genjutsu is paid per second, so only the best 6-9 s window of a source is sent; and a
Drop-in keeps the original clip audio by default, so when the Genjutsu output comes back without it, the source's
audio is muxed in again, aligned to the trimmed window. Real ffmpeg on tiny synthetic clips.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from studio.cli import app
from studio.media import clipwork
from studio.media.clipwork import ClipworkError, mux_source_audio, trim_clip
from studio.media.qa import QAError, measure_loudness, probe


def ffmpeg(*args: str) -> None:
    proc = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y", *args],
        capture_output=True, text=True, stdin=subprocess.DEVNULL,
    )  # fmt: skip
    assert proc.returncode == 0, proc.stderr[-500:]


@pytest.fixture
def source(tmp_path) -> Path:
    """10 s, 270x480: the first 5 s of its audio are digital silence, the last 5 s a 440 Hz tone."""
    out = tmp_path / "source.mp4"
    ffmpeg(
        "-f", "lavfi", "-i", "testsrc2=size=270x480:rate=30:duration=10",
        "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=5",
        "-filter_complex", "[1:a]atrim=0:5,asetpts=PTS-STARTPTS[s];[2:a]aformat=channel_layouts=stereo[t];[s][t]concat=n=2:v=0:a=1[a]",
        "-map", "0:v", "-map", "[a]", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-ar", "48000", "-t", "10", str(out),
    )  # fmt: skip
    return out


@pytest.fixture
def silent_source(tmp_path) -> Path:
    out = tmp_path / "no_audio.mp4"
    ffmpeg("-f", "lavfi", "-i", "testsrc2=size=270x480:rate=30:duration=10", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-an", str(out))
    return out


def lufs_between(video: Path, t0: float, t1: float, tmp: Path) -> float | None:
    """Integrated loudness of the audio between t0 and t1 seconds (None / <= -60: silence)."""
    wav = tmp / f"slice_{t0:g}_{t1:g}.wav"
    ffmpeg("-ss", f"{t0:g}", "-t", f"{t1 - t0:g}", "-i", str(video), "-vn", "-c:a", "pcm_s16le", str(wav))
    return measure_loudness(wav)[0]


# ---- trim_clip ----------------------------------------------------------------------------------------------------


def test_trim_keeps_the_picture_window_and_the_audio_of_that_window(tmp_path, source):
    out = trim_clip(source, tmp_path / "trimmed.mp4", 5.0, 4.0)
    report = probe(out)
    assert out.is_file() and report.duration_s == pytest.approx(4.0, abs=0.25)
    assert report.has_audio and report.lufs is not None and report.lufs > -40  # the tone half, not the silent half
    silent = probe(trim_clip(source, tmp_path / "first.mp4", 0.0, 4.0))
    assert silent.has_audio and silent.lufs is not None and silent.lufs <= -60


def test_trim_can_drop_the_audio(tmp_path, source):
    assert not probe(trim_clip(source, tmp_path / "mute.mp4", 1.0, 3.0, keep_audio=False)).has_audio


def test_trim_works_on_a_clip_with_no_audio(tmp_path, silent_source):
    report = probe(trim_clip(silent_source, tmp_path / "t.mp4", 1.0, 3.0))
    assert report.duration_s == pytest.approx(3.0, abs=0.25) and not report.has_audio


@pytest.mark.parametrize(
    ("start", "duration", "message"),
    [(0, 0, "duration"), (0, -1, "duration"), (-1, 3, "start"), (0, 16.5, "at most 16"), (12, 3, "ends at"), (8, 4, "ends at"), (float("nan"), 3, "start")],
)
def test_trim_refuses_a_window_that_makes_no_sense(tmp_path, source, start, duration, message):
    with pytest.raises(ValueError, match=message):
        trim_clip(source, tmp_path / "t.mp4", start, duration)
    assert not (tmp_path / "t.mp4").exists()


@pytest.fixture
def landscape_source(tmp_path) -> Path:
    """A 640x360 landscape clip with a tone: what an iconic YouTube source usually looks like."""
    out = tmp_path / "landscape.mp4"
    ffmpeg(
        "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=30:duration=6",
        "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=6",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(out),
    )  # fmt: skip
    return out


def test_trim_can_cut_a_vertical_9_16_window_out_of_a_landscape_clip(tmp_path, landscape_source):
    # owner 2026-10-05: iconic clips are often landscape; a 9:16 window around the star keeps the clip and its sound
    out = trim_clip(landscape_source, tmp_path / "v.mp4", 1.0, 3.0, crop_x=0.5)
    report = probe(out)
    assert (report.width, report.height) == (202, 360)  # 360 x 9/16 = 202.5, rounded down to an even width
    assert report.has_audio and report.duration_s == pytest.approx(3.0, abs=0.25)


@pytest.mark.parametrize("crop_x", [0.0, 1.0, 0.1, 0.95])
def test_a_crop_window_near_an_edge_is_clamped_inside_the_frame(tmp_path, landscape_source, crop_x):
    report = probe(trim_clip(landscape_source, tmp_path / "v.mp4", 0.0, 2.0, crop_x=crop_x))
    assert (report.width, report.height) == (202, 360)


def test_crop_offsets_follow_the_centre_and_stay_even():
    assert clipwork.crop_window(640, 360, 0.5) == (202, 360, 218)
    assert clipwork.crop_window(640, 360, 0.0) == (202, 360, 0)
    assert clipwork.crop_window(640, 360, 1.0) == (202, 360, 438)
    assert clipwork.crop_window(1920, 1080, 0.5) == (606, 1080, 656)


@pytest.mark.parametrize(("crop_x", "message"), [(-0.1, "between 0 and 1"), (1.5, "between 0 and 1"), (float("nan"), "crop_x")])
def test_trim_refuses_a_crop_centre_outside_the_frame(tmp_path, landscape_source, crop_x, message):
    with pytest.raises(ValueError, match=message):
        trim_clip(landscape_source, tmp_path / "v.mp4", 0.0, 2.0, crop_x=crop_x)


def test_trim_refuses_to_crop_a_clip_that_is_already_vertical(tmp_path, source):
    with pytest.raises(ValueError, match="already 9:16 or narrower"):
        trim_clip(source, tmp_path / "v.mp4", 0.0, 2.0, crop_x=0.5)


def test_trim_of_a_missing_or_unreadable_file_is_a_qa_error(tmp_path):
    with pytest.raises(QAError):
        trim_clip(tmp_path / "nope.mp4", tmp_path / "t.mp4", 0, 3)
    junk = tmp_path / "junk.mp4"
    junk.write_text("not a video")
    with pytest.raises(QAError):
        trim_clip(junk, tmp_path / "t.mp4", 0, 3)


# ---- mux_source_audio ---------------------------------------------------------------------------------------------


@pytest.fixture
def genjutsu_output(tmp_path) -> Path:
    """What a Genjutsu replace returns when it lost the soundtrack: 5 s of picture, no audio stream."""
    out = tmp_path / "gen.mp4"
    ffmpeg("-f", "lavfi", "-i", "testsrc2=size=270x480:rate=30:duration=5", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-an", str(out))
    return out


def test_mux_puts_the_source_audio_of_the_trimmed_window_under_the_picture(tmp_path, source, genjutsu_output):
    out = mux_source_audio(genjutsu_output, source, tmp_path / "gen_audio.mp4", 5.0)  # the window 5-10 s: all tone
    report = probe(out)
    assert report.has_audio and report.audio_codec == "aac" and report.lufs is not None and report.lufs > -40
    assert report.video_codec == "h264" and report.duration_s == pytest.approx(5.0, abs=0.25)  # the picture is untouched


def test_mux_aligns_the_audio_to_the_start_of_the_window(tmp_path, source, genjutsu_output):
    """Window 3-8 s: two silent seconds, then the tone: the tone must start about 2 s into the output."""
    out = mux_source_audio(genjutsu_output, source, tmp_path / "aligned.mp4", 3.0)
    early, late = lufs_between(out, 0.0, 1.5, tmp_path), lufs_between(out, 2.5, 4.5, tmp_path)
    assert early is None or early <= -60
    assert late is not None and late > -40
    silent = mux_source_audio(genjutsu_output, source, tmp_path / "silent.mp4", 0.0)  # window 0-5 s: silence only
    assert probe(silent).lufs is not None and probe(silent).lufs <= -60


def test_mux_refuses_a_source_without_audio_or_a_window_past_its_end(tmp_path, silent_source, source, genjutsu_output):
    with pytest.raises(ValueError, match="no audio"):
        mux_source_audio(genjutsu_output, silent_source, tmp_path / "x.mp4", 0.0)
    with pytest.raises(ValueError, match="ends at"):
        mux_source_audio(genjutsu_output, source, tmp_path / "x.mp4", 7.0)  # 7 + 5 s is past the 10 s source
    with pytest.raises(ValueError, match="start"):
        mux_source_audio(genjutsu_output, source, tmp_path / "x.mp4", -1.0)
    assert not (tmp_path / "x.mp4").exists()


def test_mux_replaces_an_existing_audio_track_and_never_doubles_it(tmp_path, source):
    """A Genjutsu output that kept its audio needs no mux, but muxing it again replaces the track, never doubles it."""
    out = mux_source_audio(source, source, tmp_path / "again.mp4", 0.0)
    streams = json.loads(subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "stream=codec_type", "-of", "json", str(out)], capture_output=True, text=True,
    ).stdout)["streams"]
    assert sorted(s["codec_type"] for s in streams) == ["audio", "video"]


def test_a_failing_ffmpeg_is_a_clipwork_error_with_its_message(tmp_path, source, monkeypatch):
    monkeypatch.setattr(clipwork, "_FFMPEG", "false")  # a binary that exits 1
    with pytest.raises(ClipworkError, match="ffmpeg failed"):
        trim_clip(source, tmp_path / "t.mp4", 0, 3)


# ---- the CLI ------------------------------------------------------------------------------------------------------


def test_cli_master_mux_audio_prints_the_result(tmp_path, source, genjutsu_output):
    r = CliRunner().invoke(app, ["master", "mux-audio", str(genjutsu_output), str(source), "--start", "5", "--out", str(tmp_path / "m.mp4")])
    assert r.exit_code == 0, r.output
    out = json.loads(r.stdout)
    assert out["out"] == str(tmp_path / "m.mp4") and out["has_audio"] is True and out["duration_s"] == pytest.approx(5.0, abs=0.25)
    assert out["lufs"] > -40


def test_cli_master_mux_audio_exit_codes(tmp_path, silent_source, genjutsu_output):
    run = lambda *a: CliRunner().invoke(app, ["master", "mux-audio", *a])  # noqa: E731
    assert run(str(genjutsu_output), str(silent_source), "--start", "0", "--out", str(tmp_path / "m.mp4")).exit_code == 2  # no audio
    assert run(str(tmp_path / "nope.mp4"), str(silent_source), "--start", "0", "--out", str(tmp_path / "m.mp4")).exit_code == 2
    assert run(str(genjutsu_output), str(silent_source), "--out", str(tmp_path / "m.mp4")).exit_code == 2  # --start is required
