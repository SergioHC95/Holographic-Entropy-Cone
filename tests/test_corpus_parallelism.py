"""Scheduler and immutable checkpoint controls, not corpus proof coverage."""

import json
import sqlite3
import sys
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from corpus_derivations import continue_pipeline, parallelize, run  # noqa: E402

from hec.count_proofs import canonical_json  # noqa: E402


class WorkerPolicyTests(unittest.TestCase):
    def test_explicit_eight_worker_override_does_not_accept_unsafe_or_implicit_counts(self):
        for count in (2, 4, 8):
            self.assertEqual(run.worker_count({"workers": count}), count)
        for count in (True, 0, 1, 3, 16, "8"):
            with self.assertRaises(ValueError):
                run.worker_count({"workers": count})

    def test_eight_small_tasks_fit_but_six_worst_exact_tasks_wait(self):
        small = run.task_memory_budget({"group": "baseline"})
        self.assertTrue(run.admission_fits(dict.fromkeys(range(7), small), small))
        large = run.task_memory_budget({"group": "exact"})
        self.assertTrue(run.admission_fits(dict.fromkeys(range(4), large), large))
        self.assertFalse(run.admission_fits(dict.fromkeys(range(5), large), large))
        self.assertEqual(run.task_memory_budget((0, b"recipe"), [{"group": "exact"}]), large)

    def test_primitive_budget_uses_hash_bound_geometry_not_a_constant_small_estimate(self):
        coefficients = [0] * 63
        for i in range(24):
            coefficients[i] = 1
        coefficients[-1] = -1
        budget = run.task_memory_budget({"group": "primitive", "coefficients": coefficients})
        self.assertEqual(budget, (1 << 24) * 12 + 2 * 1024**3)
        self.assertFalse(run.admission_fits({}, 64 * 1024**3))

    def test_eight_worker_continuation_reports_the_bound_policy(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            driver = continue_pipeline.Continuation(root, {"workers": 8, "initial_source_process_groups": []})
            driver.status("fixture-only-not-a-proof")
            self.assertEqual(json.loads((root / "progress.json").read_bytes())["processing_worker_limit"], 8)

    def run_synthetic_slots(self, group, expected_peak):
        # Thread-only synthetic control jobs, NEVER mathematical proof coverage.
        with tempfile.TemporaryDirectory(prefix="hec-eight-slot-control-") as directory:
            output = Path(directory)
            (output / "run-binding.json").write_bytes(b"binding")
            (output / "manifest.json").write_bytes(b"manifest")
            binding = {"workers": 8, "manifest_sha256": "bound", "implementation": {}, "binaries": {}}
            manifest = [{"task": i, "group": group} for i in range(84690)]
            state, mutex = {"active": 0, "peak": 0}, threading.Lock()

            def synthetic(item):
                with mutex:
                    state["active"] += 1
                    state["peak"] = max(state["peak"], state["active"])
                time.sleep(0.04)
                with mutex:
                    state["active"] -= 1
                report = {
                    "inequality_id": str(item["task"]),
                    "winner": "synthetic-not-a-proof",
                    "source_json_bytes": 1,
                    "full_cube_acceptance": {"checked_edges": 0},
                }
                return report, b"fixture", b"fixture"

            def executor(**kwargs):
                self.assertEqual(kwargs["max_workers"], 8)
                return ThreadPoolExecutor(max_workers=kwargs["max_workers"])

            args = SimpleNamespace(output=output, phase="derive", group="all", limit=16, continue_on_error=False)
            with (
                patch.object(run, "parse_json", side_effect=[binding, manifest]),
                patch.object(run, "digest", return_value="bound"),
                patch.object(run, "derive", side_effect=synthetic),
                patch.object(run, "ProcessPoolExecutor", side_effect=executor),
                patch.object(run, "enforce_rss_limit"),
                patch.object(run, "snapshot"),
            ):
                run.run(args)
            self.assertEqual(state["peak"], expected_peak)
            with closing(sqlite3.connect(output / "checkpoint.sqlite3")) as db:
                self.assertEqual(db.execute("SELECT COUNT(*) FROM results").fetchone()[0], 16)
                self.assertEqual(db.execute("SELECT COUNT(*) FROM errors").fetchone()[0], 0)

    def test_real_controller_loop_admits_eight_small_slots_and_checkpoints_each_fixture(self):
        self.run_synthetic_slots("baseline", 8)

    def test_real_controller_loop_paces_large_tasks_without_dropping_any(self):
        self.run_synthetic_slots("exact", 5)


class InheritanceTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="hec-parallelism-controls-")
        self.root = Path(self.directory.name)
        self.parent, self.output = self.root / "parent", self.root / "child"
        self.parent.mkdir()
        self.output.mkdir()
        (self.parent / "controller.lock").touch()
        (self.parent / "run-binding.json").write_bytes(canonical_json({"total": 2, "workers": 2}))
        self.snapshot = self.output / "inherited-checkpoint.sqlite3"
        with closing(sqlite3.connect(self.snapshot)) as db:
            db.execute("""CREATE TABLE results(task INTEGER PRIMARY KEY,inequality_id TEXT,recipe_sha256 TEXT,
                       winner TEXT,json_bytes INTEGER,source_json_bytes INTEGER,edges INTEGER,
                       compressed BLOB,report TEXT)""")
            db.execute("INSERT INTO results VALUES(0,'iid','sha','recipe',7,10,4,?,?)", (b"recipe", '{"ok":true}'))
            db.commit()
            with closing(sqlite3.connect(self.output / "checkpoint.sqlite3")) as child:
                db.backup(child)
            count, sha = parallelize.records_digest(db)
        self.receipt = {
            "format": parallelize.FORMAT,
            "parent_binding_sha256": run.digest(self.parent / "run-binding.json"),
            "manifest_sha256": "manifest",
            "new_workers": 8,
            "inherited_results": count,
            "inherited_results_sha256": sha,
            "inherited_snapshot_sha256": run.digest(self.snapshot),
        }
        self.binding = {
            "manifest_sha256": "manifest",
            "workers": 8,
            "checkpoint_parent": {
                "root": str(self.parent),
                "binding_sha256": self.receipt["parent_binding_sha256"],
            },
        }
        self.save_receipt()

    def save_receipt(self):
        (self.output / "inheritance.json").write_bytes(canonical_json(self.receipt))
        self.binding["checkpoint_parent"]["receipt_sha256"] = run.digest(self.output / "inheritance.json")

    def tearDown(self):
        self.directory.cleanup()

    def test_preserves_prefix_exactly_while_allowing_new_completed_rows(self):
        self.assertEqual(parallelize.validate_inheritance(self.output, self.binding)["inherited_results"], 1)
        with closing(sqlite3.connect(self.output / "checkpoint.sqlite3")) as db:
            db.execute(
                "INSERT INTO results SELECT 1,inequality_id,recipe_sha256,winner,json_bytes,"
                "source_json_bytes,edges,compressed,report FROM results WHERE task=0"
            )
            db.commit()
        parallelize.validate_inheritance(self.output, self.binding)

    def test_removed_or_edited_completed_proofs_are_rejected(self):
        with closing(sqlite3.connect(self.output / "checkpoint.sqlite3")) as db:
            db.execute("UPDATE results SET report='changed' WHERE task=0")
            db.commit()
        with self.assertRaisesRegex(ValueError, "removed or overwritten"):
            parallelize.validate_inheritance(self.output, self.binding)

    def test_changed_snapshot_or_receipt_is_rejected(self):
        with self.snapshot.open("ab") as stream:
            stream.write(b"tamper")
        with self.assertRaisesRegex(ValueError, "checkpoint changed"):
            parallelize.validate_inheritance(self.output, self.binding)

    def test_changed_worker_limit_or_parent_binding_is_rejected(self):
        self.binding["workers"] = 4
        with self.assertRaisesRegex(ValueError, "handoff binding"):
            parallelize.validate_inheritance(self.output, self.binding)

    def test_live_parent_cannot_be_forked_or_overwritten(self):
        destination = self.root / "new-generation"
        args = SimpleNamespace(source=self.parent, output=destination, parent_pgid=123, workers=8)
        with patch.object(continue_pipeline, "idle", return_value=False):
            with self.assertRaisesRegex(RuntimeError, "surviving worker"):
                parallelize.fork(args)
        self.assertFalse(destination.exists())

    def test_default_cli_scope_does_not_accept_partial_fixture(self):
        destination = self.root / "new-generation"
        args = SimpleNamespace(source=self.parent, output=destination, parent_pgid=123, workers=8)
        with patch.object(continue_pipeline, "idle", return_value=True):
            with self.assertRaisesRegex(ValueError, "without narrowing"):
                parallelize.fork(args)

    def test_math_function_changes_cannot_hide_inside_parallelism_refactor(self):
        relative = Path("tools/corpus_derivations/run.py")
        before, after = self.parent / "implementation" / relative, self.root / "checkout" / relative
        before.parent.mkdir(parents=True)
        after.parent.mkdir(parents=True)
        before.write_text("def derive(x):\n return x + 1\ndef run(x):\n return 2\n")
        after.write_text("def derive(x):\n return x + 1\ndef run(x):\n return 8\n")
        binding = {"implementation": {str(relative): run.digest(before)}}
        parallelize.unchanged_mathematics(self.parent, binding, self.root / "checkout")
        after.write_text("def derive(x):\n return x + 2\ndef run(x):\n return 8\n")
        with self.assertRaisesRegex(ValueError, "non-orchestration"):
            parallelize.unchanged_mathematics(self.parent, binding, self.root / "checkout")


if __name__ == "__main__":
    unittest.main()
