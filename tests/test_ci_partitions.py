"""Cost balance is scheduling only; row ownership and actual checks stay exact."""

import hashlib
import json
import tempfile
import unittest
from fractions import Fraction
from pathlib import Path
from unittest.mock import patch

from hec import _ci_partitions as scheduling
from hec import checks


def estimated_cost(start, stop, segments):
    total, first = Fraction(), 0
    for last, cost in segments:
        overlap = max(0, min(last, stop) - max(first, start))
        total += Fraction(cost * overlap, last - first)
        first = last
    return total


class BalancedPartitionsTests(unittest.TestCase):
    def test_work_quantiles_balance_heterogeneous_contiguous_rows(self):
        segments = ((100, 100), (200, 900), (300, 200))
        bounds = scheduling.balanced_boundaries(300, 3, segments)
        self.assertEqual(bounds, (0, 133, 178, 300))
        costs = [estimated_cost(first, last, segments) for first, last in zip(bounds[:-1], bounds[1:], strict=True)]
        self.assertLessEqual(max(costs) - min(costs), 9)
        rows = [i for group in range(3) for i in checks._shard_indices(300, group, 3, "balanced", costs=segments)]
        self.assertEqual(rows, list(range(300)))

    def test_extreme_skew_keeps_nonempty_ranges_and_handles_more_groups_than_rows(self):
        for length in (1, 2, 7, 101):
            segments = ((1, 10**30),) if length == 1 else ((1, 10**30), (length, 1))
            for groups in (1, 2, 3, 16, 128):
                bounds = scheduling.balanced_boundaries(length, groups, segments)
                self.assertEqual((bounds[0], bounds[-1]), (0, length))
                self.assertEqual(sorted(bounds), list(bounds))
                self.assertEqual(sum(b - a for a, b in zip(bounds[:-1], bounds[1:], strict=True)), length)
                if groups <= length:
                    self.assertTrue(all(a < b for a, b in zip(bounds[:-1], bounds[1:], strict=True)))

    def test_costs_require_positive_complete_ordered_coverage(self):
        for segments in ((), ((9, 1),), ((10, 0),), ((10, True),), ((10, 1), (10, 2)), ((11, 1),)):
            with self.subTest(segments=segments), self.assertRaises(ValueError):
                scheduling.balanced_boundaries(10, 3, segments)
        for length, groups in ((True, 1), (10, True), (-1, 1), (10, 0)):
            with self.assertRaises(ValueError):
                scheduling.balanced_boundaries(length, groups, None)

    def test_timing_profile_is_bound_to_exact_ordered_ray_index_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "rays.json"
            profile_path = Path(directory) / "costs.json"
            path.write_text("[[1],[2],[3]]")
            profile_path.write_text(
                json.dumps(
                    {
                        "format": "hec-ci-ray-costs-v1",
                        "rows": 3,
                        "ray_catalog_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                        "segments": [[1, 90], [3, 10]],
                    }
                )
            )
            with patch.object(scheduling, "_PROFILE", profile_path):
                self.assertEqual(scheduling.ray_costs(path, 3), ((1, 90), (3, 10)))
                self.assertIsNone(scheduling.ray_costs(path, 4))
                path.write_text("[[2],[1],[3]]")
                self.assertIsNone(scheduling.ray_costs(path, 3))
                self.assertEqual(scheduling.balanced_boundaries(3, 2, None), (0, 1, 3))

    def test_committed_complete_run_costs_balance_128_jobs_within_row_rounding(self):
        profile = json.loads(scheduling._PROFILE.read_text())
        segments = tuple(tuple(row) for row in profile["segments"])
        bounds = scheduling.balanced_boundaries(profile["rows"], 128, segments)
        costs = [estimated_cost(first, last, segments) for first, last in zip(bounds[:-1], bounds[1:], strict=True)]
        previous, largest_row = 0, Fraction()
        for stop, cost in segments:
            largest_row = max(largest_row, Fraction(cost, stop - previous))
            previous = stop
        self.assertLessEqual(max(costs) - min(costs), 2 * largest_row)
        self.assertEqual(len(bounds), 129)
        self.assertTrue(all(a < b for a, b in zip(bounds[:-1], bounds[1:], strict=True)))


if __name__ == "__main__":
    unittest.main()
