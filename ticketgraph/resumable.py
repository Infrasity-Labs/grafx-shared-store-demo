"""A resumable, idempotent importer. Run as a separate process, and run again after it dies.

    python -m ticketgraph.resumable --store PATH --job NAME --slice 0 100 --batch 10 --out stats.json

What Grafx guarantees: a commit is atomic and durable, and a transaction that never committed leaves
nothing behind after recovery. What Grafx does not do: it does not know that an importer was in the
middle of a job, it does not tell a restarted importer which batches are done, and it does not stop
an application from writing the same relationship twice. That is this module's job.

How it resumes:
- Every batch is ONE transaction that writes the tickets, their links and one Checkpoint row.
  The row exists if and only if the batch committed. There is no state kept outside the database.
- A restarted importer reads the Checkpoint rows of its job and skips those batches.
- A checkpoint also stores a digest of the batch's ticket ids. If the input changed between runs the
  importer refuses instead of silently mixing two inputs.
- Ticket ids are primary keys, so a blind replay of a committed batch fails and writes nothing. That
  protects the nodes. It is not what protects the relationships: see duplicate_link_probe in
  ticketgraph/resume_demo.py.

--crash-at injects a failure by sending SIGKILL to the importer itself:
  before_commit:N   inside batch N's transaction, after its writes, before the commit
  after_commit:N    right after batch N's commit was acknowledged as durable, before anything else runs
"""
import argparse
import hashlib
import json
import os
import signal
import time

from okto_grafx import connect

from .appschema import committed_units, write_checkpoint
from .common import FIXTURES, dump_json, load_vectors, read_jsonl
from .importer import batch_operation, static_operation
from .retry import write_with_conflict_retry


def batch_unit(n):
    return f"batch-{n:05d}"


def unit_key(job, unit):
    return f"{job}:{unit}"


def ids_digest(rows):
    return hashlib.sha256(",".join(str(r["id"]) for r in rows).encode()).hexdigest()[:16]


class CrashPoint:
    """Where to kill the importer, or nowhere."""

    def __init__(self, kind=None, batch=None):
        if kind not in (None, "before_commit", "after_commit"):
            raise ValueError(f"unknown crash point {kind!r}")
        self.kind, self.batch = kind, batch

    @classmethod
    def parse(cls, text):
        if not text:
            return cls()
        kind, _, number = text.partition(":")
        return cls(kind, int(number))

    def fire(self, kind, batch, log, unit=None):
        if self.kind == kind and self.batch == batch:
            log("sigkill_self", unit=unit or batch_unit(batch), point=kind)
            os.kill(os.getpid(), signal.SIGKILL)


def run_import(db, job, rows, batch_size, vectors, crash=None, log=None):
    """Load rows in batches, skipping batches that are already committed. Returns stats."""
    crash = crash or CrashPoint()
    log = log or (lambda *a, **k: None)
    stats = {"job": job, "pid": os.getpid(), "batches_total": 0, "skipped": [], "committed": [], "conflicts": 0,
             "tickets_committed": 0, "all_durable": True}
    started = time.perf_counter()
    done = committed_units(db, job)
    batches = [rows[i:i + batch_size] for i in range(0, len(rows), batch_size)]
    stats["batches_total"] = len(batches)
    log("start", already_committed=sorted(done))

    if "static" not in done:
        operation, counts = static_operation()

        def static(txn):
            operation(txn)
            write_checkpoint(txn, unit_key(job, "static"), job, "static", sum(counts.values()), "")

        report, conflicts = write_with_conflict_retry(db, static)
        stats["conflicts"] += conflicts
        assert report.durable
        stats["committed"].append("static")
        log("committed", unit="static", csn=report.csn)

    for n, batch in enumerate(batches):
        unit = batch_unit(n)
        digest = ids_digest(batch)
        if unit in done:
            if done[unit][1] != digest:
                raise RuntimeError(f"{unit} is committed for a different input (checkpoint digest "
                                   f"{done[unit][1]}, this input {digest}). Refusing to continue.")
            stats["skipped"].append(n)
            log("skipped", unit=unit)
            continue
        write = batch_operation(batch, vectors)

        def operation(txn, write=write, n=n, unit=unit, batch=batch, digest=digest):
            write(txn)
            write_checkpoint(txn, unit_key(job, unit), job, unit, len(batch), digest)
            log("in_transaction", unit=unit)
            crash.fire("before_commit", n, log)

        report, conflicts = write_with_conflict_retry(db, operation)
        stats["conflicts"] += conflicts
        if not (report is not None and report.durable):
            stats["all_durable"] = False
            raise RuntimeError(f"commit not durable for {unit}")
        log("committed", unit=unit, csn=report.csn)
        crash.fire("after_commit", n, log)
        stats["committed"].append(unit)
        stats["tickets_committed"] += len(batch)
    stats["elapsed_seconds"] = round(time.perf_counter() - started, 3)
    return stats


def make_logger(path, name):
    def log(event, **fields):
        if path:
            with open(path, "a", encoding="utf-8") as handle:
                handle.write(json.dumps(dict({"pid": os.getpid(), "actor": name, "event": event, "t": round(time.time(), 3)},
                                             **fields), sort_keys=True) + "\n")
    return log


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--store", required=True)
    ap.add_argument("--job", required=True)
    ap.add_argument("--name", default="importer", help="label for the event log")
    ap.add_argument("--tickets", default="tickets.jsonl")
    ap.add_argument("--slice", nargs=2, type=int, default=[0, 0], metavar=("START", "STOP"))
    ap.add_argument("--batch", type=int, default=10)
    ap.add_argument("--crash-at", help="before_commit:N or after_commit:N, kills this process with SIGKILL")
    ap.add_argument("--events", help="append one JSON line per event to this file")
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)

    rows = read_jsonl(FIXTURES / args.tickets)
    start, stop = args.slice
    if stop:
        rows = rows[start:stop]
    with connect(args.store) as db:
        stats = run_import(db, args.job, rows, args.batch, load_vectors(),
                           crash=CrashPoint.parse(args.crash_at), log=make_logger(args.events, args.name))
    dump_json(args.out, stats)


if __name__ == "__main__":
    main()
