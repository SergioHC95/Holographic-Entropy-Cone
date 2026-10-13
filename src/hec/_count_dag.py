"""Canonical reduced ordered scalar decision diagrams for exact count maps.

Scalar roots share terminals/nodes across RHS groups. This avoids the
exponential vector-leaf blowup even for a simple identity map. The independent
checker proves every original edge through exact joint cofactor maxima.
"""

from __future__ import annotations

import math
from fractions import Fraction
from functools import lru_cache

from .count_proofs import CountGeometry, decimal

KIND = "count-decision-dag/1"


def build(problem: CountGeometry, rows: list[tuple[int, tuple[int, ...]]]) -> tuple[dict, int]:
    if len(rows) != problem.vertices:
        raise ValueError("map does not cover its entire original cube")
    values = sorted({Fraction(value, q) for q, row in rows for value in row})
    terminals = {value: index for index, value in enumerate(values)}
    roots = [[terminals[Fraction(row[group], q)] for q, row in rows] for group in range(problem.G)]
    nodes = []
    for axis in range(problem.L):
        pairs = sorted(
            {
                (column[i], column[i + 1])
                for column in roots
                for i in range(0, len(column), 2)
                if column[i] != column[i + 1]
            }
        )
        refs = {}
        for left, right in pairs:
            refs[left, right] = len(values) + len(nodes)
            nodes.append([axis, left, right])
        roots = [
            [
                left if left == right else refs[left, right]
                for left, right in zip(column[::2], column[1::2], strict=True)
            ]
            for column in roots
        ]
    function = {
        "kind": KIND,
        "terminals": [[str(value.numerator), str(value.denominator)] for value in values],
        "nodes": nodes,
        "roots": [column[0] for column in roots],
    }
    return function, math.lcm(*(value.denominator for value in values))


class Diagram:
    def __init__(self, problem: CountGeometry, function: dict):
        if not isinstance(function, dict) or set(function) != {"kind", "terminals", "nodes", "roots"}:
            raise ValueError("invalid count decision diagram fields")
        if function["kind"] != KIND:
            raise ValueError("unsupported decision diagram version")
        if any(not isinstance(function[key], list) for key in ("terminals", "nodes", "roots")):
            raise ValueError("decision diagram arrays must be lists")
        self.values = []
        for terminal in function["terminals"]:
            if not isinstance(terminal, list) or len(terminal) != 2:
                raise ValueError("invalid rational terminal")
            numerator, denominator = map(decimal, terminal)
            if numerator < 0 or denominator < 1 or math.gcd(numerator, denominator) != 1:
                raise ValueError("terminal must be a nonnegative reduced rational")
            self.values.append(Fraction(numerator, denominator))
        if self.values != sorted(set(self.values)):
            raise ValueError("terminals must be numerically sorted and unique")
        self.nodes = []
        for node in function["nodes"]:
            if not isinstance(node, list) or len(node) != 3 or any(type(value) is not int for value in node):
                raise ValueError("invalid decision node")
            axis, left, right = node
            current = len(self.values) + len(self.nodes)
            if not 0 <= axis < problem.L or not 0 <= left < current or not 0 <= right < current or left == right:
                raise ValueError("unreduced, cyclic or out-of-range decision node")
            if self.axis(left) >= axis or self.axis(right) >= axis:
                raise ValueError("decision variables must strictly descend along a path")
            self.nodes.append(tuple(node))
        if self.nodes != sorted(set(self.nodes)):
            raise ValueError("nodes must be canonically sorted and unique")
        self.roots = function["roots"]
        if len(self.roots) != problem.G or any(
            type(root) is not int or not 0 <= root < self.size for root in self.roots
        ):
            raise ValueError("wrong number of roots or root outside diagram")
        visited, pending = set(), self.roots.copy()
        while pending:
            ref = pending.pop()
            if ref in visited:
                continue
            visited.add(ref)
            if ref >= len(self.values):
                pending.extend(self.nodes[ref - len(self.values)][1:])
        if len(visited) != self.size:
            raise ValueError("decision diagram contains unreachable data")

    @property
    def size(self) -> int:
        return len(self.values) + len(self.nodes)

    def axis(self, ref: int) -> int:
        return -1 if ref < len(self.values) else self.nodes[ref - len(self.values)][0]

    def at(self, vertex: int) -> tuple[Fraction, ...]:
        result = []
        for root in self.roots:
            ref = root
            while ref >= len(self.values):
                axis, left, right = self.nodes[ref - len(self.values)]
                ref = right if vertex >> axis & 1 else left
            result.append(self.values[ref])
        return tuple(result)

    def verify(self, problem: CountGeometry) -> dict:
        minima, maxima = self.values.copy(), self.values.copy()
        for _axis, left, right in self.nodes:
            minima.append(min(minima[left], minima[right]))
            maxima.append(max(maxima[left], maxima[right]))
        for root, capacity in zip(self.roots, problem.beta, strict=True):
            if minima[root] < 0 or maxima[root] > capacity:
                raise ValueError("decision root outside its RHS group bounds")
        for vertex, image in problem.boundary:
            if self.at(vertex) != image:
                raise ValueError("party/purifier occurrence boundary mismatch")
        # The following nodes are verification scratch, never saved as proof
        # data. Reduction/memoization may reuse nodes from the original DAG.
        unique = {node: len(self.values) + index for index, node in enumerate(self.nodes)}

        def intern(axis, left, right):
            if left == right:
                return left
            key = axis, left, right
            if key not in unique:
                unique[key] = len(self.values) + len(self.nodes)
                self.nodes.append(key)
            return unique[key]

        @lru_cache(None)
        def cofactor(ref, axis, bit):
            if self.axis(ref) < axis:
                return ref
            variable, left, right = self.nodes[ref - len(self.values)]
            if variable == axis:
                return right if bit else left
            return intern(variable, cofactor(left, axis, bit), cofactor(right, axis, bit))

        @lru_cache(None)
        def maximum(pairs):
            # Equal roots contribute zero without branching over their inputs.
            variable = max((max(self.axis(left), self.axis(right)) for left, right in pairs), default=-1)
            if variable == -1:
                return sum((abs(self.values[left] - self.values[right]) for left, right in pairs), Fraction(0))
            children = []
            for bit in (0, 1):
                reduced = []
                for left, right in pairs:
                    if self.axis(left) == variable:
                        left = self.nodes[left - len(self.values)][1 + bit]
                    if self.axis(right) == variable:
                        right = self.nodes[right - len(self.values)][1 + bit]
                    if left != right:
                        reduced.append((min(left, right), max(left, right)))
                children.append(maximum(tuple(sorted(reduced))))
            return max(children)

        loads = []
        for axis, capacity in enumerate(problem.alpha):
            pairs = []
            for root in self.roots:
                left, right = cofactor(root, axis, 0), cofactor(root, axis, 1)
                if left != right:
                    pairs.append((min(left, right), max(left, right)))
            load = maximum(tuple(sorted(pairs)))
            if load > capacity:
                raise ValueError(f"contraction edge violation on axis {axis}")
            loads.append(load)
        return {
            "scale": math.lcm(*(value.denominator for value in self.values)),
            "states": maximum.cache_info().currsize,
            "axis_loads": loads,
        }
