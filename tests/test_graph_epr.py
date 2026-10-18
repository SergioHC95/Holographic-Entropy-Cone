from __future__ import annotations

import unittest
from itertools import combinations
from unittest.mock import patch

import numpy as np

from hec._graph_epr import (
    EPR_BACKEND,
    _build_epr_model,
    _epr_geometry,
    _trusted_epr_infeasibility,
    solve_epr_free,
)
from hec._graph_search import solve_fixed_n
from hec.coordinates import subsets
from hec.graphs import find_graph_fixed_n


def exhaustive_table(terminal_weights, core):
    output = []
    for subset in subsets(6):
        selected = set(subset)
        costs = []
        for bulk in range(8):
            cost = sum(
                int(terminal_weights[t, k])
                for t in range(7)
                for k in range(3)
                if (t in selected) != bool(bulk & (1 << k))
            )
            cost += sum(
                int(core[j])
                for j, (a, b) in enumerate(combinations(range(3), 2))
                if bool(bulk & (1 << a)) != bool(bulk & (1 << b))
            )
            costs.append(cost)
        output.append(costs)
    return np.asarray(output)


class ReducedGraphTests(unittest.TestCase):
    def test_integer_geometry_matches_independent_exhaustive_cuts(self):
        rng = np.random.default_rng(20261017)
        boundary, coefficients = _epr_geometry()
        for _ in range(100):
            weights = rng.integers(0, 9, size=(7, 3))
            core = rng.integers(0, 9, size=3)
            degrees = weights.sum(axis=1)
            total = int(degrees.sum())
            point = np.concatenate([weights[:, :2].reshape(14), core])
            expected = exhaustive_table(weights, core)
            for sub, mask in enumerate(boundary):
                ds = sum(int(degrees[t]) for t in range(6) if mask & (1 << t))
                for bulk in range(1, 7):
                    constant = ds if not bulk & 4 else total - ds
                    self.assertEqual(int(coefficients[sub, bulk - 1] @ point) + constant, expected[sub, bulk])

    def test_reduced_model_keeps_two_hundred_known_feasible_graphs(self):
        rng = np.random.default_rng(20261018)
        checked = 0
        for _ in range(2000):
            weights = rng.integers(1, 5, size=(7, 3))
            sums = weights.sum(axis=0)
            if any(2 * np.sort(weights[:, k])[-2:].sum() > sums[k] for k in range(3)):
                continue
            weights = weights[:, np.argsort(-sums, kind="stable")]
            core = rng.integers(0, 5, size=3)
            table = exhaustive_table(weights, core)
            target = tuple(map(int, table.min(axis=1)))
            model = _build_epr_model(target)
            self.assertIsNotNone(model)
            divisor = __import__("math").gcd(*target)
            point = np.concatenate([weights[:, :2].reshape(14), core]) / divisor
            self.assertTrue(np.all(model.matrix @ point <= model.rhs + 1e-12))
            self.assertTrue(np.all(point >= 0))
            self.assertTrue(np.all(point <= model.upper))
            for choices in model.disjunctions:
                self.assertTrue(any(abs(float(np.asarray(row) @ point) - bound) < 1e-12 for row, bound in choices))
            checked += 1
            if checked == 200:
                break
        self.assertEqual(checked, 200)

    def test_applicability_and_exact_transport_guards(self):
        star = tuple(min(len(sub), 7 - len(sub)) for sub in subsets(6))
        model = _build_epr_model(star)
        self.assertIsNotNone(model)
        self.assertEqual(model.profile["continuous_parameters"], 17)
        self.assertEqual(model.profile["binary_vars"], 0)
        self.assertEqual(model.profile["cut_selectors"], 0)
        self.assertEqual(model.sha256, _build_epr_model(tuple(13 * v for v in star)).sha256)
        self.assertIsNone(_build_epr_model((0,) * 63))
        self.assertIsNone(_build_epr_model((-1,) * 63))
        bad = list(star)
        bad[0] += 1
        self.assertIsNone(_build_epr_model(tuple(bad)))
        large = list(star)
        large[0] += 1 << 50
        self.assertIsNone(_build_epr_model(tuple(large)))

    def test_native_realization_has_exact_output_and_scaled_match(self):
        star = [min(len(sub), 7 - len(sub)) for sub in subsets(6)]
        for factor in [1, 7]:
            result = find_graph_fixed_n([factor * v for v in star], 10, match="exact")
            self.assertEqual(result["status"], "realized")
            self.assertTrue(result["check"]["ok"])
            self.assertEqual(result["ahc"]["backend"], EPR_BACKEND)
            attempt = result["ahc"]["attempts"][-1]
            self.assertIsNone(attempt["effective_time_limit_s"])
            self.assertEqual(attempt["resource_limits"]["limits/nodes"], -1)
            self.assertGreaterEqual(attempt["resource_limits"]["limits/time"], 1e20)

    def test_all_native_stops_and_incomplete_negatives_fail_closed(self):
        good = {
            "backend": EPR_BACKEND,
            "status_raw": "infeasible",
            "stage": 10,
            "stage_solved_code": 10,
            "solutions": 0,
            "base_model_sha256": "a" * 64,
        }
        self.assertTrue(_trusted_epr_infeasibility(good, incumbent_returned=False))
        for field in good:
            bad = {k: v for k, v in good.items() if k != field}
            self.assertFalse(_trusted_epr_infeasibility(bad, incumbent_returned=False), field)
        for status in ["unknown", "timelimit", "nodelimit", "memlimit", "userinterrupt", "sollimit", "backend_error"]:
            self.assertFalse(_trusted_epr_infeasibility({**good, "status_raw": status}, incumbent_returned=False))
        self.assertFalse(_trusted_epr_infeasibility(good, incumbent_returned=True))

    def test_backend_error_and_bad_candidates_are_never_negative(self):
        target = tuple(min(len(sub), 7 - len(sub)) for sub in subsets(6))
        with patch("hec._graph_epr._solve_epr_native", side_effect=RuntimeError("backend failed")):
            graph, info = solve_epr_free(target)
        self.assertIsNone(graph)
        self.assertEqual(info["status"], "unknown")

    def test_explicit_limits_do_not_enter_unlimited_specialization(self):
        target = tuple(min(len(sub), 7 - len(sub)) for sub in subsets(6))
        with (
            patch("hec._graph_epr.solve_epr_free") as specialized,
            patch("hec._graph_search._solve_ahc_fixed_vertices", return_value=(None, {"status": "unknown"})),
        ):
            solve_fixed_n(target, 6, 10, node_limit=1)
        specialized.assert_not_called()

    def test_malformed_incumbent_is_unknown_not_infeasible(self):
        target = tuple(min(len(sub), 7 - len(sub)) for sub in subsets(6))
        with (
            patch("hec._graph_epr._solve_epr_native", return_value=(np.full(17, np.nan), {"status": "realized"})),
            patch("hec._graph_epr._solve_highspy_milp", return_value=(None, {"status": "unknown"})),
        ):
            graph, info = solve_epr_free(target)
        self.assertIsNone(graph)
        self.assertEqual(info["status"], "unknown")


if __name__ == "__main__":
    unittest.main()
