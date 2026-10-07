"""Integration-test housekeeping: no pg_cron job outlives the test schema.

The integration fixtures build every migration with the schema renamed to ``studio_test``. On a database that has pg_cron
(Supabase does), migration 0014 then schedules a job named ``studio_test-publish-tick`` that calls ``studio_test.publish_tick()``;
the fixtures drop the schema afterwards, so the job would be left failing every 5 minutes on the shared project. The real job
``studio-publish-tick`` is never touched (the rename changes its name too). This removes the test job before and after the session.
"""

import os

import psycopg
import pytest

DSN = os.environ.get("DATABASE_URL_TEST")
TEST_JOB = "studio_test-publish-tick"


def _unschedule_test_job() -> None:
    if not DSN:
        return
    with psycopg.connect(DSN, autocommit=True) as conn:
        if conn.execute("select to_regclass('cron.job') is not null").fetchone()[0]:
            conn.execute("select cron.unschedule(jobid) from cron.job where jobname = %s", [TEST_JOB])


@pytest.fixture(scope="session", autouse=True)
def _no_leftover_cron_job():
    _unschedule_test_job()
    yield
    _unschedule_test_job()
