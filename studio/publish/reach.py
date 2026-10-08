"""The reach pack (terminal v3 spec section 11): the free levers every approved Reel goes out with, decided per post.

``plan_post(clip, account, accounts, config)`` is pure: it says what one due post carries, and ``publish_due`` /
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
3. **The series tag**: the character's ``style.series_tag`` (``characters/<slug>/refs.json``) joins the post's hashtags when
   there is room (``captions.with_series_tag``: never a sixth, never past 2,200 characters); every platform.
4. **Collaborators** (Instagram only): only from ``features['collab']``, a list of our OTHER characters' Instagram handles.
   Each is matched (case and ``@`` aside) against our own Instagram account rows and posted as that row's handle: a name that
   is not one of our other characters' accounts is dropped (``PostPlan.collab_dropped``), never invented, never the
   character himself. Not a list: no collaborators.
5. **Trial Reels** (Instagram only): ``config/scan.json`` ``reach.trial_reels``, a map of Instagram handle -> true / false (off
   for every account; proposed to the owner for new accounts with few followers, never switched on by the build). On: the Reel
   goes out with ``is_trial_reel`` + ``graduation_strategy: SS_PERFORMANCE``. A Reel with collaborators is never a Trial Reel
   (Instagram takes no collaborators on one): the clip's own collab wins over the account's switch.

``load_reach()`` reads the two files (``config/scan.json`` ``reach``: ``stories`` and ``trial_reels``, and every
``characters/*/refs.json`` ``style.series_tag``) and refuses, naming the key or the file, a switch that is not true or false or a
series tag that is not one live hashtag.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from studio.captions import check_series_tag, with_series_tag
from studio.clips import validate_first_comment
from studio.models import Account, Clip, Platform

ROOT = Path(__file__).resolve().parents[2]
SCAN_PATH = ROOT / "config" / "scan.json"
CHARACTERS_DIR = ROOT / "characters"

SILENT_STORY = (
    "silent master: the clip's music is in_app (the owner adds the song to the Reel in the app), so a Story of it would go "
    "out with no sound on autopilot"
)
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
    """The reach pack's settings: ``trial_reels`` (Instagram handle -> on), ``series_tags`` (character slug -> ``#tag``) and
    ``stories`` (a Reel is followed by its Story; off by default)."""

    trial_reels: Mapping[str, bool] = field(default_factory=dict)
    series_tags: Mapping[str, str] = field(default_factory=dict)
    stories: bool = False

    def trial_reel_on(self, handle: str | None) -> bool:
        if not handle:
            return False
        key = handle_key(handle)
        return any(on is True and handle_key(name) == key for name, on in self.trial_reels.items())


@dataclass(frozen=True)
class PostPlan:
    """What one due post goes out with (see the module docstring)."""

    hashtags: list[str]
    reach: Reach = NO_REACH
    story: bool = False  # an Instagram Reel: a Story of its labelled Story video follows it
    story_skip: str | None = None  # why an Instagram Reel gets no Story (None: it does, or the post is not a Reel)
    story_path: str | None = None  # the labelled Story video (bucket clips) the Story is posted from, when ``story``
    collab_dropped: tuple[str, ...] = ()  # names in features['collab'] that are not our other characters' Instagram accounts

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


def _collaborators(features: Mapping[str, Any], account: Account, accounts: Iterable[Account]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """(collaborators, dropped): ``features['collab']`` matched against our other characters' Instagram accounts."""
    raw = features.get("collab")
    if not isinstance(raw, list):
        return (), ()
    ours = {
        handle_key(a.handle): a.handle.strip().lstrip("@").strip()
        for a in accounts
        if a.platform is Platform.instagram and a.handle and a.character_slug != account.character_slug
    }
    kept: list[str] = []
    dropped: list[str] = []
    for item in raw:
        name = ours.get(handle_key(item)) if isinstance(item, str) else None
        if name is None:
            dropped.append(str(item))
        elif name not in kept:
            kept.append(name)
    return tuple(kept), tuple(dropped)


def plan_post(clip: Clip, account: Account, accounts: Iterable[Account], config: ReachConfig) -> PostPlan:
    """What the post of ``clip`` on ``account`` goes out with: its hashtags (the series tag joined when there is room) and, for an
    Instagram Reel, the first comment, the collaborators, the Trial Reel switch and the Story that follows."""
    features = clip.features or {}
    hashtags = with_series_tag(clip.caption or "", list(clip.hashtags), config.series_tags.get(clip.character_slug))
    if account.platform is not Platform.instagram:
        return PostPlan(hashtags=hashtags)
    collaborators, dropped = _collaborators(features, account, accounts)
    trial = config.trial_reel_on(account.handle) and not collaborators
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


def series_tags(characters_dir: Path | str = CHARACTERS_DIR) -> dict[str, str]:
    """Every ``<dir>/<slug>/refs.json`` ``style.series_tag``, by slug; ``ValueError`` naming the file for a bad one."""
    out: dict[str, str] = {}
    for path in sorted(Path(characters_dir).glob("*/refs.json")):
        try:
            ref = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            raise ValueError(f"{path}: cannot read refs.json: {e}") from None
        style = ref.get("style") if isinstance(ref, dict) else None
        if not isinstance(style, dict) or style.get("series_tag") is None:
            continue
        try:
            out[str(ref.get("slug") or path.parent.name)] = check_series_tag(style["series_tag"])
        except ValueError as e:
            raise ValueError(f"{path}: style.{e}") from None
    return out


def load_reach(scan_path: Path | str = SCAN_PATH, characters_dir: Path | str = CHARACTERS_DIR) -> ReachConfig:
    """The reach pack's settings from the repo's files (see the module docstring)."""
    try:
        scan = json.loads(Path(scan_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise ValueError(f"{scan_path}: cannot read it: {e}") from None
    if not isinstance(scan, Mapping):
        raise ValueError(f"{scan_path}: must be a JSON object")
    return ReachConfig(trial_reels=trial_reels(scan), series_tags=series_tags(characters_dir), stories=stories(scan))
