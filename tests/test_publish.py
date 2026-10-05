"""Publishing: ``publish_due`` (claim, cap, retry, stale), the Postiz adapter and ``studio publish due``.

Everything runs on ``MemoryStore`` + ``LocalStorage``; the Postiz CLI is a fake ``run`` that records
argv, so no ``postiz`` binary, network or account is involved.
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from functools import partial
from pathlib import Path
from typing import Any

import httpx
import pytest
from typer.testing import CliRunner

from studio import publish
from studio.cli import app
from studio.config import LONDON
from studio.models import Account, Character, Clip, ClipState, Platform, Post, PostStatus, Snapshot
from studio.publish import base, postiz
from studio.publish.base import PublishResult, Publisher, UncertainPublish, preview_due, publish_due
from studio.publish.postiz import (
    INSTAGRAM_SETTINGS,
    TIKTOK_SETTINGS,
    CAPTION_LIMIT,
    PostizError,
    PostizPublisher,
    caption_length,
    compose_content,
    download_media,
)
from studio.storage import LocalStorage
from studio.store import MemoryStore

# 2026-10-06 is a Tuesday, London on BST (UTC+1). Biscuit's slot is 19:00, Reginald's 19:30.
SLOT = datetime(2026, 10, 6, 19, 0, tzinfo=LONDON)
NOW = datetime(2026, 10, 6, 20, 0, tzinfo=LONDON)
MASTER = b"\x00\x00\x00 ftypmp42 pretend-master-bytes"


# ---- helpers -----------------------------------------------------------------------------------


class FakePublisher:
    """Records every call; raises ``fail`` when set; ids are ``pz-1``, ``pz-2``..."""

    def __init__(self, fail: Exception | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self.fail = fail

    def publish(
        self,
        *,
        platform: Platform,
        integration_id: str,
        media_url: str,
        caption: str,
        hashtags: list[str],
        ai_label: bool,
    ) -> PublishResult:
        self.calls.append(
            dict(
                platform=platform,
                integration_id=integration_id,
                media_url=media_url,
                caption=caption,
                hashtags=hashtags,
                ai_label=ai_label,
            )
        )
        if self.fail is not None:
            raise self.fail
        n = len(self.calls)
        return PublishResult(platform_post_id=f"pz-{n}", url=f"https://example.test/v/{n}")


class Rig:
    """A store with both characters and their accounts, a LocalStorage and a counter of clips."""

    def __init__(self, tmp_path: Path, *, instagram: bool = False) -> None:
        accounts = [
            Account(character_slug="biscuit", platform="tiktok", handle="@biscuit.tt",
                    postiz_integration_id="int-bis-tt"),
            Account(character_slug="reginald", platform="tiktok", handle="@reginald.tt",
                    postiz_integration_id="int-reg-tt"),
        ]  # fmt: skip
        if instagram:
            accounts.append(
                Account(character_slug="biscuit", platform="instagram", handle="@biscuit.ig",
                        postiz_integration_id="int-bis-ig")
            )  # fmt: skip
        self.store = MemoryStore(
            characters=[Character(slug="biscuit", name="Biscuit"),
                        Character(slug="reginald", name="Reginald")],
            accounts=accounts,
        )  # fmt: skip
        self.storage = LocalStorage(tmp_path / "store")
        self.tmp = tmp_path
        self.n = 0

    def account(self, handle: str) -> Account:
        return next(a for a in self.store.accounts() if a.handle == handle)

    def clip(self, character: str = "biscuit", state: ClipState = ClipState.scheduled) -> Clip:
        self.n += 1
        local = self.tmp / f"master-{self.n}.mp4"
        local.write_bytes(MASTER)
        key = self.storage.upload("clips", f"masters/m{self.n}.mp4", local)
        return self.store.add_clip(
            Clip(character_slug=character, mode="recreate", state=state, master_path=key,
                 caption=f"caption {self.n}", hashtags=["oddeyes", "#ai"])
        )  # fmt: skip

    def post(
        self,
        handle: str = "@biscuit.tt",
        *,
        when: datetime = SLOT,
        clip: Clip | None = None,
        **fields: Any,
    ) -> Post:
        account = self.account(handle)
        clip = clip or self.clip(account.character_slug)
        return self.store.add_post(
            Post(clip_id=clip.id, account_id=account.id, scheduled_for=when, **fields)
        )

    def get(self, post: Post) -> Post:
        return self.store.list_posts(id=post.id)[0]

    def run(self, publisher: Publisher, now: datetime = NOW) -> dict[str, Any]:
        return publish_due(self.store, self.storage, publisher, now)


@pytest.fixture
def rig(tmp_path) -> Rig:
    return Rig(tmp_path)


def test_fake_publisher_is_a_publisher():
    assert isinstance(FakePublisher(), Publisher)


# ---- a silent master must not go out on autopilot ------------------------------------------------


def silent_clip(rig: Rig, character: str = "biscuit", music: str | None = "in_app") -> Clip:
    clip = rig.clip(character)
    return rig.store.update_clip(clip.id, features={"music": music} if music else {})


def test_a_silent_in_app_clip_is_flagged_not_posted_on_an_autopilot_account(rig):
    """music in_app = a silent master the owner finishes by hand in the app; autopilot would post it silent."""
    rig.store.update_account(rig.account("@biscuit.tt").id, mode="auto")
    p = rig.post(clip=silent_clip(rig))
    pub = FakePublisher()

    summary = rig.run(pub)

    assert pub.calls == []  # nothing left the machine
    done = rig.get(p)
    assert done.status is PostStatus.failed and done.attempts == 0  # fails at once, no attempt spent: an owner warning
    assert "silent" in done.error and "autopilot" in done.error and "in_app" in done.error
    assert [x["post_id"] for x in summary["failed"]] == [p.id]
    assert rig.store.get_clip(p.clip_id).state is ClipState.scheduled  # not posted, not moved


def test_the_dry_run_flags_the_same_post(rig):
    rig.store.update_account(rig.account("@biscuit.tt").id, mode="auto")
    p = rig.post(clip=silent_clip(rig))
    out = preview_due(rig.store, NOW)
    assert [x["post_id"] for x in out["would_fail"]] == [p.id] and "silent" in out["would_fail"][0]["reason"]
    assert out["would_post"] == []
    assert rig.get(p).status is PostStatus.scheduled  # a dry run writes nothing


@pytest.mark.parametrize("music", ["ai_beat", "original", None])
def test_clips_with_sound_in_the_file_still_post_on_autopilot(rig, music):
    rig.store.update_account(rig.account("@biscuit.tt").id, mode="auto")
    p = rig.post(clip=silent_clip(rig, music=music))  # music None = a clip made before the flag existed
    pub = FakePublisher()
    rig.run(pub)
    assert len(pub.calls) == 1 and rig.get(p).status is PostStatus.posted


def test_an_in_app_clip_on_an_approval_account_posts_as_the_owner_approved_it(rig):
    """Only autopilot is guarded: in approval mode the owner saw the clip (and the silent-master note) and approved it."""
    p = rig.post(clip=silent_clip(rig))
    pub = FakePublisher()
    rig.run(pub)
    assert len(pub.calls) == 1 and rig.get(p).status is PostStatus.posted


def test_the_flag_is_per_account_so_the_other_account_of_the_clip_is_judged_alone(tmp_path):
    rig = Rig(tmp_path, instagram=True)
    rig.store.update_account(rig.account("@biscuit.ig").id, mode="auto")
    clip = silent_clip(rig)
    tt, ig = rig.post("@biscuit.tt", clip=clip), rig.post("@biscuit.ig", clip=clip)
    pub = FakePublisher()
    rig.run(pub)
    assert rig.get(tt).status is PostStatus.posted and rig.get(ig).status is PostStatus.failed


# ---- publish_due: the happy path ---------------------------------------------------------------


def test_posts_due_and_marks_posted(rig):
    p = rig.post()
    pub = FakePublisher()

    summary = rig.run(pub)

    [call] = pub.calls
    clip = rig.store.get_clip(p.clip_id)
    assert call["platform"] is Platform.tiktok
    assert call["integration_id"] == "int-bis-tt"
    assert call["caption"] == "caption 1"
    assert call["hashtags"] == ["oddeyes", "#ai"]
    assert call["ai_label"] is True  # never without the AI label
    assert call["media_url"] == rig.storage.signed_url("clips", clip.master_path)
    done = rig.get(p)
    assert done.status is PostStatus.posted
    assert (done.platform_post_id, done.url) == ("pz-1", "https://example.test/v/1")
    assert done.error is None
    assert clip.state is ClipState.posted
    assert [x["post_id"] for x in summary["posted"]] == [p.id]
    assert summary["errors"] == []


def test_future_posts_are_left_alone(rig):
    p = rig.post(when=NOW + timedelta(minutes=1))
    pub = FakePublisher()
    summary = rig.run(pub)
    assert pub.calls == []
    assert rig.get(p).status is PostStatus.scheduled
    assert summary["posted"] == []


def test_second_run_posts_nothing_again(rig):
    rig.post()
    pub = FakePublisher()
    rig.run(pub)
    rig.run(pub, NOW + timedelta(minutes=15))
    assert len(pub.calls) == 1  # idempotent: a posted post is never picked up again


def test_clip_is_posted_only_when_all_its_posts_are_posted(tmp_path):
    rig = Rig(tmp_path, instagram=True)
    clip = rig.clip()
    tt = rig.post("@biscuit.tt", clip=clip)
    ig = rig.post("@biscuit.ig", clip=clip, when=NOW + timedelta(hours=2))
    pub = FakePublisher()

    rig.run(pub)
    assert rig.get(tt).status is PostStatus.posted
    assert rig.store.get_clip(clip.id).state is ClipState.scheduled  # Instagram still pending

    rig.run(pub, NOW + timedelta(hours=3))
    assert rig.get(ig).status is PostStatus.posted
    assert rig.store.get_clip(clip.id).state is ClipState.posted
    assert [c["platform"] for c in pub.calls] == [Platform.tiktok, Platform.instagram]


def test_a_failed_sibling_keeps_the_clip_scheduled(tmp_path):
    rig = Rig(tmp_path, instagram=True)
    clip = rig.clip()
    rig.post("@biscuit.tt", clip=clip)
    rig.post("@biscuit.ig", clip=clip, status="failed", attempts=3)
    rig.run(FakePublisher())
    assert rig.store.get_clip(clip.id).state is ClipState.scheduled


def test_posts_go_out_in_due_order(tmp_path):
    rig = Rig(tmp_path)
    late = rig.post("@reginald.tt", when=SLOT + timedelta(minutes=30))
    early = rig.post("@biscuit.tt", when=SLOT)
    pub = FakePublisher()
    rig.run(pub)
    assert [c["integration_id"] for c in pub.calls] == ["int-bis-tt", "int-reg-tt"]
    assert rig.get(early).platform_post_id == "pz-1" and rig.get(late).platform_post_id == "pz-2"


# ---- publish_due: failures and retries ---------------------------------------------------------


def test_failure_retries_then_fails_after_3(rig):
    p = rig.post()
    pub = FakePublisher(fail=RuntimeError("postiz exploded"))

    s1 = rig.run(pub)
    first = rig.get(p)
    assert (first.status, first.attempts, first.claimed_at) == (PostStatus.scheduled, 1, None)
    assert "postiz exploded" in first.error
    assert [x["post_id"] for x in s1["retry"]] == [p.id]

    rig.run(pub, NOW + timedelta(minutes=15))
    second = rig.get(p)
    assert (second.status, second.attempts, second.claimed_at) == (PostStatus.scheduled, 2, None)

    s3 = rig.run(pub, NOW + timedelta(minutes=30))
    third = rig.get(p)
    assert (third.status, third.attempts) == (PostStatus.failed, 3)
    assert "postiz exploded" in third.error
    assert [x["post_id"] for x in s3["failed"]] == [p.id]

    rig.run(pub, NOW + timedelta(minutes=45))
    assert len(pub.calls) == 3  # a failed post is never retried automatically
    assert rig.store.get_clip(p.clip_id).state is ClipState.scheduled


def test_a_retry_that_succeeds_clears_the_error(rig):
    p = rig.post()
    pub = FakePublisher(fail=RuntimeError("blip"))
    rig.run(pub)
    pub.fail = None
    rig.run(pub, NOW + timedelta(minutes=15))
    done = rig.get(p)
    assert done.status is PostStatus.posted and done.attempts == 1 and done.error is None


def test_error_text_is_kept_short(rig):
    p = rig.post()
    rig.run(FakePublisher(fail=RuntimeError("x" * 5000)))
    assert len(rig.get(p).error) <= 520


def test_a_missing_master_counts_as_a_failed_attempt(rig):
    clip = rig.clip()
    rig.store.update_clip(clip.id, master_path=None)
    p = rig.post(clip=clip)
    pub = FakePublisher()
    rig.run(pub)
    got = rig.get(p)
    assert (got.status, got.attempts) == (PostStatus.scheduled, 1) and got.error
    assert pub.calls == []


def test_an_unconnected_account_counts_as_a_failed_attempt(rig):
    acct = rig.account("@biscuit.tt")
    rig.store._accounts[acct.id].postiz_integration_id = None
    p = rig.post()
    pub = FakePublisher()
    rig.run(pub)
    assert rig.get(p).attempts == 1 and pub.calls == []


def test_a_clip_that_is_not_scheduled_is_never_published(rig):
    # e.g. rejected after its posts were created: failed at once, no attempt wasted, no retry
    p = rig.post(clip=rig.clip(state=ClipState.rejected))
    pub = FakePublisher()
    summary = rig.run(pub)
    got = rig.get(p)
    assert pub.calls == []
    assert (got.status, got.attempts) == (PostStatus.failed, 0)
    assert "rejected" in got.error
    assert [x["post_id"] for x in summary["failed"]] == [p.id]


def test_an_unknown_clip_or_account_fails_the_post(rig):
    rig.store._clips.clear()
    p = rig.post(clip=Clip(id="ghost", character_slug="biscuit", mode="recreate"))
    rig.run(FakePublisher())
    assert rig.get(p).status is PostStatus.failed and "clip" in rig.get(p).error


# ---- publish_due: a post whose outcome is unknown is never retried ------------------------------


def test_an_uncertain_publish_goes_to_needs_check_not_retry(rig):
    p = rig.post()
    pub = FakePublisher(fail=UncertainPublish("posts:create timed out"))
    summary = rig.run(pub)
    got = rig.get(p)
    assert (got.status, got.attempts) == (PostStatus.needs_check, 0)
    assert "timed out" in got.error
    assert [x["post_id"] for x in summary["needs_check"]] == [p.id]
    rig.run(pub, NOW + timedelta(minutes=15))
    assert len(pub.calls) == 1


def test_stale_posting_becomes_needs_check_not_retried(rig):
    stale = rig.post(status="posting", claimed_at=NOW - timedelta(minutes=31))
    pub = FakePublisher()

    summary = rig.run(pub)
    got = rig.get(stale)
    assert got.status is PostStatus.needs_check
    assert got.error and "check" in got.error.lower()
    assert [x["post_id"] for x in summary["stale"]] == [stale.id]
    assert pub.calls == []

    rig.run(pub, NOW + timedelta(hours=2))  # still not retried, however long it sits
    assert rig.get(stale).status is PostStatus.needs_check
    assert pub.calls == []
    assert rig.store.get_clip(stale.clip_id).state is ClipState.scheduled


def test_a_fresh_posting_is_left_to_its_owner(rig):
    inflight = rig.post(status="posting", claimed_at=NOW - timedelta(minutes=29))
    exactly = rig.post("@reginald.tt", status="posting", claimed_at=NOW - timedelta(minutes=30))
    pub = FakePublisher()
    rig.run(pub)
    assert rig.get(inflight).status is PostStatus.posting
    assert rig.get(exactly).status is PostStatus.posting  # strictly older than 30 min is stale
    assert pub.calls == []


class FlakyStore(MemoryStore):
    """Loses the write that records a successful post, as a crash right after Postiz would."""

    fail_posted_write = True
    fail_status = "posted"  # the status whose write is lost
    only_ids: set[str] | None = None  # None: every post

    def update_post(self, id, /, **kw):
        lost = self.only_ids is None or id in self.only_ids
        if self.fail_posted_write and lost and kw.get("status") == self.fail_status:
            raise RuntimeError("db went away")
        return super().update_post(id, **kw)


class ClipFlakyStore(MemoryStore):
    """Loses the clip -> posted move, as a crash between the post write and the transition would."""

    fail_clip_move = True

    def update_clip(self, id, /, **kw):
        if self.fail_clip_move and kw.get("state") == "posted":
            raise RuntimeError("db went away")
        return super().update_clip(id, **kw)


def test_a_lost_success_write_is_never_posted_twice(tmp_path):
    rig = Rig(tmp_path)
    flaky = FlakyStore(characters=rig.store.characters(), accounts=rig.store.accounts())
    rig.store = flaky
    p = rig.post()
    pub = FakePublisher()

    summary = rig.run(pub)  # Postiz said yes; our write of "posted" failed
    assert len(pub.calls) == 1
    assert [e["post_id"] for e in summary["errors"]] == [p.id]
    assert "db went away" in summary["errors"][0]["error"]
    assert rig.get(p).status is PostStatus.posting  # NOT sent back to scheduled

    flaky.fail_posted_write = False
    rig.run(pub, NOW + timedelta(minutes=15))  # not yet stale, not retried
    assert len(pub.calls) == 1
    rig.run(pub, NOW + timedelta(minutes=31))
    assert rig.get(p).status is PostStatus.needs_check
    assert len(pub.calls) == 1


def test_a_lost_success_write_still_counts_toward_the_daily_cap(tmp_path):
    rig = Rig(tmp_path)
    rig.store = FlakyStore(characters=rig.store.characters(), accounts=rig.store.accounts())
    posts = [rig.post(when=SLOT + timedelta(minutes=i)) for i in range(3)]
    pub = FakePublisher()

    summary = rig.run(pub)  # both Postiz successes lose their "posted" write

    assert len(pub.calls) == 2  # the third is NOT published in the same run
    assert [e["post_id"] for e in summary["errors"]] == [posts[0].id, posts[1].id]
    third = rig.get(posts[2])
    assert third.status is PostStatus.scheduled
    assert third.scheduled_for == datetime(2026, 10, 7, 19, 0, tzinfo=LONDON)
    assert [x["post_id"] for x in summary["rescheduled"]] == [posts[2].id]


def test_a_lost_needs_check_write_still_counts_toward_the_daily_cap(tmp_path):
    rig = Rig(tmp_path)
    flaky = FlakyStore(characters=rig.store.characters(), accounts=rig.store.accounts())
    flaky.fail_status = "needs_check"
    rig.store = flaky
    posts = [rig.post(when=SLOT + timedelta(minutes=i)) for i in range(3)]
    pub = FakePublisher(fail=UncertainPublish("posts:create timed out"))
    rig.run(pub)
    assert len(pub.calls) == 2  # an uncertain post may be live: it counts even if unrecorded
    assert rig.get(posts[2]).status is PostStatus.scheduled


def test_one_bad_post_does_not_stop_the_others(tmp_path):
    rig = Rig(tmp_path)
    rig.store = FlakyStore(characters=rig.store.characters(), accounts=rig.store.accounts())
    first = rig.post("@biscuit.tt", when=SLOT)
    second = rig.post("@reginald.tt", when=SLOT + timedelta(minutes=30))
    rig.store.only_ids = {first.id}
    pub = FakePublisher()
    summary = rig.run(pub, NOW + timedelta(hours=1))
    assert len(pub.calls) == 2  # the second still went out
    assert [e["post_id"] for e in summary["errors"]] == [first.id]
    assert [x["post_id"] for x in summary["posted"]] == [second.id]
    assert rig.get(first).status is PostStatus.posting
    assert rig.get(second).status is PostStatus.posted


# ---- publish_due: a clip whose posts are all posted but which is still `scheduled` ---------------


def test_reconcile_moves_a_clip_whose_posts_are_all_posted(rig):
    done = rig.post(status="posted", claimed_at=SLOT, platform_post_id="x")
    assert rig.store.get_clip(done.clip_id).state is ClipState.scheduled
    pub = FakePublisher()

    summary = rig.run(pub)

    assert rig.store.get_clip(done.clip_id).state is ClipState.posted
    assert summary["clips_posted"] == [done.clip_id]
    assert pub.calls == []


def test_reconcile_leaves_every_other_clip_alone(tmp_path):
    rig = Rig(tmp_path, instagram=True)
    mixed = rig.clip()  # one posted, one failed: not all posted
    rig.post("@biscuit.tt", clip=mixed, status="posted", claimed_at=SLOT, platform_post_id="a")
    rig.post("@biscuit.ig", clip=mixed, status="failed", attempts=3)
    pending = rig.clip("reginald")  # posted + a post that is still to come
    rig.post("@reginald.tt", clip=pending, status="posted", claimed_at=SLOT, platform_post_id="b")
    rig.post("@biscuit.ig", clip=pending, when=NOW + timedelta(hours=1))
    postless = rig.clip()  # no posts at all
    elsewhere = rig.clip(state=ClipState.approved)  # not scheduled: never touched
    rig.post("@biscuit.tt", clip=elsewhere, status="posted", claimed_at=SLOT, platform_post_id="c")

    summary = rig.run(FakePublisher())

    assert rig.store.get_clip(mixed.id).state is ClipState.scheduled
    assert rig.store.get_clip(pending.id).state is ClipState.scheduled
    assert rig.store.get_clip(postless.id).state is ClipState.scheduled
    assert rig.store.get_clip(elsewhere.id).state is ClipState.approved
    assert summary["clips_posted"] == [] and summary["errors"] == []


def test_a_crash_between_the_post_write_and_the_clip_move_heals_on_the_next_run(tmp_path):
    rig = Rig(tmp_path)
    flaky = ClipFlakyStore(characters=rig.store.characters(), accounts=rig.store.accounts())
    rig.store = flaky
    p = rig.post()
    pub = FakePublisher()

    first = rig.run(pub)  # the post is recorded, the clip move is lost
    assert rig.get(p).status is PostStatus.posted
    assert rig.store.get_clip(p.clip_id).state is ClipState.scheduled
    assert [e["post_id"] for e in first["errors"]] == [p.id]

    flaky.fail_clip_move = False
    second = rig.run(pub, NOW + timedelta(minutes=15))
    assert rig.store.get_clip(p.clip_id).state is ClipState.posted
    assert second["clips_posted"] == [p.clip_id] and second["errors"] == []
    assert len(pub.calls) == 1  # healing never publishes anything


def test_a_failing_reconcile_is_reported_and_does_not_stop_the_run(tmp_path):
    rig = Rig(tmp_path)
    flaky = ClipFlakyStore(characters=rig.store.characters(), accounts=rig.store.accounts())
    rig.store = flaky
    stuck = rig.post(status="posted", claimed_at=SLOT, platform_post_id="x")
    due = rig.post("@reginald.tt", when=SLOT + timedelta(minutes=30))
    pub = FakePublisher()
    summary = rig.run(pub)
    assert [e["clip_id"] for e in summary["errors"] if "clip_id" in e] == [stuck.clip_id]
    assert rig.get(due).status is PostStatus.posted  # the due post still went out


# ---- publish_due: at most 2 posted per account per London day -----------------------------------


def test_daily_cap_two_per_account(rig):
    posts = [rig.post(when=SLOT + timedelta(minutes=i)) for i in range(3)]
    pub = FakePublisher()

    summary = rig.run(pub)

    assert len(pub.calls) == 2
    assert [rig.get(p).status for p in posts] == [
        PostStatus.posted, PostStatus.posted, PostStatus.scheduled,
    ]  # fmt: skip
    third = rig.get(posts[2])
    wed_slot = datetime(2026, 10, 7, 19, 0, tzinfo=LONDON)  # biscuit's next cadence day
    assert third.scheduled_for == wed_slot
    assert (third.claimed_at, third.attempts, third.error) == (None, 0, None)
    assert [x["post_id"] for x in summary["rescheduled"]] == [posts[2].id]
    assert summary["rescheduled"][0]["to"] == wed_slot
    assert rig.store.get_clip(posts[2].clip_id).state is ClipState.scheduled

    rig.run(pub, NOW + timedelta(minutes=15))  # same day again: the deferred post waits for Wednesday
    assert len(pub.calls) == 2
    rig.run(pub, wed_slot + timedelta(minutes=5))
    assert len(pub.calls) == 3 and rig.get(posts[2]).status is PostStatus.posted


def test_the_cap_counts_posts_from_earlier_runs_today(rig):
    for minutes in (0, 5):
        rig.post(status="posted", claimed_at=SLOT + timedelta(minutes=minutes),
                 platform_post_id="old", when=SLOT)  # fmt: skip
    extra = rig.post(when=SLOT + timedelta(minutes=10))
    pub = FakePublisher()
    rig.run(pub)
    assert pub.calls == []
    assert rig.get(extra).status is PostStatus.scheduled
    assert rig.get(extra).scheduled_for > NOW


def test_the_cap_is_per_account(rig):
    for i in range(2):
        rig.post("@biscuit.tt", status="posted", claimed_at=SLOT, platform_post_id=f"b{i}")
    other = rig.post("@reginald.tt", when=SLOT + timedelta(minutes=30))
    pub = FakePublisher()
    rig.run(pub)
    assert rig.get(other).status is PostStatus.posted


def test_the_cap_counts_a_possibly_live_needs_check_post(rig):
    rig.post(status="posted", claimed_at=SLOT, platform_post_id="a")
    rig.post(status="needs_check", claimed_at=SLOT)  # may well be live: counts
    extra = rig.post()
    pub = FakePublisher()
    rig.run(pub)
    assert pub.calls == [] and rig.get(extra).status is PostStatus.scheduled


def test_a_fresh_posting_post_counts_toward_the_cap_at_run_start(rig):
    """Another runner has a post in flight: it may well be live in a minute, so it takes a slot."""
    rig.post(status="posted", claimed_at=SLOT, platform_post_id="a")
    inflight = rig.post(status="posting", claimed_at=NOW - timedelta(minutes=5))
    extra = rig.post(when=SLOT + timedelta(minutes=10))
    pub = FakePublisher()
    summary = rig.run(pub)
    assert pub.calls == []
    assert rig.get(extra).status is PostStatus.scheduled and rig.get(extra).scheduled_for > NOW
    assert [x["post_id"] for x in summary["rescheduled"]] == [extra.id]
    assert rig.get(inflight).status is PostStatus.posting  # left to its owner, as before


def test_two_fresh_posting_posts_fill_the_cap(rig):
    for minutes in (3, 4):
        rig.post(status="posting", claimed_at=NOW - timedelta(minutes=minutes))
    extra = rig.post(when=SLOT + timedelta(minutes=10))
    pub = FakePublisher()
    rig.run(pub)
    assert pub.calls == [] and rig.get(extra).status is PostStatus.scheduled


def test_one_fresh_posting_post_leaves_room_for_one_more(rig):
    rig.post(status="posting", claimed_at=NOW - timedelta(minutes=3))
    first = rig.post(when=SLOT + timedelta(minutes=10))
    second = rig.post(when=SLOT + timedelta(minutes=11))
    pub = FakePublisher()
    rig.run(pub)
    assert len(pub.calls) == 1
    assert (rig.get(first).status, rig.get(second).status) == (PostStatus.posted, PostStatus.scheduled)


def test_a_fresh_posting_post_of_another_account_does_not_count(rig):
    for minutes in (3, 4):
        rig.post("@reginald.tt", status="posting", claimed_at=NOW - timedelta(minutes=minutes))
    mine = rig.post("@biscuit.tt", when=SLOT + timedelta(minutes=10))
    rig.run(FakePublisher())
    assert rig.get(mine).status is PostStatus.posted


def test_a_stale_posting_post_is_counted_once_not_twice(rig):
    """Stale -> needs_check (counted as possibly live); the new posting rule must not count it again."""
    rig.post(status="posting", claimed_at=NOW - timedelta(minutes=31))
    due = rig.post(when=SLOT + timedelta(minutes=10))
    assert [x["post_id"] for x in preview_due(rig.store, NOW)["would_post"]] == [due.id]
    pub = FakePublisher()
    rig.run(pub)
    assert len(pub.calls) == 1 and rig.get(due).status is PostStatus.posted


def test_the_dry_run_counts_a_fresh_posting_post_too(rig):
    rig.post(status="posted", claimed_at=SLOT, platform_post_id="a")
    rig.post(status="posting", claimed_at=NOW - timedelta(minutes=5))
    extra = rig.post(when=SLOT + timedelta(minutes=10))
    out = preview_due(rig.store, NOW)
    assert out["would_post"] == []
    assert [x["post_id"] for x in out["would_reschedule"]] == [extra.id]


def test_failed_and_yesterdays_posts_do_not_count(rig):
    yesterday = SLOT - timedelta(days=1)
    rig.post(status="posted", claimed_at=yesterday, platform_post_id="y1")
    rig.post(status="posted", claimed_at=yesterday, platform_post_id="y2")
    rig.post(status="failed", claimed_at=SLOT, attempts=3)
    rig.post(status="failed", claimed_at=SLOT, attempts=3)
    due = rig.post()
    rig.run(FakePublisher())
    assert rig.get(due).status is PostStatus.posted


# ---- the kill switch stops posting (spec: "stops generation and posting") ----------------------------


def test_kill_switch_on_claims_and_posts_nothing(rig):
    rig.store.set_settings(kill_switch=True)
    due = [rig.post(), rig.post("@reginald.tt")]
    pub = FakePublisher()
    summary = rig.run(pub)
    assert pub.calls == [] and summary["paused"] is True
    assert [rig.get(p).status for p in due] == [PostStatus.scheduled, PostStatus.scheduled]
    assert all(rig.get(p).claimed_at is None and rig.get(p).attempts == 0 for p in due)  # never claimed
    assert summary["posted"] == [] and summary["errors"] == []


def test_kill_switch_still_reconciles_clips_and_flags_stale_claims(rig):
    """Bookkeeping that publishes nothing keeps running: only the posting stops."""
    rig.store.set_settings(kill_switch=True)
    stale = rig.post(status="posting", claimed_at=NOW - timedelta(hours=2))
    done = rig.post(status="posted", claimed_at=SLOT, platform_post_id="a")
    summary = rig.run(FakePublisher())
    assert rig.get(stale).status is PostStatus.needs_check and [x["post_id"] for x in summary["stale"]] == [stale.id]
    assert rig.store.get_clip(done.clip_id).state is ClipState.posted and summary["clips_posted"] == [done.clip_id]
    assert summary["paused"] is True


def test_kill_switch_off_posts_as_usual_and_says_so(rig):
    p = rig.post()
    pub = FakePublisher()
    summary = rig.run(pub)
    assert summary["paused"] is False and len(pub.calls) == 1 and rig.get(p).status is PostStatus.posted


def test_posts_wait_through_the_pause_and_go_out_when_it_lifts(rig):
    rig.store.set_settings(kill_switch=True)
    p = rig.post()
    pub = FakePublisher()
    rig.run(pub)
    rig.store.set_settings(kill_switch=False)
    rig.run(pub, NOW + timedelta(minutes=15))
    assert len(pub.calls) == 1 and rig.get(p).status is PostStatus.posted


def test_the_dry_run_with_the_kill_switch_on_would_post_nothing(rig):
    rig.store.set_settings(kill_switch=True)
    p = rig.post()
    out = preview_due(rig.store, NOW)
    assert out["paused"] is True and out["would_post"] == [] and out["would_reschedule"] == []
    assert rig.get(p).status is PostStatus.scheduled
    rig.store.set_settings(kill_switch=False)
    assert [x["post_id"] for x in preview_due(rig.store, NOW)["would_post"]] == [p.id]


# ---- a deferral lands on the first cadence day on which the account has no post ----------------------


def test_a_deferred_post_skips_a_day_the_account_already_posts_on(rig):
    for minutes in (0, 1):
        rig.post(status="posted", claimed_at=SLOT + timedelta(minutes=minutes), platform_post_id=f"p{minutes}")
    wed = datetime(2026, 10, 7, 19, 0, tzinfo=LONDON)
    rig.post(when=wed)  # another clip is already scheduled for Wednesday
    extra = rig.post(when=SLOT + timedelta(minutes=10))
    summary = rig.run(FakePublisher())
    thu = datetime(2026, 10, 8, 19, 0, tzinfo=LONDON)
    assert rig.get(extra).scheduled_for == thu and summary["rescheduled"][0]["to"] == thu


def test_two_deferrals_in_one_run_land_on_different_days(rig):
    for minutes in (0, 1):
        rig.post(status="posted", claimed_at=SLOT + timedelta(minutes=minutes), platform_post_id=f"p{minutes}")
    a = rig.post(when=SLOT + timedelta(minutes=10))
    b = rig.post(when=SLOT + timedelta(minutes=11))
    rig.run(FakePublisher())
    assert [rig.get(a).scheduled_for, rig.get(b).scheduled_for] == [
        datetime(2026, 10, 7, 19, 0, tzinfo=LONDON), datetime(2026, 10, 8, 19, 0, tzinfo=LONDON)
    ]


def test_the_dry_run_predicts_the_same_deferral_days(rig):
    for minutes in (0, 1):
        rig.post(status="posted", claimed_at=SLOT + timedelta(minutes=minutes), platform_post_id=f"p{minutes}")
    rig.post(when=datetime(2026, 10, 7, 19, 0, tzinfo=LONDON))
    a = rig.post(when=SLOT + timedelta(minutes=10))
    b = rig.post(when=SLOT + timedelta(minutes=11))
    out = preview_due(rig.store, NOW)
    assert [(x["post_id"], x["to"]) for x in out["would_reschedule"]] == [
        (a.id, datetime(2026, 10, 8, 19, 0, tzinfo=LONDON)), (b.id, datetime(2026, 10, 13, 19, 0, tzinfo=LONDON)),
    ]


def test_the_cap_day_is_the_london_day_not_the_utc_day(rig):
    # 00:30 BST on the 7th is 23:30 UTC on the 6th: still "the 7th" in London.
    after_midnight = datetime(2026, 10, 7, 0, 30, tzinfo=LONDON)
    assert after_midnight.astimezone(timezone.utc).day == 6
    for i in range(2):
        rig.post(status="posted", claimed_at=after_midnight + timedelta(minutes=i),
                 platform_post_id=f"n{i}")  # fmt: skip
    morning = datetime(2026, 10, 7, 10, 0, tzinfo=LONDON)
    extra = rig.post(when=morning - timedelta(hours=1))
    pub = FakePublisher()
    rig.run(pub, morning)
    assert pub.calls == [] and rig.get(extra).status is PostStatus.scheduled


def test_next_slot_skips_to_the_next_cadence_day(rig):
    # Thursday evening: the next biscuit day is Tuesday (cadence tue/wed/thu), 19:00 London.
    thu = datetime(2026, 10, 8, 20, 0, tzinfo=LONDON)
    for i in range(2):
        rig.post(status="posted", claimed_at=thu - timedelta(hours=1), platform_post_id=f"t{i}")
    extra = rig.post(when=thu - timedelta(hours=1))
    rig.run(FakePublisher(), thu)
    assert rig.get(extra).scheduled_for == datetime(2026, 10, 13, 19, 0, tzinfo=LONDON)


def test_next_slot_uses_the_real_cadence_and_the_characters_slot(rig):
    rig.store.set_settings(cadence={
        "biscuit": {"days": ["mon", "fri"], "slot": "18:15"},
        "reginald": {"days": ["tue"], "slot": "19:30"},
    })  # fmt: skip
    for i in range(2):
        rig.post(status="posted", claimed_at=SLOT, platform_post_id=f"c{i}")
    extra = rig.post(when=SLOT)
    rig.run(FakePublisher())
    assert rig.get(extra).scheduled_for == datetime(2026, 10, 9, 18, 15, tzinfo=LONDON)  # Friday


def test_a_character_without_cadence_days_is_pushed_to_the_next_day(rig):
    rig.store.set_settings(cadence={"biscuit": {"days": [], "slot": "19:00"}})
    for i in range(2):
        rig.post(status="posted", claimed_at=SLOT, platform_post_id=f"d{i}")
    extra = rig.post(when=SLOT)
    rig.run(FakePublisher())
    assert rig.get(extra).scheduled_for == datetime(2026, 10, 7, 19, 0, tzinfo=LONDON)


def test_next_slot_helper_handles_the_clock_change():
    cadence = {"biscuit": {"days": ["mon"], "slot": "19:00"}}
    sat = datetime(2026, 10, 24, 12, 0, tzinfo=LONDON).date()
    slot = base.next_slot("biscuit", sat, cadence)  # Monday 26th: GMT again
    assert slot == datetime(2026, 10, 26, 19, 0, tzinfo=LONDON)
    assert slot.utcoffset() == timedelta(0)
    with pytest.raises(ValueError):
        base.next_slot("nobody", sat, cadence)


# ---- dry run -----------------------------------------------------------------------------------


def test_preview_claims_and_changes_nothing(tmp_path):
    rig = Rig(tmp_path)
    due = [rig.post(when=SLOT + timedelta(minutes=i)) for i in range(3)]
    stale = rig.post("@reginald.tt", status="posting", claimed_at=NOW - timedelta(hours=2))
    future = rig.post("@reginald.tt", when=NOW + timedelta(hours=1))
    before = [p for p in rig.store.list_posts()]

    out = preview_due(rig.store, NOW)

    assert rig.store.list_posts() == before  # nothing claimed, nothing moved
    assert [x["post_id"] for x in out["would_post"]] == [due[0].id, due[1].id]
    assert [x["post_id"] for x in out["would_reschedule"]] == [due[2].id]
    assert out["would_reschedule"][0]["to"] == datetime(2026, 10, 7, 19, 0, tzinfo=LONDON)
    assert [x["post_id"] for x in out["would_flag_needs_check"]] == [stale.id]
    assert future.id not in json.dumps(out, default=str)
    first = out["would_post"][0]
    assert (first["handle"], first["platform"], first["integration_id"]) == (
        "@biscuit.tt", "tiktok", "int-bis-tt",
    )  # fmt: skip


def test_preview_flags_what_a_real_run_would_refuse(rig):
    p = rig.post(clip=rig.clip(state=ClipState.dropped))
    out = preview_due(rig.store, NOW)
    assert [x["post_id"] for x in out["would_fail"]] == [p.id]
    assert out["would_post"] == []


# ---- the Postiz adapter ------------------------------------------------------------------------

UPLOAD_OUT = '✅ File uploaded successfully!\n{"id": "m1", "path": "https://uploads.postiz.test/abc.mp4"}\n'
CREATE_OUT = '✅ Post created successfully!\n[{"postId": "pz-post-9", "integration": "int-bis-tt"}]\n'


class FakeRun:
    """A stand-in for ``subprocess.run`` that records argv and answers per subcommand."""

    def __init__(self, upload=(0, UPLOAD_OUT, ""), create=(0, CREATE_OUT, ""), raises=None):
        self.answers = {"upload": upload, "posts:create": create}
        self.raises = raises or {}
        self.calls: list[list[str]] = []
        self.kwargs: list[dict[str, Any]] = []
        self.uploaded_path: Path | None = None
        self.uploaded_bytes: bytes | None = None
        self.path_existed_at_create: bool | None = None

    def __call__(self, argv, **kw):
        self.calls.append(list(argv))
        self.kwargs.append(kw)
        sub = argv[1]
        if sub == "upload":
            self.uploaded_path = Path(argv[2])
            self.uploaded_bytes = self.uploaded_path.read_bytes()  # must exist right now
        if sub == "posts:create" and self.uploaded_path is not None:
            self.path_existed_at_create = self.uploaded_path.exists()
        if sub in self.raises:
            raise self.raises[sub]
        answer = self.answers[sub]
        rc, out, err = answer(list(argv)) if callable(answer) else answer
        return subprocess.CompletedProcess(argv, rc, stdout=out, stderr=err)

    def option(self, sub: str, flag: str) -> str:
        argv = next(c for c in self.calls if c[1] == sub)
        return argv[argv.index(flag) + 1]


def stored_master(tmp_path: Path) -> tuple[LocalStorage, str]:
    storage = LocalStorage(tmp_path / "pz-store")
    local = tmp_path / "pz-master.mp4"
    local.write_bytes(MASTER)
    storage.upload("clips", "masters/pz.mp4", local)
    return storage, storage.signed_url("clips", "masters/pz.mp4")


def publish_via_postiz(tmp_path, run, platform=Platform.tiktok, integration="int-bis-tt", **kw):
    _, url = stored_master(tmp_path)
    clock = lambda: datetime(2026, 10, 6, 18, 5, 9, tzinfo=timezone.utc)  # noqa: E731
    publisher = PostizPublisher(run, clock=clock, **kw)
    return publisher.publish(
        platform=platform, integration_id=integration, media_url=url,
        caption="the right eye is ice-blue", hashtags=["oddeyes", "#biscuit"], ai_label=True,
    )  # fmt: skip


def test_postiz_publisher_is_a_publisher():
    assert isinstance(PostizPublisher(FakeRun()), Publisher)


def test_postiz_tiktok_uses_direct_post(tmp_path):
    run = FakeRun()

    result = publish_via_postiz(tmp_path, run)

    assert [c[1] for c in run.calls] == ["upload", "posts:create"]  # upload first (Rule 2)
    settings = json.loads(run.option("posts:create", "--settings"))
    assert settings["content_posting_method"] == "DIRECT_POST"  # Rule 3
    assert settings["video_made_with_ai"] is True
    assert settings["privacy_level"] == "PUBLIC_TO_EVERYONE"
    assert settings["autoAddMusic"] == "no"  # required by the DTO; never let TikTok add music
    assert settings == TIKTOK_SETTINGS
    assert run.option("posts:create", "-i") == "int-bis-tt"
    # the media is the path Postiz returned from the upload, never a local file or the signed URL
    assert run.option("posts:create", "-m") == "https://uploads.postiz.test/abc.mp4"
    content = run.option("posts:create", "-c")
    assert content == "the right eye is ice-blue\n\nAI-generated character 🤖\n\n#oddeyes #biscuit"
    assert run.option("posts:create", "-s") == "2026-10-06T18:05:09Z"
    assert result == PublishResult(platform_post_id="pz-post-9", url=None)


def test_postiz_downloads_the_master_to_a_temp_file_and_cleans_up(tmp_path):
    run = FakeRun()
    publish_via_postiz(tmp_path, run)
    assert run.uploaded_bytes == MASTER  # the real master was handed to `postiz upload`
    assert run.uploaded_path.suffix == ".mp4"
    assert not run.uploaded_path.exists()  # temp file gone
    assert run.path_existed_at_create is False  # and gone before posts:create even runs
    assert not run.uploaded_path.parent.exists()


def test_postiz_cleans_up_when_the_upload_fails(tmp_path):
    run = FakeRun(upload=(1, "", "❌ Failed to upload file: 413"))
    with pytest.raises(PostizError, match="413"):
        publish_via_postiz(tmp_path, run)
    assert [c[1] for c in run.calls] == ["upload"]  # nothing was posted
    assert not run.uploaded_path.exists()


def test_postiz_instagram_is_a_reel(tmp_path):
    run = FakeRun(create=(0, '[{"postId": "pz-ig"}]', ""))
    result = publish_via_postiz(tmp_path, run, Platform.instagram, "int-bis-ig")
    assert json.loads(run.option("posts:create", "--settings")) == INSTAGRAM_SETTINGS
    assert INSTAGRAM_SETTINGS == {"post_type": "post"}  # a single video post is published as a Reel
    assert run.option("posts:create", "-i") == "int-bis-ig"
    assert result.platform_post_id == "pz-ig"


def test_the_settings_constants_are_marked_for_the_go_live_check():
    source = Path(postiz.__file__).read_text()
    assert source.count("# VERIFY at go-live (Task 16): postiz integrations:settings <id>") >= 2


def test_postiz_upload_result_may_come_without_a_status_line(tmp_path):
    run = FakeRun(upload=(0, '{"path": "https://uploads.postiz.test/plain.mp4"}', ""))
    publish_via_postiz(tmp_path, run)
    assert run.option("posts:create", "-m") == "https://uploads.postiz.test/plain.mp4"


def test_postiz_upload_without_a_path_is_a_plain_error(tmp_path):
    run = FakeRun(upload=(0, '✅ File uploaded successfully!\n{"id": "m1"}', ""))
    with pytest.raises(PostizError, match="path"):
        publish_via_postiz(tmp_path, run)
    assert [c[1] for c in run.calls] == ["upload"]


@pytest.mark.parametrize("status", [400, 401, 403, 404, 422, 429])
def test_postiz_a_definite_4xx_is_a_plain_retriable_error(tmp_path, status):
    err = f"❌ Failed to create post: Request failed: API Error ({status}): invalid privacy"
    run = FakeRun(create=(1, "", err))
    with pytest.raises(PostizError, match="invalid privacy") as e:
        publish_via_postiz(tmp_path, run)
    assert not isinstance(e.value, UncertainPublish)  # Postiz refused it: nothing was created


@pytest.mark.parametrize(
    "stderr",
    [
        "❌ Failed to create post: Request failed: API Error (502): Bad Gateway",
        "❌ Failed to create post: Request failed: API Error (500): boom",
        "❌ Failed to create post: Request failed: API Error (503): unavailable",
        "❌ Failed to create post: Request failed: API Error (524): origin timed out",
        "❌ Failed to create post: Request failed: API Error (408): Request Timeout",
        "❌ Failed to create post: Request failed: API Error (409): Conflict",
        "❌ Failed to create post: Request failed: socket hang up",
        "❌ Failed to create post: Request failed: connect ECONNRESET 10.0.0.1:443",
        "❌ Failed to create post: fetch failed",
        "❌ Failed to create post: something nobody has seen before",
        "",
    ],
)
def test_postiz_anything_but_a_definite_4xx_is_uncertain(tmp_path, stderr):
    # A 5xx or a dropped connection may already have committed server-side, and Postiz has no
    # idempotency key: only the operator can say whether the post exists.
    run = FakeRun(create=(1, "", stderr))
    with pytest.raises(UncertainPublish):
        publish_via_postiz(tmp_path, run)


def test_postiz_a_408_is_uncertain_not_a_definite_rejection(tmp_path):
    """408 Request Timeout: the server gave up waiting, but the create may have gone through."""
    run = FakeRun(create=(1, "", "❌ Failed to create post: Request failed: API Error (408): timeout"))
    with pytest.raises(UncertainPublish, match="408"):
        publish_via_postiz(tmp_path, run)


def test_postiz_a_409_is_uncertain_too(tmp_path):
    """409 Conflict may be the post already existing: never retried."""
    run = FakeRun(create=(1, "", "❌ Failed to create post: Request failed: API Error (409): conflict"))
    with pytest.raises(UncertainPublish, match="409"):
        publish_via_postiz(tmp_path, run)


@pytest.mark.parametrize("status", [408, 409])
def test_postiz_a_408_or_409_ends_in_needs_check_and_is_never_retried_end_to_end(tmp_path, status):
    rig = Rig(tmp_path)
    p = rig.post()
    run = FakeRun(create=(1, "", f"Request failed: API Error ({status}): x"))
    publisher = PostizPublisher(run)
    rig.run(publisher)
    rig.run(publisher, NOW + timedelta(minutes=15))
    got = rig.get(p)
    assert (got.status, got.attempts) == (PostStatus.needs_check, 0)
    assert [c[1] for c in run.calls].count("posts:create") == 1


def test_postiz_reads_the_status_from_stdout_when_stderr_is_empty(tmp_path):
    run = FakeRun(create=(1, "Request failed: API Error (400): nope", ""))
    with pytest.raises(PostizError) as e:
        publish_via_postiz(tmp_path, run)
    assert not isinstance(e.value, UncertainPublish)


def test_postiz_success_without_a_post_id_is_uncertain(tmp_path):
    run = FakeRun(create=(0, "✅ Post created successfully!\n[]", ""))
    with pytest.raises(UncertainPublish):
        publish_via_postiz(tmp_path, run)


def test_postiz_unparseable_success_output_is_uncertain(tmp_path):
    run = FakeRun(create=(0, "✅ Post created successfully!", ""))
    with pytest.raises(UncertainPublish):
        publish_via_postiz(tmp_path, run)


def test_postiz_create_timeout_is_uncertain_but_upload_timeout_is_not(tmp_path):
    slow_create = FakeRun(raises={"posts:create": subprocess.TimeoutExpired(["postiz"], 180)})
    with pytest.raises(UncertainPublish):
        publish_via_postiz(tmp_path, slow_create)
    slow_upload = FakeRun(raises={"upload": subprocess.TimeoutExpired(["postiz"], 900)})
    with pytest.raises(PostizError, match="timed out") as e:
        publish_via_postiz(tmp_path, slow_upload)
    assert not isinstance(e.value, UncertainPublish)  # nothing was posted yet: safe to retry
    assert [c[1] for c in slow_upload.calls] == ["upload"]


def test_postiz_passes_a_timeout_and_captures_output(tmp_path):
    run = FakeRun()
    publish_via_postiz(tmp_path, run)
    for kw in run.kwargs:
        assert kw["capture_output"] is True
        assert kw["encoding"] == "utf-8" and kw["errors"] == "replace"  # emoji-safe, never raises
        assert kw["timeout"] > 0
        assert kw["stdin"] is subprocess.DEVNULL


def test_postiz_with_a_real_subprocess(tmp_path):
    """The real ``subprocess.run``: argv with spaces and newlines, emoji on stdout, JSON parsing."""
    log = tmp_path / "argv.json"
    script = tmp_path / "postiz"
    script.write_text(
        f"#!{sys.executable}\n"
        "import json, sys\n"
        f"log = {str(log)!r}\n"
        "calls = json.load(open(log)) if __import__('os').path.exists(log) else []\n"
        "calls.append(sys.argv[1:])\n"
        "json.dump(calls, open(log, 'w'))\n"
        "if sys.argv[1] == 'upload':\n"
        "    print('✅ File uploaded successfully!')\n"
        "    print(json.dumps({'path': 'https://uploads.postiz.test/real.mp4'}))\n"
        "else:\n"
        "    print('✅ Post created successfully!')\n"
        "    print(json.dumps([{'postId': 'pz-real', 'integration': sys.argv[sys.argv.index('-i') + 1]}]))\n"
    )
    script.chmod(0o755)
    _, url = stored_master(tmp_path)

    result = PostizPublisher(executable=str(script)).publish(
        platform=Platform.tiktok, integration_id="int-bis-tt", media_url=url,
        caption="two words,\nthree lines\n\"quoted\"", hashtags=["oddeyes"], ai_label=True,
    )  # fmt: skip

    assert result.platform_post_id == "pz-real"
    upload, create = json.loads(log.read_text())
    assert upload[0] == "upload" and upload[1].endswith(".mp4")
    assert create[create.index("-c") + 1] == (
        'two words,\nthree lines\n"quoted"\n\nAI-generated character 🤖\n\n#oddeyes'
    )
    assert create[create.index("-m") + 1] == "https://uploads.postiz.test/real.mp4"
    assert json.loads(create[create.index("--settings") + 1])["content_posting_method"] == "DIRECT_POST"


def test_postiz_refuses_to_post_without_the_ai_label(tmp_path):
    run = FakeRun()
    _, url = stored_master(tmp_path)
    with pytest.raises(ValueError, match="AI label"):
        PostizPublisher(run).publish(
            platform=Platform.tiktok, integration_id="x", media_url=url,
            caption="c", hashtags=[], ai_label=False,
        )  # fmt: skip
    assert run.calls == []


def test_postiz_rejects_an_empty_post_or_integration(tmp_path):
    _, url = stored_master(tmp_path)
    pub = PostizPublisher(FakeRun())
    with pytest.raises(ValueError, match="integration"):
        pub.publish(platform=Platform.tiktok, integration_id="", media_url=url,
                    caption="c", hashtags=[], ai_label=True)  # fmt: skip
    with pytest.raises(ValueError, match="empty"):
        pub.publish(platform=Platform.tiktok, integration_id="x", media_url=url,
                    caption="  ", hashtags=[" ", "#"], ai_label=True)  # fmt: skip


def test_postiz_fetch_failure_names_no_url_and_posts_nothing(tmp_path):
    run = FakeRun()
    handler = lambda request: httpx.Response(403, text="forbidden")  # noqa: E731
    fetch = partial(download_media, transport=httpx.MockTransport(handler))
    secret = "https://proj.supabase.co/storage/v1/object/sign/clips/m.mp4?token=SECRET-TOKEN"
    with pytest.raises(PostizError) as e:
        PostizPublisher(run, fetch=fetch).publish(
            platform=Platform.tiktok, integration_id="x", media_url=secret,
            caption="c", hashtags=[], ai_label=True,
        )  # fmt: skip
    assert "403" in str(e.value) and "SECRET-TOKEN" not in str(e.value)
    assert run.calls == []


def test_a_transport_error_while_fetching_never_leaks_the_url(tmp_path):
    secret = "https://proj.supabase.co/storage/v1/object/sign/clips/m.mp4?token=SECRET-TOKEN"

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"cannot reach {secret}")

    with pytest.raises(PostizError) as e:
        download_media(secret, tmp_path / "x.mp4", transport=httpx.MockTransport(handler))
    assert "ConnectError" in str(e.value) and "SECRET-TOKEN" not in str(e.value)


def test_download_media_streams_an_https_signed_url(tmp_path):
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url)
        return httpx.Response(200, content=MASTER)

    dest = tmp_path / "out.mp4"
    download_media("https://proj.supabase.co/sign/m.mp4?token=t", dest,
                   transport=httpx.MockTransport(handler))  # fmt: skip
    assert dest.read_bytes() == MASTER and len(seen) == 1


def test_download_media_reads_file_uris_and_refuses_other_schemes(tmp_path):
    _, url = stored_master(tmp_path)
    dest = tmp_path / "copy.mp4"
    download_media(url, dest)
    assert dest.read_bytes() == MASTER
    with pytest.raises(ValueError, match="scheme"):
        download_media("ftp://example.test/m.mp4", dest)


AI = "AI-generated character 🤖"


@pytest.mark.parametrize(
    ("caption", "tags", "expected"),
    [
        ("hello", ["a", "#b"], f"hello\n\n{AI}\n\n#a #b"),
        ("hello", [], f"hello\n\n{AI}"),
        ("", ["a"], f"{AI}\n\n#a"),
        ("hello", ["A", "a", "#A", " b ", ""], f"hello\n\n{AI}\n\n#A #b"),  # trimmed, de-duplicated
        ("  hello  ", ["#"], f"hello\n\n{AI}"),
        # only the EXACT disclosure line is not told twice; wording that merely mentions it does not count
        (f"Meet Biscuit\n{AI}", ["a"], f"Meet Biscuit\n{AI}\n\n#a"),
        ("an ai-generated dance", [], f"an ai-generated dance\n\n{AI}"),
        ("a dance", ["aigenerated"], f"a dance\n\n{AI}\n\n#aigenerated"),
    ],
)
def test_compose_content(caption, tags, expected):
    assert compose_content(caption, tags) == expected


# ---- the disclosure is exact, and the 2,200 limit raises (never trims) --------------------------------


def test_the_caption_limit_is_2200():
    assert CAPTION_LIMIT == 2200


@pytest.mark.parametrize(
    "caption",
    [
        "AI-generated? Never.",  # says the words, not the line: still gets the disclosure
        "Meet Biscuit, AI-generated since day one",
        "an ai-generated dance",
        "AI-generated character",  # close, but not the exact string (no emoji)
    ],
)
def test_the_disclosure_is_appended_unless_the_exact_string_is_present(caption):
    assert compose_content(caption, ["a"]) == f"{caption}\n\n{AI}\n\n#a"


def test_a_caption_already_carrying_the_exact_disclosure_is_not_told_twice():
    caption = f"the right eye is ice-blue\n{AI}"
    out = compose_content(caption, ["a"])
    assert out == f"{caption}\n\n#a" and out.count(AI) == 1


def test_a_caption_that_fits_the_limit_exactly_is_untouched():
    fixed = caption_length(f"\n\n{AI}\n\n#a")
    body = "x" * (CAPTION_LIMIT - fixed)
    out = compose_content(body, ["a"])
    assert out == f"{body}\n\n{AI}\n\n#a" and caption_length(out) == CAPTION_LIMIT


def test_one_char_over_the_limit_raises_with_the_composed_length_never_trims():
    fixed = caption_length(f"\n\n{AI}\n\n#a")
    body = "x" * (CAPTION_LIMIT - fixed + 1)  # the limit applies AFTER disclosure and hashtags
    with pytest.raises(ValueError, match=r"2201 characters.*2200") as e:
        compose_content(body, ["a"])
    assert "shorten the caption by 1" in str(e.value)


def test_the_limit_counts_hashtags_too():
    with pytest.raises(ValueError, match="2200"):  # five long tags (the most allowed) still count toward the length
        compose_content("hello", [f"tag{i}" + "z" * 440 for i in range(5)])


def test_emoji_count_as_two_units_so_the_limit_holds_in_utf16_too():
    assert caption_length("🐶") == 2
    with pytest.raises(ValueError):
        compose_content("🐶" * 1100, [])  # 1,100 code points, 2,200 units + the disclosure


def test_an_over_long_caption_is_a_failed_attempt_with_nothing_fetched_or_uploaded(tmp_path):
    run = FakeRun()
    _, url = stored_master(tmp_path)
    with pytest.raises(ValueError, match="2200"):
        PostizPublisher(run).publish(
            platform=Platform.tiktok, integration_id="int-bis-tt", media_url=url,
            caption="z" * 5000, hashtags=["oddeyes"], ai_label=True,
        )  # fmt: skip
    assert run.calls == []


def test_an_over_long_caption_fails_the_post_after_3_attempts_not_a_silent_trim(tmp_path):
    rig = Rig(tmp_path)
    clip = rig.clip()
    rig.store.update_clip(clip.id, caption="z" * 5000)
    p = rig.post(clip=clip)
    run = FakeRun()
    publisher = PostizPublisher(run)
    for i in range(3):
        rig.run(publisher, NOW + timedelta(minutes=15 * i))
    got = rig.get(p)
    assert got.status is PostStatus.failed and "2200" in got.error and run.calls == []


def test_the_content_posted_ends_with_the_disclosure_then_the_hashtags_within_the_limit(tmp_path):
    run = FakeRun()
    publish_via_postiz(tmp_path, run)
    content = run.option("posts:create", "-c")
    assert caption_length(content) <= CAPTION_LIMIT
    assert content == f"the right eye is ice-blue\n\n{AI}\n\n#oddeyes #biscuit"


@pytest.mark.parametrize(
    ("platform", "integration"),
    [(Platform.tiktok, "int-bis-tt"), (Platform.instagram, "int-bis-ig")],
)
def test_every_platform_gets_the_ai_disclosure_before_the_hashtags(tmp_path, platform, integration):
    run = FakeRun()
    publish_via_postiz(tmp_path, run, platform, integration)
    content = run.option("posts:create", "-c")
    assert AI in content
    assert content.index(AI) < content.index("#oddeyes")  # visible before Instagram folds the text
    assert content.startswith("the right eye is ice-blue")


# ---- publish_due + the Postiz adapter together --------------------------------------------------


def test_publish_due_through_the_postiz_adapter(tmp_path):
    rig = Rig(tmp_path)
    p = rig.post()
    run = FakeRun()
    publisher = PostizPublisher(run)

    summary = rig.run(publisher)

    got = rig.get(p)
    assert got.status is PostStatus.posted and got.platform_post_id == "pz-post-9"
    assert summary["errors"] == []
    assert json.loads(run.option("posts:create", "--settings"))["content_posting_method"] == "DIRECT_POST"
    assert run.uploaded_bytes == MASTER


def test_a_400_from_postiz_is_retried_but_a_502_is_not_end_to_end(tmp_path):
    rig = Rig(tmp_path)
    bad_request = rig.post("@biscuit.tt")
    bad_gateway = rig.post("@reginald.tt")

    def create(argv):  # the status depends on which integration the post goes to
        status = 400 if "int-bis-tt" in argv else 502
        return 1, "", f"❌ Failed to create post: Request failed: API Error ({status}): x"

    run = FakeRun(create=create)
    publisher = PostizPublisher(run)

    rig.run(publisher)
    retried = rig.get(bad_request)
    assert (retried.status, retried.attempts) == (PostStatus.scheduled, 1)  # refused: try again
    unsure = rig.get(bad_gateway)
    assert (unsure.status, unsure.attempts) == (PostStatus.needs_check, 0)  # may exist: a human looks
    assert "502" in unsure.error

    rig.run(publisher, NOW + timedelta(minutes=15))
    assert rig.get(bad_gateway).status is PostStatus.needs_check
    by_integration = [c[c.index("-i") + 1] for c in run.calls if c[1] == "posts:create"]
    assert by_integration.count("int-reg-tt") == 1  # the 502 post was never sent again
    assert by_integration.count("int-bis-tt") == 2  # the 400 post was


def test_a_posts_create_timeout_ends_in_needs_check_end_to_end(tmp_path):
    rig = Rig(tmp_path)
    p = rig.post()
    run = FakeRun(raises={"posts:create": subprocess.TimeoutExpired(["postiz"], 180)})
    publisher = PostizPublisher(run)
    rig.run(publisher)
    rig.run(publisher, NOW + timedelta(minutes=15))
    assert rig.get(p).status is PostStatus.needs_check
    assert [c[1] for c in run.calls].count("posts:create") == 1


# ---- CLI ---------------------------------------------------------------------------------------


@pytest.fixture
def cli(tmp_path, monkeypatch):
    rig = Rig(tmp_path)
    monkeypatch.setattr(publish, "open_store", lambda: rig.store)
    monkeypatch.setattr(publish, "open_storage", lambda: rig.storage)
    monkeypatch.setattr(publish, "now_london", lambda: NOW)
    monkeypatch.setenv("POSTIZ_API_KEY", "pz-key-DO-NOT-LEAK")
    monkeypatch.setattr(publish, "which", lambda name: f"/usr/local/bin/{name}")
    return rig


def invoke(*args: str):
    return CliRunner().invoke(app, ["publish", *args])


# ---- `studio publish resolve`: a human settles a needs_check / failed post ---------------------------


def stuck(rig, status="needs_check", handle="@biscuit.tt", **kw):
    return rig.post(handle, status=status, claimed_at=SLOT, **kw)


@pytest.mark.parametrize("status", ["needs_check", "failed"])
def test_resolve_live_marks_the_post_posted_with_its_id_and_url(cli, status):
    p = stuck(cli, status, attempts=3, error="boom")
    r = invoke("resolve", p.id, "--live", "--platform-post-id", "pz-77", "--url", "https://tiktok.test/v/1")
    assert r.exit_code == 0, r.output
    got = cli.get(p)
    assert (got.status, got.platform_post_id, got.url, got.error) == (
        PostStatus.posted, "pz-77", "https://tiktok.test/v/1", None,
    )
    assert json.loads(r.stdout)["post"]["status"] == "posted"


def test_resolve_live_moves_the_clip_to_posted_once_all_its_posts_are(cli):
    clip = cli.clip()
    live = stuck(cli, "needs_check", clip=clip)  # its only post
    r = invoke("resolve", live.id, "--live", "--platform-post-id", "pz-1")
    assert r.exit_code == 0 and json.loads(r.stdout)["clip_posted"] is True
    assert cli.store.get_clip(clip.id).state is ClipState.posted


def test_resolve_live_leaves_the_clip_scheduled_while_a_sibling_is_unsettled(tmp_path, monkeypatch):
    rig = Rig(tmp_path, instagram=True)
    monkeypatch.setattr(publish, "open_store", lambda: rig.store)
    clip = rig.clip()
    live = rig.post("@biscuit.tt", clip=clip, status="needs_check", claimed_at=SLOT)
    rig.post("@biscuit.ig", clip=clip, status="needs_check", claimed_at=SLOT)
    r = invoke("resolve", live.id, "--live", "--platform-post-id", "pz-1")
    assert r.exit_code == 0 and json.loads(r.stdout)["clip_posted"] is False
    assert rig.store.get_clip(clip.id).state is ClipState.scheduled


def test_resolve_live_needs_the_platform_post_id(cli):
    p = stuck(cli)
    r = invoke("resolve", p.id, "--live")
    assert r.exit_code == 2 and "--platform-post-id" in r.output
    assert cli.get(p).status is PostStatus.needs_check


@pytest.mark.parametrize("status", ["scheduled", "posting", "posted"])
def test_resolve_only_touches_needs_check_or_failed_posts(cli, status):
    p = cli.post(status=status, claimed_at=SLOT if status != "scheduled" else None, platform_post_id="x" if status == "posted" else None)
    for flags in (["--live", "--platform-post-id", "pz-9"], ["--retry"]):
        r = invoke("resolve", p.id, *flags)
        assert r.exit_code == 2 and status in r.output
    reason = cli.tmp / "r.txt"
    reason.write_text("why", encoding="utf-8")
    assert invoke("resolve", p.id, "--drop", "--reason-file", str(reason)).exit_code == 2
    assert cli.get(p).status.value == status


def test_resolve_wants_exactly_one_action(cli):
    p = stuck(cli)
    assert invoke("resolve", p.id).exit_code == 2
    r = invoke("resolve", p.id, "--live", "--platform-post-id", "pz-1", "--retry")
    assert r.exit_code == 2 and "exactly one" in r.output
    assert cli.get(p).status is PostStatus.needs_check
    assert invoke("resolve", "no-such-post", "--retry").exit_code == 2


@pytest.mark.parametrize("status", ["needs_check", "failed"])
def test_resolve_retry_puts_the_post_back_to_scheduled_for_the_next_run(cli, status):
    p = stuck(cli, status, attempts=3, error="boom")
    r = invoke("resolve", p.id, "--retry")
    assert r.exit_code == 0, r.output
    got = cli.get(p)
    assert (got.status, got.claimed_at, got.attempts, got.error) == (PostStatus.scheduled, None, 0, None)
    pub = FakePublisher()
    cli.run(pub)  # the 15-minute job now publishes it
    assert len(pub.calls) == 1 and cli.get(p).status is PostStatus.posted


def test_resolve_retry_at_sets_the_time_and_needs_an_aware_or_london_time(cli):
    p = stuck(cli)
    r = invoke("resolve", p.id, "--retry", "--at", "2026-10-08T19:00")
    assert r.exit_code == 0, r.output
    assert cli.get(p).scheduled_for == datetime(2026, 10, 8, 19, 0, tzinfo=LONDON)
    assert invoke("resolve", stuck(cli, handle="@reginald.tt").id, "--retry", "--at", "tomorrow").exit_code == 2


def test_resolve_retry_refuses_a_clip_that_is_no_longer_scheduled(cli):
    clip = cli.clip(state=ClipState.rejected)
    p = stuck(cli, clip=clip)
    r = invoke("resolve", p.id, "--retry")
    assert r.exit_code == 2 and "rejected" in r.output and cli.get(p).status is PostStatus.needs_check


def test_resolve_drop_deletes_the_row_and_rejects_a_clip_left_without_posts(cli):
    clip = cli.clip()
    p = stuck(cli, "failed", clip=clip, error="boom")
    reason = cli.tmp / "reason.txt"
    reason.write_text("the master was wrong; do not post $(rm -rf /)\n", encoding="utf-8")
    r = invoke("resolve", p.id, "--drop", "--reason-file", str(reason))
    assert r.exit_code == 0, r.output
    assert cli.store.list_posts(id=p.id) == []
    got = cli.store.get_clip(clip.id)
    assert got.state is ClipState.rejected and got.reject_reason == "the master was wrong; do not post $(rm -rf /)"
    out = json.loads(r.stdout)
    assert out["dropped"] == p.id and out["clip_state"] == "rejected"


def test_resolve_drop_keeps_the_clip_while_it_still_has_other_posts(tmp_path, monkeypatch):
    rig = Rig(tmp_path, instagram=True)
    monkeypatch.setattr(publish, "open_store", lambda: rig.store)
    clip = rig.clip()
    gone = rig.post("@biscuit.tt", clip=clip, status="needs_check", claimed_at=SLOT)
    rig.post("@biscuit.ig", clip=clip)
    reason = tmp_path / "r.txt"
    reason.write_text("not live", encoding="utf-8")
    r = invoke("resolve", gone.id, "--drop", "--reason-file", str(reason))
    assert r.exit_code == 0 and json.loads(r.stdout)["clip_state"] == "scheduled"
    assert rig.store.get_clip(clip.id).state is ClipState.scheduled and len(rig.store.list_posts(clip_id=clip.id)) == 1


def test_resolve_drop_needs_a_reason_and_refuses_a_post_that_was_ever_live(cli):
    p = stuck(cli)
    assert invoke("resolve", p.id, "--drop").exit_code == 2  # no --reason-file
    empty = cli.tmp / "e.txt"
    empty.write_text("  \n", encoding="utf-8")
    assert invoke("resolve", p.id, "--drop", "--reason-file", str(empty)).exit_code == 2
    reason = cli.tmp / "r.txt"
    reason.write_text("why", encoding="utf-8")
    cli.store.add_snapshot(Snapshot(post_id=p.id, views=10))  # it has metrics: it was live
    r = invoke("resolve", p.id, "--drop", "--reason-file", str(reason))
    assert r.exit_code == 2 and "snapshot" in r.output
    assert cli.store.list_posts(id=p.id) != []


def test_resolve_is_in_the_publish_help():
    r = invoke("--help")
    assert r.exit_code == 0 and "resolve" in r.output


def test_cli_lists_due_and_dry_run():
    r = invoke("due", "--help")
    assert r.exit_code == 0 and "--dry-run" in r.output
    assert "due" in invoke("--help").output


def test_cli_dry_run_needs_neither_storage_nor_postiz(cli, monkeypatch):
    p = cli.post()
    monkeypatch.delenv("POSTIZ_API_KEY")
    monkeypatch.setattr(publish, "which", lambda name: None)
    monkeypatch.setattr(publish, "open_storage", lambda: pytest.fail("dry-run opened storage"))
    r = invoke("due", "--dry-run")
    assert r.exit_code == 0, r.output
    out = json.loads(r.stdout)
    assert [x["post_id"] for x in out["would_post"]] == [p.id]
    assert cli.get(p).status is PostStatus.scheduled


def test_cli_due_publishes_and_prints_the_summary(cli, monkeypatch):
    p = cli.post()
    pub = FakePublisher()
    monkeypatch.setattr(publish, "PostizPublisher", lambda: pub)
    r = invoke("due")
    assert r.exit_code == 0, r.output
    out = json.loads(r.stdout)
    assert [x["post_id"] for x in out["posted"]] == [p.id]
    assert cli.get(p).status is PostStatus.posted
    assert "pz-key-DO-NOT-LEAK" not in r.output


def test_cli_due_exits_1_when_an_outcome_could_not_be_recorded(tmp_path, monkeypatch):
    rig = Rig(tmp_path)
    flaky = FlakyStore(characters=rig.store.characters(), accounts=rig.store.accounts())
    rig.store = flaky
    rig.post()
    monkeypatch.setattr(publish, "open_store", lambda: flaky)
    monkeypatch.setattr(publish, "open_storage", lambda: rig.storage)
    monkeypatch.setattr(publish, "now_london", lambda: NOW)
    monkeypatch.setenv("POSTIZ_API_KEY", "k")
    monkeypatch.setattr(publish, "which", lambda name: "/bin/postiz")
    monkeypatch.setattr(publish, "PostizPublisher", lambda: FakePublisher())
    r = invoke("due")
    assert r.exit_code == 1
    assert json.loads(r.stdout)["errors"]


def test_cli_due_without_postiz_key_is_a_caller_error(cli, monkeypatch):
    monkeypatch.delenv("POSTIZ_API_KEY")
    r = invoke("due")
    assert r.exit_code == 2
    assert "POSTIZ_API_KEY" in r.stderr


def test_cli_due_without_the_postiz_binary_is_a_caller_error(cli, monkeypatch):
    monkeypatch.setattr(publish, "which", lambda name: None)
    r = invoke("due")
    assert r.exit_code == 2
    assert "postiz" in r.stderr and "npm" in r.stderr


def test_cli_due_without_database_url_is_a_caller_error(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    r = invoke("due")
    assert r.exit_code == 2 and "DATABASE_URL" in r.stderr
