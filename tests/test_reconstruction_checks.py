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

from proof_fixtures import document, unsupported_definition, write_frames

from hec import reconstruction_checks as checks
from hec._proof_partitions import partition_entries, proof_work
from hec.count_proofs import geometry, inequality_id, proof_id
from hec.graph_store import GRAPH_FORMAT, write_graph_catalog
from hec.inequality_records import write_inequality_catalog
from hec.proof_store import ProofCatalog


class ReconstructionChecksTests(unittest.TestCase):
    def test_large_graph_and_ray_partitions_cover_all_rows_without_payload_acceptance(self):
        self.stage(self.documents[:1])
        count = 50_001
        (self.directory / "rays.json").write_text(json.dumps([[1, 0, 1]] * count))
        (self.directory / "graphs.json").write_text(
            json.dumps(
                {"format": GRAPH_FORMAT, "count": count, "shards": [{"sha256": "0" * 64, "bytes": 10, "count": count}]}
            )
        )
        plan = checks.ci_matrix(self.root)
        for kind in ("graphs", "rays"):
            tasks = [task for task in plan["include"] if task["kind"] == kind]
            self.assertEqual(len(tasks), 3)
            coverage = [i for task in tasks for i in range(task["shard_index"], count, task["shard_count"])]
            self.assertEqual(sorted(coverage), list(range(count)))

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="hec-exact-ci-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.directory = self.root / "n=2"
        self.documents = [
            document(geometry(2, row), [(0,), (1,), (1,)]) for row in ((1, 1, -1), (2, 1, -1), (1, 2, -1))
        ]
        self.environment = patch.dict(
            os.environ,
            {"HEC_CHECK_WORKERS": "1", "HEC_NATIVE_DIR": ""},
        )
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def stage(self, documents=None, *, individual=True):
        documents = self.documents if documents is None else documents
        write_frames(self.directory, documents, individual=individual)
        # Adversarial framing may contain an unsupported function. Build only
        # its exact identity binding here; this is not a production authoring path.
        entries = []
        for doc in documents:
            p = geometry(doc["inequality"]["n"], tuple(map(int, doc["inequality"]["coefficients"])))
            entries.append({"id": inequality_id(p), **p.inequality(), "proof_ids": [proof_id(doc)]})
        write_inequality_catalog(
            self.directory / "inequalities.json",
            {"format": "hec-inequality-catalog", "entries": sorted(entries, key=lambda entry: entry["id"])},
        )
        for name, value in (("facets", [[1, 1, -1]]), ("rays", [[1, 0, 1]])):
            self.directory.joinpath(f"{name}.json").write_text(json.dumps(value))
        write_graph_catalog(self.directory / "graphs.json", [{"edges": [["A", "O"]], "weights": [1]}])

    def cli(self, *args):
        return subprocess.run(
            [sys.executable, "-m", "hec.reconstruction_checks", *args, "--root", str(self.root)],
            capture_output=True,
            text=True,
        )

    def test_full_map_validity_does_not_authorize_unlisted_nonfacet_extras(self):
        self.stage()
        before = self.directory.joinpath("facets.json").read_bytes()
        with patch.object(ProofCatalog, "__getitem__", side_effect=AssertionError("double parse")):
            result = checks.audit_partition(2, self.root, expect_proofs=3, expect_edges=12)
        self.assertEqual((result["proofs"], result["checked_vertices"], result["checked_edges"]), (3, 12, 12))
        self.assertFalse(result["source_tables_read"])
        self.assertFalse(result["stored_acceptance_flags_used"])
        self.assertFalse(result["facethood_or_rank_claims_established"])
        with self.assertRaisesRegex(ValueError, "exactly the same unique identities"):
            list(checks.check_stored_database_bindings(self.root, n=2))
        self.assertEqual(self.directory.joinpath("facets.json").read_bytes(), before)

    def test_metadata_needs_no_payload_but_is_never_full_map_acceptance(self):
        self.stage(self.documents[:1])
        self.directory.joinpath("proof-shards").rename(self.directory / "offline-shards")
        with patch.object(checks, "ReconstructionVerifier", side_effect=AssertionError("metadata executed a verifier")):
            result = list(checks.check_stored_database_bindings(self.root, n=2))
            plan = checks.ci_matrix(self.root)
        self.assertIn("metadata only, no mathematical audit", result[0])
        self.assertTrue(plan["include"])
        with self.assertRaisesRegex(ValueError, "missing/unsafe"):
            checks.audit_partition(2, self.root)
        with self.assertRaisesRegex(ValueError, "missing/unsafe"):
            list(checks.check_stored_facet_database_format(self.root, n=2))

    def test_standalone_database_executes_math_and_rejects_well_formed_bad_boundary(self):
        bad = copy.deepcopy(self.documents[0])
        bad["function"]["seed"] = {"kind": "integer-cut-dnf", "terms": [], "groups": [[[]]]}
        self.stage([bad])
        self.assertEqual(ProofCatalog(self.directory / "proofs.json")[0], bad)
        self.assertIn("metadata only", list(checks.check_stored_database_bindings(self.root, n=2))[0])
        with self.assertRaisesRegex(ValueError, "boundary"):
            list(checks.check_stored_facet_database_format(self.root, n=2))

    def test_unlisted_invalid_proof_fails_membership_and_explicit_mathematical_audit(self):
        bad = copy.deepcopy(self.documents[1])
        bad["function"]["seed"] = {"kind": "integer-cut-dnf", "terms": [], "groups": [[[]]]}
        self.stage([self.documents[0], bad])
        with self.assertRaisesRegex(ValueError, "exactly the same unique identities"):
            list(checks.check_stored_database_bindings(self.root, n=2))
        with self.assertRaisesRegex(ValueError, "exactly the same unique identities"):
            list(checks.check_stored_facet_database_format(self.root, n=2))
        with self.assertRaisesRegex(ValueError, "boundary"):
            checks.audit_partition(2, self.root)

    def test_all_physical_partitions_are_disjoint_complete_and_actually_audited(self):
        self.stage()
        with patch.object(checks, "PROOF_TARGET", 1):
            plan = checks.ci_matrix(self.root)["include"]
        jobs = [job for job in plan if job["kind"] == "contractions"]
        self.assertEqual(len(jobs), 3)
        self.assertEqual(sum(job["expect_proofs"] for job in jobs), 3)
        self.assertEqual(sum(job["expect_edges"] for job in jobs), 12)
        self.assertEqual(sum(job["kind"] == "database-bindings" for job in plan), 1)
        self.assertNotIn("database", {job["kind"] for job in plan})
        self.assertTrue(all(bool(job["checkout_paths"]) is (job["kind"] == "contractions") for job in plan))
        catalog = ProofCatalog(self.directory / "proofs.json")
        seen, total = set(), 0
        for job in jobs:
            _, inequalities = checks.bound_catalog(2, self.root)
            indices = set(partition_entries(catalog, inequalities, job["shard_index"], job["shard_count"]))
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

    def test_one_payload_can_have_multiple_disjoint_actual_full_map_jobs(self):
        self.stage(individual=False)
        with patch.object(checks, "PROOF_TARGET", 1):
            jobs = [row for row in checks.ci_matrix(self.root)["include"] if row["kind"] == "contractions"]
        self.assertEqual(len(jobs), 3)
        self.assertEqual(len({row["checkout_paths"] for row in jobs}), 1)
        seen, edges = set(), 0
        catalog, inequalities = checks.bound_catalog(2, self.root)
        self.assertEqual(len(catalog.shards), 1)
        for job in jobs:
            indices = set(partition_entries(catalog, inequalities, job["shard_index"], job["shard_count"]))
            self.assertFalse(indices & seen)
            seen |= indices
            result = checks.audit_partition(
                2,
                self.root,
                **{key: job[key] for key in ("shard_index", "shard_count", "expect_proofs", "expect_edges")},
            )
            edges += result["checked_edges"]
        self.assertEqual(seen, set(range(3)))
        self.assertEqual(edges, 12)

    def test_splitting_a_payload_cannot_hide_a_mathematically_invalid_map(self):
        bad = copy.deepcopy(self.documents[1])
        bad["function"]["seed"] = {"kind": "integer-cut-dnf", "terms": [], "groups": [[[]]]}
        self.stage([self.documents[0], bad, self.documents[2]], individual=False)
        failed = 0
        for group in range(3):
            try:
                checks.audit_partition(2, self.root, shard_index=group, shard_count=3)
            except ValueError as error:
                self.assertIn("boundary", str(error))
                failed += 1
        self.assertEqual(failed, 1)

    def test_partition_ownership_is_deterministic_under_catalogue_reordering(self):
        self.stage(individual=False)
        catalog, inequalities = checks.bound_catalog(2, self.root)
        before = [
            {catalog.entries[index]["proof_id"] for index in partition_entries(catalog, inequalities, group, 3)}
            for group in range(3)
        ]
        catalog.entries.reverse()
        after = [
            {catalog.entries[index]["proof_id"] for index in partition_entries(catalog, inequalities, group, 3)}
            for group in range(3)
        ]
        self.assertEqual(before, after)

    def test_audit_workers_use_at_most_four_configured_slots(self):
        self.stage(individual=False)
        with patch.dict(os.environ, {"HEC_CHECK_WORKERS": "8"}):
            with patch.object(checks, "ProcessPoolExecutor", wraps=checks.ProcessPoolExecutor) as pool:
                result = checks.audit_partition(2, self.root)
        self.assertEqual(result["checked_edges"], 12)
        self.assertEqual(pool.call_args.kwargs["max_workers"], 4)

    def test_dispatch_and_ci_order_put_largest_work_first_without_changing_coverage(self):
        self.stage(individual=False)
        catalog, inequalities = checks.bound_catalog(2, self.root)
        wanted = sorted(
            range(len(catalog)),
            key=lambda index: (
                -proof_work(inequalities.entries[catalog.entries[index]["inequality_id"]]),
                catalog.entries[index]["proof_id"],
            ),
        )
        original = checks._bounded_parallel_map
        dispatched = []

        def record(pool, function, items, **kwargs):
            dispatched.extend(items)
            yield from original(pool, function, items, **kwargs)

        with patch.object(checks, "_bounded_parallel_map", side_effect=record):
            result = checks.audit_partition(2, self.root)
        self.assertEqual(dispatched, wanted)
        self.assertEqual(result["proofs"], len(catalog))
        self.assertEqual(result["checked_edges"], 12)
        with patch.object(checks, "PROOF_TARGET", 1):
            plan = checks.ci_matrix(self.root)["include"]
        jobs = [row for row in plan if row["kind"] == "contractions"]
        facet = next(row for row in plan if row["kind"] == "facets")
        self.assertLess(plan.index(facet), plan.index(jobs[-1]))
        costs = [
            sum(
                proof_work(inequalities.entries[catalog.entries[index]["inequality_id"]])
                for index in partition_entries(catalog, inequalities, row["shard_index"], row["shard_count"])
            )
            for row in jobs
        ]
        self.assertEqual(costs, sorted(costs, reverse=True))

    def test_completed_result_must_match_its_planned_proof_identity(self):
        self.stage()
        wrong = iter(
            [(0, {"checked_edges": 4, "checked_vertices": 4, "proof_id": "0" * 64, "inequality_id": "0" * 64})]
        )
        with patch.object(checks, "_bounded_parallel_map", return_value=wrong):
            with self.assertRaisesRegex(ValueError, "planned proof/inequality identity"):
                checks.audit_partition(2, self.root)

    def test_cli_spawn_workers_execute_actual_complete_checks(self):
        self.stage(individual=False)
        with patch.dict(os.environ, {"HEC_CHECK_WORKERS": "4"}):
            result = self.cli("contractions", "--n", "2", "--expect-proofs", "3", "--expect-edges", "12")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout.splitlines()[-1])["checked_edges"], 12)

    def test_missing_completed_results_never_pass_partition_coverage(self):
        self.stage()
        with patch.object(checks, "_bounded_parallel_map", return_value=iter(())):
            with self.assertRaisesRegex(ValueError, "incomplete actual"):
                checks.audit_partition(2, self.root)

    def test_duplicate_completed_results_cannot_replace_another_proof(self):
        self.stage()
        p = geometry(2, (1, 1, -1))
        duplicates = iter(
            [
                (
                    0,
                    {
                        "checked_edges": 4,
                        "checked_vertices": 4,
                        "proof_id": proof_id(self.documents[0]),
                        "inequality_id": inequality_id(p),
                    },
                )
            ]
            * 2
        )
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

    def test_unsupported_definition_never_becomes_a_exact_fallback(self):
        old = unsupported_definition(geometry(2, (1, 1, -1)))
        self.stage([old])
        with self.assertRaises(ValueError):
            checks.audit_partition(2, self.root)

    def test_empty_data_invalid_partition_and_retired_options_fail_closed(self):
        with self.assertRaisesRegex(ValueError, "no exact datasets"):
            checks.ci_matrix(self.root)
        self.stage()
        self.assertNotEqual(self.cli("plan", "--lfs-ns-json", "[2]").returncode, 0)
        for group, groups in ((True, 1), (0, 0), (3, 3)):
            with self.assertRaisesRegex(ValueError, "proof partition"):
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
        result = self.cli("plan", "--github-output", str(handoff))
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
