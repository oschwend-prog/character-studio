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
* One post per ``(clip_id, account_id)``: a second ``add_post`` raises ``DuplicatePost``.
* ``claim_due_posts(now)`` atomically flips due ``scheduled`` posts to ``posting``; a
  post is handed out at most once. ``now`` must be timezone-aware.
"""

from __future__ import annotations

import copy
import threading
import uuid
from collections.abc import Iterable, Iterator
from contextlib import AbstractContextManager, contextmanager
from dataclasses import fields, replace
from datetime import datetime, timezone
from typing import Any, Protocol, runtime_checkable

from studio.models import (
    Account,
    Character,
    Clip,
    Favorite,
    LedgerEntry,
    Post,
    PostStatus,
    Settings,
    Snapshot,
    Source,
)

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

    # metrics
    def add_snapshot(self, s: Snapshot) -> Snapshot: ...
    def snapshots_for(self, post_id: str) -> list[Snapshot]: ...

    # characters and accounts (seeded by `studio seed`; the one write is update_account, used by
    # the weekly review's Instagram guard to cut an account's dropin_share)
    def accounts(self, character_slug: str | None = None) -> list[Account]: ...
    def update_account(self, id: str, /, **kw: Any) -> Account: ...
    def characters(self) -> list[Character]: ...

    # favourites (Viral Picks)
    def add_favorite(self, f: Favorite) -> Favorite: ...
    def get_favorite(self, id: str) -> Favorite | None: ...
    def update_favorite(self, id: str, /, **kw: Any) -> Favorite: ...
    def list_favorites(self, **filters: Any) -> list[Favorite]: ...

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

    # ---- transactions ------------------------------------------------------

    @contextmanager
    def transaction(self) -> Iterator[MemoryStore]:
        yield self
