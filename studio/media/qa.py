"""Technical QA of rendered clips: what ffprobe/ebur128 measure, judged against fixed specs.

``probe`` only *measures* (it never judges); ``check_master`` and ``check_source`` *judge* a
``TechReport`` and return problems. A problem is a string ``"<key>: <detail>"``; callers match on
the key (``resolution``, ``fps``, ``duration``, ``bitrate``, ``codec``, ``audio``,
``audio_format``, ``loudness``, ``peak``). The checks are pure, so they run on a hand-built
report as well as a probed one.

**Master spec** (Global Constraints): 1080x1920, 30 fps, H.264 High, 10-20 Mbps video bitrate
(the encode targets ~15), AAC at 48 kHz, an audio track, integrated loudness -14 LUFS +/- 1, true
peak <= -1 dBFS, 7-16 s (an eye loop, ``loop=True``, is 6-8 s instead). The AAC "320k" is an
encoder setting, not a property of the content (ffmpeg's encoder spends fewer bits on sparse
audio), so it is not checked; the codec and the sample rate are. Durations accept 0.05 s either
side: AAC priming and container rounding make 7 s of video read 6.98 or 7.02 s.

**Source spec** (a driver or generation as downloaded, before mastering): at least 480 px wide,
4-30 s, 23-60 fps. No audio, bitrate or loudness requirements.

Loudness is measured with ffmpeg's ``ebur128=peak=true`` (integrated ``I:`` and true ``Peak:``
from its summary), the same method the spike used. Digital silence reads -70 LUFS (the filter's
floor) and an infinite-negative peak, which has no JSON form and is stored as ``None``.

CLI (``studio qa ...``) prints JSON on stdout. ``qa tech`` exits 1 when there are problems (the
JSON says which); exit 2 is for anything the caller must fix (no such file, not a video, bad
number). An unexpected crash also exits 1 but prints a traceback and no JSON.
"""

from __future__ import annotations

import dataclasses
import json
import math
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated, Any

import typer

from studio.cli_support import emit, fail

# ---- specs -------------------------------------------------------------------------------------

MASTER_SIZE = (1080, 1920)
MASTER_FPS = 30.0
MASTER_KBPS = (10_000.0, 20_000.0)
MASTER_SECONDS = (7.0, 16.0)
LOOP_SECONDS = (6.0, 8.0)
MASTER_AUDIO_CODEC = "aac"
MASTER_AUDIO_HZ = 48_000
LUFS_TARGET = -14.0
LUFS_TOLERANCE = 1.0
TRUE_PEAK_MAX = -1.0

SOURCE_MIN_WIDTH = 480
SOURCE_SECONDS = (4.0, 30.0)
SOURCE_FPS = (23.0, 60.0)

DURATION_SLACK = 0.05  # seconds
FPS_SLACK = 0.01
_EPS = 1e-9

FRAME_WIDTH = 270
MAX_FRAMES = 24
_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png"}


class QAError(RuntimeError):
    """A file could not be inspected (missing, not a video) or ffmpeg/ffprobe failed."""


@dataclass
class TechReport:
    """What ``probe`` measured. ``problems`` is filled by whoever judged it (see the CLI)."""

    width: int
    height: int
    fps: float
    duration_s: float
    video_kbps: float | None
    has_audio: bool
    lufs: float | None
    true_peak: float | None
    problems: list[str] = field(default_factory=list)
    video_codec: str | None = None
    video_profile: str | None = None
    audio_codec: str | None = None
    audio_hz: int | None = None

    @property
    def ok(self) -> bool:
        return not self.problems


# ---- running ffmpeg ----------------------------------------------------------------------------


def _run(cmd: list[str], *, timeout: float = 600) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdin=subprocess.DEVNULL,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as e:
        raise QAError(f"{cmd[0]} not found: install ffmpeg") from e
    except subprocess.TimeoutExpired as e:
        raise QAError(f"{cmd[0]} timed out after {timeout:.0f} s") from e


def _tail(text: str, lines: int = 3) -> str:
    return " | ".join(text.strip().splitlines()[-lines:]) or "no output"


def _ffprobe(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise QAError(f"no such file: {path}")
    proc = _run(
        ["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", "-i", str(path)]
    )
    if proc.returncode != 0:
        raise QAError(f"ffprobe could not read {path}: {_tail(proc.stderr)}")
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError as e:
        raise QAError(f"ffprobe returned unreadable output for {path}") from e
    return data if isinstance(data, dict) else {}


def _stream(data: dict[str, Any], kind: str) -> dict[str, Any] | None:
    for s in data.get("streams", []):
        if s.get("codec_type") != kind:
            continue
        if kind == "video" and s.get("disposition", {}).get("attached_pic"):
            continue  # cover art, not a video
        return s
    return None


def _number(value: Any) -> float | None:
    """A positive finite number from ffprobe's strings (``"N/A"``, ``None``, ``"0"`` -> None)."""
    try:
        n = float(value)
    except (TypeError, ValueError):
        return None
    return n if math.isfinite(n) and n > 0 else None


def _ratio(text: Any) -> float | None:
    num, _, den = str(text).partition("/")
    n, d = _number(num), _number(den or "1")
    return n / d if n and d else None


def _fps(video: dict[str, Any]) -> float:
    """The nominal rate (30/1), unless the true average disagrees by over 1% (variable rate).

    The average is frames / duration, so a few frames of container padding make a 30 fps clip
    read 29.97; the nominal rate is what the encoder was told.
    """
    avg, nominal = _ratio(video.get("avg_frame_rate")), _ratio(video.get("r_frame_rate"))
    if avg and nominal:
        return nominal if abs(avg - nominal) <= 0.01 * nominal else avg
    return avg or nominal or 0.0


def _rotated(video: dict[str, Any]) -> bool:
    """True for a 90/270 degree display rotation: players show the picture sideways."""
    rotations = [video.get("tags", {}).get("rotate")]
    rotations += [sd.get("rotation") for sd in video.get("side_data_list", []) if "rotation" in sd]
    for r in rotations:
        try:
            if r is not None and int(float(r)) % 180 == 90:
                return True
        except (TypeError, ValueError):
            continue
    return False


def _duration(data: dict[str, Any], video: dict[str, Any]) -> float:
    return _number(data.get("format", {}).get("duration")) or _number(video.get("duration")) or 0.0


def _video_kbps(data: dict[str, Any], video: dict[str, Any], audio: dict[str, Any] | None) -> float | None:
    """The video stream's own bitrate; failing that the container's total minus the audio."""
    own = _number(video.get("bit_rate")) or _number(video.get("tags", {}).get("BPS"))
    if own:
        return own / 1000
    total = _number(data.get("format", {}).get("bit_rate"))
    if total:
        audio_bps = (_number(audio.get("bit_rate")) or _number(audio.get("tags", {}).get("BPS")) or 0) if audio else 0
        return max(total - audio_bps, 0.0) / 1000
    return None


# ---- loudness ----------------------------------------------------------------------------------

_LUFS = re.compile(r"^\s*I:\s*(-?inf|-?\d+(?:\.\d+)?)\s*LUFS\s*$", re.MULTILINE)
_PEAK = re.compile(r"^\s*Peak:\s*(-?inf|-?\d+(?:\.\d+)?)\s*dBFS\s*$", re.MULTILINE)


def _finite(text: str) -> float | None:
    value = float(text)
    return value if math.isfinite(value) else None


def measure_loudness(path: Path) -> tuple[float | None, float | None]:
    """``(integrated LUFS, true peak dBFS)`` of the first audio stream, via ``ebur128=peak=true``.

    A value ffmpeg prints as ``-inf`` comes back as ``None`` (digital silence has no peak).
    """
    proc = _run(
        ["ffmpeg", "-hide_banner", "-nostats", "-nostdin", "-i", str(path), "-vn", "-map", "0:a:0",
         "-af", "ebur128=peak=true:framelog=quiet", "-f", "null", "-"]
    )  # fmt: skip
    if proc.returncode != 0:
        raise QAError(f"ffmpeg could not measure the loudness of {path}: {_tail(proc.stderr)}")
    if "Summary:" not in proc.stderr:
        raise QAError(f"ffmpeg ebur128 printed no summary for {path}")
    summary = proc.stderr.rpartition("Summary:")[2]
    lufs, peak = _LUFS.search(summary), _PEAK.search(summary)
    if lufs is None or peak is None:
        raise QAError(f"could not parse the ebur128 summary for {path}")
    return _finite(lufs.group(1)), _finite(peak.group(1))


# ---- probe and checks --------------------------------------------------------------------------


def probe(path: str | Path, *, loudness: bool = True) -> TechReport:
    """Measure ``path``. ``loudness=False`` skips the (audio-only, fast) ebur128 pass.

    Raises ``QAError`` when the file is missing, unreadable or has no video stream. The report's
    width/height are as displayed (swapped for a 90/270 degree rotation flag).
    """
    path = Path(path)
    data = _ffprobe(path)
    video, audio = _stream(data, "video"), _stream(data, "audio")
    if video is None:
        raise QAError(f"{path} has no video stream")
    width, height = int(video.get("width") or 0), int(video.get("height") or 0)
    if _rotated(video):
        width, height = height, width
    lufs = peak = None
    if audio is not None and loudness:
        lufs, peak = measure_loudness(path)
    return TechReport(
        width=width,
        height=height,
        fps=_fps(video),
        duration_s=_duration(data, video),
        video_kbps=_video_kbps(data, video, audio),
        has_audio=audio is not None,
        lufs=lufs,
        true_peak=peak,
        video_codec=video.get("codec_name"),
        video_profile=video.get("profile"),
        audio_codec=audio.get("codec_name") if audio else None,
        audio_hz=int(_number(audio.get("sample_rate")) or 0) or None if audio is not None else None,
    )


def _in_range(value: float, low: float, high: float, slack: float = 0.0) -> bool:
    return low - slack - _EPS <= value <= high + slack + _EPS


def check_master(r: TechReport, *, loop: bool = False) -> list[str]:
    """Problems of ``r`` against the master spec (empty = it meets it). ``loop``: an eye loop."""
    problems: list[str] = []
    if (r.width, r.height) != MASTER_SIZE:
        problems.append(f"resolution: {r.width}x{r.height}, need {MASTER_SIZE[0]}x{MASTER_SIZE[1]}")
    if abs(r.fps - MASTER_FPS) > FPS_SLACK:
        problems.append(f"fps: {r.fps:g}, need {MASTER_FPS:g}")
    low, high = LOOP_SECONDS if loop else MASTER_SECONDS
    if not _in_range(r.duration_s, low, high, DURATION_SLACK):
        problems.append(f"duration: {r.duration_s:.2f} s, need {low:g}-{high:g} s{' (eye loop)' if loop else ''}")
    if r.video_kbps is None:
        problems.append("bitrate: unknown (the file does not carry a video bitrate)")
    elif not _in_range(r.video_kbps, *MASTER_KBPS):
        problems.append(f"bitrate: {r.video_kbps:.0f} kbps, need {MASTER_KBPS[0]:.0f}-{MASTER_KBPS[1]:.0f} kbps")
    if r.video_codec is not None and r.video_codec != "h264":
        problems.append(f"codec: video is {r.video_codec}, need h264 High")
    elif r.video_codec is not None and r.video_profile is not None and r.video_profile != "High":
        problems.append(f"codec: h264 profile is {r.video_profile}, need High")
    if not r.has_audio:
        problems.append("audio: no audio stream")
        return problems
    if (r.audio_codec is not None and r.audio_codec != MASTER_AUDIO_CODEC) or (
        r.audio_hz is not None and r.audio_hz != MASTER_AUDIO_HZ
    ):
        problems.append(
            f"audio_format: {r.audio_codec or '?'} at {r.audio_hz or '?'} Hz, "
            f"need {MASTER_AUDIO_CODEC} at {MASTER_AUDIO_HZ} Hz"
        )
    if r.lufs is None:
        problems.append("loudness: not measured")
    elif not _in_range(r.lufs, LUFS_TARGET - LUFS_TOLERANCE, LUFS_TARGET + LUFS_TOLERANCE):
        problems.append(f"loudness: {r.lufs:.1f} LUFS, need {LUFS_TARGET:g} +/- {LUFS_TOLERANCE:g}")
    if r.true_peak is not None and r.true_peak > TRUE_PEAK_MAX + _EPS:
        problems.append(f"peak: {r.true_peak:.1f} dBFS, need <= {TRUE_PEAK_MAX:g}")
    return problems


def check_source(r: TechReport) -> list[str]:
    """Problems of ``r`` as a source clip (empty = usable): >= 480 px wide, 4-30 s, 23-60 fps."""
    problems: list[str] = []
    if r.width < SOURCE_MIN_WIDTH:
        problems.append(f"resolution: {r.width}px wide, need >= {SOURCE_MIN_WIDTH}")
    if not _in_range(r.duration_s, *SOURCE_SECONDS, DURATION_SLACK):
        problems.append(f"duration: {r.duration_s:.2f} s, need {SOURCE_SECONDS[0]:g}-{SOURCE_SECONDS[1]:g} s")
    if not _in_range(r.fps, *SOURCE_FPS, FPS_SLACK):
        problems.append(f"fps: {r.fps:g}, need {SOURCE_FPS[0]:g}-{SOURCE_FPS[1]:g}")
    return problems


# ---- frame sheets ------------------------------------------------------------------------------


def frame_times(duration_s: float, n: int, fps: float = 30.0) -> list[float]:
    """``n`` evenly spaced moments from the first frame to the last (the middle for ``n == 1``)."""
    last = max(duration_s - 1.5 / (fps if fps > 0 else 30.0), 0.0)
    if n == 1:
        return [last / 2]
    return [last * i / (n - 1) for i in range(n)]


def frame_sheet(path: str | Path, n: int = 6, out: str | Path | None = None) -> Path:
    """Write ``n`` evenly spaced frames of ``path``, 270 px wide each, side by side, to ``out``.

    The first and last frames are included (the hook and the closing eye close-up).
    ``out`` is a ``.jpg`` / ``.png`` (default: ``<video>.frames.jpg`` next to the video); missing
    parent folders are created and an existing file is overwritten. The sheet is ``n * 270`` px
    wide. Raises ``ValueError`` for a bad ``n`` or extension, ``QAError`` for an unreadable video.
    """
    if not 1 <= n <= MAX_FRAMES:
        raise ValueError(f"need 1-{MAX_FRAMES} frames, got {n}")
    path = Path(path)
    out = Path(out) if out is not None else path.with_name(f"{path.stem}.frames.jpg")
    if out.suffix.lower() not in _IMAGE_SUFFIXES:
        raise ValueError(f"the sheet must be a .jpg or .png file, got {out.name!r}")
    data = _ffprobe(path)
    video = _stream(data, "video")
    if video is None:
        raise QAError(f"{path} has no video stream")
    # The video stream's own length: the container may run on for a longer audio track.
    duration = _number(video.get("duration")) or _duration(data, video)
    times = frame_times(duration, n, _fps(video))

    # One decode pass, not one seek per frame: a seek decodes from the previous keyframe, and a
    # master's keyframes are ~8 s apart. A frame is picked when it is the first at or after a
    # target moment (``prev_t`` is the previous *input* frame's time).
    pick = "+".join(
        "isnan(prev_t)" if t == 0 else f"gte(t-start_t,{t:.3f})*lt(prev_t-start_t,{t:.3f})" for t in times
    )
    graph = f"select='{pick}',scale={FRAME_WIDTH}:-2,setsar=1,tile={n}x1"
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y", "-i", str(path),
        "-vf", graph, "-fps_mode", "passthrough", "-frames:v", "1", "-q:v", "2", "-update", "1", str(out),
    ]  # fmt: skip

    out.parent.mkdir(parents=True, exist_ok=True)
    proc = _run(cmd)
    if proc.returncode != 0 or not out.is_file():
        raise QAError(f"ffmpeg could not build the frame sheet for {path}: {_tail(proc.stderr)}")
    return out


# ---- CLI ---------------------------------------------------------------------------------------

app = typer.Typer(
    help="Technical QA of rendered clips (ffprobe / ebur128 checks, frame sheets). Prints JSON; "
    "`tech` exits 1 when there are problems, 2 for anything the caller must fix.",
    no_args_is_help=True,
)


@app.command("tech")
def tech_command(
    file: Annotated[Path, typer.Argument(help="The video to check.")],
    master: Annotated[
        bool,
        typer.Option("--master", help="Judge against the delivery spec (default: the looser source spec)."),
    ] = False,
    loop: Annotated[bool, typer.Option("--loop", help="With --master: an eye loop (6-8 s).")] = False,
) -> None:
    """ffprobe checks of FILE; prints the report as JSON, exit 1 when it has problems."""
    if loop and not master:
        fail("--loop only applies together with --master")
    try:
        report = probe(file, loudness=master)  # the source spec has no loudness rule
    except QAError as e:
        fail(str(e))
    problems = check_master(report, loop=loop) if master else check_source(report)
    report = dataclasses.replace(report, problems=problems)
    checked = ("master (eye loop)" if loop else "master") if master else "source"
    emit({"file": str(file), "checked": checked, **dataclasses.asdict(report), "ok": report.ok})
    if problems:
        raise typer.Exit(1)


@app.command("frames")
def frames_command(
    file: Annotated[Path, typer.Argument(help="The video to sample.")],
    out: Annotated[Path, typer.Option("--out", help="Where to write the sheet (.jpg or .png).")],
    n: Annotated[int, typer.Option("--n", help=f"Frames on the sheet (1-{MAX_FRAMES}).")] = 6,
) -> None:
    """Write N evenly spaced frames of FILE (270 px wide each) side by side to OUT."""
    try:
        sheet = frame_sheet(file, n=n, out=out)
    except (QAError, ValueError) as e:
        fail(str(e))
    emit({"out": str(sheet), "frames": n, "frame_width": FRAME_WIDTH, "sheet_width": n * FRAME_WIDTH})
