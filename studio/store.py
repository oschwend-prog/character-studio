"""The ``Store`` protocol and ``MemoryStore``, the in-memory implementation for tests.

All business logic (budget, sources, clip state machine, planning, publishing, metrics)
talks to a ``Store``. ``studio.pgstore.PostgresStore`` is the production implementation;
``MemoryStore`` is what unit tests use. Both obey the same rules:

* ``add_*`` returns the stored object with ``id`` / ``created_at`` assigned if they were
  ``None``; every object that crosses the boundary is a copy, so callers cannot mutate
  stored state by accident.
* ``update_*(id, **fields)`` returns the updated object; raises ``KeyError`` for an
  unknown id, ``TypeError`` for an unknown field and ``ValueError`` for an ``id`` change
  or an invalid value. ``get_*`` returns ``None`` for an unknown id.
* ``list_*(**filters)`` filters by equality on any field (``None`` matches NULL) and
  raises ``TypeError`` for an unknown field. Order: ``created_at`` (posts:
  ``scheduled_for``, snapshots: ``captured_at``).
* ``upsert_character(c)`` inserts or replaces the character by ``slug``. ``upsert_account(a)`` matches an
  account on ``(character_slug, platform)``: a new one is inserted as given; an existing one gets only
  its identity refreshed (``handle``, ``postiz_integration_id``). Its ``mode`` and ``dropin_share`` are
  operational state (the terminal's autopilot toggle, the weekly review's Instagram guard) and a
  re-seed must not undo them, so they are kept.
* ``add_run(r)`` appends a line to the scheduled-run log (``started_at`` defaults to now);
  ``list_runs`` is ordered by ``started_at``. ``upsert_review(r)`` matches a review on
  ``(week, character_slug)``: a new one is inserted, an existing one gets the new ``report_md`` and
  ``bar_status`` and keeps its ``id`` and ``created_at``, so saving a week's report twice leaves one row.
  ``list_reviews`` is ordered by ``week``, then ``character_slug``.
* One post per ``(clip_id, account_id)``: a second ``add_post`` raises ``DuplicatePost``.
* ``claim_due_posts(now)`` atomically flips due ``scheduled`` posts to ``posting``; a
  post is handed out at most once. ``now`` must be timezone-aware.
* ``upsert_hit(h)`` (the cloud hits job, migration 0016) matches a hit on its ``url`` and returns ``(hit, created)``. A new
  one is inserted as given. An existing one keeps its ``id``, ``status`` (a dismissed hit stays dismissed) and ``created_at``
  (first seen); its numbers and details (``HIT_REFRESHED``) take the new value when one is given, else stay; who found it
  (``HIT_FIRST_FOUND``: the character and the keyword) is filled in only while it is empty; ``reach``, ``score`` and
  ``last_seen`` are always the new ones. ``list_hits`` is ordered by ``created_at``.
* ``get_hit_spend(day)`` is the London day's ScrapeCreators spend (a zero record when nothing was spent);
  ``add_hit_spend(day, search_credits=, download_credits=, downloads=)`` adds to it in one step (an increment, never a
  read-then-write) and returns the day's new totals.
"""

from __future__ import annotations

import copy
import threading
import uuid
from collections.abc import Iterable, Iterator
from contextlib import AbstractContextManager, contextmanager
from dataclasses import fields, replace
from datetime import date, datetime, timezone
from typing import Any, Protocol, runtime_checkable

from studio.models import (
    Account,
    Character,
    Clip,
    Favorite,
    Hit,
    HitSpend,
    LedgerEntry,
    Post,
    PostStatus,
    Review,
    Run,
    Settings,
    Snapshot,
    Source,
)

# upsert_hit's rules (MemoryStore and PostgresStore alike): refreshed when the new value is given, filled in only while empty,
# always replaced.
HIT_REFRESHED = (
    "followers", "views", "likes", "comments", "shares", "saves", "posted_at", "caption", "sound", "duration_s", "thumbnail_url",
)
HIT_FIRST_FOUND = ("character_slug", "keyword")
HIT_RECOMPUTED = ("reach", "score", "last_seen")


class DuplicatePost(ValueError):
    """A post for this (clip, account) pair already exists."""


def check_fields(cls: type, names: Iterable[str], what: str) -> None:
    """Raise ``TypeError`` if any of ``names`` is not a field of dataclass ``cls``."""
    known = {f.name for f in fields(cls)}
    unknown = sorted(set(names) - known)
    if unknown:
        raise TypeError(f"{what}: unknown field(s) {unknown} for {cls.__name__}")


def require_aware(value: datetime, what: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{what} must be timezone-aware (never naive), got {value!r}")
    return value


def require_aware_values(values: dict[str, Any]) -> None:
    """Raise ``ValueError`` if any datetime among ``values`` (field -> value) is naive."""
    for name, value in values.items():
        if isinstance(value, datetime):
            require_aware(value, name)


@runtime_checkable
class Store(Protocol):
    # settings (single row)
    def get_settings(self) -> Settings: ...
    def set_settings(self, **kw: Any) -> Settings: ...

    # budget ledger
    def ledger_add(self, e: LedgerEntry) -> LedgerEntry: ...
    def ledger_month(self, month: str) -> list[LedgerEntry]: ...

    # sources
    def add_source(self, s: Source) -> Source: ...
    def update_source(self, id: str, /, **kw: Any) -> Source: ...
    def list_sources(self, **filters: Any) -> list[Source]: ...

    # clips
    def add_clip(self, c: Clip) -> Clip: ...
    def get_clip(self, id: str) -> Clip | None: ...
    def update_clip(self, id: str, /, **kw: Any) -> Clip: ...
    def list_clips(self, **filters: Any) -> list[Clip]: ...

    # posts
    def add_post(self, p: Post) -> Post: ...
    def claim_due_posts(self, now: datetime) -> list[Post]: ...
    def update_post(self, id: str, /, **kw: Any) -> Post: ...
    def list_posts(self, **filters: Any) -> list[Post]: ...
    def delete_post(self, id: str, /) -> None: ...

    # metrics
    def add_snapshot(self, s: Snapshot) -> Snapshot: ...
    def snapshots_for(self, post_id: str) -> list[Snapshot]: ...

    # characters and accounts (written by `studio seed` through the two upserts; the one other
    # write is update_account, used by the weekly review's Instagram guard to cut dropin_share)
    def accounts(self, character_slug: str | None = None) -> list[Account]: ...
    def update_account(self, id: str, /, **kw: Any) -> Account: ...
    def characters(self) -> list[Character]: ...
    def upsert_character(self, c: Character) -> Character: ...
    def upsert_account(self, a: Account) -> Account: ...

    # favourites (Viral Picks)
    def add_favorite(self, f: Favorite) -> Favorite: ...
    def get_favorite(self, id: str) -> Favorite | None: ...
    def update_favorite(self, id: str, /, **kw: Any) -> Favorite: ...
    def list_favorites(self, **filters: Any) -> list[Favorite]: ...

    # hits (the cloud hits job, migration 0016)
    def upsert_hit(self, h: Hit) -> tuple[Hit, bool]: ...
    def get_hit(self, id: str) -> Hit | None: ...
    def update_hit(self, id: str, /, **kw: Any) -> Hit: ...
    def list_hits(self, **filters: Any) -> list[Hit]: ...
    def get_hit_spend(self, day: date, /) -> HitSpend: ...
    def add_hit_spend(self, day: date, /, *, search_credits: int = 0, download_credits: int = 0, downloads: int = 0) -> HitSpend: ...

    # scheduled-run log and weekly reviews
    def add_run(self, r: Run) -> Run: ...
    def list_runs(self, **filters: Any) -> list[Run]: ...
    def upsert_review(self, r: Review) -> Review: ...
    def list_reviews(self, **filters: Any) -> list[Review]: ...

    def transaction(self) -> AbstractContextManager[Any]: ...


def _now() -> datetime:
    return datetime.now(timezone.utc)


class MemoryStore:
    """Dict-backed ``Store``. ``transaction()`` is a no-op (there is no rollback)."""

    def __init__(
        self,
        *,
        characters: Iterable[Character] = (),
        accounts: Iterable[Account] = (),
        settings: Settings | None = None,
    ) -> None:
        self._lock = threading.RLock()
        self._settings = copy.deepcopy(settings) if settings else Settings()
        self._characters: dict[str, Character] = {}
        self._accounts: dict[str, Account] = {}
        self._sources: dict[str, Source] = {}
        self._clips: dict[str, Clip] = {}
        self._posts: dict[str, Post] = {}
        self._favorites: dict[str, Favorite] = {}
        self._hits: dict[str, Hit] = {}
        self._hit_spend: dict[date, HitSpend] = {}
        self._runs: dict[str, Run] = {}
        self._reviews: dict[str, Review] = {}
        self._ledger: list[LedgerEntry] = []
        self._snapshots: list[Snapshot] = []
        for c in characters:
            self.add_character(c)
        for a in accounts:
            self.add_account(a)

    # ---- generic helpers -------------------------------------------------

    @staticmethod
    def _insert(bucket: dict[str, Any], obj: Any) -> Any:
        stored = copy.deepcopy(obj)
        require_aware_values(vars(stored))
        if stored.id is None:
            stored.id = str(uuid.uuid4())
        if hasattr(stored, "created_at") and stored.created_at is None:
            stored.created_at = _now()
        bucket[stored.id] = stored
        return copy.deepcopy(stored)

    @staticmethod
    def _update(bucket: dict[str, Any], id: str, kw: dict[str, Any]) -> Any:
        old = bucket.get(id)
        if old is None:
            raise KeyError(id)
        check_fields(type(old), kw, "update")
        if "id" in kw:
            raise ValueError("id is immutable")
        require_aware_values(kw)
        new = replace(old, **copy.deepcopy(kw))  # re-runs __post_init__: coercion + validation
        bucket[id] = new
        return copy.deepcopy(new)

    @staticmethod
    def _select(items: Iterable[Any], filters: dict[str, Any], cls: type, key: Any) -> list[Any]:
        check_fields(cls, filters, "filter")
        rows = [o for o in items if all(getattr(o, k) == v for k, v in filters.items())]
        return [copy.deepcopy(o) for o in sorted(rows, key=key)]

    # ---- settings ----------------------------------------------------------

    def get_settings(self) -> Settings:
        with self._lock:
            return copy.deepcopy(self._settings)

    def set_settings(self, **kw: Any) -> Settings:
        with self._lock:
            check_fields(Settings, kw, "set_settings")
            self._settings = replace(self._settings, **copy.deepcopy(kw))
            return copy.deepcopy(self._settings)

    # ---- ledger ------------------------------------------------------------

    def ledger_add(self, e: LedgerEntry) -> LedgerEntry:
        with self._lock:
            stored = copy.deepcopy(e)
            stored.id = stored.id or str(uuid.uuid4())
            stored.created_at = stored.created_at or _now()
            self._ledger.append(stored)
            return copy.deepcopy(stored)

    def ledger_month(self, month: str) -> list[LedgerEntry]:
        with self._lock:
            rows = [e for e in self._ledger if e.month == month]
            return [copy.deepcopy(e) for e in sorted(rows, key=lambda e: e.created_at)]

    # ---- sources -----------------------------------------------------------

    def add_source(self, s: Source) -> Source:
        with self._lock:
            return self._insert(self._sources, s)

    def update_source(self, id: str, /, **kw: Any) -> Source:
        with self._lock:
            return self._update(self._sources, id, kw)

    def list_sources(self, **filters: Any) -> list[Source]:
        with self._lock:
            return self._select(
                self._sources.values(), filters, Source, lambda s: s.created_at
            )

    # ---- clips -------------------------------------------------------------

    def add_clip(self, c: Clip) -> Clip:
        with self._lock:
            return self._insert(self._clips, c)

    def get_clip(self, id: str) -> Clip | None:
        with self._lock:
            c = self._clips.get(id)
            return copy.deepcopy(c) if c else None

    def update_clip(self, id: str, /, **kw: Any) -> Clip:
        with self._lock:
            return self._update(self._clips, id, kw)

    def list_clips(self, **filters: Any) -> list[Clip]:
        with self._lock:
            return self._select(self._clips.values(), filters, Clip, lambda c: c.created_at)

    # ---- posts -------------------------------------------------------------

    def add_post(self, p: Post) -> Post:
        with self._lock:
            if any(
                x.clip_id == p.clip_id and x.account_id == p.account_id
                for x in self._posts.values()
            ):
                raise DuplicatePost(f"clip {p.clip_id} already has a post for account {p.account_id}")
            return self._insert(self._posts, p)

    def claim_due_posts(self, now: datetime) -> list[Post]:
        require_aware(now, "claim_due_posts(now)")
        with self._lock:
            claimed: list[Post] = []
            for p in sorted(self._posts.values(), key=lambda p: p.scheduled_for):
                if p.status is PostStatus.scheduled and p.scheduled_for <= now:
                    p.status = PostStatus.posting
                    p.claimed_at = now
                    claimed.append(copy.deepcopy(p))
            return claimed

    def update_post(self, id: str, /, **kw: Any) -> Post:
        with self._lock:
            return self._update(self._posts, id, kw)

    def list_posts(self, **filters: Any) -> list[Post]:
        with self._lock:
            return self._select(self._posts.values(), filters, Post, lambda p: p.scheduled_for)

    def delete_post(self, id: str, /) -> None:
        """Remove one post row (``studio publish resolve --drop``). ``KeyError`` when there is none."""
        with self._lock:
            if id not in self._posts:
                raise KeyError(id)
            del self._posts[id]

    # ---- metrics -----------------------------------------------------------

    def add_snapshot(self, s: Snapshot) -> Snapshot:
        with self._lock:
            stored = copy.deepcopy(s)
            stored.captured_at = stored.captured_at or _now()
            self._snapshots.append(stored)
            return copy.deepcopy(stored)

    def snapshots_for(self, post_id: str) -> list[Snapshot]:
        with self._lock:
            rows = [s for s in self._snapshots if s.post_id == post_id]
            return [copy.deepcopy(s) for s in sorted(rows, key=lambda s: s.captured_at)]

    # ---- characters and accounts -----------------------------------------

    def add_character(self, c: Character) -> Character:
        """Test/seed helper (not part of ``Store``): insert or replace by slug."""
        with self._lock:
            self._characters[c.slug] = copy.deepcopy(c)
            return copy.deepcopy(c)

    def add_account(self, a: Account) -> Account:
        """Test/seed helper (not part of ``Store``)."""
        with self._lock:
            return self._insert(self._accounts, a)

    def accounts(self, character_slug: str | None = None) -> list[Account]:
        with self._lock:
            rows = [
                a
                for a in self._accounts.values()
                if character_slug is None or a.character_slug == character_slug
            ]
            rows.sort(key=lambda a: (a.character_slug, a.platform))
            return [copy.deepcopy(a) for a in rows]

    def update_account(self, id: str, /, **kw: Any) -> Account:
        with self._lock:
            return self._update(self._accounts, id, kw)

    def characters(self) -> list[Character]:
        with self._lock:
            return [copy.deepcopy(c) for _, c in sorted(self._characters.items())]

    def upsert_character(self, c: Character) -> Character:
        with self._lock:
            return self.add_character(c)

    def upsert_account(self, a: Account) -> Account:
        with self._lock:
            old = next(
                (
                    x
                    for x in self._accounts.values()
                    if x.character_slug == a.character_slug and x.platform is a.platform
                ),
                None,
            )
            if old is None:
                return self.add_account(a)
            return self._update(
                self._accounts,
                old.id,
                {"handle": a.handle, "postiz_integration_id": a.postiz_integration_id},
            )

    # ---- favourites --------------------------------------------------------

    def add_favorite(self, f: Favorite) -> Favorite:
        with self._lock:
            return self._insert(self._favorites, f)

    def get_favorite(self, id: str) -> Favorite | None:
        with self._lock:
            f = self._favorites.get(id)
            return copy.deepcopy(f) if f else None

    def update_favorite(self, id: str, /, **kw: Any) -> Favorite:
        with self._lock:
            return self._update(self._favorites, id, kw)

    def list_favorites(self, **filters: Any) -> list[Favorite]:
        with self._lock:
            return self._select(
                self._favorites.values(), filters, Favorite, lambda f: f.created_at
            )

    # ---- hits ----------------------------------------------------------------

    def upsert_hit(self, h: Hit) -> tuple[Hit, bool]:
        with self._lock:
            old = next((x for x in self._hits.values() if x.url == h.url), None)
            if old is None:
                stored = copy.deepcopy(h)
                stored.last_seen = stored.last_seen or _now()
                return self._insert(self._hits, stored), True
            changes = {c: getattr(h, c) for c in HIT_REFRESHED if getattr(h, c) is not None}
            changes |= {c: getattr(h, c) for c in HIT_FIRST_FOUND if getattr(old, c) is None and getattr(h, c) is not None}
            changes |= {"reach": h.reach, "score": h.score, "last_seen": h.last_seen or _now()}
            return self._update(self._hits, old.id, changes), False

    def get_hit(self, id: str) -> Hit | None:
        with self._lock:
            h = self._hits.get(id)
            return copy.deepcopy(h) if h else None

    def update_hit(self, id: str, /, **kw: Any) -> Hit:
        with self._lock:
            return self._update(self._hits, id, kw)

    def list_hits(self, **filters: Any) -> list[Hit]:
        with self._lock:
            return self._select(self._hits.values(), filters, Hit, lambda h: h.created_at)

    def get_hit_spend(self, day: date, /) -> HitSpend:
        with self._lock:
            return copy.deepcopy(self._hit_spend.get(day) or HitSpend(day=day))

    def add_hit_spend(self, day: date, /, *, search_credits: int = 0, download_credits: int = 0, downloads: int = 0) -> HitSpend:
        for value in (search_credits, download_credits, downloads):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"a spend is a whole number of 0 or more, got {value!r}")
        with self._lock:
            old = self._hit_spend.get(day) or HitSpend(day=day)
            new = HitSpend(
                day=day, search_credits=old.search_credits + search_credits,
                download_credits=old.download_credits + download_credits, downloads=old.downloads + downloads, updated_at=_now(),
            )  # fmt: skip
            self._hit_spend[day] = new
            return copy.deepcopy(new)

    # ---- runs and reviews --------------------------------------------------

    def add_run(self, r: Run) -> Run:
        with self._lock:
            stored = copy.deepcopy(r)
            if stored.started_at is None:
                stored.started_at = _now()
            return self._insert(self._runs, stored)

    def list_runs(self, **filters: Any) -> list[Run]:
        with self._lock:
            return self._select(self._runs.values(), filters, Run, lambda r: r.started_at)

    def upsert_review(self, r: Review) -> Review:
        with self._lock:
            old = next(
                (
                    x
                    for x in self._reviews.values()
                    if x.week == r.week and x.character_slug == r.character_slug
                ),
                None,
            )
            if old is None:
                return self._insert(self._reviews, r)
            return self._update(
                self._reviews, old.id, {"report_md": r.report_md, "bar_status": r.bar_status}
            )

    def list_reviews(self, **filters: Any) -> list[Review]:
        with self._lock:
            return self._select(
                self._reviews.values(), filters, Review, lambda r: (r.week, r.character_slug)
            )

    # ---- transactions ------------------------------------------------------

    @contextmanager
    def transaction(self) -> Iterator[MemoryStore]:
        yield self
