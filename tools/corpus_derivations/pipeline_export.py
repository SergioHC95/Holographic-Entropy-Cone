"""Complete-scope immutable unified-pipeline catalog and honest coverage report."""

from __future__ import annotations

import argparse
import fcntl
import io
import os
import sqlite3
import tempfile
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import zstandard as zstd

from hec.count_proofs import canonical_json
from hec.reconstruction import EXTENSION, PIPELINE

from . import pipeline_batch as batch
from . import run as derivations
from .package_results import FORMAT as CATALOG_FORMAT
from .package_results import RecipeCatalog, Shards
from .synthesize import EXPECTED_COUNTS, EXPECTED_TOTAL


def export(run, output, *, _expected_total=EXPECTED_TOTAL, _expected_counts=None, _shard_bytes=16 * 1024**2):
    run, output = Path(run).resolve(), Path(output).resolve()
    settings, manifest = batch.load_binding(run, _expected_total=_expected_total, _expected_counts=_expected_counts)
    batch.initialize(settings)
    lock = (run / "controller.lock").open("r")
    selected, db, temporary = None, None, None
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        selected = batch.open_selection(settings, _expected_total=_expected_total, _expected_counts=_expected_counts)
        db = sqlite3.connect(f"file:{run / 'checkpoint.sqlite3'}?mode=ro", uri=True)
        db.execute("BEGIN")
        if db.execute("SELECT COUNT(*) FROM converted").fetchone()[0] != _expected_total:
            raise ValueError("unified export requires all conversion tasks, not a subset")
        if db.execute("SELECT COUNT(*) FROM errors").fetchone()[0]:
            raise ValueError("unresolved conversion failures prevent export")
        for protected in (selected.source.root, selected.root):
            if output.is_relative_to(protected) or protected.is_relative_to(output):
                raise ValueError("unified export must not modify original source/synthesis artifacts")
        if output == run or run.is_relative_to(output):
            raise ValueError("unified export must be a new directory, not its run or an ancestor")
        if output.exists() and any(output.iterdir()):
            raise ValueError("choose an empty new export; never overwrite immutable proof objects")
        output.mkdir(parents=True, exist_ok=True)
        shards = Shards(output, _shard_bytes)
        descriptor, name = tempfile.mkstemp(prefix=".pipeline-provenance-", dir=output)
        temporary = Path(name)
        statuses, variants, compatible, edges = Counter(), 0, 0, 0
        chosen_bytes, baseline_bytes, candidate_bytes, frames, old_selected_bytes = 0, 0, 0, 0, 0
        rows = db.execute(
            "SELECT task,inequality_id,recipe_sha256,proof_id,semantic_map_id,"
            "json_bytes,compressed,receipt FROM converted ORDER BY task"
        )
        with os.fdopen(descriptor, "wb") as stream:
            with zstd.ZstdCompressor(level=9, write_checksum=True).stream_writer(stream, closefd=False) as provenance:
                for pair, row in zip(batch.inputs(selected), rows, strict=True):
                    expected = batch.input_binding(pair)
                    task, iid, sha, identity, semantic, size, data, saved = row
                    if expected != manifest[task]:
                        raise ValueError("selected conversion input differs from the immutable manifest")
                    _, receipt, origin = batch.validate_result(*row, expected)
                    provenance.write(canonical_json(receipt) + b"\n")
                    shards.append(
                        {
                            "task": task,
                            "inequality_id": iid,
                            "recipe_sha256": sha,
                            "origin": origin,
                            "json_bytes": size,
                        },
                        data,
                    )
                    statuses[receipt["status"]] += 1
                    variants += receipt["variants_converted"]
                    compatible += sum(
                        value["equivalence"]["checked_compatible_vertices"] for value in receipt["variants"]
                    )
                    edges += receipt["chosen_conversion"]["source_mathematical_audit"]["checked_edges"]
                    chosen_bytes += size
                    baseline_bytes += receipt["baseline_pipeline_json_bytes"]
                    candidate_bytes += receipt["candidate_pipeline_json_bytes"]
                    old_selected_bytes += len(pair[0].raw)
                    frames += len(data)
            stream.flush()
            os.fsync(stream.fileno())
        shards.seal()
        if len(shards.entries) != _expected_total:
            raise ValueError("unified catalog missed one or more source identities")
        provenance_sha = derivations.digest(temporary)
        provenance_path = output / f"{provenance_sha}.conversion-provenance.jsonl.zst"
        os.link(temporary, provenance_path)
        temporary.unlink()
        temporary = None
        with provenance_path.open("rb") as packed:
            with zstd.ZstdDecompressor().stream_reader(packed, read_across_frames=True) as decoded:
                with io.BufferedReader(decoded) as lines:
                    for (saved,) in db.execute("SELECT receipt FROM converted ORDER BY task"):
                        if lines.readline(16 * 1024**2) != saved.encode() + b"\n":
                            raise ValueError("sealed conversion provenance differs from its complete checkpoint")
                    if lines.read(1):
                        raise ValueError("sealed conversion provenance contains unindexed trailing records")
        scope = {
            "proofs": _expected_total,
            "populations": EXPECTED_COUNTS if _expected_counts is None else _expected_counts,
            "definition_profile": PIPELINE,
            "extension": EXTENSION,
            "conversion_binding_sha256": derivations.digest(run / "run-binding.json"),
            "source_selected_records_sha256": settings["selected_records_sha256"],
            "conversion_provenance_sha256": provenance_sha,
            "conversion_provenance_bytes": provenance_path.stat().st_size,
            "production_format_promoted": False,
        }
        derivations.save_new(
            output / "recipes.json",
            {"format": CATALOG_FORMAT, "scope": scope, "entries": shards.entries, "shards": shards.shards},
        )
        reader = RecipeCatalog(output / "recipes.json")
        for at in range(len(reader)):
            document = reader[at]
            if document["function"].get("kind") != PIPELINE:
                raise ValueError("unified catalog contains a non-pipeline fallback")
        retained = statuses.get("retained_strictly_smaller_pipeline_alternative", 0)
        report = {
            "format": "hec-unified-pipeline-report/1",
            "reported_utc": datetime.now(UTC).isoformat(),
            "scope": scope,
            "exact_converted_inequality_identities": _expected_total,
            "converted_variant_definitions": variants,
            "compatible_vertices_compared_across_variants": compatible,
            "selected_maps_with_executed_source_free_full_cube_audits": _expected_total,
            "selected_original_cube_edges_covered_by_executed_evidence": edges,
            "new_exhaustive_original_cube_audits_executed_by_conversion": 0,
            "mathematical_justification": (
                "Complete exact compatible-value equivalence plus identical certified full-cube extension; "
                "each chosen map retains its own executed source-free full-cube audit."
            ),
            "synthesis_dispositions_before_unification": selected.statuses,
            "unified_selection_dispositions": dict(statuses),
            "retained_strictly_smaller_pipeline_alternatives": retained,
            "baseline_source_pipeline_json_bytes": baseline_bytes,
            "final_chosen_pipeline_json_bytes": chosen_bytes,
            "same_profile_synthesis_json_bytes_saved": baseline_bytes - chosen_bytes,
            "old_selected_definition_json_bytes": old_selected_bytes,
            "converted_old_selection_pipeline_json_bytes": candidate_bytes,
            "pure_encoding_json_bytes_delta": candidate_bytes - old_selected_bytes,
            "final_frame_bytes": frames,
            "catalog_bytes": (output / "recipes.json").stat().st_size,
            "shards": len(shards.shards),
            "shard_bytes": sum(item["bytes"] for item in shards.shards.values()),
            "provenance_bytes": provenance_path.stat().st_size,
            "packaging_integrity_checked_frames": len(reader),
            "processing_worker_limit": derivations.worker_count(settings),
            "rss_limit_bytes": 64 * 1024**3,
            "original_artifacts_overwritten": False,
            "cpu_totals": "not collected; overlapping per-case wall times are not aggregate CPU time",
            "additional_synthesis_needed": retained == 0,
            "full_goal_complete": False,
            "remaining_goal_work": (
                "Independent final scope, mathematical assurance and integration review; further synthesis "
                "if no genuinely smaller alternative survives same-profile comparison."
            ),
        }
        derivations.save_new(output / "report.json", report)
        return report
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)  # Only this function's own unsealed temporary file.
        if db is not None:
            db.close()
        if selected is not None:
            selected.close()
        lock.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(canonical_json(export(args.run, args.output)).decode(), flush=True)


if __name__ == "__main__":
    main()
