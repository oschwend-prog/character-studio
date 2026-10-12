"""The hook bandit (learning plan section 3.3, test B, build item 9) and ``studio learn arms``.

**What it does.** The check (Gemini) writes ONE hook candidate for each arm of the character (3 or 4 in one call; ``gemini.HookArms``,
``drop.hook_arms_for``; a character with no arms gets 3 free hooks), each labelled with one of the 7 hook patterns
(``drop.deconstruct.hook_patterns``). At Make it, ``choose_hook`` draws a pattern among the character's arms
(``config/experiments.json`` test B: Franz ``ego-claim``, ``when-relatable``, ``myth-bust``, ``trend-label``; Reginald
``false-premise``, ``understatement``, ``trend-label``; Lenny ``mid-deal``, ``when-relatable``, ``ego-claim``, ``trend-label``) and the
clip goes out with the candidate of the drawn pattern (``hook_by`` ``bandit``, ``features['test_arms']['hook']`` = the pattern). If
no candidate carries the drawn pattern, the next one of the draw's order that has a candidate is used; if none of the arms has one,
or the owner chose the hook in his Adjust (``hook_by`` ``owner``: he always wins), the clip keeps the check's first hook (``studio``)
and the draw is not recorded. ``trend-label`` is an arm only for a clip that has a moment name (``needs_moment_name``). It only
chooses among hooks already written and checked: never the clip, the slot, the price or a bar.

**No table, no stored state.** The arms' state is computed from the data every time (``bandit_state``): a made clip with a real
``hook_pattern`` and ``hook_by`` ``bandit`` (the hook the draw chose, the warm-up rotation's draws included; never ``studio``, the
check's first hook that no draw chose, nor ``owner``: the owner's hook does not change the tally, plan guard rail 4) made on or after the registry's ``start`` has a **win** when its Instagram post's ``x72`` is above 1 (its 72-hour views beat
the median 72-hour views of the account's last 15 earlier posts, ``studio.metrics.post_reads``) and a **loss** when it is 1 or below;
a clip with no ``x72`` yet is neither (a post that missed its 72 h reading never is). Only Instagram counts (plan 3.0: one
observation is one posted clip on Instagram). The tally is recomputed on every read, so a win is as final as the 72-hour reading it
rests on (the first snapshot of the window, which never moves).

**The draw.**

1. *Warm-up.* Until the character's Instagram account has ``warmup_priors`` (3) posts with a 72-hour reading, no post has an ``x72`` and
   nothing can be tallied: the patterns rotate in the registry's order, one place per clip that carries a ``hook`` arm.
2. *Thompson sampling.* Each arm's curve is Beta(wins + 1, losses + 1); the arm that draws highest is the best. ``thompson_shares``
   estimates, by a fixed-seed simulation, how often each arm would draw highest (exactly equal when the arms have the same tally, so
   with no data every arm is equally likely). An arm takes the **character's own** tally once he has ``pool_min_uses`` (3) uses of
   it, else the **studio-wide** tally of that pattern (all characters pooled); with none anywhere it is Beta(1, 1).
3. *Ceiling.* Until the character has ``ceiling_until_tallied`` (30) tallied posts, no arm's share is above ``ceiling`` (60 %): the
   excess goes to the others in proportion.
4. *Floor.* Part of every draw is uniform: ``floor`` x the number of arms of every draw (15 % each with 3 arms, 12 % with 4), so every
   arm gets at least its floor. With a number of arms the registry lists no floor for (2: ``trend-label`` left out), the smallest
   listed count's share is used.
5. *The order.* The shares are sampled without replacement by a generator seeded from the registry seed, the character and the pick, so
   the same pick and data always give the same order; the first arm with a candidate wins.

The floor and the ceiling are on the draws. Since the check writes one hook per arm, every draw finds a candidate and the shares of
the posts that go out are the draw's. (A clip checked before that has 3 free hooks, so its draw may fall through to the next arm of
the order; and a clip with no moment name has no ``trend-label`` hook: its slot carries another pattern.)

``studio learn arms [--character SLUG]`` prints (read-only) each character's arms with wins, losses, the tally used and the
current draw probabilities, as JSON.
"""

from __future__ import annotations

import random
from collections import Counter
from functools import lru_cache
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Annotated, Any

import typer

from studio import experiments
from studio.cli_support import emit, fail, open_store
from studio.config import LONDON, now_london
from studio.experiments import Experiment, Registry
from studio.metrics import post_reads
from studio.models import HOOK_PATTERNS, Platform
from studio.store import Store

WIN_X = 1.0  # a win: x72 above this (the post beat the median 72-hour views of the account's last 15)
# hook_by values that count: only a hook the bandit drew (the warm-up rotation's draws are recorded the same way). Not "studio" (the
# check's first hook, no arm had a candidate: Gemini's habit, not a draw; controller 12 Oct, before data) and not "owner" (plan rail 4).
TALLIED_BY = ("bandit",)
THOMPSON_DRAWS = 4000  # simulated rounds behind ``thompson_shares``
EPS = 1e-9


# ---- the data ----------------------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Counts:
    wins: int = 0
    losses: int = 0

    @property
    def uses(self) -> int:
        return self.wins + self.losses


@dataclass(frozen=True)
class BanditState:
    """What the data says today: ``by_character[(slug, pattern)]`` and ``studio[pattern]`` (all characters pooled) win/loss counts,
    the Instagram posts with a 72-hour reading per character (``readings``, the warm-up's count) and the clips of the tally's kind
    still waiting for an ``x72`` (``pending``)."""

    by_character: Mapping[tuple[str, str], Counts] = field(default_factory=dict)
    studio: Mapping[str, Counts] = field(default_factory=dict)
    readings: Mapping[str, int] = field(default_factory=dict)
    pending: Mapping[str, int] = field(default_factory=dict)

    def tallied(self, slug: str) -> int:
        """The character's tallied posts (wins + losses over all his patterns)."""
        return sum(c.uses for (s, _), c in self.by_character.items() if s == slug)


def instagram_x72_by_clip(store: Store) -> tuple[dict[str, float], Counter[str]]:
    """({clip id: the best ``x72`` of its Instagram posts}, {character: Instagram posts with a 72-hour reading})."""
    best: dict[str, float] = {}
    readings: Counter[str] = Counter()
    for r in post_reads(store):
        if r.platform != Platform.instagram.value:
            continue
        if r.views_72h is not None:
            readings[r.character_slug] += 1
        if r.x72 is not None and r.x72 > best.get(r.clip_id, float("-inf")):
            best[r.clip_id] = r.x72
    return best, readings


def bandit_state(store: Store, registry: Registry) -> BanditState:
    """Count wins and losses per (character, hook pattern) and per pattern studio-wide, from the made clips (see the module doc)."""
    x72, readings = instagram_x72_by_clip(store)
    wins: Counter[tuple[str, str]] = Counter()
    losses: Counter[tuple[str, str]] = Counter()
    pending: Counter[str] = Counter()
    for clip in store.list_clips():
        f = clip.features
        pattern = f.get("hook_pattern")
        if pattern not in HOOK_PATTERNS or f.get("hook_by") not in TALLIED_BY:
            continue
        if clip.created_at is not None and clip.created_at.astimezone(LONDON).date() < registry.start:
            continue  # made before the test began
        if clip.id not in x72:
            pending[clip.character_slug] += 1
            continue
        (wins if x72[clip.id] > WIN_X else losses)[(clip.character_slug, pattern)] += 1
    by_character = {k: Counts(wins[k], losses[k]) for k in {*wins, *losses}}
    pooled_w, pooled_l = Counter(), Counter()
    for (_, pattern), c in by_character.items():
        pooled_w[pattern] += c.wins
        pooled_l[pattern] += c.losses
    return BanditState(
        by_character=by_character,
        studio={p: Counts(pooled_w[p], pooled_l[p]) for p in {*pooled_w, *pooled_l}},
        readings=dict(readings),
        pending=dict(pending),
    )


# ---- the draw ----------------------------------------------------------------------------------------------------------------------


def arm_counts(state: BanditState, slug: str, pattern: str, pool_min_uses: int) -> tuple[Counts, str]:
    """(the tally the arm is drawn with, its basis): ``character`` once he has ``pool_min_uses`` uses of it, else ``studio`` (the
    pattern's tally over all characters), ``none`` when that is empty too."""
    own = state.by_character.get((slug, pattern), Counts())
    if own.uses >= pool_min_uses:
        return own, "character"
    pooled = state.studio.get(pattern, Counts())
    return pooled, "studio" if pooled.uses else "none"


def thompson_shares(counts: Sequence[Counts], rng: random.Random, draws: int = THOMPSON_DRAWS) -> list[float]:
    """How often each arm would draw highest from its Beta(wins + 1, losses + 1) curve (a simulation of ``draws`` rounds). Arms with
    the very same tally split the draw exactly equally."""
    k = len(counts)
    if k == 0:
        return []
    if len({(c.wins, c.losses) for c in counts}) == 1:
        return [1 / k] * k
    top = [0] * k
    for _ in range(draws):
        samples = [rng.betavariate(c.wins + 1, c.losses + 1) for c in counts]
        top[samples.index(max(samples))] += 1
    return [t / draws for t in top]


@lru_cache(maxsize=512)
def _thompson_cached(key: str, tallies: tuple[tuple[int, int], ...]) -> tuple[float, ...]:
    """``thompson_shares`` for a seed text and the tallies as (wins, losses): the same inputs always give the same shares, so the
    simulation runs once per tally and not once per pick."""
    return tuple(thompson_shares([Counts(w, l) for w, l in tallies], random.Random(key)))


def cap_shares(shares: Sequence[float], cap: float) -> list[float]:
    """No share above ``cap``: the excess goes to the shares below it, in proportion to what they have (equally when they have
    none). Unchanged when the cap cannot hold (one arm, or ``cap`` x arms below 1)."""
    p = list(shares)
    n = len(p)
    if n < 2 or cap * n < 1 - EPS:
        return p
    for _ in range(n):
        over = [i for i, x in enumerate(p) if x > cap + EPS]
        if not over:
            break
        excess = sum(p[i] - cap for i in over)
        for i in over:
            p[i] = cap
        under = [i for i, x in enumerate(p) if x < cap - EPS]
        if not under:
            break
        room = sum(p[i] for i in under)
        for i in under:
            p[i] += excess * (p[i] / room if room > EPS else 1 / len(under))
    return p


def floor_share(floor: Mapping[str, float], arms: int) -> float:
    """The share every arm is guaranteed with ``arms`` arms: the registry's entry for that count, else the smallest listed count
    above it (or the largest below), never more than an equal split."""
    counts = sorted(int(k) for k in floor)
    key = next((c for c in counts if c >= arms), counts[-1])
    return min(float(floor[str(key)]), 1 / arms)


def mix_floor(shares: Sequence[float], share: float) -> list[float]:
    """Part of every draw is uniform so each arm gets at least ``share``: ``share`` x arms of the draw is a coin over all arms."""
    k = len(shares)
    uniform = share * k
    return [uniform / k + (1 - uniform) * x for x in shares]


def sample_order(names: Sequence[str], shares: Sequence[float], rng: random.Random) -> list[str]:
    """All ``names`` in the order a draw by ``shares`` picks them, one after the other without putting any back."""
    left = list(zip(names, shares, strict=True))
    out: list[str] = []
    while left:
        point, acc = rng.random() * sum(x for _, x in left), 0.0
        for i, (name, x) in enumerate(left):
            acc += x
            if point < acc or i == len(left) - 1:
                out.append(name)
                left.pop(i)
                break
    return out


@dataclass(frozen=True)
class Draw:
    """The shares one draw runs on (``shares`` per eligible arm, in the arms' order) and how they came about."""

    arms: tuple[str, ...]
    shares: tuple[float, ...]
    thompson: tuple[float, ...]
    counts: tuple[Counts, ...]
    basis: tuple[str, ...]
    warmup: bool
    ceiling_applies: bool
    floor: float


def arms_of(test: Experiment, slug: str, *, moment: bool = True) -> tuple[str, ...]:
    """The character's arms in the registry's order; ``trend-label`` (``needs_moment_name``) only for a clip with a moment name."""
    arms = test.arms.get(slug, ()) if isinstance(test.arms, Mapping) else ()
    gated = set(test.params.get("needs_moment_name") or [])
    return tuple(a for a in arms if moment or a not in gated)


def draw_shares(test: Experiment, state: BanditState, seed: str, slug: str, *, moment: bool = True) -> Draw:
    """The shares of the character's next draw (see the module doc): equal shares in the warm-up, else Thompson sampling with the
    ceiling and the floor. Needs no pick: the same data always give the same shares."""
    p = test.params
    arms = arms_of(test, slug, moment=moment)
    k = len(arms)
    if k == 0:
        return Draw((), (), (), (), (), True, False, 0.0)
    pool_min = int(p["pool_min_uses"])
    picked = [arm_counts(state, slug, a, pool_min) for a in arms]
    counts, basis = tuple(c for c, _ in picked), tuple(b for _, b in picked)
    share = floor_share(p["floor"], k)
    if state.readings.get(slug, 0) < int(p["warmup_priors"]):
        equal = tuple([1 / k] * k)
        return Draw(arms, equal, equal, counts, basis, True, False, share)
    thompson = _thompson_cached(f"{seed}|thompson|{slug}", tuple((c.wins, c.losses) for c in counts))
    tallied = state.tallied(slug)
    ceiling_applies = tallied < int(p["ceiling_until_tallied"])
    shares = cap_shares(thompson, float(p["ceiling"])) if ceiling_applies else list(thompson)
    return Draw(arms, tuple(mix_floor(shares, share)), tuple(thompson), counts, basis, False, ceiling_applies, share)


@dataclass(frozen=True)
class Choice:
    """A hook the bandit chose for a pick (stored in ``drop['make']['bandit']``)."""

    pattern: str
    index: int  # the candidate's place in the check's hooks, from 0
    hook: str
    order: tuple[str, ...]  # the draw's order of the eligible arms (the first with a candidate won)
    warmup: bool

    def as_dict(self) -> dict[str, Any]:
        return {"pattern": self.pattern, "index": self.index, "hook": self.hook, "order": list(self.order), "warmup": self.warmup}


def choose_hook(
    store: Store, registry: Registry, slug: str, pick_id: str, hooks: Sequence[str], patterns: Sequence[Any], *,
    moment: bool, now: datetime, state: BanditState | None = None,
) -> Choice | None:
    """The candidate the bandit puts on screen for ``pick_id``, or ``None`` (test B off or not started, the character has no
    arms, or none of his arms has a candidate: the clip keeps the check's first hook). ``hooks`` / ``patterns`` are the check's
    candidates and their labels in the same order; ``moment`` says whether the clip has a moment name (``trend-label``'s precondition).
    Deterministic: the same registry, data and pick always give the same choice. ``state`` is ``bandit_state(store, registry)``
    (computed here when not given)."""
    test = registry.test("B")
    if not registry.is_active("B", now):
        return None
    arms = arms_of(test, slug, moment=moment)
    candidates = {pat: i for i, (h, pat) in reversed(list(enumerate(zip(hooks, patterns, strict=False)))) if isinstance(h, str) and h.strip()}
    if not arms or not any(a in candidates for a in arms):
        return None
    state = state if state is not None else bandit_state(store, registry)
    draw = draw_shares(test, state, registry.seed, slug, moment=moment)
    if draw.warmup:  # a fixed rotation, one place per clip that carries a hook arm
        start = experiments.block_position(store, slug, str(test.key)) % len(arms)
        order = tuple(arms[(start + i) % len(arms)] for i in range(len(arms)))
    else:
        rng = random.Random(f"{registry.seed}|bandit|{slug}|{pick_id}")
        order = tuple(sample_order(draw.arms, draw.shares, rng))
    pattern = next(a for a in order if a in candidates)
    index = candidates[pattern]
    return Choice(pattern=pattern, index=index, hook=hooks[index], order=order, warmup=draw.warmup)


# ---- studio learn arms -------------------------------------------------------------------------------------------------------------


def arms_report(store: Store, registry: Registry, now: datetime, *, character: str | None = None) -> dict[str, Any]:
    """Every character's arms with wins, losses, the tally the draw uses and the current draw shares (read-only)."""
    test = registry.test("B")
    state = bandit_state(store, registry)
    arms = test.arms if isinstance(test.arms, Mapping) else {}
    slugs = [character] if character else list(arms)
    rows: list[dict[str, Any]] = []
    for slug in slugs:
        if slug not in arms:
            raise ValueError(f"{slug!r} has no hook arms in config/experiments.json (test B: {', '.join(arms)})")
        full = draw_shares(test, state, registry.seed, slug)
        gated = set(test.params.get("needs_moment_name") or [])
        without = draw_shares(test, state, registry.seed, slug, moment=False) if gated & set(arms[slug]) else None
        share_without = dict(zip(without.arms, without.shares, strict=True)) if without else {}
        rows.append(
            {
                "character": slug,
                "mode": "rotation" if full.warmup else "thompson",
                "readings": state.readings.get(slug, 0),
                "readings_needed": int(test.params["warmup_priors"]),
                "tallied": state.tallied(slug),
                "pending": state.pending.get(slug, 0),
                "ceiling": {"share": test.params["ceiling"], "applies": full.ceiling_applies, "until_tallied": test.params["ceiling_until_tallied"]},
                "floor": full.floor,
                "arms": [
                    {
                        "pattern": a,
                        "wins": state.by_character.get((slug, a), Counts()).wins,
                        "losses": state.by_character.get((slug, a), Counts()).losses,
                        "uses": state.by_character.get((slug, a), Counts()).uses,
                        "studio_wins": state.studio.get(a, Counts()).wins,
                        "studio_losses": state.studio.get(a, Counts()).losses,
                        "tally": {"wins": c.wins, "losses": c.losses, "basis": b},
                        "thompson": round(t, 4),
                        "draw": round(s, 4),
                        "draw_without_moment_name": None if a in gated else (round(share_without[a], 4) if without else None),
                        "needs_moment_name": a in gated,
                    }
                    for a, c, b, t, s in zip(full.arms, full.counts, full.basis, full.thompson, full.shares, strict=True)
                ],
            }
        )
    return {
        "as_of": now.isoformat(),
        "test": {"id": "B", "status": test.status, "active": registry.is_active("B", now), "start": registry.start.isoformat()},
        "win": test.params.get("win"),
        "characters": rows,
    }


app = typer.Typer(help="The learning loop: the hook bandit's arms. Prints JSON; read-only.", no_args_is_help=True)


@app.command("arms")
def arms_command(
    character: Annotated[str | None, typer.Option(help="Only this character (slug).")] = None,
) -> None:
    """Each character's hook arms: wins, losses, the tally the draw uses and the current draw probabilities (read-only)."""
    try:
        registry = experiments.load_experiments()
        emit(arms_report(open_store(), registry, now_london(), character=character))
    except ValueError as e:
        fail(str(e))
