#!/usr/bin/env python3
"""Temporary compatibility wrapper: runs the packaged CLI.

The real CLI lives in src/text_to_ontology/cli.py. This wrapper keeps
`python ontology.py ...` working from a checkout; after `pip install -e .`
(or a normal install) the package is importable directly.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from text_to_ontology.cli import main

if __name__ == "__main__":
    main()
