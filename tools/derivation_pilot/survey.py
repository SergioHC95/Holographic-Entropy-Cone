"""Survey corpus dimensions and select exact-identity structural controls."""

import argparse
import json
from collections import Counter
from pathlib import Path

from hec._archive_proof_store import ArchiveProofCatalog as ProofCatalog
from hec.count_proofs import geometry, inequality_id


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("choose a new survey output")
    rows = json.loads((args.data_root / "n=6/facets.json").read_bytes())
    catalog = ProofCatalog(args.data_root / "n=6/proofs.json")
    by_id = {entry["inequality_id"]: index for index, entry in enumerate(catalog.entries)}
    histograms = {key: Counter() for key in ("L", "G", "max_alpha", "max_beta")}
    examples = {key: {} for key in histograms}
    for row in rows:
        positive = [value for value in row if value > 0]
        negative = [-value for value in row if value < 0]
        fields = {
            "L": len(positive),
            "G": len(negative),
            "max_alpha": max(positive, default=0),
            "max_beta": max(negative, default=0),
        }
        for key, value in fields.items():
            histograms[key][value] += 1
            examples[key].setdefault(value, row)
    selected = set()
    for records in examples.values():
        for row in records.values():
            selected.add(by_id[inequality_id(geometry(6, tuple(row)))])
    report = {
        "population": len(rows),
        "histograms": {key: dict(sorted(values.items())) for key, values in histograms.items()},
        "coverage_indices": sorted(selected),
    }
    args.output.write_text(json.dumps(report, sort_keys=True, indent=2) + "\n")
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
