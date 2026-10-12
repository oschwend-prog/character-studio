"""The hook bandit (learning plan section 3.3, test B): the tally from the data, the draw with its guard rails, the choice at Make
it and ``studio learn arms``.

Everything runs on ``MemoryStore`` and tmp registries; the live registry (A and B on from 12 Oct 2026, C off: every post is a normal
Reel) comes in through the ``experiments_on`` fixture, and ``c_on`` is a tmp copy with test C switched on for the tests that need a
trial arm beside the hook. The simulations are seeded, so every statistical check here is deterministic.
"""

from __future__ import annotations

import copy
import json
import random
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from studio import clips, drop, experiments, learn
from studio.cli import app
from studio.config import LONDON
from studio.experiments import load_experiments, parse_experiments
from studio.learn import (
    BanditState,
    Counts,
    arm_counts,
    arms_report,
    bandit_state,
    cap_shares,
    choose_hook,
    draw_shares,
    floor_share,
    mix_floor,
    sample_order,
    thompson_shares,
)
from studio.models import Account, Body, Character, Clip, Favorite, Post, Snapshot
from studio.store import MemoryStore

REPO_REGISTRY = Path(__file__).resolve().parents[1] / "config" / "experiments.json"
START = datetime(2026, 10, 13, 12, 0, tzinfo=LONDON)  # a Tuesday: the first make day
H = timedelta(hours=1)
D = timedelta(days=1)
EPS = 1e-9


def reg():
    return load_experiments(REPO_REGISTRY)


@pytest.fixture
def c_on(tmp_path, monkeypatch):
    """A tmp copy of the repo's registry with test C on (the file has it off): the make path then draws the Trial Reel coin too."""
    data = json.loads(REPO_REGISTRY.read_text())
    data["tests"]["C"]["status"] = "on"
    path = tmp_path / "experiments.json"
    path.write_text(json.dumps(data))
    monkeypatch.setattr(experiments, "EXPERIMENTS_PATH", path)


def bandit_test():
    return reg().test("B")


# ---- the pieces of the draw ------------------------------------------------------------------------------------------------------------


def test_equal_tallies_split_the_draw_exactly_and_a_winner_draws_more():
    assert thompson_shares([Counts(), Counts(), Counts()], random.Random(1)) == [1 / 3] * 3  # with no data, every arm equally likely
    assert thompson_shares([Counts(2, 3)] * 4, random.Random(1)) == [0.25] * 4
    assert thompson_shares([], random.Random(1)) == []
    shares = thompson_shares([Counts(6, 1), Counts(1, 6), Counts(3, 3)], random.Random(7))
    assert abs(sum(shares) - 1) < EPS and shares[0] > shares[2] > shares[1] and shares[0] > 0.8
    assert shares == thompson_shares([Counts(6, 1), Counts(1, 6), Counts(3, 3)], random.Random(7))  # seeded: the same every time


def test_a_few_uses_make_a_wide_curve_so_a_new_arm_still_gets_tried():
    shares = thompson_shares([Counts(3, 0), Counts()], random.Random(3))
    assert 0.5 < shares[0] < 1 and shares[1] > 0.05  # 3-0 leads, but the untried arm keeps a real chance


def test_cap_shares_moves_the_excess_to_the_others_in_proportion():
    assert cap_shares([0.9, 0.05, 0.05], 0.6) == pytest.approx([0.6, 0.2, 0.2])
    got = cap_shares([0.8, 0.15, 0.05], 0.5)
    assert got == pytest.approx([0.5, 0.375, 0.125]) and abs(sum(got) - 1) < EPS
    assert cap_shares([0.5, 0.3, 0.2], 0.6) == [0.5, 0.3, 0.2]  # nothing above the cap: untouched
    assert cap_shares([1.0, 0.0], 0.6) == pytest.approx([0.6, 0.4])  # an arm with nothing is given equally
    two = cap_shares([0.97, 0.03, 0.0, 0.0], 0.6)
    assert max(two) <= 0.6 + EPS and abs(sum(two) - 1) < EPS
    assert cap_shares([1.0], 0.6) == [1.0] and cap_shares([0.7, 0.3], 0.6) == pytest.approx([0.6, 0.4])
    assert cap_shares([0.9, 0.1], 0.4) == [0.9, 0.1]  # two arms cannot both be under 40 %: the cap cannot hold, so it is not applied


def test_the_floor_is_part_of_every_draw_and_gives_each_arm_at_least_its_share():
    floor = {"3": 0.15, "4": 0.12}
    assert (floor_share(floor, 3), floor_share(floor, 4)) == (0.15, 0.12)
    assert floor_share(floor, 2) == 0.15  # no entry for 2 arms: the smallest listed count's share
    assert floor_share(floor, 6) == min(0.12, 1 / 6)
    for shares, share in (([1.0, 0.0, 0.0], 0.15), ([0.97, 0.01, 0.01, 0.01], 0.12), ([0.5, 0.5], 0.15)):
        mixed = mix_floor(shares, share)
        assert abs(sum(mixed) - 1) < EPS and min(mixed) >= share - EPS
    # 3 arms at 15 %: 45 % of every draw is a coin over the three, 55 % goes by the data
    assert mix_floor([1.0, 0.0, 0.0], 0.15) == pytest.approx([0.15 + 0.55, 0.15, 0.15])
    assert mix_floor([1 / 3] * 3, 0.15) == pytest.approx([1 / 3] * 3)  # an even draw stays even


def test_sample_order_is_a_permutation_by_the_shares_and_the_seed():
    names = ["a", "b", "c"]
    assert sorted(sample_order(names, [0.5, 0.3, 0.2], random.Random(0))) == names
    assert sample_order(names, [0.5, 0.3, 0.2], random.Random(5)) == sample_order(names, [0.5, 0.3, 0.2], random.Random(5))
    firsts = Counter(sample_order(names, [0.6, 0.3, 0.1], random.Random(i))[0] for i in range(3000))
    assert abs(firsts["a"] / 3000 - 0.6) < 0.03 and abs(firsts["b"] / 3000 - 0.3) < 0.03 and abs(firsts["c"] / 3000 - 0.1) < 0.03
    assert sample_order(["x"], [1.0], random.Random(1)) == ["x"] and sample_order([], [], random.Random(1)) == []
    assert sample_order(names, [0, 0, 0], random.Random(1)) != []  # no weight at all still gives an order


def test_an_arm_uses_the_characters_own_tally_once_it_has_enough_uses_else_the_studios():
    state = BanditState(
        by_character={("franz", "ego-claim"): Counts(2, 1), ("lenny", "ego-claim"): Counts(0, 4), ("franz", "myth-bust"): Counts(1, 0)},
        studio={"ego-claim": Counts(2, 5), "myth-bust": Counts(1, 0)},
    )
    assert arm_counts(state, "franz", "ego-claim", 3) == (Counts(2, 1), "character")  # 3 uses: his own
    assert arm_counts(state, "franz", "myth-bust", 3) == (Counts(1, 0), "studio")  # 1 use: the studio-wide tally of the pattern
    assert arm_counts(state, "franz", "when-relatable", 3) == (Counts(), "none")
    assert arm_counts(state, "lenny", "ego-claim", 3) == (Counts(0, 4), "character")


# ---- the tally from the data -----------------------------------------------------------------------------------------------------------


class World:
    """Reginald, Franz and Lenny, each with an Instagram account (Reginald a TikTok one too), and helpers to post clips with
    72-hour readings."""

    def __init__(self) -> None:
        self.store = MemoryStore()
        for slug in ("franz", "reginald", "lenny"):
            self.store.add_character(Character(slug=slug, name=slug.title(), bodies=[Body.biped]))
            self.store.add_account(Account(character_slug=slug, platform="instagram", handle=f"{slug}.ig"))
        self.store.add_account(Account(character_slug="reginald", platform="tiktok", handle="reginald.tt"))
        self.day = 0

    def account(self, slug: str, platform: str = "instagram") -> Account:
        return next(a for a in self.store.accounts(slug) if a.platform.value == platform)

    def post(self, slug: str, views_72h: int | None, *, platform: str = "instagram", features: dict[str, Any] | None = None,
             created: datetime | None = None, at: datetime | None = None) -> Clip:
        """A clip with its post on the character's account, posted ``at`` (a day after the one before by default) and read at 72 h."""
        self.day += 1
        when = at or datetime(2026, 10, 13, 18, 0, tzinfo=LONDON) + self.day * D
        clip = self.store.add_clip(Clip(character_slug=slug, mode="dropin", state="posted", features=features or {},
                                        created_at=created or when - 2 * D))
        post = self.store.add_post(Post(clip_id=clip.id, account_id=self.account(slug, platform).id, scheduled_for=when, claimed_at=when,
                                        status="posted", platform_post_id=f"pz-{clip.id[:8]}"))
        if views_72h is not None:
            self.store.add_snapshot(Snapshot(post_id=post.id, captured_at=when + 72 * H + H, views=views_72h))
        return clip

    def readings(self, slug: str, n: int = 3, views: int = 100, **kw: Any) -> None:
        """``n`` earlier posts (no hook) with a 72-hour reading of ``views``: the baseline a later post is read against."""
        for _ in range(n):
            self.post(slug, views, **kw)

    def hooked(self, slug: str, pattern: str, views_72h: int | None, by: str = "bandit", **kw: Any) -> Clip:
        return self.post(slug, views_72h, features={"hook_pattern": pattern, "hook_by": by}, **kw)


def state_of(w: World) -> BanditState:
    return bandit_state(w.store, reg())


def test_wins_and_losses_are_counted_from_x72_on_the_instagram_post():
    w = World()
    w.readings("reginald")  # 3 readings of 100: the baseline median is 100
    w.hooked("reginald", "understatement", 300)  # x72 3.0: a win
    w.hooked("reginald", "understatement", 150)  # a win
    w.hooked("reginald", "understatement", 40)  # a loss
    w.hooked("reginald", "false-premise", 100)  # exactly 1.0 beat nothing: a loss
    w.hooked("reginald", "false-premise", 900, by="studio")  # the check's first hook, nobody drew it: no use of the arm, win or not
    s = state_of(w)
    assert s.by_character[("reginald", "understatement")] == Counts(2, 1)
    assert s.by_character[("reginald", "false-premise")] == Counts(0, 1)
    assert s.studio["understatement"] == Counts(2, 1) and s.tallied("reginald") == 4
    assert s.readings["reginald"] == 8 and s.pending == {}  # (the studio-hook post still has its reading: a baseline for the next)


def test_only_a_hook_the_bandit_chose_is_tallied_not_the_checks_default_nor_the_owners():
    """Controller, 12 Oct (before data: 1 reading): the arm tally counts the clips whose hook the bandit really drew (``hook_by``
    ``bandit``, the warm-up rotation's draws included: the make records them the same way). A ``studio`` clip kept the check's first
    hook because no arm had a candidate: its pattern is Gemini's habit, not a draw, and counting it would bias the arms (and the
    studio-wide pool the other characters' arms lean on) towards what Gemini writes first."""
    assert learn.TALLIED_BY == ("bandit",)
    w = World()
    w.readings("franz")
    w.hooked("franz", "ego-claim", 300, by="studio")  # would be a win
    w.hooked("franz", "ego-claim", 20, by="studio")  # would be a loss
    w.hooked("franz", "ego-claim", None, by="studio")  # would wait for its reading
    w.hooked("franz", "ego-claim", 300, by="owner")
    s = state_of(w)
    assert s.by_character == {} and s.studio == {} and s.pending == {} and s.tallied("franz") == 0
    w.hooked("franz", "ego-claim", 300)
    w.hooked("franz", "ego-claim", None)
    s = state_of(w)
    assert s.by_character == {("franz", "ego-claim"): Counts(1, 0)} and s.studio == {"ego-claim": Counts(1, 0)}
    assert s.pending == {"franz": 1}  # only the bandit's unread clip waits
    # the draw reads the same tally: the studio-hook clips moved no arm
    assert arm_counts(s, "franz", "ego-claim", 3) == (Counts(1, 0), "studio")


def test_the_owners_hook_a_missing_label_a_missing_reading_and_the_time_before_the_start_are_not_tallied():
    w = World()
    w.readings("reginald")
    w.hooked("reginald", "understatement", 300, by="owner")  # his own hook never changes the tally
    w.hooked("reginald", "owner", 300)  # pattern "owner": not an arm
    w.hooked("reginald", "none", 300)  # a hook nobody labelled
    w.hooked("reginald", "understatement", None)  # no 72-hour reading: neither a win nor a loss
    w.hooked("reginald", "understatement", 300, created=datetime(2026, 10, 10, 9, 0, tzinfo=LONDON))  # made before the test began
    w.post("reginald", 300, features={"hook_pattern": "understatement"})  # no hook_by (made before the labels)
    s = state_of(w)
    assert s.by_character == {} and s.studio == {}
    assert s.pending == {"reginald": 1}  # only the unread one of the tally's kind waits for its reading
    assert s.tallied("reginald") == 0


def test_the_first_posts_of_an_account_have_no_x72_so_nothing_can_be_tallied():
    w = World()
    w.hooked("reginald", "understatement", 300)  # the account's first post: no baseline
    w.hooked("reginald", "understatement", 300)
    assert state_of(w).by_character == {} and state_of(w).pending == {"reginald": 2} and state_of(w).readings == {"reginald": 2}


def test_only_instagram_counts():
    w = World()
    w.readings("reginald", platform="tiktok")
    w.hooked("reginald", "understatement", 900, platform="tiktok")  # a TikTok post: one observation is a clip on Instagram
    assert state_of(w).by_character == {} and state_of(w).readings == {}
    w.readings("reginald")
    w.hooked("reginald", "understatement", 900)
    assert state_of(w).by_character == {("reginald", "understatement"): Counts(1, 0)}


def test_the_studio_tally_pools_a_pattern_over_the_characters():
    w = World()
    for slug in ("franz", "lenny"):
        w.readings(slug)
        w.hooked(slug, "ego-claim", 500)
    w.readings("franz")
    w.hooked("franz", "ego-claim", 20)
    s = state_of(w)
    assert s.studio["ego-claim"] == Counts(2, 1)
    assert s.by_character[("franz", "ego-claim")] == Counts(1, 1) and s.by_character[("lenny", "ego-claim")] == Counts(1, 0)


# ---- the draw's shares ------------------------------------------------------------------------------------------------------------------


def test_until_three_readings_the_patterns_rotate_and_every_arm_is_equally_likely():
    t = bandit_test()
    d = draw_shares(t, BanditState(readings={"reginald": 2}), reg().seed, "reginald")
    assert d.warmup and d.arms == ("false-premise", "understatement", "trend-label") and d.shares == (1 / 3,) * 3
    assert not draw_shares(t, BanditState(readings={"reginald": 3}), reg().seed, "reginald").warmup


def test_with_no_data_after_the_warm_up_every_arm_is_equally_likely():
    d = draw_shares(bandit_test(), BanditState(readings={"franz": 5}), reg().seed, "franz")
    assert not d.warmup and d.shares == pytest.approx((0.25,) * 4) and d.thompson == (0.25,) * 4


def test_a_winning_pattern_draws_more_but_never_above_the_ceiling_before_30_tallied_posts():
    state = BanditState(
        by_character={("lenny", "mid-deal"): Counts(9, 0), ("lenny", "when-relatable"): Counts(0, 5), ("lenny", "ego-claim"): Counts(0, 4),
                      ("lenny", "trend-label"): Counts(0, 3)},
        readings={"lenny": 40},
    )
    d = draw_shares(bandit_test(), state, reg().seed, "lenny")
    assert d.ceiling_applies and d.thompson[0] > 0.95
    assert d.shares[0] <= 0.6 + EPS and d.shares[0] == pytest.approx(max(d.shares))  # capped at 60 %, still the favourite
    assert min(d.shares) >= 0.12 - EPS and abs(sum(d.shares) - 1) < EPS  # the floor of 4 arms
    # ... and with 30 tallied posts the ceiling goes: the early luck has had its chance to wash out
    state30 = BanditState(by_character={**state.by_character, ("lenny", "mid-deal"): Counts(27, 0)}, readings={"lenny": 60})
    d30 = draw_shares(bandit_test(), state30, reg().seed, "lenny")
    assert state30.tallied("lenny") == 39 and not d30.ceiling_applies
    assert d30.shares[0] > 0.6 and min(d30.shares) >= 0.12 - EPS


def test_every_arm_keeps_at_least_its_floor_whatever_the_data_say():
    for arms, slug in ((3, "reginald"), (4, "franz")):
        patterns = bandit_test().arms[slug]
        by_char = {(slug, patterns[0]): Counts(30, 0), **{(slug, p): Counts(0, 12) for p in patterns[1:]}}
        d = draw_shares(bandit_test(), BanditState(by_character=by_char, readings={slug: 50}), reg().seed, slug)
        assert len(d.arms) == arms and min(d.shares) >= (0.15 if arms == 3 else 0.12) - EPS and abs(sum(d.shares) - 1) < EPS


def test_trend_label_is_an_arm_only_for_a_clip_with_a_moment_name():
    t = bandit_test()
    with_moment = draw_shares(t, BanditState(readings={"lenny": 9}), reg().seed, "lenny")
    without = draw_shares(t, BanditState(readings={"lenny": 9}), reg().seed, "lenny", moment=False)
    assert "trend-label" in with_moment.arms and without.arms == ("mid-deal", "when-relatable", "ego-claim")
    assert without.shares == pytest.approx((1 / 3,) * 3)
    assert learn.arms_of(t, "nobody") == ()
    assert draw_shares(t, BanditState(), reg().seed, "nobody").arms == ()


# ---- the choice at Make it ---------------------------------------------------------------------------------------------------------------


HOOKS = ["The household is unaware.", "Breakfast is at eight.", "Kindly do not tell the Duchess."]


def choose(w_or_store, slug="reginald", patterns=("understatement", "false-premise", "understatement"), pick="p1", moment=True,
           now=START, registry=None, hooks=HOOKS, state=None):
    store = w_or_store.store if isinstance(w_or_store, World) else w_or_store
    return choose_hook(store, registry or reg(), slug, pick, hooks, list(patterns), moment=moment, now=now, state=state)


def test_the_warm_up_rotates_in_the_registry_order_and_the_candidate_of_the_drawn_pattern_goes_on_screen():
    w = World()
    first = choose(w)
    # Reginald's arms are false-premise, understatement, trend-label; the first place draws false-premise: the 2nd candidate
    assert (first.pattern, first.index, first.hook, first.warmup) == ("false-premise", 1, "Breakfast is at eight.", True)
    assert first.order == ("false-premise", "understatement", "trend-label")
    w.post("reginald", None, features={"test_arms": {"hook": "false-premise"}})  # one clip carries a hook arm: the next place
    second = choose(w, pick="p2")
    assert (second.pattern, second.index) == ("understatement", 0) and second.order[0] == "understatement"
    w.post("reginald", None, features={"test_arms": {"hook": "understatement"}})
    third = choose(w, pick="p3")  # trend-label is next but no candidate has it: the next of the rotation that has one
    assert third.order == ("trend-label", "false-premise", "understatement") and third.pattern == "false-premise"


def test_the_first_candidate_of_a_pattern_wins_when_two_carry_it():
    c = choose(World(), patterns=("understatement", "understatement", "understatement"))
    assert (c.pattern, c.index) == ("understatement", 0)
    c = choose(World(), patterns=("false-premise", "false-premise", "understatement"), pick="p9")
    assert (c.pattern, c.index) == ("false-premise", 0)


def test_the_next_best_pattern_with_a_candidate_is_used_when_the_drawn_one_has_none():
    c = choose(World(), patterns=("understatement", "understatement", "understatement"))  # the draw starts at false-premise: no candidate
    assert c.order[0] == "false-premise" and c.pattern == "understatement"


def test_no_choice_when_no_arm_has_a_candidate_or_the_hooks_are_not_labelled():
    w = World()
    assert choose(w, patterns=("mid-deal", "ego-claim", "myth-bust")) is None  # none of Reginald's arms
    assert choose(w, patterns=(None, None, None)) is None and choose(w, patterns=()) is None  # a check made before the labels
    assert choose(w, patterns=("trend-label", "mid-deal", "mid-deal"), moment=False) is None  # trend-label needs a moment name
    assert choose(w, patterns=("trend-label", "mid-deal", "mid-deal"), moment=True).pattern == "trend-label"
    assert choose(w, slug="biscuit") is None  # a character with no arms
    assert choose(w, hooks=["", " ", ""]) is None  # blank candidates are no candidates


def test_no_choice_while_test_b_is_off_or_before_it_starts():
    w = World()
    assert choose(w, now=datetime(2026, 10, 11, 12, 0, tzinfo=LONDON)) is None
    off = parse_experiments({**copy.deepcopy(json.loads(REPO_REGISTRY.read_text())), "tests": {
        **json.loads(REPO_REGISTRY.read_text())["tests"], "B": {**json.loads(REPO_REGISTRY.read_text())["tests"]["B"], "status": "off"}}})
    assert choose(w, registry=off) is None


def test_the_same_pick_and_data_always_give_the_same_choice():
    w = World()
    w.readings("reginald", 5)
    w.hooked("reginald", "understatement", 300)
    again = [choose(w, pick="same", patterns=("understatement", "false-premise", "trend-label")) for _ in range(5)]
    assert len({(c.pattern, c.order) for c in again}) == 1 and not again[0].warmup
    assert choose(w, pick="other", patterns=("understatement", "false-premise", "trend-label")) is not None


def test_over_many_picks_the_draw_follows_the_data_and_keeps_every_arm_alive():
    """Reginald, past the warm-up: false-premise has won 8 of 8, understatement lost 6 of 6, trend-label has no data. The
    candidates carry all three patterns, so the first of the order is the choice."""
    w = World()
    state = BanditState(
        by_character={("reginald", "false-premise"): Counts(8, 0), ("reginald", "understatement"): Counts(0, 6)}, readings={"reginald": 20},
    )
    picks = Counter(
        choose(w.store, pick=f"pick-{i}", patterns=("false-premise", "understatement", "trend-label"), state=state).pattern
        for i in range(1200)
    )
    assert picks["false-premise"] > picks["trend-label"] > picks["understatement"]
    assert picks["false-premise"] / 1200 <= 0.6 + 0.04  # the ceiling (60 %: 14 tallied posts, under 30)
    assert min(picks.values()) / 1200 >= 0.15 - 0.03  # the floor of 3 arms (15 %)


def test_with_no_data_after_the_warm_up_the_patterns_come_out_about_equally():
    w = World()
    state = BanditState(readings={"franz": 9})
    picks = Counter(
        choose(w.store, slug="franz", pick=f"pick-{i}", patterns=("ego-claim", "when-relatable", "myth-bust"), state=state).pattern
        for i in range(900)
    )
    assert set(picks) == {"ego-claim", "when-relatable", "myth-bust"} and all(abs(n / 900 - 1 / 3) < 0.05 for n in picks.values())


def test_choice_as_dict_is_plain_json():
    c = choose(World())
    out = c.as_dict()
    assert json.loads(json.dumps(out)) == out and set(out) == {"pattern", "index", "hook", "order", "warmup"}


# ---- studio learn arms -------------------------------------------------------------------------------------------------------------------


def test_the_arms_report_shows_wins_losses_and_the_draw_for_every_character():
    w = World()
    w.readings("reginald")
    w.hooked("reginald", "understatement", 300)
    w.hooked("reginald", "understatement", 10)
    w.hooked("reginald", "false-premise", 200)
    report = arms_report(w.store, reg(), START)
    assert json.loads(json.dumps(report)) == report
    assert report["test"] == {"id": "B", "status": "on", "active": True, "start": "2026-10-12"}
    assert [c["character"] for c in report["characters"]] == ["franz", "reginald", "lenny"]
    r = next(c for c in report["characters"] if c["character"] == "reginald")
    assert (r["mode"], r["readings"], r["readings_needed"], r["tallied"]) == ("thompson", 6, 3, 3)
    arms = {a["pattern"]: a for a in r["arms"]}
    assert (arms["understatement"]["wins"], arms["understatement"]["losses"], arms["understatement"]["uses"]) == (1, 1, 2)
    assert arms["false-premise"]["wins"] == 1 and arms["trend-label"]["uses"] == 0
    assert arms["understatement"]["tally"] == {"wins": 1, "losses": 1, "basis": "studio"}  # 2 uses of 3: the studio-wide tally (the same here)
    assert abs(sum(a["draw"] for a in r["arms"]) - 1) < 0.001 and all(a["draw"] >= 0.15 - 0.001 for a in r["arms"])
    assert arms["trend-label"]["needs_moment_name"] and arms["trend-label"]["draw_without_moment_name"] is None
    assert arms["understatement"]["draw_without_moment_name"] is not None
    assert r["ceiling"] == {"share": 0.6, "applies": True, "until_tallied": 30} and r["floor"] == 0.15
    franz = next(c for c in report["characters"] if c["character"] == "franz")
    assert franz["mode"] == "rotation" and all(a["draw"] == pytest.approx(0.25) for a in franz["arms"])  # no readings yet: warm-up


def test_the_arms_report_for_one_character_and_for_an_unknown_one():
    w = World()
    assert [c["character"] for c in arms_report(w.store, reg(), START, character="lenny")["characters"]] == ["lenny"]
    with pytest.raises(ValueError, match="'biscuit' has no hook arms"):
        arms_report(w.store, reg(), START, character="biscuit")


@pytest.fixture
def cli_world(monkeypatch, experiments_on):
    w = World()
    monkeypatch.setattr(learn, "open_store", lambda: w.store)
    monkeypatch.setattr(learn, "now_london", lambda: START)
    return w


def test_cli_arms_prints_json_for_everyone_or_one_character(cli_world):
    r = CliRunner().invoke(app, ["learn", "arms"])
    assert r.exit_code == 0, r.output
    assert [c["character"] for c in json.loads(r.stdout)["characters"]] == ["franz", "reginald", "lenny"]
    r = CliRunner().invoke(app, ["learn", "arms", "--character", "franz"])
    assert r.exit_code == 0 and [c["character"] for c in json.loads(r.stdout)["characters"]] == ["franz"]
    r = CliRunner().invoke(app, ["learn", "arms", "--character", "nobody"])
    assert r.exit_code == 2 and "no hook arms" in r.output


def test_cli_arms_is_read_only(cli_world):
    cli_world.readings("reginald")
    cli_world.hooked("reginald", "understatement", 300)
    before = (len(cli_world.store.list_clips()), len(cli_world.store.list_posts()), [c.features for c in cli_world.store.list_clips()])
    assert CliRunner().invoke(app, ["learn", "arms"]).exit_code == 0
    assert before == (len(cli_world.store.list_clips()), len(cli_world.store.list_posts()), [c.features for c in cli_world.store.list_clips()])


def test_cli_arms_with_a_broken_registry_is_a_caller_error(cli_world, tmp_path, monkeypatch):
    bad = tmp_path / "experiments.json"
    bad.write_text("nope")
    monkeypatch.setattr(experiments, "EXPERIMENTS_PATH", bad)
    r = CliRunner().invoke(app, ["learn", "arms"])
    assert r.exit_code == 2 and "experiments" in r.output


# ---- at Make it: the hook that is made, tagged and rendered ------------------------------------------------------------------------------


LOOK = {
    "setting": "a corridor", "moment_name": "shoulder shimmy", "classic": False, "people_count": 1, "caption": {},
    "hooks": HOOKS, "hook_patterns": ["understatement", "false-premise", "understatement"], "first_comment": "x",
}


def add_pick(store: MemoryStore, slug: str = "reginald", look: dict[str, Any] | None = None, adjust: dict[str, Any] | None = None,
             score: int = 70) -> Favorite:
    look = look or LOOK
    d: dict[str, Any] = {
        "state": "making", "kind": "file", "classic": False, "has_audio": True, "music": "original", "hit_rules_version": "v1",
        "window": {"start_s": 0.0, "length_s": 8.0}, "star": {"description": "the man in the grey suit", "body": "biped"},
        "part": "featured", "gadgets": [], "hook": look["hooks"][0], "hooks": look["hooks"], "deconstruct": look,
        "score": {"total": score, "potential": 7, "swap": 8, "reason": "x"},
    }
    if adjust is not None:
        d["adjust"] = adjust
    return store.add_favorite(
        Favorite(url=f"owner-drop:{len(store.list_favorites())}", platform="drop", origin="owner", character_slug=slug,
                 proposal={"drop": d, "make_requested": {"at": START.isoformat(), "by": "owner"}}, status="approved")
    )


def made(store: MemoryStore, pick: Favorite) -> Clip:
    return drop._new_or_current_clip(store, store.get_favorite(pick.id), START)


def test_the_made_clip_carries_the_drawn_pattern_its_hook_and_who_chose_it(experiments_on):
    store = World().store
    pick = add_pick(store)
    clip = made(store, pick)
    f = store.get_clip(clip.id).features
    # test C is off in the repo's registry: no trial arm; tests G and H (the edit tests) are on and the clip has its own sound
    assert set(f["test_arms"]) == {"hook", "zoom", "word_pop"} and f["test_arms"]["hook"] == "false-premise"
    assert (f["hook_pattern"], f["hook_index"], f["hook_by"], f["hook_text"]) == ("false-premise", 2, "bandit", "Breakfast is at eight.")
    assert clips.learn_problems(f) == []
    bandit = drop.drop_of(store.get_favorite(pick.id))["make"]["bandit"]
    assert bandit["pattern"] == "false-premise" and bandit["hook"] == "Breakfast is at eight." and bandit["index"] == 1
    # the master renders the same hook (drop.effective reads the make record) and re-tags it the same way
    d = drop.drop_of(store.get_favorite(pick.id))
    eff = drop.effective(d)
    assert eff["hook"] == "Breakfast is at eight."
    assert drop._hook_tags(d, LOOK, eff["hook"]) == {"hook_pattern": "false-premise", "hook_index": 2, "hook_by": "bandit"}


def test_the_next_clips_follow_the_rotation_through_the_warm_up(experiments_on):
    store = World().store
    patterns = []
    for _ in range(4):
        patterns.append(store.get_clip(made(store, add_pick(store)).id).features["test_arms"]["hook"])
    # arms false-premise, understatement, trend-label; the candidates carry the first two only: trend-label's place falls through
    assert patterns[:2] == ["false-premise", "understatement"]
    assert patterns[2] in ("false-premise", "understatement") and patterns[3] in ("false-premise", "understatement")


FOUR_LOOK = {
    **LOOK,
    "hooks": ["I invented this walk.", "When the hallway is your runway.", "They said a dog cannot do this.", "The shoulder shimmy, as ordered."],
    "hook_patterns": ["ego-claim", "when-relatable", "myth-bust", "trend-label"],
}


def test_with_one_hook_per_arm_every_arm_has_a_candidate_and_the_fourth_hook_is_tagged_four(experiments_on):
    """Franz has four arms; the check now writes four hooks. The warm-up rotation puts each on screen in turn, no clip falls back to
    the check's first hook, and the fourth hook is ``hook_index`` 4 (a range of 0-3 would have refused the clip)."""
    store = World().store
    seen = []
    for _ in range(4):
        f = store.get_clip(made(store, add_pick(store, slug="franz", look=FOUR_LOOK)).id).features
        assert f["hook_by"] == "bandit" and clips.learn_problems(f) == []
        seen.append((f["test_arms"]["hook"], f["hook_index"], f["hook_text"]))
    assert seen == [(p, i + 1, h) for i, (p, h) in enumerate(zip(FOUR_LOOK["hook_patterns"], FOUR_LOOK["hooks"], strict=True))]


def test_the_owners_own_hook_always_wins_and_is_not_drawn(experiments_on):
    store = World().store
    pick = add_pick(store, adjust={"hook": "Tea is at four."})
    f = store.get_clip(made(store, pick).id).features
    assert (f["hook_by"], f["hook_pattern"], f["hook_index"], f["hook_text"]) == ("owner", "owner", 0, "Tea is at four.")
    assert "hook" not in f["test_arms"] and "bandit" not in (drop.drop_of(store.get_favorite(pick.id)).get("make") or {})
    second = add_pick(store, adjust={"hook": "Kindly do not tell the Duchess."})  # his pick of the check's third candidate: still his
    f2 = store.get_clip(made(store, second).id).features
    assert f2["hook_by"] == "owner" and f2["hook_pattern"] == "understatement" and "hook" not in f2["test_arms"]
    assert drop.effective(drop.drop_of(store.get_favorite(second.id)))["hook"] == "Kindly do not tell the Duchess."


def test_an_explicit_choice_of_the_checks_first_hook_is_the_owners_and_the_bandit_never_swaps_it(experiments_on):
    """I3: he picked hook #1 in Adjust (the terminal sends a hook he touched even when it is the check's first): his choice."""
    store = World().store
    pick = add_pick(store, adjust={"hook": " the household is UNAWARE. ", "part": "star"})
    f = store.get_clip(made(store, pick).id).features
    assert (f["hook_by"], f["hook_index"], f["hook_pattern"], f["hook_text"]) == ("owner", 1, "understatement", "the household is UNAWARE.")
    assert "hook" not in f["test_arms"] and "bandit" not in (drop.drop_of(store.get_favorite(pick.id)).get("make") or {})
    d = drop.drop_of(store.get_favorite(pick.id))
    assert drop.effective(d)["hook"] == "the household is UNAWARE." and clips.learn_problems(f) == []
    # it is not tallied for the bandit either: only its own draws are
    assert drop.owner_chose_hook(d) and not drop.owner_chose_hook(drop.drop_of(add_pick(store)))


def test_an_adjust_that_never_touched_the_hook_leaves_it_to_the_bandit(experiments_on):
    """The other side: no hook in the Adjust (he changed only the part) means no choice, so the bandit still draws."""
    store = World().store
    pick = add_pick(store, adjust={"part": "star"})
    f = store.get_clip(made(store, pick).id).features
    assert f["hook_by"] == "bandit" and f["test_arms"]["hook"] == "false-premise" and f["hook_text"] == "Breakfast is at eight."
    assert drop.effective(drop.drop_of(store.get_favorite(pick.id)))["hook"] == "Breakfast is at eight."
    assert not drop.owner_chose_hook(drop.drop_of(store.get_favorite(pick.id)))


@pytest.mark.parametrize("broken", ["bandit_state", "choose_hook"])
def test_a_fault_in_the_hook_bandit_never_blocks_a_make(c_on, monkeypatch, caplog, broken):
    """Minor 1: the clip is made with the check's first hook (hook_by studio) and the other tests still assign."""
    def boom(*a, **k):
        raise ValueError("the bandit broke")

    monkeypatch.setattr(learn, broken, boom)
    store = World().store
    pick = add_pick(store)
    with caplog.at_level("WARNING", logger="studio.drop"):
        f = store.get_clip(made(store, pick).id).features
    assert (f["hook_by"], f["hook_index"], f["hook_text"]) == ("studio", 1, HOOKS[0])
    assert "hook" not in f["test_arms"] and isinstance(f["test_arms"]["trial"], bool)
    assert "hook bandit failed" in caplog.text and "bandit" not in (drop.drop_of(store.get_favorite(pick.id)).get("make") or {})


def test_the_registry_and_the_draw_refuse_a_naive_time(experiments_on):
    """Minor 6: a naive `now` is never read as machine-local time."""
    naive = datetime(2026, 10, 12, 12, 0)
    with pytest.raises(ValueError, match="timezone-aware"):
        reg().active(naive)
    with pytest.raises(ValueError, match="timezone-aware"):
        reg().is_active("B", naive)
    with pytest.raises(ValueError, match="timezone-aware"):
        choose(World(), now=naive)


def test_a_check_with_no_arm_pattern_keeps_the_first_hook_and_draws_nothing(experiments_on):
    store = World().store
    look = {**LOOK, "hook_patterns": ["mid-deal", "ego-claim", "myth-bust"]}  # none of Reginald's arms
    f = store.get_clip(made(store, add_pick(store, look=look)).id).features
    assert (f["hook_by"], f["hook_index"], f["hook_text"], f["hook_pattern"]) == ("studio", 1, HOOKS[0], "mid-deal")
    assert "hook" not in f["test_arms"]
    old = {k: v for k, v in LOOK.items() if k != "hook_patterns"}  # a drop checked before the labels
    g = store.get_clip(made(store, add_pick(store, look=old)).id).features
    assert (g["hook_by"], g["hook_pattern"], g["hook_text"]) == ("studio", "none", HOOKS[0]) and "hook" not in g["test_arms"]


def test_trend_label_needs_a_moment_name_at_make(experiments_on):
    store = World().store
    look = {**LOOK, "moment_name": "", "hook_patterns": ["trend-label", "trend-label", "trend-label"]}
    f = store.get_clip(made(store, add_pick(store, look=look)).id).features
    assert f["hook_by"] == "studio" and f["hook_pattern"] == "trend-label" and "hook" not in f["test_arms"]
    named = {**LOOK, "hook_patterns": ["trend-label", "trend-label", "trend-label"]}
    g = store.get_clip(made(store, add_pick(store, look=named)).id).features
    assert g["hook_by"] == "bandit" and g["test_arms"]["hook"] == "trend-label"


def test_a_character_with_no_arms_is_made_exactly_as_before(experiments_on):
    w = World()
    w.store.add_character(Character(slug="biscuit", name="Biscuit", bodies=[Body.biped]))
    f = w.store.get_clip(made(w.store, add_pick(w.store, slug="biscuit")).id).features
    assert (f["hook_by"], f["hook_index"], f["hook_text"]) == ("studio", 1, HOOKS[0]) and "hook" not in f["test_arms"]


def test_a_pick_made_again_keeps_its_clip_and_its_drawn_hook(experiments_on):
    store = World().store
    pick = add_pick(store)
    first = made(store, pick)
    again = made(store, store.get_favorite(pick.id))
    assert again.id == first.id and len(store.list_clips()) == 1
    assert store.get_clip(first.id).features["hook_text"] == "Breakfast is at eight."


def test_with_test_b_off_the_hook_is_the_checks_first_as_before(tmp_path, monkeypatch):
    data = json.loads(REPO_REGISTRY.read_text())
    data["tests"]["B"]["status"] = "off"
    data["tests"]["C"]["status"] = "on"  # the file has C off; the other tests still assign, which this checks
    path = tmp_path / "experiments.json"
    path.write_text(json.dumps(data))
    monkeypatch.setattr(experiments, "EXPERIMENTS_PATH", path)
    store = World().store
    f = store.get_clip(made(store, add_pick(store)).id).features
    assert (f["hook_by"], f["hook_index"], f["hook_text"]) == ("studio", 1, HOOKS[0]) and "hook" not in f["test_arms"]
    assert "trial" in f["test_arms"]  # test C is still on in this registry (switched on above)


def test_the_tally_reads_what_was_made(experiments_on):
    """A clip made by the bandit and posted becomes a win or a loss once its Instagram post has an x72."""
    w = World()
    store = w.store
    clip = store.get_clip(made(store, add_pick(store)).id)
    pattern = clip.features["hook_pattern"]
    assert clip.features["hook_by"] == "bandit"
    w.readings("reginald")
    post_at = START + 5 * D
    store.update_clip(clip.id, state="posted")
    post = store.add_post(Post(clip_id=clip.id, account_id=w.account("reginald").id, scheduled_for=post_at, claimed_at=post_at,
                               status="posted", platform_post_id="pz-x"))
    assert bandit_state(store, reg()).pending == {"reginald": 1}
    store.add_snapshot(Snapshot(post_id=post.id, captured_at=post_at + 73 * H, views=400))
    assert bandit_state(store, reg()).by_character[("reginald", pattern)] == Counts(1, 0)
