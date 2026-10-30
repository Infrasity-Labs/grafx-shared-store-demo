"""Opt-in concurrency workload against a fresh temporary Grafx store.

It does not touch the ticket demo schema. It builds its own small store:

    WRecord(id INT64, writer INT64, seq INT64, payload STRING, PRIMARY KEY(id))
    WHot(id INT64, version INT64, last_writer INT64, PRIMARY KEY(id))
    REL WLink(FROM WRecord TO WHot)

Writer and reader processes (ticketgraph.workload_worker) run against the store at the same time.
Each writer batch is one write transaction that creates `batch_size` WRecords, their WLinks and a
read-modify-write of every distinct WHot row it linked to. Afterwards the orchestrator checks the
store against what the writers say they committed (lost updates, lost or extra records, partial
batches seen by readers), then measures a reopen after a SIGKILL of a process that held an open
write transaction.

    python -m ticketgraph.workload --config workloads/disjoint-small.json [--workdir DIR] [--out FILE]
        [--override key=value ...] [--keep-store] [--allow-large]

Config keys (JSON object; unknown keys are rejected):

    name                  string, required.
    description           string, optional.
    writers               int >= 1, required. Writer processes.
    readers               int >= 0, required. Reader processes.
    records_per_writer    int >= 1, multiple of batch_size, < 1000000. WRecord rows each writer creates.
    duration_seconds      number > 0. Writers run for this long instead.
                          Exactly one of records_per_writer and duration_seconds must be given.
    batch_size            int >= 1, required. WRecords per write transaction.
    links_per_record      int >= 0, default 1. WLink rels per record; at most hot_records.
    contention            "disjoint" or "shared", required.
                          shared: one pool of `hot_records` WHot rows read-modify-written by every writer.
                          disjoint: each writer has its own private pool of `hot_records` WHot rows.
    hot_records           int >= 1, required. Pool size, see contention.
    max_attempts          int >= 1, default 12. Retry budget for ticketgraph.retry.write_with_conflict_retry.
    seed                  int, default 0. Writer w draws hot rows from random.Random(seed * 1000 + w).

Record ids: writer w (1-based) uses w * 1_000_000 + batch_index * batch_size + j. Hot ids: shared pool
1..hot_records; disjoint pool of writer w is w * 1_000_000 + i for i in 0..hot_records-1.

Latency definitions (all reported in milliseconds):
    commit_latency_ms   one write attempt that committed: the whole transaction block, i.e. the
                        statements, the read-modify-write and the commit.
    batch_latency_ms    one committed batch end to end, including conflict attempts and backoff pauses.
    read_latency_ms     one reader iteration (one read transaction: count, point lookup, sum).
"""
import argparse
import json
import math
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from collections import Counter
from pathlib import Path

from okto_grafx import connect

from .common import ROOT, dump_json, to_plain

RECORD_BLOCK = 1_000_000
LARGE_LIMIT = 200_000
SEED_CHUNK = 500

DDL = [
    "CREATE NODE TABLE WRecord(id INT64, writer INT64, seq INT64, payload STRING, PRIMARY KEY(id))",
    "CREATE NODE TABLE WHot(id INT64, version INT64, last_writer INT64, PRIMARY KEY(id))",
    "CREATE REL TABLE WLink(FROM WRecord TO WHot)",
]
RECORD_SQL = "CREATE (:WRecord {id: $id, writer: $writer, seq: $seq, payload: $payload})"
LINK_SQL = "MATCH (r:WRecord {id: $r}), (h:WHot {id: $h}) CREATE (r)-[:WLink]->(h)"
HOT_SEED_SQL = "CREATE (:WHot {id: $id, version: 0, last_writer: -1})"
HOT_READ_SQL = "MATCH (h:WHot {id: $id}) RETURN h.version"
HOT_SET_SQL = "MATCH (h:WHot {id: $id}) SET h.version = $v, h.last_writer = $w"

KNOWN_KEYS = {
    "name", "description", "writers", "readers", "records_per_writer", "duration_seconds", "batch_size",
    "links_per_record", "contention", "hot_records", "max_attempts", "seed",
}
RECOVERY_LABEL = ("reopen time after SIGKILL of a process holding an open write transaction, "
                  "at this store size")


# ------------------------------------------------------------------ pure helpers
def percentile(values, p):
    """Nearest-rank percentile: sorted(values)[ceil(p/100 * n) - 1], with p=0 giving the minimum.

    Returns None for an empty list. p must be within 0..100.
    """
    if not 0 <= p <= 100:
        raise ValueError("p must be within 0..100")
    if not values:
        return None
    ordered = sorted(values)
    rank = max(math.ceil(p / 100 * len(ordered)), 1)
    return ordered[rank - 1]


def summarize(values, scale=1000.0, digits=3):
    """{count,min,p50,p95,p99,max,mean} of values times scale (seconds to milliseconds by default).

    Percentiles use percentile() (nearest rank). An empty list gives count 0 and None for the rest.
    """
    if not values:
        return {"count": 0, "min": None, "p50": None, "p95": None, "p99": None, "max": None, "mean": None}
    return {
        "count": len(values),
        "min": round(min(values) * scale, digits),
        "p50": round(percentile(values, 50) * scale, digits),
        "p95": round(percentile(values, 95) * scale, digits),
        "p99": round(percentile(values, 99) * scale, digits),
        "max": round(max(values) * scale, digits),
        "mean": round(sum(values) / len(values) * scale, digits),
    }


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def validate_config(config, allow_large=False):
    """Return a normalized copy of config (defaults filled in). Raise ValueError with a clear message."""
    if not isinstance(config, dict):
        raise ValueError("workload config must be a JSON object")
    unknown = sorted(set(config) - KNOWN_KEYS)
    if unknown:
        raise ValueError(f"unknown config keys: {', '.join(unknown)}")
    cfg = dict(config)
    cfg.setdefault("description", "")
    cfg.setdefault("links_per_record", 1)
    cfg.setdefault("max_attempts", 12)
    cfg.setdefault("seed", 0)

    for key in ("name", "writers", "readers", "batch_size", "contention", "hot_records"):
        if key not in cfg:
            raise ValueError(f"config key '{key}' is required")
    if not isinstance(cfg["name"], str) or not cfg["name"]:
        raise ValueError("name must be a non-empty string")
    if not isinstance(cfg["description"], str):
        raise ValueError("description must be a string")
    minimums = {"writers": 1, "readers": 0, "batch_size": 1, "links_per_record": 0,
                "hot_records": 1, "max_attempts": 1}
    for key, low in minimums.items():
        if not _is_int(cfg[key]) or cfg[key] < low:
            raise ValueError(f"{key} must be an integer >= {low}, got {cfg[key]!r}")
    if not _is_int(cfg["seed"]):
        raise ValueError(f"seed must be an integer, got {cfg['seed']!r}")
    if cfg["contention"] not in ("disjoint", "shared"):
        raise ValueError(f"contention must be 'disjoint' or 'shared', got {cfg['contention']!r}")
    if cfg["links_per_record"] > cfg["hot_records"]:
        raise ValueError("links_per_record cannot exceed hot_records (each record links to distinct hot rows)")

    has_records = "records_per_writer" in cfg
    has_duration = "duration_seconds" in cfg
    if has_records == has_duration:
        raise ValueError("give exactly one of records_per_writer and duration_seconds"
                         + (" (both were given)" if has_records else " (neither was given)"))
    if has_records:
        rpw = cfg["records_per_writer"]
        if not _is_int(rpw) or rpw < 1:
            raise ValueError(f"records_per_writer must be an integer >= 1, got {rpw!r}")
        if rpw >= RECORD_BLOCK:
            raise ValueError(f"records_per_writer must be below {RECORD_BLOCK} (id range per writer)")
        if rpw % cfg["batch_size"]:
            raise ValueError("records_per_writer must be a multiple of batch_size")
        total = cfg["writers"] * rpw
        if total > LARGE_LIMIT and not allow_large:
            raise ValueError(f"writers * records_per_writer = {total} exceeds {LARGE_LIMIT}; "
                             "pass --allow-large to run a workload this big")
    else:
        if not _is_number(cfg["duration_seconds"]) or cfg["duration_seconds"] <= 0:
            raise ValueError(f"duration_seconds must be a number > 0, got {cfg['duration_seconds']!r}")
    return cfg


def load_config(path, allow_large=False):
    """Read and validate a workload config file."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(f"{path}: not valid JSON: {error}") from error
    return validate_config(data, allow_large=allow_large)


def parse_override(text):
    """'key=value' to (key, value). Ints and floats are parsed; 'none' or 'null' removes the key (None)."""
    if "=" not in text:
        raise ValueError(f"override must look like key=value, got {text!r}")
    key, raw = text.split("=", 1)
    if raw.lower() in ("none", "null"):
        return key, None
    for cast in (int, float):
        try:
            return key, cast(raw)
        except ValueError:
            pass
    return key, raw


def apply_overrides(config, overrides):
    cfg = dict(config)
    for text in overrides:
        key, value = parse_override(text)
        if value is None:
            cfg.pop(key, None)
        else:
            cfg[key] = value
    return cfg


def writer_ids(writers):
    return range(1, writers + 1)


def hot_pool(config, writer):
    """The WHot ids writer draws from."""
    if config["contention"] == "shared":
        return list(range(1, config["hot_records"] + 1))
    return [writer * RECORD_BLOCK + i for i in range(config["hot_records"])]


def all_hot_ids(config):
    if config["contention"] == "shared":
        return list(range(1, config["hot_records"] + 1))
    ids = []
    for writer in writer_ids(config["writers"]):
        ids.extend(hot_pool(config, writer))
    return ids


def plan_batch(config, writer, batch_index, rng):
    """Deterministic plan for one batch: record ids, links (record, hot) and the distinct hot ids."""
    first = writer * RECORD_BLOCK + batch_index * config["batch_size"]
    ids = list(range(first, first + config["batch_size"]))
    pool = hot_pool(config, writer)
    links = []
    for rid in ids:
        for hid in rng.sample(pool, config["links_per_record"]):
            links.append((rid, hid))
    return {"batch": batch_index, "first_id": first, "ids": ids, "links": links,
            "hot": sorted({hid for _, hid in links})}


def batch_operation(plan, writer):
    """The transaction body for one planned batch, including the read-modify-write of each hot row."""
    first_seq = plan["batch"] * len(plan["ids"])
    records = [{"id": rid, "writer": writer, "seq": first_seq + i, "payload": f"w{writer}-{rid}"}
               for i, rid in enumerate(plan["ids"])]
    links = [{"r": r, "h": h} for r, h in plan["links"]]

    def operation(txn):
        txn.executemany(RECORD_SQL, records)
        if links:
            txn.executemany(LINK_SQL, links)
        for hid in plan["hot"]:
            rows = txn.execute(HOT_READ_SQL, {"id": hid}).rows
            version = rows[0][0]
            txn.execute(HOT_SET_SQL, {"id": hid, "v": version + 1, "w": writer})

    return operation


def committed_entry(plan):
    """What a writer reports for a committed batch (ids are first_id .. first_id + count - 1)."""
    return {"batch": plan["batch"], "first_id": plan["first_id"], "count": len(plan["ids"]),
            "hot": plan["hot"], "links": [list(pair) for pair in plan["links"]]}


def dir_bytes(path):
    return sum(p.stat().st_size for p in Path(path).rglob("*") if p.is_file())


# ------------------------------------------------------------------ store
def create_store(store, config):
    """Create the schema and seed the WHot rows (version 0, last_writer -1)."""
    with connect(store) as db:
        with db.begin("write") as txn:
            for statement in DDL:
                txn.execute(statement)
        db.ensure_identity_indexes()
        hot = [{"id": hid} for hid in all_hot_ids(config)]
        for i in range(0, len(hot), SEED_CHUNK):
            with db.begin("write") as txn:
                txn.executemany(HOT_SEED_SQL, hot[i:i + SEED_CHUNK])
        return len(db.verify("all").findings)


# ------------------------------------------------------------------ integrity
def expected_state(writer_results, config):
    """Fold writer logs into expected record ids, link pairs and per-hot version counts."""
    ids = set()
    links = Counter()
    versions = Counter()
    batches = 0
    for result in writer_results:
        for entry in result["committed"]:
            batches += 1
            ids.update(range(entry["first_id"], entry["first_id"] + entry["count"]))
            links.update((r, h) for r, h in entry["links"])
            versions.update(entry["hot"])
    return {"ids": ids, "links": links, "versions": versions, "batches": batches}


def check_integrity(store, writer_results, reader_results, config):
    """Open the store and compare it with what the workers reported.

    Returns {"checks": {name: bool}, "numbers": {...}, "ok": bool}. Checks:
    record_count, record_ids, link_count, link_pairs, hot_rows_present, hot_versions (every WHot
    version equals the committed batches that touched it, so a lost update fails here),
    hot_version_sum, hot_last_writer, no_partial_batches, no_reader_errors, verify_all.
    """
    expect = expected_state(writer_results, config)
    batch_size = config["batch_size"]
    with connect(store) as db:
        with db.begin("read") as txn:
            record_ids = [row[0] for row in txn.execute("MATCH (r:WRecord) RETURN r.id").rows]
            link_pairs = Counter((row[0], row[1]) for row in txn.execute(
                "MATCH (r:WRecord)-[l:WLink]->(h:WHot) RETURN r.id, h.id").rows)
            link_count = txn.execute("MATCH ()-[l:WLink]->() RETURN count(*)").rows[0][0]
            hot_rows = {row[0]: (row[1], row[2]) for row in txn.execute(
                "MATCH (h:WHot) RETURN h.id, h.version, h.last_writer").rows}
            version_sum = txn.execute("MATCH (h:WHot) RETURN sum(h.version)").rows[0][0] or 0
        findings = db.verify("all").findings

    stored_ids = set(record_ids)
    expected_ids = expect["ids"]
    missing = expected_ids - stored_ids
    extra = stored_ids - expected_ids
    expected_hot = set(all_hot_ids(config))
    version_mismatches = {
        hid: {"stored": hot_rows[hid][0], "expected": expect["versions"].get(hid, 0)}
        for hid in sorted(expected_hot & set(hot_rows))
        if hot_rows[hid][0] != expect["versions"].get(hid, 0)
    }
    touches = sum(expect["versions"].values())
    bad_writer = []
    for hid, (version, last_writer) in hot_rows.items():
        if version == 0:
            valid = last_writer == -1
        elif config["contention"] == "disjoint":
            valid = last_writer == hid // RECORD_BLOCK
        else:
            valid = last_writer in set(writer_ids(config["writers"]))
        if not valid:
            bad_writer.append(hid)
    partial = sum(r["partial_batch_observations"] for r in reader_results)
    read_errors = sum(sum(r["errors"].values()) for r in reader_results)
    expected_records = expect["batches"] * batch_size

    checks = {
        "record_count": len(record_ids) == expected_records,
        "record_ids": not missing and not extra and len(record_ids) == len(stored_ids),
        "link_count": link_count == expected_records * config["links_per_record"]
        and link_count == sum(link_pairs.values()),
        "link_pairs": link_pairs == expect["links"],
        "hot_rows_present": set(hot_rows) == expected_hot,
        "hot_versions": not version_mismatches,
        "hot_version_sum": version_sum == touches and sum(v for v, _ in hot_rows.values()) == touches,
        "hot_last_writer": not bad_writer,
        "no_partial_batches": partial == 0,
        "no_reader_errors": read_errors == 0,
        "verify_all": len(findings) == 0,
    }
    numbers = {
        "committed_batches": expect["batches"],
        "expected_records": expected_records,
        "stored_records": len(record_ids),
        "missing_record_ids": len(missing),
        "extra_record_ids": len(extra),
        "stored_links": link_count,
        "expected_links": expected_records * config["links_per_record"],
        "hot_version_sum": version_sum,
        "expected_hot_version_sum": touches,
        "hot_version_mismatches": len(version_mismatches),
        "hot_version_mismatch_sample": dict(list(version_mismatches.items())[:5]),
        "partial_batch_observations": partial,
        "reader_errors": read_errors,
        "verify_findings": len(findings),
    }
    return {"checks": checks, "numbers": numbers, "ok": all(checks.values())}


# ------------------------------------------------------------------ orchestration
def _worker_cmd(role, index, store, cfg_file, files, out, extra=()):
    return [sys.executable, "-m", "ticketgraph.workload_worker", "--role", role, "--index", str(index),
            "--store", str(store), "--config", str(cfg_file), "--ready-file", str(files / f"ready-{role}-{index}"),
            "--start-file", str(files / "go"), "--stop-file", str(files / "stop"), "--out", str(out), *extra]


def _spawn(cmd, log_path):
    log = open(log_path, "wb")
    try:
        return subprocess.Popen(cmd, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
    finally:
        log.close()


def _log_tail(path, lines=15):
    try:
        return "\n".join(Path(path).read_text(errors="replace").splitlines()[-lines:])
    except OSError:
        return ""


def _kill_all(procs):
    for proc in procs:
        if proc.poll() is None:
            proc.kill()
    for proc in procs:
        proc.wait()


def _wait_for_files(paths, procs, logs, timeout):
    deadline = time.monotonic() + timeout
    while not all(Path(p).exists() for p in paths):
        for proc, log in zip(procs, logs):
            if proc.poll() is not None and proc.returncode != 0:
                raise RuntimeError(f"worker exited with {proc.returncode} before it was ready:\n{_log_tail(log)}")
        if time.monotonic() > deadline:
            raise RuntimeError("timed out waiting for workers to become ready")
        time.sleep(0.02)


def _wait_exit(procs, logs, deadline, what):
    for proc, log in zip(procs, logs):
        remaining = deadline - time.monotonic()
        try:
            proc.wait(timeout=max(remaining, 0.1))
        except subprocess.TimeoutExpired:
            raise RuntimeError(f"timed out waiting for {what}") from None
        if proc.returncode != 0:
            raise RuntimeError(f"{what} exited with {proc.returncode}:\n{_log_tail(log)}")


def _read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def measure_recovery(store, files, timeout=60):
    """SIGKILL a child that holds an open write transaction, then time connect(store)."""
    marker = files / "holder-marker"
    log = files / "holder.log"
    cmd = [sys.executable, "-m", "ticketgraph.workload_worker", "--role", "holder", "--store", str(store),
           "--marker", str(marker)]
    proc = _spawn(cmd, log)
    try:
        deadline = time.monotonic() + timeout
        while not marker.exists():
            if proc.poll() is not None:
                raise RuntimeError(f"holder exited early with {proc.returncode}:\n{_log_tail(log)}")
            if time.monotonic() > deadline:
                raise RuntimeError("timed out waiting for the holder process to open its write transaction")
            time.sleep(0.01)
        os.kill(proc.pid, signal.SIGKILL)
        proc.wait()
    finally:
        _kill_all([proc])
    started = time.perf_counter()
    with connect(store) as db:
        reopen = time.perf_counter() - started
        report = to_plain(db.recovery_report)
        with db.begin("read") as txn:
            marker_rows = txn.execute("MATCH (r:WRecord {id: $id}) RETURN r.id", {"id": HOLDER_MARKER_ID}).rows
        findings = len(db.verify("all").findings)
    return {
        "what": RECOVERY_LABEL,
        "reopen_seconds": round(reopen, 4),
        "killed_pid": proc.pid,
        "recovery_report": report,
        "uncommitted_marker_visible": bool(marker_rows),
        "verify_findings": findings,
        "outcome": "ok" if not marker_rows and findings == 0 else "unexpected",
    }


HOLDER_MARKER_ID = 999_999_999_999


def _aggregate(config, writer_results, reader_results, write_seconds):
    committed_attempts, conflict_attempts, error_attempts, batch_seconds = [], [], [], []
    conflicts_by_writer, failed_by_writer = {}, {}
    retry_hist = Counter()
    errors = set()
    error_samples = []
    attempts_total = conflicts_total = failed = committed_batches = with_retry = max_retries = 0
    for res in writer_results:
        w = str(res["writer"])
        committed_attempts += res["attempt_seconds"]["committed"]
        conflict_attempts += res["attempt_seconds"]["conflict"]
        error_attempts += res["attempt_seconds"]["error"]
        batch_seconds += res["batch_seconds"]
        conflicts_by_writer[w] = res["conflicts"]
        failed_by_writer[w] = res["failed_batches"]
        conflicts_total += res["conflicts"]
        attempts_total += res["attempts"]
        failed += res["failed_batches"]
        committed_batches += len(res["committed"])
        for retries, count in res["retry_histogram"].items():
            retry_hist[int(retries)] += count
            if int(retries) > 0:
                with_retry += count
            max_retries = max(max_retries, int(retries))
        errors.update(res["error_types"])
        error_samples += res["error_samples"]
    records = committed_batches * config["batch_size"]
    seconds = write_seconds if write_seconds > 0 else None
    return {
        "commit_latency_ms": summarize(committed_attempts),
        "conflict_attempt_latency_ms": summarize(conflict_attempts),
        "batch_latency_ms": summarize(batch_seconds),
        "read_latency_ms": summarize([s for r in reader_results for s in r["read_seconds"]]),
        "throughput": {
            "basis": "wall time of the write phase (first writer start to last writer finish)",
            "write_phase_seconds": round(write_seconds, 4),
            "records_committed": records,
            "batches_committed": committed_batches,
            "records_per_second": round(records / seconds, 2) if seconds else None,
            "batches_per_second": round(committed_batches / seconds, 2) if seconds else None,
        },
        "conflicts": {
            "total": conflicts_total,
            "by_writer": conflicts_by_writer,
            "attempts_total": attempts_total,
            "conflict_rate": round(conflicts_total / attempts_total, 4) if attempts_total else 0.0,
            "batches_with_retry": with_retry,
            "max_retries_in_one_batch": max_retries,
            "retry_histogram": {str(k): retry_hist[k] for k in sorted(retry_hist)},
        },
        "failed_or_exhausted": {
            "batches": failed,
            "by_writer": failed_by_writer,
            "errors": sorted(errors),
            "error_samples": error_samples[:5],
        },
        "readers": {
            "iterations": sum(r["iterations"] for r in reader_results),
            "lookups": sum(r["lookups"] for r in reader_results),
            "lookup_hits": sum(r["lookup_hits"] for r in reader_results),
            "partial_batch_observations": sum(r["partial_batch_observations"] for r in reader_results),
            "errors": sorted({k for r in reader_results for k in r["errors"]}),
        },
    }


def run_workload(config, workdir, allow_large=False, timeout=None):
    """Run one workload in workdir (must not already hold a store). Returns the result dict."""
    cfg = validate_config(config, allow_large=allow_large)
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    store = workdir / "store"
    if store.exists():
        raise ValueError(f"{store} already exists; use an empty workdir")
    files = workdir / "files"
    files.mkdir(exist_ok=True)
    if timeout is None:
        timeout = (cfg["duration_seconds"] + 120) if "duration_seconds" in cfg else 900
    wall_started = time.perf_counter()

    seed_findings = create_store(store, cfg)
    bytes_before = dir_bytes(store)
    cfg_file = files / "config.json"
    cfg_file.write_text(json.dumps(cfg), encoding="utf-8")

    procs, logs, outs = [], [], {}
    roles = [("writer", w) for w in writer_ids(cfg["writers"])] + [("reader", r) for r in range(1, cfg["readers"] + 1)]
    try:
        for role, index in roles:
            out = files / f"{role}-{index}.json"
            log = files / f"{role}-{index}.log"
            procs.append(_spawn(_worker_cmd(role, index, store, cfg_file, files, out), log))
            logs.append(log)
            outs[(role, index)] = out
        _wait_for_files([files / f"ready-{role}-{index}" for role, index in roles], procs, logs, 60)
        (files / "go").write_text("go")
        deadline = time.monotonic() + timeout
        n_writers = cfg["writers"]
        _wait_exit(procs[:n_writers], logs[:n_writers], deadline, "writers")
        (files / "stop").write_text("stop")
        _wait_exit(procs[n_writers:], logs[n_writers:], deadline, "readers")
    except BaseException:
        _kill_all(procs)
        raise

    writer_results = [_read_json(outs[("writer", w)]) for w in writer_ids(cfg["writers"])]
    reader_results = [_read_json(outs[("reader", r)]) for r in range(1, cfg["readers"] + 1)]
    write_seconds = max(r["t_end"] for r in writer_results) - min(r["t_start"] for r in writer_results)

    result = {
        "config": cfg,
        "pids": {"orchestrator": os.getpid(), "writers": [r["pid"] for r in writer_results],
                 "readers": [r["pid"] for r in reader_results]},
        "seed_verify_findings": seed_findings,
    }
    result.update(_aggregate(cfg, writer_results, reader_results, write_seconds))
    bytes_after = dir_bytes(store)
    result["store"] = {"dir_bytes_before": bytes_before, "dir_bytes_after": bytes_after}
    result["integrity"] = check_integrity(store, writer_results, reader_results, cfg)
    result["recovery"] = measure_recovery(store, files)
    result["wall_seconds"] = round(time.perf_counter() - wall_started, 3)
    return result


def main(argv=None):
    ap = argparse.ArgumentParser(description="Run an opt-in Grafx concurrency workload.")
    ap.add_argument("--config", required=True)
    ap.add_argument("--workdir", help="directory for the store and worker files (default: a temp dir)")
    ap.add_argument("--out", help="write the result JSON here")
    ap.add_argument("--override", action="append", default=[], metavar="KEY=VALUE",
                    help="override a config key; 'none' removes it (e.g. records_per_writer=none)")
    ap.add_argument("--keep-store", action="store_true", help="do not remove the temp workdir afterwards")
    ap.add_argument("--allow-large", action="store_true",
                    help=f"allow writers * records_per_writer above {LARGE_LIMIT}")
    args = ap.parse_args(argv)

    try:
        with open(args.config, encoding="utf-8") as handle:
            raw = json.load(handle)
        config = validate_config(apply_overrides(raw, args.override), allow_large=args.allow_large)
    except (ValueError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2

    temp = None
    if args.workdir:
        workdir = Path(args.workdir)
    else:
        temp = tempfile.mkdtemp(prefix="ticketgraph-workload-")
        workdir = Path(temp)
    try:
        result = run_workload(config, workdir, allow_large=args.allow_large)
    finally:
        if temp and not args.keep_store:
            shutil.rmtree(temp, ignore_errors=True)
        elif temp or args.workdir:
            print(f"store kept in {workdir}")
    if args.out:
        dump_json(args.out, result)
    tp, ok = result["throughput"], result["integrity"]["ok"]
    print(f"{config['name']}: {tp['records_per_second']} records/s, "
          f"{result['conflicts']['total']} conflicts in {result['conflicts']['attempts_total']} attempts, "
          f"{result['failed_or_exhausted']['batches']} failed batches, "
          f"p95 commit {result['commit_latency_ms']['p95']} ms, integrity ok={ok}")
    if not ok:
        failed = [name for name, passed in result["integrity"]["checks"].items() if not passed]
        print(f"integrity failed: {', '.join(failed)}", file=sys.stderr)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
