"""Retrieval metrics with binary relevance. Pure functions, no Grafx.

ranked is a list of ids, best first. relevant is a set of ids that count as relevant.
"""
import math


def precision_at_k(ranked, relevant, k):
    """Share of the first k results that are relevant. A result list shorter than k is still divided by k."""
    return sum(1 for r in ranked[:k] if r in relevant) / k


def recall_at_k(ranked, relevant, k):
    """Share of all relevant items found in the first k results."""
    if not relevant:
        raise ValueError("a question without relevant items has no recall")
    return sum(1 for r in ranked[:k] if r in relevant) / len(relevant)


def recall_ceiling(relevant, k):
    """The best recall@k any ranking can reach: k results cannot find more than k items."""
    return min(1.0, k / len(relevant))


def reciprocal_rank(ranked, relevant, k):
    """1 / rank of the first relevant result within the first k, else 0."""
    for position, r in enumerate(ranked[:k], start=1):
        if r in relevant:
            return 1.0 / position
    return 0.0


def ndcg_at_k(ranked, relevant, k):
    """Normalised discounted cumulative gain with gain 1 for a relevant result: sum 1/log2(rank+1)."""
    dcg = sum(1.0 / math.log2(position + 1) for position, r in enumerate(ranked[:k], start=1) if r in relevant)
    ideal = sum(1.0 / math.log2(position + 1) for position in range(1, min(k, len(relevant)) + 1))
    return dcg / ideal if ideal else 0.0


def score_query(ranked, relevant, ks=(5, 10, 20), rr_cutoff=10):
    """Every metric for one question."""
    out = {"mrr": reciprocal_rank(ranked, relevant, rr_cutoff)}
    for k in ks:
        out[f"precision@{k}"] = precision_at_k(ranked, relevant, k)
        out[f"recall@{k}"] = recall_at_k(ranked, relevant, k)
        out[f"ndcg@{k}"] = ndcg_at_k(ranked, relevant, k)
    return out


def mean_scores(rows):
    """Mean of each metric over a list of score_query dicts."""
    if not rows:
        return {}
    return {key: sum(r[key] for r in rows) / len(rows) for key in rows[0]}
