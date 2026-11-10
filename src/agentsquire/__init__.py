"""AgentSquire: ship agent integrations inside a Python package and install
them into whatever agent harness is present.

The full lifecycle is available as plain Python (REQ-16), no CLI required:
enumerate skills from a source, detect harnesses, then install / status /
update / uninstall. See docs/api.md for the reference.
"""

__version__ = "0.6.1"

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
from agentsquire.release import ReleaseCheck, ReleaseStatus, check_for_update
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
    DuplicateSkillError,
    FirstAvailableSource,
    SkillSource,
    SourceSkill,
    UnionSource,
    default_source,
    verify_skill_roots,
)
from agentsquire.staleness import check_stale, notify_update
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
    "UnionSource",
    "FirstAvailableSource",
    "DuplicateSkillError",
    "default_source",
    "verify_skill_roots",
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
    # release check
    "ReleaseCheck",
    "ReleaseStatus",
    "check_for_update",
    "notify_update",
    "check_update_command",
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


def __getattr__(name: str):
    """Load check_update_command at first use.

    The command builder lives in agentsquire.cli, which imports click. A
    program that uses the Python API only does not pay for that import.
    """
    if name == "check_update_command":
        from agentsquire.cli import check_update_command

        globals()[name] = check_update_command
        return check_update_command
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
