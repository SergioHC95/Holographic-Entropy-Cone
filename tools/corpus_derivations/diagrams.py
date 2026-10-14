"""Exact compatible-domain scalar DAGs followed by the fixed transport rule.

Missing branches are don't-cares only outside C. Acceptance derives C afresh,
checks every reconstructed compatible value, then audits the full original cube.
Common-denominator terminals represent rational counts, never rounded values.
"""

from __future__ import annotations

import bisect
import hashlib
import math
from fractions import Fraction

from hec.count_proofs import (
    KERNEL,
    TRANSPORT,
    canonical_json,
    compatible_vertices,
    decimal,
    decode_rows,
    geometry,
    kernel_scale,
    proof_geometry,
)

FORMAT = "hec-compatible-derivation/experimental-2"
DAG = "compatible-scalar-dag/experimental-1"
SEED = "compatible-explicit-seed/experimental-1"


def document(problem, function):
    return {"format": FORMAT, "inequality": problem.inequality(), "function": function}


def identity(recipe):
    return hashlib.sha256(FORMAT.encode() + b"\0" + canonical_json(recipe)).hexdigest()


def recipe_geometry(recipe):
    canonical_json(recipe)
    if not isinstance(recipe, dict) or set(recipe) != {"format", "inequality", "function"}:
        raise ValueError("invalid wide recipe fields")
    if recipe["format"] != FORMAT:
        raise ValueError("unsupported wide recipe format")
    item = recipe["inequality"]
    if not isinstance(item, dict) or set(item) != {"n", "coefficients"}:
        raise ValueError("invalid inequality fields")
    if type(item["n"]) is not int or not 1 <= item["n"] <= 6 or not isinstance(item["coefficients"], list):
        raise ValueError("wide research recipes support only n=1 through n=6")
    p = geometry(item["n"], tuple(map(decimal, item["coefficients"])))
    if p.L > 25 or p.G > 63 or any(cap > 1024 for cap in p.alpha + p.beta):
        raise ValueError("geometry exceeds bounded wide auditor capability")
    return p


def common_seed(proof):
    parties = proof.get("inequality", {}).get("n")
    if type(parties) is not int or not 1 <= parties <= 6:
        raise ValueError("source geometry outside bounded corpus capability")
    p = proof_geometry(proof)
    if p.L > 25 or p.G > 63 or any(cap > 1024 for cap in p.alpha + p.beta):
        raise ValueError("source geometry outside bounded corpus capability")
    if "rows" not in proof["function"]:
        from derivation_pilot.recipes import integer_seed

        p, vertices, rows = integer_seed(proof)
        return p, vertices, 1, rows
    decoded = list(decode_rows(p, proof["function"]["rows"]))
    vertices = list(compatible_vertices(p))
    if len(decoded) != len(vertices):
        raise ValueError("source seed coverage mismatch")
    scale = math.lcm(*(q for q, _ in decoded))
    rows = [tuple(v * (scale // q) for v in values) for q, values in decoded]
    validate_rows(p, vertices, scale, rows)
    function, clearing = proof["function"], proof["clearing_scale"]
    if set(function) != {"kind", "rows"} or function["kind"] not in (KERNEL, TRANSPORT):
        raise ValueError("unsupported exact compatible source constructor")
    if not isinstance(clearing, dict) or set(clearing) != {"value", "minimal"} or clearing["minimal"] is not False:
        raise ValueError("invalid compatible source clearing metadata")
    from hec._count_transport import clearing_scale

    expected = kernel_scale(p, scale) if function["kind"] == KERNEL else clearing_scale(p, scale)
    if decimal(clearing["value"]) != expected:
        raise ValueError("source clearing scale differs from exact construction")
    return p, vertices, scale, rows


def validate_rows(p, vertices, scale, rows):
    if type(scale) is not int or scale < 1 or vertices != list(compatible_vertices(p)):
        raise ValueError("non-exact scale or incomplete compatible coverage")
    if len(rows) != len(vertices):
        raise ValueError("seed shape mismatch")
    divisor = scale
    for row in rows:
        if len(row) != p.G:
            raise ValueError("seed group mismatch")
        for value, cap in zip(row, p.beta, strict=True):
            if type(value) is not int or not 0 <= value <= cap * scale:
                raise ValueError("seed value outside exact bounds")
            divisor = math.gcd(divisor, value)
    if divisor != 1:
        raise ValueError("seed common denominator is not minimal")


def build(p, vertices, scale, rows):
    validate_rows(p, vertices, scale, rows)
    terminals = sorted({value for row in rows for value in row})
    refs = {value: i for i, value in enumerate(terminals)}
    nodes, shared, roots = [], {}, []
    for group in range(p.G):
        values = [row[group] for row in rows]
        changes = [i for i in range(len(values) - 1) if values[i] != values[i + 1]]

        def visit(axis, start, stop, changes=changes, values=values):
            if bisect.bisect_left(changes, start) == bisect.bisect_left(changes, stop - 1):
                return refs[values[start]]
            if axis < 0:
                raise ValueError("distinct values at one compatible vertex")
            prefix = vertices[start] & ~((1 << (axis + 1)) - 1)
            mid = bisect.bisect_left(vertices, prefix | (1 << axis), start, stop)
            if mid == start or mid == stop:
                return visit(axis - 1, start, stop)
            low, high = visit(axis - 1, start, mid), visit(axis - 1, mid, stop)
            if low == high:
                return low
            key = axis, low, high
            if key not in shared:
                shared[key] = len(terminals) + len(nodes)
                nodes.append(list(key))
            return shared[key]

        roots.append(visit(p.L - 1, 0, len(vertices)))
    return document(
        p,
        {"kind": DAG, "seed_scale": str(scale), "terminals": list(map(str, terminals)), "nodes": nodes, "roots": roots},
    )


class Diagram:
    def __init__(self, recipe):
        self.problem = recipe_geometry(recipe)
        f = recipe["function"]
        if (
            not isinstance(f, dict)
            or set(f) != {"kind", "seed_scale", "terminals", "nodes", "roots"}
            or f["kind"] != DAG
        ):
            raise ValueError("invalid compatible DAG fields")
        self.scale = decimal(f["seed_scale"])
        if self.scale < 1 or any(not isinstance(f[key], list) for key in ("terminals", "nodes", "roots")):
            raise ValueError("invalid DAG scale or arrays")
        self.terminals = list(map(decimal, f["terminals"]))
        self.nodes, self.roots = f["nodes"], f["roots"]
        if self.terminals != sorted(set(self.terminals)) or any(v < 0 for v in self.terminals):
            raise ValueError("noncanonical DAG terminals")
        if math.gcd(self.scale, *self.terminals) != 1 or len(self.roots) != self.problem.G:
            raise ValueError("nonminimal scale or root shape mismatch")
        count, seen = len(self.terminals), set()
        for index, node in enumerate(self.nodes):
            if not isinstance(node, list) or len(node) != 3 or any(type(v) is not int for v in node):
                raise ValueError("invalid DAG node")
            axis, low, high = node
            if (
                not 0 <= axis < self.problem.L
                or not 0 <= low < count + index
                or not 0 <= high < count + index
                or low == high
            ):
                raise ValueError("non-reduced, cyclic or out-of-range DAG node")
            if tuple(node) in seen:
                raise ValueError("duplicate DAG node")
            seen.add(tuple(node))
            for child in (low, high):
                if child >= count and self.nodes[child - count][0] >= axis:
                    raise ValueError("DAG variables not in decreasing source order")
        reachable, pending = set(), list(self.roots)
        while pending:
            ref = pending.pop()
            if type(ref) is not int or not 0 <= ref < count + len(self.nodes):
                raise ValueError("invalid DAG root/reference")
            if ref in reachable:
                continue
            reachable.add(ref)
            if ref >= count:
                pending.extend(self.nodes[ref - count][1:])
        if reachable != set(range(count + len(self.nodes))):
            raise ValueError("unreachable DAG terminals/nodes")

    def numerators(self, vertex):
        if type(vertex) is not int or not 0 <= vertex < self.problem.vertices:
            raise ValueError("DAG query outside source cube")
        values, count = [], len(self.terminals)
        for ref in self.roots:
            while ref >= count:
                axis, low, high = self.nodes[ref - count]
                ref = high if vertex & (1 << axis) else low
            values.append(self.terminals[ref])
        return tuple(values)

    def __getitem__(self, vertex):
        return tuple(Fraction(v, self.scale) for v in self.numerators(vertex))


def reconstruct(recipe):
    diagram = Diagram(recipe)
    p = diagram.problem
    vertices = list(compatible_vertices(p))
    rows = [diagram.numerators(x) for x in vertices]
    validate_rows(p, vertices, diagram.scale, rows)
    return p, vertices, diagram.scale, rows
