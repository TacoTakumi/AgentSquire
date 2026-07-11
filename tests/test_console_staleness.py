"""T-04 / REQ-06: the squire root callback wires check_stale, so any subcommand
emits exactly one stderr update notice - naming 'squire skills update' - without
touching stdout or the exit code, and the suppression env vars silence it.

The hook is wired the production way (no home=/project=); these tests redirect
the roots with AGENTSQUIRE_HOME / AGENTSQUIRE_PROJECT."""

import os
import subprocess
import sys
from pathlib import Path

from agentsquire.console import main
from agentsquire.harnesses import CLAUDE_CODE
from agentsquire.sources import DirectorySource
from agentsquire.verbs import install
from click.testing import CliRunner

SKILL = "developing-with-agentsquire"
SRC = Path(__file__).parent.parent / "src"


def stale_home(tmp_path):
    """Home + project fixtures with an installed-but-stale developing-with-agentsquire.

    An 'old' copy (content differing from the real bundled skill) is installed
    with a correct stamp, so status against BundledPackageDataSource('agentsquire')
    - the source the console wires - classifies it UPDATE_AVAILABLE."""
    home = tmp_path / "home"
    project = tmp_path / "project"
    (home / ".claude").mkdir(parents=True)
    project.mkdir()

    bundle = tmp_path / "old-bundle"
    old = bundle / SKILL
    old.mkdir(parents=True)
    (old / "SKILL.md").write_text(
        f"---\nname: {SKILL}\ndescription: An older bundled copy.\n---\n\nold body\n"
    )
    install(
        DirectorySource(bundle), CLAUDE_CODE, scope="user",
        home=home, project=project,
        source_package="agentsquire", source_version="0.0.1",
    )
    return home, project


def env_for(home, project, **extra):
    return {"AGENTSQUIRE_HOME": str(home), "AGENTSQUIRE_PROJECT": str(project), **extra}


def run(home, project, **extra_env):
    return CliRunner().invoke(
        main, ["skills", "status", "--scope", "user"],
        env=env_for(home, project, **extra_env), catch_exceptions=False,
    )


def test_stale_install_emits_exactly_one_update_notice_on_stderr(tmp_path):
    home, project = stale_home(tmp_path)

    result = run(home, project)

    assert result.exit_code == 0
    notices = result.stderr.splitlines()
    assert len(notices) == 1
    assert "squire skills update" in notices[0]
    assert SKILL in notices[0]


def test_notice_is_stderr_only_and_leaves_stdout_intact(tmp_path):
    home, project = stale_home(tmp_path)

    result = run(home, project)

    # stdout is exactly the subcommand's own output; the notice never leaks in.
    assert "a skills update is available" not in result.stdout
    assert SKILL in result.stdout


def test_ci_env_suppresses_the_notice(tmp_path):
    home, project = stale_home(tmp_path)

    result = run(home, project, CI="1")

    assert result.exit_code == 0
    assert result.stderr == ""


def test_no_update_check_env_suppresses_the_notice(tmp_path):
    home, project = stale_home(tmp_path)

    result = run(home, project, AGENTSQUIRE_NO_UPDATE_CHECK="1")

    assert result.exit_code == 0
    assert result.stderr == ""


def test_real_entry_point_keeps_stdout_stderr_and_exit_code_separate(tmp_path):
    # Strongest evidence: the wired callback fires before dispatch in a real
    # process, the notice lands on stderr, and stdout/exit code are untouched.
    home, project = stale_home(tmp_path)
    env = {k: v for k, v in os.environ.items() if k not in ("CI", "AGENTSQUIRE_NO_UPDATE_CHECK")}
    env.update({
        "PYTHONPATH": str(SRC),
        "AGENTSQUIRE_HOME": str(home),
        "AGENTSQUIRE_PROJECT": str(project),
    })

    proc = subprocess.run(
        [sys.executable, "-c",
         "import sys; sys.argv = ['squire', 'skills', 'status', '--scope', 'user'];"
         " from agentsquire.console import main; main()"],
        stdin=subprocess.DEVNULL, capture_output=True, timeout=60, env=env,
    )

    assert proc.returncode == 0
    assert SKILL.encode() in proc.stdout
    assert b"squire skills update" in proc.stderr
    assert b"a skills update is available" not in proc.stdout
