"""T-06 / REQ-08, REQ-09, REQ-10, REQ-01: the `squire guide` command.

Bare `guide` lists the topics; `guide <topic>` pages the canonical doc via
click.echo; an unknown topic is a clean non-zero error naming the valid topics.
Content resolves from the packaged agentsquire/_docs (so it works from an
installed wheel), falling back to the repo docs/ + README only in a source
checkout. The wheel-resolution claim is proved by build-and-install, following
the tests/test_bundled_source.py pattern.
"""

import subprocess
import sys
from pathlib import Path

from agentsquire.console import main
from click.testing import CliRunner

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Topic -> a heading known to appear only in that topic's canonical source.
TOPIC_HEADINGS = {
    "api": "# AgentSquire Python API reference",
    "harnesses": "# Harness reference",
    "integration": "## Consumer integration guide",
}


def invoke(*args):
    # Suppress the root staleness notice so guide output is deterministic.
    return CliRunner().invoke(
        main, list(args), env={"AGENTSQUIRE_NO_UPDATE_CHECK": "1"}
    )


def test_root_help_lists_the_guide_command():
    # REQ-01: guide is mounted on the root group alongside skills.
    result = invoke("--help")
    assert result.exit_code == 0
    assert "guide" in result.output


def test_bare_guide_lists_the_three_topics():
    # REQ-08: no argument -> exit 0, listing api, harnesses, integration.
    result = invoke("guide")
    assert result.exit_code == 0
    for topic in TOPIC_HEADINGS:
        assert topic in result.output


def test_guide_topic_pages_its_canonical_doc():
    # REQ-09: each topic prints its own doc's known heading.
    for topic, heading in TOPIC_HEADINGS.items():
        result = invoke("guide", topic)
        assert result.exit_code == 0, result.output
        assert heading in result.output


def test_unknown_topic_is_a_clean_error_naming_valid_topics():
    # REQ-09: a bogus topic exits non-zero and names the valid topics.
    result = invoke("guide", "bogus")
    assert result.exit_code != 0
    for topic in TOPIC_HEADINGS:
        assert topic in result.output


def test_guide_resolves_from_the_installed_wheel(tmp_path):
    """REQ-10: with only the built wheel on the path (no repo checkout),
    `squire guide api` still prints api.md content - proving it resolves from
    the packaged agentsquire/_docs, not the source tree."""
    outdir = tmp_path / "dist"
    subprocess.run(
        [
            sys.executable, "-m", "build", "--wheel", "--no-isolation",
            "--outdir", str(outdir),
        ],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
    )
    wheel = next(outdir.glob("*.whl"))

    site = tmp_path / "site"
    subprocess.run(
        [
            sys.executable, "-m", "pip", "install",
            "--no-deps", "--no-index", "--target", str(site), str(wheel),
        ],
        check=True,
        capture_output=True,
    )

    # Runner asserts agentsquire imports from the wheel-only site (not the
    # editable source install), then runs `guide api`. Running outside the repo
    # with PYTHONPATH=site means the source-checkout fallback cannot reach the
    # repo docs/, so a printed heading can only come from the packaged _docs.
    runner = tmp_path / "run_guide.py"
    runner.write_text(
        "import sys\n"
        "import agentsquire\n"
        "assert agentsquire.__file__.startswith(sys.argv[1]), agentsquire.__file__\n"
        "from agentsquire.console import main\n"
        "main(args=sys.argv[2:], prog_name='squire', standalone_mode=False)\n"
    )
    result = subprocess.run(
        [sys.executable, str(runner), str(site), "guide", "api"],
        cwd=tmp_path,
        env={
            "PYTHONPATH": str(site),
            "AGENTSQUIRE_NO_UPDATE_CHECK": "1",
            "PATH": "/usr/bin:/bin",
        },
        check=True,
        capture_output=True,
        text=True,
    )
    assert TOPIC_HEADINGS["api"] in result.stdout
