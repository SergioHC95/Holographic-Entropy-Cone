from __future__ import annotations

import unittest
from itertools import combinations
from math import gcd

import numpy as np
from numba import njit
from test_graph_epr_four_bulk import full_table

from hec._graph_capacity import (
    _BIT_INDEX,
    capacity_plan,
    close_terminal_upper,
    geometry,
    prune_capacity_memberships,
    single_bit_index,
    sparse_terminal_budgets,
    terminal_totals,
)
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
    def test_one_hot_decoder_covers_all_thirty_two_bits(self):
        self.assertEqual(_BIT_INDEX.shape, (32,))
        self.assertFalse(_BIT_INDEX.flags.writeable)
        for bit in range(32):
            self.assertEqual(single_bit_index(1 << bit), bit)

    def test_terminal_subset_sums_match_independent_dense_sums(self):
        rng = np.random.default_rng(202610180244)
        for bulk in (4, 5):
            size, full = 1 << bulk, (1 << bulk) - 1
            for _ in range(30):
                upper = rng.integers(0, 1 << 40, (7, size), dtype=np.int64)
                degree = rng.integers(0, 1 << 40, 7, dtype=np.int64)
                saved_upper, saved_degree = upper.copy(), degree.copy()
                lower, total_lower, total_upper = terminal_totals(upper, degree)
                for side in range(64):
                    for u in range(size):
                        crossings = [(u ^ full) if side >> t & 1 else u for t in range(7)]
                        self.assertEqual(
                            int(total_upper[side, u]), sum(int(upper[t, q]) for t, q in enumerate(crossings))
                        )
                        self.assertEqual(
                            int(total_lower[side, u]),
                            sum(max(0, int(degree[t]) - int(upper[t, q ^ full])) for t, q in enumerate(crossings)),
                        )
                np.testing.assert_array_equal(upper, saved_upper)
                np.testing.assert_array_equal(degree, saved_degree)

    def test_sparse_feedback_matches_dense_choice_enumeration(self):
        rng = np.random.default_rng(202610180245)
        for bulk in (4, 5):
            size, full = 1 << bulk, (1 << bulk) - 1
            domains = [1 << u for u in range(size)] + [(1 << size) - 1]
            domains += list(map(int, rng.integers(1, 1 << size, 300)))
            for domain in domains:
                side = int(rng.integers(1, 64))
                inside, outside = int(rng.integers(0, size)), int(rng.integers(0, size))
                h = int(rng.integers(0, 100))
                cuts = rng.integers(0, 100, size // 2, dtype=np.int64)
                total = rng.integers(0, 100, size, dtype=np.int64)
                terminal = rng.integers(0, 100, (7, size), dtype=np.int64)
                expected = np.full(7, -1, dtype=np.int64)
                for t in range(7):
                    q = outside if side >> t & 1 else inside
                    if not q:
                        continue
                    for u in range(size):
                        if domain >> u & 1:
                            crossing = (u ^ full) if side >> t & 1 else u
                            expected[t] = max(
                                expected[t],
                                2 * h - int(cuts[min(u, u ^ full)]) - int(total[u]) + int(terminal[t, crossing]),
                            )
                np.testing.assert_array_equal(
                    sparse_terminal_budgets(domain, side, inside, outside, h, cuts, total, terminal), expected
                )

    def test_invalid_width_or_bulk_scope_is_not_an_infeasibility_verdict(self):
        domains = np.ones(64, dtype=np.int64)
        h = np.ones(64, dtype=np.int64)
        degree = np.ones(7, dtype=np.int64)
        caps = np.ones((64, 7), dtype=np.int64)
        memberships = np.zeros(64, dtype=np.int64)
        cuts = np.zeros(16, dtype=np.int64)
        for bulk, value in ((4, 1 << 16), (5, 1 << 32), (5, -1), (6, 1)):
            invalid = domains.copy()
            invalid[1] = value
            with self.subTest(bulk=bulk, value=value), self.assertRaises(ValueError):
                prune_capacity_memberships(invalid, h, degree, caps, memberships, memberships, cuts, bulk)

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
