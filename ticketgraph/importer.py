"""Importer: loads fixtures into the store. Run as a separate process.

    python -m ticketgraph.importer --store PATH --name A --tickets FILE --slice 200 500 --stride 2 0 --out stats.json
"""
import argparse
import json
import os
import time
from pathlib import Path

from okto_grafx import connect

from .common import FIXTURES, dump_json, load_vectors, read_jsonl
from .retry import write_with_conflict_retry

TICKET_SQL = (
    "CREATE (:Ticket {id: $id, subject: $subject, body: $body, priority: $priority, "
    "status: $status, embedding: $embedding})"
)
LINKS = [
    "MATCH (c:Customer {id: $customer_id}), (t:Ticket {id: $id}) CREATE (c)-[:Opened]->(t)",
    "MATCH (t:Ticket {id: $id}), (a:Article {id: $article_id}) CREATE (t)-[:Mentions]->(a)",
    "MATCH (t:Ticket {id: $id}), (p:Product {id: $product_id}) CREATE (t)-[:About]->(p)",
]


def load_static(db):
    """Products, customers and articles, in one commit."""
    products = json.loads((FIXTURES / "products.json").read_text())
    customers = json.loads((FIXTURES / "customers.json").read_text())
    articles = read_jsonl(FIXTURES / "articles.jsonl")

    def operation(txn):
        txn.executemany("CREATE (:Product {id: $id, name: $name, summary: $summary})", products)
        txn.executemany("CREATE (:Customer {id: $id, name: $name})", customers)
        txn.executemany("CREATE (:Article {id: $id, title: $title, body: $body, revision: $revision})", articles)
        txn.executemany("MATCH (c:Customer {id: $id}), (p:Product {id: $product_id}) CREATE (c)-[:Uses]->(p)", customers)
        txn.executemany("MATCH (a:Article {id: $id}), (p:Product {id: $product_id}) CREATE (a)-[:Covers]->(p)", articles)

    report, conflicts = write_with_conflict_retry(db, operation)
    assert report.durable
    return {"durable": report.durable, "conflicts": conflicts,
            "products": len(products), "customers": len(customers), "articles": len(articles)}


def batch_operation(rows, vectors, hold=None):
    """One transaction: tickets plus their links. hold = (marker_path, seconds) pauses before commit."""
    params = [dict(r, embedding=vectors[r["id"]]) for r in rows]

    def operation(txn):
        txn.executemany(TICKET_SQL, params)
        for sql in LINKS:
            txn.executemany(sql, params)
        if hold is not None:
            marker, seconds = hold
            Path(marker).write_text(str(os.getpid()))
            time.sleep(seconds)

    return operation


def load_tickets(db, rows, batch_size, vectors, hold_last=None, name="importer"):
    """Load rows in batches. Every commit must report durable. Returns stats."""
    stats = {"name": name, "pid": os.getpid(), "tickets_committed": 0, "batches": 0,
             "conflicts": 0, "all_durable": True, "commit_csns": []}
    started = time.perf_counter()
    batches = [rows[i:i + batch_size] for i in range(0, len(rows), batch_size)]
    for n, batch in enumerate(batches):
        hold = hold_last if (hold_last is not None and n == len(batches) - 1) else None
        report, conflicts = write_with_conflict_retry(db, batch_operation(batch, vectors, hold))
        stats["conflicts"] += conflicts
        if not (report is not None and report.durable):
            stats["all_durable"] = False
            raise RuntimeError(f"commit not durable for batch {n}")
        stats["tickets_committed"] += len(batch)
        stats["batches"] += 1
        stats["commit_csns"].append(report.csn)
    stats["elapsed_seconds"] = round(time.perf_counter() - started, 3)
    return stats


def link_related(db, tickets, per_ticket=2, batch_size=100):
    """Related edges: each ticket points to the 2 previous tickets about the same product."""
    by_product = {}
    pairs = []
    for t in sorted(tickets, key=lambda r: r["id"]):
        earlier = by_product.setdefault(t["product_id"], [])
        for other in earlier[-per_ticket:]:
            pairs.append({"a": t["id"], "b": other})
        earlier.append(t["id"])
    sql = "MATCH (x:Ticket {id: $a}), (y:Ticket {id: $b}) CREATE (x)-[:Related]->(y)"
    commits = 0
    for i in range(0, len(pairs), batch_size):
        chunk = pairs[i:i + batch_size]
        report, _ = write_with_conflict_retry(db, lambda txn, c=chunk: txn.executemany(sql, c))
        assert report.durable
        commits += 1
    return {"edges": len(pairs), "commits": commits}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", required=True)
    ap.add_argument("--name", default="importer")
    ap.add_argument("--static", action="store_true", help="load products, customers and articles first")
    ap.add_argument("--tickets", default="tickets.jsonl")
    ap.add_argument("--slice", nargs=2, type=int, default=[0, 0], metavar=("START", "STOP"))
    ap.add_argument("--stride", nargs=2, type=int, default=[1, 0], metavar=("STEP", "OFFSET"))
    ap.add_argument("--batch", type=int, default=10)
    ap.add_argument("--hold-last", nargs=2, metavar=("MARKER", "SECONDS"),
                    help="pause inside the last transaction, before commit, and write MARKER")
    ap.add_argument("--start-file", help="wait until this file exists before writing")
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)

    rows = read_jsonl(FIXTURES / args.tickets)
    start, stop = args.slice
    if stop:
        rows = rows[start:stop]
    step, offset = args.stride
    rows = rows[offset::step]
    vectors = load_vectors()
    hold = (args.hold_last[0], float(args.hold_last[1])) if args.hold_last else None

    with connect(args.store) as db:
        result = {}
        if args.static:
            result["static"] = load_static(db)
        if args.start_file:
            while not Path(args.start_file).exists():
                time.sleep(0.01)
        result["tickets"] = load_tickets(db, rows, args.batch, vectors, hold_last=hold, name=args.name)
    dump_json(args.out, result)


if __name__ == "__main__":
    main()
