"""The weekly review in the cloud (learning plan 4.2, 4.3, 6.1, build items 10-11): the score test (test A), the mechanism floors,
the rule candidates and arm proposals, the playbooks, the digest and ``studio review weekly``.

Every rule is a pure function with its threshold tested at the exact boundary (the plan's sections 3 and 4.3 are frozen); the whole
run is tested on ``MemoryStore``. Nothing here touches the network or a database.
"""

from __future__ import annotations

import json
import random
import statistics
from datetime import date, datetime, timedelta, timezone
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


# ---- test A: a look, once taken, is frozen (fix round 1, I1) ---------------------------------------------------------------------------


def near_threshold() -> list[ScoreObservation]:
    """20 observations whose interim rho is 0.4677: validated, but close enough to the line that one late arrival would flip it."""
    xs = with_rho(20, 0.46, 0.50)
    return [obs(i, s, x) for i, (s, x) in enumerate(zip(scores(20), xs, strict=True))]


def early_arrival() -> ScoreObservation:
    """A post whose 7-day figure arrives late (a failed pull) but sorts EARLIER than all of the first 20: it displaces the 20th."""
    return obs(99, 95, 0.01, day=-1)


def test_without_the_stored_look_a_late_arrival_that_sorts_earlier_would_flip_the_interim():
    # the defect this round fixes, pinned so the next tests mean something: the sample is rebuilt from the data
    rows = near_threshold()
    assert score_test(rows)["label"] == "validated"
    assert score_test(rows + [early_arrival()])["label"] != "validated"


def test_a_decided_interim_look_is_stored_and_never_recomputed():
    rows = near_threshold()
    first = score_test(rows)
    assert set(first["decided"]) == {"20"} and first["decided"]["20"]["clip_ids"] == [o.clip_id for o in rows]
    again = score_test(rows + [early_arrival()], decided=first["decided"])
    assert (again["label"], again["look"], again["rho"], again["buckets"], again["note"]) == (first["label"], 20, first["rho"], first["buckets"], first["note"])
    assert again["n"] == 21 and again["decided"] == first["decided"]


def test_a_failed_interim_stays_failed_when_a_late_arrival_sorts_earlier():
    rows = falling(20)
    first = score_test(rows)
    assert first["label"] == "failed"
    better = obs(99, 20, 9.0, day=-1)  # an early one that would pull the first 20 up
    assert score_test(rows + [better], decided=first["decided"])["rho"] == first["rho"]


def test_an_unproven_interim_is_frozen_too_and_the_final_look_is_taken_once_at_40():
    xs20 = with_rho(20, 0.1, 0.4)
    first20 = [obs(i, s, x) for i, (s, x) in enumerate(zip(scores(20), xs20, strict=True))]
    interim = score_test(first20)
    assert interim["label"] == "unproven" and set(interim["decided"]) == {"20"}
    more = first20 + [obs(20 + i, 40 + 2 * i, 3.0 + i) for i in range(20)]
    # an earlier arrival (sorts before everything) must not change the look at 20 that was taken
    sample = more + [obs(98, 95, 0.01, day=-1)]
    at40 = score_test(sample, decided=interim["decided"])
    assert at40["decided"]["20"] == interim["decided"]["20"] and at40["look"] == 40 and at40["n"] == 41
    assert at40["decided"]["40"]["clip_ids"] == [o.clip_id for o in sorted(sample, key=lambda o: (o.available_at, o.clip_id))[:40]]
    # the final look, once taken, is frozen as well
    later = score_test(sample + [obs(97, 99, 0.001, day=-2)], decided=at40["decided"])
    assert (later["label"], later["look"], later["rho"], later["n"]) == (at40["label"], 40, at40["rho"], 42)


def test_a_decided_interim_never_takes_a_final_look():
    rows = near_threshold()
    first = score_test(rows)
    big = rows + [obs(20 + i, 50 + i, 0.001) for i in range(25)]
    out = score_test(big, decided=first["decided"])
    assert (out["label"], out["look"], out["needed"]) == ("validated", 20, 20) and set(out["decided"]) == {"20"}


def test_a_stored_look_that_is_damaged_is_ignored_not_trusted():
    rows = near_threshold()
    for bad in ({"20": {"look": 20, "label": "maybe", "rho": 0.9, "span": 40.0}}, {"20": "validated"}, {"20": {"look": 40, "label": "validated", "rho": 0.9, "span": 40.0}}, {"20": {"look": 20, "label": "failed", "rho": "x", "span": 40.0}}):
        out = score_test(rows, decided=bad)
        assert out["rho"] == score_test(rows)["rho"] and out["decided"]["20"]["clip_ids"] == [o.clip_id for o in rows]


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
    assert f["fixed_on"][SENDS] == "2026-10-18"  # the first fix records the end of weeks 1-2, not the day the run happened


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
    assert later["fixed_on"][SENDS] == "2026-10-18"  # the day it was fixed stays
    w = later["studio"]["watched_pct"]
    assert (w["status"], w["value"], w["n"]) == ("fixed", 75.0, 6) and later["fixed_on"]["watched_pct"] == "2026-10-26"  # no times given: the run's day
    assert later["characters"]["a"]["watched_pct"]["value"] == 75.0


def arrivals_at(*moments: datetime) -> dict[str, list[datetime]]:
    return {"watched_pct": list(moments)}


def test_a_later_fix_records_the_london_day_the_6th_reading_arrived_not_the_day_of_the_run():
    first = weekly.compute_floors(readings(sends_per_1k={"a": [1.0] * 6}, watched_pct={"a": [50.0, 60.0]}), ["a"], today=TODAY)
    values = readings(sends_per_1k={"a": [1.0] * 6}, watched_pct={"a": [50.0, 60.0, 70.0, 80.0, 90.0, 100.0, 40.0]})
    moments = [datetime(2026, 10, d, 12, 0, tzinfo=timezone.utc) for d in (20, 20, 21, 21, 22, 22)] + [datetime(2026, 10, 25, 12, 0, tzinfo=timezone.utc)]
    later = weekly.compute_floors(values, ["a"], today=date(2026, 10, 26), previous=first, arrivals=arrivals_at(*reversed(moments)))
    # the 6th earliest arrival is 22 Oct 12:00; the 7th (25 Oct) and the run (26 Oct) do not matter
    assert later["fixed_on"]["watched_pct"] == "2026-10-22" and later["studio"]["watched_pct"]["fixed_on"] == "2026-10-22"
    assert later["fixed_on"][SENDS] == "2026-10-18"


def test_the_day_of_the_6th_reading_is_a_london_day_not_a_utc_one():
    first = weekly.compute_floors(readings(), ["a"], today=TODAY)
    values = readings(watched_pct={"a": [50.0] * 6})
    late = [datetime(2026, 10, 20, h, 0, tzinfo=timezone.utc) for h in (1, 2, 3, 4, 5)] + [datetime(2026, 10, 22, 23, 30, tzinfo=timezone.utc)]  # BST: 00:30 on the 23rd
    later = weekly.compute_floors(values, ["a"], today=date(2026, 10, 26), previous=first, arrivals=arrivals_at(*late))
    assert later["fixed_on"]["watched_pct"] == "2026-10-23"


def test_the_first_fix_is_the_end_of_weeks_1_and_2_however_late_the_first_run_is():
    values = readings(sends_per_1k={"a": [1.0] * 6})
    first = weekly.compute_floors(values, ["a"], today=date(2026, 11, 2), arrivals={"sends_per_1k": [datetime(2026, 10, 30, tzinfo=timezone.utc)] * 6})
    assert first["fixed_on"][SENDS] == "2026-10-18"


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


# ---- lifts against the others (plan 4.3) ----------------------------------------------------------------------------------------------


def mc(i: int, x: float | None, slug: str = "franz", **features: Any) -> Clip:
    """A posted clip ``k<i>`` with an ``outlier_x`` (unless ``x`` is None) and the given tags."""
    feats = dict(features)
    if x is not None:
        feats["outlier_x"] = x
    return Clip(id=f"k{i}", character_slug=slug, mode="dropin", state="posted", features=feats, created_at=T0 + i * D)


def two_sides(xs_with: list[float], xs_without: list[float], feature: str = "setting", value: str = "kitchen", other: str = "garden") -> list[Clip]:
    return [mc(i, x, **{feature: value}) for i, x in enumerate(xs_with)] + [mc(100 + i, x, **{feature: other}) for i, x in enumerate(xs_without)]


def find(lifts: list[weekly.SideLift], feature: str, value: Any) -> weekly.SideLift:
    return next(lf for lf in lifts if lf.feature == feature and lf.value == value)


def test_the_lift_is_the_followers_median_against_the_others_median_not_against_everybody():
    clips = two_sides([2.0] * 5, [1.0] * 5)
    kitchen = find(weekly.side_lifts(clips), "setting", "kitchen")
    assert (kitchen.n, kitchen.n_others, kitchen.median, kitchen.median_others) == (5, 5, 2.0, 1.0)
    assert kitchen.lift == pytest.approx(2.0)  # 4.3: at least 1.5x the OTHERS' median (review.Lift divides by the median of all ten: 1.33)
    assert kitchen.hits == 0 and len(kitchen.clip_ids) == 5 and set(kitchen.clip_ids) == {f"k{i}" for i in range(5)}
    garden = find(weekly.side_lifts(clips), "setting", "garden")
    assert garden.lift == pytest.approx(0.5)


def test_hits_are_the_followers_with_outlier_x_3_or_more():
    kitchen = find(weekly.side_lifts(two_sides([3.0, 2.99, 5.0, 1.0, 1.0], [1.0] * 5)), "setting", "kitchen")
    assert kitchen.hits == 2


def test_clips_without_an_outlier_x_or_without_the_tag_are_not_on_either_side():
    clips = two_sides([2.0] * 5, [1.0] * 5) + [mc(200 + i, None, setting="kitchen") for i in range(3)] + [mc(300 + i, 9.0) for i in range(3)]
    kitchen = find(weekly.side_lifts(clips), "setting", "kitchen")
    assert (kitchen.n, kitchen.n_others, kitchen.median_others) == (5, 5, 1.0)  # the unmeasured ones and the untagged ones count nowhere


def test_a_group_under_5_is_not_listed_and_the_default_is_the_pre_registered_5():
    assert weekly.side_lifts(two_sides([2.0] * 4, [1.0] * 5)) == [] or all(lf.value != "kitchen" for lf in weekly.side_lifts(two_sides([2.0] * 4, [1.0] * 5)))
    assert any(lf.value == "kitchen" for lf in weekly.side_lifts(two_sides([2.0] * 5, [1.0] * 5)))
    assert any(lf.value == "kitchen" for lf in weekly.side_lifts(two_sides([2.0] * 2, [1.0] * 5), min_n=2))


def test_a_lift_against_a_zero_median_is_undefined_not_infinite():
    lf = find(weekly.side_lifts(two_sides([2.0] * 5, [0.0] * 5)), "setting", "kitchen")
    assert lf.median_others == 0.0 and lf.lift is None


@pytest.mark.parametrize(
    ("xs_with", "n_without", "x_without", "expected"),
    [
        ([1.5] * 5, 5, 1.0, True),  # exactly 1.5 with 5 each side
        ([1.4999] * 5, 5, 1.0, False),
        ([1.5] * 5, 4, 1.0, False),  # only 4 on the other side
        ([1.5] * 4, 5, 1.0, False),
        ([3.0] * 7, 9, 1.0, True),
    ],
)
def test_do_more_needs_a_lift_of_1_5_with_5_each_side(xs_with, n_without, x_without, expected):
    lifts = weekly.side_lifts(two_sides(xs_with, [x_without] * n_without), min_n=1)
    pick = weekly.do_more([lf for lf in lifts if lf.value == "kitchen"])
    assert (pick is not None) is expected


@pytest.mark.parametrize(
    ("n_with", "x_with", "n_without", "expected"),
    [
        (8, 0.7, 8, True),  # exactly 0.7 with 8 each side
        (8, 0.7001, 8, False),
        (7, 0.7, 8, False),
        (8, 0.7, 7, False),
        (9, 0.3, 12, True),
    ],
)
def test_stop_needs_a_lift_of_0_7_or_less_with_8_each_side(n_with, x_with, n_without, expected):
    lifts = weekly.side_lifts(two_sides([x_with] * n_with, [1.0] * n_without), min_n=1)
    pick = weekly.stop([lf for lf in lifts if lf.value == "kitchen"])
    assert (pick is not None) is expected


def test_do_more_and_stop_pick_the_strongest_and_the_weakest():
    clips = (
        [mc(i, 4.0, setting="kitchen") for i in range(8)] + [mc(10 + i, 2.0, setting="garden") for i in range(8)]
        + [mc(20 + i, 0.5, setting="roof") for i in range(8)] + [mc(30 + i, 1.0, prop="ball") for i in range(8)] + [mc(40 + i, 1.0, prop="box") for i in range(8)]
    )
    lifts = weekly.side_lifts(clips)
    best, worst = weekly.do_more(lifts), weekly.stop(lifts)
    assert best is not None and (best.feature, best.value) == ("setting", "kitchen")
    assert worst is not None and (worst.feature, worst.value) == ("setting", "roof")
    assert weekly.do_more([]) is None and weekly.stop([]) is None


# ---- rule candidates and the second look (plan 4.3) ------------------------------------------------------------------------------------


def candidates_of(clips: list[Clip]) -> list[weekly.SideLift]:
    return weekly.rule_candidates(weekly.side_lifts(clips, min_n=1))


def test_a_rule_candidate_needs_5_each_side_a_lift_of_1_5_and_a_hit():
    ok = two_sides([3.0, 3.0, 3.0, 3.0, 3.0], [1.0] * 5)
    assert [(c.feature, c.value) for c in candidates_of(ok)] == [("setting", "kitchen")]
    assert candidates_of(two_sides([1.5] * 5, [1.0] * 5)) == []  # a lift of 1.5 but no hit among the followers
    assert candidates_of(two_sides([2.9, 3.0, 2.0, 2.0, 2.0], [1.0] * 5)) != []  # one hit is enough
    assert candidates_of(two_sides([4.0, 3.0, 3.0, 3.0, 3.0], [2.0] * 5))  # lift 1.5 exactly (3.0 / 2.0), with hits
    assert candidates_of(two_sides([4.0, 3.5, 2.99, 2.99, 2.99], [2.0] * 5)) == []  # median 2.99: lift 1.495
    assert candidates_of(two_sides([3.0] * 5, [1.0] * 4)) == []  # only 4 on the other side
    assert candidates_of(two_sides([3.0] * 4, [1.0] * 5)) == []  # only 4 followers


def test_tags_that_are_not_content_are_never_rule_candidates():
    clips = [mc(i, 5.0, hook_by="bandit") for i in range(5)] + [mc(10 + i, 1.0, hook_by="studio") for i in range(5)]
    assert candidates_of(clips) == []  # who chose the hook is a test, not a rule about clips
    clips = [mc(i, 5.0, explore_pick=True) for i in range(5)] + [mc(10 + i, 1.0, explore_pick=False) for i in range(5)]
    assert candidates_of(clips) == []


@pytest.mark.parametrize(
    ("feature", "value", "other"),
    [
        ("score_bucket", "80_up", "40_59"), ("score_total", 85, 40), ("score_potential", 9, 3), ("score_swap", 9, 2),
        ("test_arms", {"C": "a"}, {"C": "b"}), ("family_id", "fam-1", "fam-2"), ("trial_reel", True, False),
        ("first_comment_posted", True, False), ("series", "s1", "s2"), ("episode", 3, 1), ("zoom_pulses", 2, 0), ("hook_entrance", "slam", "fade"),
    ],
)
def test_tags_about_the_score_the_tests_or_how_a_clip_was_filed_are_no_advice(feature, value, other):
    # a lift on the score is advice from the score before test A has looked, and a hit rule about the score is circular
    clips = [mc(i, 5.0, **{feature: value}) for i in range(10)] + [mc(100 + i, 1.0, **{feature: other}) for i in range(10)]
    lifts = weekly.side_lifts(clips)
    assert candidates_of(clips) == [] and weekly.do_more(lifts) is None and weekly.stop(lifts) is None
    assert weekly.stop(weekly.side_lifts([mc(i, 0.5, **{feature: value}) for i in range(10)] + [mc(100 + i, 5.0, **{feature: other}) for i in range(10)])) is None
    rules, watching = weekly.playbook_items(clips)
    assert not any(feature in r["title"] for r in rules) and not any(feature in w for w in watching)


def lifts_all(clips: list[Clip]) -> list[weekly.SideLift]:
    return weekly.side_lifts(clips, min_n=1)


WEEK1, WEEK2 = date(2026, 10, 19), date(2026, 10, 26)


def test_a_new_candidate_is_stored_and_not_yet_a_proposal():
    clips = two_sides([3.0] * 5, [1.0] * 5)
    stored, ready = weekly.update_candidates([], lifts_all(clips), measured=10, week=WEEK1)
    assert ready == [] and len(stored) == 1
    c = stored[0]
    assert (c["feature"], c["value"], c["status"], c["since_week"], c["measured"]) == ("setting", "kitchen", "candidate", "2026-10-19", 10)
    assert (c["n"], c["n_others"], c["median"], c["median_others"], c["lift"], c["hits"]) == (5, 5, 3.0, 1.0, 3.0, 5)
    assert c["clip_ids"] == sorted(c["clip_ids"]) and len(c["clip_ids"]) == 5
    json.dumps(stored)


def test_the_second_look_makes_it_ready_when_next_weeks_posts_still_show_1_2():
    first = weekly.update_candidates([], lifts_all(two_sides([3.0] * 5, [1.0] * 5)), measured=10, week=WEEK1)[0]
    # next week: two more kitchen posts and one garden post: still 3.0 vs 1.0
    more = two_sides([3.0] * 7, [1.0] * 6)
    stored, ready = weekly.update_candidates(first, lifts_all(more), measured=13, week=WEEK2)
    assert [r["feature"] for r in ready] == ["setting"] and ready[0]["status"] == "ready" and ready[0]["since_week"] == "2026-10-19"
    assert ready[0]["repeat"] is False and ready[0]["n"] == 7 and ready[0]["n_others"] == 6
    assert [c["status"] for c in stored] == ["ready"]


@pytest.mark.parametrize(("x_with", "expected"), [(1.2, True), (1.1999, False)])
def test_the_second_look_needs_a_lift_of_1_2_exactly_or_more(x_with, expected):
    first = weekly.update_candidates([], lifts_all(two_sides([3.0] * 5, [1.0] * 5)), measured=10, week=WEEK1)[0]
    now = two_sides([x_with] * 6, [1.0] * 6)  # the lift has fallen to x_with
    stored, ready = weekly.update_candidates(first, lifts_all(now), measured=12, week=WEEK2)
    assert bool(ready) is expected
    assert [c["status"] for c in stored] == (["ready"] if expected else [])  # below 1.2: it leaves the list


def test_without_new_posts_there_is_no_second_look():
    clips = two_sides([3.0] * 5, [1.0] * 5)
    first = weekly.update_candidates([], lifts_all(clips), measured=10, week=WEEK1)[0]
    stored, ready = weekly.update_candidates(first, lifts_all(clips), measured=10, week=WEEK2)  # the same ten posts again (a rerun)
    assert ready == [] and [c["status"] for c in stored] == ["candidate"] and stored[0]["since_week"] == "2026-10-19"


def test_a_candidate_that_lost_one_side_is_not_ready():
    first = weekly.update_candidates([], lifts_all(two_sides([3.0] * 5, [1.0] * 5)), measured=10, week=WEEK1)[0]
    stored, ready = weekly.update_candidates(first, lifts_all([mc(i, 3.0, setting="kitchen") for i in range(8)]), measured=12, week=WEEK2)
    assert ready == []  # no clip on the other side any more: nothing to compare


def test_a_ready_rule_that_is_still_ready_next_week_is_marked_a_repeat():
    first = weekly.update_candidates([], lifts_all(two_sides([3.0] * 5, [1.0] * 5)), measured=10, week=WEEK1)[0]
    clips = two_sides([3.0] * 7, [1.0] * 6)
    ready1 = weekly.update_candidates(first, lifts_all(clips), measured=13, week=WEEK2)[0]
    stored, ready = weekly.update_candidates(ready1, lifts_all(two_sides([3.0] * 8, [1.0] * 8)), measured=16, week=date(2026, 11, 2))
    assert ready[0]["repeat"] is True and ready[0]["since_week"] == "2026-10-19"


def test_a_fresh_candidate_that_meets_the_entry_conditions_is_added_beside_the_old_ones():
    first = weekly.update_candidates([], lifts_all(two_sides([3.0] * 5, [1.0] * 5)), measured=10, week=WEEK1)[0]
    clips = two_sides([3.0] * 6, [1.0] * 6) + [mc(500 + i, 4.0, prop="ball") for i in range(5)] + [mc(600 + i, 1.0, prop="box") for i in range(5)]
    stored, ready = weekly.update_candidates(first, lifts_all(clips), measured=22, week=WEEK2)
    assert {(c["feature"], c["status"]) for c in stored} == {("setting", "ready"), ("prop", "candidate")}
    assert [r["feature"] for r in ready] == ["setting"]


# ---- the hook arms: standings and the retire rule (plan 3.3) --------------------------------------------------------------------------


def arms_row(slug: str, arms: dict[str, tuple[int, int]], *, mode: str = "thompson", readings: int = 5, tallied: int | None = None) -> dict[str, Any]:
    return {
        "character": slug, "mode": mode, "readings": readings, "readings_needed": 3, "pending": 0,
        "tallied": sum(w + l for w, l in arms.values()) if tallied is None else tallied,
        "arms": [{"pattern": p, "wins": w, "losses": l, "uses": w + l} for p, (w, l) in arms.items()],
    }


def standings(rows: list[dict[str, Any]], outliers: dict[tuple[str, str], list[float]] | None = None) -> list[dict[str, Any]]:
    return weekly.arm_standings({"characters": rows}, outliers or {}, min_uses=6)


def test_standings_show_wins_losses_win_rate_and_the_median_outlier_x_of_each_arm():
    rows = [arms_row("reginald", {"false-premise": (3, 1), "understatement": (1, 3), "trend-label": (0, 0)})]
    (r,) = standings(rows, {("reginald", "false-premise"): [1.0, 2.0, 3.0], ("reginald", "understatement"): [0.5]})
    by = {a["pattern"]: a for a in r["arms"]}
    assert (by["false-premise"]["wins"], by["false-premise"]["losses"], by["false-premise"]["uses"], by["false-premise"]["win_rate"]) == (3, 1, 4, 0.75)
    assert (by["false-premise"]["median_outlier_x"], by["false-premise"]["n_outlier"]) == (2.0, 3)
    assert by["trend-label"]["win_rate"] is None and by["trend-label"]["median_outlier_x"] is None  # nothing yet: none, not 0
    assert r["leading"] == {"pattern": "false-premise", "wins": 3, "uses": 4} and r["fewest_uses"] == 0


def test_the_leading_arm_is_the_best_win_rate_then_the_most_uses_then_the_registry_order():
    r = standings([arms_row("franz", {"ego-claim": (1, 1), "when-relatable": (2, 2), "myth-bust": (0, 3)})])[0]
    assert r["leading"]["pattern"] == "when-relatable"  # 50 % with 4 uses beats 50 % with 2
    r = standings([arms_row("franz", {"ego-claim": (1, 1), "when-relatable": (1, 1)})])[0]
    assert r["leading"]["pattern"] == "ego-claim"  # a full tie: the first in the registry
    assert standings([arms_row("franz", {"ego-claim": (0, 0), "when-relatable": (0, 0)})])[0]["leading"] is None


def test_an_arm_is_proposed_for_retirement_after_10_tallied_uses_with_20_percent_wins_or_fewer_and_a_median_of_0_7_or_less():
    arms = {"ego-claim": (2, 8), "when-relatable": (5, 5), "myth-bust": (4, 4)}  # ego-claim: 10 uses, exactly 20 % wins
    low = {("franz", "ego-claim"): [0.7, 0.5, 0.9]}  # median 0.7: on the line
    (p,) = weekly.retire_proposals(standings([arms_row("franz", arms)], low))
    assert (p["kind"], p["character"], p["arm"], p["uses"], p["wins"], p["win_rate"], p["median_outlier_x"]) == ("arm_retire", "franz", "ego-claim", 10, 2, 0.2, 0.7)
    for label, row, out in (
        ("9 uses", {**arms, "ego-claim": (1, 8)}, low),
        ("21 % wins", {**arms, "ego-claim": (3, 11)}, low),  # 14 uses, 21.4 %
        ("median 0.71", arms, {("franz", "ego-claim"): [0.71]}),
        ("no median", arms, {}),
    ):
        assert weekly.retire_proposals(standings([arms_row("franz", row)], out)) == [], label


def test_an_arm_is_never_retired_when_it_would_leave_fewer_than_two():
    two = arms_row("lenny", {"mid-deal": (0, 12), "ego-claim": (5, 5)})
    assert weekly.retire_proposals(standings([two], {("lenny", "mid-deal"): [0.1]})) == []  # the registry needs two arms per character


def test_there_is_no_add_proposal_because_the_plan_gives_no_rule_for_one():
    assert not hasattr(weekly, "add_proposals")


# ---- the playbook ---------------------------------------------------------------------------------------------------------------------


def test_a_format_that_keeps_or_kills_and_a_proven_hook_become_rules_with_their_numbers():
    clips = (
        [mc(i, 2.0, format_id="swap_trend") for i in range(5)]  # keep: median 2.0 over 5
        + [mc(10 + i, 0.5, format_id="swap_classic") for i in range(8)]  # kill: median 0.5 over 8
        + [mc(20 + i, 1.0, format_id="recreate") for i in range(3)]  # fewer than 5: watching
    )
    rules, watching = weekly.playbook_items(clips)
    titles = [r["title"] for r in rules]
    assert "Keep format `swap_trend`" in titles and "Stop format `swap_classic`" in titles
    keep = next(r for r in rules if r["title"] == "Keep format `swap_trend`")
    assert "median outlier_x 2.00 over 5 posts" in keep["detail"]
    assert any("recreate" in w and "3 " in w for w in watching)
    assert all("recreate" not in t for t in titles)


def test_a_proven_hook_needs_5_measured_uses_before_it_is_a_rule():
    few = [mc(i, 4.0, hook_pattern="understatement") for i in range(4)]  # 4 hits in 4 uses: proven by the bar, but only 4 posts behind it
    rules, watching = weekly.playbook_items(few)
    assert rules == [] and any("understatement" in w for w in watching)
    five = [mc(i, 4.0 if i < 2 else 1.0, hook_pattern="understatement") for i in range(5)]
    rules, _ = weekly.playbook_items(five)
    assert [r["title"] for r in rules] == ["Hook pattern `understatement` is proven"]
    assert "2 hits in its last 5 uses" in rules[0]["detail"]


def test_a_tag_that_beats_the_others_is_a_rule_only_with_5_posts_on_each_side():
    clips = two_sides([3.0] * 5, [1.0] * 5, feature="prop", value="ball", other="box")
    rules, _ = weekly.playbook_items(clips)
    works = next(r for r in rules if r["title"] == "Works: `prop` = `ball`")
    assert "3.00 against 1.00" in works["detail"] and "5 against 5 posts" in works["detail"]
    avoid_clips = two_sides([0.5] * 8, [1.0] * 8, feature="prop", value="ball", other="box")
    rules, _ = weekly.playbook_items(avoid_clips)
    assert "Avoid: `prop` = `ball`" in [r["title"] for r in rules]
    rules, _ = weekly.playbook_items(two_sides([3.0] * 5, [1.0] * 4, feature="prop", value="ball", other="box"))
    assert rules == []


def test_rendering_carries_the_date_a_rule_entered_and_gives_new_rules_today():
    rules = [{"title": "Keep format `swap_trend`", "detail": "median outlier_x 2.00 over 5 posts"}]
    text = weekly.render_playbook("Franz", rules, ["format `recreate`: 3 measured posts, median outlier_x 1.00"], {}, date(2026, 10, 19))
    assert text.startswith("# Franz: playbook\n")
    assert "- **Keep format `swap_trend`**: median outlier_x 2.00 over 5 posts · since 2026-10-19" in text
    assert "## Watching\n\n- format `recreate`: 3 measured posts, median outlier_x 1.00\n" in text
    assert text.endswith("\n") and not text.endswith("\n\n")
    since = weekly.read_since(text)
    assert since == {"Keep format `swap_trend`": "2026-10-19"}
    again = weekly.render_playbook("Franz", rules, [], since, date(2026, 11, 2))
    assert "since 2026-10-19" in again and "2026-11-02" not in again  # the rule keeps the day it entered
    assert weekly.render_playbook("Franz", rules, [], since, date(2026, 11, 2)) == again  # deterministic


def test_a_playbook_with_nothing_to_say_says_so():
    text = weekly.render_playbook("Lenny Gold", [], [], {}, date(2026, 10, 19))
    assert "_No rule yet" in text and "## Watching" not in text


# ---- the week and the five lines ------------------------------------------------------------------------------------------------------


def test_the_default_week_is_the_last_finished_one():
    assert weekly.default_week(datetime(2026, 10, 19, 6, 15, tzinfo=LONDON)) == date(2026, 10, 12)  # the Monday run reviews 12-18 Oct
    assert weekly.default_week(datetime(2026, 10, 25, 23, 59, tzinfo=LONDON)) == date(2026, 10, 12)  # Sunday: the week is not over
    assert weekly.default_week(datetime(2026, 10, 26, 0, 0, tzinfo=LONDON)) == date(2026, 10, 19)
    assert weekly.default_week(datetime(2026, 10, 18, 23, 0, tzinfo=timezone.utc)) == date(2026, 10, 12)  # 23:00 UTC is already Mon 19 Oct 00:00 in London (BST)
    assert weekly.default_week(datetime(2026, 10, 18, 22, 59, tzinfo=timezone.utc)) == date(2026, 10, 5)  # one minute earlier it is still Sunday
    with pytest.raises(ValueError):
        weekly.default_week(datetime(2026, 10, 19, 6, 15))


def test_a_week_is_monday_to_sunday_london_across_the_clock_change():
    w = weekly.week_window(date(2026, 10, 19))
    assert w.start == datetime(2026, 10, 19, 0, 0, tzinfo=LONDON) and w.end == datetime(2026, 10, 26, 0, 0, tzinfo=LONDON)
    assert w.sunday == date(2026, 10, 25) and w.label() == "week of 19 Oct"
    cc = weekly.week_window(date(2026, 10, 26))  # BST ends Sun 25 Oct 2026: this week starts in GMT
    assert cc.start.utcoffset() == timedelta(0) and weekly.week_window(date(2026, 10, 19)).start.utcoffset() == timedelta(hours=1)
    with pytest.raises(ValueError):
        weekly.week_window(date(2026, 10, 20))


WEEK = weekly.week_window(date(2026, 10, 12))
MON = datetime(2026, 10, 12, 19, 0, tzinfo=LONDON)


def fact(i: int, at: datetime, *, views: int | None = None, x: float | None = None, hook: str | None = None, platform: str = "instagram", **metrics: float) -> weekly.PostFact:
    return weekly.PostFact(post_id=f"p{i}", clip_id=f"k{i}", platform=platform, posted_at=at, peak_views=views, outlier_x=x, hook=hook, metrics=metrics)


def test_the_result_line_has_posts_the_median_with_its_n_the_hits_and_the_best_post_beside_last_week():
    older = [fact(i, MON - 14 * D + i * D, x=v) for i, v in enumerate([0.9, 0.9])]  # their 7-day figures are in before last week ended
    last = [fact(10 + i, MON - 7 * D + i * D, x=v) for i, v in enumerate([1.0, 1.2, 1.4, 3.2])]  # week before: figures arrive from 7 days on
    mine = [fact(20, MON, views=2300, x=None, hook="First day as head butler."), fact(21, MON + D, views=800)]
    line = weekly.result_line(WEEK, [*older, *last, *mine])
    assert line.startswith("2 posts (last week 4) · median outlier_x ")
    assert "best “First day as head butler.” 2,300 views" in line
    assert "(n " in line and "last week " in line and "hit" in line and "measured" in line


def test_the_median_is_cumulative_to_the_weeks_end_against_the_same_a_week_earlier():
    # posts from 5-9 Oct have their 7-day figure by 12-16 Oct; the week to Sun 18 Oct includes them, the week before does not
    early = [fact(i, datetime(2026, 10, 5, 19, 0, tzinfo=LONDON) + i * D, x=v) for i, v in enumerate([1.0, 2.0, 3.0])]
    line = weekly.result_line(WEEK, early)
    assert "median outlier_x 2.0 (n 3; last week none yet)" in line and "1 hit of 3 measured" in line


def test_a_post_without_its_7_day_figure_by_the_weeks_end_is_not_counted_and_the_reason_is_given():
    fresh = [fact(1, datetime(2026, 10, 15, 19, 0, tzinfo=LONDON), views=500)]
    line = weekly.result_line(WEEK, fresh)
    assert "median outlier_x: none yet (the 7-day figure comes 7 days after a post)" in line and "hits: none yet" in line
    old_but_no_baseline = [fact(i, datetime(2026, 10, 1, 19, 0, tzinfo=LONDON) + i * H, x=None) for i in range(2)]
    assert "each post needs 3 earlier ones with a 7-day figure" in weekly.result_line(WEEK, old_but_no_baseline)
    assert "no Instagram post yet" in weekly.result_line(WEEK, [fact(1, MON, views=10, platform="tiktok")])


def test_only_instagram_figures_make_the_median_and_a_quiet_week_says_so():
    early = [fact(i, datetime(2026, 10, 5, 19, 0, tzinfo=LONDON), x=9.0, platform="tiktok") for i in range(3)]
    assert "none yet" in weekly.result_line(WEEK, early)
    assert "best: no post this week" in weekly.result_line(WEEK, early)
    assert "best: none yet (no views read this week)" in weekly.result_line(WEEK, [fact(1, MON)])


def test_a_long_hook_is_cut_and_a_missing_one_is_named():
    long = fact(1, MON, views=10, hook="x" * 100)
    assert "“" + "x" * 39 + "…”" in weekly.result_line(WEEK, [long])
    assert "a clip without a hook" in weekly.result_line(WEEK, [fact(1, MON, views=10)])


def test_the_audience_line_shows_follows_reach_and_the_guard_each_with_its_comparison_or_why_it_is_missing():
    partial = weekly.audience_line(follows=None, follows_n=0, follows_floor=None, reach=97.0, reach_prev=None, reach_n=1, guard=None)
    assert "followers: none yet (no follower count in the cloud yet)" in partial  # some data: every figure keeps its own phrase
    assert "follows per 1K: none yet (no follows data in the cloud yet)" in partial and "non-follower reach 97 % (last week none yet; n 1)" in partial
    assert "guard: no Instagram account" in partial
    full = weekly.audience_line(
        follows=3.8, follows_n=4, follows_floor={"status": "fixed", "value": 3.0}, reach=97.2, reach_prev=99.0, reach_n=6,
        guard={"handle": "franz.ig", "fires": False, "applied": False, "non_follower_pct_previous_week": 99.0, "non_follower_pct_this_week": 97.2},
    )
    assert "follows per 1K 3.8 (floor 3.0; n 4)" in full and "non-follower reach 97 % (last week 99 %; n 6)" in full and full.endswith("guard: no change")
    pending = weekly.audience_line(follows=1.0, follows_n=2, follows_floor={"status": "pending", "reason": "2 of 6 readings studio-wide so far"}, reach=None, reach_prev=None, reach_n=0, guard=None)
    assert "floor pending: 2 of 6 readings studio-wide so far" in pending


def test_with_no_audience_figure_at_all_the_audience_line_is_one_short_phrase():
    empty = weekly.audience_line(follows=None, follows_n=0, follows_floor=None, reach=None, reach_prev=None, reach_n=0, guard=None)
    assert empty == "no follower, follows or reach data in the cloud yet · guard: no Instagram account"
    guard = {"handle": "x", "fires": False, "applied": False, "non_follower_pct_previous_week": None, "non_follower_pct_this_week": None}
    assert weekly.audience_line(follows=None, follows_n=0, follows_floor=None, reach=None, reach_prev=None, reach_n=0, guard=guard) == (
        "no follower, follows or reach data in the cloud yet · guard: no change"  # no repeat of the missing reach reading
    )
    only_follows = weekly.audience_line(follows=2.0, follows_n=1, follows_floor=None, reach=None, reach_prev=None, reach_n=0, guard=guard)
    assert "non-follower reach: none yet (no reach data in the cloud yet)" in only_follows and "follows per 1K 2.0" in only_follows
    assert only_follows.endswith("guard: no change (it needs a reach reading in both weeks)")  # partial data: the per-figure form stays


def test_the_guard_text_says_what_the_code_did():
    base = {"handle": "franz.ig", "non_follower_pct_previous_week": 90.0, "non_follower_pct_this_week": 50.0, "drop_pct": 44.4}
    assert weekly.guard_text({**base, "fires": True, "applied": True, "new_dropin_share": 0.2}) == "guard: cut franz.ig to 0.20 (reach down 44 %)"
    assert "would cut franz.ig to 0.20" in weekly.guard_text({**base, "fires": True, "applied": False, "new_dropin_share": 0.2})
    assert "already at or under 0.20" in weekly.guard_text({**base, "fires": True, "applied": False, "new_dropin_share": None})
    assert weekly.guard_text({"handle": "x", "fires": False, "non_follower_pct_previous_week": None, "non_follower_pct_this_week": 80.0}) == (
        "guard: no change (it needs a reach reading in both weeks)"
    )


def lead_row(**kw: Any) -> dict[str, Any]:
    row = {"mode": "thompson", "readings": 5, "readings_needed": 3, "tallied": 4, "min_uses": 6, "fewest_uses": 1, "leading": {"pattern": "false-premise", "wins": 3, "uses": 4}}
    return {**row, **kw}


def test_the_hook_line_has_skip_rate_against_the_ceiling_the_leading_pattern_and_flags():
    line = weekly.hook_line(skip=41.0, skip_n=5, ceiling={"status": "fixed", "value": 45.0}, row=lead_row(), flagged_posts=[("“First day.”", ["hook", "hold"])])
    assert line == "skip rate 41 % (ceiling 45 %; n 5) · leading: false-premise, 3 wins of 4 (too few to call) · below 2 floors: “First day.” (hook, hold)"
    firm = weekly.hook_line(skip=41.0, skip_n=5, ceiling={"status": "fixed", "value": 45.0}, row=lead_row(leading={"pattern": "false-premise", "wins": 5, "uses": 6}), flagged_posts=[])
    assert "leading: false-premise, 5 wins of 6" in firm and "too few" not in firm


def test_the_hook_line_says_why_a_part_is_missing():
    line = weekly.hook_line(skip=None, skip_n=0, ceiling=None, row=lead_row(leading=None, mode="rotation", tallied=0), flagged_posts=[])
    assert "skip rate: none yet (no skip-rate data in the cloud yet)" in line and "leading: none yet (rotating, 5 of 3 readings before it can learn)" in line
    pend = weekly.hook_line(skip=40.0, skip_n=3, ceiling={"status": "pending", "reason": "no data in the cloud yet"}, row=None, flagged_posts=[])
    assert "ceiling pending: no data in the cloud yet" in pend and "no hook arms" in pend
    assert "nothing tallied yet" in weekly.hook_line(skip=None, skip_n=0, ceiling=None, row=lead_row(leading=None), flagged_posts=[])
    two = weekly.hook_line(skip=None, skip_n=0, ceiling=None, row=lead_row(), flagged_posts=[("a", ["hook", "hold"]), ("b", ["hook", "sends"]), ("c", ["hold", "sends"])])
    assert "below 2 floors: a (hook, hold)" in two and "below 2 floors: b" in two and "below 2 floors: c" not in two  # at most two are named


def test_next_says_too_few_to_call_under_10_measured_posts_and_always_names_what_needs_you():
    assert weekly.next_line(measured=9, lifts=[], needs=[]) == "too few to call (9 of 10 measured posts) · needs you: nothing"
    assert weekly.next_line(measured=0, lifts=[], needs=["the bar says PROMOTE"]).endswith("needs you: the bar says PROMOTE")
    assert weekly.next_line(measured=10, lifts=[], needs=[]) == "STOP nothing clear · DO MORE nothing clear · needs you: nothing"
    lifts = weekly.side_lifts([mc(i, 4.0, setting="kitchen") for i in range(9)] + [mc(20 + i, 1.0, setting="garden") for i in range(9)])
    line = weekly.next_line(measured=18, lifts=lifts, needs=["merge the playbook PR", "retire arm x"])
    assert "DO MORE setting = kitchen (median 4.0x against 1.0x for the others; n 9 v 9)" in line
    assert "STOP setting = garden (median 1.0x against 4.0x for the others; n 9 v 9)" in line  # the garden lift is 0.25
    assert line.endswith("needs you: merge the playbook PR; retire arm x")


def test_the_labels_are_those_of_the_plans_example():
    out = weekly.with_labels(["a", "b", "c", "d", "e"])
    assert out == ["1 Result    a", "2 Audience  b", "3 Hook      c", "4 Tests     d", "5 Next      e"]


def test_the_bar_phrase_matches_the_plans_example():
    from studio.review import CharacterEvidence

    ev = CharacterEvidence(slug="reginald", bar="not_yet", posts=9, first_post_at=MON, age=timedelta(days=14, hours=3), mature_posts={}, median_views_7d={}, max_views=None)
    assert weekly.bar_text(ev) == "not yet (9 of 20 posts, day 14 of 28)"
    assert weekly.bar_text(CharacterEvidence(slug="x", bar="continue", posts=22, first_post_at=MON, age=timedelta(days=31), mature_posts={}, median_views_7d={}, max_views=None)) == "continue (22 posts, day 31)"
    assert weekly.bar_text(CharacterEvidence(slug="x", bar="not_yet", posts=0, first_post_at=None, age=None, mature_posts={}, median_views_7d={}, max_views=None)) == "not yet (0 of 20 posts, day 0 of 28)"


# ---- the whole run on a small studio ---------------------------------------------------------------------------------------------------

NOW = datetime(2026, 10, 19, 6, 15, tzinfo=LONDON)  # the first Monday run: it reviews 12-18 Oct and sets the floors
MONDAY = date(2026, 10, 12)


def metrics(i: int) -> dict[str, Any]:
    """Readings of a post taken a week after it went out."""
    return {"views": 1000, "shares": 10 + i, "follows": i, "watched_pct": 40.0 + i, "skip_rate": 50.0 - i}


def first_weeks() -> World:
    """Franz posted 10 times between 5 and 16 Oct (the first five have 7-day figures by now), Reginald 3 times, Lenny not yet."""
    w = World()
    days = [datetime(2026, 10, d, 19, 0, tzinfo=LONDON) for d in (5, 6, 7, 8, 9, 12, 13, 14, 15, 16)]
    v7 = [100, 100, 100, 300, 50, None, None, None, None, None]
    for i, (at, v) in enumerate(zip(days, v7, strict=True)):
        w.post("franz", at, v7=v, hook=f"Franz hook {i}", snaps=[metrics(i)], features={"setting": "kitchen" if i % 2 else "garden"})
    for i in range(3):
        w.post("reginald", datetime(2026, 10, 13 + i, 19, 30, tzinfo=LONDON), v72=500 + i, hook=f"Reg hook {i}", snaps=[metrics(20 + i)])
    return w


def run(w: World, tmp_path: Path, **kw: Any) -> dict[str, Any]:
    kw.setdefault("out_dir", tmp_path / "out")
    kw.setdefault("repo_root", tmp_path / "repo")
    return weekly.run_weekly(w.store, kw.pop("now", NOW), **kw)


def test_the_first_monday_run_builds_the_digest_saves_the_reviews_and_logs_one_run(tmp_path):
    w = first_weeks()
    out = run(w, tmp_path)
    assert out["week"] == "2026-10-12" and out["status"] == "ok" and out["dry_run"] is False
    header = out["digest"]["header"]
    assert len(header) == 2 and header[0].startswith("Credits 0 of 6,000 this month") and header[1].startswith("Warnings: none · Proposals waiting: ")
    assert [c["slug"] for c in out["digest"]["characters"]] == ["franz", "reginald", "lenny"]  # the owner's order
    franz, reginald, lenny = out["digest"]["characters"]
    assert franz["bar"] == "not yet (10 of 20 posts, day 13 of 28)" and franz["bar_status"] == "not_yet"
    assert franz["title"] == "Franz · week of 12 Oct · bar: not yet (10 of 20 posts, day 13 of 28)"
    assert [ln.split("  ")[0].strip() for ln in franz["lines"]] == ["1 Result", "2 Audience", "3 Hook", "4 Tests", "5 Next"]
    assert lenny["lines"] == ["no posts yet"] and lenny["bar_status"] == "not_yet"
    assert "too few to call" in franz["lines"][4] and "needs you:" in franz["lines"][4]
    # reviews: one per live character for the Monday of the week, with the code's bar
    reviews = {r.character_slug: r for r in w.store.list_reviews()}
    assert set(reviews) == {"franz", "reginald", "lenny"} and all(r.week == MONDAY and r.bar_status == "not_yet" for r in reviews.values())
    head = "\n".join(header) + "\n\n"  # the studio header, a blank line, then his title and his lines
    assert reviews["franz"].report_md == head + "\n".join([franz["title"], *franz["lines"]])
    assert reviews["lenny"].report_md == head + lenny["title"] + "\nno posts yet"
    # one run, kind weekly, status ok, the digest as its summary and the structured details the terminal reads
    (run_row,) = w.store.list_runs(kind="weekly")
    assert run_row.status.value == "ok" and run_row.summary == out["summary"] and run_row.id == out["run_id"]
    d = run_row.details
    assert {"week", "digest", "score_test", "floors", "proposals", "proposal_url", "proposal_pending_url"} <= set(d)
    assert d["week"] == "2026-10-12" and d["digest"]["header"] == header and d["score_test"]["label"] == "unproven"
    json.dumps(d)  # strict JSON: nothing the database could not store
    assert out["summary"].startswith(header[0]) and franz["title"] in out["summary"]


def test_the_baseline_week_sets_the_floors_on_the_first_run_and_pending_ones_say_why(tmp_path):
    out = run(first_weeks(), tmp_path)
    f = out["floors"]
    assert f["computed"] is True and f["basis"]["from"] == "2026-10-05" and f["basis"]["to"] == "2026-10-18"
    sends = f["studio"]["sends_per_1k"]
    assert sends["status"] == "fixed" and sends["n"] == 13 and f["fixed_on"]["sends_per_1k"] == "2026-10-18"  # 10 + 3 readings; the first fix: end of weeks 1-2
    assert f["characters"]["franz"]["sends_per_1k"]["basis"] == "character" and f["characters"]["lenny"]["sends_per_1k"]["basis"] == "studio"
    assert f["characters"]["franz"]["skip_rate"]["kind"] == "ceiling"
    assert any(n.startswith("score test: 0 of 20") for n in out["notes"])


def test_floors_with_no_data_yet_are_pending_with_the_reason(tmp_path):
    w = World()
    w.post("franz", datetime(2026, 10, 13, 19, 0, tzinfo=LONDON), v72=100)
    out = run(w, tmp_path)
    for metric, _ in weekly.FLOOR_METRICS:
        assert out["floors"]["studio"][metric] == {"kind": out["floors"]["studio"][metric]["kind"], "status": "pending", "n": 0, "needed": 6, "reason": "no data in the cloud yet"}
    assert any(n.startswith("floors pending:") and "no data in the cloud yet" in n for n in out["notes"])
    assert out["status"] == "ok"  # a part with no data is a note, not an error


def test_a_week_that_ends_before_the_baseline_is_over_sets_no_floors(tmp_path):
    out = run(first_weeks(), tmp_path, monday=date(2026, 10, 5), now=datetime(2026, 10, 12, 6, 15, tzinfo=LONDON))
    assert out["floors"]["computed"] is False and "18 Oct" in out["floors"]["reason"]


def test_later_runs_copy_the_fixed_floors_and_never_recompute_them(tmp_path):
    w = first_weeks()
    first = run(w, tmp_path)
    # a lot of new readings arrive: a recount would change every median
    for i in range(6):
        w.post("franz", datetime(2026, 10, 20 + i % 3, 19, 0, tzinfo=LONDON), snaps=[{"views": 1000, "shares": 900, "follows": 90, "watched_pct": 99.0, "skip_rate": 5.0}])
    w.post("franz", datetime(2026, 10, 12, 20, 0, tzinfo=LONDON), snaps=[{"views": 1000, "shares": 999}])  # even a late baseline post
    second = run(w, tmp_path, monday=date(2026, 10, 19), now=datetime(2026, 10, 26, 6, 15, tzinfo=LONDON))
    assert second["floors"]["studio"] == first["floors"]["studio"] and second["floors"]["characters"] == first["floors"]["characters"]
    assert second["floors"]["fixed_on"] == first["floors"]["fixed_on"]


def test_a_floor_that_was_pending_is_filled_by_a_later_run_with_the_date_written_down(tmp_path):
    w = World()
    for i in range(3):
        w.post("franz", datetime(2026, 10, 13 + i, 19, 0, tzinfo=LONDON), snaps=[{"views": 1000, "shares": 10 + i, "at": datetime(2026, 10, 20, 10, 0, tzinfo=timezone.utc)}])
    first = run(w, tmp_path)
    assert first["floors"]["studio"]["sends_per_1k"]["status"] == "pending" and first["floors"]["fixed_on"]["sends_per_1k"] is None
    for i, at in enumerate([(20, 0), (21, 0), (23, 30)]):  # the 4th..6th readings arrive on 22 Oct, the last at 23:30 UTC: 00:30 on the 23rd in London
        w.post("franz", datetime(2026, 10, 16 + i, 19, 0, tzinfo=LONDON), snaps=[{"views": 1000, "shares": 20 + i, "at": datetime(2026, 10, 22, *at, tzinfo=timezone.utc)}])
    second = run(w, tmp_path, monday=date(2026, 10, 19), now=datetime(2026, 10, 26, 6, 15, tzinfo=LONDON))
    # the day is the one the 6th reading arrived (London), not the day of the run (26 Oct)
    assert second["floors"]["studio"]["sends_per_1k"]["status"] == "fixed" and second["floors"]["fixed_on"]["sends_per_1k"] == "2026-10-23"


def test_rerunning_the_same_week_rewrites_its_reviews_and_logs_another_run(tmp_path):
    w = first_weeks()
    run(w, tmp_path)
    run(w, tmp_path)
    assert len(w.store.list_reviews()) == 3  # rewritten, not duplicated
    assert len(w.store.list_runs(kind="weekly")) == 2


def test_a_dry_run_prints_everything_and_writes_nothing(tmp_path):
    w = first_weeks()
    # an Instagram guard that would fire: reach fell by more than 40 % in a week
    acct = w.account("franz")
    p = w.store.list_posts(account_id=acct.id)[0]
    w.store.add_snapshot(Snapshot(post_id=p.id, captured_at=NOW - 10 * D, views=10, non_follower_pct=90.0))
    w.store.add_snapshot(Snapshot(post_id=p.id, captured_at=NOW - 2 * D, views=10, non_follower_pct=40.0))
    out = run(w, tmp_path, dry_run=True)
    assert out["dry_run"] is True and out["run_id"] is None and out["reviews_saved"] == [] and out["files"] == []
    assert w.store.list_reviews() == [] and w.store.list_runs() == []
    assert w.store.accounts("franz")[0].dropin_share != 0.20  # the binding guard is not applied by a dry run
    assert "would cut franz.ig to 0.20" in out["digest"]["characters"][0]["lines"][1]
    assert not (tmp_path / "out").exists()
    real = run(w, tmp_path)
    assert w.store.accounts("franz")[0].dropin_share == 0.20 and "guard: cut franz.ig to 0.20" in real["digest"]["characters"][0]["lines"][1]
    assert "needs you: the guard cut franz.ig" in real["digest"]["characters"][0]["lines"][4]


def test_the_audience_line_reads_the_weeks_reach_and_follows_and_the_hook_line_the_skip_rate(tmp_path):
    w = first_weeks()
    acct = w.account("franz")
    p = w.store.list_posts(account_id=acct.id)[0]
    for days, pct in ((10, 95.0), (3, 97.0), (2, 99.0)):
        w.store.add_snapshot(Snapshot(post_id=p.id, captured_at=NOW - days * D, views=10, non_follower_pct=pct, skip_rate=41.0))
    out = run(w, tmp_path)
    lines = out["digest"]["characters"][0]["lines"]
    assert "non-follower reach 98 % (last week 95 %; n 2)" in lines[1] and "guard: no change" in lines[1]
    assert "followers: none yet" in lines[1] and "follows per 1K " in lines[1]
    # the week's skip readings: the five baseline posts' of 13-17 Oct (50 .. 46) and the two added ones (41): median 47, n 7
    assert "skip rate 47 % (ceiling " in lines[2] and "; n 7)" in lines[2]


def test_the_credits_and_the_cost_per_1k_views_are_in_the_header(tmp_path):
    from studio.models import LedgerEntry

    w = first_weeks()
    clip = w.store.list_clips()[0]
    w.store.ledger_add(LedgerEntry(clip_id=clip.id, month="2026-10", kind="settle", credits=91))
    out = run(w, tmp_path)
    line = out["digest"]["header"][0]
    assert line.startswith("Credits 91 of 6,000 this month (2 %, 0 still reserved; last month 0)")
    assert "cost per 1K views 7.0 credits (n 13,000 views" in line and "last month none yet)" in line  # under 100: one decimal


def test_a_cost_per_1k_views_of_100_credits_or_more_is_in_whole_credits_in_the_header(tmp_path):
    from studio.models import LedgerEntry

    w = first_weeks()
    clip = w.store.list_clips()[0]
    w.store.ledger_add(LedgerEntry(clip_id=clip.id, month="2026-10", kind="settle", credits=2000))
    line = run(w, tmp_path)["digest"]["header"][0]
    assert "cost per 1K views 154 credits (n 13,000 views" in line  # 2000 credits over 13,000 views: 153.8


def test_the_cost_per_1k_views_has_no_decimals_from_100_credits():
    assert weekly.per_1k_text(4.2) == "4.2"  # under 100: one decimal, as before
    assert weekly.per_1k_text(99.94) == "99.9" and weekly.per_1k_text(100.0) == "100" and weekly.per_1k_text(11461.5) == "11,462"
    assert weekly.per_1k_text(2500.4) == "2,500"


def test_a_warning_that_fired_is_in_the_header(tmp_path):
    w = first_weeks()
    post = w.store.list_posts()[0]
    w.store.update_post(post.id, status="failed", error="Postiz said no")
    out = run(w, tmp_path)
    assert out["digest"]["header"][1].startswith("Warnings: 1 (post ") and "is failed" in out["digest"]["header"][1]
    assert len(out["warnings"]) == 1 and out["warnings"][0] in out["digest"]["header"][1]


def test_a_part_that_crashes_is_a_note_the_digest_still_comes_and_the_run_is_logged_as_an_error(tmp_path, monkeypatch):
    w = first_weeks()

    def boom(*_args, **_kw):
        raise RuntimeError("no way")

    monkeypatch.setattr(weekly, "score_test", boom)
    out = run(w, tmp_path)
    assert out["status"] == "error" and any(n.startswith("score test failed: RuntimeError: no way") for n in out["notes"])
    assert len(out["digest"]["characters"]) == 3 and w.store.list_runs(kind="weekly")[0].status.value == "error"
    assert w.store.list_runs(kind="weekly")[0].details["score_test"]["label"] == "unproven"  # the empty test, not a crash


def test_the_score_test_takes_its_looks_once_across_the_weekly_runs(tmp_path, monkeypatch, experiments_on):
    w = first_weeks()
    rows = near_threshold()
    monkeypatch.setattr(weekly, "score_observations", lambda _store: rows)
    first = run(w, tmp_path)
    assert first["score_test"]["label"] == "validated" and set(first["score_test"]["decided"]) == {"20"}
    # next Monday a 7-day figure arrives late and sorts earlier: the look that was taken must not move
    monkeypatch.setattr(weekly, "score_observations", lambda _store: rows + [early_arrival()])
    second = run(w, tmp_path, monday=date(2026, 10, 19), now=datetime(2026, 10, 26, 6, 15, tzinfo=LONDON))
    st = second["score_test"]
    assert (st["label"], st["look"], st["rho"], st["n"]) == ("validated", 20, first["score_test"]["rho"], 21)
    assert st["decided"] == first["score_test"]["decided"]
    assert w.store.list_runs(kind="weekly")[-1].details["score_test"]["decided"] == first["score_test"]["decided"]  # stored, so the next run copies it
    # the score test line of the digest is built from the frozen look
    assert "score test validated at 20" in second["digest"]["characters"][0]["lines"][3]


def test_a_run_whose_score_test_crashes_still_carries_the_looks_taken_forward(tmp_path, monkeypatch):
    w = first_weeks()
    monkeypatch.setattr(weekly, "score_observations", lambda _store: near_threshold())
    first = run(w, tmp_path)

    def boom(*_args, **_kw):
        raise RuntimeError("no way")

    monkeypatch.setattr(weekly, "score_test", boom)
    broken = run(w, tmp_path, monday=date(2026, 10, 19), now=datetime(2026, 10, 26, 6, 15, tzinfo=LONDON))
    assert broken["status"] == "error" and broken["score_test"]["decided"] == first["score_test"]["decided"]


def test_the_command_shows_a_look_the_weekly_review_already_took(monkeypatch, tmp_path):
    w = first_weeks()
    rows = near_threshold()
    monkeypatch.setattr(weekly, "score_observations", lambda _store: rows)
    first = run(w, tmp_path)
    monkeypatch.setattr(weekly, "score_observations", lambda _store: rows + [early_arrival()])
    monkeypatch.setattr(weekly, "open_store", lambda: w.store)
    r = CliRunner().invoke(app, ["learn", "score-test"])
    assert r.exit_code == 0, r.output
    out = json.loads(r.stdout)
    assert (out["label"], out["rho"], out["n"]) == ("validated", first["score_test"]["rho"], 21)


def test_a_character_block_that_crashes_is_one_line_the_rest_of_the_digest_still_comes_and_the_run_is_logged_as_an_error(tmp_path, monkeypatch):
    w = first_weeks()
    real = weekly.tests_line

    def tests_line(slug, *args, **kw):
        if slug == "reginald":
            raise RuntimeError("no way")
        return real(slug, *args, **kw)

    monkeypatch.setattr(weekly, "tests_line", tests_line)
    out = run(w, tmp_path)
    assert out["status"] == "error" and any(n.startswith("digest of reginald failed: RuntimeError: no way") for n in out["notes"])
    franz, reginald, lenny = out["digest"]["characters"]
    assert reginald["slug"] == "reginald" and reginald["lines"] == ["could not be built (RuntimeError)"]
    assert reginald["title"] == "Reginald · week of 12 Oct" and "failed" not in reginald and reginald["bar"] == ""  # the title only, nothing half-built
    assert franz["lines"][0].startswith("1 Result") and lenny["lines"] == ["no posts yet"]
    assert "could not be built (RuntimeError)" in out["summary"] and out["summary"].startswith(out["digest"]["header"][0])
    # the run is logged; the failed character gets no review row (it would overwrite a good one with a line of excuses)
    (logged,) = w.store.list_runs(kind="weekly")
    assert logged.status.value == "error" and logged.details["digest"]["characters"][1]["lines"] == reginald["lines"]
    assert {r.character_slug for r in w.store.list_reviews()} == {"franz", "lenny"} and out["reviews_saved"] == ["franz", "lenny"]
    json.dumps(logged.details)


def test_the_guard_is_applied_before_a_block_can_crash(tmp_path, monkeypatch):
    w = first_weeks()
    acct = w.account("franz")
    p = w.store.list_posts(account_id=acct.id)[0]
    w.store.add_snapshot(Snapshot(post_id=p.id, captured_at=NOW - 10 * D, views=10, non_follower_pct=90.0))
    w.store.add_snapshot(Snapshot(post_id=p.id, captured_at=NOW - 2 * D, views=10, non_follower_pct=40.0))
    def boom(*_a, **_k):
        raise RuntimeError("all of them")

    monkeypatch.setattr(weekly, "result_line", boom)  # every character with posts fails (Lenny has none: his block is built)
    out = run(w, tmp_path)
    assert out["status"] == "error" and w.store.accounts("franz")[0].dropin_share == 0.20  # the binding cut happened
    assert [c["lines"] for c in out["digest"]["characters"]] == [["could not be built (RuntimeError)"]] * 2 + [["no posts yet"]]
    assert len(w.store.list_runs(kind="weekly")) == 1


def test_a_header_that_crashes_does_not_cost_the_owner_the_characters(tmp_path, monkeypatch):
    w = first_weeks()

    def boom(*_a, **_k):
        raise RuntimeError("no header")

    monkeypatch.setattr(weekly, "studio_header", boom)
    out = run(w, tmp_path)
    assert out["status"] == "error" and any(n.startswith("studio header failed: RuntimeError") for n in out["notes"])
    assert out["digest"]["header"][0] == "The studio header could not be built (RuntimeError)." and out["digest"]["characters"][0]["lines"][0].startswith("1 Result")


def test_only_live_characters_are_reviewed(tmp_path):
    w = first_weeks()
    w.store.upsert_character(Character(slug="biscuit", name="Biscuit", status="paused"))
    w.store.upsert_character(Character(slug="reginald", name="Reginald", status="designing"))
    out = run(w, tmp_path)
    assert [c["slug"] for c in out["digest"]["characters"]] == ["franz", "lenny"]


# ---- the proposals, the playbooks and the files for the proposal job -------------------------------------------------------------------


def measured_world() -> World:
    """Franz with 10 measured clips split between two settings: kitchen (5, median 3.5, hits) against garden (5, median 1.0)."""
    w = World()
    for i in range(10):
        kitchen = i < 5
        w.post(
            "franz", datetime(2026, 9, 29, 19, 0, tzinfo=LONDON) + i * D, hook=f"hook {i}",
            features={"setting": "kitchen" if kitchen else "garden", "outlier_x": 3.5 if kitchen else 1.0, "hook_pattern": "none", "format_id": "swap_trend"},
        )
    return w


WEEK2_NOW = datetime(2026, 10, 26, 6, 15, tzinfo=LONDON)


def test_a_rule_candidate_waits_a_week_and_becomes_a_proposal_when_the_next_weeks_posts_still_show_it(tmp_path):
    w = measured_world()
    first = run(w, tmp_path)
    assert [c["status"] for c in first["candidates"]] == ["candidate"] and first["candidates"][0]["feature"] == "setting"
    assert [p for p in first["proposals"] if p["kind"] == "hit_rule"] == []
    # next week: two more kitchen posts and one garden post
    for i, (setting, x) in enumerate([("kitchen", 3.0), ("kitchen", 3.0), ("garden", 1.0)]):
        w.post("franz", datetime(2026, 10, 13 + i, 19, 0, tzinfo=LONDON), features={"setting": setting, "outlier_x": x, "hook_pattern": "none", "format_id": "swap_trend"})
    second = run(w, tmp_path, monday=date(2026, 10, 19), now=WEEK2_NOW)
    (rule,) = [p for p in second["proposals"] if p["kind"] == "hit_rule"]
    assert rule["feature"] == "setting" and rule["value"] == "kitchen" and rule["status"] == "ready" and rule["repeat"] is False
    assert (rule["n"], rule["n_others"], rule["hits"]) == (7, 6, 7) and len(rule["clip_ids"]) == 7 and rule["since_week"] == "2026-10-12"
    assert second["digest"]["header"][1].endswith("Proposals waiting: 1 hit rule, 1 playbook")
    assert "docs/weekly/2026-10-19.md" in second["files"]
    assert second["proposal_pending_url"] == "https://github.com/oschwend-prog/character-studio/compare/build/slice1...weekly/2026-10-19?expand=1"
    assert second["proposal_url"] is None  # the card links it only once the propose job has pushed the branch (confirm_proposal)


def test_a_ready_hit_rule_is_named_once_on_the_first_live_characters_needs_you(tmp_path):
    w = measured_world()
    run(w, tmp_path)
    for i, (setting, x) in enumerate([("kitchen", 3.0), ("kitchen", 3.0), ("garden", 1.0)]):
        w.post("franz", datetime(2026, 10, 13 + i, 19, 0, tzinfo=LONDON), features={"setting": setting, "outlier_x": x, "hook_pattern": "none", "format_id": "swap_trend"})
    w.post("reginald", datetime(2026, 10, 14, 19, 30, tzinfo=LONDON), hook="Reg hook")  # a second character with posts: the line is not repeated
    second = run(w, tmp_path, monday=date(2026, 10, 19), now=WEEK2_NOW)
    assert [p["kind"] for p in second["proposals"]].count("hit_rule") == 1
    franz, reginald, lenny = (c["lines"] for c in second["digest"]["characters"])
    assert "merge the hit-rule PR" in franz[4] and "needs you: merge the playbook PR; merge the hit-rule PR" in franz[4]
    assert "hit-rule" not in reginald[4] and lenny == ["no posts yet"]
    # with no ready rule nothing is named
    quiet = run(w, tmp_path, monday=date(2026, 10, 12), now=NOW)
    assert "hit-rule" not in quiet["digest"]["characters"][0]["lines"][4]


def test_rerunning_the_same_week_is_not_a_second_look(tmp_path):
    w = measured_world()
    run(w, tmp_path)
    again = run(w, tmp_path)  # the same data, the same week
    assert [p for p in again["proposals"] if p["kind"] == "hit_rule"] == []
    later = run(w, tmp_path, monday=date(2026, 10, 19), now=WEEK2_NOW)  # a week later with no new posts: still no new data to look at
    assert [p for p in later["proposals"] if p["kind"] == "hit_rule"] == [] and [c["status"] for c in later["candidates"]] == ["candidate"]


def test_the_proposal_files_are_the_changed_playbooks_and_the_weekly_doc_and_nothing_when_nothing_changed(tmp_path):
    w = measured_world()
    out = tmp_path / "out"
    first = run(w, tmp_path)
    assert "characters/franz/playbook.md" in first["files"] and f"docs/weekly/2026-10-12.md" in first["files"]
    playbook = (out / "characters/franz/playbook.md").read_text(encoding="utf-8")
    assert playbook.startswith("# Franz: playbook\n") and "Works: `setting` = `kitchen`" in playbook and "since 2026-10-19" in playbook
    assert not (out / "characters/reginald").exists() and not (out / "characters/lenny").exists()  # nothing to say: no file
    doc = (out / "docs/weekly/2026-10-12.md").read_text(encoding="utf-8")
    assert doc.startswith("# Weekly review: week of 12 Oct\n") and "Franz · week of 12 Oct" in doc and "## Proposals" in doc
    assert first["proposal_pending_url"].endswith("weekly/2026-10-12?expand=1") and first["proposal_url"] is None
    # the owner merged the PR: the playbook is in the repo now. The same data again changes nothing, so no files and no URL
    repo = tmp_path / "repo"
    (repo / "characters/franz").mkdir(parents=True)
    (repo / "characters/franz/playbook.md").write_text(playbook, encoding="utf-8")
    quiet = run(w, tmp_path, out_dir=tmp_path / "out2", repo_root=repo, monday=date(2026, 10, 19), now=WEEK2_NOW)
    assert quiet["files"] == [] and quiet["proposal_pending_url"] is None and not (tmp_path / "out2").exists()
    assert quiet["playbooks"]["franz"]["changed"] is False
    assert "Proposals waiting: none" in quiet["digest"]["header"][1]


def test_a_rule_keeps_the_day_it_entered_when_the_playbook_is_regenerated(tmp_path):
    w = measured_world()
    first = run(w, tmp_path)
    assert first["playbooks"]["franz"]["changed"]
    repo = tmp_path / "repo"
    (repo / "characters/franz").mkdir(parents=True)
    (repo / "characters/franz/playbook.md").write_text((tmp_path / "out/characters/franz/playbook.md").read_text(encoding="utf-8"), encoding="utf-8")
    for i in range(2):  # new data changes the numbers of the rule, so the file is rewritten ...
        w.post("franz", datetime(2026, 10, 13 + i, 19, 0, tzinfo=LONDON), features={"setting": "kitchen", "outlier_x": 5.0, "hook_pattern": "none", "format_id": "swap_trend"})
    second = run(w, tmp_path, out_dir=tmp_path / "out2", repo_root=repo, monday=date(2026, 10, 19), now=WEEK2_NOW)
    text = (tmp_path / "out2/characters/franz/playbook.md").read_text(encoding="utf-8")
    assert second["playbooks"]["franz"]["changed"] and "since 2026-10-19" in text and "2026-10-26" not in text  # ... but it keeps its entry day


def test_a_proposal_that_was_made_last_week_and_is_still_waiting_does_not_open_a_new_pr(tmp_path):
    w = measured_world()
    run(w, tmp_path)  # week of 12 Oct: the candidate
    for i, (setting, x) in enumerate([("kitchen", 3.0), ("kitchen", 3.0), ("garden", 1.0)]):
        w.post("franz", datetime(2026, 10, 13 + i, 19, 0, tzinfo=LONDON), features={"setting": setting, "outlier_x": x, "hook_pattern": "none", "format_id": "swap_trend"})
    repo = tmp_path / "repo"
    (repo / "characters/franz").mkdir(parents=True)
    second = run(w, tmp_path, out_dir=tmp_path / "out2", repo_root=repo, monday=date(2026, 10, 19), now=WEEK2_NOW)
    assert second["proposal_pending_url"]
    (repo / "characters/franz/playbook.md").write_text((tmp_path / "out2/characters/franz/playbook.md").read_text(encoding="utf-8"), encoding="utf-8")
    third = run(w, tmp_path, out_dir=tmp_path / "out3", repo_root=repo, monday=date(2026, 10, 26), now=datetime(2026, 11, 2, 6, 15, tzinfo=LONDON))
    (rule,) = [p for p in third["proposals"] if p["kind"] == "hit_rule"]
    assert rule["repeat"] is True  # still waiting ...
    assert third["files"] == [] and third["proposal_pending_url"] is None  # ... but nothing new to put in front of him
    assert "Proposals waiting: 1 hit rule" in third["digest"]["header"][1]


def test_an_arm_retire_proposal_comes_from_the_tally_and_is_a_proposal_to_merge(tmp_path, experiments_on):
    w = World()
    w.baseline("reginald", datetime(2026, 10, 13, 19, 30, tzinfo=LONDON), v72=100)  # the 72-hour readings x72 is measured against
    # twelve tallied uses of one arm that each lost (x72 below 1) and have a poor outlier_x
    for i in range(12):
        w.post(
            "reginald", datetime(2026, 10, 16, 19, 30, tzinfo=LONDON) + i * D, v72=10, v7=40,
            features={"hook_pattern": "understatement", "hook_by": "bandit", "outlier_x": 0.4},
            created=datetime(2026, 10, 14, 12, 0, tzinfo=LONDON),
        )
    out = run(w, tmp_path, now=datetime(2026, 11, 9, 6, 15, tzinfo=LONDON), monday=date(2026, 11, 2))
    retire = [p for p in out["proposals"] if p["kind"] == "arm_retire"]
    assert [(p["character"], p["arm"]) for p in retire] == [("reginald", "understatement")] and retire[0]["win_rate"] == 0.0
    assert any("retire hook arm understatement" in ln for ln in out["digest"]["characters"][1]["lines"][4:])
    assert "Proposals waiting: 1 arm" in out["digest"]["header"][1] or "1 arm" in out["digest"]["header"][1]
    doc = (tmp_path / "out/docs/weekly/2026-11-02.md").read_text(encoding="utf-8")
    assert "retire `understatement` for reginald" in doc


def test_the_test_registry_decides_which_tests_the_tests_line_names(tmp_path, experiments_on):
    w = first_weeks()
    out = run(w, tmp_path)
    tests = out["digest"]["characters"][0]["lines"][3]
    assert "score test 0 of 20 measured clips, 0 of them Franz's (not a verdict)" in tests and "hook test" in tests and "not a verdict" in tests
    # the two edit tests carry short labels, not their long names
    assert "test G zoom pulses 0 v 0 (need 10 v 10; not a verdict)" in tests and "test H word pop 0 v 0 (need 10 v 10; not a verdict)" in tests
    assert "on the beat" not in tests and "word by word" not in tests
    off = run(first_weeks(), tmp_path)  # the same data, with the live registry (A and B on, C off)
    assert "test C" not in off["digest"]["characters"][0]["lines"][3]  # a test that is off is not named


def test_with_every_test_off_the_tests_line_says_so(tmp_path):
    out = run(first_weeks(), tmp_path)  # the suite's default registry has every test off
    assert out["digest"]["characters"][0]["lines"][3].endswith("no test is on")


def test_a_post_below_two_floors_is_flagged_on_the_hook_line_from_week_3(tmp_path):
    w = first_weeks()
    first = run(w, tmp_path)
    assert first["floors"]["characters"]["franz"]["watched_pct"]["status"] == "fixed"
    # week 3: a post with every reading far below the floors, and one in the baseline weeks (not diagnosed)
    w.post("franz", datetime(2026, 10, 20, 19, 0, tzinfo=LONDON), hook="A weak one", snaps=[{"views": 1000, "shares": 0, "follows": 0, "watched_pct": 5.0, "skip_rate": 95.0}])
    w.post("franz", datetime(2026, 10, 17, 19, 0, tzinfo=LONDON), hook="Baseline weak", snaps=[{"views": 1000, "shares": 0, "follows": 0, "watched_pct": 5.0, "skip_rate": 95.0}])
    out = run(w, tmp_path, monday=date(2026, 10, 19), now=WEEK2_NOW)
    hook_line = out["digest"]["characters"][0]["lines"][2]
    assert "below 2 floors: “A weak one” (hook, hold, sends, follows)" in hook_line and "Baseline weak" not in hook_line


def test_the_summary_and_the_details_agree(tmp_path):
    out = run(first_weeks(), tmp_path)
    for block in out["digest"]["characters"]:
        assert block["title"] in out["summary"] and all(line in out["summary"] for line in block["lines"])
    assert all(line in out["summary"] for line in out["digest"]["header"])


# ---- the command -----------------------------------------------------------------------------------------------------------------------


@pytest.fixture
def cli_world(monkeypatch, tmp_path):
    w = first_weeks()
    monkeypatch.setattr(weekly, "open_store", lambda: w.store)
    monkeypatch.setattr(weekly, "now_london", lambda: NOW)
    monkeypatch.setattr(experiments, "ROOT", tmp_path / "repo")
    return w


def test_the_command_prints_the_run_as_json_and_writes_the_files(cli_world, tmp_path):
    r = CliRunner().invoke(app, ["review", "weekly", "--out-dir", str(tmp_path / "weekly-out")])
    assert r.exit_code == 0, r.output
    out = json.loads(r.stdout)
    assert out["week"] == "2026-10-12" and out["status"] == "ok" and len(out["digest"]["header"]) == 2 and out["run_id"]
    assert len(cli_world.store.list_runs(kind="weekly")) == 1 and len(cli_world.store.list_reviews()) == 3


def test_the_command_takes_an_iso_week_or_a_date(cli_world):
    for value in ("2026-W41", "2026-10-07"):  # the week of 5 Oct
        r = CliRunner().invoke(app, ["review", "weekly", "--week", value, "--dry-run"])
        assert r.exit_code == 0, r.output
        assert json.loads(r.stdout)["week"] == "2026-10-05"
    bad = CliRunner().invoke(app, ["review", "weekly", "--week", "last tuesday"])
    assert bad.exit_code == 2 and "week must be" in bad.output


def test_the_command_dry_run_writes_nothing(cli_world, tmp_path):
    r = CliRunner().invoke(app, ["review", "weekly", "--dry-run", "--out-dir", str(tmp_path / "x")])
    assert r.exit_code == 0 and json.loads(r.stdout)["dry_run"] is True
    assert cli_world.store.list_runs() == [] and cli_world.store.list_reviews() == [] and not (tmp_path / "x").exists()


def test_the_command_without_a_database_is_a_caller_error(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    r = CliRunner().invoke(app, ["review", "weekly"])
    assert r.exit_code == 2 and "DATABASE_URL" in r.output


# ---- the pull request link is confirmed once the branch is pushed (Task 16 parked, Task 20) ---------------------------------------------


COMPARE_12_OCT = "https://github.com/oschwend-prog/character-studio/compare/build/slice1...weekly/2026-10-12?expand=1"


def test_the_run_keeps_the_proposal_link_pending_and_confirm_proposal_publishes_it_once_the_branch_is_pushed(tmp_path):
    w = measured_world()
    out = run(w, tmp_path)
    (stored,) = w.store.list_runs(kind="weekly")
    assert stored.details["proposal_url"] is None and stored.details["proposal_pending_url"] == COMPARE_12_OCT  # what the Today card reads: no link yet
    done = weekly.confirm_proposal(w.store, out["run_id"])
    assert done == {"run_id": out["run_id"], "proposal_url": COMPARE_12_OCT, "confirmed": True}
    (after,) = w.store.list_runs(kind="weekly")
    assert after.details["proposal_url"] == COMPARE_12_OCT and after.details["week"] == "2026-10-12" and after.details["digest"] == stored.details["digest"]
    assert weekly.confirm_proposal(w.store, out["run_id"])["confirmed"] is False  # a rerun of the job changes nothing


def test_confirm_proposal_refuses_what_is_not_a_run_with_a_pending_link():
    from studio.models import Run, RunKind, RunStatus

    store = World().store

    def add(kind: RunKind, details: dict) -> str:
        return store.add_run(Run(kind=kind, status=RunStatus.ok, started_at=NOW, details=details)).id

    cases = {
        "not a run id": "not-a-uuid",
        "no such run": "00000000-0000-4000-8000-000000000000",
        "not a weekly run": add(RunKind.daily, {"proposal_pending_url": COMPARE_12_OCT}),
        "no pending proposal link": add(RunKind.weekly, {"proposal_pending_url": None, "proposal_url": None}),
    }
    forged = add(RunKind.weekly, {"proposal_pending_url": "https://evil.example/x"})  # only this repository's compare page is ever linked
    for why, run_id in [*cases.items(), ("no pending proposal link", forged)]:
        with pytest.raises(ValueError, match=why):
            weekly.confirm_proposal(store, run_id)
    assert all(r.details.get("proposal_url") is None for r in store.list_runs())


def test_the_confirm_command_prints_json_and_a_bad_run_is_a_caller_error(monkeypatch, tmp_path):
    w = measured_world()
    run_id = run(w, tmp_path)["run_id"]
    monkeypatch.setattr(weekly, "open_store", lambda: w.store)
    r = CliRunner().invoke(app, ["review", "confirm-proposal", "--run-id", run_id])
    assert r.exit_code == 0, r.output
    assert json.loads(r.stdout) == {"run_id": run_id, "proposal_url": COMPARE_12_OCT, "confirmed": True}
    assert w.store.list_runs(kind="weekly")[0].details["proposal_url"] == COMPARE_12_OCT
    bad = CliRunner().invoke(app, ["review", "confirm-proposal", "--run-id", "nope"])
    assert bad.exit_code == 2 and "not a run id" in bad.output


# ---- the pre-registered numbers are pinned ---------------------------------------------------------------------------------------------


def test_the_frozen_numbers_of_the_plan_are_pinned_and_match_the_test_registry():
    assert (weekly.SCORE_INTERIM_N, weekly.SCORE_FINAL_N) == (20, 40)
    assert (weekly.SCORE_INTERIM_VALIDATED_RHO, weekly.SCORE_INTERIM_FAILED_RHO, weekly.SCORE_FINAL_VALIDATED_RHO) == (0.45, 0.0, 0.31)
    assert (weekly.SCORE_MIN_SPAN, weekly.SCORE_BUCKET_WIDTH) == (15, 20)
    assert (weekly.FLOORS_FROM, weekly.FLOORS_TO, weekly.FLOORS_APPLY_FROM) == (date(2026, 10, 5), date(2026, 10, 18), date(2026, 10, 19))
    assert (weekly.FLOOR_MIN_OWN, weekly.FLOOR_MIN_STUDIO, weekly.FLOOR_FLAG_MIN) == (4, 6, 2)
    assert (weekly.DO_MORE_LIFT, weekly.DO_MORE_MIN_N, weekly.STOP_LIFT, weekly.STOP_MIN_N) == (1.5, 5, 0.7, 8)
    assert (weekly.RULE_READY_LIFT, weekly.CALL_MIN_POSTS, weekly.PLAYBOOK_MIN_POSTS) == (1.2, 10, 5)
    assert (weekly.ARM_RETIRE_MIN_USES, weekly.ARM_RETIRE_MAX_WIN_RATE, weekly.ARM_RETIRE_MAX_MEDIAN) == (10, 0.20, 0.7)
    reg = experiments.load_experiments(Path(__file__).resolve().parents[1] / "config" / "experiments.json")
    a = reg.test("A").params
    assert a["min_n"] == {"interim": weekly.SCORE_INTERIM_N, "final": weekly.SCORE_FINAL_N}
    assert a["decision"]["interim"] == {"validated_rho_at_least": weekly.SCORE_INTERIM_VALIDATED_RHO, "failed_rho_at_most": weekly.SCORE_INTERIM_FAILED_RHO}
    assert a["decision"]["final"] == {"validated_rho_at_least": weekly.SCORE_FINAL_VALIDATED_RHO}
    assert a["decision"]["uninformative_if_middle_80_percent_spans_under"] == weekly.SCORE_MIN_SPAN


def test_the_bar_thresholds_the_digest_quotes_are_the_codes_not_copies():
    from studio import review

    assert (review.CHARACTER_MIN_POSTS, review.CHARACTER_MIN_AGE.days) == (20, 28)  # the "9 of 20 posts, day 14 of 28" of the digest
    assert weekly.PROPOSAL_BASE == "build/slice1" and weekly.PROPOSAL_REPO == "https://github.com/oschwend-prog/character-studio"
