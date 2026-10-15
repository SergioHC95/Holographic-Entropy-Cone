"""Actual spawn audit, source/identity binding, checkpoint resume; private tiny scope."""

import sqlite3
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


if __name__ == "__main__":
    unittest.main()
