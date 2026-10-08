"""Clip state machine and feature tags.

Every clip walks one fixed path (``ALLOWED``); ``transition`` is the only way its state moves::

    planned -> generating -> generated -> qa_passed -> mastered -> awaiting_approval -> approved
                  |  ^           |                       |               |               |
                  v  |           v                       +----> scheduled <--------------+
              gen_failed      qa_failed                              |
                  |              |                                   v
                  +--> dropped <-+                                 posted      (rejected: from
                                                                               awaiting_approval, or from
                                                                               scheduled once every post
                                                                               of the clip was dropped)

``rejected``, ``posted`` and ``dropped`` are final: they have no entry in ``ALLOWED``. A clip that leaves
``scheduled`` for ``rejected`` / ``dropped`` takes its never-sent posts with it, in the same transaction
(``scheduled`` / ``failed`` ones with no platform id and no metrics snapshot); a ``posting``, ``needs_check``
or ``posted`` post stays, it may be live.

**Re-rolls.** A clip that failed QA may go back to ``generating`` exactly once
(``qa_failed -> generating``); ``features['rerolls']`` counts it and a second one raises
``IllegalTransition("max one re-roll")``. ``gen_failed -> generating`` is a technical retry (the
reservation was released, nothing was judged), so it does not use up the re-roll.

**Feature tags.** ``new_clip`` refuses a clip that lacks any of ``REQUIRED_FEATURES``: they are
what the weekly review learns from (``feature_lifts``), so they are set at creation and never
guessed later. A tag whose value is ``None`` counts as missing (``False`` and ``0`` are values;
use ``"evergreen"`` for ``trend_name`` when there is no trend). Extra tags are kept as given.
``rerolls`` belongs to the state machine: it starts at 0 and callers may not set it.

**Learning tags** (``docs/launch/measurement-and-learning-plan.md`` section 2, plan Task 10): tags cannot be added to posts
afterwards, so a made clip carries them from creation. ``LEARN_FEATURES`` are the keys besides ``REQUIRED_FEATURES``;
``LEARN_VALUES`` holds the fixed vocabularies (``format_id`` and ``hook_pattern`` among them), so values repeat often enough to
reach n >= 5. ``"none"`` is a value; a missing tag is an error. ``new_clip`` requires every one of them except the master's own
two (``MASTER_FEATURES``: ``length_s`` and ``length_bucket``, written by ``set_length`` when the master is attached to the clip,
``master.upload_master``) for a clip that is a drop's (``drop: True``, written by ``studio drop``), any clip made from a pick
(``fav_id``: the daily run's Recreate or Drop-in of a pick) or one that opts in by writing ``source_kind``: a key absent is
"missing", a value outside its vocabulary or of the wrong type is refused (``learn_problems``). A categorical tag is never
``None``; only the exact detail of a tag may be (``LEARN_NULLABLE``), and then it goes with its tag both ways: the three
``score_*`` numbers are None exactly when ``score_bucket`` is none, ``days_since_trend_peak`` is None when ``trend_stage`` is
none or classic, ``episode`` is None when ``series`` is none. ``hit_rules_version`` is ``v<N>`` or ``none``. A clip made by hand
with no pick and no ``source_kind`` (and not a drop's) is created exactly as before (legacy). ``set_hook_tags`` re-tags the hook
when the master renders another one than the clip was created with. ``review.feature_lifts`` reads the tags.

``transition`` and ``set_fields`` write only ``SETTABLE_FIELDS``. The state never changes through
``set_fields`` (or ``store.update_clip`` anywhere else): that is the whole point of the table.

**The source** is set at creation and may be changed by ``set_source`` only while the clip is ``planned``:
a synthetic driver exists only after the clip was created and its credits reserved, so it has to be linked
afterwards. Once generation starts the source is fixed again (``clip set --source-id`` is refused).

**Scheduling** (``schedule_clip``, ``studio clip schedule <id> [--at ISO]``) is the autopilot path and the
rule the terminal's approve RPC mirrors. A clip in ``mastered`` or ``approved`` gets one ``scheduled``
post for every account ``planning.accounts_for_clip`` picks (its connected accounts; for a Drop-in only
those under their own share), and the clip moves to ``scheduled`` through ``transition``, all in one
transaction. The time is ``--at`` (the owner's choice, taken as given) or the **free slot**
(``planning.free_slot``): the first cadence slot, from the character's ``upcoming_slot``, on a London day
on which none of those accounts has a post in ``scheduled`` / ``posting`` / ``posted`` / ``needs_check``,
so two clips for the same accounts never share a day, and (terminal v3) none within 13 days of a post of another clip of the
same family (``planning.family_days``: a drop and its versions, on any account). It refuses, writing nothing, for any other state,
for a clip with no master file, for a character with no connected account, for a Drop-in no account may
take, for a character with no slot or free day when no ``--at`` is given. A post that already exists for a
(clip, account) is kept as it is, never duplicated, so a call that was cut short can simply be repeated.

**Approval mode.** A ``mastered`` clip is the autopilot's: it is refused when ANY account it would go to
is in ``approval`` mode (the default; the owner approves those in the terminal), with the handles named
and the instruction to set the clip to ``awaiting_approval``. There is no override flag. An ``approved``
clip (the owner's yes) is scheduled whatever the account mode. Only the accounts that would get a post
count (not an unconnected one, not one a Drop-in skips).

**Idempotent.** Asking again for a clip that is already ``scheduled`` and has posts returns those posts
(and the clip) unchanged, exit 0, writing nothing and checking nothing: ``--at`` is ignored then, the
existing posts keep their times. A ``scheduled`` clip with no posts at all is refused (it is inconsistent).

**The first comment** (owner's caption playbook, 2026-10-05): one line in the character's voice that seeds a thread under the
post; the owner pins it. ``set_first_comment`` / ``clip set --first-comment-file F`` stores it as ``features['first_comment']``
(one line, 1-300 characters; the clip's JSON field, no new column), the terminal shows it next to the post text with a Copy
button (v_queue and v_tracker, migration 0010).

CLI (``studio clip ...``) prints JSON on stdout; exit 2 for anything the caller must fix
(unknown id, illegal transition, missing tags, bad value). ``clip set --state`` goes through
``transition``, so the table cannot be bypassed from the command line either. ``clip set --caption`` /
``--hashtag`` refuse (exit 2, nothing written) a caption that, composed with the AI disclosure and the
hashtags (``studio.captions``), would be over the 2,200-character post limit, carry more than 5 hashtags or a refused one
(#fyp, #foryou, #foryoupage, #viral, #explore).
"""

from __future__ import annotations

import dataclasses
import json
import math
import re
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any

import typer

from studio.captions import caption_length, compose_content
from studio.cli_support import emit, fail, open_store, parse_when, text_option
from studio.config import now_london
from studio.models import HOOK_PATTERNS, MUSIC_ARMS, Clip, ClipState, Mode, Post, PostStatus
from studio.planning import accounts_for_clip, family_days, free_slot, taken_days
from studio.store import DuplicatePost, Store, require_aware

S = ClipState

ALLOWED: dict[ClipState, set[ClipState]] = {
    S.planned: {S.generating, S.dropped},
    S.generating: {S.generated, S.gen_failed},
    S.gen_failed: {S.generating, S.dropped},
    S.generated: {S.qa_passed, S.qa_failed},
    S.qa_failed: {S.generating, S.dropped},
    S.qa_passed: {S.mastered},
    S.mastered: {S.awaiting_approval, S.scheduled},
    S.awaiting_approval: {S.approved, S.rejected},
    S.approved: {S.scheduled},
    S.scheduled: {S.posted, S.rejected},
}

REQUIRED_FEATURES = frozenset(
    {
        "format_id",
        "hook_pattern",
        "hook_text",
        "prop",
        "setting",
        "motion_type",
        "audio_arm",
        "bodies_in_frame",
        "seamless_loop",
        "eye_closeup_end",
        "trend_name",
    }
)

# ---- the learning tags (see the module doc) ----
LEARN_FEATURES = frozenset(
    {
        "hook_index",  # which of the check's hooks is on screen: 1-3 (1 = the first, the default); 0 = none of them
        "hook_by",  # who chose the hook: studio, owner (his Adjust changed it), bandit (test B, later)
        "caption_line1",
        "first_comment_kind",
        "trend_stage",
        "days_since_trend_peak",  # whole days, or None until the hits job measures it
        "sound_type",
        "sound_rising",  # true / false
        "length_s",  # the master's real length, seconds to the hundredth
        "length_bucket",
        "score_bucket",
        "score_total",  # drop.score: 0-100, or None (score_bucket none)
        "score_potential",  # 0-10 or None
        "score_swap",  # 0-10 or None
        "part",  # the part he really plays (cameo, featured, star)
        "family_id",  # the root pick's id (drop.copy_of, else the pick itself); "none" without a pick
        "version_index",  # 1 = the root, 2-3 = its versions by creation order
        "series",
        "episode",  # a whole number from 1, or None
        "hit_rules_version",  # v<N> of config/hit_rules.md the check ran under, or "none"
        "source_kind",
        "test_arms",  # what each running test assigned ({} until a test runs)
        "explore_pick",  # true / false (test A)
    }
)
MASTER_FEATURES = frozenset({"length_s", "length_bucket"})  # written by the master (set_length), not at creation
LEARN_VALUES: dict[str, tuple[Any, ...]] = {
    "format_id": ("swap_trend", "swap_classic", "swap_other", "recreate", "own_footage"),
    # the 7 patterns; "owner" = the owner's own line (none of the check's hooks), "none" = a hook nobody labelled
    "hook_pattern": (*HOOK_PATTERNS, "owner", "none"),
    "hook_by": ("studio", "owner", "bandit"),
    "caption_line1": ("label-first", "joke-first"),
    "first_comment_kind": ("vote", "question", "none"),
    "trend_stage": ("rising", "peak", "fading", "classic", "none"),
    "sound_type": ("own_trend_sound", "own_other", "ai_beat", "in_app", "none"),
    "length_bucket": ("under_8", "8_10", "11_16"),
    "score_bucket": ("none", "under_50", "50_64", "65_79", "80_up"),
    "part": ("cameo", "featured", "star"),
    "series": ("sausage_vs_trend", "household_unaware", "on_hold", "classics", "halloween_countdown", "none"),
    "source_kind": ("owner_saved", "auto_filed", "own_footage", "recreate"),
}
LEARN_BOOLS = frozenset({"sound_rising", "explore_pick"})
LEARN_NULLABLE = frozenset({"days_since_trend_peak", "episode", "score_total", "score_potential", "score_swap"})
HOOK_TAGS = ("hook_text", "hook_pattern", "hook_index", "hook_by")  # what set_hook_tags may write
_RULES_VERSION = re.compile(r"v\d+")  # gemini.hit_rules_version: v<N>, or "none"
_WHOLE_RANGES: dict[str, tuple[int, int | None]] = {  # whole numbers (never a bool) from low to high (None: no top)
    "hook_index": (0, 3), "version_index": (1, 3), "days_since_trend_peak": (0, None), "episode": (1, None),
    "score_total": (0, 100), "score_potential": (0, 10), "score_swap": (0, 10),
}

MAX_REROLLS = 1
FIRST_COMMENT_MAX_CHARS = 300

# What ``transition`` / ``set_fields`` may write besides the state. Everything else on a clip
# (id, character, source, mode, features, created_at) is fixed at creation or owned by another step.
SETTABLE_FIELDS = frozenset(
    {
        "hook",
        "caption",
        "hashtags",
        "qa",
        "master_path",
        "hf_job_id",
        "credits_reserved",
        "credits_actual",
        "reject_reason",
    }
)


def score_bucket(total: int | None) -> str:
    """The clip score's bucket (learning plan tag 9): none (no score), under_50, 50_64, 65_79, 80_up."""
    if total is None:
        return "none"
    return "under_50" if total < 50 else "50_64" if total < 65 else "65_79" if total < 80 else "80_up"


def length_bucket(seconds: float) -> str:
    """The master's length bucket (learning plan tag 8): under_8, 8_10 (8.0-10.9 s), 11_16."""
    return "under_8" if seconds < 8.0 else "8_10" if seconds < 11.0 else "11_16"


def needs_learn_tags(features: Mapping[str, Any]) -> bool:
    """A drop's clip (``drop: True``), any clip made from a pick (``fav_id``) or one that opts in with ``source_kind`` must carry
    the learning tags."""
    return features.get("drop") is True or features.get("fav_id") not in (None, "") or "source_kind" in features


def _whole(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def learn_problems(features: Mapping[str, Any]) -> list[str]:
    """What is wrong with the learning tags of ``features`` (empty = fine): every key of ``LEARN_FEATURES`` but the master's
    must be there (the master's are checked when present), each value from its vocabulary or of its type; ``score_bucket`` must
    be the bucket of ``score_total``. ``format_id`` and ``hook_pattern`` are checked against their vocabularies too."""
    p: list[str] = []
    missing = sorted(k for k in LEARN_FEATURES - MASTER_FEATURES if k not in features)
    if missing:
        p.append(f"missing feature tags: {', '.join(missing)}")
    for key in sorted((LEARN_FEATURES | LEARN_VALUES.keys()) & features.keys()):
        if (problem := _value_problem(key, features[key])) is not None:
            p.append(problem)
    total = features.get("score_total")
    if "score_bucket" in features and (total is None or _whole(total)) and features["score_bucket"] != score_bucket(total):
        p.append(f"score_bucket must be {score_bucket(total)!r} for score_total {total!r}, got {features['score_bucket']!r}")
    if features.get("score_bucket") == "none":  # no score, no score numbers
        late = [k for k in ("score_potential", "score_swap") if features.get(k) is not None]
        p.extend(f"{k} must be null when score_bucket is none" for k in late)
    if features.get("days_since_trend_peak") is not None and features.get("trend_stage") in ("none", "classic"):
        p.append(f"days_since_trend_peak must be null when trend_stage is {features['trend_stage']} (no peak to count from)")
    if features.get("episode") is not None and features.get("series") == "none":
        p.append("episode must be null when series is none")
    return p


def _value_problem(key: str, value: Any) -> str | None:
    """What is wrong with one learning tag's value on its own, or None."""
    if value is None:
        return None if key in LEARN_NULLABLE else f"{key} may not be null (\"none\" is a value where the tag has one)"
    if key in LEARN_VALUES:
        ok = isinstance(value, str) and value in LEARN_VALUES[key]
        return None if ok else f"{key} must be one of {', '.join(LEARN_VALUES[key])}, got {value!r}"
    if key in LEARN_BOOLS:
        return None if isinstance(value, bool) else f"{key} must be true or false, got {value!r}"
    if key in _WHOLE_RANGES:
        low, high = _WHOLE_RANGES[key]
        if not _whole(value) or value < low or (high is not None and value > high):
            return f"{key} must be a whole number from {low}{'' if high is None else f' to {high}'}, got {value!r}"
        return None
    if key == "length_s":
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
            return f"length_s must be a number of seconds, got {value!r}"
        return None
    if key == "family_id":
        return None if isinstance(value, str) and value.strip() else f"family_id must be a non-empty text, got {value!r}"
    if key == "hit_rules_version":
        ok = isinstance(value, str) and (value == "none" or _RULES_VERSION.fullmatch(value) is not None)
        return None if ok else f"hit_rules_version must be v<N> or none, got {value!r}"
    if key == "test_arms":
        return None if isinstance(value, Mapping) else f"test_arms must be an object ({{}} until a test runs), got {value!r}"
    if key == "hook_text":
        return None if isinstance(value, str) else f"hook_text must be text, got {value!r}"
    return None


class IllegalTransition(Exception):
    """The clip's state may not move there (not in ``ALLOWED``, or the re-roll is used up)."""


def next_states(state: ClipState) -> list[ClipState]:
    """Where a clip in ``state`` may go next, sorted by name (empty for a final state)."""
    return sorted(ALLOWED.get(state, ()), key=lambda s: s.value)


def _check_settable(fields: Mapping[str, Any]) -> None:
    bad = sorted(set(fields) - SETTABLE_FIELDS)
    if not bad:
        return
    hint = " (the state only moves through transition())" if "state" in bad else ""
    raise TypeError(f"unknown or fixed field(s) {bad}{hint}; settable: {sorted(SETTABLE_FIELDS)}")


def _state(value: ClipState | str) -> ClipState:
    try:
        return ClipState(value)
    except ValueError:
        allowed = [s.value for s in ClipState]
        raise ValueError(f"state must be one of {allowed}, got {value!r}") from None


def _rerolls(clip: Clip) -> int:
    value = clip.features.get("rerolls", 0)
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def transition(store: Store, clip_id: str, to: ClipState | str, **fields: Any) -> Clip:
    """Move the clip to ``to`` if ``ALLOWED`` says so; ``fields`` are written in the same update.

    Raises ``KeyError`` for an unknown clip, ``ValueError`` for an unknown state, ``TypeError``
    for a field outside ``SETTABLE_FIELDS``, ``IllegalTransition`` for a move the table does not
    allow or a second re-roll. A refused transition writes nothing.
    """
    to = _state(to)
    _check_settable(fields)
    with store.transaction():  # one connection: the state checked is the state updated
        clip = store.get_clip(clip_id)
        if clip is None:
            raise KeyError(clip_id)
        if to not in ALLOWED.get(clip.state, set()):
            where = ", ".join(s.value for s in next_states(clip.state)) or "nowhere, it is final"
            raise IllegalTransition(
                f"{clip.state.value} -> {to.value} is not allowed (from {clip.state.value}: {where})"
            )
        update: dict[str, Any] = dict(fields)
        if clip.state is S.qa_failed and to is S.generating:
            rerolls = _rerolls(clip)
            if rerolls >= MAX_REROLLS:
                raise IllegalTransition("max one re-roll")
            update["features"] = {**clip.features, "rerolls": rerolls + 1}
        moved = store.update_clip(clip_id, state=to, **update)
        if clip.state is S.scheduled and to in (S.rejected, S.dropped):
            _discard_unsent_posts(store, clip_id)
        return moved


def _discard_unsent_posts(store: Store, clip_id: str) -> None:
    """Delete the posts of a clip that left ``scheduled`` for good and never went out: ``scheduled`` or ``failed``,
    no platform id, no metrics snapshot. Otherwise the publisher would refuse each one (the clip is not scheduled)
    and raise a failed-post alert for a post nobody wants. ``posting``, ``needs_check`` and ``posted`` may be live: kept."""
    for post in store.list_posts(clip_id=clip_id):
        if post.status in (PostStatus.scheduled, PostStatus.failed) and not (
            post.platform_post_id or store.snapshots_for(post.id)
        ):
            store.delete_post(post.id)


def set_fields(store: Store, clip_id: str, **fields: Any) -> Clip:
    """Write non-state fields (``SETTABLE_FIELDS``) directly. ``KeyError`` for an unknown clip."""
    _check_settable(fields)
    return store.update_clip(clip_id, **fields)


def validate_first_comment(text: str) -> str:
    """The first comment, trimmed: one line of 1-300 characters (UTF-16, like the caption limit), else ``ValueError``."""
    clean = (text or "").strip()
    if not clean:
        raise ValueError("the first comment is empty: one line in the character's voice")
    if "\n" in clean or "\r" in clean:
        raise ValueError("the first comment is one line: no line breaks")
    if (n := caption_length(clean)) > FIRST_COMMENT_MAX_CHARS:
        raise ValueError(f"the first comment is {n} characters, over the {FIRST_COMMENT_MAX_CHARS} limit")
    return clean


def set_first_comment(store: Store, clip_id: str, text: str) -> Clip:
    """Store the post's first comment as ``features['first_comment']`` (the owner pins it). ``KeyError`` for an unknown clip,
    ``ValueError`` (nothing written) for a comment that is not one line of 1-300 characters. Any state: it is post text."""
    clean = validate_first_comment(text)
    clip = store.get_clip(clip_id)
    if clip is None:
        raise KeyError(clip_id)
    return store.update_clip(clip_id, features={**clip.features, "first_comment": clean})


def set_length(store: Store, clip_id: str, seconds: float) -> Clip:
    """Write the master's real length on the clip: ``features['length_s']`` (to the hundredth) and ``length_bucket`` (learning
    plan tag 8). ``KeyError`` for an unknown clip, ``ValueError`` for a length that is not a positive number. Any state: the
    master that is attached is the one measured (``master.upload_master`` calls it)."""
    if isinstance(seconds, bool) or not isinstance(seconds, (int, float)) or not math.isfinite(seconds) or seconds <= 0:
        raise ValueError(f"the master's length must be a positive number of seconds, got {seconds!r}")
    clip = store.get_clip(clip_id)
    if clip is None:
        raise KeyError(clip_id)
    length = round(float(seconds), 2)
    return store.update_clip(clip_id, features={**clip.features, "length_s": length, "length_bucket": length_bucket(length)})


def set_hook_tags(store: Store, clip_id: str, tags: Mapping[str, Any]) -> Clip:
    """Re-tag the hook the master renders (``HOOK_TAGS``: ``hook_text`` and, for a clip with the learning tags, its
    ``hook_pattern`` / ``hook_index`` / ``hook_by``): a make that resumes after a failed master renders the hook of the owner's
    latest Adjust, which may not be the one the clip was created with. The other tags are kept. ``KeyError`` for an unknown clip,
    ``ValueError`` (nothing written) for another key or a value outside its vocabulary."""
    unknown = sorted(set(tags) - set(HOOK_TAGS))
    if unknown:
        raise ValueError(f"set_hook_tags writes only {', '.join(HOOK_TAGS)}, got {', '.join(unknown)}")
    bad = [problem for key, value in tags.items() if (problem := _value_problem(key, value)) is not None]
    if bad:
        raise ValueError("bad hook tag(s): " + "; ".join(bad))
    clip = store.get_clip(clip_id)
    if clip is None:
        raise KeyError(clip_id)
    return store.update_clip(clip_id, features={**clip.features, **tags})


def set_source(store: Store, clip_id: str, source_id: str) -> Clip:
    """Link ``source_id`` to the clip, only while it is ``planned`` and only to a source that exists.

    ``KeyError`` for an unknown clip, ``ValueError`` for an unknown source or a clip past ``planned``.
    """
    with store.transaction():
        clip = store.get_clip(clip_id)
        if clip is None:
            raise KeyError(clip_id)
        if clip.state is not S.planned:
            raise ValueError(
                f"the source can only change while the clip is planned (clip {clip_id} is {clip.state.value})"
            )
        if source_id not in {s.id for s in store.list_sources()}:
            raise ValueError(f"unknown source {source_id!r}")
        return store.update_clip(clip_id, source_id=source_id)


def new_clip(
    store: Store,
    character_slug: str,
    source_id: str | None,
    mode: Mode | str,
    features: Mapping[str, Any],
) -> Clip:
    """Create a ``planned`` clip carrying its feature tags.

    Raises ``ValueError`` (and stores nothing) for a bad mode, an unknown character or source,
    a caller-set ``rerolls``, or any of ``REQUIRED_FEATURES`` absent or ``None``; the message
    lists the missing tags. A drop's clip or one that writes ``source_kind`` must also carry the learning tags
    (``learn_problems``, see the module doc).
    """
    try:
        mode = Mode(mode)
    except ValueError:
        raise ValueError(f"mode must be one of {[m.value for m in Mode]}, got {mode!r}") from None
    if not isinstance(features, Mapping):
        raise ValueError(f"features must be a mapping of tag -> value, got {type(features).__name__}")
    if "rerolls" in features:
        raise ValueError("features['rerolls'] is managed by the state machine; leave it out")
    missing = sorted(k for k in REQUIRED_FEATURES if features.get(k) is None)
    if needs_learn_tags(features):
        missing = sorted({*missing, *(k for k in LEARN_FEATURES - MASTER_FEATURES if k not in features)})
    if missing:
        raise ValueError(f"missing feature tags: {', '.join(missing)}")
    if needs_learn_tags(features) and (bad := learn_problems(features)):
        raise ValueError("bad learning tag(s): " + "; ".join(bad))
    music = features.get("music")
    if music is not None and music not in MUSIC_ARMS:
        raise ValueError(f"features['music'] must be one of {', '.join(MUSIC_ARMS)}, got {music!r}")
    if music == "original" and mode is not Mode.dropin:
        raise ValueError("features['music'] original (keep the generation's own audio) only applies to a dropin clip")
    if character_slug not in {c.slug for c in store.characters()}:
        raise ValueError(f"unknown character {character_slug!r}")
    if source_id is not None and source_id not in {s.id for s in store.list_sources()}:
        raise ValueError(f"unknown source {source_id!r}")
    return store.add_clip(
        Clip(
            character_slug=character_slug,
            source_id=source_id,
            mode=mode,
            features={**features, "rerolls": 0},
        )
    )


def schedule_clip(
    store: Store,
    clip_id: str,
    *,
    at: datetime | None = None,
    now: datetime | None = None,
) -> tuple[Clip, list[Post]]:
    """Create the posts of a ``mastered`` / ``approved`` clip and move it to ``scheduled``.

    Returns the clip and its posts (one per account, including ones that already existed; for a clip
    that is already ``scheduled``, the posts it has). See the module docstring for the rule.
    ``KeyError`` for an unknown clip; ``ValueError`` (nothing written) for a wrong state, no master file,
    no connected account, no account that may take a Drop-in, a ``mastered`` clip with a target account in
    ``approval`` mode, no slot or free day, or a naive ``at``.
    """
    if at is not None:
        require_aware(at, "schedule_clip(at)")
    now = now_london() if now is None else now
    with store.transaction():  # all of it or none of it
        clip = store.get_clip(clip_id)
        if clip is None:
            raise KeyError(clip_id)
        if clip.state is S.scheduled and (existing_posts := store.list_posts(clip_id=clip.id)):
            return clip, existing_posts  # asking twice is fine: nothing to write, nothing to bypass
        if clip.state not in (S.mastered, S.approved):
            raise ValueError(
                f"clip {clip_id} is {clip.state.value}: only a mastered or approved clip can be scheduled"
            )
        if not clip.master_path:  # the publisher would fail it three times (migration 0005 refuses it too)
            raise ValueError(f"clip {clip_id} has no master file yet: upload one before scheduling")
        slug = clip.character_slug
        if not any(a.postiz_integration_id for a in store.accounts(slug)):
            raise ValueError(
                f"no connected account for {slug!r}: no Postiz integration id yet (connect it, then run seed)"
            )
        accounts = accounts_for_clip(store, clip)
        if not accounts:
            raise ValueError(
                f"no account of {slug!r} may take this {clip.mode.value} clip: every connected account "
                "is at or over its drop-in share"
            )
        if clip.state is S.mastered and (manual := [a for a in accounts if a.mode != "auto"]):
            handles = ", ".join(a.handle for a in manual)
            raise ValueError(
                f"{handles} {'is' if len(manual) == 1 else 'are'} in approval mode: set the clip to "
                "awaiting_approval, the owner approves it in the terminal"
            )
        when = at if at is not None else free_slot(
            slug, now, store.get_settings().cadence,
            taken_days(store, [a.id for a in accounts], exclude_clip_id=clip.id) | family_days(store, clip.id),
        )  # fmt: skip
        posts: list[Post] = []
        for account in accounts:
            existing = next((p for p in store.list_posts(clip_id=clip.id) if p.account_id == account.id), None)
            if existing is None:
                try:
                    existing = store.add_post(
                        Post(clip_id=clip.id, account_id=account.id, scheduled_for=when)
                    )
                except DuplicatePost:  # another runner won the (clip, account) slot: use its post
                    existing = next(
                        p for p in store.list_posts(clip_id=clip.id) if p.account_id == account.id
                    )
            posts.append(existing)
        return transition(store, clip.id, S.scheduled), posts


# ---- CLI -----------------------------------------------------------------------------------

app = typer.Typer(
    help="Clips: create with feature tags, move through the state machine, show, list. "
    "Prints JSON; exit 2 = caller error.",
    no_args_is_help=True,
)


def _clip_json(c: Clip) -> dict[str, Any]:
    return {**dataclasses.asdict(c), "next_states": [s.value for s in next_states(c.state)]}


def _json_object(raw: str, what: str) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"{what} must be valid JSON: {e}") from None
    if not isinstance(value, dict):
        raise ValueError(f"{what} must be a JSON object, got {type(value).__name__}")
    return value


@app.command("new")
def new_command(
    character: Annotated[str, typer.Option(help="Character slug (the folder name in characters/, e.g. franz).")],
    mode: Annotated[Mode, typer.Option(help="dropin or recreate.")],
    features: Annotated[
        str | None,
        typer.Option(
            help="JSON object with every required tag: " + ", ".join(sorted(REQUIRED_FEATURES))
            + ". Use \"evergreen\" for trend_name when there is no trend."
        ),
    ] = None,
    features_file: Annotated[
        Path | None, typer.Option("--features-file", help="Same JSON, read from a file (use for any free text).")
    ] = None,
    source: Annotated[
        str | None, typer.Option(help="Source id the clip is made from (can be linked later while planned).")
    ] = None,
) -> None:
    """Create a planned clip. Refused (exit 2) when a required feature tag is missing."""
    raw = text_option(features, features_file, "features")
    if raw is None:
        fail("--features or --features-file is required")
    store = open_store()
    try:
        c = new_clip(store, character, source, mode, _json_object(raw, "--features"))
    except ValueError as e:
        fail(str(e))
    emit(_clip_json(c))


@app.command("set")
def set_command(
    id: Annotated[str, typer.Argument(help="Clip id.")],
    state: Annotated[
        ClipState | None,
        typer.Option(help="Move to this state (through the state machine; exit 2 if illegal)."),
    ] = None,
    source_id: Annotated[
        str | None,
        typer.Option("--source-id", help="Link a source: only while the clip is planned (applied before --state)."),
    ] = None,
    hook: Annotated[str | None, typer.Option(help="On-screen hook text.")] = None,
    hook_file: Annotated[Path | None, typer.Option("--hook-file", help="Hook text from a file.")] = None,
    caption: Annotated[str | None, typer.Option(help="Post caption.")] = None,
    caption_file: Annotated[Path | None, typer.Option("--caption-file", help="Caption from a file.")] = None,
    hashtag: Annotated[
        list[str] | None, typer.Option("--hashtag", help="Hashtag (repeatable); replaces the list.")
    ] = None,
    qa: Annotated[str | None, typer.Option(help="JSON object; replaces the QA record.")] = None,
    qa_file: Annotated[Path | None, typer.Option("--qa-file", help="QA JSON object from a file.")] = None,
    master_path: Annotated[str | None, typer.Option(help="Storage path of the master.")] = None,
    hf_job_id: Annotated[str | None, typer.Option(help="Higgsfield job id.")] = None,
    credits_reserved: Annotated[int | None, typer.Option(min=0, help="Credits reserved.")] = None,
    credits_actual: Annotated[int | None, typer.Option(min=0, help="Credits really spent.")] = None,
    reject_reason: Annotated[str | None, typer.Option(help="Why it was rejected.")] = None,
    first_comment: Annotated[
        str | None, typer.Option("--first-comment", help="The post's first comment (one line, the owner pins it).")
    ] = None,
    first_comment_file: Annotated[
        Path | None, typer.Option("--first-comment-file", help="The first comment from a file (use for free text).")
    ] = None,
) -> None:
    """Set a clip's state and/or fields; the state only moves along the allowed transitions."""
    hook = text_option(hook, hook_file, "hook")
    caption = text_option(caption, caption_file, "caption")
    qa = text_option(qa, qa_file, "qa")
    first_comment = text_option(first_comment, first_comment_file, "first-comment")
    if first_comment is not None:
        try:
            first_comment = validate_first_comment(first_comment)
        except ValueError as e:
            fail(str(e))
    fields: dict[str, Any] = {
        "hook": hook,
        "caption": caption,
        "hashtags": hashtag,
        "master_path": master_path,
        "hf_job_id": hf_job_id,
        "credits_reserved": credits_reserved,
        "credits_actual": credits_actual,
        "reject_reason": reject_reason,
    }
    try:
        if qa is not None:
            fields["qa"] = _json_object(qa, "--qa")
    except ValueError as e:
        fail(str(e))
    fields = {k: v for k, v in fields.items() if v is not None}
    if state is None and source_id is None and not fields and first_comment is None:
        fail("nothing to set: pass --state, --source-id and/or at least one field")
    store = open_store()
    try:
        with store.transaction():  # the source first (it needs the clip still planned), then the rest
            if "caption" in fields or "hashtags" in fields:
                current = store.get_clip(id)  # unknown clip: the writes below say so
                if current is not None:  # the text posted must fit the 2,200 limit, disclosure included
                    compose_content(
                        fields.get("caption", current.caption or ""),
                        fields.get("hashtags", current.hashtags),
                    )
            if source_id is not None:
                c = set_source(store, id, source_id)
            if state is not None:
                c = transition(store, id, state, **fields)
            elif fields:
                c = set_fields(store, id, **fields)
            if first_comment is not None:
                c = set_first_comment(store, id, first_comment)
    except KeyError:
        fail(f"unknown clip {id}")
    except IllegalTransition as e:
        fail(f"clip {id}: {e}")
    except ValueError as e:
        fail(str(e))
    emit(_clip_json(c))


@app.command("show")
def show_command(id: Annotated[str, typer.Argument(help="Clip id.")]) -> None:
    """Print one clip and where it may go next."""
    c = open_store().get_clip(id)
    if c is None:
        fail(f"unknown clip {id}")
    emit(_clip_json(c))


@app.command("list")
def list_command(
    state: Annotated[ClipState | None, typer.Option(help="Only clips in this state.")] = None,
    character: Annotated[str | None, typer.Option(help="Only this character's clips.")] = None,
    mode: Annotated[Mode | None, typer.Option(help="dropin or recreate.")] = None,
    source: Annotated[str | None, typer.Option(help="Only clips made from this source id.")] = None,
) -> None:
    """List clips, oldest first, optionally filtered."""
    filters = {
        k: v
        for k, v in {
            "state": state, "character_slug": character, "mode": mode, "source_id": source,
        }.items()
        if v is not None
    }
    emit([_clip_json(c) for c in open_store().list_clips(**filters)])


@app.command("schedule")
def schedule_command(
    id: Annotated[str, typer.Argument(help="Clip id (mastered or approved).")],
    at: Annotated[
        str | None,
        typer.Option(
            help="ISO 8601 post time (no offset = London); default: the first cadence slot on a day "
            "none of the clip's accounts posts."
        ),
    ] = None,
) -> None:
    """Create a post per account for a mastered/approved clip and move it to scheduled (autopilot).

    A mastered clip is refused (exit 2) when an account it goes to is in approval mode: set it to
    awaiting_approval and the owner approves it in the terminal. Asking again for a clip that is
    already scheduled prints its existing posts (exit 0).
    """
    when = parse_when(at, "--at") if at is not None else None
    store = open_store()
    try:
        clip, posts = schedule_clip(store, id, at=when)
    except KeyError:
        fail(f"unknown clip {id}")
    except ValueError as e:
        fail(str(e))
    emit({"clip": _clip_json(clip), "posts": posts})
