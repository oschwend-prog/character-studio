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
from PIL import Image, ImageChops, ImageFont, ImageStat
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


def test_the_studio_pill_is_a_full_frame_overlay_in_the_safe_zone_with_the_two_dots(tmp_path):
    png = overlays.pill_png(["Kindly do not inform the Duchess."], tmp_path / "pill.png")
    img = Image.open(png)
    assert img.mode == "RGBA" and img.size == overlays.FRAME
    left, top, right, bottom = img.getchannel("A").getbbox()
    assert overlays.SAFE_TOP <= top and bottom <= overlays.SAFE_BOTTOM  # clear of Instagram's buttons
    assert abs((left + right) / 2 - overlays.FRAME[0] / 2) <= 2  # centred
    cy = (top + bottom) // 2
    blue = img.getpixel((left + overlays.PILL_PAD_X, cy))[:3]
    amber = img.getpixel((left + overlays.PILL_PAD_X + overlays.PILL_DOT_GAP, cy))[:3]
    assert blue == overlays.BUG_BLUE and amber == overlays.BUG_AMBER  # the ODD EYES dots: blue first, amber second
    assert overlays.PILL_FONT.is_file()  # the committed Figtree: the same caption on the Mac and in the cloud


def test_a_long_hook_wraps_to_two_lines_and_a_low_pill_moves_up_out_of_the_buttons(tmp_path):
    short = Image.open(overlays.pill_png(["The household is unaware."], tmp_path / "s.png")).getchannel("A").getbbox()
    long = Image.open(overlays.pill_png(["Breakfast will be served at eight. As usual. Naturally."], tmp_path / "l.png"))
    lb = long.getchannel("A").getbbox()
    assert lb[3] - lb[1] > (short[3] - short[1]) * 1.5  # two lines
    low = Image.open(overlays.pill_png(["hi"], tmp_path / "low.png", y=1900)).getchannel("A").getbbox()
    assert low[3] <= overlays.SAFE_BOTTOM
    with pytest.raises(ValueError):
        overlays.pill_png(["  "], tmp_path / "x.png")


def test_the_text_pop_and_the_title_band_never_reach_the_studio_pill(tmp_path):
    from studio.media import master
    pill_top = Image.open(overlays.pill_png(["one", "two"], tmp_path / "p.png")).getchannel("A").getbbox()[1]
    pop = Image.open(overlays.hook_png(["WOW"], tmp_path / "pop.png", y=master.TEXT_POP_Y, size=master.TEXT_POP_SIZE))
    title = Image.open(overlays.title_png("TEA TIME", tmp_path / "t.png", y=master.TITLE_CARD_Y))
    assert pop.getchannel("A").getbbox()[3] < pill_top and title.getchannel("A").getbbox()[3] < pill_top


# ---- the style kits (C1): a caption pill per character ----------------------------------------

ROOT = Path(__file__).resolve().parents[1]
ROSTER = ("franz", "reginald", "lenny", "dj")
FRANZ_NAVY = (0x1F, 0x2A, 0x44)


def kit(slug: str) -> dict:
    """The character's style kit as the master will read it: refs.json ``style``, else ``style.json`` (the parked DJ)."""
    folder = ROOT / "characters" / slug
    if (folder / "refs.json").is_file():
        return json.loads((folder / "refs.json").read_text())["style"]
    return json.loads((folder / "style.json").read_text())


def pill_for(slug: str, lines: list[str], out: Path, y: int = overlays.PILL_Y) -> Image.Image:
    style = overlays.pill_style(kit(slug)["pill"])
    return Image.open(overlays.pill_png(lines, out, y=y, style=style))


def near(a, b, tol: int = 3) -> bool:
    return all(abs(x - y) <= tol for x, y in zip(a[:3], b[:3], strict=True))


def has_opaque(img: Image.Image, rgb, tol: int = 3, alpha: int = 255) -> bool:
    """Is there a pixel of this colour (within ``tol`` per channel) at this alpha? (The pill's fill is 215, its text 255.)"""
    return any(c[3] == alpha and near(c, rgb, tol) for _, c in img.getcolors(maxcolors=1 << 24))


def legacy_pill_png(lines: list[str], out: Path, y: int = 1300) -> Path:
    """The dark pill exactly as ``pill_png`` drew it before the style kits (a port of that body): the pixel reference for
    ``DEFAULT_PILL``. Self-contained on purpose, so a later change to the new code cannot move the reference."""
    from PIL import ImageDraw

    def font(size: int):
        fnt = ImageFont.truetype(str(overlays.PILL_FONT), size)
        fnt.set_variation_by_name(b"SemiBold")
        return fnt

    def wrap(words, fnt, width):
        draw = ImageDraw.Draw(Image.new("L", (1, 1)))
        out_lines: list[str] = []
        for word in words:
            if out_lines and draw.textlength(f"{out_lines[-1]} {word}", font=fnt) <= width:
                out_lines[-1] = f"{out_lines[-1]} {word}"
            else:
                out_lines.append(word)
        return out_lines

    words = " ".join(line for line in lines if line.strip()).split()
    size = 54
    while True:
        fnt = font(size)
        wrapped = wrap(words, fnt, 780)
        if len(wrapped) <= 2 or size <= 40:
            break
        size -= 2
    pitch = round(size * 1.26)
    probe_draw = ImageDraw.Draw(Image.new("L", (1, 1)))
    text_w = max(probe_draw.textlength(line, font=fnt) for line in wrapped)
    w, h = round(96 + text_w + 40), pitch * len(wrapped) + 2 * 25
    x0 = (1080 - w) // 2
    y0 = max(250, min(y, 1570 - h))
    k = 3
    pill = Image.new("RGBA", (w * k, h * k), (0, 0, 0, 0))
    d = ImageDraw.Draw(pill)
    d.rounded_rectangle((0, 0, w * k - 1, h * k - 1), radius=34 * k, fill=(14, 17, 22, 215))
    cy = h * k / 2
    for cx, colour in ((40 * k, (0x8F, 0xD3, 0xFF)), (66 * k, (0xFF, 0xB0, 0x40))):
        r = 10 * k
        d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(*colour, 255))
    big = font(size * k)
    for i, line in enumerate(wrapped):
        top = 25 * k + i * pitch * k
        d.text((96 * k, top + (pitch - size) * k / 2), line, font=big, fill=(255, 255, 255, 255))
    pill = pill.resize((w, h), Image.LANCZOS)
    layer = Image.new("RGBA", (1080, 1920), (0, 0, 0, 0))
    layer.alpha_composite(pill, (x0, y0))
    out.parent.mkdir(parents=True, exist_ok=True)
    layer.save(out)
    return out


@pytest.mark.parametrize(
    ("lines", "y"),
    [
        (["Kindly do not inform the Duchess."], 1300),  # one line
        (["Breakfast will be served at eight. As usual. Naturally."], 1300),  # wraps to two lines
        (["one", "two"], 1900),  # a low pill moves up out of the buttons
        (["hi"], 0),  # and one too high moves down
    ],
)
def test_default_pill_is_unchanged(tmp_path, lines, y):
    """A character without a style kit keeps today's pill, pixel for pixel."""
    legacy = Image.open(legacy_pill_png(lines, tmp_path / "legacy.png", y=y))
    plain = Image.open(overlays.pill_png(lines, tmp_path / "plain.png", y=y))
    styled = Image.open(overlays.pill_png(lines, tmp_path / "styled.png", y=y, style=overlays.DEFAULT_PILL))
    assert ImageChops.difference(plain, legacy).getbbox() is None, "no style: not one pixel moved"
    assert ImageChops.difference(styled, legacy).getbbox() is None, "DEFAULT_PILL is the same pill"
    assert overlays.pill_style(None) is overlays.DEFAULT_PILL and overlays.pill_style({}) == overlays.DEFAULT_PILL


def test_styled_pill_uses_the_kit_colours(tmp_path):
    img = pill_for("franz", ["Kindly do not inform the Duchess."], tmp_path / "franz.png")
    left, top, right, bottom = img.getchannel("A").getbbox()
    cy = (top + bottom) // 2
    px = img.getpixel((right - 14, cy))  # the padding after the text: the fill
    assert near(px, (0xF4, 0xEB, 0xDD), 2) and px[3] == overlays.pill_style(kit("franz")["pill"]).fill_alpha
    assert has_opaque(img, FRANZ_NAVY, 2), "the italic serif text is navy #1F2A44"
    reginald = pill_for("reginald", ["Kindly do not inform the Duchess."], tmp_path / "reg.png")
    assert has_opaque(reginald, (0xF2, 0xF0, 0xEA), 2), "the off-white small caps"
    assert has_opaque(reginald, (0xE8, 0xE6, 0xE1), 6), "and the thin rule #E8E6E1 round the card (a little soft at 3x -> 1x)"
    lenny = pill_for("lenny", ["Kindly do not inform the Duchess."], tmp_path / "lenny.png")
    _, ltop, lright, lbottom = lenny.getchannel("A").getbbox()
    assert has_opaque(lenny, (0x14, 0x14, 0x14), 2) and near(lenny.getpixel((lright - 14, (ltop + lbottom) // 2)), (0xE8, 0xB9, 0x31), 2)


@pytest.mark.parametrize("slug", ROSTER)
def test_dots_survive_every_kit(tmp_path, slug):
    img = pill_for(slug, ["Breakfast will be served at eight. As usual. Naturally."], tmp_path / f"{slug}.png")
    assert has_opaque(img, overlays.BUG_BLUE, 4), f"{slug}: the right-eye blue dot #8FD3FF"
    assert has_opaque(img, overlays.BUG_AMBER, 4), f"{slug}: the left-eye amber dot #FFB040"


def test_a_light_pill_rings_its_dots(tmp_path):
    light = overlays.PillStyle(fill="#F4EBDD", text="#1F2A44")
    dark = overlays.DEFAULT_PILL
    for style in (light, dark):
        img = Image.open(overlays.pill_png(["Kindly do not inform the Duchess."], tmp_path / "p.png", style=style))
        left, top, right, bottom = img.getchannel("A").getbbox()
        cx, cy = left + overlays.PILL_PAD_X, (top + bottom) // 2
        ring = img.getpixel((cx - overlays.PILL_DOT_R - 1, cy))
        assert img.getpixel((cx, cy))[:3] == overlays.BUG_BLUE, "the dot itself keeps its exact colour"
        if style is light:
            assert near(ring, FRANZ_NAVY, 12) and ring[3] == 255, "a 2 px ring in the text colour (soft at its 1x edges)"
            assert near(img.getpixel((cx - overlays.PILL_DOT_R - 4, cy)), (0xF4, 0xEB, 0xDD), 8), "and no wider than that"
        else:
            assert max(ring[:3]) < 60, "a dark pill needs no ring: the pixel beside the dot is still the dark fill"


@pytest.mark.parametrize("y", [0, 1300, 1900])
@pytest.mark.parametrize("hook", [["DROP"], ["Breakfast will be served at eight. As usual. Naturally."]])
def test_tilted_pill_stays_in_the_band(tmp_path, y, hook):
    img = pill_for("dj", hook, tmp_path / "dj.png", y=y)
    left, top, right, bottom = img.getchannel("A").getbbox()
    assert overlays.SAFE_TOP <= top and bottom <= overlays.SAFE_BOTTOM, "tilt, shear and block stay in the band"
    assert 0 < left and right < overlays.FRAME[0]
    assert abs((left + right) / 2 - overlays.FRAME[0] / 2) <= 3, "still centred"


def test_the_tilt_and_the_block_are_really_drawn(tmp_path):
    flat = Image.open(overlays.pill_png(["DROP THE BEAT"], tmp_path / "flat.png", style=overlays.PillStyle(font="Anton-Regular.ttf", case="upper")))
    dj = pill_for("dj", ["DROP THE BEAT"], tmp_path / "dj.png")
    fb, db = flat.getchannel("A").getbbox(), dj.getchannel("A").getbbox()
    assert db[3] - db[1] > (fb[3] - fb[1]) + 30, "the tilt and the shear make the pill taller than the flat one"
    alpha = dj.getchannel("A")
    quarter = (db[2] - db[0]) // 4
    left_top = alpha.crop((db[0], db[1], db[0] + quarter, db[3])).getbbox()[1] + db[1]
    right_top = alpha.crop((db[2] - quarter, db[1], db[2], db[3])).getbbox()[1] + db[1]
    assert right_top < left_top - 10, "tilt_deg -4: counter-clockwise, the pill rises to the right"
    assert has_opaque(dj, (0xFF, 0x7A, 0x00), 3), "the orange block #FF7A00 behind the pill"
    assert has_opaque(dj, (0xE6, 0xFF, 0x00), 3, alpha=215), "and the neon yellow fill #E6FF00 in front, not tinted by the block"


def test_case_tracking_and_weight_follow_the_style(tmp_path):
    upper = overlays.PillStyle(case="upper")
    a = Image.open(overlays.pill_png(["go go"], tmp_path / "a.png", style=upper))
    b = Image.open(overlays.pill_png(["GO GO"], tmp_path / "b.png", style=upper))
    assert ImageChops.difference(a, b).getbbox() is None, "upper: the same as typing capitals"
    assert a.getchannel("A").getbbox() == Image.open(overlays.pill_png(["GO GO"], tmp_path / "c.png")).getchannel("A").getbbox(), "same pill"

    def width(im: Image.Image) -> int:
        left, _, right, _ = im.getchannel("A").getbbox()
        return right - left

    plain = Image.open(overlays.pill_png(["ODD EYES"], tmp_path / "p.png"))
    spaced = Image.open(overlays.pill_png(["ODD EYES"], tmp_path / "s.png", style=overlays.PillStyle(tracking=3)))
    assert 19 <= width(spaced) - width(plain) <= 24, "tracking 3 adds 3 px between each of the 8 letters (7 gaps)"
    for slug in ("franz", "lenny"):  # the variable fonts really take their weight (no silent fallback to the default)
        style = overlays.pill_style(kit(slug)["pill"])
        raw = ImageFont.truetype(str(overlays.FONT_DIR / style.font), 40)
        assert overlays._apply_weight(raw, style.weight), slug
    medium = overlays.pill_style(kit("franz")["pill"])
    assert width(Image.open(overlays.pill_png(["Kindly do not inform"], tmp_path / "m.png", style=medium))) != width(
        Image.open(overlays.pill_png(["Kindly do not inform"], tmp_path / "r.png", style=dataclasses.replace(medium, weight=None)))
    ), "Medium Italic is wider than the font's default weight"
    ghost = overlays.PillStyle(font="Nope-Regular.ttf")
    assert overlays.pill_png(["a font that is gone falls back"], tmp_path / "g.png", style=ghost).is_file()


def test_pill_style_reads_the_refs_block_and_refuses_the_rest():
    s = overlays.pill_style({"fill": "#F4EBDD", "border": ["#E8E6E1", 2], "block": ["#FF7A00", 10, 10], "case": "smallcaps", "tilt_deg": -4, "shear": 0.2})
    assert s.border == ("#E8E6E1", 2) and s.block == ("#FF7A00", 10, 10) and s.case == "smallcaps"
    assert (s.tilt_deg, s.shear, s.font, s.weight) == (-4.0, 0.2, "Figtree-Variable.ttf", "SemiBold")
    bad = [
        {"fill": "red"}, {"fill": "#FFF"}, {"text": "#12345G"}, {"colour": "#FFFFFF"}, {"case": "title"}, {"font": "Nope.ttf"},
        {"font": "../x.ttf"}, {"radius": -1}, {"fill_alpha": 300}, {"border": ["#E8E6E1"]}, {"border": ["#E8E6E1", 0]},
        {"block": ["#FF7A00", 10]}, {"block": ["orange", 1, 1]}, {"tilt_deg": 45}, {"shear": 2}, {"tracking": True}, {"weight": 600},
    ]
    for style in bad:
        with pytest.raises(ValueError):
            overlays.pill_style(style)
    with pytest.raises(ValueError):
        overlays.pill_style("dark")  # type: ignore[arg-type]


def test_every_shipped_font_has_its_ofl_licence_and_the_kits_fit_in_a_few_megabytes():
    fonts = sorted((ROOT / "assets" / "fonts").glob("*.ttf"))
    assert {f.name for f in fonts} >= {
        "Figtree-Variable.ttf", "PlayfairDisplay-Italic-Variable.ttf", "CormorantSC-Medium.ttf", "Oswald-Variable.ttf", "Anton-Regular.ttf"
    }
    for f in fonts:
        licence = f.with_name(f"{f.stem.split('-')[0]}-OFL.txt")
        assert licence.is_file() and "SIL Open Font License" in licence.read_text(), f.name
    assert sum(f.stat().st_size for f in fonts) < 3_000_000


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

POP_BOX = (0, 1080, 1080, 1240)  # where a text_pop lands: above the studio pill (y >= 1300), which holds the hook
TITLE_BOX = (0, 1000, 1080, 1160)  # the title band, also above the pill


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


# ---- the end beat: eye close-up, glint and sting, in a built master -----------------------------------


def test_a_built_master_ends_on_the_eye_closeup_with_the_glint_and_the_sting(tmp_path):
    """Every master ends on the close-up glint + sting (CLAUDE.md): checked in the rendered file."""
    dance = flat_video(tmp_path / "dance.mp4", 2, colour="0x203040")  # dark blue, no bright pixel anywhere
    closeup = flat_png(tmp_path / "eye_closeup.png", colour=(150, 30, 30))  # red: unlike the dance, no bright pixel
    beat = tone(tmp_path / "beat.wav", 1.0)  # the beat is over long before the dance ends
    spec = spec_for(tmp_path, dance, beat, closeup=closeup, hook1=[], hook2=[], audio_offset_s=0.0)
    out = build_master(spec)
    total = probe(out, loudness=False).duration_s
    dance_end = total - spec.outro_s
    glint_box = (spec.blue_eye_xy[0] - 150, spec.blue_eye_xy[1] - 150, spec.blue_eye_xy[0] + 150, spec.blue_eye_xy[1] + 150)

    # the picture: the dance, then the close-up with the sparkle on the blue eye
    dance_frame = frame_at(out, 0.8 + 1.0, tmp_path)
    end_frame = frame_at(out, dance_end + 0.28, tmp_path)
    assert ImageStat.Stat(dance_frame).mean[2] > ImageStat.Stat(dance_frame).mean[0]  # blue dance
    assert ImageStat.Stat(end_frame).mean[0] > ImageStat.Stat(end_frame).mean[2] + 40  # the red close-up
    assert bright_pixels(dance_frame, glint_box) == 0
    assert bright_pixels(end_frame, glint_box, floor=215) > 300, "the glint sits on the blue eye"
    assert bright_pixels(end_frame, (0, 0, 1080, 600), floor=215) == 0  # and only there

    # the sound: the sting lands just after the dance ends, over a silent beat
    samples, _, rate = read_wav(s16_of(out, tmp_path))
    quiet = rms(samples, rate, 1.4, dance_end - 0.1)
    sting = rms(samples, rate, dance_end + 0.1, dance_end + 0.55)
    assert sting > 0.02 and sting > 20 * quiet, (sting, quiet)


def s16_of(video: Path, tmp: Path) -> Path:
    wav = tmp / "master_audio.wav"
    ffmpeg("-i", str(video), "-vn", "-c:a", "pcm_s16le", str(wav))
    return wav


# ---- hooks are lists of lines; the hook2 window must be real with or without a close-up ----------------


@pytest.mark.parametrize("key", ["hook1", "hook2"])
@pytest.mark.parametrize("bad", ["my eyes don't match.", 5, None, [["a"]], ["ok", 3], {"line": "x"}])
def test_spec_from_json_rejects_a_hook_that_is_not_a_list_of_strings(key, bad):
    """A str is a sequence of characters: it would render one letter per line."""
    data = {"dance": "d.mp4", "audio": "a.wav", "out": "o.mp4", "closeup": None, key: bad}
    with pytest.raises(ValueError, match=key):
        master.spec_from_json(data)


def test_spec_from_json_accepts_lists_of_lines_and_the_defaults():
    data = {"dance": "d.mp4", "audio": "a.wav", "out": "o.mp4", "closeup": None,
            "hook1": ["a", "b"], "hook2": ["c"], "hook2_until_s": 2.0}  # fmt: skip
    spec = master.spec_from_json(data)
    assert (spec.hook1, spec.hook2) == (["a", "b"], ["c"])
    bare = master.spec_from_json({"dance": "d.mp4", "audio": "a.wav", "out": "o.mp4", "closeup": None})
    assert (bare.hook1, bare.hook2) == ([], [])


def test_the_hook2_window_is_checked_without_a_closeup_too(tmp_path):
    """No intro: the window runs from 0, so an end at or before 0 would flash for one frame."""
    dance = flat_video(tmp_path / "dance.mp4", 1)
    spec = spec_for(tmp_path, dance, tone(tmp_path / "beat.wav", 3), closeup=None, hook1=[], hook2_until_s=0.0)
    with pytest.raises(ValueError, match="hook2_until_s"):
        build_master(spec)
    assert not spec.out.exists()


def test_the_hook2_window_still_has_to_follow_the_intro_with_a_closeup(tmp_path):
    dance = flat_video(tmp_path / "dance.mp4", 1)
    spec = spec_for(tmp_path, dance, tone(tmp_path / "beat.wav", 3), hook2_until_s=0.5)  # intro is 0.8 s
    with pytest.raises(ValueError, match="hook2_until_s"):
        build_master(spec)


def test_without_hook2_text_no_window_is_needed(tmp_path):
    dance = flat_video(tmp_path / "dance.mp4", 1)
    spec = spec_for(tmp_path, dance, tone(tmp_path / "beat.wav", 3), closeup=None, hook1=[], hook2=[], hook2_until_s=0.0)
    assert build_master(spec).is_file()


# ---- the beat must be ours: never the source's soundtrack (third-party audio) -----------------------------


@pytest.fixture
def clip_rig(monkeypatch):
    from studio.models import Body, Clip, Source
    from studio.store import MemoryStore

    store = MemoryStore()
    monkeypatch.setattr(master, "open_store", lambda: store)

    def make(mode: str, kind: str | None):
        source = None
        if kind:
            source = store.add_source(Source(kind=kind, body=Body.biped, bodies=1, duration_s=9.0))
        return store.add_clip(Clip(character_slug="biscuit", mode=mode, state="qa_passed",
                                   source_id=source.id if source else None))

    return store, make


def run_build(tmp_path, dance, audio, *extra, **over):
    return CliRunner().invoke(app, ["master", "build", "--spec", str(spec_json(tmp_path, dance, audio, closeup=None, hook1=[], **over)), *extra])


def test_a_build_whose_audio_is_the_dance_file_is_refused_without_clip_context(tmp_path):
    dance = flat_video(tmp_path / "dance.mp4", 1)
    r = run_build(tmp_path, dance, dance)
    assert r.exit_code == 2 and "third-party" in r.output and "--clip" in r.output
    assert not (tmp_path / "master.mp4").exists()


def test_a_copy_of_the_dance_file_is_the_same_file(tmp_path):
    dance = flat_video(tmp_path / "dance.mp4", 1)
    copy = tmp_path / "gen_copy.mp4"
    copy.write_bytes(dance.read_bytes())
    assert run_build(tmp_path, dance, copy).exit_code == 2


@pytest.mark.parametrize(("mode", "kind"), [
    ("dropin", "higgsfield_library"), ("dropin", "owner_inbox"), ("recreate", "higgsfield_library"),
    ("recreate", "owner_inbox"), ("recreate", None),
])  # fmt: skip
def test_the_dance_audio_is_refused_for_every_clip_that_is_not_recreate_from_a_synthetic_driver(
    tmp_path, clip_rig, mode, kind
):
    store, make = clip_rig
    clip = make(mode, kind)
    dance = flat_video(tmp_path / "dance.mp4", 1)
    r = run_build(tmp_path, dance, dance, "--clip", clip.id)
    assert r.exit_code == 2 and "third-party" in r.output
    assert not (tmp_path / "master.mp4").exists()


def test_a_recreate_clip_with_a_synthetic_driver_may_use_its_own_generation_audio(tmp_path, clip_rig):
    """The synthetic driver (Seedance) carries OUR beat: gen.mp4's audio is ours there."""
    store, make = clip_rig
    clip = make("recreate", "synthetic")
    dance = tmp_path / "dance.mp4"
    ffmpeg("-f", "lavfi", "-i", "color=c=0x203040:s=1080x1920:r=30:d=1", "-f", "lavfi", "-i", "sine=frequency=330:duration=1",
           "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-shortest", str(dance))  # fmt: skip
    r = run_build(tmp_path, dance, dance, "--clip", clip.id)
    assert r.exit_code in (0, 1), r.output  # built (1 only means the 1 s clip misses the 7 s master spec)
    assert (tmp_path / "master.mp4").is_file()


def test_the_clip_can_come_from_the_spec_as_clip_id(tmp_path, clip_rig):
    store, make = clip_rig
    clip = make("dropin", "higgsfield_library")
    dance = flat_video(tmp_path / "dance.mp4", 1)
    r = run_build(tmp_path, dance, dance, clip_id=clip.id)
    assert r.exit_code == 2 and "third-party" in r.output


def test_a_clip_given_twice_must_agree_and_must_exist(tmp_path, clip_rig):
    store, make = clip_rig
    a, b = make("recreate", "synthetic"), make("recreate", "synthetic")
    dance = flat_video(tmp_path / "dance.mp4", 1)
    assert run_build(tmp_path, dance, dance, "--clip", a.id, clip_id=b.id).exit_code == 2
    r = run_build(tmp_path, dance, dance, "--clip", "no-such-clip")
    assert r.exit_code == 2 and "unknown clip" in r.output


def test_audio_under_an_inbox_folder_is_a_source_file_and_is_refused(tmp_path, clip_rig):
    store, make = clip_rig
    clip = make("dropin", "owner_inbox")
    dance = flat_video(tmp_path / "dance.mp4", 1)
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    src = tone(inbox / "owner_clip.wav", 3)
    r = run_build(tmp_path, dance, src, "--clip", clip.id)
    assert r.exit_code == 2 and "source" in r.output


# ---- Drop-ins keep the original clip audio by default (owner decision 2026-10-05) ----------------------------------


@pytest.fixture
def original_rig(clip_rig):
    """A Drop-in clip made as the daily run makes it: ``features.music`` and, for a pick, ``features.fav_id``."""
    from studio.models import Body, Clip, Favorite, Source

    store, _ = clip_rig

    def make(*, clip_music="original", owner_music=None, with_pick=True):
        source = store.add_source(Source(kind="higgsfield_library", body=Body.biped, bodies=1, duration_s=9.0))
        pick = store.add_favorite(Favorite(
            url=f"https://www.tiktok.com/@c/video/{len(store.list_favorites()) + 1}", platform="tiktok",
            status="approved", proposal={"owner_music": owner_music} if owner_music else {},
        ))
        features = {"music": clip_music, **({"fav_id": pick.id} if with_pick else {})}
        return store.add_clip(Clip(character_slug="biscuit", mode="dropin", state="qa_passed",
                                   source_id=source.id, features=features))

    return make


def sine_dance(tmp_path: Path) -> Path:
    dance = tmp_path / "dance.mp4"
    ffmpeg("-f", "lavfi", "-i", "color=c=0x203040:s=1080x1920:r=30:d=1", "-f", "lavfi", "-i", "sine=frequency=330:duration=1",
           "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-shortest", str(dance))  # fmt: skip
    return dance


@pytest.mark.parametrize("kw", [{}, {"with_pick": False}, {"owner_music": "original"}])
def test_the_original_audio_is_kept_for_a_dropin_clip_marked_music_original(tmp_path, original_rig, kw):
    """music "original" (the default): the Genjutsu output's own soundtrack is the master's audio, loudness-normalised."""
    clip = original_rig(**kw)
    dance = sine_dance(tmp_path)
    r = run_build(tmp_path, dance, dance, "--clip", clip.id, music="original")
    assert r.exit_code in (0, 1), r.output  # built (1 only means the 1 s clip misses the master spec)
    assert (tmp_path / "master.mp4").is_file()
    assert probe(tmp_path / "master.mp4").lufs == pytest.approx(-14.0, abs=1.5)  # normalised, not left raw


@pytest.mark.parametrize(
    ("kw", "message"),
    [
        ({"owner_music": "in_app"}, "owner chose in_app"),  # the owner picked another music for this video
        ({"owner_music": "ai_beat"}, "owner chose ai_beat"),
        ({"clip_music": "ai_beat"}, "third-party"),  # the clip is not marked original
        ({"clip_music": "in_app"}, "third-party"),
        ({"clip_music": None}, "third-party"),
    ],
)
def test_the_original_audio_is_refused_unless_the_clip_is_original_and_the_owner_did_not_choose_otherwise(
    tmp_path, original_rig, kw, message
):
    clip = original_rig(**kw)
    dance = flat_video(tmp_path / "dance.mp4", 1)
    r = run_build(tmp_path, dance, dance, "--clip", clip.id, music="original")
    assert r.exit_code == 2 and message in r.output
    assert not (tmp_path / "master.mp4").exists()


def test_the_original_audio_needs_the_clip_to_be_named(tmp_path, original_rig):
    """Without --clip the exception cannot be proved, so the generation's audio is refused as ever."""
    original_rig()
    dance = flat_video(tmp_path / "dance.mp4", 1)
    r = run_build(tmp_path, dance, dance, music="original")
    assert r.exit_code == 2 and "third-party" in r.output and "--clip" in r.output


def test_a_recreate_clip_never_keeps_original_audio(tmp_path, clip_rig):
    store, make = clip_rig
    clip = make("recreate", "higgsfield_library")
    store.update_clip(clip.id, features={"music": "original"})  # cannot be made through `clip new`; refused here too
    dance = flat_video(tmp_path / "dance.mp4", 1)
    assert run_build(tmp_path, dance, dance, "--clip", clip.id, music="original").exit_code == 2


def test_the_original_audio_choice_does_not_open_the_inbox_files(tmp_path, original_rig):
    clip = original_rig()
    dance = flat_video(tmp_path / "dance.mp4", 1)
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    r = run_build(tmp_path, dance, tone(inbox / "source.wav", 3), "--clip", clip.id, music="original")
    assert r.exit_code == 2 and "source" in r.output  # only the generation's own audio, never the raw source file


def test_audio_problem_allows_the_default_and_refuses_what_the_owner_overrode(tmp_path):
    from studio.models import Clip

    dance = flat_video(tmp_path / "dance.mp4", 1)
    clip = Clip(character_slug="biscuit", mode="dropin", features={"music": "original"})
    assert master.audio_problem(dance, dance, clip, None) is None  # the default needs no explicit owner choice
    assert master.audio_problem(dance, dance, clip, None, owner_music="original") is None
    assert "owner chose in_app" in master.audio_problem(dance, dance, clip, None, owner_music="in_app")
    plain = Clip(character_slug="biscuit", mode="dropin", features={})
    assert "third-party" in master.audio_problem(dance, dance, plain, None)


def test_a_separate_beat_render_is_fine_for_a_dropin_clip(tmp_path, clip_rig):
    """The legal path: a Seedance beat render of our own (a different file from the dance)."""
    store, make = clip_rig
    clip = make("dropin", "higgsfield_library")
    dance = flat_video(tmp_path / "dance.mp4", 1)
    r = run_build(tmp_path, dance, tone(tmp_path / "beat.wav", 3), "--clip", clip.id)
    assert r.exit_code in (0, 1) and (tmp_path / "master.mp4").is_file()


def test_audio_rights_is_a_plain_function_too(tmp_path):
    dance = flat_video(tmp_path / "dance.mp4", 1)
    beat = tone(tmp_path / "beat.wav", 1)
    assert master.audio_problem(dance, beat, None, None) is None
    assert "third-party" in master.audio_problem(dance, dance, None, None)


# ---- music "in_app": a silent master, the owner adds the song in the Instagram app -----------------------------


def test_spec_from_json_music_defaults_to_ai_beat_which_needs_its_audio():
    spec = master.spec_from_json({"dance": "d.mp4", "audio": "a.wav", "out": "o.mp4", "closeup": None})
    assert spec.music == "ai_beat"
    with pytest.raises(ValueError, match="audio"):
        master.spec_from_json({"dance": "d.mp4", "out": "o.mp4", "closeup": None})
    with pytest.raises(ValueError, match="audio"):
        master.spec_from_json({"dance": "d.mp4", "out": "o.mp4", "closeup": None, "music": "original"})


def test_spec_from_json_in_app_needs_no_audio_and_unknown_music_is_refused():
    spec = master.spec_from_json({"dance": "d.mp4", "out": "o.mp4", "closeup": None, "music": "in_app"})
    assert (spec.music, spec.audio) == ("in_app", None)
    with pytest.raises(ValueError, match="music"):
        master.spec_from_json({"dance": "d.mp4", "audio": "a.wav", "out": "o.mp4", "closeup": None, "music": "spotify"})


def test_an_in_app_master_carries_a_silent_aac_track_and_meets_the_silent_master_spec(tmp_path, synth_video):
    dance = synth_video(dur=7)
    spec = spec_for(
        tmp_path, dance, None, music="in_app", closeup=detailed_png(tmp_path / "closeup.png"), hook2_until_s=3.0,
    )  # fmt: skip
    out = build_master(spec)
    report = probe(out)
    assert report.has_audio and report.audio_codec == "aac" and report.audio_hz == 48000
    assert report.lufs is not None and report.lufs <= -60  # digital silence: no sting, no beat, nothing of the source
    assert check_master(report, silent=True) == [], report
    assert "loudness" in [p.split(":", 1)[0] for p in check_master(report)]  # judged as a normal master it would fail
    assert report.duration_s == pytest.approx(0.8 + 7 + 0.7, abs=0.05)


def test_an_in_app_master_ignores_impact_sfx_because_it_has_no_sound_at_all(tmp_path, synth_video):
    spec = spec_for(tmp_path, synth_video(dur=7), None, music="in_app", enhancements=[{"type": "impact_sfx", "at_s": 2.0}])
    report = probe(build_master(spec))
    assert report.lufs is not None and report.lufs <= -60


def test_a_non_silent_build_without_audio_is_refused_before_rendering(tmp_path, synth_video):
    spec = spec_for(tmp_path, synth_video(dur=7), None, music="ai_beat")
    with pytest.raises(ValueError, match="audio"):
        build_master(spec)
    assert not spec.out.exists()


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


def test_cli_master_build_in_app_judges_the_silent_track_as_expected(tmp_path, synth_video):
    path = spec_json(tmp_path, synth_video(dur=7), None, music="in_app", closeup=None, hook1=[], hook2=[], hook2_until_s=0.0)
    r = CliRunner().invoke(app, ["master", "build", "--spec", str(path)])
    data = json.loads(r.stdout)
    assert r.exit_code == 0, r.output
    assert data["ok"] is True and data["problems"] == [] and data["lufs"] <= -60


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


# ---- master upload: the finished master goes to the `clips` bucket and onto the clip ---------------


@pytest.fixture
def upload_rig(monkeypatch, tmp_path):
    from studio.models import Clip
    from studio.storage import LocalStorage
    from studio.store import MemoryStore

    store = MemoryStore()
    storage = LocalStorage(tmp_path / "bucket")
    monkeypatch.setattr(master, "open_store", lambda: store)
    monkeypatch.setattr(master, "open_storage", lambda: storage)
    clip = store.add_clip(Clip(character_slug="biscuit", mode="recreate", state="qa_passed"))
    return store, storage, clip


def test_the_master_bucket_is_the_one_publishing_reads():
    from studio.publish.base import MASTER_BUCKET

    assert master.MASTER_BUCKET == MASTER_BUCKET == "clips"


def test_upload_master_stores_the_file_and_sets_the_master_path(upload_rig, synth_video):
    store, storage, clip = upload_rig
    got = master.upload_master(store, storage, clip.id, synth_video())
    assert got.master_path == f"biscuit/{clip.id}.mp4"
    assert store.get_clip(clip.id).master_path == got.master_path
    assert storage.signed_url("clips", got.master_path).startswith("file://")  # it is really there
    assert got.state.value == "qa_passed"  # the state moves through `clip set`, not here


def test_upload_master_refuses_a_file_that_misses_the_master_spec(upload_rig, synth_video):
    store, storage, clip = upload_rig
    with pytest.raises(master.MasterRejected) as e:
        master.upload_master(store, storage, clip.id, synth_video(w=720, h=1280))
    assert any(p.startswith("resolution") for p in e.value.problems)
    assert store.get_clip(clip.id).master_path is None


def test_upload_master_accepts_a_silent_master_only_for_an_in_app_clip(upload_rig, synth_video, tmp_path):
    store, storage, clip = upload_rig
    silent = tmp_path / "silent.mp4"
    ffmpeg("-i", str(synth_video(dur=8)), "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
           "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-c:a", "aac", "-ar", "48000", "-shortest", str(silent))  # fmt: skip
    with pytest.raises(master.MasterRejected) as e:
        master.upload_master(store, storage, clip.id, silent)  # an ordinary clip: silence is a loudness problem
    assert any(p.startswith("loudness") for p in e.value.problems)
    store.update_clip(clip.id, features={"music": "in_app"})
    assert master.upload_master(store, storage, clip.id, silent).master_path == f"biscuit/{clip.id}.mp4"


def test_upload_master_judges_an_eye_loop_by_the_loop_length(upload_rig, synth_video):
    store, storage, clip = upload_rig
    with pytest.raises(master.MasterRejected):
        master.upload_master(store, storage, clip.id, synth_video(dur=3))  # too short for both
    got = master.upload_master(store, storage, clip.id, synth_video(dur=7), loop=True)
    assert got.master_path


def test_upload_master_unknown_clip_and_missing_file(upload_rig, synth_video):
    store, storage, clip = upload_rig
    with pytest.raises(KeyError):
        master.upload_master(store, storage, "nope", synth_video())
    with pytest.raises(master.QAError):
        master.upload_master(store, storage, clip.id, Path("/no/such/file.mp4"))


def test_cli_master_upload_prints_the_clip_path(upload_rig, synth_video):
    store, storage, clip = upload_rig
    r = CliRunner().invoke(app, ["master", "upload", clip.id, str(synth_video())])
    assert r.exit_code == 0, r.output
    out = json.loads(r.stdout)
    assert out == {"clip": clip.id, "master_path": f"biscuit/{clip.id}.mp4", "bucket": "clips"}


def test_cli_master_upload_exit_codes(upload_rig, synth_video):
    store, storage, clip = upload_rig
    runner = CliRunner()
    r = runner.invoke(app, ["master", "upload", clip.id, str(synth_video(w=720, h=1280))])
    assert r.exit_code == 1 and json.loads(r.stdout)["ok"] is False
    assert any(p.startswith("resolution") for p in json.loads(r.stdout)["problems"])
    assert runner.invoke(app, ["master", "upload", "nope", str(synth_video())]).exit_code == 2
    assert runner.invoke(app, ["master", "upload", clip.id, "/no/such/file.mp4"]).exit_code == 2
