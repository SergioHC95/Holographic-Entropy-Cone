from __future__ import annotations

import unittest
from unittest.mock import patch

import numpy as np
from test_graph_constructive import CONTROL

from hec._graph_capacity import prune_capacity_memberships
from hec._graph_cut_domains import (
    close,
    five_core_cuts,
    five_join_tables,
    five_memberships,
    initial,
    make_dependencies,
    propagate_events,
    propagate_five,
    support_tables,
    verify_dependencies,
)
from hec._graph_epr import _build_epr_model, solve_epr_free
from hec._graph_pair import pair_cut_disjunctions
from hec.coordinates import subsets
from hec.graphs import check_graph


def dense_close(domains, rules):
    """Independent full-sweep schedule of the same exact necessary rules."""
    mapping, images = support_tables(5)
    image, preimage = five_join_tables()
    plan = rules.capacity
    while True:
        if not propagate_five(domains, rules.binary, mapping, images, rules.joins, image, preimage):
            return False
        inside, outside = five_memberships(domains)
        changed = prune_capacity_memberships(
            domains,
            plan.entropy,
            plan.degree_twice,
            plan.crossing_caps,
            inside,
            outside,
            five_core_cuts(),
            5,
            plan.zero_pairs,
        )
        if changed <= 0:
            return changed == 0


class EventPropagationTests(unittest.TestCase):
    def test_dependencies_cover_every_rule_position_once_and_are_immutable(self):
        binary = np.asarray([(1, 2, 1), (2, 3, 6), (3, 4, 16)], dtype=np.int64)
        joins = np.asarray([(1, 3, 5), (2, 4, 6)], dtype=np.int64)
        offsets, neighbors = make_dependencies(binary, joins)
        self.assertTrue(verify_dependencies(binary, joins, offsets, neighbors))
        self.assertFalse(offsets.flags.writeable)
        self.assertFalse(neighbors.flags.writeable)
        for side in range(64):
            expected = [k for k, row in enumerate(binary) if side in row[:2]]
            expected += [len(binary) + k for k, row in enumerate(joins) if side in row]
            self.assertEqual(list(neighbors[offsets[side] : offsets[side + 1]]), expected)
        for value in (-1, len(binary) + len(joins), int(neighbors[1])):
            broken = neighbors.copy()
            broken[0] = value
            self.assertFalse(verify_dependencies(binary, joins, offsets, broken))
        for position, value in ((0, 1), (64, len(neighbors) - 1), (2, -1)):
            broken = offsets.copy()
            broken[position] = value
            self.assertFalse(verify_dependencies(binary, joins, broken, neighbors))
        self.assertFalse(verify_dependencies(binary, joins, offsets[:-1], neighbors))
        self.assertFalse(verify_dependencies(binary, joins, offsets, neighbors[:-1]))

    def test_queue_matches_dense_relations_and_incremental_restrictions(self):
        rng = np.random.default_rng(202610180409)
        mapping, images = support_tables(5)
        image, preimage = five_join_tables()
        for _ in range(400):
            domains = rng.integers(1, 1 << 32, 64, dtype=np.int64)
            domains[0] = 1
            binary = np.asarray([(1, 2, int(rng.integers(256))), (2, 3, int(rng.integers(256)))])
            joins = np.asarray([(1, 3, 4), (2, 4, 5)], dtype=np.int64)
            offsets, neighbors = make_dependencies(binary, joins)
            dense, event = domains.copy(), domains.copy()
            expected = propagate_five(dense, binary, mapping, images, joins, image, preimage)
            seeds = np.ones(64, dtype=np.uint8)
            metrics = np.zeros(3, dtype=np.int64)
            self.assertEqual(
                propagate_events(
                    event, binary, mapping, images, joins, image, preimage, offsets, neighbors, seeds, True, metrics
                ),
                expected,
            )
            self.assertGreater(metrics[2], 0)
            if not expected:
                continue
            np.testing.assert_array_equal(event, dense)
            side = int(rng.integers(1, 6))
            choices = [u for u in range(32) if dense[side] >> u & 1]
            dense[side] = 1 << int(rng.choice(choices))
            event = dense.copy()
            seeds[:] = 0
            seeds[side] = 1
            expected = propagate_five(dense, binary, mapping, images, joins, image, preimage)
            self.assertEqual(
                propagate_events(
                    event, binary, mapping, images, joins, image, preimage, offsets, neighbors, seeds, False, metrics
                ),
                expected,
            )
            if expected:
                np.testing.assert_array_equal(event, dense)

    def test_complete_and_seeded_capacity_fixed_points_match_dense_schedule(self):
        rng = np.random.default_rng(202610180410)
        targets = (CONTROL, tuple(min(len(s), 7 - len(s)) for s in subsets(6)))
        for target in targets:
            source = pair_cut_disjunctions(_build_epr_model(target, 5))
            base, rules = initial(source)
            self.assertTrue(close(base, rules))
            for turn in range(300):
                trial = base.copy()
                for side in rng.choice(np.arange(1, 64), 1 + turn % 5, replace=False):
                    choices = list(range(32)) if turn % 11 == 0 else [u for u in range(32) if base[side] >> u & 1]
                    trial[side] = 1 << int(rng.choice(choices))
                dense = trial.copy()
                expected = dense_close(dense, rules)
                for previous in (None, base):
                    actual = trial.copy()
                    self.assertEqual(close(actual, rules, previous), expected)
                    if expected:
                        np.testing.assert_array_equal(actual, dense)

    def test_root_expansion_retains_a_complete_scan_and_malformed_inputs_raise(self):
        source = pair_cut_disjunctions(_build_epr_model(CONTROL, 5))
        base, rules = initial(source)
        self.assertTrue(close(base, rules))
        expanded = base.copy()
        expanded[1] = 2  # Root templates can replace a previously excluded choice.
        expected = expanded.copy()
        success = dense_close(expected, rules)
        metrics = np.zeros(3, dtype=np.int64)
        self.assertEqual(close(expanded, rules, base, metrics), success)
        self.assertGreater(metrics[0], 0)
        for value in (-1, 1 << 32):
            malformed = base.copy()
            malformed[7] = value
            with self.assertRaises(ValueError):
                close(malformed, rules)
        for malformed in (base[:-1], base.astype(np.uint64)):
            with self.assertRaises(ValueError):
                close(malformed, rules)

    def test_bad_dependency_certificate_fails_closed_before_native_exclusion(self):
        source = pair_cut_disjunctions(_build_epr_model(CONTROL, 5))
        _, rules = initial(source)
        offsets, neighbors = rules.dependencies
        broken = neighbors.copy()
        broken[0] = -1
        with patch("hec._graph_cut_domains.dependency_arrays", return_value=(offsets, broken)):
            with self.assertRaisesRegex(RuntimeError, "dependency certificate"):
                initial(source)
            graph, info = solve_epr_free(CONTROL, total_vertices=12)
        self.assertIsNone(graph)
        self.assertEqual(info["status"], "unknown")
        self.assertIn("dependency certificate", info["error"])

    def test_actual_native_queue_executes_without_weakening_checks(self):
        graph, info = solve_epr_free(CONTROL, total_vertices=12)
        self.assertEqual(info["status"], "realized")
        self.assertTrue(check_graph(graph, CONTROL, 6, match="ray")["ok"])
        attempt = info["attempts"][0]
        branch = attempt["branching"]
        self.assertEqual(branch["propagation_engine"], "verified_dependency_queue_from_closed_parent")
        self.assertTrue(branch["dependency_certificate_verified"])
        self.assertGreater(branch["event_full_propagations"], 0)
        self.assertGreater(branch["event_seeded_propagations"], 0)
        self.assertGreater(branch["event_rule_visits"], branch["event_seeded_propagations"])
        self.assertTrue(branch["covers_complete"])
        self.assertTrue(attempt["model_construction"]["all_original_constraints_retained"])
        self.assertFalse(attempt["model_construction"]["native_state_reused"])
        self.assertIsNone(attempt["effective_time_limit_s"])
        self.assertEqual(attempt["resource_limits"]["limits/nodes"], -1)


if __name__ == "__main__":
    unittest.main()
