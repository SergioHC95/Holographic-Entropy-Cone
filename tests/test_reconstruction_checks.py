"""Unified-only actual CI audits, metadata separation and complete partitions."""

import copy
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import zstandard as zstd
from corpus_derivations.pipeline_import import import_recipe
from corpus_derivations.repository_stage import Frames

from hec import reconstruction_checks as checks
from hec.count_proofs import canonical_json, geometry, inequality_id, make_count_proof, proof_geometry, proof_id
from hec.inequality_records import inequality_catalog, write_inequality_catalog
from hec.proof_store import CATALOG_FORMAT
from hec.reconstruction_store import ReconstructionCatalog


class ReconstructionChecksTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="hec-unified-ci-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.directory = self.root / "n=2"
        self.documents = [
            import_recipe(make_count_proof(geometry(2, row), [(0,), (1,), (1,)], transport=True))[0]
            for row in ((1, 1, -1), (2, 1, -1), (1, 2, -1))
        ]
        self.environment = patch.dict(
            os.environ,
            {"HEC_CHECK_WORKERS": "1", "HEC_RECONSTRUCTION_CLOSURE": "", "HEC_RECONSTRUCTION_VERIFIER": ""},
        )
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def stage(self, documents=None):
        documents = self.documents if documents is None else documents
        writer = Frames(self.directory, 1)  # One immutable physical shard per definition.
        for document in documents:
            writer.append(
                inequality_id(proof_geometry(document)),
                proof_id(document),
                zstd.ZstdCompressor(write_checksum=True).compress(canonical_json(document)),
            )
        writer.seal()
        self.directory.joinpath("proofs.json").write_bytes(
            canonical_json({"format": CATALOG_FORMAT, "entries": writer.entries, "shards": writer.shards})
        )
        write_inequality_catalog(self.directory / "inequalities.json", inequality_catalog(documents))
        for name, value in (("facets", [[1, 1, -1]]), ("rays", [[1, 0, 1]]), ("graphs", [])):
            self.directory.joinpath(f"{name}.json").write_text(json.dumps(value))

    def cli(self, *args):
        return subprocess.run(
            [sys.executable, "-m", "hec.reconstruction_checks", *args, "--root", str(self.root)],
            capture_output=True,
            text=True,
        )

    def test_full_audit_uses_single_parse_and_accepts_valid_nonfacet_extras(self):
        self.stage()
        before = self.directory.joinpath("facets.json").read_bytes()
        with patch.object(ReconstructionCatalog, "__getitem__", side_effect=AssertionError("double parse")):
            result = checks.audit_partition(2, self.root, expect_proofs=3, expect_edges=12)
        self.assertEqual((result["proofs"], result["checked_vertices"], result["checked_edges"]), (3, 12, 12))
        self.assertFalse(result["source_tables_read"])
        self.assertFalse(result["stored_acceptance_flags_used"])
        self.assertFalse(result["facethood_or_rank_claims_established"])
        bindings = list(checks.check_stored_database_bindings(self.root, n=2))
        self.assertIn("3 inequality/3 proof", bindings[0])
        self.assertIn("1 listed facets covered", bindings[0])
        self.assertEqual(self.directory.joinpath("facets.json").read_bytes(), before)

    def test_metadata_needs_no_payload_but_is_never_full_map_acceptance(self):
        self.stage()
        self.directory.joinpath("proof-shards").rename(self.directory / "offline-shards")
        with patch.object(checks, "ReconstructionVerifier", side_effect=AssertionError("metadata executed a verifier")):
            result = list(checks.check_stored_database_bindings(self.root, n=2))
            plan = checks.ci_matrix(self.root, lfs_ns=[2])
        self.assertIn("metadata only, no mathematical audit", result[0])
        self.assertTrue(plan["include"])
        with self.assertRaisesRegex(ValueError, "missing/unsafe"):
            checks.audit_partition(2, self.root)
        with self.assertRaisesRegex(ValueError, "missing/unsafe"):
            list(checks.check_stored_facet_database_format(self.root, n=2))

    def test_standalone_database_executes_math_and_rejects_well_formed_bad_boundary(self):
        bad = copy.deepcopy(self.documents[0])
        bad["function"]["seed"] = {"kind": "integer-cut-dnf/1", "terms": [], "groups": [[[]]]}
        self.stage([bad])
        self.assertEqual(ReconstructionCatalog(self.directory / "proofs.json")[0], bad)
        self.assertIn("metadata only", list(checks.check_stored_database_bindings(self.root, n=2))[0])
        with self.assertRaisesRegex(ValueError, "boundary"):
            list(checks.check_stored_facet_database_format(self.root, n=2))

    def test_standalone_database_does_not_skip_invalid_extra_nonfacet_proof(self):
        bad = copy.deepcopy(self.documents[1])
        bad["function"]["seed"] = {"kind": "integer-cut-dnf/1", "terms": [], "groups": [[[]]]}
        self.stage([self.documents[0], bad])
        self.assertIn("1 listed facets covered", list(checks.check_stored_database_bindings(self.root, n=2))[0])
        with self.assertRaisesRegex(ValueError, "boundary"):
            list(checks.check_stored_facet_database_format(self.root, n=2))

    def test_all_physical_partitions_are_disjoint_complete_and_actually_audited(self):
        self.stage()
        with patch.object(checks, "PROOF_TARGET", 1):
            plan = checks.ci_matrix(self.root, lfs_ns=[2])["include"]
        jobs = [job for job in plan if job["kind"] == "contractions"]
        self.assertEqual(len(jobs), 3)
        self.assertEqual(sum(job["expect_proofs"] for job in jobs), 3)
        self.assertEqual(sum(job["expect_edges"] for job in jobs), 12)
        self.assertEqual(sum(job["kind"] == "database-bindings" for job in plan), 1)
        self.assertNotIn("database", {job["kind"] for job in plan})
        self.assertTrue(all(job["lfs"] is (job["kind"] == "contractions") for job in plan))
        catalog = ReconstructionCatalog(self.directory / "proofs.json")
        seen, total = set(), 0
        for job in jobs:
            indices = set(catalog.shard_group_entries(job["shard_index"], job["shard_count"]))
            self.assertFalse(indices & seen)
            seen |= indices
            result = checks.audit_partition(
                2,
                self.root,
                **{key: job[key] for key in ("shard_index", "shard_count", "expect_proofs", "expect_edges")},
            )
            total += result["checked_edges"]
        self.assertEqual(seen, set(range(3)))
        self.assertEqual(total, 12)

    def test_planned_coverage_mismatch_stops_before_native_startup(self):
        self.stage()
        with patch.object(checks, "ReconstructionVerifier", side_effect=AssertionError("must preflight first")):
            for options in ({"expect_proofs": 2}, {"expect_edges": 8}, {"expect_proofs": True}):
                with self.subTest(options=options), self.assertRaisesRegex(ValueError, "planned exact"):
                    checks.audit_partition(2, self.root, **options)

    def test_missing_completed_results_never_pass_partition_coverage(self):
        self.stage()
        with patch.object(checks, "_bounded_parallel_map", return_value=iter(())):
            with self.assertRaisesRegex(ValueError, "incomplete actual"):
                checks.audit_partition(2, self.root)

    def test_duplicate_completed_results_cannot_replace_another_proof(self):
        self.stage()
        duplicates = iter([(0, {"checked_edges": 4, "checked_vertices": 4})] * 2)
        with patch.object(checks, "_bounded_parallel_map", return_value=duplicates):
            with self.assertRaisesRegex(ValueError, "duplicate or out-of-partition"):
                checks.audit_partition(2, self.root)

    def test_missing_known_facet_and_party_mismatch_fail_closed(self):
        self.stage(self.documents[:2])
        self.directory.joinpath("facets.json").write_text(json.dumps([[1, 2, -1]]))
        with self.assertRaisesRegex(ValueError, "known facets"):
            list(checks.check_stored_database_bindings(self.root, n=2))
        self.directory.rename(self.root / "n=3")
        with self.assertRaisesRegex(ValueError, "wrong party"):
            checks.audit_partition(3, self.root)

    def test_legacy_definition_never_becomes_a_unified_fallback(self):
        old = make_count_proof(geometry(2, (1, 1, -1)), [(0,), (1,), (1,)], transport=True)
        self.stage([old])
        with self.assertRaises(ValueError):
            checks.audit_partition(2, self.root)

    def test_empty_data_invalid_partition_and_wrong_lfs_scope_fail_closed(self):
        with self.assertRaisesRegex(ValueError, "no unified datasets"):
            checks.ci_matrix(self.root)
        self.stage()
        for scope in ([True], [3], [2, 2], {2: True}):
            with self.subTest(scope=scope), self.assertRaisesRegex(ValueError, "LFS party"):
                checks.ci_matrix(self.root, lfs_ns=scope)
        for group, groups in ((True, 1), (0, 0), (3, 3)):
            with self.assertRaisesRegex(ValueError, "physical proof shard"):
                checks.audit_partition(2, self.root, shard_index=group, shard_count=groups)
        with self.assertRaisesRegex(ValueError, "cannot be split"):
            list(checks.check_stored_database_bindings(self.root, n=2, shard_count=2))

    def test_repeated_party_count_directories_cannot_duplicate_ci_coverage(self):
        self.stage()
        self.root.joinpath("n=02").mkdir()
        with self.assertRaisesRegex(ValueError, "ambiguous repeated"):
            checks.ci_matrix(self.root)

    def test_cli_plan_is_full_scope_and_actual_cli_audit_checks_expected_counts(self):
        self.stage()
        handoff = self.root / "github-output"
        result = self.cli("plan", "--lfs-ns-json", "[2]", "--github-output", str(handoff))
        self.assertEqual(result.returncode, 0, result.stderr)
        plan = json.loads(result.stdout)
        self.assertEqual(json.loads(handoff.read_text().removeprefix("matrix=")), plan)
        result = self.cli("contractions", "--n", "2", "--expect-proofs", "3", "--expect-edges", "12")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout.splitlines()[-1])["checked_edges"], 12)
        self.assertNotEqual(self.cli("plan", "--n", "2").returncode, 0)
        self.assertNotEqual(self.cli("contractions").returncode, 0)


if __name__ == "__main__":
    unittest.main()
