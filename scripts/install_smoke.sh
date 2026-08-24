#!/usr/bin/env bash
# Build the wheel, install it into a clean temporary virtual environment,
# and import the package from outside the repository.
set -euo pipefail

REPOSITORY="$(cd "$(dirname "$0")/.." && pwd)"
SMOKE="$(mktemp -d)"

python3 -m venv "$SMOKE/venv"
"$SMOKE/venv/bin/pip" install --quiet "$REPOSITORY/dist/"text_to_ontology-*.whl

cd /
"$SMOKE/venv/bin/python" - <<'EOF'
import text_to_ontology
from text_to_ontology import graph_management, ontology, view_ontology
print("version:", text_to_ontology.__version__)
print("imported:", text_to_ontology.__file__)
print("install smoke test: OK")
EOF

rm -rf "$SMOKE"
