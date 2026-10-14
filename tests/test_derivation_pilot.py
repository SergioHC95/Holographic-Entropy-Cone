"""Offline experiment tests do not read or change the authoritative corpus."""

import copy
import os
import random
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from derivation_pilot.recipes import (  # noqa: E402
    CutFunction,
    WorkLimit,
    choice_recipe,
    closure_call,
    cut_recipe,
    decode_closure,
    full_map_definition,
    policy_recipe,
    reconstruct,
)

from hec._count_verify import FullMapVerifier  # noqa: E402
from hec.count_proofs import compatible_vertices, geometry  # noqa: E402


def mmi_rows(problem):
    rows = []
    for vertex in compatible_vertices(problem):
        a, b, c = ((vertex >> axis) & 1 for axis in range(3))
        rows.append((a * b * (1 - c), a * c * (1 - b), b * c * (1 - a), max(a, b, c)))
    return rows


@unittest.skipUnless(shutil.which("c++"), "research native backend needs a C++17 compiler")
class DerivationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="hec-derivation-tests-")
        cls.binary = Path(os.environ.get("HEC_DERIVATION_BINARY", str(Path(cls.temporary.name) / "closure")))
        if not cls.binary.is_file():
            subprocess.run(
                [
                    "c++",
                    "-O3",
                    "-std=c++17",
                    "-Wall",
                    "-Wextra",
                    "-Werror",
                    str(ROOT / "tools/derivation_pilot/closure.cpp"),
                    "-o",
                    str(cls.binary),
                ],
                check=True,
            )

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def test_mmi_is_completely_derived_from_boundary(self):
        problem = geometry(3, (-1, -1, -1, 1, 1, 1, -1))
        rows = mmi_rows(problem)
        result = closure_call(self.binary, problem, mode="encode", rows=rows)
        self.assertEqual(result.tape, [])
        self.assertEqual(result.stats["initial_forced_cells"], 32)
        for policy in ("lower", "upper"):
            _, reconstructed, _ = reconstruct(policy_recipe(problem, policy), self.binary)
            self.assertEqual(reconstructed, rows)
            verifier = FullMapVerifier()
            try:
                self.assertEqual(verifier.verify(full_map_definition(problem, reconstructed))["checked_edges"], 12)
            finally:
                verifier.close()

    def test_high_capacity_free_choices_are_not_claimed_forced(self):
        problem = geometry(3, (-1, -1, -1, 3, 3, 3, -1))
        rows = mmi_rows(problem)
        result = closure_call(self.binary, problem, mode="encode", rows=rows)
        self.assertGreater(len(result.tape), 0)
        self.assertLess(result.stats["initial_forced_cells"], result.stats["cells"])
        self.assertEqual(decode_closure(choice_recipe(problem, result), self.binary).rows, rows)

    def test_random_integral_maps_are_not_excluded_by_inference(self):
        # Capacity 4 makes any Boolean vector difference admissible. These
        # twenty independently chosen maps test all inference rules against
        # known feasible completions, not just one special solver output.
        generator = random.Random(20261013)
        problem = geometry(3, (-1, -1, -1, 4, 4, 4, -1))
        for _ in range(20):
            rows = [tuple(generator.randrange(2) for _ in range(4)) for _ in range(8)]
            for vertex, image in problem.boundary:
                rows[vertex] = image
            for enumeration in (0, 64):
                result = closure_call(self.binary, problem, mode="encode", rows=rows, enumeration=enumeration)
                document = choice_recipe(problem, result, enumeration=enumeration)
                self.assertEqual(decode_closure(document, self.binary).rows, rows)

    def test_missing_extra_bad_and_fractional_choices_fail(self):
        problem = geometry(3, (-1, -1, -1, 3, 3, 3, -1))
        result = closure_call(self.binary, problem, mode="encode", rows=mmi_rows(problem))
        document = choice_recipe(problem, result)
        for mutation in ("missing", "extra", "range", "fraction", "claim", "lattice", "settings"):
            bad = copy.deepcopy(document)
            function = bad["function"]
            if mutation == "missing":
                function["choice_count"] -= 1
                function["exceptions"] = [item for item in function["exceptions"] if item[0] < function["choice_count"]]
            elif mutation == "extra":
                function["choice_count"] += 1
            elif mutation == "range":
                function["exceptions"] = [[0, "65535"]]
            elif mutation == "fraction":
                function["exceptions"] = [[0, "0.5"]]
            elif mutation == "claim":
                bad["verified"] = True
            elif mutation == "lattice":
                function["seed_scale"] = "2"
            else:
                function["enumeration"] = True
            with self.assertRaises(ValueError, msg=mutation):
                decode_closure(bad, self.binary)

    def test_six_cut_formulas_reconstruct_mmi_and_reject_bad_references(self):
        problem = geometry(3, (-1, -1, -1, 1, 1, 1, -1))
        rows = mmi_rows(problem)
        document, stats = cut_recipe(problem, list(compatible_vertices(problem)), rows)
        self.assertEqual(stats["unique_terms"], 6)
        self.assertEqual([CutFunction(document)[vertex] for vertex in range(8)], rows)
        bad = copy.deepcopy(document)
        bad["function"]["groups"][0][0] = [len(bad["function"]["terms"])]
        with self.assertRaises(ValueError):
            CutFunction(bad)
        bad = copy.deepcopy(document)
        bad["function"]["terms"].append([1, 1])
        with self.assertRaises(ValueError):
            CutFunction(bad)
        bad = copy.deepcopy(document)
        bad["function"]["terms"] = [[0, 0], [1, 0]]
        bad["function"]["groups"] = [[[0]]] * problem.G
        with self.assertRaisesRegex(ValueError, "unreachable"):
            CutFunction(bad)
        with self.assertRaises(WorkLimit):
            cut_recipe(problem, list(compatible_vertices(problem)), rows, max_terms=0)

    def test_formula_math_is_not_conferred_by_valid_syntax(self):
        problem = geometry(3, (-1, -1, -1, 1, 1, 1, -1))
        document, _ = cut_recipe(problem, list(compatible_vertices(problem)), mmi_rows(problem))
        document["function"]["terms"] = [[0, 0]]
        document["function"]["groups"] = [[[0]]] * 4
        _, rows, _ = reconstruct(document, self.binary)
        with self.assertRaisesRegex(ValueError, "boundary"):
            full_map_definition(problem, rows)

    def test_schema_never_accepts_experiment_as_production_proof(self):
        from hec.count_proofs import check_count_proof

        problem = geometry(3, (-1, -1, -1, 1, 1, 1, -1))
        with self.assertRaises(ValueError):
            check_count_proof(policy_recipe(problem, "lower"))

    def test_unsupported_dimensions_fail_before_enumeration_or_overflow(self):
        from derivation_pilot.recipes import recipe_geometry

        problem = geometry(3, (-1, -1, -1, 1, 1, 1, -1))
        document = policy_recipe(problem, "lower")
        bad = copy.deepcopy(document)
        bad["inequality"]["n"] = 10**12
        with self.assertRaisesRegex(ValueError, "n=1"):
            recipe_geometry(bad)
        bad = copy.deepcopy(document)
        bad["inequality"]["coefficients"][3] = str(10**80)
        with self.assertRaisesRegex(ValueError, "wider"):
            recipe_geometry(bad)


if __name__ == "__main__":
    unittest.main()
