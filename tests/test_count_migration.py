import importlib.util
import json
import shutil
import subprocess
import tempfile
import unittest
from fractions import Fraction
from pathlib import Path

import numpy as np

from hec.count_proofs import decode_rows, geometry, make_count_proof

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("count_migration", ROOT / "tools/migrate_count_proofs.py")
MIGRATION = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MIGRATION)


class BooleanMigrationTests(unittest.TestCase):
    def test_positive_scaling_is_explicit_not_lost_in_normalization(self):
        problem = geometry(2, (1, 1, -1))
        source = {"lhs": [["A", 2], ["B", 2]], "rhs": [["AB", 1], ["AB", 1]], "images": ["00", "11", "11", "10"]}
        raw = np.frombuffer(MIGRATION.legacy_minimal(source, problem, 2), dtype=np.uint8)
        self.assertEqual(MIGRATION.audit_boolean(raw, problem, 2)["positive_scale"], "2")
        proof = make_count_proof(problem, MIGRATION.count_rows(raw, problem, np.arange(4), 2), integral=False)
        self.assertEqual(proof["clearing_scale"], {"value": "2", "minimal": True})

    def test_original_snapshot_is_immutable_and_hash_bound(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "original.json"
            source.write_text('{"original":1}')
            target = MIGRATION.archive_original(source, root / "archive")
            self.assertEqual(target.stem, MIGRATION.file_hash(source))
            source.write_text('{"changed":2}')
            self.assertEqual(target.read_text(), '{"original":1}')

    def test_group_normalization_preserves_proof_not_bits(self):
        problem = geometry(2, (2, 3, -2))
        original = {"lhs": [["A", 2], ["B", 3]], "rhs": [["AB", 1], ["AB", 1]], "images": ["00", "11", "11", "01"]}
        packed = MIGRATION.legacy_minimal(original, problem)
        raw = np.frombuffer(packed, dtype=np.uint8)
        self.assertTrue(MIGRATION.audit_boolean(raw, problem)["ok"])
        rows = list(MIGRATION.count_rows(raw, problem, np.arange(4)))
        self.assertEqual(rows, [(0,), (2,), (2,), (1,)])
        proof = make_count_proof(problem, rows, audit_table=True)
        self.assertEqual(
            list(decode_rows(problem, proof["function"]["rows"])), [(1, (0,)), (1, (2,)), (1, (2,)), (1, (1,))]
        )
        # "01" becomes the canonical prefix "10", not an alleged bit-exact copy.

    def test_original_bit_audit_cannot_be_replaced_by_count_audit(self):
        problem = geometry(3, (2, 2, 1, -2, 0, 0, 0))
        record = {
            "lhs": [["A", 2], ["B", 2], ["C", 1]],
            "rhs": [["AB", 1], ["AB", 1]],
            "images": ["00", "11", "11", "10", "00", "11", "11", "01"],
        }
        raw = np.frombuffer(MIGRATION.legacy_minimal(record, problem), dtype=np.uint8)
        # Normalized count images are valid, but the original 10--01 edge has
        # Hamming load 2 on capacity 1. A migration must not conceal that.
        make_count_proof(problem, MIGRATION.count_rows(raw, problem, np.arange(8)))
        with self.assertRaisesRegex(ValueError, "edge violation"):
            MIGRATION.audit_boolean(raw, problem)
        record["lhs"][0][1] = 2.0
        with self.assertRaises(ValueError):
            MIGRATION.legacy_minimal(record, problem)


@unittest.skipUnless(shutil.which("c++") and __import__("os").name == "posix", "offline auditor needs POSIX C++")
class NativeCountAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scratch = tempfile.TemporaryDirectory(prefix="hec-test-count-audit-")
        cls.root = Path(cls.scratch.name)
        cls.binary = cls.root / "audit_counts"
        subprocess.run(
            [
                shutil.which("c++"),
                "-std=c++17",
                "-O3",
                "-Wall",
                "-Wextra",
                str(ROOT / "tools/audit_counts.cpp"),
                "-o",
                str(cls.binary),
            ],
            check=True,
        )

    @classmethod
    def tearDownClass(cls):
        cls.scratch.cleanup()

    def audit(self, problem, rows, scale, width):
        config = self.root / "config.bin"
        counts = self.root / "counts.raw"
        config.write_bytes(MIGRATION._config(problem, scale, width))
        counts.write_bytes(b"".join(int(value * scale).to_bytes(width, "little") for row in rows for value in row))
        process = subprocess.run([str(self.binary), str(config), str(counts), "1"], capture_output=True, text=True)
        return process, json.loads(process.stdout)

    def test_small_rational_table_large_scale_and_bad_boundary(self):
        problem = geometry(2, (2, 1, -1))
        rows = [(0,), (1,), (1,), (Fraction(1, 2),)]
        for scale, width in ((2, 8), (1 << 60, 8), (1 << 100, 16)):
            process, result = self.audit(problem, rows, scale, width)
            self.assertEqual(process.returncode, 0)
            self.assertEqual(result["checked_edges"], 4)
        rows[0] = (1,)
        process, result = self.audit(problem, rows, 2, 8)
        self.assertNotEqual(process.returncode, 0)
        self.assertIn("boundary", result["error"])

    def test_bounds_edges_and_configuration_overflow_fail_closed(self):
        proof = MIGRATION.legacy_minimal(
            {
                "lhs": [["AB", 1], ["AC", 1], ["BC", 1]],
                "rhs": [["A", 1], ["B", 1], ["C", 1], ["ABC", 1]],
                "images": ["0000", "0001", "0001", "1001", "0001", "0101", "0011", "0001"],
            },
            geometry(3, (-1, -1, -1, 1, 1, 1, -1)),
        )
        problem = geometry(3, (-1, -1, -1, 1, 1, 1, -1))
        rows = list(MIGRATION.count_rows(np.frombuffer(proof, dtype=np.uint8), problem, np.arange(8)))
        process, result = self.audit(problem, rows, 1, 8)
        self.assertEqual(process.returncode, 0)
        rows[7] = (1, 1, 1, 1)
        process, result = self.audit(problem, rows, 1, 8)
        self.assertNotEqual(process.returncode, 0)
        self.assertIn("edge violation", result["error"])
        rows[7] = (2, 0, 0, 0)
        process, result = self.audit(problem, rows, 1, 8)
        self.assertNotEqual(process.returncode, 0)
        self.assertIn("bound", result["error"])
        rows[7] = (0, 0, 0, 1)
        process, result = self.audit(problem, rows, 1 << 127, 16)
        self.assertNotEqual(process.returncode, 0)
        self.assertIn("overflow", result["error"])

    def test_large_axes_cover_each_edge_exactly_once(self):
        n = 15
        normal = [0] * ((1 << n) - 1)
        normal[:n] = [1] * n
        normal[-1] = -1
        problem = geometry(n, normal)
        rows = [(vertex.bit_count() % 2,) for vertex in range(problem.vertices)]
        process, result = self.audit(problem, rows, 1, 8)
        self.assertEqual(process.returncode, 0)
        self.assertEqual(result["checked_edges"], n * (1 << (n - 1)))
        self.assertEqual(result["axis_maximum_load_numerators"], ["1"] * n)


if __name__ == "__main__":
    unittest.main()
