"""Exact compact-domain proposals must still pass the sole full-cube verifier."""

import contextlib
import importlib.util
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from hec.count_proofs import canonical_json, geometry, inequality_id
from hec.proof_store import ProofCatalog
from hec.reconstruction import PIPELINE, ReconstructionProgram

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "compatible_seed_authoring", ROOT / "examples/compatible_seed_authoring.py"
)
authoring = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(authoring)


class CompatibleSeedAuthoringTests(unittest.TestCase):
    def construct(self, coefficients, n, scale=1):
        with contextlib.redirect_stdout(io.StringIO()):
            proof, result = authoring.construct(coefficients, n=n, scale=scale)
        self.assertIsNotNone(proof)
        self.assertEqual(proof["function"]["kind"], PIPELINE)
        self.assertFalse(result["floating_point_acceptance"])
        p = geometry(n, coefficients)
        expected = (p.vertices, p.L * (p.vertices // 2))
        self.assertEqual((result["audit"]["checked_vertices"], result["audit"]["checked_edges"]), expected)
        reference = ReconstructionProgram(proof).audit_reference()
        self.assertTrue(reference["ok"])
        self.assertEqual((reference["checked_vertices"], reference["checked_edges"]), expected)
        return proof

    def test_actual_subadditivity_weighted_and_mmi_maps_at_two_scales(self):
        for coefficients, n in (((1, 1, -1), 2), ((2, 1, -1), 2), ((-1, -1, -1, 1, 1, 1, -1), 3)):
            for scale in (1, 2):
                with self.subTest(coefficients=coefficients, scale=scale):
                    self.construct(coefficients, n, scale)

    def test_real_pr238_control_has_actual_complete_original_cube_acceptance(self):
        coefficients = (
            -1,
            -1,
            -1,
            -1,
            -1,
            0,
            -1,
            -1,
            0,
            0,
            -1,
            0,
            -1,
            0,
            0,
            0,
            0,
            -1,
            0,
            -1,
            0,
            2,
            1,
            0,
            0,
            0,
            0,
            1,
            0,
            2,
            0,
            1,
            -1,
            0,
            1,
            0,
            0,
            0,
            0,
            1,
            0,
            -1,
            1,
            0,
            0,
            0,
            1,
            1,
            0,
            0,
            -1,
            0,
            1,
            0,
            0,
            0,
            -1,
            -1,
            -1,
            0,
            0,
            0,
            0,
        )
        self.construct(coefficients, 6)

    def test_zero_and_empty_rhs_still_cover_the_complete_source_cube(self):
        for coefficients in ((0,), (1,)):
            self.construct(coefficients, 1)

    def test_scale_has_no_implicit_boolean_or_float_conversion(self):
        for scale in (0, -1, True, 1.0):
            with self.subTest(scale=scale), self.assertRaisesRegex(ValueError, "positive integer"):
                authoring.construct((1, 1, -1), n=2, scale=scale)

    def test_sat_failure_at_a_fixed_scale_is_not_an_inequality_invalidity_claim(self):
        with patch.object(authoring.Solver, "solve", return_value=False):
            with contextlib.redirect_stdout(io.StringIO()):
                proof, result = authoring.construct((1, 1, -1), n=2)
        self.assertIsNone(proof)
        self.assertFalse(result["inequality_invalidity_claimed"])

    def test_cli_selects_exact_cases_and_writes_only_the_primary_dataset(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            rows, index, output = root / "rows.json", root / "case-index.json", root / "proofs"
            rows.write_text("[[1,1,-1],[2,1,-1]]")
            wanted = inequality_id(geometry(2, (2, 1, -1)))
            selection = {"format": "hec-proof-authoring-case-index/1", "n": 2, "inequality_ids": [wanted]}
            index.write_bytes(canonical_json(selection))
            args = ["--rows", str(rows), "--n", "2", "--case-index", str(index), "--output", str(output)]
            with contextlib.redirect_stdout(io.StringIO()):
                authoring.main(args)
            catalog = ProofCatalog(output / "proofs.json")
            self.assertEqual(len(catalog), 1)
            self.assertEqual(catalog.entries[0]["inequality_id"], wanted)
            for bad in ({**selection, "n": True}, {**selection, "inequality_ids": [wanted, wanted]}):
                index.write_bytes(canonical_json(bad))
                with self.assertRaises(ValueError):
                    authoring.main(args)


if __name__ == "__main__":
    unittest.main()
