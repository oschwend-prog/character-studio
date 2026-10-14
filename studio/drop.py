"""``studio drop``: a video the owner drops is animated into our character in the cloud ("Drop a video", plan 2026-10-06).

Owner: "keep the terminal simpler. I will drop in videos and it will animate for our characters", "it should happen even when
the Mac is closed" and "always check with me if we generate new videos". Genjutsu is used the way Higgsfield designed it:
**Object swap** keeps the clip's setting, camera, timing and sound and replaces its star, like for like (refs.json ``swap``:
a character drawn as a person replaces a person, a dog replaces a dog).

**A drop is a pick** (``favorites``, origin ``owner``, status ``approved``) carrying ``proposal['drop']``. The terminal files it
with the ``studio.add_drop`` RPC (migration 0012): a file drop is keyed ``owner-drop:<pick id>`` (platform ``drop``) and its
video goes to Storage ``sources/owner/<pick id>/<file>`` (``attach_clip``); a pasted link is the canonical TikTok / Instagram /
YouTube URL. ``studio.request_job(pick, kind)`` (security definer, pg_net + the Vault secret ``github_dispatch_token``) records
the request and fires the ``studio-drop`` GitHub workflow, which runs ``studio drop process`` or ``studio drop make``; a
2-hourly ``studio drop sweep`` picks up anything left pending, in three parallel workers (``STUDIO_WORKER`` makes each worker's
``job_id`` its own, so the lease keeps them off each other's drop; a drop another worker holds or has finished is no failure;
a check that still has to download its clip is worker 1's alone, ``takes_downloads``: one download at a time).
``drop.state`` moves::

    uploading -> checking -> ready -----------(Make it: request_job make)----------> making -> made
                    |   \\-> blocked (a child as the star, a watermark, burned-in text, the wrong star, too short)  \\-> failed
                    \\-> waiting (a link the cloud could not fetch: the daily run on the Mac tries again)

``reason`` carries the one line the card shows (blocked, waiting, failed, or what a making job waits for).

**A failed check retries itself when the cause is temporary** (task 12): the sweep (never the Mac's run) takes a drop ``failed``
in its CHECK (reason "the look at the clip failed ...") again when ``transient_kind`` of the reason is ``timeout`` / ``busy``
(Gemini timed out, answered 5xx, was busy or the network dropped: at most ``AUTO_RETRY_MAX`` automatic retries) or ``quota`` (HTTP
429 "exceeded your current quota": only once the quota has reset, i.e. after the latest 08:00 London, and at most
``AUTO_RETRY_QUOTA_MAX`` times, one a London day). ``drop.auto_retries`` counts them (both kinds in one count) and
``drop.auto_retry_at`` stamps the last; the owner's Try again (``requested.process`` after that stamp) starts the count over. A 429
is told apart where ``studio.gemini`` raises it (``GeminiQuota``: the day's quota or a per-minute limit; the quota id sits beyond the
140 characters a raw reason keeps) and ``check_failed_reason`` writes it in plain words with a tag (``[quota:day]``,
``[quota:minute]``: a per-minute 429 is retaken on the next sweep, not held until 08:00); while the retake is booked the outcome
carries ``will_retry`` and the run exits 0 (``Outcome.red``: red means a real problem). Three
sweep workers list the same failed drop: only the first retakes it, the others find it has moved on (``drop.at`` or
``drop.auto_retry_at`` differs from the listed row: ``failure_stamp``), so one sweep spends one retry per drop. A failed MAKE is
never retried by itself (it spends credits): the owner taps Make it again.

**Whose clip it is** (owner 2026-10-06: "the core of the terminal is dropping our characters into my saved videos"). A drop is
filed for a character the owner chose (``drop['character_by'] = 'owner'``) or for none: then the studio recommends one
(``'studio'``) and the drop waits under a provisional character (``provisional``: the first of the live roster, by slug, who
replaces a person; migration 0013's add_drop picks the same). The deconstruct names the character of the live roster (``roster``:
not paused, with a swap rule) who should replace the star, like for like, with a one-line reason (``drop['recommended']``,
shown with a star on the terminal's menu). While the choice is the studio's and the recommendation differs, the check moves
the pick to him and looks once more in his voice, in the same job (free: Gemini only); the owner's choice is never overridden.
The owner's menu (``studio.set_drop_character``, migration 0013) records his choice, clears the old character's results and
asks for the check again; a check that finds its character changed under it starts again for the new one.

**Only the section we use is judged** (owner 2026-10-06). The deconstruct says when text or a watermark is on screen
(``burned_in_text_spans``, ``watermark_spans``); the section (``drop_window``) keeps ``SPAN_PAD_S`` clear of them
(``drop['avoid']``, which the owner's Adjust may not overlap either), and only a clip with no clean section of 6 s is blocked.
The check also writes ``drop['max_length_s']`` (16 s less what his kit adds before the dance: 15.6 s for Reginald's pause) so the
terminal's Adjust refuses a longer section before Make it, as ``validate_adjust`` would at Make it.

**Process** (``process_drop``, free): the clip (``source ingest-owner`` for a file, ``source fetch`` with no Recreate fallback
for a link), a probe, the free local analysis (``source analyze``: cuts, beat, the best window), the Gemini **deconstruct**
(``studio.gemini``: people, the star and where and whether the star is a child, children anywhere (recorded only), a watermark or
handle, burned-in text, setting, what happens, his part, gadgets from the traits card, 3 hooks (one per arm of the hook bandit when
test B has arms for him: 3 or 4, ``hook_arms_for``) in the bible voice with their
patterns, a playbook caption, a first comment and its question variant, hashtags) or, without the key, the one the daily run
wrote by hand (``--deconstruct-file``), the checks, the window (``drop_window``: a classic 12-15 s, any other
clip 8-10 s, inside one shot, on the beat), the crop of a landscape clip around the star, the price (``planning.estimate_credits``
for the window) and a preview strip in ``sources/owner/<pick id>/preview.jpg`` (the owner's browser may read ``owner/``). Then
``ready``, with the clip's **score** (terminal v3, ``drop_score``: ``drop['score'] = {total 0-100, potential 0-10, swap 0-10,
reason}``, the potential from the deconstruct, the swap points from the check); a blocked or failed check has none. A ready
drop without the owner's Make it can be checked again for free (``request_recheck``, ``studio drop recheck <pick>`` or
``--all-ready``): it goes back to ``checking`` for the sweep, so a drop checked before the score gets one.

**What the owner sees and watches** (terminal v3 Task 11, owner 2026-10-08: "make them larger so I can actually see them ... Even
better if I could click and watch them"). Next to the strip the check writes the clip card's picture, ``cover.jpg`` (the middle
frame of the section, 540x960), and a watch copy of the section, ``preview.mp4`` (540x960, small H.264 with the clip's own sound,
faststart), as ``drop['cover_path']`` and ``drop['preview_video_path']`` (``_watch_files``). Neither is ever a reason to fail a
check: an error is a warning and the field stays empty (the card shows the strip, then the tile). ``studio drop previews --missing``
(or ``--pick <id>``) makes both, for free, for the clips checked before them; retention deletes them with the strip.

**The balance of suggestions and fresh hooks** (controller 2026-10-08). ``roster`` counts each character's drops ``ready`` to
make (``ready_clips``): the prompt shows the counts and, when two characters fit about as well, prefers the one with fewer. The
check shows Gemini the character's latest hooks (``used_hooks``: his drops' ``hook`` and his clips' ``hook_text``, newest first,
at most ``USED_HOOKS``) as "Angles already used", so his next hooks take another angle.

**One clip, up to three characters** (terminal v3, spec section 4). From a drop whose check finished (``CHECKED_STATES``) the
owner files a **version** for another character (``copy_drop``, ``studio drop copy <pick> --character <slug>``; the RPC
``studio.copy_drop`` in SQL): a new file drop that shares the root's full clip (``source_id``, no new upload) with
``drop['copy_of']`` = the root's pick id (a version of a version points at the root) and gets its own free check, in his voice
and at his price; Make it stays per version. A **family** (``family``) is the root and its versions, skipped picks not counted,
at most ``MAX_FAMILY`` (3); a character is in it once, like for like, never a paused one. The check of a family member looks
first for a section clear of the other members' sections (``family_spans``, ``what: version``) and takes the best one as usual
when the clip has none; the studio never moves a member to a character the family already has. ``planning.family_days`` keeps
the family's posts at least 14 days apart.

**His part and his performance** (owner 2026-10-08, refs.json). A character's ``swap_part`` (Franz: ``star``) is his default
part: the check writes it as the drop's ``part`` (the Adjust sheet's default) and Make it reads it from refs.json again (the
owner's Adjust wins, then ``swap_part``, then the check's suggestion, then featured); his ``swap_performance`` line is added to
the swap prompt as one sentence. A character without them builds exactly the prompt it did before.

**Learning tags** (``docs/launch/measurement-and-learning-plan.md`` section 2, plan Task 10: tags cannot be added to posts
afterwards). The check stores the version of the hit rules it was judged by (``drop['hit_rules_version']``, from
``gemini.hit_rules_version``; a check that does not end ready keeps none, like the score), and its deconstruct carries a pattern
per hook (``hook_patterns``) and the question variant of the first comment (``first_comment_question``). Make it writes every
tag on the clip (``learn_tags``: the format, the hook used with its pattern, the score, the family, his part, the sound, the
source...; ``clips.new_clip`` refuses a drop's clip that misses one) and the master writes its real length
(``master.upload_master``) and re-tags the hook it renders (``clips.set_hook_tags``: a make resumed after a failed master renders
the owner's latest Adjust). A drop checked before this build is made with ``none`` where the check gave nothing (``drop recheck
--all-ready`` gives the ready ones their labels first).

**The learning tests at Make it** (``docs/launch/measurement-and-learning-plan.md`` section 3, ``config/experiments.json``,
``studio.experiments``, ``studio.learn``). When a clip is created, under the settings row lock: every active block-coin test writes
its arm into ``features['test_arms']`` (test C: ``trial``, true / false, the clip's Trial Reel coin, read by the publisher); test A
tags ``explore_pick`` (the clip's score is below the median of the character's checked scores, ``checked_scores``: ready, being
made, made, so the median does not move while a batch is made); test B, the hook
bandit, draws a hook pattern for the character and puts the check's candidate of that pattern on screen: ``test_arms['hook']`` is
the pattern, ``hook_by`` is ``bandit`` and the draw is kept in ``drop['make']['bandit']`` so the master renders the same hook
(``effective``). The owner's own hook (his Adjust saved one: any explicit choice, the check's first included) is never drawn over (``hook_by`` ``owner``, no ``hook`` arm). A test that
is ``off``, or not started, assigns nothing; a broken registry stops the make before anything is reserved.

**Tests G and H, the master's two edits** (plan 3.9, 3.10; ``test_arms['zoom']`` and ``['word_pop']``, true / false): zoom pulses on
every 4th beat, and the first hook coming in word by word on the beat. Both need a beat: a master with none to follow
(``has_beat_source``: a silent ``in_app`` master, a clip with no sound) takes no position in them and carries neither key. The
master step turns the clip's two keys into the spec's ``edits`` (``master.edits_from_arms``; a clip with neither key is built exactly
as before) and, once the master is built and checked, writes what it really applied on the clip: ``features['zoom_pulses']`` (the
count; 0 when the sound had no beat after all), ``features['hook_entrance']`` (the entrance shown: the kit's own, or
``word_pop``) and ``features['beats']`` (the beats of its sound, measured for the control arm too), ``clips.set_edit_tags``, so
the analysis leaves out a clip with no beat (both arms) or whose edit did not happen (the treated arm). The Recreate path assigns no
test arms (it writes ``test_arms`` ``{}``), so it is not part of G and H.

**The studio makes them** (owner decision 2026-10-14, replacing the launch-phase rule that production waits for the owner's Make it:
"once Higgsfield has credits the cloud makes clips by itself"). ``studio drop auto-make`` (``auto_make``, run first by every cloud
sweep, ``studio-drop.yml``) looks at each live character with a connected account: when his next posting slot (``planning.upcoming_slot``,
London, ``studio.settings`` cadence) starts within ``auto_make.horizon_hours`` (``config/scan.json``, 30) and nothing covers it, it asks
for ONE of his ready drops (``request_make``), written exactly as ``request_job`` writes the owner's Make it but with
``make_requested.by`` = ``studio`` and no Adjust. Covered means a pick of his with a make requested (making, or about to be), or a clip
of his from generating to scheduled that has no post yet or a post on that slot's London day (``_covering_clip``); a studio make that
failed in the last day holds him until the owner looks. The drop is the best score (ties: the oldest; no score last), except one clip
in every 4 (test A, ``explore_turn``), which is the best drop below the median of his checked scores, the pool the clip's ``explore_pick``
tag is judged by at Make it. It is priced at the check's price and must fit the monthly cap, Higgsfield's balance
(``HiggsfieldClient.balance``, a free read) and the credits already spoken for; the kill switch, the cap or too few credits ask for
nothing and print why as ``waiting`` with exit 0 (a normal state until the owner tops up: never a red run). An unreadable balance waits too.
It is idempotent and changes no account mode: a made clip still waits for the owner's one tap. Off: ``auto_make.enabled`` false.

**Make** (``make_drop``, paid, ONLY after a Make it, the owner's or the studio's): refused unless ``proposal['make_requested']`` is
a record (``{"at", "by": "owner"}`` written only by ``request_job``, or ``{"at", "by": "studio", ...}`` written only by
``request_make``; ``make_requested`` / ``make_requested_by``). The owner's Adjust
(``drop['adjust']``: who is replaced, his part, gadgets, hook, section start and length, crop) overrides the defaults. A clip is
created (``clip new``, ``fav_id`` = the pick, the pick ``queued``), the window trimmed and cropped (at least 409,600 pixels a
frame), the credits reserved (``budget.reserve``: the monthly cap and the kill switch refuse), then the **Higgsfield API**
(``studio.higgsfield_api``): our signed URL, the character's master + sheet of the star's body + close-up (refs.json
``reference_urls``), a SHORT prompt ("replace the <star> with the <noun> from the reference images" + the keep-the-scene line +
his part + gadgets), 1080p. It is polled up to 25 minutes (longer: the next sweep polls again, never resubmits). Completed: the output is
downloaded, the credits settled (the API reports no cost: the estimate for the trimmed seconds is booked), ``qa tech``, the
original audio muxed back if it was lost, the Gemini frame QA (a leftover person, a watermark, the eyes), one automatic
re-roll on a fail then stop, the master (``closeup: null``, music ``original``, the hook on screen), the upload, the caption +
first comment + hashtags of the deconstruct (playbook: a searchable title, the joke, a rotating engagement line, the credit; the
hashtags are 3-4 and the character's series tag joins them here, ``captions.with_series_tag``, so stored = previewed = posted),
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

**Are the keys good?** ``studio drop check-keys`` asks Higgsfield (a status read of a random request id) and Gemini (a model read)
for free and prints ``{"higgsfield": "ok|invalid: ..|error: ..|missing: ..", "gemini": ...}``, never the keys (the workflow's manual
``job: check-keys`` runs it with the GitHub secrets); exit 1 unless both are ``ok``.

**The owner's clips folder** (Terminal v2): ``studio drop sync-folder`` (``studio/clipfolder.py``) turns each new video in the iCloud
Drive folder into a file drop (no character: the studio recommends) and moves it to ``Added/``; after a run that added clips it
wakes this workflow's sweep with ``gh workflow run`` (a failure of that is only reported: the 2-hourly sweep catches the drops).

**From the hits job, and Keep** (plan Task 6). ``studio hits pull`` files its best new hits as link drops (``add_drop`` with
``auto_filed`` and ``hit``, the hit's character as the provisional one): ``drop['auto_filed']`` is the learning tag
``source_kind`` and goes into every version (``copy_drop``; SQL ``studio.copy_drop`` of migration 0016). A link yt-dlp cannot
fetch from the cloud is taken from ScrapeCreators' copy of that one post (``media_fallback``: the cloud jobs pass
``studio.hits.DownloadBudget`` when ``SCRAPECREATORS_API_KEY`` is set, at most ``hits.download_cap_per_day`` downloads a London
day within ``hits.daily_credit_cap``); without the key, over a cap, or when both fail, the drop waits as before, with both
reasons. The owner's
Keep (``set_keep``, ``studio drop keep <pick> [--off]``, RPC ``studio.set_drop_keep``) sets ``drop['keep']``: retention
(``studio source purge --stale``) never deletes a kept drop's clip.

CLI (``studio drop ...``) prints JSON. Exit 0 when the step was recorded (whatever the drop's state), 1 when a job stopped on a
failure it recorded (the JSON says), 2 for anything the caller must fix, 3 when the budget refused the reservation.
"""

from __future__ import annotations

import json
import logging
import math
import os
import re
import shutil
import socket
import tempfile
import uuid
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Annotated, Any, NoReturn

import typer

from studio import budget, clips, experiments, fetch, gemini, learn, seed, sources
from studio.budget import BudgetRefused
from studio.captions import compose_content, with_series_tag
from studio.cli_support import EXIT_USAGE, emit, fail, open_storage, open_store, text_option
from studio.config import LONDON, now_london
from studio.favorites import (
    DROP_PLATFORM,
    DROP_URL_PREFIX,
    family_picks,
    family_root_id,
    is_drop,
    mark_favorite,
    parse_video_url,
    validate_analysis,
)
from studio import higgsfield_api
from studio.higgsfield_api import (
    HiggsfieldClient,
    HiggsfieldError,
    PollTimeout,
    SubmitUncertain,
)
from studio.media import clipwork
from studio.media.analyze import AnalysisError, analyze_clip
from studio.media.master import MasterSpec, audio_problem, build_master, edits_from_arms, style_lead_s, upload_master
from studio.media.qa import QAError, check_master, contact_sheet, frame_sheet, probe
from studio.models import HOOK_PATTERNS, Body, Clip, ClipState, Favorite, Mode, Source
from studio.planning import TAKEN_STATUSES, estimate_credits, upcoming_slot
from studio.storage import Storage, StorageError
from studio.store import Store, require_aware

log = logging.getLogger("studio.drop")
S = ClipState
DROP_STATES = ("uploading", "checking", "waiting", "ready", "blocked", "making", "made", "failed")
PROCESS_FROM = frozenset({"uploading", "checking", "waiting"})
CHECK_REQUEST_FROM = PROCESS_FROM | {"failed"}  # request_job(pick, 'process') (migration 0012) takes these states
CHECK_FAILED = "the look at the clip failed"  # how the reason of a failed CHECK starts (a failed make never says it)
AUTO_RETRY_MAX = 2  # a timeout / 5xx / busy failure of a check is taken again by the sweep this many times, then the owner's Try again
AUTO_RETRY_QUOTA_MAX = 3  # a daily-quota failure: one retry a London day (after the reset), at most this many (same drop.auto_retries)
QUOTA_RESET_HOUR = 8  # Google resets the daily quota at midnight Pacific = 08:00 London (07:00 in the weeks the clocks differ)
QUOTA_DAY, QUOTA_MINUTE = (f"[{gemini.QUOTA_TAGS[w]}]" for w in ("day", "minute"))  # the tags a 429 reason carries (studio.gemini)
PARTS = ("cameo", "featured", "star")
ADJUST_KEYS = ("star", "part", "gadgets", "hook", "start_s", "length_s", "crop_x")
WINDOW_CLASSIC = (12.0, 15.0)  # owner 2026-10-05: a classic keeps its whole recognisable section
WINDOW_OTHER = (8.0, 10.0)
MASTER_MIN_S = 6.0  # the master spec
MASTER_MAX_S = 16.0
WINDOW_STEP_S = 0.5
SLACK_S = 0.15
LEASE_MINUTES = 70  # longer than the job's 60-minute timeout (studio-drop.yml): a lease never expires under a live run, so no second worker takes over a paid make
SIGNED_URL_S = 6 * 3600
HOOK_ON_SCREEN_S = 4.0
HOOK_LINE_CHARS = 22
MUSIC = "original"  # the clip keeps its own sound (owner decision 2026-10-05)
MASTER_PRESET = "slow"
SOURCES_BUCKET = sources.SOURCES_BUCKET
PREVIEW_NAME = "preview.jpg"
COVER_NAME = "cover.jpg"  # terminal v3 Task 11: the clip card's picture, next to the strip
PREVIEW_VIDEO_NAME = "preview.mp4"  # ... and the owner's watch copy of the section
ENGAGEMENT_ORDER = gemini.ENGAGEMENT_KINDS  # send -> question -> tease -> send ...
STAR_WORDS = gemini.STAR_WORDS
CHARACTER_BY = ("owner", "studio")  # who chose the drop's character: the owner's choice is never overridden
SPAN_PAD_S = 0.5  # Gemini's times are approximate: a section keeps this far from text or a watermark on screen
CHANGE_RESTARTS = 2  # the owner changed the character mid-check this often in a row: the next run checks it again
SCORE_CLEAR_S = 1.0  # the score's "clear" point: the section keeps this far from every text or watermark span (terminal v3)
MAX_FAMILY = 3  # terminal v3: one clip goes to at most 3 characters (the root drop and 2 versions; skipped picks do not count)
CHECKED_STATES = ("ready", "making", "made")  # a drop whose check finished: its clip may be used for another character
USED_HOOKS = gemini.USED_HOOKS_MAX  # "Angles already used": the character's latest hooks the check shows Gemini
TREND_TAGS = ("trend_stage", "days_since_trend_peak", "sound_rising")  # what the hits job's trend gate writes onto a drop (task 18)
AUTO_FETCH_DAYS = 3  # an auto-filed link the cloud cannot fetch is tried on its first 3 London days, then dropped
UNFETCHED_REASON = "couldn't be fetched in the cloud: dropped after 3 days"

EXIT_FAILED = 1
EXIT_REFUSED = 3


class DropError(ValueError):
    """A drop the caller asked about cannot take this step (not a drop, the wrong state, no Make it): exit 2."""


class NoCleanSection(ValueError):
    """Text or a watermark is on screen in every section of 6 s or more the clip could give."""


class _CharacterChanged(Exception):
    """The owner chose another character while a check was running: the check starts again, for him."""


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


MAKE_BY = ("owner", "studio")  # who may ask for a make: the owner's Make it, or the studio's own ``auto-make`` (owner decision 2026-10-14)


def make_requested_by(pick: Favorite) -> str | None:
    """Who asked for the make: ``proposal['make_requested']`` is ``{"at": <aware ISO time>, "by": "owner"}`` (written by
    ``request_job``, the terminal's Make it) or ``{"at": ..., "by": "studio", ...}`` (written by ``request_make``, ``studio drop
    auto-make``); ``"owner"`` / ``"studio"``, or None for no record or a forged one (another ``by``, a time that is no aware ISO time)."""
    rec = pick.proposal.get("make_requested")
    if isinstance(rec, Mapping) and rec.get("by") in MAKE_BY and _moment(rec.get("at")) is not None:
        return rec["by"]
    return None


def make_requested(pick: Favorite) -> bool:
    """Was this video sent to be made, by the owner's Make it or the studio's auto-make: the one gate of every paid step."""
    return make_requested_by(pick) is not None


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


def _unready(store: Store, pick: Favorite, now: datetime, **drop_changes: Any) -> Favorite:
    """``_update`` for a check that does not end ``ready`` (blocked, failed, waiting, still checking): the drop keeps no
    ``score`` and no ``hit_rules_version`` (an older check's, or another character's: the owner's menu moves a scored drop back
    to checking with it). A failed MAKE goes through ``_update`` and keeps both for Try again."""
    return _update(store, pick, now, score=None, hit_rules_version=None, **drop_changes)


# ---- one run per pick ------------------------------------------------------------------------------------------------------


def job_id() -> str:
    """Who is running: the GitHub run (and, in a sweep, which of its parallel workers: ``STUDIO_WORKER``, the matrix value of
    ``studio-drop.yml``), else this machine and process. The lease (``claim``) knows its holder by this id, so the workers of
    one run, which share the run id, must differ in it: two of them never check the same drop. The workflow exports
    ``STUDIO_WORKER`` on every run, a dispatched run (one pick) and the key check included (matrix value ``1``), so on GitHub even
    a dispatched run is ``gh-<run>-<attempt>-w1`` (harmless: the id stays unique per run); only a run without the variable
    (a test, a hand run) gets the bare ``gh-<run>-<attempt>``."""
    run = os.environ.get("GITHUB_RUN_ID")
    if not run:
        return f"{socket.gethostname()}-{os.getpid()}"
    worker = (os.environ.get("STUDIO_WORKER") or "").strip()
    return f"gh-{run}-{os.environ.get('GITHUB_RUN_ATTEMPT', '1')}" + (f"-w{worker}" if worker else "")


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
    return ref, _who(ref, characters_dir)


def _who(ref: Mapping[str, Any], characters_dir: Path | str, ready_clips: int | None = None) -> gemini.Character:
    slug = ref["slug"]
    swap = ref.get("swap")
    if not swap:
        raise DropError(f"characters/{slug}/refs.json has no swap rule (noun, stars)")
    bible_path = Path(characters_dir) / slug / "bible.md"
    bible = bible_path.read_text(encoding="utf-8") if bible_path.is_file() else ""
    voice = gemini.bible_section(bible, "Voice (captions)")
    return gemini.Character(
        slug=slug, name=ref["name"], noun=swap["noun"], stars=tuple(swap["stars"]),
        voice=voice, keywords=gemini.bible_section(bible, "Search keywords"),
        traits=ref.get("traits") or {}, edition=gemini.bible_edition(voice), ready_clips=ready_clips,
    )


def roster(store: Store, characters_dir: Path | str = seed.DEFAULT_CHARACTERS_DIR) -> list[gemini.Character]:
    """The live roster a check recommends from, by slug: every character of the database that is not paused (the owner's
    v_characters) and has a swap rule in its refs.json (a character Genjutsu cannot be given is no choice). Each carries his
    count of drops ``ready`` to make (``ready_clips``; a skipped one is not counted): the prompt's balance of suggestions."""
    refs = {r["slug"]: r for r in seed.load_refs(characters_dir)}
    ready = Counter(
        f.character_slug for f in store.list_favorites()
        if f.status != "skipped" and is_drop(f.proposal) and f.proposal["drop"].get("state") == "ready"
    )
    return [
        _who(refs[c.slug], characters_dir, ready_clips=ready[c.slug])
        for c in sorted(store.characters(), key=lambda c: c.slug)
        if c.status != "paused" and refs.get(c.slug, {}).get("swap")
    ]


def provisional(store: Store, characters_dir: Path | str = seed.DEFAULT_CHARACTERS_DIR) -> str:
    """Who a drop filed without a character waits under until its check recommends one (migration 0013's add_drop picks the
    same): the first of the live roster, by slug, who replaces a person (the likelier star), else the first of it."""
    crew = roster(store, characters_dir)
    if not crew:
        raise ValueError("no character takes new videos: every one is paused")
    return next((c.slug for c in crew if "person" in c.stars), crew[0].slug)


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


# ---- a clip used by several characters: the family (terminal v3) ---------------------------------------------------------------


def family(store: Store, pick: Favorite) -> list[Favorite]:
    """``pick``'s family: the root drop and its versions (``drop.copy_of`` = the root's pick id; a version of a version points
    at the root), the root first, then the versions oldest first. Skipped picks are no members: they never count towards
    ``MAX_FAMILY``, and the owner may file that character again."""
    return [m for m in family_picks(store, pick) if m.status != "skipped"]


def _finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def family_spans(store: Store, pick: Favorite) -> list[dict[str, Any]]:
    """The sections the family's other members use (``CHECKED_STATES``: the check's window, or the owner's Adjust of it), as
    ``drop_window`` avoid spans ``{start_s, end_s, what: "version"}``: a version looks for a different part of the clip first."""
    out: list[dict[str, Any]] = []
    for m in family(store, pick):
        d = m.proposal.get("drop")
        if m.id == pick.id or not isinstance(d, Mapping) or d.get("state") not in CHECKED_STATES:
            continue
        window = d.get("window") if isinstance(d.get("window"), Mapping) else {}
        adjust = d.get("adjust") if isinstance(d.get("adjust"), Mapping) else {}
        start, length = adjust.get("start_s", window.get("start_s")), adjust.get("length_s", window.get("length_s"))
        if _finite(start) and _finite(length) and length > 0:
            out.append({"start_s": round(float(start), 2), "end_s": round(float(start) + float(length), 2), "what": "version"})
    return sorted(out, key=lambda x: (x["start_s"], x["end_s"]))


def hook_arms_for(slug: str, now: datetime) -> gemini.HookArms | None:
    """The hook patterns the check writes ONE hook for, for this character: his arms of test B (``config/experiments.json``) while
    the test is on and has started, else ``None`` (three free hooks, as before). A registry that cannot be read is no reason to stop
    a free look: it gives ``None`` here (Make it stops on it by itself, ``_new_or_current_clip``) and says so in the log."""
    try:
        registry = experiments.load_experiments()
    except ValueError as e:
        log.warning("drop check: the test registry cannot be read (%s): three free hooks", str(e)[:140])
        return None
    if not registry.is_active("B", now):
        return None
    test = registry.test("B")
    arms = learn.arms_of(test, slug)  # all of them: trend-label is asked for when the clip turns out to have a moment name
    return gemini.HookArms(arms, needs_moment=tuple(a for a in arms if a in (test.params.get("needs_moment_name") or ()))) if arms else None


def used_hooks(store: Store, slug: str, exclude_pick_id: str | None = None) -> list[str]:
    """The character's latest hooks, newest first, at most ``USED_HOOKS`` (the check's "Angles already used"): the ``hook`` of
    his drops and the ``hook_text`` (else the on-screen ``hook``) of his clips, by when they were filed, each once (whitespace and
    case aside, in its newest place). The pick being checked (``exclude_pick_id``) and its clips are left out: its old hook is
    the one this check replaces."""
    found: list[tuple[float, str]] = []
    for f in store.list_favorites(character_slug=slug):
        hook = f.proposal["drop"].get("hook") if is_drop(f.proposal) and f.id != exclude_pick_id else None
        if isinstance(hook, str) and hook.strip():
            found.append((f.created_at.timestamp() if f.created_at else 0.0, hook))
    for c in store.list_clips(character_slug=slug):
        hook = c.features.get("hook_text") or c.hook
        if isinstance(hook, str) and hook.strip() and (exclude_pick_id is None or c.features.get("fav_id") != exclude_pick_id):
            found.append((c.created_at.timestamp() if c.created_at else 0.0, hook))
    found.sort(key=lambda x: x[0], reverse=True)
    out: list[str] = []
    seen: set[str] = set()
    for _, hook in found:
        line = " ".join(hook.split())
        if line.casefold() not in seen:
            seen.add(line.casefold())
            out.append(line)
    return out[:USED_HOOKS]


# ---- the window ----------------------------------------------------------------------------------------------------------------


def _shots(cuts: list[float], duration: float) -> list[tuple[float, float]]:
    edges = [0.0, *sorted(c for c in cuts if 0 < c < duration), duration]
    return [(a, b) for a, b in zip(edges, edges[1:]) if b > a]


def avoid_spans(look: Mapping[str, Any], duration: float) -> list[dict[str, Any]]:
    """The moments no section may touch (``drop['avoid']``): the deconstruct's text and watermark spans, each widened by
    ``SPAN_PAD_S``, kept inside the clip and merged per kind, as ``{start_s, end_s, what}`` (``what`` = text or watermark) in
    time order. Fail closed: a flag with no span is the whole clip, and a span is used even when its flag says no."""
    out: list[dict[str, Any]] = []
    for what, flag, key in (("watermark", "watermark", "watermark_spans"), ("text", "burned_in_text", "burned_in_text_spans")):
        spans = [(float(x["start_s"]), float(x["end_s"])) for x in look.get(key) or []]
        if look.get(flag) and not spans:
            spans = [(0.0, duration)]
        merged: list[tuple[float, float]] = []
        for a, b in sorted((max(0.0, a - SPAN_PAD_S), min(duration, b + SPAN_PAD_S)) for a, b in spans):
            if b <= a:
                continue
            if merged and a <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(merged[-1][1], b))
            else:
                merged.append((a, b))
        out.extend({"start_s": round(a, 2), "end_s": round(b, 2), "what": what} for a, b in merged)
    return sorted(out, key=lambda x: (x["start_s"], x["end_s"], x["what"]))


def overlaps(start: float, length: float, span: Mapping[str, Any]) -> bool:
    """Does the section ``start``..``start + length`` show any of ``span`` (an ``avoid`` entry)?"""
    return start < float(span["end_s"]) - 1e-9 and start + length > float(span["start_s"]) + 1e-9


def drop_window(
    analysis: Mapping[str, Any], *, classic: bool, duration: float, avoid: list[Mapping[str, Any]] | tuple = (), lead_s: float = 0.0
) -> dict[str, float]:
    """The section Genjutsu gets: ``{start_s, length_s}`` (pure).

    The target is 12-15 s for a classic and 8-10 s for any other clip (owner 2026-10-05), never over 16 s or under 6 s. It
    stays inside one shot when one is long enough (the analysis' cuts), else in the longest shot (at least 6 s), else it
    crosses as few cuts as it must. Among the windows that qualify, the one with the most motion wins (the analysis' energy per
    0.5 s), ties to the longer then the earlier; the ends move to the nearest beats when that keeps the length in range. A
    clip shorter than 6 s is refused (``ValueError``).

    ``avoid`` (``avoid_spans``: text or a watermark on screen): no window may overlap one. When none of the target length is
    clear, a shorter one (never under 6 s) is taken; when none of 6 s is clear, ``NoCleanSection``.

    ``lead_s`` is what the character's kit adds before the dance (Reginald's pause, ``master.style_lead_s``): the window is at
    most ``MASTER_MAX_S - lead_s``, so the master stays within 16 s."""
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

    def clean(a: float, b: float) -> bool:
        return not any(overlaps(a, b - a, s) for s in avoid)

    def search(shortest: float, longest: float) -> tuple[int, float, float, float] | None:
        best: tuple[int, float, float, float] | None = None  # (cuts, -energy, -length, start)
        length = shortest
        while length <= longest + 1e-9:
            start = 0.0
            while start + length <= total + 1e-9:
                if clean(start, start + length):
                    key = (inside(start, start + length), -round(mean_energy(start, start + length), 6), -length, start)
                    if best is None or key < best:
                        best = key
                start += WINDOW_STEP_S
            length += WINDOW_STEP_S
        return best

    hi = min(hi, MASTER_MAX_S - lead_s, total)
    lo = min(lo, hi)
    longest_shot = max((b - a for a, b in _shots(cuts, total)), default=total)
    if longest_shot < lo:  # no shot is long enough: shorten to the longest shot (never under 6 s)
        lo = max(MASTER_MIN_S, math.floor(longest_shot / WINDOW_STEP_S) * WINDOW_STEP_S)
        hi = max(lo, min(hi, lo))
    best = search(lo, hi)
    if best is None and lo > MASTER_MIN_S:  # text or a watermark in every window of the target length: a shorter clean one
        best = search(MASTER_MIN_S, lo - WINDOW_STEP_S)
    if best is None:
        raise NoCleanSection("text or a watermark is on screen in every usable section")
    start, length = best[3], -best[2]
    if beats:
        s2 = min(beats, key=lambda b: abs(b - start))
        e2 = min(beats, key=lambda b: abs(b - (start + length)))
        shortest = min(lo, length)
        if abs(s2 - start) <= 0.35 and abs(e2 - start - length) <= 0.35 and shortest - 1e-9 <= e2 - s2 <= hi + 1e-9 and e2 <= total + 1e-9:
            if inside(s2, e2) <= best[0] and clean(s2, e2) and s2 >= 0:
                start, length = s2, e2 - s2
    return {"start_s": round(start, 3), "length_s": round(length, 3)}


def _clear_by(start: float, length: float, avoid: list[Mapping[str, Any]], gap: float) -> bool:
    """Is the section ``start``..``start + length`` at least ``gap`` seconds away from every ``avoid`` span?"""
    end = start + length
    return all(float(s["start_s"]) - end >= gap - 1e-9 or start - float(s["end_s"]) >= gap - 1e-9 for s in avoid)


def drop_score(look: Mapping[str, Any], window: Mapping[str, float], avoid: list[Mapping[str, Any]], has_audio: bool) -> dict[str, Any]:
    """The clip's score (terminal v3, spec section 3; pure): ``{"total": 0-100, "potential": 0-10, "swap": 0-10, "reason"}``.

    ``potential`` and ``reason`` are the deconstruct's (Gemini: how likely the clip gets views). ``swap`` is how easy the clip is
    to swap, from the check: one body in frame 3 (two 1, more 0; a dog or animal star counts as one besides the people), the
    star's full body 2, a static camera 2 (handheld 1), the section at least ``SCORE_CLEAR_S`` away from every text or watermark
    span 1, sound 1, a classic 1; capped at 10. ``total`` = round(10 x (0.6 x potential + 0.4 x swap))."""
    star = look["star"]
    in_frame = int(look["people_count"]) + (1 if star.get("kind") in ("dog", "animal") else 0)
    swap = {1: 3, 2: 1}.get(in_frame, 0)
    swap += 2 if star.get("full_body") else 0
    swap += {"static": 2, "handheld": 1}.get(look["camera"], 0)
    swap += 1 if _clear_by(float(window["start_s"]), float(window["length_s"]), avoid, SCORE_CLEAR_S) else 0
    swap += 1 if has_audio else 0
    swap += 1 if look["classic"] else 0
    swap = min(swap, 10)
    potential = int(look["potential"]["score"])
    return {
        "total": round(10 * (0.6 * potential + 0.4 * swap)), "potential": potential, "swap": swap,
        "reason": look["potential"]["reason"],
    }


def crop_for(width: int, height: int, x_center: float | None) -> float | None:
    """The ``--crop-x`` of a landscape clip (the star's centre, kept inside the frame); None for a vertical one."""
    if width <= height * 9 / 16 + 1:
        return None
    x = 0.5 if x_center is None else float(x_center)
    return round(min(max(x, 0.0), 1.0), 3)


# ---- the owner's Adjust ----------------------------------------------------------------------------------------------------------


def validate_adjust(adjust: Any, drop: Mapping[str, Any], *, lead_s: float = 0.0) -> dict[str, Any]:
    """The owner's Adjust of a ready drop (``drop['adjust']``, written by request_job), checked again here (fail closed).

    Every key optional: ``star`` (1-80 characters: who is replaced), ``part`` (cameo, featured or star), ``gadgets`` (at most 3
    of 1-40 characters), ``hook`` (1-80 characters), ``start_s`` (0 or more) and ``length_s`` (6-16 s, inside the video, clear
    of the text and watermark moments of ``drop['avoid']``), ``crop_x`` (0-1 or null). ``ValueError`` names the first problem.

    ``lead_s`` is what the character's kit adds before the dance (``master.style_lead_s``: Reginald's pause): the section is at
    most ``MASTER_MAX_S - lead_s`` s, so the master (the lead plus the section) can never pass 16 s once Genjutsu has been paid.
    The terminal and ``request_job`` only know 6-16 s: this check is the binding one."""
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
        longest = MASTER_MAX_S - lead_s
        if not MASTER_MIN_S <= length <= longest + 1e-9:
            why = f": the master starts {lead_s:g} s later (the character's pause), so it stays within {MASTER_MAX_S:g} s" if lead_s else ""
            raise ValueError(f"adjust.length_s must be {MASTER_MIN_S:g}-{longest:g} s{why}")
        if duration and start + length > duration + SLACK_S:
            raise ValueError(f"the section {start:g}-{start + length:g} s runs past the end of the {duration:g} s video")
        for span in drop.get("avoid") or []:  # only the section is judged: it may not show text or a watermark
            if overlaps(start, length, span):
                what = "a watermark" if span.get("what") == "watermark" else "text"
                raise ValueError(
                    f"the section {start:g}-{start + length:g} s shows {what} on screen ({span['start_s']:g}-{span['end_s']:g} s): "
                    "Genjutsu would keep it"
                )
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


def effective(drop: Mapping[str, Any], *, lead_s: float = 0.0, swap_part: str | None = None) -> dict[str, Any]:
    """What the make job uses: the process job's choices with the owner's Adjust on top (``lead_s``: see ``validate_adjust``).
    His part: the owner's Adjust, else the character's own (refs.json ``swap_part``, read at Make it: Franz performs as the star),
    else the check's suggestion, else featured. His hook: the owner's Adjust when it saved one (any explicit choice, the check's first
    included), else the one the hook bandit drew at Make it (``drop['make']['bandit']``, learning test B), else the check's first."""
    adjust = validate_adjust(drop.get("adjust"), drop, lead_s=lead_s)
    window = drop.get("window") or {}
    star = drop.get("star") or {}
    hook = adjust.get("hook", drop.get("hook"))
    chosen = bandit_hook(drop)
    if chosen is not None and "hook" not in adjust:
        hook = chosen  # the bandit's draw, unless the owner's Adjust saved a hook (his own choice always wins)
    return {
        "star": adjust.get("star", star.get("description")),
        "body": star.get("body"),
        "part": adjust.get("part") or swap_part or drop.get("part") or "featured",
        "gadgets": adjust.get("gadgets", drop.get("gadgets", [])),
        "hook": hook,
        "start_s": adjust.get("start_s", float(window.get("start_s", 0.0))),
        "length_s": adjust.get("length_s", float(window.get("length_s", 0.0))),
        "crop_x": adjust["crop_x"] if "crop_x" in adjust else drop.get("crop_x"),
    }


SWAP_KEEP_LINE = (  # owner 2026-10-08 (his swap prompt, two lines folded in): the images give the character only, the scene is the clip's
    "Use the reference images for the character only. Keep the original's camera movement, framing, lighting and colour grading, "
    "and match its colour grading."
)


def swap_prompt(star: str, noun: str, part: str, gadgets: list[str], performance: str | None = None) -> str:
    """The SHORT Object swap prompt (Higgsfield's own form): who is replaced, by whom, ``SWAP_KEEP_LINE`` (the reference images
    are for the character only; the clip's camera, framing, lighting and grading stay), his part, his gadgets, and the character's
    one performance line when his refs.json has one (``swap_performance``: how he performs the moves); without it, as before."""
    lines = [f"Replace {star.strip().rstrip('.')} with the {noun} from the reference images.", SWAP_KEEP_LINE]
    lines.append({
        "cameo": "Keep his motion minimal and natural; the scene stays the same.",
        "featured": "He follows the original performer's motion exactly; the scene stays the same.",
        "star": "He performs every beat with full energy; the scene stays the same.",
    }[part])
    if gadgets:
        lines.append(f"He wears or holds: {', '.join(gadgets)} (no brand logos).")
    if performance and performance.strip():
        lines.append(f"Performance: {' '.join(performance.split()).rstrip('.')}.")
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

# What a link dropped again does not inherit from the drop it files over (migration 0017's strip list, final review M1 and task 19
# review M2): the check's score and rules version, the hits job's tags and the trend reading it took at filing (TREND_TAGS).
# `job` stays: it holds a live worker's lease.
MERGE_STRIP = ("score", "hit_rules_version", "auto_filed", "hit", "fetch_days", "trend_stage", "days_since_trend_peak", "sound_rising")


def add_drop(
    store: Store, character_slug: str | None, link: str | None, now: datetime | None = None, *, own_footage: bool = False,
    characters_dir: Path | str = seed.DEFAULT_CHARACTERS_DIR, provisional_slug: str | None = None, auto_filed: bool = False,
    hit: Mapping[str, Any] | None = None, trend: Mapping[str, Any] | None = None,
) -> tuple[Favorite, bool]:
    """File a drop: ``(pick, duplicate)``. A file (``link`` None) is a new pick keyed ``owner-drop:<id>`` at ``uploading``; a link
    is its canonical URL at ``checking``, and a link already a pick of this character becomes that pick's drop (a pick already
    queued or made is returned as it is, ``duplicate`` True); the earlier drop's keys stay under the new drop's (``MERGE_STRIP`` aside),
    exactly as 0017's ``studio.add_drop`` merges them. ``own_footage`` (owner 2026-10-06, for reporting later): the owner's
    own recording or footage used with permission; the default is a downloaded clip (False). It does not change the generation.

    ``character_slug`` None (owner 2026-10-06, the Drop box's "Recommend"): the studio chooses after the check
    (``character_by`` studio); the drop waits under ``provisional``, and a link is matched against every pick of that URL (the
    oldest), keeping that pick's character while he is not paused. With a character it is the owner's (``character_by`` owner).

    The cloud hits job (``studio.hits.auto_file``, plan Task 6) files a hit's link with no character and ``provisional_slug`` = the
    character whose keywords found it (used while he is in the live roster, else the studio's ``provisional``), ``auto_filed``
    (``drop['auto_filed']``: the learning tag ``source_kind``, retention's 30 days) and ``hit`` (``drop['hit']``: the hit's id and
    lane). It may also hand the LunarCrush reading of the hit's trend (``trend``, task 18: ``trend_stage``,
    ``days_since_trend_peak``, ``sound_rising``; any other key is ignored), written onto the drop's top level, where ``learn_tags``
    reads them: a stage it does not know (``unknown``, ``classic``) is the tag ``none`` there."""
    now = now or now_london()
    if character_slug is None:
        crew = {c.slug for c in roster(store, characters_dir)} if provisional_slug else set()
        character_slug = provisional_slug if provisional_slug in crew else provisional(store, characters_dir)
        by = "studio"
    elif character_slug not in {c.slug for c in store.characters()}:
        raise ValueError(f"unknown character {character_slug!r}")
    else:
        by = "owner"
    record = {"decision": "approve", "by": "owner", "reason": "owner's own video", "at": now.isoformat()}
    tags: dict[str, Any] = {"auto_filed": True} if auto_filed else {}
    if hit is not None:
        tags["hit"] = dict(hit)
    if trend is not None:
        tags.update({k: v for k, v in trend.items() if k in TREND_TAGS})
    if link is None:
        pick_id = str(uuid.uuid4())
        drop = {
            "state": "uploading", "kind": "file", "at": now.isoformat(), "reason": None, "own_footage": bool(own_footage),
            "character_by": by, **tags,
        }
        return store.add_favorite(Favorite(
            id=pick_id, url=f"{DROP_URL_PREFIX}{pick_id}", platform=DROP_PLATFORM, origin="owner", character_slug=character_slug,
            proposal={"decision": record, "drop": drop}, status="approved",
        )), False  # fmt: skip
    platform, canonical = parse_video_url(link)
    drop = {
        "state": "checking", "kind": "link", "at": now.isoformat(), "reason": None, "own_footage": bool(own_footage),
        "character_by": by, **tags,
    }
    handle = canonical.split("/@", 1)[1].split("/", 1)[0] if platform == "tiktok" else None
    found = store.list_favorites(url=canonical) if by == "studio" else store.list_favorites(url=canonical, character_slug=character_slug)
    for f in sorted(found, key=lambda f: (f.created_at.timestamp() if f.created_at else 0.0, f.id)):
        if f.status in ("queued", "made"):
            return f, True
        if by == "studio" and f.character_slug in {c.slug for c in store.characters() if c.status != "paused"}:
            character_slug = f.character_slug  # the pick's own character is the provisional one while he is not paused
        proposal = {k: v for k, v in f.proposal.items() if k != "hold_reason"}
        earlier = f.proposal.get("drop")  # the earlier drop's keys stay, the new ones win (migration 0017); no object counts as empty
        kept = {k: v for k, v in earlier.items() if k not in MERGE_STRIP} if isinstance(earlier, Mapping) else {}
        proposal.update(decision=record, drop={**kept, **drop})
        return store.update_favorite(f.id, status="approved", character_slug=character_slug, proposal=proposal), True
    return store.add_favorite(Favorite(
        url=canonical, platform=platform, origin="owner", character_slug=character_slug,
        creator_handle=f"@{handle}" if handle else None, proposal={"decision": record, "drop": drop}, status="approved",
    )), False  # fmt: skip


CLIP_EXTENSIONS = ("mp4", "mov", "m4v")
CLIP_MAX_BYTES = 200 * 1024 * 1024  # the terminal's limit for a dropped video


def attach_file(store: Store, storage: Storage, pick_id: str, file: Path, now: datetime | None = None) -> str:
    """Upload a saved video for a file drop and attach it, exactly as the terminal does (``sources/owner/<pick>/<ms>.<ext>``,
    then ``attach_clip``): the owner's saved clips on the Mac (``inbox/drops``) go in without the browser. Returns the path.
    ``DropError`` for a link drop, a drop already past ``uploading``, or a file that is not a video under the size limit."""
    now = now or now_london()
    pick = _load(store, pick_id)
    d = drop_of(pick)
    if d.get("kind") != "file":
        raise DropError(f"pick {pick.id} is not a file drop")
    if d.get("state") != "uploading":
        raise DropError(f"pick {pick.id} is {d.get('state')}: a file is attached only while it is uploading")
    ext = file.suffix.lower().lstrip(".")
    if ext not in CLIP_EXTENSIONS or not file.is_file():
        raise DropError(f"{file.name} is not a video file (.mp4, .mov or .m4v)")
    if file.stat().st_size > CLIP_MAX_BYTES:
        raise DropError(f"{file.name} is over {CLIP_MAX_BYTES // (1024 * 1024)} MB")
    path = f"owner/{pick.id}/{int(now.timestamp() * 1000)}.{ext}"
    storage.upload("sources", path, file)
    store.update_favorite(pick.id, proposal={**pick.proposal, "owner_clip_path": path}, source_id=None)
    return path


def request_check(store: Store, pick_id: str, now: datetime | None = None) -> Favorite:
    """Ask for the free check, exactly what the terminal's ``studio.request_job(pick, 'process')`` writes (migration 0012) once its
    file is attached: the drop goes to ``checking`` (``reason`` cleared, ``at`` and ``requested.process`` stamped), so ``pending()``
    and the cloud sweep take it and the terminal shows a drop waiting for its check, not an upload that never finished. The same
    refusals: ``DropError`` for a pick already made, a state other than uploading, checking, waiting or failed, or an uploading
    drop whose file is not attached yet. (The GitHub dispatch is the database's own; the cloud sweep and ``nudge_cloud`` do it here.)"""
    now = now or now_london()
    pick = _load(store, pick_id)
    if pick.status == "made":
        raise DropError(f"pick {pick.id} is already made")
    d = drop_of(pick)
    state = d.get("state")
    if state not in CHECK_REQUEST_FROM:
        raise DropError(f"a check runs on an uploading, checking, waiting or failed drop; pick {pick.id} is {state}")
    if state == "uploading" and not pick.proposal.get("owner_clip_path"):
        raise DropError("the upload has not finished: attach the video first")
    requested = {**(d.get("requested") or {}), "process": now.isoformat()}
    return _update(store, pick, now, state="checking", reason=None, at=now.isoformat(), requested=requested)


def request_recheck(store: Store, pick_id: str, now: datetime | None = None) -> Favorite:
    """Check a ``ready`` drop again (free, terminal v3): a drop checked before the score existed gets one, and any drop is looked
    at again with the current hit rules. The drop goes to ``checking`` stamped exactly as ``request_check`` stamps it, and its old
    ``score`` goes (only the new check's end may give one); the cloud sweep or the next dispatch takes it (nothing is dispatched
    here).

    ``DropError`` (one line) for a pick the owner sent with Make it (``proposal.make_requested``: re-checking would move a paid
    job), a drop that is ``making`` or ``made``, a pick already ``made`` or ``queued``, or any state but ``ready``; ``KeyError``
    for an unknown pick."""
    now = now or now_london()
    pick = _load(store, pick_id)
    state = drop_of(pick).get("state")
    if pick.proposal.get("make_requested") is not None:
        raise DropError(f"pick {pick.id} has a Make it (the owner's or the studio's): a recheck would move a paid job")
    if state in ("making", "made"):
        raise DropError(f"pick {pick.id} is {state}: a recheck would move a paid job")
    if pick.status in ("made", "queued"):
        raise DropError(f"pick {pick.id} is already {pick.status}")
    if state != "ready":
        raise DropError(f"only a ready drop is checked again; pick {pick.id} is {state}")
    d = drop_of(pick)
    requested = {**(d.get("requested") or {}), "process": now.isoformat()}
    return _update(store, pick, now, state="checking", reason=None, at=now.isoformat(), requested=requested, score=None)


def copy_drop(
    store: Store, pick_id: str, character_slug: str, now: datetime | None = None, *,
    characters_dir: Path | str = seed.DEFAULT_CHARACTERS_DIR,
) -> Favorite:
    """Use a checked clip for another character (terminal v3, spec section 4; free): file a **version**, a new pick that shares
    the root's full clip (nothing is uploaded again) and gets its own free check, in his voice and at his price.

    ``pick_id`` is the root drop or any version of it: the version always points at the ROOT (``drop.copy_of``). It is a file
    drop keyed ``owner-drop:<new id>`` (platform ``drop``, origin ``owner``, ``approved``, the root's ``source_id`` and creator
    handle, and the root's ``fetched`` marker when it has one, so ``source purge`` deletes the shared clip only once the last
    member is done) at ``checking`` with ``character_by`` owner, ``copy_of``, the root's ``kind`` and ``own_footage`` (and its
    ``auto_filed`` tag when the hits job filed it, migration 0016), and ``requested.process`` stamped: the cloud sweep (or the
    RPC's dispatch) checks it.

    Refused (``DropError``, one plain line, nothing written), in this order: the root's check has not finished (``ready``,
    ``making`` or ``made``, with a source) "the clip is not checked yet" (asked from a version's card: "the original clip is being
    checked again: try in a few minutes" while the root is uploading, checking or waiting, "the original clip can't be used any
    more" when it is blocked or failed); its file was deleted after posting; an unknown
    character; he is in the family already "<Name> already has a version of this clip"; the family has ``MAX_FAMILY`` members
    "a clip goes to at most 3 characters" (skipped picks do not count); he is paused "<Name> is paused"; like for like with the
    root's star fails (``like_for_like``'s own line, from his refs.json). ``KeyError`` for an unknown pick. SQL
    ``studio.copy_drop`` (migration 0015) applies the same rules."""
    now = now or now_london()
    pick = _load(store, pick_id)
    root_id = family_root_id(pick)
    root = pick if root_id == pick.id else store.get_favorite(root_id)
    if root is None or not is_drop(root.proposal):
        raise DropError(f"the original clip {root_id} is gone")
    d = drop_of(root)
    source_id = root.source_id or d.get("source_id")
    if root.id != pick.id and d.get("state") in ("blocked", "failed"):  # from a version's card: say what is true of the root
        raise DropError("the original clip can't be used any more")
    if root.id != pick.id and d.get("state") in PROCESS_FROM:
        raise DropError("the original clip is being checked again: try in a few minutes")
    if d.get("state") not in CHECKED_STATES or not source_id:
        raise DropError("the clip is not checked yet")
    src = next(iter(store.list_sources(id=source_id)), None)
    if src is None or not src.storage_path:
        raise DropError("the clip's file is gone (deleted after posting): drop it again")
    target = next((c for c in store.characters() if c.slug == character_slug), None)
    if target is None:
        raise DropError(f"unknown character {character_slug!r}")
    ref, _ = character(character_slug, characters_dir)
    name = ref["name"]
    members = family(store, root)
    if any(m.character_slug == character_slug for m in members):
        raise DropError(f"{name} already has a version of this clip")
    if len(members) >= MAX_FAMILY:
        raise DropError(f"a clip goes to at most {MAX_FAMILY} characters")
    if target.status == "paused":
        raise DropError(f"{name} is paused")
    wrong = like_for_like(d.get("star") or {}, ref, name)
    if wrong is not None:
        raise DropError(wrong)
    at = now.isoformat()
    proposal: dict[str, Any] = {
        "decision": {"decision": "approve", "by": "owner", "reason": "owner's own video", "at": at},
        "drop": {
            "state": "checking", "kind": d.get("kind", "file"), "at": at, "reason": None,
            "own_footage": bool(d.get("own_footage", False)), "character_by": "owner", "copy_of": root.id,
            "requested": {"process": at},
        },
    }
    marker = root.proposal.get("fetched")
    if isinstance(marker, Mapping):  # one download, shared like the "Both" pick of a video (studio.fetch)
        proposal["fetched"] = {k: v for k, v in marker.items() if k != "purged_at"}
    if d.get("auto_filed") is True:  # the hits job's tag (learning's source_kind, retention's 30 days) goes into the version too
        proposal["drop"]["auto_filed"] = True
    version_id = str(uuid.uuid4())
    return store.add_favorite(Favorite(
        id=version_id, url=f"{DROP_URL_PREFIX}{version_id}", platform=DROP_PLATFORM, origin="owner",
        character_slug=character_slug, creator_handle=root.creator_handle, proposal=proposal, status="approved",
        source_id=source_id,
    ))  # fmt: skip


def set_own_footage(store: Store, pick_id: str, own_footage: bool) -> Favorite:
    """The owner's toggle (``studio.set_drop_footage``, migration 0012): ``drop['own_footage']``, for reporting; any state."""
    pick = _load(store, pick_id)
    if not isinstance(own_footage, bool):
        raise ValueError("own_footage must be true or false")
    return store.update_favorite(pick.id, proposal={**pick.proposal, "drop": {**drop_of(pick), "own_footage": own_footage}})


def set_keep(store: Store, pick_id: str, keep: bool) -> Favorite:
    """The owner's Keep (``studio.set_drop_keep``, migration 0016): ``drop['keep']``; a kept drop's clip is never deleted by
    retention (``studio.fetch.purge_stale``). Any state. ``DropError`` for a pick that is not a drop, ``KeyError`` for none."""
    pick = store.get_favorite(pick_id)
    if pick is None:
        raise KeyError(pick_id)
    if not isinstance(keep, bool):
        raise ValueError("keep must be true or false")
    return store.update_favorite(pick.id, proposal={**pick.proposal, "drop": {**drop_of(pick), "keep": keep}})


# ---- process -------------------------------------------------------------------------------------------------------------------


@dataclass
class Outcome:
    pick_id: str
    state: str
    reason: str | None = None
    ok: bool = True
    detail: dict[str, Any] | None = None

    @property
    def red(self) -> bool:
        """A real problem, which a run answers with a non-zero exit: not ok, and not a Gemini quota 429 the sweep takes again by
        itself (``detail.will_retry``, set by ``check_failed_reason``'s caller): that one is failed and says so, but is no alarm."""
        return not self.ok and not (self.detail or {}).get("will_retry")

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


def _get_source(store: Store, storage: Storage, pick: Favorite, now: datetime, runner: Any, media_fallback: Any = None) -> Source | Outcome:
    """The pick's full clip as a source: the owner's upload, or the pasted link fetched once: yt-dlp, else (with
    ``media_fallback``, the ScrapeCreators client of the cloud jobs) that one post's copy (a failure of both: ``waiting``, with
    both reasons)."""
    if pick.source_id:
        found = next(iter(store.list_sources(id=pick.source_id)), None)
        if found is not None and found.storage_path:
            return found
    if pick.proposal.get("owner_clip_path"):
        try:
            return sources.ingest_owner_clip(store, storage, pick.id)
        except ValueError as e:
            pick = _unready(store, pick, now, state="blocked", reason=str(e))
            return Outcome(pick.id, "blocked", str(e))
    if pick.platform == DROP_PLATFORM:
        return Outcome(pick.id, drop_of(pick)["state"], "the upload has not finished", detail={"waiting_for": "upload"})
    try:
        result = fetch.fetch_pick_clip(store, storage, pick.id, runner=runner, fall_back=False, media_fallback=media_fallback)
    except fetch.FetchFailed as e:
        d = drop_of(pick)
        if d.get("auto_filed") is True:  # never the Mac's (controller ruling 2026-10-08): the cloud tries again on a later day
            reason = (
                f"the link could not be fetched in the cloud ({str(e)[:260]}): the cloud tries again on a later day "
                f"(dropped after {AUTO_FETCH_DAYS} days)"
            )
            tried = sorted({*[x for x in d.get("fetch_days") or [] if isinstance(x, str)], now.astimezone(LONDON).date().isoformat()})
            _unready(store, pick, now, state="waiting", reason=reason, fetch_days=tried)
        else:
            reason = f"the link could not be fetched in the cloud ({str(e)[:260]}): the Mac's daily run tries again"
            _unready(store, pick, now, state="waiting", reason=reason)
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


def _blocked_reason(answer: Mapping[str, Any], ref: Mapping[str, Any], name: str) -> str | None:
    """Why the clip cannot be made with this character whatever section is taken (text and a watermark are the section's
    business: ``drop_window`` keeps clear of them, ``_unclean_reason`` says when nothing is left)."""
    if answer["star"].get("child"):  # children elsewhere in the clip are fine (owner 2026-10-06): only the star we replace must be an adult
        return "the star is a child: our character only replaces an adult"
    return like_for_like(answer["star"], ref, name)


def _unclean_reason(avoid: list[Mapping[str, Any]], link: bool) -> str:
    """The blocked line when no clean section is left: only text and watermark spans speak; another family member's section
    (``what: version``) is never a reason (``_section`` drops those before it gives up)."""
    base = "text or a watermark is on screen in every usable section"
    if any(x["what"] == "watermark" for x in avoid):
        return f"{base}: {'we cannot use this clip' if link else 'paste the link instead'}"
    return f"{base}: Genjutsu would keep it, drop a clean copy"


def _section(
    free: Mapping[str, Any], *, classic: bool, duration: float, avoid: list[Mapping[str, Any]], others: list[Mapping[str, Any]],
    lead_s: float,
) -> dict[str, float]:
    """The section a check takes: the best one (``drop_window``), or, for a family member, another part of the clip clear of
    the other members' sections too (``family_spans``) when that part is as long as the target (12 s for a classic, 8 s for any
    other clip, capped as ``drop_window`` caps) or as the best section, whichever is shorter. The family's sections are no text:
    a version never takes a shorter cut to avoid them (``drop_window``'s shorter fallback is for text and watermarks only).
    ``NoCleanSection`` only when text or a watermark leaves no section at all."""
    best = drop_window(free, classic=classic, duration=duration, avoid=avoid, lead_s=lead_s)
    if not others:
        return best
    try:
        other = drop_window(free, classic=classic, duration=duration, avoid=[*avoid, *others], lead_s=lead_s)
    except NoCleanSection:
        return best
    target = min((WINDOW_CLASSIC if classic else WINDOW_OTHER)[0], MASTER_MAX_S - lead_s, duration)
    return other if other["length_s"] >= min(best["length_s"], target) - 1e-3 else best


def _recommended_slug(answer: Mapping[str, Any], crew: list[gemini.Character]) -> str | None:
    rec = answer.get("recommended")
    slug = rec.get("slug") if isinstance(rec, Mapping) else None
    return slug if slug in {c.slug for c in crew} else None


def _still(store: Store, pick_id: str, slug: str) -> Favorite:
    """The pick as it is now, while its character is still ``slug`` (else the owner moved it: ``_CharacterChanged``)."""
    fresh = store.get_favorite(pick_id)
    if fresh is None or fresh.character_slug != slug:
        raise _CharacterChanged()
    return fresh


def _switch(store: Store, pick_id: str, slug: str, to: str) -> Favorite:
    """The studio's own move to the character it recommends: only while the choice is still the studio's and nobody moved it."""
    fresh = _still(store, pick_id, slug)
    if drop_of(fresh).get("character_by") != "studio":
        raise _CharacterChanged()
    return mark_favorite(store, pick_id, fresh.status, character_slug=to)


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
    media_fallback: Any = None,
    auto_retry: bool = False,
    listed: Mapping[str, str] | None = None,
) -> Outcome:
    """Check a dropped video (free) and make it ``ready`` (see the module doc). ``KeyError`` for an unknown pick, ``DropError``
    for a pick that is not a drop or not at a step a check runs from; ``StorageError`` when our own Storage fails. When the
    owner chooses another character during the check, it starts again for him (up to ``CHANGE_RESTARTS`` times).
    ``auto_retry`` (the sweep, for a drop ``pending`` listed as ``failed``): a failed check that ``auto_retry_kind`` still allows
    goes back to ``checking`` under the lease (``drop.auto_retries`` + 1, ``drop.auto_retry_at``; ``requested`` untouched, so the
    owner's own Try again stays recognisable) and is checked again; otherwise it is left as it is (busy). Without it a failed
    drop is refused, as ever. ``listed`` (the sweep passes the row ``pending`` gave it): the failure as it was listed
    (``failure_stamp``); read again under the lease, a drop whose ``at`` or ``auto_retry_at`` differs has moved on (another
    worker retook it, and it failed again) and is left alone (busy): one sweep spends one automatic retry per drop.
    ``media_fallback`` (``studio.hits.ScrapeCreators``, the cloud jobs pass it when the key is set): a link yt-dlp cannot fetch
    is taken from ScrapeCreators' copy of that one post (``studio.fetch.fetch_pick_clip``)."""
    now = now or now_london()
    job = job or job_id()
    pick = _load(store, pick_id)
    state = drop_of(pick)["state"]
    retaking = auto_retry and state == "failed"
    if state not in PROCESS_FROM and not retaking:
        raise DropError(f"pick {pick_id} is {state}: a check runs on an uploading, checking or waiting drop")
    if not claim(store, pick_id, "process", job, now):
        return Outcome(pick_id, state, "another run is checking this video", detail={"busy": True})
    try:
        # read again under the lease: a parallel worker of the same sweep may have finished this drop since it was listed
        fresh = _load(store, pick_id)
        now_state = drop_of(fresh)["state"]
        if retaking and now_state == "failed":
            if listed is not None and not same_failure(listed, drop_of(fresh)):
                return Outcome(pick_id, now_state, "another run already took this failed check again", detail={"busy": True})
            if auto_retry_kind(fresh, now) is None:
                return Outcome(pick_id, now_state, "this failed check is not taken again by itself", detail={"busy": True})
            _update(
                store, fresh, now, state="checking", reason=None, auto_retries=auto_retries_used(drop_of(fresh)) + 1,
                auto_retry_at=now.isoformat(),
            )
        elif now_state not in PROCESS_FROM:
            return Outcome(pick_id, now_state, "another run already checked this video", detail={"busy": True})
        for _ in range(CHANGE_RESTARTS + 1):
            try:
                return _process(
                    store, storage, store.get_favorite(pick_id), gemini_client, deconstruct_answer, runner, now, characters_dir,
                    media_fallback=media_fallback,
                )
            except _CharacterChanged:
                if deconstruct_answer is not None:
                    raise DropError("the owner chose another character during the check: write the deconstruct for him") from None
        reason = "the character changed during every look: the next run checks it again"
        fresh = _unready(store, store.get_favorite(pick_id), now, reason=reason)
        return Outcome(pick_id, drop_of(fresh)["state"], reason, ok=False)
    except (DropError, StorageError):
        raise
    except Exception as e:
        reason = f"the check stopped: {type(e).__name__}: {str(e)[:160]}"
        _unready(store, store.get_favorite(pick_id), now, state="failed", reason=reason)
        return Outcome(pick_id, "failed", reason, ok=False)
    finally:
        release(store, pick_id, job)


def _process(
    store: Store, storage: Storage, pick: Favorite, client: gemini.GeminiClient | None,
    answer: Mapping[str, Any] | None, runner: Any, now: datetime, characters_dir: Path | str, *, media_fallback: Any = None,
) -> Outcome:
    slug = pick.character_slug
    ref, who = character(slug, characters_dir)
    crew = roster(store, characters_dir)
    rules_version = gemini.hit_rules_version()  # the hit rules this look is judged by (the clip's hit_rules_version tag)
    by_studio = drop_of(pick).get("character_by") == "studio"
    in_family = {m.character_slug for m in family(store, pick) if m.id != pick.id}  # the studio never moves it to one of them
    got = _get_source(store, storage, pick, now, runner, media_fallback)
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
            _unready(store, pick, now, state="blocked", reason=reason, source_id=src.id)
            return Outcome(pick.id, "blocked", reason)
        if report.duration_s < MASTER_MIN_S - SLACK_S:
            reason = f"the video is {report.duration_s:.1f} s: a video needs at least {MASTER_MIN_S:g} s"
            _unready(store, pick, now, state="blocked", reason=reason, source_id=src.id)
            return Outcome(pick.id, "blocked", reason)
        try:
            free = analyze_clip(local, work / "analysis.png")
        except AnalysisError as e:
            reason = f"the video could not be analysed: {e}"
            _unready(store, pick, now, state="blocked", reason=reason, source_id=src.id)
            return Outcome(pick.id, "blocked", reason)
        basics = {
            "source_id": src.id, "duration_s": round(report.duration_s, 3), "width": report.width, "height": report.height,
            "has_audio": report.has_audio,
        }
        if answer is not None:
            # by hand: written for the character it recommends when the choice is the studio's (the skill says so)
            target = (_recommended_slug(answer, crew) if by_studio else None) or slug
            target = slug if target in in_family else target
            ref_t, who_t = (ref, who) if target == slug else character(target, characters_dir)
            problems = gemini.deconstruct_problems(answer, who_t, crew)
            if problems:
                raise DropError("the deconstruct file breaks the rules: " + "; ".join(problems))
            look = gemini.tidy_deconstruct(answer, who_t)
            recommended = look["recommended"]
            if target != slug:
                _switch(store, pick.id, slug, target)
                slug, ref, who = target, ref_t, who_t
        elif client is None:
            reason = "waiting for the Gemini key: the next daily run looks at it by hand"
            _unready(store, pick, now, state="checking", reason=reason, **basics)
            return Outcome(pick.id, "checking", reason, detail={**basics, "best_window": free["best_window"]})
        else:
            proxy = clipwork.proxy_clip(local, work / "proxy.mp4")
            try:
                look = gemini.deconstruct(client, proxy, who, crew, used_hooks(store, slug, pick.id), hook_arms_for(slug, now))
                recommended = look["recommended"]  # the one the card shows (the second look is asked in his voice only)
                if by_studio and recommended["slug"] != slug and recommended["slug"] not in in_family:
                    _switch(store, pick.id, slug, recommended["slug"])
                    slug = recommended["slug"]
                    ref, who = character(slug, characters_dir)
                    look = gemini.deconstruct(  # once more, his voice (and his arms)
                        client, proxy, who, crew, used_hooks(store, slug, pick.id), hook_arms_for(slug, now),
                    )
            except gemini.GeminiBlocked as e:
                reason = f"Gemini would not look at this clip ({e}): we cannot use it"
                _unready(store, _still(store, pick.id, slug), now, state="blocked", reason=reason, **basics)
                return Outcome(pick.id, "blocked", reason)
            except gemini.GeminiError as e:
                pick = _still(store, pick.id, slug)
                reason, retries = check_failed_reason(e, drop_of(pick))
                _unready(store, pick, now, state="failed", reason=reason, **basics)
                return Outcome(pick.id, "failed", reason, ok=False, detail={"will_retry": True} if retries else None)
        pick = _still(store, pick.id, slug)
        sources.record_checks(  # anywhere in the clip: the section's own flags are set when it is cut (_child)
            store, src.id, has_watermark=look["watermark"] or bool(look["watermark_spans"]),
            has_overlay=look["burned_in_text"] or bool(look["burned_in_text_spans"]),
            other_people=max(0, look["people_count"] - 1), has_minors=look["minors"],
        )
        if look["star"]["body"] in (b.value for b in Body):
            store.update_source(src.id, body=look["star"]["body"])
        avoid = avoid_spans(look, report.duration_s)
        blocked = _blocked_reason(look, ref, who.name)
        if blocked is None:
            try:
                window = _section(
                    free, classic=look["classic"], duration=report.duration_s, avoid=avoid, others=family_spans(store, pick),
                    lead_s=style_lead_s(ref.get("style")),
                )
            except NoCleanSection:
                blocked = _unclean_reason(avoid, drop_of(pick).get("kind") == "link")
        if blocked is not None:
            _unready(store, pick, now, state="blocked", reason=blocked, **basics, star=look["star"], recommended=recommended, avoid=avoid)
            return Outcome(pick.id, "blocked", blocked, detail={"character": slug, "recommended": recommended})
        crop_x = crop_for(report.width, report.height, look["star"]["x_center"])
        credits = estimate_credits(Mode.dropin, window["length_s"], MUSIC)
        preview = _preview(storage, local, work, pick.id, window, crop_x)
        watch, _ = _watch_files(storage, local, work, pick.id, window, crop_x)  # never a reason to fail the check
    card = _analysis_card(look, free, window)
    hook = look["hooks"][0]
    pick = _still(store, pick.id, slug)  # read again: the owner's toggles during the look are kept
    proposal = {
        **pick.proposal, "mode": "dropin", "owner_mode": "dropin", "hook": hook, "concept": look["what_happens"],
        "analysis": card,
        "drop": {
            **drop_of(pick), **basics, "state": "ready", "reason": None, "at": now.isoformat(),
            "window": window, "crop_x": crop_x, "star": look["star"], "classic": look["classic"],
            # his own part when his refs.json has one (Make it reads it again): the Adjust sheet's default is what is made
            "part": ref.get("swap_part") or look["suggested_part"], "gadgets": look["gadgets"], "hooks": look["hooks"], "hook": hook,
            "deconstruct": look, "music": MUSIC, "seconds": window["length_s"], "credits": credits, "preview_path": preview,
            **watch,  # cover_path and preview_video_path: absent (null) when one could not be made, never an older check's
            "recommended": recommended, "avoid": avoid,
            # the longest section Make it takes for him (validate_adjust's cap): the terminal's Adjust checks it before Make it
            "max_length_s": round(MASTER_MAX_S - style_lead_s(ref.get("style")), 3),
            "score": drop_score(look, window, avoid, basics["has_audio"]),  # only a check that ends ready has one
            "hit_rules_version": rules_version,  # copied to the clip at make (learning plan section 2)
        },
    }
    proposal["drop"] = {k: v for k, v in proposal["drop"].items() if v is not None or k in ("reason", "crop_x")}
    mark_favorite(store, pick.id, pick.status, proposal=proposal, source_id=src.id)
    return Outcome(
        pick.id, "ready", None,
        detail={"credits": credits, "window": window, "crop_x": crop_x, "preview_path": preview, "character": slug, "recommended": recommended},
    )


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


def _watch_files(
    storage: Storage, local: Path, work: Path, pick_id: str, window: Mapping[str, float], crop_x: float | None,
) -> tuple[dict[str, str | None], list[str]]:
    """The clip card's picture and the owner's watch copy of the section (terminal v3 Task 11), next to the strip in
    ``sources/owner/<pick id>/``: ``cover.jpg`` (the middle frame of the section) and ``preview.mp4`` (the section with its own
    sound, 540x960; ``clipwork.cover_frame`` / ``preview_video``, cropped like the master when ``crop_x``). Returns
    ``({"cover_path": key | None, "preview_video_path": key | None}, problems)``. Never a reason to fail a check: any error (ffmpeg,
    the disk, our own Storage) is a warning and leaves that field None (the card then shows the strip, or the tile)."""
    start, length = float(window["start_s"]), float(window["length_s"])
    jobs = (
        ("cover_path", COVER_NAME, "the cover", lambda out: clipwork.cover_frame(local, out, start + length / 2, crop_x=crop_x)),
        ("preview_video_path", PREVIEW_VIDEO_NAME, "the watch copy", lambda out: clipwork.preview_video(local, out, start, length, crop_x=crop_x)),
    )
    paths: dict[str, str | None] = {}
    problems: list[str] = []
    for field, name, what, make in jobs:
        key = f"owner/{pick_id}/{name}"
        try:
            storage.upload(SOURCES_BUCKET, key, make(work / name))
        except Exception as e:  # noqa: BLE001: whatever it is, the check carries on without this file
            line = f"{what}: {type(e).__name__}: {' '.join(str(e).split())[:200]}"
            log.warning("drop %s: %s could not be made (%s): the card shows the strip instead", pick_id, what, line)
            problems.append(line)
            paths[field] = None
        else:
            paths[field] = key
    return paths, problems


def make_previews(store: Store, storage: Storage, pick_id: str) -> dict[str, Any]:
    """``studio drop previews``: the cover and watch copy (``_watch_files``) of a drop checked before they existed, from its clip
    in Storage, its section (``drop['window']``) and its crop: free (no Gemini, no Higgsfield), whatever the drop's state. Each
    one made is recorded on the card at once (any other key is left as it is). Returns ``{"pick_id", "cover_path",
    "preview_video_path"}``; ``KeyError`` for an unknown pick, ``DropError`` (one line) for a pick that is not a drop, has no
    section yet or whose clip is not in Storage, or when the watch copy could not be made; ``StorageError`` when the download
    fails."""
    pick = store.get_favorite(pick_id)
    if pick is None:
        raise KeyError(pick_id)
    d = drop_of(pick)
    window = d.get("window")
    if not isinstance(window, Mapping) or not all(isinstance(window.get(k), (int, float)) for k in ("start_s", "length_s")):
        raise DropError("no section yet: the check makes the cover and the watch copy")
    source_id = pick.source_id or d.get("source_id")
    src = next(iter(store.list_sources(id=source_id)), None) if isinstance(source_id, str) and source_id else None
    if src is None or not src.storage_path:
        raise DropError("the clip is not in Storage any more (deleted after posting, or by retention)")
    crop_x = d.get("crop_x") if isinstance(d.get("crop_x"), (int, float)) else None
    with tempfile.TemporaryDirectory(prefix="studio-previews-") as tmp:
        work = Path(tmp)
        local = _fetch_local(storage, src, work, "clip")
        paths, problems = _watch_files(storage, local, work, pick.id, window, crop_x)
    made = {k: v for k, v in paths.items() if v is not None}
    if made:
        fresh = store.get_favorite(pick.id) or pick  # read again: only these two keys change
        store.update_favorite(pick.id, proposal={**fresh.proposal, "drop": {**drop_of(fresh), **made}})
    if paths["preview_video_path"] is None:
        raise DropError("the watch copy could not be made: " + "; ".join(problems))
    return {"pick_id": pick.id, **paths}


def missing_previews(store: Store) -> list[str]:
    """``drop previews --missing``: the drops with a section and their clip in Storage but no watch copy (checked before Task 11),
    oldest first. A skipped pick is left out: it has no card, and retention never sweeps its files."""
    stored = {s.id for s in store.list_sources() if s.storage_path}
    out: list[str] = []
    for f in store.list_favorites():  # oldest first (both stores order by created_at)
        if not is_drop(f.proposal) or f.status == "skipped":
            continue
        d = f.proposal["drop"]
        if isinstance(d.get("window"), Mapping) and not d.get("preview_video_path") and (f.source_id or d.get("source_id")) in stored:
            out.append(f.id)
    return out


# ---- make --------------------------------------------------------------------------------------------------------------------


def _same_line(a: Any, b: Any) -> bool:
    """Two hooks are the same line, case and spaces aside."""
    return isinstance(a, str) and isinstance(b, str) and " ".join(a.split()).casefold() == " ".join(b.split()).casefold()


def _bandit(drop: Mapping[str, Any]) -> Mapping[str, Any] | None:
    """The hook the bandit drew at Make it (``drop['make']['bandit']``: ``learn.Choice.as_dict``), or None."""
    b = (drop.get("make") or {}).get("bandit")
    return b if isinstance(b, Mapping) and isinstance(b.get("hook"), str) and b["hook"].strip() else None


def bandit_hook(drop: Mapping[str, Any]) -> str | None:
    """The text of the hook the bandit drew, or None."""
    b = _bandit(drop)
    return b["hook"] if b else None


def owner_chose_hook(drop: Mapping[str, Any]) -> bool:
    """Did the owner's Adjust save a hook: any explicit choice, his own line or one of the check's three (the first included).
    The terminal sends ``hook`` only when he touched the hook in Adjust, so a hook that is there IS his choice, even when it is
    the line the check put first; one he never touched is not in the Adjust and the bandit may draw."""
    adjusted = (drop.get("adjust") or {}).get("hook")
    return isinstance(adjusted, str) and bool(adjusted.strip())


def _hook_tags(drop: Mapping[str, Any], look: Mapping[str, Any], hook: Any) -> dict[str, Any]:
    """Which hook went on screen (learning plan tag 3). ``hook_index`` 1-N = the check's hook of that place (3, or one per bandit arm) (case and spaces
    aside), with the pattern the check gave it (``"none"`` for a check made before the labels); 0 = none of them (the owner's own
    line): its pattern is ``"owner"``, never guessed from the nearest one. ``hook_by`` is ``owner`` when his Adjust saved a
    hook (any explicit choice, the check's first included: ``owner_chose_hook``), ``bandit`` when it is the hook the bandit drew at Make it
    (``drop['make']['bandit']``, test B: its own pattern and place), else ``studio``."""
    hooks = list(look.get("hooks") or drop.get("hooks") or [])
    labels = list(look.get("hook_patterns") or [])
    index = next((i for i, h in enumerate(hooks) if _same_line(h, hook)), None)
    if index is None:
        pattern = "owner"
    else:
        pattern = labels[index] if index < len(labels) and labels[index] in HOOK_PATTERNS else "none"
    if owner_chose_hook(drop):
        return {"hook_pattern": pattern, "hook_index": 0 if index is None else index + 1, "hook_by": "owner"}
    drawn = _bandit(drop)
    if drawn is not None and _same_line(hook, drawn["hook"]) and drawn.get("pattern") in HOOK_PATTERNS and _whole(drawn.get("index"), 0) is not None:
        return {"hook_pattern": drawn["pattern"], "hook_index": drawn["index"] + 1, "hook_by": "bandit"}
    return {"hook_pattern": pattern, "hook_index": 0 if index is None else index + 1, "hook_by": "studio"}


def _whole(value: Any, low: int) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= low else None


def learn_tags(
    pick: Favorite, drop: Mapping[str, Any], eff: Mapping[str, Any], *, version_index: int,
    test_arms: Mapping[str, Any] | None = None, explore_pick: bool = False,
) -> dict[str, Any]:
    """The learning tags of the clip a drop makes (docs/launch/measurement-and-learning-plan.md section 2; pure; every value
    from ``clips.LEARN_VALUES``), from the check (``drop``: its deconstruct, ``classic``, ``has_audio``, ``score``,
    ``hit_rules_version``, ``own_footage``), what is made (``eff``: the hook and his part) and the pick:

    - ``format_id``: ``own_footage`` for the owner's own footage, else ``swap_classic`` (a classic), ``swap_trend`` (a moment or
      trend name), ``swap_other``; ``source_kind``: ``own_footage``, ``auto_filed`` (a pick the hits job filed,
      ``drop.auto_filed``, plan Task 6), else ``owner_saved``.
    - the hook: ``_hook_tags``.
    - ``trend_stage``: ``classic`` for a classic, else the hits job's ``drop.trend_stage`` when it gave one, else ``none``;
      ``days_since_trend_peak`` likewise, and only with a rising, peak or fading stage (a classic never peaks); ``sound_rising``
      likewise (None and false until then).
    - ``sound_type``: the clip keeps its own sound (music ``original``): ``own_trend_sound`` with a moment name, ``own_other``
      without, ``none`` when the clip has no sound; ``ai_beat`` / ``in_app`` per the music.
    - the score (``drop.score``, terminal v3) as ``score_bucket`` and its three numbers (``none`` and None for a check made
      before the score); ``part`` = the part he really plays; ``family_id`` = the root pick (``drop.copy_of``), ``version_index``
      as given (``version_index``); ``series`` / ``episode`` from the pick's proposal when it names a series of the list.
    - ``caption_line1`` ``label-first`` (``caption_text``: the title, then the joke); ``first_comment_kind`` ``vote`` (the check
      writes a vote; its question variant is not used yet) or ``none``; ``hit_rules_version`` (``none`` for a check made before
      the version); ``test_arms`` and ``explore_pick`` as given (what the running tests assigned, ``experiments``; ``{}`` and
      false when none runs)."""
    look = drop.get("deconstruct") or {}
    classic = bool(drop.get("classic", look.get("classic")))
    moment = (look.get("moment_name") or "").strip()
    own = bool(drop.get("own_footage"))
    fmt = "own_footage" if own else "swap_classic" if classic else "swap_trend" if moment else "swap_other"
    source_kind = "own_footage" if own else "auto_filed" if drop.get("auto_filed") is True else "owner_saved"
    stage = drop.get("trend_stage")
    stage = "classic" if classic else stage if stage in ("rising", "peak", "fading") else "none"
    music = drop.get("music") or MUSIC
    if music == "original":
        sound = ("own_trend_sound" if moment else "own_other") if drop.get("has_audio", True) else "none"
    else:
        sound = music if music in ("ai_beat", "in_app") else "none"
    score = drop.get("score") if isinstance(drop.get("score"), Mapping) else {}
    total = _whole(score.get("total"), 0)
    series = pick.proposal.get("series")
    series = series if isinstance(series, str) and series in clips.LEARN_VALUES["series"] else "none"
    return {
        "format_id": fmt, **_hook_tags(drop, look, eff["hook"]),
        "caption_line1": "label-first", "first_comment_kind": "vote" if look.get("first_comment") else "none",
        "trend_stage": stage,
        "days_since_trend_peak": _whole(drop.get("days_since_trend_peak"), 0) if stage in ("rising", "peak", "fading") else None,
        "sound_type": sound, "sound_rising": drop.get("sound_rising") is True,
        "score_bucket": clips.score_bucket(total), "score_total": total,
        "score_potential": _whole(score.get("potential"), 0) if total is not None else None,
        "score_swap": _whole(score.get("swap"), 0) if total is not None else None,
        "part": eff["part"], "family_id": family_root_id(pick), "version_index": version_index,
        "series": series, "episode": _whole(pick.proposal.get("episode"), 1) if series != "none" else None,
        "hit_rules_version": drop.get("hit_rules_version") or "none", "source_kind": source_kind,
        "test_arms": dict(test_arms or {}), "explore_pick": explore_pick is True,
    }


def version_index(store: Store, pick: Favorite) -> int:
    """The pick's place in its family (learning plan tag 11): 1 = the root, 2-3 = its versions by creation order, skipped ones
    not counted (``family``). ``DropError`` for a version that is no member any more (it was skipped)."""
    root = family_root_id(pick)
    if root == pick.id:
        return 1
    versions = [m.id for m in family(store, pick) if m.id != root]
    if pick.id not in versions:
        raise DropError("this clip's version was skipped: drop it again")
    return versions.index(pick.id) + 2


def _features(
    pick: Favorite, drop: Mapping[str, Any], eff: Mapping[str, Any], kind: str, version_index: int,
    test_arms: Mapping[str, Any] | None = None, explore_pick: bool = False,
) -> dict[str, Any]:
    """The clip's feature tags: the required ones, the learning tags (``learn_tags``) and the drop's own (``presence`` is the
    old name of ``part``, kept)."""
    look = drop.get("deconstruct") or {}
    return {
        "hook_text": eff["hook"],
        "prop": ", ".join(eff["gadgets"]) or "none", "setting": look.get("setting") or "the clip's own",
        "motion_type": "object_swap", "audio_arm": "original_audio", "bodies_in_frame": int(look.get("people_count") or 1),
        "seamless_loop": False, "eye_closeup_end": False, "trend_name": look.get("moment_name") or "evergreen",
        "music": MUSIC, "fav_id": pick.id, "drop": True, "presence": eff["part"], "engagement_kind": kind,
        **learn_tags(pick, drop, eff, version_index=version_index, test_arms=test_arms, explore_pick=explore_pick),
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
    if not make_requested(pick):
        raise DropError(
            f"pick {pick_id}: no Make it from the owner or the studio (proposal.make_requested): nothing is generated without it"
        )
    if drop["state"] != "making":
        raise DropError(f"pick {pick_id} is {drop['state']}: a make runs on a drop the owner sent with Make it (making)")
    for key in ("source_id", "window", "star", "credits"):
        if not drop.get(key):
            raise DropError(f"pick {pick_id}: the check never finished ({key} missing): process it first")
    ref, _ = character(pick.character_slug, characters_dir)  # his kit may add a lead (Reginald's pause): the section shrinks by it
    try:
        effective(drop, lead_s=style_lead_s(ref.get("style")))
    except ValueError as e:
        return _give_up(store, pick, None, now, f"the Adjust is not valid: {e}")
    if not claim(store, pick_id, "make", job, now):
        return Outcome(pick_id, "making", "another run is making this video", detail={"busy": True})
    try:
        # read again under the lease: a parallel worker may have made this drop (or the owner taken Make it back) since it was
        # listed, and a stale listing must never pay Higgsfield twice
        fresh = _load(store, pick_id)
        if drop_of(fresh).get("state") != "making" or not make_requested(fresh):
            made = drop_of(fresh).get("state") != "making"  # else the owner took Make it back: nobody made anything
            text = "another run already made this video" if made else "this video is no longer waiting to be made"
            return Outcome(pick_id, drop_of(fresh).get("state"), text, detail={"busy": True})
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


def _score_of(pick: Favorite) -> int | None:
    score = drop_of(pick).get("score")
    return _whole(score.get("total"), 0) if isinstance(score, Mapping) else None


def checked_scores(store: Store, pick: Favorite) -> list[int]:
    """The scores test A's median is taken over: every scored drop of the pick's character whose check finished and that the owner
    has not skipped, whatever became of it since: ``ready`` ones, those sent to be made (``making``, with or without a clip yet:
    tapping Make on several at once puts them all in ``making`` before the first make runs, and each make starts a clip that
    leaves "waiting"), ``made`` ones and a failed make (``failed`` with its score kept; a failed check keeps none), and the clip
    itself. So the median does not move while a batch is being made: the clip the terminal offered as the Explore pick is judged
    against the same pool as the others. Each pick once."""
    pool: dict[str, int] = {}
    for f in store.list_favorites(character_slug=pick.character_slug):
        if f.status == "skipped" or not is_drop(f.proposal):
            continue
        d = f.proposal["drop"]
        if (d.get("state") in CHECKED_STATES or d.get("state") == "failed") and (total := _score_of(f)) is not None:
            pool[f.id] = total
    if (own := _score_of(pick)) is not None:
        pool[pick.id] = own
    return list(pool.values())


def has_beat_source(pick: Favorite, drop: Mapping[str, Any]) -> bool:
    """Does the master of this drop have a beat to follow (tests G and H: zoom pulses and the word pop go on the beat)? Yes for the
    clip's own sound (music ``original``, the default) or an ``ai_beat``; no for a silent ``in_app`` master (the drop's music, or
    the owner's choice on the Make-it sheet, ``proposal.owner_music``) and for a clip the check found to have no sound
    (``drop.has_audio`` false). A check that did not record ``has_audio`` is taken to have one: the master finds out for itself
    (it renders without the edit when it hears no beat, ``master.build_master``)."""
    if "in_app" in (drop.get("music"), pick.proposal.get("owner_music")):
        return False
    return drop.get("has_audio", True) is not False


def _tests_at_make(
    store: Store, pick: Favorite, now: datetime, registry: experiments.Registry,
) -> tuple[dict[str, Any], bool]:
    """(the block-coin arms for the pick's next clip, whether test A tags it ``explore_pick``): see ``studio.experiments``. A
    master with no beat to follow (``has_beat_source``) takes no position in tests G and H."""
    arms = experiments.assign_blocks(store, registry, pick.character_slug, now, beats=has_beat_source(pick, drop_of(pick)))
    explore = registry.is_active("A", now) and experiments.is_explore(_score_of(pick), checked_scores(store, pick))
    return arms, explore


# What a fault inside the hook bandit can raise (pure computation on the clips' tags): a database error is not among them, since it
# would leave the open transaction aborted, so it still stops the make.
_BANDIT_FAILURES = (ValueError, TypeError, KeyError, IndexError, ArithmeticError, StopIteration)


def _bandit_warning(pick: Favorite, error: Exception) -> None:
    log.warning(
        "drop %s: the hook bandit failed (%s: %s); the check's first hook stays (hook_by studio)",
        pick.id, type(error).__name__, str(error)[:140],
    )


def _new_or_current_clip(store: Store, pick: Favorite, now: datetime, swap_part: str | None = None) -> Clip:
    drop = drop_of(pick)
    clip_id = (drop.get("make") or {}).get("clip_id")
    if clip_id:
        clip = store.get_clip(clip_id)
        if clip is not None:
            return clip
    registry = experiments.load_experiments()  # a broken registry stops the make here, before anything is reserved or paid
    look = drop.get("deconstruct") or {}
    state = None
    if registry.is_active("B", now) and not owner_chose_hook(drop):
        try:
            state = learn.bandit_state(store, registry)
        except _BANDIT_FAILURES as e:  # the bandit only chooses among hooks already checked: a fault in it never blocks a make
            _bandit_warning(pick, e)
    with store.transaction():
        store.get_settings()  # the settings row lock: two makes of one character never read the same place in a test's block
        arms, explore = _tests_at_make(store, pick, now, registry)
        choice = None
        if state is not None:  # the hook bandit (test B): the owner's own hook is never drawn over
            try:
                choice = learn.choose_hook(
                    store, registry, pick.character_slug, pick.id, list(look.get("hooks") or drop.get("hooks") or []),
                    list(look.get("hook_patterns") or []), moment=bool((look.get("moment_name") or "").strip()), now=now,
                    state=state,
                )
            except _BANDIT_FAILURES as e:  # the check's first hook stays (hook_by studio)
                _bandit_warning(pick, e)
        extra: dict[str, Any] = {}
        if choice is not None:
            extra = {"bandit": choice.as_dict()}
            drop = {**drop, "make": {**(drop.get("make") or {}), **extra}}
            arms = {**arms, "hook": choice.pattern}
        eff = effective(drop, swap_part=swap_part)
        kind = next_engagement(store, pick.character_slug)
        features = _features(pick, drop, eff, kind, version_index(store, pick), test_arms=arms, explore_pick=explore)
        clip = clips.new_clip(store, pick.character_slug, None, Mode.dropin, features)
        pick = _record_make(store, pick, now, clip_id=clip.id, attempt=0, **extra)
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
    clip = _new_or_current_clip(store, pick, now, ref.get("swap_part"))
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
    drop = drop_of(pick)
    eff = effective(drop)
    child = sources.trim_source(
        store, storage, drop["source_id"], eff["start_s"], eff["length_s"], crop_x=eff["crop_x"],
        min_pixels=clipwork.OBJECT_SWAP_MIN_PIXELS,
    )
    if "avoid" in drop:  # the section is judged, not the clip: the cut carries its own text and watermark flags
        seen = {x["what"] for x in drop["avoid"] if overlaps(eff["start_s"], eff["length_s"], x)}
        child = sources.record_checks(
            store, child.id, has_watermark="watermark" in seen, has_overlay="text" in seen,
            other_people=child.other_people or 0, has_minors=bool(child.has_minors),
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
        eff = effective(drop_of(pick), swap_part=ref.get("swap_part"))
        body = {
            "video_url": sources.signed_source_url(store, storage, child.id, SIGNED_URL_S),
            "image_urls": seed.reference_images(ref, eff["body"] or ref["bodies"][0]),
            "prompt": swap_prompt(
                eff["star"] or "the main performer", who.noun, eff["part"], eff["gadgets"], ref.get("swap_performance"),
            ),
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
    eff = effective(drop_of(pick), swap_part=ref.get("swap_part"))
    inputs = {
        "clip_id": clip.id, "source_id": child.id, "seconds": child.duration_s,
        "video_url": sources.signed_source_url(store, storage, child.id, SIGNED_URL_S),
        "image_urls": seed.reference_images(ref, eff["body"] or ref["bodies"][0]),
        "prompt": swap_prompt(
            eff["star"] or "the main performer", who.noun, eff["part"], eff["gadgets"], ref.get("swap_performance"),
        ),
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
        character=pick.character_slug, style=ref.get("style"),  # his kit: pill, entrance, hook edit, tone (refs.json is the authority)
        edits=edits_from_arms(clip.features.get("test_arms")),  # tests G and H: the clip's two coins, None when it carries neither
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
    # the hook on screen is the one tagged: a make resumed after a failed master renders the owner's latest Adjust, which may
    # not be the hook the clip was created with (a clip made before the learning tags keeps its old pattern tags)
    retag = {"hook_text": hook, **(_hook_tags(drop, look, hook) if "hook_index" in clip.features else {})}
    clips.set_hook_tags(store, clip.id, retag)
    if spec.edits is not None and spec.applied:  # tests G, H: what the master really shows (a remake says what it did this time)
        clips.set_edit_tags(store, clip.id, spec.applied)
    upload_master(store, storage, clip.id, out)
    kind = clip.features.get("engagement_kind") if clip.features.get("engagement_kind") in ENGAGEMENT_ORDER else ENGAGEMENT_ORDER[0]
    caption = caption_text(pick, look, kind) if look.get("caption") else hook
    # The character's series tag (refs.json ``style.series_tag``) joins the deconstruct's 3-4 tags HERE, when the clip is made, so
    # the post text the owner previews is the one that is posted (the publisher adds nothing); never a sixth tag.
    hashtags = with_series_tag(caption, list(look.get("hashtags") or ["#oddeyes"]), (ref.get("style") or {}).get("series_tag"))
    compose_content(caption, hashtags)  # the 2,200 limit, 5 tags, no refused tag: before anything is written
    clips.transition(store, clip.id, S.mastered, hook=hook, caption=caption, hashtags=hashtags)
    if look.get("first_comment"):
        clips.set_first_comment(store, clip.id, look["first_comment"])
    return None


# ---- what is pending (the sweep) ------------------------------------------------------------------------------------------


def _fetch_age(pick: Favorite, now: datetime) -> tuple[int, str | None]:
    """An auto-filed drop's London days since it was filed, and the London day of its last failed fetch (``drop.fetch_days``)."""
    filed = fetch.filed_at(pick) or now
    days = (now.astimezone(LONDON).date() - filed.astimezone(LONDON).date()).days
    tried = [x for x in drop_of(pick).get("fetch_days") or [] if isinstance(x, str)]
    return days, max(tried) if tried else None


# ---- a failed check that retries itself (task 12) -----------------------------------------------------------------------------


def transient_kind(reason: str) -> str | None:
    """Why a failed check failed, when the cause is temporary: ``"quota"`` (Gemini's daily quota: HTTP 429 "You exceeded your
    current quota"), ``"timeout"`` (a timed-out call, or every model timed out) or ``"busy"`` (HTTP 5xx, any other 429 such as a
    per-minute rate limit, "busy", "high demand", "overloaded", or the network dropping: ``ConnectError``, ``ReadError``,
    ``WriteError``, ``RemoteProtocolError``, "connection", "network"); ``None`` for anything else (a refused key, a clip Gemini would not look at, an error of ours). The
    reason is the one the drop recorded ("the look at the clip failed (...): tap Try again"). Pure: it reads the text only.
    A 429 that names a per-minute limit is busy even with the quota wording (the day's quota is not gone: a retry in two hours
    works). ``studio.gemini`` tells the two apart when it raises (``GeminiQuota``) and ``check_failed_reason`` writes the tag
    (``[quota:day]``, ``[quota:minute]``) into the reason, which this reads first; a reason from before that (the raw text, cut
    at 140 characters before the quota id) falls back to its wording, where the plain quota wording stays the daily quota."""
    if not isinstance(reason, str):
        return None
    if QUOTA_DAY in reason:  # a 429 the client told apart at raise time (studio.gemini.GeminiQuota): its tag is the answer
        return "quota"
    if QUOTA_MINUTE in reason:
        return "busy"
    low = reason.lower()
    if "exceeded your current quota" in low and not re.search(r"per[ _-]?minute", low):  # an older reason, cut before the quota id
        return "quota"
    if re.search(r"http (429|5\d\d)\b", low):  # an answer with a status comes first: a 504 "gateway timeout" is Gemini's, busy
        return "busy"
    if "timeout" in low or "timed out" in low:
        return "timeout"
    if any(w in low for w in ("busy", "high demand", "overloaded", "connecterror", "readerror", "writeerror", "remoteprotocolerror", "connection", "network")):
        return "busy"
    return None


def check_failed_reason(error: gemini.GeminiError, d: Mapping[str, Any]) -> tuple[str, bool]:
    """``(the reason, whether the sweep takes this failed check again by itself)`` for a check that Gemini failed. Every error
    reads ``the look at the clip failed (<its text>): tap Try again``, except an HTTP 429 that ``studio.gemini`` told apart: that
    one is said in plain words with its tag (``transient_kind`` reads the tag) and, while the automatic retries are not used up
    (``auto_retries_used`` of the drop ``d``: ``AUTO_RETRY_QUOTA_MAX`` for the day's quota, ``AUTO_RETRY_MAX`` for a per-minute
    limit), that the sweep tries again by itself; after them, that it is the owner's Try again."""
    if not isinstance(error, gemini.GeminiQuota):
        return f"{CHECK_FAILED} ({str(error)[:140]}): tap Try again", False
    day = error.window == "day"
    what = f"Gemini's daily free quota is used up {QUOTA_DAY}" if day else f"Gemini's per-minute limit {QUOTA_MINUTE}"
    if auto_retries_used(d) >= (AUTO_RETRY_QUOTA_MAX if day else AUTO_RETRY_MAX):
        return f"{CHECK_FAILED} ({what}): its automatic retries are used up: tap Try again", False
    when = f"after {QUOTA_RESET_HOUR:02d}:00 London" if day else "on the next sweep"
    return f"{CHECK_FAILED} ({what}): it tries again {when} by itself", True


def last_quota_reset(now: datetime) -> datetime:
    """The most recent ``QUOTA_RESET_HOUR`` London at or before ``now``: a quota failure from before it is a new day's quota."""
    local = now.astimezone(LONDON)
    day: date = local.date() if local.time() >= time(QUOTA_RESET_HOUR) else local.date() - timedelta(days=1)
    return datetime.combine(day, time(QUOTA_RESET_HOUR), tzinfo=LONDON)


def failure_stamp(d: Mapping[str, Any]) -> tuple[str, str]:
    """When this failed drop failed (``drop.at``) and when the sweep last retook it (``drop.auto_retry_at``), as text ("" for
    none). A retake that fails again moves both, so a drop whose stamp differs from the one listed has been retaken since."""
    return str(d.get("at") or ""), str(d.get("auto_retry_at") or "")


def same_failure(listed: Mapping[str, str], d: Mapping[str, Any]) -> bool:
    """Whether the drop ``d`` (read now) is still the failure the sweep listed (``pending``'s ``failed_at`` / ``retried_at``)."""
    return (listed.get("failed_at", ""), listed.get("retried_at", "")) == failure_stamp(d)


def auto_retries_used(d: Mapping[str, Any]) -> int:
    """How many times the sweep has retaken this drop's failed check by itself (``drop.auto_retries``); the owner's Try again
    resets it: a ``requested.process`` stamped after ``drop.auto_retry_at`` (``request_job`` and ``request_check`` write it; the
    sweep's own retry never does) starts the count over."""
    n = d.get("auto_retries")
    used = n if isinstance(n, int) and not isinstance(n, bool) and n > 0 else 0
    requested = d.get("requested")
    asked = _moment(requested.get("process")) if isinstance(requested, Mapping) else None
    last = _moment(d.get("auto_retry_at"))
    return 0 if asked is not None and last is not None and asked > last else used


def auto_retry_kind(pick: Favorite, now: datetime) -> str | None:
    """Whether the sweep takes this drop's failed CHECK again by itself, and for what cause (``transient_kind``), else ``None``:

    * only a drop ``failed`` with a check's reason (``CHECK_FAILED``): a make is never retried by itself (it costs credits);
    * a timeout / 5xx / busy failure: at most ``AUTO_RETRY_MAX`` times (``auto_retries_used``);
    * a daily-quota failure: once the quota has reset, i.e. the failure (``drop.at``) is before the latest 08:00 London
      (``last_quota_reset``), so once a London day at most, and at most ``AUTO_RETRY_QUOTA_MAX`` times in all (the same
      ``auto_retries`` count: a quota that never comes back is the owner's to look at, not a daily storm of retries)."""
    d = drop_of(pick)
    reason = d.get("reason")
    if d.get("state") != "failed" or pick.status not in ("approved", "queued") or not isinstance(reason, str):
        return None
    if not reason.startswith(CHECK_FAILED):
        return None
    kind = transient_kind(reason)
    if kind == "quota":
        failed = _moment(d.get("at"))
        return kind if failed is not None and failed < last_quota_reset(now) and auto_retries_used(d) < AUTO_RETRY_QUOTA_MAX else None
    return kind if kind is not None and auto_retries_used(d) < AUTO_RETRY_MAX else None


def needs_fetch(store: Store, pick: Favorite) -> bool:
    """Does checking this drop still download its clip? Yes for a pasted or auto-filed link whose clip is not in storage yet (what
    ``_get_source`` would fetch with yt-dlp, else ScrapeCreators' copy of that one post); no for the owner's upload (a file drop, or
    a clip attached to the pick) and for a drop whose source is already stored. It over-reads a link another pick already fetched
    (``fetch.fetch_pick_clip`` would share that copy): harmless, only the first worker then takes it."""
    if pick.proposal.get("owner_clip_path") or pick.platform == DROP_PLATFORM:
        return False
    if pick.source_id:
        found = next(iter(store.list_sources(id=pick.source_id)), None)
        if found is not None and found.storage_path:
            return False
    return True


def takes_downloads() -> bool:
    """May this run take a drop that needs a download? Of the sweep's three parallel workers (``STUDIO_WORKER``, the matrix value of
    ``studio-drop.yml``) only the first: CLAUDE.md has the cloud fetch a clip ONE at a time, and three workers listing the same rows
    would start up to three downloads at once. A run with no worker number (the Mac, a hand run) is alone, so it may."""
    return (os.environ.get("STUDIO_WORKER") or "").strip() in ("", "1")


def pending(
    store: Store, *, include_waiting: bool = False, now: datetime | None = None, auto_retry: bool = False, fetches: bool = True,
) -> list[dict[str, str]]:
    """The drops a run should take, oldest first: ``checking`` (and an ``uploading`` one whose file is attached) -> process,
    ``making`` with a Make it (the owner's, or the studio's auto-make) -> make; ``waiting`` links only with ``include_waiting`` (the Mac: the cloud could not
    fetch them). A pick another run holds (a live lease) is left out.

    An auto-filed drop (``drop.auto_filed``, the hits job's) is never the Mac's: with ``include_waiting`` it is left out of the
    checks (its make, after the owner's Make it, stays). For the cloud (no ``include_waiting``) a WAITING one is ``expire`` from
    its ``AUTO_FETCH_DAYS``th London day after filing on (``expire_unfetched``), and before that ``process`` again when
    ``auto_retry`` (the sweep: the day's one-post downloads allow) and its last failed fetch was on an earlier London day.

    For the cloud (no ``include_waiting``) a drop ``failed`` in its CHECK for a temporary cause is ``process`` again
    (``auto_retry_kind``: a Gemini timeout, 5xx or busy answer up to ``AUTO_RETRY_MAX`` times; the daily quota once it has reset);
    ``process_drop(auto_retry=True)`` moves it back to ``checking`` when the run claims it. A failed make is never listed. Its row
    also carries ``failed_at`` and ``retried_at`` (``failure_stamp``), so a worker can tell the failure it listed from a later one.
    ``fetches=False`` (a sweep worker other than the first, ``takes_downloads``) leaves out the checks that still need their clip
    downloaded (``needs_fetch``); expiring and making never download."""
    now = now or now_london()
    today = now.astimezone(LONDON).date().isoformat()
    out: list[tuple[datetime | None, dict[str, str]]] = []
    for f in store.list_favorites():
        if not is_drop(f.proposal) or f.status not in ("approved", "queued"):
            continue
        d = f.proposal["drop"]
        held = d.get("job")
        if isinstance(held, Mapping) and (since := _moment(held.get("at"))) is not None and now - since < timedelta(minutes=LEASE_MINUTES):
            continue
        state = d.get("state")
        auto = d.get("auto_filed") is True
        if state == "waiting" and auto:
            if include_waiting or f.status != "approved":
                continue
            age, last = _fetch_age(f, now)
            if age >= AUTO_FETCH_DAYS:
                out.append((f.created_at, {"pick_id": f.id, "job": "expire", "state": state}))
            elif auto_retry and (last is None or last < today):
                out.append((f.created_at, {"pick_id": f.id, "job": "process", "state": state}))
            continue
        if state == "failed":
            if not include_waiting and auto_retry_kind(f, now) is not None:
                failed_at, retried_at = failure_stamp(d)  # the failure as listed: a worker that retakes it later compares
                out.append((f.created_at, {
                    "pick_id": f.id, "job": "process", "state": state, "failed_at": failed_at, "retried_at": retried_at,
                }))  # fmt: skip
            continue
        if auto and include_waiting and state != "making":
            continue  # the cloud checks it; the Mac never fetches an auto-filed link
        if state == "checking" or (state == "uploading" and f.proposal.get("owner_clip_path")) or (state == "waiting" and include_waiting):
            out.append((f.created_at, {"pick_id": f.id, "job": "process", "state": state}))
        elif state == "making" and make_requested(f):
            out.append((f.created_at, {"pick_id": f.id, "job": "make", "state": state}))
    if not fetches:
        out = [(at, row) for at, row in out if row["job"] != "process" or not needs_fetch(store, store.get_favorite(row["pick_id"]))]
    out.sort(key=lambda p: p[0].timestamp() if p[0] else 0.0)
    return [p for _, p in out]


def expire_unfetched(store: Store, pick_id: str, now: datetime | None = None) -> dict[str, Any]:
    """Skip an auto-filed drop the cloud could not fetch on its first ``AUTO_FETCH_DAYS`` London days (``pending`` lists it as
    ``expire``): the pick is ``skipped`` with ``UNFETCHED_REASON`` and its hit becomes ``dismissed`` (it is not offered again).
    ``DropError`` for any other drop (not auto-filed, not waiting, not that old)."""
    now = now or now_london()
    pick = _load(store, pick_id)
    d = drop_of(pick)
    if d.get("auto_filed") is not True or d.get("state") != "waiting" or pick.status != "approved":
        raise DropError(f"pick {pick.id} is not an auto-filed link waiting for its fetch")
    age, _ = _fetch_age(pick, now)
    if age < AUTO_FETCH_DAYS:
        raise DropError(f"pick {pick.id} was filed {age} London days ago: it is tried for {AUTO_FETCH_DAYS}")
    mark_favorite(store, pick.id, "skipped", proposal={
        **pick.proposal, "drop": {**d, "reason": UNFETCHED_REASON, "at": now.isoformat()},
    })  # fmt: skip
    hit = d.get("hit") if isinstance(d.get("hit"), Mapping) else {}
    hit_id = hit.get("id") if isinstance(hit.get("id"), str) else None
    if hit_id is not None and store.get_hit(hit_id) is not None:
        store.update_hit(hit_id, status="dismissed")
    return {"pick_id": pick.id, "state": "waiting", "reason": UNFETCHED_REASON, "ok": True, "hit_id": hit_id, "skipped": True}


def _auto_retry(media: Any) -> bool:
    """Whether the cloud tries a waiting auto-filed link again now: with the ScrapeCreators key, while the day's one-post
    downloads allow (yt-dlp first, then the copy); without it, with yt-dlp alone (free)."""
    return media is None or media.refusal() is None


# ---- auto-make: the studio asks for the clip of every coming slot ---------------------------------------------------------------------

AUTO_MAKE_DEFAULTS = {"enabled": True, "horizon_hours": 30}  # config/scan.json ``auto_make``
AUTO_MAKE_MAX_HORIZON_H = 168  # a week: further ahead than that, a slot is not "coming"
STUDIO_FAILED_HOLD_H = 24  # a make the studio asked for that failed holds its character this long: the owner looks first
WATCHED_CLIP_STATES = (  # a clip in one of these may cover a slot (``_covering_clip``); planned, rejected and dropped never do
    S.generating, S.gen_failed, S.generated, S.qa_failed, S.qa_passed, S.mastered, S.awaiting_approval, S.approved, S.scheduled, S.posted,
)


def _scan() -> dict[str, Any]:
    """``config/scan.json`` (the file ``studio.hits`` reads; imported here, not at the top: ``studio.hits`` imports this module)."""
    from studio import hits

    return hits.load_scan()


def auto_make_config(scan: Mapping[str, Any]) -> dict[str, Any]:
    """``config/scan.json`` ``auto_make`` with its defaults (``AUTO_MAKE_DEFAULTS``): ``enabled`` (true or false) and
    ``horizon_hours`` (a whole number of 1 to 168: how far ahead of a slot the clip is asked for). ``ValueError`` names the key."""
    raw = scan.get("auto_make") if isinstance(scan.get("auto_make"), Mapping) else {}
    enabled = raw.get("enabled", AUTO_MAKE_DEFAULTS["enabled"])
    if not isinstance(enabled, bool):
        raise ValueError(f"config/scan.json auto_make.enabled must be true or false, got {enabled!r}")
    horizon = raw.get("horizon_hours", AUTO_MAKE_DEFAULTS["horizon_hours"])
    if isinstance(horizon, bool) or not isinstance(horizon, int) or not 1 <= horizon <= AUTO_MAKE_MAX_HORIZON_H:
        raise ValueError(
            f"config/scan.json auto_make.horizon_hours must be a whole number of 1 to {AUTO_MAKE_MAX_HORIZON_H}, got {horizon!r}"
        )
    return {"enabled": enabled, "horizon_hours": horizon}


@dataclass(frozen=True)
class Balance:
    """What Higgsfield says is left (``credits``), or why it could not be read (``problem``): never both, never a guess."""

    credits: int | None
    problem: str | None = None


def read_balance(hf: Any) -> Balance:
    """Higgsfield's free balance read (``HiggsfieldClient.balance``). Whatever goes wrong (no key, a refusal, another shape, no
    answer) is a ``problem``, not an error: auto-make then waits and says why."""
    if hf is None:
        return Balance(None, "no Higgsfield key in this run (HF_KEY): its balance is unknown")
    try:
        credits = hf.balance()
    except Exception as e:  # noqa: BLE001 - a read that fails for any reason leaves the balance unknown, which waits
        return Balance(None, f"Higgsfield's balance could not be read ({type(e).__name__}: {' '.join(str(e).split())[:140]})")
    if isinstance(credits, bool) or not isinstance(credits, int) or credits < 0:
        return Balance(None, f"Higgsfield's balance could not be read (it answered {credits!r})")
    return Balance(credits)


def explore_turn(store: Store, slug: str, now: datetime, registry: experiments.Registry | None = None) -> bool:
    """Is the next clip of this character test A's Explore pick: one in every ``explore.every`` (4), like the terminal's suggestions
    (``terminal/src/lib/ranking.ts``: the best 3, then one from below the median). Counted over his clips made since the test
    began (``registry.start``, London): those that carry the ``explore_pick`` tag (made from a drop; a Recreate has none), a
    given-up clip (``dropped``) left out. It is his turn when ``every - 1`` of them in a row, newest last, were not Explore picks,
    so a turn that could not be served (nothing below the median yet) stays his until it can. False while test A is off."""
    registry = registry or experiments.load_experiments()
    if not registry.is_active("A", now):
        return False
    every = registry.test("A").params["explore"]["every"]
    began = datetime.combine(registry.start, time(0, 0), tzinfo=LONDON)
    mine = sorted(
        (c for c in store.list_clips(character_slug=slug)
         if c.state is not S.dropped and c.created_at is not None and c.created_at >= began and isinstance(c.features.get("explore_pick"), bool)),
        key=lambda c: (c.created_at, c.id),
    )  # fmt: skip
    since = 0
    for c in reversed(mine):
        if c.features["explore_pick"]:
            break
        since += 1
    return since >= every - 1


def _is_ready_choice(f: Favorite, now: datetime) -> bool:
    """A drop auto-make may ask for: ready, checked (a source, a window, a star) and priced, not skipped, nobody has asked for it
    and no run holds it (a live lease)."""
    d = f.proposal.get("drop")
    if not isinstance(d, Mapping) or f.status != "approved" or d.get("state") != "ready" or f.proposal.get("make_requested") is not None:
        return False
    credits = d.get("credits")
    if isinstance(credits, bool) or not isinstance(credits, int) or credits <= 0:
        return False
    if not all(d.get(key) for key in ("source_id", "window", "star")):
        return False
    held = d.get("job")
    return not (isinstance(held, Mapping) and (since := _moment(held.get("at"))) is not None and now - since < timedelta(minutes=LEASE_MINUTES))


def _ranked(picks: list[Favorite]) -> list[Favorite]:
    """Best first: the highest ``drop.score.total``; a tie goes to the pick filed first; a drop without a score ranks last (oldest
    first among those)."""
    def key(f: Favorite) -> tuple[bool, int, float, str]:
        score = _score_of(f)
        return (score is None, -(score or 0), f.created_at.timestamp() if f.created_at else 0.0, f.id)

    return sorted(picks, key=key)


def choose_ready_drop(
    store: Store, picks: list[Favorite], slug: str, now: datetime, registry: experiments.Registry,
) -> tuple[Favorite, bool]:
    """``(the drop to ask for, whether it is an Explore pick)`` among a character's ready drops (at least one): the best-ranked
    (``_ranked``), except on his Explore turn (``explore_turn``), when it is the best drop below the median score of his checked
    drops (``experiments.is_explore`` over ``checked_scores``: the same pool the clip's ``explore_pick`` tag will be judged by at
    Make it). With nothing below the median the best drop is taken and the turn stays his. The flag says what the tag will say."""
    ranked = _ranked(picks)
    pool = checked_scores(store, ranked[0])
    if explore_turn(store, slug, now, registry):
        below = [f for f in ranked if experiments.is_explore(_score_of(f), pool)]
        if below:
            return below[0], True
    best = ranked[0]
    return best, registry.is_active("A", now) and experiments.is_explore(_score_of(best), pool)


def _post_days(store: Store, clip: Clip) -> set[date]:
    """The London days on which the clip has a post that holds a day (``planning.TAKEN_STATUSES``; a failed post never held one),
    dated like ``planning.taken_days``: when it really went out, else when it is scheduled."""
    return {
        (p.claimed_at or p.scheduled_for).astimezone(LONDON).date()
        for p in store.list_posts(clip_id=clip.id) if p.status in TAKEN_STATUSES
    }


def _covering_clip(store: Store, slug: str, slot: datetime) -> Clip | None:
    """A clip of his that already stands for the slot: in the pipeline from generating to scheduled (``WATCHED_CLIP_STATES``) and
    either with no post that holds a day yet (it takes the next free slot once it is approved) or with one on the slot's London
    day; a posted clip only by the second (a post earlier in the day). Planned, rejected and dropped clips cover nothing."""
    day = slot.astimezone(LONDON).date()
    for c in store.list_clips(character_slug=slug):
        if c.state not in WATCHED_CLIP_STATES:
            continue
        days = _post_days(store, c)
        if day in days or (not days and c.state is not S.posted):
            return c
    return None


def _studio_failure(picks: list[Favorite], now: datetime) -> Favorite | None:
    """A make the studio asked for that failed within ``STUDIO_FAILED_HOLD_H`` hours: the owner looks at it before the studio
    spends on another drop of his (a failure that repeats must not eat the drops one sweep after another). An owner's failed make
    never holds anyone: it is his to retry."""
    for f in picks:
        d = f.proposal["drop"]
        failed_at = _moment(d.get("at"))
        if (d.get("state") == "failed" and make_requested_by(f) == "studio" and failed_at is not None
                and now - failed_at < timedelta(hours=STUDIO_FAILED_HOLD_H)):  # fmt: skip
            return f
    return None


@dataclass
class _Want:
    """One request the plan makes."""

    character: str
    pick_id: str
    slot: datetime
    credits: int
    explore: bool

    def json(self) -> dict[str, Any]:
        return {"character": self.character, "pick_id": self.pick_id, "slot": self.slot.isoformat(), "credits": self.credits, "explore": self.explore}


def _london_words(at: datetime) -> str:
    return at.astimezone(LONDON).strftime("%a %d %b %H:%M")


def plan_auto_make(
    store: Store, now: datetime, cfg: Mapping[str, Any], registry: experiments.Registry, balance: Balance,
) -> tuple[list[_Want], list[dict[str, str]], str | None]:
    """``(what to ask for, who is left alone and why, the credits reason if any character waits for them)``. Writes nothing.

    Every live character (``status`` live) in the order of his next slot: no connected account, no slot, a slot further than the
    horizon, something already covering it (a pick with a make requested, ``_covering_clip``), a studio make that failed lately
    (``_studio_failure``) or no ready drop leaves him alone, each with its own line. Otherwise his drop is chosen
    (``choose_ready_drop``) and priced at the check's price; it must fit the monthly cap
    and Higgsfield's balance, counting what is already spoken for: the ledger (settled and reserved), the makes asked for that have not reserved yet
    (``making`` without ``make.reserved``) and, in the slot order, what this plan asks for before him. A character that does not
    fit waits, and the first such reason is the plan's ``waiting``."""
    settings = store.get_settings()
    picks = [f for f in store.list_favorites() if is_drop(f.proposal) and f.status != "skipped"]
    promised = 0
    for f in picks:
        d = f.proposal["drop"]
        if d.get("state") == "making" and make_requested(f) and not (d.get("make") or {}).get("reserved"):
            credits = d.get("credits")
            promised += credits if isinstance(credits, int) and not isinstance(credits, bool) else 0
    held = budget.committed(store, budget.month_key(now)) + promised
    cap = settings.monthly_cap_credits
    horizon = timedelta(hours=cfg["horizon_hours"])
    wants: list[_Want] = []
    skipped: list[dict[str, str]] = []
    waiting: str | None = None
    slotted: list[tuple[datetime, str]] = []
    for c in sorted((c for c in store.characters() if c.status == "live"), key=lambda c: c.slug):
        if not any(a.postiz_integration_id for a in store.accounts(c.slug)):
            skipped.append({"character": c.slug, "reason": "no connected account to post to"})
            continue
        try:
            slot = upcoming_slot(c.slug, now, settings.cadence)
        except ValueError as e:
            skipped.append({"character": c.slug, "reason": f"no posting slot: {e}"})
            continue
        if slot - now > horizon:
            skipped.append({"character": c.slug, "reason": f"his next slot, {_london_words(slot)}, is more than {cfg['horizon_hours']} h away"})
            continue
        slotted.append((slot, c.slug))
    spent = 0  # what this plan has already asked for (it counts against the cap and the balance for the next character)
    for slot, slug in sorted(slotted):
        mine = [f for f in picks if f.character_slug == slug]
        asked = next((f for f in mine if make_requested(f) and f.proposal["drop"].get("state") in ("making", "ready")), None)
        if asked is not None:
            skipped.append({"character": slug, "reason": f"a make is already requested for pick {asked.id}"})
            continue
        on_its_way = _covering_clip(store, slug, slot)
        if on_its_way is not None:
            skipped.append({"character": slug, "reason": f"a clip is already on its way ({on_its_way.state.value}, {on_its_way.id}) for {_london_words(slot)}"})
            continue
        failed = _studio_failure(mine, now)
        if failed is not None:
            skipped.append({"character": slug, "reason": f"the studio's make of pick {failed.id} failed lately: waiting for the owner to look at it"})
            continue
        choices = [f for f in mine if _is_ready_choice(f, now)]
        if not choices:
            skipped.append({"character": slug, "reason": "no ready drop to make (checked, priced, not skipped, nobody has asked for it)"})
            continue
        pick, explore = choose_ready_drop(store, choices, slug, now, registry)
        price = pick.proposal["drop"]["credits"]
        reason = None
        if held + spent + price > cap:
            reason = f"the monthly cap would be passed ({held + spent} + {price} > {cap})"
        elif balance.credits is None:
            reason = balance.problem
        elif balance.credits - promised - spent < price:
            reason = f"Higgsfield has {balance.credits} credits ({promised + spent} already spoken for), a clip costs {price}"
        if reason is not None:
            skipped.append({"character": slug, "reason": reason})
            waiting = waiting or f"waiting for credits: {reason}"
            continue
        spent += price
        wants.append(_Want(slug, pick.id, slot, price, explore))
    return wants, skipped, waiting


def request_make(store: Store, pick_id: str, now: datetime, *, slot: datetime, explore: bool) -> Favorite:
    """Ask for the make of a ready drop as the studio: what ``studio.request_job(pick, 'make')`` (migration 0012) writes for the
    owner, with no Adjust (the check's own choices) and the studio's name on it: the drop goes ``making`` (``requested.make``
    stamped, the reason cleared) and ``proposal['make_requested']`` is ``{"at", "by": "studio", "slot", "explore"}`` (the slot it
    is for and whether it is test A's Explore pick, for the record). Nothing is dispatched: the sweep that asked takes it up next.
    ``KeyError`` for an unknown pick; ``DropError`` for a drop that is not ``ready`` any more or already has a make requested (the
    owner may have tapped Make it a moment ago: his request stands)."""
    pick = store.get_favorite(pick_id)
    if pick is None:
        raise KeyError(pick_id)
    d = drop_of(pick)
    if d.get("state") != "ready":
        raise DropError(f"pick {pick_id} is {d.get('state')}: only a ready drop is asked for")
    if pick.proposal.get("make_requested") is not None:
        raise DropError(f"pick {pick_id}: a make is already requested")
    d.pop("adjust", None)
    d.update(state="making", reason=None, at=now.isoformat(), requested={**(d.get("requested") or {}), "make": now.isoformat()})
    record = {"at": now.isoformat(), "by": "studio", "slot": slot.isoformat(), "explore": explore}
    return mark_favorite(store, pick_id, pick.status, proposal={**pick.proposal, "drop": d, "make_requested": record})


def auto_make(
    store: Store, now: datetime | None = None, *, hf: Any, dry_run: bool = False, scan: Mapping[str, Any] | None = None,
    registry: experiments.Registry | None = None,
) -> dict[str, Any]:
    """The studio makes them (owner decision 2026-10-14: once Higgsfield has credits the cloud makes clips by itself): for every
    live character with a posting slot coming up and nothing in the pipeline for it, ask for the make of one of his ready drops
    (``plan_auto_make``, ``request_make``). Returns ``{"requested": [{character, pick_id, slot, credits, explore}], "skipped":
    [{character, reason}], "waiting": reason | None}`` (plus ``dry_run`` true for a dry run, which writes nothing, and ``enabled``
    false when ``config/scan.json`` ``auto_make.enabled`` switches it off).

    The kill switch, the monthly cap and Higgsfield's balance ask for nothing and set ``waiting``: a normal state until the owner
    tops up, never an error. The balance is read first and outside the lock (``read_balance``; a read that fails leaves it unknown,
    which waits, never guesses), then the plan is drawn and written under the settings row lock (the one ``budget.reserve`` takes),
    so two runs never ask for two drops of one character. It is idempotent: a second run finds the asked-for make covering the slot.
    ``ValueError`` for a naive ``now``, a broken ``auto_make`` config or a broken test registry (the caller fixes those)."""
    now = require_aware(now or now_london(), "auto_make(now)")
    cfg = auto_make_config(scan if scan is not None else _scan())
    out: dict[str, Any] = {"requested": [], "skipped": [], "waiting": None}
    if not cfg["enabled"]:
        return {**out, "enabled": False}
    registry = registry or experiments.load_experiments()
    if store.get_settings().kill_switch:
        return {**out, "waiting": "waiting: the kill switch is on, nothing is made"}
    balance = read_balance(hf)
    if dry_run:
        wants, skipped, waiting = plan_auto_make(store, now, cfg, registry, balance)
        asked = wants
    else:
        with store.transaction():
            store.get_settings()  # the settings row lock: two runs (or a run and a Make it's reserve) never plan on the same numbers
            wants, skipped, waiting = plan_auto_make(store, now, cfg, registry, balance)
            asked = []
            for want in wants:
                try:
                    request_make(store, want.pick_id, now, slot=want.slot, explore=want.explore)
                except DropError as e:  # the owner tapped Make it on it a moment ago: his request stands
                    skipped.append({"character": want.character, "reason": str(e)})
                else:
                    asked.append(want)
    return {**out, "requested": [w.json() for w in asked], "skipped": skipped, "waiting": waiting, **({"dry_run": True} if dry_run else {})}


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
    if outcome.red:
        raise typer.Exit(EXIT_FAILED)


def _media(store: Store) -> Any:
    """The one-post downloads for a dropped link yt-dlp cannot fetch: ScrapeCreators (``SCRAPECREATORS_API_KEY``) under the
    London day's caps (``studio.hits.DownloadBudget``: ``hits.download_cap_per_day``, ``hits.daily_credit_cap``), else None."""
    from studio import hits  # here, not at the top: studio.hits imports this module

    try:
        return hits.download_budget(store)
    except ValueError as e:  # config/scan.json hits block broken
        fail(str(e))


@app.command("add")
def add_command(
    character_slug: Annotated[
        str | None,
        typer.Option(
            "--character",
            help="A character slug (the folder name in characters/, e.g. franz); left out, the studio recommends one after the check.",
        ),
    ] = None,
    link: Annotated[str | None, typer.Option("--link", help="A full TikTok / Instagram Reel / YouTube link (else a file drop).")] = None,
    own_footage: Annotated[
        bool, typer.Option("--own-footage", help="The owner's own recording or footage used with permission (default: a downloaded clip).")
    ] = False,
    file: Annotated[
        Path | None, typer.Option("--file", help="A saved video on this Mac: uploaded, attached and asked for its check as the terminal does (else a link or an empty file drop).")
    ] = None,
) -> None:
    """File a drop like the terminal does (a link, a saved video with --file, or a file drop waiting for its upload); without
    --character the studio recommends the character (Gemini, free) and moves the drop to him."""
    if file is not None and link is not None:
        fail("give --link or --file, not both")
    store = open_store()
    try:
        pick, duplicate = add_drop(store, character_slug, link, own_footage=own_footage)
        path = None
        if file is not None:
            path = attach_file(store, open_storage(), pick.id, file)
            pick = request_check(store, pick.id)  # the terminal's last step too: the drop leaves Uploading and waits for its check
    except (ValueError, DropError) as e:
        fail(str(e))
    emit({
        "pick_id": pick.id, "duplicate": duplicate, "character": pick.character_slug, "owner_clip_path": path,
        "drop": pick.proposal.get("drop"),
    })


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
        outcome = process_drop(
            store, storage, pick, gemini_client=gemini.GeminiClient.from_env(), deconstruct_answer=answer, media_fallback=_media(store),
        )
    except KeyError:
        fail(f"unknown pick {pick}")
    except (DropError, StorageError) as e:
        fail(str(e))
    _finish(outcome)


@app.command("recheck")
def recheck_command(
    pick: Annotated[str | None, typer.Argument(help="A ready drop's pick id.")] = None,
    all_ready: Annotated[
        bool, typer.Option("--all-ready", help="Every ready drop without the owner's Make it, scored or not.")
    ] = False,
) -> None:
    """Check ready drops again for free (the score, the current hit rules): each goes back to checking for the cloud sweep. Prints
    {"rechecked": [...], "refused": [{"pick_id", "reason"}]}; exit 2 when the one pick named was refused. Nothing is dispatched."""
    if (pick is None) == (not all_ready):
        fail("give a pick or --all-ready (not both)")
    store = open_store()
    if pick is not None:
        ids = [pick]
    else:
        ids = [
            f.id for f in store.list_favorites()
            if is_drop(f.proposal) and f.proposal["drop"].get("state") == "ready" and f.proposal.get("make_requested") is None
        ]
    rechecked: list[str] = []
    refused: list[dict[str, str]] = []
    for pick_id in ids:
        try:
            request_recheck(store, pick_id)
            rechecked.append(pick_id)
        except KeyError:
            refused.append({"pick_id": pick_id, "reason": f"unknown pick {pick_id}"})
        except DropError as e:
            refused.append({"pick_id": pick_id, "reason": str(e)})
    emit({"rechecked": rechecked, "refused": refused})
    if pick is not None and refused:
        raise typer.Exit(EXIT_USAGE)


@app.command("copy")
def copy_command(
    pick: Annotated[str, typer.Argument(help="A checked drop's pick id: the clip, or any version of it.")],
    character_slug: Annotated[
        str, typer.Option("--character", help="Who the version is for: a character slug (the folder name in characters/, e.g. lenny).")
    ],
) -> None:
    """Use a checked clip for another character (free): a version that shares the clip and gets its own check, in his voice, at
    his price. At most 3 characters per clip, like for like, not a paused one. Prints {"pick_id", "copy_of", "character",
    "drop"}; the cloud sweep checks it (nothing is dispatched here). Exit 2 with one line when it is refused."""
    store = open_store()
    try:
        version = copy_drop(store, pick, character_slug)
    except KeyError:
        fail(f"unknown pick {pick}")
    except (DropError, ValueError) as e:
        fail(str(e))
    d = version.proposal["drop"]
    emit({"pick_id": version.id, "copy_of": d["copy_of"], "character": version.character_slug, "drop": d})


@app.command("keep")
def keep_command(
    pick: Annotated[str, typer.Argument(help="A drop's pick id.")],
    off: Annotated[bool, typer.Option("--off", help="Take the Keep off again (retention may then delete an unused clip).")] = False,
) -> None:
    """Keep a drop's clip: retention (``source purge --stale``) never deletes it. Prints {"pick_id", "keep"}."""
    store = open_store()
    try:
        kept = set_keep(store, pick, not off)
    except KeyError:
        fail(f"unknown pick {pick}")
    except (DropError, ValueError) as e:
        fail(str(e))
    emit({"pick_id": kept.id, "keep": kept.proposal["drop"]["keep"]})


@app.command("previews")
def previews_command(
    pick: Annotated[
        str | None, typer.Option("--pick", help="One drop's pick id: its cover and watch copy, made (again) from its clip in Storage.")
    ] = None,
    missing: Annotated[
        bool,
        typer.Option("--missing", help="Every drop with a section and its clip in Storage but no watch copy yet (checked before them)."),
    ] = False,
) -> None:
    """The clip card's cover and watch copy (540x960, the section with its own sound) for clips checked before the check wrote
    them. Free: no Gemini, no Higgsfield. Prints {"made": [ids], "skipped": [{"pick_id", "reason"}]}; exit 2 when the one pick
    named was skipped."""
    if (pick is None) == (not missing):
        fail("give --pick <id> or --missing (not both)")
    store, storage = open_store(), open_storage()
    ids = [pick] if pick is not None else missing_previews(store)
    made: list[str] = []
    skipped: list[dict[str, str]] = []
    for pick_id in ids:
        try:
            make_previews(store, storage, pick_id)
            made.append(pick_id)
        except KeyError:
            skipped.append({"pick_id": pick_id, "reason": f"unknown pick {pick_id}"})
        except (DropError, StorageError, ValueError) as e:
            skipped.append({"pick_id": pick_id, "reason": str(e)})
    emit({"made": made, "skipped": skipped})
    if pick is not None and skipped:
        raise typer.Exit(EXIT_USAGE)


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


def check_keys(
    env: Mapping[str, str] | None = None, *, hf_transport: Any = None, gemini_transport: Any = None
) -> dict[str, str]:
    """Both keys of the cloud jobs, checked for free (a Higgsfield status read, a Gemini model read; nothing is generated or
    spent): ``{"higgsfield": "ok|invalid: ..|error: ..|missing: ..", "gemini": ...}``. The keys never appear in it."""
    return {
        "higgsfield": higgsfield_api.check_credentials(env, transport=hf_transport),
        "gemini": gemini.check_key(env, transport=gemini_transport),
    }


@app.command("check-keys")
def check_keys_command() -> None:
    """Check the Higgsfield and Gemini keys for free: nothing is generated or spent. Exit 1 unless both are ok."""
    out = check_keys()
    emit(out)
    if any(v != "ok" for v in out.values()):
        raise typer.Exit(EXIT_FAILED)


@app.command("pending")
def pending_command(
    include_waiting: Annotated[
        bool, typer.Option("--include-waiting", help="Also the links the cloud could not fetch (the Mac's daily run).")
    ] = False,
    count: Annotated[bool, typer.Option("--count", help="Print only how many.")] = False,
) -> None:
    """The drops a run should take now: process, make or expire (an auto-filed link the cloud could not fetch in 3 days), oldest
    first."""
    store = open_store()
    rows = pending(store, include_waiting=include_waiting, auto_retry=not include_waiting and _auto_retry(_media(store)))
    if count:
        typer.echo(str(len(rows)))
        return
    emit(rows)


def _moved_on(store: Store, row: Mapping[str, str]) -> bool:
    """Whether the drop is no longer where the sweep listed it (a parallel worker finished, expired or skipped it meanwhile):
    still approved or queued, and still in the state ``pending`` saw. A failed check also has moved on when another worker retook
    it since (it failed again, so it is ``failed`` still, but ``at`` / ``auto_retry_at`` differ from the listed row's). A pick that
    has vanished is left to the job to report."""
    fresh = store.get_favorite(row["pick_id"])
    if fresh is None or not is_drop(fresh.proposal):
        return False
    d = drop_of(fresh)
    if fresh.status not in ("approved", "queued") or d.get("state") != row["state"]:
        return True
    return row["state"] == "failed" and not same_failure(row, d)


def _expire_once(store: Store, pick_id: str, now: datetime) -> dict[str, Any]:
    """``expire_unfetched`` under the pick's lease, so two sweep workers never expire the same drop (the loser is ``busy``)."""
    job = job_id()
    if not claim(store, pick_id, "expire", job, now):
        return {"pick_id": pick_id, "ok": True, "busy": True, "reason": "another run holds this video"}
    try:
        return expire_unfetched(store, pick_id, now)
    finally:
        release(store, pick_id, job)


@app.command("sweep")
def sweep_command(
    include_waiting: Annotated[bool, typer.Option("--include-waiting", help="Also retry the waiting links (the Mac).")] = False,
) -> None:
    """Run every pending drop job, one after another (the 2-hourly safety net; the cloud runs three of these workers side by
    side, ``STUDIO_WORKER``, and the lease keeps them off each other's drop). Exit 1 when one of them stopped on a failure: a
    drop another worker holds (busy) or has already moved on is none, and neither is a check that Gemini's quota (HTTP 429) failed
    and the sweep takes again by itself (``Outcome.red``). A check that still has to download its clip is worker 1's alone
    (``takes_downloads``): the others go on to the rest."""
    store, storage = open_store(), open_storage()
    hf, client, media = HiggsfieldClient.from_env(), gemini.GeminiClient.from_env(), _media(store)
    results: list[dict[str, Any]] = []
    failed = False
    rows = pending(
        store, include_waiting=include_waiting, auto_retry=not include_waiting and _auto_retry(media), fetches=takes_downloads(),
    )  # workers 2 and 3 leave the checks that still download a clip to worker 1: one download at a time
    for row in rows:
        try:
            if _moved_on(store, row):
                results.append({"job": row["job"], "pick_id": row["pick_id"], "ok": True, "moved_on": True})
                continue
            if row["job"] == "expire":
                results.append({"job": "expire", **_expire_once(store, row["pick_id"], now_london())})
                continue
            if row["job"] == "process":
                outcome = process_drop(
                    store, storage, row["pick_id"], gemini_client=client, media_fallback=media, auto_retry=row["state"] == "failed",
                    listed=row if row["state"] == "failed" else None,
                )
            else:
                outcome = make_drop(store, storage, row["pick_id"], hf=hf, gemini_client=client)
            results.append({"job": row["job"], **outcome.json()})
            failed = failed or outcome.red
        except (KeyError, DropError, StorageError, ValueError) as e:
            results.append({"job": row["job"], "pick_id": row["pick_id"], "ok": False, "error": str(e)[:300]})
            failed = True
    emit({"ran": len(results), "results": results})
    if failed:
        raise typer.Exit(EXIT_FAILED)


@app.command("auto-make")
def auto_make_command(
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Print what would be asked for; write nothing.")] = False,
) -> None:
    """The studio makes them: ask for the make of one ready drop for every live character whose next slot is coming and has nothing
    on its way, within the credit cap and Higgsfield's balance (see ``auto_make``). Runs at the start of every cloud sweep. Prints one
    JSON object, {"requested": [...], "skipped": [...], "waiting": reason | null}; exit 0 even while it waits for credits (every
    day until the owner tops up), 2 for a broken config or test registry."""
    store = open_store()
    hf = HiggsfieldClient.from_env()
    try:
        out = auto_make(store, now_london(), hf=hf, dry_run=dry_run, scan=_scan())
    except ValueError as e:  # a broken config/scan.json or config/experiments.json: the caller fixes it
        fail(str(e))
    finally:
        if hf is not None:
            hf.close()
    emit(out)


def _sync_stopped(error: BaseException) -> NoReturn:
    """One line on stderr, exit 1: an unattended run (the LaunchAgent) must leave a readable log, never a traceback."""
    what = str(error) if isinstance(error, (OSError, ValueError)) else f"{type(error).__name__}: {error}"
    hint = " (macOS may be refusing access to iCloud Drive)" if isinstance(error, PermissionError) else ""
    typer.echo(f"error: the clips sync stopped: {' '.join(what.split())[:300]}{hint}", err=True)
    raise typer.Exit(EXIT_FAILED)


@app.command("sync-folder")
def sync_folder_command(
    folder: Annotated[Path | None, typer.Option("--folder", help="The clips folder (default: ODD EYES clips in iCloud Drive).")] = None,
    ledger: Annotated[
        Path | None, typer.Option("--ledger", help="The ledger of the clips taken (default: ~/.local/state/odd-eyes/clips-ledger.json).")
    ] = None,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Only list what would be taken: nothing is uploaded, moved or written, iCloud is not asked.")
    ] = False,
    dispatch: Annotated[
        bool, typer.Option("--dispatch/--no-dispatch", help="After a run that added clips, wake the cloud check (gh workflow run).")
    ] = True,
) -> None:
    """Take the new videos of the owner's iCloud clips folder as file drops (no character: the studio recommends) and move them to
    Added/. Exit 0 unless every file failed (1); a missing folder is 2 (run bin/install-clip-sync); any other error stops the run
    with one line and exit 1. A second run at the same time does nothing."""
    from studio import clipfolder  # here, not at the top: clipfolder imports this module

    folder = folder if folder is not None else clipfolder.DEFAULT_FOLDER
    ledger = ledger if ledger is not None else clipfolder.DEFAULT_LEDGER
    try:
        present = folder.is_dir()
    except OSError as e:  # macOS refuses even the look at it
        _sync_stopped(e)
    if not present:
        fail(f"no clips folder at {folder}: run bin/install-clip-sync")
    if dry_run:  # no store, no storage, no lock: nothing is written
        try:
            result: dict[str, Any] = {"dry_run": True, **clipfolder.preview_folder(folder, ledger)}
        except (OSError, ValueError) as e:
            _sync_stopped(e)
        emit({**result, "dispatched": False, "dispatch_error": None})
        return
    store, storage = open_store(), open_storage()  # outside the try: fail() is an exit, not an error to report
    try:
        with clipfolder.run_lock(ledger) as free:
            if not free:
                emit({"skipped_run": "another sync is running"})
                return
            result = clipfolder.sync_folder(store, storage, folder, ledger, now_london())
    except Exception as e:  # whatever it is (a database error included) is one line in the log, never a traceback
        _sync_stopped(e)
    nudge = dispatch and bool(result["added"])  # once per run, and only when there is something new to check
    dispatch_error = clipfolder.nudge_cloud() if nudge else None
    emit({**result, "dispatched": nudge and dispatch_error is None, "dispatch_error": dispatch_error})
    if clipfolder.every_file_failed(result):
        raise typer.Exit(EXIT_FAILED)
