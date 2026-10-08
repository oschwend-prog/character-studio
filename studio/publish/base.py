"""Idempotent publishing: claim due posts, hand each clip master to a ``Publisher``, record the outcome.

``publish_due(store, storage, publisher, now)`` is the whole job (``studio publish due``, on GitHub Actions: every
15 minutes through the 17:00-20:59 UTC posting window, at 11:30 and 12:30 UTC for the midday slot, and every 3 hours otherwise). The rules, in the order they run:

0. **Reconcile.** A clip still ``scheduled`` whose posts are ALL ``posted`` moves to ``posted``: this
   heals a crash between the post write and the clip transition. It never publishes anything.
1. **Stale claims.** A post in ``posting`` whose ``claimed_at`` is more than 30 minutes before
   ``now`` (or missing) becomes ``needs_check`` and is never retried automatically: the process that
   claimed it may have reached the platform before it died, so only a human can say whether the
   post is live. This runs *before* the claim, so a fresh claim is never judged stale.
1b. **Kill switch.** With ``Settings.kill_switch`` on ("stop all new spend and posting") nothing is claimed
   or published: the summary comes back with ``paused: true``, every due post stays ``scheduled`` and goes
   out on the first run after the switch is lifted. Reconcile and stale handling above still ran, they
   publish nothing.
2. **Claim.** ``store.claim_due_posts(now)`` atomically flips due ``scheduled`` posts to ``posting``
   (one runner per post), earliest first.
3. **Per post**, one at a time:

   * the clip must still be ``scheduled`` (a rejected or dropped clip is never published; the post
     fails at once with the reason and no attempt is spent);
   * **a silent master never goes out on autopilot.** A clip with ``features.music == "in_app"`` carries a
     silent track (the owner adds the song in the Instagram app); a post of it to an account in ``auto`` mode
     would be posted with no sound, so it fails at once like the case above, with a reason that says so (the
     terminal shows failed posts as an alert). An approval-mode account is not guarded: the owner approved it;
   * **at most 2 posted per account per London day.** A third due post goes back to ``scheduled``
     at that account's character's first *free* cadence slot after today (``planning.free_slot``: the
     first cadence day, from tomorrow, on which the account has no post in ``scheduled`` / ``posting`` /
     ``posted`` / ``needs_check``, so a deferral never stacks a second post on a taken day, and none within 13 days of a
     post of another clip of the same family: ``planning.family_days``). A
     ``needs_check`` post counts like a posted one: it may well be live, and so does a fresh ``posting``
     post (claimed within the last 30 minutes: another runner has it in flight). The in-run counter is
     bumped as soon as the publisher returns, before any database write, so a lost write cannot let a
     third post out in that run.
     The day of a posted post is the London date of its ``claimed_at`` (the posts table has no
     ``posted_at``), falling back to ``scheduled_for``;
   * the master's signed URL goes to ``publisher.publish(..., ai_label=True)`` (never without the AI
     label), with the post's **reach pack** (``studio.publish.reach.plan_post``, terminal v3 spec section 11): the clip's hashtags
     as stored (its series tag was written into them when the clip was made) and, for an Instagram Reel, the clip's first
     comment, its collaborators (live characters only, at most 3) and the account's Trial Reel switch;
   * success: the post is ``posted`` with the platform id and URL; the clip's learning tags ``first_comment_posted`` and
     ``trial_reel`` are written (``clips.set_publish_tags``: an Instagram Reel writes both, a TikTok post only the ones the clip
     does not carry yet, so it never undoes its Reel's); an Instagram Reel is followed by its **Story** (below); and the clip
     moves to ``posted`` (through ``clips.transition``) once **all** its posts are ``posted``;
   * an exception: ``attempts + 1``, back to ``scheduled`` with ``claimed_at = None`` while
     ``attempts < 3``, else ``failed``; the error text is kept (500 characters);
   * ``UncertainPublish``: the platform may have accepted the post, so it goes to ``needs_check`` at
     once, like a stale claim, and is never retried.

**A post is only ever sent back to ``scheduled`` when the publisher itself raised.** Anything that
goes wrong *after* the publisher returned (the database write recording the success, the clip move)
is reported under ``errors`` and leaves the post in ``posting``: 30 minutes later it becomes
``needs_check``. That is the whole crash story: a post can be late or need a human, never be posted
twice. One post's failure never stops the others.

**The Story after a Reel** (terminal v3 spec section 11, item 2; task 8 fix 1). Only with ``reach.stories`` on
(``config/scan.json``, off by default). Right after an Instagram Reel is recorded ``posted``, ``publisher.publish_story`` posts the
clip's **labelled Story video** as a Story: ``features['story_path']``, the master with the AI label burned into the picture
(``master.render_story``), signed from bucket ``clips`` and uploaded on its own. A Story shows no caption, so it is never the
plain master: a clip without that file gets no Story ("no labelled story video"). The Story is not a post row (``posts`` holds
one row per clip and account): it is recorded on the clip as ``features['story']`` = ``{post_id (the Reel's), status, at, ...}``,
and that record is what keeps it to one:

* it is **claimed first**: ``status: posting`` is written before Postiz is asked, and only when the clip has no ``story`` yet.
  A clip that already has one (any status) never gets another; a claim that cannot be written means no Story at all;
* then ``posted`` (with ``platform_post_id`` / ``url``), ``failed`` (Postiz refused, or anything else that raised: the error is
  kept) or ``needs_check`` (``UncertainPublish``: it may exist). **A failed Story is never retried**, on this run or a later one:
  a Story lives 24 hours, a late one is worth little, and a resend could double one that went out after all. A claim left in
  ``posting`` (the process died) stays as it is, like a stale post: a human looks;
* ``skipped`` (with the ``reason``, ``PostPlan.story_skip``): Stories are off; a silent master (``music: in_app``: the owner adds
  the song to the Reel in the app; a Story of it would go out silent on autopilot); a Trial Reel (it is shown to non-followers
  first, and a Story would show it to the followers before it graduates); no labelled Story video;
* it is **not counted** toward the 2-a-day cap (it is not a feed post: ``_posted_counts`` reads post rows only), and **a Story
  never fails, retries or holds up its Reel**: whatever happens to it lands in the summary's ``stories``, never in ``errors``.
  No Story follows a Reel that failed, is uncertain or whose ``posted`` write was lost, a TikTok post, or a Reel settled by hand
  (``studio publish resolve --live``): a Story is only ever sent right after its Reel, in the same run.

``publish_due`` returns a JSON-friendly summary: ``paused`` (the kill switch is on), ``stale``, ``posted`` (each with its
``reach``: what went with it), ``retry``, ``failed``, ``rescheduled``, ``needs_check`` (each a list of dicts with a ``post_id``),
``stories`` (one per Instagram Reel posted: ``post_id`` of the Reel, ``clip_id``, ``status`` and its details), ``clips_posted``
(clip ids, reconciled ones included) and ``errors`` (outcomes that could not be recorded, each with a ``post_id`` or a
``clip_id``; the CLI exits 1 on any).
``preview_due(store, now)`` is the read-only twin behind ``--dry-run``: same decisions, nothing
claimed or written, no storage or publisher needed; each post it would send shows its hashtags and its ``reach``.
Both take ``reach`` (``studio.publish.reach.ReachConfig``), read from ``config/scan.json`` and the characters' ``refs.json``
(``load_reach``) when it is not given.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any, Protocol, runtime_checkable

from studio.clips import set_publish_tags, transition
from studio.config import LONDON
from studio.models import Account, Clip, ClipState, Platform, Post, PostStatus
from studio.planning import family_days, free_slot, taken_days
from studio.publish.reach import NO_REACH, PostPlan, Reach, ReachConfig, load_reach, plan_post
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
        reach: Reach = NO_REACH,
    ) -> PublishResult: ...

    def publish_story(self, *, integration_id: str, media_url: str, ai_label: bool) -> PublishResult:
        """A Story of ``media_url``: the clip's labelled Story video (never the master: a Story shows no caption)."""
        ...


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
    midnight = datetime.combine(after + timedelta(days=1), time(0), tzinfo=LONDON)
    return free_slot(character_slug, midnight, cadence, set())


def _deferred_slot(
    store: Store,
    account: Account,
    post: Post,
    today: date,
    cadence: Any,
    extra: dict[str, set[date]],
) -> datetime:
    """Where a post that hit the daily cap goes: the first free cadence slot after today, else tomorrow.

    Free = a day on which the account has no post that holds a slot (``planning.taken_days``), not within 13 days of a post of
    another clip of the post's family (``planning.family_days``, terminal v3: the same rule as scheduling), and not one of the
    days this run already deferred other posts of the account to (``extra``: a dry run writes nothing).
    """
    taken = taken_days(store, [account.id]) | family_days(store, post.clip_id) | extra.get(account.id, set())
    midnight = datetime.combine(today + timedelta(days=1), time(0), tzinfo=LONDON)
    try:
        target = free_slot(account.character_slug, midnight, cadence, taken)
    except ValueError:  # no slot or no free cadence day configured: tomorrow, at the post's own time
        wall = post.scheduled_for.astimezone(LONDON).timetz()
        target = datetime.combine(today + timedelta(days=1), wall)
    extra.setdefault(account.id, set()).add(target.astimezone(LONDON).date())
    return target


def _posted_counts(store: Store, day: date, now: datetime) -> Counter[str]:
    """Posts per account that count against the cap on ``day``: posted, possibly live, or in flight.

    In flight = ``posting`` and claimed within ``STALE_AFTER``: another runner is publishing it right
    now. A stale ``posting`` post is not counted here: it is flagged ``needs_check`` first (which counts).
    """
    counts: Counter[str] = Counter()
    for status in (PostStatus.posted, PostStatus.needs_check):
        for post in store.list_posts(status=status):
            if _post_day(post) == day:
                counts[post.account_id] += 1
    cutoff = now - STALE_AFTER
    for post in store.list_posts(status=PostStatus.posting):
        if post.claimed_at is not None and post.claimed_at >= cutoff and _post_day(post) == day:
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
    if account.mode == "auto" and clip.features.get("music") == "in_app":
        return REFUSE, (
            f"silent master: the clip's music is in_app (the song is added by hand in the app), but "
            f"{account.handle} is on autopilot, so it would go out with no sound. Add the song in the app "
            "yourself, or remake the clip with an AI beat (music ai_beat)"
        )
    if posted_today >= DAILY_CAP:
        return DEFER, f"{account.handle} already has {DAILY_CAP} posts today"
    return PUBLISH, ""


def _live_characters(store: Store) -> frozenset[str]:
    """The slugs of the characters who are ``live``: the only possible collaborators of a Reel (``reach.plan_post``)."""
    return frozenset(c.slug for c in store.characters() if c.status == "live")


def _short(error: BaseException | str) -> str:
    text = error if isinstance(error, str) else f"{type(error).__name__}: {error}"
    return text if len(text) <= _ERROR_CHARS else text[:_ERROR_CHARS] + "…"


# ---- the job -------------------------------------------------------------------------------------


def publish_due(
    store: Store, storage: Storage, publisher: Publisher, now: datetime, *, reach: ReachConfig | None = None
) -> dict[str, Any]:
    """Run the publish job once; see the module docstring for the rules. Returns the summary.

    ``reach`` is the reach pack's config (``load_reach()`` from the repo's files when not given): read before anything is
    claimed, so a broken one (``ValueError``) stops the run with nothing touched."""
    require_aware(now, "publish_due(now)")
    config = load_reach() if reach is None else reach
    out: dict[str, Any] = {
        "paused": False, "stale": [], "posted": [], "retry": [], "failed": [],
        "rescheduled": [], "needs_check": [], "stories": [], "clips_posted": [], "errors": [],
    }  # fmt: skip

    _reconcile_clips(store, out)

    for post in stale_posts(store, now):
        reason = (
            f"stuck in posting since {post.claimed_at}: not retried, check the platform "
            "and settle it by hand"
        )
        store.update_post(post.id, status=PostStatus.needs_check, error=reason)
        out["stale"].append({"post_id": post.id, "claimed_at": post.claimed_at})

    settings = store.get_settings()
    if settings.kill_switch:  # "stop all new spend and posting": claim nothing, due posts keep waiting
        out["paused"] = True
        return out

    today = _day(now)
    cadence = settings.cadence
    accounts = {a.id: a for a in store.accounts()}
    live = _live_characters(store)
    counts = _posted_counts(store, today, now)
    deferred_days: dict[str, set[date]] = {}

    for post in store.claim_due_posts(now):
        try:
            _publish_one(
                store, storage, publisher, post, accounts, cadence, today, counts, deferred_days, out, config, now, live
            )
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
    deferred_days: dict[str, set[date]],
    out: dict[str, Any],
    config: ReachConfig,
    now: datetime,
    live: frozenset[str],
) -> None:
    account = accounts.get(post.account_id)
    clip = store.get_clip(post.clip_id)
    verdict, why = _decide(account, clip, counts[post.account_id])

    if verdict == REFUSE:
        store.update_post(post.id, status=PostStatus.failed, error=why)
        out["failed"].append({"post_id": post.id, "attempts": post.attempts, "error": why})
        return

    if verdict == DEFER:
        target = _deferred_slot(store, account, post, today, cadence, deferred_days)
        store.update_post(
            post.id, status=PostStatus.scheduled, claimed_at=None, scheduled_for=target
        )
        out["rescheduled"].append({"post_id": post.id, "to": target, "reason": why})
        return

    media_url = ""
    try:
        plan = plan_post(clip, account, accounts.values(), config, live=live)  # pure; were it to raise, nothing was sent: one attempt
        if not account.postiz_integration_id:
            raise ValueError(f"{account.handle} has no postiz_integration_id")
        if not clip.master_path:
            raise ValueError(f"clip {clip.id} has no master_path")
        media_url = storage.signed_url(MASTER_BUCKET, clip.master_path)
        result = publisher.publish(
            platform=account.platform,
            integration_id=account.postiz_integration_id,
            media_url=media_url,
            caption=clip.caption or "",
            hashtags=plan.hashtags,
            ai_label=True,
            reach=plan.reach,
        )
    except UncertainPublish as e:
        counts[account.id] += 1  # it may be live: counted before the write, which may fail
        store.update_post(post.id, status=PostStatus.needs_check, error=_short(e))
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

    # The platform said yes. From here nothing may send the post back to `scheduled`, and the post
    # counts toward the cap even if the write below fails.
    counts[account.id] += 1
    store.update_post(
        post.id,
        status=PostStatus.posted,
        platform_post_id=result.platform_post_id,
        url=result.url,
        error=None,
    )
    out["posted"].append(
        {"post_id": post.id, "platform_post_id": result.platform_post_id, "url": result.url, "reach": plan.summary()}
    )
    _record_reach(store, clip, account, plan, out)
    if account.platform is Platform.instagram:
        out["stories"].append(_follow_with_story(store, storage, publisher, post, clip, account, plan, now))
    if _all_posted(store, clip.id):
        transition(store, clip.id, ClipState.posted)
        out["clips_posted"].append(clip.id)


def _record_reach(store: Store, clip: Clip, account: Account, plan: PostPlan, out: dict[str, Any]) -> None:
    """The publisher's learning tags on the clip (see the module docstring); a lost write is reported, the post stays posted."""
    reel = account.platform is Platform.instagram
    tags = {"first_comment_posted": reel and plan.reach.first_comment is not None, "trial_reel": reel and plan.reach.trial_reel}
    try:
        set_publish_tags(store, clip.id, tags, only_missing=not reel)
    except Exception as e:  # noqa: BLE001 - the post is live: only the tag is lost
        out["errors"].append({"clip_id": clip.id, "error": _short(f"the learning tags were not written: {_short(e)}")})


def _story_marker(store: Store, clip_id: str, marker: dict[str, Any], *, claim: bool) -> bool:
    """Write ``features['story']``. ``claim``: only when the clip has none yet (False when it has one: never a second Story)."""
    with store.transaction():
        # The store has no locking read of a clip, so the claim queues on the settings row lock (``get_settings`` inside a
        # transaction is ``FOR UPDATE`` on Postgres, the lock budget reservations and drop leases use): two runners never both claim.
        store.get_settings()
        clip = store.get_clip(clip_id)
        if clip is None:
            raise KeyError(clip_id)
        if claim and clip.features.get("story") is not None:
            return False
        store.update_clip(clip_id, features={**clip.features, "story": marker})
        return True


def _follow_with_story(
    store: Store,
    storage: Storage,
    publisher: Publisher,
    post: Post,
    clip: Clip,
    account: Account,
    plan: PostPlan,
    now: datetime,
) -> dict[str, Any]:
    """The Story of a Reel that was just posted (see the module docstring). Never raises: the summary line says what happened."""
    entry: dict[str, Any] = {"post_id": post.id, "clip_id": clip.id}
    stamp = {"post_id": post.id, "at": now.isoformat()}
    try:
        if plan.story_skip is not None:
            if _story_marker(store, clip.id, {**stamp, "status": "skipped", "reason": plan.story_skip}, claim=True):
                return {**entry, "status": "skipped", "reason": plan.story_skip}
            return {**entry, "status": "skipped", "reason": "a Story of this clip is already recorded: never a second one"}
        if not _story_marker(store, clip.id, {**stamp, "status": "posting"}, claim=True):
            return {**entry, "status": "skipped", "reason": "a Story of this clip is already recorded: never a second one"}
    except Exception as e:  # noqa: BLE001 - without its claim a Story could be sent twice: none is sent
        return {**entry, "status": "failed", "error": _short(f"the Story could not be claimed, so none was sent: {_short(e)}")}

    try:
        if not plan.story_path:  # never: plan_post plans a Story only with its labelled video
            raise ValueError("no labelled story video")
        story = publisher.publish_story(
            integration_id=account.postiz_integration_id or "",
            media_url=storage.signed_url(MASTER_BUCKET, plan.story_path),  # the labelled Story video, never the master
            ai_label=True,
        )
        outcome: dict[str, Any] = {"status": "posted", "platform_post_id": story.platform_post_id, "url": story.url}
    except UncertainPublish as e:  # it may exist: a human looks, never a resend
        outcome = {"status": "needs_check", "error": _short(e)}
    except Exception as e:  # noqa: BLE001 - a failed Story never fails its Reel, and is never retried
        outcome = {"status": "failed", "error": _short(e)}
    try:
        _story_marker(store, clip.id, {**stamp, **outcome}, claim=False)
    except Exception as e:  # noqa: BLE001 - the claim stays "posting": it is never sent again, a human looks
        outcome = {**outcome, "record_error": _short(e)}
    return {**entry, **outcome}


def _reconcile_clips(store: Store, out: dict[str, Any]) -> None:
    """Move ``scheduled`` clips whose posts are all ``posted`` to ``posted`` (crash recovery)."""
    posted_clips = {p.clip_id for p in store.list_posts(status=PostStatus.posted)}
    for clip in store.list_clips(state=ClipState.scheduled):
        if clip.id not in posted_clips:
            continue
        try:
            if _all_posted(store, clip.id):
                transition(store, clip.id, ClipState.posted)
                out["clips_posted"].append(clip.id)
        except Exception as e:  # noqa: BLE001 - one clip must never stop the run
            out["errors"].append({"clip_id": clip.id, "error": _short(e)})


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


def preview_due(store: Store, now: datetime, *, reach: ReachConfig | None = None) -> dict[str, Any]:
    """What ``publish_due`` would do right now, without claiming or writing anything.

    With the kill switch on it reports ``paused: true`` and nothing would be posted, deferred or failed. A post that would go
    out shows the hashtags it would carry and its ``reach`` (``PostPlan.summary``; ``story`` is the reason when a Reel would get
    none). ``reach`` as in ``publish_due``.
    """
    require_aware(now, "preview_due(now)")
    config = load_reach() if reach is None else reach
    today = _day(now)
    settings = store.get_settings()
    cadence = settings.cadence
    accounts = {a.id: a for a in store.accounts()}
    live = _live_characters(store)
    counts = _posted_counts(store, today, now)
    deferred_days: dict[str, set[date]] = {}

    stale = stale_posts(store, now)
    for post in stale:  # they would be flagged first and count if they went out today
        if post.claimed_at is not None and _post_day(post) == today:
            counts[post.account_id] += 1

    out: dict[str, Any] = {
        "now": now,
        "paused": settings.kill_switch,
        "would_flag_needs_check": [{"post_id": p.id, "claimed_at": p.claimed_at} for p in stale],
        "would_post": [], "would_reschedule": [], "would_fail": [],
    }  # fmt: skip
    if settings.kill_switch:  # nothing would be claimed
        return out
    due = [p for p in store.list_posts(status=PostStatus.scheduled) if p.scheduled_for <= now]
    for post in due:  # list_posts is ordered by scheduled_for, like the claim
        account = accounts.get(post.account_id)
        clip = store.get_clip(post.clip_id)
        verdict, why = _decide(account, clip, counts[post.account_id])
        row = _row(post, account, clip)
        if verdict == REFUSE:
            out["would_fail"].append({**row, "reason": why})
        elif verdict == DEFER:
            target = _deferred_slot(store, account, post, today, cadence, deferred_days)
            out["would_reschedule"].append({**row, "to": target, "reason": why})
        else:
            counts[post.account_id] += 1
            plan = plan_post(clip, account, accounts.values(), config, live=live)
            out["would_post"].append({**row, "hashtags": plan.hashtags, "reach": plan.summary()})
    return out
