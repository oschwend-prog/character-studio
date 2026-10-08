"""``PostgresStore``: the production ``Store``, backed by schema ``studio`` (psycopg 3).

Behaviour matches ``MemoryStore`` (see ``studio.store``). Notes on how it talks to Postgres:

* Every call uses its own short-lived connection and commits on success, except inside
  ``with store.transaction():`` where all calls on that thread share one connection and
  commit or roll back together. ``get_settings()`` takes the settings row ``FOR UPDATE``
  while inside a transaction, which is what serialises budget reservations.
* ``claim_due_posts`` is one ``UPDATE ... WHERE status='scheduled' AND scheduled_for <= now
  RETURNING``: a concurrent claimer blocks on the row, re-checks the predicate after the
  first commits, and gets nothing. ``claimed_at`` is stamped with the ``now`` passed in
  (the same clock the caller used to decide what is due), not the database clock.
* ``prepare_threshold=None`` keeps it working through Supabase's transaction-mode pooler.
* Table and column names come from the dataclass fields (never from caller input);
  values are always bound parameters.
"""

from __future__ import annotations

import dataclasses
import re
import threading
import uuid
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any

import psycopg
from psycopg import sql
from psycopg.errors import CheckViolation, ForeignKeyViolation, UniqueViolation
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from studio.models import (
    Account,
    Character,
    Clip,
    Favorite,
    Hit,
    LedgerEntry,
    Post,
    Review,
    Run,
    Settings,
    Snapshot,
    Source,
)
from studio.store import (
    HIT_FIRST_FOUND,
    HIT_RECOMPUTED,
    HIT_REFRESHED,
    DuplicatePost,
    check_fields,
    require_aware,
    require_aware_values,
)

_IDENT = re.compile(r"[a-z_][a-z0-9_]*")


@dataclasses.dataclass(frozen=True)
class _Table:
    name: str
    cls: type
    json_cols: frozenset[str] = frozenset()
    # Columns the database fills in when Python leaves them as None.
    db_default: frozenset[str] = frozenset({"id", "created_at"})

    @property
    def columns(self) -> list[str]:
        return [f.name for f in dataclasses.fields(self.cls)]


_SETTINGS = _Table("settings", Settings, json_cols=frozenset({"cadence"}), db_default=frozenset())
_CHARACTERS = _Table("characters", Character, json_cols=frozenset({"setup"}), db_default=frozenset())
_ACCOUNTS = _Table("accounts", Account)
_SOURCES = _Table("sources", Source)
_CLIPS = _Table("clips", Clip, json_cols=frozenset({"qa", "features"}))
_POSTS = _Table("posts", Post)
_SNAPSHOTS = _Table("snapshots", Snapshot, db_default=frozenset({"captured_at"}))
_LEDGER = _Table("ledger", LedgerEntry)
_FAVORITES = _Table("favorites", Favorite, json_cols=frozenset({"proposal", "scores"}))
_RUNS = _Table("runs", Run, json_cols=frozenset({"details"}), db_default=frozenset({"id", "started_at"}))
_REVIEWS = _Table("reviews", Review)
_HITS = _Table("hits", Hit, db_default=frozenset({"id", "created_at", "last_seen"}))


def _as_uuid(value: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value))
    except ValueError:
        return None


class PostgresStore:
    def __init__(self, dsn: str, schema: str = "studio") -> None:
        if not _IDENT.fullmatch(schema):
            raise ValueError(f"invalid schema name {schema!r}")
        self._dsn = dsn
        self._schema = schema
        self._local = threading.local()  # .conn is set while a transaction() is open

    # ---- connection plumbing ---------------------------------------------

    def _connect(self) -> psycopg.Connection[dict[str, Any]]:
        return psycopg.connect(self._dsn, row_factory=dict_row, prepare_threshold=None)

    def _in_transaction(self) -> bool:
        return getattr(self._local, "conn", None) is not None

    @contextmanager
    def _cursor(self) -> Iterator[psycopg.Cursor[dict[str, Any]]]:
        conn = getattr(self._local, "conn", None)
        if conn is not None:  # inside transaction(): share the connection, no commit here
            with conn.cursor() as cur:
                yield cur
            return
        with self._connect() as conn:  # commits on success, rolls back on error, closes
            with conn.cursor() as cur:
                yield cur

    @contextmanager
    def transaction(self) -> Iterator[PostgresStore]:
        """Run the block in one database transaction (nested use joins the outer one)."""
        if self._in_transaction():
            yield self
            return
        with self._connect() as conn:
            # conn.transaction() issues BEGIN now (not lazily at the first statement), so a
            # savepoint-protected insert inside the block really is a savepoint and not an
            # early commit; it COMMITs on a clean exit and ROLLBACKs on an exception.
            with conn.transaction():
                self._local.conn = conn
                try:
                    yield self
                finally:
                    self._local.conn = None

    def _execute(self, query: sql.Composable, params: Sequence[Any] = ()) -> list[dict[str, Any]]:
        with self._cursor() as cur:
            cur.execute(query, params)
            return cur.fetchall() if cur.description else []

    # ---- query building --------------------------------------------------

    def _tbl(self, table: _Table) -> sql.Identifier:
        return sql.Identifier(self._schema, table.name)

    @staticmethod
    def _cols(names: Sequence[str]) -> sql.Composable:
        return sql.SQL(", ").join(sql.Identifier(n) for n in names)

    @staticmethod
    def _to_db(table: _Table, col: str, value: Any) -> Any:
        if col in table.json_cols:
            return Jsonb(value)
        if isinstance(value, Enum):
            return value.value
        if isinstance(value, list):
            return [v.value if isinstance(v, Enum) else v for v in value]
        return value

    @staticmethod
    def _from_row(table: _Table, row: dict[str, Any]) -> Any:
        kwargs: dict[str, Any] = {}
        for col in table.columns:
            value = row[col]
            if isinstance(value, uuid.UUID):
                value = str(value)
            elif isinstance(value, Decimal):
                value = float(value)
            kwargs[col] = value
        return table.cls(**kwargs)

    def _insert(self, table: _Table, obj: Any, *, savepoint: bool = False) -> Any:
        cols = [
            c
            for c in table.columns
            if not (c in table.db_default and getattr(obj, c) is None)
        ]
        query = sql.SQL("insert into {t} ({cols}) values ({vals}) returning {ret}").format(
            t=self._tbl(table),
            cols=self._cols(cols),
            vals=sql.SQL(", ").join([sql.Placeholder()] * len(cols)),
            ret=self._cols(table.columns),
        )
        require_aware_values({c: getattr(obj, c) for c in cols})
        params = [self._to_db(table, c, getattr(obj, c)) for c in cols]
        with self._cursor() as cur:
            if savepoint:
                # A failed insert must not poison an enclosing transaction().
                with cur.connection.transaction():
                    cur.execute(query, params)
                    row = cur.fetchone()
            else:
                cur.execute(query, params)
                row = cur.fetchone()
        return self._from_row(table, row)

    def _upsert(
        self, table: _Table, obj: Any, conflict: Sequence[str], update: Sequence[str]
    ) -> Any:
        """``insert ... on conflict (<conflict>) do update set <update> = excluded.<update>``.

        Columns outside ``update`` keep their stored value when the row already exists.
        """
        cols = [
            c
            for c in table.columns
            if not (c in table.db_default and getattr(obj, c) is None)
        ]
        query = sql.SQL(
            "insert into {t} ({cols}) values ({vals}) on conflict ({conflict}) do update set {sets} "
            "returning {ret}"
        ).format(
            t=self._tbl(table),
            cols=self._cols(cols),
            vals=sql.SQL(", ").join([sql.Placeholder()] * len(cols)),
            conflict=self._cols(conflict),
            sets=sql.SQL(", ").join(
                sql.SQL("{c} = excluded.{c}").format(c=sql.Identifier(c)) for c in update
            ),
            ret=self._cols(table.columns),
        )
        params = [self._to_db(table, c, getattr(obj, c)) for c in cols]
        try:
            rows = self._execute(query, params)
        except (CheckViolation, UniqueViolation) as e:  # a bad value, or a handle another account holds
            raise ValueError(str(e)) from e
        return self._from_row(table, rows[0])

    def _get(self, table: _Table, id: str) -> Any | None:
        uid = _as_uuid(id)
        if uid is None:
            return None
        query = sql.SQL("select {ret} from {t} where id = %s").format(
            ret=self._cols(table.columns), t=self._tbl(table)
        )
        rows = self._execute(query, [uid])
        return self._from_row(table, rows[0]) if rows else None

    def _update(self, table: _Table, id: str, kw: dict[str, Any]) -> Any:
        check_fields(table.cls, kw, "update")
        if "id" in kw:
            raise ValueError("id is immutable")
        require_aware_values(kw)
        uid = _as_uuid(id)
        if uid is None:
            raise KeyError(id)
        if not kw:
            row = self._get(table, id)
            if row is None:
                raise KeyError(id)
            return row
        query = sql.SQL("update {t} set {sets} where id = %s returning {ret}").format(
            t=self._tbl(table),
            sets=sql.SQL(", ").join(
                sql.SQL("{} = %s").format(sql.Identifier(c)) for c in kw
            ),
            ret=self._cols(table.columns),
        )
        params = [self._to_db(table, c, v) for c, v in kw.items()] + [uid]
        try:
            rows = self._execute(query, params)
        except CheckViolation as e:
            raise ValueError(str(e)) from e
        if not rows:
            raise KeyError(id)
        return self._from_row(table, rows[0])

    def _list(
        self,
        table: _Table,
        filters: dict[str, Any],
        order_by: Sequence[str],
    ) -> list[Any]:
        check_fields(table.cls, filters, "filter")
        conds: list[sql.Composable] = []
        params: list[Any] = []
        for col, value in filters.items():
            if value is None:
                conds.append(sql.SQL("{} is null").format(sql.Identifier(col)))
            else:
                conds.append(sql.SQL("{} = %s").format(sql.Identifier(col)))
                params.append(self._to_db(table, col, value))
        query = sql.SQL("select {ret} from {t}").format(
            ret=self._cols(table.columns), t=self._tbl(table)
        )
        if conds:
            query += sql.SQL(" where ") + sql.SQL(" and ").join(conds)
        query += sql.SQL(" order by ") + self._cols(order_by)
        return [self._from_row(table, r) for r in self._execute(query, params)]

    # ---- settings ----------------------------------------------------------

    def get_settings(self) -> Settings:
        # Inside a transaction, lock the row so concurrent reservations queue up.
        lock = sql.SQL(" for update") if self._in_transaction() else sql.SQL("")
        query = sql.SQL("select {ret} from {t} where id = 1{lock}").format(
            ret=self._cols(_SETTINGS.columns), t=self._tbl(_SETTINGS), lock=lock
        )
        return self._from_row(_SETTINGS, self._execute(query)[0])

    def set_settings(self, **kw: Any) -> Settings:
        check_fields(Settings, kw, "set_settings")
        if not kw:
            return self.get_settings()
        query = sql.SQL("update {t} set {sets} where id = 1 returning {ret}").format(
            t=self._tbl(_SETTINGS),
            sets=sql.SQL(", ").join(
                sql.SQL("{} = %s").format(sql.Identifier(c)) for c in kw
            ),
            ret=self._cols(_SETTINGS.columns),
        )
        params = [self._to_db(_SETTINGS, c, v) for c, v in kw.items()]
        try:
            rows = self._execute(query, params)
        except CheckViolation as e:
            raise ValueError(str(e)) from e
        return self._from_row(_SETTINGS, rows[0])

    # ---- ledger ------------------------------------------------------------

    def ledger_add(self, e: LedgerEntry) -> LedgerEntry:
        return self._insert(_LEDGER, e)

    def ledger_month(self, month: str) -> list[LedgerEntry]:
        return self._list(_LEDGER, {"month": month}, ["created_at", "id"])

    # ---- sources -----------------------------------------------------------

    def add_source(self, s: Source) -> Source:
        return self._insert(_SOURCES, s)

    def update_source(self, id: str, /, **kw: Any) -> Source:
        return self._update(_SOURCES, id, kw)

    def list_sources(self, **filters: Any) -> list[Source]:
        return self._list(_SOURCES, filters, ["created_at", "id"])

    # ---- clips -------------------------------------------------------------

    def add_clip(self, c: Clip) -> Clip:
        return self._insert(_CLIPS, c)

    def get_clip(self, id: str) -> Clip | None:
        return self._get(_CLIPS, id)

    def update_clip(self, id: str, /, **kw: Any) -> Clip:
        return self._update(_CLIPS, id, kw)

    def list_clips(self, **filters: Any) -> list[Clip]:
        return self._list(_CLIPS, filters, ["created_at", "id"])

    # ---- posts -------------------------------------------------------------

    def add_post(self, p: Post) -> Post:
        try:
            return self._insert(_POSTS, p, savepoint=True)
        except UniqueViolation as e:
            raise DuplicatePost(
                f"clip {p.clip_id} already has a post for account {p.account_id}"
            ) from e

    def claim_due_posts(self, now: datetime) -> list[Post]:
        require_aware(now, "claim_due_posts(now)")
        query = sql.SQL(
            "update {t} set status = 'posting', claimed_at = %s "
            "where status = 'scheduled' and scheduled_for <= %s "
            "returning {ret}"
        ).format(t=self._tbl(_POSTS), ret=self._cols(_POSTS.columns))
        posts = [self._from_row(_POSTS, r) for r in self._execute(query, [now, now])]
        return sorted(posts, key=lambda p: p.scheduled_for)

    def update_post(self, id: str, /, **kw: Any) -> Post:
        return self._update(_POSTS, id, kw)

    def list_posts(self, **filters: Any) -> list[Post]:
        return self._list(_POSTS, filters, ["scheduled_for", "id"])

    def delete_post(self, id: str, /) -> None:
        """Remove one post row (``studio publish resolve --drop``). ``KeyError`` when there is none."""
        uid = _as_uuid(id)
        if uid is None:
            raise KeyError(id)
        query = sql.SQL("delete from {t} where id = %s returning id").format(t=self._tbl(_POSTS))
        if not self._execute(query, [uid]):
            raise KeyError(id)

    # ---- metrics -----------------------------------------------------------

    def add_snapshot(self, s: Snapshot) -> Snapshot:
        return self._insert(_SNAPSHOTS, s)

    def snapshots_for(self, post_id: str) -> list[Snapshot]:
        uid = _as_uuid(post_id)
        if uid is None:
            return []
        return self._list(_SNAPSHOTS, {"post_id": uid}, ["captured_at"])

    # ---- characters and accounts -----------------------------------------

    def accounts(self, character_slug: str | None = None) -> list[Account]:
        filters = {} if character_slug is None else {"character_slug": character_slug}
        return self._list(_ACCOUNTS, filters, ["character_slug", "platform"])

    def update_account(self, id: str, /, **kw: Any) -> Account:
        return self._update(_ACCOUNTS, id, kw)

    def characters(self) -> list[Character]:
        return self._list(_CHARACTERS, {}, ["slug"])

    def upsert_character(self, c: Character) -> Character:
        return self._upsert(_CHARACTERS, c, ["slug"], ["name", "status", "bodies", "setup"])

    def upsert_account(self, a: Account) -> Account:
        # Needs the unique index of migration 0003. Only the identity is refreshed on conflict:
        # mode and dropin_share are operational state (autopilot toggle, Instagram guard).
        return self._upsert(
            _ACCOUNTS, a, ["character_slug", "platform"], ["handle", "postiz_integration_id"]
        )

    # ---- favourites --------------------------------------------------------

    def add_favorite(self, f: Favorite) -> Favorite:
        return self._insert(_FAVORITES, f)

    def get_favorite(self, id: str) -> Favorite | None:
        return self._get(_FAVORITES, id)

    def update_favorite(self, id: str, /, **kw: Any) -> Favorite:
        return self._update(_FAVORITES, id, kw)

    def list_favorites(self, **filters: Any) -> list[Favorite]:
        return self._list(_FAVORITES, filters, ["created_at", "id"])

    # ---- hits (migration 0016) ---------------------------------------------

    def upsert_hit(self, h: Hit) -> tuple[Hit, bool]:
        """One ``insert ... on conflict (url) do update`` with the rules of ``studio.store`` (``HIT_REFRESHED``,
        ``HIT_FIRST_FOUND``, ``HIT_RECOMPUTED``); ``status``, ``id`` and ``created_at`` are never touched on a conflict.
        ``(xmax = 0)`` tells an inserted row from an updated one."""
        cols = [c for c in _HITS.columns if not (c in _HITS.db_default and getattr(h, c) is None)]
        require_aware_values({c: getattr(h, c) for c in cols})
        sets = [sql.SQL("{c} = coalesce(excluded.{c}, h.{c})").format(c=sql.Identifier(c)) for c in HIT_REFRESHED]
        sets += [sql.SQL("{c} = coalesce(h.{c}, excluded.{c})").format(c=sql.Identifier(c)) for c in HIT_FIRST_FOUND]
        sets += [sql.SQL("{c} = excluded.{c}").format(c=sql.Identifier(c)) for c in HIT_RECOMPUTED]
        query = sql.SQL(
            "insert into {t} as h ({cols}) values ({vals}) on conflict ({url}) do update set {sets} "
            "returning {ret}, (xmax = 0) as inserted"
        ).format(
            t=self._tbl(_HITS),
            cols=self._cols(cols),
            vals=sql.SQL(", ").join([sql.Placeholder()] * len(cols)),
            url=sql.Identifier("url"),
            sets=sql.SQL(", ").join(sets),
            ret=sql.SQL(", ").join(sql.SQL("h.{}").format(sql.Identifier(c)) for c in _HITS.columns),
        )
        params = [self._to_db(_HITS, c, getattr(h, c)) for c in cols]
        try:
            rows = self._execute(query, params)
        except (CheckViolation, ForeignKeyViolation) as e:  # a value the table refuses, or an unknown character
            raise ValueError(str(e)) from e
        return self._from_row(_HITS, rows[0]), bool(rows[0]["inserted"])

    def get_hit(self, id: str) -> Hit | None:
        return self._get(_HITS, id)

    def update_hit(self, id: str, /, **kw: Any) -> Hit:
        return self._update(_HITS, id, kw)

    def list_hits(self, **filters: Any) -> list[Hit]:
        return self._list(_HITS, filters, ["created_at", "id"])

    # ---- scheduled-run log and weekly reviews ------------------------------

    def add_run(self, r: Run) -> Run:
        return self._insert(_RUNS, r)

    def list_runs(self, **filters: Any) -> list[Run]:
        return self._list(_RUNS, filters, ["started_at", "id"])

    def upsert_review(self, r: Review) -> Review:
        # Needs the unique index of migration 0006 on (week, character_slug). One statement, so two saves
        # of the same week cannot both insert; the stored id and created_at survive a rewrite.
        try:
            return self._upsert(_REVIEWS, r, ["week", "character_slug"], ["report_md", "bar_status"])
        except ForeignKeyViolation as e:  # an unknown character
            raise ValueError(str(e)) from e

    def list_reviews(self, **filters: Any) -> list[Review]:
        return self._list(_REVIEWS, filters, ["week", "character_slug", "id"])
