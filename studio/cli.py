"""The ``studio`` CLI. Sub-apps are empty skeletons; later tasks fill them in."""

from __future__ import annotations

import typer

from studio import __version__, budget, favorites, sources

app = typer.Typer(
    name="studio",
    help="ODD EYES Character Studio: owns all pipeline state and deterministic steps.",
    no_args_is_help=True,
    add_completion=False,
)

# Sub-apps still to come (anonymous skeletons). A task that implements one removes its entry
# here and registers its module's own ``app`` instead, as ``budget`` does below.
SUBAPPS: dict[str, str] = {
    "clip": "Clip state machine and feature tags.",
    "plan": "Daily plan: mode choice and posting slots.",
    "qa": "Technical and visual QA of rendered clips.",
    "master": "Master a clip to the 1080x1920 delivery spec.",
    "publish": "Publish due clips via Postiz.",
    "metrics": "Ingest metric snapshots and compute outlier_x.",
    "review": "Weekly review: lift table and KPI bars.",
    "db": "Database utilities.",
}

app.add_typer(budget.app, name="budget")
app.add_typer(sources.app, name="source")
app.add_typer(favorites.app, name="fav")

for _name, _help in SUBAPPS.items():
    app.add_typer(typer.Typer(help=_help, no_args_is_help=True), name=_name)


@app.command()
def version() -> None:
    """Print the studio version."""
    typer.echo(__version__)
