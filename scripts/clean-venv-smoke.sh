#!/usr/bin/env bash
# Build the agentsquire wheel and smoke-test it in a throwaway venv:
# install it, import it, and check the wheel metadata (MIT license,
# no consumer packages among the dependencies, py.typed shipped).
# Always builds fresh - never trusts whatever is lying around in dist/.
set -euo pipefail

cd "$(dirname "$0")/.."

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

python3 -m venv "$tmp/venv"
"$tmp/venv/bin/pip" install --quiet build hatchling
"$tmp/venv/bin/python" -m build --wheel --no-isolation --outdir "$tmp/dist" . >/dev/null
wheel=$(ls "$tmp/dist"/agentsquire-*.whl)
echo "smoke-testing $wheel"

"$tmp/venv/bin/pip" install --quiet "$wheel"
"$tmp/venv/bin/python" - <<'EOF'
from importlib.metadata import metadata, requires
from importlib.resources import files

import agentsquire

md = metadata("agentsquire")
license_field = md.get("License-Expression") or md.get("License") or ""
assert "MIT" in license_field, f"license metadata is not MIT: {license_field!r}"

reqs = requires("agentsquire") or []
for banned in ("awiki", "specflo"):
    assert not any(banned in r for r in reqs), f"consumer package in deps: {reqs}"

assert files("agentsquire").joinpath("py.typed").is_file(), "py.typed not in wheel"

print(f"smoke OK: {md['Name']} {md['Version']} | license: {license_field} | deps: {reqs}")
EOF
