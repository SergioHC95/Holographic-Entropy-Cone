from __future__ import annotations

import unittest
from types import SimpleNamespace

from hec._graph_cut_domains import OrbitCover


class ChildPriorityTests(unittest.TestCase):
    def handler(self, bulk_count=5):
        return SimpleNamespace(
            source=SimpleNamespace(bulk_count=bulk_count), child_priority_calls=0, child_priority_nonfinite_fallbacks=0
        )

    def test_finite_lp_cut_slacks_only_order_children(self):
        handler = self.handler()
        slacks = (0, -1, 2.5, -1e-12, 1e25)
        priorities = [OrbitCover.child_priority(handler, s) for s in slacks]
        self.assertEqual(priorities, [-float(s) for s in slacks])
        self.assertEqual(handler.child_priority_calls, len(slacks))
        self.assertEqual(handler.child_priority_nonfinite_fallbacks, 0)
        self.assertEqual(
            sorted(range(len(slacks)), key=lambda i: -priorities[i]), sorted(range(len(slacks)), key=slacks.__getitem__)
        )

    def test_nonfinite_guidance_falls_back_to_neutral_not_an_exclusion(self):
        handler = self.handler()
        for value in (float("nan"), float("inf"), -float("inf")):
            self.assertEqual(OrbitCover.child_priority(handler, value), 0.0)
        self.assertEqual(handler.child_priority_calls, 3)
        self.assertEqual(handler.child_priority_nonfinite_fallbacks, 3)

    def test_unbenchmarked_four_bulk_search_keeps_neutral_priorities(self):
        handler = self.handler(4)
        for value in (1, -2, float("nan")):
            self.assertEqual(OrbitCover.child_priority(handler, value), 0.0)
        self.assertEqual(handler.child_priority_calls, 0)
        self.assertEqual(handler.child_priority_nonfinite_fallbacks, 0)


if __name__ == "__main__":
    unittest.main()
