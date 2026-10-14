import copy
import shutil
import subprocess
import tempfile
import unittest
from fractions import Fraction
from pathlib import Path

from hec._count_verify import FullMapVerifier
from hec.count_proofs import encode_rows, geometry, make_count_proof

ROOT = Path(__file__).resolve().parents[1]


class ExactFallbackTests(unittest.TestCase):
    def test_small_arbitrary_precision_full_cube_is_exact(self):
        problem = geometry(2, (10**80 + 1, 1, -1))
        proof = make_count_proof(problem, [(0,), (1,), (1,)], transport=True)
        verifier = FullMapVerifier()
        self.assertEqual(verifier.verify(proof)["checked_edges"], 4)
        verifier.close()

    def test_small_fractional_seed_full_cube_is_exact(self):
        problem = geometry(3, (-1, -1, -1, 2, 2, 2, -1))
        rows = [(Fraction(1, 2),) * 4 for _ in range(8)]
        for vertex, image in problem.boundary:
            rows[vertex] = image
        proof = make_count_proof(problem, rows, integral=False, transport=True)
        verifier = FullMapVerifier()
        self.assertEqual(verifier.verify(proof)["checked_edges"], 12)
        verifier.close()


@unittest.skipUnless(shutil.which("c++"), "native exact verifier needs a C++17 compiler")
class NativeProofTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scratch = tempfile.TemporaryDirectory(prefix="hec-exact-proof-")
        cls.binary = Path(cls.scratch.name) / "verify_count_proofs"
        subprocess.run(
            [
                shutil.which("c++"),
                "-O3",
                "-std=c++17",
                "-Wall",
                "-Wextra",
                "-Werror",
                str(ROOT / "tools/verify_count_proofs.cpp"),
                "-o",
                str(cls.binary),
            ],
            check=True,
        )

    @classmethod
    def tearDownClass(cls):
        cls.scratch.cleanup()

    def audit(self, proof):
        verifier = FullMapVerifier(self.binary)
        try:
            return verifier.verify(proof)
        finally:
            verifier.close()

    def test_weighted_cases_audit_every_source_edge(self):
        for coefficients in ((1, 1, -1), (2, 1, -1), (5, 3, -2)):
            problem = geometry(2, coefficients)
            proof = make_count_proof(problem, [(0,), (problem.beta[0],), (problem.beta[0],)], transport=True)
            result = self.audit(proof)
            self.assertEqual(result["checked_vertices"], 4)
            self.assertEqual(result["checked_edges"], 4)
            self.assertEqual(result["scope"], "original-cube-all-edges")

    def test_valid_hashes_and_boundary_are_not_a_mathematical_proof(self):
        problem = geometry(3, (-1, -1, -1, 1, 1, 1, -1))
        rows = [
            (0, 0, 0, 0),
            (0, 0, 0, 1),
            (0, 0, 0, 1),
            (1, 0, 0, 1),
            (0, 0, 0, 1),
            (0, 1, 0, 1),
            (0, 0, 1, 1),
            (0, 0, 0, 1),
        ]
        proof = make_count_proof(problem, rows, transport=True)
        self.assertEqual(self.audit(proof)["checked_edges"], 12)
        rows[7] = (0, 0, 0, 0)  # Preserves every party/purifier image, breaks an edge.
        bad = copy.deepcopy(proof)
        bad["function"]["rows"], _ = encode_rows(problem, rows, integral=True)
        with self.assertRaisesRegex(ValueError, "edge violation"):
            self.audit(bad)

    def test_scale_incomplete_domain_bounds_unknown_constructor_and_claims_fail(self):
        problem = geometry(2, (2, 1, -1))
        proof = make_count_proof(problem, [(0,), (1,), (1,)], transport=True)
        for mutation in ("scale", "coverage", "bounds", "constructor", "inherited-valid", "audit-format"):
            bad = copy.deepcopy(proof)
            if mutation == "scale":
                bad["clearing_scale"]["value"] = "1"
            elif mutation == "coverage":
                bad["function"]["rows"]["count"] = 2
            elif mutation == "bounds":
                # Widening the bit width isn't a permission to exceed beta.
                bad["function"]["rows"]["data"] = "/w=="
            elif mutation == "constructor":
                bad["function"]["kind"] = "unproved-constructor/1"
            elif mutation == "inherited-valid":
                bad["verified"] = True
            else:
                bad["format"] = "hec-count-audit/1"
            with self.assertRaises(ValueError):
                self.audit(bad)
