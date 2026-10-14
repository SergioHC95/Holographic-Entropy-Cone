"""Exact, self-contained full-cube count certificates.

This reader accepts only the new certificate format. Historical Boolean maps
belong in the offline migration tool, not in this verifier's acceptance path.
Geometry is deliberately rebuilt without the solver's float/NumPy parser.
"""

from __future__ import annotations

import base64
import hashlib
import json
import math
import re
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from fractions import Fraction
from itertools import combinations
from typing import Any

FORMAT = "hec-count-proof/1"
AUDIT_FORMAT = "hec-count-audit/1"
INTEGER_ROWS = "bounded-integers/1"
RATIONAL_ROWS = "reduced-rationals/1"
TABLE = "full-table/1"
KERNEL = "compatible-order-kernel/1"
TRANSPORT = "compatible-cancel-fill-kernel/1"
DAG = "count-decision-dag/1"
_DECIMAL = re.compile(r"(?:0|-?[1-9][0-9]*)\Z")


def decimal(value: object) -> int:
    """Read an arbitrary-precision integer, never a JSON number or float."""
    if not isinstance(value, str) or _DECIMAL.fullmatch(value) is None:
        raise ValueError("mathematical integers must be canonical decimal strings")
    return int(value)


def _keys(value: object, expected: set[str], label: str) -> dict:
    if not isinstance(value, dict) or set(value) != expected:
        raise ValueError(f"{label} must have exactly the fields {sorted(expected)}")
    return value


def canonical_json(value: object) -> bytes:
    """Our restricted canonical JSON; this is not a claim of RFC 8785 JCS."""

    def inspect(item: object) -> None:
        if isinstance(item, dict):
            if any(not isinstance(key, str) for key in item):
                raise ValueError("JSON object keys must be strings")
            for child in item.values():
                inspect(child)
        elif isinstance(item, list | tuple):
            for child in item:
                inspect(child)
        elif type(item) is int:
            if not 0 <= item <= (1 << 53) - 1:
                raise ValueError("JSON numbers are reserved for nonnegative safe indices")
        elif item is not None and not isinstance(item, str | bool):
            raise ValueError("floating-point and non-JSON values are forbidden")

    inspect(value)
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("ascii")


def parse_json(data: bytes) -> Any:
    def pairs(items: list[tuple[str, Any]]) -> dict:
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    def forbidden(value: str) -> Any:
        raise ValueError(f"non-exact JSON number: {value}")

    result = json.loads(data, object_pairs_hook=pairs, parse_float=forbidden, parse_constant=forbidden)
    canonical_json(result)
    return result


@dataclass(frozen=True)
class CountGeometry:
    n: int
    coefficients: tuple[int, ...]
    lhs: tuple[int, ...]
    alpha: tuple[int, ...]
    rhs: tuple[int, ...]
    beta: tuple[int, ...]
    boundary: tuple[tuple[int, tuple[int, ...]], ...]

    @property
    def L(self) -> int:
        return len(self.lhs)

    @property
    def G(self) -> int:
        return len(self.rhs)

    @property
    def vertices(self) -> int:
        return 1 << self.L

    @property
    def disjoint(self) -> tuple[tuple[int, int], ...]:
        return tuple((i, j) for i, a in enumerate(self.lhs) for j, b in enumerate(self.lhs) if i < j and not a & b)

    @property
    def nested(self) -> tuple[tuple[int, int], ...]:
        return tuple((i, j) for i, a in enumerate(self.lhs) for j, b in enumerate(self.lhs) if a != b and a & b == a)

    def inequality(self) -> dict:
        return {"n": self.n, "coefficients": [str(value) for value in self.coefficients]}


def geometry(n: int, coefficients: Sequence[int]) -> CountGeometry:
    """Primitive positive-scale normal in the declared repository party frame."""
    if type(n) is not int or n < 1 or len(coefficients) != (1 << n) - 1:
        raise ValueError("inequality dimension must be 2**n - 1 with n >= 1")
    if any(type(value) is not int for value in coefficients):
        raise ValueError("inequality coefficients must be exact Python integers")
    coefficients = tuple(coefficients)
    if math.gcd(*coefficients) not in (0, 1):
        raise ValueError("inequality must be primitive; record input positive scaling in the migration receipt")
    supports = [sum(1 << i for i in subset) for size in range(1, n + 1) for subset in combinations(range(n), size)]
    lhs, alpha, rhs, beta = [], [], [], []
    for support, coefficient in zip(supports, coefficients, strict=True):
        if coefficient > 0:
            lhs.append(support)
            alpha.append(coefficient)
        elif coefficient < 0:
            rhs.append(support)
            beta.append(-coefficient)
    boundary = {}
    # Atom n is the purifier: all stored supports exclude it, giving x=y=0.
    for atom in range(n + 1):
        vertex = sum(int(bool(support & (1 << atom))) << i for i, support in enumerate(lhs))
        image = tuple(capacity if support & (1 << atom) else 0 for support, capacity in zip(rhs, beta, strict=True))
        if vertex in boundary and boundary[vertex] != image:
            raise ValueError("conflicting occurrence boundary images")
        boundary[vertex] = image
    return CountGeometry(
        n,
        coefficients,
        tuple(lhs),
        tuple(alpha),
        tuple(rhs),
        tuple(beta),
        tuple(sorted(boundary.items())),
    )


def inequality_id(problem: CountGeometry) -> str:
    return hashlib.sha256(b"hec-inequality/1\0" + canonical_json(problem.inequality())).hexdigest()


def compatible_vertices(problem: CountGeometry) -> Iterator[int]:
    """Enumerate the complete compatible domain in ascending vertex order.

    Propagation checks *both* disjointness and nesting, independently of any
    supplied seed list. No purported domain-coverage receipt is trusted.
    """
    successors, predecessors, conflicts = [0] * problem.L, [0] * problem.L, [0] * problem.L
    for i, j in problem.nested:
        successors[i] |= 1 << j
        predecessors[j] |= 1 << i
    for i, j in problem.disjoint:
        conflicts[i] |= 1 << j
        conflicts[j] |= 1 << i
    full = problem.vertices - 1

    def visit(ones: int, zeros: int) -> Iterator[int]:
        while True:
            before = ones, zeros
            for i in range(problem.L):
                if ones >> i & 1:
                    ones |= successors[i]
                    zeros |= conflicts[i]
                if zeros >> i & 1:
                    zeros |= predecessors[i]
            if ones & zeros:
                return
            if before == (ones, zeros):
                break
        unknown = full & ~(ones | zeros)
        if not unknown:
            yield ones
            return
        bit = 1 << (unknown.bit_length() - 1)
        yield from visit(ones, zeros | bit)
        yield from visit(ones | bit, zeros)

    yield from visit(0, 0)


def _put_unsigned(value: int, output: bytearray) -> None:
    if type(value) is not int or value < 0:
        raise ValueError("unsigned integer expected")
    while value >= 128:
        output.append((value & 127) | 128)
        value >>= 7
    output.append(value)


def _unsigned(data: bytes, position: int) -> tuple[int, int]:
    start = position
    result = 0
    while position < len(data):
        byte = data[position]
        result |= (byte & 127) << (7 * (position - start))
        position += 1
        if byte < 128:
            if position > start + 1 and not byte:
                raise ValueError("nonminimal unsigned varint")
            return result, position
    raise ValueError("truncated unsigned varint")


def _normalized_row(values: Sequence[int | Fraction], groups: int) -> tuple[int, tuple[int, ...]]:
    if len(values) != groups or any(type(value) not in (int, Fraction) for value in values):
        raise ValueError("count rows require exactly G rational/integer values, never floats")
    if all(type(value) is int for value in values):
        if any(value < 0 for value in values):
            raise ValueError("counts must be nonnegative")
        return 1, tuple(values)
    fractions = tuple(Fraction(value) for value in values)
    denominator = math.lcm(*(value.denominator for value in fractions))
    numerators = tuple(value.numerator * (denominator // value.denominator) for value in fractions)
    if any(value < 0 for value in numerators):
        raise ValueError("counts must be nonnegative")
    return denominator, numerators


def encode_rows(
    problem: CountGeometry,
    rows: Iterable[Sequence[int | Fraction]],
    *,
    integral: bool,
) -> tuple[dict, int]:
    """Canonical bounded-bit integer rows or reduced rational unsigned varints."""
    output = bytearray()
    scale, count, accumulator, pending = 1, 0, 0, 0
    widths = [capacity.bit_length() for capacity in problem.beta]
    for row in rows:
        denominator, numerators = _normalized_row(row, problem.G)
        if any(value > capacity * denominator for value, capacity in zip(numerators, problem.beta, strict=True)):
            raise ValueError("count outside its RHS group bounds")
        count += 1
        scale = math.lcm(scale, denominator)
        if integral:
            if denominator != 1:
                raise ValueError("integer row encoding cannot hold fractional counts")
            for value, width in zip(numerators, widths, strict=True):
                accumulator |= value << pending
                pending += width
                while pending >= 8:
                    output.append(accumulator & 255)
                    accumulator >>= 8
                    pending -= 8
        else:
            _put_unsigned(denominator, output)
            for value in numerators:
                _put_unsigned(value, output)
    if pending:
        output.append(accumulator)
    return {
        "encoding": INTEGER_ROWS if integral else RATIONAL_ROWS,
        "count": count,
        "data": base64.b64encode(output).decode("ascii"),
    }, scale


def row_bytes(payload: object) -> tuple[dict, bytes]:
    payload = _keys(payload, {"encoding", "count", "data"}, "row payload")
    count = payload["count"]
    if type(count) is not int or count < 0 or not isinstance(payload["data"], str):
        raise ValueError("invalid row count/data")
    data = base64.b64decode(payload["data"], validate=True)
    if base64.b64encode(data).decode("ascii") != payload["data"]:
        raise ValueError("noncanonical base64")
    return payload, data


def decode_rows(problem: CountGeometry, payload: object) -> Iterator[tuple[int, tuple[int, ...]]]:
    payload, data = row_bytes(payload)
    count = payload["count"]
    if payload["encoding"] == INTEGER_ROWS:
        widths = [capacity.bit_length() for capacity in problem.beta]
        bits = count * sum(widths)
        if len(data) != (bits + 7) // 8 or (bits % 8 and data[-1] >> (bits % 8)):
            raise ValueError("integer row byte length/padding mismatch")
        cursor = 0
        for _ in range(count):
            values = []
            for width in widths:
                byte, shift = divmod(cursor, 8)
                value = int.from_bytes(data[byte : (cursor + width + 7) // 8], "little") >> shift
                values.append(value & ((1 << width) - 1))
                cursor += width
            yield 1, tuple(values)
    elif payload["encoding"] == RATIONAL_ROWS:
        position = 0
        for _ in range(count):
            denominator, position = _unsigned(data, position)
            values = []
            for _ in range(problem.G):
                value, position = _unsigned(data, position)
                values.append(value)
            if denominator < 1 or math.gcd(denominator, *values) != 1:
                raise ValueError("rational row is not jointly reduced")
            yield denominator, tuple(values)
        if position != len(data):
            raise ValueError("trailing rational row data")
    else:
        raise ValueError("unknown count row encoding")


def kernel_scale(problem: CountGeometry, seed_scale: int) -> int:
    """A proved clearing bound, explicitly not claimed to be minimal."""
    isotonic = math.lcm(*range(1, sum(problem.alpha) + 1))
    folds = math.prod(
        max(problem.alpha[i], problem.alpha[j]) // math.gcd(problem.alpha[i], problem.alpha[j])
        for i, j in problem.disjoint
    )
    return seed_scale * isotonic * folds


def make_count_proof(
    problem: CountGeometry,
    rows: Iterable[Sequence[int | Fraction]],
    *,
    kernel: bool = False,
    transport: bool = False,
    integral: bool = True,
    audit_table: bool = False,
) -> dict:
    if kernel and transport:
        raise ValueError("choose exactly one certified compact construction")
    compact = kernel or transport
    if compact and audit_table:
        raise ValueError("an enumerated audit cannot be a compact kernel definition")
    payload, scale = encode_rows(problem, rows, integral=integral)
    if scale == 1 and not integral:
        # Exactly one canonical payload encoding for integral functions/seeds.
        values = (numerators for _q, numerators in decode_rows(problem, payload))
        payload, scale = encode_rows(problem, values, integral=True)
    function = {"kind": TRANSPORT if transport else KERNEL if kernel else TABLE, "rows": payload}
    if not compact and not audit_table:
        from ._count_dag import build

        function, scale = build(problem, list(decode_rows(problem, payload)))
    if transport:
        from ._count_transport import clearing_scale

        scale = clearing_scale(problem, scale)
    elif kernel:
        scale = kernel_scale(problem, scale)
    proof = {
        "format": AUDIT_FORMAT if audit_table else FORMAT,
        "inequality": problem.inequality(),
        "function": function,
        "clearing_scale": {"value": str(scale), "minimal": not compact},
    }
    check_count_proof(proof)  # Construction cannot create an unchecked certificate.
    return proof


def proof_geometry(proof: object) -> CountGeometry:
    proof = _keys(proof, {"format", "inequality", "function", "clearing_scale"}, "count proof")
    if proof["format"] not in (FORMAT, AUDIT_FORMAT):
        raise ValueError("unsupported proof format; run the offline migration tool")
    inequality = _keys(proof["inequality"], {"n", "coefficients"}, "inequality")
    if not isinstance(inequality["coefficients"], list):
        raise ValueError("coefficient vector must be a list")
    return geometry(inequality["n"], tuple(decimal(value) for value in inequality["coefficients"]))


def check_count_proof(proof: object, *, reference: bool = False) -> dict:
    """Independent exact acceptance; historical receipts never confer validity.

    Literal maps check every original-source edge. Kernel maps check complete
    seed coverage, every compatible edge, and the fixed certified construction.
    See docs/contraction-proof-standard.md for the construction's proof.
    """
    canonical_json(proof)
    problem = proof_geometry(proof)
    if not isinstance(proof["function"], dict):
        raise ValueError("function definition must be an object")
    if (proof["function"].get("kind") == TABLE) != (proof["format"] == AUDIT_FORMAT):
        raise ValueError("enumerated tables are optional audits, not authoritative proof definitions")
    if isinstance(proof["function"], dict) and proof["function"].get("kind") == DAG:
        from ._count_dag import Diagram

        diagram = Diagram(problem, proof["function"])
        outcome = diagram.verify(problem)
        if reference:
            rows = [diagram.at(vertex) for vertex in range(problem.vertices)]
            audit = make_count_proof(problem, rows, integral=False, audit_table=True)
            check_count_proof(audit, reference=True)
        _check_scale(proof, outcome["scale"], minimal=True)
        receipt = _receipt(
            proof, problem, problem.vertices, problem.L * (problem.vertices // 2), outcome["scale"], kernel=False
        )
        receipt["scope"] = "symbolic-original-cube-all-edges"
        return receipt
    function = _keys(proof["function"], {"kind", "rows"}, "function")
    kind = function["kind"]
    if kind not in (TABLE, KERNEL, TRANSPORT):
        raise ValueError("unsupported full-map definition")
    _keys(function["rows"], {"encoding", "count", "data"}, "row payload")
    if kind == TABLE and not reference and function["rows"].get("encoding") == INTEGER_ROWS:
        from ._integer_count_table import supported, verify_integer_table

        if supported(problem):
            payload, data = row_bytes(function["rows"])
            if payload["count"] != problem.vertices:
                raise ValueError("map does not cover its entire declared domain")
            edges = verify_integer_table(problem, data)
            _check_scale(proof, 1, minimal=True)
            return _receipt(proof, problem, problem.vertices, edges, 1, kernel=False)
    rows = list(decode_rows(problem, function["rows"]))
    compact = kind in (KERNEL, TRANSPORT)
    vertices = list(compatible_vertices(problem)) if compact else range(problem.vertices)
    if len(rows) != len(vertices):
        raise ValueError("map/seed does not cover its entire declared domain")
    locations = dict(zip(vertices, range(len(rows)), strict=True)) if compact else None
    scale = 1
    for denominator, numerators in rows:
        if any(value > capacity * denominator for value, capacity in zip(numerators, problem.beta, strict=True)):
            raise ValueError("count outside its RHS group bounds")
        scale = math.lcm(scale, denominator)
    if scale == 1 and function["rows"]["encoding"] != INTEGER_ROWS:
        raise ValueError("integral rows must use the canonical bounded integer encoding")
    for vertex, image in problem.boundary:
        location = locations.get(vertex) if locations is not None else vertex
        if location is None:
            raise ValueError("boundary occurrence missing from seed")
        denominator, values = rows[location]
        if values != tuple(value * denominator for value in image):
            raise ValueError("party/purifier occurrence boundary mismatch")
    edges = 0
    for location, vertex in enumerate(vertices):
        q, left = rows[location]
        for axis, capacity in enumerate(problem.alpha):
            if vertex >> axis & 1:
                continue
            neighbor = vertex | (1 << axis)
            target = locations.get(neighbor) if locations is not None else neighbor
            if target is None:
                continue
            r, right = rows[target]
            distance = sum(abs(a * r - b * q) for a, b in zip(left, right, strict=True))
            if distance > capacity * q * r:
                raise ValueError(f"contraction edge violation at vertex {vertex}, axis {axis}")
            edges += 1
    if kind == TRANSPORT:
        from ._count_transport import clearing_scale

        expected_scale = clearing_scale(problem, scale)
    else:
        expected_scale = kernel_scale(problem, scale) if kind == KERNEL else scale
    _check_scale(proof, expected_scale, minimal=kind == TABLE)
    if kind == TABLE and edges != problem.L * (problem.vertices // 2):
        raise ValueError("original-cube edge coverage mismatch")
    result = _receipt(proof, problem, len(rows), edges, expected_scale, kernel=compact)
    if kind == TRANSPORT:
        result["constructor"] = TRANSPORT
    return result


def _check_scale(proof: dict, expected: int, *, minimal: bool) -> None:
    clearing = _keys(proof["clearing_scale"], {"value", "minimal"}, "clearing scale")
    if decimal(clearing["value"]) != expected or type(clearing["minimal"]) is not bool:
        raise ValueError("incorrect rational clearing scale")
    if clearing["minimal"] != minimal:
        raise ValueError("incorrect minimal-scale claim")


def _receipt(proof: dict, problem: CountGeometry, vertices: int, edges: int, scale: int, *, kernel: bool) -> dict:
    return {
        "ok": True,
        "inequality_id": inequality_id(problem),
        "proof_id": proof_id(proof),
        "source_vertices": problem.vertices,
        "checked_vertices": vertices,
        "checked_edges": edges,
        "scope": "complete-compatible-seed-and-certified-extension" if kernel else "original-cube-all-edges",
        "clearing_scale": str(scale),
        "minimal_scale": not kernel,
    }


def proof_id(proof: object) -> str:
    """Identity of the uncompressed definition, independent of zstd/sharding."""
    prefix = proof.get("format", FORMAT) if isinstance(proof, dict) else FORMAT
    return hashlib.sha256(prefix.encode("ascii") + b"\0" + canonical_json(proof)).hexdigest()


def evaluate_count_proof(proof: dict, vertex: int, *, verify: bool = True) -> tuple[Fraction, ...]:
    if verify:
        check_count_proof(proof)
    problem = proof_geometry(proof)
    if type(vertex) is not int or not 0 <= vertex < problem.vertices:
        raise ValueError("source vertex outside the original cube")
    if proof["function"]["kind"] == DAG:
        from ._count_dag import Diagram

        return Diagram(problem, proof["function"]).at(vertex)
    if proof["function"]["kind"] == TRANSPORT:
        from ._count_transport import SeedLookup, evaluate_transport

        return evaluate_transport(problem, SeedLookup(problem, proof["function"]["rows"]), vertex)
    rows = list(decode_rows(problem, proof["function"]["rows"]))
    if proof["function"]["kind"] == TABLE:
        denominator, values = rows[vertex]
        return tuple(Fraction(value, denominator) for value in values)
    if proof["function"]["kind"] != KERNEL:
        raise ValueError("unsupported full-map definition")
    from ._count_kernel import evaluate_kernel

    seed = {
        x: tuple(Fraction(value, q) for value in values)
        for x, (q, values) in zip(compatible_vertices(problem), rows, strict=True)
    }
    return evaluate_kernel(problem, seed, vertex)
