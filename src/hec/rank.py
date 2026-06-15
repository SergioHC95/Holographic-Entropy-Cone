"""Small modular rank kernels."""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
from numba import njit

from .coordinates import dim, row_to_array
from .symmetry import permutation_array

RANK_PRIME = 2_147_483_647


def prepare_rank_candidates(
    candidates: Sequence[Sequence[int]],
    n: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, int]:
    """Convert shared rank-check inputs once for repeated support-rank calls."""
    width = dim(n)
    target = width - 1
    candidate_arr = np.asarray([row_to_array(row, n, dtype=np.int64) for row in candidates], dtype=np.int64)
    candidate_counts = np.count_nonzero(candidate_arr, axis=1).astype(np.int64)
    max_count = int(candidate_counts.max()) if candidate_counts.size else 0
    candidate_indices = np.zeros((candidate_arr.shape[0], max_count), dtype=np.int64)
    candidate_values = np.zeros((candidate_arr.shape[0], max_count), dtype=np.int64)
    for row_index, row in enumerate(candidate_arr):
        nonzero = np.flatnonzero(row)
        candidate_indices[row_index, : nonzero.size] = nonzero
        candidate_values[row_index, : nonzero.size] = row[nonzero]
    maps = permutation_array(n)
    inverse_maps = np.empty_like(maps)
    source_indices = np.arange(width, dtype=np.int64)
    for map_index, mapping in enumerate(maps):
        inverse_maps[map_index, mapping] = source_indices
    inverse_maps.setflags(write=False)
    return candidate_arr, maps, inverse_maps, candidate_indices, candidate_values, candidate_counts, target


def support_rank(fixed: Sequence[int], candidates: Sequence[Sequence[int]], n: int) -> dict:
    prepared = prepare_rank_candidates(candidates, n)
    return support_rank_prepared(fixed, n, *prepared)


def support_rank_prepared(
    fixed: Sequence[int],
    n: int,
    candidate_arr: np.ndarray,
    maps: np.ndarray,
    inverse_maps: np.ndarray,
    candidate_indices: np.ndarray,
    candidate_values: np.ndarray,
    candidate_counts: np.ndarray,
    target: int,
) -> dict:
    if target == 0:
        return {"rank": 0, "target_rank": 0, "saturating_images": 0, "tested_images": 0}

    fixed_arr = row_to_array(fixed, n, dtype=np.int64)
    nonzero = np.flatnonzero(fixed_arr)
    if nonzero.size * candidate_arr.shape[0] <= int(candidate_counts.sum()):
        rank, saturating_images, tested_images = saturating_image_rank_sparse_fixed(
            nonzero.astype(np.int64), fixed_arr[nonzero].astype(np.int64), candidate_arr, maps, inverse_maps, target
        )
    elif int(candidate_counts.max()) * 2 < fixed_arr.size:
        rank, saturating_images, tested_images = saturating_image_rank_sparse_candidates(
            fixed_arr, candidate_indices, candidate_values, candidate_counts, maps, target
        )
    else:
        rank, saturating_images, tested_images = saturating_image_rank(fixed_arr, candidate_arr, maps, target)
    return {
        "rank": rank,
        "target_rank": target,
        "saturating_images": saturating_images,
        "tested_images": tested_images,
    }


def check_support_rank(fixed: Sequence[int], candidates: Sequence[Sequence[int]], n: int) -> dict:
    result = support_rank(fixed, candidates, n)
    return {"ok": result["rank"] == result["target_rank"], "n": n, **result}


def check_support_rank_prepared(
    fixed: Sequence[int],
    n: int,
    candidate_arr: np.ndarray,
    maps: np.ndarray,
    inverse_maps: np.ndarray,
    candidate_indices: np.ndarray,
    candidate_values: np.ndarray,
    candidate_counts: np.ndarray,
    target: int,
) -> dict:
    result = support_rank_prepared(
        fixed,
        n,
        candidate_arr,
        maps,
        inverse_maps,
        candidate_indices,
        candidate_values,
        candidate_counts,
        target,
    )
    return {"ok": result["rank"] == result["target_rank"], "n": n, **result}


@njit(cache=True, nogil=True)
def _mod_pow(base: int, exponent: int, modulus: int) -> int:
    result = 1
    value = base % modulus
    while exponent:
        if exponent & 1:
            result = (result * value) % modulus
        value = (value * value) % modulus
        exponent >>= 1
    return result


@njit(cache=True, nogil=True, inline="always")
def _insert_rank_row(
    row: np.ndarray,
    basis: np.ndarray,
    has_pivot: np.ndarray,
    rank: int,
    target: int,
    width: int,
) -> tuple[int, bool]:
    while True:
        pivot = -1
        for index in range(width):
            if row[index] != 0:
                pivot = index
                break
        if pivot < 0:
            break
        if not has_pivot[pivot]:
            inverse = _mod_pow(row[pivot], RANK_PRIME - 2, RANK_PRIME)
            for index in range(width):
                basis[pivot, index] = (row[index] * inverse) % RANK_PRIME
            has_pivot[pivot] = True
            rank += 1
            return rank, rank == target
        factor = row[pivot]
        for index in range(width):
            row[index] = (row[index] - factor * basis[pivot, index]) % RANK_PRIME
    return rank, False


@njit(cache=True, nogil=True)
def saturating_image_rank(
    fixed: np.ndarray,
    candidates: np.ndarray,
    maps: np.ndarray,
    target: int,
) -> tuple[int, int, int]:
    width = fixed.shape[0]
    basis = np.zeros((width, width), dtype=np.int64)
    has_pivot = np.zeros(width, dtype=np.bool_)
    row = np.empty(width, dtype=np.int64)
    rank = 0
    saturating_images = 0
    tested_images = 0

    for candidate in candidates:
        for mapping in maps:
            dot = 0
            for source in range(width):
                dot += fixed[mapping[source]] * candidate[source]
            tested_images += 1
            if dot != 0:
                continue

            saturating_images += 1
            for source in range(width):
                row[mapping[source]] = candidate[source] % RANK_PRIME

            rank, complete = _insert_rank_row(row, basis, has_pivot, rank, target, width)
            if complete:
                return rank, saturating_images, tested_images

    return rank, saturating_images, tested_images


@njit(cache=True, nogil=True)
def saturating_image_rank_sparse_fixed(
    fixed_indices: np.ndarray,
    fixed_values: np.ndarray,
    candidates: np.ndarray,
    maps: np.ndarray,
    inverse_maps: np.ndarray,
    target: int,
) -> tuple[int, int, int]:
    width = maps.shape[1]
    basis = np.zeros((width, width), dtype=np.int64)
    has_pivot = np.zeros(width, dtype=np.bool_)
    row = np.empty(width, dtype=np.int64)
    rank = 0
    saturating_images = 0
    tested_images = 0

    for candidate in candidates:
        for map_index in range(maps.shape[0]):
            inverse_mapping = inverse_maps[map_index]
            dot = 0
            for pos in range(fixed_indices.shape[0]):
                dot += fixed_values[pos] * candidate[inverse_mapping[fixed_indices[pos]]]
            tested_images += 1
            if dot != 0:
                continue

            saturating_images += 1
            mapping = maps[map_index]
            for source in range(width):
                row[mapping[source]] = candidate[source] % RANK_PRIME

            rank, complete = _insert_rank_row(row, basis, has_pivot, rank, target, width)
            if complete:
                return rank, saturating_images, tested_images

    return rank, saturating_images, tested_images


@njit(cache=True, nogil=True)
def saturating_image_rank_sparse_candidates(
    fixed: np.ndarray,
    candidate_indices: np.ndarray,
    candidate_values: np.ndarray,
    candidate_counts: np.ndarray,
    maps: np.ndarray,
    target: int,
) -> tuple[int, int, int]:
    width = fixed.shape[0]
    basis = np.zeros((width, width), dtype=np.int64)
    has_pivot = np.zeros(width, dtype=np.bool_)
    row = np.empty(width, dtype=np.int64)
    rank = 0
    saturating_images = 0
    tested_images = 0

    for candidate_index in range(candidate_indices.shape[0]):
        count = candidate_counts[candidate_index]
        for mapping in maps:
            dot = 0
            for pos in range(count):
                source = candidate_indices[candidate_index, pos]
                dot += fixed[mapping[source]] * candidate_values[candidate_index, pos]
            tested_images += 1
            if dot != 0:
                continue

            saturating_images += 1
            for index in range(width):
                row[index] = 0
            for pos in range(count):
                source = candidate_indices[candidate_index, pos]
                row[mapping[source]] = candidate_values[candidate_index, pos] % RANK_PRIME

            rank, complete = _insert_rank_row(row, basis, has_pivot, rank, target, width)
            if complete:
                return rank, saturating_images, tested_images

    return rank, saturating_images, tested_images
