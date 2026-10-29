"""``studio clip crosspost``: a posted clip goes out once more on the character's account on another platform (TikTok).

The clip stays ``posted`` throughout: when the post is added, when it goes out, when Postiz reports it failed. Everything runs on
``MemoryStore`` + ``LocalStorage``; Postiz is a fake ``run`` (or a fake publisher / lister), so no ``postiz`` binary, network or
account is involved.
"""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from studio import clips, metrics
from studio.cli import app
from studio.clips import CROSSPOST_KEY, crosspost_clip, is_crosspost
from studio.config import LONDON
from studio.models import Account, Character, Clip, ClipState, Favorite, Mode, Platform, Post, PostStatus, Settings
from studio.planning import DAILY_CAP, FAMILY_GAP_DAYS
from studio.publish.base import PublishResult, UncertainPublish, preview_due, publish_due
from studio.publish.confirm import confirm_posts
from studio.publish.postiz import TIKTOK_SETTINGS, PostizPublisher
from studio.publish.reach import NO_REACH, Reach, ReachConfig, plan_post
from studio.publish.resolve import resolve_drop, resolve_retry
from studio.storage import LocalStorage
from studio.store import MemoryStore

S = ClipState
CADENCE = {
    "franz": {"days": ["tue", "wed", "thu"], "slot": "19:00"},
    "reginald": {"days": ["tue", "wed", "thu"], "slot": "19:30"},
}
TUE = datetime(2026, 10, 6, 8, 0, tzinfo=LONDON)  # Tue 6 Oct 2026, 08:00 BST: the morning the owner asks
EVENING = datetime(2026, 10, 6, 20, 0, tzinfo=LONDON)  # the publish run after Franz's 19:00 slot
OUT = datetime(2026, 9, 15, 19, 0, tzinfo=LONDON)  # when the clips' Instagram Reels went out (long before confirm's 14 days)
MASTER = b"\x00\x00\x00 ftypmp42 pretend-master-bytes"


def slot(day: int, hour: int = 19, minute: int = 0, month: int = 10) -> datetime:
    return datetime(2026, month, day, hour, minute, tzinfo=LONDON)


# ---- helpers -----------------------------------------------------------------------------------


def make_store(
    *, mode: str = "auto", handle: str | None = "@franz.tt", integration: str | None = "int-tt", tiktok: bool = True,
    cadence: dict[str, Any] | None = None,
) -> MemoryStore:
    """Franz (live) with an Instagram account and, unless ``tiktok`` is off, a TikTok one; Reginald (live) with both."""
    accounts = [
        Account(character_slug="franz", platform="instagram", handle="@franz.ig", postiz_integration_id="int-ig", mode="auto"),
        Account(character_slug="reginald", platform="instagram", handle="@reginald.ig", postiz_integration_id="int-reg-ig", mode="auto"),
        Account(character_slug="reginald", platform="tiktok", handle="@reginald.tt", postiz_integration_id="int-reg-tt", mode="auto"),
    ]  # fmt: skip
    if tiktok:
        accounts.append(
            Account(character_slug="franz", platform="tiktok", handle=handle or "", postiz_integration_id=integration, mode=mode)
        )
    return MemoryStore(
        settings=Settings(cadence=CADENCE if cadence is None else cadence),
        characters=[Character(slug="franz", name="Franz", status="live"), Character(slug="reginald", name="Reginald", status="live")],
        accounts=accounts,
    )  # fmt: skip


class World:
    """A store, a storage and a counter of clips."""

    def __init__(self, tmp_path: Path, **store_kw: Any) -> None:
        self.store = make_store(**store_kw)
        self.storage = LocalStorage(tmp_path / "store")
        self.tmp = tmp_path
        self.n = 0

    def account(self, handle: str) -> Account:
        return next(a for a in self.store.accounts() if a.handle == handle)

    def clip(self, character: str = "franz", state: ClipState = S.posted, **features: Any) -> Clip:
        self.n += 1
        local = self.tmp / f"master-{self.n}.mp4"
        local.write_bytes(MASTER)
        key = self.storage.upload("clips", f"masters/m{self.n}.mp4", local)
        return self.store.add_clip(
            Clip(character_slug=character, mode=Mode.recreate, state=state, master_path=key, caption=f"caption {self.n}",
                 hashtags=["oddeyes", "#franz"], features=features)
        )  # fmt: skip

    def posted_clip(self, character: str = "franz", *, ig_url: str | None = "https://www.instagram.com/reel/x/", **features: Any) -> Clip:
        """A clip that is ``posted``: its Instagram Reel went out on 15 Sep (``ig_url`` None: Postiz has not confirmed it)."""
        clip = self.clip(character, **features)
        ig = self.account("@franz.ig" if character == "franz" else "@reginald.ig")
        self.store.add_post(
            Post(clip_id=clip.id, account_id=ig.id, scheduled_for=OUT, status="posted", claimed_at=OUT,
                 platform_post_id=f"ig-{clip.id}", url=ig_url)
        )  # fmt: skip
        return clip

    def tiktok_post(self, clip: Clip, when: datetime, status: str = "posted", handle: str = "@franz.tt", **fields: Any) -> Post:
        fields.setdefault("claimed_at", when if status in ("posted", "posting", "needs_check") else None)
        return self.store.add_post(
            Post(clip_id=clip.id, account_id=self.account(handle).id, scheduled_for=when, status=status, **fields)
        )  # fmt: skip

    def crosspost(self, clip: Clip, **kw: Any) -> Post:
        kw.setdefault("now", TUE)
        return crosspost_clip(self.store, clip.id, "tiktok", **kw)[1]

    def run(self, publisher: Any, now: datetime = EVENING, reach: ReachConfig | None = None) -> dict[str, Any]:
        return publish_due(self.store, self.storage, publisher, now, reach=reach or ReachConfig())

    def get(self, post: Post) -> Post:
        return self.store.list_posts(id=post.id)[0]

    def state(self, clip: Clip) -> ClipState:
        return self.store.get_clip(clip.id).state


@pytest.fixture
def world(tmp_path) -> World:
    return World(tmp_path)


class FakePublisher:
    """Records every call; ids are ``pz-1``, ``pz-2``...; ``fail`` is raised instead of answering."""

    def __init__(self, fail: Exception | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self.stories: list[dict[str, Any]] = []
        self.fail = fail

    def publish(self, *, platform, integration_id, media_url, caption, hashtags, ai_label, reach=NO_REACH) -> PublishResult:
        self.calls.append(dict(platform=platform, integration_id=integration_id, media_url=media_url, caption=caption,
                               hashtags=hashtags, ai_label=ai_label, reach=reach))  # fmt: skip
        if self.fail is not None:
            raise self.fail
        return PublishResult(platform_post_id=f"pz-{len(self.calls)}", url=f"https://example.test/v/{len(self.calls)}")

    def publish_story(self, *, integration_id, media_url, ai_label) -> PublishResult:
        self.stories.append(dict(integration_id=integration_id, media_url=media_url, ai_label=ai_label))
        return PublishResult(platform_post_id=f"story-{len(self.stories)}")


# ---- the post: which account, which slot --------------------------------------------------------


def test_a_posted_clip_gets_one_scheduled_tiktok_post_and_stays_posted(world):
    clip = world.posted_clip()
    ig_post = world.store.list_posts(clip_id=clip.id)[0]

    done, post = crosspost_clip(world.store, clip.id, "tiktok", now=TUE)

    assert post.id and post.status is PostStatus.scheduled and post.account_id == world.account("@franz.tt").id
    assert post.scheduled_for == slot(6)  # the first cadence slot: its Instagram Reel's day is another account's business
    assert (post.claimed_at, post.platform_post_id, post.url, post.attempts) == (None, None, None, 0)
    assert done.state is S.posted and world.state(clip) is S.posted  # the state never moves
    assert sorted(p.id for p in world.store.list_posts(clip_id=clip.id)) == sorted([ig_post.id, post.id])
    assert world.get(ig_post) == ig_post  # the Reel's own post is not touched
    record = world.store.get_clip(clip.id).features[CROSSPOST_KEY]
    assert record == {"tiktok": {"post_id": post.id, "at": TUE.isoformat()}} and is_crosspost(world.store.get_clip(clip.id), post)
    assert not is_crosspost(world.store.get_clip(clip.id), ig_post)


def test_the_other_features_of_the_clip_are_kept(world):
    clip = world.posted_clip(hook_text="two ways", first_comment_posted=True)
    world.crosspost(clip)
    features = world.store.get_clip(clip.id).features
    assert features["hook_text"] == "two ways" and features["first_comment_posted"] is True and set(features) == {"hook_text", "first_comment_posted", CROSSPOST_KEY}


def test_the_slot_is_the_first_cadence_day_the_tiktok_account_does_not_post(world):
    world.tiktok_post(world.posted_clip(), slot(6), status="posted")  # another clip of his, on Tue
    world.tiktok_post(world.posted_clip(), slot(7), status="scheduled")  # and one waiting for Wed
    world.tiktok_post(world.posted_clip(), slot(8), status="failed")  # a failed post never took a day
    assert world.crosspost(world.posted_clip()).scheduled_for == slot(8)


def test_a_day_with_a_post_on_another_account_is_still_free_for_tiktok(world):
    clip = world.posted_clip()
    ig_other = world.account("@franz.ig")
    other = world.clip()
    world.store.add_post(Post(clip_id=other.id, account_id=ig_other.id, scheduled_for=slot(6), status="scheduled"))
    assert world.crosspost(clip).scheduled_for == slot(6)


def test_two_crossposts_never_share_a_day_and_the_cap_holds(world):
    first, second, third = world.posted_clip(), world.posted_clip(), world.posted_clip()
    days = [world.crosspost(c).scheduled_for for c in (first, second, third)]
    assert days == [slot(6), slot(7), slot(8)]  # one a day: well inside the two-a-day cap


def test_the_slot_is_after_now_not_before(world):
    clip = world.posted_clip()
    assert world.crosspost(clip, now=slot(6, 20)).scheduled_for == slot(7)  # Tuesday's slot has gone


def test_the_slot_keeps_the_family_two_weeks_apart(world):
    """One dance used by Reginald and Franz: their posts, on any account, are 14 days apart."""
    root = world.store.add_favorite(Favorite(url="owner-drop:root", platform="drop", origin="owner", status="made",
                                             character_slug="reginald", proposal={"drop": {"state": "made"}}))  # fmt: skip
    version = world.store.add_favorite(Favorite(url="owner-drop:version", platform="drop", origin="owner", status="made",
                                                character_slug="franz", proposal={"drop": {"state": "made", "copy_of": root.id}}))  # fmt: skip
    reginald_clip = world.posted_clip("reginald", fav_id=root.id)
    franz_clip = world.posted_clip("franz", fav_id=version.id)
    world.store.update_favorite(root.id, clip_id=reginald_clip.id)
    world.store.update_favorite(version.id, clip_id=franz_clip.id)
    world.tiktok_post(reginald_clip, slot(6, 19, 30), status="scheduled", handle="@reginald.tt")  # Reginald's goes out Tue 6 Oct

    post = world.crosspost(franz_clip)

    assert FAMILY_GAP_DAYS == 14 and post.scheduled_for == slot(20)  # Tue 20 Oct: the first cadence day 14 days on
    assert world.crosspost(world.posted_clip(), now=TUE).scheduled_for == slot(6)  # a clip of no family is not held back


def test_at_is_taken_as_given_and_must_be_aware(world):
    clip = world.posted_clip()
    with pytest.raises(ValueError, match="timezone-aware"):
        crosspost_clip(world.store, clip.id, "tiktok", at=datetime(2026, 10, 9, 19, 0), now=TUE)
    assert len(world.store.list_posts(clip_id=clip.id)) == 1 and CROSSPOST_KEY not in world.store.get_clip(clip.id).features
    at = datetime(2026, 10, 10, 7, 45, tzinfo=timezone.utc)  # a Saturday: not a cadence day, the owner's own choice
    assert world.crosspost(clip, at=at).scheduled_for == at


def test_the_cap_of_two_posts_per_london_day_refuses_a_third_at_a_given_time(world):
    world.tiktok_post(world.posted_clip(), slot(13, 12), status="scheduled")
    world.tiktok_post(world.posted_clip(), slot(13, 18), status="posted")
    clip = world.posted_clip()
    before = len(world.store.list_posts())

    with pytest.raises(ValueError, match=rf"already has {DAILY_CAP} posts on 2026-10-13"):
        crosspost_clip(world.store, clip.id, "tiktok", at=slot(13, 21), now=TUE)

    assert len(world.store.list_posts()) == before and CROSSPOST_KEY not in world.store.get_clip(clip.id).features
    assert world.crosspost(clip, at=slot(14, 12)).scheduled_for == slot(14, 12)  # another day is fine
    other = world.posted_clip()
    world.tiktok_post(other, slot(15, 12), status="scheduled")
    assert world.crosspost(world.posted_clip(), at=slot(15, 21)).scheduled_for == slot(15, 21)  # a second post that day is allowed


def test_the_cap_counts_london_days_and_ignores_failed_posts(world):
    late = datetime(2026, 10, 13, 22, 30, tzinfo=timezone.utc)  # 23:30 BST on the 13th
    after_midnight = datetime(2026, 10, 13, 23, 30, tzinfo=timezone.utc)  # 00:30 BST on the 14th
    world.tiktok_post(world.posted_clip(), late, status="posted")
    world.tiktok_post(world.posted_clip(), after_midnight, status="posted")
    world.tiktok_post(world.posted_clip(), slot(15, 12), status="failed")
    world.tiktok_post(world.posted_clip(), slot(15, 13), status="failed")
    assert world.crosspost(world.posted_clip(), at=slot(13, 12)).scheduled_for == slot(13, 12)  # one London post on the 13th
    assert world.crosspost(world.posted_clip(), at=slot(15, 12)).scheduled_for == slot(15, 12)  # failed posts hold no day


def test_a_post_that_appears_between_the_lookup_and_the_insert_is_a_refusal(world, monkeypatch):
    clip = world.posted_clip()
    real_add = world.store.add_post

    def racing_add(post):  # another process wins the (clip, account) slot first
        real_add(Post(clip_id=post.clip_id, account_id=post.account_id, scheduled_for=slot(1, 12)))
        return real_add(post)  # -> DuplicatePost

    monkeypatch.setattr(world.store, "add_post", racing_add)
    with pytest.raises(ValueError, match="already has a post"):
        crosspost_clip(world.store, clip.id, "tiktok", now=TUE)


# ---- the refusals: ValueError (exit 2 on the command line), nothing written ---------------------


def refused(world: World, clip: Clip, match: str, **kw: Any) -> None:
    before_posts, before_clip = world.store.list_posts(), world.store.get_clip(clip.id)
    with pytest.raises(ValueError, match=match):
        crosspost_clip(world.store, clip.id, "tiktok", now=TUE, **kw)
    assert world.store.list_posts() == before_posts and world.store.get_clip(clip.id) == before_clip


@pytest.mark.parametrize("state", [s for s in ClipState if s is not S.posted], ids=lambda s: s.value)
def test_a_clip_that_is_not_posted_is_refused(world, state):
    refused(world, world.clip(state=state), rf"is {state.value}: only a posted clip is cross-posted")


def test_a_variant_is_refused_only_originals_cross_post(world):
    original = world.posted_clip()
    variant = world.posted_clip(variant_of=original.id)
    refused(world, variant, rf"variant of {original.id}.*only an original")
    assert world.crosspost(original).clip_id == original.id  # the original is fine


@pytest.mark.parametrize(
    "store_kw",
    [{"tiktok": False}, {"handle": None}, {"integration": None}],
    ids=["no tiktok account", "no handle yet", "not connected in Postiz"],
)
def test_a_character_without_a_connected_account_on_the_platform_is_refused(tmp_path, store_kw):
    w = World(tmp_path, **store_kw)
    refused(w, w.posted_clip(), "no connected tiktok account for 'franz'.*Postiz integration id")


def test_a_clip_that_already_has_a_post_on_that_account_is_refused(world):
    clip = world.posted_clip()
    first = world.crosspost(clip)
    refused(world, clip, r"already has a post on @franz\.tt \(scheduled")
    world.store.update_post(first.id, status=PostStatus.failed)
    refused(world, clip, rf"\(failed, post {first.id}\).*studio publish resolve {first.id}")
    world.store.update_post(first.id, status=PostStatus.posted)
    refused(world, clip, r"\(posted")


def test_an_account_in_approval_mode_is_refused(tmp_path):
    w = World(tmp_path, mode="approval")
    refused(w, w.posted_clip(), r"@franz\.tt is in approval mode.*autopilot")
    w.store.update_account(w.account("@franz.tt").id, mode="auto")
    assert w.crosspost(w.store.list_clips()[0]).status is PostStatus.scheduled  # switched on: it goes through


def test_a_clip_without_a_master_file_is_refused(world):
    clip = world.posted_clip()
    world.store.update_clip(clip.id, master_path=None)
    refused(world, clip, "no master file")


def test_an_unknown_clip_is_a_key_error(world):
    with pytest.raises(KeyError):
        crosspost_clip(world.store, "nope", "tiktok", now=TUE)


def test_a_character_without_a_slot_is_refused_before_anything_is_written(tmp_path):
    w = World(tmp_path, cadence={})
    clip = w.posted_clip()
    refused(w, clip, "slot")
    assert w.crosspost(clip, at=slot(9, 12)).scheduled_for == slot(9, 12)  # an explicit time needs no cadence


# ---- the command line --------------------------------------------------------------------------


@pytest.fixture
def cli_world(tmp_path, monkeypatch) -> World:
    w = World(tmp_path)
    monkeypatch.setattr(clips, "open_store", lambda: w.store)
    monkeypatch.setattr(clips, "now_london", lambda: TUE)
    return w


def run(*args: str):
    return CliRunner().invoke(app, ["clip", *args])


def test_clip_help_lists_crosspost():
    r = run("--help")
    assert r.exit_code == 0 and "crosspost" in r.output
    assert "--platform" in run("crosspost", "--help").output


def test_cli_crosspost_prints_the_clip_and_the_new_post(cli_world):
    clip = cli_world.posted_clip()
    r = run("crosspost", clip.id, "--platform", "tiktok")
    assert r.exit_code == 0, r.output
    out = json.loads(r.stdout)
    assert out["clip"]["state"] == "posted" and out["clip"]["id"] == clip.id and out["clip"]["next_states"] == []
    assert out["post"]["status"] == "scheduled" and out["post"]["scheduled_for"] == slot(6).isoformat()
    assert out["post"]["account_id"] == cli_world.account("@franz.tt").id
    assert cli_world.state(clip) is S.posted and len(cli_world.store.list_posts(clip_id=clip.id)) == 2


def test_cli_crosspost_at_takes_iso_with_or_without_an_offset(cli_world):
    a, b = cli_world.posted_clip(), cli_world.posted_clip()
    r = run("crosspost", a.id, "--platform", "tiktok", "--at", "2026-10-09T18:30:00+01:00")
    assert r.exit_code == 0, r.output
    assert json.loads(r.stdout)["post"]["scheduled_for"] == "2026-10-09T18:30:00+01:00"
    r = run("crosspost", b.id, "--platform", "tiktok", "--at", "2026-12-01T19:00")  # London wall clock: GMT in December
    assert r.exit_code == 0, r.output
    assert json.loads(r.stdout)["post"]["scheduled_for"] == "2026-12-01T19:00:00+00:00"


def test_cli_crosspost_refusals_exit_2_and_write_nothing(cli_world):
    assert run("crosspost", "nope", "--platform", "tiktok").exit_code == 2  # unknown clip
    not_out = cli_world.clip(state=S.mastered)
    r = run("crosspost", not_out.id, "--platform", "tiktok")
    assert r.exit_code == 2 and "only a posted clip" in r.output
    clip = cli_world.posted_clip()
    r = run("crosspost", clip.id, "--platform", "tiktok", "--at", "tomorrow")
    assert r.exit_code == 2 and "--at" in r.output
    assert run("crosspost", clip.id).exit_code == 2  # --platform is required
    assert run("crosspost", clip.id, "--platform", "youtube").exit_code == 2
    assert run("crosspost", clip.id, "--platform", "tiktok").exit_code == 0
    again = run("crosspost", clip.id, "--platform", "tiktok")
    assert again.exit_code == 2 and "already has a post" in again.output
    assert len(cli_world.store.list_posts(clip_id=clip.id)) == 2


def test_cli_crosspost_refuses_a_variant_and_an_approval_mode_account(tmp_path, monkeypatch):
    w = World(tmp_path, mode="approval")
    monkeypatch.setattr(clips, "open_store", lambda: w.store)
    monkeypatch.setattr(clips, "now_london", lambda: TUE)
    clip = w.posted_clip()
    r = run("crosspost", clip.id, "--platform", "tiktok")
    assert r.exit_code == 2 and "approval mode" in r.output
    w.store.update_account(w.account("@franz.tt").id, mode="auto")
    variant = w.posted_clip(variant_of=clip.id)
    r = run("crosspost", variant.id, "--platform", "tiktok")
    assert r.exit_code == 2 and "variant" in r.output
    assert [p for p in w.store.list_posts() if p.account_id == w.account("@franz.tt").id] == []


# ---- the publish path: the post goes out, the clip is left alone ---------------------------------


def test_a_crosspost_goes_out_and_the_clip_stays_posted(world):
    clip = world.posted_clip()
    post = world.crosspost(clip)
    ig_post = next(p for p in world.store.list_posts(clip_id=clip.id) if p.id != post.id)
    features_before = {k: v for k, v in world.store.get_clip(clip.id).features.items()}
    pub = FakePublisher()

    out = world.run(pub)

    assert out["errors"] == [] and out["failed"] == [] and out["retry"] == []
    assert [p["post_id"] for p in out["posted"]] == [post.id]
    (call,) = pub.calls
    assert (call["platform"], call["integration_id"], call["ai_label"]) == (Platform.tiktok, "int-tt", True)
    assert call["caption"] == "caption 1" and call["hashtags"] == ["oddeyes", "#franz"] and call["reach"] == NO_REACH
    done = world.get(post)
    assert (done.status, done.platform_post_id, done.url, done.error) == (PostStatus.posted, "pz-1", "https://example.test/v/1", None)
    assert world.state(clip) is S.posted and out["clips_posted"] == []  # the clip was posted already and stays so
    assert world.store.get_clip(clip.id).features == features_before  # no learning tag is invented for a clip whose Reel wrote them
    assert world.get(ig_post) == ig_post


def test_nothing_instagram_only_reaches_a_tiktok_crosspost(world):
    """First comment, collaborators, Trial Reel, the Story: all of them need an Instagram Reel; the TikTok post carries none."""
    features = {
        "first_comment": "Which hat? A or B", "collab": ["reginald.ig"], "story_path": "masters/m1-story.mp4",
        "test_arms": {"trial": True}, "music": "original",
    }  # fmt: skip
    clip = world.posted_clip(**features)
    post = world.crosspost(clip)
    config = ReachConfig(stories=True, trial_reels={"franz.ig": True}, trial_test=True)
    accounts, live = world.store.accounts(), {"franz", "reginald"}

    # the same clip on its Instagram account would carry them (so the absence below means something) ...
    reel = plan_post(world.store.get_clip(clip.id), world.account("@franz.ig"), accounts, config, live=live)
    assert reel.reach.first_comment == "Which hat? A or B" and reel.reach.collaborators == ("reginald.ig",)
    assert plan_post(world.store.get_clip(clip.id), world.account("@franz.tt"), accounts, config, live=live).reach == NO_REACH
    # ... and the dry run says the TikTok post goes with nothing of it
    (row,) = preview_due(world.store, EVENING, reach=config)["would_post"]
    assert row["post_id"] == post.id and row["platform"] == "tiktok"
    assert row["reach"] == {"first_comment": False, "collaborators": [], "collab_dropped": [], "trial_reel": False, "story": False}

    pub = FakePublisher()
    out = world.run(pub, reach=config)

    assert out["errors"] == [] and [p["post_id"] for p in out["posted"]] == [post.id]
    assert pub.calls[0]["reach"] == NO_REACH and pub.calls[0]["platform"] is Platform.tiktok
    assert pub.stories == [] and out["stories"] == []  # no Story follows a TikTok post
    got = world.store.get_clip(clip.id).features
    assert "story" not in got and got["first_comment"] == "Which hat? A or B"  # nothing recorded, nothing taken from the clip
    assert "first_comment_posted" not in got and "trial_reel" not in got


def test_a_trial_reel_arm_never_makes_a_tiktok_post_a_trial(world):
    clip = world.posted_clip(test_arms={"trial": True})
    world.crosspost(clip)
    pub = FakePublisher()
    world.run(pub, reach=ReachConfig(trial_reels={"franz.ig": True, "franz.tt": True}, trial_test=True))
    assert pub.calls[0]["reach"].trial_reel is False


class FakeRun:
    """``subprocess.run`` stand-in for the Postiz CLI: ``upload`` and ``posts:create`` answer, argv is recorded."""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def __call__(self, argv, **kw):
        self.calls.append(list(argv))
        out = {
            "upload": '✅ File uploaded successfully!\n{"id": "m1", "path": "https://uploads.postiz.test/abc.mp4"}\n',
            "posts:create": '✅ Post created successfully!\n[{"postId": "pz-post-9", "integration": "int-tt"}]\n',
        }[argv[1]]
        return subprocess.CompletedProcess(argv, 0, stdout=out, stderr="")


def test_through_the_postiz_adapter_the_tiktok_ai_label_is_on_and_there_is_no_comment(world):
    """The real adapter, a posted clip with a first comment: TikTok's AI-generated flag is set, one content, no Instagram key."""
    clip = world.posted_clip(first_comment="Which hat? A or B", collab=["reginald.ig"])
    post = world.crosspost(clip)
    run_ = FakeRun()

    out = world.run(PostizPublisher(run_, clock=lambda: EVENING.astimezone(timezone.utc)))

    assert out["errors"] == [] and [p["post_id"] for p in out["posted"]] == [post.id]
    (create,) = [c for c in run_.calls if c[1] == "posts:create"]
    settings = json.loads(create[create.index("--settings") + 1])
    assert settings == TIKTOK_SETTINGS and settings["video_made_with_ai"] is True  # TikTok's AI-generated content flag (is_aigc)
    assert settings["content_posting_method"] == "DIRECT_POST" and not {"post_type", "collaborators", "is_trial_reel"} & set(settings)
    contents = [a for a in create if a.startswith("--content=")]
    assert len(contents) == 1 and "AI-generated character" in contents[0]  # the caption's AI line, and no second content (a comment)
    assert create[create.index("-i") + 1] == "int-tt"
    assert world.get(post).platform_post_id == "pz-post-9" and world.state(clip) is S.posted


def test_a_crosspost_that_fails_is_retried_and_the_clip_stays_posted(world):
    clip = world.posted_clip()
    post = world.crosspost(clip)
    out = world.run(FakePublisher(fail=RuntimeError("API Error (500): boom")))
    assert [r["post_id"] for r in out["retry"]] == [post.id]
    got = world.get(post)
    assert (got.status, got.attempts, got.claimed_at) == (PostStatus.scheduled, 1, None) and world.state(clip) is S.posted


def test_an_uncertain_crosspost_goes_to_needs_check_and_the_clip_stays_posted(world):
    clip = world.posted_clip()
    post = world.crosspost(clip)
    out = world.run(FakePublisher(fail=UncertainPublish("timed out: the post may exist")))
    assert [r["post_id"] for r in out["needs_check"]] == [post.id]
    assert world.get(post).status is PostStatus.needs_check and world.state(clip) is S.posted


def test_the_daily_cap_defers_a_third_post_of_the_account_and_the_clip_stays_posted(world):
    clip = world.posted_clip()
    post = world.crosspost(clip)  # Tue 19:00
    for hour in (12, 18):  # then two others of the account went out the same day
        world.tiktok_post(world.posted_clip(), slot(6, hour), status="posted")
    pub = FakePublisher()

    out = world.run(pub)

    assert pub.calls == [] and [r["post_id"] for r in out["rescheduled"]] == [post.id]
    got = world.get(post)
    assert got.status is PostStatus.scheduled and got.scheduled_for == slot(7) and world.state(clip) is S.posted


def test_a_silent_master_is_not_cross_posted_on_autopilot(world):
    clip = world.posted_clip(music="in_app")
    post = world.crosspost(clip)
    pub = FakePublisher()
    out = world.run(pub)
    assert pub.calls == [] and [f["post_id"] for f in out["failed"]] == [post.id]
    assert "silent master" in world.get(post).error and world.state(clip) is S.posted


def test_a_clip_that_is_no_longer_publishable_is_still_refused(world):
    clip = world.clip(state=S.rejected)
    post = world.tiktok_post(clip, slot(6), status="scheduled")
    pub = FakePublisher()
    out = world.run(pub)
    assert pub.calls == [] and [f["post_id"] for f in out["failed"]] == [post.id]
    assert "rejected" in world.get(post).error and "scheduled or posted" in world.get(post).error


def test_a_scheduled_crosspost_can_be_called_off_with_resolve_drop(world):
    clip = world.posted_clip()
    post = world.crosspost(clip)
    result = resolve_drop(world.store, post.id, "the owner changed his mind")
    assert world.store.list_posts(id=post.id) == [] and result["clip_state"] == "posted"
    assert world.state(clip) is S.posted
    assert world.crosspost(clip).status is PostStatus.scheduled  # and he can ask again


# ---- confirm: did Postiz really publish it? ----------------------------------------------------


class FakePostiz:
    """The ``PostLister`` of ``confirm_posts``: what ``postiz posts:list`` would print."""

    def __init__(self, *entries: dict[str, Any]) -> None:
        self.entries = list(entries)

    def list_posts(self, start: datetime, end: datetime) -> list[dict[str, Any]]:
        return self.entries


def listed(postiz_id: str, state: str, *, url: str | None = None, error: Any = None) -> dict[str, Any]:
    return {"id": postiz_id, "state": state, "releaseURL": url, "error": error, "integration": {"id": "int-tt", "providerIdentifier": "tiktok"}}


def accepted_crosspost(world: World, clip: Clip, postiz_id: str = "pz-tt") -> Post:
    """A cross-post the publisher recorded as posted (Postiz accepted it; no url yet)."""
    post = world.crosspost(clip, at=slot(6))
    return world.store.update_post(post.id, status=PostStatus.posted, claimed_at=slot(6), platform_post_id=postiz_id)


def test_confirm_fills_the_url_of_a_published_crosspost_and_leaves_the_clip(world):
    clip = world.posted_clip()
    post = accepted_crosspost(world, clip)
    out = confirm_posts(world.store, FakePostiz(listed("pz-tt", "PUBLISHED", url="https://www.tiktok.com/@franz/video/1")), EVENING)
    got = world.get(post)
    assert (got.status, got.url, got.platform_post_id) == (PostStatus.posted, "https://www.tiktok.com/@franz/video/1", "pz-tt")
    assert [c["post_id"] for c in out["confirmed"]] == [post.id] and out["failed"] == [] and out["write_errors"] == []
    assert world.state(clip) is S.posted


def test_confirm_fails_an_errored_crosspost_and_the_clip_is_never_reopened(world):
    """The Reel is posted but Postiz never confirmed it (no url, no metrics yet): a normal post's clip would be sent back to
    scheduled here. A cross-post's clip was posted before the post existed and stays so."""
    clip = world.posted_clip(ig_url=None)
    post = accepted_crosspost(world, clip)

    out = confirm_posts(world.store, FakePostiz(listed("pz-tt", "ERROR", error="TikTok said no")), EVENING)

    got = world.get(post)
    assert got.status is PostStatus.failed and got.platform_post_id is None and "state ERROR" in got.error
    assert f"studio publish resolve {post.id} --retry" in got.error
    assert [f["clip_reopened"] for f in out["failed"]] == [False]
    assert world.state(clip) is S.posted
    # the owner retries it: resolve takes a posted clip, the next publish run sends it, the clip is still posted
    resolve_retry(world.store, post.id)
    assert world.get(post).status is PostStatus.scheduled
    pub = FakePublisher()
    world.run(pub)
    assert len(pub.calls) == 1 and world.get(post).status is PostStatus.posted and world.state(clip) is S.posted


def test_confirm_still_reopens_a_clip_whose_own_post_errored(world):
    """The marker only protects a cross-post: the same error on the clip's own post keeps its old behaviour."""
    clip = world.posted_clip(ig_url=None)
    ig = world.store.list_posts(clip_id=clip.id)[0]
    world.store.update_post(ig.id, scheduled_for=slot(5), claimed_at=slot(5))  # recent enough to be asked about
    out = confirm_posts(world.store, FakePostiz(listed(ig.platform_post_id, "ERROR")), EVENING)
    assert [f["clip_reopened"] for f in out["failed"]] == [True] and world.state(clip) is S.scheduled


# ---- metrics: a cross-post is pulled like any post ---------------------------------------------


class FakeAnalytics:
    """``subprocess.run`` stand-in for ``postiz analytics:post <id> -d 7``."""

    def __init__(self, views: int) -> None:
        self.views, self.calls = views, []

    def __call__(self, argv, **kw):
        self.calls.append(list(argv))
        payload = [{"label": "Views", "data": [{"total": str(self.views), "date": "2026-10-07"}], "percentageChange": 0}]
        return subprocess.CompletedProcess(argv, 0, json.dumps(payload), "")


def test_metrics_pull_reads_a_crosspost_and_leaves_its_clip_alone(world):
    clip = world.posted_clip()
    old_ig = world.store.list_posts(clip_id=clip.id)[0]
    world.store.update_post(old_ig.id, claimed_at=datetime(2026, 8, 1, 19, 0, tzinfo=LONDON))  # long past the pull's reach
    post = accepted_crosspost(world, clip)
    fake = FakeAnalytics(views=480)
    features_before = dict(world.store.get_clip(clip.id).features)

    out = metrics.pull(world.store, fake, slot(7, 20))  # 25 hours after it went out

    assert fake.calls == [["postiz", "analytics:post", "pz-tt", "-d", "7"]]
    assert out["pulled"] == [{"post_id": post.id, "window": "24h"}] and out["errors"] == []
    (snap,) = world.store.snapshots_for(post.id)
    assert snap.views == 480 and world.state(clip) is S.posted
    assert world.store.get_clip(clip.id).features == features_before
    again = metrics.pull(world.store, fake, slot(7, 20))  # idempotent per (post, window), as for any post
    assert again["pulled"] == [] and len(fake.calls) == 1 and len(world.store.snapshots_for(post.id)) == 1
