"""``osfabricumctl users`` — Users / Groups / Credentials / Secrets Designer CLI (M44)."""

from __future__ import annotations

import json
from typing import Annotated, Any, NoReturn

import typer
from rich.console import Console
from rich.table import Table

from osfabricum import users as us

users_app = typer.Typer(
    help="Manage OS user / group / secret profiles (M44)", no_args_is_help=True
)

_DbUrl = Annotated[
    str | None, typer.Option("--db-url", envvar="OSFABRICUM_DB_URL", help="DB URL override")
]

_console = Console()


def _fail(message: str) -> NoReturn:
    typer.secho(f"Error: {message}", fg=typer.colors.RED, err=True)
    raise typer.Exit(code=1)


def _print_json(data: Any) -> None:
    _console.print_json(json.dumps(data, default=str))


@users_app.command("shell-list")
def shell_list(db_url: _DbUrl = None) -> None:
    """List seeded login shell paths."""
    items = us.list_user_shell_kinds(db_url=db_url)
    t = Table(title="Login Shell Kinds")
    t.add_column("#", style="dim")
    t.add_column("Path")
    t.add_column("Description")
    for k in items:
        t.add_row(str(k["display_order"]), k["path"], k["description"])
    _console.print(t)


@users_app.command("list")
def list_profiles(
    distribution_id: Annotated[
        str | None, typer.Option("--distribution-id", "-d")
    ] = None,
    db_url: _DbUrl = None,
) -> None:
    """List user profiles."""
    profiles = us.list_user_profiles(distribution_id, db_url=db_url)
    t = Table(title="User Profiles")
    t.add_column("ID")
    t.add_column("Name")
    t.add_column("Distribution")
    t.add_column("Rendered")
    for p in profiles:
        t.add_row(
            p["id"],
            p["name"],
            p["distribution_id"] or "—",
            "✓" if p["content_hash"] else "",
        )
    _console.print(t)


@users_app.command("create")
def create_profile(
    name: Annotated[str, typer.Argument(help="Profile name")],
    distribution_id: Annotated[str | None, typer.Option("--distribution-id", "-d")] = None,
    db_url: _DbUrl = None,
) -> None:
    """Create a new user profile."""
    try:
        result = us.create_user_profile(name, distribution_id=distribution_id, db_url=db_url)
    except ValueError as exc:
        _fail(str(exc))
    _print_json(result)


@users_app.command("show")
def show_profile(
    profile_id: Annotated[str, typer.Argument(help="Profile ID")],
    db_url: _DbUrl = None,
) -> None:
    """Show full details of a user profile (groups, users, secrets)."""
    try:
        result = us.get_user_profile(profile_id, db_url=db_url)
    except ValueError as exc:
        _fail(str(exc))
    _print_json(result)


@users_app.command("update")
def update_profile(
    profile_id: Annotated[str, typer.Argument(help="Profile ID")],
    name: Annotated[str | None, typer.Option("--name")] = None,
    db_url: _DbUrl = None,
) -> None:
    """Rename a user profile (clears rendered cache)."""
    try:
        result = us.update_user_profile(profile_id, name=name, db_url=db_url)
    except ValueError as exc:
        _fail(str(exc))
    _print_json(result)


@users_app.command("group-add")
def group_add(
    profile_id: Annotated[str, typer.Argument(help="Profile ID")],
    name: Annotated[str, typer.Option("--name", "-n")],
    gid: Annotated[int | None, typer.Option("--gid")] = None,
    is_system: Annotated[bool, typer.Option("--system")] = False,
    description: Annotated[str, typer.Option("--description")] = "",
    db_url: _DbUrl = None,
) -> None:
    """Add an OS group to a profile."""
    try:
        result = us.add_os_group(
            profile_id,
            name,
            gid=gid,
            is_system=is_system,
            description=description,
            db_url=db_url,
        )
    except ValueError as exc:
        _fail(str(exc))
    _print_json(result)


@users_app.command("user-add")
def user_add(
    profile_id: Annotated[str, typer.Argument(help="Profile ID")],
    username: Annotated[str, typer.Option("--username", "-u")],
    uid: Annotated[int | None, typer.Option("--uid")] = None,
    primary_group: Annotated[str, typer.Option("--primary-group", "-g")] = "users",
    home_dir: Annotated[str | None, typer.Option("--home")] = None,
    shell: Annotated[str, typer.Option("--shell")] = "/bin/bash",
    gecos: Annotated[str, typer.Option("--gecos")] = "",
    is_system: Annotated[bool, typer.Option("--system")] = False,
    is_locked: Annotated[bool, typer.Option("--locked")] = False,
    db_url: _DbUrl = None,
) -> None:
    """Add an OS user account to a profile."""
    try:
        result = us.add_os_user(
            profile_id,
            username,
            uid=uid,
            primary_group=primary_group,
            home_dir=home_dir,
            shell=shell,
            gecos=gecos,
            is_system=is_system,
            is_locked=is_locked,
            db_url=db_url,
        )
    except ValueError as exc:
        _fail(str(exc))
    _print_json(result)


@users_app.command("supp-group-add")
def supp_group_add(
    user_id: Annotated[str, typer.Argument(help="User ID")],
    group_name: Annotated[str, typer.Option("--group", "-g")],
    db_url: _DbUrl = None,
) -> None:
    """Add a supplementary group to an OS user."""
    try:
        result = us.add_supplementary_group(user_id, group_name, db_url=db_url)
    except ValueError as exc:
        _fail(str(exc))
    _print_json(result)


@users_app.command("secret-add")
def secret_add(
    profile_id: Annotated[str, typer.Argument(help="Profile ID")],
    name: Annotated[str, typer.Option("--name", "-n")],
    kind: Annotated[str, typer.Option("--kind", "-k")],
    description: Annotated[str, typer.Option("--description")] = "",
    masked_value: Annotated[str | None, typer.Option("--masked-value")] = None,
    is_required: Annotated[bool, typer.Option("--required/--optional")] = True,
    db_url: _DbUrl = None,
) -> None:
    """Register a named build-time secret reference."""
    try:
        result = us.add_secret_variable(
            profile_id,
            name,
            kind,
            description=description,
            masked_value=masked_value,
            is_required=is_required,
            db_url=db_url,
        )
    except ValueError as exc:
        _fail(str(exc))
    _print_json(result)


@users_app.command("render")
def render(
    profile_id: Annotated[str, typer.Argument(help="Profile ID")],
    db_url: _DbUrl = None,
) -> None:
    """Generate /etc/passwd, /etc/group, secrets manifest and store on profile."""
    try:
        result = us.render_user_config(profile_id, db_url=db_url)
    except ValueError as exc:
        _fail(str(exc))
    _console.print(f"[green]✓[/green] content_hash: {result['content_hash']}")
    _console.print(
        f"   users={result['user_count']}  "
        f"groups={result['group_count']}  "
        f"secrets={result['secret_count']}"
    )
    _console.rule("/etc/passwd")
    _console.print(result["rendered_passwd"])
    _console.rule("/etc/group")
    _console.print(result["rendered_group"])
    _console.rule("secrets manifest")
    _console.print(result["rendered_secrets_manifest"])
