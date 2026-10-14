"""Opt-in experiment: reuse a bound compact input seed, never a Boolean archive.

This does NOT enable a production cache. Every tested seed is compared in full
with the saved recipe decoder. A trusted input locator is not mathematical
acceptance; independent candidate and fresh cube audits remain mandatory.
"""

import argparse
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

from hec.count_proofs import canonical_json, inequality_id, parse_json
from hec.proof_store import ProofCatalog

from . import run as derivations
from .diagrams import common_seed
from .speedup_benchmark import guard, load_control, measure


def check(source, synthesis, output, tasks, *, validated_reader=False):
    source, synthesis, output = Path(source).resolve(), Path(synthesis).resolve(), Path(output).resolve()
    if not tasks or len(tasks) > 8 or len(set(tasks)) != len(tasks):
        raise ValueError("choose at most eight distinct bounded controls")
    if output.exists() and any(output.iterdir()):
        raise ValueError("choose a new immutable seed experiment directory")
    for protected in (source, synthesis, Path(__file__).resolve().parents[2]):
        if output.is_relative_to(protected) or protected.is_relative_to(output):
            raise ValueError("experiment cannot modify protected inputs")
    binding = parse_json((source / "run-binding.json").read_bytes())
    if derivations.digest(source / "manifest.json") != binding["manifest_sha256"]:
        raise ValueError("bound source manifest changed")
    manifest = parse_json((source / "manifest.json").read_bytes())
    guard(synthesis)
    output.mkdir(parents=True, exist_ok=True)
    derivations.initialize(binding)
    catalogs, cases = {}, []
    reader = None
    if validated_reader:
        from .compact_source import POLICY, Reader

        reader = Reader(
            {
                "source": str(source),
                "source_total": binding["total"],
                "source_seed_input": {
                    "policy": POLICY,
                    "source_binding_sha256": derivations.digest(source / "run-binding.json"),
                    "source_manifest_sha256": binding["manifest_sha256"],
                },
            }
        )
    try:
        with closing(sqlite3.connect(f"file:{source / 'checkpoint.sqlite3'}?mode=ro", uri=True)) as db:
            for task in tasks:
                guard(synthesis)
                raw, info = load_control(db, task, manifest)
                entry = manifest[task]
                if entry["group"] == "primitive" or "catalog" not in entry:
                    raise ValueError("this experiment never reads original Boolean archive payloads")
                report = parse_json(
                    db.execute("SELECT report FROM results WHERE task=?", (task,)).fetchone()[0].encode()
                )
                if report.get("source_proof_id") != entry["source_proof_id"]:
                    raise ValueError("source derivation receipt lost the bound input proof identity")
                key = entry["catalog"]
                expected = binding["source_catalogs"][key]["sha256"]
                if derivations.digest(key) != expected:
                    raise ValueError("compact input catalog changed")
                old, cost = measure(lambda raw=raw: derivations.reconstruct(parse_json(raw)))

                def direct(entry=entry, key=key, raw=raw, info=info):
                    if reader is not None:
                        result = reader.decode(
                            (entry["task"], raw, info["source_sha256"], info["inequality_id"]), parse_json(raw)
                        )
                        if result is None:
                            raise ValueError("chosen gate control cannot exercise the reviewed provenance reader")
                        return result[0]
                    if key not in catalogs:
                        catalogs[key] = ProofCatalog(key)
                    catalog = catalogs[key]
                    if catalog.entries[entry["index"]]["proof_id"] != entry["source_proof_id"]:
                        raise ValueError("compact input index/proof binding changed")
                    proof = catalog[entry["index"]]
                    if "rows" not in proof["function"]:
                        raise ValueError("selected direct-input control is not a compact seed table")
                    decoded = common_seed(proof)
                    if inequality_id(decoded[0]) != entry["inequality_id"]:
                        raise ValueError("compact input belongs to another exact inequality")
                    return decoded

                cold, cold_cost = measure(direct)
                warm, warm_cost = measure(direct)
                if old != cold or old != warm:
                    raise ValueError("direct compact seed differs from complete saved-recipe semantics")
                p, vertices, scale, rows = old
                cases.append(
                    {
                        **info,
                        "input_proof_id": entry["source_proof_id"],
                        "input_catalog_sha256": expected,
                        "L": p.L,
                        "G": p.G,
                        "compatible_vertices": len(vertices),
                        "seed_scale": str(scale),
                        "saved_recipe_decode": cost,
                        "direct_cold": cold_cost,
                        "direct_warm": warm_cost,
                        "every_exact_compatible_value_equal": True,
                    }
                )
        result = {
            "format": "hec-direct-compact-source-seed-experiment/1",
            "reported_utc": datetime.now(UTC).isoformat(),
            "implementation_sha256": {
                name: derivations.digest(Path(__file__).resolve().parents[2] / name)
                for name in (
                    "tools/corpus_derivations/source_seed_benchmark.py",
                    "tools/corpus_derivations/run.py",
                    "tools/corpus_derivations/diagrams.py",
                    "src/hec/proof_store.py",
                    "src/hec/count_proofs.py",
                    "tools/corpus_derivations/compact_source.py",
                )
            },
            "source_binding_sha256": derivations.digest(source / "run-binding.json"),
            "cases": cases,
            "original_boolean_archives_read": False,
            "new_cube_audits_executed": 0,
            "scope": "complete-compatible-value-equivalence-and-identical-fixed-extension",
            "deployed_to_production": False,
            "validated_provenance_reader": validated_reader,
            "full_corpus_coverage_claimed": False,
            "limitations": [
                "Cold catalog/shard integrity checks are included; warm reads amortize them.",
                "Only these hand-picked cases were compared; production cache provenance needs review.",
                "Input identity is not proof acceptance; independent full-cube and fresh audits remain required.",
            ],
        }
        derivations.save_new(output / "result.json", result)
        return result
    finally:
        if reader is not None:
            reader.close()
        derivations.NARROW.close()
        derivations.WIDE.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--synthesis", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--tasks", required=True, type=int, nargs="+")
    parser.add_argument("--validated-reader", action="store_true")
    args = parser.parse_args()
    print(
        canonical_json(
            check(args.source, args.synthesis, args.output, args.tasks, validated_reader=args.validated_reader)
        ).decode(),
        flush=True,
    )


if __name__ == "__main__":
    main()
