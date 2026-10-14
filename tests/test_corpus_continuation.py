"""Continuation sequencing controls; these never admit real corpus workers."""

import fcntl
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from corpus_derivations import continue_pipeline as pipeline  # noqa: E402


class ContinuationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="hec-continuation-controls-")
        self.root = Path(self.directory.name)
        self.source = self.root / "source"
        self.source.mkdir()
        self.db = sqlite3.connect(self.source / "checkpoint.sqlite3")
        self.db.executescript("""
          CREATE TABLE results(task INTEGER PRIMARY KEY);
          CREATE TABLE fresh(task INTEGER PRIMARY KEY,ok INTEGER);
          CREATE TABLE attempts(task INTEGER PRIMARY KEY,status TEXT);
          CREATE TABLE errors(phase TEXT,task INTEGER,error TEXT);
        """)
        self.driver = pipeline.Continuation(self.root, {"initial_source_process_groups": [], "python": sys.executable})

    def tearDown(self):
        self.db.close()
        self.directory.cleanup()

    def count(self, phase):
        with patch.object(pipeline, "EXPECTED_TOTAL", 2):
            return pipeline.counters(self.source, phase)

    def phase(self, phase="derive", start=False):
        with patch.object(pipeline, "EXPECTED_TOTAL", 2):
            self.driver.phase(
                self.source,
                phase,
                "corpus_derivations.run",
                "fresh",
                self.source / "implementation",
                start_if_idle=start,
            )

    def test_complete_counts_do_not_override_a_live_lock(self):
        path = self.source / "controller.lock"
        path.touch()
        with path.open("r") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with patch.object(pipeline, "processes", side_effect=AssertionError("must respect lock first")):
                self.assertFalse(pipeline.idle(self.source, set()))

    def test_owner_birth_and_group_are_checked_without_signalling(self):
        pipeline.atomic_record(self.source / "controller.json", {"pid": 123, "birth": "Wed Oct 14 00:55:14 2026"})
        row = {"pid": 123, "ppid": 1, "pgid": 120, "birth": "Wed Oct 14  00:55:14 2026", "command": "python"}
        groups = set()
        with patch.object(pipeline, "processes", return_value=[row]), patch.object(os, "kill") as signal:
            self.assertFalse(pipeline.idle(self.source, groups))
            self.assertEqual(groups, {120})
            signal.assert_not_called()
        row["birth"] = "Wed Oct 14 01:55:14 2026"
        with patch.object(pipeline, "processes", return_value=[row]):
            self.assertTrue(pipeline.idle(self.source, set()))

    def test_orphan_native_and_process_group_prevent_overlap(self):
        row = {"pid": 123, "pgid": 120, "command": str(self.source / "wide")}
        with patch.object(pipeline, "processes", return_value=[row]):
            self.assertFalse(pipeline.idle(self.source, set()))
            row["command"] = "python -c multiprocessing.spawn"
            self.assertFalse(pipeline.idle(self.source, {120}))
            self.assertTrue(pipeline.idle(self.source, set()))

    def test_unrecorded_matching_controller_is_also_a_risk(self):
        row = {
            "pid": 123,
            "pgid": 120,
            "command": f"python -m corpus_derivations.run --output {self.source} run --phase derive",
        }
        groups = set()
        with patch.object(pipeline, "processes", return_value=[row]):
            self.assertFalse(pipeline.idle(self.source, groups))
            self.assertEqual(groups, {120})

    def test_partial_derive_is_not_restarted_or_treated_as_complete(self):
        self.db.execute("INSERT INTO results VALUES(0)")
        self.db.commit()
        with patch.object(pipeline, "idle", return_value=True), patch.object(self.driver, "command") as command:
            with self.assertRaisesRegex(RuntimeError, "stopped incomplete"):
                self.phase()
            command.assert_not_called()

    def test_zero_alternatives_is_not_a_shortcut_around_full_synthesis(self):
        with self.assertRaisesRegex(ValueError, "every synthesis disposition"):
            self.count("alternative-fresh")
        self.db.executemany("INSERT INTO attempts VALUES(?,?)", [(0, "unchanged"), (1, "unchanged")])
        self.db.commit()
        self.assertEqual(self.count("alternative-fresh"), {"done": 0, "expected": 0, "errors": 0})
        with self.assertRaisesRegex(ValueError, "every derivation"):
            self.count("source-fresh")

    def test_next_phase_admitted_only_when_idle_and_checked_again_after_exit(self):
        self.db.executemany("INSERT INTO results VALUES(?)", [(0,), (1,)])
        self.db.commit()

        def complete(module, args, snapshot):
            self.assertEqual(module, "corpus_derivations.run")
            self.assertEqual(args, ["--output", self.source, "run", "--phase", "fresh"])
            self.assertEqual(snapshot, self.source / "implementation")
            self.db.executemany("INSERT INTO fresh VALUES(?,1)", [(0,), (1,)])
            self.db.commit()

        with (
            patch.object(pipeline, "idle", side_effect=[False, True, True]),
            patch.object(pipeline.time, "sleep"),
            patch.object(self.driver, "status"),
            patch.object(self.driver, "command", side_effect=complete) as command,
        ):
            self.phase("source-fresh", start=True)
            command.assert_called_once()

    def test_successful_but_partial_child_exit_cannot_advance_to_next_stage(self):
        self.db.executemany("INSERT INTO results VALUES(?)", [(0,), (1,)])
        self.db.commit()
        with (
            patch.object(pipeline, "idle", return_value=True),
            patch.object(self.driver, "status"),
            patch.object(self.driver, "command") as command,
        ):
            with self.assertRaisesRegex(RuntimeError, "stopped incomplete"):
                self.phase("source-fresh", start=True)
            command.assert_called_once()

    def test_recorded_errors_block_even_with_complete_counts(self):
        self.db.executemany("INSERT INTO results VALUES(?)", [(0,), (1,)])
        self.db.execute("INSERT INTO errors VALUES('derive',1,'mathematical failure')")
        self.db.commit()
        with patch.object(self.driver, "command") as command:
            with self.assertRaisesRegex(RuntimeError, "recorded errors"):
                self.phase()
            command.assert_not_called()

    def test_phase_completion_is_not_persistent_goal_completion(self):
        self.db.executemany("INSERT INTO results VALUES(?)", [(0,), (1,)])
        self.db.commit()
        with patch.object(pipeline, "idle", return_value=True):
            self.phase()
        state = json.loads((self.root / "progress.json").read_bytes())
        self.assertFalse(state["full_goal_complete"])
        self.assertEqual(state["phase"], "phase-complete")
        self.assertEqual(state["processing_worker_limit"], 2)

    def test_atomic_operational_owner_can_change_after_exclusive_handoff(self):
        path = self.root / "owner.json"
        pipeline.atomic_record(path, {"pid": 1})
        pipeline.atomic_record(path, {"pid": 2})
        self.assertEqual(pipeline.read_json(path), {"pid": 2})
        self.assertFalse(path.with_name("owner.json.next").exists())

    def test_frozen_child_environment_does_not_reuse_mutable_worktree(self):
        snapshot = self.root / "implementation"
        result = pipeline.environment(snapshot)
        self.assertEqual(result["PYTHONPATH"], str(snapshot / "src") + os.pathsep + str(snapshot / "tools"))
        self.assertEqual(result["OPENBLAS_NUM_THREADS"], "1")
        self.assertEqual(result["OMP_NUM_THREADS"], "1")

    def test_failed_phase_command_stops_the_continuation(self):
        child = Mock(pid=123, returncode=9)
        child.poll.return_value = 9
        with patch.object(pipeline.subprocess, "Popen", return_value=child) as launch:
            with self.assertRaisesRegex(RuntimeError, "phase exited 9"):
                self.driver.command("corpus_derivations.run", ["--output", self.source], self.root / "implementation")
        self.assertTrue(launch.call_args.kwargs["start_new_session"])
        self.assertEqual(launch.call_args.kwargs["stdin"], pipeline.subprocess.DEVNULL)

    def test_whole_stage_order_retains_final_review_and_does_not_touch_the_source(self):
        source = self.source
        self.driver.binding.update(source=str(source), source_manifest_sha256="fixed-manifest")
        events = []

        def phase(root, name, module, native_phase, snapshot, *, start_if_idle):
            events.append(name)
            self.assertEqual(start_if_idle, name != "derive")
            self.assertEqual(root, source if name in ("derive", "source-fresh") else self.root / "synthesis")

        def command(module, args, snapshot):
            events.append(module)
            if module == "corpus_derivations.synthesize":
                destination = self.root / "synthesis"
                destination.mkdir()
                pipeline.atomic_record(
                    destination / "run-binding.json",
                    {
                        "source": str(source),
                        "source_manifest_sha256": "fixed-manifest",
                        "workers": 2,
                        "source_total": pipeline.EXPECTED_TOTAL,
                        "rss_limit_bytes": 64 * 1024**3,
                    },
                )
            elif module == "corpus_derivations.package_results":
                destination = self.root / "export"
                destination.mkdir()
                pipeline.atomic_record(destination / "report.json", {"retained_alternatives": 1})
            else:
                self.fail("unplanned stage admitted")

        with (
            patch.object(self.driver, "phase", side_effect=phase),
            patch.object(self.driver, "command", side_effect=command),
        ):
            self.driver.execute()
        self.assertEqual(
            events,
            [
                "derive",
                "source-fresh",
                "corpus_derivations.synthesize",
                "synthesize",
                "alternative-fresh",
                "corpus_derivations.package_results",
            ],
        )
        state = pipeline.read_json(self.root / "progress.json")
        self.assertEqual(state["phase"], "packaged-awaiting-independent-review")
        self.assertFalse(state["full_goal_complete"])
        self.assertFalse(state["additional_synthesis_needed"])


if __name__ == "__main__":
    unittest.main()
