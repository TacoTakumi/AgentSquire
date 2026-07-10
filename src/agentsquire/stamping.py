"""Provenance stamp read/write in SKILL.md frontmatter (``metadata.agentsquire``).

The stamp is spliced into the frontmatter textually so every non-stamp byte —
frontmatter and body — is unchanged from the source, then the result is
re-parsed and checked against the expected mapping; a splice that would alter
or lose anything raises instead of installing a corrupted SKILL.md.
"""

from __future__ import annotations

import re
import textwrap

import yaml

from agentsquire.hashing import STAMP_KEY


class StampError(Exception):
    """Stamping could not proceed without altering non-stamp content."""


def read_stamp(text: str) -> dict | None:
    """The stamp mapping from SKILL.md text, or None if absent/unparseable."""
    if not text.startswith("---"):
        return None
    parts = text.split("---", 2)
    if len(parts) < 3:
        return None
    try:
        frontmatter = yaml.safe_load(parts[1])
    except yaml.YAMLError:
        return None
    if not isinstance(frontmatter, dict):
        return None
    metadata = frontmatter.get("metadata")
    if not isinstance(metadata, dict):
        return None
    stamp = metadata.get(STAMP_KEY)
    return stamp if isinstance(stamp, dict) else None


def stamped_skill_md(text: str, stamp: dict) -> str:
    """SKILL.md text with the stamp added under the frontmatter metadata map."""
    parts = text.split("---", 2)
    if not text.startswith("---") or len(parts) < 3:
        raise StampError("SKILL.md has no frontmatter block to stamp")
    frontmatter_text, body = parts[1], parts[2]
    frontmatter = yaml.safe_load(frontmatter_text)
    if not isinstance(frontmatter, dict):
        raise StampError("SKILL.md frontmatter is not a mapping")

    stamp_block = textwrap.indent(
        yaml.safe_dump({STAMP_KEY: dict(stamp)}, sort_keys=True), "  "
    )
    if not frontmatter_text.endswith("\n"):
        frontmatter_text += "\n"
    if "metadata" not in frontmatter:
        new_frontmatter = frontmatter_text + "metadata:\n" + stamp_block
    else:
        opener = re.search(r"^metadata:[ \t]*$", frontmatter_text, flags=re.MULTILINE)
        if opener is None:
            raise StampError("existing metadata map is not in block style; cannot stamp")
        insert_at = opener.end() + 1  # just past the metadata: line's newline
        new_frontmatter = (
            frontmatter_text[:insert_at] + stamp_block + frontmatter_text[insert_at:]
        )

    stamped = f"---{new_frontmatter}---{body}"
    expected = dict(frontmatter)
    expected["metadata"] = {**frontmatter.get("metadata", {}), STAMP_KEY: dict(stamp)}
    if yaml.safe_load(stamped.split("---", 2)[1]) != expected:
        raise StampError("stamping would alter existing frontmatter; refusing")
    return stamped
