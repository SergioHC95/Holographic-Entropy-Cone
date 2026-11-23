import json
import runpy
import unittest
from math import comb
from pathlib import Path

RESEARCH = Path(__file__).resolve().parents[1] / "research"
CHECKER = runpy.run_path(str(RESEARCH / "verify_pentagon_minimum.py"))


class PentagonMinimumTests(unittest.TestCase):
    def test_published_lower_and_upper_bounds_meet(self):
        supports, cuts, minimum = CHECKER["verify"]()
        self.assertEqual((supports, cuts, minimum), (comb(32, 12), 63 * (1 << 13), 20))

    def test_compatible_clauses_do_not_exclude_a_support(self):
        # A support containing both end bits hits both clauses, across the half split.
        with self.assertRaisesRegex(ValueError, "leaves a 12-type support"):
            CHECKER["exclude_small_supports"]({1, 1 << 31})

    def test_changing_weights_without_scale_is_not_a_witness(self):
        ledger = json.loads((RESEARCH / "six-party-section-ray-certificates.json").read_bytes())
        row = next(row for row in ledger["rays"] if row["key"] == "034")
        graph = CHECKER["paired_graph"](row)
        graph["weights"] = [2 * w for w in graph["weights"]]
        with self.assertRaisesRegex(ValueError, "min-cut mismatch"):
            CHECKER["check_witness"](row, graph)
