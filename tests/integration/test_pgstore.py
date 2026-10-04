"""PostgresStore against a real Postgres. Skipped unless ``DATABASE_URL_TEST`` is set.

Run locally with a DSN for a Supabase (or Supabase-like) database where the connecting role
owns the objects it creates and the ``authenticated`` role and ``auth.jwt()`` exist, e.g.:

    DATABASE_URL_TEST='postgresql://postgres:...@db.<ref>.supabase.co:5432/postgres' \
        uv run pytest tests/integration -v

The fixture builds the full schema from ``supabase/migrations/0001_studio.sql`` with the
schema renamed to ``studio_test`` (it never touches ``studio``) and drops it afterwards.
"""

import os
import re
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

import psycopg
import pytest

from studio.models import (
    Body,
    Clip,
    ClipState,
    Favorite,
    LedgerEntry,
    Mode,
    Post,
    PostStatus,
    Snapshot,
    Source,
    SourceKind,
)
from studio.pgstore import PostgresStore
from studio.store import DuplicatePost

DSN = os.environ.get("DATABASE_URL_TEST")
pytestmark = pytest.mark.skipif(not DSN, reason="DATABASE_URL_TEST is not set")

SCHEMA = "studio_test"
MIGRATION = Path(__file__).resolve().parents[2] / "supabase" / "migrations" / "0001_studio.sql"


def _ddl() -> str:
    return re.sub(r"\bstudio\b", SCHEMA, MIGRATION.read_text())


@pytest.fixture
def store():
    with psycopg.connect(DSN, autocommit=True) as conn:
        conn.execute(f"drop schema if exists {SCHEMA} cascade")
        conn.execute(_ddl())
        conn.execute(f"insert into {SCHEMA}.characters (slug, name, bodies) values ('biscuit', 'Biscuit', '{{quadruped}}')")
        conn.execute(f"insert into {SCHEMA}.accounts (character_slug, platform, handle) values ('biscuit', 'tiktok', '@biscuit')")
        conn.execute(f"insert into {SCHEMA}.accounts (character_slug, platform, handle) values ('biscuit', 'instagram', 'biscuit.odd')")
    try:
        yield PostgresStore(DSN, schema=SCHEMA)
    finally:
        with psycopg.connect(DSN, autocommit=True) as conn:
            conn.execute(f"drop schema if exists {SCHEMA} cascade")


def _due_post(store: PostgresStore, account_id: str, now: datetime) -> Post:
    clip = store.add_clip(Clip(character_slug="biscuit", mode=Mode.recreate))
    return store.add_post(
        Post(clip_id=clip.id, account_id=account_id, scheduled_for=now - timedelta(minutes=1))
    )


def test_claim_is_atomic(store):
    now = datetime.now(timezone.utc)
    account = store.accounts("biscuit")[0]
    post = _due_post(store, account.id, now)

    barrier = threading.Barrier(2)
    results: list[list[Post]] = []

    def worker() -> None:
        barrier.wait()
        results.append(store.claim_due_posts(now))

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert sorted(len(r) for r in results) == [0, 1]  # exactly one claimer got it
    claimed = next(r for r in results if r)[0]
    assert claimed.id == post.id and claimed.status is PostStatus.posting
    assert store.list_posts()[0].status is PostStatus.posting
    assert store.claim_due_posts(now) == []


def test_claim_many_posts_never_double_claims(store):
    now = datetime.now(timezone.utc)
    account = store.accounts("biscuit")[0]
    posts = [_due_post(store, account.id, now) for _ in range(12)]

    claimed: list[Post] = []
    lock = threading.Lock()
    barrier = threading.Barrier(4)

    def worker() -> None:
        barrier.wait()
        for _ in range(4):
            got = store.claim_due_posts(now)
            with lock:
                claimed.extend(got)

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    ids = [p.id for p in claimed]
    assert len(ids) == len(set(ids)) == len(posts)  # every post claimed, none twice


def test_roundtrip_every_table(store):
    now = datetime.now(timezone.utc)
    by_platform = {a.platform.value: a for a in store.accounts("biscuit")}
    assert set(by_platform) == {"tiktok", "instagram"}
    tiktok = by_platform["tiktok"]
    assert tiktok.dropin_share == 0.7 and tiktok.mode == "approval"  # DB defaults (raw inserts)
    assert [c.slug for c in store.characters()] == ["biscuit"]
    assert store.characters()[0].bodies == [Body.quadruped]

    settings = store.get_settings()
    assert settings.monthly_cap_credits == 6000 and settings.cadence["biscuit"]["slot"] == "19:00"
    assert store.set_settings(kill_switch=True, monthly_cap_credits=300).kill_switch is True

    src = store.add_source(
        Source(kind=SourceKind.owner_inbox, body=Body.biped, bodies=1, duration_s=8.5, trend="x")
    )
    assert store.update_source(src.id, has_watermark=False, other_people=0).has_watermark is False
    assert [s.id for s in store.list_sources(kind="owner_inbox")] == [src.id]

    clip = store.add_clip(
        Clip(
            character_slug="biscuit", mode=Mode.dropin, source_id=src.id,
            hashtags=["#odd"], features={"hook_type": "reveal"}, qa={"t": "pass"},
        )
    )
    assert store.get_clip(clip.id) == clip
    store.update_clip(clip.id, state=ClipState.approved, credits_reserved=115)
    assert [c.id for c in store.list_clips(state=ClipState.approved, source_id=src.id)] == [clip.id]
    with pytest.raises(ValueError):
        store.update_clip(clip.id, state="not_a_state")  # CHECK violation surfaces as ValueError

    post = store.add_post(Post(clip_id=clip.id, account_id=tiktok.id, scheduled_for=now))
    with pytest.raises(DuplicatePost):
        store.add_post(Post(clip_id=clip.id, account_id=tiktok.id, scheduled_for=now))
    with store.transaction():  # a duplicate must not poison the enclosing transaction
        with pytest.raises(DuplicatePost):
            store.add_post(Post(clip_id=clip.id, account_id=tiktok.id, scheduled_for=now))
        store.update_post(post.id, attempts=1)
    assert store.list_posts(account_id=tiktok.id)[0].attempts == 1

    store.add_snapshot(Snapshot(post_id=post.id, captured_at=now, views=10))
    store.add_snapshot(Snapshot(post_id=post.id, captured_at=now + timedelta(hours=6), views=50, likes=5))
    snaps = store.snapshots_for(post.id)
    assert [s.views for s in snaps] == [10, 50] and snaps[0].likes is None

    store.ledger_add(LedgerEntry(clip_id=clip.id, month="2026-10", kind="reserve", credits=115))
    assert [e.credits for e in store.ledger_month("2026-10")] == [115]
    assert store.ledger_month("2026-11") == []

    fav = store.add_favorite(
        Favorite(url="https://www.tiktok.com/@x/video/1", platform="tiktok", views=1_000_000,
                 outlier_x=4.5, character_slug="biscuit", proposal={"mode": "recreate"},
                 scores={"virality": 90}, total_score=92.5)
    )
    assert store.get_favorite(fav.id) == fav and fav.total_score == 92.5 and fav.outlier_x == 4.5
    assert store.update_favorite(fav.id, status="approved").status == "approved"
    assert store.list_favorites(status="new") == []


def test_settings_row_is_locked_inside_a_transaction(store):
    """A second transaction reading settings waits until the first commits."""
    order: list[str] = []
    entered = threading.Event()

    def first() -> None:
        with store.transaction():
            store.get_settings()  # takes the row lock
            entered.set()
            threading.Event().wait(0.5)
            order.append("first-commit")

    def second() -> None:
        entered.wait()
        with store.transaction():
            store.get_settings()  # blocks until `first` commits
            order.append("second-read")

    threads = [threading.Thread(target=first), threading.Thread(target=second)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert order == ["first-commit", "second-read"]
