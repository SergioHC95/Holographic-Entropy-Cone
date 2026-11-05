from __future__ import annotations

import hashlib
import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import zstandard as zstd
from jsonschema import Draft202012Validator, ValidationError

from hec.checks import check_stored_facets
from hec.count_proofs import canonical_json, geometry, inequality_id
from hec.facet_witnesses import FORMAT, MODEL_FORMAT, FacetWitnessCatalog, row_digest, verify_model


def model():
    return {
        "format": MODEL_FORMAT,
        "n": 2,
        "vertices": 3,
        "edges": [[1, 2]],
        "capacities": ["1"],
        "cuts": [
            {"mask": 1, "value": "0", "shore": "1", "flows": ["0"]},
            {"mask": 2, "value": "1", "shore": "2", "flows": ["1"]},
            {"mask": 3, "value": "1", "shore": "3", "flows": ["1"]},
        ],
    }


def write(directory, proposal=None, fixed=(1, 1, -1), duplicate=False):
    proposal = model() if proposal is None else proposal
    raw = canonical_json(proposal)
    identity = hashlib.sha256(raw).hexdigest()
    frame = zstd.ZstdCompressor().compress(raw)
    shard = hashlib.sha256(frame).hexdigest()
    (directory / "witness-shards").mkdir(exist_ok=True)
    (directory / "witness-shards" / (shard + ".witnesspack")).write_bytes(frame)
    ref = {"model": identity, "permutation": 0}
    document = {
        "format": FORMAT,
        "n": 2,
        "shards": {shard: {"bytes": len(frame)}},
        "models": {identity: {"shard": shard, "offset": 0, "bytes": len(frame)}},
        "facets": [
            {
                "inequality_id": inequality_id(geometry(2, fixed)),
                "basis": [ref if duplicate else {"ray": 0, "permutation": 0, "row_sha256": row_digest((1, 0, 1))}, ref],
            }
        ],
    }
    path = directory / "facet-witnesses.json"
    path.write_bytes(canonical_json(document))
    return path


class FacetWitnessTests(unittest.TestCase):
    def test_closed_repository_schema_covers_both_rank_witness_documents(self):
        schema = json.loads((Path(__file__).resolve().parents[1] / "schemas/repository.schema.json").read_bytes())
        validator = Draft202012Validator(schema)
        validator.validate(model())
        with TemporaryDirectory() as temporary:
            path = write(Path(temporary))
            document = json.loads(path.read_bytes())
            validator.validate(document)
            document["verified"] = True
            with self.assertRaises(ValidationError):
                validator.validate(document)

    def test_graph_entropy_is_proved_by_all_exact_flow_cut_equalities(self):
        self.assertEqual(verify_model(model(), 2), (0, 1, 1))

    def test_missing_coordinate_wrong_shore_and_infeasible_flow_fail(self):
        bad = []
        missing = model()
        missing["cuts"].pop()
        bad.append(missing)
        shore = model()
        shore["cuts"][1]["shore"] = "1"
        bad.append(shore)
        flow = model()
        flow["cuts"][1]["flows"] = ["2"]
        bad.append(flow)
        false = model()
        false["cuts"][1]["value"] = "0"
        bad.append(false)
        for proposal in bad:
            with self.subTest(proposal=proposal), self.assertRaises(ValueError):
                verify_model(proposal, 2)

    def test_bulk_flow_conservation_is_required(self):
        proposal = model()
        proposal.update(vertices=4, edges=[[1, 3], [3, 2]], capacities=["1", "1"])
        for cut in proposal["cuts"]:
            cut["flows"] = ["1", "0"]
        with self.assertRaisesRegex(ValueError, "conservation"):
            verify_model(proposal, 2)

    def test_current_ray_and_verified_model_complete_the_facet_rank(self):
        with TemporaryDirectory() as temporary:
            directory = Path(temporary) / "n=2"
            directory.mkdir()
            write(directory)
            (directory / "facets.json").write_text("[[1,1,-1]]")
            (directory / "rays.json").write_text("[[1,0,1]]")
            with patch.dict(os.environ, {"HEC_CHECK_WORKERS": "1"}):
                self.assertEqual(list(check_stored_facets(temporary, n=2)), ["n=2: 1 ok"])

    def test_rehashed_false_graph_certificate_cannot_manufacture_a_facet(self):
        with TemporaryDirectory() as temporary:
            directory = Path(temporary)
            forged = model()
            forged["cuts"][1]["flows"] = ["0"]
            catalogue = FacetWitnessCatalog(write(directory, forged), 2)
            with self.assertRaisesRegex(ValueError, "flow and cut"):
                catalogue.verify_facet((1, 1, -1), [(1, 0, 1)])

    def test_dependent_basis_and_changed_ray_identity_fail(self):
        with TemporaryDirectory() as temporary:
            directory = Path(temporary)
            catalogue = FacetWitnessCatalog(write(directory, duplicate=True), 2)
            with self.assertRaisesRegex(ValueError, "dependent"):
                catalogue.verify_facet((1, 1, -1), [(1, 0, 1)])
            catalogue = FacetWitnessCatalog(write(directory), 2)
            with self.assertRaisesRegex(ValueError, "ray witness identity"):
                catalogue.verify_facet((1, 1, -1), [(0, 1, 1)])

    def test_valid_nonfacet_cannot_pass_with_nontight_graph_witnesses(self):
        with TemporaryDirectory() as temporary:
            catalogue = FacetWitnessCatalog(write(Path(temporary), fixed=(2, 1, -1)), 2)
            with self.assertRaisesRegex(ValueError, "not exactly tight"):
                catalogue.verify_facet((2, 1, -1), [(1, 0, 1)])

    def test_orphan_binding_and_corrupt_shard_fail_closed(self):
        with TemporaryDirectory() as temporary:
            directory = Path(temporary)
            catalogue = FacetWitnessCatalog(write(directory), 2)
            with self.assertRaisesRegex(ValueError, "no stored facet"):
                catalogue.check_bindings([])
            path = next((directory / "witness-shards").iterdir())
            path.write_bytes(path.read_bytes() + b"x")
            with self.assertRaises(ValueError):
                catalogue.verify_facet((1, 1, -1), [(1, 0, 1)])

    def test_float_and_boolean_contexts_cannot_be_truncated_into_acceptance(self):
        with TemporaryDirectory() as temporary:
            catalogue = FacetWitnessCatalog(write(Path(temporary)), 2)
            for fixed in ((1.5, 1, -1), (True, 1, -1)):
                with self.subTest(fixed=fixed), self.assertRaisesRegex(ValueError, "exact integers"):
                    catalogue.verify_facet(fixed, [(1, 0, 1)])
            with self.assertRaisesRegex(ValueError, "exact integers"):
                catalogue.verify_facet((1, 1, -1), [(1.5, 0, 1)])


if __name__ == "__main__":
    unittest.main()
