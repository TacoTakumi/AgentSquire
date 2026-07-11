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
is by marker directory; every operation is local (no network in any verb). Each
harness's directories, scopes, and behaviour are recorded in
[docs/harnesses.md](docs/harnesses.md).

## Installation

    pip install agentsquire

This installs the library and its own CLI, `squire` (aliased `agentsquire`). As
a consumer you normally add `agentsquire` to your package's dependencies rather
than having users install it directly - it rides in your wheel, and your users
only ever see your tool.

agentsquire dogfoods its own contract: it carries the
`developing-with-agentsquire` skill and its reference docs as package data. When
you build an app on agentsquire, install that skill into your own agent harness
so the harness has the integration know-how on hand while it works:

    squire skills install

That copies `developing-with-agentsquire` (how to ship skills, mount the group,
and wire the staleness hook) into every detected harness. The same reference
docs are served at the terminal from the installed wheel - no checkout needed:

    squire guide              # topics: api, harnesses, integration
    squire guide api          # the Python API reference
    squire guide integration  # this consumer integration guide

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

Place the one-call staleness hook at your CLI entry point. When installed
skills have updates available it prints a single advisory line on stderr,
for example:

    your-cli: a skills update is available for 1 skill (alpha); run `your-cli skills update`

The hook is notice-only: it never prompts, never reads stdin, and never
updates anything itself - the explicit `skills update` verb stays the sole
updater. It writes nothing to stdout, never changes your exit code, and
swallows its own errors, so it can never break the command it runs inside:

```python
from agentsquire import BundledPackageDataSource, check_stale


def main():
    check_stale(
        BundledPackageDataSource("your_pkg"),
        prog_name="your-cli",
        update_command="your-cli skills update",
    )
    # ... the rest of your entry point
```

The notice shows unless a suppression gate holds: `CI` set to a non-empty
value, or `AGENTSQUIRE_NO_UPDATE_CHECK` set to a non-empty value. It is not
gated on an interactive terminal - it fires on non-TTY stderr too, so an
agent harness that runs your CLI with captured stderr still sees that an
update is available. Suppression is presence-disables, the `NO_COLOR`
convention: any non-empty value disables the notice (`CI=false` and
`AGENTSQUIRE_NO_UPDATE_CHECK=0` both suppress), while an empty string is
treated as unset.

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
on), or locally-modified (the user edited the install, the directory carries
no stamp, or a symlink sits at the target - none of them ours to touch).
`update` refreshes update-available skills and skips locally modified ones
unless `--force` is given; `uninstall` removes only directories whose stamp
names your package. User content is never silently overwritten or deleted -
a pre-existing symlink at a target (a common hand-wired setup) is reported
and skipped, never followed or clobbered.

## Python API

Everything the CLI group does is available as plain Python - enumerate,
detect, install, status, update, uninstall, and the staleness check - with no
CLI involved. See [docs/api.md](docs/api.md) for the reference.

## License

MIT.
