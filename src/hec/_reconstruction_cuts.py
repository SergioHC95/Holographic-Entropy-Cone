"""Bounded exact evaluation of already validated integral cut seed programs.

This is evaluation, not mathematical acceptance. The caller derives the entire
compatible domain and retains all bounds, boundaries, coupled-edge and separate
original-cube checks. The scalar query evaluator remains an independent control.
"""

from __future__ import annotations

from functools import lru_cache

import numpy as np


def cut_integer_rows(vertices, axes, terms, groups, *, cache_bytes=32 * 1024**2):
    """Evaluate every threshold layer without Fraction objects or per-cell terms.

    Python integers represent literal truth sets, with incompatible vertices
    absent and padding bits masked out. Each output is a sum of exactly
    ``len(group)`` Boolean indicators, so the uint64 accumulator cannot overflow:
    a Python sequence cannot have 2**64 entries. No coefficient is rounded or
    cast to a narrow integer type. Cached term bitsets have a bounded budget;
    large term counts never allocate one truth set per program term at once.
    """
    if type(cache_bytes) is not int or cache_bytes < 1:
        raise ValueError("cut evaluation cache budget must be a positive exact integer")
    count = len(vertices)
    values = np.asarray(vertices, dtype=np.uint64)
    universe, literals = (1 << count) - 1, []
    for axis in range(axes):
        positive = int.from_bytes(
            np.packbits(((values >> axis) & 1).astype(np.uint8), bitorder="little").tobytes(), "little"
        )
        literals.append((universe ^ positive, positive))
    width = (count + 7) // 8
    # Conservatively allow twice the packed payload plus object overhead for
    # each Python bigint. Dict/cache bookkeeping is additionally bounded by
    # the fixed entry ceiling. This is not a measured peak-RSS guarantee.
    entries = min(16384, cache_bytes // max(1, 2 * width + 64))

    @lru_cache(maxsize=entries)
    def hits(reference):
        ones, zeros = terms[reference]
        covered, mask = universe, ones | zeros
        while mask and covered:
            bit = mask & -mask
            covered &= literals[bit.bit_length() - 1][int(bool(ones & bit))]
            mask ^= bit
        return covered

    matrix = np.zeros((count, len(groups)), dtype=np.uint64)
    for group, layers in enumerate(groups):
        for layer in layers:
            covered = 0
            for reference in layer:
                covered |= hits(reference)
            packed = np.frombuffer(covered.to_bytes(width, "little"), dtype=np.uint8)
            matrix[:, group] += np.unpackbits(packed, bitorder="little")[:count].astype(np.uint64)
    return tuple(tuple(row) for row in matrix.tolist())
