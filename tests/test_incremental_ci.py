"""Offline Git/GitHub fixtures and actual small exact validation controls."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
from proof_fixtures import document, write_frames

from hec.ci_baseline import GitHub, GitTree, VerifiedBaseline, acceptance_receipt, checkout_commit, verify_baseline
from hec.ci_checks import check_catalogue_delta, check_storage_delta, orbit_sum, resolve_plan, run_task
from hec.count_proofs import geometry, inequality_id, proof_id
from hec.data import default_data_root
from hec.graph_store import GraphCatalog, write_graph_catalog
from hec.incremental_ci import IntegrityPlan
from hec.inequality_records import inequality_catalog
from hec.proof_store import ProofCatalog
from hec.ray_store import write_ray_catalog
from hec.storage import history_audit, snapshot
from hec.symmetry import permutation_array


class FakeGitHub:
    repository = "fixture/repository"

    def __init__(self, accepted, tree, *, event="push"):
        self.accepted, self.tree, self.event = accepted, tree, event
        self.app = 15368
        self.conclusion = "success"
        self.workflow_id = 313
        self.checkout_tree = tree
        self.missing_core = False
        self.calls = []
        self.receipt = None

    def request(self, path, *, pages=False, raw=False):
        self.calls.append(path)
        check = {
            "id": 900,
            "name": "database integrity",
            "status": "completed",
            "conclusion": self.conclusion,
            "head_sha": self.accepted,
            "app": {"id": self.app},
            "details_url": f"https://github.com/{self.repository}/actions/runs/77/job/900",
        }
        if path == "actions/workflows/database-integrity.yml":
            return {"id": 313}
        if path.startswith("commits/"):
            return [{"check_runs": [check]}]
        if path == "check-runs/900":
            return check
        if path.startswith("check-runs/900/annotations"):
            return (
                [
                    [
                        {
                            "title": "HEC integrity acceptance v1",
                            "annotation_level": "notice",
                            "message": json.dumps(self.receipt),
                        }
                    ]
                ]
                if self.receipt is not None
                else [[]]
            )
        if path == "actions/runs/77":
            return {
                "id": 77,
                "workflow_id": self.workflow_id,
                "status": "completed",
                "conclusion": self.conclusion,
                "head_sha": self.accepted,
                "path": ".github/workflows/database-integrity.yml",
                "event": self.event,
                "run_attempt": 1,
            }
        if path.startswith("actions/runs/77/jobs"):
            names = [
                "discover datasets",
                "ordinary Git data and complete main-ancestry hygiene",
                "installed wheel and exact small-corpus acceptance",
                "code quality and tests (ubuntu-24.04)",
                "code quality and tests (macos-15)",
                "catalogue integration (ubuntu-24.04)",
                "catalogue integration (macos-15)",
            ]
            if self.missing_core:
                names.pop()
            jobs = [
                {"id": 100 + i, "name": name, "status": "completed", "conclusion": "success"}
                for i, name in enumerate(names)
            ]
            return [
                {"total_count": len(jobs) + 1, "jobs": jobs},
                {
                    "total_count": len(jobs) + 1,
                    "jobs": [{"id": 900, "name": "database integrity", "status": "completed", "conclusion": "success"}],
                },
            ]
        if path == "actions/jobs/100/logs":
            return f"unrelated {'f' * 40}\n[command]/usr/bin/git log -1 --format=%H\n{self.accepted}\n"
        if path.startswith("git/commits/"):
            return {"tree": {"sha": self.checkout_tree}, "parents": [{"sha": self.accepted}]}
        raise AssertionError("unexpected external request: " + path)


class IncrementalFixtures(unittest.TestCase):
    n = 2

    def git(self, *args):
        return subprocess.run(
            ["git", "-C", str(self.root), *args], capture_output=True, text=True, check=True
        ).stdout.strip()

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="hec-incremental-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.data = self.root / f"data/n={self.n}"
        self.git("init", "-b", "main")
        self.git("config", "user.name", "Integrity fixture")
        self.git("config", "user.email", "fixture@example.invalid")
        (self.root / "src").mkdir()
        (self.root / "src/verifier.py").write_text("# fixed fixture verifier\n")
        (self.root / ".github/workflows").mkdir(parents=True)
        (self.root / ".github/workflows/database-integrity.yml").write_text("# fixed fixture policy\n")
        (self.root / ".gitattributes").write_text(
            "*.proofpack -filter -text -diff\n*.witnesspack -filter -text -diff\n"
        )
        shutil.copytree(default_data_root() / f"n={self.n}", self.data)
        self.base = self.commit("accepted base")
        base = GitTree(self.root, self.base)
        self.evidence = VerifiedBaseline(self.base, base.tree, self.base, self.base, 77, 1, 900, base.fingerprint())
        self.environment = patch.dict(os.environ, {"HEC_CHECK_WORKERS": "1"})
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def doc(self, name):
        return json.loads((self.data / name).read_bytes())

    def write(self, name, value):
        (self.data / name).write_text(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n")

    def trim(self):
        for kind, suffix in (
            ("proof", ".proofpack"),
            ("graph", ".json"),
            ("ray", ".json"),
            ("witness", ".witnesspack"),
        ):
            index = {
                "proof": "proofs.json",
                "graph": "graphs.json",
                "ray": "rays.json",
                "witness": "facet-witnesses.json",
            }[kind]
            if not (self.data / index).exists():
                continue
            doc = self.doc(index)
            shards = doc.get("shards", {}) if isinstance(doc, dict) else {}
            wanted = set(shards) if isinstance(shards, dict) else {shard["sha256"] for shard in shards}
            for path in (self.data / (kind + "-shards")).glob("*" + suffix):
                if path.stem not in wanted:
                    path.unlink()

    def readme(self):
        facets = self.doc("facets.json")
        rays = json.loads((self.data / "rays.json").read_bytes())
        if isinstance(rays, dict):
            rays = [
                row
                for shard in rays["shards"]
                for row in json.loads((self.data / "ray-shards" / (shard["sha256"] + ".json")).read_bytes())
            ]
        proofs = self.doc("proofs.json")
        maps = permutation_array(self.n)

        def images(rows):
            return sum(len({tuple(image) for image in np.asarray(row)[maps]}) for row in rows)

        text = (
            "# Fixture\nexactly one full-map proof per listed facet\n"
            f"**{len(proofs['entries']):,} full-map proofs**; **{len(proofs['shards']):,} proof shards**; "
            f"**{sum(v['bytes'] for v in proofs['shards'].values()):,} bytes**\n"
            "## Cone summary\n| n | facets | facet images | rays | ray images | proofs | status |\n"
            "| --- | --- | --- | --- | --- | --- | --- |\n"
            f"| {self.n} | {len(facets):,} | {images(facets):,} | {len(rays):,} | {images(rays):,} | "
            f"{len(proofs['entries']):,} | complete |\n"
        )
        (self.root / "README.md").write_text(text)

    def commit(self, message, *, refresh=True):
        if refresh:
            self.trim()
            self.readme()
            self.git("add", ".")
            snapshot(self.root, replace=True)
        self.git("add", ".")
        self.git("commit", "--allow-empty", "-m", message)
        return self.git("rev-parse", "HEAD")

    def plan(self):
        result = IntegrityPlan(GitTree(self.root), baseline=self.evidence)
        self.addCleanup(result.close)
        return result

    def add_facet(self, coefficients=(2, 1, -1), *, bad=False):
        proof = document(geometry(2, coefficients), [(0,), (1,), (1,)])
        if bad:
            proof["function"]["kind"] = "not-a-proof-language"
        with tempfile.TemporaryDirectory(prefix="hec-new-proof-control-") as name:
            directory = Path(name)
            write_frames(directory, [proof])
            new = json.loads((directory / "proofs.json").read_bytes())
            for path in (directory / "proof-shards").iterdir():
                shutil.copy2(path, self.data / "proof-shards" / path.name)
        proofs = self.doc("proofs.json")
        proofs["entries"] += new["entries"]
        proofs["shards"].update(new["shards"])
        self.write("proofs.json", proofs)
        inequalities = self.doc("inequalities.json")
        inequalities["entries"].append(
            {
                "id": inequality_id(geometry(2, coefficients)),
                **geometry(2, coefficients).inequality(),
                "proof_ids": [proof_id(proof)],
            }
        )
        inequalities["entries"].sort(key=lambda row: row["id"])
        self.write("inequalities.json", inequalities)
        self.write("facets.json", self.doc("facets.json") + [list(coefficients)])


class BaselineTests(IncrementalFixtures):
    def test_actual_success_and_second_job_page_are_required(self):
        current = GitTree(self.root)
        github = FakeGitHub(self.base, current.tree)
        result = verify_baseline(current, self.base, github)
        self.assertEqual((result.run_id, result.accepted_commit, result.tree), (77, self.base, current.tree))
        github.missing_core = True
        with self.assertRaises(ValueError):
            verify_baseline(current, self.base, github)

    def test_wrong_app_failed_run_wrong_workflow_and_wrong_tested_tree_fail(self):
        for field, value in (("app", 7), ("conclusion", "failure"), ("workflow_id", 8), ("checkout_tree", "f" * 40)):
            with self.subTest(field=field):
                github = FakeGitHub(self.base, GitTree(self.root).tree, event="pull_request")
                setattr(github, field, value)
                with self.assertRaises(ValueError):
                    verify_baseline(GitTree(self.root), self.base, github)

    def test_pull_request_uses_actual_checkout_tree_not_just_head_sha(self):
        github = FakeGitHub(self.base, GitTree(self.root).tree, event="pull_request")
        self.assertEqual(verify_baseline(GitTree(self.root), self.base, github).tested_commit, self.base)
        self.assertIn("actions/jobs/100/logs", github.calls)

    def test_bound_gate_receipt_avoids_legacy_log_and_job_downloads(self):
        current = GitTree(self.root)
        github = FakeGitHub(self.base, current.tree, event="pull_request")
        github.receipt = {
            "format": "hec-integrity-acceptance-v1",
            "tested_commit": self.base,
            "tree": current.tree,
            "verifier": current.fingerprint(),
            "plan_sha256": "a" * 64,
            "mode": "full",
        }
        self.assertEqual(verify_baseline(current, self.base, github).run_id, 77)
        self.assertFalse(any("/logs" in path or "/jobs" in path for path in github.calls))
        github.receipt["tree"] = "f" * 40
        with self.assertRaises(ValueError):
            verify_baseline(current, self.base, github)

    def test_acceptance_receipt_is_closed_unique_and_context_bound(self):
        verifier = self.evidence.verifier
        value = {
            "format": "hec-integrity-acceptance-v1",
            "tested_commit": self.base,
            "tree": self.evidence.tree,
            "verifier": verifier,
            "plan_sha256": "a" * 64,
            "mode": "incremental",
        }
        record = {"title": "HEC integrity acceptance v1", "annotation_level": "notice", "message": json.dumps(value)}
        self.assertEqual(acceptance_receipt([[record]], verifier), value)
        for bad in (
            [[record, record]],
            [[{**record, "annotation_level": "warning"}]],
            [[{**record, "message": json.dumps({**value, "verifier": "f" * 64})}]],
            [[{**record, "message": json.dumps({**value, "cached": True})}]],
            [[{**record, "message": json.dumps({**value, "tested_commit": 4})}]],
        ):
            with self.assertRaises(ValueError):
                acceptance_receipt(bad, verifier)

    def test_merge_tree_can_reuse_accepted_parent_but_new_history_is_still_audited(self):
        self.git("switch", "-c", "bad-history")
        path = self.root / "removed-pointer"
        path.write_text("version https://git-lfs.github.com/spec/v1\noid sha256:" + "a" * 64 + "\nsize 4\n")
        self.commit("historical pointer", refresh=False)
        path.unlink()
        self.commit("remove current pointer", refresh=False)
        self.git("switch", "main")
        self.git("merge", "--no-ff", "bad-history", "-m", "merge same tree")
        head = GitTree(self.root)
        self.assertEqual(head.tree, self.evidence.tree)
        baseline = verify_baseline(head, head.commit, FakeGitHub(self.base, self.evidence.tree))
        self.assertEqual(baseline.accepted_commit, self.base)
        with self.assertRaisesRegex(ValueError, "pointer"):
            history_audit(self.root, trusted_ancestor=self.base)

    def test_source_change_or_missing_authentication_falls_back_to_full(self):
        (self.root / "src/verifier.py").write_text("# changed verifier\n")
        self.commit("source change")
        result = resolve_plan(self.root, base=self.base, github=FakeGitHub(self.base, self.evidence.tree))
        self.addCleanup(result.close)
        self.assertEqual(result.mode, "full")
        self.assertTrue(any(task["kind"] == "contractions" for task in result.tasks))
        with self.assertRaises(ValueError):
            resolve_plan(
                self.root, mode="incremental", base=self.base, github=FakeGitHub(self.base, self.evidence.tree)
            )

    def test_checkout_log_has_one_explicit_identity(self):
        log = (
            f"noise {'e' * 40}\n2026-11-05T00:00:00.000Z [command]/usr/bin/git log -1 --format=%H\n"
            f"2026-11-05T00:00:00.001Z {self.base}\n"
        )
        self.assertEqual(checkout_commit(log), self.base)
        for invalid in (self.base, log + log, "[command]git log -1 --format=%H\nnot-a-sha"):
            with self.assertRaises(ValueError):
                checkout_commit(invalid)

    def test_dirty_verifier_and_mismatched_certificate_are_rejected(self):
        (self.root / "src/verifier.py").write_text("# uncommitted changes\n")
        with self.assertRaisesRegex(ValueError, "working files"):
            resolve_plan(self.root, base=self.base, github=FakeGitHub(self.base, self.evidence.tree))
        self.git("restore", "src/verifier.py")
        forged = replace(self.evidence, verifier="f" * 64)
        with self.assertRaisesRegex(ValueError, "baseline"):
            IntegrityPlan(GitTree(self.root), baseline=forged)

    def test_incomplete_job_pages_are_not_a_baseline(self):
        github = FakeGitHub(self.base, self.evidence.tree)
        request = github.request

        def incomplete(path, **kwargs):
            result = request(path, **kwargs)
            if path.startswith("actions/runs/77/jobs"):
                result[0]["total_count"] += 1
            return result

        with patch.object(github, "request", side_effect=incomplete), self.assertRaisesRegex(ValueError, "incomplete"):
            verify_baseline(GitTree(self.root), self.base, github)


class ChangedResultTests(IncrementalFixtures):
    def test_unchanged_results_need_only_reuse_guard_and_exact_metadata(self):
        plan = self.plan()
        self.assertEqual([task["kind"] for task in plan.tasks], ["acceptance"])
        self.assertEqual(check_storage_delta(plan, self.root)["new_or_changed_files_verified"], 0)
        self.assertTrue(check_catalogue_delta(plan, self.root)["ok"])

    def test_unchanged_payloads_are_not_read_while_planning_or_checking_counts(self):
        original = GitTree.read

        def metadata_only(tree, path):
            if "-shards/" in path:
                raise AssertionError("unchanged payload was loaded: " + path)
            return original(tree, path)

        with patch.object(GitTree, "read", metadata_only):
            plan = self.plan()
            self.assertTrue(check_catalogue_delta(plan, self.root)["ok"])

    def test_new_facet_and_proof_do_not_repeat_existing_ray_or_graph_audits(self):
        self.add_facet()
        self.commit("new inequality and facet candidate")
        plan = self.plan()
        self.assertEqual(plan.selected[2], {"contractions": [1], "facets": [1], "rays": [], "graphs": []})
        self.assertEqual(sorted(task["kind"] for task in plan.tasks), ["acceptance", "contractions", "facets"])
        self.assertTrue(check_catalogue_delta(plan, self.root)["ok"])
        proof = next(task for task in plan.tasks if task["kind"] == "contractions")
        result = run_task(plan, proof["task_id"], self.root)
        self.assertEqual(result["proofs"], 1)
        facet = next(task for task in plan.tasks if task["kind"] == "facets")
        # This valid inequality is deliberately not a facet. A cached old
        # facet rank cannot promote it; the fresh rank check must reject it.
        with self.assertRaisesRegex(ValueError, "rank"):
            run_task(plan, facet["task_id"], self.root)

    def test_corrupt_changed_proof_cannot_inherit_old_acceptance(self):
        self.add_facet(bad=True)
        self.commit("bad new proof has new content identity")
        plan = self.plan()
        task = next(task for task in plan.tasks if task["kind"] == "contractions")
        with self.assertRaises(ValueError):
            run_task(plan, task["task_id"], self.root)

    def test_append_rays_and_graphs_rechecks_only_new_pair_and_new_ray(self):
        rays = self.doc("rays.json")
        graphs = list(GraphCatalog(self.data / "graphs.json"))
        write_ray_catalog(self.data / "rays.json", rays + [[1, 0, 1]], 2)
        write_graph_catalog(self.data / "graphs.json", graphs + [{"edges": [["A", "O"]], "weights": [1]}])
        self.commit("append one ray and graph")
        plan = self.plan()
        self.assertEqual(plan.selected[2], {"contractions": [], "facets": [], "rays": [1], "graphs": [1]})
        for task in plan.tasks:
            self.assertTrue(run_task(plan, task["task_id"], self.root)["ok"])
        self.assertTrue(check_catalogue_delta(plan, self.root)["ok"])

    def test_old_graph_edit_is_checked_but_does_not_repeat_proofs_or_ranks(self):
        graph = list(GraphCatalog(self.data / "graphs.json"))[0]
        graph["weights"] = [2 * value for value in graph["weights"]]
        write_graph_catalog(self.data / "graphs.json", [graph])
        self.commit("change existing graph")
        plan = self.plan()
        self.assertEqual(plan.selected[2]["graphs"], [0])
        self.assertEqual(plan.selected[2]["contractions"], [])
        self.assertEqual(plan.selected[2]["rays"], [])
        self.assertEqual(plan.catalogue_mode, "full")
        task = next(task for task in plan.tasks if task["kind"] == "graphs")
        with self.assertRaisesRegex(ValueError, "canonical"):
            run_task(plan, task["task_id"], self.root)

    def test_one_edited_graph_inside_a_repacked_shard_does_not_recheck_its_neighbors(self):
        from hec.checks import _check_graph_pair

        rays = self.doc("rays.json") + [[1, 0, 1]]
        graphs = list(GraphCatalog(self.data / "graphs.json")) + [{"edges": [["A", "O"]], "weights": [1]}]
        self.write("rays.json", rays)
        write_graph_catalog(self.data / "graphs.json", graphs)
        self.base = self.commit("accepted two-pair fixture")
        tree = GitTree(self.root)
        self.evidence = VerifiedBaseline(self.base, tree.tree, self.base, self.base, 77, 1, 900, tree.fingerprint())
        graphs[1] = {"edges": [["A", "x1"], ["x1", "O"]], "weights": [1, 1]}
        write_graph_catalog(self.data / "graphs.json", graphs)
        self.commit("edit just the second realization")
        plan = self.plan()
        self.assertEqual(plan.selected[2]["graphs"], [1])
        task = next(task for task in plan.tasks if task["kind"] == "graphs")
        with patch("hec.checks._check_graph_pair", wraps=_check_graph_pair) as exact:
            self.assertTrue(run_task(plan, task["task_id"], self.root)["ok"])
        self.assertEqual([call.args[0][0] for call in exact.call_args_list], [1])

    def test_old_sparse_payload_need_not_be_downloaded_again(self):
        self.add_facet()
        self.commit("append")
        plan = self.plan()
        previous = json.loads(plan.old.tree.read("data/n=2/proofs.json"))
        for key in previous["shards"]:
            (self.data / "proof-shards" / (key + ".proofpack")).unlink()
        result = check_storage_delta(plan, self.root)
        self.assertGreater(result["byte_identical_files_reused"], 0)
        new = next(key for key in self.doc("proofs.json")["shards"] if key not in previous["shards"])
        (self.data / "proof-shards" / (new + ".proofpack")).write_bytes(b"bad")
        with self.assertRaises(ValueError):
            check_storage_delta(plan, self.root)

    def test_stale_readme_and_forged_task_are_not_acceptance(self):
        self.add_facet()
        self.commit("append")
        (self.root / "README.md").write_text((self.root / "README.md").read_text().replace("| 2 | 2 |", "| 2 | 1 |"))
        self.commit("stale docs", refresh=False)
        plan = self.plan()
        with self.assertRaisesRegex(ValueError, "README"):
            check_catalogue_delta(plan, self.root)
        with self.assertRaisesRegex(ValueError, "task"):
            run_task(plan, "f" * 64, self.root)

    def test_mutating_a_discovered_selection_cannot_hide_new_invalid_results(self):
        self.add_facet(bad=True)
        self.commit("new invalid result")
        plan = self.plan()
        task = next(task for task in plan.tasks if task["kind"] == "contractions")
        task["indices"] = [0]
        with self.assertRaisesRegex(ValueError, "plan changed"):
            run_task(plan, task["task_id"], self.root)
        with self.assertRaisesRegex(ValueError, "ownership"):
            plan._require_planned_coverage()

    def test_payload_reencoding_reuses_math_but_checks_new_storage_bytes(self):
        graphs = list(GraphCatalog(self.data / "graphs.json"))
        raw = json.dumps(graphs, indent=1).encode()
        from hashlib import sha256

        key = sha256(raw).hexdigest()
        (self.data / "graph-shards" / (key + ".json")).write_bytes(raw)
        self.write(
            "graphs.json",
            {
                "format": "hec-graph-catalogue",
                "count": len(graphs),
                "shards": [{"sha256": key, "bytes": len(raw), "count": len(graphs)}],
            },
        )
        self.commit("same graph records in a new byte encoding")
        plan = self.plan()
        self.assertEqual([task["kind"] for task in plan.tasks], ["acceptance"])
        self.assertGreater(check_storage_delta(plan, self.root)["new_or_changed_files_verified"], 0)

    def test_ray_frame_change_rechecks_the_paired_graph(self):
        self.write("rays.json", [[1, 0, 1]])
        self.commit("different entropy vector without corresponding graph")
        plan = self.plan()
        self.assertEqual(plan.selected[2]["facets"], [])  # Same S3 orbit preserves the old rank basis.
        self.assertEqual(plan.selected[2]["rays"], [0])
        self.assertEqual(plan.selected[2]["graphs"], [0])
        task = next(task for task in plan.tasks if task["kind"] == "graphs")
        with self.assertRaisesRegex(ValueError, "mismatch"):
            run_task(plan, task["task_id"], self.root)

    def test_unknown_data_paths_are_not_silently_ignored(self):
        (self.data / "unindexed-result.json").write_text("{}")
        self.commit("unknown data path", refresh=False)
        with self.assertRaisesRegex(ValueError, "unrecognized"):
            self.plan()

    def test_changed_witness_models_invalidate_their_dependent_facet(self):
        from test_facet_witnesses import model, write

        self.write("rays.json", [[1, 0, 1]])
        write_graph_catalog(self.data / "graphs.json", [{"edges": [["A", "O"]], "weights": [1]}])
        write(self.data)
        self.base = self.commit("accepted explicit rank witness")
        tree = GitTree(self.root)
        self.evidence = VerifiedBaseline(self.base, tree.tree, self.base, self.base, 77, 1, 900, tree.fingerprint())
        invalid = model()
        invalid["capacities"] = ["2"]
        write(self.data, proposal=invalid)
        self.commit("changed but invalid exact witness model")
        plan = self.plan()
        self.assertEqual(plan.selected[2]["facets"], [0])
        self.assertEqual(plan.selected[2]["contractions"], [])
        task = next(task for task in plan.tasks if task["kind"] == "facets")
        with self.assertRaises(ValueError):
            run_task(plan, task["task_id"], self.root)

    def test_hashed_payload_edits_without_updating_index_fail_closed(self):
        write_ray_catalog(self.data / "rays.json", [[1, 1, 0]], 2)
        self.base = self.commit("accepted sharded rays")
        tree = GitTree(self.root)
        self.evidence = VerifiedBaseline(self.base, tree.tree, self.base, self.base, 77, 1, 900, tree.fingerprint())
        path = next((self.data / "ray-shards").iterdir())
        path.write_text("[[1,0,1]]")
        self.commit("changed immutable ray bytes without matching index", refresh=False)
        with self.assertRaisesRegex(ValueError, "content identity"):
            self.plan()


class DependencyTests(IncrementalFixtures):
    n = 3

    def replace_proofs(self, documents):
        with tempfile.TemporaryDirectory(prefix="hec-replaced-proof-control-") as name:
            directory = Path(name)
            write_frames(directory, documents)
            for path in (directory / "proof-shards").iterdir():
                shutil.copy2(path, self.data / "proof-shards" / path.name)
            shutil.copy2(directory / "proofs.json", self.data / "proofs.json")
        self.write("inequalities.json", inequality_catalog(documents))

    def test_facet_removal_invalidates_every_ray_rank(self):
        facets = self.doc("facets.json")
        self.assertGreater(len(facets), 1)
        keep = facets[:1]
        target = inequality_id(geometry(3, tuple(keep[0])))
        catalog = ProofCatalog(self.data / "proofs.json")
        documents = [catalog[index] for index, entry in enumerate(catalog.entries) if entry["inequality_id"] == target]
        self.replace_proofs(documents)
        self.write("facets.json", keep)
        self.commit("remove a supporting facet")
        plan = self.plan()
        self.assertEqual(plan.selected[3]["rays"], list(range(len(self.doc("rays.json")))))
        self.assertEqual(plan.catalogue_mode, "full")

    def test_ray_removal_invalidates_every_facet_rank(self):
        rays = self.doc("rays.json")
        graphs = list(GraphCatalog(self.data / "graphs.json"))
        self.assertGreater(len(rays), 1)
        self.write("rays.json", rays[:1])
        write_graph_catalog(self.data / "graphs.json", graphs[:1])
        self.commit("remove a supporting ray")
        plan = self.plan()
        self.assertEqual(plan.selected[3]["facets"], list(range(len(self.doc("facets.json")))))
        self.assertEqual(plan.selected[3]["contractions"], [])
        self.assertEqual(plan.catalogue_mode, "full")


class ExplicitCoverageTests(unittest.TestCase):
    def test_selected_complete_proofs_are_cost_balanced_without_missing_or_duplicate_ownership(self):
        from hec.incremental_ci import proof_batches

        catalog = SimpleNamespace(entries=[{"inequality_id": str(i), "proof_id": str(i)} for i in range(12)])
        inequalities = SimpleNamespace(entries={str(i): {"weight": (1 << 29) if i % 2 else 1} for i in range(12)})
        selected = [1, 3, 4, 5, 7, 8, 9, 11]
        with patch("hec.incremental_ci.proof_work", side_effect=lambda entry: entry["weight"]):
            batches = proof_batches(catalog, inequalities, selected)
        self.assertEqual(sorted(index for batch in batches for index in batch), selected)
        self.assertTrue(all(batches))
        self.assertGreater(len(batches), 1)

    def test_explicit_row_coverage_rejects_duplicates_missing_and_foreign_rows(self):
        from hec.checks import _RowCoverage, _selected_rows

        selected = _selected_rows(20, 0, 1, "round-robin", [3, 11])
        coverage = _RowCoverage(selected)
        coverage.add(3)
        with self.assertRaisesRegex(ValueError, "duplicate"):
            coverage.add(3)
        with self.assertRaisesRegex(ValueError, "out-of-partition"):
            coverage.add(4)
        with self.assertRaisesRegex(ValueError, "incomplete"):
            coverage.require_complete()
        coverage.add(11)
        coverage.require_complete()
        for invalid in ([], [3, 3], [11, 3], [-1], [20], [True]):
            with self.assertRaises(ValueError):
                _selected_rows(20, 0, 1, "round-robin", invalid)

    def test_delta_orbit_counts_match_explicit_unique_images(self):
        for n in range(1, 5):
            rows = np.random.default_rng(n).integers(-2, 3, size=(7, (1 << n) - 1))
            maps = permutation_array(n)
            expected = sum(len({tuple(image) for image in row[maps]}) for row in rows)
            self.assertEqual(orbit_sum(rows, n), expected)


class MetadataTransportTests(unittest.TestCase):
    def test_transient_metadata_read_retries_without_changing_authentication_rules(self):
        import hec.ci_baseline as baseline

        failure = subprocess.CalledProcessError(1, "gh", stderr=b"gh: HTTP 502 Bad Gateway")
        with (
            patch.object(
                baseline.subprocess, "run", side_effect=[failure, SimpleNamespace(stdout=b'{"ok":true}')]
            ) as run,
            patch.object(baseline.time, "sleep") as sleep,
        ):
            self.assertEqual(
                GitHub("fixture/repository").request("actions/workflows/database-integrity.yml"), {"ok": True}
            )
        self.assertEqual(run.call_count, 2)
        sleep.assert_called_once_with(1)
        self.assertIn("--hostname", run.call_args.args[0])

    def test_authentication_errors_are_not_retried_or_called_success(self):
        import hec.ci_baseline as baseline

        failure = subprocess.CalledProcessError(1, "gh", stderr=b"gh: HTTP 401 Unauthorized")
        with (
            patch.object(baseline.subprocess, "run", side_effect=failure) as run,
            patch.object(baseline.time, "sleep") as sleep,
        ):
            with self.assertRaises(subprocess.CalledProcessError):
                GitHub("fixture/repository").request("checks")
        self.assertEqual(run.call_count, 1)
        sleep.assert_not_called()

    def test_workflow_receipt_producer_matches_the_authenticated_parser(self):
        root = Path(__file__).resolve().parents[1]
        workflow = (root / ".github/workflows/database-integrity.yml").read_text()
        gate = workflow.split("  gate:\n", 1)[1]
        code = gate.split("python3 - <<'PY'\n", 1)[1].rsplit("\n          PY", 1)[0]
        environment = dict(
            os.environ,
            TESTED_COMMIT="a" * 40,
            TESTED_TREE="b" * 40,
            VERIFIER="c" * 64,
            AUDIT_PLAN="d" * 64,
            AUDIT_MODE="incremental",
        )
        result = subprocess.run(
            [sys.executable, "-c", textwrap.dedent(code)], env=environment, capture_output=True, text=True, check=True
        )
        prefix = "::notice title=HEC integrity acceptance v1::"
        self.assertTrue(result.stdout.startswith(prefix))
        record = {
            "title": "HEC integrity acceptance v1",
            "annotation_level": "notice",
            "message": result.stdout.removeprefix(prefix).strip(),
        }
        self.assertEqual(acceptance_receipt([[record]], "c" * 64)["tree"], "b" * 40)
