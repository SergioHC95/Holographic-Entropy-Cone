"""Fixture-only final coverage and immutable packaging checks."""

import hashlib
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import test_synthesis_workflow as fixtures
import zstandard as zstd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from corpus_derivations import package_results, run, synthesize  # noqa: E402

from hec.count_proofs import canonical_json, parse_json  # noqa: E402


class DerivationPackagingTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.SynthesisWorkflowTests("test_complete_source_is_hash_bound_and_read_only")
        self.fixture.setUp()
        self.source, self.synthesis = self.fixture.root, self.fixture.root / "synthesis"
        self.synthesis.mkdir()
        (self.synthesis / "controller.lock").touch()
        for task in range(2):
            row = self.fixture.source_db.execute("SELECT json_bytes FROM results WHERE task=?", (task,)).fetchone()
            metadata = {
                "winner": "explicit-compatible-seed",
                "seed_scale": "1" if task == 0 else "17",
                "source_json_bytes": row[0],
                "winner_json_bytes": row[0],
                "methods": {"explicit-compatible-seed": {"status": "exact_equivalence_to_full_cube_verified_map"}},
            }
            self.fixture.source_db.execute(
                "UPDATE results SET report=? WHERE task=?", (canonical_json(metadata).decode(), task)
            )
        self.fixture.source_db.commit()
        source = self.fixture.source()
        try:
            binding = {
                "source_total": 2,
                "workers": 2,
                "method": synthesize.METHOD,
                "source_records_sha256": source.records_sha256,
                "implementation": {},
                "binaries": {},
            }
        finally:
            source.close()
        (self.synthesis / "run-binding.json").write_bytes(canonical_json(binding))
        self.db = synthesize.database(self.synthesis)
        for task in range(2):
            with patch.object(run, "accept", side_effect=fixtures.accept_small):
                report, data = synthesize.attempt(self.fixture.item(task))
            self.db.execute(
                "INSERT INTO attempts VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    task,
                    report["inequality_id"],
                    report["source_recipe_sha256"],
                    report["status"],
                    report["source_json_bytes"],
                    report["alternative_json_bytes"],
                    report.get("alternative_recipe_sha256"),
                    data,
                    canonical_json(report).decode(),
                ),
            )
            if data is not None:
                raw = zstd.ZstdDecompressor().decompress(data)
                p, vertices, scale, rows = run.reconstruct(parse_json(raw))
                acceptance = fixtures.accept_small(p, vertices, scale, rows, run.standard(p, scale, rows))
                acceptance["scope"] = "original-cube-all-edges"
                receipt = {
                    "task": task,
                    "ok": True,
                    "recipe_sha256": report["alternative_recipe_sha256"],
                    "source_tables_read": False,
                    "full_cube_acceptance": acceptance,
                }
                self.db.execute("INSERT INTO fresh VALUES(?,1,?)", (task, canonical_json(receipt).decode()))
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.fixture.tearDown()

    def export(self, target=None):
        return package_results.export(
            self.source,
            self.synthesis,
            target or self.source / "export",
            _expected_total=2,
            _expected_counts={"small-n": 2},
            _shard_bytes=1,
        )

    def test_all_tasks_export_one_definition_and_selected_alternative_is_verified(self):
        before = run.digest(self.source / "checkpoint.sqlite3")
        report = self.export()
        self.assertEqual(report["scope"]["proofs"], 2)
        self.assertEqual(report["retained_alternatives"], 1)
        self.assertEqual(report["alternative_fresh_full_cube_verified"], 1)
        self.assertGreater(report["synthesis_json_bytes_saved"], 0)
        self.assertEqual(report["packaging_integrity_checked_frames"], 2)
        self.assertEqual(before, run.digest(self.source / "checkpoint.sqlite3"))
        catalog = package_results.RecipeCatalog(self.source / "export/recipes.json")
        self.assertEqual([e["origin"] for e in catalog.entries], ["verified-source", "verified-alternative"])
        self.assertEqual(len(catalog), 2)
        for index in range(2):
            p, vertices, scale, rows = run.reconstruct(catalog[index])
            fixtures.accept_small(p, vertices, scale, rows, run.standard(p, scale, rows))

    def test_default_export_scope_never_accepts_fixture_as_full_corpus(self):
        with self.assertRaisesRegex(ValueError, "full approved corpus"):
            package_results.export(self.source, self.synthesis, self.source / "export")

    def test_missing_synthesis_disposition_and_fresh_receipt_prevent_export(self):
        self.db.execute("DELETE FROM attempts WHERE task=0")
        self.db.commit()
        with self.assertRaisesRegex(ValueError, "every source task"):
            self.export()

    def test_unverified_alternative_is_not_exported(self):
        self.db.execute("DELETE FROM fresh")
        self.db.commit()
        with self.assertRaisesRegex(ValueError, "separate source-free fresh audit"):
            self.export()

    def test_incomplete_alternative_cube_coverage_is_rejected(self):
        receipt = json.loads(self.db.execute("SELECT report FROM fresh WHERE task=1").fetchone()[0])
        receipt["full_cube_acceptance"]["checked_edges"] -= 1
        self.db.execute("UPDATE fresh SET report=? WHERE task=1", (canonical_json(receipt).decode(),))
        self.db.commit()
        with self.assertRaisesRegex(ValueError, "complete original-cube coverage"):
            self.export()

    def test_overlapping_catalog_ranges_and_shard_corruption_are_rejected(self):
        self.export()
        path = self.source / "export/recipes.json"
        original = json.loads(path.read_bytes())
        bad = json.loads(path.read_bytes())
        bad["entries"][0]["offset"] = 1
        altered = self.source / "export/bad.json"
        altered.write_bytes(canonical_json(bad))
        with self.assertRaises(ValueError):
            package_results.RecipeCatalog(altered)
        entry = original["entries"][0]
        shard = self.source / f"export/recipe-shards/{entry['shard']}.recipepack"
        encoded = bytearray(shard.read_bytes())
        encoded[0] ^= 1
        shard.write_bytes(encoded)
        catalog = package_results.RecipeCatalog(path)
        with self.assertRaisesRegex(ValueError, "SHA256/length"):
            catalog[0]

    def test_existing_export_is_never_overwritten(self):
        self.export()
        target = self.source / "export/recipes.json"
        before = hashlib.sha256(target.read_bytes()).hexdigest()
        with self.assertRaisesRegex(ValueError, "never replace"):
            self.export()
        self.assertEqual(before, hashlib.sha256(target.read_bytes()).hexdigest())


if __name__ == "__main__":
    unittest.main()
