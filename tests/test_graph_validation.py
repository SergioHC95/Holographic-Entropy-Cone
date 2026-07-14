from __future__ import annotations

import math
import random
import unittest
from fractions import Fraction
from itertools import combinations

from hec._graph_validation import (
    canonical_primitive_ray_graph,
    exact_entropy_vector_mincut,
    graph_total_vertices,
    lift_graph_total_vertices,
    prune_entropy_irrelevant_components,
)
from hec.coordinates import party_index, party_labels, subsets


def brute_force_entropy(graph: dict, n: int) -> tuple[Fraction, ...]:
    """Independent cut-enumeration oracle for small test graphs."""

    terminals = party_labels(n)
    physical = terminals[:-1]
    vertices = set(terminals)
    weighted_edges: list[tuple[str, str, Fraction]] = []
    for edge, weight in zip(graph["edges"], graph["weights"], strict=True):
        left, right = edge
        vertices.update((left, right))
        weighted_edges.append((left, right, Fraction(weight)))
    bulk = sorted(vertices - set(terminals))

    result: list[Fraction] = []
    for subsystem in subsets(n):
        required = {physical[index] for index in subsystem}
        capacities: list[Fraction] = []
        for mask in range(1 << len(bulk)):
            side = required | {vertex for index, vertex in enumerate(bulk) if (mask >> index) & 1}
            capacities.append(
                sum(
                    (weight for left, right, weight in weighted_edges if (left in side) != (right in side)),
                    start=Fraction(0),
                )
            )
        result.append(min(capacities))
    return tuple(result)


class ExactGraphValidationTests(unittest.TestCase):
    def test_exact_mincut_matches_independent_random_cut_enumeration(self) -> None:
        rng = random.Random(1729)
        for n in range(1, 4):
            terminals = party_labels(n)
            for sample in range(30):
                vertices = [*terminals, *(f"x{index}" for index in range(1, 1 + rng.randrange(3)))]
                edges: list[list[str]] = []
                weights: list[Fraction] = []
                for left, right in combinations(vertices, 2):
                    if rng.randrange(3) == 0:
                        continue
                    edges.append([left, right])
                    weights.append(Fraction(rng.randrange(1, 6), rng.randrange(1, 5)))
                graph = {"edges": edges, "weights": weights}
                with self.subTest(n=n, sample=sample):
                    self.assertEqual(exact_entropy_vector_mincut(graph, n), brute_force_entropy(graph, n))

    def test_party_labels_reserve_the_purifier_for_arbitrary_counts(self) -> None:
        for n in (14, 15, 25, 26, 64):
            with self.subTest(n=n):
                labels = party_labels(n)
                self.assertEqual(labels[:14], list("ABCDEFGHIJKLMN"))
                self.assertEqual(labels[-1], "O")
                self.assertEqual(len(labels), len(set(labels)))
                self.assertEqual([party_index(label, n) for label in labels[:-1]], list(range(n)))

    def test_ray_canonicalization_merges_and_primitivizes_exact_weights(self) -> None:
        graph = {
            "edges": [["x1", "A"], ["A", "x1"], ["O", "x1"]],
            "weights": ["2/3", "4/3", 4],
        }
        self.assertEqual(
            canonical_primitive_ray_graph(graph),
            {"edges": [["A", "x1"], ["x1", "O"]], "weights": [1, 2]},
        )

    def test_exact_rational_star_entropy(self) -> None:
        graph = {
            "edges": [["A", "x1"], ["B", "x1"], ["O", "x1"]],
            "weights": [Fraction(3, 2), "5/2", "7/3"],
        }

        self.assertEqual(
            exact_entropy_vector_mincut(graph, 2),
            (Fraction(3, 2), Fraction(5, 2), Fraction(7, 3)),
        )

    def test_parallel_edges_are_merged_and_zero_edges_are_ignored(self) -> None:
        graph = {
            "edges": [["x1", "A"], ["A", "x1"], ["x1", "x2"], ["O", "x3"]],
            "weights": [Fraction(1, 3), Fraction(2, 3), 0, 4],
        }

        self.assertEqual(graph_total_vertices(graph, 1), 4)
        lifted, _metadata = lift_graph_total_vertices(graph, 1, 4)
        self.assertEqual(lifted["edges"], [["A", "x1"], ["x3", "O"]])
        self.assertEqual(lifted["weights"], [1, 4])

    def test_pruning_removes_only_components_without_physical_terminals(self) -> None:
        graph = {
            "edges": [["A", "x1"], ["B", "x2"], ["O", "x3"], ["x4", "x5"]],
            "weights": [2, 3, "5/2", 7],
        }
        before = exact_entropy_vector_mincut(graph, 2)

        pruned, metadata = prune_entropy_irrelevant_components(graph, 2)

        self.assertEqual(pruned, {"edges": [["A", "x1"], ["B", "x2"]], "weights": [2, 3]})
        self.assertEqual(exact_entropy_vector_mincut(pruned, 2), before)
        self.assertEqual(metadata["removed_edges"], [["x3", "O"], ["x4", "x5"]])
        self.assertEqual(metadata["removed_weights"], ["5/2", 7])
        self.assertEqual(metadata["removed_bulk_vertices"], ["x3", "x4", "x5"])
        self.assertEqual(metadata["preprune_total_vertices"], 8)
        self.assertEqual(metadata["postprune_total_vertices"], 5)

    def test_subdivision_lift_is_exact_deterministic_and_canonical(self) -> None:
        graph = {
            "edges": [["x2", "A"], ["x2", "B"], ["O", "x2"], ["O", "A"]],
            "weights": [Fraction(3, 2), Fraction(5, 2), Fraction(7, 3), 4],
        }
        before = exact_entropy_vector_mincut(graph, 2)

        first, first_metadata = lift_graph_total_vertices(graph, 2, 6)
        second, second_metadata = lift_graph_total_vertices(graph, 2, 6)

        self.assertEqual(first, second)
        self.assertEqual(first_metadata, second_metadata)
        self.assertEqual(graph_total_vertices(first, 2), 6)
        self.assertEqual(exact_entropy_vector_mincut(first, 2), before)
        self.assertEqual([step["new_vertex"] for step in first_metadata["lift_steps"]], ["x1", "x3"])
        self.assertEqual(first_metadata["canonical_bulk_label_pool"], ["x1", "x2", "x3"])
        self.assertIsNone(first_metadata["zero_ray_seed"])

    def test_zero_graph_uses_purifier_seed_then_subdivision(self) -> None:
        lifted, metadata = lift_graph_total_vertices({"edges": [], "weights": []}, 1, 6)

        self.assertEqual(graph_total_vertices(lifted, 1), 6)
        self.assertEqual(exact_entropy_vector_mincut(lifted, 1), (Fraction(0),))
        self.assertEqual(metadata["zero_ray_seed"]["edge"], ["x1", "O"])
        self.assertEqual([step["new_vertex"] for step in metadata["lift_steps"]], ["x2", "x3", "x4"])

    def test_exact_mincut_has_no_machine_word_vertex_limit(self) -> None:
        vertices = ["A", *(f"x{index}" for index in range(1, 65)), "O"]
        graph = {
            "edges": [[left, right] for left, right in zip(vertices[:-1], vertices[1:], strict=True)],
            "weights": [1] * (len(vertices) - 1),
        }

        self.assertEqual(exact_entropy_vector_mincut(graph, 1), (Fraction(1),))

    def test_invalid_graphs_fail_closed(self) -> None:
        invalid = (
            ({"edges": [["A", "A"]], "weights": [1]}, "self-loop"),
            ({"edges": [["A", "O"]], "weights": [-1]}, "non-negative"),
            ({"edges": [["A", "O"]], "weights": [math.inf]}, "finite"),
            ({"edges": [["A", "O"]], "weights": [True]}, "boolean"),
            ({"edges": [["A", "O"]], "weights": []}, "mismatch"),
            ({"edges": [["bogus", "also-bogus"]], "weights": [0]}, "invalid graph vertex"),
            ({"edges": [["A", "Z"]], "weights": [0]}, "not a terminal"),
        )
        for graph, message in invalid:
            with self.subTest(message=message), self.assertRaisesRegex((TypeError, ValueError), message):
                exact_entropy_vector_mincut(graph, 1)

    def test_lift_rejects_lowering_and_invalid_counts(self) -> None:
        graph = {"edges": [["A", "x1"]], "weights": [1]}
        with self.assertRaisesRegex(ValueError, "cannot lift"):
            lift_graph_total_vertices(graph, 1, 2)
        with self.assertRaisesRegex(ValueError, "at least 2"):
            lift_graph_total_vertices({"edges": [], "weights": []}, 1, 1)
        with self.assertRaisesRegex(ValueError, "positive integer"):
            graph_total_vertices(graph, 0)


if __name__ == "__main__":
    unittest.main()
