"""Fork a quiescent checkpoint into an explicitly approved larger worker cohort.

No live run, completed receipt, mathematical implementation or verifier binary
is overwritten. The inherited prefix remains independently auditable, and ALL
saved definitions must still pass the later source-free original-cube audit.
"""

from __future__ import annotations

import argparse
import ast
import fcntl
import hashlib
import json
import shutil
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

from hec.count_proofs import canonical_json, parse_json

from . import run as derivations

FORMAT = "hec-parallelism-checkpoint-handoff/1"
ORCHESTRATION = {"prepare", "run", "main", "snapshot"}
CONTROL_FILES = {
    "tools/corpus_derivations/run.py",
    "tools/corpus_derivations/synthesize.py",
    "tools/corpus_derivations/package_results.py",
    "tools/corpus_derivations/continue_pipeline.py",
    "tools/corpus_derivations/parallelize.py",
}


def function_hashes(path):
    tree = ast.parse(path.read_text())
    return {
        node.name: hashlib.sha256(ast.dump(node, include_attributes=False).encode()).hexdigest()
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def unchanged_mathematics(parent, binding, checkout):
    verified = {}
    for relative, expected in binding["implementation"].items():
        frozen = parent / "implementation" / relative
        if derivations.digest(frozen) != expected:
            raise ValueError("parent frozen implementation changed")
        if relative not in CONTROL_FILES:
            if derivations.digest(checkout / relative) != expected:
                raise ValueError("parallelism-only handoff cannot change mathematical code: " + relative)
            verified[relative] = expected
    relative = "tools/corpus_derivations/run.py"
    before, after = function_hashes(parent / "implementation" / relative), function_hashes(checkout / relative)
    mathematical = {name: sha for name, sha in before.items() if name not in ORCHESTRATION}
    if any(after.get(name) != sha for name, sha in mathematical.items()):
        raise ValueError("parallelism-only handoff changed an existing non-orchestration function")
    return {"unchanged_files": verified, "unchanged_run_functions": mathematical}


def records_digest(db):
    digest, count = hashlib.sha256(), 0
    for row in db.execute("SELECT * FROM results ORDER BY task"):
        if len(row) != 9:
            raise ValueError("unexpected parent result schema")
        value = [*row[:7], hashlib.sha256(row[7]).hexdigest(), hashlib.sha256(row[8].encode()).hexdigest()]
        digest.update(canonical_json(value) + b"\n")
        count += 1
    return count, digest.hexdigest()


def validate_inheritance(output, binding):
    parent_info = binding["checkpoint_parent"]
    receipt_path = output / "inheritance.json"
    if derivations.digest(receipt_path) != parent_info["receipt_sha256"]:
        raise ValueError("immutable handoff receipt changed")
    receipt = parse_json(receipt_path.read_bytes())
    parent = Path(parent_info["root"])
    if (
        receipt["format"] != FORMAT
        or derivations.digest(parent / "run-binding.json") != receipt["parent_binding_sha256"]
        or receipt["parent_binding_sha256"] != parent_info["binding_sha256"]
        or receipt["manifest_sha256"] != binding["manifest_sha256"]
        or receipt["new_workers"] != derivations.worker_count(binding)
    ):
        raise ValueError("handoff binding differs from preserved parent or child")
    snapshot = output / "inherited-checkpoint.sqlite3"
    if derivations.digest(snapshot) != receipt["inherited_snapshot_sha256"]:
        raise ValueError("preserved inherited checkpoint changed")
    with closing(sqlite3.connect(f"file:{snapshot}?mode=ro", uri=True)) as old:
        count, sha = records_digest(old)
        if count != receipt["inherited_results"] or sha != receipt["inherited_results_sha256"]:
            raise ValueError("inherited result inventory differs from the handoff receipt")
        with closing(sqlite3.connect(f"file:{output / 'checkpoint.sqlite3'}?mode=ro", uri=True)) as current:
            for row in old.execute("SELECT * FROM results ORDER BY task"):
                if current.execute("SELECT * FROM results WHERE task=?", (row[0],)).fetchone() != row:
                    raise ValueError("a completed inherited proof/receipt was removed or overwritten")
    return receipt


def fork(args):
    from .continue_pipeline import idle

    parent, output = args.source.resolve(), args.output.resolve()
    if parent == output or output.is_relative_to(parent) or parent.is_relative_to(output):
        raise ValueError("a new immutable generation must be outside the parent run")
    if args.parent_pgid < 1:
        raise ValueError("a verified positive parent process-group identity is required")
    if output.exists() and any(output.iterdir()):
        raise ValueError("choose a new empty output; never overwrite a prior run")
    # Recorded PGID comes from the live owner inspected BEFORE the handoff.
    if not idle(parent, {args.parent_pgid}):
        raise RuntimeError("parent controller or surviving worker/session remains; no fork admitted")
    with (parent / "controller.lock").open("r") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        old = parse_json((parent / "run-binding.json").read_bytes())
        if old["total"] != 84690 or derivations.worker_count(old) >= args.workers:
            raise ValueError("handoff must increase the worker cohort without narrowing the corpus")
        if old["rss_limit_bytes"] != 64 * 1024**3:
            raise ValueError("parent memory cap differs from the approved 64 GiB")
        if derivations.digest(parent / "manifest.json") != old["manifest_sha256"]:
            raise ValueError("parent manifest changed")
        manifest = parse_json((parent / "manifest.json").read_bytes())
        if (
            len(manifest) != 84690
            or [item["task"] for item in manifest] != list(range(84690))
            or len({item["inequality_id"] for item in manifest}) != 84690
        ):
            raise ValueError("parent manifest does not cover the complete unique corpus")
        root = Path(__file__).resolve().parents[2]
        equivalence = unchanged_mathematics(parent, old, root)
        output.mkdir(parents=True, exist_ok=True)
        shutil.copy2(parent / "manifest.json", output / "manifest.json")
        implementation, binaries = {}, {}
        for directory in (root / "src/hec", root / "tools/derivation_pilot", root / "tools/corpus_derivations"):
            for path in sorted(directory.rglob("*")):
                if path.is_file() and path.suffix in (".py", ".cpp"):
                    relative = path.relative_to(root)
                    target = output / "implementation" / relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(path, target)
                    implementation[str(relative)] = derivations.digest(target)
        for relative in (
            "tools/verify_count_proofs.cpp",
            "tools/derivation_pilot/closure.cpp",
            "tools/corpus_derivations/audit_wide.cpp",
        ):
            target = output / "implementation" / relative
            shutil.copy2(parent / "implementation" / relative, target)
            implementation[relative] = derivations.digest(target)
        for name, info in old["binaries"].items():
            if derivations.digest(info["path"]) != info["sha256"]:
                raise ValueError("parent native binary changed")
            target = output / name
            shutil.copy2(info["path"], target)
            binaries[name] = {"path": str(target), "sha256": derivations.digest(target)}
        snapshot = output / "inherited-checkpoint.sqlite3"
        with closing(sqlite3.connect(f"file:{parent / 'checkpoint.sqlite3'}?mode=ro", uri=True)) as source:
            if source.execute("SELECT COUNT(*) FROM errors").fetchone()[0]:
                raise ValueError("resolve parent errors before inheriting completed results")
            with closing(sqlite3.connect(snapshot)) as saved:
                source.backup(saved)
        with closing(sqlite3.connect(f"file:{snapshot}?mode=ro", uri=True)) as saved:
            count, records_sha = records_digest(saved)
            for task, iid in saved.execute("SELECT task,inequality_id FROM results"):
                if not 0 <= task < len(manifest) or manifest[task]["inequality_id"] != iid:
                    raise ValueError("inherited result differs from the immutable corpus identity")
            with closing(sqlite3.connect(output / "checkpoint.sqlite3")) as target:
                saved.backup(target)
        receipt = {
            "format": FORMAT,
            "created_utc": datetime.now(UTC).isoformat(),
            "parent": str(parent),
            "parent_binding_sha256": derivations.digest(parent / "run-binding.json"),
            "parent_pgid": args.parent_pgid,
            "manifest_sha256": old["manifest_sha256"],
            "old_workers": old["workers"],
            "new_workers": args.workers,
            "inherited_results": count,
            "inherited_results_sha256": records_sha,
            "inherited_snapshot_sha256": derivations.digest(snapshot),
            "mathematical_equivalence": equivalence,
            "authorization": (
                "User explicitly requested eight corpus workers on 2026-10-14, "
                "leaving other jobs running; same 64 GiB caps."
            ),
            "original_proofs_overwritten": False,
            "inflight_uncommitted_work": "not counted as a proof; missing tasks are retried from the checkpoint",
            "source_free_full_cube_reverification": "still required for every saved definition",
        }
        derivations.save_new(output / "inheritance.json", receipt)
        binding = dict(old)
        binding.update(
            prepared_utc=datetime.now(UTC).isoformat(),
            implementation=implementation,
            binaries=binaries,
            workers=args.workers,
            checkpoint_parent={
                "root": str(parent),
                "binding_sha256": receipt["parent_binding_sha256"],
                "receipt_sha256": derivations.digest(output / "inheritance.json"),
            },
        )
        derivations.save_new(output / "run-binding.json", binding)
        validate_inheritance(output, binding)
        print(
            json.dumps(
                {
                    "prepared": True,
                    "workers": args.workers,
                    "inherited_results": count,
                    "remaining": 84690 - count,
                    "output": str(output),
                }
            ),
            flush=True,
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--parent-pgid", required=True, type=int)
    parser.add_argument("--workers", choices=(4, 8), default=8, type=int)
    fork(parser.parse_args())


if __name__ == "__main__":
    main()
