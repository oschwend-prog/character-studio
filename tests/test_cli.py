from typer.testing import CliRunner

from studio.cli import app


def test_version_and_help():
    r = CliRunner().invoke(app, ["--help"])
    assert r.exit_code == 0 and "budget" in r.output and "clip" in r.output
    r = CliRunner().invoke(app, ["version"])
    assert r.exit_code == 0 and r.output.strip() == "0.1.0"


def test_all_subapps_registered():
    r = CliRunner().invoke(app, ["--help"])
    assert r.exit_code == 0
    for name in (
        "budget", "source", "fav", "clip", "plan", "qa", "master",
        "publish", "metrics", "review", "seed", "db", "version",
    ):
        assert name in r.output, name
