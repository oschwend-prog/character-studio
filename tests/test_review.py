"""Weekly review data and the pre-registered KPI bars.

The bars are BINDING (the owner fixed them in advance; code never renegotiates them), so every
threshold is tested at its exact boundary: 1.5 / 0.7 with n 5 / 8, the 20 posts / 4 weeks gate,
5,000 / 100,000 / 500 / 10,000 views and the 40 % reach drop. Everything runs on ``MemoryStore``.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from typing import Any

import pytest
from typer.testing import CliRunner

from studio import review
from studio.cli import app
from studio.clips import REQUIRED_FEATURES
from studio.models import Account, Character, Clip, Post, PostStatus, Snapshot
from studio.review import (
    Lift,
    apply_ig_guard,
    character_bar,
    feature_lifts,
    format_verdicts,
    hook_proven,
    ig_guard,
    parse_week,
    review_payload,
    save_review,
)
from studio.store import MemoryStore

NOW = datetime(2026, 11, 10, 12, 0, tzinfo=timezone.utc)
D = timedelta(days=1)
H = timedelta(hours=1)

BASE_FEATURES: dict[str, Any] = {
    "format_id": "fmt-a",
    "hook_pattern": "hook-a",
    "hook_text": "wait for it",
    "prop": "ball",
    "setting": "kitchen",
    "motion_type": "walk",
    "audio_arm": "trend",
    "bodies_in_frame": 1,
    "seamless_loop": True,
    "eye_closeup_end": False,
    "trend_name": "evergreen",
}


def mk(x: float | None, *, age_days: float = 0, **features: Any) -> Clip:
    """An unsaved clip with a full feature set and (unless ``x`` is None) an ``outlier_x``."""
    feats = {**BASE_FEATURES, **features}
    if x is not None:
        feats["outlier_x"] = x
    return Clip(
        character_slug="biscuit",
        mode="recreate",
        state="posted",
        features=feats,
        created_at=NOW - timedelta(days=age_days),
    )


def measured(xs: list[float | None], **features: Any) -> list[Clip]:
    """One clip per value, oldest first (the last one is the newest)."""
    return [mk(x, age_days=len(xs) - i, **features) for i, x in enumerate(xs)]


# ---- the bars are pinned ----------------------------------------------------------------------


def test_the_binding_bars_are_pinned():
    assert review.HIT_X == 3
    assert (review.FORMAT_KEEP_MEDIAN, review.FORMAT_KEEP_MIN_N) == (1.5, 5)
    assert (review.FORMAT_KILL_MEDIAN, review.FORMAT_KILL_MIN_N) == (0.7, 8)
    assert (review.HOOK_WINDOW, review.HOOK_MIN_HITS) == (10, 2)
    assert review.LIFT_MIN_N == 5
    assert (review.CHARACTER_MIN_POSTS, review.CHARACTER_MIN_AGE) == (20, timedelta(weeks=4))
    assert (review.PROMOTE_MEDIAN_VIEWS, review.PROMOTE_ANY_VIEWS) == (5_000, 100_000)
    assert (review.KILL_MEDIAN_VIEWS, review.KILL_ANY_VIEWS) == (500, 10_000)
    assert (review.IG_GUARD_DROP_PCT, review.IG_GUARD_DROPIN_SHARE) == (40, 0.20)


# ---- feature_lifts ----------------------------------------------------------------------------


def test_lift_needs_5_posts():
    four = measured([2.0] * 4, prop="ball")
    assert feature_lifts(four) == []
    five = measured([2.0] * 5, prop="ball")
    lifts = feature_lifts(five)
    assert {(lf.feature, lf.value, lf.n) for lf in lifts} >= {("prop", "ball", 5)}
    # a clip without an outlier_x is not a post to learn from: it does not count towards n
    four_and_unmeasured = measured([2.0] * 4, prop="ball") + [mk(None, prop="ball")]
    assert [lf for lf in feature_lifts(four_and_unmeasured) if lf.feature == "prop"] == []
    # min_n is the knob; the default is the pre-registered 5
    assert feature_lifts(four, min_n=4)
    assert feature_lifts(five, min_n=6) == []


def test_lift_reports_median_n_and_the_baseline_it_is_judged_against():
    ball = measured([1.0, 2.0, 3.0, 4.0, 10.0], prop="ball")  # median 3.0, mean 4.0
    box = measured([0.5, 0.5, 0.5, 0.5, 0.5], prop="box")
    lifts = {(lf.feature, lf.value): lf for lf in feature_lifts([*ball, *box])}
    lf = lifts[("prop", "ball")]
    assert isinstance(lf, Lift)
    assert (lf.n, lf.median_outlier_x) == (5, 3.0)
    # account_median: the median outlier_x of every measured clip, the yardstick for the lift
    assert lf.account_median == 0.75  # median of [1,2,3,4,10,.5,.5,.5,.5,.5] -> (0.5 + 1.0) / 2
    assert lf.lift == pytest.approx(4.0)
    assert lifts[("prop", "box")].median_outlier_x == 0.5


def test_lifts_cover_only_the_required_feature_keys_and_split_by_value():
    clips = measured([2.0] * 5, seamless_loop=True, rerolls=0)
    clips += measured([1.0] * 5, seamless_loop=False, rerolls=0)
    lifts = feature_lifts(clips)
    assert {lf.feature for lf in lifts} <= REQUIRED_FEATURES  # not outlier_x, not rerolls
    loops = {lf.value: lf for lf in lifts if lf.feature == "seamless_loop"}
    assert set(loops) == {True, False}
    assert loops[True].median_outlier_x == 2.0 and loops[False].median_outlier_x == 1.0


def test_lifts_skip_clips_that_lack_the_feature_or_the_outlier():
    clips = measured([2.0] * 5, prop="ball")
    odd = mk(9.0, prop="ball")
    del odd.features["prop"]
    assert [lf.n for lf in feature_lifts([*clips, odd]) if lf.feature == "prop"] == [5]


# ---- format_verdicts --------------------------------------------------------------------------


def verdict(xs: list[float | None]) -> str:
    return format_verdicts(measured(xs))["fmt-a"]


def test_format_keep_and_kill_thresholds():
    # keep: median >= 1.5 over >= 5 posts
    assert verdict([1.5] * 5) == "keep"  # exactly 1.5, exactly 5
    assert verdict([1.4999] * 5) == "continue"
    assert verdict([9.0] * 4) == "continue"  # strong but only 4 posts
    assert verdict([9.0] * 4 + [None]) == "continue"  # an unmeasured clip is not a 5th post
    assert verdict([0.1, 0.1, 1.5, 9.0, 9.0]) == "keep"  # a median, not a mean
    assert verdict([0.1, 0.1, 0.1, 9.0, 9.0]) == "continue"  # mean 3.7 would pass; the median 0.1 does not
    # kill: median <= 0.7 over >= 8 posts
    assert verdict([0.7] * 8) == "kill"  # exactly 0.7, exactly 8
    assert verdict([0.7001] * 8) == "continue"
    assert verdict([0.0] * 7) == "continue"  # 7 posts is not enough to kill
    assert verdict([0.0] * 7 + [None]) == "continue"
    assert verdict([0.0] * 8) == "kill"
    assert verdict([0.0] * 3 + [0.9] * 5) == "continue"  # mean 0.56 would kill; the median 0.9 does not
    assert verdict([0.7] * 5) == "continue"  # 5 posts at 0.7 is neither keep nor kill yet
    # between the bars
    assert verdict([1.0] * 10) == "continue"


def test_format_verdicts_group_by_format_id_and_list_unmeasured_formats_as_continue():
    clips = measured([2.0] * 5, format_id="strong") + measured([0.1] * 8, format_id="weak")
    clips += [mk(None, format_id="new")]  # posted, not yet 7 days old
    assert format_verdicts(clips) == {"strong": "keep", "weak": "kill", "new": "continue"}


def test_format_verdicts_ignore_clips_without_a_format_id():
    odd = mk(5.0)
    del odd.features["format_id"]
    assert format_verdicts([odd]) == {}


# ---- hook_proven ------------------------------------------------------------------------------


def proven(xs: list[float | None], **features: Any) -> bool:
    return hook_proven(measured(xs, **features))["hook-a"]


def test_hook_proven_two_hits_in_ten():
    ten = [1.0] * 10
    assert proven([3.0, 3.0, *ten[:8]]) is True  # two hits, exactly at the bar (>= 3)
    assert proven([2.99, 3.0, *ten[:8]]) is False  # one hit and a near miss
    assert proven([3.0, *ten[:9]]) is False  # one hit
    assert proven([1.0] * 10) is False
    assert proven([3.0, 3.0]) is True  # fewer than 10 uses: all of them count
    assert proven([30.0]) is False  # one hit, however big, is not "proven"


def test_hook_proven_only_looks_at_the_last_ten_uses():
    # 11 uses, oldest first: hits at positions 1 and 2 -> only position 2 is inside the last 10
    assert proven([3.0, 3.0] + [1.0] * 9) is False
    # hits at positions 2 and 3 -> both inside the last 10
    assert proven([1.0, 3.0, 3.0] + [1.0] * 8) is True
    # 12 uses with the two hits the oldest: long out of the window
    assert proven([5.0, 5.0] + [1.0] * 10) is False
    # recency is by clip creation, not by the order the caller passes the list in
    clips = measured([3.0, 3.0] + [1.0] * 10)
    assert hook_proven(list(reversed(clips)))["hook-a"] is False


def test_hook_proven_unmeasured_uses_take_no_slot_and_patterns_are_independent():
    # 3 clips with no outlier_x yet, newest: they are not "uses" with a result, so they do not push hits out
    clips = measured([3.0, 3.0] + [1.0] * 8)
    clips += [mk(None, age_days=0) for _ in range(3)]
    assert hook_proven(clips)["hook-a"] is True
    other = measured([3.0, 1.0, 1.0], hook_pattern="hook-b")
    got = hook_proven([*clips, *other])
    assert got == {"hook-a": True, "hook-b": False}


def test_hook_proven_lists_a_pattern_with_no_measured_use_as_false():
    assert hook_proven([mk(None, hook_pattern="hook-z")]) == {"hook-z": False}


# ---- a store with two characters ---------------------------------------------------------------


class Rig:
    def __init__(self) -> None:
        self.store = MemoryStore(
            characters=[
                Character(slug="biscuit", name="Biscuit"),
                Character(slug="reginald", name="Reginald"),
            ],
            accounts=[
                Account(character_slug="biscuit", platform="tiktok", handle="@biscuit.tt"),
                Account(character_slug="biscuit", platform="instagram", handle="@biscuit.ig"),
                Account(character_slug="reginald", platform="tiktok", handle="@reginald.tt"),
                Account(character_slug="reginald", platform="instagram", handle="@reginald.ig"),
            ],
        )  # fmt: skip
        self.n = 0

    def account(self, handle: str) -> Account:
        return next(a for a in self.store.accounts() if a.handle == handle)

    def post(
        self,
        handle: str,
        *,
        age_days: float,
        views7: int | None = None,
        peak: int | None = None,
        status: PostStatus = PostStatus.posted,
        features: dict[str, Any] | None = None,
    ) -> Post:
        """A post ``age_days`` old. ``views7``: its reading at day 7. ``peak``: a later reading."""
        account = self.account(handle)
        at = NOW - timedelta(days=age_days)
        clip = self.store.add_clip(
            Clip(
                character_slug=account.character_slug,
                mode="recreate",
                state="posted",
                features=features or {},
                created_at=at,
            )
        )
        self.n += 1
        post = self.store.add_post(
            Post(
                clip_id=clip.id, account_id=account.id, scheduled_for=at, claimed_at=at,
                status=status, platform_post_id=f"pz-{self.n}",
            )
        )  # fmt: skip
        if views7 is not None:
            self.store.add_snapshot(Snapshot(post_id=post.id, captured_at=at + 7 * D, views=views7))
        if peak is not None:
            self.store.add_snapshot(Snapshot(post_id=post.id, captured_at=at + 9 * D, views=peak))
        return post

    def fill(
        self,
        *,
        tiktok: list[int],
        instagram: list[int],
        first_age_days: float = 40,
        character: str = "biscuit",
    ) -> None:
        """Mature posts (7-day views given), one a day from ``first_age_days`` ago, alternating."""
        handles = {"tiktok": f"@{character}.tt", "instagram": f"@{character}.ig"}
        rows = [("tiktok", v) for v in tiktok] + [("instagram", v) for v in instagram]
        rows.sort(key=lambda r: r[1])  # arbitrary but deterministic; the dates are what matter
        for i, (platform, views) in enumerate(rows):
            self.post(handles[platform], age_days=first_age_days - i, views7=views)

    def snap(self, post: Post, days_ago: float, **fields: Any) -> None:
        self.store.add_snapshot(
            Snapshot(post_id=post.id, captured_at=NOW - timedelta(days=days_ago), **fields)
        )


@pytest.fixture
def rig() -> Rig:
    return Rig()


# ---- character_bar: the gate ------------------------------------------------------------------


def test_character_bar_not_yet_before_20_posts_and_4_weeks(rig):
    assert character_bar(rig.store, "biscuit", NOW) == "not_yet"  # no posts at all

    # 19 posts, the first 27 days ago: neither 20 posts nor 4 weeks, even with promote-grade numbers
    for i in range(19):
        rig.post("@biscuit.tt", age_days=27 - i, views7=6_000)
    assert character_bar(rig.store, "biscuit", NOW) == "not_yet"

    # the 20th post opens the bar
    rig.post("@biscuit.tt", age_days=8, views7=6_000)
    assert character_bar(rig.store, "biscuit", NOW) == "promote"


def test_character_bar_four_weeks_since_the_first_post_opens_the_bar_on_its_own(rig):
    for i in range(12):  # 12 posts only; the first exactly 28 days ago
        rig.post("@biscuit.tt", age_days=28 - i, views7=6_000)
    assert character_bar(rig.store, "biscuit", NOW) == "promote"
    # one hour short of 4 weeks: not yet
    assert character_bar(rig.store, "biscuit", NOW - H) == "not_yet"


def test_character_bar_counts_only_posted_posts_of_that_character(rig):
    for i in range(19):
        rig.post("@biscuit.tt", age_days=27 - i, views7=6_000)
    rig.post("@biscuit.tt", age_days=9, views7=6_000, status=PostStatus.failed)  # never went out
    rig.post("@reginald.tt", age_days=9, views7=6_000)  # someone else's
    assert character_bar(rig.store, "biscuit", NOW) == "not_yet"  # still 19 of its own


# ---- character_bar: promote -------------------------------------------------------------------


def test_character_bar_promote_on_median_5000_on_either_platform(rig):
    rig.fill(tiktok=[5_000] * 10, instagram=[100] * 10)
    assert character_bar(rig.store, "biscuit", NOW) == "promote"  # exactly 5,000, TikTok only


def test_character_bar_median_4999_is_not_a_promotion(rig):
    rig.fill(tiktok=[4_999] * 10, instagram=[4_999] * 10)
    assert character_bar(rig.store, "biscuit", NOW) == "continue"


def test_character_bar_promote_when_instagram_alone_reaches_5000(rig):
    rig.fill(tiktok=[1_000] * 10, instagram=[5_000] * 10)
    assert character_bar(rig.store, "biscuit", NOW) == "promote"


def test_character_bar_promote_uses_the_median_not_the_mean(rig):
    rig.fill(tiktok=[100] * 6 + [90_000] * 4, instagram=[100] * 10)  # mean 36,000, median 100
    assert character_bar(rig.store, "biscuit", NOW) == "continue"


def test_character_bar_any_post_at_100k_promotes(rig):
    rig.fill(tiktok=[1_000] * 9 + [100_000], instagram=[1_000] * 10)
    assert character_bar(rig.store, "biscuit", NOW) == "promote"


def test_character_bar_99999_views_is_not_a_viral_promotion():
    rig = Rig()
    rig.fill(tiktok=[1_000] * 9 + [99_999], instagram=[1_000] * 10)
    assert character_bar(rig.store, "biscuit", NOW) == "continue"


def test_character_bar_any_post_counts_its_peak_reading_not_only_day_7(rig):
    rig.fill(tiktok=[1_000] * 10, instagram=[1_000] * 9)
    rig.post("@biscuit.ig", age_days=12, views7=1_000, peak=100_000)  # blew up after day 7
    assert character_bar(rig.store, "biscuit", NOW) == "promote"


def test_character_bar_a_young_post_that_already_passed_100k_counts(rig):
    rig.fill(tiktok=[1_000] * 10, instagram=[1_000] * 9)
    young = rig.post("@biscuit.tt", age_days=2)  # no day-7 reading yet
    rig.snap(young, 1, views=250_000)
    assert character_bar(rig.store, "biscuit", NOW) == "promote"


# ---- character_bar: kill ----------------------------------------------------------------------


def test_character_bar_kill_requires_both_platforms_low(rig):
    rig.fill(tiktok=[499] * 10, instagram=[499] * 10)
    assert character_bar(rig.store, "biscuit", NOW) == "kill"


def test_character_bar_median_exactly_500_on_one_platform_is_not_a_kill(rig):
    rig.fill(tiktok=[499] * 10, instagram=[500] * 10)
    assert character_bar(rig.store, "biscuit", NOW) == "continue"


def test_character_bar_one_low_platform_alone_is_not_a_kill(rig):
    rig.fill(tiktok=[10] * 10, instagram=[2_000] * 10)
    assert character_bar(rig.store, "biscuit", NOW) == "continue"


def test_character_bar_a_post_at_10000_blocks_the_kill_and_9999_does_not(rig):
    rig.fill(tiktok=[100] * 9 + [10_000], instagram=[100] * 10)
    assert character_bar(rig.store, "biscuit", NOW) == "continue"


def test_character_bar_9999_views_does_not_block_the_kill():
    rig = Rig()
    rig.fill(tiktok=[100] * 9 + [9_999], instagram=[100] * 10)
    assert character_bar(rig.store, "biscuit", NOW) == "kill"


def test_character_bar_never_kills_on_one_platform_of_evidence(rig):
    rig.fill(tiktok=[10] * 20, instagram=[])  # nothing posted on Instagram: "both" cannot be shown
    assert character_bar(rig.store, "biscuit", NOW) == "continue"


def test_character_bar_medians_are_seven_day_views_so_young_posts_never_kill(rig):
    # 20 posts, every one younger than 7 days with a low reading: no mature figure, no verdict
    for i in range(20):
        young = rig.post("@biscuit.tt" if i % 2 else "@biscuit.ig", age_days=3)
        rig.snap(young, 1, views=50)
    assert character_bar(rig.store, "biscuit", NOW) == "continue"


def test_character_bar_the_other_characters_numbers_do_not_leak(rig):
    rig.fill(tiktok=[5_000] * 10, instagram=[5_000] * 10, character="reginald")
    rig.fill(tiktok=[10] * 10, instagram=[10] * 10, character="biscuit")
    assert character_bar(rig.store, "biscuit", NOW) == "kill"
    assert character_bar(rig.store, "reginald", NOW) == "promote"


# ---- ig_guard ---------------------------------------------------------------------------------


def reach_rig(prev: list[float | None], cur: list[float | None], handle: str = "@biscuit.ig"):
    """Snapshots of one post: ``prev`` days 8..13 ago, ``cur`` days 1..6 ago (``non_follower_pct``)."""
    rig = Rig()
    post = rig.post(handle, age_days=20)
    for i, v in enumerate(prev):
        rig.snap(post, 8 + i, non_follower_pct=v)
    for i, v in enumerate(cur):
        rig.snap(post, 1 + i, non_follower_pct=v)
    return rig, rig.account(handle)


@pytest.mark.parametrize(
    ("prev", "cur", "fires"),
    [
        (50.0, 30.0, True),  # exactly -40 %
        (50.0, 30.1, False),  # a hair under
        (50.0, 20.0, True),
        (50.0, 0.0, True),
        (40.0, 24.0, True),  # exactly -40 % again, other numbers
        (40.0, 24.1, False),
        (50.0, 50.0, False),
        (50.0, 60.0, False),  # up is never a drop
        (0.0, 0.0, False),  # no baseline: undefined, not a drop
    ],
)
def test_ig_guard_threshold_is_a_40_percent_drop_week_on_week(prev, cur, fires):
    rig, account = reach_rig([prev], [cur])
    assert ig_guard(rig.store, account, NOW) is fires


def test_ig_guard_cuts_share_on_40pct_drop():
    rig, account = reach_rig([50.0, 50.0], [30.0, 30.0])
    assert account.dropin_share == 0.40  # the Instagram default
    assert apply_ig_guard(rig.store, account, NOW) is True
    assert rig.account("@biscuit.ig").dropin_share == 0.20
    # nothing else moved
    assert rig.account("@biscuit.tt").dropin_share == 0.70
    assert rig.account("@reginald.ig").dropin_share == 0.40


def test_ig_guard_leaves_the_share_alone_below_the_bar():
    rig, account = reach_rig([50.0], [30.1])
    assert apply_ig_guard(rig.store, account, NOW) is False
    assert rig.account("@biscuit.ig").dropin_share == 0.40


def test_ig_guard_never_raises_a_share_that_is_already_at_or_below_the_cut():
    for share in (0.20, 0.10):
        rig, account = reach_rig([50.0], [10.0])
        rig.store.update_account(account.id, dropin_share=share)
        account = rig.account("@biscuit.ig")
        assert apply_ig_guard(rig.store, account, NOW) is True  # the bar fired ...
        assert rig.account("@biscuit.ig").dropin_share == share  # ... and there was nothing to cut


def test_ig_guard_compares_medians_not_means():
    rig, account = reach_rig([50.0, 50.0, 10.0], [30.0, 30.0, 90.0])
    assert ig_guard(rig.store, account, NOW) is True  # 50 -> 30; the means (36.7 -> 50) say "up"


def test_ig_guard_windows_are_the_last_7_days_and_the_7_days_before():
    rig = Rig()
    post = rig.post("@biscuit.ig", age_days=30)
    account = rig.account("@biscuit.ig")
    rig.snap(post, 14, non_follower_pct=5.0)  # 14 days ago exactly: in neither window
    rig.snap(post, 7, non_follower_pct=50.0)  # exactly 7 days ago: the earlier week
    rig.snap(post, 0, non_follower_pct=30.0)  # right now: this week
    assert ig_guard(rig.store, account, NOW) is True
    # had the day-14 reading counted, the earlier median would be 27.5 and there would be no drop
    rig.snap(post, -1, non_follower_pct=99.0)  # in the future: ignored (it would lift this week's median)
    assert ig_guard(rig.store, account, NOW) is True


def test_ig_guard_pools_every_post_of_the_account():
    rig = Rig()
    a, b = rig.post("@biscuit.ig", age_days=20), rig.post("@biscuit.ig", age_days=21)
    rig.snap(a, 9, non_follower_pct=50.0)
    rig.snap(b, 10, non_follower_pct=50.0)
    rig.snap(a, 2, non_follower_pct=30.0)
    rig.snap(b, 3, non_follower_pct=30.0)
    assert ig_guard(rig.store, rig.account("@biscuit.ig"), NOW) is True


@pytest.mark.parametrize(
    ("prev", "cur"),
    [([], [10.0]), ([50.0], []), ([], []), ([None], [10.0]), ([50.0], [None])],
)
def test_ig_guard_with_insufficient_data_changes_nothing(prev, cur):
    rig, account = reach_rig(prev, cur)
    assert ig_guard(rig.store, account, NOW) is False
    assert apply_ig_guard(rig.store, account, NOW) is False
    assert rig.account("@biscuit.ig").dropin_share == 0.40


def test_ig_guard_is_for_instagram_accounts_only():
    rig, account = reach_rig([50.0], [10.0], handle="@biscuit.tt")
    assert ig_guard(rig.store, account, NOW) is False
    assert apply_ig_guard(rig.store, account, NOW) is False
    assert rig.account("@biscuit.tt").dropin_share == 0.70


def test_ig_guard_needs_an_aware_now():
    rig, account = reach_rig([50.0], [10.0])
    with pytest.raises(ValueError, match="timezone-aware"):
        ig_guard(rig.store, account, datetime(2026, 11, 10, 12))


# ---- review_payload ---------------------------------------------------------------------------


def payload_rig() -> Rig:
    """Biscuit: 5 clips on format fmt-a (keep), 8 on fmt-b (kill), reach down 50 % on Instagram."""
    rig = Rig()
    for i, x in enumerate([2.0, 2.0, 2.0, 2.0, 2.0]):
        p = rig.post("@biscuit.tt", age_days=40 - i, views7=1_000,
                     features={**BASE_FEATURES, "format_id": "fmt-a", "outlier_x": x})  # fmt: skip
    for i in range(8):
        rig.post("@biscuit.tt", age_days=30 - i, views7=100,
                 features={**BASE_FEATURES, "format_id": "fmt-b", "hook_pattern": "hook-b",
                           "outlier_x": 0.5})  # fmt: skip
    rig.post("@biscuit.tt", age_days=2, features={**BASE_FEATURES, "format_id": "fmt-c"})
    ig = rig.post("@biscuit.ig", age_days=20)
    rig.snap(ig, 10, non_follower_pct=50.0, skip_rate=0.5, watched_pct=30.0)
    rig.snap(ig, 3, non_follower_pct=30.0, skip_rate=0.4, watched_pct=40.0)
    rig.snap(ig, 1, non_follower_pct=30.0, skip_rate=0.2, watched_pct=50.0)
    rig.snap(ig, 0.5, non_follower_pct=None, skip_rate=None, watched_pct=None)
    return rig


def test_review_payload_is_json_serialisable_and_has_every_section():
    rig = payload_rig()
    payload = review_payload(rig.store, NOW)
    again = json.loads(json.dumps(payload))
    assert again == payload
    assert {"as_of", "bars", "clips", "lifts", "formats", "hooks", "characters", "accounts", "ig_guard"} <= set(
        payload
    )
    assert payload["as_of"] == NOW.isoformat()


def test_review_payload_format_hook_and_lift_sections():
    payload = review_payload(payload_rig().store, NOW)
    formats = {f["format_id"]: f for f in payload["formats"]}
    assert formats["fmt-a"] == {
        "format_id": "fmt-a", "n": 5, "median_outlier_x": 2.0, "verdict": "keep"
    }  # fmt: skip
    assert (formats["fmt-b"]["n"], formats["fmt-b"]["verdict"]) == (8, "kill")
    assert (formats["fmt-c"]["n"], formats["fmt-c"]["median_outlier_x"], formats["fmt-c"]["verdict"]) == (
        0, None, "continue",
    )  # fmt: skip
    hooks = {h["hook_pattern"]: h for h in payload["hooks"]}
    assert hooks["hook-a"]["proven"] is False and hooks["hook-a"]["hits_last_10"] == 0
    assert payload["clips"]["measured"] == 13
    assert payload["clips"]["hits"] == 0
    assert any(lf["feature"] == "format_id" and lf["value"] == "fmt-a" and lf["n"] == 5 for lf in payload["lifts"])
    assert all({"feature", "value", "n", "median_outlier_x", "account_median", "lift"} <= set(lf)
               for lf in payload["lifts"])  # fmt: skip


def test_review_payload_echoes_the_binding_bars():
    bars = review_payload(Rig().store, NOW)["bars"]
    assert bars["hit_outlier_x"] == 3
    assert bars["format"] == {"keep_median": 1.5, "keep_min_posts": 5, "kill_median": 0.7, "kill_min_posts": 8}
    assert bars["hook"] == {"min_hits": 2, "last_uses": 10}
    assert bars["lift_min_posts"] == 5
    assert bars["character"]["promote_median_views"] == 5_000
    assert bars["character"]["promote_any_post_views"] == 100_000
    assert bars["character"]["kill_median_views"] == 500
    assert bars["character"]["kill_any_post_views"] == 10_000
    assert (bars["character"]["min_posts"], bars["character"]["min_weeks"]) == (20, 4)
    assert bars["ig_guard"] == {"reach_drop_pct": 40, "dropin_share": 0.2}


def test_review_payload_characters_carry_the_bar_and_its_evidence():
    payload = review_payload(payload_rig().store, NOW)
    chars = {c["slug"]: c for c in payload["characters"]}
    assert set(chars) == {"biscuit", "reginald"}
    assert chars["reginald"]["bar"] == "not_yet" and chars["reginald"]["posts"] == 0
    biscuit = chars["biscuit"]
    assert biscuit["bar"] == "continue"  # 15 posts over 40 days: the bar is open, nothing is met
    assert biscuit["posts"] == 5 + 8 + 1 + 1
    assert biscuit["first_post_at"] == (NOW - 40 * D).isoformat()
    assert biscuit["age_days"] == 40.0
    assert biscuit["median_views_7d"]["tiktok"] == 100  # 13 mature posts: 5 x 1,000 and 8 x 100
    assert biscuit["median_views_7d"]["instagram"] is None


def test_review_payload_accounts_carry_week_medians_including_skip_rate_and_watched_pct():
    payload = review_payload(payload_rig().store, NOW)
    accounts = {a["handle"]: a for a in payload["accounts"]}
    ig = accounts["@biscuit.ig"]
    assert ig["platform"] == "instagram" and ig["character_slug"] == "biscuit"
    assert ig["dropin_share"] == 0.40
    # the last 7 days: readings of day 3, day 1 and the all-None one of half a day ago
    assert ig["snapshots_this_week"] == 3
    assert ig["non_follower_pct"] == 30.0  # median of [30, 30] (None left out)
    assert ig["skip_rate"] == pytest.approx(0.3)  # median of [0.4, 0.2]
    assert ig["watched_pct"] == 45.0  # median of [40, 50]
    assert ig["non_follower_pct_previous_week"] == 50.0
    # an account with no readings this week: the keys are present and null, never 0
    tt = accounts["@biscuit.tt"]
    assert tt["snapshots_this_week"] == 0
    assert tt["skip_rate"] is None and tt["watched_pct"] is None and tt["non_follower_pct"] is None


def test_review_payload_reports_the_ig_guard_without_writing_by_default():
    rig = payload_rig()
    payload = review_payload(rig.store, NOW)
    (guard,) = [g for g in payload["ig_guard"] if g["handle"] == "@biscuit.ig"]
    assert guard["fires"] is True
    assert (guard["non_follower_pct_previous_week"], guard["non_follower_pct_this_week"]) == (50.0, 30.0)
    assert guard["drop_pct"] == pytest.approx(40.0)
    assert guard["dropin_share"] == 0.40 and guard["new_dropin_share"] == 0.20
    assert guard["applied"] is False
    assert rig.account("@biscuit.ig").dropin_share == 0.40  # a read does not write
    # Instagram accounts only
    assert {g["handle"] for g in payload["ig_guard"]} == {"@biscuit.ig", "@reginald.ig"}
    quiet = next(g for g in payload["ig_guard"] if g["handle"] == "@reginald.ig")
    assert quiet["fires"] is False and quiet["new_dropin_share"] is None and quiet["drop_pct"] is None


def test_review_payload_can_apply_the_guard_and_says_so_once():
    rig = payload_rig()
    payload = review_payload(rig.store, NOW, apply_guard=True)
    (guard,) = [g for g in payload["ig_guard"] if g["handle"] == "@biscuit.ig"]
    assert guard["fires"] is True and guard["applied"] is True
    assert rig.account("@biscuit.ig").dropin_share == 0.20
    # a second run: the bar still fires (reach is still down) but there is nothing left to cut
    again = review_payload(rig.store, NOW, apply_guard=True)
    (guard2,) = [g for g in again["ig_guard"] if g["handle"] == "@biscuit.ig"]
    assert guard2["fires"] is True and guard2["applied"] is False and guard2["new_dropin_share"] is None


def test_review_payload_on_an_empty_store_is_valid():
    payload = review_payload(Rig().store, NOW)
    json.dumps(payload)
    assert payload["lifts"] == [] and payload["formats"] == [] and payload["hooks"] == []
    assert payload["clips"] == {"posted": 0, "measured": 0, "hits": 0, "hit_rate": None}


def test_review_payload_counts_hits_at_the_bar():
    rig = Rig()
    for x in (3.0, 2.99, 10.0):
        rig.post("@biscuit.tt", age_days=10, features={**BASE_FEATURES, "outlier_x": x})
    assert review_payload(rig.store, NOW)["clips"] == {
        "posted": 3, "measured": 3, "hits": 2, "hit_rate": pytest.approx(2 / 3)
    }  # fmt: skip


# ---- CLI --------------------------------------------------------------------------------------


@pytest.fixture
def cli_rig(monkeypatch) -> Rig:
    rig = payload_rig()
    monkeypatch.setattr(review, "open_store", lambda: rig.store)
    monkeypatch.setattr(review, "now_london", lambda: NOW)
    return rig


def test_review_help_lists_data():
    r = CliRunner().invoke(app, ["review", "--help"])
    assert r.exit_code == 0 and "data" in r.output


def test_review_data_prints_the_payload_and_applies_the_ig_guard(cli_rig):
    r = CliRunner().invoke(app, ["review", "data"])
    assert r.exit_code == 0, r.output
    out = json.loads(r.output)
    assert out["as_of"] == NOW.isoformat()
    guard = next(g for g in out["ig_guard"] if g["handle"] == "@biscuit.ig")
    assert guard["fires"] is True and guard["applied"] is True
    assert cli_rig.account("@biscuit.ig").dropin_share == 0.20
    ig = next(a for a in out["accounts"] if a["handle"] == "@biscuit.ig")
    assert ig["skip_rate"] == pytest.approx(0.3) and ig["watched_pct"] == 45.0


def test_review_data_without_a_database_url_is_a_caller_error(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    r = CliRunner().invoke(app, ["review", "data"])
    assert r.exit_code == 2
    assert "DATABASE_URL" in r.output


# ---- review save -------------------------------------------------------------------------------


def test_review_help_lists_save():
    r = CliRunner().invoke(app, ["review", "--help"])
    assert r.exit_code == 0 and "save" in r.output


@pytest.mark.parametrize(
    ("raw", "monday"),
    [
        ("2026-W41", date(2026, 10, 5)),
        ("2026-w41", date(2026, 10, 5)),
        ("2026-W01", date(2025, 12, 29)),  # ISO week 1 of 2026 starts in December
        ("2020-W53", date(2020, 12, 28)),  # a 53-week year
        ("2026-10-05", date(2026, 10, 5)),  # a Monday as a date: what the weekly-review skill passes
        ("2026-10-08", date(2026, 10, 5)),  # any other day lands on its Monday
        ("2026-10-11", date(2026, 10, 5)),  # Sunday still belongs to that week
    ],
)
def test_parse_week_gives_the_monday_of_the_iso_week(raw, monday):
    assert parse_week(raw) == monday


@pytest.mark.parametrize("raw", ["2026-W54", "2026-W00", "2025-W53", "W41", "next week", "2026-13-01", ""])
def test_parse_week_refuses_what_is_not_a_week(raw):
    with pytest.raises(ValueError, match="week"):
        parse_week(raw)


def reviews_store() -> MemoryStore:
    return MemoryStore(characters=[Character(slug="biscuit", name="Biscuit"), Character(slug="reginald", name="Reginald")])


def test_save_review_inserts_and_then_rewrites_the_same_week_and_character():
    store = reviews_store()
    first = save_review(store, date(2026, 10, 5), "biscuit", "# v1", "not_yet")
    again = save_review(store, date(2026, 10, 5), "biscuit", "# v2", "continue")
    assert again.id == first.id and (again.report_md, again.bar_status) == ("# v2", "continue")
    save_review(store, date(2026, 10, 5), "reginald", "# r", None)
    assert len(store.list_reviews()) == 2


def test_save_review_refuses_an_unknown_character_and_an_empty_report():
    store = reviews_store()
    with pytest.raises(ValueError, match="unknown character"):
        save_review(store, date(2026, 10, 5), "nobody", "# x", None)
    with pytest.raises(ValueError, match="empty"):
        save_review(store, date(2026, 10, 5), "biscuit", "  \n", None)
    assert store.list_reviews() == []


@pytest.fixture
def save_store(monkeypatch) -> MemoryStore:
    store = reviews_store()
    monkeypatch.setattr(review, "open_store", lambda: store)
    return store


def save(tmp_path, *args: str, text: str = "# Biscuit\n\nweek 41 report\n"):
    report = tmp_path / "report.md"
    report.write_text(text, encoding="utf-8")
    return CliRunner().invoke(app, ["review", "save", *args, "--report-file", str(report)])


def test_cli_review_save_writes_one_row_and_is_idempotent(save_store, tmp_path):
    args = ("--week", "2026-W41", "--character", "biscuit", "--bar-status", "continue")
    r = save(tmp_path, *args)
    assert r.exit_code == 0, r.output
    out = json.loads(r.stdout)
    assert (out["week"], out["character_slug"], out["bar_status"]) == ("2026-10-05", "biscuit", "continue")
    (row,) = save_store.list_reviews()
    assert row.report_md == "# Biscuit\n\nweek 41 report" and out["id"] == row.id  # one trailing newline dropped

    r = save(tmp_path, *args, text="# Biscuit\n\nrevised\n")
    assert r.exit_code == 0, r.output
    (row2,) = save_store.list_reviews()  # still one row for (week, character)
    assert row2.id == row.id and row2.report_md.endswith("revised")


def test_cli_review_save_accepts_a_monday_date_like_the_skill_passes(save_store, tmp_path):
    r = save(tmp_path, "--week", "2026-10-05", "--character", "reginald", "--bar-status", "not_yet")
    assert r.exit_code == 0, r.output
    assert [(x.week, x.character_slug) for x in save_store.list_reviews()] == [(date(2026, 10, 5), "reginald")]


def test_cli_review_save_takes_the_report_literally(save_store, tmp_path):
    nasty = "it's $(echo pwned) `x` \"q\" ; && | > \U0001F499"
    r = save(tmp_path, "--week", "2026-W41", "--character", "biscuit", "--bar-status", "kill", text=nasty + "\n")
    assert r.exit_code == 0, r.output
    assert save_store.list_reviews()[0].report_md == nasty


def test_cli_review_save_refuses_bad_calls_without_writing(save_store, tmp_path):
    ok = ("--week", "2026-W41", "--character", "biscuit", "--bar-status", "continue")
    assert save(tmp_path, "--week", "soon", "--character", "biscuit", "--bar-status", "x").exit_code == 2
    r = save(tmp_path, "--week", "2026-W41", "--character", "nobody", "--bar-status", "x")
    assert r.exit_code == 2 and "unknown character" in r.output
    r = CliRunner().invoke(app, ["review", "save", *ok, "--report-file", str(tmp_path / "missing.md")])
    assert r.exit_code == 2 and "no such file" in r.output
    assert CliRunner().invoke(app, ["review", "save", *ok]).exit_code == 2  # --report-file is required
    assert CliRunner().invoke(app, ["review", "save", "--week", "2026-W41", "--character", "biscuit",
                                    "--report-file", str(tmp_path / "x")]).exit_code == 2  # --bar-status too
    assert save(tmp_path, *ok, text="\n").exit_code == 2  # an empty report
    assert save_store.list_reviews() == []
