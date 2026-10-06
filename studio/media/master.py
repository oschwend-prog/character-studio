"""The master timeline: a dance clip + an eye close-up + a beat -> the delivery MP4.

This is the pipeline proven on Biscuit's debut, as code. For a spec with a close-up (``closeup``):

1. **intro** (0.8 s): a slow push-in on the close-up, centred between the eyes (``closeup_center``).
2. **dance**: the generation normalised to 1080x1920 @ 30 fps.
3. **outro** (0.7 s): the close-up held at zoom 1.30 with a glint (the sparkle) on the ice-blue eye
   (``blue_eye_xy``, in screen pixels at the outro zoom).
4. The three are concatenated, then PNG overlays go on: hook line 1 over the intro, hook line 2 until
   ``hook2_until_s``, both in the studio pill (``overlays.pill_png``, owner 2026-10-06: the signature caption of every
   character), the two-dot ODD EYES bug throughout (ffmpeg here has no ``drawtext``).
5. **audio**: the source beat from ``audio_offset_s``, faded out into the outro, the 0.6 s sting just
   after the dance ends, then a two-pass ``loudnorm`` to -14 LUFS with a **-1.5 dBTP** ceiling (the
   AAC encode adds ~0.1 dB of true peak, and the delivery spec is <= -1.0), encoded AAC 320k / 48 kHz.

With ``closeup=None`` there is no intro, outro, sting or fade (an eye loop builds its own); the clip
is the dance with overlays (``hook1`` has no intro to sit on, so it is not shown) and the normalised
beat. Overlay PNGs are cropped to their visible box before ffmpeg sees them: decoding and blending
full-frame RGBA stills per frame was half the encode time.

**Enhancements** (``MasterSpec.enhancements``, a list of dicts) are small, separately testable
steps, each a filter fragment or an overlay spec:

``{"type": "slowmo", "at_s", "dur_s", "factor"}``
    The span plays at ``factor`` x speed (0 < factor < 1; 0.5 is half speed), so the master gets
    longer by ``dur_s * (1/factor - 1)``. Video only: the beat is not touched and keeps its own
    time, so after the span the picture runs behind the beat by that amount, and the sting follows
    the picture, not the beat. Put a slowmo late (or accept the drift); it is a punctuation mark.
``{"type": "zoom_hit", "at_s", "scale": 1.06}``
    A 0.25 s punch-in (1 -> ``scale`` -> 1) on the picture; overlays are not zoomed.
``{"type": "impact_sfx", "at_s"}``
    A synthesised low thump mixed in at -6 dB.
``{"type": "text_pop", "at_s", "dur_s", "text"}``
    ``text`` (the hook style, lower third) on screen for ``dur_s``.
``{"type": "title_card", "text"}``
    ``text`` in the brand serif on a dark band, for the first 0.6 s.

Every ``at_s`` is a moment of the *unstretched* timeline (the intro starts at 0), so slowmo spans
do not move the other enhancements off their beats; ``out_time`` maps it onto the finished
master. The hook windows and the bug are already on the finished timeline.

CLI: ``studio master build --spec <json> [--clip <id>]`` builds, runs the master QA and prints JSON; it
exits 1 when the master has QA problems (the JSON says which) and 2 for anything the caller must fix.

**Music** (``MasterSpec.music``, owner decisions 2026-10-05): ``original`` is the default of a Drop-in: it keeps the
Genjutsu output's own audio (the clip's original soundtrack) as ``audio``, mixed with the sting and loudness-normalised
to -14 LUFS like any beat ("Drop-ins keep the original clip audio by default; never ADD third-party audio we sourced
ourselves"). ``ai_beat`` mixes ``audio`` (a Seedance beat render of our own, or a Recreate clip's synthetic driver) the
same way. ``in_app`` builds a **silent** AAC track (48 kHz stereo, no beat, no sting, no impact sfx; ``audio`` is not
needed): the owner adds the song in the Instagram app, the fallback when Instagram mutes a chart song, and the master
QA (``check_master(silent=True)``) skips the loudness rule for silence. A spec with no ``music`` is ``ai_beat``, what
every spec written before this decision meant.

**Never add the source's audio under a clip that did not carry it; keep the clip's own when ``music`` is original.**
The generation of a Drop-in clip (and a library or inbox source file) carries the source's soundtrack. ``master
build`` therefore refuses (exit 2, nothing rendered) when ``audio`` is the same file as ``dance`` (same path or same
bytes) or a file under an ``inbox`` folder (the owner's source drop), unless the clip is a ``recreate`` clip made
from a ``synthetic`` driver (Seedance renders it with our own beat in it), or the clip is a ``dropin`` clip marked
``features.music == "original"`` (and its pick, ``features.fav_id``, does not say the owner chose another music in
``proposal.owner_music``). An inbox file is refused even then: only the generation's own audio, never the raw
source file. The clip comes from ``--clip <id>`` or ``clip_id`` in the spec (both: they must agree); without one the
exception cannot be proved, so it does not apply. Any other ``audio`` file is not looked at: a Seedance beat render
of its own (``seedance_2_5`` t2v with audio) is the way to get an ``ai_beat``.

``studio master mux-audio`` puts a source clip's audio back under a Genjutsu output that lost it, aligned to the
trimmed window (``studio.media.clipwork``).

``studio master upload <clip> <file>`` is the last step: it re-checks the file against the master spec
(``--loop`` for an eye loop), uploads it to bucket ``clips`` at ``<character>/<clip id>.mp4`` (what
publishing and the terminal sign) and sets ``clip.master_path``. A file that misses the spec is not
uploaded (exit 1, the JSON lists the problems); the clip's state is left to ``clip set --state``.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import re
import shutil
import subprocess
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated, Any

import typer
from PIL import Image

from studio.cli_support import emit, fail, open_storage, open_store
from studio.clips import set_fields
from studio.media import clipwork, overlays
from studio.media.qa import QAError, check_master, probe
from studio.models import MUSIC_ARMS, Clip, Mode, Source, SourceKind
from studio.storage import Storage, StorageError
from studio.store import Store

MASTER_BUCKET = "clips"  # the bucket studio.publish.base signs masters from
WIDTH, HEIGHT = 1080, 1920
FPS = 30
ZOOM_HIT_SECONDS = 0.25
TITLE_CARD_SECONDS = 0.6
TEXT_POP_Y = 1180
TEXT_POP_SIZE = 110
SPARKLE_PX = 280  # the 320 px sparkle PNG is shown at this size on the outro
BEAT_FADE_SECONDS = 0.4
FADE_LEAD_SECONDS = 0.35  # the fade starts this long before the dance ends
STING_LAG_SECONDS = 0.05  # the sting starts this long after the dance ends
STING_GAIN = 0.9
IMPACT_GAIN_DB = -6
LOUDNORM = "I=-14:TP=-1.5:LRA=11"
INTERMEDIATE_CRF = 12
_EPS = 1e-6


class MasterError(RuntimeError):
    """ffmpeg failed, or the audio could not be measured."""


class MasterRejected(Exception):
    """The file does not meet the master spec, so it was not uploaded. ``problems`` says why."""

    def __init__(self, problems: list[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = problems


@dataclass
class MasterSpec:
    """Everything ``build_master`` needs. Paths may be ``str``; relative ones resolve from the cwd.

    ``closeup_center`` / ``blue_eye_xy`` are pixels of the 1080x1920 close-up (the centre of the
    push-in) and of the screen at the outro zoom (where the glint sits); unused without a close-up.
    ``preset`` is the x264 preset (``slow`` for real masters; tests use ``veryfast``).
    """

    dance: Path
    closeup: Path | None
    closeup_center: tuple[int, int]
    blue_eye_xy: tuple[int, int]
    hook1: list[str]
    hook2: list[str]
    hook2_until_s: float
    audio: Path | None  # None only with music "in_app" (a silent track is built instead)
    audio_offset_s: float
    out: Path
    intro_s: float = 0.8
    outro_s: float = 0.7
    intro_zoom: float = 0.30
    outro_zoom: float = 1.30
    enhancements: list[dict[str, Any]] = field(default_factory=list)
    preset: str = "slow"
    clip_id: str | None = None  # the clip this master is for: lets ``master build`` judge the audio source
    music: str = "ai_beat"  # ai_beat | in_app | original (see the module docstring)


# ---- enhancements: parsing ---------------------------------------------------------------------


@dataclass(frozen=True)
class Slowmo:
    at_s: float
    dur_s: float
    factor: float


@dataclass(frozen=True)
class ZoomHit:
    at_s: float
    scale: float = 1.06


@dataclass(frozen=True)
class ImpactSfx:
    at_s: float


@dataclass(frozen=True)
class TextPop:
    at_s: float
    dur_s: float
    text: str


@dataclass(frozen=True)
class TitleCard:
    text: str


Enhancement = Slowmo | ZoomHit | ImpactSfx | TextPop | TitleCard

_KINDS: dict[str, type[Enhancement]] = {
    "slowmo": Slowmo,
    "zoom_hit": ZoomHit,
    "impact_sfx": ImpactSfx,
    "text_pop": TextPop,
    "title_card": TitleCard,
}


def _number(kind: str, key: str, value: Any, *, low: float, strict: bool = False, high: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"{kind}: {key} must be a number, got {value!r}")
    bad_low = value <= low if strict else value < low
    if bad_low or (high is not None and value >= high):
        want = f"> {low:g}" if strict else f">= {low:g}"
        raise ValueError(f"{kind}: {key} must be {want}{f' and < {high:g}' if high is not None else ''}, got {value:g}")
    return value


def _parse_one(item: dict[str, Any]) -> Enhancement:
    kind = item.get("type") if isinstance(item, dict) else None
    if kind is None:
        raise ValueError(f"an enhancement needs a 'type' (one of {', '.join(_KINDS)}): {item!r}")
    cls = _KINDS.get(kind)
    if cls is None:
        raise ValueError(f"unknown enhancement type {kind!r} (one of {', '.join(_KINDS)})")
    fields = {f.name: f for f in dataclasses.fields(cls)}
    extra = sorted(set(item) - set(fields) - {"type"})
    if extra:
        raise ValueError(f"{kind}: unknown key(s) {', '.join(extra)}")
    missing = [n for n, f in fields.items() if f.default is dataclasses.MISSING and n not in item]
    if missing:
        raise ValueError(f"{kind}: missing {', '.join(missing)}")
    args = {n: item[n] for n in fields if n in item}
    if "at_s" in args:
        args["at_s"] = _number(kind, "at_s", args["at_s"], low=0)
    if "dur_s" in args:
        args["dur_s"] = _number(kind, "dur_s", args["dur_s"], low=0, strict=True)
    if "factor" in args:
        args["factor"] = _number(kind, "factor", args["factor"], low=0, strict=True, high=1)
    if "scale" in args:
        args["scale"] = _number(kind, "scale", args["scale"], low=1, strict=True)
    if "text" in args and (not isinstance(args["text"], str) or not args["text"].strip()):
        raise ValueError(f"{kind}: text must be a non-empty string")
    return cls(**args)


def parse_enhancements(raw: Sequence[dict[str, Any]]) -> list[Enhancement]:
    """Validate and type the ``enhancements`` dicts. Raises ``ValueError`` naming the bad item."""
    items = [_parse_one(item) for item in raw]
    spans = sorted((e for e in items if isinstance(e, Slowmo)), key=lambda s: s.at_s)
    for a, b in zip(spans, spans[1:], strict=False):
        if b.at_s < a.at_s + a.dur_s - _EPS:
            raise ValueError(f"slowmo spans overlap: {a.at_s:g}+{a.dur_s:g} and {b.at_s:g}")
    return items


# ---- enhancements: time maths and filter fragments ---------------------------------------------


def out_time(t: float, spans: Sequence[Slowmo]) -> float:
    """Where moment ``t`` of the unstretched timeline lands once the slowmo ``spans`` are applied."""
    return t + sum(min(max(t - s.at_s, 0.0), s.dur_s) * (1 / s.factor - 1) for s in spans)


def _check_span_fits(s: Slowmo, total_s: float) -> None:
    if s.at_s + s.dur_s > total_s + _EPS:
        raise ValueError(f"slowmo {s.at_s:g}+{s.dur_s:g} s runs past the end of the {total_s:.2f} s clip")


def slowmo_filter(src: str, dst: str, spans: Sequence[Slowmo], total_s: float) -> str:
    """Stretch each span of ``[src]`` (``total_s`` long) by 1/factor, rejoin, resample to 30 fps."""
    segments: list[tuple[float, float | None, float | None]] = []  # start, end (None = to the end), factor
    cursor = 0.0
    for s in sorted(spans, key=lambda s: s.at_s):
        _check_span_fits(s, total_s)
        if s.at_s > cursor + _EPS:
            segments.append((cursor, s.at_s, None))
        segments.append((s.at_s, s.at_s + s.dur_s, s.factor))
        cursor = s.at_s + s.dur_s
    if total_s - cursor > _EPS:
        segments.append((cursor, None, None))

    def trim(start: float, end: float | None) -> str:
        return f"trim=start={start:g}" + (f":end={end:g}" if end is not None else "")

    def cut(start: float, end: float | None, factor: float | None) -> str:
        stretch = f"(PTS-STARTPTS)/{factor:g}" if factor else "PTS-STARTPTS"
        return f"{trim(start, end)},setpts={stretch}"

    if len(segments) == 1:
        return f"[{src}]{cut(*segments[0])},fps={FPS}[{dst}]"
    n = len(segments)
    split = f"[{src}]split={n}" + "".join(f"[sm{i}]" for i in range(n))
    cuts = [f"[sm{i}]{cut(*seg)}[sw{i}]" for i, seg in enumerate(segments)]
    join = "".join(f"[sw{i}]" for i in range(n)) + f"concat=n={n}:v=1:a=0,fps={FPS}[{dst}]"
    return ";".join([split, *cuts, join])


def zoom_hit_filter(src: str, dst: str, hit: ZoomHit) -> str:
    """A 0.25 s punch-in: scale 1 -> ``hit.scale`` -> 1 along a half sine, cropped back to frame."""
    z = f"1+{hit.scale - 1:g}*sin(PI*clip((t-{hit.at_s:g})/{ZOOM_HIT_SECONDS:g},0,1))"
    return (
        f"[{src}]scale=w='trunc({WIDTH}*({z})/2)*2':h='trunc({HEIGHT}*({z})/2)*2':eval=frame:flags=bicubic,"
        f"crop={WIDTH}:{HEIGHT}[{dst}]"
    )


def impact_filter(index: int, at_s: float, dst: str) -> str:
    """Delay input ``index`` (the thump) to ``at_s`` and attenuate it by 6 dB."""
    ms = round(at_s * 1000)
    return f"[{index}:a]adelay={ms}|{ms},volume={IMPACT_GAIN_DB}dB[{dst}]"


@dataclass(frozen=True)
class Overlay:
    """A PNG placed at (``x``, ``y``), shown from ``start`` to ``end`` (``None``: to the end)."""

    png: Path
    start: float = 0.0
    end: float | None = None
    x: int = 0
    y: int = 0


def overlay_filter(src: str, index: int, dst: str, ov: Overlay) -> str:
    """Lay input ``index`` (a single-frame PNG, repeated by overlay) over ``[src]`` in its window."""
    options = []
    if ov.x or ov.y:
        options += [f"x={ov.x}", f"y={ov.y}"]
    if ov.end is not None:
        options.append(f"enable='between(t,{ov.start:g},{ov.end:g})'")
    elif ov.start > 0:
        options.append(f"enable='gte(t,{ov.start:g})'")
    return f"[{src}][{index}:v]overlay={':'.join(options)}[{dst}]" if options else f"[{src}][{index}:v]overlay[{dst}]"


# ---- running ffmpeg ----------------------------------------------------------------------------


def _ffmpeg(*args: str | Path | int, capture: bool = False, timeout: float = 1800) -> str:
    """Run ffmpeg quietly; return stderr when ``capture`` (for loudnorm's JSON)."""
    cmd = ["ffmpeg", "-hide_banner", "-nostdin", "-y", *(["-nostats"] if capture else ["-loglevel", "error"]),
           *map(str, args)]  # fmt: skip
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
            stdin=subprocess.DEVNULL, timeout=timeout, check=False,
        )  # fmt: skip
    except FileNotFoundError as e:
        raise MasterError("ffmpeg not found: install ffmpeg") from e
    except subprocess.TimeoutExpired as e:
        raise MasterError(f"ffmpeg timed out after {timeout:.0f} s") from e
    if proc.returncode != 0:
        tail = " | ".join(proc.stderr.strip().splitlines()[-4:]) or "no output"
        raise MasterError(f"ffmpeg failed ({proc.returncode}): {tail}")
    return proc.stderr


def _duration(path: Path) -> float:
    try:
        return probe(path, loudness=False).duration_s
    except QAError as e:
        raise MasterError(str(e)) from e


# ---- video stages ------------------------------------------------------------------------------


def _frames(seconds: float) -> int:
    return max(round(seconds * FPS), 1)


def _x264(preset: str) -> list[str]:
    return ["-c:v", "libx264", "-crf", str(INTERMEDIATE_CRF), "-preset", preset, "-r", str(FPS)]


def _pan(cx: int, cy: int) -> str:
    """zoompan centring: keep source point (cx, cy) in the middle of the frame."""
    return f"x='{cx}-(iw/zoom/2)':y='{cy}-(ih/zoom/2)'"


def _intro(spec: MasterSpec, closeup: Path, out: Path) -> Path:
    n = _frames(spec.intro_s)
    cx, cy = spec.closeup_center
    vf = (
        f"scale={WIDTH}:{HEIGHT}:flags=lanczos,setsar=1,"
        f"zoompan=z='1+{spec.intro_zoom:g}*on/{max(n - 1, 1)}':{_pan(cx, cy)}:d={n}:s={WIDTH}x{HEIGHT}:fps={FPS},"
        "format=yuv420p"
    )
    _ffmpeg("-loop", "1", "-i", closeup, "-vf", vf, "-frames:v", n, *_x264(spec.preset), out)
    return out


def _outro(spec: MasterSpec, closeup: Path, sparkle: Path, out: Path) -> Path:
    cx, cy = spec.closeup_center
    bx, by = spec.blue_eye_xy
    half = SPARKLE_PX // 2
    fade_out_at = max(spec.outro_s - 0.30, 0.25)
    graph = (
        f"[0]scale={WIDTH}:{HEIGHT}:flags=lanczos,setsar=1,"
        f"zoompan=z={spec.outro_zoom:g}:{_pan(cx, cy)}:d=1:s={WIDTH}x{HEIGHT}:fps={FPS}[c];"
        f"[1]format=rgba,scale={SPARKLE_PX}:{SPARKLE_PX},fade=in:st=0.10:d=0.15:alpha=1,"
        f"fade=out:st={fade_out_at:g}:d=0.25:alpha=1[s];"
        f"[c][s]overlay=x={bx - half}:y={by - half}:shortest=1,format=yuv420p"
    )
    _ffmpeg(
        "-loop", "1", "-i", closeup, "-loop", "1", "-i", sparkle, "-filter_complex", graph,
        "-t", f"{_frames(spec.outro_s) / FPS:g}", *_x264(spec.preset), out,
    )  # fmt: skip
    return out


def _dance(spec: MasterSpec, out: Path) -> Path:
    vf = f"scale={WIDTH}:{HEIGHT}:flags=lanczos,setsar=1,fps={FPS},format=yuv420p"
    _ffmpeg("-i", spec.dance, "-an", "-vf", vf, *_x264(spec.preset), out)
    return out


# ---- audio -------------------------------------------------------------------------------------

_STEREO_48K = "aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo"


def mix_audio(
    beat: Path,
    offset_s: float,
    *,
    total_s: float,
    sting_at_s: float | None,
    impacts_at_s: Sequence[float],
    out: Path,
    work: Path,
    fade_out_at_s: float | None = None,
) -> Path:
    """The beat from ``offset_s`` (padded with silence / cut to ``total_s``), optionally faded out
    at ``fade_out_at_s``, with the sting at ``sting_at_s`` and a thump at each of ``impacts_at_s``
    mixed in; 32-bit float stereo 48 kHz WAV, so the sum cannot clip before ``loudnorm``.
    """
    inputs: list[Path] = [beat]
    parts = [
        f"[0:a]atrim=start={offset_s:g},asetpts=PTS-STARTPTS,{_STEREO_48K}"
        + (f",afade=t=out:st={fade_out_at_s:g}:d={BEAT_FADE_SECONDS:g}" if fade_out_at_s is not None else "")
        + f",apad=whole_dur={total_s:.3f},atrim=0:{total_s:.3f}[b]"
    ]
    mixed = ["[b]"]
    if sting_at_s is not None:
        inputs.append(overlays.sting_wav(work / "sting.wav"))
        ms = round(sting_at_s * 1000)
        parts.append(f"[{len(inputs) - 1}:a]{_STEREO_48K},adelay={ms}|{ms},volume={STING_GAIN:g}[s]")
        mixed.append("[s]")
    if impacts_at_s:
        thump = overlays.impact_wav(work / "impact.wav")
        for i, at in enumerate(impacts_at_s):
            inputs.append(thump)
            parts.append(impact_filter(len(inputs) - 1, at, f"imp{i}"))
            mixed.append(f"[imp{i}]")
    parts.append(
        f"{''.join(mixed)}amix=inputs={len(mixed)}:normalize=0:duration=longest,"
        f"atrim=0:{total_s:.3f},aresample=48000[a]"
    )
    args: list[str | Path] = []
    for path in inputs:
        args += ["-i", path]
    _ffmpeg(*args, "-filter_complex", ";".join(parts), "-map", "[a]", "-c:a", "pcm_f32le", out)
    return out


_JSON_OBJECT = re.compile(r"\{[^{}]*\}")


def _loudnorm_params(mix: Path) -> str:
    """Pass 1: measure ``mix``; return the pass-2 ``loudnorm`` filter (linear, the measured values)."""
    log = _ffmpeg("-i", mix, "-af", f"loudnorm={LOUDNORM}:print_format=json", "-f", "null", "-", capture=True)
    found = _JSON_OBJECT.findall(log)
    if not found:
        raise MasterError("loudnorm printed no measurement")
    m = json.loads(found[-1])
    if str(m.get("input_i")) in ("-inf", "inf", "nan"):
        raise MasterError("the audio mix is silent (nothing to normalise)")
    return (
        f"loudnorm={LOUDNORM}:measured_I={m['input_i']}:measured_TP={m['input_tp']}:measured_LRA={m['input_lra']}"
        f":measured_thresh={m['input_thresh']}:offset={m['target_offset']}:linear=true"
    )


# ---- the build ---------------------------------------------------------------------------------


def _boxed(png: Path, start: float = 0.0, end: float | None = None) -> Overlay:
    """An ``Overlay`` of ``png`` cropped to its visible box, so ffmpeg decodes and blends only that
    (a full-frame RGBA blend per frame per overlay is the slowest part of the encode)."""
    with Image.open(png) as img:
        box = img.getchannel("A").getbbox() or (0, 0, 1, 1)
        small = png.with_name(f"{png.stem}_box.png")
        img.crop(box).save(small)
    return Overlay(small, start, end, x=box[0], y=box[1])


def _check_inputs(spec: MasterSpec) -> tuple[Path, Path | None]:
    if spec.music not in MUSIC_ARMS:
        raise ValueError(f"music must be one of {', '.join(MUSIC_ARMS)}, got {spec.music!r}")
    if spec.audio is None and spec.music != "in_app":
        raise ValueError(f"audio is required unless music is in_app (the master is silent), got music {spec.music!r}")
    dance = Path(spec.dance)
    audio = Path(spec.audio) if spec.audio is not None else None
    closeup = Path(spec.closeup) if spec.closeup is not None else None
    for label, path in (("dance", dance), ("audio", audio), ("closeup", closeup)):
        if path is not None and not path.is_file():
            raise ValueError(f"{label}: no such file: {path}")
    if closeup is not None:
        if spec.intro_s <= 0 or spec.outro_s <= 0:
            raise ValueError("intro_s and outro_s must be positive")
        with Image.open(closeup) as img:
            w, h = img.size
        if abs(w / h - WIDTH / HEIGHT) > 0.01:
            raise ValueError(f"the closeup must be 9:16 portrait (it is {w}x{h})")
    return dance, closeup


def build_master(spec: MasterSpec) -> Path:
    """Render ``spec`` to ``spec.out`` (see the module docstring); returns that path.

    Raises ``ValueError`` for a bad spec (checked before anything renders) and ``MasterError`` when
    ffmpeg fails. The finished file replaces ``out`` only when the whole build succeeded.
    """
    items = parse_enhancements(spec.enhancements)
    dance, closeup = _check_inputs(spec)
    out = Path(spec.out)
    slow = [e for e in items if isinstance(e, Slowmo)]
    intro_len = _frames(spec.intro_s) / FPS if closeup else 0.0
    outro_len = _frames(spec.outro_s) / FPS if closeup else 0.0
    if any(line.strip() for line in spec.hook2) and spec.hook2_until_s <= intro_len:
        # Without a close-up the intro is 0 s long: an end at 0 would flash the hook for one frame.
        raise ValueError(f"hook2_until_s ({spec.hook2_until_s:g}) must come after the intro ({intro_len:g} s)")
    if slow:  # fail before rendering anything; the exact check follows the normalised dance
        estimate = intro_len + _duration(dance) + outro_len + 1 / FPS
        for span in slow:
            _check_span_fits(span, estimate)

    with tempfile.TemporaryDirectory(prefix="studio-master-") as tmp:
        work = Path(tmp)
        clips: list[Path] = []
        if closeup:
            clips.append(_intro(spec, closeup, work / "intro.mp4"))
        dance_n = _dance(spec, work / "dance_n.mp4")
        clips.append(dance_n)
        if closeup:
            clips.append(_outro(spec, closeup, overlays.sparkle_png(work / "sparkle.png"), work / "outro.mp4"))
        base_s = intro_len + _duration(dance_n) + outro_len

        # Overlays: every window is on the finished timeline.
        shown: list[Overlay] = []
        for i, card in enumerate(e for e in items if isinstance(e, TitleCard)):
            shown.append(_boxed(overlays.title_png(card.text, work / f"title{i}.png"), 0.0, TITLE_CARD_SECONDS))
        if closeup and any(line.strip() for line in spec.hook1):
            shown.append(_boxed(overlays.pill_png(spec.hook1, work / "hook1.png"), 0.0, intro_len))
        if any(line.strip() for line in spec.hook2):
            shown.append(_boxed(overlays.pill_png(spec.hook2, work / "hook2.png"), intro_len, spec.hook2_until_s))
        for i, pop in enumerate(e for e in items if isinstance(e, TextPop)):
            png = overlays.hook_png([pop.text], work / f"pop{i}.png", y=TEXT_POP_Y, size=TEXT_POP_SIZE)
            shown.append(_boxed(png, out_time(pop.at_s, slow), out_time(pop.at_s + pop.dur_s, slow)))
        shown.append(_boxed(overlays.bug_png(work / "bug.png")))

        # One graph: concat -> zoom hits -> slowmo -> overlays -> yuv420p.
        graph = [
            "".join(f"[{i}:v]" for i in range(len(clips))) + f"concat=n={len(clips)}:v=1:a=0[v0]"
            if len(clips) > 1
            else "[0:v]null[v0]"
        ]
        label = "v0"

        def step(fragment: str) -> None:
            nonlocal label
            graph.append(fragment)
            label = fragment.rsplit("[", 1)[1].rstrip("]")

        for i, hit in enumerate(e for e in items if isinstance(e, ZoomHit)):
            step(zoom_hit_filter(label, f"z{i}", hit))
        if slow:
            step(slowmo_filter(label, "vs", slow, base_s))
        for i, ov in enumerate(shown):
            step(overlay_filter(label, len(clips) + i, f"o{i}", ov))
        graph.append(f"[{label}]format=yuv420p[vout]")

        video = work / "video_only.mp4"
        args: list[str | Path] = []
        for clip in clips:
            args += ["-i", clip]
        for ov in shown:
            args += ["-i", ov.png]
        _ffmpeg(
            *args, "-filter_complex", ";".join(graph), "-map", "[vout]", "-an",
            "-c:v", "libx264", "-profile:v", "high", "-preset", spec.preset,
            "-b:v", "15M", "-maxrate", "18M", "-bufsize", "30M", "-r", FPS, video,
        )  # fmt: skip
        total_s = _duration(video)

        finished = work / "master.mp4"
        if spec.music == "in_app":
            # a silent AAC track: the owner adds the song in the Instagram app (no beat, sting or sfx to normalise)
            _ffmpeg(
                "-i", video, "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-map", "0:v", "-map", "1:a",
                "-c:v", "copy", "-c:a", "aac", "-b:a", "320k", "-ar", "48000", "-t", f"{total_s:.3f}",
                "-shortest", "-movflags", "+faststart", finished,
            )  # fmt: skip
        else:
            # Audio: the beat fades into the outro and the sting lands just after the dance ends.
            dance_end = total_s - outro_len
            mix = mix_audio(
                Path(spec.audio),
                spec.audio_offset_s,
                total_s=total_s,
                sting_at_s=dance_end + STING_LAG_SECONDS if closeup else None,
                impacts_at_s=[out_time(e.at_s, slow) for e in items if isinstance(e, ImpactSfx)],
                out=work / "mix.wav",
                work=work,
                fade_out_at_s=dance_end - FADE_LEAD_SECONDS if closeup else None,
            )
            _ffmpeg(
                "-i", video, "-i", mix, "-map", "0:v", "-map", "1:a", "-c:v", "copy",
                "-af", _loudnorm_params(mix), "-c:a", "aac", "-b:a", "320k", "-ar", "48000",
                "-shortest", "-movflags", "+faststart", finished,
            )  # fmt: skip
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(finished, out)
    return out


# ---- CLI ---------------------------------------------------------------------------------------

_REQUIRED = ("dance", "out", "closeup")
_DEFAULTS: dict[str, Any] = {"hook1": [], "hook2": [], "hook2_until_s": 0.0, "audio_offset_s": 0.0, "music": "ai_beat"}


def spec_from_json(data: Any) -> MasterSpec:
    """A ``MasterSpec`` from a decoded JSON object. Raises ``ValueError`` listing what is wrong.

    ``dance``, ``out`` and ``closeup`` (a path or ``null``) are required, and ``audio`` unless ``music`` is
    ``in_app`` (a silent master); ``music`` defaults to ``ai_beat``. Hooks default
    to none, the offset to 0, and ``closeup_center`` / ``blue_eye_xy`` are required only with a
    close-up. ``hook1`` / ``hook2`` must be lists of strings (a bare string is refused). ``clip_id`` is
    optional. Other keys are the ``MasterSpec`` fields.
    """
    if not isinstance(data, dict):
        raise ValueError("the spec must be a JSON object")
    names = {f.name for f in dataclasses.fields(MasterSpec)}
    unknown = sorted(set(data) - names)
    if unknown:
        raise ValueError(f"unknown key(s) in the spec: {', '.join(unknown)}")
    music = data.get("music", "ai_beat")
    if music not in MUSIC_ARMS:
        raise ValueError(f"music must be one of {', '.join(MUSIC_ARMS)}, got {music!r}")
    needed = [
        *_REQUIRED, *(() if music == "in_app" else ("audio",)),
        *(("closeup_center", "blue_eye_xy") if data.get("closeup") else ()),
    ]
    missing = [k for k in needed if k not in data or (k == "audio" and not data[k])]
    if missing:
        raise ValueError(f"the spec is missing: {', '.join(missing)}")
    merged = {"closeup_center": (0, 0), "blue_eye_xy": (0, 0), **_DEFAULTS, **data}
    for key in ("hook1", "hook2"):
        lines = merged[key]
        if not (isinstance(lines, list) and all(isinstance(line, str) for line in lines)):
            raise ValueError(
                f'{key} must be a list of text lines, e.g. ["line one", "line two"] '
                f"(a bare string would be drawn one letter per line), got {lines!r}"
            )
    for key in ("closeup_center", "blue_eye_xy"):
        xy = merged[key]
        if not (isinstance(xy, list | tuple) and len(xy) == 2 and all(isinstance(v, int | float) for v in xy)):
            raise ValueError(f"{key} must be [x, y]")
        merged[key] = (round(xy[0]), round(xy[1]))
    for key in ("dance", "out"):
        merged[key] = Path(merged[key])
    merged["audio"] = Path(merged["audio"]) if merged.get("audio") else None
    merged["closeup"] = Path(merged["closeup"]) if merged["closeup"] else None
    return MasterSpec(**merged)


def _same_file(a: Path, b: Path) -> bool:
    """The same path, or two files with identical bytes (a copy of the generation is the generation)."""
    try:
        if a.resolve() == b.resolve() or (a.exists() and b.exists() and a.samefile(b)):
            return True
        if a.stat().st_size != b.stat().st_size:
            return False
        digest = lambda p: hashlib.sha256(p.read_bytes()).digest()  # noqa: E731
        return digest(a) == digest(b)
    except OSError:
        return False


def _in_inbox(audio: Path) -> bool:
    return "inbox" in (part.lower() for part in audio.resolve().parts)


def audio_problem(
    dance: Path, audio: Path, clip: Clip | None, source: Source | None, owner_music: str | None = None
) -> str | None:
    """Why ``audio`` may not be used for this master, or ``None`` (see the module docstring).

    The soundtrack of the dance generation or of a source file is third-party audio. Two cases are ours or
    kept on purpose: a ``recreate`` clip with a ``synthetic`` driver (its generation carries our own beat), and a
    ``dropin`` clip marked ``features.music == "original"``, the default (``owner_music`` is its pick's value: a
    different choice there, e.g. ``in_app`` or ``ai_beat``, refuses). An inbox file is never allowed.
    """
    ours = (
        clip is not None
        and clip.mode is Mode.recreate
        and source is not None
        and source.kind is SourceKind.synthetic
    )
    keeps_original = clip is not None and clip.mode is Mode.dropin and clip.features.get("music") == "original"
    if not ours and keeps_original and _same_file(Path(dance), Path(audio)):
        if owner_music not in (None, "original"):
            return (
                f"the clip says music original, but the owner chose {owner_music} for this video (Make-it sheet): "
                "its generation's own soundtrack is not used"
            )
        return _inbox_problem(audio) if _in_inbox(Path(audio)) else None
    if not ours and _same_file(Path(dance), Path(audio)):
        return (
            "the audio is the dance generation's own soundtrack, which for this clip may be third-party "
            "audio (kept only for a Drop-in with music original). Use a beat of our own: a seedance_2_5 "
            "t2v render with generate_audio. Only a recreate clip with a synthetic driver, or a dropin clip whose "
            "features.music is original, may use its generation's audio, and then master build needs --clip <id> "
            "(or clip_id in the spec) to know it is one"
        )
    if _in_inbox(Path(audio)):
        return _inbox_problem(audio)
    return None


def _inbox_problem(audio: Path) -> str:
    return (
        f"the audio {audio} is in an inbox folder: that is a source file (third-party audio, "
        "never posted). Use a beat of our own: a seedance_2_5 t2v render with generate_audio"
    )


app = typer.Typer(
    help="Build the 1080x1920 delivery master of a clip. Prints JSON; `build` exits 1 when the "
    "master has QA problems, 2 for anything the caller must fix.",
    no_args_is_help=True,
)


def upload_master(
    store: Store, storage: Storage, clip_id: str, file: Path | str, *, loop: bool = False
) -> Clip:
    """Check ``file`` against the master spec, upload it to ``clips/<character>/<clip id>.mp4``, set the path.

    ``KeyError`` for an unknown clip, ``QAError`` for an unreadable file, ``MasterRejected`` (nothing
    uploaded) when it misses the spec, ``StorageError`` when the upload fails.
    """
    clip = store.get_clip(clip_id)
    if clip is None:
        raise KeyError(clip_id)
    problems = check_master(probe(file), loop=loop, silent=clip.features.get("music") == "in_app")
    if problems:
        raise MasterRejected(problems)
    key = f"{clip.character_slug}/{clip.id}.mp4"
    storage.upload(MASTER_BUCKET, key, file)
    return set_fields(store, clip_id, master_path=key)


def _check_audio_rights(spec: MasterSpec, clip_id: str | None) -> None:
    """``ValueError`` when the spec's audio may be third-party.

    Only an audio that is the dance file or sits in an inbox folder needs a closer look, so the store is
    opened (for the clip and its source) only then: an ordinary build needs no database.
    """
    if spec.audio is None:  # a silent master has no audio to be third-party
        return
    dance, audio = Path(spec.dance), Path(spec.audio)
    if not (_same_file(dance, audio) or _in_inbox(audio)):
        return
    clip = source = None
    owner_music = None
    if clip_id is not None:
        store = open_store()
        clip = store.get_clip(clip_id)
        if clip is None:
            raise ValueError(f"unknown clip {clip_id}")
        source = next(iter(store.list_sources(id=clip.source_id)), None) if clip.source_id else None
        fav_id = clip.features.get("fav_id")
        pick = store.get_favorite(fav_id) if isinstance(fav_id, str) else None
        owner_music = pick.proposal.get("owner_music") if pick is not None else None
    if (problem := audio_problem(dance, audio, clip, source, owner_music)) is not None:
        raise ValueError(problem)


@app.command("build")
def build_command(
    spec: Annotated[Path, typer.Option("--spec", help="JSON file of MasterSpec fields (see master.py).")],
    loop: Annotated[bool, typer.Option("--loop", help="Judge the result as an eye loop (6-8 s).")] = False,
    clip: Annotated[
        str | None,
        typer.Option(
            "--clip",
            help="Clip id (or clip_id in the spec): needed to use the dance generation's own audio, "
            "allowed only for a recreate clip with a synthetic driver.",
        ),
    ] = None,
) -> None:
    """Render the master described by SPEC, check it against the master spec, print the report.

    Refuses (exit 2) an audio that is the dance generation's soundtrack or a source file, unless the
    clip is a recreate clip made from a synthetic driver.
    """
    try:
        data = json.loads(spec.read_text(encoding="utf-8"))
    except FileNotFoundError:
        fail(f"no such file: {spec}")
    except (OSError, json.JSONDecodeError) as e:
        fail(f"cannot read the spec {spec}: {e}")
    try:
        built = spec_from_json(data)
        if clip is not None and built.clip_id is not None and clip != built.clip_id:
            raise ValueError(f"--clip {clip} and clip_id {built.clip_id} in the spec are different clips")
        _check_audio_rights(built, clip or built.clip_id)
        out = build_master(built)
        report = probe(out)
    except (ValueError, MasterError, QAError) as e:
        fail(str(e))
    problems = check_master(report, loop=loop, silent=built.music == "in_app")
    report = dataclasses.replace(report, problems=problems)
    emit({"out": str(out), **dataclasses.asdict(report), "ok": report.ok})
    if problems:
        raise typer.Exit(1)


@app.command("mux-audio")
def mux_audio_command(
    video: Annotated[Path, typer.Argument(help="The Genjutsu output that came back without its audio.")],
    source: Annotated[Path, typer.Argument(help="The source clip (trimmed or whole) whose audio goes back under it.")],
    start: Annotated[float, typer.Option("--start", help="Where the trimmed window began in SOURCE, in seconds.")],
    out: Annotated[Path, typer.Option("--out", help="Where to write the result (.mp4).")],
) -> None:
    """Put SOURCE's audio (from --start, as long as VIDEO runs) back under VIDEO's picture; prints the result as JSON."""
    try:
        done = clipwork.mux_source_audio(video, source, out, start)
        report = probe(done)
    except (ValueError, QAError, clipwork.ClipworkError) as e:
        fail(str(e))
    emit({"out": str(done), "duration_s": report.duration_s, "has_audio": report.has_audio, "lufs": report.lufs})


@app.command("upload")
def upload_command(
    clip: Annotated[str, typer.Argument(help="Clip id.")],
    file: Annotated[Path, typer.Argument(help="The finished master (output of `master build`).")],
    loop: Annotated[bool, typer.Option("--loop", help="Judge it as an eye loop (6-8 s).")] = False,
) -> None:
    """Upload a spec-checked master to the clips bucket and set the clip's master_path."""
    store = open_store()
    storage = open_storage()
    try:
        done = upload_master(store, storage, clip, file, loop=loop)
    except KeyError:
        fail(f"unknown clip {clip}")
    except MasterRejected as e:
        emit({"ok": False, "clip": clip, "problems": e.problems})
        raise typer.Exit(1) from e
    except (QAError, StorageError) as e:
        fail(str(e))
    emit({"clip": done.id, "master_path": done.master_path, "bucket": MASTER_BUCKET})
