"""Backend dispatch, evidence, fresh-audit isolation and safe orphan controls."""

import copy
import io
import os
import struct
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import test_synthesis_workflow as fixtures
from corpus_derivations import continue_pipeline, speedup_rollout, synthesize
from corpus_derivations import smoothing_runtime as runtime
from corpus_derivations.native_smooth import NativeSmoother, packed
from corpus_derivations.simplify import WorkLimit, smooth
from test_native_smoothing import mmi

from hec.count_proofs import canonical_json, parse_json

ROOT = Path(__file__).resolve().parents[1]


def config():
    return {
        "policy": runtime.POLICY,
        "path": "/private/test-only/smoother",
        "sha256": "0" * 64,
        "source_sha256": "1" * 64,
        "min_cells": runtime.MIN_CELLS,
    }


class SmoothingRuntimeTests(unittest.TestCase):
    def tearDown(self):
        runtime.close()

    def test_tiny_reference_has_no_native_startup_or_acceptance_cache(self):
        values = mmi(17)
        settings = {"sweeps": 2, "max_work": 50_000_000, "smoothing_backend": config()}
        with patch.object(runtime, "NativeSmoother", side_effect=AssertionError("tiny seed spawned helper")):
            action, metadata = runtime.operation(settings, *values)
            self.assertEqual(action(), smooth(*values))
        self.assertEqual(metadata["implementation"], "python-reference")
        self.assertFalse(metadata["mathematical_acceptance_cached"])

    def test_unsupported_precision_uses_exact_reference_without_truncation(self):
        values = mmi(1 << 90)
        with patch.object(runtime, "MIN_CELLS", 1), patch.object(runtime, "NativeSmoother") as native:
            settings = {"sweeps": 2, "max_work": 50_000_000, "smoothing_backend": config()}
            action, metadata = runtime.operation(settings, *values)
            self.assertEqual(action(), smooth(*values))
        native.assert_not_called()
        self.assertIn("no_truncation", metadata["reason"])

    def test_native_helper_is_lazy_reused_and_cannot_change_binding_inside_worker(self):
        values = mmi(17)
        helper = Mock()
        helper.smooth.return_value = smooth(*values)
        with (
            patch.object(runtime, "MIN_CELLS", 1),
            patch.object(runtime, "NativeSmoother", return_value=helper) as native,
        ):
            settings = {"sweeps": 2, "max_work": 50_000_000, "smoothing_backend": config()}
            for _ in range(2):
                action, metadata = runtime.operation(settings, *values)
                self.assertEqual(action(), smooth(*values))
                self.assertEqual(metadata["binary_sha256"], "0" * 64)
            native.assert_called_once()
            settings["smoothing_backend"]["sha256"] = "2" * 64
            with self.assertRaisesRegex(ValueError, "changed inside"):
                runtime.operation(settings, *values)

    def test_strict_configuration_rejects_unknown_fields_and_false_thresholds(self):
        for key, value in (
            ("extra", True),
            ("min_cells", True),
            ("min_cells", 0),
            ("path", "relative"),
            ("sha256", "z" * 64),
        ):
            bad = {**config(), key: value}
            with self.assertRaises(ValueError):
                runtime.parameters(bad)

    def test_orphan_native_helper_blocks_idle_even_without_a_live_owner(self):
        with tempfile.TemporaryDirectory(prefix="hec-native-orphan-test-") as directory:
            root = Path(directory)
            (root / "controller.lock").touch()
            orphan = {"pid": 987654, "ppid": 1, "pgid": 987654, "command": str(root / "smoother")}
            with patch.object(continue_pipeline, "processes", return_value=[orphan]):
                self.assertFalse(continue_pipeline.idle(root, set()))

    def test_idle_source_review_allows_only_the_additional_helper_identity(self):
        after = (ROOT / "tools/corpus_derivations/continue_pipeline.py").read_bytes()
        before = after.replace(b'("wide", "narrow", "closure", "smoother")', b'("wide", "narrow", "closure")')
        self.assertNotEqual(before, after)
        with tempfile.TemporaryDirectory(prefix="hec-idle-review-test-") as directory:
            a, b = Path(directory) / "before.py", Path(directory) / "after.py"
            a.write_bytes(before)
            b.write_bytes(after)
            speedup_rollout.review_idle_change(a, b)
            b.write_bytes(after.replace(b"time.sleep(30)", b"time.sleep(31)", 1))
            with self.assertRaisesRegex(ValueError, "more than"):
                speedup_rollout.review_idle_change(a, b)

    def test_actual_reviewed_controls_and_tampered_cube_or_budget_flags(self):
        directory = os.environ.get("HEC_NATIVE_SMOOTH_CONTROLS")
        if not directory:
            self.skipTest("set HEC_NATIVE_SMOOTH_CONTROLS for the real frozen evidence control")
        directory = Path(directory)
        binding = parse_json((directory / "binding.json").read_bytes())
        source = Path(binding["source"]) / "run-binding.json"
        reviewed = runtime.review_controls(directory, ROOT, source, check_binary=True)
        self.assertEqual(len(reviewed["report"]["cases"]), 16)
        with tempfile.TemporaryDirectory(prefix="hec-control-tamper-test-") as temporary:
            target = Path(temporary)
            (target / "binding.json").write_bytes((directory / "binding.json").read_bytes())
            for budget in (False, True):
                report = copy.deepcopy(reviewed["report"])
                case = next(value for value in report["cases"] if (value["task"] in runtime.BUDGET_TASKS) == budget)
                if budget:
                    case["independent_original_cube_audit"] = {"ok": True}
                else:
                    case["independent_original_cube_audit"]["checked_edges"] = True
                (target / "report.json").write_bytes(canonical_json(report))
                with self.assertRaises(ValueError):
                    runtime.review_controls(target, ROOT, source)

    def test_malformed_native_reply_never_substitutes_for_exact_seed_checks(self):
        values = mmi()
        new_scale, rows, statistics = smooth(*values)
        for mutation in ("identity", "coverage", "bounds", "boundary", "coupled-edge"):
            report, changed = {"ok": True, **statistics}, copy.deepcopy(rows)
            sequence = 2 if mutation == "identity" else 1
            if mutation == "coverage":
                report["work"] = True
            elif mutation == "bounds":
                changed[0] = (2, 0, 0, 0)
            elif mutation == "boundary":
                changed[0] = (1, 0, 0, 0)
            elif mutation == "coupled-edge":
                changed[7] = (1, 1, 1, 0)
            meta = canonical_json(report)
            payload = packed((value for row in changed for value in row), "Q")
            output = struct.pack("<IIQ", len(meta), sequence, len(payload)) + meta + payload
            engine = NativeSmoother.__new__(NativeSmoother)
            engine.sequence, engine.check_binary = 0, lambda: None
            engine.process = SimpleNamespace(stdin=io.BytesIO(), stdout=io.BytesIO(output))
            with self.assertRaises(ValueError):
                engine.smooth(*values)
        self.assertEqual(new_scale, 1)


class NativeAttemptGateTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.SynthesisWorkflowTests("test_complete_source_is_hash_bound_and_read_only")
        self.fixture.setUp()
        self.old = synthesize.SETTINGS

    def tearDown(self):
        synthesize.SETTINGS = self.old
        self.fixture.tearDown()

    def test_dispatch_still_requires_independent_cube_acceptance(self):
        item = self.fixture.item(1)
        settings = {**self.old, "optimization": synthesize.OPTIMIZATION, "smoothing_backend": config()}
        synthesize.SETTINGS = settings
        metadata = {"implementation": "test-only-native-dispatch", "mathematical_acceptance_cached": False}

        def operation(settings, *values):
            return lambda: smooth(*values, sweeps=settings["sweeps"], max_work=settings["max_work"]), metadata

        with (
            patch.object(runtime, "operation", side_effect=operation),
            patch.object(synthesize.derivations, "accept", side_effect=fixtures.accept_small) as acceptance,
        ):
            report, packed_candidate = synthesize.attempt(item)
        self.assertIsNotNone(packed_candidate)
        acceptance.assert_called_once()
        self.assertEqual(report["smoothing_backend"], metadata)
        self.assertEqual(report["fresh_saved_alternative_audit"], "pending_separate_source_free_phase")

    def test_fresh_audit_never_uses_smoother_or_original_construction_inputs(self):
        with (
            patch.object(runtime, "operation", side_effect=AssertionError("fresh used smoother")),
            patch.object(synthesize.derivations, "accept", side_effect=fixtures.accept_small) as acceptance,
        ):
            report = synthesize.optimized_fresh(self.fixture.item(1))
        acceptance.assert_called_once()
        self.assertFalse(report["source_tables_read"])

    def test_budget_exhaustion_keeps_backend_provenance_but_claims_no_proof(self):
        synthesize.SETTINGS = {**self.old, "optimization": synthesize.OPTIMIZATION, "smoothing_backend": config()}
        metadata = {"implementation": "test-only-native-dispatch", "mathematical_acceptance_cached": False}

        def exhausted():
            raise WorkLimit("exact synthesis work budget exhausted; alternative not accepted")

        with (
            patch.object(runtime, "operation", return_value=(exhausted, metadata)),
            patch.object(synthesize.derivations, "accept") as acceptance,
        ):
            report, packed_candidate = synthesize.attempt(self.fixture.item(1))
        acceptance.assert_not_called()
        self.assertIsNone(packed_candidate)
        self.assertEqual(report["status"], "incomplete_synthesis_budget_not_a_proof")
        self.assertEqual(report["smoothing_backend"], metadata)


if __name__ == "__main__":
    unittest.main()
