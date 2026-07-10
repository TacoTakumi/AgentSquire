# AgentSquire

A reusable Python library + CLI that lets a Python package carry its own agent
integrations (Agent Skills) and install them into whatever agent harness is
present - the executable is the framework.

Your CLI ships its skills as package data inside its own wheel, adds
`agentsquire` as a plain pip dependency, and mounts a ready-made subcommand
group. Your users only ever see your tool:

```
$ awiki skills install
installed awiki-search -> /home/you/.claude/skills/awiki-search
```

Supported harnesses at launch: Claude Code, pi, Hermes, and opencode. Detection
is by marker directory; every operation is local (no network in any verb).

## Consumer integration guide

### 1. Ship skills as package data

Lay each skill out as a directory containing a `SKILL.md` (the agentskills.io
format) under a `skills/` resource inside your importable package:

```
your_pkg/
    __init__.py
    skills/
        my-skill/
            SKILL.md
            reference.md
```

The skills ride inside your wheel; make sure your build backend includes
package data (hatchling includes it by default, setuptools needs
`include-package-data`). No source checkout is needed at run time - skills are
enumerated straight from the installed wheel.

### 2. Mount the subcommand group

One call returns a click group with `install`, `status`, `update`, and
`uninstall` subcommands, parameterized by your package name, the resource path
(default `"skills"`), and the default scope.

For a click CLI:

```python
import click

from agentsquire.cli import skills_command_group


@click.group()
def cli():
    """Your CLI."""


cli.add_command(skills_command_group("your_pkg", default_scope="user"))
```

For a typer CLI, mount onto the underlying click command:

```python
import typer
import typer.main

from agentsquire.cli import skills_command_group

app = typer.Typer()


@app.callback()
def main():
    """Your CLI."""


cli = typer.main.get_command(app)
cli.add_command(skills_command_group("your_pkg", default_scope="user"))
```

Your users now run `your-cli skills install` and friends. Every subcommand
takes `--scope user|project` (overriding your declared default) and
`--harness NAME` (default: all detected harnesses).

Choosing the default scope: `user` installs into the harness's per-user
skills directory and follows the user everywhere - right for general-purpose
tools. `project` installs into the current project's directory - right for
skills that only make sense inside a repository that uses your tool.

### 3. Surface updates proactively (optional)

Place the one-call staleness hook at your CLI entry point. On an interactive
terminal with stale installs it offers to update; without a TTY it writes
nothing to stdout, never prompts, never changes your exit code, and swallows
its own errors, so it can never break the command it runs inside:

```python
from your_pkg import __version__

from agentsquire import BundledPackageDataSource, check_stale


def main():
    check_stale(
        BundledPackageDataSource("your_pkg"),
        source_package="your_pkg",
        source_version=__version__,
    )
    # ... the rest of your entry point
```

### 4. Mark your package as skill-carrying (optional)

One pyproject line registers your package under the `agentsquire.skills`
entry-point group. Nothing reads it today - it is reserved for a future
environment-wide listing of skill-carrying packages and changes no behaviour:

```toml
[project.entry-points."agentsquire.skills"]
your_pkg = "your_pkg"
```

## The provenance and update model

Installs are plain copies - no symlinks, no lockfile, no references back into
site-packages - so an installed skill survives upgrade or removal of your
package. Each installed `SKILL.md` carries a provenance stamp in its
frontmatter `metadata.agentsquire` map: `installer`, `installer_version`,
`source_package`, `source_version`, and `content_hash`. The skill body is
byte-identical to what you shipped.

`status` classifies every skill by local hash compares only (no network,
ever): not-installed, up-to-date, update-available (your shipped copy moved
on), or locally-modified (the user edited the install, or the directory
carries no stamp and is not ours to touch). `update` refreshes
update-available skills and skips locally modified ones unless `--force` is
given; `uninstall` removes only directories whose stamp names your package.
User content is never silently overwritten or deleted.

## Python API

Everything the CLI group does is available as plain Python - enumerate,
detect, install, status, update, uninstall, and the staleness check - with no
CLI involved. See [docs/api.md](docs/api.md) for the reference.

## License

MIT.
