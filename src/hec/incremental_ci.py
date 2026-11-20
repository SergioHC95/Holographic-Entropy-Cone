"""Content-identity and dependency closure for incremental integrity audits.

This module never treats a plan or a hash as new mathematical acceptance.
Unchanged results require an authenticated prior integrity run; selected
results still execute the standard exact validators with actual coverage.
"""

from __future__ import annotations

import hashlib
import heapq
import json
import math
import re
import tempfile
from bisect import bisect_left, bisect_right
from dataclasses import dataclass
from pathlib import Path

from ._proof_partitions import proof_work
from .ci_baseline import GitTree
from .count_proofs import geometry, inequality_id
from .data import load_hec_data
from .facet_witnesses import FacetWitnessCatalog
from .graph_store import GraphCatalog
from .graph_store import _exact_payload as graph_payload
from .inequality_records import InequalityCatalog
from .proof_store import ProofCatalog
from .ray_store import RayCatalog
from .ray_store import _exact_payload as ray_payload
from .reconstruction_checks import ci_matrix

# The complete catalogue tests also pin these literal regression inputs. A
# membership change needs that test (including uniqueness), not a count delta.
CERTIFIED_RAY_N6 = "39484b4dc968ef126c6fa47184797b727397c291fb831c2105dee3ba703cad8f"
GRAPH_FINDER_CASES_N6 = (
    ("c5cb8bf65b3ad299ab6a4ca307b6d3cbbd449da30b9c80590fd017fa5e3e76aa", 11),
    ("6b9933a923d299a26d6c12e6089ad29186dabb16b498a9617d9c8da49769ccd1", 9),
    ("4388ecb359d4478911f81ced52c033368d3753ac941657edace90389956525fd", 11),
    ("ea49fdcd8e0d15ca4e5686fedbf14ae935863894b9d6b89d34c99a7ca52b6756", 10),
)
_CATALOGUE_RAY_CONTROLS = frozenset((6, key) for key in (CERTIFIED_RAY_N6, *(key for key, _ in GRAPH_FINDER_CASES_N6)))

METADATA = re.compile(r"data/n=([1-9][0-9]*)/(facets|rays|graphs|inequalities|proofs|facet-witnesses)\.json\Z")
DATA_FILE = re.compile(
    r"data/(?:storage\.json|n=[1-9][0-9]*/(?:(?:facets|rays|graphs|inequalities|proofs|facet-witnesses)\.json"
    r"|(?:ray|graph)-shards/[0-9a-f]{64}\.json|proof-shards/[0-9a-f]{64}\.proofpack"
    r"|witness-shards/[0-9a-f]{64}\.witnesspack))\Z"
)


def identity(value):
    # Scientific row vectors contain signed integers; proof-language JSON
    # reserves numeric literals for nonnegative indices and is not its codec.
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode()
    return hashlib.sha256(raw).hexdigest()


def orbit_key(row, n):
    from .symmetry import canonical_vector

    divisor = math.gcd(*(abs(int(value)) for value in row)) or 1
    return tuple(int(value) for value in canonical_vector(tuple(value // divisor for value in row), n))


def _framed_graph_rows(raw, count):
    """Find writer record boundaries without building millions of graph objects."""
    if not raw.startswith(b"[\n  {") or not raw.endswith(b"}\n]\n") or raw.count(b"\n") != count + 2:
        return None
    rows = raw[4:-3].split(b",\n  ")
    if len(rows) != count or any(
        row[:1] != b"{" or row[-1:] != b"}" or row.count(b"{") != 1 or row.count(b"}") != 1 for row in rows
    ):
        return None
    return rows


def _same_graph(before, after):
    if isinstance(before, bytes) and isinstance(after, bytes) and before == after:
        # Both are isolated records, and the baseline's bytes were accepted.
        return True
    if isinstance(before, bytes):
        before = graph_payload(b"[" + before + b"]")[0]
    if isinstance(after, bytes):
        after = graph_payload(b"[" + after + b"]")[0]
    # Python treats True == 1; only the exact integer is an accepted weight.
    return before == after and all(type(weight) is int for weight in after["weights"])


class Catalogue:
    def __init__(self, snapshot, n, kind):
        self.snapshot, self.n, self.kind = snapshot, n, kind
        path = snapshot.data / f"n={n}" / f"{kind}.json"
        self.rows = None
        if kind == "rays":
            data = load_hec_data(n, kind, root=snapshot.data)
            if not isinstance(data, RayCatalog):
                self.rows = data
        else:
            data = GraphCatalog(path)
        self.count = len(data)
        self.segments, self.ends = [], []
        if self.rows is None:
            start = 0
            for shard in data.shards:
                relative = f"data/n={n}/{shard.path}"
                token = (shard.sha256, shard.bytes, shard.count, snapshot.tree.oid(relative))
                if token[-1] is None:
                    raise ValueError("referenced payload is missing from Git")
                self.segments.append((start, start + shard.count, token, relative))
                start += shard.count
                self.ends.append(start)
        self.cached = None
        self.comparison_cache = None

    def __len__(self):
        return self.count

    def shard_bytes(self, segment):
        _, _, token, path = segment
        raw = self.snapshot.tree.read(path)
        if len(raw) != token[1] or hashlib.sha256(raw).hexdigest() != token[0]:
            raise ValueError("changed catalogue shard differs from its declared content identity")
        return raw

    def values(self, segment):
        start, stop, _, _ = segment
        raw = self.shard_bytes(segment)
        rows = ray_payload(raw, self.n) if self.kind == "rays" else graph_payload(raw)
        if len(rows) != stop - start:
            raise ValueError("changed shard lost declared row coverage")
        return rows

    def at(self, index):
        if not 0 <= index < len(self):
            raise ValueError("catalogue row outside current context")
        if self.rows is not None:
            return self.rows[index]
        ordinal = bisect_right(self.ends, index)
        return self.segment_rows(ordinal)[index - self.segments[ordinal][0]]

    def segment_rows(self, ordinal):
        if self.cached is None or self.cached[0] != ordinal:
            self.cached = ordinal, self.values(self.segments[ordinal])
        return self.cached[1]

    def graph_comparison_rows(self, ordinal):
        if self.comparison_cache is None or self.comparison_cache[0] != ordinal:
            segment = self.segments[ordinal]
            count = segment[1] - segment[0]
            raw = self.shard_bytes(segment)
            rows = _framed_graph_rows(raw, count)
            if rows is None:
                rows = graph_payload(raw)
                if len(rows) != count:
                    raise ValueError("changed shard lost declared row coverage")
            self.comparison_cache = ordinal, rows
        return self.comparison_cache[1]

    def location(self, index):
        if not 0 <= index < len(self):
            return None
        if self.rows is not None:
            return identity(self.rows[index])
        ordinal = bisect_right(self.ends, index)
        segment = self.segments[ordinal]
        return segment[2], index - segment[0]

    def blocks(self):
        if self.rows is None:
            return self.segments
        path = f"data/n={self.n}/rays.json"
        return [(0, len(self), ("inline", self.snapshot.tree.oid(path)), path)]

    def block_rows(self, block):
        return self.rows if self.rows is not None else self.values(block)


@dataclass
class RowDelta:
    graphs: list[int]
    added: list[int]
    removed: list[int]
    retained: bool


def _changed_graph_rows(old, current, start, stop, previous):
    """Compare graphs only after identifying the old row for the exact same ray."""
    while start < stop:
        a = bisect_right(old.ends, previous)
        b = bisect_right(current.ends, start)
        a_start, a_stop, a_token, _ = old.segments[a]
        b_start, b_stop, b_token, _ = current.segments[b]
        count = min(stop - start, a_stop - previous, b_stop - start)
        a_offset, b_offset = previous - a_start, start - b_start
        if a_token != b_token or a_offset != b_offset:
            left, right = old.graph_comparison_rows(a), current.graph_comparison_rows(b)
            for offset in range(count):
                if not _same_graph(left[a_offset + offset], right[b_offset + offset]):
                    yield start + offset
        start += count
        previous += count


def paired_delta(old_rays, rays, old_graphs, graphs):
    """Bind retained results to the exact ray AND graph, independent of row position."""
    if len(old_rays) != len(old_graphs) or len(rays) != len(graphs):
        raise ValueError("graph/ray coverage differs")
    old_blocks, blocks = old_rays.blocks(), rays.blocks()
    old_offsets = {token: start for start, _, token, _ in old_blocks}
    common = old_offsets.keys() & {token for _, _, token, _ in blocks}
    previous_rows, repeats = {}, {}
    for block in old_blocks:
        if block[2] in common:
            continue
        for index, row in enumerate(old_rays.block_rows(block), start=block[0]):
            key = identity(row)
            if key in previous_rows:
                repeats.setdefault(key, []).append(index)
            else:
                previous_rows[key] = index

    added, changed = [], []
    for block in blocks:
        start, stop, token, _ = block
        if token in common:
            changed.extend(_changed_graph_rows(old_graphs, graphs, start, stop, old_offsets[token]))
            continue
        run = None
        for index, row in enumerate(rays.block_rows(block), start=start):
            key = identity(row)
            extras = repeats.get(key)
            previous = extras.pop() if extras else previous_rows.pop(key, None)
            if previous is not None and run is not None and previous - run[1] == index - run[0]:
                continue
            if run is not None:
                changed.extend(_changed_graph_rows(old_graphs, graphs, run[0], index, run[1]))
                run = None
            if previous is None:
                added.append(index)
                changed.append(index)
            else:
                run = index, previous
        if run is not None:
            changed.extend(_changed_graph_rows(old_graphs, graphs, run[0], stop, run[1]))
    removed = sorted([*previous_rows.values(), *(i for rows in repeats.values() for i in rows)])
    return RowDelta(changed, added, removed, not removed)


def _catalogue_controls_changed(old, current, delta):
    n = current.n
    return (
        any((n, identity(old.at(i))) in _CATALOGUE_RAY_CONTROLS for i in delta.removed)
        or any((n, identity(current.at(i))) in _CATALOGUE_RAY_CONTROLS for i in delta.added)
        or (n == 6 and any(identity(current.at(i)) == CERTIFIED_RAY_N6 for i in delta.graphs))
    )


class Snapshot:
    def __init__(self, tree):
        self.tree = tree
        for path, (mode, kind, _oid) in tree.entries.items():
            if path.startswith(("data/", "provenance/")) and (
                DATA_FILE.fullmatch(path) is None or kind != "blob" or mode not in ("100644", "100755")
            ):
                raise ValueError("unrecognized or non-regular scientific data path: " + path)
        self.temporary = tempfile.TemporaryDirectory(prefix="hec-ci-metadata-")
        self.root = Path(self.temporary.name)
        self.data = self.root / "data"
        try:
            self._populate(tree)
        except BaseException:
            self.temporary.cleanup()
            raise
        self._facets, self._proofs, self._catalogues, self._witnesses = {}, {}, {}, {}

    def _populate(self, tree):
        self.ns = sorted({int(match[1]) for name in tree.files if (match := METADATA.fullmatch(name))})
        if not self.ns:
            raise ValueError("empty repository datasets are not acceptance")
        for name in tree.files:
            if METADATA.fullmatch(name) or name in ("data/storage.json", "README.md"):
                path = self.root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(tree.read(name))

    def close(self):
        self.temporary.cleanup()

    def facets(self, n):
        if n not in self._facets:
            self._facets[n] = load_hec_data(n, "facets", root=self.data)
        return self._facets[n]

    def proofs(self, n):
        if n not in self._proofs:
            proofs = ProofCatalog(self.data / f"n={n}/proofs.json")
            inequalities = InequalityCatalog(self.data / f"n={n}/inequalities.json")
            inequalities.check_bindings(proofs)
            if any(entry["n"] != n for entry in inequalities.entries.values()):
                raise ValueError("wrong party count in inequality catalogue")
            self._proofs[n] = proofs, inequalities
        return self._proofs[n]

    def catalogue(self, n, kind):
        key = n, kind
        if key not in self._catalogues:
            self._catalogues[key] = Catalogue(self, n, kind)
        return self._catalogues[key]

    def witnesses(self, n):
        if n not in self._witnesses:
            self._witnesses[n] = FacetWitnessCatalog.optional(self.data / f"n={n}", n)
        return self._witnesses[n]


def witness_changes(old, current, n):
    before, after = old.witnesses(n), current.witnesses(n)
    old_entries, new_entries = ({} if item is None else item.facets for item in (before, after))
    changed = set()
    for key in old_entries.keys() | new_entries.keys():
        prior, present = old_entries.get(key), new_entries.get(key)
        if prior is None or present is None or len(prior) != len(present):
            changed.add(key)
            continue
        for previous, ref in zip(prior, present, strict=True):
            if "ray" in ref and "ray" in previous:
                if (ref["permutation"], ref["row_sha256"]) != (previous["permutation"], previous["row_sha256"]):
                    changed.add(key)
                    continue
                a, b = old.catalogue(n, "rays"), current.catalogue(n, "rays")
                i, j = previous["ray"], ref["ray"]
                if i >= len(a) or j >= len(b) or (a.location(i) != b.location(j) and a.at(i) != b.at(j)):
                    changed.add(key)
            elif ref != previous:
                changed.add(key)
            else:
                model = ref["model"]
                a, b = before.models[model], after.models[model]
                old_path = f"data/n={n}/witness-shards/{a['shard']}.witnesspack"
                new_path = f"data/n={n}/witness-shards/{b['shard']}.witnesspack"
                if a != b or old.tree.oid(old_path) != current.tree.oid(new_path):
                    changed.add(key)
    return changed


def proof_changes(old, current, n):
    before, _ = old.proofs(n)
    after, _ = current.proofs(n)
    previous = {entry["proof_id"]: entry for entry in before.entries}
    result = []
    for index, entry in enumerate(after.entries):
        path = f"data/n={n}/proof-shards/{entry['shard']}.proofpack"
        if previous.get(entry["proof_id"]) != entry or old.tree.oid(path) != current.tree.oid(path):
            result.append(index)
    return result


def proof_batches(catalog, inequalities, indices):
    """Balance only selected complete maps; never split or omit a proof."""
    weights = {i: proof_work(inequalities.entries[catalog.entries[i]["inequality_id"]]) for i in indices}
    target = 1024 * (1 << 18)
    # One job already audits four complete maps in parallel. Avoid redundant
    # startup/downloads for tiny batches, even if one indivisible map is large.
    groups = min(
        64,
        max(1, (len(indices) + 3) // 4),
        max(1, (len(indices) + 1023) // 1024, (sum(weights.values()) + target - 1) // target),
    )
    batches = [[] for _ in range(groups)]
    heap = [(0, 0, group) for group in range(groups)]
    for index in sorted(indices, key=lambda i: (-weights[i], catalog.entries[i]["proof_id"])):
        cost, count, group = heapq.heappop(heap)
        batches[group].append(index)
        heapq.heappush(heap, (cost + weights[index], count + 1, group))
    return [sorted(batch) for batch in batches]


def _payload_paths(snapshot, kind, n, indices):
    if kind == "contractions":
        catalog, _ = snapshot.proofs(n)
        return {f"/data/n={n}/proof-shards/{catalog.entries[index]['shard']}.proofpack" for index in indices}
    rays = snapshot.catalogue(n, "rays")
    if kind == "facets":
        result = {"/" + segment[3] for segment in rays.segments}
        witnesses = snapshot.witnesses(n)
        if witnesses:
            result |= {f"/data/n={n}/witness-shards/{key}.witnesspack" for key in witnesses.shards}
        return result
    result = set()
    for catalog in [rays, snapshot.catalogue(n, "graphs")] if kind == "graphs" else [rays]:
        for start, stop, _, path in catalog.segments:
            position = bisect_left(indices, start)
            if position < len(indices) and indices[position] < stop:
                result.add("/" + path)
    return result


class IntegrityPlan:
    def __init__(self, current, *, baseline=None, full=False, base=None):
        self.current = self.old = None
        try:
            self._initialize(current, baseline=baseline, full=full, base=base)
        except BaseException:
            self.close()
            raise

    def _initialize(self, current, *, baseline=None, full=False, base=None):
        self.current = Snapshot(current)
        self.old = Snapshot(GitTree(current.repository, baseline.base)) if baseline is not None and not full else None
        self.baseline = baseline if self.old is not None else None
        if self.old is not None and (
            self.old.tree.tree != baseline.tree
            or baseline.verifier != current.fingerprint()
            or self.old.tree.fingerprint() != current.fingerprint()
        ):
            raise ValueError("verified baseline does not bind the current verifier and exact old tree")
        if self.old is not None and self.old.ns != self.current.ns:
            self.old.close()
            self.old, self.baseline = None, None
        self.mode = "incremental" if self.baseline else "full"
        self.base = self.baseline.base if self.baseline else base
        self.deltas, self.selected, self.totals, self.tasks = {}, {}, {}, []
        full_matrix = ci_matrix(self.current.data)["include"]
        self.catalogue_mode = self.mode
        if self.mode == "full":
            self.tasks = [{**task, "indices": None} for task in full_matrix]
        else:
            self._incremental(full_matrix)
            self._require_planned_coverage()
        self.tasks.append(
            {
                "kind": "acceptance",
                "n": 0,
                "label": "verify trusted reuse and affected coverage",
                "checkout_paths": "",
                "indices": None,
            }
        )
        if len(self.tasks) > 256:
            raise ValueError("incremental acceptance exceeds the matrix limit; no checks may be dropped")
        for task in self.tasks:
            task["task_id"] = identity(task)
        if len({task["task_id"] for task in self.tasks}) != len(self.tasks):
            raise ValueError("duplicate integrity task identities")
        self.document = {
            "format": "hec-integrity-plan-v1",
            "head": current.commit,
            "tree": current.tree,
            "verifier": current.fingerprint(),
            "base": self.base,
            "mode": self.mode,
            "catalogue_mode": self.catalogue_mode,
            "baseline": self.baseline.document() if self.baseline else None,
            "tasks": self.tasks,
            "coverage": self.totals,
        }
        self.sha256 = identity(self.document)

    def close(self):
        if self.current is not None:
            self.current.close()
        if self.old is not None:
            self.old.close()

    def _incremental(self, full_matrix):
        for n in self.current.ns:
            a, b = self.old, self.current
            old_facets, facets = a.facets(n), b.facets(n)
            old_set = set(old_facets)
            if len(set(facets)) != len(facets):
                raise ValueError("duplicate current facet rows")
            before, after = a.catalogue(n, "rays"), b.catalogue(n, "rays")
            rays = paired_delta(before, after, a.catalogue(n, "graphs"), b.catalogue(n, "graphs"))
            if not rays.retained:
                removed_orbits = {orbit_key(before.at(i), n) for i in rays.removed}
                added_orbits = {orbit_key(after.at(i), n) for i in rays.added}
                rays.retained = removed_orbits <= added_orbits
            self.deltas[n] = rays
            rank_facets = (
                set(range(len(facets)))
                if not rays.retained
                else {i for i, row in enumerate(facets) if row not in old_set}
            )
            affected_witnesses = witness_changes(a, b, n)
            if affected_witnesses:
                rank_facets |= {
                    i for i, row in enumerate(facets) if inequality_id(geometry(n, row)) in affected_witnesses
                }
            literal_facets_retained = old_set <= set(facets)
            facets_retained = literal_facets_retained or {orbit_key(row, n) for row in old_set - set(facets)} <= {
                orbit_key(row, n) for row in set(facets) - old_set
            }
            rank_rays = rays.added if facets_retained else list(range(len(after)))
            selected = {
                "contractions": proof_changes(a, b, n),
                "facets": sorted(rank_facets),
                "rays": rank_rays,
                "graphs": rays.graphs,
            }
            self.selected[n] = selected
            if not literal_facets_retained or not rays.retained or _catalogue_controls_changed(before, after, rays):
                self.catalogue_mode = "full"
            catalog, inequalities = b.proofs(n)
            counts = {
                "contractions": len(catalog),
                "facets": len(facets),
                "rays": len(b.catalogue(n, "rays")),
                "graphs": len(b.catalogue(n, "graphs")),
            }
            self.totals[str(n)] = {
                kind: {"total": count, "audit": len(selected[kind]), "reused": count - len(selected[kind])}
                for kind, count in counts.items()
            }
            for kind, indices in selected.items():
                if not indices:
                    continue
                if len(indices) == counts[kind]:
                    self.tasks += [
                        {**task, "indices": None} for task in full_matrix if task["n"] == n and task["kind"] == kind
                    ]
                    continue
                size = 1024 if kind == "contractions" else 10000 if kind == "facets" else 25000
                limit = {"contractions": 64, "facets": 8, "graphs": 16, "rays": 128}[kind]
                groups = max(1, min(limit, math.ceil(len(indices) / size)))
                batches = (
                    proof_batches(catalog, inequalities, indices)
                    if kind == "contractions"
                    else [
                        indices[len(indices) * group // groups : len(indices) * (group + 1) // groups]
                        for group in range(groups)
                    ]
                )
                for group, owned in enumerate(batches):
                    task = {
                        "kind": kind,
                        "n": n,
                        "indices": owned,
                        "shard_index": 0,
                        "shard_count": 1,
                        "label": f"{kind} (n={n}, changed partition {group + 1}/{len(batches)})",
                        "checkout_paths": "\n".join(sorted(_payload_paths(b, kind, n, owned))),
                    }
                    if kind == "contractions":
                        task["expect_proofs"] = len(owned)
                        task["expect_edges"] = sum(
                            p.L * (p.vertices // 2)
                            for i in owned
                            for p in [
                                geometry(
                                    n,
                                    tuple(
                                        map(
                                            int,
                                            inequalities.entries[catalog.entries[i]["inequality_id"]]["coefficients"],
                                        )
                                    ),
                                )
                            ]
                        )
                    else:
                        task.update(expect_rows=len(owned), partition_mode="round-robin")
                    self.tasks.append(task)

    def _require_planned_coverage(self):
        for n, selections in self.selected.items():
            for kind, wanted in selections.items():
                tasks = [task for task in self.tasks if task["n"] == n and task["kind"] == kind]
                if any(task["indices"] is None for task in tasks):
                    total = self.totals[str(n)][kind]["total"]
                    groups = {task["shard_count"] for task in tasks}
                    if (
                        len(wanted) != total
                        or any(task["indices"] is not None for task in tasks)
                        or len(groups) != 1
                        or {task["shard_index"] for task in tasks} != set(range(groups.pop()))
                        or sum(task.get("expect_proofs", task.get("expect_rows", 0)) for task in tasks) != total
                    ):
                        raise ValueError("incomplete dependent full-partition coverage")
                else:
                    actual = [index for task in tasks for index in task["indices"]]
                    if len(actual) != len(set(actual)) or sorted(actual) != wanted:
                        raise ValueError("missing, duplicate or foreign changed-result ownership")

    def matrix(self):
        # Row selections and potentially long payload lists are recomputed by
        # executors, never transported through GitHub's limited job outputs.
        return {
            "include": [
                {key: value for key, value in task.items() if key not in ("indices", "checkout_paths")}
                for task in self.tasks
            ]
        }

    def storage_paths(self):
        if self.mode == "full":
            return "/data/"
        return "\n".join(
            "/" + path
            for path in sorted(self.current.tree.files)
            if path.startswith("data/") and self.current.tree.oid(path) != self.old.tree.oid(path)
        )

    def catalogue_paths(self):
        return "/data/" if self.catalogue_mode == "full" else self.storage_paths()
