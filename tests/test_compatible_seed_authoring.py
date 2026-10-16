"""Exact compact-domain proposals must still pass the sole full-cube verifier."""

import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from hec import authoring, construct_contraction
from hec.cli import main as cli_main
from hec.count_proofs import geometry, inequality_id
from hec.proof_store import ProofCatalog
from hec.reconstruction import PIPELINE, ReconstructionProgram
from hec.reconstruction_verify import ReconstructionVerifier


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

    def test_real_six_party_control_has_actual_complete_original_cube_acceptance(self):
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

    def test_cli_writes_only_the_primary_dataset_and_never_overwrites(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            rows, output = root / "rows.json", root / "proofs"
            rows.write_text("[[2,1,-1]]")
            wanted = inequality_id(geometry(2, (2, 1, -1)))
            args = ["--rows", str(rows), "--n", "2", "--output", str(output)]
            with contextlib.redirect_stdout(io.StringIO()):
                authoring.main(args)
            catalog = ProofCatalog(output / "proofs.json")
            self.assertEqual(len(catalog), 1)
            self.assertEqual(catalog.entries[0]["inequality_id"], wanted)
            with self.assertRaises(ValueError), contextlib.redirect_stdout(io.StringIO()):
                authoring.main(args)

    def test_public_production_constructor_returns_only_a_freshly_audited_standard_proof(self):
        with contextlib.redirect_stdout(io.StringIO()):
            result = construct_contraction((1, 1, -1), 2)
        self.assertEqual(result["status"], "proved")
        self.assertEqual(result["proof"]["function"]["kind"], PIPELINE)
        self.assertEqual(result["audit"]["checked_edges"], 4)
        self.assertTrue(ReconstructionProgram(result["proof"]).audit_reference()["ok"])

    def test_supported_cli_audits_once_per_map_instead_of_constructor_plus_writer_twice(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            rows, output = root / "rows.json", root / "proofs"
            rows.write_text("[[1,1,-1]]")
            actual_verify = ReconstructionVerifier.verify
            with (
                contextlib.redirect_stdout(io.StringIO()),
                patch.object(ReconstructionVerifier, "verify", autospec=True, side_effect=actual_verify) as audit,
            ):
                cli_main(["construct", "--rows", str(rows), "--n", "2", "--output", str(output)])
            self.assertEqual(audit.call_count, 1)
            self.assertEqual(len(ProofCatalog(output / "proofs.json")), 1)


if __name__ == "__main__":
    unittest.main()
