"""Release notice at consumer startup.

notify_update reads the release cache and nothing else. When the cached
newest version is newer than the installed one it prints exactly one line on
stderr. It makes no network request, never writes the cache, never writes
stdout, never prompts, never raises and returns None.
"""

import ast
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import agentsquire._install
import agentsquire._pypi
import agentsquire._release_cache
import agentsquire.staleness
from agentsquire import check_stale
from agentsquire._release_cache import cache_path, write_cache
from agentsquire.harnesses import CLAUDE_CODE
from agentsquire.sources import DirectorySource
from agentsquire.staleness import notify_update
from agentsquire.verbs import install

# A distribution name that is not installed, so it is never an editable
# checkout and has no install metadata.
DIST = "fixture-consumer"

LINE = "fixture: a new release is available: 1.0.0 -> 2.0.0\n"


@pytest.fixture(autouse=True)
def release_env(tmp_path, monkeypatch):
    """A private cache directory, no notice gate, and a fetch that fails."""
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.delenv("AGENTSQUIRE_NO_UPDATE_CHECK", raising=False)
    monkeypatch.setattr(agentsquire._release_cache, "_is_windows", lambda: False)

    def no_fetch(*args, **kwargs):
        pytest.fail("notify_update must not call the fetch step")

    monkeypatch.setattr(agentsquire._pypi, "fetch", no_fetch)


@pytest.fixture
def plain_env(tmp_path, monkeypatch):
    """An environment with no known install method."""
    prefix = tmp_path / "plain-venv"
    prefix.mkdir()
    monkeypatch.setattr(sys, "prefix", str(prefix))
    return prefix


@pytest.fixture
def uv_tool_env(tmp_path, monkeypatch):
    """A uv tool environment: the prefix holds a uv-receipt.toml file."""
    prefix = tmp_path / "uv-tool"
    prefix.mkdir()
    (prefix / "uv-receipt.toml").write_text("[tool]\n")
    monkeypatch.setattr(sys, "prefix", str(prefix))
    return prefix


def write_raw_cache(text: str, distribution: str = DIST) -> Path:
    path = cache_path(distribution)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def run(capsys, *args, **kwargs):
    """Call notify_update; return (result, stdout, stderr)."""
    kwargs.setdefault("prog_name", "fixture")
    result = notify_update(*args, **kwargs)
    captured = capsys.readouterr()
    return result, captured.out, captured.err


def assert_silent(outcome):
    assert outcome == (None, "", "")


# --- the line -------------------------------------------------------------


def test_prints_the_line_in_a_plain_environment(capsys, plain_env):
    write_cache(DIST, "2.0.0")
    assert run(capsys, DIST, "1.0.0") == (None, "", LINE)


def test_prints_the_command_part_in_a_uv_tool_environment(capsys, uv_tool_env):
    write_cache(DIST, "2.0.0")
    assert run(capsys, DIST, "1.0.0") == (
        None,
        "",
        "fixture: a new release is available: 1.0.0 -> 2.0.0;"
        f" run `uv tool upgrade {DIST}`\n",
    )


def test_prog_name_is_keyword_only_and_names_the_cli(capsys, plain_env):
    write_cache(DIST, "2.0.0")
    with pytest.raises(TypeError):
        notify_update(DIST, "1.0.0", "awiki")
    assert run(capsys, DIST, "1.0.0", prog_name="awiki") == (
        None,
        "",
        "awiki: a new release is available: 1.0.0 -> 2.0.0\n",
    )


def test_prints_with_captured_non_tty_stderr(capsys, plain_env):
    write_cache(DIST, "2.0.0")
    assert not sys.stderr.isatty()
    assert run(capsys, DIST, "1.0.0") == (None, "", LINE)


# --- the silent cases -----------------------------------------------------


def test_no_cache_is_silent(capsys, plain_env):
    assert not cache_path(DIST).exists()
    assert_silent(run(capsys, DIST, "1.0.0"))
    assert not cache_path(DIST).exists()


def test_cache_equal_to_installed_is_silent(capsys, plain_env):
    write_cache(DIST, "1.0.0")
    assert_silent(run(capsys, DIST, "1.0.0"))


def test_cache_older_than_installed_is_silent(capsys, plain_env):
    write_cache(DIST, "1.0.0")
    assert_silent(run(capsys, DIST, "1.1.0"))


def test_installed_version_that_does_not_parse_is_silent(capsys, plain_env):
    write_cache(DIST, "2.0.0")
    assert_silent(run(capsys, DIST, "unknown"))


def test_cached_version_that_does_not_parse_is_silent(capsys, plain_env):
    write_cache(DIST, "unknown")
    assert_silent(run(capsys, DIST, "1.0.0"))


def test_invalid_json_cache_is_silent(capsys, plain_env):
    write_raw_cache("{not json")
    assert_silent(run(capsys, DIST, "1.0.0"))


@pytest.mark.parametrize(
    "text",
    ['["2.0.0"]', '"2.0.0"', '{"newest": 2}', '{"newest": ""}', '{"version": "2.0.0"}'],
)
def test_wrong_shape_cache_is_silent(capsys, plain_env, text):
    write_raw_cache(text)
    assert_silent(run(capsys, DIST, "1.0.0"))


# --- no stored verdict, no age limit, no cache write ------------------------


def test_old_cache_still_gives_the_line_and_is_never_written(capsys, plain_env):
    checked_at = datetime.now(timezone.utc) - timedelta(days=400)
    path = write_raw_cache(
        json.dumps({"newest": "2.0.0", "checked_at": checked_at.isoformat()})
    )
    before = path.read_bytes()
    stat_before = path.stat().st_mtime_ns

    assert run(capsys, DIST, "1.0.0") == (None, "", LINE)
    assert path.read_bytes() == before

    assert_silent(run(capsys, DIST, "2.0.0"))
    assert path.read_bytes() == before
    assert path.stat().st_mtime_ns == stat_before
    assert sorted(p.name for p in path.parent.iterdir()) == [path.name]


def test_does_not_call_the_cache_write(capsys, plain_env, monkeypatch):
    write_cache(DIST, "2.0.0")

    def no_write(*args, **kwargs):
        pytest.fail("notify_update must not write the cache")

    monkeypatch.setattr(agentsquire._release_cache, "write_cache", no_write)
    assert run(capsys, DIST, "1.0.0") == (None, "", LINE)


# --- never raises ---------------------------------------------------------


def test_cache_read_error_gives_none_and_no_output(capsys, plain_env, monkeypatch):
    write_cache(DIST, "2.0.0")

    def broken(distribution):
        raise RuntimeError("cache read failed")

    monkeypatch.setattr(agentsquire._release_cache, "read_cache", broken)
    assert_silent(run(capsys, DIST, "1.0.0"))


def test_upgrade_command_error_gives_none_and_no_output(capsys, plain_env, monkeypatch):
    write_cache(DIST, "2.0.0")

    def broken(distribution):
        raise RuntimeError("detection failed")

    monkeypatch.setattr(agentsquire._install, "upgrade_command", broken)
    assert_silent(run(capsys, DIST, "1.0.0"))


# --- the notice gate ------------------------------------------------------


def test_ci_disables_the_line(capsys, plain_env, monkeypatch):
    write_cache(DIST, "2.0.0")
    monkeypatch.setenv("CI", "true")
    assert_silent(run(capsys, DIST, "1.0.0"))


def test_no_update_check_variable_disables_the_line(capsys, plain_env, monkeypatch):
    write_cache(DIST, "2.0.0")
    monkeypatch.setenv("AGENTSQUIRE_NO_UPDATE_CHECK", "1")
    assert_silent(run(capsys, DIST, "1.0.0"))


def test_gate_is_checked_before_the_cache_read(capsys, plain_env, monkeypatch):
    monkeypatch.setenv("CI", "true")

    def no_read(distribution):
        pytest.fail("a disabled notice must not read the cache")

    monkeypatch.setattr(agentsquire._release_cache, "read_cache", no_read)
    assert_silent(run(capsys, DIST, "1.0.0"))


@pytest.mark.parametrize("name", ["CI", "AGENTSQUIRE_NO_UPDATE_CHECK"])
def test_empty_gate_value_counts_as_unset(capsys, plain_env, monkeypatch, name):
    write_cache(DIST, "2.0.0")
    monkeypatch.setenv(name, "")
    assert run(capsys, DIST, "1.0.0") == (None, "", LINE)


# --- the installed version from the install metadata ------------------------


def test_version_none_uses_the_install_metadata(capsys, plain_env, monkeypatch):
    write_cache(DIST, "2.0.0")
    asked = []

    def fake_installed(distribution):
        asked.append(distribution)
        return "1.0.0"

    monkeypatch.setattr(agentsquire._install, "installed_version", fake_installed)
    assert run(capsys, DIST) == (None, "", LINE)
    assert asked == [DIST]


def test_version_none_reads_real_install_metadata(capsys, plain_env):
    installed = agentsquire._install.installed_version("pytest")
    assert installed
    write_cache("pytest", "99999.0.0")
    result, out, err = run(capsys, "pytest")
    assert (result, out) == (None, "")
    assert err.startswith(
        f"fixture: a new release is available: {installed} -> 99999.0.0"
    )
    assert err.count("\n") == 1


def test_version_none_for_a_distribution_not_installed_is_silent(capsys, plain_env):
    # A name of its own: another test file installs a fixture distribution
    # under the shared fixture name, and the metadata lookup can still see
    # it later in the same run.
    name = "agentsquire-fixture-not-installed"
    write_cache(name, "2.0.0")
    assert agentsquire._install.installed_version(name) is None
    assert_silent(run(capsys, name))


def test_passed_version_is_used_without_a_metadata_lookup(
    capsys, plain_env, monkeypatch
):
    write_cache(DIST, "2.0.0")

    def no_lookup(distribution):
        pytest.fail("a passed version must not be looked up")

    monkeypatch.setattr(agentsquire._install, "installed_version", no_lookup)
    assert run(capsys, DIST, "1.0.0") == (None, "", LINE)


# --- no fetch, by construction ----------------------------------------------


def test_staleness_module_does_not_import_the_fetch_module():
    source = Path(agentsquire.staleness.__file__).with_suffix(".py").read_text()
    names = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            names.add(node.module or "")
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
        elif isinstance(node, ast.Name):
            names.add(node.id)
    assert not any("_pypi" in name for name in names)
    assert not any("check_for_update" in name for name in names)


# --- check_stale stays a skills notice only ---------------------------------


def test_check_stale_prints_no_release_line_and_calls_no_fetch(
    capsys, tmp_path, monkeypatch
):
    root = tmp_path / "skills-env"
    for sub in ("home", "project", "bundle"):
        (root / sub).mkdir(parents=True)
    skill = root / "bundle" / "fixture-skill"
    skill.mkdir()
    (skill / "SKILL.md").write_text(
        "---\nname: fixture-skill\ndescription: A fixture skill.\n---\n\nbody\n"
    )
    (skill / "reference.md").write_text("v1\n")
    source = DirectorySource(root / "bundle")
    install(
        source,
        CLAUDE_CODE,
        scope="user",
        home=root / "home",
        project=root / "project",
        source_package=DIST,
        source_version="1.0.0",
    )
    (skill / "reference.md").write_text("v2\n")

    # Release caches that would give a notice for each name in play.
    for name in (DIST, "fixture", "agentsquire"):
        write_cache(name, "99999.0.0")

    def no_notice(*args, **kwargs):
        pytest.fail("check_stale must not call the release notice")

    monkeypatch.setattr(agentsquire.staleness, "notify_update", no_notice)

    result = check_stale(
        source,
        CLAUDE_CODE,
        scope="user",
        home=root / "home",
        project=root / "project",
        prog_name="fixture",
        update_command="fixture skills update",
    )
    captured = capsys.readouterr()
    assert result is None
    assert captured.out == ""
    assert captured.err == (
        "fixture: a skills update is available for 1 skill (fixture-skill);"
        " run `fixture skills update`\n"
    )
    assert "release" not in captured.err
