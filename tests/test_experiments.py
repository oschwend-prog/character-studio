"""The test registry (``config/experiments.json``), its block coins and test A's exploration tag, and the make path that writes them
on a clip (learning plan sections 3.0-3.4, build item 7).

The registry file itself is pinned: the owner's decisions of Mon 12 Oct 2026 (A and B on; C off since the owner chose normal Reels
for every post; D, E and F off) are the file's, and a change to them is a new dated version of the plan. Everything else runs on
``MemoryStore`` and tmp registries; ``conftest`` points every other test at an all-off copy. The tests of test C's mechanics (the
block coin, its place in the block, the trial arm on a made clip) build their own registry with C on (``c_on_registry`` /
``c_on``): they keep testing the coin although the repo's file has it off.
"""

from __future__ import annotations

import copy
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from studio import clips, drop, experiments
from studio.config import LONDON
from studio.experiments import (
    Registry,
    assign_blocks,
    block_arm,
    block_order,
    block_position,
    is_explore,
    load_experiments,
    parse_experiments,
)
from studio.models import Body, Character, Clip, ClipState, Favorite, HOOK_PATTERNS
from studio.publish.reach import load_reach
from studio.store import MemoryStore

REPO_REGISTRY = Path(__file__).resolve().parents[1] / "config" / "experiments.json"
START = datetime(2026, 10, 12, 9, 0, tzinfo=LONDON)
DATA: dict[str, Any] = json.loads(REPO_REGISTRY.read_text(encoding="utf-8"))


def registry(**over: Any) -> Registry:
    """The repo's registry with top-level keys replaced (``tests`` as a whole, or deep-edited by ``edit``)."""
    return parse_experiments({**copy.deepcopy(DATA), **over})


def edit(path: str, value: Any) -> dict[str, Any]:
    """The repo's registry data with ``a.b.c`` set to ``value`` (a ``Ellipsis`` value removes the key)."""
    data = copy.deepcopy(DATA)
    *parents, last = path.split(".")
    node = data
    for key in parents:
        node = node[key]
    if value is ...:
        del node[last]
    else:
        node[last] = value
    return data


def c_on_data() -> dict[str, Any]:
    """The repo's registry data with test C switched on: the file has it off (owner 12 Oct), its mechanics are still tested."""
    return edit("tests.C.status", "on")


def c_on_registry() -> Registry:
    return parse_experiments(c_on_data())


@pytest.fixture
def c_on(tmp_path, monkeypatch) -> Registry:
    """The make path reads a tmp copy of the repo's registry with test C on (A and B stay on, D-F off)."""
    path = tmp_path / "experiments.json"
    path.write_text(json.dumps(c_on_data()), encoding="utf-8")
    monkeypatch.setattr(experiments, "EXPERIMENTS_PATH", path)
    return load_experiments(path)


# ---- the file in the repo ------------------------------------------------------------------------------------------------------------


def test_the_repos_registry_loads_and_holds_the_owners_decisions_of_12_oct():
    reg = load_experiments(REPO_REGISTRY)
    assert reg.version == 1 and str(reg.start) == "2026-10-12" and reg.seed
    assert {t: reg.test(t).status for t in "ABCDEF"} == {"A": "on", "B": "on", "C": "off", "D": "off", "E": "off", "F": "off"}
    assert {t: reg.test(t).assignment for t in "ABCDEF"} == {
        "A": "tag", "B": "bandit", "C": "block_coin", "D": "block_coin", "E": "block_coin", "F": "block_coin",
    }
    assert [t.id for t in reg.active(START)] == ["A", "B"]
    assert {t: reg.test(t).key for t in "BCDEF"} == {"B": "hook", "C": "trial", "D": "own_series", "E": "length", "F": "comment"}


def test_the_default_path_is_the_repos_file(experiments_on):
    assert Path(experiments.EXPERIMENTS_PATH) == REPO_REGISTRY
    assert not load_experiments().test("C").on  # the owner posts every video as a normal Reel


def test_the_hook_arms_are_the_plans_fits_column():
    arms = load_experiments(REPO_REGISTRY).test("B").arms
    assert arms == {
        "franz": ("ego-claim", "when-relatable", "myth-bust", "trend-label"),
        "reginald": ("false-premise", "understatement", "trend-label"),
        "lenny": ("mid-deal", "when-relatable", "ego-claim", "trend-label"),
    }
    assert all(p in HOOK_PATTERNS for patterns in arms.values() for p in patterns)


def test_the_bandits_guard_rails_and_test_cs_block_are_the_plans():
    b, c = load_experiments(REPO_REGISTRY).test("B").params, load_experiments(REPO_REGISTRY).test("C")
    assert (b["warmup_priors"], b["floor"], b["ceiling"], b["ceiling_until_tallied"]) == (3, {"3": 0.15, "4": 0.12}, 0.6, 30)
    assert (c.block, c.arms, dict(c.counts)) == (4, (True, False), {True: 2, False: 2})  # 2 trial and 2 normal in every 4
    assert c.params["min_n"] == {"trial": 10, "normal": 10, "per_account_each": 3}


def test_the_conftest_registry_has_every_test_off():
    assert load_experiments().active(START) == []  # what every other test sees


# ---- validation: a broken file stops the run, naming the key ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("path", "value", "message"),
    [
        ("version", 0, "version"),
        ("version", "1", "version"),
        ("start", "12 October", "start"),
        ("start", None, "start"),
        ("seed", "", "seed"),
        ("seed", 7, "seed"),
        ("tests.A.status", "maybe", r"tests\.A\.status"),
        ("tests.A.name", "", r"tests\.A\.name"),
        ("tests.A.assignment", "dice", r"tests\.A\.assignment"),
        ("tests.A.min_n", {}, r"tests\.A\.min_n"),
        ("tests.A.min_n", {"interim": 0}, r"tests\.A\.min_n"),
        ("tests.A.explore.every", 1, r"tests\.A\.explore\.every"),
        ("tests.A.explore", ..., r"tests\.A\.explore\.every"),
        ("tests.C.key", "", r"tests\.C\.key"),
        ("tests.C.key", ..., r"tests\.C\.key"),
        ("tests.C.block", 3, r"tests\.C\.block"),  # 3 places cannot be shared equally by 2 arms
        ("tests.C.block", 0, r"tests\.C\.block"),
        ("tests.C.block", True, r"tests\.C\.block"),
        ("tests.C.arms", [True], r"tests\.C\.arms"),
        ("tests.C.arms", [True, True], r"tests\.C\.arms"),
        ("tests.C.arms", "trial", r"tests\.C\.arms"),
        ("tests.C.arms", [True, ""], r"tests\.C\.arms"),
        ("tests.D.arms", {"own": 1, "swap": 1}, r"tests\.D\.arms"),  # adds up to 2, the block has 3
        ("tests.D.arms", {"own": 0, "swap": 3}, r"tests\.D\.arms"),
        ("tests.D.arms", {"own": 3}, r"tests\.D\.arms"),
        ("tests.B.arms", {}, r"tests\.B\.arms"),
        ("tests.B.arms.franz", ["ego-claim"], r"tests\.B\.arms\.franz"),
        ("tests.B.arms.franz", ["ego-claim", "ego-claim"], r"tests\.B\.arms\.franz"),
        ("tests.B.arms.franz", ["ego-claim", "shouting"], r"tests\.B\.arms\.franz.*shouting.*no hook pattern"),
        ("tests.B.arms.lenny", ["mid-deal", "ego-claim", "myth-bust", "trend-label", "false-premise"], r"tests\.B\.floor.*5 arms"),
        ("tests.B.floor", {"3": 0.15}, r"tests\.B\.floor.*4 arms"),
        ("tests.B.floor", {"3": 0.5, "4": 0.12}, r"tests\.B\.floor.*3 arms of 0.5"),  # more than every post
        ("tests.B.floor", {}, r"tests\.B\.floor"),
        ("tests.B.ceiling", 0, r"tests\.B\.ceiling"),
        ("tests.B.ceiling", 1.5, r"tests\.B\.ceiling"),
        ("tests.B.warmup_priors", 0, r"tests\.B\.warmup_priors"),
        ("tests.B.ceiling_until_tallied", "30", r"tests\.B\.ceiling_until_tallied"),
        ("tests.B.pool_min_uses", ..., r"tests\.B\.pool_min_uses"),
        ("tests.B.needs_moment_name", ["nonsense"], r"tests\.B\.needs_moment_name"),
        ("tests.F.key", "trial", "two tests write the same key"),
    ],
)
def test_a_registry_that_breaks_a_rule_is_refused_naming_the_key(path, value, message):
    with pytest.raises(ValueError, match=message) as e:
        parse_experiments(edit(path, value))
    assert str(e.value).startswith("config/experiments.json")


def test_a_missing_or_extra_test_is_refused():
    data = copy.deepcopy(DATA)
    del data["tests"]["E"]
    with pytest.raises(ValueError, match="no entry for test E"):
        parse_experiments(data)
    data = copy.deepcopy(DATA)
    data["tests"]["G"] = data["tests"]["F"]
    with pytest.raises(ValueError, match="unknown test 'G'"):
        parse_experiments(data)
    with pytest.raises(ValueError, match="must be a JSON object"):
        parse_experiments([])
    with pytest.raises(ValueError, match="tests"):
        parse_experiments({**DATA, "tests": []})
    with pytest.raises(ValueError, match=r"tests\.A"):
        parse_experiments({**DATA, "tests": {**DATA["tests"], "A": "on"}})


def test_an_unreadable_or_non_json_file_is_refused(tmp_path):
    with pytest.raises(ValueError, match="cannot read the test registry"):
        load_experiments(tmp_path / "missing.json")
    bad = tmp_path / "bad.json"
    bad.write_text("{nope", encoding="utf-8")
    with pytest.raises(ValueError, match="cannot read the test registry"):
        load_experiments(bad)


def test_a_test_off_is_valid_and_assigns_nothing():
    reg = registry(tests={**DATA["tests"], "C": {**DATA["tests"]["C"], "status": "off"}})
    assert not reg.test("C").on and [t.id for t in reg.active(START)] == ["A", "B"]
    assert reg.is_active("A", START) and not reg.is_active("C", START)


def test_a_test_starts_on_its_start_day_london_and_not_before():
    reg = c_on_registry()
    before = datetime(2026, 10, 11, 22, 0, tzinfo=timezone.utc)  # 23:00 on the 11th in London (BST)
    after = datetime(2026, 10, 11, 23, 30, tzinfo=timezone.utc)  # 00:30 on the 12th in London
    assert reg.active(before) == [] and [t.id for t in reg.active(after)] == ["A", "B", "C"]
    assert [t.id for t in load_experiments(REPO_REGISTRY).active(after)] == ["A", "B"]  # the file has C off
    assert reg.active(datetime(2026, 10, 5, 12, 0, tzinfo=LONDON)) == []


# ---- the block coin ------------------------------------------------------------------------------------------------------------------


def test_every_block_of_four_holds_each_arm_twice_for_every_character():
    reg, c = load_experiments(REPO_REGISTRY), load_experiments(REPO_REGISTRY).test("C")
    for slug in ("franz", "reginald", "lenny", "biscuit"):
        for block in range(60):
            order = block_order(reg.seed, c, slug, block)
            assert len(order) == 4 and Counter(order) == {True: 2, False: 2}, (slug, block, order)


def test_block_arm_follows_the_blocks_in_order():
    reg, c = load_experiments(REPO_REGISTRY), load_experiments(REPO_REGISTRY).test("C")
    seq = [block_arm(reg, c, "reginald", i) for i in range(16)]
    assert seq == [x for b in range(4) for x in block_order(reg.seed, c, "reginald", b)]
    assert all(Counter(seq[i : i + 4]) == {True: 2, False: 2} for i in range(0, 16, 4))


def test_the_same_inputs_always_give_the_same_arm():
    reg, c = load_experiments(REPO_REGISTRY), load_experiments(REPO_REGISTRY).test("C")
    first = [block_arm(reg, c, "franz", i) for i in range(40)]
    assert first == [block_arm(load_experiments(REPO_REGISTRY), c, "franz", i) for i in range(40)]
    assert first == [block_arm(reg, c, "franz", i) for i in range(40)]


def test_each_character_test_and_seed_has_its_own_coin():
    reg = load_experiments(REPO_REGISTRY)
    c, e, f = reg.test("C"), reg.test("E"), reg.test("F")
    seqs = {
        "franz": [block_arm(reg, c, "franz", i) for i in range(48)],
        "lenny": [block_arm(reg, c, "lenny", i) for i in range(48)],
        "reginald": [block_arm(reg, c, "reginald", i) for i in range(48)],
    }
    assert len({tuple(s) for s in seqs.values()}) == 3  # three characters, three sequences
    other = parse_experiments({**copy.deepcopy(DATA), "seed": "another-seed"})
    assert [block_arm(other, other.test("C"), "franz", i) for i in range(48)] != seqs["franz"]
    # two tests with the same two-arm shape never line up: map E's and F's arms to C's and compare position by position
    to_bool = lambda arm: arm in ("long", "vote")  # noqa: E731 - long = trial, vote = trial
    ef = [(to_bool(block_arm(reg, e, "franz", i)), to_bool(block_arm(reg, f, "franz", i))) for i in range(48)]
    c_seq = seqs["franz"]
    assert sum(a == b for a, b in ef) not in (0, 48)  # E and F differ somewhere and agree somewhere
    assert [a for a, _ in ef] != c_seq and [b for _, b in ef] != c_seq


def test_tests_are_not_plain_alternations():
    """Section 3.0: never A, B, A, B (it would line up with the caption rotation): over 48 posts a character's coin is not one."""
    reg, c = load_experiments(REPO_REGISTRY), load_experiments(REPO_REGISTRY).test("C")
    for slug in ("franz", "reginald", "lenny"):
        seq = [block_arm(reg, c, slug, i) for i in range(48)]
        alternating = [seq[i] != seq[i + 1] for i in range(len(seq) - 1)]
        assert not all(alternating) and seq != [seq[0], not seq[0]] * 24


def test_test_d_is_one_in_three():
    reg, d = load_experiments(REPO_REGISTRY), load_experiments(REPO_REGISTRY).test("D")
    for block in range(30):
        assert Counter(block_order(reg.seed, d, "franz", block)) == {"own": 1, "swap": 2}
    assert d.block == 3 and dict(d.counts) == {"own": 1, "swap": 2}


def test_block_arm_refuses_a_test_without_a_coin():
    reg = load_experiments(REPO_REGISTRY)
    with pytest.raises(ValueError, match="no block coin"):
        block_arm(reg, reg.test("A"), "franz", 0)
    with pytest.raises(ValueError, match="no block coin"):
        block_arm(reg, reg.test("B"), "franz", 0)


# ---- the place in the block ----------------------------------------------------------------------------------------------------------


def clip_with(store: MemoryStore, slug: str, arms: Any = None, state: str = "awaiting_approval", fav_id: str | None = None) -> Clip:
    features: dict[str, Any] = {}
    if arms is not None:
        features["test_arms"] = arms
    if fav_id:
        features["fav_id"] = fav_id
    return store.add_clip(Clip(character_slug=slug, mode="dropin", state=state, features=features))


def world() -> MemoryStore:
    store = MemoryStore()
    for slug in ("franz", "reginald"):
        store.add_character(Character(slug=slug, name=slug.title(), bodies=[Body.biped]))
    return store


def test_the_position_is_the_number_of_his_clips_that_carry_the_key():
    store = world()
    assert block_position(store, "franz", "trial") == 0
    clip_with(store, "franz", {"trial": True})
    clip_with(store, "franz", {"trial": False, "hook": "ego-claim"})  # False is a value: the clip took a place
    clip_with(store, "franz", {"hook": "ego-claim"})  # no trial key: not part of this test's blocks
    clip_with(store, "franz", {})
    clip_with(store, "franz", None)
    clip_with(store, "reginald", {"trial": True})  # another character has his own blocks
    assert block_position(store, "franz", "trial") == 2
    assert block_position(store, "franz", "hook") == 2
    assert block_position(store, "reginald", "trial") == 1
    assert block_position(store, "franz", "length") == 0


def test_every_clip_that_ever_got_the_arm_keeps_its_place_whatever_became_of_it():
    """I1: a rejected or dropped clip, and an earlier try of the same pick, still count: a position is never given twice."""
    store = world()
    for state in ("posted", "dropped", "rejected", "generating", "planned"):
        clip_with(store, "franz", {"trial": True}, state=state, fav_id="pick-1" if state == "planned" else None)
    assert block_position(store, "franz", "trial") == 5


def test_assign_blocks_gives_the_arm_of_the_next_place_and_only_for_active_block_coin_tests():
    reg, store = c_on_registry(), world()
    c = reg.test("C")
    got = []
    for _ in range(8):
        arms = assign_blocks(store, reg, "franz", START)
        assert set(arms) == {"trial"}  # A is a tag, B the bandit, D-F are off (C is on in this registry)
        got.append(arms["trial"])
        clip_with(store, "franz", arms)
    assert got == [block_arm(reg, c, "franz", i) for i in range(8)]
    assert Counter(got[:4]) == {True: 2, False: 2} and Counter(got[4:]) == {True: 2, False: 2}
    assert assign_blocks(store, reg, "franz", START) == {"trial": block_arm(reg, c, "franz", 8)}  # asking twice changes nothing
    assert assign_blocks(store, reg, "franz", START) == assign_blocks(store, reg, "franz", START)
    assert assign_blocks(store, reg, "reginald", START) == {"trial": block_arm(reg, c, "reginald", 0)}


def test_assign_blocks_assigns_nothing_before_the_start_or_for_an_off_test():
    reg, store = c_on_registry(), world()
    assert assign_blocks(store, reg, "franz", datetime(2026, 10, 11, 12, 0, tzinfo=LONDON)) == {}
    off = registry(tests={t: {**v, "status": "off"} for t, v in DATA["tests"].items()})
    assert assign_blocks(store, off, "franz", START) == {}
    assert assign_blocks(store, load_experiments(REPO_REGISTRY), "franz", START) == {}  # the file has C off: no trial arm
    on = registry(tests={**c_on_data()["tests"], "F": {**DATA["tests"]["F"], "status": "on"}})
    assert set(assign_blocks(store, on, "franz", START)) == {"trial", "comment"}  # a test turned on assigns by its own coin
    assert assign_blocks(store, on, "franz", START)["comment"] in ("vote", "question")


# ---- test A: the exploration tag ---------------------------------------------------------------------------------------------------


def test_a_clip_below_the_median_of_the_ready_scores_is_an_exploration_pick():
    pool = [90, 80, 70, 60, 50]
    assert [is_explore(s, pool) for s in pool] == [False, False, False, True, True]  # the median is 70, strictly below
    assert not is_explore(70, pool)


def test_an_unscored_clip_and_a_pool_of_one_are_never_exploration_picks():
    assert not is_explore(None, [90, 80, 10])
    assert not is_explore(10, [10])  # the clip alone: nothing to be below
    assert not is_explore(10, [])
    assert is_explore(10, [10, 90])
    assert not is_explore(50, [50, 50, 50])


# ---- the make path writes the tags on the clip -------------------------------------------------------------------------------------------


LOOK = {
    "setting": "a corridor", "moment_name": "shoulder shimmy", "classic": False, "people_count": 1, "caption": {},
    "hooks": ["The household is unaware.", "Breakfast is at eight.", "Kindly do not tell the Duchess."],
    "hook_patterns": ["understatement", "false-premise", "understatement"], "first_comment": "x",
}


def add_pick(store: MemoryStore, slug: str, score: int | None, state: str = "ready", **drop_over: Any) -> Favorite:
    d: dict[str, Any] = {
        "state": state, "kind": "file", "classic": False, "has_audio": True, "music": "original", "hit_rules_version": "v1",
        "window": {"start_s": 0.0, "length_s": 8.0}, "star": {"description": "the man in the grey suit", "body": "biped"},
        "part": "featured", "gadgets": [], "hook": LOOK["hooks"][0], "hooks": LOOK["hooks"], "deconstruct": LOOK, **drop_over,
    }
    if score is not None:
        d["score"] = {"total": score, "potential": 7, "swap": 8, "reason": "x"}
    return store.add_favorite(
        Favorite(url=f"owner-drop:{len(store.list_favorites())}", platform="drop", origin="owner", character_slug=slug,
                 proposal={"drop": d, "make_requested": {"at": START.isoformat(), "by": "owner"}}, status="approved")
    )


def make_clip(store: MemoryStore, pick: Favorite, now: datetime = START) -> Clip:
    return drop._new_or_current_clip(store, store.get_favorite(pick.id), now)


def test_a_made_clip_carries_its_coin_and_the_explore_tag(c_on):
    store = world()
    for s in (90, 80, 70, 60, 50):
        add_pick(store, "franz", s)
    low = add_pick(store, "franz", 40, state="making")  # sent just now: no clip yet, so it still counts in the pool
    clip = make_clip(store, low)
    f = store.get_clip(clip.id).features
    assert f["explore_pick"] is True  # 40 is below the median (65) of the ready clips and of itself
    assert f["test_arms"] == {"trial": block_arm(load_experiments(REPO_REGISTRY), load_experiments(REPO_REGISTRY).test("C"), "franz", 0)}
    assert clips.learn_problems(f) == []
    top = add_pick(store, "franz", 99, state="making")
    assert store.get_clip(make_clip(store, top).id).features["explore_pick"] is False


def test_the_pool_is_the_characters_checked_drops_with_a_score(experiments_on):
    store = world()
    ready = [add_pick(store, "franz", s) for s in (90, 80, 70)]
    add_pick(store, "reginald", 5)  # another character's clips are not his pool
    add_pick(store, "franz", 1, state="blocked")  # a check that did not finish
    add_pick(store, "franz", 4, state="checking")
    skipped = add_pick(store, "franz", 2)
    store.update_favorite(skipped.id, status="skipped")
    started = add_pick(store, "franz", 3, state="making", make={"clip_id": "c-1"})  # its make has begun: still in the pool
    add_pick(store, "franz", 85, state="made")
    add_pick(store, "franz", 75, state="failed")  # a failed make keeps its score (a failed check keeps none)
    add_pick(store, "franz", None, state="failed")
    expected = [3, 70, 75, 80, 85, 90]
    assert sorted(drop.checked_scores(store, ready[2])) == expected
    assert sorted(drop.checked_scores(store, started)) == expected  # the same pool for every clip of the batch
    sent_now = add_pick(store, "franz", 60, state="making")
    assert sorted(drop.checked_scores(store, sent_now)) == sorted([*expected, 60])


def test_the_median_does_not_move_while_a_batch_is_made_so_the_explore_clip_the_terminal_offered_is_tagged(experiments_on):
    """I2, the reviewer's probe: Franz has Ready 90, 80, 70, 60, 50, 40 (median 65). The terminal offers 90, 80, 70 and, as the
    Explore card, 50. The owner ticks all four and the makes run one after the other; each earlier make leaves the waiting set,
    but the pool does not shrink, so 50 is still judged against 65 and tagged."""
    store = world()
    picks = {s: add_pick(store, "franz", s) for s in (90, 80, 70, 60, 50, 40)}
    batch = [picks[s] for s in (90, 80, 70, 50)]
    for pick in batch:  # tapping Make: all four are `making` before the first make runs
        store.update_favorite(pick.id, proposal={**pick.proposal, "drop": {**pick.proposal["drop"], "state": "making"}})
    tagged = {}
    for pick in batch:
        clip = make_clip(store, store.get_favorite(pick.id))
        tagged[pick.proposal["drop"]["score"]["total"]] = store.get_clip(clip.id).features["explore_pick"]
    assert tagged == {90: False, 80: False, 70: False, 50: True}
    # the 60 and the 40 that were not ticked are still in the pool, as is everything made: nothing left it
    assert sorted(drop.checked_scores(store, store.get_favorite(picks[60].id))) == [40, 50, 60, 70, 80, 90]


def test_a_clip_with_no_score_is_never_an_exploration_pick_and_a_lone_clip_neither(experiments_on):
    store = world()
    unscored = add_pick(store, "franz", None)
    assert store.get_clip(make_clip(store, unscored).id).features["explore_pick"] is False
    lone = add_pick(store, "reginald", 10)
    assert store.get_clip(make_clip(store, lone).id).features["explore_pick"] is False


def test_the_coin_follows_the_block_across_several_makes_of_one_character(c_on):
    store, reg = world(), load_experiments(REPO_REGISTRY)
    got = []
    for i in range(8):
        pick = add_pick(store, "franz", 50 + i, state="making")
        got.append(store.get_clip(make_clip(store, pick).id).features["test_arms"]["trial"])
    assert got == [block_arm(reg, reg.test("C"), "franz", i) for i in range(8)]
    assert Counter(got[:4]) == {True: 2, False: 2} == Counter(got[4:])


def test_making_the_same_pick_again_reuses_its_clip_and_its_place(c_on):
    store = world()
    pick = add_pick(store, "franz", 70, state="making")
    first = make_clip(store, pick)
    again = make_clip(store, store.get_favorite(pick.id))
    assert again.id == first.id and block_position(store, "franz", "trial") == 1
    assert len(store.list_clips()) == 1


def test_a_rejected_clip_keeps_its_place_so_the_next_clip_gets_a_new_one(c_on):
    store, reg = world(), load_experiments(REPO_REGISTRY)
    first = make_clip(store, add_pick(store, "franz", 70, state="making"))
    store.update_clip(first.id, state=ClipState.rejected)
    second = make_clip(store, add_pick(store, "franz", 71, state="making"))
    assert store.get_clip(second.id).features["test_arms"]["trial"] is block_arm(reg, reg.test("C"), "franz", 1)


def test_a_rejection_in_the_middle_never_repeats_a_position_and_every_block_holds_two_and_two(c_on):
    """The reviewer's probe (I1): clips made at positions 0, 1, 2; the second is rejected; five more are made. Every position is
    handed out once, so every block of 4 holds 2 trial and 2 normal (the rejected clip's arm included)."""
    store, reg = world(), load_experiments(REPO_REGISTRY)
    made = [make_clip(store, add_pick(store, "franz", 50 + i, state="making")) for i in range(3)]
    store.update_clip(made[1].id, state=ClipState.rejected)
    made += [make_clip(store, add_pick(store, "franz", 60 + i, state="making")) for i in range(5)]
    arms = [store.get_clip(c.id).features["test_arms"]["trial"] for c in made]
    assert arms == [block_arm(reg, reg.test("C"), "franz", i) for i in range(8)]  # positions 0..7, none twice
    assert Counter(arms[:4]) == {True: 2, False: 2} == Counter(arms[4:])
    assert block_position(store, "franz", "trial") == 8


def test_with_the_repos_registry_a_made_clip_gets_no_trial_arm_but_keeps_the_explore_tag(experiments_on):
    """Test C is off in the file (every post is a normal Reel): no coin, no place in a block, test A's tag as before."""
    store = world()
    for s in (90, 80, 70, 60, 50):
        add_pick(store, "franz", s)
    f = store.get_clip(make_clip(store, add_pick(store, "franz", 40, state="making")).id).features
    assert f["explore_pick"] is True and "trial" not in f["test_arms"] and f["test_arms"] == {}
    assert block_position(store, "franz", "trial") == 0
    assert clips.learn_problems(f) == []


def test_an_account_with_trial_reels_ticked_still_gets_no_trial_arm_while_test_c_is_off(experiments_on, tmp_path):
    """The owner's per-account Trial Reel tick (config/scan.json reach.trial_reels) does not bring the coin back: with C off the
    reach pack reads no coin (``trial_test`` false) and the made clip carries none."""
    scan, chars = tmp_path / "scan.json", tmp_path / "chars"
    scan.write_text(json.dumps({"reach": {"trial_reels": {"franz.unimpressed": True}}}), encoding="utf-8")
    (chars / "franz").mkdir(parents=True)
    (chars / "franz" / "refs.json").write_text(
        json.dumps({"slug": "franz", "accounts": [{"platform": "instagram", "handle": "franz.unimpressed"}]}), encoding="utf-8"
    )
    cfg = load_reach(scan, chars)
    assert cfg.trial_reel_on("franz.unimpressed") and cfg.trial_test is False  # eligible account, test C off
    store = world()
    f = store.get_clip(make_clip(store, add_pick(store, "franz", 70, state="making")).id).features
    assert "trial" not in f["test_arms"]


def test_with_every_test_off_a_clip_is_made_exactly_as_before():
    store = world()
    for s in (90, 80, 70):
        add_pick(store, "franz", s)
    clip = make_clip(store, add_pick(store, "franz", 10, state="making"))
    f = store.get_clip(clip.id).features
    assert f["test_arms"] == {} and f["explore_pick"] is False


def test_before_the_start_day_nothing_is_assigned(experiments_on):
    store = world()
    add_pick(store, "franz", 90)
    clip = make_clip(store, add_pick(store, "franz", 10, state="making"), now=datetime(2026, 10, 11, 12, 0, tzinfo=LONDON))
    f = store.get_clip(clip.id).features
    assert f["test_arms"] == {} and f["explore_pick"] is False


def test_a_broken_registry_stops_the_make_before_a_clip_exists(tmp_path, monkeypatch):
    store = world()
    pick = add_pick(store, "franz", 70, state="making")
    bad = tmp_path / "experiments.json"
    bad.write_text(json.dumps(edit("tests.C.status", "perhaps")))
    monkeypatch.setattr(experiments, "EXPERIMENTS_PATH", bad)
    with pytest.raises(ValueError, match=r"tests\.C\.status"):
        make_clip(store, pick)
    assert store.list_clips() == []  # nothing was created, so nothing can be reserved or paid


def test_learn_tags_take_the_arms_and_the_flag_as_given():
    pick = add_pick(world(), "franz", 70)
    eff = {"hook": LOOK["hooks"][0], "part": "featured", "gadgets": []}
    d = drop.drop_of(pick)
    plain = drop.learn_tags(pick, d, eff, version_index=1)
    assert (plain["test_arms"], plain["explore_pick"]) == ({}, False)
    given = drop.learn_tags(pick, d, eff, version_index=1, test_arms={"trial": True}, explore_pick=True)
    assert (given["test_arms"], given["explore_pick"]) == ({"trial": True}, True)
    assert clips.learn_problems({**given, "length_s": 7.0}) == []
