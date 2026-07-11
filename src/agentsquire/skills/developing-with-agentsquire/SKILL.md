---
name: developing-with-agentsquire
description: "Use when building a Python CLI that carries its own Agent Skills with agentsquire - wiring the skills subcommand group, the staleness notice, console entry points, and package-data layout into a consumer package."
---

# Developing with agentsquire

agentsquire lets your Python package carry its own Agent Skills and install them
into whatever agent harness is present (Claude Code, pi, Hermes, opencode). Your
users only ever run your tool - `your-cli skills install` - never a second CLI.

Add `agentsquire` as a plain dependency, then wire the four points below. This is
a checklist, not the reference: run `squire guide` (topics `api`, `harnesses`,
`integration`) or read `docs/api.md` for full signatures and behaviour.

## 1. Ship skills as package data

Lay each skill out as a directory with a `SKILL.md` (agentskills.io format)
under a `skills/` resource inside your importable package:

```
your_pkg/
    __init__.py
    skills/
        my-skill/
            SKILL.md
```

The skills ride inside your wheel, so no source checkout is needed at run time.
hatchling includes package data by default; setuptools needs
`include-package-data`. This skills-as-package-data layout is what
`BundledPackageDataSource("your_pkg")` reads from.

## 2. Mount the skills subcommand group

`skills_command_group` returns a click group with `install`, `status`, `update`,
and `uninstall` subcommands, parameterized by your package name and default
scope. Mount it on your root group:

```python
from agentsquire.cli import skills_command_group

cli.add_command(skills_command_group("your_pkg", default_scope="user"))
```

For typer, mount onto `typer.main.get_command(app)`. Every subcommand takes
`--scope user|project` and `--harness NAME`. Choose `user` scope for
general-purpose tools, `project` for repo-specific skills.

## 3. Expose a console entry point

Give your CLI a `[project.scripts]` console entry in `pyproject.toml` so users
invoke it by name:

```toml
[project.scripts]
your-cli = "your_pkg.console:main"
```

## 4. Surface updates proactively (optional)

Call the `check_stale` hook at your entry point. When an installed skill has a
newer shipped copy it prints one advisory line on stderr and nothing else - it
never prompts, never writes stdout, never changes your exit code:

```python
from agentsquire import BundledPackageDataSource, check_stale

def main():
    check_stale(
        BundledPackageDataSource("your_pkg"),
        prog_name="your-cli",
        update_command="your-cli skills update",
    )
    # ... rest of your entry point
```

Suppressed when `CI` or `AGENTSQUIRE_NO_UPDATE_CHECK` is set to any non-empty
value.

## 5. Mark the package as skill-carrying (optional)

One pyproject line registers your package under the `agentsquire.skills`
entry-point marker. Nothing reads it today; it is reserved for a future
environment-wide listing and changes no behaviour:

```toml
[project.entry-points."agentsquire.skills"]
your_pkg = "your_pkg"
```

## The provenance and update model

Installs are plain copies - no symlinks, no lockfile - so an installed skill
survives upgrade or removal of your package. Each installed `SKILL.md` carries a
provenance stamp in its frontmatter `metadata.agentsquire` map (installer,
versions, source package, content hash). Staleness detection is a local hash
compare: `status` classifies each skill as not-installed, up-to-date,
update-available, or locally-modified, and `update` refreshes only the stale
ones. User-modified installs and pre-existing symlinks are reported and skipped,
never clobbered. See `squire guide integration` for the full model.
