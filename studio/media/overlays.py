"""Overlay graphics (PIL PNGs) and synthesised sounds for the master timeline.

ffmpeg here has no ``drawtext``, so every piece of text or graphics is a full-frame (1080x1920)
transparent PNG that ``master`` lays over the video with ``overlay``. The look is the debut's:
white text, a 3 px dark stroke and a blurred drop shadow; the ODD EYES bug is two dots (the
character's right eye ice-blue ``#8FD3FF`` on the viewer's left, the left eye amber ``#FFB040``)
top-right at (972, 268); the sparkle is a four-point star with a soft glow.

Fonts are not committed (system licences). ``font_path()`` is Arial Rounded Bold on macOS and
otherwise whatever ``fc-match`` resolves ``DejaVu Sans:bold`` to (the CI image installs
``fonts-dejavu-core``); ``serif_font_path()`` is the same idea for the title card (Georgia Bold /
DejaVu Serif Bold).

The two sounds are written with the standard library only: a 0.6 s three-partial chime (the
sting that ends every master) and a short low thump (the ``impact_sfx`` enhancement). Both are
48 kHz 16-bit stereo, the master's own format.
"""

from __future__ import annotations

import math
import struct
import subprocess
import sys
import wave
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

FRAME = (1080, 1920)
TEXT_MARGIN = 30  # a hook line is shrunk until it fits this far inside both edges
STROKE_PX = 3
STROKE_COLOUR = (20, 30, 45, 255)
SHADOW_OFFSET = 6
SHADOW_BLUR = 6
SHADOW_ALPHA = 0.62
LINE_PITCH = 1.18  # line spacing as a multiple of the font size (the debut's 113 px at 96)
MIN_FONT_SIZE = 24

BUG_CENTER = (972, 268)
BUG_BLUE = (0x8F, 0xD3, 0xFF)
BUG_AMBER = (0xFF, 0xB0, 0x40)
BUG_DOT_SPACING = 40  # centre to centre
BUG_OUTER_RADIUS = 15.5
BUG_OUTLINE_PX = 2.0
_SUPERSAMPLE = 4

IVORY = (246, 241, 231)
TITLE_BAND = (14, 20, 28, 205)

AUDIO_RATE = 48_000
STING_SECONDS = 0.6
STING_PARTIALS = ((2093.0, 6.0, 0.35), (3136.0, 8.0, 0.18), (4186.0, 10.0, 0.09))  # Hz, decay/s, gain
IMPACT_SECONDS = 0.4

_MAC_SANS = Path("/System/Library/Fonts/Supplemental/Arial Rounded Bold.ttf")
_MAC_SERIF = Path("/System/Library/Fonts/Supplemental/Georgia Bold.ttf")


class OverlayError(RuntimeError):
    """A font could not be found."""


# ---- fonts -------------------------------------------------------------------------------------


def _fc_match(pattern: str) -> Path:
    try:
        proc = subprocess.run(
            ["fc-match", "-f", "%{file}", pattern],
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            timeout=30,
            check=False,
        )
        found = Path(proc.stdout.strip()) if proc.returncode == 0 and proc.stdout.strip() else None
    except (FileNotFoundError, subprocess.TimeoutExpired):
        found = None
    if found is None or not found.is_file():
        raise OverlayError(f"no font for {pattern!r}: install fonts-dejavu-core and fontconfig")
    return found


def font_path() -> Path:
    """Arial Rounded Bold on macOS, else ``fc-match 'DejaVu Sans:bold'``."""
    if sys.platform == "darwin" and _MAC_SANS.is_file():
        return _MAC_SANS
    return _fc_match("DejaVu Sans:bold")


def serif_font_path() -> Path:
    """The brand serif: Georgia Bold on macOS, else ``fc-match 'DejaVu Serif:bold'``."""
    if sys.platform == "darwin" and _MAC_SERIF.is_file():
        return _MAC_SERIF
    return _fc_match("DejaVu Serif:bold")


# ---- text --------------------------------------------------------------------------------------


def _line_width(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, stroke: int) -> float:
    left, _, right, _ = draw.textbbox((0, 0), text, font=font, stroke_width=stroke)
    return right - left


def _fit(lines: list[str], font_file: Path, size: int, stroke: int) -> ImageFont.FreeTypeFont:
    """The font at ``size``, or smaller if the widest line would cross the margins."""
    draw = ImageDraw.Draw(Image.new("L", (1, 1)))
    room = FRAME[0] - 2 * TEXT_MARGIN
    while True:
        font = ImageFont.truetype(str(font_file), size)
        widest = max(_line_width(draw, line, font, stroke) for line in lines)
        if widest <= room or size <= MIN_FONT_SIZE:
            return font
        size -= 2


def _shadowed(text_layer: Image.Image) -> Image.Image:
    """``text_layer`` over a blurred, offset black copy of its own silhouette."""
    alpha = text_layer.getchannel("A")
    shadow_alpha = ImageChops.offset(alpha, 0, SHADOW_OFFSET).point(lambda a: int(a * SHADOW_ALPHA))
    shadow = Image.new("RGBA", FRAME, (0, 0, 0, 0))
    shadow.putalpha(shadow_alpha.filter(ImageFilter.GaussianBlur(SHADOW_BLUR)))
    return Image.alpha_composite(shadow, text_layer)


def _save(img: Image.Image, out: str | Path) -> Path:
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out)
    return out


def _clean(lines: list[str]) -> list[str]:
    kept = [line for line in lines if line.strip()]
    if not kept:
        raise ValueError("need at least one non-empty line of text")
    return kept


def hook_png(
    lines: list[str],
    out: str | Path,
    y: int = 350,
    size: int = 96,
    font: str | Path | None = None,
) -> Path:
    """A full-frame transparent PNG with ``lines`` centred, the first line's top at ``y``.

    White fill, 3 px dark stroke, blurred shadow (the debut style). A line wider than the frame
    minus 30 px each side shrinks the whole block until it fits (DejaVu is wider than Arial
    Rounded, so the CI font would otherwise clip). Raises ``ValueError`` for no text.
    """
    lines = _clean(lines)
    fnt = _fit(lines, Path(font) if font else font_path(), size, STROKE_PX)
    layer = Image.new("RGBA", FRAME, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    pitch = round(fnt.size * LINE_PITCH)
    for i, line in enumerate(lines):
        x = (FRAME[0] - draw.textlength(line, font=fnt)) / 2
        draw.text(
            (x, y + i * pitch), line, font=fnt, fill=(255, 255, 255, 255),
            stroke_width=STROKE_PX, stroke_fill=STROKE_COLOUR,
        )  # fmt: skip
    return _save(_shadowed(layer), out)


# ---- the studio pill (owner 2026-10-06: the signature on-screen caption of every character) ------------------------------

PILL_FONT = Path(__file__).resolve().parents[2] / "assets" / "fonts" / "Figtree-Variable.ttf"  # OFL, committed: same on Mac and CI
PILL_WEIGHT = b"SemiBold"
PILL_SIZE = 54
PILL_MIN_SIZE = 40
PILL_MAX_TEXT_W = 780  # the text column; the pill adds the dots and the padding around it
PILL_MAX_LINES = 2
PILL_Y = 1300  # top of the pill: lower middle, clear of faces and of Instagram's bottom ~350 px of buttons
PILL_FILL = (14, 17, 22, 215)
PILL_RADIUS = 34
PILL_PAD_X = 40
PILL_PAD_Y = 25
PILL_TEXT_X = 96  # from the pill's left edge: the dots sit in front of the text
PILL_DOT_R = 10
PILL_DOT_GAP = 26  # centre to centre
SAFE_TOP, SAFE_BOTTOM = 250, FRAME[1] - 350


def _pill_font(size: int) -> ImageFont.FreeTypeFont:
    if PILL_FONT.is_file():
        fnt = ImageFont.truetype(str(PILL_FONT), size)
        try:
            fnt.set_variation_by_name(PILL_WEIGHT)
        except (OSError, ValueError):
            pass  # a static build of the font: its own weight
        return fnt
    return ImageFont.truetype(str(font_path()), size)


def _wrap(words: list[str], fnt: ImageFont.FreeTypeFont, width: int) -> list[str]:
    draw = ImageDraw.Draw(Image.new("L", (1, 1)))
    lines: list[str] = []
    for word in words:
        if lines and draw.textlength(f"{lines[-1]} {word}", font=fnt) <= width:
            lines[-1] = f"{lines[-1]} {word}"
        else:
            lines.append(word)
    return lines


def pill_png(lines: list[str], out: str | Path, y: int = PILL_Y) -> Path:
    """The studio pill: a full-frame transparent PNG with the text in a dark rounded pill, the two ODD EYES dots in front.

    The lines are joined and re-wrapped to at most ``PILL_MAX_LINES`` lines of ``PILL_MAX_TEXT_W`` px (the font shrinks to
    ``PILL_MIN_SIZE`` first; past that the block keeps its lines). The pill is centred, its top at ``y``, moved up if it
    would reach Instagram's bottom buttons. Drawn at 3x and scaled down so the curves and dots are smooth.
    Raises ``ValueError`` for no text.
    """
    words = " ".join(_clean(lines)).split()
    size = PILL_SIZE
    while True:
        fnt = _pill_font(size)
        wrapped = _wrap(words, fnt, PILL_MAX_TEXT_W)
        if len(wrapped) <= PILL_MAX_LINES or size <= PILL_MIN_SIZE:
            break
        size -= 2
    pitch = round(size * 1.26)
    probe = ImageDraw.Draw(Image.new("L", (1, 1)))
    text_w = max(probe.textlength(line, font=fnt) for line in wrapped)
    w, h = round(PILL_TEXT_X + text_w + PILL_PAD_X), pitch * len(wrapped) + 2 * PILL_PAD_Y
    x0 = (FRAME[0] - w) // 2
    y0 = max(SAFE_TOP, min(y, SAFE_BOTTOM - h))

    k = 3  # supersample the pill on its own canvas
    pill = Image.new("RGBA", (w * k, h * k), (0, 0, 0, 0))
    d = ImageDraw.Draw(pill)
    d.rounded_rectangle((0, 0, w * k - 1, h * k - 1), radius=PILL_RADIUS * k, fill=PILL_FILL)
    cy = h * k / 2
    for cx, colour in ((PILL_PAD_X * k, BUG_BLUE), ((PILL_PAD_X + PILL_DOT_GAP) * k, BUG_AMBER)):
        r = PILL_DOT_R * k
        d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(*colour, 255))
    big = _pill_font(size * k)
    for i, line in enumerate(wrapped):
        top = PILL_PAD_Y * k + i * pitch * k
        d.text((PILL_TEXT_X * k, top + (pitch - size) * k / 2), line, font=big, fill=(255, 255, 255, 255))
    pill = pill.resize((w, h), Image.LANCZOS)

    layer = Image.new("RGBA", FRAME, (0, 0, 0, 0))
    layer.alpha_composite(pill, (x0, y0))
    return _save(layer, out)


def title_png(text: str, out: str | Path, y: int = 1400, size: int = 96, font: str | Path | None = None) -> Path:
    """A title card: ``text`` in small caps (upper case), ivory brand serif, on a dark band.

    The band spans the frame and is vertically centred on ``y``; the text shrinks to fit.
    """
    text = _clean([text])[0].upper()
    fnt = _fit([text], Path(font) if font else serif_font_path(), size, 0)
    layer = Image.new("RGBA", FRAME, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    left, top, right, bottom = draw.textbbox((0, 0), text, font=fnt)
    pad = round(fnt.size * 0.45)
    draw.rectangle((0, y - (bottom - top) // 2 - pad, FRAME[0], y + (bottom - top) // 2 + pad), fill=TITLE_BAND)
    draw.text(
        ((FRAME[0] - (right - left)) / 2 - left, y - (bottom - top) / 2 - top), text, font=fnt, fill=(*IVORY, 255)
    )
    return _save(layer, out)


# ---- the ODD EYES bug and the sparkle ----------------------------------------------------------


def bug_png(out: str | Path) -> Path:
    """The two-dot ODD EYES mark, centred on (972, 268): ice-blue (viewer's left) and amber."""
    k = _SUPERSAMPLE
    layer = Image.new("RGBA", (FRAME[0] * k, FRAME[1] * k), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    cy = BUG_CENTER[1]
    for dx, colour in ((-BUG_DOT_SPACING // 2, BUG_BLUE), (BUG_DOT_SPACING // 2, BUG_AMBER)):
        cx = BUG_CENTER[0] + dx
        for radius, fill in (
            (BUG_OUTER_RADIUS, (255, 255, 255, 200)),
            (BUG_OUTER_RADIUS - BUG_OUTLINE_PX, (*colour, 235)),
        ):
            draw.ellipse(
                ((cx - radius) * k, (cy - radius) * k, (cx + radius) * k, (cy + radius) * k), fill=fill
            )
    return _save(layer.resize(FRAME, Image.Resampling.BOX), out)


def sparkle_png(out: str | Path, size: int = 320) -> Path:
    """A square four-point star (white) with a soft cool glow, ``size`` px, transparent around it."""
    k = _SUPERSAMPLE
    big, c = size * k, size * k / 2
    star = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    tip, waist = 0.47 * big, 0.044 * big
    ImageDraw.Draw(star).polygon(
        [(c, c - tip), (c + waist, c - waist), (c + tip, c), (c + waist, c + waist),
         (c, c + tip), (c - waist, c + waist), (c - tip, c), (c - waist, c - waist)],
        fill=(255, 255, 255, 255),
    )  # fmt: skip
    star = star.resize((size, size), Image.Resampling.BOX)

    radius = round(0.33 * size)
    ramp = Image.radial_gradient("L").resize((2 * radius, 2 * radius), Image.Resampling.BILINEAR)
    glow_alpha = ramp.point(lambda g: int(170 * (1 - g / 255) ** 1.2))
    glow = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    tint = Image.new("RGBA", glow_alpha.size, (200, 225, 255, 255))
    glow.paste(tint, (size // 2 - radius, size // 2 - radius), glow_alpha)
    return _save(Image.alpha_composite(glow, star), out)


# ---- sounds ------------------------------------------------------------------------------------


def _write_wav(out: str | Path, samples: list[float]) -> Path:
    """Mono ``samples`` (-1..1) as 48 kHz 16-bit stereo, the same signal in both channels."""
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    frames = b"".join(
        struct.pack("<hh", s16 := round(max(-1.0, min(1.0, s)) * 32767), s16) for s in samples
    )
    with wave.open(str(out), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(AUDIO_RATE)
        w.writeframes(frames)
    return out


def _tail_fade(samples: list[float], seconds: float) -> list[float]:
    n = min(len(samples), round(seconds * AUDIO_RATE))
    for i in range(n):
        samples[len(samples) - n + i] *= 1 - (i + 1) / n
    return samples


def sting_wav(out: str | Path) -> Path:
    """The 0.6 s closing chime: partials at 2093 / 3136 / 4186 Hz decaying at 6 / 8 / 10 per second."""
    n = round(STING_SECONDS * AUDIO_RATE)
    samples = [
        sum(g * math.sin(2 * math.pi * f * t) * math.exp(-d * t) for f, d, g in STING_PARTIALS)
        for t in (i / AUDIO_RATE for i in range(n))
    ]
    return _write_wav(out, _tail_fade(samples, 0.01))


def impact_wav(out: str | Path) -> Path:
    """A 0.4 s low thump: a sine sweeping 120 -> 45 Hz under a fast decay (peak 0.9)."""
    n = round(IMPACT_SECONDS * AUDIO_RATE)
    tau = 0.06
    samples = []
    for i in range(n):
        t = i / AUDIO_RATE
        phase = 2 * math.pi * (45 * t + 75 * tau * (1 - math.exp(-t / tau)))
        attack = min(1.0, t / 0.003)
        samples.append(0.9 * attack * math.exp(-11 * t) * math.sin(phase))
    return _write_wav(out, _tail_fade(samples, 0.02))
