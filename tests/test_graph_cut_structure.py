from __future__ import annotations

import json
import random
import unittest
from fractions import Fraction
from itertools import combinations, product
from pathlib import Path
from unittest.mock import patch

import numpy as np

from hec._graph_milp import (
    _ahc_structure,
    _edge_bounds_exact,
    _exact_ahc_preprocessing,
    _solve_ahc_fixed_vertices,
)


class ExactCutStructureTests(unittest.TestCase):
    def test_every_three_bulk_domain_has_an_exact_logarithmic_selector(self) -> None:
        # If a simplex mixture has integral membership coordinates, every
        # positive coefficient must have the same bit in every coordinate.
        # Distinct cut masks then leave at most one positive coefficient.
        for domain_code in range(1, 1 << 8):
            masks = [mask for mask in range(8) if domain_code & (1 << mask)]
            bits = [bit for bit in range(3) if len({(mask >> bit) & 1 for mask in masks}) == 2]
            decoded = []
            for assignment in product((0, 1), repeat=len(bits)):
                possible = [
                    mask
                    for mask in masks
                    if all((mask >> bit) & 1 == value for bit, value in zip(bits, assignment, strict=True))
                ]
                self.assertLessEqual(len(possible), 1)
                decoded.extend(possible)
            self.assertEqual(sorted(decoded), masks)

    def test_integer_cut_bounds_equal_fraction_sums_even_for_huge_denominators(self) -> None:
        cases = [
            (Fraction(1, 10**80), Fraction(10**80, 3), Fraction(10**80, 3)),
            (Fraction(1, 2**1074), Fraction(1, 7), Fraction(1, 7)),
            (Fraction(0), Fraction(0), Fraction(0)),
        ]
        edges, _, _, crossings = _ahc_structure(2, 5)
        for target in cases:
            result = _exact_ahc_preprocessing(2, 5, target)
            lower, upper = _edge_bounds_exact(edges, result.scaled_target, 2, 5)
            expected = tuple(
                tuple(
                    (sum((lower[e] for e in cut), Fraction(0)), sum((upper[e] for e in cut), Fraction(0)))
                    for cut in cuts
                )
                for cuts in crossings
            )
            self.assertEqual(result.cut_bounds, expected)

    def test_actual_small_model_uses_membership_bits_and_unlimited_preset(self) -> None:
        fixture = json.loads((Path(__file__).parent / "fixtures" / "graph_quality_tie.json").read_text())
        captured = {}

        def capture(c, a_ineq, lo, hi, a_eq, rhs, integer, lb, ub, **kwargs):
            captured.update(integer=integer, a_eq=a_eq, rhs=rhs, kwargs=kwargs)
            return None, {"backend": "scip-indicator", "status": "unknown"}

        with (
            patch("hec._graph_milp._solve_scip_indicator_milp", side_effect=capture),
            patch("hec._graph_milp._solve_highspy_milp", return_value=(None, {"status": "unknown"})),
        ):
            _, info = _solve_ahc_fixed_vertices(np.asarray(fixture["target"]), 6, 10)
        profile = info["profile"]
        self.assertEqual(profile["cut_encoding"], "bulk_membership")
        self.assertEqual(captured["kwargs"]["emphasis"], "EASYCIP")
        self.assertIsNone(captured["kwargs"]["time_limit_s"])
        self.assertIsNone(captured["kwargs"]["node_limit"])
        edges = profile["edge_vars"]
        selectors = profile["continuous_cut_selectors"]
        integer = captured["integer"]
        self.assertGreater(selectors, profile["binary_vars"])
        self.assertTrue(np.all(integer[: edges + selectors] == 0))
        self.assertTrue(np.all(integer[edges + selectors :] == 1))
        # Every membership variable is linked to a subset of its continuous
        # cut selectors by an exact0/1 coefficient equality, with RHS zero.
        matrix = captured["a_eq"].tocsc()
        for column in np.flatnonzero(integer):
            rows = matrix.indices[matrix.indptr[column] : matrix.indptr[column + 1]]
            self.assertEqual(len(rows), 1)
            row = int(rows[0])
            self.assertEqual(captured["rhs"][row], 0.0)
            self.assertEqual(matrix[row, column], -1.0)

    def test_random_graph_minimal_cuts_obey_nesting_and_disjointness(self) -> None:
        n, bulk = 4, 3
        total = n + bulk + 1
        edges = list(combinations(range(total), 2))
        for seed in range(24):
            rng = random.Random(seed)
            weights = [rng.randrange(4) for _ in edges]
            minimal = {}
            for boundary in range(1, 1 << n):
                costs = []
                for mask in range(1 << bulk):
                    side = boundary | (mask << n)
                    costs.append(
                        sum(
                            weight
                            for (a, b), weight in zip(edges, weights, strict=True)
                            if bool(side & (1 << a)) != bool(side & (1 << b))
                        )
                    )
                minimizers = [mask for mask, cost in enumerate(costs) if cost == min(costs)]
                intersection = (1 << bulk) - 1
                for mask in minimizers:
                    intersection &= mask
                self.assertIn(intersection, minimizers)
                minimal[boundary] = intersection
            for left, right in combinations(minimal, 2):
                common = left & right
                if common == left:
                    self.assertEqual(minimal[left] & ~minimal[right], 0)
                elif common == right:
                    self.assertEqual(minimal[right] & ~minimal[left], 0)
                elif common == 0:
                    self.assertEqual(minimal[left] & minimal[right], 0)


if __name__ == "__main__":
    unittest.main()
