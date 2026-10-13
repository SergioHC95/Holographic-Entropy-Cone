"""Verify new proof shards and ordinary-Git inequality bindings exactly."""

import argparse
import json
from pathlib import Path

from hec.count_proofs import KERNEL, check_count_proof
from hec.inequality_records import InequalityCatalog
from hec.proof_store import ProofCatalog


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
    proofs, source_edges, seed_edges = 0, 0, 0
    for _index, proof in catalog.iter_selected(args.shard_index, args.shard_count):
        receipt = check_count_proof(proof)
        if proof["function"]["kind"] == KERNEL:
            seed_edges += receipt["checked_edges"]
        else:
            source_edges += receipt["checked_edges"]
        proofs += 1
    print(
        json.dumps(
            {
                "ok": True,
                "verified_proofs": proofs,
                "symbolic_original_cube_edges": source_edges,
                "compatible_seed_edges": seed_edges,
            }
        )
    )


if __name__ == "__main__":
    main()
