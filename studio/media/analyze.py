"""Local analysis of a clip: motion, beat, the best 6-9 s window and a contact sheet (owner request 2026-10-05).

Free (ffmpeg only, no credits, no network, no new dependency) and deterministic. ``analyze_clip`` measures what a machine can:

* **Motion energy** per 0.5 s: the clip is decoded as tiny grey frames (48 x 84, 10 a second) and the mean absolute change
  between neighbouring frames (grey levels, 0-255) is averaged per half second. A still shot reads under 1, a person
  dancing in a static frame 3-10, a hard cut spikes far above. **Cuts** are the frames where the change is both large (18
  or more) and at least four times the local median: a cut is a change of shot, not just fast movement.
* **Beat**: the audio is decoded to 8 kHz mono, pre-emphasised, and its energy per 10 ms (log scale) differenced into an
  onset envelope. The tempo is the strongest autocorrelation lag between 60 and 180 bpm (parabolic interpolation), folded into
  80-160 bpm (the range of dance music: a clip clapping at 60 reads 120), and the beats are tracked through the onsets from
  the best phase. No audio, silence or no clear pulse gives ``bpm: null`` and no beats (never a made-up tempo).
* **Best window**: the 6-9 s stretch (0.5 s steps) with the highest mean motion energy, a window that contains a cut
  discounted (x0.7 per cut: one clean shot is what a Drop-in swaps), ties to the shorter then earlier one (Genjutsu is paid
  per second). With a beat, the start and the end snap to the nearest beat when both stay within 6-9 s. A clip shorter than
  6 s is its own window.
* **Contact sheet**: nine evenly spaced frames, 3 x 3, in a PNG (``renders/<id>/analysis.png``, never in git): what the agent
  looks at to judge people, subject, camera, a watermark, burned-in text and children, which no program here can.

The numbers are measurements; ``who is in the clip`` stays a visual judgement, stored by ``fav mark --analysis-file``.
"""

from __future__ import annotations

import math
import statistics
import subprocess
import sys
from array import array
from operator import mul, sub
from pathlib import Path
from typing import Any

from studio.media.qa import QAError, TechReport, check_source, contact_sheet, probe

MOTION_STEP_S = 0.5
MOTION_FPS = 10
MOTION_SIZE = (48, 84)
CUT_MIN_CHANGE = 18.0  # grey levels (0-255) of mean absolute change between two frames
CUT_OVER_MEDIAN = 4.0
CUT_DISCOUNT = 0.7  # a window containing a cut keeps this share of its motion score per cut
CUT_EDGE_S = 0.3  # a cut this close to a window's start or end is a clean start, not a cut inside

WINDOW_SECONDS = (6.0, 9.0)
WINDOW_STEP_S = 0.5

AUDIO_HZ = 8000
HOP = 80  # samples: 10 ms
HOP_S = HOP / AUDIO_HZ
BPM_SEARCH = (60.0, 180.0)
BPM_FOLD = (80.0, 160.0)
MIN_PULSE = 0.2  # the autocorrelation peak against its zero lag: below this there is no clear beat
MIN_ONSET = 0.5  # a log-energy rise (decades of mean square) below this is silence, not an attack

MAX_ANALYSIS_SECONDS = 180.0
MAX_BEATS_LISTED = 120
_DECODE_TIMEOUT = 300.0


class AnalysisError(RuntimeError):
    """The clip could not be analysed (not a readable video, too long, or ffmpeg failed)."""


# ---- decoding --------------------------------------------------------------------------------------------------------


def _decode_raw(path: Path, args: list[str]) -> bytes:
    """ffmpeg's stdout for ``-i path <args> -``: raw video or PCM, as bytes."""
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-i", str(path), *args, "-"]
    try:
        proc = subprocess.run(cmd, capture_output=True, stdin=subprocess.DEVNULL, timeout=_DECODE_TIMEOUT, check=False)
    except FileNotFoundError as e:
        raise AnalysisError("ffmpeg not found: install ffmpeg") from e
    except subprocess.TimeoutExpired as e:
        raise AnalysisError(f"ffmpeg timed out after {_DECODE_TIMEOUT:.0f} s decoding {path.name}") from e
    if proc.returncode != 0:
        tail = " | ".join(proc.stderr.decode("utf-8", "replace").strip().splitlines()[-3:]) or "no output"
        raise AnalysisError(f"ffmpeg could not decode {path.name}: {tail}")
    return proc.stdout


def _pcm(path: Path) -> array:
    raw = _decode_raw(path, ["-vn", "-ac", "1", "-ar", str(AUDIO_HZ), "-f", "s16le"])
    samples = array("h")
    samples.frombytes(raw[: len(raw) - len(raw) % 2])
    if sys.byteorder == "big":
        samples.byteswap()
    return samples


def _gray_frames(path: Path) -> list[bytes]:
    w, h = MOTION_SIZE
    raw = _decode_raw(
        path, ["-an", "-vf", f"fps={MOTION_FPS},scale={w}:{h}:flags=area,format=gray", "-pix_fmt", "gray", "-f", "rawvideo"]
    )
    size = w * h
    return [raw[i : i + size] for i in range(0, len(raw) - size + 1, size)]


# ---- motion ----------------------------------------------------------------------------------------------------------


def motion_profile(path: Path, duration_s: float) -> tuple[list[float], list[float]]:
    """``(energy per 0.5 s, cut times)`` of a clip: see the module doc. A frame that is a cut is left out of the energy: a
    change of shot is not movement, and would make a window with a cut in it look like the liveliest one."""
    frames = _gray_frames(path)
    changes = [sum(map(abs, map(sub, frames[i], frames[i - 1]))) / len(frames[i]) for i in range(1, len(frames))]
    cut_at: set[int] = set()
    reach = MOTION_FPS  # one second either side
    for i, change in enumerate(changes):
        if change < CUT_MIN_CHANGE:
            continue
        around = changes[max(0, i - reach) : i] + changes[i + 1 : i + 1 + reach]
        if not around or change >= CUT_OVER_MEDIAN * max(statistics.median(around), 1e-9):
            cut_at.add(i)
    bins = max(1, math.ceil(duration_s / MOTION_STEP_S - 1e-9))
    sums, counts = [0.0] * bins, [0] * bins
    for i, change in enumerate(changes):
        if i in cut_at:
            continue
        b = min(bins - 1, int(((i + 1) / MOTION_FPS) / MOTION_STEP_S))
        sums[b] += change
        counts[b] += 1
    energy = [round(s / c, 3) if c else 0.0 for s, c in zip(sums, counts)]
    return energy, [round((i + 1) / MOTION_FPS, 3) for i in sorted(cut_at)]


# ---- beat ------------------------------------------------------------------------------------------------------------


def _onset_envelope(samples: array) -> list[float]:
    """The rise of the log mean-square energy per 10 ms of the pre-emphasised signal (>= 0)."""
    emphasised = [0, *map(sub, samples[1:], samples[:-1])]
    levels = [
        math.log10(1.0 + sum(map(mul, c, c)) / HOP)
        for c in (emphasised[i : i + HOP] for i in range(0, len(emphasised) - HOP + 1, HOP))
    ]
    return [0.0] + [max(0.0, b - a) for a, b in zip(levels, levels[1:])]


def _autocorrelation(env: list[float], lag: int) -> float:
    n = len(env) - lag
    return sum(map(mul, env[:n], env[lag:])) / n if n > 0 else 0.0


def estimate_beat(samples: array) -> tuple[float | None, list[float], int]:
    """``(bpm or None, beat times in seconds, onset count)`` of mono PCM at 8 kHz (see the module doc)."""
    env = _onset_envelope(samples)
    onsets = sum(1 for i in range(1, len(env) - 1) if env[i] >= MIN_ONSET and env[i] >= env[i - 1] and env[i] > env[i + 1])
    lo, hi = (round(6000.0 / b) for b in reversed(BPM_SEARCH))  # lags in 10 ms hops: 33..100
    if len(env) < 2 * hi or max(env, default=0.0) < MIN_ONSET:
        return None, [], onsets
    zero = _autocorrelation(env, 0)
    r = {lag: _autocorrelation(env, lag) for lag in range(lo - 1, hi + 2)}
    best = max(r[lag] for lag in range(lo, hi + 1))
    if zero <= 0 or best / zero < MIN_PULSE:
        return None, [], onsets
    lag = next(l for l in range(lo, hi + 1) if r[l] >= 0.95 * best)  # near-ties go to the shorter lag (the faster pulse)
    while lag < hi and r[lag + 1] > r[lag]:  # climb to the top of that peak
        lag += 1
    denom = r[lag - 1] - 2 * r[lag] + r[lag + 1]
    refined = lag + (0.5 * (r[lag - 1] - r[lag + 1]) / denom if denom < 0 else 0.0)
    bpm = 6000.0 / refined
    while bpm < BPM_FOLD[0]:
        bpm *= 2
    while bpm >= BPM_FOLD[1]:
        bpm /= 2
    return round(bpm, 1), _track_beats(env, 6000.0 / bpm), onsets


def _best_phase(env: list[float], period: float) -> int:
    """The offset (in hops) within one period at which the onsets of every period line up best."""
    n = len(env)

    def score(p: int) -> float:
        total, k = 0.0, 0
        while (i := int(round(p + k * period))) < n:
            total += max(env[max(0, i - 1) : i + 2])
            k += 1
        return total

    return max(range(max(1, int(period))), key=score)


def _track_beats(env: list[float], period: float) -> list[float]:
    """Beat times: the best phase of ``period`` hops, then each beat pulled to the strongest onset near its prediction."""
    n = len(env)
    reach = max(2, int(0.12 * period))
    beats: list[float] = []
    t = float(_best_phase(env, period))
    while t < n:
        centre = int(round(t))
        window = env[max(0, centre - reach) : min(n, centre + reach + 1)]
        if window and max(window) >= MIN_ONSET:
            centre = max(0, centre - reach) + window.index(max(window))
        beats.append(round(centre * HOP_S, 3))
        t = centre + period
    return beats


# ---- the best window -----------------------------------------------------------------------------------------------


def _nearest(times: list[float], t: float) -> float:
    return min(times, key=lambda b: abs(b - t))


def best_window(
    energy: list[float], cuts: list[float], beats: list[float], bpm: float | None, duration_s: float
) -> dict[str, Any]:
    """The 6-9 s window to give Genjutsu (see the module doc): ``start_s``, ``end_s``, ``duration_s``, ``motion`` (its mean
    energy), ``cuts_inside`` and ``aligned_to_beats``."""
    lo, hi = WINDOW_SECONDS

    def inside(start: float, end: float) -> int:
        return sum(1 for c in cuts if start + CUT_EDGE_S < c < end - CUT_EDGE_S)

    def mean_energy(start: float, end: float) -> float:
        a, b = int(round(start / MOTION_STEP_S)), int(round(end / MOTION_STEP_S))
        part = energy[a:b]
        return sum(part) / len(part) if part else 0.0

    if duration_s <= lo + 1e-9:
        return {
            "start_s": 0.0, "end_s": round(duration_s, 3), "duration_s": round(duration_s, 3),
            "motion": round(mean_energy(0.0, duration_s), 3), "cuts_inside": inside(0.0, duration_s), "aligned_to_beats": False,
            "note": "the clip is not longer than 6 s: the whole clip is the window",
        }  # fmt: skip

    candidates: list[tuple[float, float, float, float, int]] = []
    length = lo
    while length <= min(hi, duration_s) + 1e-9:
        start = 0.0
        while start + length <= duration_s + 1e-9:
            end = start + length
            n_cuts = inside(start, end)
            candidates.append((mean_energy(start, end) * CUT_DISCOUNT**n_cuts, length, start, mean_energy(start, end), n_cuts))
            start += WINDOW_STEP_S
        length += WINDOW_STEP_S
    score, length, start, motion, n_cuts = min(candidates, key=lambda c: (-round(c[0], 6), c[1], c[2]))
    end = start + length
    aligned = False
    if beats and bpm:
        s2 = _nearest(beats, start)
        e2 = _nearest(beats, end)
        if abs(s2 - start) <= 30 / bpm and abs(e2 - end) <= 30 / bpm and lo - 1e-9 <= e2 - s2 <= hi + 1e-9 and e2 <= duration_s + 1e-9:
            start, end, aligned = s2, e2, True
            motion, n_cuts = mean_energy(start, end), inside(start, end)
    return {
        "start_s": round(start, 3), "end_s": round(end, 3), "duration_s": round(end - start, 3),
        "motion": round(motion, 3), "cuts_inside": n_cuts, "aligned_to_beats": aligned,
    }  # fmt: skip


# ---- the whole analysis ----------------------------------------------------------------------------------------------


def analyze_clip(path: str | Path, sheet: str | Path) -> dict[str, Any]:
    """Analyse the video at ``path``: JSON-ready dict (see the module doc), contact sheet written to ``sheet`` (.png / .jpg).

    ``QAError`` for a file that is missing or not a video; ``AnalysisError`` for one longer than 3 minutes or that ffmpeg
    cannot decode; ``ValueError`` for a bad sheet extension.
    """
    path = Path(path)
    if Path(sheet).suffix.lower() not in {".png", ".jpg", ".jpeg"}:  # before the minutes of work, not after them
        raise ValueError(f"the contact sheet must be a .png or .jpg file, got {Path(sheet).name!r}")
    report: TechReport = probe(path, loudness=False)
    if report.duration_s > MAX_ANALYSIS_SECONDS:
        raise AnalysisError(f"the clip is {report.duration_s:.0f} s long: the analysis takes at most {MAX_ANALYSIS_SECONDS:.0f} s")
    energy, cuts = motion_profile(path, report.duration_s)
    bpm: float | None = None
    beats: list[float] = []
    onsets = 0
    if report.has_audio:
        bpm, beats, onsets = estimate_beat(_pcm(path))
    window = best_window(energy, cuts, beats, bpm, report.duration_s)
    sheet_path, times = contact_sheet(path, sheet, cols=3, rows=3, width=320)
    return {
        "file": str(path),
        "duration_s": round(report.duration_s, 3),
        "width": report.width,
        "height": report.height,
        "fps": round(report.fps, 3),
        "has_audio": report.has_audio,
        "source_problems": check_source(report),
        "motion": {
            "step_s": MOTION_STEP_S,
            "energy": energy,
            "mean": round(statistics.fmean(energy), 3) if energy else 0.0,
            "peak": max(energy, default=0.0),
            "cuts": cuts,
        },
        "audio": {"bpm": bpm, "beats": beats[:MAX_BEATS_LISTED], "beat_count": len(beats), "onsets": onsets},
        "best_window": window,
        "contact_sheet": {"path": str(sheet_path), "cols": 3, "rows": 3, "times": times},
    }


__all__ = ["AnalysisError", "QAError", "analyze_clip", "best_window", "estimate_beat", "motion_profile"]
