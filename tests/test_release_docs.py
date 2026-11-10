"""The release check is documented, and the README example runs.

README.md, docs/api.md and the CHANGELOG.md section of the release that added
the release check each name its five public names. The API reference states the two
facts a consumer relies on. The three files are ASCII only. The README
example is extracted and run against a fake PyPI answer, so it can only
drift from the working API by failing here.
"""

import json
import re
import sys
from pathlib import Path

import pytest
from click.testing import CliRunner

import agentsquire
import agentsquire._pypi
import agentsquire._release_cache

ROOT = Path(__file__).parent.parent
README = ROOT / "README.md"
API = ROOT / "docs" / "api.md"
CHANGELOG = ROOT / "CHANGELOG.md"

NAMES = [
    "check_for_update",
    "notify_update",
    "check_update_command",
    "ReleaseCheck",
    "ReleaseStatus",
]

STATUS_VALUES = ["up-to-date", "update-available", "ahead", "unknown", "check-failed"]


# The release that added the release check. Its changelog section names the
# public names; a later section has no reason to repeat them.
RELEASE_CHECK_VERSION = "0.6.0"


def release_check_changelog_section() -> str:
    """The text of the changelog section of the release that added the check."""
    chunks = re.split(r"^## \[", CHANGELOG.read_text(encoding="utf-8"), flags=re.MULTILINE)
    prefix = RELEASE_CHECK_VERSION + "]"
    section = next((chunk for chunk in chunks[1:] if chunk.startswith(prefix)), None)
    assert section, f"the changelog has no {RELEASE_CHECK_VERSION} section"
    return section


def api_release_section() -> str:
    """The text of the "Release check" section of the API reference."""
    text = API.read_text(encoding="utf-8")
    match = re.search(r"^## Release check\n(.*?)(?=^## )", text, flags=re.DOTALL | re.MULTILINE)
    assert match, "docs/api.md has no 'Release check' section"
    return match.group(1)


def one_line(text: str) -> str:
    """The text with each run of whitespace as one space."""
    return " ".join(text.split())


def release_snippet() -> str:
    """The one python block of the README that mounts check-update."""
    blocks = re.findall(r"```python\n(.*?)```", README.read_text(encoding="utf-8"), flags=re.DOTALL)
    matches = [block for block in blocks if "check_update_command" in block]
    assert len(matches) == 1, "expected exactly one README block with check_update_command"
    return matches[0]


@pytest.mark.parametrize("name", NAMES)
def test_readme_names_each_public_name(name):
    assert name in README.read_text(encoding="utf-8")


@pytest.mark.parametrize("name", NAMES)
def test_api_reference_names_each_public_name(name):
    assert name in api_release_section()


@pytest.mark.parametrize("name", NAMES)
def test_release_check_changelog_section_names_each_public_name(name):
    assert name in release_check_changelog_section()


@pytest.mark.parametrize("name", NAMES)
def test_each_documented_name_is_exported(name):
    assert name in agentsquire.__all__


def test_api_release_section_comes_after_the_staleness_section():
    text = API.read_text(encoding="utf-8")
    assert text.index("## Staleness check hook") < text.index("## Release check")


def test_api_reference_states_that_notify_update_makes_no_request():
    assert "notify_update makes no request" in one_line(api_release_section())


def test_api_reference_states_the_exit_code_rule_of_check_update():
    assert "check-update exits non-zero only for a failed check" in one_line(
        api_release_section()
    )


@pytest.mark.parametrize("value", STATUS_VALUES)
def test_api_reference_lists_each_status_value(value):
    assert f'"{value}"' in api_release_section()


@pytest.mark.parametrize("doc", [README, API, CHANGELOG], ids=lambda path: path.name)
def test_document_is_ascii_only(doc):
    text = doc.read_text(encoding="utf-8")
    bad = [
        f"line {number}: {line.strip()[:60]}"
        for number, line in enumerate(text.splitlines(), start=1)
        if not line.isascii()
    ]
    assert bad == []


def test_readme_snippet_does_not_match_the_other_snippet_searches():
    snippet = release_snippet()
    for marker in ("check_stale", "@click.group()", "typer.Typer()"):
        assert marker not in snippet


def test_readme_release_snippet_runs_against_a_fake(tmp_path, monkeypatch, capsys):
    pkg = tmp_path / "pkgroot" / "your_pkg"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text('__version__ = "1.2.3"\n')
    monkeypatch.syspath_prepend(str(tmp_path / "pkgroot"))
    monkeypatch.delitem(sys.modules, "your_pkg", raising=False)

    # A private cache, no notice gate and an environment with no known
    # install method, so the lines carry no upgrade command.
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.setattr(agentsquire._release_cache, "_is_windows", lambda: False)
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.delenv("AGENTSQUIRE_NO_UPDATE_CHECK", raising=False)
    prefix = tmp_path / "plain-venv"
    prefix.mkdir()
    monkeypatch.setattr(sys, "prefix", str(prefix))

    urls = []

    def fake_fetch(url):
        urls.append(url)
        return json.dumps({"info": {"version": "9.0.0"}}).encode()

    monkeypatch.setattr(agentsquire._pypi, "fetch", fake_fetch)

    namespace = {}
    exec(compile(release_snippet(), "<README snippet>", "exec"), namespace)
    line = "your-cli: a new release is available: 1.2.3 -> 9.0.0\n"

    # Startup with no cache: no notice and no request.
    monkeypatch.setattr(sys, "argv", ["your-cli", "--help"])
    with pytest.raises(SystemExit) as stopped:
        namespace["main"]()
    assert stopped.value.code == 0
    assert capsys.readouterr().err == ""
    assert urls == []

    # The mounted command asks the fake and reports the newer release.
    result = CliRunner().invoke(namespace["cli"], ["check-update"])
    assert result.exit_code == 0
    assert result.output == line
    assert urls == ["https://pypi.org/pypi/your-dist/json"]

    # Startup after the check: the notice comes from the cache, with no
    # second request.
    with pytest.raises(SystemExit) as stopped:
        namespace["main"]()
    assert stopped.value.code == 0
    assert capsys.readouterr().err == line
    assert urls == ["https://pypi.org/pypi/your-dist/json"]
