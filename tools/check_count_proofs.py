"""Exactly verify standard proof shards and inequality bindings; no legacy fallback."""

import argparse
import json
from pathlib import Path

from hec.inequality_records import InequalityCatalog
from hec.proof_store import ProofCatalog
from hec.reconstruction_verify import ReconstructionVerifier


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("catalog", type=Path)
    parser.add_argument("--inequalities", type=Path)
    parser.add_argument("--shard-index", type=int, default=0)
    parser.add_argument("--shard-count", type=int, default=1)
    args = parser.parse_args()
    catalog = ProofCatalog(args.catalog)
    if args.inequalities:
        InequalityCatalog(args.inequalities).check_bindings(catalog)
    proofs, edges, vertices = 0, 0, 0
    verifier = ReconstructionVerifier()
    try:
        for index in catalog.shard_group_entries(args.shard_index, args.shard_count):
            result = catalog.audit_entry(index, verifier)
            proofs += 1
            edges += result["checked_edges"]
            vertices += result["checked_vertices"]
    finally:
        verifier.close()
    print(
        json.dumps(
            {
                "ok": True,
                "verified_proofs": proofs,
                "checked_original_cube_vertices": vertices,
                "checked_original_cube_edges": edges,
                "scope": "original-cube-all-edges",
                "source_tables_read": False,
                "stored_acceptance_flags_used": False,
            }
        )
    )


if __name__ == "__main__":
    main()
