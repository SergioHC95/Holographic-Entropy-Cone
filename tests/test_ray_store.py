"""Ray-shard storage is byte-checked metadata, not mathematical acceptance."""

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator, ValidationError

from hec.data import load_hec_data
from hec.ray_store import RAY_FORMAT, RAY_SHARD_BYTES, RayCatalog, read_rays, write_ray_catalog


class RayStoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.path = self.root / "rays.json"
        self.rays = [(index, index + 1, index + 2) for index in range(12)]

    def write(self):
        write_ray_catalog(self.path, self.rays, 2, shard_bytes=100)
        return json.loads(self.path.read_bytes())

    def test_deterministic_complete_alignment_and_one_shard_cache(self):
        before = self.write()
        other = self.root / "other" / "rays.json"
        write_ray_catalog(other, iter(self.rays), 2, shard_bytes=100)
        self.assertEqual(self.path.read_bytes(), other.read_bytes())
        catalog = RayCatalog(self.path, 2)
        self.assertGreater(len(catalog.shards), 1)
        self.assertEqual(len(catalog), len(self.rays))
        self.assertEqual(list(catalog), self.rays)
        self.assertEqual(catalog[::-2], self.rays[::-2])
        for index in range(len(catalog)):
            self.assertEqual(catalog[index], self.rays[index])
            self.assertLessEqual(len(catalog._cached_rows), max(shard.count for shard in catalog.shards))
        self.assertEqual(catalog[-1], self.rays[-1])
        for index in (len(catalog), -len(catalog) - 1):
            with self.assertRaises(IndexError):
                catalog[index]
        with self.assertRaises(TypeError):
            catalog[0.5]
        for shard in before["shards"]:
            payload = self.root / "ray-shards" / (shard["sha256"] + ".json")
            data = payload.read_bytes()
            self.assertEqual(len(data), shard["bytes"])
            self.assertLessEqual(len(data), 100)
            self.assertEqual(hashlib.sha256(data).hexdigest(), shard["sha256"])
            self.assertEqual(data, (other.parent / "ray-shards" / payload.name).read_bytes())

    def test_empty_inline_and_public_catalogue_reads_are_supported(self):
        write_ray_catalog(self.path, [], 2)
        self.assertEqual(list(RayCatalog(self.path, 2)), [])
        self.assertEqual(json.loads(self.path.read_bytes()), {"format": RAY_FORMAT, "count": 0, "shards": []})
        inline = self.root / "inline.json"
        inline.write_text("[[1,2,3]]")
        self.assertEqual(read_rays(inline, 2), [(1, 2, 3)])
        target = self.root / "data" / "n=2"
        target.mkdir(parents=True)
        write_ray_catalog(target / "rays.json", self.rays, 2, shard_bytes=100)
        self.assertEqual(list(load_hec_data(2, "rays", root=self.root / "data")), self.rays)

    def test_malformed_metadata_and_payloads_fail_closed(self):
        original = self.write()
        for key, value in (("format", RAY_FORMAT + "/1"), ("count", True), ("count", original["count"] + 1)):
            item = copy.deepcopy(original)
            item[key] = value
            self.path.write_text(json.dumps(item))
            with self.subTest(item=item), self.assertRaises(ValueError):
                RayCatalog(self.path, 2)
        for key, value in (
            ("count", True),
            ("count", 0),
            ("bytes", True),
            ("bytes", RAY_SHARD_BYTES + 1),
            ("sha256", "../escape"),
        ):
            item = copy.deepcopy(original)
            item["shards"][0][key] = value
            self.path.write_text(json.dumps(item))
            with self.subTest(item=item), self.assertRaises(ValueError):
                RayCatalog(self.path, 2)
        self.path.write_text("[[1,2.0,3]]")
        with self.assertRaises(ValueError):
            read_rays(self.path, 2)

    def test_missing_truncated_rehashed_and_immutable_payloads_are_rejected(self):
        original = self.write()
        pristine = copy.deepcopy(original)
        record = original["shards"][0]
        path = self.root / "ray-shards" / (record["sha256"] + ".json")
        saved = path.read_bytes()
        path.unlink()
        with self.assertRaises(FileNotFoundError):
            RayCatalog(self.path, 2)[0]
        path.write_bytes(saved[:-1])
        with self.assertRaisesRegex(ValueError, "identity mismatch"):
            RayCatalog(self.path, 2)[0]
        wrong = b"[[1,2,3]]\n"
        digest = hashlib.sha256(wrong).hexdigest()
        (path.parent / (digest + ".json")).write_bytes(wrong)
        original["shards"][0].update(sha256=digest, bytes=len(wrong))
        self.path.write_text(json.dumps(original))
        with self.assertRaisesRegex(ValueError, "row count"):
            RayCatalog(self.path, 2)[0]
        path.write_bytes(saved)
        self.path.write_text(json.dumps(pristine))
        payload = self.root / "ray-shards" / (pristine["shards"][0]["sha256"] + ".json")
        payload.write_bytes(b"broken")
        with self.assertRaisesRegex(ValueError, "immutable"):
            write_ray_catalog(self.path, self.rays, 2, shard_bytes=100)

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
