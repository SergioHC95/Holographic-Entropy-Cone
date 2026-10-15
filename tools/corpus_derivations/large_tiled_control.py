"""One existing L=24/25 proof: actual complete bounded-memory audit, no search.

Never allocate its multi-GiB full-table reference. Bind its already executed
source fresh audit, convert exactly, save/re-read the self-contained pipeline,
and execute all original cube checks with measured private-native peak RSS.
"""

from __future__ import annotations

import argparse
import hashlib
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

from hec.count_proofs import canonical_json, inequality_id, parse_json
from hec.reconstruction import ReconstructionProgram

from . import run as derivations
from .pipeline_import import NativeClosure, import_recipe
from .selected_corpus import check_audit
from .speedup_benchmark import guard, measure
from .synthesize import EXPECTED_TOTAL, decode_frame, geometry_only
from .tiled_audit_benchmark import execute


def control(source, observed_run, binary, output, task, *, working_bytes=256 * 1024**2):
    source, observed_run, binary, output = (Path(value).resolve() for value in (source, observed_run, binary, output))
    root = Path(__file__).resolve().parents[2]
    for protected in (source, observed_run, root):
        if output.is_relative_to(protected) or protected.is_relative_to(output):
            raise ValueError("new immutable control output must be outside all protected inputs")
    if output.exists() and any(output.iterdir()):
        raise ValueError("never overwrite an existing experiment")
    if (
        type(task) is not int
        or not 0 <= task < EXPECTED_TOTAL
        or type(working_bytes) is not int
        or not 1024 <= working_bytes <= 1024**3
    ):
        raise ValueError("one explicit existing task and bounded primary buffer budget required")
    binding = parse_json((source / "run-binding.json").read_bytes())
    if binding["total"] != EXPECTED_TOTAL or derivations.digest(source / "manifest.json") != binding["manifest_sha256"]:
        raise ValueError("original complete source identity changed")
    manifest = parse_json((source / "manifest.json").read_bytes())
    with closing(sqlite3.connect(f"file:{source / 'checkpoint.sqlite3'}?mode=ro", uri=True)) as db:
        db.execute("BEGIN")
        if (
            db.execute("SELECT COUNT(*) FROM results").fetchone()[0] != EXPECTED_TOTAL
            or db.execute("SELECT COUNT(*) FROM errors").fetchone()[0]
        ):
            raise ValueError("control source lacks complete error-free results")
        row = db.execute(
            "SELECT inequality_id,recipe_sha256,json_bytes,compressed FROM results WHERE task=?", (task,)
        ).fetchone()
        fresh = db.execute("SELECT report FROM fresh WHERE task=? AND ok=1", (task,)).fetchone()
    if row is None or fresh is None or row[0] != manifest[task]["inequality_id"] or row[2] > 32 * 1024**2:
        raise ValueError("control source/fresh audit is missing, changed or outside bounded input size")
    raw = decode_frame(row[3], row[2])
    document = parse_json(raw)
    p = geometry_only(document)
    if hashlib.sha256(raw).hexdigest() != row[1] or canonical_json(document) != raw or inequality_id(p) != row[0]:
        raise ValueError("control canonical definition or exact inequality changed")
    if not 24 <= p.L <= 25 or not p.G:
        raise ValueError("this is one explicit largest-dimension control, not a corpus runner")
    check_audit(parse_json(fresh[0].encode()), task, row[1], p)
    info = binding["binaries"]["closure"]
    closure = NativeClosure(info["path"], info["sha256"])
    native_sha = derivations.digest(binary)
    implementation = {
        str(path.relative_to(root)): derivations.digest(path)
        for folder in ("src/hec", "tools/corpus_derivations", "tools/derivation_pilot")
        for path in sorted((root / folder).rglob("*"))
        if path.is_file() and path.suffix in (".py", ".cpp")
    }
    start_sample = guard(observed_run)
    output.mkdir(parents=True, exist_ok=True)
    derivations.save_new(
        output / "binding.json",
        {
            "format": "hec-largest-tiled-control/1",
            "prepared_utc": datetime.now(UTC).isoformat(),
            "task": task,
            "source": str(source),
            "source_binding_sha256": derivations.digest(source / "run-binding.json"),
            "source_recipe_sha256": row[1],
            "source_fresh_receipt_sha256": hashlib.sha256(fresh[0].encode()).hexdigest(),
            "prototype_binary": {"path": str(binary), "sha256": native_sha},
            "implementation": implementation,
            "primary_buffer_budget_bytes": working_bytes,
            "rss_limit_bytes": 64 * 1024**3,
            "observed_live_cohort_at_start": start_sample,
            "new_corpus_workers_started": 0,
        },
    )
    target, conversion = import_recipe(document, closure_backend=closure)
    derivations.save_new(output / "proof.json", target)
    program = ReconstructionProgram((output / "proof.json").read_bytes(), closure_backend=closure)
    if (
        program.identity != conversion["target_proof_id"]
        or program.semantic_identity() != conversion["semantic_map_id"]
    ):
        raise ValueError("saved standalone control changed its exact identity or map semantics")
    program.materialize_seed()
    result, timing = measure(lambda: execute(program, binary, native_sha, working_bytes))
    audit = result["audit"]
    if (
        (audit["checked_vertices"], audit["checked_edges"]) != (p.vertices, p.L * (p.vertices // 2))
        or audit.get("working_layout") != "exact-tiles/1"
        or audit["output_row_storage_bytes"] > working_bytes
    ):
        raise ValueError("large control lacks actual complete bounded-memory cube verification")
    if derivations.digest(binary) != native_sha or any(
        derivations.digest(root / path) != sha for path, sha in implementation.items()
    ):
        raise ValueError("prototype or executing control code changed")
    report = {
        "format": "hec-largest-tiled-report/1",
        "reported_utc": datetime.now(UTC).isoformat(),
        "binding_sha256": derivations.digest(output / "binding.json"),
        "task": task,
        "inequality_id": row[0],
        "proof_id": program.identity,
        "conversion": conversion,
        "L": p.L,
        "G": p.G,
        "full_table_allocation_avoided_bytes": p.vertices * p.G * 8,
        "existing_source_receipt_is_not_new_acceptance": True,
        "actual_new_full_cube_audit_executed": True,
        "audit": audit,
        "native_peak_rss_bytes": result["native_peak_rss_bytes"],
        "timing": timing,
        "primary_buffer_budget_bytes": working_bytes,
        "newly_proved_inequalities": 0,
        "live_cohort_modified": False,
        "production_promoted": False,
        "full_goal_complete": False,
        "caveats": [
            "One existing proof, not whole-corpus/hosted-CI validation.",
            "No full-table baseline is allocated; avoided allocation is calculated, not measured peak RSS.",
            "Peak native RSS is measured separately from the historical start cohort sample.",
        ],
    }
    derivations.save_new(output / "report.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("source", "observed-run", "binary", "output"):
        parser.add_argument("--" + name, required=True, type=Path)
    parser.add_argument("--task", type=int, required=True)
    parser.add_argument("--working-bytes", type=int, default=256 * 1024**2)
    args = parser.parse_args()
    result = control(
        args.source, args.observed_run, args.binary, args.output, args.task, working_bytes=args.working_bytes
    )
    print(
        canonical_json(
            {"report": str(args.output / "report.json"), "actual_edges": result["audit"]["checked_edges"]}
        ).decode()
    )


if __name__ == "__main__":
    main()
