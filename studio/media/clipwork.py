"""Small ffmpeg jobs on a clip: cut it to its best window, and put a source's audio back (owner decisions 2026-10-05).

**Trim before generating.** Genjutsu is paid per second, so only the best 6-9 s window of a source goes to it
(``trim_clip``; the hard maximum of a master is 16 s, which is also the longest window accepted). The window keeps
its audio unless asked otherwise: a Drop-in keeps the original clip audio by default.

**Mux the source audio back.** A Genjutsu output normally carries the audio of the clip it was given. When it comes
back without an audio stream, ``mux_source_audio`` takes the source clip's audio for the same window (``start_s``
is where the trimmed window began in the source), lays it under the output's picture (the video stream is copied,
the audio is AAC 48 kHz) and stops at the picture's length. This only restores the clip's own audio: it never adds
anything the clip did not carry, and ``master build`` still refuses any other third-party audio.

CLI: ``studio master mux-audio VIDEO SOURCE --start S --out OUT`` (and ``studio source trim`` for the trim of a
catalogued source). Exit 2 for anything the caller must fix.
"""

from __future__ import annotations

import math
import os
import subprocess
import tempfile
from pathlib import Path

from studio.media.qa import QAError, probe

TRIM_MAX_SECONDS = 16.0  # the hard maximum of a master
_SLACK = 0.15  # a window may overshoot the end of the file by a frame or two of container rounding
_FFMPEG = "ffmpeg"


class ClipworkError(RuntimeError):
    """ffmpeg failed."""


def _ffmpeg(*args: str | Path, timeout: float = 900) -> None:
    cmd = [_FFMPEG, "-hide_banner", "-loglevel", "error", "-nostdin", "-y", *map(str, args)]
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
            stdin=subprocess.DEVNULL, timeout=timeout, check=False,
        )  # fmt: skip
    except FileNotFoundError as e:
        raise ClipworkError("ffmpeg not found: install ffmpeg") from e
    except subprocess.TimeoutExpired as e:
        raise ClipworkError(f"ffmpeg timed out after {timeout:.0f} s") from e
    if proc.returncode != 0:
        tail = " | ".join(proc.stderr.strip().splitlines()[-4:]) or "no output"
        raise ClipworkError(f"ffmpeg failed ({proc.returncode}): {tail}")


def _number(value: float, what: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{what} must be a number, got {value!r}")
    return float(value)


def _finish(tmp: Path, out: Path) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    os.replace(tmp, out)  # the output only appears when the whole job worked
    return out


def trim_clip(
    src: Path | str, out: Path | str, start_s: float, duration_s: float, *, keep_audio: bool = True
) -> Path:
    """Cut ``duration_s`` seconds from ``start_s`` of ``src`` into ``out`` (H.264 + AAC, re-encoded for an exact cut).

    ``ValueError`` for a window that makes no sense (non-positive or over 16 s, a negative start, or one that
    ends after the clip does); ``QAError`` for a missing or unreadable file; ``ClipworkError`` when ffmpeg fails.
    """
    src, out = Path(src), Path(out)
    start, duration = _number(start_s, "start"), _number(duration_s, "duration")
    if start < 0:
        raise ValueError(f"start must be 0 or more seconds, got {start:g}")
    if duration <= 0:
        raise ValueError(f"duration must be positive, got {duration:g}")
    if duration > TRIM_MAX_SECONDS:
        raise ValueError(f"a window is at most {TRIM_MAX_SECONDS:g} s (the hard maximum of a master), got {duration:g}")
    total = probe(src, loudness=False).duration_s
    if start + duration > total + _SLACK:
        raise ValueError(f"the source ends at {total:.2f} s, before the window {start:g}-{start + duration:g} s does")
    with tempfile.TemporaryDirectory(prefix="studio-trim-") as tmp:
        work = Path(tmp) / "trimmed.mp4"
        _ffmpeg(
            "-ss", f"{start:.3f}", "-t", f"{duration:.3f}", "-i", src,
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p",
            *(["-c:a", "aac", "-b:a", "192k", "-ar", "48000"] if keep_audio else ["-an"]),
            "-movflags", "+faststart", work,
        )  # fmt: skip
        return _finish(work, out)


def mux_source_audio(video: Path | str, source: Path | str, out: Path | str, start_s: float) -> Path:
    """Put the audio of ``source`` from ``start_s`` (for as long as ``video`` runs) under ``video``'s picture.

    The picture is copied untouched; any audio ``video`` already had is replaced. ``ValueError`` when the source
    has no audio or the window does not fit in it; ``QAError`` for a missing or unreadable file.
    """
    video, source, out = Path(video), Path(source), Path(out)
    start = _number(start_s, "start")
    if start < 0:
        raise ValueError(f"start must be 0 or more seconds, got {start:g}")
    picture = probe(video, loudness=False)
    audio_source = probe(source, loudness=False)
    if not audio_source.has_audio:
        raise ValueError(f"the source {source.name} has no audio to put back")
    if start + picture.duration_s > audio_source.duration_s + _SLACK:
        raise ValueError(
            f"the source ends at {audio_source.duration_s:.2f} s, before the window {start:g}-{start + picture.duration_s:g} s does"
        )
    with tempfile.TemporaryDirectory(prefix="studio-mux-") as tmp:
        work = Path(tmp) / "muxed.mp4"
        _ffmpeg(
            "-i", video, "-ss", f"{start:.3f}", "-t", f"{picture.duration_s:.3f}", "-i", source,
            "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
            "-shortest", "-movflags", "+faststart", work,
        )  # fmt: skip
        return _finish(work, out)


__all__ = ["ClipworkError", "QAError", "TRIM_MAX_SECONDS", "mux_source_audio", "trim_clip"]
