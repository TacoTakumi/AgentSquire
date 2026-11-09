"""Install detection: the installed version and the upgrade command.

installed_version reads the version of a distribution from the install
metadata. upgrade_command names the command that upgrades the running
environment: a uv tool environment, a pipx environment, or nothing when the
install method is not known or the distribution is an editable checkout.
Neither function raises.
"""

import importlib.metadata
import json
import sys

import pytest

from agentsquire._install import installed_version, upgrade_command


class FakeDistribution:
    """Stands in for an installed distribution with a direct_url.json file."""

    def __init__(self, direct_url):
        self._direct_url = direct_url

    def read_text(self, filename):
        if filename == "direct_url.json":
            return self._direct_url
        return None


def patch_distribution(monkeypatch, direct_url):
    """Make every metadata lookup return a distribution with this direct_url.json."""
    monkeypatch.setattr(
        importlib.metadata,
        "distribution",
        lambda name: FakeDistribution(direct_url),
    )


def patch_not_installed(monkeypatch):
    """Make every metadata lookup report that the distribution is not installed."""

    def missing(name):
        raise importlib.metadata.PackageNotFoundError(name)

    monkeypatch.setattr(importlib.metadata, "distribution", missing)


def editable_direct_url():
    return json.dumps({"url": "file:///home/you/src/x", "dir_info": {"editable": True}})


def uv_tool_env(tmp_path):
    prefix = tmp_path / "uv" / "tools" / "agent-wiki-kb"
    prefix.mkdir(parents=True)
    (prefix / "uv-receipt.toml").write_text("[tool]\n")
    return prefix


def test_installed_version_reads_the_install_metadata():
    assert installed_version("agentsquire") == importlib.metadata.version("agentsquire")


def test_installed_version_is_none_when_not_installed():
    assert installed_version("no-such-distribution-agentsquire-test") is None


def test_installed_version_is_none_when_the_lookup_fails(monkeypatch):
    def broken(name):
        raise ValueError("bad metadata")

    monkeypatch.setattr(importlib.metadata, "version", broken)
    assert installed_version("agentsquire") is None


def test_uv_receipt_gives_the_uv_tool_upgrade_command(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "prefix", str(uv_tool_env(tmp_path)))
    patch_not_installed(monkeypatch)
    assert upgrade_command("Agent_Wiki.KB") == "uv tool upgrade Agent_Wiki.KB"


def test_pipx_venv_path_gives_the_pipx_upgrade_command(tmp_path, monkeypatch):
    prefix = tmp_path / "pipx" / "venvs" / "x"
    prefix.mkdir(parents=True)
    monkeypatch.setattr(sys, "prefix", str(prefix))
    patch_not_installed(monkeypatch)
    assert upgrade_command("Agent_Wiki.KB") == "pipx upgrade Agent_Wiki.KB"


def test_plain_venv_gives_no_command(tmp_path, monkeypatch):
    prefix = tmp_path / "project" / ".venv"
    prefix.mkdir(parents=True)
    monkeypatch.setattr(sys, "prefix", str(prefix))
    patch_not_installed(monkeypatch)
    assert upgrade_command("agentsquire") is None


def test_pipx_directory_that_is_not_a_venv_gives_no_command(tmp_path, monkeypatch):
    prefix = tmp_path / "pipx" / "venvs"
    prefix.mkdir(parents=True)
    monkeypatch.setattr(sys, "prefix", str(prefix))
    patch_not_installed(monkeypatch)
    assert upgrade_command("agentsquire") is None


def test_editable_install_in_a_uv_tool_env_gives_no_command(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "prefix", str(uv_tool_env(tmp_path)))
    patch_distribution(monkeypatch, editable_direct_url())
    assert upgrade_command("agentsquire") is None


def test_editable_install_in_a_pipx_env_gives_no_command(tmp_path, monkeypatch):
    prefix = tmp_path / "pipx" / "venvs" / "x"
    prefix.mkdir(parents=True)
    monkeypatch.setattr(sys, "prefix", str(prefix))
    patch_distribution(monkeypatch, editable_direct_url())
    assert upgrade_command("agentsquire") is None


@pytest.mark.parametrize(
    "direct_url",
    [
        None,
        "",
        "not json",
        "[]",
        json.dumps({"url": "file:///home/you/src/x", "dir_info": {}}),
        json.dumps({"url": "file:///home/you/src/x", "dir_info": {"editable": False}}),
        json.dumps({"url": "https://example.invalid/x.whl", "archive_info": {}}),
    ],
)
def test_install_that_is_not_editable_keeps_the_command(tmp_path, monkeypatch, direct_url):
    monkeypatch.setattr(sys, "prefix", str(uv_tool_env(tmp_path)))
    patch_distribution(monkeypatch, direct_url)
    assert upgrade_command("agentsquire") == "uv tool upgrade agentsquire"


def test_upgrade_command_does_not_raise_when_the_lookup_fails(tmp_path, monkeypatch):
    def broken(name):
        raise RuntimeError("bad metadata")

    monkeypatch.setattr(sys, "prefix", str(uv_tool_env(tmp_path)))
    monkeypatch.setattr(importlib.metadata, "distribution", broken)
    assert upgrade_command("agentsquire") == "uv tool upgrade agentsquire"
