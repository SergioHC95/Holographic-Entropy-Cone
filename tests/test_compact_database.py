import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from proof_fixtures import document

from hec.checks import check_stored_facet_database_format
from hec.contractions import read_contractions
from hec.count_proofs import geometry
from hec.data import load_hec_data
from hec.inequality_records import inequality_catalog, write_inequality_catalog
from hec.proof_store import write_proof_catalog
from hec.serialization import read_integer_rows


class CompactDatabaseTests(unittest.TestCase):
    def fixture(self, root):
        directory = root / "n=2"
        directory.mkdir()
        directory.joinpath("facets.json").write_text("[[1,1,-1]]\n")
        proof = document(geometry(2, (1, 1, -1)), [(0,), (1,), (1,)])
        write_proof_catalog(directory / "proofs.json", [proof])
        write_inequality_catalog(directory / "inequalities.json", inequality_catalog([proof]))
        return directory, proof

    def test_normal_reader_and_database_are_new_format_only(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data, _proof = self.fixture(root)
            with patch.dict(os.environ, {"HEC_CHECK_WORKERS": "1"}, clear=False):
                result = list(check_stored_facet_database_format(root, n=2))
            self.assertIn("complete full-map audits", result[-1])
            self.assertEqual(len(load_hec_data(2, "contractions", root=root)), 1)
            old = data / "contractions.json"
            old.write_text("[]")
            with self.assertRaises(ValueError):
                read_contractions(old)

    def test_identity_mismatch_and_missing_proof_fail(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data, _proof = self.fixture(root)
            data.joinpath("facets.json").write_text("[[2,1,-1]]")
            with self.assertRaisesRegex(ValueError, "known facets"):
                list(check_stored_facet_database_format(root, n=2))

    def test_integer_dataset_floats_and_bools_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "facets.json"
            for value in (1.0, True):
                target.write_text(json.dumps([[value, 1, -1]]))
                with self.assertRaises(ValueError):
                    read_integer_rows(target, n=2)
