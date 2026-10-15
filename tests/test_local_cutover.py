"""Local replacement is gated, recoverable and never writes the Git/LFS index."""

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

import test_repository_acceptance as fixtures
from corpus_derivations import local_cutover as local
from corpus_derivations import run as d

from hec.proof_store import ProofCatalog


class LocalCutoverTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.RepositoryAcceptanceTests(
            "test_real_complete_fixture_reconciles_without_new_audits_or_database_writes"
        )
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.complete()
        self.review = self.fixture.review(**self.fixture.fixture.options)
        self.temporary = tempfile.TemporaryDirectory(prefix="hec-local-cutover-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.git("init", "-q")
        binding = json.loads((Path(self.review["audit"]) / "run-binding.json").read_bytes())
        self.old = {}
        for n in binding["catalogs"]:
            directory = self.repo / "data" / f"n={n}"
            (directory / "proof-shards").mkdir(parents=True)
            for relative, data in (
                ("proofs.json", b"old catalogue\n"),
                ("inequalities.json", b"old inequalities\n"),
                ("proof-shards/" + "a" * 64 + ".proofpack", b"old immutable bytes\n"),
            ):
                path = directory / relative
                path.write_bytes(data)
                self.old[path.relative_to(self.repo).as_posix()] = data
            (directory / "facets.json").write_bytes(b"preserve known facet records\n")
        self.git("add", ".")
        self.git(
            "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-qm", "old artifacts"
        )
        self.review_path = self.root / "review.json"
        d.save_new(self.review_path, self.review)
        self.archive = self.root / "archive" / "originals"

    def git(self, *args):
        return subprocess.run(
            ["git", "-C", str(self.repo), *args], capture_output=True, text=True, check=True
        ).stdout.strip()

    def run_cutover(self, **options):
        return local.cutover(
            self.repo, self.review_path, d.digest(self.review_path), self.archive, _expected_total=2, **options
        )

    def test_complete_replacement_retains_original_bytes_and_untouched_index(self):
        before = self.git("write-tree")
        result = self.run_cutover()
        self.assertEqual(result["proofs"], 2)
        self.assertFalse(result["git_index_changed"])
        self.assertFalse(result["git_lfs_or_billing_mutated"])
        self.assertEqual(self.git("write-tree"), before)
        for relative, data in self.old.items():
            self.assertEqual((self.archive / relative).read_bytes(), data)
        total = 0
        for path in (self.repo / "data").glob("n=*/proofs.json"):
            total += len(ProofCatalog(path))
            self.assertEqual(path.with_name("facets.json").read_bytes(), b"preserve known facet records\n")
        self.assertEqual(total, 2)
        self.assertTrue((self.archive.parent / "publication-assets.json").is_file())

    def test_default_scope_or_wrong_review_hash_refuses_before_changes(self):
        with self.assertRaises(ValueError):
            local.cutover(self.repo, self.review_path, d.digest(self.review_path), self.archive)
        with self.assertRaises(ValueError):
            local.cutover(self.repo, self.review_path, "0" * 64, self.archive, _expected_total=2)
        self.assertFalse(self.archive.exists())
        for relative, data in self.old.items():
            self.assertEqual((self.repo / relative).read_bytes(), data)

    def test_user_data_changes_and_changed_accepted_payload_are_not_overwritten(self):
        relative = next(iter(self.old))
        target = self.repo / relative
        target.write_bytes(b"user change\n")
        with self.assertRaisesRegex(ValueError, "user changes"):
            self.run_cutover()
        self.assertFalse(self.archive.exists())
        self.assertEqual(target.read_bytes(), b"user change\n")
        target.write_bytes(self.old[relative])
        stage = Path(self.review["stage"])
        shard = next(stage.glob("data/n=*/proof-shards/*.proofpack"))
        shard.write_bytes(shard.read_bytes() + b"changed")
        with self.assertRaisesRegex(ValueError, "bound acceptance input changed"):
            self.run_cutover()
        self.assertFalse(self.archive.exists())


if __name__ == "__main__":
    unittest.main()
