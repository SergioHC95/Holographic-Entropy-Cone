"""Immutable, content-addressed, independently seekable LFS proof shards.

The catalogue is ordinary Git JSON. A shard is a sequence of independently
compressed canonical certificates; proof identities do not depend on shard
boundaries or compression settings. Only this format is read here.
"""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
from collections.abc import Iterable, Iterator, Sequence
from pathlib import Path

import zstandard as zstd

from .count_proofs import (
    DAG,
    FORMAT,
    KERNEL,
    TRANSPORT,
    canonical_json,
    check_count_proof,
    inequality_id,
    parse_json,
    proof_geometry,
    proof_id,
)

CATALOG_FORMAT = "hec-proof-catalog/1"
_HASH = re.compile(r"[0-9a-f]{64}\Z")
DEFAULT_SHARD_BYTES = 16 * 1024**2
MAX_RECORD_BYTES = 1024**3


def _digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024**2), b""):
            digest.update(chunk)
    return digest.hexdigest()


class ProofCatalog(Sequence[dict]):
    def __init__(self, path: str | Path):
        self.path = Path(path)
        catalog = parse_json(self.path.read_bytes())
        if not isinstance(catalog, dict) or set(catalog) != {"format", "entries", "shards"}:
            raise ValueError("unsupported proof catalogue")
        if catalog["format"] != CATALOG_FORMAT or not isinstance(catalog["entries"], list):
            raise ValueError("unsupported proof catalogue format")
        if not isinstance(catalog["shards"], dict):
            raise ValueError("shard index must be an object")
        self.entries, self.shards = catalog["entries"], catalog["shards"]
        self._verified: dict[str, tuple[int, int, int, int]] = {}
        intervals: dict[str, list[tuple[int, int]]] = {key: [] for key in self.shards}
        identities = set()
        for key, shard in self.shards.items():
            if _HASH.fullmatch(key) is None or not isinstance(shard, dict) or set(shard) != {"bytes"}:
                raise ValueError("invalid content-addressed shard")
            if type(shard["bytes"]) is not int or shard["bytes"] < 1:
                raise ValueError("invalid shard byte length")
        for entry in self.entries:
            if not isinstance(entry, dict) or set(entry) != {"inequality_id", "proof_id", "shard", "offset", "bytes"}:
                raise ValueError("invalid proof index entry")
            if any(
                not isinstance(entry[key], str) or _HASH.fullmatch(entry[key]) is None
                for key in ("inequality_id", "proof_id", "shard")
            ):
                raise ValueError("invalid proof/inequality/shard identity")
            if entry["proof_id"] in identities:
                raise ValueError("duplicate proof identity")
            identities.add(entry["proof_id"])
            if entry["shard"] not in self.shards:
                raise ValueError("indexed proof has no declared shard")
            if type(entry["offset"]) is not int or type(entry["bytes"]) is not int:
                raise ValueError("proof offsets/lengths must be integers")
            start, stop = entry["offset"], entry["offset"] + entry["bytes"]
            if start < 0 or entry["bytes"] < 1 or stop > self.shards[entry["shard"]]["bytes"]:
                raise ValueError("proof index outside its shard")
            intervals[entry["shard"]].append((start, stop))
        for key, ranges in intervals.items():
            cursor = 0
            for start, stop in sorted(ranges):
                if start != cursor:
                    raise ValueError("shard has overlapping records or unindexed bytes")
                cursor = stop
            if cursor != self.shards[key]["bytes"]:
                raise ValueError("shard has unindexed/trailing bytes")

    def __len__(self) -> int:
        return len(self.entries)

    def _shard_path(self, key: str) -> Path:
        path = self.path.parent / "proof-shards" / f"{key}.proofpack"
        if path.is_symlink() or path.parent.is_symlink() or not path.is_file():
            raise ValueError(f"missing/unsafe proof shard: {path}")
        stat = path.stat()
        fingerprint = stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns
        if self._verified.get(key) != fingerprint:
            if stat.st_size != self.shards[key]["bytes"] or _digest(path) != key:
                raise ValueError(f"proof shard length/SHA256 mismatch: {key}")
            self._verified[key] = fingerprint
        return path

    def __getitem__(self, index: int | slice) -> dict | list[dict]:
        if isinstance(index, slice):
            return [self[i] for i in range(*index.indices(len(self)))]
        entry = self.entries[index]
        with self._shard_path(entry["shard"]).open("rb") as source:
            source.seek(entry["offset"])
            compressed = source.read(entry["bytes"])
        # A seekable record is one frame, not a chain accepting trailing data.
        if not 0 <= zstd.frame_content_size(compressed) <= MAX_RECORD_BYTES:
            raise ValueError("proof frame exceeds the reader safety limit or has no declared size")
        raw = zstd.ZstdDecompressor().decompress(compressed, max_output_size=MAX_RECORD_BYTES, allow_extra_data=False)
        proof = parse_json(raw)
        if proof.get("format") != FORMAT:
            raise ValueError("authoritative catalogue accepts only the exact primary proof format")
        if canonical_json(proof) != raw or proof_id(proof) != entry["proof_id"]:
            raise ValueError("proof record is not canonical or differs from its identity")
        if inequality_id(proof_geometry(proof)) != entry["inequality_id"]:
            raise ValueError("proof differs from its indexed inequality")
        self._check_definition(proof)
        return proof

    def _check_definition(self, proof):
        if proof.get("format") != FORMAT or proof.get("function", {}).get("kind") not in (DAG, KERNEL, TRANSPORT):
            raise ValueError("authoritative catalogue accepts compact definitions, not audit tables")

    def iter_selected(self, shard: int = 0, shards: int = 1) -> Iterator[tuple[int, dict]]:
        if type(shard) is not int or type(shards) is not int or shards < 1 or not 0 <= shard < shards:
            raise ValueError("invalid verification shard")
        for index in range(shard, len(self), shards):
            yield index, self[index]

    def shard_group_entries(self, group: int = 0, groups: int = 1) -> list[int]:
        """Assign whole immutable shards; each payload belongs to one CI job."""
        if (
            type(group) is not int
            or type(groups) is not int
            or not 1 <= groups <= len(self.shards)
            or not 0 <= group < groups
        ):
            raise ValueError("invalid physical proof shard group")
        owned = set(sorted(self.shards)[group::groups])
        return [index for index, entry in enumerate(self.entries) if entry["shard"] in owned]

    def verify(self) -> dict:
        checked_edges = 0
        cube_edges, seed_edges = 0, 0
        for proof in self:
            edges = check_count_proof(proof)["checked_edges"]
            checked_edges += edges
            if proof["function"]["kind"] in (KERNEL, TRANSPORT):
                seed_edges += edges
            else:
                cube_edges += edges
        return {
            "ok": True,
            "proofs": len(self),
            "checked_edges": checked_edges,
            "shards": len(self.shards),
            "symbolic_original_cube_edges": cube_edges,
            "compatible_seed_edges": seed_edges,
        }


def write_proof_catalog(
    path: str | Path,
    proofs: Iterable[dict],
    *,
    shard_bytes: int = DEFAULT_SHARD_BYTES,
    compression_level: int = 9,
) -> dict:
    """Stage verified immutable shards, then atomically publish their catalogue.

    A single large record is kept whole; it may exceed the soft shard target.
    Existing immutable objects must match their names and are never replaced.
    """
    path = Path(path)
    if type(shard_bytes) is not int or shard_bytes < 1 or path.exists():
        raise ValueError("choose a positive shard target and a new catalogue destination")
    directory = path.parent / "proof-shards"
    if path.is_symlink() or directory.is_symlink():
        raise ValueError("unsafe catalogue destination")
    directory.mkdir(parents=True, exist_ok=True)
    compressor = zstd.ZstdCompressor(level=compression_level, write_checksum=True)
    entries, shards, pending, blocks = [], {}, [], bytearray()
    identities = set()

    def finish() -> None:
        if not blocks:
            return
        key = hashlib.sha256(blocks).hexdigest()
        target = directory / f"{key}.proofpack"
        if target.exists():
            if target.is_symlink() or target.stat().st_size != len(blocks) or _digest(target) != key:
                raise ValueError("existing immutable shard is corrupt")
        else:
            descriptor, temporary = tempfile.mkstemp(prefix=".proof-shard-", dir=directory)
            try:
                with os.fdopen(descriptor, "wb") as output:
                    output.write(blocks)
                    output.flush()
                    os.fsync(output.fileno())
                try:
                    os.link(temporary, target)
                except FileExistsError:
                    if target.is_symlink() or target.stat().st_size != len(blocks) or _digest(target) != key:
                        raise ValueError("racing immutable shard is corrupt") from None
            finally:
                Path(temporary).unlink(missing_ok=True)
        shards[key] = {"bytes": len(blocks)}
        for entry in pending:
            entry["shard"] = key
            entries.append(entry)
        pending.clear()
        blocks.clear()

    for proof in proofs:
        if proof.get("format") != FORMAT or proof.get("function", {}).get("kind") not in (DAG, KERNEL, TRANSPORT):
            raise ValueError("authoritative catalogue accepts compact definitions, not audit tables")
        receipt = check_count_proof(proof)
        identity = receipt["proof_id"]
        if identity in identities:
            raise ValueError("duplicate proof identity in catalogue")
        identities.add(identity)
        raw = canonical_json(proof)
        if len(raw) > MAX_RECORD_BYTES:
            raise ValueError("proof record exceeds reader safety limit")
        compressed = compressor.compress(raw)
        if blocks and len(blocks) + len(compressed) > shard_bytes:
            finish()
        pending.append(
            {
                "inequality_id": receipt["inequality_id"],
                "proof_id": identity,
                "offset": len(blocks),
                "bytes": len(compressed),
            }
        )
        blocks.extend(compressed)
    finish()
    catalog = {"format": CATALOG_FORMAT, "entries": entries, "shards": shards}
    # Only this process's temporary file is cleaned up. Original tables and
    # completed source proofs are outside this function's write scope.
    descriptor, name = tempfile.mkstemp(prefix=".proof-catalog-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(canonical_json(catalog) + b"\n")
            output.flush()
            os.fsync(output.fileno())
        # Hard-link publication is atomic and refuses races/existing targets.
        os.link(name, path)
    finally:
        Path(name).unlink(missing_ok=True)
    return catalog
