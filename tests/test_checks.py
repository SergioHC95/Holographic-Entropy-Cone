from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from hec.checks import check_stored_contractions, check_stored_graphs
from hec.data import default_data_root


def _temporary_dataset(n: int, *kinds: str) -> tuple[TemporaryDirectory, Path, dict[str, list]]:
    temporary = TemporaryDirectory()
    target = Path(temporary.name) / f"n={n}"
    target.mkdir()
    source = default_data_root() / f"n={n}"
    records = {kind: json.loads((source / f"{kind}.json").read_text(encoding="utf-8")) for kind in kinds}
    for kind, values in records.items():
        (target / f"{kind}.json").write_text(json.dumps(values), encoding="utf-8")
    return temporary, target, records


class StoredContractionCheckTests(unittest.TestCase):
    def test_noncanonical_fractional_coefficient_is_rejected(self) -> None:
        temporary, target, records = _temporary_dataset(2, "facets", "contractions")
        self.addCleanup(temporary.cleanup)
        mutated = copy.deepcopy(records["contractions"])
        mutated[0]["lhs"][0][1] = 1.9
        (target / "contractions.json").write_text(json.dumps(mutated), encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "canonical stored form"):
            list(check_stored_contractions(temporary.name, n=2))

    def test_nonempty_images_for_empty_rhs_are_rejected(self) -> None:
        temporary, target, records = _temporary_dataset(1, "facets", "contractions")
        self.addCleanup(temporary.cleanup)
        mutated = copy.deepcopy(records["contractions"])
        mutated[0]["images"] = [""]
        (target / "contractions.json").write_text(json.dumps(mutated), encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "canonical stored form"):
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


if __name__ == "__main__":
    unittest.main()
