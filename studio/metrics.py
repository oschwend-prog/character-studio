"""Metrics: pull post analytics from Postiz, ingest vidIQ Instagram insights, compute ``outlier_x``.

**Pull** (``studio metrics pull``, run by the metrics workflow at whatever cadence it likes: every
6 hours, a missed run loses nothing). For every post that is ``posted`` and has a
Postiz id, the post's age (from ``claimed_at``; the posts table has no ``posted_at``, ``claimed_at`` is
when ``publish_due`` claimed it, ``scheduled_for`` is the fallback) puts it in one **catch-up window**:
the latest of 1 h / 24 h / 72 h / 7 d (``WINDOWS``, the window *starts*) whose start has passed. The
windows tile a post's life (1 h = [1 h, 24 h), 24 h = [24 h, 72 h), 72 h = [72 h, 7 d), 7 d = [7 d, for
ever): the tiling classifies a snapshot, ``ABANDON_AFTER`` is when a pull stops), and a snapshot belongs to the window its own age falls in, so every snapshot maps to exactly
one window (a snapshot younger than 1 h belongs to none). A window is due when the post has reached it
and holds no snapshot of it yet; a due window is pulled as soon as a run sees it, however late (the 7 d
window up to 14 d, see below). (A run that first meets a post at 30 h pulls the 24 h window; the 1 h window
is gone for good, a snapshot taken at 30 h can only honestly be a 24 h one.) The 7 d window gives up
at post age > ``ABANDON_AFTER`` (14 d): a post that old with no 7 d snapshot (deleted, never indexed)
is no longer fetched and is listed under ``abandoned`` (not ``errors``), so it cannot keep the
Action red for ever. It is listed for 14 more days (``ABANDON_REPORT_FOR``) and is then skipped before
any snapshot query, so a run's work is bounded by the last 28 days of posts, not the whole library;
past 14 d a post's clip is no longer refreshed from the pull (an ingest still does). A pull runs
``postiz analytics:post <postiz-post-id> -d 7`` and writes one ``Snapshot`` with ``captured_at = now``.
**Idempotent per (post, window):** a window that already holds a snapshot of the post (from any
source) is never pulled again, so a job that runs every 5 minutes writes one snapshot per window, not
twelve. ``{"missing": true}`` (Postiz has the post but no provider id yet; ``postiz posts:missing`` /
``posts:connect`` resolves it by hand) writes no snapshot, is logged and is listed under ``missing`` in
the summary; the window stays due, so the next run asks again. A reply with none of the metrics we know
writes nothing either (``empty``). A metric the platform did not report is ``None``, never 0, and the
numbers are never guessed.

**outlier_x** = the post's views at 7 days / the median of the account's last 15 earlier posts' 7-day
views. A post's "7-day views" is the FIRST snapshot taken at or after day 7 that has ``views``, whoever
wrote it (Postiz pull or vidIQ ingest): first, so the figure never moves once it exists, and a late pull
(day 7 + 5 h, or day 9) still counts. Posts without one are left out of the median, never counted as 0;
fewer than 3 usable priors, or no views for this post, means ``None`` and nothing is written. The
clip's ``features['outlier_x']`` is the max over its accounts' values (a clip has at most one post per
account). It is (re)computed whenever a 7-day figure exists or changes: for every clip that has a
post with a new 7 d snapshot (a pull or an ingest just wrote it) and for every clip aged 7 d or more
that has no ``outlier_x`` yet, so a crash between the snapshot write and the clip write heals on the
next run. A value, once written, is only recomputed when one of its posts gets a new 7 d snapshot. The
other keys of ``features`` are never touched.

**72-hour reads and ``x72``** (``docs/launch/measurement-and-learning-plan.md`` sections 1.1-1.2, learning build item 5). A post's
**72-hour views** are the ``views`` of its FIRST snapshot from 72 h up to day 7 (``views_at_72h``: its 72 h window; a reading
from day 7 on is the 7-day figure, so a post whose 72 h window was missed has none). ``x72`` = 72-hour views / the median
72-hour views of the account's last 15 strictly earlier posts, by the very rules of ``outlier_x`` (at least 3 usable priors, a
missing figure is left out and never 0, a zero median is undefined; ``x72`` / ``post_x72``). It is **not binding**: only the hook
bandit (``studio.learn``) and the quick reads use it. Nothing about it is stored (no migration, no feature key): ``post_reads``
computes every posted post's ``views_72h``, ``x72``, ``views_7d`` and ``outlier_x`` on read, per account and so **per platform**
(an account has one platform; ``best_by_platform`` rolls a clip's posts up by platform, beside the binding
``features['outlier_x']``, which stays the better of the clip's accounts'). ``studio review data`` prints them under ``posts``.

**Instagram insights.** ``ingest_ig_insights(store, rows)`` takes the rows of vidIQ's
``instagram_owner_insights`` (the weekly-review skill fetches them; ``studio metrics ingest-ig`` feeds
them in), matches each to a post on ``platform_post_id`` and writes a snapshot of views / likes /
comments / shares / saves / watch time / skip rate / watched percentage (the last two are the Reels
KPIs the weekly review reports, migration 0002; stored in the units vidIQ reports). Fields we do not
store (the trial flag, ...) are ignored. Nullable values stay ``None``; a row with no usable metric,
or whose numbers equal the post's latest snapshot, writes nothing.

**Account daily totals** (``studio metrics accounts``, owner 2026-10-15; ``pull_accounts``). Postiz gives no numbers for a single
Story (``analytics:post <story id>`` prints ``[]``), but ``analytics:platform <integration id> -d 7`` prints the ACCOUNT's figures,
Stories included. **They are not all per day** (verified live 2026-10-15): Reach is a daily series (one point per London day,
Instagram's ``time_series`` metric), but Views, Likes, Comments, Shares, Saves and Replies come as ONE total over the whole ``-d``
window, stamped with the day it was read (Instagram's ``total_value`` metrics). So a label with two or more points is a daily
series, and a label with exactly one point is a **window total** (``AccountReading``); the first version stored the window total as
"views on the day it was read", which was wrong. For every live character's account with a Postiz integration the figures are stored
in ``studio.runs`` as kind ``account_daily``, one row per London day (started_at = noon London of that day), updated in place:

- the daily series, in ``details = {"day", "accounts": {handle: {reach}}}`` (only daily fields, never a window one);
- the 7-day window totals, on the row of the day they were read (today in London), in
  ``details.window = {"days": 7, "read_at": <ISO>, "accounts": {handle: {views, likes, comments, shares, saves, replies}}}``.

A later read of the same day overwrites them, an identical read writes nothing (``read_at`` stays). The rows the first version wrote
(a window field under ``accounts``) are cleaned whenever their day's row is written. No migration (``runs`` has no constraint on
``kind``). A Postiz failure never fails the job: it is a warning in the JSON (``postiz_errors``) and exit 0. The terminal's "Account
per day" block (Artist page) shows the reach per day beside the views his Reels gained that day, and the newest window total as
"Account views, last 7 days" with what his Reels gained in the same days, so the rest (Stories, older posts) is visible.

CLI (``studio metrics ...``) prints JSON on stdout; exit 0 normally (``missing`` and ``abandoned`` posts
included), exit 1 when a pull failed (the Action goes red; the window stays due, so the next run tries
again) or, for ``accounts``, when a database write failed, exit 2 for anything the caller must fix
(no ``DATABASE_URL``, ``POSTIZ_API_KEY`` or ``postiz`` binary, unreadable input).
"""

from __future__ import annotations

import dataclasses
import json
import logging
import math
import statistics
import subprocess
import sys
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from shutil import which
from typing import Annotated, Any

import typer

from studio.cli_support import emit, fail, open_store
from studio.config import LONDON, load, now_london
from studio.models import Post, PostStatus, Run, RunKind, RunStatus, Snapshot
from studio.publish.postiz import _json_in, _tail
from studio.store import Store, require_aware

log = logging.getLogger("studio.metrics")

# ---- pull windows ---------------------------------------------------------------------------------

# Catch-up windows: each entry is the post age at which the window STARTS; a window ends where the
# next one starts, and the last one never ends (see the module docstring).
WINDOWS: tuple[tuple[str, timedelta], ...] = (
    ("1h", timedelta(hours=1)),
    ("24h", timedelta(hours=24)),
    ("72h", timedelta(hours=72)),
    ("7d", timedelta(days=7)),
)
SEVEN_DAYS = dict(WINDOWS)["7d"]
THREE_DAYS = dict(WINDOWS)["72h"]
# The 7 d window is the last one and has no end as a classification (a late snapshot still belongs
# to it), but a pull gives up on a post older than ABANDON_AFTER with no 7 d snapshot: it is reported as
# abandoned for ABANDON_REPORT_FOR more days (so the owner sees it), then dropped from the run entirely:
# a post older than both is skipped before any snapshot query, which bounds the work of every run to
# the last 28 days of posts however long the library grows.
ABANDON_AFTER = timedelta(days=14)
ABANDON_REPORT_FOR = timedelta(days=14)

MIN_PRIORS = 3  # fewer non-None prior 7-day views than this: no baseline, outlier_x is None
MAX_PRIORS = 15  # the baseline is the median of the account's last 15

ANALYTICS_DAYS = 7  # `postiz analytics:post <id> -d 7`
ANALYTICS_TIMEOUT_S = 120

# ---- Postiz field mapping -------------------------------------------------------------------------
# ``analytics:post`` prints an array of metrics, one per label, each with daily data points:
#   [{"label": "Views", "data": [{"total": "123", "date": "2026-10-20"}], "percentageChange": 0}, ...]
# Per snapshot field, the labels (case-insensitive) that feed it, most preferred first. Only labels
# believed to mean exactly that are mapped; anything else stays None (watch time and follows are left
# out until their labels and units are seen on a real account). Several data points: the latest date
# wins (TikTok and Instagram report one cumulative total per metric).
# VERIFY at go-live (Task 16): postiz analytics:post <id> -d 7 on a real TikTok and Instagram post.
POSTIZ_METRIC_LABELS: dict[str, tuple[str, ...]] = {
    "views": ("views", "video views", "plays", "impressions"),
    "likes": ("likes",),
    "comments": ("comments",),
    "shares": ("shares",),
    "saves": ("saves",),
}

# How a metric's data points (one per day) combine into the snapshot value:
#   "latest": the point with the newest date (the points are cumulative totals, as TikTok and Instagram
#             report per-post counters),
#   "sum":    the sum of all points (the points are per-day increments).
# VERIFY at go-live (Task 16): cumulative totals vs per-day increments, on a real post of each platform.
POSTIZ_SERIES_MODE = "latest"

# ---- Postiz ``analytics:platform`` (the account's figures) ----------------------------------------
# ``postiz analytics:platform <integration id> -d 7`` prints the ACCOUNT's figures, one entry per label:
#   [{"label": "Reach", "percentageChange": 0, "data": [{"total": "161", "date": "2026-10-13"}, {"total": "127", "date": "2026-10-14"}, ...]},
#    {"label": "Views", "percentageChange": 0, "data": [{"total": "334", "date": "2026-10-15"}]}, ...]
# with the labels Reach, Likes, Views, Comments, Shares, Saves and Replies (an account may lack some). Verified live 2026-10-15
# (lennygold.agent, ``-d 7``): Reach has one point per day (a daily series); Views, Likes, Comments, Shares, Saves and Replies have ONE
# point, the total over the whole window, dated the day it was read. A label with two or more points is therefore a daily series, a
# label with exactly one point a window total (whatever its date). Reach is a daily series by nature (it has no window total here),
# so a single reach point is still a day. Unlike ``analytics:post`` this includes the Stories, which Postiz cannot report one by one
# (``analytics:post <story id>`` prints ``[]``). Per field, the labels (case-insensitive) that feed it, most preferred first; anything
# else is left out.
ACCOUNT_DAYS = 7  # `postiz analytics:platform <integration id> -d 7`: the window of the totals, and the week the terminal shows
ACCOUNT_METRIC_LABELS: dict[str, tuple[str, ...]] = {
    "views": ("views", "video views", "plays"),
    "reach": ("reach",),
    "likes": ("likes",),
    "comments": ("comments",),
    "shares": ("shares",),
    "saves": ("saves",),
    "replies": ("replies",),
}
# The fields Instagram gives as one total over the window (``details.window``), not per day; the rows of the first version held
# these under ``accounts``, and ``_store_account_day`` removes them from there.
ACCOUNT_WINDOW_FIELDS: tuple[str, ...] = ("views", "likes", "comments", "shares", "saves", "replies")

# ---- vidIQ ``instagram_owner_insights`` field mapping ---------------------------------------------
# Key names tried per snapshot field, most preferred first. The tool reports "views/plays, shares,
# saves, watch time, watched percentage, skip rate", and nullable values mean "unavailable".
# VERIFY at go-live (Task 16): the exact keys, the watch-time unit, and which id identifies a reel
# (our ``platform_post_id`` is the Postiz post id: it must equal the id vidIQ reports, or ingest
# matches nothing).
IG_ID_KEYS: tuple[str, ...] = (
    "platform_post_id", "platformPostId", "postId", "post_id", "mediaId", "media_id", "id",
)  # fmt: skip
IG_COUNT_KEYS: dict[str, tuple[str, ...]] = {
    "views": ("views", "viewCount", "views_count", "plays", "playCount", "videoViews"),
    "likes": ("likes", "likeCount", "likes_count"),
    "comments": ("comments", "commentCount", "comments_count"),
    "shares": ("shares", "shareCount", "shares_count"),
    "saves": ("saves", "saveCount", "saves_count"),
}
IG_WATCH_TIME_S_KEYS: tuple[str, ...] = (
    "watchTimeSeconds", "watch_time_s", "watchTimeS", "watchTime", "watch_time",
)  # fmt: skip
IG_WATCH_TIME_MS_KEYS: tuple[str, ...] = ("watchTimeMs", "watch_time_ms")
# The two Reels KPIs stored as reported (no unit conversion: VERIFY whether vidIQ sends a fraction
# or a percentage; the weekly review only compares an account with its own earlier weeks).
IG_SKIP_RATE_KEYS: tuple[str, ...] = ("skipRate", "skip_rate", "skipRatePct", "skip_rate_pct")
IG_WATCHED_PCT_KEYS: tuple[str, ...] = (
    "watchedPercentage", "watched_percentage", "watchedPct", "watched_pct", "watchedPercent",
)  # fmt: skip

_COUNT_FIELDS = ("views", "likes", "comments", "shares", "saves")
_METRIC_FIELDS = (*_COUNT_FIELDS, "watch_time_s", "skip_rate", "watched_pct")


class AnalyticsError(RuntimeError):
    """``postiz analytics:post`` failed or printed something that is not JSON."""


# ---- outlier_x ------------------------------------------------------------------------------------


def outlier_x(views_7d: int | None, prior_views_7d: list[int | None]) -> float | None:
    """``views_7d`` / median of the last ``MAX_PRIORS`` non-``None`` priors (oldest first).

    ``None`` when this post has no views, when there are fewer than ``MIN_PRIORS`` non-``None``
    priors, or when the median is 0 (the ratio is undefined). Missing data is never counted as 0.
    """
    if views_7d is None:
        return None
    priors = [v for v in prior_views_7d if v is not None][-MAX_PRIORS:]
    if len(priors) < MIN_PRIORS:
        return None
    baseline = statistics.median(priors)
    if baseline == 0:
        return None
    return views_7d / baseline


def posted_at(post: Post) -> datetime:
    """When the post went out: ``claimed_at`` (the posts table has no ``posted_at``), else its slot."""
    return post.claimed_at or post.scheduled_for


def window_at(age: timedelta) -> str | None:
    """The window an age falls in: the latest whose start has passed; ``None`` before the first."""
    found = None
    for name, start in WINDOWS:
        if age >= start:
            found = name
    return found


def _snapshots_in_window(store: Store, post: Post, window: str) -> list[Snapshot]:
    """The post's snapshots whose own age falls in ``window`` (oldest first)."""
    at = posted_at(post)
    return [
        s for s in store.snapshots_for(post.id)
        if s.captured_at and window_at(s.captured_at - at) == window
    ]  # fmt: skip


def _views_between(snapshots: list[Snapshot], at: datetime, start: timedelta, end: timedelta | None = None) -> int | None:
    """``views`` of the FIRST snapshot (by time) that has any and whose age (since ``at``) is ``start`` or more and, when ``end`` is
    given, below it; ``None`` when there is none. First, so the figure never moves once it exists."""
    for snap in sorted(snapshots, key=lambda s: s.captured_at):
        age = snap.captured_at - at
        if snap.views is not None and age >= start and (end is None or age < end):
            return snap.views
    return None


def views_at_7d(store: Store, post: Post) -> int | None:
    """``views`` of the FIRST snapshot taken at or after day 7 that has any, else ``None``."""
    return _views_between(store.snapshots_for(post.id), posted_at(post), SEVEN_DAYS)


def views_at_72h(store: Store, post: Post) -> int | None:
    """The post's 72-hour views (learning plan section 1.1): ``views`` of the FIRST snapshot that has any and was taken from 72 h
    up to (not including) day 7, i.e. the post's 72 h window (``window_at``). A reading from day 7 on is the 7-day figure, not
    a 72-hour one, so a post whose 72 h window was missed has none (the plan: neither a win nor a loss)."""
    return _views_between(store.snapshots_for(post.id), posted_at(post), THREE_DAYS, SEVEN_DAYS)


def x72(views_72h: int | None, prior_views_72h: list[int | None]) -> float | None:
    """``x72``, the early read (learning plan section 1.2): the post's 72-hour views / the median 72-hour views of the account's
    last ``MAX_PRIORS`` earlier posts. The same rules as ``outlier_x`` (fewer than ``MIN_PRIORS`` usable priors, no views of its own
    or a zero median: ``None``), only with 72-hour readings. Never binding: only the hook bandit and the quick reads use it."""
    return outlier_x(views_72h, prior_views_72h)


def _post_ratio(store: Store, post: Post, views_of: Callable[[Store, Post], int | None]) -> float | None:
    views = views_of(store, post)
    if views is None:
        return None
    me = posted_at(post)
    earlier = sorted(
        (p for p in store.list_posts(account_id=post.account_id, status=PostStatus.posted)
         if p.id != post.id and posted_at(p) < me),
        key=posted_at,
    )  # fmt: skip
    priors: list[int] = []  # newest first, until the last MAX_PRIORS usable ones are in hand
    for p in reversed(earlier):
        if (v := views_of(store, p)) is not None:
            priors.append(v)
            if len(priors) == MAX_PRIORS:
                break
    return outlier_x(views, priors[::-1])


def post_outlier_x(store: Store, post: Post) -> float | None:
    """This post's ``outlier_x``: its 7-day views against the account's earlier posts' 7-day views."""
    return _post_ratio(store, post, views_at_7d)


def post_x72(store: Store, post: Post) -> float | None:
    """This post's ``x72``: its 72-hour views against the account's earlier posts' 72-hour views."""
    return _post_ratio(store, post, views_at_72h)


@dataclass(frozen=True)
class PostRead:
    """What one posted post has been read at (compute on read: nothing here is stored). ``outlier_x`` and ``x72`` are the post's own
    account's (so per platform: an account has one platform); a ``None`` is "no value yet", never 0."""

    post_id: str
    clip_id: str
    account_id: str
    character_slug: str
    platform: str
    handle: str
    posted_at: datetime
    views_72h: int | None
    x72: float | None
    views_7d: int | None
    outlier_x: float | None

    def as_dict(self) -> dict[str, Any]:
        return {**dataclasses.asdict(self), "posted_at": self.posted_at.isoformat()}


def post_reads(store: Store, *, character_slug: str | None = None) -> list[PostRead]:
    """The 72-hour and 7-day reads of every ``posted`` post of every account (or of one character's), oldest first per account.

    Each post's own ``views_72h`` / ``views_7d`` come from its first snapshot of that window; ``x72`` / ``outlier_x`` divide them
    by the median of the account's last ``MAX_PRIORS`` strictly earlier posts' figure, as ``post_x72`` / ``post_outlier_x`` do (the
    same numbers, with one snapshot query per post instead of one per prior)."""
    reads: list[PostRead] = []
    for account in store.accounts(character_slug):
        posts = sorted(
            (p for p in store.list_posts(account_id=account.id, status=PostStatus.posted)),
            key=lambda p: (posted_at(p), p.id),
        )  # fmt: skip
        views: dict[str, tuple[int | None, int | None]] = {}
        for p in posts:
            snaps, at = store.snapshots_for(p.id), posted_at(p)
            views[p.id] = (_views_between(snaps, at, THREE_DAYS, SEVEN_DAYS), _views_between(snaps, at, SEVEN_DAYS))
        for p in posts:
            earlier = [q for q in posts if posted_at(q) < posted_at(p)]
            v72, v7 = views[p.id]
            reads.append(
                PostRead(
                    post_id=p.id, clip_id=p.clip_id, account_id=account.id, character_slug=account.character_slug,
                    platform=account.platform.value, handle=account.handle, posted_at=posted_at(p),
                    views_72h=v72, x72=x72(v72, [views[q.id][0] for q in earlier]),
                    views_7d=v7, outlier_x=outlier_x(v7, [views[q.id][1] for q in earlier]),
                )  # fmt: skip
            )
    return reads


def best_by_platform(reads: Iterable[PostRead], field: str) -> dict[str, float]:
    """The best (largest) non-``None`` ``field`` (``"x72"`` or ``"outlier_x"``) of ``reads`` per platform, only the platforms
    that have one: a clip's values beside the binding one (``features['outlier_x']`` stays the better of its accounts')."""
    out: dict[str, float] = {}
    for r in reads:
        value = getattr(r, field)
        if value is not None and value > out.get(r.platform, float("-inf")):
            out[r.platform] = value
    return out


def _refresh_clip(store: Store, clip_id: str) -> tuple[float | None, bool]:
    """(the clip's outlier_x, whether it was written). ``(None, False)`` when no post has one yet."""
    with store.transaction():
        clip = store.get_clip(clip_id)
        if clip is None:
            return None, False
        values = [
            x
            for p in store.list_posts(clip_id=clip_id, status=PostStatus.posted)
            if (x := post_outlier_x(store, p)) is not None
        ]
        if not values:
            return None, False
        best = max(values)
        if clip.features.get("outlier_x") == best:
            return best, False
        store.update_clip(clip_id, features={**clip.features, "outlier_x": best})
        return best, True


def refresh_clip_outlier_x(store: Store, clip_id: str) -> float | None:
    """Set the clip's ``features['outlier_x']`` to the max over its posts; returns that value.

    ``None`` (and nothing written) when no post has an ``outlier_x`` yet. Other feature keys are kept.
    """
    return _refresh_clip(store, clip_id)[0]


# ---- parsing --------------------------------------------------------------------------------------


def _number(value: Any) -> float | None:
    """A finite, non-negative number from an int / float / numeric string; anything else ``None``."""
    if isinstance(value, bool):
        return None
    if isinstance(value, str):
        try:
            value = float(value.strip())
        except ValueError:
            return None
    if isinstance(value, (int, float)) and math.isfinite(value) and value >= 0:
        return float(value)
    return None


def _count(value: Any) -> int | None:
    n = _number(value)
    return int(n) if n is not None and n.is_integer() else None


def _series_total(data: Any) -> Any:
    """A Postiz metric's value: the scalar itself, or its data points combined per ``POSTIZ_SERIES_MODE``.

    ``"latest"``: the total of the point with the newest date (ties and missing dates: the later one
    in the list). ``"sum"``: the sum of every usable point. Points without a usable number are skipped;
    ``None`` when none is usable. Any other mode is a ``ValueError`` (a typo must not pick one silently).
    """
    if POSTIZ_SERIES_MODE not in ("latest", "sum"):
        raise ValueError(f"POSTIZ_SERIES_MODE must be 'latest' or 'sum', got {POSTIZ_SERIES_MODE!r}")
    if not isinstance(data, list):
        return data
    points: list[tuple[str, float, Any]] = []
    for point in data:
        total, date = (point.get("total", point.get("value")), str(point.get("date") or "")) \
            if isinstance(point, dict) else (point, "")  # fmt: skip
        if (n := _number(total)) is not None:
            points.append((date, n, total))
    if not points:
        return None
    if POSTIZ_SERIES_MODE == "sum":
        return sum(n for _, n, _ in points)
    best_date, _, best = points[0]
    for date, _, total in points[1:]:
        if date >= best_date:
            best_date, best = date, total
    return best


def _label(value: Any) -> str:
    return " ".join(str(value).replace("_", " ").replace("-", " ").lower().split())


def parse_post_analytics(payload: Any) -> dict[str, int | None]:
    """Snapshot fields from an ``analytics:post`` reply (see ``POSTIZ_METRIC_LABELS``).

    Only recognised metrics with a usable value appear in the result; an empty dict means the
    reply held nothing we know.
    """
    found: dict[str, Any] = {}
    if isinstance(payload, list):
        for item in payload:
            if isinstance(item, dict) and "label" in item:
                found.setdefault(_label(item["label"]), item.get("data"))
    elif isinstance(payload, dict):
        for key, value in payload.items():
            found.setdefault(_label(key), value)
    out: dict[str, int | None] = {}
    for field, labels in POSTIZ_METRIC_LABELS.items():
        for label in labels:
            if label in found and (n := _count(_series_total(found[label]))) is not None:
                out[field] = n
                break
    return out


# ---- pull -----------------------------------------------------------------------------------------


def _analytics(postiz_run: Callable[..., Any], executable: str, command: str, target_id: str, days: int) -> Any:
    """``postiz <command> <target_id> -d <days>`` (``analytics:post`` or ``analytics:platform``) and the JSON it prints."""
    argv = [executable, command, target_id, "-d", str(days)]
    try:
        proc = postiz_run(
            argv,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=ANALYTICS_TIMEOUT_S,
            stdin=subprocess.DEVNULL,
        )
    except subprocess.TimeoutExpired:
        raise AnalyticsError(f"postiz {command} timed out after {ANALYTICS_TIMEOUT_S} s") from None
    except OSError as e:
        raise AnalyticsError(f"could not run postiz: {e}") from None
    if proc.returncode != 0:
        raise AnalyticsError(f"postiz {command} failed (exit {proc.returncode}): {_tail(proc)}")
    try:
        return _json_in(proc.stdout or "")
    except ValueError:
        raise AnalyticsError(f"postiz {command} printed no JSON: {_tail(proc)}") from None


def _fetch(postiz_run: Callable[..., Any], executable: str, postiz_post_id: str) -> Any:
    return _analytics(postiz_run, executable, "analytics:post", postiz_post_id, ANALYTICS_DAYS)


def _pull_window(
    store: Store, postiz_run: Callable[..., Any], executable: str, post: Post, window: str,
    now: datetime, out: dict[str, Any],
) -> bool:  # fmt: skip
    """Pull ``window`` of ``post`` unless it holds a snapshot already. True when a snapshot was written."""
    where = {"post_id": post.id, "window": window}
    if _snapshots_in_window(store, post, window):
        out["already_pulled"].append(where)
        return False
    payload = _fetch(postiz_run, executable, post.platform_post_id)
    if isinstance(payload, dict) and payload.get("missing") is True:
        log.warning(
            "analytics missing for post %s (postiz id %s, %s): Postiz has no provider id for it; "
            "resolve with `postiz posts:missing` and `posts:connect`",
            post.id, post.platform_post_id, window,
        )  # fmt: skip
        out["missing"].append({**where, "platform_post_id": post.platform_post_id})
        return False
    values = parse_post_analytics(payload)
    if not values:
        log.warning("analytics for post %s (%s) held no known metric", post.id, window)
        out["empty"].append(where)
        return False
    store.add_snapshot(Snapshot(post_id=post.id, captured_at=now, **values))
    out["pulled"].append(where)
    return True


def _report_abandoned(store: Store, post: Post, age: timedelta, out: dict[str, Any]) -> None:
    """A post past ``ABANDON_AFTER``: list it under ``abandoned`` unless it holds its 7 d snapshot."""
    try:
        if _snapshots_in_window(store, post, "7d"):
            return  # measured: nothing was lost
    except Exception as e:  # noqa: BLE001 - one post must never stop the rest
        out["errors"].append({"post_id": post.id, "window": "7d", "error": _short(e)})
        return
    log.warning(
        "giving up on post %s (postiz id %s): aged %.1f d with no 7 d snapshot (deleted or never "
        "indexed); not pulled again",
        post.id, post.platform_post_id, age / timedelta(days=1),
    )  # fmt: skip
    out["abandoned"].append(
        {"post_id": post.id, "window": "7d", "age_days": round(age / timedelta(days=1), 1)}
    )


def pull(
    store: Store,
    postiz_run: Callable[..., Any],
    now: datetime,
    *,
    executable: str = "postiz",
) -> dict[str, Any]:
    """Pull every due (post, window); returns a JSON-friendly summary (see the module docstring).

    ``postiz_run`` is ``subprocess.run`` (a fake in tests). One post's failure never stops the rest:
    it is listed under ``errors`` and nothing is written for it. A post past ``ABANDON_AFTER`` with no
    7 d snapshot is listed under ``abandoned`` (for ``ABANDON_REPORT_FOR``) and is not fetched; one older
    than both is skipped without any query.
    """
    require_aware(now, "pull(now)")
    out: dict[str, Any] = {
        "pulled": [], "already_pulled": [], "missing": [], "empty": [], "abandoned": [], "errors": [],
        "outlier_x": [],
    }  # fmt: skip
    fresh: dict[str, None] = {}  # clips whose post just got a 7 d snapshot (insertion-ordered set)
    aged: dict[str, None] = {}  # clips with a post aged 7 d or more

    for post in store.list_posts(status=PostStatus.posted):
        if not post.platform_post_id:
            continue
        age = now - posted_at(post)
        window = window_at(age)
        if window is None or age > ABANDON_AFTER + ABANDON_REPORT_FOR:
            continue  # too young, or long past reporting: not even the idempotency lookup is spent
        if window == "7d" and age > ABANDON_AFTER:
            _report_abandoned(store, post, age, out)
            continue
        if window == "7d":
            aged[post.clip_id] = None
        try:
            wrote = _pull_window(store, postiz_run, executable, post, window, now, out)
        except Exception as e:  # noqa: BLE001 - one post must never stop the rest
            out["errors"].append({"post_id": post.id, "window": window, "error": _short(e)})
            continue
        if wrote and window == "7d":
            fresh[post.clip_id] = None

    try:
        unmeasured = {c.id for c in store.list_clips() if "outlier_x" not in c.features} if aged else set()
    except Exception as e:  # noqa: BLE001
        out["errors"].append({"error": _short(e)})
        unmeasured = set()
    for clip_id in [*fresh, *(c for c in aged if c in unmeasured and c not in fresh)]:
        try:
            value, written = _refresh_clip(store, clip_id)
        except Exception as e:  # noqa: BLE001
            out["errors"].append({"clip_id": clip_id, "error": _short(e)})
            continue
        if written:
            out["outlier_x"].append({"clip_id": clip_id, "outlier_x": value})
    return out


def _short(error: BaseException) -> str:
    text = f"{type(error).__name__}: {error}"
    return text if len(text) <= 500 else text[:500] + "…"


# ---- Instagram insights ---------------------------------------------------------------------------


def _first(row: dict[str, Any], keys: tuple[str, ...]) -> Any:
    return next((row[k] for k in keys if k in row and row[k] is not None), None)


def _row_id(row: dict[str, Any]) -> str | None:
    value = _first(row, IG_ID_KEYS)
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        return None
    return str(value) or None


def _ig_metrics(row: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for field, keys in IG_COUNT_KEYS.items():
        out[field] = _count(_first(row, keys))
    watch = _number(_first(row, IG_WATCH_TIME_S_KEYS))
    if watch is None and (ms := _number(_first(row, IG_WATCH_TIME_MS_KEYS))) is not None:
        watch = ms / 1000
    out["watch_time_s"] = watch
    out["skip_rate"] = _number(_first(row, IG_SKIP_RATE_KEYS))
    out["watched_pct"] = _number(_first(row, IG_WATCHED_PCT_KEYS))
    return out


def ingest_ig_insights(
    store: Store, rows: list[dict[str, Any]], *, now: datetime | None = None
) -> dict[str, Any]:
    """Write a snapshot per vidIQ ``instagram_owner_insights`` row that matches a post.

    A row matches on ``platform_post_id``. Unknown fields are ignored and nullable values stay
    ``None``. A row is not ingested when it matches no post (``unmatched``), holds no usable metric
    (``empty``) or repeats the post's latest snapshot (``unchanged``); ``skipped`` counts rows that
    are not objects or carry no id. Each clip whose post got a snapshot has its ``outlier_x``
    recomputed (``outlier_x`` lists the ones written).
    """
    now = now or datetime.now(timezone.utc)
    require_aware(now, "ingest_ig_insights(now)")
    out: dict[str, Any] = {
        "ingested": [], "unchanged": [], "unmatched": [], "empty": [], "skipped": 0, "outlier_x": [],
    }  # fmt: skip
    clips: dict[str, None] = {}  # clips of the posts that got a snapshot (insertion-ordered set)
    for row in rows:
        pid = _row_id(row) if isinstance(row, dict) else None
        if pid is None:
            out["skipped"] += 1
            continue
        posts = store.list_posts(platform_post_id=pid)
        if not posts:
            out["unmatched"].append(pid)
            continue
        values = _ig_metrics(row)
        for post in posts:
            where = {"post_id": post.id, "platform_post_id": pid}
            if all(v is None for v in values.values()):
                out["empty"].append(where)
                continue
            history = store.snapshots_for(post.id)
            if history and all(getattr(history[-1], f) == values[f] for f in _METRIC_FIELDS):
                out["unchanged"].append(where)
                continue
            store.add_snapshot(Snapshot(post_id=post.id, captured_at=now, **values))
            out["ingested"].append(where)
            clips[post.clip_id] = None
    for clip_id in clips:  # a new reading may be (or change) a 7-day figure
        value, written = _refresh_clip(store, clip_id)
        if written:
            out["outlier_x"].append({"clip_id": clip_id, "outlier_x": value})
    return out


# ---- the account's daily totals -------------------------------------------------------------------


def _day_key(value: Any) -> str | None:
    """A ``YYYY-MM-DD`` date from a data point's ``date`` (a plain date or an ISO timestamp: its first ten characters); else ``None``."""
    try:
        return date.fromisoformat(str(value or "").strip()[:10]).isoformat()
    except ValueError:
        return None


def _daily_counts(data: Any) -> dict[str, int]:
    """One metric's data points as ``{day: whole number}``. A point with no usable date or number is skipped; a day that repeats
    takes the later point."""
    out: dict[str, int] = {}
    for point in data if isinstance(data, list) else []:
        if not isinstance(point, dict):
            continue
        day, n = _day_key(point.get("date")), _count(point.get("total", point.get("value")))
        if day is not None and n is not None:
            out[day] = n
    return out


@dataclass(frozen=True)
class AccountReading:
    """What one ``analytics:platform`` reply holds: the daily series (``days``: ``{day: {field: n}}``, oldest day first) and the totals
    over the whole ``-d`` window (``window``: ``{field: n}``)."""

    days: dict[str, dict[str, int]] = dataclasses.field(default_factory=dict)
    window: dict[str, int] = dataclasses.field(default_factory=dict)

    @property
    def known(self) -> bool:
        """True when the reply held at least one metric we know."""
        return bool(self.days or self.window)


def parse_account_analytics(payload: Any) -> AccountReading:
    """The figures in a ``postiz analytics:platform`` reply, split by what they are: ``AccountReading(days={"2026-10-14": {"reach": 127}},
    window={"views": 334, "likes": 1, ...})``.

    The labels are mapped by ``ACCOUNT_METRIC_LABELS`` (case-insensitive; the totals may be strings). A label with two or more points is
    a **daily series** (``days``, one number per day); a label with exactly one point is a **window total** (``window``) over the ``-d``
    window, whatever the date that point carries (Instagram stamps it with the day it was read). Reach is the one field that is always
    daily: it is Instagram's time series, so even a single reach point is a day. A label a reply does not have, or one with no usable
    number, is simply absent: it is never filled with 0 (a real 0 is kept). A reply that is not a list of labelled metrics, or holds
    none we know, gives an empty reading.
    """
    found: dict[str, Any] = {}
    for item in payload if isinstance(payload, list) else []:
        if isinstance(item, dict) and "label" in item:
            found.setdefault(_label(item["label"]), item.get("data"))
    days: dict[str, dict[str, int]] = {}
    window: dict[str, int] = {}
    for field, labels in ACCOUNT_METRIC_LABELS.items():
        for label in labels:
            if counts := _daily_counts(found.get(label)):
                if len(counts) == 1 and field in ACCOUNT_WINDOW_FIELDS:
                    window[field] = next(iter(counts.values()))
                else:
                    for day, n in counts.items():
                        days.setdefault(day, {})[field] = n
                break
    return AccountReading(days={day: days[day] for day in sorted(days)}, window=window)


def _merge_window(old: Any, readings: dict[str, dict[str, int]], now: datetime) -> dict[str, Any]:
    """The row's ``window`` after a read: a handle's fields are overwritten by the new reading, a field it does not have keeps its
    earlier value, a handle not read this time stays as it was. ``read_at`` is the time of the read that changed something: an
    identical read returns ``old`` untouched, so the row is not rewritten just because the clock moved."""
    held = old.get("accounts") if isinstance(old, dict) else None
    accounts: dict[str, dict[str, int]] = {h: dict(v) for h, v in held.items() if isinstance(v, dict)} if isinstance(held, dict) else {}
    for handle, fields in readings.items():
        accounts[handle] = {**accounts.get(handle, {}), **fields}
    if isinstance(old, dict) and old.get("accounts") == accounts and old.get("days") == ACCOUNT_DAYS and isinstance(old.get("read_at"), str):
        return old
    return {"days": ACCOUNT_DAYS, "read_at": now.astimezone(LONDON).isoformat(timespec="seconds"), "accounts": accounts}


def _store_account_day(
    store: Store,
    row: Run | None,
    day: str,
    readings: dict[str, dict[str, int]],
    now: datetime,
    window: dict[str, dict[str, int]] | None = None,
) -> bool:
    """Write one London day into its ``account_daily`` row, which is created on the first read of the day and updated in place after
    that. ``readings`` are the day's daily figures (``{handle: fields}``, ``accounts``), ``window`` the 7-day totals read today
    (``{handle: fields}``, ``details.window``; only passed for today's row, and a past day's row keeps the window it had).

    A handle's fields are overwritten by the new reading, a field the new reading does not have keeps its earlier value, a handle not
    read this time stays as it was. **Cleaning:** the first version stored the window totals (views, likes, ...) under ``accounts``
    as if they were that day's; whenever a row is written, those fields are dropped from ``accounts`` before the new reading is merged
    (a handle left with nothing is dropped too). True when something was written (an identical reading writes nothing, so the row
    and its ``finished_at`` stay)."""
    old = row.details.get("accounts") if row is not None and isinstance(row.details, dict) else None
    accounts: dict[str, dict[str, int]] = {}
    for handle, fields in old.items() if isinstance(old, dict) else ():
        if isinstance(fields, dict) and (daily := {f: n for f, n in fields.items() if f not in ACCOUNT_WINDOW_FIELDS}):
            accounts[handle] = daily
    for handle, fields in readings.items():
        accounts[handle] = {**accounts.get(handle, {}), **fields}
    details: dict[str, Any] = {"day": day, "accounts": accounts}
    held_window = row.details.get("window") if row is not None and isinstance(row.details, dict) else None
    if window:
        details["window"] = _merge_window(held_window, window, now)
    elif isinstance(held_window, dict):
        details["window"] = held_window
    if row is not None and row.details == details:
        return False
    handles = list(dict.fromkeys([*accounts, *details.get("window", {}).get("accounts", {})]))
    summary = f"Account totals for {day}: " + ", ".join(handles)
    if row is not None:
        store.update_run(row.id, details=details, finished_at=now, summary=summary)
    else:
        d = date.fromisoformat(day)
        store.add_run(
            Run(
                kind=RunKind.account_daily, status=RunStatus.ok, started_at=datetime.combine(d, time(12, 0), tzinfo=LONDON),
                finished_at=now, summary=summary, details=details,
            )  # fmt: skip
        )
    return True


def pull_accounts(
    store: Store,
    postiz_run: Callable[..., Any],
    now: datetime,
    *,
    executable: str = "postiz",
) -> dict[str, Any]:
    """Read the figures of every live character's account that has a Postiz integration and store them, one ``account_daily`` run row
    per London day (owner 2026-10-15; no migration: ``runs`` has no constraint on ``kind``). Returns a JSON-friendly summary.

    Why. Instagram and Postiz give no numbers for a single Story, but ``postiz analytics:platform <integration id> -d 7`` gives the
    account's figures, Stories included. Beside the Reels' own views (the per-post pulls) the terminal's "Account per day" block
    shows what Stories and older posts add.

    **Two shapes in one reply** (verified live 2026-10-15, see ``parse_account_analytics``): Reach is a daily series, the other labels
    (Views, Likes, Comments, Shares, Saves, Replies) are ONE total over the 7-day window, dated the day it was read.

    Stored: the daily series as ``details = {"day": "2026-10-14", "accounts": {"@handle": {"reach": n}}}``, one row per data point's
    own date (taken as the London day); the window totals on the row of today (London) as ``details["window"] = {"days": 7,
    "read_at": "<ISO>", "accounts": {"@handle": {"views": n, "likes": n, "comments": n, "shares": n, "saves": n, "replies": n}}}``
    (the row is created for the window alone when the day has no daily figure yet). A number the platform did not report is absent,
    never 0. The row's ``started_at`` is noon London of its day (so rows sort by day), its ``finished_at`` the last time a read changed
    it. **Idempotent per (account, day):** a later read of the same day overwrites it (the window total grows through the day, a past
    day's reach may settle), an identical read writes nothing, and a day that is no longer in the reply is left as it was. A day after
    today (London) is never stored. A row written by the first version (window fields under ``accounts``) is corrected when it is next
    written.

    Summary keys: ``read`` (account, platform, days with a daily figure, window fields), ``skipped`` (a live character's account
    with no Postiz integration), ``empty`` (the reply held no known metric), ``postiz_errors`` (the reply failed: a warning, never an
    exception, and the other accounts are still read), ``written`` (day and the handles read, plus ``window`` on the row that got
    a window), ``unchanged`` (days that already held this reading) and ``write_errors`` (a day the database refused; the other days
    are still written).
    """
    require_aware(now, "pull_accounts(now)")
    today = now.astimezone(LONDON).date()
    out: dict[str, Any] = {
        "read": [], "skipped": [], "empty": [], "postiz_errors": [], "written": [], "unchanged": [], "write_errors": [],
    }  # fmt: skip
    live = {c.slug for c in store.characters() if c.status == "live"}
    by_day: dict[str, dict[str, dict[str, int]]] = {}  # day -> handle -> that day's numbers
    window: dict[str, dict[str, int]] = {}  # handle -> the 7-day totals read now
    for account in store.accounts():
        if account.character_slug not in live:
            continue
        if not account.postiz_integration_id:
            out["skipped"].append({"account": account.handle, "reason": "no Postiz integration"})
            continue
        try:
            payload = _analytics(postiz_run, executable, "analytics:platform", account.postiz_integration_id, ACCOUNT_DAYS)
        except Exception as e:  # noqa: BLE001 - a Postiz failure must never fail the job
            log.warning("account totals of %s not read: %s", account.handle, _short(e))
            out["postiz_errors"].append({"account": account.handle, "error": _short(e)})
            continue
        reading = parse_account_analytics(payload)
        days = {d: v for d, v in reading.days.items() if date.fromisoformat(d) <= today}
        if not days and not reading.window:
            log.warning("account totals of %s held no known metric", account.handle)
            out["empty"].append({"account": account.handle})
            continue
        out["read"].append(
            {"account": account.handle, "platform": account.platform.value, "days": len(days), "window": list(reading.window)}
        )
        for day, fields in days.items():
            by_day.setdefault(day, {})[account.handle] = fields
        if reading.window:
            window[account.handle] = reading.window

    if not by_day and not window:
        return out
    wanted = sorted({*by_day, *([today.isoformat()] if window else [])})
    try:
        rows: dict[str, Run] = {}
        for r in store.list_runs(kind=RunKind.account_daily):  # the oldest row of a day is its row
            if isinstance(r.details, dict) and isinstance(r.details.get("day"), str):
                rows.setdefault(r.details["day"], r)
    except Exception as e:  # noqa: BLE001
        out["write_errors"].append({"error": _short(e)})
        return out
    for day in wanted:
        with_window = window if day == today.isoformat() else None
        try:
            if _store_account_day(store, rows.get(day), day, by_day.get(day, {}), now, with_window):
                entry: dict[str, Any] = {"day": day, "accounts": list(dict.fromkeys([*by_day.get(day, {}), *(with_window or {})]))}
                if with_window:
                    entry["window"] = list(with_window)
                out["written"].append(entry)
            else:
                out["unchanged"].append(day)
        except Exception as e:  # noqa: BLE001 - one day's write must never stop the others
            out["write_errors"].append({"day": day, "error": _short(e)})
    return out


# ---- CLI ------------------------------------------------------------------------------------------

app = typer.Typer(
    help="Pull post analytics from Postiz, store the accounts' daily totals, ingest Instagram insights, compute outlier_x. Prints "
    "JSON; exit 1 = a pull or a write failed, exit 2 = something to fix.",
    no_args_is_help=True,
)


@app.command("pull")
def pull_command() -> None:
    """Pull analytics for every post that reached a window (1 h / 24 h / 72 h / 7 d) and holds no snapshot of it."""
    store = open_store()
    if not load().postiz_api_key:
        fail("POSTIZ_API_KEY is not set. Run through bin/studio (Keychain item cs-postiz-api-key).")
    if which("postiz") is None:
        fail("the postiz CLI is not on PATH (npm install -g postiz).")
    summary = pull(store, subprocess.run, now_london())
    emit(summary)
    if summary["errors"]:
        raise typer.Exit(1)


@app.command("accounts")
def accounts_command() -> None:
    """Store each live account's figures from Postiz (Stories included): the daily reach per London day, and the 7-day totals of
    views, likes, comments, shares, saves and replies on today's row.

    Prints one JSON summary. A Postiz failure is a warning in the summary (``postiz_errors``) and exit 0; exit 1 only when the
    database refused a write; exit 2 for a missing ``POSTIZ_API_KEY`` or ``postiz`` binary."""
    store = open_store()
    if not load().postiz_api_key:
        fail("POSTIZ_API_KEY is not set. Run through bin/studio (Keychain item cs-postiz-api-key).")
    if which("postiz") is None:
        fail("the postiz CLI is not on PATH (npm install -g postiz).")
    summary = pull_accounts(store, subprocess.run, now_london())
    emit(summary)
    if summary["write_errors"]:
        raise typer.Exit(1)


def _read_json(source: str) -> Any:
    """``source`` is inline JSON (starts with ``[`` or ``{``), ``-`` for stdin, or a file path."""
    stripped = source.strip()
    try:
        if stripped[:1] in ("[", "{"):
            text = stripped
        elif source == "-":
            text = sys.stdin.read()
        else:
            text = Path(source).expanduser().read_text(encoding="utf-8")
        return json.loads(text)
    except OSError as e:
        fail(f"cannot read {source!r}: {e.strerror or e}")
    except ValueError as e:
        fail(f"not valid JSON: {e}")


def _rows(payload: Any) -> list[dict[str, Any]]:
    """The reel rows: a list, or an object holding exactly one list of objects under any key."""
    if isinstance(payload, dict):
        lists = [v for v in payload.values() if isinstance(v, list) and any(isinstance(r, dict) for r in v)]
        if len(lists) != 1:
            fail("expected a JSON list of rows, or an object with one list of rows in it")
        payload = lists[0]
    if not isinstance(payload, list):
        fail("expected a JSON list of rows, or an object with one list of rows in it")
    return payload


@app.command("ingest-ig")
def ingest_ig_command(
    source: Annotated[
        str,
        typer.Argument(
            metavar="JSON", help="vidIQ instagram_owner_insights rows: a file, '-' for stdin, or inline JSON."
        ),
    ],
) -> None:
    """Write snapshots from vidIQ Instagram owner insights (matched on platform_post_id)."""
    rows = _rows(_read_json(source))
    emit(ingest_ig_insights(open_store(), rows))
