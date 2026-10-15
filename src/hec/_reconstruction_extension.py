"""Exact cancel/fill/threshold full-cube construction and direct seed lookup.

No solver, float, stochastic particles, or numerical order projection is used.
This is the sole standardized full-map extension.
"""

from __future__ import annotations

import math
from fractions import Fraction
from functools import lru_cache

from .count_proofs import INTEGER_ROWS, RATIONAL_ROWS, CountGeometry, decode_rows, row_bytes


class CompatibleRank:
    """Exact ordinal in the ascending complete compatible domain."""

    def __init__(self, problem: CountGeometry):
        self.problem = problem
        predecessors, conflicts = [0] * problem.L, [0] * problem.L
        for i, j in problem.nested:
            if i >= j:
                raise ValueError("source supports must put proper subsets first")
            predecessors[j] |= 1 << i
        for i, j in problem.disjoint:
            conflicts[i] |= 1 << j
            conflicts[j] |= 1 << i
        self.predecessors, self.conflicts = predecessors, conflicts

        @lru_cache(None)
        def completions(axis: int, zeros: int) -> int:
            if axis < 0:
                return 1
            lower = (1 << axis) - 1
            zero = completions(axis - 1, (zeros | predecessors[axis]) & lower)
            if zeros >> axis & 1:
                return zero
            return zero + completions(axis - 1, (zeros | conflicts[axis]) & lower)

        self.completions = completions
        self.count = completions(problem.L - 1, 0)

    def rank(self, vertex: int) -> int:
        if type(vertex) is not int or not 0 <= vertex < self.problem.vertices:
            raise ValueError("vertex outside source cube")
        zeros, ordinal = 0, 0
        for axis in range(self.problem.L - 1, -1, -1):
            lower = (1 << axis) - 1
            if vertex >> axis & 1:
                if zeros >> axis & 1:
                    raise ValueError("vertex is not compatible")
                ordinal += self.completions(axis - 1, (zeros | self.predecessors[axis]) & lower)
                zeros = (zeros | self.conflicts[axis]) & lower
            else:
                zeros = (zeros | self.predecessors[axis]) & lower
        return ordinal


class SeedLookup:
    """Look up integral rows directly, without enumerating C or a vertex dict."""

    def __init__(self, problem: CountGeometry, payload: dict):
        self.problem = problem
        self.domain = CompatibleRank(problem)
        self.payload, self.data = row_bytes(payload)
        if self.payload["count"] != self.domain.count:
            raise ValueError("seed does not cover the complete compatible domain")
        self.widths = tuple(cap.bit_length() for cap in problem.beta)
        self.row_bits = sum(self.widths)
        self.rows = None
        if self.payload["encoding"] == INTEGER_ROWS:
            bits = self.domain.count * self.row_bits
            if len(self.data) != (bits + 7) // 8 or (bits % 8 and self.data[-1] >> (bits % 8)):
                raise ValueError("integer seed byte length/padding mismatch")
        elif self.payload["encoding"] == RATIONAL_ROWS:
            self.rows = list(decode_rows(problem, payload))
        else:
            raise ValueError("unsupported seed row encoding")

    def __getitem__(self, vertex: int) -> tuple[Fraction, ...]:
        ordinal = self.domain.rank(vertex)
        if self.rows is not None:
            denominator, values = self.rows[ordinal]
        else:
            denominator, cursor, values = 1, ordinal * self.row_bits, []
            for width in self.widths:
                byte, shift = divmod(cursor, 8)
                value = int.from_bytes(self.data[byte : (cursor + width + 7) // 8], "little") >> shift
                values.append(value & ((1 << width) - 1))
                cursor += width
        if any(value > denominator * cap for value, cap in zip(values, self.problem.beta, strict=True)):
            raise ValueError("seed count outside RHS group bounds")
        return tuple(Fraction(value, denominator) for value in values)


def clearing_scale(problem: CountGeometry, seed_scale: int) -> int:
    if len(set(problem.alpha)) <= 1:
        return seed_scale
    return seed_scale * math.lcm(*problem.alpha)


def transport_mass(problem: CountGeometry, vertex: int) -> tuple[int, ...]:
    mass = [cap * ((vertex >> i) & 1) for i, cap in enumerate(problem.alpha)]
    for i, j in problem.disjoint:
        difference = mass[i] - mass[j]
        mass[i], mass[j] = max(difference, 0), max(-difference, 0)
    for i, j in problem.nested:
        if i >= j:
            raise ValueError("source supports must put proper subsets first")
        total = mass[i] + mass[j]
        mass[i], mass[j] = max(total - problem.alpha[j], 0), min(total, problem.alpha[j])
    if any(not 0 <= value <= cap for value, cap in zip(mass, problem.alpha, strict=True)):
        raise ValueError("transport outside source capacities")
    if any(mass[i] and mass[j] for i, j in problem.disjoint):
        raise ValueError("transport disjoint conflict")
    if any(mass[i] and mass[j] != problem.alpha[j] for i, j in problem.nested):
        raise ValueError("one-pass transport nesting conflict")
    return tuple(mass)


def evaluate_transport(problem: CountGeometry, seed, vertex: int) -> tuple[Fraction, ...]:
    mass = transport_mass(problem, vertex)
    levels = tuple(Fraction(value, cap) for value, cap in zip(mass, problem.alpha, strict=True))
    previous, result = Fraction(0), [Fraction(0)] * problem.G
    for level in sorted(set(levels) | {Fraction(1)}):
        if level == previous:
            continue
        endpoint = sum(int(value >= level) << i for i, value in enumerate(levels))
        weight = level - previous
        for group, value in enumerate(seed[endpoint]):
            result[group] += weight * value
        previous = level
    if previous != 1:
        raise ValueError("threshold weights do not sum to one")
    return tuple(result)
