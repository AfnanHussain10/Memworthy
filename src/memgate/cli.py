"""MemGate command-line interface."""

from __future__ import annotations

import typer

from memgate import __version__

app = typer.Typer(help="MemGate: decide what an AI system should remember.",
                  no_args_is_help=True, add_completion=False)


@app.command()
def version() -> None:
    """Print the MemGate version."""
    print(__version__)


def main() -> None:
    """Console-script entry point."""
    app()
