# Changelog

All notable changes to AgentSquire are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project aims
to follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

The version is declared in two places that are kept in sync by the release
tooling: `__version__` in `src/agentsquire/__init__.py` and `version` in
`pyproject.toml`.

## [0.2.1]

### Fixed
- **A pre-existing symlink at a target no longer crashes install/update or
  gets clobbered (BUG-02).** The classifier and copy guard tested the target
  with `Path.exists()`, which follows a symlink: a dangling link read as
  not-installed and then `install` hit `FileExistsError`, while a live link
  reached `shutil.rmtree` on `update --force` and raised "Cannot call rmtree
  on a symbolic link". Detection now uses `is_symlink`, so a symlink (dangling
  or live) classifies as `LOCALLY_MODIFIED` - present but not ours. `install`
  and `update` (without `--force`) skip it with a reason naming the symlink;
  `update --force` unlinks the link (never `rmtree`s through it) before
  writing a real install; `uninstall` leaves it in place with a reason.
  Symlinking skills into `~/.claude/skills` is a mainstream hand-wired setup,
  so anyone migrating to `skills install` from it hit this on the first run.

## [0.2.0] - 2026-07-10

### Added
- **`AGENTSQUIRE_HOME` / `AGENTSQUIRE_PROJECT` root overrides.** When
  `check_stale` and the mounted `skills` subcommands are wired the production
  way (no `home=`/`project=` arguments, so each invocation resolves the real
  roots), these env vars redirect the home and project roots. A consumer's
  CLI-level test can point the wired hook and the subcommands at fixture
  directories by setting two variables instead of monkeypatching `Path.home`
  and chdir. Explicit `home=`/`project=` arguments still take precedence; an
  empty value is treated as unset (the `NO_COLOR` convention). Documented in
  the `docs/api.md` "Testing your integration" section.

### Fixed
- **`check_stale` now surfaces the update notice on non-TTY stderr.** The
  hook previously required stderr to be an interactive TTY, which silenced
  it in exactly the case that matters most for an agent-skills tool: an
  agent harness runs the consumer CLI with captured (non-TTY) stderr and so
  never saw that an update was available. The interactive-TTY gate is
  removed; `CI` and `AGENTSQUIRE_NO_UPDATE_CHECK` (presence-disables) remain
  the escape hatches for pipelines and opt-out. README and `docs/api.md`
  updated accordingly.

## [0.1.0] - 2026-07-10

Initial release.

### Added
- **Mountable `skills` command group.** `skills_command_group(package, ...)`
  returns a ready-made click group with `install`, `status`, `update`, and
  `uninstall` subcommands that a consumer CLI mounts under its own name, so
  its users only ever see one tool (e.g. `awiki skills install`). Works with
  click directly and with typer via `typer.main.get_command`. Every
  subcommand takes `--scope user|project` and `--harness NAME`.
- **Skills as package data.** Consumers ship SKILL.md directories (the
  agentskills.io format) as package data inside their own wheel; skills are
  enumerated straight from the installed wheel, no source checkout needed.
  `BundledPackageDataSource` reads them, with structural validation against
  the agentskills.io spec.
- **Four harness backends.** Claude Code, pi, Hermes, and opencode, detected
  by marker directory, each with user and project scopes. Directories and
  behaviour are recorded in `docs/harnesses.md`; backends resolve exactly
  the paths documented there.
- **Copy-with-provenance install model.** Installs are plain copies - no
  symlinks, no lockfile - stamped with an `agentsquire` provenance block
  (installer, installer_version, source_package, source_version,
  content_hash) in the installed SKILL.md frontmatter. The skill body stays
  byte-identical to what was shipped.
- **Hash-based status and safe updates.** `status` classifies each skill as
  not-installed, up-to-date, update-available, or locally-modified using
  local hash compares only (no network in any verb). `update` refreshes
  update-available skills and skips locally modified ones unless `--force`;
  `uninstall` removes only directories whose stamp names the consumer's
  package. User content is never silently overwritten or deleted.
- **Notice-only staleness hook.** `check_stale(source, prog_name=...,
  update_command=...)` prints a single stderr advisory when installed skills
  are stale. It never prompts, never updates, never touches stdout or the
  exit code, and swallows its own errors. Gated on stderr being a TTY, `CI`
  unset or empty, and `AGENTSQUIRE_NO_UPDATE_CHECK` unset or empty.
- **Python API.** Everything the CLI group does - enumerate, detect, install,
  status, update, uninstall, staleness check - is available as plain Python;
  see `docs/api.md`.
- **`agentsquire.skills` entry-point group.** Consumers may register their
  package under it; reserved for a future environment-wide listing, changes
  no behaviour today.
