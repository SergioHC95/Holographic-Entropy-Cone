"""Direct controls for the sole seed/extension contract, not corpus coverage."""

import copy
import gc
import json
import random
import unittest
import weakref
from fractions import Fraction
from pathlib import Path
from unittest.mock import patch

from proof_fixtures import cut_seed, document, native_release

from hec.count_proofs import FORMAT, canonical_json, compatible_vertices, geometry, parse_json
from hec.proof_builders import closure_seed, dag_seed, table_seed
from hec.reconstruction import CLOSURE, EXTENSION, PIPELINE, Limits, ReconstructionProgram, make_pipeline
from hec.reconstruction_verify import IndependentCubeAuditor, IntervalClosureDecoder

ROOT = Path(__file__).resolve().parents[1]


def mmi(p, scale=1):
    return [
        tuple(scale * value for value in (a * b * (1 - c), a * c * (1 - b), b * c * (1 - a), max(a, b, c)))
        for x in compatible_vertices(p)
        for a, b, c in [tuple((x >> axis) & 1 for axis in range(3))]
    ]


class ReconstructionPipelineTests(unittest.TestCase):
    def setUp(self):
        self.p = geometry(3, (-1, -1, -1, 2, 2, 2, -1))
        self.vertices = list(compatible_vertices(self.p))
        self.rows = mmi(self.p)

    def variants(self, p=None, rows=None):
        p = self.p if p is None else p
        rows = self.rows if rows is None else rows
        vertices = list(compatible_vertices(p))
        return [
            document(p, rows),
            make_pipeline(p, dag_seed(p, rows)),
            make_pipeline(p, cut_seed(p, vertices, rows)),
        ]

    def test_all_seed_families_have_one_exact_full_map_semantics(self):
        identities, proof_ids = set(), set()
        for doc in self.variants():
            program = ReconstructionProgram(doc)
            result = program.audit_reference()
            self.assertEqual((result["checked_vertices"], result["checked_edges"]), (8, 12))
            self.assertEqual(doc["format"], FORMAT)
            self.assertEqual(doc["function"]["kind"], PIPELINE)
            self.assertEqual(program.stages[-1], EXTENSION)
            identities.add(result["semantic_map_id"])
            proof_ids.add(result["proof_id"])
            for x in range(8):
                self.assertEqual(program.evaluate(x), self.rows[x])
        self.assertEqual(len(identities), 1)
        self.assertEqual(len(proof_ids), 3)

    def test_weighted_rational_extension_preserves_proof_not_original_bits(self):
        p = geometry(2, (2, 1, -1))
        program = ReconstructionProgram(document(p, [(0,), (1,), (1,)]))
        self.assertEqual(program.clearing_scale, 2)
        self.assertEqual(program.evaluate(3), (Fraction(1, 2),))
        # A Boolean OR output would instead be 1 here; neither map is privileged.
        self.assertEqual(program.audit_reference()["checked_edges"], 4)

    def test_real_nested_disjoint_standard_fixture(self):
        doc = parse_json((ROOT / "tests/fixtures/count_proof_n5.json").read_bytes())
        program = ReconstructionProgram(doc)
        self.assertTrue(program.problem.disjoint)
        self.assertTrue(program.problem.nested)
        self.assertEqual(program.audit_reference()["checked_edges"], 448)
        auditor = IndependentCubeAuditor(native_release()["cube"])
        try:
            self.assertEqual(program.audit(auditor)["checked_edges"], 448)
        finally:
            auditor.close()

    def test_documented_example_and_self_contained_schema(self):
        text = (ROOT / "docs/proofs.md").read_text()
        example = text.split("```json", 1)[1].split("```", 1)[0]
        self.assertTrue(ReconstructionProgram(parse_json(example.encode())).audit_reference()["ok"])
        schema = json.loads((ROOT / "schemas/repository.schema.json").read_text())

        def visit(value):
            if isinstance(value, dict):
                if "$ref" in value:
                    self.assertTrue(value["$ref"].startswith("#/"))
                for child in value.values():
                    visit(child)
            elif isinstance(value, list):
                for child in value:
                    visit(child)

        visit(schema)

    def test_arbitrary_precision_table_and_dag_share_exact_semantics(self):
        for scale in (1 << 90, (1 << 130) + 51):
            rows = [[Fraction(value) for value in row] for row in self.rows]
            rows[7][0] = Fraction(1, scale)
            programs = [
                ReconstructionProgram(document(self.p, rows)),
                ReconstructionProgram(make_pipeline(self.p, dag_seed(self.p, rows))),
            ]
            self.assertEqual(programs[0].semantic_identity(), programs[1].semantic_identity())
            for program in programs:
                self.assertEqual(program.evaluate(7)[0], Fraction(1, scale))
                self.assertEqual(program.audit_reference()["checked_edges"], 12)

    def test_random_feasible_seeds_are_not_solver_specific(self):
        p, rng = geometry(3, (-1, -1, -1, 4, 4, 4, -1)), random.Random(20261015)
        vertices = list(compatible_vertices(p))
        for _ in range(20):
            rows = [tuple(rng.randrange(2) for _ in p.beta) for _ in vertices]
            for x, image in p.boundary:
                rows[vertices.index(x)] = image
            first = ReconstructionProgram(document(p, rows))
            second = ReconstructionProgram(make_pipeline(p, dag_seed(p, rows)))
            self.assertEqual(first.semantic_identity(), second.semantic_identity())
            self.assertEqual(first.audit_reference()["checked_edges"], 12)

    def test_zero_and_empty_rhs_have_complete_images(self):
        for p in (geometry(1, (0,)), geometry(1, (1,))):
            program = ReconstructionProgram(document(p, [() for _ in compatible_vertices(p)]))
            self.assertEqual(program.audit_reference()["checked_vertices"], p.vertices)
            self.assertEqual(program.evaluate(0), ())

    def test_loaded_program_owns_immutable_canonical_bytes(self):
        doc = document(self.p, self.rows)
        program = ReconstructionProgram(doc)
        expected = program.identity, program.evaluate(3)
        doc["inequality"]["coefficients"][0] = "999"
        exported = program.document
        exported["function"]["seed"]["rows"]["data"] = ""
        self.assertEqual((program.identity, program.evaluate(3)), expected)

    def test_dag_seed_has_no_reference_cycle(self):
        program = ReconstructionProgram(make_pipeline(self.p, dag_seed(self.p, self.rows)))
        enabled = gc.isenabled()
        gc.disable()
        try:
            reference = weakref.ref(program._seed)
            del program
            self.assertIsNone(reference())
        finally:
            if enabled:
                gc.enable()

    def test_materialization_matches_independent_scalar_queries(self):
        for doc in self.variants():
            program = ReconstructionProgram(doc)
            materialized = program.materialize_seed()
            self.assertEqual(materialized.vertices, tuple(self.vertices))
            for vertex, row in zip(materialized.vertices, materialized.numerators, strict=True):
                self.assertEqual(program[vertex], tuple(Fraction(value, materialized.scale) for value in row))

    def test_unknown_execution_paths_and_forged_acceptance_fail_closed(self):
        base = document(self.p, self.rows)
        for target, key, value in (
            ((), "verified", True),
            ((), "source", "/archive/table"),
            (("function",), "binary", "/anything"),
            (("function", "seed"), "source", "/archive/table"),
        ):
            bad = copy.deepcopy(base)
            item = bad
            for part in target:
                item = item[part]
            item[key] = value
            with self.assertRaises(ValueError):
                ReconstructionProgram(bad)

    def test_duplicate_keys_floats_scales_and_limits_fail_closed(self):
        for raw in (b'{"x":1,"x":2}', b'{"x":1.0}', b'{"x":NaN}'):
            with self.assertRaises(ValueError):
                parse_json(raw)
        for value in (0, True, 1.5):
            with self.assertRaises(ValueError):
                Limits(max_l=value)
        doc = document(self.p, self.rows)
        for scale in ({"value": "2", "minimal": False}, {"value": "1", "minimal": True}):
            bad = copy.deepcopy(doc)
            bad["clearing_scale"] = scale
            with self.assertRaises(ValueError):
                ReconstructionProgram(bad)
        with self.assertRaises(ValueError):
            ReconstructionProgram(doc, limits=Limits(max_l=2))
        with self.assertRaises(ValueError):
            ReconstructionProgram(doc).audit_reference(max_vertices=7)

    def test_incomplete_table_and_noncanonical_dags_fail_closed(self):
        with self.assertRaises(ValueError):
            make_pipeline(self.p, table_seed(self.p, self.rows[:-1]))
        doc = make_pipeline(self.p, dag_seed(self.p, self.rows))
        for mutation in ("cycle", "bool", "unreachable", "equal", "unsorted"):
            bad = copy.deepcopy(doc)
            seed = bad["function"]["seed"]
            if mutation == "cycle":
                seed["nodes"][0][1] = 10**6
            elif mutation == "bool":
                seed["roots"][0] = True
            elif mutation == "unreachable":
                seed["terminals"].append("99")
            elif mutation == "equal":
                seed["nodes"][0][2] = seed["nodes"][0][1]
            else:
                seed["nodes"].reverse()
            with self.assertRaises(ValueError, msg=mutation):
                ReconstructionProgram(bad)

    def test_incomplete_backend_receipt_is_never_acceptance(self):
        program = ReconstructionProgram(document(self.p, self.rows))

        class Incomplete:
            extension = EXTENSION

            def verify(self, *args):
                return {"ok": True, "scope": "compatible-seed-only"}

        with self.assertRaises(ValueError):
            program.audit(Incomplete())
        with self.assertRaises(ValueError):
            program.audit({"ok": True})

    def test_fourth_primitive_real_closure_and_independent_full_cube(self):
        binary = native_release()["closure"]
        seed = closure_seed(self.p, self.rows, binary)
        backend = IntervalClosureDecoder(binary)
        program = ReconstructionProgram(make_pipeline(self.p, seed, closure_backend=backend), closure_backend=backend)
        explicit = ReconstructionProgram(document(self.p, self.rows))
        self.assertEqual(program.stages[1], CLOSURE)
        self.assertEqual(program.semantic_identity(), explicit.semantic_identity())
        with patch.object(backend, "decode", wraps=backend.decode) as decode:
            program = ReconstructionProgram(program.document, closure_backend=backend)
            with patch.object(program._seed, "at", side_effect=AssertionError("scalar path")):
                self.assertEqual(program.materialize_seed().numerators, tuple(self.rows))
            decode.assert_called_once()
        auditor = IndependentCubeAuditor(native_release()["cube"])
        try:
            self.assertEqual(program.audit(auditor)["checked_edges"], 12)
        finally:
            auditor.close()
        self.assertEqual(program.audit_reference()["checked_edges"], 12)
        with self.assertRaises(ValueError):
            ReconstructionProgram(program.document)

    def test_uint128_distance_sums_and_explicit_rational_scale(self):
        p, scale = geometry(3, (-25, -25, -25, 26, 26, 26, -25)), 1 << 59
        rows = [tuple(25 * value for value in row) for row in mmi(p, scale)]
        rows[7] = (1, 0, 0, 25 * scale)
        program = ReconstructionProgram(document(p, [[Fraction(value, scale) for value in row] for row in rows]))
        self.assertGreater(sum(p.beta) * scale, (1 << 64) - 1)
        auditor = IndependentCubeAuditor(native_release()["cube"])
        try:
            self.assertEqual(program.audit(auditor)["checked_edges"], 12)
        finally:
            auditor.close()

    def test_canonical_document_rejects_floating_and_boolean_math(self):
        for value in (1.0, float("inf"), Fraction(1, 2)):
            with self.assertRaises(ValueError):
                canonical_json({"value": value})
