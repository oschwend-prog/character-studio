"""Idempotent publishing: claim due posts, hand each clip master to a ``Publisher``, record the outcome.

``publish_due(store, storage, publisher, now)`` is the whole job (``studio publish due``, every 15
minutes on GitHub Actions). The rules, in the order they run:

1. **Stale claims.** A post in ``posting`` whose ``claimed_at`` is more than 30 minutes before
   ``now`` (or missing) becomes ``needs_check`` and is never retried automatically: the process that
   claimed it may have reached the platform before it died, so only a human can say whether the
   post is live. This runs *before* the claim, so a fresh claim is never judged stale.
2. **Claim.** ``store.claim_due_posts(now)`` atomically flips due ``scheduled`` posts to ``posting``
   (one runner per post), earliest first.
3. **Per post**, one at a time:

   * the clip must still be ``scheduled`` (a rejected or dropped clip is never published; the post
     fails at once with the reason and no attempt is spent);
   * **at most 2 posted per account per London day.** A third due post goes back to ``scheduled``
     at that account's character's next cadence slot (``slot_for`` with the real
     ``Settings.cadence``, the next cadence day after today). A ``needs_check`` post counts like a
     posted one: it may well be live. The day of a posted post is the London date of its
     ``claimed_at`` (the posts table has no ``posted_at``), falling back to ``scheduled_for``;
   * the master's signed URL goes to ``publisher.publish(..., ai_label=True)`` (never without the AI
     label);
   * success: the post is ``posted`` with the platform id and URL, and the clip moves to ``posted``
     (through ``clips.transition``) once **all** its posts are ``posted``;
   * an exception: ``attempts + 1``, back to ``scheduled`` with ``claimed_at = None`` while
     ``attempts < 3``, else ``failed``; the error text is kept (500 characters);
   * ``UncertainPublish``: the platform may have accepted the post, so it goes to ``needs_check`` at
     once, like a stale claim, and is never retried.

**A post is only ever sent back to ``scheduled`` when the publisher itself raised.** Anything that
goes wrong *after* the publisher returned (the database write recording the success, the clip move)
is reported under ``errors`` and leaves the post in ``posting``: 30 minutes later it becomes
``needs_check``. That is the whole crash story: a post can be late or need a human, never be posted
twice. One post's failure never stops the others.

``publish_due`` returns a JSON-friendly summary: ``stale``, ``posted``, ``retry``, ``failed``,
``rescheduled``, ``needs_check`` (each a list of dicts with a ``post_id``), ``clips_posted`` (clip
ids) and ``errors`` (outcomes that could not be recorded; the CLI exits 1 on any).
``preview_due(store, now)`` is the read-only twin behind ``--dry-run``: same decisions, nothing
claimed or written, no storage or publisher needed.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Protocol, runtime_checkable

from studio.clips import transition
from studio.config import LONDON
from studio.models import Account, Clip, ClipState, Platform, Post, PostStatus
from studio.planning import WEEKDAYS, _cadence_days, slot_for
from studio.storage import Storage
from studio.store import Store, require_aware

MASTER_BUCKET = "clips"
MAX_ATTEMPTS = 3
DAILY_CAP = 2
STALE_AFTER = timedelta(minutes=30)
_ERROR_CHARS = 500

# What happens to a due post (see ``_decide``).
PUBLISH, DEFER, REFUSE = "publish", "defer", "refuse"


class UncertainPublish(Exception):
    """The platform may have accepted the post, but we cannot tell: never retry it."""


@dataclass
class PublishResult:
    platform_post_id: str
    url: str | None = None


@runtime_checkable
class Publisher(Protocol):
    def publish(
        self,
        *,
        platform: Platform,
        integration_id: str,
        media_url: str,
        caption: str,
        hashtags: list[str],
        ai_label: bool,
    ) -> PublishResult: ...


# ---- days, slots, caps ---------------------------------------------------------------------------


def _day(moment: datetime) -> date:
    return moment.astimezone(LONDON).date()


def _post_day(post: Post) -> date:
    """The London day a post went out (or was attempted) on."""
    return _day(post.claimed_at or post.scheduled_for)


def next_slot(character_slug: str, after: date, cadence: Any) -> datetime:
    """The character's slot on the first cadence day strictly after ``after`` (a London date).

    ``ValueError`` when the character has no slot or no usable cadence days.
    """
    days = _cadence_days(cadence.get(character_slug))
    for offset in range(1, 8):
        day = after + timedelta(days=offset)
        if WEEKDAYS[day.weekday()] in days:
            return slot_for(character_slug, day, cadence)
    raise ValueError(f"no posting days configured for {character_slug!r}")


def _deferred_slot(character_slug: str, post: Post, today: date, cadence: Any) -> datetime:
    """Where a post that hit the daily cap goes: the next cadence slot, else tomorrow, same time."""
    try:
        return next_slot(character_slug, today, cadence)
    except ValueError:
        wall = post.scheduled_for.astimezone(LONDON).timetz()
        return datetime.combine(today + timedelta(days=1), wall)


def _posted_counts(store: Store, day: date) -> Counter[str]:
    """Posts per account that count against the cap on ``day``: posted, or possibly live."""
    counts: Counter[str] = Counter()
    for status in (PostStatus.posted, PostStatus.needs_check):
        for post in store.list_posts(status=status):
            if _post_day(post) == day:
                counts[post.account_id] += 1
    return counts


def stale_posts(store: Store, now: datetime) -> list[Post]:
    """Posts stuck in ``posting`` for more than ``STALE_AFTER`` (or with no claim time at all)."""
    cutoff = now - STALE_AFTER
    return [
        p
        for p in store.list_posts(status=PostStatus.posting)
        if p.claimed_at is None or p.claimed_at < cutoff
    ]


def _decide(account: Account | None, clip: Clip | None, posted_today: int) -> tuple[str, str]:
    if account is None:
        return REFUSE, "unknown account"
    if clip is None:
        return REFUSE, "unknown clip"
    if clip.state is not ClipState.scheduled:
        return REFUSE, f"clip is {clip.state.value}, not scheduled: never published"
    if posted_today >= DAILY_CAP:
        return DEFER, f"{account.handle} already has {DAILY_CAP} posts today"
    return PUBLISH, ""


def _short(error: BaseException | str) -> str:
    text = error if isinstance(error, str) else f"{type(error).__name__}: {error}"
    return text if len(text) <= _ERROR_CHARS else text[:_ERROR_CHARS] + "…"


# ---- the job -------------------------------------------------------------------------------------


def publish_due(
    store: Store, storage: Storage, publisher: Publisher, now: datetime
) -> dict[str, Any]:
    """Run the publish job once; see the module docstring for the rules. Returns the summary."""
    require_aware(now, "publish_due(now)")
    out: dict[str, Any] = {
        "stale": [], "posted": [], "retry": [], "failed": [],
        "rescheduled": [], "needs_check": [], "clips_posted": [], "errors": [],
    }  # fmt: skip

    for post in stale_posts(store, now):
        reason = (
            f"stuck in posting since {post.claimed_at}: not retried, check the platform "
            "and settle it by hand"
        )
        store.update_post(post.id, status=PostStatus.needs_check, error=reason)
        out["stale"].append({"post_id": post.id, "claimed_at": post.claimed_at})

    today = _day(now)
    cadence = store.get_settings().cadence
    accounts = {a.id: a for a in store.accounts()}
    counts = _posted_counts(store, today)

    for post in store.claim_due_posts(now):
        try:
            _publish_one(store, storage, publisher, post, accounts, cadence, today, counts, out)
        except Exception as e:  # noqa: BLE001 - one post must never stop the rest
            # Whatever happened, the post is still `posting`: it becomes needs_check, never a retry.
            out["errors"].append({"post_id": post.id, "error": _short(e)})
    return out


def _publish_one(
    store: Store,
    storage: Storage,
    publisher: Publisher,
    post: Post,
    accounts: dict[str, Account],
    cadence: Any,
    today: date,
    counts: Counter[str],
    out: dict[str, Any],
) -> None:
    account = accounts.get(post.account_id)
    clip = store.get_clip(post.clip_id)
    verdict, why = _decide(account, clip, counts[post.account_id])

    if verdict == REFUSE:
        store.update_post(post.id, status=PostStatus.failed, error=why)
        out["failed"].append({"post_id": post.id, "attempts": post.attempts, "error": why})
        return

    if verdict == DEFER:
        target = _deferred_slot(account.character_slug, post, today, cadence)
        store.update_post(
            post.id, status=PostStatus.scheduled, claimed_at=None, scheduled_for=target
        )
        out["rescheduled"].append({"post_id": post.id, "to": target, "reason": why})
        return

    try:
        if not account.postiz_integration_id:
            raise ValueError(f"{account.handle} has no postiz_integration_id")
        if not clip.master_path:
            raise ValueError(f"clip {clip.id} has no master_path")
        result = publisher.publish(
            platform=account.platform,
            integration_id=account.postiz_integration_id,
            media_url=storage.signed_url(MASTER_BUCKET, clip.master_path),
            caption=clip.caption or "",
            hashtags=list(clip.hashtags),
            ai_label=True,
        )
    except UncertainPublish as e:
        store.update_post(post.id, status=PostStatus.needs_check, error=_short(e))
        counts[account.id] += 1  # it may be live
        out["needs_check"].append({"post_id": post.id, "error": _short(e)})
        return
    except Exception as e:  # noqa: BLE001 - any failure of the publisher is one failed attempt
        attempts = post.attempts + 1
        error = _short(e)
        if attempts < MAX_ATTEMPTS:
            store.update_post(
                post.id, status=PostStatus.scheduled, claimed_at=None, attempts=attempts, error=error
            )
            out["retry"].append({"post_id": post.id, "attempts": attempts, "error": error})
        else:
            store.update_post(post.id, status=PostStatus.failed, attempts=attempts, error=error)
            out["failed"].append({"post_id": post.id, "attempts": attempts, "error": error})
        return

    # The platform said yes. From here nothing may send the post back to `scheduled`.
    store.update_post(
        post.id,
        status=PostStatus.posted,
        platform_post_id=result.platform_post_id,
        url=result.url,
        error=None,
    )
    counts[account.id] += 1
    out["posted"].append(
        {"post_id": post.id, "platform_post_id": result.platform_post_id, "url": result.url}
    )
    if _all_posted(store, clip.id):
        transition(store, clip.id, ClipState.posted)
        out["clips_posted"].append(clip.id)


def _all_posted(store: Store, clip_id: str) -> bool:
    with store.transaction():
        posts = store.list_posts(clip_id=clip_id)
        return bool(posts) and all(p.status is PostStatus.posted for p in posts)


# ---- dry run -------------------------------------------------------------------------------------


def _row(post: Post, account: Account | None, clip: Clip | None) -> dict[str, Any]:
    return {
        "post_id": post.id,
        "clip_id": post.clip_id,
        "account_id": post.account_id,
        "handle": account.handle if account else None,
        "platform": account.platform.value if account else None,
        "integration_id": account.postiz_integration_id if account else None,
        "scheduled_for": post.scheduled_for,
        "master_path": clip.master_path if clip else None,
        "caption": clip.caption if clip else None,
        "hashtags": list(clip.hashtags) if clip else None,
    }


def preview_due(store: Store, now: datetime) -> dict[str, Any]:
    """What ``publish_due`` would do right now, without claiming or writing anything."""
    require_aware(now, "preview_due(now)")
    today = _day(now)
    cadence = store.get_settings().cadence
    accounts = {a.id: a for a in store.accounts()}
    counts = _posted_counts(store, today)

    stale = stale_posts(store, now)
    for post in stale:  # they would be flagged first and count if they went out today
        if post.claimed_at is not None and _post_day(post) == today:
            counts[post.account_id] += 1

    out: dict[str, Any] = {
        "now": now,
        "would_flag_needs_check": [{"post_id": p.id, "claimed_at": p.claimed_at} for p in stale],
        "would_post": [], "would_reschedule": [], "would_fail": [],
    }  # fmt: skip
    due = [p for p in store.list_posts(status=PostStatus.scheduled) if p.scheduled_for <= now]
    for post in due:  # list_posts is ordered by scheduled_for, like the claim
        account = accounts.get(post.account_id)
        clip = store.get_clip(post.clip_id)
        verdict, why = _decide(account, clip, counts[post.account_id])
        row = _row(post, account, clip)
        if verdict == REFUSE:
            out["would_fail"].append({**row, "reason": why})
        elif verdict == DEFER:
            target = _deferred_slot(account.character_slug, post, today, cadence)
            out["would_reschedule"].append({**row, "to": target, "reason": why})
        else:
            counts[post.account_id] += 1
            out["would_post"].append(row)
    return out
