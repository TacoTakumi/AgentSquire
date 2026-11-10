---
name: developing-with-agentsquire
description: "Use when building a Python CLI that carries its own Agent Skills with agentsquire - wiring the skills subcommand group, the staleness notice, console entry points, package-data layout and the release check (check-update command and new-release notice) into a consumer package."
---

# Developing with agentsquire

agentsquire lets your Python package carry its own Agent Skills and install them
into whatever agent harness is present (Claude Code, pi, Hermes, opencode). Your
users only ever run your tool - `your-cli skills install` - never a second CLI.

Add `agentsquire` as a plain dependency, then wire the points below. This is
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
from agentsquire import check_stale, default_source

def main():
    check_stale(
        default_source("your_pkg"),
        prog_name="your-cli",
        update_command="your-cli skills update",
    )
    # ... rest of your entry point
```

`default_source("your_pkg")` is the source the `skills` subcommands use by
default: your package-data skills plus any repo-level skills you ship, so the
notice covers every skill your CLI installs.

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

## 6. Tell users about a new release (optional)

This point is about your package, not your skills: agentsquire can say that a
newer release of your CLI is on PyPI. Mount the command and call the notice:

```python
from agentsquire import check_update_command, notify_update
from your_pkg import __version__

cli.add_command(check_update_command("your-dist", __version__, prog_name="your-cli"))

def main():
    notify_update("your-dist", __version__, prog_name="your-cli")
    # ... rest of your entry point
```

`your-cli check-update` makes one request to PyPI, prints one line and records
the newest version in a cache file. `notify_update` reads only that file and
prints one stderr line while the recorded release is newer than yours. A user
who never runs the check gets no notice. For a `doctor` command, call
`check_for_update("your-dist", __version__)`: it returns a result and never
raises. For typer, mount onto `typer.main.get_command(app)`.

Pass the PyPI distribution name, which can differ from the import name, and
pass your own `__version__`: an editable install reports a frozen version in
its metadata.

Three things the first adoption got wrong:

- **Your test suite needs two guards.** Each command now reads the cache at
  startup, so a newer release recorded on the developer's machine adds a
  stderr line to every test that reads stderr. In `conftest.py`, with autouse
  fixtures: set `XDG_CACHE_HOME` to a temporary directory with
  `monkeypatch.setenv` (a subprocess then gets it too), and replace
  `agentsquire.release._fetch_body` with a function that raises `OSError`, so
  no test reaches PyPI. `_fetch_body` is private: check it again when you
  raise your agentsquire minimum. If your tests run `uv`, keep its cache with
  `UV_CACHE_DIR`, because `XDG_CACHE_HOME` moves it.
- **Leave the notice out of `check-update`.** The command prints the fresh
  answer, and the cached notice before it can be older. Skip `notify_update`
  when `check-update` is anywhere in the arguments, not only the first one: a
  global option can come before the command.
- **A doctor command needs two decisions.** Skip the request when `CI` or
  `AGENTSQUIRE_NO_UPDATE_CHECK` is set, or each test and each sandboxed run
  reaches for PyPI: `check_for_update` itself ignores both. And report a newer
  release as advice, not as a failure: an old release is not a broken setup.

When you raise your agentsquire minimum, look for other places that pin it,
such as a packaging test that reads the wheel metadata.

## The provenance and update model

Installs are plain copies - no symlinks, no lockfile - so an installed skill
survives upgrade or removal of your package. Each installed `SKILL.md` carries a
provenance stamp in its frontmatter `metadata.agentsquire` map (installer,
versions, source package, content hash). Staleness detection is a local hash
compare: `status` classifies each skill as not-installed, up-to-date,
update-available, or locally-modified, and `update` refreshes only the stale
ones. User-modified installs and pre-existing symlinks are reported and skipped,
never clobbered. See `squire guide integration` for the full model.
