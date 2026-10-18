from __future__ import annotations

import unittest
from itertools import combinations
from math import gcd
from types import SimpleNamespace

import numpy as np
from test_graph_epr_four_bulk import full_table

from hec._graph_cut_domains import DomainCover, forced_cut_bundle
from hec._graph_epr import _epr_geometry, solve_epr_free


class CutBundleTests(unittest.TestCase):
    def test_bundles_are_exactly_the_sum_of_nonnegative_cut_slacks(self):
        rng = np.random.default_rng(202610172118)
        boundary, coefficients = _epr_geometry(5)
        side_index = np.zeros(64, dtype=np.int64)
        for i, s in enumerate(boundary):
            side_index[s] = i
        checked = 0
        for _turn in range(5000):
            weights = np.ones((7, 5), dtype=np.int64) if checked == 0 else rng.integers(1, 5, (7, 5))
            core = np.zeros(10, dtype=np.int64) if checked == 0 else rng.integers(0, 2, 10)
            if any(2 * np.sort(weights[:, k])[-2:].sum() > weights[:, k].sum() for k in range(5)):
                continue
            table = full_table(weights, core)
            raw_target = tuple(map(int, table.min(axis=1)))
            divisor = gcd(*raw_target)
            target = np.asarray(raw_target, dtype=np.int64) // divisor
            degrees = weights.sum(axis=1) // divisor
            self.assertTrue(np.all(weights.sum(axis=1) % divisor == 0))
            sums = [sum(int(degrees[t]) for t in range(6) if s >> t & 1) for s in boundary]
            bounds = np.asarray(
                [
                    [target[i] - (int(degrees.sum()) - sums[i] if u & 16 else sums[i]) for u in range(1, 31)]
                    for i in range(63)
                ],
                dtype=np.int64,
            )
            trial = np.ones(64, dtype=np.int64)
            previous = np.full(64, -1, dtype=np.int16)
            chosen = {}
            for s in range(1, 64):
                value = int(rng.integers(0, 32))
                trial[s] = 1 << value
                if rng.integers(0, 4) == 0:
                    previous[s] = value
                elif 0 < value < 31:
                    chosen[s] = value
            saved_parent, saved_trial = previous.copy(), trial.copy()
            fixed, row, rhs, count = forced_cut_bundle(trial, previous, side_index, coefficients, bounds, 31)
            self.assertTrue(np.array_equal(previous, saved_parent))
            self.assertTrue(np.array_equal(trial, saved_trial))
            self.assertEqual(count, len(chosen))
            point = np.r_[weights[:, :4].ravel(), core]
            slacks = [
                int(coefficients[side_index[s], u - 1] @ point) - int(bounds[side_index[s], u - 1]) * divisor
                for s, u in chosen.items()
            ]
            self.assertTrue(all(s >= 0 for s in slacks))
            combined = int(row @ point) - int(rhs) * divisor
            self.assertEqual(combined, sum(slacks))
            self.assertEqual(combined <= 0, all(s == 0 for s in slacks))
            for s in range(1, 64):
                self.assertEqual(fixed[s], int(trial[s]).bit_length() - 1)
            checked += 1
            if checked == 100:
                break
        self.assertEqual(checked, 100)

    def test_non_singleton_domains_and_already_fixed_cuts_add_no_rows(self):
        boundary, coefficients = _epr_geometry(5)
        index = np.zeros(64, dtype=np.int64)
        for i, s in enumerate(boundary):
            index[s] = i
        trial = np.full(64, (1 << 31) - 2, dtype=np.int64)
        trial[1] = 1 << 31
        trial[2] = 1
        trial[3] = 1 << 4
        previous = np.full(64, -1, dtype=np.int16)
        previous[3] = 4
        fixed, row, rhs, count = forced_cut_bundle(
            trial, previous, index, coefficients, np.zeros((63, 30), dtype=np.int64), 31
        )
        self.assertEqual(count, 0)
        self.assertFalse(row.any())
        self.assertEqual(rhs, 0)
        self.assertEqual(fixed[1], 31)
        self.assertEqual(fixed[2], 0)

    def test_large_aggregate_falls_back_before_native_float_conversion(self):
        boundary, coefficients = _epr_geometry(5)
        index = np.zeros(64, dtype=np.int64)
        for i, s in enumerate(boundary):
            index[s] = i
        calls = []
        previous = np.full(64, -1, dtype=np.int16)
        handler = SimpleNamespace(
            bulk_count=5,
            side_index=index,
            coefficients=coefficients,
            upper_cut_rhs=np.full((63, 30), 1 << 50, dtype=np.int64),
            full=31,
            upper_cut_numeric_fallbacks=0,
            enforce_individual_cuts=lambda *args: calls.append(args) or previous.copy(),
        )
        result = DomainCover.enforce_singles(handler, None, np.full(64, 2, dtype=np.int64), previous)
        self.assertEqual(len(calls), 1)
        self.assertEqual(handler.upper_cut_numeric_fallbacks, 1)
        self.assertTrue(np.array_equal(result, previous))

    def test_real_native_execution_retains_complete_checks_and_records_row_savings(self):
        columns = ((1, 1, 1, 1, 1, 0, 0), (0, 0, 1, 1, 1, 1, 1), (1, 0, 1, 0, 1, 1, 1), (0, 1, 0, 1, 1, 1, 1))
        target = tuple(
            sum(min(sum(column[t] for t in side), sum(column) - sum(column[t] for t in side)) for column in columns)
            for size in range(1, 7)
            for side in combinations(range(6), size)
        )
        graph, info = solve_epr_free(target, total_vertices=12)
        self.assertEqual(info["status"], "realized")
        self.assertIsNotNone(graph)
        attempt = info["attempts"][0]
        branch = attempt["branching"]
        self.assertEqual(branch["upper_cut_policy"], "exact_nonnegative_slack_aggregation")
        self.assertLessEqual(branch["upper_cut_rows"], branch["forced_upper_cuts"])
        self.assertEqual(branch["upper_cut_numeric_fallbacks"], 0)
        self.assertEqual(branch["child_selection_policy"], "minimum_local_cut_slack")
        self.assertEqual(branch["child_priority_nonfinite_fallbacks"], 0)
        self.assertEqual(
            branch["child_priority_calls"], branch["root_orbit_children"] + branch["domain_branch_children"]
        )
        self.assertEqual(branch["capacity_kernel_policy"], "subset_dp_and_sparse_set_bit_feedback")
        self.assertTrue(branch["covers_complete"])
        self.assertTrue(attempt["model_construction"]["all_original_constraints_retained"])
        self.assertFalse(attempt["model_construction"]["native_state_reused"])
        self.assertIsNone(attempt["effective_time_limit_s"])
        self.assertEqual(attempt["resource_limits"]["limits/nodes"], -1)


if __name__ == "__main__":
    unittest.main()
