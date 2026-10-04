import json
from datetime import datetime, timezone

import pytest
import typer

from studio import cli_support
from studio.cli_support import EXIT_USAGE, emit, fail, open_store
from studio.models import Mode
from studio.pgstore import PostgresStore


def test_open_store_without_database_url_exits_2_with_a_clear_message(monkeypatch, capsys):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(typer.Exit) as exc:
        open_store()
    assert exc.value.exit_code == EXIT_USAGE == 2
    assert "DATABASE_URL" in capsys.readouterr().err


def test_open_store_with_database_url_returns_a_postgres_store(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pw@localhost:5432/db")
    assert isinstance(open_store(), PostgresStore)  # constructing never connects


def test_fail_prints_to_stderr_and_exits_2(capsys):
    with pytest.raises(typer.Exit) as exc:
        fail("nope")
    assert exc.value.exit_code == 2
    captured = capsys.readouterr()
    assert captured.err == "error: nope\n" and captured.out == ""


def test_emit_writes_json_with_enums_and_datetimes(capsys):
    emit({"mode": Mode.dropin, "at": datetime(2026, 10, 6, 12, 0, tzinfo=timezone.utc), "n": [1, 2]})
    assert json.loads(capsys.readouterr().out) == {
        "mode": "dropin",
        "at": "2026-10-06T12:00:00+00:00",
        "n": [1, 2],
    }


def test_emit_handles_lists_and_dataclasses(capsys):
    from studio.models import Character

    emit([Character(slug="biscuit", name="Biscuit", bodies=["quadruped"])])
    assert json.loads(capsys.readouterr().out) == [
        {"slug": "biscuit", "name": "Biscuit", "status": "designing", "bodies": ["quadruped"]}
    ]


def test_budget_uses_the_shared_helpers():
    from studio import budget

    assert budget.open_store is cli_support.open_store
    assert budget.fail is cli_support.fail
