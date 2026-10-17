from __future__ import annotations

import math
import unittest
from itertools import combinations, permutations

import numpy as np
from test_graph_epr_four_bulk import full_table

from hec._graph_cut_domains import (
    affine_geometry,
    close,
    five_core_cuts,
    five_join_tables,
    five_memberships,
    half_image,
    initial,
    propagate_five,
    stabilizer_representatives,
    support_tables,
)
from hec._graph_epr import _build_epr_model, _epr_geometry, solve_epr_free
from hec._graph_pair import _allowed_pair, _bulk_pair_orbits, pair_cut_disjunctions
from hec.coordinates import subsets
from hec.graphs import check_graph, find_graph_fixed_n, graph_total_vertices


class FiveBulkTests(unittest.TestCase):
    def test_all_affine_cuts_match_independent_thirty_two_cut_table(self):
        rng = np.random.default_rng(2026101712)
        boundary, rows = _epr_geometry(5)
        self.assertEqual(rows.shape, (63, 30, 38))
        for _ in range(30):
            weights, core = rng.integers(0, 8, (7, 5)), rng.integers(0, 8, 10)
            degrees = weights.sum(axis=1)
            point = np.r_[weights[:, :4].ravel(), core]
            truth = full_table(weights, core)
            for i, side in enumerate(boundary):
                ds = sum(int(degrees[t]) for t in range(6) if side >> t & 1)
                for u in range(1, 31):
                    constant = int(degrees.sum()) - ds if u & 16 else ds
                    self.assertEqual(int(rows[i, u - 1] @ point) + constant, int(truth[i, u]))

    def test_pair_histograms_cover_every_labelled_pair_and_relation(self):
        group = tuple(permutations(range(5)))
        for left, right in [(7, 11), (7, 15), (7, 56)]:
            covered = set()
            for a, b in _bulk_pair_orbits(5):
                if not _allowed_pair(left, right, a, b):
                    continue
                for p in group:
                    aa = sum(((a >> p[k]) & 1) << k for k in range(5))
                    bb = sum(((b >> p[k]) & 1) << k for k in range(5))
                    covered.add((aa, bb))
            expected = {(a, b) for a in range(1, 31) for b in range(1, 31) if _allowed_pair(left, right, a, b)}
            self.assertEqual(covered, expected)

    def test_every_split_support_entry_matches_independent_finite_relation(self):
        _, support = affine_geometry(5)
        mapping, images = support_tables(5)
        self.assertEqual(images.shape[1:], (2, 65536))
        self.assertLessEqual(images.nbytes, 64 * 1024**2)
        self.assertFalse(images.flags.writeable)
        masks = np.arange(65536, dtype=np.uint32)
        checked = set()
        for orientation in range(2):
            for flags in range(256):
                row = int(mapping[orientation, flags])
                if row in checked:
                    continue
                checked.add(row)
                for half in range(2):
                    expected = np.zeros(65536, dtype=np.uint32)
                    for bit in range(16):
                        expected |= np.where(masks >> bit & 1, support[orientation, flags, bit + 16 * half], 0).astype(
                            np.uint32
                        )
                    self.assertTrue(np.array_equal(expected, images[row, half]))
        self.assertEqual(len(checked), len(images))

    def test_split_join_images_and_preimages_are_exact_including_bit_31(self):
        image, preimage = five_join_tables()
        rng = np.random.default_rng(20261017121)
        for domain in [0, 1, 1 << 31, (1 << 32) - 1, *map(int, rng.integers(0, 1 << 32, 100))]:
            for a in range(32):
                expected_image = expected_preimage = 0
                for b in range(32):
                    if domain >> b & 1:
                        expected_image |= 1 << (a | b)
                    if domain >> (a | b) & 1:
                        expected_preimage |= 1 << b
                self.assertEqual(half_image(image, a, domain), expected_image)
                self.assertEqual(half_image(preimage, a, domain), expected_preimage)

    def test_combined_supports_match_slow_bruteforce_arc_consistency(self):
        rng = np.random.default_rng(20261017122)
        mapping, images = support_tables(5)
        image, preimage = five_join_tables()
        _, support = affine_geometry(5)
        for _ in range(100):
            domains = rng.integers(1, 1 << 32, 6, dtype=np.int64)
            binary = np.asarray([(1, 2, int(rng.integers(0, 256))), (2, 3, int(rng.integers(0, 256)))])
            joins = np.asarray([(1, 3, 4)], dtype=np.int64)
            slow = domains.copy()
            possible = True
            while True:
                previous = slow.copy()
                for a, b, flags in binary:
                    aa = sum(1 << u for u in range(32) if slow[a] >> u & 1 and support[0, flags, u] & slow[b])
                    bb = sum(1 << u for u in range(32) if slow[b] >> u & 1 and support[1, flags, u] & aa)
                    if not aa or not bb:
                        possible = False
                        break
                    slow[a], slow[b] = aa, bb
                if not possible:
                    break
                aa = bb = cc = 0
                for u in range(32):
                    for v in range(32):
                        if slow[1] >> u & 1 and slow[3] >> v & 1 and slow[4] >> (u | v) & 1:
                            aa |= 1 << u
                            bb |= 1 << v
                            cc |= 1 << (u | v)
                if not aa or not bb or not cc:
                    possible = False
                    break
                slow[1], slow[3], slow[4] = aa, bb, cc
                if np.array_equal(slow, previous):
                    break
            actual = domains.copy()
            self.assertEqual(propagate_five(actual, binary, mapping, images, joins, image, preimage), possible)
            if possible:
                self.assertTrue(np.array_equal(actual, slow))

    def test_mandatory_membership_and_complementary_core_geometry(self):
        rng = np.random.default_rng(20261017123)
        domains = np.r_[np.asarray([0, 1, 1 << 31, (1 << 32) - 1]), rng.integers(0, 1 << 32, 1000)]
        inside, outside = five_memberships(domains)
        for i, domain in enumerate(domains):
            common, union = 31, 0
            for u in range(32):
                if domain >> u & 1:
                    common &= u
                    union |= u
            self.assertEqual((int(inside[i]), int(outside[i])), (common, union ^ 31))
        edges = tuple(combinations(range(5), 2))
        cuts = five_core_cuts()
        for u in range(32):
            self.assertEqual(
                cuts[min(u, u ^ 31)], sum(1 << e for e, (a, b) in enumerate(edges) if (u >> a & 1) != (u >> b & 1))
            )

    def test_hundred_weighted_graphs_survive_all_exact_reductions(self):
        rng = np.random.default_rng(20261017124)
        boundary, _ = _epr_geometry(5)
        pairs = tuple(combinations(range(5), 2))
        checked = 0
        for _ in range(10000):
            weights, core = rng.integers(1, 5, (7, 5)), rng.integers(0, 2, 10)
            sums = weights.sum(axis=0)
            if any(2 * np.sort(weights[:, k])[-2:].sum() > sums[k] for k in range(5)):
                continue
            table = full_table(weights, core)
            target = tuple(map(int, table.min(axis=1)))
            source = _build_epr_model(target, 5)
            self.assertIsNotNone(source)
            model = pair_cut_disjunctions(source)
            if "paired_cut_subsystems" not in model.profile:
                continue
            chosen = []
            truth = np.ones(64, dtype=np.int64)
            for i, side in enumerate(boundary):
                value = 31
                for u in np.flatnonzero(table[i] == target[i]):
                    value &= int(u)
                truth[side] = 1 << value
                if i in model.profile["paired_cut_subsystems"]:
                    chosen.append((i, value))
            chosen = dict(chosen)
            a, b = (chosen[i] for i in model.profile["paired_cut_subsystems"])
            order = sorted(range(5), key=lambda k: ((a >> k & 1) | ((b >> k & 1) << 1), k))
            reordered_core = [core[pairs.index(tuple(sorted((order[a], order[b]))))] for a, b in pairs]
            point = np.r_[weights[:, order][:, :4].ravel(), reordered_core] / math.gcd(*target)
            self.assertTrue(np.all(point >= 0) and np.all(point <= model.upper))
            self.assertTrue(np.all(model.matrix @ point <= model.rhs + 1e-10))
            for choices in model.disjunctions:
                self.assertTrue(any(np.asarray(row) @ point <= bound + 1e-10 for row, bound in choices))
            base, rules = initial(model)
            self.assertTrue(close(base, rules))
            self.assertTrue(close(truth, rules))
            checked += 1
            if checked == 100:
                break
        self.assertEqual(checked, 100)

    def test_fifth_capacity_weights_need_not_be_half_integral(self):
        weights = np.ones((7, 5), dtype=np.int64)
        table = full_table(weights, np.zeros(10, dtype=np.int64))
        target = tuple(map(int, table.min(axis=1)))
        self.assertEqual(math.gcd(*target), 5)
        model = pair_cut_disjunctions(_build_epr_model(target, 5))
        base, rules = initial(model)
        self.assertTrue(close(base, rules))
        truth = np.ones(64, dtype=np.int64)
        boundary, _ = _epr_geometry(5)
        for i, side in enumerate(boundary):
            minimal = 31
            for u in np.flatnonzero(table[i] == target[i]):
                minimal &= int(u)
            truth[side] = 1 << minimal
        self.assertTrue(close(truth, rules))

    def test_stabilizer_masks_cover_exact_s5_orbits(self):
        rng = np.random.default_rng(20261017125)
        for _ in range(50):
            fixed = np.full(64, -1, dtype=np.int16)
            fixed[0] = 0
            for side in rng.choice(np.arange(1, 64), 3, replace=False):
                fixed[side] = rng.integers(0, 32)
            group = [
                p
                for p in permutations(range(5))
                if all(value < 0 or sum(((int(value) >> p[k]) & 1) << k for k in range(5)) == value for value in fixed)
            ]
            representatives = int(stabilizer_representatives(fixed, True, 5))
            self.assertEqual(stabilizer_representatives(fixed, False, 5), (1 << 31) - 2)
            expected = {max(sum(((u >> p[k]) & 1) << k for k in range(5)) for p in group) for u in range(1, 31)}
            self.assertEqual({u for u in range(1, 31) if representatives >> u & 1}, expected)

    def test_twelve_vertex_native_positive_and_completed_unsat_evidence(self):
        target = tuple(
            map(
                int,
                (
                    "1 1 1 1 1 1 2 2 2 2 2 2 2 2 2 2 2 2 2 2 2 "
                    "2 3 3 3 3 3 3 3 3 3 3 3 3 3 3 3 3 3 3 3 2 "
                    "3 3 4 4 3 4 4 3 3 4 4 4 4 4 3 3 3 3 3 3 2"
                ).split(),
            )
        )
        result = find_graph_fixed_n(target, 12, match="exact", node_limit=None, time_limit_s=None)
        self.assertEqual(result["status"], "realized")
        self.assertEqual(graph_total_vertices(result["graph"], 6), 12)
        self.assertTrue(check_graph(result["graph"], target, 6, match="exact")["ok"])
        self.assertEqual(result["ahc"]["profile"]["continuous_parameters"], 38)
        attempt = result["ahc"]["attempts"][0]
        self.assertEqual(attempt["model_construction"]["variables"], 38)
        self.assertEqual(attempt["model_construction"]["policy"], "fresh_batched_scip_constraints")
        self.assertEqual(attempt["branching"]["total_vertices"], 12)
        self.assertEqual(attempt["branching"]["binary_support_policy"], "immutable_split_support_images")
        self.assertTrue(attempt["branching"]["covers_complete"])
        self.assertGreaterEqual(attempt["resource_limits"]["limits/time"], 1e20)
        self.assertEqual(attempt["resource_limits"]["limits/nodes"], -1)
        bad = list(target)
        bad[next(i for i, sub in enumerate(subsets(6)) if set(sub) == {0, 1, 2, 3})] = 0
        graph, info = solve_epr_free(tuple(bad), total_vertices=12)
        self.assertIsNone(graph)
        self.assertEqual(info["status"], "infeasible")
        self.assertTrue(info["attempts"][0]["trusted_infeasibility"])
        self.assertTrue(info["attempts"][0]["branching"]["covers_complete"])


if __name__ == "__main__":
    unittest.main()
