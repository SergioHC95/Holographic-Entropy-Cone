"""Reverify selected recipes in fresh processes, without a source-data option."""

import argparse
import json
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", type=Path, action="append", required=True)
    parser.add_argument("--closure", type=Path, required=True)
    parser.add_argument("--verifier", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("choose a new validation output; previous receipts are retained")
    items = []
    for path in args.results:
        report = json.loads(path.read_text())
        for case in report["cases"]:
            accepted = [
                (value["recipe_bytes"], name, value)
                for name, value in case["methods"].items()
                if value["status"] == "exact_full_cube_verified"
            ]
            _, name, best = min(accepted)
            items.append((case["n"], case["index"], name, path.parent / best["recipe"], best["recipe_id"]))

    def verify(item):
        n, index, name, path, identity = item
        command = [
            sys.executable,
            "-m",
            "derivation_pilot.verify_recipe",
            "--recipe",
            str(path),
            "--closure",
            str(args.closure),
            "--verifier",
            str(args.verifier),
        ]
        checked = subprocess.run(command, check=True, capture_output=True, text=True)
        result = json.loads(checked.stdout)
        if result.get("ok") is not True or result["recipe_id"] != identity or result["source_tables_read"] is not False:
            raise ValueError("fresh acceptance was incomplete or misbound")
        return {"n": n, "index": index, "method": name, **result}

    started = time.perf_counter()
    receipts = []
    with ThreadPoolExecutor(max_workers=2) as pool:
        for future in as_completed([pool.submit(verify, item) for item in items]):
            receipts.append(future.result())
            if len(receipts) % 32 == 0:
                print(json.dumps({"fresh_verified": len(receipts), "total": len(items)}), flush=True)
    output = {
        "proofs": len(receipts),
        "full_cube_edges": sum(item["checked_edges"] for item in receipts),
        "source_tables_read": False,
        "workers": 2,
        "elapsed_seconds": time.perf_counter() - started,
        "cases": sorted(receipts, key=lambda item: (item["n"], item["index"])),
    }
    args.output.write_text(json.dumps(output, sort_keys=True, indent=2) + "\n")
    print(json.dumps({key: value for key, value in output.items() if key != "cases"}), flush=True)


if __name__ == "__main__":
    main()
