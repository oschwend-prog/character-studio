"""Overlay graphics (PIL PNGs) and synthesised sounds for the master timeline.

ffmpeg here has no ``drawtext``, so every piece of text or graphics is a full-frame (1080x1920)
transparent PNG that ``master`` lays over the video with ``overlay``. The look is the debut's:
white text, a 3 px dark stroke and a blurred drop shadow; the ODD EYES bug is two dots (the
character's right eye ice-blue ``#8FD3FF`` on the viewer's left, the left eye amber ``#FFB040``)
top-right at (972, 268); the sparkle is a four-point star with a soft glow.

System fonts are not committed (their licences). ``font_path()`` is Arial Rounded Bold on macOS and
otherwise whatever ``fc-match`` resolves ``DejaVu Sans:bold`` to (the CI image installs
``fonts-dejavu-core``); ``serif_font_path()`` is the same idea for the title card (Georgia Bold /
DejaVu Serif Bold). The caption pill is the exception: its fonts are OFL files committed in
``assets/fonts/`` with their licences (Figtree for the default pill; Playfair Display, Cormorant SC,
Oswald and Anton for the per-character kits), so it looks the same on the Mac and in the cloud.

The two sounds are written with the standard library only: a 0.6 s three-partial chime (the
sting that ends every master) and a short low thump (the ``impact_sfx`` enhancement). Both are
48 kHz 16-bit stereo, the master's own format.
"""

from __future__ import annotations

import dataclasses
import math
import re
import struct
import subprocess
import sys
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

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

FONT_DIR = Path(__file__).resolve().parents[2] / "assets" / "fonts"  # OFL files, committed with their licences: the same on Mac and CI
PILL_FONT = FONT_DIR / "Figtree-Variable.ttf"  # the default pill's font
PILL_SIZE = 54
PILL_MIN_SIZE = 40
PILL_MAX_TEXT_W = 780  # the text column; the pill adds the dots and the padding around it
PILL_MAX_LINES = 2
PILL_Y = 1300  # top of the pill: lower middle, clear of faces and of Instagram's bottom ~350 px of buttons
PILL_PAD_X = 40
PILL_PAD_Y = 25
PILL_TEXT_X = 96  # from the pill's left edge: the dots sit in front of the text
PILL_DOT_R = 10
PILL_DOT_GAP = 26  # centre to centre
PILL_RING_PX = 2  # the ring round each dot on a light pill
SAFE_TOP, SAFE_BOTTOM = 250, FRAME[1] - 350

PILL_CASES = ("none", "upper", "smallcaps")


@dataclass(frozen=True)
class PillStyle:
    """How a character's caption pill looks (the kit's ``style.pill`` in ``characters/<slug>/refs.json``).

    ``DEFAULT_PILL`` (all defaults) is the studio's dark pill, drawn exactly as before the kits existed.

    * ``fill`` / ``fill_alpha`` / ``text``: ``#RRGGBB`` colours and the fill's opacity (0-255).
    * ``font`` is a file in ``assets/fonts/``; ``weight`` the named instance of a variable font (``Medium``, ``Bold``; a static
      font ignores it).
    * ``case``: ``none`` as written, ``upper``, or ``smallcaps`` (the text as written, set in a small-caps face such as Cormorant SC).
    * ``tracking``: extra pixels between letters (at 1x). ``border``: ``(colour, width px)`` rule just inside the edge.
    * ``tilt_deg``: counter-clockwise when negative (the pill rises to the right), as in a design tool; ``shear``: forward lean
      (the top moves right by ``shear`` px per px of height). ``block``: ``(colour, dx, dy)``, a solid copy of the pill behind it.
    The two ODD EYES dots are always drawn; on a light fill (luminance over 50%) each gets a 2 px ring in the text colour.
    """

    fill: str = "#0E1116"
    fill_alpha: int = 215
    text: str = "#FFFFFF"
    font: str = "Figtree-Variable.ttf"
    weight: str | None = "SemiBold"
    radius: int = 34
    border: tuple[str, int] | None = None
    case: Literal["none", "upper", "smallcaps"] = "none"
    tracking: int = 0
    tilt_deg: float = 0.0
    shear: float = 0.0
    block: tuple[str, int, int] | None = None


DEFAULT_PILL = PillStyle()
_HEX = re.compile(r"#[0-9A-Fa-f]{6}")


def _rgb(colour: str) -> tuple[int, int, int]:
    return int(colour[1:3], 16), int(colour[3:5], 16), int(colour[5:7], 16)


def _luminance(colour: str) -> float:
    """Rec. 709 luma of an ``#RRGGBB`` colour, 0 (black) to 1 (white)."""
    r, g, b = _rgb(colour)
    return (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255


def _whole(value: Any, low: int, high: int) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and low <= value <= high


def _number(value: Any, low: float, high: float) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and low <= value <= high


def pill_style(style: dict[str, Any] | None) -> PillStyle:
    """The ``PillStyle`` of a kit's ``style.pill`` object; ``None`` (a character with no kit) is ``DEFAULT_PILL``.

    Strict: an unknown key, a colour that is not ``#RRGGBB``, a number out of range or a font that is not in ``assets/fonts/``
    raises ``ValueError`` (the seed turns it into an error naming the file).
    """
    if style is None:
        return DEFAULT_PILL
    if not isinstance(style, dict):
        raise ValueError(f"pill must be an object, got {style!r:.40}")
    names = [f.name for f in dataclasses.fields(PillStyle)]
    unknown = sorted(set(style) - set(names))
    if unknown:
        raise ValueError(f"pill has no key {', '.join(unknown)} (the keys are {', '.join(names)})")

    def colour(key: str, value: Any) -> str:
        if not (isinstance(value, str) and _HEX.fullmatch(value)):
            raise ValueError(f"pill {key} must be a #RRGGBB colour, got {value!r:.40}")
        return value

    fields = dict(style)
    for key in ("fill", "text"):
        if key in fields:
            fields[key] = colour(key, fields[key])
    if "fill_alpha" in fields and not _whole(fields["fill_alpha"], 0, 255):
        raise ValueError(f"pill fill_alpha must be a whole number from 0 to 255, got {fields['fill_alpha']!r:.40}")
    if "radius" in fields and not _whole(fields["radius"], 0, 200):
        raise ValueError(f"pill radius must be a whole number from 0 to 200, got {fields['radius']!r:.40}")
    if "tracking" in fields and not _whole(fields["tracking"], 0, 20):
        raise ValueError(f"pill tracking must be a whole number of pixels from 0 to 20, got {fields['tracking']!r:.40}")
    if "tilt_deg" in fields:
        if not _number(fields["tilt_deg"], -15, 15):
            raise ValueError(f"pill tilt_deg must be a number from -15 to 15, got {fields['tilt_deg']!r:.40}")
        fields["tilt_deg"] = float(fields["tilt_deg"])
    if "shear" in fields:
        if not _number(fields["shear"], -0.5, 0.5):
            raise ValueError(f"pill shear must be a number from -0.5 to 0.5, got {fields['shear']!r:.40}")
        fields["shear"] = float(fields["shear"])
    if "case" in fields and fields["case"] not in PILL_CASES:
        raise ValueError(f"pill case must be one of {', '.join(PILL_CASES)}, got {fields['case']!r:.40}")
    if "weight" in fields and fields["weight"] is not None and not (isinstance(fields["weight"], str) and fields["weight"].strip()):
        raise ValueError(f"pill weight must be a named weight such as Medium or null, got {fields['weight']!r:.40}")
    if "font" in fields:
        font = fields["font"]
        if not (isinstance(font, str) and font == Path(font).name and (FONT_DIR / font).is_file()):
            raise ValueError(f"pill font {font!r:.60} is not a file in assets/fonts/")
    if fields.get("border") is not None:
        border = fields["border"]
        if not (isinstance(border, (list, tuple)) and len(border) == 2 and _whole(border[1], 1, 12)):
            raise ValueError(f"pill border must be [#RRGGBB, width 1-12], got {border!r:.60}")
        fields["border"] = (colour("border", border[0]), border[1])
    if fields.get("block") is not None:
        block = fields["block"]
        if not (isinstance(block, (list, tuple)) and len(block) == 3 and _whole(block[1], -40, 40) and _whole(block[2], -40, 40)):
            raise ValueError(f"pill block must be [#RRGGBB, dx, dy] with the offsets within 40 px, got {block!r:.60}")
        fields["block"] = (colour("block", block[0]), block[1], block[2])
    return PillStyle(**fields)


def _apply_weight(fnt: ImageFont.FreeTypeFont, weight: str | None) -> bool:
    """Select a variable font's named instance (``Medium``, or ``Medium Italic`` in an italic file); False when it did not take.

    A static font has no instances: it keeps its own weight, which is not an error.
    """
    if not weight:
        return False
    for name in (weight, f"{weight} Italic"):
        try:
            fnt.set_variation_by_name(name)
            return True
        except (OSError, ValueError):
            continue
    return False


def _pill_font(size: int, style: PillStyle = DEFAULT_PILL) -> ImageFont.FreeTypeFont:
    path = FONT_DIR / style.font
    if path.is_file():
        fnt = ImageFont.truetype(str(path), size)
        _apply_weight(fnt, style.weight)
        return fnt
    return ImageFont.truetype(str(font_path()), size)


def _text_w(text: str, fnt: ImageFont.FreeTypeFont, tracking: int = 0) -> float:
    probe = ImageDraw.Draw(Image.new("L", (1, 1)))
    return probe.textlength(text, font=fnt) + max(len(text) - 1, 0) * tracking


def _wrap(words: list[str], fnt: ImageFont.FreeTypeFont, width: int, tracking: int = 0) -> list[str]:
    lines: list[str] = []
    for word in words:
        if lines and _text_w(f"{lines[-1]} {word}", fnt, tracking) <= width:
            lines[-1] = f"{lines[-1]} {word}"
        else:
            lines.append(word)
    return lines


def _cap_mid(fnt: ImageFont.FreeTypeFont) -> float:
    """Distance from the top of the text box (the ``la`` anchor) to the middle of the capitals."""
    _, top, _, bottom = fnt.getbbox("H", anchor="la")
    return (top + bottom) / 2


def _lift(style: PillStyle, size_k: int, fnt: ImageFont.FreeTypeFont) -> float:
    """Pixels (at 3x) to move the text down so each font's capitals sit where Figtree's do in the studio pill.

    Fonts differ in how much room they leave above and below the capitals, so the same box would seat Oswald or Playfair low.
    Mixed-case text keeps Figtree's seat (a little low: the descenders hang below); all-caps and small-caps text, which have none,
    are centred on the line. The default pill is untouched (0), pixel for pixel.
    """
    if style.font == DEFAULT_PILL.font and style.case == "none":
        return 0.0
    seat = size_k / 2  # the middle of the line box, measured from the text box's top
    drop = _cap_mid(_pill_font(size_k, DEFAULT_PILL)) - seat if style.case == "none" else 0.0
    return seat + drop - _cap_mid(fnt)


def _draw_line(
    d: ImageDraw.ImageDraw, xy: tuple[float, float], line: str, fnt: ImageFont.FreeTypeFont, fill: tuple[int, ...], tracking: float
) -> None:
    """One line of text; with ``tracking`` each letter is placed ``tracking`` px further than the font's own advance."""
    if not tracking:
        d.text(xy, line, font=fnt, fill=fill)
        return
    x, y = xy
    for i, ch in enumerate(line):
        d.text((x + d.textlength(line[:i], font=fnt) + i * tracking, y), ch, font=fnt, fill=fill)


def _with_block(pill: Image.Image, style: PillStyle, k: int) -> Image.Image:
    """``pill`` on a canvas grown by the block's offset, a solid copy of its shape behind it (visible only beyond its edge)."""
    colour, dx, dy = style.block  # type: ignore[misc]
    w, h = pill.size
    gx, gy = abs(dx) * k, abs(dy) * k
    size = (w + gx, h + gy)
    pill_at, block_at = (max(-dx, 0) * k, max(-dy, 0) * k), (max(dx, 0) * k, max(dy, 0) * k)

    def shape(at: tuple[int, int]) -> Image.Image:
        mask = Image.new("L", size, 0)
        ImageDraw.Draw(mask).rounded_rectangle(
            (at[0], at[1], at[0] + w - 1, at[1] + h - 1), radius=style.radius * k, fill=255
        )
        return mask

    back = Image.new("RGBA", size, (*_rgb(colour), 0))
    back.putalpha(ImageChops.subtract(shape(block_at), shape(pill_at)))  # knocked out under the pill: its fill stays pure
    front = Image.new("RGBA", size, (0, 0, 0, 0))
    front.alpha_composite(pill, pill_at)
    return Image.alpha_composite(back, front)


def _lean_and_tilt(img: Image.Image, shear: float, tilt_deg: float) -> Image.Image:
    """Shear (the top moves right by ``shear`` px per px of height) then rotate (negative = counter-clockwise), canvas grown to fit.

    Done on premultiplied pixels, so the transparent edge does not darken the soft rim.
    """
    img = img.convert("RGBa")
    if shear:
        w, h = img.size
        off = math.ceil(abs(shear) * h / 2)
        img = img.transform((w + 2 * off, h), Image.AFFINE, (1, shear, -off - shear * h / 2, 0, 1, 0), resample=Image.BICUBIC)
    if tilt_deg:
        img = img.rotate(-tilt_deg, resample=Image.BICUBIC, expand=True)  # PIL turns counter-clockwise for a positive angle
    return img.convert("RGBA")


def pill_png(lines: list[str], out: str | Path, y: int = PILL_Y, style: PillStyle = DEFAULT_PILL) -> Path:
    """The studio pill: a full-frame transparent PNG with the text in a rounded pill, the two ODD EYES dots in front.

    The lines are joined and re-wrapped to at most ``PILL_MAX_LINES`` lines of ``PILL_MAX_TEXT_W`` px (the font shrinks to
    ``PILL_MIN_SIZE`` first; past that the block keeps its lines). The pill is centred, its top at ``y``, moved up if it
    would reach Instagram's bottom buttons. Drawn at 3x and scaled down so the curves and dots are smooth. ``style`` is the
    character's kit (``PillStyle``); the default is the studio's dark pill. A tilted or sheared pill (or one with a block) is
    placed by what it covers: that whole shape stays between ``SAFE_TOP`` and ``SAFE_BOTTOM``.
    Raises ``ValueError`` for no text.
    """
    words = " ".join(_clean(lines)).split()
    if style.case == "upper":
        words = [word.upper() for word in words]
    size = PILL_SIZE
    while True:
        fnt = _pill_font(size, style)
        wrapped = _wrap(words, fnt, PILL_MAX_TEXT_W, style.tracking)
        if len(wrapped) <= PILL_MAX_LINES or size <= PILL_MIN_SIZE:
            break
        size -= 2
    pitch = round(size * 1.26)
    text_w = max(_text_w(line, fnt, style.tracking) for line in wrapped)
    w, h = round(PILL_TEXT_X + text_w + PILL_PAD_X), pitch * len(wrapped) + 2 * PILL_PAD_Y
    ink = (*_rgb(style.text), 255)

    k = 3  # supersample the pill on its own canvas
    pill = Image.new("RGBA", (w * k, h * k), (0, 0, 0, 0))
    d = ImageDraw.Draw(pill)
    shape = (0, 0, w * k - 1, h * k - 1)
    d.rounded_rectangle(shape, radius=style.radius * k, fill=(*_rgb(style.fill), style.fill_alpha))
    if style.border:
        d.rounded_rectangle(shape, radius=style.radius * k, outline=(*_rgb(style.border[0]), 255), width=style.border[1] * k)
    cy = h * k / 2
    ring = PILL_RING_PX * k if _luminance(style.fill) > 0.5 else 0
    for cx, colour in ((PILL_PAD_X * k, BUG_BLUE), ((PILL_PAD_X + PILL_DOT_GAP) * k, BUG_AMBER)):
        r = PILL_DOT_R * k
        if ring:  # on a light pill the pale blue and amber would sink into the fill: edge them in the text colour
            d.ellipse((cx - r - ring, cy - r - ring, cx + r + ring, cy + r + ring), fill=ink)
        d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(*colour, 255))
    big = _pill_font(size * k, style)
    lift = _lift(style, size * k, big)
    for i, line in enumerate(wrapped):
        top = PILL_PAD_Y * k + i * pitch * k
        _draw_line(d, (PILL_TEXT_X * k, top + (pitch - size) * k / 2 + lift), line, big, ink, style.tracking * k)

    if style.block or style.tilt_deg or style.shear:
        if style.block:
            pill = _with_block(pill, style, k)
        pill = _lean_and_tilt(pill, style.shear, style.tilt_deg)
        pill = pill.resize((math.ceil(pill.width / k), math.ceil(pill.height / k)), Image.LANCZOS)
        pill = pill.crop(pill.getchannel("A").getbbox())  # place what is actually covered, not the empty canvas round it
        w, h = pill.size
    else:
        pill = pill.resize((w, h), Image.LANCZOS)
    x0 = (FRAME[0] - w) // 2
    y0 = max(SAFE_TOP, min(y, SAFE_BOTTOM - h))

    layer = Image.new("RGBA", FRAME, (0, 0, 0, 0))
    layer.alpha_composite(pill, (x0, y0))
    return _save(layer, out)


def entrance_png(png: str | Path, out: str | Path, *, alpha: float = 1.0, dy: int = 0, scale: float = 1.0) -> Path:
    """One frame of a caption's entrance: the overlay ``png`` (full frame) with what it shows scaled by ``scale`` about its own
    centre, its opacity times ``alpha`` (a pixel that shows stays at least 1, so the frame covers the same box) and moved
    ``dy`` px down. Written to ``out`` (full frame); what falls outside the frame is cut.
    """
    with Image.open(png) as img:
        img = img.convert("RGBA")
        box = img.getchannel("A").getbbox() or (0, 0, 1, 1)
        shown = img.crop(box)
    if scale != 1.0:
        shown = shown.resize((max(1, round(shown.width * scale)), max(1, round(shown.height * scale))), Image.LANCZOS)
    if alpha < 1.0:
        shown.putalpha(shown.getchannel("A").point(lambda a: 0 if a == 0 else max(1, round(a * alpha))))
    x0 = round((box[0] + box[2]) / 2 - shown.width / 2)
    y0 = round((box[1] + box[3]) / 2 - shown.height / 2) + dy
    layer = Image.new("RGBA", FRAME, (0, 0, 0, 0))
    layer.paste(shown, (x0, y0))  # a straight copy (alpha too) onto the empty frame; paste clips at the edges
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
