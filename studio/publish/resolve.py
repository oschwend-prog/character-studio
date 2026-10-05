"""``studio publish resolve``: a human settles a post the publisher could not.

A post ends in ``needs_check`` when the platform may have accepted it (a timeout, a 5xx, a stale claim)
and in ``failed`` after three refused attempts. Neither is retried by the machine, and until now nothing
in the CLI could move them. After looking at the platform, the owner picks exactly one:

* ``--live --platform-post-id ID [--url URL]``: it is live. The post becomes ``posted`` (id and url
  recorded, the error cleared) and, when it was the clip's last unsettled post, the clip moves to
  ``posted`` too (the next publish run would reconcile it anyway).
* ``--retry [--at ISO]``: it is not live, send it again. Only from ``needs_check`` / ``failed``, and only
  while the clip is still ``scheduled``. The post goes back to ``scheduled`` (attempts 0, error and
  claim cleared) at ``--at`` (no offset = London) or its old time, so the next 15-minute run publishes it.
* ``--drop --reason-file F``: forget it. The never-posted row is deleted (refused when it has a platform
  id or any metrics snapshot: it was live). A clip left with no posts at all moves ``scheduled ->
  rejected`` with the reason; a clip with other posts stays as it is.

Only ``needs_check`` and ``failed`` posts can be resolved: a ``scheduled`` one is not stuck, a ``posting``
one is in flight (it turns ``needs_check`` after 30 minutes), a ``posted`` one is settled. A wrong call
changes nothing. Every function is one transaction.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from studio.clips import transition
from studio.models import ClipState, Post, PostStatus
from studio.store import Store, require_aware

RESOLVABLE = (PostStatus.needs_check, PostStatus.failed)


def _stuck_post(store: Store, post_id: str) -> Post:
    post = next(iter(store.list_posts(id=post_id)), None)
    if post is None:
        raise KeyError(post_id)
    if post.status not in RESOLVABLE:
        raise ValueError(
            f"post {post.id} is {post.status.value}: only a needs_check or failed post can be resolved"
        )
    return post


def _all_posted(store: Store, clip_id: str) -> bool:
    posts = store.list_posts(clip_id=clip_id)
    return bool(posts) and all(p.status is PostStatus.posted for p in posts)


def resolve_live(
    store: Store, post_id: str, platform_post_id: str, url: str | None = None
) -> dict[str, Any]:
    """The post is live on the platform: record it as ``posted``."""
    platform_post_id = platform_post_id.strip()
    if not platform_post_id:
        raise ValueError("--platform-post-id is required with --live (metrics are pulled by it)")
    with store.transaction():
        post = _stuck_post(store, post_id)
        post = store.update_post(
            post.id, status=PostStatus.posted, platform_post_id=platform_post_id, url=url or None,
            error=None,
        )
        clip = store.get_clip(post.clip_id)
        clip_posted = False
        if clip is not None and clip.state is ClipState.scheduled and _all_posted(store, clip.id):
            transition(store, clip.id, ClipState.posted)
            clip_posted = True
    return {"post": post, "clip_posted": clip_posted}


def resolve_retry(store: Store, post_id: str, at: datetime | None = None) -> dict[str, Any]:
    """The post is not live: send it again at ``at`` (or its old time)."""
    if at is not None:
        require_aware(at, "resolve_retry(at)")
    with store.transaction():
        post = _stuck_post(store, post_id)
        clip = store.get_clip(post.clip_id)
        if clip is None or clip.state is not ClipState.scheduled:
            state = clip.state.value if clip else "missing"
            raise ValueError(
                f"clip {post.clip_id} is {state}, not scheduled: the publisher would refuse the post"
            )
        post = store.update_post(
            post.id, status=PostStatus.scheduled, claimed_at=None, attempts=0, error=None,
            scheduled_for=at or post.scheduled_for,
        )
    return {"post": post}


def resolve_drop(store: Store, post_id: str, reason: str) -> dict[str, Any]:
    """Forget a post that never went out: delete the row; reject a clip left with no posts."""
    reason = reason.strip()
    if not reason:
        raise ValueError("--reason-file is empty: say why the post is dropped")
    with store.transaction():
        post = _stuck_post(store, post_id)
        if post.platform_post_id or store.snapshots_for(post.id):
            raise ValueError(
                f"post {post.id} has a platform id or a metrics snapshot: it was "
                "live, resolve it with --live instead of dropping it"
            )
        store.delete_post(post.id)
        clip = store.get_clip(post.clip_id)
        state = clip.state if clip is not None else None
        if clip is not None and clip.state is ClipState.scheduled and not store.list_posts(clip_id=clip.id):
            state = transition(store, clip.id, ClipState.rejected, reject_reason=reason).state
    return {"dropped": post.id, "clip_id": post.clip_id, "clip_state": state.value if state else None,
            "reason": reason}  # fmt: skip
