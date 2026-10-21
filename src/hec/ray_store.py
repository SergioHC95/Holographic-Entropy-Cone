"""Ordered integer-ray records in bounded, content-addressed JSON shards.

Large ray catalogues use the same ordinary-Git discipline as graph catalogues:
the small index binds ordered immutable payloads by SHA256, byte count and row
count.  The index is storage metadata, never mathematical acceptance.
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

from .coordinates import dim
from .count_proofs import canonical_json, parse_json
from .serialization import json_path, read_integer_rows

RAY_FORMAT = "hec-ray-catalogue"
RAY_SHARD_BYTES = 16 * 1024**2
_INDEX_BYTES = 1024**2


@dataclass(frozen=True)
class RayShard:
    sha256: str
    bytes: int
    count: int

    @property
    def path(self) -> str:
        return f"ray-shards/{self.sha256}.json"


def _exact_payload(data: bytes, n: int) -> list[tuple[int, ...]]:
    def unique(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate ray JSON key")
            result[key] = value
        return result

    def forbidden(value):
        raise ValueError(f"non-exact ray JSON number: {value}")

    rows = json.loads(data, object_pairs_hook=unique, parse_float=forbidden, parse_constant=forbidden)
    if not isinstance(rows, list):
        raise ValueError("a ray shard must contain a JSON array")
    expected = dim(n)
    result = []
    for row in rows:
        if not isinstance(row, list) or len(row) != expected:
            raise ValueError("invalid ray shard row width")
        if any(isinstance(value, bool) or not isinstance(value, int) for value in row):
            raise ValueError("ray shard rows must contain exact integers")
        result.append(tuple(row))
    return result


class RayCatalog(Sequence[tuple[int, ...]]):
    """Position-preserving ray sequence with at most one materialized shard."""

    def __init__(self, path: str | Path, n: int):
        if type(n) is not int or n < 1:
            raise ValueError("ray catalogue party count must be a positive integer")
        self.path = json_path(path, "ray catalogue")
        self.n = n
        if self.path.is_symlink():
            raise ValueError("ray catalogue cannot be a symlink")
        with self.path.open("rb") as stream:
            data = stream.read(_INDEX_BYTES + 1)
        if len(data) > _INDEX_BYTES:
            raise ValueError("oversized ray catalogue index")
        document = parse_json(data)
        if not isinstance(document, dict) or set(document) != {"format", "count", "shards"}:
            raise ValueError("expected a closed ray catalogue index")
        if document["format"] != RAY_FORMAT or type(document["count"]) is not int or document["count"] < 0:
            raise ValueError("invalid ray catalogue format or count")
        if not isinstance(document["shards"], list):
            raise ValueError("ray catalogue shards must be an ordered list")
        shards, ends, seen = [], [], set()
        total = 0
        for record in document["shards"]:
            if not isinstance(record, dict) or set(record) != {"sha256", "bytes", "count"}:
                raise ValueError("invalid ray shard metadata")
            digest, size, count = record["sha256"], record["bytes"], record["count"]
            if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None or digest in seen:
                raise ValueError("invalid or repeated ray shard identity")
            if type(size) is not int or not 3 <= size <= RAY_SHARD_BYTES or type(count) is not int or count < 1:
                raise ValueError("invalid ray shard size or row count")
            total += count
            seen.add(digest)
            shards.append(RayShard(digest, size, count))
            ends.append(total)
        if total != document["count"]:
            raise ValueError("ray catalogue row coverage does not match its count")
        self.shards = tuple(shards)
        self._ends = tuple(ends)
        self._count = total
        self._cached_ordinal = -1
        self._cached_rows: list[tuple[int, ...]] = []

    def __len__(self) -> int:
        return self._count

    def _load(self, ordinal: int) -> list[tuple[int, ...]]:
        if ordinal != self._cached_ordinal:
            shard = self.shards[ordinal]
            path = self.path.parent / shard.path
            if path.parent.is_symlink() or path.is_symlink():
                raise ValueError("ray shard paths cannot traverse symlinks")
            with path.open("rb") as stream:
                data = stream.read(shard.bytes + 1)
            if len(data) != shard.bytes or hashlib.sha256(data).hexdigest() != shard.sha256:
                raise ValueError("ray shard size or content identity mismatch")
            rows = _exact_payload(data, self.n)
            if len(rows) != shard.count:
                raise ValueError("ray shard row count mismatch")
            self._cached_ordinal, self._cached_rows = ordinal, rows
        return self._cached_rows

    def __getitem__(self, index):
        if isinstance(index, slice):
            return [self[item] for item in range(*index.indices(len(self)))]
        if not isinstance(index, int):
            raise TypeError("ray catalogue indices must be integers or slices")
        if index < 0:
            index += len(self)
        if not 0 <= index < len(self):
            raise IndexError(index)
        ordinal = bisect_right(self._ends, index)
        start = self._ends[ordinal - 1] if ordinal else 0
        return self._load(ordinal)[index - start]

    def __iter__(self) -> Iterator[tuple[int, ...]]:
        for ordinal in range(len(self.shards)):
            yield from self._load(ordinal)


def read_rays(path: str | Path, n: int) -> list[tuple[int, ...]] | RayCatalog:
    """Read an inline small catalogue or the current sharded ray catalogue."""

    source = json_path(path, "ray")
    if source.is_symlink():
        raise ValueError("ray data cannot be a symlink")
    with source.open("rb") as stream:
        prefix = stream.read(8192).lstrip()
    if prefix.startswith(b"{"):
        return RayCatalog(source, n)
    if prefix.startswith(b"["):
        return read_integer_rows(source, n=n)
    raise ValueError("expected inline rays or a ray catalogue index")


def write_ray_catalog(
    path: str | Path,
    rays: Iterable[Sequence[int]],
    n: int,
    *,
    shard_bytes: int = RAY_SHARD_BYTES,
) -> None:
    """Write deterministic exact ray shards without inferring their validity."""

    target = json_path(path, "ray catalogue")
    if type(n) is not int or n < 1:
        raise ValueError("ray catalogue party count must be a positive integer")
    if type(shard_bytes) is not int or not 5 <= shard_bytes <= RAY_SHARD_BYTES:
        raise ValueError("invalid ray shard byte budget")
    target.parent.mkdir(parents=True, exist_ok=True)
    directory = target.parent / "ray-shards"
    if target.is_symlink() or directory.is_symlink():
        raise ValueError("ray catalogue and payload directories cannot be symlinks")
    directory.mkdir(exist_ok=True)
    expected = dim(n)
    shards, lines, count, size, seen = [], [], 0, 0, set()

    def flush() -> None:
        nonlocal lines, size
        if not lines:
            return
        data = b"[\n" + b",\n".join(lines) + b"\n]\n"
        if len(data) > shard_bytes:
            raise ValueError("ray shard exceeds its byte budget")
        digest = hashlib.sha256(data).hexdigest()
        if digest in seen:
            raise ValueError("repeated ray shard identity")
        payload = directory / f"{digest}.json"
        if payload.is_symlink():
            raise ValueError("ray payload cannot be a symlink")
        try:
            with payload.open("xb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
        except FileExistsError:
            if payload.read_bytes() != data:
                raise ValueError("existing immutable ray payload differs from its identity") from None
        seen.add(digest)
        shards.append({"sha256": digest, "bytes": len(data), "count": len(lines)})
        lines, size = [], 0

    for row in rays:
        values = tuple(row)
        if len(values) != expected or any(isinstance(value, bool) or not isinstance(value, int) for value in values):
            raise ValueError("invalid exact ray row")
        line = json.dumps(list(values), separators=(",", ":"), allow_nan=False).encode("ascii")
        candidate_size = (5 + len(line)) if not lines else (size + 2 + len(line))
        if lines and candidate_size > shard_bytes:
            flush()
            candidate_size = 5 + len(line)
        if candidate_size > shard_bytes:
            raise ValueError("one ray exceeds its shard byte budget")
        lines.append(line)
        size = candidate_size
        count += 1
    flush()
    document = {"format": RAY_FORMAT, "count": count, "shards": shards}
    data = canonical_json(document) + b"\n"
    if len(data) > _INDEX_BYTES:
        raise ValueError("ray catalogue index exceeds its byte budget")
    fd, temporary = tempfile.mkstemp(prefix=".rays-", dir=target.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    finally:
        Path(temporary).unlink(missing_ok=True)
