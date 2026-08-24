#!/usr/bin/env python3
"""Temporary compatibility wrapper: runs the packaged CLI.

The real module lives in src/text_to_ontology/ontology.py. This wrapper keeps
`python ontology.py ...` working from a checkout; after `pip install -e .`
(or a normal install) the package is importable directly.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from text_to_ontology.ontology import main

if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError) as error:
        print(f"Error: {error}", file=sys.stderr)
        raise SystemExit(1)
