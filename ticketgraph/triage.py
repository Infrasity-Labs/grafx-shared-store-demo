"""Triage of a new ticket: search for similar tickets, correlate through the graph, decide.

The decision rule is small on purpose, so that the effect of the graph is easy to see.

    Escalate when the evidence shows at least ESCALATION_PRODUCTS different products affected.

Two pipelines apply the same rule to different evidence:

  text_and_vector_only   evidence = the products of the top HITS hybrid search results
  with_graph             evidence = the products of every ticket recorded in the same incident as the
                         results (Incident membership and SameIncident links), when at least
                         CORROBORATION results belong to one incident

Both pipelines see only the ticket's own text and vector. The ticket's product comes from the
customer's account, never from a label.
"""
from dataclasses import dataclass

from . import retrieval
from .evaluate import article_ranking

HITS = 5
CORROBORATION = 2
ESCALATION_PRODUCTS = 2


@dataclass(frozen=True)
class Evidence:
    pipeline: str
    hit_ids: tuple
    products: tuple           # (product id, name) pairs, sorted
    incident_id: object       # None unless the graph found a corroborated incident
    incident_name: object
    affected_ids: tuple       # every ticket the evidence was drawn from


def decide(evidence):
    """Pure function: the decision for one pipeline's evidence."""
    escalate = len(evidence.products) >= ESCALATION_PRODUCTS
    if evidence.incident_id is not None:
        action = "attach_to_incident"
    else:
        action = "routine"
    return {"action": action, "escalate": escalate, "incident_id": evidence.incident_id}


def similar_tickets(db, directory, ticket_id, subject, body, vector, graph=None):
    """The top HITS hybrid results for a ticket, without the ticket itself."""
    text = f"{subject} {body}"
    found = retrieval.hybrid(db, directory, text, vector, HITS + 1, graph=graph, exclude=(ticket_id,))
    hits = [h for h in found["hits"] if h["ticket_id"] != ticket_id][:HITS]
    return dict(found, hits=hits)


def products_of(db, ticket_ids):
    if not ticket_ids:
        return ()
    rows = db.execute("MATCH (t:Ticket)-[:About]->(p:Product) WHERE t.id IN $ids RETURN DISTINCT p.id, p.name",
                      {"ids": list(ticket_ids)}).rows
    return tuple(sorted((r[0], r[1]) for r in rows))


def baseline_evidence(db, hit_ids):
    return Evidence("text_and_vector_only", tuple(hit_ids), products_of(db, hit_ids), None, None, tuple(hit_ids))


def graph_evidence(db, hit_ids):
    """Follow Incident membership from the hits. Needs CORROBORATION hits in one incident."""
    rows = db.execute("MATCH (t:Ticket)-[:InIncident]->(i:Incident) WHERE t.id IN $ids RETURN i.id, i.name, t.id",
                      {"ids": list(hit_ids)}).rows if hit_ids else []
    support = {}
    for incident_id, name, _ticket in rows:
        entry = support.setdefault(incident_id, [name, 0])
        entry[1] += 1
    best = sorted(support.items(), key=lambda kv: (-kv[1][1], kv[0]))
    if not best or best[0][1][1] < CORROBORATION:
        return Evidence("with_graph", tuple(hit_ids), products_of(db, hit_ids), None, None, tuple(hit_ids))
    incident_id, (name, _count) = best[0]
    members = {r[0] for r in db.execute("MATCH (t:Ticket)-[:InIncident]->(i:Incident {id: $i}) RETURN t.id",
                                        {"i": incident_id}).rows}
    linked = {r[0] for r in db.execute(
        "MATCH (h:Ticket)-[:SameIncident]-(o:Ticket) WHERE h.id IN $ids RETURN DISTINCT o.id",
        {"ids": list(hit_ids)}).rows}
    affected = sorted(members | linked | set(hit_ids))
    return Evidence("with_graph", tuple(hit_ids), products_of(db, affected), incident_id, name, tuple(affected))


def suggest_articles(db, hit_ids, limit=2):
    rows = db.execute("MATCH (t:Ticket)-[:Mentions]->(a:Article) WHERE t.id IN $ids RETURN t.id, a.id",
                      {"ids": list(hit_ids)}).rows if hit_ids else []
    ranking = article_ranking(list(hit_ids), {t: a for t, a in rows})
    return ranking[:limit]
