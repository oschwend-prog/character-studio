"""The test registry and the assignment of a made clip to its test arms (learning plan sections 3.0-3.4, build item 7).

``config/experiments.json`` holds one entry per pre-registered test (A score and exploration picks, B hook bandit, C Trial
Reels, D own series, E length, F first comment): its ``status`` (``on`` / ``off``: an ``off`` test assigns nothing), how it
assigns, its arms, the block of its coin, the minimum sample. ``load_experiments`` reads and validates it and refuses, naming the
key, anything it does not understand (``ValueError``): the make and the publish run stop, nothing is guessed. The registry path is
``EXPERIMENTS_PATH`` (read at call time, so a test can point it elsewhere). A test assigns only from the registry's ``start`` day
on (London).

**The block coin** (section 3.0; tests C, D, E, F). Each test has its own coin, so two tests never line up and none lines up with
the caption rotation. A character's clips are numbered by the tests they carry: the next clip is at ``position`` = the number of his
earlier clips that ever carried the test's ``key`` in ``features['test_arms']``: EVERY one, whatever became of it (a clip that was
dropped, rejected or failed keeps its place, as does an earlier try of the same pick), so a position is never given out twice. A
clip that never posts leaves a hole in its block rather than a duplicate: the arms handed out stay 2 and 2 in every 4. Positions are cut into blocks of ``block``; a block
holds every arm exactly ``block / len(arms)`` times (or ``arms[name]`` times when ``arms`` is a name -> count object, test D's
1 in 3) in an order shuffled by ``random.Random`` seeded from the registry ``seed``, the test id, the character and the block
number. So the same character, test, position and seed always give the same arm, whatever else happened, and no run of four posts
is ever lopsided. ``assign_blocks`` returns ``{key: arm}`` for every active block-coin test; the make path calls it under the
settings row lock (``drop._new_or_current_clip``), so two makes of one character never read the same position.

**Test A** (section 3.2) is a tag, not a coin: ``explore_pick`` is true when the clip's score is below the median score of the
character's checked drops (ready, being made or made, ``drop.checked_scores``: so the median does not move while a batch is made;
``is_explore``; the pool is given by the caller and holds the clip itself).
The owner still ticks what is made; the terminal's suggestions (``terminal/src/lib/ranking.ts``) offer one such clip in every 4.

**Test B** is the hook bandit (``studio.learn``); this module only validates its entry (arms per character, floor, ceiling).
"""

from __future__ import annotations

import json
import random
import statistics
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

from studio.config import LONDON
from studio.models import HOOK_PATTERNS
from studio.store import Store, require_aware

ROOT = Path(__file__).resolve().parents[1]
EXPERIMENTS_PATH = ROOT / "config" / "experiments.json"

TEST_IDS = ("A", "B", "C", "D", "E", "F")
STATUSES = ("on", "off")
ASSIGNMENTS = ("tag", "block_coin", "bandit")
MIN_EXPLORE_POOL = 2  # a median needs at least two scored clips; with one, nothing is "below" it


@dataclass(frozen=True)
class Experiment:
    """One registry entry, validated. ``arms`` is the tuple of arms (``block_coin``: JSON booleans or names; ``counts`` then gives
    each arm's places in a block) or, for the bandit, a character -> patterns map."""

    id: str
    name: str
    status: str
    assignment: str
    key: str | None
    arms: tuple[Any, ...] | Mapping[str, tuple[str, ...]]
    block: int | None
    counts: Mapping[Any, int]
    params: Mapping[str, Any]  # the entry as written (the bandit reads its floor, ceiling ... from here)

    @property
    def on(self) -> bool:
        return self.status == "on"


@dataclass(frozen=True)
class Registry:
    version: int
    start: date
    seed: str
    tests: Mapping[str, Experiment]

    def test(self, test_id: str) -> Experiment:
        return self.tests[test_id]

    def active(self, now: datetime) -> list[Experiment]:
        """The tests that assign at ``now``: ``on``, and the registry's ``start`` day (London) has come. ``ValueError`` for a naive
        ``now`` (never read as machine-local time)."""
        require_aware(now, "Registry.active(now)")
        if now.astimezone(LONDON).date() < self.start:
            return []
        return [t for t in self.tests.values() if t.on]

    def is_active(self, test_id: str, now: datetime) -> bool:
        return any(t.id == test_id for t in self.active(now))


def _bad(where: str, what: str) -> ValueError:
    return ValueError(f"config/experiments.json {where}: {what}")


def _positive_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _unit(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and 0 < value <= 1


def _scalar(value: Any) -> bool:
    return isinstance(value, (bool, str)) and value != ""


def _coin(where: str, raw: Mapping[str, Any]) -> tuple[tuple[Any, ...], int, dict[Any, int]]:
    """(arms, block, places per arm) of a block-coin entry: ``arms`` a list of distinct arms sharing the block equally, or an
    object of name -> places that adds up to ``block``."""
    block, arms = raw.get("block"), raw.get("arms")
    if not _positive_int(block):
        raise _bad(f"{where}.block", f"must be a whole number of 1 or more, got {block!r:.40}")
    if isinstance(arms, Mapping):
        counts = {name: n for name, n in arms.items()}
        if len(counts) < 2 or not all(isinstance(n, str) and n and _positive_int(c) for n, c in counts.items()):
            raise _bad(f"{where}.arms", "an object needs at least two names, each with a whole number of places")
        if sum(counts.values()) != block:
            raise _bad(f"{where}.arms", f"the places add up to {sum(counts.values())}, the block has {block}")
        return tuple(counts), block, counts
    if not isinstance(arms, list) or len(arms) < 2 or not all(_scalar(a) for a in arms):
        raise _bad(f"{where}.arms", f"must be a list of at least two arms (true / false or names), got {arms!r:.60}")
    if len({json.dumps(a) for a in arms}) != len(arms):
        raise _bad(f"{where}.arms", "an arm appears twice")
    if block % len(arms):
        raise _bad(f"{where}.block", f"{block} places cannot be shared equally by {len(arms)} arms")
    return tuple(arms), block, {a: block // len(arms) for a in arms}


def _bandit(where: str, raw: Mapping[str, Any]) -> dict[str, tuple[str, ...]]:
    arms = raw.get("arms")
    if not isinstance(arms, Mapping) or not arms:
        raise _bad(f"{where}.arms", "must be an object of character -> hook patterns")
    out: dict[str, tuple[str, ...]] = {}
    floor = raw.get("floor")
    if not isinstance(floor, Mapping) or not floor or not all(k.isdigit() and _unit(v) for k, v in floor.items()):
        raise _bad(f"{where}.floor", 'must map a number of arms to the share each arm is guaranteed, e.g. {"3": 0.15}')
    for slug, patterns in arms.items():
        if not isinstance(patterns, list) or len(patterns) < 2 or len(set(patterns)) != len(patterns):
            raise _bad(f"{where}.arms.{slug}", "needs at least two different hook patterns")
        if unknown := [p for p in patterns if p not in HOOK_PATTERNS]:
            raise _bad(f"{where}.arms.{slug}", f"{unknown[0]!r} is no hook pattern (one of {', '.join(HOOK_PATTERNS)})")
        share = floor.get(str(len(patterns)))
        if share is None:
            raise _bad(f"{where}.floor", f"no floor for {len(patterns)} arms ({slug})")
        if share * len(patterns) > 1:
            raise _bad(f"{where}.floor", f"{len(patterns)} arms of {share} each is more than every post")
        out[slug] = tuple(patterns)
    for key in ("ceiling",):
        if not _unit(raw.get(key)):
            raise _bad(f"{where}.{key}", f"must be a share above 0 up to 1, got {raw.get(key)!r:.40}")
    for key in ("warmup_priors", "ceiling_until_tallied", "pool_min_uses"):
        if not _positive_int(raw.get(key)):
            raise _bad(f"{where}.{key}", f"must be a whole number of 1 or more, got {raw.get(key)!r:.40}")
    needing = raw.get("needs_moment_name", [])
    if not isinstance(needing, list) or any(p not in HOOK_PATTERNS for p in needing):
        raise _bad(f"{where}.needs_moment_name", "must be a list of hook patterns")
    return out


def _experiment(test_id: str, raw: Any) -> Experiment:
    where = f"tests.{test_id}"
    if not isinstance(raw, Mapping):
        raise _bad(where, "must be an object")
    for key in ("name", "status", "assignment"):
        if not isinstance(raw.get(key), str) or not raw[key].strip():
            raise _bad(f"{where}.{key}", "is required (text)")
    if raw["status"] not in STATUSES:
        raise _bad(f"{where}.status", f"must be one of {', '.join(STATUSES)}, got {raw['status']!r:.30}")
    if raw["assignment"] not in ASSIGNMENTS:
        raise _bad(f"{where}.assignment", f"must be one of {', '.join(ASSIGNMENTS)}, got {raw['assignment']!r:.30}")
    min_n = raw.get("min_n")
    if not isinstance(min_n, Mapping) or not min_n or not all(_positive_int(v) for v in min_n.values()):
        raise _bad(f"{where}.min_n", "must be an object of whole numbers of 1 or more (the minimum sample)")
    key = raw.get("key")
    if raw["assignment"] != "tag" and (not isinstance(key, str) or not key.strip()):
        raise _bad(f"{where}.key", "is required (the key of features['test_arms'])")
    arms: Any = ()
    block: int | None = None
    counts: Mapping[Any, int] = {}
    if raw["assignment"] == "block_coin":
        arms, block, counts = _coin(where, raw)
    elif raw["assignment"] == "bandit":
        arms = _bandit(where, raw)
    else:
        explore = raw.get("explore")
        if not isinstance(explore, Mapping) or not _positive_int(explore.get("every")) or explore["every"] < 2:
            raise _bad(f"{where}.explore.every", "must be a whole number of 2 or more (one clip in every N)")
    return Experiment(
        id=test_id, name=raw["name"], status=raw["status"], assignment=raw["assignment"],
        key=key if isinstance(key, str) else None, arms=arms, block=block, counts=counts, params=dict(raw),
    )


def parse_experiments(data: Any) -> Registry:
    """The registry from its parsed JSON (``ValueError`` naming the key when anything is wrong)."""
    if not isinstance(data, Mapping):
        raise _bad("", "must be a JSON object")
    version = data.get("version")
    if not _positive_int(version):
        raise _bad("version", f"must be a whole number of 1 or more, got {version!r:.30}")
    try:
        start = date.fromisoformat(str(data.get("start")))
    except ValueError:
        raise _bad("start", f"must be a date (YYYY-MM-DD), got {data.get('start')!r:.30}") from None
    seed = data.get("seed")
    if not isinstance(seed, str) or not seed.strip():
        raise _bad("seed", "is required (text)")
    tests = data.get("tests")
    if not isinstance(tests, Mapping):
        raise _bad("tests", "must be an object with one entry per test")
    if missing := [t for t in TEST_IDS if t not in tests]:
        raise _bad("tests", f"has no entry for test {', '.join(missing)}")
    if extra := sorted(set(tests) - set(TEST_IDS)):
        raise _bad("tests", f"has an unknown test {extra[0]!r} (the tests are {', '.join(TEST_IDS)})")
    parsed = {t: _experiment(t, tests[t]) for t in TEST_IDS}
    keys = [e.key for e in parsed.values() if e.key]
    if len(set(keys)) != len(keys):
        raise _bad("tests", "two tests write the same key of test_arms")
    return Registry(version=version, start=start, seed=seed.strip(), tests=parsed)


def load_experiments(path: Path | str | None = None) -> Registry:
    """Read and validate the registry (``EXPERIMENTS_PATH`` when no ``path`` is given). ``ValueError`` when it cannot be read, is
    not JSON or breaks a rule: the caller stops, nothing is assigned or published on a guess."""
    path = Path(path) if path is not None else Path(EXPERIMENTS_PATH)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise ValueError(f"{path}: cannot read the test registry: {e}") from None
    return parse_experiments(data)


# ---- the block coin ---------------------------------------------------------------------------------------------------------------


def block_order(seed: str, test: Experiment, character: str, block_index: int) -> list[Any]:
    """The arms of one block in the order they are played: every arm exactly its places, shuffled by a coin seeded from the
    registry seed, the test, the character and the block (so another test, character or block has its own order)."""
    places = [arm for arm, n in test.counts.items() for _ in range(n)]
    random.Random(f"{seed}|{test.id}|{character}|{block_index}").shuffle(places)
    return places


def block_arm(registry: Registry, test: Experiment, character: str, position: int) -> Any:
    """The arm of a character's ``position``-th (from 0) clip of this test."""
    if test.assignment != "block_coin" or not test.block:
        raise ValueError(f"test {test.id} has no block coin")
    return block_order(registry.seed, test, character, position // test.block)[position % test.block]


def block_position(store: Store, character: str, key: str) -> int:
    """How many of the character's clips ever carried ``key`` in their ``test_arms``: all of them, rejected, dropped and failed
    ones included, so the next position is never one that was already given out (a rejected clip in the middle leaves a hole in
    its block, never a duplicate)."""
    return sum(
        1 for clip in store.list_clips(character_slug=character)
        if isinstance(arms := clip.features.get("test_arms"), Mapping) and key in arms
    )


def assign_blocks(store: Store, registry: Registry, character: str, now: datetime) -> dict[str, Any]:
    """``{key: arm}`` for every active block-coin test, for the character's next clip (``{}`` when none is active). Call it under
    the settings row lock so two makes of one character cannot read the same position."""
    out: dict[str, Any] = {}
    for test in registry.active(now):
        if test.assignment == "block_coin" and test.key:
            position = block_position(store, character, test.key)
            out[test.key] = block_arm(registry, test, character, position)
    return out


# ---- test A: exploration picks ----------------------------------------------------------------------------------------------------


def is_explore(score_total: int | None, pool: Sequence[int]) -> bool:
    """Test A's tag: the clip's score is below the median of ``pool`` (the scores of the character's checked drops, the clip itself
    included). False for a clip with no score and for a pool of fewer than two scores."""
    if score_total is None or len(pool) < MIN_EXPLORE_POOL:
        return False
    return score_total < statistics.median(pool)
