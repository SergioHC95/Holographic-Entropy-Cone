"""Private exact input/provenance controls; no full-corpus acceptance claims."""

import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import test_synthesis_workflow as math_controls

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from corpus_derivations import compact_source, run, synthesize  # noqa: E402
from corpus_derivations.diagrams import common_seed  # noqa: E402
from derivation_pilot import recipes  # noqa: E402

from hec._archive_proof_store import write_archive_catalog as write_proof_catalog  # noqa: E402
from hec.count_proofs import canonical_json, geometry, inequality_id, make_count_proof  # noqa: E402


@unittest.skipUnless(shutil.which("c++"), "exact closure input control needs C++17")
class CompactSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.build = tempfile.TemporaryDirectory(prefix="hec-compact-source-closure-")
        existing = os.environ.get("HEC_DERIVATION_BINARY")
        cls.binary = Path(existing) if existing else Path(cls.build.name) / "closure"
        if not existing:
            subprocess.run(
                ["c++", "-O3", "-std=c++17", str(ROOT / "tools/derivation_pilot/closure.cpp"), "-o", str(cls.binary)],
                check=True,
            )

    @classmethod
    def tearDownClass(cls):
        cls.build.cleanup()

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="hec-compact-source-controls-")
        self.root = Path(self.temporary.name)
        self.old_run, self.old_synthesis = run.SETTINGS, synthesize.SETTINGS
        p = geometry(3, (-1, -1, -1, 2, 2, 2, -1))
        rows = []
        for vertex in range(8):
            a, b, c = ((vertex >> axis) & 1 for axis in range(3))
            rows.append((a * b * (1 - c), a * c * (1 - b), b * c * (1 - a), max(a, b, c)))
        rows[7] = (1, 0, 0, 1)
        proof = make_count_proof(p, rows, transport=True)
        self.seed = common_seed(proof)
        self.catalog = self.root / "inputs/proofs.json"
        self.catalog.parent.mkdir()
        index = write_proof_catalog(self.catalog, [proof])
        source = recipes.choice_recipe(p, recipes.closure_call(self.binary, p, mode="encode", rows=rows))
        decoded = recipes.decode_closure(source, self.binary)
        self.assertEqual(decoded.rows, rows)  # Actually execute the recorded seed-equivalence control.
        self.raw = canonical_json(source)
        self.sha = hashlib.sha256(self.raw).hexdigest()
        self.iid = inequality_id(p)
        self.item = (0, self.raw, self.sha, self.iid)
        input_id = index["entries"][0]["proof_id"]
        self.report = {
            "task": 0,
            "inequality_id": self.iid,
            "source_proof_id": input_id,
            "winner": "choice-closure",
            "winner_json_bytes": len(self.raw),
            "seed_scale": "1",
            "L": p.L,
            "G": p.G,
            "compatible_vertices": 8,
            "methods": {
                "choice-closure": {"recipe_sha256": self.sha, "status": "exact_equivalence_to_full_cube_verified_map"}
            },
            "mathematical_transform": "preserve complete compatible counts; fixed cancel/fill full-cube extension",
        }
        audit = math_controls.accept_small(p, list(range(8)), 1, rows, proof)
        audit["scope"] = "original-cube-all-edges"  # The reference above executed every original edge.
        receipt = {
            "task": 0,
            "ok": True,
            "source_tables_read": False,
            "recipe_sha256": self.sha,
            "full_cube_acceptance": audit,
        }
        self.db = sqlite3.connect(self.root / "checkpoint.sqlite3")
        self.db.executescript("""PRAGMA journal_mode=WAL;
          CREATE TABLE results(task INTEGER PRIMARY KEY,recipe_sha256 TEXT,inequality_id TEXT,report TEXT);
          CREATE TABLE fresh(task INTEGER PRIMARY KEY,ok INTEGER,report TEXT);""")
        self.db.execute(
            "INSERT INTO results VALUES(?,?,?,?)", (0, self.sha, self.iid, canonical_json(self.report).decode())
        )
        self.db.execute("INSERT INTO fresh VALUES(0,1,?)", (canonical_json(receipt).decode(),))
        self.db.commit()
        self.manifest = [
            {
                "task": 0,
                "group": "baseline",
                "catalog": str(self.catalog),
                "index": 0,
                "source_proof_id": input_id,
                "inequality_id": self.iid,
            }
        ]
        self.reader = None
        self.rebind()
        run.SETTINGS = {"binaries": {"closure": {"path": str(self.binary)}}}

    def rebind(self):
        (self.root / "manifest.json").write_bytes(canonical_json(self.manifest))
        binding = {
            "total": 1,
            "manifest_sha256": run.digest(self.root / "manifest.json"),
            "source_catalogs": {str(self.catalog): {"sha256": run.digest(self.catalog)}},
        }
        (self.root / "run-binding.json").write_bytes(canonical_json(binding))
        self.settings = {
            "source": str(self.root),
            "source_total": 1,
            "source_seed_input": {
                "policy": compact_source.POLICY,
                "source_binding_sha256": run.digest(self.root / "run-binding.json"),
                "source_manifest_sha256": binding["manifest_sha256"],
            },
        }

    def tearDown(self):
        if self.reader is not None:
            self.reader.close()
        run.SETTINGS, synthesize.SETTINGS = self.old_run, self.old_synthesis
        self.db.close()
        self.temporary.cleanup()

    def decode(self):
        self.reader = compact_source.Reader(self.settings)
        return self.reader.decode(self.item, json.loads(self.raw))

    def test_bound_compact_input_matches_every_count_and_emits_no_cached_acceptance(self):
        seed, provenance = self.decode()
        self.assertEqual(seed, self.seed)
        self.assertFalse(provenance["mathematical_acceptance_cached"])
        self.assertFalse(provenance["original_boolean_archives_read"])
        self.assertEqual(provenance["source_recipe_sha256"], self.sha)

    def test_manifest_and_source_binding_cannot_change(self):
        (self.root / "manifest.json").write_bytes(b"[]")
        with self.assertRaisesRegex(ValueError, "manifest/scope"):
            compact_source.Reader(self.settings)

    def test_source_equivalence_flag_hash_identity_and_boolean_task_are_not_interchangeable(self):
        for key, value in (("source_proof_id", "0" * 64), ("task", False), ("winner", "cut-formulas")):
            bad = {**self.report, key: value}
            self.db.execute("UPDATE results SET report=?", (canonical_json(bad).decode(),))
            self.db.commit()
            with self.assertRaisesRegex(ValueError, "equivalence provenance"):
                self.decode()
            self.reader.close()
            self.reader = None

    def test_missing_fresh_source_audit_blocks_input_reuse(self):
        self.db.execute("DELETE FROM fresh")
        self.db.commit()
        with self.assertRaisesRegex(ValueError, "source-free cube audit"):
            self.decode()

    def test_changed_compact_catalogue_is_an_error_not_an_acceptance_fallback(self):
        self.reader = compact_source.Reader(self.settings)
        self.catalog.write_bytes(b"{}")
        with self.assertRaisesRegex(ValueError, "catalogue changed"):
            self.reader.decode(self.item, json.loads(self.raw))

    def test_primitive_archive_locator_is_never_opened(self):
        self.manifest[0]["group"] = "primitive"
        self.manifest[0]["packed_file"] = "/never-open-a-Boolean-archive"
        self.rebind()
        with patch.object(compact_source, "ProofCatalog", side_effect=AssertionError("archive not an input")):
            self.assertIsNone(self.decode())

    def test_missing_optional_input_uses_the_saved_standalone_recipe(self):
        self.catalog.rename(self.catalog.with_name("preserved-original.json"))
        self.assertIsNone(self.decode())

    def test_fresh_verification_never_calls_the_construction_input_reader(self):
        with (
            patch.object(compact_source, "decode", side_effect=AssertionError("fresh must be source-free")),
            patch.object(run, "accept", side_effect=math_controls.accept_small) as acceptance,
        ):
            receipt = synthesize.optimized_fresh(self.item)
        acceptance.assert_called_once()
        self.assertFalse(receipt["source_tables_read"])

    def test_reused_starting_seed_still_requires_new_independent_acceptance(self):
        seed, provenance = self.decode()
        settings = {
            **self.settings,
            "optimization": synthesize.OPTIMIZATION,
            "sweeps": 2,
            "max_work": 50000,
            "binaries": {"closure": {"path": str(self.binary)}},
        }
        synthesize.SETTINGS = settings
        with (
            patch.object(compact_source, "decode", return_value=(seed, provenance)),
            patch.object(run, "accept", side_effect=math_controls.accept_small) as acceptance,
        ):
            report, packed = synthesize.attempt(self.item)
        self.assertEqual(report["status"], "accepted_strictly_smaller_alternative")
        self.assertIsNotNone(packed)
        self.assertFalse(report["construction_seed_input"]["mathematical_acceptance_cached"])
        acceptance.assert_called_once()


if __name__ == "__main__":
    unittest.main()
