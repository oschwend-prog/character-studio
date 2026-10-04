"""Clip state machine and feature tags.

Every clip walks one fixed path (``ALLOWED``); ``transition`` is the only way its state moves::

    planned -> generating -> generated -> qa_passed -> mastered -> awaiting_approval -> approved
                  |  ^           |                       |               |               |
                  v  |           v                       +----> scheduled <--------------+
              gen_failed      qa_failed                              |
                  |              |                                   v
                  +--> dropped <-+                                 posted      (rejected: from
                                                                               awaiting_approval)

``rejected``, ``posted`` and ``dropped`` are final: they have no entry in ``ALLOWED``.

**Re-rolls.** A clip that failed QA may go back to ``generating`` exactly once
(``qa_failed -> generating``); ``features['rerolls']`` counts it and a second one raises
``IllegalTransition("max one re-roll")``. ``gen_failed -> generating`` is a technical retry (the
reservation was released, nothing was judged), so it does not use up the re-roll.

**Feature tags.** ``new_clip`` refuses a clip that lacks any of ``REQUIRED_FEATURES``: they are
what the weekly review learns from (``feature_lifts``), so they are set at creation and never
guessed later. A tag whose value is ``None`` counts as missing (``False`` and ``0`` are values;
use ``"evergreen"`` for ``trend_name`` when there is no trend). Extra tags are kept as given.
``rerolls`` belongs to the state machine: it starts at 0 and callers may not set it.

``transition`` and ``set_fields`` write only ``SETTABLE_FIELDS``. The state never changes through
``set_fields`` (or ``store.update_clip`` anywhere else): that is the whole point of the table.

CLI (``studio clip ...``) prints JSON on stdout; exit 2 for anything the caller must fix
(unknown id, illegal transition, missing tags, bad value). ``clip set --state`` goes through
``transition``, so the table cannot be bypassed from the command line either.
"""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Mapping
from typing import Annotated, Any

import typer

from studio.cli_support import emit, fail, open_store
from studio.models import Clip, ClipState, Mode
from studio.store import Store

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
    S.scheduled: {S.posted},
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

MAX_REROLLS = 1

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
        return store.update_clip(clip_id, state=to, **update)


def set_fields(store: Store, clip_id: str, **fields: Any) -> Clip:
    """Write non-state fields (``SETTABLE_FIELDS``) directly. ``KeyError`` for an unknown clip."""
    _check_settable(fields)
    return store.update_clip(clip_id, **fields)


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
    lists the missing tags.
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
    if missing:
        raise ValueError(f"missing feature tags: {', '.join(missing)}")
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
    character: Annotated[str, typer.Option(help="Character slug (biscuit, reginald).")],
    mode: Annotated[Mode, typer.Option(help="dropin or recreate.")],
    features: Annotated[
        str,
        typer.Option(
            help="JSON object with every required tag: " + ", ".join(sorted(REQUIRED_FEATURES))
            + ". Use \"evergreen\" for trend_name when there is no trend."
        ),
    ],
    source: Annotated[str | None, typer.Option(help="Source id the clip is made from.")] = None,
) -> None:
    """Create a planned clip. Refused (exit 2) when a required feature tag is missing."""
    store = open_store()
    try:
        c = new_clip(store, character, source, mode, _json_object(features, "--features"))
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
    hook: Annotated[str | None, typer.Option(help="On-screen hook text.")] = None,
    caption: Annotated[str | None, typer.Option(help="Post caption.")] = None,
    hashtag: Annotated[
        list[str] | None, typer.Option("--hashtag", help="Hashtag (repeatable); replaces the list.")
    ] = None,
    qa: Annotated[str | None, typer.Option(help="JSON object; replaces the QA record.")] = None,
    master_path: Annotated[str | None, typer.Option(help="Storage path of the master.")] = None,
    hf_job_id: Annotated[str | None, typer.Option(help="Higgsfield job id.")] = None,
    credits_reserved: Annotated[int | None, typer.Option(min=0, help="Credits reserved.")] = None,
    credits_actual: Annotated[int | None, typer.Option(min=0, help="Credits really spent.")] = None,
    reject_reason: Annotated[str | None, typer.Option(help="Why it was rejected.")] = None,
) -> None:
    """Set a clip's state and/or fields; the state only moves along the allowed transitions."""
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
    if state is None and not fields:
        fail("nothing to set: pass --state and/or at least one field")
    store = open_store()
    try:
        c = (
            transition(store, id, state, **fields)
            if state is not None
            else set_fields(store, id, **fields)
        )
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
