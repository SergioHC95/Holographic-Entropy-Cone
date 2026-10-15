"""The unified-only standard catalogue reader and exact writer.

The primary repository API aliases this one implementation.
Storage framing is shared, not a legacy-format fallback. Reading a frame or
checking syntax is NOT mathematical acceptance: verify() executes the exact
original-cube verifier for every selected proof, every time.
"""

from __future__ import annotations

from ._proof_frames import DEFAULT_SHARD_BYTES, FrameCatalog, _write_catalog
from .count_proofs import FORMAT, inequality_id, proof_geometry, proof_id
from .reconstruction import CLOSURE, PIPELINE, ReconstructionProgram
from .reconstruction_verify import ReconstructionVerifier


class _SyntaxOnlyClosure:
    primitive = CLOSURE

    def decode(self, *args):
        raise ValueError("syntax-only catalogue read is not a closure evaluation or mathematical acceptance")


def _full_result(proof, result):
    p = proof_geometry(proof)
    expected = {
        "ok": True,
        "scope": "original-cube-all-edges",
        "proof_id": proof_id(proof),
        "inequality_id": inequality_id(p),
        "checked_vertices": p.vertices,
        "checked_edges": p.L * (p.vertices // 2),
        "source_tables_read": False,
    }
    if not isinstance(result, dict) or any(
        type(result.get(key)) is not type(value) or result[key] != value for key, value in expected.items()
    ):
        raise ValueError("unified catalogue lacks actual complete independent cube verification")
    return result


def write_reconstruction_catalog(path, proofs, *, shard_bytes=DEFAULT_SHARD_BYTES, compression_level=9, verifier=None):
    """Publish only complete, actually audited, unified-only definitions.

    One selected proof per inequality; no legacy/audit-table fallback and no
    stored acceptance cache. The catalogue is published atomically LAST.
    A failed stream may leave reusable immutable shards but no catalogue.
    """
    owned, selected, inequalities = verifier is None, verifier, set()

    def validate(proof):
        nonlocal selected
        if proof.get("format") != FORMAT or proof.get("function", {}).get("kind") != PIPELINE:
            raise ValueError("unified writer accepts only the single reconstruction pipeline, no legacy fallback")
        iid = inequality_id(proof_geometry(proof))
        if iid in inequalities:
            raise ValueError("authoritative unified writer requires one selected proof per inequality")
        if selected is None:
            selected = ReconstructionVerifier()
        result = _full_result(proof, selected.verify(proof))
        inequalities.add(iid)
        return result

    try:
        return _write_catalog(
            path, proofs, validate, shard_bytes=shard_bytes, compression_level=compression_level, require_nonempty=True
        )
    finally:
        if owned and selected is not None:
            selected.close()


class ReconstructionCatalog(FrameCatalog):
    def __init__(self, path):
        super().__init__(path)
        if not self.entries:
            raise ValueError("authoritative unified catalogue cannot be empty")
        if len({entry["inequality_id"] for entry in self.entries}) != len(self.entries):
            raise ValueError("authoritative unified catalogue requires one selected proof per inequality")

    def _check_definition(self, proof):
        if proof.get("format") != FORMAT or proof.get("function", {}).get("kind") != PIPELINE:
            raise ValueError("unified catalogue accepts only the single reconstruction pipeline, no legacy fallback")
        # Validate the closed data language without launching a decoder or
        # claiming seed/full-map validity. Native configuration belongs to the
        # actual verifier, not the proof document or storage catalogue.
        ReconstructionProgram(proof, closure_backend=_SyntaxOnlyClosure())

    def audit_entry(self, index, verifier):
        """Read once and execute the verifier, without a discarded program.

        The canonical frame/hash/identity checks remain in _read_record. The
        verifier constructs the same closed ReconstructionProgram and executes
        the complete original-cube audit. This does not return an unchecked
        document, cache acceptance, or rely on a previous stored receipt.
        """
        proof = self._read_record(index)
        return _full_result(proof, verifier.verify(proof))

    def verify(self, verifier=None):
        owned = verifier is None
        verifier = ReconstructionVerifier() if owned else verifier
        checked_edges, checked_vertices = 0, 0
        try:
            for index in range(len(self)):
                result = self.audit_entry(index, verifier)
                checked_edges += result["checked_edges"]
                checked_vertices += result["checked_vertices"]
        finally:
            if owned:
                verifier.close()
        return {
            "ok": True,
            "proofs": len(self),
            "shards": len(self.shards),
            "scope": "original-cube-all-edges",
            "checked_vertices": checked_vertices,
            "checked_edges": checked_edges,
            "source_tables_read": False,
            "stored_acceptance_flags_used": False,
        }
