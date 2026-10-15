"""Opt-in unified-only catalogue reader, pending full-corpus promotion.

The existing primary repository loader is deliberately not switched here.
Storage framing is shared, not a legacy-format fallback. Reading a frame or
checking syntax is NOT mathematical acceptance: verify() executes the exact
original-cube verifier for every selected proof, every time.
"""

from __future__ import annotations

from .count_proofs import FORMAT, inequality_id, proof_geometry, proof_id
from .proof_store import ProofCatalog
from .reconstruction import CLOSURE, PIPELINE, ReconstructionProgram
from .reconstruction_verify import ReconstructionVerifier


class _SyntaxOnlyClosure:
    primitive = CLOSURE

    def decode(self, *args):
        raise ValueError("syntax-only catalogue read is not a closure evaluation or mathematical acceptance")


class ReconstructionCatalog(ProofCatalog):
    def __init__(self, path):
        super().__init__(path)
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
        result = verifier.verify(proof)
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
