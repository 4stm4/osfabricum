"""Real implementations of ``osfabricumctl package`` subcommands (M9)."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from osfabricum.packaging.builder import build_ofpkg
from osfabricum.packaging.installer import install_ofpkg, verify_ofpkg

package_app = typer.Typer(help="Build and inspect packages", no_args_is_help=True)

console = Console()


# ---------------------------------------------------------------------------
# package build
# ---------------------------------------------------------------------------


@package_app.command("build")
def package_build(
    name: Annotated[str, typer.Argument(help="Package name")],
    version: Annotated[str, typer.Option("--version", "-v", help="Package version")],
    arch: Annotated[str, typer.Option("--arch", "-a", help="Target architecture")],
    destdir: Annotated[
        Path,
        typer.Option(
            "--destdir",
            "-d",
            help="Staging root (DESTDIR) produced by the build recipe",
            exists=True,
            file_okay=False,
            dir_okay=True,
        ),
    ],
    output_dir: Annotated[
        Path,
        typer.Option("--output-dir", "-o", help="Output directory for the .ofpkg file"),
    ] = Path("."),
    description: Annotated[str, typer.Option("--description", help="Package description")] = "",
    license_spdx: Annotated[
        str, typer.Option("--license", help="SPDX license expression")
    ] = "NOASSERTION",
    build_system: Annotated[
        str | None, typer.Option("--build-system", help="Build system used")
    ] = None,
    source_hash: Annotated[
        str | None, typer.Option("--source-hash", help="SHA-256 of upstream source")
    ] = None,
    recipe_hash: Annotated[
        str | None, typer.Option("--recipe-hash", help="SHA-256 of build recipe")
    ] = None,
) -> None:
    """Build a .ofpkg archive from a staging directory (DESTDIR)."""
    try:
        pkg_path = build_ofpkg(
            name=name,
            version=version,
            arch=arch,
            destdir=destdir,
            output_dir=output_dir,
            description=description,
            license_spdx=license_spdx,
            build_system=build_system,
            source_hash=source_hash,
            recipe_hash=recipe_hash,
        )
    except Exception as exc:
        typer.secho(f"ERROR: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc

    typer.echo(str(pkg_path))


# ---------------------------------------------------------------------------
# package verify
# ---------------------------------------------------------------------------


@package_app.command("verify")
def package_verify(
    pkg_path: Annotated[Path, typer.Argument(help="Path to .ofpkg file")],
) -> None:
    """Verify checksums, manifest schema, and SBOM of a .ofpkg file."""
    try:
        manifest = verify_ofpkg(pkg_path)
    except ValueError as exc:
        typer.secho(f"FAILED: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc

    tbl = Table("Field", "Value", title=f"Package: {pkg_path.name}")
    for key in ("name", "version", "arch", "license", "description", "build_system"):
        value = manifest.get(key)
        if value is not None:
            tbl.add_row(key, str(value))
    console.print(tbl)
    typer.secho("OK: package is valid", fg=typer.colors.GREEN)


# ---------------------------------------------------------------------------
# package install
# ---------------------------------------------------------------------------


@package_app.command("install")
def package_install(
    pkg_path: Annotated[Path, typer.Argument(help="Path to .ofpkg file")],
    prefix: Annotated[
        Path,
        typer.Option("--prefix", "-p", help="Installation prefix"),
    ] = Path("/"),
) -> None:
    """Verify and install a .ofpkg into a prefix directory."""
    try:
        install_ofpkg(pkg_path, prefix)
    except ValueError as exc:
        typer.secho(f"FAILED: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc

    typer.secho(f"Installed {pkg_path.name} → {prefix}", fg=typer.colors.GREEN)


# ---------------------------------------------------------------------------
# package list / show  (stubs — full implementation in later milestones)
# ---------------------------------------------------------------------------


@package_app.command("list")
def package_list() -> None:
    """List packages registered in the catalog (not yet implemented)."""
    typer.secho("`package list` is not implemented yet", fg=typer.colors.YELLOW, err=True)
    raise typer.Exit(code=1)


@package_app.command("show")
def package_show(
    name: Annotated[str, typer.Argument(help="Package name")],
) -> None:
    """Show details for a registered package (not yet implemented)."""
    typer.secho("`package show` is not implemented yet", fg=typer.colors.YELLOW, err=True)
    raise typer.Exit(code=1)
