"""``studio publish reshare``: once a day, an account's best recent Reel is shown again as a Story.

Owner 2026-10-14: more exposure from the clips already posted, without posting the same Reel twice (Instagram demotes a duplicate
Reel). A Story is the free way: every Reel already has a Story video (``features['story_path']``, see ``studio.publish.reach``),
and a Story lives 24 hours, so showing it again a day or more later reaches the followers who missed the Reel without touching the
feed. This step runs in the metrics workflow (every 6 hours, after ``studio publish confirm``, which is what puts a ``url`` on a
live Reel) and by hand.

**Eligible clips.** With ``reach.stories`` on (``config/scan.json``; off: nothing happens), for every Instagram account of a ``live``
character that has a Postiz integration, a clip qualifies when its Instagram post is:

* ``posted`` with a ``url`` (``confirm`` saw Postiz publish it: a Reel Postiz failed on is never re-shared);
* posted at least 20 hours and at most 14 days ago (``claimed_at``, else ``scheduled_for``: the posts table has no ``posted_at``);
* and its clip has a Story video, is not a silent ``in_app`` master (a Story of it would go out with no sound, the same rule as the
  Story after a Reel) and was not a Trial Reel (``features['trial_reel']``: it is shown to non-followers first, and a Story would
  show it to the followers before it graduates).

**The pick.** The eligible clip with the most views (the latest ``snapshots`` row of its post; no reading yet = 0). A tie goes to the
more recent post. A clip re-shared in the last 72 hours (any outcome, a failed attempt included, so a clip Postiz keeps refusing
does not hold up the others every day) is skipped, the next best is picked. Only the Instagram post counts: a clip's TikTok views
do not.

**The limits.** At most ONE re-share per account per London day, counted over every clip of the account, and only between 11:00 and
22:00 London time (a Story posted in the small hours is wasted): outside it nothing is posted and the JSON says why. The kill switch
("stop all new spend and posting") stops it too.

**The record.** Each re-share is added to the clip's ``features['story_reshares']``, a list of
``{at, post_id (the Reel's), status, platform_post_id | error}``. It is **claimed first** (``status: posting`` is written before
Postiz is asked), the way the Story after a Reel is (``studio.publish.base._story_marker``): the claim and the outcome are each
written in a transaction that first asks ``get_settings`` (``FOR UPDATE`` on Postgres, the row lock budget reservations use), and the
claim re-reads the account's clips under that lock, so two runs never both take the day's one. Then ``posted``, ``failed`` (Postiz
refused, or anything that raised: the error is kept) or ``needs_check`` (``UncertainPublish``: it may exist). **A failed re-share is
not retried that day** (it still counts as the day's one, on this clip or any other): a resend could double a Story that went out
after all, and tomorrow's pick rests the clip for 72 hours. A claim left in ``posting`` (the process died, or the outcome write was
lost) stays as it is and also holds the day. A re-share **never touches** ``features['story']`` (the one Story that followed the
Reel, "never a second one") or the Reel's post row: it is the owner's own, separate decision (2026-10-14), and its record is its own.
It is a Story, not a feed post: it is not counted toward the 2-posts-a-day cap.

``reshare_stories(store, storage, publisher, now)`` returns ``{"reshared": [...], "skipped": [{account, reason}], "errors": [...]}``
(``studio publish reshare`` prints it as JSON): each ``reshared`` entry has the ``account`` handle, ``clip_id``, ``post_id`` (the
Reel's), its ``views``, the ``status`` and ``platform_post_id`` or ``error``; ``skipped`` says why an account (or, with ``account``
null, the whole run) did nothing; ``errors`` are database writes that failed (a claim that could not be written means nothing was
sent; an outcome that could not be written is left as ``posting``). The command exits 0 whatever Postiz did and 1 only when a write
failed. ``preview_reshare`` is the read-only twin behind ``--dry-run``: the same decisions, nothing written, no storage or
publisher; the picks are under ``would_reshare``. Both take ``reach`` as ``publish_due`` does (``load_reach()`` when not given).
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from studio.config import LONDON
from studio.models import Account, Clip, Platform, Post, PostStatus
from studio.publish.base import MASTER_BUCKET, Publisher, UncertainPublish, _live_characters
from studio.publish.reach import STORIES_OFF, ReachConfig, load_reach
from studio.storage import Storage
from studio.store import Store, require_aware

RESHARES = "story_reshares"  # the clip's list of re-shares (features)
MIN_AGE = timedelta(hours=20)  # a Reel is re-shared once it is at least this old ...
MAX_AGE = timedelta(days=14)  # ... and no older than this
COOLDOWN = timedelta(hours=72)  # a clip is not re-shared again within this long of its last re-share (any outcome)
FIRST_HOUR, LAST_HOUR = 11, 22  # London time: from 11:00 up to, not including, 22:00
LOOK_BACK = MAX_AGE + timedelta(days=1)  # a clip posted longer ago than this cannot hold a re-share of today
_ERROR_CHARS = 500


@dataclass(frozen=True)
class Pick:
    """The re-share chosen for one account."""

    account: Account
    post: Post  # the clip's Instagram Reel
    clip: Clip
    views: int


def _short(error: BaseException | str) -> str:
    text = error if isinstance(error, str) else f"{type(error).__name__}: {error}"
    return text if len(text) <= _ERROR_CHARS else text[:_ERROR_CHARS] + "…"


def _day(moment: datetime) -> date:
    return moment.astimezone(LONDON).date()


def _posted_at(post: Post) -> datetime:
    """When the Reel went out: the claim time (the posts table has no ``posted_at``), else its slot."""
    return post.claimed_at or post.scheduled_for


def _records(clip: Clip) -> list[Any]:
    """The clip's ``story_reshares`` as stored (a value that is not a list reads as none)."""
    raw = clip.features.get(RESHARES)
    return list(raw) if isinstance(raw, list) else []


def _times(clip: Clip, post: Post) -> list[datetime]:
    """When the clip's Reel ``post`` was re-shared, whatever the outcome (a record with no readable ``at`` is not placed)."""
    out: list[datetime] = []
    for record in _records(clip):
        if not isinstance(record, dict) or record.get("post_id") != post.id or not isinstance(record.get("at"), str):
            continue
        try:
            at = datetime.fromisoformat(record["at"])
        except ValueError:
            continue
        if at.tzinfo is not None:
            out.append(at)
    return out


def _history(store: Store, account: Account, now: datetime) -> list[tuple[Post, Clip]]:
    """The account's posted Reels that could still matter (posted within ``LOOK_BACK``) with their clips, read fresh."""
    rows: list[tuple[Post, Clip]] = []
    for post in store.list_posts(account_id=account.id, status=PostStatus.posted):
        if now - _posted_at(post) > LOOK_BACK:
            continue
        clip = store.get_clip(post.clip_id)
        if clip is not None:
            rows.append((post, clip))
    return rows


def _shared_today(history: list[tuple[Post, Clip]], today: date) -> list[str]:
    """The ids of the account's clips that were re-shared (or claimed) on London day ``today``."""
    return [clip.id for post, clip in history if any(_day(at) == today for at in _times(clip, post))]


def _rests(clip: Clip, post: Post, now: datetime) -> bool:
    return any(now - at < COOLDOWN for at in _times(clip, post))


def _ineligible(post: Post, clip: Clip, now: datetime) -> str | None:
    """Why this Reel cannot be re-shared (None: it can); see the module docstring."""
    if not (post.url and post.url.strip()):
        return "not confirmed live yet (no url)"
    age = now - _posted_at(post)
    if age < MIN_AGE:
        return "under 20 hours old"
    if age > MAX_AGE:
        return "over 14 days old"
    video = clip.features.get("story_path")
    if not isinstance(video, str) or not video.strip():
        return "no story video"
    if clip.features.get("music") == "in_app":
        return "a silent in_app master"
    if clip.features.get("trial_reel"):
        return "a Trial Reel"
    return None


def _views(store: Store, post: Post) -> int:
    """The post's views at its latest reading (``snapshots_for`` is oldest first); no reading, or one without views, is 0."""
    readings = store.snapshots_for(post.id)
    return int(readings[-1].views or 0) if readings else 0


def _plan(store: Store, now: datetime, config: ReachConfig) -> tuple[list[Pick], list[dict[str, Any]]]:
    """Who gets a re-share right now, and why the others do not (nothing is written)."""

    def stop(reason: str) -> tuple[list[Pick], list[dict[str, Any]]]:
        return [], [{"account": None, "reason": reason}]

    if not config.stories:
        return stop(f"{STORIES_OFF} (config/scan.json reach.stories): nothing is re-shared")
    if store.get_settings().kill_switch:
        return stop("the kill switch is on: nothing is posted")
    local = now.astimezone(LONDON)
    if not FIRST_HOUR <= local.hour < LAST_HOUR:
        return stop(f"outside 11:00-22:00 London ({local:%H:%M} now): nothing is re-shared")
    live = _live_characters(store)
    picks: list[Pick] = []
    skipped: list[dict[str, Any]] = []
    for account in store.accounts():
        if account.platform is not Platform.instagram or account.character_slug not in live:
            continue  # TikTok has no Story; a character who is not live posts nothing
        if not account.postiz_integration_id:
            skipped.append({"account": account.handle, "reason": "no Postiz integration"})
            continue
        history = _history(store, account, now)
        if done := _shared_today(history, _day(now)):
            skipped.append({"account": account.handle, "reason": f"already re-shared today (clip {done[0]}): one per account per day"})
            continue
        why: Counter[str] = Counter()
        best: tuple[tuple[int, datetime, str], Post, Clip] | None = None
        for post, clip in history:
            reason = _ineligible(post, clip, now) or ("re-shared in the last 72 hours" if _rests(clip, post, now) else None)
            if reason is not None:
                why[reason] += 1
                continue
            rank = (_views(store, post), _posted_at(post), post.id or "")  # most views, then the more recent post
            if best is None or rank > best[0]:
                best = (rank, post, clip)
        if best is None:
            detail = ", ".join(f"{n} {reason}" for reason, n in why.most_common()) or "no Reel posted in the last 15 days"
            skipped.append({"account": account.handle, "reason": f"no eligible clip ({detail})"})
        else:
            picks.append(Pick(account, best[1], best[2], best[0][0]))
    return picks, skipped


def _line(pick: Pick) -> dict[str, Any]:
    return {"account": pick.account.handle, "clip_id": pick.clip.id, "post_id": pick.post.id, "views": pick.views}


def preview_reshare(store: Store, now: datetime, *, reach: ReachConfig | None = None) -> dict[str, Any]:
    """What ``reshare_stories`` would do right now (``--dry-run``): nothing is claimed or written, no storage or publisher needed."""
    require_aware(now, "preview_reshare(now)")
    config = load_reach() if reach is None else reach
    picks, skipped = _plan(store, now, config)
    return {"dry_run": True, "reshared": [], "would_reshare": [_line(p) for p in picks], "skipped": skipped, "errors": []}


def reshare_stories(
    store: Store, storage: Storage, publisher: Publisher, now: datetime, *, reach: ReachConfig | None = None
) -> dict[str, Any]:
    """Run the daily re-share once; see the module docstring. ``now`` is aware; ``reach`` as in ``publish_due``."""
    require_aware(now, "reshare_stories(now)")
    config = load_reach() if reach is None else reach
    picks, skipped = _plan(store, now, config)
    out: dict[str, Any] = {"reshared": [], "skipped": skipped, "errors": []}
    for pick in picks:
        try:
            _reshare_one(store, storage, publisher, pick, now, out)
        except Exception as e:  # noqa: BLE001 - one account must never stop the rest
            out["errors"].append({"clip_id": pick.clip.id, "error": _short(e)})
    return out


def _reshare_one(store: Store, storage: Storage, publisher: Publisher, pick: Pick, now: datetime, out: dict[str, Any]) -> None:
    """Claim the account's re-share, send it, record the outcome. Never raises for a Postiz failure (it is recorded)."""
    record: dict[str, Any] = {"at": now.isoformat(), "post_id": pick.post.id, "status": "posting"}
    try:
        taken = _claim(store, pick, record, now)
    except Exception as e:  # noqa: BLE001 - without its claim a re-share could be sent twice: none is sent
        out["errors"].append({"clip_id": pick.clip.id, "error": _short(f"the re-share could not be claimed, so none was sent: {_short(e)}")})
        return
    if taken is not None:
        out["skipped"].append({"account": pick.account.handle, "reason": taken})
        return
    try:
        story = publisher.publish_story(
            integration_id=pick.account.postiz_integration_id or "",
            media_url=storage.signed_url(MASTER_BUCKET, str(pick.clip.features["story_path"])),  # the Story video, never the master
            ai_label=True,
        )
        outcome: dict[str, Any] = {"status": "posted", "platform_post_id": story.platform_post_id}
    except UncertainPublish as e:  # it may exist: a human looks, never a resend
        outcome = {"status": "needs_check", "error": _short(e)}
    except Exception as e:  # noqa: BLE001 - a failed re-share is recorded, never retried that day
        outcome = {"status": "failed", "error": _short(e)}
    try:
        _settle(store, pick.clip.id, record, outcome)
    except Exception as e:  # noqa: BLE001 - the claim stays "posting": it holds the day, a human looks
        out["errors"].append({"clip_id": pick.clip.id, "error": _short(f"the re-share's outcome was not written: {_short(e)}")})
        outcome = {**outcome, "record_error": _short(e)}
    out["reshared"].append({**_line(pick), **outcome})


def _claim(store: Store, pick: Pick, record: dict[str, Any], now: datetime) -> str | None:
    """Write ``record`` (status ``posting``) on the clip. None when it is claimed; otherwise why it is not (the day was taken)."""
    with store.transaction():
        # The store has no locking read of a clip, so the claim queues on the settings row lock (``get_settings`` inside a
        # transaction is ``FOR UPDATE`` on Postgres), and the day's count is read again under it: two runs never both claim.
        store.get_settings()
        if done := _shared_today(_history(store, pick.account, now), _day(now)):
            return f"already re-shared today (clip {done[0]}): another run was first"
        clip = store.get_clip(pick.clip.id)
        if clip is None:
            raise KeyError(pick.clip.id)
        store.update_clip(clip.id, features={**clip.features, RESHARES: [*_records(clip), record]})
        return None


def _settle(store: Store, clip_id: str, record: dict[str, Any], outcome: dict[str, Any]) -> None:
    """Replace the claimed record (same ``at`` and ``post_id``, still ``posting``) with its outcome, under the same lock."""
    with store.transaction():
        store.get_settings()
        clip = store.get_clip(clip_id)
        if clip is None:
            raise KeyError(clip_id)
        records = [
            {**record, **outcome}
            if isinstance(r, dict) and r.get("at") == record["at"] and r.get("post_id") == record["post_id"] and r.get("status") == "posting"
            else r
            for r in _records(clip)
        ]
        store.update_clip(clip_id, features={**clip.features, RESHARES: records})
