"""End-to-end support workflow on the shared store. One command:

    python -m ticketgraph.workflow --out workflow.json [--workdir DIR | --store EXISTING_STORE] [--no-faults]

Two new tickets arrive. Separate processes, each with its own Grafx handle, do the work:

  intake x2 (at once)   persist the new ticket, link the customer and the product from the account
  triage x2 (at once)   search for similar tickets, follow the graph to the incident they belong to,
                        decide, and write the decision, suggested articles and incident link
  maintain              enrich the article that triage suggested, with a note drawn from the incident
  audit                 a separate process reads the article's previous state from system history and
                        reports what changed

With faults (the default) the maintainer is killed twice: inside its transaction before the commit, and
right after the commit was acknowledged. Each time the whole workflow is started again. Nothing is
done twice and nothing is lost: every stage's write carries a Checkpoint row in the same transaction.

Without --store a fresh store is built from the fixtures. With --store the workflow runs on an existing
demo store (for example the one steps 1 to 8 leave in live-store/graph); missing application tables,
the incident graph and the text index are added to it first.
"""
import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path

from okto_grafx import connect

from . import roles
from .appschema import committed_units, ensure_app_schema, ensure_ticket_text_index, load_incident_graph
from .common import FIXTURES, dump_json, read_jsonl
from .evaluate import build_eval_store
from .procs import run_modules_together
from .resumable import make_logger

TICKETS = (3001, 3002)


def prepare_existing_store(path):
    with connect(path) as db:
        have = db.execute("MATCH (t:Ticket) RETURN count(*)").rows[0][0]
        core = {t["id"] for t in read_jsonl(FIXTURES / "tickets.jsonl")}
        present = {r[0] for r in db.execute("MATCH (t:Ticket) WHERE t.id <= 500 RETURN t.id").rows}
        if core - present:
            raise RuntimeError(f"{path} does not hold the 500 core tickets ({len(core - present)} missing). "
                               "Run steps 1 to 3 of run_demo.py first, or omit --store.")
        created = ensure_app_schema(db)
        graph = load_incident_graph(db)
        index = ensure_ticket_text_index(db)
        db.checkpoint()
    return {"existing_store": True, "tickets_before": have, "app_tables_created": created,
            "incident_graph": graph, "text_index_created": index}


def state_snapshot(store, article_id=None):
    with connect(store) as db:
        out = {
            "new_tickets": {str(t): db.execute("MATCH (x:Ticket {id: $id}) RETURN count(*)", {"id": t}).rows[0][0]
                            for t in TICKETS},
            "opened_links": {str(t): db.execute("MATCH ()-[r:Opened]->(x:Ticket {id: $id}) RETURN count(*)",
                                                {"id": t}).rows[0][0] for t in TICKETS},
            "about_links": {str(t): db.execute("MATCH (x:Ticket {id: $id})-[r:About]->() RETURN count(*)",
                                               {"id": t}).rows[0][0] for t in TICKETS},
            "triage_rows": db.execute("MATCH (x:Triage) RETURN count(*)").rows[0][0],
            "workflow_checkpoints": sorted(committed_units(db, roles.JOB)),
            "verify_findings": len(db.verify("all").findings),
        }
        if article_id is not None:
            body, revision = db.execute("MATCH (a:Article {id: $id}) RETURN a.body, a.revision", {"id": article_id}).rows[0]
            out["article"] = {"id": article_id, "revision": revision, "body_chars": len(body)}
    return out


def noise_diagnostics(decisions):
    """After the fact, using the fixture's own flag: did a recorded link that is known to be wrong
    (kind misfiled) end up in a decision's evidence? The workflow itself cannot tell."""
    links = json.loads((FIXTURES / "incident_graph.json").read_text())["links"]
    product_of = {t["id"]: t["product_id"] for t in read_jsonl(FIXTURES / "tickets.jsonl")}
    out = {}
    for ticket, d in decisions.items():
        evidence = set(d["with_graph"].get("evidence_ticket_ids") or [])
        wrong = [l for l in links if l["kind"] == "misfiled" and (l["a"] in evidence or l["b"] in evidence)]
        out[str(ticket)] = {"misfiled_links_touching_evidence": [
            {"a": l["a"], "b": l["b"], "product_of_a": product_of[l["a"]], "product_of_b": product_of[l["b"]]}
            for l in wrong]}
    return out


def read_json(path):
    return json.loads(Path(path).read_text())


def run(workdir=None, store=None, out=None, faults=True):
    own = workdir is None
    workdir = Path(workdir or tempfile.mkdtemp(prefix="grafx-workflow-"))
    workdir.mkdir(parents=True, exist_ok=True)
    events = workdir / "workflow-events.jsonl"
    if events.exists():
        raise RuntimeError(f"{events} already exists. Use a new --workdir.")
    try:
        if store:
            store = str(Path(store).resolve())
            setup = prepare_existing_store(store)
        else:
            store = str(workdir / "support-store")
            if Path(store).exists():
                raise RuntimeError(f"{store} already exists. Use a new --workdir.")
            setup = dict(build_eval_store(store), existing_store=False)
        orchestrator_log = make_logger(str(events), "orchestrator")
        counter = {"n": 0}

        def role_cmd(role, tag, *extra):
            counter["n"] += 1
            out_file = workdir / f"{counter['n']:02d}-{role}-{tag}.json"
            args = ["ticketgraph.roles", role, "--store", store, "--events", str(events), "--out", str(out_file), *extra]
            return args, out_file

        def run_stage(stage, specs, crash_expected=None):
            """specs: list of (role, tag, extra args). Runs them together. Returns their results."""
            cmds = [role_cmd(role, tag, *extra) for role, tag, extra in specs]
            expect = [((-9,) if crash_expected == i else (0,)) for i in range(len(cmds))]
            orchestrator_log("stage_start", stage=stage, processes=len(cmds))
            codes = run_modules_together([c for c, _ in cmds], expect)
            results = []
            for (code, _), (_, out_file) in zip(codes, cmds):
                results.append({"returncode": code, "result": read_json(out_file) if out_file.exists() else None})
            orchestrator_log("stage_end", stage=stage, returncodes=[r["returncode"] for r in results])
            return results

        def one_pass(number, crash_kind):
            record = {"pass": number, "injected_fault": crash_kind, "stages": {}}
            record["stages"]["intake"] = run_stage("intake", [("intake", str(t), ("--ticket-id", str(t))) for t in TICKETS])
            record["stages"]["triage"] = run_stage("triage", [("triage", str(t), ("--ticket-id", str(t))) for t in TICKETS])
            maintain_specs = [("maintain", str(t), ("--ticket-id", str(t)) + (("--crash-at", crash_kind) if crash_kind and t == TICKETS[0] else ()))
                              for t in TICKETS]
            expected = 0 if crash_kind else None
            record["stages"]["maintain"] = run_stage("maintain", maintain_specs, crash_expected=expected)
            interrupted = any(r["returncode"] != 0 for r in record["stages"]["maintain"])
            record["interrupted"] = interrupted
            article = None
            for r in record["stages"]["maintain"]:
                if r["result"] and r["result"].get("article_id"):
                    article = r["result"]["article_id"]
            if article is None:
                with connect(store) as db:
                    rows = db.execute("MATCH (x:Triage {id: $id})-[:Suggests]->(a:Article) RETURN a.id ORDER BY a.id",
                                      {"id": TICKETS[0]}).rows
                article = rows[0][0] if rows else None
            record["article_id"] = article
            if not interrupted and article is not None:
                record["stages"]["audit"] = run_stage("audit", [("audit", str(article), ("--article-id", str(article)))])
            record["state_after"] = state_snapshot(store, article)
            return record

        with connect(store) as db:
            baseline_revisions = {r[0]: r[1] for r in db.execute("MATCH (a:Article) RETURN a.id, a.revision").rows}
        passes = []
        plan = ["before_commit", "after_commit", None] if faults else [None]
        decisions = {}
        for number, kind in enumerate(plan, start=1):
            record = one_pass(number, kind)
            passes.append(record)
            for r in record["stages"]["triage"]:  # a restarted pass skips triage, so keep the pass that did it
                if not r["result"]["skipped"]:
                    decisions[r["result"]["ticket_id"]] = r["result"]
        final = passes[-1]
        article = final["article_id"]
        with connect(store) as db:
            body = db.execute("MATCH (a:Article {id: $id}) RETURN a.body", {"id": article}).rows[0][0] if article else ""
            joins = db.execute("MATCH ()-[r:JoinsIncident]->() RETURN count(*)").rows[0][0]
        audit = (final["stages"].get("audit") or [{}])[0].get("result") or {}
        incident_names = {d["with_graph"]["incident"] for d in decisions.values() if d["with_graph"]["incident"]}
        note = roles.enrichment_note(sorted(incident_names)[0]) if incident_names else None
        events_list = [json.loads(x) for x in events.read_text().splitlines()]
        pids = {}
        for e in events_list:
            if e["actor"] != "orchestrator":
                pids.setdefault(e["actor"].split("-")[0], set()).add(e["pid"])
        state = final["state_after"]
        checks = {
            "each_new_ticket_exists_once": all(v == 1 for v in state["new_tickets"].values()),
            "no_duplicate_links": all(v == 1 for v in state["opened_links"].values())
                                  and all(v == 1 for v in state["about_links"].values()),
            "one_triage_row_per_ticket": state["triage_rows"] == len(TICKETS),
            "article_enriched_exactly_once": bool(article) and state["article"]["revision"] == baseline_revisions[article] + 1
                                             and body.count(note or "\0") == 1,
            "audit_found_the_change": bool(audit.get("changed")) and audit.get("sentences_added") == [note],
            "audit_saw_only_that_revision_step": audit.get("revision_after") == (audit.get("revision_before") or 0) + 1,
            "graph_changed_a_decision": any(d["graph_changed_decision"] for d in decisions.values()),
            "graph_did_not_change_every_decision": any(not d["graph_changed_decision"] for d in decisions.values()),
            "verify_clean": state["verify_findings"] == 0,
            "four_roles_ran_as_separate_processes": len(pids) == 4,
        }
        result = {
            "store": setup,
            "faults_injected": faults,
            "passes": passes,
            "decisions": {str(t): decisions[t] for t in sorted(decisions)},
            "audit": audit,
            "article_after": {"id": article, "revision": state["article"]["revision"],
                              "revision_before_workflow": baseline_revisions.get(article)},
            "joins_incident_rows": joins,
            "processes_by_role": {k: len(v) for k, v in sorted(pids.items())},
            "diagnostics": noise_diagnostics(decisions),
            "trace": [{k: v for k, v in e.items() if k != "t"} for e in events_list],
            "checks": checks,
            "ok": all(checks.values()),
        }
        if out:
            dump_json(out, {"result": result})
        return result
    finally:
        if own:
            shutil.rmtree(workdir, ignore_errors=True)


def report(result):
    for t, d in result["decisions"].items():
        w, b = d["with_graph"], d["text_and_vector_only"]
        print(f"ticket {t}: {d['ticket']['subject']!r}")
        print(f"  text and vector only: products {b['products']} -> {b['decision']['action']}"
              f"{', escalate' if b['decision']['escalate'] else ''}")
        print(f"  with graph:           products {w['products']} incident {w['incident']!r} -> {w['decision']['action']}"
              f"{', escalate' if w['decision']['escalate'] else ''}")
    for p in result["passes"]:
        print(f"pass {p['pass']}: fault {p['injected_fault']}, interrupted {p['interrupted']}, "
              f"article revision {p['state_after'].get('article', {}).get('revision')}, "
              f"checkpoints {len(p['state_after']['workflow_checkpoints'])}")
    a = result["audit"]
    if a.get("changed"):
        print(f"audit: article {a['article_id']} revision {a['revision_before']} -> {a['revision_after']}, "
              f"added: {a['sentences_added']}")
    print("checks:", ", ".join(f"{k}={v}" for k, v in result["checks"].items()))
    print("ok" if result["ok"] else "FAILED")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--workdir", help="default: a temp dir, removed after")
    ap.add_argument("--store", help="run on an existing demo store instead of building a fresh one")
    ap.add_argument("--no-faults", action="store_true", help="one clean pass, no SIGKILL")
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    result = run(args.workdir, args.store, args.out, faults=not args.no_faults)
    report(result)
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
