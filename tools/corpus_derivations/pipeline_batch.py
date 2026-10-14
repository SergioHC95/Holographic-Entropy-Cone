"""Frozen, memory-bounded, checkpointed conversion of the complete selected corpus.

No new full-cube audit is claimed. Every conversion preserves complete exact
compatible values and the same fixed extension, retaining executed audit
provenance. Alternatives are compared against their sources IN THIS FORMAT.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import importlib.metadata
import multiprocessing
import os
import shutil
import sqlite3
import subprocess
import sys
import time
import traceback
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from datetime import UTC, datetime
from pathlib import Path

import zstandard as zstd

from hec._count_transport import CompatibleRank
from hec.count_proofs import canonical_json, inequality_id, parse_json, proof_geometry, proof_id
from hec.reconstruction import EXTENSION, PIPELINE, ReconstructionProgram

from . import run as derivations
from .continue_pipeline import atomic_record
from .pipeline_convert import convert_definition
from .pipeline_import import NativeClosure
from .selected_corpus import VerifiedSelection
from .synthesize import EXPECTED_COUNTS, EXPECTED_TOTAL, decode_frame, geometry_only

FORMAT = "hec-unified-pipeline-run/1"
_CLOSURE = None
_MATH_FILES = (
    "src/hec/count_proofs.py",
    "src/hec/_count_transport.py",
    "tools/derivation_pilot/recipes.py",
    "tools/corpus_derivations/diagrams.py",
)


def runtime_versions():
    return {"python": sys.version, **{name: importlib.metadata.version(name) for name in ("numpy", "zstandard")}}


def inputs(selection, done=frozenset()):
    for selected in selection.items():
        if selected.task not in done:
            baseline = selection.source_definition(selected.task) if selected.origin == "verified-alternative" else None
            yield selected, baseline


def input_binding(pair):
    selected, baseline = pair
    return {"task": selected.task, "selected": selected.binding(), "baseline": baseline.binding() if baseline else None}


def memory_budget(pair):
    p = geometry_only(parse_json(pair[0].raw))
    count = CompatibleRank(p).count
    # Seed/candidate/Fraction copies, two variants where appropriate, and parsed
    # JSON. This phase does NOT allocate a full original-cube output table.
    variants = 2 if pair[1] is not None else 1
    raw = sum(len(record.raw) for record in pair if record is not None)
    return 1024**3 + 128 * variants * count * max(1, p.G) + 8 * raw


def initialize(settings):
    global _CLOSURE
    info = settings["binaries"].get("closure")
    _CLOSURE = NativeClosure(info["path"], info["sha256"]) if info else None


def convert_pair(pair):
    selected, baseline = pair
    candidate = convert_definition(selected, closure_backend=_CLOSURE)
    variants, chosen = [candidate], candidate
    status = "verified_source_no_retained_alternative"
    if baseline is not None:
        if selected.origin != "verified-alternative" or baseline.origin != "verified-source":
            raise ValueError("invalid alternative/source variant pair")
        if (selected.task, selected.inequality_id) != (baseline.task, baseline.inequality_id):
            raise ValueError("variant pair changed task or inequality")
        source = convert_definition(baseline, closure_backend=_CLOSURE)
        variants.append(source)
        if candidate.semantic_map_id == source.semantic_map_id:
            raise ValueError("reported changed alternative unexpectedly has identical full-map semantics")
        if len(candidate.raw) < len(source.raw):
            status = "retained_strictly_smaller_pipeline_alternative"
        else:
            status, chosen = "verified_source_alternative_not_smaller_in_pipeline", source
        baseline_size = len(source.raw)
    else:
        if selected.origin != "verified-source":
            raise ValueError("an alternative requires its audited source for fair size comparison")
        baseline_size = len(candidate.raw)
    receipt = {
        "format": "hec-pipeline-variant-selection/1",
        "input": input_binding(pair),
        "task": chosen.task,
        "inequality_id": chosen.inequality_id,
        "status": status,
        "target_recipe_sha256": chosen.recipe_sha256,
        "target_proof_id": chosen.proof_id,
        "semantic_map_id": chosen.semantic_map_id,
        "target_json_bytes": len(chosen.raw),
        "baseline_pipeline_json_bytes": baseline_size,
        "candidate_pipeline_json_bytes": len(candidate.raw),
        "variants_converted": len(variants),
        "variants": [parse_json(value.receipt) for value in variants],
        "chosen_conversion": parse_json(chosen.receipt),
        "new_exhaustive_original_cube_audits_executed": 0,
    }
    return receipt, zstd.ZstdCompressor(level=9, write_checksum=True).compress(chosen.raw)


def prepare(source, synthesis, output, *, _expected_total=EXPECTED_TOTAL, _expected_counts=None):
    output, root = Path(output).resolve(), Path(__file__).resolve().parents[2]
    expected_counts = EXPECTED_COUNTS if _expected_counts is None else _expected_counts
    # Validate complete, idle input phases BEFORE creating an output directory.
    with VerifiedSelection(
        source, synthesis, _expected_total=_expected_total, _expected_counts=expected_counts
    ) as selected:
        for protected in (root, selected.source.root, selected.root):
            if output.is_relative_to(protected) or protected.is_relative_to(output):
                raise ValueError(
                    "conversion output must be a separate immutable run, outside protected inputs/worktree"
                )
        if output.exists() and any(output.iterdir()):
            raise ValueError("choose an empty new conversion output; never overwrite a run")
        if _expected_total == EXPECTED_TOTAL:
            if set(selected.source.binding["binaries"]) != {"closure", "wide", "narrow"}:
                raise ValueError("full corpus requires its frozen exact primitive binaries")
            for relative in _MATH_FILES:
                if derivations.digest(root / relative) != selected.source.binding["implementation"].get(relative):
                    raise ValueError(
                        "accepted seed decoder/extension changed; exact conversion requires explicit review"
                    )
        output.mkdir(parents=True, exist_ok=True)
        implementation, binaries, manifest = {}, {}, []
        for directory in ("src/hec", "tools/derivation_pilot", "tools/corpus_derivations"):
            for path in sorted((root / directory).rglob("*")):
                if path.is_file() and path.suffix in (".py", ".cpp"):
                    relative = path.relative_to(root)
                    target = output / "implementation" / relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(path, target)
                    implementation[str(relative)] = derivations.digest(target)
        for label, info in selected.source.binding["binaries"].items():
            target = output / label
            shutil.copy2(info["path"], target)
            if derivations.digest(target) != info["sha256"]:
                raise ValueError("frozen primitive copy changed")
            binaries[label] = {"path": str(target), "sha256": info["sha256"]}
        for pair in inputs(selected):
            manifest.append(input_binding(pair))
        derivations.save_new(output / "manifest.json", manifest)
        settings = {
            "format": FORMAT,
            "prepared_utc": datetime.now(UTC).isoformat(),
            "source": str(selected.source.root),
            "synthesis": str(selected.root),
            "source_binding_sha256": derivations.digest(selected.source.root / "run-binding.json"),
            "synthesis_binding_sha256": derivations.digest(selected.root / "run-binding.json"),
            "source_records_sha256": selected.source.records_sha256,
            "selected_records_sha256": selected.records_sha256,
            "total": _expected_total,
            "scope_counts": expected_counts,
            "workers": derivations.worker_count(selected.source.binding),
            "rss_limit_bytes": 64 * 1024**3,
            "profile": PIPELINE,
            "extension": EXTENSION,
            "manifest_sha256": derivations.digest(output / "manifest.json"),
            "implementation": implementation,
            "binaries": binaries,
            "runtime": runtime_versions(),
            "python": sys.executable,
            "python_sha256": derivations.digest(sys.executable),
            "output": str(output),
            "new_exhaustive_original_cube_audits_planned": 0,
        }
        derivations.save_new(output / "run-binding.json", settings)
        (output / "controller.lock").touch(exist_ok=False)
        return settings


def load_binding(output, *, _expected_total=EXPECTED_TOTAL, _expected_counts=None):
    output = Path(output).resolve()
    settings = parse_json((output / "run-binding.json").read_bytes())
    counts = EXPECTED_COUNTS if _expected_counts is None else _expected_counts
    if (
        settings.get("format") != FORMAT
        or settings.get("total") != _expected_total
        or settings.get("scope_counts") != counts
        or settings.get("rss_limit_bytes") != 64 * 1024**3
        or settings.get("profile") != PIPELINE
        or settings.get("extension") != EXTENSION
        or settings.get("output") != str(output)
        or settings.get("runtime") != runtime_versions()
        or settings.get("python_sha256") != derivations.digest(sys.executable)
    ):
        raise ValueError("frozen conversion scope, runtime or exact profile changed")
    derivations.worker_count(settings)
    if derivations.digest(output / "manifest.json") != settings["manifest_sha256"]:
        raise ValueError("immutable conversion manifest changed")
    manifest = parse_json((output / "manifest.json").read_bytes())
    if (
        len(manifest) != _expected_total
        or any(type(row["task"]) is not int for row in manifest)
        or [row["task"] for row in manifest] != list(range(_expected_total))
    ):
        raise ValueError("conversion manifest is not the complete ordered scope")
    root = Path(__file__).resolve().parents[2]
    for relative, sha in settings["implementation"].items():
        if (
            derivations.digest(output / "implementation" / relative) != sha
            or derivations.digest(root / relative) != sha
        ):
            raise ValueError("frozen or executing conversion implementation changed")
    for info in settings["binaries"].values():
        if derivations.digest(info["path"]) != info["sha256"]:
            raise ValueError("frozen exact primitive binary changed")
    return settings, manifest


def open_selection(settings, *, _expected_total=EXPECTED_TOTAL, _expected_counts=None):
    selected = VerifiedSelection(
        settings["source"], settings["synthesis"], _expected_total=_expected_total, _expected_counts=_expected_counts
    )
    if (
        selected.records_sha256 != settings["selected_records_sha256"]
        or selected.source.records_sha256 != settings["source_records_sha256"]
        or derivations.worker_count(selected.source.binding) != derivations.worker_count(settings)
        or derivations.digest(selected.source.root / "run-binding.json") != settings["source_binding_sha256"]
        or derivations.digest(selected.root / "run-binding.json") != settings["synthesis_binding_sha256"]
    ):
        selected.close()
        raise ValueError("fully verified selected corpus changed after conversion preparation")
    return selected


def database(output):
    db = sqlite3.connect(Path(output) / "checkpoint.sqlite3")
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA synchronous=FULL")
    db.executescript("""
      CREATE TABLE IF NOT EXISTS converted(task INTEGER PRIMARY KEY,inequality_id TEXT UNIQUE NOT NULL,
        recipe_sha256 TEXT NOT NULL,proof_id TEXT NOT NULL,semantic_map_id TEXT NOT NULL,
        json_bytes INTEGER NOT NULL,compressed BLOB NOT NULL,receipt TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS errors(task INTEGER PRIMARY KEY,error TEXT NOT NULL);
    """)
    return db


def validate_result(task, iid, sha, identity, semantic, size, data, receipt, expected_input):
    raw = decode_frame(data, size)
    document = parse_json(raw)
    if isinstance(receipt, str):
        saved_receipt = receipt.encode()
        receipt = parse_json(saved_receipt)
        if canonical_json(receipt) != saved_receipt:
            raise ValueError("converted checkpoint receipt is not canonical")
    if (
        type(task) is not int
        or task != expected_input["task"]
        or iid != expected_input["selected"]["inequality_id"]
        or len(raw) != size
        or hashlib.sha256(raw).hexdigest() != sha
        or canonical_json(document) != raw
        or proof_id(document) != identity
        or inequality_id(proof_geometry(document)) != iid
        or document["function"].get("kind") != PIPELINE
        or document["function"].get("extension") != {"kind": EXTENSION}
        or receipt.get("input") != expected_input
        or receipt.get("task") != task
        or receipt.get("inequality_id") != iid
        or receipt.get("target_recipe_sha256") != sha
        or receipt.get("target_proof_id") != identity
        or receipt.get("semantic_map_id") != semantic
        or receipt.get("target_json_bytes") != size
        or type(receipt.get("new_exhaustive_original_cube_audits_executed")) is not int
        or receipt["new_exhaustive_original_cube_audits_executed"] != 0
    ):
        raise ValueError("converted checkpoint changed its bound task, target or provenance")
    ReconstructionProgram(raw, closure_backend=_CLOSURE)  # Strict syntax/scale, no repeated full-cube audit.
    chosen = receipt.get("chosen_conversion", {})
    candidates = [expected_input["selected"]] + ([expected_input["baseline"]] if expected_input["baseline"] else [])
    variants = receipt.get("variants")
    if (
        not isinstance(variants, list)
        or len(variants) != len(candidates)
        or chosen not in variants
        or type(receipt.get("variants_converted")) is not int
        or receipt["variants_converted"] != len(variants)
    ):
        raise ValueError("conversion lost a required source/alternative comparison")
    p = proof_geometry(document)
    domain_count = CompatibleRank(p).count
    for variant, source in zip(variants, candidates, strict=True):
        audit = variant.get("source_mathematical_audit", {})
        equivalence = variant.get("equivalence", {})
        if (
            variant.get("task") != task
            or variant.get("inequality_id") != iid
            or variant.get("source_recipe_sha256") != source["recipe_sha256"]
            or variant.get("source_origin") != source["origin"]
            or audit.get("root") != source["audit_root"]
            or audit.get("receipt_sha256") != source["audit_receipt_sha256"]
            or audit.get("scope") != "original-cube-all-edges"
            or type(audit.get("checked_vertices")) is not int
            or audit["checked_vertices"] != p.vertices
            or type(audit.get("checked_edges")) is not int
            or audit["checked_edges"] != p.L * (p.vertices // 2)
            or equivalence.get("scope") != "complete-compatible-value-equivalence-and-identical-fixed-extension"
            or type(equivalence.get("checked_compatible_vertices")) is not int
            or equivalence["checked_compatible_vertices"] != domain_count
            or equivalence.get("source_definition_sha256") != source["recipe_sha256"]
            or equivalence.get("target_proof_id") != variant.get("target_proof_id")
            or type(variant.get("target_json_bytes")) is not int
            or variant["target_json_bytes"] < 1
            or variant.get("new_exhaustive_original_cube_audit_executed") is not False
        ):
            raise ValueError("variant comparison has incomplete equivalence or mismatched executed audit evidence")
    if (
        type(receipt.get("baseline_pipeline_json_bytes")) is not int
        or type(receipt.get("candidate_pipeline_json_bytes")) is not int
    ):
        raise ValueError("pipeline cost comparison needs exact integer byte counts")
    if (
        receipt["candidate_pipeline_json_bytes"] != variants[0]["target_json_bytes"]
        or receipt["baseline_pipeline_json_bytes"] != variants[-1]["target_json_bytes"]
    ):
        raise ValueError("pipeline size ranking differs from its converted variants")
    origin = next(
        (record for record in candidates if record["recipe_sha256"] == chosen.get("source_recipe_sha256")), None
    )
    audit = chosen.get("source_mathematical_audit", {})
    if (
        origin is None
        or chosen.get("target_recipe_sha256") != sha
        or chosen.get("target_proof_id") != identity
        or chosen.get("semantic_map_id") != semantic
        or chosen.get("new_exhaustive_original_cube_audit_executed") is not False
        or audit.get("receipt_sha256") != origin["audit_receipt_sha256"]
        or audit.get("root") != origin["audit_root"]
        or audit.get("task") != task
        or audit.get("scope") != "original-cube-all-edges"
    ):
        raise ValueError("chosen pipeline does not preserve its own executed audit provenance")
    alternative = receipt.get("status") == "retained_strictly_smaller_pipeline_alternative"
    if alternative:
        if (
            origin["origin"] != "verified-alternative"
            or not size < receipt["baseline_pipeline_json_bytes"]
            or chosen != variants[0]
        ):
            raise ValueError("unified alternative is not genuinely smaller in the same encoding")
    elif (
        receipt.get("status")
        not in ("verified_source_no_retained_alternative", "verified_source_alternative_not_smaller_in_pipeline")
        or origin["origin"] != "verified-source"
    ):
        raise ValueError("invalid unified selection disposition")
    elif expected_input["baseline"] is not None:
        if receipt["candidate_pipeline_json_bytes"] < receipt["baseline_pipeline_json_bytes"] or chosen != variants[-1]:
            raise ValueError("unified selection discarded a genuinely smaller verified pipeline alternative")
    elif receipt["status"] != "verified_source_no_retained_alternative":
        raise ValueError("source-only conversion has an inconsistent disposition")
    return raw, receipt, origin["origin"]


def progress(db, output, settings, active, started, reserved=0):
    rss, processes = derivations.process_usage(os.getpid())
    count = db.execute("SELECT COUNT(*) FROM converted").fetchone()[0]
    value = {
        "sample_utc": datetime.now(UTC).isoformat(),
        "phase": "unified-pipeline-conversion",
        "converted": count,
        "expected": settings["total"],
        "remaining": settings["total"] - count,
        "configured_workers": derivations.worker_count(settings),
        "active_tasks": sorted(active),
        "reserved_task_budget_bytes": reserved,
        "rss_bytes": rss,
        "rss_limit_bytes": 64 * 1024**3,
        "recorded_errors": db.execute("SELECT COUNT(*) FROM errors").fetchone()[0],
        "new_exhaustive_original_cube_audits_executed": 0,
        "full_goal_complete": False,
        "elapsed_seconds": int(time.monotonic() - started),
        "processes": processes,
    }
    atomic_record(Path(output) / "progress.json", value)
    return value


def execute(output, *, _expected_total=EXPECTED_TOTAL, _expected_counts=None):
    output = Path(output).resolve()
    lock = (output / "controller.lock").open("r")
    selected, db, executor = None, None, None
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        settings, manifest = load_binding(output, _expected_total=_expected_total, _expected_counts=_expected_counts)
        initialize(settings)
        selected = open_selection(settings, _expected_total=_expected_total, _expected_counts=_expected_counts)
        db = database(output)
        done = set()
        for row in db.execute(
            "SELECT task,inequality_id,recipe_sha256,proof_id,semantic_map_id,"
            "json_bytes,compressed,receipt FROM converted"
        ):
            if type(row[0]) is not int or not 0 <= row[0] < len(manifest):
                raise ValueError("completed conversion lies outside the immutable manifest")
            validate_result(*row, manifest[row[0]])
            done.add(row[0])
        atomic_record(
            output / "controller.json",
            {
                "pid": os.getpid(),
                "pgid": os.getpgrp(),
                "birth": subprocess.check_output(["ps", "-p", str(os.getpid()), "-o", "lstart="], text=True).strip(),
                "phase": "unified-pipeline-conversion",
            },
        )
        workers = derivations.worker_count(settings)
        executor = ProcessPoolExecutor(
            max_workers=workers,
            mp_context=multiprocessing.get_context("spawn"),
            initializer=initialize,
            initargs=(settings,),
        )
        stream, active, reserved = iter(inputs(selected, done)), {}, {}
        pending, exhausted, started, last_guard, last_sample = None, False, time.monotonic(), 0, 0
        while active or not exhausted:
            if time.monotonic() - last_guard >= 2:
                derivations.enforce_rss_limit(output)
                last_guard = time.monotonic()
            while not exhausted and len(active) < workers:
                if pending is None:
                    try:
                        pending = next(stream)
                    except StopIteration:
                        exhausted = True
                        break
                proposed = memory_budget(pending)
                if not derivations.admission_fits(reserved, proposed):
                    if not active:
                        raise MemoryError("individual conversion exceeds the unchanged 64 GiB admission cap")
                    break
                binding = input_binding(pending)
                if binding != manifest[pending[0].task]:
                    raise ValueError("selected input changed since its conversion manifest was frozen")
                future = executor.submit(convert_pair, pending)
                active[future], reserved[future], pending = binding, proposed, None
            if time.monotonic() - last_sample >= 30:
                progress(
                    db,
                    output,
                    settings,
                    (record["task"] for record in active.values()),
                    started,
                    sum(reserved.values()),
                )
                last_sample = time.monotonic()
            ready, _ = wait(active, timeout=1, return_when=FIRST_COMPLETED)
            for future in ready:
                binding = active.pop(future)
                reserved.pop(future)
                task = binding["task"]
                try:
                    receipt, data = future.result()
                    row = (
                        task,
                        receipt["inequality_id"],
                        receipt["target_recipe_sha256"],
                        receipt["target_proof_id"],
                        receipt["semantic_map_id"],
                        receipt["target_json_bytes"],
                        data,
                        canonical_json(receipt).decode(),
                    )
                    validate_result(*row, binding)
                    with db:
                        db.execute("INSERT INTO converted VALUES(?,?,?,?,?,?,?,?)", row)
                        db.execute("DELETE FROM errors WHERE task=?", (task,))
                except Exception:
                    with db:
                        db.execute("INSERT OR REPLACE INTO errors VALUES(?,?)", (task, traceback.format_exc()))
                    raise
        value = progress(db, output, settings, (), started)
        if value["converted"] != _expected_total or value["recorded_errors"]:
            raise ValueError("conversion ended without complete error-free manifest coverage")
        return value
    finally:
        if executor is not None:
            executor.shutdown(wait=True, cancel_futures=True)
        if db is not None:
            db.close()
        if selected is not None:
            selected.close()
        lock.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    commands = parser.add_subparsers(dest="command", required=True)
    setup = commands.add_parser("prepare")
    setup.add_argument("--source", type=Path, required=True)
    setup.add_argument("--synthesis", type=Path, required=True)
    commands.add_parser("run")
    args = parser.parse_args()
    result = prepare(args.source, args.synthesis, args.output) if args.command == "prepare" else execute(args.output)
    print(canonical_json(result).decode(), flush=True)


if __name__ == "__main__":
    main()
