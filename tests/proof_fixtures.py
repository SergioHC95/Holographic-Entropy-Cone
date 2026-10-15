"""Current-language fixtures; deliberately invalid bytes are used only in tests."""

import atexit
import hashlib
import os
import tempfile
from pathlib import Path

import zstandard as zstd

from hec.count_proofs import canonical_json, geometry, inequality_id, proof_id
from hec.native import build_backends, load_backends
from hec.proof_builders import table_seed
from hec.proof_store import CATALOG_FORMAT
from hec.reconstruction import CUTS, make_pipeline

_native = None


def native_release():
    global _native
    if os.environ.get("HEC_NATIVE_DIR"):
        return load_backends(os.environ["HEC_NATIVE_DIR"])
    if _native is None:
        temporary = tempfile.TemporaryDirectory(prefix="hec-native-tests-")
        atexit.register(temporary.cleanup)
        directory = Path(temporary.name) / "release"
        build_backends(directory)
        _native = load_backends(directory)
    return _native


def document(problem, rows):
    return make_pipeline(problem, table_seed(problem, rows))


def departed_definition(problem):
    # Negative fixture, not an old-format reader or constructor.
    return {
        "format": "hec-count-proof/1",
        "inequality": problem.inequality(),
        "function": {"kind": "compatible-cancel-fill-kernel/1", "rows": {}},
        "clearing_scale": {"value": "1", "minimal": False},
    }


def cut_seed(problem, vertices, rows):
    terms = sorted(
        {(vertex, (problem.vertices - 1) ^ vertex) for vertex, row in zip(vertices, rows, strict=True) if any(row)}
    )
    references = {one: index for index, (one, _) in enumerate(terms)}
    return {
        "kind": CUTS,
        "terms": [[str(one), str(zero)] for one, zero in terms],
        "groups": [
            [
                sorted(references[vertex] for vertex, row in zip(vertices, rows, strict=True) if row[g] > layer)
                for layer in range(cap)
            ]
            for g, cap in enumerate(problem.beta)
        ],
    }


def write_frames(directory, documents, *, individual=False):
    """Stage canonical/hash-bound but intentionally unaudited adversarial fixtures."""
    directory.mkdir(parents=True, exist_ok=True)
    output = directory / "proof-shards"
    output.mkdir()
    entries, shards, pending, data = [], {}, [], bytearray()

    def seal():
        if not data:
            return
        shard = hashlib.sha256(data).hexdigest()
        (output / f"{shard}.proofpack").write_bytes(data)
        shards[shard] = {"bytes": len(data)}
        for entry in pending:
            entry["shard"] = shard
        data.clear()
        pending.clear()

    for doc in documents:
        frame = zstd.ZstdCompressor(write_checksum=True).compress(canonical_json(doc))
        p = geometry(doc["inequality"]["n"], tuple(map(int, doc["inequality"]["coefficients"])))
        entry = {"proof_id": proof_id(doc), "inequality_id": inequality_id(p), "offset": len(data), "bytes": len(frame)}
        entries.append(entry)
        pending.append(entry)
        data.extend(frame)
        if individual:
            seal()
    seal()
    path = directory / "proofs.json"
    path.write_bytes(canonical_json({"format": CATALOG_FORMAT, "entries": entries, "shards": shards}))
    return path
