"""Ordinary-Git data, offline operation, sparse planning and clean ancestry."""

import copy
import hashlib
import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from hec import storage
from hec.count_proofs import geometry, inequality_id
from hec.graph_store import GraphCatalog, write_graph_catalog
from hec.ray_store import RayCatalog, write_ray_catalog


class GitStorageTests(unittest.TestCase):
    def test_ray_payloads_have_complete_ownership_and_actual_byte_checks(self):
        self.shard(n=2)
        path = self.root / "data/n=2/rays.json"
        write_ray_catalog(path, [(1, 2, 3), (2, 3, 4)], 2, shard_bytes=20)
        self.commit()
        storage.snapshot(self.root)
        self.assertEqual(len(storage.make_plan(self.root)["ray_payloads"]), 2)
        storage.audit_inventory(self.root)
        catalog = RayCatalog(path, 2)
        payload = path.parent / catalog.shards[0].path
        saved = payload.read_bytes()
        payload.write_bytes(saved[:-1])
        with self.assertRaises(ValueError):
            storage.audit_inventory(self.root)
        payload.write_bytes(saved)
        extra = payload.parent / ("0" * 64 + ".json")
        extra.write_text("[]")
        with self.assertRaisesRegex(ValueError, "unindexed.*ray"):
            storage.make_plan(self.root)
        extra.unlink()
        payload.unlink()
        self.assertTrue(storage.make_plan(self.root)["ray_payloads"])
        with self.assertRaisesRegex(ValueError, "absent"):
            storage.audit_inventory(self.root)

    def test_graph_payloads_have_complete_ownership_and_actual_byte_checks(self):
        self.shard(n=2)
        path = self.root / "data/n=2/graphs.json"
        write_graph_catalog(path, [{"edges": [["A", "O"]], "weights": [1]}])
        self.commit()
        storage.snapshot(self.root)
        self.assertEqual(len(storage.make_plan(self.root)["graph_payloads"]), 1)
        storage.audit_inventory(self.root)
        catalog = GraphCatalog(path)
        payload = path.parent / catalog.shards[0].path
        saved = payload.read_bytes()
        payload.write_bytes(saved[:-1])
        with self.assertRaises(ValueError):
            storage.audit_inventory(self.root)
        payload.write_bytes(saved)
        extra = payload.parent / ("0" * 64 + ".json")
        extra.write_text("[]")
        with self.assertRaisesRegex(ValueError, "unindexed.*graph"):
            storage.make_plan(self.root)
        extra.unlink()
        payload.unlink()
        self.assertTrue(storage.make_plan(self.root)["graph_payloads"])
        with self.assertRaisesRegex(ValueError, "absent"):
            storage.audit_inventory(self.root)

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="hec-git-storage-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.git("init", "-q", "-b", "main")
        self.root.joinpath(".gitattributes").write_text("*.proofpack -text -diff\n*.zst -text -diff\n")
        self.binary = b"ordinary Git exact-proof transfer fixture"

    def git(self, *args):
        return subprocess.run(
            [
                "git",
                "-c",
                f"core.hooksPath={self.root / '.no-hooks'}",
                "-c",
                "core.fsmonitor=false",
                "-c",
                "filter.lfs.process=",
                "-c",
                "filter.lfs.clean=cat",
                "-c",
                "filter.lfs.required=false",
                "-C",
                str(self.root),
                *args,
            ],
            check=True,
            capture_output=True,
            text=True,
        )

    def commit(self):
        self.git("add", "--all")
        self.git(
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "commit",
            "--no-gpg-sign",
            "-qm",
            "fixture",
        )

    def shard(self, n=6, binary=None):
        binary = self.binary if binary is None else binary
        sha = hashlib.sha256(binary).hexdigest()
        directory = self.root / f"data/n={n}"
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / "proofs.json"
        catalog = (
            json.loads(path.read_text())
            if path.exists()
            else {"format": "hec-proof-catalog", "entries": [], "shards": {}}
        )
        p = geometry(n, (len(catalog["entries"]) + 1, 1, *((0,) * ((1 << n) - 3))))
        identity, proof = inequality_id(p), hashlib.sha256(b"proof" + binary).hexdigest()
        catalog["shards"][sha] = {"bytes": len(binary)}
        catalog["entries"].append(
            {"inequality_id": identity, "proof_id": proof, "shard": sha, "offset": 0, "bytes": len(binary)}
        )
        path.write_text(json.dumps(catalog))
        inequalities = directory / "inequalities.json"
        bound = (
            json.loads(inequalities.read_text())
            if inequalities.exists()
            else {"format": "hec-inequality-catalog", "entries": []}
        )
        bound["entries"].append({"id": identity, **p.inequality(), "proof_ids": [proof]})
        bound["entries"].sort(key=lambda entry: entry["id"])
        inequalities.write_text(json.dumps(bound))
        payload = directory / "proof-shards" / f"{sha}.proofpack"
        payload.parent.mkdir(exist_ok=True)
        payload.write_bytes(binary)
        return path, payload

    def test_all_required_bytes_are_plain_git_blobs_without_an_artifact_cache(self):
        _, payload = self.shard()
        self.commit()
        plan = storage.make_plan(self.root)
        self.assertEqual(plan["payload_bytes"], len(self.binary))
        self.assertEqual(plan["proofs"], 1)
        self.assertEqual(self.git("show", f"HEAD:{payload.relative_to(self.root)}").stdout.encode(), self.binary)
        self.assertFalse(plan["content_verified"])
        self.assertFalse(plan["mathematical_acceptance"])
        storage.snapshot(self.root)
        result = storage.audit_inventory(self.root)
        self.assertTrue(result["content_verified"])
        self.assertFalse(result["mathematical_acceptance"])
        self.assertFalse((self.root / ".git/lfs").exists())

    def test_integral_and_pointer_bytes_have_no_alternate_acceptance_path(self):
        pointer = b"version https://git-lfs.github.com/spec/v1\noid sha256:" + b"0" * 64 + b"\nsize 99\n"
        self.shard(binary=pointer)
        self.commit()
        self.assertEqual(storage.make_plan(self.root)["proofs"], 1)
        with self.assertRaisesRegex(ValueError, "pointers are forbidden"):
            storage.snapshot(self.root)

    def test_sparse_planning_is_not_missing_byte_acceptance(self):
        _, payload = self.shard()
        self.commit()
        storage.snapshot(self.root)
        payload.unlink()
        self.assertFalse(storage.make_plan(self.root)["content_verified"])
        with self.assertRaisesRegex(ValueError, "absent"):
            storage.audit_inventory(self.root)

    def test_unindexed_payloads_and_empty_datasets_are_rejected(self):
        with self.assertRaises(ValueError):
            storage.make_plan(self.root)
        _, payload = self.shard()
        (payload.parent / "extra.proofpack").write_bytes(b"extra")
        with self.assertRaisesRegex(ValueError, "unindexed|unexpected production data path"):
            storage.make_plan(self.root)

    def test_changed_bytes_or_declared_lengths_cannot_pass_hash_inventory(self):
        _, payload = self.shard()
        self.commit()
        storage.snapshot(self.root)
        payload.write_bytes(b"!" + self.binary[1:])
        with self.assertRaisesRegex(ValueError, "identity"):
            storage.audit_inventory(self.root)

    def test_snapshot_replacement_requires_explicit_intent_and_unknown_formats_fail(self):
        self.shard()
        self.commit()
        storage.snapshot(self.root)
        with self.assertRaisesRegex(ValueError, "exists"):
            storage.snapshot(self.root)
        path = self.root / storage.INVENTORY
        old = json.loads(path.read_text())
        old["format"] = "unrecognized-storage"
        old["entries"][0]["storage"] = "lfs"
        path.write_text(json.dumps(old))
        with self.assertRaises(ValueError):
            storage.audit_inventory(self.root)
        storage.snapshot(self.root, replace=True)
        self.assertTrue(storage.audit_inventory(self.root)["content_verified"])

    def test_boolean_metadata_and_unsafe_paths_are_rejected(self):
        self.shard()
        self.commit()
        storage.snapshot(self.root)
        path = self.root / storage.INVENTORY
        doc = json.loads(path.read_text())
        bad = copy.deepcopy(doc)
        bad["entries"][0]["bytes"] = True
        path.write_text(json.dumps(bad))
        with self.assertRaises(ValueError):
            storage.audit_inventory(self.root)
        for relative in ("../outside", "/outside", "data/../outside", "data\\outside", "data//x"):
            with self.assertRaises(ValueError):
                storage.safe_path(self.root, relative)
        (self.root / "link").symlink_to(self.root / "data", target_is_directory=True)
        with self.assertRaises(ValueError):
            storage.safe_path(self.root, "link/file")

    def test_oversized_declared_payload_fails_before_any_download_or_acceptance(self):
        self.shard()
        with patch.object(storage, "MAX_GIT_FILE_BYTES", 1):
            with self.assertRaisesRegex(ValueError, "ordinary-Git file limit"):
                storage.make_plan(self.root)

    def test_no_transfer_cache_or_lfs_commands_are_available(self):
        for name in ("populate", "install", "compact_cache", "verify_cache", "payload_entry"):
            self.assertFalse(hasattr(storage, name))
        self.shard()
        self.commit()
        result = subprocess.run(
            [sys.executable, "-m", "hec", "storage", "populate", "--root", str(self.root)], capture_output=True
        )
        self.assertNotEqual(result.returncode, 0)

    def test_clean_history_reports_every_reachable_blob(self):
        self.shard()
        self.commit()
        result = storage.history_audit(self.root, all_refs=True)
        self.assertEqual(result["LFS_pointers"], 0)
        self.assertEqual(result["LFS_filters"], 0)
        self.assertEqual(result["commits"], 1)
        self.assertGreater(result["blobs"], 0)

    def test_deleted_pointer_still_fails_history_hygiene(self):
        self.shard()
        pointer = self.root / "old-pointer"
        pointer.write_text("version https://git-lfs.github.com/spec/v1\noid sha256:" + "0" * 64 + "\nsize 1\n")
        self.commit()
        pointer.unlink()
        self.commit()
        with self.assertRaisesRegex(ValueError, "reachable LFS pointer"):
            storage.history_audit(self.root)

    def test_retired_filter_after_long_comments_and_deleted_config_fail_history(self):
        self.shard()
        self.root.joinpath(".gitattributes").write_text("# padding\n" * 200 + "*.proofpack filter=lfs\n")
        self.commit()
        self.root.joinpath(".gitattributes").write_text("*.proofpack -text\n")
        self.commit()
        with self.assertRaisesRegex(ValueError, "filter remains"):
            storage.history_audit(self.root)

    def test_deleted_configuration_is_not_hidden_by_a_clean_head(self):
        self.shard()
        config = self.root / ".lfsconfig"
        config.write_text("[lfs]\n")
        self.commit()
        config.unlink()
        self.commit()
        with self.assertRaisesRegex(ValueError, "configuration remains"):
            storage.history_audit(self.root)

    def test_workflow_uses_normal_git_sparse_payloads_and_mandatory_storage_gate(self):
        text = (Path(__file__).parents[1] / ".github/workflows/database-integrity.yml").read_text()
        for obsolete in ("git lfs", "prepare_lfs", ".hec-ci-lfs", "GIT_LFS_SKIP_SMUDGE", "actions/cache/"):
            self.assertNotIn(obsolete, text)
        self.assertIn("matrix.checkout_paths", text)
        self.assertIn("hec storage history", text)
        self.assertIn("hec storage audit", text)
        self.assertIn('"$STORAGE_RESULT" != "success"', text)

    def test_history_cutover_candidate_can_run_the_complete_gate_without_a_pr_merge(self):
        text = (Path(__file__).parents[1] / ".github/workflows/database-integrity.yml").read_text()
        self.assertIn('branches: [main, "codex/lfs-free-main-*"]', text)
        self.assertIn("  workflow_dispatch:", text)
        self.assertIn("needs: [quality, catalogue, distribution, storage, discover, validate]", text)
        self.assertIn("CATALOGUE_RESULT", text)
        self.assertIn("needs.discover.outputs.test_plan_sha256", text)
        self.assertIn("--partition unit --expected-plan", text)
        self.assertIn("--partition catalogue --expected-plan", text)

    def test_historical_records_cannot_become_production_dependencies(self):
        self.shard()
        for relative in (
            "provenance/contractions/run/receipt.json",
            "data/contraction-corpus.json",
            "data/n=6/inconclusive/candidates.json",
            "data/n=6/run-report.json",
        ):
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('{"ok":true}')
            with self.subTest(path=relative), self.assertRaisesRegex(ValueError, "unexpected production data path"):
                storage.make_plan(self.root)
            path.unlink()

    def test_storage_and_planning_need_only_current_self_contained_data(self):
        self.shard()
        self.commit()
        plan = storage.make_plan(self.root)
        self.assertEqual(plan["proofs"], 1)
        self.assertEqual(len(plan["payloads"]), 1)
        self.assertTrue(all(row["path"].startswith("data/n=6/proof-shards/") for row in plan["payloads"]))
        storage.snapshot(self.root)
        result = storage.audit_inventory(self.root)
        self.assertTrue(result["content_verified"])
        self.assertFalse(result["mathematical_acceptance"])
        self.assertFalse((self.root / "provenance").exists())

    def test_proof_ids_cannot_be_reused_in_another_party_frame(self):
        self.shard(n=2)
        self.shard(n=3)
        with self.assertRaisesRegex(ValueError, "repeated"):
            storage.make_plan(self.root)

    def test_inventory_schema_admits_only_current_production_artifacts(self):
        schema = json.loads((Path(__file__).parents[1] / "schemas/repository.schema.json").read_text())
        pattern = schema["$defs"]["storage"]["properties"]["entries"]["items"]["properties"]["path"]["pattern"]
        self.shard(n=2)
        storage.snapshot(self.root)
        inventory = json.loads((self.root / storage.INVENTORY).read_text())
        for entry in inventory["entries"]:
            self.assertIsNotNone(re.fullmatch(pattern, entry["path"]))
        for path in ("provenance/run.json", "data/contraction-corpus.json", "data/n=2/inconclusive/rows.json"):
            self.assertIsNone(re.fullmatch(pattern, path))


if __name__ == "__main__":
    unittest.main()
