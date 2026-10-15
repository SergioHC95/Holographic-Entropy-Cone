"""Tiny full-run promotion fixtures; default CLI still requires all 84690."""

import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

import test_pipeline_batch as fixtures
from corpus_derivations import repository_stage as staging
from corpus_derivations.package_results import RecipeCatalog

from hec.count_proofs import parse_json
from hec.inequality_records import InequalityCatalog
from hec.reconstruction_store import ReconstructionCatalog
from hec.reconstruction_verify import ReconstructionVerifier


class RepositoryStageTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.PipelineBatchTests("test_default_cli_scope_never_accepts_the_fixture_as_all_84690")
        self.fixture.setUp()
        self.temporary = tempfile.TemporaryDirectory(prefix="hec-repository-stage-")
        self.destination = Path(self.temporary.name) / "stage"

    def tearDown(self):
        self.fixture.tearDown()
        self.temporary.cleanup()

    def complete(self):
        self.fixture.run_conversion()
        self.fixture.export()
        return self.fixture.output / "export"

    def stage(self, export, **options):
        # The fixture runs the library synchronously in this test's PID, not
        # a live corpus controller. Never expose this override in the CLI.
        with patch.object(staging, "idle", return_value=True):
            return staging.stage(self.fixture.output, export, self.destination, **options)

    def test_complete_lossless_party_catalogues_bind_and_actually_verify(self):
        export = self.complete()
        source = RecipeCatalog(export / "recipes.json")
        original_frames = {source.read_record(i)[1] for i in range(len(source))}
        report = self.stage(export, **self.fixture.options, _shard_bytes=1)
        self.assertEqual(report["proofs"], 2)
        self.assertEqual(report["frames_recompressed"], 0)
        self.assertFalse(report["production_format_promoted"])
        self.assertFalse(report["facet_or_rank_claims_inherited"])
        self.assertEqual(report["new_mathematical_audits_executed"], 0)
        staged_frames = set()
        checked = 0
        for path in (self.destination / "data").glob("n=*/proofs.json"):
            catalog = ReconstructionCatalog(path)
            InequalityCatalog(path.with_name("inequalities.json")).check_bindings(catalog)
            verifier = ReconstructionVerifier(closure_binary="", cube_binary="")
            try:
                result = catalog.verify(verifier)
                checked += result["proofs"]
            finally:
                verifier.close()
            for entry in catalog.entries:
                shard = path.parent / "proof-shards" / f"{entry['shard']}.proofpack"
                with shard.open("rb") as stream:
                    stream.seek(entry["offset"])
                    staged_frames.add(stream.read(entry["bytes"]))
        self.assertEqual(checked, 2)
        self.assertEqual(staged_frames, original_frames)

    def test_cli_default_scope_refuses_small_fixture_before_creating_output(self):
        export = self.complete()
        with self.assertRaisesRegex(ValueError, "complete bound unified export"):
            self.stage(export)
        self.assertFalse(self.destination.exists())

    def test_live_controller_blocks_without_touching_outputs(self):
        with patch.object(staging, "idle", return_value=False):
            with self.assertRaises(BlockingIOError):
                staging.stage(self.fixture.output, self.fixture.output / "export", self.destination)
        self.assertFalse(self.destination.exists())

    def test_partial_ledger_even_with_old_complete_report_is_not_promotable(self):
        export = self.complete()
        with closing(sqlite3.connect(self.fixture.output / "checkpoint.sqlite3")) as db, db:
            db.execute("DELETE FROM converted WHERE task=0")
        with self.assertRaisesRegex(ValueError, "partial/error"):
            self.stage(export, **self.fixture.options)
        self.assertFalse(self.destination.exists())

    def test_changed_provenance_and_original_nested_destination_fail_closed(self):
        export = self.complete()
        with patch.object(staging, "idle", return_value=True):
            with self.assertRaisesRegex(ValueError, "outside all original"):
                staging.stage(
                    self.fixture.output, export, self.fixture.output / "invalid-stage", **self.fixture.options
                )
        self.assertFalse((self.fixture.output / "invalid-stage").exists())
        scope = parse_json((export / "recipes.json").read_bytes())["scope"]
        provenance = export / f"{scope['conversion_provenance_sha256']}.conversion-provenance.jsonl.zst"
        provenance.write_bytes(provenance.read_bytes() + b"trailing")
        with self.assertRaisesRegex(ValueError, "provenance object changed"):
            self.stage(export, **self.fixture.options)
        self.assertFalse(self.destination.exists())


if __name__ == "__main__":
    unittest.main()
