# Changelog

All notable changes to AgentSquire are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project aims
to follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

The version is declared in two places that are kept in sync by the release
tooling: `__version__` in `src/agentsquire/__init__.py` and `version` in
`pyproject.toml`.

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
