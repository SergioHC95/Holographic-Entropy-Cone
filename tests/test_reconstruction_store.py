"""Unified-only framing and actual verification; no repository promotion yet."""

import copy
import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

import zstandard as zstd
from corpus_derivations.pipeline_import import import_recipe

from hec.count_proofs import canonical_json, geometry, inequality_id, make_count_proof, proof_id
from hec.proof_store import CATALOG_FORMAT, ProofCatalog
from hec.reconstruction_store import ReconstructionCatalog
from hec.reconstruction_verify import ReconstructionVerifier


def stage(directory, documents):
    data, entries = bytearray(), []
    for doc in documents:
        frame = zstd.ZstdCompressor(write_checksum=True).compress(canonical_json(doc))
        # The fixture deliberately stages malformed documents as well. Build
        # the index from the otherwise valid inequality, not a proof parser
        # that would reject the intended adversarial record before the test.
        p = geometry(doc["inequality"]["n"], tuple(map(int, doc["inequality"]["coefficients"])))
        entries.append(
            {
                "proof_id": proof_id(doc),
                "inequality_id": inequality_id(p),
                "offset": len(data),
                "bytes": len(frame),
            }
        )
        data.extend(frame)
    shard = hashlib.sha256(data).hexdigest()
    for entry in entries:
        entry["shard"] = shard
    output = directory / "proof-shards"
    output.mkdir()
    (output / f"{shard}.proofpack").write_bytes(data)
    path = directory / "proofs.json"
    path.write_bytes(
        canonical_json({"format": CATALOG_FORMAT, "entries": entries, "shards": {shard: {"bytes": len(data)}}})
    )
    return path


class ReconstructionStoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="hec-unified-store-")
        self.directory = Path(self.temporary.name)
        self.old = make_count_proof(geometry(2, (2, 1, -1)), [(0,), (1,), (1,)], transport=True)
        self.document = import_recipe(self.old)[0]

    def tearDown(self):
        self.temporary.cleanup()

    def test_frame_reader_is_explicit_unified_only_and_old_primary_remains_unchanged(self):
        path = stage(self.directory, [self.document])
        self.assertEqual(ReconstructionCatalog(path)[0], self.document)
        with self.assertRaises(ValueError):
            ProofCatalog(path)[0]

    def test_legacy_definition_never_becomes_unified_fallback(self):
        path = stage(self.directory, [self.old])
        self.assertEqual(ProofCatalog(path)[0], self.old)
        with self.assertRaisesRegex(ValueError, "no legacy fallback"):
            ReconstructionCatalog(path)[0]

    def test_duplicate_inequality_cannot_have_two_authoritative_selections(self):
        other = copy.deepcopy(self.document)
        other["function"]["seed"] = {"kind": "integer-cut-dnf/1", "terms": [], "groups": [[[]]]}
        path = stage(self.directory, [self.document, other])
        with self.assertRaisesRegex(ValueError, "one selected proof"):
            ReconstructionCatalog(path)

    def test_verify_executes_full_reference_audit_again_not_stored_receipts(self):
        path = stage(self.directory, [self.document])
        catalog = ReconstructionCatalog(path)
        verifier = ReconstructionVerifier(closure_binary="", cube_binary="")
        spy = Mock(wraps=verifier)
        for _ in range(2):
            result = catalog.verify(spy)
            self.assertEqual((result["proofs"], result["checked_vertices"], result["checked_edges"]), (1, 4, 4))
            self.assertFalse(result["stored_acceptance_flags_used"])
        self.assertEqual(spy.verify.call_count, 2)

    def test_seed_only_or_incomplete_receipt_is_never_mathematical_acceptance(self):
        path = stage(self.directory, [self.document])
        with self.assertRaisesRegex(ValueError, "complete independent"):
            ReconstructionCatalog(path).verify(
                Mock(verify=Mock(return_value={"ok": True, "scope": "compatible-seed-only"}))
            )

    def test_well_formed_wrong_boundary_is_readable_but_rejected_by_verify(self):
        p = geometry(2, (2, 1, -1))
        bad = import_recipe(make_count_proof(p, [(0,), (1,), (1,)], transport=True))[0]
        # A different valid data-language function, not an accepted proof.
        bad["function"]["seed"] = {"kind": "integer-cut-dnf/1", "terms": [], "groups": [[[]]]}
        path = stage(self.directory, [bad])
        self.assertEqual(ReconstructionCatalog(path)[0], bad)
        with self.assertRaisesRegex(ValueError, "boundary"):
            ReconstructionCatalog(path).verify(ReconstructionVerifier(closure_binary="", cube_binary=""))

    def test_forged_flags_unknown_data_and_corrupted_shards_fail_closed(self):
        bad = copy.deepcopy(self.document)
        bad["verified"] = True
        path = stage(self.directory, [bad])
        with self.assertRaises(ValueError):
            ReconstructionCatalog(path)[0]
        shard = next((self.directory / "proof-shards").iterdir())
        shard.write_bytes(shard.read_bytes() + b"trailing")
        with self.assertRaisesRegex(ValueError, "SHA256"):
            ReconstructionCatalog(path)[0]


if __name__ == "__main__":
    unittest.main()
