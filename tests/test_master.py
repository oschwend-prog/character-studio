"""Overlays (PIL PNGs, synthesised audio) and the master timeline (ffmpeg).

Rendering tests use tiny clips and ``preset="veryfast"`` (the default ``slow`` is for real
masters); flat-colour sources make "is the text on screen?" a plain pixel count.
"""

from __future__ import annotations

import dataclasses
import json
import math
import subprocess
import wave
from pathlib import Path

import pytest
from PIL import Image, ImageChops, ImageStat
from typer.testing import CliRunner

from studio.cli import app
from studio.media import master, overlays
from studio.media.master import MasterSpec, build_master
from studio.media.qa import check_master, probe

# ---- helpers -----------------------------------------------------------------------------------


def ffmpeg(*args: str) -> None:
    proc = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y", *args],
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
    )
    assert proc.returncode == 0, proc.stderr[-600:]


def flat_video(path: Path, dur: float, colour: str = "0x203040") -> Path:
    """A 1080x1920@30 flat-colour clip: any white pixel in a frame of it is an overlay."""
    ffmpeg(
        "-f", "lavfi", "-i", f"color=c={colour}:s=1080x1920:r=30:d={dur:g}",
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(path),
    )  # fmt: skip
    return path


def flat_png(path: Path, colour=(24, 32, 44)) -> Path:
    Image.new("RGB", (1080, 1920), colour).save(path)
    return path


def tone(path: Path, dur: float, hz: int = 440, lead_s: float = 0.0) -> Path:
    """A stereo sine (peak 0.5) of ``dur`` s, preceded by ``lead_s`` s of silence."""
    ms = round(lead_s * 1000)
    chain = f"sine=frequency={hz}:sample_rate=48000:duration={dur:g},volume=4,pan=stereo|c0=c0|c1=c0"
    ffmpeg("-f", "lavfi", "-i", chain + (f",adelay={ms}|{ms}" if ms else ""), str(path))
    return path


def frame_at(video: Path, t: float, tmp: Path) -> Image.Image:
    out = tmp / f"frame_{t:g}.png"
    ffmpeg("-ss", f"{t:g}", "-i", str(video), "-frames:v", "1", str(out))
    return Image.open(out).convert("RGB")


def bright_pixels(img: Image.Image, box: tuple[int, int, int, int], floor: int = 225) -> int:
    """Pixels of ``box`` whose channels are all >= ``floor`` (white / ivory text)."""
    colours = img.crop(box).getcolors(maxcolors=1 << 24)
    return sum(count for count, px in colours if min(px) >= floor)


def spec_for(tmp_path: Path, dance: Path, audio: Path, **over) -> MasterSpec:
    base = dict(
        dance=dance,
        closeup=flat_png(tmp_path / "closeup.png"),
        closeup_center=(536, 732),
        blue_eye_xy=(301, 960),
        hook1=["my eyes don't match."],
        hook2=["my eyes don't match.", "my moves do."],
        hook2_until_s=1.8,
        audio=audio,
        audio_offset_s=0.2,
        out=tmp_path / "master.mp4",
        preset="veryfast",
    )
    base.update(over)
    return MasterSpec(**base)


def detailed_png(path: Path) -> Path:
    """A closeup with some texture (and two coloured 'eyes') so it is not a flat fill."""
    from PIL import ImageDraw

    img = Image.effect_noise((1080, 1920), 40).convert("RGB")
    d = ImageDraw.Draw(img)
    d.ellipse((250, 680, 450, 780), fill=(143, 211, 255))
    d.ellipse((630, 680, 830, 780), fill=(255, 176, 64))
    img.save(path)
    return path


# ---- overlays ----------------------------------------------------------------------------------


def test_hook_png_is_transparent_and_full_frame(tmp_path):
    png = overlays.hook_png(["my eyes don't match.", "my moves do."], tmp_path / "hook.png")
    img = Image.open(png)
    assert img.size == (1080, 1920) and img.mode == "RGBA"
    for corner in [(0, 0), (1079, 0), (0, 1919), (1079, 1919)]:
        assert img.getpixel(corner)[3] == 0
    alpha = img.getchannel("A")
    left, top, right, bottom = alpha.getbbox()
    assert top >= 340 and bottom < 700, "two lines drawn from y=350"
    assert left >= 0 and right <= 1080
    # White fill with a dark stroke: the text has opaque white pixels and opaque dark ones.
    colours = [c for _, c in img.getcolors(maxcolors=1 << 24)]
    assert any(c[3] == 255 and min(c[:3]) >= 250 for c in colours)
    assert any(c[3] == 255 and max(c[:3]) <= 50 for c in colours)


def test_hook_png_y_moves_the_text_and_wide_lines_are_shrunk_to_fit(tmp_path):
    low = overlays.hook_png(["hi"], tmp_path / "low.png", y=1000)
    assert Image.open(low).getchannel("A").getbbox()[1] >= 990
    wide = overlays.hook_png(["the quick brown fox jumps over the lazy dogs"], tmp_path / "w.png")
    left, _, right, _ = Image.open(wide).getchannel("A").getbbox()
    assert left >= 10 and right <= 1070, "an over-wide line is shrunk, never clipped"


def test_hook_png_rejects_empty_text(tmp_path):
    with pytest.raises(ValueError):
        overlays.hook_png([], tmp_path / "x.png")


def test_bug_png_is_two_odd_eyes_dots(tmp_path):
    img = Image.open(overlays.bug_png(tmp_path / "bug.png"))
    assert img.size == (1080, 1920)
    blue, orange = img.getpixel((952, 268)), img.getpixel((992, 268))
    # Premultiplied resampling may be one level off; the colours are #8FD3FF and #FFB040.
    assert all(abs(a - b) <= 2 for a, b in zip(blue[:3], (0x8F, 0xD3, 0xFF), strict=True)) and blue[3] > 200
    assert all(abs(a - b) <= 2 for a, b in zip(orange[:3], (0xFF, 0xB0, 0x40), strict=True)) and orange[3] > 200
    assert img.getpixel((972, 268))[3] == 0, "a gap between the dots"
    assert img.getpixel((0, 0))[3] == 0
    left, top, right, bottom = img.getchannel("A").getbbox()
    assert abs((left + right) / 2 - 972) <= 2 and abs((top + bottom) / 2 - 268) <= 2


def test_sparkle_png_is_a_star_with_a_glow(tmp_path):
    img = Image.open(overlays.sparkle_png(tmp_path / "s.png"))
    assert img.size == (320, 320) and img.mode == "RGBA"
    assert img.getpixel((160, 160))[3] == 255
    assert img.getpixel((14, 160))[3] > 0 and img.getpixel((160, 14))[3] > 0, "arms reach the tips"
    assert img.getpixel((0, 0))[3] == 0
    assert 0 < img.getpixel((190, 190))[3] < 255, "a soft glow between the arms"
    assert Image.open(overlays.sparkle_png(tmp_path / "s2.png", size=160)).size == (160, 160)


def read_wav(path: Path) -> tuple[list[int], int, int]:
    with wave.open(str(path)) as w:
        n, ch, rate = w.getnframes(), w.getnchannels(), w.getframerate()
        raw = w.readframes(n)
    samples = [int.from_bytes(raw[i : i + 2], "little", signed=True) for i in range(0, len(raw), 2 * ch)]
    return samples, ch, rate


def test_sting_length(tmp_path):
    samples, ch, rate = read_wav(overlays.sting_wav(tmp_path / "sting.wav"))
    assert abs(len(samples) / rate - 0.6) <= 0.01
    assert (ch, rate) == (2, 48000)
    peak = max(abs(s) for s in samples) / 32768
    assert 0.3 < peak < 0.95, "audible and not clipping"
    assert max(abs(s) for s in samples[-200:]) / 32768 < 0.02, "ends without a click"


def test_impact_wav_is_a_short_low_thump(tmp_path):
    samples, _, rate = read_wav(overlays.impact_wav(tmp_path / "hit.wav"))
    assert 0.25 <= len(samples) / rate <= 0.6
    head = samples[: rate // 20]
    crossings = sum(1 for a, b in zip(head, head[1:], strict=False) if (a < 0) != (b < 0))
    assert crossings * 10 < 400, "energy sits below ~200 Hz"
    assert max(abs(s) for s in samples) / 32768 > 0.5
    assert max(abs(s) for s in samples[-100:]) / 32768 < 0.02


def test_font_path_points_at_a_real_font():
    assert overlays.font_path().is_file()
    assert overlays.serif_font_path().is_file()


def test_font_path_uses_fc_match_off_macos(monkeypatch):
    monkeypatch.setattr(overlays.sys, "platform", "linux")
    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout=str(Path(overlays.__file__)), stderr="")

    monkeypatch.setattr(overlays.subprocess, "run", fake_run)
    assert overlays.font_path() == Path(overlays.__file__)
    assert calls == [["fc-match", "-f", "%{file}", "DejaVu Sans:bold"]]


def test_font_path_explains_a_missing_font(monkeypatch):
    monkeypatch.setattr(overlays.sys, "platform", "linux")

    def boom(cmd, **kw):
        raise FileNotFoundError("fc-match")

    monkeypatch.setattr(overlays.subprocess, "run", boom)
    with pytest.raises(overlays.OverlayError, match="fonts-dejavu-core"):
        overlays.font_path()


# ---- enhancements: parsing, time maths, filter fragments ---------------------------------------


def test_parse_enhancements_builds_typed_items():
    items = master.parse_enhancements(
        [
            {"type": "slowmo", "at_s": 2, "dur_s": 1, "factor": 0.5},
            {"type": "zoom_hit", "at_s": 3.0},
            {"type": "impact_sfx", "at_s": 3.0},
            {"type": "text_pop", "at_s": 4, "dur_s": 1, "text": "WAIT"},
            {"type": "title_card", "text": "Biscuit"},
        ]
    )
    assert items == [
        master.Slowmo(2, 1, 0.5),
        master.ZoomHit(3.0, 1.06),
        master.ImpactSfx(3.0),
        master.TextPop(4, 1, "WAIT"),
        master.TitleCard("Biscuit"),
    ]


@pytest.mark.parametrize(
    "bad, match",
    [
        ({"type": "wobble"}, "unknown enhancement"),
        ({"at_s": 1}, "type"),
        ({"type": "slowmo", "at_s": 1, "dur_s": 1}, "factor"),
        ({"type": "slowmo", "at_s": 1, "dur_s": 1, "factor": 1.5}, "factor"),
        ({"type": "slowmo", "at_s": 1, "dur_s": 1, "factor": 0}, "factor"),
        ({"type": "slowmo", "at_s": -1, "dur_s": 1, "factor": 0.5}, "at_s"),
        ({"type": "zoom_hit", "at_s": 1, "scale": 0.9}, "scale"),
        ({"type": "text_pop", "at_s": 1, "dur_s": 1, "text": " "}, "text"),
        ({"type": "text_pop", "at_s": 1, "dur_s": 0, "text": "x"}, "dur_s"),
        ({"type": "impact_sfx"}, "at_s"),
        ({"type": "title_card"}, "text"),
        ({"type": "zoom_hit", "at_s": 1, "colour": "red"}, "colour"),
    ],
)
def test_parse_enhancements_rejects_bad_items(bad, match):
    with pytest.raises(ValueError, match=match):
        master.parse_enhancements([bad])


def test_parse_enhancements_rejects_overlapping_slowmos():
    with pytest.raises(ValueError, match="overlap"):
        master.parse_enhancements(
            [
                {"type": "slowmo", "at_s": 1, "dur_s": 2, "factor": 0.5},
                {"type": "slowmo", "at_s": 2.5, "dur_s": 1, "factor": 0.5},
            ]
        )


def test_out_time_stretches_after_a_slowmo_span():
    spans = [master.Slowmo(2.0, 1.0, 0.5)]  # one extra second over the span
    assert master.out_time(1.0, spans) == 1.0
    assert master.out_time(2.0, spans) == 2.0
    assert master.out_time(2.5, spans) == pytest.approx(3.0)
    assert master.out_time(3.0, spans) == pytest.approx(4.0)
    assert master.out_time(5.0, spans) == pytest.approx(6.0)
    assert master.out_time(5.0, []) == 5.0


def test_slowmo_fragment_splits_stretches_and_rejoins():
    frag = master.slowmo_filter("v", "vs", [master.Slowmo(2.0, 1.0, 0.5)], total_s=10.0)
    assert frag.startswith("[v]split=3[sm0][sm1][sm2];")
    assert "[sm1]trim=start=2:end=3,setpts=(PTS-STARTPTS)/0.5[sw1]" in frag
    assert frag.endswith("[sw0][sw1][sw2]concat=n=3:v=1:a=0,fps=30[vs]")
    # A span touching the start or the end has no empty neighbour.
    edge = master.slowmo_filter("v", "vs", [master.Slowmo(0, 1.0, 0.5)], total_s=1.0)
    assert "split=1" not in edge and "concat" not in edge and "setpts=(PTS-STARTPTS)/0.5" in edge


def test_slowmo_must_fit_inside_the_clip():
    with pytest.raises(ValueError, match="runs past"):
        master.slowmo_filter("v", "vs", [master.Slowmo(9.5, 1.0, 0.5)], total_s=10.0)


def test_zoom_hit_fragment_only_scales_inside_its_window(tmp_path):
    """Frames outside the 0.25 s window are untouched; the middle of it is zoomed in."""
    src = tmp_path / "src.mp4"
    ffmpeg("-f", "lavfi", "-i", "testsrc2=size=1080x1920:rate=30:duration=1", "-c:v", "libx264",
           "-preset", "ultrafast", "-crf", "5", "-pix_fmt", "yuv420p", str(src))  # fmt: skip
    out = tmp_path / "zoomed.mp4"
    frag = master.zoom_hit_filter("0:v", "z", master.ZoomHit(0.5, 1.10))
    ffmpeg("-i", str(src), "-filter_complex", frag, "-map", "[z]", "-c:v", "libx264",
           "-preset", "ultrafast", "-crf", "5", "-pix_fmt", "yuv420p", str(out))  # fmt: skip

    def diff(t: float) -> float:
        a, b = frame_at(src, t, tmp_path), frame_at(out, t, tmp_path)
        return sum(ImageStat.Stat(ImageChops.difference(a, b)).mean) / 3

    assert diff(0.2) < 2 and diff(0.9) < 2
    assert diff(0.5 + 0.125) > 8, "peak of the punch-in"
    assert probe(out, loudness=False).width == 1080 and probe(out, loudness=False).height == 1920


def test_impact_fragment_delays_and_attenuates():
    frag = master.impact_filter(3, 1.5, "imp0")
    assert frag == "[3:a]adelay=1500|1500,volume=-6dB[imp0]"


def test_overlay_fragment_windows_the_overlay():
    ov = master.Overlay(Path("x.png"), start=1.5, end=2.0)
    assert master.overlay_filter("v1", 4, "v2", ov) == "[v1][4:v]overlay=enable='between(t,1.5,2)'[v2]"
    always = master.Overlay(Path("x.png"), start=0, end=None)
    assert master.overlay_filter("v1", 4, "v2", always) == "[v1][4:v]overlay[v2]"
    late = master.Overlay(Path("x.png"), start=2.5, end=None, x=40, y=359)
    assert master.overlay_filter("v1", 5, "v2", late) == "[v1][5:v]overlay=x=40:y=359:enable='gte(t,2.5)'[v2]"


# ---- audio mix ---------------------------------------------------------------------------------


def rms(samples: list[int], rate: int, t0: float, t1: float) -> float:
    seg = samples[int(t0 * rate) : int(t1 * rate)]
    return math.sqrt(sum(s * s for s in seg) / max(len(seg), 1)) / 32768


def s16(path: Path) -> Path:
    """The mix is 32-bit float (headroom before loudnorm); ``wave`` reads 16-bit PCM only."""
    out = path.with_name(path.stem + "_s16.wav")
    ffmpeg("-i", str(path), "-c:a", "pcm_s16le", str(out))
    return out


def silence(path: Path, dur: float) -> Path:
    ffmpeg("-f", "lavfi", "-i", f"anullsrc=r=48000:cl=stereo:d={dur:g}", str(path))
    return path


def test_mix_places_sting_and_impacts_and_pads_to_length(tmp_path):
    beat = silence(tmp_path / "beat.wav", 1.0)  # shorter than the clip: padded with silence
    out = master.mix_audio(beat, 0.0, total_s=4.0, sting_at_s=2.5, impacts_at_s=[1.0], out=tmp_path / "mix.wav",
                           work=tmp_path)  # fmt: skip
    samples, ch, rate = read_wav(s16(out))
    assert (ch, rate) == (2, 48000)
    assert len(samples) / rate == pytest.approx(4.0, abs=0.01)
    assert rms(samples, rate, 0.0, 0.9) < 0.001, "silent beat before the thump"
    assert rms(samples, rate, 1.0, 1.3) > 0.05, "the thump lands at 1.0 s"
    assert rms(samples, rate, 1.6, 2.4) < 0.001
    assert rms(samples, rate, 2.5, 2.9) > 0.05, "the sting lands at 2.5 s"
    assert rms(samples, rate, 3.2, 4.0) < 0.01


def test_mix_cuts_the_beat_from_the_offset_and_fades_it_out(tmp_path):
    beat = tone(tmp_path / "beat.wav", 4.0, lead_s=1.0)  # 1 s of silence, then the tone
    out = master.mix_audio(beat, 1.0, total_s=3.0, sting_at_s=None, impacts_at_s=[], out=tmp_path / "mix.wav",
                           work=tmp_path, fade_out_at_s=2.0)  # fmt: skip
    samples, _, rate = read_wav(s16(out))
    assert len(samples) / rate == pytest.approx(3.0, abs=0.01)
    assert rms(samples, rate, 0.2, 1.0) > 0.2
    assert rms(samples, rate, 2.7, 3.0) < rms(samples, rate, 0.2, 1.0) / 4, "faded out"


# ---- the master timeline -----------------------------------------------------------------------

POP_BOX = (0, 1150, 1080, 1500)  # where a text_pop lands (the hook text sits at y=350)
TITLE_BOX = (0, 1200, 1080, 1600)  # the title band


def test_master_meets_spec(tmp_path, synth_video):
    dance = synth_video(dur=9)
    audio = synth_video(dur=9)
    spec = spec_for(
        tmp_path, dance, audio,
        closeup=detailed_png(tmp_path / "closeup.png"), hook2_until_s=3.0,
    )  # fmt: skip
    out = build_master(spec)
    assert out == spec.out and out.is_file()
    report = probe(out)
    assert check_master(report) == [], report
    assert report.duration_s == pytest.approx(0.8 + 9 + 0.7, abs=0.05)
    assert report.video_profile == "High" and report.audio_hz == 48000


def test_master_without_closeup_has_no_intro_or_outro(tmp_path):
    dance = flat_video(tmp_path / "dance.mp4", 2)
    spec = spec_for(tmp_path, dance, tone(tmp_path / "beat.wav", 3), closeup=None, hook1=[], hook2_until_s=1.0)
    out = build_master(spec)
    report = probe(out)
    assert report.duration_s == pytest.approx(2.0, abs=0.05)
    assert (report.width, report.height, report.fps) == (1080, 1920, 30.0) and report.has_audio


def test_slowmo_extends_duration(tmp_path):
    """Half speed over 0.5 s adds 0.5 s; later enhancements follow their moment to its new place."""
    dance = flat_video(tmp_path / "dance.mp4", 2)
    spec = spec_for(
        tmp_path, dance, tone(tmp_path / "beat.wav", 6),
        enhancements=[
            {"type": "slowmo", "at_s": 1.2, "dur_s": 0.5, "factor": 0.5},
            {"type": "text_pop", "at_s": 1.9, "dur_s": 0.4, "text": "WAIT FOR IT"},  # lands at 2.4-2.8
        ],
    )  # fmt: skip
    out = build_master(spec)
    report = probe(out, loudness=False)
    assert report.duration_s == pytest.approx(0.8 + 2 + 0.7 + 0.5, abs=0.06)
    assert report.fps == 30.0 and (report.width, report.height) == (1080, 1920)
    before, inside, after = (frame_at(out, t, tmp_path) for t in (2.0, 2.6, 3.1))
    assert bright_pixels(before, POP_BOX) == 0
    assert bright_pixels(inside, POP_BOX) > 800
    assert bright_pixels(after, POP_BOX) == 0


@pytest.fixture(scope="module")
def enhanced(tmp_path_factory) -> tuple[Path, Path]:
    """One render with a title card, a text pop, a zoom hit and an impact over a flat clip."""
    tmp = tmp_path_factory.mktemp("enhanced")
    spec = spec_for(
        tmp, flat_video(tmp / "dance.mp4", 2), tone(tmp / "beat.wav", 6),
        enhancements=[
            {"type": "title_card", "text": "Biscuit"},
            {"type": "text_pop", "at_s": 1.5, "dur_s": 0.5, "text": "WAIT FOR IT"},
            {"type": "zoom_hit", "at_s": 1.5},
            {"type": "impact_sfx", "at_s": 1.5},
        ],
    )  # fmt: skip
    return build_master(spec), tmp



def test_text_pop_visible_only_in_window(enhanced):
    out, tmp = enhanced
    before, inside, after = (frame_at(out, t, tmp) for t in (1.0, 1.75, 2.4))
    assert bright_pixels(before, POP_BOX) == 0
    assert bright_pixels(inside, POP_BOX) > 800
    assert bright_pixels(after, POP_BOX) == 0


def test_title_card_shows_for_the_first_600ms_only(enhanced):
    out, tmp = enhanced
    early, later = frame_at(out, 0.3, tmp), frame_at(out, 0.9, tmp)
    assert bright_pixels(early, TITLE_BOX, floor=215) > 500
    assert bright_pixels(later, TITLE_BOX, floor=215) == 0


def test_a_full_enhanced_master_keeps_the_delivery_format(enhanced):
    out, _ = enhanced
    report = probe(out)
    assert (report.width, report.height, report.fps) == (1080, 1920, 30.0)
    assert report.duration_s == pytest.approx(0.8 + 2 + 0.7, abs=0.05)
    assert report.has_audio and report.audio_hz == 48000


def test_enhancements_are_validated_before_any_rendering(tmp_path):
    spec = spec_for(tmp_path, tmp_path / "missing.mp4", tmp_path / "missing.wav",
                    enhancements=[{"type": "wobble"}])  # fmt: skip
    with pytest.raises(ValueError, match="unknown enhancement"):
        build_master(spec)


def test_a_slowmo_past_the_end_is_refused(tmp_path):
    dance = flat_video(tmp_path / "dance.mp4", 1)
    spec = spec_for(tmp_path, dance, tone(tmp_path / "beat.wav", 4),
                    enhancements=[{"type": "slowmo", "at_s": 2.0, "dur_s": 1.5, "factor": 0.5}])  # fmt: skip
    with pytest.raises(ValueError, match="runs past"):
        build_master(spec)


def test_closeup_must_be_portrait_9_16(tmp_path):
    wide = tmp_path / "wide.png"
    Image.new("RGB", (1920, 1080)).save(wide)
    spec = spec_for(tmp_path, flat_video(tmp_path / "d.mp4", 1), tone(tmp_path / "b.wav", 3), closeup=wide)
    with pytest.raises(ValueError, match="9:16"):
        build_master(spec)


def test_an_ffmpeg_failure_is_a_master_error_with_the_tail(tmp_path):
    dance = tmp_path / "not_a_video.mp4"
    dance.write_text("nope")
    spec = spec_for(tmp_path, dance, tone(tmp_path / "beat.wav", 3))
    with pytest.raises(master.MasterError, match="ffmpeg"):
        build_master(spec)


# ---- CLI ---------------------------------------------------------------------------------------


def spec_json(tmp_path: Path, dance: Path, audio: Path, **over) -> Path:
    spec = spec_for(tmp_path, dance, audio, **over)
    data = {k: str(v) if isinstance(v, Path) else v for k, v in dataclasses.asdict(spec).items()}
    path = tmp_path / "spec.json"
    path.write_text(json.dumps(data))
    return path


def test_cli_master_build_prints_json_and_exits_1_on_problems(tmp_path):
    dance = flat_video(tmp_path / "dance.mp4", 1)
    path = spec_json(tmp_path, dance, tone(tmp_path / "beat.wav", 3), closeup=None)
    r = CliRunner().invoke(app, ["master", "build", "--spec", str(path)])
    data = json.loads(r.stdout)
    assert data["out"] == str(tmp_path / "master.mp4") and (tmp_path / "master.mp4").is_file()
    assert data["duration_s"] == pytest.approx(1.0, abs=0.06)
    keys = [p.split(":", 1)[0] for p in data["problems"]]
    assert "duration" in keys and data["ok"] is False and r.exit_code == 1


def test_cli_master_build_rejects_a_bad_spec(tmp_path):
    runner = CliRunner()
    r = runner.invoke(app, ["master", "build", "--spec", str(tmp_path / "nope.json")])
    assert r.exit_code == 2 and "no such file" in r.output
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"dance": "x.mp4"}))
    r = runner.invoke(app, ["master", "build", "--spec", str(bad)])
    assert r.exit_code == 2 and "missing" in r.output and "audio" in r.output
    bad.write_text("{not json")
    assert runner.invoke(app, ["master", "build", "--spec", str(bad)]).exit_code == 2
    bad.write_text(json.dumps({"dance": "x", "audio": "y", "out": "z", "closeup": None, "hook1": [], "hook2": [],
                               "hook2_until_s": 1, "audio_offset_s": 0, "wobble": 1}))  # fmt: skip
    r = runner.invoke(app, ["master", "build", "--spec", str(bad)])
    assert r.exit_code == 2 and "wobble" in r.output


def test_cli_master_build_reports_a_bad_enhancement_as_exit_2(tmp_path):
    dance = flat_video(tmp_path / "dance.mp4", 1)
    path = spec_json(tmp_path, dance, tone(tmp_path / "beat.wav", 3), enhancements=[{"type": "wobble"}])
    r = CliRunner().invoke(app, ["master", "build", "--spec", str(path)])
    assert r.exit_code == 2 and "unknown enhancement" in r.output
