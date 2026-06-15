"""HEC coordinate conventions and entropy-vector helpers.

Entropy vectors are indexed by non-empty subsets of ``{0, ..., n-1}`` in
cardinality-then-lexicographic order.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from functools import cache
from itertools import combinations

import numpy as np


def dim(n: int) -> int:
    return (1 << n) - 1


def infer_n(vector_length: int) -> int:
    size = int(vector_length) + 1
    if vector_length < 1 or size & (size - 1):
        raise ValueError(f"expected vector length 2^n - 1, got {vector_length}")
    return size.bit_length() - 1


def party_labels(n: int) -> list[str]:
    labels = [chr(ord("A") + i) if i < 26 else f"P{i + 1}" for i in range(n)]
    return labels + ["O"]


@cache
def subsets(n: int) -> tuple[tuple[int, ...], ...]:
    out: list[tuple[int, ...]] = []
    for k in range(1, n + 1):
        out.extend(combinations(range(n), k))
    return tuple(out)


@cache
def subset_index_map(n: int) -> dict[frozenset[int], int]:
    return {frozenset(s): i for i, s in enumerate(subsets(n))}


def row_to_array(row: Sequence[int | float], n: int | None = None, *, dtype=np.int64) -> np.ndarray:
    arr = np.asarray(row, dtype=dtype)
    if n is not None and arr.shape != (dim(n),):
        raise ValueError(f"expected vector length {dim(n)} for n={n}, got {arr.shape}")
    return arr


def primitive_vector(row: Sequence[int | float], *, tol: float = 1e-9) -> tuple[int, ...] | None:
    arr = np.asarray(row)
    if np.issubdtype(arr.dtype, np.floating):
        rounded = np.rint(arr)
        if not np.allclose(arr, rounded, atol=tol):
            return None
        arr = rounded.astype(np.int64)
    else:
        arr = arr.astype(np.int64)
    factor = 0
    values = [int(value) for value in arr.tolist()]
    for value in values:
        factor = math.gcd(factor, abs(value))
    if factor == 0:
        return None
    return tuple(value // factor for value in values)


def parse_inequality(
    coeffs: Sequence[int | float],
    n: int,
) -> tuple[list[frozenset[int]], list[int], list[frozenset[int]], list[int]]:
    raw = row_to_array(coeffs, n, dtype=np.float64)
    rounded = np.rint(raw)
    if not np.allclose(raw, rounded, atol=1e-9, rtol=0.0):
        raise ValueError("contraction inequalities require integer coefficients")
    arr = rounded.astype(np.int64)
    lhs_sets: list[frozenset[int]] = []
    lhs_coeffs: list[int] = []
    rhs_sets: list[frozenset[int]] = []
    rhs_coeffs: list[int] = []
    for subset, raw_coeff in zip(subsets(n), arr.tolist(), strict=True):
        coeff = int(raw_coeff)
        if coeff > 0:
            lhs_sets.append(frozenset(subset))
            lhs_coeffs.append(coeff)
        elif coeff < 0:
            rhs_sets.append(frozenset(subset))
            rhs_coeffs.append(-coeff)
    return lhs_sets, lhs_coeffs, rhs_sets, rhs_coeffs


def occurrence_vectors(
    lhs_sets: Sequence[frozenset[int]],
    rhs_sets: Sequence[frozenset[int]],
    rhs_coeffs: Sequence[int],
    n: int,
) -> list[tuple[tuple[int, ...], tuple[int, ...]]]:
    out: list[tuple[tuple[int, ...], tuple[int, ...]]] = []
    for party in range(n):
        x = tuple(1 if party in term else 0 for term in lhs_sets)
        y_bits: list[int] = []
        for term, multiplicity in zip(rhs_sets, rhs_coeffs, strict=True):
            y_bits.extend([1 if party in term else 0] * int(multiplicity))
        out.append((x, tuple(y_bits)))
    out.append((tuple([0] * len(lhs_sets)), tuple([0] * sum(rhs_coeffs))))
    return out
