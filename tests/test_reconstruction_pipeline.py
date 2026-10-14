"""One seed/extension contract; controls are not full-corpus coverage."""

import copy
import hashlib
import json
import os
import random
import shutil
import subprocess
import sys
import tempfile
import unittest
from fractions import Fraction
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from corpus_derivations import diagrams  # noqa: E402
from corpus_derivations.pipeline_import import (  # noqa: E402
    NativeClosure,
    NativePipelineAuditor,
    canonical_dag,
    import_recipe,
)
from derivation_pilot.recipes import choice_recipe, closure_call, cut_recipe  # noqa: E402

from hec.count_proofs import (  # noqa: E402
    FORMAT,
    canonical_json,
    check_count_proof,
    compatible_vertices,
    decode_rows,
    encode_rows,
    evaluate_count_proof,
    geometry,
    make_count_proof,
    parse_json,
    proof_geometry,
)
from hec.reconstruction import (  # noqa: E402
    CLOSURE,
    EXTENSION,
    PIPELINE,
    TABLE,
    Limits,
    ReconstructionProgram,
    make_pipeline,
)


def mmi(p, scale=1):
    return [
        tuple(scale * value for value in (a * b * (1 - c), a * c * (1 - b), b * c * (1 - a), max(a, b, c)))
        for x in compatible_vertices(p)
        for a, b, c in [tuple((x >> axis) & 1 for axis in range(3))]
    ]


def table(p, rows, *, integral=True):
    return {"kind": TABLE, "rows": encode_rows(p, rows, integral=integral)[0]}


class ReconstructionPipelineTests(unittest.TestCase):
    def setUp(self):
        self.p = geometry(3, (-1, -1, -1, 2, 2, 2, -1))
        self.vertices = list(compatible_vertices(self.p))
        self.rows = mmi(self.p)

    def test_three_seed_families_have_one_exact_full_map_semantics(self):
        sources = [
            make_count_proof(self.p, self.rows, transport=True),
            diagrams.build(self.p, self.vertices, 1, self.rows),
            cut_recipe(self.p, self.vertices, self.rows)[0],
        ]
        identities, proof_ids = set(), set()
        for source in sources:
            document, receipt = import_recipe(source)
            program = ReconstructionProgram(document)
            self.assertEqual(program.stages[-1], EXTENSION)
            self.assertEqual(document["format"], FORMAT)
            self.assertEqual(document["function"]["kind"], PIPELINE)
            audit = program.audit_reference()
            self.assertEqual((audit["checked_vertices"], audit["checked_edges"]), (8, 12))
            self.assertFalse(receipt["new_exhaustive_original_cube_audit_executed"])
            self.assertTrue(receipt["source_mathematical_acceptance_still_required"])
            self.assertEqual(receipt["checked_compatible_vertices"], len(self.vertices))
            identities.add(audit["semantic_map_id"])
            proof_ids.add(audit["proof_id"])
            for x in range(self.p.vertices):
                self.assertEqual(program.evaluate(x), tuple(self.rows[x]))
        self.assertEqual(len(identities), 1)
        self.assertEqual(len(proof_ids), 3)  # Encoding identity is not semantic identity.

    def test_weighted_mass_and_rational_thresholds_are_shared(self):
        p, rows = geometry(2, (2, 1, -1)), [(0,), (1,), (1,)]
        document = make_pipeline(p, table(p, rows))
        program = ReconstructionProgram(document)
        original = make_count_proof(p, rows, transport=True)
        self.assertEqual(program.clearing_scale, 2)
        self.assertEqual(program.evaluate(3), (Fraction(1, 2),))
        for vertex in range(p.vertices):
            self.assertEqual(program.evaluate(vertex), evaluate_count_proof(original, vertex))
        self.assertEqual(program.audit_reference()["checked_edges"], 4)

    def test_general_restriction_extension_is_proof_preserving_not_always_bit_preserving(self):
        p = geometry(2, (2, 1, -1))
        original = make_count_proof(p, [(0,), (1,), (1,), (1,)])
        restricted = [evaluate_count_proof(original, x, verify=False) for x in compatible_vertices(p)]
        program = ReconstructionProgram(make_pipeline(p, table(p, restricted)))
        self.assertEqual(evaluate_count_proof(original, 3), (Fraction(1),))
        self.assertEqual(program.evaluate(3), (Fraction(1, 2),))
        self.assertEqual(program.audit_reference()["checked_edges"], 4)

    def test_real_nested_disjoint_fixture_preserves_all_original_cube_images(self):
        literal = parse_json((ROOT / "tests/fixtures/count_proof_n5.json").read_bytes())
        p = proof_geometry(literal)
        self.assertTrue(p.disjoint)
        self.assertTrue(p.nested)
        original = list(decode_rows(p, literal["function"]["rows"]))
        seed = [[Fraction(value, original[x][0]) for value in original[x][1]] for x in compatible_vertices(p)]
        source = make_count_proof(p, seed, integral=False, transport=True)
        document, _ = import_recipe(source)
        program = ReconstructionProgram(document)
        for x in range(p.vertices):
            self.assertEqual(program.evaluate(x), evaluate_count_proof(source, x, verify=False))
        self.assertEqual(program.audit_reference()["checked_edges"], 448)

    def test_documented_program_executes_and_schema_references_resolve_locally(self):
        doc = (ROOT / "docs/contraction-derivation-experiments.md").read_text()
        example = doc.split("a complete MMI reconstruction is:", 1)[1].split("```json", 1)[1].split("```", 1)[0]
        program = ReconstructionProgram(parse_json(example.encode()))
        self.assertEqual(program.audit_reference()["checked_edges"], 12)
        schema_path = ROOT / "schemas/reconstruction-pipeline-v1.schema.json"
        schema = json.loads(schema_path.read_bytes())
        self.assertEqual(schema["properties"]["function"]["properties"]["kind"]["const"], PIPELINE)

        def visit(node):
            if isinstance(node, dict):
                if "$ref" in node:
                    filename, pointer = node["$ref"].split("#", 1)
                    target = json.loads((schema_path.parent / filename).read_bytes()) if filename else schema
                    for part in pointer.lstrip("/").split("/"):
                        target = target[int(part)] if isinstance(target, list) else target[part]
                    self.assertIsInstance(target, dict)
                for child in node.values():
                    visit(child)
            elif isinstance(node, list):
                for child in node:
                    visit(child)

        visit(schema)

    def test_arbitrary_precision_fractional_seed_and_shared_dag_agree(self):
        scale = 1 << 90
        rows = mmi(self.p, scale)
        rows[7] = (1, 0, 0, scale)
        exact = [[Fraction(value, scale) for value in row] for row in rows]
        programs = [
            ReconstructionProgram(make_pipeline(self.p, table(self.p, exact, integral=False))),
            ReconstructionProgram(
                make_pipeline(self.p, canonical_dag(diagrams.build(self.p, self.vertices, scale, rows)["function"]))
            ),
        ]
        self.assertEqual(programs[0].semantic_identity(), programs[1].semantic_identity())
        for program in programs:
            self.assertEqual(program.evaluate(7)[0], Fraction(1, scale))
            self.assertEqual(program.clearing_scale, scale)
            self.assertEqual(program.audit_reference()["checked_edges"], 12)

    def test_random_feasible_seeds_do_not_assume_special_solver_structure(self):
        p, rng = geometry(3, (-1, -1, -1, 4, 4, 4, -1)), random.Random(20261014)
        vertices = list(compatible_vertices(p))
        for _ in range(20):
            rows = [tuple(rng.randrange(2) for _ in p.beta) for _ in vertices]
            for x, image in p.boundary:
                rows[vertices.index(x)] = image
            first = ReconstructionProgram(make_pipeline(p, table(p, rows)))
            second = ReconstructionProgram(
                make_pipeline(p, canonical_dag(diagrams.build(p, vertices, 1, rows)["function"]))
            )
            self.assertEqual(first.semantic_identity(), second.semantic_identity())
            self.assertEqual(first.audit_reference()["checked_edges"], 12)

    def test_zero_and_empty_rhs_have_complete_not_missing_images(self):
        for p in (geometry(1, (0,)), geometry(1, (1,))):
            rows = [() for _ in compatible_vertices(p)]
            program = ReconstructionProgram(make_pipeline(p, table(p, rows)))
            self.assertEqual(program.audit_reference()["checked_vertices"], p.vertices)
            self.assertEqual(program.evaluate(0), ())

    def test_input_documents_and_returned_documents_do_not_mutate_loaded_program(self):
        document = make_pipeline(self.p, table(self.p, self.rows))
        program = ReconstructionProgram(document)
        identity, image = program.identity, program.evaluate(3)
        document["inequality"]["coefficients"][0] = "999"
        exported = program.document
        exported["function"]["seed"]["rows"]["data"] = ""
        self.assertEqual((program.identity, program.evaluate(3)), (identity, image))

    def test_unknown_execution_paths_and_forged_acceptance_fields_fail_closed(self):
        document = make_pipeline(self.p, table(self.p, self.rows))
        for location, key, value in (
            ((), "verified", True),
            (("function",), "script", "anything.py"),
            (("function", "seed"), "source", "/archived/table"),
            (("function", "extension"), "order", "custom"),
        ):
            bad, at = copy.deepcopy(document), None
            at = bad
            for part in location:
                at = at[part]
            at[key] = value
            with self.assertRaises(ValueError):
                ReconstructionProgram(bad)
        bad = copy.deepcopy(document)
        bad["function"]["extension"]["kind"] = "execute-arbitrary-code/1"
        with self.assertRaises(ValueError):
            ReconstructionProgram(bad)

    def test_duplicate_keys_floats_bad_scale_and_unsupported_geometry_are_rejected(self):
        document = make_pipeline(self.p, table(self.p, self.rows))
        for mutation in ("scale", "minimal", "float", "party", "primitive"):
            bad = copy.deepcopy(document)
            if mutation == "scale":
                bad["clearing_scale"]["value"] = "2"
            elif mutation == "minimal":
                bad["clearing_scale"]["minimal"] = True
            elif mutation == "float":
                bad["inequality"]["coefficients"][0] = 0.5
            elif mutation == "party":
                bad["inequality"]["n"] = 10**9
            else:
                bad["function"]["seed"]["kind"] = "unknown/1"
            with self.assertRaises(ValueError, msg=mutation):
                ReconstructionProgram(bad)
        with self.assertRaisesRegex(ValueError, "duplicate"):
            ReconstructionProgram(canonical_json(document).replace(b'"format":', b'"format":"x","format":', 1))
        with patch("hec.reconstruction.CompatibleRank", side_effect=AssertionError("must not enumerate")):
            with self.assertRaisesRegex(ValueError, "capability"):
                ReconstructionProgram(document, limits=Limits(max_l=1))

    def test_seed_and_full_cube_scopes_are_not_conflated_or_sampled(self):
        program = ReconstructionProgram(make_pipeline(self.p, table(self.p, self.rows)))
        seed = program.materialize_seed()
        self.assertEqual(len(seed.vertices), 8)
        with self.assertRaisesRegex(ValueError, "full-cube backend"):
            program.audit_reference(max_vertices=4)
        with self.assertRaises(ValueError):
            program.evaluate(True)
        with self.assertRaises(ValueError):
            program.evaluate(8)

    def test_well_formed_bad_boundary_or_coupled_distance_is_not_a_proof(self):
        for mutation in ("boundary", "coupling"):
            p = geometry(3, (-1, -1, -1, 1, 1, 1, -1))
            rows = mmi(p)
            rows[3 if mutation == "boundary" else 7] = (0, 0, 0, 0) if mutation == "boundary" else (1, 1, 1, 0)
            with self.assertRaisesRegex(ValueError, "boundary|contraction"):
                make_pipeline(p, table(p, rows))

    def test_missing_compatible_rows_and_dag_forgery_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "complete compatible"):
            make_pipeline(self.p, table(self.p, self.rows[:-1]))
        document = make_pipeline(self.p, canonical_dag(diagrams.build(self.p, self.vertices, 1, self.rows)["function"]))
        for mutation in ("cycle", "bool", "unreachable", "equal", "unsorted"):
            bad = copy.deepcopy(document)
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

    def test_production_reader_is_not_silently_changed_and_old_extension_not_mislabelled(self):
        document = make_pipeline(self.p, table(self.p, self.rows))
        with self.assertRaises(ValueError):
            check_count_proof(document)
        old_order = make_count_proof(self.p, self.rows, kernel=True)
        with self.assertRaisesRegex(ValueError, "same cancel/fill"):
            import_recipe(old_order)

    def test_native_acceptance_requires_a_live_call_and_complete_bound_coverage(self):
        program = ReconstructionProgram(make_pipeline(self.p, table(self.p, self.rows)))

        class IncompleteBackend:
            extension = EXTENSION

            def verify(self, p, vertices, scale, rows):
                return {"ok": True, "scope": "compatible-seed-only"}

        with self.assertRaisesRegex(ValueError, "incomplete or mismatched"):
            program.audit(IncompleteBackend())
        with self.assertRaisesRegex(ValueError, "backend"):
            program.audit({"ok": True, "scope": "original-cube-all-edges"})


@unittest.skipUnless(shutil.which("c++"), "exact closure control needs a C++17 compiler")
class ClosurePipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="hec-pipeline-closure-test-")
        cls.binary = Path(os.environ.get("HEC_DERIVATION_BINARY", str(Path(cls.temporary.name) / "closure")))
        if not cls.binary.is_file():
            subprocess.run(
                ["c++", "-O2", "-std=c++17", str(ROOT / "tools/derivation_pilot/closure.cpp"), "-o", str(cls.binary)],
                check=True,
            )
        cls.sha256 = hashlib.sha256(cls.binary.read_bytes()).hexdigest()

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def test_real_sparse_closure_joins_the_same_pipeline_and_semantic_identity(self):
        p = geometry(3, (-1, -1, -1, 3, 3, 3, -1))
        rows = mmi(p)
        source = choice_recipe(p, closure_call(self.binary, p, mode="encode", rows=rows))
        backend = NativeClosure(self.binary, self.sha256)
        target, receipt = import_recipe(source, closure_backend=backend)
        program = ReconstructionProgram(target, closure_backend=backend)
        explicit = ReconstructionProgram(make_pipeline(p, table(p, rows)))
        self.assertEqual(program.semantic_identity(), explicit.semantic_identity())
        self.assertEqual(program.audit_reference()["checked_edges"], 12)
        self.assertFalse(receipt["new_exhaustive_original_cube_audit_executed"])
        self.assertEqual(program.stages[1], CLOSURE)
        with self.assertRaisesRegex(ValueError, "backend required"):
            ReconstructionProgram(target)
        with self.assertRaisesRegex(ValueError, "binary changed"):
            NativeClosure(self.binary, "0" * 64)


@unittest.skipUnless(shutil.which("c++"), "independent pipeline control needs a C++17 compiler")
class NativePipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="hec-pipeline-audit-test-")
        cls.binary = Path(os.environ.get("HEC_WIDE_AUDITOR", str(Path(cls.temporary.name) / "wide")))
        if not cls.binary.is_file():
            subprocess.run(
                [
                    "c++",
                    "-O2",
                    "-std=c++17",
                    str(ROOT / "tools/corpus_derivations/audit_wide.cpp"),
                    "-o",
                    str(cls.binary),
                ],
                check=True,
            )
        cls.sha256 = hashlib.sha256(cls.binary.read_bytes()).hexdigest()

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def test_independent_original_cube_backend_is_shared_across_seed_families(self):
        p = geometry(3, (-1, -1, -1, 2, 2, 2, -1))
        rows, vertices = mmi(p), list(compatible_vertices(p))
        sources = [
            make_count_proof(p, rows, transport=True),
            diagrams.build(p, vertices, 1, rows),
            cut_recipe(p, vertices, rows)[0],
        ]
        auditor = NativePipelineAuditor(self.binary, self.sha256)
        try:
            for source in sources:
                target, _ = import_recipe(source)
                program = ReconstructionProgram(target)
                native, reference = program.audit(auditor), program.audit_reference()
                self.assertEqual(native["checked_edges"], 12)
                self.assertEqual(native["scope"], "original-cube-all-edges")
                self.assertEqual(native["semantic_map_id"], reference["semantic_map_id"])
                self.assertEqual(native["proof_id"], program.identity)
        finally:
            auditor.close()

    def test_wide_distance_accumulators_and_explicit_rational_scaling(self):
        p, scale = geometry(3, (-25, -25, -25, 26, 26, 26, -25)), 1 << 59
        rows = [tuple(25 * value for value in row) for row in mmi(p, scale)]
        rows[7] = (1, 0, 0, 25 * scale)
        exact = [[Fraction(value, scale) for value in row] for row in rows]
        program = ReconstructionProgram(make_pipeline(p, table(p, exact, integral=False)))
        self.assertGreater(sum(p.beta) * scale, (1 << 64) - 1)
        auditor = NativePipelineAuditor(self.binary, self.sha256)
        try:
            native = program.audit(auditor)
            self.assertEqual(native["checked_edges"], 12)
            self.assertEqual(native["clearing_scale"], str(scale))
        finally:
            auditor.close()


if __name__ == "__main__":
    unittest.main()
