"""Weekly review data: feature lifts and the owner's pre-registered KPI bars.

The weekly-review skill reads ``studio review data`` and writes the report. Every verdict in it is
computed here, from the numbers, by the bars below. **The bars are binding**: the owner fixed them in
advance and they are module constants, never parameters of a verdict function (``min_n`` of
``feature_lifts`` is the one knob, and its default is the pre-registered 5). Nothing here reads a bar
from a config, a flag or the database, so no later run can renegotiate one.

========================  ====================================================================
hit                       a clip with ``outlier_x >= 3``
format                    keep: median ``outlier_x >= 1.5`` over >= 5 clips; kill: median
                          ``<= 0.7`` over >= 8 clips; otherwise continue
hook pattern              proven: >= 2 hits among its last 10 uses
feature lift              reported only for a value used by >= 5 clips (``min_n``)
character                 evaluated after 20 posts OR 4 weeks since its first post, whichever
                          comes first (else ``not_yet``). promote: median views per post >=
                          5,000 on either platform OR any post >= 100,000. kill: median < 500 on
                          BOTH platforms AND no post >= 10,000. Otherwise continue
Instagram guard           an Instagram account's non-follower reach % down >= 40 % week-on-week
                          sets that account's ``dropin_share`` to 0.20
========================  ====================================================================

How the numbers are read (the bars say *what*; these are the *how*, chosen so that a verdict never
rests on data that is not there yet):

* ``outlier_x`` is ``clip.features['outlier_x']`` (see ``studio.metrics``). A clip without one has no
  result yet and is left out of every median **and every count**: it is neither a post that missed nor
  a post that hit. One clip is one observation (a clip posted on two accounts carries the better
  ``outlier_x`` of the two).
* Medians are medians, never means. All comparisons are exact (``>=`` / ``<=`` / ``<`` on the raw
  value, no tolerance): 1.5 keeps, 1.4999 does not.
* "Last 10 uses" of a hook pattern: its 10 most recent *measured* clips by clip creation time.
* A post's **views** for the character bar's medians are its 7-day views (``metrics.views_at_7d``, the
  figure ``outlier_x`` is built on): a post younger than 7 days has none yet and is left out of the
  median, so a young post can never drag a character towards a kill. The "any post >= N" tests use a
  post's **peak** reading (the largest ``views`` in any snapshot; counters only grow, so a post that has
  crossed a line has crossed it). "Both platforms" needs a median on TikTok AND on Instagram: with no
  7-day figure on one of them the kill cannot be shown and the verdict is ``continue``.
* A character's posts are its ``posted`` posts on its accounts; 4 weeks are counted from the earliest
  of them (``claimed_at``, the time it went out).
* Instagram guard: per Instagram account, the median ``non_follower_pct`` of the snapshots captured in
  the 7 days up to ``now`` (``now - 7 d < captured_at <= now``) against the 7 days before
  (``now - 14 d < captured_at <= now - 7 d``). A week with no reading, or an earlier week at 0, is
  insufficient data and changes nothing. The cut only ever *lowers* the share: an account already at or
  below 0.20 is left as it is.

CLI (``studio review data``) prints the payload as JSON on stdout and, when the Instagram guard
fires, applies it (writes ``dropin_share``) and says so under ``ig_guard``. Exit 0 normally, exit 2
for anything the caller must fix (no ``DATABASE_URL``).

``studio review save --week W --character SLUG --report-file PATH --bar-status TEXT`` stores the
written report in ``reviews``, one row per (week, character): saving the same week again rewrites
that row, never adds a second. ``W`` is an ISO week (``2026-W41``) or any ``YYYY-MM-DD`` date in the
week; both are stored as the Monday of the week. The report is read from a file (free text never goes
through the shell). Exit 2 for an unknown character, a bad week or an empty report.
"""

from __future__ import annotations

import json
import math
import re
import statistics
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Annotated, Any, Literal

import typer

from studio.cli_support import emit, fail, open_store, text_option
from studio.clips import REQUIRED_FEATURES
from studio.config import now_london
from studio.metrics import posted_at, views_at_7d
from studio.models import Account, Clip, ClipState, Platform, PostStatus, Review, Snapshot
from studio.store import Store, require_aware

# ---- the pre-registered bars (binding: change nothing here without the owner) -----------------------

HIT_X = 3  # a clip with outlier_x >= 3 is a hit

FORMAT_KEEP_MEDIAN, FORMAT_KEEP_MIN_N = 1.5, 5  # keep: median >= 1.5 over >= 5 clips
FORMAT_KILL_MEDIAN, FORMAT_KILL_MIN_N = 0.7, 8  # kill: median <= 0.7 over >= 8 clips

HOOK_WINDOW, HOOK_MIN_HITS = 10, 2  # proven: >= 2 hits in the last 10 uses

LIFT_MIN_N = 5  # a feature value needs >= 5 clips to be reported

CHARACTER_MIN_POSTS = 20  # the bar opens after 20 posts ...
CHARACTER_MIN_AGE = timedelta(weeks=4)  # ... or 4 weeks since the first post, whichever comes first
PROMOTE_MEDIAN_VIEWS, PROMOTE_ANY_VIEWS = 5_000, 100_000  # median >= 5,000 on either platform, or any post >= 100,000
KILL_MEDIAN_VIEWS, KILL_ANY_VIEWS = 500, 10_000  # median < 500 on both platforms and no post >= 10,000

IG_GUARD_DROP_PCT = 40  # non-follower reach % down >= 40 % week-on-week ...
IG_GUARD_DROPIN_SHARE = 0.20  # ... cuts the account's dropin_share to 0.20

WEEK = timedelta(days=7)

Verdict = Literal["keep", "kill", "continue"]
Bar = Literal["promote", "kill", "continue", "not_yet"]

_EPOCH = datetime.min.replace(tzinfo=timezone.utc)


# ---- reading the numbers --------------------------------------------------------------------------


def clip_outlier_x(clip: Clip) -> float | None:
    """``features['outlier_x']`` as a float; ``None`` when absent or not a finite number."""
    value = clip.features.get("outlier_x")
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    return float(value)


def _median(values: list[Any]) -> Any:
    return statistics.median(values) if values else None


def _label(value: Any) -> str:
    return value if isinstance(value, str) else str(value)


# ---- feature lifts --------------------------------------------------------------------------------


@dataclass(frozen=True)
class Lift:
    """How clips that share one feature value performed against all measured clips.

    ``n`` clips (with an ``outlier_x``) carry ``feature == value``; their median ``outlier_x`` is
    ``median_outlier_x``. ``account_median`` is the median ``outlier_x`` of every measured clip in the
    set, the yardstick (an ``outlier_x`` is already relative to its own account's recent posts, so
    ``1.0`` is "as usual"). ``lift`` is their ratio.
    """

    feature: str
    value: Any
    n: int
    median_outlier_x: float
    account_median: float | None

    @property
    def lift(self) -> float | None:
        if not self.account_median:
            return None
        return self.median_outlier_x / self.account_median

    def as_dict(self) -> dict[str, Any]:
        return {
            "feature": self.feature,
            "value": self.value,
            "n": self.n,
            "median_outlier_x": self.median_outlier_x,
            "account_median": self.account_median,
            "lift": self.lift,
        }


def feature_lifts(clips: list[Clip], min_n: int = LIFT_MIN_N) -> list[Lift]:
    """One ``Lift`` per (required feature, value) used by at least ``min_n`` measured clips.

    Only ``REQUIRED_FEATURES`` keys are considered. Clips without an ``outlier_x`` and clips whose
    feature is absent or ``None`` do not count. Sorted by feature, then best median first.
    """
    rated = [(c, x) for c in clips if (x := clip_outlier_x(c)) is not None]
    overall = _median([x for _, x in rated])
    lifts: list[Lift] = []
    for feature in sorted(REQUIRED_FEATURES):
        groups: dict[str, tuple[Any, list[float]]] = {}
        for clip, x in rated:
            value = clip.features.get(feature)
            if value is None:
                continue
            key = json.dumps(value, sort_keys=True, default=str)  # True and 1 stay apart; lists are fine
            groups.setdefault(key, (value, []))[1].append(x)
        for key, (value, xs) in groups.items():
            if len(xs) >= min_n:
                lifts.append(Lift(feature, value, len(xs), _median(xs), overall))
    lifts.sort(key=lambda lf: (lf.feature, -lf.median_outlier_x, -lf.n, json.dumps(lf.value, default=str)))
    return lifts


# ---- format verdicts ------------------------------------------------------------------------------


def format_verdict(n: int, median: float | None) -> Verdict:
    """The bar for one format: ``n`` measured clips with this median ``outlier_x``."""
    if median is None:
        return "continue"
    if n >= FORMAT_KEEP_MIN_N and median >= FORMAT_KEEP_MEDIAN:
        return "keep"
    if n >= FORMAT_KILL_MIN_N and median <= FORMAT_KILL_MEDIAN:
        return "kill"
    return "continue"


@dataclass(frozen=True)
class FormatStat:
    format_id: str
    n: int  # measured clips
    median_outlier_x: float | None
    verdict: Verdict


def format_stats(clips: list[Clip]) -> list[FormatStat]:
    """Every ``format_id`` seen among ``clips`` (sorted), with its evidence and verdict."""
    groups: dict[str, list[float]] = {}
    for clip in clips:
        fmt = clip.features.get("format_id")
        if fmt is None:
            continue
        xs = groups.setdefault(_label(fmt), [])
        if (x := clip_outlier_x(clip)) is not None:
            xs.append(x)
    return [
        FormatStat(fmt, len(xs), (m := _median(xs)), format_verdict(len(xs), m))
        for fmt, xs in sorted(groups.items())
    ]


def format_verdicts(clips: list[Clip]) -> dict[str, Verdict]:
    """``{format_id: 'keep' | 'kill' | 'continue'}`` (keep >= 1.5 over >= 5, kill <= 0.7 over >= 8)."""
    return {s.format_id: s.verdict for s in format_stats(clips)}


# ---- hook patterns --------------------------------------------------------------------------------


def hook_uses(clips: list[Clip]) -> dict[str, list[float]]:
    """``{hook_pattern: outlier_x of its last 10 measured uses, oldest first}``.

    Uses are ordered by clip creation time (ties keep the caller's order). A pattern with no
    measured use maps to ``[]``.
    """
    groups: dict[str, list[Clip]] = {}
    for clip in clips:
        pattern = clip.features.get("hook_pattern")
        if pattern is not None:
            groups.setdefault(_label(pattern), []).append(clip)
    out: dict[str, list[float]] = {}
    for pattern, uses in groups.items():
        ordered = sorted(uses, key=lambda c: c.created_at or _EPOCH)
        out[pattern] = [x for c in ordered if (x := clip_outlier_x(c)) is not None][-HOOK_WINDOW:]
    return out


def hook_proven(clips: list[Clip]) -> dict[str, bool]:
    """``{hook_pattern: True}`` when >= 2 of its last 10 uses are hits (``outlier_x >= 3``)."""
    return {
        pattern: sum(x >= HIT_X for x in xs) >= HOOK_MIN_HITS for pattern, xs in hook_uses(clips).items()
    }


# ---- character bar --------------------------------------------------------------------------------


@dataclass(frozen=True)
class CharacterEvidence:
    """What the character bar was decided on, so the report can show its working."""

    slug: str
    bar: Bar
    posts: int
    first_post_at: datetime | None
    age: timedelta | None
    mature_posts: dict[Platform, int]  # posts with a 7-day figure
    median_views_7d: dict[Platform, float | None]
    max_views: int | None  # the best peak reading of any post

    def as_dict(self, name: str | None = None) -> dict[str, Any]:
        return {
            "slug": self.slug,
            "name": name,
            "bar": self.bar,
            "posts": self.posts,
            "first_post_at": self.first_post_at.isoformat() if self.first_post_at else None,
            "age_days": self.age.total_seconds() / 86400 if self.age is not None else None,
            "mature_posts": {p.value: n for p, n in self.mature_posts.items()},
            "median_views_7d": {p.value: m for p, m in self.median_views_7d.items()},
            "max_views": self.max_views,
        }


def character_evidence(store: Store, slug: str, now: datetime) -> CharacterEvidence:
    """The character's numbers and its bar (see the module docstring for the rules)."""
    require_aware(now, "character_bar(now)")
    accounts = store.accounts(slug)
    platform_of = {a.id: a.platform for a in accounts}
    posts = [
        p for a in accounts for p in store.list_posts(account_id=a.id, status=PostStatus.posted)
    ]  # fmt: skip
    mature: dict[Platform, list[int]] = {p: [] for p in Platform}
    peaks: list[int] = []
    for post in posts:
        if (v7 := views_at_7d(store, post)) is not None:
            mature[platform_of[post.account_id]].append(v7)
        views = [s.views for s in store.snapshots_for(post.id) if s.views is not None]
        if views:
            peaks.append(max(views))
    first = min((posted_at(p) for p in posts), default=None)
    age = now - first if first is not None else None
    medians = {p: _median(v) for p, v in mature.items()}
    best = max(peaks, default=None)

    bar: Bar
    if len(posts) < CHARACTER_MIN_POSTS and (age is None or age < CHARACTER_MIN_AGE):
        bar = "not_yet"
    elif any(m is not None and m >= PROMOTE_MEDIAN_VIEWS for m in medians.values()) or (
        best is not None and best >= PROMOTE_ANY_VIEWS
    ):
        bar = "promote"
    elif all(m is not None and m < KILL_MEDIAN_VIEWS for m in medians.values()) and not (
        best is not None and best >= KILL_ANY_VIEWS
    ):
        bar = "kill"
    else:
        bar = "continue"
    return CharacterEvidence(
        slug=slug,
        bar=bar,
        posts=len(posts),
        first_post_at=first,
        age=age,
        mature_posts={p: len(v) for p, v in mature.items()},
        median_views_7d=medians,
        max_views=best,
    )


def character_bar(store: Store, slug: str, now: datetime) -> Bar:
    """``promote`` / ``kill`` / ``continue``, or ``not_yet`` before 20 posts AND before 4 weeks."""
    return character_evidence(store, slug, now).bar


# ---- Instagram guard ------------------------------------------------------------------------------


def _account_snapshots(store: Store, account: Account) -> list[Snapshot]:
    return [
        s
        for post in store.list_posts(account_id=account.id)
        for s in store.snapshots_for(post.id)
        if s.captured_at is not None
    ]  # fmt: skip


def _week_median(snaps: list[Snapshot], field: str, end: datetime) -> float | None:
    """Median of ``field`` over the snapshots captured in ``(end - 7 d, end]`` (None values left out)."""
    values = [
        v for s in snaps
        if end - WEEK < s.captured_at <= end and (v := getattr(s, field)) is not None
    ]  # fmt: skip
    return _median(values)


def _guard_fires(previous: float | None, current: float | None) -> bool:
    """Reach down >= 40 % week-on-week (needs a reading in both weeks and a non-zero earlier week)."""
    if previous is None or current is None or previous <= 0:
        return False
    return (previous - current) * 100 >= IG_GUARD_DROP_PCT * previous


def _drop_pct(previous: float | None, current: float | None) -> float | None:
    if previous is None or current is None or previous <= 0:
        return None
    return (previous - current) / previous * 100


def ig_guard(store: Store, account: Account, now: datetime) -> bool:
    """True when this Instagram account's non-follower reach % fell >= 40 % week-on-week.

    True means its ``dropin_share`` must be cut to 0.20 (``apply_ig_guard`` does that). Any other
    platform, or too little data (no reading in a week, or an earlier week at 0), is False.
    """
    require_aware(now, "ig_guard(now)")
    if account.platform is not Platform.instagram:
        return False
    snaps = _account_snapshots(store, account)
    return _guard_fires(
        _week_median(snaps, "non_follower_pct", now - WEEK),
        _week_median(snaps, "non_follower_pct", now),
    )


def _cut_share(store: Store, account: Account) -> bool:
    """Set ``dropin_share`` to 0.20 unless it is already at or below it. True when it wrote."""
    if account.dropin_share is not None and account.dropin_share <= IG_GUARD_DROPIN_SHARE:
        return False
    store.update_account(account.id, dropin_share=IG_GUARD_DROPIN_SHARE)
    return True


def apply_ig_guard(store: Store, account: Account, now: datetime) -> bool:
    """Run ``ig_guard`` and, when it fires, cut the account's ``dropin_share`` to 0.20.

    Returns whether the bar fired (an account already at or below 0.20 is left alone: the cut never
    raises a share).
    """
    if not ig_guard(store, account, now):
        return False
    _cut_share(store, account)
    return True


# ---- the payload ----------------------------------------------------------------------------------


def bars() -> dict[str, Any]:
    """The binding bars as data, so the report quotes them from the code rather than from memory."""
    return {
        "hit_outlier_x": HIT_X,
        "format": {
            "keep_median": FORMAT_KEEP_MEDIAN,
            "keep_min_posts": FORMAT_KEEP_MIN_N,
            "kill_median": FORMAT_KILL_MEDIAN,
            "kill_min_posts": FORMAT_KILL_MIN_N,
        },
        "hook": {"min_hits": HOOK_MIN_HITS, "last_uses": HOOK_WINDOW},
        "lift_min_posts": LIFT_MIN_N,
        "character": {
            "min_posts": CHARACTER_MIN_POSTS,
            "min_weeks": CHARACTER_MIN_AGE // WEEK,
            "promote_median_views": PROMOTE_MEDIAN_VIEWS,
            "promote_any_post_views": PROMOTE_ANY_VIEWS,
            "kill_median_views": KILL_MEDIAN_VIEWS,
            "kill_any_post_views": KILL_ANY_VIEWS,
        },
        "ig_guard": {"reach_drop_pct": IG_GUARD_DROP_PCT, "dropin_share": IG_GUARD_DROPIN_SHARE},
    }


def review_payload(store: Store, now: datetime, *, apply_guard: bool = False) -> dict[str, Any]:
    """Everything the weekly-review skill needs, as JSON-serialisable data.

    Read-only unless ``apply_guard``: then every Instagram account whose guard fires and whose
    ``dropin_share`` is above 0.20 is cut to 0.20 and its ``ig_guard`` entry says ``applied``.

    Sections: ``as_of``, ``bars``, ``clips`` (counts and hit rate), ``lifts``, ``formats`` (with
    verdicts), ``hooks`` (with ``proven``), ``characters`` (bar and evidence), ``accounts`` (this
    week's median ``non_follower_pct`` / ``skip_rate`` / ``watched_pct``, ``null`` when no snapshot of
    the week reported it) and ``ig_guard`` (one entry per Instagram account).
    """
    require_aware(now, "review_payload(now)")
    clips = [
        c for c in store.list_clips() if c.state is ClipState.posted or clip_outlier_x(c) is not None
    ]  # fmt: skip
    measured = [x for c in clips if (x := clip_outlier_x(c)) is not None]
    hits = sum(x >= HIT_X for x in measured)
    uses = hook_uses(clips)
    proven = hook_proven(clips)

    names = {c.slug: c.name for c in store.characters()}
    accounts_out: list[dict[str, Any]] = []
    guard_out: list[dict[str, Any]] = []
    for account in store.accounts():
        snaps = _account_snapshots(store, account)
        this_week = _week_median(snaps, "non_follower_pct", now)
        last_week = _week_median(snaps, "non_follower_pct", now - WEEK)
        accounts_out.append(
            {
                "account_id": account.id,
                "character_slug": account.character_slug,
                "platform": account.platform.value,
                "handle": account.handle,
                "dropin_share": account.dropin_share,
                "snapshots_this_week": sum(now - WEEK < s.captured_at <= now for s in snaps),
                "non_follower_pct": this_week,
                "non_follower_pct_previous_week": last_week,
                "skip_rate": _week_median(snaps, "skip_rate", now),
                "watched_pct": _week_median(snaps, "watched_pct", now),
            }
        )
        if account.platform is not Platform.instagram:
            continue
        fires = _guard_fires(last_week, this_week)
        will_cut = fires and (
            account.dropin_share is None or account.dropin_share > IG_GUARD_DROPIN_SHARE
        )
        applied = bool(apply_guard and will_cut and _cut_share(store, account))
        guard_out.append(
            {
                "account_id": account.id,
                "character_slug": account.character_slug,
                "handle": account.handle,
                "non_follower_pct_previous_week": last_week,
                "non_follower_pct_this_week": this_week,
                "drop_pct": _drop_pct(last_week, this_week),
                "fires": fires,
                "dropin_share": account.dropin_share,
                "new_dropin_share": IG_GUARD_DROPIN_SHARE if will_cut else None,
                "applied": applied,
            }
        )

    return {
        "as_of": now.isoformat(),
        "bars": bars(),
        "clips": {
            "posted": len(clips),
            "measured": len(measured),
            "hits": hits,
            "hit_rate": hits / len(measured) if measured else None,
        },
        "lifts": [lf.as_dict() for lf in feature_lifts(clips)],
        "formats": [
            {
                "format_id": s.format_id,
                "n": s.n,
                "median_outlier_x": s.median_outlier_x,
                "verdict": s.verdict,
            }
            for s in format_stats(clips)
        ],
        "hooks": [
            {
                "hook_pattern": pattern,
                "uses_counted": len(xs),
                "hits_last_10": sum(x >= HIT_X for x in xs),
                "proven": proven[pattern],
            }
            for pattern, xs in sorted(uses.items())
        ],
        "characters": [
            character_evidence(store, slug, now).as_dict(names[slug]) for slug in sorted(names)
        ],
        "accounts": accounts_out,
        "ig_guard": guard_out,
    }


# ---- saving the written report --------------------------------------------------------------------

_ISO_WEEK = re.compile(r"(\d{4})-W(\d{2})", re.IGNORECASE)


def parse_week(value: str) -> date:
    """The Monday of an ISO week (``2026-W41``) or of the week a ``YYYY-MM-DD`` date falls in.

    ``ValueError`` for anything else, including a week the year does not have (``2025-W53``).
    """
    raw = value.strip()
    try:
        match = _ISO_WEEK.fullmatch(raw)
        if match:
            return date.fromisocalendar(int(match[1]), int(match[2]), 1)
        day = date.fromisoformat(raw)
    except ValueError:
        raise ValueError(
            f"week must be an ISO week like 2026-W41 or a YYYY-MM-DD date, got {value!r}"
        ) from None
    return day - timedelta(days=day.weekday())


def save_review(
    store: Store, week: date, character_slug: str, report_md: str, bar_status: str | None
) -> Review:
    """Store (or rewrite) the report of ``character_slug`` for the ISO week containing ``week``.

    ``ValueError`` for an empty report or an unknown character; nothing is written then.
    """
    if not report_md.strip():
        raise ValueError("the report is empty")
    if character_slug not in {c.slug for c in store.characters()}:
        raise ValueError(f"unknown character {character_slug!r}")
    monday = week - timedelta(days=week.weekday())
    return store.upsert_review(
        Review(week=monday, character_slug=character_slug, report_md=report_md, bar_status=bar_status)
    )


# ---- CLI ------------------------------------------------------------------------------------------

app = typer.Typer(
    help="Weekly review: lift table and the pre-registered KPI bars. Prints JSON.",
    no_args_is_help=True,
)


@app.command("data")
def data_command() -> None:
    """Print the weekly review data; applies the Instagram guard (dropin_share 0.20) when it fires."""
    emit(review_payload(open_store(), now_london(), apply_guard=True))


@app.command("save")
def save_command(
    week: Annotated[str, typer.Option(help="ISO week like 2026-W41, or any YYYY-MM-DD date in it.")],
    character: Annotated[str, typer.Option(help="Character slug (biscuit, reginald).")],
    report_file: Annotated[
        Path, typer.Option("--report-file", help="The markdown report (written with the Write tool).")
    ],
    bar_status: Annotated[
        str, typer.Option("--bar-status", help="The character bar: not_yet, continue, promote or kill.")
    ],
) -> None:
    """Save a character's weekly report; the same week and character is rewritten, not duplicated."""
    try:
        monday = parse_week(week)
    except ValueError as e:
        fail(str(e))
    report = text_option(None, report_file, "report")
    status = bar_status.strip()
    if not status:
        fail("--bar-status must not be empty")
    try:
        saved = save_review(open_store(), monday, character, report or "", status)
    except ValueError as e:
        fail(str(e))
    emit(
        {
            "id": saved.id,
            "week": saved.week,
            "character_slug": saved.character_slug,
            "bar_status": saved.bar_status,
            "report_chars": len(saved.report_md),
        }
    )
