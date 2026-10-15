"""Bounded, reproducible comparisons against real compact source definitions."""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import resource
import statistics
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path

from hec._archive_proof_store import ArchiveProofCatalog as ProofCatalog
from hec._count_transport import SeedLookup, evaluate_transport
from hec._count_verify import FullMapVerifier
from hec.count_proofs import canonical_json

from .recipes import (
    CutFunction,
    WorkLimit,
    choice_recipe,
    closure_call,
    cut_recipe,
    full_map_definition,
    integer_seed,
    policy_recipe,
    recipe_id,
    reconstruct,
)

SETTINGS = {}
CATALOGS = {}
VERIFIER = None


def digest(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024**2), b""):
            result.update(block)
    return result.hexdigest()


def initialize(settings):
    global SETTINGS, VERIFIER
    SETTINGS = settings
    VERIFIER = FullMapVerifier(settings["verifier"])


def source_catalog(n):
    if n not in CATALOGS:
        CATALOGS[n] = ProofCatalog(Path(SETTINGS["data_root"]) / f"n={n}/proofs.json")
    return CATALOGS[n]


def check_candidate(document, source_rows, directory, name):
    # Persist then read the recipe. Reconstruction receives only that recipe,
    # geometry and the versioned backend, never the source table or proof ID.
    path = directory / f"{name}.json"
    path.write_bytes(canonical_json(document) + b"\n")
    restored = json.loads(path.read_bytes())
    started = time.perf_counter_ns()
    problem, rows, decoding = reconstruct(restored, Path(SETTINGS["closure"]))
    standard = full_map_definition(problem, rows)
    acceptance = VERIFIER.verify(standard)
    if acceptance.get("ok") is not True:
        raise ValueError("independent full-map acceptance did not succeed")
    return {
        "status": "exact_full_cube_verified",
        "recipe": str(path.relative_to(Path(SETTINGS["output"]))),
        "recipe_id": recipe_id(restored),
        "recipe_bytes": len(canonical_json(restored)),
        "seed_matches_source": rows == source_rows,
        "decoding": decoding,
        "full_cube_vertices": acceptance["checked_vertices"],
        "full_cube_edges": acceptance["checked_edges"],
        "verification_scope": acceptance["scope"],
        "reconstruct_and_verify_us": (time.perf_counter_ns() - started) // 1000,
    }


def benchmark_case(item):
    n, index, tags = item
    source = source_catalog(n)[index]
    problem, vertices, rows = integer_seed(source)
    directory = Path(SETTINGS["output"]) / "recipes" / f"n{n}-{index:05d}"
    directory.mkdir(parents=True, exist_ok=False)
    report = {
        "n": n,
        "index": index,
        "selection_tags": tags,
        "inequality_id": source_catalog(n).entries[index]["inequality_id"],
        "source_proof_id": source_catalog(n).entries[index]["proof_id"],
        "L": problem.L,
        "G": problem.G,
        "max_alpha": max(problem.alpha, default=0),
        "max_beta": max(problem.beta, default=0),
        "compatible_vertices": len(vertices),
        "source_count_values": len(vertices) * problem.G,
        "source_json_bytes": len(canonical_json(source)),
        "source_frame_bytes": source_catalog(n).entries[index]["bytes"],
        "methods": {},
    }
    result = closure_call(
        Path(SETTINGS["closure"]),
        problem,
        mode="encode",
        rows=rows,
        enumeration=SETTINGS["enumeration"],
    )
    document = choice_recipe(problem, result, enumeration=SETTINGS["enumeration"])
    source_closure = check_candidate(document, rows, directory, "choice-closure")
    if source_closure["seed_matches_source"] is not True:
        raise ValueError("choice replay failed exact source-seed reconstruction")
    source_closure.update(
        encoding=result.stats,
        encode_wall_us=result.wall_microseconds,
        recorded_exceptions=len(document["function"]["exceptions"]),
        default=document["function"]["policy"],
    )
    report["methods"]["choice-closure"] = source_closure
    for policy in ("lower", "upper"):
        doc = policy_recipe(problem, policy, enumeration=SETTINGS["enumeration"])
        try:
            report["methods"]["derive-" + policy] = check_candidate(doc, rows, directory, "derive-" + policy)
        except ValueError as error:
            report["methods"]["derive-" + policy] = {"status": "failed_not_a_proof", "error": str(error)}
    start = time.perf_counter_ns()
    try:
        doc, stats = cut_recipe(problem, vertices, rows, candidates=4, max_terms=SETTINGS["cut_terms"])
        extraction = (time.perf_counter_ns() - start) // 1000
        formula = check_candidate(doc, rows, directory, "cut-formulas")
        if formula["seed_matches_source"] is not True:
            raise ValueError("formula did not reconstruct source seed")
        formula.update(stats, extraction_us=extraction)
        if "rows" in source["function"] and problem.G:
            queries = sorted({vertex for vertex, _ in problem.boundary})
            rng = random.Random(20261013 + index)
            queries.extend(rng.randrange(problem.vertices) for _ in range(24))
            packed = SeedLookup(problem, source["function"]["rows"])
            definition = CutFunction(doc)
            start = time.perf_counter_ns()
            expected = [evaluate_transport(problem, packed, x) for x in queries]
            baseline_time = (time.perf_counter_ns() - start) // 1000
            start = time.perf_counter_ns()
            actual = [evaluate_transport(problem, definition, x) for x in queries]
            formula_time = (time.perf_counter_ns() - start) // 1000
            if actual != expected:
                raise ValueError("formula full-map queries disagree")
            formula["query_benchmark"] = {
                "vertices": len(queries),
                "packed_lookup_us": baseline_time,
                "formula_lookup_us": formula_time,
                "exact_equal": True,
                "scope": "timing sample; mathematical acceptance is separately exhaustive",
            }
        report["methods"]["cut-formulas"] = formula
    except WorkLimit as error:
        report["methods"]["cut-formulas"] = {"status": "incomplete_budget_not_a_proof", "error": str(error)}
    multiplier = 1 if sys.platform == "darwin" else 1024
    report["worker_peak_rss_bytes"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * multiplier
    report["native_child_peak_rss_bytes"] = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss * multiplier
    return report


def select_cases(root, sample, seed):
    cases = []
    for n in range(1, 6):
        catalog = ProofCatalog(root / f"n={n}/proofs.json")
        cases.extend((n, index, ["all-small-n"]) for index in range(len(catalog)))
    catalog = ProofCatalog(root / "n=6/proofs.json")
    ordered = sorted(range(len(catalog)), key=lambda i: (catalog.entries[i]["bytes"], i))
    selected = {}
    rng = random.Random(seed)
    for bin_index in range(10):
        bucket = ordered[bin_index * len(ordered) // 10 : (bin_index + 1) * len(ordered) // 10]
        size = sample // 10 + int(bin_index < sample % 10)
        for index in rng.sample(bucket, min(size, len(bucket))):
            selected.setdefault(index, []).append(f"frame-size-decile-{bin_index}")
    for index in ordered[:4] + ordered[-8:] + [0, len(catalog) // 2, len(catalog) - 1]:
        selected.setdefault(index, []).append("extreme-or-control")
    cases.extend((6, index, tags) for index, tags in sorted(selected.items()))
    return cases


def summarize(cases):
    summary = {}
    for method in ("choice-closure", "derive-lower", "derive-upper", "cut-formulas"):
        valid = [
            (case, case["methods"][method])
            for case in cases
            if case["methods"][method]["status"] == "exact_full_cube_verified"
        ]
        source_bytes = sum(case["source_json_bytes"] for case, _ in valid)
        recipe_bytes = sum(result["recipe_bytes"] for _, result in valid)
        times = [result["decoding"]["wall_microseconds"] for _, result in valid]
        summary[method] = {
            "verified_cases": len(valid),
            "other_cases": len(cases) - len(valid),
            "source_json_bytes_on_valid_cases": source_bytes,
            "recipe_json_bytes": recipe_bytes,
            "recipe_to_source_ratio": recipe_bytes / source_bytes if source_bytes else None,
            "smaller_than_source_cases": sum(
                result["recipe_bytes"] < case["source_json_bytes"] for case, result in valid
            ),
            "median_decode_us": statistics.median(times) if times else None,
            "original_cube_edges_checked": sum(result["full_cube_edges"] for _, result in valid),
        }
    winners = []
    for case in cases:
        valid = [
            (result["recipe_bytes"], name)
            for name, result in case["methods"].items()
            if result["status"] == "exact_full_cube_verified"
        ]
        size, name = min(valid + [(case["source_json_bytes"], "existing-definition")])
        winners.append((size, name))
    source_bytes = sum(case["source_json_bytes"] for case in cases)
    summary["best_with_existing_fallback"] = {
        "source_json_bytes": source_bytes,
        "selected_json_bytes": sum(size for size, _ in winners),
        "selected_to_source_ratio": sum(size for size, _ in winners) / source_bytes,
        "winner_counts": {
            name: sum(winner == name for _, winner in winners) for name in sorted({name for _, name in winners})
        },
    }
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--closure", type=Path, required=True)
    parser.add_argument("--verifier", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--sample", type=int, default=128)
    parser.add_argument("--seed", type=int, default=20261013)
    parser.add_argument("--workers", type=int, choices=(1, 2), default=2)
    parser.add_argument("--enumeration", type=int, default=64)
    parser.add_argument("--cut-terms", type=int, default=512)
    parser.add_argument("--indices-file", type=Path)
    parser.add_argument("--exclude-results", type=Path)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("choose a new output directory; previous runs are never overwritten")
    args.output.mkdir(parents=True)
    if args.indices_file:
        supplied = json.loads(args.indices_file.read_text())
        indices = supplied["coverage_indices"] if isinstance(supplied, dict) else supplied
        items = [(6, index, ["structural-coverage-outlier"]) for index in indices]
        if args.exclude_results:
            earlier = json.loads(args.exclude_results.read_text())
            seen = {(case["n"], case["index"]) for case in earlier["cases"]}
            items = [item for item in items if item[:2] not in seen]
    else:
        items = select_cases(args.data_root, args.sample, args.seed)
    settings = {name: str(getattr(args, name).resolve()) for name in ("data_root", "closure", "verifier", "output")}
    settings.update(enumeration=args.enumeration, cut_terms=args.cut_terms)
    sources = [Path(__file__), Path(__file__).with_name("recipes.py"), Path(__file__).with_name("closure.cpp")]
    binding = {
        "format": "hec-derivation-pilot-run/1",
        "started_at": datetime.now(UTC).isoformat(),
        "sample": args.sample,
        "selection_seed": args.seed,
        "workers": args.workers,
        "settings": settings,
        "selected_cases": items,
        "source_catalog_sha256": digest(args.data_root / "n=6/proofs.json"),
        "implementation_sha256": {path.name: digest(path) for path in sources},
        "native_binary_sha256": {"closure": digest(args.closure), "verifier": digest(args.verifier)},
        "changes_production_or_repository_data": False,
        "population_scope": "all 14 small-n proofs plus a stratified/control n=6 pilot, not all n=6 proofs",
    }
    (args.output / "run-binding.json").write_text(json.dumps(binding, sort_keys=True, indent=2) + "\n")
    started = time.perf_counter()
    cases = []
    with ProcessPoolExecutor(max_workers=args.workers, initializer=initialize, initargs=(settings,)) as pool:
        futures = {pool.submit(benchmark_case, item): item for item in items}
        with (args.output / "cases.jsonl").open("w") as log:
            for future in as_completed(futures):
                result = future.result()
                cases.append(result)
                log.write(json.dumps(result, sort_keys=True) + "\n")
                log.flush()
                if len(cases) % 8 == 0 or len(cases) == len(items):
                    print(
                        json.dumps(
                            {
                                "completed": len(cases),
                                "total": len(items),
                                "elapsed_s": int(time.perf_counter() - started),
                                "lower_successes": sum(
                                    c["methods"]["derive-lower"]["status"] == "exact_full_cube_verified" for c in cases
                                ),
                                "upper_successes": sum(
                                    c["methods"]["derive-upper"]["status"] == "exact_full_cube_verified" for c in cases
                                ),
                            }
                        ),
                        flush=True,
                    )
    cases.sort(key=lambda case: (case["n"], case["index"]))
    report = {
        "finished_at": datetime.now(UTC).isoformat(),
        "elapsed_seconds": time.perf_counter() - started,
        "cases": cases,
        "summary": summarize(cases),
        "workers": args.workers,
        "maximum_worker_rss_bytes": max(case["worker_peak_rss_bytes"] for case in cases),
        "maximum_native_child_rss_bytes": max(case["native_child_peak_rss_bytes"] for case in cases),
        "compression_used_in_comparison": False,
        "failed_or_incomplete_attempts_are_not_proofs": True,
    }
    (args.output / "results.json").write_text(json.dumps(report, sort_keys=True, indent=2) + "\n")
    print(
        json.dumps({"cases": len(cases), "summary": report["summary"], "elapsed_seconds": report["elapsed_seconds"]}),
        flush=True,
    )


if __name__ == "__main__":
    main()
