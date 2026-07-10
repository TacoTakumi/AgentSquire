"""Proactive staleness check hook (REQ-17).

A consumer script calls check_stale() at startup, then does its own work.
Run under a pty with a stale install, the hook announces and offers to
update, and accepting runs the update. Run without a TTY it never prompts or
blocks, writes nothing to stdout, emits at most one stderr notice line, and
leaves the exit code untouched. Local-only.
"""

import os
import pty
import select
import subprocess
import sys
import time
from pathlib import Path

import pytest

SRC = Path(__file__).parent.parent / "src"

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
    source_package="fixture-consumer",
    source_version="1.2.3",
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


@pytest.fixture
def env(tmp_path):
    """A root with bundle/home/project, one skill installed up to date."""
    from agentsquire.harnesses import CLAUDE_CODE
    from agentsquire.sources import DirectorySource
    from agentsquire.verbs import install

    for sub in ("home", "project", "bundle"):
        (tmp_path / sub).mkdir()
    write_skill(tmp_path / "bundle", "alpha")
    install(
        DirectorySource(tmp_path / "bundle"),
        CLAUDE_CODE,
        scope="user",
        home=tmp_path / "home",
        project=tmp_path / "project",
        source_package="fixture-consumer",
        source_version="1.2.3",
    )
    script = tmp_path / "consumer.py"
    script.write_text(CONSUMER_SCRIPT)
    return tmp_path, script


def make_stale(root: Path) -> None:
    (root / "bundle" / "alpha" / "reference.md").write_text("v2\n")


def installed_reference(root: Path) -> str:
    return (root / "home" / ".claude" / "skills" / "alpha" / "reference.md").read_text()


def run_no_tty(root: Path, script: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(script), str(root)],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        timeout=30,
        env={**os.environ, "PYTHONPATH": str(SRC)},
    )


def run_in_pty(root: Path, script: Path, answer: bytes, timeout: float = 30.0) -> str:
    """Run the consumer under a pty, sending answer when the prompt appears."""
    master, slave = pty.openpty()
    proc = subprocess.Popen(
        [sys.executable, str(script), str(root)],
        stdin=slave,
        stdout=slave,
        stderr=slave,
        env={**os.environ, "PYTHONPATH": str(SRC)},
    )
    os.close(slave)
    output = b""
    answered = False
    deadline = time.monotonic() + timeout
    try:
        while time.monotonic() < deadline:
            ready, _, _ = select.select([master], [], [], 0.2)
            if ready:
                try:
                    chunk = os.read(master, 4096)
                except OSError:
                    break
                if not chunk:
                    break
                output += chunk
                if not answered and b"[y/N]" in output:
                    os.write(master, answer)
                    answered = True
            elif proc.poll() is not None:
                break
        else:
            proc.kill()
            pytest.fail(f"consumer did not finish; output so far: {output!r}")
    finally:
        os.close(master)
        proc.wait(timeout=10)
    return output.decode()


class TestNonTty:
    def test_fresh_case_is_silent(self, env):
        root, script = env

        proc = run_no_tty(root, script)

        assert proc.returncode == 0
        assert proc.stdout == b"COMMAND OUTPUT\n"
        assert proc.stderr == b""

    def test_stale_case_never_blocks_and_keeps_stdout_and_exit_code(self, env):
        root, script = env
        fresh = run_no_tty(root, script)
        make_stale(root)

        proc = run_no_tty(root, script)

        assert proc.returncode == fresh.returncode == 0
        assert proc.stdout == fresh.stdout  # byte-identical stdout
        stderr_lines = proc.stderr.decode().splitlines()
        assert len(stderr_lines) <= 1
        assert "update" in stderr_lines[0].lower()
        # no update actually ran
        assert installed_reference(root) == "reference for alpha\n"


class TestTty:
    def test_announces_prompts_and_yes_runs_the_update(self, env):
        root, script = env
        make_stale(root)

        output = run_in_pty(root, script, b"y\n")

        assert "new version" in output
        assert "[y/N]" in output
        assert "COMMAND OUTPUT" in output
        assert installed_reference(root) == "v2\n"

    def test_declining_leaves_the_install_alone(self, env):
        root, script = env
        make_stale(root)

        output = run_in_pty(root, script, b"n\n")

        assert "[y/N]" in output
        assert "COMMAND OUTPUT" in output
        assert installed_reference(root) == "reference for alpha\n"

    def test_fresh_case_shows_no_prompt(self, env):
        root, script = env

        output = run_in_pty(root, script, b"")

        assert "[y/N]" not in output
        assert "COMMAND OUTPUT" in output
