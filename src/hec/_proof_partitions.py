"""One payload-ownership rule for storage installation and exact CI audits."""

from .count_proofs import decimal


def physical_groups(catalog, inequalities, groups):
    """Greedily balance actual cube-edge counts, never split an immutable shard."""
    if type(groups) is not int or not 1 <= groups <= len(catalog.shards):
        raise ValueError("invalid physical proof partition count")
    inequalities.check_bindings(catalog)
    weights = dict.fromkeys(catalog.shards, 0)
    for entry in catalog.entries:
        row = inequalities.entries[entry["inequality_id"]]
        axes = sum(decimal(value) > 0 for value in row["coefficients"])
        weights[entry["shard"]] += axes * (1 << (axes - 1)) if axes else 0
    result, costs = [set() for _ in range(groups)], [0] * groups
    for shard in sorted(weights, key=lambda key: (-weights[key], key)):
        target = min(range(groups), key=lambda index: (costs[index], len(result[index]), index))
        result[target].add(shard)
        costs[target] += weights[shard]
    if any(not owned for owned in result) or sum(map(len, result)) != len(catalog.shards):
        raise ValueError("incomplete physical proof ownership")
    return result


def partition_entries(catalog, inequalities, group, groups):
    if type(group) is not int or not 0 <= group < groups:
        raise ValueError("invalid physical proof partition index")
    owned = physical_groups(catalog, inequalities, groups)[group]
    return [index for index, entry in enumerate(catalog.entries) if entry["shard"] in owned]
