"""Sharded graph bytes confer no mathematical acceptance."""

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator, ValidationError

from hec.checks import check_stored_graphs
from hec.graph_store import GRAPH_FORMAT, GRAPH_SHARD_BYTES, GraphCatalog, write_graph_catalog
from hec.graphs import read_graphs, write_graphs


class GraphStoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.path = self.root / "graphs.json"
        self.graphs = [{"edges": [["A", "O"]], "weights": [i]} for i in range(1, 13)]

    def write(self):
        write_graph_catalog(self.path, self.graphs, shard_bytes=100)
        return json.loads(self.path.read_bytes())

    def mutate(self, document):
        self.path.write_text(json.dumps(document))

    def test_deterministic_complete_alignment_and_one_shard_cache(self):
        before = self.write()
        other = self.root / "other" / "graphs.json"
        write_graph_catalog(other, iter(self.graphs), shard_bytes=100)
        self.assertEqual(self.path.read_bytes(), other.read_bytes())
        catalog = GraphCatalog(self.path)
        self.assertGreater(len(catalog.shards), 1)
        self.assertEqual(len(catalog), len(self.graphs))
        self.assertEqual(list(catalog), self.graphs)
        self.assertEqual(catalog[::-2], self.graphs[::-2])
        for index in range(len(catalog)):
            self.assertEqual(catalog[index], self.graphs[index])
            self.assertLessEqual(len(catalog._cached_records), max(s.count for s in catalog.shards))
        self.assertEqual(catalog[-1], self.graphs[-1])
        for index in (len(catalog), -len(catalog) - 1):
            with self.assertRaises(IndexError):
                catalog[index]
        with self.assertRaises(TypeError):
            catalog[0.5]
        for shard in before["shards"]:
            payload = self.root / "graph-shards" / (shard["sha256"] + ".json")
            data = payload.read_bytes()
            self.assertEqual(len(data), shard["bytes"])
            self.assertLessEqual(len(data), 100)
            self.assertEqual(hashlib.sha256(data).hexdigest(), shard["sha256"])
            self.assertEqual(data, (other.parent / "graph-shards" / payload.name).read_bytes())

    def test_empty_and_public_graph_roundtrip_use_only_the_current_format(self):
        write_graphs(self.path, [])
        self.assertEqual(read_graphs(self.path), [])
        self.assertEqual(json.loads(self.path.read_bytes()), {"format": GRAPH_FORMAT, "count": 0, "shards": []})
        graph = {"edges": [["A", "B"]], "weights": [1]}
        write_graphs(self.path, [graph])
        self.assertEqual(read_graphs(self.path), [graph])
        self.path.write_text(json.dumps([graph]))
        with self.assertRaisesRegex(ValueError, "index"):
            GraphCatalog(self.path)

    def test_arbitrary_exact_integer_and_rational_weights_are_not_safe_index_limited(self):
        graphs = [{"edges": [["A", "B"]], "weights": [1 << 90]}, {"edges": [["A", "B"]], "weights": ["13/17"]}]
        write_graphs(self.path, graphs)
        self.assertEqual(read_graphs(self.path), graphs)

    def test_unknown_duplicate_and_inexact_index_fields_fail_closed(self):
        original = self.write()
        bad = []
        for key, value in (("format", GRAPH_FORMAT + "/1"), ("count", True), ("count", original["count"] + 1)):
            item = copy.deepcopy(original)
            item[key] = value
            bad.append(item)
        item = copy.deepcopy(original)
        item["verified"] = True
        bad.append(item)
        for key, value in (
            ("count", True),
            ("count", 0),
            ("bytes", True),
            ("bytes", GRAPH_SHARD_BYTES + 1),
            ("sha256", "../escape"),
            ("sha256", "A" * 64),
        ):
            item = copy.deepcopy(original)
            item["shards"][0][key] = value
            bad.append(item)
        item = copy.deepcopy(original)
        item["count"] += item["shards"][0]["count"]
        item["shards"].append(item["shards"][0])
        bad.append(item)
        for item in bad:
            self.mutate(item)
            with self.subTest(item=item), self.assertRaises(ValueError):
                GraphCatalog(self.path)
        self.path.write_text('{"format":"x","format":"y","count":0,"shards":[]}')
        with self.assertRaisesRegex(ValueError, "duplicate"):
            GraphCatalog(self.path)

    def test_missing_truncated_and_rehashed_wrong_row_count_are_rejected(self):
        original = self.write()
        record = original["shards"][0]
        path = self.root / "graph-shards" / (record["sha256"] + ".json")
        saved = path.read_bytes()
        path.unlink()
        with self.assertRaises(FileNotFoundError):
            GraphCatalog(self.path)[0]
        path.write_bytes(saved[:-1])
        with self.assertRaisesRegex(ValueError, "identity mismatch"):
            GraphCatalog(self.path)[0]
        path.write_bytes(saved.replace(b'"weights"', b'"Weights"'))
        with self.assertRaisesRegex(ValueError, "identity mismatch"):
            GraphCatalog(self.path)[0]
        wrong = b"[]\n"
        digest = hashlib.sha256(wrong).hexdigest()
        (path.parent / (digest + ".json")).write_bytes(wrong)
        original["shards"][0].update(sha256=digest, bytes=len(wrong))
        self.mutate(original)
        with self.assertRaisesRegex(ValueError, "row count"):
            GraphCatalog(self.path)[0]

    def test_payload_floats_duplicate_keys_and_symlinks_cannot_be_accepted(self):
        original = self.write()
        for data in (b'[{"weights":[1.0]}]', b'[{"edges":[],"edges":[]}]'):
            digest = hashlib.sha256(data).hexdigest()
            (self.root / "graph-shards" / (digest + ".json")).write_bytes(data)
            item = copy.deepcopy(original)
            item["shards"][0].update(sha256=digest, bytes=len(data))
            self.mutate(item)
            with self.assertRaises(ValueError):
                GraphCatalog(self.path)[0]
        self.mutate(original)
        payload = self.root / "graph-shards" / (original["shards"][0]["sha256"] + ".json")
        payload.rename(self.root / "saved.json")
        payload.symlink_to(self.root / "saved.json")
        with self.assertRaisesRegex(ValueError, "symlink"):
            GraphCatalog(self.path)[0]

    def test_writer_never_overwrites_an_immutable_payload_and_enforces_budgets(self):
        original = self.write()
        path = self.root / "graph-shards" / (original["shards"][0]["sha256"] + ".json")
        path.write_bytes(b"broken")
        with self.assertRaisesRegex(ValueError, "immutable"):
            write_graph_catalog(self.path, self.graphs, shard_bytes=100)
        self.assertEqual(path.read_bytes(), b"broken")
        for budget in (True, 2, GRAPH_SHARD_BYTES + 1):
            with self.assertRaises(ValueError):
                write_graph_catalog(self.path, [], shard_bytes=budget)
        with self.assertRaisesRegex(ValueError, "exceeds"):
            write_graph_catalog(self.root / "tiny.json", self.graphs, shard_bytes=5)

    def test_hashes_and_well_formed_metadata_do_not_authorize_invalid_graphs(self):
        target = self.root / "n=1"
        target.mkdir()
        (target / "rays.json").write_text("[[1]]")
        write_graph_catalog(target / "graphs.json", [{"edges": [["A", "O"]], "weights": [2]}])
        with self.assertRaisesRegex(ValueError, "canonical stored form"):
            list(check_stored_graphs(self.root, n=1))

    def test_catalogue_schema_is_closed_and_unversioned(self):
        schema = json.loads((Path(__file__).parents[1] / "schemas/repository.schema.json").read_bytes())
        validator = Draft202012Validator(schema)
        original = self.write()
        validator.validate(original)
        original["shards"][0]["bytes"] = True
        with self.assertRaises(ValidationError):
            validator.validate(original)


if __name__ == "__main__":
    unittest.main()
