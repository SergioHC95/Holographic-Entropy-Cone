"""Bounded-memory exact integer-table verification, independent of the solver.

NumPy is only an integer SIMD engine here. Verified group bounds make every
subtraction, absolute value and sum safe in int64. Larger arithmetic goes to
the arbitrary-precision reference, never to a floating-point approximation.
"""

from __future__ import annotations

import numpy as np

from .count_proofs import CountGeometry


def supported(problem: CountGeometry) -> bool:
    row_bits = sum(capacity.bit_length() for capacity in problem.beta)
    return sum(problem.beta) <= 1 << 62 and (problem.vertices - 1) * row_bits < 1 << 63


class IntegerRows:
    def __init__(self, problem: CountGeometry, data: bytes):
        self.problem = problem
        self.widths = [capacity.bit_length() for capacity in problem.beta]
        self.row_bits = sum(self.widths)
        self.data = np.frombuffer(data, dtype=np.uint8)
        bits = problem.vertices * self.row_bits
        if len(data) != (bits + 7) // 8 or (bits % 8 and data[-1] >> (bits % 8)):
            raise ValueError("integer table byte length/padding mismatch")

    def _bits(self, positions: np.ndarray, width: int) -> np.ndarray:
        byte, shift = positions >> 3, (positions & 7).astype(np.uint64)
        values = np.zeros(len(positions), dtype=np.uint64)
        for k in range((width + 14) // 8):
            addresses = byte + k
            piece = self.data[np.minimum(addresses, len(self.data) - 1)].astype(np.uint64)
            piece *= addresses < len(self.data)
            values |= (piece >> shift) if k == 0 else (piece << (8 * k - shift))
        if width < 64:
            values &= (1 << width) - 1
        return values

    def rows(self, vertices: np.ndarray) -> np.ndarray:
        values = np.empty((len(vertices), self.problem.G), dtype=np.int64)
        if not self.row_bits:
            return values
        positions = np.asarray(vertices, dtype=np.int64) * self.row_bits
        whole = self._bits(positions, self.row_bits) if self.row_bits <= 64 else None
        offset = 0
        for group, width in enumerate(self.widths):
            if whole is not None:
                column = (whole >> offset) & ((1 << width) - 1)
            else:
                column = self._bits(positions + offset, width)
            values[:, group] = column
            offset += width
        return values


def verify_integer_table(problem: CountGeometry, data: bytes, batch: int = 4096) -> int:
    if not supported(problem):
        raise ValueError("integer SIMD audit requires the exact arbitrary-precision reference for this geometry")
    table = IntegerRows(problem, data)
    bounds = np.array(problem.beta, dtype=np.int64)
    for first in range(0, problem.vertices, batch):
        vertices = np.arange(first, min(first + batch, problem.vertices), dtype=np.int64)
        if np.any(table.rows(vertices) > bounds):
            raise ValueError("count outside its RHS group bounds")
    for vertex, expected in problem.boundary:
        image = tuple(int(value) for value in table.rows(np.array([vertex], dtype=np.int64))[0])
        if image != expected:
            raise ValueError("party/purifier occurrence boundary mismatch")
    checked = 0
    for axis, capacity in enumerate(problem.alpha):
        side = 1 << axis
        for first in range(0, problem.vertices // 2, batch):
            compact = np.arange(first, min(first + batch, problem.vertices // 2), dtype=np.int64)
            left = (compact & (side - 1)) | ((compact >> axis) << (axis + 1))
            distances = np.abs(table.rows(left) - table.rows(left | side)).sum(axis=1, dtype=np.int64)
            # A huge exact capacity does not get converted to a NumPy float.
            if capacity < 1 << 63 and np.any(distances > capacity):
                raise ValueError(f"contraction edge violation on axis {axis}")
            checked += len(left)
    if checked != problem.L * (problem.vertices // 2):
        raise ValueError("original-cube edge coverage mismatch")
    return checked
