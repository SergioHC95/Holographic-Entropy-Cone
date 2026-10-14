"""Full-scope two-worker research with immutable inputs and durable receipts.

prepare snapshots code and inventories all sources; derive benchmarks exact
recipes; fresh independently checks saved winners without reading source maps.
Synthesis is a subsequent phase, never inferred from a lossless encoding pass.
"""

from __future__ import annotations

import argparse
import atexit
import fcntl
import hashlib
import json
import os
import shutil
import signal
import sqlite3
import subprocess
import time
import traceback
from collections import Counter
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from datetime import UTC, datetime
from fractions import Fraction
from pathlib import Path

import zstandard as zstd
from derivation_pilot.recipes import (
    FORMAT as PILOT_FORMAT,
)
from derivation_pilot.recipes import (
    WorkLimit,
    choice_recipe,
    closure_call,
    cut_recipe,
)
from derivation_pilot.recipes import (
    reconstruct as reconstruct_pilot,
)

from hec._count_transport import clearing_scale
from hec._count_verify import FullMapVerifier, native_supported
from hec.count_proofs import (
    FORMAT as STANDARD_FORMAT,
)
from hec.count_proofs import (
    INTEGER_ROWS,
    TRANSPORT,
    canonical_json,
    compatible_vertices,
    encode_rows,
    geometry,
    inequality_id,
    parse_json,
)
from hec.proof_store import ProofCatalog

from .diagrams import FORMAT as WIDE_FORMAT
from .diagrams import build, common_seed
from .diagrams import reconstruct as reconstruct_diagram
from .native import Auditor

SETTINGS = {}
CATALOGS = {}
NARROW = None
WIDE = None


def digest(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024**2), b""):
            result.update(block)
    return result.hexdigest()


def save_new(path, value):
    raw = canonical_json(value) + b"\n"
    if path.exists():
        if path.is_symlink() or path.read_bytes() != raw:
            raise ValueError("immutable run metadata differs: " + str(path))
        return
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def prepare(args):
    output, root = args.output.resolve(), Path(__file__).resolve().parents[2]
    if (output / "manifest.json").exists():
        raise ValueError("run is already prepared; never replace its sources/code")
    output.mkdir(parents=True, exist_ok=True)
    manifest, catalogs, ids, counts = [], {}, set(), Counter()
    paths = [("baseline", n, args.data_root / f"n={n}/proofs.json") for n in range(1, 7)]
    paths.append(("exact", 6, args.exact_catalog))
    for group, n, path in paths:
        source = ProofCatalog(path)
        catalogs[str(path.resolve())] = {"sha256": digest(path), "proofs": len(source), "shards": source.shards}
        for index, entry in enumerate(source.entries):
            iid = entry["inequality_id"]
            if iid in ids:
                raise ValueError("duplicate inequality identity across corpus sources")
            ids.add(iid)
            manifest.append(
                {
                    "group": group,
                    "n": n,
                    "catalog": str(path.resolve()),
                    "index": index,
                    "inequality_id": iid,
                    "source_proof_id": entry["proof_id"],
                    "source_frame_bytes": entry["bytes"],
                }
            )
            counts[group if n == 6 else "small-n"] += 1
    for path in sorted(args.outcomes.glob("*.json")):
        raw = path.read_bytes()
        receipt = json.loads(raw)
        if receipt.get("status") != "proved_full_cube":
            continue
        p = geometry(6, tuple(receipt["normal"]))
        iid = inequality_id(p)
        if iid in ids:
            raise ValueError("duplicate primitive proof inequality")
        ids.add(iid)
        manifest.append(
            {
                "group": "primitive",
                "n": 6,
                "index": counts["primitive"],
                "inequality_id": iid,
                "outcome": str(path.resolve()),
                "outcome_sha256": digest(path),
                "coefficients": list(map(str, p.coefficients)),
                "packed_file": receipt["packed_zstd_file"],
                "packed_sha256": receipt["packed_zstd_sha256"],
                "packed_bytes": receipt["packed_zstd_bytes"],
                "raw_sha256": receipt["packed_raw_sha256"],
                "raw_bytes": receipt["packed_raw_bytes"],
                "source_proof_id": receipt["canonical_sha256"],
                "source_frame_bytes": receipt["packed_zstd_bytes"],
            }
        )
        counts["primitive"] += 1
    if counts != Counter({"baseline": 80213, "small-n": 14, "exact": 76, "primitive": 4387}) or len(ids) != 84690:
        raise ValueError("scope differs from approved exact 84,690-proof corpus: " + str(counts))
    for i, item in enumerate(manifest):
        item["task"] = i
    snapshot = output / "implementation"
    snapshot.mkdir()
    implementation = {}
    for directory in (root / "src/hec", root / "tools/derivation_pilot", root / "tools/corpus_derivations"):
        for path in sorted(directory.rglob("*")):
            if not path.is_file() or path.suffix not in (".py", ".cpp"):
                continue
            relative = path.relative_to(root)
            target = snapshot / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
            implementation[str(relative)] = digest(path)
    narrow_source = root / "tools/verify_count_proofs.cpp"
    shutil.copy2(narrow_source, snapshot / "tools/verify_count_proofs.cpp")
    implementation["tools/verify_count_proofs.cpp"] = digest(narrow_source)
    binaries = {}
    for label, source in (("closure", args.closure), ("narrow", args.narrow), ("wide", args.wide)):
        target = output / label
        if target.exists():
            raise ValueError("binary snapshot target already exists")
        shutil.copy2(source, target)
        binaries[label] = {"path": str(target), "sha256": digest(target)}
    save_new(output / "manifest.json", manifest)
    binding = {
        "format": "hec-full-corpus-derivation-run/1",
        "prepared_utc": datetime.now(UTC).isoformat(),
        "scope_counts": dict(counts),
        "total": len(manifest),
        "manifest_sha256": digest(output / "manifest.json"),
        "source_catalogs": catalogs,
        "implementation": implementation,
        "binaries": binaries,
        "workers": 2,
        "rss_limit_bytes": 64 * 1024**3,
        "synthesis_started": False,
        "scope": "proofs; not a universal facet-rank certification",
    }
    save_new(output / "run-binding.json", binding)
    print(json.dumps({"prepared": True, "output": str(output), "counts": dict(counts)}, sort_keys=True), flush=True)


def initialize(settings):
    global SETTINGS, NARROW, WIDE
    SETTINGS = settings
    NARROW = FullMapVerifier(settings["binaries"]["narrow"]["path"])
    WIDE = Auditor(settings["binaries"]["wide"]["path"])
    atexit.register(NARROW.close)
    atexit.register(WIDE.close)


def standard(p, d, rows):
    values = rows if d == 1 else ([Fraction(v, d) for v in row] for row in rows)
    payload, actual = encode_rows(p, values, integral=d == 1)
    if actual != d:
        raise ValueError("reconstructed common seed scale differs from actual reduced denominators")
    return {
        "format": STANDARD_FORMAT,
        "inequality": p.inequality(),
        "function": {"kind": TRANSPORT, "rows": payload},
        "clearing_scale": {"value": str(clearing_scale(p, d)), "minimal": False},
    }


def reconstruct(recipe):
    if recipe.get("format") == WIDE_FORMAT:
        return reconstruct_diagram(recipe)
    if recipe.get("format") == PILOT_FORMAT:
        p, rows, _ = reconstruct_pilot(recipe, Path(SETTINGS["binaries"]["closure"]["path"]))
        return p, list(compatible_vertices(p)), 1, rows
    if recipe.get("format") == STANDARD_FORMAT and recipe.get("function", {}).get("kind") == TRANSPORT:
        return common_seed(recipe)
    raise ValueError("saved candidate has no supported exact reconstruction rule")


def accept(p, vertices, scale, rows, definition):
    if native_supported(p, INTEGER_ROWS) and scale == 1:
        return NARROW.verify(definition)
    return WIDE.verify(p, vertices, scale, rows)


def source_seed(item):
    original = None
    if item["group"] == "primitive":
        if digest(item["outcome"]) != item["outcome_sha256"] or digest(item["packed_file"]) != item["packed_sha256"]:
            raise ValueError("original primitive source/receipt changed")
        path = Path(item["packed_file"])
        if path.is_symlink() or path.stat().st_size != item["packed_bytes"]:
            raise ValueError("primitive packed payload has unsafe path or length")
        data = path.read_bytes()
        raw = zstd.ZstdDecompressor().decompress(data, max_output_size=item["raw_bytes"], allow_extra_data=False)
        if len(raw) != item["raw_bytes"] or hashlib.sha256(raw).hexdigest() != item["raw_sha256"]:
            raise ValueError("original packed raw hash/length mismatch")
        p = geometry(6, tuple(map(int, item["coefficients"])))
        vertices = list(compatible_vertices(p))
        original, rows, _ = WIDE.call(p, vertices, 1, packed=raw)
        return p, vertices, 1, rows, standard(p, 1, rows), original
    key = item["catalog"]
    if key not in CATALOGS:
        if digest(key) != SETTINGS["source_catalogs"][key]["sha256"]:
            raise ValueError("source catalog changed")
        CATALOGS[key] = ProofCatalog(key)
    source = CATALOGS[key][item["index"]]
    if CATALOGS[key].entries[item["index"]]["proof_id"] != item["source_proof_id"]:
        raise ValueError("source proof identity changed")
    p, vertices, d, rows = common_seed(source)
    return p, vertices, d, rows, source, original


def derive(item):
    start = time.monotonic_ns()
    p, vertices, d, rows, source, original = source_seed(item)
    if inequality_id(p) != item["inequality_id"]:
        raise ValueError("proof source is not the manifest inequality")
    candidates, methods = {}, {}

    def candidate(name, recipe, started):
        raw = canonical_json(recipe)
        # Decoder is handed ONLY a serialized recipe and its frozen implementation.
        # Exact seed equality binds every candidate to the same full-map rule.
        rp, rv, rd, rr = reconstruct(parse_json(raw))
        if (rp, rv, rd, rr) != (p, vertices, d, rows):
            raise ValueError("recipe changed an exact compatible source value")
        candidates[name] = raw
        methods[name] = {
            "status": "complete_exact_seed_equivalence_pending_full_audit",
            "bytes": len(raw),
            "recipe_sha256": hashlib.sha256(raw).hexdigest(),
            "construction_and_replay_us": (time.monotonic_ns() - started) // 1000,
        }

    started = time.monotonic_ns()
    fallback = standard(p, d, rows)
    candidate("explicit-compatible-seed", fallback, started)
    started = time.monotonic_ns()
    candidate("shared-compatible-dag", build(p, vertices, d, rows), started)
    eligible = d == 1 and p.L <= 17 and sum(p.beta) <= 63 and max(p.alpha, default=0) <= 32
    if eligible:
        started = time.monotonic_ns()
        result = closure_call(Path(SETTINGS["binaries"]["closure"]["path"]), p, mode="encode", rows=rows)
        candidate("choice-closure", choice_recipe(p, result), started)
        methods["choice-closure"]["encoding"] = result.stats
        started = time.monotonic_ns()
        try:
            recipe, stats = cut_recipe(p, vertices, rows, candidates=4, max_terms=512)
            candidate("cut-formulas", recipe, started)
            methods["cut-formulas"]["extraction"] = stats
        except WorkLimit as error:
            methods["cut-formulas"] = {"status": "incomplete_budget_not_a_proof", "error": str(error)}
    else:
        for name in ("choice-closure", "cut-formulas"):
            methods[name] = {
                "status": "outside_frozen_pilot_capability_not_a_proof",
                "reason": "rational seed or larger L/R; covered separately by the wide exact DAG path",
            }
    selected = min(candidates, key=lambda name: (len(candidates[name]), name))
    raw = candidates[selected]
    rp, rv, rd, rr = reconstruct(parse_json(raw))
    acceptance = accept(rp, rv, rd, rr, fallback)
    if acceptance.get("ok") is not True:
        raise ValueError("independent full-cube audit did not accept reconstructed winner")
    for name in candidates:
        methods[name]["status"] = "exact_equivalence_to_full_cube_verified_map"
    report = {
        "task": item["task"],
        "inequality_id": item["inequality_id"],
        "source_proof_id": item["source_proof_id"],
        "group": item["group"],
        "n": p.n,
        "index": item["index"],
        "L": p.L,
        "G": p.G,
        "compatible_vertices": len(vertices),
        "seed_scale": str(d),
        "methods": methods,
        "winner": selected,
        "source_json_bytes": len(canonical_json(source)),
        "normalized_seed_json_bytes": len(canonical_json(fallback)),
        "winner_json_bytes": len(raw),
        "full_cube_acceptance": acceptance,
        "original_source_audit": original,
        "fresh_saved_recipe_audit": "pending_separate_source_free_phase",
        "wall_microseconds": (time.monotonic_ns() - start) // 1000,
        "mathematical_transform": "preserve complete compatible counts; fixed cancel/fill full-cube extension",
    }
    packed = zstd.ZstdCompressor(level=9, write_checksum=True).compress(raw)
    return report, raw, packed


def fresh(item):
    task, raw, expected_hash, expected_iid = item
    if hashlib.sha256(raw).hexdigest() != expected_hash:
        raise ValueError("saved recipe hash differs from its durable checkpoint")
    p, vertices, d, rows = reconstruct(parse_json(raw))
    if inequality_id(p) != expected_iid:
        raise ValueError("saved recipe changed the manifest inequality")
    result = accept(p, vertices, d, rows, standard(p, d, rows))
    return {
        "task": task,
        "ok": True,
        "recipe_sha256": expected_hash,
        "source_tables_read": False,
        "full_cube_acceptance": result,
    }


def process_usage(root):
    text = subprocess.check_output(["ps", "-axo", "pid=,ppid=,rss=,pcpu=,command="], text=True)
    rows = []
    for line in text.splitlines():
        fields = line.strip().split(None, 4)
        if len(fields) == 5:
            try:
                rows.append((int(fields[0]), int(fields[1]), int(fields[2]) * 1024, fields[3], fields[4]))
            except ValueError:
                continue
    owned, changed = {root}, True
    while changed:
        before = len(owned)
        owned.update(pid for pid, parent, *_ in rows if parent in owned)
        changed = len(owned) != before
    selected = [row for row in rows if row[0] in owned]
    return sum(row[2] for row in selected), [
        {"pid": r[0], "ppid": r[1], "rss_bytes": r[2], "cpu_percent_sample": r[3], "command": r[4]} for r in selected
    ]


def enforce_rss_limit(output):
    rss, processes = process_usage(os.getpid())
    limit = 64 * 1024**3
    if rss <= limit and all(row["rss_bytes"] <= limit for row in processes):
        return
    # Only our snapshotted mathematical children can be interrupted. A fresh
    # PID/parent/command check prevents signalling a reused or unrelated PID.
    executables = {str(output / name) for name in ("wide", "narrow", "closure")}
    candidates = sorted(
        (row for row in processes if row["command"].split()[0] in executables),
        key=lambda row: row["rss_bytes"],
        reverse=True,
    )
    interrupted = []
    for row in candidates:
        current = (
            subprocess.run(
                ["ps", "-p", str(row["pid"]), "-o", "pid=,ppid=,command="],
                text=True,
                capture_output=True,
                check=False,
            )
            .stdout.strip()
            .split(None, 2)
        )
        if len(current) == 3 and current[:2] == [str(row["pid"]), str(row["ppid"])] and current[2] == row["command"]:
            os.kill(row["pid"], signal.SIGTERM)
            interrupted.append(row["pid"])
            break
    print(json.dumps({"rss_interruption_not_a_proof": interrupted, "rss_bytes": rss, "limit_bytes": limit}), flush=True)
    raise MemoryError("live RSS cap exceeded; own native search interrupted when identity matched; no new admission")


def snapshot(db, output, phase, total, running, started):
    stats = db.execute(
        "SELECT COUNT(*),COALESCE(SUM(edges),0),COALESCE(SUM(json_bytes),0),"
        "COALESCE(SUM(source_json_bytes),0) FROM results"
    ).fetchone()
    fresh_count = db.execute("SELECT COUNT(*) FROM fresh WHERE ok=1").fetchone()[0]
    rss, processes = process_usage(os.getpid())
    value = {
        "sample_utc": datetime.now(UTC).isoformat(),
        "phase": phase,
        "expected": total,
        "derived_and_full_cube_audited": stats[0],
        "fresh_source_free_verified": fresh_count,
        "remaining_derivation": total - stats[0],
        "remaining_fresh": total - fresh_count,
        "recorded_failures": db.execute("SELECT COUNT(*) FROM errors").fetchone()[0],
        "original_cube_edges_checked": stats[1],
        "selected_recipe_json_bytes": stats[2],
        "source_definition_json_bytes": stats[3],
        "configured_workers": 2,
        "active_tasks": sorted(running),
        "controller_plus_workers_rss_bytes": rss,
        "rss_limit_bytes": 64 * 1024**3,
        "processes": processes,
        "controller_elapsed_seconds": int(time.monotonic() - started),
        "synthesis_started": False,
    }
    temporary = output / "progress.next.json"
    temporary.write_bytes(canonical_json(value) + b"\n")
    os.replace(temporary, output / "progress.json")
    print(json.dumps({k: v for k, v in value.items() if k != "processes"}, sort_keys=True), flush=True)
    if rss > value["rss_limit_bytes"]:
        # Fail closed: external process-tree guard is required to interrupt work
        # that breaches the admitted cap; do not keep scheduling new tasks.
        raise MemoryError("live controller/worker RSS exceeds 64 GiB; stop admission")


def run(args):
    output = args.output.resolve()
    lock = (output / "controller.lock").open("a+")
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    binding = parse_json((output / "run-binding.json").read_bytes())
    if digest(output / "manifest.json") != binding["manifest_sha256"]:
        raise ValueError("durable manifest has changed")
    for relative, expected in binding["implementation"].items():
        if digest(output / "implementation" / relative) != expected:
            raise ValueError("frozen research implementation has changed")
    for info in binding["binaries"].values():
        if digest(info["path"]) != info["sha256"]:
            raise ValueError("frozen native binary has changed")
    manifest = parse_json((output / "manifest.json").read_bytes())
    if len(manifest) != 84690 or binding["workers"] != 2:
        raise ValueError("scope/worker configuration changed")
    db = sqlite3.connect(output / "checkpoint.sqlite3")
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA synchronous=FULL")
    db.executescript("""
      CREATE TABLE IF NOT EXISTS results(task INTEGER PRIMARY KEY, inequality_id TEXT UNIQUE NOT NULL,
        recipe_sha256 TEXT NOT NULL, winner TEXT NOT NULL, json_bytes INTEGER NOT NULL,
        source_json_bytes INTEGER NOT NULL, edges INTEGER NOT NULL, compressed BLOB NOT NULL, report TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS fresh(task INTEGER PRIMARY KEY,ok INTEGER NOT NULL,report TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS errors(phase TEXT NOT NULL,task INTEGER NOT NULL,error TEXT NOT NULL,
        PRIMARY KEY(phase,task));
    """)
    # The owner record is a live process identity, not authority to kill a PID.
    birth = subprocess.check_output(["ps", "-p", str(os.getpid()), "-o", "lstart="], text=True).strip()
    (output / "controller.json").write_bytes(
        canonical_json({"pid": os.getpid(), "birth": birth, "phase": args.phase, "output": str(output)}) + b"\n"
    )
    if args.phase == "derive":
        done = {row[0] for row in db.execute("SELECT task FROM results")}
        items = (
            item
            for item in manifest
            if item["task"] not in done and (args.group == "all" or item["group"] == args.group)
        )
        action = derive
    else:
        if db.execute("SELECT COUNT(*) FROM results").fetchone()[0] != len(manifest):
            raise ValueError("fresh full-scope phase requires all derivation results first")
        done = {row[0] for row in db.execute("SELECT task FROM fresh WHERE ok=1")}
        source = db.execute("SELECT task,compressed,recipe_sha256,inequality_id FROM results ORDER BY task")

        def saved_items():
            for task, data, sha, iid in source:
                if task in done:
                    continue
                if not 0 <= task < len(manifest) or manifest[task]["inequality_id"] != iid:
                    raise ValueError("checkpoint identity differs from immutable source manifest")
                raw = zstd.ZstdDecompressor().decompress(data, max_output_size=1024**3, allow_extra_data=False)
                yield task, raw, sha, manifest[task]["inequality_id"]

        items = saved_items()
        action = fresh
    if args.limit:
        import itertools

        items = itertools.islice(items, args.limit)
    started, last_sample, last_guard, active, completed = time.monotonic(), 0, 0, {}, 0
    executor = ProcessPoolExecutor(max_workers=2, initializer=initialize, initargs=(binding,))
    try:
        exhausted = False
        while active or not exhausted:
            if time.monotonic() - last_guard >= 2:
                enforce_rss_limit(output)
                last_guard = time.monotonic()
            while not exhausted and len(active) < 2:
                try:
                    item = next(items)
                except StopIteration:
                    exhausted = True
                    break
                task = item["task"] if isinstance(item, dict) else item[0]
                active[executor.submit(action, item)] = task
            if time.monotonic() - last_sample >= 30:
                snapshot(db, output, args.phase, len(manifest), active.values(), started)
                last_sample = time.monotonic()
            ready, _ = wait(active, timeout=1, return_when=FIRST_COMPLETED)
            for future in ready:
                task = active.pop(future)
                try:
                    value = future.result()
                    if args.phase == "derive":
                        report, raw, packed = value
                        db.execute(
                            "INSERT INTO results VALUES(?,?,?,?,?,?,?,?,?)",
                            (
                                task,
                                report["inequality_id"],
                                hashlib.sha256(raw).hexdigest(),
                                report["winner"],
                                len(raw),
                                report["source_json_bytes"],
                                report["full_cube_acceptance"]["checked_edges"],
                                packed,
                                canonical_json(report).decode(),
                            ),
                        )
                    else:
                        db.execute("INSERT OR REPLACE INTO fresh VALUES(?,1,?)", (task, canonical_json(value).decode()))
                    db.execute("DELETE FROM errors WHERE phase=? AND task=?", (args.phase, task))
                    db.commit()
                    completed += 1
                except Exception:
                    detail = traceback.format_exc()
                    db.execute("INSERT OR REPLACE INTO errors VALUES(?,?,?)", (args.phase, task, detail))
                    db.commit()
                    print(json.dumps({"failed_not_a_proof": task, "phase": args.phase, "error": detail}), flush=True)
                    if not args.continue_on_error:
                        raise
        snapshot(db, output, args.phase, len(manifest), (), started)
        print(
            json.dumps(
                {
                    "phase_invocation_ended": args.phase,
                    "completed_this_invocation": completed,
                    "full_goal_complete": False,
                    "synthesis_started": False,
                }
            ),
            flush=True,
        )
    finally:
        executor.shutdown(wait=True, cancel_futures=True)
        db.close()
        lock.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    commands = parser.add_subparsers(dest="command", required=True)
    inventory = commands.add_parser("prepare")
    inventory.add_argument("--data-root", type=Path, required=True)
    inventory.add_argument("--exact-catalog", type=Path, required=True)
    inventory.add_argument("--outcomes", type=Path, required=True)
    inventory.add_argument("--closure", type=Path, required=True)
    inventory.add_argument("--narrow", type=Path, required=True)
    inventory.add_argument("--wide", type=Path, required=True)
    execute = commands.add_parser("run")
    execute.add_argument("--phase", choices=("derive", "fresh"), default="derive")
    execute.add_argument("--group", choices=("all", "baseline", "exact", "primitive"), default="all")
    execute.add_argument("--limit", type=int)
    execute.add_argument("--continue-on-error", action="store_true")
    args = parser.parse_args()
    prepare(args) if args.command == "prepare" else run(args)


if __name__ == "__main__":
    main()
