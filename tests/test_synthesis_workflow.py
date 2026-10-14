"""Fixture-only sequencing, hash binding and full-map retention gates."""

import fcntl
import hashlib
import json
import sqlite3
import sys
import tempfile
import unittest
from fractions import Fraction
from pathlib import Path
from unittest.mock import patch

import zstandard as zstd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from corpus_derivations import run, synthesize  # noqa: E402
from corpus_derivations.diagrams import common_seed  # noqa: E402

from hec._count_verify import FullMapVerifier  # noqa: E402
from hec.count_proofs import canonical_json, geometry, inequality_id, make_count_proof  # noqa: E402


def accept_small(p, vertices, d, rows, definition):
    del p, vertices, d, rows
    verifier = FullMapVerifier()
    verifier.binary = None  # Always use the tiny arbitrary-precision fallback.
    try:
        return verifier.verify(definition)
    finally:
        verifier.close()


def fractional_fixture():
    p = geometry(3, (-1, -1, -1, 2, 2, 2, -1))
    rows = []
    for x in range(8):
        a, b, c = ((x >> i) & 1 for i in range(3))
        rows.append((a * b * (1 - c), a * c * (1 - b), b * c * (1 - a), max(a, b, c)))
    rows[7] = (Fraction(1, 17), 0, 0, 1)
    return make_count_proof(p, rows, integral=False, transport=True)


class SynthesisWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="hec-synthesis-gates-")
        self.root = Path(self.temporary.name)
        self.proofs = [
            make_count_proof(geometry(2, (2, 1, -1)), [(0,), (1,), (1,)], transport=True),
            fractional_fixture(),
        ]
        self.expected = {"small-n": 2}
        self.source_db = sqlite3.connect(self.root / "checkpoint.sqlite3")
        self.source_db.executescript("""
          CREATE TABLE results(task INTEGER PRIMARY KEY,inequality_id TEXT UNIQUE,recipe_sha256 TEXT,
            winner TEXT,json_bytes INTEGER,source_json_bytes INTEGER,edges INTEGER,compressed BLOB,report TEXT);
          CREATE TABLE fresh(task INTEGER PRIMARY KEY,ok INTEGER,report TEXT);
          CREATE TABLE errors(phase TEXT,task INTEGER,error TEXT);
        """)
        self.manifest = []
        for task, proof in enumerate(self.proofs):
            p, vertices, d, rows = common_seed(proof)
            acceptance = accept_small(p, vertices, d, rows, proof)
            # Fixture coverage matches the native service's receipt vocabulary.
            # Mathematical acceptance was actually performed immediately above.
            acceptance["scope"] = "original-cube-all-edges"
            raw, iid = canonical_json(proof), inequality_id(p)
            sha = hashlib.sha256(raw).hexdigest()
            self.manifest.append({"task": task, "inequality_id": iid, "group": "baseline", "n": p.n})
            receipt = {
                "task": task,
                "ok": True,
                "source_tables_read": False,
                "recipe_sha256": sha,
                "full_cube_acceptance": acceptance,
            }
            self.source_db.execute(
                "INSERT INTO results VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    task,
                    iid,
                    sha,
                    "explicit-compatible-seed",
                    len(raw),
                    len(raw),
                    p.L * (p.vertices // 2),
                    zstd.ZstdCompressor(write_checksum=True).compress(raw),
                    canonical_json({"seed_scale": str(d)}).decode(),
                ),
            )
            self.source_db.execute("INSERT INTO fresh VALUES(?,1,?)", (task, canonical_json(receipt).decode()))
        self.source_db.commit()
        (self.root / "controller.lock").touch()
        (self.root / "manifest.json").write_bytes(canonical_json(self.manifest))
        binding = {
            "total": 2,
            "workers": 2,
            "scope_counts": self.expected,
            "manifest_sha256": run.digest(self.root / "manifest.json"),
            "implementation": {},
            "binaries": {},
        }
        (self.root / "run-binding.json").write_bytes(canonical_json(binding))
        synthesize.SETTINGS = {"sweeps": 2, "max_work": 50000, "binaries": {"closure": {"path": None}}}

    def tearDown(self):
        self.source_db.close()
        self.temporary.cleanup()

    def source(self):
        # Testing overrides are private library parameters, never CLI options.
        return synthesize.VerifiedSource(self.root, _expected_total=2, _expected_counts=self.expected)

    def item(self, task=1):
        source = self.source()
        try:
            return next(item for item in source.items(set()) if item[0] == task)
        finally:
            source.close()

    def test_complete_source_is_hash_bound_and_read_only(self):
        before = run.digest(self.root / "checkpoint.sqlite3")
        source = self.source()
        try:
            self.assertEqual(len(source.records_sha256), 64)
            self.assertEqual(sorted(item[0] for item in source.items(set())), [0, 1])
            self.assertEqual([item[0] for item in source.items({1})], [0])
        finally:
            source.close()
        self.assertEqual(before, run.digest(self.root / "checkpoint.sqlite3"))

    def test_real_default_scope_rejects_the_two_case_fixture(self):
        with self.assertRaisesRegex(ValueError, "full approved corpus"):
            synthesize.VerifiedSource(self.root)

    def test_incomplete_source_free_pass_blocks_synthesis(self):
        self.source_db.execute("DELETE FROM fresh WHERE task=1")
        self.source_db.commit()
        with self.assertRaisesRegex(ValueError, "complete derivation AND source-free"):
            self.source()

    def test_active_source_controller_lock_is_not_adopted_or_competed_with(self):
        with (self.root / "controller.lock").open("r") as owner:
            fcntl.flock(owner, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaises(BlockingIOError):
                self.source()

    def test_changed_recipe_and_receipt_hashes_fail_closed(self):
        self.source_db.execute("UPDATE results SET recipe_sha256=? WHERE task=1", ("0" * 64,))
        self.source_db.commit()
        with self.assertRaisesRegex(ValueError, "hash or length"):
            self.source()

    def test_incomplete_cube_receipt_is_not_counted_as_full_coverage(self):
        row = self.source_db.execute("SELECT report FROM fresh WHERE task=1").fetchone()[0]
        receipt = json.loads(row)
        receipt["full_cube_acceptance"]["checked_edges"] -= 1
        self.source_db.execute("UPDATE fresh SET report=? WHERE task=1", (canonical_json(receipt).decode(),))
        self.source_db.commit()
        with self.assertRaisesRegex(ValueError, "complete original cube"):
            self.source()

    def test_retained_alternative_changes_map_and_is_strictly_smaller_and_verified(self):
        with patch.object(run, "accept", side_effect=accept_small):
            report, packed = synthesize.attempt(self.item())
        self.assertEqual(report["status"], "accepted_strictly_smaller_alternative")
        self.assertGreater(report["synthesis"]["changed_cells"], 0)
        self.assertLess(report["alternative_json_bytes"], report["source_json_bytes"])
        self.assertEqual(report["full_cube_acceptance"]["checked_edges"], 12)
        raw = zstd.ZstdDecompressor().decompress(packed)
        self.assertEqual(hashlib.sha256(raw).hexdigest(), report["alternative_recipe_sha256"])
        p, vertices, d, rows = run.reconstruct(json.loads(raw))
        accept_small(p, vertices, d, rows, run.standard(p, d, rows))

    def test_mathematical_rejection_cannot_be_replaced_by_syntax_or_hashes(self):
        with patch.object(run, "accept", return_value={"ok": False}):
            with self.assertRaisesRegex(ValueError, "independent full-cube acceptance"):
                synthesize.attempt(self.item())

    def test_unchanged_source_and_budget_exhaustion_are_not_alternative_proofs(self):
        report, packed = synthesize.attempt(self.item(0))
        self.assertEqual(report["status"], "unchanged_source_no_alternative")
        self.assertIsNone(packed)
        synthesize.SETTINGS["max_work"] = 1
        report, packed = synthesize.attempt(self.item())
        self.assertEqual(report["status"], "incomplete_synthesis_budget_not_a_proof")
        self.assertIsNone(packed)

    def test_no_size_improvement_is_not_retained(self):
        item = self.item()
        with patch.object(synthesize, "choose_definition", return_value=("mock", item[1], {}, self.proofs[1])):
            report, packed = synthesize.attempt(item)
        self.assertEqual(report["status"], "changed_seed_without_strict_description_improvement_not_retained")
        self.assertIsNone(packed)

    def test_frame_lengths_and_trailing_data_are_not_silently_accepted(self):
        frame = zstd.ZstdCompressor().compress(b"complete recipe")
        self.assertEqual(synthesize.decode_frame(frame, 15), b"complete recipe")
        with self.assertRaisesRegex(ValueError, "mismatched declared length"):
            synthesize.decode_frame(frame, 14)
        with self.assertRaises(zstd.ZstdError):
            synthesize.decode_frame(frame + b"unindexed trailing bytes", 15)


if __name__ == "__main__":
    unittest.main()
