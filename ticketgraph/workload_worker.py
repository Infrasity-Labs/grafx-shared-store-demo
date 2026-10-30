"""One workload worker process: a writer, a reader, or the holder used for the recovery measurement.

Started by ticketgraph.workload, not meant to be run by hand:

    python -m ticketgraph.workload_worker --role writer --index 1 --store S --config C
        --ready-file R --start-file G --stop-file X --out OUT
"""
import argparse
import json
import os
import random
import time
from collections import Counter
from pathlib import Path

from okto_grafx import connect

from .common import dump_json
from .retry import write_with_conflict_retry
from .workload import (HOLDER_MARKER_ID, RECORD_BLOCK, RECORD_SQL, batch_operation, committed_entry,
                       plan_batch)

READER_PAUSE = 0.002


def wait_for(path, poll=0.005):
    while not Path(path).exists():
        time.sleep(poll)


def run_writer(db, cfg, writer, args):
    rng = random.Random(cfg["seed"] * 1000 + writer)
    attempt_seconds = {"committed": [], "conflict": [], "error": []}
    batch_seconds, committed, histogram = [], [], Counter()
    error_types, error_samples = set(), []
    counts = {"attempts": 0, "conflicts": 0, "failed_batches": 0}
    Path(args.ready_file).write_text(str(os.getpid()))
    wait_for(args.start_file)
    t_start = time.time()
    started = time.perf_counter()
    duration = cfg.get("duration_seconds")
    batch_index = 0
    while True:
        if duration is None:
            if batch_index * cfg["batch_size"] >= cfg["records_per_writer"]:
                break
        elif (time.perf_counter() - started >= duration
              or (batch_index + 1) * cfg["batch_size"] > RECORD_BLOCK):
            break
        plan = plan_batch(cfg, writer, batch_index, rng)
        batch_attempts = []

        def on_attempt(number, seconds, outcome):
            batch_attempts.append(outcome)
            attempt_seconds[outcome].append(seconds)

        batch_started = time.perf_counter()
        try:
            report, _ = write_with_conflict_retry(db, batch_operation(plan, writer), attempts=cfg["max_attempts"],
                                                  on_attempt=on_attempt)
            if report is None or not report.durable:
                raise RuntimeError("commit did not report durable")
            batch_seconds.append(time.perf_counter() - batch_started)
            committed.append(committed_entry(plan))
        except Exception as error:
            counts["failed_batches"] += 1
            error_types.add(type(error).__name__)
            if len(error_samples) < 3:
                error_samples.append(f"{type(error).__name__}: {error}"[:300])
        counts["attempts"] += len(batch_attempts)
        counts["conflicts"] += batch_attempts.count("conflict")
        histogram[max(len(batch_attempts) - 1, 0)] += 1
        batch_index += 1
    t_end = time.time()
    return {
        "role": "writer", "writer": writer, "pid": os.getpid(), "t_start": t_start, "t_end": t_end,
        "committed": committed, "attempt_seconds": attempt_seconds, "batch_seconds": batch_seconds,
        "retry_histogram": {str(k): v for k, v in histogram.items()},
        "error_types": sorted(error_types), "error_samples": error_samples, **counts,
    }


def run_reader(db, cfg, reader, args):
    rng = random.Random(cfg["seed"] * 1000 + 500 + reader)
    batch_size = cfg["batch_size"]
    read_seconds, errors = [], Counter()
    iterations = lookups = hits = partial = 0
    max_count = 0
    Path(args.ready_file).write_text(str(os.getpid()))
    wait_for(args.start_file)
    t_start = time.time()
    while iterations == 0 or not Path(args.stop_file).exists():
        started = time.perf_counter()
        try:
            with db.begin("read") as txn:
                count = txn.execute("MATCH (r:WRecord) RETURN count(*)").rows[0][0]
                writer = rng.randint(1, cfg["writers"])
                offset = rng.randrange(max(count // cfg["writers"], 1))
                rid = writer * RECORD_BLOCK + offset
                found = txn.execute("MATCH (r:WRecord {id: $id}) RETURN r.id", {"id": rid}).rows
                txn.execute("MATCH (h:WHot) RETURN sum(h.version)")
            read_seconds.append(time.perf_counter() - started)
            lookups += 1
            hits += 1 if found else 0
            max_count = max(max_count, count)
            if count % batch_size:
                partial += 1
        except Exception as error:
            errors[type(error).__name__] += 1
        iterations += 1
        time.sleep(READER_PAUSE)
    return {
        "role": "reader", "reader": reader, "pid": os.getpid(), "t_start": t_start, "t_end": time.time(),
        "iterations": iterations, "lookups": lookups, "lookup_hits": hits, "max_record_count": max_count,
        "partial_batch_observations": partial, "errors": dict(errors), "read_seconds": read_seconds,
    }


def run_holder(db, marker):
    """Open a write transaction, write an uncommitted marker record, then wait to be SIGKILLed."""
    with db.begin("write") as txn:
        txn.execute(RECORD_SQL, {"id": HOLDER_MARKER_ID, "writer": 0, "seq": 0, "payload": "uncommitted"})
        Path(marker).write_text(str(os.getpid()))
        time.sleep(600)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--role", required=True, choices=["writer", "reader", "holder"])
    ap.add_argument("--index", type=int, default=0)
    ap.add_argument("--store", required=True)
    ap.add_argument("--config")
    ap.add_argument("--ready-file")
    ap.add_argument("--start-file")
    ap.add_argument("--stop-file")
    ap.add_argument("--marker")
    ap.add_argument("--out")
    args = ap.parse_args(argv)
    cfg = json.loads(Path(args.config).read_text(encoding="utf-8")) if args.config else None

    with connect(args.store) as db:
        if args.role == "holder":
            run_holder(db, args.marker)
            return
        runner = run_writer if args.role == "writer" else run_reader
        result = runner(db, cfg, args.index, args)
    dump_json(args.out, result)


if __name__ == "__main__":
    main()
