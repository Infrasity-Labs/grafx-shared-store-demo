"""Markdown tables for the README and docs, rendered from recorded scenario outputs (never typed by hand).

A block in a markdown file looks like

    <!-- generated:eval-summary run=20261030T101500Z-a5ad197 -->
    ...table...
    <!-- /generated -->

    python -m ticketgraph.render            check that every block equals what its run recorded
    python -m ticketgraph.render --write    rewrite the blocks

tests/test_readme_numbers.py runs the check, so a number in the README cannot drift from the JSON.
"""
import json
import re
import sys
from pathlib import Path

NAMES = {"lexical": "Lexical only", "hybrid": "Hybrid (lexical + vector)",
         "hybrid_graph": "Hybrid + graph (incident links)",
         "hybrid_graph_product_edges": "Ablation: hybrid + graph over same-product edges"}
GROUPS = (("all", "All 36 questions"), ("feature", "24 same-problem questions"),
          ("incident", "12 same-outage questions"))


def eval_tables(result, groups=GROUPS):
    """The ticket-level metrics, one table per question group, and the per-question graph comparison."""
    out = []
    for group, title in groups:
        ceiling = result["strategies"]["lexical"][group]["tickets"]["recall_ceiling@10"]
        out.append(f"**{title}** (best possible Recall@10 for any ranking: {ceiling:.3f})\n")
        out.append("| Strategy | P@5 | P@10 | R@10 | R@20 | MRR | nDCG@10 |")
        out.append("|---|---|---|---|---|---|---|")
        for name in NAMES:
            m = result["strategies"][name][group]["tickets"]
            out.append(f"| {NAMES[name]} | {m['precision@5']:.3f} | {m['precision@10']:.3f} | {m['recall@10']:.3f} | "
                       f"{m['recall@20']:.3f} | {m['mrr']:.3f} | {m['ndcg@10']:.3f} |")
        out.append("")
    c = result["graph_comparison"]
    out.append("Question by question, nDCG@10 of hybrid + graph against plain hybrid:\n")
    out.append("| Questions | Improved | Unchanged | Worse |")
    out.append("|---|---|---|---|")
    out.append(f"| All 36 | {c['counts']['improved']} | {c['counts']['unchanged']} | {c['counts']['worse']} |")
    for intent, title in (("feature", "24 same-problem"), ("incident", "12 same-outage")):
        b = c["by_intent"][intent]
        out.append(f"| {title} | {b['improved']} | {b['unchanged']} | {b['worse']} |")
    return "\n".join(out)


def sweep_table(result):
    """nDCG@10 of hybrid + graph at each tested graph weight, next to plain hybrid."""
    out = ["| Graph weight | All 36 | 24 same-problem | 12 same-outage |", "|---|---|---|---|"]
    h = result["strategies"]["hybrid"]
    out.append("| none (plain hybrid) | " + " | ".join(f"{h[g]['tickets']['ndcg@10']:.3f}" for g, _ in GROUPS) + " |")
    for weight, row in result["graph_weight_sweep"].items():
        out.append(f"| {weight} | " + " | ".join(f"{row[g]['ndcg@10']:.3f}" for g, _ in GROUPS) + " |")
    return "\n".join(out)


def workload_table(results):
    """One row per workload result: shape, throughput, conflicts, latency, integrity."""
    out = ["| Workload | Writers / readers | Contention | Records/s | Conflicts / attempts | Failed batches | "
           "Commit p50 / p95 / p99 (ms) | Read p95 (ms) | Reopen after SIGKILL (s) | Integrity |",
           "|---|---|---|---|---|---|---|---|---|---|"]
    for r in sorted(results, key=lambda x: x["config"]["name"]):
        cfg, lat, rd = r["config"], r["commit_latency_ms"], r["read_latency_ms"]
        out.append(
            f"| {cfg['name']} | {cfg['writers']} / {cfg['readers']} | {cfg['contention']}, {cfg['hot_records']} hot | "
            f"{r['throughput']['records_per_second']} | {r['conflicts']['total']} / {r['conflicts']['attempts_total']} | "
            f"{r['failed_or_exhausted']['batches']} | {lat['p50']} / {lat['p95']} / {lat['p99']} | {rd['p95']} | "
            f"{r['recovery']['reopen_seconds']} | {'ok' if r['integrity']['ok'] else 'FAILED'} |")
    return "\n".join(out)


def load_workloads(run_dir):
    return [json.loads(p.read_text())["result"] for p in sorted(Path(run_dir).glob("scenario_workload_*.json"))]


def block_text(name, run_dir):
    """The generated text of one named block, from the recorded outputs in run_dir."""
    run_dir = Path(run_dir)
    if name.startswith("eval"):
        result = json.loads((run_dir / "scenario_eval.json").read_text())["result"]
        if name == "eval-sweep":
            return sweep_table(result)
        return eval_tables(result, GROUPS[:1] if name == "eval-summary" else GROUPS)
    if name == "workloads":
        return workload_table(load_workloads(run_dir))
    raise ValueError(f"unknown block {name!r}")


BLOCK = re.compile(r"(<!-- generated:(?P<name>[a-z-]+) run=(?P<run>[A-Za-z0-9._-]+) -->\n)(?P<body>.*?)(\n<!-- /generated -->)",
                   re.DOTALL)


def render_file(path, runs_root, write=False):
    """Compare (or rewrite) every generated block of a markdown file with what the recorded run says.
    Returns the list of block names whose text differs."""
    path = Path(path)
    text = path.read_text(encoding="utf-8")
    stale = []

    def replace(m):
        fresh = block_text(m["name"], Path(runs_root) / m["run"])
        if fresh != m["body"]:
            stale.append(m["name"])
        return m.group(1) + fresh + m.group(5)

    new = BLOCK.sub(replace, text)
    if write and new != text:
        path.write_text(new, encoding="utf-8")
    return stale


def main(argv=None):
    """python -m ticketgraph.render [--write]  : check (or refresh) the generated blocks in README and docs."""
    args = list(argv if argv is not None else sys.argv[1:])
    write = "--write" in args
    root = Path(__file__).resolve().parent.parent
    bad = {}
    for path in [root / "README.md"] + sorted((root / "docs").glob("*.md")):
        stale = render_file(path, root / "runs", write=write)
        if stale:
            bad[str(path.relative_to(root))] = stale
    if bad and not write:
        print("generated blocks differ from the recorded run:", bad)
        return 1
    print("generated blocks " + ("refreshed" if write else "match the recorded runs"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
