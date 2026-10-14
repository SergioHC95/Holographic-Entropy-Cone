import copy
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from derivation_pilot.anchors import definition, derive  # noqa: E402

from hec.count_proofs import geometry  # noqa: E402


@unittest.skipUnless(shutil.which("c++"), "fixed-anchor research backend needs C++17")
class FixedAnchorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scratch = tempfile.TemporaryDirectory(prefix="hec-anchor-tests-")
        cls.binary = Path(os.environ.get("HEC_ANCHOR_BINARY", str(Path(cls.scratch.name) / "anchors")))
        if not cls.binary.is_file():
            subprocess.run(
                [
                    "c++",
                    "-O3",
                    "-std=c++17",
                    "-Wall",
                    "-Wextra",
                    "-Werror",
                    str(ROOT / "tools/derivation_pilot/anchors.cpp"),
                    "-o",
                    str(cls.binary),
                ],
                check=True,
            )

    @classmethod
    def tearDownClass(cls):
        cls.scratch.cleanup()

    def test_no_source_table_needed_for_mmi(self):
        problem = geometry(3, (-1, -1, -1, 1, 1, 1, -1))
        _, rows, stats, diagnostics = derive(definition(problem, []), self.binary)
        self.assertTrue(stats["ok"])
        self.assertEqual(rows[3], (1, 0, 0, 1))
        self.assertEqual(rows[7], (0, 0, 0, 1))
        self.assertIsNone(diagnostics)

    def test_contradictory_anchor_does_not_become_a_proof(self):
        problem = geometry(3, (-1, -1, -1, 1, 1, 1, -1))
        _, rows, stats, _ = derive(definition(problem, [(0, (1, 0, 0, 0))]), self.binary)
        self.assertIsNone(rows)
        self.assertFalse(stats["ok"])

    def test_float_outside_domain_duplicate_and_claims_are_rejected(self):
        problem = geometry(3, (-1, -1, -1, 1, 1, 1, -1))
        original = definition(problem, [(1, (0, 0, 0, 1))])
        for mutation in ("float", "domain", "duplicate", "claim"):
            document = copy.deepcopy(original)
            if mutation == "float":
                document["function"]["pins"][0][1][0] = "0.5"
            elif mutation == "domain":
                document["function"]["pins"][0][0] = 8
            elif mutation == "duplicate":
                document["function"]["pins"].append(document["function"]["pins"][0])
            else:
                document["verified"] = True
            with self.assertRaises(ValueError):
                derive(document, self.binary)


if __name__ == "__main__":
    unittest.main()
