"""Searcher: read-only work. Counts, snapshot reads, text search and hybrid search."""
import argparse
import time
from pathlib import Path

from okto_grafx import HybridSearchOptions, TextIndexOptions, connect

from .common import FIXTURES, dump_json, load_question_vectors, load_questions, read_jsonl

COUNT_QUERIES = {
    "tickets": "MATCH (t:Ticket) RETURN count(*)",
    "customers": "MATCH (c:Customer) RETURN count(*)",
    "articles": "MATCH (a:Article) RETURN count(*)",
    "products": "MATCH (p:Product) RETURN count(*)",
    "opened": "MATCH ()-[r:Opened]->() RETURN count(*)",
    "mentions": "MATCH ()-[r:Mentions]->() RETURN count(*)",
    "about": "MATCH ()-[r:About]->() RETURN count(*)",
    "related": "MATCH ()-[r:Related]->() RETURN count(*)",
}


def counts(db, reader=None):
    run = reader.execute if reader is not None else db.execute
    return {name: run(sql).rows[0][0] for name, sql in COUNT_QUERIES.items()}


def create_ticket_text_index(db):
    db.create_text_index("ticket_text", "Ticket", ("subject", "body"),
                         options=TextIndexOptions(field_weights=(2.0, 1.0)))


def ticket_directory(db):
    """Native record id -> (ticket id, subject), read from system history at the newest commit."""
    commit = db.commit_history().entries[-1].identity
    graph = db.system_as_of(commit, tables=("Ticket",))
    return {row.record_id: (row.values[0], row.values[1]) for row in graph.rows}


def _hit(directory, h):
    ticket_id, subject = directory[h.record_id]
    return {"ticket_id": ticket_id, "subject": subject, "score": round(h.score, 6)}


def keyword_search(db, directory, question, k=5):
    with db.begin("read") as reader:
        found = db.search_text(reader, index="ticket_text", query=question["text"], k=k)
    return {"id": question["id"], "query": question["text"], "regime": found.regime,
            "hits": [dict(_hit(directory, h), matched_fields=list(h.matched_fields)) for h in found.hits]}


def phrase_search(db, directory, question, k=5):
    with db.begin("read") as reader:
        found = db.search_text(reader, index="ticket_text", query=question["text"], k=k, phrase=True)
    return {"id": question["id"], "query": question["text"], "regime": found.regime,
            "hits": [dict(_hit(directory, h), matched_fields=list(h.matched_fields)) for h in found.hits]}


def product_seeds(directory, product_id, n=3):
    """Fixed rule, set before any search: the n lowest ticket ids of the question's product."""
    tickets = read_jsonl(FIXTURES / "tickets.jsonl")
    rid_by_ticket = {tid: rid for rid, (tid, _) in directory.items()}
    ids = sorted(t["id"] for t in tickets if t["product_id"] == product_id)[:n]
    return tuple(rid_by_ticket[i] for i in ids)


def hybrid_search(db, directory, question, vector, k=5, with_graph=True):
    options = {"candidate_k": 50}
    if with_graph:
        options.update(graph_relations=("Related",), graph_seeds=product_seeds(directory, question["product_id"]),
                       graph_direction="both", graph_hops=2, graph_weight=0.5)
    with db.begin("read") as reader:
        found = db.search_hybrid(reader, table="Ticket", index="ticket_text", query=question["text"],
                                 space="minilm", vector=tuple(vector), k=k, options=HybridSearchOptions(**options))
    return {"id": question["id"], "query": question["text"], "regime": found.regime,
            "hits": [dict(_hit(directory, h), lexical_rank=h.lexical_rank, vector_rank=h.vector_rank,
                          graph_distance=h.graph_distance) for h in found.hits]}


def run_all_questions(db):
    directory = ticket_directory(db)
    questions = load_questions()
    qvecs = load_question_vectors()
    return {
        "keyword": [keyword_search(db, directory, q) for q in questions["keyword"]],
        "phrase": [phrase_search(db, directory, q) for q in questions["phrase"]],
        "hybrid": [hybrid_search(db, directory, q, qvecs[q["id"]]) for q in questions["keyword"]],
        "hybrid_no_graph": [hybrid_search(db, directory, q, qvecs[q["id"]], with_graph=False)
                            for q in questions["keyword"]],
    }


def snapshot_demo(store, signal_dir, out):
    """Step 4 Searcher process: hold a read snapshot while another process commits."""
    signal_dir = Path(signal_dir)
    with connect(store) as db:  # a read-only open needs a checkpoint-complete store
        old = db.begin("read")
        try:
            before = counts(db, old)
            (signal_dir / "snapshot_open").write_text("open")
            deadline = time.time() + 120
            while not (signal_dir / "committed").exists():
                if time.time() > deadline:
                    raise TimeoutError("importer never committed")
                time.sleep(0.02)
            old_after = counts(db, old)
        finally:
            old.rollback()
        new_read = counts(db)
    dump_json(out, {"old_snapshot_before_commit": before, "old_snapshot_after_commit": old_after,
                    "new_read_after_commit": new_read, "pid": __import__("os").getpid()})


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["snapshot"])
    ap.add_argument("--store", required=True)
    ap.add_argument("--dir", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    snapshot_demo(a.store, a.dir, a.out)
