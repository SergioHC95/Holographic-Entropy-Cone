import hashlib
import json
import math
import os
import tempfile
import unittest
from itertools import combinations
from pathlib import Path
from unittest.mock import patch

import numpy as np
from numba import njit
from proof_fixtures import document

from hec.checks import check_stored_facet_database_format
from hec.contractions import read_contractions
from hec.count_proofs import geometry
from hec.data import load_hec_data
from hec.inequality_records import inequality_catalog, write_inequality_catalog
from hec.proof_store import write_proof_catalog
from hec.rank import check_support_rank
from hec.serialization import read_integer_rows
from hec.symmetry import permutation_array


@njit(cache=True)
def _orbit_image_count(rows, maps):
    """Orbit-stabilizer count; no expanded multi-million-row orbit tables."""
    total = 0
    for row in rows:
        stabilizer = 0
        for mapping in maps:
            for coordinate in range(len(row)):
                if row[coordinate] != row[mapping[coordinate]]:
                    break
            else:
                stabilizer += 1
        assert stabilizer > 0 and len(maps) % stabilizer == 0
        total += len(maps) // stabilizer
    return total


class ReadmeDataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(__file__).resolve().parents[1]
        cls.readme = (cls.root / "README.md").read_text()
        cls.datasets = []
        for directory in sorted((cls.root / "data").glob("n=*"), key=lambda path: int(path.name[2:])):
            docs = {
                kind: json.loads((directory / f"{kind}.json").read_bytes())
                for kind in ("facets", "rays", "graphs", "inequalities", "proofs")
            }
            cls.datasets.append((int(directory.name[2:]), docs))

    def test_cone_table_matches_every_tracked_catalogue_and_exact_orbit_size(self):
        table = self.readme.split("## Cone summary\n", 1)[1].split("\n## ", 1)[0]
        actual = [line for line in table.splitlines() if line.startswith("| ")][2:]
        expected = []
        for n, docs in self.datasets:
            facets, rays = docs["facets"], docs["rays"]
            proofs, inequalities = docs["proofs"]["entries"], docs["inequalities"]["entries"]
            with self.subTest(n=n):
                self.assertEqual(len(docs["graphs"]), len(rays))
                self.assertEqual(len(proofs), len(inequalities))
                self.assertEqual(len(facets), len(proofs))
            maps = permutation_array(n)
            facet_images = _orbit_image_count(np.asarray(facets, dtype=np.int64), maps)
            ray_images = _orbit_image_count(np.asarray(rays, dtype=np.int64), maps)
            status = "complete" if n <= 5 else "partial"
            expected.append(
                f"| {n} | {len(facets):,} | {facet_images:,} | {len(rays):,} | "
                f"{ray_images:,} | {len(proofs):,} | {status} |"
            )
        self.assertEqual(actual, expected)

    def test_documented_totals_and_facet_only_membership_match_catalogues(self):
        proofs = sum(len(docs["proofs"]["entries"]) for _, docs in self.datasets)
        shards = sum(len(docs["proofs"]["shards"]) for _, docs in self.datasets)
        payload_bytes = sum(shard["bytes"] for _, docs in self.datasets for shard in docs["proofs"]["shards"].values())
        for phrase in (f"{proofs:,} full-map proofs", f"{shards:,} proof shards", f"{payload_bytes:,} bytes"):
            self.assertIn(f"**{phrase}**", self.readme)
        n6 = dict(self.datasets)[6]
        self.assertEqual(len(n6["facets"]), len(n6["inequalities"]["entries"]))
        self.assertIn(f"**{len(n6['facets']):,} listed facet representatives**", self.readme)
        self.assertIn("exactly one full-map proof per listed facet", self.readme)

    def test_orbit_stabilizer_matches_explicit_unique_images_on_small_controls(self):
        rng = np.random.default_rng(12301)
        for n in range(1, 6):
            maps = permutation_array(n)
            rows = rng.integers(-2, 3, size=(6, maps.shape[1]), dtype=np.int64)
            rows[0] = 0
            expected = sum(len(np.unique(row[maps], axis=0)) for row in rows)
            with self.subTest(n=n):
                self.assertEqual(_orbit_image_count(rows, maps), expected)

    def _certified_facet_ray_pair(self):
        data = dict(self.datasets)[6]
        ray_id = "39484b4dc968ef126c6fa47184797b727397c291fb831c2105dee3ba703cad8f"
        pairs = [
            (ray, graph)
            for ray, graph in zip(data["rays"], data["graphs"], strict=True)
            if hashlib.sha256(json.dumps(ray, separators=(",", ":")).encode()).hexdigest() == ray_id
        ]
        self.assertEqual(len(pairs), 1)
        identity = "e7b8a988f55d1418c78bfc1e2e1580952fcfbc2d418d37b7097480e021eb1e10"
        entry = next(row for row in data["inequalities"]["entries"] if row["id"] == identity)
        facet = [int(value) for value in entry["coefficients"]]
        self.assertIn(facet, data["facets"])
        proofs = [row["proof_id"] for row in data["proofs"]["entries"] if row["inequality_id"] == identity]
        self.assertEqual(proofs, entry["proof_ids"])
        self.assertEqual(len(proofs), 1)
        return facet, *pairs[0]

    def test_certified_ray_graph_matches_exhaustive_integer_cuts(self):
        _facet, ray, graph = self._certified_facet_ray_pair()
        terminals = set("ABCDEFO")
        bulk = sorted({vertex for edge in graph["edges"] for vertex in edge} - terminals)
        self.assertLessEqual(len(bulk), 8)
        self.assertTrue(all(type(weight) is int and weight > 0 for weight in graph["weights"]))
        observed = []
        for size in range(1, 7):
            for subsystem in combinations("ABCDEF", size):
                costs = []
                for mask in range(1 << len(bulk)):
                    inside = set(subsystem) | {vertex for index, vertex in enumerate(bulk) if mask >> index & 1}
                    costs.append(
                        sum(
                            weight
                            for (left, right), weight in zip(graph["edges"], graph["weights"], strict=True)
                            if (left in inside) != (right in inside)
                        )
                    )
                observed.append(min(costs))
        divisor = math.gcd(*observed)
        self.assertGreater(divisor, 0)
        self.assertEqual([value // divisor for value in observed], ray)

    def test_certified_facet_ray_pair_has_both_support_ranks(self):
        facet, ray, _graph = self._certified_facet_ray_pair()
        data = dict(self.datasets)[6]
        self.assertTrue(check_support_rank(facet, data["rays"], 6)["ok"])
        self.assertTrue(check_support_rank(ray, data["facets"], 6)["ok"])


class CompactDatabaseTests(unittest.TestCase):
    def fixture(self, root):
        directory = root / "n=2"
        directory.mkdir()
        directory.joinpath("facets.json").write_text("[[1,1,-1]]\n")
        proof = document(geometry(2, (1, 1, -1)), [(0,), (1,), (1,)])
        write_proof_catalog(directory / "proofs.json", [proof])
        write_inequality_catalog(directory / "inequalities.json", inequality_catalog([proof]))
        return directory, proof

    def test_normal_reader_and_database_require_exact_proof_catalogues(self):
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
