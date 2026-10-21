"""Integrity checks for the non-catalogue external fixed-10 research record."""

from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
DIRECTORY = ROOT / "research" / "external-46d-fixed10"


class ExternalFixedTenRecordTests(unittest.TestCase):
    def test_manifest_binds_every_replayed_record(self):
        manifest = json.loads((DIRECTORY / "manifest.json").read_text())
        payload = DIRECTORY / manifest["payload"]["path"]
        self.assertEqual(
            hashlib.sha256(payload.read_bytes()).hexdigest(),
            manifest["payload"]["sha256"],
        )
        self.assertEqual(payload.stat().st_size, manifest["payload"]["bytes"])
        audit = DIRECTORY / manifest["audit_report"]["path"]
        self.assertEqual(
            hashlib.sha256(audit.read_bytes()).hexdigest(),
            manifest["audit_report"]["sha256"],
        )
        records = [json.loads(line) for line in payload.read_text().splitlines()]
        self.assertEqual(len(records), manifest["positive_replay"]["records"])
        self.assertEqual(len(records), manifest["screen"]["completed_counts"]["realized_at_most_10_vertices"])
        self.assertEqual(len({record["candidate_sha256"] for record in records}), len(records))
        self.assertTrue(all(len(record["ray"]) == 63 for record in records))
        self.assertTrue(all(record["independent_membership"]["enumerated_cuts"] == 504 for record in records))
        self.assertTrue(
            all(record["fixed10_native_evidence"]["fixed_native_total_vertices"] == 10 for record in records)
        )
        self.assertEqual(
            manifest["not_a_claim"],
            [
                "accepted repository ray",
                "global HEC extremality proof",
                "minimal-vertex realization",
                "global non-realizability result for completed fixed-10 UNSAT cases",
            ],
        )


if __name__ == "__main__":
    unittest.main()
