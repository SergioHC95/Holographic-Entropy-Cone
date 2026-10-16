"""Standard-only search, atomic authoring, native packaging and CI contracts."""

import copy
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import Mock, patch

import numpy as np
from proof_fixtures import document, native_release

from hec.contractions import check_contraction, find_contraction
from hec.count_proofs import canonical_json, geometry, proof_id
from hec.inequality_records import InequalityCatalog
from hec.native import build_backends, load_backends
from hec.proof_builders import proof_from_boolean_table, proof_from_seed_rows
from hec.proof_store import ProofCatalog, write_proof_dataset
from hec.reconstruction import PIPELINE, ReconstructionProgram
from hec.reconstruction_verify import ReconstructionVerifier
from hec.runs import create_run_output, run_generation
from hec.serialization import save_json


class AuthoringTests(unittest.TestCase):
    def setUp(self):
        self.p = geometry(2, (1, 1, -1))
        self.rows = [(0,), (1,), (1,)]
        self.proof = document(self.p, self.rows)

    def test_search_returns_only_a_freshly_audited_standard_proof(self):
        table = np.array([[0], [1], [1], [1]], dtype=np.int8)
        with patch("hec.contraction_solver.solve_contraction", return_value=(table, {"elapsed_s": 0})):
            result = find_contraction(self.p.coefficients, 2)
        self.assertEqual(result["status"], "proved")
        self.assertNotIn("images", result)
        self.assertEqual(result["proof"]["function"]["kind"], PIPELINE)
        self.assertEqual(result["audit"]["checked_edges"], 4)
        self.assertTrue(check_contraction(None, None, result["proof"])["ok"])
        self.assertFalse(check_contraction(None, None, {"images": ["0", "1", "1", "1"]})["ok"])

    def test_raw_solver_status_and_bad_arrays_cannot_authorize_a_proof(self):
        for table in (np.ones((3, 1), dtype=np.int8), np.ones((4, 1), dtype=float), np.full((4, 1), 2)):
            with self.subTest(table=table), self.assertRaises(ValueError):
                proof_from_boolean_table(self.p, table)
        with patch("hec.contraction_solver.solve_contraction", return_value=(None, {"status": "unfinished"})):
            self.assertNotIn("proof", find_contraction(self.p.coefficients, 2))

    def test_solver_and_checker_require_exact_context_without_rounding(self):
        for coefficients in ((True, 1, -1), (1.0, 1, -1), (1, 1, -1.01)):
            with self.assertRaises(ValueError):
                find_contraction(coefficients, 2)
            self.assertFalse(check_contraction(coefficients, 2, self.proof)["ok"])
        self.assertFalse(check_contraction(self.p.coefficients, True, self.proof)["ok"])
        self.assertFalse(check_contraction((2, 1, -1), 2, self.proof)["ok"])

    def test_zero_and_empty_rhs_searches_still_have_complete_proofs(self):
        for coefficients in ((0,), (1,)):
            result = find_contraction(coefficients, 1)
            self.assertEqual(result["status"], "proved")
            self.assertTrue(result["audit"]["ok"])
            self.assertEqual(result["audit"]["checked_vertices"], 1 if coefficients == (0,) else 2)

    def test_seed_authoring_is_deterministic_and_has_no_stored_acceptance_claim(self):
        a = proof_from_seed_rows(self.p, iter(self.rows))
        b = proof_from_seed_rows(self.p, self.rows)
        self.assertEqual(canonical_json(a), canonical_json(b))
        self.assertNotIn("verified", a)
        self.assertTrue(ReconstructionProgram(a).audit_reference()["ok"])
        expected = hashlib.sha256(b"hec-count-proof\0" + canonical_json(a)).hexdigest()
        self.assertEqual(proof_id(a), expected)

    def test_dataset_stream_audits_once_and_atomically_publishes_exact_bindings(self):
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "new"
            verifier = ReconstructionVerifier(closure_binary="", cube_binary="")
            spy = Mock(wraps=verifier)
            result = write_proof_dataset(target, [self.proof], verifier=spy)
            self.assertEqual(result["proofs"], 1)
            self.assertEqual(spy.verify.call_count, 1)
            self.assertEqual(ProofCatalog(target / "proofs.json")[0], self.proof)
            InequalityCatalog(target / "inequalities.json").check_bindings(ProofCatalog(target / "proofs.json"))
            with self.assertRaises(ValueError):
                write_proof_dataset(target, [self.proof], verifier=spy)

    def test_failed_or_duplicate_dataset_never_publishes_a_partial_target(self):
        for records in ([], [self.proof, self.proof], [{"status": "proved", "images": []}]):
            with tempfile.TemporaryDirectory() as temporary:
                target = Path(temporary) / "new"
                with self.assertRaises(ValueError):
                    write_proof_dataset(target, records)
                self.assertFalse(target.exists())

    def test_inequality_authoring_metadata_is_owned_not_the_callers_mutable_dict(self):
        original = copy.deepcopy(self.proof)
        verifier = ReconstructionVerifier(closure_binary="", cube_binary="")

        def verify(owned):
            original["inequality"]["coefficients"][0] = "999"
            return verifier.verify(owned)

        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "new"
            write_proof_dataset(target, [original], verifier=Mock(verify=verify))
            stored = ProofCatalog(target / "proofs.json")
            self.assertEqual(stored[0], self.proof)
            InequalityCatalog(target / "inequalities.json").check_bindings(stored)


class GenerationOutputTests(unittest.TestCase):
    def test_output_helper_returns_only_a_new_directory_and_refuses_collisions(self):
        with tempfile.TemporaryDirectory() as temporary, patch("hec.runs.datetime") as clock:
            clock.now.return_value.strftime.return_value = "fixture"
            output = create_run_output("graphs", temporary)
            self.assertEqual(output, Path(temporary) / "graphs_fixture")
            self.assertTrue(output.is_dir())
            self.assertEqual(list(output.iterdir()), [])
            with self.assertRaises(FileExistsError):
                create_run_output("graphs", temporary)

    def test_generation_preserves_ordered_records_and_timings_when_workers_finish_out_of_order(self):
        with (
            tempfile.TemporaryDirectory() as temporary,
            patch("hec.runs.datetime") as clock,
            patch("hec.runs.available_ns", return_value=[2]),
            patch("hec.runs.load_hec_data", return_value=[11, 22, 33]),
            patch("hec.runs.as_completed", side_effect=lambda futures: reversed(tuple(futures))),
        ):
            clock.now.return_value.strftime.return_value = "fixture"
            writer = Mock(side_effect=save_json)
            run_generation(
                prefix="graphs",
                run_root_parent=temporary,
                data_root=temporary,
                kind="rays",
                record_name="graphs",
                worker=lambda n, index, value: (value, {"index": index}, f"n={n}, index={index}"),
                writer=writer,
                executor=lambda: ThreadPoolExecutor(max_workers=2),
                workers=2,
                write_every=1,
            )
            output = Path(temporary) / "graphs_fixture"
            writer.assert_called_once_with(output / "graphs_n2.json", [11, 22, 33])
            self.assertEqual(json.loads((output / "graphs_n2.json").read_text()), [11, 22, 33])
            self.assertEqual(json.loads((output / "timings.json").read_text()), {"2": [{"index": i} for i in range(3)]})


class DistributionTests(unittest.TestCase):
    def test_checks_require_the_supported_cli_and_the_canonical_route_still_works(self):
        unsupported = subprocess.run(
            [sys.executable, "-m", "hec.checks", "facets", "--n", "1"],
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(unsupported.returncode, 0)
        self.assertIn("hec check", unsupported.stderr)
        supported = subprocess.run(
            [
                sys.executable,
                "-m",
                "hec",
                "check",
                "database-bindings",
                "--n",
                "1",
                "--root",
                str(Path(__file__).resolve().parents[1] / "data"),
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        self.assertIn("1 inequality/1 proof", supported.stdout)

    def test_no_historical_acceptance_implementations_ship(self):
        for module in (
            "hec.reconstruction_store",
            "hec._archive_proof_store",
            "hec._count_kernel",
            "hec._count_dag",
            "hec._count_verify",
        ):
            self.assertIsNone(importlib.util.find_spec(module))

    def test_bound_native_release_is_reusable_and_source_binary_checked(self):
        native_release()  # Actual current compiler, not a mocked successful build.
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "bad"
            target.mkdir()
            with self.assertRaises((ValueError, FileNotFoundError)):
                build_backends(target)
        with patch.dict(os.environ, {"HEC_NATIVE_DIR": "/missing-hec-native-release"}):
            with self.assertRaises(ValueError):
                ReconstructionVerifier()
        with self.assertRaises(ValueError):
            load_backends("/missing-hec-native-release")
