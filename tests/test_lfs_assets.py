import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1] / ".github/scripts/lfs_assets.py"
SPEC = importlib.util.spec_from_file_location("hec_ci_lfs_assets", SOURCE)
lfs = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = lfs
SPEC.loader.exec_module(lfs)


class LFSAssetsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="hec-lfs-tests-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.git("init", "-q")
        self.root.joinpath(".gitattributes").write_text(
            "data/n=*/contractions*.zst filter=lfs diff=lfs merge=lfs -text\n"
            "data/n=*/archive*.zip filter=lfs diff=lfs merge=lfs -text\n"
        )
        self.binary = b"small compressed-map transfer fixture"
        self.oid = hashlib.sha256(self.binary).hexdigest()

    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.root), *args], check=True, capture_output=True, text=True)

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

    def packed(self, n=6, *, tail=False, binary=None):
        binary = self.binary if binary is None else binary
        oid = hashlib.sha256(binary).hexdigest()
        directory = self.root / f"data/n={n}"
        directory.mkdir(parents=True, exist_ok=True)
        manifest = {
            "schema_version": 1,
            "kind": "packed-contraction-tail" if tail else "packed-contractions",
            "n": n,
            "compressed_sha256": oid,
            "compressed_size": len(binary),
        }
        index = directory / ("contractions-tail.index.json" if tail else "contractions.json")
        index.write_text(json.dumps(manifest))
        data = directory / ("contractions-tail.packbits.zst" if tail else "contractions.packbits.zst")
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
        directory = self.root / "data/n=2"
        directory.mkdir(parents=True)
        directory.joinpath("contractions.json").write_text("[]")
        self.commit()
        plan = lfs.make_plan(self.root)
        self.assertEqual(plan["assets"], [])
        self.assertEqual(plan["bytes"], 0)

    def test_plan_selects_active_stream_not_archives_or_inconclusive_data(self):
        self.packed()
        archive = self.root / "data/n=6/archive-unused.zip"
        archive.write_text(f"version https://git-lfs.github.com/spec/v1\noid sha256:{self.oid}\nsize 36\n")
        unrelated = self.root / "data/n=6/inconclusive/contractions.json"
        unrelated.parent.mkdir()
        unrelated.write_text("{}")
        self.commit()
        plan = lfs.make_plan(self.root)
        self.assertEqual([item["path"] for item in plan["assets"]], ["data/n=6/contractions.packbits.zst"])
        self.assertEqual(plan["required_ns"], [6])
        self.assertEqual(plan["bytes"], len(self.binary))

    def test_append_only_tail_is_selected(self):
        self.packed()
        self.packed(tail=True, binary=b"additional proof segment")
        self.commit()
        self.assertEqual(len(lfs.make_plan(self.root)["objects"]), 2)

    def test_identical_objects_are_cached_once(self):
        self.packed(2)
        self.packed(6)
        self.commit()
        plan = lfs.make_plan(self.root)
        self.assertEqual(len(plan["assets"]), 2)
        self.assertEqual(len(plan["objects"]), 1)
        self.assertEqual(plan["bytes"], len(self.binary))

    def test_key_is_based_on_bytes_not_manifest_formatting(self):
        index, _ = self.packed()
        self.commit()
        initial = lfs.make_plan(self.root)["cache_key"]
        value = json.loads(index.read_text())
        value["unrelated_annotation"] = "new note"
        index.write_text(json.dumps(value, indent=4))
        self.assertEqual(lfs.make_plan(self.root)["cache_key"], initial)

    def test_pointer_manifest_disagreement_fails_before_download(self):
        index, _ = self.packed()
        self.commit()
        value = json.loads(index.read_text())
        value["compressed_sha256"] = "0" * 64
        index.write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError, "differs from the proof manifest"):
            lfs.make_plan(self.root)

    def test_invalid_pointer_cannot_be_cached(self):
        _, path = self.packed()
        path.write_text("not an LFS pointer")
        self.commit()
        with self.assertRaisesRegex(ValueError, "differs from the proof manifest"):
            lfs.make_plan(self.root)

    def test_noninteger_size_is_rejected(self):
        index, _ = self.packed()
        self.commit()
        value = json.loads(index.read_text())
        value["compressed_size"] = float(len(self.binary))
        index.write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError, "must be an integer"):
            lfs.make_plan(self.root)

    def test_cache_safety_cap_is_enforced(self):
        self.packed()
        self.commit()
        with patch.object(lfs, "MAX_CACHE_BYTES", 1):
            with self.assertRaisesRegex(ValueError, "safety cap"):
                lfs.make_plan(self.root)

    def test_offline_populate_reuses_local_lfs_store(self):
        self.packed()
        self.commit()
        self.seed_store()
        plan = lfs.make_plan(self.root)
        result = lfs.populate(self.root, plan, offline=True)
        self.assertEqual(result["requested_LFS_bytes"], 0)
        self.assertEqual(lfs.cache_path(self.root, self.oid).read_bytes(), self.binary)
        self.assertEqual(lfs.populate(self.root, plan, offline=True), result)

    def test_missing_objects_cannot_trigger_offline_download(self):
        self.packed()
        self.commit()
        with self.assertRaisesRegex(ValueError, "offline mode forbids"):
            lfs.populate(self.root, lfs.make_plan(self.root), offline=True)

    def test_one_filtered_fetch_and_no_recent_history(self):
        self.packed()
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
        self.assertIn("--include=data/n=6/contractions.packbits.zst", fetches[0])
        self.assertIn("--exclude=", fetches[0])
        self.assertIn("lfs.fetchrecentalways=false", fetches[0])
        self.assertEqual(fetches[0][-2:], ["origin", "HEAD"])
        self.assertEqual(result["requested_LFS_bytes"], len(self.binary))

    def test_consumer_installs_verified_bytes_without_network(self):
        _, path = self.packed()
        self.commit()
        self.seed_store()
        plan = lfs.make_plan(self.root)
        lfs.populate(self.root, plan, offline=True)
        with patch.object(lfs.subprocess, "run", side_effect=AssertionError("consumer must not fetch")):
            self.assertEqual(lfs.install(self.root, plan, 6), 1)
        self.assertEqual(path.read_bytes(), self.binary)
        self.assertEqual(lfs.make_plan(self.root)["cache_key"], plan["cache_key"])

    def test_consumer_cache_miss_fails_without_network(self):
        self.packed()
        self.commit()
        plan = lfs.make_plan(self.root)
        with patch.object(lfs.subprocess, "run", side_effect=AssertionError("consumer must not fetch")):
            with self.assertRaisesRegex(ValueError, "missing"):
                lfs.install(self.root, plan, 6)

    def test_corrupt_cache_is_rejected_not_silently_repaired(self):
        self.packed()
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
        self.packed()
        self.commit()
        source = self.seed_store()
        plan = lfs.make_plan(self.root)
        cached = lfs.cache_path(self.root, self.oid)
        cached.parent.mkdir(parents=True)
        cached.symlink_to(source)
        with self.assertRaisesRegex(ValueError, "regular file"):
            lfs.verify_cache(self.root, plan)

    def test_workflow_has_one_producer_and_no_automatic_smudge(self):
        workflow = SOURCE.parents[1] / "workflows/database-integrity.yml"
        text = workflow.read_text()
        self.assertNotIn("lfs: true", text)
        self.assertIn('GIT_LFS_SKIP_SMUDGE: "1"', text)
        self.assertEqual(text.count("lfs_assets.py populate"), 1)
        self.assertIn("fail-on-cache-miss: true", text)
        self.assertIn("LFS_RESULT", text)


if __name__ == "__main__":
    unittest.main()
