"""Historical persisted contraction formats, for offline archive import only."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Iterator, Sequence
from pathlib import Path
from typing import Any

import numpy as np

from hec.contractions import _encoded_image_rows, _ordered_image_bits, minimal_contraction, normalize_contraction
from hec.coordinates import infer_n, parse_inequality
from hec.serialization import json_path, load_json, save_json_records


def _packed_tail_paths(path: str | Path) -> tuple[Path, Path]:
    source = json_path(path, "contraction")
    return (
        source.with_name(f"{source.stem}-tail.packbits.zst"),
        source.with_name(f"{source.stem}-tail.index.json"),
    )


def packed_contraction_tail_paths(path: str | Path) -> tuple[Path, Path]:
    """Return the append-only packed-tail data and index paths for ``path``."""

    return _packed_tail_paths(path)


def _packed_contractions_path(path: str | Path) -> Path:
    source = json_path(path, "contraction")
    return source.with_name(f"{source.stem}.packbits.zst")


def _read_stream_exact(reader: Any, count: int) -> bytes:
    chunks: list[bytes] = []
    remaining = int(count)
    while remaining:
        chunk = reader.read(remaining)
        if not chunk:
            raise ValueError("packed contraction stream ended before the indexed bytes")
        chunks.append(bytes(chunk))
        remaining -= len(chunk)
    return b"".join(chunks)


def _packed_image_bytes(images: object, L: int, R: int) -> bytes:
    """Encode canonical image rows as the compact on-disk bit table."""

    if R == 0:
        if images != []:
            raise ValueError("zero-width contraction images must use the canonical empty list")
        return b""
    _rows, bits = _ordered_image_bits(images, L, R)
    return np.packbits((bits == ord("1")).reshape(-1), bitorder="little").tobytes()


def _sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_packed_contraction_tail(
    path: str | Path,
    contractions: Sequence[dict],
    *,
    n: int,
    facet_rows: Sequence[Sequence[int]],
    facet_start: int,
    compression_level: int = 19,
) -> dict[str, Any]:
    """Write one append-only packed proof segment and return its checked index.

    ``facet_rows`` must be the rows represented by ``contractions``; their
    absolute database positions begin at ``facet_start``.  The caller owns
    atomic replacement of the generated data file and its JSON index.
    """

    if len(facet_rows) != len(contractions):
        raise ValueError("packed contraction tail rows and proofs must have the same length")
    if int(facet_start) < 0:
        raise ValueError("packed contraction tail facet_start must be nonnegative")

    import zstandard as zstd

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    raw_digest = hashlib.sha256()
    raw_size = 0
    records: list[list[int]] = []
    with target.open("wb") as handle:
        with zstd.ZstdCompressor(level=int(compression_level)).stream_writer(handle) as writer:
            for row, contraction in zip(facet_rows, contractions, strict=True):
                canonical = minimal_contraction(row, int(n), contraction)
                lhs_sets, _alpha, _rhs_sets, beta = parse_inequality(row, int(n))
                L = len(lhs_sets)
                R = int(sum(beta))
                payload = _packed_image_bytes(canonical["images"], L, R)
                writer.write(payload)
                raw_digest.update(payload)
                raw_size += len(payload)
                records.append([L, R])
    return {
        "schema_version": 1,
        "kind": "packed-contraction-tail",
        "n": int(n),
        "facet_start": int(facet_start),
        "record_count": len(records),
        "order": "same-as-facets-json",
        "records": records,
        "raw_size": raw_size,
        "raw_sha256": raw_digest.hexdigest(),
        "compressed_size": target.stat().st_size,
        "compressed_sha256": _sha256_path(target),
        "encoding": {
            "compression": "zstd",
            "compression_level": int(compression_level),
            "domain_order": "integer-mask-ascending",
            "output_order": "rhs-term-order-from-minimal_contraction",
            "table": "row-major-packbits-little",
        },
    }


class ContractionRecords(Sequence[dict]):
    """Lazy contraction records reconstructed from an aligned packed stream."""

    def __init__(
        self,
        prefix: Sequence[dict],
        *,
        n: int,
        facet_rows: Sequence[Sequence[int]],
        data_path: Path,
        index: dict[str, Any],
    ) -> None:
        self._prefix = tuple(prefix)
        self._n = int(n)
        self._facet_start = int(index.get("facet_start", -1))
        self._records = tuple(self._parse_records(index.get("records")))
        self._data_path = data_path
        self._raw_size = int(index.get("raw_size", -1))
        self._raw_sha256 = str(index.get("raw_sha256", ""))
        self._compressed_size = int(index.get("compressed_size", -1))
        self._compressed_sha256 = str(index.get("compressed_sha256", ""))
        if self._facet_start < len(self._prefix):
            raise ValueError(
                f"packed contraction stream starts at {self._facet_start}, before prefix length {len(self._prefix)}"
            )
        if self._facet_start < 0 or self._raw_size < 0 or self._compressed_size < 0:
            raise ValueError("packed contraction stream has invalid size metadata")
        if int(index.get("record_count", -1)) != len(self._records):
            raise ValueError("packed contraction stream record count does not match its records")
        expected_facets = self._facet_start + len(self._records)
        if len(facet_rows) < expected_facets:
            raise ValueError(f"packed contraction records={expected_facets} but aligned facet rows={len(facet_rows)}")
        self._facet_rows = tuple(
            tuple(int(value) for value in facet_rows[self._facet_start + index]) for index in range(len(self._records))
        )
        if not self._data_path.is_file():
            raise FileNotFoundError(self._data_path)
        if self._data_path.stat().st_size != self._compressed_size:
            raise ValueError("packed contraction stream compressed size does not match its manifest")
        if len(self._raw_sha256) != 64 or len(self._compressed_sha256) != 64:
            raise ValueError("packed contraction stream has invalid SHA-256 metadata")

    @staticmethod
    def _parse_records(value: object) -> list[tuple[int, int]]:
        if not isinstance(value, list):
            raise ValueError("packed contraction manifest records must be a list")
        records: list[tuple[int, int]] = []
        for entry in value:
            if not isinstance(entry, list | tuple) or len(entry) != 2:
                raise ValueError(f"invalid packed contraction shape record {entry!r}")
            L, R = int(entry[0]), int(entry[1])
            if L < 0 or R < 0:
                raise ValueError(f"invalid packed contraction shape L={L}, R={R}")
            records.append((L, R))
        return records

    def __len__(self) -> int:
        return self._facet_start + len(self._records)

    @property
    def facet_start(self) -> int:
        """Absolute index of this packed segment's first record."""

        return self._facet_start

    def __getitem__(self, index: int | slice) -> dict | list[dict]:
        if isinstance(index, slice):
            return list(iter(self))[index]
        position = int(index)
        if position < 0:
            position += len(self)
        if position < 0 or position >= len(self):
            raise IndexError(position)
        if position < len(self._prefix):
            return self._prefix[position]
        if position < self._facet_start:
            raise IndexError(position)
        for current, record in enumerate(self._iter_tail(), start=self._facet_start):
            if current == position:
                return record
        raise IndexError(position)

    def __iter__(self) -> Iterator[dict]:
        yield from self._prefix
        yield from self._iter_tail()

    def iter_selected(self, shard_index: int, shard_count: int) -> Iterator[tuple[int, dict]]:
        """Yield selected global records while scanning the packed stream once."""

        if shard_count < 1:
            raise ValueError(f"shard count must be positive, got {shard_count}")
        if not 0 <= shard_index < shard_count:
            raise ValueError(f"shard index must be in [0, {shard_count}), got {shard_index}")
        for index, record in enumerate(self._prefix):
            if index % shard_count == shard_index:
                yield index, record
        yield from self._iter_tail_indexed(shard_index, shard_count)

    def _iter_tail(self) -> Iterator[dict]:
        for _index, record in self._iter_tail_indexed(0, 1):
            yield record

    def _iter_tail_indexed(self, shard_index: int, shard_count: int) -> Iterator[tuple[int, dict]]:
        import zstandard as zstd

        compressed_digest = hashlib.sha256()
        with self._data_path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
                compressed_digest.update(chunk)
        if compressed_digest.hexdigest() != self._compressed_sha256:
            raise ValueError("packed contraction stream compressed SHA-256 mismatch")
        with self._data_path.open("rb") as compressed:
            with zstd.ZstdDecompressor().stream_reader(compressed) as reader:
                digest = hashlib.sha256()
                raw_size = 0
                for offset, (L, R) in enumerate(self._records):
                    bit_count = (1 << L) * R
                    payload = _read_stream_exact(reader, (bit_count + 7) // 8)
                    digest.update(payload)
                    raw_size += len(payload)
                    index = self._facet_start + offset
                    if index % shard_count == shard_index:
                        yield (
                            index,
                            minimal_contraction(
                                self._facet_rows[offset], self._n, {"images": _encoded_image_rows(payload, L, R)}
                            ),
                        )
                if reader.read(1):
                    raise ValueError("packed contraction stream has bytes beyond its indexed records")
        if raw_size != self._raw_size:
            raise ValueError(f"packed contraction stream raw size {raw_size} does not match {self._raw_size}")
        if digest.hexdigest() != self._raw_sha256:
            raise ValueError("packed contraction stream raw SHA-256 mismatch")


class ChainedContractionRecords(Sequence[dict]):
    """A contiguous sequence assembled from immutable packed proof segments."""

    def __init__(self, segments: Sequence[ContractionRecords]) -> None:
        if not segments:
            raise ValueError("packed contraction chain requires at least one segment")
        expected_start = 0
        for segment in segments:
            if segment.facet_start != expected_start:
                raise ValueError(
                    f"packed contraction chain has a gap or overlap at {segment.facet_start}, expected {expected_start}"
                )
            expected_start = len(segment)
        self._segments = tuple(segments)

    def __len__(self) -> int:
        return len(self._segments[-1])

    def __getitem__(self, index: int | slice) -> dict | list[dict]:
        if isinstance(index, slice):
            return list(iter(self))[index]
        position = int(index)
        if position < 0:
            position += len(self)
        if position < 0 or position >= len(self):
            raise IndexError(position)
        for segment in self._segments:
            if segment.facet_start <= position < len(segment):
                return segment[position]
        raise IndexError(position)  # pragma: no cover - constructor proves coverage.

    def __iter__(self) -> Iterator[dict]:
        for segment in self._segments:
            yield from segment._iter_tail()

    def iter_selected(self, shard_index: int, shard_count: int) -> Iterator[tuple[int, dict]]:
        """Yield globally sharded records while scanning each immutable segment once."""

        for segment in self._segments:
            yield from segment.iter_selected(shard_index, shard_count)


def _read_packed_tail_segment(
    source: Path,
    *,
    n: int,
    facet_rows: Sequence[Sequence[int]],
    expected_start: int,
    prefix: Sequence[dict] = (),
) -> ContractionRecords | None:
    packed_path, index_path = _packed_tail_paths(source)
    if not index_path.exists() and not packed_path.exists():
        return None
    if not index_path.is_file() or not packed_path.is_file():
        raise FileNotFoundError("packed contraction tail requires both its data and index files")
    index = json.loads(index_path.read_text(encoding="utf-8"))
    if not isinstance(index, dict):
        raise ValueError(f"packed contraction tail index is not an object: {index_path}")
    if int(index.get("schema_version", -1)) != 1 or index.get("kind") != "packed-contraction-tail":
        raise ValueError(f"unsupported packed contraction tail index: {index_path}")
    if int(index.get("n", -1)) != int(n):
        raise ValueError(f"packed contraction tail n={index.get('n')!r}, expected {n}")
    if index.get("order") != "same-as-facets-json":
        raise ValueError("packed contraction tail does not declare facet-file order")
    if int(index.get("facet_start", -1)) != int(expected_start):
        raise ValueError(
            f"packed contraction tail starts at {index.get('facet_start')!r}, expected {int(expected_start)}"
        )
    return ContractionRecords(prefix, n=int(n), facet_rows=facet_rows, data_path=packed_path, index=index)


def read_contractions(
    path: str | Path,
    *,
    n: int | None = None,
    facet_rows: Sequence[Sequence[int]] | None = None,
) -> Sequence[dict]:
    source = json_path(path, "contraction")
    payload = load_json(source)
    if isinstance(payload, dict) and payload.get("kind") == "packed-contractions":
        if facet_rows is None:
            raise ValueError("facet_rows are required to reconstruct packed contractions")
        if n is None:
            n = infer_n(len(facet_rows[0]))
        if int(payload.get("schema_version", -1)) != 1:
            raise ValueError(f"unsupported packed contraction manifest: {source}")
        if int(payload.get("n", -1)) != int(n):
            raise ValueError(f"packed contraction manifest n={payload.get('n')!r}, expected {n}")
        packed_path = _packed_contractions_path(source)
        if not packed_path.is_file():
            raise FileNotFoundError(packed_path)
        base = ContractionRecords(
            (),
            n=int(n),
            facet_rows=facet_rows,
            data_path=packed_path,
            index={**payload, "facet_start": 0},
        )
        tail = _read_packed_tail_segment(
            source,
            n=int(n),
            facet_rows=facet_rows,
            expected_start=len(base),
        )
        if tail is None:
            if len(base) != len(facet_rows):
                raise ValueError(f"packed contractions={len(base)} but aligned facet rows={len(facet_rows)}")
            return base
        chain = ChainedContractionRecords((base, tail))
        if len(chain) != len(facet_rows):
            raise ValueError(f"packed contractions={len(chain)} but aligned facet rows={len(facet_rows)}")
        return chain
    if not isinstance(payload, list):
        raise ValueError(f"expected a list of contractions or packed manifest in {source}")
    prefix = [normalize_contraction(record) for record in payload]
    packed_path, index_path = _packed_tail_paths(source)
    if not index_path.exists() and not packed_path.exists():
        return prefix
    if facet_rows is None:
        raise ValueError("facet_rows are required to reconstruct a packed contraction tail")
    if n is None:
        n = infer_n(len(facet_rows[0]))
    tail = _read_packed_tail_segment(
        source,
        n=int(n),
        facet_rows=facet_rows,
        expected_start=len(prefix),
        prefix=prefix,
    )
    if tail is None:  # pragma: no cover - checked above; keeps the type narrow.
        return prefix
    if len(tail) != len(facet_rows):
        raise ValueError(f"packed contractions={len(tail)} but aligned facet rows={len(facet_rows)}")
    return tail


def write_contractions(path: str | Path, contractions: Iterable[dict]) -> None:
    target = json_path(path, "contraction")
    save_json_records(target, (normalize_contraction(record) for record in contractions))
