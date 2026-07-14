from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from hec.checks import check_stored_contractions, check_stored_graphs
from hec.data import default_data_root


class StoredContractionCheckTests(unittest.TestCase):
    def _temporary_dataset(self, n: int) -> tuple[TemporaryDirectory, Path, list, list]:
        temporary = TemporaryDirectory()
        root = Path(temporary.name)
        target = root / f"n={n}"
        target.mkdir()
        source = default_data_root() / f"n={n}"
        facets = json.loads((source / "facets.json").read_text(encoding="utf-8"))
        contractions = json.loads((source / "contractions.json").read_text(encoding="utf-8"))
        (target / "facets.json").write_text(json.dumps(facets), encoding="utf-8")
        return temporary, target, facets, contractions

    def test_noncanonical_fractional_coefficient_is_rejected(self) -> None:
        temporary, target, _facets, contractions = self._temporary_dataset(2)
        self.addCleanup(temporary.cleanup)
        mutated = copy.deepcopy(contractions)
        mutated[0]["lhs"][0][1] = 1.9
        (target / "contractions.json").write_text(json.dumps(mutated), encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "canonical stored form"):
            list(check_stored_contractions(temporary.name, n=2))

    def test_nonempty_images_for_empty_rhs_are_rejected(self) -> None:
        temporary, target, _facets, contractions = self._temporary_dataset(1)
        self.addCleanup(temporary.cleanup)
        mutated = copy.deepcopy(contractions)
        mutated[0]["images"] = [""]
        (target / "contractions.json").write_text(json.dumps(mutated), encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "canonical stored form"):
            list(check_stored_contractions(temporary.name, n=1))


class StoredGraphCheckTests(unittest.TestCase):
    def _temporary_dataset(self) -> tuple[TemporaryDirectory, Path, list]:
        temporary = TemporaryDirectory()
        root = Path(temporary.name)
        target = root / "n=1"
        target.mkdir()
        source = default_data_root() / "n=1"
        rays = json.loads((source / "rays.json").read_text(encoding="utf-8"))
        graphs = json.loads((source / "graphs.json").read_text(encoding="utf-8"))
        (target / "rays.json").write_text(json.dumps(rays), encoding="utf-8")
        return temporary, target, graphs

    def test_scaled_graph_is_rejected_as_nonprimitive(self) -> None:
        temporary, target, graphs = self._temporary_dataset()
        self.addCleanup(temporary.cleanup)
        graphs[0]["weights"] = [2]
        (target / "graphs.json").write_text(json.dumps(graphs), encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "canonical stored form"):
            list(check_stored_graphs(temporary.name, n=1))

    def test_out_of_range_party_label_is_rejected(self) -> None:
        temporary, target, graphs = self._temporary_dataset()
        self.addCleanup(temporary.cleanup)
        graphs[0]["edges"] = [["A", "Z"]]
        (target / "graphs.json").write_text(json.dumps(graphs), encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "not a terminal"):
            list(check_stored_graphs(temporary.name, n=1))


if __name__ == "__main__":
    unittest.main()
