"""The ``studio`` CLI. Sub-apps are empty skeletons; later tasks fill them in."""

from __future__ import annotations

import typer

from studio import __version__, budget, clips, favorites, metrics, planning, publish, sources
from studio.media import master, qa

app = typer.Typer(
    name="studio",
    help="ODD EYES Character Studio: owns all pipeline state and deterministic steps.",
    no_args_is_help=True,
    add_completion=False,
)

# Sub-apps still to come (anonymous skeletons). A task that implements one removes its entry
# here and registers its module's own ``app`` instead, as ``budget`` does below.
SUBAPPS: dict[str, str] = {
    "review": "Weekly review: lift table and KPI bars.",
    "db": "Database utilities.",
}

app.add_typer(budget.app, name="budget")
app.add_typer(sources.app, name="source")
app.add_typer(favorites.app, name="fav")
app.add_typer(clips.app, name="clip")
app.add_typer(planning.app, name="plan")
app.add_typer(qa.app, name="qa")
app.add_typer(master.app, name="master")
app.add_typer(publish.app, name="publish")
app.add_typer(metrics.app, name="metrics")

for _name, _help in SUBAPPS.items():
    app.add_typer(typer.Typer(help=_help, no_args_is_help=True), name=_name)


@app.command()
def version() -> None:
    """Print the studio version."""
    typer.echo(__version__)
