"""The standard reconstruction pipeline inside the exact count-proof envelope.

Seed programs are data, not executable code. They all feed the SAME certified
cancel/fill/common-threshold extension. The authoritative reader accepts only
this closed language. Syntax and stored flags are never mathematical acceptance.
"""

from __future__ import annotations

import bisect
import hashlib
import math
from dataclasses import dataclass
from fractions import Fraction

from ._count_transport import CompatibleRank, SeedLookup, clearing_scale, evaluate_transport
from ._reconstruction_cuts import cut_integer_rows
from .count_proofs import (
    FORMAT,
    RATIONAL_ROWS,
    canonical_json,
    compatible_vertices,
    decimal,
    geometry,
    inequality_id,
    parse_json,
    proof_id,
)

PIPELINE = "compatible-reconstruction-pipeline/1"
EXTENSION = "cancel-fill-common-threshold/1"
TABLE = "compatible-count-table/1"
DAG = "compatible-scalar-dag/1"
CUTS = "integer-cut-dnf/1"
CLOSURE = "integer-interval-closure/1"


@dataclass(frozen=True)
class Limits:
    """Implementation resource limits, NOT restrictions in the mathematical model."""

    max_n: int = 6
    max_l: int = 25
    max_groups: int = 63
    max_seed_vertices: int = 1_000_000
    max_seed_cells: int = 16_000_000
    max_nodes: int = 2_000_000
    max_document_bytes: int = 256 * 1024**2

    def __post_init__(self):
        if any(type(value) is not int or value < 1 for value in vars(self).values()):
            raise ValueError("resource limits must be positive exact integers")


DEFAULT_LIMITS = Limits()


def fields(value, names, label):
    if not isinstance(value, dict) or set(value) != set(names):
        raise ValueError(f"invalid {label} fields")
    return value


def problem_of(document, limits):
    fields(document, ("format", "inequality", "function", "clearing_scale"), "pipeline proof")
    if document["format"] != FORMAT:
        raise ValueError("only the exact count-proof envelope is accepted; use offline conversion")
    item = fields(document["inequality"], ("n", "coefficients"), "inequality")
    if type(item["n"]) is not int or not 1 <= item["n"] <= limits.max_n:
        raise ValueError("party count exceeds configured reconstruction capability")
    if not isinstance(item["coefficients"], list):
        raise ValueError("coefficient vector must be a list")
    p = geometry(item["n"], tuple(decimal(value) for value in item["coefficients"]))
    if p.L > limits.max_l or p.G > limits.max_groups:
        raise ValueError("geometry exceeds configured reconstruction capability")
    return p


class SeedProgram:
    """Closed seed algebra: exact lookup, scalar DAG, cuts, or interval closure.

    Syntax and complete-domain size are checked here. Contraction is NOT
    inferred from syntax. A trusted closure backend implements a named exact
    primitive; its path or executable code never comes from a proof document.
    """

    def __init__(self, p, definition, limits, closure_backend=None):
        if not 1 <= p.n <= limits.max_n or p.L > limits.max_l or p.G > limits.max_groups:
            raise ValueError("geometry exceeds configured reconstruction capability")
        self.problem, self.definition = p, definition
        self.domain = CompatibleRank(p)
        if self.domain.count > limits.max_seed_vertices or self.domain.count * p.G > limits.max_seed_cells:
            raise ValueError("complete seed exceeds configured reconstruction capability")
        if not isinstance(definition, dict):
            raise ValueError("seed program must be an object")
        kind = definition.get("kind")
        if kind == TABLE:
            fields(definition, ("kind", "rows"), "explicit seed")
            self.lookup = SeedLookup(p, definition["rows"])
            self.scale = math.lcm(*(q for q, _ in self.lookup.rows)) if self.lookup.rows is not None else 1
            if self.scale == 1 and definition["rows"]["encoding"] == RATIONAL_ROWS:
                raise ValueError("integral seeds require the canonical integer row encoding")
            self.at = self.lookup.__getitem__
        elif kind == DAG:
            self._dag(definition, limits)
        elif kind == CUTS:
            self._cuts(definition, limits)
        elif kind == CLOSURE:
            self._closure(definition, closure_backend)
        else:
            raise ValueError("unsupported seed primitive; there is no legacy fallback")

    def _dag(self, f, limits):
        fields(f, ("kind", "scale", "terminals", "nodes", "roots"), "scalar DAG seed")
        self.scale = decimal(f["scale"])
        if self.scale < 1 or any(not isinstance(f[key], list) for key in ("terminals", "nodes", "roots")):
            raise ValueError("invalid scalar DAG arrays or scale")
        terminals = tuple(map(decimal, f["terminals"]))
        nodes, roots, count = f["nodes"], f["roots"], len(terminals)
        if count + len(nodes) > limits.max_nodes or len(roots) != self.problem.G:
            raise ValueError("scalar DAG exceeds configured size or group count")
        if list(terminals) != sorted(set(terminals)) or any(value < 0 for value in terminals):
            raise ValueError("scalar DAG terminals must be sorted, unique and nonnegative")
        if math.gcd(self.scale, *terminals) != 1:
            raise ValueError("nonminimal scalar DAG denominator")
        for index, node in enumerate(nodes):
            if not isinstance(node, list) or len(node) != 3 or any(type(value) is not int for value in node):
                raise ValueError("invalid scalar DAG node")
            axis, low, high = node
            if not 0 <= axis < self.problem.L or not 0 <= low < count + index or not 0 <= high < count + index:
                raise ValueError("cyclic or out-of-range scalar DAG node")
            if low == high or any(child >= count and nodes[child - count][0] >= axis for child in (low, high)):
                raise ValueError("scalar DAG is not reduced or axis ordered")
        if nodes != sorted(nodes) or len({tuple(node) for node in nodes}) != len(nodes):
            raise ValueError("scalar DAG nodes must be canonical, sorted and shared")
        reached, pending = set(), list(roots)
        while pending:
            ref = pending.pop()
            if type(ref) is not int or not 0 <= ref < count + len(nodes):
                raise ValueError("invalid scalar DAG root/reference")
            if ref not in reached:
                reached.add(ref)
                if ref >= count:
                    pending.extend(nodes[ref - count][1:])
        if reached != set(range(count + len(nodes))):
            raise ValueError("unreachable scalar DAG objects")

        scale = self.scale

        def at(vertex):
            result = []
            for ref in roots:
                while ref >= count:
                    axis, low, high = nodes[ref - count]
                    ref = high if vertex >> axis & 1 else low
                result.append(Fraction(terminals[ref], scale))
            return tuple(result)

        self.at = at

        def numerators(vertex):
            result = []
            for ref in roots:
                while ref >= count:
                    axis, low, high = nodes[ref - count]
                    ref = high if vertex >> axis & 1 else low
                result.append(terminals[ref])
            return tuple(result)

        self.numerator_at = numerators

    def _cuts(self, f, limits):
        fields(f, ("kind", "terms", "groups"), "logical cut seed")
        if not isinstance(f["terms"], list) or not isinstance(f["groups"], list):
            raise ValueError("logical cuts require arrays")
        if len(f["terms"]) > limits.max_nodes or len(f["groups"]) != self.problem.G:
            raise ValueError("logical cut size or group count mismatch")
        terms = []
        for term in f["terms"]:
            if not isinstance(term, list) or len(term) != 2:
                raise ValueError("logical cut term requires two exact masks")
            one, zero = map(decimal, term)
            if not 0 <= one < self.problem.vertices or not 0 <= zero < self.problem.vertices or one & zero:
                raise ValueError("invalid or conflicting literal masks")
            terms.append((one, zero))
        if terms != sorted(set(terms)):
            raise ValueError("logical terms must be sorted, unique and shared")
        used, references = set(), 0
        for layers, cap in zip(f["groups"], self.problem.beta, strict=True):
            if not isinstance(layers, list) or len(layers) != cap:
                raise ValueError("cut layers differ from inequality capacity")
            for layer in layers:
                if not isinstance(layer, list) or any(
                    type(ref) is not int or not 0 <= ref < len(terms) for ref in layer
                ):
                    raise ValueError("invalid logical term reference")
                if layer != sorted(set(layer)):
                    raise ValueError("logical references must be sorted and unique")
                references += len(layer)
                used.update(layer)
        if used != set(range(len(terms))) or references > limits.max_nodes:
            raise ValueError("unreachable or oversized logical cut program")
        self.scale = 1
        self.cut_terms = tuple(terms)
        self.cut_groups = tuple(tuple(tuple(layer) for layer in group) for group in f["groups"])

        def at(vertex):
            truth = [vertex & one == one and not vertex & zero for one, zero in terms]
            return tuple(Fraction(sum(any(truth[ref] for ref in layer) for layer in group)) for group in f["groups"])

        self.at = at

    def _closure(self, f, backend):
        fields(f, ("kind", "anchors", "enumeration", "pairs", "policy", "choice_count", "exceptions"), "closure seed")
        for key, maximum in (
            ("anchors", 128),
            ("enumeration", 1024),
            ("choice_count", self.domain.count * self.problem.G),
        ):
            if type(f[key]) is not int or not 0 <= f[key] <= maximum:
                raise ValueError("invalid bounded exact closure setting")
        if (
            type(f["pairs"]) is not bool
            or f["policy"] not in ("lower", "upper")
            or not isinstance(f["exceptions"], list)
        ):
            raise ValueError("invalid closure policy")
        previous = -1
        for entry in f["exceptions"]:
            if not isinstance(entry, list) or len(entry) != 2:
                raise ValueError("invalid sparse closure choice")
            position, value = entry
            if type(position) is not int or not previous < position < f["choice_count"] or decimal(value) < 0:
                raise ValueError("noncanonical sparse closure choice")
            previous = position
        if backend is None or getattr(backend, "primitive", None) != CLOSURE:
            raise ValueError("exact interval-closure backend required; no source-table fallback")
        self.scale = 1
        problem, domain, cached = self.problem, self.domain, []

        def integer_rows():
            if not cached:
                rows = backend.decode(problem, f)
                if (
                    not isinstance(rows, (list, tuple))
                    or len(rows) != domain.count
                    or any(
                        not isinstance(row, (list, tuple))
                        or len(row) != problem.G
                        or any(type(value) is not int for value in row)
                        for row in rows
                    )
                ):
                    raise ValueError("closure backend returned an incomplete or non-integral seed")
                cached.append(tuple(tuple(row) for row in rows))
            return cached[0]

        def at(vertex):
            return tuple(Fraction(value) for value in integer_rows()[domain.rank(vertex)])

        self.at = at
        self.closure_integer_rows = integer_rows

    def numerator_rows(self, vertices):
        """Internal exact materialization algebra on the caller's complete C.

        Counts stay as arbitrary-precision integer numerators over self.scale;
        public rational queries remain separate. This is evaluation, not an
        acceptance shortcut: the caller retains every seed/full-cube check.
        """
        kind = self.definition["kind"]
        if kind == CUTS:
            rows = cut_integer_rows(vertices, self.problem.L, self.cut_terms, self.cut_groups)
            if not isinstance(rows, (tuple, list)) or len(rows) != len(vertices):
                raise ValueError("bulk cut evaluator returned an incomplete seed")
            return rows
        if kind == CLOSURE:
            return self.closure_integer_rows()
        if kind == DAG:
            return (self.numerator_at(vertex) for vertex in vertices)
        return self.table_numerator_rows()

    def table_numerator_rows(self):
        """Ordinal order is the ascending complete compatible-domain order."""
        lookup, scale = self.lookup, self.scale
        if lookup.rows is not None:
            for denominator, values in lookup.rows:
                if scale % denominator:
                    raise ValueError("seed denominator does not clear exact counts")
                factor = scale // denominator
                yield tuple(value * factor for value in values)
            return
        for ordinal in range(lookup.domain.count):
            cursor, values = ordinal * lookup.row_bits, []
            for width in lookup.widths:
                byte, shift = divmod(cursor, 8)
                value = int.from_bytes(lookup.data[byte : (cursor + width + 7) // 8], "little") >> shift
                values.append(value & ((1 << width) - 1))
                cursor += width
            yield tuple(values)


@dataclass(frozen=True)
class MaterializedSeed:
    vertices: tuple
    scale: int
    numerators: tuple
    checked_edges: int
    semantic_sha256: str

    def __getitem__(self, vertex):
        at = bisect.bisect_left(self.vertices, vertex)
        if at == len(self.vertices) or self.vertices[at] != vertex:
            raise ValueError("query outside complete compatible domain")
        return tuple(Fraction(value, self.scale) for value in self.numerators[at])


class ReconstructionProgram:
    """Self-contained exact pipeline; construction alone does not confer validity."""

    def __init__(self, document, *, limits=DEFAULT_LIMITS, closure_backend=None):
        raw = document if isinstance(document, bytes) else canonical_json(document)
        if len(raw) > limits.max_document_bytes:
            raise ValueError("pipeline document exceeds configured byte limit")
        document = parse_json(raw)  # Own an immutable byte snapshot, not the caller's mutable dict.
        self.raw = canonical_json(document)
        self.problem = p = problem_of(document, limits)
        function = fields(document["function"], ("kind", "seed", "extension"), "reconstruction pipeline")
        extension = fields(function["extension"], ("kind",), "full-cube extension")
        if function["kind"] != PIPELINE or extension["kind"] != EXTENSION:
            raise ValueError("unsupported pipeline or fixed extension version")
        self._seed = SeedProgram(p, function["seed"], limits, closure_backend)
        clearing = fields(document["clearing_scale"], ("value", "minimal"), "clearing scale")
        self.clearing_scale = clearing_scale(p, self._seed.scale)
        if clearing["minimal"] is not False or decimal(clearing["value"]) != self.clearing_scale:
            raise ValueError("incorrect derived pipeline clearing guarantee")
        self._materialized = None

    @property
    def document(self):
        return parse_json(self.raw)

    @property
    def identity(self):
        return proof_id(self.document)

    @property
    def stages(self):
        return ("derive-complete-support-domain/1", self._seed.definition["kind"], EXTENSION)

    def __getitem__(self, vertex):
        self._seed.domain.rank(vertex)  # Reject incompatible queries, not arbitrary missing rows.
        values = self._seed.at(vertex)
        if any(value < 0 or value > cap for value, cap in zip(values, self.problem.beta, strict=True)):
            raise ValueError("seed value outside exact count bounds")
        return values

    def evaluate(self, vertex):
        if type(vertex) is not int or not 0 <= vertex < self.problem.vertices:
            raise ValueError("query outside original source cube")
        return evaluate_transport(self.problem, self, vertex)

    def materialize_seed(self):
        if self._materialized is not None:
            return self._materialized
        p, scale = self.problem, self._seed.scale
        vertices = tuple(compatible_vertices(p))
        rows, divisor = [], scale
        semantic = hashlib.sha256(b"hec-compatible-seed-semantics/1\0")
        semantic.update(canonical_json(p.inequality()) + b"\n" + str(scale).encode() + b"\n")
        for vertex, row in zip(vertices, self._seed.numerator_rows(vertices), strict=True):
            if (
                not isinstance(row, (tuple, list))
                or len(row) != p.G
                or any(
                    type(value) is not int or not 0 <= value <= cap * scale
                    for value, cap in zip(row, p.beta, strict=True)
                )
            ):
                raise ValueError("seed value outside exact count shape or bounds")
            for value in row:
                divisor = math.gcd(divisor, value)
            rows.append(row)
            semantic.update(str(vertex).encode() + b":" + b",".join(str(value).encode() for value in row) + b"\n")
        if len(vertices) != self._seed.domain.count or divisor != 1:
            raise ValueError("incomplete seed domain or nonminimal seed denominator")
        index = {vertex: at for at, vertex in enumerate(vertices)}
        for vertex, image in p.boundary:
            if rows[index[vertex]] != tuple(value * scale for value in image):
                raise ValueError("seed occurrence boundary violation")
        edges = 0
        for u, vertex in enumerate(vertices):
            for axis, cap in enumerate(p.alpha):
                v = index.get(vertex ^ (1 << axis))
                if v is not None and v > u:
                    if sum(abs(a - b) for a, b in zip(rows[u], rows[v], strict=True)) > cap * scale:
                        raise ValueError("seed coupled contraction edge violation")
                    edges += 1
        self._materialized = MaterializedSeed(vertices, scale, tuple(rows), edges, semantic.hexdigest())
        return self._materialized

    def semantic_identity(self):
        """Encoding-independent identity for this fixed extension, NOT a validity flag."""
        seed = self.materialize_seed()
        return hashlib.sha256(
            b"hec-pipeline-map-semantics/1\0" + EXTENSION.encode() + b"\0" + bytes.fromhex(seed.semantic_sha256)
        ).hexdigest()

    def audit(self, backend):
        """Execute a trusted independent full-cube backend, never accept a stored receipt."""
        if getattr(backend, "extension", None) != EXTENSION:
            raise ValueError("independent backend for this exact extension required")
        p, seed = self.problem, self.materialize_seed()
        result = backend.verify(p, seed.vertices, seed.scale, seed.numerators)
        expected = {
            "n": p.n,
            "L": p.L,
            "G": p.G,
            "seed_vertices": len(seed.vertices),
            "seed_scale": str(seed.scale),
            "clearing_scale": str(self.clearing_scale),
            "scope": "original-cube-all-edges",
            "checked_vertices": p.vertices,
            "checked_edges": p.L * (p.vertices // 2),
        }
        if (
            not isinstance(result, dict)
            or result.get("ok") is not True
            or any(type(result.get(key)) is not type(value) or result[key] != value for key, value in expected.items())
        ):
            raise ValueError("independent backend returned incomplete or mismatched full-cube coverage")
        return {
            **result,
            "proof_id": self.identity,
            "inequality_id": inequality_id(p),
            "semantic_map_id": self.semantic_identity(),
            "source_tables_read": False,
        }

    def audit_reference(self, *, max_vertices=16384):
        """Direct exact full-cube audit of the actual evaluator, never sampling."""
        p = self.problem
        if type(max_vertices) is not int or max_vertices < 1 or p.vertices > max_vertices:
            raise ValueError("exact full-cube backend required; reference audit resource bound exceeded")
        seed = self.materialize_seed()
        rows = [self.evaluate(vertex) for vertex in range(p.vertices)]
        for row in rows:
            if any(not 0 <= value <= cap for value, cap in zip(row, p.beta, strict=True)):
                raise ValueError("full-cube output bounds violation")
        for vertex, image in p.boundary:
            if rows[vertex] != image:
                raise ValueError("full-cube occurrence boundary violation")
        edges = 0
        for vertex, row in enumerate(rows):
            for axis, cap in enumerate(p.alpha):
                neighbor = vertex ^ (1 << axis)
                if neighbor > vertex:
                    if sum(abs(a - b) for a, b in zip(row, rows[neighbor], strict=True)) > cap:
                        raise ValueError("full-cube coupled contraction edge violation")
                    edges += 1
        return {
            "ok": True,
            "proof_id": self.identity,
            "inequality_id": inequality_id(p),
            "semantic_map_id": self.semantic_identity(),
            "scope": "original-cube-all-edges",
            "checked_vertices": p.vertices,
            "checked_edges": edges,
            "compatible_vertices": len(seed.vertices),
            "compatible_edges": seed.checked_edges,
            "clearing_scale": str(self.clearing_scale),
            "implementation": "exact-fraction-reference/1",
            "source_tables_read": False,
        }


def compile_pipeline(problem, seed, *, limits=DEFAULT_LIMITS, closure_backend=None):
    """Build once, retaining the checked seed for subsequent equivalence/audit calls."""
    raw = canonical_json(seed)
    if len(raw) > limits.max_document_bytes:
        raise ValueError("pipeline seed exceeds configured byte limit")
    seed = parse_json(raw)
    program = SeedProgram(problem, seed, limits, closure_backend)
    document = {
        "format": FORMAT,
        "inequality": problem.inequality(),
        "function": {"kind": PIPELINE, "seed": seed, "extension": {"kind": EXTENSION}},
        "clearing_scale": {"value": str(clearing_scale(problem, program.scale)), "minimal": False},
    }
    result = ReconstructionProgram(document, limits=limits, closure_backend=closure_backend)
    result.materialize_seed()
    return result


def make_pipeline(problem, seed, *, limits=DEFAULT_LIMITS, closure_backend=None):
    """Build the single envelope and check its complete seed, not a full-cube claim."""
    return compile_pipeline(problem, seed, limits=limits, closure_backend=closure_backend).document
