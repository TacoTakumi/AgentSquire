"""Deterministic content hash over a skill directory.

The hash covers every file under the skill directory, sorted by relative path
so filesystem ordering never matters. SKILL.md is hashed in canonical form —
frontmatter minus the provenance stamp (``metadata.agentsquire``), dumped with
sorted keys, plus the body — so a freshly stamped install hashes back to its
own stamped value even though stamping rewrites the frontmatter bytes.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import yaml

# The provenance stamp lives under this key in the SKILL.md frontmatter
# "metadata" map (spec-legal free-form map per agentskills.io).
STAMP_KEY = "agentsquire"


def _canonical_skill_md(text: str) -> bytes:
    """SKILL.md content with the stamp stripped and frontmatter canonicalized."""
    if not text.startswith("---"):
        return text.encode()
    parts = text.split("---", 2)
    if len(parts) < 3:
        return text.encode()
    try:
        frontmatter = yaml.safe_load(parts[1])
    except yaml.YAMLError:
        return text.encode()
    if not isinstance(frontmatter, dict):
        return text.encode()

    metadata = frontmatter.get("metadata")
    if isinstance(metadata, dict):
        metadata.pop(STAMP_KEY, None)
    if not metadata and "metadata" in frontmatter:
        del frontmatter["metadata"]

    canonical_fm = yaml.safe_dump(frontmatter, sort_keys=True)
    return f"---\n{canonical_fm}---{parts[2]}".encode()


def skill_content_hash(path: Path) -> str:
    """Deterministic hash of a skill directory, excluding the provenance stamp."""
    digest = hashlib.sha256()
    for file in sorted(p for p in path.rglob("*") if p.is_file()):
        relpath = file.relative_to(path).as_posix()
        if relpath == "SKILL.md":
            content = _canonical_skill_md(file.read_text())
        else:
            content = file.read_bytes()
        digest.update(relpath.encode())
        digest.update(b"\0")
        digest.update(hashlib.sha256(content).digest())
        digest.update(b"\0")
    return f"sha256:{digest.hexdigest()}"
