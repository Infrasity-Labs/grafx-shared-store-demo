"""Hand-computed values for the retrieval metrics."""
import math
import unittest

from ticketgraph import metrics


class Metrics(unittest.TestCase):
    ranked = [10, 11, 12, 13, 14]
    relevant = {11, 13, 99}

    def test_precision_and_recall(self):
        self.assertAlmostEqual(metrics.precision_at_k(self.ranked, self.relevant, 5), 2 / 5)
        self.assertAlmostEqual(metrics.precision_at_k(self.ranked, self.relevant, 2), 1 / 2)
        self.assertAlmostEqual(metrics.recall_at_k(self.ranked, self.relevant, 5), 2 / 3)
        self.assertAlmostEqual(metrics.recall_at_k(self.ranked, self.relevant, 1), 0.0)

    def test_short_result_list_is_still_divided_by_k(self):
        self.assertAlmostEqual(metrics.precision_at_k([11], {11}, 5), 1 / 5)

    def test_recall_needs_relevant_items(self):
        with self.assertRaises(ValueError):
            metrics.recall_at_k([1], set(), 5)

    def test_recall_ceiling(self):
        self.assertEqual(metrics.recall_ceiling({1, 2}, 5), 1.0)
        self.assertAlmostEqual(metrics.recall_ceiling(set(range(40)), 10), 0.25)

    def test_reciprocal_rank(self):
        self.assertAlmostEqual(metrics.reciprocal_rank(self.ranked, self.relevant, 10), 1 / 2)
        self.assertEqual(metrics.reciprocal_rank(self.ranked, {99}, 10), 0.0)
        self.assertEqual(metrics.reciprocal_rank(self.ranked, {14}, 3), 0.0, "outside the cutoff")

    def test_ndcg_matches_a_hand_computation(self):
        dcg = 1 / math.log2(3) + 1 / math.log2(5)
        ideal = 1 / math.log2(2) + 1 / math.log2(3) + 1 / math.log2(4)
        self.assertAlmostEqual(metrics.ndcg_at_k(self.ranked, self.relevant, 5), dcg / ideal)

    def test_ndcg_is_one_for_a_perfect_ranking_and_zero_for_none(self):
        self.assertAlmostEqual(metrics.ndcg_at_k([1, 2, 3, 9], {1, 2, 3}, 10), 1.0)
        self.assertEqual(metrics.ndcg_at_k([7, 8], {1}, 10), 0.0)
        self.assertEqual(metrics.ndcg_at_k([], {1}, 10), 0.0)

    def test_score_query_and_mean(self):
        a = metrics.score_query([1, 2], {1}, ks=(2,))
        b = metrics.score_query([2, 1], {1}, ks=(2,))
        self.assertEqual(set(a), {"mrr", "precision@2", "recall@2", "ndcg@2"})
        m = metrics.mean_scores([a, b])
        self.assertAlmostEqual(m["mrr"], 0.75)
        self.assertAlmostEqual(m["precision@2"], 0.5)
        self.assertEqual(metrics.mean_scores([]), {})


if __name__ == "__main__":
    unittest.main()
