#!/usr/bin/env bash
# Build the wheel, install it into a clean temporary virtual environment,
# and import the package and run its console command from outside the repository.
set -euo pipefail

REPOSITORY="$(cd "$(dirname "$0")/.." && pwd)"
SMOKE="$(mktemp -d)"

python3 -m venv "$SMOKE/venv"
"$SMOKE/venv/bin/pip" install --quiet "$REPOSITORY/dist/"text_to_ontology-*.whl

cd /
"$SMOKE/venv/bin/python" - <<'EOF'
import text_to_ontology
from text_to_ontology import api, cli, graph_management, pipeline, view_ontology
print("version:", text_to_ontology.__version__)
print("imported:", text_to_ontology.__file__)
EOF

"$SMOKE/venv/bin/text-to-ontology" --help > /dev/null
"$SMOKE/venv/bin/python" -m text_to_ontology --help > /dev/null
echo "install smoke test: OK"

rm -rf "$SMOKE"
