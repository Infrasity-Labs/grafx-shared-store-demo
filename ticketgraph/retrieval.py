"""The three retrieval strategies. Each one gets a query text and a query vector, nothing else.

    lexical        full-text search over ticket subject and body
    hybrid         lexical + stored vectors, rank fusion
    hybrid_graph   hybrid plus graph evidence from relationships between tickets

No strategy sees a product id, an article id, an incident id, a question intent or a label. Graph
seeds are the top lexical hits for the same query, which are known at query time.
tests/test_evaluation.py checks that this file names none of those fields.
"""
from dataclasses import dataclass

from okto_grafx import HybridSearchOptions

DEFAULT_CANDIDATE_K = 100


@dataclass(frozen=True)
class GraphEvidence:
    relations: tuple
    seed_count: int = 3
    direction: str = "both"
    hops: int = 2
    weight: float = 0.5


def _row(directory, hit, **extra):
    ticket_id, subject = directory[hit.record_id]
    return dict({"ticket_id": ticket_id, "subject": subject, "score": round(hit.score, 6)}, **extra)


def lexical(db, directory, text, k):
    with db.begin("read") as reader:
        found = db.search_text(reader, index="ticket_text", query=text, k=k)
    return {"regime": found.regime, "seeds": [], "hits": [_row(directory, h) for h in found.hits]}


def lexical_record_ids(db, text, k):
    with db.begin("read") as reader:
        found = db.search_text(reader, index="ticket_text", query=text, k=k)
    return [h.record_id for h in found.hits]


def hybrid(db, directory, text, vector, k, graph=None, candidate_k=DEFAULT_CANDIDATE_K, exclude=()):
    """Hybrid search. With graph, the seeds are the top lexical hits of the same text.

    exclude: ticket ids that may not be a seed (the workflow excludes the ticket it is triaging, which
    is in the index). The evaluation excludes nothing.
    """
    options = {"candidate_k": candidate_k}
    seeds = []
    if graph is not None:
        excluded = set(exclude)
        skip = {rid for rid, (tid, _) in directory.items() if tid in excluded}
        found_ids = lexical_record_ids(db, text, graph.seed_count + len(skip))
        seeds = [r for r in found_ids if r not in skip][:graph.seed_count]
        if seeds:
            options.update(graph_relations=tuple(graph.relations), graph_seeds=tuple(seeds),
                           graph_direction=graph.direction, graph_hops=graph.hops, graph_weight=graph.weight)
    with db.begin("read") as reader:
        found = db.search_hybrid(reader, table="Ticket", index="ticket_text", query=text, space="minilm",
                                 vector=tuple(vector), k=k, options=HybridSearchOptions(**options))
    return {
        "regime": found.regime,
        "seeds": [directory[r][0] for r in seeds],
        "graph_used": bool(seeds),
        "hits": [_row(directory, h, lexical_rank=h.lexical_rank, vector_rank=h.vector_rank,
                      graph_distance=h.graph_distance) for h in found.hits],
    }
