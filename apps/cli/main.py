"""``osfabricumctl`` — the OSFabricum operator CLI.

M1 registers the full top-level command surface from ROADMAP section 20 so
``--help`` is complete. Individual commands are stubs that report they are not
implemented yet; they gain behaviour in their respective milestones.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated

import typer

from apps.cli.commands.catalog import catalog_app
from osfabricum import __version__

# group name -> (help text, subcommand names)
GROUPS: dict[str, tuple[str, list[str]]] = {
    "builds": (
        "Inspect and manage builds",
        ["list", "show", "logs", "cancel", "reproduce", "diff"],
    ),
    "package": ("Build and inspect packages", ["build", "list", "show", "verify"]),
    "kernel": ("Build and inspect kernels", ["build", "list", "show"]),
    "toolchain": ("Manage cross-compilation toolchains", ["add", "fetch", "verify", "list"]),
    "artifacts": (
        "Browse the artifact store",
        ["list", "show", "download", "verify", "pin", "unpin"],
    ),
    "store": ("Artifact store maintenance", ["stats", "verify", "gc"]),
    "cache": ("Build cache maintenance", ["stats", "verify", "gc"]),
    "workers": ("Inspect worker inventory", ["list", "show", "disable", "enable"]),
    "flash": ("Flash images to devices", ["list-devices", "image", "verify"]),
    "test": ("Run image tests", ["run", "list-suites"]),
    "releases": ("Manage releases and promotion", ["list", "show", "promote", "publish"]),
}


def _not_implemented(path: str) -> None:
    typer.secho(f"`osfabricumctl {path}` is not implemented yet", fg=typer.colors.YELLOW, err=True)
    raise typer.Exit(code=1)


def _make_stub(path: str) -> Callable[[], None]:
    def _stub() -> None:
        _not_implemented(path)

    return _stub


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"osfabricumctl {__version__}")
        raise typer.Exit()


app = typer.Typer(
    help="osfabricumctl — OSFabricum operator CLI",
    no_args_is_help=True,
    add_completion=False,
)


@app.callback()
def _root(
    version: Annotated[
        bool,
        typer.Option(
            "--version", callback=_version_callback, is_eager=True, help="Show version and exit"
        ),
    ] = False,
) -> None:
    """OSFabricum operator CLI."""


@app.command()
def build(
    target: Annotated[str, typer.Argument(help="<distribution>/<profile>")],
    board: Annotated[str, typer.Option("--board", help="Target board")],
) -> None:
    """Start a full build pipeline."""
    _not_implemented(f"build {target} --board {board}")


@app.command()
def plan(
    target: Annotated[str, typer.Argument(help="<distribution>/<profile>")],
    board: Annotated[str, typer.Option("--board", help="Target board")],
) -> None:
    """Resolve and display a build plan without building."""
    _not_implemented(f"plan {target} --board {board}")


@app.command()
def prefetch(
    target: Annotated[str, typer.Argument(help="<distribution>/<profile>")],
    board: Annotated[str, typer.Option("--board", help="Target board")],
) -> None:
    """Download all sources and toolchains for a build plan."""
    _not_implemented(f"prefetch {target} --board {board}")


def _register_groups() -> None:
    for name, (help_text, commands) in GROUPS.items():
        group = typer.Typer(help=help_text, no_args_is_help=True)
        for cmd in commands:
            group.command(name=cmd)(_make_stub(f"{name} {cmd}"))
        app.add_typer(group, name=name)
    app.add_typer(catalog_app, name="catalog")


_register_groups()


def main() -> None:
    app()


if __name__ == "__main__":
    main()
