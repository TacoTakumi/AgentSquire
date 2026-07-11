"""T-02 / REQ-01..03: the squire root CLI, its agentsquire alias, and --version."""

from importlib.metadata import entry_points, version

import agentsquire
from agentsquire.console import main
from click.testing import CliRunner


def test_help_exits_zero_and_renders_the_root_group():
    # REQ-01: `squire --help` exits 0 and prints the root command group.
    result = CliRunner().invoke(main, ["--help"])
    assert result.exit_code == 0
    assert result.output.startswith("Usage:")
    assert "install agentsquire's own agent skills" in result.output


def test_version_prints_the_installed_agentsquire_version():
    # REQ-03: `squire --version` prints exactly importlib.metadata.version('agentsquire').
    result = CliRunner().invoke(main, ["--version"])
    assert result.exit_code == 0
    assert result.output.strip() == version("agentsquire")


def test_reported_version_equals_dunder_version():
    # REQ-03: the two declared version sources agree.
    assert version("agentsquire") == agentsquire.__version__


def test_both_console_scripts_resolve_to_the_same_callable():
    # REQ-01/REQ-02: squire and its agentsquire alias are the identical CLI.
    scripts = {
        ep.name: ep.value
        for ep in entry_points(group="console_scripts")
        if ep.name in ("squire", "agentsquire")
    }
    assert scripts == {
        "squire": "agentsquire.console:main",
        "agentsquire": "agentsquire.console:main",
    }


def test_alias_help_is_identical_below_the_usage_line():
    # REQ-02: `agentsquire --help` is the same root-group help as `squire --help`;
    # the two invocations differ only in the program name on the Usage line.
    runner = CliRunner()
    squire = runner.invoke(main, ["--help"], prog_name="squire").output.splitlines()
    alias = runner.invoke(main, ["--help"], prog_name="agentsquire").output.splitlines()
    assert squire[0].startswith("Usage: squire")
    assert alias[0].startswith("Usage: agentsquire")
    assert squire[1:] == alias[1:]
