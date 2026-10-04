import dataclasses
import json
import re
import subprocess
from pathlib import Path

import pytest
from PIL import Image, ImageStat
from typer.testing import CliRunner

from studio.cli import app
from studio.media import qa
from studio.media.qa import (
    QAError,
    TechReport,
    check_master,
    check_source,
    frame_sheet,
    frame_times,
    probe,
)

# ---- helpers -----------------------------------------------------------------------------------


def keys(problems: list[str]) -> list[str]:
    """Problems read ``<key>: <detail>``; the key is what callers match on."""
    return [p.split(":", 1)[0] for p in problems]


def good_report(**over) -> TechReport:
    """A hand-built report that meets the master spec (no ffmpeg needed)."""
    base = dict(
        width=1080,
        height=1920,
        fps=30.0,
        duration_s=10.0,
        video_kbps=15000.0,
        has_audio=True,
        lufs=-14.0,
        true_peak=-3.0,
        video_codec="h264",
        video_profile="High",
        audio_codec="aac",
        audio_hz=48000,
    )
    base.update(over)
    return TechReport(**base)


def ffmpeg(*args: str) -> None:
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y", *args],
        check=True,
        capture_output=True,
    )


def tile_means(sheet: Path, n: int) -> list[float]:
    """Mean luma of each of the n equal-width tiles of a sheet."""
    img = Image.open(sheet).convert("L")
    w, h = img.size
    tw = w // n
    return [ImageStat.Stat(img.crop((i * tw, 0, (i + 1) * tw, h))).mean[0] for i in range(n)]


# ---- the brief's five --------------------------------------------------------------------------


def test_good_master_passes(synth_video):
    report = probe(synth_video())  # 1080x1920 / 30 fps / 10 s, audio normalised to -14 LUFS
    assert check_master(report) == []
    assert (report.width, report.height) == (1080, 1920)
    assert report.fps == pytest.approx(30.0)
    assert report.duration_s == pytest.approx(10.0, abs=0.1)
    assert 10_000 <= report.video_kbps <= 20_000
    assert report.has_audio
    assert report.lufs == pytest.approx(-14.0, abs=0.5)
    assert report.true_peak is not None and report.true_peak <= -1.0


def test_low_res_fails(synth_video):
    problems = check_master(probe(synth_video(w=720, h=1280)))
    assert "resolution" in keys(problems)
    assert any("720x1280" in p for p in problems)


def test_silent_fails(synth_video):
    report = probe(synth_video(audio=False))
    assert not report.has_audio and report.lufs is None and report.true_peak is None
    # Exactly one complaint: no loudness / peak noise on top of the missing track.
    assert keys(check_master(report)) == ["audio"]


def test_too_long_fails(synth_video, tmp_path):
    twenty = tmp_path / "twenty.mp4"  # the 10 s master played twice: 20 s, same streams
    ffmpeg("-stream_loop", "1", "-i", str(synth_video()), "-c", "copy", "-t", "20", str(twenty))
    problems = check_master(probe(twenty))
    assert keys(problems) == ["duration"]
    assert "20.0" in problems[0]


def test_frame_sheet_has_n_frames(synth_video, tmp_path):
    out = tmp_path / "sheet.jpg"
    assert frame_sheet(synth_video(), n=6, out=out) == out
    with Image.open(out) as img:
        assert img.format == "JPEG"
        assert img.size == (6 * 270, 480)  # 1080x1920 scaled to 270 wide


# ---- TechReport --------------------------------------------------------------------------------


def test_ok_follows_problems():
    assert good_report().ok
    assert not dataclasses.replace(good_report(), problems=["fps: 25"]).ok


def test_brief_field_order_is_positional():
    r = TechReport(1080, 1920, 30.0, 10.0, 15000.0, True, -14.0, -3.0, ["x"])
    assert (r.width, r.height, r.fps, r.duration_s, r.video_kbps) == (1080, 1920, 30.0, 10.0, 15000.0)
    assert (r.has_audio, r.lufs, r.true_peak, r.problems) == (True, -14.0, -3.0, ["x"])
    assert TechReport(1, 2, 3.0, 4.0, None, False, None, None).problems == []


def test_problems_default_is_not_shared():
    a, b = good_report(), good_report()
    a.problems.append("x")
    assert b.problems == []


# ---- check_master: the Global Constraints, boundary by boundary --------------------------------


def test_good_report_has_no_problems():
    assert check_master(good_report()) == []


@pytest.mark.parametrize(
    "width,height",
    [(1080, 1919), (1079, 1920), (1920, 1080), (720, 1280), (2160, 3840)],
)
def test_only_exactly_1080x1920_passes(width, height):
    assert keys(check_master(good_report(width=width, height=height))) == ["resolution"]


@pytest.mark.parametrize("fps", [24.0, 25.0, 29.97, 60.0])
def test_fps_must_be_30(fps):
    assert keys(check_master(good_report(fps=fps))) == ["fps"]


def test_fps_float_noise_is_tolerated():
    assert check_master(good_report(fps=30.004)) == []


@pytest.mark.parametrize(
    "seconds,ok",
    [(7.0, True), (10.5, True), (16.0, True), (6.9, False), (16.1, False), (25.0, False), (0.0, False)],
)
def test_master_duration_7_to_16(seconds, ok):
    problems = check_master(good_report(duration_s=seconds))
    assert (problems == []) is ok
    assert ok or keys(problems) == ["duration"]


@pytest.mark.parametrize(
    "seconds,ok",
    [(6.0, True), (7.0, True), (8.0, True), (5.9, False), (8.1, False), (10.0, False)],
)
def test_eye_loop_duration_6_to_8(seconds, ok):
    problems = check_master(good_report(duration_s=seconds), loop=True)
    assert (problems == []) is ok
    assert ok or keys(problems) == ["duration"]


def test_loop_flag_is_a_replacement_range_not_an_extension():
    # 6.5 s is a fine loop but too short for a normal master; 10 s the other way round.
    assert keys(check_master(good_report(duration_s=6.5))) == ["duration"]
    assert check_master(good_report(duration_s=6.5), loop=True) == []
    assert check_master(good_report(duration_s=10.0)) == []
    assert keys(check_master(good_report(duration_s=10.0), loop=True)) == ["duration"]


def test_duration_allows_encoder_padding_of_a_frame_or_two():
    # AAC priming / container rounding: 7 s of video often reads 6.99x or 7.02x.
    assert check_master(good_report(duration_s=6.97)) == []
    assert check_master(good_report(duration_s=16.03)) == []
    assert keys(check_master(good_report(duration_s=6.93))) == ["duration"]
    assert keys(check_master(good_report(duration_s=16.07))) == ["duration"]


@pytest.mark.parametrize(
    "kbps,ok",
    [(10_000.0, True), (15_000.0, True), (20_000.0, True), (9_999.0, False), (20_001.0, False), (4_000.0, False)],
)
def test_video_bitrate_10_to_20_mbps(kbps, ok):
    problems = check_master(good_report(video_kbps=kbps))
    assert (problems == []) is ok
    assert ok or keys(problems) == ["bitrate"]


def test_unknown_video_bitrate_is_a_problem():
    problems = check_master(good_report(video_kbps=None))
    assert keys(problems) == ["bitrate"] and "unknown" in problems[0]


def test_video_must_be_h264_high():
    assert keys(check_master(good_report(video_codec="hevc", video_profile="Main"))) == ["codec"]
    for profile in ("Main", "Constrained Baseline", "High 10", "High 4:2:2"):
        problems = check_master(good_report(video_profile=profile))
        assert keys(problems) == ["codec"] and profile in problems[0]


def test_a_non_h264_codec_is_named_whatever_its_profile():
    problems = check_master(good_report(video_codec="vp9", video_profile=None))
    assert keys(problems) == ["codec"] and "vp9" in problems[0]
    problems = check_master(good_report(video_codec="hevc", video_profile="High"))
    assert keys(problems) == ["codec"] and "hevc" in problems[0]


def test_unknown_codec_fields_are_not_judged():
    # A hand-built report without codec facts is judged on the numbers it has.
    r = good_report(video_codec=None, video_profile=None, audio_codec=None, audio_hz=None)
    assert check_master(r) == []


def test_no_audio_stream_is_one_problem_and_skips_loudness():
    r = good_report(has_audio=False, lufs=None, true_peak=None, audio_codec=None, audio_hz=None)
    assert keys(check_master(r)) == ["audio"]


def test_audio_must_be_aac_48k():
    assert keys(check_master(good_report(audio_codec="mp3"))) == ["audio_format"]
    assert keys(check_master(good_report(audio_hz=44100))) == ["audio_format"]
    problems = check_master(good_report(audio_codec="mp3", audio_hz=44100))
    assert keys(problems) == ["audio_format"] and "mp3" in problems[0] and "44100" in problems[0]


@pytest.mark.parametrize(
    "lufs,ok",
    [(-14.0, True), (-13.0, True), (-15.0, True), (-12.9, False), (-15.1, False), (-23.0, False), (-70.0, False)],
)
def test_loudness_minus_14_plus_minus_1(lufs, ok):
    problems = check_master(good_report(lufs=lufs))
    assert (problems == []) is ok
    assert ok or keys(problems) == ["loudness"]


def test_loudness_not_measured_is_a_problem():
    problems = check_master(good_report(lufs=None, true_peak=None))
    assert keys(problems) == ["loudness"] and "not measured" in problems[0]


@pytest.mark.parametrize("peak,ok", [(-1.0, True), (-1.5, True), (-20.0, True), (-0.9, False), (0.0, False), (1.2, False)])
def test_true_peak_at_most_minus_1(peak, ok):
    problems = check_master(good_report(true_peak=peak))
    assert (problems == []) is ok
    assert ok or keys(problems) == ["peak"]


def test_silent_signal_has_no_peak_to_judge():
    # -inf dBFS is stored as None: the loudness (-70) already fails, the peak adds nothing.
    assert keys(check_master(good_report(lufs=-70.0, true_peak=None))) == ["loudness"]


def test_problems_accumulate_in_a_stable_order():
    r = good_report(
        width=720, height=1280, fps=25.0, duration_s=30.0, video_kbps=2000.0,
        video_profile="Main", audio_codec="mp3", lufs=-23.0, true_peak=0.5,
    )  # fmt: skip
    assert keys(check_master(r)) == [
        "resolution", "fps", "duration", "bitrate", "codec", "audio_format", "loudness", "peak",
    ]  # fmt: skip


def test_check_does_not_mutate_the_report():
    r = good_report(fps=25.0)
    check_master(r)
    assert r.problems == []


# ---- check_source ------------------------------------------------------------------------------


def source_report(**over) -> TechReport:
    base = dict(width=720, height=1280, fps=24.0, duration_s=10.0, video_kbps=4000.0, has_audio=False)
    base.update(over)
    return TechReport(lufs=None, true_peak=None, **base)


def test_source_needs_no_audio_no_bitrate_no_loudness():
    assert check_source(source_report()) == []
    assert check_source(source_report(video_kbps=None)) == []


@pytest.mark.parametrize("width,ok", [(480, True), (1080, True), (479, False), (270, False)])
def test_source_at_least_480_wide(width, ok):
    problems = check_source(source_report(width=width))
    assert (problems == []) is ok
    assert ok or keys(problems) == ["resolution"]


def test_source_width_not_height_decides():
    assert check_source(source_report(width=1920, height=1080)) == []


@pytest.mark.parametrize("seconds,ok", [(4.0, True), (30.0, True), (3.9, False), (30.1, False), (60.0, False)])
def test_source_duration_4_to_30(seconds, ok):
    problems = check_source(source_report(duration_s=seconds))
    assert (problems == []) is ok
    assert ok or keys(problems) == ["duration"]


@pytest.mark.parametrize("fps,ok", [(23.0, True), (23.976, True), (30.0, True), (60.0, True), (22.5, False), (60.5, False), (15.0, False)])
def test_source_fps_23_to_60(fps, ok):
    problems = check_source(source_report(fps=fps))
    assert (problems == []) is ok
    assert ok or keys(problems) == ["fps"]


def test_source_problems_accumulate():
    r = source_report(width=320, duration_s=2.0, fps=12.0)
    assert keys(check_source(r)) == ["resolution", "duration", "fps"]


# ---- probe -------------------------------------------------------------------------------------


def test_probe_reports_the_stream_facts(synth_video):
    r = probe(synth_video(w=270, h=480, fps=24, dur=3))
    assert (r.width, r.height) == (270, 480)
    assert r.fps == pytest.approx(24.0)
    assert r.duration_s == pytest.approx(3.0, abs=0.1)
    assert r.has_audio
    assert (r.video_codec, r.video_profile) == ("h264", "High")
    assert (r.audio_codec, r.audio_hz) == ("aac", 48000)
    assert r.video_kbps is not None and r.video_kbps > 1000
    assert r.problems == []  # probe measures, the check_* functions judge


@pytest.mark.parametrize(
    "avg,nominal,expected",
    [
        ("30/1", "30/1", 30.0),
        ("1152000/38441", "30/1", 30.0),  # 29.97 average from container padding: still a 30 fps clip
        ("24/1", "30/1", 24.0),  # variable rate: the true average wins
        ("30000/1001", "30000/1001", 30000 / 1001),
        ("0/0", "25/1", 25.0),
        ("25/1", "0/0", 25.0),
        ("0/0", "0/0", 0.0),
        ("N/A", None, 0.0),
    ],
)
def test_fps_reading(avg, nominal, expected):
    stream = {"avg_frame_rate": avg, "r_frame_rate": nominal}
    assert qa._fps(stream) == pytest.approx(expected)


def test_video_bitrate_prefers_the_streams_own_figure():
    video = {"bit_rate": "14000000", "tags": {"BPS": "13000000"}}
    audio = {"bit_rate": "320000"}
    data = {"format": {"bit_rate": "15000000"}}
    assert qa._video_kbps(data, video, audio) == pytest.approx(14000.0)
    assert qa._video_kbps(data, {"tags": {"BPS": "13000000"}}, audio) == pytest.approx(13000.0)  # mkv tag
    assert qa._video_kbps(data, {}, audio) == pytest.approx(14680.0)  # container total minus audio
    assert qa._video_kbps(data, {}, None) == pytest.approx(15000.0)
    assert qa._video_kbps({"format": {"bit_rate": "N/A"}}, {"bit_rate": "N/A"}, audio) is None
    assert qa._video_kbps({}, {}, None) is None


def test_probe_without_audio(synth_video):
    r = probe(synth_video(w=270, h=480, dur=3, audio=False))
    assert not r.has_audio
    assert (r.lufs, r.true_peak, r.audio_codec, r.audio_hz) == (None, None, None, None)


def test_probe_can_skip_the_loudness_pass(synth_video):
    r = probe(synth_video(w=270, h=480, dur=3), loudness=False)
    assert r.has_audio and r.lufs is None and r.true_peak is None


def test_probe_measures_the_requested_loudness(synth_video):
    for lufs in (-23.0, -14.0):
        r = probe(synth_video(w=270, h=480, dur=3, lufs=lufs))
        assert r.lufs == pytest.approx(lufs, abs=0.3)
        assert r.true_peak == pytest.approx(lufs, abs=1.0)  # a sine: peak sits at its level


def test_quiet_audio_fails_loudness_but_not_peak(synth_video):
    problems = check_master(probe(synth_video(w=270, h=480, dur=3, lufs=-23.0)))
    assert "loudness" in keys(problems) and "peak" not in keys(problems)
    assert any("-23.0" in p for p in problems)


def test_hot_master_fails_peak_and_loudness(synth_video):
    r = probe(synth_video(w=270, h=480, dur=3, lufs=-0.4))
    assert r.true_peak is not None and r.true_peak > -1.0
    problems = check_master(r)
    assert "peak" in keys(problems) and "loudness" in keys(problems)


def test_digital_silence_track_is_present_but_fails_loudness(tmp_path):
    out = tmp_path / "silent_track.mp4"
    ffmpeg(
        "-f", "lavfi", "-i", "testsrc2=size=270x480:rate=30:duration=3",
        "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-t", "3", str(out),
    )  # fmt: skip
    r = probe(out)
    assert r.has_audio
    assert r.lufs is not None and r.lufs <= -60
    assert r.true_peak is None  # -inf dBFS has no JSON form: stored as None
    assert "loudness" in keys(check_master(r))
    assert "peak" not in keys(check_master(r))


SUMMARY = """\
[Parsed_ebur128_0 @ 0x1] Summary:

  Integrated loudness:
    I:         {i} LUFS
    Threshold: -24.0 LUFS

  Loudness range:
    LRA:         0.0 LU

  True peak:
    Peak:      {peak} dBFS
"""


def canned(stderr: str, code: int = 0):
    return lambda cmd, **kw: subprocess.CompletedProcess(cmd, code, "", stderr)


def test_measure_loudness_reads_the_summary_not_the_frame_lines(monkeypatch):
    frame_lines = "t: 0.1  M: -70.0 S: -70.0  I: -70.0 LUFS  LRA: 0.0 LU  TPK: -70.0 -70.0 dBFS\n" * 3
    monkeypatch.setattr(qa, "_run", canned(frame_lines + SUMMARY.format(i="-13.6", peak="-2.4")))
    assert qa.measure_loudness(Path("x.mp4")) == (-13.6, -2.4)


def test_measure_loudness_maps_minus_inf_to_none(monkeypatch):
    monkeypatch.setattr(qa, "_run", canned(SUMMARY.format(i="-inf", peak="-inf")))
    assert qa.measure_loudness(Path("x.mp4")) == (None, None)


def test_measure_loudness_ffmpeg_failure(monkeypatch):
    monkeypatch.setattr(qa, "_run", canned("Invalid data found", code=1))
    with pytest.raises(QAError, match="could not measure.*Invalid data"):
        qa.measure_loudness(Path("x.mp4"))


def test_measure_loudness_without_summary(monkeypatch):
    monkeypatch.setattr(qa, "_run", canned("size=N/A time=00:00:10.00"))
    with pytest.raises(QAError, match="no summary"):
        qa.measure_loudness(Path("x.mp4"))


def test_measure_loudness_unparseable_summary(monkeypatch):
    monkeypatch.setattr(qa, "_run", canned("Summary:\n  nothing useful here\n"))
    with pytest.raises(QAError, match="could not parse"):
        qa.measure_loudness(Path("x.mp4"))


def test_probe_swaps_width_and_height_for_rotated_video(synth_video, tmp_path):
    src = synth_video(w=270, h=480, dur=3, audio=False)
    out = tmp_path / "rotated.mp4"
    try:
        ffmpeg("-display_rotation", "90", "-i", str(src), "-c", "copy", str(out))
    except subprocess.CalledProcessError:
        pytest.skip("this ffmpeg has no -display_rotation input option")
    report = probe(out)
    assert (report.width, report.height) == (480, 270)


def test_probe_bitrate_survives_a_container_without_stream_bitrate(synth_video, tmp_path):
    src = synth_video(w=270, h=480, dur=3, audio=False)
    mkv = tmp_path / "copy.mkv"
    ffmpeg("-i", str(src), "-c", "copy", str(mkv))
    original, copy = probe(src).video_kbps, probe(mkv).video_kbps
    assert copy is not None and copy == pytest.approx(original, rel=0.25)


def test_probe_is_independent_of_the_cwd(synth_video, tmp_path, monkeypatch):
    src = synth_video(w=270, h=480, dur=3, audio=False)
    monkeypatch.chdir(tmp_path)
    assert probe(src).width == 270


def test_probe_missing_file():
    with pytest.raises(QAError, match="no such file"):
        probe(Path("/nonexistent/clip.mp4"))


def test_probe_not_a_media_file(tmp_path):
    junk = tmp_path / "notes.mp4"
    junk.write_text("definitely not a video")
    with pytest.raises(QAError, match="could not read"):
        probe(junk)


def test_probe_cover_art_is_not_a_video_stream(tmp_path):
    m4a = tmp_path / "with_cover.m4a"
    ffmpeg(
        "-f", "lavfi", "-i", "sine=duration=1", "-f", "lavfi", "-i", "testsrc2=size=64x64:rate=1:duration=1",
        "-map", "0:a", "-map", "1:v", "-c:a", "aac", "-c:v", "mjpeg", "-frames:v", "1",
        "-disposition:v:0", "attached_pic", str(m4a),
    )  # fmt: skip
    with pytest.raises(QAError, match="no video stream"):
        probe(m4a)


def test_probe_audio_only_file_has_no_video(tmp_path):
    wav = tmp_path / "tone.wav"
    ffmpeg("-f", "lavfi", "-i", "sine=duration=1", str(wav))
    with pytest.raises(QAError, match="no video stream"):
        probe(wav)


def test_ffmpeg_missing_is_a_clear_error(monkeypatch, tmp_path):
    monkeypatch.setenv("PATH", str(tmp_path))
    f = tmp_path / "x.mp4"
    f.write_bytes(b"")
    with pytest.raises(QAError, match="ffprobe not found"):
        probe(f)


# ---- frame sheets ------------------------------------------------------------------------------


def test_frame_times_are_evenly_spaced_and_inside_the_clip():
    times = frame_times(10.0, 6, fps=30)
    assert len(times) == 6 and times[0] == 0.0
    assert times[-1] == pytest.approx(10.0 - 1.5 / 30)
    steps = [b - a for a, b in zip(times, times[1:], strict=False)]
    assert max(steps) - min(steps) < 1e-9


def test_frame_times_single_frame_is_the_middle():
    assert frame_times(8.0, 1) == [pytest.approx((8.0 - 1.5 / 30) / 2)]


def test_frame_times_for_a_clip_shorter_than_the_margin():
    assert frame_times(0.02, 3) == [0.0, 0.0, 0.0]


def test_frame_sheet_portrait_geometry(synth_video, tmp_path):
    with Image.open(frame_sheet(synth_video(w=270, h=480, dur=3), n=4, out=tmp_path / "s.jpg")) as img:
        assert img.size == (4 * 270, 480)


def test_frame_sheet_landscape_keeps_the_aspect_ratio_with_even_height(synth_video, tmp_path):
    src = synth_video(w=640, h=360, dur=3, audio=False)
    with Image.open(frame_sheet(src, n=3, out=tmp_path / "s.jpg")) as img:
        assert img.size == (3 * 270, 152)  # 270 * 360/640 = 151.9 -> nearest even


def test_frame_sheet_single_frame(synth_video, tmp_path):
    with Image.open(frame_sheet(synth_video(w=270, h=480, dur=3), n=1, out=tmp_path / "s.jpg")) as img:
        assert img.size == (270, 480)


def test_frame_sheet_defaults_to_six_frames(synth_video, tmp_path):
    with Image.open(frame_sheet(synth_video(w=270, h=480, dur=3), out=tmp_path / "s.jpg")) as img:
        assert img.size[0] == 6 * 270


@pytest.fixture(scope="module")
def ramp_clip(tmp_path_factory) -> Path:
    """10 s, 160x90, luma = 16 + 20*t: a frame's brightness says when it was taken."""
    clip = tmp_path_factory.mktemp("ramp") / "ramp.mp4"
    ffmpeg(
        "-f", "lavfi", "-i", "color=c=black:s=160x90:r=10:d=10,format=yuv420p,geq=lum='16+20*T':cb=128:cr=128",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-t", "10", str(clip),
    )  # fmt: skip
    return clip


def test_frame_sheet_frames_come_from_evenly_spaced_moments(ramp_clip, tmp_path):
    means = tile_means(frame_sheet(ramp_clip, n=6, out=tmp_path / "ramp.jpg"), 6)
    steps = [b - a for a, b in zip(means, means[1:], strict=False)]
    assert means[0] < 12  # t = 0: black
    assert means[-1] > 200  # last frame: just before the end
    assert all(s > 0 for s in steps)
    assert max(steps) - min(steps) < 0.2 * (sum(steps) / len(steps))  # even spacing in time


def test_frame_sheet_single_frame_is_from_the_middle(ramp_clip, tmp_path):
    (mean,) = tile_means(frame_sheet(ramp_clip, n=1, out=tmp_path / "mid.jpg"), 1)
    assert 100 < mean < 135  # t ~ 5 s of 10


def test_frame_sheet_two_frames_are_the_first_and_the_last(ramp_clip, tmp_path):
    first, last = tile_means(frame_sheet(ramp_clip, n=2, out=tmp_path / "ends.jpg"), 2)
    assert first < 12 and last > 215


def test_frame_sheet_uses_the_video_length_when_the_audio_runs_longer(ramp_clip, tmp_path):
    long_audio = tmp_path / "long_audio.mp4"  # 10 s of video, 15 s of audio: the container says 15 s
    ffmpeg(
        "-i", str(ramp_clip), "-f", "lavfi", "-i", "sine=duration=15",
        "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-c:a", "aac", str(long_audio),
    )  # fmt: skip
    assert probe(long_audio, loudness=False).duration_s > 14
    means = tile_means(frame_sheet(long_audio, n=4, out=tmp_path / "s.jpg"), 4)
    assert means[0] < 12 and means[-1] > 200  # the last tile is the end of the picture, not blank padding


def test_frame_sheet_creates_missing_parent_directories(synth_video, tmp_path):
    out = tmp_path / "a" / "b" / "sheet.jpg"
    assert frame_sheet(synth_video(w=270, h=480, dur=3), n=2, out=out).is_file()


def test_frame_sheet_png_output(synth_video, tmp_path):
    with Image.open(frame_sheet(synth_video(w=270, h=480, dur=3), n=2, out=tmp_path / "s.png")) as img:
        assert img.format == "PNG" and img.size == (540, 480)


def test_frame_sheet_default_output_sits_next_to_the_video(synth_video, tmp_path):
    src = synth_video(tmp_path, w=270, h=480, dur=3)
    out = frame_sheet(src, n=2)
    assert out == tmp_path / f"{src.stem}.frames.jpg" and out.is_file()


def test_frame_sheet_overwrites_an_existing_file(synth_video, tmp_path):
    out = tmp_path / "s.jpg"
    out.write_bytes(b"stale")
    frame_sheet(synth_video(w=270, h=480, dur=3), n=2, out=out)
    with Image.open(out) as img:
        assert img.size == (540, 480)


@pytest.mark.parametrize("n", [0, -1, 25])
def test_frame_sheet_rejects_a_silly_frame_count(synth_video, tmp_path, n):
    with pytest.raises(ValueError, match="frames"):
        frame_sheet(synth_video(w=270, h=480, dur=3), n=n, out=tmp_path / "s.jpg")


def test_frame_sheet_rejects_an_unknown_image_extension(synth_video, tmp_path):
    with pytest.raises(ValueError, match="jpg"):
        frame_sheet(synth_video(w=270, h=480, dur=3), n=2, out=tmp_path / "s.gif")


def test_frame_sheet_missing_video(tmp_path):
    with pytest.raises(QAError, match="no such file"):
        frame_sheet(tmp_path / "nope.mp4", n=2, out=tmp_path / "s.jpg")


def test_frame_sheet_works_from_another_cwd(synth_video, tmp_path, monkeypatch):
    src = synth_video(w=270, h=480, dur=3)
    monkeypatch.chdir(tmp_path)
    assert frame_sheet(src, n=2, out=tmp_path / "x.jpg").is_file()


# ---- CLI ---------------------------------------------------------------------------------------


def run(*args: str):
    return CliRunner().invoke(app, ["qa", *args])


def test_cli_tech_master_ok(synth_video):
    r = run("tech", str(synth_video()), "--master")
    assert r.exit_code == 0, r.output
    body = json.loads(r.stdout, parse_constant=pytest.fail)  # strict JSON: no NaN / Infinity
    assert body["ok"] is True and body["problems"] == []
    assert body["checked"] == "master"
    assert (body["width"], body["height"]) == (1080, 1920)
    assert body["lufs"] == pytest.approx(-14.0, abs=0.5)


def test_cli_tech_master_problems_exit_1_with_json(synth_video):
    r = run("tech", str(synth_video(w=720, h=1280)), "--master")
    assert r.exit_code == 1
    body = json.loads(r.stdout)
    assert body["ok"] is False
    assert "resolution" in keys(body["problems"])


def test_cli_tech_silent_master_exit_1(synth_video):
    r = run("tech", str(synth_video(audio=False)), "--master")
    assert r.exit_code == 1
    assert keys(json.loads(r.stdout)["problems"]) == ["audio"]


def test_cli_tech_without_master_applies_the_source_check(synth_video):
    # 720x1280, 10 s, 30 fps, no loudness judgement: fine as a source, not as a master.
    clip = str(synth_video(w=720, h=1280, audio=False))
    r = run("tech", clip)
    assert r.exit_code == 0, r.output
    body = json.loads(r.stdout)
    assert body["checked"] == "source" and body["ok"] is True and body["lufs"] is None
    assert run("tech", clip, "--master").exit_code == 1


def test_cli_tech_source_problems_exit_1(synth_video):
    r = run("tech", str(synth_video(w=270, h=480, dur=3, audio=False)))
    assert r.exit_code == 1
    assert keys(json.loads(r.stdout)["problems"]) == ["resolution", "duration"]


def test_cli_tech_loop_changes_the_duration_range(monkeypatch):
    clip = good_report(duration_s=6.5)
    monkeypatch.setattr(qa, "probe", lambda path, *, loudness=True: clip)
    assert run("tech", "x.mp4", "--master", "--loop").exit_code == 0
    r = run("tech", "x.mp4", "--master")
    assert r.exit_code == 1 and keys(json.loads(r.stdout)["problems"]) == ["duration"]
    body = json.loads(run("tech", "x.mp4", "--master", "--loop").stdout)
    assert body["checked"] == "master (eye loop)"


def test_cli_tech_loop_needs_master():
    r = run("tech", "x.mp4", "--loop")
    assert r.exit_code == 2 and "--master" in r.output


def test_cli_tech_missing_file_exits_2():
    r = run("tech", "/nonexistent/clip.mp4", "--master")
    assert r.exit_code == 2 and r.output.startswith("error: ") and "no such file" in r.output


def test_cli_tech_unreadable_file_exits_2(tmp_path):
    junk = tmp_path / "junk.mp4"
    junk.write_text("nope")
    r = run("tech", str(junk))
    assert r.exit_code == 2 and "could not read" in r.output


def test_cli_frames_writes_the_sheet(synth_video, tmp_path):
    out = tmp_path / "sheets" / "clip.jpg"
    r = run("frames", str(synth_video()), "--out", str(out))
    assert r.exit_code == 0, r.output
    assert json.loads(r.stdout) == {"out": str(out), "frames": 6, "frame_width": 270, "sheet_width": 1620}
    with Image.open(out) as img:
        assert img.size == (1620, 480)


def test_cli_frames_n_option(synth_video, tmp_path):
    out = tmp_path / "clip.jpg"
    r = run("frames", str(synth_video(w=270, h=480, dur=3)), "--out", str(out), "--n", "3")
    assert r.exit_code == 0, r.output
    assert json.loads(r.stdout)["sheet_width"] == 810
    with Image.open(out) as img:
        assert img.size[0] == 810


def test_cli_frames_bad_n_exits_2(synth_video, tmp_path):
    r = run("frames", str(synth_video(w=270, h=480, dur=3)), "--out", str(tmp_path / "x.jpg"), "--n", "0")
    assert r.exit_code == 2 and "frames" in r.output


def test_cli_frames_missing_file_exits_2(tmp_path):
    r = run("frames", "/nonexistent/clip.mp4", "--out", str(tmp_path / "x.jpg"))
    assert r.exit_code == 2 and "no such file" in r.output


def test_cli_frames_requires_out(synth_video):
    assert run("frames", str(synth_video(w=270, h=480, dur=3))).exit_code == 2


def test_qa_group_is_registered_once_with_both_commands():
    r = CliRunner().invoke(app, ["--help"])
    assert r.exit_code == 0
    assert len(re.findall(r"^\W*qa\s", r.output, flags=re.MULTILINE)) == 1
    out = run("--help").output
    assert "tech" in out and "frames" in out
