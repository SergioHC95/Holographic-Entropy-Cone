"""Bounded same-algorithm native smoothing controls; no live rollout or proof import."""

from __future__ import annotations

import argparse
import hashlib
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from functools import partial
from pathlib import Path

from hec.count_proofs import canonical_json, inequality_id, parse_json

from . import run as derivations
from .native_smooth import NativeSmoother, supported
from .pipeline_import import NativePipelineAuditor
from .selected_corpus import check_audit
from .simplify import WorkLimit, smooth
from .speedup_benchmark import guard, measure
from .speedups import reconstruct
from .synthesize import EXPECTED_TOTAL, decode_frame, geometry_only


def disposition(action):
    try:
        return "complete", action()
    except WorkLimit:
        return "identical_budget_exhaustion_not_a_proof", None


def cold_native(binary, sha, values):
    engine = NativeSmoother(binary, sha)
    try:
        return disposition(partial(engine.smooth, *values))
    finally:
        engine.close()  # Include startup, all Python postchecks and reaped child CPU.


def benchmark(source, synthesis, binary, output, tasks, *, repeats=2):
    source, synthesis, binary, output = (Path(value).resolve() for value in (source, synthesis, binary, output))
    checkout = Path(__file__).resolve().parents[2]
    if not 1 <= len(tasks) <= 16 or len(set(tasks)) != len(tasks) or not 1 <= repeats <= 5:
        raise ValueError("choose at most sixteen unique bounded controls and five paired repeats")
    if output.exists() and any(output.iterdir()):
        raise ValueError("choose an empty new immutable output")
    if any(output.is_relative_to(path) or path.is_relative_to(output) for path in (source, synthesis, checkout)):
        raise ValueError("benchmark must not overwrite protected corpus/worktree paths")
    binding = parse_json((source / "run-binding.json").read_bytes())
    if binding["total"] != EXPECTED_TOTAL or derivations.digest(source / "manifest.json") != binding["manifest_sha256"]:
        raise ValueError("source corpus manifest changed")
    for info in binding["binaries"].values():
        if derivations.digest(info["path"]) != info["sha256"]:
            raise ValueError("independent exact primitive binary changed")
    manifest = parse_json((source / "manifest.json").read_bytes())
    sha = derivations.digest(binary)
    files = (
        "tools/corpus_derivations/native_smooth.py",
        "tools/corpus_derivations/smooth_exact.cpp",
        "tools/corpus_derivations/native_smoothing_benchmark.py",
        "tools/corpus_derivations/simplify.py",
        "tools/corpus_derivations/diagrams.py",
        "tools/corpus_derivations/speedups.py",
        "tools/corpus_derivations/native.py",
        "tools/derivation_pilot/recipes.py",
        "src/hec/count_proofs.py",
        "src/hec/_count_transport.py",
    )
    implementation = {path: derivations.digest(checkout / path) for path in files}
    resources, cases = [guard(synthesis)], []
    output.mkdir(parents=True, exist_ok=True)
    derivations.save_new(
        output / "binding.json",
        {
            "format": "hec-native-smoothing-control-run/1",
            "prepared_utc": datetime.now(UTC).isoformat(),
            "source_binding_sha256": derivations.digest(source / "run-binding.json"),
            "source": str(source),
            "observed_synthesis": str(synthesis),
            "tasks": tasks,
            "binary": {"path": str(binary), "sha256": sha},
            "implementation": implementation,
            "paired_repeats": repeats,
            "sweeps": 2,
            "max_work": 50_000_000,
            "production_workers_started": 0,
            "rss_limit_bytes": 64 * 1024**3,
        },
    )
    info = binding["binaries"]["wide"]
    auditor = NativePipelineAuditor(info["path"], info["sha256"])
    try:
        with closing(sqlite3.connect(f"file:{source / 'checkpoint.sqlite3'}?mode=ro", uri=True)) as db:
            for task in tasks:
                if type(task) is not int or not 0 <= task < len(manifest):
                    raise ValueError("invalid source identity")
                item = db.execute(
                    "SELECT inequality_id,recipe_sha256,json_bytes,compressed FROM results WHERE task=?", (task,)
                ).fetchone()
                if item is None or item[0] != manifest[task]["inequality_id"] or item[2] > 32 * 1024**2:
                    raise ValueError("missing or unbounded control")
                raw = decode_frame(item[3], item[2])
                document = parse_json(raw)
                p = geometry_only(document)
                if (
                    hashlib.sha256(raw).hexdigest() != item[1]
                    or canonical_json(document) != raw
                    or inequality_id(p) != item[0]
                ):
                    raise ValueError("saved control identity changed")
                fresh = db.execute("SELECT report FROM fresh WHERE task=? AND ok=1", (task,)).fetchone()
                if fresh is None:
                    raise ValueError("saved control lacks its source-free full-cube audit")
                check_audit(parse_json(fresh[0].encode()), task, item[1], p)
                values = reconstruct(document)
                if not supported(*values):
                    raise ValueError("control exceeds exact native smoothing capability")
                comparisons = []
                for repeat in range(repeats):
                    outputs, timings = {}, {}
                    for name in ("python", "native") if repeat % 2 == 0 else ("native", "python"):
                        resources.append(guard(synthesis))
                        action = (
                            partial(disposition, partial(smooth, *values))
                            if name == "python"
                            else partial(cold_native, binary, sha, values)
                        )
                        outputs[name], timings[name] = measure(action)
                    if outputs["python"] != outputs["native"]:
                        raise ValueError(
                            "native smoothing changed a seed value, denominator, statistic or charged work"
                        )
                    comparisons.append({"repeat": repeat, "timings": timings})
                status, result = outputs["native"]
                audit = None
                if result is not None:
                    resources.append(guard(synthesis))
                    new_scale, rows, statistics = result
                    audit = auditor.verify(p, values[1], new_scale, rows)
                else:
                    statistics = None
                case = {
                    "task": task,
                    "inequality_id": item[0],
                    "source_sha256": item[1],
                    "L": p.L,
                    "G": p.G,
                    "source_scale": str(values[2]),
                    "compatible_vertices": len(values[1]),
                    "compatible_cells_compared": len(values[1]) * p.G if result is not None else 0,
                    "status": status,
                    "statistics": statistics,
                    "paired_comparisons": comparisons,
                    "independent_original_cube_audit": audit,
                    "full_corpus_coverage_claimed": False,
                }
                derivations.save_new(output / f"{task}.result.json", case)
                cases.append(case)
                print(canonical_json({"completed_control": task, "status": status}).decode(), flush=True)
        if any(derivations.digest(checkout / path) != value for path, value in implementation.items()):
            raise ValueError("control implementation changed during measurements")
        report = {
            "format": "hec-native-smoothing-control-report/1",
            "reported_utc": datetime.now(UTC).isoformat(),
            "binding_sha256": derivations.digest(output / "binding.json"),
            "cases": cases,
            "resource_samples": resources,
            "live_cohort_modified": False,
            "full_goal_complete": False,
            "caveats": [
                "Selected controls, not representative population performance or full-corpus coverage.",
                "Cold native timings include process startup and arbitrary-precision Python postchecks.",
                "Native child CPU is included only after reaping; own Python CPU is separate.",
                "Budget exhaustion is not a proof; every complete control receives its own independent cube audit.",
            ],
        }
        derivations.save_new(output / "report.json", report)
        return report
    finally:
        auditor.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("source", "synthesis", "binary", "output"):
        parser.add_argument("--" + name, required=True, type=Path)
    parser.add_argument("--tasks", nargs="+", type=int, required=True)
    parser.add_argument("--repeats", type=int, default=2)
    args = parser.parse_args()
    benchmark(args.source, args.synthesis, args.binary, args.output, args.tasks, repeats=args.repeats)
    print(canonical_json({"report": str(args.output / "report.json")}).decode())


if __name__ == "__main__":
    main()
