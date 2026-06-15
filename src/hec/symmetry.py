"""Symmetry actions and orbit representatives for HEC vectors."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from functools import cache
from itertools import permutations

import numpy as np

from .coordinates import dim, row_to_array, subset_index_map, subsets


@cache
def permutation_maps(n: int) -> tuple[np.ndarray, ...]:
    """Unique S_{n+1} maps in source-index -> target-index form."""
    idx = subset_index_map(n)
    augmented = set(range(n + 1))
    maps: list[np.ndarray] = []
    seen: set[tuple[int, ...]] = set()
    for perm in permutations(range(n + 1)):
        target = np.empty(dim(n), dtype=np.int32)
        for source_index, sub in enumerate(subsets(n)):
            image = {perm[item] for item in sub}
            if n in image:
                image = augmented - image
            target[source_index] = idx[frozenset(image)]
        key = tuple(int(value) for value in target)
        if key not in seen:
            seen.add(key)
            maps.append(target)
    return tuple(maps)


@cache
def permutation_array(n: int) -> np.ndarray:
    maps = np.asarray(permutation_maps(n), dtype=np.int64)
    maps.setflags(write=False)
    return maps


def permute_vector(row: Sequence[int | float], n: int, perm_index: int | np.ndarray) -> np.ndarray:
    arr = row_to_array(row, n, dtype=np.asarray(row).dtype)
    mapping = permutation_maps(n)[perm_index] if isinstance(perm_index, int) else perm_index
    out = np.empty_like(arr)
    out[mapping] = arr
    return out


def permuted_vectors(row: Sequence[int | float], n: int) -> np.ndarray:
    arr = row_to_array(row, n, dtype=np.asarray(row).dtype)
    maps = permutation_array(n)
    out = np.empty((len(maps), arr.size), dtype=arr.dtype)
    out[np.arange(len(maps))[:, None], maps] = arr
    return out


def canonical_vector(row: Sequence[int | float], n: int) -> tuple[int | float, ...]:
    return min(tuple(image.tolist()) for image in permuted_vectors(row, n))


def symmetry_representative_indices(rows: Iterable[Sequence[int | float]], n: int) -> list[int]:
    seen: set[tuple[int | float, ...]] = set()
    indices: list[int] = []
    for index, row in enumerate(rows):
        key = canonical_vector(row, n)
        if key in seen:
            continue
        seen.add(key)
        indices.append(index)
    return indices


def symmetry_representatives(rows: Iterable[Sequence[int | float]], n: int) -> list[tuple[int | float, ...]]:
    records = [tuple(row) for row in rows]
    return [records[index] for index in symmetry_representative_indices(records, n)]
