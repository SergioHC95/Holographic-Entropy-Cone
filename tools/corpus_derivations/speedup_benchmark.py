"""Bounded single-process speed controls, NEVER a corpus acceptance/export.

The live cohort is observed, not modified. Inputs and outputs are hash-bound;
only the chosen encoding receives mathematical acceptance. Timing controls
are explicitly not a population sample, CPU extrapolation or a universal gain.
"""

from __future__ import annotations

import argparse
import cProfile
import hashlib
import io
import os
import pstats
import resource
import sqlite3
import sys
import time
from contextlib import closing
from datetime import UTC, datetime
from fractions import Fraction
from functools import partial
from pathlib import Path
from unittest.mock import patch

import numpy as np
import zstandard as zstd

from hec.count_proofs import canonical_json, inequality_id, parse_json

from . import run as derivations
from . import speedups, synthesize
from .selected_corpus import check_audit
from .simplify import WorkLimit, smooth
from .synthesize import EXPECTED_TOTAL, decode_frame, geometry_only


def measure(action):
    children = resource.getrusage(resource.RUSAGE_CHILDREN)
    cpu, started = time.process_time_ns(), time.perf_counter_ns()
    result = action()
    wall, own = time.perf_counter_ns() - started, time.process_time_ns() - cpu
    after = resource.getrusage(resource.RUSAGE_CHILDREN)
    return result, {
        "wall_nanoseconds": wall,
        "python_process_cpu_nanoseconds": own,
        "reaped_child_cpu_microseconds": round(
            1_000_000 * (after.ru_utime + after.ru_stime - children.ru_utime - children.ru_stime)
        ),
    }


def guard(synthesis):
    """Only abort THIS small experiment; never signal a live corpus process."""
    live = parse_json((synthesis / "controller.json").read_bytes())
    from .continue_pipeline import birth, processes

    rows = processes()
    owner = next((row for row in rows if row["pid"] == live["pid"]), None)
    if owner is None or birth(owner["birth"]) != birth(live["birth"]) or str(synthesis) not in owner["command"]:
        raise RuntimeError("live synthesis identity changed; stop the experiment, never recover or compete here")
    first, a = derivations.process_usage(live["pid"])
    second, b = derivations.process_usage(os.getpid())
    if first + second > 64 * 1024**3 or any(row["rss_bytes"] > 64 * 1024**3 for row in a + b):
        raise MemoryError("combined experiment/cohort RSS exceeds unchanged 64 GiB cap")
    return {"sample_utc": datetime.now(UTC).isoformat(), "cohort_rss_bytes": first, "experiment_rss_bytes": second}


def load_control(db, task, manifest):
    row = db.execute(
        "SELECT inequality_id,recipe_sha256,json_bytes,compressed FROM results WHERE task=?", (task,)
    ).fetchone()
    if row is None or not 0 <= task < len(manifest) or row[0] != manifest[task]["inequality_id"]:
        raise ValueError("control missing from the complete source manifest")
    iid, sha, size, packed = row
    raw = decode_frame(packed, size)
    document = parse_json(raw)
    p = geometry_only(document)
    if hashlib.sha256(raw).hexdigest() != sha or canonical_json(document) != raw or inequality_id(p) != iid:
        raise ValueError("control changed its exact source identity")
    receipt = db.execute("SELECT report FROM fresh WHERE task=? AND ok=1", (task,)).fetchone()
    if receipt is None:
        raise ValueError("control lacks its executed source-free cube audit")
    check_audit(parse_json(receipt[0].encode()), task, sha, p)
    if p.L > 17 or size > 32 * 1024**2:
        raise ValueError("choose a bounded control; this experiment is not a new large corpus cohort")
    return raw, {"task": task, "inequality_id": iid, "source_sha256": sha}


def benchmark(source, synthesis, output, tasks, *, repeats=2, profile=False):
    source, synthesis, output = Path(source).resolve(), Path(synthesis).resolve(), Path(output).resolve()
    checkout = Path(__file__).resolve().parents[2]
    if not tasks or len(tasks) > 8 or len(set(tasks)) != len(tasks) or not 1 <= repeats <= 5:
        raise ValueError("use one through eight unique controls and one through five paired repeats")
    if any(type(task) is not int or task < 0 for task in tasks):
        raise ValueError("control tasks must be exact nonnegative indices")
    for protected in (source, synthesis, checkout):
        if output.is_relative_to(protected) or protected.is_relative_to(output):
            raise ValueError("experiment must be outside protected original/run/worktree paths")
    if output.exists() and any(output.iterdir()):
        raise ValueError("choose a new empty immutable experiment directory")
    binding = parse_json((source / "run-binding.json").read_bytes())
    if binding["total"] != EXPECTED_TOTAL or derivations.digest(source / "manifest.json") != binding["manifest_sha256"]:
        raise ValueError("experiment source is not the complete bound corpus")
    manifest = parse_json((source / "manifest.json").read_bytes())
    for info in binding["binaries"].values():
        if derivations.digest(info["path"]) != info["sha256"]:
            raise ValueError("independent primitive binary changed")
    guard(synthesis)
    output.mkdir(parents=True, exist_ok=True)
    derivations.initialize(binding)
    closure = Path(binding["binaries"]["closure"]["path"])
    cases, resources = [], []
    root_files = (
        "tools/corpus_derivations/speedups.py",
        "tools/corpus_derivations/speedup_benchmark.py",
        "tools/corpus_derivations/simplify.py",
        "tools/corpus_derivations/synthesize.py",
        "tools/corpus_derivations/run.py",
        "tools/corpus_derivations/diagrams.py",
        "tools/derivation_pilot/recipes.py",
        "src/hec/count_proofs.py",
        "src/hec/_count_transport.py",
    )
    settings = {
        "format": "hec-bounded-speedup-experiment/1",
        "prepared_utc": datetime.now(UTC).isoformat(),
        "source": str(source),
        "observed_synthesis": str(synthesis),
        "tasks": tasks,
        "source_binding_sha256": derivations.digest(source / "run-binding.json"),
        "implementation": {relative: derivations.digest(checkout / relative) for relative in root_files},
        "binaries": binding["binaries"],
        "python": sys.version,
        "numpy": np.__version__,
        "zstandard": zstd.__version__,
        "paired_repeats": repeats,
        "new_corpus_workers_started": 0,
        "rss_limit_bytes": 64 * 1024**3,
        "live_cohort_modified": False,
        "full_corpus_coverage_claimed": False,
    }
    derivations.save_new(output / "binding.json", settings)
    try:
        with closing(sqlite3.connect(f"file:{source / 'checkpoint.sqlite3'}?mode=ro", uri=True)) as db:
            for task in tasks:
                resources.append(guard(synthesis))
                source_raw, info = load_control(db, task, manifest)
                with (output / f"{task}.source.json").open("xb") as stream:
                    stream.write(source_raw)
                document = parse_json(source_raw)
                baseline, old_decode = measure(partial(derivations.reconstruct, document))
                fast_seed, fast_decode = measure(partial(speedups.reconstruct, document))
                if fast_seed != baseline:
                    raise ValueError("bulk decoder differs from an exact compatible source value")
                p, vertices, scale, rows = baseline
                info.update(
                    L=p.L,
                    G=p.G,
                    compatible_vertices=len(vertices),
                    source_decode=old_decode,
                    optimized_source_decode=fast_decode,
                    source_decode_exact_equivalence=True,
                )
                if profile:
                    profiler = cProfile.Profile()
                    profiler.runcall(derivations.reconstruct, document)
                    text = io.StringIO()
                    pstats.Stats(profiler, stream=text).sort_stats("cumulative").print_stats(16)
                    with (output / f"{task}.source-decode-profile.txt").open("x") as stream:
                        stream.write(text.getvalue())
                try:
                    candidate, smoothing = measure(partial(smooth, p, vertices, scale, rows))
                except WorkLimit as error:
                    cases.append({**info, "status": "incomplete_synthesis_budget_not_a_proof", "error": str(error)})
                    continue
                new_scale, changed, statistics = candidate
                info.update(smoothing=smoothing, synthesis=statistics)
                comparisons, old_reconstruct, fast_reconstruct = [], derivations.reconstruct, speedups.reconstruct

                def eager(p=p, vertices=vertices, new_scale=new_scale, changed=changed):
                    winner, raw, methods, _ = synthesize.choose_definition(
                        p, vertices, new_scale, changed, closure=closure
                    )
                    decoded = derivations.reconstruct(parse_json(raw))  # Existing caller's extra replay.
                    return winner, raw, methods, decoded

                for repeat in range(repeats):
                    results, measured, counts = {}, {}, {}
                    for name in ("eager", "optimized") if repeat % 2 == 0 else ("optimized", "eager"):
                        resources.append(guard(synthesis))
                        if name == "eager":
                            with patch.object(derivations, "reconstruct", wraps=old_reconstruct) as replay:
                                results[name], measured[name] = measure(eager)
                                counts[name] = replay.call_count
                        else:
                            with patch.object(speedups, "reconstruct", wraps=fast_reconstruct) as replay:
                                value, measured[name] = measure(
                                    partial(
                                        speedups.choose_definition, p, vertices, new_scale, changed, closure=closure
                                    )
                                )
                                results[name] = value.winner, value.raw, value.methods, value.decoded
                                counts[name] = replay.call_count
                    a, b = results["eager"], results["optimized"]
                    if a[:2] != b[:2] or a[3] != b[3] or b[3] != (p, vertices, new_scale, changed):
                        raise ValueError("deferred replay changed selected bytes or an intended exact seed value")
                    comparisons.append(
                        {
                            "repeat": repeat,
                            "timings": measured,
                            "full_seed_replays": counts,
                            "wall_ratio_eager_over_optimized": str(
                                Fraction(
                                    measured["eager"]["wall_nanoseconds"], measured["optimized"]["wall_nanoseconds"]
                                )
                            ),
                        }
                    )
                raw, decoded = results["optimized"][1], results["optimized"][3]
                with (output / f"{task}.candidate.json").open("xb") as stream:
                    stream.write(raw)
                rp, rv, rd, rr = decoded
                resources.append(guard(synthesis))
                definition = derivations.standard(rp, rd, rr)
                audit, audit_timing = measure(partial(derivations.accept, rp, rv, rd, rr, definition))
                cases.append(
                    {
                        **info,
                        "status": "byte_identical_winner_and_complete_exact_seed_equivalence",
                        "winner": results["optimized"][0],
                        "candidate_sha256": hashlib.sha256(raw).hexdigest(),
                        "paired_comparisons": comparisons,
                        "independent_full_cube_audit": audit,
                        "independent_audit_timing": audit_timing,
                        "candidate_json_bytes": len(raw),
                        "source_json_bytes": len(source_raw),
                        "strict_description_improvement": len(raw) < len(source_raw),
                    }
                )
                derivations.save_new(output / f"{task}.result.json", cases[-1])
        report = {
            "format": "hec-bounded-speedup-report/1",
            "reported_utc": datetime.now(UTC).isoformat(),
            "binding_sha256": derivations.digest(output / "binding.json"),
            "cases": cases,
            "resource_samples": resources,
            "full_goal_complete": False,
            "deployed_to_live_cohort": False,
            "caveats": [
                "Bounded hand-picked controls, not full-corpus correctness or universal speedup.",
                "Alternating paired order reduces but cannot remove host-contention effects.",
                "Stage process CPU excludes running persistent children; reaped-child CPU is separate.",
                "Both methods choose identical bytes; one executed cube audit covers that same candidate.",
                "Fresh saved-artifact audit remains required before corpus retention/export.",
            ],
        }
        derivations.save_new(output / "report.json", report)
        return report
    finally:
        derivations.NARROW.close()
        derivations.WIDE.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--synthesis", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--tasks", required=True, type=int, nargs="+")
    parser.add_argument("--repeats", type=int, default=2)
    parser.add_argument("--profile", action="store_true")
    args = parser.parse_args()
    result = benchmark(args.source, args.synthesis, args.output, args.tasks, repeats=args.repeats, profile=args.profile)
    print(canonical_json(result).decode(), flush=True)


if __name__ == "__main__":
    main()
