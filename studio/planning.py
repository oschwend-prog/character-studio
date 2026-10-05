"""Daily plan: which characters are due a clip today, in which mode, and at what slot.

``plan_today`` answers the first question of the daily run. A character is **due** when

* the **London** weekday of ``now`` is in its ``cadence.days`` (``Settings.cadence``),
* it has no clip created today (London date) in any state beyond ``planned``: one plan per
  character per day, whatever became of today's clip (a dead one is not replaced until
  tomorrow), and
* the kill switch is off, and
* its ``status`` is ``live`` (a character still being designed is never planned; ``studio plan today`` lists
  those it skipped under ``skipped_not_live``, so a day with nothing due says why).

Due characters are ordered by slot, then slug, and added one by one at an estimated cost
(``EST_CREDITS``: recreate 160 including the amortised synthetic driver, drop-in 115). The plan
**stops at the first clip that would take ``committed + Σ est`` past the monthly cap**: nothing
after it is planned either, even if a cheaper clip would still fit (the daily run's rule is to
stop on a budget refusal). ``studio plan today`` also reports those deferred clips.

**Mode** (``choose_mode``): ``dropin`` when a Drop-in eligible source exists for the character and
its TikTok account's rolling Drop-in ratio is under that account's ``dropin_share``; else
``recreate``. The rolling ratio (``dropin_ratio``) is the fraction of Drop-ins among the last
``ROLLING_WINDOW`` (10) clips that produced a post for the account, oldest to newest by the
post's ``scheduled_for``. A post counts whatever its status (a failed post still used a slot in
the window); with no history the ratio is 0. The comparison is strict: a ratio equal to the
share is not under it, and a share of 0 turns Drop-in off for the account.

**Accounts** (``accounts_for_clip``): a recreate clip goes to every connected account of the
character; a drop-in clip only to those whose own ratio is under their own share, so an Instagram
account at 5 Drop-ins in 10 (share 0.40) is skipped. The clip's own posts are left out of the
window, so asking again after the posts exist gives the same answer.

Accounts with no ``postiz_integration_id`` are not connected yet, so planning skips them
everywhere. A character without a connected TikTok account is therefore always ``recreate``.

**Slots** (``slot_for``) are London wall-clock times built with ``zoneinfo``, never naive:
19:00 is 19:00 whether it is GMT or BST that day. ``upcoming_slot`` is the first slot still ahead of a
moment: today's if today is a cadence day and the slot has not started, else the next cadence day's.

CLI (``studio plan today``) prints JSON on stdout; exit 0 even when nothing is due (the caller
reads ``due`` and ``kill_switch``), exit 2 for a cadence the caller must fix.
"""

from __future__ import annotations

import re
from collections.abc import Collection, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from typing import Any

import typer

from studio.budget import committed, month_key
from studio.cli_support import emit, fail, open_store
from studio.config import LONDON, now_london
from studio.models import (
    DEFAULT_CADENCE,
    Account,
    Character,
    Clip,
    ClipState,
    Mode,
    Platform,
    PostStatus,
)
from studio.sources import rank_sources
from studio.store import Store, require_aware

# Estimated credits per clip. Recreate includes the ~70 credits of its synthetic driver, spread
# over the clips made from it.
EST_CREDITS: dict[Mode, int] = {Mode.recreate: 160, Mode.dropin: 115}

ROLLING_WINDOW = 10

WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")

_SLOT = re.compile(r"([01]\d|2[0-3]):([0-5]\d)")


@dataclass
class DueClip:
    character_slug: str
    mode: Mode
    slot: datetime
    est_credits: int
    source_candidates: list[str] = field(default_factory=list)  # source ids, best first


@dataclass
class Plan:
    """What ``plan_today`` decided, with the numbers it decided on."""

    day: date  # the London date of ``now``
    kill_switch: bool
    cap: int
    committed: int  # settled + reserved credits of the month, before this plan
    due: list[DueClip] = field(default_factory=list)
    deferred: list[DueClip] = field(default_factory=list)  # due today, but past the cap
    skipped_not_live: list[str] = field(default_factory=list)  # on today's cadence, but not ``live`` yet


# ---- slots ---------------------------------------------------------------------------------


def _slot_time(character_slug: str, cadence: Mapping[str, Any]) -> time:
    entry = cadence.get(character_slug)
    if not isinstance(entry, Mapping) or "slot" not in entry:
        raise ValueError(f"no posting slot configured for {character_slug!r}")
    raw = entry["slot"]
    match = _SLOT.fullmatch(raw) if isinstance(raw, str) else None
    if match is None:
        raise ValueError(f"slot for {character_slug!r} must be 'HH:MM' (London time), got {raw!r}")
    return time(int(match[1]), int(match[2]))


def slot_for(
    character_slug: str, day: date, cadence: Mapping[str, Any] | None = None
) -> datetime:
    """The character's posting slot on ``day`` as an aware Europe/London datetime.

    ``cadence`` is ``Settings.cadence`` (``{slug: {"days": [...], "slot": "HH:MM"}}``); without
    it the shipped default cadence is used. A wall time that does not exist (inside the spring
    clock change) is read as the real instant it falls on, so the result is always a valid time.
    """
    slot = _slot_time(character_slug, DEFAULT_CADENCE if cadence is None else cadence)
    local = datetime.combine(day, slot, tzinfo=LONDON)
    return local.astimezone(timezone.utc).astimezone(LONDON)


def upcoming_slot(
    character_slug: str, now: datetime, cadence: Mapping[str, Any]
) -> datetime:
    """The character's first posting slot strictly after ``now``, on a cadence day (London days).

    Today's slot if today is a cadence day and the slot has not started yet, else the slot of the next
    cadence day. ``ValueError`` when the character has no slot, or no cadence days at all.
    """
    require_aware(now, "upcoming_slot(now)")
    _slot_time(character_slug, cadence)  # a missing or malformed slot is reported as such
    days = _cadence_days(cadence.get(character_slug))
    today = now.astimezone(LONDON).date()
    for offset in range(8):  # today and the next seven days: every weekday is seen twice at most
        day = today + timedelta(days=offset)
        if WEEKDAYS[day.weekday()] in days:
            candidate = slot_for(character_slug, day, cadence)
            if candidate > now:
                return candidate
    if not days:
        raise ValueError(f"no posting days configured for {character_slug!r}")
    raise ValueError(f"no upcoming slot found for {character_slug!r}")  # unreachable with real weekdays


# A post in one of these statuses holds (or already used) its account's slot on its London day.
TAKEN_STATUSES = (PostStatus.scheduled, PostStatus.posting, PostStatus.posted, PostStatus.needs_check)
FREE_SLOT_LOOKAHEAD_DAYS = 56  # eight weeks of cadence days to look through


def taken_days(
    store: Store, account_ids: Collection[str], *, exclude_clip_id: str | None = None
) -> set[date]:
    """The London days on which any of ``account_ids`` already has a post that holds a slot.

    A post counts when it is ``scheduled``, ``posting``, ``posted`` or ``needs_check`` (a failed one
    never took the slot). Its day is that of ``claimed_at`` (when it really went out), else of
    ``scheduled_for``: the same day ``studio.publish.base`` caps on. ``exclude_clip_id`` leaves one clip's
    own posts out (a half-finished earlier call of the clip being scheduled must not push its other
    posts to another day). Mirrors ``studio.free_slot`` in migration 0006.
    """
    days: set[date] = set()
    for account_id in account_ids:
        for post in store.list_posts(account_id=account_id):
            if post.status in TAKEN_STATUSES and post.clip_id != exclude_clip_id:
                days.add((post.claimed_at or post.scheduled_for).astimezone(LONDON).date())
    return days


def free_slot(
    character_slug: str, start: datetime, cadence: Mapping[str, Any], taken: Collection[date]
) -> datetime:
    """The first cadence slot at or after ``upcoming_slot(start)`` whose London day is not in ``taken``.

    The one rule for a default slot: an approval (``schedule_clip`` here, ``approve_clip`` in migration
    0006) and a publish deferral past the daily cap both land on the first cadence day on which none of
    the target accounts already posts, so two clips approved for the same accounts never share a day.
    An explicit time given by the owner is not passed through here. ``ValueError`` when the character has
    no slot or cadence days, or when the next ``FREE_SLOT_LOOKAHEAD_DAYS`` days hold no free cadence day.
    """
    first = upcoming_slot(character_slug, start, cadence)  # raises for a missing slot or cadence days
    days = _cadence_days(cadence.get(character_slug))
    first_day = first.astimezone(LONDON).date()
    for offset in range(FREE_SLOT_LOOKAHEAD_DAYS):
        day = first_day + timedelta(days=offset)
        if WEEKDAYS[day.weekday()] in days and day not in taken:
            return slot_for(character_slug, day, cadence)
    raise ValueError(
        f"no free posting day for {character_slug!r} in the next {FREE_SLOT_LOOKAHEAD_DAYS} days"
    )


# ---- Drop-in ratio and mode choice -----------------------------------------------------------


def _connected(account: Account) -> bool:
    return bool(account.postiz_integration_id)


def dropin_ratio(store: Store, account: Account, *, exclude_clip_id: str | None = None) -> float:
    """Share of Drop-ins among the account's last ``ROLLING_WINDOW`` clips that produced a post.

    0.0 without history. ``exclude_clip_id`` leaves that clip's own post out of the window.
    """
    with store.transaction():  # one connection for the post list and the per-clip reads
        posts = [p for p in store.list_posts(account_id=account.id) if p.clip_id != exclude_clip_id]
        recent = posts[-ROLLING_WINDOW:]
        if not recent:
            return 0.0
        dropins = 0
        for post in recent:
            clip = store.get_clip(post.clip_id)
            if clip is not None and clip.mode is Mode.dropin:
                dropins += 1
    return dropins / len(recent)


def _under_share(ratio: float, account: Account) -> bool:
    return ratio < float(account.dropin_share)


def _tiktok_account(store: Store, character: Character) -> Account | None:
    return next(
        (
            a
            for a in store.accounts(character.slug)
            if a.platform is Platform.tiktok and _connected(a)
        ),
        None,
    )


def _pick_mode(store: Store, character: Character) -> tuple[Mode, list[str]]:
    """The mode and the ranked source ids to make the clip from, in one pass."""
    with store.transaction():
        dropin_sources = rank_sources(store, character, Mode.dropin, set())
        if dropin_sources:
            tiktok = _tiktok_account(store, character)
            if tiktok is not None and _under_share(dropin_ratio(store, tiktok), tiktok):
                return Mode.dropin, [s.id for s in dropin_sources]
        return Mode.recreate, [s.id for s in rank_sources(store, character, Mode.recreate, set())]


def choose_mode(store: Store, character: Character) -> Mode:
    """``dropin`` if a Drop-in eligible source exists and TikTok is under its share, else ``recreate``."""
    return _pick_mode(store, character)[0]


def accounts_for_clip(store: Store, clip: Clip) -> list[Account]:
    """The character's connected accounts this clip should be posted to.

    Recreate: all of them. Drop-in: only those whose own rolling Drop-in ratio is under their own
    ``dropin_share``.
    """
    with store.transaction():
        accounts = [a for a in store.accounts(clip.character_slug) if _connected(a)]
        if clip.mode is Mode.recreate:
            return accounts
        return [
            a
            for a in accounts
            if _under_share(dropin_ratio(store, a, exclude_clip_id=clip.id), a)
        ]


# ---- the plan ----------------------------------------------------------------------------------


def _cadence_days(entry: Any) -> set[str]:
    raw = entry.get("days") if isinstance(entry, Mapping) else None
    if isinstance(raw, str):
        raw = [raw]
    return {str(d).strip().lower()[:3] for d in raw or ()}


def _has_clip_today(store: Store, character_slug: str, day: date) -> bool:
    """A clip of this character created on ``day`` (London) that is already beyond ``planned``."""
    return any(
        c.state is not ClipState.planned
        and c.created_at is not None
        and c.created_at.astimezone(LONDON).date() == day
        for c in store.list_clips(character_slug=character_slug)
    )


def _plan(store: Store, now: datetime) -> Plan:
    require_aware(now, "plan_today(now)")
    settings = store.get_settings()  # outside any transaction: no row lock for a read-only plan
    day = now.astimezone(LONDON).date()
    plan = Plan(
        day=day,
        kill_switch=settings.kill_switch,
        cap=settings.monthly_cap_credits,
        committed=committed(store, month_key(now)),
    )
    if settings.kill_switch:
        return plan

    weekday = WEEKDAYS[day.weekday()]
    characters = {c.slug: c for c in store.characters()}
    todo: list[tuple[datetime, Character]] = []
    for slug, entry in settings.cadence.items():
        character = characters.get(slug)
        if character is None or weekday not in _cadence_days(entry):
            continue
        if character.status != "live":  # a character still being designed has no avatar or accounts to post
            plan.skipped_not_live.append(slug)
            continue
        if _has_clip_today(store, slug, day):
            continue
        todo.append((slot_for(slug, day, settings.cadence), character))
    todo.sort(key=lambda item: (item[0], item[1].slug))

    total = plan.committed
    stopped = False
    for slot, character in todo:
        mode, candidates = _pick_mode(store, character)
        clip = DueClip(character.slug, mode, slot, EST_CREDITS[mode], candidates)
        if stopped or total + clip.est_credits > plan.cap:
            stopped = True
            plan.deferred.append(clip)
        else:
            total += clip.est_credits
            plan.due.append(clip)
    return plan


def plan_today(store: Store, now: datetime) -> list[DueClip]:
    """The clips to make today, within the monthly cap (empty with the kill switch on)."""
    return _plan(store, now).due


# ---- CLI ---------------------------------------------------------------------------------------

app = typer.Typer(
    help="Daily plan: who is due a clip today, in which mode, at which slot. "
    "Prints JSON; exit 2 = cadence the caller must fix.",
    no_args_is_help=True,
)


@app.command("today")
def today_command() -> None:
    """Characters due a clip today with mode, slot, estimated credits and ranked source ids."""
    store = open_store()
    now = now_london()
    try:
        plan = _plan(store, now)
    except ValueError as e:
        fail(str(e))
    estimated = sum(d.est_credits for d in plan.due)
    emit(
        {
            "date": plan.day.isoformat(),
            "weekday": WEEKDAYS[plan.day.weekday()],
            "month": month_key(now),
            "kill_switch": plan.kill_switch,
            "cap": plan.cap,
            "committed": plan.committed,
            "remaining": max(plan.cap - plan.committed, 0),
            "estimated": estimated,
            "due": plan.due,
            "deferred_over_cap": plan.deferred,
            "skipped_not_live": sorted(plan.skipped_not_live),
        }
    )
