"""Unified-only framing and actual verification; no repository promotion yet."""

import copy
import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import zstandard as zstd
from proof_fixtures import departed_definition, document

from hec.count_proofs import canonical_json, geometry, inequality_id, proof_id
from hec.proof_store import CATALOG_FORMAT, ProofCatalog
from hec.reconstruction import ReconstructionProgram
from hec.reconstruction_store import ReconstructionCatalog, write_reconstruction_catalog
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
        self.old = departed_definition(geometry(2, (2, 1, -1)))
        self.document = document(geometry(2, (2, 1, -1)), [(0,), (1,), (1,)])

    def tearDown(self):
        self.temporary.cleanup()

    def test_primary_reader_is_the_single_unified_reader(self):
        path = stage(self.directory, [self.document])
        self.assertEqual(ReconstructionCatalog(path)[0], self.document)
        self.assertIs(ProofCatalog, ReconstructionCatalog)
        self.assertEqual(ProofCatalog(path)[0], self.document)

    def test_legacy_definition_never_becomes_unified_fallback(self):
        path = stage(self.directory, [self.old])
        with self.assertRaisesRegex(ValueError, "standardized reconstruction|no legacy fallback"):
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

    def test_audit_entry_constructs_one_checked_program_and_public_read_still_checks(self):
        path = stage(self.directory, [self.document])
        catalog = ReconstructionCatalog(path)
        verifier = ReconstructionVerifier(closure_binary="", cube_binary="")
        with (
            patch("hec.reconstruction_store.ReconstructionProgram", wraps=ReconstructionProgram) as syntax,
            patch("hec.reconstruction_verify.ReconstructionProgram", wraps=ReconstructionProgram) as actual,
        ):
            self.assertEqual(catalog[0], self.document)
            syntax.assert_called_once()
            syntax.reset_mock()
            result = catalog.audit_entry(0, verifier)
            syntax.assert_not_called()
            actual.assert_called_once()
        self.assertEqual((result["checked_vertices"], result["checked_edges"]), (4, 4))

    def test_single_parse_path_rejects_unknown_syntax_and_legacy_definitions(self):
        bad = copy.deepcopy(self.document)
        bad["verified"] = True
        verifier = ReconstructionVerifier(closure_binary="", cube_binary="")
        for index, candidate in enumerate((bad, self.old)):
            directory = self.directory / str(index)
            directory.mkdir()
            catalog = ReconstructionCatalog(stage(directory, [candidate]))
            with self.assertRaises(ValueError):
                catalog.audit_entry(0, verifier)

    def test_single_parse_path_checks_actual_coverage_types_and_identity(self):
        path = stage(self.directory, [self.document])
        catalog = ReconstructionCatalog(path)
        correct = ReconstructionVerifier(closure_binary="", cube_binary="").verify(self.document)
        for key, value in (
            ("ok", 1),
            ("checked_vertices", True),
            ("checked_edges", 3),
            ("proof_id", "0" * 64),
            ("inequality_id", "0" * 64),
            ("scope", "compatible-seed-only"),
            ("source_tables_read", True),
        ):
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, "complete independent"):
                catalog.audit_entry(0, Mock(verify=Mock(return_value={**correct, key: value})))
        with self.assertRaisesRegex(ValueError, "complete independent"):
            catalog.audit_entry(0, Mock(verify=Mock(return_value=None)))

    def test_single_parse_path_still_hashes_payload_before_calling_verifier(self):
        path = stage(self.directory, [self.document])
        shard = next((self.directory / "proof-shards").iterdir())
        shard.write_bytes(shard.read_bytes() + b"trailing")
        verifier = Mock()
        with self.assertRaisesRegex(ValueError, "SHA256"):
            ReconstructionCatalog(path).audit_entry(0, verifier)
        verifier.verify.assert_not_called()

    def test_well_formed_wrong_boundary_is_readable_but_rejected_by_verify(self):
        p = geometry(2, (2, 1, -1))
        bad = document(p, [(0,), (1,), (1,)])
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


class ReconstructionWriterTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="hec-unified-writer-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.legacy = departed_definition(geometry(2, (2, 1, -1)))
        self.document = document(geometry(2, (2, 1, -1)), [(0,), (1,), (1,)])
        self.other = document(geometry(2, (1, 1, -1)), [(0,), (1,), (1,)])
        self.verifier = ReconstructionVerifier(closure_binary="", cube_binary="")
        self.addCleanup(self.verifier.close)

    def test_complete_writer_and_reader_both_execute_actual_audits(self):
        spy = Mock(wraps=self.verifier)
        path = self.root / "proofs.json"
        result = write_reconstruction_catalog(path, [self.document, self.other], shard_bytes=1, verifier=spy)
        self.assertEqual((len(result["entries"]), len(result["shards"])), (2, 2))
        self.assertEqual(spy.verify.call_count, 2)
        catalog = ReconstructionCatalog(path)
        self.assertEqual(list(catalog), [self.document, self.other])
        audit = catalog.verify(spy)
        self.assertEqual((audit["proofs"], audit["checked_vertices"], audit["checked_edges"]), (2, 8, 8))
        self.assertEqual(spy.verify.call_count, 4)

    def test_legacy_bad_boundary_forged_receipt_and_empty_stream_publish_no_catalogue(self):
        bad = copy.deepcopy(self.document)
        bad["function"]["seed"] = {"kind": "integer-cut-dnf/1", "terms": [], "groups": [[[]]]}
        for name, documents, verifier in (
            ("legacy", [self.legacy], self.verifier),
            ("boundary", [bad], self.verifier),
            (
                "seed-only",
                [self.document],
                Mock(verify=Mock(return_value={"ok": True, "scope": "compatible-seed-only"})),
            ),
            ("empty", [], self.verifier),
        ):
            path = self.root / name / "proofs.json"
            with self.subTest(name=name), self.assertRaises(ValueError):
                write_reconstruction_catalog(path, documents, verifier=verifier)
            self.assertFalse(path.exists())

    def test_only_one_definition_per_inequality_even_when_both_are_valid(self):
        cut = copy.deepcopy(self.document)
        cut["function"]["seed"] = {"kind": "integer-cut-dnf/1", "terms": [["1", "0"], ["2", "0"]], "groups": [[[0, 1]]]}
        # Both definitions independently verify, but the authoritative selection
        # cannot contain two encodings/proofs for the same inequality.
        self.verifier.verify(cut)
        spy = Mock(wraps=self.verifier)
        path = self.root / "proofs.json"
        with self.assertRaisesRegex(ValueError, "one selected proof"):
            write_reconstruction_catalog(path, [self.document, cut], verifier=spy)
        self.assertEqual(spy.verify.call_count, 1)
        self.assertFalse(path.exists())

    def test_caller_mutation_during_verification_cannot_change_published_bytes(self):
        original, expected = copy.deepcopy(self.document), copy.deepcopy(self.document)

        def verify(snapshot):
            original["function"]["seed"] = {"kind": "integer-cut-dnf/1", "terms": [], "groups": [[[]]]}
            return self.verifier.verify(snapshot)

        path = self.root / "proofs.json"
        write_reconstruction_catalog(path, [original], verifier=Mock(verify=Mock(side_effect=verify)))
        self.assertNotEqual(original, expected)
        self.assertEqual(ReconstructionCatalog(path)[0], expected)

    def test_verifier_mutating_owned_snapshot_is_rejected_not_silently_published(self):
        def verify(snapshot):
            result = self.verifier.verify(snapshot)
            snapshot["function"]["seed"] = {"kind": "integer-cut-dnf/1", "terms": [], "groups": [[[]]]}
            return result

        path = self.root / "proofs.json"
        with self.assertRaises(ValueError):
            write_reconstruction_catalog(path, [self.document], verifier=Mock(verify=Mock(side_effect=verify)))
        self.assertFalse(path.exists())

    def test_existing_target_and_symlink_parent_fail_before_backend_call(self):
        path = self.root / "proofs.json"
        path.write_bytes(b"preserve this original")
        spy = Mock(verify=Mock(side_effect=AssertionError("existing destination must preflight first")))
        with self.assertRaises(ValueError):
            write_reconstruction_catalog(path, [self.document], verifier=spy)
        self.assertEqual(path.read_bytes(), b"preserve this original")
        directory = self.root / "directory"
        directory.mkdir()
        link = self.root / "linked"
        link.symlink_to(directory, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "unsafe"):
            write_reconstruction_catalog(link / "new.json", [self.document], verifier=spy)
        spy.verify.assert_not_called()
        self.assertFalse((directory / "proof-shards").exists())

    def test_existing_immutable_payload_reused_but_corruption_is_never_replaced(self):
        write_reconstruction_catalog(self.root / "first.json", [self.document], verifier=self.verifier)
        shard = next((self.root / "proof-shards").iterdir())
        before = shard.read_bytes(), shard.stat().st_ino
        write_reconstruction_catalog(self.root / "second.json", [self.document], verifier=self.verifier)
        self.assertEqual((shard.read_bytes(), shard.stat().st_ino), before)
        shard.write_bytes(shard.read_bytes() + b"corrupt")
        corrupt = shard.read_bytes()
        with self.assertRaisesRegex(ValueError, "immutable shard is corrupt"):
            write_reconstruction_catalog(self.root / "third.json", [self.document], verifier=self.verifier)
        self.assertEqual(shard.read_bytes(), corrupt)
        self.assertFalse((self.root / "third.json").exists())

    def test_failure_after_sealing_leaves_no_published_catalogue(self):
        bad = document(geometry(2, (1, 2, -1)), [(0,), (1,), (1,)])
        bad["function"]["seed"] = {"kind": "integer-cut-dnf/1", "terms": [], "groups": [[[]]]}
        path = self.root / "proofs.json"
        with self.assertRaisesRegex(ValueError, "boundary"):
            write_reconstruction_catalog(path, [self.document, self.other, bad], shard_bytes=1, verifier=self.verifier)
        self.assertFalse(path.exists())
        # The only residue is a content-addressed, reusable verified frame,
        # never an authoritative index claiming complete publication.
        for shard in (self.root / "proof-shards").iterdir():
            self.assertEqual(hashlib.sha256(shard.read_bytes()).hexdigest(), shard.stem)


if __name__ == "__main__":
    unittest.main()
