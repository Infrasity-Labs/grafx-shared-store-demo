"""Application recovery demo: an import that is killed twice and finished by restarting it.

    python -m ticketgraph.resume_demo --out resume.json [--workdir DIR]

Five separate importer processes run the same job on a fresh store:

  1. killed with SIGKILL inside batch 3's transaction, before its commit
  2. restarted, skips batches 0 to 2, killed right after batch 6's commit was acknowledged
  3. restarted, skips batches 0 to 6, finishes
  4. started again on a finished job: must change nothing
  5. a control importer loads the same rows in one uninterrupted run into a second store

After each step the store is reopened by this process and its state is recorded. At the end the resumed
store is compared with the fixtures and with the control store (content digests).
"""
import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path

from okto_grafx import connect
from okto_grafx.errors import GrafxError

from . import digest
from .appschema import committed_units, ensure_app_schema
from .common import FIXTURES, dump_json, load_vectors, read_jsonl, to_plain
from .importer import LINKS, batch_operation
from .procs import run_module
from .resumable import batch_unit
from .schema import create_store

JOB = "import-demo"
ROWS = (0, 100)
BATCH = 10
STATIC_ROWS = 70  # 5 products + 25 customers + 40 articles

GUARANTEES = {
    "grafx_database": [
        "A commit is atomic: a batch's tickets, links and checkpoint row are all there or none are.",
        "A commit reported durable survives SIGKILL of the writer.",
        "A transaction that never committed is not visible after the store is reopened (recovery).",
        "A duplicate primary key is refused, and the refused transaction writes nothing.",
    ],
    "application_ticketgraph": [
        "Knowing which batches are done: Checkpoint rows, written in the same transaction as the batch.",
        "Resuming: a restarted importer skips committed batches and does the rest.",
        "Not duplicating relationships: Grafx accepts a second identical relationship, so the application "
        "must never replay a committed batch (shown by the duplicate link probe).",
        "Refusing a changed input: a checkpoint carries a digest of its batch's ticket ids.",
    ],
}


class _Rollback(Exception):
    """Raised inside a probe transaction so that it is rolled back."""


def snapshot_state(store, job):
    """Reopen the store (this runs Grafx recovery) and record what is in it."""
    with connect(store) as db:
        recovery = to_plain(db.recovery_report)
        ids = [r[0] for r in db.execute("MATCH (t:Ticket) RETURN t.id ORDER BY t.id").rows]
        rels = {name: db.execute(f"MATCH ()-[r:{name}]->() RETURN count(*)").rows[0][0]
                for name in ("Opened", "Mentions", "About")}
        units = sorted(committed_units(db, job))
        findings = db.verify("all").findings
    return {"tickets": len(ids), "ticket_id_min": ids[0] if ids else None, "ticket_id_max": ids[-1] if ids else None,
            "relationships": rels, "committed_units": units,
            "recovery_outcome": recovery.get("outcome") if isinstance(recovery, dict) else recovery,
            "recovery_report": recovery, "verify_findings": len(findings)}


def read_events(path, offset):
    lines = Path(path).read_text().splitlines() if Path(path).exists() else []
    return [json.loads(x) for x in lines[offset:]], len(lines)


def duplicate_link_probe(store, rows):
    """What the database does NOT protect: write one committed batch's links a second time, then roll back."""
    batch = rows[:BATCH]
    params = [dict(r, embedding=None) for r in batch]
    result = {}
    with connect(store) as db:
        before = db.execute("MATCH ()-[r:Opened]->() RETURN count(*)").rows[0][0]
        try:
            with db.begin("write") as txn:
                for sql in LINKS:
                    txn.executemany(sql, params)
                result["opened_links_inside_probe_transaction"] = txn.execute(
                    "MATCH ()-[r:Opened]->() RETURN count(*)").rows[0][0]
                raise _Rollback
        except _Rollback:
            pass
        after = db.execute("MATCH ()-[r:Opened]->() RETURN count(*)").rows[0][0]
        result.update({"opened_links_before": before, "opened_links_after_rollback": after,
                       "grafx_accepted_duplicate_links": result["opened_links_inside_probe_transaction"] == before + len(batch),
                       "probe_rolled_back": before == after})
        vectors = load_vectors()
        error_type = None
        try:
            with db.begin("write") as txn:
                batch_operation(batch, vectors)(txn)
        except GrafxError as error:
            error_type = type(error).__name__
        result["blind_replay_of_whole_batch"] = {
            "refused": error_type is not None, "error_type": error_type,
            "tickets_after": db.execute("MATCH (t:Ticket) RETURN count(*)").rows[0][0]}
    return result


def verify_against_fixture(store, rows, job):
    """Final state against the fixture rows: identities, content, relationships, checkpoints."""
    expected = {r["id"]: r for r in rows}
    with connect(store) as db:
        got = {r[0]: r for r in db.execute(
            "MATCH (t:Ticket) RETURN t.id, t.subject, t.body, t.priority, t.status").rows}
        links = {
            "Opened": db.execute("MATCH (c:Customer)-[:Opened]->(t:Ticket) RETURN c.id, t.id").rows,
            "Mentions": db.execute("MATCH (t:Ticket)-[:Mentions]->(a:Article) RETURN t.id, a.id").rows,
            "About": db.execute("MATCH (t:Ticket)-[:About]->(p:Product) RETURN t.id, p.id").rows,
        }
        units = committed_units(db, job)
        findings = db.verify("all").findings
    want = {"Opened": sorted((r["customer_id"], r["id"]) for r in rows),
            "Mentions": sorted((r["id"], r["article_id"]) for r in rows),
            "About": sorted((r["id"], r["product_id"]) for r in rows)}
    content_mismatches = [i for i, r in expected.items() if i in got and tuple(got[i][1:]) != (
        r["subject"], r["body"], r["priority"], r["status"])]
    expected_units = ["static"] + [batch_unit(n) for n in range((len(rows) + BATCH - 1) // BATCH)]
    sample_ids = [rows[0]["id"], rows[len(rows) // 2]["id"], rows[-1]["id"]]
    return {
        "ticket_ids_match_fixture": sorted(got) == sorted(expected),
        "ticket_count": len(got), "expected_ticket_count": len(expected),
        "missing_ids": sorted(set(expected) - set(got)), "unexpected_ids": sorted(set(got) - set(expected)),
        "content_mismatches": content_mismatches,
        "relationship_counts": {k: len(v) for k, v in links.items()},
        "relationships_match_fixture": all(sorted(tuple(x) for x in links[k]) == want[k] for k in links),
        "duplicate_relationships": sum(len(v) - len(set(map(tuple, v))) for v in links.values()),
        "checkpoints_match_expected_units": sorted(units) == sorted(expected_units),
        "checkpoint_units": len(units),
        "verify_findings": len(findings),
        "representative_tickets": [{"id": i, "subject": got[i][1], "priority": got[i][3], "status": got[i][4],
                                   "matches_fixture": tuple(got[i][1:]) == (
                                       expected[i]["subject"], expected[i]["body"], expected[i]["priority"],
                                       expected[i]["status"])} for i in sample_ids],
    }


def run(workdir=None, out=None):
    own = workdir is None
    workdir = Path(workdir or tempfile.mkdtemp(prefix="grafx-resume-"))
    workdir.mkdir(parents=True, exist_ok=True)
    store, control = workdir / "resume-store", workdir / "control-store"
    events = workdir / "resume-events.jsonl"
    for p in (store, control, events):
        if p.exists():
            raise RuntimeError(f"{p} already exists. Use a new --workdir.")
    rows = read_jsonl(FIXTURES / "tickets.jsonl")[ROWS[0]:ROWS[1]]
    try:
        for path in (store, control):
            create_store(path)
            with connect(path) as db:
                ensure_app_schema(db)
        base = ["ticketgraph.resumable", "--job", JOB, "--slice", str(ROWS[0]), str(ROWS[1]), "--batch", str(BATCH)]
        phases, seen = [], 0

        def phase(label, expect_crash, name, crash_at=None):
            nonlocal seen
            out_file = workdir / f"{name}.json"
            args = base + ["--store", str(store), "--name", name, "--events", str(events), "--out", str(out_file)]
            if crash_at:
                args += ["--crash-at", crash_at]
            code, _ = run_module(*args, expect=(-9,) if expect_crash else (0,))
            evs, seen = read_events(events, seen)
            entry = {"phase": label, "importer": name, "crash_injected": crash_at, "returncode": code,
                     "events": [{k: v for k, v in e.items() if k != "t"} for e in evs],
                     "stats": json.loads(out_file.read_text()) if out_file.exists() else None}
            entry["state_after"] = snapshot_state(store, JOB)
            phases.append(entry)
            return entry

        initial = snapshot_state(store, JOB)
        phase("1 first run, killed inside batch 3 before its commit", True, "run1", "before_commit:3")
        phase("2 restart, killed right after batch 6 was acknowledged as committed", True, "run2", "after_commit:6")
        phase("3 restart, finishes the job", False, "run3")
        phase("4 start again on the finished job (must change nothing)", False, "run4")
        digest_before_rerun = phases[2]["state_after"]
        no_change = {k: phases[3]["state_after"][k] for k in ("tickets", "relationships", "committed_units")} == {
            k: digest_before_rerun[k] for k in ("tickets", "relationships", "committed_units")}

        probe = duplicate_link_probe(store, rows)
        final_state = snapshot_state(store, JOB)
        verification = verify_against_fixture(store, rows, JOB)

        run_module(*base, "--store", str(control), "--name", "control", "--out", str(workdir / "control.json"))
        with connect(store) as db1, connect(control) as db2:
            d_resumed, d_control = digest.content_digest(db1), digest.content_digest(db2)
        result = {
            "job": JOB, "input": {"tickets": len(rows), "batch_size": BATCH, "batches": len(rows) // BATCH,
                                  "first_ticket_id": rows[0]["id"], "last_ticket_id": rows[-1]["id"]},
            "guarantees": GUARANTEES,
            "state_before": initial,
            "phases": phases,
            "rerun_changed_nothing": no_change,
            "skipped_by_phase": {p["importer"]: (p["stats"] or {}).get("skipped") for p in phases},
            "duplicate_link_probe": probe,
            "final_state": final_state,
            "final_verification": verification,
            "control": {"description": "same job, same rows, one uninterrupted importer, separate store",
                        "digest": d_control["overall"], "resumed_digest": d_resumed["overall"],
                        "digests_match": d_control["overall"] == d_resumed["overall"],
                        "differing_tables": digest.differing_tables(d_resumed, d_control),
                        "table_rows": {k: v["rows"] for k, v in d_resumed["tables"].items() if v["rows"]}},
        }
        result["ok"] = (verification["ticket_ids_match_fixture"] and not verification["content_mismatches"]
                        and verification["relationships_match_fixture"] and verification["duplicate_relationships"] == 0
                        and verification["checkpoints_match_expected_units"] and verification["verify_findings"] == 0
                        and result["control"]["digests_match"] and no_change and probe["probe_rolled_back"]
                        and probe["blind_replay_of_whole_batch"]["refused"])
        if out:
            dump_json(out, {"result": result})
        return result
    finally:
        if own:
            shutil.rmtree(workdir, ignore_errors=True)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--workdir", help="default: a temp dir, removed after")
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    r = run(args.workdir, args.out)
    for p in r["phases"]:
        s = p["state_after"]
        print(f"{p['phase']}: exit {p['returncode']}, tickets {s['tickets']}, checkpoints {len(s['committed_units'])}, "
              f"recovery {s['recovery_outcome']}")
    print(f"final: {r['final_verification']['ticket_count']} tickets, duplicates "
          f"{r['final_verification']['duplicate_relationships']}, matches control {r['control']['digests_match']}, ok={r['ok']}")
    return 0 if r["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
