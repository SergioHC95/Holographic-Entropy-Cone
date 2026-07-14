from __future__ import annotations

import unittest
from collections import Counter
from itertools import permutations, product

from hec._graph_symmetry import (
    RowAction,
    canonical_masks_from_histogram,
    extended_terminal_automorphisms,
    quotient_bulk_mask_orbits,
    row_action_group,
    setwise_stabilizer_actions,
    transform_subsystem_mask,
)


def _mask_tuple_histogram(masks: tuple[int, ...], bulk_count: int) -> tuple[int, ...]:
    histogram = [0] * (1 << len(masks))
    for bulk_offset in range(bulk_count):
        signature = sum(((mask >> bulk_offset) & 1) << row for row, mask in enumerate(masks))
        histogram[signature] += 1
    return tuple(histogram)


def _permute_bulk_bits(masks: tuple[int, ...], permutation: tuple[int, ...]) -> tuple[int, ...]:
    transformed = []
    for mask in masks:
        image = 0
        for source, destination in enumerate(permutation):
            if (mask >> source) & 1:
                image |= 1 << destination
        transformed.append(image)
    return tuple(transformed)


def _brute_orbit_key(
    masks: tuple[int, ...],
    bulk_count: int,
    actions: tuple[RowAction, ...],
) -> tuple[int, ...]:
    return min(
        action.transform_masks(_permute_bulk_bits(masks, permutation), bulk_count)
        for permutation in permutations(range(bulk_count))
        for action in actions
    )


class GraphSymmetryTests(unittest.TestCase):
    def test_bulk_histograms_are_complete_exact_orbit_invariants(self) -> None:
        for bulk_count in range(4):
            for row_count in range(4):
                with self.subTest(bulk_count=bulk_count, row_count=row_count):
                    brute = Counter(
                        _mask_tuple_histogram(masks, bulk_count)
                        for masks in product(range(1 << bulk_count), repeat=row_count)
                    )
                    for histogram in brute:
                        canonical = canonical_masks_from_histogram(histogram, row_count)
                        self.assertEqual(_mask_tuple_histogram(canonical, bulk_count), histogram)

    def test_zero_row_and_zero_bulk_cases_are_well_defined(self) -> None:
        self.assertEqual(canonical_masks_from_histogram((0,)), ())
        self.assertEqual(canonical_masks_from_histogram((3,)), ())

    def test_signed_row_quotient_matches_direct_group_action(self) -> None:
        actions = row_action_group(
            2,
            (
                RowAction((1, 0), (False, False)),
                RowAction((0, 1), (True, False)),
            ),
        )
        for bulk_count in range(4):
            with self.subTest(bulk_count=bulk_count):
                brute = Counter(
                    _brute_orbit_key(tuple(masks), bulk_count, actions)
                    for masks in product(range(1 << bulk_count), repeat=2)
                )
                generated = {
                    _brute_orbit_key(orbit.masks, bulk_count, actions): orbit.weight
                    for orbit in quotient_bulk_mask_orbits(bulk_count, 2, actions)
                }
                self.assertEqual(generated, dict(brute))
                self.assertEqual(sum(generated.values()), 1 << (2 * bulk_count))

    def test_exact_entropy_automorphisms_use_purifier_complementarity(self) -> None:
        self.assertEqual(extended_terminal_automorphisms([7]), ((0, 1), (1, 0)))
        self.assertEqual(extended_terminal_automorphisms([1, 2, 3]), ((0, 1, 2),))
        self.assertEqual(extended_terminal_automorphisms([1, 1, 2]), ((0, 1, 2), (1, 0, 2)))

        actions = setwise_stabilizer_actions((1,), extended_terminal_automorphisms([7]), party_count=1)
        complement = RowAction((0,), (True,))
        self.assertEqual(actions, (RowAction.identity(1), complement))
        self.assertEqual(complement.transform_masks((0b001,), 3), (0b110,))
        self.assertEqual(transform_subsystem_mask(1, (1, 0), party_count=1), (1, True))

    def test_selected_subsystem_stabilizer_induces_row_swap(self) -> None:
        identity = (0, 1, 2)
        swap_physical = (1, 0, 2)
        actions = setwise_stabilizer_actions((0b01, 0b10), (identity, swap_physical), party_count=2)
        self.assertEqual(
            actions,
            (
                RowAction.identity(2),
                RowAction((1, 0), (False, False)),
            ),
        )

    def test_invalid_actions_masks_and_histograms_fail_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "row complement flags"):
            RowAction((0,), (1,))  # type: ignore[arg-type]
        with self.assertRaisesRegex(ValueError, "not a row permutation"):
            RowAction((1,), (False,))
        with self.assertRaisesRegex(ValueError, "positive power of two"):
            canonical_masks_from_histogram((1, 2, 3))
        with self.assertRaisesRegex(ValueError, "bulk masks must be"):
            RowAction.identity(1).transform_masks((4,), bulk_count=2)
        with self.assertRaisesRegex(ValueError, "not a permutation"):
            transform_subsystem_mask(1, (0, 0), party_count=1)
        with self.assertRaisesRegex(ValueError, r"2\^n - 1"):
            extended_terminal_automorphisms([1, 2])


if __name__ == "__main__":
    unittest.main()
