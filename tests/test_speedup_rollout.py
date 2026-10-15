"""Private two-case rollout/drain controls; never production scope coverage."""

import json
import sqlite3
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import test_selected_corpus as fixtures
import test_synthesis_workflow as math_controls

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from corpus_derivations import run as derivations  # noqa: E402
from corpus_derivations import speedup_rollout as rollout  # noqa: E402
from corpus_derivations import synthesize  # noqa: E402


class SpeedupRolloutTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.SelectedCorpusTests(
            "test_final_choices_and_actual_receipts_are_bound_without_writing_sources"
        )
        self.fixture.setUp()
        self.math = self.fixture.fixture.fixture
        self.parent = self.fixture.synthesis
        self.directory = tempfile.TemporaryDirectory(prefix="hec-speedup-rollout-controls-")
        self.output = Path(self.directory.name) / "generation"

    def tearDown(self):
        self.fixture.tearDown()
        self.directory.cleanup()

    def fork(self):
        with patch.object(rollout, "idle", return_value=True):
            return rollout.fork(
                self.parent, self.output, parent_pgid=123, _expected_total=2, _expected_counts={"small-n": 2}
            )

    def test_fork_preserves_every_attempt_fresh_receipt_and_blob_without_source_changes(self):
        before = derivations.digest(self.parent / "checkpoint.sqlite3")
        receipt = self.fork()
        self.assertEqual(receipt["inherited_counts"], {"attempts": 2, "fresh": 1, "errors": 0})
        self.assertEqual(receipt["workers"], 2)
        settings = json.loads((self.output / "run-binding.json").read_bytes())
        self.assertEqual(settings["optimization"], synthesize.OPTIMIZATION)
        rollout.validate_inheritance(self.output, settings)
        self.assertEqual(before, derivations.digest(self.parent / "checkpoint.sqlite3"))
        with self.assertRaisesRegex(ValueError, "never overwrite"):
            self.fork()

    def test_changed_inherited_proof_or_receipt_is_never_silently_retried(self):
        self.fork()
        settings = json.loads((self.output / "run-binding.json").read_bytes())
        with closing(sqlite3.connect(self.output / "checkpoint.sqlite3")) as db, db:
            db.execute("UPDATE attempts SET report='{}' WHERE task=0")
        with self.assertRaisesRegex(ValueError, "removed or overwritten"):
            rollout.validate_inheritance(self.output, settings)

    def test_live_parent_blocks_before_creating_a_generation(self):
        with patch.object(rollout, "idle", return_value=False):
            with self.assertRaisesRegex(BlockingIOError, "no competing rollout"):
                rollout.fork(self.parent, self.output, parent_pgid=123)
        self.assertFalse(self.output.exists())

    def test_unrelated_pending_reconstruction_code_is_preserved_from_parent(self):
        relative = "src/hec/reconstruction.py"
        old = self.parent / "implementation" / relative
        old.parent.mkdir(parents=True, exist_ok=True)
        saved = b"PARENT_ONLY_FIXTURE = True\n"
        old.write_bytes(saved)
        binding = json.loads((self.parent / "run-binding.json").read_bytes())
        binding["implementation"][relative] = derivations.digest(old)
        (self.parent / "run-binding.json").write_bytes(derivations.canonical_json(binding))
        receipt = self.fork()
        self.assertEqual((self.output / "implementation" / relative).read_bytes(), saved)
        self.assertEqual(receipt["preserved_inactive_parent_files"][relative], derivations.digest(old))

    def test_optimized_attempt_is_same_mathematical_map_and_saved_recipe(self):
        item = self.math.item(1)
        previous = synthesize.SETTINGS
        try:
            settings = {"sweeps": 2, "max_work": 50000, "binaries": {"closure": {"path": None}}}
            synthesize.SETTINGS = settings
            with patch.object(derivations, "accept", side_effect=math_controls.accept_small):
                old, a = synthesize.attempt(item)
                synthesize.SETTINGS = {**settings, "optimization": synthesize.OPTIMIZATION}
                new, b = synthesize.attempt(item)
            self.assertEqual(a, b)
            for key in ("winner", "status", "alternative_recipe_sha256", "alternative_json_bytes", "synthesis"):
                self.assertEqual(old[key], new[key])
            self.assertEqual(new["optimization"], synthesize.OPTIMIZATION)
            self.assertEqual(
                new["encodings"][new["winner"]]["status"], "exact_seed_replay_and_independent_full_cube_verified"
            )
        finally:
            synthesize.SETTINGS = previous

    def test_optimized_fresh_still_executes_independent_acceptance_and_binds_hash(self):
        task, raw, sha, iid = self.math.item(1)
        with patch.object(derivations, "accept", side_effect=math_controls.accept_small) as acceptance:
            receipt = synthesize.optimized_fresh((task, raw, sha, iid))
        acceptance.assert_called_once()
        self.assertFalse(receipt["source_tables_read"])
        self.assertEqual(receipt["recipe_sha256"], sha)
        with self.assertRaisesRegex(ValueError, "changed before"):
            synthesize.optimized_fresh((task, raw + b" ", sha, iid))

    def run_drain(self, *, preexisting):
        db = self.fixture.fixture.db
        saved = {
            task: (json.loads(report), packed)
            for task, report, packed in db.execute("SELECT task,report,compressed FROM attempts")
        }
        db.execute("DELETE FROM attempts")
        db.execute("DELETE FROM fresh")
        db.commit()
        binding = json.loads((self.parent / "run-binding.json").read_bytes())
        items = [self.math.item(task) for task in range(2)]
        source = SimpleNamespace(
            binding={"workers": 2},
            records_sha256=binding["source_records_sha256"],
            manifest=self.math.manifest,
            items=lambda done: iter(items),
            close=Mock(),
        )
        pause = self.parent / "pause-after-inflight.json"
        if preexisting:
            pause.touch()

        def action(item):
            pause.touch(exist_ok=True)
            return saved[item[0]]

        def pool(**kwargs):
            return ThreadPoolExecutor(max_workers=kwargs["max_workers"])

        with (
            patch.object(synthesize, "EXPECTED_TOTAL", 2),
            patch.object(synthesize, "VerifiedSource", return_value=source),
            patch.object(synthesize, "ProcessPoolExecutor", side_effect=pool),
            patch.object(synthesize, "attempt", side_effect=action) as attempts,
            patch.object(derivations, "enforce_rss_limit"),
            patch.object(synthesize, "progress"),
        ):
            synthesize.execute(SimpleNamespace(output=self.parent, phase="synthesize", limit=None))
        completed = db.execute("SELECT COUNT(*) FROM attempts").fetchone()[0]
        self.assertEqual(completed, attempts.call_count)
        source.close.assert_called_once()
        return completed

    def test_drain_request_before_admission_starts_zero_tasks(self):
        self.assertEqual(self.run_drain(preexisting=True), 0)

    def test_drain_commits_every_inflight_result_before_returning(self):
        self.assertEqual(self.run_drain(preexisting=False), 2)


if __name__ == "__main__":
    unittest.main()
