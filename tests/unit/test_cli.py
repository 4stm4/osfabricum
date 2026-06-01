from typer.testing import CliRunner

from apps.cli.main import GROUPS, app

runner = CliRunner()


def test_help_lists_all_top_level_commands() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for name in ["build", "plan", "prefetch", *GROUPS.keys()]:
        assert name in result.output


def test_version() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert "osfabricumctl" in result.output


def test_plan_command_exits_nonzero_without_db() -> None:
    # plan is a real command (M12); without a valid DB it exits non-zero
    result = runner.invoke(app, ["plan", "tinywifi/default", "--board", "rpi-zero-2w"])
    assert result.exit_code != 0


def test_group_help_lists_subcommands() -> None:
    result = runner.invoke(app, ["toolchain", "--help"])
    assert result.exit_code == 0
    for sub in ["add", "fetch", "verify", "list"]:
        assert sub in result.output
