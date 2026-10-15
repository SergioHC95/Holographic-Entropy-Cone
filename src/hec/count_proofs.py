"""Exact geometry, canonical identities and seed rows for the sole proof standard.

Mathematical acceptance belongs exclusively to ReconstructionVerifier.
No historical full-map definitions, alternate verifiers or format adapters.
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
INTEGER_ROWS = "bounded-integers/1"
RATIONAL_ROWS = "reduced-rationals/1"
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
        raise ValueError("inequality must be primitive; record input positive scaling in a transformation receipt")
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


def proof_geometry(proof: object) -> CountGeometry:
    proof = _keys(proof, {"format", "inequality", "function", "clearing_scale"}, "standard proof")
    if proof["format"] != FORMAT:
        raise ValueError("only hec-count-proof/1 is supported")
    if (
        not isinstance(proof["function"], dict)
        or proof["function"].get("kind") != "compatible-reconstruction-pipeline/1"
    ):
        raise ValueError("only the standardized reconstruction pipeline is supported")
    inequality = _keys(proof["inequality"], {"n", "coefficients"}, "inequality")
    if not isinstance(inequality["coefficients"], list):
        raise ValueError("coefficient vector must be a list")
    return geometry(inequality["n"], tuple(decimal(value) for value in inequality["coefficients"]))


def proof_id(proof: object) -> str:
    """Canonical definition identity; hashing is never mathematical acceptance."""
    if not isinstance(proof, dict) or proof.get("format") != FORMAT:
        raise ValueError("only hec-count-proof/1 has a primary proof identity")
    return hashlib.sha256(FORMAT.encode("ascii") + b"\0" + canonical_json(proof)).hexdigest()
