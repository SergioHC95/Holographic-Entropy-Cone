"""GitHub CI entry point: authenticated reuse plus exact affected-result checks."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
from itertools import islice
from pathlib import Path

import numpy as np
from numba import njit

from .ci_baseline import SHA, GitHub, GitTree, prepare_history, verify_baseline
from .count_proofs import canonical_json, geometry, inequality_id, parse_json
from .incremental_ci import DATA_FILE, IntegrityPlan, identity


def event_base():
    path = os.environ.get("GITHUB_EVENT_PATH")
    if not path:
        return None
    event = json.loads(Path(path).read_bytes())
    if os.environ.get("GITHUB_EVENT_NAME") == "pull_request":
        return event["pull_request"]["base"]["sha"]
    if os.environ.get("GITHUB_EVENT_NAME") == "push":
        value = event.get("before", "")
        return value if SHA.fullmatch(value) and set(value) != {"0"} else None
    return None


def resolve_plan(repository, *, mode="auto", base=None, run_id=None, gate_id=None, github=None):
    current = GitTree(repository)
    current.require_clean_verifier()
    base = base or None
    evidence = None
    if mode == "auto" and run_id is None and gate_id is None:
        try:
            evidence = verify_baseline(current, current.commit, github or GitHub())
        except (ValueError, subprocess.SubprocessError, OSError, KeyError):
            pass
    if evidence is None and mode != "full" and base:
        try:
            evidence = verify_baseline(current, base, github or GitHub(), run_id=run_id, gate_id=gate_id)
        except (ValueError, subprocess.SubprocessError, OSError, KeyError) as exc:
            if mode == "incremental":
                raise ValueError("pinned incremental baseline could not be authenticated") from exc
            print(f"Full audit fallback: {type(exc).__name__}: {exc}", flush=True)
    if mode == "incremental" and evidence is None:
        raise ValueError("incremental execution requires authenticated baseline evidence")
    return IntegrityPlan(current, baseline=evidence, full=mode == "full", base=base)


def check_materialized_metadata(plan, repository):
    for name in plan.current.tree.files:
        if name == "README.md" or (name.startswith("data/") and name.endswith(".json") and "-shards/" not in name):
            path = Path(repository) / name
            if path.is_symlink() or not path.is_file() or path.read_bytes() != plan.current.tree.read(name):
                raise ValueError("materialized CI metadata differs from the immutable checkout: " + name)


def run_task(plan, task_id, repository):
    from .checks import check_stored_facets, check_stored_graphs, check_stored_rays
    from .reconstruction_checks import audit_partition, check_stored_database_bindings

    if identity(plan.document) != plan.sha256:
        raise ValueError("integrity plan changed after its digest was bound")
    matches = [task for task in plan.tasks if task["task_id"] == task_id]
    if len(matches) != 1:
        raise ValueError("task is absent, duplicated or outside the exact complete plan")
    task = matches[0]
    if identity({key: value for key, value in task.items() if key != "task_id"}) != task_id:
        raise ValueError("selected task changed after discovery")
    check_materialized_metadata(plan, repository)
    kind, n = task["kind"], task["n"]
    root = Path(repository) / "data"
    if kind == "acceptance":
        return {
            "ok": True,
            "mode": plan.mode,
            "plan_sha256": plan.sha256,
            "baseline": plan.baseline.document() if plan.baseline else None,
            "affected_and_reused_coverage": plan.totals,
            "new_mathematical_results_claimed_by_this_task": False,
        }
    options = {"shard_index": task["shard_index"], "shard_count": task["shard_count"]}
    if task["indices"] is not None:
        options["indices"] = task["indices"]
    if kind == "contractions":
        return audit_partition(
            n, root, **options, expect_proofs=task["expect_proofs"], expect_edges=task["expect_edges"]
        )
    if kind == "database-bindings":
        results = list(check_stored_database_bindings(root, n=n, **options))
    else:
        function = {"facets": check_stored_facets, "rays": check_stored_rays, "graphs": check_stored_graphs}[kind]
        results = list(
            function(root, n=n, **options, partition_mode=task["partition_mode"], expect_rows=task["expect_rows"])
        )
    if not results:
        raise ValueError("empty actual validation is not acceptance")
    return {"ok": True, "kind": kind, "n": n, "results": results, "plan_sha256": plan.sha256}


@njit(cache=True)
def _orbit_sum(rows, maps):
    total = 0
    for row in rows:
        stabilizer = 0
        for mapping in maps:
            for coordinate in range(len(row)):
                if row[coordinate] != row[mapping[coordinate]]:
                    break
            else:
                stabilizer += 1
        if stabilizer == 0 or len(maps) % stabilizer:
            raise ValueError("invalid exact orbit stabilizer")
        total += len(maps) // stabilizer
    return total


def orbit_sum(rows, n):
    from .symmetry import permutation_array

    maps, iterator, total = permutation_array(n), iter(rows), 0
    while batch := list(islice(iterator, 4096)):
        total += int(_orbit_sum(np.asarray(batch, dtype=np.int64), maps))
    return total


def _cone_rows(text):
    try:
        table = text.split("## Cone summary\n", 1)[1].split("\n## ", 1)[0]
    except IndexError as exc:
        raise ValueError("README cone table is absent") from exc
    return [line for line in table.splitlines() if line.startswith("| ")][2:]


def check_catalogue_delta(plan, repository):
    """Fresh metadata/docs checks; unchanged integration cases have prior evidence."""
    from .checks import _is_primitive_row
    from .symmetry import permuted_vectors

    if plan.mode != "incremental" or plan.catalogue_mode != "incremental" or plan.baseline is None:
        raise ValueError("full catalogue integration is required for this change")
    check_materialized_metadata(plan, repository)
    before = (plan.old.root / "README.md").read_text()
    text = (plan.current.root / "README.md").read_text()
    old_table = _cone_rows(before)
    if len(old_table) != len(plan.old.ns):
        raise ValueError("baseline README table does not cover the baseline catalogue")
    expected, totals = [], [0, 0, 0]
    for n, previous_line in zip(plan.current.ns, old_table, strict=True):
        match = re.fullmatch(
            r"\| (\d+) \| ([\d,]+) \| ([\d,]+) \| ([\d,]+) \| ([\d,]+) \| ([\d,]+) \| (complete|partial) \|",
            previous_line,
        )
        if not match or int(match[1]) != n:
            raise ValueError("baseline README row is invalid or out of order")
        facets, old_facets = plan.current.facets(n), plan.old.facets(n)
        old_set, current_set = set(old_facets), set(facets)
        if len(current_set) != len(facets):
            raise ValueError("duplicate current facet")
        lift = {1: 0, 2: 1, 3: 1, 4: 2, 5: 3, 6: 11}.get(n, 0)
        if len(facets) < lift or facets != sorted(facets[:lift]) + sorted(facets[lift:]):
            raise ValueError("current facets are not ordered lifts-first and row-lexicographically")
        for row in current_set - old_set:
            if not _is_primitive_row(row):
                raise ValueError("new facet is not primitive")
            orbit = {tuple(int(value) for value in image) for image in permuted_vectors(row, n)}
            if len(orbit & current_set) != 1:
                raise ValueError("new facet duplicates a current symmetry orbit")
        proofs, inequalities = plan.current.proofs(n)
        facet_ids = {inequality_id(geometry(n, tuple(row))) for row in facets}
        if len(facet_ids) != len(facets) or facet_ids != inequalities.entries.keys() or len(proofs) != len(facets):
            raise ValueError("current facets/inequalities/proofs are not exactly one-to-one")
        witnesses = plan.current.witnesses(n)
        if witnesses:
            witnesses.check_bindings(facet_ids)
        if int(match[2].replace(",", "")) != len(old_facets):
            raise ValueError("baseline facet count disagrees with README")
        rays, _graphs = plan.deltas[n]
        old_rays, current_rays = plan.old.catalogue(n, "rays"), plan.current.catalogue(n, "rays")
        if int(match[4].replace(",", "")) != len(old_rays):
            raise ValueError("baseline ray count disagrees with README")
        facet_images = (
            int(match[3].replace(",", "")) + orbit_sum(current_set - old_set, n) - orbit_sum(old_set - current_set, n)
        )
        ray_images = (
            int(match[5].replace(",", ""))
            + orbit_sum((current_rays.at(i) for i in rays.added), n)
            - orbit_sum((old_rays.at(i) for i in rays.removed), n)
        )
        status = "complete" if n <= 5 else "partial"
        expected.append(
            f"| {n} | {len(facets):,} | {facet_images:,} | {len(current_rays):,} | "
            f"{ray_images:,} | {len(proofs):,} | {status} |"
        )
        totals[0] += len(proofs)
        totals[1] += len(proofs.shards)
        totals[2] += sum(shard["bytes"] for shard in proofs.shards.values())
    if _cone_rows(text) != expected:
        raise ValueError("README counts differ from exact baseline-plus-changed-result orbit counts")
    for value, label in zip(totals, ("full-map proofs", "proof shards", "bytes"), strict=True):
        if f"**{value:,} {label}**" not in text:
            raise ValueError("README proof storage totals differ")
    if 6 in plan.current.ns and f"**{len(plan.current.facets(6)):,} listed facet representatives**" not in text:
        raise ValueError("README six-party count differs")
    if "exactly one full-map proof per listed facet" not in text:
        raise ValueError("README facet-only proof contract is absent")
    return {
        "ok": True,
        "mode": "fresh affected metadata plus authenticated prior catalogue integration",
        "baseline_run": plan.baseline.run_id,
        "plan_sha256": plan.sha256,
        "proof_totals": totals,
    }


def check_storage_delta(plan, repository):
    from .storage import INVENTORY_FORMAT, inspect_file, make_plan, safe_path

    if plan.mode != "incremental" or plan.baseline is None:
        raise ValueError("full storage audit is required without an authenticated baseline")
    check_materialized_metadata(plan, repository)
    old = parse_json(plan.old.tree.read("data/storage.json"))
    current = parse_json(plan.current.tree.read("data/storage.json"))
    if set(current) != {"format", "entries"} or current["format"] != INVENTORY_FORMAT:
        raise ValueError("invalid current inventory")
    previous = {entry["path"]: entry for entry in old["entries"]}
    entries = {}
    for entry in current["entries"]:
        if not isinstance(entry, dict) or set(entry) != {"path", "bytes", "sha256"}:
            raise ValueError("invalid current inventory record")
        path = entry["path"]
        if path in entries or DATA_FILE.fullmatch(path) is None or path == "data/storage.json":
            raise ValueError("invalid, repeated or recursive inventory path")
        if (
            type(entry["bytes"]) is not int
            or entry["bytes"] < 0
            or re.fullmatch(r"[0-9a-f]{64}", entry["sha256"]) is None
        ):
            raise ValueError("invalid exact inventory identity")
        entries[path] = entry
    paths = {path for path in plan.current.tree.files if path.startswith(("data/", "provenance/"))}
    if set(entries) != paths - {"data/storage.json"} or list(entries) != sorted(entries):
        raise ValueError("inventory must bind the complete ordered ordinary-Git data tree")
    metadata_plan = make_plan(repository)
    for group in ("payloads", "graph_payloads", "ray_payloads", "witness_payloads"):
        for entry in metadata_plan[group]:
            declared = {key: entry[key] for key in ("path", "sha256", "bytes")}
            if entries.get(entry["path"]) != declared:
                raise ValueError("payload catalogue declaration differs from inventory")
    verified = reused = 0
    for path, entry in entries.items():
        if previous.get(path) == entry and plan.old.tree.oid(path) == plan.current.tree.oid(path):
            reused += 1
            continue
        size, sha = inspect_file(safe_path(repository, path))
        if (size, sha) != (entry["bytes"], entry["sha256"]):
            raise ValueError("changed data bytes differ from their declared identity")
        verified += 1
    return {
        "ok": True,
        "new_or_changed_files_verified": verified,
        "byte_identical_files_reused": reused,
        "baseline_run": plan.baseline.run_id,
        "mathematical_acceptance": False,
    }


def _output(path, key, value):
    with Path(path).open("a", encoding="utf-8") as stream:
        if "\n" in value:
            marker = "HEC_" + hashlib.sha256(value.encode()).hexdigest()
            stream.write(f"{key}<<{marker}\n{value}\n{marker}\n")
        else:
            stream.write(f"{key}={value}\n")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("plan", "run", "catalogue", "storage"))
    parser.add_argument("--repository", type=Path, default=Path.cwd())
    parser.add_argument("--base")
    parser.add_argument("--mode", choices=("auto", "full", "incremental"), default="auto")
    parser.add_argument("--baseline-run", type=int, default=0)
    parser.add_argument("--baseline-gate", type=int, default=0)
    parser.add_argument("--expected-plan")
    parser.add_argument("--task")
    parser.add_argument("--github-output", type=Path)
    args = parser.parse_args(argv)
    repository = args.repository.resolve()
    if Path(__file__).resolve() != repository / "src/hec/ci_checks.py":
        parser.error("integrity CI must execute the exact checked-out implementation")
    current = GitTree(repository)
    base = args.base or event_base()
    if os.environ.get("GITHUB_ACTIONS") == "true" and current.commit != os.environ.get("GITHUB_SHA"):
        raise ValueError("checkout is not the immutable GitHub event commit")
    if base and SHA.fullmatch(base) is None:
        parser.error("baseline must be an immutable full SHA")
    prepare_history(repository, current.commit, base)
    if args.command == "plan" and args.mode == "auto" and os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch":
        args.mode = "full"
    plan = resolve_plan(
        repository, mode=args.mode, base=base, run_id=args.baseline_run or None, gate_id=args.baseline_gate or None
    )
    try:
        if args.expected_plan is not None and plan.sha256 != args.expected_plan:
            raise ValueError("recomputed CI plan differs from the immutable discovery plan")
        if args.command == "plan":
            if args.github_output:
                values = {
                    "matrix": canonical_json(plan.matrix()).decode(),
                    "plan_sha256": plan.sha256,
                    "mode": plan.mode,
                    "catalogue_mode": plan.catalogue_mode,
                    "base": plan.base or "",
                    "baseline_run": str(plan.baseline.run_id if plan.baseline else 0),
                    "baseline_gate": str(plan.baseline.gate_id if plan.baseline else 0),
                    "tested_commit": current.commit,
                    "tested_tree": current.tree,
                    "verifier": current.fingerprint(),
                    "storage_paths": plan.storage_paths(),
                    "catalogue_paths": plan.catalogue_paths(),
                }
                for key, value in values.items():
                    _output(args.github_output, key, value)
            print(
                canonical_json(
                    {
                        "mode": plan.mode,
                        "plan_sha256": plan.sha256,
                        "matrix_jobs": len(plan.tasks),
                        "coverage": plan.totals,
                    }
                ).decode()
            )
        elif args.command == "run":
            if not args.expected_plan or not args.task:
                parser.error("execution requires the exact plan digest and task identity")
            print(canonical_json(run_task(plan, args.task, repository)).decode())
        elif args.command == "catalogue":
            if not args.expected_plan:
                parser.error("catalogue verification requires the exact plan digest")
            print(canonical_json(check_catalogue_delta(plan, repository)).decode())
        else:
            if not args.expected_plan:
                parser.error("storage verification requires the exact plan digest")
            result = check_storage_delta(plan, repository)
            from .storage import history_audit

            result["history"] = history_audit(repository, trusted_ancestor=plan.baseline.accepted_commit)
            print(canonical_json(result).decode())
    finally:
        plan.close()


if __name__ == "__main__":
    main()
