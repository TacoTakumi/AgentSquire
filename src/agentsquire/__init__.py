"""AgentSquire: ship agent integrations inside a Python package and install
them into whatever agent harness is present.

The full lifecycle is available as plain Python (REQ-16), no CLI required:
enumerate skills from a source, detect harnesses, then install / status /
update / uninstall. See docs/api.md for the reference.
"""

__version__ = "0.2.2"

from agentsquire.harnesses import (
    CLAUDE_CODE,
    HERMES,
    OPENCODE,
    PI,
    HarnessBackend,
    HarnessNotDetectedError,
    HarnessRegistry,
    UnknownHarnessError,
    UnsupportedScopeError,
    default_registry,
)
from agentsquire.hashing import STAMP_KEY, skill_content_hash
from agentsquire.skills import (
    InvalidSkillError,
    Skill,
    SkillViolation,
    load_skill,
    validate_skill_dir,
)
from agentsquire.sources import (
    ENTRY_POINT_GROUP,
    BundledPackageDataSource,
    DirectorySource,
    SkillSource,
    SourceSkill,
)
from agentsquire.staleness import check_stale
from agentsquire.stamping import StampError, read_stamp
from agentsquire.verbs import (
    InstalledSkill,
    InstallResult,
    RemovedSkill,
    SkillState,
    SkillStatus,
    SkippedSkill,
    UninstallResult,
    UpdateResult,
    install,
    status,
    uninstall,
    update,
)

__all__ = [
    "__version__",
    # skill model
    "Skill",
    "SkillViolation",
    "InvalidSkillError",
    "validate_skill_dir",
    "load_skill",
    # hashing / provenance
    "skill_content_hash",
    "STAMP_KEY",
    "read_stamp",
    "StampError",
    # sources (enumerate)
    "SkillSource",
    "SourceSkill",
    "DirectorySource",
    "BundledPackageDataSource",
    "ENTRY_POINT_GROUP",
    # harnesses (detect)
    "HarnessBackend",
    "HarnessRegistry",
    "default_registry",
    "UnknownHarnessError",
    "HarnessNotDetectedError",
    "UnsupportedScopeError",
    "CLAUDE_CODE",
    "PI",
    "HERMES",
    "OPENCODE",
    # staleness hook
    "check_stale",
    # lifecycle verbs
    "install",
    "status",
    "update",
    "uninstall",
    "SkillState",
    "SkillStatus",
    "InstalledSkill",
    "SkippedSkill",
    "RemovedSkill",
    "InstallResult",
    "UpdateResult",
    "UninstallResult",
]
