"""Explicit offline reader/writer for archived pre-unification artifacts.

Never imported as an automatic fallback by the primary proof storage API.
Historical constructors and scopes remain reproducible, not authoritative.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from ._proof_frames import DEFAULT_SHARD_BYTES, FrameCatalog, _write_catalog
from .count_proofs import DAG, FORMAT, KERNEL, TRANSPORT, check_count_proof


class ArchiveProofCatalog(FrameCatalog):
    def _check_definition(self, proof):
        if proof.get("format") != FORMAT or proof.get("function", {}).get("kind") not in (DAG, KERNEL, TRANSPORT):
            raise ValueError("authoritative catalogue accepts compact definitions, not audit tables")

    def verify(self) -> dict:
        checked_edges = 0
        cube_edges, seed_edges = 0, 0
        for proof in self:
            edges = check_count_proof(proof)["checked_edges"]
            checked_edges += edges
            if proof["function"]["kind"] in (KERNEL, TRANSPORT):
                seed_edges += edges
            else:
                cube_edges += edges
        return {
            "ok": True,
            "proofs": len(self),
            "checked_edges": checked_edges,
            "shards": len(self.shards),
            "symbolic_original_cube_edges": cube_edges,
            "compatible_seed_edges": seed_edges,
        }


def write_archive_catalog(
    path: str | Path,
    proofs: Iterable[dict],
    *,
    shard_bytes: int = DEFAULT_SHARD_BYTES,
    compression_level: int = 9,
) -> dict:
    """Offline archival writer; never the authoritative repository publisher."""

    def validate(proof):
        if proof.get("format") != FORMAT or proof.get("function", {}).get("kind") not in (DAG, KERNEL, TRANSPORT):
            raise ValueError("authoritative catalogue accepts compact definitions, not audit tables")
        return check_count_proof(proof)

    return _write_catalog(path, proofs, validate, shard_bytes=shard_bytes, compression_level=compression_level)
