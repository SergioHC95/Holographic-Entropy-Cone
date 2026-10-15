"""Bounded paired full audits of old double-parse and single-parse read paths.

The same saved canonical definitions and exact verifier are used in both arms.
No corpus workers, source changes, acceptance cache, or production promotion.
"""

from __future__ import annotations

import argparse
import hashlib
from datetime import UTC, datetime
from functools import partial
from pathlib import Path

import zstandard as zstd

from hec.count_proofs import canonical_json, parse_json, proof_id
from hec.proof_store import CATALOG_FORMAT
from hec.reconstruction_store import ReconstructionCatalog
from hec.reconstruction_verify import ReconstructionVerifier

from . import run as derivations
from .repository_stage import Frames
from .speedup_benchmark import guard, measure


def audit(catalog, index, binaries, single_parse):
    verifier = ReconstructionVerifier(closure_binary=binaries["closure"]["path"], cube_binary=binaries["wide"]["path"])
    try:
        return catalog.audit_entry(index, verifier) if single_parse else verifier.verify(catalog[index])
    finally:
        verifier.close()  # Timings include reaped native CPU, not only Python CPU.


def benchmark(controls, observed_run, output, *, repeats=2):
    controls, observed_run, output = (Path(value).resolve() for value in (controls, observed_run, output))
    checkout = Path(__file__).resolve().parents[2]
    if type(repeats) is not int or not 1 <= repeats <= 3:
        raise ValueError("one through three bounded paired timing repeats required")
    for protected in (controls, observed_run, checkout):
        if output.is_relative_to(protected) or protected.is_relative_to(output):
            raise ValueError("new benchmark output must be outside protected inputs/run/worktree")
    if output.exists() and any(output.iterdir()):
        raise ValueError("new immutable benchmark output only")
    previous = parse_json((controls / "report.json").read_bytes())
    if previous.get("format") != "hec-bounded-pipeline-speedup-report/1" or not 1 <= len(previous["cases"]) <= 8:
        raise ValueError("bounded saved pipeline controls required, not arbitrary acceptance flags")
    binding = parse_json((observed_run / "run-binding.json").read_bytes())
    binaries = {key: binding["binaries"][key] for key in ("closure", "wide")}
    for info in binaries.values():
        if derivations.digest(info["path"]) != info["sha256"]:
            raise ValueError("independent exact binary changed")
    implementation = {
        str(path.relative_to(checkout)): derivations.digest(path)
        for folder in ("src/hec", "tools/corpus_derivations", "tools/derivation_pilot")
        for path in sorted((checkout / folder).rglob("*"))
        if path.is_file() and path.suffix in (".py", ".cpp")
    }
    resources = [guard(observed_run)]
    inputs = {str(controls / "report.json"): derivations.digest(controls / "report.json")}
    documents = []
    for case in previous["cases"]:
        path = controls / f"{case['task']}.pipeline.json"
        document = parse_json(path.read_bytes())
        raw = canonical_json(document)
        if (
            hashlib.sha256(raw).hexdigest() != case["target_definition_sha256"]
            or proof_id(document) != case["conversion"]["target_proof_id"]
        ):
            raise ValueError("saved control changed canonical definition or proof identity")
        documents.append((case, raw))
        inputs[str(path)] = derivations.digest(path)
    output.mkdir(parents=True, exist_ok=True)
    settings = {
        "format": "hec-catalog-audit-speed-control/1",
        "prepared_utc": datetime.now(UTC).isoformat(),
        "observed_run": str(observed_run),
        "observed_binding_sha256": derivations.digest(observed_run / "run-binding.json"),
        "inputs": inputs,
        "implementation": implementation,
        "binaries": binaries,
        "paired_repeats": repeats,
        "rss_limit_bytes": 64 * 1024**3,
        "new_corpus_workers_started": 0,
        "live_cohort_modified": False,
    }
    derivations.save_new(output / "binding.json", settings)
    frames = Frames(output / "catalog", 16 * 1024**2)
    for case, raw in documents:
        frames.append(
            case["inequality_id"], proof_id(parse_json(raw)), zstd.ZstdCompressor(write_checksum=True).compress(raw)
        )
    frames.seal()
    path = output / "catalog" / "proofs.json"
    derivations.save_new(path, {"format": CATALOG_FORMAT, "entries": frames.entries, "shards": frames.shards})
    baseline, optimized = ReconstructionCatalog(path), ReconstructionCatalog(path)
    for reader in (baseline, optimized):
        for key in reader.shards:
            reader._shard_path(key)  # Equal warm hash-cache setup; not mathematical acceptance.
    cases, executed_edges = [], 0
    for index, (case, _raw) in enumerate(documents):
        pairs = []
        expected = {
            "ok": True,
            "scope": "original-cube-all-edges",
            "proof_id": case["conversion"]["target_proof_id"],
            "inequality_id": case["inequality_id"],
            "semantic_map_id": case["semantic_map_id"],
            "checked_vertices": 1 << case["L"],
            "checked_edges": case["L"] * ((1 << case["L"]) // 2),
            "source_tables_read": False,
        }
        for repeat in range(repeats):
            timings = {}
            for name in ("double_parse", "single_parse") if repeat % 2 == 0 else ("single_parse", "double_parse"):
                resources.append(guard(observed_run))
                reader = optimized if name == "single_parse" else baseline
                result, timings[name] = measure(partial(audit, reader, index, binaries, name == "single_parse"))
                if any(
                    type(result.get(key)) is not type(value) or result[key] != value for key, value in expected.items()
                ):
                    raise ValueError("actual independent cube audit changed semantics, identity or complete coverage")
                executed_edges += result["checked_edges"]
                resources.append(guard(observed_run))
            pairs.append({"repeat": repeat, "timings": timings})
        result = {"task": case["task"], "primitive": case["seed_primitive"], **expected, "pairs": pairs}
        derivations.save_new(output / f"{case['task']}.result.json", result)
        cases.append(result)
    for relative, sha in implementation.items():
        if derivations.digest(checkout / relative) != sha:
            raise ValueError("executing benchmark implementation changed")
    for path, sha in inputs.items():
        if derivations.digest(path) != sha:
            raise ValueError("immutable benchmark input changed")
    report = {
        "format": "hec-catalog-audit-speed-report/1",
        "reported_utc": datetime.now(UTC).isoformat(),
        "binding_sha256": derivations.digest(output / "binding.json"),
        "cases": cases,
        "actual_executed_original_cube_edges_including_timing_repeats": executed_edges,
        "resource_samples": resources,
        "live_cohort_modified": False,
        "production_format_promoted": False,
        "full_goal_complete": False,
        "caveats": [
            "Hand-picked controls, not whole-corpus coverage or a universal speedup.",
            "Both arms execute actual complete cube audits; no stored receipt is acceptance.",
            "Same canonical frames, hash checks and exact verifier; only redundant syntax construction is removed.",
            "Timing includes native startup/reaping; CPU and host-contention-sensitive wall time are separate.",
        ],
    }
    derivations.save_new(output / "report.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("controls", "observed-run", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--repeats", type=int, default=2)
    args = parser.parse_args()
    result = benchmark(args.controls, args.observed_run, args.output, repeats=args.repeats)
    print(canonical_json({"report": str(args.output / "report.json"), "cases": len(result["cases"])}).decode())


if __name__ == "__main__":
    main()
