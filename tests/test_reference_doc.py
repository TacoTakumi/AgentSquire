"""Structural completeness of the harness reference document (REQ-06).

Every supported harness has an entry with all four fields filled: skill
directories per scope, discovery/precedence behaviour, official doc URLs,
and the location of a local source checkout used as evidence. A harness
lacking a scope (or lacking public docs/source) records that explicitly —
the field is still filled.
"""

import re
from pathlib import Path

import pytest

DOC = Path(__file__).parent.parent / "docs" / "harnesses.md"

HARNESSES = ["Claude Code", "pi", "Hermes", "opencode"]
FIELDS = [
    "Skill directories per scope",
    "Discovery / precedence",
    "Official docs",
    "Local source checkout",
]
SCOPES = ["user", "project"]


def parse_sections() -> dict[str, str]:
    text = DOC.read_text()
    chunks = re.split(r"^## ", text, flags=re.MULTILINE)[1:]
    return {chunk.splitlines()[0].strip(): chunk for chunk in chunks}


def field_body(section: str, field: str) -> str:
    """Content of one **Field:** up to the next field label or section end."""
    pattern = rf"\*\*{re.escape(field)}:\*\*(.*?)(?=\n- \*\*|\Z)"
    match = re.search(pattern, section, flags=re.DOTALL)
    assert match, f"field {field!r} missing"
    return match.group(1)


def test_document_exists():
    assert DOC.is_file()


def test_all_four_harnesses_have_entries():
    assert sorted(parse_sections()) == sorted(HARNESSES)


@pytest.mark.parametrize("harness", HARNESSES)
@pytest.mark.parametrize("field", FIELDS)
def test_every_field_is_filled(harness, field):
    section = parse_sections()[harness]

    body = field_body(section, field)

    assert body.strip(), f"{harness}: field {field!r} is empty"


@pytest.mark.parametrize("harness", HARNESSES)
@pytest.mark.parametrize("scope", SCOPES)
def test_each_scope_recorded_with_a_path_or_explicit_none(harness, scope):
    section = parse_sections()[harness]
    scopes = field_body(section, "Skill directories per scope")

    line = re.search(rf"^\s*- {scope}: (.+)$", scopes, flags=re.MULTILINE)

    assert line, f"{harness}: no {scope}-scope line"
    value = line.group(1)
    assert re.search(r"`[^`]+`", value) or "none" in value.lower(), (
        f"{harness}: {scope} scope has neither a path nor an explicit none"
    )


@pytest.mark.parametrize("harness", ["Claude Code", "pi", "opencode"])
def test_public_harnesses_cite_official_doc_urls(harness):
    section = parse_sections()[harness]

    assert "http" in field_body(section, "Official docs")
