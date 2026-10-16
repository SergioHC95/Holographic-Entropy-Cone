# The supported repository pipeline

One proof language, one exact verifier and one ordinary-Git data inventory.
There are no old-format readers, pointer resolvers, hydration commands,
proof-transfer caches or alternate mathematical-acceptance paths.

## Setup

The tested CI runtime is Python 3.13.14 with the committed `uv.lock`.
Exact native verification requires GCC/Clang-compatible C++17 and unsigned
128-bit integers. Linux and macOS are covered by CI.

```bash
git clone https://github.com/SergioHC95/Holographic-Entropy-Cone.git
cd Holographic-Entropy-Cone
uv sync --locked --dev --python 3.13.14
uv run hec native build --directory .hec-native
export HEC_NATIVE_DIR="$PWD/.hec-native"
export HEC_RECONSTRUCTION_WORKING_BYTES=268435456
uv run hec storage audit
HEC_CHECK_WORKERS=2 uv run hec check database --root data
```

A clone of the replacement main contains every required payload as an actual
Git blob. Git LFS is neither installed nor invoked. The native buffer setting
bounds primary output buffers, not total RSS. Data is not embedded in the
Python wheel: run from a repository root, set `HEC_DATA_ROOT`, or provide the
data root explicitly.

## Immutable storage and provenance

All proof shards, indexes, graph/facet/ray data and current provenance are
ordinary Git files. `data/storage.json`, format `hec-repository-storage/2`,
binds every required path, byte length and SHA256. Every file must fit the
100-MiB ordinary-Git file limit. Binary attributes disable text conversion
and textual diffs, not Git storage.

Current receipts live under `provenance/contractions/`. Historical recovery
artifacts live outside the active repository. The archived originals are not
alternate accepted inputs, dependencies of CI or part of normal clone storage.
New authoring provenance is required ordinary-Git payload, bound to the exact
proof identity, party frame, primitive source normal and recorded audit scope.
Storage checks validate those bindings and complete declared identity coverage,
but never accept stored `ok` flags as mathematical evidence. All maps still
undergo the same independent complete-cube CI checks.

```bash
uv run hec storage plan                 # metadata only; NOT byte or math acceptance
uv run hec storage audit                # every required byte/hash; NOT math acceptance
uv run hec storage history              # complete HEAD ancestry: reject pointers/retired filters/large blobs
uv run hec storage history --all-refs   # additionally audit every local ref
uv run hec storage snapshot --replace  # intentional data update; records bytes, NOT validity
```

The old storage inventory and transfer/cache commands are rejected. No missing
file triggers a download fallback. Independent full-map verification remains
required even when all byte hashes match.

## Authoring

`find_contraction` returns `result['proof']` only after exhaustive independent
full-cube verification. Solver arrays are ephemeral, not persisted legacy
`images` tables. `proof_from_seed_rows` deterministically chooses a compact
table/DAG; named closure rules and logical cuts share the same fixed extension.

`hec.proof_store.write_proof_dataset(new_directory, proofs)` streams exact
audits and atomically publishes both proof and inequality indexes. It captures
metadata from owned snapshots, without decompressing saved maps again merely
to construct their inequality index. Existing datasets are not replaced.

For exact compact-domain candidate construction, see
[Compatible seed authoring](compatible-seed-authoring.md). This saved example
searches only the complete compatible seed, uses the existing fixed extension,
and requires the same full original-cube audit before publication. It does not
introduce another proof format or silently replace the public search API.

## Required CI and sparse checkouts

The gate requires all of: Linux/macOS code tests, a wheel built from the source
distribution and tested outside the checkout, full storage/ancestry hygiene,
complete mathematical proof partitions, global inequality bindings, and
facet/ray rank and graph-realization checks.

Metadata/code jobs use sparse partial Git checkouts. The matrix reincludes only
each contraction partition's owned immutable shards. One storage job checks all
required payloads and the checked-out commit's complete ancestry. There is no
binary-payload cache to restore, populate, download, bill or clean. Ordinary
dependency caches remain separate. Missing objects fail, never bypass checks.

Whole-shard ownership is deterministic and balanced by exact cube-edge counts.
Every proof belongs to exactly one full-corpus mathematical partition. Byte and
history integrity confer no mathematical validity, facethood or rank claim.
The proof representation, exact evaluator and saved maps did not change during
the switch to ordinary Git.

## Coordinated adoption

The replacement main is prepared and verified in an independent repository,
with old data/configuration removed throughout its ancestry and meaningful code
authorship retained. Do not publish the old staging branch: its ancestors still
contain retired pointers and artifacts. Review the cutover handoff, coordinate
with collaborators, and use a lease pinned to the reviewed remote main tip.
Old branches and open PRs must be rebased/recreated rather than merged with
their old ancestry. No force-push is authorized by preparation alone.

Old GitHub Actions proof caches can be retired independently when no live run
depends on them. Remote LFS objects require separate owner/GitHub Support
cleanup after adoption; a Git history rewrite does not itself release that
storage. Do not delete/recreate the live repository to perform this migration.
