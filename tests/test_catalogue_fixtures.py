"""Selected controls stay exact without retaining an entire ray catalogue."""

import unittest

from catalogue_fixtures import ray_fingerprint, select_rays


class CatalogueFixtureTests(unittest.TestCase):
    def test_selection_is_bounded_and_stops_after_every_requested_identity(self):
        rows = [(1, 0, 1), (0, 1, 1)]

        def stream():
            yield from rows
            raise AssertionError("selection read an unneeded tail")

        wanted = [ray_fingerprint(row) for row in rows]
        self.assertEqual(
            select_rays(stream(), wanted),
            {identity: (i, row) for i, (identity, row) in enumerate(zip(wanted, rows, strict=True))},
        )

    def test_nonmatching_rows_are_not_retained_and_missing_controls_fail(self):
        wanted_row = (1000, 1001, 1002)
        identity = ray_fingerprint(wanted_row)
        result = select_rays(((i, i + 1, i + 2) for i in range(1001)), [identity])
        self.assertEqual(result, {identity: (1000, wanted_row)})
        with self.assertRaisesRegex(ValueError, "missing selected"):
            select_rays([], [identity])
        self.assertEqual(select_rays(iter(()), []), {})

    def test_unique_selection_checks_the_tail_and_rejects_duplicate_controls(self):
        row = (1, 0, 1)
        with self.assertRaisesRegex(ValueError, "duplicate selected"):
            select_rays(iter([row, row]), [ray_fingerprint(row)], unique=True)

    def test_fingerprint_rejects_nonfinite_numbers(self):
        with self.assertRaises(ValueError):
            ray_fingerprint([float("nan")])
