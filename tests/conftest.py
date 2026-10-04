"""Shared fixtures.

``synth_video`` builds synthetic clips with ffmpeg (lavfi ``testsrc2`` video + a ``sine`` track
calibrated to a known loudness), so media tests need no files in the repo.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

# lavfi ``sine`` peaks at 1/8 (-18 dBFS) before any gain.
_SINE_PEAK = 0.125


def _ffmpeg(*args: str) -> None:
    proc = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdin=subprocess.DEVNULL,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed ({proc.returncode}): {proc.stderr.strip()[-600:]}")


def _name(w: int, h: int, fps: float, dur: float, audio: bool, lufs: float) -> str:
    tail = f"{lufs:g}lufs" if audio else "silent"
    return f"synth_{w}x{h}_{fps:g}fps_{dur:g}s_{tail}.mp4".replace("-", "m")


def _build(path: Path, w: int, h: int, fps: float, dur: float, audio: bool, lufs: float) -> None:
    """H.264 High at ~15 Mbps (the master recipe), AAC 48 kHz stereo when ``audio``.

    ``ultrafast`` would drop to Constrained Baseline; ``8x8dct`` + ``cabac`` keep the High
    profile signalled at a fraction of the cost of a slower preset.
    """
    args = ["-f", "lavfi", "-i", f"testsrc2=size={w}x{h}:rate={fps:g}:duration={dur:g}"]
    if audio:
        # A 1 kHz sine of amplitude a, identical on both channels, measures 20*log10(a) LUFS.
        gain = 10 ** (lufs / 20) / _SINE_PEAK
        args += [
            "-f", "lavfi", "-i",
            f"sine=frequency=1000:sample_rate=48000:duration={dur:g},"
            f"pan=stereo|c0=c0|c1=c0,volume={gain:.6f}",
        ]
    args += [
        "-c:v", "libx264", "-profile:v", "high", "-preset", "ultrafast",
        "-x264-params", "8x8dct=1:cabac=1",
        "-b:v", "15M", "-maxrate", "18M", "-bufsize", "30M", "-pix_fmt", "yuv420p",
    ]  # fmt: skip
    args += ["-c:a", "aac", "-b:a", "320k", "-ar", "48000"] if audio else ["-an"]
    args += ["-t", f"{dur:g}", str(path)]
    _ffmpeg(*args)


@pytest.fixture(scope="session")
def _synth_cache(tmp_path_factory) -> tuple[Path, dict[str, Path]]:
    return tmp_path_factory.mktemp("synth"), {}


@pytest.fixture
def synth_video(_synth_cache) -> Callable[..., Path]:
    """Factory ``synth_video(tmp_path=None, w=1080, h=1920, fps=30, dur=10, audio=True, *, lufs=-14.0)``.

    Returns the path of an H.264 High / ~15 Mbps MP4 (``testsrc2``) with, when ``audio``, an
    AAC 48 kHz stereo sine whose integrated loudness is ``lufs``. Without ``tmp_path`` the file
    lives in a session-wide cache shared by every test that asks for the same parameters, so
    treat it as read-only (copy it to edit); the silent variant is the audio variant with the
    track stream-copied away. With ``tmp_path`` a fresh private file is written there instead.
    Sizes must be even.
    """
    cache_dir, files = _synth_cache

    def make(
        tmp_path: Path | None = None,
        w: int = 1080,
        h: int = 1920,
        fps: float = 30,
        dur: float = 10,
        audio: bool = True,
        *,
        lufs: float = -14.0,
    ) -> Path:
        name = _name(w, h, fps, dur, audio, lufs)
        if tmp_path is not None:
            path = Path(tmp_path) / name
            _build(path, w, h, fps, dur, audio, lufs)
            return path
        if name not in files:
            path = cache_dir / name
            if audio:
                _build(path, w, h, fps, dur, audio, lufs)
            else:
                # Same picture as the audio version (one encode per size), track dropped.
                _ffmpeg("-i", str(make(None, w, h, fps, dur, True)), "-an", "-c", "copy", str(path))
            files[name] = path
        return files[name]

    return make
