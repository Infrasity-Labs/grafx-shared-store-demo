"""The ten demo steps. Each step returns a plain dict that run_demo.py saves."""
import json
import os
import platform
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import okto_grafx
from okto_grafx import connect
from okto_grafx.backup import create_backup, restore_backup
from okto_grafx.transfer import export_graph, import_graph

from . import auditor, digest, restore_check, searcher
from .common import FIXTURES, ROOT, load_questions, read_jsonl, to_plain
from .importer import link_related
from .schema import create_store


class Ctx:
    """Where things live for one run."""

    def __init__(self, workdir, state_dir):
        self.workdir = Path(workdir).resolve()
        self.state_dir = Path(state_dir).resolve()
        self.store = self.workdir / "graph"
        self.backup = self.workdir / "backup-001"
        self.restored = self.workdir / "restored"
        self.package = self.workdir / "logical-package"
        self.fork = self.workdir / "fork"
        self.scratch = self.workdir / "scratch"
        self.children = []  # every subprocess pid started by the demo
        self.workdir.mkdir(parents=True, exist_ok=True)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.scratch.mkdir(exist_ok=True)


def py(*args):
    return [sys.executable, "-m", *args]


def importer_cmd(ctx, out, *extra):
    return py("ticketgraph.importer", "--store", str(ctx.store), "--out", str(out), *extra)


def spawn(ctx, cmd):
    proc = subprocess.Popen(cmd, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    ctx.children.append(proc.pid)
    return proc


def finish(proc, label):
    out, _ = proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"{label} exited with {proc.returncode}:\n{out}")
    return out


def read(path):
    return json.loads(Path(path).read_text())


def dir_bytes(path):
    return sum(p.stat().st_size for p in Path(path).rglob("*") if p.is_file())


# ---------------------------------------------------------------- step 1
def step1(ctx):
    if ctx.store.exists():
        raise RuntimeError(f"{ctx.store} already exists. Use a new --workdir or remove it.")
    report = create_store(ctx.store)
    with connect(ctx.store) as db:
        tables = [t.name for t in db.catalog.catalog.tables()]
        history = to_plain(db.commit_history().entries[-1].identity)
    return {
        "grafx_version": okto_grafx.__version__,
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "machine": platform.machine(),
        "tables": tables,
        "identity_indexes": True,
        "commit_history": True,
        "system_history_tables": ["Product", "Customer", "Article", "Ticket", "Opened", "Mentions",
                                  "About", "Covers", "Uses", "Related"],
        "last_commit": history,
        "verify_findings": len(report.findings),
        "verify_pages_checked": report.pages_checked,
        "verify_records_checked": report.records_checked,
    }


# ---------------------------------------------------------------- step 2
def step2(ctx):
    out = ctx.scratch / "step2-importer.json"
    finish(spawn(ctx, importer_cmd(ctx, out, "--name", "solo", "--static", "--slice", "0", "200",
                                   "--batch", "10")), "solo importer")
    r = read(out)
    with connect(ctx.store) as db:
        counts = searcher.counts(db)
    return {
        "tickets_loaded": r["tickets"]["tickets_committed"],
        "batches": r["tickets"]["batches"],
        "all_durable": r["tickets"]["all_durable"],
        "conflicts": r["tickets"]["conflicts"],
        "static": r["static"],
        "counts": counts,
        "pid": r["tickets"]["pid"],
    }


# ---------------------------------------------------------------- step 3
def step3(ctx):
    start = ctx.scratch / "go-step3"
    start.unlink(missing_ok=True)
    outs, procs = {}, {}
    for offset, name in ((0, "A"), (1, "B")):
        outs[name] = ctx.scratch / f"step3-{name}.json"
        procs[name] = spawn(ctx, importer_cmd(ctx, outs[name], "--name", name, "--slice", "200", "500",
                                              "--stride", "2", str(offset), "--batch", "10",
                                              "--start-file", str(start)))
    time.sleep(2.0)  # both processes have opened the store and are waiting
    start.write_text("go")
    for name, proc in procs.items():
        finish(proc, f"importer {name}")
    res = {n: read(p)["tickets"] for n, p in outs.items()}
    with connect(ctx.store) as db:
        counts = searcher.counts(db)
        ids = {row[0] for row in db.execute("MATCH (t:Ticket) RETURN t.id").rows}
        findings = db.verify("all").findings
    fixture = read_jsonl(FIXTURES / "tickets.jsonl")
    expected = {t["id"] for t in fixture}
    return {
        "tickets_loaded": sum(r["tickets_committed"] for r in res.values()),
        "fixture_ticket_count": len(fixture),
        "conflicts_by_importer": {n: r["conflicts"] for n, r in res.items()},
        "conflicts_total": sum(r["conflicts"] for r in res.values()),
        "batches_by_importer": {n: r["batches"] for n, r in res.items()},
        "all_durable": all(r["all_durable"] for r in res.values()),
        "pids": {n: r["pid"] for n, r in res.items()},
        "counts_after": counts,
        "lost_commits": len(expected - ids),
        "unexpected_ids": len(ids - expected),
        "verify_findings": len(findings),
    }


# ---------------------------------------------------------------- step 4
def step4(ctx):
    sig = ctx.scratch / "signals-step4"
    shutil.rmtree(sig, ignore_errors=True)
    sig.mkdir()
    out = ctx.scratch / "step4-searcher.json"
    searcher_proc = spawn(ctx, py("ticketgraph.searcher", "snapshot", "--store", str(ctx.store),
                                  "--dir", str(sig), "--out", str(out)))
    deadline = time.time() + 120
    while not (sig / "snapshot_open").exists():
        if time.time() > deadline or searcher_proc.poll() is not None:
            raise RuntimeError("searcher did not open its snapshot:\n" + (searcher_proc.communicate()[0] or ""))
        time.sleep(0.02)
    imp_out = ctx.scratch / "step4-importer.json"
    finish(spawn(ctx, importer_cmd(ctx, imp_out, "--name", "A-late", "--tickets", "tickets_late.jsonl",
                                   "--batch", "10")), "late importer")
    (sig / "committed").write_text("done")
    finish(searcher_proc, "searcher")
    r = read(out)
    late = read(imp_out)["tickets"]
    return {
        "late_tickets_loaded": late["tickets_committed"],
        "late_commit_durable": late["all_durable"],
        "old_before": r["old_snapshot_before_commit"],
        "old_after": r["old_snapshot_after_commit"],
        "new_read": r["new_read_after_commit"],
        "old_snapshot_unchanged": r["old_snapshot_before_commit"] == r["old_snapshot_after_commit"],
        "new_read_saw_commit": r["new_read_after_commit"]["tickets"] == r["old_snapshot_before_commit"]["tickets"]
                               + late["tickets_committed"],
        "searcher_pid": r["pid"],
    }


# ---------------------------------------------------------------- step 5
def step5(ctx):
    marker = ctx.scratch / "in-transaction"
    marker.unlink(missing_ok=True)
    out = ctx.scratch / "step5-importer.json"
    proc = spawn(ctx, importer_cmd(ctx, out, "--name", "B-crash", "--tickets", "tickets_crash.jsonl",
                                   "--batch", "10", "--hold-last", str(marker), "600"))
    deadline = time.time() + 120
    while not marker.exists():
        if time.time() > deadline or proc.poll() is not None:
            raise RuntimeError("importer never reached its last transaction:\n" + (proc.communicate()[0] or ""))
        time.sleep(0.02)
    time.sleep(0.5)
    os.kill(proc.pid, signal.SIGKILL)
    proc.wait()
    crash_rows = read_jsonl(FIXTURES / "tickets_crash.jsonl")
    committed_ids = [r["id"] for r in crash_rows[:20]]
    unfinished_ids = [r["id"] for r in crash_rows[20:]]

    reopen_started = time.perf_counter()
    with connect(ctx.store) as db:
        reopen_seconds = round(time.perf_counter() - reopen_started, 3)
        recovery = to_plain(db.recovery_report)
        found = {row[0] for row in db.execute("MATCH (t:Ticket) WHERE t.id >= 2001 RETURN t.id").rows}
        opened = db.execute("MATCH ()-[r:Opened]->(t:Ticket) WHERE t.id >= 2001 RETURN count(*)").rows[0][0]
        findings = db.verify("all").findings
        counts = searcher.counts(db)
        db.checkpoint()
    return {
        "signal": "SIGKILL",
        "killed_pid": proc.pid,
        "killed_returncode": proc.returncode,
        "batch_size": 10,
        "committed_expected": len(committed_ids),
        "committed_found": len(found & set(committed_ids)),
        "unfinished_expected_absent": len(unfinished_ids),
        "unfinished_found": len(found & set(unfinished_ids)),
        "opened_links_for_crash_tickets": opened,
        "recovery_outcome": recovery.get("outcome") if isinstance(recovery, dict) else recovery,
        "recovery_report": recovery,
        "reopen_seconds": reopen_seconds,
        "verify_findings": len(findings),
        "counts_after": counts,
    }


# ---------------------------------------------------------------- step 6
def step6(ctx):
    with connect(ctx.store) as db:
        link = link_related(db, read_jsonl(FIXTURES / "tickets.jsonl"))
        searcher.create_ticket_text_index(db)
        directory = searcher.ticket_directory(db)
        q = load_questions()
        keyword = [searcher.keyword_search(db, directory, x) for x in q["keyword"]]
        phrase = [searcher.phrase_search(db, directory, x) for x in q["phrase"]]
        findings = db.verify("all").findings
    return {"related_links": link, "index": "ticket_text on Ticket(subject, body), weights 2.0 and 1.0",
            "keyword": keyword, "phrase": phrase, "verify_findings": len(findings)}


# ---------------------------------------------------------------- step 7
def step7(ctx):
    step6_file = ctx.state_dir / "step06_full_text.json"
    text = read(step6_file)["result"]["keyword"]
    with connect(ctx.store) as db:
        every = searcher.run_all_questions(db)
    hybrid, plain = every["hybrid"], every["hybrid_no_graph"]
    rows = []
    for t, h, n in zip(text, hybrid, plain):
        t_ids = [x["ticket_id"] for x in t["hits"]]
        h_ids = [x["ticket_id"] for x in h["hits"]]
        n_ids = [x["ticket_id"] for x in n["hits"]]
        rows.append({"id": t["id"], "query": t["query"], "text_top5": t_ids, "hybrid_top5": h_ids,
                     "hybrid_no_graph_top5": n_ids,
                     "text_top1_tied_with_top2": len(t["hits"]) > 1 and t["hits"][0]["score"] == t["hits"][1]["score"],
                     "top1_changed_with_graph": bool(t_ids and h_ids and t_ids[0] != h_ids[0]),
                     "top1_changed_no_graph": bool(t_ids and n_ids and t_ids[0] != n_ids[0]),
                     "top5_set_changed_with_graph": set(t_ids) != set(h_ids)})
    return {
        "questions": len(rows),
        "top1_changed_with_graph": sum(r["top1_changed_with_graph"] for r in rows),
        "top1_changed_no_graph": sum(r["top1_changed_no_graph"] for r in rows),
        "top5_set_changed_with_graph": sum(r["top5_set_changed_with_graph"] for r in rows),
        "text_top1_tied_with_top2": sum(r["text_top1_tied_with_top2"] for r in rows),
        "side_by_side": rows,
        "hybrid_results": hybrid,
        "hybrid_no_graph_results": plain,
        "graph_rule": "Related edges, both directions, 2 hops, weight 0.5. Seeds are the 3 lowest ticket ids "
                      "of the question's product, set before any search.",
    }


# ---------------------------------------------------------------- step 8
NEW_BODY = ("This article covers webhook timeout in Cobalt Gateway. "
            "A webhook call is cancelled after 30 seconds, so reply with a 200 status first and do slow work later. "
            "Check the delivery log in the dashboard, then follow the steps in the settings page for webhook timeout.")


def step8(ctx):
    with connect(ctx.store) as db:
        result = auditor.time_travel(db, 25, NEW_BODY)
        findings = db.verify("all").findings
    result["verify_findings"] = len(findings)
    return result


# ---------------------------------------------------------------- step 9
def step9(ctx):
    from okto_grafx.errors import GrafxError

    for p in (ctx.backup, ctx.restored, ctx.package, ctx.fork):
        if p.exists():
            raise RuntimeError(f"{p} already exists. Use a new --workdir.")
    result = {"platform": sys.platform}
    digests = {}
    history = {}
    with connect(ctx.store) as db:
        original = searcher.counts(db)
        original_uuid = to_plain(db.identity.database_uuid)
        # Content and history of the original, taken before anything is copied.
        digests["original"] = digest.content_digest(db)
        history["original"] = restore_check.history_fingerprint(db)
        try:
            backup = create_backup(db, ctx.backup)
        except GrafxError as error:
            # Documented: only Windows and Linux can publish a backup. Other hosts refuse.
            backup = None
            result["physical_backup"] = {"supported": False, "error_type": type(error).__name__,
                                         "message": str(error).split(" [code=")[0],
                                         "code": getattr(error, "code", None)}
    result["counts_original"] = original
    result["original_dir_bytes"] = dir_bytes(ctx.store)
    if backup is not None:
        # The Auditor handle is closed. Check that every process the demo started has exited.
        alive = []
        for pid in ctx.children:
            try:
                os.kill(pid, 0)
                alive.append(pid)
            except ProcessLookupError:
                pass
        if alive:
            raise RuntimeError(f"processes still running: {alive}")
        restore_backup(ctx.backup, ctx.restored, confirm_original_offline=True)
        with connect(ctx.restored) as db:
            restored_findings = db.verify("all").findings
            restored_counts = searcher.counts(db)
            same_uuid = to_plain(db.identity.database_uuid) == original_uuid
            digests["restored"] = digest.content_digest(db)
            history["restored"] = restore_check.history_fingerprint(db)
        result.update({
            "physical_backup": {"supported": True},
            "backup_files": backup.files,
            "backup_payload_bytes": backup.bytes,
            "backup_dir_bytes": dir_bytes(ctx.backup),
            "processes_alive_at_restore": len(alive),
            "restored_dir_bytes": dir_bytes(ctx.restored),
            "restored_counts": restored_counts,
            "restored_counts_match": restored_counts == original,
            "restored_verify_findings": len(restored_findings),
            "restored_same_uuid": same_uuid,
        })
    try:
        with connect(ctx.store) as db:
            exported = export_graph(db, ctx.package, history="current-only")
        imported = import_graph(ctx.package, ctx.fork)
    except GrafxError as error:
        result["logical_transfer"] = {"supported": False, "error_type": type(error).__name__,
                                      "message": str(error).split(" [code=")[0]}
        result["integrity"] = integrity_summary(digests, history, result)
        result["digests"] = {k: v["tables"] for k, v in digests.items()}
        return result
    with connect(ctx.fork) as db:
        fork_counts = searcher.counts(db)
        fork_findings = db.verify("all").findings
        fork_uuid = to_plain(db.identity.database_uuid)
        digests["fork"] = digest.content_digest(db)
        history["fork"] = restore_check.history_fingerprint(db)
    result.update({
        "logical_transfer": {"supported": True},
        "logical_package_bytes": dir_bytes(ctx.package),
        "logical_rows_exported": exported.rows,
        "logical_rows_imported": imported.rows,
        "fork_counts": fork_counts,
        "fork_counts_match": fork_counts == original,
        "fork_verify_findings": len(fork_findings),
        "fork_new_uuid": fork_uuid != original_uuid,
    })
    result["integrity"] = integrity_summary(digests, history, result)
    result["digests"] = {k: v["tables"] for k, v in digests.items()}
    return result


def integrity_summary(digests, history, result):
    """Content digests, history and identity, original against restored and against the logical import."""
    out = {"digest_scope": "every property of every node and the endpoints of every relationship, all 10 tables; "
                           "native record ids and history timestamps are not part of it",
           "content_digest_original": digests["original"]["overall"],
           "tables_compared": len(digests["original"]["tables"]),
           "rows_hashed": sum(t["rows"] for t in digests["original"]["tables"].values()),
           "history_original": restore_check.summarise(history["original"])}
    if "restored" in digests:
        out.update({
            "content_digest_restored": digests["restored"]["overall"],
            "restored_digest_matches": digests["restored"]["overall"] == digests["original"]["overall"],
            "restored_differing_tables": digest.differing_tables(digests["original"], digests["restored"]),
            "history_restored": restore_check.summarise(history["restored"]),
            "history_survives_physical_restore": restore_check.history_preserved(history["original"], history["restored"]),
            "physical_restore_keeps_database_identity": result["restored_same_uuid"],
        })
    if "fork" in digests:
        out.update({
            "content_digest_fork": digests["fork"]["overall"],
            "fork_digest_matches": digests["fork"]["overall"] == digests["original"]["overall"],
            "fork_differing_tables": digest.differing_tables(digests["original"], digests["fork"]),
            "history_fork": restore_check.summarise(history["fork"]),
            "history_survives_logical_import": restore_check.history_preserved(history["original"], history["fork"]),
            "logical_import_gets_new_database_identity": result["fork_new_uuid"],
        })
    return out


# ---------------------------------------------------------------- step 10
def step10(ctx, html_path=None):
    from okto_grafx.html_snapshot import HtmlSnapshotLimits, render_html_snapshot
    from okto_grafx.projections import ProjectionLimits, project_graph

    customer_id = 1
    html_path = Path(html_path or ctx.state_dir / "customer-1-tickets.html")
    with connect(ctx.store) as db:
        customer = db.execute("MATCH (c:Customer {id: $id}) RETURN c.name", {"id": customer_id}).rows[0][0]
        tickets = db.execute("MATCH (c:Customer {id: $id})-[:Opened]->(t:Ticket) RETURN t.id, t.subject",
                             {"id": customer_id}).rows
        db.checkpoint()  # the CLI opens read-only and needs a checkpoint-complete store
    small = ctx.scratch / "customer-1"
    shutil.rmtree(small, ignore_errors=True)
    with connect(small) as db:
        with db.begin("write") as txn:
            txn.execute("CREATE NODE TABLE Customer(id INT64, name STRING, PRIMARY KEY(id))")
            txn.execute("CREATE NODE TABLE Ticket(id INT64, subject STRING, PRIMARY KEY(id))")
            txn.execute("CREATE REL TABLE Opened(FROM Customer TO Ticket)")
            txn.execute("CREATE (:Customer {id: $id, name: $name})", {"id": customer_id, "name": customer})
            txn.executemany("CREATE (:Ticket {id: $id, subject: $subject})",
                            [{"id": t[0], "subject": t[1]} for t in tickets])
            txn.executemany("MATCH (c:Customer {id: 1}), (t:Ticket {id: $id}) CREATE (c)-[:Opened]->(t)",
                            [{"id": t[0]} for t in tickets])
        graph = project_graph(db, node_tables=("Customer", "Ticket"), relationship_tables=("Opened",),
                              limits=ProjectionLimits(max_nodes=10000))
        schema = db.catalog.catalog
    html = render_html_snapshot(graph, catalog=schema, limits=HtmlSnapshotLimits(max_nodes=200, max_edges=500))
    html_path.write_text(html, encoding="utf-8")

    node = shutil.which("node")
    cli_doc = None
    if node:
        proc = subprocess.run([node, str(ROOT / "node" / "read_schema.mjs"), str(ctx.store), sys.executable],
                              capture_output=True, text=True, cwd=ROOT)
        if proc.returncode != 0:
            raise RuntimeError("node reader failed:\n" + proc.stdout + proc.stderr)
        cli_doc = json.loads(proc.stdout)
    return {
        "html_snapshot": html_path.name,
        "html_bytes": len(html.encode("utf-8")),
        "customer": customer,
        "customer_tickets": len(tickets),
        "snapshot_is_separate_small_store": True,
        "node_version": subprocess.run([node, "--version"], capture_output=True, text=True).stdout.strip() if node else None,
        "node_cli_schema": cli_doc,
    }


STEPS = {
    1: ("setup", step1), 2: ("first_load", step2), 3: ("two_writers", step3), 4: ("snapshot_reads", step4),
    5: ("kill_and_recover", step5), 6: ("full_text", step6), 7: ("hybrid", step7), 8: ("time_travel", step8),
    9: ("backup_restore", step9), 10: ("closeout", step10),
}
