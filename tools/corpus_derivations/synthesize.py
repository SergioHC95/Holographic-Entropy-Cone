"""Checkpointed alternative-map synthesis, gated on complete source verification.

This offline phase reads saved compact definitions, never archived source maps.
No corpus attempt is admitted until all 84,690 source winners have completed
the separate source-free original-cube audit. Every retained alternative must
change the map, strictly reduce canonical description bytes, and pass exact
full-cube acceptance. A second fresh phase audits retained alternatives again.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import itertools
import json
import os
import shutil
import sqlite3
import subprocess
import time
import traceback
from collections import Counter
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from datetime import UTC, datetime
from pathlib import Path

import zstandard as zstd
from derivation_pilot.recipes import FORMAT as PILOT_FORMAT
from derivation_pilot.recipes import WorkLimit as CutWorkLimit
from derivation_pilot.recipes import choice_recipe, closure_call, cut_recipe
from derivation_pilot.recipes import recipe_geometry as pilot_geometry

from hec.count_proofs import FORMAT as STANDARD_FORMAT
from hec.count_proofs import canonical_json, inequality_id, parse_json, proof_geometry

from . import run as derivations
from .diagrams import FORMAT as WIDE_FORMAT
from .diagrams import build, recipe_geometry
from .simplify import METHOD, WorkLimit, smooth

EXPECTED_TOTAL = 84690
EXPECTED_COUNTS = {"baseline": 80213, "small-n": 14, "exact": 76, "primitive": 4387}
SETTINGS = {}


def decode_frame(data, expected_size=None):
    size = zstd.frame_content_size(data)
    if not 0 <= size <= 1024**3 or (expected_size is not None and size != expected_size):
        raise ValueError("saved recipe frame has an unsafe or mismatched declared length")
    return zstd.ZstdDecompressor().decompress(data, max_output_size=1024**3, allow_extra_data=False)


def geometry_only(recipe):
    kind = recipe.get("format")
    if kind == WIDE_FORMAT:
        return recipe_geometry(recipe)
    if kind == PILOT_FORMAT:
        return pilot_geometry(recipe)
    if kind == STANDARD_FORMAT:
        n = recipe.get("inequality", {}).get("n")
        if type(n) is not int or not 1 <= n <= 6:
            raise ValueError("source recipe exceeds bounded party dimension")
        problem = proof_geometry(recipe)
        if problem.L > 25 or problem.G > 63:
            raise ValueError("source recipe exceeds bounded native geometry")
        return problem
    raise ValueError("unsupported saved source recipe format")


class VerifiedSource:
    """Locked, read-only, complete source ledger with per-record hash binding."""

    def __init__(self, root, *, _expected_total=EXPECTED_TOTAL, _expected_counts=None):
        self.root, self.db, self.lock = Path(root).resolve(), None, None
        expected_counts = EXPECTED_COUNTS if _expected_counts is None else _expected_counts
        try:
            self.lock = (self.root / "controller.lock").open("r")
            # No competing source writer, or adoption of a live verification job.
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.binding = parse_json((self.root / "run-binding.json").read_bytes())
            if self.binding["total"] != _expected_total or self.binding["workers"] != 2:
                raise ValueError("source scope or worker target differs from the full approved corpus")
            if self.binding["scope_counts"] != expected_counts:
                raise ValueError("source population counts differ from the full approved corpus")
            if derivations.digest(self.root / "manifest.json") != self.binding["manifest_sha256"]:
                raise ValueError("immutable source manifest changed")
            self.manifest = parse_json((self.root / "manifest.json").read_bytes())
            if (
                len(self.manifest) != _expected_total
                or len({item["inequality_id"] for item in self.manifest}) != _expected_total
            ):
                raise ValueError("source manifest has missing or duplicated identities")
            if [item["task"] for item in self.manifest] != list(range(_expected_total)):
                raise ValueError("source manifest task coverage is not complete")
            counts = Counter(item["group"] if item["n"] == 6 else "small-n" for item in self.manifest)
            if counts != Counter(expected_counts):
                raise ValueError("source manifest population differs from its approved binding")
            for relative, expected in self.binding["implementation"].items():
                if derivations.digest(self.root / "implementation" / relative) != expected:
                    raise ValueError("frozen source implementation changed")
            for info in self.binding["binaries"].values():
                if derivations.digest(info["path"]) != info["sha256"]:
                    raise ValueError("frozen source verifier binary changed")
            self.db = sqlite3.connect(f"file:{self.root / 'checkpoint.sqlite3'}?mode=ro", uri=True)
            counts = [
                self.db.execute(sql).fetchone()[0]
                for sql in (
                    "SELECT COUNT(*) FROM results",
                    "SELECT COUNT(*) FROM fresh WHERE ok=1",
                    "SELECT COUNT(*) FROM errors",
                )
            ]
            if counts != [_expected_total, _expected_total, 0]:
                raise ValueError("synthesis requires complete derivation AND source-free verification with no errors")
            binding_hash, seen = hashlib.sha256(), 0
            query = """SELECT r.task,r.inequality_id,r.recipe_sha256,r.json_bytes,r.compressed,f.report
                       FROM results r JOIN fresh f ON r.task=f.task AND f.ok=1 ORDER BY r.task"""
            for task, iid, sha, size, data, receipt in self.db.execute(query):
                raw = self.validate_record(task, iid, sha, size, data)
                verification = parse_json(receipt.encode())
                if verification.get("ok") is not True or verification.get("source_tables_read") is not False:
                    raise ValueError("source receipt is not a successful source-free audit")
                if verification.get("task") != task or verification.get("recipe_sha256") != sha:
                    raise ValueError("source-free receipt belongs to another task or recipe")
                p = geometry_only(parse_json(raw))
                acceptance = verification.get("full_cube_acceptance", {})
                if (
                    acceptance.get("ok") is not True
                    or acceptance.get("scope") != "original-cube-all-edges"
                    or acceptance.get("checked_vertices") != p.vertices
                    or acceptance.get("checked_edges") != p.L * (p.vertices // 2)
                ):
                    raise ValueError("source receipt does not cover the complete original cube")
                binding_hash.update(
                    canonical_json([task, iid, sha, hashlib.sha256(receipt.encode()).hexdigest()]) + b"\n"
                )
                seen += 1
            if seen != _expected_total:
                raise ValueError("source-free receipts do not cover every manifest task")
            self.records_sha256 = binding_hash.hexdigest()
        except Exception:
            self.close()
            raise

    def validate_record(self, task, iid, sha, size, data):
        if not 0 <= task < len(self.manifest) or self.manifest[task]["inequality_id"] != iid:
            raise ValueError("source ledger identity differs from its immutable manifest")
        raw = decode_frame(data, size)
        if len(raw) != size or hashlib.sha256(raw).hexdigest() != sha:
            raise ValueError("saved source recipe hash or length changed")
        recipe = parse_json(raw)
        if canonical_json(recipe) != raw or inequality_id(geometry_only(recipe)) != iid:
            raise ValueError("saved source recipe is noncanonical or belongs to another inequality")
        return raw

    def items(self, done):
        # Large/rational definitions first, but ALL source tasks remain in scope.
        query = """SELECT task,inequality_id,recipe_sha256,json_bytes,compressed FROM results
                   ORDER BY LENGTH(json_extract(report,'$.seed_scale')) DESC,json_bytes DESC,task"""
        for task, iid, sha, size, data in self.db.execute(query):
            if task not in done:
                yield task, self.validate_record(task, iid, sha, size, data), sha, iid

    def close(self):
        if self.db is not None:
            self.db.close()
            self.db = None
        if self.lock is not None:
            self.lock.close()
            self.lock = None


def initialize(settings):
    global SETTINGS
    SETTINGS = settings
    derivations.initialize(settings)


def choose_definition(problem, vertices, scale, rows, *, closure=None):
    """Exact replay of candidate encodings, not an acceptance shortcut."""
    methods, choices = {}, {}

    def add(name, recipe):
        raw = canonical_json(recipe)
        restored = derivations.reconstruct(parse_json(raw))
        if restored != (problem, vertices, scale, rows):
            raise ValueError("alternative encoding changed a synthesized exact seed value")
        choices[name] = raw
        methods[name] = {"complete_exact_seed_replay": True, "json_bytes": len(raw)}

    fallback = derivations.standard(problem, scale, rows)
    add("explicit-compatible-seed", fallback)
    add("shared-compatible-dag", build(problem, vertices, scale, rows))
    eligible = scale == 1 and problem.L <= 17 and sum(problem.beta) <= 63 and max(problem.alpha, default=0) <= 32
    if eligible and closure is not None:
        result = closure_call(Path(closure), problem, mode="encode", rows=rows)
        add("choice-closure", choice_recipe(problem, result))
        try:
            recipe, _ = cut_recipe(problem, vertices, rows, candidates=4, max_terms=512)
            add("cut-formulas", recipe)
        except CutWorkLimit as error:
            methods["cut-formulas"] = {"status": "incomplete_encoding_budget_not_a_proof", "error": str(error)}
    selected = min(choices, key=lambda name: (len(choices[name]), name))
    return selected, choices[selected], methods, fallback


def attempt(item):
    task, source_raw, source_sha, iid = item
    if hashlib.sha256(source_raw).hexdigest() != source_sha:
        raise ValueError("source definition does not match the completed verification ledger")
    p, vertices, d, rows = derivations.reconstruct(parse_json(source_raw))
    if inequality_id(p) != iid:
        raise ValueError("source recipe differs from the manifest inequality")
    start = time.monotonic_ns()
    report = {
        "task": task,
        "inequality_id": iid,
        "source_recipe_sha256": source_sha,
        "source_json_bytes": len(source_raw),
        "method": METHOD,
        "original_archived_maps_read": False,
        "alternative_json_bytes": None,
    }
    try:
        new_d, new_rows, statistics = smooth(
            p, vertices, d, rows, sweeps=SETTINGS["sweeps"], max_work=SETTINGS["max_work"]
        )
    except WorkLimit as error:
        report.update(status="incomplete_synthesis_budget_not_a_proof", error=str(error))
        return report, None
    report["synthesis"] = statistics
    if not statistics["changed_cells"]:
        report["status"] = "unchanged_source_no_alternative"
        return report, None
    selected, raw, methods, definition = choose_definition(
        p, vertices, new_d, new_rows, closure=SETTINGS["binaries"]["closure"]["path"]
    )
    report.update(winner=selected, encodings=methods, alternative_json_bytes=len(raw))
    if len(raw) >= len(source_raw):
        report["status"] = "changed_seed_without_strict_description_improvement_not_retained"
        return report, None
    # Reconstruct the saved candidate, with no source seed supplied to the decoder.
    rp, rv, rd, rr = derivations.reconstruct(parse_json(raw))
    acceptance = derivations.accept(rp, rv, rd, rr, definition)
    if acceptance.get("ok") is not True:
        raise ValueError("new alternative did not pass independent full-cube acceptance")
    report.update(
        status="accepted_strictly_smaller_alternative",
        full_cube_acceptance=acceptance,
        alternative_recipe_sha256=hashlib.sha256(raw).hexdigest(),
        json_bytes_saved=len(source_raw) - len(raw),
        fresh_saved_alternative_audit="pending_separate_source_free_phase",
        wall_microseconds=(time.monotonic_ns() - start) // 1000,
    )
    return report, zstd.ZstdCompressor(level=9, write_checksum=True).compress(raw)


def prepare(args):
    if args.max_work < 1:
        raise ValueError("synthesis work limit must be positive")
    source = VerifiedSource(args.source)
    try:
        output, root = args.output.resolve(), Path(__file__).resolve().parents[2]
        if output.exists() and any(output.iterdir()):
            raise ValueError("choose an empty new synthesis output; never overwrite an earlier run")
        output.mkdir(parents=True, exist_ok=True)
        snapshot, implementation, binaries = output / "implementation", {}, {}
        for directory in (root / "src/hec", root / "tools/derivation_pilot", root / "tools/corpus_derivations"):
            for path in sorted(directory.rglob("*")):
                if path.is_file() and path.suffix in (".py", ".cpp"):
                    relative = path.relative_to(root)
                    target = snapshot / relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(path, target)
                    implementation[str(relative)] = derivations.digest(path)
        # These sources must match the copied verifier/decoder binaries, not
        # whatever a later research checkout happens to contain.
        for relative in (
            "tools/verify_count_proofs.cpp",
            "tools/derivation_pilot/closure.cpp",
            "tools/corpus_derivations/audit_wide.cpp",
        ):
            path = source.root / "implementation" / relative
            target = snapshot / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
            implementation[relative] = derivations.digest(target)
        for label, info in source.binding["binaries"].items():
            target = output / label
            shutil.copy2(info["path"], target)
            binaries[label] = {"path": str(target), "sha256": derivations.digest(target)}
        binding = {
            "format": "hec-simpler-map-synthesis-run/1",
            "source": str(source.root),
            "source_records_sha256": source.records_sha256,
            "source_manifest_sha256": source.binding["manifest_sha256"],
            "source_total": EXPECTED_TOTAL,
            "prepared_utc": datetime.now(UTC).isoformat(),
            "workers": 2,
            "rss_limit_bytes": 64 * 1024**3,
            "sweeps": args.sweeps,
            "max_work": args.max_work,
            "method": METHOD,
            "implementation": implementation,
            "binaries": binaries,
        }
        derivations.save_new(output / "run-binding.json", binding)
        print(json.dumps({"prepared": True, "scope": EXPECTED_TOTAL, "output": str(output)}), flush=True)
    finally:
        source.close()


def database(output):
    db = sqlite3.connect(output / "checkpoint.sqlite3")
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA synchronous=FULL")
    db.executescript("""
      CREATE TABLE IF NOT EXISTS attempts(task INTEGER PRIMARY KEY,inequality_id TEXT UNIQUE NOT NULL,
        source_sha256 TEXT NOT NULL,status TEXT NOT NULL,source_json_bytes INTEGER NOT NULL,
        alternative_json_bytes INTEGER,alternative_sha256 TEXT,compressed BLOB,report TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS fresh(task INTEGER PRIMARY KEY,ok INTEGER NOT NULL,report TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS errors(phase TEXT NOT NULL,task INTEGER NOT NULL,error TEXT NOT NULL,
        PRIMARY KEY(phase,task));
    """)
    return db


def progress(db, output, phase, active, started):
    totals = dict(db.execute("SELECT status,COUNT(*) FROM attempts GROUP BY status"))
    attempted = sum(totals.values())
    accepted = totals.get("accepted_strictly_smaller_alternative", 0)
    fresh_count = db.execute("SELECT COUNT(*) FROM fresh WHERE ok=1").fetchone()[0]
    rss, processes = derivations.process_usage(os.getpid())
    status = {
        "sample_utc": datetime.now(UTC).isoformat(),
        "phase": phase,
        "scope": EXPECTED_TOTAL,
        "attempted": attempted,
        "remaining_attempts": EXPECTED_TOTAL - attempted,
        "statuses": totals,
        "retained_full_cube_verified_alternatives": accepted,
        "fresh_alternatives_verified": fresh_count,
        "remaining_alternative_fresh_checks": accepted - fresh_count,
        "active_tasks": sorted(active),
        "workers": 2,
        "rss_bytes": rss,
        "rss_limit_bytes": 64 * 1024**3,
        "processes": processes,
        "elapsed_seconds": int(time.monotonic() - started),
        "recorded_errors": db.execute("SELECT COUNT(*) FROM errors").fetchone()[0],
    }
    temporary = output / "progress.next.json"
    temporary.write_bytes(canonical_json(status) + b"\n")
    os.replace(temporary, output / "progress.json")
    print(json.dumps({k: v for k, v in status.items() if k != "processes"}, sort_keys=True), flush=True)


def execute(args):
    output = args.output.resolve()
    lock = (output / "controller.lock").open("a+")
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    settings = parse_json((output / "run-binding.json").read_bytes())
    if settings["workers"] != 2 or settings["source_total"] != EXPECTED_TOTAL or settings["method"] != METHOD:
        raise ValueError("frozen synthesis scope or method changed")
    for relative, sha in settings["implementation"].items():
        if derivations.digest(output / "implementation" / relative) != sha:
            raise ValueError("frozen synthesis implementation changed")
    for info in settings["binaries"].values():
        if derivations.digest(info["path"]) != info["sha256"]:
            raise ValueError("frozen synthesis native binary changed")
    source = VerifiedSource(settings["source"])
    if source.records_sha256 != settings["source_records_sha256"]:
        source.close()
        raise ValueError("completed source ledger changed since synthesis preparation")
    db = database(output)
    (output / "controller.json").write_bytes(
        canonical_json(
            {
                "pid": os.getpid(),
                "phase": args.phase,
                "birth": subprocess.check_output(["ps", "-p", str(os.getpid()), "-o", "lstart="], text=True).strip(),
            }
        )
        + b"\n"
    )
    if args.phase == "synthesize":
        done = {task for (task,) in db.execute("SELECT task FROM attempts")}
        items, action = source.items(done), attempt
    else:
        if db.execute("SELECT COUNT(*) FROM attempts").fetchone()[0] != EXPECTED_TOTAL:
            raise ValueError("fresh alternative audits require every source task to have a recorded disposition")
        done = {task for (task,) in db.execute("SELECT task FROM fresh WHERE ok=1")}

        def saved_alternatives():
            for (
                task,
                iid,
                sha,
                data,
            ) in db.execute("""SELECT task,inequality_id,alternative_sha256,compressed FROM attempts
                    WHERE status='accepted_strictly_smaller_alternative' ORDER BY task"""):
                if task in done:
                    continue
                if source.manifest[task]["inequality_id"] != iid:
                    raise ValueError("saved alternative changed the immutable source identity")
                raw = decode_frame(data)
                yield task, raw, sha, iid

        items, action = saved_alternatives(), derivations.fresh
    if args.limit is not None:
        if args.limit < 1:
            raise ValueError("explicit invocation limit must be positive")
        items = itertools.islice(items, args.limit)
    executor = ProcessPoolExecutor(max_workers=2, initializer=initialize, initargs=(settings,))
    active, started, last_guard, last_sample, exhausted = {}, time.monotonic(), 0, 0, False
    try:
        while active or not exhausted:
            if time.monotonic() - last_guard >= 2:
                derivations.enforce_rss_limit(output)
                last_guard = time.monotonic()
            while not exhausted and len(active) < 2:
                try:
                    item = next(items)
                except StopIteration:
                    exhausted = True
                    break
                active[executor.submit(action, item)] = item[0]
            if time.monotonic() - last_sample >= 30:
                progress(db, output, args.phase, active.values(), started)
                last_sample = time.monotonic()
            ready, _ = wait(active, timeout=1, return_when=FIRST_COMPLETED)
            for future in ready:
                task = active.pop(future)
                try:
                    value = future.result()
                    if args.phase == "synthesize":
                        report, packed = value
                        db.execute(
                            "INSERT INTO attempts VALUES(?,?,?,?,?,?,?,?,?)",
                            (
                                task,
                                report["inequality_id"],
                                report["source_recipe_sha256"],
                                report["status"],
                                report["source_json_bytes"],
                                report["alternative_json_bytes"],
                                report.get("alternative_recipe_sha256"),
                                packed,
                                canonical_json(report).decode(),
                            ),
                        )
                    else:
                        db.execute("INSERT OR REPLACE INTO fresh VALUES(?,1,?)", (task, canonical_json(value).decode()))
                    db.execute("DELETE FROM errors WHERE phase=? AND task=?", (args.phase, task))
                    db.commit()
                except Exception:
                    error = traceback.format_exc()
                    db.execute("INSERT OR REPLACE INTO errors VALUES(?,?,?)", (args.phase, task, error))
                    db.commit()
                    print(json.dumps({"failed_not_a_proof": task, "error": error}), flush=True)
                    raise
        progress(db, output, args.phase, (), started)
        print(json.dumps({"phase_invocation_ended": args.phase, "full_goal_complete": False}), flush=True)
    finally:
        executor.shutdown(wait=True, cancel_futures=True)
        db.close()
        source.close()
        lock.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    commands = parser.add_subparsers(dest="command", required=True)
    setup = commands.add_parser("prepare")
    setup.add_argument("--source", type=Path, required=True)
    setup.add_argument("--sweeps", type=int, choices=range(1, 9), default=2)
    setup.add_argument("--max-work", type=int, default=50_000_000)
    run = commands.add_parser("run")
    run.add_argument("--phase", choices=("synthesize", "fresh"), default="synthesize")
    run.add_argument("--limit", type=int)
    args = parser.parse_args()
    prepare(args) if args.command == "prepare" else execute(args)


if __name__ == "__main__":
    main()
