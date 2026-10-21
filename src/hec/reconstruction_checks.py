"""Standard repository/CI checks for the single reconstruction proof language.

Bindings are explicitly metadata only. Full-map validity requires every
contraction partition to execute actual exhaustive audits. The standalone
database command does both; the CI plan separates them to avoid a duplicate
full-cube pass. The gate requires every disjoint mathematical partition.
"""

from __future__ import annotations

import argparse
import math
import multiprocessing
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from multiprocessing.util import Finalize
from pathlib import Path

from ._proof_partitions import partition_entries, proof_groups, proof_work
from .checks import _bounded_parallel_map, _check_facet_structure, check_worker_count, run_check
from .count_proofs import canonical_json, decimal, geometry, inequality_id
from .data import available_ns, data_path, load_hec_data
from .inequality_records import InequalityCatalog
from .proof_store import ProofCatalog
from .reconstruction_verify import ReconstructionVerifier

PROOF_TARGET, PROOF_JOB_LIMIT = 1024, 64
_process_catalog = _process_verifier = None


def _close_process_verifier():
    if _process_verifier is not None:
        _process_verifier.close()


def _initialize_audit_process(path):
    global _process_catalog, _process_verifier
    _process_catalog = ProofCatalog(path)
    _process_verifier = ReconstructionVerifier()
    Finalize(None, _close_process_verifier, exitpriority=10)


def _audit_in_process(index):
    return index, _process_catalog.audit_entry(index, _process_verifier)


def selected_ns(root, n):
    available = available_ns(root=root)
    if not available:
        raise ValueError("no exact datasets found; an empty check is not acceptance")
    if len(available) != len(set(available)):
        raise ValueError("ambiguous repeated party-count directories cannot define a complete CI plan")
    if n is not None and (type(n) is not int or n not in available):
        raise ValueError(f"no stored exact data for n={n}")
    return available if n is None else [n]


def bound_catalog(current_n, root):
    path = data_path(current_n, "contractions", root=root)
    proofs, inequalities = ProofCatalog(path), InequalityCatalog(path.with_name("inequalities.json"))
    if not len(proofs):
        raise ValueError("empty authoritative exact catalogue is not acceptance")
    inequalities.check_bindings(proofs)
    if any(entry["n"] != current_n for entry in inequalities.entries.values()):
        raise ValueError("inequality/proof catalogue is stored under the wrong party count")
    return proofs, inequalities


def check_stored_database_bindings(root=None, *, n=None, shard_index=0, shard_count=1):
    """Check indexes and known facet-list structure, NOT map validity or rank."""
    if type(shard_index) is not int or type(shard_count) is not int or (shard_index, shard_count) != (0, 1):
        raise ValueError("global database bindings cannot be split into shards")
    for current_n in selected_ns(root, n):
        proofs, inequalities = bound_catalog(current_n, root)
        facets = load_hec_data(current_n, "facets", root=root)
        _check_facet_structure(current_n, facets)
        facet_ids = {inequality_id(geometry(current_n, tuple(row))) for row in facets}
        if len(facet_ids) != len(facets) or facet_ids != inequalities.entries.keys():
            raise ValueError("known facets and proof inequalities must have exactly the same unique identities")
        yield (
            f"n={current_n}: {len(inequalities.entries)} inequality/{len(proofs)} proof index bindings; "
            f"{len(facets)} facets in exact one-to-one correspondence; "
            "metadata only, no mathematical audit or rank claim"
        )


def _geometry(entry):
    return geometry(entry["n"], tuple(map(decimal, entry["coefficients"])))


def audit_partition(current_n, root=None, *, shard_index=0, shard_count=1, expect_proofs=None, expect_edges=None):
    """Actually audit one disjoint complete-map partition; never cached flags."""
    selected_ns(root, current_n)
    catalog, inequalities = bound_catalog(current_n, root)
    selected = partition_entries(catalog, inequalities, shard_index, shard_count)
    # Start expensive complete maps first, so one late map cannot strand the
    # other bounded workers. This changes order only, never proof ownership.
    selected.sort(
        key=lambda index: (
            -proof_work(inequalities.entries[catalog.entries[index]["inequality_id"]]),
            catalog.entries[index]["proof_id"],
        )
    )
    expected_edges = sum(
        p.L * (p.vertices // 2)
        for index in selected
        for p in [_geometry(inequalities.entries[catalog.entries[index]["inequality_id"]])]
    )
    for claimed, actual in ((expect_proofs, len(selected)), (expect_edges, expected_edges)):
        if claimed is not None and (type(claimed) is not int or claimed != actual):
            raise ValueError("planned exact proof/edge coverage differs from the selected partition")
    workers = min(4, check_worker_count())
    verifier = None

    def check(index):
        nonlocal verifier
        if verifier is None:
            verifier = ReconstructionVerifier()
        return index, catalog.audit_entry(index, verifier)

    wanted, seen, edges, vertices = set(selected), set(), 0, 0
    print(
        f"n={current_n} partition {shard_index + 1}/{shard_count}: actual exact full-map audit "
        f"of {len(selected):,} proofs with {workers} workers",
        flush=True,
    )
    try:
        pool = (
            ThreadPoolExecutor(max_workers=1)
            if workers == 1
            else ProcessPoolExecutor(
                max_workers=workers,
                mp_context=multiprocessing.get_context("spawn"),
                initializer=_initialize_audit_process,
                initargs=(catalog.path,),
            )
        )
        with pool:
            function = check if workers == 1 else _audit_in_process
            for index, result in _bounded_parallel_map(pool, function, selected, max_pending=2 * workers):
                if type(index) is not int or index not in wanted or index in seen:
                    raise ValueError("duplicate or out-of-partition actual audit result")
                expected = catalog.entries[index]
                if (
                    result.get("proof_id") != expected["proof_id"]
                    or result.get("inequality_id") != expected["inequality_id"]
                ):
                    raise ValueError("actual audit result differs from its planned proof/inequality identity")
                seen.add(index)
                edges += result["checked_edges"]
                vertices += result["checked_vertices"]
                if len(seen) % 1000 == 0:
                    print(f"n={current_n}: audited {len(seen):,}/{len(selected):,} selected proofs", flush=True)
    finally:
        if verifier is not None:
            verifier.close()
    if seen != wanted or edges != expected_edges:
        raise ValueError("incomplete actual full-cube audit coverage")
    return {
        "ok": True,
        "n": current_n,
        "scope": "original-cube-all-edges",
        "proofs": len(seen),
        "checked_vertices": vertices,
        "checked_edges": edges,
        "source_tables_read": False,
        "stored_acceptance_flags_used": False,
        "facethood_or_rank_claims_established": False,
    }


def check_stored_contractions(root=None, *, n=None, shard_index=0, shard_count=1):
    for current_n in selected_ns(root, n):
        result = audit_partition(current_n, root, shard_index=shard_index, shard_count=shard_count)
        yield (
            f"n={current_n}: {result['proofs']} mathematically valid full maps; "
            f"{result['checked_edges']} original cube edges"
        )


def check_stored_facet_database_format(root=None, *, n=None, shard_index=0, shard_count=1):
    """Standalone integrity remains mathematical: bindings AND all full maps."""
    yield from check_stored_database_bindings(root, n=n, shard_index=shard_index, shard_count=shard_count)
    yield from check_stored_contractions(root, n=n)
    yield "complete full-map audits and exact inequality/proof bindings; no facet/rank claim inferred from validity."


def ci_matrix(root=None):
    """Cover every complete proof exactly once, plus all other data gates.

    The entire matrix, including every contraction partition, must pass at
    one immutable checkout. Metadata-only database jobs confer no validity.
    This planner reads no proof payloads and fetches nothing.
    """
    ns = selected_ns(root, None)
    tasks = []
    priorities = []
    for current_n in reversed(ns):
        catalog, inequalities = bound_catalog(current_n, root)
        counts = {}
        from .graph_store import GraphCatalog

        counts["graphs"] = len(GraphCatalog(data_path(current_n, "graphs", root=root)))
        for kind in ("facets", "rays"):
            # Rays may use the bounded, content-addressed catalogue format.
            # The standard data reader validates its index without loading all
            # payloads, which preserves this planner's metadata-only scope.
            counts[kind] = len(load_hec_data(current_n, kind, root=root))
        if counts["graphs"] != counts["rays"]:
            raise ValueError("CI graph/ray coverage counts disagree")
        counts.update(contractions=len(catalog), **{"database-bindings": len(inequalities.entries)})
        audit_count = min(PROOF_JOB_LIMIT, max(1, math.ceil(len(catalog) / PROOF_TARGET)), len(catalog))
        owned_entries = proof_groups(catalog, inequalities, audit_count)
        for kind in ("facets", "contractions", "database-bindings", "graphs", "rays"):
            groups = audit_count if kind == "contractions" else 1
            if kind == "facets":
                groups = min(8, max(1, math.ceil(counts[kind] / 10_000)))
            elif kind in ("graphs", "rays"):
                groups = min(16, max(1, math.ceil(counts[kind] / 25_000)))
            for group in range(groups):
                task = {
                    "kind": kind,
                    "n": current_n,
                    "shard_index": group,
                    "shard_count": groups,
                    "label": f"{kind} (n={current_n}, partition {group + 1}/{groups})",
                    "checkout_paths": "",
                }
                if kind == "contractions":
                    indices = owned_entries[group]
                    owned_shards = {catalog.entries[index]["shard"] for index in indices}
                    task["checkout_paths"] = "\n".join(
                        f"/data/n={current_n}/proof-shards/{key}.proofpack" for key in sorted(owned_shards)
                    )
                    task["expect_proofs"] = len(indices)
                    task["expect_edges"] = sum(
                        p.L * (p.vertices // 2)
                        for index in indices
                        for p in [_geometry(inequalities.entries[catalog.entries[index]["inequality_id"]])]
                    )
                    priority = sum(
                        proof_work(inequalities.entries[catalog.entries[index]["inequality_id"]]) for index in indices
                    )
                elif kind == "facets":
                    # Cubic exact elimination is independently expensive. Give
                    # rank partitions early slots alongside the largest maps,
                    # rather than placing every rank job at the queue's tail.
                    owned_rows = (counts[kind] + groups - 1 - group) // groups
                    priority = 3 * owned_rows * ((1 << current_n) - 1) ** 3 + (1 << 18)
                elif kind == "database-bindings":
                    # Global symmetry/normalization checks must not become a
                    # late tail after all independent map jobs are finished.
                    priority = counts[kind] * ((1 << current_n) - 1) * math.factorial(current_n + 1)
                else:
                    priority = 0
                tasks.append(task)
                priorities.append(priority)
    if len(tasks) > 256:
        raise ValueError("complete CI plan exceeds the matrix limit; repartition without dropping proofs")
    # Queue the longest estimated complete-map jobs before smaller work. The
    # executor can interleave jobs; the final gate still requires every row.
    ordered = sorted(zip(priorities, tasks, strict=True), key=lambda item: -item[0])
    return {"include": [task for _, task in ordered]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "kind", choices=("contractions", "database", "database-bindings", "facets", "rays", "graphs", "plan")
    )
    parser.add_argument("--root", type=Path, help="data/n=* parent, not a repository root")
    parser.add_argument("--n", type=int)
    parser.add_argument("--shard-index", type=int, default=0)
    parser.add_argument("--shard-count", type=int, default=1)
    parser.add_argument("--expect-proofs", type=int)
    parser.add_argument("--expect-edges", type=int)
    parser.add_argument("--github-output", type=Path)
    args = parser.parse_args(argv)
    if args.kind == "plan":
        if args.n is not None or (args.shard_index, args.shard_count) != (0, 1):
            parser.error("the CI plan must include every dataset and proof partition")
        if args.expect_proofs is not None or args.expect_edges is not None:
            parser.error("expected mathematical coverage belongs only to contraction audit partitions")
        value = ci_matrix(args.root)
        raw = canonical_json(value).decode()
        if args.github_output is not None:
            with args.github_output.open("a", encoding="utf-8") as stream:
                stream.write("matrix=" + raw + "\n")
        print(raw)
    elif args.kind == "contractions":
        if args.n is None:
            parser.error("contractions CLI requires one explicit --n; use plan for complete CI coverage")
        result = audit_partition(
            args.n,
            args.root,
            shard_index=args.shard_index,
            shard_count=args.shard_count,
            expect_proofs=args.expect_proofs,
            expect_edges=args.expect_edges,
        )
        print(canonical_json(result).decode())
    else:
        if args.expect_proofs is not None or args.expect_edges is not None:
            parser.error("expected mathematical coverage belongs only to contraction audit partitions")
        from .checks import check_stored_facets, check_stored_graphs, check_stored_rays

        function = {
            "database": check_stored_facet_database_format,
            "database-bindings": check_stored_database_bindings,
            "facets": check_stored_facets,
            "rays": check_stored_rays,
            "graphs": check_stored_graphs,
        }[args.kind]
        run_check(function(args.root, n=args.n, shard_index=args.shard_index, shard_count=args.shard_count))


if __name__ == "__main__":
    main()
