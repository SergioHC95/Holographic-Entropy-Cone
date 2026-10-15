"""Actual spawn audit, source/identity binding, checkpoint resume; private tiny scope."""

import copy
import hashlib
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

import test_repository_stage as fixtures
from corpus_derivations import repository_audit as audit

from hec.count_proofs import canonical_json, parse_json


class RepositoryAuditTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.RepositoryStageTests(
            "test_cli_default_scope_refuses_small_fixture_before_creating_output"
        )
        self.fixture.setUp()
        self.temporary = tempfile.TemporaryDirectory(prefix="hec-repository-audit-")
        self.output = Path(self.temporary.name) / "audit"
        self.options = self.fixture.fixture.options

    def tearDown(self):
        self.fixture.tearDown()
        self.temporary.cleanup()

    def prepare(self):
        export = self.fixture.complete()
        self.fixture.stage(export, **self.options, _shard_bytes=1)
        with patch.object(audit, "idle", return_value=True):
            return audit.prepare(self.fixture.destination, self.fixture.fixture.output, self.output, **self.options)

    def test_actual_complete_audit_and_resume_preserve_rows_and_report(self):
        self.prepare()
        report = audit.execute(self.output, **self.options)
        self.assertEqual(report["actual_full_cube_audited"], 2)
        self.assertEqual(report["checked_original_cube_edges"], 16)
        self.assertFalse(report["stored_acceptance_flags_used"])
        self.assertFalse(report["source_tables_read"])
        with closing(sqlite3.connect(self.output / "checkpoint.sqlite3")) as db:
            before = list(db.execute("SELECT * FROM audited ORDER BY task"))
        self.assertEqual(audit.execute(self.output, **self.options), report)
        with closing(sqlite3.connect(self.output / "checkpoint.sqlite3")) as db:
            self.assertEqual(before, list(db.execute("SELECT * FROM audited ORDER BY task")))

    def test_default_scope_rejects_fixture_and_live_conversion_blocks_before_output(self):
        export = self.fixture.complete()
        self.fixture.stage(export, **self.options)
        with patch.object(audit, "idle", return_value=False):
            with self.assertRaises(BlockingIOError):
                audit.prepare(self.fixture.destination, self.fixture.fixture.output, self.output)
        with patch.object(audit, "idle", return_value=True):
            with self.assertRaisesRegex(ValueError, "complete bound corpus"):
                audit.prepare(self.fixture.destination, self.fixture.fixture.output, self.output)
        self.assertFalse(self.output.exists())

    def test_modified_proof_payload_or_index_never_reuses_audit_cache(self):
        self.prepare()
        binding = parse_json((self.output / "run-binding.json").read_bytes())
        path = Path(next(iter(binding["catalogs"].values()))["path"])
        catalog = parse_json(path.read_bytes())
        shard = path.parent / "proof-shards" / f"{next(iter(catalog['shards']))}.proofpack"
        shard.write_bytes(shard.read_bytes() + b"corrupt")
        with self.assertRaisesRegex(ValueError, "shard changed"):
            audit.execute(self.output, **self.options)

    def test_forged_partial_completed_receipt_is_not_skipped_on_resume(self):
        self.prepare()
        audit.execute(self.output, **self.options)
        with closing(sqlite3.connect(self.output / "checkpoint.sqlite3")) as db, db:
            row = db.execute("SELECT report FROM audited WHERE task=0").fetchone()[0]
            report = parse_json(row.encode())
            report["audit"]["checked_edges"] = True
            db.execute("UPDATE audited SET report=? WHERE task=0", (canonical_json(report).decode(),))
        with self.assertRaisesRegex(ValueError, "not actual original-cube"):
            audit.execute(self.output, **self.options)

    def test_frozen_code_and_bound_runtime_changes_fail_closed(self):
        self.prepare()
        path = self.output / "implementation/src/hec/reconstruction_verify.py"
        path.write_bytes(path.read_bytes() + b"\n")
        with self.assertRaisesRegex(ValueError, "implementation changed"):
            audit.execute(self.output, **self.options)

    def test_standard_native_source_is_frozen_and_checked_on_resume(self):
        self.prepare()
        path = self.output / "implementation/tools/verify_reconstruction.cpp"
        self.assertTrue(path.is_file())
        path.write_bytes(path.read_bytes() + b"\n")
        with self.assertRaisesRegex(ValueError, "implementation changed"):
            audit.execute(self.output, **self.options)

    def test_backend_override_cannot_be_partial_or_use_wrong_binary_hash(self):
        root = Path(__file__).resolve().parents[1]
        binary = Path(sys.executable).resolve()
        self.assertIsNone(audit.cube_backend(None, None, None, root))
        with self.assertRaisesRegex(ValueError, "requires an explicit"):
            audit.cube_backend(binary, None, None, root)
        controls = Path(self.temporary.name) / "controls.json"
        controls.write_bytes(b"{}")
        with self.assertRaisesRegex(ValueError, "binary SHA256"):
            audit.cube_backend(binary, "0" * 64, controls, root)

    def test_control_evidence_cannot_authorize_seed_only_boolean_or_wrong_source(self):
        # Pure evidence-validation fixture; this never runs the configured
        # executable and never constitutes mathematical acceptance.
        root = Path(self.temporary.name) / "fixture-root"
        source = root / "tools/verify_reconstruction.cpp"
        source.parent.mkdir(parents=True)
        source.write_bytes(b"source hash fixture\n")
        controls = root / "report.json"
        binding_path = root / "binding.json"
        binary = Path(sys.executable).resolve()
        binary_sha = audit.derivations.digest(binary)
        binding = {
            "format": "hec-tiled-audit-control/1",
            "prototype_binary": {"sha256": binary_sha},
            "primary_output_buffer_budget_bytes": 256 * 1024**2,
            "implementation": {"tools/verify_reconstruction.cpp": hashlib.sha256(source.read_bytes()).hexdigest()},
        }
        binding_path.write_bytes(canonical_json(binding))
        cases = []
        for primitive in (
            "integer-interval-closure/1",
            "integer-cut-dnf/1",
            "compatible-count-table/1",
            "compatible-scalar-dag/1",
        ):
            result = {
                "ok": True,
                "scope": "original-cube-all-edges",
                "source_tables_read": False,
                "checked_vertices": 4,
                "checked_edges": 4,
                "proof_id": "0" * 64,
                "inequality_id": "1" * 64,
                "semantic_map_id": "2" * 64,
                "output_row_storage_limit": 256 * 1024**2,
                "output_row_storage_bytes": 32,
            }
            cases.append(
                {
                    "L": 2,
                    "primitive": primitive,
                    "pairs": [{"arms": {"full": {"audit": dict(result)}, "bounded": {"audit": dict(result)}}}],
                }
            )
        report = {
            "format": "hec-tiled-audit-report/1",
            "binding_sha256": audit.derivations.digest(binding_path),
            "primary_output_buffer_budget_bytes": 256 * 1024**2,
            "cases": cases,
            "actual_original_cube_edges_including_timing_repeats": 32,
        }
        controls.write_bytes(canonical_json(report))
        selected = audit.cube_backend(binary, binary_sha, controls, root)
        self.assertEqual(selected["primary_output_buffer_bytes"], 256 * 1024**2)
        for key, value in (("checked_edges", True), ("scope", "compatible-seed-only"), ("output_row_storage_limit", 1)):
            bad = copy.deepcopy(report)
            bad["cases"][0]["pairs"][0]["arms"]["bounded"]["audit"][key] = value
            controls.write_bytes(canonical_json(bad))
            with self.subTest(key=key), self.assertRaises(ValueError):
                audit.cube_backend(binary, binary_sha, controls, root)
        controls.write_bytes(canonical_json(report))
        source.write_bytes(b"changed source\n")
        with self.assertRaisesRegex(ValueError, "exact standard source"):
            audit.cube_backend(binary, binary_sha, controls, root)


if __name__ == "__main__":
    unittest.main()
