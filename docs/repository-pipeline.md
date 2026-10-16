# Repository pipeline

One self-contained proof language, one exact verifier and one ordinary-Git
data inventory. No migration ledger, stored audit flag or historical report
is needed to reconstruct or verify a map.

## Setup

CI uses Python 3.13.14 and the committed `uv.lock`. Exact native verification
requires GCC/Clang-compatible C++17 and unsigned 128-bit integers.
Linux and macOS are covered by CI.

```bash
uv sync --locked --dev --python 3.13.14
uv run hec native build --directory .hec-native
export HEC_NATIVE_DIR="$PWD/.hec-native"
export HEC_RECONSTRUCTION_WORKING_BYTES=268435456
uv run hec storage audit
HEC_CHECK_WORKERS=2 uv run hec check database --root data
```

The buffer setting bounds native output buffers, not total RSS. Data is not
embedded in the Python wheel: run from the repository root, set `HEC_DATA_ROOT`
or provide a data root explicitly.

## Data and storage

`data/n=*/` contains facets, rays, graphs, inequality/proof indexes and
immutable proof shards. `data/storage.json` binds every current path, byte
length and SHA256. Every required payload is an ordinary Git blob below
100 MiB; no LFS installation, hydration service or download fallback exists.
Research candidates, run logs and historical receipts belong outside this tree.

```bash
uv run hec storage plan                 # metadata only, not byte/math acceptance
uv run hec storage audit                # current bytes/hashes, not math acceptance
uv run hec storage history              # reject pointers/filters/oversize blobs in HEAD ancestry
uv run hec storage history --all-refs   # additionally audit all local refs
uv run hec storage snapshot --replace  # intentional byte-inventory update, not validity
```

## Authoring

`find_contraction` returns a standard proof only after independent exhaustive
full-cube verification. Solver arrays are transient. All seed primitives use
the same fixed extension; see the [proof standard](contraction-proof-standard.md)
and [compact-domain authoring example](compatible-seed-authoring.md).

`hec.proof_store.write_proof_dataset(new_directory, proofs)` verifies every
complete map and atomically publishes proof/inequality indexes. It never
overwrites an existing dataset or accepts incomplete attempts.

## Required CI

The final gate requires Linux/macOS tests, an installed wheel built from the
source distribution, complete byte/ancestry integrity, every mathematical
proof partition, global inequality bindings, facet/ray ranks and graph checks.
CI derives proof and edge counts from the current indexes, not dated reports.

Each complete map belongs to exactly one full-map partition. Scheduling uses
64 cost-balanced n=6 partitions and up to four independent worker processes per job, rather
than limiting parallel work to the number of storage files. A shard can feed
multiple disjoint jobs; storage-local grouping limits repeated downloads.
Sparse checkouts include only the files needed by that job; a separate job
verifies all current data bytes. Every partition executes original-cube bounds,
occurrence images and weighted edges at the same immutable commit.
Metadata hashes and saved receipts never confer mathematical validity.
