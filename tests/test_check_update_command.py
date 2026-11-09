"""check_update_command: the mountable check-update verb.

Every test replaces ``agentsquire._pypi.fetch``; no test opens a connection.
The cache root is a temp directory for every test.
"""

import ast
import inspect
import json
import sys
import textwrap
import urllib.error

import click
import pytest
from click.testing import CliRunner

from agentsquire import _install, _pypi, _release_cache
from agentsquire import cli as cli_module
from agentsquire.cli import check_update_command

# A distribution name that is not installed in any test environment.
ABSENT = "agentsquire-test-absent-distribution"


def pypi_body(version="2.0.0"):
    """A PyPI JSON document, as bytes, with the given info.version."""
    return json.dumps({"info": {"name": "x", "version": version}, "releases": {}}).encode()


def make_runner():
    """A CliRunner that keeps stderr apart from stdout."""
    try:
        return CliRunner(mix_stderr=False)
    except TypeError:
        # Newer click always keeps the two streams apart.
        return CliRunner()


def run(command, args=()):
    return make_runner().invoke(command, list(args))


@pytest.fixture(autouse=True)
def cache_home(tmp_path, monkeypatch):
    """Point the cache root at a temp directory and clear the switches."""
    home = tmp_path / "cache-home"
    monkeypatch.setenv("XDG_CACHE_HOME", str(home))
    monkeypatch.setattr(_release_cache, "_is_windows", lambda: False)
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.delenv("AGENTSQUIRE_NO_UPDATE_CHECK", raising=False)
    return home


@pytest.fixture
def stub_fetch(monkeypatch):
    """Replace _pypi.fetch; return the function that installs the stub."""

    def install(version="2.0.0", error=None):
        urls = []

        def fetch(url):
            urls.append(url)
            if error is not None:
                raise error
            return pypi_body(version)

        monkeypatch.setattr(_pypi, "fetch", fetch)
        return urls

    return install


@pytest.fixture
def plain_env(tmp_path, monkeypatch):
    """An environment with no known install method: no upgrade command."""
    monkeypatch.setattr(sys, "prefix", str(tmp_path / "plain-env"))


@pytest.fixture
def uv_tool_env(tmp_path, monkeypatch):
    """Make the running environment look like a uv tool environment."""
    prefix = tmp_path / "uv-tool-env"
    prefix.mkdir()
    (prefix / "uv-receipt.toml").write_text("[tool]\n", encoding="utf-8")
    monkeypatch.setattr(sys, "prefix", str(prefix))
    monkeypatch.setattr(_install, "_is_editable", lambda distribution: False)
    return prefix


# --- the command object ---------------------------------------------------


def test_returns_a_click_command_named_check_update():
    command = check_update_command("x", "1.0.0", prog_name="tool")
    assert isinstance(command, click.Command)
    assert command.name == "check-update"


def test_name_argument_sets_the_command_name():
    command = check_update_command("x", "1.0.0", prog_name="tool", name="x")
    assert command.name == "x"


def test_prog_name_is_keyword_only():
    with pytest.raises(TypeError):
        check_update_command("x", "1.0.0", "tool")
    with pytest.raises(TypeError):
        check_update_command("x", "1.0.0")


def test_mounted_command_shows_in_the_group_help(stub_fetch):
    urls = stub_fetch("2.0.0")

    @click.group()
    def app():
        pass

    app.add_command(check_update_command("x", "1.0.0", prog_name="tool"))
    result = run(app, ["--help"])
    assert result.exit_code == 0
    assert "check-update" in result.stdout
    # The help does not run the check.
    assert urls == []


def test_mounted_command_runs_through_the_group(stub_fetch, plain_env):
    stub_fetch("2.0.0")

    @click.group()
    def app():
        pass

    app.add_command(check_update_command(ABSENT, "1.0.0", prog_name="tool"))
    result = run(app, ["check-update"])
    assert result.exit_code == 0
    assert result.stdout == "tool: a new release is available: 1.0.0 -> 2.0.0\n"


def test_command_has_a_help_text_and_no_parameters():
    command = check_update_command("x", "1.0.0", prog_name="tool")
    assert command.help
    assert "tool" in command.help
    assert [p.name for p in command.params] == []


def test_command_rejects_an_argument(stub_fetch):
    urls = stub_fetch("2.0.0")
    result = run(check_update_command("x", "1.0.0", prog_name="tool"), ["extra"])
    assert result.exit_code == 2
    assert urls == []


# --- the cache ------------------------------------------------------------


def test_invoke_writes_the_cache_file(stub_fetch, cache_home, plain_env):
    urls = stub_fetch("2.0.0")
    path = _release_cache.cache_path(ABSENT)
    assert not path.exists()
    result = run(check_update_command(ABSENT, "1.0.0", prog_name="tool"))
    assert result.exit_code == 0
    assert len(urls) == 1
    assert path.is_file()
    assert cache_home in path.parents
    assert json.loads(path.read_text(encoding="utf-8"))["newest"] == "2.0.0"
    assert _release_cache.read_cache(ABSENT) == "2.0.0"


# --- the four result lines ------------------------------------------------


@pytest.mark.parametrize(
    "installed, newest, line",
    [
        ("1.0.0", "2.0.0", "tool: a new release is available: 1.0.0 -> 2.0.0"),
        ("1.0.0", "1.0.0", "tool 1.0.0 is up to date"),
        ("2.0.0", "1.0.0", "tool 2.0.0 is newer than the newest PyPI release 1.0.0"),
        (
            "abc",
            "1.0.0",
            "tool: installed abc, newest PyPI release 1.0.0; the versions cannot be compared",
        ),
    ],
    ids=["update-available", "up-to-date", "ahead", "unknown"],
)
def test_result_line_on_stdout_with_exit_0(stub_fetch, plain_env, installed, newest, line):
    stub_fetch(newest)
    result = run(check_update_command(ABSENT, installed, prog_name="tool"))
    assert result.exit_code == 0
    assert result.stdout == line + "\n"
    assert result.stdout.splitlines() == [line]
    assert result.stderr == ""


def test_update_line_has_the_command_in_a_uv_tool_environment(stub_fetch, uv_tool_env):
    stub_fetch("2.0.0")
    result = run(check_update_command(ABSENT, "1.0.0", prog_name="tool"))
    assert result.exit_code == 0
    assert result.stdout.splitlines() == [
        f"tool: a new release is available: 1.0.0 -> 2.0.0; run `uv tool upgrade {ABSENT}`"
    ]
    assert result.stderr == ""


@pytest.mark.parametrize(
    "installed, newest, line",
    [
        ("1.0.0", "1.0.0", "tool 1.0.0 is up to date"),
        ("2.0.0", "1.0.0", "tool 2.0.0 is newer than the newest PyPI release 1.0.0"),
        (
            "abc",
            "1.0.0",
            "tool: installed abc, newest PyPI release 1.0.0; the versions cannot be compared",
        ),
    ],
    ids=["up-to-date", "ahead", "unknown"],
)
def test_other_lines_have_no_command_in_a_uv_tool_environment(
    stub_fetch, uv_tool_env, installed, newest, line
):
    stub_fetch(newest)
    result = run(check_update_command(ABSENT, installed, prog_name="tool"))
    assert result.exit_code == 0
    assert result.stdout.splitlines() == [line]


def test_unknown_line_names_a_version_that_is_not_known(stub_fetch, plain_env):
    stub_fetch("1.0.0")
    result = run(check_update_command(ABSENT, prog_name="tool"))
    assert result.exit_code == 0
    assert result.stdout.splitlines() == [
        "tool: installed unknown, newest PyPI release 1.0.0; the versions cannot be compared"
    ]


def test_prog_name_is_used_in_the_line(stub_fetch, plain_env):
    stub_fetch("1.0.0")
    result = run(check_update_command(ABSENT, "1.0.0", prog_name="other-tool"))
    assert result.stdout == "other-tool 1.0.0 is up to date\n"


def test_no_version_reads_the_install_metadata(stub_fetch, plain_env):
    import agentsquire

    stub_fetch(agentsquire.__version__)
    result = run(check_update_command("agentsquire", prog_name="tool"))
    assert result.exit_code == 0
    assert result.stdout == f"tool {agentsquire.__version__} is up to date\n"


# --- the failed check -----------------------------------------------------


def test_failed_check_goes_to_stderr_with_exit_1(stub_fetch, cache_home):
    urls = stub_fetch(error=urllib.error.URLError("Name or service not known"))
    result = run(check_update_command(ABSENT, "1.0.0", prog_name="tool"))
    assert len(urls) == 1
    assert result.exit_code == 1
    assert result.stdout == ""
    prefix = "tool: could not check for a new release: "
    lines = result.stderr.splitlines()
    assert len(lines) == 1
    assert lines[0].startswith(prefix)
    assert lines[0][len(prefix):].strip()
    assert lines[0] == prefix + "Name or service not known"
    assert not _release_cache.cache_path(ABSENT).exists()


def test_failed_check_through_a_group_exits_1(stub_fetch):
    stub_fetch(error=urllib.error.URLError("no network"))

    @click.group()
    def app():
        pass

    app.add_command(check_update_command(ABSENT, "1.0.0", prog_name="tool"))
    result = run(app, ["check-update"])
    assert result.exit_code == 1
    assert result.stdout == ""
    assert result.stderr == "tool: could not check for a new release: no network\n"


# --- the environment switches ---------------------------------------------


def test_runs_when_the_environment_switches_are_set(stub_fetch, plain_env, monkeypatch):
    monkeypatch.setenv("CI", "true")
    monkeypatch.setenv("AGENTSQUIRE_NO_UPDATE_CHECK", "1")
    urls = stub_fetch("2.0.0")
    result = run(check_update_command(ABSENT, "1.0.0", prog_name="tool"))
    assert result.exit_code == 0
    assert result.stdout == "tool: a new release is available: 1.0.0 -> 2.0.0\n"
    assert len(urls) == 1
    assert _release_cache.read_cache(ABSENT) == "2.0.0"


# --- the command upgrades nothing -----------------------------------------


def test_check_function_is_looked_up_at_call_time(monkeypatch):
    from agentsquire import release
    from agentsquire.release import ReleaseCheck, ReleaseStatus

    calls = []

    def fake(distribution, version=None):
        calls.append((distribution, version))
        return ReleaseCheck(
            distribution=distribution,
            installed=version,
            newest="9.0.0",
            status=ReleaseStatus.UPDATE_AVAILABLE,
            upgrade_command="do the upgrade",
        )

    command = check_update_command("x", "1.0.0", prog_name="tool")
    monkeypatch.setattr(release, "check_for_update", fake)
    result = run(command)
    assert calls == [("x", "1.0.0")]
    assert result.stdout == "tool: a new release is available: 1.0.0 -> 9.0.0; run `do the upgrade`\n"


def test_command_code_uses_no_subprocess_and_no_installer():
    source = textwrap.dedent(inspect.getsource(check_update_command))
    tree = ast.parse(source)
    names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    names |= {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            names.add(node.module or "")
            names |= {alias.name for alias in node.names}
    banned = {"subprocess", "Popen", "system", "execv", "execvp", "spawnv", "pip", "uv", "pipx"}
    assert not names & banned
    # The module itself does not load subprocess for any verb.
    module_tree = ast.parse(inspect.getsource(cli_module))
    imported = set()
    for node in ast.walk(module_tree):
        if isinstance(node, ast.Import):
            imported |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            imported.add((node.module or "").split(".")[0])
    assert "subprocess" not in imported


def test_invoke_starts_no_process(stub_fetch, uv_tool_env, monkeypatch):
    import subprocess

    def refuse(*args, **kwargs):
        raise AssertionError("the command must not start a process")

    monkeypatch.setattr(subprocess, "Popen", refuse)
    monkeypatch.setattr(subprocess, "run", refuse)
    stub_fetch("2.0.0")
    result = run(check_update_command(ABSENT, "1.0.0", prog_name="tool"))
    assert result.exit_code == 0
    assert result.stdout.startswith("tool: a new release is available: 1.0.0 -> 2.0.0")
