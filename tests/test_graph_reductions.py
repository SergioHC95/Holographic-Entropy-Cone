from __future__ import annotations

import random
import unittest
from itertools import combinations

from hec._graph_reductions import EqualityCut, close_tight_submodularity


def _subsets(n: int) -> tuple[frozenset[int], ...]:
    return tuple(frozenset(subset) for size in range(1, n + 1) for subset in combinations(range(n), size))


def _cut_vertices(cut: EqualityCut, n: int, N: int) -> frozenset[int]:
    bulk_count = N - n - 1
    bulk = frozenset(n + offset for offset in range(bulk_count) if (cut.bulk_mask >> offset) & 1)
    return cut.boundary | bulk


def _cut_capacity(cut: EqualityCut, n: int, N: int, weights: dict[tuple[int, int], int]) -> int:
    inside = _cut_vertices(cut, n, N)
    return sum(weight for (u, v), weight in weights.items() if (u in inside) != (v in inside))


def _target_from_graph(
    n: int,
    N: int,
    weights: dict[tuple[int, int], int],
) -> tuple[list[int], dict[frozenset[int], list[int]]]:
    bulk_count = N - n - 1
    target: list[int] = []
    minimizing_masks: dict[frozenset[int], list[int]] = {}
    for boundary in _subsets(n):
        capacities = [_cut_capacity(EqualityCut(boundary, mask), n, N, weights) for mask in range(1 << bulk_count)]
        value = min(capacities)
        target.append(value)
        minimizing_masks[boundary] = [mask for mask, capacity in enumerate(capacities) if capacity == value]
    return target, minimizing_masks


class TightSubmodularityReductionTests(unittest.TestCase):
    def test_empty_intersection_retains_its_bulk_mask(self) -> None:
        result = close_tight_submodularity(
            n=2,
            N=4,
            target=[1, 2, 3],
            equality_cuts=[
                EqualityCut(frozenset({0}), 0b1),
                EqualityCut(frozenset({1}), 0b1),
            ],
        )

        self.assertIn(EqualityCut(frozenset(), 0b1), result.derived_cuts)
        self.assertIn(EqualityCut(frozenset({0, 1}), 0b1), result.derived_cuts)
        self.assertEqual(result.forced_zero_edges, frozenset({(0, 1)}))

    def test_opposite_regions_force_each_edge_individually(self) -> None:
        result = close_tight_submodularity(
            n=2,
            N=5,
            target=[1, 1, 2],
            equality_cuts=[
                EqualityCut(frozenset({0}), 0b01),
                EqualityCut(frozenset({1}), 0b10),
            ],
        )

        self.assertEqual(
            result.forced_zero_edges,
            frozenset({(0, 1), (0, 3), (1, 2), (2, 3)}),
        )
        self.assertIn(EqualityCut(frozenset(), 0b00), result.derived_cuts)
        self.assertIn(EqualityCut(frozenset({0, 1}), 0b11), result.derived_cuts)

    def test_only_exact_tightness_produces_deductions(self) -> None:
        cuts = [
            EqualityCut(frozenset({0}), 0b01),
            EqualityCut(frozenset({1}), 0b10),
        ]
        nontight = close_tight_submodularity(2, 5, [1, 1, 1], cuts)
        rounded = close_tight_submodularity(2, 5, [1e16, 1.0, 1e16], cuts)

        self.assertFalse(nontight.derived_cuts)
        self.assertFalse(nontight.forced_zero_edges)
        self.assertFalse(rounded.derived_cuts)
        self.assertFalse(rounded.forced_zero_edges)

    def test_random_graph_closures_are_sound_by_brute_force(self) -> None:
        n = 3
        N = 6
        derived_count = 0
        forced_count = 0

        for seed in range(24):
            rng = random.Random(seed)
            weights = {edge: rng.choice((0, 0, 0, 1, 2, 3)) for edge in combinations(range(N), 2)}
            target, minimizing_masks = _target_from_graph(n, N, weights)
            known = [EqualityCut(boundary, rng.choice(masks)) for boundary, masks in minimizing_masks.items()]

            result = close_tight_submodularity(n, N, target, known)
            derived_count += len(result.derived_cuts)
            forced_count += len(result.forced_zero_edges)
            target_by_boundary = dict(zip(_subsets(n), target, strict=True))
            target_by_boundary[frozenset()] = 0

            for cut in result.all_cuts:
                self.assertEqual(
                    _cut_capacity(cut, n, N, weights),
                    target_by_boundary[cut.boundary],
                    msg=f"seed={seed} cut={cut}",
                )
            for edge in result.forced_zero_edges:
                self.assertEqual(weights[edge], 0, msg=f"seed={seed} edge={edge}")

            for left, right in combinations(result.all_cuts, 2):
                intersection = EqualityCut(left.boundary & right.boundary, left.bulk_mask & right.bulk_mask)
                union = EqualityCut(left.boundary | right.boundary, left.bulk_mask | right.bulk_mask)
                left_only = _cut_vertices(left, n, N) - _cut_vertices(right, n, N)
                right_only = _cut_vertices(right, n, N) - _cut_vertices(left, n, N)
                opposite_weight = sum(weights[(min(u, v), max(u, v))] for u in left_only for v in right_only)
                self.assertEqual(
                    _cut_capacity(left, n, N, weights) + _cut_capacity(right, n, N, weights),
                    _cut_capacity(intersection, n, N, weights)
                    + _cut_capacity(union, n, N, weights)
                    + 2 * opposite_weight,
                )

        self.assertGreater(derived_count, 0)
        self.assertGreater(forced_count, 0)

    def test_input_validation_fails_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "positive integer"):
            close_tight_submodularity(0, 2, [1], [])
        with self.assertRaisesRegex(ValueError, "at least n \\+ 1"):
            close_tight_submodularity(2, 2, [1, 1, 2], [])
        with self.assertRaisesRegex(ValueError, "length"):
            close_tight_submodularity(2, 4, [1, 2], [])
        with self.assertRaisesRegex(ValueError, "nonnegative"):
            close_tight_submodularity(2, 4, [1, -1, 2], [])
        with self.assertRaisesRegex(ValueError, "finite"):
            close_tight_submodularity(2, 4, [1, float("inf"), 2], [])
        with self.assertRaisesRegex(TypeError, "real numbers"):
            close_tight_submodularity(2, 4, [1, "1", 2], [])  # type: ignore[list-item]
        with self.assertRaisesRegex(ValueError, "boundary"):
            close_tight_submodularity(2, 4, [1, 1, 2], [EqualityCut(frozenset({2}), 0)])
        with self.assertRaisesRegex(ValueError, "bulk mask"):
            close_tight_submodularity(2, 4, [1, 1, 2], [EqualityCut(frozenset({0}), 2)])
        with self.assertRaisesRegex(TypeError, "boundary indices"):
            EqualityCut(frozenset({True}), 0)
        with self.assertRaisesRegex(TypeError, "bulk mask"):
            EqualityCut(frozenset({0}), True)


if __name__ == "__main__":
    unittest.main()
