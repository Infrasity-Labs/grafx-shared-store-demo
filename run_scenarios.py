#!/usr/bin/env python3
"""Run the scenarios that go beyond the ten steps. Each writes one JSON file into the run's folder.

    python run_scenarios.py eval        retrieval evaluation: lexical vs hybrid vs hybrid + graph
    python run_scenarios.py resume      resumable import: killed twice, restarted, verified
    python run_scenarios.py workflow    end-to-end support workflow, several processes, graph decision, audit
    python run_scenarios.py workload    opt-in concurrency workloads (small configs by default)
    python run_scenarios.py all         eval, resume, workflow and the small workloads

    --state-dir DIR   where outputs go (default runs/<run id>/); --run-id ID continues a run, so that
                      the ten steps (run_demo.py --run-id ID) and the scenarios can share one folder.

Needs only the pinned Grafx. Nothing here calls a model or the network.
"""
import argparse
import sys
import tempfile
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

SCENARIOS = ("eval", "resume", "workflow", "workload")
DEFAULT_WORKLOADS = ["disjoint-small", "disjoint-4w-small", "shared-wide-small", "shared-hot-small"]


def write(state_dir, run_id, name, grafx_version, elapsed, result, file_name=None):
    from ticketgraph.common import dump_json
    file_name = file_name or f"scenario_{name}.json"
    dump_json(Path(state_dir) / file_name, {"scenario": name, "run_id": run_id, "grafx_version": grafx_version,
                                            "elapsed_seconds": elapsed, "result": result})
    return file_name


def run_eval(state_dir, run_id, version, workdir):
    from ticketgraph import evaluate
    started = time.perf_counter()
    result = evaluate.run(workdir=Path(workdir) / "eval", out=None)
    evaluate.show(result)
    f = write(state_dir, run_id, "eval", version, round(time.perf_counter() - started, 3), result)
    return f, True


def run_resume(state_dir, run_id, version, workdir):
    from ticketgraph import resume_demo
    started = time.perf_counter()
    result = resume_demo.run(workdir=Path(workdir) / "resume", out=None)
    for p in result["phases"]:
        s = p["state_after"]
        print(f"  {p['phase']}: exit {p['returncode']}, tickets {s['tickets']}, checkpoints {len(s['committed_units'])}")
    v = result["final_verification"]
    print(f"  final: {v['ticket_count']} tickets, duplicate relationships {v['duplicate_relationships']}, "
          f"matches uninterrupted control {result['control']['digests_match']}, ok={result['ok']}")
    f = write(state_dir, run_id, "resume", version, round(time.perf_counter() - started, 3), result)
    return f, result["ok"]


def run_workflow(state_dir, run_id, version, workdir, store=None):
    from ticketgraph import workflow
    started = time.perf_counter()
    result = workflow.run(workdir=Path(workdir) / "workflow", store=store, out=None, faults=True)
    workflow.report(result)
    f = write(state_dir, run_id, "workflow", version, round(time.perf_counter() - started, 3), result,
              "scenario_workflow_on_demo_store.json" if store else None)
    return f, result["ok"]


def run_workloads(state_dir, run_id, version, workdir, configs, allow_large=False):
    from ticketgraph import workload
    ok_all, files = True, []
    for config_path in configs:
        path = Path(config_path)
        if not path.exists():
            path = ROOT / "workloads" / f"{config_path}.json"
        config = workload.load_config(path, allow_large=allow_large)
        started = time.perf_counter()
        result = workload.run_workload(config, Path(workdir) / f"workload-{config['name']}", allow_large=allow_large)
        tp, ok = result["throughput"], result["integrity"]["ok"]
        print(f"  {config['name']}: {tp['records_per_second']} records/s, {result['conflicts']['total']} conflicts in "
              f"{result['conflicts']['attempts_total']} attempts, {result['failed_or_exhausted']['batches']} failed batches, "
              f"p95 commit {result['commit_latency_ms']['p95']} ms, integrity ok={ok}")
        files.append(write(state_dir, run_id, f"workload:{config['name']}", version,
                           round(time.perf_counter() - started, 3), result, f"scenario_workload_{config['name']}.json"))
        ok_all = ok_all and ok
    return files, ok_all


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("scenario", choices=list(SCENARIOS) + ["all"])
    ap.add_argument("--state-dir")
    ap.add_argument("--run-id")
    ap.add_argument("--label", default="local")
    ap.add_argument("--workdir", help="default: a temp dir, removed after")
    ap.add_argument("--store", help="workflow only: run on an existing demo store instead of a fresh one")
    ap.add_argument("--config", action="append", help="workload only: config name or path (repeatable)")
    ap.add_argument("--allow-large", action="store_true", help="workload only: lift the 200000-record guard")
    ap.add_argument("--force-overwrite", action="store_true")
    args = ap.parse_args(argv)

    import okto_grafx
    from ticketgraph import runs

    run_id = runs.check_run_id(args.run_id) if args.run_id else runs.new_run_id()
    state_dir = Path(args.state_dir) if args.state_dir else ROOT / "runs" / run_id
    chosen = list(SCENARIOS) if args.scenario == "all" else [args.scenario]
    config = {"scenarios": chosen, "arguments": runs.sanitize_args(sys.argv[1:] if argv is None else list(argv))}
    prior = (runs.load_manifest(state_dir) or {}).get("status")
    if args.force_overwrite and runs.load_manifest(state_dir) is None:
        state_dir.mkdir(parents=True, exist_ok=True)
        runs.write_manifest(state_dir, runs.build_manifest(run_id, args.label, config, okto_grafx.__version__))
    else:
        runs.start_or_resume(state_dir, run_id, args.label, config, okto_grafx.__version__)
    print(f"Run {run_id} -> {state_dir}", flush=True)

    own = args.workdir is None
    workdir = tempfile.mkdtemp(prefix="grafx-scenarios-") if own else args.workdir
    Path(workdir).mkdir(parents=True, exist_ok=True)
    version = okto_grafx.__version__
    failed = []
    try:
        for name in chosen:
            print(f"Scenario {name}", flush=True)
            try:
                if name == "eval":
                    _, ok = run_eval(state_dir, run_id, version, workdir)
                elif name == "resume":
                    _, ok = run_resume(state_dir, run_id, version, workdir)
                elif name == "workflow":
                    _, ok = run_workflow(state_dir, run_id, version, workdir, args.store)
                else:
                    _, ok = run_workloads(state_dir, run_id, version, workdir, args.config or DEFAULT_WORKLOADS,
                                          args.allow_large)
            except BaseException as error:
                from ticketgraph.common import dump_json
                dump_json(Path(state_dir) / runs.FAILURE, {"run_id": run_id, "scenario": name,
                                                           "error_type": type(error).__name__, "message": str(error),
                                                           "traceback": traceback.format_exc()})
                runs.finish(state_dir, "failed")
                print(f"FAILED in scenario {name}: {type(error).__name__}: {error}", file=sys.stderr, flush=True)
                raise
            print(f"  {name}: {'ok' if ok else 'FAILED'}", flush=True)
            if not ok:
                failed.append(name)
    finally:
        if own:
            import shutil
            shutil.rmtree(workdir, ignore_errors=True)
    runs.finish(state_dir, "failed" if failed else runs.status_after(prior, args.scenario == "all"))
    if failed:
        print(f"Scenario checks failed: {', '.join(failed)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
