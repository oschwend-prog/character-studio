"""The weekly review in the cloud (learning plan ``docs/launch/measurement-and-learning-plan.md`` sections 3.2, 3.8, 4.1-4.3, 6.1 and build
items 10-11): ``studio review weekly`` and ``studio learn score-test``. Deterministic code only, no Claude: the Monday cloud job
(``.github/workflows/studio-weekly.yml``) runs it.

(This docstring grows with the module: see the sections below.)
"""

from __future__ import annotations

import statistics
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

import typer

from studio.cli_support import emit, open_store
from studio.config import LONDON, now_london
from studio.metrics import post_reads, posted_at
from studio.models import Platform, PostStatus, Snapshot
from studio.store import Store

INSTAGRAM = Platform.instagram.value

# ---- test A: the pre-registered looks and thresholds (plan 3.2; FROZEN: never "improve" one, change it only as a new dated version) ----

SCORE_INTERIM_N, SCORE_FINAL_N = 20, 40  # the looks: the first 20 observations, then the first 40
SCORE_INTERIM_VALIDATED_RHO, SCORE_INTERIM_FAILED_RHO = 0.45, 0.0  # at 20: rho >= 0.45 validated, rho <= 0 failed
SCORE_FINAL_VALIDATED_RHO = 0.31  # at 40: rho >= 0.31 validated, else failed
SCORE_MIN_SPAN = 15  # the middle 80 % of the scores spans fewer points than this: uninformative (never failed)
SCORE_BUCKET_WIDTH = 20
OUTLIER_LAG = timedelta(days=7)  # a clip's outlier_x exists 7 days after its post (``metrics.views_at_7d``)

# ---- the mechanism floors: the plan's procedure (3.8, FROZEN) ----

FLOORS_FROM, FLOORS_TO = date(2026, 10, 5), date(2026, 10, 18)  # weeks 1-2: Mon 5 Oct to Sun 18 Oct (London days)
FLOORS_APPLY_FROM = date(2026, 10, 19)  # week 3: a post from this day on is diagnosed against the floors
FLOOR_MIN_OWN = 4  # fewer than 4 readings for a character: the studio-wide median
FLOOR_MIN_STUDIO = 6  # fewer than 6 readings studio-wide: the metric is pending
FLOOR_NO_DATA = "no data in the cloud yet"
# metric -> its kind: a floor (a post should reach it) or a ceiling (a post should stay under it)
FLOOR_METRICS: tuple[tuple[str, str], ...] = (
    ("sends_per_1k", "floor"), ("follows_per_1k", "floor"), ("watched_pct", "floor"), ("skip_rate", "ceiling"),
)
FLOOR_FAILS = {"skip_rate": "hook", "watched_pct": "hold", "sends_per_1k": "sends", "follows_per_1k": "follows"}  # what failing each one means
FLOOR_FLAG_MIN = 2  # a post below two of them is flagged


# ---- Spearman (no new dependency) -------------------------------------------------------------------------------------------------------


def average_ranks(values: Sequence[float]) -> list[float]:
    """The ranks (from 1) of ``values``; values that tie share the mean of the places they cover."""
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        mean_rank = (i + j) / 2 + 1
        for k in range(i, j + 1):
            ranks[order[k]] = mean_rank
        i = j + 1
    return ranks


def spearman(xs: Sequence[float], ys: Sequence[float]) -> float:
    """Spearman's rho: the Pearson correlation of the average ranks. 0.0 when either side does not vary (no association to
    speak of) or there are fewer than 2 pairs; ``ValueError`` for lists of different lengths."""
    if len(xs) != len(ys):
        raise ValueError(f"spearman needs pairs: {len(xs)} against {len(ys)}")
    if len(xs) < 2:
        return 0.0
    rx, ry = average_ranks(xs), average_ranks(ys)
    mx, my = statistics.fmean(rx), statistics.fmean(ry)
    sxx = sum((a - mx) ** 2 for a in rx)
    syy = sum((b - my) ** 2 for b in ry)
    if sxx == 0 or syy == 0:
        return 0.0
    return sum((a - mx) * (b - my) for a, b in zip(rx, ry, strict=True)) / (sxx * syy) ** 0.5


# ---- test A: the score test ------------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class ScoreObservation:
    """One posted drop with its check score and its Instagram ``outlier_x``; ``available_at`` is when that figure became available
    (the post's time + 7 days), which orders the observations. ``potential`` / ``swap`` are the score's two parts (None when the
    clip does not carry them)."""

    clip_id: str
    available_at: datetime
    score: int
    outlier_x: float
    potential: int | None = None
    swap: int | None = None


def middle_span(scores: Sequence[float]) -> float:
    """How many points the middle 80 % of the scores span: the lowest and the highest tenth (``n // 10`` each) are left out, then
    highest minus lowest. 0 for no scores."""
    ordered = sorted(scores)
    k = len(ordered) // 10
    middle = ordered[k : len(ordered) - k]
    return float(middle[-1] - middle[0]) if middle else 0.0


def look_label(rho: float, span: float, look: int) -> str:
    """The label at a look (plan 3.2, frozen). A middle 80 % of the scores under 15 points wide is ``uninformative`` (never
    ``failed``: a score nobody varied cannot be failed). At the interim look (20): rho >= 0.45 ``validated``, rho <= 0 ``failed``,
    else ``unproven``. At the final look (40): rho >= 0.31 ``validated``, else ``failed``."""
    if span < SCORE_MIN_SPAN:
        return "uninformative"
    if look == SCORE_INTERIM_N:
        if rho >= SCORE_INTERIM_VALIDATED_RHO:
            return "validated"
        return "failed" if rho <= SCORE_INTERIM_FAILED_RHO else "unproven"
    return "validated" if rho >= SCORE_FINAL_VALIDATED_RHO else "failed"


def _median(values: Iterable[float]) -> float | None:
    data = list(values)
    return statistics.median(data) if data else None


def _bucket_range(score: int) -> tuple[int, str]:
    last = 100 // SCORE_BUCKET_WIDTH - 1  # the top bucket also holds a score of 100
    index = min(score // SCORE_BUCKET_WIDTH, last)
    low = index * SCORE_BUCKET_WIDTH
    return index, f"{low}-{100 if index == last else low + SCORE_BUCKET_WIDTH - 1}"


def score_buckets(sample: Sequence[ScoreObservation]) -> list[dict[str, Any]]:
    """The median ``outlier_x`` per score bucket of 20 points (0-19, 20-39, 40-59, 60-79, 80-100); a bucket with no clip is left out."""
    groups: dict[int, tuple[str, list[float]]] = {}
    for o in sample:
        index, label = _bucket_range(o.score)
        groups.setdefault(index, (label, []))[1].append(o.outlier_x)
    return [
        {"range": label, "n": len(xs), "median_outlier_x": round(statistics.median(xs), 3)}
        for _, (label, xs) in sorted(groups.items())
    ]


def _rho_of(sample: Sequence[ScoreObservation], part: str) -> float | None:
    pairs = [(getattr(o, part), o.outlier_x) for o in sample if getattr(o, part) is not None]
    return round(spearman([p for p, _ in pairs], [x for _, x in pairs]), 4) if len(pairs) >= 2 else None


def score_test(observations: Iterable[ScoreObservation]) -> dict[str, Any]:
    """Test A (plan 3.2): does a higher ``score_total`` go with a higher ``outlier_x``?

    The observations are put in the order their ``outlier_x`` became available (then the clip id). **No peeking**: before 20 only the
    count is shown; the interim look judges the first 20 and is never recomputed on 21..39; the final look judges the first 40 and
    never moves again. A ``validated`` or ``failed`` interim ends the test (the label sticks, whatever comes later). ``uninformative``
    (the middle 80 % of the scores spans under 15 points) is not a decision: the test goes on to the next look.

    Returns ``{"label", "n", "needed", "look", "rho", "rho_potential", "rho_swap", "buckets", "note"}``: ``label`` one of
    ``unproven`` / ``validated`` / ``failed`` / ``uninformative``; ``needed`` the n of the next look (20, then 40); ``look`` the look the
    label comes from (None before the first); the rho of the total, of ``potential`` and of ``swap`` (each None before a look, or with
    fewer than 2 values) and the median ``outlier_x`` per score bucket are reported on the looked-at sample only: report, no decision.
    """
    ordered = sorted(observations, key=lambda o: (o.available_at, o.clip_id))
    n = len(ordered)
    result: dict[str, Any] = {
        "label": "unproven", "n": n, "needed": SCORE_INTERIM_N, "look": None,
        "rho": None, "rho_potential": None, "rho_swap": None, "buckets": [], "note": "",
    }
    if n < SCORE_INTERIM_N:
        result["note"] = f"{n} of {SCORE_INTERIM_N} posted drops with a score and a 7-day figure so far. Not a verdict."
        return result

    def read(look: int) -> tuple[str, float, float, list[ScoreObservation]]:
        sample = ordered[:look]
        rho = spearman([o.score for o in sample], [o.outlier_x for o in sample])
        span = middle_span([o.score for o in sample])
        return look_label(rho, span, look), rho, span, sample

    label, rho, span, sample = read(SCORE_INTERIM_N)
    look, needed = SCORE_INTERIM_N, SCORE_INTERIM_N
    if label not in ("validated", "failed"):  # the interim did not end the test: it goes on to 40
        needed = SCORE_FINAL_N
        if n >= SCORE_FINAL_N:
            label, rho, span, sample = read(SCORE_FINAL_N)
            look = SCORE_FINAL_N
    name = "interim look at 20" if look == SCORE_INTERIM_N else "final look at 40"
    if label == "uninformative":
        note = (
            f"Uninformative at the {name}: the middle 80 % of the scores spans {span:g} points (under {SCORE_MIN_SPAN}), so the score "
            f"cannot be judged: raise the exploration picks."
        )
    elif label == "validated":
        bar = SCORE_INTERIM_VALIDATED_RHO if look == SCORE_INTERIM_N else SCORE_FINAL_VALIDATED_RHO
        note = f"Validated at the {name}: rho {rho:.2f} is at least {bar}."
    elif label == "failed":
        bar = SCORE_INTERIM_FAILED_RHO if look == SCORE_INTERIM_N else SCORE_FINAL_VALIDATED_RHO
        note = f"Failed at the {name}: rho {rho:.2f} is " + (f"{bar:g} or less." if look == SCORE_INTERIM_N else f"under {bar}.")
    else:
        note = (
            f"Interim look at 20: rho {rho:.2f}, between {SCORE_INTERIM_FAILED_RHO:g} and {SCORE_INTERIM_VALIDATED_RHO}, so unproven "
            f"until {SCORE_FINAL_N} ({n} of {SCORE_FINAL_N} so far). Not a verdict."
        )
    result.update(
        label=label, needed=needed, look=look, rho=round(rho, 4), rho_potential=_rho_of(sample, "potential"),
        rho_swap=_rho_of(sample, "swap"), buckets=score_buckets(sample), note=note,
    )
    return result


def score_observations(store: Store) -> list[ScoreObservation]:
    """The test's observations from the data: every posted drop (``features['drop']``) with a ``score_total`` and an Instagram
    ``outlier_x``, pooled over the characters. A clip's figure is the best ``outlier_x`` of its Instagram posts (``metrics.post_reads``:
    the post's 7-day views against its own account's earlier posts); a clip only on TikTok, with no score or with no 7-day figure yet
    is not an observation. The figure became available 7 days after the post. Versions of a clip for other characters are clips of
    their own, so they count separately."""
    best: dict[str, Any] = {}
    for r in post_reads(store):
        if r.platform == INSTAGRAM and r.outlier_x is not None and (r.clip_id not in best or r.outlier_x > best[r.clip_id].outlier_x):
            best[r.clip_id] = r
    out: list[ScoreObservation] = []
    for clip in store.list_clips():
        read = best.get(clip.id)
        total = clip.features.get("score_total")
        if read is None or clip.features.get("drop") is not True or isinstance(total, bool) or not isinstance(total, int):
            continue
        part = {k: clip.features.get(f"score_{k}") for k in ("potential", "swap")}
        out.append(
            ScoreObservation(
                clip_id=clip.id, available_at=read.posted_at + OUTLIER_LAG, score=total, outlier_x=float(read.outlier_x),
                potential=part["potential"] if isinstance(part["potential"], int) and not isinstance(part["potential"], bool) else None,
                swap=part["swap"] if isinstance(part["swap"], int) and not isinstance(part["swap"], bool) else None,
            )
        )
    return out


def score_test_command() -> None:
    """Test A, the score test (plan 3.2): the label, n against the looks, rho and the median outlier_x per score bucket. Read-only."""
    emit(score_test(score_observations(open_store())))


# ---- the mechanism floors (plan 3.8) ---------------------------------------------------------------------------------------------------


def floors_due(week_monday: date) -> bool:
    """Whether the review of the week starting ``week_monday`` is the one that sets the floors: its Sunday is Sun 18 Oct or later."""
    return week_monday + timedelta(days=6) >= FLOORS_TO


def post_metric_values(snapshots: Iterable[Snapshot]) -> dict[str, float]:
    """A post's floor metrics from its snapshots, each from the LATEST snapshot that reports what it needs (a counter only grows):
    ``sends_per_1k`` = shares / views x 1000 and ``follows_per_1k`` = follows / views x 1000 (a snapshot with views above 0 and the
    count), ``watched_pct`` and ``skip_rate`` as reported. A metric nothing reported is left out, never 0."""
    out: dict[str, float] = {}
    for snap in sorted((s for s in snapshots if s.captured_at is not None), key=lambda s: s.captured_at, reverse=True):
        if snap.views is not None and snap.views > 0:
            if "sends_per_1k" not in out and snap.shares is not None:
                out["sends_per_1k"] = snap.shares / snap.views * 1000
            if "follows_per_1k" not in out and snap.follows is not None:
                out["follows_per_1k"] = snap.follows / snap.views * 1000
        if "watched_pct" not in out and snap.watched_pct is not None:
            out["watched_pct"] = float(snap.watched_pct)
        if "skip_rate" not in out and snap.skip_rate is not None:
            out["skip_rate"] = float(snap.skip_rate)
    return out


def floor_readings(store: Store, start: date = FLOORS_FROM, end: date = FLOORS_TO) -> dict[str, dict[str, list[float]]]:
    """``{metric: {character: [one reading per post]}}`` of the Instagram posts posted from ``start`` to ``end`` (London days, both
    included): the baseline of weeks 1-2. A post that has no reading of a metric is not in its list."""
    out: dict[str, dict[str, list[float]]] = {}
    for account in store.accounts():
        if account.platform.value != INSTAGRAM:
            continue
        for post in store.list_posts(account_id=account.id, status=PostStatus.posted):
            if not start <= posted_at(post).astimezone(LONDON).date() <= end:
                continue
            for metric, value in post_metric_values(store.snapshots_for(post.id)).items():
                out.setdefault(metric, {}).setdefault(account.character_slug, []).append(value)
    return out


def _fixed(entry: Any) -> bool:
    return isinstance(entry, dict) and entry.get("status") == "fixed" and isinstance(entry.get("value"), (int, float))


def _pending_reason(n: int) -> str:
    return FLOOR_NO_DATA if n == 0 else f"{n} of {FLOOR_MIN_STUDIO} readings studio-wide so far"


def compute_floors(
    readings: dict[str, dict[str, list[float]]], characters: Sequence[str], *, today: date, previous: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """The floors (plan 3.8, frozen). ``readings`` is ``floor_readings``'s ``{metric: {character: [values]}}``; ``previous`` the
    ``floors`` of an earlier weekly run.

    Per metric: **studio-wide** the median of every reading once there are at least 6 (else it is ``pending`` with the reason: none
    at all means "no data in the cloud yet"); **per character** the median of his own readings when he has at least 4, else the
    studio-wide median. A pending metric stays pending for everybody (even a character with 4 readings) until the 6th reading
    arrives; the day a metric is fixed is written down (``fixed_on``, ``today``). **A fixed floor is never recomputed**: whatever
    ``previous`` has fixed is copied as it is, and only pending ones are filled. A character who joins later gets the fixed
    studio-wide value (or his own median if he already has 4 readings).

    ``{"computed": True, "basis", "fixed_on": {metric: date|None}, "studio": {metric: entry}, "characters": {slug: {metric: entry}}}``;
    an entry is ``{"kind", "status": "fixed", "value", "n", ...}`` or ``{"kind", "status": "pending", "n", "needed", "reason"}``.
    """
    prev = previous or {}
    prev_studio = prev.get("studio") or {}
    prev_chars = prev.get("characters") or {}
    prev_fixed_on = prev.get("fixed_on") or {}
    studio: dict[str, Any] = {}
    fixed_on: dict[str, str | None] = {}
    chars: dict[str, dict[str, Any]] = {slug: {} for slug in characters}
    for metric, kind in FLOOR_METRICS:
        by_character = readings.get(metric, {})
        pooled = [v for values in by_character.values() for v in values]
        if _fixed(prev_studio.get(metric)):
            studio[metric] = dict(prev_studio[metric])
            fixed_on[metric] = prev_fixed_on.get(metric) or studio[metric].get("fixed_on")
        elif len(pooled) >= FLOOR_MIN_STUDIO:
            studio[metric] = {"kind": kind, "status": "fixed", "value": statistics.median(pooled), "n": len(pooled), "fixed_on": today.isoformat()}
            fixed_on[metric] = today.isoformat()
        else:
            studio[metric] = {
                "kind": kind, "status": "pending", "n": len(pooled), "needed": FLOOR_MIN_STUDIO, "reason": _pending_reason(len(pooled)),
            }
            fixed_on[metric] = None
        for slug in characters:
            earlier = (prev_chars.get(slug) or {}).get(metric)
            own = by_character.get(slug, [])
            if _fixed(earlier):
                chars[slug][metric] = dict(earlier)
            elif studio[metric]["status"] != "fixed":
                chars[slug][metric] = {
                    "kind": kind, "status": "pending", "n": len(own), "needed": FLOOR_MIN_STUDIO, "reason": studio[metric]["reason"],
                }
            elif len(own) >= FLOOR_MIN_OWN:
                chars[slug][metric] = {"kind": kind, "status": "fixed", "value": statistics.median(own), "n": len(own), "basis": "character"}
            else:
                chars[slug][metric] = {"kind": kind, "status": "fixed", "value": studio[metric]["value"], "n": len(own), "basis": "studio"}
    return {
        "computed": True,
        "basis": {"from": FLOORS_FROM.isoformat(), "to": FLOORS_TO.isoformat(), "platform": INSTAGRAM},
        "fixed_on": fixed_on, "studio": studio, "characters": chars,
    }


def floor_failures(values: dict[str, float], floors: dict[str, Any]) -> list[str]:
    """What a post fails against a character's floors, in the order hook, hold, sends, follows: the skip rate above its ceiling
    (the hook), the watched share, the sends or the follows per 1K below their floors. A metric the post has no reading of, or whose
    floor is pending, is never failed. Exactly on the line is not below it."""
    out = []
    for metric, name in FLOOR_FAILS.items():
        entry, value = floors.get(metric), values.get(metric)
        if value is None or not _fixed(entry):
            continue
        if (value > entry["value"]) if entry.get("kind") == "ceiling" else (value < entry["value"]):
            out.append(name)
    return out


def flagged(failures: Sequence[str]) -> bool:
    """A post is flagged when it is below two floors or more (they diagnose; they never kill or change anything)."""
    return len(failures) >= FLOOR_FLAG_MIN
