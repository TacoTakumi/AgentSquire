#!/usr/bin/env bash
# Clean-venv wheel end-to-end test (REQ-01, REQ-03, REQ-07).
#
# Builds the agentsquire wheel and a fixture consumer wheel (three bundled
# skills, mounted CLI, entry-point registration), installs both into a fresh
# venv, runs the full lifecycle through the consumer CLI (import, enumerate,
# install, status, update, uninstall), then pip-uninstalls the consumer and
# confirms the installed skills survive readable. Invoked from CI and locally.
set -euo pipefail

cd "$(dirname "$0")/.."
repo=$(pwd)

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

step() { echo; echo "== $*"; }

step "build the agentsquire wheel"
python3 -m venv "$tmp/build"
"$tmp/build/bin/pip" install --quiet build hatchling
"$tmp/build/bin/python" -m build --wheel --no-isolation \
    --outdir "$tmp/dist" "$repo" >/dev/null
squire_wheel=$(ls "$tmp/dist"/agentsquire-*.whl)
echo "$squire_wheel"

step "author and build the fixture consumer wheel (three skills)"
consumer="$tmp/consumer"
pkg="$consumer/src/fixture_consumer"
mkdir -p "$pkg"
cat > "$consumer/pyproject.toml" <<'EOF'
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "fixture-consumer"
version = "1.2.3"
dependencies = ["agentsquire"]

[project.scripts]
fixture-consumer = "fixture_consumer.cli:main"

[project.entry-points."agentsquire.skills"]
fixture_consumer = "fixture_consumer"

[tool.hatch.build.targets.wheel]
packages = ["src/fixture_consumer"]
EOF
cat > "$pkg/__init__.py" <<'EOF'
__version__ = "1.2.3"
EOF
cat > "$pkg/cli.py" <<'EOF'
import click

from agentsquire.cli import skills_command_group


@click.group()
def main():
    """Fixture consumer CLI."""


main.add_command(skills_command_group("fixture_consumer"))
EOF
for name in alpha-skill beta-skill gamma-skill; do
    mkdir -p "$pkg/skills/$name/docs"
    cat > "$pkg/skills/$name/SKILL.md" <<EOF
---
name: $name
description: $name does things.
---

Use $name wisely.
EOF
    echo "reference for $name" > "$pkg/skills/$name/reference.md"
    echo "nested notes" > "$pkg/skills/$name/docs/notes.md"
done
"$tmp/build/bin/python" -m build --wheel --no-isolation \
    --outdir "$consumer/dist" "$consumer" >/dev/null
consumer_wheel=$(ls "$consumer/dist"/fixture_consumer-*.whl)
echo "$consumer_wheel"

step "install both wheels into a fresh venv"
python3 -m venv "$tmp/run"
run="$tmp/run/bin"
"$run/pip" install --quiet "$squire_wheel" "$consumer_wheel"

step "import agentsquire in the clean venv (REQ-01)"
"$run/python" -c "import agentsquire; print('import OK', agentsquire.__version__)"

step "enumerate exactly the three bundled skills from the wheel (REQ-03)"
"$run/python" - <<'EOF'
from agentsquire import BundledPackageDataSource

skills = BundledPackageDataSource("fixture_consumer").list_skills()
names = sorted(s.name for s in skills)
assert names == ["alpha-skill", "beta-skill", "gamma-skill"], names
assert all(s.content_hash for s in skills)
print("enumerated:", ", ".join(names))
EOF

# the lifecycle runs against a fake home carrying the Claude Code marker
export HOME="$tmp/home"
skills_dir="$HOME/.claude/skills"
mkdir -p "$HOME/.claude" "$tmp/project"
cd "$tmp/project"

step "install through the consumer CLI"
"$run/fixture-consumer" skills install | tee "$tmp/out"
grep -c "^installed " "$tmp/out" | grep -qx 3
for name in alpha-skill beta-skill gamma-skill; do
    test -f "$skills_dir/$name/SKILL.md"
    test -f "$skills_dir/$name/docs/notes.md"
done

step "installed tree contains no symlinks (REQ-07)"
if find "$skills_dir" -type l | grep -q .; then
    echo "FAIL: symlink found in installed tree"
    exit 1
fi
echo "no symlinks"

step "status reports all three up-to-date"
"$run/fixture-consumer" skills status | tee "$tmp/out"
grep -c "^up-to-date " "$tmp/out" | grep -qx 3

step "update after the shipped copy moves on"
site_pkg=$("$run/python" -c \
    "import fixture_consumer, pathlib; print(pathlib.Path(fixture_consumer.__file__).parent)")
echo "reference v2" > "$site_pkg/skills/alpha-skill/reference.md"
"$run/fixture-consumer" skills status | tee "$tmp/out"
grep -q "^update-available alpha-skill" "$tmp/out"
"$run/fixture-consumer" skills update | tee "$tmp/out"
grep -q "^updated alpha-skill" "$tmp/out"
grep -qx "reference v2" "$skills_dir/alpha-skill/reference.md"
"$run/fixture-consumer" skills status | tee "$tmp/out"
grep -c "^up-to-date " "$tmp/out" | grep -qx 3

step "uninstall removes the installs"
"$run/fixture-consumer" skills uninstall | tee "$tmp/out"
grep -c "^removed " "$tmp/out" | grep -qx 3
for name in alpha-skill beta-skill gamma-skill; do
    test ! -e "$skills_dir/$name"
done

step "reinstall, then pip-uninstall the consumer: skills survive readable (REQ-07)"
"$run/fixture-consumer" skills install >/dev/null
"$run/pip" uninstall --quiet --yes fixture-consumer
if "$run/python" -c "import fixture_consumer" 2>/dev/null; then
    echo "FAIL: consumer package still importable after pip uninstall"
    exit 1
fi
for name in alpha-skill beta-skill gamma-skill; do
    grep -q "description: $name does things." "$skills_dir/$name/SKILL.md"
    grep -q "reference for $name" "$skills_dir/$name/reference.md" \
        || grep -qx "reference v2" "$skills_dir/$name/reference.md"
done
"$run/python" -c "import agentsquire" # the library itself is untouched
echo "skills survive the consumer's removal"

echo
echo "e2e OK"
