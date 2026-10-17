from __future__ import annotations

import math
import unittest
from fractions import Fraction
from itertools import combinations

import numpy as np

from hec._graph_epr import _build_epr_model, _epr_geometry, solve_epr_free
from hec._graph_pair import _pair_penalties, _pair_ranking_scale, _pair_score, pair_cut_disjunctions
from hec.coordinates import subsets
from hec.graphs import check_graph, find_graph_fixed_n, graph_total_vertices


def full_table(weights, core):
    count = weights.shape[1]
    pairs = tuple(combinations(range(count), 2))
    return np.asarray(
        [
            [
                sum(int(weights[t, k]) for t in range(7) for k in range(count) if (t in sub) != bool(bulk >> k & 1))
                + sum(int(core[j]) for j, (a, b) in enumerate(pairs) if bool(bulk >> a & 1) != bool(bulk >> b & 1))
                for bulk in range(1 << count)
            ]
            for sub in subsets(6)
        ]
    )


class FourBulkTests(unittest.TestCase):
    def test_every_affine_cut_matches_the_independent_sixteen_cut_table(self):
        rng = np.random.default_rng(202610174)
        boundary, rows = _epr_geometry(4)
        self.assertEqual(rows.shape, (63, 14, 27))
        for _ in range(50):
            weights, core = rng.integers(0, 8, (7, 4)), rng.integers(0, 8, 6)
            degrees = weights.sum(axis=1)
            point = np.r_[weights[:, :3].ravel(), core]
            table = full_table(weights, core)
            for i, side in enumerate(boundary):
                ds = sum(int(degrees[t]) for t in range(6) if side >> t & 1)
                for bulk in range(1, 15):
                    constant = int(degrees.sum()) - ds if bulk & 8 else ds
                    self.assertEqual(int(rows[i, bulk - 1] @ point) + constant, int(table[i, bulk]))

    def test_four_bulk_pair_scores_use_a_common_exact_scale(self):
        self.assertEqual(_pair_ranking_scale(4), 114)
        for left, right in [(7, 15), (7, 56), (7, 11)]:
            for saturation in (0, 6, 9, 15):
                penalties = _pair_penalties(left, right, saturation, 4)
                expected = 114 * (4 * Fraction(sum(p[-1] for p in penalties), len(penalties)) + 19 - len(penalties))
                self.assertEqual(expected.denominator, 1)
                self.assertEqual(_pair_score(left, right, saturation, 4), expected.numerator)

    def test_hundred_random_feasible_graphs_survive_every_model_reduction(self):
        rng = np.random.default_rng(202610175)
        pairs = tuple(combinations(range(4), 2))
        checked = 0
        for _ in range(5000):
            weights, core = rng.integers(1, 5, (7, 4)), rng.integers(0, 2, 6)
            sums = weights.sum(axis=0)
            if any(2 * np.sort(weights[:, k])[-2:].sum() > sums[k] for k in range(4)):
                continue
            table = full_table(weights, core)
            target = tuple(map(int, table.min(axis=1)))
            source = _build_epr_model(target, 4)
            self.assertIsNotNone(source)
            self.assertEqual(source.bulk_count, 4)
            self.assertEqual(source.profile["continuous_parameters"], 27)
            model = pair_cut_disjunctions(source)
            if "paired_cut_subsystems" not in model.profile:
                continue
            selected = model.profile["paired_cut_subsystems"]
            chosen = []
            for index in selected:
                bulk = 15
                for option in np.flatnonzero(table[index] == target[index]):
                    bulk &= int(option)
                chosen.append(bulk)
            signature = [((chosen[0] >> k) & 1) | (((chosen[1] >> k) & 1) << 1) for k in range(4)]
            order = np.argsort(signature, kind="stable")
            relabelled = weights[:, order]
            relabelled_core = [core[pairs.index(tuple(sorted((int(order[a]), int(order[b])))))] for a, b in pairs]
            point = np.r_[relabelled[:, :3].ravel(), relabelled_core] / math.gcd(*target)
            self.assertEqual(model.matrix.shape[0], source.matrix.shape[0] - 3)
            self.assertIn(model.profile["paired_orbit_representatives"], (6, 19))
            self.assertTrue(np.all(point >= 0) and np.all(point <= model.upper))
            self.assertTrue(np.all(model.matrix @ point <= model.rhs + 1e-10))
            for group in model.disjunctions:
                self.assertTrue(any(float(np.asarray(row) @ point) <= bound + 1e-10 for row, bound in group))
            checked += 1
            if checked == 100:
                break
        self.assertEqual(checked, 100)

    def test_exact_eleven_vertex_realization_has_unlimited_native_evidence(self):
        target = [min(len(sub), 7 - len(sub)) for sub in subsets(6)]
        result = find_graph_fixed_n(target, 11, match="exact", node_limit=None, time_limit_s=None)
        self.assertEqual(result["status"], "realized")
        self.assertEqual(graph_total_vertices(result["graph"], 6), 11)
        self.assertTrue(check_graph(result["graph"], target, 6, match="exact")["ok"])
        self.assertEqual(result["ahc"]["profile"]["continuous_parameters"], 27)
        self.assertEqual(result["ahc"]["profile"]["bulk_vertices"], 4)
        attempt = result["ahc"]["attempts"][0]
        self.assertIsNone(attempt["effective_time_limit_s"])
        self.assertGreaterEqual(attempt["resource_limits"]["limits/time"], 1e20)
        self.assertEqual(attempt["resource_limits"]["limits/nodes"], -1)

    def test_invalid_entropy_gets_only_a_completed_native_infeasibility(self):
        target = [min(len(sub), 7 - len(sub)) for sub in subsets(6)]
        target[next(i for i, sub in enumerate(subsets(6)) if set(sub) == {0, 1, 2, 3})] = 0
        graph, info = solve_epr_free(tuple(target), total_vertices=11)
        self.assertIsNone(graph)
        self.assertEqual(info["status"], "infeasible")
        self.assertTrue(info["attempts"][0]["trusted_infeasibility"])

    def test_other_sizes_do_not_silently_enter_the_specialization(self):
        target = tuple(min(len(sub), 7 - len(sub)) for sub in subsets(6))
        self.assertIsNone(solve_epr_free(target, total_vertices=9))
        self.assertIsNone(solve_epr_free(target, total_vertices=12))


if __name__ == "__main__":
    unittest.main()
