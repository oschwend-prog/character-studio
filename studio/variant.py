"""``studio clip variant``: the same generated dance video, mastered again with a NEW hook, as a clip of its own (owner 2026-10-28).

There are no video credits, and a Reel that was posted can be posted again: every Reel of the three accounts is an Instagram Trial
Reel now (``config/scan.json`` ``reach.trial_reels``, shown to non-followers only). A repost must not be the same picture: the hook
pill is on the first frame, which Instagram takes as the cover (``master.with_cover_frame``), so a new hook is a new cover and a new
Reel. ``studio.posts`` has unique(clip_id, account_id), so the repost needs a clip row of its own: nothing is generated, nothing is
reserved (credits 0), the original clip is only read.

**Refused (exit 2, nothing written)**: an original that is not ``posted``; a hook that is empty, has more than one line, has emoji
or symbols the pill's fonts cannot draw, is longer than the character's pill holds (``master.hook_fits``: two lines of
``overlays.PILL_MAX_LINES`` at the smallest size the pill shrinks to) or is the original's own line (case and spaces aside); an
original that already has a variant that is not ``dropped`` / ``rejected`` (one repost per clip); no generation to master from;
a master spec the original left that cannot be read or has an intro hook over a close-up; the audio rule of ``master.audio_problem``.

**The generation** (the dance before any overlay), in this order: ``--gen FILE``; ``renders/<original id>/gen.mp4`` (or the other file
of that folder the original's spec.json names as its dance: ``gen_audio.mp4``, the generation with its sound put back); the Higgsfield
output URL recorded on the original's pick (``proposal.drop.make.output_url``, kept at least 7 days by Higgsfield), downloaded into
``renders/<new id>/gen.mp4`` (``higgsfield_api.download_output``: only a Higgsfield-hosted https URL, no key); else "no generation
for <id>: pass --gen".

**The master** is the original's again but for the hook: when ``renders/<original id>/spec.json`` exists its MasterSpec is reused with
only ``hook2`` replaced (and ``dance``, ``out`` and ``clip_id`` set for the new clip; an ``audio`` that was the dance stays the
dance); otherwise it is built as a Drop-in master is (``drop.master_spec``: the character's kit from refs.json, music ``original``,
the edits of tests G and H that the original's ``test_arms`` asked for). ``renders/<new id>/`` keeps the spec, the master and, for a
download, the generation.

**The new clip** (``clips.new_clip``): the original's character, source, mode and features, credits 0, but not what describes the
original's POST or its outcome or its place in a test (``NOT_COPIED``): ``story*``, ``trial_reel`` / ``trial_refused``, ``collab*``
(a week's collaborator is the make's, ``studio.collab``), ``first_comment_posted``, ``outlier_x``, the master's own records
(``length_*``, the edit record), ``rerolls`` / ``regenerate_*``, and the test membership: ``test_arms`` is ``{}`` and ``drop`` is left
out. A repost is not a new draw of the hook bandit, a new coin position of a block test (a clip that ever carried a key takes a
position of its block, and an extra one breaks the 2 and 2 in every 4 for the clips made after it) or a second observation of the
score test (``weekly.score_observations`` counts posted drops); ``variant_of`` marks it and ``drop.explore_turn`` /
``drop.next_engagement`` skip it. The hook tags are re-written: ``hook_text``, and for a clip with the learning tags
``hook_pattern`` / ``hook_index`` when the new line is one of the check's hooks (else ``none`` / 0), ``hook_by`` ``variant``
(``clips.LEARN_VALUES``: never tallied by the bandit). The caption, hashtags and first comment are the original's.

**The state path** is the one every clip walks: planned -> generating -> generated -> (master built, checked, uploaded) -> qa_passed
-> mastered, through ``clips.transition``, with ``qa`` = ``{"pass": true, "variant_of": <original>, "note": ...}``. The master is
uploaded while the clip is still ``generated`` so that a failure can drop it cleanly (``qa_failed`` -> ``dropped``; ``qa_passed``
has no way out but ``mastered``): a failed build leaves a dropped clip, not a stuck one, and the original may be varianted again.
Scheduling and approval are the usual ones (``clip set --state``, ``clip schedule``).
"""

from __future__ import annotations

import dataclasses
import json
import logging
import shutil
import tempfile
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from studio import clips, drop, higgsfield_api, seed
from studio.captions import compose_content
from studio.media import master, overlays
from studio.media.master import MasterRejected, MasterSpec
from studio.media.qa import QAError, check_master, probe
from studio.models import Clip, ClipState, Favorite
from studio.storage import Storage, StorageError
from studio.store import Store

log = logging.getLogger("studio.variant")

S = ClipState
ROOT = Path(__file__).resolve().parents[1]
RENDERS = "renders"
QA_NOTE = "same generation as the posted original"

# What a variant does not inherit from its original (see the module doc).
NOT_COPIED = frozenset(
    {
        # the original's post(s) and what came of them
        "story", "story_path", "story_reshares", "trial_reel", "trial_refused", "first_comment_posted", "outlier_x",
        "collab", "collab_auto", "collab_by",
        # the state machine's and the master's own records: the new clip counts and measures its own
        "rerolls", "regenerate_of", "regenerate_note", "length_s", "length_bucket", "zoom_pulses", "hook_entrance", "beats",
        # the tests: a repost is no new draw (test_arms is set to {}; ``drop`` is what test A's observations are read from)
        "test_arms", "drop",
        # re-written for the new line
        "hook_text", "hook_pattern", "hook_index", "hook_by", "variant_of",
    }
)
_GIVE_UP: dict[ClipState, tuple[ClipState, ...]] = {  # how a clip that cannot go on leaves the path (clips.ALLOWED)
    S.planned: (S.dropped,),
    S.generating: (S.gen_failed, S.dropped),
    S.gen_failed: (S.dropped,),
    S.generated: (S.qa_failed, S.dropped),
    S.qa_failed: (S.dropped,),
}


class VariantRefused(ValueError):
    """The caller must fix something (exit 2); nothing was written."""


class VariantFailed(RuntimeError):
    """Our side failed after the variant's clip was made (exit 1): the clip was dropped, the original may be varianted again."""


def clean_hook(raw: str | None) -> str:
    """The new hook as it is stored: one line, spaces collapsed. ``VariantRefused`` for an empty one, one with line breaks or one
    the pill's fonts cannot draw (emoji, pictographs: ``overlays.drawable`` would silently leave them out of the picture)."""
    text = (raw or "").strip()
    if not text:
        raise VariantRefused("the hook is empty: write the new on-screen line in the hook file")
    if "\n" in text or "\r" in text:
        raise VariantRefused("the hook is one line: no line breaks")
    text = " ".join(text.split())
    if overlays.drawable(text) != text:
        raise VariantRefused("the hook has an emoji or a symbol the pill's fonts cannot draw: take it out")
    return text


def renders_dir(original_id: str, root: Path | str | None = None) -> Path:
    """The ``renders`` folder to work in: the one that holds the original's own folder (the repo's, else the current directory's:
    a checkout without the media can still run against the Mac's folder), else the repo's. ``root`` is the repo's folder
    (default ``ROOT``, read at call time)."""
    top = ROOT if root is None else Path(root)
    for base in (top / RENDERS, Path.cwd() / RENDERS):
        if (base / original_id).is_dir():
            return base
    return top / RENDERS


def _pick_of(store: Store, clip: Clip) -> Favorite | None:
    """The clip's pick: ``features.fav_id``, else the oldest pick that names the clip."""
    fav_id = clip.features.get("fav_id")
    if isinstance(fav_id, str) and fav_id:
        pick = store.get_favorite(fav_id)
        if pick is not None:
            return pick
    return next(iter(store.list_favorites(clip_id=clip.id)), None)


def _check_original(store: Store, original: Clip, hook: str) -> None:
    """The refusals that need only the database (``VariantRefused``)."""
    if original.state is not S.posted:
        raise VariantRefused(f"clip {original.id} is {original.state.value}: only a posted clip can be reposted as a variant")
    for line in (original.hook, original.features.get("hook_text")):
        if drop._same_line(line, hook):
            raise VariantRefused(f"the hook is the original's own line ({hook!r}): a variant needs a new one")
    live = [
        c for c in store.list_clips(character_slug=original.character_slug)
        if c.features.get("variant_of") == original.id and c.state not in (S.dropped, S.rejected)
    ]  # fmt: skip
    if live:
        raise VariantRefused(
            f"clip {original.id} already has a variant ({live[0].id}, {live[0].state.value}): one repost per clip; "
            "drop or reject that one first"
        )


def _hook_tags(pick: Favorite | None, hook: str) -> dict[str, Any]:
    """The hook tags of the variant: the pattern and place of the line among the check's hooks (``drop._hook_tags``) when it is
    one of them, else ``none`` and 0 (a line nobody labelled); ``hook_by`` is always ``variant``."""
    look: dict[str, Any] = {}
    d: dict[str, Any] = {}
    if pick is not None and drop.is_drop(pick.proposal):
        d = drop.drop_of(pick)
        look = d.get("deconstruct") or {}
    found = drop._hook_tags(d, look, hook)
    matched = found["hook_index"] > 0
    return {
        "hook_pattern": found["hook_pattern"] if matched else "none",
        "hook_index": found["hook_index"] if matched else 0,
        "hook_by": "variant",
    }


def variant_features(original: Clip, pick: Favorite | None, hook: str) -> dict[str, Any]:
    """The features of the variant's clip (see the module doc)."""
    features = {k: v for k, v in original.features.items() if k not in NOT_COPIED}
    tags = _hook_tags(pick, hook)
    if "hook_index" not in original.features:  # a clip made before the learning tags has no place to give (hook_pattern is required)
        del tags["hook_index"]
    return {**features, **tags, "hook_text": hook, "test_arms": {}, "variant_of": original.id}


def _fetch_output(
    original: Clip, pick: Favorite | None, download: Callable[..., Path], into: Path
) -> Path | None:
    """The pick's Higgsfield output downloaded to ``into / gen.mp4``; None when the drop recorded none."""
    d = pick.proposal.get("drop") if pick is not None else None
    url = ((d.get("make") if isinstance(d, Mapping) else None) or {}).get("output_url")
    if not (isinstance(url, str) and url.strip()):
        return None
    try:
        return download(url, into / "gen.mp4")
    except (ValueError, higgsfield_api.HiggsfieldError) as e:
        raise VariantRefused(
            f"no generation for {original.id}: pass --gen (the output recorded on its drop could not be downloaded: {str(e)[:160]})"
        ) from None


def find_generation(
    original: Clip, pick: Favorite | None, gen: Path | str | None, base: Path, download: Callable[..., Path], scratch: Path
) -> Path:
    """The generated dance video, in the order of the module doc (a download lands in ``scratch``)."""
    if gen is not None:
        path = Path(gen)
        if not path.is_file():
            raise VariantRefused(f"no such file: {path}")
        return path.resolve()
    folder = base / original.id
    named = _spec_dance(folder, base.parent)
    for own in (named, folder / "gen.mp4"):
        if own is not None and own.is_file():
            return own
    fetched = _fetch_output(original, pick, download, scratch)
    if fetched is None:
        raise VariantRefused(f"no generation for {original.id}: pass --gen")
    return fetched


def _spec_dance(folder: Path, root: Path) -> Path | None:
    """The dance file the original's own master spec names when it is another file of the original's folder (``gen_audio.mp4``: the
    generation with its sound put back, which is the one to master from), else None."""
    try:
        data = json.loads((folder / "spec.json").read_text(encoding="utf-8"))
        dance = _resolved(data["dance"], root)
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return dance if dance.parent == folder and dance.name != "gen.mp4" else None


def _resolved(raw: Any, root: Path) -> Path:
    path = Path(str(raw))
    return path if path.is_absolute() else root / path


def _reused_spec(data: Mapping[str, Any], root: Path, dance: Path, hook: str, out: Path, preset: str | None) -> MasterSpec:
    """The original's master spec with only the hook (and where the dance is, and the output) changed."""
    if data.get("closeup") and data.get("hook1"):
        raise VariantRefused(
            "the original's master has an intro hook over a close-up (hook1): a variant cannot say which line to replace; "
            "remove its renders/<id>/spec.json to build the variant as a Drop-in master"
        )
    new: dict[str, Any] = {k: v for k, v in data.items() if k != "clip_id"}
    old_dance = _resolved(data["dance"], root) if data.get("dance") else None
    old_audio = _resolved(data["audio"], root) if data.get("audio") else None
    new.update(dance=str(dance), hook2=drop.hook_lines(hook), out=str(out))
    if old_audio is not None:  # the generation's own sound follows the generation; any other audio stays where it was
        new["audio"] = str(dance) if old_dance is not None and old_audio == old_dance else str(old_audio)
    if new.get("closeup"):
        new["closeup"] = str(_resolved(new["closeup"], root))
    if preset is not None:
        new["preset"] = preset
    try:
        return master.spec_from_json(new)
    except ValueError as e:
        raise VariantRefused(f"the original's master spec is not valid: {e}") from None


def _draft_spec(
    original: Clip, hook: str, dance: Path, base: Path, out: Path, preset: str | None, characters_dir: Path | str
) -> MasterSpec:
    """The master spec of the variant for ``dance`` (its clip id is set once the clip exists): the original's, if it left one,
    else a Drop-in master's (``drop.master_spec``)."""
    path = base / original.id / "spec.json"
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            raise VariantRefused(f"cannot read the original's master spec {path}: {e}") from None
        if not isinstance(data, dict):
            raise VariantRefused(f"{path} must be a JSON object")
        return _reused_spec(data, base.parent, dance, hook, out, preset)
    try:
        ref, _ = drop.character(original.character_slug, characters_dir)
        return drop.master_spec(
            slug=original.character_slug, ref=ref, gen=dance, hook=hook, out=out, clip_id=None,
            test_arms=original.features.get("test_arms"), preset=preset or drop.MASTER_PRESET,
        )
    except QAError as e:
        raise VariantRefused(f"the generation {dance} cannot be read: {e}") from None
    except ValueError as e:  # DropError (no refs.json for the character) and a bad style kit
        raise VariantRefused(str(e)) from None


def _spec_json(spec: MasterSpec) -> dict[str, Any]:
    """``spec`` as the JSON ``master build --spec`` reads (paths as text)."""
    return json.loads(json.dumps(dataclasses.asdict(spec), default=str))


def _give_up(store: Store, clip_id: str, original_id: str, reason: str) -> None:
    """Take a variant that cannot go on off the path: the way out ``clips.ALLOWED`` has for the state it is in, ``dropped`` last."""
    try:
        for to in _GIVE_UP.get(store.get_clip(clip_id).state, ()):
            fields = {"qa": {"pass": False, "variant_of": original_id, "problems": [reason[:300]]}} if to is S.qa_failed else {}
            if to is S.dropped:
                fields["reject_reason"] = reason[:300]
            clips.transition(store, clip_id, to, **fields)
    except Exception:  # noqa: BLE001 - the caller reports the real failure; a clip left on the path is visible in clip list
        log.exception("variant: could not drop clip %s", clip_id)


def make_variant(
    store: Store,
    storage: Storage,
    original_id: str,
    hook: str,
    *,
    gen: Path | str | None = None,
    root: Path | str | None = None,
    preset: str | None = None,
    characters_dir: Path | str = seed.DEFAULT_CHARACTERS_DIR,
    download: Callable[..., Path] | None = None,
) -> dict[str, Any]:
    """Make the variant of the posted clip ``original_id`` with ``hook`` (see the module doc) and return
    ``{clip_id, variant_of, hook, master_path, story_path}``.

    ``KeyError`` for an unknown clip, ``VariantRefused`` (nothing written, or the clip dropped) for anything the caller must fix,
    ``VariantFailed`` when the build or the upload failed (the variant's clip is dropped). ``root`` is the repo's folder (it holds
    ``renders/``; default ``ROOT``); ``preset`` the x264 preset (None: the original's spec, else ``slow``); ``download(url, dest)`` fetches a Higgsfield output
    (default ``higgsfield_api.download_output``, looked up at call time).
    """
    hook = clean_hook(hook)
    original = store.get_clip(original_id)
    if original is None:
        raise KeyError(original_id)
    _check_original(store, original, hook)
    pick = _pick_of(store, original)
    base = renders_dir(original.id, root)
    caption = original.caption or hook
    hashtags = list(original.hashtags)
    try:
        compose_content(caption, hashtags)  # the 2,200 limit, 5 tags, no refused tag: before anything is written
    except ValueError as e:
        raise VariantRefused(f"the original's caption cannot be posted again: {e}") from None
    scratch = Path(tempfile.mkdtemp(prefix="studio-variant-"))
    new: Clip | None = None
    try:
        dance = find_generation(original, pick, gen, base, download or higgsfield_api.download_output, scratch)
        draft = _draft_spec(original, hook, dance, base, scratch / "master.mp4", preset, characters_dir)
        try:
            fits = master.hook_fits(draft)
        except ValueError as e:
            raise VariantRefused(str(e)) from None
        if not fits:
            raise VariantRefused(
                f"the hook is too long for the pill ({len(hook)} characters): it would need more than "
                f"{overlays.PILL_MAX_LINES} lines even at the smallest type; shorten it"
            )
        with store.transaction():
            store.get_settings()  # the settings row lock: two runs never both make the one variant of a clip
            fresh = store.get_clip(original.id)
            if fresh is None:
                raise KeyError(original_id)
            _check_original(store, fresh, hook)
            try:
                new = clips.new_clip(
                    store, original.character_slug, original.source_id, original.mode, variant_features(fresh, pick, hook)
                )
            except ValueError as e:
                raise VariantRefused(f"the new clip was refused: {e}") from None
        out_dir = base / new.id
        out_dir.mkdir(parents=True, exist_ok=True)
        if dance.parent == scratch:  # a download: it belongs to the new clip
            dance = Path(shutil.move(str(dance), out_dir / "gen.mp4"))
        spec = dataclasses.replace(
            draft, dance=dance, audio=dance if draft.audio == draft.dance else draft.audio, out=out_dir / "master.mp4", clip_id=new.id
        )
        return _master_and_walk(store, storage, original, pick, new, spec, hook, caption, hashtags)
    except (VariantRefused, VariantFailed) as e:
        if new is not None:
            _give_up(store, new.id, original.id, str(e))
        raise
    except (master.MasterError, MasterRejected, QAError, StorageError, OSError, ValueError) as e:
        reason = f"the variant could not be mastered ({type(e).__name__}: {str(e)[:200]})"
        if new is not None:
            _give_up(store, new.id, original.id, reason)
        raise VariantFailed(reason) from None
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def _master_and_walk(
    store: Store, storage: Storage, original: Clip, pick: Favorite | None, new: Clip, spec: MasterSpec, hook: str, caption: str,
    hashtags: list[str],
) -> dict[str, Any]:
    """From ``planned`` to ``mastered``: the transitions, the audio rule, the build, the check and the upload."""
    (spec.out.parent / "spec.json").write_text(json.dumps(_spec_json(spec), indent=2) + "\n", encoding="utf-8")
    clips.transition(store, new.id, S.generating)
    clips.transition(store, new.id, S.generated, credits_actual=0)  # nothing was generated or paid: the original's output is used again
    clip = store.get_clip(new.id)
    source = next(iter(store.list_sources(id=clip.source_id)), None) if clip.source_id else None
    owner_music = pick.proposal.get("owner_music") if pick is not None else None
    if spec.audio is not None and (problem := master.audio_problem(spec.dance, spec.audio, clip, source, owner_music)) is not None:
        raise VariantRefused(f"the audio rule refused the master: {problem}")
    built = master.build_master(spec)
    problems = check_master(probe(built), silent=spec.music == "in_app")
    if problems:
        raise VariantFailed("the master missed the spec: " + "; ".join(problems)[:200])
    if spec.edits is not None and spec.applied:  # tests G, H: what the master really shows (the original's edits, again)
        clips.set_edit_tags(store, new.id, spec.applied)
    master.upload_master(store, storage, new.id, built)  # also the Story video while Stories are on
    clips.transition(
        store, new.id, S.qa_passed, qa={"pass": True, "variant_of": original.id, "note": QA_NOTE}
    )
    done = clips.transition(store, new.id, S.mastered, hook=hook, caption=caption, hashtags=hashtags)
    return {
        "clip_id": done.id,
        "variant_of": original.id,
        "hook": hook,
        "master_path": done.master_path,
        "story_path": done.features.get("story_path"),
    }
