"""Domain model: enums and plain dataclasses, one per table in schema ``studio``.

Conventions
-----------
* Every dataclass is keyword-only. Ids are ``str`` (uuid text); ``id=None`` and
  ``created_at=None`` mean "let the store assign it".
* Enum-valued fields accept the enum or its string value and are normalised to the
  enum in ``__post_init__`` (so ``Clip(mode="dropin").mode is Mode.dropin``). Bad values
  raise ``ValueError`` here, before they can reach a CHECK constraint.
* ``Post.scheduled_for`` must be timezone-aware: the plan forbids naive datetimes,
  and Postgres would silently read a naive one in the session time zone.
* ``studio.config.Settings`` is the *environment* settings; ``Settings`` here is the
  single ``studio.settings`` row (budget cap, kill switch, cadence).
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any, Literal, get_args


class Platform(StrEnum):
    tiktok = "tiktok"
    instagram = "instagram"


class Mode(StrEnum):
    dropin = "dropin"
    recreate = "recreate"


class SourceKind(StrEnum):
    higgsfield_library = "higgsfield_library"
    owner_inbox = "owner_inbox"
    synthetic = "synthetic"


class Body(StrEnum):
    biped = "biped"
    quadruped = "quadruped"


class ClipState(StrEnum):
    planned = "planned"
    generating = "generating"
    gen_failed = "gen_failed"
    generated = "generated"
    qa_failed = "qa_failed"
    qa_passed = "qa_passed"
    mastered = "mastered"
    awaiting_approval = "awaiting_approval"
    approved = "approved"
    rejected = "rejected"
    scheduled = "scheduled"
    posted = "posted"
    dropped = "dropped"


class PostStatus(StrEnum):
    scheduled = "scheduled"
    posting = "posting"
    posted = "posted"
    failed = "failed"
    needs_check = "needs_check"


AccountMode = Literal["approval", "auto"]
LedgerKind = Literal["reserve", "settle", "release"]
FavoriteOrigin = Literal["scan", "owner"]
FavoriteStatus = Literal["new", "approved", "skipped", "analysed", "queued", "made"]

# Drop-in targets per platform (plan Global Constraints); used when an Account sets none.
DEFAULT_DROPIN_SHARE: dict[Platform, float] = {Platform.tiktok: 0.70, Platform.instagram: 0.40}

# Same JSON as the seed row in supabase/migrations/0001_studio.sql.
DEFAULT_CADENCE: dict[str, Any] = {
    "biscuit": {"days": ["tue", "wed", "thu"], "slot": "19:00"},
    "reginald": {"days": ["tue", "wed", "thu"], "slot": "19:30"},
}


def _one_of(value: str, literal: Any, what: str) -> str:
    allowed = get_args(literal)
    if value not in allowed:
        raise ValueError(f"{what} must be one of {allowed}, got {value!r}")
    return value


def _aware(value: datetime, what: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{what} must be timezone-aware (never naive), got {value!r}")
    return value


@dataclass(kw_only=True)
class Character:
    slug: str
    name: str
    status: str = "designing"
    bodies: list[Body] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.bodies = [Body(b) for b in self.bodies]


@dataclass(kw_only=True)
class Account:
    id: str | None = None
    character_slug: str
    platform: Platform
    handle: str
    postiz_integration_id: str | None = None
    mode: AccountMode = "approval"
    # None -> the platform default (TikTok 0.70, Instagram 0.40); always a float afterwards.
    dropin_share: float | None = None

    def __post_init__(self) -> None:
        self.platform = Platform(self.platform)
        _one_of(self.mode, AccountMode, "Account.mode")
        if self.dropin_share is None:
            self.dropin_share = DEFAULT_DROPIN_SHARE[self.platform]


@dataclass(kw_only=True)
class Source:
    id: str | None = None
    kind: SourceKind
    url: str | None = None
    storage_path: str | None = None
    preset_id: str | None = None
    body: Body
    bodies: int
    duration_s: float
    has_watermark: bool | None = None  # None = not checked yet
    has_overlay: bool | None = None
    other_people: int | None = None
    trend: str | None = None
    credit_handle: str | None = None
    created_at: datetime | None = None

    def __post_init__(self) -> None:
        self.kind = SourceKind(self.kind)
        self.body = Body(self.body)


@dataclass(kw_only=True)
class Clip:
    id: str | None = None
    character_slug: str
    source_id: str | None = None
    mode: Mode
    state: ClipState = ClipState.planned
    hf_job_id: str | None = None
    credits_reserved: int = 0
    credits_actual: int | None = None  # None until settled
    qa: dict[str, Any] = field(default_factory=dict)
    master_path: str | None = None
    hook: str | None = None
    caption: str | None = None
    hashtags: list[str] = field(default_factory=list)
    features: dict[str, Any] = field(default_factory=dict)
    reject_reason: str | None = None
    created_at: datetime | None = None

    def __post_init__(self) -> None:
        self.mode = Mode(self.mode)
        self.state = ClipState(self.state)


@dataclass(kw_only=True)
class Post:
    id: str | None = None
    clip_id: str
    account_id: str
    scheduled_for: datetime
    status: PostStatus = PostStatus.scheduled
    claimed_at: datetime | None = None
    attempts: int = 0
    platform_post_id: str | None = None
    url: str | None = None
    error: str | None = None

    def __post_init__(self) -> None:
        self.status = PostStatus(self.status)
        _aware(self.scheduled_for, "Post.scheduled_for")


@dataclass(kw_only=True)
class Snapshot:
    """One metrics reading. Any metric the platform did not report stays ``None``, never 0."""

    post_id: str
    captured_at: datetime | None = None
    views: int | None = None
    likes: int | None = None
    comments: int | None = None
    shares: int | None = None
    saves: int | None = None
    watch_time_s: float | None = None
    follows: int | None = None
    non_follower_pct: float | None = None


@dataclass(kw_only=True)
class Settings:
    monthly_cap_credits: int = 6000
    kill_switch: bool = False
    cadence: dict[str, Any] = field(default_factory=lambda: copy.deepcopy(DEFAULT_CADENCE))


@dataclass(kw_only=True)
class Favorite:
    """A Viral Picks row. Scan results arrive as ``new``; only ``approved`` ones are produced."""

    id: str | None = None
    url: str
    platform: str | None = None  # tiktok / instagram / youtube
    creator_handle: str | None = None
    views: int | None = None
    outlier_x: float | None = None
    origin: FavoriteOrigin = "scan"
    character_slug: str | None = None
    proposal: dict[str, Any] = field(default_factory=dict)
    scores: dict[str, Any] = field(default_factory=dict)
    total_score: float | None = None
    note: str | None = None
    status: FavoriteStatus = "new"
    breakdown_md: str | None = None
    source_id: str | None = None
    clip_id: str | None = None
    created_at: datetime | None = None

    def __post_init__(self) -> None:
        _one_of(self.origin, FavoriteOrigin, "Favorite.origin")
        _one_of(self.status, FavoriteStatus, "Favorite.status")


@dataclass(kw_only=True)
class LedgerEntry:
    id: str | None = None
    clip_id: str
    month: str  # 'YYYY-MM' (London month; a settle/release carries the month of its reservation)
    kind: LedgerKind
    credits: int
    created_at: datetime | None = None

    def __post_init__(self) -> None:
        _one_of(self.kind, LedgerKind, "LedgerEntry.kind")
