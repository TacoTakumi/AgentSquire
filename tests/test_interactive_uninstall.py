"""Interactive uninstall picker (REQ-22).

A bare ``uninstall`` on a TTY lists exactly the installed-and-ours skills —
enumerated from on-disk provenance stamps across every detected harness and
scope — and removes the selected subset. Every path is driven with
``questionary`` monkeypatched to canned answers; no test needs a real TTY.
"""

import sys
from pathlib import Path

import pytest
import questionary
from click.testing import CliRunner

import agentsquire.cli as cli
from agentsquire.cli import installed_and_ours, skills_command_group
from agentsquire.harnesses import CLAUDE_CODE, PI, default_registry
from agentsquire.interactive import gather_uninstall_plan
from agentsquire.sources import BundledPackageDataSource
from agentsquire.stamping import stamped_skill_md
from agentsquire.verbs import install as install_verb

PKG = "fixture_consumer_pkg"
SKILL_MD = "---\nname: alpha\ndescription: A fixture skill.\n---\n\nbody\n"


class _Answer:
    def __init__(self, value):
        self._value = value

    def ask(self, **kwargs):
        return self._value


class FakeQuestionary:
    """Records checkbox/confirm calls and returns canned answers."""

    def __init__(self, *, checkbox, confirm=True):
        self._checkbox = checkbox
        self._confirm = confirm
        self.calls = []  # (kind, message, choices)

    def checkbox(self, message, choices, **kwargs):
        self.calls.append(("checkbox", message, list(choices)))
        return _Answer(self._checkbox)

    def confirm(self, message, **kwargs):
        self.calls.append(("confirm", message, None))
        return _Answer(self._confirm)


@pytest.fixture(autouse=True)
def forbid_real_tty(monkeypatch):
    """REQ-17: turn any un-stubbed prompt into a loud failure, not a TTY hang."""
    import prompt_toolkit

    def _entered(*args, **kwargs):
        raise AssertionError("a real prompt_toolkit prompt was entered under test")

    monkeypatch.setattr(prompt_toolkit.Application, "run", _entered)


@pytest.fixture
def fake_questionary(monkeypatch):
    def install(*, checkbox, confirm=True):
        fake = FakeQuestionary(checkbox=checkbox, confirm=confirm)
        monkeypatch.setattr(questionary, "checkbox", fake.checkbox)
        monkeypatch.setattr(questionary, "confirm", fake.confirm)
        return fake

    return install


@pytest.fixture
def tty(monkeypatch):
    monkeypatch.setattr(cli, "_stdin_is_interactive", lambda: True)
    monkeypatch.delenv("CI", raising=False)


def _write_skill(dir_path: Path, name: str, *, stamp=None):
    dir_path.mkdir(parents=True, exist_ok=True)
    text = f"---\nname: {name}\ndescription: d\n---\nbody\n"
    if stamp is not None:
        text = stamped_skill_md(text, stamp)
    (dir_path / "SKILL.md").write_text(text)


@pytest.fixture
def installed(tmp_path, monkeypatch):
    """A home/project with claude-code + pi detected, carrying our-stamped alpha
    in three (harness, scope) slots plus unstamped and foreign-stamped decoys."""
    pkg = tmp_path / "pkgroot" / PKG
    skill = pkg / "skills" / "alpha"
    skill.mkdir(parents=True)
    (pkg / "__init__.py").write_text('__version__ = "1.2.3"\n')
    (skill / "SKILL.md").write_text(SKILL_MD)
    monkeypatch.syspath_prepend(str(tmp_path / "pkgroot"))
    monkeypatch.delitem(sys.modules, PKG, raising=False)

    home = tmp_path / "home"
    project = tmp_path / "project"
    (home / ".claude").mkdir(parents=True)
    (home / ".pi").mkdir()
    project.mkdir()

    source = BundledPackageDataSource(PKG, "skills")
    for backend, scope in [(CLAUDE_CODE, "user"), (CLAUDE_CODE, "project"), (PI, "user")]:
        install_verb(
            source, backend, scope=scope, home=home, project=project,
            source_package=PKG, source_version="1.2.3",
        )

    # Decoys at claude-code/user that must never be offered:
    claude_user = home / ".claude" / "skills"
    _write_skill(claude_user / "beta", "beta")  # unstamped
    _write_skill(
        claude_user / "gamma", "gamma",
        stamp={"installer": "other-tool", "source_package": PKG},
    )  # foreign installer
    _write_skill(
        claude_user / "delta", "delta",
        stamp={"installer": "agentsquire", "source_package": "other-pkg"},
    )  # foreign source package
    return home, project


def _group(home, project):
    return skills_command_group(PKG, default_scope="user", home=home, project=project)


def test_enumerates_exactly_installed_and_ours(installed):
    home, project = installed
    backends = default_registry().detect(home=home, project=project)

    entries = installed_and_ours(
        backends, source_package=PKG, home=home, project=project
    )

    assert [(e.name, e.backend.name, e.scope) for e in entries] == [
        ("alpha", "claude-code", "user"),
        ("alpha", "claude-code", "project"),
        ("alpha", "pi", "user"),
    ]


def test_picker_offers_exactly_installed_and_ours(installed, fake_questionary):
    home, project = installed
    backends = default_registry().detect(home=home, project=project)
    entries = installed_and_ours(
        backends, source_package=PKG, home=home, project=project
    )
    fake = fake_questionary(checkbox=[], confirm=True)

    gather_uninstall_plan(entries)

    checkbox = next(call for call in fake.calls if call[0] == "checkbox")
    titles = [choice.title for choice in checkbox[2]]
    assert titles == [
        "alpha (claude-code/user)",
        "alpha (claude-code/project)",
        "alpha (pi/user)",
    ]


def test_selecting_and_confirming_removes_exactly_those(
    installed, fake_questionary, tty
):
    home, project = installed
    # index 0 == alpha @ claude-code/user (first enumerated entry)
    fake_questionary(checkbox=[0], confirm=True)

    result = CliRunner().invoke(
        _group(home, project), ["uninstall"], catch_exceptions=False
    )

    assert result.exit_code == 0, result.output
    assert not (home / ".claude" / "skills" / "alpha").exists()  # removed
    # every other target and every decoy is untouched
    assert (project / ".claude" / "skills" / "alpha").is_dir()
    assert (home / ".pi" / "agent" / "skills" / "alpha").is_dir()
    assert (home / ".claude" / "skills" / "beta").is_dir()
    assert (home / ".claude" / "skills" / "gamma").is_dir()
    assert (home / ".claude" / "skills" / "delta").is_dir()


class TestUninstallConfirmAndFlags:
    """REQ-23: a destructive confirm summary before removal; -y pre-answers it;
    --no-input runs the flag path over the specified targets with no prompt."""

    def test_declining_the_confirm_removes_nothing(
        self, installed, fake_questionary, tty
    ):
        home, project = installed
        fake = fake_questionary(checkbox=[0], confirm=False)

        result = CliRunner().invoke(
            _group(home, project), ["uninstall"], catch_exceptions=False
        )

        assert result.exit_code == 0, result.output
        assert any(call[0] == "confirm" for call in fake.calls)  # summary shown
        assert (home / ".claude" / "skills" / "alpha").is_dir()  # nothing removed

    def test_yes_removes_without_a_confirm_prompt(
        self, installed, fake_questionary, tty
    ):
        home, project = installed
        fake = fake_questionary(checkbox=[0], confirm=True)

        result = CliRunner().invoke(
            _group(home, project), ["uninstall", "-y"], catch_exceptions=False
        )

        assert result.exit_code == 0, result.output
        assert any(call[0] == "checkbox" for call in fake.calls)  # picker still shown
        assert not any(call[0] == "confirm" for call in fake.calls)  # confirm skipped
        assert not (home / ".claude" / "skills" / "alpha").exists()  # removed

    def test_no_input_with_harness_removes_only_that_target_without_prompting(
        self, installed, fake_questionary, tty
    ):
        home, project = installed
        fake = fake_questionary(checkbox=[0], confirm=True)

        result = CliRunner().invoke(
            _group(home, project),
            ["uninstall", "--no-input", "--harness", "claude-code"],
            catch_exceptions=False,
        )

        assert result.exit_code == 0, result.output
        assert fake.calls == []  # no prompt constructed
        assert not (home / ".claude" / "skills" / "alpha").exists()  # target removed
        # other harness/scope targets are untouched by the flag-specified run
        assert (project / ".claude" / "skills" / "alpha").is_dir()
        assert (home / ".pi" / "agent" / "skills" / "alpha").is_dir()
