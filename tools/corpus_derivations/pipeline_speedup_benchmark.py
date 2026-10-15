"""Small paired controls of exact unified-pipeline materialization, not a cohort.

The scalar reference is the actual hash-bound pre-optimization implementation.
Both reconstruct all compatible values and retain every local mathematical
check. The chosen actual seed also receives an independent original-cube audit.
Nothing in this experiment modifies the live synthesis or accepts stored flags.
"""

from __future__ import annotations

import argparse
import hashlib
import sqlite3
import sys
import types
from contextlib import closing
from datetime import UTC, datetime
from functools import partial
from pathlib import Path

from hec.count_proofs import canonical_json, inequality_id, parse_json
from hec.reconstruction import ReconstructionProgram

from . import run as derivations
from .pipeline_import import NativeClosure, NativePipelineAuditor, import_recipe
from .selected_corpus import check_audit
from .speedup_benchmark import guard, measure
from .synthesize import EXPECTED_TOTAL, decode_frame, geometry_only


def scalar_reference(synthesis):
    binding = parse_json((synthesis / "run-binding.json").read_bytes())
    relative = "src/hec/reconstruction.py"
    path = synthesis / "implementation" / relative
    raw, expected = path.read_bytes(), binding["implementation"][relative]
    if hashlib.sha256(raw).hexdigest() != expected:
        raise ValueError("frozen scalar reference implementation changed")
    # Trusted, explicitly hash-bound code only; never a proof-specified module,
    # expression or executable. Compile from read bytes without writing pycache
    # into the live immutable implementation directory.
    name = "hec._scalar_pipeline_control_" + expected[:16]
    module = types.ModuleType(name)
    module.__file__, module.__package__ = str(path), "hec"
    sys.modules[name] = module
    exec(compile(raw, str(path), "exec"), vars(module))
    if "cut_integer_rows" in vars(module):
        raise ValueError("control must precede the bulk cut materialization optimization")
    return module.ReconstructionProgram, {"path": str(path), "sha256": expected}


def materialized(program_class, raw, closure_backend):
    program = program_class(raw, closure_backend=closure_backend)
    program.materialize_seed()
    return program


def compare(first, second):
    a, b = first.materialize_seed(), second.materialize_seed()
    if (
        first.raw != second.raw
        or first.problem != second.problem
        or first.clearing_scale != second.clearing_scale
        or (a.vertices, a.scale, a.numerators, a.checked_edges, a.semantic_sha256)
        != (b.vertices, b.scale, b.numerators, b.checked_edges, b.semantic_sha256)
        or first.semantic_identity() != second.semantic_identity()
    ):
        raise ValueError("bulk materialization changed exact values, checks or full-map semantics")


def benchmark(source, synthesis, output, tasks, *, repeats=2):
    source, synthesis, output = (Path(path).resolve() for path in (source, synthesis, output))
    checkout = Path(__file__).resolve().parents[2]
    if not 1 <= len(tasks) <= 8 or len(set(tasks)) != len(tasks) or not 1 <= repeats <= 5:
        raise ValueError("use at most eight unique bounded controls and five paired repeats")
    if any(type(task) is not int or task < 0 for task in tasks):
        raise ValueError("control identities must be exact nonnegative indices")
    if any(output.is_relative_to(path) or path.is_relative_to(output) for path in (source, synthesis, checkout)):
        raise ValueError("experiment output must be outside protected inputs/worktree")
    if output.exists() and any(output.iterdir()):
        raise ValueError("choose a new empty immutable experiment directory")
    binding = parse_json((source / "run-binding.json").read_bytes())
    if binding["total"] != EXPECTED_TOTAL or derivations.digest(source / "manifest.json") != binding["manifest_sha256"]:
        raise ValueError("control source changed its bound full corpus identity")
    manifest = parse_json((source / "manifest.json").read_bytes())
    reference, reference_binding = scalar_reference(synthesis)
    files = [
        path
        for folder in ("src/hec", "tools/corpus_derivations", "tools/derivation_pilot")
        for path in (checkout / folder).rglob("*")
        if path.is_file() and path.suffix in (".py", ".cpp")
    ]
    implementation = {str(path.relative_to(checkout)): derivations.digest(path) for path in sorted(files)}
    resources, cases = [guard(synthesis)], []
    output.mkdir(parents=True, exist_ok=True)
    settings = {
        "format": "hec-bounded-pipeline-speedup-control/1",
        "prepared_utc": datetime.now(UTC).isoformat(),
        "source": str(source),
        "source_binding_sha256": derivations.digest(source / "run-binding.json"),
        "observed_synthesis": str(synthesis),
        "scalar_reference": reference_binding,
        "implementation": implementation,
        "tasks": tasks,
        "paired_repeats": repeats,
        "python": sys.version,
        "binaries": binding["binaries"],
        "rss_limit_bytes": 64 * 1024**3,
        "new_corpus_workers_started": 0,
        "live_cohort_modified": False,
        "full_corpus_coverage_claimed": False,
    }
    derivations.save_new(output / "binding.json", settings)
    info = binding["binaries"]["wide"]
    auditor = NativePipelineAuditor(info["path"], info["sha256"])
    info = binding["binaries"]["closure"]
    closure = NativeClosure(info["path"], info["sha256"])
    try:
        with closing(sqlite3.connect(f"file:{source / 'checkpoint.sqlite3'}?mode=ro", uri=True)) as db:
            for task in tasks:
                if not 0 <= task < len(manifest):
                    raise ValueError("invalid source control task")
                row = db.execute(
                    "SELECT inequality_id,recipe_sha256,json_bytes,compressed FROM results WHERE task=?", (task,)
                ).fetchone()
                if row is None or row[0] != manifest[task]["inequality_id"] or row[2] > 32 * 1024**2:
                    raise ValueError("control missing, out of scope or too large")
                raw = decode_frame(row[3], row[2])
                document = parse_json(raw)
                p = geometry_only(document)
                if (
                    hashlib.sha256(raw).hexdigest() != row[1]
                    or canonical_json(document) != raw
                    or inequality_id(p) != row[0]
                ):
                    raise ValueError("control changed its canonical source identity")
                fresh = db.execute("SELECT report FROM fresh WHERE task=? AND ok=1", (task,)).fetchone()
                if fresh is None:
                    raise ValueError("control lacks its executed source-free full-cube audit")
                check_audit(parse_json(fresh[0].encode()), task, row[1], p)
                identity = {"task": task, "inequality_id": row[0], "source_sha256": row[1]}
                target, receipt = import_recipe(document, closure_backend=closure)
                target_raw, comparisons = canonical_json(target), []
                derivations.save_new(output / f"{task}.pipeline.json", target)
                for repeat in range(repeats):
                    measured, programs = {}, {}
                    for name in ("scalar", "bulk") if repeat % 2 == 0 else ("bulk", "scalar"):
                        resources.append(guard(synthesis))
                        cls = reference if name == "scalar" else ReconstructionProgram
                        programs[name], measured[name] = measure(partial(materialized, cls, target_raw, closure))
                    compare(programs["scalar"], programs["bulk"])
                    comparisons.append({"repeat": repeat, "timings": measured})
                program = programs["bulk"]
                resources.append(guard(synthesis))
                audit, timing = measure(partial(program.audit, auditor))
                seed = program.materialize_seed()
                case = {
                    **identity,
                    "target_definition_sha256": hashlib.sha256(target_raw).hexdigest(),
                    "semantic_map_id": program.semantic_identity(),
                    "L": program.problem.L,
                    "G": program.problem.G,
                    "seed_primitive": program.stages[1],
                    "seed_scale": str(program.materialize_seed().scale),
                    "compatible_vertices": len(seed.vertices),
                    "compatible_cells_compared": len(seed.vertices) * program.problem.G,
                    "conversion": receipt,
                    "paired_comparisons": comparisons,
                    "independent_full_cube_audit": audit,
                    "independent_audit_timing": timing,
                    "status": "identical_complete_seed_and_semantics_with_executed_independent_cube_audit",
                }
                derivations.save_new(output / f"{task}.result.json", case)
                cases.append(case)
        if any(derivations.digest(checkout / path) != sha for path, sha in implementation.items()):
            raise ValueError("executing benchmark implementation changed while controls were running")
        report = {
            "format": "hec-bounded-pipeline-speedup-report/1",
            "reported_utc": datetime.now(UTC).isoformat(),
            "binding_sha256": derivations.digest(output / "binding.json"),
            "cases": cases,
            "resource_samples": resources,
            "full_goal_complete": False,
            "live_cohort_modified": False,
            "caveats": [
                "Hand-picked bounded controls, not corpus-wide coverage or a universal speedup.",
                "Wall timings include host contention; own-process and reaped closure child CPU are separate.",
                "Each materialization retains complete local seed checks; these are not cube acceptance.",
                "Independent native cube audits were additionally executed once per identical full map.",
                "Full-scope conversion, separate saved-map audits and integration remain required.",
            ],
        }
        derivations.save_new(output / "report.json", report)
        return report
    finally:
        auditor.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("source", "synthesis", "output"):
        parser.add_argument("--" + name, required=True, type=Path)
    parser.add_argument("--tasks", required=True, type=int, nargs="+")
    parser.add_argument("--repeats", default=2, type=int)
    args = parser.parse_args()
    result = benchmark(args.source, args.synthesis, args.output, args.tasks, repeats=args.repeats)
    print(canonical_json({"report": str(args.output / "report.json"), "cases": len(result["cases"])}).decode())


if __name__ == "__main__":
    main()
