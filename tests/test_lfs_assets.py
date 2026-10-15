import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from hec import storage as lfs
from hec.count_proofs import geometry, inequality_id


class LFSAssetsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="hec-lfs-tests-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.git("init", "-q")
        self.root.joinpath(".gitattributes").write_text(
            "data/n=*/proof-shards/*.proofpack filter=lfs diff=lfs merge=lfs -text\n"
            "data/n=*/archive*.zip filter=lfs diff=lfs merge=lfs -text\n"
        )
        self.binary = b"small compressed-map transfer fixture"
        self.oid = hashlib.sha256(self.binary).hexdigest()

    def git(self, *args):
        return subprocess.run(
            [
                "git",
                "-c",
                f"core.hooksPath={self.root / '.no-hooks'}",
                "-c",
                "core.fsmonitor=false",
                "-C",
                str(self.root),
                *args,
            ],
            check=True,
            capture_output=True,
            text=True,
        )

    def commit(self):
        self.git("add", ".")
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

    def shard(self, n=6, *, binary=None):
        binary = self.binary if binary is None else binary
        oid = hashlib.sha256(binary).hexdigest()
        directory = self.root / f"data/n={n}"
        directory.mkdir(parents=True, exist_ok=True)
        index = directory / "proofs.json"
        manifest = (
            json.loads(index.read_text())
            if index.exists()
            else {"format": "hec-proof-catalog/1", "entries": [], "shards": {}}
        )
        manifest["shards"][oid] = {"bytes": len(binary)}
        coefficients = (len(manifest["entries"]) + 1, 1, *((0,) * ((1 << n) - 3)))
        problem = geometry(n, coefficients)
        identity = inequality_id(problem)
        proof = hashlib.sha256(b"fixture-proof" + binary).hexdigest()
        manifest["entries"].append(
            {"inequality_id": identity, "proof_id": proof, "shard": oid, "offset": 0, "bytes": len(binary)}
        )
        index.write_text(json.dumps(manifest))
        inequalities = directory / "inequalities.json"
        bound = (
            json.loads(inequalities.read_text())
            if inequalities.exists()
            else {"format": "hec-inequality-catalog/1", "entries": []}
        )
        bound["entries"].append({"id": identity, **problem.inequality(), "proof_ids": [proof]})
        bound["entries"].sort(key=lambda entry: entry["id"])
        inequalities.write_text(json.dumps(bound))
        data = directory / "proof-shards" / f"{oid}.proofpack"
        data.parent.mkdir(exist_ok=True)
        data.write_text(f"version https://git-lfs.github.com/spec/v1\noid sha256:{oid}\nsize {len(binary)}\n")
        return index, data

    def seed_store(self, binary=None):
        binary = self.binary if binary is None else binary
        oid = hashlib.sha256(binary).hexdigest()
        target = self.root / ".git/lfs/objects" / oid[:2] / oid[2:4] / oid
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(binary)
        return target

    def test_plain_json_does_not_need_lfs(self):
        self.root.joinpath(".gitattributes").write_text(
            "data/n=6/proof-shards/*.proofpack filter=lfs diff=lfs merge=lfs -text\n"
        )
        _, path = self.shard(2)
        path.write_bytes(self.binary)
        self.commit()
        plan = lfs.make_plan(self.root)
        self.assertEqual(plan["assets"], [])
        self.assertEqual(plan["bytes"], 0)

    def test_plan_selects_active_stream_not_archives_or_inconclusive_data(self):
        self.shard()
        archive = self.root / "data/n=6/archive-unused.zip"
        archive.write_text(f"version https://git-lfs.github.com/spec/v1\noid sha256:{self.oid}\nsize 36\n")
        unrelated = self.root / "data/n=6/inconclusive/contractions.json"
        unrelated.parent.mkdir()
        unrelated.write_text("{}")
        self.commit()
        plan = lfs.make_plan(self.root)
        self.assertEqual([item["path"] for item in plan["assets"]], [f"data/n=6/proof-shards/{self.oid}.proofpack"])
        self.assertEqual(plan["required_ns"], [6])
        self.assertEqual(plan["bytes"], len(self.binary))

    def test_every_active_immutable_shard_is_selected(self):
        self.shard()
        self.shard(binary=b"additional proof segment")
        self.commit()
        self.assertEqual(len(lfs.make_plan(self.root)["objects"]), 2)

    def test_identical_objects_are_cached_once(self):
        self.shard(2)
        self.shard(6)
        self.commit()
        plan = lfs.make_plan(self.root)
        self.assertEqual(len(plan["assets"]), 2)
        self.assertEqual(len(plan["objects"]), 1)
        self.assertEqual(plan["bytes"], len(self.binary))

    def test_key_is_based_on_bytes_not_manifest_formatting(self):
        index, _ = self.shard()
        self.commit()
        initial = lfs.make_plan(self.root)["cache_key"]
        value = json.loads(index.read_text())
        index.write_text(json.dumps(value, indent=4))
        self.assertEqual(lfs.make_plan(self.root)["cache_key"], initial)

    def test_pointer_manifest_disagreement_fails_before_download(self):
        index, _ = self.shard()
        self.commit()
        value = json.loads(index.read_text())
        value["shards"][self.oid]["bytes"] += 1
        value["entries"][0]["bytes"] += 1  # Keep index coverage coherent; exercise the pointer/manifest check itself.
        index.write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError, "differs from the proof manifest"):
            lfs.make_plan(self.root)

    def test_invalid_pointer_cannot_be_cached(self):
        _, path = self.shard()
        path.write_text("not an LFS pointer")
        self.commit()
        with self.assertRaisesRegex(ValueError, "differs from the proof manifest"):
            lfs.make_plan(self.root)

    def test_noninteger_size_is_rejected(self):
        index, _ = self.shard()
        self.commit()
        value = json.loads(index.read_text())
        value["shards"][self.oid]["bytes"] = float(len(self.binary))
        index.write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError, "must be an integer|non-exact JSON"):
            lfs.make_plan(self.root)

    def test_cache_safety_cap_is_enforced(self):
        self.shard()
        self.commit()
        with patch.object(lfs, "MAX_CACHE_BYTES", 1):
            with self.assertRaisesRegex(ValueError, "safety cap"):
                lfs.make_plan(self.root)

    def test_offline_populate_reuses_local_lfs_store(self):
        self.shard()
        self.commit()
        self.seed_store()
        plan = lfs.make_plan(self.root)
        result = lfs.populate(self.root, plan, offline=True)
        self.assertEqual(result["requested_LFS_bytes"], 0)
        self.assertEqual(lfs.cache_path(self.root, self.oid).read_bytes(), self.binary)
        self.assertEqual(lfs.populate(self.root, plan, offline=True), result)

    def test_missing_objects_cannot_trigger_offline_download(self):
        self.shard()
        self.commit()
        with self.assertRaisesRegex(ValueError, "offline mode forbids"):
            lfs.populate(self.root, lfs.make_plan(self.root), offline=True)

    def test_one_filtered_fetch_and_no_recent_history(self):
        self.shard()
        self.commit()
        plan = lfs.make_plan(self.root)
        original = subprocess.run
        fetches = []

        def fake_fetch(command, *args, **kwargs):
            if "fetch" in command:
                fetches.append(command)
                self.seed_store()
                return subprocess.CompletedProcess(command, 0)
            return original(command, *args, **kwargs)

        with patch.object(lfs.subprocess, "run", side_effect=fake_fetch):
            result = lfs.populate(self.root, plan)
        self.assertEqual(len(fetches), 1)
        self.assertIn(f"--include=data/n=6/proof-shards/{self.oid}.proofpack", fetches[0])
        self.assertIn("--exclude=", fetches[0])
        self.assertIn("lfs.fetchrecentalways=false", fetches[0])
        self.assertEqual(fetches[0][-2:], ["origin", "HEAD"])
        self.assertEqual(result["requested_LFS_bytes"], len(self.binary))

    def test_consumers_select_only_owned_payload_shards(self):
        self.shard(binary=b"first shard")
        self.shard(binary=b"second shard")
        self.commit()
        self.seed_store(b"first shard")
        self.seed_store(b"second shard")
        plan = lfs.make_plan(self.root)
        lfs.populate(self.root, plan, offline=True)
        self.assertEqual(lfs.install(self.root, plan, 6, 0, 2), 1)
        self.assertEqual(lfs.install(self.root, plan, 6, 1, 2), 1)
        with self.assertRaises(ValueError):
            lfs.install(self.root, plan, 6, 2, 2)

    def test_consumer_installs_verified_bytes_without_network(self):
        _, path = self.shard()
        self.commit()
        self.seed_store()
        plan = lfs.make_plan(self.root)
        lfs.populate(self.root, plan, offline=True)
        with patch.object(lfs.subprocess, "run", side_effect=AssertionError("consumer must not fetch")):
            self.assertEqual(lfs.install(self.root, plan, 6), 1)
        self.assertEqual(path.read_bytes(), self.binary)
        self.assertEqual(lfs.make_plan(self.root)["cache_key"], plan["cache_key"])

    def test_consumer_cache_miss_fails_without_network(self):
        self.shard()
        self.commit()
        plan = lfs.make_plan(self.root)
        with patch.object(lfs.subprocess, "run", side_effect=AssertionError("consumer must not fetch")):
            with self.assertRaisesRegex(ValueError, "missing"):
                lfs.install(self.root, plan, 6)

    def test_corrupt_cache_is_rejected_not_silently_repaired(self):
        self.shard()
        self.commit()
        self.seed_store()
        plan = lfs.make_plan(self.root)
        lfs.populate(self.root, plan, offline=True)
        cached = lfs.cache_path(self.root, self.oid)
        cached.write_bytes(b"!" + self.binary[1:])
        with self.assertRaisesRegex(ValueError, "SHA256 mismatch"):
            lfs.populate(self.root, plan, offline=True)
        with self.assertRaisesRegex(ValueError, "SHA256 mismatch"):
            lfs.install(self.root, plan, 6)

    def test_symlink_cache_is_rejected(self):
        self.shard()
        self.commit()
        source = self.seed_store()
        plan = lfs.make_plan(self.root)
        cached = lfs.cache_path(self.root, self.oid)
        cached.parent.mkdir(parents=True)
        cached.symlink_to(source)
        with self.assertRaisesRegex(ValueError, "regular file"):
            lfs.verify_cache(self.root, plan)

    def test_workflow_has_one_producer_and_no_automatic_smudge(self):
        workflow = Path(__file__).parents[1] / ".github/workflows/database-integrity.yml"
        text = workflow.read_text()
        self.assertNotIn("lfs: true", text)
        self.assertIn('GIT_LFS_SKIP_SMUDGE: "1"', text)
        self.assertEqual(text.count("hec storage populate --fetch"), 1)
        self.assertIn("fail-on-cache-miss: true", text)
        self.assertIn("LFS_RESULT", text)

    def test_inventory_binds_all_actual_data_and_detects_edits(self):
        self.shard()
        self.commit()
        self.assertFalse(lfs.snapshot(self.root)["mathematical_acceptance"])
        self.assertFalse(lfs.audit_inventory(self.root)["LFS_payload_bytes_verified"])
        with self.assertRaisesRegex(ValueError, "already exists"):
            lfs.snapshot(self.root)
        (self.root / "data/n=6/notes.json").write_text("{}")
        with self.assertRaisesRegex(ValueError, "inventory differs"):
            lfs.audit_inventory(self.root)
        lfs.snapshot(self.root, replace=True)
        lfs.audit_inventory(self.root)
        with self.assertRaisesRegex(ValueError, "SHA256 mismatch"):
            lfs.audit_inventory(self.root, payloads=True)

    def test_offline_source_root_is_hash_checked_without_lfs_or_network(self):
        _, path = self.shard()
        self.commit()
        plan = lfs.make_plan(self.root)
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)
            payload = source / path.relative_to(self.root)
            payload.parent.mkdir(parents=True)
            payload.write_bytes(self.binary)
            with patch.object(
                lfs.subprocess, "run", side_effect=AssertionError("offline source must not call Git/LFS")
            ):
                result = lfs.populate(self.root, plan, offline=True, source_root=source)
            self.assertEqual(result["requested_LFS_bytes"], 0)
            self.assertEqual(lfs.cache_path(self.root, self.oid).read_bytes(), self.binary)

    def test_unindexed_active_payload_cannot_silently_enter_the_cache(self):
        self.shard()
        self.commit()
        (self.root / "data/n=6/proof-shards/unindexed.proofpack").write_bytes(b"extra")
        with self.assertRaisesRegex(ValueError, "unindexed"):
            lfs.make_plan(self.root)

    def test_inventory_and_install_reject_unsafe_paths_and_symlink_parents(self):
        for relative in ("../outside", "/outside", "data/../outside", "data\\outside", "C:/outside", "data//x"):
            with self.assertRaises(ValueError):
                lfs.safe_path(self.root, relative)
        directory = self.root / "linked"
        directory.symlink_to(self.root / "data", target_is_directory=True)
        with self.assertRaises(ValueError):
            lfs.safe_path(self.root, "linked/file")

    def test_cache_compaction_preserves_recoverable_old_bytes_and_current_objects(self):
        self.shard()
        self.commit()
        self.seed_store()
        plan = lfs.make_plan(self.root)
        lfs.populate(self.root, plan, offline=True)
        obsolete = b"previous cache generation, not an authoritative proof"
        oid = hashlib.sha256(obsolete).hexdigest()
        old = lfs.cache_path(self.root, oid)
        old.write_bytes(obsolete)
        result = lfs.compact_cache(self.root, plan)
        self.assertEqual(result["retired_cache_objects"], 1)
        self.assertFalse(old.exists())
        self.assertEqual((Path(result["recoverable_at"]) / oid).read_bytes(), obsolete)
        lfs.verify_cache(self.root, plan)
        self.assertEqual(lfs.compact_cache(self.root, plan)["retired_cache_objects"], 0)


if __name__ == "__main__":
    unittest.main()
