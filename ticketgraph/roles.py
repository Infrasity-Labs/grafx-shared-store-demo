"""The roles of the support workflow. Each runs as its own process with its own Grafx handle.

    python -m ticketgraph.roles intake   --store S --ticket-id 3001 --out FILE --events FILE
    python -m ticketgraph.roles triage   --store S --ticket-id 3001 ...
    python -m ticketgraph.roles maintain --store S --ticket-id 3001 [--crash-at before_commit|after_commit] ...
    python -m ticketgraph.roles audit    --store S --article-id 1 ...

Every write is one transaction that also writes a Checkpoint row (see appschema.py), so running a
role again after an interruption does nothing it has already done.
"""
import argparse
import json
import os
import sys

from okto_grafx import connect

from . import auditor, retrieval, triage
from .appschema import checkpoint_exists, write_checkpoint
from .common import FIXTURES, dump_json, load_eval_vectors, to_plain
from .resumable import CrashPoint, make_logger
from .retry import write_with_conflict_retry

JOB = "workflow"
INTAKE_SQL = ("CREATE (:Ticket {id: $id, subject: $subject, body: $body, priority: $priority, "
              "status: $status, embedding: $embedding})")


def incoming(ticket_id):
    for row in json.loads((FIXTURES / "incoming_tickets.json").read_text(encoding="utf-8")):
        if row["id"] == ticket_id:
            return row
    raise ValueError(f"no incoming ticket {ticket_id}")


def key(stage, *parts):
    return ":".join([JOB, "-".join([stage, *map(str, parts)])])


def ticket_row(db, ticket_id):
    row = db.execute("MATCH (t:Ticket {id: $id}) RETURN t.subject, t.body, t.priority, t.status, t.embedding",
                     {"id": ticket_id}).rows
    if not row:
        raise RuntimeError(f"ticket {ticket_id} is not in the store; intake has not run")
    subject, body, priority, status, embedding = row[0]
    return {"subject": subject, "body": body, "priority": priority, "status": status,
            "vector": [float(x) for x in embedding.values]}


# ----------------------------------------------------------------- intake
def intake(db, ticket_id, log):
    checkpoint = key("intake", ticket_id)
    if checkpoint_exists(db, checkpoint):
        log("skipped", stage="intake", ticket_id=ticket_id)
        return {"stage": "intake", "ticket_id": ticket_id, "skipped": True}
    ticket = incoming(ticket_id)
    vector = load_eval_vectors()["incoming"][str(ticket_id)]
    # The product is known from the customer's account (Uses), not from the ticket.
    product = db.execute("MATCH (c:Customer {id: $id})-[:Uses]->(p:Product) RETURN p.id, p.name",
                         {"id": ticket["customer_id"]}).rows[0]
    params = dict(ticket, embedding=vector)
    conflicts = []

    def operation(txn):
        txn.execute(INTAKE_SQL, params)
        txn.execute("MATCH (c:Customer {id: $customer_id}), (t:Ticket {id: $id}) CREATE (c)-[:Opened]->(t)", params)
        txn.execute("MATCH (t:Ticket {id: $id}), (p:Product {id: $product}) CREATE (t)-[:About]->(p)",
                    {"id": ticket_id, "product": product[0]})
        write_checkpoint(txn, checkpoint, JOB, f"intake-{ticket_id}", 1)

    report, n_conflicts = write_with_conflict_retry(db, operation, on_conflict=lambda n, e: conflicts.append(n))
    assert report.durable
    log("committed", stage="intake", ticket_id=ticket_id, csn=report.csn, conflicts=n_conflicts)
    return {"stage": "intake", "ticket_id": ticket_id, "skipped": False, "csn": report.csn,
            "conflicts": n_conflicts, "product_from_account": {"id": product[0], "name": product[1]},
            "customer_id": ticket["customer_id"]}


# ----------------------------------------------------------------- triage
def run_triage(db, ticket_id, log):
    from . import searcher

    checkpoint = key("triage", ticket_id)
    if checkpoint_exists(db, checkpoint):
        log("skipped", stage="triage", ticket_id=ticket_id)
        return {"stage": "triage", "ticket_id": ticket_id, "skipped": True}
    t = ticket_row(db, ticket_id)
    directory = searcher.ticket_directory(db)
    plain = triage.similar_tickets(db, directory, ticket_id, t["subject"], t["body"], t["vector"])
    boosted = triage.similar_tickets(db, directory, ticket_id, t["subject"], t["body"], t["vector"],
                                     graph=retrieval.GraphEvidence(relations=("SameIncident",)))
    plain_ids = [h["ticket_id"] for h in plain["hits"]]
    base = triage.baseline_evidence(db, plain_ids)
    graph = triage.graph_evidence(db, plain_ids)
    base_decision, decision = triage.decide(base), triage.decide(graph)
    articles = triage.suggest_articles(db, plain_ids)

    def operation(txn):
        txn.execute("CREATE (:Triage {id: $id, ticket_id: $id, decision: $decision, incident_id: $incident, "
                    "products: $products, rationale: $rationale})",
                    {"id": ticket_id, "decision": decision["action"] + (":escalate" if decision["escalate"] else ""),
                     "incident": decision["incident_id"] if decision["incident_id"] is not None else 0,
                     "products": ", ".join(name for _, name in graph.products),
                     "rationale": f"{len(graph.affected_ids)} tickets considered, products {len(graph.products)}"})
        txn.execute("MATCH (x:Triage {id: $id}), (t:Ticket {id: $id}) CREATE (x)-[:TriageOf]->(t)", {"id": ticket_id})
        for article in articles:
            txn.execute("MATCH (x:Triage {id: $id}), (a:Article {id: $a}) CREATE (x)-[:Suggests]->(a)",
                        {"id": ticket_id, "a": article})
        if decision["incident_id"] is not None:
            txn.execute("MATCH (x:Triage {id: $id}), (i:Incident {id: $i}) CREATE (x)-[:JoinsIncident]->(i)",
                        {"id": ticket_id, "i": decision["incident_id"]})
        if decision["escalate"]:
            txn.execute("MATCH (t:Ticket {id: $id}) SET t.priority = 'high', t.status = 'escalated'", {"id": ticket_id})
        write_checkpoint(txn, checkpoint, JOB, f"triage-{ticket_id}", 1)

    report, n_conflicts = write_with_conflict_retry(db, operation)
    assert report.durable
    log("committed", stage="triage", ticket_id=ticket_id, csn=report.csn, decision=decision["action"],
        escalate=decision["escalate"])
    return {
        "stage": "triage", "ticket_id": ticket_id, "skipped": False, "csn": report.csn, "conflicts": n_conflicts,
        "ticket": {"subject": t["subject"]},
        "similar_tickets_hybrid": [{"ticket_id": h["ticket_id"], "subject": h["subject"]} for h in plain["hits"]],
        "similar_tickets_hybrid_with_graph_boost": [{"ticket_id": h["ticket_id"], "subject": h["subject"],
                                                      "graph_distance": h["graph_distance"]} for h in boosted["hits"]],
        "graph_boost_seeds": boosted["seeds"],
        "text_and_vector_only": {"products": [n for _, n in base.products], "decision": base_decision},
        "with_graph": {"products": [n for _, n in graph.products], "incident": graph.incident_name,
                       "incident_id": graph.incident_id, "tickets_considered": len(graph.affected_ids),
                       "evidence_ticket_ids": list(graph.affected_ids),
                       "decision": decision},
        "graph_changed_decision": base_decision != decision,
        "suggested_articles": articles,
    }


# ----------------------------------------------------------------- maintainer
def enrichment_note(incident_name):
    return (f"If this problem shows up in several products at once, check whether the incident "
            f"\"{incident_name}\" is open before you reset accounts or ask the customer to reinstall.")


def maintain(db, ticket_id, crash, log):
    """Enrich the article that triage suggested, once. Only for tickets that joined an incident."""
    row = db.execute("MATCH (x:Triage {id: $id})-[:JoinsIncident]->(i:Incident) RETURN i.name", {"id": ticket_id}).rows
    if not row:
        log("nothing_to_do", stage="maintain", ticket_id=ticket_id)
        return {"stage": "maintain", "ticket_id": ticket_id, "skipped": True, "reason": "triage did not join an incident"}
    incident_name = row[0][0]
    suggested = sorted(r[0] for r in db.execute(
        "MATCH (x:Triage {id: $id})-[:Suggests]->(a:Article) RETURN a.id", {"id": ticket_id}).rows)
    article_id = suggested[0]
    checkpoint = key("maintain", article_id, ticket_id)
    if checkpoint_exists(db, checkpoint):
        log("skipped", stage="maintain", ticket_id=ticket_id, article_id=article_id)
        return {"stage": "maintain", "ticket_id": ticket_id, "article_id": article_id, "skipped": True}
    note = enrichment_note(incident_name)
    before_commit = auditor.latest_commit(db).sequence

    def operation(txn):
        body, revision = txn.execute("MATCH (a:Article {id: $id}) RETURN a.body, a.revision", {"id": article_id}).rows[0]
        txn.execute("MATCH (a:Article {id: $id}) SET a.body = $body, a.revision = $rev",
                    {"id": article_id, "body": f"{body} {note}", "rev": revision + 1})
        write_checkpoint(txn, checkpoint, JOB, f"maintain-{article_id}-{ticket_id}", 1)
        log("in_transaction", stage="maintain", article_id=article_id)
        crash.fire("before_commit", 0, log, unit=f"maintain-{article_id}")

    report, n_conflicts = write_with_conflict_retry(db, operation)
    assert report.durable
    log("committed", stage="maintain", article_id=article_id, csn=report.csn)
    crash.fire("after_commit", 0, log, unit=f"maintain-{article_id}")
    return {"stage": "maintain", "ticket_id": ticket_id, "article_id": article_id, "skipped": False,
            "csn": report.csn, "commit_before_csn": before_commit, "conflicts": n_conflicts, "note_added": note}


# ----------------------------------------------------------------- auditor
def audit(db, article_id, log):
    result = auditor.article_audit(db, article_id)
    result = dict({"stage": "audit"}, **result)
    log("audited", stage="audit", article_id=article_id, changed=result["changed"])
    return result


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("role", choices=["intake", "triage", "maintain", "audit"])
    ap.add_argument("--store", required=True)
    ap.add_argument("--ticket-id", type=int)
    ap.add_argument("--article-id", type=int)
    ap.add_argument("--crash-at", help="before_commit or after_commit (maintain only): SIGKILL this process")
    ap.add_argument("--events")
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    log = make_logger(args.events, args.role + (f"-{args.ticket_id}" if args.ticket_id else ""))
    crash = CrashPoint.parse(f"{args.crash_at}:0" if args.crash_at else None)
    with connect(args.store) as db:
        if args.role == "intake":
            result = intake(db, args.ticket_id, log)
        elif args.role == "triage":
            result = run_triage(db, args.ticket_id, log)
        elif args.role == "maintain":
            result = maintain(db, args.ticket_id, crash, log)
        else:
            result = audit(db, args.article_id, log)
    result["pid"] = os.getpid()
    dump_json(args.out, result)


if __name__ == "__main__":
    sys.exit(main())
