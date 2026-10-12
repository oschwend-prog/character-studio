"""The weekly review in the cloud (learning plan ``docs/launch/measurement-and-learning-plan.md`` sections 3.2, 3.8, 4.1-4.3, 6.1 and build
items 10-11): ``studio review weekly`` and ``studio learn score-test``. Deterministic code only, no Claude: the Monday cloud job
(``.github/workflows/studio-weekly.yml``, 06:15 UTC) runs it, so the numbers, the digest, the reviews and the proposals no longer
wait for the Mac. Sections 3 and 4.3 of the plan are frozen: every threshold below is a module constant with its test at the exact
boundary, never a parameter or a config value.

``studio review weekly [--week YYYY-MM-DD|2026-W42] [--out-dir PATH] [--dry-run]``
    The week is Monday to Sunday, London; the default is the last finished week (the Monday run reviews the week that just ended).
    Everything is read from the store; ``--dry-run`` prints the same JSON and writes nothing (not even the Instagram guard's cut).
    Otherwise it (1) applies the binding Instagram guard (``review.review_payload``), (2) saves one ``reviews`` row per LIVE
    character (``review.save_review``: the studio header, then his title line and his five lines, ``bar_status`` the code's bar; a
    character whose block could not be built gets no row), (3) writes the
    proposal files under ``--out-dir`` (below) and (4) logs ONE ``weekly`` run (the path ``studio run log`` uses) whose ``summary`` is
    the full digest text. Rerunning a week rewrites its reviews and logs another run. Exit 0 unless the database fails (2 for a
    caller error: no ``DATABASE_URL``, a bad ``--week``, a broken test registry). A part with no data yet is a note (the run stays
    ``ok``); a part that crashes is a note too, the digest still comes and the run is logged as ``error``.

**The digest** (plan 6.1; the terminal's Today card shows it): a studio header of two lines (credits this month against the cap and
the cost per 1K views; the warnings ``studio.health`` raises and the proposals waiting), then for every live character his title
(``Reginald · week of 12 Oct · bar: not yet (9 of 20 posts, day 14 of 28)``) and five lines: 1 Result, 2 Audience, 3 Hook, 4 Tests,
5 Next. A character with no post yet has the one line ``no posts yet``. Every number sits next to a comparison and its n; a
number that does not exist yet is ``none yet`` with the reason, never 0. Figures are Instagram's (the reach channel); the 7-day
``outlier_x`` of a post exists 7 days after it. Followers, follows, reach, skip rate and watch time reach the cloud only with
Instagram's own API (plan Task 9) or the Mac's vidIQ ingest, so until then they read ``none yet``.

``runs.details`` of the logged run (the terminal reads it)::

    {"week": "2026-10-12",                      # the Monday of the week reviewed
     "digest": {"header": [line1, line2],
                "characters": [{"slug", "name", "bar", "bar_status", "title", "lines": [...5 strings, labelled "1 Result    ..."]}]},
     "score_test": {"label", "n", "needed", "look", "rho", "rho_potential", "rho_swap", "buckets", "note",
                    "decided": {"20": {look, label, rho, span, ..., "clip_ids"}, "40": {...}}},   # test A; a look taken is frozen
     "floors": {"computed", "basis", "fixed_on": {metric: day|null}, "studio": {...}, "characters": {slug: {...}}},   # plan 3.8
     "proposals": [{"kind": "hit_rule" | "arm_retire" | "playbook", ...its numbers and clip ids...}],
     "proposal_pending_url": "https://github.com/.../compare/build/slice1...weekly/<monday>?expand=1" | null,   # the review sets it with the files
     "proposal_url": null | the same address,   # what the Today card links: null until the propose job has pushed the branch (confirm_proposal)
     "candidates": [...],                       # rule candidates waiting for their second look (4.3)
     "arms": [...], "warnings": [...], "notes": [...], "playbooks": {slug: {"changed", "path", ...}}, "generated_at": iso}

**Test A, the score test** (3.2; ``score_test``, ``studio learn score-test``): Spearman rho (average ranks, no dependency) of
``score_total`` against the Instagram ``outlier_x`` of the posted drops, pooled over the characters and ordered by when the figure
became available (post + 7 days). Interim look at the first 20 (rho >= 0.45 validated, rho <= 0 failed, else unproven), final look
at the first 40 (rho >= 0.31 validated, else failed); no peeking (21..39 never recompute the interim); a decided interim ends the
test; a middle 80 % of the scores under 15 points wide is ``uninformative``, never ``failed``.

**The floors** (3.8; ``compute_floors``): from the Instagram posts of Mon 5 to Sun 18 Oct (London days) the median of sends per 1K
(shares), follows per 1K and watched %, and his median skip rate as a ceiling; per character when he has 4 readings, else the
studio-wide median; pending below 6 readings studio-wide ("no data in the cloud yet" when there is none at all). The first weekly run
for a week that ends on or after Sun 18 Oct stores them in its ``details.floors``; every later run copies the fixed ones from the
latest run that has them and only fills the pending ones, writing down the day (a fixed floor is never recomputed): the first fix
records Sun 18 Oct, the end of weeks 1-2; a later fix the London date the 6th reading arrived. They diagnose
only: from Mon 19 Oct a post below two of them is named on the Hook line with what failed (hook, hold, sends, follows).

**Proposals** (4.1, 4.3, 3.3): a rule candidate is a tag value that passes entry conditions 1-3 (5 clips on each side, a median at
least 1.5x the others', a hit among the followers); the run after next week's posts have been added makes it ``ready`` if it still
shows 1.2x. An arm is proposed for retirement after 10 tallied uses with 20 % wins or fewer and a median ``outlier_x`` of 0.7 or
less (no rule exists for adding one). ``characters/<slug>/playbook.md`` is regenerated from the data (a rule needs 5 posts behind it,
fewer goes under Watching; each rule keeps the day it entered). Under ``--out-dir`` the run writes the changed playbooks and
``docs/weekly/<monday>.md`` (the digest and the proposals with their numbers and clip ids), only when a playbook changed or a NEW
proposal exists, and sets ``proposal_pending_url`` (``proposal_url`` stays null: the card must not link a compare page before the branch
is on GitHub, and the propose job can fail after the review; the confirm job calls ``studio review confirm-proposal`` once the propose
job succeeded, which copies the address into ``proposal_url``); otherwise nothing is written and both are null. ``config/hit_rules.md`` is never
edited by code: a ready rule is a proposal with its numbers, and the owner (or a Claude session) writes the rule text.
"""

from __future__ import annotations

import json
import re
import statistics
import uuid
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
# Tags that say who chose or how a clip was made or filed, or that carry the score or a test's arm, not what is in the clip: a lift on
# one of them is no rule about clips (a rule about the score would be advice from the score before test A has looked, and circular).
# ``zoom_pulses`` and ``hook_entrance`` arrive with Task 17's merge: listing them now is harmless.
NOT_A_RULE = frozenset(
    {
        "hit_rules_version", "explore_pick", "hook_by", "version_index", "hook_text", "hook_index",
        "score_bucket", "score_total", "score_potential", "score_swap", "test_arms", "family_id", "trial_reel", "first_comment_posted",
        "series", "episode", "zoom_pulses", "hook_entrance", "beats",
    }
)


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


SCORE_LABELS = ("unproven", "validated", "failed", "uninformative")


def _number(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def stored_look(decided: Mapping[str, Any] | None, look: int) -> dict[str, Any] | None:
    """The look ``look`` (20 or 40) as an earlier weekly run stored it in ``score_test.decided``, or None when there is none or what is
    there is damaged (a wrong look, an unknown label, a rho that is no number): a damaged record is ignored, never trusted."""
    entry = (decided or {}).get(str(look))
    if (
        not isinstance(entry, Mapping) or entry.get("look") != look or entry.get("label") not in SCORE_LABELS
        or not _number(entry.get("rho")) or not _number(entry.get("span")) or not isinstance(entry.get("clip_ids"), list)
    ):
        return None
    return dict(entry)


def frozen_looks(runs: Sequence[Run]) -> dict[str, Any]:
    """The looks already taken: ``score_test.decided`` of the most recent weekly run (oldest first in ``runs``) that carries any."""
    for run in reversed(runs):
        test = run.details.get("score_test") if isinstance(run.details, dict) else None
        decided = test.get("decided") if isinstance(test, dict) else None
        if isinstance(decided, dict) and decided:
            return dict(decided)
    return {}


def score_test(observations: Iterable[ScoreObservation], decided: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Test A (plan 3.2): does a higher ``score_total`` go with a higher ``outlier_x``?

    The observations are put in the order their ``outlier_x`` became available (then the clip id). **No peeking**: before 20 only the
    count is shown; the interim look judges the first 20 and is never recomputed on 21..39; the final look judges the first 40 and
    never moves again. A ``validated`` or ``failed`` interim ends the test (the label sticks, whatever comes later). ``uninformative``
    (the middle 80 % of the scores spans under 15 points) is not a decision: the test goes on to the next look.

    **A look, once taken, is frozen.** The first run that has 20 (or 40) observations takes the look on the first 20 (40) as they are
    at that run and keeps it in the result's ``decided`` (``{"20": {...}, "40": {...}}``: label, rho, span, the two parts' rho, the
    buckets and the ``clip_ids`` of the sample). The caller passes the latest stored ``decided`` back (``frozen_looks``): a stored look is
    copied as it is and never recomputed, so a 7-day figure that arrives late and sorts earlier (a failed pull) cannot move a look
    that was taken, in either direction.

    Returns ``{"label", "n", "needed", "look", "rho", "rho_potential", "rho_swap", "buckets", "note", "decided"}``: ``label`` one of
    ``unproven`` / ``validated`` / ``failed`` / ``uninformative``; ``needed`` the n of the next look (20, then 40); ``look`` the look the
    label comes from (None before the first); the rho of the total, of ``potential`` and of ``swap`` (each None before a look, or with
    fewer than 2 values) and the median ``outlier_x`` per score bucket are reported on the looked-at sample only: report, no decision.
    """
    ordered = sorted(observations, key=lambda o: (o.available_at, o.clip_id))
    n = len(ordered)
    frozen: dict[str, Any] = {}
    result: dict[str, Any] = {
        "label": "unproven", "n": n, "needed": SCORE_INTERIM_N, "look": None,
        "rho": None, "rho_potential": None, "rho_swap": None, "buckets": [], "note": "", "decided": frozen,
    }

    def take(look: int) -> dict[str, Any] | None:
        """The look: the stored one as it is, else taken now on the first ``look`` observations when there are that many."""
        entry = stored_look(decided, look)
        if entry is None:
            if n < look:
                return None
            sample = ordered[:look]
            rho = spearman([o.score for o in sample], [o.outlier_x for o in sample])
            span = middle_span([o.score for o in sample])
            entry = {
                "look": look, "label": look_label(rho, span, look), "rho": round(rho, 4), "span": span,
                "rho_potential": _rho_of(sample, "potential"), "rho_swap": _rho_of(sample, "swap"), "buckets": score_buckets(sample),
                "clip_ids": [o.clip_id for o in sample],
            }
        frozen[str(look)] = entry
        return entry

    entry = take(SCORE_INTERIM_N)
    if entry is None:
        result["note"] = f"{n} of {SCORE_INTERIM_N} posted drops with a score and a 7-day figure so far. Not a verdict."
        return result
    needed = SCORE_INTERIM_N
    if entry["label"] not in ("validated", "failed"):  # the interim did not end the test: it goes on to 40
        needed = SCORE_FINAL_N
        entry = take(SCORE_FINAL_N) or entry
    label, look, rho, span = entry["label"], entry["look"], entry["rho"], entry["span"]
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
        label=label, needed=needed, look=look, rho=rho, rho_potential=entry.get("rho_potential"), rho_swap=entry.get("rho_swap"),
        buckets=list(entry.get("buckets") or []), note=note,
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
    """Test A, the score test (plan 3.2): the label, n against the looks, rho and the median outlier_x per score bucket. Read-only; a
    look the weekly review already took is shown as it took it (``decided``), never recomputed."""
    store = open_store()
    emit(score_test(score_observations(store), decided=frozen_looks(_weekly_runs(store))))


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


def _baseline_posts(store: Store, start: date, end: date) -> Iterable[tuple[str, list[Snapshot]]]:
    """``(character, the post's snapshots)`` of the Instagram posts posted from ``start`` to ``end`` (London days, both included)."""
    for account in store.accounts():
        if account.platform.value != INSTAGRAM:
            continue
        for post in store.list_posts(account_id=account.id, status=PostStatus.posted):
            if start <= posted_at(post).astimezone(LONDON).date() <= end:
                yield account.character_slug, store.snapshots_for(post.id)


def floor_readings(store: Store, start: date = FLOORS_FROM, end: date = FLOORS_TO) -> dict[str, dict[str, list[float]]]:
    """``{metric: {character: [one reading per post]}}`` of the Instagram posts posted from ``start`` to ``end`` (London days, both
    included): the baseline of weeks 1-2. A post that has no reading of a metric is not in its list."""
    out: dict[str, dict[str, list[float]]] = {}
    for slug, snaps in _baseline_posts(store, start, end):
        for metric, value in post_metric_values(snaps).items():
            out.setdefault(metric, {}).setdefault(slug, []).append(value)
    return out


def post_metric_arrivals(snapshots: Iterable[Snapshot]) -> dict[str, datetime]:
    """When each of a post's floor metrics first existed: the ``captured_at`` of the EARLIEST snapshot that reports it (a later
    snapshot may change the value, not the day the reading arrived). A metric nothing reported is left out."""
    out: dict[str, datetime] = {}
    for snap in snapshots:
        if snap.captured_at is None:
            continue
        for metric in post_metric_values([snap]):
            if metric not in out or snap.captured_at < out[metric]:
                out[metric] = snap.captured_at
    return out


def floor_arrivals(store: Store, start: date = FLOORS_FROM, end: date = FLOORS_TO) -> dict[str, list[datetime]]:
    """``{metric: [when each reading arrived]}`` for the same posts as ``floor_readings``, pooled over the characters (the studio-wide
    floor is fixed by the 6th of them): ``compute_floors`` dates a later fix by the 6th."""
    out: dict[str, list[datetime]] = {}
    for _, snaps in _baseline_posts(store, start, end):
        for metric, moment in post_metric_arrivals(snaps).items():
            out.setdefault(metric, []).append(moment)
    return out


def _fixed(entry: Any) -> bool:
    return isinstance(entry, dict) and entry.get("status") == "fixed" and isinstance(entry.get("value"), (int, float))


def _pending_reason(n: int) -> str:
    return FLOOR_NO_DATA if n == 0 else f"{n} of {FLOOR_MIN_STUDIO} readings studio-wide so far"


def compute_floors(
    readings: dict[str, dict[str, list[float]]], characters: Sequence[str], *, today: date, previous: dict[str, Any] | None = None,
    arrivals: Mapping[str, Sequence[datetime]] | None = None,
) -> dict[str, Any]:
    """The floors (plan 3.8, frozen). ``readings`` is ``floor_readings``'s ``{metric: {character: [values]}}``; ``previous`` the
    ``floors`` of an earlier weekly run.

    Per metric: **studio-wide** the median of every reading once there are at least 6 (else it is ``pending`` with the reason: none
    at all means "no data in the cloud yet"); **per character** the median of his own readings when he has at least 4, else the
    studio-wide median. A pending metric stays pending for everybody (even a character with 4 readings) until the 6th reading
    arrives. **The day a metric is fixed is written down** (``fixed_on``): the first computation (no ``previous``) records Sun 18 Oct,
    the end of weeks 1-2, whatever day the run happens; a later fix records the London date the 6th reading arrived (``arrivals``,
    ``{metric: [when each reading arrived]}`` from ``floor_arrivals``: the reading's own time, not the run's), or ``today`` when no
    times are given. **A fixed floor is never recomputed**: whatever
    ``previous`` has fixed is copied as it is, and only pending ones are filled. A character who joins later gets the fixed
    studio-wide value (or his own median if he already has 4 readings).

    ``{"computed": True, "basis", "fixed_on": {metric: date|None}, "studio": {metric: entry}, "characters": {slug: {metric: entry}}}``;
    an entry is ``{"kind", "status": "fixed", "value", "n", ...}`` or ``{"kind", "status": "pending", "n", "needed", "reason"}``.
    """
    prev = previous or {}
    first_computation = not prev.get("computed")

    def fixed_day(metric: str) -> str:
        if first_computation:
            return FLOORS_TO.isoformat()
        moments = sorted((arrivals or {}).get(metric, ()))
        return moments[FLOOR_MIN_STUDIO - 1].astimezone(LONDON).date().isoformat() if len(moments) >= FLOOR_MIN_STUDIO else today.isoformat()

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
            day = fixed_day(metric)
            studio[metric] = {"kind": kind, "status": "fixed", "value": statistics.median(pooled), "n": len(pooled), "fixed_on": day}
            fixed_on[metric] = day
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


def guard_text(entry: Mapping[str, Any] | None, *, brief: bool = False) -> str:
    """The Instagram guard's state from ``review_payload``'s ``ig_guard`` entry of his account. ``brief`` leaves out the reason a missing
    reach reading would add (the audience line has already said there is no reach data)."""
    if entry is None:
        return "guard: no Instagram account"
    drop = entry.get("drop_pct")
    if entry.get("applied"):
        return f"guard: cut {entry['handle']} to {entry['new_dropin_share']:.2f} (reach down {drop:.0f} %)"
    if entry.get("fires") and entry.get("new_dropin_share") is not None:
        return f"guard: would cut {entry['handle']} to {entry['new_dropin_share']:.2f} (reach down {drop:.0f} %), nothing written"
    if entry.get("fires"):
        return f"guard: fired (reach down {drop:.0f} %), the share is already at or under {review.IG_GUARD_DROPIN_SHARE:.2f}"
    if not brief and (entry.get("non_follower_pct_previous_week") is None or entry.get("non_follower_pct_this_week") is None):
        return "guard: no change (it needs a reach reading in both weeks)"
    return "guard: no change"


def audience_line(
    *, follows: float | None, follows_n: int, follows_floor: Mapping[str, Any] | None, reach: float | None, reach_prev: float | None,
    reach_n: int, guard: Mapping[str, Any] | None,
) -> str:
    """Line 2: followers (no follower count reaches the cloud yet), follows per 1K against its floor, non-follower reach against last
    week, and the guard's state. With no follows and no reach figure at all (so nothing but the missing follower count) the three
    figures are one short phrase; any data keeps every figure's own phrase."""
    if follows is None and reach is None:
        return " · ".join(["no follower, follows or reach data in the cloud yet", guard_text(guard, brief=True)])
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


TEST_LABELS = {"G": "zoom pulses", "H": "word pop"}  # the digest's short names for the edit tests (any other test shows its registry name)


def _tests_parts(
    slug: str, registry: experiments.Registry, score: Mapping[str, Any], his_scored: int, row: Mapping[str, Any] | None, his_clips: Sequence[Clip],
    name: str | None = None,
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
                parts.append(f"score test {score['n']} of {score['needed']} measured clips, {his_scored} of them {name or slug}'s{interim}")
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
            parts.append(f"test {test.id} {TEST_LABELS.get(test.id, test.name)} {have} (need {need}; not a verdict)")
    return parts


def tests_line(
    slug: str, registry: experiments.Registry, score: Mapping[str, Any], his_scored: int, row: Mapping[str, Any] | None,
    his_clips: Sequence[Clip], name: str | None = None,
) -> str:
    """Line 4: n so far against n needed for each test that is on in ``config/experiments.json`` (A: the score test, pooled over the
    characters, with how many of those measured clips are his (``his_scored``, by his ``name``); B: the hook arms; any other block-coin
    test: its arms' counts), each marked "not a verdict" before its look."""
    parts = _tests_parts(slug, registry, score, his_scored, row, his_clips, name)
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


# ---- the studio header (two lines) -------------------------------------------------------------------------------------------------------


def _prev_month(month: str) -> str:
    year, mon = (int(p) for p in month.split("-"))
    return f"{year - 1:04d}-12" if mon == 1 else f"{year:04d}-{mon - 1:02d}"


def month_cost(store: Store, month: str, facts: Mapping[str, Sequence[PostFact]]) -> dict[str, Any]:
    """The month's real spend (settled credits), the views its posts have so far (their best reading; posts posted in the London
    month) and the cost per 1K views, None while there are no views: the number is left out, never 0."""
    spent = budget.spend(store, month)
    posts = [f for fs in facts.values() for f in fs if f.posted_at.astimezone(LONDON).strftime("%Y-%m") == month and f.peak_views is not None]
    views = sum(f.peak_views for f in posts if f.peak_views is not None)
    return {
        "month": month, "settled": spent.settled, "reserved": spent.reserved, "committed": spent.committed,
        "views": views, "posts": len(posts), "per_1k": round(spent.settled / views * 1000, 2) if views > 0 else None,
    }


def per_1k_text(credits: float) -> str:
    """The cost per 1K views: one decimal under 100 credits, whole credits (with a thousands comma) from 100 up, where a decimal is noise."""
    return f"{credits:,.0f}" if credits >= 100 else f"{credits:.1f}"


def studio_header(
    store: Store, now: datetime, facts: Mapping[str, Sequence[PostFact]], warnings: Sequence[str], waiting: Mapping[str, int],
) -> list[str]:
    """The two lines above the characters: the credits this month against the cap and the cost per 1K views (against last month's),
    then the warnings that fired (``studio.health``'s checks, only the ones that are not ok) and the proposals waiting."""
    month = budget.month_key(now)
    cap = store.get_settings().monthly_cap_credits
    now_m, before = month_cost(store, month, facts), month_cost(store, _prev_month(month), facts)
    pct = f"{now_m['committed'] * 100 / cap:.0f} %, " if cap > 0 else ""
    credits = f"Credits {now_m['committed']:,} of {cap:,} this month ({pct}{now_m['reserved']:,} still reserved; last month {before['committed']:,})"
    if now_m["per_1k"] is None:
        cost = "cost per 1K views: none yet (no views read this month)"
    else:
        last = per_1k_text(before["per_1k"]) if before["per_1k"] is not None else "none yet"
        cost = f"cost per 1K views {per_1k_text(now_m['per_1k'])} credits (n {now_m['views']:,} views from {_s(now_m['posts'], 'post')}; last month {last})"
    shown = [w if len(w) <= 110 else w[:109] + "…" for w in warnings[:2]]
    more = f" +{len(warnings) - 2} more" if len(warnings) > 2 else ""
    flagged = f"{len(warnings)} ({'; '.join(shown)}{more})" if warnings else "none"
    queue = ", ".join(f"{n} {name}" for name, n in waiting.items() if n) or "none"
    return [f"{credits} · {cost}", f"Warnings: {flagged} · Proposals waiting: {queue}"]


# ---- the weekly document (the PR) ------------------------------------------------------------------------------------------------------


def proposal_url(monday: date) -> str:
    return f"{PROPOSAL_REPO}/compare/{PROPOSAL_BASE}...weekly/{monday.isoformat()}?expand=1"


def render_week_doc(
    window: WeekWindow, header: Sequence[str], blocks: Sequence[Mapping[str, Any]], proposals: Sequence[Mapping[str, Any]],
    score: Mapping[str, Any], floors: Mapping[str, Any], standings: Sequence[Mapping[str, Any]],
) -> str:
    """``docs/weekly/<monday>.md`` and the PR's body: the digest, then every proposal with its numbers and clip ids. Nothing in it
    changes a rule by itself: merging the PR is the owner's approval, and ``config/hit_rules.md`` is only ever edited by a person."""
    out = [f"# Weekly review: {window.label()}", "", "```text", *header, ""]
    for block in blocks:
        out += [block["title"], *block["lines"], ""]
    out[-1:] = ["```", "", "## Proposals", ""]
    rules = [p for p in proposals if p["kind"] == "hit_rule"]
    arms = [p for p in proposals if p["kind"] == "arm_retire"]
    plays = [p for p in proposals if p["kind"] == "playbook"]
    if not (rules or arms or plays):
        out += ["Nothing to decide this week.", ""]
    if rules:
        out += ["### Hit rules (`config/hit_rules.md`)", "", "A rule here passed all four entry conditions of plan 4.3. The rule text is yours to write; nothing edits the file.", ""]
        for r in rules:
            again = " (proposed last week too)" if r.get("repeat") else ""
            out += [
                f"- `{r['label']}`{again}: median outlier_x {r['median']} against {r['median_others']} for the others, lift {r['lift']}, "
                f"n {r['n']} v {r['n_others']}, {_s(r['hits'], 'hit')} among the {r['n']}; first seen the week of {r['since_week']}.",
                f"  - clips: {', '.join(r['clip_ids'])}",
            ]
        out.append("")
    if arms:
        out += ["### Hook arms (`config/experiments.json`, test B)", "", "Plan 3.3 retires an arm after 10 tallied uses with 20 % wins or fewer and a median outlier_x of 0.7 or less.", ""]
        out += [
            f"- retire `{a['arm']}` for {a['character']}: {a['wins']} wins in {a['uses']} uses ({a['win_rate'] * 100:.0f} %), median outlier_x {a['median_outlier_x']} over {a['n_outlier']} clips."
            for a in arms
        ]
        out.append("")
    if plays:
        out += ["### Playbooks", ""] + [f"- `{p['path']}`: regenerated from the data ({p['rules']} rules)." for p in plays] + [""]
    out += ["## The tests and the floors", "", f"- Score test (test A): {score['label']}. {score['note']}"]
    if floors.get("computed"):
        pending = [m for m, e in floors["studio"].items() if e["status"] == "pending"]
        out.append(
            "- Floors (plan 3.8): " + ("all four fixed." if not pending else f"pending: {', '.join(pending)}; fixed: "
            + (", ".join(f"{m} {e['value']:.1f} (n {e['n']})" for m, e in floors['studio'].items() if e['status'] == 'fixed') or "none") + ".")
        )
    else:
        out.append(f"- Floors (plan 3.8): {floors.get('reason', 'not set yet')}")
    for row in standings:
        arms_text = ", ".join(f"{a['pattern']} {a['wins']}-{a['losses']}" for a in row["arms"])
        out.append(f"- Hook arms of {row['character']} (wins-losses, {row['tallied']} tallied): {arms_text}.")
    return "\n".join(out).rstrip() + "\n"


# ---- the run ---------------------------------------------------------------------------------------------------------------------------


def _norm(text: str) -> str:
    return text.replace("\r\n", "\n").rstrip("\n") + "\n"


def _median_or_none(values: Sequence[float]) -> float | None:
    return statistics.median(values) if values else None


def _snapshots_of(store: Store, account_id: str) -> list[Snapshot]:
    return [s for p in store.list_posts(account_id=account_id) for s in store.snapshots_for(p.id) if s.captured_at is not None]


def _window_values(snaps: Sequence[Snapshot], field: str, end: datetime) -> list[float]:
    """The ``field`` of the snapshots captured in the 7 days up to ``end`` (as ``studio review data`` reads them), None left out."""
    return [float(v) for s in snaps if end - WEEK_LEN < s.captured_at <= end and (v := getattr(s, field)) is not None]  # type: ignore[operator]


def _weekly_runs(store: Store) -> list[Run]:
    runs = [r for r in store.list_runs(kind=RunKind.weekly) if isinstance(r.details, dict) and isinstance(r.details.get("week"), str)]
    return sorted(runs, key=lambda r: (r.started_at or datetime.min.replace(tzinfo=LONDON), r.id or ""))


def run_weekly(
    store: Store, now: datetime, *, monday: date | None = None, out_dir: Path | None = None, dry_run: bool = False,
    repo_root: Path | None = None, registry: experiments.Registry | None = None,
) -> dict[str, Any]:
    """The Monday review (module doc). Reads everything, builds the digest, the score test, the floors, the proposals and the
    playbooks, and (unless ``dry_run``) applies the Instagram guard, saves one review per live character, writes the PR files under
    ``out_dir`` and logs one ``weekly`` run. Returns the JSON the command prints. A part that crashes is a note, the run is then
    logged as ``error``; a part with no data is a note and the run stays ``ok``."""
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError(f"now must be timezone-aware (never naive), got {now!r}")
    monday = monday or default_week(now)
    window = week_window(monday)
    registry = registry or experiments.load_experiments()
    root = repo_root or experiments.ROOT
    today = now.astimezone(LONDON).date()
    notes: list[str] = []
    failures: list[str] = []

    def part(name: str, fn: Any, default: Any, *, fallback: Any = None) -> Any:
        """``fn()``; when it raises, the failure is a note (the run is logged as ``error``) and the result is ``default``, or
        ``fallback(error)`` when the default depends on what went wrong."""
        try:
            return fn()
        except Exception as e:  # noqa: BLE001  one broken part must not cost the owner the whole digest
            failures.append(f"{name} failed: {type(e).__name__}: {e}")
            return fallback(e) if fallback is not None else default

    payload = review.review_payload(store, now, apply_guard=not dry_run)
    characters = {c.slug: c for c in store.characters()}
    live = _ordered(slug for slug, c in characters.items() if c.status == "live")
    facts = post_facts(store)
    clips = [c for c in store.list_clips() if c.state is ClipState.posted or review.clip_outlier_x(c) is not None]
    measured_total = sum(1 for c in clips if review.clip_outlier_x(c) is not None)
    runs = _weekly_runs(store)
    earlier = [r for r in runs if r.details["week"] < monday.isoformat()]

    # test A
    observations = part("score test: observations", lambda: score_observations(store), [])
    taken = frozen_looks(runs)  # the looks the earlier runs took: copied forward, never recomputed
    score = part(
        "score test", lambda: score_test(observations, decided=taken),
        {"label": "unproven", "n": 0, "needed": SCORE_INTERIM_N, "look": None, "rho": None, "rho_potential": None, "rho_swap": None, "buckets": [],
         "note": "The score test could not be computed: see the notes.", "decided": taken},
    )
    scored_by = {c.id: c.character_slug for c in clips}

    # the floors (frozen once fixed)
    earlier_floors = next((r.details["floors"] for r in reversed(runs) if isinstance(r.details.get("floors"), dict) and r.details["floors"].get("computed")), None)

    def make_floors() -> dict[str, Any]:
        if earlier_floors is None and not floors_due(monday):
            return {"computed": False, "reason": f"set after Sun {FLOORS_TO.day} Oct, by the first review of a week that ends then or later"}
        return compute_floors(floor_readings(store), live, today=today, previous=earlier_floors, arrivals=floor_arrivals(store))

    floors = part("floors", make_floors, {"computed": False, "reason": "failed, see notes"})
    pending = [m for m, e in floors.get("studio", {}).items() if e["status"] == "pending"]
    if floors.get("computed") and pending:
        notes.append("floors pending: " + "; ".join(f"{m} ({floors['studio'][m]['reason']})" for m in pending))

    # rule candidates (4.3), arms (3.3)
    previous_candidates = next((r.details["candidates"] for r in reversed(earlier) if isinstance(r.details.get("candidates"), list)), [])
    candidates, ready = part(
        "rule candidates", lambda: update_candidates(previous_candidates, side_lifts(clips, min_n=1), measured=measured_total, week=monday), ([], [])
    )
    arm_report = part("hook arms", lambda: learn.arms_report(store, registry, now), {"characters": []})
    min_uses = int(registry.test("B").params.get("min_n", {}).get("tallied_per_arm", 6))
    standings = part("hook arm standings", lambda: arm_standings(arm_report, arm_outliers(store, registry), min_uses=min_uses), [])
    retire = retire_proposals(standings)
    earlier_proposals = next((r.details["proposals"] for r in reversed(earlier) if isinstance(r.details.get("proposals"), list)), [])
    already = {(p.get("kind"), p.get("character"), p.get("arm")) for p in earlier_proposals if isinstance(p, dict)}
    proposals: list[dict[str, Any]] = [{"kind": "hit_rule", **r} for r in ready]
    proposals += [{**a, "repeat": ("arm_retire", a["character"], a["arm"]) in already} for a in retire]

    # the playbooks
    playbooks: dict[str, dict[str, Any]] = {}
    texts: dict[str, str] = {}
    for slug in live:

        def make_playbook(slug: str = slug) -> None:
            his = [c for c in clips if c.character_slug == slug]
            rules, watching = playbook_items(his)
            path = root / "characters" / slug / "playbook.md"
            old = path.read_text(encoding="utf-8") if path.exists() else None
            text = render_playbook(characters[slug].name, rules, watching, read_since(old), today)
            changed = (old is None and bool(rules or watching)) or (old is not None and _norm(old) != _norm(text))
            playbooks[slug] = {"changed": changed, "path": f"characters/{slug}/playbook.md", "rules": len(rules), "watching": len(watching)}
            if changed:
                texts[slug] = text
                proposals.append({"kind": "playbook", "character": slug, "path": f"characters/{slug}/playbook.md", "rules": len(rules)})

        part(f"playbook of {slug}", make_playbook, None)

    # the digest: every character's block runs inside ``part``, so one that raises is his one line, never a missing digest
    rows = {r["character"]: r for r in standings}
    first_with_posts = next((slug for slug in live if facts.get(slug)), None)  # the studio-wide "merge the hit-rule PR" goes on his line 5

    def build_block(slug: str) -> dict[str, Any]:
        name = characters[slug].name
        ev = review.character_evidence(store, slug, now)
        title = f"{name} · {window.label()} · bar: {bar_text(ev)}"
        his_facts = facts.get(slug, [])
        base = {"slug": slug, "name": name, "bar": bar_text(ev), "bar_status": ev.bar, "title": title}
        if not his_facts:
            return {**base, "lines": ["no posts yet"]}
        his_clips = [c for c in clips if c.character_slug == slug]
        account = next((a for a in store.accounts(slug) if a.platform.value == INSTAGRAM), None)
        snaps = _snapshots_of(store, account.id) if account else []
        guard = next((g for g in payload["ig_guard"] if account and g["account_id"] == account.id), None)
        mine = [f for f in his_facts if window.start <= f.posted_at < window.end]
        follows = [f.metrics["follows_per_1k"] for f in mine if f.platform == INSTAGRAM and f.metrics and "follows_per_1k" in f.metrics]
        char_floors = floors.get("characters", {}).get(slug, {}) if floors.get("computed") else {}
        skip_values = _window_values(snaps, "skip_rate", now)
        reach_values = _window_values(snaps, "non_follower_pct", now)
        flagged_posts = []
        for f in mine:
            if f.platform == INSTAGRAM and f.posted_at.astimezone(LONDON).date() >= FLOORS_APPLY_FROM and char_floors:
                failed = floor_failures(dict(f.metrics or {}), char_floors)
                if flagged(failed):
                    flagged_posts.append((_quote(f.hook, "a clip without a hook"), failed))
        needs = []
        if ev.bar in ("promote", "kill"):
            needs.append(f"the bar says {ev.bar.upper()}: your call")
        if guard and (guard.get("applied") or guard.get("fires")):
            needs.append(f"the guard {'cut' if guard.get('applied') else 'fired on'} {guard['handle']}: look at why reach fell")
        if playbooks.get(slug, {}).get("changed"):
            needs.append("merge the playbook PR")
        if slug == first_with_posts and any(p["kind"] == "hit_rule" for p in proposals):
            needs.append("merge the hit-rule PR")
        needs += [f"retire hook arm {a['arm']}? (merge or leave it)" for a in retire if a["character"] == slug]
        lines = [
            result_line(window, his_facts),
            audience_line(
                follows=_median_or_none(follows), follows_n=len(follows), follows_floor=char_floors.get("follows_per_1k"),
                reach=guard["non_follower_pct_this_week"] if guard else None,
                reach_prev=guard["non_follower_pct_previous_week"] if guard else None, reach_n=len(reach_values), guard=guard,
            ),
            hook_line(
                skip=_median_or_none(skip_values), skip_n=len(skip_values), ceiling=char_floors.get("skip_rate"), row=rows.get(slug),
                flagged_posts=flagged_posts,
            ),
            tests_line(slug, registry, score, sum(1 for o in observations if scored_by.get(o.clip_id) == slug), rows.get(slug), his_clips, name),
            next_line(measured=sum(1 for c in his_clips if review.clip_outlier_x(c) is not None), lifts=side_lifts(his_clips), needs=needs),
        ]
        return {**base, "lines": with_labels(lines)}

    def unbuilt_block(slug: str, error: Exception) -> dict[str, Any]:
        """His block when it raised: his name and the week, one line with the error's class, and ``failed`` (no review row is saved)."""
        name = characters[slug].name
        return {
            "slug": slug, "name": name, "bar": "", "bar_status": None, "title": f"{name} · {window.label()}",
            "lines": [f"could not be built ({type(error).__name__})"], "failed": True,
        }

    blocks: list[dict[str, Any]] = [
        part(f"digest of {slug}", lambda slug=slug: build_block(slug), None, fallback=lambda e, slug=slug: unbuilt_block(slug, e)) for slug in live
    ]

    waiting = {
        "hit rule": sum(1 for p in proposals if p["kind"] == "hit_rule"),
        "arm": sum(1 for p in proposals if p["kind"] == "arm_retire"),
        "playbook": sum(1 for p in proposals if p["kind"] == "playbook"),
    }
    warnings = part("studio warnings", lambda: health.check(store, now), [])
    header = part(
        "studio header", lambda: studio_header(store, now, facts, warnings, waiting), None,
        fallback=lambda e: [f"The studio header could not be built ({type(e).__name__}).", "See the run's notes."],
    )
    summary = "\n".join(header) + "\n\n" + "\n\n".join("\n".join([b["title"], *b["lines"]]) for b in blocks)

    # the files for the proposal job
    new_work = any(p["kind"] in ("hit_rule", "arm_retire") and not p.get("repeat") for p in proposals) or any(p["changed"] for p in playbooks.values())
    files: dict[str, str] = {}
    if new_work:
        files = {f"characters/{slug}/playbook.md": text for slug, text in texts.items()}
        doc = part("weekly document", lambda: render_week_doc(window, header, blocks, proposals, score, floors, standings), None)
        if doc is None:  # no document, no pull request: the digest and the reviews still stand
            files = {}
        else:
            files[f"docs/weekly/{monday.isoformat()}.md"] = doc
    url = proposal_url(monday) if files and (out_dir is not None or dry_run) else None

    if score["n"] < SCORE_INTERIM_N:
        notes.append(f"score test: {score['n']} of {SCORE_INTERIM_N} observations, no look yet")
    notes += failures
    details: dict[str, Any] = {
        "week": monday.isoformat(),
        "digest": {"header": header, "characters": [{k: b[k] for k in ("slug", "name", "bar", "bar_status", "title", "lines")} for b in blocks]},
        "score_test": score, "floors": floors, "proposals": proposals, "proposal_url": None, "proposal_pending_url": url,
        "candidates": candidates, "arms": standings, "warnings": warnings, "notes": notes, "playbooks": playbooks,
        "generated_at": now.isoformat(),
    }
    health.validate_details(details)
    status = RunStatus.error if failures else RunStatus.ok
    result: dict[str, Any] = {**details, "summary": summary, "status": status.value, "dry_run": dry_run, "run_id": None, "reviews_saved": [], "files": []}
    if dry_run:
        result["would_write"] = sorted(files)
        return result

    for block in blocks:
        if block.get("failed"):  # a line of excuses must not overwrite a good review of the same week
            continue
        report = "\n".join([*header, "", block["title"], *block["lines"]])  # the studio header, then his title and his lines
        review.save_review(store, monday, block["slug"], report, block["bar_status"])
        result["reviews_saved"].append(block["slug"])
    if out_dir is not None:
        for rel, text in files.items():
            target = out_dir / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
        result["files"] = sorted(files)
    result["run_id"] = store.add_run(Run(kind=RunKind.weekly, status=status, started_at=now, finished_at=now, summary=summary, details=details)).id
    return result


def confirm_proposal(store: Store, run_id: str) -> dict[str, Any]:
    """Publish a weekly run's pull request link: copy its ``proposal_pending_url`` into ``proposal_url``, which is what the terminal's
    Today card links. The cloud job calls this only after the propose job succeeded, so the card never links a compare page that does
    not exist. ``ValueError`` (the caller's error) for a value that is not a run id, an unknown run, a run that is not a weekly review,
    or one with no pending address of this repository's compare page. Already confirmed: nothing is written (``confirmed`` false)."""
    try:
        wanted = str(uuid.UUID(run_id))
    except ValueError:
        raise ValueError(f"{run_id!r:.40} is not a run id") from None
    run = next(iter(store.list_runs(id=wanted)), None)  # the one row, whatever other kinds of run the table holds
    if run is None:
        raise ValueError(f"no such run: {wanted}")
    if run.kind != RunKind.weekly:
        raise ValueError(f"run {wanted} is not a weekly run")
    pending = run.details.get("proposal_pending_url")
    if not isinstance(pending, str) or not pending.startswith(f"{PROPOSAL_REPO}/compare/"):
        raise ValueError(f"run {wanted} has no pending proposal link")
    if run.details.get("proposal_url") == pending:
        return {"run_id": wanted, "proposal_url": pending, "confirmed": False}
    store.update_run(wanted, details={**run.details, "proposal_url": pending})
    return {"run_id": wanted, "proposal_url": pending, "confirmed": True}


def confirm_proposal_command(
    run_id: Annotated[str, typer.Option("--run-id", help="The weekly run: the `run_id` that `studio review weekly` printed.")],
) -> None:
    """Link the weekly pull request on Today (the cloud job, after the proposal branch is on GitHub). Prints JSON."""
    try:
        emit(confirm_proposal(open_store(), run_id))
    except ValueError as e:
        fail(str(e))


def weekly_command(
    week: Annotated[str | None, typer.Option(help="The week to review: an ISO week like 2026-W42 or any YYYY-MM-DD in it (default: the last finished week).")] = None,
    out_dir: Annotated[Path | None, typer.Option("--out-dir", help="Write the proposal files (playbooks, docs/weekly/<monday>.md) here, mirroring the repo's paths.")] = None,
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Print the digest and the JSON; write nothing (no guard cut, no review, no run, no file).")] = False,
) -> None:
    """The weekly review (the Monday cloud job): the digest, the score test, the floors and the proposals; saves one review per live
    character and logs one run. Rerunning the same week rewrites its reviews and logs another run. Prints the run's JSON."""
    try:
        monday = review.parse_week(week) if week else None
        result = run_weekly(open_store(), now_london(), monday=monday, out_dir=out_dir, dry_run=dry_run)
    except ValueError as e:
        fail(str(e))
    emit(result)
