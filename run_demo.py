#!/usr/bin/env python3
"""Replay the ten demo steps.

    python run_demo.py --steps 1 2 3 4
    python run_demo.py --start 5
    python run_demo.py --dry-run

--dry-run prints every command and needs no Grafx install.
"""
import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent

STEP_NAMES = {
    1: ("step01_setup.json", "Setup: schema, identity indexes, commit history, system history, verify"),
    2: ("step02_first_load.json", "First load: 40 articles, 25 customers, 5 products, 200 tickets, durable on every commit"),
    3: ("step03_two_writers.json", "Two writers at once: Importer A and B load 300 tickets, conflicts retried and counted"),
    4: ("step04_snapshot_reads.json", "Snapshot reads: an old read snapshot stays old while an importer commits"),
    5: ("step05_kill_and_recover.json", "Kill and recover: SIGKILL inside a write transaction, reopen, verify"),
    6: ("step06_full_text.json", "Full-text search: 10 keyword questions and 3 exact phrase questions"),
    7: ("step07_hybrid.json", "Hybrid search: same 10 questions with stored vectors and graph evidence"),
    8: ("step08_time_travel.json", "Time travel: correct one article, show before, after and diff"),
    9: ("step09_backup_restore.json", "Backup and restore, then logical export and import"),
    10: ("step10_closeout.json", "Close-out: HTML snapshot, Node schema reader, scoreboard"),
}

COMMANDS = {
    1: ["python -c 'create store, schema, ensure_identity_indexes, enable_commit_history, enable_system_history, verify(all)'"],
    2: ["python -m ticketgraph.importer --store STORE --name solo --static --slice 0 200 --batch 10 --out OUT"],
    3: ["python -m ticketgraph.importer --store STORE --name A --slice 200 500 --stride 2 0 --batch 10 --start-file GO --out OUT   (process 1)",
        "python -m ticketgraph.importer --store STORE --name B --slice 200 500 --stride 2 1 --batch 10 --start-file GO --out OUT   (process 2)"],
    4: ["python -m ticketgraph.searcher snapshot --store STORE --dir SIGNALS --out OUT   (holds a read snapshot)",
        "python -m ticketgraph.importer --store STORE --name A-late --tickets tickets_late.jsonl --batch 10 --out OUT"],
    5: ["python -m ticketgraph.importer --store STORE --name B-crash --tickets tickets_crash.jsonl --batch 10 --hold-last MARKER 600 --out OUT",
        "kill -9 <importer pid>   (while it holds its last transaction open)",
        "python -c 'connect(STORE) -> recovery_report, count tickets, verify(all)'"],
    6: ["python -c 'link Related edges, create_text_index ticket_text, search_text x10, search_text(phrase=True) x3'"],
    7: ["python -c 'search_hybrid x10 with stored vectors, graph evidence on and off'"],
    8: ["python -c 'system_as_of before, SET article body, system_as_of after, system_versions, system_diff'"],
    9: ["python -c 'create_backup -> stop all processes -> restore_backup(confirm_original_offline=True) -> verify'",
        "python -c 'export_graph(history=current-only) -> import_graph into a second store -> compare counts'"],
    10: ["python -c 'project_graph + render_html_snapshot for one customer'",
         "node node/read_schema.mjs STORE PYTHON   (reads the schema through the oktografx CLI)",
         "python -m ticketgraph.scoreboard   (builds closeout-result.json)"],
}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--steps", nargs="+", type=int, metavar="N", help="run only these steps")
    ap.add_argument("--start", type=int, metavar="N", help="run step N and every step after it")
    ap.add_argument("--dry-run", action="store_true", help="print the commands and exit")
    ap.add_argument("--workdir", default=str(ROOT / "live-store"), help="where the store, backup and restore live")
    ap.add_argument("--state-dir", default=str(ROOT / "demo-state"), help="where recorded outputs are written")
    args = ap.parse_args(argv)

    if args.steps:
        chosen = sorted(set(args.steps))
    elif args.start:
        chosen = list(range(args.start, 11))
    else:
        chosen = list(range(1, 11))
    bad = [n for n in chosen if n not in STEP_NAMES]
    if bad:
        ap.error(f"unknown step(s): {bad}. Steps are 1 to 10.")

    if args.dry_run:
        for n in chosen:
            print(f"Step {n}: {STEP_NAMES[n][1]}")
            for cmd in COMMANDS[n]:
                print(f"  $ {cmd}")
        print("Dry run only. Nothing was executed.")
        return 0

    # Grafx is imported only for a real run, so a dry run needs no install.
    sys.path.insert(0, str(ROOT))
    import okto_grafx
    from ticketgraph import scoreboard
    from ticketgraph.common import dump_json
    from ticketgraph.steps import STEPS, Ctx

    ctx = Ctx(args.workdir, args.state_dir)
    for n in chosen:
        name, fn = STEPS[n]
        print(f"Step {n}: {STEP_NAMES[n][1]}", flush=True)
        started = time.perf_counter()
        result = fn(ctx)
        elapsed = round(time.perf_counter() - started, 3)
        dump_json(ctx.state_dir / STEP_NAMES[n][0], {
            "step": n, "name": name, "grafx_version": okto_grafx.__version__,
            "elapsed_seconds": elapsed, "result": result})
        print(f"  done in {elapsed}s -> {STEP_NAMES[n][0]}", flush=True)
    if 10 in chosen:
        dump_json(ctx.state_dir / "closeout-result.json", scoreboard.build(ctx.state_dir))
        print("  scoreboard -> closeout-result.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
