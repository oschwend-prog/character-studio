"""The ``studio`` CLI. Sub-apps are empty skeletons; later tasks fill them in."""

from __future__ import annotations

import typer

from studio import __version__

app = typer.Typer(
    name="studio",
    help="ODD EYES Character Studio: owns all pipeline state and deterministic steps.",
    no_args_is_help=True,
    add_completion=False,
)

SUBAPPS: dict[str, str] = {
    "budget": "Credit budget: reserve, settle, release, cap, kill switch.",
    "source": "Source library: add, check, eligibility, ranking.",
    "clip": "Clip state machine and feature tags.",
    "plan": "Daily plan: mode choice and posting slots.",
    "qa": "Technical and visual QA of rendered clips.",
    "master": "Master a clip to the 1080x1920 delivery spec.",
    "publish": "Publish due clips via Postiz.",
    "metrics": "Ingest metric snapshots and compute outlier_x.",
    "review": "Weekly review: lift table and KPI bars.",
    "db": "Database utilities.",
}

for _name, _help in SUBAPPS.items():
    app.add_typer(typer.Typer(help=_help, no_args_is_help=True), name=_name)


@app.command()
def version() -> None:
    """Print the studio version."""
    typer.echo(__version__)
