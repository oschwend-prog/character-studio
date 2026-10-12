"""The weekly review in the cloud (learning plan ``docs/launch/measurement-and-learning-plan.md`` sections 3.2, 3.8, 4.1-4.3, 6.1 and build
items 10-11): ``studio review weekly`` and ``studio learn score-test``. Deterministic code only, no Claude: the Monday cloud job
(``.github/workflows/studio-weekly.yml``) runs it.

(This docstring grows with the module: see the sections below.)
"""

from __future__ import annotations

import json
import re
import statistics
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Annotated, Any

import typer

from studio import budget, experiments, health, learn, review
from studio.cli_support import emit, fail, open_store
from studio.config import LONDON, now_london
from studio.metrics import MIN_PRIORS, post_reads, posted_at
from studio.models import HOOK_PATTERNS, Clip, ClipState, Platform, PostStatus, Run, RunKind, RunStatus, Snapshot
from studio.store import Store

INSTAGRAM = Platform.instagram.value

# ---- test A: the pre-registered looks and thresholds (plan 3.2; FROZEN: never "improve" one, change it only as a new dated version) ----

SCORE_INTERIM_N, SCORE_FINAL_N = 20, 40  # the looks: the first 20 observations, then the first 40
SCORE_INTERIM_VALIDATED_RHO, SCORE_INTERIM_FAILED_RHO = 0.45, 0.0  # at 20: rho >= 0.45 validated, rho <= 0 failed
SCORE_FINAL_VALIDATED_RHO = 0.31  # at 40: rho >= 0.31 validated, else failed
SCORE_MIN_SPAN = 15  # the middle 80 % of the scores spans fewer points than this: uninformative (never failed)
SCORE_BUCKET_WIDTH = 20
OUTLIER_LAG = timedelta(days=7)  # a clip's outlier_x exists 7 days after its post (``metrics.views_at_7d``)
WEEK_LEN = timedelta(days=7)

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

# ---- what the digest and the proposals call a finding: the plan's numbers (4.3 and 3.3, FROZEN) ----

DO_MORE_LIFT, DO_MORE_MIN_N = 1.5, 5  # 4.3 entry 2-3: a lift of 1.5 with 5 clips on each side
STOP_LIFT, STOP_MIN_N = 0.7, 8  # the kill line: a lift of 0.7 or less with 8 on each side
RULE_READY_LIFT = 1.2  # 4.3 entry 4: next week's posts, added in, still show at least 1.2x
CALL_MIN_POSTS = 10  # under 10 measured posts line 5 says "too few to call" (SKILL.md)
PLAYBOOK_MIN_POSTS = 5  # a playbook rule needs 5 posts behind it (SKILL.md step 6)
ARM_RETIRE_MIN_USES, ARM_RETIRE_MAX_WIN_RATE, ARM_RETIRE_MAX_MEDIAN = 10, 0.20, 0.7  # 3.3: retire an arm
ARMS_MIN = 2  # the registry needs at least two arms per character
# Tags that say who chose or how a clip was made, not what is in it: a lift on one of them is no rule about clips.
NOT_A_RULE = frozenset({"hit_rules_version", "explore_pick", "hook_by", "version_index", "hook_text", "hook_index"})


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


# ---- lifts against the others, rule candidates, the second look (plan 4.3) -------------------------------------------------------------


def _value_key(value: Any) -> str:
    return json.dumps(value, sort_keys=True, default=str)  # True and 1 stay apart (as in review.feature_lifts)


def _shown(value: Any) -> str:
    return str(value).lower() if isinstance(value, bool) else str(value)


@dataclass(frozen=True)
class SideLift:
    """One tag value measured the way 4.3 writes it: ``n`` measured clips carry ``feature == value`` (``median``), ``n_others`` carry
    the tag with another value (``median_others``); ``lift`` is the first median over the second (None when there is no other
    side, or its median is 0). ``hits`` counts the followers with ``outlier_x >= 3``. A clip without the tag is on neither side."""

    feature: str
    value: Any
    n: int
    n_others: int
    median: float
    median_others: float | None
    hits: int
    clip_ids: tuple[str, ...]

    @property
    def lift(self) -> float | None:
        return self.median / self.median_others if self.median_others else None

    @property
    def key(self) -> str:
        return f"{self.feature}={_value_key(self.value)}"

    @property
    def label(self) -> str:
        return f"{self.feature} = {_shown(self.value)}"


def side_lifts(clips: Sequence[Clip], min_n: int = review.LIFT_MIN_N) -> list[SideLift]:
    """One ``SideLift`` per (tag, value) that at least ``min_n`` measured clips carry (the groups of ``review.feature_lifts``), each
    set against the clips that carry the same tag with another value. Same order as ``feature_lifts``."""
    rated = [(c, x) for c in clips if (x := review.clip_outlier_x(c)) is not None]
    out: list[SideLift] = []
    for lift in review.feature_lifts(list(clips), min_n=min_n):
        key = _value_key(lift.value)
        with_x: list[tuple[Clip, float]] = []
        others: list[float] = []
        for clip, x in rated:
            value = clip.features.get(lift.feature)
            if value is None:
                continue
            if _value_key(value) == key:
                with_x.append((clip, x))
            else:
                others.append(x)
        out.append(
            SideLift(
                feature=lift.feature, value=lift.value, n=len(with_x), n_others=len(others),
                median=float(statistics.median(x for _, x in with_x)),
                median_others=float(statistics.median(others)) if others else None,
                hits=sum(x >= review.HIT_X for _, x in with_x), clip_ids=tuple(sorted(str(c.id) for c, _ in with_x)),
            )
        )
    return out


def _content(lifts: Iterable[SideLift]) -> list[SideLift]:
    return [lf for lf in lifts if lf.feature not in NOT_A_RULE and lf.lift is not None]


def do_more(lifts: Iterable[SideLift]) -> SideLift | None:
    """The strongest DO MORE: a lift of at least 1.5 with at least 5 clips on each side (ties: more clips, then the name)."""
    ok = [lf for lf in _content(lifts) if lf.lift >= DO_MORE_LIFT and lf.n >= DO_MORE_MIN_N and lf.n_others >= DO_MORE_MIN_N]  # type: ignore[operator]
    return min(ok, key=lambda lf: (-lf.lift, -lf.n, lf.feature, str(lf.value)), default=None)  # type: ignore[operator]


def stop(lifts: Iterable[SideLift]) -> SideLift | None:
    """The weakest STOP: a lift of at most 0.7 with at least 8 clips on each side (ties: more clips, then the name)."""
    ok = [lf for lf in _content(lifts) if lf.lift <= STOP_LIFT and lf.n >= STOP_MIN_N and lf.n_others >= STOP_MIN_N]  # type: ignore[operator]
    return min(ok, key=lambda lf: (lf.lift, -lf.n, lf.feature, str(lf.value)), default=None)


def rule_candidates(lifts: Iterable[SideLift]) -> list[SideLift]:
    """Entry conditions 1-3 of a rule in ``config/hit_rules.md`` (4.3): a tag measures it, at least 5 measured clips on each side, a
    median at least 1.5x the others', and at least one hit among the clips that follow it."""
    return [
        lf for lf in _content(lifts)
        if lf.lift >= DO_MORE_LIFT and lf.n >= DO_MORE_MIN_N and lf.n_others >= DO_MORE_MIN_N and lf.hits >= 1  # type: ignore[operator]
    ]


def _record(lf: SideLift, *, status: str, since: str, measured: int, repeat: bool = False) -> dict[str, Any]:
    rec: dict[str, Any] = {
        "scope": "studio", "feature": lf.feature, "value": lf.value, "key": lf.key, "label": lf.label, "status": status,
        "n": lf.n, "n_others": lf.n_others, "median": round(lf.median, 3),
        "median_others": None if lf.median_others is None else round(lf.median_others, 3),
        "lift": None if lf.lift is None else round(lf.lift, 3), "hits": lf.hits, "clip_ids": list(lf.clip_ids),
        "measured": measured, "since_week": since,
    }
    if status == "ready":
        rec["repeat"] = repeat
    return rec


def update_candidates(
    previous: Sequence[Mapping[str, Any]], lifts: Sequence[SideLift], *, measured: int, week: date,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """The rule candidates after this week's look (4.3). ``previous`` are the candidates the last weekly run of an EARLIER week
    stored, ``lifts`` this week's ``side_lifts`` (all of them, ``min_n=1``) and ``measured`` the measured clips studio-wide now.

    A candidate (entry conditions 1-3 now) is stored with the week it first appeared. **Entry condition 4, the second look**: a
    candidate of the previous run whose lift, with the posts added since (``measured`` has grown), is still at least 1.2 with 5 clips
    on each side becomes ``ready``: a rule proposal. A rule that was already ``ready`` and still is stays ``ready`` (marked
    ``repeat``); one that fell below 1.2 leaves the list. Returns ``(everything to store, the ready ones)``."""
    by_value = {(lf.feature, _value_key(lf.value)): lf for lf in lifts}
    now = {lf.key: lf for lf in rule_candidates(lifts)}
    earlier = {str(c["key"]): c for c in previous if "key" in c and "feature" in c}
    stored: dict[str, dict[str, Any]] = {}
    for key, old in earlier.items():
        lf = by_value.get((str(old["feature"]), _value_key(old.get("value"))))
        was_ready = old.get("status") == "ready"
        grown = measured > int(old.get("measured", measured))
        if (
            lf is not None and lf.lift is not None and lf.lift >= RULE_READY_LIFT
            and lf.n >= DO_MORE_MIN_N and lf.n_others >= DO_MORE_MIN_N and (was_ready or grown)
        ):
            stored[key] = _record(lf, status="ready", since=str(old.get("since_week") or week.isoformat()), measured=measured, repeat=was_ready)
    for key, lf in now.items():
        if key not in stored:
            since = str(earlier[key].get("since_week")) if key in earlier else week.isoformat()
            stored[key] = _record(lf, status="candidate", since=since, measured=measured)
    ordered = [stored[k] for k in sorted(stored)]
    return ordered, [r for r in ordered if r["status"] == "ready"]


# ---- the hook arms: standings and the retire rule (plan 3.3) --------------------------------------------------------------------------


def arm_outliers(store: Store, registry: Any) -> dict[tuple[str, str], list[float]]:
    """``{(character, hook pattern): [outlier_x of its tallied clips]}``: the clips the bandit tallies (``learn.TALLIED_BY``, a real
    pattern, made on or after the registry's start) that have an ``outlier_x``."""
    out: dict[tuple[str, str], list[float]] = {}
    for clip in store.list_clips():
        f = clip.features
        pattern = f.get("hook_pattern")
        if pattern not in HOOK_PATTERNS or f.get("hook_by") not in learn.TALLIED_BY:
            continue
        if clip.created_at is not None and clip.created_at.astimezone(LONDON).date() < registry.start:
            continue
        if (x := review.clip_outlier_x(clip)) is not None:
            out.setdefault((clip.character_slug, str(pattern)), []).append(x)
    return out


def arm_standings(report: Mapping[str, Any], outliers: Mapping[tuple[str, str], Sequence[float]], *, min_uses: int) -> list[dict[str, Any]]:
    """Each character's arms from ``learn.arms_report``: wins, losses, uses, win rate (None with no use) and the median ``outlier_x``
    of the arm's tallied clips (None with none), the leading arm (best win rate, then more uses, then the registry's order; None when
    nothing is tallied) and the fewest uses of any arm (against ``min_uses``, the tally the plan wants per arm)."""
    rows: list[dict[str, Any]] = []
    for row in report.get("characters", []):
        slug = row["character"]
        arms = []
        for a in row["arms"]:
            xs = list(outliers.get((slug, a["pattern"]), ()))
            uses = int(a["uses"])
            arms.append(
                {
                    "pattern": a["pattern"], "wins": int(a["wins"]), "losses": int(a["losses"]), "uses": uses,
                    "win_rate": round(a["wins"] / uses, 4) if uses else None,
                    "median_outlier_x": round(statistics.median(xs), 3) if xs else None, "n_outlier": len(xs),
                }
            )
        used = [(i, a) for i, a in enumerate(arms) if a["uses"] > 0]
        best = min(used, key=lambda t: (-t[1]["win_rate"], -t[1]["uses"], t[0]), default=None)
        rows.append(
            {
                "character": slug, "mode": row.get("mode"), "readings": row.get("readings"), "readings_needed": row.get("readings_needed"),
                "tallied": row.get("tallied", 0), "pending": row.get("pending", 0), "min_uses": min_uses, "arms": arms,
                "leading": None if best is None else {"pattern": best[1]["pattern"], "wins": best[1]["wins"], "uses": best[1]["uses"]},
                "fewest_uses": min((a["uses"] for a in arms), default=0),
            }
        )
    return rows


def retire_proposals(standings: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """The only arm change the plan gives a rule for (3.3): retire an arm after at least 10 tallied uses with 20 % wins or fewer and a
    median ``outlier_x`` of 0.7 or less. Not when it would leave a character with fewer than two arms (the registry needs two).
    Adding an arm is only ever from outside evidence (a research doc), so there is no add rule here."""
    out: list[dict[str, Any]] = []
    for row in standings:
        if len(row["arms"]) <= ARMS_MIN:
            continue
        for a in row["arms"]:
            if (
                a["uses"] >= ARM_RETIRE_MIN_USES and a["win_rate"] is not None and a["win_rate"] <= ARM_RETIRE_MAX_WIN_RATE
                and a["median_outlier_x"] is not None and a["median_outlier_x"] <= ARM_RETIRE_MAX_MEDIAN
            ):
                out.append(
                    {
                        "kind": "arm_retire", "character": row["character"], "arm": a["pattern"], "uses": a["uses"], "wins": a["wins"],
                        "win_rate": a["win_rate"], "median_outlier_x": a["median_outlier_x"], "n_outlier": a["n_outlier"],
                    }
                )
    return out


# ---- the playbook (SKILL.md step 6: a rule needs 5 posts behind it) --------------------------------------------------------------------

_PLAYBOOK_SINCE = re.compile(r"^- \*\*(?P<title>.+?)\*\*: .* · since (?P<day>\d{4}-\d{2}-\d{2})$")
_PLAYBOOK_OWN_BARS = frozenset({"format_id", "hook_pattern"})  # they have their own lines (the format and hook bars)


def playbook_items(clips: Sequence[Clip]) -> tuple[list[dict[str, str]], list[str]]:
    """(the rules, the Watching lines) of one character's playbook, from his posted clips. A rule needs at least 5 measured posts
    behind it: a format the bar keeps (median 1.5 over 5) or kills (0.7 over 8), a hook pattern the bar calls proven (2 hits in its
    last 10 uses) with at least 5 measured uses, a tag value that beats the others (``DO_MORE``) or loses to them (``STOP``) with
    posts on both sides. Anything with fewer posts goes under Watching. Sorted, so the same data always gives the same text."""
    rules: list[dict[str, str]] = []
    watching: list[str] = []
    for fmt in review.format_stats(list(clips)):
        m = fmt.median_outlier_x
        if fmt.verdict in ("keep", "kill") and m is not None:
            verb = "Keep" if fmt.verdict == "keep" else "Stop"
            bar = f"{review.FORMAT_KEEP_MEDIAN:g}x over {review.FORMAT_KEEP_MIN_N}" if fmt.verdict == "keep" else f"{review.FORMAT_KILL_MEDIAN:g}x over {review.FORMAT_KILL_MIN_N}"
            rules.append({"title": f"{verb} format `{fmt.format_id}`", "detail": f"median outlier_x {m:.2f} over {fmt.n} posts (the {fmt.verdict} line is {bar})"})
        elif 0 < fmt.n < PLAYBOOK_MIN_POSTS and m is not None:
            watching.append(f"format `{fmt.format_id}`: {fmt.n} measured post{'s' if fmt.n != 1 else ''}, median outlier_x {m:.2f}")
    proven = review.hook_proven(list(clips))
    for pattern, xs in sorted(review.hook_uses(list(clips)).items()):
        hits = sum(x >= review.HIT_X for x in xs)
        if proven.get(pattern) and len(xs) >= PLAYBOOK_MIN_POSTS:
            rules.append(
                {
                    "title": f"Hook pattern `{pattern}` is proven",
                    "detail": f"{hits} hits in its last {len(xs)} uses (the bar: {review.HOOK_MIN_HITS} hits in the last {review.HOOK_WINDOW})",
                }
            )
        elif 0 < len(xs) < PLAYBOOK_MIN_POSTS:
            watching.append(f"hook pattern `{pattern}`: {len(xs)} measured post{'s' if len(xs) != 1 else ''}, {hits} hit{'s' if hits != 1 else ''}")
    lifts = [lf for lf in side_lifts(clips) if lf.feature not in _PLAYBOOK_OWN_BARS]
    for lf in _content(lifts):
        if lf.n_others < DO_MORE_MIN_N:
            continue
        detail = f"median outlier_x {lf.median:.2f} against {lf.median_others:.2f} for the others ({lf.n} against {lf.n_others} posts)"
        if lf.lift >= DO_MORE_LIFT:  # type: ignore[operator]
            rules.append({"title": f"Works: `{lf.feature}` = `{_shown(lf.value)}`", "detail": detail})
        elif lf.lift <= STOP_LIFT and lf.n >= STOP_MIN_N and lf.n_others >= STOP_MIN_N:  # type: ignore[operator]
            rules.append({"title": f"Avoid: `{lf.feature}` = `{_shown(lf.value)}`", "detail": detail})
    return sorted(rules, key=lambda r: r["title"]), sorted(watching)


def read_since(text: str | None) -> dict[str, str]:
    """``{rule title: the day it entered}`` read from an existing playbook, so a regenerated one keeps each rule's date."""
    out: dict[str, str] = {}
    for line in (text or "").splitlines():
        if m := _PLAYBOOK_SINCE.match(line):
            out[m["title"]] = m["day"]
    return out


def render_playbook(name: str, rules: Sequence[Mapping[str, str]], watching: Sequence[str], since: Mapping[str, str], today: date) -> str:
    """The playbook text. Each rule carries its numbers and the day it entered (``since``, kept from the old file; ``today`` for a
    new rule). Deterministic: the same inputs give the same text, so a quiet week changes nothing."""
    lines = [
        f"# {name}: playbook",
        "",
        "Written by `studio review weekly` from the data and rewritten every Monday: do not edit it by hand. A rule enters only with at "
        f"least {PLAYBOOK_MIN_POSTS} posts behind it, with its numbers and the day it entered; anything with fewer posts is under Watching.",
        "",
        "## Rules",
        "",
    ]
    if rules:
        lines += [f"- **{r['title']}**: {r['detail']} · since {since.get(r['title'], today.isoformat())}" for r in rules]
    else:
        lines.append(f"_No rule yet: a rule needs at least {PLAYBOOK_MIN_POSTS} measured posts behind it._")
    if watching:
        lines += ["", "## Watching", ""] + [f"- {w}" for w in watching]
    return "\n".join(lines) + "\n"


# ---- the week --------------------------------------------------------------------------------------------------------------------------

ROSTER_ORDER = ("franz", "reginald", "lenny")  # the owner's order (terminal/src/lib/roster.ts); any other live character follows by slug
PROPOSAL_REPO = "https://github.com/oschwend-prog/character-studio"
PROPOSAL_BASE = "build/slice1"
LINE_LABELS = ("1 Result", "2 Audience", "3 Hook", "4 Tests", "5 Next")
HOOK_CHARS = 40


@dataclass(frozen=True)
class WeekWindow:
    """A week, Monday 00:00 to the next Monday 00:00 London (``end`` excluded)."""

    monday: date
    start: datetime
    end: datetime

    @property
    def sunday(self) -> date:
        return self.monday + timedelta(days=6)

    def label(self) -> str:
        return f"week of {self.monday.day} {self.monday.strftime('%b')}"


def week_window(monday: date) -> WeekWindow:
    """The window of the week starting on ``monday`` (aware London datetimes; a DST change inside it is handled by the zone)."""
    if monday.weekday() != 0:
        raise ValueError(f"{monday} is not a Monday")
    return WeekWindow(
        monday=monday, start=datetime.combine(monday, time.min, tzinfo=LONDON),
        end=datetime.combine(monday + timedelta(days=7), time.min, tzinfo=LONDON),
    )


def default_week(now: datetime) -> date:
    """The Monday of the last finished week: the Monday run reviews the week that just ended (Mon 19 Oct reviews 12-18 Oct)."""
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError(f"now must be timezone-aware (never naive), got {now!r}")
    today = now.astimezone(LONDON).date()
    return today - timedelta(days=today.weekday() + 7)


def _ordered(slugs: Iterable[str]) -> list[str]:
    return sorted(slugs, key=lambda s: (ROSTER_ORDER.index(s) if s in ROSTER_ORDER else len(ROSTER_ORDER), s))


# ---- a post as the digest sees it ------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class PostFact:
    """One posted post: when, where, its best views reading so far, its ``outlier_x`` (None until it has one) and the floor metrics of
    its snapshots (``post_metric_values``). ``available_at`` is when its 7-day figure exists."""

    post_id: str
    clip_id: str
    platform: str
    posted_at: datetime
    peak_views: int | None = None
    outlier_x: float | None = None
    hook: str | None = None
    metrics: Mapping[str, float] | None = None

    @property
    def available_at(self) -> datetime:
        return self.posted_at + OUTLIER_LAG


def post_facts(store: Store) -> dict[str, list[PostFact]]:
    """``{character: [PostFact]}`` for every posted post of every account, oldest first."""
    reads = {r.post_id: r for r in post_reads(store)}
    hooks = {c.id: c.hook for c in store.list_clips()}
    out: dict[str, list[PostFact]] = {}
    for account in store.accounts():
        for post in store.list_posts(account_id=account.id, status=PostStatus.posted):
            snaps = store.snapshots_for(post.id)
            views = [s.views for s in snaps if s.views is not None]
            read = reads.get(post.id)
            out.setdefault(account.character_slug, []).append(
                PostFact(
                    post_id=post.id, clip_id=post.clip_id, platform=account.platform.value, posted_at=posted_at(post),
                    peak_views=max(views) if views else None, outlier_x=read.outlier_x if read else None,
                    hook=hooks.get(post.clip_id), metrics=post_metric_values(snaps),
                )
            )
    for facts in out.values():
        facts.sort(key=lambda f: (f.posted_at, f.post_id))
    return out


# ---- the five lines of a character (plan 6.1) --------------------------------------------------------------------------------------------


def _s(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def _quote(text: str | None, fallback: str) -> str:
    text = " ".join((text or "").split())
    if not text:
        return fallback
    return f"“{text[: HOOK_CHARS - 1] + '…' if len(text) > HOOK_CHARS else text}”"


def bar_text(ev: review.CharacterEvidence) -> str:
    """The character bar as one phrase: ``not yet (9 of 20 posts, day 14 of 28)``; the verdict itself is the code's (``review``)."""
    days = int(ev.age.days) if ev.age is not None else 0
    if ev.bar == "not_yet":
        return f"not yet ({ev.posts} of {review.CHARACTER_MIN_POSTS} posts, day {days} of {review.CHARACTER_MIN_AGE.days})"
    return f"{ev.bar} ({_s(ev.posts, 'post')}, day {days})"


def _median_as_of(facts: Sequence[PostFact], moment: datetime) -> tuple[float | None, int]:
    xs = [f.outlier_x for f in facts if f.platform == INSTAGRAM and f.outlier_x is not None and f.available_at <= moment]
    return (statistics.median(xs) if xs else None), len(xs)


def result_line(week: WeekWindow, facts: Sequence[PostFact]) -> str:
    """Line 1: posts this week against last week; the median ``outlier_x`` of the Instagram posts that have one (cumulative to the
    week's end, against the same to the week before; n beside it) or why there is none; the hits (``outlier_x >= 3``) among them; the
    best post of the week with its raw views (and its ``outlier_x`` when it has one)."""
    mine = [f for f in facts if week.start <= f.posted_at < week.end]
    before = [f for f in facts if week.start - WEEK_LEN <= f.posted_at < week.start]
    med, k = _median_as_of(facts, week.end)
    prev, kp = _median_as_of(facts, week.start)
    parts = [f"{_s(len(mine), 'post')} (last week {len(before)})"]
    if med is None:
        ig = [f for f in facts if f.platform == INSTAGRAM and f.posted_at < week.end]
        if not ig:
            why = "no Instagram post yet"
        elif min(f.posted_at for f in ig) + OUTLIER_LAG > week.end:
            why = "the 7-day figure comes 7 days after a post"
        else:
            why = f"each post needs {MIN_PRIORS} earlier ones with a 7-day figure"
        parts += [f"median outlier_x: none yet ({why})", "hits: none yet (nothing measured)"]
    else:
        last = f"{prev:.1f} n {kp}" if prev is not None else "none yet"
        parts.append(f"median outlier_x {med:.1f} (n {k}; last week {last})")
        hits = sum(1 for f in facts if f.platform == INSTAGRAM and f.outlier_x is not None and f.available_at <= week.end and f.outlier_x >= review.HIT_X)
        parts.append(f"{_s(hits, 'hit')} of {k} measured")
    seen = [f for f in mine if f.peak_views is not None]
    if seen:
        best = max(seen, key=lambda f: (f.peak_views, f.post_id))
        x = f" ({best.outlier_x:.1f}x)" if best.outlier_x is not None else ""
        parts.append(f"best {_quote(best.hook, 'a clip without a hook')} {best.peak_views:,} views{x}")
    else:
        parts.append("best: none yet (no views read this week)" if mine else "best: no post this week")
    return " · ".join(parts)


def _floor_note(entry: Mapping[str, Any] | None, word: str = "floor") -> str:
    if entry is None:
        return f"{word} pending"
    if entry.get("status") == "fixed":
        return f"{word} {entry['value']:.1f}"
    return f"{word} pending: {entry.get('reason', FLOOR_NO_DATA)}"


def guard_text(entry: Mapping[str, Any] | None) -> str:
    """The Instagram guard's state from ``review_payload``'s ``ig_guard`` entry of his account."""
    if entry is None:
        return "guard: no Instagram account"
    drop = entry.get("drop_pct")
    if entry.get("applied"):
        return f"guard: cut {entry['handle']} to {entry['new_dropin_share']:.2f} (reach down {drop:.0f} %)"
    if entry.get("fires") and entry.get("new_dropin_share") is not None:
        return f"guard: would cut {entry['handle']} to {entry['new_dropin_share']:.2f} (reach down {drop:.0f} %), nothing written"
    if entry.get("fires"):
        return f"guard: fired (reach down {drop:.0f} %), the share is already at or under {review.IG_GUARD_DROPIN_SHARE:.2f}"
    if entry.get("non_follower_pct_previous_week") is None or entry.get("non_follower_pct_this_week") is None:
        return "guard: no change (it needs a reach reading in both weeks)"
    return "guard: no change"


def audience_line(
    *, follows: float | None, follows_n: int, follows_floor: Mapping[str, Any] | None, reach: float | None, reach_prev: float | None,
    reach_n: int, guard: Mapping[str, Any] | None,
) -> str:
    """Line 2: followers (no follower count reaches the cloud yet), follows per 1K against its floor, non-follower reach against last
    week, and the guard's state."""
    parts = ["followers: none yet (no follower count in the cloud yet)"]
    if follows is None:
        parts.append("follows per 1K: none yet (no follows data in the cloud yet)")
    else:
        parts.append(f"follows per 1K {follows:.1f} ({_floor_note(follows_floor)}; n {follows_n})")
    if reach is None:
        parts.append("non-follower reach: none yet (no reach data in the cloud yet)")
    else:
        last = f"{reach_prev:.0f} %" if reach_prev is not None else "none yet"
        parts.append(f"non-follower reach {reach:.0f} % (last week {last}; n {reach_n})")
    parts.append(guard_text(guard))
    return " · ".join(parts)


def hook_line(
    *, skip: float | None, skip_n: int, ceiling: Mapping[str, Any] | None, row: Mapping[str, Any] | None,
    flagged_posts: Sequence[tuple[str, Sequence[str]]],
) -> str:
    """Line 3: the median skip rate against his ceiling, the bandit's leading pattern with its n ("too few to call" until the arm has
    the tally the plan wants), and the posts below two floors with what failed (hook, hold, sends, follows)."""
    if skip is None:
        parts = ["skip rate: none yet (no skip-rate data in the cloud yet)"]
    else:
        cap = f"ceiling {ceiling['value']:.0f} %" if ceiling and ceiling.get("status") == "fixed" else _floor_note(ceiling, "ceiling")
        parts = [f"skip rate {skip:.0f} % ({cap}; n {skip_n})"]
    if row is None:
        parts.append("hook test: this character has no hook arms")
    elif row["leading"] is None:
        why = (
            f"rotating, {row['readings']} of {row['readings_needed']} readings before it can learn"
            if row.get("mode") == "rotation" else "nothing tallied yet"
        )
        parts.append(f"leading: none yet ({why})")
    else:
        lead = row["leading"]
        weak = " (too few to call)" if lead["uses"] < row["min_uses"] else ""
        parts.append(f"leading: {lead['pattern']}, {lead['wins']} wins of {lead['uses']}{weak}")
    for hook, failed in flagged_posts[:2]:
        parts.append(f"below 2 floors: {hook} ({', '.join(failed)})")
    return " · ".join(parts)


def _tests_parts(
    slug: str, registry: experiments.Registry, score: Mapping[str, Any], his_scored: int, row: Mapping[str, Any] | None, his_clips: Sequence[Clip],
) -> list[str]:
    parts: list[str] = []
    for test in registry.tests.values():
        if not test.on:
            continue
        if test.id == "A":
            if score["label"] in ("validated", "failed"):
                parts.append(f"score test {score['label']} at {score['look']} (rho {score['rho']:.2f})")
            elif score["label"] == "uninformative":
                parts.append(f"score test uninformative at {score['look']}: raise the exploration picks")
            else:
                interim = " (interim: unproven, not a verdict)" if score["look"] else " (not a verdict)"
                parts.append(f"score test {score['n']} of {score['needed']}, his {his_scored}{interim}")
        elif test.id == "B":
            if row is None:
                continue
            if row.get("mode") == "rotation" and row["tallied"] == 0:
                parts.append(f"hook test rotating, {row['readings']} of {row['readings_needed']} readings so far (not a verdict)")
            else:
                done = row["fewest_uses"] >= row["min_uses"]
                parts.append(
                    f"hook test {row['tallied']} tallied, fewest arm {row['fewest_uses']} of {row['min_uses']}"
                    + ("" if done else " (not a verdict)")
                )
        else:
            counts: dict[str, int] = {}
            for clip in his_clips:
                arms = clip.features.get("test_arms")
                if isinstance(arms, Mapping) and test.key in arms:
                    counts[_shown(arms[test.key])] = counts.get(_shown(arms[test.key]), 0) + 1
            have = " v ".join(f"{counts.get(_shown(a), 0)}" for a in test.counts) if test.counts else str(sum(counts.values()))
            need = " v ".join(str(v) for v in test.params.get("min_n", {}).values())
            parts.append(f"test {test.id} {test.name} {have} (need {need}; not a verdict)")
    return parts


def tests_line(
    slug: str, registry: experiments.Registry, score: Mapping[str, Any], his_scored: int, row: Mapping[str, Any] | None,
    his_clips: Sequence[Clip],
) -> str:
    """Line 4: n so far against n needed for each test that is on in ``config/experiments.json`` (A: the score test, pooled over the
    characters with his share; B: the hook arms; any other block-coin test: its arms' counts), each marked "not a verdict" before its look."""
    parts = _tests_parts(slug, registry, score, his_scored, row, his_clips)
    return " · ".join(parts) if parts else "no test is on"


def _lift_text(lf: SideLift) -> str:
    return f"{lf.label} (median {lf.median:.1f}x against {lf.median_others:.1f}x for the others; n {lf.n} v {lf.n_others})"


def next_line(*, measured: int, lifts: Sequence[SideLift], needs: Sequence[str]) -> str:
    """Line 5: under 10 measured posts "too few to call"; else one STOP and one DO MORE from the lifts (or "nothing clear"); then
    "needs you:" the decisions waiting for him, or "nothing"."""
    if measured < CALL_MIN_POSTS:
        verdict = f"too few to call ({measured} of {CALL_MIN_POSTS} measured posts)"
    else:
        up, down = do_more(lifts), stop(lifts)
        verdict = f"STOP {_lift_text(down) if down else 'nothing clear'} · DO MORE {_lift_text(up) if up else 'nothing clear'}"
    return f"{verdict} · needs you: {'; '.join(needs) if needs else 'nothing'}"


def with_labels(lines: Sequence[str]) -> list[str]:
    """The five lines with their labels, as 6.1's example shows them (``1 Result    ...``)."""
    return [f"{label:<10}  {line}" for label, line in zip(LINE_LABELS, lines, strict=True)]
