"""Same exact maps, ordering, denominator and charged work as Python reference."""

import copy
import hashlib
import os
import random
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from corpus_derivations.native_smooth import NativeSmoother, supported
from corpus_derivations.pipeline_import import NativePipelineAuditor
from corpus_derivations.simplify import WorkLimit, smooth

from hec.count_proofs import compatible_vertices, geometry

ROOT = Path(__file__).resolve().parents[1]


def mmi(scale=1, *, wide=False):
    p = geometry(3, (-1, -1, -1, 1024, 1024, 1023, -1) if wide else (-1, -1, -1, 2, 2, 2, -1))
    vertices = list(compatible_vertices(p))
    rows = [
        tuple(scale * value for value in (a * b * (1 - c), a * c * (1 - b), b * c * (1 - a), max(a, b, c)))
        for x in vertices
        for a, b, c in [tuple((x >> axis) & 1 for axis in range(3))]
    ]
    if scale > 1:
        rows[7] = (scale - 1, scale - 2, scale - 3, scale) if wide else (1, 0, 0, scale)
    return p, vertices, scale, rows


@unittest.skipUnless(shutil.which("c++"), "native exact smoothing control needs C++17")
class NativeSmoothingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="hec-exact-smoothing-test-")
        cls.binary = Path(os.environ.get("HEC_SMOOTHER_BINARY", str(Path(cls.temporary.name) / "smoother")))
        if not cls.binary.is_file():
            subprocess.run(
                [
                    "c++",
                    "-O3",
                    "-std=c++17",
                    str(ROOT / "tools/corpus_derivations/smooth_exact.cpp"),
                    "-o",
                    str(cls.binary),
                ],
                check=True,
            )
        cls.sha = hashlib.sha256(cls.binary.read_bytes()).hexdigest()

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def setUp(self):
        self.engine = NativeSmoother(self.binary, self.sha)

    def tearDown(self):
        self.engine.close()

    def compare(self, values, **settings):
        original = copy.deepcopy(values[-1])
        expected = smooth(*values, **settings)
        actual = self.engine.smooth(*values, **settings)
        self.assertEqual(actual, expected)  # Includes every statistic/work charge.
        self.assertEqual(values[-1], original)
        return actual

    def test_integral_fractional_and_wide_coupled_arithmetic(self):
        for scale in (1, 17, (1 << 55) + 1, (1 << 63) - 1):
            for wide in (False, True):
                for sweeps in (1, 2, 8):
                    self.compare(mmi(scale, wide=wide), sweeps=sweeps)

    def test_50_random_complete_feasible_seeds_match_every_value_and_statistic(self):
        rng = random.Random(20261015)
        p = geometry(3, (-1, -1, -1, 4, 4, 4, -1))
        vertices = list(compatible_vertices(p))
        for _ in range(50):
            scale = rng.choice((1, 2, 17, (1 << 31) - 1, (1 << 55) + 1))
            rows = [tuple(rng.randrange(scale + 1) for _ in p.beta) for _ in vertices]
            for x, image in p.boundary:
                rows[vertices.index(x)] = tuple(scale * value for value in image)
            rows[7] = (1, *rows[7][1:])  # An explicitly minimal denominator.
            self.compare((p, vertices, scale, rows))

    def test_identical_work_limit_and_private_helper_survives_budget_exhaustion(self):
        values = mmi(17)
        full = smooth(*values)
        for budget in (1, 3, 7, 31, full[2]["work"] - 1):
            for action in (smooth, self.engine.smooth):
                with self.assertRaises(WorkLimit):
                    action(*values, max_work=budget)
        self.compare(values, max_work=full[2]["work"])

    def test_zero_geometry_and_empty_output_are_complete_images(self):
        for p in (geometry(1, (0,)), geometry(1, (1,))):
            vertices = list(compatible_vertices(p))
            self.compare((p, vertices, 1, [() for _ in vertices]))

    def test_unsupported_precision_never_truncates_or_claims_acceptance(self):
        values = mmi(1 << 90)
        self.assertFalse(supported(*values))
        with self.assertRaisesRegex(ValueError, "arbitrary-precision"):
            self.engine.smooth(*values)
        self.assertIsNone(self.engine.process)
        self.assertEqual(smooth(*values)[2]["method"], "exact-tight-component-smoothing/experimental-1")

    def test_incomplete_domain_nonminimal_scale_and_wrong_bounds_rejected(self):
        p, vertices, scale, rows = mmi(17)
        for v, d, r in ((vertices[:-1], scale, rows[:-1]), (vertices, 34, [tuple(2 * x for x in row) for row in rows])):
            with self.assertRaises(ValueError):
                self.engine.smooth(p, v, d, r)
        bad = copy.deepcopy(rows)
        bad[7] = (18, 0, 0, 17)
        with self.assertRaises(ValueError):
            self.engine.smooth(p, vertices, scale, bad)
        self.assertIsNone(self.engine.process)

    def test_binary_identity_is_explicit_and_checked_again_before_use(self):
        with self.assertRaisesRegex(ValueError, "bound"):
            NativeSmoother(self.binary, "0" * 64)
        self.engine.sha256 = "0" * 64
        with self.assertRaisesRegex(ValueError, "bound"):
            self.engine.smooth(*mmi())
        self.assertIsNone(self.engine.process)

    def test_actual_candidate_receives_independent_original_cube_audit(self):
        binary = os.environ.get("HEC_WIDE_AUDITOR")
        if not binary:
            self.skipTest("set HEC_WIDE_AUDITOR for the independent full-cube control")
        p, vertices, _, _ = values = mmi(17)
        scale, rows, _ = self.compare(values)
        verifier = NativePipelineAuditor(binary, hashlib.sha256(Path(binary).read_bytes()).hexdigest())
        try:
            audit = verifier.verify(p, vertices, scale, rows)
        finally:
            verifier.close()
        self.assertEqual((audit["checked_vertices"], audit["checked_edges"]), (8, 12))
        self.assertEqual(audit["scope"], "original-cube-all-edges")


if __name__ == "__main__":
    unittest.main()
