from __future__ import annotations

import copy
import hashlib
import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import zstandard as zstd
from proof_fixtures import document

from hec import checks as row_checks
from hec.checks import check_stored_contractions, check_stored_facets, check_stored_graphs, check_stored_rays
from hec.count_proofs import canonical_json, compatible_vertices, geometry, proof_id
from hec.data import default_data_root
from hec.graph_store import GraphCatalog, write_graph_catalog
from hec.inequality_records import inequality_catalog, write_inequality_catalog
from hec.proof_store import write_proof_catalog
from hec.ray_store import RayCatalog, write_ray_catalog


def _temporary_dataset(n: int, *kinds: str) -> tuple[TemporaryDirectory, Path, dict[str, list]]:
    temporary = TemporaryDirectory()
    target = Path(temporary.name) / f"n={n}"
    target.mkdir()
    source = default_data_root() / f"n={n}"
    records = {
        kind: json.loads((source / f"{kind}.json").read_text(encoding="utf-8"))
        for kind in kinds
        if kind not in ("contractions", "graphs")
    }
    if "graphs" in kinds:
        records["graphs"] = list(GraphCatalog(source / "graphs.json"))
    for kind, values in records.items():
        if kind == "graphs":
            write_graph_catalog(target / "graphs.json", values)
        else:
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
            "kind": "compatible-scalar-dag",
            "scale": "1",
            "terminals": ["0"],
            "nodes": [],
            "roots": [0],
        }
        _replace_proof(target, mutated[0])

        with self.assertRaisesRegex(ValueError, "group count"):
            list(check_stored_contractions(temporary.name, n=1))


class StoredGraphCheckTests(unittest.TestCase):
    def test_generation_bound_is_enforced_before_exact_graph_work(self):
        graph = {"edges": [["A", "x1"], ["x1", "O"]], "weights": [1, 1]}
        with patch.object(row_checks, "DEFAULT_MAX_VERTICES", 2), patch.object(row_checks, "check_graph") as exact:
            index, error = row_checks._check_graph_pair((7, (1,), graph, 1))
        self.assertEqual(index, 7)
        self.assertIn("uses 3 vertices", error)
        exact.assert_not_called()

    def test_contiguous_jobs_need_only_their_own_ray_and_graph_payloads(self):
        with TemporaryDirectory() as temporary:
            directory = Path(temporary) / "n=2"
            directory.mkdir()
            rays = [(1, 0, 1), (0, 1, 1), (1, 1, 0)]
            graphs = [
                {"edges": [[left, right]], "weights": [1]} for left, right in (("A", "O"), ("B", "O"), ("A", "B"))
            ]
            write_ray_catalog(directory / "rays.json", rays, 2, shard_bytes=15)
            write_graph_catalog(directory / "graphs.json", graphs, shard_bytes=80)
            (directory / "facets.json").write_text("[[1,1,-1]]")
            ray_catalog, graph_catalog = RayCatalog(directory / "rays.json", 2), GraphCatalog(directory / "graphs.json")
            self.assertEqual(len(ray_catalog.shards), 3)
            self.assertEqual(len(graph_catalog.shards), 3)
            for catalog in (ray_catalog, graph_catalog):
                for ordinal in (0, 2):
                    path = directory / catalog.shards[ordinal].path
                    path.rename(path.with_suffix(".offline"))
            options = dict(n=2, shard_index=1, shard_count=3, partition_mode="contiguous", expect_rows=1)
            with patch.dict(os.environ, {"HEC_CHECK_WORKERS": "1"}):
                self.assertIn("1 ok", list(check_stored_graphs(temporary, **options))[0])
                self.assertIn("1 ok", list(check_stored_rays(temporary, **options))[0])

    def test_scaled_graph_is_rejected_as_nonprimitive(self) -> None:
        temporary, target, records = _temporary_dataset(1, "rays", "graphs")
        self.addCleanup(temporary.cleanup)
        records["graphs"][0]["weights"] = [2]
        write_graph_catalog(target / "graphs.json", records["graphs"])

        with self.assertRaisesRegex(ValueError, "canonical stored form"):
            list(check_stored_graphs(temporary.name, n=1))

    def test_out_of_range_party_label_is_rejected(self) -> None:
        temporary, target, records = _temporary_dataset(1, "rays", "graphs")
        self.addCleanup(temporary.cleanup)
        records["graphs"][0]["edges"] = [["A", "Z"]]
        write_graph_catalog(target / "graphs.json", records["graphs"])

        with self.assertRaisesRegex(ValueError, "not a terminal"):
            list(check_stored_graphs(temporary.name, n=1))


class StoredRankCheckTests(unittest.TestCase):
    def test_facets_and_rays_are_checked_in_both_rank_directions(self) -> None:
        temporary, _target, _records = _temporary_dataset(1, "facets", "rays")
        self.addCleanup(temporary.cleanup)

        self.assertEqual(list(check_stored_facets(temporary.name, n=1)), ["n=1: 1 ok"])
        self.assertEqual(list(check_stored_rays(temporary.name, n=1)), ["n=1: 1 ok"])

    def test_valid_contraction_for_a_nonfacet_does_not_pass_the_facet_rank_gate(self):
        from hec.reconstruction import ReconstructionProgram

        proof = document(geometry(2, (2, 1, -1)), [(0,), (1,), (1,)])
        self.assertTrue(ReconstructionProgram(proof).audit_reference()["ok"])
        temporary, target, _records = _temporary_dataset(2, "facets", "rays")
        self.addCleanup(temporary.cleanup)
        (target / "facets.json").write_text("[[2,1,-1]]")
        with self.assertRaisesRegex(ValueError, "rank 1 < 2"):
            list(check_stored_facets(temporary.name, n=2))

    def test_rank_batch_rejects_integer_dot_product_overflow_before_jit(self):
        temporary, target, _records = _temporary_dataset(1, "facets", "rays")
        self.addCleanup(temporary.cleanup)
        (target / "facets.json").write_text(json.dumps([[1 << 62]]))
        (target / "rays.json").write_text("[[4]]")
        with self.assertRaisesRegex(ValueError, "integer dot-product bound"):
            list(check_stored_facets(temporary.name, n=1))


class RowCoverageTests(unittest.TestCase):
    def test_both_partition_modes_are_disjoint_and_complete(self):
        for length in (0, 1, 2, 7, 32, 101):
            for groups in (1, 2, 3, 16):
                for mode in ("round-robin", "contiguous"):
                    rows = [
                        index
                        for group in range(groups)
                        for index in row_checks._shard_indices(length, group, groups, mode)
                    ]
                    with self.subTest(length=length, groups=groups, mode=mode):
                        self.assertEqual(sorted(rows), list(range(length)))
        self.assertEqual(list(row_checks._shard_indices(10, 1, 3)), [1, 4, 7])
        self.assertEqual(list(row_checks._shard_indices(10, 1, 3, "contiguous")), [3, 4, 5])
        for index, count, mode in (
            (True, 1, "contiguous"),
            (0, True, "contiguous"),
            (0, 0, "round-robin"),
            (1, 1, "round-robin"),
            (0, 1, "missing"),
        ):
            with self.assertRaises(ValueError):
                row_checks._shard_indices(10, index, count, mode)

    def stage(self, root, count):
        directory = root / "n=1"
        directory.mkdir()
        (directory / "rays.json").write_text(json.dumps([[1]] * count))
        (directory / "facets.json").write_text("[[1]]")
        write_graph_catalog(directory / "graphs.json", [{"edges": [["A", "O"]], "weights": [1]}] * count)

    def test_all_rows_are_visited_once_across_contiguous_graph_partitions(self):
        with TemporaryDirectory() as temporary:
            self.stage(Path(temporary), 7)
            with patch.object(row_checks, "_check_graph_pair", wraps=row_checks._check_graph_pair) as work:
                for group in range(3):
                    selected = row_checks._shard_indices(7, group, 3, "contiguous")
                    list(
                        check_stored_graphs(
                            temporary,
                            n=1,
                            shard_index=group,
                            shard_count=3,
                            partition_mode="contiguous",
                            expect_rows=len(selected),
                        )
                    )
            self.assertEqual(sorted(call.args[0][0] for call in work.call_args_list), list(range(7)))

    def test_missing_duplicate_and_out_of_partition_results_fail_closed(self):
        with TemporaryDirectory() as temporary, patch.dict(os.environ, {"HEC_CHECK_WORKERS": "2"}):
            self.stage(Path(temporary), 33)
            for results in ([], [(0, None), (0, None)], [(99, None)]):
                with (
                    patch.object(row_checks, "_bounded_parallel_map", return_value=iter(results)),
                    self.assertRaises(ValueError),
                ):
                    list(check_stored_graphs(temporary, n=1))
            valid = {"ok": True}
            for results in ([], [(1, valid), (1, valid)], [(99, valid)]):
                with (
                    patch.object(row_checks, "_bounded_parallel_map", return_value=iter(results)),
                    self.assertRaises(ValueError),
                ):
                    list(check_stored_rays(temporary, n=1))

    def test_expected_count_preflights_before_rank_preparation(self):
        with TemporaryDirectory() as temporary:
            self.stage(Path(temporary), 3)
            with patch.object(row_checks, "prepare_rank_candidates", side_effect=AssertionError("preflight first")):
                for expected in (2, True):
                    with self.assertRaisesRegex(ValueError, "planned row coverage"):
                        list(check_stored_rays(temporary, n=1, expect_rows=expected))


if __name__ == "__main__":
    unittest.main()
