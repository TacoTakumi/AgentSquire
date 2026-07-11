"""The mounted CLI surfaces a DuplicateSkillError as a clean failure (REQ-04).

A consumer whose two roots (package-data skills and repo-level _repo_skills)
both provide the same skill name is a disjoint-or-die packaging mistake. Running
any verb through the mounted group must exit non-zero with a human-readable
message naming the colliding skill and both roots - never an uncaught traceback.
"""

import importlib
import sys
from pathlib import Path

from click.testing import CliRunner

from agentsquire.cli import skills_command_group

SKILL = "---\nname: {name}\ndescription: A fixture skill.\n---\n\n{name} body\n"


def write_skill(root: Path, name: str) -> None:
    skill = root / name
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(SKILL.format(name=name))


def colliding_pkg(base, package, monkeypatch):
    """A package whose Root A (skills/) and Root B (_repo_skills/) both provide
    'clash' - the two roots collide."""
    pkg = base / "site" / package
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text('__version__ = "1.0.0"\n')
    write_skill(pkg / "skills", "clash")
    write_skill(pkg / "_repo_skills", "clash")
    monkeypatch.syspath_prepend(str(base / "site"))
    monkeypatch.delitem(sys.modules, package, raising=False)
    importlib.invalidate_caches()
    return package


def home_with_claude(base):
    home = base / "home"
    (home / ".claude").mkdir(parents=True)
    project = base / "project"
    project.mkdir()
    return home, project


def invoke(app, *args):
    # catch_exceptions=False: a raw (untranslated) DuplicateSkillError would
    # escape and error the test - so passing proves the CLI translated it.
    return CliRunner().invoke(app, args, catch_exceptions=False)


def test_status_on_colliding_roots_is_a_clean_named_failure(tmp_path, monkeypatch):
    pkg = colliding_pkg(tmp_path, "dupcli_pkg", monkeypatch)
    home, project = home_with_claude(tmp_path)
    group = skills_command_group(pkg, home=home, project=project)

    result = invoke(group, "status")

    assert result.exit_code != 0
    assert "clash" in result.output
    assert f"{pkg}/skills" in result.output       # Root A named
    assert f"{pkg}/_repo_skills" in result.output  # Root B named
    assert "Traceback" not in result.output


def test_install_on_colliding_roots_is_a_clean_named_failure(tmp_path, monkeypatch):
    pkg = colliding_pkg(tmp_path, "dupcli_install_pkg", monkeypatch)
    home, project = home_with_claude(tmp_path)
    group = skills_command_group(pkg, home=home, project=project)

    result = invoke(group, "install", "--no-input")

    assert result.exit_code != 0
    assert "clash" in result.output
    assert "Traceback" not in result.output
    assert not (home / ".claude" / "skills" / "clash").exists()
