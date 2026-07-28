"""Contraction-map search and verification for HEC inequalities.

The public API is intentionally small:

``find_contraction`` searches for a contraction certificate.
``check_contraction`` verifies a saved or in-memory certificate.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

import numpy as np

from .bits import BitPoint, bit_mask, bit_tuple, d_alpha, d_hamming, encode_bits
from .coordinates import (
    dim,
    infer_n,
    occurrence_vectors,
    parse_inequality,
    party_index,
    party_labels,
    subset_index_map,
)
from .serialization import json_path, load_json, save_json_records

_TERM_LABEL_RE = re.compile(r"P\d+|[A-Z]")


@dataclass(frozen=True)
class ContractionProblem:
    coeffs: tuple[int, ...]
    n: int
    lhs_sets: list[frozenset[int]]
    alpha: list[int]
    rhs_sets: list[frozenset[int]]
    beta: list[int]
    boundary: dict[BitPoint, BitPoint]
    L: int
    R: int


def _build_problem(coeffs: Sequence[int], n: int) -> tuple[ContractionProblem | None, dict]:
    lhs_sets, alpha, rhs_sets, beta = parse_inequality(coeffs, n)
    L = len(lhs_sets)
    R = sum(beta)
    info = {
        "n": n,
        "L": L,
        "R": R,
        "lhs_terms": len(lhs_sets),
        "rhs_terms": len(rhs_sets),
        "alpha_sum": int(sum(alpha)),
    }
    if L == 0 and R == 0:
        info.update(status="proved", reason="trivial_zero")
        return None, info
    if R == 0:
        info.update(status="proved", reason="empty_rhs")
        return None, info
    if L == 0:
        info.update(status="infeasible", reason="empty_lhs_nonempty_rhs")
        return None, info

    boundary: dict[BitPoint, BitPoint] = {}
    for x, y in occurrence_vectors(lhs_sets, rhs_sets, beta, n):
        if x in boundary and boundary[x] != y:
            info.update(status="boundary_conflict", x=encode_bits(x), y1=encode_bits(boundary[x]), y2=encode_bits(y))
            return None, info
        boundary[x] = y

    bad = _boundary_pairwise_violations(boundary, alpha)
    if bad:
        info.update(status="pairwise_violation", sample=bad[:5])
        return None, info

    problem = ContractionProblem(
        coeffs=tuple(int(v) for v in coeffs),
        n=n,
        lhs_sets=lhs_sets,
        alpha=[int(v) for v in alpha],
        rhs_sets=rhs_sets,
        beta=[int(v) for v in beta],
        boundary=boundary,
        L=L,
        R=R,
    )
    return problem, info


def _boundary_pairwise_violations(boundary: dict[BitPoint, BitPoint], alpha: Sequence[int]) -> list[dict]:
    items = list(boundary.items())
    bad = []
    for i, (x1, y1) in enumerate(items):
        for x2, y2 in items[i + 1 :]:
            da = d_alpha(x1, x2, alpha)
            db = d_hamming(y1, y2)
            if db > da:
                bad.append({"x1": encode_bits(x1), "x2": encode_bits(x2), "d_alpha": da, "d_beta": db})
    return bad


@cache
def _cube_bitstrings(width: int) -> tuple[str, ...]:
    return tuple(encode_bits(bit_tuple(mask, width)) for mask in range(1 << width))


def _encoded_image_table(table: np.ndarray, L: int) -> dict[str, str]:
    ascii_rows = np.asarray(table, dtype=np.uint8) + ord("0")
    R = table.shape[1]
    raw = ascii_rows.tobytes()
    if R == 0:
        images = ("",) * table.shape[0]
    else:
        images = tuple(raw[offset : offset + R].decode("ascii") for offset in range(0, len(raw), R))
    return dict(zip(_cube_bitstrings(L), images, strict=True))


def _encoded_image_rows(data: bytes, L: int, R: int) -> list[str]:
    """Decode a row-major little-endian packed contraction table."""

    bit_count = (1 << int(L)) * int(R)
    expected_bytes = (bit_count + 7) // 8
    if len(data) != expected_bytes:
        raise ValueError(f"packed contraction table has {len(data)} bytes, expected {expected_bytes}")
    if R == 0:
        return [""] * (1 << int(L))
    bits = np.unpackbits(np.frombuffer(data, dtype=np.uint8), bitorder="little", count=bit_count)
    table = bits.reshape(1 << int(L), int(R))
    ascii_rows = np.asarray(table, dtype=np.uint8) + ord("0")
    raw = ascii_rows.tobytes()
    return [raw[offset : offset + int(R)].decode("ascii") for offset in range(0, len(raw), int(R))]


def find_contraction(
    coeffs: Sequence[int],
    n: int,
) -> dict:
    """Find a contraction map proving ``coeffs . S >= 0``."""
    start = time.perf_counter()

    problem, info = _build_problem(coeffs, n)
    if problem is None:
        info.setdefault("elapsed_s", round(time.perf_counter() - start, 6))
        return info

    from .contraction_solver import solve_contraction

    table, solver_info = solve_contraction(problem)
    if table is None:
        info.update(solver_info)
        info.setdefault("elapsed_s", round(time.perf_counter() - start, 6))
        return info
    return {
        "status": "proved",
        "n": problem.n,
        "coeffs": list(problem.coeffs),
        "elapsed_s": solver_info.get("elapsed_s", round(time.perf_counter() - start, 6)),
        "images": _encoded_image_table(table, problem.L),
    }


def minimal_contraction(coeffs: Sequence[int], n: int, contraction: dict) -> dict:
    """Return the compact JSON-ready contraction map representation."""
    lhs_sets, alpha, rhs_sets, beta = parse_inequality(coeffs, n)
    labels = party_labels(n)
    L = len(lhs_sets)
    R = sum(beta)

    def label(term: frozenset[int]) -> str:
        return "".join(labels[index] for index in sorted(term))

    return {
        "lhs": [[label(term), coefficient] for term, coefficient in zip(lhs_sets, alpha, strict=True)],
        "rhs": [
            [label(term), 1] for term, multiplicity in zip(rhs_sets, beta, strict=True) for _ in range(multiplicity)
        ],
        "images": [] if R == 0 else _normalize_images(contraction.get("images", {}), L, R),
    }


@cache
def _term_from_label(label: str) -> frozenset[int]:
    pieces = _TERM_LABEL_RE.findall(label)
    if not pieces or "".join(pieces) != label:
        raise ValueError(f"invalid term label {label!r}")
    out = frozenset(party_index(piece) for piece in pieces)
    if len(out) != len(pieces):
        raise ValueError(f"repeated party in term label {label!r}")
    return out


def _term_and_coefficient(entry: object) -> tuple[frozenset[int], int]:
    if isinstance(entry, list | tuple) and len(entry) == 2:
        coefficient = int(entry[1])
        if isinstance(entry[1], bool) or coefficient <= 0:
            raise ValueError(f"invalid contraction coefficient {entry[1]!r}")
        if not isinstance(entry[0], str):
            raise ValueError(f"invalid term label {entry[0]!r}")
        return _term_from_label(entry[0]), coefficient
    raise ValueError(f"invalid contraction term {entry!r}")


def _decode_mask(text: object, width: int, label: str) -> int:
    if not isinstance(text, str) or len(text) != width:
        raise ValueError(f"{label} must be a {width}-bit string")
    mask = 0
    for bit, char in enumerate(text):
        if char == "1":
            mask |= 1 << bit
        elif char != "0":
            raise ValueError(f"{label} must contain only 0/1 bits")
    return mask


def _image_table(images: object, L: int, R: int) -> np.ndarray:
    if isinstance(images, dict):
        table = np.full((1 << L, R), -1, dtype=np.int8)
        if len(images) != 1 << L:
            raise ValueError(f"image table has {len(images)} rows, expected {1 << L}")
        for point, image in images.items():
            row = _decode_mask(point, L, "domain point")
            if np.any(table[row] >= 0):
                raise ValueError(f"duplicate image row {point!r}")
            if not isinstance(image, str) or len(image) != R:
                raise ValueError(f"image at {point!r} must be a {R}-bit string")
            for bit, char in enumerate(image):
                if char == "1":
                    table[row, bit] = 1
                elif char == "0":
                    table[row, bit] = 0
                else:
                    raise ValueError(f"image at {point!r} must contain only 0/1 bits")
    elif isinstance(images, list | tuple):
        _, bits = _ordered_image_bits(images, L, R)
        table = bits.astype(np.int8)
        table -= ord("0")
    else:
        raise ValueError("contraction images must be a dictionary or ordered list")
    if np.any(table < 0):
        raise ValueError("image table is incomplete")
    return table


def _ordered_image_bits(images: Sequence[object], L: int, R: int) -> tuple[list[str], np.ndarray]:
    if len(images) != 1 << L:
        raise ValueError(f"image table has {len(images)} rows, expected {1 << L}")
    rows: list[str] = []
    for row, image in enumerate(images):
        if not isinstance(image, str) or len(image) != R:
            raise ValueError(f"image row {row} must be a {R}-bit string")
        rows.append(image)
    raw = np.frombuffer("".join(rows).encode("ascii"), dtype=np.uint8)
    bits = raw.reshape(1 << L, R)
    invalid = (bits != ord("0")) & (bits != ord("1"))
    if np.any(invalid):
        row = int(np.flatnonzero(invalid.any(axis=1))[0])
        raise ValueError(f"image row {row} must contain only 0/1 bits")
    return rows, bits


def _normalize_images(images: object, L: int, R: int) -> list[str]:
    if isinstance(images, list | tuple):
        rows, _ = _ordered_image_bits(images, L, R)
        return rows
    table = _image_table(images, L, R)
    return ["".join(str(int(bit)) for bit in row) for row in table]


def contraction_coeffs(contraction: dict, n: int | None = None) -> tuple[list[int], int]:
    if "coeffs" in contraction:
        coeffs = [int(value) for value in contraction["coeffs"]]
        if n is None:
            n = infer_n(len(coeffs))
        elif len(coeffs) != dim(n):
            raise ValueError(f"coefficients have width {len(coeffs)}, expected {dim(n)} for n={n}")
        return coeffs, n

    terms: list[tuple[int, frozenset[int], int]] = []
    for sign, key in ((1, "lhs"), (-1, "rhs")):
        side = contraction.get(key)
        if not isinstance(side, list):
            raise ValueError("minimal contraction records must contain list-valued lhs and rhs")
        terms.extend((sign, term, coefficient) for term, coefficient in map(_term_and_coefficient, side))
    if n is None:
        max_party = max((party for _, term, _ in terms for party in term), default=0)
        n = max_party + 1

    coeffs = [0] * dim(n)
    index = subset_index_map(n)
    for sign, term, coefficient in terms:
        if not term or max(term) >= n:
            raise ValueError(f"term {sorted(term)} is outside n={n}")
        coeffs[index[term]] += sign * coefficient
    return coeffs, n


def normalize_contraction(contraction: dict, n: int | None = None) -> dict:
    coeffs, inferred_n = contraction_coeffs(contraction, n)
    return minimal_contraction(coeffs, inferred_n, contraction)


def _packed_tail_paths(path: str | Path) -> tuple[Path, Path]:
    source = json_path(path, "contraction")
    return (
        source.with_name(f"{source.stem}-tail.packbits.zst"),
        source.with_name(f"{source.stem}-tail.index.json"),
    )


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
        if self._facet_start != len(self._prefix):
            raise ValueError(
                f"packed contraction stream starts at {self._facet_start}, expected prefix length {len(self._prefix)}"
            )
        if self._facet_start < 0 or self._raw_size < 0 or self._compressed_size < 0:
            raise ValueError("packed contraction stream has invalid size metadata")
        if int(index.get("record_count", -1)) != len(self._records):
            raise ValueError("packed contraction stream record count does not match its records")
        expected_facets = self._facet_start + len(self._records)
        if len(facet_rows) != expected_facets:
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

    def __getitem__(self, index: int | slice) -> dict | list[dict]:
        if isinstance(index, slice):
            return list(iter(self))[index]
        position = int(index)
        if position < 0:
            position += len(self)
        if position < 0 or position >= len(self):
            raise IndexError(position)
        if position < self._facet_start:
            return self._prefix[position]
        for current, record in enumerate(self._iter_tail(), start=self._facet_start):
            if current == position:
                return record
        raise IndexError(position)

    def __iter__(self) -> Iterator[dict]:
        yield from self._prefix
        yield from self._iter_tail()

    def _iter_tail(self) -> Iterator[dict]:
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
                    yield minimal_contraction(
                        self._facet_rows[offset], self._n, {"images": _encoded_image_rows(payload, L, R)}
                    )
                if reader.read(1):
                    raise ValueError("packed contraction stream has bytes beyond its indexed records")
        if raw_size != self._raw_size:
            raise ValueError(f"packed contraction stream raw size {raw_size} does not match {self._raw_size}")
        if digest.hexdigest() != self._raw_sha256:
            raise ValueError("packed contraction stream raw SHA-256 mismatch")


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
        return ContractionRecords(
            (),
            n=int(n),
            facet_rows=facet_rows,
            data_path=packed_path,
            index={**payload, "facet_start": 0},
        )
    if not isinstance(payload, list):
        raise ValueError(f"expected a list of contractions or packed manifest in {source}")
    prefix = [normalize_contraction(record) for record in payload]
    packed_path, index_path = _packed_tail_paths(source)
    if not index_path.exists() and not packed_path.exists():
        return prefix
    if not index_path.is_file() or not packed_path.is_file():
        raise FileNotFoundError("packed contraction tail requires both its data and index files")
    if facet_rows is None:
        raise ValueError("facet_rows are required to reconstruct a packed contraction tail")
    if n is None:
        n = infer_n(len(facet_rows[0]))
    index = json.loads(index_path.read_text(encoding="utf-8"))
    if not isinstance(index, dict):
        raise ValueError(f"packed contraction tail index is not an object: {index_path}")
    if int(index.get("schema_version", -1)) != 1 or index.get("kind") != "packed-contraction-tail":
        raise ValueError(f"unsupported packed contraction tail index: {index_path}")
    if int(index.get("n", -1)) != int(n):
        raise ValueError(f"packed contraction tail n={index.get('n')!r}, expected {n}")
    return ContractionRecords(prefix, n=int(n), facet_rows=facet_rows, data_path=packed_path, index=index)


def write_contractions(path: str | Path, contractions: Iterable[dict]) -> None:
    target = json_path(path, "contraction")
    save_json_records(target, (normalize_contraction(record) for record in contractions))


@cache
def _cube_left_masks(L: int) -> tuple[np.ndarray, ...]:
    vertices = np.arange(1 << L, dtype=np.int64)
    return tuple(vertices[((vertices >> bit) & 1) == 0] for bit in range(L))


def check_contraction(
    coeffs: Sequence[int] | None,
    n: int | None,
    contraction: dict,
) -> dict:
    """Verify a contraction certificate.

    If ``coeffs`` or ``n`` is omitted, they are read from the certificate.
    Minimal records with ``lhs``, ``rhs``, and ``images`` are also accepted.
    """
    if n is None:
        raw_n = contraction.get("n")
        if raw_n is not None:
            n = int(raw_n)
    if coeffs is None:
        try:
            coeffs, n = contraction_coeffs(contraction, n)
        except (TypeError, ValueError) as exc:
            return {"ok": False, "errors": [str(exc)]}
    if n is None and coeffs is not None:
        n = infer_n(len(coeffs))
    if coeffs is None or n is None:
        return {"ok": False, "errors": ["coefficients and n could not be inferred"]}

    problem, info = _build_problem(coeffs, n)
    errors: list[str] = []
    if problem is None:
        return {"ok": info.get("status") == "proved", "errors": [] if info.get("status") == "proved" else [str(info)]}

    try:
        table = _image_table(contraction.get("images"), problem.L, problem.R)
    except ValueError as exc:
        return {"ok": False, "errors": [str(exc)], "n": problem.n, "L": problem.L, "R": problem.R}
    for point, image in problem.boundary.items():
        if not np.array_equal(table[bit_mask(point)], np.asarray(image, dtype=np.int8)):
            errors.append(f"boundary mismatch at {encode_bits(point)}")

    checked_pairs = 0
    if not errors:
        left_masks = _cube_left_masks(problem.L)
        for bit, bound in enumerate(problem.alpha):
            left = left_masks[bit]
            right = left | (1 << bit)
            distances = np.count_nonzero(table[left] != table[right], axis=1)
            violations = np.flatnonzero(distances > bound)
            if violations.size:
                offset = int(violations[0])
                checked_pairs += offset + 1
                left_bits = bit_tuple(int(left[offset]), problem.L)
                right_bits = bit_tuple(int(right[offset]), problem.L)
                errors.append(
                    f"Lipschitz violation {encode_bits(left_bits)}-{encode_bits(right_bits)}: "
                    f"d_beta={int(distances[offset])} > d_alpha={bound}"
                )
                break
            checked_pairs += len(left)
    return {
        "ok": not errors,
        "errors": errors,
        "checked_pairs": checked_pairs,
        "cube_size": 1 << problem.L,
        "n": problem.n,
        "L": problem.L,
        "R": problem.R,
    }
