# Incremental database integrity

The required `database integrity` check still covers the complete accepted
database. Expensive mathematical audits run only for new or edited results
and results whose mathematical inputs were removed or changed. Unchanged
results are reused only with authenticated evidence of earlier acceptance.

## Trusted baseline

Discovery fingerprints the complete validator implementation, packaged
resources, schemas, tests, dependency/build configuration and CI definition.
It authenticates a completed successful run of this repository's integrity
workflow and its successful required gate from the GitHub Actions app.
The gate records its tested commit, exact Git tree, verifier fingerprint and
plan digest as a closed, versioned check annotation. The GitHub commit API
must independently bind that commit to the exact baseline tree. A branch
name, repository file saying “accepted”, arbitrary status, cached flag or
successful unrelated workflow is insufficient.

A merged commit can reuse a tested parent with the same tree. Thus merging
an already-validated PR does not repeat its mathematical audits. Reuse of
the data tree does **not** imply that additional Git history is safe: all
commits and objects outside the accepted ancestor are audited separately.

Executors authenticate the same pinned baseline and recompute the discovery
plan. They require the exact plan digest and task identity. Changed tasks use
the existing full-cube, rank and graph validators; planned counts never
substitute for actual complete, unique, in-selection results.

## Change dependencies

| Change | Fresh mathematical work |
| --- | --- |
| New/edited proof definition or frame | Its complete original-cube audit. |
| New/edited facet | Its support rank; its current selected proof must also be accepted. |
| New/edited ray | Its rank and its paired graph's exact entropy check. |
| New/edited graph | Its exact graph/ray check, including the stored vertex bound. |
| Removed facet support orbit | Recheck existing ray ranks against the remaining facets. |
| Removed ray support orbit | Recheck existing facet ranks against the remaining rays. |
| Changed witness basis, referenced ray or model frame | Recheck the dependent facet certificates. |
| Pure repacking with identical decoded graph/ray rows | Check changed bytes/indexes; reuse the unchanged mathematical facts. |

The planner compares immutable shard identities first and decodes only changed
ray/graph shards. It preserves coordinate frames and pairing: reordering or
editing ray rows cannot silently reuse a different paired graph. Symmetry
orbit retention preserves rank-support monotonicity, while explicitly stored
witness row/frame bindings still require their own dependency checks.

Selected proof batches are balanced by estimated complete-map work, not just
row count. Scheduling weights never split a proof or change its full-cube
acceptance. Planned ownership must be complete, disjoint and within the
workflow matrix limit before any task can run.

Adding valid constraints cannot reduce an already-certified ray's support
rank. Adding realized rays cannot reduce an already-certified facet's support
rank. Every new proof and realization establishing those premises remains a
required task. Edits/removals do not receive that append-only shortcut.

## Global invariants and tests

Every run still executes portable tests on Ubuntu and macOS, builds and tests
the installed wheel, validates the complete current metadata/bindings, checks
README counts, verifies changed data bytes, and audits uncovered Git history.
Unchanged byte identities are bound both to Git objects and the prior SHA256
inventory; declarations alone are never new byte acceptance.

Append-only changes retain prior whole-catalogue regression inputs. Their
catalogue jobs explicitly report authenticated integration reuse and execute
fresh current bindings, ordering, primitive/symmetry checks and exact
baseline-plus-delta orbit/storage counts. They do not pretend to have rerun
the old exhaustive tests. Changes to existing regression inputs require the
original full catalogue integration suite on both platforms.

An explicit acceptance-plan task is always present, even when no mathematical
row changed. Metadata-only success does not certify a new proof or rank; the
final gate also requires every planned mathematical task, both quality jobs,
both catalogue jobs, distribution and storage to succeed.

## Full audit and rollout

A verifier/schema/test/dependency/CI change, an unverifiable or unavailable
baseline, a new/removed party-count dataset, or an explicit full request
requires a full mathematical audit. Malformed data fails closed. A transient
GitHub metadata read has bounded retries; it never turns into a successful
partial audit. A pinned baseline that becomes unavailable during selected
execution fails that execution rather than dropping its checks.

The first rollout therefore performs a full certification. Later data-only
changes use the accepted implementation. For example, three appended facets
and three proofs schedule those three ranks and three full-map audits,
normally in two mathematical jobs, plus the explicit reuse/coverage task;
they do not repeat every stored ray and graph audit.

The workflow's manual dispatch always requests a full audit. The existing
standalone `hec check`, `hec plan` and `hec storage history` commands keep their
complete-audit defaults. CI's authenticated planner is available as:

```sh
uv run python -m hec.ci_checks plan --mode full
```

No branch protections, mathematical data, proof payloads, exact kernels,
acceptance deadlines or running research campaigns are changed by this CI
policy.
