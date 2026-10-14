"""Stress the new exact cut decoder at every observed source-dimension category.

Largest stored cut recipe per L is a deliberate stress selection, not a random
sample or whole-corpus coverage. Complete seed equality and the same fixed
extension preserve each source map; this does NOT execute another cube audit.
"""

import argparse
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

from hec.count_proofs import canonical_json, parse_json

from . import run as derivations
from . import speedups
from .speedup_benchmark import guard, load_control, measure


def check(source, synthesis, output):
    source, synthesis, output = Path(source).resolve(), Path(synthesis).resolve(), Path(output).resolve()
    if output.exists() and any(output.iterdir()):
        raise ValueError("choose a new empty decoder-gate directory")
    for protected in (source, synthesis, Path(__file__).resolve().parents[2]):
        if output.is_relative_to(protected) or protected.is_relative_to(output):
            raise ValueError("decoder gate cannot write into its protected inputs/worktree")
    binding = parse_json((source / "run-binding.json").read_bytes())
    if derivations.digest(source / "manifest.json") != binding["manifest_sha256"]:
        raise ValueError("source manifest changed")
    manifest = parse_json((source / "manifest.json").read_bytes())
    guard(synthesis)
    output.mkdir(parents=True, exist_ok=True)
    derivations.SETTINGS = binding  # CUTS uses no native process or archived source table.
    cases, cells = [], 0
    with closing(sqlite3.connect(f"file:{source / 'checkpoint.sqlite3'}?mode=ro", uri=True)) as db:
        selected = db.execute("""SELECT task FROM (
          SELECT task, ROW_NUMBER() OVER (
            PARTITION BY json_extract(report,'$.L') ORDER BY json_bytes DESC,task) AS rank
          FROM results WHERE winner='cut-formulas') WHERE rank=1 ORDER BY task""").fetchall()
        if not 1 <= len(selected) <= 24:
            raise ValueError("unexpected stress-control geometry scope")
        for (task,) in selected:
            guard(synthesis)
            raw, info = load_control(db, task, manifest)
            document = parse_json(raw)
            old, old_cost = measure(lambda: derivations.reconstruct(document))  # noqa: B023
            new, new_cost = measure(lambda: speedups.reconstruct(document))  # noqa: B023
            if old != new:
                raise ValueError("bulk cut decoder changed a complete exact compatible value")
            p, vertices, scale, rows = new
            cells += len(rows) * p.G
            cases.append(
                {
                    **info,
                    "L": p.L,
                    "G": p.G,
                    "compatible_vertices": len(vertices),
                    "seed_scale": str(scale),
                    "old_cost": old_cost,
                    "new_cost": new_cost,
                    "exact_all_compatible_values_equal": True,
                }
            )
    result = {
        "format": "hec-exact-cut-decoder-stress-gate/1",
        "reported_utc": datetime.now(UTC).isoformat(),
        "source_binding_sha256": derivations.digest(source / "run-binding.json"),
        "implementation_sha256": {
            p: derivations.digest(Path(__file__).resolve().parents[2] / p)
            for p in (
                "tools/corpus_derivations/speedup_gate.py",
                "tools/corpus_derivations/speedups.py",
                "tools/derivation_pilot/recipes.py",
                "src/hec/count_proofs.py",
            )
        },
        "cases": cases,
        "compared_compatible_cells": cells,
        "selection": "largest stored cut description in each observed source L category",
        "scope": "complete-compatible-value-equivalence-and-identical-fixed-extension",
        "new_original_cube_audits_executed": 0,
        "full_corpus_coverage_claimed": False,
        "live_cohort_changed": False,
    }
    derivations.save_new(output / "gate.json", result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--synthesis", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    print(canonical_json(check(args.source, args.synthesis, args.output)).decode(), flush=True)


if __name__ == "__main__":
    main()
