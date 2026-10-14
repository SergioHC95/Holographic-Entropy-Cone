"""Small mathematical controls; the actual corpus synthesis phase is not run."""

import copy
import random
import sys
import unittest
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from corpus_derivations.simplify import WorkLimit, smooth  # noqa: E402

from hec._count_verify import FullMapVerifier  # noqa: E402
from hec.count_proofs import compatible_vertices, geometry, make_count_proof  # noqa: E402


def source_mmi(p, scale):
    return [
        tuple(
            scale * cap * value
            for cap, value in zip(
                p.beta, (a * b * (1 - c), a * c * (1 - b), b * c * (1 - a), max(a, b, c)), strict=True
            )
        )
        for x in compatible_vertices(p)
        for a, b, c in [tuple((x >> i) & 1 for i in range(3))]
    ]


class ExactSimplificationTests(unittest.TestCase):
    def full_acceptance(self, p, scale, rows):
        proof = make_count_proof(p, [[Fraction(v, scale) for v in row] for row in rows], transport=True, integral=False)
        verifier = FullMapVerifier()  # Tiny arbitrary-precision fallback, no extra native worker.
        verifier.binary = None  # Also ignore a host-wide native-verifier environment override.
        try:
            result = verifier.verify(proof)
            self.assertEqual(result["checked_edges"], p.L * (p.vertices // 2))
        finally:
            verifier.close()

    def test_fractional_perturbation_synthesizes_a_simpler_integral_map(self):
        p = geometry(3, (-1, -1, -1, 2, 2, 2, -1))
        vertices, rows = list(compatible_vertices(p)), source_mmi(p, 17)
        rows[7] = (1, 0, 0, 17)
        preserved = copy.deepcopy(rows)
        scale, result, report = smooth(p, vertices, 17, rows)
        self.assertEqual(scale, 1)
        self.assertGreater(report["changed_cells"], 0)
        self.assertEqual(rows, preserved)
        self.full_acceptance(p, scale, result)

    def test_random_feasible_maps_remain_exact_after_all_component_moves(self):
        rng = random.Random(20261014)
        p = geometry(3, (-1, -1, -1, 4, 4, 4, -1))
        vertices = list(compatible_vertices(p))
        for _ in range(30):
            rows = [tuple(rng.randrange(2) for _ in p.beta) for _ in vertices]
            for x, image in p.boundary:
                rows[vertices.index(x)] = image
            scale, candidate, _ = smooth(p, vertices, 1, rows)
            self.full_acceptance(p, scale, candidate)

    def test_occurrence_components_are_fixed_and_repeat_is_deterministic(self):
        p = geometry(3, (-1, -1, -1, 1, 1, 1, -1))
        vertices, rows = list(compatible_vertices(p)), source_mmi(p, 1)
        first = smooth(p, vertices, 1, rows)
        self.assertEqual(first, smooth(p, vertices, 1, rows))
        for x, image in p.boundary:
            self.assertEqual(first[1][vertices.index(x)], image)
        self.full_acceptance(p, first[0], first[1])

    def test_budget_exhaustion_has_no_proof_receipt_and_preserves_input(self):
        p = geometry(3, (-1, -1, -1, 2, 2, 2, -1))
        rows = source_mmi(p, 1)
        unchanged = copy.deepcopy(rows)
        with self.assertRaises(WorkLimit):
            smooth(p, list(compatible_vertices(p)), 1, rows, max_work=1)
        self.assertEqual(rows, unchanged)

    def test_bad_edges_and_boundaries_fail_closed(self):
        p = geometry(3, (-1, -1, -1, 1, 1, 1, -1))
        vertices, rows = list(compatible_vertices(p)), source_mmi(p, 1)
        rows[7] = (1, 1, 1, 0)
        with self.assertRaisesRegex(ValueError, "edge violation"):
            smooth(p, vertices, 1, rows)
        rows = source_mmi(p, 1)
        rows[3] = (0, 0, 0, 0)
        with self.assertRaisesRegex(ValueError, "boundary"):
            smooth(p, vertices, 1, rows)

    def test_empty_rhs_and_a_fully_boundary_pinned_compatible_domain(self):
        for p, rows in ((geometry(1, (1,)), [(), ()]), (geometry(2, (2, 1, -1)), [(0,), (1,), (1,)])):
            vertices = list(compatible_vertices(p))
            scale, candidate, report = smooth(p, vertices, 1, rows)
            self.assertEqual((scale, candidate), (1, rows))
            self.assertEqual(report["changed_cells"], 0)
            self.full_acceptance(p, scale, candidate)

    def test_huge_exact_numerators_are_never_rounded_or_overflowed(self):
        p = geometry(3, (-25, -25, -25, 26, 26, 26, -25))
        vertices, denominator = list(compatible_vertices(p)), 1 << 59
        rows = source_mmi(p, denominator)
        rows[7] = (1, 0, 0, 25 * denominator)
        self.assertGreater(sum(p.beta) * denominator, (1 << 64) - 1)
        scale, candidate, _ = smooth(p, vertices, denominator, rows)
        self.assertEqual(scale, 1)
        self.full_acceptance(p, scale, candidate)

    def test_unsupported_geometry_fails_before_domain_enumeration(self):
        p = geometry(6, (1,) * 63)
        with self.assertRaisesRegex(ValueError, "capability"):
            smooth(p, [], 1, [])


if __name__ == "__main__":
    unittest.main()
