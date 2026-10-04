"""Budget reservations against a real Postgres. Skipped unless ``DATABASE_URL_TEST`` is set.

Same setup as ``test_pgstore.py`` (the full migration under the schema ``studio_test``, dropped
afterwards); see its docstring for the DSN requirements. The fixture is repeated here so the file
stands alone.
"""

import os
import re
import threading
from datetime import datetime
from pathlib import Path

import psycopg
import pytest

from studio.budget import BudgetRefused, NoOpenReservation, committed, month_key, reserve, settle
from studio.config import LONDON
from studio.models import Clip, Mode
from studio.pgstore import PostgresStore

DSN = os.environ.get("DATABASE_URL_TEST")
pytestmark = pytest.mark.skipif(not DSN, reason="DATABASE_URL_TEST is not set")

SCHEMA = "studio_test"
MIGRATION = Path(__file__).resolve().parents[2] / "supabase" / "migrations" / "0001_studio.sql"


@pytest.fixture
def store():
    ddl = re.sub(r"\bstudio\b", SCHEMA, MIGRATION.read_text())
    with psycopg.connect(DSN, autocommit=True) as conn:
        conn.execute(f"drop schema if exists {SCHEMA} cascade")
        conn.execute(ddl)
        conn.execute(
            f"insert into {SCHEMA}.characters (slug, name, bodies) "
            "values ('biscuit', 'Biscuit', '{quadruped}')"
        )
    try:
        yield PostgresStore(DSN, schema=SCHEMA)
    finally:
        with psycopg.connect(DSN, autocommit=True) as conn:
            conn.execute(f"drop schema if exists {SCHEMA} cascade")


def _clips(store: PostgresStore, n: int) -> list[Clip]:
    return [store.add_clip(Clip(character_slug="biscuit", mode=Mode.recreate)) for _ in range(n)]


def _race(jobs) -> list:
    """Run the callables on parallel threads released together; return each result or exception."""
    barrier = threading.Barrier(len(jobs))
    outcomes: list = []
    lock = threading.Lock()

    def worker(job) -> None:
        barrier.wait()
        try:
            result = job()
        except Exception as e:  # noqa: BLE001 - the test inspects the type
            result = e
        with lock:
            outcomes.append(result)

    threads = [threading.Thread(target=worker, args=(job,)) for job in jobs]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return outcomes


def test_parallel_reserves_respect_cap(store):
    store.set_settings(monthly_cap_credits=150)
    now = datetime.now(LONDON)
    a, b = _clips(store, 2)

    outcomes = _race([lambda: reserve(store, a.id, 110, now), lambda: reserve(store, b.id, 110, now)])

    refused = [o for o in outcomes if isinstance(o, BudgetRefused)]
    assert len(refused) == 1 and refused[0].reason == "over_cap", outcomes
    assert len(outcomes) == 2 and sum(not isinstance(o, Exception) for o in outcomes) == 1, outcomes
    assert committed(store, month_key(now)) == 110
    assert len(store.ledger_month(month_key(now))) == 1


def test_many_parallel_reserves_never_pass_the_cap(store):
    store.set_settings(monthly_cap_credits=350)
    now = datetime.now(LONDON)
    clips = _clips(store, 8)

    outcomes = _race([lambda c=c: reserve(store, c.id, 110, now) for c in clips])

    assert all(isinstance(o, BudgetRefused) or not isinstance(o, Exception) for o in outcomes), outcomes
    assert sum(not isinstance(o, Exception) for o in outcomes) == 3  # 3 x 110 = 330 <= 350 < 440
    assert committed(store, month_key(now)) == 330


def test_parallel_settles_of_one_clip_book_the_cost_once(store):
    now = datetime.now(LONDON)
    (clip,) = _clips(store, 1)
    reserve(store, clip.id, 110, now)

    outcomes = _race([lambda: settle(store, clip.id, 99, now) for _ in range(3)])

    assert sum(not isinstance(o, Exception) for o in outcomes) == 1, outcomes
    assert all(isinstance(o, NoOpenReservation) for o in outcomes if isinstance(o, Exception))
    assert committed(store, month_key(now)) == 99
