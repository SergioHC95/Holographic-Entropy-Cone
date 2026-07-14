"""HEC coordinate conventions and entropy-vector helpers.

Entropy vectors are indexed by non-empty subsets of ``{0, ..., n-1}`` in
cardinality-then-lexicographic order.
"""

from __future__ import annotations

from collections.abc import Sequence
from functools import cache
from itertools import combinations

import numpy as np

_PARTY_ALPHABET = tuple(chr(code) for code in range(ord("A"), ord("Z") + 1) if chr(code) != "O")


def dim(n: int) -> int:
    return (1 << n) - 1


def infer_n(vector_length: int) -> int:
    size = int(vector_length) + 1
    if vector_length < 1 or size & (size - 1):
        raise ValueError(f"expected vector length 2^n - 1, got {vector_length}")
    return size.bit_length() - 1


def party_labels(n: int) -> list[str]:
    if isinstance(n, bool) or not isinstance(n, int) or n < 0:
        raise ValueError("party count must be a non-negative integer")
    # ``O`` is the purifier, so physical labels use A..N, skip O, and continue
    # through the remaining letters before switching to P<number>.
    labels = list(_PARTY_ALPHABET[:n])
    labels.extend(f"P{i + 1}" for i in range(len(labels), n))
    return labels + ["O"]


def party_index(label: str, n: int | None = None) -> int:
    """Decode one physical-party label produced by :func:`party_labels`."""

    if label in _PARTY_ALPHABET:
        index = _PARTY_ALPHABET.index(label)
    elif label.startswith("P") and label[1:].isdigit() and int(label[1:]) > len(_PARTY_ALPHABET):
        index = int(label[1:]) - 1
    else:
        raise ValueError(f"invalid physical-party label {label!r}")
    if n is not None and not 0 <= index < n:
        raise ValueError(f"party label {label!r} is outside n={n}")
    return index


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
