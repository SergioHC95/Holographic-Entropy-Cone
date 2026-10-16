"""Installed-package adapter: real full-cube calls, strict replies, no tool imports."""

import copy
import hashlib
import io
import json
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

from hec.count_proofs import canonical_json, compatible_vertices, geometry, parse_json
from hec.proof_builders import closure_seed, dag_seed, table_seed
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

    def test_native_audit_checks_seed_and_cube_without_a_duplicate_python_edge_pass(self):
        verifier = ReconstructionVerifier(closure_binary=self.closure, cube_binary=self.cube)
        try:
            with patch.object(
                ReconstructionProgram, "materialize_seed", side_effect=AssertionError("duplicate seed audit")
            ):
                result = verifier.verify(self.table)
        finally:
            verifier.close()
        self.assertTrue(result["ok"])
        self.assertEqual(result["seed_edges"], 12)
        self.assertEqual(result["checked_edges"], 12)

    def test_seed_identity_is_not_acceptance_and_native_still_rejects_bad_edges(self):
        p = geometry(3, (-1, -1, -1, 1, 1, 1, -1))
        rows = list(self.rows)
        rows[7] = (1, 1, 1, 1)
        bad = table_document(p, self.rows)
        bad["function"]["seed"] = table_seed(p, rows)
        program = ReconstructionProgram(bad)
        self.assertEqual(len(program.semantic_identity()), 64)
        with self.assertRaisesRegex(ValueError, "seed coupled"):
            program.materialize_seed()
        verifier = ReconstructionVerifier(closure_binary=self.closure, cube_binary=self.cube)
        try:
            with self.assertRaisesRegex(ValueError, "incomplete or misbound|seed edge"):
                verifier.verify(bad)
        finally:
            verifier.close()

    def test_owned_document_identity_does_not_reparse_or_reserialize(self):
        program = ReconstructionProgram(self.table)
        expected = hashlib.sha256(b"hec-count-proof/1\0" + canonical_json(self.table)).hexdigest()
        with patch("hec.reconstruction.parse_json", side_effect=AssertionError("redundant parse")):
            self.assertEqual(program.identity, expected)

    def assert_native_points(self, document, working_bytes):
        program = ReconstructionProgram(document)
        p, seed, scale = program.problem, program.materialize_seed(), program.clearing_scale
        for first in range(0, p.vertices, 64):
            queries = list(range(first, min(first + 64, p.vertices)))
            values = [value for row in seed.numerators for value in row]
            request = (
                struct.pack(
                    "<8sIIIIQIQQI",
                    b"HECCRP01",
                    1,
                    p.n,
                    0,
                    len(p.coefficients),
                    8 * len(values),
                    len(seed.vertices),
                    seed.scale,
                    scale,
                    len(queries),
                )
                + struct.pack(f"<{len(p.coefficients)}i", *p.coefficients)
                + struct.pack(f"<{len(queries)}I", *queries)
                + struct.pack(f"<{len(values)}Q", *values)
            )
            response = subprocess.run(
                [str(self.cube), "--working-bytes", str(working_bytes)],
                input=request,
                capture_output=True,
                check=True,
            ).stdout
            meta_bytes, row_bytes, query_bytes = struct.unpack("<IQI", response[:16])
            result = parse_json(response[16 : 16 + meta_bytes])
            self.assertIs(result["ok"], True)
            self.assertEqual(
                (result["checked_vertices"], result["checked_edges"]), (p.vertices, p.L * (p.vertices // 2))
            )
            self.assertEqual((row_bytes, query_bytes), (0, len(queries) * p.G * 8))
            returned = struct.unpack(f"<{len(queries) * p.G}Q", response[16 + meta_bytes :])
            cleared = tuple(value * scale for x in queries for value in program.evaluate(x))
            self.assertTrue(all(value.denominator == 1 for value in cleared))
            expected = tuple(value.numerator for value in cleared)
            self.assertEqual(returned, expected)
        return result

    def test_uniform_bit_transport_matches_every_reference_point_with_nested_disjoint_rules(self):
        original = ReconstructionProgram(parse_json((ROOT / "tests/fixtures/count_proof_n5.json").read_bytes()))
        coefficients = tuple(17 if c > 0 else c for c in original.problem.coefficients)
        p = geometry(5, coefficients)
        self.assertTrue(p.nested and p.disjoint)
        document = table_document(p, original.materialize_seed().numerators)
        for budget in (p.G * 16, 1024**2):
            with self.subTest(budget=budget):
                result = self.assert_native_points(document, budget)
                self.assertEqual(result["edge_metric"], "unary-prefix-hamming/1")

    def test_packed_metrics_and_wide_fallback_keep_exact_queries_and_full_coverage(self):
        for caps in ((1, 1, 1, 1), (16, 16, 16, 16), (17, 16, 16, 16), (32, 32, 32, 32), (33, 32, 32, 32)):
            capacity = sum(caps) + 1
            p = geometry(3, (-caps[0], -caps[1], -caps[2], capacity, capacity, capacity, -caps[3]))
            rows = [tuple(value * cap for value, cap in zip(row, caps, strict=True)) for row in self.rows]
            document = table_document(p, rows)
            for budget in (64, 1024**2):
                with self.subTest(caps=caps, budget=budget):
                    result = self.assert_native_points(document, budget)
                    expected = "unary-prefix-hamming/1" if sum(caps) <= 128 else "exact-count-l1/1"
                    self.assertEqual(result["edge_metric"], expected)
        p = geometry(3, (-1, -1, -1, 2, 3, 2, -1))
        weighted = table_document(p, self.rows)
        rational_rows = [tuple(map(Fraction, row)) for row in self.rows]
        rational_rows[7] = (Fraction(1, 3), Fraction(0), Fraction(0), Fraction(1))
        for document in (weighted, table_document(self.p, rational_rows)):
            for budget in (64, 1024**2):
                with self.subTest(scale=document["clearing_scale"], budget=budget):
                    self.assert_native_points(document, budget)

    def test_native_row_metric_exhaustive_pairs_cross_word_bounds_and_uint64_overflow(self):
        source = ROOT / "src/hec/_native/verify.cpp"
        harness = r"""
#define main hec_cube_protocol_main
#include SOURCE_PATH
#undef main
int main() {
  uint64_t state = 982451653;
  for (auto caps : std::vector<std::vector<int>>{{1,1,1,1},{16,16,16,16},{17,16,16,16},
                                               {32,32,32,32},{33,32,32,32}}) {
    Problem p(3, {-caps[0],-caps[1],-caps[2],3,3,3,-caps[3]});
    std::vector<uint64_t> scales{1,3};
    if (caps[0] == 1) scales.push_back(UINT64_MAX);
    for (uint64_t scale : scales) {
      RowMetric metric(p, scale);
      std::vector<uint64_t> rows(256 * p.G);
      for (unsigned x = 0; x < 256; ++x) for (unsigned g = 0; g < p.G; ++g) {
        uint64_t cap = scale * p.beta[g];
        state = state * 6364136223846793005ULL + 1442695040888963407ULL;
        rows[x*p.G+g] = x%4 == 0 ? 0 : x%4 == 1 ? cap : cap == UINT64_MAX ? state : state%(cap+1);
      }
      auto packed = rows;
      metric.pack(packed, 256);
      for (unsigned a = 0; a < 256; ++a) for (unsigned b = 0; b < 256; ++b) {
        Wide expected = 0;
        for (unsigned g = 0; g < p.G; ++g) {
          uint64_t x = rows[a*p.G+g], y = rows[b*p.G+g];
          expected += x > y ? x-y : y-x;
        }
        need(metric.distance(packed.data()+a*metric.stride(), packed.data()+b*metric.stride()) == expected,
             "count L1 metric changed");
      }
      bool rejected = false;
      try { metric.edge(0, packed.data(), packed.data()+metric.stride()); }
      catch (const std::exception&) { rejected = true; }
      need(rejected, "over-budget full cube edge accepted");
      if (scale != UINT64_MAX) {
        rows[0] = scale * p.beta[0] + 1;
        rejected = false;
        try { metric.pack(rows, 256); } catch (const std::exception&) { rejected = true; }
        need(rejected, "out-of-bounds count accepted by packing");
      }
    }
  }
}
""".replace("SOURCE_PATH", json.dumps(str(source)))
        with tempfile.TemporaryDirectory(prefix="hec-row-metric-") as directory:
            cpp, executable = Path(directory) / "metric.cpp", Path(directory) / "metric"
            cpp.write_text(harness)
            subprocess.run(["c++", "-std=c++17", "-O2", str(cpp), "-o", str(executable)], check=True)
            subprocess.run([str(executable)], check=True)

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

    def test_closure_keeps_golden_choice_order_as_anchors_and_pair_boxes_grow(self):
        program = ReconstructionProgram(parse_json((ROOT / "tests/fixtures/count_proof_n5.json").read_bytes()))
        rows = program.materialize_seed().numerators
        controls = (
            (0, 0, False, 282, (6, 14, 25, 37, 48, 63, 74, 92, 131, 143, 166, 173, 212, 219, 263)),
            (8, 16, True, 14, (10,)),
            (32, 64, True, 10, ()),
        )
        decoder = IntervalClosureDecoder(self.closure)
        for anchors, enumeration, pairs, choices, offsets in controls:
            seed = {
                "kind": "integer-interval-closure/1",
                "anchors": anchors,
                "enumeration": enumeration,
                "pairs": pairs,
                "policy": "lower",
                "choice_count": choices,
                "exceptions": [[index, "1"] for index in offsets],
            }
            with self.subTest(anchors=anchors, enumeration=enumeration, pairs=pairs):
                encoded = closure_seed(
                    program.problem, rows, self.closure, anchors=anchors, enumeration=enumeration, pairs=pairs
                )
                self.assertEqual(encoded, seed)
                self.assertEqual(tuple(decoder.decode(program.problem, seed)), rows)

    def test_native_interval_masks_match_scalar_inference_and_never_retire_a_live_constraint(self):
        with tempfile.TemporaryDirectory(prefix="hec-interval-controls-") as directory:
            executable = Path(directory) / "interval-controls"
            source = ROOT / "tests/native_interval_controls.cpp"
            subprocess.run(["c++", "-std=c++17", "-O2", str(source), "-o", str(executable)], check=True)
            subprocess.run([str(executable)], check=True)

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
