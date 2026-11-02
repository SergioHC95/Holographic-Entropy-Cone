"""Exact finite-field controls for incremental support-rank elimination."""

import random
import unittest
from unittest.mock import patch

import numpy as np

from hec import rank as kernels
from hec.rank import RANK_PRIME, _insert_rank_row


def reference_insert(row, basis, flags, rank, target):
    """Straight Gaussian elimination with arbitrary-precision Python integers."""
    while any(row):
        pivot = next(index for index, value in enumerate(row) if value)
        if not flags[pivot]:
            inverse = pow(row[pivot], -1, RANK_PRIME)
            basis[pivot] = [(value * inverse) % RANK_PRIME for value in row]
            flags[pivot] = True
            return rank + 1, rank + 1 == target
        factor = row[pivot]
        row[:] = [(value - factor * value_at) % RANK_PRIME for value, value_at in zip(row, basis[pivot], strict=True)]
    return rank, False


class ModularRankTests(unittest.TestCase):
    def test_one_off_dense_candidates_keep_one_owned_row_matrix(self):
        for row in ((1, 2, 3, 4, 5, 6, 7), (1, 2, 0, 4, 0, 6, 0)):
            candidates = [row] * 70
            prepared = kernels._prepare_rank_candidates(candidates, 3, shared=False)
            arrays, maps, _inverse, indices, values, _counts, target, representatives, lengths = prepared
            np.testing.assert_array_equal(arrays, candidates)
            self.assertEqual(indices.size, 0)
            self.assertEqual(values.size, 0)
            for fixed in ((1, -1, 0, 0, 0, 0, 0), (1, -1, 2, -2, 3, -3, 1)):
                with self.subTest(row=row, fixed=fixed):
                    actual = kernels.support_rank_prepared(fixed, 3, *prepared)
                    expected = kernels.saturating_image_rank(
                        np.array(fixed, dtype=np.int64), arrays, maps, target, representatives, lengths
                    )
                    self.assertEqual((actual["rank"], actual["saturating_images"], actual["tested_images"]), expected)

    def test_rank_preparation_preserves_unsized_iterable_inputs(self):
        rows = [(1, 0, 1), (0, 1, 1)]
        expected = kernels.support_rank((1, 1, -1), rows, 2)
        actual = kernels.support_rank((1, 1, -1), iter(rows), 2)
        self.assertEqual(actual, expected)

    def test_one_off_sparse_candidates_still_have_complete_sparse_rows(self):
        candidates = [(1, 0, 0, 0, 0, 0, 0), (0, 0, 0, 0, 0, 0, 0)]
        prepared = kernels._prepare_rank_candidates(candidates, 3, shared=False)
        arrays, maps, _inverse, indices, values, counts, target, representatives, lengths = prepared
        self.assertEqual(indices.shape, (2, 1))
        np.testing.assert_array_equal(counts, [1, 0])
        fixed = np.array([1, -1, 2, -2, 3, -3, 1], dtype=np.int64)
        actual = kernels.support_rank_prepared(fixed, 3, *prepared)
        expected = kernels.saturating_image_rank(fixed, arrays, maps, target, representatives, lengths)
        self.assertEqual((actual["rank"], actual["saturating_images"], actual["tested_images"]), expected)
        np.testing.assert_array_equal(values, [[1], [0]])

    def test_sequence_count_drift_and_late_bad_rows_are_not_silently_accepted(self):
        class ChangedSequence:
            def __init__(self, count, rows):
                self.count, self.rows = count, rows

            def __len__(self):
                return self.count

            def __iter__(self):
                return iter(self.rows)

        for count, rows in ((2, [(1, 1, -1)]), (1, [(1, 1, -1)] * 2)):
            with self.subTest(count=count), self.assertRaisesRegex(ValueError, "candidate count changed"):
                kernels._prepare_rank_candidates(ChangedSequence(count, rows), 2, shared=False)
        with self.assertRaisesRegex(ValueError, "expected vector length"):
            kernels.support_rank((1, 1, -1), [(1, 0, 1), (0, 1, 1), (1, 2)], 2)

    def test_single_rank_query_does_not_pay_for_shared_orbit_preprocessing(self):
        with patch.object(kernels, "_orbit_representatives", side_effect=AssertionError("one-off orbit preprocessing")):
            result = kernels.support_rank((1, 1, -1), [(1, 0, 1), (0, 1, 1)], 2)
        self.assertEqual(result["rank"], 2)

    def test_orbit_representatives_cover_every_integer_image_in_first_occurrence_order(self):
        rng = np.random.default_rng(982451653)
        candidates = rng.integers(-2, 3, size=(70, 7)).tolist()
        candidates[0] = [0] * 7
        candidates[1] = [1] * 7
        candidates[2] = [-(1 << 42), 1 << 40, 0, 1, -1, 2, 3]
        prepared = kernels.prepare_rank_candidates(candidates, 3)
        arrays, _maps, inverse = prepared[:3]
        indices, counts = prepared[-2:]
        self.assertEqual(indices.shape[0], 64)
        self.assertFalse(indices.flags.writeable)
        for index, row in enumerate(arrays[:64]):
            first = {}
            for at, mapping in enumerate(inverse):
                first.setdefault(tuple(row[mapping]), at)
            self.assertEqual(indices[index, : counts[index]].tolist(), sorted(first.values()))

    def test_all_rank_kernels_match_full_orbits_including_unprepared_candidates(self):
        rng = np.random.default_rng(982451653)
        candidates = rng.integers(-2, 3, size=(70, 7)).tolist()
        p = kernels.prepare_rank_candidates(candidates, 3)
        arrays, maps, inverse, indices, values, counts, target, representatives, lengths = p
        fixed = np.array([1, -1, 0, 0, 0, 0, 0], dtype=np.int64)
        nonzero = np.flatnonzero(fixed)
        empty_indices = np.empty((0, len(maps)), dtype=np.int32)
        empty_counts = np.empty(0, dtype=np.int64)
        calls = (
            (kernels.saturating_image_rank, (fixed, arrays, maps, target)),
            (kernels.saturating_image_rank_sparse_fixed, (nonzero, fixed[nonzero], arrays, maps, inverse, target)),
            (kernels.saturating_image_rank_sparse_candidates, (fixed, indices, values, counts, maps, target)),
        )
        for function, args in calls:
            with self.subTest(kernel=function.py_func.__name__):
                actual = function(*args, representatives, lengths)
                full = function(*args, empty_indices, empty_counts)
                self.assertEqual(actual[0], full[0])
                self.assertLessEqual(actual[1], full[1])
                self.assertLessEqual(actual[2], full[2])
                self.assertEqual(actual[0], target)

    def test_unprepared_orbit_tail_is_still_exhaustive(self):
        rng = np.random.default_rng(982451653)
        candidates = [[0] * 7 for _ in range(64)] + rng.integers(-2, 3, size=(6, 7)).tolist()
        p = kernels.prepare_rank_candidates(candidates, 3)
        arrays, maps, inverse, indices, values, counts, target, representatives, lengths = p
        fixed = np.array([1, -1, 0, 0, 0, 0, 0], dtype=np.int64)
        nonzero = np.flatnonzero(fixed)
        empty_indices = np.empty((0, len(maps)), dtype=np.int32)
        empty_counts = np.empty(0, dtype=np.int64)
        calls = (
            (kernels.saturating_image_rank, (fixed, arrays, maps, target)),
            (kernels.saturating_image_rank_sparse_fixed, (nonzero, fixed[nonzero], arrays, maps, inverse, target)),
            (kernels.saturating_image_rank_sparse_candidates, (fixed, indices, values, counts, maps, target)),
        )
        for function, args in calls:
            with self.subTest(kernel=function.py_func.__name__):
                actual = function(*args, representatives, lengths)
                full = function(*args, empty_indices, empty_counts)
                self.assertEqual(actual[0], full[0])
                self.assertEqual(actual[0], target)
                self.assertGreater(actual[2], 64)

    def test_suffix_elimination_matches_bigint_reference_after_every_insertion(self):
        rng = random.Random(982451653)
        for width in (1, 2, 7, 31, 63):
            for target in sorted({max(1, width - 1), width}):
                basis = np.zeros((width, width), dtype=np.int64)
                flags = np.zeros(width, dtype=np.bool_)
                expected_basis = [[0] * width for _ in range(width)]
                expected_flags = [False] * width
                rank = expected_rank = 0
                inputs = [[0] * width, [RANK_PRIME - 1] * width]
                for _ in range(width * 3):
                    row = [rng.choice((0, 1, RANK_PRIME - 1, rng.randrange(RANK_PRIME))) for _ in range(width)]
                    inputs.extend((row, row.copy(), [(2 * value) % RANK_PRIME for value in row]))
                for values in inputs:
                    row, expected_row = np.array(values, dtype=np.int64), values.copy()
                    result = _insert_rank_row(row, basis, flags, rank, target, width)
                    expected = reference_insert(expected_row, expected_basis, expected_flags, expected_rank, target)
                    self.assertEqual(result, expected)
                    rank, expected_rank = result[0], expected[0]
                    np.testing.assert_array_equal(row, expected_row)
                    np.testing.assert_array_equal(basis, expected_basis)
                    np.testing.assert_array_equal(flags, expected_flags)
                    self.assertLessEqual(rank, width)

    def test_unit_pivots_and_late_pivots_preserve_cleared_columns(self):
        width = 8
        basis = np.zeros((width, width), dtype=np.int64)
        flags = np.zeros(width, dtype=np.bool_)
        rank = 0
        for pivot in reversed(range(width)):
            row = np.zeros(width, dtype=np.int64)
            row[pivot] = 1
            rank, done = _insert_rank_row(row, basis, flags, rank, width, width)
            self.assertEqual(done, rank == width)
        np.testing.assert_array_equal(basis, np.eye(width, dtype=np.int64))
        row = np.full(width, RANK_PRIME - 1, dtype=np.int64)
        self.assertEqual(_insert_rank_row(row, basis, flags, rank, width, width), (width, False))
        self.assertFalse(np.any(row))


if __name__ == "__main__":
    unittest.main()
