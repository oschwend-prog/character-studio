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

CLI (``studio fav ...``) prints JSON on stdout. Exit codes: 0 ok, 2 anything the caller must fix,
4 ``fav decide`` found the pick needs an analyst decision (JSON on stdout says so).
"""

from __future__ import annotations

import dataclasses
import json
import math
import re
from pathlib import Path
from typing import Annotated, Any, Literal, cast, get_args
from urllib.parse import urlsplit

import typer

from studio.cli_support import emit, fail, open_store, text_option
from studio.models import Favorite, FavoriteOrigin, FavoriteStatus
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

_FULL_URL_HELP = (
    "https://www.tiktok.com/@user/video/<id>, https://www.instagram.com/reel/<code>/ "
    "or https://www.youtube.com/shorts/<id>"
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
    raise ValueError(f"not a supported video URL: expected {_FULL_URL_HELP}, got {raw!r}")


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
) -> dict[str, float]:
    """The six sub-scores (0-10) and ``total`` (0-100, whole number) of a pick, spec weights v1.

    ``virality`` and ``reach`` are returned to 1 decimal and ``total`` is computed from the
    returned values. ``outlier_x`` and ``views`` are scored here (an unknown or sub-1x outlier scores 0 virality,
    views under 100K score 0 reach); the other four are judged and must be within 0-10.
    """
    judged = {"freshness": freshness, "fit": fit, "feasibility": feasibility, "saturation": saturation}
    for name, value in judged.items():
        if not 0 <= value <= 10:  # also false for NaN
            raise ValueError(f"{name} must be between 0 and 10, got {value!r}")
    virality = _clamp(math.log10(outlier_x) / 3 * 10) if outlier_x and outlier_x > 0 else 0.0
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
    found_platform, canonical = parse_video_url(url)
    if platform != found_platform:
        raise ValueError(f"platform {platform!r} does not match the URL ({found_platform})")
    if character_slug is not None:  # None = not matched to a seeded character yet
        _require_character(store, character_slug)
    validate_needs(proposal)
    scores = score_pick(outlier_x, views, **judged)
    existing = store.list_favorites(url=canonical)
    if existing:
        return existing[0], False
    total = scores.pop("total")
    proposal = dict(proposal)
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
    that was already picked, produced or skipped.
    """
    if limit < 0:
        raise ValueError(f"limit must be 0 or more, got {limit!r}")
    rows = store.list_favorites()
    rows.sort(key=lambda f: f.created_at.timestamp() if f.created_at else 0.0, reverse=True)
    return [content_id(f.url) for f in rows[:limit]]


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
    platform: Annotated[str, typer.Option(help="tiktok | instagram | youtube.")],
    views: Annotated[int, typer.Option(min=0)],
    outlier_x: Annotated[float, typer.Option(min=0, help="Views divided by the creator's median.")],
    character: Annotated[str, typer.Option(help="Matched character slug.")],
    freshness: Annotated[float, typer.Option(min=0, max=10, help="Judged: 10 rising now, 6 evergreen, 3 past peak.")],
    fit: Annotated[float, typer.Option(min=0, max=10, help="Judged: fit with the character's premise.")],
    feasibility: Annotated[float, typer.Option(min=0, max=10, help="Judged: how easy for our pipeline.")],
    saturation: Annotated[float, typer.Option(min=0, max=10, help="Judged: 10 fresh, 5 template everywhere.")],
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
    """File a scored Viral Pick (status new). A URL already in the list is returned as is."""
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
    if url is None:
        fail('a pick needs its URL: pass --url or put "url" in the --proposal-file JSON')
    store = open_store()
    try:
        f, created = _add_pick(
            store, url, platform, creator, views, outlier_x, character, proposal_obj,
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
    status: Annotated[str, typer.Option(help="new, approved, skipped, analysed, queued or made.")],
    breakdown: Annotated[str | None, typer.Option(help="Beat-by-beat breakdown (markdown).")] = None,
    breakdown_file: Annotated[
        Path | None, typer.Option("--breakdown-file", help="The breakdown, read from a file (use for tool text).")
    ] = None,
    clip: Annotated[str | None, typer.Option(help="Clip id made from it.")] = None,
    source: Annotated[str | None, typer.Option(help="Source id of a clean inbox file (Drop-in).")] = None,
    note: Annotated[str | None, typer.Option()] = None,
    note_file: Annotated[Path | None, typer.Option("--note-file", help="The note, read from a file.")] = None,
) -> None:
    """Move a pick through production and attach its breakdown, clip or source."""
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
