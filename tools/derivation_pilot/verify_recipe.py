"""Fresh-process exact acceptance using a saved recipe and no source corpus."""

import argparse
import json
import time
from pathlib import Path

from hec._count_verify import FullMapVerifier
from hec.count_proofs import parse_json, proof_id

from .recipes import full_map_definition, recipe_id, reconstruct


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--recipe", type=Path, required=True)
    parser.add_argument("--closure", type=Path, required=True)
    parser.add_argument("--verifier", type=Path, required=True)
    parser.add_argument("--anchored-backend", type=Path)
    args = parser.parse_args()
    verifier = FullMapVerifier(args.verifier)
    started = time.perf_counter_ns()
    try:
        document = parse_json(args.recipe.read_bytes())
        if document.get("function", {}).get("kind") == "fixed-anchor-closure/experimental-1":
            from .anchors import derive

            if args.anchored_backend is None:
                raise ValueError("fixed-anchor recipe requires its exact backend")
            problem, rows, decoding, _ = derive(document, args.anchored_backend)
            if rows is None:
                raise ValueError("fixed-anchor attempt did not construct a complete seed")
        else:
            problem, rows, decoding = reconstruct(document, args.closure)
        definition = full_map_definition(problem, rows)
        check = verifier.verify(definition)
        print(
            json.dumps(
                {
                    "ok": True,
                    "recipe_id": recipe_id(document),
                    "derived_standard_proof_id": proof_id(definition),
                    "n": problem.n,
                    "compatible_vertices": len(rows),
                    "decoding": decoding,
                    "checked_vertices": check["checked_vertices"],
                    "checked_edges": check["checked_edges"],
                    "scope": check["scope"],
                    "source_tables_read": False,
                    "elapsed_microseconds": (time.perf_counter_ns() - started) // 1000,
                },
                sort_keys=True,
            )
        )
    except (ValueError, OSError) as error:
        print(json.dumps({"ok": False, "error": str(error), "not_a_proof": True}))
        raise SystemExit(1) from error
    finally:
        verifier.close()


if __name__ == "__main__":
    main()
