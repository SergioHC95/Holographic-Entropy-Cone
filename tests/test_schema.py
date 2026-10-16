"""One closed syntax schema; complete mathematical acceptance stays independent."""

import copy
import json
import re
import tempfile
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator, ValidationError
from proof_fixtures import cut_seed, document, native_release, write_frames

from hec.count_proofs import canonical_json, compatible_vertices, geometry, parse_json
from hec.inequality_records import inequality_catalog
from hec.proof_builders import closure_seed, dag_seed
from hec.reconstruction import ReconstructionProgram, make_pipeline
from hec.reconstruction_verify import IntervalClosureDecoder
from hec.storage import INVENTORY_FORMAT

ROOT = Path(__file__).resolve().parents[1]


class SchemaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema = json.loads((ROOT / "schemas/repository.schema.json").read_text())
        Draft202012Validator.check_schema(cls.schema)
        cls.validator = Draft202012Validator(cls.schema)

    def fixture(self):
        p = geometry(3, (-1, -1, -1, 2, 2, 2, -1))
        vertices = list(compatible_vertices(p))
        rows = [
            (a * b * (1 - c), a * c * (1 - b), b * c * (1 - a), max(a, b, c))
            for x in vertices
            for a, b, c in [tuple((x >> axis) & 1 for axis in range(3))]
        ]
        return p, vertices, rows

    def test_all_seed_primitives_and_documented_example_obey_the_same_schema(self):
        p, vertices, rows = self.fixture()
        proofs = [
            document(p, rows),
            make_pipeline(p, dag_seed(p, rows)),
            make_pipeline(p, cut_seed(p, vertices, rows)),
            make_pipeline(
                p,
                closure_seed(p, rows, native_release()["closure"]),
                closure_backend=IntervalClosureDecoder(native_release()["closure"]),
            ),
        ]
        text = (ROOT / "docs/proofs.md").read_text()
        proofs.append(parse_json(text.split("```json", 1)[1].split("```", 1)[0].encode()))
        for proof in proofs:
            with self.subTest(kind=proof["function"]["seed"]["kind"]):
                self.validator.validate(proof)
                decoder = IntervalClosureDecoder(native_release()["closure"])
                self.assertTrue(ReconstructionProgram(proof, closure_backend=decoder).audit_reference()["ok"])

    def test_catalogues_and_inventory_have_closed_exact_shapes(self):
        p, _, rows = self.fixture()
        proof = document(p, rows)
        with tempfile.TemporaryDirectory() as directory:
            path = write_frames(Path(directory), [proof])
            catalog = json.loads(path.read_bytes())
            self.validator.validate(catalog)
            invalid = copy.deepcopy(catalog)
            invalid["entries"][0]["offset"] = True
            with self.assertRaises(ValidationError):
                self.validator.validate(invalid)
        self.validator.validate(inequality_catalog([proof]))
        inventory = {
            "format": INVENTORY_FORMAT,
            "entries": [{"path": "data/n=3/proofs.json", "sha256": "0" * 64, "bytes": 1}],
        }
        self.validator.validate(inventory)
        inventory["entries"][0]["path"] = "provenance/receipt.json"
        with self.assertRaises(ValidationError):
            self.validator.validate(inventory)

    def test_no_unknown_versioned_or_self_accepting_proof_is_admitted(self):
        p, _, rows = self.fixture()
        original = document(p, rows)
        for kind in ("format", "pipeline", "seed", "extra", "scale", "party"):
            proof = copy.deepcopy(original)
            if kind == "format":
                proof["format"] += "/" + str(1)
            elif kind == "pipeline":
                proof["function"]["kind"] = "unrecognized"
            elif kind == "seed":
                proof["function"]["seed"]["kind"] = "unrecognized"
            elif kind == "extra":
                proof["verified"] = True
            elif kind == "scale":
                proof["clearing_scale"]["value"] = "01"
            else:
                proof["inequality"]["n"] = True
            with self.subTest(kind=kind):
                with self.assertRaises(ValidationError):
                    self.validator.validate(proof)
                with self.assertRaises(ValueError):
                    ReconstructionProgram(proof)

    def test_schema_conformance_is_not_mathematical_acceptance(self):
        p, _, rows = self.fixture()
        proof = document(p, rows)
        proof["function"]["seed"] = {"kind": "integer-cut-dnf", "terms": [], "groups": [[[]] for _ in p.beta]}
        self.validator.validate(proof)
        with self.assertRaisesRegex(ValueError, "occurrence"):
            ReconstructionProgram(proof).audit_reference()

    def test_docs_links_are_live_and_artifact_identifiers_are_unversioned(self):
        for path in [ROOT / "README.md", *ROOT.glob("docs/*.md")]:
            for target in re.findall(r"\]\(([^)]+)\)", path.read_text()):
                if "://" not in target and not target.startswith("#"):
                    self.assertTrue((path.parent / target.split("#", 1)[0]).is_file(), target)
        constants = canonical_json(self.schema).decode()
        self.assertNotRegex(constants, r"(?:hec|compatible|integer|bounded|reduced)[a-z-]*/[0-9]+")
        self.assertEqual([path.name for path in ROOT.glob("schemas/*.json")], ["repository.schema.json"])
