"""Ordered exact graph records in bounded, content-addressed JSON shards.

The index is metadata, not a mathematical certificate. Each referenced byte
and row count is checked on loading; the original independent graph/ray and
rank gates must still check every record. There is one current format and no
legacy-array or LFS fallback. One loaded shard is cached, never a solver state.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from bisect import bisect_right
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .count_proofs import canonical_json, parse_json
from .serialization import json_path, json_ready

GRAPH_FORMAT = "hec-graph-catalogue"
GRAPH_SHARD_BYTES = 16 * 1024**2
_INDEX_BYTES = 1024**2


@dataclass(frozen=True)
class GraphShard:
    sha256: str
    bytes: int
    count: int

    @property
    def path(self) -> str:
        return f"graph-shards/{self.sha256}.json"


def _exact_payload(data: bytes) -> list:
    def unique(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate graph JSON key")
            result[key] = value
        return result

    def forbidden(value):
        raise ValueError(f"non-exact graph JSON number: {value}")

    # Graph edge capacities may be arbitrarily large exact integers or rational
    # strings. Only index counters, not capacities, use the safe-index bound.
    result = json.loads(data, object_pairs_hook=unique, parse_float=forbidden, parse_constant=forbidden)
    if not isinstance(result, list):
        raise ValueError("a graph shard must contain a JSON array")
    return result


class GraphCatalog(Sequence):
    """Position-preserving graph sequence with at most one materialized shard."""

    def __init__(self, path: str | Path):
        self.path = json_path(path, "graph catalogue")
        if self.path.is_symlink():
            raise ValueError("graph catalogue cannot be a symlink")
        with self.path.open("rb") as stream:
            data = stream.read(_INDEX_BYTES + 1)
        if len(data) > _INDEX_BYTES:
            raise ValueError("oversized graph catalogue index")
        document = parse_json(data)
        if not isinstance(document, dict) or set(document) != {"format", "count", "shards"}:
            raise ValueError("expected a closed graph catalogue index")
        if document["format"] != GRAPH_FORMAT or type(document["count"]) is not int or document["count"] < 0:
            raise ValueError("invalid graph catalogue format or count")
        if not isinstance(document["shards"], list):
            raise ValueError("graph catalogue shards must be an ordered list")
        shards, ends, seen = [], [], set()
        total = 0
        for record in document["shards"]:
            if not isinstance(record, dict) or set(record) != {"sha256", "bytes", "count"}:
                raise ValueError("invalid graph shard metadata")
            digest, size, count = record["sha256"], record["bytes"], record["count"]
            if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None or digest in seen:
                raise ValueError("invalid or repeated graph shard identity")
            if type(size) is not int or not 3 <= size <= GRAPH_SHARD_BYTES or type(count) is not int or count < 1:
                raise ValueError("invalid graph shard size or row count")
            total += count
            seen.add(digest)
            shards.append(GraphShard(digest, size, count))
            ends.append(total)
        if total != document["count"]:
            raise ValueError("graph catalogue row coverage does not match its count")
        self.shards = tuple(shards)
        self._ends = tuple(ends)
        self._count = total
        self._cached_ordinal = -1
        self._cached_records: list[Any] = []

    def __len__(self) -> int:
        return self._count

    def _load(self, ordinal: int) -> list:
        if ordinal != self._cached_ordinal:
            shard = self.shards[ordinal]
            path = self.path.parent / shard.path
            if path.parent.is_symlink() or path.is_symlink():
                raise ValueError("graph shard paths cannot traverse symlinks")
            with path.open("rb") as stream:
                data = stream.read(shard.bytes + 1)
            if len(data) != shard.bytes or hashlib.sha256(data).hexdigest() != shard.sha256:
                raise ValueError("graph shard size or content identity mismatch")
            records = _exact_payload(data)
            if len(records) != shard.count:
                raise ValueError("graph shard row count mismatch")
            self._cached_ordinal, self._cached_records = ordinal, records
        return self._cached_records

    def __getitem__(self, index):
        if isinstance(index, slice):
            return [self[i] for i in range(*index.indices(len(self)))]
        if not isinstance(index, int):
            raise TypeError("graph catalogue indices must be integers or slices")
        if index < 0:
            index += len(self)
        if not 0 <= index < len(self):
            raise IndexError(index)
        ordinal = bisect_right(self._ends, index)
        start = self._ends[ordinal - 1] if ordinal else 0
        return self._load(ordinal)[index - start]

    def __iter__(self) -> Iterator:
        for ordinal in range(len(self.shards)):
            yield from self._load(ordinal)


def write_graph_catalog(path: str | Path, graphs: Iterable, *, shard_bytes: int = GRAPH_SHARD_BYTES) -> None:
    """Write deterministic exact records; never infer mathematical validity.

    Immutable payloads are reused only after a complete byte comparison. The
    index is replaced atomically after its payloads are durable. Unreferenced
    old payloads are not silently deleted; repository storage audit rejects
    them until an intentional dataset update removes or archives them.
    """
    target = json_path(path, "graph catalogue")
    if type(shard_bytes) is not int or not 3 <= shard_bytes <= GRAPH_SHARD_BYTES:
        raise ValueError("invalid graph shard byte budget")
    target.parent.mkdir(parents=True, exist_ok=True)
    directory = target.parent / "graph-shards"
    if target.is_symlink() or directory.is_symlink():
        raise ValueError("graph catalogue and payload directories cannot be symlinks")
    directory.mkdir(exist_ok=True)
    shards, lines, count, size, seen = [], [], 0, 3, set()

    def flush():
        if not lines:
            return
        data = b"[\n  " + b",\n  ".join(lines) + b"\n]\n"
        digest = hashlib.sha256(data).hexdigest()
        if digest in seen:
            raise ValueError("repeated graph shard identity")
        payload = directory / f"{digest}.json"
        if payload.is_symlink():
            raise ValueError("graph payload cannot be a symlink")
        try:
            with payload.open("xb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
        except FileExistsError:
            if payload.read_bytes() != data:
                raise ValueError("existing immutable graph payload differs from its identity") from None
        seen.add(digest)
        shards.append({"sha256": digest, "bytes": len(data), "count": len(lines)})

    for graph in graphs:
        line = json.dumps(json_ready(graph), sort_keys=True, separators=(",", ": "), allow_nan=False).encode("ascii")
        _exact_payload(b"[" + line + b"]")
        if len(line) + 7 > shard_bytes:
            raise ValueError("one graph exceeds its shard byte budget")
        if lines and size + len(line) + 4 > shard_bytes:
            flush()
            lines, size = [], 3
        lines.append(line)
        size += len(line) + 4
        count += 1
    flush()
    document = {"format": GRAPH_FORMAT, "count": count, "shards": shards}
    data = canonical_json(document) + b"\n"
    if len(data) > _INDEX_BYTES:
        raise ValueError("graph catalogue index exceeds its byte budget")
    fd, temporary = tempfile.mkstemp(prefix=".graphs-", dir=target.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    finally:
        Path(temporary).unlink(missing_ok=True)
