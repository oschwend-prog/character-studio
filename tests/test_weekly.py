"""The weekly review in the cloud (learning plan 4.2, 4.3, 6.1, build items 10-11): the score test (test A), the mechanism floors,
the rule candidates and arm proposals, the playbooks, the digest and ``studio review weekly``.

Every rule is a pure function with its threshold tested at the exact boundary (the plan's sections 3 and 4.3 are frozen); the whole
run is tested on ``MemoryStore``. Nothing here touches the network or a database.
"""

from __future__ import annotations

import json
import random
import statistics
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from collections.abc import Sequence

import pytest
from typer.testing import CliRunner

from studio import experiments, weekly
from studio.cli import app
from studio.config import LONDON
from studio.models import Account, Body, Character, Clip, Post, Snapshot
from studio.store import MemoryStore
from studio.weekly import ScoreObservation, average_ranks, look_label, middle_span, score_test, spearman

H = timedelta(hours=1)
D = timedelta(days=1)
T0 = datetime(2026, 10, 13, 19, 0, tzinfo=LONDON)  # a Tuesday evening: the first posts


# ---- Spearman with average ranks -------------------------------------------------------------------------------------------------------


def test_average_ranks_give_ties_the_mean_of_their_places():
    assert average_ranks([10, 20, 30]) == [1.0, 2.0, 3.0]
    assert average_ranks([5, 6, 7, 8, 7]) == [1.0, 2.0, 3.5, 5.0, 3.5]
    assert average_ranks([4, 4, 4]) == [2.0, 2.0, 2.0]
    assert average_ranks([]) == []


def test_spearman_is_the_correlation_of_the_average_ranks():
    assert spearman([1, 2, 3, 4, 5], [10, 20, 30, 40, 50]) == pytest.approx(1.0)
    assert spearman([1, 2, 3, 4, 5], [50, 40, 30, 20, 10]) == pytest.approx(-1.0)
    assert spearman([1, 2, 3, 4, 5], [5, 6, 7, 8, 7]) == pytest.approx(8 / 95**0.5)  # ties, worked by hand: 0.8208
    assert spearman([1, 2, 3, 4, 5], [2, 1, 4, 3, 5]) == pytest.approx(0.8)
    assert spearman([3, 1, 2], [30, 10, 20]) == pytest.approx(1.0)  # only the order counts, not the size


def test_spearman_of_something_that_does_not_vary_is_zero_not_an_error():
    assert spearman([5, 5, 5, 5], [1, 2, 3, 4]) == 0.0
    assert spearman([1, 2, 3, 4], [7, 7, 7, 7]) == 0.0
    assert spearman([1], [1]) == 0.0 and spearman([], []) == 0.0
    with pytest.raises(ValueError):
        spearman([1, 2], [1, 2, 3])


# ---- test A: the decision at a look, at its exact boundaries ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("rho", "label"),
    [(1.0, "validated"), (0.45, "validated"), (0.4499999, "unproven"), (0.31, "unproven"), (0.0001, "unproven"), (0.0, "failed"), (-0.3, "failed")],
)
def test_the_interim_look_at_20(rho, label):
    assert look_label(rho, span=40, look=20) == label


@pytest.mark.parametrize(("rho", "label"), [(0.31, "validated"), (0.3099999, "failed"), (0.9, "validated"), (0.0, "failed"), (-0.5, "failed")])
def test_the_final_look_at_40(rho, label):
    assert look_label(rho, span=40, look=40) == label


@pytest.mark.parametrize("look", [20, 40])
def test_a_narrow_range_is_uninformative_never_failed(look):
    assert look_label(-0.5, span=14.99, look=look) == "uninformative"  # under 15 points: do not fail the score
    assert look_label(0.9, span=14.99, look=look) == "uninformative"
    assert look_label(-0.5, span=15, look=look) != "uninformative"  # exactly 15 is wide enough


def test_the_middle_80_percent_drops_the_lowest_and_highest_tenth():
    assert middle_span(list(range(0, 100, 5))) == 75  # 20 scores 0, 5 ... 95: the 2 lowest and 2 highest go, 10 .. 85 stay
    assert middle_span(list(range(40))) == 31  # 40 scores: 4 + 4 go, 4 .. 35 stay
    assert middle_span([50] * 20) == 0
    assert middle_span([0, 100] + [50] * 18) == 0  # the two extremes are outside the middle 80 %
    assert middle_span([10, 90]) == 80 and middle_span([]) == 0  # under 10 scores nothing is dropped


# ---- test A: the whole test on observations ---------------------------------------------------------------------------------------------


def obs(i: int, score: int, x: float, *, potential: int | None = None, swap: int | None = None, day: float | None = None) -> ScoreObservation:
    """The ``i``-th observation; its outlier_x became available ``i`` days after T0 unless ``day`` says otherwise."""
    return ScoreObservation(
        clip_id=f"c{i:03d}", available_at=T0 + (i if day is None else day) * D, score=score, outlier_x=x, potential=potential, swap=swap,
    )


def scores(n: int, low: int = 30, step: int = 3) -> list[int]:
    """``n`` scores climbing from ``low`` by ``step`` (wide: 20 of them have a middle 80 % of 42 points)."""
    return [low + step * i for i in range(n)]


def rising(n: int, start: int = 0) -> list[ScoreObservation]:
    """Observations whose outlier_x rises with the score (rho = 1)."""
    return [obs(start + i, s, 0.5 + 0.1 * i) for i, s in enumerate(scores(n))]


def falling(n: int, start: int = 0) -> list[ScoreObservation]:
    return [obs(start + i, s, 5.0 - 0.1 * i) for i, s in enumerate(scores(n))]


def with_rho(n: int, lo: float, hi: float, seed: int = 1) -> list[float]:
    """A shuffle of 0..n-1 whose Spearman rho with 0..n-1 lies in [lo, hi] (a fixed seed: always the same series)."""
    rng = random.Random(seed)
    base = list(range(n))
    for _ in range(100_000):
        cand = base[:]
        rng.shuffle(cand)
        if lo <= spearman(base, cand) <= hi:
            return [float(v) + 1 for v in cand]
    raise AssertionError("no series found")


def test_before_20_observations_it_is_unproven_and_shows_only_the_count():
    r = score_test(rising(19))
    assert r["label"] == "unproven" and r["n"] == 19 and r["needed"] == 20 and r["look"] is None
    assert r["rho"] is None and r["rho_potential"] is None and r["rho_swap"] is None and r["buckets"] == []  # no peeking
    assert "19 of 20" in r["note"] and "Not a verdict" in r["note"]
    r0 = score_test([])
    assert (r0["label"], r0["n"], r0["needed"], r0["look"]) == ("unproven", 0, 20, None)


def test_a_strong_rank_correlation_at_the_interim_look_validates_and_the_label_sticks():
    r = score_test(rising(20))
    assert (r["label"], r["look"], r["needed"], r["n"]) == ("validated", 20, 20, 20)
    assert r["rho"] == pytest.approx(1.0)
    # more observations afterwards, even contradicting ones, never change a decided test
    later = rising(20) + [obs(20 + i, 90 - 2 * i, 0.1) for i in range(30)]
    again = score_test(later)
    assert (again["label"], again["look"], again["rho"], again["n"]) == ("validated", 20, r["rho"], 50)


def test_no_positive_correlation_at_the_interim_look_fails_the_score_and_the_label_sticks():
    r = score_test(falling(20))
    assert (r["label"], r["look"], r["needed"]) == ("failed", 20, 20) and r["rho"] == pytest.approx(-1.0)
    assert score_test(falling(20) + rising(25, start=20))["label"] == "failed"


def test_a_middling_correlation_is_unproven_until_40_and_the_look_at_20_is_never_recomputed():
    xs = with_rho(20, 0.1, 0.4)
    first20 = [obs(i, s, x) for i, (s, x) in enumerate(zip(scores(20), xs, strict=True))]
    r = score_test(first20)
    assert (r["label"], r["look"], r["needed"], r["n"]) == ("unproven", 20, 40, 20)
    assert 0.1 <= r["rho"] <= 0.4 and "unproven until 40" in r["note"] and "Not a verdict" in r["note"]
    # 21..39: the look at 20 stands: the same rho, whatever the new ones say (no peeking)
    more = first20 + [obs(20 + i, 40 + 2 * i, 3.0 + i) for i in range(10)]
    r30 = score_test(more)
    assert (r30["label"], r30["look"], r30["needed"], r30["n"], r30["rho"]) == ("unproven", 20, 40, 30, r["rho"])


def test_the_final_look_at_40_uses_the_first_40_and_ignores_later_ones():
    xs20 = with_rho(20, 0.1, 0.4)
    first = [obs(i, s, x) for i, (s, x) in enumerate(zip(scores(20), xs20, strict=True))]
    good = [obs(20 + i, 51 + 2 * i, 21.0 + i) for i in range(20)]  # the next 20 all beat the first 20 and rise with the score
    r = score_test(first + good)
    assert r["look"] == 40 and r["needed"] == 40 and r["n"] == 40
    assert r["rho"] == pytest.approx(spearman([o.score for o in first + good], [o.outlier_x for o in first + good]), abs=1e-4)
    assert r["rho"] >= 0.31 and r["label"] == "validated"
    extra = score_test(first + good + [obs(40 + i, 99 - i, 0.01) for i in range(10)])  # a 41st..50th observation changes nothing
    assert (extra["label"], extra["rho"], extra["look"], extra["n"]) == ("validated", r["rho"], 40, 50)


def test_the_final_look_fails_below_031():
    xs20 = with_rho(20, 0.1, 0.4)
    first = [obs(i, s, x) for i, (s, x) in enumerate(zip(scores(20), xs20, strict=True))]
    flat = [obs(20 + i, 50 + i, 5.0 - 0.2 * i) for i in range(20)]  # the next 20 pull the pooled correlation down
    r = score_test(first + flat)
    assert r["look"] == 40 and r["rho"] < 0.31 and r["label"] == "failed"


def test_observations_are_ordered_by_when_their_outlier_x_became_available_not_by_the_order_given():
    early = [obs(i, 40 + 2 * i, 1.0 + 0.1 * i, day=i) for i in range(20)]  # a clean rise, available days 0..19
    late = [obs(100 + i, 99 - i, 0.1, day=30 + i) for i in range(20)]  # contradicting, available days 30..49
    shuffled = late + early
    r = score_test(shuffled)
    assert (r["label"], r["look"], r["n"]) == ("validated", 20, 40) and r["rho"] == pytest.approx(1.0)
    same_time = [ScoreObservation(clip_id=f"z{i}", available_at=T0, score=40 + i, outlier_x=1.0 + i) for i in range(20)]
    assert score_test(same_time) == score_test(list(reversed(same_time)))  # ties on the time break on the clip id: stable


def test_a_narrow_score_range_is_uninformative_with_the_advice_to_raise_the_exploration_picks():
    narrow = [obs(i, 60 + (i % 5), 5.0 - 0.1 * i) for i in range(20)]  # a falling outlier_x would have failed a wide range
    r = score_test(narrow)
    assert (r["label"], r["look"]) == ("uninformative", 20) and "raise the exploration picks" in r["note"]
    # still uninformative at 40 when the range stays narrow; a wide range by then is judged on its rho
    r40 = score_test(narrow + [obs(20 + i, 60 + (i % 5), 0.5) for i in range(20)])
    assert (r40["label"], r40["look"]) == ("uninformative", 40)
    wide = score_test(narrow + [obs(20 + i, 10 + 4 * i, 0.5 + 0.2 * i) for i in range(20)])
    assert wide["look"] == 40 and wide["label"] in ("validated", "failed")


def test_it_reports_rho_of_potential_and_of_swap_apart_without_deciding_on_them():
    xs = [0.5 + 0.1 * i for i in range(20)]
    rows = [obs(i, s, x, potential=p, swap=w) for i, (s, x, p, w) in enumerate(zip(scores(20), xs, range(20), range(19, -1, -1), strict=True))]
    r = score_test(rows)
    assert r["rho_potential"] == pytest.approx(1.0) and r["rho_swap"] == pytest.approx(-1.0)
    assert r["label"] == "validated"  # decided by the total score alone
    partial = [obs(i, s, x, potential=(i if i % 2 else None)) for i, (s, x) in enumerate(zip(scores(20), xs, strict=True))]
    assert score_test(partial)["rho_potential"] == pytest.approx(1.0) and score_test(partial)["rho_swap"] is None  # nothing to correlate


def test_the_median_outlier_x_per_bucket_of_20_points():
    rows = [
        obs(0, 5, 1.0), obs(1, 15, 3.0), obs(2, 19, 2.0),  # 0-19: median 2.0
        obs(3, 20, 4.0), obs(4, 39, 6.0),  # 20-39: median 5.0
        obs(5, 60, 0.5), obs(6, 79, 1.5), obs(7, 70, 1.0),  # 60-79: median 1.0
        obs(8, 100, 9.0), obs(9, 80, 7.0),  # 80-100: median 8.0 (100 is in the top bucket)
    ] + [obs(10 + i, 40 + i, 2.0) for i in range(10)]  # 40-59
    r = score_test(rows)
    by = {b["range"]: b for b in r["buckets"]}
    assert set(by) == {"0-19", "20-39", "40-59", "60-79", "80-100"}
    assert (by["0-19"]["n"], by["0-19"]["median_outlier_x"]) == (3, 2.0)
    assert (by["20-39"]["n"], by["20-39"]["median_outlier_x"]) == (2, 5.0)
    assert (by["60-79"]["n"], by["60-79"]["median_outlier_x"]) == (3, 1.0)
    assert (by["80-100"]["n"], by["80-100"]["median_outlier_x"]) == (2, 8.0)
    assert by["40-59"]["n"] == 10


def test_an_empty_bucket_is_left_out_not_shown_as_zero():
    r = score_test(rising(20))
    assert all(b["n"] > 0 and b["median_outlier_x"] is not None for b in r["buckets"])
    assert len(r["buckets"]) < 5  # the scores 30..87 never reach 0-19 or 88+... only the buckets with clips are listed


def test_the_result_is_plain_json():
    json.dumps(score_test(rising(25)))
    json.dumps(score_test([]))


# ---- a small studio to test against ---------------------------------------------------------------------------------------------------


class World:
    """Franz, Reginald and Lenny (live), each with an Instagram account; Reginald has a TikTok one too. ``post`` files a posted clip with
    its post and readings at 72 h and 7 d, ``baseline`` the earlier posts an ``outlier_x`` is measured against."""

    def __init__(self, live: tuple[str, ...] = ("franz", "reginald", "lenny")) -> None:
        self.store = MemoryStore()
        for slug in live:
            self.store.add_character(Character(slug=slug, name={"lenny": "Lenny Gold"}.get(slug, slug.title()), status="live", bodies=[Body.biped]))
            self.store.add_account(Account(character_slug=slug, platform="instagram", handle=f"{slug}.ig"))
        if "reginald" in live:
            self.store.add_account(Account(character_slug="reginald", platform="tiktok", handle="reginald.tt"))
        self.n = 0

    def account(self, slug: str, platform: str = "instagram") -> Account:
        return next(a for a in self.store.accounts(slug) if a.platform.value == platform)

    def post(
        self, slug: str, at: datetime, *, v7: int | None = None, v72: int | None = None, features: dict[str, Any] | None = None,
        platform: str = "instagram", hook: str | None = None, snaps: Sequence[dict[str, Any]] = (), created: datetime | None = None,
    ) -> Clip:
        self.n += 1
        clip = self.store.add_clip(
            Clip(character_slug=slug, mode="dropin", state="posted", hook=hook, features=dict(features or {}), created_at=created or at - 2 * D)
        )
        post = self.store.add_post(
            Post(clip_id=clip.id, account_id=self.account(slug, platform).id, scheduled_for=at, claimed_at=at, status="posted", platform_post_id=f"pz-{self.n}")
        )
        if v72 is not None:
            self.store.add_snapshot(Snapshot(post_id=post.id, captured_at=at + 73 * H, views=v72))
        if v7 is not None:
            self.store.add_snapshot(Snapshot(post_id=post.id, captured_at=at + 7 * D + H, views=v7))
        for extra in snaps:
            extra = dict(extra)
            when = extra.pop("at", at + 8 * D)
            self.store.add_snapshot(Snapshot(post_id=post.id, captured_at=when, **extra))
        return clip

    def baseline(self, slug: str, start: datetime, n: int = 3, v7: int = 100, **kw: Any) -> list[Clip]:
        """``n`` earlier posts of 7-day ``v7`` views, one a day from ``start``: the median every later post is read against."""
        return [self.post(slug, start + i * D, v7=v7, **kw) for i in range(n)]


def drop_features(score: int | None, **extra: Any) -> dict[str, Any]:
    return {"drop": True, "score_total": score, "score_potential": None if score is None else score // 10, "score_swap": None if score is None else 5, **extra}


# ---- the observations from the store ---------------------------------------------------------------------------------------------------


def test_observations_are_the_posted_drops_with_a_score_and_an_instagram_outlier_x():
    w = World()
    w.baseline("franz", T0)  # three posts of 100 views at 7 days (no score: not observations)
    start = T0 + 3 * D
    good = w.post("franz", start, v7=300, features=drop_features(70))  # outlier_x 3.0
    w.post("franz", start + D, v7=150, features=drop_features(None))  # a drop with no score: left out
    w.post("franz", start + 2 * D, v7=150, features={"score_total": 80})  # not a drop: left out
    w.post("franz", start + 3 * D, v7=None, features=drop_features(60))  # no 7-day figure yet: left out
    w.post("franz", start + 4 * D, v7=400, features=drop_features(50))
    rows = weekly.score_observations(w.store)
    ids = {o.clip_id for o in rows}
    assert good.id in ids and len(rows) == 2
    one = next(o for o in rows if o.clip_id == good.id)
    assert (one.score, one.potential, one.swap) == (70, 7, 5)
    assert one.outlier_x == pytest.approx(3.0)
    assert one.available_at == start + 7 * D  # the post's time + 7 days


def test_only_instagram_counts_and_a_clip_posted_on_both_takes_its_instagram_figure():
    w = World()
    w.baseline("reginald", T0)
    w.baseline("reginald", T0, platform="tiktok")
    start = T0 + 3 * D
    clip = w.post("reginald", start, v7=200, features=drop_features(60))  # instagram: 2.0
    tt = w.store.add_post(Post(clip_id=clip.id, account_id=w.account("reginald", "tiktok").id, scheduled_for=start, claimed_at=start, status="posted"))
    w.store.add_snapshot(Snapshot(post_id=tt.id, captured_at=start + 8 * D, views=900))  # tiktok: 9.0, must not be used
    tt_only = w.post("reginald", start + D, v7=900, platform="tiktok", features=drop_features(55))  # a TikTok-only clip: not an observation
    rows = weekly.score_observations(w.store)
    assert [o.clip_id for o in rows] == [clip.id] and rows[0].outlier_x == pytest.approx(2.0)
    assert tt_only.id not in {o.clip_id for o in rows}


def test_each_clip_is_one_observation_and_a_version_for_another_character_counts_separately():
    w = World()
    for slug in ("franz", "lenny"):
        w.baseline(slug, T0)
    a = w.post("franz", T0 + 3 * D, v7=200, features=drop_features(60))
    b = w.post("lenny", T0 + 3 * D, v7=100, features=drop_features(60, version_index=2))
    assert {o.clip_id for o in weekly.score_observations(w.store)} == {a.id, b.id}


def test_the_cli_score_test_is_read_only_and_prints_the_test(monkeypatch):
    w = World()
    w.baseline("franz", T0)
    for i in range(3):
        w.post("franz", T0 + (3 + i) * D, v7=100 + 50 * i, features=drop_features(40 + 10 * i))
    monkeypatch.setattr(weekly, "open_store", lambda: w.store)
    before = (len(w.store.list_clips()), len(w.store.list_posts()), len(w.store.list_runs()), len(w.store.list_reviews()))
    r = CliRunner().invoke(app, ["learn", "score-test"])
    assert r.exit_code == 0, r.output
    out = json.loads(r.stdout)
    assert (out["label"], out["n"], out["needed"], out["look"]) == ("unproven", 3, 20, None) and "3 of 20" in out["note"]
    assert before == (len(w.store.list_clips()), len(w.store.list_posts()), len(w.store.list_runs()), len(w.store.list_reviews()))


# ---- the mechanism floors (plan 3.8) ---------------------------------------------------------------------------------------------------

TODAY = date(2026, 10, 19)  # the Monday after the baseline weeks
SENDS = "sends_per_1k"


def readings(**per_metric: dict[str, list[float]]) -> dict[str, dict[str, list[float]]]:
    return per_metric


def test_the_floor_is_the_median_of_the_characters_own_readings_with_4_or_more():
    r = readings(sends_per_1k={"franz": [1.0, 2.0, 3.0, 10.0], "lenny": [5.0, 6.0, 7.0]})  # 7 readings studio-wide
    f = weekly.compute_floors(r, ["franz", "lenny"], today=TODAY)
    assert f["studio"][SENDS]["status"] == "fixed" and f["studio"][SENDS]["value"] == statistics.median([1.0, 2.0, 3.0, 10.0, 5.0, 6.0, 7.0])
    assert f["studio"][SENDS]["n"] == 7
    own = f["characters"]["franz"][SENDS]
    assert (own["status"], own["value"], own["basis"], own["n"]) == ("fixed", 2.5, "character", 4)  # median of his four
    assert f["fixed_on"][SENDS] == "2026-10-19"


def test_fewer_than_4_of_his_own_readings_take_the_studio_wide_median():
    r = readings(sends_per_1k={"franz": [1.0, 2.0, 3.0, 10.0], "lenny": [5.0, 6.0, 7.0]})
    f = weekly.compute_floors(r, ["franz", "lenny"], today=TODAY)
    lenny = f["characters"]["lenny"][SENDS]
    assert (lenny["status"], lenny["basis"], lenny["n"]) == ("fixed", "studio", 3)
    assert lenny["value"] == f["studio"][SENDS]["value"] == 5.0


def test_a_character_with_no_reading_at_all_uses_the_studio_median():
    r = readings(sends_per_1k={"franz": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]})
    f = weekly.compute_floors(r, ["franz", "reginald"], today=TODAY)
    assert f["characters"]["reginald"][SENDS]["basis"] == "studio" and f["characters"]["reginald"][SENDS]["n"] == 0
    assert f["characters"]["reginald"][SENDS]["value"] == 3.5


def test_exactly_6_readings_studio_wide_fix_it_and_5_do_not():
    six = weekly.compute_floors(readings(sends_per_1k={"a": [1.0] * 3, "b": [2.0] * 3}), ["a", "b"], today=TODAY)
    five = weekly.compute_floors(readings(sends_per_1k={"a": [1.0] * 3, "b": [2.0] * 2}), ["a", "b"], today=TODAY)
    assert six["studio"][SENDS]["status"] == "fixed"
    st = five["studio"][SENDS]
    assert st["status"] == "pending" and st["n"] == 5 and st["needed"] == 6 and "5 of 6" in st["reason"]
    assert five["fixed_on"][SENDS] is None
    # nobody gets a number from an unfixed studio: not even a character with 4 readings of his own
    five4 = weekly.compute_floors(readings(sends_per_1k={"a": [1.0] * 4, "b": [2.0]}), ["a", "b"], today=TODAY)
    assert five4["characters"]["a"][SENDS]["status"] == "pending" and "value" not in five4["characters"]["a"][SENDS]


def test_a_metric_with_no_reading_anywhere_is_pending_because_there_is_no_data_in_the_cloud_yet():
    f = weekly.compute_floors(readings(), ["franz"], today=TODAY)
    for metric, _ in weekly.FLOOR_METRICS:
        assert f["studio"][metric]["status"] == "pending" and f["studio"][metric]["n"] == 0
        assert f["studio"][metric]["reason"] == "no data in the cloud yet"
        assert f["characters"]["franz"][metric]["status"] == "pending" and f["fixed_on"][metric] is None


def test_the_skip_rate_is_a_ceiling_and_the_others_floors():
    f = weekly.compute_floors(readings(skip_rate={"a": [40.0] * 6}), ["a"], today=TODAY)
    assert f["studio"]["skip_rate"]["kind"] == "ceiling" and f["studio"][SENDS]["kind"] == "floor"
    assert [m for m, _ in weekly.FLOOR_METRICS] == ["sends_per_1k", "follows_per_1k", "watched_pct", "skip_rate"]


def test_a_fixed_floor_is_never_recomputed_and_a_pending_one_is_filled_when_the_6th_reading_arrives():
    first = weekly.compute_floors(
        readings(sends_per_1k={"a": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]}, watched_pct={"a": [50.0, 60.0]}), ["a"], today=TODAY,
    )
    assert first["studio"][SENDS]["status"] == "fixed" and first["studio"]["watched_pct"]["status"] == "pending"
    later = weekly.compute_floors(
        readings(sends_per_1k={"a": [100.0] * 6}, watched_pct={"a": [50.0, 60.0, 70.0, 80.0, 90.0, 100.0]}),
        ["a"], today=date(2026, 10, 26), previous=first,
    )
    assert later["studio"][SENDS] == first["studio"][SENDS] and later["characters"]["a"][SENDS] == first["characters"]["a"][SENDS]
    assert later["fixed_on"][SENDS] == "2026-10-19"  # the day it was fixed stays
    w = later["studio"]["watched_pct"]
    assert (w["status"], w["value"], w["n"]) == ("fixed", 75.0, 6) and later["fixed_on"]["watched_pct"] == "2026-10-26"  # the date is written down
    assert later["characters"]["a"]["watched_pct"]["value"] == 75.0


def test_a_character_who_joins_later_gets_the_fixed_studio_value_not_a_new_median():
    first = weekly.compute_floors(readings(sends_per_1k={"a": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]}), ["a"], today=TODAY)
    later = weekly.compute_floors(
        readings(sends_per_1k={"a": [99.0] * 6, "b": [8.0, 9.0]}), ["a", "b"], today=date(2026, 10, 26), previous=first,
    )
    assert later["characters"]["b"][SENDS]["value"] == first["studio"][SENDS]["value"] == 3.5 and later["characters"]["b"][SENDS]["basis"] == "studio"


def test_a_pending_character_floor_is_fixed_with_his_own_median_once_he_has_4_readings():
    first = weekly.compute_floors(readings(sends_per_1k={"a": [1.0] * 6}), ["a"], today=TODAY)
    assert first["characters"]["a"][SENDS]["status"] == "fixed"
    # a character who was added with the studio fixed but no data of his own, then gets a 4th reading: still the fixed studio value
    again = weekly.compute_floors(
        readings(sends_per_1k={"a": [1.0] * 6, "b": [9.0] * 4}), ["a", "b"], today=date(2026, 10, 26), previous=first,
    )
    assert again["characters"]["b"][SENDS]["basis"] == "character" and again["characters"]["b"][SENDS]["value"] == 9.0


def test_floors_are_due_for_a_week_that_ends_on_or_after_sunday_18_october():
    assert weekly.floors_due(date(2026, 10, 12)) is True  # the week of 12 Oct ends Sun 18 Oct
    assert weekly.floors_due(date(2026, 10, 5)) is False  # ends Sun 11 Oct
    assert weekly.floors_due(date(2026, 10, 19)) is True


def test_the_floors_result_is_plain_json():
    json.dumps(weekly.compute_floors(readings(sends_per_1k={"a": [1.0] * 6}), ["a"], today=TODAY))


# ---- a post's readings and the readings of the baseline weeks --------------------------------------------------------------------------


def snap(at: datetime, **kw: Any) -> dict[str, Any]:
    return {"at": at, **kw}


def test_a_posts_values_come_from_its_latest_snapshot_that_has_them():
    at = T0
    snaps = [
        Snapshot(post_id="p", captured_at=at + 1 * D, views=1000, shares=5, follows=1, watched_pct=40.0, skip_rate=50.0),
        Snapshot(post_id="p", captured_at=at + 3 * D, views=4000, shares=40, follows=8, watched_pct=None, skip_rate=None),
        Snapshot(post_id="p", captured_at=at + 8 * D, views=5000, shares=None, follows=None),
    ]
    v = weekly.post_metric_values(snaps)
    assert v["sends_per_1k"] == pytest.approx(10.0)  # 40 / 4000 x 1000: the latest snapshot with views and shares
    assert v["follows_per_1k"] == pytest.approx(2.0)
    assert v["watched_pct"] == 40.0 and v["skip_rate"] == 50.0  # the latest that reported them
    assert weekly.post_metric_values([]) == {}
    assert weekly.post_metric_values([Snapshot(post_id="p", captured_at=at, views=0, shares=0)]) == {}  # no views: no rate, and 0 shares is a reading only with views
    assert "sends_per_1k" not in weekly.post_metric_values([Snapshot(post_id="p", captured_at=at, views=None, shares=3)])


def test_the_baseline_readings_are_the_instagram_posts_of_5_to_18_october_london():
    w = World()
    inside = [datetime(2026, 10, 5, 0, 30, tzinfo=LONDON), datetime(2026, 10, 18, 23, 30, tzinfo=LONDON)]
    outside = [datetime(2026, 10, 4, 23, 30, tzinfo=LONDON), datetime(2026, 10, 19, 0, 30, tzinfo=LONDON)]
    for i, at in enumerate(inside + outside):
        w.post("franz", at, snaps=[{"views": 1000, "shares": 10 * (i + 1)}])
    w.post("reginald", inside[0], platform="tiktok", snaps=[{"views": 1000, "shares": 99}])  # TikTok: not a baseline reading
    got = weekly.floor_readings(w.store)
    assert sorted(got["sends_per_1k"]["franz"]) == [10.0, 20.0] and "reginald" not in got["sends_per_1k"]
    assert got.get("skip_rate", {}) == {}


def test_a_post_just_before_midnight_london_is_that_londons_day_not_utcs():
    w = World()
    late = datetime(2026, 10, 18, 23, 59, tzinfo=LONDON)  # BST: 22:59 UTC, still the 18th either way
    early = datetime(2026, 10, 19, 0, 30, tzinfo=LONDON)  # BST: 23:30 UTC on the 18th, but London's 19th
    w.post("franz", late, snaps=[{"views": 1000, "shares": 10}])
    w.post("franz", early, snaps=[{"views": 1000, "shares": 50}])
    assert weekly.floor_readings(w.store)["sends_per_1k"]["franz"] == [10.0]


def test_a_post_below_two_floors_is_flagged_with_what_failed():
    floors = {
        "sends_per_1k": {"status": "fixed", "kind": "floor", "value": 5.0},
        "follows_per_1k": {"status": "fixed", "kind": "floor", "value": 2.0},
        "watched_pct": {"status": "fixed", "kind": "floor", "value": 40.0},
        "skip_rate": {"status": "fixed", "kind": "ceiling", "value": 45.0},
    }
    ok = {"sends_per_1k": 5.0, "follows_per_1k": 2.0, "watched_pct": 40.0, "skip_rate": 45.0}  # exactly on every line: nothing failed
    assert weekly.floor_failures(ok, floors) == []
    assert weekly.floor_failures({**ok, "skip_rate": 45.1}, floors) == ["hook"]  # above the ceiling
    assert weekly.floor_failures({**ok, "watched_pct": 39.9}, floors) == ["hold"]
    assert weekly.floor_failures({**ok, "sends_per_1k": 4.9}, floors) == ["sends"]
    assert weekly.floor_failures({**ok, "follows_per_1k": 1.9}, floors) == ["follows"]
    assert weekly.floor_failures({"sends_per_1k": 1.0, "follows_per_1k": 0.0, "watched_pct": 10.0, "skip_rate": 80.0}, floors) == ["hook", "hold", "sends", "follows"]
    assert weekly.flagged(["hook"]) is False and weekly.flagged(["hook", "sends"]) is True  # two floors flag a post, one does not


def test_a_pending_floor_or_a_missing_reading_never_counts_as_failed():
    floors = {"sends_per_1k": {"status": "pending", "kind": "floor"}, "skip_rate": {"status": "fixed", "kind": "ceiling", "value": 40.0}}
    assert weekly.floor_failures({"sends_per_1k": 0.0, "skip_rate": 90.0}, floors) == ["hook"]  # sends has no floor yet
    assert weekly.floor_failures({}, floors) == []  # nothing read: nothing failed
    assert weekly.floor_failures({"watched_pct": 1.0}, floors) == []  # no floor for it at all
