import copy
import itertools
import tempfile
import unittest
from fractions import Fraction
from pathlib import Path

from hec._count_transport import CompatibleRank, SeedLookup, evaluate_transport, transport_mass
from hec.count_proofs import (
    TRANSPORT,
    check_count_proof,
    compatible_vertices,
    decode_rows,
    evaluate_count_proof,
    geometry,
    make_count_proof,
    parse_json,
    proof_geometry,
)
from hec.proof_store import ProofCatalog, write_proof_catalog


class TransportProofTests(unittest.TestCase):
    def test_weighted_disjoint_cases_have_exact_full_cube_proofs(self):
        for a, b in itertools.product(range(1, 7), repeat=2):
            problem = geometry(2, (a, b, -1))
            proof = make_count_proof(problem, [(0,), (1,), (1,)], transport=True)
            self.assertEqual(proof["function"]["kind"], TRANSPORT)
            rows = [evaluate_count_proof(proof, x, verify=False) for x in range(4)]
            self.assertEqual(rows[3], (Fraction(abs(a - b), max(a, b)),))
            audit = make_count_proof(problem, rows, integral=False, audit_table=True)
            self.assertEqual(check_count_proof(audit, reference=True)["checked_edges"], 4)

    def test_nesting_transfer_uses_parent_capacity_not_isotonic_mean(self):
        problem = geometry(2, (1, -1, 2))
        proof = make_count_proof(problem, [(0,), (1,), (0,)], transport=True)
        self.assertEqual(transport_mass(problem, 1), (0, 1))
        self.assertEqual(evaluate_count_proof(proof, 1), (Fraction(1, 2),))
        self.assertEqual(proof["clearing_scale"], {"value": "2", "minimal": False})
        rows = [evaluate_count_proof(proof, x, verify=False) for x in range(4)]
        make_count_proof(problem, rows, integral=False, audit_table=True)

    def test_full_real_nested_disjoint_fixture(self):
        literal = parse_json((Path(__file__).parent / "fixtures/count_proof_n5.json").read_bytes())
        problem = proof_geometry(literal)
        original = list(decode_rows(problem, literal["function"]["rows"]))
        seed = {x: tuple(Fraction(v, original[x][0]) for v in original[x][1]) for x in compatible_vertices(problem)}
        proof = make_count_proof(problem, seed.values(), transport=True, integral=False)
        lookup = SeedLookup(problem, proof["function"]["rows"])
        rows = [evaluate_transport(problem, lookup, x) for x in range(problem.vertices)]
        self.assertEqual(rows, [evaluate_transport(problem, seed, x) for x in range(problem.vertices)])
        audit = make_count_proof(problem, rows, integral=False, audit_table=True)
        self.assertEqual(check_count_proof(audit, reference=True)["checked_edges"], 448)

    def test_domain_ranks_match_independent_complete_enumerator(self):
        for n in range(1, 5):
            for shift in range(8):
                problem = geometry(n, tuple(int((index + shift) % 3 != 0) for index in range((1 << n) - 1)))
                rank = CompatibleRank(problem)
                expected = list(compatible_vertices(problem))
                self.assertEqual(rank.count, len(expected))
                self.assertEqual([rank.rank(x) for x in expected], list(range(len(expected))))
                for x in set(range(problem.vertices)) - set(expected):
                    with self.assertRaisesRegex(ValueError, "compatible"):
                        rank.rank(x)

    def test_fractional_seed_is_not_rounded(self):
        problem = geometry(3, (-1, -1, -1, 2, 2, 2, -1))
        vertices = list(compatible_vertices(problem))
        rows = [tuple(Fraction(1, 2) for _ in problem.beta) for _ in vertices]
        for x, image in problem.boundary:
            rows[vertices.index(x)] = image
        proof = make_count_proof(problem, rows, transport=True, integral=False)
        self.assertEqual(proof["clearing_scale"]["value"], "2")
        lookup = SeedLookup(problem, proof["function"]["rows"])
        self.assertEqual(lookup[7], (Fraction(1, 2),) * 4)
        full = [evaluate_transport(problem, lookup, x) for x in range(problem.vertices)]
        make_count_proof(problem, full, integral=False, audit_table=True)

    def test_uniform_capacities_keep_seed_scale(self):
        for a in (1, 2, 10**80 + 1):
            proof = make_count_proof(geometry(2, (a, a, -1)), [(0,), (1,), (1,)], transport=True)
            self.assertEqual(proof["clearing_scale"]["value"], "1")
            self.assertEqual(evaluate_count_proof(proof, 3), (Fraction(0),))

    def test_empty_rhs_and_zero_inequality(self):
        for problem in (geometry(1, (1,)), geometry(1, (0,))):
            proof = make_count_proof(problem, [() for _ in compatible_vertices(problem)], transport=True)
            for x in range(problem.vertices):
                self.assertEqual(evaluate_count_proof(proof, x), ())

    def test_incomplete_bad_scale_and_exclusive_constructors_rejected(self):
        problem = geometry(2, (2, 1, -1))
        with self.assertRaisesRegex(ValueError, "entire"):
            make_count_proof(problem, [(0,), (1,)], transport=True)
        with self.assertRaises(ValueError):
            make_count_proof(problem, [(0,), (1,), (1,)], transport=True, kernel=True)
        proof = make_count_proof(problem, [(0,), (1,), (1,)], transport=True)
        for field, value in (("value", "1"), ("minimal", True)):
            bad = copy.deepcopy(proof)
            bad["clearing_scale"][field] = value
            with self.assertRaises(ValueError):
                check_count_proof(bad)

    def test_catalog_accepts_and_counts_transport_seed_edges(self):
        proof = make_count_proof(geometry(2, (2, 1, -1)), [(0,), (1,), (1,)], transport=True)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "proofs.json"
            write_proof_catalog(path, [proof])
            reader = ProofCatalog(path)
            self.assertEqual(reader[0], proof)
            self.assertEqual(reader.verify()["compatible_seed_edges"], 2)
            self.assertEqual(reader.verify()["symbolic_original_cube_edges"], 0)


if __name__ == "__main__":
    unittest.main()
