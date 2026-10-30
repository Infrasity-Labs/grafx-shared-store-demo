"""CI check for the full integration run: every assertion reads a run folder that THIS run just wrote.

    python scripts/assert_full_run.py STATE_DIR [--summary FILE]

STATE_DIR must hold run-manifest.json and the outputs of run_demo.py (all ten steps) and of
run_scenarios.py all. It must not be the committed reference (demo-state/). Nothing here reads any
recorded output from the repository, so the checks say whether the demo works today, not whether it
worked once.

Step 9 (backup, restore, logical export and import) is expected to work on Linux and Windows. On another
platform Grafx refuses, and this script then expects exactly that refusal to be recorded.

Exits 1 and prints every failed check, grouped by step.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ticketgraph import runs  # noqa: E402
from ticketgraph.scoreboard import STEP_FILES  # noqa: E402

TABLES = {"Product", "Customer", "Article", "Ticket", "Opened", "Mentions", "About", "Covers", "Uses", "Related"}
STRATEGIES = {"lexical", "hybrid", "hybrid_graph", "hybrid_graph_product_edges"}


class Checks:
    def __init__(self):
        self.rows = []

    def check(self, group, name, condition, detail=""):
        self.rows.append((group, name, bool(condition), detail))

    @property
    def failures(self):
        return [r for r in self.rows if not r[2]]


def load(state, name):
    return json.loads((state / name).read_text(encoding="utf-8"))


def step(state, n):
    return load(state, STEP_FILES[n])["result"]


def check_run(state, c):
    manifest = runs.load_manifest(state)
    c.check("run", "manifest exists", manifest is not None)
    if manifest is None:
        return None
    c.check("run", "manifest status is complete", manifest["status"] == "complete", manifest["status"])
    c.check("run", "Grafx version equals the pin in requirements.txt",
            manifest["grafx_version"] == runs.pinned_grafx(), f"{manifest['grafx_version']} vs {runs.pinned_grafx()}")
    c.check("run", "no failure.json", not (state / runs.FAILURE).exists())
    ids = {n: load(state, STEP_FILES[n]).get("run_id") for n in STEP_FILES if (state / STEP_FILES[n]).exists()}
    c.check("run", "all ten step files exist", len(ids) == 10, str(sorted(ids)))
    c.check("run", "every step file carries this run's id", all(v == manifest["run_id"] for v in ids.values()))
    board = load(state, "closeout-result.json") if (state / "closeout-result.json").exists() else {}
    c.check("run", "scoreboard names this run", board.get("run", {}).get("run_id") == manifest["run_id"])
    return manifest


def check_steps(state, manifest, c):
    r1, r2, r3, r4 = (step(state, n) for n in (1, 2, 3, 4))
    c.check("step 1", "verify clean, 10 tables", r1["verify_findings"] == 0 and set(r1["tables"]) == TABLES)
    c.check("step 2", "200 tickets, all commits durable", r2["tickets_loaded"] == 200 and r2["all_durable"])
    c.check("step 2", "static counts", (r2["counts"]["articles"], r2["counts"]["customers"], r2["counts"]["products"]) == (40, 25, 5))
    c.check("step 3", "two writer processes", len(set(r3["pids"].values())) == 2)
    c.check("step 3", "store holds exactly the fixture tickets",
            r3["counts_after"]["tickets"] == r3["fixture_ticket_count"] == 500 and r3["lost_commits"] == 0
            and r3["unexpected_ids"] == 0)
    c.check("step 3", "all durable, verify clean", r3["all_durable"] and r3["verify_findings"] == 0)
    c.check("step 3", "conflict counts add up", r3["conflicts_total"] == sum(r3["conflicts_by_importer"].values()))
    c.check("step 4", "old snapshot unchanged, new read saw the commit", r4["old_snapshot_unchanged"] and r4["new_read_saw_commit"])
    r5 = step(state, 5)
    c.check("step 5", "SIGKILL: committed batches present, unfinished batch absent",
            r5["killed_returncode"] == -9 and r5["committed_found"] == r5["committed_expected"] == 20
            and r5["unfinished_found"] == 0)
    c.check("step 5", "verify clean and links of the committed tickets present",
            r5["verify_findings"] == 0 and r5["opened_links_for_crash_tickets"] == 20)
    r6, r7, r8 = step(state, 6), step(state, 7), step(state, 8)
    c.check("step 6", "10 keyword and 3 phrase questions all have hits",
            len(r6["keyword"]) == 10 and len(r6["phrase"]) == 3 and all(q["hits"] for q in r6["keyword"] + r6["phrase"]))
    c.check("step 6", "phrase results are phrase_verified", all(q["regime"] == "phrase_verified" for q in r6["phrase"]))
    c.check("step 7", "text column equals step 6 of this run",
            all(row["text_top5"] == [h["ticket_id"] for h in t["hits"]] for row, t in zip(r7["side_by_side"], r6["keyword"])))
    c.check("step 7", "hybrid complete for every question", all(q["regime"] == "complete" for q in r7["hybrid_results"]))
    c.check("step 8", "revision 1 then 2, joined versions, one updated row",
            r8["as_of_before"]["revision"] == 1 and r8["as_of_after"]["revision"] == 2 and len(r8["versions"]) == 2
            and r8["versions"][0]["system_to"] == r8["versions"][1]["system_from"]
            and [d["operation"] for d in r8["diff_rows"]] == ["updated"] and r8["verify_findings"] == 0)
    check_step9(step(state, 9), manifest, c)
    r10 = step(state, 10)
    c.check("step 10", "html snapshot without scripts",
            (state / r10["html_snapshot"]).exists() and "<script" not in (state / r10["html_snapshot"]).read_text().lower())
    c.check("step 10", "node reader sees all 10 tables",
            r10["node_cli_schema"] is not None and {t["name"] for t in r10["node_cli_schema"]["tables"]} == TABLES)


def check_step9(r9, manifest, c):
    plat = manifest["platform"].lower()
    supported = "linux" in plat or "windows" in plat
    if not supported:
        c.check("step 9", "platform limit recorded as a refusal, not a crash",
                r9["physical_backup"]["supported"] is False and r9["logical_transfer"]["supported"] is False,
                json.dumps(r9.get("physical_backup")))
        c.check("step 9", "content digest of the original was still taken", "content_digest_original" in r9["integrity"])
        return
    i = r9["integrity"]
    both = r9["physical_backup"]["supported"] and r9.get("logical_transfer", {}).get("supported")
    c.check("step 9", "physical backup and logical transfer supported", both, json.dumps(r9.get("physical_backup")))
    if not both:
        return
    c.check("step 9", "no demo process alive at restore", r9["processes_alive_at_restore"] == 0)
    c.check("step 9", "restore: verify clean, counts equal, same identity",
            r9["restored_verify_findings"] == 0 and r9["restored_counts_match"] and r9["restored_same_uuid"])
    c.check("step 9", "restore: content digest identical in all 10 tables",
            i["restored_digest_matches"] and i["restored_differing_tables"] == [] and i["tables_compared"] == 10)
    c.check("step 9", "restore: system history survives", i["history_survives_physical_restore"]
            and len(i["history_restored"]["article_versions"]) == len(i["history_original"]["article_versions"]) >= 2)
    c.check("step 9", "logical import: rows equal, verify clean, new identity",
            r9["logical_rows_exported"] == r9["logical_rows_imported"] and r9["fork_counts_match"]
            and r9["fork_verify_findings"] == 0 and r9["fork_new_uuid"])
    c.check("step 9", "logical import: content digest identical in all 10 tables",
            i["fork_digest_matches"] and i["fork_differing_tables"] == [])
    c.check("step 9", "logical import does NOT carry history (current-only)", i["history_survives_logical_import"] is False)


def check_scenarios(state, manifest, c):
    scenario_files = sorted(state.glob("scenario_*.json"))
    c.check("run", "scenario outputs exist and carry this run's id",
            len(scenario_files) >= 7 and all(load(state, p.name).get("run_id") == manifest["run_id"] for p in scenario_files),
            str(len(scenario_files)))
    ev = load(state, "scenario_eval.json")["result"]
    c.check("eval", "four strategies scored on the same questions",
            set(ev["strategies"]) == STRATEGIES and all(ev["strategies"][s]["all"]["questions"] == 36 for s in STRATEGIES))
    c.check("eval", "metrics are numbers between 0 and 1",
            all(0.0 <= v <= 1.0 for s in STRATEGIES for g in ev["strategies"][s].values()
                for part in ("tickets", "articles") for v in g[part].values()))
    c.check("eval", "labels are marked as not human reviewed", "Not reviewed by a human" in ev["setup"]["labels"])
    c.check("eval", "store built clean", ev["store_build"]["verify_findings"] == 0)
    c.check("eval", "every question got lexical hits and a graph seed",
            ev["lexical_empty_results"] == [] and ev["questions_without_lexical_seeds"] == [])
    rs = load(state, "scenario_resume.json")["result"]
    v = rs["final_verification"]
    c.check("resume", "interrupted twice: SIGKILL before commit and after commit acknowledgement",
            [p["returncode"] for p in rs["phases"]] == [-9, -9, 0, 0])
    c.check("resume", "final identities, content and relationships equal the fixture",
            v["ticket_ids_match_fixture"] and not v["content_mismatches"] and v["relationships_match_fixture"])
    c.check("resume", "no duplicate relationships, checkpoints complete, verify clean",
            v["duplicate_relationships"] == 0 and v["checkpoints_match_expected_units"] and v["verify_findings"] == 0)
    c.check("resume", "equals an uninterrupted control by content digest", rs["control"]["digests_match"])
    c.check("resume", "re-running a finished job changes nothing", rs["rerun_changed_nothing"])
    c.check("resume", "Grafx accepts duplicate links, refuses a blind replay of a batch",
            rs["duplicate_link_probe"]["grafx_accepted_duplicate_links"]
            and rs["duplicate_link_probe"]["blind_replay_of_whole_batch"]["refused"])
    wf = load(state, "scenario_workflow.json")["result"]
    c.check("workflow", "every workflow check passed", wf["ok"],
            ", ".join(k for k, ok in wf["checks"].items() if not ok))
    c.check("workflow", "two interruptions then completion", [p["interrupted"] for p in wf["passes"]] == [True, True, False])
    for path in sorted(state.glob("scenario_workload_*.json")):
        w = json.loads(path.read_text())["result"]
        c.check("workload", f"{w['config']['name']}: integrity ok", w["integrity"]["ok"],
                ", ".join(k for k, ok in w["integrity"]["checks"].items() if not ok))
    c.check("workload", "at least one low- and one high-contention workload ran",
            {json.loads(p.read_text())["result"]["config"]["contention"] for p in state.glob("scenario_workload_*.json")}
            == {"disjoint", "shared"})


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    summary = None
    if "--summary" in args:
        i = args.index("--summary")
        summary = Path(args[i + 1])
        del args[i:i + 2]
    if len(args) != 1:
        print(__doc__)
        return 2
    state = Path(args[0]).resolve()
    if state == (ROOT / "demo-state").resolve() or ROOT / "demo-state" in state.parents:
        print("refusing to check the committed reference: this script checks a run made just now")
        return 2
    c = Checks()
    manifest = check_run(state, c)
    if manifest is not None and not c.failures:
        check_steps(state, manifest, c)
        check_scenarios(state, manifest, c)
    lines = [f"{'ok  ' if ok else 'FAIL'} [{group}] {name}" + (f" ({detail})" if detail and not ok else "")
             for group, name, ok, detail in c.rows]
    print("\n".join(lines))
    print(f"{len(c.rows) - len(c.failures)} of {len(c.rows)} checks passed")
    if summary:
        with open(summary, "a", encoding="utf-8") as handle:
            handle.write(f"### Full integration run {manifest['run_id'] if manifest else ''}\n\n"
                         f"{len(c.rows) - len(c.failures)} of {len(c.rows)} checks passed.\n\n")
            for group, name, ok, detail in c.failures:
                handle.write(f"- FAILED [{group}] {name} {detail}\n")
    return 1 if c.failures else 0


if __name__ == "__main__":
    sys.exit(main())
