"""Offline, proof-preserving import. Never an input path of the new reader.

Original artifacts are read-only. A new catalogue is published only after all
selected originals pass fresh exhaustive source-cube audits and every new
definition passes the independent exact verifier. No numerical seed fitting.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import struct
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from fractions import Fraction
from pathlib import Path

import numpy as np
import zstandard as zstd

from hec.coordinates import party_labels
from hec.count_proofs import (
    CountGeometry,
    canonical_json,
    check_count_proof,
    compatible_vertices,
    geometry,
    inequality_id,
    make_count_proof,
    proof_geometry,
    proof_id,
)
from hec.inequality_records import InequalityCatalog, write_inequality_catalog
from hec.proof_store import ProofCatalog, write_proof_catalog

_POPCOUNT = np.array([value.bit_count() for value in range(256)], dtype=np.uint8)


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024**2), b""):
            digest.update(block)
    return digest.hexdigest()


def packed_rows(raw: np.ndarray, vertices: np.ndarray, width: int) -> np.ndarray:
    if not width:
        return np.empty((len(vertices), 0), dtype=np.uint8)
    if width % 8 == 0:
        return raw.reshape(-1, width // 8)[vertices]
    starts = np.asarray(vertices, dtype=np.int64)[:, None] * width
    offsets = (starts >> 3) + np.arange((width + 7) // 8, dtype=np.int64)
    shifts = starts & 7
    values = (raw[offsets].astype(np.uint16) >> shifts) | (
        raw[np.minimum(offsets + 1, len(raw) - 1)].astype(np.uint16) << (8 - shifts)
    )
    result = (values & 255).astype(np.uint8)
    result[:, -1] &= (1 << (width % 8)) - 1
    return result


def count_rows(raw: np.ndarray, problem: CountGeometry, vertices: np.ndarray, scale: int = 1):
    width = scale * sum(problem.beta)
    # Batch memory depends on output width, not on total cube size.
    batch = max(1, min(8192, (8 * 1024**2) // max(width, 1)))
    boundaries = np.cumsum([0, *(scale * value for value in problem.beta)])
    for first in range(0, len(vertices), batch):
        selected = packed_rows(raw, vertices[first : first + batch], width)
        bits = np.unpackbits(selected, axis=1, bitorder="little", count=width)
        counts = [
            bits[:, start:stop].sum(axis=1, dtype=np.int64)
            for start, stop in zip(boundaries[:-1], boundaries[1:], strict=True)
        ]
        for index in range(len(selected)):
            if scale == 1:
                yield tuple(int(column[index]) for column in counts)
            else:
                yield tuple(Fraction(int(column[index]), scale) for column in counts)


def audit_boolean(raw: np.ndarray, problem: CountGeometry, scale: int = 1) -> dict:
    """Audit original bits, not merely their potentially shorter count images."""
    width = scale * sum(problem.beta)
    bits = problem.vertices * width
    if len(raw) != (bits + 7) // 8 or (bits % 8 and int(raw[-1]) >> (bits % 8)):
        raise ValueError("original Boolean table length/padding mismatch")
    boundaries = list(problem.boundary)
    images = list(count_rows(raw, problem, np.array([v for v, _ in boundaries], dtype=np.int64), scale))
    for (_vertex, expected), image in zip(boundaries, images, strict=True):
        if tuple(image) != expected:
            raise ValueError("original Boolean occurrence boundary mismatch")
    checked = 0
    batch = max(1, min(8192, (4 * 1024**2) // max((width + 7) // 8, 1)))
    for axis, capacity in enumerate(problem.alpha):
        for first in range(0, problem.vertices, batch):
            vertices = np.arange(first, min(first + batch, problem.vertices), dtype=np.int64)
            left = vertices[vertices & (1 << axis) == 0]
            if not len(left):
                continue
            differences = packed_rows(raw, left, width) ^ packed_rows(raw, left | (1 << axis), width)
            distances = _POPCOUNT[differences].sum(axis=1, dtype=np.int64)
            if np.any(distances > capacity * scale):
                raise ValueError(f"original Boolean edge violation on axis {axis}")
            checked += len(left)
    if checked != problem.L * (problem.vertices // 2):
        raise ValueError("original Boolean edge coverage mismatch")
    return {
        "ok": True,
        "checked_edges": checked,
        "scope": "all-original-Boolean-cube-edges",
        "positive_scale": str(scale),
    }


def _config(problem: CountGeometry, scale: int, width: int) -> bytes:
    if not 8 <= width <= 64 or width % 8:
        raise ValueError("offline audit backend supports 64..512 bit counts")
    output = bytearray(b"HECCNT01")
    output.extend(struct.pack("<IIIIQ", problem.L, problem.G, width, problem.n + 1, problem.vertices))
    output.extend(struct.pack("<" + "Q" * problem.L, *problem.alpha))
    output.extend(struct.pack("<" + "Q" * problem.G, *problem.beta))
    output.extend(scale.to_bytes(width, "little"))
    for atom in range(problem.n + 1):
        vertex = sum(int(bool(support & (1 << atom))) << axis for axis, support in enumerate(problem.lhs))
        output.extend(struct.pack("<Q", vertex))
    output.extend(bytes(int(bool(support & (1 << atom))) for atom in range(problem.n + 1) for support in problem.rhs))
    return bytes(output)


def audit_counts(problem: CountGeometry, raw_path: Path, scale: int, width: int, binary: Path) -> dict:
    configuration = _config(problem, scale, width)
    config = raw_path.with_suffix(".audit-config")
    config.write_bytes(configuration)
    run = subprocess.run([str(binary), str(config), str(raw_path), "1"], capture_output=True, text=True)
    result = json.loads(run.stdout)
    expected = problem.L * (problem.vertices // 2)
    if run.returncode or not result.get("ok") or result.get("checked_edges") != expected:
        raise ValueError(f"fresh original-cube audit failed: {result}")
    return {
        "ok": True,
        "checked_edges": expected,
        "scope": "all-original-prefix-count-cube-edges",
        "positive_scale": str(scale),
        "auditor_binary_sha256": file_hash(binary),
        "configuration_sha256": hashlib.sha256(configuration).hexdigest(),
        "enumeration_mode": 1,
    }


def decode_original(source: Path, target: Path, record: dict) -> None:
    if source.stat().st_size != record["artifact_bytes"] or file_hash(source) != record["artifact_sha256"]:
        raise ValueError("original compressed artifact checksum/size mismatch")
    digest, size = hashlib.sha256(), 0
    with source.open("rb") as original, target.open("xb") as output:
        with zstd.ZstdDecompressor().stream_reader(original) as reader:
            for block in iter(lambda: reader.read(8 * 1024**2), b""):
                digest.update(block)
                size += len(block)
                output.write(block)
    if size != record["raw_bytes"] or digest.hexdigest() != record["raw_sha256"]:
        raise ValueError("original decoded artifact checksum/size mismatch")


def release_proofs(release: Path, binary: Path, selected: list[str], receipts: list[dict]):
    index = json.loads((release / "proofs/index.json").read_text())
    records = index["receipts"]
    if selected:
        matches = [record for record in records if any(record["id"].startswith(prefix) for prefix in selected)]
        for prefix in selected:
            if sum(record["id"].startswith(prefix) for record in matches) != 1:
                raise ValueError(f"case prefix missing or ambiguous: {prefix}")
        records = matches
    for number, record in enumerate(records, 1):
        start = time.monotonic()
        problem = geometry(record["n"], record["normal"])
        scale = record["positive_scale"]
        if type(scale) is not int or scale < 1:
            raise ValueError("source positive scale must be an exact positive integer")
        source = (release / record["artifact"]).resolve()
        if not source.is_relative_to(release.resolve()):
            raise ValueError("source artifact escapes its sealed release")
        vertices = np.array(list(compatible_vertices(problem)), dtype=np.int64)
        # Exactly one case's scratch data exists at a time. Never delete or
        # overwrite a completed proof, release, campaign table or seed cache.
        with tempfile.TemporaryDirectory(prefix="hec-count-migration-") as scratch:
            raw_path = Path(scratch) / "original.raw"
            decode_original(source, raw_path, record)
            if record["representation"] == "fixed-width-prefix-counts":
                width = record["count_bytes_per_entry"]
                audit = audit_counts(problem, raw_path, scale, width, binary)
                row_bytes = width * problem.G

                def rows(
                    raw_path=raw_path, vertices=vertices, row_bytes=row_bytes, width=width, scale=scale, problem=problem
                ):
                    with raw_path.open("rb") as raw:
                        for vertex in vertices:
                            raw.seek(int(vertex) * row_bytes)
                            data = raw.read(row_bytes)
                            if len(data) != row_bytes:
                                raise ValueError("truncated compatible seed row")
                            yield tuple(
                                Fraction(int.from_bytes(data[g * width : (g + 1) * width], "little"), scale)
                                for g in range(problem.G)
                            )

                proof = make_count_proof(problem, rows(), kernel=True, integral=False)
            elif record["representation"] == "packed-Boolean-bits":
                raw = np.memmap(raw_path, mode="r", dtype=np.uint8)
                audit = audit_boolean(raw, problem, scale)
                proof = make_count_proof(
                    problem, count_rows(raw, problem, vertices, scale), kernel=True, integral=False
                )
                del raw
            else:
                raise ValueError("unsupported one-time source representation")
        receipt = check_count_proof(proof)
        receipts.append(
            {
                "source_case_id": record["id"],
                "source_compressed_sha256": record["artifact_sha256"],
                "source_raw_sha256": record["raw_sha256"],
                "source_bytes": record["artifact_bytes"],
                "source_positive_scale": str(scale),
                "source_archive_path": str(source),
                "original_cube_audit": audit,
                "target_verification": receipt,
                "transformation": "extract-exact-complete-seed-and-certified-full-cube-extension",
                "preserves": "inequality-proof-not-every-original-output-bit",
                "audited_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        print(
            json.dumps(
                {
                    "case": record["id"],
                    "completed": number,
                    "selected": len(records),
                    "source_edges": audit["checked_edges"],
                    "seed_vertices": receipt["checked_vertices"],
                    "seconds": round(time.monotonic() - start, 3),
                }
            ),
            flush=True,
        )
        yield proof


def legacy_minimal(record: dict, problem: CountGeometry, scale: int = 1) -> bytes:
    if type(scale) is not int or scale < 1:
        raise ValueError("source positive scale must be an exact positive integer")
    if not isinstance(record, dict) or set(record) != {"lhs", "rhs", "images"}:
        raise ValueError("offline importer requires the historical minimal Boolean schema")
    labels = party_labels(problem.n)

    def label(support):
        return "".join(labels[i] for i in range(problem.n) if support >> i & 1)

    expected_lhs = [
        [label(support), scale * capacity] for support, capacity in zip(problem.lhs, problem.alpha, strict=True)
    ]
    expected_rhs = [
        [label(support), 1]
        for support, capacity in zip(problem.rhs, problem.beta, strict=True)
        for _ in range(scale * capacity)
    ]
    for side in (record["lhs"], record["rhs"]):
        if not isinstance(side, list) or any(
            not isinstance(term, list) or len(term) != 2 or type(term[1]) is not int for term in side
        ):
            raise ValueError("historical coefficients must be exact integers")
    if record["lhs"] != expected_lhs or record["rhs"] != expected_rhs:
        raise ValueError("historical proof geometry differs from its inequality")
    width = scale * sum(problem.beta)
    if not width:
        if record["images"] != []:
            raise ValueError("historical empty RHS must have no image payload")
        return b""
    rows = record["images"]
    if not isinstance(rows, list) or len(rows) != problem.vertices:
        raise ValueError("historical Boolean image table is incomplete")
    if any(not isinstance(row, str) or len(row) != width or set(row) - {"0", "1"} for row in rows):
        raise ValueError("invalid historical Boolean row")
    bits = np.frombuffer("".join(rows).encode("ascii"), dtype=np.uint8) - ord("0")
    return np.packbits(bits, bitorder="little").tobytes()


def archive_original(path: Path, archive: Path) -> Path:
    """Small legacy JSON snapshots are archive data, not live compatibility."""
    digest = file_hash(path)
    if archive.is_symlink():
        raise ValueError("unsafe original archive directory")
    archive.mkdir(parents=True, exist_ok=True)
    target = archive / f"{digest}.json"
    if target.exists():
        if target.is_symlink() or file_hash(target) != digest:
            raise ValueError("immutable original snapshot is corrupt")
    else:
        with path.open("rb") as source, target.open("xb") as output:
            for block in iter(lambda: source.read(1024**2), b""):
                output.write(block)
    if file_hash(target) != digest:
        raise ValueError("original snapshot copy differs")
    return target


def legacy_proofs(root: Path, parties: list[int], receipts: list[dict], archive: Path | None = None):
    for n in parties:
        source = root / f"n={n}" / "contractions.json"
        archived = archive_original(source, archive) if archive is not None else source
        normal_path = source.parent / "facets.json"
        archived_normals = archive_original(normal_path, archive) if archive is not None else normal_path
        normals = json.loads(archived_normals.read_text())
        records = json.loads(archived.read_text())
        if not isinstance(records, list):
            raise ValueError("this import mode handles the small historical JSON datasets, not packed manifests")
        if len(normals) != len(records):
            raise ValueError("historical facets/proofs are not aligned")
        for index, (normal, record) in enumerate(zip(normals, records, strict=True)):
            if any(type(value) is not int for value in normal):
                raise ValueError("source normal requires exact integer coefficients")
            scale = math.gcd(*normal) or 1
            problem = geometry(n, tuple(value // scale for value in normal))
            packed = legacy_minimal(record, problem, scale)
            raw = np.frombuffer(packed, dtype=np.uint8)
            audit = audit_boolean(raw, problem, scale)
            proof = make_count_proof(
                problem, count_rows(raw, problem, np.arange(problem.vertices), scale), integral=scale == 1
            )
            receipts.append(
                {
                    "source_n": n,
                    "source_index": index,
                    "source_archive_path": str(archived.resolve()),
                    "source_coefficient_positive_scale": str(scale),
                    "source_file_sha256": file_hash(archived),
                    "source_normals_archive_path": str(archived_normals.resolve()),
                    "source_normals_sha256": file_hash(archived_normals),
                    "source_record_sha256": hashlib.sha256(json.dumps(record, sort_keys=True).encode()).hexdigest(),
                    "original_cube_audit": audit,
                    "target_verification": check_count_proof(proof),
                    "transformation": "repeat-RHS-group-counts-with-canonical-prefix-blocks",
                    "preserves": "inequality-proof-not-every-original-output-bit",
                    "audited_at": datetime.now(timezone.utc).isoformat(),
                }
            )
            print(json.dumps({"n": n, "index": index, "source_edges": audit["checked_edges"]}), flush=True)
            yield proof


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    source = parser.add_subparsers(dest="source", required=True)
    legacy = source.add_parser("legacy-json")
    legacy.add_argument("root", type=Path)
    legacy.add_argument("--n", type=int, action="append", required=True)
    release = source.add_parser("sealed-release")
    release.add_argument("root", type=Path)
    release.add_argument("--audit-native", type=Path, required=True)
    release.add_argument("--case", action="append", default=[])
    args = parser.parse_args()
    args.destination.mkdir(parents=True, exist_ok=False)
    receipts = []
    if args.source == "legacy-json":
        proofs = legacy_proofs(args.root, args.n, receipts, args.destination / "original-archive")
    else:
        proofs = release_proofs(args.root, args.audit_native, args.case, receipts)
    inequality_entries = {}

    def indexed_proofs():
        for proof in proofs:
            problem = proof_geometry(proof)
            key = inequality_id(problem)
            entry = inequality_entries.setdefault(key, {"id": key, **problem.inequality(), "proof_ids": []})
            entry["proof_ids"].append(proof_id(proof))
            yield proof

    catalog = write_proof_catalog(args.destination / "proofs.json", indexed_proofs())
    for entry in inequality_entries.values():
        entry["proof_ids"].sort()
    inequalities = {
        "format": "hec-inequality-catalog/1",
        "entries": [inequality_entries[key] for key in sorted(inequality_entries)],
    }
    write_inequality_catalog(args.destination / "inequalities.json", inequalities)
    InequalityCatalog(args.destination / "inequalities.json").check_bindings(
        ProofCatalog(args.destination / "proofs.json")
    )
    report = {
        "format": "hec-proof-migration/1",
        "receipts": receipts,
        "catalog_sha256": file_hash(args.destination / "proofs.json"),
        "inequalities_sha256": file_hash(args.destination / "inequalities.json"),
        "proofs": len(catalog["entries"]),
        "shards": len(catalog["shards"]),
        "compressed_proof_bytes": sum(shard["bytes"] for shard in catalog["shards"].values()),
        "source_original_cube_edges": sum(item["original_cube_audit"]["checked_edges"] for item in receipts),
        "original_artifacts_modified": False,
    }
    (args.destination / "migration.json").write_bytes(canonical_json(report) + b"\n")
    print(json.dumps({key: value for key, value in report.items() if key != "receipts"}), flush=True)


if __name__ == "__main__":
    main()
