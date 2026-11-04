"""Exact graph-entropy certificates supplement facet rank, never ray extremality.

Each entropy coordinate has a feasible signed flow and an equal-capacity cut.
Their equality proves the minimum cut with integer arithmetic. Sixty-two tight,
independent graph entropies then certify a six-party facet's support rank.
Contraction validity remains a separate, mandatory full-map audit.
"""

from __future__ import annotations

import hashlib
import math
import re
import threading
from numbers import Integral
from pathlib import Path

import zstandard as zstd

from .coordinates import subsets
from .count_proofs import canonical_json, decimal, geometry, inequality_id, parse_json
from .rank import RANK_PRIME
from .symmetry import permutation_array

FORMAT = "hec-facet-rank-witnesses"
MODEL_FORMAT = "hec-exact-graph-entropy"
INDEX_BYTES = 2 * 1024**2
SHARD_BYTES = 16 * 1024**2
MODEL_BYTES = 64 * 1024**2
_SHA = re.compile(r"[0-9a-f]{64}\Z")


def _require(ok, message):
    if not ok:
        raise ValueError(message)


def _keys(value, names, label):
    _require(isinstance(value, dict) and set(value) == set(names), f"invalid {label} fields")


def _sha(value):
    return isinstance(value, str) and _SHA.fullmatch(value) is not None


def row_digest(row):
    return hashlib.sha256(canonical_json([str(int(value)) for value in row])).hexdigest()


def _read(path, limit):
    _require(not path.is_symlink() and not path.parent.is_symlink(), "unsafe witness path")
    with path.open("rb") as stream:
        raw = stream.read(limit + 1)
    _require(len(raw) <= limit, "oversized witness input")
    return raw


def verify_model(model, n):
    """Verify all coordinates by primal/dual equality; no solver or receipt."""
    _keys(model, ("format", "n", "vertices", "edges", "capacities", "cuts"), "graph entropy model")
    _require(model["format"] == MODEL_FORMAT and type(model["n"]) is int and model["n"] == n, "wrong model frame")
    size, edges, capacities, cuts = (model[key] for key in ("vertices", "edges", "capacities", "cuts"))
    _require(type(size) is int and n + 1 <= size <= 65536, "invalid witness graph order")
    _require(
        isinstance(edges, list) and isinstance(capacities, list) and 0 < len(edges) == len(capacities) <= 262144,
        "invalid witness edge coverage",
    )
    weights = []
    for edge, capacity in zip(edges, capacities, strict=True):
        _require(
            isinstance(edge, list)
            and len(edge) == 2
            and all(type(v) is int and 0 <= v < size for v in edge)
            and edge[0] != edge[1],
            "invalid witness edge",
        )
        weight = decimal(capacity)
        _require(0 <= weight < 1 << 1024, "invalid witness capacity")
        weights.append(weight)
    masks = [sum(1 << v for v in part) for part in subsets(n)]
    _require(isinstance(cuts, list) and len(cuts) == len(masks), "incomplete entropy coordinate coverage")
    values = []
    for mask, cut in zip(masks, cuts, strict=True):
        _keys(cut, ("mask", "value", "shore", "flows"), "flow/cut certificate")
        _require(type(cut["mask"]) is int and cut["mask"] == mask, "wrong entropy coordinate")
        value = decimal(cut["value"])
        shore = cut["shore"]
        _require(
            isinstance(shore, str)
            and re.fullmatch(r"(?:0|[1-9a-f][0-9a-f]*)", shore) is not None
            and len(shore) <= (size + 3) // 4,
            "invalid cut shore",
        )
        word = int(shore, 16)
        _require(0 <= word < 1 << size and word & ((1 << (n + 1)) - 1) == mask, "cut terminal mismatch")
        flows = cut["flows"]
        _require(isinstance(flows, list) and len(flows) == len(edges), "incomplete flow coverage")
        balance, capacity = [0] * size, 0
        for (left, right), weight, raw_flow in zip(edges, weights, flows, strict=True):
            flow = decimal(raw_flow)
            _require(-weight <= flow <= weight, "flow exceeds edge capacity")
            balance[left] += flow
            balance[right] -= flow
            if ((word >> left) ^ (word >> right)) & 1:
                capacity += weight
        _require(value >= 0 and not any(balance[n + 1 :]), "invalid flow conservation")
        _require(
            sum(balance[v] for v in range(n) if mask >> v & 1) == value == capacity,
            "feasible flow and cut capacity differ",
        )
        values.append(value)
    divisor = math.gcd(*values)
    _require(divisor > 0, "zero graph entropy is not a rank witness")
    return tuple(value // divisor for value in values)


def _independent_rank(rows, width):
    basis = {}
    for vector in rows:
        row = [value % RANK_PRIME for value in vector]
        for pivot in range(width):
            if not row[pivot]:
                continue
            if pivot in basis:
                factor, previous = row[pivot], basis[pivot]
                row = [(a - factor * b) % RANK_PRIME for a, b in zip(row, previous, strict=True)]
            else:
                inverse = pow(row[pivot], -1, RANK_PRIME)
                basis[pivot] = [value * inverse % RANK_PRIME for value in row]
                break
    return len(basis)


class FacetWitnessCatalog:
    """Bounded immutable proposals; only verify_facet confers a rank result."""

    @classmethod
    def optional(cls, directory, n):
        path = Path(directory) / "facet-witnesses.json"
        return cls(path, n) if path.exists() or path.is_symlink() else None

    def __init__(self, path, n):
        self.path, self.n = Path(path), n
        document = parse_json(_read(self.path, INDEX_BYTES))
        _keys(document, ("format", "n", "facets", "models", "shards"), "facet witness catalogue")
        _require(
            document["format"] == FORMAT and type(document["n"]) is int and document["n"] == n,
            "wrong witness catalogue frame",
        )
        _require(
            isinstance(document["facets"], list)
            and document["facets"]
            and isinstance(document["models"], dict)
            and document["models"]
            and isinstance(document["shards"], dict)
            and document["shards"],
            "empty witness catalogue",
        )
        self.models, self.shards, self.facets = document["models"], document["shards"], {}
        used = set()
        for entry in document["facets"]:
            _keys(entry, ("inequality_id", "basis"), "facet basis")
            identity, basis = entry["inequality_id"], entry["basis"]
            _require(
                _sha(identity)
                and identity not in self.facets
                and isinstance(basis, list)
                and len(basis) == (1 << n) - 2,
                "invalid facet basis identity or size",
            )
            for ref in basis:
                _require(isinstance(ref, dict), "invalid basis reference")
                if "ray" in ref:
                    _keys(ref, ("ray", "permutation", "row_sha256"), "ray witness")
                    _require(
                        type(ref["ray"]) is int and ref["ray"] >= 0 and _sha(ref["row_sha256"]), "invalid ray identity"
                    )
                else:
                    _keys(ref, ("model", "permutation"), "graph witness")
                    _require(_sha(ref["model"]) and ref["model"] in self.models, "unknown graph witness")
                    used.add(ref["model"])
                _require(
                    type(ref["permutation"]) is int and 0 <= ref["permutation"] < math.factorial(n + 1),
                    "invalid witness permutation",
                )
            self.facets[identity] = basis
        _require(used == set(self.models), "unreferenced witness model")
        spans = {key: [] for key in self.shards}
        for key, info in self.shards.items():
            _keys(info, ("bytes",), "witness shard")
            _require(
                _sha(key) and type(info["bytes"]) is int and 0 < info["bytes"] <= SHARD_BYTES,
                "invalid witness shard identity or size",
            )
        for identity, entry in self.models.items():
            _keys(entry, ("shard", "offset", "bytes"), "witness model")
            _require(
                _sha(identity)
                and entry["shard"] in self.shards
                and type(entry["offset"]) is int
                and entry["offset"] >= 0
                and type(entry["bytes"]) is int
                and entry["bytes"] > 0,
                "invalid witness model frame",
            )
            spans[entry["shard"]].append((entry["offset"], entry["bytes"]))
        for key, entries in spans.items():
            end = 0
            for start, size in sorted(entries):
                _require(start == end, "overlapping or missing witness payload bytes")
                end += size
            _require(end == self.shards[key]["bytes"], "incomplete witness shard coverage")
        self._models, self._payloads, self._lock = {}, {}, threading.Lock()
        self._inverse = None

    def check_bindings(self, facet_ids):
        _require(set(self.facets) <= set(facet_ids), "witness basis has no stored facet")

    def _model(self, identity):
        with self._lock:
            if identity not in self._models:
                entry = self.models[identity]
                shard = entry["shard"]
                if shard not in self._payloads:
                    raw = _read(self.path.parent / "witness-shards" / (shard + ".witnesspack"), SHARD_BYTES)
                    _require(
                        len(raw) == self.shards[shard]["bytes"] and hashlib.sha256(raw).hexdigest() == shard,
                        "witness shard hash or size mismatch",
                    )
                    self._payloads[shard] = raw
                frame = self._payloads[shard][entry["offset"] : entry["offset"] + entry["bytes"]]
                size = zstd.frame_content_size(frame)
                _require(type(size) is int and 0 < size <= MODEL_BYTES, "unbounded witness model frame")
                raw = zstd.ZstdDecompressor().decompress(frame, max_output_size=MODEL_BYTES, allow_extra_data=False)
                _require(
                    len(raw) <= MODEL_BYTES and hashlib.sha256(raw).hexdigest() == identity,
                    "wrong witness model identity",
                )
                self._models[identity] = verify_model(parse_json(raw), self.n)
            return self._models[identity]

    def verify_facet(self, coefficients, ray_matrix):
        _require(
            all(isinstance(v, Integral) and not isinstance(v, bool) for v in coefficients),
            "facet coefficients must be exact integers",
        )
        problem = geometry(self.n, tuple(int(v) for v in coefficients))
        _require(any(problem.coefficients), "zero inequality is not a facet")
        identity = inequality_id(problem)
        if identity not in self.facets:
            return None
        if self._inverse is None:
            import numpy as np

            self._inverse = np.argsort(permutation_array(self.n), axis=1)
        rows = []
        for ref in self.facets[identity]:
            if "ray" in ref:
                _require(ref["ray"] < len(ray_matrix), "ray witness index out of range")
                _require(
                    all(isinstance(v, Integral) and not isinstance(v, bool) for v in ray_matrix[ref["ray"]]),
                    "ray witness coefficients must be exact integers",
                )
                vector = tuple(int(v) for v in ray_matrix[ref["ray"]])
                _require(row_digest(vector) == ref["row_sha256"], "ray witness identity changed")
            else:
                vector = self._model(ref["model"])
            image = tuple(vector[int(v)] for v in self._inverse[ref["permutation"]])
            _require(
                sum(a * b for a, b in zip(problem.coefficients, image, strict=True)) == 0,
                "facet witness is not exactly tight",
            )
            rows.append(image)
        rank = _independent_rank(rows, len(problem.coefficients))
        _require(rank == len(problem.coefficients) - 1, "dependent facet witness basis")
        return {
            "ok": True,
            "n": self.n,
            "rank": rank,
            "target_rank": rank,
            "method": "exact tight graph-entropy basis; every supplied flow and cut freshly verified",
        }
