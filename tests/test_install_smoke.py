"""Opt-in installation smoke test: wheel into a clean venv, import outside.

Run it with:

    TEXT_TO_ONTOLOGY_INSTALL_SMOKE=1 python3 -m unittest \
        tests.test_install_smoke -v

It needs the `pip wheel` build step and network access to install rdflib into
the temporary environment, so the normal suite skips it.
"""

import os
import subprocess
import unittest
from pathlib import Path

REPOSITORY = Path(__file__).resolve().parent.parent
SMOKE_SCRIPT = REPOSITORY / "scripts" / "install_smoke.sh"


class InstallSmokeTest(unittest.TestCase):
    def test_the_wheel_installs_and_imports_outside_the_repository(self):
        if not os.environ.get("TEXT_TO_ONTOLOGY_INSTALL_SMOKE"):
            self.skipTest(
                "set TEXT_TO_ONTOLOGY_INSTALL_SMOKE=1 to run the "
                "installation smoke test")
        result = subprocess.run(
            ["bash", str(SMOKE_SCRIPT)],
            cwd=REPOSITORY, capture_output=True, text=True)
        self.assertEqual(
            result.returncode, 0,
            f"smoke test failed:\n{result.stdout}\n{result.stderr}")
        self.assertIn("install smoke test: OK", result.stdout)


if __name__ == "__main__":
    unittest.main()
