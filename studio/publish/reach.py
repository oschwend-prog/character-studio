"""The reach pack (terminal v3 spec section 11): the free levers every approved Reel goes out with, decided per post.

``plan_post(clip, account, accounts, config, live=...)`` is pure: it says what one due post carries, and ``publish_due`` /
``preview_due`` (``studio.publish.base``) both use it, so the dry run shows exactly what a real run sends.

1. **The first comment** (``Reach.first_comment``): the clip's ``features['first_comment']`` (the two-option vote,
   ``clips.set_first_comment``), sent with an **Instagram** Reel as the post's second content; Postiz posts it as the Reel's first
   comment and the owner pins it. Postiz has no comment for TikTok, so a TikTok post carries none. A first comment that is not
   one line of 1-300 characters (``clips.validate_first_comment``; ``clip set`` never writes one) is left out, never a failed Reel.
2. **The Story**: an Instagram Reel is followed by a Story (``PostPlan.story``) of the clip's **labelled Story video**
   (``features['story_path']``: the master with the AI label burned in, ``master.render_story``; a Story shows no caption, so
   the plain master would go out undisclosed and is never used). ``PostPlan.story_skip`` says why there is none, checked in this
   order: ``reach.stories`` is off ("stories are off", the default), a Story of the clip is already recorded
   (``features['story']``), a silent master (``features['music'] == 'in_app'``: the owner adds the song to the Reel in the app,
   a Story would go out silent on autopilot, CLAUDE.md), a Trial Reel ("trial reel: followers see it only if it graduates") or
   no Story video ("no labelled story video").
3. **The series tag** is NOT added here: it is written into the clip's own hashtags when the clip is made (``studio.drop`` at
   Make it, ``clip set``; ``captions.with_series_tag``), so the text the owner previews is the text that goes out.
4. **Collaborators** (Instagram only): only from ``features['collab']``, a list of our OTHER characters' Instagram handles.
   Each is matched (case and ``@`` aside) against our own Instagram account rows and posted as that row's handle: a name that
   is not the Instagram account of another character who is ``live`` and has a Postiz integration is dropped
   (``PostPlan.collab_dropped``), never invented, never the character himself; at most ``MAX_COLLABORATORS`` (3, Instagram's
   limit) are kept, in the clip's order, and the rest are listed in ``collab_dropped`` too. Not a list: no collaborators.
5. **Trial Reels** (Instagram only): ``config/scan.json`` ``reach.trial_reels``, a map of Instagram handle -> true / false (off
   for every account; the owner's tick that the account can post Trial Reels, never switched on by the build). On: the Reel
   goes out with ``is_trial_reel`` + ``graduation_strategy: SS_PERFORMANCE``. A Reel with collaborators is never a Trial Reel
   (Instagram takes no collaborators on one): the clip's own collab wins over the account's switch. **The switch is also the
   eligibility for test C** (``config/experiments.json``, learning plan 3.4; ``ReachConfig.trial_test``): while test C is ``on``
   a clip made under it carries ``features['test_arms']['trial']`` (true / false, a block coin of 2 and 2 in every 4 per
   character, ``studio.experiments``) and its Reel goes out as a Trial Reel exactly when the account is ELIGIBLE (its switch is
   true) AND that arm is true. On an account that is not eligible the Reel is a normal one (``trial_reel`` false) and the arm
   stays recorded on the clip: the test never reaches an account the owner has not cleared. A clip with no such arm (made
   before the test, or a Recreate), or one whose arm is not true / false, falls back to the account's switch alone. The
   collaborator rule still wins.
   **A refusal is never a lost post** (``PostizPublisher.publish``): when Postiz refuses a Trial Reel synchronously (a definite
   4xx, nothing was created) the same Reel is posted once more as a normal one; ``PublishResult.trial_refused`` carries the
   reason, ``publish_due`` plans the post again with ``normal_reel=True`` (``trial_reel`` false, no Trial Story skip) and
   records the reason on the clip (``features['trial_refused']``).

``load_reach()`` reads ``config/scan.json`` ``reach`` (``stories`` and ``trial_reels``) and the test registry
(``config/experiments.json``, whether test C is on) and refuses, naming the key, a switch that is not true or false, a
``trial_reels`` key that is no Instagram handle of ``characters/*/refs.json`` (a typo would silently leave the switch off) and a
registry that cannot be read or breaks a rule: the run stops, nothing is posted. A character's ``style.series_tag`` is not read
here.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Collection, Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from studio.clips import validate_first_comment
from studio.experiments import load_experiments
from studio.models import Account, Clip, Platform

ROOT = Path(__file__).resolve().parents[2]
SCAN_PATH = ROOT / "config" / "scan.json"
CHARACTERS_DIR = ROOT / "characters"

SILENT_STORY = (
    "silent master: the clip's music is in_app (the owner adds the song to the Reel in the app), so a Story of it would go "
    "out with no sound on autopilot"
)
MAX_COLLABORATORS = 3  # Instagram's limit on collaborators of one Reel
STORIES_OFF = "stories are off"
TRIAL_STORY = "trial reel: followers see it only if it graduates"
NO_STORY_VIDEO = "no labelled story video"


@dataclass(frozen=True)
class Reach:
    """The levers one post carries besides its text (all Instagram only; a TikTok post carries ``NO_REACH``)."""

    first_comment: str | None = None
    collaborators: tuple[str, ...] = ()
    trial_reel: bool = False


NO_REACH = Reach()


def handle_key(handle: str) -> str:
    """An account handle as compared: no ``@``, no spaces around it, lower case."""
    return handle.strip().lstrip("@").strip().lower()


@dataclass(frozen=True)
class ReachConfig:
    """The reach pack's settings: ``trial_reels`` (Instagram handle -> on), ``stories`` (a Reel is followed by its Story; off
    by default) and ``trial_test`` (test C is on)."""

    trial_reels: Mapping[str, bool] = field(default_factory=dict)
    stories: bool = False
    trial_test: bool = False  # test C is on: a clip's own coin (features['test_arms']['trial']) decides its Trial Reel

    def trial_reel_on(self, handle: str | None) -> bool:
        if not handle:
            return False
        key = handle_key(handle)
        return any(on is True and handle_key(name) == key for name, on in self.trial_reels.items())

    def trial_for(self, features: Mapping[str, Any], handle: str | None) -> bool:
        """Does this clip's Reel go out as a Trial Reel? The account's switch is the eligibility (the owner's tick that it can
        post Trial Reels). Test C on and the clip carries its coin (``test_arms.trial`` true or false): eligible AND the coin;
        an account that is not eligible never gets a Trial Reel from the coin. Otherwise the account's switch alone."""
        eligible = self.trial_reel_on(handle)
        arms = features.get("test_arms")
        arm = arms.get("trial") if isinstance(arms, Mapping) else None
        if self.trial_test and isinstance(arm, bool):
            return eligible and arm
        return eligible


@dataclass(frozen=True)
class PostPlan:
    """What one due post goes out with (see the module docstring)."""

    hashtags: list[str]
    reach: Reach = NO_REACH
    story: bool = False  # an Instagram Reel: a Story of its labelled Story video follows it
    story_skip: str | None = None  # why an Instagram Reel gets no Story (None: it does, or the post is not a Reel)
    story_path: str | None = None  # the labelled Story video (bucket clips) the Story is posted from, when ``story``
    collab_dropped: tuple[str, ...] = ()  # names in features['collab'] that are not sent (see ``_collaborators``)

    def summary(self) -> dict[str, Any]:
        """The JSON the run summary and the dry run show (the first comment's text stays on the clip)."""
        return {
            "first_comment": self.reach.first_comment is not None,
            "collaborators": list(self.reach.collaborators),
            "collab_dropped": list(self.collab_dropped),
            "trial_reel": self.reach.trial_reel,
            "story": self.story_skip if self.story_skip else self.story,
        }


def _first_comment(features: Mapping[str, Any]) -> str | None:
    raw = features.get("first_comment")
    if not isinstance(raw, str):
        return None
    try:
        return validate_first_comment(raw)
    except ValueError:
        return None


def _collaborators(
    features: Mapping[str, Any], account: Account, accounts: Iterable[Account], live: Collection[str]
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """(collaborators, dropped): ``features['collab']`` matched against the Instagram accounts of OUR OTHER characters who are
    ``live`` (``live``: their slugs) and have a Postiz integration (an account that cannot post is no partner), at most
    ``MAX_COLLABORATORS`` of them, in the clip's order. Everything else, an eligible name over the limit included, is dropped."""
    raw = features.get("collab")
    if not isinstance(raw, list):
        return (), ()
    ours = {
        handle_key(a.handle): a.handle.strip().lstrip("@").strip()
        for a in accounts
        if a.platform is Platform.instagram and a.handle and a.postiz_integration_id
        and a.character_slug != account.character_slug and a.character_slug in live
    }
    kept: list[str] = []
    dropped: list[str] = []
    for item in raw:
        name = ours.get(handle_key(item)) if isinstance(item, str) else None
        if name is None or (name not in kept and len(kept) >= MAX_COLLABORATORS):
            dropped.append(str(item))
        elif name not in kept:
            kept.append(name)
    return tuple(kept), tuple(dropped)


def plan_post(
    clip: Clip, account: Account, accounts: Iterable[Account], config: ReachConfig, *, live: Collection[str],
    normal_reel: bool = False,
) -> PostPlan:
    """What the post of ``clip`` on ``account`` goes out with: its hashtags exactly as stored (the series tag is part of them since
    the clip was made) and, for an Instagram Reel, the first comment, the collaborators (``live``: the slugs of the characters
    who are live, the only possible partners), the Trial Reel switch and the Story that follows. ``normal_reel``: the Trial Reel
    was refused and the Reel went out as a normal one, so plan it as one (no Trial Reel, no Trial Story skip)."""
    features = clip.features or {}
    hashtags = list(clip.hashtags)
    if account.platform is not Platform.instagram:
        return PostPlan(hashtags=hashtags)
    collaborators, dropped = _collaborators(features, account, accounts, live)
    trial = config.trial_for(features, account.handle) and not collaborators and not normal_reel
    reach = Reach(first_comment=_first_comment(features), collaborators=collaborators, trial_reel=trial)
    video = features.get("story_path")
    video = video if isinstance(video, str) and video.strip() else None
    skip: str | None
    if not config.stories:
        skip = STORIES_OFF
    elif features.get("story") is not None:
        skip = f"a Story of this clip is already recorded ({_story_status(features['story'])}): never a second one"
    elif features.get("music") == "in_app":
        skip = SILENT_STORY
    elif trial:
        skip = TRIAL_STORY
    elif video is None:
        skip = NO_STORY_VIDEO
    else:
        skip = None
    return PostPlan(
        hashtags=hashtags, reach=reach, story=skip is None, story_skip=skip, story_path=video if skip is None else None,
        collab_dropped=dropped,
    )


def _story_status(marker: Any) -> str:
    return str(marker.get("status")) if isinstance(marker, Mapping) else "unreadable"


# ---- the configuration -------------------------------------------------------------------------------------------------


def stories(scan: Mapping[str, Any]) -> bool:
    """``config/scan.json`` ``reach.stories`` (absent: off); ``ValueError`` for anything but true or false."""
    block = scan.get("reach", {})
    on = block.get("stories", False) if isinstance(block, Mapping) else False
    if not isinstance(on, bool):
        raise ValueError(f"config/scan.json reach.stories must be true or false, got {on!r:.40}")
    return on


def trial_reels(scan: Mapping[str, Any]) -> dict[str, bool]:
    """``config/scan.json`` ``reach.trial_reels`` (keys starting with ``_`` are notes); ``ValueError`` naming the key."""
    block = scan.get("reach", {})
    if not isinstance(block, Mapping):
        raise ValueError(f"config/scan.json reach must be an object with trial_reels, got {block!r:.60}")
    switches = block.get("trial_reels", {})
    if not isinstance(switches, Mapping):
        raise ValueError(f"config/scan.json reach.trial_reels must be an object of handle -> true/false, got {switches!r:.60}")
    out: dict[str, bool] = {}
    for handle, on in switches.items():
        if str(handle).startswith("_"):
            continue
        if not isinstance(on, bool):
            raise ValueError(f"config/scan.json reach.trial_reels.{handle} must be true or false, got {on!r:.40}")
        out[handle_key(str(handle))] = on
    return out


def instagram_handles(characters_dir: Path | str = CHARACTERS_DIR) -> set[str]:
    """Every Instagram handle the roster has or plans (``handle`` and ``planned_handle`` of the ``instagram`` accounts in
    ``<dir>/*/refs.json``, as ``handle_key``). A refs.json that cannot be read is skipped with a warning on stderr: that can only
    make a ``trial_reels`` key look unknown (the run then stops), never hide a typo."""
    found: set[str] = set()
    for path in sorted(Path(characters_dir).glob("*/refs.json")):
        try:
            ref = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            print(f"warning: {path}: cannot read refs.json ({e}); its handles are not known to the reach pack", file=sys.stderr)
            continue
        for acc in (ref.get("accounts") or []) if isinstance(ref, dict) else []:
            if isinstance(acc, dict) and acc.get("platform") == "instagram":
                found.update(handle_key(h) for h in (acc.get("handle"), acc.get("planned_handle")) if isinstance(h, str) and h.strip())
    return found


def load_reach(
    scan_path: Path | str = SCAN_PATH, characters_dir: Path | str = CHARACTERS_DIR, experiments_path: Path | str | None = None,
) -> ReachConfig:
    """The reach pack's settings from the repo's files (see the module docstring). ``ValueError`` (the CLI exits 2, nothing is
    posted) for a switch that is not true or false, for a ``trial_reels`` key that is no Instagram handle of the roster (a typo
    there would silently leave a Trial Reel switch off) and for a test registry (``experiments_path``, default
    ``studio.experiments.EXPERIMENTS_PATH``) that cannot be read or breaks a rule."""
    try:
        scan = json.loads(Path(scan_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise ValueError(f"{scan_path}: cannot read it: {e}") from None
    if not isinstance(scan, Mapping):
        raise ValueError(f"{scan_path}: must be a JSON object")
    switches = trial_reels(scan)
    if switches:
        known = instagram_handles(characters_dir)
        if unknown := sorted(h for h in switches if h not in known):
            raise ValueError(
                f"config/scan.json reach.trial_reels.{unknown[0]}: no character has an Instagram account with that handle "
                f"(known: {', '.join(sorted(known)) or 'none'}); fix the key, a typo would leave the switch off"
                + (f" ({len(unknown) - 1} more unknown)" if len(unknown) > 1 else "")
            )
    registry = load_experiments(experiments_path)
    return ReachConfig(trial_reels=switches, stories=stories(scan), trial_test=registry.test("C").on)
