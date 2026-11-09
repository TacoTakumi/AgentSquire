"""README consumer-guide snippets import and execute (REQ-15/16/20).

The integration guide's mount snippets (click and typer), staleness hook
snippet, and entry-point registration line are extracted from README.md and
run against a fixture consumer package literally named ``your_pkg`` - the
name the snippets use - so the guide can only drift from the working API by
failing here.
"""

import re
import sys
import tomllib
from pathlib import Path

import pytest
from click.testing import CliRunner

import agentsquire as sq

README = Path(__file__).parent.parent / "README.md"
BUNDLED_SKILL = (
    Path(__file__).parent.parent
    / "src"
    / "agentsquire"
    / "skills"
    / "developing-with-agentsquire"
    / "SKILL.md"
)
SKILL_MD = "---\nname: alpha\ndescription: A fixture skill.\n---\n\nbody\n"


def blocks(language: str, doc: Path = README) -> list[str]:
    pattern = rf"```{language}\n(.*?)```"
    return re.findall(pattern, doc.read_text(), flags=re.DOTALL)


def block_containing(language: str, marker: str, doc: Path = README) -> str:
    matches = [b for b in blocks(language, doc) if marker in b]
    assert matches, f"no {language} block containing {marker!r} in {doc.name}"
    assert len(matches) == 1, f"ambiguous {language} blocks for {marker!r}"
    return matches[0]


@pytest.fixture
def your_pkg(tmp_path, monkeypatch):
    """An importable consumer package named exactly as the snippets name it."""
    pkg = tmp_path / "pkgroot" / "your_pkg"
    skill = pkg / "skills" / "alpha"
    skill.mkdir(parents=True)
    (pkg / "__init__.py").write_text('__version__ = "1.2.3"\n')
    (skill / "SKILL.md").write_text(SKILL_MD)
    monkeypatch.syspath_prepend(str(tmp_path / "pkgroot"))
    monkeypatch.delitem(sys.modules, "your_pkg", raising=False)

    home = tmp_path / "home"
    project = tmp_path / "project"
    (home / ".claude").mkdir(parents=True)
    project.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.chdir(project)
    return home


def run_snippet(code: str) -> dict:
    namespace = {}
    exec(compile(code, "<README snippet>", "exec"), namespace)
    return namespace


def test_click_mount_snippet_executes_all_four_verbs(your_pkg):
    home = your_pkg
    cli = run_snippet(block_containing("python", "@click.group()"))["cli"]
    runner = CliRunner()

    assert runner.invoke(cli, ["skills", "install"]).exit_code == 0
    assert (home / ".claude" / "skills" / "alpha").is_dir()
    assert "up-to-date" in runner.invoke(cli, ["skills", "status"]).output
    assert runner.invoke(cli, ["skills", "update"]).exit_code == 0
    assert runner.invoke(cli, ["skills", "uninstall"]).exit_code == 0
    assert not (home / ".claude" / "skills" / "alpha").exists()


def test_typer_mount_snippet_executes_all_four_verbs(your_pkg):
    home = your_pkg
    cli = run_snippet(block_containing("python", "typer.Typer()"))["cli"]
    runner = CliRunner()

    assert runner.invoke(cli, ["skills", "install"]).exit_code == 0
    assert (home / ".claude" / "skills" / "alpha").is_dir()
    assert runner.invoke(cli, ["skills", "uninstall"]).exit_code == 0


def test_staleness_hook_snippet_runs_silently_without_a_tty(your_pkg, capsys):
    main = run_snippet(block_containing("python", "check_stale"))["main"]

    assert main() is None
    assert capsys.readouterr().out == ""  # nothing on stdout off-TTY (REQ-17)


@pytest.mark.parametrize("doc", [README, BUNDLED_SKILL], ids=["readme", "skill"])
def test_staleness_hook_snippet_checks_the_default_two_root_source(doc):
    snippet = block_containing("python", "check_stale", doc)

    assert "from agentsquire import check_stale, default_source" in snippet
    assert 'default_source("your_pkg")' in snippet
    assert "BundledPackageDataSource" not in snippet


def test_bundled_skill_staleness_snippet_runs_silently_without_a_tty(your_pkg, capsys):
    snippet = block_containing("python", "check_stale", BUNDLED_SKILL)
    main = run_snippet(snippet)["main"]

    assert main() is None
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize("doc", [README, BUNDLED_SKILL], ids=["readme", "skill"])
def test_staleness_hook_snippet_notices_a_stale_repo_level_skill(
    doc, your_pkg, tmp_path, monkeypatch, capsys
):
    """A consumer that also ships repo-level skills gets a notice for them."""
    home = your_pkg
    repo = tmp_path / "pkgroot"  # the checkout root: pyproject.toml + skills/
    (repo / "pyproject.toml").write_text('[project]\nname = "your-pkg"\n')
    beta = repo / "skills" / "beta"
    beta.mkdir(parents=True)
    (beta / "SKILL.md").write_text(SKILL_MD.replace("alpha", "beta"))
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.delenv("AGENTSQUIRE_NO_UPDATE_CHECK", raising=False)

    source = sq.default_source("your_pkg")
    assert sorted(s.name for s in source.list_skills()) == ["alpha", "beta"]
    sq.install(
        source,
        sq.CLAUDE_CODE,
        scope="user",
        home=home,
        project=tmp_path / "project",
        source_package="your_pkg",
        source_version="1.2.3",
    )
    (beta / "reference.md").write_text("a newer shipped copy\n")

    main = run_snippet(block_containing("python", "check_stale", doc))["main"]

    assert main() is None
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "beta" in captured.err
    assert "alpha" not in captured.err


def test_entry_point_snippet_registers_under_the_documented_group():
    registration = tomllib.loads(block_containing("toml", "entry-points"))
    group = registration["project"]["entry-points"][sq.ENTRY_POINT_GROUP]
    assert list(group.values()) == [list(group)[0]]  # value names the package


def test_guide_explains_the_provenance_and_update_model():
    text = README.read_text()
    for term in ("provenance", "content_hash", "locally", "--force", "no network"):
        assert term in text, f"guide never mentions {term!r}"
