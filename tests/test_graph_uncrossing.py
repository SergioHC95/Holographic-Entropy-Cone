from __future__ import annotations

import unittest
from itertools import combinations
from unittest.mock import patch

import numpy as np
from numba import njit
from test_graph_constructive import CONTROL

from hec._graph_capacity import (
    capacity_plan,
    mandatory_zero_edges,
    tight_pair_regions,
    verify_tight_pairs,
)
from hec._graph_cut_domains import close, five_memberships, initial
from hec._graph_epr import _build_epr_model, solve_epr_free
from hec._graph_pair import pair_cut_disjunctions
from hec.coordinates import subsets


@njit(cache=True)
def cut_table(weights, core):
    count = weights.shape[1]
    result = np.zeros((64, 1 << count), dtype=np.int64)
    for side in range(64):
        for u in range(1 << count):
            value = 0
            for t in range(7):
                for k in range(count):
                    if bool(side >> t & 1) != bool(u >> k & 1):
                        value += weights[t, k]
            e = 0
            for a in range(count):
                for b in range(a + 1, count):
                    if bool(u >> a & 1) != bool(u >> b & 1):
                        value += core[e]
                    e += 1
            result[side, u] = value
    return result


class UncrossingTests(unittest.TestCase):
    def test_exact_certificates_cover_all_identities_and_reject_corruption(self):
        h = np.array([min(s.bit_count(), 7 - s.bit_count()) for s in range(64)], dtype=np.int64)
        pairs = tight_pair_regions(h)
        expected = []
        for a, b in combinations(range(1, 64), 2):
            if h[a] + h[b] == h[a & b] + h[a | b]:
                expected.append((a, b, 0, a & ~b, b & ~a))
            if h[a] + h[b] == h[a & ~b] + h[b & ~a]:
                expected.append((a, b, 1, a & b, 127 & ~(a | b)))
        np.testing.assert_array_equal(pairs, np.array(expected))
        self.assertTrue(verify_tight_pairs(h, pairs))
        for broken in (pairs[:-1], np.vstack([pairs, pairs[:1]]), pairs[:, :-1]):
            self.assertFalse(verify_tight_pairs(h, broken))
        for column, value in ((0, 0), (1, 64), (2, 2), (3, 128), (4, -1)):
            broken = pairs.copy()
            broken[0, column] = value
            self.assertFalse(verify_tight_pairs(h, broken))
        plan = capacity_plan(h, (1,) * 7)
        self.assertFalse(plan.zero_pairs.flags.writeable)
        np.testing.assert_array_equal(plan.zero_pairs, pairs)

    def test_both_cut_identities_for_every_pair_of_five_vertex_sides(self):
        # Integer numerators with common denominator 15 also verify genuinely
        # rational weights, without introducing any floating-point equality.
        weights = {edge: 2 * i + 1 for i, edge in enumerate(combinations(range(5), 2))}

        def capacity(side):
            return sum(w for (a, b), w in weights.items() if bool(side >> a & 1) != bool(side >> b & 1))

        for x in range(32):
            for y in range(32):
                exclusive = sum(
                    w
                    for (a, b), w in weights.items()
                    if ((x & ~y) >> a & 1 and (y & ~x) >> b & 1) or ((x & ~y) >> b & 1 and (y & ~x) >> a & 1)
                )
                common, outside = x & y, 31 & ~(x | y)
                opposite = sum(
                    w
                    for (a, b), w in weights.items()
                    if (common >> a & 1 and outside >> b & 1) or (common >> b & 1 and outside >> a & 1)
                )
                self.assertEqual(capacity(x) + capacity(y) - capacity(x & y) - capacity(x | y), 2 * exclusive)
                self.assertEqual(capacity(x) + capacity(y) - capacity(x & ~y) - capacity(y & ~x), 2 * opposite)

    def test_random_true_graph_domains_never_exclude_positive_rational_edges(self):
        rng = np.random.default_rng(202610180557)
        bulk_pairs = tuple(combinations(range(5), 2))
        checked_zero_edges = 0
        for turn in range(640):
            # This does not assume pairwise independence, edge integrality, or
            # unique minima. Dividing all weights by 3 or 5 changes no zeros.
            weights = rng.integers(0, 5, (7, 5), dtype=np.int64)
            core = rng.integers(0, 3, 10, dtype=np.int64)
            table = cut_table(weights, core)
            h = table.min(axis=1)
            pairs = tight_pair_regions(h)
            self.assertTrue(verify_tight_pairs(h, pairs))
            truth = np.ones(64, dtype=np.int64)
            for side in range(1, 64):
                choices = np.flatnonzero(table[side] == h[side])
                u = int(rng.choice(choices)) if turn % 2 else int(np.bitwise_and.reduce(choices))
                truth[side] = 1 << u
            for extra in (False, True):
                domains = truth | rng.integers(0, 1 << 32, 64, dtype=np.int64) if extra else truth
                inside, outside = five_memberships(domains)
                terminal, bulk = mandatory_zero_edges(inside, outside, pairs, 5)
                for t in range(7):
                    for k in range(5):
                        if terminal[t] >> k & 1:
                            self.assertEqual(weights[t, k], 0)
                            checked_zero_edges += 1
                for e, _ in enumerate(bulk_pairs):
                    if bulk >> e & 1:
                        self.assertEqual(core[e], 0)
                        checked_zero_edges += 1
        self.assertGreater(checked_zero_edges, 500)

    def test_feasible_pairwise_independent_graphs_survive_partial_and_singleton_closure(self):
        rng = np.random.default_rng(202610180558)
        boundary = np.array([sum(1 << t for t in s) for s in subsets(6)], dtype=np.int64)
        checked = 0
        for _ in range(1000):
            weights = rng.integers(1, 5, (7, 5), dtype=np.int64)
            if np.any(2 * np.sort(weights, axis=0)[-2:].sum(axis=0) > weights.sum(axis=0)):
                continue
            core = rng.integers(0, 3, 10, dtype=np.int64)
            table = cut_table(weights, core)
            h = table.min(axis=1)
            source = pair_cut_disjunctions(_build_epr_model(tuple(map(int, h[boundary])), 5))
            base, rules = initial(source)
            truth = np.ones(64, dtype=np.int64)
            for side in range(1, 64):
                truth[side] = 1 << int(np.bitwise_and.reduce(np.flatnonzero(table[side] == h[side])))
            self.assertTrue(close(base, rules))
            self.assertTrue(np.all(base & truth))
            partial = truth | (base & rng.integers(0, 1 << 32, 64, dtype=np.int64))
            self.assertTrue(close(partial, rules, base))
            self.assertTrue(np.all(partial & truth))
            self.assertTrue(close(truth, rules))
            checked += 1
            if checked == 100:
                break
        self.assertEqual(checked, 100)

    def test_invalid_pair_certificate_fails_closed_not_as_native_unsat(self):
        source = pair_cut_disjunctions(_build_epr_model(CONTROL, 5))
        _, rules = initial(source)
        broken = rules.capacity.zero_pairs.copy()
        broken[0, 3] = 128
        with patch("hec._graph_capacity.tight_pair_regions", return_value=broken):
            with self.assertRaisesRegex(RuntimeError, "zero-edge certificate"):
                initial(source)
            graph, info = solve_epr_free(CONTROL, total_vertices=12)
        self.assertIsNone(graph)
        self.assertEqual(info["status"], "unknown")
        self.assertIn("zero-edge certificate", info["error"])

    def test_native_records_the_verified_inference_and_preserves_full_checks(self):
        graph, info = solve_epr_free(CONTROL, total_vertices=12)
        self.assertIsNotNone(graph)
        attempt = info["attempts"][0]
        branch = attempt["branching"]
        self.assertEqual(branch["uncrossing_policy"], "all_tight_pair_mandatory_zero_edge_feedback")
        self.assertTrue(branch["uncrossing_certificate_verified"])
        self.assertGreater(branch["tight_uncrossing_pairs"], 0)
        self.assertTrue(branch["covers_complete"])
        self.assertTrue(attempt["model_construction"]["all_original_constraints_retained"])
        self.assertFalse(attempt["model_construction"]["native_state_reused"])
        self.assertEqual(attempt["resource_limits"]["limits/nodes"], -1)
        self.assertGreaterEqual(attempt["resource_limits"]["limits/time"], 1e20)


if __name__ == "__main__":
    unittest.main()
