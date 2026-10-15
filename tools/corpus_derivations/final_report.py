"""Reconcile final quantitative results without rerunning any mathematical audit."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from collections import Counter
from contextlib import closing
from pathlib import Path

from hec.count_proofs import parse_json

from . import run as d
from .repository_acceptance import bound, equal
from .synthesize import decode_frame


def build(locator, repo):
    p = json.loads(Path(locator).read_bytes())  # Operational locator can contain historical float timings.
    repo = Path(repo).resolve()
    source, synth, conversion, audit = (
        Path(p[key]) for key in ("source_run", "synthesis_run", "unified_pipeline_run", "full_staged_audit_root")
    )
    export_path = Path(p["unified_export"]) / "report.json"
    research_path = Path(p["research_export_report"])
    review_path = Path(p["full_staged_audit_acceptance_review"])
    bound(review_path, p["full_staged_audit_acceptance_review_sha256"])
    review, export, research = (parse_json(x.read_bytes()) for x in (review_path, export_path, research_path))
    equal(review["mathematical_promotion_precondition_passed"], True, "complete review")
    equal(review["proofs"], 84690, "whole corpus")
    source_binding = parse_json((source / "run-binding.json").read_bytes())
    bound(source / "manifest.json", source_binding["manifest_sha256"])
    manifest = parse_json((source / "manifest.json").read_bytes())
    groups = {x["task"]: (x["group"] if x["n"] == 6 else "small-n") for x in manifest}
    identities = {x["task"]: x["inequality_id"] for x in manifest}
    populations = Counter(groups.values())
    by_group = {
        key: {
            "proofs": 0,
            "initial_definition_json_bytes": 0,
            "phase_one_json_bytes": 0,
            "final_source_pipeline_json_bytes": 0,
            "final_selected_pipeline_json_bytes": 0,
            "final_compressed_frame_bytes": 0,
            "retained_simpler_maps": 0,
        }
        for key in populations
    }

    def connect(root):
        return closing(sqlite3.connect(f"file:{root / 'checkpoint.sqlite3'}?mode=ro", uri=True))

    with connect(source) as db:
        source_counts = {
            "results": db.execute("SELECT COUNT(*) FROM results").fetchone()[0],
            "fresh_successful": db.execute("SELECT COUNT(*) FROM fresh WHERE ok=1").fetchone()[0],
            "errors": db.execute("SELECT COUNT(*) FROM errors").fetchone()[0],
        }
        for task, iid, size, original in db.execute(
            "SELECT task,inequality_id,json_bytes,source_json_bytes FROM results"
        ):
            equal(iid, identities[task], "source identity")
            group = by_group[groups[task]]
            group["initial_definition_json_bytes"] += original
            group["phase_one_json_bytes"] += size
    kinds, retained, statuses = Counter(), set(), Counter()
    with connect(conversion) as db:
        equal(db.execute("SELECT COUNT(*) FROM errors").fetchone()[0], 0, "conversion errors")
        for task, iid, sha, size, packed, baseline, status in db.execute(
            "SELECT task,inequality_id,recipe_sha256,json_bytes,compressed,"
            "json_extract(receipt,'$.baseline_pipeline_json_bytes'),json_extract(receipt,'$.status') "
            "FROM converted ORDER BY task"
        ):
            equal(iid, identities[task], "final identity")
            raw = decode_frame(packed, size)
            equal(hashlib.sha256(raw).hexdigest(), sha, "final definition bytes")
            document = parse_json(raw)
            equal(document["function"]["kind"], "compatible-reconstruction-pipeline/1", "one final language")
            kinds[document["function"]["seed"]["kind"]] += 1
            group = by_group[groups[task]]
            group["proofs"] += 1
            group["final_source_pipeline_json_bytes"] += baseline
            group["final_selected_pipeline_json_bytes"] += size
            group["final_compressed_frame_bytes"] += len(packed)
            statuses[status] += 1
            if status == "retained_strictly_smaller_pipeline_alternative":
                retained.add(task)
                group["retained_simpler_maps"] += 1
    with connect(synth) as db:
        synth_counts = dict(db.execute("SELECT status,COUNT(*) FROM attempts GROUP BY status"))
        synth_fresh = db.execute("SELECT COUNT(*) FROM fresh WHERE ok=1").fetchone()[0]
        equal(db.execute("SELECT COUNT(*) FROM errors").fetchone()[0], 0, "synthesis errors")
        incomplete = [
            {"task": task, "inequality_id": iid, "source_proof_remains_valid": True}
            for task, iid in db.execute(
                "SELECT task,inequality_id FROM attempts "
                "WHERE status='incomplete_synthesis_budget_not_a_proof' ORDER BY task"
            )
        ]
        changed_cells = 0
        for task, raw in db.execute(
            "SELECT task,report FROM attempts WHERE status='accepted_strictly_smaller_alternative'"
        ):
            if task in retained:
                changed_cells += parse_json(raw.encode())["synthesis"]["changed_cells"]
    seed_bits, full_bits, dimensions = Counter(), Counter(), Counter()
    with connect(audit) as db:
        equal(db.execute("SELECT COUNT(*) FROM audited").fetchone()[0], 84690, "actual new audit rows")
        equal(db.execute("SELECT COUNT(*) FROM errors").fetchone()[0], 0, "actual audit errors")
        for seed, full, L in db.execute(
            "SELECT json_extract(report,'$.audit.seed_scale'),json_extract(report,'$.audit.clearing_scale'),"
            "json_extract(report,'$.audit.L') FROM audited"
        ):
            seed_bits[str(int(seed).bit_length())] += 1
            full_bits[str(int(full).bit_length())] += 1
            dimensions[str(L)] += 1
    equal(source_counts, {"results": 84690, "fresh_successful": 84690, "errors": 0}, "all source passes")
    equal(sum(kinds.values()), 84690, "all final definitions")
    for field, expected in (
        ("initial_definition_json_bytes", research["initial_source_definition_json_bytes"]),
        ("phase_one_json_bytes", research["phase_one_selected_json_bytes"]),
        ("final_source_pipeline_json_bytes", export["baseline_source_pipeline_json_bytes"]),
        ("final_selected_pipeline_json_bytes", export["final_chosen_pipeline_json_bytes"]),
        ("final_compressed_frame_bytes", export["final_frame_bytes"]),
    ):
        equal(sum(x[field] for x in by_group.values()), expected, "cost reconciliation " + field)
    job = Path(p["local_cutover_job"])
    assets = json.loads((job / "publication-assets.json").read_bytes())
    old = parse_json((job / "originals/originals-index.json").read_bytes())
    raw76 = parse_json(
        Path("/Users/sergio/.hec/contraction-migration-exact76-fast-20261013/migration.json").read_bytes()
    )
    original76_bytes = sum(x["source_bytes"] for x in raw76["receipts"])
    report = {
        "format": "hec-final-contraction-corpus-results/1",
        "scope": dict(populations),
        "proofs": 84690,
        "cutover_commit": p["local_cutover_commit"],
        "source_and_fresh_counts": source_counts,
        "phase_one_winners": research["phase_one_winners"],
        "phase_one_method_statuses": research["phase_one_method_statuses"],
        "synthesis_dispositions": synth_counts,
        "independently_fresh_audited_old_profile_alternatives": synth_fresh,
        "final_selection_dispositions": dict(statuses),
        "final_retained_simpler_maps": len(retained),
        "changed_compatible_cells_in_final_retained_maps": changed_cells,
        "budget_limited_synthesis": incomplete,
        "final_seed_primitives": dict(kinds),
        "by_population": by_group,
        "final_seed_denominator_bit_lengths": dict(seed_bits),
        "final_clearing_scale_bit_lengths": dict(full_bits),
        "source_dimensions": dict(dimensions),
        "actual_new_staged_full_cube_audits": 84690,
        "actual_checked_source_vertices": review["actual_prior_audit_vertices_reconciled"],
        "actual_checked_weighted_cube_edges": review["actual_prior_audit_edges_reconciled"],
        "independent_review_frames": review["checked_stored_frames"],
        "conversion_and_review_new_cube_audits": 0,
        "costs": {
            key: export[key]
            for key in (
                "baseline_source_pipeline_json_bytes",
                "final_chosen_pipeline_json_bytes",
                "same_profile_synthesis_json_bytes_saved",
                "old_selected_definition_json_bytes",
                "converted_old_selection_pipeline_json_bytes",
                "pure_encoding_json_bytes_delta",
                "final_frame_bytes",
                "catalog_bytes",
                "provenance_bytes",
            )
        },
        "pre_unified_compressed_frames": research["final_selected_frame_bytes"],
        "old_active_proof_payload_bytes": sum(x.get("payload_bytes", 0) for x in old["entries"]),
        "new_n6_lfs_proof_payload_bytes": sum(x["bytes"] for x in assets["assets"] if x["path"].startswith("data/")),
        "new_large_objects_pending_authorized_upload": len(assets["assets"]),
        "new_large_payload_bytes_pending_authorized_upload": sum(x["bytes"] for x in assets["assets"]),
        "historical_exact76_enumerated_json_bytes": original76_bytes,
        "historical_exact76_scope_warning": (
            "76 input archives only; do not compare this partial-scope total as the baseline for all 84690 proofs."
        ),
        "ordinary_git_catalog_and_inequality_bytes": sum(
            x.stat().st_size
            for x in (repo / "data").glob("n=*/*.json")
            if x.name in ("proofs.json", "inequalities.json")
        ),
        "ordinary_git_small_proof_payload_bytes": sum(
            x.stat().st_size
            for x in (repo / "data").glob("n=*/proof-shards/*.proofpack")
            if x.parent.parent.name != "n=6"
        ),
        "cpu_totals": (
            "Whole-campaign aggregate CPU was not collected. "
            "Overlapping case walls and native microseconds are not aggregate CPU."
        ),
        "construction_method": (
            "Exact tight-component/interval smoothing with unchanged two-sweep and 50000000 charged-work budget; "
            "exact winner replay, full cube acceptance and separate source-free fresh checks."
        ),
        "performance_scope": (
            "Validated case-specific stage gains, not a universal or whole-campaign speedup. "
            "Bounded-memory tiling trades extra CPU for memory on large maps."
        ),
        "originals_preserved": True,
        "facet_rank_assertions_inherited": False,
        "git_lfs_or_billing_mutated": False,
        "remote_ci_run_or_payload_upload_claimed": False,
        "evidence": {
            str(path): d.digest(path)
            for path in (
                export_path,
                research_path,
                review_path,
                audit / "report.json",
                audit / "run-binding.json",
                job / "primary-api-integration.json",
            )
        },
        "recovery_and_upload_manifest": str(job / "publication-assets.json"),
    }
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--locator", required=True, type=Path)
    parser.add_argument("--repo", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = build(args.locator, args.repo)
    d.save_new(args.output, result)
    print(
        json.dumps(
            {
                "report": str(args.output),
                "proofs": result["proofs"],
                "final_seed_primitives": result["final_seed_primitives"],
                "by_population": result["by_population"],
            }
        )
    )


if __name__ == "__main__":
    main()
