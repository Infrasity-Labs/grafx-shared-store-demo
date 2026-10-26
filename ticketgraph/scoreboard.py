"""Build demo-state/closeout-result.json from the recorded step outputs only."""
import json
from pathlib import Path

STEP_FILES = {
    1: "step01_setup.json", 2: "step02_first_load.json", 3: "step03_two_writers.json",
    4: "step04_snapshot_reads.json", 5: "step05_kill_and_recover.json", 6: "step06_full_text.json",
    7: "step07_hybrid.json", 8: "step08_time_travel.json", 9: "step09_backup_restore.json",
    10: "step10_closeout.json",
}


def load_steps(state_dir):
    state_dir = Path(state_dir)
    out = {}
    for number, name in STEP_FILES.items():
        path = state_dir / name
        if path.exists():
            out[number] = json.loads(path.read_text(encoding="utf-8"))
    return out


def top_ids(results):
    return {r["id"]: (r["hits"][0]["ticket_id"] if r["hits"] else None) for r in results}


def build(state_dir):
    s = load_steps(state_dir)
    board = {"steps_recorded": sorted(s)}

    if 2 in s and 3 in s:
        r2, r3, r5, r4 = s[2]["result"], s[3]["result"], s.get(5, {}).get("result", {}), s.get(4, {}).get("result", {})
        board["tickets"] = {
            "step2_loaded": r2["tickets_loaded"],
            "step3_loaded": r3["tickets_loaded"],
            "core_fixture_count": r3["fixture_ticket_count"],
            "core_count_in_store_after_step3": r3["counts_after"]["tickets"],
            "core_count_matches_fixture": r3["counts_after"]["tickets"] == r3["fixture_ticket_count"],
            "step4_late_batch_loaded": r4.get("late_tickets_loaded"),
            "step5_committed_before_kill": r5.get("committed_found"),
            "final_ticket_count": s.get(9, {}).get("result", {}).get("counts_original", {}).get("tickets"),
        }
        board["writers"] = {
            "conflicts_by_importer": r3["conflicts_by_importer"],
            "conflicts_total": r3["conflicts_total"],
            "all_commits_durable": r2["all_durable"] and r3["all_durable"],
            "lost_commits": r3["lost_commits"],
        }
    if 4 in s:
        r = s[4]["result"]
        board["stale_snapshot"] = {
            "old_snapshot_tickets_before": r["old_before"]["tickets"],
            "old_snapshot_tickets_after_commit": r["old_after"]["tickets"],
            "new_read_tickets": r["new_read"]["tickets"],
            "old_snapshot_unchanged": r["old_snapshot_unchanged"],
            "new_read_saw_commit": r["new_read_saw_commit"],
        }
    if 5 in s:
        r = s[5]["result"]
        board["crash"] = {
            "signal": r["signal"],
            "committed_tickets_found": r["committed_found"],
            "committed_expected": r["committed_expected"],
            "unfinished_batch_found": r["unfinished_found"],
            "verify_findings": r["verify_findings"],
            "recovery_outcome": r["recovery_outcome"],
        }
    if 6 in s:
        r = s[6]["result"]
        board["text_search"] = {"keyword_questions": len(r["keyword"]), "phrase_questions": len(r["phrase"]),
                                "keyword_with_hits": sum(1 for q in r["keyword"] if q["hits"]),
                                "phrase_with_hits": sum(1 for q in r["phrase"] if q["hits"])}
    if 7 in s:
        r = s[7]["result"]
        board["hybrid"] = {k: r[k] for k in ("questions", "top1_changed_with_graph", "top1_changed_no_graph",
                                              "top5_set_changed_with_graph", "text_top1_tied_with_top2")}
    if 8 in s:
        board["article_diff"] = s[8]["result"]
    if 9 in s:
        board["backup_restore"] = {k: s[9]["result"][k] for k in s[9]["result"] if k != "counts_original"}
    board["seconds_by_step"] = {str(n): s[n]["elapsed_seconds"] for n in sorted(s)}
    return board


if __name__ == "__main__":
    import sys
    from .common import dump_json
    state = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent / "demo-state"
    dump_json(state / "closeout-result.json", build(state))
