from __future__ import annotations

import copy
import hashlib
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import zstandard as zstd
from proof_fixtures import document

from hec.checks import check_stored_contractions, check_stored_facets, check_stored_graphs, check_stored_rays
from hec.count_proofs import canonical_json, compatible_vertices, geometry, proof_id
from hec.data import default_data_root
from hec.inequality_records import inequality_catalog, write_inequality_catalog
from hec.proof_store import write_proof_catalog


def _temporary_dataset(n: int, *kinds: str) -> tuple[TemporaryDirectory, Path, dict[str, list]]:
    temporary = TemporaryDirectory()
    target = Path(temporary.name) / f"n={n}"
    target.mkdir()
    source = default_data_root() / f"n={n}"
    records = {
        kind: json.loads((source / f"{kind}.json").read_text(encoding="utf-8"))
        for kind in kinds
        if kind != "contractions"
    }
    for kind, values in records.items():
        (target / f"{kind}.json").write_text(json.dumps(values), encoding="utf-8")
    if "contractions" in kinds:
        proofs = []
        for facet in records["facets"]:
            problem = geometry(n, tuple(facet))
            rows = [(vertex.bit_count() % 2,) if problem.G else () for vertex in compatible_vertices(problem)]
            proofs.append(document(problem, rows))
        write_proof_catalog(target / "proofs.json", proofs)
        write_inequality_catalog(target / "inequalities.json", inequality_catalog(proofs))
        records["contractions"] = proofs
    return temporary, target, records


def _replace_proof(target: Path, proof: dict) -> None:
    # The forged record has correct byte hashes and identities. Acceptance
    # must still reject bad mathematical syntax or a bad full-map definition.
    frame = zstd.ZstdCompressor().compress(canonical_json(proof))
    key = hashlib.sha256(frame).hexdigest()
    (target / "proof-shards" / f"{key}.proofpack").write_bytes(frame)
    catalog = json.loads((target / "proofs.json").read_text())
    catalog["entries"][0].update(proof_id=proof_id(proof), shard=key, bytes=len(frame))
    catalog["shards"] = {key: {"bytes": len(frame)}}
    (target / "proofs.json").write_bytes(canonical_json(catalog))
    inequalities = json.loads((target / "inequalities.json").read_text())
    inequalities["entries"][0]["proof_ids"] = [proof_id(proof)]
    (target / "inequalities.json").write_bytes(canonical_json(inequalities))


class StoredContractionCheckTests(unittest.TestCase):
    def test_noncanonical_fractional_coefficient_is_rejected(self) -> None:
        temporary, target, records = _temporary_dataset(2, "facets", "contractions")
        self.addCleanup(temporary.cleanup)
        mutated = copy.deepcopy(records["contractions"])
        mutated[0]["inequality"]["coefficients"][0] = "1.9"
        _replace_proof(target, mutated[0])

        with self.assertRaisesRegex(ValueError, "canonical decimal"):
            list(check_stored_contractions(temporary.name, n=2))

    def test_nonempty_images_for_empty_rhs_are_rejected(self) -> None:
        temporary, target, records = _temporary_dataset(1, "facets", "contractions")
        self.addCleanup(temporary.cleanup)
        mutated = copy.deepcopy(records["contractions"])
        mutated[0]["function"]["seed"] = {
            "kind": "compatible-scalar-dag/1",
            "scale": "1",
            "terminals": ["0"],
            "nodes": [],
            "roots": [0],
        }
        _replace_proof(target, mutated[0])

        with self.assertRaisesRegex(ValueError, "group count"):
            list(check_stored_contractions(temporary.name, n=1))


class StoredGraphCheckTests(unittest.TestCase):
    def test_scaled_graph_is_rejected_as_nonprimitive(self) -> None:
        temporary, target, records = _temporary_dataset(1, "rays", "graphs")
        self.addCleanup(temporary.cleanup)
        records["graphs"][0]["weights"] = [2]
        (target / "graphs.json").write_text(json.dumps(records["graphs"]), encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "canonical stored form"):
            list(check_stored_graphs(temporary.name, n=1))

    def test_out_of_range_party_label_is_rejected(self) -> None:
        temporary, target, records = _temporary_dataset(1, "rays", "graphs")
        self.addCleanup(temporary.cleanup)
        records["graphs"][0]["edges"] = [["A", "Z"]]
        (target / "graphs.json").write_text(json.dumps(records["graphs"]), encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "not a terminal"):
            list(check_stored_graphs(temporary.name, n=1))


class StoredRankCheckTests(unittest.TestCase):
    def test_facets_and_rays_are_checked_in_both_rank_directions(self) -> None:
        temporary, _target, _records = _temporary_dataset(1, "facets", "rays")
        self.addCleanup(temporary.cleanup)

        self.assertEqual(list(check_stored_facets(temporary.name, n=1)), ["n=1: 1 ok"])
        self.assertEqual(list(check_stored_rays(temporary.name, n=1)), ["n=1: 1 ok"])


if __name__ == "__main__":
    unittest.main()
