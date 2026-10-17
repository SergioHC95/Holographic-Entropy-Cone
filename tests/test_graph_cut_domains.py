from __future__ import annotations

import unittest
from fractions import Fraction
from itertools import combinations, permutations, product
from math import gcd
from unittest.mock import patch

import numpy as np
from test_graph_epr_four_bulk import full_table

from hec._graph_cut_domains import (
    DomainCover,
    binary_geometry,
    close,
    initial,
    install_cut_domain_branching,
    local_zero_rows,
    stabilizer_representatives,
    tables,
)
from hec._graph_epr import _build_epr_model, _epr_geometry, _trusted_epr_infeasibility, solve_epr_free
from hec._graph_pair import _pair_penalties, pair_cut_disjunctions
from hec.coordinates import subsets
from hec.graphs import check_graph


class MinimumCutDomainTests(unittest.TestCase):
    def test_all_join_image_and_preimage_entries_match_direct_set_logic(self):
        image, preimage = tables()
        domains = np.arange(65536, dtype=np.uint32)
        for a in range(16):
            expected_image = np.zeros(65536, dtype=np.uint32)
            expected_preimage = np.zeros(65536, dtype=np.uint32)
            for b in range(16):
                expected_image |= ((domains >> b) & 1) << (a | b)
                expected_preimage |= ((domains >> (a | b)) & 1) << b
            self.assertTrue(np.array_equal(image[a], expected_image))
            self.assertTrue(np.array_equal(preimage[a], expected_preimage))
        self.assertFalse(image.flags.writeable)
        self.assertFalse(preimage.flags.writeable)

    def test_binary_supports_are_exact_and_immutable(self):
        relations, support = binary_geometry()
        self.assertFalse(relations.flags.writeable)
        self.assertFalse(support.flags.writeable)
        for a in range(16):
            self.assertEqual(support[0, a], sum(1 << b for b in range(16) if a & b == a))
            self.assertEqual(support[1, a], sum(1 << b for b in range(16) if a & b == b))
            self.assertEqual(support[2, a], sum(1 << b for b in range(16) if not a & b))

    def test_random_graph_minimal_cut_families_survive_domains_and_every_root_constraint(self):
        rng = np.random.default_rng(20261017553)
        boundary, _ = _epr_geometry(4)
        pairs = tuple(combinations(range(4), 2))
        checked = 0
        for turn in range(5000):
            weights = rng.integers(0 if turn % 3 == 0 else 1, 5, (7, 4))
            if turn % 7 == 0:
                weights[:, 3] = 0  # Tied/unused bulk vertices must not be lost.
            sums = weights.sum(axis=0)
            if any(2 * np.sort(weights[:, k])[-2:].sum() > sums[k] for k in range(4)):
                continue
            core = rng.integers(0, 3, 6)
            if turn % 7 == 0:
                for j, edge in enumerate(pairs):
                    if 3 in edge:
                        core[j] = 0
            table = full_table(weights, core)
            target = tuple(map(int, table.min(axis=1)))
            raw = _build_epr_model(target, 4)
            self.assertIsNotNone(raw)
            source = pair_cut_disjunctions(raw)
            if "paired_cut_subsystems" not in source.profile:
                continue
            minimal = np.zeros(64, dtype=np.int64)
            for i, side in enumerate(boundary):
                minimal[side] = 15
                for mask in np.flatnonzero(table[i] == target[i]):
                    minimal[side] &= int(mask)
            base, joins = initial(source)
            for a, b, u in joins:
                self.assertEqual(minimal[u], minimal[a] | minimal[b])
            self.assertTrue(close(base, joins))
            self.assertTrue(all(base[s] >> int(minimal[s]) & 1 for s in range(64)))
            left_sub, right_sub = source.profile["paired_cut_subsystems"]
            left, right = boundary[left_sub], boundary[right_sub]
            signatures = [((int(minimal[left]) >> k) & 1) | (((int(minimal[right]) >> k) & 1) << 1) for k in range(4)]
            order = sorted(range(4), key=lambda k: (signatures[k], k))
            transformed = np.asarray([sum(((int(mask) >> order[k]) & 1) << k for k in range(4)) for mask in minimal])
            a, b = int(transformed[left]), int(transformed[right])
            physical = dict(zip(boundary, raw.target, strict=True))
            physical[0] = 0

            def h(s, physical=physical):
                return physical[s ^ 127 if s & 64 else s]

            saturation = 9 if h(left) + h(right) == h(left & right) + h(left | right) else 0
            saturation |= 6 if h(left) + h(right) == h(left & ~right) + h(right & ~left) else 0
            templates = _pair_penalties(left, right, saturation, 4)
            chosen = next(entry for entry in templates if entry[:2] == (a, b))
            point_values = list(weights[:, order][:, :3].ravel()) + [
                core[pairs.index(tuple(sorted((order[i], order[j]))))] for i, j in pairs
            ]
            point = [Fraction(int(v), gcd(*target)) for v in point_values]
            for kind, index in local_zero_rows(chosen[2], chosen[3], 4):
                value = point[index] if kind == "bound" else raw.degrees[index] - sum(point[3 * index : 3 * index + 3])
                self.assertEqual(value, 0)
            trial = base.copy()
            trial[left], trial[right] = 1 << a, 1 << b
            self.assertTrue(close(trial, joins))
            self.assertTrue(all(trial[s] >> int(transformed[s]) & 1 for s in range(64)))
            for side in rng.permutation(np.arange(1, 64))[:12]:
                fixed = np.asarray(
                    [int(d).bit_length() - 1 if int(d) and not int(d) & (int(d) - 1) else -1 for d in trial],
                    dtype=np.int16,
                )
                previous = transformed.copy()
                allowed_permutations = [
                    p
                    for p in permutations(range(4))
                    if all(
                        fixed[s] < 0 or sum(((int(fixed[s]) >> p[k]) & 1) << k for k in range(4)) == fixed[s]
                        for s in range(1, 64)
                    )
                ]
                chosen = max(
                    allowed_permutations,
                    key=lambda p, side=side: sum(((int(previous[side]) >> p[k]) & 1) << k for k in range(4)),
                )
                transformed = np.asarray(
                    [sum(((int(mask) >> chosen[k]) & 1) << k for k in range(4)) for mask in previous]
                )
                self.assertTrue(all(fixed[s] < 0 or transformed[s] == fixed[s] for s in range(1, 64)))
                value = int(transformed[side])
                if 0 < value < 15:
                    self.assertTrue(stabilizer_representatives(fixed) >> value & 1)
                trial[side] = 1 << int(transformed[side])
                self.assertTrue(close(trial, joins))
                self.assertTrue(all(trial[s] >> int(transformed[s]) & 1 for s in range(64)))
            checked += 1
            if checked == 150:
                break
        self.assertEqual(checked, 150)

    def test_every_stabilizer_partition_and_invariant_proper_mask_domain(self):
        checked_partitions = checked_domains = 0
        for partition in product(range(4), repeat=4):
            if partition[0] != 0 or any(partition[k] > max(partition[:k]) + 1 for k in range(1, 4)):
                continue
            fixed = np.full(64, -1, dtype=np.int16)
            for bit in range(2):
                fixed[bit + 1] = sum(((partition[k] >> bit) & 1) << k for k in range(4))
            group = [p for p in permutations(range(4)) if all(partition[p[k]] == partition[k] for k in range(4))]
            unseen = set(range(1, 15))
            orbits = []
            while unseen:
                value = min(unseen)
                orbit = {sum(((value >> p[k]) & 1) << k for k in range(4)) for p in group}
                unseen.difference_update(orbit)
                orbits.append(orbit)
            representatives = int(stabilizer_representatives(fixed))
            self.assertEqual(stabilizer_representatives(fixed, False), 32766)
            for selected in range(1 << len(orbits)):
                domain = expected = 0
                for k, orbit in enumerate(orbits):
                    if selected >> k & 1:
                        domain |= sum(1 << value for value in orbit)
                        expected |= 1 << max(orbit)
                self.assertEqual(domain & representatives, expected)
                checked_domains += 1
            checked_partitions += 1
        self.assertEqual(checked_partitions, 15)
        self.assertEqual(checked_domains, 23176)

    def test_inconsistent_fixed_cut_domains_are_rejected(self):
        source = _build_epr_model(tuple(min(len(s), 7 - len(s)) for s in subsets(6)), 4)
        base, joins = initial(source)
        base[1], base[2] = 1 << 1, 1 << 1  # Disjoint terminals cannot share a minimal bulk side.
        self.assertFalse(close(base, joins))
        with self.assertRaises(ValueError):
            initial(_build_epr_model(source.target))

    def test_incomplete_branch_covers_cannot_authorize_unsat(self):
        good = {
            "backend": "scip-disjunction",
            "status_raw": "infeasible",
            "stage": 10,
            "stage_solved_code": 10,
            "solutions": 0,
            "base_model_sha256": "a" * 64,
        }
        for branching in [True, {}, {"covers_complete": False}, {"covers_complete": 1}]:
            self.assertFalse(_trusted_epr_infeasibility({**good, "branching": branching}, incumbent_returned=False))
        self.assertTrue(
            _trusted_epr_infeasibility({**good, "branching": {"covers_complete": True}}, incumbent_returned=False)
        )

    def control_targets(self):
        return {
            "realized": (
                "1 1 1 1 1 1 2 2 2 2 2 2 2 2 2 2 2 2 2 2 2 "
                "2 3 3 3 3 3 3 3 3 3 3 3 3 3 3 3 3 3 3 3 2 "
                "3 3 4 4 3 4 4 3 3 4 4 4 4 4 3 3 3 3 3 3 2"
            ),
            "infeasible": (
                "2 3 3 4 4 4 5 5 6 6 6 6 7 7 7 7 7 7 8 8 8 "
                "8 7 9 9 9 9 9 10 10 8 8 10 10 11 11 11 9 9 11 10 8 "
                "8 12 11 11 11 11 11 11 10 10 10 10 9 9 8 8 8 7 7 6 4"
            ),
        }

    def test_realized_or_unsat_controls_retain_native_acceptance(self):
        for expected, encoded in self.control_targets().items():
            with self.subTest(expected=expected):
                target = tuple(map(int, encoded.split()))
                self.assertEqual(len(target), 63)
                handlers = []

                def remember_handler(*args, handlers=handlers):
                    handler = install_cut_domain_branching(*args)
                    handlers.append(handler)
                    return handler

                with patch("hec._graph_cut_domains.install_cut_domain_branching", side_effect=remember_handler):
                    graph, info = solve_epr_free(target, total_vertices=11)
                self.assertEqual(len(handlers), 1)
                self.assertIsNone(handlers[0].model)  # Deterministic release, not cyclic-GC timing.
                self.assertEqual(info["status"], expected)
                attempt = info["attempts"][0]
                self.assertIsNone(attempt["effective_time_limit_s"])
                self.assertEqual(attempt["resource_limits"]["limits/nodes"], -1)
                branch = attempt["branching"]
                self.assertEqual(branch["kind"], "minimal_cut_domain_branching")
                self.assertTrue(branch["covers_complete"])
                self.assertGreater(branch["root_orbit_candidates"], 0)
                self.assertTrue(branch["automatic_symmetry_disabled"])
                self.assertTrue(branch["dual_reductions_disabled"])
                self.assertEqual(branch["symmetry_policy"], "dynamic_minimal_cut_stabilizer")
                self.assertTrue(branch["symmetry_consistent"])
                self.assertTrue(branch["capacity_ordering_disabled"])
                self.assertEqual(branch["residual_order_rows"], 0)
                self.assertEqual(
                    branch["symmetry_raw_masks"], branch["symmetry_orbit_masks"] + branch["symmetry_skipped_masks"]
                )
                self.assertEqual(branch["symmetry_orbit_masks"], branch["domain_branch_candidates"])
                if expected == "realized":
                    self.assertIsNotNone(graph)
                    # The internal finder returns primitive integer graph weights;
                    # the public exact-match adapter applies the entropy scale.
                    self.assertTrue(check_graph(graph, target, 6, match="ray")["ok"])
                else:
                    self.assertIsNone(graph)
                    self.assertTrue(attempt["trusted_infeasibility"])
                    self.assertEqual(attempt["solutions"], 0)

    def test_untracked_native_subtrees_disable_quotienting_without_losing_unsat(self):
        original = DomainCover.consenfolp

        def enforce(handler, *args):
            if handler.model.getDepth() > 0:
                handler.symmetry_nodes.discard(handler.model.getCurrentNode().getNumber())
            return original(handler, *args)

        target = tuple(map(int, self.control_targets()["infeasible"].split()))
        with patch.object(DomainCover, "consenfolp", enforce):
            graph, info = solve_epr_free(target, total_vertices=11)
        self.assertIsNone(graph)
        self.assertEqual(info["status"], "infeasible")
        branch = info["attempts"][0]["branching"]
        self.assertGreater(branch["symmetry_untracked_enforcements"], 0)
        self.assertEqual(branch["symmetry_skipped_masks"], 0)
        self.assertTrue(branch["covers_complete"])


if __name__ == "__main__":
    unittest.main()
