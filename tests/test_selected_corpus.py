"""Completed-selection gates for the future full-corpus pipeline conversion."""

import fcntl
import hashlib
import json
import sys
import unittest
from dataclasses import replace
from pathlib import Path

import test_derivation_packaging as fixtures

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from corpus_derivations.pipeline_convert import convert_definition  # noqa: E402
from corpus_derivations.selected_corpus import VerifiedSelection, check_audit  # noqa: E402

from hec.count_proofs import canonical_json, geometry  # noqa: E402
from hec.reconstruction import PIPELINE, ReconstructionProgram  # noqa: E402


class SelectedCorpusTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.DerivationPackagingTests(
            "test_all_tasks_export_one_definition_and_selected_alternative_is_verified"
        )
        self.fixture.setUp()
        self.source, self.synthesis = self.fixture.source.resolve(), self.fixture.synthesis.resolve()
        path = self.synthesis / "run-binding.json"
        binding = json.loads(path.read_bytes())
        source = json.loads((self.source / "run-binding.json").read_bytes())
        binding.update(
            source=str(self.source),
            source_manifest_sha256=source["manifest_sha256"],
            rss_limit_bytes=64 * 1024**3,
        )
        path.write_bytes(canonical_json(binding))

    def tearDown(self):
        self.fixture.tearDown()

    def selection(self):
        return VerifiedSelection(self.source, self.synthesis, _expected_total=2, _expected_counts={"small-n": 2})

    def test_final_choices_and_actual_receipts_are_bound_without_writing_sources(self):
        paths = [root / "checkpoint.sqlite3" for root in (self.source, self.synthesis)]
        before = [hashlib.sha256(path.read_bytes()).hexdigest() for path in paths]
        with self.selection() as selection:
            records = list(selection.items())
            self.assertEqual([record.task for record in records], [0, 1])
            self.assertEqual([record.origin for record in records], ["verified-source", "verified-alternative"])
            self.assertEqual([record.audit_root for record in records], [str(self.source), str(self.synthesis)])
            self.assertEqual(len(selection.records_sha256), 64)
            for record in records:
                self.assertEqual(hashlib.sha256(record.raw).hexdigest(), record.recipe_sha256)
                self.assertEqual(hashlib.sha256(record.audit_receipt).hexdigest(), record.audit_receipt_sha256)
                receipt = json.loads(record.audit_receipt)
                self.assertEqual(receipt["recipe_sha256"], record.recipe_sha256)
                self.assertEqual(receipt["full_cube_acceptance"]["scope"], "original-cube-all-edges")
            self.assertEqual([record.task for record in selection.items({0})], [1])
        self.assertEqual(before, [hashlib.sha256(path.read_bytes()).hexdigest() for path in paths])

    def test_default_scope_rejects_two_case_fixture_as_complete_corpus(self):
        with self.assertRaisesRegex(ValueError, "full approved corpus"):
            VerifiedSelection(self.source, self.synthesis)

    def test_selected_source_and_changed_alternative_convert_with_their_own_audit_provenance(self):
        with self.selection() as selection:
            for record in selection.items():
                converted = convert_definition(record)
                program = ReconstructionProgram(converted.raw)
                receipt = json.loads(converted.receipt)
                self.assertEqual(converted.task, record.task)
                self.assertEqual(json.loads(converted.raw)["function"]["kind"], PIPELINE)
                self.assertEqual(program.identity, converted.proof_id)
                self.assertEqual(program.semantic_identity(), converted.semantic_map_id)
                self.assertEqual(hashlib.sha256(converted.raw).hexdigest(), converted.recipe_sha256)
                self.assertEqual(receipt["source_origin"], record.origin)
                self.assertEqual(receipt["source_mathematical_audit"]["receipt_sha256"], record.audit_receipt_sha256)
                self.assertFalse(receipt["new_exhaustive_original_cube_audit_executed"])
                self.assertEqual(program.audit_reference()["scope"], "original-cube-all-edges")

    def test_conversion_rejects_changed_input_bytes_audit_identity_and_boolean_task(self):
        with self.selection() as selection:
            record = next(selection.items())
        for bad in (
            replace(record, raw=record.raw + b" "),
            replace(record, inequality_id="0" * 64),
            replace(record, task=False),
        ):
            with self.assertRaises(ValueError):
                convert_definition(bad)
        receipt = json.loads(record.audit_receipt)
        receipt["recipe_sha256"] = "0" * 64
        raw = canonical_json(receipt)
        bad = replace(record, audit_receipt=raw, audit_receipt_sha256=hashlib.sha256(raw).hexdigest())
        with self.assertRaisesRegex(ValueError, "wrong identity"):
            convert_definition(bad)

    def test_live_or_locked_synthesis_is_never_competed_with(self):
        with (self.synthesis / "controller.lock").open("r") as owner:
            fcntl.flock(owner, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaises(BlockingIOError):
                self.selection()

    def test_missing_disposition_or_unfinished_alternative_fresh_blocks_conversion(self):
        self.fixture.db.execute("DELETE FROM fresh")
        self.fixture.db.commit()
        with self.assertRaisesRegex(ValueError, "separate source-free full-cube"):
            self.selection()

    def test_report_cannot_substitute_another_source_or_an_unchanged_map(self):
        path = self.synthesis / "run-binding.json"
        original = path.read_bytes()
        binding = json.loads(original)
        binding["source_manifest_sha256"] = "0" * 64
        path.write_bytes(canonical_json(binding))
        with self.assertRaisesRegex(ValueError, "synthesis binding"):
            self.selection()
        path.write_bytes(original)
        report = json.loads(self.fixture.db.execute("SELECT report FROM attempts WHERE task=1").fetchone()[0])
        report["synthesis"]["changed_cells"] = True  # bool is not a count of changed cells.
        self.fixture.db.execute("UPDATE attempts SET report=? WHERE task=1", (canonical_json(report).decode(),))
        self.fixture.db.commit()
        with self.assertRaisesRegex(ValueError, "changed exact map"):
            self.selection()

    def test_alternative_hash_and_cube_receipt_are_not_inherited_from_the_source(self):
        receipt = json.loads(self.fixture.db.execute("SELECT report FROM fresh WHERE task=1").fetchone()[0])
        receipt["recipe_sha256"] = self.fixture.fixture.source_db.execute(
            "SELECT recipe_sha256 FROM results WHERE task=1"
        ).fetchone()[0]
        self.fixture.db.execute("UPDATE fresh SET report=? WHERE task=1", (canonical_json(receipt).decode(),))
        self.fixture.db.commit()
        with self.assertRaisesRegex(ValueError, "wrong identity"):
            self.selection()

    def test_seed_only_and_boolean_coverage_counts_are_rejected(self):
        p = geometry(1, (0,))
        receipt = {
            "task": 0,
            "recipe_sha256": "a" * 64,
            "ok": True,
            "source_tables_read": False,
            "full_cube_acceptance": {
                "ok": True,
                "scope": "original-cube-all-edges",
                "checked_vertices": 1,
                "checked_edges": 0,
            },
        }
        check_audit(receipt, 0, "a" * 64, p)
        receipt["full_cube_acceptance"]["checked_edges"] = False
        with self.assertRaisesRegex(ValueError, "complete exact original-cube"):
            check_audit(receipt, 0, "a" * 64, p)
        receipt["full_cube_acceptance"]["checked_edges"] = 0
        receipt["full_cube_acceptance"]["scope"] = "compatible-seed-only"
        with self.assertRaisesRegex(ValueError, "complete exact original-cube"):
            check_audit(receipt, 0, "a" * 64, p)

    def test_any_recorded_synthesis_error_blocks_a_selection(self):
        self.fixture.db.execute("INSERT INTO errors VALUES('synthesize',0,'test unresolved failure')")
        self.fixture.db.commit()
        with self.assertRaisesRegex(ValueError, "unresolved synthesis errors"):
            self.selection()


if __name__ == "__main__":
    unittest.main()
