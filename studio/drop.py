"""``studio drop``: a video the owner drops is animated into our character in the cloud ("Drop a video", plan 2026-10-06).

Owner: "keep the terminal simpler. I will drop in videos and it will animate for our characters", "it should happen even when
the Mac is closed" and "always check with me if we generate new videos". Genjutsu is used the way Higgsfield designed it:
**Object swap** keeps the clip's setting, camera, timing and sound and replaces its star, like for like (refs.json ``swap``:
Reginald replaces a person, Biscuit a dog or a small animal).

**A drop is a pick** (``favorites``, origin ``owner``, status ``approved``) carrying ``proposal['drop']``. The terminal files it
with the ``studio.add_drop`` RPC (migration 0012): a file drop is keyed ``owner-drop:<pick id>`` (platform ``drop``) and its
video goes to Storage ``sources/owner/<pick id>/<file>`` (``attach_clip``); a pasted link is the canonical TikTok / Instagram /
YouTube URL. ``studio.request_job(pick, kind)`` (security definer, pg_net + the Vault secret ``github_dispatch_token``) records
the request and fires the ``studio-drop`` GitHub workflow, which runs ``studio drop process`` or ``studio drop make``; a
2-hourly ``studio drop sweep`` picks up anything left pending. ``drop.state`` moves::

    uploading -> checking -> ready -----------(Make it: request_job make)----------> making -> made
                    |   \\-> blocked (a child, a watermark, burned-in text, the wrong star, too short)    \\-> failed
                    \\-> waiting (a link the cloud could not fetch: the daily run on the Mac tries again)

``reason`` carries the one line the card shows (blocked, waiting, failed, or what a making job waits for).

**Process** (``process_drop``, free): the clip (``source ingest-owner`` for a file, ``source fetch`` with no Recreate fallback
for a link), a probe, the free local analysis (``source analyze``: cuts, beat, the best window), the Gemini **deconstruct**
(``studio.gemini``: people, the star and where, a child, a watermark or handle, burned-in text, setting, what happens, his part,
gadgets from the traits card, 3 hooks in the bible voice, a playbook caption, a first comment, hashtags) or, without the key, the
one the daily run wrote by hand (``--deconstruct-file``), the checks, the window (``drop_window``: a classic 12-15 s, any other
clip 8-10 s, inside one shot, on the beat), the crop of a landscape clip around the star, the price (``planning.estimate_credits``
for the window) and a preview strip in ``sources/owner/<pick id>/preview.jpg`` (the owner's browser may read ``owner/``). Then
``ready``.

**Make** (``make_drop``, paid, ONLY after the owner's Make it): refused unless ``proposal['make_requested']`` is the owner's
record (``{"at", "by": "owner"}``, written only by ``request_job``; nothing in this CLI writes it). The owner's Adjust
(``drop['adjust']``: who is replaced, his part, gadgets, hook, section start and length, crop) overrides the defaults. A clip is
created (``clip new``, ``fav_id`` = the pick, the pick ``queued``), the window trimmed and cropped (at least 409,600 pixels a
frame), the credits reserved (``budget.reserve``: the monthly cap and the kill switch refuse), then the **Higgsfield API**
(``studio.higgsfield_api``): our signed URL, the character's master + sheet of the star's body + close-up (refs.json
``reference_urls``), a SHORT prompt ("replace the <star> with the <noun> from the reference images" + his part + gadgets),
1080p. It is polled up to 25 minutes (longer: the next sweep polls again, never resubmits). Completed: the output is
downloaded, the credits settled (the API reports no cost: the estimate for the trimmed seconds is booked), ``qa tech``, the
original audio muxed back if it was lost, the Gemini frame QA (a leftover person, a watermark, a child, the eyes), one automatic
re-roll on a fail then stop, the master (``closeup: null``, music ``original``, the hook on screen), the upload, the caption +
first comment + hashtags of the deconstruct (playbook: a searchable title, the joke, a rotating engagement line, the credit),
``awaiting_approval``. The card then follows the 8 tracker steps of "In the works".

**Resumable and one at a time.** Every step reads where the clip is (its state, ``drop['make']``) and goes on from there, so a
run that dies, a poll that times out or a missing key is picked up again by the next run. A run claims the pick
(``drop['job']``, a lease of ``LEASE_MINUTES`` taken under the settings row lock) and a second run on the same pick answers
``busy``. The submit is never repeated blindly: the Idempotency-Key and the exact body are stored before the POST, and an
uncertain submit is looked up with them (``higgsfield_api``).

**By hand, until the keys exist** (the daily-run skill): without ``GEMINI_API_KEY`` a process stops at ``checking`` ("waiting
for the Gemini key") with the source and the analysis stored, and ``drop process <pick> --deconstruct-file F`` finishes it with
the deconstruct the run wrote after looking at the contact sheet. Without ``HF_API_KEY_ID`` / ``HF_API_KEY_SECRET`` a make
stops at ``making`` ("waiting for the Higgsfield key"); ``drop make <pick> --prepare`` reserves, trims and prints the inputs of
the MCP Object swap, and ``drop make <pick> --generated-file F --credits N`` goes on from the downloaded output (the frame QA by
hand with ``--qa-file``).

CLI (``studio drop ...``) prints JSON. Exit 0 when the step was recorded (whatever the drop's state), 1 when a job stopped on a
failure it recorded (the JSON says), 2 for anything the caller must fix, 3 when the budget refused the reservation.
"""

from __future__ import annotations

import json
import math
import os
import shutil
import socket
import tempfile
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Annotated, Any

import typer

from studio import budget, clips, fetch, gemini, seed, sources
from studio.budget import BudgetRefused
from studio.captions import compose_content
from studio.cli_support import emit, fail, open_storage, open_store, text_option
from studio.config import now_london
from studio.favorites import DROP_PLATFORM, DROP_URL_PREFIX, is_drop, mark_favorite, parse_video_url, validate_analysis
from studio.higgsfield_api import (
    HiggsfieldClient,
    HiggsfieldError,
    PollTimeout,
    SubmitUncertain,
)
from studio.media import clipwork
from studio.media.analyze import AnalysisError, analyze_clip
from studio.media.master import MasterSpec, audio_problem, build_master, upload_master
from studio.media.qa import QAError, check_master, contact_sheet, frame_sheet, probe
from studio.models import Body, Clip, ClipState, Favorite, Mode, Source
from studio.planning import estimate_credits
from studio.storage import Storage, StorageError
from studio.store import Store

S = ClipState
DROP_STATES = ("uploading", "checking", "waiting", "ready", "blocked", "making", "made", "failed")
PROCESS_FROM = frozenset({"uploading", "checking", "waiting"})
PARTS = ("cameo", "featured", "star")
ADJUST_KEYS = ("star", "part", "gadgets", "hook", "start_s", "length_s", "crop_x")
WINDOW_CLASSIC = (12.0, 15.0)  # owner 2026-10-05: a classic keeps its whole recognisable section
WINDOW_OTHER = (8.0, 10.0)
MASTER_MIN_S = 6.0  # the master spec
MASTER_MAX_S = 16.0
WINDOW_STEP_S = 0.5
SLACK_S = 0.15
LEASE_MINUTES = 45
SIGNED_URL_S = 6 * 3600
HOOK_ON_SCREEN_S = 4.0
HOOK_LINE_CHARS = 22
MUSIC = "original"  # the clip keeps its own sound (owner decision 2026-10-05)
MASTER_PRESET = "slow"
SOURCES_BUCKET = sources.SOURCES_BUCKET
PREVIEW_NAME = "preview.jpg"
ENGAGEMENT_ORDER = gemini.ENGAGEMENT_KINDS  # send -> question -> tease -> send ...
STAR_WORDS = {"person": "a person", "dog": "a dog", "animal": "a small animal"}

EXIT_FAILED = 1
EXIT_REFUSED = 3


class DropError(ValueError):
    """A drop the caller asked about cannot take this step (not a drop, the wrong state, no Make it): exit 2."""


# ---- reading a drop ------------------------------------------------------------------------------------------------------


def drop_of(pick: Favorite) -> dict[str, Any]:
    d = pick.proposal.get("drop")
    if not isinstance(d, Mapping):
        raise DropError(f"pick {pick.id} is not a dropped video (no proposal.drop)")
    return dict(d)


def _load(store: Store, pick_id: str) -> Favorite:
    pick = store.get_favorite(pick_id)
    if pick is None:
        raise KeyError(pick_id)
    drop_of(pick)
    if not pick.character_slug:
        raise DropError(f"pick {pick_id} has no character")
    return pick


def _moment(raw: Any) -> datetime | None:
    if not isinstance(raw, str):
        return None
    try:
        at = datetime.fromisoformat(raw)
    except ValueError:
        return None
    return at if at.tzinfo is not None else None


def owner_requested_make(pick: Favorite) -> bool:
    """Did the owner tap Make it: ``proposal['make_requested']`` is ``{"at": <aware ISO time>, "by": "owner"}`` (request_job)."""
    rec = pick.proposal.get("make_requested")
    return isinstance(rec, Mapping) and rec.get("by") == "owner" and _moment(rec.get("at")) is not None


def _update(store: Store, pick: Favorite, now: datetime, *, status: str | None = None, **drop_changes: Any) -> Favorite:
    """Merge ``drop_changes`` into ``proposal['drop']`` (``at`` moves when the state does) and write it through ``fav mark``."""
    current = store.get_favorite(pick.id) or pick
    drop = {**drop_of(current), **drop_changes}
    if "state" in drop_changes and drop_changes["state"] != drop_of(current).get("state"):
        drop["at"] = now.isoformat()
    if drop.get("state") not in DROP_STATES:
        raise ValueError(f"drop.state must be one of {', '.join(DROP_STATES)}, got {drop.get('state')!r}")
    drop = {k: v for k, v in drop.items() if v is not None or k == "reason"}
    return mark_favorite(store, pick.id, status or current.status, proposal={**current.proposal, "drop": drop})


# ---- one run per pick ------------------------------------------------------------------------------------------------------


def job_id() -> str:
    """Who is running: the GitHub run, else this machine and process."""
    run = os.environ.get("GITHUB_RUN_ID")
    return f"gh-{run}-{os.environ.get('GITHUB_RUN_ATTEMPT', '1')}" if run else f"{socket.gethostname()}-{os.getpid()}"


def claim(store: Store, pick_id: str, kind: str, job: str, now: datetime) -> bool:
    """Take the pick for this run (``drop['job']``), unless another run holds a lease younger than ``LEASE_MINUTES``.

    Taken under the settings row lock (``get_settings`` inside a transaction locks it on Postgres, the same lock the budget
    uses), so two runners never both take it."""
    with store.transaction():
        store.get_settings()
        pick = _load(store, pick_id)
        held = drop_of(pick).get("job")
        if isinstance(held, Mapping) and held.get("by") != job:
            since = _moment(held.get("at"))
            if since is not None and now - since < timedelta(minutes=LEASE_MINUTES):
                return False
        drop = {**drop_of(pick), "job": {"kind": kind, "by": job, "at": now.isoformat()}}
        store.update_favorite(pick.id, proposal={**pick.proposal, "drop": drop})
    return True


def release(store: Store, pick_id: str, job: str) -> None:
    pick = store.get_favorite(pick_id)
    if pick is None or not is_drop(pick.proposal):
        return
    drop = drop_of(pick)
    held = drop.get("job")
    if isinstance(held, Mapping) and held.get("by") == job:
        drop.pop("job")
        store.update_favorite(pick.id, proposal={**pick.proposal, "drop": drop})


# ---- the character -----------------------------------------------------------------------------------------------------------


def character(slug: str, characters_dir: Path | str = seed.DEFAULT_CHARACTERS_DIR) -> tuple[dict[str, Any], gemini.Character]:
    """``(refs.json, the prompts' view of the character)``: the swap rule, the voice and keywords of the bible, the traits card."""
    refs = {r["slug"]: r for r in seed.load_refs(characters_dir)}
    ref = refs.get(slug)
    if ref is None:
        raise DropError(f"no characters/{slug}/refs.json")
    swap = ref.get("swap")
    if not swap:
        raise DropError(f"characters/{slug}/refs.json has no swap rule (noun, stars)")
    bible_path = Path(characters_dir) / slug / "bible.md"
    bible = bible_path.read_text(encoding="utf-8") if bible_path.is_file() else ""
    return ref, gemini.Character(
        slug=slug, name=ref["name"], noun=swap["noun"], stars=tuple(swap["stars"]),
        voice=gemini.bible_section(bible, "Voice (captions)"), keywords=gemini.bible_section(bible, "Search keywords"),
        traits=ref.get("traits") or {},
    )


def like_for_like(star: Mapping[str, Any], ref: Mapping[str, Any], name: str) -> str | None:
    """Why this star cannot be swapped for the character (the blocked line), or None."""
    kind = star.get("kind")
    allowed = ref["swap"]["stars"]
    if kind == "none":
        return "nobody to replace: the clip has no clear star"
    if kind not in allowed:
        wants = " or ".join(STAR_WORDS[s] for s in allowed)
        return f"the wrong star: {name} replaces {wants}, this clip's star is {STAR_WORDS.get(kind, kind)}"
    if star.get("body") not in ref["bodies"]:
        return f"the wrong star: {name} has no {star.get('body')} body"
    return None


# ---- the window ----------------------------------------------------------------------------------------------------------------


def _shots(cuts: list[float], duration: float) -> list[tuple[float, float]]:
    edges = [0.0, *sorted(c for c in cuts if 0 < c < duration), duration]
    return [(a, b) for a, b in zip(edges, edges[1:]) if b > a]


def drop_window(analysis: Mapping[str, Any], *, classic: bool, duration: float) -> dict[str, float]:
    """The section Genjutsu gets: ``{start_s, length_s}`` (pure).

    The target is 12-15 s for a classic and 8-10 s for any other clip (owner 2026-10-05), never over 16 s or under 6 s. It
    stays inside one shot when one is long enough (the analysis' cuts), else in the longest shot (at least 6 s), else it
    crosses as few cuts as it must. Among the windows that qualify, the one with the most motion wins (the analysis' energy per
    0.5 s), ties to the longer then the earlier; the ends move to the nearest beats when that keeps the length in range. A
    clip shorter than 6 s is refused (``ValueError``)."""
    if duration < MASTER_MIN_S - SLACK_S:
        raise ValueError(f"the video is {duration:.1f} s: a video needs at least {MASTER_MIN_S:g} s")
    lo, hi = WINDOW_CLASSIC if classic else WINDOW_OTHER
    motion = analysis.get("motion") if isinstance(analysis.get("motion"), Mapping) else {}
    energy = [float(e) for e in motion.get("energy", [])]
    step = float(motion.get("step_s", WINDOW_STEP_S)) or WINDOW_STEP_S
    cuts = [float(c) for c in motion.get("cuts", [])]
    audio = analysis.get("audio") if isinstance(analysis.get("audio"), Mapping) else {}
    beats = [float(b) for b in audio.get("beats", [])]
    total = min(duration, 600.0)

    def mean_energy(a: float, b: float) -> float:
        part = energy[int(round(a / step)) : int(round(b / step))]
        return sum(part) / len(part) if part else 0.0

    def inside(a: float, b: float) -> int:
        return sum(1 for c in cuts if a + 0.3 < c < b - 0.3)

    hi = min(hi, MASTER_MAX_S, total)
    lo = min(lo, hi)
    longest_shot = max((b - a for a, b in _shots(cuts, total)), default=total)
    if longest_shot < lo:  # no shot is long enough: shorten to the longest shot (never under 6 s)
        lo = max(MASTER_MIN_S, math.floor(longest_shot / WINDOW_STEP_S) * WINDOW_STEP_S)
        hi = max(lo, min(hi, lo))
    best: tuple[int, float, float, float] | None = None  # (cuts, -energy, -length, start)
    length = lo
    while length <= hi + 1e-9:
        start = 0.0
        while start + length <= total + 1e-9:
            key = (inside(start, start + length), -round(mean_energy(start, start + length), 6), -length, start)
            if best is None or key < best:
                best = key
            start += WINDOW_STEP_S
        length += WINDOW_STEP_S
    assert best is not None
    start, length = best[3], -best[2]
    if beats:
        s2 = min(beats, key=lambda b: abs(b - start))
        e2 = min(beats, key=lambda b: abs(b - (start + length)))
        if abs(s2 - start) <= 0.35 and abs(e2 - start - length) <= 0.35 and lo - 1e-9 <= e2 - s2 <= hi + 1e-9 and e2 <= total + 1e-9:
            if inside(s2, e2) <= best[0]:
                start, length = s2, e2 - s2
    return {"start_s": round(start, 3), "length_s": round(length, 3)}


def crop_for(width: int, height: int, x_center: float | None) -> float | None:
    """The ``--crop-x`` of a landscape clip (the star's centre, kept inside the frame); None for a vertical one."""
    if width <= height * 9 / 16 + 1:
        return None
    x = 0.5 if x_center is None else float(x_center)
    return round(min(max(x, 0.0), 1.0), 3)


# ---- the owner's Adjust ----------------------------------------------------------------------------------------------------------


def validate_adjust(adjust: Any, drop: Mapping[str, Any]) -> dict[str, Any]:
    """The owner's Adjust of a ready drop (``drop['adjust']``, written by request_job), checked again here (fail closed).

    Every key optional: ``star`` (1-80 characters: who is replaced), ``part`` (cameo, featured or star), ``gadgets`` (at most 3
    of 1-40 characters), ``hook`` (1-80 characters), ``start_s`` (0 or more) and ``length_s`` (6-16 s, inside the video),
    ``crop_x`` (0-1 or null). ``ValueError`` names the first problem."""
    if adjust is None:
        return {}
    if not isinstance(adjust, Mapping):
        raise ValueError("adjust must be an object")
    unknown = sorted(set(adjust) - set(ADJUST_KEYS))
    if unknown:
        raise ValueError(f"adjust has unknown key(s) {', '.join(unknown)}")
    out: dict[str, Any] = {}

    def text(key: str, limit: int) -> None:
        v = adjust[key]
        if not isinstance(v, str) or not v.strip() or len(v.strip()) > limit or "\n" in v:
            raise ValueError(f"adjust.{key} must be one line of 1-{limit} characters")
        out[key] = v.strip()

    def number(key: str) -> float:
        v = adjust[key]
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
            raise ValueError(f"adjust.{key} must be a number")
        return float(v)

    if "star" in adjust:
        text("star", 80)
    if "hook" in adjust:
        text("hook", 80)
    if "part" in adjust:
        if adjust["part"] not in PARTS:
            raise ValueError(f"adjust.part must be one of {', '.join(PARTS)}")
        out["part"] = adjust["part"]
    if "gadgets" in adjust:
        g = adjust["gadgets"]
        if not isinstance(g, list) or len(g) > 3 or not all(isinstance(x, str) and 0 < len(x.strip()) <= 40 for x in g):
            raise ValueError("adjust.gadgets must be at most 3 items of 1-40 characters")
        out["gadgets"] = [x.strip() for x in g]
    window = drop.get("window") or {}
    duration = float(drop.get("duration_s") or 0)
    start = number("start_s") if "start_s" in adjust else float(window.get("start_s", 0.0))
    length = number("length_s") if "length_s" in adjust else float(window.get("length_s", 0.0))
    if "start_s" in adjust or "length_s" in adjust:
        if start < 0:
            raise ValueError("adjust.start_s must be 0 or more")
        if not MASTER_MIN_S <= length <= MASTER_MAX_S:
            raise ValueError(f"adjust.length_s must be {MASTER_MIN_S:g}-{MASTER_MAX_S:g} s")
        if duration and start + length > duration + SLACK_S:
            raise ValueError(f"the section {start:g}-{start + length:g} s runs past the end of the {duration:g} s video")
        out["start_s"], out["length_s"] = start, length
    if "crop_x" in adjust:
        if adjust["crop_x"] is None:
            out["crop_x"] = None
        else:
            c = number("crop_x")
            if not 0 <= c <= 1:
                raise ValueError("adjust.crop_x must be from 0 to 1")
            w, h = int(drop.get("width") or 0), int(drop.get("height") or 0)
            if w and h and crop_for(w, h, c) is None:
                raise ValueError("adjust.crop_x: the video is already vertical, there is nothing to crop")
            out["crop_x"] = c
    return out


def effective(drop: Mapping[str, Any]) -> dict[str, Any]:
    """What the make job uses: the process job's choices with the owner's Adjust on top."""
    adjust = validate_adjust(drop.get("adjust"), drop)
    window = drop.get("window") or {}
    star = drop.get("star") or {}
    return {
        "star": adjust.get("star", star.get("description")),
        "body": star.get("body"),
        "part": adjust.get("part", drop.get("part", "featured")),
        "gadgets": adjust.get("gadgets", drop.get("gadgets", [])),
        "hook": adjust.get("hook", drop.get("hook")),
        "start_s": adjust.get("start_s", float(window.get("start_s", 0.0))),
        "length_s": adjust.get("length_s", float(window.get("length_s", 0.0))),
        "crop_x": adjust["crop_x"] if "crop_x" in adjust else drop.get("crop_x"),
    }


def swap_prompt(star: str, noun: str, part: str, gadgets: list[str]) -> str:
    """The SHORT Object swap prompt (Higgsfield's own form): who is replaced, by whom, his part, his gadgets."""
    lines = [f"Replace {star.strip().rstrip('.')} with the {noun} from the reference images."]
    lines.append({
        "cameo": "Keep his motion minimal and natural; the scene stays the same.",
        "featured": "He follows the original performer's motion exactly; the scene stays the same.",
        "star": "He performs every beat with full energy; the scene stays the same.",
    }[part])
    if gadgets:
        lines.append(f"He wears or holds: {', '.join(gadgets)} (no brand logos).")
    return " ".join(lines)


def hook_lines(hook: str) -> list[str]:
    """The on-screen hook in at most two lines of about ``HOOK_LINE_CHARS`` characters (the overlay shrinks a long one)."""
    words = hook.split()
    if len(hook) <= HOOK_LINE_CHARS or len(words) < 2:
        return [hook]
    best = min(range(1, len(words)), key=lambda i: abs(len(" ".join(words[:i])) - len(" ".join(words[i:]))))
    return [" ".join(words[:best]), " ".join(words[best:])]


def caption_text(pick: Favorite, deconstruct: Mapping[str, Any], kind: str) -> str:
    """The post caption by the owner's formula: the searchable title, the joke, one engagement line of ``kind``, the credit."""
    cap = deconstruct["caption"]
    lines = [cap["title"], cap["joke"], cap[kind]]
    if pick.creator_handle:
        lines.append(f"trend: {pick.creator_handle}")
    return "\n".join(lines)


def next_engagement(store: Store, slug: str, clip_id: str | None = None) -> str:
    """The engagement line's kind for the character's next post: the one after the kind of its latest clip that has one."""
    latest = None
    for c in store.list_clips(character_slug=slug):
        if c.id != clip_id and c.features.get("engagement_kind") in ENGAGEMENT_ORDER:
            latest = c.features["engagement_kind"]
    if latest is None:
        return ENGAGEMENT_ORDER[0]
    return ENGAGEMENT_ORDER[(ENGAGEMENT_ORDER.index(latest) + 1) % len(ENGAGEMENT_ORDER)]


# ---- adding a drop (the terminal's RPC does the same: studio.add_drop, migration 0012) ----------------------------------------


def add_drop(
    store: Store, character_slug: str, link: str | None, now: datetime | None = None, *, own_footage: bool = False
) -> tuple[Favorite, bool]:
    """File a drop: ``(pick, duplicate)``. A file (``link`` None) is a new pick keyed ``owner-drop:<id>`` at ``uploading``; a link
    is its canonical URL at ``checking``, and a link already a pick of this character becomes that pick's drop (a pick already
    queued or made is returned as it is, ``duplicate`` True). ``own_footage`` (owner 2026-10-06, for reporting later): the owner's
    own recording or footage used with permission; the default is a downloaded clip (False). It does not change the generation."""
    now = now or now_london()
    if character_slug not in {c.slug for c in store.characters()}:
        raise ValueError(f"unknown character {character_slug!r}")
    record = {"decision": "approve", "by": "owner", "reason": "owner's own video", "at": now.isoformat()}
    if link is None:
        pick_id = str(uuid.uuid4())
        drop = {"state": "uploading", "kind": "file", "at": now.isoformat(), "reason": None, "own_footage": bool(own_footage)}
        return store.add_favorite(Favorite(
            id=pick_id, url=f"{DROP_URL_PREFIX}{pick_id}", platform=DROP_PLATFORM, origin="owner", character_slug=character_slug,
            proposal={"decision": record, "drop": drop}, status="approved",
        )), False  # fmt: skip
    platform, canonical = parse_video_url(link)
    drop = {"state": "checking", "kind": "link", "at": now.isoformat(), "reason": None, "own_footage": bool(own_footage)}
    handle = canonical.split("/@", 1)[1].split("/", 1)[0] if platform == "tiktok" else None
    for f in store.list_favorites(url=canonical, character_slug=character_slug):
        if f.status in ("queued", "made"):
            return f, True
        proposal = {k: v for k, v in f.proposal.items() if k != "hold_reason"}
        proposal.update(decision=record, drop=drop)
        return store.update_favorite(f.id, status="approved", proposal=proposal), True
    return store.add_favorite(Favorite(
        url=canonical, platform=platform, origin="owner", character_slug=character_slug,
        creator_handle=f"@{handle}" if handle else None, proposal={"decision": record, "drop": drop}, status="approved",
    )), False  # fmt: skip


def set_own_footage(store: Store, pick_id: str, own_footage: bool) -> Favorite:
    """The owner's toggle (``studio.set_drop_footage``, migration 0012): ``drop['own_footage']``, for reporting; any state."""
    pick = _load(store, pick_id)
    if not isinstance(own_footage, bool):
        raise ValueError("own_footage must be true or false")
    return store.update_favorite(pick.id, proposal={**pick.proposal, "drop": {**drop_of(pick), "own_footage": own_footage}})


# ---- process -------------------------------------------------------------------------------------------------------------------


@dataclass
class Outcome:
    pick_id: str
    state: str
    reason: str | None = None
    ok: bool = True
    detail: dict[str, Any] | None = None

    def json(self) -> dict[str, Any]:
        return {"pick_id": self.pick_id, "state": self.state, "reason": self.reason, "ok": self.ok, **(self.detail or {})}


def _source(store: Store, source_id: str) -> Source:
    found = next(iter(store.list_sources(id=source_id)), None)
    if found is None:
        raise DropError(f"source {source_id} is gone")
    return found


def _fetch_local(storage: Storage, src: Source, folder: Path, name: str) -> Path:
    if not src.storage_path:
        raise DropError(f"source {src.id} is not in Storage any more")
    return storage.download(SOURCES_BUCKET, src.storage_path, folder / f"{name}{Path(src.storage_path).suffix or '.mp4'}")


def _get_source(store: Store, storage: Storage, pick: Favorite, now: datetime, runner: Any) -> Source | Outcome:
    """The pick's full clip as a source: the owner's upload, or the pasted link fetched once (a failure: ``waiting``)."""
    if pick.source_id:
        found = next(iter(store.list_sources(id=pick.source_id)), None)
        if found is not None and found.storage_path:
            return found
    if pick.proposal.get("owner_clip_path"):
        try:
            return sources.ingest_owner_clip(store, storage, pick.id)
        except ValueError as e:
            pick = _update(store, pick, now, state="blocked", reason=str(e))
            return Outcome(pick.id, "blocked", str(e))
    if pick.platform == DROP_PLATFORM:
        return Outcome(pick.id, drop_of(pick)["state"], "the upload has not finished", detail={"waiting_for": "upload"})
    try:
        result = fetch.fetch_pick_clip(store, storage, pick.id, runner=runner, fall_back=False)
    except fetch.FetchFailed as e:
        reason = f"the link could not be fetched in the cloud ({str(e)[:120]}): the Mac's daily run tries again"
        _update(store, pick, now, state="waiting", reason=reason)
        return Outcome(pick.id, "waiting", reason)
    return _source(store, result["source_id"])


def _analysis_card(answer: Mapping[str, Any], free: Mapping[str, Any], window: Mapping[str, float]) -> dict[str, Any]:
    card = {
        "people_count": int(answer["people_count"]), "main_subject": answer["star"]["description"][:80],
        "camera": answer["camera"], "watermark": bool(answer["watermark"]), "overlay": bool(answer["burned_in_text"]),
        "minors": bool(answer["minors"]),
        "best_window": {"start_s": window["start_s"], "end_s": round(window["start_s"] + window["length_s"], 3)},
        "bpm": free.get("audio", {}).get("bpm"),
    }
    if answer.get("notes"):
        card["notes"] = answer["notes"][:500]
    validate_analysis(card)
    return card


def _blocked_reason(answer: Mapping[str, Any], ref: Mapping[str, Any], name: str, link: bool) -> str | None:
    if answer["minors"]:
        return "a child is in the clip: we never use it"
    if answer["watermark"]:
        return (
            "a watermark or creator handle is burned in: we cannot use this clip"
            if link else "a watermark or creator handle is burned in: paste the link instead"
        )
    if answer["burned_in_text"]:
        return "text is burned into the picture: Genjutsu would keep it, drop a clean copy"
    return like_for_like(answer["star"], ref, name)


def process_drop(
    store: Store,
    storage: Storage,
    pick_id: str,
    *,
    gemini_client: gemini.GeminiClient | None,
    deconstruct_answer: Mapping[str, Any] | None = None,
    runner: Any = None,
    now: datetime | None = None,
    job: str | None = None,
    characters_dir: Path | str = seed.DEFAULT_CHARACTERS_DIR,
) -> Outcome:
    """Check a dropped video (free) and make it ``ready`` (see the module doc). ``KeyError`` for an unknown pick, ``DropError``
    for a pick that is not a drop or not at a step a check runs from; ``StorageError`` when our own Storage fails."""
    now = now or now_london()
    job = job or job_id()
    pick = _load(store, pick_id)
    state = drop_of(pick)["state"]
    if state not in PROCESS_FROM:
        raise DropError(f"pick {pick_id} is {state}: a check runs on an uploading, checking or waiting drop")
    if not claim(store, pick_id, "process", job, now):
        return Outcome(pick_id, state, "another run is checking this video", detail={"busy": True})
    try:
        return _process(store, storage, store.get_favorite(pick_id), gemini_client, deconstruct_answer, runner, now, characters_dir)
    except (DropError, StorageError):
        raise
    except Exception as e:
        reason = f"the check stopped: {type(e).__name__}: {str(e)[:160]}"
        _update(store, store.get_favorite(pick_id), now, state="failed", reason=reason)
        return Outcome(pick_id, "failed", reason, ok=False)
    finally:
        release(store, pick_id, job)


def _process(
    store: Store, storage: Storage, pick: Favorite, client: gemini.GeminiClient | None,
    answer: Mapping[str, Any] | None, runner: Any, now: datetime, characters_dir: Path | str,
) -> Outcome:
    ref, who = character(pick.character_slug, characters_dir)
    got = _get_source(store, storage, pick, now, runner)
    if isinstance(got, Outcome):
        return got
    src = got
    pick = store.get_favorite(pick.id)
    with tempfile.TemporaryDirectory(prefix="studio-drop-") as tmp:
        work = Path(tmp)
        local = _fetch_local(storage, src, work, "clip")
        try:
            report = probe(local, loudness=False)
        except QAError as e:
            reason = f"not a readable video: {str(e)[:120]}"
            _update(store, pick, now, state="blocked", reason=reason, source_id=src.id)
            return Outcome(pick.id, "blocked", reason)
        if report.duration_s < MASTER_MIN_S - SLACK_S:
            reason = f"the video is {report.duration_s:.1f} s: a video needs at least {MASTER_MIN_S:g} s"
            _update(store, pick, now, state="blocked", reason=reason, source_id=src.id)
            return Outcome(pick.id, "blocked", reason)
        try:
            free = analyze_clip(local, work / "analysis.png")
        except AnalysisError as e:
            reason = f"the video could not be analysed: {e}"
            _update(store, pick, now, state="blocked", reason=reason, source_id=src.id)
            return Outcome(pick.id, "blocked", reason)
        basics = {
            "source_id": src.id, "duration_s": round(report.duration_s, 3), "width": report.width, "height": report.height,
            "has_audio": report.has_audio,
        }
        if answer is not None:
            problems = gemini.deconstruct_problems(answer, who)
            if problems:
                raise DropError("the deconstruct file breaks the rules: " + "; ".join(problems))
            look = gemini.tidy_deconstruct(answer, who)
        elif client is None:
            reason = "waiting for the Gemini key: the next daily run looks at it by hand"
            _update(store, pick, now, state="checking", reason=reason, **basics)
            return Outcome(pick.id, "checking", reason, detail={**basics, "best_window": free["best_window"]})
        else:
            proxy = clipwork.proxy_clip(local, work / "proxy.mp4")
            try:
                look = gemini.deconstruct(client, proxy, who)
            except gemini.GeminiBlocked as e:
                reason = f"Gemini would not look at this clip ({e}): we cannot use it"
                _update(store, pick, now, state="blocked", reason=reason, **basics)
                return Outcome(pick.id, "blocked", reason)
            except gemini.GeminiError as e:
                reason = f"the look at the clip failed ({str(e)[:140]}): tap Try again"
                _update(store, pick, now, state="failed", reason=reason, **basics)
                return Outcome(pick.id, "failed", reason, ok=False)
        sources.record_checks(
            store, src.id, has_watermark=look["watermark"], has_overlay=look["burned_in_text"],
            other_people=max(0, look["people_count"] - 1), has_minors=look["minors"],
        )
        if look["star"]["body"] in (b.value for b in Body):
            store.update_source(src.id, body=look["star"]["body"])
        blocked = _blocked_reason(look, ref, who.name, pick.platform != DROP_PLATFORM)
        if blocked is not None:
            _update(store, pick, now, state="blocked", reason=blocked, **basics, star=look["star"])
            return Outcome(pick.id, "blocked", blocked)
        window = drop_window(free, classic=look["classic"], duration=report.duration_s)
        crop_x = crop_for(report.width, report.height, look["star"]["x_center"])
        credits = estimate_credits(Mode.dropin, window["length_s"], MUSIC)
        preview = _preview(storage, local, work, pick.id, window, crop_x)
    card = _analysis_card(look, free, window)
    hook = look["hooks"][0]
    proposal = {
        **pick.proposal, "mode": "dropin", "owner_mode": "dropin", "hook": hook, "concept": look["what_happens"],
        "analysis": card,
        "drop": {
            **drop_of(pick), **basics, "state": "ready", "reason": None, "at": now.isoformat(),
            "window": window, "crop_x": crop_x, "star": look["star"], "classic": look["classic"],
            "part": look["suggested_part"], "gadgets": look["gadgets"], "hooks": look["hooks"], "hook": hook,
            "deconstruct": look, "music": MUSIC, "seconds": window["length_s"], "credits": credits, "preview_path": preview,
        },
    }
    proposal["drop"] = {k: v for k, v in proposal["drop"].items() if v is not None or k in ("reason", "crop_x")}
    mark_favorite(store, pick.id, pick.status, proposal=proposal, source_id=src.id)
    return Outcome(pick.id, "ready", None, detail={"credits": credits, "window": window, "crop_x": crop_x, "preview_path": preview})


def _preview(storage: Storage, local: Path, work: Path, pick_id: str, window: Mapping[str, float], crop_x: float | None) -> str | None:
    """Five frames of the section side by side, in ``sources/owner/<pick id>/preview.jpg`` (the owner's browser may read it)."""
    try:
        cut = clipwork.trim_clip(local, work / "section.mp4", window["start_s"], window["length_s"], keep_audio=False, crop_x=crop_x)
        sheet, _ = contact_sheet(cut, work / PREVIEW_NAME, cols=5, rows=1, width=160)
    except (QAError, clipwork.ClipworkError, ValueError):
        return None  # a missing strip never blocks a drop: the card shows the thumbnail-less frame
    key = f"owner/{pick_id}/{PREVIEW_NAME}"
    storage.upload(SOURCES_BUCKET, key, sheet)
    return key


# ---- make --------------------------------------------------------------------------------------------------------------------


def _features(pick: Favorite, drop: Mapping[str, Any], eff: Mapping[str, Any], kind: str) -> dict[str, Any]:
    look = drop.get("deconstruct") or {}
    return {
        "format_id": "drop_object_swap", "hook_pattern": "drop", "hook_text": eff["hook"],
        "prop": ", ".join(eff["gadgets"]) or "none", "setting": look.get("setting") or "the clip's own",
        "motion_type": "object_swap", "audio_arm": "original_audio", "bodies_in_frame": int(look.get("people_count") or 1),
        "seamless_loop": False, "eye_closeup_end": False, "trend_name": look.get("moment_name") or "evergreen",
        "music": MUSIC, "fav_id": pick.id, "drop": True, "presence": eff["part"], "engagement_kind": kind,
    }


def _settle_amount(pick: Favorite, clip: Clip) -> int:
    """This attempt's reservation (the API reports no cost, so the estimate for the trimmed seconds is what is booked)."""
    reserved = (drop_of(pick).get("make") or {}).get("reserved")
    return int(reserved) if isinstance(reserved, int) and not isinstance(reserved, bool) else (clip.credits_reserved or 0)


def _record_make(store: Store, pick: Favorite, now: datetime, **changes: Any) -> Favorite:
    drop = drop_of(store.get_favorite(pick.id) or pick)
    make = {**(drop.get("make") or {}), **changes}
    return _update(store, pick, now, make=make)


def _give_up(store: Store, pick: Favorite, clip: Clip | None, now: datetime, reason: str) -> Outcome:
    """A make that cannot go on: the clip dropped, the pick back to approved, the drop ``failed`` (Make it again starts over)."""
    if clip is not None and S.dropped in clips.ALLOWED.get(store.get_clip(clip.id).state, set()):
        clips.transition(store, clip.id, S.dropped, reject_reason=reason[:300])
    pick = store.get_favorite(pick.id)
    drop = drop_of(pick)
    drop.pop("make", None)
    proposal = {**pick.proposal, "drop": {**drop, "state": "failed", "reason": reason, "at": now.isoformat()}}
    mark_favorite(store, pick.id, "approved", proposal=proposal)
    return Outcome(pick.id, "failed", reason, ok=False, detail={"clip_id": clip.id if clip else None})


def make_drop(
    store: Store,
    storage: Storage,
    pick_id: str,
    *,
    hf: HiggsfieldClient | None,
    gemini_client: gemini.GeminiClient | None,
    prepare: bool = False,
    generated_file: Path | str | None = None,
    generated_credits: int | None = None,
    qa_answer: Mapping[str, Any] | None = None,
    now: datetime | None = None,
    job: str | None = None,
    poll_timeout_s: float | None = None,
    preset: str = MASTER_PRESET,
    characters_dir: Path | str = seed.DEFAULT_CHARACTERS_DIR,
) -> Outcome:
    """Make a dropped video the owner approved (see the module doc). ``KeyError`` for an unknown pick; ``DropError`` when it may
    not be made (no Make it, not ``making``, by-hand options that do not fit); ``BudgetRefused`` is recorded, not raised."""
    now = now or now_london()
    job = job or job_id()
    if generated_credits is not None and generated_file is None:
        raise DropError("--credits only goes with --generated-file (what that job cost)")
    pick = _load(store, pick_id)
    drop = drop_of(pick)
    if not owner_requested_make(pick):
        raise DropError(f"pick {pick_id}: no Make it from the owner (proposal.make_requested): nothing is generated without it")
    if drop["state"] != "making":
        raise DropError(f"pick {pick_id} is {drop['state']}: a make runs on a drop the owner sent with Make it (making)")
    for key in ("source_id", "window", "star", "credits"):
        if not drop.get(key):
            raise DropError(f"pick {pick_id}: the check never finished ({key} missing): process it first")
    try:
        effective(drop)
    except ValueError as e:
        return _give_up(store, pick, None, now, f"the Adjust is not valid: {e}")
    if not claim(store, pick_id, "make", job, now):
        return Outcome(pick_id, "making", "another run is making this video", detail={"busy": True})
    try:
        return _make(
            store, storage, pick_id, hf, gemini_client, prepare, generated_file, generated_credits, qa_answer, now,
            poll_timeout_s, preset, characters_dir,
        )
    except (DropError, StorageError):
        raise
    except Exception as e:  # a crash mid-way: recorded; the next run resumes where the clip is (never a blind resubmit)
        return _stopped(store, pick_id, now, e)
    finally:
        release(store, pick_id, job)


MAX_STOPS = 3  # the same step stopping this often in a row gives up (its reservation is left to the daily run's recovery)


def _stopped(store: Store, pick_id: str, now: datetime, error: Exception) -> Outcome:
    pick = store.get_favorite(pick_id)
    make = drop_of(pick).get("make") or {}
    clip = store.get_clip(make["clip_id"]) if make.get("clip_id") else None
    where = clip.state.value if clip else "start"
    stops = int(make.get("stops") or 0) + 1 if make.get("stopped_at_state") == where else 1
    what = f"{type(error).__name__}: {str(error)[:140]}"
    if stops >= MAX_STOPS:
        return _give_up(
            store, pick, clip, now,
            f"the make stopped {stops} times at {where} ({what}); any credits it still holds are settled by the daily run",
        )
    if make:
        pick = _record_make(store, pick, now, stops=stops, stopped_at_state=where)
    reason = f"the make stopped at {where} ({what}): the next run resumes"
    _update(store, pick, now, reason=reason)
    return Outcome(pick_id, "making", reason, ok=False)


def _new_or_current_clip(store: Store, pick: Favorite, now: datetime) -> Clip:
    drop = drop_of(pick)
    clip_id = (drop.get("make") or {}).get("clip_id")
    if clip_id:
        clip = store.get_clip(clip_id)
        if clip is not None:
            return clip
    eff = effective(drop)
    kind = next_engagement(store, pick.character_slug)
    clip = clips.new_clip(store, pick.character_slug, None, Mode.dropin, _features(pick, drop, eff, kind))
    pick = _record_make(store, pick, now, clip_id=clip.id, attempt=0)
    mark_favorite(store, pick.id, "queued", clip_id=clip.id)
    return clip


def _make(
    store: Store, storage: Storage, pick_id: str, hf: HiggsfieldClient | None, client: gemini.GeminiClient | None,
    prepare: bool, generated_file: Path | str | None, generated_credits: int | None, qa_answer: Mapping[str, Any] | None,
    now: datetime, poll_timeout_s: float | None, preset: str, characters_dir: Path | str,
) -> Outcome:
    pick = store.get_favorite(pick_id)
    ref, who = character(pick.character_slug, characters_dir)
    if hf is None and not prepare and generated_file is None and not (drop_of(pick).get("make") or {}).get("output_url"):
        clip_id = (drop_of(pick).get("make") or {}).get("clip_id")
        clip = store.get_clip(clip_id) if clip_id else None
        if clip is None or clip.state in (S.planned, S.generating):
            reason = "waiting for the Higgsfield key: the next daily run makes it by hand"
            _update(store, pick, now, reason=reason)
            return Outcome(pick_id, "making", reason)
    clip = _new_or_current_clip(store, pick, now)
    with tempfile.TemporaryDirectory(prefix="studio-drop-make-") as tmp:
        work = Path(tmp)
        for _ in range(12):  # each pass moves the clip one state on; a finished or waiting make returns
            pick = store.get_favorite(pick_id)
            clip = store.get_clip(clip.id)
            step = _step(
                store, storage, pick, clip, ref, who, hf, client, prepare, generated_file, generated_credits, qa_answer,
                now, poll_timeout_s, preset, work,
            )
            if isinstance(step, Outcome):
                return step
        raise RuntimeError("the make did not settle in 12 steps")  # pragma: no cover - a state machine loop


def _child(store: Store, storage: Storage, pick: Favorite, clip: Clip, now: datetime) -> Source:
    """The trimmed (and cropped, and big enough) section Genjutsu is given, made once per clip."""
    if clip.source_id:
        return _source(store, clip.source_id)
    eff = effective(drop_of(pick))
    child = sources.trim_source(
        store, storage, drop_of(pick)["source_id"], eff["start_s"], eff["length_s"], crop_x=eff["crop_x"],
        min_pixels=clipwork.OBJECT_SWAP_MIN_PIXELS,
    )
    clips.set_source(store, clip.id, child.id)
    return child


def _reserve(store: Store, pick: Favorite, clip: Clip, child: Source, now: datetime) -> int | Outcome:
    credits = estimate_credits(Mode.dropin, child.duration_s, MUSIC)
    try:
        budget.reserve(store, clip.id, credits, now)
    except BudgetRefused as e:
        reason = (
            "the kill switch is on: nothing is generated" if e.reason == "kill_switch"
            else f"the monthly cap would be passed ({e.committed} + {e.requested} > {e.cap}): tap Make it again when there is room"
        )
        if clip.state is S.planned:
            clips.transition(store, clip.id, S.dropped, reject_reason=reason[:300])
            fresh = store.get_favorite(pick.id)
            drop = drop_of(fresh)
            drop.pop("make", None)
            proposal = {**fresh.proposal, "drop": {**drop, "state": "ready", "reason": reason, "at": now.isoformat()}}
            proposal.pop("make_requested", None)
            mark_favorite(store, pick.id, "approved", proposal=proposal)
            return Outcome(pick.id, "ready", reason, ok=False, detail={"refused": e.reason, "clip_id": clip.id})
        return _give_up(store, pick, clip, now, reason)
    clips.set_fields(store, clip.id, credits_reserved=(clip.credits_reserved or 0) + credits)  # a note: every attempt's reserve
    _record_make(store, pick, now, reserved=credits)
    return credits


def _submit(store: Store, storage: Storage, pick: Favorite, clip: Clip, child: Source, ref: Mapping[str, Any], who: gemini.Character,
            hf: HiggsfieldClient, now: datetime) -> None | Outcome:
    """POST the Object swap once, with the key and the body stored first; an uncertain answer is looked up with them."""
    make = drop_of(pick).get("make") or {}
    if not make.get("idempotency_key"):
        eff = effective(drop_of(pick))
        body = {
            "video_url": sources.signed_source_url(store, storage, child.id, SIGNED_URL_S),
            "image_urls": seed.reference_images(ref, eff["body"] or ref["bodies"][0]),
            "prompt": swap_prompt(eff["star"] or "the main performer", who.noun, eff["part"], eff["gadgets"]),
            "resolution": "1080p",
        }
        attempt = int(make.get("attempt") or 0) + 1
        key = f"drop-{clip.id}-{attempt}"
        pick = _record_make(store, pick, now, attempt=attempt, idempotency_key=key, body=body, submitted_at=now.isoformat(),
                            status_url=None, request_id=None, output_url=None, status=None)
        make = drop_of(pick)["make"]
    try:
        sub = hf.submit_object_swap(**make["body"], idempotency_key=make["idempotency_key"])
    except SubmitUncertain as e:
        reason = f"Higgsfield did not answer the submit ({str(e)[:100]}): the next run looks it up with the same key"
        _update(store, pick, now, reason=reason)
        return Outcome(pick.id, "making", reason, ok=False)
    except HiggsfieldError as e:  # a refusal: nothing was created, nothing was charged
        budget.release(store, clip.id, now)
        clips.transition(store, clip.id, S.gen_failed, qa={"error": str(e)[:300]})
        return _give_up(store, pick, store.get_clip(clip.id), now, f"Higgsfield refused the job: {str(e)[:160]}")
    _record_make(store, pick, now, request_id=sub.request_id, status_url=sub.status_url, status=sub.status)
    clips.set_fields(store, clip.id, hf_job_id=sub.request_id)
    _update(store, store.get_favorite(pick.id), now, reason=None)
    return None


def _download_output(hf: HiggsfieldClient | None, pick: Favorite, work: Path, generated_file: Path | str | None) -> Path | None:
    gen = work / "gen.mp4"
    if gen.is_file():
        return gen
    if generated_file is not None:
        src = Path(generated_file)
        if not src.is_file():
            raise DropError(f"no such file: {src}")
        shutil.copyfile(src, gen)
        return gen
    url = (drop_of(pick).get("make") or {}).get("output_url")
    if url and hf is not None:
        return hf.download(url, gen)
    return None


def _qa_from_file(answer: Mapping[str, Any]) -> tuple[bool, list[str]]:
    if not isinstance(answer, Mapping) or not isinstance(answer.get("pass"), bool):
        raise DropError('the QA file must be {"pass": true|false, "problems": [...], "visual": "..."}')
    problems = answer.get("problems", [])
    if not isinstance(problems, list) or not all(isinstance(p, str) for p in problems):
        raise DropError("the QA file's problems must be a list of short lines")
    return answer["pass"], [p.strip() for p in problems if p.strip()]


def _step(
    store: Store, storage: Storage, pick: Favorite, clip: Clip, ref: Mapping[str, Any], who: gemini.Character,
    hf: HiggsfieldClient | None, client: gemini.GeminiClient | None, prepare: bool, generated_file: Path | str | None,
    generated_credits: int | None, qa_answer: Mapping[str, Any] | None, now: datetime, poll_timeout_s: float | None,
    preset: str, work: Path,
) -> Outcome | None:
    """Move the clip one state on (see the module doc); an ``Outcome`` when this run stops."""
    state = clip.state
    if state is S.planned:
        child = _child(store, storage, pick, clip, now)
        got = _reserve(store, pick, clip, child, now)
        if isinstance(got, Outcome):
            return got
        clips.transition(store, clip.id, S.generating)
        if prepare:
            return _prepared(store, storage, pick, clip, child, ref, who, now)
        return None
    if state is S.generating:
        make = drop_of(pick).get("make") or {}
        if generated_file is not None:
            if generated_credits is None:
                raise DropError("--credits is needed with the output of a job: what it really cost")
            spent = int(generated_credits)
            budget.settle(store, clip.id, spent, now)
            clips.transition(store, clip.id, S.generated, credits_actual=(clip.credits_actual or 0) + spent)
            _record_make(store, pick, now, status="completed", output_url=None)
            return None
        if hf is None:
            if prepare:
                return _prepared(store, storage, pick, clip, _source(store, clip.source_id), ref, who, now)
            reason = "waiting for the Higgsfield key: the next daily run makes it by hand"
            _update(store, pick, now, reason=reason)
            return Outcome(pick.id, "making", reason)
        if not make.get("status_url"):
            stopped = _submit(store, storage, pick, clip, _source(store, clip.source_id), ref, who, hf, now)
            if stopped is not None:
                return stopped
            pick = store.get_favorite(pick.id)
            make = drop_of(pick)["make"]
        try:
            kw = {} if poll_timeout_s is None else {"timeout_s": poll_timeout_s}
            st = hf.wait(make["status_url"], **kw)
        except PollTimeout as e:
            reason = f"Higgsfield is still working ({e.last or 'queued'}): the next run checks again"
            _record_make(store, pick, now, status=e.last)
            _update(store, store.get_favorite(pick.id), now, reason=reason)
            return Outcome(pick.id, "making", reason)
        if not st.ok:
            budget.release(store, clip.id, now)  # a failed job is refunded
            clips.transition(store, clip.id, S.gen_failed, qa={"error": f"{st.status}: {st.error or 'no reason given'}"[:300]})
            return _give_up(store, pick, store.get_clip(clip.id), now, f"Higgsfield said {st.status}: {st.error or 'no reason given'}")
        spent = _settle_amount(store.get_favorite(pick.id), clip)  # the API reports no cost: the estimate is booked
        budget.settle(store, clip.id, spent, now)
        _record_make(store, pick, now, status="completed", output_url=st.video_url, credits_basis="estimate (the API reports no cost)")
        clips.transition(store, clip.id, S.generated, credits_actual=(clip.credits_actual or 0) + spent)
        return None
    if state is S.generated:
        gen = _download_output(hf, pick, work, generated_file)
        if gen is None:
            reason = "the output is waiting to be checked: the next run with the Higgsfield key downloads it"
            _update(store, pick, now, reason=reason)
            return Outcome(pick.id, "making", reason)
        return _quality(store, storage, pick, clip, who, client, qa_answer, gen, now, work)
    if state is S.qa_failed:
        if clips._rerolls(clip) >= clips.MAX_REROLLS:
            problems = " / ".join(clip.qa.get("problems", [])) or "the quality check failed"
            return _give_up(store, pick, clip, now, f"the quality check failed twice: {problems}"[:300])
        child = _source(store, clip.source_id)
        got = _reserve(store, pick, clip, child, now)
        if isinstance(got, Outcome):
            return got
        _record_make(store, pick, now, idempotency_key=None, body=None, status_url=None, request_id=None, output_url=None, status=None)
        clips.transition(store, clip.id, S.generating)  # the one re-roll (the state machine counts it)
        (work / "gen.mp4").unlink(missing_ok=True)
        (work / "gen_audio.mp4").unlink(missing_ok=True)
        if hf is None and generated_file is not None:
            reason = "the quality check failed: the daily run makes the one re-roll by hand"
            _update(store, store.get_favorite(pick.id), now, reason=reason)
            return Outcome(pick.id, "making", reason, ok=False)
        return None
    if state is S.qa_passed:
        gen = _download_output(hf, pick, work, generated_file)
        if gen is None:
            reason = "the master waits for the output: the next run with the Higgsfield key downloads it"
            _update(store, pick, now, reason=reason)
            return Outcome(pick.id, "making", reason)
        return _master(store, storage, pick, clip, ref, gen, now, work, preset)
    if state is S.mastered:
        clips.transition(store, clip.id, S.awaiting_approval)
        return None
    if state in (S.awaiting_approval, S.approved, S.scheduled, S.posted):
        fresh = store.get_favorite(pick.id)
        drop = drop_of(fresh)
        if drop["state"] != "made":
            proposal = {**fresh.proposal, "drop": {**drop, "state": "made", "reason": None, "at": now.isoformat()}}
            mark_favorite(store, pick.id, "made", proposal=proposal, clip_id=clip.id)
        return Outcome(pick.id, "made", None, detail={"clip_id": clip.id, "clip_state": clip.state.value})
    return _give_up(store, pick, None, now, f"the clip is {state.value}: tap Make it again to start over")


def _prepared(store: Store, storage: Storage, pick: Favorite, clip: Clip, child: Source, ref: Mapping[str, Any],
              who: gemini.Character, now: datetime) -> Outcome:
    eff = effective(drop_of(pick))
    inputs = {
        "clip_id": clip.id, "source_id": child.id, "seconds": child.duration_s,
        "video_url": sources.signed_source_url(store, storage, child.id, SIGNED_URL_S),
        "image_urls": seed.reference_images(ref, eff["body"] or ref["bodies"][0]),
        "prompt": swap_prompt(eff["star"] or "the main performer", who.noun, eff["part"], eff["gadgets"]),
        "resolution": "1080p", "reserved": store.get_clip(clip.id).credits_reserved,
    }
    reason = "prepared for the MCP Object swap: run it, then drop make --generated-file F --credits N"
    _update(store, pick, now, reason=reason)
    return Outcome(pick.id, "making", reason, detail={"inputs": inputs})


def _quality(
    store: Store, storage: Storage, pick: Favorite, clip: Clip, who: gemini.Character, client: gemini.GeminiClient | None,
    qa_answer: Mapping[str, Any] | None, gen: Path, now: datetime, work: Path,
) -> Outcome | None:
    problems: list[str] = []
    try:
        report = probe(gen, loudness=False)
    except QAError as e:
        report = None
        problems.append(f"tech: {e}")
    if report is not None:
        if report.duration_s < MASTER_MIN_S - 0.3:
            problems.append(f"duration: {report.duration_s:.2f} s, a master needs {MASTER_MIN_S:g} s")
        if not report.has_audio:  # the clip's own sound went missing: put it back from the section we sent
            child = _source(store, clip.source_id)
            section = _fetch_local(storage, child, work, "section")
            try:
                clipwork.mux_source_audio(gen, section, work / "gen_audio.mp4", 0.0)
                (work / "gen_audio.mp4").replace(gen)
            except (ValueError, QAError, clipwork.ClipworkError) as e:
                problems.append(f"audio: the original sound could not be put back ({e})")
    visual = ""
    if not problems:
        if qa_answer is not None:
            passed, seen = _qa_from_file(qa_answer)
            visual = str(qa_answer.get("visual") or "")[:300]
        elif client is not None:
            sheet = frame_sheet(gen, n=6, out=work / "frames.jpg")
            try:
                verdict = gemini.frame_qa(client, sheet, who)
            except gemini.GeminiError as e:
                reason = f"the frame check failed ({str(e)[:120]}): the next run tries again"
                _update(store, pick, now, reason=reason)
                return Outcome(pick.id, "making", reason, ok=False)
            passed, seen = verdict.passed, verdict.problems
        else:
            reason = "waiting for the Gemini key: the next daily run checks the frames by hand (--qa-file)"
            _update(store, pick, now, reason=reason)
            return Outcome(pick.id, "making", reason)
        if not passed:
            problems.extend(seen or ["the frame check said fail"])
    qa = {"tech": "ok" if not any(p.startswith(("tech", "duration", "audio")) for p in problems) else "problems",
          "problems": problems, "visual": visual}
    if problems:
        clips.transition(store, clip.id, S.qa_failed, qa=qa)
        if any("watermark" in p for p in problems):  # leaked from the source: it is no longer Drop-in eligible
            sources.flag_dirty(store, clip.source_id, "; ".join(problems)[:300])
        return None
    clips.transition(store, clip.id, S.qa_passed, qa=qa)
    return None


def _master(store: Store, storage: Storage, pick: Favorite, clip: Clip, ref: Mapping[str, Any], gen: Path, now: datetime,
            work: Path, preset: str) -> Outcome | None:
    drop = drop_of(pick)
    eff = effective(drop)
    look = drop.get("deconstruct") or {}
    hook = eff["hook"] or (drop.get("hooks") or [""])[0]
    duration = probe(gen, loudness=False).duration_s
    spec = MasterSpec(
        dance=gen, closeup=None, closeup_center=tuple(ref.get("closeup_center") or (0, 0)),
        blue_eye_xy=tuple(ref.get("blue_eye_xy") or (0, 0)), hook1=[], hook2=hook_lines(hook),
        hook2_until_s=max(1.0, min(HOOK_ON_SCREEN_S, duration - 1.0)), audio=gen, audio_offset_s=0.0,
        out=work / "master.mp4", preset=preset, clip_id=clip.id, music=MUSIC,
    )
    source = _source(store, clip.source_id) if clip.source_id else None
    if (problem := audio_problem(gen, gen, clip, source, pick.proposal.get("owner_music"))) is not None:
        return _give_up(store, pick, clip, now, f"the audio rule refused the master: {problem}"[:300])
    try:
        out = build_master(spec)
        problems = check_master(probe(out), silent=False)
    except Exception as e:  # ffmpeg or a bad spec: our side; the owner can tap again and it resumes from here
        reason = f"the master build failed ({type(e).__name__}: {str(e)[:120]}): tap Make it again"
        _update(store, pick, now, state="failed", reason=reason)
        return Outcome(pick.id, "failed", reason, ok=False, detail={"clip_id": clip.id})
    if problems:
        reason = f"the master missed the spec: {'; '.join(problems)[:200]}"
        _update(store, pick, now, state="failed", reason=reason)
        return Outcome(pick.id, "failed", reason, ok=False, detail={"clip_id": clip.id})
    upload_master(store, storage, clip.id, out)
    kind = clip.features.get("engagement_kind") if clip.features.get("engagement_kind") in ENGAGEMENT_ORDER else ENGAGEMENT_ORDER[0]
    caption = caption_text(pick, look, kind) if look.get("caption") else hook
    hashtags = list(look.get("hashtags") or ["#oddeyes"])
    compose_content(caption, hashtags)  # the 2,200 limit, 5 tags, no refused tag: before anything is written
    clips.transition(store, clip.id, S.mastered, hook=hook, caption=caption, hashtags=hashtags)
    if look.get("first_comment"):
        clips.set_first_comment(store, clip.id, look["first_comment"])
    return None


# ---- what is pending (the sweep) ------------------------------------------------------------------------------------------


def pending(store: Store, *, include_waiting: bool = False, now: datetime | None = None) -> list[dict[str, str]]:
    """The drops a run should take, oldest first: ``checking`` (and an ``uploading`` one whose file is attached) -> process,
    ``making`` with the owner's Make it -> make; ``waiting`` links only with ``include_waiting`` (the Mac: the cloud could not
    fetch them). A pick another run holds (a live lease) is left out."""
    now = now or now_london()
    out: list[tuple[datetime | None, dict[str, str]]] = []
    for f in store.list_favorites():
        if not is_drop(f.proposal) or f.status not in ("approved", "queued"):
            continue
        d = f.proposal["drop"]
        held = d.get("job")
        if isinstance(held, Mapping) and (since := _moment(held.get("at"))) is not None and now - since < timedelta(minutes=LEASE_MINUTES):
            continue
        state = d.get("state")
        if state == "checking" or (state == "uploading" and f.proposal.get("owner_clip_path")) or (state == "waiting" and include_waiting):
            out.append((f.created_at, {"pick_id": f.id, "job": "process", "state": state}))
        elif state == "making" and owner_requested_make(f):
            out.append((f.created_at, {"pick_id": f.id, "job": "make", "state": state}))
    out.sort(key=lambda p: p[0].timestamp() if p[0] else 0.0)
    return [p for _, p in out]


# ---- CLI --------------------------------------------------------------------------------------------------------------------------

app = typer.Typer(
    help="Drop a video: owner-dropped clips animated into our characters (Object swap). Prints JSON; exit 1 = a job stopped on "
    "a recorded failure, 2 = caller error, 3 = the budget refused.",
    no_args_is_help=True,
)


def _json_file(path: Path | None, what: str) -> dict[str, Any] | None:
    if path is None:
        return None
    raw = text_option(None, path, what)
    try:
        data = json.loads(raw or "")
    except json.JSONDecodeError as e:
        fail(f"--{what}-file is not valid JSON: {e}")
    if not isinstance(data, dict):
        fail(f"--{what}-file must hold a JSON object")
    return data


def _finish(outcome: Outcome) -> None:
    emit(outcome.json())
    if (outcome.detail or {}).get("refused"):
        raise typer.Exit(EXIT_REFUSED)
    if not outcome.ok:
        raise typer.Exit(EXIT_FAILED)


@app.command("add")
def add_command(
    character_slug: Annotated[str, typer.Option("--character", help="biscuit or reginald.")],
    link: Annotated[str | None, typer.Option("--link", help="A full TikTok / Instagram Reel / YouTube link (else a file drop).")] = None,
    own_footage: Annotated[
        bool, typer.Option("--own-footage", help="The owner's own recording or footage used with permission (default: a downloaded clip).")
    ] = False,
) -> None:
    """File a drop like the terminal does (a link, or a file drop waiting for its upload)."""
    store = open_store()
    try:
        pick, duplicate = add_drop(store, character_slug, link, own_footage=own_footage)
    except ValueError as e:
        fail(str(e))
    emit({"pick_id": pick.id, "duplicate": duplicate, "drop": pick.proposal.get("drop")})


@app.command("process")
def process_command(
    pick: Annotated[str, typer.Argument(help="The drop's pick id.")],
    deconstruct_file: Annotated[
        Path | None,
        typer.Option("--deconstruct-file", help="The deconstruct written by hand (studio.gemini's schema), when there is no Gemini key."),
    ] = None,
) -> None:
    """Check a dropped video for free: the clip, its analysis, the deconstruct, the checks, the section, the price -> ready."""
    answer = _json_file(deconstruct_file, "deconstruct")
    store, storage = open_store(), open_storage()
    try:
        outcome = process_drop(store, storage, pick, gemini_client=gemini.GeminiClient.from_env(), deconstruct_answer=answer)
    except KeyError:
        fail(f"unknown pick {pick}")
    except (DropError, StorageError) as e:
        fail(str(e))
    _finish(outcome)


@app.command("make")
def make_command(
    pick: Annotated[str, typer.Argument(help="The drop's pick id (the owner tapped Make it).")],
    prepare: Annotated[bool, typer.Option("--prepare", help="Without the Higgsfield key: reserve, trim and print the MCP inputs.")] = False,
    generated_file: Annotated[
        Path | None, typer.Option("--generated-file", help="The Object swap output made by hand (MCP), downloaded.")
    ] = None,
    credits: Annotated[int | None, typer.Option("--credits", min=0, help="With --generated-file: what that job really cost.")] = None,
    qa_file: Annotated[
        Path | None, typer.Option("--qa-file", help='The frame check by hand: {"pass": bool, "problems": [...], "visual": ".."}.')
    ] = None,
) -> None:
    """Make a dropped video the owner sent with Make it: trim, reserve, Object swap, QA, master, awaiting approval."""
    qa = _json_file(qa_file, "qa")
    store, storage = open_store(), open_storage()
    try:
        outcome = make_drop(
            store, storage, pick, hf=HiggsfieldClient.from_env(), gemini_client=gemini.GeminiClient.from_env(), prepare=prepare,
            generated_file=generated_file, generated_credits=credits, qa_answer=qa,
        )
    except KeyError:
        fail(f"unknown pick {pick}")
    except (DropError, StorageError, ValueError) as e:
        fail(str(e))
    _finish(outcome)


@app.command("pending")
def pending_command(
    include_waiting: Annotated[
        bool, typer.Option("--include-waiting", help="Also the links the cloud could not fetch (the Mac's daily run).")
    ] = False,
    count: Annotated[bool, typer.Option("--count", help="Print only how many.")] = False,
) -> None:
    """The drops a run should take now: process or make, oldest first."""
    rows = pending(open_store(), include_waiting=include_waiting)
    if count:
        typer.echo(str(len(rows)))
        return
    emit(rows)


@app.command("sweep")
def sweep_command(
    include_waiting: Annotated[bool, typer.Option("--include-waiting", help="Also retry the waiting links (the Mac).")] = False,
) -> None:
    """Run every pending drop job, one after another (the 2-hourly safety net). Exit 1 when one of them stopped on a failure."""
    store, storage = open_store(), open_storage()
    hf, client = HiggsfieldClient.from_env(), gemini.GeminiClient.from_env()
    results: list[dict[str, Any]] = []
    failed = False
    for row in pending(store, include_waiting=include_waiting):
        try:
            if row["job"] == "process":
                outcome = process_drop(store, storage, row["pick_id"], gemini_client=client)
            else:
                outcome = make_drop(store, storage, row["pick_id"], hf=hf, gemini_client=client)
            results.append({"job": row["job"], **outcome.json()})
            failed = failed or not outcome.ok
        except (KeyError, DropError, StorageError, ValueError) as e:
            results.append({"job": row["job"], "pick_id": row["pick_id"], "ok": False, "error": str(e)[:300]})
            failed = True
    emit({"ran": len(results), "results": results})
    if failed:
        raise typer.Exit(EXIT_FAILED)
