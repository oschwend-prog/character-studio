"""Viral Picks (favourites): links we want to copy, scored, approved, then produced.

A favourite is **not** a source: we never download it. It carries a breakdown that briefs a
synthetic driver (Recreate); a Drop-in happens only if the owner drops a clean file in
``inbox/`` (linked through ``source_id``). Two ways in:

* the owner pastes a link (``add_favorite``): ``origin='owner'``, approved on the spot,
* the daily scan files a candidate (``add_pick``): ``origin='scan'``, status ``new``, scored.

Status flow: ``new -> approved | skipped`` (``decide``), then ``analysed -> queued -> made`` as
the pick is produced (``mark_favorite``). ``next_favorites`` only ever hands out ``approved`` /
``analysed`` picks, oldest first, and ``mark_favorite`` refuses to move an unapproved pick into
production, so a ``new`` pick is never produced without approval.

Scoring (spec section 4.4b, weights v1): six sub-scores of 0-10, total = 0-100.
``virality`` and ``reach`` are computed here, the other four are judged by Claude and passed in::

    virality = clamp(log10(outlier_x) / 3 * 10, 0, 10)
    reach    = clamp(log10(max(views, 100_000) / 100_000) / log10(500) * 10, 0, 10)
    total    = round(10 * (.25 virality + .10 reach + .15 freshness + .20 fit
                           + .20 feasibility + .10 saturation))     # half up, not to even

``virality`` and ``reach`` are kept to 1 decimal and the total is computed from the stored
values, so it can be recomputed from what the terminal shows.

The standing rule (``auto_decision``, owner 2026-10-04: "approve for me"), checked in this order:
``hold`` when ``proposal['needs']`` names an untested capability (``multi_body``,
``talking_lane``); ``approve`` when total >= 80 and feasibility >= 7; ``skip`` when total < 65;
otherwise ``analyst`` (Claude decides and must write a reason). ``decide`` records every decision
as ``proposal['decision'] = {decision, by, reason}``; a hold also stores ``proposal['hold_reason']``
and leaves the status ``new`` so it is re-checked when the capability lands. ``add_pick`` and
``mark_favorite`` refuse any other ``needs`` value (``validate_needs``: an unknown token, a dict, an int, a
list with a bad item), and a malformed one that is stored anyway holds the pick (``_needs``) rather than
approving it or breaking ``fav list``.

**The pick card** (owner decisions 2026-10-05) rides in ``proposal`` (no migration; the terminal reads it through
``v_picks``, migrations 0008 and 0009): ``tier`` (``iconic`` "Broke the internet", ``viral_now`` "Viral now", ``rising``
"Up and coming", ``gallery`` "Ready to drop in"), ``theme`` (which of the character's scan themes it matched),
``posted_at`` (an ISO date or time, from the tool result: what the tier rule reads), ``thumbnail_url`` and
``preview_url`` (https URLs a tool already returned: vidIQ's thumbnail, a Genjutsu preset's thumbnail and
preview, ``https://i.ytimg.com/vi/<id>/hqdefault.jpg`` for a YouTube clip; never fetched or rehosted here) and
what the owner says in the Make-it sheet (``owner_props``, ``owner_music``). ``add_pick`` / ``mark_favorite``
refuse a malformed one (``validate_card``).

**The analyst's data** (owner request 2026-10-05, migration 0009; every field optional): ``velocity`` (views per day since
posting, worked out at filing time when the post date and the views are known: ``velocity_per_day``), ``engagement``
(``{likes, comments, shares, saves}`` from vidIQ when it returns them: ``engagement_rates`` gives the engagement and share
rate), ``saturation_count`` (similar outliers of the last 7 days: ``saturation_score`` turns it into the 0-10 saturation
sub-score), ``trait_matches`` (1-4 short phrases of the character's traits card the video matches), ``why`` (the analyst's
reasoning, one paragraph) and ``analysis`` (the local check of a fetched or attached clip: people, subject, camera,
watermark, overlay, children, best window, bpm). ``fav mark --analysis-file`` stores the last one.

**The tier rule** (``default_tier``, mirrored by the terminal's ``defaultTier``; the numbers live once, in
``config/scan.json`` ``tier_rules``, and ``TIER_RULES`` here is pinned equal to them by a test). A pick with an explicit
``tier`` keeps it. Otherwise, in this order: a Genjutsu gallery clip is ``gallery``; older than 180 days or 50M views or
more is ``iconic``; posted within 21 days with an outlier of 20 or more, or at 100K views a day or more, is ``viral_now``;
posted within 7 days with an outlier of 5 or more is ``rising``; anything else is ``viral_now`` up to 30 days old and
``iconic`` after that (an unknown post date is ``viral_now``). ``fav list`` prints ``tier``, ``tier_label`` and
``tier_derived`` next to the stored proposal, and ``age_days``, ``velocity_per_day``, ``engagement_rate`` and ``share_rate``.

CLI (``studio fav ...``) prints JSON on stdout. Exit codes: 0 ok, 2 anything the caller must fix,
4 ``fav decide`` found the pick needs an analyst decision (JSON on stdout says so).
"""

from __future__ import annotations

import dataclasses
import json
import math
import re
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Any, Literal, cast, get_args
from urllib.parse import urlsplit

import typer

from studio.cli_support import emit, fail, open_store, text_option
from studio.config import now_london
from studio.models import MUSIC_ARMS, Favorite, FavoriteOrigin, FavoriteStatus
from studio.store import Store

Decision = Literal["approve", "skip", "hold"]
DecidedBy = Literal["owner", "analyst", "rule"]
AutoDecision = Literal["approve", "analyst", "hold", "skip"]

WEIGHTS: dict[str, float] = {
    "virality": 0.25,
    "reach": 0.10,
    "freshness": 0.15,
    "fit": 0.20,
    "feasibility": 0.20,
    "saturation": 0.10,
}
APPROVE_MIN_TOTAL = 80
APPROVE_MIN_FEASIBILITY = 7
SKIP_BELOW_TOTAL = 65
HOLD_NEEDS = frozenset({"multi_body", "talking_lane"})

# Statuses a pick can only reach after approval; `new` and `skipped` ones may not enter them.
PRODUCTION_STATUSES = frozenset({"analysed", "queued", "made"})
APPROVED_OR_LATER = frozenset({"approved", "analysed", "queued", "made"})
# Fields `mark_favorite` may set next to the status (never url, scores, id or created_at).
MARKABLE_FIELDS = frozenset({"breakdown_md", "source_id", "clip_id", "note", "character_slug", "proposal"})

EXIT_NEEDS_ANALYST = 4


class NeedsAnalyst(ValueError):
    """The standing rule cannot decide this pick: Claude must (``decide(..., by='analyst')``)."""

    def __init__(self, favorite: Favorite) -> None:
        super().__init__(
            f"favourite {favorite.id} needs an analyst decision "
            f"(total {favorite.total_score}, feasibility {favorite.scores.get('feasibility')})"
        )
        self.favorite = favorite


# ---- URLs ------------------------------------------------------------------------------

_HOSTS = {
    "tiktok": frozenset({"tiktok.com", "www.tiktok.com", "m.tiktok.com"}),
    "instagram": frozenset({"instagram.com", "www.instagram.com"}),
    "youtube": frozenset({"youtube.com", "www.youtube.com", "m.youtube.com"}),
}
_SHORT_HOSTS = frozenset({"vm.tiktok.com", "vt.tiktok.com", "instagr.am", "youtu.be"})
_TIKTOK_VIDEO = re.compile(r"/@([\w.\-]+)/video/(\d+)")
_INSTAGRAM_REEL = re.compile(r"(?:/[\w.]+)?/reel/([\w\-]+)")
_YOUTUBE_SHORT = re.compile(r"/shorts/([\w\-]+)")
_YOUTUBE_ID = re.compile(r"[\w\-]{11}")

_FULL_URL_HELP = (
    "https://www.tiktok.com/@user/video/<id>, https://www.instagram.com/reel/<code>/ "
    "https://www.youtube.com/shorts/<id> or https://www.youtube.com/watch?v=<id>"
)


def parse_video_url(url: str) -> tuple[str, str]:
    """``(platform, canonical_url)`` of a full TikTok, Instagram Reel or YouTube Shorts link.

    Canonical = fixed ``https://www.<platform>`` host, the video path only (no query, fragment,
    user-prefix or trailing-slash variants), so the same video always dedupes to one URL.
    Short links (vm./vt.tiktok.com, tiktok.com/t/, instagr.am, youtu.be) are refused: they hide
    which video they are.
    """
    raw = (url or "").strip()
    if not raw:
        raise ValueError("url is required")
    parts = urlsplit(raw if "://" in raw else f"//{raw}")
    host = (parts.hostname or "").lower().rstrip(".")
    path = parts.path.rstrip("/")
    if parts.scheme in ("", "http", "https"):
        if host in _SHORT_HOSTS or (host in _HOSTS["tiktok"] and path.startswith("/t/")):
            raise ValueError(
                f"short links are not accepted: paste the full URL ({_FULL_URL_HELP}), got {raw!r}"
            )
        if host in _HOSTS["tiktok"] and (m := _TIKTOK_VIDEO.fullmatch(path)):
            return "tiktok", f"https://www.tiktok.com/@{m[1].lower()}/video/{m[2]}"
        if host in _HOSTS["instagram"] and (m := _INSTAGRAM_REEL.fullmatch(path)):
            return "instagram", f"https://www.instagram.com/reel/{m[1]}/"
        if host in _HOSTS["youtube"] and (m := _YOUTUBE_SHORT.fullmatch(path)):
            return "youtube", f"https://www.youtube.com/shorts/{m[1]}"
        if host in _HOSTS["youtube"] and path == "/watch":
            # a famous clip that lives as a regular video (an iconic music video or scene): the v= id is the video
            vid = dict(p.split("=", 1) for p in parts.query.split("&") if "=" in p).get("v", "")
            if _YOUTUBE_ID.fullmatch(vid):
                return "youtube", f"https://www.youtube.com/watch?v={vid}"
    raise ValueError(f"not a supported video URL: expected {_FULL_URL_HELP}, got {raw!r}")


# ---- Genjutsu gallery picks ---------------------------------------------------------------

GALLERY_PLATFORM = "higgsfield"
_PRESET_ID = re.compile(r"[\w.:\-]{1,120}")  # Genjutsu ids look like genjutsu:trending:<uuid>


def gallery_key(proposal: Mapping[str, Any], url: str | None) -> str:
    """The key of a Higgsfield Genjutsu gallery pick: ``higgsfield-preset:<preset id>``.

    A gallery clip has no TikTok / Instagram / YouTube page, so its ``proposal['preset_id']`` is its identity (one
    preset is one pick, deduped like a URL). A made-up URL is refused: the key is derived, never given.
    """
    preset = proposal.get("preset_id")
    if not isinstance(preset, str) or not _PRESET_ID.fullmatch(preset.strip()):
        raise ValueError(f"a gallery pick needs proposal.preset_id (letters, digits, - _ . :), got {preset!r}")
    key = f"higgsfield-preset:{preset.strip()}"
    if url and url != key:
        raise ValueError(f"a gallery pick is keyed by its preset ({key}), not by a URL: got {url!r:.60}")
    return key


# ---- helpers ---------------------------------------------------------------------------


def _one_of(value: Any, allowed: tuple[Any, ...], what: str) -> None:
    if value not in allowed:
        raise ValueError(f"{what} must be one of {allowed}, got {value!r}")


def _require_character(store: Store, slug: str | None) -> None:
    if slug is None or slug not in {c.slug for c in store.characters()}:
        raise ValueError(f"unknown character {slug!r}")


def _record(decision: Decision, by: DecidedBy, reason: str) -> dict[str, Any]:
    return {"decision": decision, "by": by, "reason": reason or None}


MALFORMED_NEEDS = "unreadable"


def _needs(proposal: dict[str, Any]) -> list[str]:
    """The untested capabilities a pick names. A value ``validate_needs`` would refuse (an old row, a hand
    edit) is never read as "needs nothing" and never raises: it counts as one unreadable need, so the
    standing rule holds the pick (fail closed)."""
    try:
        validate_needs(proposal)
    except ValueError:
        return [MALFORMED_NEEDS]
    needs = proposal.get("needs")
    items = [needs] if isinstance(needs, str) else list(needs or [])
    return [n for n in items if n in HOLD_NEEDS]


def validate_needs(proposal: dict[str, Any]) -> None:
    """Refuse a ``proposal['needs']`` that is not one of ``HOLD_NEEDS`` or a list of them.

    ``_needs`` ignores unknown tokens, so a misspelling (``multi-body``) would silently turn a hold
    into an approval. Checking at the door keeps the rule fail-closed. Absent, ``None`` and ``[]``
    all mean "needs nothing".
    """
    needs = proposal.get("needs")
    if needs is None:
        return
    allowed = ", ".join(sorted(HOLD_NEEDS))
    items = [needs] if isinstance(needs, str) else needs
    if not isinstance(items, (list, tuple)) or not all(isinstance(n, str) and n in HOLD_NEEDS for n in items):
        raise ValueError(f"proposal.needs must be one of or a list of {{{allowed}}}, got {needs!r}")


# ---- the pick card: tier, theme, thumbnails, owner choices -----------------------------------------------

TIERS = ("iconic", "viral_now", "rising", "gallery")  # the order the terminal groups them in
TIER_LABELS = {
    "iconic": "Broke the internet",
    "viral_now": "Viral now",
    "rising": "Up and coming",
    "gallery": "Ready to drop in",
}
# The tier rule's numbers: config/scan.json `tier_rules` is the one place they are written (the terminal's scanner panel
# reads it); tests/test_analyst.py pins this dict equal to it and the terminal's own test pins scanConfig.ts equal to it.
TIER_RULES: dict[str, int] = {
    "iconic_min_age_days": 180,  # strictly older than this
    "iconic_min_views": 50_000_000,
    "viral_now_max_age_days": 21,
    "viral_now_min_outlier": 20,
    "viral_now_min_velocity_per_day": 100_000,
    "rising_max_age_days": 7,
    "rising_min_outlier": 5,
    "fallback_viral_now_max_age_days": 30,  # viral now up to this age, iconic after it
    "velocity_min_age_days": 1,  # a clip posted hours ago is divided by one day, not by a fraction
}
SATURATION_STEPS = ((8, 3.0), (4, 5.0), (1, 8.0), (0, 10.0))  # (similar outliers or more, score)
THEME_MAX_CHARS = 60
URL_MAX_CHARS = 2048
PREVIEW_SUFFIXES = (".mp4", ".webm", ".mov", ".m4v")
OWNER_PROPS_MAX = 3
OWNER_PROP_MAX_CHARS = 40
TRAIT_MATCHES_MAX = 4
TRAIT_MATCH_MAX_CHARS = 60
WHY_MAX_CHARS = 600
ENGAGEMENT_KEYS = ("likes", "comments", "shares", "saves")
CAMERAS = ("static", "handheld", "moving")
ANALYSIS_REQUIRED = ("people_count", "camera", "watermark", "overlay", "minors")
ANALYSIS_KEYS = (*ANALYSIS_REQUIRED, "main_subject", "best_window", "bpm", "notes")
ANALYSIS_SUBJECT_MAX_CHARS = 80
ANALYSIS_NOTES_MAX_CHARS = 500
BPM_RANGE = (30.0, 300.0)


def is_gallery(proposal: Mapping[str, Any]) -> bool:
    """A Higgsfield Genjutsu gallery clip: its source kind or a preset id says so."""
    preset = proposal.get("preset_id")
    return proposal.get("source_kind") == "higgsfield_library" or (isinstance(preset, str) and bool(preset.strip()))


def _moment(raw: Any) -> datetime | None:
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        moment = datetime.fromisoformat(raw.strip())
    except ValueError:
        return None
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=timezone.utc)


def posted_age_days(proposal: Mapping[str, Any], now: datetime) -> float | None:
    """Days since the video was posted: ``proposal['posted_at']`` (ISO), else the scan's ``age_days``; None if unknown."""
    if (moment := _moment(proposal.get("posted_at"))) is not None:
        return (now - moment).total_seconds() / 86400
    age = proposal.get("age_days")
    if (n := _finite(age)) is not None and n >= 0:
        return n
    return None


def _finite(value: Any) -> float | None:
    """``value`` as a finite float, or None (a bool, a string, NaN and infinity are not numbers here)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    return float(value)


def velocity_per_day(views: Any, age_days: Any) -> int | None:
    """Views per day since posting, to the whole view; None when the views or the age are unknown.

    A clip posted a few hours ago is divided by one day (``velocity_min_age_days``), never by a fraction of one: 90K
    views in 12 hours is 90K a day, not 180K.
    """
    v, age = _finite(views), _finite(age_days)
    if v is None or age is None or v < 0:
        return None
    return math.floor(v / max(age, TIER_RULES["velocity_min_age_days"]) + 0.5)  # half up, like the terminal


def _stored_velocity(proposal: Mapping[str, Any]) -> float | None:
    v = _finite(proposal.get("velocity"))
    return v if v is not None and v >= 0 else None


def engagement_rates(engagement: Any, views: Any) -> dict[str, float | None] | None:
    """``{engagement_rate, share_rate}`` of a pick, or None when there is nothing to divide.

    ``engagement_rate`` = (likes + comments + shares + saves) / views over the counts vidIQ returned (a platform that
    hides one counts the others); ``share_rate`` = shares / views, None when the shares are not known. None without a
    view count or without any engagement count.
    """
    v = _finite(views)
    if v is None or v <= 0 or not isinstance(engagement, Mapping):
        return None
    counts = {k: n for k in ENGAGEMENT_KEYS if (n := _finite(engagement.get(k))) is not None and n >= 0}
    if not counts:
        return None
    return {
        "engagement_rate": sum(counts.values()) / v,
        "share_rate": counts["shares"] / v if "shares" in counts else None,
    }


def saturation_score(count: Any) -> float:
    """The 0-10 saturation sub-score from the number of similar outliers found in the last 7 days.

    8 or more copies is 3, 4-7 is 5, 1-3 is 8, none is 10. ``ValueError`` for anything that is not a whole number of 0 or more.
    """
    if isinstance(count, bool) or not isinstance(count, int) or count < 0:
        raise ValueError(f"saturation_count must be a whole number of 0 or more, got {count!r}")
    return next(score for floor, score in SATURATION_STEPS if count >= floor)


def default_tier(proposal: Mapping[str, Any], outlier_x: float | None, now: datetime, views: int | None = None) -> str:
    """The tier of a pick the analyst did not tier (mirrored by ``defaultTier`` in terminal/src/lib/rules.ts).

    In this order (numbers: ``TIER_RULES``): a gallery clip is ``gallery``; older than 180 days or ``views`` of 50M or more
    is ``iconic``; posted within 21 days with ``outlier_x`` of 20 or more, or at 100K views a day or more (the stored
    ``proposal['velocity']``, else ``views`` / age), is ``viral_now``; posted within 7 days with an outlier of 5 or more is
    ``rising``; anything else is ``viral_now`` up to 30 days old and ``iconic`` after (an unknown age: ``viral_now``).
    """
    if is_gallery(proposal):
        return "gallery"
    r = TIER_RULES
    age = posted_age_days(proposal, now)
    x, seen = _finite(outlier_x), _finite(views)
    if (age is not None and age > r["iconic_min_age_days"]) or (seen is not None and seen >= r["iconic_min_views"]):
        return "iconic"
    if age is None:
        return "viral_now"
    velocity = _stored_velocity(proposal)
    if velocity is None:
        velocity = velocity_per_day(seen, age)
    if age <= r["viral_now_max_age_days"] and (
        (x is not None and x >= r["viral_now_min_outlier"])
        or (velocity is not None and velocity >= r["viral_now_min_velocity_per_day"])
    ):
        return "viral_now"
    if age <= r["rising_max_age_days"] and x is not None and x >= r["rising_min_outlier"]:
        return "rising"
    return "viral_now" if age <= r["fallback_viral_now_max_age_days"] else "iconic"


def _https_url(value: Any, key: str, suffixes: tuple[str, ...] | None = None) -> None:
    if not isinstance(value, str) or not value or len(value) > URL_MAX_CHARS or re.search(r"\s", value):
        raise ValueError(f"proposal.{key} must be an https URL (no spaces, at most {URL_MAX_CHARS} characters), got {value!r:.80}")
    parts = urlsplit(value)
    if parts.scheme != "https" or not parts.hostname:
        raise ValueError(f"proposal.{key} must be an https URL, got {value!r:.80}")
    if suffixes is not None and not parts.path.lower().endswith(suffixes):
        raise ValueError(f"proposal.{key} must be an https video URL ending {'/'.join(suffixes)}, got {value!r:.80}")


def validate_card(proposal: Mapping[str, Any]) -> None:
    """Refuse a malformed pick-card field of ``proposal`` (see the module doc). Absent and ``None`` are fine.

    The URLs are only ever stored, never fetched: they must be the https URL a tool returned.
    """
    if (tier := proposal.get("tier")) is not None and tier not in TIERS:
        raise ValueError(f"proposal.tier must be one of {', '.join(TIERS)}, got {tier!r}")
    if (theme := proposal.get("theme")) is not None and not (
        isinstance(theme, str) and 0 < len(theme.strip()) <= THEME_MAX_CHARS
    ):
        raise ValueError(f"proposal.theme must be a short label (1-{THEME_MAX_CHARS} characters), got {theme!r:.80}")
    if (raw := proposal.get("posted_at")) is not None and _moment(raw) is None:
        raise ValueError(f"proposal.posted_at must be an ISO date or time (2026-10-01), got {raw!r:.40}")
    if (url := proposal.get("thumbnail_url")) is not None:
        _https_url(url, "thumbnail_url")
    if (url := proposal.get("preview_url")) is not None:
        _https_url(url, "preview_url", PREVIEW_SUFFIXES)
    if (music := proposal.get("owner_music")) is not None and music not in MUSIC_ARMS:
        raise ValueError(f"proposal.owner_music must be one of {', '.join(MUSIC_ARMS)}, got {music!r}")
    if (props := proposal.get("owner_props")) is not None:
        ok = (
            isinstance(props, list)
            and len(props) <= OWNER_PROPS_MAX
            and all(isinstance(p, str) and 0 < len(p.strip()) <= OWNER_PROP_MAX_CHARS for p in props)
        )
        if not ok:
            raise ValueError(
                f"proposal.owner_props must be a list of at most {OWNER_PROPS_MAX} items of 1-{OWNER_PROP_MAX_CHARS} "
                f"characters, got {props!r:.80}"
            )
    _validate_analyst_fields(proposal)


def _whole(value: Any) -> bool:
    n = _finite(value)
    return n is not None and n >= 0 and n == int(n) and not isinstance(value, bool)


def _short_text(value: Any, limit: int) -> bool:
    return isinstance(value, str) and 0 < len(value.strip()) and len(value) <= limit


def _validate_analyst_fields(proposal: Mapping[str, Any]) -> None:
    """The analyst's data of a pick (see the module doc): each optional, each refused with its own sentence."""
    if (v := proposal.get("velocity")) is not None and not ((n := _finite(v)) is not None and n >= 0):
        raise ValueError(f"proposal.velocity must be views per day, a number of 0 or more, got {v!r:.40}")
    if (e := proposal.get("engagement")) is not None:
        ok = (
            isinstance(e, Mapping)
            and bool(e)
            and set(e) <= set(ENGAGEMENT_KEYS)
            and all(_whole(n) for n in e.values())
        )
        if not ok:
            raise ValueError(
                f"proposal.engagement must be counts of {', '.join(ENGAGEMENT_KEYS)} (whole numbers of 0 or more, at "
                f"least one), got {e!r:.80}"
            )
    if (c := proposal.get("saturation_count")) is not None and not (isinstance(c, int) and not isinstance(c, bool) and c >= 0):
        raise ValueError(f"proposal.saturation_count must be a whole number of 0 or more, got {c!r:.40}")
    if (t := proposal.get("trait_matches")) is not None:
        ok = (
            isinstance(t, list)
            and 1 <= len(t) <= TRAIT_MATCHES_MAX
            and all(_short_text(m, TRAIT_MATCH_MAX_CHARS) for m in t)
        )
        if not ok:
            raise ValueError(
                f"proposal.trait_matches must be a list of 1-{TRAIT_MATCHES_MAX} short phrases (1-{TRAIT_MATCH_MAX_CHARS} "
                f"characters) from the character's traits card, got {t!r:.80}"
            )
    if (w := proposal.get("why")) is not None and not _short_text(w, WHY_MAX_CHARS):
        raise ValueError(f"proposal.why must be a short paragraph (1-{WHY_MAX_CHARS} characters), got {w!r:.80}")
    if (a := proposal.get("analysis")) is not None:
        validate_analysis(a)


def validate_analysis(analysis: Any) -> None:
    """Refuse a malformed ``proposal['analysis']``, the check of a fetched or attached clip.

    Required: ``people_count`` (whole number), ``camera`` (static, handheld or moving) and the three yes/no flags
    ``watermark``, ``overlay`` and ``minors`` (a child anywhere in the clip). Optional: ``main_subject``, ``best_window``
    (``{start_s, end_s}``, 0 <= start < end, seconds), ``bpm`` (30-300 or null) and ``notes``. An unknown key is refused,
    so a typo is never stored as if it were data.
    """
    what = "proposal.analysis"
    if not isinstance(analysis, Mapping) or not analysis:
        raise ValueError(f"{what} must be an object with {', '.join(ANALYSIS_REQUIRED)}, got {analysis!r:.80}")
    if unknown := sorted(set(analysis) - set(ANALYSIS_KEYS)):
        raise ValueError(f"{what} has unknown key(s) {unknown}; allowed: {', '.join(ANALYSIS_KEYS)}")
    if missing := [k for k in ANALYSIS_REQUIRED if k not in analysis]:
        raise ValueError(f"{what} needs {', '.join(missing)}")
    if not _whole(analysis["people_count"]):
        raise ValueError(f"{what}.people_count must be a whole number of 0 or more, got {analysis['people_count']!r:.40}")
    if analysis["camera"] not in CAMERAS:
        raise ValueError(f"{what}.camera must be one of {', '.join(CAMERAS)}, got {analysis['camera']!r:.40}")
    for flag in ("watermark", "overlay", "minors"):
        if not isinstance(analysis[flag], bool):
            raise ValueError(f"{what}.{flag} must be true or false, got {analysis[flag]!r:.40}")
    if "main_subject" in analysis and not _short_text(analysis["main_subject"], ANALYSIS_SUBJECT_MAX_CHARS):
        raise ValueError(f"{what}.main_subject must be 1-{ANALYSIS_SUBJECT_MAX_CHARS} characters, got {analysis['main_subject']!r:.80}")
    if "notes" in analysis and not _short_text(analysis["notes"], ANALYSIS_NOTES_MAX_CHARS):
        raise ValueError(f"{what}.notes must be 1-{ANALYSIS_NOTES_MAX_CHARS} characters, got {analysis['notes']!r:.80}")
    if (bpm := analysis.get("bpm")) is not None and not (
        (n := _finite(bpm)) is not None and BPM_RANGE[0] <= n <= BPM_RANGE[1]
    ):
        raise ValueError(f"{what}.bpm must be {BPM_RANGE[0]:g}-{BPM_RANGE[1]:g} or null, got {bpm!r:.40}")
    if (window := analysis.get("best_window")) is not None:
        start = end = None
        if isinstance(window, Mapping) and set(window) == {"start_s", "end_s"}:
            start, end = _finite(window["start_s"]), _finite(window["end_s"])
        if start is None or end is None or not 0 <= start < end:
            raise ValueError(f"{what}.best_window must be {{start_s, end_s}} in seconds with 0 <= start < end, got {window!r:.80}")


# ---- scoring ---------------------------------------------------------------------------


def _clamp(x: float) -> float:
    return max(0.0, min(10.0, x))


def score_pick(
    outlier_x: float | None,
    views: int | None,
    freshness: float,
    fit: float,
    feasibility: float,
    saturation: float,
    *,
    iconic: bool = False,
) -> dict[str, float]:
    """The six sub-scores (0-10) and ``total`` (0-100, whole number) of a pick, spec weights v1.

    ``iconic`` ("Broke the internet": a famous moment everyone knows, owner rule 2026-10-05) scores full virality:
    beating its uploader's median says nothing about a clip that is famous in its own right.

    ``virality`` and ``reach`` are returned to 1 decimal and ``total`` is computed from the
    returned values. ``outlier_x`` and ``views`` are scored here (an unknown or sub-1x outlier scores 0 virality,
    views under 100K score 0 reach); the other four are judged and must be within 0-10.
    """
    judged = {"freshness": freshness, "fit": fit, "feasibility": feasibility, "saturation": saturation}
    for name, value in judged.items():
        if not 0 <= value <= 10:  # also false for NaN
            raise ValueError(f"{name} must be between 0 and 10, got {value!r}")
    virality = _clamp(math.log10(outlier_x) / 3 * 10) if outlier_x and outlier_x > 0 else 0.0
    if iconic:
        virality = 10.0
    reach = _clamp(math.log10(max(views or 0, 100_000) / 100_000) / math.log10(500) * 10)
    # Computed scores are kept to 1 decimal, and the total is taken from those stored values, so
    # anyone can recompute it from what the terminal shows (this reproduces every total of the
    # batch-1 table; unrounded, B2 would be 87 instead of 88).
    parts = {"virality": round(virality, 1), "reach": round(reach, 1), **judged}
    weighted = sum(WEIGHTS[name] * parts[name] for name in WEIGHTS)
    # Half up (x.5 -> x+1): round() goes to even, so 64.5 would skip while 65.5 would not.
    # The epsilon absorbs float noise (0.15 * 3 * 10 = 4.499999999999999).
    total = math.floor(10 * weighted + 0.5 + 1e-9)
    return {**parts, "total": total}


# ---- adding ----------------------------------------------------------------------------


def add_favorite(store: Store, url: str, character_slug: str, note: str | None = None) -> Favorite:
    """The owner's own favourite: approved on the spot (they asked for it), never downloaded.

    A link already in the list is not added twice: if it is still ``new`` or ``skipped`` the owner
    just asked for it, so it becomes ``approved`` (and takes the note); anything further along is
    returned untouched.
    """
    platform, canonical = parse_video_url(url)
    _require_character(store, character_slug)
    note = (note or "").strip() or None
    existing = store.list_favorites(url=canonical)
    if existing:
        f = existing[0]
        if f.status in ("new", "skipped"):
            f = decide(store, f.id, "approve", "owner's own favourite", "owner")
            if note:
                f = store.update_favorite(f.id, note=note)
        return f
    return store.add_favorite(
        Favorite(
            url=canonical,
            platform=platform,
            origin="owner",
            character_slug=character_slug,
            proposal={"decision": _record("approve", "owner", "owner's own favourite")},
            note=note,
            status="approved",
        )
    )


def _add_pick(
    store: Store,
    url: str,
    platform: str,
    creator_handle: str | None,
    views: int | None,
    outlier_x: float | None,
    character_slug: str | None,
    proposal: dict[str, Any],
    origin: FavoriteOrigin,
    judged: dict[str, float],
) -> tuple[Favorite, bool]:
    """``(favourite, created)``: ``created`` is False when the URL was already in the list."""
    _one_of(origin, get_args(FavoriteOrigin), "origin")
    if platform == GALLERY_PLATFORM:
        found_platform, canonical = GALLERY_PLATFORM, gallery_key(proposal, url)
    else:
        found_platform, canonical = parse_video_url(url)
        if platform != found_platform:
            raise ValueError(f"platform {platform!r} does not match the URL ({found_platform})")
    if character_slug is not None:  # None = not matched to a seeded character yet
        _require_character(store, character_slug)
    validate_needs(proposal)
    validate_card(proposal)
    scores = score_pick(outlier_x, views, **judged, iconic=proposal.get("tier") == "iconic")
    existing = store.list_favorites(url=canonical)
    if existing:
        return existing[0], False
    total = scores.pop("total")
    proposal = dict(proposal)
    if proposal.get("velocity") is None and (v := velocity_per_day(views, posted_age_days(proposal, now_london()))) is not None:
        proposal["velocity"] = v  # views per day since posting, as of the day it was filed
    if origin == "owner":
        proposal["decision"] = _record("approve", "owner", "owner's own link")
    f = store.add_favorite(
        Favorite(
            url=canonical,
            platform=found_platform,
            creator_handle=creator_handle,
            views=views,
            outlier_x=outlier_x,
            origin=origin,
            character_slug=character_slug,
            proposal=proposal,
            scores=scores,
            total_score=float(total),
            status="approved" if origin == "owner" else "new",
        )
    )
    return f, True


def add_pick(
    store: Store,
    url: str,
    platform: str,
    creator_handle: str | None,
    views: int | None,
    outlier_x: float | None,
    character_slug: str | None,
    proposal: dict[str, Any],
    origin: FavoriteOrigin = "scan",
    *,
    freshness: float,
    fit: float,
    feasibility: float,
    saturation: float,
) -> Favorite:
    """File a scored Viral Pick (status ``new``; owner-origin picks arrive ``approved``).

    The four judged sub-scores (0-10, rubric in the spec) come in as keyword arguments;
    virality and reach are computed from ``outlier_x`` and ``views``. A URL already in the list
    returns the existing row untouched, so a rescan never duplicates or rescores a pick.
    ``proposal['needs']`` must be ``multi_body`` / ``talking_lane`` (or a list of them), else
    ``ValueError``. ``character_slug=None`` files a pick not matched to a character yet (the owner
    assigns one in the terminal); an unknown slug is still refused.
    """
    judged = {"freshness": freshness, "fit": fit, "feasibility": feasibility, "saturation": saturation}
    f, _ = _add_pick(
        store, url, platform, creator_handle, views, outlier_x, character_slug, proposal, origin, judged
    )
    return f


# ---- listing and rule ------------------------------------------------------------------


def list_picks(store: Store, status: str | None = "new", character: str | None = None) -> list[Favorite]:
    """Favourites with this status (``None`` = any; ``character`` limits to one), highest total first, unscored last."""
    if status is not None:
        _one_of(status, get_args(FavoriteStatus), "status")
    if character is not None:
        _require_character(store, character)
    filters: dict[str, Any] = {} if status is None else {"status": status}
    if character is not None:
        filters["character_slug"] = character
    rows = store.list_favorites(**filters)
    rows.sort(key=lambda f: (f.total_score is None, -(f.total_score or 0.0)))  # stable: older first
    return rows


def auto_decision(pick: Favorite) -> AutoDecision:
    """The standing rule: hold, else approve, else skip, else leave it to the analyst."""
    if _needs(pick.proposal):
        return "hold"
    total = pick.total_score
    feasibility = pick.scores.get("feasibility")
    if (
        total is not None
        and feasibility is not None
        and total >= APPROVE_MIN_TOTAL
        and feasibility >= APPROVE_MIN_FEASIBILITY
    ):
        return "approve"
    if total is not None and total < SKIP_BELOW_TOTAL:
        return "skip"
    return "analyst"


def decide(store: Store, id: str, decision: Decision, reason: str, by: DecidedBy) -> Favorite:
    """Record a decision on a pick.

    ``approve`` -> ``approved`` (a pick already ``analysed`` keeps its status), ``skip`` ->
    ``skipped``, ``hold`` leaves the status ``new`` and stores ``proposal['hold_reason']``.
    An analyst must give a non-empty reason and a final choice (approve or skip); a hold needs a
    reason too. Picks already ``queued`` or ``made`` are past deciding.
    """
    _one_of(decision, get_args(Decision), "decision")
    _one_of(by, get_args(DecidedBy), "by")
    reason = reason.strip()
    if by == "analyst" and not reason:
        raise ValueError("an analyst decision needs a one-line reason")
    if by == "analyst" and decision == "hold":
        raise ValueError("an analyst makes the final choice: approve or skip (hold is the rule's call)")
    if decision == "hold" and not reason:
        raise ValueError("a hold needs a reason (it is shown until the capability lands)")
    f = store.get_favorite(id)
    if f is None:
        raise KeyError(id)
    if f.status in ("queued", "made"):
        raise ValueError(f"favourite {id} is already {f.status}: too late to decide")
    if decision == "hold" and f.status != "new":
        raise ValueError(f"only new picks can be put on hold, this one is {f.status}")
    proposal = {k: v for k, v in f.proposal.items() if k != "hold_reason"}
    proposal["decision"] = _record(decision, by, reason)
    if decision == "hold":
        proposal["hold_reason"] = reason
        status = f.status
    elif decision == "approve":
        status = f.status if f.status in ("approved", "analysed") else "approved"
    else:
        status = "skipped"
    return store.update_favorite(id, status=status, proposal=proposal)


def _g(x: float | None) -> str:
    return "?" if x is None else f"{x:g}"


def apply_rule(store: Store, id: str) -> Favorite:
    """Decide a ``new`` pick by the standing rule (``by='rule'``), or raise ``NeedsAnalyst``."""
    f = store.get_favorite(id)
    if f is None:
        raise KeyError(id)
    if f.status != "new":
        raise ValueError(f"favourite {id} is already {f.status}: the rule only decides new picks")
    outcome = auto_decision(f)
    if outcome == "analyst":
        raise NeedsAnalyst(f)
    total, feasibility = f.total_score, f.scores.get("feasibility")
    if outcome == "approve":
        reason = (
            f"rule: total {_g(total)} >= {APPROVE_MIN_TOTAL} "
            f"and feasibility {_g(feasibility)} >= {APPROVE_MIN_FEASIBILITY}"
        )
    elif outcome == "hold":
        reason = f"rule: needs {', '.join(_needs(f.proposal))} (capability not tested yet)"
    else:
        reason = f"rule: total {_g(total)} < {SKIP_BELOW_TOTAL}"
    return decide(store, id, outcome, reason, "rule")


# ---- production ------------------------------------------------------------------------


def next_favorites(store: Store, limit: int, character: str | None = None) -> list[Favorite]:
    """Up to ``limit`` picks ready to produce: ``approved`` or ``analysed``, oldest first.

    ``character`` limits the queue to that character's picks, so a character is never starved by
    older picks of another (the daily run asks once per due clip).
    """
    if limit < 0:
        raise ValueError(f"limit must be 0 or more, got {limit!r}")
    if character is not None:
        _require_character(store, character)
    extra = {} if character is None else {"character_slug": character}
    ready = [f for status in ("approved", "analysed") for f in store.list_favorites(status=status, **extra)]
    ready.sort(key=lambda f: f.created_at.timestamp() if f.created_at else 0.0)
    return ready[:limit]


def content_id(url: str) -> str:
    """The platform id of a canonical favourite URL: TikTok video id, Instagram reel shortcode, Shorts id."""
    return url.rstrip("/").rsplit("/", 1)[-1]


def seen_ids(store: Store, limit: int) -> list[str]:
    """Platform ids of the ``limit`` newest favourites of any status, newest first.

    Feeds vidIQ's ``excludeContentIds`` (which takes at most 100) so a scan never resurfaces a video
    that was already picked, produced or skipped. Each video is named once, however many rows it has.
    """
    if limit < 0:
        raise ValueError(f"limit must be 0 or more, got {limit!r}")
    rows = store.list_favorites()
    rows.sort(key=lambda f: f.created_at.timestamp() if f.created_at else 0.0, reverse=True)
    # one video can be two rows (the terminal's "Both" files a sibling for the other character): name it once
    ids = list(dict.fromkeys(content_id(f.url) for f in rows if f.platform != GALLERY_PLATFORM))  # no platform id to exclude
    return ids[:limit]


def mark_favorite(store: Store, id: str, status: str, **fields: Any) -> Favorite:
    """Move a pick to ``status`` and set any of ``MARKABLE_FIELDS`` alongside.

    ``analysed`` / ``queued`` / ``made`` need the pick to have been approved first.
    """
    _one_of(status, get_args(FavoriteStatus), "status")
    unknown = sorted(set(fields) - MARKABLE_FIELDS)
    if unknown:
        raise TypeError(f"mark_favorite: unknown field(s) {unknown}; allowed: {sorted(MARKABLE_FIELDS)}")
    if fields.get("character_slug") is not None:
        _require_character(store, fields["character_slug"])
    if fields.get("proposal") is not None:
        validate_needs(fields["proposal"])  # the same door as add_pick: needs can never be written malformed
        validate_card(fields["proposal"])
    if status in PRODUCTION_STATUSES:
        f = store.get_favorite(id)
        if f is None:
            raise KeyError(id)
        if f.status not in APPROVED_OR_LATER:
            raise ValueError(
                f"favourite {id} is {f.status}: it must be approved before it can be {status}"
            )
    return store.update_favorite(id, status=status, **fields)


# ---- CLI -----------------------------------------------------------------------------------

app = typer.Typer(
    help="Viral Picks: add favourites, file scored picks, decide, track production. "
    "Prints JSON; exit 2 = caller error, 4 = needs an analyst decision.",
    no_args_is_help=True,
)


def _fav_json(f: Favorite, **extra: Any) -> dict[str, Any]:
    out = dataclasses.asdict(f)
    if f.status == "new":
        out["auto_decision"] = auto_decision(f)
    now = now_london()
    stored = f.proposal.get("tier")
    tier = stored if stored in TIERS else default_tier(f.proposal, f.outlier_x, now, views=f.views)
    out.update(tier=tier, tier_label=TIER_LABELS[tier], tier_derived=stored not in TIERS)
    age = posted_age_days(f.proposal, now)
    rates = engagement_rates(f.proposal.get("engagement"), f.views) or {}
    velocity = _stored_velocity(f.proposal)
    out.update(
        age_days=None if age is None else round(age, 1),
        velocity_per_day=math.floor(velocity + 0.5) if velocity is not None else velocity_per_day(f.views, age),
        engagement_rate=rates.get("engagement_rate"),
        share_rate=rates.get("share_rate"),
    )
    return {**out, **extra}


@app.command("add")
def add_command(
    url: Annotated[str, typer.Argument(help="Full TikTok / Instagram Reel / YouTube Shorts URL.")],
    character: Annotated[str, typer.Option(help="Character slug that should make it.")],
    note: Annotated[str | None, typer.Option(help="Why you like it.")] = None,
) -> None:
    """Add one of the owner's own favourites (approved at once; never downloaded)."""
    store = open_store()
    try:
        f = add_favorite(store, url, character, note)
    except ValueError as e:
        fail(str(e))
    emit(_fav_json(f))


def _from_file_or_flag(proposal: dict[str, Any], key: str, flag: str | None) -> str | None:
    """``proposal[key]`` (removed from the proposal: it is the pick's identity) or the ``--<key>`` flag.

    Text that came from a creator or a tool belongs in the JSON file, never inline in the shell; both given
    must agree. ``None`` when neither is given.
    """
    in_file = proposal.pop(key, None)
    if in_file is not None and not isinstance(in_file, str):
        fail(f'"{key}" in the proposal must be a string, got {in_file!r}')
    if flag is not None and in_file is not None and flag.strip() != in_file.strip():
        fail(f'--{key} ({flag!r}) and "{key}" in the proposal ({in_file!r}) disagree: give it once')
    return flag if flag is not None else in_file


@app.command("pick")
def pick_command(
    platform: Annotated[str, typer.Option(help="tiktok | instagram | youtube | higgsfield (a Genjutsu gallery clip: proposal.preset_id).")],
    views: Annotated[int, typer.Option(min=0)],
    outlier_x: Annotated[float, typer.Option(min=0, help="Views divided by the creator's median.")],
    character: Annotated[str, typer.Option(help="Matched character slug.")],
    freshness: Annotated[float, typer.Option(min=0, max=10, help="Judged: 10 rising now, 6 evergreen, 3 past peak.")],
    fit: Annotated[float, typer.Option(min=0, max=10, help="Judged: fit with the character's premise.")],
    feasibility: Annotated[float, typer.Option(min=0, max=10, help="Judged: how easy for our pipeline.")],
    saturation: Annotated[
        float | None,
        typer.Option(
            min=0, max=10,
            help="Judged: 10 fresh, 5 template everywhere. Omit it when the proposal has saturation_count: "
            "8+ copies = 3, 4-7 = 5, 1-3 = 8, none = 10.",
        ),
    ] = None,
    url: Annotated[
        str | None,
        typer.Option(help='Full video URL (or "url" in the --proposal-file JSON: text from a scan goes in a file).'),
    ] = None,
    creator: Annotated[
        str | None, typer.Option(help='Creator handle (or "creator" in the --proposal-file JSON).')
    ] = None,
    proposal: Annotated[
        str | None,
        typer.Option(
            help='JSON: {"mode", "hook", "prop", "concept", "needs"?, "url"?, "creator"?}; needs is multi_body '
            "and/or talking_lane; url and creator are pick identity, not stored in the proposal."
        ),
    ] = None,
    proposal_file: Annotated[
        Path | None, typer.Option("--proposal-file", help="The same JSON, read from a file (use for free text).")
    ] = None,
    origin: Annotated[str, typer.Option(help="scan (default) or owner.")] = "scan",
) -> None:
    """File a scored Viral Pick (status new). A URL (or gallery preset) already in the list is returned as is."""
    proposal = text_option(proposal, proposal_file, "proposal") or "{}"
    try:
        proposal_obj = json.loads(proposal)
    except json.JSONDecodeError as e:
        fail(f"--proposal is not valid JSON: {e}")
    if not isinstance(proposal_obj, dict):
        fail("--proposal must be a JSON object")
    proposal_obj = dict(proposal_obj)
    url = _from_file_or_flag(proposal_obj, "url", url)
    creator = _from_file_or_flag(proposal_obj, "creator", creator)
    if url is None and platform != GALLERY_PLATFORM:  # a gallery clip is keyed by its preset_id instead
        fail('a pick needs its URL: pass --url or put "url" in the --proposal-file JSON')
    if saturation is None:
        count = proposal_obj.get("saturation_count")
        if count is None:
            fail('--saturation is needed (or "saturation_count" in the proposal: the score is worked out from it)')
        try:
            saturation = saturation_score(count)
        except ValueError as e:
            fail(f"proposal.saturation_count: {e}")
    store = open_store()
    try:
        f, created = _add_pick(
            store, url or "", platform, creator, views, outlier_x, character, proposal_obj,
            cast(FavoriteOrigin, origin),
            {"freshness": freshness, "fit": fit, "feasibility": feasibility, "saturation": saturation},
        )
    except ValueError as e:
        fail(str(e))
    emit(_fav_json(f, duplicate=not created))


@app.command("list")
def list_command(
    status: Annotated[
        str | None, typer.Option(help="new (default), approved, skipped, analysed, queued, made or all.")
    ] = None,
    next_: Annotated[
        int | None, typer.Option("--next", min=0, help="The next N picks to produce (approved/analysed, oldest first).")
    ] = None,
    character: Annotated[
        str | None, typer.Option(help="Only this character's picks (with --next: its own queue).")
    ] = None,
) -> None:
    """List picks by total score, or with --next the production queue."""
    if next_ is not None and status is not None:
        fail("--next and --status cannot be combined")
    store = open_store()
    try:
        if next_ is not None:
            rows = next_favorites(store, next_, character)
        else:
            rows = list_picks(store, None if status == "all" else (status or "new"), character)
    except ValueError as e:
        fail(str(e))
    emit([_fav_json(f) for f in rows])


@app.command("seen")
def seen_command(
    limit: Annotated[
        int, typer.Option(min=0, max=100, help="How many (vidIQ's excludeContentIds takes at most 100).")
    ] = 100,
) -> None:
    """Platform ids of the newest favourites of any status, newest first: vidIQ's excludeContentIds."""
    emit(seen_ids(open_store(), limit))


@app.command("mark")
def mark_command(
    id: Annotated[str, typer.Argument(help="Favourite id.")],
    status: Annotated[
        str | None,
        typer.Option(help="new, approved, skipped, analysed, queued or made. Omit it to keep the pick's own status."),
    ] = None,
    breakdown: Annotated[str | None, typer.Option(help="Beat-by-beat breakdown (markdown).")] = None,
    breakdown_file: Annotated[
        Path | None, typer.Option("--breakdown-file", help="The breakdown, read from a file (use for tool text).")
    ] = None,
    clip: Annotated[str | None, typer.Option(help="Clip id made from it.")] = None,
    source: Annotated[str | None, typer.Option(help="Source id of a clean inbox file (Drop-in).")] = None,
    note: Annotated[str | None, typer.Option()] = None,
    note_file: Annotated[Path | None, typer.Option("--note-file", help="The note, read from a file.")] = None,
    analysis_file: Annotated[
        Path | None,
        typer.Option(
            "--analysis-file",
            help="JSON object: the check of the clip (people_count, main_subject, camera, watermark, overlay, minors, "
            "best_window, bpm, notes), stored as proposal.analysis.",
        ),
    ] = None,
) -> None:
    """Move a pick through production and attach its breakdown, clip, source or clip check."""
    breakdown = text_option(breakdown, breakdown_file, "breakdown")
    note = text_option(note, note_file, "note")
    fields = {
        k: v
        for k, v in {
            "breakdown_md": breakdown, "clip_id": clip, "source_id": source, "note": note
        }.items()
        if v is not None
    }
    store = open_store()
    try:
        if analysis_file is not None or status is None:
            current = store.get_favorite(id)
            if current is None:
                raise KeyError(id)
            status = status or current.status
            if analysis_file is not None:
                try:
                    analysis = json.loads(text_option(None, analysis_file, "analysis") or "")
                except json.JSONDecodeError as e:
                    fail(f"--analysis-file is not valid JSON: {e}")
                fields["proposal"] = {**current.proposal, "analysis": analysis}
        f = mark_favorite(store, id, status, **fields)
    except KeyError:
        fail(f"unknown favourite {id}")
    except ValueError as e:
        fail(str(e))
    emit(_fav_json(f))


@app.command("decide")
def decide_command(
    id: Annotated[str, typer.Argument(help="Favourite id.")],
    decision: Annotated[str | None, typer.Option(help="approve, skip or hold. Omit to apply the standing rule.")] = None,
    reason: Annotated[
        str | None, typer.Option(help="One line; required for analyst decisions and holds.")
    ] = None,
    reason_file: Annotated[
        Path | None, typer.Option("--reason-file", help="The reason, read from a file (use for free text).")
    ] = None,
    by: Annotated[str | None, typer.Option(help="owner, analyst or rule; required with --decision.")] = None,
) -> None:
    """Decide a pick: by the standing rule (default; exit 4 = needs an analyst) or by hand."""
    reason = text_option(reason, reason_file, "reason") or ""
    store = open_store()
    try:
        if decision is None:
            if reason or by not in (None, "rule"):
                fail("--reason and --by only apply with --decision (the rule writes its own reason)")
            f = apply_rule(store, id)
        else:
            if by is None:
                fail("--by is required with --decision (owner, analyst or rule)")
            f = decide(store, id, cast(Decision, decision), reason, cast(DecidedBy, by))
    except NeedsAnalyst as e:
        emit(
            {
                "ok": False,
                "needs": "analyst",
                "id": e.favorite.id,
                "total_score": e.favorite.total_score,
                "feasibility": e.favorite.scores.get("feasibility"),
                "message": f"{e} - rerun with --decision approve|skip --reason '...' --by analyst",
            }
        )
        raise typer.Exit(EXIT_NEEDS_ANALYST) from e
    except KeyError:
        fail(f"unknown favourite {id}")
    except ValueError as e:
        fail(str(e))
    emit(_fav_json(f))
