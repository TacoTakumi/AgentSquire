"""Harness backend registry: detection and explicit-name resolution (REQ-04, REQ-05).

Backends resolve skill directories per scope from the values recorded in
docs/harnesses.md; the registry detects which harnesses are present in a
fixture environment by marker directories, and resolves explicit names with
distinct errors for supported-but-undetected vs unsupported.
"""

import re
from pathlib import Path

import pytest

from agentsquire.harnesses import (
    CLAUDE_CODE,
    HarnessBackend,
    HarnessNotDetectedError,
    HarnessRegistry,
    UnknownHarnessError,
    default_registry,
)

DOC = Path(__file__).parent.parent / "docs" / "harnesses.md"


@pytest.fixture
def env(tmp_path):
    home = tmp_path / "home"
    project = tmp_path / "project"
    home.mkdir()
    project.mkdir()
    return home, project


def doc_scope_path(harness: str, scope: str) -> str:
    """The backticked path on the harness's scope line in docs/harnesses.md."""
    section = re.split(rf"^## {re.escape(harness)}$", DOC.read_text(), flags=re.MULTILINE)[1]
    section = section.split("\n## ")[0]
    line = re.search(rf"^\s*- {scope}: `([^`]+)`", section, flags=re.MULTILINE)
    assert line, f"{harness}: no backticked {scope}-scope path in the reference doc"
    return line.group(1)


class TestDetection:
    def test_not_detected_in_empty_env(self, env):
        home, project = env
        assert default_registry().detect(home=home, project=project) == []

    def test_detected_by_user_marker_dir(self, env):
        home, project = env
        (home / ".claude").mkdir()

        detected = default_registry().detect(home=home, project=project)

        assert [b.name for b in detected] == ["claude-code"]

    def test_detected_by_project_marker_dir(self, env):
        home, project = env
        (project / ".claude").mkdir()

        detected = default_registry().detect(home=home, project=project)

        assert [b.name for b in detected] == ["claude-code"]

    def test_marker_file_is_not_a_marker_dir(self, env):
        home, project = env
        (home / ".claude").write_text("not a directory")

        assert default_registry().detect(home=home, project=project) == []


class TestScopeResolution:
    def test_user_scope_resolves_to_documented_directory(self, env):
        home, project = env
        assert CLAUDE_CODE.skills_dir("user", home=home, project=project) == (
            home / ".claude" / "skills"
        )

    def test_project_scope_resolves_to_documented_directory(self, env):
        home, project = env
        assert CLAUDE_CODE.skills_dir("project", home=home, project=project) == (
            project / ".claude" / "skills"
        )

    def test_unknown_scope_is_rejected(self, env):
        home, project = env
        with pytest.raises(ValueError, match="scope"):
            CLAUDE_CODE.skills_dir("global", home=home, project=project)

    @pytest.mark.parametrize("scope", ["user", "project"])
    def test_backend_agrees_with_reference_doc(self, env, scope):
        """REQ-06: the backend carries exactly the paths the doc records."""
        home, project = env
        documented = doc_scope_path("Claude Code", scope)
        root = home if documented.startswith("~/") else project
        expected = root / documented.removeprefix("~/").rstrip("/")

        assert CLAUDE_CODE.skills_dir(scope, home=home, project=project) == expected


class TestExplicitNameResolution:
    def test_detected_harness_resolves(self, env):
        home, project = env
        (home / ".claude").mkdir()

        backend = default_registry().resolve("claude-code", home=home, project=project)

        assert backend is CLAUDE_CODE

    def test_supported_but_undetected_harness_errors_clearly(self, env):
        home, project = env
        with pytest.raises(HarnessNotDetectedError, match="not detected"):
            default_registry().resolve("claude-code", home=home, project=project)

    def test_unknown_harness_error_lists_supported_set(self, env):
        home, project = env
        registry = default_registry()

        with pytest.raises(UnknownHarnessError) as excinfo:
            registry.resolve("emacs", home=home, project=project)

        message = str(excinfo.value)
        for name in registry.names():
            assert name in message


class TestRegistryExtensibility:
    """REQ-05: harness N+1 is one backend registration, nothing else."""

    def test_dummy_backend_registers_and_participates_in_detection(self, env):
        home, project = env
        dummy = HarnessBackend(
            name="dummy",
            user_skills_dir=".dummy/skills",
            project_skills_dir=".dummy/skills",
            user_marker_dirs=(".dummy",),
            project_marker_dirs=(".dummy",),
        )
        registry = default_registry()
        registry.register(dummy)
        (home / ".dummy").mkdir()

        detected = registry.detect(home=home, project=project)

        assert [b.name for b in detected] == ["dummy"]
        assert registry.resolve("dummy", home=home, project=project) is dummy
        assert dummy.skills_dir("user", home=home, project=project) == (
            home / ".dummy" / "skills"
        )

    def test_dummy_backend_runs_the_full_verb_lifecycle(self, env, tmp_path):
        """REQ-05 acceptance: the fifth backend needs only registration to
        participate in the full verb lifecycle - the verbs never change."""
        from agentsquire.sources import DirectorySource
        from agentsquire.verbs import SkillState, install, status, uninstall, update

        home, project = env
        dummy = HarnessBackend(
            name="dummy",
            user_skills_dir=".dummy/skills",
            project_skills_dir=".dummy/skills",
            user_marker_dirs=(".dummy",),
            project_marker_dirs=(".dummy",),
        )
        registry = default_registry()
        registry.register(dummy)
        (home / ".dummy").mkdir()
        source_root = tmp_path / "bundle"
        skill = source_root / "alpha"
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text(
            "---\nname: alpha\ndescription: A fixture skill.\n---\nbody\n"
        )
        (skill / "reference.md").write_text("reference for alpha\n")

        source = DirectorySource(source_root)
        backend = registry.resolve("dummy", home=home, project=project)
        roots = {"home": home, "project": project}
        provenance = {"source_package": "fixture-consumer", "source_version": "1.2.3"}

        def state():
            return {
                s.name: s.state
                for s in status(source, backend, scope="user", **roots)
            }["alpha"]

        installed = install(source, backend, scope="user", **roots, **provenance)
        assert [s.name for s in installed.installed] == ["alpha"]
        assert (home / ".dummy" / "skills" / "alpha" / "SKILL.md").is_file()
        assert state() is SkillState.UP_TO_DATE
        (skill / "reference.md").write_text("v2\n")
        assert state() is SkillState.UPDATE_AVAILABLE
        updated = update(source, backend, scope="user", **roots, **provenance)
        assert [s.name for s in updated.updated] == ["alpha"]
        assert state() is SkillState.UP_TO_DATE
        removed = uninstall(
            source, backend, scope="user", **roots,
            source_package="fixture-consumer",
        )
        assert [s.name for s in removed.removed] == ["alpha"]
        assert state() is SkillState.NOT_INSTALLED

    def test_registration_does_not_leak_between_registries(self, env):
        registry = default_registry()
        registry.register(HarnessBackend(name="dummy", user_skills_dir=".dummy/skills"))

        assert "dummy" not in default_registry().names()
