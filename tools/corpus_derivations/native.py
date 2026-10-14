"""Bounded exact wide-auditor protocol and arbitrary-precision differentials."""

from __future__ import annotations

import array
import bisect
import json
import math
import random
import struct
import subprocess
import sys
from fractions import Fraction
from pathlib import Path

from hec._count_transport import clearing_scale, evaluate_transport


def exact(stream, size):
    blocks = []
    while size:
        part = stream.read(size)
        if not part:
            raise ValueError("truncated independent wide-auditor reply")
        blocks.append(part)
        size -= len(part)
    return b"".join(blocks)


class Lookup:
    def __init__(self, vertices, scale, rows):
        self.vertices, self.scale, self.rows = vertices, scale, rows

    def __getitem__(self, vertex):
        at = bisect.bisect_left(self.vertices, vertex)
        if at >= len(self.vertices) or self.vertices[at] != vertex:
            raise ValueError("threshold endpoint outside independently regenerated C")
        return tuple(Fraction(v, self.scale) for v in self.rows[at])


class Auditor:
    def __init__(self, binary):
        self.binary, self.process, self.sequence = Path(binary), None, 0

    def close(self):
        if self.process is not None:
            self.process.stdin.close()
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.terminate()
                self.process.wait(timeout=10)
            self.process.stdout.close()
            self.process = None

    def call(self, p, vertices, scale, *, rows=None, packed=None, queries=()):
        if self.binary.is_symlink() or not self.binary.is_file():
            raise ValueError("independent verifier binary is missing/unsafe")
        if not 1 <= p.n <= 6 or p.L > 25 or p.G > 63 or any(abs(v) > 1024 for v in p.coefficients):
            raise ValueError("geometry exceeds wide native capability")
        if type(scale) is not int or scale < 1:
            raise ValueError("seed scale must be an exact positive integer")
        full_scale = clearing_scale(p, scale)
        if full_scale >= 1 << 64 or any(b * full_scale >= 1 << 64 for b in p.beta):
            raise ValueError("output value needs a wider native backend; no overflow truncation")
        mode = int(packed is not None)
        if mode:
            if rows is not None or scale != 1 or queries:
                raise ValueError("invalid original-map mode")
            if sum(p.beta) > 120:
                raise ValueError("original Boolean row too wide for this native checker")
            data = packed
        else:
            if rows is None or len(rows) != len(vertices) or any(len(row) != p.G for row in rows):
                raise ValueError("reconstructed seed shape mismatch")
            flat = array.array("Q")
            for row in rows:
                for value in row:
                    if type(value) is not int or not 0 <= value < 1 << 64:
                        raise ValueError("scaled seed is not an exact uint64")
                    flat.append(value)
            if sys.byteorder != "little":
                flat.byteswap()
            data = flat.tobytes()
        if len(data) > 1024**3 or len(queries) > 64:
            raise ValueError("request exceeds bounded exact-auditor protocol")
        if any(type(x) is not int or not 0 <= x < p.vertices for x in queries):
            raise ValueError("query outside source cube")
        if self.process is None:
            self.process = subprocess.Popen([str(self.binary)], stdin=subprocess.PIPE, stdout=subprocess.PIPE)
        self.sequence += 1
        header = struct.pack(
            "<8sIIIIQIQQI",
            b"HECCRP01",
            self.sequence,
            p.n,
            mode,
            len(p.coefficients),
            len(data),
            len(vertices),
            scale,
            full_scale,
            len(queries),
        )
        self.process.stdin.write(
            header
            + struct.pack(f"<{len(p.coefficients)}i", *p.coefficients)
            + struct.pack(f"<{len(queries)}I", *queries)
        )
        self.process.stdin.write(data)
        self.process.stdin.flush()
        meta_bytes, seed_bytes, query_bytes = struct.unpack("<IQI", exact(self.process.stdout, 16))
        if meta_bytes > 16384 or seed_bytes > 1024**3 or query_bytes > 64 * 63 * 8:
            raise ValueError("unsafe auditor response lengths")
        result = json.loads(exact(self.process.stdout, meta_bytes))
        seed = exact(self.process.stdout, seed_bytes)
        response = exact(self.process.stdout, query_bytes)
        if result.get("ok") is not True:
            raise ValueError("wide independent full-cube audit failed: " + str(result.get("error")))
        expected = {
            "index": self.sequence,
            "n": p.n,
            "L": p.L,
            "G": p.G,
            "R": sum(p.beta),
            "seed_vertices": len(vertices),
            "checked_vertices": p.vertices,
            "checked_edges": p.L * (p.vertices // 2),
            "seed_scale": str(scale),
            "clearing_scale": str(full_scale),
            "scope": "original-Boolean-cube-all-edges" if mode else "original-cube-all-edges",
        }
        if any(result.get(key) != value for key, value in expected.items()):
            raise ValueError("incomplete or misbound wide exact acceptance")
        if seed_bytes != (8 * len(vertices) * p.G if mode else 0) or query_bytes != len(queries) * p.G * 8:
            raise ValueError("misbound wide auditor rows/queries")
        values = struct.unpack(f"<{seed_bytes // 8}Q", seed)
        extracted = [tuple(values[i * p.G : (i + 1) * p.G]) for i in range(len(vertices))] if mode else None
        qvalues = struct.unpack(f"<{query_bytes // 8}Q", response)
        return result, extracted, qvalues

    def verify(self, p, vertices, scale, rows):
        # These are implementation differentials, NOT the mathematical coverage.
        # Acceptance above separately checks all original-cube vertices and edges.
        rng = random.Random(20261014 + sum(p.lhs))
        queries = sorted(
            {0, p.vertices - 1, *(x for x, _ in p.boundary), *(rng.randrange(p.vertices) for _ in range(8))}
        )
        result, _, values = self.call(p, vertices, scale, rows=rows, queries=queries)
        seed = Lookup(vertices, scale, rows)
        t = int(result["clearing_scale"])
        for i, x in enumerate(queries):
            actual = tuple(Fraction(v, t) for v in values[i * p.G : (i + 1) * p.G])
            if evaluate_transport(p, seed, x) != actual:
                raise ValueError("native/arbitrary-precision constructor differential failed")
        result["arbitrary_precision_query_differentials"] = len(queries)
        divisor = scale
        for row in rows:
            for value in row:
                divisor = math.gcd(divisor, value)
        result["seed_scale_minimal"] = divisor == 1
        return result
