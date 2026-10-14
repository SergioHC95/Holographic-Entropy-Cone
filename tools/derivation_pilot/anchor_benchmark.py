"""Bounded negative/positive tests of counterexample-guided fixed anchors."""

import argparse
import json
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

from hec._count_verify import FullMapVerifier
from hec.count_proofs import canonical_json
from hec.proof_store import ProofCatalog

from .anchors import derive, extract
from .recipes import full_map_definition, integer_seed

OPTIONS = {}
CATALOG = None


def initialize(options):
    global OPTIONS, CATALOG
    OPTIONS = options
    CATALOG = ProofCatalog(Path(options["data_root"]) / "n=6/proofs.json")


def check(index):
    source = CATALOG[index]
    problem, _vertices, rows = integer_seed(source)
    document, reconstructed, stats = extract(problem, rows, Path(OPTIONS["backend"]), budget=OPTIONS["budget"])
    if document is not None:
        verifier = FullMapVerifier(OPTIONS["verifier"])
        try:
            audit = verifier.verify(full_map_definition(problem, reconstructed))
        finally:
            verifier.close()
        path = Path(OPTIONS["output"]) / f"{index}.json"
        path.write_bytes(canonical_json(document) + b"\n")
        _, replay, _, _ = derive(document, Path(OPTIONS["backend"]))
        if reconstructed != replay:
            raise ValueError("fixed-anchor replay differs")
        stats.update(
            status="exact_full_cube_verified",
            recipe_bytes=len(canonical_json(document)),
            source_bytes=len(canonical_json(source)),
            full_edges=audit["checked_edges"],
            seed_matches_source=reconstructed == rows,
        )
    return {"index": index, **stats}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pilot-results", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--backend", type=Path, required=True)
    parser.add_argument("--verifier", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--budget", type=int, default=8)
    args = parser.parse_args()
    if args.output.exists() or not 0 <= args.budget <= 64:
        parser.error("choose a new output and a budget from zero through 64")
    args.output.mkdir(parents=True)
    parent = json.loads(args.pilot_results.read_text())
    indices = []
    for bucket in range(10):
        eligible = [
            case
            for case in parent["cases"]
            if case["n"] == 6 and f"frame-size-decile-{bucket}" in case["selection_tags"]
        ]
        indices.extend(case["index"] for case in eligible[:2])
    options = {key: str(getattr(args, key).resolve()) for key in ("data_root", "backend", "verifier", "output")}
    options["budget"] = args.budget
    started, results = time.perf_counter(), []
    with ProcessPoolExecutor(max_workers=2, initializer=initialize, initargs=(options,)) as pool:
        for future in as_completed([pool.submit(check, index) for index in indices]):
            result = future.result()
            results.append(result)
            print(
                json.dumps(
                    {
                        "tested": len(results),
                        "index": result["index"],
                        "status": result["status"],
                        "pins": result["pins"],
                    }
                ),
                flush=True,
            )
    report = {
        "cases": results,
        "workers": 2,
        "elapsed_seconds": time.perf_counter() - started,
        "budget": args.budget,
        "successful": sum(case["status"] == "exact_full_cube_verified" for case in results),
    }
    (args.output / "results.json").write_text(json.dumps(report, sort_keys=True, indent=2) + "\n")


if __name__ == "__main__":
    main()
