"""Tiny complete fixtures exercise real spawn workers; no corpus-wide claim."""

import fcntl
import hashlib
import json
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import test_selected_corpus as fixtures

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from corpus_derivations import pipeline_batch as batch  # noqa: E402
from corpus_derivations import pipeline_export  # noqa: E402
from corpus_derivations.package_results import RecipeCatalog  # noqa: E402
from corpus_derivations.pipeline_convert import convert_definition  # noqa: E402

from hec.count_proofs import canonical_json  # noqa: E402
from hec.reconstruction import PIPELINE, ReconstructionProgram  # noqa: E402


class PipelineBatchTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.SelectedCorpusTests(
            "test_final_choices_and_actual_receipts_are_bound_without_writing_sources"
        )
        self.fixture.setUp()
        self.temporary = tempfile.TemporaryDirectory(prefix="hec-pipeline-batch-controls-")
        self.root = Path(self.temporary.name).resolve()
        self.output = self.root / "run"
        self.options = {"_expected_total": 2, "_expected_counts": {"small-n": 2}}

    def tearDown(self):
        self.fixture.tearDown()
        self.temporary.cleanup()

    def prepare(self):
        return batch.prepare(self.fixture.source, self.fixture.synthesis, self.output, **self.options)

    def run_conversion(self):
        self.prepare()
        return batch.execute(self.output, **self.options)

    def export(self):
        return pipeline_export.export(self.output, self.output / "export", **self.options, _shard_bytes=1)

    def test_real_spawn_workers_complete_resume_without_replacing_rows_and_export_one_profile(self):
        value = self.run_conversion()
        self.assertEqual(value["converted"], 2)
        self.assertEqual(value["configured_workers"], 2)  # Private fixture cohort, not the production target.
        self.assertEqual(value["new_exhaustive_original_cube_audits_executed"], 0)
        with closing(sqlite3.connect(self.output / "checkpoint.sqlite3")) as db:
            before = db.execute("SELECT * FROM converted ORDER BY task").fetchall()
        batch.execute(self.output, **self.options)
        with closing(sqlite3.connect(self.output / "checkpoint.sqlite3")) as db:
            self.assertEqual(before, db.execute("SELECT * FROM converted ORDER BY task").fetchall())
        report = self.export()
        self.assertEqual(report["exact_converted_inequality_identities"], 2)
        self.assertEqual(report["converted_variant_definitions"], 3)
        self.assertEqual(report["new_exhaustive_original_cube_audits_executed_by_conversion"], 0)
        self.assertEqual(report["selected_maps_with_executed_source_free_full_cube_audits"], 2)
        self.assertEqual(report["packaging_integrity_checked_frames"], 2)
        self.assertGreaterEqual(report["same_profile_synthesis_json_bytes_saved"], 0)
        self.assertFalse(report["full_goal_complete"])
        reader = RecipeCatalog(self.output / "export/recipes.json")
        for at in range(2):
            proof = reader[at]
            self.assertEqual(proof["function"]["kind"], PIPELINE)
            self.assertEqual(ReconstructionProgram(proof).audit_reference()["scope"], "original-cube-all-edges")

    def test_default_cli_scope_never_accepts_the_fixture_as_all_84690(self):
        self.prepare()
        with self.assertRaisesRegex(ValueError, "scope"):
            batch.load_binding(self.output)
        with self.assertRaisesRegex(ValueError, "scope"):
            batch.execute(self.output)

    def test_live_input_controller_blocks_prepare_before_any_output_is_created(self):
        with (self.fixture.synthesis / "controller.lock").open("r") as owner:
            fcntl.flock(owner, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaises(BlockingIOError):
                self.prepare()
        self.assertFalse(self.output.exists())

    def test_source_nested_and_existing_outputs_are_never_overwritten(self):
        protected = self.fixture.source / "new-but-not-allowed"
        with self.assertRaisesRegex(ValueError, "separate immutable"):
            batch.prepare(self.fixture.source, self.fixture.synthesis, protected, **self.options)
        self.assertFalse(protected.exists())
        self.prepare()
        before = hashlib.sha256((self.output / "run-binding.json").read_bytes()).hexdigest()
        with self.assertRaisesRegex(ValueError, "never overwrite"):
            self.prepare()
        self.assertEqual(before, hashlib.sha256((self.output / "run-binding.json").read_bytes()).hexdigest())

    def test_frozen_code_and_input_bindings_are_checked_on_resume(self):
        self.prepare()
        target = self.output / "implementation/src/hec/reconstruction.py"
        target.write_bytes(target.read_bytes() + b"\n")
        with self.assertRaisesRegex(ValueError, "implementation changed"):
            batch.execute(self.output, **self.options)

    def test_incomplete_and_error_ledgers_do_not_export(self):
        self.prepare()
        db = batch.database(self.output)
        db.close()
        with self.assertRaisesRegex(ValueError, "all conversion tasks"):
            self.export()
        self.assertFalse((self.output / "export").exists())
        batch.execute(self.output, **self.options)
        with closing(sqlite3.connect(self.output / "checkpoint.sqlite3")) as db, db:
            db.execute("INSERT INTO errors VALUES(0,'test unresolved failure')")
        with self.assertRaisesRegex(ValueError, "unresolved conversion failures"):
            self.export()

    def test_completed_row_receipt_corruption_is_not_skipped_on_resume(self):
        self.run_conversion()
        with closing(sqlite3.connect(self.output / "checkpoint.sqlite3")) as db, db:
            row = db.execute("SELECT receipt FROM converted WHERE task=0").fetchone()[0]
            receipt = json.loads(row)
            receipt["new_exhaustive_original_cube_audits_executed"] = False
            db.execute("UPDATE converted SET receipt=? WHERE task=0", (canonical_json(receipt).decode(),))
        with self.assertRaisesRegex(ValueError, "bound task, target or provenance"):
            batch.execute(self.output, **self.options)

    def test_same_profile_size_comparison_can_reject_an_old_format_winner(self):
        with self.fixture.selection() as selected:
            alternative = next(record for record in selected.items() if record.origin == "verified-alternative")
            source = selected.source_definition(alternative.task)
        actual = {record.recipe_sha256: convert_definition(record) for record in (alternative, source)}

        def larger_new_alternative(record, **_):
            value = actual[record.recipe_sha256]
            if record.origin == "verified-alternative":
                # Ranking-only synthetic cost, never inserted or mathematically accepted.
                return replace(value, raw=b"x" * (len(actual[source.recipe_sha256].raw) + 1))
            return value

        with patch.object(batch, "convert_definition", side_effect=larger_new_alternative):
            receipt, _ = batch.convert_pair((alternative, source))
        self.assertEqual(receipt["status"], "verified_source_alternative_not_smaller_in_pipeline")
        self.assertEqual(receipt["chosen_conversion"]["source_origin"], "verified-source")

    def test_memory_reservations_remain_under_shared_64_gib_admission_rule(self):
        with self.fixture.selection() as selected:
            pair = next(batch.inputs(selected))
        budget = batch.memory_budget(pair)
        self.assertGreaterEqual(budget, 1024**3)
        self.assertTrue(batch.derivations.admission_fits({}, budget))
        self.assertFalse(batch.derivations.admission_fits({0: 63 * 1024**3}, budget))


if __name__ == "__main__":
    unittest.main()
