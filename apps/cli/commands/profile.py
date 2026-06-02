"""``osfabricumctl profile`` — Profile Designer CLI (M27).

A thin client over ``osfabricum.profile``. References to the universal entities
are given as ``--set field=name`` (e.g. ``--set class=router --set
package_set=core``).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Any, NoReturn

import typer
import yaml
from rich.console import Console
from rich.table import Table

from osfabricum import profile as svc
from osfabricum.profile.schema import REF_FIELDS

profile_app = typer.Typer(help="Create and manage profiles (M27)", no_args_is_help=True)

_DbUrl = Annotated[
    str | None, typer.Option("--db-url", envvar="OSFABRICUM_DB_URL", help="DB URL override")
]
_Set = Annotated[
    list[str] | None,
    typer.Option("--set", "-s", help="Reference as field=name (repeatable)"),
]


def _fail(message: str) -> NoReturn:
    typer.secho(f"Error: {message}", fg=typer.colors.RED, err=True)
    raise typer.Exit(code=1)


def _parse_refs(pairs: list[str] | None) -> dict[str, str]:
    refs: dict[str, str] = {}
    for pair in pairs or []:
        if "=" not in pair:
            _fail(f"--set expects field=name, got {pair!r}")
        field, value = pair.split("=", 1)
        if field not in REF_FIELDS:
            _fail(f"unknown field {field!r}; valid: {', '.join(sorted(REF_FIELDS))}")
        refs[field] = value
    return refs


def _parse_inputs(text: str | None) -> dict[str, Any] | None:
    if text is None:
        return None
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        _fail(f"--inputs must be JSON: {exc}")
    if not isinstance(data, dict):
        _fail("--inputs must be a JSON object")
    return data


def _print_profile(data: dict[str, Any]) -> None:
    console = Console()
    console.print(
        f"[bold]{data['distribution']}/{data['name']}[/bold]"
        + (f"  (inherits {data['inherits']})" if data.get("inherits") else "")
    )
    tbl = Table("Field", "Value", title="Selections")
    for field in REF_FIELDS:
        if data.get(field):
            tbl.add_row(field, str(data[field]))
    if data.get("inputs"):
        tbl.add_row("inputs", json.dumps(data["inputs"]))
    console.print(tbl)


@profile_app.command("list")
def list_cmd(distribution: str, db_url: _DbUrl = None) -> None:
    """List profiles of a distribution."""
    try:
        rows = svc.list_profiles(distribution, db_url=db_url)
    except ValueError as exc:
        _fail(str(exc))
    tbl = Table("Name", "Inherits", "Class", "Package set", title=f"{distribution} profiles")
    for p in rows:
        tbl.add_row(
            p["name"], p.get("inherits") or "—", p.get("class") or "—", p.get("package_set") or "—"
        )
    Console().print(tbl)


@profile_app.command("show")
def show_cmd(distribution: str, name: str, db_url: _DbUrl = None) -> None:
    """Show a profile and its selections."""
    try:
        _print_profile(svc.get_profile(distribution, name, db_url=db_url))
    except ValueError as exc:
        _fail(str(exc))


@profile_app.command("create")
def create_cmd(
    distribution: str,
    name: str,
    inherits: Annotated[str | None, typer.Option("--inherits")] = None,
    sets: _Set = None,
    inputs: Annotated[str | None, typer.Option("--inputs", help="JSON object")] = None,
    db_url: _DbUrl = None,
) -> None:
    """Create a profile (references via --set field=name)."""
    try:
        data = svc.create_profile(
            distribution=distribution,
            name=name,
            inherits=inherits,
            refs=_parse_refs(sets),
            inputs=_parse_inputs(inputs),
            db_url=db_url,
        )
    except ValueError as exc:
        _fail(str(exc))
    typer.secho(f"Created profile '{distribution}/{name}'", fg=typer.colors.GREEN)
    _print_profile(data)


@profile_app.command("edit")
def edit_cmd(
    distribution: str,
    name: str,
    inherits: Annotated[str | None, typer.Option("--inherits")] = None,
    sets: _Set = None,
    inputs: Annotated[str | None, typer.Option("--inputs", help="JSON object")] = None,
    db_url: _DbUrl = None,
) -> None:
    """Update a profile's references / inherits / inputs."""
    kwargs: dict[str, Any] = {}
    if sets:
        kwargs["refs"] = _parse_refs(sets)
    if inherits is not None:
        kwargs["inherits"] = inherits
    if inputs is not None:
        kwargs["inputs"] = _parse_inputs(inputs)
    if not kwargs:
        _fail("nothing to update (pass --set / --inherits / --inputs)")
    try:
        data = svc.update_profile(distribution, name, db_url=db_url, **kwargs)
    except ValueError as exc:
        _fail(str(exc))
    typer.secho(f"Updated profile '{distribution}/{name}'", fg=typer.colors.GREEN)
    _print_profile(data)


@profile_app.command("clone")
def clone_cmd(distribution: str, name: str, new_name: str, db_url: _DbUrl = None) -> None:
    """Clone a profile under a new name (same distribution)."""
    try:
        svc.clone_profile(distribution, name, new_name, db_url=db_url)
    except ValueError as exc:
        _fail(str(exc))
    typer.secho(f"Cloned '{distribution}/{name}' -> '{new_name}'", fg=typer.colors.GREEN)


@profile_app.command("delete")
def delete_cmd(
    distribution: str,
    name: str,
    yes: Annotated[bool, typer.Option("--yes", "-y")] = False,
    db_url: _DbUrl = None,
) -> None:
    """Delete a profile."""
    if not yes and not typer.confirm(f"Delete profile '{distribution}/{name}'?"):
        raise typer.Abort()
    try:
        svc.delete_profile(distribution, name, db_url=db_url)
    except ValueError as exc:
        _fail(str(exc))
    typer.secho(f"Deleted profile '{distribution}/{name}'", fg=typer.colors.GREEN)


@profile_app.command("version")
def version_cmd(distribution: str, name: str, db_url: _DbUrl = None) -> None:
    """Snapshot the current profile state as a new version."""
    try:
        out = svc.create_version(distribution, name, db_url=db_url)
    except ValueError as exc:
        _fail(str(exc))
    typer.secho(
        f"Created version {out['version']} of '{distribution}/{name}'", fg=typer.colors.GREEN
    )


@profile_app.command("versions")
def versions_cmd(distribution: str, name: str, db_url: _DbUrl = None) -> None:
    """List a profile's versions."""
    try:
        rows = svc.list_versions(distribution, name, db_url=db_url)
    except ValueError as exc:
        _fail(str(exc))
    tbl = Table("Version", "Created", title=f"{distribution}/{name} versions")
    for r in rows:
        tbl.add_row(str(r["version"]), r["created_at"])
    Console().print(tbl)


@profile_app.command("diff")
def diff_cmd(distribution: str, a: str, b: str, db_url: _DbUrl = None) -> None:
    """Diff two profiles in the same distribution."""
    try:
        result = svc.diff_profiles(distribution, a, b, db_url=db_url)
    except ValueError as exc:
        _fail(str(exc))
    changes = result["changes"]
    if not changes:
        typer.secho("profiles are identical", fg=typer.colors.GREEN)
        return
    tbl = Table("Field", a, b, title=f"diff {distribution}: {a} ↔ {b}")
    for field, vals in changes.items():
        tbl.add_row(field, json.dumps(vals["a"]), json.dumps(vals["b"]))
    Console().print(tbl)


@profile_app.command(name="import")
def import_cmd(
    file: Annotated[Path, typer.Option("--file", "-f", help="Profile YAML to import")],
    overwrite: Annotated[bool, typer.Option("--overwrite")] = False,
    db_url: _DbUrl = None,
) -> None:
    """Import a profile from a YAML document."""
    if not file.exists():
        _fail(f"file not found: {file}")
    with file.open() as fh:
        data = yaml.safe_load(fh)
    try:
        result = svc.import_profile(data, db_url=db_url, overwrite=overwrite)
    except ValueError as exc:
        _fail(str(exc))
    typer.secho(
        f"Imported profile '{result['distribution']}/{result['name']}'", fg=typer.colors.GREEN
    )


@profile_app.command("export")
def export_cmd(
    distribution: str,
    name: str,
    file: Annotated[Path | None, typer.Option("--file", "-f")] = None,
    db_url: _DbUrl = None,
) -> None:
    """Export a profile to a YAML document (stdout or --file)."""
    try:
        doc = svc.export_profile(distribution, name, db_url=db_url)
    except ValueError as exc:
        _fail(str(exc))
    text = yaml.safe_dump(doc, sort_keys=False)
    if file is not None:
        file.write_text(text)
        typer.secho(f"Exported -> {file}", fg=typer.colors.GREEN, err=True)
    else:
        typer.echo(text)
