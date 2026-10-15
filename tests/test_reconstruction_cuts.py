"""Exact bulk cut evaluation, with the scalar evaluator retained as a control."""

import copy
import hashlib
import random
import unittest
from pathlib import Path
from unittest.mock import patch

from proof_fixtures import cut_seed, native_release

from hec._reconstruction_cuts import cut_integer_rows
from hec.count_proofs import compatible_vertices, geometry
from hec.reconstruction import ReconstructionProgram, make_pipeline
from hec.reconstruction_verify import IndependentCubeAuditor


def example(capacity=1):
    # Extra LHS slack keeps the high-capacity example primitive rather than
    # passing a forbidden common scaling as a new inequality identity.
    p = geometry(3, tuple(capacity * value + int(capacity > 1 and value > 0) for value in (-1, -1, -1, 2, 2, 2, -1)))
    vertices = list(compatible_vertices(p))
    rows = [
        tuple(capacity * value for value in (a * b * (1 - c), a * c * (1 - b), b * c * (1 - a), max(a, b, c)))
        for x in vertices
        for a, b, c in [tuple((x >> axis) & 1 for axis in range(3))]
    ]
    document = make_pipeline(p, cut_seed(p, vertices, rows))
    return p, vertices, rows, None, document


class BulkReconstructionCutTests(unittest.TestCase):
    def test_scalar_differential_including_padding_empty_and_repeated_layers(self):
        rng = random.Random(20261015)
        for axes in range(1, 8):
            terms = [(0, 0)]
            for _ in range(24):
                ones = rng.randrange(1 << axes)
                zeros = rng.randrange(1 << axes) & ~ones
                terms.append((ones, zeros))
            for count in sorted({1, 3, 7, min(17, 1 << axes), 1 << axes}):
                if count > 1 << axes:
                    continue
                vertices = sorted(rng.sample(range(1 << axes), count))
                groups = [[], [[]], [[0]], [[1, 2]] * 257]
                groups += [[sorted(rng.sample(range(len(terms)), rng.randrange(8))) for _ in range(6)]]
                expected = []
                for vertex in vertices:
                    truth = [vertex & one == one and not vertex & zero for one, zero in terms]
                    expected.append(tuple(sum(any(truth[ref] for ref in layer) for layer in group) for group in groups))
                self.assertEqual(cut_integer_rows(vertices, axes, terms, groups), tuple(expected))
                # No cached terms, or one at a time, must preserve every value.
                self.assertEqual(cut_integer_rows(vertices, axes, terms, groups, cache_bytes=1), tuple(expected))
                self.assertEqual(
                    cut_integer_rows(vertices, axes, terms, groups, cache_bytes=2 * ((count + 7) // 8) + 64),
                    tuple(expected),
                )

    def test_high_capacity_counts_semantics_and_entire_original_cube(self):
        p, vertices, rows, _, document = example(257)
        program = ReconstructionProgram(document)
        seed = program.materialize_seed()
        self.assertEqual(seed.vertices, tuple(vertices))
        self.assertEqual(seed.numerators, tuple(rows))
        self.assertEqual(seed.scale, 1)
        self.assertTrue(all(type(value) is int for row in seed.numerators for value in row))
        self.assertEqual(max(value for row in seed.numerators for value in row), 257)
        for vertex in vertices:
            self.assertEqual(program[vertex], rows[vertex])
        audit = program.audit_reference()
        self.assertEqual((audit["checked_vertices"], audit["checked_edges"]), (p.vertices, p.L * p.vertices // 2))
        self.assertFalse(audit["source_tables_read"])

    def test_bulk_materialization_does_not_execute_the_slow_scalar_query(self):
        _, _, rows, _, document = example()
        program = ReconstructionProgram(document)
        with patch.object(program._seed, "at", side_effect=AssertionError("scalar materialization was used")):
            self.assertEqual(program.materialize_seed().numerators, tuple(rows))
        # Normal scalar queries remain a distinct implementation, not a lookup
        # into the bulk materialization or a hidden original source table.
        self.assertEqual(program[3], rows[3])

    def test_bulk_results_still_receive_shape_type_bounds_and_boundary_checks(self):
        _, _, rows, _, document = example()
        bad_rows = [None, rows[:-1], rows + [rows[0]]]
        for value in (True, -1, 2):
            changed = copy.deepcopy(rows)
            changed[0] = (value, *changed[0][1:])
            bad_rows.append(changed)
        changed = copy.deepcopy(rows)
        changed[0] = changed[0][:-1]
        bad_rows.append(changed)
        changed = copy.deepcopy(rows)
        changed[0] = (1, 0, 0, 0)  # Bounded integers, but the prescribed image changed.
        bad_rows.append(changed)
        for bad in bad_rows:
            with patch("hec.reconstruction.cut_integer_rows", return_value=bad):
                with self.assertRaises(ValueError):
                    ReconstructionProgram(document).materialize_seed()

    def test_malformed_artifact_is_rejected_before_bulk_evaluation(self):
        _, _, _, _, document = example()
        for mutation in ("conflicting-literals", "duplicate-refs", "missing-layer"):
            bad = copy.deepcopy(document)
            seed = bad["function"]["seed"]
            if mutation == "conflicting-literals":
                seed["terms"][0] = ["1", "1"]
            elif mutation == "duplicate-refs":
                seed["groups"][0][0] = [0, 0]
            else:
                seed["groups"][0] = []
            with patch("hec.reconstruction.cut_integer_rows", side_effect=AssertionError("syntax bypassed")):
                with self.assertRaises(ValueError):
                    ReconstructionProgram(bad).materialize_seed()

    def test_independent_native_audit_of_actual_reconstructed_seed(self):
        binary = native_release()["cube"]
        _, _, _, _, document = example()
        sha = hashlib.sha256(Path(binary).read_bytes()).hexdigest()
        verifier = IndependentCubeAuditor(binary, sha)
        try:
            result = ReconstructionProgram(document).audit(verifier)
        finally:
            verifier.close()
        self.assertEqual((result["checked_vertices"], result["checked_edges"]), (8, 12))
        self.assertEqual(result["scope"], "original-cube-all-edges")
        self.assertFalse(result["source_tables_read"])


if __name__ == "__main__":
    unittest.main()
