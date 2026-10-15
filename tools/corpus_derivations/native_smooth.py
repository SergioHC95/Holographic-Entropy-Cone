"""Opt-in exact native implementation of the SAME deterministic smoother.

This module is not imported by the live frozen cohort. It neither accepts a
proof nor changes the work/sweep budget. Complete returned seed bounds,
boundaries and coupled edges are checked again with Python arbitrary-precision
integers. Independent original-cube acceptance and a separate saved-map audit
are still mandatory for any retained alternative.
"""

from __future__ import annotations

import array
import hashlib
import struct
import subprocess
import sys
from pathlib import Path

from hec.count_proofs import parse_json

from .diagrams import validate_rows
from .native import exact
from .simplify import METHOD, WorkLimit

POLICY = "native-exact-same-smoothing/experimental-1"


def packed(values, code):
    result = array.array(code, values)
    if result.itemsize != (8 if code == "Q" else 4):
        raise ValueError("native exact smoother requires explicit 32/64-bit protocol integers")
    if sys.byteorder != "little":
        result.byteswap()
    return result.tobytes()


def supported(p, vertices, scale, rows, *, sweeps=2, max_work=50_000_000):
    """Exact resource capability, not mathematical validity or acceptance."""
    return (
        1 <= p.n <= 6
        and p.L <= 25
        and p.G <= 63
        and 1 <= len(vertices) <= 1_000_000
        and len(vertices) * p.G <= 16_000_000
        and type(scale) is int
        and 1 <= scale < 1 << 64
        and type(sweeps) is int
        and 1 <= sweeps <= 8
        and type(max_work) is int
        and 1 <= max_work < 1 << 64
        and all(0 < cap <= 1024 for cap in p.alpha + p.beta)
        and all(cap * scale < 1 << 64 for cap in p.beta)
    )


class NativeSmoother:
    def __init__(self, binary, expected_sha256):
        self.binary, self.sha256 = Path(binary), expected_sha256
        self.process, self.sequence = None, 0
        self.check_binary()

    def check_binary(self):
        if (
            self.binary.is_symlink()
            or not self.binary.is_file()
            or not isinstance(self.sha256, str)
            or len(self.sha256) != 64
            or hashlib.sha256(self.binary.read_bytes()).hexdigest() != self.sha256
        ):
            raise ValueError("explicitly bound native smoothing binary missing, unsafe or changed")

    def close(self):
        if self.process is not None:
            self.process.stdin.close()
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.terminate()  # This private helper only, never a corpus worker.
                self.process.wait(timeout=10)
            self.process.stdout.close()
            self.process = None

    def smooth(self, p, vertices, scale, rows, *, sweeps=2, max_work=50_000_000):
        if not supported(p, vertices, scale, rows, sweeps=sweeps, max_work=max_work):
            raise ValueError("smoothing exceeds exact native capability; use the arbitrary-precision reference")
        validate_rows(p, vertices, scale, rows)
        self.check_binary()
        index = {vertex: at for at, vertex in enumerate(vertices)}
        fixed = [index[vertex] for vertex, _ in p.boundary]
        images = [value * scale for _, image in p.boundary for value in image]
        if self.process is None:
            self.process = subprocess.Popen([str(self.binary)], stdin=subprocess.PIPE, stdout=subprocess.PIPE)
        self.sequence += 1
        header = struct.pack(
            "<8s6IQQI", b"HECSMO01", self.sequence, p.n, p.L, p.G, len(vertices), len(fixed), scale, max_work, sweeps
        )
        for block in (
            header,
            packed(p.alpha, "Q"),
            packed(p.beta, "Q"),
            packed(vertices, "I"),
            packed(fixed, "I"),
            packed(images, "Q"),
            packed((value for row in rows for value in row), "Q"),
        ):
            self.process.stdin.write(block)
        self.process.stdin.flush()
        meta_bytes, sequence, row_bytes = struct.unpack("<IIQ", exact(self.process.stdout, 16))
        expected_bytes = len(vertices) * p.G * 8
        if not 0 < meta_bytes <= 16384 or sequence != self.sequence or row_bytes not in (0, expected_bytes):
            raise ValueError("invalid bounded exact-smoothing reply lengths or request identity")
        report = parse_json(exact(self.process.stdout, meta_bytes))
        payload = exact(self.process.stdout, row_bytes)
        if report == {"ok": False, "status": "work_limit"} and row_bytes == 0:
            raise WorkLimit("exact synthesis work budget exhausted; alternative not accepted")
        if report.get("ok") is not True or row_bytes != expected_bytes:
            raise ValueError("native exact smoother did not return a complete candidate")
        report = {key: value for key, value in report.items() if key != "ok"}
        expected_keys = {
            "method",
            "status",
            "source_scale",
            "candidate_scale",
            "changed_cells",
            "component_moves",
            "component_visits",
            "compatible_edges",
            "sweeps",
            "work",
            "strict_description_improvement",
        }
        if (
            set(report) != expected_keys
            or report["method"] != METHOD
            or report["status"] != "complete_compatible_seed_pending_independent_full_cube_acceptance"
            or report["source_scale"] != str(scale)
            or report["strict_description_improvement"] != "not_yet_measured"
            or any(
                type(report[key]) is not int or report[key] < 0
                for key in (
                    "changed_cells",
                    "component_moves",
                    "component_visits",
                    "compatible_edges",
                    "sweeps",
                    "work",
                )
            )
            or not 1 <= report["sweeps"] <= sweeps
            or report["work"] > max_work
        ):
            raise ValueError("native exact-smoothing scope or statistics mismatch")
        new_scale = int(report["candidate_scale"])
        if report["candidate_scale"] != str(new_scale) or not 1 <= new_scale <= scale or scale % new_scale:
            raise ValueError("native exact smoother changed the denominator contract")
        flat = array.array("Q")
        flat.frombytes(payload)
        if sys.byteorder != "little":
            flat.byteswap()
        changed = [tuple(flat[at * p.G : (at + 1) * p.G]) for at in range(len(vertices))]
        validate_rows(p, vertices, new_scale, changed)
        for vertex, image in p.boundary:
            if changed[index[vertex]] != tuple(value * new_scale for value in image):
                raise ValueError("native exact smoothing changed an occurrence boundary")
        edges = 0
        for u, vertex in enumerate(vertices):
            for axis, cap in enumerate(p.alpha):
                v = index.get(vertex ^ (1 << axis))
                if v is not None and v > u:
                    if sum(abs(a - b) for a, b in zip(changed[u], changed[v], strict=True)) > cap * new_scale:
                        raise ValueError("Python arbitrary-precision postcheck rejected a coupled edge")
                    edges += 1
        changes = sum(
            a * new_scale != b * scale
            for before, after in zip(rows, changed, strict=True)
            for a, b in zip(before, after, strict=True)
        )
        if edges != report["compatible_edges"] or changes != report["changed_cells"]:
            raise ValueError("native smoothing statistics disagree with exact Python postchecks")
        return new_scale, changed, report
