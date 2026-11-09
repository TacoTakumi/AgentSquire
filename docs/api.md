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
- `UnionSource(sources)` - the disjoint merge of the member sources.
  `list_skills()` returns the skills of every member, sorted by name, each
  with the content hash its own member reports; `materialize(name)` delegates
  to the member that provides the name and raises `KeyError` when no member
  does. A skill name present in more than one member is never an override:
  both methods raise `DuplicateSkillError`.
- `FirstAvailableSource(sources)` - resolves entirely to the first member
  whose `root_exists()` is true and ignores every later member; an existing
  but empty root still wins. With no member available, `list_skills()` is
  empty and `materialize(name)` raises `KeyError`. Each member must be a
  `SkillSource` that also exposes `root_exists() -> bool`, which is not part
  of the protocol: `DirectorySource` and `BundledPackageDataSource` provide
  it, `UnionSource` and `FirstAvailableSource` do not, and a member without
  it raises `AttributeError` when the source resolves and reaches it, not
  at construction.
- `DuplicateSkillError` - raised when a skill name is provided by more than
  one member of a `UnionSource`; the message names the skill and both roots.
  A collision is a packaging mistake, not an override.
- `default_source(package, resource_path="skills") -> UnionSource` - the
  source the `skills` subcommands use by default: the union of the
  package-data skills under `resource_path` (Root A) and the repo-level
  skills (Root B), which resolve wheel-first then checkout - the packaged
  `<package>/_repo_skills` copy first, else `<repo>/skills` in an editable
  checkout. For a package with no repo-level skills it lists exactly the
  skills of `BundledPackageDataSource(package, resource_path)`.
- `verify_skill_roots(package, resource_path="skills") -> None` - builds
  `default_source(package, resource_path)` and enumerates it. Returns
  silently when the two roots are disjoint and raises `DuplicateSkillError`
  when a skill name is present in both; call it from one test in your suite.

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
  hash, the directory carries no stamp at all, or a symlink sits at the
  target (dangling or live) - none of them ours to touch.

Decisions are local hash compares only. The symlink check uses `is_symlink`
(not `exists`, which would follow the link): a pre-existing symlink at a
target is always "present but not ours", so `install` skips it with a reason
naming the symlink rather than crashing or clobbering it, and `update
--force` unlinks the link (never `rmtree` through it) before writing a real
install.

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
same-named directories - and a symlink at the target - survive with the
reason recorded per skill (a symlink is never followed or `rmtree`d).

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

## Release check

Tells the users of a consumer CLI that a newer release of the consumer is on
PyPI. There are three functions: `notify_update` is the startup notice,
`check_for_update` is the check itself, and `check_update_command` is the
check as a mountable CLI command. The check is the only part of agentsquire
that uses the network, and it runs only when the user or the consumer asks
for it. Nothing here upgrades anything.

In each function, `distribution` is the consumer's distribution name on PyPI,
which can differ from its import name. `version` is the installed version of
the consumer. When it is omitted, the version comes from the install
metadata. Pass the consumer's own `__version__`: an editable install reports
a frozen version in its metadata.

### notify_update

`notify_update(distribution, version=None, *, prog_name) -> None`

The startup hook. notify_update makes no request: it reads the cache file
that an earlier check wrote and compares the cached newest version with the
installed one. It does not write the cache. The cached version is used at any
age, and the comparison runs at each call, so the notice stays until the user
upgrades and stops after that.

When the installed version is older it prints exactly one stderr line:

    {prog_name}: a new release is available: {installed} -> {newest}; run `{upgrade command}`

The part from `;` on is there only when an upgrade command is known. Nothing
is printed when there is no usable cache, when the installed version is not
older, or when a version does not parse.

The suppression gate is the one of `check_stale`: `CI` or
`AGENTSQUIRE_NO_UPDATE_CHECK` set to a non-empty value turns the notice off,
an empty string counts as unset, and there is no TTY gate. On every path the
hook returns None, writes nothing to stdout, leaves the exit code untouched
and swallows its own errors.

### check_for_update

`check_for_update(distribution, version=None) -> ReleaseCheck`

Asks PyPI for the newest version: one HTTPS GET of
`https://pypi.org/pypi/{distribution}/json`, with the User-Agent
`agentsquire/{agentsquire version}`. A successful check records the newest
version in the cache. A failed check writes nothing. The function never
raises: each failure (no network, a timeout, an HTTP error, an unexpected
response) becomes a result with the status `check-failed`. `CI` and
`AGENTSQUIRE_NO_UPDATE_CHECK` do not turn it off, because the caller asked
for the check.

`ReleaseCheck` is a frozen dataclass with these fields:

- `distribution` - the name as passed.
- `installed` - the installed version, or None when it is not known.
- `newest` - the newest version on PyPI, or None when the check failed.
- `status` - a `ReleaseStatus`.
- `upgrade_command` - the command that upgrades the consumer, or None. Set
  only when the status is `update-available` and a command is known.
- `error` - a one-line reason, set only when the status is `check-failed`.

`ReleaseStatus` is an enum with five values:

- `UP_TO_DATE` (`"up-to-date"`) - the installed version has the release
  numbers of the newest one.
- `UPDATE_AVAILABLE` (`"update-available"`) - the installed version is older.
- `AHEAD` (`"ahead"`) - the installed version is newer than the newest
  release on PyPI.
- `UNKNOWN` (`"unknown"`) - the check gave a newest version, but the two
  versions cannot be compared.
- `CHECK_FAILED` (`"check-failed"`) - the check gave no newest version.

### check_update_command

`check_update_command(distribution, version=None, *, prog_name,
name="check-update") -> click.Command`

Builds a click command that the consumer mounts with `cli.add_command(...)`.
Like `skills_command_group`, it also imports from `agentsquire.cli`.
`prog_name` is the program name in the output line and `name` is the command
name. The command takes no arguments and no options. It calls
`check_for_update` and prints exactly one line:

| Status | Line | Stream | Exit code |
|---|---|---|---|
| `update-available` | ``{prog_name}: a new release is available: {installed} -> {newest}; run `{upgrade command}` `` | stdout | 0 |
| `up-to-date` | `{prog_name} {installed} is up to date` | stdout | 0 |
| `ahead` | `{prog_name} {installed} is newer than the newest PyPI release {newest}` | stdout | 0 |
| `unknown` | `{prog_name}: installed {installed}, newest PyPI release {newest}; the versions cannot be compared` | stdout | 0 |
| `check-failed` | `{prog_name}: could not check for a new release: {reason}` | stderr | 1 |

check-update exits non-zero only for a failed check. An available update is
a result, not an error, so its exit code is 0. In the `update-available`
line, the part from `;` on is there only when an upgrade command is known. A
version that is not known prints as `unknown`. The command runs when `CI` or
`AGENTSQUIRE_NO_UPDATE_CHECK` is set.

### Cache location

One JSON file per distribution, named after the normalized distribution name
(lower case, each run of `-`, `_` and `.` as one `-`), in the directory
`agentsquire` under the user cache root:

- POSIX: `$XDG_CACHE_HOME/agentsquire/{name}.json`, or
  `~/.cache/agentsquire/{name}.json` when `XDG_CACHE_HOME` is unset or empty.
- Windows: `%LOCALAPPDATA%\agentsquire\{name}.json`.

The file holds the newest version and the time of the check
(`{"newest": "1.3.0", "checked_at": "<ISO 8601 UTC time>"}`), and nothing
else. A file that is missing, unreadable or invalid counts as no cache. A
write that fails is ignored.

### Limits

- Each socket operation of the request has a 3 second timeout.
- The whole check has a 5 second total limit, `agentsquire.release.TOTAL_TIMEOUT`.
  A check that is not done by then has the status `check-failed` and the
  reason `timed out`.

### Version comparison

The comparison uses the release numbers only: the dotted integers at the
start of the version, after an optional `v`. Missing trailing numbers count
as zero, so `1.2` equals `1.2.0`. The text after the release numbers (pre,
post, dev and local parts) is ignored.

- A dev or post build of the same release number is not outdated:
  `1.3.0.dev4` and `1.3.0.post1` are `up-to-date` against `1.3.0`.
- A version that does not parse (no leading number, or an epoch such as
  `1!2.0`) gives `unknown`, never an error.
- Known limit: an installed pre-release gets no notice for the final release
  of the same number. `1.3.0rc1` is `up-to-date` against `1.3.0`.

### Upgrade command

The upgrade command is known for two install methods, read from the running
environment:

- a uv tool install: `uv tool upgrade {distribution}`
- a pipx install: `pipx upgrade {distribution}`

The distribution name is used exactly as passed. For every other install
method, and for an editable install in any environment, there is no command
and the output line ends after the versions.

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

`skills_command_group(package, resource_path="skills", default_scope="user",
*, name="skills", source=None, source_package=None, source_version=None,
home=None, project=None) -> click.Group`

- `source` (keyword-only) - the `SkillSource` the subcommands operate on.
  When omitted (`None`) the group uses `default_source(package,
  resource_path)`; pass any `SkillSource`, for example
  `DirectorySource(fixture_dir)`, and the group uses it as given.
  `resource_path` then has no effect on the source, and `package` still
  supplies the default `source_package` and `source_version`. A
  `DuplicateSkillError` from the source ends the subcommand with a
  one-line error and a non-zero exit, not a traceback.

### Redirecting a wired CLI with env vars

Explicit roots cover a *direct* call, but the test that matters most drives
your own CLI end to end - and that wiring omits `home=`/`project=` on purpose,
so each real invocation resolves `Path.home()`/`Path.cwd()`. To point those
unset roots at fixtures without monkeypatching `Path.home` or chdir, set
`AGENTSQUIRE_HOME` and `AGENTSQUIRE_PROJECT`:

```python
def test_my_cli_reports_updates(tmp_path, monkeypatch):
    home, project = tmp_path / "home", tmp_path / "project"
    (home / ".claude").mkdir(parents=True)  # marker so the harness is detected
    project.mkdir()
    monkeypatch.setenv("AGENTSQUIRE_HOME", str(home))
    monkeypatch.setenv("AGENTSQUIRE_PROJECT", str(project))

    # my_cli wires check_stale and mounts the skills group with no home=/project=
    result = CliRunner().invoke(my_cli, ["skills", "status"])
    assert result.exit_code == 0
```

The overrides fill in wherever roots are otherwise taken from the real
environment - the `check_stale` hook and the mounted `skills` subcommands.
Explicit `home=`/`project=` arguments still win over the env vars, and an
empty value is treated as unset (the `NO_COLOR` convention).

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
