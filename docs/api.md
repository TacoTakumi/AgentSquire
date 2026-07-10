# AgentSquire Python API reference

Everything the library can do is available as plain Python through top-level
`agentsquire` names - no CLI involved. The importable surface is exactly
`agentsquire.__all__`; anything not exported there is internal.

All verbs are local-only: no network access ever happens in enumerate,
detect, install, status, update, or uninstall.

## Common parameters

- `scope` - `"user"` or `"project"`, selecting which of the harness's skill
  directories a verb operates on.
- `home`, `project` - the roots the scope directories are resolved against
  (normally `Path.home()` and the project root). Injectable so tests and
  tools can point at fixture trees.
- `source_package`, `source_version` - the consumer package's name and
  version, recorded in the provenance stamp.

## Enumerate: skill sources

- `SkillSource` (protocol) - where skills come from: `list_skills() ->
  list[SourceSkill]` and `materialize(name)`, a context manager yielding a
  filesystem path to the named skill directory.
- `BundledPackageDataSource(package, resource_path="skills")` - skills
  shipped as package data inside an installed consumer wheel
  (importlib.resources backed). For a normally installed wheel the skills
  are real on-disk paths and the status/enumerate hot path performs no temp
  copy; only zip-served or namespace-package sources are materialized to a
  temporary directory.
- `DirectorySource(root)` - skills laid out as subdirectories of a plain
  local directory.
- `SourceSkill` - one enumerable skill: `name`, `content_hash`.

## Entry-point marker (optional)

A consumer package may mark itself as skill-carrying by registering under
the `agentsquire.skills` pyproject entry-point group (exported as
`ENTRY_POINT_GROUP`). The registration is one line - the value is the
importable package whose bundled skills live in its package data, the same
name you pass to `BundledPackageDataSource` or `skills_command_group`:

```toml
[project.entry-points."agentsquire.skills"]
awiki = "awiki"
```

Registering changes no behaviour: no verb reads the group today. It is
reserved for a future environment-wide listing of skill-carrying packages.

## Detect: harness backends

- `default_registry() -> HarnessRegistry` - a fresh registry with the four
  launch backends registered (`CLAUDE_CODE`, `PI`, `HERMES`, `OPENCODE`).
- `HarnessRegistry.detect(home=..., project=...)` - the backends whose
  marker directories are present.
- `HarnessRegistry.resolve(name, home=..., project=...)` - one backend by
  name; raises `HarnessNotDetectedError` (supported but absent) or
  `UnknownHarnessError` (message lists the supported set).
- `HarnessBackend.skills_dir(scope, home=..., project=...)` - the harness's
  skill directory for a scope; raises `UnsupportedScopeError` when the
  harness has no such scope (Hermes has no project scope).
- `HarnessRegistry.register(backend)` - adding harness N+1 is one
  registration; the verbs never change.

Backend directory values mirror docs/harnesses.md - change the document
first, then the backend.

## Install

`install(source, backend, *, scope, home, project, source_package,
source_version) -> InstallResult`

Copies every valid skill in the source into the backend's scope directory
(regular files only, symlinks dereferenced, nothing pointing back at
site-packages) and stamps provenance into the SKILL.md frontmatter
`metadata.agentsquire` map: `installer`, `installer_version`,
`source_package`, `source_version`, `content_hash`. Non-stamp bytes are
unchanged from the source.

Idempotent: a current install is a byte-identical no-op reported in
`result.up_to_date`. Invalid skills land in `result.rejected` (one
`SkillViolation` per broken rule) without stopping the run; stale or
locally-modified installs are skipped, never overwritten. `result.ok` is
False when anything was rejected.

## Status

`status(source, backend, *, scope, home, project) -> list[SkillStatus]`

Classifies each source skill as exactly one `SkillState`:

- `NOT_INSTALLED` - nothing at the target path.
- `UP_TO_DATE` - installed content matches its own stamp and the stamped
  hash matches the shipped copy.
- `UPDATE_AVAILABLE` - stamped hash differs from the shipped copy's hash.
- `LOCALLY_MODIFIED` - installed content no longer matches its own stamped
  hash, or the directory carries no stamp at all (not ours to touch).

Decisions are local hash compares only.

## Update

`update(source, backend, *, scope, home, project, source_package,
source_version, force=False) -> UpdateResult`

Re-copies and re-stamps every update-available skill, after which status
reports it up-to-date. Locally-modified installs are skipped with the skill
named in `result.skipped` unless `force=True`, which overwrites and
re-stamps. Not-installed skills are left to install.

## Uninstall

`uninstall(source, backend, *, scope, home, project, source_package) ->
UninstallResult`

Removes only skill directories whose stamp names agentsquire as the
installer and `source_package` as the source. Unstamped or foreign-stamped
same-named directories survive with the reason recorded per skill.

## Staleness check hook

The one-call startup hook a consumer CLI places at its entry point to
surface "a skills update is available" proactively.

`check_stale(source, backend=None, *, scope="user", home=None, project=None,
prog_name, update_command) -> None`

With no backend given, every detected harness is checked; `home` and
`project` default to `Path.home()` and the current directory. `prog_name`
names the consumer CLI and `update_command` is the exact command the notice
tells the user to run; both are required keyword arguments.

The hook is notice-only and does not prompt. With update-available skills
it prints exactly one stderr line, "{prog_name}: a skills update is
available for N skill/skills (sorted names); run `{update_command}`", and
does nothing else: it never reads stdin, never blocks, and never updates
anything itself - the explicit `skills update` verb is the sole updater.

The notice is emitted unless a suppression gate holds: `CI` set to a
non-empty value, or `AGENTSQUIRE_NO_UPDATE_CHECK` set to a non-empty value.
It is not gated on an interactive TTY - it fires on non-TTY stderr too, so
an agent harness running the consumer with captured stderr still sees that
an update is available. Suppression is presence-disables (the `NO_COLOR`
convention): any non-empty value disables the notice - `CI=false` and
`AGENTSQUIRE_NO_UPDATE_CHECK=0` both suppress - while an empty string is
treated as unset.

On every path it returns None, writes nothing to stdout, never mutates
installed skills, and leaves the exit code untouched. It swallows its own
errors - a startup hook must never break the command it runs inside. Local
hash compares only.

## Testing your integration

Every verb and the mounted skills group accept explicit roots: point
`home=` and `project=` at fixture directories and the whole surface
operates on them. No monkeypatching of `Path.home()` and no chdir needed:

```python
from click.testing import CliRunner

from agentsquire.cli import skills_command_group


def test_install_lands_in_the_fixture_home(tmp_path):
    home, project = tmp_path / "home", tmp_path / "project"
    (home / ".claude").mkdir(parents=True)  # marker so the harness is detected
    project.mkdir()

    group = skills_command_group("your_pkg", home=home, project=project)

    result = CliRunner().invoke(group, ["install"])
    assert result.exit_code == 0
    assert (home / ".claude" / "skills" / "alpha").is_dir()
```

The verbs accept the same `home=` and `project=` roots directly, for
example `install(source, backend, scope="user", home=home,
project=project, source_package="your_pkg", source_version="1.0")`;
`status`, `update`, `uninstall`, and `check_stale` take `home=` and
`project=` the same way.

## Building blocks

- `validate_skill_dir(path) -> list[SkillViolation]` - agentskills.io
  structural rules; empty list means valid.
- `load_skill(path) -> Skill` - parse a valid skill directory; raises
  `InvalidSkillError` listing the violations otherwise.
- `skill_content_hash(path) -> str` - deterministic hash of a skill
  directory, excluding the provenance stamp, stable across filesystem
  ordering.
- `read_stamp(text) -> dict | None` - the provenance stamp from SKILL.md
  text, if present.
- `STAMP_KEY` - the key inside frontmatter `metadata` the stamp lives under
  (`"agentsquire"`).
