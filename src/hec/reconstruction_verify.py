"""Installed-package exact verification for the standard proof protocol.

No research-tool imports, proof-selected executables, acceptance receipts, or
original tables. Backend paths are trusted caller/CI configuration; their
bytes are pinned for the lifetime of each adapter. Every mathematical request
executes complete original-cube checks; stored receipts do not confer validity.
"""

from __future__ import annotations

import array
import hashlib
import os
import struct
import subprocess
import sys
from pathlib import Path

from ._count_transport import clearing_scale
from .count_proofs import canonical_json, compatible_vertices, decimal, parse_json
from .reconstruction import CLOSURE, EXTENSION, ReconstructionProgram


class ExactCapabilityError(ValueError):
    """An implementation limit, never mathematical rejection or acceptance."""


def digest(path):
    result = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024**2), b""):
            result.update(block)
    return result.hexdigest()


def exact(stream, size):
    result = []
    while size:
        block = stream.read(size)
        if not block:
            raise ValueError("truncated independent exact reconstruction backend response")
        result.append(block)
        size -= len(block)
    return b"".join(result)


class BoundBinary:
    """Trusted configuration only, never a field inside a proof definition."""

    def __init__(self, path, expected_sha256=None):
        self.path = Path(path)
        if self.path.is_symlink() or not self.path.is_file():
            raise ValueError("independent exact backend is missing or unsafe")
        actual = digest(self.path)
        if expected_sha256 is not None and actual != expected_sha256:
            raise ValueError("independent exact backend SHA256 mismatch")
        self.sha256 = actual

    def check(self):
        if self.path.is_symlink() or not self.path.is_file() or digest(self.path) != self.sha256:
            raise ValueError("independent exact backend changed after binding")


class IntervalClosureDecoder:
    """Decode the named exact interval primitive; this does NOT accept a proof."""

    primitive = CLOSURE

    def __init__(self, binary, expected_sha256=None):
        self.binding = BoundBinary(binary, expected_sha256)

    def decode(self, p, seed):
        self.binding.check()
        if p.n > 6 or p.L > 17 or sum(p.beta) > 63 or max(p.alpha, default=0) > 32:
            raise ValueError("interval-closure definition exceeds configured exact native capability")
        count = len(list(compatible_vertices(p)))
        # The public program reader has already checked the closed seed schema.
        # Repeat protocol-specific checks here; direct adapter calls fail closed.
        fields = {"kind", "anchors", "enumeration", "pairs", "policy", "choice_count", "exceptions"}
        if (
            not isinstance(seed, dict)
            or set(seed) != fields
            or seed["kind"] != CLOSURE
            or type(seed["anchors"]) is not int
            or not 0 <= seed["anchors"] <= 128
            or type(seed["enumeration"]) is not int
            or not 0 <= seed["enumeration"] <= 1024
            or type(seed["pairs"]) is not bool
            or seed["policy"] not in ("lower", "upper")
            or type(seed["choice_count"]) is not int
            or not 0 <= seed["choice_count"] <= count * p.G
            or not isinstance(seed["exceptions"], list)
        ):
            raise ValueError("invalid exact interval-closure definition")
        request = bytearray(struct.pack("<8sIII", b"HECDRV01", p.n, len(p.coefficients), count))
        request.extend(struct.pack(f"<{len(p.coefficients)}i", *p.coefficients))
        request.extend(
            struct.pack("<III", seed["choice_count"], 1 if seed["policy"] == "lower" else 2, len(seed["exceptions"]))
        )
        previous = -1
        for entry in seed["exceptions"]:
            if not isinstance(entry, list) or len(entry) != 2:
                raise ValueError("invalid exact closure exception")
            position, value = entry[0], decimal(entry[1])
            if type(position) is not int or not previous < position < seed["choice_count"] or not 0 <= value <= 65535:
                raise ValueError("invalid exact closure exception position/offset")
            request.extend(struct.pack("<IH", position, value))
            previous = position
        command = [
            str(self.binding.path),
            "--mode",
            "decode",
            "--anchors",
            str(seed["anchors"]),
            "--enumeration",
            str(seed["enumeration"]),
        ]
        if not seed["pairs"]:
            command.append("--no-pairs")
        response = subprocess.run(command, input=bytes(request), capture_output=True, check=True).stdout
        if len(response) < 16:
            raise ValueError("truncated exact closure decoder reply")
        meta_bytes, tape_bytes, width_bytes, row_bytes = struct.unpack("<IIII", response[:16])
        if not 0 < meta_bytes <= 8192 or len(response) != 16 + meta_bytes + tape_bytes + width_bytes + row_bytes:
            raise ValueError("unsafe exact closure decoder reply lengths")
        meta = parse_json(response[16 : 16 + meta_bytes])
        expected = {"ok": True, "vertices": count, "groups": p.G, "choices": seed["choice_count"]}
        if any(type(meta.get(key)) is not type(value) or meta[key] != value for key, value in expected.items()):
            raise ValueError("misbound exact closure decoder reply")
        if tape_bytes != 2 * seed["choice_count"] or width_bytes != tape_bytes or row_bytes != 2 * count * p.G:
            raise ValueError("incomplete exact closure decoder reply")
        at = 16 + meta_bytes + tape_bytes + width_bytes
        values = struct.unpack(f"<{count * p.G}H", response[at:])
        return [tuple(values[i * p.G : (i + 1) * p.G]) for i in range(count)]


class IndependentCubeAuditor:
    """Execute all original-cube bounds, occurrence images and weighted edges."""

    extension = EXTENSION

    def __init__(self, binary, expected_sha256=None, *, working_bytes=None):
        self.binding = BoundBinary(binary, expected_sha256)
        if working_bytes is not None and (type(working_bytes) is not int or not 1 <= working_bytes <= 30 * 1024**3):
            raise ValueError("trusted primary output-buffer budget must be an exact positive bounded integer")
        self.working_bytes = working_bytes
        self.process, self.sequence = None, 0

    def close(self):
        if self.process is not None:
            if not self.process.stdin.closed:
                self.process.stdin.close()
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.terminate()  # Private completed-request helper, not a solver timeout.
                self.process.wait(timeout=10)
            self.process.stdout.close()
            self.process = None

    def verify(self, p, vertices, scale, rows):
        self.binding.check()
        if (
            not 1 <= p.n <= 6
            or p.L > 25
            or p.G > 63
            or any(abs(value) > 1024 for value in p.coefficients)
            or type(scale) is not int
            or scale < 1
        ):
            raise ExactCapabilityError("proof exceeds exact native cube-audit capability")
        clearing = clearing_scale(p, scale)
        if clearing >= 1 << 64 or any(cap * clearing >= 1 << 64 for cap in p.beta):
            raise ExactCapabilityError("proof needs a wider exact cube-audit backend; no truncation or sampling")
        if len(rows) != len(vertices) or any(len(row) != p.G for row in rows):
            raise ValueError("incomplete exact seed for independent cube audit")
        values = array.array("Q")
        if values.itemsize != 8:
            raise ValueError("exact cube protocol requires explicit uint64 transport")
        for row in rows:
            for value in row:
                if type(value) is not int or not 0 <= value < 1 << 64:
                    raise ValueError("seed is not representable exactly by this native audit backend")
                values.append(value)
        if sys.byteorder != "little":
            values.byteswap()
        data = values.tobytes()
        if len(data) > 1024**3:
            raise ValueError("seed exceeds bounded exact cube-audit request")
        if self.process is None:
            command = [str(self.binding.path)]
            if self.working_bytes is not None:
                command.extend(("--working-bytes", str(self.working_bytes)))
            self.process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE)
        self.sequence += 1
        self.process.stdin.write(
            struct.pack(
                "<8sIIIIQIQQI",
                b"HECCRP01",
                self.sequence,
                p.n,
                0,
                len(p.coefficients),
                len(data),
                len(vertices),
                scale,
                clearing,
                0,
            )
        )
        self.process.stdin.write(struct.pack(f"<{len(p.coefficients)}i", *p.coefficients))
        self.process.stdin.write(data)
        self.process.stdin.flush()
        meta_bytes, seed_bytes, query_bytes = struct.unpack("<IQI", exact(self.process.stdout, 16))
        if not 0 < meta_bytes <= 16384 or seed_bytes or query_bytes:
            raise ValueError("unsafe exact cube-auditor reply lengths")
        result = parse_json(exact(self.process.stdout, meta_bytes))
        expected = {
            "ok": True,
            "index": self.sequence,
            "n": p.n,
            "L": p.L,
            "G": p.G,
            "R": sum(p.beta),
            "seed_vertices": len(vertices),
            "seed_scale": str(scale),
            "clearing_scale": str(clearing),
            "checked_vertices": p.vertices,
            "checked_edges": p.L * (p.vertices // 2),
            "scope": "original-cube-all-edges",
            "arithmetic": "uint64-values-uint128-sums",
        }
        if any(type(result.get(key)) is not type(value) or result[key] != value for key, value in expected.items()):
            raise ValueError("independent exact backend returned incomplete or misbound cube coverage")
        if self.working_bytes is not None and (
            type(result.get("output_row_storage_limit")) is not int
            or result["output_row_storage_limit"] != self.working_bytes
            or type(result.get("output_row_storage_bytes")) is not int
            or not 0 <= result["output_row_storage_bytes"] <= self.working_bytes
        ):
            raise ValueError("independent exact backend did not honor its bound output-buffer budget")
        return {**result, "binary_sha256": self.binding.sha256}


class ReconstructionVerifier:
    """One exact verification entry point for all four standard seed primitives."""

    def __init__(self, *, closure_binary=None, cube_binary=None, cube_working_bytes=None):
        closure = closure_binary if closure_binary is not None else os.environ.get("HEC_RECONSTRUCTION_CLOSURE")
        cube = cube_binary if cube_binary is not None else os.environ.get("HEC_RECONSTRUCTION_VERIFIER")
        if cube_working_bytes is None and "HEC_RECONSTRUCTION_WORKING_BYTES" in os.environ:
            raw = os.environ["HEC_RECONSTRUCTION_WORKING_BYTES"]
            if not raw.isascii() or not raw.isdecimal() or str(int(raw)) != raw:
                raise ValueError("trusted working-byte configuration must be a canonical exact integer")
            cube_working_bytes = int(raw)
        self.closure = IntervalClosureDecoder(closure) if closure else None
        if cube_working_bytes is not None and not cube:
            raise ValueError("an explicit exact backend is required with a bound working budget")
        self.auditor = IndependentCubeAuditor(cube, working_bytes=cube_working_bytes) if cube else None

    def close(self):
        if self.auditor is not None:
            self.auditor.close()

    def verify(self, document):
        canonical_json(document)
        program = ReconstructionProgram(document, closure_backend=self.closure)
        if self.auditor is not None:
            try:
                return program.audit(self.auditor)
            except ExactCapabilityError:
                # Only exact capability limits permit the full rational fallback;
                # malformed/incomplete/native-failure responses always propagate.
                pass
        result = program.audit_reference()
        return {**result, "scope": "original-cube-all-edges"}
