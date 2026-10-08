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
(``estimate_credits``, the single source of truth: recreate 160 including the amortised synthetic driver; a
drop-in is priced per second of the trimmed source, ``ceil(seconds x 11) + 3`` for the stills, plus 30 for an
``ai_beat`` render, so 91 for the default 8 s keeping the original audio (or adding the song in the app) and 121
with an AI beat). The plan
**stops at the first clip that would take ``committed + Σ est`` past the monthly cap**: nothing
after it is planned either, even if a cheaper clip would still fit (the daily run's rule is to
stop on a budget refusal). ``studio plan today`` also reports those deferred clips.

**Mode** (``choose_mode``): ``dropin`` when a Drop-in eligible source exists for the character and
its lead account's rolling Drop-in ratio is under that account's ``dropin_share``; else
``recreate``. The lead account is the character's connected TikTok account, else its connected
Instagram account (a character with neither is always ``recreate``). The rolling ratio
(``dropin_ratio``) is the fraction of Drop-ins among the last ``ROLLING_WINDOW`` (10) clips that
produced a post for the account, oldest to newest by the post's ``scheduled_for``. A post counts
whatever its status (a failed post still used a slot in the window); with no history the ratio is 0.
The comparison is strict: a ratio equal to the share is not under it, and a share of 0 turns Drop-in
off for the account. **A share of 1 (or more) is the one exception: it means "no cap", Drop-in is the
default for every video (owner decision 2026-10-05), so it is always under the share** even with ten
Drop-ins in a row; the Instagram guard still cuts an account to 0.20.

**Accounts** (``accounts_for_clip``): a recreate clip goes to every connected account of the
character; a drop-in clip only to those whose own ratio is under their own share, so an Instagram
account at 5 Drop-ins in 10 (share 0.40) is skipped. The clip's own posts are left out of the
window, so asking again after the posts exist gives the same answer.

Accounts with no ``postiz_integration_id`` are not connected yet, so planning skips them
everywhere. A character with no connected account at all is therefore always ``recreate``.

**Slots** (``slot_for``) are London wall-clock times built with ``zoneinfo``, never naive:
19:00 is 19:00 whether it is GMT or BST that day. ``upcoming_slot`` is the first slot still ahead of a
moment: today's if today is a cadence day and the slot has not started, else the next cadence day's.

**The cadence** is the ``studio.settings`` row (``cadence``: ``{slug: {"days": [...], "slot": "HH:MM"}}``), the one place
the posting days and slots live; the SQL slot functions of the terminal read the same row. ``studio plan cadence`` prints it
and changes it (``apply_cadence``): ``--slot franz=19:00`` sets or adds a character's slot (a new character starts on
``LAUNCH_DAYS``, the weeks 1-2 days), ``--days`` sets the days of those characters (or of every character: the week-3 switch is
``--days mon,tue,wed,thu,fri``), ``--drop`` removes a retired character's entry (its slot functions then refuse to schedule).

**A clip's family** (terminal v3): one clip the owner dropped may be used by up to 3 characters (a drop and its versions,
``drop.copy_of``). ``family_days`` gives the London days within 13 days either side of a post of another clip of the family, on
any account; ``schedule_clip`` treats them as taken, so the family's posts are at least ``FAMILY_GAP_DAYS`` (14) apart.

CLI (``studio plan today``) prints JSON on stdout; exit 0 even when nothing is due (the caller
reads ``due`` and ``kill_switch``), exit 2 for a cadence the caller must fix.
"""

from __future__ import annotations

import math
import re
from collections.abc import Collection, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from typing import Annotated, Any

import typer

from studio.budget import committed, month_key
from studio.cli_support import emit, fail, open_store
from studio.config import LONDON, now_london
from studio.favorites import family_picks
from studio.models import (
    DEFAULT_CADENCE,
    MUSIC_ARMS,
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

# Estimated credits per clip (owner decision 2026-10-05: the Drop-in cost follows the length Genjutsu is paid for).
# Recreate includes the ~70 credits of its synthetic driver, spread over the clips made from it. A Drop-in is
# priced per second of the trimmed source (Genjutsu 1080p), plus the stills, plus the ~30-credit Seedance beat
# render only when the music is ``ai_beat`` (``original``, the default, and ``in_app`` need none).
RECREATE_CREDITS = 160
DROPIN_CREDITS_PER_SECOND = 11
DROPIN_STILLS_CREDITS = 3
AI_BEAT_CREDITS = 30
DEFAULT_DROPIN_SECONDS = 8.0
DEFAULT_MUSIC = "original"  # owner decision 2026-10-05: Drop-ins keep the original clip audio by default
RECREATE_MUSIC = "ai_beat"  # a Recreate clip's synthetic driver has no original audio: it carries our own beat


def estimate_credits(
    mode: Mode | str, seconds: float = DEFAULT_DROPIN_SECONDS, music: str = DEFAULT_MUSIC
) -> int:
    """Credits one clip is expected to cost. The only place the numbers live: the plan, ``plan estimate`` and
    the daily run's reserve all call this (the terminal's Make-it sheet mirrors it in ``estimateCredits``).

    Recreate is 160 whatever ``seconds`` and ``music``. A Drop-in is ``ceil(seconds x 11) + 3`` (+ 30 for
    ``ai_beat``), so the default 8 s costs 91 and 121.
    """
    try:
        mode = Mode(mode)
    except ValueError:
        raise ValueError(f"mode must be one of {[m.value for m in Mode]}, got {mode!r}") from None
    if music not in MUSIC_ARMS:
        raise ValueError(f"music must be one of {list(MUSIC_ARMS)}, got {music!r}")
    if mode is Mode.recreate:
        return RECREATE_CREDITS
    if isinstance(seconds, bool) or not isinstance(seconds, (int, float)) or not math.isfinite(seconds) or seconds <= 0:
        raise ValueError(f"seconds must be a positive number, got {seconds!r}")
    # round first: 0.1 x 11 style float noise must not push an exact figure up a whole credit
    base = math.ceil(round(seconds * DROPIN_CREDITS_PER_SECOND, 6)) + DROPIN_STILLS_CREDITS
    return base + (AI_BEAT_CREDITS if music == "ai_beat" else 0)

ROLLING_WINDOW = 10

WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")

_SLOT = re.compile(r"([01]\d|2[0-3]):([0-5]\d)")
_SLUG = re.compile(r"[a-z0-9][a-z0-9-]{0,39}")
# The posting days of a character's first two weeks (CLAUDE.md "Slots": weeks 1-2 Tue/Wed/Thu, from week 3 Mon-Fri): what a
# character added to the cadence starts on.
LAUNCH_DAYS: tuple[str, ...] = ("tue", "wed", "thu")


@dataclass
class DueClip:
    character_slug: str
    mode: Mode
    slot: datetime
    est_credits: int
    source_candidates: list[str] = field(default_factory=list)  # source ids, best first
    music: str = DEFAULT_MUSIC  # original | in_app | ai_beat: what ``est_credits`` assumes (see ``choose_music``)


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


FAMILY_GAP_DAYS = 14  # terminal v3: the posts of one clip's family (a drop and its versions) are at least 14 days apart


def family_days(store: Store, clip_id: str) -> set[date]:
    """The London days the clip may not be posted on because of its family (terminal v3, spec section 4).

    A drop's family is its root and the versions of it (``favorites.family_picks``: ``drop.copy_of``). Every post of another
    clip of the family (a member's ``clip_id``, or a clip whose ``features.fav_id`` is a member) that holds a day
    (``TAKEN_STATUSES``, dated like ``taken_days``: ``claimed_at``, else ``scheduled_for``, in London), on ANY account, takes
    that day and the 13 days either side of it, so no two of the family's posts are less than ``FAMILY_GAP_DAYS`` apart. The
    clip itself is left out (its own posts are ``taken_days``' business), and a skipped member's posts still count. A clip of
    no family (or an unknown one) has none. ``schedule_clip`` adds them to its taken days; SQL ``studio.free_slot`` mirrors it.
    """
    clip = store.get_clip(clip_id)
    if clip is None:
        return set()
    pick = None
    fav_id = clip.features.get("fav_id")
    if isinstance(fav_id, str) and fav_id:
        pick = store.get_favorite(fav_id)
    if pick is None:
        pick = next(iter(store.list_favorites(clip_id=clip_id)), None)
    if pick is None:
        return set()
    members = family_picks(store, pick)
    if len(members) < 2:
        return set()
    member_ids = {m.id for m in members}
    clip_ids = {m.clip_id for m in members if m.clip_id}
    clip_ids |= {c.id for c in store.list_clips() if c.features.get("fav_id") in member_ids}
    clip_ids.discard(clip_id)
    near = range(-(FAMILY_GAP_DAYS - 1), FAMILY_GAP_DAYS)
    days: set[date] = set()
    for other in clip_ids:
        for post in store.list_posts(clip_id=other):
            if post.status in TAKEN_STATUSES:
                day = (post.claimed_at or post.scheduled_for).astimezone(LONDON).date()
                days.update(day + timedelta(days=k) for k in near)
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


NO_CAP_SHARE = 1.0  # a Drop-in share at or above this is "no cap": Drop-in is the default for every video


def _under_share(ratio: float, account: Account) -> bool:
    share = float(account.dropin_share)
    return share >= NO_CAP_SHARE or ratio < share


def _lead_account(store: Store, character: Character) -> Account | None:
    """The account whose Drop-in ratio decides the character's mode: connected TikTok, else connected Instagram."""
    connected = [a for a in store.accounts(character.slug) if _connected(a)]
    for platform in (Platform.tiktok, Platform.instagram):
        found = next((a for a in connected if a.platform is platform), None)
        if found is not None:
            return found
    return None


def _pick_mode(store: Store, character: Character) -> tuple[Mode, list[str]]:
    """The mode and the ranked source ids to make the clip from, in one pass."""
    with store.transaction():
        dropin_sources = rank_sources(store, character, Mode.dropin, set())
        if dropin_sources:
            lead = _lead_account(store, character)
            if lead is not None and _under_share(dropin_ratio(store, lead), lead):
                return Mode.dropin, [s.id for s in dropin_sources]
        return Mode.recreate, [s.id for s in rank_sources(store, character, Mode.recreate, set())]


def choose_music(store: Store, character: Character, owner_music: str | None = None) -> str:
    """Where a Drop-in's music comes from: the owner's choice for the video (``owner_music``, from the Make-it
    sheet), else ``original``: Drop-ins keep the original clip audio by default (owner decision 2026-10-05; it
    comes through the Genjutsu output, or is muxed back in from the source), so an autopilot account posts a video
    with sound too. ``in_app`` (a silent master, the owner adds the song in the Instagram app) is the fallback when
    Instagram mutes a chart song; ``ai_beat`` is our own Seedance beat (+30 credits).
    """
    if owner_music is not None:
        if owner_music not in MUSIC_ARMS:
            raise ValueError(f"music must be one of {list(MUSIC_ARMS)}, got {owner_music!r}")
        return owner_music
    return DEFAULT_MUSIC


def choose_mode(store: Store, character: Character) -> Mode:
    """``dropin`` if a Drop-in eligible source exists and the lead account is under its share, else ``recreate``."""
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


def parse_days(raw: str) -> list[str]:
    """``"mon,tue , Wed"`` -> ``["mon", "tue", "wed"]`` in week order; ``ValueError`` for an unknown day or none at all."""
    days = {d.strip().lower()[:3] for d in raw.split(",") if d.strip()}
    unknown = sorted(d for d in days if d not in WEEKDAYS)
    if unknown or not days:
        raise ValueError(f"days must be a comma list of {', '.join(WEEKDAYS)}, got {raw!r}")
    return [d for d in WEEKDAYS if d in days]


def apply_cadence(
    current: Mapping[str, Any],
    slots: Mapping[str, str] | None = None,
    days: list[str] | None = None,
    drop: Collection[str] = (),
) -> dict[str, Any]:
    """The cadence after a change (``studio plan cadence``), checked before anything is written.

    ``slots`` sets each named character's ``slot`` ("HH:MM", London), adding a character that has no entry yet on
    ``days`` or else ``LAUNCH_DAYS``; ``days`` sets the days of the ``slots`` characters, or of every character when no slot
    is given (the week-3 switch); ``drop`` removes entries (a slug that has none is an error, so a typo never passes).
    The other entries are kept as they are. ``ValueError`` names the first problem."""
    slots = dict(slots or {})
    out: dict[str, Any] = {slug: dict(entry) if isinstance(entry, Mapping) else entry for slug, entry in current.items()}
    for slug in [*slots, *drop]:
        if not _SLUG.fullmatch(slug):
            raise ValueError(f"not a character slug: {slug!r} (lowercase letters, digits and dashes)")
    both = sorted(set(slots) & set(drop))
    if both:
        raise ValueError(f"{', '.join(both)}: given to both --slot and --drop")
    for slug in drop:
        if slug not in out:
            raise ValueError(f"{slug!r} has no cadence entry to drop (it has: {', '.join(sorted(out)) or 'none'})")
        del out[slug]
    for slug, slot in slots.items():
        if not isinstance(slot, str) or not _SLOT.fullmatch(slot.strip()):
            raise ValueError(f"slot for {slug!r} must be 'HH:MM' (London time), got {slot!r}")
        entry = out.get(slug) if isinstance(out.get(slug), dict) else None
        if entry is None:
            out[slug] = {"days": list(days or LAUNCH_DAYS), "slot": slot.strip()}
        else:
            entry["slot"] = slot.strip()
            if days is not None:
                entry["days"] = list(days)
    if days is not None and not slots:
        if not out:
            raise ValueError("there is no character in the cadence to give --days to")
        for slug, entry in out.items():
            if not isinstance(entry, dict):
                raise ValueError(f"the cadence entry of {slug!r} is not an object: fix it with --slot {slug}=HH:MM")
            entry["days"] = list(days)
    for slug, entry in out.items():  # what the SQL slot functions refuse is refused here first
        _slot_time(slug, out)
        if not _cadence_days(entry) <= set(WEEKDAYS) or not _cadence_days(entry):
            raise ValueError(f"the days of {slug!r} must be some of {', '.join(WEEKDAYS)}, got {entry.get('days')!r}")
    return out


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
        # a Recreate clip's soundtrack is the beat of its own synthetic driver; only a Drop-in chooses music
        music = choose_music(store, character) if mode is Mode.dropin else RECREATE_MUSIC
        clip = DueClip(character.slug, mode, slot, estimate_credits(mode, music=music), candidates, music)
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


@app.command("estimate")
def estimate_command(
    mode: Annotated[str, typer.Option("--mode", help="dropin or recreate.")],
    seconds: Annotated[
        float, typer.Option("--seconds", help="Length of the trimmed source Genjutsu is paid for (Drop-in).")
    ] = DEFAULT_DROPIN_SECONDS,
    music: Annotated[
        str, typer.Option("--music", help="original (default), in_app or ai_beat (+30 credits).")
    ] = DEFAULT_MUSIC,
) -> None:
    """The estimated credits of one clip: what the daily run reserves for the ACTUAL trimmed seconds."""
    try:
        credits = estimate_credits(mode, seconds, music)
    except ValueError as e:
        fail(str(e))
    emit({"mode": mode, "seconds": seconds, "music": music, "est_credits": credits})


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


@app.command("cadence")
def cadence_command(
    slot: Annotated[
        list[str] | None,
        typer.Option("--slot", help="slug=HH:MM (London): set a character's posting slot, or add the character; repeatable."),
    ] = None,
    days: Annotated[
        str | None,
        typer.Option(
            "--days",
            help="Comma list of mon..sun: the posting days of the --slot characters, or of every character when no --slot is "
            "given (the week-3 switch: --days mon,tue,wed,thu,fri). A new character without it starts on tue,wed,thu.",
        ),
    ] = None,
    drop: Annotated[
        list[str] | None, typer.Option("--drop", help="Remove a character's entry (a retired character); repeatable.")
    ] = None,
) -> None:
    """Show the posting cadence (days and London slot per character), or change it with --slot / --days / --drop."""
    store = open_store()
    current = store.get_settings().cadence
    if not slot and days is None and not drop:
        emit({"cadence": current})
        return
    slots: dict[str, str] = {}
    for item in slot or []:
        slug, sep, value = item.partition("=")
        if not sep or not slug.strip():
            fail(f"--slot takes slug=HH:MM, got {item!r}")
        if slug.strip() in slots:
            fail(f"--slot names {slug.strip()!r} twice")
        slots[slug.strip()] = value.strip()
    try:
        new = apply_cadence(current, slots, parse_days(days) if days is not None else None, [d.strip() for d in drop or []])
    except ValueError as e:
        fail(str(e))
    store.set_settings(cadence=new)
    seeded = {c.slug for c in store.characters()}
    emit(
        {
            "cadence": new,
            "before": current,
            "not_seeded": sorted(s for s in new if s not in seeded),  # planned only once seeded and live
        }
    )
