#!/usr/bin/env bash
# Smoke-test the built agentsquire wheel in a throwaway venv:
# install it, import it, and check the wheel metadata (MIT license,
# no consumer packages among the dependencies).
set -euo pipefail

cd "$(dirname "$0")/.."
wheel=$(ls -t dist/agentsquire-*.whl | head -1)
echo "smoke-testing $wheel"

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

python3 -m venv "$tmp/venv"
"$tmp/venv/bin/pip" install --quiet "$wheel"
"$tmp/venv/bin/python" - <<'EOF'
from importlib.metadata import metadata, requires

import agentsquire

md = metadata("agentsquire")
license_field = md.get("License-Expression") or md.get("License") or ""
assert "MIT" in license_field, f"license metadata is not MIT: {license_field!r}"

reqs = requires("agentsquire") or []
for banned in ("awiki", "specflo"):
    assert not any(banned in r for r in reqs), f"consumer package in deps: {reqs}"

print(f"smoke OK: {md['Name']} {md['Version']} | license: {license_field} | deps: {reqs}")
EOF
