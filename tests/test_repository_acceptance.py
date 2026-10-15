"""Complete acceptance review fixtures; report flags never replace real rows."""

import copy
import sqlite3
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

import test_repository_audit as fixtures
from corpus_derivations import repository_acceptance as acceptance
from corpus_derivations import repository_audit as audit

from hec.count_proofs import canonical_json, parse_json


class RepositoryAcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.RepositoryAuditTests("test_actual_complete_audit_and_resume_preserve_rows_and_report")
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.output = self.fixture.output

    def complete(self):
        self.fixture.prepare()
        return audit.execute(self.output, **self.fixture.options)

    def review(self, **options):
        # The tiny fixture's synchronous controller is this test's own PID,
        # not a live long-running production process. CLI has no override.
        with patch.object(acceptance, "idle", return_value=True):
            return acceptance.review(self.output, **options)

    def test_real_complete_fixture_reconciles_without_new_audits_or_database_writes(self):
        self.complete()
        before = (self.output / "report.json").read_bytes()
        with closing(sqlite3.connect(self.output / "checkpoint.sqlite3")) as db:
            rows = list(db.execute("SELECT * FROM audited ORDER BY task"))
        with patch("hec.reconstruction_store.ReconstructionVerifier", side_effect=AssertionError("no new math pass")):
            result = self.review(**self.fixture.options)
        self.assertEqual((result["proofs"], result["checked_stored_frames"]), (2, 2))
        self.assertEqual(result["actual_prior_audit_edges_reconciled"], 16)
        self.assertEqual(result["new_mathematical_audits_executed_by_review"], 0)
        self.assertTrue(result["mathematical_promotion_precondition_passed"])
        self.assertFalse(result["repository_reader_data_or_ci_changed"])
        self.assertFalse(result["full_goal_complete"])
        self.assertEqual((self.output / "report.json").read_bytes(), before)
        with closing(sqlite3.connect(self.output / "checkpoint.sqlite3")) as db:
            self.assertEqual(rows, list(db.execute("SELECT * FROM audited ORDER BY task")))

    def test_live_run_and_default_full_scope_do_not_accept_fixture(self):
        with patch.object(acceptance, "idle", return_value=False):
            with self.assertRaisesRegex(BlockingIOError, "remain live"):
                acceptance.review(self.output)
        self.assertFalse(self.output.exists())
        self.complete()
        with self.assertRaisesRegex(ValueError, "all source identities"):
            self.review()

    def test_green_report_does_not_hide_missing_successful_row(self):
        self.complete()
        with closing(sqlite3.connect(self.output / "checkpoint.sqlite3")) as db, db:
            db.execute("DELETE FROM audited WHERE task=0")
        with self.assertRaisesRegex(ValueError, "actual successful result rows"):
            self.review(**self.fixture.options)

    def test_seed_only_or_boolean_coverage_in_a_full_size_ledger_is_rejected(self):
        self.complete()
        with closing(sqlite3.connect(self.output / "checkpoint.sqlite3")) as db:
            original = parse_json(db.execute("SELECT report FROM audited WHERE task=0").fetchone()[0].encode())
        for field, value in (("scope", "compatible-seed-only"), ("checked_edges", True)):
            changed = copy.deepcopy(original)
            changed["audit"][field] = value
            with closing(sqlite3.connect(self.output / "checkpoint.sqlite3")) as db, db:
                db.execute("UPDATE audited SET report=? WHERE task=0", (canonical_json(changed).decode(),))
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "not actual original-cube"):
                self.review(**self.fixture.options)

    def test_changed_frozen_source_or_actual_payload_cannot_reuse_green_report(self):
        self.complete()
        path = self.output / "implementation/tools/verify_reconstruction.cpp"
        old = path.read_bytes()
        path.write_bytes(old + b"\n")
        with self.assertRaisesRegex(ValueError, "bound acceptance input changed"):
            self.review(**self.fixture.options)
        path.write_bytes(old)
        binding = parse_json((self.output / "run-binding.json").read_bytes())
        info = next(iter(binding["catalogs"].values()))
        shard = Path(info["path"]).parent / "proof-shards" / f"{next(iter(info['shards']))}.proofpack"
        shard.write_bytes(shard.read_bytes() + b"corruption")
        with self.assertRaisesRegex(ValueError, "bound acceptance input changed"):
            self.review(**self.fixture.options)

    def test_matching_forged_counts_in_manifest_and_result_still_fail_actual_geometry(self):
        self.complete()
        manifest = parse_json((self.output / "manifest.json").read_bytes())
        manifest[0]["L"] += 1
        (self.output / "manifest.json").write_bytes(canonical_json(manifest))
        binding = parse_json((self.output / "run-binding.json").read_bytes())
        binding["manifest_sha256"] = acceptance.derivations.digest(self.output / "manifest.json")
        (self.output / "run-binding.json").write_bytes(canonical_json(binding))
        with closing(sqlite3.connect(self.output / "checkpoint.sqlite3")) as db, db:
            record = parse_json(db.execute("SELECT report FROM audited WHERE task=0").fetchone()[0].encode())
            L = manifest[0]["L"]
            record["audit"].update(checked_vertices=1 << L, checked_edges=L * ((1 << L) // 2))
            db.execute("UPDATE audited SET report=? WHERE task=0", (canonical_json(record).decode(),))
        with self.assertRaisesRegex(ValueError, "actual geometry"):
            self.review(**self.fixture.options)


if __name__ == "__main__":
    unittest.main()
