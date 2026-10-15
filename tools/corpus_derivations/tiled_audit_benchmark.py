"""Bound exact full-audit memory/CPU tradeoffs, never promote a live backend.

Both arms execute all original cube checks and query differentials on the same
warm reconstructed seed. wait4 records each private native child's actual peak
RSS, separately from parent/live-cohort samples; no peak sums masquerade as a
live sample. This benchmark is deliberately Unix-only like the corpus runner.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import subprocess
import sys
from datetime import UTC, datetime
from functools import partial
from pathlib import Path

from hec.count_proofs import canonical_json, parse_json
from hec.reconstruction import ReconstructionProgram

from . import run as derivations
from .pipeline_import import NativeClosure, NativePipelineAuditor
from .speedup_benchmark import guard, measure


class MeasuredAuditor(NativePipelineAuditor):
    def __init__(self, binary, sha256, working_bytes=None):
        super().__init__(binary, sha256)
        self.working_bytes, self.peak_rss_bytes, self.exit_code = working_bytes, 0, None

    def verify(self, *args):
        if self.process is None and self.working_bytes is not None:
            self.process = subprocess.Popen(
                [str(self.binary), "--working-bytes", str(self.working_bytes)],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
            )
        return super().verify(*args)

    def close(self):
        if self.process is not None:
            process = self.process
            process.stdin.close()  # Every request finished before close; this is not a solver timeout.
            pid, status, usage = os.wait4(process.pid, 0)
            if pid != process.pid:
                raise ValueError("private native audit child identity changed at reap")
            self.exit_code = process.returncode = os.waitstatus_to_exitcode(status)
            self.peak_rss_bytes = int(usage.ru_maxrss) * (1 if sys.platform == "darwin" else 1024)
            process.stdout.close()
            self.process = None


def execute(program, binary, sha256, budget):
    auditor = MeasuredAuditor(binary, sha256, budget)
    try:
        result = program.audit(auditor)  # Actual full cube, never a stored receipt.
    finally:
        auditor.close()
    if auditor.exit_code != 0:
        raise ValueError("private exact audit process did not exit successfully")
    return {"audit": result, "native_peak_rss_bytes": auditor.peak_rss_bytes}


def benchmark(controls, observed_run, binary, output, *, working_bytes=256 * 1024**2, repeats=2):
    controls, observed_run, binary, output = (
        Path(value).resolve() for value in (controls, observed_run, binary, output)
    )
    checkout = Path(__file__).resolve().parents[2]
    if not hasattr(os, "wait4") or sys.platform not in ("darwin", "linux"):
        raise ValueError("exact per-child RSS controls require supported Unix wait4 accounting")
    if (
        type(working_bytes) is not int
        or not 1024 <= working_bytes <= 1024**3
        or type(repeats) is not int
        or not 1 <= repeats <= 3
    ):
        raise ValueError("bounded 1 KiB--1 GiB tile budget and one--three paired repeats required")
    for protected in (controls, observed_run, checkout):
        if output.is_relative_to(protected) or protected.is_relative_to(output):
            raise ValueError("new immutable experiment output must be outside protected inputs/run/worktree")
    if output.exists() and any(output.iterdir()):
        raise ValueError("never overwrite completed experiment results")
    previous = parse_json((controls / "report.json").read_bytes())
    if previous.get("format") != "hec-bounded-pipeline-speedup-report/1" or not 1 <= len(previous["cases"]) <= 8:
        raise ValueError("bounded hash-bound saved pipeline controls required")
    binding = parse_json((observed_run / "run-binding.json").read_bytes())
    info = binding["binaries"]["wide"]
    closure_info = binding["binaries"]["closure"]
    for item in (info, closure_info):
        if derivations.digest(item["path"]) != item["sha256"]:
            raise ValueError("bound independent reference/closure binary changed")
    if binary.is_symlink() or not binary.is_file():
        raise ValueError("new prototype binary must be an explicit regular file")
    sha = derivations.digest(binary)
    inputs, documents = {str(controls / "report.json"): derivations.digest(controls / "report.json")}, []
    for case in previous["cases"]:
        path = controls / f"{case['task']}.pipeline.json"
        document = parse_json(path.read_bytes())
        if hashlib.sha256(canonical_json(document)).hexdigest() != case["target_definition_sha256"]:
            raise ValueError("saved canonical control definition changed")
        if case["L"] > 22 or (1 << case["L"]) * case["G"] * 8 > 1024**3:
            raise ValueError("this comparison never starts an unbounded full-table control")
        inputs[str(path)] = derivations.digest(path)
        documents.append((case, document))
    implementation = {
        str(path.relative_to(checkout)): derivations.digest(path)
        for folder in ("src/hec", "tools/corpus_derivations", "tools/derivation_pilot")
        for path in sorted((checkout / folder).rglob("*"))
        if path.is_file() and path.suffix in (".py", ".cpp")
    }
    primary_source = checkout / "tools/verify_reconstruction.cpp"
    if primary_source.is_file():
        implementation[str(primary_source.relative_to(checkout))] = derivations.digest(primary_source)
    samples, cases, executed_edges = [guard(observed_run)], [], 0
    output.mkdir(parents=True, exist_ok=True)
    derivations.save_new(
        output / "binding.json",
        {
            "format": "hec-tiled-audit-control/1",
            "prepared_utc": datetime.now(UTC).isoformat(),
            "inputs": inputs,
            "implementation": implementation,
            "observed_run": str(observed_run),
            "observed_binding_sha256": derivations.digest(observed_run / "run-binding.json"),
            "reference_binary": info,
            "closure_binary": closure_info,
            "prototype_binary": {"path": str(binary), "sha256": sha},
            "primary_output_buffer_budget_bytes": working_bytes,
            "paired_repeats": repeats,
            "rss_limit_bytes": 64 * 1024**3,
            "new_corpus_workers_started": 0,
            "live_cohort_modified": False,
        },
    )
    closure = NativeClosure(closure_info["path"], closure_info["sha256"])
    for case, document in documents:
        program = ReconstructionProgram(document, closure_backend=closure)
        program.materialize_seed()  # Warm seed preparation is OUTSIDE the measured native-request stage.
        if (
            program.identity != case["conversion"]["target_proof_id"]
            or program.semantic_identity() != case["semantic_map_id"]
        ):
            raise ValueError("saved control proof or exact map semantics changed")
        pairs = []
        for repeat in range(repeats):
            arms = {}
            for name in ("full", "bounded") if repeat % 2 == 0 else ("bounded", "full"):
                samples.append(guard(observed_run))
                action = partial(
                    execute,
                    program,
                    info["path"] if name == "full" else binary,
                    info["sha256"] if name == "full" else sha,
                    None if name == "full" else working_bytes,
                )
                measured, timing = measure(action)
                audit = measured["audit"]
                expected = {
                    "ok": True,
                    "scope": "original-cube-all-edges",
                    "proof_id": program.identity,
                    "inequality_id": case["inequality_id"],
                    "semantic_map_id": case["semantic_map_id"],
                    "checked_vertices": 1 << case["L"],
                    "checked_edges": case["L"] * ((1 << case["L"]) // 2),
                    "source_tables_read": False,
                }
                if any(
                    type(audit.get(key)) is not type(value) or audit[key] != value for key, value in expected.items()
                ):
                    raise ValueError("actual native audit lost exact identities or complete coverage")
                if name == "bounded" and audit["output_row_storage_bytes"] > working_bytes:
                    raise ValueError("prototype exceeded primary output-buffer budget")
                arms[name] = {**measured, "timing": timing}
                executed_edges += audit["checked_edges"]
                samples.append(guard(observed_run))
            pairs.append({"repeat": repeat, "arms": arms})
        result = {
            "task": case["task"],
            "L": case["L"],
            "G": case["G"],
            "primitive": case["seed_primitive"],
            "pairs": pairs,
        }
        derivations.save_new(output / f"{case['task']}.result.json", result)
        cases.append(result)
    if derivations.digest(binary) != sha or any(
        derivations.digest(path) != expected for path, expected in inputs.items()
    ):
        raise ValueError("bound prototype or saved control input changed")
    if any(derivations.digest(checkout / path) != expected for path, expected in implementation.items()):
        raise ValueError("executing experiment implementation changed")
    report = {
        "format": "hec-tiled-audit-report/1",
        "reported_utc": datetime.now(UTC).isoformat(),
        "binding_sha256": derivations.digest(output / "binding.json"),
        "cases": cases,
        "actual_original_cube_edges_including_timing_repeats": executed_edges,
        "resource_samples": samples,
        "primary_output_buffer_budget_bytes": working_bytes,
        "live_cohort_modified": False,
        "production_promoted": False,
        "full_goal_complete": False,
        "caveats": [
            "Bounded hand-picked controls, not whole-corpus or hosted-CI validation.",
            "Every arm executes actual complete cube audits plus exact query differentials, not stored acceptance.",
            "Tile storage excludes the seed, domain index, protocol buffers and parent; "
            "child peak RSS is separately measured.",
            "CPU is native-request stage on a warm seed, including reaped child; wall time includes host contention.",
            "Repeated reconstruction for lower memory need not be a CPU speedup; no live backend is replaced here.",
        ],
    }
    derivations.save_new(output / "report.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("controls", "observed-run", "binary", "output"):
        parser.add_argument("--" + name, required=True, type=Path)
    parser.add_argument("--working-bytes", type=int, default=256 * 1024**2)
    parser.add_argument("--repeats", type=int, default=2)
    args = parser.parse_args()
    report = benchmark(
        args.controls,
        args.observed_run,
        args.binary,
        args.output,
        working_bytes=args.working_bytes,
        repeats=args.repeats,
    )
    print(canonical_json({"report": str(args.output / "report.json"), "cases": len(report["cases"])}).decode())


if __name__ == "__main__":
    main()
