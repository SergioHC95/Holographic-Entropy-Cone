"""Installed-package adapter: real full-cube calls, strict replies, no tool imports."""

import copy
import hashlib
import io
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
from fractions import Fraction
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from proof_fixtures import cut_seed, departed_definition, native_release
from proof_fixtures import document as table_document

from hec.count_proofs import canonical_json, compatible_vertices, geometry
from hec.proof_builders import closure_seed, dag_seed
from hec.reconstruction import ReconstructionProgram, make_pipeline
from hec.reconstruction_verify import IndependentCubeAuditor, IntervalClosureDecoder, ReconstructionVerifier

ROOT = Path(__file__).resolve().parents[1]


def fixture():
    p = geometry(3, (-1, -1, -1, 2, 2, 2, -1))
    vertices = list(compatible_vertices(p))
    rows = [
        tuple((a * b * (1 - c), a * c * (1 - b), b * c * (1 - a), max(a, b, c)))
        for x in vertices
        for a, b, c in [tuple((x >> axis) & 1 for axis in range(3))]
    ]
    return p, vertices, rows


@unittest.skipUnless(shutil.which("c++"), "native adapter controls need C++17")
class ReconstructionVerifierTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="hec-reconstruction-adapter-")
        cls.closure, cls.cube = native_release()["closure"], native_release()["cube"]

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def setUp(self):
        self.p, self.vertices, self.rows = fixture()
        self.table = table_document(self.p, self.rows)

    def test_all_four_primitives_execute_the_same_independent_full_cube_protocol(self):
        verifier = ReconstructionVerifier(closure_binary=self.closure, cube_binary=self.cube)
        encoded = closure_seed(self.p, self.rows, self.closure)
        closure_doc = copy.deepcopy(self.table)
        closure_doc["function"]["seed"] = encoded
        docs = [
            self.table,
            make_pipeline(self.p, dag_seed(self.p, self.rows)),
            make_pipeline(self.p, cut_seed(self.p, self.vertices, self.rows)),
            closure_doc,
        ]
        identities = set()
        try:
            for doc in docs:
                result = verifier.verify(doc)
                self.assertEqual((result["checked_vertices"], result["checked_edges"]), (8, 12))
                self.assertEqual(result["scope"], "original-cube-all-edges")
                self.assertFalse(result["source_tables_read"])
                self.assertEqual(result["binary_sha256"], hashlib.sha256(self.cube.read_bytes()).hexdigest())
                identities.add(result["semantic_map_id"])
        finally:
            verifier.close()
        self.assertEqual(len(identities), 1)

    def test_arbitrary_precision_small_case_fallback_is_exhaustive(self):
        scale = (1 << 130) + 51
        rows = [[Fraction(value) for value in row] for row in self.rows]
        rows[7][0] = Fraction(1, scale)
        document = table_document(self.p, rows)
        verifier = ReconstructionVerifier(cube_binary=self.cube, closure_binary="")
        try:
            result = verifier.verify(document)
            self.assertIsNone(verifier.auditor.process)
        finally:
            verifier.close()
        self.assertEqual(result["implementation"], "exact-fraction-reference/1")
        self.assertEqual((result["checked_vertices"], result["checked_edges"]), (8, 12))

    def test_malformed_or_incomplete_native_failure_never_uses_reference_fallback(self):
        verifier = ReconstructionVerifier(cube_binary=self.cube, closure_binary="")
        try:
            for outcome in (
                ValueError("proof needs a wider exact cube-audit backend"),
                {"ok": True, "scope": "compatible-seed-only"},
            ):
                with (
                    patch.object(
                        verifier.auditor,
                        "verify",
                        side_effect=outcome if isinstance(outcome, Exception) else None,
                        return_value=outcome,
                    ),
                    patch.object(
                        ReconstructionProgram,
                        "audit_reference",
                        side_effect=AssertionError("malformed reply fell back"),
                    ),
                ):
                    with self.assertRaises(ValueError):
                        verifier.verify(self.table)
        finally:
            verifier.close()

    def test_stored_verified_flags_and_executable_paths_are_not_accepted(self):
        verifier = ReconstructionVerifier(cube_binary=self.cube, closure_binary=self.closure)
        try:
            for mutation in ("verified", "executable", "legacy"):
                bad = copy.deepcopy(self.table)
                if mutation == "verified":
                    bad["verified"] = True
                elif mutation == "executable":
                    bad["function"]["seed"]["binary"] = "/anything"
                else:
                    bad = departed_definition(self.p)
                with self.assertRaises(ValueError):
                    verifier.verify(bad)
        finally:
            verifier.close()

    def test_low_level_reply_types_request_identity_and_lengths_fail_closed(self):
        base = {
            "ok": True,
            "index": 1,
            "n": 3,
            "L": 3,
            "G": 4,
            "R": 4,
            "seed_vertices": 8,
            "seed_scale": "1",
            "clearing_scale": "1",
            "checked_vertices": 8,
            "checked_edges": 12,
            "scope": "original-cube-all-edges",
            "arithmetic": "uint64-values-uint128-sums",
        }
        for mutation in ("bool-index", "partial", "rows", "truncated"):
            reply = dict(base)
            if mutation == "bool-index":
                reply["index"] = True
            if mutation == "partial":
                reply["checked_edges"] = 11
            raw = canonical_json(reply)
            output = struct.pack("<IQI", len(raw), 1 if mutation == "rows" else 0, 0) + raw
            if mutation == "truncated":
                output = output[:-2]
            verifier = IndependentCubeAuditor.__new__(IndependentCubeAuditor)
            verifier.binding = Mock(sha256="0" * 64)
            verifier.sequence = 0
            verifier.process = SimpleNamespace(stdin=io.BytesIO(), stdout=io.BytesIO(output))
            with self.assertRaises(ValueError):
                verifier.verify(self.p, self.vertices, 1, self.rows)

    def test_closure_decoder_rejects_untrusted_fields_and_changed_binary(self):
        seed = closure_seed(self.p, self.rows, self.closure)
        decoder = IntervalClosureDecoder(self.closure)
        self.assertEqual(decoder.decode(self.p, seed), self.rows)
        with self.assertRaises(ValueError):
            decoder.decode(self.p, {**seed, "path": "/anything"})
        decoder.binding.sha256 = "0" * 64
        with self.assertRaisesRegex(ValueError, "changed"):
            decoder.decode(self.p, seed)

    def test_adapter_imports_without_any_research_packages_available(self):
        env = dict(os.environ, PYTHONPATH=str(ROOT / "src"), OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1")
        code = (
            "import sys; import hec.reconstruction_verify; "
            "assert not any(x.startswith(('corpus_derivations', 'derivation_pilot')) for x in sys.modules)"
        )
        subprocess.run([sys.executable, "-c", code], cwd=self.temporary.name, env=env, check=True)


@unittest.skipUnless(shutil.which("c++"), "standard verifier configuration needs C++17")
class StandardCubeConfigurationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="hec-standard-native-")
        cls.binary = native_release()["cube"]

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def test_configured_buffer_is_in_actual_command_and_exact_tiled_reply(self):
        p, _vertices, rows = fixture()
        document = table_document(p, rows)
        verifier = ReconstructionVerifier(closure_binary="", cube_binary=self.binary, cube_working_bytes=64)
        try:
            result = verifier.verify(document)
            self.assertEqual(verifier.auditor.process.args, [str(self.binary), "--working-bytes", "64"])
            self.assertEqual((result["checked_vertices"], result["checked_edges"]), (8, 12))
            self.assertEqual(result["working_layout"], "exact-tiles/1")
            self.assertEqual(result["output_row_storage_limit"], 64)
            self.assertLessEqual(result["output_row_storage_bytes"], 64)
        finally:
            verifier.close()

    def test_trusted_configuration_rejects_inexact_or_missing_backend(self):
        for value in (True, 0, -1, 1.5, "64", 31 * 1024**3):
            with self.subTest(value=value), self.assertRaises(ValueError):
                ReconstructionVerifier(closure_binary="", cube_binary=self.binary, cube_working_bytes=value)
        with self.assertRaisesRegex(ValueError, "explicit exact backend"):
            ReconstructionVerifier(closure_binary="", cube_binary="", cube_working_bytes=64)
        for raw in ("01", "1.0", "-1", " 64", ""):
            with patch.dict(os.environ, {"HEC_RECONSTRUCTION_WORKING_BYTES": raw}), self.assertRaises(ValueError):
                ReconstructionVerifier(closure_binary="", cube_binary=self.binary)

    def test_shared_full_point_rule_handles_empty_output(self):
        p = geometry(1, (1,))
        document = table_document(p, [(), ()])
        verifier = ReconstructionVerifier(closure_binary="", cube_binary=self.binary, cube_working_bytes=64)
        try:
            result = verifier.verify(document)
        finally:
            verifier.close()
        self.assertEqual((result["checked_vertices"], result["checked_edges"]), (2, 1))
        self.assertEqual(result["working_layout"], "full-table/1")
        self.assertEqual(result["output_row_storage_bytes"], 0)


if __name__ == "__main__":
    unittest.main()
