"""Small modular rank kernels."""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
from numba import njit

from .coordinates import dim, row_to_array
from .symmetry import permutation_array

RANK_PRIME = 2_147_483_647


def _orbit_representatives(candidates: np.ndarray, inverse_maps: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Exact first-occurrence representatives for a bounded prefix of orbits.

    Equal integer rows, not hashes or approximate equality, establish each
    duplicate. Unprepared candidates still use every permutation. This is
    transient shared input preprocessing, never cached rank acceptance.
    """
    count = min(64, candidates.shape[0])
    if inverse_maps.shape[0] > np.iinfo(np.int32).max:
        raise ValueError("exact orbit representative index capacity exceeded")
    indices = np.zeros((count, inverse_maps.shape[0]), dtype=np.int32)
    counts = np.zeros(count, dtype=np.int64)
    for index in range(count):
        row = candidates[index]
        # Narrow only after proving the complete integer range fits exactly.
        # This reduces temporary comparison bandwidth; no artifact is changed.
        low, high = int(row.min(initial=0)), int(row.max(initial=0))
        dtype = np.uint8 if 0 <= low and high <= 255 else np.int16 if -32768 <= low and high <= 32767 else np.int64
        images = row[inverse_maps].astype(dtype)
        _, first = np.unique(images, axis=0, return_index=True)
        first.sort()  # Preserve the original order of distinct image discovery.
        counts[index] = len(first)
        indices[index, : len(first)] = first
    indices.setflags(write=False)
    counts.setflags(write=False)
    return indices, counts


def prepare_rank_candidates(
    candidates: Sequence[Sequence[int]],
    n: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, int, np.ndarray, np.ndarray]:
    """Convert shared rank-check inputs once for repeated support-rank calls."""
    return _prepare_rank_candidates(candidates, n, shared=True)


def _prepare_rank_candidates(candidates, n, *, shared):
    width = dim(n)
    target = width - 1
    # Catalogue sequences know their row count. Fill their one owned matrix
    # directly instead of retaining another NumPy array per row until stacking.
    # Keep the iterable fallback for callers without sequence metadata.
    try:
        count = len(candidates)
    except TypeError:
        candidate_arr = np.asarray([row_to_array(row, n, dtype=np.int64) for row in candidates], dtype=np.int64)
    else:
        candidate_arr = np.empty((count, width), dtype=np.int64)
        filled = 0
        for row in candidates:
            if filled == count:
                raise ValueError("rank candidate count changed during preparation")
            candidate_arr[filled] = row_to_array(row, n, dtype=np.int64)
            filled += 1
        if filled != count:
            raise ValueError("rank candidate count changed during preparation")
    # Lossless range-proven storage, never clipping or floating conversion.
    # Rank arithmetic still uses the existing int64 work/basis arrays.
    low, high = int(candidate_arr.min(initial=0)), int(candidate_arr.max(initial=0))
    candidate_dtype = _signed_storage_dtype(low, high)
    if candidate_arr.dtype != candidate_dtype:
        candidate_arr = candidate_arr.astype(candidate_dtype)
    candidate_counts = np.count_nonzero(candidate_arr, axis=1).astype(np.int64)
    max_count = int(candidate_counts.max()) if candidate_counts.size else 0
    # One-off dense queries can select only the dense or sparse-fixed kernel;
    # neither reads sparse candidate copies. Shared preparation still exposes
    # all representations for callers that explicitly exercise each kernel.
    if shared or max_count * 2 < width:
        candidate_indices = np.zeros(
            (candidate_arr.shape[0], max_count), dtype=_signed_storage_dtype(0, max(0, width - 1))
        )
        candidate_values = np.zeros((candidate_arr.shape[0], max_count), dtype=candidate_dtype)
        for row_index, row in enumerate(candidate_arr):
            nonzero = np.flatnonzero(row)
            candidate_indices[row_index, : nonzero.size] = nonzero
            candidate_values[row_index, : nonzero.size] = row[nonzero]
    else:
        candidate_indices = np.empty((0, 0), dtype=np.int64)
        candidate_values = np.empty((0, 0), dtype=np.int64)
    maps = permutation_array(n)
    inverse_maps = np.empty_like(maps)
    source_indices = np.arange(width, dtype=np.int64)
    for map_index, mapping in enumerate(maps):
        inverse_maps[map_index, mapping] = source_indices
    inverse_maps.setflags(write=False)
    if shared:
        orbit_indices, orbit_counts = _orbit_representatives(candidate_arr, inverse_maps)
    else:
        # One-off calls must not pay for preprocessing that repeated callers
        # amortize. Empty representative metadata means all exact images.
        orbit_indices = np.empty((0, maps.shape[0]), dtype=np.int32)
        orbit_counts = np.empty(0, dtype=np.int64)
    return (
        candidate_arr,
        maps,
        inverse_maps,
        candidate_indices,
        candidate_values,
        candidate_counts,
        target,
        orbit_indices,
        orbit_counts,
    )


def _signed_storage_dtype(low: int, high: int):
    for dtype in (np.int8, np.int16, np.int32, np.int64):
        limits = np.iinfo(dtype)
        if limits.min <= low <= high <= limits.max:
            return dtype
    raise ValueError("rank candidates exceed exact signed 64-bit storage")


def support_rank(fixed: Sequence[int], candidates: Sequence[Sequence[int]], n: int) -> dict:
    prepared = _prepare_rank_candidates(candidates, n, shared=False)
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
    orbit_indices: np.ndarray,
    orbit_counts: np.ndarray,
) -> dict:
    if target == 0:
        return {"rank": 0, "target_rank": 0, "saturating_images": 0, "tested_images": 0}

    fixed_arr = row_to_array(fixed, n, dtype=np.int64)
    nonzero = np.flatnonzero(fixed_arr)
    if nonzero.size * candidate_arr.shape[0] <= int(candidate_counts.sum()):
        rank, saturating_images, tested_images = saturating_image_rank_sparse_fixed(
            nonzero.astype(np.int64),
            fixed_arr[nonzero].astype(np.int64),
            candidate_arr,
            maps,
            inverse_maps,
            target,
            orbit_indices,
            orbit_counts,
        )
    elif int(candidate_counts.max()) * 2 < fixed_arr.size:
        rank, saturating_images, tested_images = saturating_image_rank_sparse_candidates(
            fixed_arr, candidate_indices, candidate_values, candidate_counts, maps, target, orbit_indices, orbit_counts
        )
    else:
        rank, saturating_images, tested_images = saturating_image_rank(
            fixed_arr, candidate_arr, maps, target, orbit_indices, orbit_counts
        )
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
    orbit_indices: np.ndarray,
    orbit_counts: np.ndarray,
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
        orbit_indices,
        orbit_counts,
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
    # A normalized pivot row has zero columns before its pivot. Eliminating
    # left-to-right never changes those cleared columns, so neither rescanning
    # nor modular multiplication of that zero prefix is necessary.
    for pivot in range(width):
        if row[pivot] == 0:
            continue
        if not has_pivot[pivot]:
            inverse = 1 if row[pivot] == 1 else _mod_pow(row[pivot], RANK_PRIME - 2, RANK_PRIME)
            for index in range(pivot):
                basis[pivot, index] = 0
            basis[pivot, pivot] = 1
            for index in range(pivot + 1, width):
                basis[pivot, index] = (row[index] * inverse) % RANK_PRIME
            has_pivot[pivot] = True
            rank += 1
            return rank, rank == target
        factor = row[pivot]
        row[pivot] = 0
        for index in range(pivot + 1, width):
            row[index] = (row[index] - factor * basis[pivot, index]) % RANK_PRIME
    return rank, False


@njit(cache=True, nogil=True)
def saturating_image_rank(
    fixed: np.ndarray,
    candidates: np.ndarray,
    maps: np.ndarray,
    target: int,
    orbit_indices: np.ndarray,
    orbit_counts: np.ndarray,
) -> tuple[int, int, int]:
    width = fixed.shape[0]
    basis = np.zeros((width, width), dtype=np.int64)
    has_pivot = np.zeros(width, dtype=np.bool_)
    row = np.empty(width, dtype=np.int64)
    rank = 0
    saturating_images = 0
    tested_images = 0

    for candidate_index in range(candidates.shape[0]):
        candidate = candidates[candidate_index]
        prepared = candidate_index < orbit_counts.shape[0]
        count = orbit_counts[candidate_index] if prepared else maps.shape[0]
        for position in range(count):
            map_index = orbit_indices[candidate_index, position] if prepared else position
            mapping = maps[map_index]
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
    orbit_indices: np.ndarray,
    orbit_counts: np.ndarray,
) -> tuple[int, int, int]:
    width = maps.shape[1]
    basis = np.zeros((width, width), dtype=np.int64)
    has_pivot = np.zeros(width, dtype=np.bool_)
    row = np.empty(width, dtype=np.int64)
    rank = 0
    saturating_images = 0
    tested_images = 0

    for candidate_index in range(candidates.shape[0]):
        candidate = candidates[candidate_index]
        prepared = candidate_index < orbit_counts.shape[0]
        count = orbit_counts[candidate_index] if prepared else maps.shape[0]
        for position in range(count):
            map_index = orbit_indices[candidate_index, position] if prepared else position
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
    orbit_indices: np.ndarray,
    orbit_counts: np.ndarray,
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
        prepared = candidate_index < orbit_counts.shape[0]
        image_count = orbit_counts[candidate_index] if prepared else maps.shape[0]
        for position in range(image_count):
            map_index = orbit_indices[candidate_index, position] if prepared else position
            mapping = maps[map_index]
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
