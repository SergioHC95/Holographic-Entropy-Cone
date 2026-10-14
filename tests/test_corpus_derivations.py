"""Wide research paths: rational exactness, every-edge acceptance, fail-closed."""

import copy
import os
import random
import shutil
import subprocess
import sys
import tempfile
import unittest
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from corpus_derivations.diagrams import Diagram, build, common_seed, reconstruct  # noqa: E402
from corpus_derivations.native import Auditor  # noqa: E402

from hec._count_transport import evaluate_transport  # noqa: E402
from hec.count_proofs import compatible_vertices, geometry, make_count_proof  # noqa: E402


def mmi_seed(p, scale=1):
    rows = []
    for x in compatible_vertices(p):
        a, b, c = ((x >> i) & 1 for i in range(3))
        rows.append(
            tuple(
                scale * p.beta[g] * v
                for g, v in enumerate((a * b * (1 - c), a * c * (1 - b), b * c * (1 - a), max(a, b, c)))
            )
        )
    return rows


class DiagramTests(unittest.TestCase):
    def test_source_seed_reconstructed_with_rational_values(self):
        p = geometry(3, (-1, -1, -1, 2, 2, 2, -1))
        vertices = list(compatible_vertices(p))
        rows = mmi_seed(p, 17)
        rows[7] = (1, 0, 0, 17)
        recipe = build(p, vertices, 17, rows)
        self.assertEqual(reconstruct(recipe)[2:], (17, rows))
        self.assertEqual(Diagram(recipe)[7], (Fraction(1, 17), 0, 0, 1))
        proof = make_count_proof(p, [[Fraction(v, 17) for v in row] for row in rows], integral=False, transport=True)
        self.assertEqual(common_seed(proof), (p, vertices, 17, rows))

    def test_partial_compatible_branches_are_dont_cares_not_missing_rows(self):
        p = geometry(2, (2, 1, -1))
        vertices = list(compatible_vertices(p))
        rows = [(0,), (1,), (1,)]
        recipe = build(p, vertices, 1, rows)
        self.assertEqual(reconstruct(recipe)[3], rows)
        self.assertEqual([Diagram(recipe).numerators(x) for x in vertices], rows)
        with self.assertRaisesRegex(ValueError, "coverage"):
            build(p, vertices[:-1], 1, rows[:-1])

    def test_random_rows_round_trip_without_assuming_contraction(self):
        rng = random.Random(14)
        p = geometry(3, (-1, -1, -1, 4, 4, 4, -1))
        vertices = list(compatible_vertices(p))
        for _ in range(20):
            rows = [tuple(rng.randrange(2) for _ in p.beta) for _ in vertices]
            self.assertEqual(reconstruct(build(p, vertices, 1, rows))[3], rows)

    def test_empty_rhs_and_zero_source(self):
        for p in (geometry(1, (1,)), geometry(1, (0,))):
            vertices = list(compatible_vertices(p))
            rows = [() for _ in vertices]
            self.assertEqual(reconstruct(build(p, vertices, 1, rows))[3], rows)

    def test_duplicate_cycles_unreachable_nonminimal_bad_indices_rejected(self):
        p = geometry(3, (-1, -1, -1, 1, 1, 1, -1))
        recipe = build(p, list(compatible_vertices(p)), 1, mmi_seed(p))
        for kind in ("cycle", "bool", "unreachable", "duplicate", "equal", "scale", "claim", "dimension"):
            bad = copy.deepcopy(recipe)
            f = bad["function"]
            if kind == "cycle":
                f["nodes"][0][1] = len(f["terminals"]) + len(f["nodes"])
            elif kind == "bool":
                f["roots"][0] = True
            elif kind == "unreachable":
                f["terminals"].append("100")
            elif kind == "duplicate":
                f["nodes"].append(f["nodes"][0])
            elif kind == "equal":
                f["nodes"][0][2] = f["nodes"][0][1]
            elif kind == "scale":
                f["seed_scale"] = "0"
            elif kind == "claim":
                bad["verified"] = True
            else:
                bad["inequality"]["n"] = 10**9
            with self.assertRaises(ValueError, msg=kind):
                Diagram(bad)


@unittest.skipUnless(shutil.which("c++"), "wide auditor needs a C++17 compiler")
class WideAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="hec-wide-audit-tests-")
        cls.binary = Path(os.environ.get("HEC_WIDE_AUDITOR", str(Path(cls.temporary.name) / "audit_wide")))
        if not cls.binary.is_file():
            subprocess.run(
                [
                    "c++",
                    "-O3",
                    "-std=c++17",
                    "-Wall",
                    "-Wextra",
                    "-Werror",
                    str(ROOT / "tools/corpus_derivations/audit_wide.cpp"),
                    "-o",
                    str(cls.binary),
                ],
                check=True,
            )

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def test_all_vertices_against_python_transport(self):
        for a in range(1, 6):
            for b in range(1, 6):
                p = geometry(2, (a, b, -1))
                if __import__("math").gcd(a, b) != 1:
                    continue
                vertices, rows = list(compatible_vertices(p)), [(0,), (1,), (1,)]
                audit = Auditor(self.binary)
                try:
                    result, _, values = audit.call(p, vertices, 1, rows=rows, queries=range(p.vertices))
                    seed = dict(zip(vertices, rows, strict=True))
                    actual = [
                        tuple(Fraction(v, int(result["clearing_scale"])) for v in values[i : i + p.G])
                        for i in range(0, len(values), p.G)
                    ]
                    self.assertEqual(actual, [evaluate_transport(p, seed, x) for x in range(p.vertices)])
                    self.assertEqual(result["checked_edges"], 4)
                finally:
                    audit.close()

    def test_distance_accumulation_above_uint64_is_exact(self):
        p = geometry(3, (-25, -25, -25, 26, 26, 26, -25))
        vertices, scale = list(compatible_vertices(p)), 1 << 59
        rows = mmi_seed(p, scale)
        rows[7] = (1, 0, 0, 25 * scale)
        self.assertGreater(sum(p.beta) * scale, (1 << 64) - 1)
        auditor = Auditor(self.binary)
        try:
            result = auditor.verify(p, vertices, scale, rows)
            self.assertEqual(result["checked_edges"], 12)
            self.assertEqual(result["clearing_scale"], str(scale))
        finally:
            auditor.close()

    def test_invalid_full_seed_is_not_a_proof(self):
        p = geometry(3, (-1, -1, -1, 1, 1, 1, -1))
        vertices = list(compatible_vertices(p))
        rows = mmi_seed(p)
        rows[7] = (1, 1, 1, 0)
        auditor = Auditor(self.binary)
        try:
            with self.assertRaisesRegex(ValueError, "edge violation"):
                auditor.verify(p, vertices, 1, rows)
        finally:
            auditor.close()

    def test_original_boolean_audit_and_tamper_detection(self):
        p = geometry(3, (-1, -1, -1, 1, 1, 1, -1))
        vertices, rows = list(compatible_vertices(p)), mmi_seed(p)
        bits = sum(sum(v << g for g, v in enumerate(row)) << (x * 4) for x, row in enumerate(rows))
        raw = bits.to_bytes(4, "little")
        auditor = Auditor(self.binary)
        try:
            result, extracted, _ = auditor.call(p, vertices, 1, packed=raw)
            self.assertEqual(extracted, rows)
            self.assertEqual(result["scope"], "original-Boolean-cube-all-edges")
        finally:
            auditor.close()
        auditor = Auditor(self.binary)
        try:
            with self.assertRaisesRegex(ValueError, "occurrence"):
                auditor.call(p, vertices, 1, packed=bytes(4))
        finally:
            auditor.close()

    def test_overflow_fails_closed(self):
        p = geometry(3, (-1, -1, -1, 2, 2, 2, -1))
        auditor = Auditor(self.binary)
        try:
            with self.assertRaisesRegex(ValueError, "wider"):
                auditor.verify(p, list(compatible_vertices(p)), 1 << 64, mmi_seed(p, 1 << 64))
        finally:
            auditor.close()

    def test_original_boolean_rows_above_64_bits(self):
        p = geometry(2, (67, 68, -67))
        vertices = list(compatible_vertices(p))
        bits = sum(((1 << 67) - 1) << (67 * x) for x in (1, 2, 3))
        raw = bits.to_bytes((4 * 67 + 7) // 8, "little")
        auditor = Auditor(self.binary)
        try:
            result, rows, _ = auditor.call(p, vertices, 1, packed=raw)
            self.assertEqual(rows, [(0,), (67,), (67,)])
            self.assertEqual(result["checked_edges"], 4)
            self.assertEqual(auditor.verify(p, vertices, 1, rows)["checked_edges"], 4)
        finally:
            auditor.close()


class CorpusRunnerTests(unittest.TestCase):
    def test_explicit_fallback_has_exact_rational_scale_and_replays(self):
        from corpus_derivations.run import reconstruct as restore
        from corpus_derivations.run import standard

        p = geometry(3, (-1, -1, -1, 2, 2, 2, -1))
        vertices, rows = list(compatible_vertices(p)), mmi_seed(p, 17)
        rows[7] = (1, 0, 0, 17)
        proof = standard(p, 17, rows)
        self.assertEqual(restore(proof), (p, vertices, 17, rows))
        self.assertEqual(proof["clearing_scale"]["value"], "17")

    def test_saved_metadata_is_immutable(self):
        from corpus_derivations.run import save_new

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "binding.json"
            save_new(path, {"original": True})
            save_new(path, {"original": True})
            with self.assertRaisesRegex(ValueError, "immutable"):
                save_new(path, {"original": False})
            self.assertEqual(path.read_text(), '{"original":true}\n')

    def test_bad_clearing_metadata_is_not_silently_repaired(self):
        from corpus_derivations.run import reconstruct as restore
        from corpus_derivations.run import standard

        p = geometry(2, (2, 1, -1))
        proof = standard(p, 1, [(0,), (1,), (1,)])
        for kind in ("scale", "minimal", "claim"):
            bad = copy.deepcopy(proof)
            if kind == "scale":
                bad["clearing_scale"]["value"] = "1"
            elif kind == "minimal":
                bad["clearing_scale"]["minimal"] = True
            else:
                bad["function"]["verified"] = True
            with self.assertRaises(ValueError):
                restore(bad)


if __name__ == "__main__":
    unittest.main()
