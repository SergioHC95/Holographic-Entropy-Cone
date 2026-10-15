"""Quiescent, checkpoint-preserving rollout of the validated exact speedups.

No signals, adoption or competing controllers are issued here. The caller must
resolve live identities and drain the old cohort first. Every committed row
and blob remains byte-identical; missing uncommitted tasks are not proofs.
"""

from __future__ import annotations

import argparse
import ast
import fcntl
import hashlib
import shutil
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

from hec.count_proofs import canonical_json, parse_json

from . import run as derivations
from .compact_source import POLICY as INPUT_POLICY
from .continue_pipeline import idle
from .parallelize import function_hashes
from .simplify import METHOD
from .synthesize import EXPECTED_COUNTS, EXPECTED_TOTAL, OPTIMIZATION

FORMAT = "hec-exact-speedup-checkpoint-handoff/1"
TABLES = ("attempts", "fresh", "errors")
PRESERVE_FROM_PARENT = {"src/hec/reconstruction.py"}


def review_idle_change(before_path, after_path):
    """Only the reviewed additional native-helper orphan identity is allowed."""
    before, after = ast.parse(before_path.read_bytes()), ast.parse(after_path.read_bytes())
    if ast.dump(before) == ast.dump(after):
        return

    class AddHelper(ast.NodeTransformer):
        changed = 0

        def visit_Tuple(self, node):
            self.generic_visit(node)
            if all(isinstance(value, ast.Constant) for value in node.elts) and [v.value for v in node.elts] == [
                "wide",
                "narrow",
                "closure",
            ]:
                node.elts.append(ast.Constant(value="smoother"))
                self.changed += 1
            return node

    transform = AddHelper()
    before = transform.visit(before)
    if transform.changed != 1 or ast.dump(before) != ast.dump(after):
        raise ValueError("rollout changed more than the reviewed native-helper orphan check")


def review_release(parent, *, smoothing_controls=None, _expected_total=EXPECTED_TOTAL, _expected_counts=None):
    """Read-only preflight, usable BEFORE asking a healthy cohort to drain."""
    parent, root = Path(parent).resolve(), Path(__file__).resolve().parents[2]
    old = parse_json((parent / "run-binding.json").read_bytes())
    source_binding_path = Path(old["source"]) / "run-binding.json"
    source = parse_json(source_binding_path.read_bytes())
    counts = EXPECTED_COUNTS if _expected_counts is None else _expected_counts
    if (
        old["source_total"] != _expected_total
        or source["total"] != _expected_total
        or source["scope_counts"] != counts
        or old["method"] != METHOD
        or old["rss_limit_bytes"] != 64 * 1024**3
        or derivations.worker_count(old) != derivations.worker_count(source)
    ):
        raise ValueError("rollout cannot change source scope, mathematics, workers or memory caps")
    for relative, expected in old["implementation"].items():
        frozen = parent / "implementation" / relative
        if derivations.digest(frozen) != expected:
            raise ValueError("old frozen synthesis implementation changed")
        if relative in PRESERVE_FROM_PARENT:
            continue  # Copy the parent's exact file, not unrelated newer research.
        if relative == "tools/corpus_derivations/continue_pipeline.py":
            review_idle_change(frozen, root / relative)
        elif (
            relative not in {"tools/corpus_derivations/synthesize.py", "tools/corpus_derivations/speedup_rollout.py"}
            and derivations.digest(root / relative) != expected
        ):
            raise ValueError("speedup rollout changed non-scheduling mathematical/decoder code: " + relative)
    relative = "tools/corpus_derivations/synthesize.py"
    if relative in old["implementation"]:
        before, after = function_hashes(parent / "implementation" / relative), function_hashes(root / relative)
        if any(after.get(name) != value for name, value in before.items() if name not in {"attempt", "execute"}):
            raise ValueError("speedup rollout changed an unrelated existing synthesis function")
    for info in old["binaries"].values():
        if derivations.digest(info["path"]) != info["sha256"]:
            raise ValueError("independent exact primitive binary changed")
    if smoothing_controls is None and old.get("smoothing_backend") is not None:
        smoothing_controls = parent / "smoothing-controls"
    reviewed = None
    if smoothing_controls is not None:
        from .smoothing_runtime import review_controls

        reviewed = review_controls(smoothing_controls, root, source_binding_path, check_binary=True)
        if old["sweeps"] != reviewed["binding"]["sweeps"] or old["max_work"] != reviewed["binding"]["max_work"]:
            raise ValueError("reviewed native controls changed the old mathematical work/sweep settings")
    return old, reviewed, Path(smoothing_controls) if smoothing_controls is not None else None


def records(db):
    digest, counts = hashlib.sha256(), {}
    for table in TABLES:
        count = 0
        for row in db.execute(f"SELECT * FROM {table} ORDER BY " + ("phase,task" if table == "errors" else "task")):
            bound = [
                {"blob_bytes": len(value), "sha256": hashlib.sha256(value).hexdigest()}
                if isinstance(value, bytes)
                else value
                for value in row
            ]
            digest.update(canonical_json([table, bound]) + b"\n")
            count += 1
        counts[table] = count
    return counts, digest.hexdigest()


def validate_inheritance(output, binding):
    output = Path(output)
    parent = binding["checkpoint_parent"]
    receipt_path = output / "inheritance.json"
    if derivations.digest(receipt_path) != parent["receipt_sha256"]:
        raise ValueError("immutable optimization handoff receipt changed")
    receipt = parse_json(receipt_path.read_bytes())
    if (
        receipt["format"] != FORMAT
        or receipt["optimization"] != OPTIMIZATION
        or binding.get("optimization") != OPTIMIZATION
        or derivations.digest(Path(parent["root"]) / "run-binding.json") != receipt["parent_binding_sha256"]
        or parent["binding_sha256"] != receipt["parent_binding_sha256"]
        or binding["source_records_sha256"] != receipt["source_records_sha256"]
        or derivations.worker_count(binding) != receipt["workers"]
        or binding["rss_limit_bytes"] != 64 * 1024**3
    ):
        raise ValueError("optimization handoff changed its source, worker cohort or mathematical binding")
    if receipt.get("smoothing_backend") != binding.get("smoothing_backend") or receipt.get(
        "smoothing_validation"
    ) != binding.get("smoothing_validation"):
        raise ValueError("optimization handoff changed its reviewed smoothing backend")
    for relative, expected in receipt.get("preserved_inactive_parent_files", {}).items():
        old = parse_json((Path(parent["root"]) / "run-binding.json").read_bytes())
        if old["implementation"].get(relative) != expected or binding["implementation"].get(relative) != expected:
            raise ValueError("an inactive parent implementation file was not preserved exactly")
    snapshot = output / "inherited-checkpoint.sqlite3"
    if derivations.digest(snapshot) != receipt["inherited_snapshot_sha256"]:
        raise ValueError("immutable inherited optimization checkpoint changed")
    with closing(sqlite3.connect(f"file:{snapshot}?mode=ro", uri=True)) as saved:
        counts, sha = records(saved)
        if counts != receipt["inherited_counts"] or sha != receipt["inherited_records_sha256"]:
            raise ValueError("inherited optimization rows differ from their receipt")
        with closing(sqlite3.connect(f"file:{output / 'checkpoint.sqlite3'}?mode=ro", uri=True)) as live:
            for table in TABLES:
                for row in saved.execute(f"SELECT * FROM {table}"):
                    where, keys = ("phase=? AND task=?", row[:2]) if table == "errors" else ("task=?", row[:1])
                    if live.execute(f"SELECT * FROM {table} WHERE {where}", keys).fetchone() != row:
                        raise ValueError("a completed inherited optimization row/blob was removed or overwritten")
    return receipt


def fork(
    parent, output, *, parent_pgid, smoothing_controls=None, _expected_total=EXPECTED_TOTAL, _expected_counts=None
):
    parent, output = Path(parent).resolve(), Path(output).resolve()
    root = Path(__file__).resolve().parents[2]
    if (
        output.is_relative_to(parent)
        or parent.is_relative_to(output)
        or output.is_relative_to(root)
        or root.is_relative_to(output)
    ):
        raise ValueError("use a new generation outside the protected old run/worktree")
    if type(parent_pgid) is not int or parent_pgid < 1:
        raise ValueError("verified old process group identity required")
    if not idle(parent, {parent_pgid}):
        raise BlockingIOError("old synthesis controller, worker or native child remains; no competing rollout")
    with (parent / "controller.lock").open("r") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        old, smoothing_review, control_directory = review_release(
            parent,
            smoothing_controls=smoothing_controls,
            _expected_total=_expected_total,
            _expected_counts=_expected_counts,
        )
        source_binding = parse_json((Path(old["source"]) / "run-binding.json").read_bytes())
        if output.exists() and any(output.iterdir()):
            raise ValueError("choose an empty new optimization generation; never overwrite a run")
        output.mkdir(parents=True, exist_ok=True)
        implementation, binaries = {}, {}
        for folder in ("src/hec", "tools/corpus_derivations", "tools/derivation_pilot"):
            for path in sorted((root / folder).rglob("*")):
                if path.is_file() and path.suffix in (".py", ".cpp"):
                    relative = path.relative_to(root)
                    target = output / "implementation" / relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    preserved = str(relative) in PRESERVE_FROM_PARENT and str(relative) in old["implementation"]
                    shutil.copy2(parent / "implementation" / relative if preserved else path, target)
                    implementation[str(relative)] = derivations.digest(target)
        for relative, expected in old["implementation"].items():
            if relative not in implementation:
                target = output / "implementation" / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(parent / "implementation" / relative, target)
                implementation[relative] = expected
        for name, info in old["binaries"].items():
            target = output / name
            shutil.copy2(info["path"], target)
            binaries[name] = {"path": str(target), "sha256": derivations.digest(target)}
        smoothing, validation = None, None
        if smoothing_review is not None:
            from .native_smooth import POLICY as SMOOTHING_POLICY
            from .smoothing_runtime import MIN_CELLS, SOURCE

            target = output / "smoother"
            shutil.copy2(smoothing_review["binding"]["binary"]["path"], target)
            smoothing = {
                "policy": SMOOTHING_POLICY,
                "path": str(target),
                "sha256": derivations.digest(target),
                "source_sha256": implementation[SOURCE],
                "min_cells": MIN_CELLS,
            }
            validation = {key: smoothing_review[key] for key in ("binding_sha256", "report_sha256")}
            evidence = output / "smoothing-controls"
            evidence.mkdir()
            for filename in ("binding.json", "report.json"):
                shutil.copy2(control_directory / filename, evidence / filename)
        snapshot = output / "inherited-checkpoint.sqlite3"
        with closing(sqlite3.connect(f"file:{parent / 'checkpoint.sqlite3'}?mode=ro", uri=True)) as original:
            if original.execute("PRAGMA quick_check").fetchone() != ("ok",):
                raise ValueError("old checkpoint integrity check failed")
            if original.execute("SELECT COUNT(*) FROM errors").fetchone()[0]:
                raise ValueError("resolve recorded synthesis errors before rollout")
            with closing(sqlite3.connect(snapshot)) as saved:
                original.backup(saved)
        with closing(sqlite3.connect(f"file:{snapshot}?mode=ro", uri=True)) as saved:
            inherited, sha = records(saved)
            with closing(sqlite3.connect(output / "checkpoint.sqlite3")) as target:
                saved.backup(target)
        receipt = {
            "format": FORMAT,
            "created_utc": datetime.now(UTC).isoformat(),
            "parent": str(parent),
            "parent_binding_sha256": derivations.digest(parent / "run-binding.json"),
            "parent_pgid": parent_pgid,
            "source_records_sha256": old["source_records_sha256"],
            "optimization": OPTIMIZATION,
            "workers": derivations.worker_count(old),
            "inherited_counts": inherited,
            "inherited_records_sha256": sha,
            "inherited_snapshot_sha256": derivations.digest(snapshot),
            "independent_binaries_unchanged": True,
            "smoothing_mathematics_unchanged": True,
            "completed_proofs_overwritten": False,
            "preserved_inactive_parent_files": {
                path: old["implementation"][path] for path in PRESERVE_FROM_PARENT if path in old["implementation"]
            },
            "smoothing_backend": smoothing,
            "smoothing_validation": validation,
            "inflight_uncommitted_attempts": "Not counted as proofs; only missing durable tasks are retried.",
            "authorization": "User explicitly authorized replacing production with properly validated speedups.",
        }
        derivations.save_new(output / "inheritance.json", receipt)
        settings = dict(
            old,
            prepared_utc=datetime.now(UTC).isoformat(),
            optimization=OPTIMIZATION,
            implementation=implementation,
            binaries=binaries,
            source_seed_input={
                "policy": INPUT_POLICY,
                "source_binding_sha256": derivations.digest(Path(old["source"]) / "run-binding.json"),
                "source_manifest_sha256": source_binding["manifest_sha256"],
            },
            checkpoint_parent={
                "root": str(parent),
                "binding_sha256": receipt["parent_binding_sha256"],
                "receipt_sha256": derivations.digest(output / "inheritance.json"),
            },
        )
        if smoothing is not None:
            settings.update(smoothing_backend=smoothing, smoothing_validation=validation)
        else:
            settings.pop("smoothing_backend", None)
            settings.pop("smoothing_validation", None)
        derivations.save_new(output / "run-binding.json", settings)
        (output / "controller.lock").touch(exist_ok=False)
        validate_inheritance(output, settings)
        if smoothing is not None:
            from .smoothing_runtime import validate_run

            validate_run(settings, output)
        return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--parent", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--parent-pgid", required=True, type=int)
    parser.add_argument("--smoothing-controls", type=Path)
    args = parser.parse_args()
    print(
        canonical_json(
            fork(args.parent, args.output, parent_pgid=args.parent_pgid, smoothing_controls=args.smoothing_controls)
        ).decode(),
        flush=True,
    )


if __name__ == "__main__":
    main()
