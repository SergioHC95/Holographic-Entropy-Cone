"""Actual tiled/full/reference differentials; no sampled mathematical acceptance."""

import os
import shutil
import struct
import subprocess
import tempfile
import unittest
from fractions import Fraction
from pathlib import Path

from corpus_derivations.native import Auditor, Lookup

from hec._count_transport import evaluate_transport
from hec.count_proofs import compatible_vertices, decode_rows, geometry, parse_json, proof_geometry

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which("c++"), "exact tiled auditor controls need C++17")
class TiledAuditorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="hec-tiled-controls-")
        directory = Path(cls.temporary.name)
        cls.tiled = Path(os.environ.get("HEC_TILED_AUDITOR", str(directory / "tiled")))
        cls.full = Path(os.environ.get("HEC_WIDE_AUDITOR", str(directory / "full")))
        for binary, source in (
            (cls.tiled, "tools/corpus_derivations/audit_tiled.cpp"),
            (cls.full, "tools/corpus_derivations/audit_wide.cpp"),
        ):
            if not binary.is_file():
                subprocess.run(
                    ["c++", "-O3", "-std=c++17", "-Wall", "-Wextra", "-Werror", str(ROOT / source), "-o", str(binary)],
                    check=True,
                )

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def configured(self, budget=None):
        auditor = Auditor(self.tiled if budget is not None else self.full)
        if budget is not None:
            auditor.process = subprocess.Popen(
                [str(self.tiled), "--working-bytes", str(budget)], stdin=subprocess.PIPE, stdout=subprocess.PIPE
            )
        self.addCleanup(auditor.close)
        return auditor

    def compare(self, p, rows, *, scale=1, budgets=(64, 128, 255, 256, 1024)):
        vertices = list(compatible_vertices(p))
        reference = Lookup(vertices, scale, rows)
        full = self.configured()
        for budget in budgets:
            tiled = self.configured(budget)
            for first in range(0, p.vertices, 64):
                queries = tuple(range(first, min(first + 64, p.vertices)))
                before, _, original = full.call(p, vertices, scale, rows=rows, queries=queries)
                after, _, actual = tiled.call(p, vertices, scale, rows=rows, queries=queries)
                self.assertEqual(actual, original)
                self.assertEqual(
                    (after["checked_vertices"], after["checked_edges"]), (p.vertices, p.L * (p.vertices // 2))
                )
                self.assertLessEqual(after["output_row_storage_bytes"], budget)
                self.assertEqual(after["output_row_storage_limit"], budget)
                full_bytes = p.vertices * p.G * 8
                self.assertEqual(after["working_layout"], "exact-tiles/1" if full_bytes > budget else "full-table/1")
                for index, x in enumerate(queries):
                    expected = evaluate_transport(p, reference, x)
                    observed = tuple(
                        Fraction(value, int(after["clearing_scale"]))
                        for value in actual[index * p.G : (index + 1) * p.G]
                    )
                    self.assertEqual(expected, observed)
                if after["working_layout"] == "exact-tiles/1":
                    width = after["output_row_storage_bytes"] // (16 * p.G)
                    low_axes = width.bit_length() - 1
                    evaluations = p.vertices + (p.L - low_axes) * (p.vertices // 2) + p.n + 1 + len(queries)
                    self.assertEqual(after["reconstruction_evaluations"], evaluations)
                else:
                    self.assertEqual(after["reconstruction_evaluations"], p.vertices)
                self.assertEqual(before["clearing_scale"], after["clearing_scale"])
            tiled.close()
        full.close()

    def test_every_tiny_weighted_disjoint_vertex_matches_full_and_fraction_reference(self):
        for a in range(1, 5):
            for b in range(1, 5):
                with self.subTest(a=a, b=b):
                    self.compare(geometry(2, (a, b, -1)), [(0,), (1,), (1,)], budgets=(16, 24, 32))

    def test_tiny_nesting_transport_matches_at_all_original_vertices(self):
        self.compare(geometry(2, (1, -1, 2)), [(0,), (1,), (0,)], budgets=(16, 24, 32))

    def test_all_mmi_edges_and_vertices_with_integral_and_large_rational_counts(self):
        p = geometry(3, (-1, -1, -1, 2, 2, 2, -1))
        vertices = list(compatible_vertices(p))
        for scale in (1, 2, (1 << 55) + 9):
            rows = [
                tuple(value * scale for value in (a * b * (1 - c), a * c * (1 - b), b * c * (1 - a), max(a, b, c)))
                for x in vertices
                for a, b, c in [tuple((x >> axis) & 1 for axis in range(3))]
            ]
            if scale != 1:
                rows[7] = (1, 0, 0, scale)
            with self.subTest(scale=scale):
                self.compare(p, rows, scale=scale)

    def test_actual_n5_fixture_queries_every_vertex_with_bounded_tiles(self):
        literal = parse_json((ROOT / "tests/fixtures/count_proof_n5.json").read_bytes())
        p = proof_geometry(literal)
        full = list(decode_rows(p, literal["function"]["rows"]))
        vertices = list(compatible_vertices(p))
        # The original fixture is integral; reject silent rounding if that changes.
        self.assertTrue(all(full[x][0] == 1 for x in vertices))
        rows = [tuple(full[x][1]) for x in vertices]
        self.compare(p, rows, budgets=(max(16 * p.G, 64), 256, 4096))

    def test_empty_output_and_zero_dimensional_cubes_remain_complete(self):
        for p in (geometry(1, (1,)), geometry(1, (0,))):
            self.compare(p, [() for _ in compatible_vertices(p)], budgets=(1,))

    def test_uint128_distance_violation_cannot_wrap_into_acceptance(self):
        p = geometry(3, (-1, -1, -1, 2, 2, 2, -1))
        vertices, scale = list(compatible_vertices(p)), (1 << 63) - 1
        rows = [(0, 0, 0, 0) for _ in vertices]
        for x, image in p.boundary:
            rows[vertices.index(x)] = tuple(value * scale for value in image)
        rows[7] = (scale, scale, scale, 1)
        for auditor in (self.configured(), self.configured(64)):
            with self.assertRaisesRegex(ValueError, "edge violation"):
                auditor.call(p, vertices, scale, rows=rows)
            auditor.close()

    def test_insufficient_budget_is_an_explicit_failure_not_partial_coverage(self):
        p = geometry(2, (2, 1, -1))
        auditor = self.configured(1)
        with self.assertRaisesRegex(ValueError, "cannot hold two exact rows"):
            auditor.call(p, list(compatible_vertices(p)), 1, rows=[(0,), (1,), (1,)])
        auditor.close()

    def test_invalid_trusted_budget_never_clamps_or_runs_a_partial_audit(self):
        for value in ("0", "-1", "01", "1.5", "999999999999999999999999999", str(31 * 1024**3)):
            with self.subTest(value=value):
                result = subprocess.run([str(self.tiled), "--working-bytes", value], input=b"", capture_output=True)
                self.assertNotEqual(result.returncode, 0)
                meta, seed, queries = struct.unpack("<IQI", result.stdout[:16])
                self.assertEqual((seed, queries), (0, 0))
                self.assertIs(parse_json(result.stdout[16 : 16 + meta])["ok"], False)


if __name__ == "__main__":
    unittest.main()
