# Exact graph-entropy facet rank witnesses

A globally valid nonzero inequality in the 63-dimensional six-party entropy
space defines a facet when its tight graph entropies span dimension 62.
Graph entropies outside the example ray catalogue can establish this dimension.
Their graph models are stored separately from the paired ray/graph catalogue.

`data/n=6/facet-witnesses.json` binds each supplied basis to the exact inequality
identity. Each of its 62 rows references either a stored ray, identified by its
ordinal and coefficient digest, or a graph model in a compressed witness shard.
Every reference includes a checked S7 permutation. The reader derives each
vector, checks its exact integer dot product with the inequality is zero, and
requires rank 62 modulo the fixed prime 2147483647. Modular independence implies
independence over the rationals. Missing, repeated or dependent directions
cannot complete a basis.

Each graph model records nonnegative integer edge capacities and one signed
feasible flow with a matching cut for every nonempty physical subsystem. Vertex
IDs 0 through 5 are A through F, and ID 6 is the purifier. For every coordinate,
the verifier checks all edge capacity bounds, conservation at every bulk vertex,
the terminal assignment of the cut, and equality of the flow value and cut
capacity. Flow conservation and capacity bounds give a lower bound on every
admissible cut; the supplied cut attains that bound. Thus all 63 entropies are
proved exactly. Positive common scaling yields the primitive entropy vector.

The closed formats and resource bounds are enforced by `hec.facet_witnesses`.
Model definitions and compressed shard frames are bound by SHA256, byte sizes
and disjoint complete offsets. Storage inventory and ordinary Git history checks
cover all witness bytes. CI's facet partitions materialize the declared witness
shards and execute the mathematical checks. Discovery and database bindings
inspect metadata only.

These certificates establish support rank. Every stored facet still requires
its current-standard contraction proof to pass the independent exhaustive
original-cube audit. The required gate retains every contraction, facet, ray,
graph, storage and binding partition.
