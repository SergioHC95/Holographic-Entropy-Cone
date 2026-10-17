from __future__ import annotations

import unittest
from fractions import Fraction
from itertools import combinations, permutations
from math import comb, gcd

import numpy as np
from test_graph_epr import exhaustive_table

from hec._graph_epr import _build_epr_model, _epr_geometry
from hec._graph_pair import _bulk_pair_orbits, _pair_penalties, _pair_score, pair_cut_disjunctions


class PairedCutTests(unittest.TestCase):
    def test_histograms_cover_every_bulk_mask_pair(self):
        for size in range(2, 7):
            full = (1 << size) - 1
            brute = {
                tuple(sorted(((a >> k) & 1) | (((b >> k) & 1) << 1) for k in range(size)))
                for a in range(1, full)
                for b in range(1, full)
            }
            observed = {
                tuple(sorted(((a >> k) & 1) | (((b >> k) & 1) << 1) for k in range(size)))
                for a, b in _bulk_pair_orbits(size)
            }
            self.assertEqual(observed, brute)
            self.assertEqual(len(observed), comb(size + 3, 3) - 4 * (size + 1) + 4)

    def test_minimal_cut_relations_preserve_all_compatible_orbits(self):
        for left, right, expected in [(7, 15, 3), (7, 56, 3), (7, 11, 8)]:
            representatives = {(a, b) for a, b, *_ in _pair_penalties(left, right, 0)}
            self.assertEqual(len(representatives), expected)
            for a in range(1, 7):
                for b in range(1, 7):
                    if left & right == left and a & ~b:
                        continue
                    if not left & right and a & b:
                        continue
                    images = {
                        (
                            sum(((a >> k) & 1) << p[k] for k in range(3)),
                            sum(((b >> k) & 1) << p[k] for k in range(3)),
                        )
                        for p in permutations(range(3))
                    }
                    self.assertTrue(representatives & images)

    def test_integer_scores_equal_explicit_zero_edge_counts(self):
        boundary, _ = _epr_geometry()
        candidates = [mask for mask in boundary if mask.bit_count() in (3, 4)]
        for left, right in combinations(candidates, 2):
            for saturation in (0, 6, 9, 15):
                rows = _pair_penalties(left, right, saturation)
                exact = 24 * (4 * Fraction(sum(row[-1] for row in rows), len(rows)) + 8 - len(rows))
                self.assertEqual(exact.denominator, 1)
                self.assertEqual(_pair_score(left, right, saturation), exact.numerator)

    def test_random_feasible_graphs_survive_orbits_and_zero_edge_penalties(self):
        rng = np.random.default_rng(20261020)
        observed = 0
        pairs = list(combinations(range(3), 2))
        for _ in range(4000):
            weights = rng.integers(1, 5, size=(7, 3))
            sums = weights.sum(axis=0)
            if any(2 * np.sort(weights[:, k])[-2:].sum() > sums[k] for k in range(3)):
                continue
            core = rng.integers(0, 3, size=3)
            table = exhaustive_table(weights, core)
            target = tuple(map(int, table.min(axis=1)))
            base = _build_epr_model(target)
            self.assertIsNotNone(base)
            model = pair_cut_disjunctions(base)
            if "paired_cut_subsystems" not in model.profile:
                continue
            left, right = model.profile["paired_cut_subsystems"]
            chosen = []
            for sub in (left, right):
                mask = 7
                for option in np.flatnonzero(table[sub] == target[sub]):
                    mask &= int(option)
                chosen.append(mask)
            signature = [((chosen[0] >> k) & 1) | (((chosen[1] >> k) & 1) << 1) for k in range(3)]
            order = np.argsort(signature, kind="stable")
            relabelled = weights[:, order]
            relabelled_core = [core[pairs.index(tuple(sorted((int(order[a]), int(order[b])))))] for a, b in pairs]
            point = np.concatenate([relabelled[:, :2].reshape(14), relabelled_core]) / gcd(*target)
            self.assertEqual(model.matrix.shape[0], base.matrix.shape[0] - 2)
            self.assertTrue(np.all(model.matrix @ point <= model.rhs + 1e-12))
            self.assertTrue(np.all(point >= 0) and np.all(point <= model.upper))
            for group in model.disjunctions:
                self.assertTrue(any(float(np.asarray(row) @ point) <= rhs + 1e-12 for row, rhs in group))
            self.assertEqual(model.profile["constraint_model_sha256"], model.sha256)
            observed += 1
            if observed == 200:
                break
        self.assertEqual(observed, 200)


if __name__ == "__main__":
    unittest.main()
