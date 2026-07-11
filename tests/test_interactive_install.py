"""Interactive install front-end (REQ-07, REQ-08, REQ-09, REQ-16).

The gatherer prompts checkbox(detected harnesses) -> per-harness scope select
-> confirm summary, and returns a plan the shared executor runs. Every path is
driven with ``questionary`` monkeypatched to canned answers; no test needs a
real TTY (REQ-17).
"""

import ast
import sys
from pathlib import Path

import pytest
import questionary
from click.testing import CliRunner

import agentsquire.cli as cli
from agentsquire.cli import execute_install_plan, skills_command_group
from agentsquire.harnesses import CLAUDE_CODE, HERMES, PI, default_registry
from agentsquire.interactive import gather_install_plan
from agentsquire.sources import BundledPackageDataSource

SKILL_MD = "---\nname: alpha\ndescription: A fixture skill.\n---\n\nbody\n"

SRC = Path(__file__).parent.parent / "src" / "agentsquire"


class _Answer:
    """A stand-in questionary Question whose .ask() returns a canned value."""

    def __init__(self, value):
        self._value = value

    def ask(self, **kwargs):
        return self._value


class FakeQuestionary:
    """Records checkbox/select/confirm calls and returns canned answers so the
    prompt order, the choices, and the confirm text can be asserted."""

    def __init__(self, *, checkbox, scopes, confirm):
        self._checkbox = checkbox
        self._scopes = list(scopes)
        self._confirm = confirm
        self.calls = []  # (kind, message, choices)

    def checkbox(self, message, choices, **kwargs):
        self.calls.append(("checkbox", message, list(choices)))
        return _Answer(self._checkbox)

    def select(self, message, choices, **kwargs):
        self.calls.append(("select", message, list(choices)))
        return _Answer(self._scopes.pop(0))

    def confirm(self, message, **kwargs):
        self.calls.append(("confirm", message, None))
        return _Answer(self._confirm)


@pytest.fixture
def fake_questionary(monkeypatch):
    def install(*, checkbox, scopes=(), confirm=True):
        fake = FakeQuestionary(checkbox=checkbox, scopes=scopes, confirm=confirm)
        monkeypatch.setattr(questionary, "checkbox", fake.checkbox)
        monkeypatch.setattr(questionary, "select", fake.select)
        monkeypatch.setattr(questionary, "confirm", fake.confirm)
        return fake

    return install


def _register_consumer(tmp_path, monkeypatch):
    """Create and import-register a fixture consumer package with one skill."""
    pkg = tmp_path / "pkgroot" / "fixture_consumer_pkg"
    skill = pkg / "skills" / "alpha"
    skill.mkdir(parents=True)
    (pkg / "__init__.py").write_text('__version__ = "1.2.3"\n')
    (skill / "SKILL.md").write_text(SKILL_MD)
    monkeypatch.syspath_prepend(str(tmp_path / "pkgroot"))
    monkeypatch.delitem(sys.modules, "fixture_consumer_pkg", raising=False)


@pytest.fixture
def prepared(tmp_path, monkeypatch):
    """A bundled source plus a home/project with claude-code and pi detected."""
    _register_consumer(tmp_path, monkeypatch)
    home = tmp_path / "home"
    project = tmp_path / "project"
    (home / ".claude").mkdir(parents=True)
    (home / ".pi").mkdir()
    project.mkdir()
    source = BundledPackageDataSource("fixture_consumer_pkg", "skills")
    return source, home, project


@pytest.fixture
def bare(tmp_path, monkeypatch):
    """A registered consumer plus a home/project with no harness markers."""
    _register_consumer(tmp_path, monkeypatch)
    home = tmp_path / "home"
    project = tmp_path / "project"
    home.mkdir()
    project.mkdir()
    return home, project


@pytest.fixture
def tty(monkeypatch):
    """Force the install auto-gate on: interactive stdin, CI unset."""
    monkeypatch.setattr(cli, "_stdin_is_interactive", lambda: True)
    monkeypatch.delenv("CI", raising=False)


def _group(home, project):
    return skills_command_group(
        "fixture_consumer_pkg", default_scope="user", home=home, project=project
    )


class TestInstallTtyGate:
    """REQ-02/REQ-03/REQ-04/REQ-05: install prompts only on an interactive TTY
    with no selection/control flag and CI unset; any explicit flag, a non-TTY,
    or CI runs the non-interactive flag path with no prompt constructed."""

    def test_bare_install_on_a_tty_launches_the_shared_front_end(
        self, prepared, fake_questionary, tty
    ):
        _, home, project = prepared
        fake = fake_questionary(checkbox=["claude-code"], scopes=["user"], confirm=True)

        result = CliRunner().invoke(
            _group(home, project), ["install"], catch_exceptions=False
        )

        assert result.exit_code == 0, result.output
        assert [call[0] for call in fake.calls] == ["checkbox", "select", "confirm"]
        assert (home / ".claude" / "skills" / "alpha").is_dir()

    def test_non_tty_runs_the_flag_path_with_no_prompt(
        self, prepared, fake_questionary, monkeypatch
    ):
        _, home, project = prepared
        monkeypatch.setattr(cli, "_stdin_is_interactive", lambda: False)
        monkeypatch.delenv("CI", raising=False)
        fake = fake_questionary(checkbox=["claude-code"], scopes=["user"], confirm=True)

        result = CliRunner().invoke(
            _group(home, project), ["install"], catch_exceptions=False
        )

        assert result.exit_code == 0, result.output
        assert fake.calls == []  # no prompt constructed
        # flag path: every detected harness at the default user scope
        assert (home / ".claude" / "skills" / "alpha").is_dir()
        assert (home / ".pi" / "agent" / "skills" / "alpha").is_dir()

    def test_ci_env_disables_the_tui(self, prepared, fake_questionary, monkeypatch):
        _, home, project = prepared
        monkeypatch.setattr(cli, "_stdin_is_interactive", lambda: True)
        monkeypatch.setenv("CI", "true")
        fake = fake_questionary(checkbox=["claude-code"], scopes=["user"], confirm=True)

        result = CliRunner().invoke(
            _group(home, project), ["install"], catch_exceptions=False
        )

        assert result.exit_code == 0, result.output
        assert fake.calls == []

    def test_explicit_scope_equal_to_default_still_disables_the_tui(
        self, prepared, fake_questionary, tty
    ):
        _, home, project = prepared
        fake = fake_questionary(checkbox=["claude-code"], scopes=["user"], confirm=True)

        result = CliRunner().invoke(
            _group(home, project), ["install", "--scope", "user"],
            catch_exceptions=False,
        )

        assert result.exit_code == 0, result.output
        assert fake.calls == []  # detected via parameter source, not truthiness

    def test_explicit_harness_disables_the_tui(self, prepared, fake_questionary, tty):
        _, home, project = prepared
        fake = fake_questionary(checkbox=["claude-code"], scopes=["user"], confirm=True)

        result = CliRunner().invoke(
            _group(home, project), ["install", "--harness", "claude-code"],
            catch_exceptions=False,
        )

        assert result.exit_code == 0, result.output
        assert fake.calls == []

    @pytest.mark.parametrize("flag", ["--no-input", "-y"])
    def test_control_flags_disable_the_tui(
        self, prepared, fake_questionary, tty, flag
    ):
        _, home, project = prepared
        fake = fake_questionary(checkbox=["claude-code"], scopes=["user"], confirm=True)

        result = CliRunner().invoke(
            _group(home, project), ["install", flag], catch_exceptions=False
        )

        assert result.exit_code == 0, result.output
        assert fake.calls == []

    def test_help_lists_the_control_flags(self, prepared):
        _, home, project = prepared

        result = CliRunner().invoke(_group(home, project), ["install", "--help"])

        assert "--no-input" in result.output
        assert "--yes" in result.output and "-y" in result.output


class TestInstallSafety:
    """REQ-18/REQ-19/REQ-20/REQ-24: zero-harness guard, cancel abort, empty or
    declined no-op, and no partial write on a confirmed multi-harness plan."""

    def test_zero_detected_errors_without_constructing_a_checkbox(
        self, bare, fake_questionary, tty
    ):
        home, project = bare
        fake = fake_questionary(checkbox=["claude-code"], scopes=["user"], confirm=True)

        result = CliRunner().invoke(
            _group(home, project), ["install"], catch_exceptions=False
        )

        assert result.exit_code != 0
        assert "no supported harnesses detected" in result.output
        assert fake.calls == []  # no checkbox rendered

    @pytest.mark.parametrize(
        "checkbox, scopes, confirm",
        [
            (None, [], True),                 # cancel at the checkbox
            (["claude-code"], [None], True),  # cancel at the scope select
            (["claude-code"], ["user"], None),  # cancel at the confirm
        ],
    )
    def test_cancel_at_any_prompt_aborts_with_no_writes(
        self, prepared, fake_questionary, tty, checkbox, scopes, confirm
    ):
        _, home, project = prepared
        fake_questionary(checkbox=checkbox, scopes=scopes, confirm=confirm)

        result = CliRunner().invoke(
            _group(home, project), ["install"], catch_exceptions=False
        )

        assert result.exit_code != 0
        assert "aborted" in result.output.lower()
        assert not (home / ".claude" / "skills" / "alpha").exists()
        assert not (home / ".pi" / "agent" / "skills" / "alpha").exists()

    @pytest.mark.parametrize(
        "checkbox, scopes, confirm",
        [
            ([], [], True),                     # nothing selected
            (["claude-code"], ["user"], False),  # confirm declined
        ],
    )
    def test_empty_or_declined_is_a_clean_noop(
        self, prepared, fake_questionary, tty, checkbox, scopes, confirm
    ):
        _, home, project = prepared
        fake_questionary(checkbox=checkbox, scopes=scopes, confirm=confirm)

        result = CliRunner().invoke(
            _group(home, project), ["install"], catch_exceptions=False
        )

        assert result.exit_code == 0, result.output
        assert "nothing" in result.output.lower()
        assert not (home / ".claude" / "skills" / "alpha").exists()
        assert not (home / ".pi" / "agent" / "skills" / "alpha").exists()

    @pytest.mark.parametrize("confirm", [False, None])
    def test_multi_harness_abort_at_confirm_writes_no_subset(
        self, prepared, fake_questionary, tty, confirm
    ):
        _, home, project = prepared
        fake_questionary(
            checkbox=["claude-code", "pi"], scopes=["user", "user"], confirm=confirm
        )

        CliRunner().invoke(
            _group(home, project), ["install"], catch_exceptions=False
        )

        # Confirm is the single last gate: zero of the two targets are written.
        assert not (home / ".claude" / "skills" / "alpha").exists()
        assert not (home / ".pi" / "agent" / "skills" / "alpha").exists()


def test_prompts_in_order_and_returns_the_confirmed_plan(fake_questionary):
    fake = fake_questionary(
        checkbox=["claude-code", "pi"], scopes=["project", "user"], confirm=True
    )

    plan = gather_install_plan([CLAUDE_CODE, PI], default_scope="user")

    assert [call[0] for call in fake.calls] == [
        "checkbox", "select", "select", "confirm",
    ]
    assert [(t.backend.name, t.scope) for t in plan] == [
        ("claude-code", "project"), ("pi", "user"),
    ]


def test_single_scope_harness_is_offered_only_its_scope(fake_questionary):
    fake = fake_questionary(checkbox=["hermes"], scopes=["user"], confirm=True)

    gather_install_plan([HERMES])

    hermes_select = next(
        call for call in fake.calls if call[0] == "select" and "hermes" in call[1]
    )
    values = [choice.value for choice in hermes_select[2]]
    assert values == ["user"]  # only Global/user; never project/Local


def test_confirm_summary_lists_every_harness_scope_pair(fake_questionary):
    fake = fake_questionary(
        checkbox=["claude-code", "pi"], scopes=["project", "user"], confirm=True
    )

    gather_install_plan([CLAUDE_CODE, PI], default_scope="user")

    confirm_message = next(call[1] for call in fake.calls if call[0] == "confirm")
    assert "claude-code (project)" in confirm_message
    assert "pi (user)" in confirm_message


def test_gathered_plan_installs_through_the_shared_executor(
    fake_questionary, prepared
):
    source, home, project = prepared
    backends = default_registry().detect(home=home, project=project)
    fake_questionary(
        checkbox=["claude-code", "pi"], scopes=["project", "user"], confirm=True
    )

    plan = gather_install_plan(backends, default_scope="user")
    execution = execute_install_plan(
        source, plan, home=home, project=project,
        source_package="fixture_consumer_pkg", source_version="1.2.3",
    )

    assert execution.ok
    assert (project / ".claude" / "skills" / "alpha").is_dir()  # claude at project
    assert (home / ".pi" / "agent" / "skills" / "alpha").is_dir()  # pi at user


def _module_imports(filename: str) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(ast.parse((SRC / filename).read_text())):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".")[0])
    return names


def test_questionary_is_imported_only_in_the_front_end_module():
    """REQ-16: questionary/prompt_toolkit live only in interactive.py; the
    executor (cli.py) and the verbs reference neither."""
    assert "questionary" in _module_imports("interactive.py")
    for module in ("verbs.py", "cli.py"):
        assert "questionary" not in _module_imports(module)
        assert "prompt_toolkit" not in _module_imports(module)
