"""Reframe a COMPLETE unified export into repository-layout staging, not promotion.

No new mathematical acceptance, Git/LFS operation, facet claim, replacement of
old artifacts, or repository reader switch. A separate actual full-data audit
of the staged unified catalogue is mandatory before promotion.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import os
import shutil
import sqlite3
from collections import Counter
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

from hec.count_proofs import canonical_json, inequality_id, parse_json, proof_geometry, proof_id
from hec.inequality_records import FORMAT as INEQUALITIES_FORMAT
from hec.inequality_records import InequalityCatalog
from hec.proof_store import CATALOG_FORMAT
from hec.reconstruction import EXTENSION, PIPELINE
from hec.reconstruction_store import ReconstructionCatalog

from . import run as derivations
from .continue_pipeline import idle
from .package_results import RecipeCatalog
from .synthesize import EXPECTED_COUNTS, EXPECTED_TOTAL


class Frames:
    def __init__(self, root, target):
        self.root, self.target = root, target
        (root / "proof-shards").mkdir(parents=True)
        self.data, self.pending, self.entries, self.shards = bytearray(), [], [], {}

    def append(self, iid, pid, frame):
        if self.data and len(self.data) + len(frame) > self.target:
            self.seal()
        self.pending.append({"inequality_id": iid, "proof_id": pid, "offset": len(self.data), "bytes": len(frame)})
        self.data.extend(frame)

    def seal(self):
        if not self.data:
            return
        key = hashlib.sha256(self.data).hexdigest()
        path = self.root / "proof-shards" / f"{key}.proofpack"
        with path.open("xb") as stream:
            stream.write(self.data)
            stream.flush()
            os.fsync(stream.fileno())
        self.entries.extend({**entry, "shard": key} for entry in self.pending)
        self.shards[key] = {"bytes": len(self.data)}
        self.data.clear()
        self.pending.clear()


def ready(run, export, *, expected_total, expected_counts):
    binding = parse_json((run / "run-binding.json").read_bytes())
    report = parse_json((export / "report.json").read_bytes())
    reader = RecipeCatalog(export / "recipes.json")
    if (
        binding.get("format") != "hec-unified-pipeline-run/1"
        or binding.get("total") != expected_total
        or binding.get("scope_counts") != expected_counts
        or binding.get("profile") != PIPELINE
        or binding.get("extension") != EXTENSION
        or binding.get("rss_limit_bytes") != 64 * 1024**3
        or report.get("format") != "hec-unified-pipeline-report/1"
        or report.get("exact_converted_inequality_identities") != expected_total
        or report.get("packaging_integrity_checked_frames") != expected_total
        or report.get("new_exhaustive_original_cube_audits_executed_by_conversion") != 0
        or reader.scope != report.get("scope")
        or reader.scope.get("proofs") != expected_total
        or reader.scope.get("populations") != expected_counts
        or reader.scope.get("definition_profile") != PIPELINE
        or reader.scope.get("extension") != EXTENSION
        or reader.scope.get("production_format_promoted") is not False
        or reader.scope.get("conversion_binding_sha256") != derivations.digest(run / "run-binding.json")
        or reader.scope.get("source_selected_records_sha256") != binding.get("selected_records_sha256")
    ):
        raise ValueError("repository staging requires a complete bound unified export, never a subset")
    manifest_path = run / "manifest.json"
    if derivations.digest(manifest_path) != binding["manifest_sha256"]:
        raise ValueError("immutable complete conversion manifest changed")
    manifest = parse_json(manifest_path.read_bytes())
    if len(manifest) != expected_total or [entry["task"] for entry in manifest] != list(range(expected_total)):
        raise ValueError("conversion manifest has incomplete task coverage")
    for relative, sha in binding["implementation"].items():
        if derivations.digest(run / "implementation" / relative) != sha:
            raise ValueError("frozen conversion implementation changed")
    source = Path(binding["source"])
    source_binding = parse_json((source / "run-binding.json").read_bytes())
    if (
        derivations.digest(source / "run-binding.json") != binding["source_binding_sha256"]
        or derivations.digest(Path(binding["synthesis"]) / "run-binding.json") != binding["synthesis_binding_sha256"]
        or derivations.digest(source / "manifest.json") != source_binding["manifest_sha256"]
    ):
        raise ValueError("original source/synthesis identity changed")
    source_manifest = parse_json((source / "manifest.json").read_bytes())
    populations = Counter(item["group"] if item["n"] == 6 else "small-n" for item in source_manifest)
    if len(source_manifest) != expected_total or dict(populations) != expected_counts:
        raise ValueError("source manifest population differs from the complete export")
    provenance = export / f"{reader.scope['conversion_provenance_sha256']}.conversion-provenance.jsonl.zst"
    if (
        provenance.is_symlink()
        or provenance.stat().st_size != reader.scope["conversion_provenance_bytes"]
        or derivations.digest(provenance) != reader.scope["conversion_provenance_sha256"]
    ):
        raise ValueError("complete conversion provenance object changed")
    return binding, reader, source_manifest, provenance


def stage(run, export, output, *, _expected_total=EXPECTED_TOTAL, _expected_counts=None, _shard_bytes=16 * 1024**2):
    run, export, output = (Path(value).resolve() for value in (run, export, output))
    counts = EXPECTED_COUNTS if _expected_counts is None else _expected_counts
    if type(_shard_bytes) is not int or _shard_bytes < 1:
        raise ValueError("positive repository shard target required")
    if not idle(run, set()):
        raise BlockingIOError("conversion controller/native child or exporter remains live; no staging")
    with (run / "controller.lock").open("r") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        binding, reader, source_manifest, provenance = ready(
            run, export, expected_total=_expected_total, expected_counts=counts
        )
        for protected in (
            run,
            export,
            Path(binding["source"]),
            Path(binding["synthesis"]),
            Path(__file__).resolve().parents[2],
        ):
            if output.is_relative_to(protected) or protected.is_relative_to(output):
                raise ValueError("repository staging must be outside all original/run/export/worktree paths")
        if output.exists() and any(output.iterdir()):
            raise ValueError("new immutable repository staging only; never overwrite prior data")
        with closing(sqlite3.connect(f"file:{run / 'checkpoint.sqlite3'}?mode=ro", uri=True)) as db:
            db.execute("BEGIN")
            if (
                db.execute("SELECT COUNT(*) FROM converted").fetchone()[0] != _expected_total
                or db.execute("SELECT COUNT(*) FROM errors").fetchone()[0]
            ):
                raise ValueError("partial/error conversion ledger cannot stage repository artifacts")
            rows = list(
                db.execute(
                    "SELECT task,inequality_id,recipe_sha256,proof_id,semantic_map_id,json_bytes "
                    "FROM converted ORDER BY task"
                )
            )
            for task, (entry, row) in enumerate(zip(reader.entries, rows, strict=True)):
                if (entry["task"], entry["inequality_id"], entry["recipe_sha256"], entry["json_bytes"]) != (
                    task,
                    row[1],
                    row[2],
                    row[5],
                ) or row[0] != task:
                    raise ValueError("export catalog differs from complete immutable conversion results")
                if source_manifest[task]["task"] != task or source_manifest[task]["inequality_id"] != row[1]:
                    raise ValueError("staging changed original ordered source identities")
        # No output directory is created until ALL complete-scope gates pass.
        output.mkdir(parents=True, exist_ok=True)
        frames, inequalities, bytes_copied, by_group = {}, {}, 0, Counter()
        for at, entry in enumerate(reader.entries):
            document, frame = reader.read_record(at)  # Verify/copy the SAME bytes, not a second file read.
            if document.get("function", {}).get("kind") != PIPELINE:
                raise ValueError("repository stage contains a non-unified fallback")
            p, identity = proof_geometry(document), proof_id(document)
            if p.n != source_manifest[at]["n"] or identity != rows[at][3]:
                raise ValueError("staged definition changed party count or canonical proof identity")
            if len(frame) != entry["bytes"]:
                raise ValueError("export frame changed during staging")
            if p.n not in frames:
                directory = output / "data" / f"n={p.n}"
                frames[p.n] = Frames(directory, _shard_bytes)
                inequalities[p.n] = {}
            iid = inequality_id(p)
            frames[p.n].append(iid, identity, frame)
            inequalities[p.n][iid] = {"id": iid, **p.inequality(), "proof_ids": [identity]}
            bytes_copied += len(frame)
            by_group[source_manifest[at]["group"] if p.n == 6 else "small-n"] += 1
        artifact_counts = {}
        for n, writer in frames.items():
            writer.seal()
            directory = output / "data" / f"n={n}"
            derivations.save_new(
                directory / "proofs.json",
                {"format": CATALOG_FORMAT, "entries": writer.entries, "shards": writer.shards},
            )
            derivations.save_new(
                directory / "inequalities.json",
                {"format": INEQUALITIES_FORMAT, "entries": [inequalities[n][key] for key in sorted(inequalities[n])]},
            )
            catalog = ReconstructionCatalog(directory / "proofs.json")
            InequalityCatalog(directory / "inequalities.json").check_bindings(catalog)
            # Verify every reframed record, not merely the first or an index.
            for doc in catalog:
                if doc["inequality"]["n"] != n:
                    raise ValueError("mixed-party staged proof catalogue")
            artifact_counts[str(n)] = {
                "proofs": len(catalog),
                "inequalities": len(inequalities[n]),
                "shards": len(writer.shards),
            }
        if sum(value["proofs"] for value in artifact_counts.values()) != _expected_total or dict(by_group) != counts:
            raise ValueError("repository staging lost complete corpus coverage")
        evidence = output / "conversion-provenance"
        evidence.mkdir()
        shutil.copy2(provenance, evidence / provenance.name)
        report = {
            "format": "hec-unified-repository-stage/1",
            "reported_utc": datetime.now(UTC).isoformat(),
            "source_run": str(run),
            "source_export": str(export),
            "source_export_report_sha256": derivations.digest(export / "report.json"),
            "conversion_binding_sha256": derivations.digest(run / "run-binding.json"),
            "proofs": _expected_total,
            "scope_counts": counts,
            "party_artifacts": artifact_counts,
            "exact_compressed_frame_bytes_preserved": bytes_copied,
            "frames_recompressed": 0,
            "packaging_integrity_checked_frames": _expected_total,
            "provenance_sha256": reader.scope["conversion_provenance_sha256"],
            "facet_or_rank_claims_inherited": False,
            "new_mathematical_audits_executed": 0,
            "original_artifacts_overwritten": False,
            "repository_primary_loader_switched": False,
            "production_format_promoted": False,
            "git_lfs_or_billing_mutated": False,
            "required_next": (
                "Actual complete staged-corpus mathematical audit through the new package verifier, "
                "independent scope/schema/CI review, then explicit local repository promotion; "
                "no publication or LFS/billing change."
            ),
            "goal_complete": False,
        }
        derivations.save_new(output / "stage-report.json", report)
        return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("run", "export", "output"):
        parser.add_argument("--" + name, required=True, type=Path)
    args = parser.parse_args()
    print(canonical_json(stage(args.run, args.export, args.output)).decode())


if __name__ == "__main__":
    main()
