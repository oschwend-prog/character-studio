"""Collab posts (owner 2026-10-24): each character's first Reel of the week carries one of our other characters as collaborator.

An Instagram Collab Reel shows on both profiles and in both audiences' feeds once the invited account accepts the invite (the owner
does that in the partner's Instagram app; until then the Reel shows only on the author's profile). The publisher already sends
``features['collab']`` (``studio.publish.reach``: live partners with a Postiz integration only, never a Trial Reel); this module is
what writes it.

**The rule** (``config/scan.json`` ``reach.collabs``: ``on``, ``order``, ``from``):

- **How often:** one per character per London week (Monday to Sunday). At make (``studio.drop``) a character's clip gets a
  collaborator when no clip of his made the same week holds it: a clip holds the week while it carries that week's
  ``features['collab_auto']`` and is not failed, rejected or dropped (``learn.LEAD_GIVES_BACK``: such a clip gives the week back,
  so his next clip that week takes it). With Monday-to-Friday posting that is 1 Reel in 5.
- **Who:** ``partner_of``: the characters stand in the ring ``order``; in the week ``from`` (a Monday, week A) each one takes the
  next in the ring, the week after the one after that, and so on through the others (``1 + week % (n - 1)`` places on). With
  three characters: week A Franz with Reginald, Reginald with Lenny, Lenny with Franz; week B the reverse; then A again. Every
  character is the guest on exactly one other Reel a week. Before ``from`` there is no collab.
- **Who can be a partner:** a ``live`` character with an Instagram account that has a Postiz integration (the publisher would
  drop anyone else); no such partner, no collab that week for him (the week is not held, a later clip may still take it).
- **What it writes:** ``features['collab']`` = ``[the partner's Instagram handle]`` and ``features['collab_auto']`` =
  ``{"week": "<Monday, ISO>", "partner": "<slug>"}``: the week marker. The owner changes or removes the partner before the post
  with ``clip set --collab HANDLE`` / ``--no-collab`` (``set_collab``: ``features['collab_by']`` = ``owner``); the week stays held
  by that clip, it is his call, never handed to the next clip.
- **Learning:** collab is chosen by the week, never by the hook, so the running tests stay as they are (no bias, a little noise);
  the weekly review shows the collab Reels beside the solo ones and marks a collab best post or hit (two audiences).

``load_collabs`` refuses a broken block (``ValueError``, the make stops before anything is reserved or paid); an absent block is off.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from studio.config import LONDON
from studio.learn import LEAD_GIVES_BACK
from studio.models import Clip, ClipState, Platform
from studio.store import Store

ROOT = Path(__file__).resolve().parents[1]
SCAN_PATH = ROOT / "config" / "scan.json"  # read at call time: tests point it elsewhere (conftest)
CHARACTERS_DIR = ROOT / "characters"

GIVES_BACK = LEAD_GIVES_BACK  # failed, rejected, dropped: such a clip gives the week back


@dataclass(frozen=True)
class CollabRule:
    """``config/scan.json`` ``reach.collabs``: ``on``, the ring ``order`` (character slugs) and ``since`` (``from``: week A's
    Monday)."""

    on: bool = False
    order: tuple[str, ...] = ()
    since: date | None = None


OFF = CollabRule()


def load_collabs(scan_path: Path | str | None = None, characters_dir: Path | str | None = None) -> CollabRule:
    """The rule from ``config/scan.json`` ``reach.collabs`` (absent: off). ``ValueError`` naming the key for an ``on`` that is not
    true or false, an ``order`` that is not a list of 2 or more distinct characters of ``characters/`` and a ``from`` that is not a
    Monday (YYYY-MM-DD)."""
    path = Path(scan_path or SCAN_PATH)
    try:
        scan = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise ValueError(f"{path}: cannot read it: {e}") from None
    reach = scan.get("reach", {}) if isinstance(scan, Mapping) else {}
    block = reach.get("collabs") if isinstance(reach, Mapping) else None
    if block is None:
        return OFF
    if not isinstance(block, Mapping):
        raise ValueError(f'config/scan.json reach.collabs must be an object {{"on", "order", "from"}}, got {block!r:.60}')
    on = block.get("on", False)
    if not isinstance(on, bool):
        raise ValueError(f"config/scan.json reach.collabs.on must be true or false, got {on!r:.40}")
    order = block.get("order", [])
    known = {p.parent.name for p in Path(characters_dir or CHARACTERS_DIR).glob("*/refs.json")}
    if (not isinstance(order, list) or len(order) < 2 or len(set(order)) != len(order)
            or any(not isinstance(s, str) or s not in known for s in order)):  # fmt: skip
        raise ValueError(
            f"config/scan.json reach.collabs.order must list 2 or more distinct characters (known: {', '.join(sorted(known))}), "
            f"got {order!r:.80}"
        )
    raw = block.get("from")
    try:
        since = date.fromisoformat(str(raw))
    except ValueError:
        raise ValueError(f"config/scan.json reach.collabs.from must be a date (YYYY-MM-DD), got {raw!r:.30}") from None
    if since.weekday() != 0:
        raise ValueError(f"config/scan.json reach.collabs.from must be a Monday (week A starts on it), got {since.isoformat()}")
    return CollabRule(on=on, order=tuple(order), since=since)


def week_of(moment: datetime) -> date:
    """The Monday of ``moment``'s London week."""
    day = moment.astimezone(LONDON).date()
    return day - timedelta(days=day.weekday())


def partner_of(rule: CollabRule, slug: str, monday: date) -> str | None:
    """The character ``slug`` takes as collaborator in the week of ``monday`` (see the module doc), or None: he is not in the ring,
    the ring has fewer than 2, or the week is before ``from``."""
    if rule.since is None or slug not in rule.order or len(rule.order) < 2 or monday < rule.since:
        return None
    n = len(rule.order)
    week = (monday - rule.since).days // 7
    return rule.order[(rule.order.index(slug) + 1 + week % (n - 1)) % n]


def partner_handle(store: Store, slug: str) -> str | None:
    """The Instagram handle of ``slug`` when he can be a partner: ``live``, with an Instagram account that has a Postiz
    integration (the publisher drops anyone else, ``reach._collaborators``)."""
    if not any(c.slug == slug and c.status == "live" for c in store.characters()):
        return None
    for a in store.accounts(slug):
        if a.platform is Platform.instagram and a.handle and a.postiz_integration_id:
            return a.handle.strip().lstrip("@").strip()
    return None


def holds_week(clip: Clip, monday: date) -> bool:
    """Does ``clip`` hold its character's collab of the week of ``monday``? It carries that week's marker and is not failed,
    rejected or dropped."""
    marker = clip.features.get("collab_auto")
    return isinstance(marker, Mapping) and marker.get("week") == monday.isoformat() and clip.state not in GIVES_BACK


def collab_at_make(store: Store, slug: str, now: datetime, rule: CollabRule) -> dict[str, Any]:
    """The collab tags of the clip ``slug`` is being made (``studio.drop``, inside the make's transaction, under the settings row
    lock: two makes of one character never both take the week): ``{"collab": [handle], "collab_auto": {...}}`` when the rule is on,
    the week has a partner for him, no clip of his holds the week yet and the partner can be one; else ``{}``."""
    if not rule.on:
        return {}
    monday = week_of(now)
    partner = partner_of(rule, slug, monday)
    if partner is None or any(holds_week(c, monday) for c in store.list_clips(character_slug=slug)):
        return {}
    handle = partner_handle(store, partner)
    if handle is None:
        return {}
    return {"collab": [handle], "collab_auto": {"week": monday.isoformat(), "partner": partner}}


def set_collab(store: Store, clip_id: str, handle: str | None) -> Clip:
    """The owner's choice before the post (``clip set --collab HANDLE`` / ``--no-collab``): ``handle`` = the Instagram handle of
    another character who can be a partner (``partner_handle``; ``@`` and case aside), or None for no collaborator. Writes
    ``features['collab']`` (``[handle]`` or ``[]``) and ``features['collab_by']`` = ``owner``; a ``collab_auto`` marker stays, so the
    week stays held by this clip. ``KeyError`` for an unknown clip, ``ValueError`` (nothing written) for a posted clip or a handle
    that is no partner of his."""
    clip = store.get_clip(clip_id)
    if clip is None:
        raise KeyError(clip_id)
    if clip.state is ClipState.posted:
        raise ValueError(f"clip {clip_id} is already posted: its collaborators went out with it")
    chosen: list[str] = []
    if handle is not None:
        key = handle.strip().lstrip("@").strip().lower()
        partners = {
            h.lower(): h for c in store.characters() if c.slug != clip.character_slug
            if (h := partner_handle(store, c.slug)) is not None
        }
        if key not in partners:
            raise ValueError(
                f"{handle!r} is not the Instagram account of another live character with Postiz "
                f"(partners: {', '.join(sorted(partners.values())) or 'none'})"
            )
        chosen = [partners[key]]
    return store.update_clip(clip_id, features={**clip.features, "collab": chosen, "collab_by": "owner"})
