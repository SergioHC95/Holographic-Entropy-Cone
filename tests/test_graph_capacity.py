from __future__ import annotations

import unittest
from itertools import combinations
from math import gcd

import numpy as np
from numba import njit
from test_graph_epr_four_bulk import full_table

from hec._graph_capacity import capacity_plan, close_terminal_upper, geometry
from hec._graph_cut_domains import close, initial
from hec._graph_epr import _build_epr_model, _epr_geometry
from hec._graph_pair import pair_cut_disjunctions


@njit(cache=True)
def repeated_cover_closure(upper, degree):
    """Independent slow definition: alternate all supersets and all splits."""
    full = upper.shape[1] - 1
    for t in range(7):
        while True:
            changed = False
            for q in range(full, 0, -1):
                for r in range(1, full + 1):
                    if q & r == q and upper[t, r] < upper[t, q]:
                        upper[t, q] = upper[t, r]
                        changed = True
            for q in range(1, full + 1):
                a = (q - 1) & q
                while a:
                    value = upper[t, a] + upper[t, q ^ a]
                    if value < upper[t, q]:
                        upper[t, q] = value
                        changed = True
                    a = (a - 1) & q
            if upper[t, full] < degree[t]:
                return False
            if not changed:
                break
    return True


class CapacityBudgetTests(unittest.TestCase):
    def test_partition_dp_matches_repeated_exact_closure(self):
        rng = np.random.default_rng(202610180024)
        for bulk in (4, 5):
            for turn in range(1500):
                size = 1 << bulk
                upper = rng.integers(0, 1 << (40 if turn % 3 == 0 else 7), (7, size), dtype=np.int64)
                upper[:, 0] = 0
                # Include many complete, noncontradictory fixed points as well
                # as early contradictions and large exact integer bounds.
                degree = np.zeros(7, dtype=np.int64) if turn % 2 else rng.integers(0, 50, 7, dtype=np.int64)
                expected, actual = upper.copy(), upper.copy()
                possible = repeated_cover_closure(expected, degree)
                self.assertEqual(close_terminal_upper(actual, degree), possible)
                if possible:
                    np.testing.assert_array_equal(actual, expected)

    def test_all_memberships_and_complementary_core_cuts_are_exact(self):
        inside, outside, cuts = geometry()
        domains = np.arange(65536, dtype=np.int64)
        expected_inside = np.full(65536, 15, dtype=np.int64)
        expected_union = np.zeros(65536, dtype=np.int64)
        for value in range(16):
            present = (domains >> value) & 1
            expected_inside &= np.where(present, value, 15)
            expected_union |= present * value
        self.assertTrue(np.array_equal(inside, expected_inside))
        self.assertTrue(np.array_equal(outside, expected_union ^ 15))
        for array in (inside, outside, cuts):
            self.assertFalse(array.flags.writeable)
        for u in range(16):
            expected = sum(
                1 << e for e, (a, b) in enumerate(combinations(range(4), 2)) if ((u >> a) & 1) != ((u >> b) & 1)
            )
            self.assertEqual(cuts[min(u, u ^ 15)], expected)

    def test_capacity_plan_is_target_local_immutable_and_exact(self):
        target = tuple(min(int(s).bit_count(), 7 - int(s).bit_count()) for s in range(64))
        h = np.asarray(target, dtype=np.int64)
        plan = capacity_plan(h, (1,) * 7)
        for side in range(64):
            for terminal in range(7):
                flipped = side ^ (1 << terminal)
                flipped = flipped ^ 127 if flipped & 64 else flipped
                self.assertEqual(plan.crossing_caps[side, terminal], 1 + h[side] - h[flipped])
        h[1] = 99
        self.assertEqual(plan.entropy[1], 1)
        for array in (plan.entropy, plan.degree_twice, plan.crossing_caps):
            self.assertFalse(array.flags.writeable)
        self.assertEqual(len(plan.certificate_sha256), 64)
        with self.assertRaises(ValueError):
            capacity_plan(h, (1,) * 7)
        with self.assertRaises(ValueError):
            capacity_plan(np.full(64, np.iinfo(np.int64).max // 2), (1,) * 7)

    def test_cover_closure_preserves_rational_not_necessarily_half_integral_weights(self):
        rng = np.random.default_rng(202610170943)
        for turn in range(100):
            denominator = 3 if turn % 2 else 5
            numerators = rng.integers(0, 10, (7, 4))
            degree = np.zeros(7, dtype=np.int64)
            upper = np.zeros((7, 16), dtype=np.int64)
            for t in range(7):
                numerators[t, 3] += int(-numerators[t].sum()) % denominator
                degree[t] = 2 * int(numerators[t].sum()) // denominator
                for q in range(1, 16):
                    value = 2 * sum(int(numerators[t, k]) for k in range(4) if q >> k & 1)
                    upper[t, q] = (value + denominator - 1) // denominator + int(rng.integers(0, 4))
                upper[t, 15] = degree[t]
            self.assertTrue(close_terminal_upper(upper, degree))
            for t in range(7):
                for q in range(16):
                    actual = 2 * sum(int(numerators[t, k]) for k in range(4) if q >> k & 1)
                    self.assertGreaterEqual(int(upper[t, q]) * denominator, actual)

    def test_quarter_weight_graph_satisfies_slopes_and_complete_domain_feedback(self):
        weights = np.ones((7, 4), dtype=np.int64)
        table = full_table(weights, np.zeros(6, dtype=np.int64))
        target = tuple(map(int, table.min(axis=1)))
        divisor = gcd(*target)
        self.assertEqual(divisor, 4)
        source = pair_cut_disjunctions(_build_epr_model(target, 4))
        base, rules = initial(source)
        boundary, _ = _epr_geometry(4)
        truth = np.ones(64, dtype=np.int64)
        for i, side in enumerate(boundary):
            minimal = 15
            for u in np.flatnonzero(table[i] == target[i]):
                minimal &= int(u)
            truth[side] = 1 << minimal
            for t in range(7):
                crossing = sum(int(weights[t, k]) for k in range(4) if bool(side >> t & 1) != bool(minimal >> k & 1))
                self.assertLessEqual(2 * crossing, divisor * int(rules.capacity.crossing_caps[side, t]))
        self.assertTrue(close(base, rules))
        self.assertTrue(close(truth, rules))

    def test_degree_cover_contradictions_are_exact(self):
        degree = np.full(7, 8, dtype=np.int64)
        upper = np.full((7, 16), 8, dtype=np.int64)
        upper[:, 0] = 0
        upper[0, 3] = upper[0, 12] = 3
        self.assertFalse(close_terminal_upper(upper, degree))


if __name__ == "__main__":
    unittest.main()
