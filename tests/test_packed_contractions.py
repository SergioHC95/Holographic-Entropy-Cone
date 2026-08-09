import hashlib
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
import zstandard as zstd

from hec.contractions import (
    _image_table,
    minimal_contraction,
    packed_contraction_tail_paths,
    read_contractions,
    write_packed_contraction_tail,
)


class PackedContractionTests(unittest.TestCase):
    def test_full_packed_stream_reconstructs_minimal_records(self) -> None:
        facet = (1, 1, -1)
        source = {"lhs": [["A", 1], ["B", 1]], "rhs": [["AB", 1]], "images": ["0", "1", "1", "0"]}
        table = _image_table(source["images"], 2, 1)
        payload = np.packbits(np.asarray(table, dtype=np.uint8).reshape(-1), bitorder="little").tobytes()

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            contractions = root / "contractions.json"
            packed = root / "contractions.packbits.zst"
            facets = root / "facets.json"
            compressed = zstd.ZstdCompressor(level=3).compress(payload)
            packed.write_bytes(compressed)
            facets.write_text(json.dumps([list(facet)]) + "\n", encoding="utf-8")
            manifest = {
                "schema_version": 1,
                "kind": "packed-contractions",
                "n": 2,
                "record_count": 1,
                "order": "same-as-facets-json",
                "records": [[2, 1]],
                "raw_size": len(payload),
                "raw_sha256": hashlib.sha256(payload).hexdigest(),
                "compressed_size": len(compressed),
                "compressed_sha256": hashlib.sha256(compressed).hexdigest(),
            }
            contractions.write_text(json.dumps(manifest) + "\n", encoding="utf-8")

            records = read_contractions(contractions, n=2, facet_rows=[facet])
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0], minimal_contraction(facet, 2, source))
            self.assertEqual(list(records.iter_selected(0, 2)), [(0, minimal_contraction(facet, 2, source))])
            self.assertEqual(list(records.iter_selected(1, 2)), [])

    def test_packed_base_accepts_an_append_only_tail(self) -> None:
        facet = (1, 1, -1)
        source = {"lhs": [["A", 1], ["B", 1]], "rhs": [["AB", 1]], "images": ["0", "1", "1", "0"]}
        table = _image_table(source["images"], 2, 1)
        payload = np.packbits(np.asarray(table, dtype=np.uint8).reshape(-1), bitorder="little").tobytes()

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            contractions = root / "contractions.json"
            packed = root / "contractions.packbits.zst"
            facets = root / "facets.json"
            compressed = zstd.ZstdCompressor(level=3).compress(payload)
            packed.write_bytes(compressed)
            facets.write_text(json.dumps([list(facet), list(facet)]) + "\n", encoding="utf-8")
            manifest = {
                "schema_version": 1,
                "kind": "packed-contractions",
                "n": 2,
                "record_count": 1,
                "order": "same-as-facets-json",
                "records": [[2, 1]],
                "raw_size": len(payload),
                "raw_sha256": hashlib.sha256(payload).hexdigest(),
                "compressed_size": len(compressed),
                "compressed_sha256": hashlib.sha256(compressed).hexdigest(),
            }
            contractions.write_text(json.dumps(manifest) + "\n", encoding="utf-8")
            tail_data, tail_index = packed_contraction_tail_paths(contractions)
            index = write_packed_contraction_tail(
                tail_data,
                [source],
                n=2,
                facet_rows=[facet],
                facet_start=1,
                compression_level=3,
            )
            tail_index.write_text(json.dumps(index) + "\n", encoding="utf-8")

            records = read_contractions(contractions, n=2, facet_rows=[facet, facet])
            expected = minimal_contraction(facet, 2, source)
            self.assertEqual(len(records), 2)
            self.assertEqual(list(records), [expected, expected])
            self.assertEqual(list(records.iter_selected(0, 2)), [(0, expected)])
            self.assertEqual(list(records.iter_selected(1, 2)), [(1, expected)])


if __name__ == "__main__":
    unittest.main()
