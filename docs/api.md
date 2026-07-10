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
  (importlib.resources backed).
- `DirectorySource(root)` - skills laid out as subdirectories of a plain
  local directory.
- `SourceSkill` - one enumerable skill: `name`, `content_hash`.

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
surface "a new version is available" proactively. Signature (implementation
lands with the proactive-staleness task):

`check_stale(source, backend, *, scope, home, project, source_package,
source_version) -> None`

On a TTY with update-available skills it announces them and offers to run
update. With no TTY it never prompts or blocks, writes nothing to stdout,
emits at most one stderr notice line, and leaves the exit code untouched.

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
