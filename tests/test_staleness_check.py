"""Notice-only staleness check hook (REQ-01, REQ-02, REQ-03, REQ-05, REQ-13).

check_stale is a safe startup hook: with update-available skills it prints
exactly one advisory line on stderr naming the real CLI and the exact update
command, and nothing else. It never reads stdin, never prompts, never
updates anything, never writes stdout, never raises, and never changes the
consumer command's exit code.
"""

import ast
import inspect
import io
import os
import subprocess
import sys
from pathlib import Path

import pytest

import agentsquire.staleness
from agentsquire import check_stale
from agentsquire.harnesses import CLAUDE_CODE
from agentsquire.sources import DirectorySource
from agentsquire.verbs import install

SRC = Path(__file__).parent.parent / "src"
STALENESS_SOURCE = Path(agentsquire.staleness.__file__).with_suffix(".py").read_text()

CONSUMER_SCRIPT = """\
import sys
from pathlib import Path

import agentsquire as sq

root = Path(sys.argv[1])
sq.check_stale(
    sq.DirectorySource(root / "bundle"),
    sq.CLAUDE_CODE,
    scope="user",
    home=root / "home",
    project=root / "project",
    prog_name="awiki",
    update_command="awiki skills update",
)
print("COMMAND OUTPUT")
"""


def write_skill(root: Path, name: str) -> Path:
    skill = root / name
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: A fixture skill.\n---\n\nbody\n"
    )
    (skill / "reference.md").write_text(f"reference for {name}\n")
    return skill


def make_env(root: Path, names: tuple[str, ...]) -> DirectorySource:
    """bundle/home/project roots with the named skills installed up to date."""
    for sub in ("home", "project", "bundle"):
        (root / sub).mkdir()
    for name in names:
        write_skill(root / "bundle", name)
    source = DirectorySource(root / "bundle")
    install(
        source,
        CLAUDE_CODE,
        scope="user",
        home=root / "home",
        project=root / "project",
        source_package="fixture-consumer",
        source_version="1.2.3",
    )
    return source


def make_stale(root: Path, name: str) -> None:
    (root / "bundle" / name / "reference.md").write_text("v2\n")


def snapshot(directory: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(directory)): path.read_bytes()
        for path in sorted(directory.rglob("*"))
        if path.is_file()
    }


def call(source, root: Path):
    return check_stale(
        source,
        CLAUDE_CODE,
        scope="user",
        home=root / "home",
        project=root / "project",
        prog_name="awiki",
        update_command="awiki skills update",
    )


@pytest.fixture
def notice_permitted(monkeypatch, capsys):
    """Force notice-permitting conditions: suppression env unset, stderr a TTY.

    Depends on capsys so the isatty patch lands on the captured stderr.
    """
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.delenv("AGENTSQUIRE_NO_UPDATE_CHECK", raising=False)
    monkeypatch.setattr(sys.stderr, "isatty", lambda: True, raising=False)
    return capsys


class TestStructural:
    def test_source_never_touches_stdin_or_prompts(self):
        assert "stdin" not in STALENESS_SOURCE
        assert "readline" not in STALENESS_SOURCE
        assert "Update now?" not in STALENESS_SOURCE

    def test_update_verb_neither_imported_nor_called(self):
        tree = ast.parse(STALENESS_SOURCE)
        imported = [
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.Import, ast.ImportFrom))
            for alias in node.names
        ]
        assert "update" not in imported
        called = [
            node.func.id if isinstance(node.func, ast.Name) else getattr(node.func, "attr", None)
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
        ]
        assert "update" not in called


class TestSignature:
    def test_prog_name_and_update_command_are_required_keyword_only(self):
        params = inspect.signature(check_stale).parameters
        for name in ("prog_name", "update_command"):
            assert params[name].kind is inspect.Parameter.KEYWORD_ONLY
            assert params[name].default is inspect.Parameter.empty
        assert "source_package" not in params
        assert "source_version" not in params

    def test_calling_without_prog_name_or_update_command_raises(self, tmp_path):
        with pytest.raises(TypeError):
            check_stale(DirectorySource(tmp_path))

    def test_passing_source_package_or_source_version_raises(self, tmp_path):
        source = DirectorySource(tmp_path)
        with pytest.raises(TypeError):
            check_stale(
                source,
                prog_name="awiki",
                update_command="awiki skills update",
                source_package="fixture-consumer",
            )
        with pytest.raises(TypeError):
            check_stale(
                source,
                prog_name="awiki",
                update_command="awiki skills update",
                source_version="1.2.3",
            )


class TestNotice:
    def test_one_stale_skill_prints_the_exact_stderr_line(self, tmp_path, notice_permitted):
        source = make_env(tmp_path, ("awiki-search",))
        make_stale(tmp_path, "awiki-search")

        result = call(source, tmp_path)

        captured = notice_permitted.readouterr()
        assert result is None
        assert captured.out == ""
        assert captured.err == (
            "awiki: a skills update is available for 1 skill (awiki-search);"
            " run `awiki skills update`\n"
        )

    def test_two_stale_skills_pluralize_and_sort_names(self, tmp_path, notice_permitted):
        source = make_env(tmp_path, ("beta", "alpha"))
        make_stale(tmp_path, "alpha")
        make_stale(tmp_path, "beta")

        call(source, tmp_path)

        captured = notice_permitted.readouterr()
        assert captured.out == ""
        assert captured.err == (
            "awiki: a skills update is available for 2 skills (alpha, beta);"
            " run `awiki skills update`\n"
        )

    def test_fresh_install_is_silent(self, tmp_path, notice_permitted):
        source = make_env(tmp_path, ("awiki-search",))

        result = call(source, tmp_path)

        captured = notice_permitted.readouterr()
        assert result is None
        assert captured.out == ""
        assert captured.err == ""


class TestNeverMutatesOrConsumes:
    def test_installed_content_and_stamp_are_untouched(self, tmp_path, notice_permitted):
        source = make_env(tmp_path, ("awiki-search",))
        make_stale(tmp_path, "awiki-search")
        installed = tmp_path / "home" / ".claude" / "skills"
        before = snapshot(installed)

        call(source, tmp_path)

        assert snapshot(installed) == before
        assert before  # the snapshot actually covered installed files

    def test_a_prewritten_stdin_line_is_still_readable_verbatim(
        self, tmp_path, notice_permitted, monkeypatch
    ):
        source = make_env(tmp_path, ("awiki-search",))
        make_stale(tmp_path, "awiki-search")
        monkeypatch.setattr(sys, "stdin", io.StringIO("sentinel line\n"))

        call(source, tmp_path)

        assert sys.stdin.readline() == "sentinel line\n"


class TestSafeHook:
    def test_internal_errors_are_swallowed(self, tmp_path, notice_permitted, monkeypatch):
        source = make_env(tmp_path, ("awiki-search",))
        make_stale(tmp_path, "awiki-search")

        def boom(*args, **kwargs):
            raise RuntimeError("status exploded")

        monkeypatch.setattr(agentsquire.staleness, "status", boom)

        result = call(source, tmp_path)

        captured = notice_permitted.readouterr()
        assert result is None
        assert captured.out == ""
        assert captured.err == ""

    def test_wrapper_process_keeps_stdout_and_exit_code(self, tmp_path):
        make_env(tmp_path, ("awiki-search",))
        make_stale(tmp_path, "awiki-search")
        script = tmp_path / "consumer.py"
        script.write_text(CONSUMER_SCRIPT)

        proc = subprocess.run(
            [sys.executable, str(script), str(tmp_path)],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=30,
            env={**os.environ, "PYTHONPATH": str(SRC)},
        )

        assert proc.returncode == 0
        assert proc.stdout == b"COMMAND OUTPUT\n"
