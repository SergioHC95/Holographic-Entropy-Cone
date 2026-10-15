import base64
import copy
import itertools
import json
import random
import tempfile
import unittest
from fractions import Fraction
from pathlib import Path

from hec._archive_proof_store import ArchiveProofCatalog as ProofCatalog
from hec._archive_proof_store import write_archive_catalog as write_proof_catalog
from hec._count_kernel import evaluate_kernel, isotonic_projection
from hec.count_proofs import (
    INTEGER_ROWS,
    KERNEL,
    RATIONAL_ROWS,
    canonical_json,
    check_count_proof,
    compatible_vertices,
    decode_rows,
    encode_rows,
    evaluate_count_proof,
    geometry,
    inequality_id,
    make_count_proof,
    parse_json,
    proof_geometry,
    proof_id,
)
from hec.inequality_records import InequalityCatalog, inequality_catalog, write_inequality_catalog


class CountProofTests(unittest.TestCase):
    def setUp(self):
        self.problem = geometry(2, (1, 1, -1))
        self.proof = make_count_proof(self.problem, [(0,), (1,), (1,), (0,)], audit_table=True)

    def test_integer_table_and_all_original_edges(self):
        result = check_count_proof(self.proof)
        self.assertEqual(result["checked_vertices"], 4)
        self.assertEqual(result["checked_edges"], 4)
        self.assertEqual(result["scope"], "original-cube-all-edges")
        self.assertEqual(self.proof["clearing_scale"], {"value": "1", "minimal": True})
        self.assertEqual(self.proof["function"]["rows"]["encoding"], INTEGER_ROWS)
        self.assertEqual(
            [evaluate_count_proof(self.proof, x) for x in range(4)],
            [(Fraction(0),), (Fraction(1),), (Fraction(1),), (Fraction(0),)],
        )

    def test_fractional_map_and_explicit_minimal_scale(self):
        problem = geometry(2, (2, 1, -1))
        proof = make_count_proof(problem, [(0,), (1,), (1,), (Fraction(1, 2),)], integral=False, audit_table=True)
        self.assertEqual(proof["clearing_scale"], {"value": "2", "minimal": True})
        self.assertEqual(proof["function"]["rows"]["encoding"], RATIONAL_ROWS)
        self.assertEqual(evaluate_count_proof(proof, 3), (Fraction(1, 2),))

    def test_canonical_joint_denominator_arbitrary_precision(self):
        problem = geometry(3, (1, 1, 1, -1, -1, 0, 0))
        value = 10**80 + 1
        payload, scale = encode_rows(problem, [(Fraction(1, value), Fraction(2, value))], integral=False)
        self.assertEqual(scale, value)
        self.assertEqual(list(decode_rows(problem, payload)), [(value, (1, 2))])
        payload2, _ = encode_rows(problem, [(Fraction(3, 6), Fraction(4, 6))], integral=False)
        self.assertEqual(list(decode_rows(problem, payload2)), [(6, (3, 4))])

    def test_exact_geometry_rejects_floats_bools_and_nonprimitive_normals(self):
        for coefficients in ((1.0, 1, -1), (True, 1, -1), (2, 2, -2)):
            with self.assertRaises(ValueError):
                geometry(2, coefficients)
        for raw in (1, 1.0, True, "01", "-0", "+1", "1.0", " 1"):
            proof = copy.deepcopy(self.proof)
            proof["inequality"]["coefficients"][0] = raw
            with self.assertRaises(ValueError):
                check_count_proof(proof)

    def test_json_rejects_duplicate_keys_float_nan_unsafe_number(self):
        for source in (b'{"a":1,"a":2}', b'{"a":1.0}', b'{"a":NaN}', b'{"a":9007199254740992}'):
            with self.assertRaises(ValueError):
                parse_json(source)
        with self.assertRaises(ValueError):
            canonical_json({"a": -1})
        self.assertEqual(parse_json(canonical_json(self.proof)), self.proof)

    def test_complete_domain_wrong_boundary_and_edge_fail_closed(self):
        for rows in ([(0,), (1,), (1,)], [(0,), (0,), (1,), (0,)]):
            with self.assertRaises(ValueError):
                make_count_proof(self.problem, rows)
        problem = geometry(3, (1, 1, 1, -1, -1, 0, 0))
        # Boundary images are preserved; vertex 3 has an invalid axis-1 edge.
        rows = [(0, 0), (1, 1), (1, 0), (0, 0), (0, 1), (0, 0), (0, 0), (0, 0)]
        with self.assertRaisesRegex(ValueError, "edge violation"):
            make_count_proof(problem, rows)

    def test_nonminimal_varints_truncation_trailing_and_bad_padding(self):
        problem = geometry(2, (2, 1, -1))
        payload, _ = encode_rows(problem, [(Fraction(1, 2),)], integral=False)
        for data in (b"\x82\x00\x01", b"\x02", b"\x04\x02", b"\x02\x01\x00", b"\x00\x00"):
            malformed = dict(payload, data=base64.b64encode(data).decode())
            with self.assertRaises(ValueError):
                list(decode_rows(problem, malformed))
        proof = copy.deepcopy(self.proof)
        proof["function"]["rows"]["data"] = base64.b64encode(b"\x86").decode()
        with self.assertRaisesRegex(ValueError, "padding"):
            check_count_proof(proof)

    def test_occurrence_conflict_is_not_a_proof(self):
        with self.assertRaisesRegex(ValueError, "boundary"):
            geometry(2, (1, -1, 0))

    def test_empty_rhs_full_function(self):
        problem = geometry(1, (1,))
        proof = make_count_proof(problem, [(), ()])
        self.assertEqual(check_count_proof(proof)["checked_edges"], 1)
        self.assertEqual(evaluate_count_proof(proof, 1), ())

    def test_bounded_integer_batches_match_arbitrary_precision_reference(self):
        randomizer = random.Random(137)
        for beta in ((1, 1, 1, 1), (1, 3, 7, 9), (1, 1 << 30, 1 << 30, 1), (1, (1 << 61) + 3, 1, 1)):
            capacity = sum(beta)
            problem = geometry(3, (capacity, capacity, capacity, *(-value for value in beta)))
            for _ in range(4):
                rows = [tuple(randomizer.randrange(value + 1) for value in beta) for _ in range(8)]
                for vertex, image in problem.boundary:
                    rows[vertex] = image
                proof = make_count_proof(problem, rows, audit_table=True)
                self.assertEqual(check_count_proof(proof), check_count_proof(proof, reference=True))

    def test_integer_overflow_guard_uses_exact_reference(self):
        capacity = (1 << 80) + 1
        problem = geometry(2, (capacity, capacity, -1))
        proof = make_count_proof(problem, [(0,), (1,), (1,), (0,)], audit_table=True)
        self.assertEqual(check_count_proof(proof), check_count_proof(proof, reference=True))
        problem = geometry(2, (capacity, capacity, -(1 << 80)))
        proof = make_count_proof(problem, [(0,), (1 << 80,), (1 << 80,), (0,)], audit_table=True)
        self.assertEqual(check_count_proof(proof), check_count_proof(proof, reference=True))


class KernelTests(unittest.TestCase):
    def test_real_nested_disjoint_case_exhaustively_matches_contract(self):
        path = Path(__file__).parent / "fixtures/count_proof_n5.json"
        literal = parse_json(path.read_bytes())
        self.assertEqual(check_count_proof(literal), check_count_proof(literal, reference=True))
        problem = proof_geometry(literal)
        self.assertTrue(problem.disjoint)
        self.assertTrue(problem.nested)
        source = list(decode_rows(problem, literal["function"]["rows"]))
        seed = {
            vertex: tuple(Fraction(value, source[vertex][0]) for value in source[vertex][1])
            for vertex in compatible_vertices(problem)
        }
        compact = make_count_proof(problem, seed.values(), kernel=True)
        rows = [evaluate_kernel(problem, seed, vertex) for vertex in range(problem.vertices)]
        table = make_count_proof(problem, rows, integral=False, audit_table=True)
        self.assertEqual(check_count_proof(table)["checked_edges"], 448)
        for vertex in problem.boundary:
            self.assertEqual(evaluate_count_proof(compact, vertex[0]), rows[vertex[0]])

    def test_complete_domain_matches_independent_bruteforce(self):
        for n in range(1, 5):
            # Deterministically exercise many nesting and disjoint patterns.
            for shift in range(8):
                coefficients = tuple(int((index + shift) % 3 != 0) for index in range((1 << n) - 1))
                problem = geometry(n, coefficients)
                expected = [
                    x
                    for x in range(problem.vertices)
                    if all(not (x >> i & x >> j & 1) for i, j in problem.disjoint)
                    and all(not (x >> i & 1) or x >> j & 1 for i, j in problem.nested)
                ]
                self.assertEqual(list(compatible_vertices(problem)), expected)

    def test_fractional_disjoint_extension_all_cube_edges(self):
        for a, b in itertools.product(range(1, 6), repeat=2):
            problem = geometry(2, (a, b, -1))
            proof = make_count_proof(problem, [(0,), (1,), (1,)], kernel=True)
            result = check_count_proof(proof)
            self.assertEqual(result["checked_vertices"], 3)
            self.assertEqual(result["checked_edges"], 2)
            self.assertFalse(result["minimal_scale"])
            self.assertEqual(proof["function"]["kind"], KERNEL)
            rows = [evaluate_count_proof(proof, x, verify=False) for x in range(problem.vertices)]
            make_count_proof(problem, rows, integral=all(value.denominator == 1 for row in rows for value in row))
            self.assertEqual(rows[3], (Fraction(abs(a - b), max(a, b)),))

    def test_nesting_projection_known_exact_mean(self):
        problem = geometry(2, (1, -1, 2))
        self.assertEqual(isotonic_projection(problem, 1), (Fraction(1, 3), Fraction(1, 3)))
        self.assertEqual(isotonic_projection(problem, 2), (Fraction(0), Fraction(1)))
        proof = make_count_proof(problem, [(0,), (1,), (0,)], kernel=True)
        rows = [evaluate_count_proof(proof, x, verify=False) for x in range(4)]
        make_count_proof(problem, rows, integral=False)

    def test_projection_against_exhaustive_partition_optimizer(self):
        def partitions(size):
            if not size:
                yield ()
                return

            def visit(labels):
                if len(labels) == size:
                    yield tuple(labels)
                else:
                    for label in range(max(labels, default=-1) + 2):
                        yield from visit(labels + [label])

            yield from visit([])

        for coefficients in ((1, 0, 2), (1, 1, 0, 2, 0, 0, 3), (1, 0, 1, 0, 2, 0, 3)):
            problem = geometry((len(coefficients) + 1).bit_length() - 1, coefficients)
            for vertex in range(problem.vertices):
                objective = None
                minimizer = None
                for labels in partitions(problem.L):
                    levels = {}
                    for label in set(labels):
                        block = [i for i in range(problem.L) if labels[i] == label]
                        levels[label] = Fraction(
                            sum(problem.alpha[i] * (vertex >> i & 1) for i in block),
                            sum(problem.alpha[i] for i in block),
                        )
                    candidate = tuple(levels[label] for label in labels)
                    if any(candidate[i] > candidate[j] for i, j in problem.nested):
                        continue
                    loss = sum(
                        weight * (value - (vertex >> i & 1)) ** 2
                        for i, (weight, value) in enumerate(zip(problem.alpha, candidate, strict=True))
                    )
                    if objective is None or loss < objective:
                        objective, minimizer = loss, candidate
                self.assertEqual(isotonic_projection(problem, vertex), minimizer)

    def test_seed_domain_is_not_the_full_cube_and_scale_is_not_trusted(self):
        problem = geometry(2, (2, 1, -1))
        with self.assertRaisesRegex(ValueError, "entire"):
            make_count_proof(problem, [(0,), (1,), (1,), (0,)], kernel=True)
        proof = make_count_proof(problem, [(0,), (1,), (1,)], kernel=True)
        proof["clearing_scale"]["value"] = "1"
        with self.assertRaisesRegex(ValueError, "scale"):
            check_count_proof(proof)


class ProofStoreTests(unittest.TestCase):
    def setUp(self):
        self.a = make_count_proof(geometry(2, (1, 1, -1)), [(0,), (1,), (1,), (0,)])
        self.b = make_count_proof(geometry(2, (2, 1, -1)), [(0,), (1,), (1,)], kernel=True)

    def test_sharding_and_compression_do_not_change_proof_ids(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            one = write_proof_catalog(root / "one/catalog.json", [self.a, self.b], compression_level=1)
            two = write_proof_catalog(root / "two/catalog.json", [self.a, self.b], shard_bytes=1, compression_level=19)
            self.assertEqual(len(one["shards"]), 1)
            self.assertEqual(len(two["shards"]), 2)
            self.assertEqual(
                [entry["proof_id"] for entry in one["entries"]], [entry["proof_id"] for entry in two["entries"]]
            )
            reader = ProofCatalog(root / "one/catalog.json")
            self.assertEqual(list(reader), [self.a, self.b])
            self.assertEqual(reader.verify()["proofs"], 2)
            self.assertEqual(list(reader.iter_selected(1, 2)), [(1, self.b)])
            self.assertEqual(inequality_id(geometry(2, (1, 1, -1))), one["entries"][0]["inequality_id"])
            self.assertEqual(proof_id(self.b), two["entries"][1]["proof_id"])

    def test_corruption_misalignment_duplicate_index_and_path_escape(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "catalog.json"
            catalog = write_proof_catalog(path, [self.a, self.b])
            shard = path.parent / "proof-shards" / (next(iter(catalog["shards"])) + ".proofpack")
            original = shard.read_bytes()
            shard.write_bytes(original[:-1] + bytes([original[-1] ^ 1]))
            with self.assertRaisesRegex(ValueError, "SHA256"):
                ProofCatalog(path)[0]
            shard.write_bytes(original)
            for mutation in ("overlap", "duplicate", "escape", "identity"):
                altered = copy.deepcopy(catalog)
                if mutation == "overlap":
                    altered["entries"][1]["offset"] = 0
                elif mutation == "duplicate":
                    altered["entries"][1]["proof_id"] = altered["entries"][0]["proof_id"]
                elif mutation == "escape":
                    altered["entries"][0]["shard"] = "../proofpack"
                else:
                    altered["entries"][0]["inequality_id"] = "0" * 64
                path.write_text(json.dumps(altered))
                with self.assertRaises(ValueError):
                    ProofCatalog(path)[0]

    def test_existing_catalog_and_immutable_data_are_not_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "catalog.json"
            write_proof_catalog(path, [self.a])
            original = path.read_bytes()
            with self.assertRaises(ValueError):
                write_proof_catalog(path, [self.b])
            self.assertEqual(path.read_bytes(), original)

    def test_inequality_records_exactly_bind_all_proofs_and_no_facet_claim(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_proof_catalog(root / "proofs.json", [self.a, self.b])
            records = inequality_catalog([self.a, self.b])
            path = root / "inequalities.json"
            write_inequality_catalog(path, records)
            self.assertEqual(
                InequalityCatalog(path).check_bindings(ProofCatalog(root / "proofs.json")),
                {"ok": True, "inequalities": 2, "proofs": 2},
            )
            for mutation in ("normal", "float", "unmatched", "facet"):
                altered = copy.deepcopy(records)
                if mutation == "normal":
                    altered["entries"][0]["coefficients"][0] = "123"
                elif mutation == "float":
                    altered["entries"][0]["coefficients"][0] = 1.0
                elif mutation == "unmatched":
                    altered["entries"][0]["proof_ids"] = ["0" * 64]
                else:
                    altered["entries"][0]["facet"] = True
                path.write_text(json.dumps(altered))
                with self.assertRaises(ValueError):
                    InequalityCatalog(path).check_bindings(ProofCatalog(root / "proofs.json"))

    def test_authoritative_store_rejects_enumerated_audit_tables(self):
        audit = make_count_proof(geometry(2, (1, 1, -1)), [(0,), (1,), (1,), (0,)], audit_table=True)
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "audit tables"):
                write_proof_catalog(Path(directory) / "proofs.json", [audit])


class DecisionDiagramTests(unittest.TestCase):
    def test_scalar_sharing_and_independent_exhaustive_reference(self):
        n = 8
        coefficients = [n - 1] * n + [-1] * (n * (n - 1) // 2)
        coefficients += [0] * ((1 << n) - 1 - len(coefficients))
        problem = geometry(n, tuple(coefficients))
        rows = [tuple(int(bool(vertex & support)) for support in problem.rhs) for vertex in range(problem.vertices)]
        proof = make_count_proof(problem, rows)
        self.assertEqual(proof["function"]["kind"], "count-decision-dag/1")
        self.assertEqual(len(proof["function"]["terminals"]), 2)
        self.assertEqual(len(proof["function"]["nodes"]), 35)
        self.assertEqual(check_count_proof(proof), check_count_proof(proof, reference=True))
        self.assertEqual(check_count_proof(proof)["checked_edges"], 1024)
        for vertex in range(problem.vertices):
            self.assertEqual(evaluate_count_proof(proof, vertex, verify=False), rows[vertex])

    def test_fractional_diagrams_match_exhaustive_arbitrary_precision(self):
        randomizer = random.Random(154)
        problem = geometry(3, (4, 4, 4, -1, -1, -1, -1))
        for _ in range(12):
            rows = [tuple(Fraction(randomizer.randrange(6), 5) for _g in range(problem.G)) for _x in range(8)]
            for vertex, image in problem.boundary:
                rows[vertex] = image
            proof = make_count_proof(problem, rows, integral=False)
            self.assertEqual(check_count_proof(proof), check_count_proof(proof, reference=True))

    def test_noncanonical_cyclic_unreachable_or_misbound_diagrams_fail_closed(self):
        proof = make_count_proof(geometry(2, (1, 1, -1)), [(0,), (1,), (1,), (0,)])
        for mutation in ("cycle", "unreduced", "bad-order", "bad-root", "fraction", "extra"):
            changed = copy.deepcopy(proof)
            function = changed["function"]
            if mutation == "cycle":
                function["nodes"][-1][1] = len(function["nodes"]) + len(function["terminals"]) - 1
            elif mutation == "unreduced":
                function["nodes"][0][2] = function["nodes"][0][1]
            elif mutation == "bad-order":
                function["nodes"][0][0] = 1
            elif mutation == "bad-root":
                function["roots"][0] = 999
            elif mutation == "fraction":
                function["terminals"][1] = ["2", "2"]
            else:
                function["nodes"].append([1, 0, 1])
            with self.assertRaises(ValueError):
                check_count_proof(changed)


if __name__ == "__main__":
    unittest.main()
