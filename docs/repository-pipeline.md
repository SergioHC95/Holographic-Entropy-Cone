# The supported repository pipeline

The repository has one proof language, one installed verifier, one storage
inventory and one required CI gate. There are no maintained old-format readers,
conversion commands, optional validity shortcuts or legacy fallbacks.

## Setup and verification

The CI runtime is pinned to Python 3.13.14 and the committed `uv.lock`.
The exact native primitives require a GCC/Clang-compatible C++17 compiler with
unsigned 128-bit integer support. Linux and macOS are covered by CI.

```bash
uv sync --locked --dev --python 3.13.14
uv run hec native build --directory .hec-native
export HEC_NATIVE_DIR="$PWD/.hec-native"
export HEC_RECONSTRUCTION_WORKING_BYTES=268435456
uv run hec storage audit
uv run hec check database --root data
```

`hec native build` builds the C++ sources shipped INSIDE the package, binds
their source and binary hashes, and publishes a release manifest last. A
different source, platform, corrupt binary or partial release fails closed.
The buffer setting bounds primary output buffers, not total process RSS.

Data is deliberately not bundled into the Python wheel. Run from a repository
root, set `HEC_DATA_ROOT` to its data directory, or pass `--root data` to checks.

## Storage

`data/storage.json` binds every active data path, size and SHA256, plus the
explicitly declared current conversion provenance and acceptance records.
Large n=6 proof shards and the conversion-provenance payload use Git LFS.
Tiny proof shards, indexes and graph/facet/ray records use ordinary Git.
Historical archives are recovery evidence, never accepted proof inputs.
The repository's `.lfsconfig` excludes the old recovery payloads from default
LFS downloads. Explicit, hash-scoped recovery is still possible; this is not
object deletion or quota reclamation.

```bash
uv run hec storage plan
uv run hec storage populate                       # offline; existing local LFS objects only
uv run hec storage populate --source-root /path/to/verified/repository-layout
uv run hec storage verify                         # verify every cached object's actual bytes
uv run hec storage install --n 6                  # verify then hydrate current proof shards
uv run hec storage audit --payloads               # also requires hydrated provenance bytes
```

The offline source root mirrors each declared repository-relative payload path.
It cannot supply unindexed objects or bypass length/hash checks. Populating the
transfer cache is not a Git LFS import or upload. `populate --fetch` explicitly
permits ONE filtered fetch of missing declared HEAD objects; no command fetches
historical revisions or uploads anything. Until the pending objects have been
published with authorization, a pointer-only checkout cannot pass full proof QA.

After an intentional data update, regenerate its inventory with
`hec storage snapshot --replace`. This records bytes, NOT proof validity.
CI independently performs every mathematical check again.

## Authoring

`find_contraction` returns a standard definition in `result['proof']` only
after independent full-cube acceptance. Its solver array is ephemeral; no
`images`/`lhs`/`rhs` serialization or packed-stream interface remains.
`proof_from_seed_rows` selects a deterministic exact table/DAG definition;
`closure_seed` constructs named closure rules and checks exact seed equality.
All four seed primitives feed the same fixed full-map extension.

Use `hec.proof_store.write_proof_dataset(new_directory, proofs)` to stream
audits and atomically publish both exact proof and inequality indexes. Metadata
is captured from owned proof snapshots; saved maps are not decoded a second
time merely to build their inequality index. Existing datasets are not replaced.
The search example uses this path.

## Required CI

The gate requires code/tests on Linux and macOS, a separately installed wheel
tested outside the checkout, the storage inventory and current provenance,
every exhaustive contraction partition, exact inequality bindings, and the
existing facet/ray rank and graph-realization checks.

One cache producer verifies the declared objects; consumers never fetch.
New cache generations reuse existing content-addressed objects and fetch only
missing hashes. Before saving, obsolete transfer-cache objects are moved
recoverably out of the shared cache; Git/LFS history and proof payloads are untouched.
Proof shards are assigned greedily by exact cube-edge counts. Storage installs
and audit jobs use the SAME ownership rule, with every proof assigned once.
The gate fails on missing data, failed/skipped required jobs, malformed replies,
coverage mismatches or mathematical errors. There is no sampling or receipt-only
acceptance, and no exemption for unchanged proof payloads.

## Recovery and reproducibility

The retired research/migration implementation and its historical tests remain
recoverable at Git commit `71f32d96032526edc93db43cecb358f3e955941a` and in a
separately hashed pre-modernization source snapshot. They are not installed or
run by the current pipeline. The previously verified corpus, source maps and
transformation receipts remain intact. This refactor does not reclaim LFS history
or quota, upload objects, publish a PR, or establish additional facethood claims.
