from __future__ import annotations

import unittest
from unittest.mock import patch

import numpy as np

from hec._graph_cut_domains import common_singleton_domains
from hec._graph_epr import _epr_geometry, solve_epr_free
from hec.graphs import check_graph

CONTROL = (
    4,
    4,
    4,
    5,
    6,
    6,
    8,
    8,
    9,
    10,
    10,
    8,
    9,
    10,
    10,
    9,
    10,
    10,
    11,
    11,
    12,
    12,
    11,
    14,
    14,
    13,
    14,
    14,
    11,
    15,
    16,
    13,
    14,
    14,
    15,
    15,
    16,
    15,
    13,
    12,
    17,
    13,
    18,
    14,
    11,
    17,
    16,
    13,
    17,
    16,
    15,
    17,
    17,
    12,
    15,
    13,
    13,
    13,
    12,
    11,
    11,
    11,
    7,
)


class ConstructiveCutTests(unittest.TestCase):
    def test_lift_common_singletons_but_discard_other_canonical_restrictions(self):
        parent = np.full(64, (1 << 32) - 1, dtype=np.int64)
        parent[0] = 1
        children = np.tile(parent, (2, 1))
        children[:, 7] = 1 << 31
        children[0, 3], children[1, 3] = 1 << 4, 1 << 12
        children[0, 9], children[1, 9] = 3, 5
        refined, count, valid = common_singleton_domains(parent, children)
        self.assertTrue(valid)
        self.assertEqual(count, 1)
        self.assertEqual(refined[7], 1 << 31)
        self.assertEqual(refined[3], parent[3])  # No second, competing cut ordering.
        self.assertEqual(refined[9], parent[9])
        self.assertEqual(parent[7], (1 << 32) - 1)

    def test_random_lifts_preserve_every_child_and_are_idempotent(self):
        rng = np.random.default_rng(202610180155)
        for _ in range(1000):
            parent = rng.integers(1, 1 << 32, 64, dtype=np.int64)
            parent[0] = 1
            children = rng.integers(1, 1 << 32, (int(rng.integers(2, 7)), 64), dtype=np.int64) & parent
            for child in children:
                for side in np.flatnonzero(child == 0):
                    child[side] = int(parent[side]) & -int(parent[side])
            saved_parent, saved_children = parent.copy(), children.copy()
            refined, count, valid = common_singleton_domains(parent, children)
            self.assertTrue(valid)
            expected = parent.copy()
            for side in range(1, 64):
                values = {int(child[side]) for child in children}
                value = next(iter(values))
                if len(values) == 1 and value.bit_count() == 1:
                    expected[side] = value
            np.testing.assert_array_equal(refined, expected)
            self.assertEqual(count, int(np.count_nonzero(refined != parent)))
            self.assertFalse(np.any(children & ~refined))
            second, count, valid = common_singleton_domains(refined, children)
            self.assertTrue(valid)
            self.assertEqual(count, 0)
            np.testing.assert_array_equal(second, refined)
            np.testing.assert_array_equal(parent, saved_parent)
            np.testing.assert_array_equal(children, saved_children)

    def test_missing_empty_or_nonrestricting_children_fail_closed(self):
        parent = np.full(64, 3, dtype=np.int64)
        invalid = (
            np.empty((0, 64), dtype=np.int64),
            np.ones((2, 63), dtype=np.int64),
            np.zeros((2, 64), dtype=np.int64),
            np.full((2, 64), 4, dtype=np.int64),
        )
        for children in invalid:
            refined, count, valid = common_singleton_domains(parent, children)
            self.assertFalse(valid)
            self.assertEqual(count, 0)
            np.testing.assert_array_equal(refined, parent)

    def test_precast_search_matrix_matches_original_mixed_dtype_products(self):
        rng = np.random.default_rng(202610180156)
        for bulk in (4, 5):
            source = _epr_geometry(bulk)[1]
            matrix = source.reshape(-1, source.shape[-1])
            precast = np.ascontiguousarray(matrix, dtype=np.float64)
            for _ in range(100):
                point = rng.random(matrix.shape[1]) * 1e6
                np.testing.assert_array_equal(matrix @ point, precast @ point)

    def test_real_native_units_and_parent_lifts_preserve_complete_checks(self):
        graph, info = solve_epr_free(CONTROL, total_vertices=12)
        self.assertEqual(info["status"], "realized")
        self.assertTrue(check_graph(graph, CONTROL, 6, match="ray")["ok"])
        attempt = info["attempts"][0]
        branch = attempt["branching"]
        self.assertGreater(branch["domain_unit_continuations"], 0)
        self.assertGreater(branch["constructive_parent_lifts"], 0)
        self.assertTrue(branch["covers_complete"])
        self.assertEqual(
            branch["domain_branch_candidates"],
            branch["domain_branch_children"] + branch["domain_branch_pruned"] + branch["domain_unit_continuations"],
        )
        self.assertEqual(branch["symmetry_orbit_masks"], branch["domain_branch_candidates"])
        self.assertEqual(
            branch["child_priority_calls"], branch["root_orbit_children"] + branch["domain_branch_children"]
        )
        self.assertTrue(attempt["model_construction"]["all_original_constraints_retained"])
        self.assertFalse(attempt["model_construction"]["native_state_reused"])
        self.assertIsNone(attempt["effective_time_limit_s"])
        self.assertEqual(attempt["resource_limits"]["limits/nodes"], -1)

    def test_broken_constructive_invariant_cannot_be_recorded_as_unsat(self):
        with patch(
            "hec._graph_cut_domains.common_singleton_domains",
            side_effect=lambda parent, children: (parent.copy(), 0, False),
        ):
            graph, info = solve_epr_free(CONTROL, total_vertices=12)
        self.assertIsNone(graph)
        self.assertEqual(info["status"], "unknown")
        self.assertFalse(info["attempts"][0]["trusted_infeasibility"])
        self.assertFalse(info["attempts"][0]["branching"]["covers_complete"])


if __name__ == "__main__":
    unittest.main()
