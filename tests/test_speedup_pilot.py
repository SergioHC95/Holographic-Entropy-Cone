"""Exact speed controls, not whole-corpus coverage or performance promises."""

import random
import sys
import unittest
from fractions import Fraction
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from corpus_derivations import speedups, synthesize  # noqa: E402
from corpus_derivations.diagrams import common_seed  # noqa: E402
from derivation_pilot import recipes  # noqa: E402

from hec.count_proofs import compatible_vertices, geometry, make_count_proof  # noqa: E402


class SpeedupPilotTests(unittest.TestCase):
    def test_exact_bulk_matches_scalar_on_100_random_integer_cut_programs(self):
        rng = random.Random(20261014)
        for coefficients in ((2, 1, -1), (-2, -3, -1, 2, 2, 2, -4)):
            p = geometry(2 if len(coefficients) == 3 else 3, coefficients)
            for trial in range(50):
                terms = set()
                for _ in range(20):
                    ones, zeros = 0, 0
                    for axis in range(p.L):
                        bit = rng.randrange(3)
                        ones |= (bit == 1) << axis
                        zeros |= (bit == 2) << axis
                    terms.add((ones, zeros))
                terms = sorted(terms)
                groups = [
                    [sorted(ref for ref in range(len(terms)) if rng.randrange(2)) for _ in range(cap)] for cap in p.beta
                ]
                groups[0][0] = list(range(len(terms)))  # No unreachable term objects.
                document = recipes.recipe(
                    p, {"kind": recipes.CUTS, "terms": [list(term) for term in terms], "groups": groups}
                )
                original = recipes.CutFunction(document)
                vertices = list(compatible_vertices(p))
                with self.subTest(coefficients=coefficients, trial=trial):
                    self.assertEqual(speedups.cut_rows(document), (p, vertices, 1, [original[x] for x in vertices]))

    def test_empty_disjunction_constant_term_and_non_byte_aligned_domain(self):
        p = geometry(2, (2, 1, -1))
        vertices = list(compatible_vertices(p))
        self.assertEqual(len(vertices), 3)
        for terms, layers, expected in (([], [[]], (0,)), ([[0, 0]], [[0]], (1,))):
            document = recipes.recipe(p, {"kind": recipes.CUTS, "terms": terms, "groups": [layers]})
            self.assertEqual(speedups.cut_rows(document)[3], [expected] * 3)

    def test_invalid_syntax_is_not_hidden_by_vectorized_execution(self):
        p = geometry(2, (2, 1, -1))
        for terms, groups in (([[1, 1]], [[[0]]]), ([[0, 0]], [[[True]]]), ([[0, 0]], [[[]]])):
            document = recipes.recipe(p, {"kind": recipes.CUTS, "terms": terms, "groups": groups})
            with self.assertRaises(ValueError):
                speedups.cut_rows(document)

    @staticmethod
    def seed():
        p = geometry(2, (2, 1, -1))
        proof = make_count_proof(p, [(0,), (1,), (1,)], transport=True)
        return common_seed(proof)

    def test_winner_bytes_and_every_seed_value_match_eager_selection(self):
        p, vertices, scale, rows = self.seed()
        eager = synthesize.choose_definition(p, vertices, scale, rows)
        with patch.object(speedups, "reconstruct", wraps=speedups.reconstruct) as replay:
            chosen = speedups.choose_definition(p, vertices, scale, rows)
        self.assertEqual((chosen.winner, chosen.raw), eager[:2])
        self.assertEqual(chosen.decoded, (p, vertices, scale, rows))
        self.assertEqual(replay.call_count, 1)
        self.assertEqual(sum("pending_full_cube_audit" in item["status"] for item in chosen.methods.values()), 1)
        self.assertFalse(any("accepted" == item["status"] for item in chosen.methods.values()))

    def test_uncompetitive_candidate_skips_all_replays_and_claims_no_acceptance(self):
        p, vertices, scale, rows = self.seed()
        with patch.object(speedups, "reconstruct", side_effect=AssertionError("loser must not replay")):
            chosen = speedups.choose_definition(p, vertices, scale, rows, source_json_bytes=1)
        self.assertIsNone(chosen.decoded)
        self.assertTrue(
            all(value["status"] == "encoded_not_replayed_not_accepted" for value in chosen.methods.values())
        )

    def test_corrupt_chosen_reconstruction_is_rejected_before_independent_acceptance(self):
        p, vertices, scale, rows = self.seed()
        wrong = (p, vertices, scale, [(0,)] * len(vertices))
        with patch.object(speedups, "reconstruct", return_value=wrong):
            with self.assertRaisesRegex(ValueError, "synthesized exact compatible value"):
                speedups.choose_definition(p, vertices, scale, rows)

    def test_exact_decoder_does_not_grant_boundary_or_contraction_acceptance(self):
        p = geometry(2, (2, 1, -1))
        document = recipes.recipe(p, {"kind": recipes.CUTS, "terms": [], "groups": [[[]]]})
        _, _, _, rows = speedups.cut_rows(document)
        with self.assertRaisesRegex(ValueError, "boundary"):
            make_count_proof(p, rows, transport=True)

    def test_empty_output_and_zero_dimensional_domain_are_exact(self):
        p = geometry(1, (0,))
        document = recipes.recipe(p, {"kind": recipes.CUTS, "terms": [], "groups": []})
        self.assertEqual(speedups.cut_rows(document), (p, [0], 1, [()]))

    def test_fractional_seed_keeps_the_unchanged_exact_decoder_and_same_winner(self):
        p = geometry(3, (-1, -1, -1, 2, 2, 2, -1))
        rows = []
        for vertex in range(8):
            a, b, c = ((vertex >> axis) & 1 for axis in range(3))
            rows.append((a * b * (1 - c), a * c * (1 - b), b * c * (1 - a), max(a, b, c)))
        rows[7] = (Fraction(1, 17), 0, 0, 1)
        source = make_count_proof(p, rows, integral=False, transport=True)
        p, vertices, scale, rows = common_seed(source)
        self.assertEqual(scale, 17)
        before = synthesize.choose_definition(p, vertices, scale, rows)
        after = speedups.choose_definition(p, vertices, scale, rows)
        self.assertEqual((after.winner, after.raw), before[:2])
        self.assertEqual(after.decoded, (p, vertices, scale, rows))


if __name__ == "__main__":
    unittest.main()
