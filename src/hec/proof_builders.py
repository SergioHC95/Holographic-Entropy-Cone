"""Standard-only proof authoring from exact complete compatible seeds.

Builders validate the complete seed but do not confer full-map acceptance.
The catalogue writer independently audits every resulting original-cube map.
No historical artifact reader or solver-output serialization is used.
"""

from __future__ import annotations

import bisect
import struct
import subprocess
from itertools import accumulate

from .count_proofs import canonical_json, compatible_vertices, decode_rows, encode_rows, parse_json
from .reconstruction import CLOSURE, DAG, TABLE, make_pipeline
from .reconstruction_verify import BoundBinary, IntervalClosureDecoder


def table_seed(problem, rows):
    """Canonical exact rows; integral values always use the integer encoding."""
    payload, scale = encode_rows(problem, rows, integral=False)
    if scale == 1:
        payload, _ = encode_rows(problem, (values for _, values in decode_rows(problem, payload)), integral=True)
    return {"kind": TABLE, "rows": payload}


def dag_seed(problem, rows):
    """Canonical reduced scalar DAG over the independently derived domain."""
    payload, scale = encode_rows(problem, rows, integral=False)
    vertices = tuple(compatible_vertices(problem))
    decoded = list(decode_rows(problem, payload))
    if len(decoded) != len(vertices):
        raise ValueError("rows must cover the complete compatible domain exactly")
    values = [tuple(value * (scale // q) for value in row) for q, row in decoded]
    terminals = sorted({value for row in values for value in row})
    refs = {value: i for i, value in enumerate(terminals)}
    nodes, shared, roots = [], {}, []
    for group in range(problem.G):
        column = [row[group] for row in values]
        changes = [i for i in range(len(column) - 1) if column[i] != column[i + 1]]

        def visit(axis, start, stop, column=column, changes=changes):
            if bisect.bisect_left(changes, start) == bisect.bisect_left(changes, stop - 1):
                return refs[column[start]]
            if axis < 0:
                raise ValueError("distinct values at one compatible vertex")
            prefix = vertices[start] & ~((1 << (axis + 1)) - 1)
            mid = bisect.bisect_left(vertices, prefix | (1 << axis), start, stop)
            if mid in (start, stop):
                return visit(axis - 1, start, stop)
            low, high = visit(axis - 1, start, mid), visit(axis - 1, mid, stop)
            if low == high:
                return low
            key = axis, low, high
            if key not in shared:
                shared[key] = len(terminals) + len(nodes)
                nodes.append(key)
            return shared[key]

        roots.append(visit(problem.L - 1, 0, len(vertices)))
    remap, canonical = {i: i for i in range(len(terminals))}, []
    for axis in sorted({node[0] for node in nodes}):
        level = sorted(
            (axis, remap[low], remap[high], len(terminals) + i) for i, (at, low, high) in enumerate(nodes) if at == axis
        )
        for at, low, high, old in level:
            remap[old] = len(terminals) + len(canonical)
            canonical.append([at, low, high])
    return {
        "kind": DAG,
        "scale": str(scale),
        "terminals": list(map(str, terminals)),
        "nodes": canonical,
        "roots": [remap[ref] for ref in roots],
    }


def proof_from_seed_rows(problem, rows):
    """Choose the shorter of exact table and shared-DAG seed definitions."""
    rows = tuple(tuple(row) for row in rows)
    seeds = (table_seed(problem, rows), dag_seed(problem, rows))
    return make_pipeline(problem, min(seeds, key=lambda seed: (len(canonical_json(seed)), canonical_json(seed))))


def closure_seed(problem, rows, binary, *, anchors=32, enumeration=64, pairs=True):
    """Encode an integral seed as named closure rules, then independently decode.

    The binary is trusted caller configuration, never proof-supplied code.
    Exact seed equality is required; full-cube verification remains separate.
    """
    if type(anchors) is not int or not 0 <= anchors <= 128 or type(pairs) is not bool:
        raise ValueError("invalid closure settings")
    if type(enumeration) is not int or not 0 <= enumeration <= 1024:
        raise ValueError("invalid closure enumeration bound")
    if problem.n > 6 or problem.L > 17 or sum(problem.beta) > 63 or max(problem.alpha, default=0) > 32:
        raise ValueError("closure encoder exceeds exact native capability")
    rows = tuple(tuple(row) for row in rows)
    # This validates exact types, coverage, bounds, boundaries and every seed edge.
    make_pipeline(problem, table_seed(problem, rows))
    if any(type(value) is not int or not 0 <= value <= 65535 for row in rows for value in row):
        raise ValueError("closure encoder requires bounded exact integers")
    binding = BoundBinary(binary)
    binding.check()
    request = struct.pack("<8sIII", b"HECDRV01", problem.n, len(problem.coefficients), len(rows))
    request += struct.pack(f"<{len(problem.coefficients)}i", *problem.coefficients)
    request += struct.pack(f"<{len(rows) * problem.G}H", *(value for row in rows for value in row))
    command = [str(binding.path), "--mode", "encode", "--anchors", str(anchors), "--enumeration", str(enumeration)]
    if not pairs:
        command.append("--no-pairs")
    response = subprocess.run(command, input=request, capture_output=True, check=True).stdout
    binding.check()
    if len(response) < 16:
        raise ValueError("truncated closure encoder response")
    meta_bytes, tape_bytes, width_bytes, row_bytes = struct.unpack("<IIII", response[:16])
    if not 0 < meta_bytes <= 8192 or len(response) != 16 + meta_bytes + tape_bytes + width_bytes + row_bytes:
        raise ValueError("invalid closure encoder response lengths")
    meta = parse_json(response[16 : 16 + meta_bytes])
    count = meta.get("choices")
    expected = {"ok": True, "vertices": len(rows), "groups": problem.G}
    if (
        any(type(meta.get(key)) is not type(value) or meta[key] != value for key, value in expected.items())
        or type(count) is not int
        or not 0 <= count <= len(rows) * problem.G
        or tape_bytes != 2 * count
        or width_bytes != tape_bytes
        or row_bytes != 2 * len(rows) * problem.G
    ):
        raise ValueError("misbound closure encoder response")
    at = 16 + meta_bytes
    tape = struct.unpack(f"<{count}H", response[at : at + tape_bytes])
    at += tape_bytes
    widths = struct.unpack(f"<{count}H", response[at : at + width_bytes])
    lower = [[i, str(value)] for i, value in enumerate(tape) if value]
    upper = [[i, str(value)] for i, value in enumerate(tape) if value != widths[i]]
    policy, exceptions = min((("lower", lower), ("upper", upper)), key=lambda item: (len(item[1]), item[0]))
    seed = {
        "kind": CLOSURE,
        "anchors": anchors,
        "enumeration": enumeration,
        "pairs": pairs,
        "policy": policy,
        "choice_count": count,
        "exceptions": exceptions,
    }
    decoder = IntervalClosureDecoder(binding.path, binding.sha256)
    if tuple(map(tuple, decoder.decode(problem, seed))) != rows:
        raise ValueError("encoded closure rules changed exact seed values")
    return seed


def proof_from_boolean_table(problem, table):
    """Author a standard proof from the solver's ephemeral Boolean array.

    This is not a stored-format adapter. The array must cover the exact source
    cube and expanded RHS positions; grouping is proof-preserving. The fixed
    extension may change images outside the compatible domain.
    """
    import numpy as np

    table = np.asarray(table)
    if table.shape != (problem.vertices, sum(problem.beta)) or table.dtype.kind not in "bui":
        raise ValueError("solver must return a complete exact Boolean array")
    if np.any((table != 0) & (table != 1)):
        raise ValueError("solver array contains non-Boolean values")
    offsets = [0, *accumulate(problem.beta)]
    rows = (
        tuple(int(table[vertex, offsets[g] : offsets[g + 1]].sum()) for g in range(problem.G))
        for vertex in compatible_vertices(problem)
    )
    return proof_from_seed_rows(problem, rows)
