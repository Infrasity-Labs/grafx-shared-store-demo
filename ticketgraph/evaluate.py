"""Retrieval evaluation: lexical vs hybrid vs hybrid + graph, scored against labelled questions.

    python -m ticketgraph.evaluate --out eval-result.json [--workdir DIR]

It builds its own fresh store from the fixtures (the 500 core tickets, the stored vectors, the
recorded incident links), runs every strategy for every question in fixtures/eval_questions.json and
scores the ranked tickets against fixtures/eval_qrels.json. The labels are used only in this file,
after retrieval, to compute Precision@K, Recall@K, MRR and nDCG@K. How the labels were made is
written in scripts/make_fixtures.py.
"""
import argparse
import json
import shutil
import sys
import tempfile
import time
from pathlib import Path

from okto_grafx import connect

from . import metrics, retrieval, searcher
from .appschema import ensure_app_schema, ensure_ticket_text_index, load_incident_graph
from .common import (FIXTURES, dump_json, load_eval_qrels, load_eval_questions, load_eval_vectors,
                     load_vectors, read_jsonl)
from .importer import link_related, load_static, load_tickets
from .schema import create_store

KS = (5, 10, 20)
SEARCH_K = max(KS)
ARTICLE_KS = (3,)

INCIDENT_EDGES = retrieval.GraphEvidence(relations=("SameIncident",))
PRODUCT_EDGES = retrieval.GraphEvidence(relations=("Related",))
# The first three strategies are the comparison the review asks for. The product-edge strategy is an
# ablation: the same graph evidence over the original "same product" Related edges.
STRATEGIES = ("lexical", "hybrid", "hybrid_graph", "hybrid_graph_product_edges")
GRAPH_WEIGHT_SWEEP = (0.25, 0.5, 1.0, 2.0)  # reported as sensitivity only, never used to pick the default


def build_eval_store(path):
    """A fresh store that holds exactly the core fixtures and the recorded incident graph."""
    started = time.perf_counter()
    create_store(path)
    tickets = read_jsonl(FIXTURES / "tickets.jsonl")
    with connect(path) as db:
        ensure_app_schema(db)
        load_static(db)
        load_tickets(db, tickets, 50, load_vectors(), name="eval-load")
        product_links = link_related(db, tickets)
        graph = load_incident_graph(db)
        ensure_ticket_text_index(db)
        findings = db.verify("all").findings
    return {"seconds": round(time.perf_counter() - started, 3), "tickets": len(tickets),
            "product_related_edges": product_links["edges"], "incident_graph": graph,
            "verify_findings": len(findings)}


def run_strategy(db, directory, name, text, vector, graph_weight=None):
    if name == "lexical":
        return retrieval.lexical(db, directory, text, SEARCH_K)
    if name == "hybrid":
        return retrieval.hybrid(db, directory, text, vector, SEARCH_K)
    evidence = INCIDENT_EDGES if name == "hybrid_graph" else PRODUCT_EDGES
    if graph_weight is not None:
        evidence = retrieval.GraphEvidence(evidence.relations, evidence.seed_count, evidence.direction,
                                           evidence.hops, graph_weight)
    return retrieval.hybrid(db, directory, text, vector, SEARCH_K, graph=evidence)


def article_ranking(top_tickets, article_of):
    """Rank articles by the tickets above them: a ticket at rank r votes 1/r for the article it mentions."""
    votes = {}
    for rank, ticket in enumerate(top_tickets[:10], start=1):
        article = article_of.get(ticket)
        if article is not None:
            votes[article] = votes.get(article, 0.0) + 1.0 / rank
    return [a for a, _ in sorted(votes.items(), key=lambda kv: (-kv[1], kv[0]))]


def score_run(results_by_query, qrels, article_of, questions):
    """Per-question and mean metrics for one strategy's results."""
    per_query, art_rows = {}, {}
    for q in questions:
        ranked = [h["ticket_id"] for h in results_by_query[q["id"]]["hits"]]
        rel = set(qrels[q["id"]]["tickets"])
        row = metrics.score_query(ranked, rel, KS)
        row["recall_ceiling@10"] = metrics.recall_ceiling(rel, 10)
        per_query[q["id"]] = row
        art_rel = set(qrels[q["id"]]["articles"])
        art_rows[q["id"]] = metrics.score_query(article_ranking(ranked, article_of), art_rel, ARTICLE_KS, rr_cutoff=5)
    groups = {"all": [q["id"] for q in questions]}
    for intent in ("feature", "incident"):
        groups[intent] = [q["id"] for q in questions if q["intent"] == intent]
    summary = {g: {"questions": len(ids),
                   "tickets": metrics.mean_scores([per_query[i] for i in ids]),
                   "articles": metrics.mean_scores([art_rows[i] for i in ids])}
               for g, ids in groups.items()}
    return per_query, summary


def first_relevant_rank(ranked, rel):
    for position, r in enumerate(ranked, start=1):
        if r in rel:
            return position
    return None


def compare_graph(base, graph, qrels, questions, tickets_by_id, tol=1e-9):
    """Question by question: did graph evidence change nDCG@10 versus plain hybrid, and how."""
    rows = []
    for q in questions:
        rel = set(qrels[q["id"]]["tickets"])
        b = [h["ticket_id"] for h in base[q["id"]]["hits"]]
        g = [h["ticket_id"] for h in graph[q["id"]]["hits"]]
        nb, ng = metrics.ndcg_at_k(b, rel, 10), metrics.ndcg_at_k(g, rel, 10)
        entered = [t for t in g[:10] if t not in b[:10]]
        left = [t for t in b[:10] if t not in g[:10]]
        rows.append({
            "id": q["id"], "query": q["text"], "intent": q["intent"],
            "ndcg@10_hybrid": nb, "ndcg@10_graph": ng, "delta": ng - nb,
            "outcome": "improved" if ng - nb > tol else "worse" if nb - ng > tol else "unchanged",
            "first_relevant_rank_hybrid": first_relevant_rank(b, rel),
            "first_relevant_rank_graph": first_relevant_rank(g, rel),
            "seeds": [{"ticket_id": s, "subject": tickets_by_id[s]["subject"], "relevant": s in rel}
                      for s in graph[q["id"]]["seeds"]],
            "entered_top10": [{"ticket_id": t, "subject": tickets_by_id[t]["subject"], "relevant": t in rel}
                              for t in entered],
            "left_top10": [{"ticket_id": t, "subject": tickets_by_id[t]["subject"], "relevant": t in rel}
                           for t in left],
        })
    counts = {o: sum(1 for r in rows if r["outcome"] == o) for o in ("improved", "unchanged", "worse")}
    by_intent = {i: {o: sum(1 for r in rows if r["outcome"] == o and r["intent"] == i)
                     for o in ("improved", "unchanged", "worse")} for i in ("feature", "incident")}
    ordered = sorted(rows, key=lambda r: r["delta"])
    return {"counts": counts, "by_intent": by_intent, "per_query": rows,
            "largest_gains": [r for r in ordered[::-1][:3] if r["outcome"] == "improved"],
            "largest_losses": [r for r in ordered[:3] if r["outcome"] == "worse"]}


def evaluate(db):
    """Run every strategy on every question and score it. db must be a store from build_eval_store."""
    questions = load_eval_questions()
    qrels = load_eval_qrels()
    vectors = load_eval_vectors()["questions"]
    directory = searcher.ticket_directory(db)
    article_of = {r[0]: r[1] for r in db.execute("MATCH (t:Ticket)-[:Mentions]->(a:Article) RETURN t.id, a.id").rows}
    tickets_by_id = {t["id"]: t for t in read_jsonl(FIXTURES / "tickets.jsonl")}

    raw = {name: {q["id"]: run_strategy(db, directory, name, q["text"], vectors[q["id"]]) for q in questions}
           for name in STRATEGIES}
    out = {"strategies": {}, "per_query": {}}
    for name in STRATEGIES:
        per_query, summary = score_run(raw[name], qrels, article_of, questions)
        out["strategies"][name] = summary
        out["per_query"][name] = {
            q["id"]: dict(per_query[q["id"]], ranked_top10=[h["ticket_id"] for h in raw[name][q["id"]]["hits"][:10]])
            for q in questions}
    graph_no_seeds = [q["id"] for q in questions if not raw["hybrid_graph"][q["id"]].get("graph_used")]
    out["graph_comparison"] = compare_graph(raw["hybrid"], raw["hybrid_graph"], qrels, questions, tickets_by_id)
    out["graph_product_edges_comparison"] = compare_graph(
        raw["hybrid"], raw["hybrid_graph_product_edges"], qrels, questions, tickets_by_id)
    out["questions_without_lexical_seeds"] = graph_no_seeds
    out["lexical_empty_results"] = [q["id"] for q in questions if not raw["lexical"][q["id"]]["hits"]]

    sweep = {}
    for weight in GRAPH_WEIGHT_SWEEP:
        res = {q["id"]: run_strategy(db, directory, "hybrid_graph", q["text"], vectors[q["id"]], weight)
               for q in questions}
        _, summary = score_run(res, qrels, article_of, questions)
        sweep[str(weight)] = {g: summary[g]["tickets"] for g in summary}
    out["graph_weight_sweep"] = sweep
    return out


def describe_setup(store_info):
    questions = load_eval_questions()
    qrels = load_eval_qrels()
    doc = json.loads((FIXTURES / "incident_graph.json").read_text())
    sizes = [len(qrels[q["id"]]["tickets"]) for q in questions]
    return {
        "labels": ("Computed by scripts/make_fixtures.py from the generation structure of the fixtures "
                   "(a ticket's article_id and the invented incident definitions). Not reviewed by a human."),
        "questions": len(questions),
        "questions_by_intent": {i: sum(1 for q in questions if q["intent"] == i) for i in ("feature", "incident")},
        "relevant_tickets_per_question": {"min": min(sizes), "max": max(sizes)},
        "tickets_in_store": store_info["tickets"],
        "incident_links": {"total": len(doc["links"]),
                           "same_incident": sum(1 for x in doc["links"] if x["kind"] == "same_incident"),
                           "misfiled": sum(1 for x in doc["links"] if x["kind"] == "misfiled"),
                           "triaged_tickets": len(doc["members"]), "rule": doc["rule"]},
        "product_related_edges": store_info["product_related_edges"],
        "strategies": {
            "lexical": "search_text on ticket_text (subject weight 2.0, body 1.0), k=20",
            "hybrid": f"search_hybrid, stored vectors, rank fusion, candidate_k={retrieval.DEFAULT_CANDIDATE_K}, no graph, k=20",
            "hybrid_graph": ("hybrid plus graph evidence: relation SameIncident, direction both, 2 hops, weight 0.5, "
                             "seeds = the 3 top lexical hits of the same question"),
            "hybrid_graph_product_edges": ("ablation: same as hybrid_graph but over the original Related edges "
                                           "(each ticket to the 2 previous tickets of the same product)"),
        },
        "no_leakage": ("A strategy receives the question text and its vector. It never receives a product id, "
                       "article id, incident id, intent or label (checked by tests/test_evaluation.py)."),
    }


def run(workdir=None, out=None):
    own = workdir is None
    workdir = Path(workdir or tempfile.mkdtemp(prefix="grafx-eval-"))
    workdir.mkdir(parents=True, exist_ok=True)
    store = workdir / "eval-store"
    if store.exists():
        raise RuntimeError(f"{store} already exists. Use a new --workdir.")
    try:
        info = build_eval_store(store)
        with connect(store) as db:
            result = evaluate(db)
        result["setup"] = describe_setup(info)
        result["store_build"] = info
        if out:
            dump_json(out, {"result": result})
        return result
    finally:
        if own:
            shutil.rmtree(workdir, ignore_errors=True)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--workdir", help="where the temporary eval store is built (default: a temp dir, removed after)")
    ap.add_argument("--out", required=True, help="JSON file for the result")
    args = ap.parse_args(argv)
    result = run(args.workdir, args.out)
    show(result)
    return 0


def show(result):
    print(f"{'strategy':28s} {'group':9s} {'P@5':>6s} {'P@10':>6s} {'R@10':>6s} {'R@20':>6s} {'MRR':>6s} {'nDCG@10':>8s}")
    for name in STRATEGIES:
        for group in ("all", "feature", "incident"):
            m = result["strategies"][name][group]["tickets"]
            print(f"{name:28s} {group:9s} {m['precision@5']:6.3f} {m['precision@10']:6.3f} {m['recall@10']:6.3f} "
                  f"{m['recall@20']:6.3f} {m['mrr']:6.3f} {m['ndcg@10']:8.3f}")
    c = result["graph_comparison"]["counts"]
    print(f"graph vs hybrid, nDCG@10 per question: improved {c['improved']}, unchanged {c['unchanged']}, worse {c['worse']}")


if __name__ == "__main__":
    sys.exit(main())
