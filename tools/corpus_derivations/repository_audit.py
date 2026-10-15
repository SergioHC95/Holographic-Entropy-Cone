"""Frozen, checkpointed ACTUAL full-cube audit of the complete staged corpus.

This is a new mathematical pass through the installed-package reader/verifier,
not acceptance from conversion receipts. CLI scope cannot be narrowed. Every
input/code/runtime/binary binding and prior completed row is checked on resume.
"""

from __future__ import annotations

import argparse
import atexit
import fcntl
import multiprocessing
import os
import shutil
import sqlite3
import subprocess
import sys
import time
import traceback
from collections import Counter
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from contextlib import ExitStack, closing
from datetime import UTC, datetime
from pathlib import Path

from hec._count_transport import CompatibleRank
from hec.count_proofs import canonical_json, decimal, geometry, parse_json
from hec.inequality_records import InequalityCatalog
from hec.reconstruction_store import ReconstructionCatalog
from hec.reconstruction_verify import ReconstructionVerifier

from . import run as derivations
from .continue_pipeline import atomic_record, idle
from .pipeline_batch import runtime_versions
from .synthesize import EXPECTED_COUNTS, EXPECTED_TOTAL

FORMAT = "hec-staged-full-cube-audit/1"
_SETTINGS, _CATALOGS, _VERIFIER = None, {}, None


def initialize(settings):
    global _SETTINGS, _CATALOGS, _VERIFIER
    _SETTINGS, _CATALOGS = settings, {}
    binaries = settings["binaries"]
    profile = settings.get("cube_backend_profile")
    _VERIFIER = ReconstructionVerifier(
        closure_binary=binaries.get("closure", {}).get("path", ""),
        cube_binary=binaries.get("wide", {}).get("path", ""),
        cube_working_bytes=profile["primary_output_buffer_bytes"] if profile is not None else None,
    )
    atexit.register(_VERIFIER.close)


def validate_result(result, item):
    audit = result.get("audit", {})
    expected = {
        "ok": True,
        "scope": "original-cube-all-edges",
        "proof_id": item["proof_id"],
        "inequality_id": item["inequality_id"],
        "semantic_map_id": item["semantic_map_id"],
        "checked_vertices": 1 << item["L"],
        "checked_edges": item["L"] * ((1 << item["L"]) // 2),
        "source_tables_read": False,
    }
    if (
        type(result.get("task")) is not int
        or result["task"] != item["task"]
        or result.get("actual_new_full_cube_audit_executed") is not True
        or any(type(audit.get(key)) is not type(value) or audit[key] != value for key, value in expected.items())
    ):
        raise ValueError("staged audit is incomplete, mismatched or not actual original-cube acceptance")


def audit_one(item):
    n = str(item["n"])
    if n not in _CATALOGS:
        _CATALOGS[n] = ReconstructionCatalog(_SETTINGS["catalogs"][n]["path"])
    catalog = _CATALOGS[n]
    entry = catalog.entries[item["index"]]
    if (entry["proof_id"], entry["inequality_id"]) != (item["proof_id"], item["inequality_id"]):
        raise ValueError("staged audit input changed before worker read")
    result = {
        "task": item["task"],
        "actual_new_full_cube_audit_executed": True,
        "audit": catalog.audit_entry(item["index"], _VERIFIER),
    }
    validate_result(result, item)
    return result


def cube_backend(binary, expected_sha, controls, root):
    """Trusted operator configuration, never a field inside a proof document.

    Controls qualify an implementation, not a mathematical proof. The full
    staged run still executes every original-cube audit independently.
    """
    if binary is None and expected_sha is None and controls is None:
        return None
    if binary is None or expected_sha is None or controls is None:
        raise ValueError("cube override requires an explicit binary, SHA256 and actual control report")
    binary, controls = Path(binary), Path(controls)
    if binary.is_symlink() or controls.is_symlink() or not binary.is_file() or not controls.is_file():
        raise ValueError("cube override binary/control must be explicit regular files")
    if derivations.digest(binary) != expected_sha:
        raise ValueError("cube override binary SHA256 mismatch")
    report = parse_json(controls.read_bytes())
    control_binding = controls.with_name("binding.json")
    if derivations.digest(control_binding) != report.get("binding_sha256"):
        raise ValueError("cube control implementation binding changed")
    binding = parse_json(control_binding.read_bytes())
    source = root / "tools/verify_reconstruction.cpp"
    if (
        report.get("format") != "hec-tiled-audit-report/1"
        or binding.get("format") != "hec-tiled-audit-control/1"
        or report.get("primary_output_buffer_budget_bytes") != 256 * 1024**2
        or binding.get("primary_output_buffer_budget_bytes") != 256 * 1024**2
        or binding.get("prototype_binary", {}).get("sha256") != expected_sha
        or binding.get("implementation", {}).get("tools/verify_reconstruction.cpp") != derivations.digest(source)
        or not isinstance(report.get("cases"), list)
        or not 4 <= len(report["cases"]) <= 8
        or {case.get("primitive") for case in report["cases"]}
        != {"integer-interval-closure/1", "integer-cut-dnf/1", "compatible-count-table/1", "compatible-scalar-dag/1"}
    ):
        raise ValueError("cube override lacks the exact standard source and all-four-primitive controls")
    edges = 0
    for case in report["cases"]:
        L = case.get("L")
        if type(L) is not int or not 0 <= L <= 25 or not case.get("pairs"):
            raise ValueError("invalid cube control geometry or repeated-pair scope")
        for pair in case["pairs"]:
            if set(pair.get("arms", {})) != {"full", "bounded"}:
                raise ValueError("cube control lacks actual full/reference and bounded arms")
            reference = pair["arms"]["full"]["audit"]
            for name, arm in pair["arms"].items():
                result = arm["audit"]
                expected = {
                    "ok": True,
                    "scope": "original-cube-all-edges",
                    "source_tables_read": False,
                    "checked_vertices": 1 << L,
                    "checked_edges": L * ((1 << L) // 2),
                }
                if any(
                    type(result.get(key)) is not type(value) or result[key] != value for key, value in expected.items()
                ):
                    raise ValueError("cube control is partial, seed-only or has inexact coverage types")
                if any(
                    result.get(key) != reference.get(key)
                    or not isinstance(result.get(key), str)
                    or len(result[key]) != 64
                    for key in ("proof_id", "inequality_id", "semantic_map_id")
                ):
                    raise ValueError("cube control changed exact definition/inequality/map identities")
                if name == "bounded" and (
                    type(result.get("output_row_storage_limit")) is not int
                    or result["output_row_storage_limit"] != 256 * 1024**2
                    or type(result.get("output_row_storage_bytes")) is not int
                    or not 0 <= result["output_row_storage_bytes"] <= 256 * 1024**2
                ):
                    raise ValueError("cube control did not acknowledge its exact primary buffer budget")
                edges += result["checked_edges"]
    if (
        type(report.get("actual_original_cube_edges_including_timing_repeats")) is not int
        or report["actual_original_cube_edges_including_timing_repeats"] != edges
    ):
        raise ValueError("cube control actual coverage total differs")
    return {
        "path": str(binary.resolve()),
        "sha256": expected_sha,
        "source_sha256": derivations.digest(source),
        "primary_output_buffer_bytes": 256 * 1024**2,
        "controls": str(controls.resolve()),
        "controls_sha256": derivations.digest(controls),
        "control_binding": str(control_binding.resolve()),
        "control_binding_sha256": derivations.digest(control_binding),
    }


def prepare(
    stage,
    conversion,
    output,
    *,
    cube_binary=None,
    cube_sha256=None,
    cube_controls=None,
    _expected_total=EXPECTED_TOTAL,
    _expected_counts=None,
):
    stage, conversion, output = (Path(value).resolve() for value in (stage, conversion, output))
    counts = EXPECTED_COUNTS if _expected_counts is None else _expected_counts
    if not idle(conversion, set()):
        raise BlockingIOError("conversion/export still live; do not compete with staged full audit")
    report = parse_json((stage / "stage-report.json").read_bytes())
    original = parse_json((conversion / "run-binding.json").read_bytes())
    if (
        report.get("format") != "hec-unified-repository-stage/1"
        or report.get("proofs") != _expected_total
        or report.get("scope_counts") != counts
        or report.get("source_run") != str(conversion)
        or report.get("conversion_binding_sha256") != derivations.digest(conversion / "run-binding.json")
        or report.get("production_format_promoted") is not False
        or report.get("packaging_integrity_checked_frames") != _expected_total
        or original.get("total") != _expected_total
        or original.get("scope_counts") != counts
    ):
        raise ValueError("staged audit requires complete bound corpus staging, never a subset")
    root = Path(__file__).resolve().parents[2]
    selected_cube = cube_backend(cube_binary, cube_sha256, cube_controls, root)
    for protected in (stage, conversion, root):
        if output.is_relative_to(protected) or protected.is_relative_to(output):
            raise ValueError("audit output must be outside protected data/run/worktree paths")
    if output.exists() and any(output.iterdir()):
        raise ValueError("choose a new immutable audit run; never overwrite prior checks")
    with closing(sqlite3.connect(f"file:{conversion / 'checkpoint.sqlite3'}?mode=ro", uri=True)) as db:
        if (
            db.execute("SELECT COUNT(*) FROM converted").fetchone()[0] != _expected_total
            or db.execute("SELECT COUNT(*) FROM errors").fetchone()[0]
        ):
            raise ValueError("partial/error conversion cannot authorize full staged audit")
        expected = {
            iid: (pid, semantic)
            for iid, pid, semantic in db.execute("SELECT inequality_id,proof_id,semantic_map_id FROM converted")
        }
    source = Path(original["source"])
    source_manifest = parse_json((source / "manifest.json").read_bytes())
    source_binding = parse_json((source / "run-binding.json").read_bytes())
    if derivations.digest(source / "manifest.json") != source_binding["manifest_sha256"]:
        raise ValueError("original complete source scope changed")
    source_ids = {entry["inequality_id"]: entry for entry in source_manifest}
    catalogs, manifest, seen, populations = {}, [], set(), Counter()
    for path in sorted((stage / "data").glob("n=*/proofs.json")):
        n = int(path.parent.name[2:])
        catalog = ReconstructionCatalog(path)
        records_path = path.with_name("inequalities.json")
        records = InequalityCatalog(records_path)
        records.check_bindings(catalog)
        catalogs[str(n)] = {
            "path": str(path),
            "sha256": derivations.digest(path),
            "inequalities_sha256": derivations.digest(records_path),
            "shards": catalog.shards,
        }
        for index, entry in enumerate(catalog.entries):
            iid = entry["inequality_id"]
            if (
                iid in seen
                or iid not in source_ids
                or source_ids[iid]["n"] != n
                or expected.get(iid, (None, None))[0] != entry["proof_id"]
            ):
                raise ValueError("staged audit catalogue changed the complete unique input scope")
            record = records.entries[iid]
            p = geometry(n, tuple(map(decimal, record["coefficients"])))
            C = CompatibleRank(p).count
            table_bytes = p.vertices * max(1, p.G) * 8
            if selected_cube is not None:
                table_bytes = min(table_bytes, selected_cube["primary_output_buffer_bytes"]) + p.vertices * 4
            budget = 1024**3 + table_bytes + 128 * C * max(1, p.G)
            manifest.append(
                {
                    "task": len(manifest),
                    "n": n,
                    "index": index,
                    "inequality_id": iid,
                    "proof_id": entry["proof_id"],
                    "semantic_map_id": expected[iid][1],
                    "L": p.L,
                    "G": p.G,
                    "memory_budget_bytes": budget,
                }
            )
            seen.add(iid)
            populations[source_ids[iid]["group"] if n == 6 else "small-n"] += 1
    if len(manifest) != _expected_total or seen != set(expected) or dict(populations) != counts:
        raise ValueError("staged audit did not bind ALL source/converted inequalities")
    if _expected_total == EXPECTED_TOTAL and set(original["binaries"]) != {"closure", "wide", "narrow"}:
        raise ValueError("complete staged corpus requires bound independent exact binaries")
    output.mkdir(parents=True, exist_ok=True)
    implementation, binaries = {}, {}
    for folder in ("src/hec", "tools/corpus_derivations", "tools/derivation_pilot"):
        for path in sorted((root / folder).rglob("*")):
            if path.is_file() and path.suffix in (".py", ".cpp"):
                relative = path.relative_to(root)
                target = output / "implementation" / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, target)
                implementation[str(relative)] = derivations.digest(target)
    relative = Path("tools/verify_reconstruction.cpp")
    target = output / "implementation" / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(root / relative, target)
    implementation[str(relative)] = derivations.digest(target)
    for label in ("closure", "wide"):
        if label in original["binaries"]:
            info = selected_cube if label == "wide" and selected_cube is not None else original["binaries"][label]
            if derivations.digest(info["path"]) != info["sha256"]:
                raise ValueError("independent audit binary changed")
            target = output / label
            shutil.copy2(info["path"], target)
            binaries[label] = {"path": str(target), "sha256": derivations.digest(target)}
    derivations.save_new(output / "manifest.json", manifest)
    binding = {
        "format": FORMAT,
        "prepared_utc": datetime.now(UTC).isoformat(),
        "stage": str(stage),
        "stage_report_sha256": derivations.digest(stage / "stage-report.json"),
        "conversion": str(conversion),
        "conversion_binding_sha256": derivations.digest(conversion / "run-binding.json"),
        "total": _expected_total,
        "scope_counts": counts,
        "workers": derivations.worker_count(original),
        "rss_limit_bytes": 64 * 1024**3,
        "manifest_sha256": derivations.digest(output / "manifest.json"),
        "catalogs": catalogs,
        "implementation": implementation,
        "binaries": binaries,
        "cube_backend_profile": selected_cube,
        "runtime": runtime_versions(),
        "python_sha256": derivations.digest(sys.executable),
    }
    derivations.save_new(output / "run-binding.json", binding)
    (output / "controller.lock").touch(exist_ok=False)
    return binding


def load_binding(output, expected_total, expected_counts):
    binding = parse_json((output / "run-binding.json").read_bytes())
    if (
        binding.get("format") != FORMAT
        or binding.get("total") != expected_total
        or binding.get("scope_counts") != expected_counts
        or binding.get("rss_limit_bytes") != 64 * 1024**3
        or binding.get("runtime") != runtime_versions()
        or binding.get("python_sha256") != derivations.digest(sys.executable)
    ):
        raise ValueError("staged audit scope/runtime/resource binding changed")
    derivations.worker_count(binding)
    if derivations.digest(output / "manifest.json") != binding["manifest_sha256"]:
        raise ValueError("immutable audit input manifest changed")
    manifest = parse_json((output / "manifest.json").read_bytes())
    if len(manifest) != expected_total or [item["task"] for item in manifest] != list(range(expected_total)):
        raise ValueError("audit input coverage changed")
    root = Path(__file__).resolve().parents[2]
    for relative, sha in binding["implementation"].items():
        if (
            derivations.digest(output / "implementation" / relative) != sha
            or derivations.digest(root / relative) != sha
        ):
            raise ValueError("frozen or executing staged audit implementation changed")
    for info in binding["binaries"].values():
        if derivations.digest(info["path"]) != info["sha256"]:
            raise ValueError("independent staged audit binary changed")
    profile = binding.get("cube_backend_profile")
    if profile is not None:
        if binding["binaries"].get("wide", {}).get("sha256") != profile["sha256"]:
            raise ValueError("selected standard cube backend changed")
        for label in ("controls", "control_binding"):
            if derivations.digest(profile[label]) != profile[label + "_sha256"]:
                raise ValueError("selected cube control evidence changed")
    if derivations.digest(Path(binding["stage"]) / "stage-report.json") != binding["stage_report_sha256"]:
        raise ValueError("staged input provenance changed")
    if derivations.digest(Path(binding["conversion"]) / "run-binding.json") != binding["conversion_binding_sha256"]:
        raise ValueError("completed conversion provenance changed")
    for info in binding["catalogs"].values():
        path = Path(info["path"])
        if (
            derivations.digest(path) != info["sha256"]
            or derivations.digest(path.with_name("inequalities.json")) != info["inequalities_sha256"]
        ):
            raise ValueError("staged catalogue/index changed")
        for sha, metadata in info["shards"].items():
            shard = path.parent / "proof-shards" / f"{sha}.proofpack"
            if shard.is_symlink() or shard.stat().st_size != metadata["bytes"] or derivations.digest(shard) != sha:
                raise ValueError("staged proof shard changed")
    return binding, manifest


def execute(output, *, _expected_total=EXPECTED_TOTAL, _expected_counts=None):
    output = Path(output).resolve()
    counts = EXPECTED_COUNTS if _expected_counts is None else _expected_counts
    with (output / "controller.lock").open("r") as lock, ExitStack() as resources:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        settings, manifest = load_binding(output, _expected_total, counts)
        db = resources.enter_context(closing(sqlite3.connect(output / "checkpoint.sqlite3")))
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA synchronous=FULL")
        db.executescript(
            "CREATE TABLE IF NOT EXISTS audited(task INTEGER PRIMARY KEY,proof_id TEXT NOT NULL,report TEXT NOT NULL); "
            "CREATE TABLE IF NOT EXISTS errors(task INTEGER PRIMARY KEY,error TEXT NOT NULL);"
        )
        done = set()
        for task, pid, raw in db.execute("SELECT task,proof_id,report FROM audited"):
            if type(task) is not int or not 0 <= task < len(manifest) or pid != manifest[task]["proof_id"]:
                raise ValueError("completed audit row changed scope/identity")
            validate_result(parse_json(raw.encode()), manifest[task])
            done.add(task)
        atomic_record(
            output / "controller.json",
            {
                "pid": os.getpid(),
                "birth": subprocess.check_output(["ps", "-p", str(os.getpid()), "-o", "lstart="], text=True).strip(),
                "phase": "repository-full-cube-audit",
            },
        )
        stream = iter(item for item in manifest if item["task"] not in done)
        active, reserved, pending, exhausted = {}, {}, None, False
        last_guard = last_sample = 0
        with ProcessPoolExecutor(
            max_workers=derivations.worker_count(settings),
            mp_context=multiprocessing.get_context("spawn"),
            initializer=initialize,
            initargs=(settings,),
        ) as pool:
            try:
                while active or not exhausted:
                    if time.monotonic() - last_guard >= 2:
                        derivations.enforce_rss_limit(output)
                        last_guard = time.monotonic()
                    while not exhausted and len(active) < derivations.worker_count(settings):
                        if pending is None:
                            try:
                                pending = next(stream)
                            except StopIteration:
                                exhausted = True
                                break
                        budget = pending["memory_budget_bytes"]
                        if not derivations.admission_fits(reserved, budget):
                            if not active:
                                raise MemoryError("individual audit exceeds unchanged aggregate admission cap")
                            break
                        future = pool.submit(audit_one, pending)
                        active[future] = pending
                        reserved[future] = budget
                        pending = None
                    if time.monotonic() - last_sample >= 30:
                        rss, _ = derivations.process_usage(os.getpid())
                        atomic_record(
                            output / "progress.json",
                            {
                                "sample_utc": datetime.now(UTC).isoformat(),
                                "phase": "actual-staged-original-cube-audit",
                                "audited": len(done),
                                "expected": _expected_total,
                                "configured_workers": derivations.worker_count(settings),
                                "active_tasks": [item["task"] for item in active.values()],
                                "reserved_budget_bytes": sum(reserved.values()),
                                "rss_bytes": rss,
                                "rss_limit_bytes": 64 * 1024**3,
                                "recorded_errors": db.execute("SELECT COUNT(*) FROM errors").fetchone()[0],
                                "goal_complete": False,
                            },
                        )
                        last_sample = time.monotonic()
                    ready, _ = wait(active, timeout=1, return_when=FIRST_COMPLETED)
                    for future in ready:
                        item = active.pop(future)
                        reserved.pop(future)
                        try:
                            result = future.result()
                            validate_result(result, item)
                            with db:
                                db.execute(
                                    "INSERT INTO audited VALUES(?,?,?)",
                                    (item["task"], item["proof_id"], canonical_json(result).decode()),
                                )
                                db.execute("DELETE FROM errors WHERE task=?", (item["task"],))
                            done.add(item["task"])
                        except Exception:
                            with db:
                                db.execute(
                                    "INSERT OR REPLACE INTO errors VALUES(?,?)", (item["task"], traceback.format_exc())
                                )
                            raise
                if db.execute("SELECT COUNT(*) FROM errors").fetchone()[0]:
                    raise ValueError("unresolved audit errors prevent completion")
            finally:
                db.close()
        if len(done) != _expected_total:
            raise ValueError("audit invocation ended without all complete maps")
        load_binding(output, _expected_total, counts)  # Detect any input/code change during the audit, too.
        edges = sum(item["L"] * ((1 << item["L"]) // 2) for item in manifest)
        vertices = sum(1 << item["L"] for item in manifest)
        previous = output / "report.json"
        if previous.exists():
            saved = parse_json(previous.read_bytes())
            if (
                saved.get("run_binding_sha256") != derivations.digest(output / "run-binding.json")
                or saved.get("actual_full_cube_audited") != _expected_total
                or saved.get("checked_original_cube_edges") != edges
            ):
                raise ValueError("completed immutable audit report changed")
            return saved
        report = {
            "format": FORMAT,
            "completed_utc": datetime.now(UTC).isoformat(),
            "actual_full_cube_audited": len(done),
            "checked_original_cube_vertices": vertices,
            "checked_original_cube_edges": edges,
            "party_counts": dict(Counter(str(item["n"]) for item in manifest)),
            "recorded_errors": 0,
            "source_tables_read": False,
            "stored_acceptance_flags_used": False,
            "run_binding_sha256": derivations.digest(output / "run-binding.json"),
            "goal_complete": False,
        }
        derivations.save_new(output / "report.json", report)
        atomic_record(
            output / "progress.json",
            {
                "sample_utc": datetime.now(UTC).isoformat(),
                "phase": "completed-staged-original-cube-audit",
                "audited": len(done),
                "expected": _expected_total,
                "configured_workers": derivations.worker_count(settings),
                "active_tasks": [],
                "recorded_errors": 0,
                "rss_limit_bytes": 64 * 1024**3,
                "goal_complete": False,
            },
        )
        return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    commands = parser.add_subparsers(dest="command", required=True)
    setup = commands.add_parser("prepare")
    setup.add_argument("--stage", type=Path, required=True)
    setup.add_argument("--conversion", type=Path, required=True)
    setup.add_argument("--cube-binary", type=Path)
    setup.add_argument("--cube-sha256")
    setup.add_argument("--cube-controls", type=Path)
    commands.add_parser("run")
    args = parser.parse_args()
    value = (
        prepare(
            args.stage,
            args.conversion,
            args.output,
            cube_binary=args.cube_binary,
            cube_sha256=args.cube_sha256,
            cube_controls=args.cube_controls,
        )
        if args.command == "prepare"
        else execute(args.output)
    )
    print(canonical_json(value).decode())


if __name__ == "__main__":
    main()
