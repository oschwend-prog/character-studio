"""Metrics: ``outlier_x``, the Postiz analytics pull (idempotent per post and window) and the vidIQ
Instagram insights ingest.

Everything runs on ``MemoryStore``; the Postiz CLI is a fake ``run`` that records argv, so no
``postiz`` binary, network or account is involved.
"""

from __future__ import annotations

import json
import logging
import stat
import subprocess
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from typer.testing import CliRunner

from studio import metrics
from studio.cli import app
from studio.metrics import ingest_ig_insights, outlier_x, pull
from studio.models import Account, Character, Clip, Post, PostStatus, Snapshot
from studio.store import MemoryStore

NOW = datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc)
H = timedelta(hours=1)
D = timedelta(days=1)


# ---- outlier_x ---------------------------------------------------------------------------------


def test_outlier_x_basic():
    assert outlier_x(600, [100, 200, 300]) == 3.0


def test_outlier_x_none_when_missing():
    assert outlier_x(None, [100, 200, 300]) is None
    # fewer than 3 non-None priors: not enough baseline
    assert outlier_x(600, []) is None
    assert outlier_x(600, [100, 200]) is None
    assert outlier_x(600, [100, None, 200, None]) is None
    assert outlier_x(600, [None, None, None]) is None


def test_outlier_x_ignores_none_priors():
    assert outlier_x(600, [None, 100, None, 200, 300, None]) == 3.0


def test_outlier_x_uses_last_15_only():
    # 16 old big values, then the 15 most recent at 100: only the last 15 count
    priors = [1000] * 16 + [100] * 15
    assert outlier_x(300, priors) == 3.0
    # the 16th-from-last is outside the window even when it is the only odd one out
    assert outlier_x(300, [1_000_000] + [100] * 15) == 3.0


def test_outlier_x_the_16th_from_last_is_outside_the_window():
    # the last 15 are 7 x 100 and 8 x 1000 (median 1000); the older 100 would drag the median of 16
    # down to 550 if it were included
    priors = [100] + [100] * 7 + [1000] * 8
    assert outlier_x(3000, priors) == 3.0


def test_outlier_x_the_15th_from_last_is_inside_the_window():
    # 8 x 100 and 7 x 1000: median 100; dropping the 15th would give 550
    assert outlier_x(300, [100] * 8 + [1000] * 7) == 3.0


def test_outlier_x_is_a_median_not_a_mean():
    assert outlier_x(300, [100, 100, 1000]) == 3.0


def test_outlier_x_last_15_counts_non_none_values_not_positions():
    # a None among the most recent slots does not shrink the window: it is the last 15 *non-None*
    priors = [1000] * 16 + [None, None] + [100] * 15
    assert outlier_x(300, priors) == 3.0


def test_outlier_x_median_of_an_even_count():
    assert outlier_x(500, [100, 200, 300, 400]) == 2.0


def test_outlier_x_zero_baseline_is_undefined_not_infinite():
    assert outlier_x(500, [0, 0, 0]) is None


def test_outlier_x_zero_views_is_a_real_zero():
    assert outlier_x(0, [100, 200, 300]) == 0.0


# ---- rig ---------------------------------------------------------------------------------------


def analytics(**metrics_: Any) -> list[dict[str, Any]]:
    """A Postiz ``analytics:post`` payload: one entry per metric, one daily data point each."""
    labels = {
        "views": "Views", "impressions": "Impressions", "likes": "Likes", "comments": "Comments",
        "shares": "Shares", "saves": "Saves",
    }  # fmt: skip
    return [
        {
            "label": labels[k],
            "data": [{"total": v if isinstance(v, str) else str(v), "date": "2026-10-20"}],
            "percentageChange": 0,
        }
        for k, v in metrics_.items()
    ]


class FakePostiz:
    """``subprocess.run`` stand-in. ``responses`` maps a Postiz post id to what ``analytics:post``
    prints: a JSON value, a raw string, an ``Exception`` to raise, or ``("exit", code, stderr)``."""

    def __init__(self, responses: dict[str, Any] | None = None, default: Any = None) -> None:
        self.responses = responses or {}
        self.default = default
        self.calls: list[list[str]] = []
        self.kwargs: list[dict[str, Any]] = []

    def __call__(self, argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        self.calls.append(list(argv))
        self.kwargs.append(kwargs)
        reply = self.responses.get(argv[2], self.default)
        if isinstance(reply, Exception):
            raise reply
        if isinstance(reply, tuple) and reply and reply[0] == "exit":
            return subprocess.CompletedProcess(argv, reply[1], "", reply[2])
        out = reply if isinstance(reply, str) else json.dumps(reply)
        return subprocess.CompletedProcess(argv, 0, out, "")


class Rig:
    def __init__(self) -> None:
        self.store = MemoryStore(
            characters=[Character(slug="biscuit", name="Biscuit"),
                        Character(slug="reginald", name="Reginald")],
            accounts=[
                Account(character_slug="biscuit", platform="tiktok", handle="@biscuit.tt",
                        postiz_integration_id="int-bis-tt"),
                Account(character_slug="biscuit", platform="instagram", handle="@biscuit.ig",
                        postiz_integration_id="int-bis-ig"),
                Account(character_slug="reginald", platform="tiktok", handle="@reginald.tt",
                        postiz_integration_id="int-reg-tt"),
            ],
        )  # fmt: skip
        self.n = 0

    def account(self, handle: str) -> Account:
        return next(a for a in self.store.accounts() if a.handle == handle)

    def clip(self, character: str = "biscuit", **features: Any) -> Clip:
        return self.store.add_clip(
            Clip(character_slug=character, mode="recreate", state="posted", features=features)
        )

    def post(
        self,
        handle: str = "@biscuit.tt",
        *,
        age: timedelta = 24 * H,
        now: datetime = NOW,
        clip: Clip | None = None,
        platform_post_id: str | None = "auto",
        status: PostStatus = PostStatus.posted,
        **fields: Any,
    ) -> Post:
        """A post that went out ``age`` before ``now`` (``claimed_at`` is when it was posted)."""
        account = self.account(handle)
        clip = clip or self.clip(account.character_slug)
        at = now - age
        self.n += 1
        if platform_post_id == "auto":
            platform_post_id = f"pz-{self.n}"
        fields.setdefault("claimed_at", at)
        fields.setdefault("scheduled_for", at)
        return self.store.add_post(
            Post(clip_id=clip.id, account_id=account.id, status=status,
                 platform_post_id=platform_post_id, **fields)
        )  # fmt: skip

    def seven_day_views(self, post: Post, views: int | None, *, offset: timedelta = timedelta(0)):
        at = (post.claimed_at or post.scheduled_for) + 7 * D + offset
        self.store.add_snapshot(Snapshot(post_id=post.id, captured_at=at, views=views))

    def history(
        self, handle: str, views: list[int | None], *, target_at: datetime
    ) -> list[Post]:
        """Earlier posts on one account, one per day before ``target_at``, oldest first, each with
        its 7-day snapshot already recorded."""
        posts = []
        for i, v in enumerate(views):
            p = self.post(handle, age=(len(views) - i) * D + (NOW - target_at))
            self.seven_day_views(p, v)
            posts.append(p)
        return posts

    def snaps(self, post: Post) -> list[Snapshot]:
        return self.store.snapshots_for(post.id)

    def features(self, clip: Clip) -> dict[str, Any]:
        return self.store.get_clip(clip.id).features


@pytest.fixture
def rig() -> Rig:
    return Rig()


# ---- pull: which posts, which windows ------------------------------------------------------------


def test_pull_asks_postiz_for_seven_days_and_writes_a_snapshot(rig):
    post = rig.post(age=24 * H)
    fake = FakePostiz({post.platform_post_id: analytics(views=1200, likes=90, comments=7,
                                                       shares=11, saves=30)})
    out = pull(rig.store, fake, NOW)

    assert fake.calls == [["postiz", "analytics:post", post.platform_post_id, "-d", "7"]]
    (snap,) = rig.snaps(post)
    assert snap.captured_at == NOW
    assert (snap.views, snap.likes, snap.comments, snap.shares, snap.saves) == (1200, 90, 7, 11, 30)
    assert snap.watch_time_s is None and snap.follows is None and snap.non_follower_pct is None
    assert out["pulled"] == [{"post_id": post.id, "window": "24h"}]
    assert out["errors"] == []


@pytest.mark.parametrize(
    ("age", "window"),
    [(1 * H, "1h"), (24 * H, "24h"), (72 * H, "72h"), (7 * D, "7d")],
)
def test_pull_covers_the_four_windows(rig, age, window):
    post = rig.post(age=age)
    out = pull(rig.store, FakePostiz(default=analytics(views=10)), NOW)
    assert [r["window"] for r in out["pulled"]] == [window]
    assert len(rig.snaps(post)) == 1


MIN = timedelta(minutes=1)


@pytest.mark.parametrize(
    ("age", "window"),
    [
        (5 * MIN, None),                   # just posted
        (59 * MIN, None),                  # a minute short of the first window
        (1 * H, "1h"),                     # a window starts exactly at its age
        (3 * H, "1h"),                     # ... and stays open until the next one starts
        (24 * H - MIN, "1h"),
        (24 * H, "24h"),
        (72 * H - MIN, "24h"),
        (72 * H, "72h"),
        (5 * D, "72h"),
        (7 * D - MIN, "72h"),
        (7 * D, "7d"),
        (7 * D + 5 * H, "7d"),             # catch-up: late is still in time
        (30 * D, "7d"),                    # the 7 d window has no upper bound
    ],
)
def test_pull_windows_start_at_their_age_and_have_no_upper_bound(rig, age, window):
    rig.post(age=age)
    fake = FakePostiz(default=analytics(views=1))
    out = pull(rig.store, fake, NOW)
    assert [r["window"] for r in out["pulled"]] == ([window] if window else [])
    assert len(fake.calls) == (1 if window else 0)


@pytest.mark.parametrize(
    ("age", "window"),
    [(-1 * H, None), (59 * MIN, None), (1 * H, "1h"), (23 * H, "1h"), (24 * H, "24h"),
     (71 * H, "24h"), (72 * H, "72h"), (7 * D - MIN, "72h"), (7 * D, "7d"), (400 * D, "7d")],
)  # fmt: skip
def test_every_age_falls_in_at_most_one_window(age, window):
    assert metrics.window_at(age) == window


def test_a_snapshot_belongs_to_the_window_its_own_age_falls_in(rig):
    post = rig.post(age=10 * D)
    at = post.claimed_at
    for age in (30 * MIN, 1 * H, 25 * H, 80 * H, 7 * D, 9 * D):
        rig.store.add_snapshot(Snapshot(post_id=post.id, captured_at=at + age, views=1))
    counts = {w: len(metrics._snapshots_in_window(rig.store, post, w)) for w, _ in metrics.WINDOWS}
    # the 30-minute snapshot is younger than the first window and belongs to none
    assert counts == {"1h": 1, "24h": 1, "72h": 1, "7d": 2}


def test_a_pull_at_day_7_plus_5h_writes_the_7d_snapshot_and_outlier_x(rig):
    clip, post, fake = seven_day_rig(rig, age=7 * D + 5 * H)
    out = pull(rig.store, fake, NOW)
    assert out["pulled"] == [{"post_id": post.id, "window": "7d"}]
    assert rig.snaps(post)[0].views == 600
    assert rig.features(clip)["outlier_x"] == 3.0


def test_a_6_hourly_job_never_loses_the_1h_window(rig):
    posted = datetime(2026, 10, 20, 12, 30, tzinfo=timezone.utc)
    post = rig.post(age=timedelta(0), now=posted)
    fake = FakePostiz(default=analytics(views=5))
    # the job runs at 00:00, 06:00, 12:00 and 18:00 for ten days; the first run after 12:30 is 18:00
    for k in range(0, 10 * 4):
        t = datetime(2026, 10, 20, 0, 0, tzinfo=timezone.utc) + 6 * H * k
        if t >= posted:
            pull(rig.store, fake, t)
    ages = [s.captured_at - posted for s in rig.snaps(post)]
    assert ages[0] == 5 * H + 30 * MIN  # the first pull, 5.5 h after posting, is the 1 h window
    assert [metrics.window_at(a) for a in ages] == ["1h", "24h", "72h", "7d"]
    assert len(fake.calls) == 4


def test_the_first_pull_at_6h_writes_the_1h_window(rig):
    post = rig.post(age=6 * H)
    fake = FakePostiz(default=analytics(views=5))
    out = pull(rig.store, fake, NOW)
    assert out["pulled"] == [{"post_id": post.id, "window": "1h"}]
    assert len(rig.snaps(post)) == 1


def test_a_post_first_met_late_pulls_only_the_current_window(rig):
    """At 30 h the 1 h window can no longer be honest: one 24 h snapshot, and nothing more, ever."""
    post = rig.post(age=30 * H)
    fake = FakePostiz(default=analytics(views=5))
    first = pull(rig.store, fake, NOW)
    assert first["pulled"] == [{"post_id": post.id, "window": "24h"}]
    for k in range(1, 12):
        pull(rig.store, fake, NOW + k * H)
    assert len(fake.calls) == 1 and len(rig.snaps(post)) == 1


def test_a_window_is_never_written_twice(rig):
    post = rig.post(age=1 * H)
    fake = FakePostiz(default=analytics(views=5))
    for k in range(0, 9 * 24 * 60 // 37):  # an irregular 37-minute job over nine days
        pull(rig.store, fake, NOW + k * 37 * MIN)
    windows = [metrics.window_at(s.captured_at - post.claimed_at) for s in rig.snaps(post)]
    assert sorted(windows) == ["1h", "24h", "72h", "7d"]
    assert len(fake.calls) == 4


def test_pull_is_idempotent_per_post_and_window(rig):
    post = rig.post(age=24 * H)
    fake = FakePostiz(default=analytics(views=1200))
    pull(rig.store, fake, NOW)
    # the job runs every few minutes: a later run inside the same window writes nothing
    again = pull(rig.store, fake, NOW + timedelta(minutes=10))
    assert len(fake.calls) == 1
    assert len(rig.snaps(post)) == 1
    assert again["pulled"] == []
    assert again["already_pulled"] == [{"post_id": post.id, "window": "24h"}]


def test_pull_writes_one_snapshot_per_window_over_a_posts_life(rig):
    post = rig.post(age=1 * H)
    fake = FakePostiz(default=analytics(views=5))
    for age in (1 * H, 24 * H, 72 * H, 7 * D):
        pull(rig.store, fake, NOW - 1 * H + age)  # same post, the clock moves on
    assert len(rig.snaps(post)) == 4
    assert len(fake.calls) == 4


def test_pull_only_looks_at_posted_posts_with_a_postiz_id(rig):
    rig.post(age=24 * H, status=PostStatus.needs_check)
    rig.post(age=24 * H, status=PostStatus.failed)
    rig.post(age=24 * H, status=PostStatus.scheduled, claimed_at=None)
    rig.post(age=24 * H, platform_post_id=None)
    ok = rig.post(age=24 * H)
    fake = FakePostiz(default=analytics(views=1))
    pull(rig.store, fake, NOW)
    assert fake.calls == [["postiz", "analytics:post", ok.platform_post_id, "-d", "7"]]


def test_pull_dates_a_post_by_claimed_at_falling_back_to_scheduled_for(rig):
    # claimed_at says 24 h ago; scheduled_for is far earlier and must not matter
    a = rig.post(age=24 * H, scheduled_for=NOW - 30 * D)
    # no claimed_at: scheduled_for is the posting time
    b = rig.post(age=72 * H, claimed_at=None)
    out = pull(rig.store, FakePostiz(default=analytics(views=1)), NOW)
    assert {(r["post_id"], r["window"]) for r in out["pulled"]} == {(a.id, "24h"), (b.id, "72h")}


def test_pull_needs_an_aware_now(rig):
    with pytest.raises(ValueError, match="timezone-aware"):
        pull(rig.store, FakePostiz(), datetime(2026, 10, 20, 12, 0))


# ---- pull: what Postiz says ----------------------------------------------------------------------


def test_missing_analytics_writes_no_snapshot(rig, caplog):
    post = rig.post(age=24 * H)
    fake = FakePostiz({post.platform_post_id: {"missing": True}})
    with caplog.at_level(logging.WARNING, logger="studio.metrics"):
        out = pull(rig.store, fake, NOW)
    assert rig.snaps(post) == []
    assert out["pulled"] == [] and out["errors"] == []
    assert out["missing"] == [
        {"post_id": post.id, "platform_post_id": post.platform_post_id, "window": "24h"}
    ]
    assert post.platform_post_id in caplog.text and "missing" in caplog.text


def test_a_missing_post_is_asked_again_while_the_window_is_open(rig):
    # no snapshot was written, so a later run in the same window tries again
    post = rig.post(age=24 * H)
    fake = FakePostiz({post.platform_post_id: {"missing": True}})
    pull(rig.store, fake, NOW)
    pull(rig.store, fake, NOW + timedelta(minutes=10))
    assert len(fake.calls) == 2


def test_the_cli_status_line_before_the_json_is_ignored(rig):
    post = rig.post(age=24 * H)
    raw = "✅ Analytics fetched\n" + json.dumps(analytics(views=77))
    pull(rig.store, FakePostiz({post.platform_post_id: raw}), NOW)
    assert rig.snaps(post)[0].views == 77


def test_a_metric_postiz_did_not_report_stays_none_never_zero(rig):
    post = rig.post(age=24 * H)
    pull(rig.store, FakePostiz({post.platform_post_id: analytics(views=10, likes=0)}), NOW)
    (snap,) = rig.snaps(post)
    assert snap.likes == 0  # a reported zero is a zero
    assert snap.comments is None and snap.shares is None and snap.saves is None


def test_views_prefer_the_views_metric_over_impressions(rig):
    a, b = rig.post(age=24 * H), rig.post(age=24 * H)
    fake = FakePostiz({
        a.platform_post_id: analytics(impressions=900, views=100),
        b.platform_post_id: analytics(impressions=900),
    })  # fmt: skip
    pull(rig.store, fake, NOW)
    assert rig.snaps(a)[0].views == 100
    assert rig.snaps(b)[0].views == 900


def test_totals_may_be_strings_and_the_latest_data_point_wins(rig):
    post = rig.post(age=24 * H)
    payload = [
        {
            "label": "Views",
            "data": [
                {"total": "10", "date": "2026-10-19"},
                {"total": "120", "date": "2026-10-20"},
                {"total": "30", "date": "2026-10-18"},
            ],
            "percentageChange": 5,
        },
        {"label": "likes", "data": [{"total": 4.0, "date": "2026-10-20"}]},
    ]
    pull(rig.store, FakePostiz({post.platform_post_id: payload}), NOW)
    (snap,) = rig.snaps(post)
    assert (snap.views, snap.likes) == (120, 4)


def test_unusable_values_become_none(rig):
    post = rig.post(age=24 * H)
    payload = [
        {"label": "Views", "data": [{"total": "n/a", "date": "2026-10-20"}]},
        {"label": "Likes", "data": []},
        {"label": "Comments", "data": [{"total": -3, "date": "2026-10-20"}]},
        {"label": "Shares", "data": [{"total": True, "date": "2026-10-20"}]},
        {"label": "Saves", "data": [{"total": "12", "date": "2026-10-20"}]},
        {"label": "Something Else", "data": [{"total": "99", "date": "2026-10-20"}]},
        "not a metric",
    ]
    pull(rig.store, FakePostiz({post.platform_post_id: payload}), NOW)
    (snap,) = rig.snaps(post)
    assert (snap.views, snap.likes, snap.comments, snap.shares, snap.saves) == (
        None, None, None, None, 12,
    )


@pytest.mark.parametrize("payload", [[], [{"label": "Followers", "data": [{"total": "3"}]}], {}, "[]"])
def test_a_reply_with_no_recognised_metric_writes_no_snapshot(rig, payload):
    post = rig.post(age=24 * H)
    out = pull(rig.store, FakePostiz({post.platform_post_id: payload}), NOW)
    assert rig.snaps(post) == []
    assert out["empty"] == [{"post_id": post.id, "window": "24h"}]
    assert out["errors"] == []


@pytest.mark.parametrize(
    "reply",
    [
        ("exit", 1, "❌ Not authenticated"),
        subprocess.TimeoutExpired(["postiz"], 120),
        "garbage, no json here",
        OSError("postiz: not found"),
    ],
)
def test_a_failed_pull_is_reported_and_writes_nothing(rig, reply):
    post = rig.post(age=24 * H)
    out = pull(rig.store, FakePostiz({post.platform_post_id: reply}), NOW)
    assert rig.snaps(post) == []
    assert len(out["errors"]) == 1
    assert out["errors"][0]["post_id"] == post.id and out["errors"][0]["error"]


def test_one_failing_post_does_not_stop_the_others(rig):
    bad, good = rig.post(age=24 * H), rig.post(age=24 * H)
    fake = FakePostiz({bad.platform_post_id: ("exit", 1, "boom"),
                       good.platform_post_id: analytics(views=3)})  # fmt: skip
    out = pull(rig.store, fake, NOW)
    assert [r["post_id"] for r in out["pulled"]] == [good.id]
    assert [e["post_id"] for e in out["errors"]] == [bad.id]


def test_postiz_is_called_like_the_publisher_calls_it(rig):
    rig.post(age=24 * H)
    fake = FakePostiz(default=analytics(views=1))
    pull(rig.store, fake, NOW)
    kw = fake.kwargs[0]
    assert kw["capture_output"] is True and kw["encoding"] == "utf-8" and kw["errors"] == "replace"
    assert kw["stdin"] == subprocess.DEVNULL and kw["timeout"] > 0


def test_pull_works_with_a_real_subprocess(rig, tmp_path):
    """Real ``subprocess.run`` against a tiny executable that prints a status line and JSON."""
    post = rig.post(age=24 * H)
    script = tmp_path / "postiz"
    script.write_text(
        "#!/bin/sh\n"
        'echo "✅ ok"\n'
        f'echo \'[{{"label":"Views","data":[{{"total":"42","date":"2026-10-20"}}]}}]\'\n'
        f'echo "$@" > "{tmp_path}/argv"\n',
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    pull(rig.store, subprocess.run, NOW, executable=str(script))
    assert rig.snaps(post)[0].views == 42
    assert (tmp_path / "argv").read_text().split() == ["analytics:post", post.platform_post_id, "-d", "7"]


# ---- pull: outlier_x at 7 days ---------------------------------------------------------------------


def seven_day_rig(
    rig: Rig, *, handle="@biscuit.tt", priors=(100, 200, 300), views=600, age=7 * D, **features
):
    clip = rig.clip(**features)
    post = rig.post(handle, age=age, clip=clip)
    rig.history(handle, list(priors), target_at=NOW - age)
    fake = FakePostiz({post.platform_post_id: analytics(views=views)})
    return clip, post, fake


def test_the_seven_day_pull_writes_outlier_x_to_the_clip(rig):
    clip, post, fake = seven_day_rig(rig)
    out = pull(rig.store, fake, NOW)
    assert rig.features(clip)["outlier_x"] == 3.0
    assert out["outlier_x"] == [{"clip_id": clip.id, "outlier_x": 3.0}]


def test_outlier_x_keeps_the_clips_other_features(rig):
    clip, _, fake = seven_day_rig(rig, hook_type="odd eyes", rerolls=1, motion={"preset": "p"})
    pull(rig.store, fake, NOW)
    assert rig.features(clip) == {
        "hook_type": "odd eyes", "rerolls": 1, "motion": {"preset": "p"}, "outlier_x": 3.0,
    }


def test_earlier_windows_never_write_outlier_x(rig):
    clip = rig.clip()
    post = rig.post(age=72 * H, clip=clip)
    rig.history("@biscuit.tt", [100, 200, 300], target_at=NOW - 72 * H)
    pull(rig.store, FakePostiz({post.platform_post_id: analytics(views=600)}), NOW)
    assert "outlier_x" not in rig.features(clip)


def test_too_few_priors_means_no_outlier_x(rig):
    clip, _, fake = seven_day_rig(rig, priors=(100, 200))
    out = pull(rig.store, fake, NOW)
    assert "outlier_x" not in rig.features(clip)
    assert out["outlier_x"] == []


def test_priors_are_this_accounts_earlier_posts_only(rig):
    clip, post, fake = seven_day_rig(rig, priors=(100, 200, 300))
    # another account's history (huge) and this account's later post (huge) must not count
    rig.history("@reginald.tt", [10_000] * 5, target_at=NOW - 7 * D)
    later = rig.post("@biscuit.tt", age=2 * D, platform_post_id=None)
    rig.seven_day_views(later, 50_000)
    pull(rig.store, fake, NOW)
    assert rig.features(clip)["outlier_x"] == 3.0


def test_a_prior_without_seven_day_views_is_left_out_not_counted_as_zero(rig):
    # two real priors plus one that never got a 7-day snapshot: only 2 usable -> no baseline
    clip, _, fake = seven_day_rig(rig, priors=(100, None, 300))
    pull(rig.store, fake, NOW)
    assert "outlier_x" not in rig.features(clip)
    # with a fourth usable prior the None is simply skipped: median of [100, 300, 200] = 200
    rig2 = Rig()
    clip2, _, fake2 = seven_day_rig(rig2, priors=(100, None, 300, 200))
    rig2.post("@biscuit.tt", age=20 * D, platform_post_id=None)  # no snapshot at all: also skipped
    pull(rig2.store, fake2, NOW)
    assert rig2.features(clip2)["outlier_x"] == 3.0


def test_a_priors_views_are_its_first_reading_from_day_7_not_an_earlier_or_later_one(rig):
    clip = rig.clip()
    post = rig.post(age=7 * D, clip=clip)
    posts = rig.history("@biscuit.tt", [100, 200, 300], target_at=NOW - 7 * D)
    for p in posts:  # a reading at 24 h is too early and a reading at day 9 comes after the first
        for age in (24 * H, 9 * D):
            rig.store.add_snapshot(
                Snapshot(post_id=p.id, captured_at=p.claimed_at + age, views=9_999 if age > D else 1)
            )
    pull(rig.store, FakePostiz({post.platform_post_id: analytics(views=600)}), NOW)
    assert rig.features(clip)["outlier_x"] == 3.0


def test_outlier_x_uses_only_the_last_15_priors_of_the_account(rig):
    clip, _, fake = seven_day_rig(rig, priors=[5_000] * 8 + [100] * 15, views=300)
    pull(rig.store, fake, NOW)
    assert rig.features(clip)["outlier_x"] == 3.0


def test_the_last_15_are_the_most_recently_posted_not_the_latest_scheduled(rig):
    clip = rig.clip()
    post = rig.post(age=7 * D, clip=clip)
    old = rig.history("@biscuit.tt", [5_000] * 16 + [100] * 15, target_at=NOW - 7 * D)
    for i, p in enumerate(old):  # scheduled_for runs backwards: the store lists newest-posted first
        rig.store.update_post(p.id, scheduled_for=NOW - 60 * D - i * H)
    pull(rig.store, FakePostiz({post.platform_post_id: analytics(views=300)}), NOW)
    assert rig.features(clip)["outlier_x"] == 3.0


def test_the_clip_gets_the_best_outlier_x_over_its_accounts(rig):
    clip = rig.clip()
    tt = rig.post("@biscuit.tt", age=7 * D, clip=clip)
    ig = rig.post("@biscuit.ig", age=7 * D, clip=clip)
    rig.history("@biscuit.tt", [100, 200, 300], target_at=NOW - 7 * D)
    rig.history("@biscuit.ig", [50, 100, 150], target_at=NOW - 7 * D)
    fake = FakePostiz({tt.platform_post_id: analytics(views=400),   # 400 / 200 = 2.0
                       ig.platform_post_id: analytics(views=500)})  # 500 / 100 = 5.0
    pull(rig.store, fake, NOW)
    assert rig.features(clip)["outlier_x"] == 5.0


def test_the_clip_value_is_the_max_even_when_the_best_account_has_no_baseline(rig):
    clip = rig.clip()
    tt = rig.post("@biscuit.tt", age=7 * D, clip=clip)
    ig = rig.post("@biscuit.ig", age=7 * D, clip=clip)
    rig.history("@biscuit.tt", [100, 200, 300], target_at=NOW - 7 * D)  # ig has no history
    fake = FakePostiz({tt.platform_post_id: analytics(views=400),
                       ig.platform_post_id: analytics(views=9_999)})  # fmt: skip
    pull(rig.store, fake, NOW)
    assert rig.features(clip)["outlier_x"] == 2.0


def test_a_clip_is_refreshed_when_the_seven_day_snapshot_already_exists(rig):
    """Crash recovery: the snapshot was written but the clip update was not."""
    clip, post, fake = seven_day_rig(rig, age=7 * D + 1 * H)
    rig.store.add_snapshot(Snapshot(post_id=post.id, captured_at=NOW - 10 * MIN, views=600))
    pull(rig.store, fake, NOW)
    assert fake.calls == []  # idempotent: nothing is fetched again
    assert rig.features(clip)["outlier_x"] == 3.0


def test_a_rerun_does_not_change_or_duplicate_anything(rig):
    clip, post, fake = seven_day_rig(rig)
    pull(rig.store, fake, NOW)
    again = pull(rig.store, fake, NOW + timedelta(minutes=5))
    assert len(rig.snaps(post)) == 1
    assert rig.features(clip)["outlier_x"] == 3.0
    assert again["pulled"] == []
    assert len(fake.calls) == 1


def test_views_at_7d_is_the_first_reading_from_day_7_on(rig):
    post = rig.post(age=8 * D)
    at = post.claimed_at
    for age, views in [(7 * D - 10 * MIN, 500), (7 * D + 5 * MIN, None), (7 * D + 30 * MIN, 600),
                       (7 * D + 3 * H, 700), (9 * D, 800)]:  # fmt: skip
        rig.store.add_snapshot(Snapshot(post_id=post.id, captured_at=at + age, views=views))
    # 500 is too early, None is not a reading, 600 is the first one: later readings never move it
    assert metrics.views_at_7d(rig.store, post) == 600


def test_views_at_7d_counts_a_late_reading_and_ignores_early_ones(rig):
    post = rig.post(age=12 * D)
    at = post.claimed_at
    for age in (1 * H, 24 * H, 3 * D, 7 * D - MIN):
        rig.store.add_snapshot(Snapshot(post_id=post.id, captured_at=at + age, views=9_999))
    assert metrics.views_at_7d(rig.store, post) is None
    rig.store.add_snapshot(Snapshot(post_id=post.id, captured_at=at + 9 * D, views=1_234))
    assert metrics.views_at_7d(rig.store, post) == 1_234


def test_a_late_seven_day_reading_serves_as_a_prior(rig):
    clip = rig.clip()
    post = rig.post(age=7 * D, clip=clip)
    priors = rig.history("@biscuit.tt", [100, 200], target_at=NOW - 7 * D)
    late = rig.post("@biscuit.tt", age=7 * D + 1 * D + 2 * H)  # between the others in time, read late
    rig.store.add_snapshot(Snapshot(post_id=late.id, captured_at=late.claimed_at + 9 * D, views=300))
    assert [p.id for p in priors] and late.claimed_at < post.claimed_at
    pull(rig.store, FakePostiz({post.platform_post_id: analytics(views=600)}), NOW)
    assert rig.features(clip)["outlier_x"] == 3.0


def test_an_old_clip_without_outlier_x_gets_it_from_an_existing_figure(rig):
    """A figure that exists (say, from an ingest long ago) fills a clip that has no outlier_x yet."""
    clip = rig.clip(hook_type="x")
    post = rig.post(age=10 * D, clip=clip)
    rig.store.add_snapshot(Snapshot(post_id=post.id, captured_at=post.claimed_at + 8 * D, views=600))
    rig.history("@biscuit.tt", [100, 200, 300], target_at=NOW - 10 * D)
    pull(rig.store, FakePostiz(), NOW)
    assert rig.features(clip) == {"hook_type": "x", "outlier_x": 3.0}


def test_a_later_accounts_seven_day_pull_raises_the_clip_value(rig):
    clip = rig.clip()
    tt = rig.post("@biscuit.tt", age=7 * D, clip=clip)
    ig = rig.post("@biscuit.ig", age=7 * D, clip=clip)
    rig.history("@biscuit.tt", [100, 200, 300], target_at=NOW - 7 * D)
    rig.history("@biscuit.ig", [50, 100, 150], target_at=NOW - 7 * D)
    # run 1: TikTok answers (400 / 200 = 2.0), Instagram has no provider id yet
    first = pull(rig.store, FakePostiz({tt.platform_post_id: analytics(views=400),
                                        ig.platform_post_id: {"missing": True}}), NOW)  # fmt: skip
    assert rig.features(clip)["outlier_x"] == 2.0 and len(first["missing"]) == 1
    # run 2, an hour later: Instagram answers (500 / 100 = 5.0) and the clip moves up to it
    second = pull(rig.store, FakePostiz({ig.platform_post_id: analytics(views=500)}), NOW + 1 * H)
    assert second["pulled"] == [{"post_id": ig.id, "window": "7d"}]
    assert rig.features(clip)["outlier_x"] == 5.0
    assert second["outlier_x"] == [{"clip_id": clip.id, "outlier_x": 5.0}]


def test_refreshing_an_unchanged_clip_writes_nothing(rig, monkeypatch):
    clip, post, fake = seven_day_rig(rig)
    pull(rig.store, fake, NOW)
    writes = []
    real = rig.store.update_clip
    monkeypatch.setattr(rig.store, "update_clip", lambda *a, **k: writes.append(a) or real(*a, **k))
    assert metrics.refresh_clip_outlier_x(rig.store, clip.id) == 3.0
    assert writes == []


def test_a_rerun_does_not_rewrite_an_unchanged_clip(rig, monkeypatch):
    clip, post, fake = seven_day_rig(rig)
    pull(rig.store, fake, NOW)
    writes = []
    real = rig.store.update_clip
    monkeypatch.setattr(rig.store, "update_clip", lambda *a, **k: writes.append(a) or real(*a, **k))
    pull(rig.store, fake, NOW + timedelta(minutes=5))
    assert writes == []


# ---- ingest_ig_insights --------------------------------------------------------------------------


def ig_row(post: Post, **fields: Any) -> dict[str, Any]:
    return {"id": post.platform_post_id, **fields}


def test_ingest_maps_owner_metrics_into_a_snapshot(rig):
    post = rig.post("@biscuit.ig", age=72 * H)
    out = ingest_ig_insights(
        rig.store,
        [ig_row(post, views=5000, likes=300, comments=20, shares=45, saves=80,
                watchTime=12345.5, watchedPercentage=41.2, skipRate=0.37, isPossibleTrial=False,
                caption="hello", somethingNew={"x": 1})],
        now=NOW,
    )  # fmt: skip
    (snap,) = rig.snaps(post)
    assert snap.captured_at == NOW
    assert (snap.views, snap.likes, snap.comments, snap.shares, snap.saves) == (5000, 300, 20, 45, 80)
    assert snap.watch_time_s == 12345.5
    assert snap.follows is None and snap.non_follower_pct is None
    assert out["ingested"] == [{"post_id": post.id, "platform_post_id": post.platform_post_id}]


def test_ingest_accepts_plays_for_views(rig):
    post = rig.post("@biscuit.ig")
    ingest_ig_insights(rig.store, [ig_row(post, plays=900)], now=NOW)
    assert rig.snaps(post)[0].views == 900


def test_ingest_nullable_values_stay_none(rig):
    post = rig.post("@biscuit.ig")
    ingest_ig_insights(
        rig.store,
        [ig_row(post, views=100, shares=None, saves=None, watchTime=None, likes=0)],
        now=NOW,
    )
    (snap,) = rig.snaps(post)
    assert snap.views == 100 and snap.likes == 0
    assert snap.shares is None and snap.saves is None and snap.watch_time_s is None


def test_ingest_ignores_unknown_fields_and_bad_values(rig):
    post = rig.post("@biscuit.ig")
    ingest_ig_insights(
        rig.store,
        [ig_row(post, views="n/a", likes=True, comments=-4, shares="12", saves=1.5, mystery=7)],
        now=NOW,
    )
    (snap,) = rig.snaps(post)
    assert (snap.views, snap.likes, snap.comments, snap.shares, snap.saves) == (
        None, None, None, 12, None,
    )


def test_ingest_reads_watch_time_in_milliseconds_when_the_field_says_so(rig):
    post = rig.post("@biscuit.ig")
    ingest_ig_insights(rig.store, [ig_row(post, watchTimeMs=2500, views=1)], now=NOW)
    assert rig.snaps(post)[0].watch_time_s == 2.5


def test_ingest_skips_rows_for_unknown_posts(rig):
    post = rig.post("@biscuit.ig")
    out = ingest_ig_insights(
        rig.store,
        [{"id": "not-ours", "views": 10}, {"views": 10}, "junk", ig_row(post, views=7)],
        now=NOW,
    )
    assert [r["post_id"] for r in out["ingested"]] == [post.id]
    assert out["unmatched"] == ["not-ours"] and out["skipped"] == 2
    assert len(rig.snaps(post)) == 1


def test_ingest_skips_a_row_with_no_metrics_at_all(rig):
    post = rig.post("@biscuit.ig")
    out = ingest_ig_insights(rig.store, [ig_row(post, skipRate=0.4, caption="x")], now=NOW)
    assert rig.snaps(post) == []
    assert out["empty"] == [{"post_id": post.id, "platform_post_id": post.platform_post_id}]


def test_ingest_is_idempotent_for_unchanged_numbers(rig):
    post = rig.post("@biscuit.ig")
    row = ig_row(post, views=100, shares=5)
    ingest_ig_insights(rig.store, [row], now=NOW)
    again = ingest_ig_insights(rig.store, [row], now=NOW + D)
    assert len(rig.snaps(post)) == 1
    assert again["ingested"] == [] and len(again["unchanged"]) == 1
    # a changed number is new information
    ingest_ig_insights(rig.store, [ig_row(post, views=150, shares=5)], now=NOW + 2 * D)
    assert [s.views for s in rig.snaps(post)] == [100, 150]


def test_ingest_matches_on_platform_post_id_across_accounts(rig):
    a, b = rig.post("@biscuit.ig"), rig.post("@biscuit.tt")
    ingest_ig_insights(rig.store, [ig_row(a, views=1)], now=NOW)
    assert len(rig.snaps(a)) == 1 and rig.snaps(b) == []


def test_ingest_accepts_numeric_ids(rig):
    post = rig.post("@biscuit.ig", platform_post_id="178900")
    ingest_ig_insights(rig.store, [{"id": 178900, "views": 3}], now=NOW)
    assert rig.snaps(post)[0].views == 3


def test_an_ingested_snapshot_feeds_the_seven_day_views(rig):
    """The 7-day figure is whichever snapshot sits in the window, wherever it came from."""
    clip = rig.clip()
    post = rig.post("@biscuit.ig", age=7 * D, clip=clip)
    rig.history("@biscuit.ig", [100, 200, 300], target_at=NOW - 7 * D)
    ingest_ig_insights(rig.store, [ig_row(post, views=600)], now=NOW)
    pull(rig.store, FakePostiz(), NOW)
    assert rig.features(clip)["outlier_x"] == 3.0


def test_ingest_refreshes_the_clip_when_it_brings_a_seven_day_figure(rig):
    clip = rig.clip(hook_type="x")
    ig = rig.post("@biscuit.ig", age=8 * D, clip=clip)
    rig.history("@biscuit.ig", [100, 200, 300], target_at=NOW - 8 * D)
    out = ingest_ig_insights(rig.store, [ig_row(ig, views=600)], now=ig.claimed_at + 7 * D + 2 * H)
    assert rig.features(clip) == {"hook_type": "x", "outlier_x": 3.0}
    assert out["outlier_x"] == [{"clip_id": clip.id, "outlier_x": 3.0}]


def test_ingest_takes_the_clip_to_the_best_of_its_accounts(rig):
    clip = rig.clip()
    tt = rig.post("@biscuit.tt", age=8 * D, clip=clip)
    ig = rig.post("@biscuit.ig", age=8 * D, clip=clip)
    rig.history("@biscuit.tt", [100, 200, 300], target_at=NOW - 8 * D)
    rig.history("@biscuit.ig", [100, 100, 100], target_at=NOW - 8 * D)
    rig.store.add_snapshot(Snapshot(post_id=tt.id, captured_at=tt.claimed_at + 7 * D, views=400))
    rig.store.update_clip(clip.id, features={"outlier_x": 2.0})
    ingest_ig_insights(rig.store, [ig_row(ig, views=500)], now=ig.claimed_at + 7 * D + 1 * H)
    assert rig.features(clip)["outlier_x"] == 5.0


def test_ingest_of_an_early_reading_does_not_touch_the_clip(rig):
    clip = rig.clip()
    ig = rig.post("@biscuit.ig", age=2 * D, clip=clip)
    out = ingest_ig_insights(rig.store, [ig_row(ig, views=600)], now=NOW)
    assert "outlier_x" not in rig.features(clip) and out["outlier_x"] == []


# ---- Postiz series aggregation -------------------------------------------------------------------

SERIES = [
    {
        "label": "Views",
        "data": [
            {"total": "10", "date": "2026-10-19"},
            {"total": "120", "date": "2026-10-20"},
            {"total": "30", "date": "2026-10-18"},
            {"total": "n/a", "date": "2026-10-21"},
        ],
    },
    {"label": "Likes", "data": [{"total": "4", "date": "2026-10-20"}]},
]


def test_series_mode_is_an_explicit_named_constant_defaulting_to_latest():
    assert metrics.POSTIZ_SERIES_MODE == "latest"


def test_series_mode_latest_takes_the_newest_data_point(monkeypatch):
    monkeypatch.setattr(metrics, "POSTIZ_SERIES_MODE", "latest")
    assert metrics.parse_post_analytics(SERIES) == {"views": 120, "likes": 4}


def test_series_mode_sum_adds_the_usable_data_points(monkeypatch):
    monkeypatch.setattr(metrics, "POSTIZ_SERIES_MODE", "sum")
    assert metrics.parse_post_analytics(SERIES) == {"views": 160, "likes": 4}


@pytest.mark.parametrize("mode", ["latest", "sum"])
def test_series_mode_with_nothing_usable_is_none(monkeypatch, mode):
    monkeypatch.setattr(metrics, "POSTIZ_SERIES_MODE", mode)
    payload = [{"label": "Views", "data": [{"total": "n/a", "date": "2026-10-20"}]}]
    assert metrics.parse_post_analytics(payload) == {}


def test_series_mode_reaches_the_snapshot(rig, monkeypatch):
    post = rig.post(age=24 * H)
    monkeypatch.setattr(metrics, "POSTIZ_SERIES_MODE", "sum")
    pull(rig.store, FakePostiz({post.platform_post_id: SERIES}), NOW)
    assert rig.snaps(post)[0].views == 160


def test_an_unknown_series_mode_is_an_error_not_a_silent_default(monkeypatch):
    monkeypatch.setattr(metrics, "POSTIZ_SERIES_MODE", "mean")
    with pytest.raises(ValueError, match="POSTIZ_SERIES_MODE"):
        metrics.parse_post_analytics(SERIES)


def test_an_unknown_series_mode_is_reported_by_the_pull_not_swallowed(rig, monkeypatch):
    post = rig.post(age=24 * H)
    monkeypatch.setattr(metrics, "POSTIZ_SERIES_MODE", "mean")
    out = pull(rig.store, FakePostiz({post.platform_post_id: SERIES}), NOW)
    assert rig.snaps(post) == [] and "POSTIZ_SERIES_MODE" in out["errors"][0]["error"]


# ---- CLI -----------------------------------------------------------------------------------------


@pytest.fixture
def cli(monkeypatch):
    rig = Rig()
    monkeypatch.setattr(metrics, "open_store", lambda: rig.store)
    monkeypatch.setattr(metrics, "now_london", lambda: NOW)
    monkeypatch.setenv("POSTIZ_API_KEY", "pz-key-DO-NOT-LEAK")
    monkeypatch.setattr(metrics, "which", lambda name: f"/usr/local/bin/{name}")
    return rig


def run_cli(*args: str, input: str | None = None):
    return CliRunner().invoke(app, ["metrics", *args], input=input)


def test_cli_help_lists_the_commands():
    r = run_cli("--help")
    assert r.exit_code == 0 and "pull" in r.output and "ingest-ig" in r.output


def test_cli_pull_prints_the_summary(cli, monkeypatch):
    post = cli.post(age=24 * H)
    fake = FakePostiz({post.platform_post_id: analytics(views=9)})
    monkeypatch.setattr(subprocess, "run", fake)
    r = run_cli("pull")
    assert r.exit_code == 0, r.output
    assert json.loads(r.stdout)["pulled"] == [{"post_id": post.id, "window": "24h"}]
    assert cli.snaps(post)[0].views == 9
    assert "DO-NOT-LEAK" not in r.output


def test_cli_pull_exits_1_when_a_pull_failed(cli, monkeypatch):
    post = cli.post(age=24 * H)
    monkeypatch.setattr(subprocess, "run", FakePostiz({post.platform_post_id: ("exit", 1, "boom")}))
    r = run_cli("pull")
    assert r.exit_code == 1
    assert len(json.loads(r.stdout)["errors"]) == 1


def test_cli_pull_with_a_missing_post_is_still_exit_0(cli, monkeypatch):
    post = cli.post(age=24 * H)
    monkeypatch.setattr(subprocess, "run", FakePostiz({post.platform_post_id: {"missing": True}}))
    r = run_cli("pull")
    assert r.exit_code == 0
    assert len(json.loads(r.stdout)["missing"]) == 1


def test_cli_pull_without_postiz_key_is_a_caller_error(cli, monkeypatch):
    monkeypatch.delenv("POSTIZ_API_KEY")
    r = run_cli("pull")
    assert r.exit_code == 2 and "POSTIZ_API_KEY" in r.output


def test_cli_pull_without_the_postiz_binary_is_a_caller_error(cli, monkeypatch):
    monkeypatch.setattr(metrics, "which", lambda name: None)
    r = run_cli("pull")
    assert r.exit_code == 2 and "postiz" in r.output


def test_cli_without_database_url_is_a_caller_error(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert run_cli("pull").exit_code == 2
    assert run_cli("ingest-ig", "-", input="[]").exit_code == 2


def test_cli_ingest_ig_from_a_file(cli, tmp_path):
    post = cli.post("@biscuit.ig")
    f = tmp_path / "rows.json"
    f.write_text(json.dumps([ig_row(post, views=11, shares=2)]))
    r = run_cli("ingest-ig", str(f))
    assert r.exit_code == 0, r.output
    assert len(json.loads(r.stdout)["ingested"]) == 1
    assert cli.snaps(post)[0].shares == 2


def test_cli_ingest_ig_from_stdin_and_inline_json(cli):
    a, b = cli.post("@biscuit.ig"), cli.post("@biscuit.ig")
    assert run_cli("ingest-ig", "-", input=json.dumps([ig_row(a, views=1)])).exit_code == 0
    assert run_cli("ingest-ig", json.dumps([ig_row(b, views=2)])).exit_code == 0
    assert cli.snaps(a)[0].views == 1 and cli.snaps(b)[0].views == 2


def test_cli_ingest_ig_accepts_the_rows_inside_an_object(cli):
    post = cli.post("@biscuit.ig")
    payload = {"status": "ok", "reels": [ig_row(post, views=5)]}
    r = run_cli("ingest-ig", "-", input=json.dumps(payload))
    assert r.exit_code == 0, r.output
    assert cli.snaps(post)[0].views == 5


@pytest.mark.parametrize("text", ["not json", '{"status": "unavailable"}', '"a string"', "42"])
def test_cli_ingest_ig_rejects_what_is_not_rows(cli, text):
    r = run_cli("ingest-ig", "-", input=text)
    assert r.exit_code == 2 and "error:" in r.output


def test_cli_ingest_ig_missing_file_is_a_caller_error(cli, tmp_path):
    r = run_cli("ingest-ig", str(tmp_path / "nope.json"))
    assert r.exit_code == 2


def test_metrics_replaced_the_empty_skeleton():
    from studio import cli as cli_module

    assert "metrics" not in cli_module.SUBAPPS
