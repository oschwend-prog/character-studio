"""``studio publish confirm``: did Postiz really publish what it accepted?

``publish_due`` marks a post (and, once all its posts are in, its clip) ``posted`` the moment Postiz accepts the create call and returns
an id. Postiz then publishes to the platform on its own, later, and can fail there: Franz's Instagram post of 13 Oct 2026 shows
``state: "ERROR"``, ``error: null``, ``releaseURL: null`` in ``postiz posts:list`` while the database said ``posted``, and nothing ever
looked, so a broken channel would have "posted" silently for days. This step looks. It runs at the end of every publish run and before
every metrics pull (the two workflows), and by hand.

**What it asks about.** Every post that is ``posted``, has a ``platform_post_id`` (the Postiz post id), has no ``url`` yet and whose
``scheduled_for`` is within the last 14 days (``CONFIRM_WINDOW``). ONE ``postiz posts:list`` call, over a date range that covers all of
them (``PostizPublisher.list_posts``); no post to ask about means no call at all. Each post is matched to Postiz's list by its id and
judged by Postiz's ``state``:

* ``PUBLISHED``: the post's ``url`` becomes Postiz's ``releaseURL`` and the Postiz id stays. Settled: it is not asked about again. A
  ``PUBLISHED`` entry with no ``releaseURL`` yet is left alone (``waiting``) and asked about again.
* ``ERROR``: Postiz could not publish it. The post becomes ``failed`` with one plain line as its error (Postiz's own detail in it when
  there is one, cut short): "Postiz could not publish it on <platform> (state ERROR, Postiz post <id>: <detail>): check the channel in
  Postiz, then `studio publish resolve <post> --retry`". ``studio health`` lists a ``failed`` post with that error, so it shows up
  without anything else. Then, **when the post never went out** (it holds no metrics snapshot: a reading means the platform showed it),
  its Postiz id is cleared, as for any post that was never live (``resolve --drop`` refuses a post with an id or a snapshot; the id
  stays in the error line), and **when no other post of the clip is live** the clip goes back from ``posted`` to ``scheduled``
  (``clips.unpost_clip``, the one exception to "``posted`` is final", used by this step only), so the existing
  ``studio publish resolve <post> --retry`` (which wants a ``scheduled`` clip) can send the post again. ``--drop`` works too. A post
  with a snapshot stays as it is, id included, and its clip stays ``posted``: it was live once, so a human decides.
* any other state (``QUEUE``, ...) or the post missing from Postiz's list: nothing is written; a later run asks again. A post whose
  Postiz id is missing for MORE than 24 hours after its slot (``MISSING_AFTER``) becomes ``needs_check`` with a clear error (it may be
  live; deleted in Postiz, or posted from a Postiz we cannot see): ``studio health`` lists it and a human settles it with
  ``studio publish resolve``. Its clip is not touched.

**Safe to run any time, and idempotent.** A ``failed`` / ``needs_check`` post, one with a url, one past 14 days is never asked about, so a
second run changes nothing and, with nothing left to ask, calls nothing. A failing ``posts:list`` (the CLI missing, a timeout, a
non-zero exit, output that is not the expected JSON) never raises out of the step: it is logged as a warning and reported as ``error`` in the
summary, nothing is written, and the next run tries again. One post's failed database write never stops the others: it is listed under
``write_errors``, the post is left as it was and the next run asks again.

The summary (printed as JSON by ``studio publish confirm``): ``confirmed`` (``post_id``, ``platform_post_id``, ``url``), ``failed``
(``post_id``, ``platform_post_id``, ``state``, ``error``, ``clip_reopened``), ``needs_check`` (``post_id``, ``platform_post_id``,
``error``), ``waiting`` (``post_id``, ``platform_post_id``, ``state``, ``reason``), ``error`` (``None``, or why ``posts:list`` failed) and
``write_errors`` (``post_id``, ``error``). The command exits 0 whatever Postiz did, and 1 only when a database write failed (2 for a missing
``DATABASE_URL`` / ``POSTIZ_API_KEY`` / ``postiz`` CLI, as for ``publish due``).
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from typing import Any, Protocol

from studio.clips import IllegalTransition, unpost_clip
from studio.models import ClipState, Post, PostStatus
from studio.store import Store, require_aware

log = logging.getLogger("studio.publish.confirm")

CONFIRM_WINDOW = timedelta(days=14)  # a post older than this (by its slot) is no longer asked about
MISSING_AFTER = timedelta(hours=24)  # a post Postiz does not list for longer than this after its slot needs a human
LOOK_BACK = timedelta(days=1)  # the asked range starts this long before the earliest slot (Postiz dates a post when it was created)
LOOK_AHEAD = timedelta(days=1)  # ... and ends this long after now
_DETAIL_CHARS = 100
_ERROR_CHARS = 500


class PostLister(Protocol):
    """What the step needs from Postiz: ``PostizPublisher.list_posts`` (a fake in tests)."""

    def list_posts(self, start: datetime, end: datetime) -> list[dict[str, Any]]: ...


def confirm_posts(store: Store, postiz: PostLister, now: datetime) -> dict[str, Any]:
    """Ask Postiz about every accepted-but-unconfirmed post, once; see the module docstring. ``now`` is aware."""
    require_aware(now, "confirm_posts(now)")
    out: dict[str, Any] = {
        "confirmed": [], "failed": [], "needs_check": [], "waiting": [], "error": None, "write_errors": [],
    }  # fmt: skip
    cutoff = now - CONFIRM_WINDOW
    asked = sorted(
        (
            p for p in store.list_posts(status=PostStatus.posted)
            if p.platform_post_id and not p.url and p.scheduled_for >= cutoff
        ),
        key=lambda p: (p.scheduled_for, p.id or ""),
    )  # fmt: skip
    if not asked:
        return out
    try:
        listed = postiz.list_posts(asked[0].scheduled_for - LOOK_BACK, now + LOOK_AHEAD)
    except Exception as e:  # noqa: BLE001 - a Postiz hiccup must never stop a publish run or a metrics pull
        out["error"] = _short(f"{type(e).__name__}: {e}")
        log.warning("could not read Postiz's posts, nothing confirmed this run: %s", out["error"])
        return out
    by_id = {str(entry["id"]): entry for entry in listed if entry.get("id")}
    platforms = {a.id: a.platform.value for a in store.accounts()}
    for post in asked:
        try:
            _settle(store, post, by_id.get(post.platform_post_id), platforms.get(post.account_id, "the platform"), now, out)
        except Exception as e:  # noqa: BLE001 - one post must never stop the rest; it is asked about again next run
            out["write_errors"].append({"post_id": post.id, "error": _short(f"{type(e).__name__}: {e}")})
    return out


def _settle(
    store: Store, post: Post, entry: dict[str, Any] | None, platform: str, now: datetime, out: dict[str, Any]
) -> None:
    """Apply what Postiz says (``entry``, or None when it does not list the post) to one post."""
    postiz_id = post.platform_post_id
    if entry is None:
        if now - post.scheduled_for > MISSING_AFTER:
            error = _short(
                f"Postiz does not list this post (Postiz post {postiz_id}) more than 24 hours after its slot: look in Postiz and "
                f"on {platform} whether it is live, then settle it with `studio publish resolve {post.id}`"
            )
            store.update_post(post.id, status=PostStatus.needs_check, error=error)
            out["needs_check"].append({"post_id": post.id, "platform_post_id": postiz_id, "error": error})
        else:
            out["waiting"].append(_waiting(post, None, "Postiz does not list it (yet)"))
        return
    state = str(entry.get("state") or "")
    if state.upper() == "PUBLISHED":
        url = entry.get("releaseURL")
        if isinstance(url, str) and url.strip():
            store.update_post(post.id, url=url.strip())
            out["confirmed"].append({"post_id": post.id, "platform_post_id": postiz_id, "url": url.strip()})
        else:
            out["waiting"].append(_waiting(post, state, "Postiz says PUBLISHED but gives no releaseURL yet"))
    elif state.upper() == "ERROR":
        _fail(store, post, entry, platform, out)
    else:
        out["waiting"].append(_waiting(post, state or None, f"Postiz says {state}" if state else "Postiz gives no state"))


def _fail(store: Store, post: Post, entry: dict[str, Any], platform: str, out: dict[str, Any]) -> None:
    """Postiz could not publish the post: fail it, and (when it never went out) give its clip back to ``resolve --retry``."""
    detail = _detail(entry.get("error"))
    error = (
        f"Postiz could not publish it on {platform} (state ERROR, Postiz post {post.platform_post_id}"
        + (f": {detail}" if detail else "")
        + f"): check the channel in Postiz, then `studio publish resolve {post.id} --retry`"
    )
    with store.transaction():  # the post and its clip move together
        never_live = not store.snapshots_for(post.id)
        store.update_post(
            post.id, status=PostStatus.failed, error=error,
            **({"platform_post_id": None} if never_live else {}),
        )  # fmt: skip
        reopened = False
        clip = store.get_clip(post.clip_id) if never_live else None
        if clip is not None and clip.state is ClipState.posted:
            try:
                unpost_clip(store, clip.id)
                reopened = True
            except IllegalTransition:
                pass  # another post of the clip is live: the clip stays posted
    out["failed"].append(
        {
            "post_id": post.id, "platform_post_id": post.platform_post_id, "state": "ERROR", "error": error,
            "clip_reopened": reopened,
        }  # fmt: skip
    )


def _waiting(post: Post, state: str | None, reason: str) -> dict[str, Any]:
    return {"post_id": post.id, "platform_post_id": post.platform_post_id, "state": state, "reason": reason}


def _detail(error: Any) -> str:
    """Postiz's own error for the post as one short line ('' when it gave none)."""
    if error is None or error == "":
        return ""
    text = error if isinstance(error, str) else json.dumps(error, ensure_ascii=False, default=str)
    text = " ".join(text.split())
    return text if len(text) <= _DETAIL_CHARS else text[:_DETAIL_CHARS].rstrip() + "…"


def _short(text: str) -> str:
    return text if len(text) <= _ERROR_CHARS else text[:_ERROR_CHARS] + "…"
