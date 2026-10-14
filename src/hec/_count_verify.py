"""Independent, exact full-map acceptance for stored compact definitions.

The native service verifies every original cube vertex and edge from the
compact payload alone. It never reads migration receipts or original tables.
Unsupported large definitions fail closed rather than silently being sampled.
"""

from __future__ import annotations

import json
import os
import struct
import subprocess
from pathlib import Path

from .count_proofs import (
    DAG,
    FORMAT,
    INTEGER_ROWS,
    KERNEL,
    TRANSPORT,
    canonical_json,
    check_count_proof,
    decimal,
    make_count_proof,
    proof_geometry,
    row_bytes,
)


def _exact(stream, size: int) -> bytes:
    parts = []
    while size:
        chunk = stream.read(size)
        if not chunk:
            raise ValueError("native verifier response was truncated")
        parts.append(chunk)
        size -= len(chunk)
    return b"".join(parts)


def _fields(value: object, fields: set[str], label: str) -> dict:
    if not isinstance(value, dict) or set(value) != fields:
        raise ValueError(f"invalid {label} fields")
    return value


def native_supported(problem, encoding: str) -> bool:
    if encoding != INTEGER_ROWS or problem.n > 6 or problem.L > 17 or sum(problem.beta) > 63:
        return False
    if any(cap > 32 for cap in problem.alpha) or any(cap > 63 for cap in problem.beta):
        return False
    from ._count_transport import clearing_scale

    scale = clearing_scale(problem, 1)
    return scale <= 65535 and all(cap * scale <= 65535 for cap in problem.beta)


class FullMapVerifier:
    """One lazily started native process per bounded verification worker."""

    def __init__(self, binary: str | Path | None = None):
        value = binary if binary is not None else os.environ.get("HEC_COUNT_VERIFIER")
        self.binary = Path(value) if value else None
        self.process = None
        self.sequence = 0

    def close(self) -> None:
        if self.process is None:
            return
        if not self.process.stdin.closed:
            self.process.stdin.close()
        if self.process.poll() is None:
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.terminate()
                self.process.wait(timeout=10)
        self.process.stdout.close()
        self.process = None

    def verify(self, proof: dict) -> dict:
        canonical_json(proof)
        if proof.get("format") != FORMAT:
            raise ValueError("only authoritative exact proof definitions can be audited")
        problem = proof_geometry(proof)
        function = proof["function"]
        if not isinstance(function, dict):
            raise ValueError("function must be an object")
        if function.get("kind") == DAG:
            # Exact joint-cofactor maxima cover all edges. Small DAGs also
            # receive an independent exhaustive arbitrary-precision audit.
            return check_count_proof(proof, reference=problem.vertices <= 16384)
        if function.get("kind") not in (KERNEL, TRANSPORT):
            raise ValueError("unsupported authoritative full-map constructor")
        _fields(function, {"kind", "rows"}, "compact function")
        payload, data = row_bytes(function["rows"])
        if payload["count"] > problem.vertices:
            raise ValueError("seed row count exceeds the original cube")
        clearing = _fields(proof["clearing_scale"], {"value", "minimal"}, "clearing scale")
        scale = decimal(clearing["value"])
        if scale < 1 or clearing["minimal"] is not False:
            raise ValueError("compact constructor must declare its exact nonminimal clearing guarantee")
        if function["kind"] == TRANSPORT and native_supported(problem, payload["encoding"]):
            if self.binary is not None:
                return self._native(problem, payload, data, scale)
        if problem.vertices > 16384:
            raise ValueError(
                "exact full-cube verifier required; build tools/verify_count_proofs.cpp and set HEC_COUNT_VERIFIER"
            )
        # Arbitrary precision full-cube fallback for small unsupported cases.
        # Seed checks alone are never silently reported as this direct audit.
        check_count_proof(proof)
        from fractions import Fraction

        from .count_proofs import compatible_vertices, decode_rows

        if function["kind"] == TRANSPORT:
            from ._count_transport import SeedLookup, evaluate_transport

            seed = SeedLookup(problem, payload)
            rows = [evaluate_transport(problem, seed, vertex) for vertex in range(problem.vertices)]
        else:
            from ._count_kernel import evaluate_kernel

            seed = {
                vertex: tuple(Fraction(value, q) for value in row)
                for vertex, (q, row) in zip(compatible_vertices(problem), decode_rows(problem, payload), strict=True)
            }
            rows = [evaluate_kernel(problem, seed, vertex) for vertex in range(problem.vertices)]
        audit = make_count_proof(problem, rows, integral=False, audit_table=True)
        return check_count_proof(audit, reference=True)

    def _native(self, problem, payload: dict, data: bytes, scale: int) -> dict:
        if self.process is None:
            if self.binary.is_symlink() or not self.binary.is_file():
                raise ValueError("native exact verifier binary is missing or unsafe")
            self.process = subprocess.Popen([str(self.binary)], stdin=subprocess.PIPE, stdout=subprocess.PIPE)
        self.sequence += 1
        header = struct.pack(
            "<8sIIIQIQ",
            b"HECPRF01",
            self.sequence,
            problem.n,
            len(problem.coefficients),
            len(data),
            payload["count"],
            scale,
        )
        coefficients = struct.pack(f"<{len(problem.coefficients)}i", *problem.coefficients)
        self.process.stdin.write(header + coefficients + data)
        self.process.stdin.flush()
        length, seed_bytes, queries_bytes = struct.unpack("<III", _exact(self.process.stdout, 12))
        if length > 16384 or seed_bytes or queries_bytes:
            raise ValueError("unsafe native verifier response")
        result = json.loads(_exact(self.process.stdout, length))
        if result.get("ok") is not True:
            raise ValueError(f"native exact verification failed: {result.get('error', 'invalid response')}")
        if (
            result.get("index") != self.sequence
            or result.get("n") != problem.n
            or result.get("L") != problem.L
            or result.get("G") != problem.G
            or result.get("checked_vertices") != problem.vertices
            or result.get("checked_edges") != problem.L * (problem.vertices // 2)
            or result.get("seed_vertices") != payload["count"]
            or result.get("clearing_scale") != scale
            or result.get("scope") != "original-cube-all-edges"
        ):
            raise ValueError("native exact verifier returned incomplete or misbound coverage")
        return result
