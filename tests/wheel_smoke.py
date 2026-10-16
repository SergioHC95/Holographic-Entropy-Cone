"""Actual installed-wheel acceptance, run outside the checkout by CI."""

import argparse
import importlib.util
import os
from pathlib import Path

import hec
from hec.checks import check_stored_facets, check_stored_rays
from hec.count_proofs import canonical_json, decimal, geometry
from hec.inequality_records import InequalityCatalog
from hec.native import build_backends, load_backends
from hec.proof_store import ProofCatalog


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--native-directory", type=Path, required=True)
    args = parser.parse_args()
    repository = args.repository.resolve()
    if Path(hec.__file__).resolve().is_relative_to(repository):
        raise ValueError("wheel acceptance must import the installed distribution, not the checkout")
    for obsolete in ("hec._archive_proof_store", "hec._count_verify", "hec._count_kernel", "hec._count_dag"):
        if importlib.util.find_spec(obsolete) is not None:
            raise ValueError("obsolete proof implementation shipped in the wheel")
    build_backends(args.native_directory)
    load_backends(args.native_directory)
    os.environ["HEC_NATIVE_DIR"] = str(args.native_directory)
    os.environ["HEC_RECONSTRUCTION_WORKING_BYTES"] = "268435456"
    proofs, edges = 0, 0
    for n in range(1, 6):
        directory = repository / f"data/n={n}"
        catalog, inequalities = (
            ProofCatalog(directory / "proofs.json"),
            InequalityCatalog(directory / "inequalities.json"),
        )
        inequalities.check_bindings(catalog)
        expected_edges = sum(
            p.L * (p.vertices // 2)
            for entry in inequalities.entries.values()
            for p in [geometry(entry["n"], tuple(map(decimal, entry["coefficients"])))]
        )
        result = catalog.verify()
        if result["proofs"] != len(catalog) or result["checked_edges"] != expected_edges:
            raise ValueError("installed-wheel full-map coverage differs from its exact indexes")
        proofs += result["proofs"]
        edges += result["checked_edges"]
        # Exercise the installed exact rank implementation in both directions,
        # not just the source checkout's rank jobs.
        list(check_stored_facets(repository / "data", n=n))
        list(check_stored_rays(repository / "data", n=n))
    search = hec.find_contraction((1, 1, -1), 2)
    if search["status"] != "proved" or search["audit"]["checked_edges"] != 4 or "images" in search:
        raise ValueError("installed-wheel search did not return an audited standard proof")
    print(
        canonical_json(
            {
                "installed_wheel": True,
                "proofs": proofs,
                "checked_edges": edges,
                "scope": "original-cube-all-edges",
                "source_tables_read": False,
            }
        ).decode()
    )


if __name__ == "__main__":
    main()
