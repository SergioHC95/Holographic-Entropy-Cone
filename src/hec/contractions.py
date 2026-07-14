"""Contraction-map search and verification for HEC inequalities.

The public API is intentionally small:

``find_contraction`` searches for a contraction certificate.
``check_contraction`` verifies a saved or in-memory certificate.
"""

from __future__ import annotations

import re
import time
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from functools import cache
from pathlib import Path

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
from .serialization import json_path, load_json_records, save_json_records

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


def read_contractions(path: str | Path) -> list[dict]:
    return load_json_records(path, "contraction", normalize_contraction)


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
