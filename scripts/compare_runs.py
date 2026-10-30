"""Compare two runs by their closeout scoreboards.

    python scripts/compare_runs.py demo-state runs/20261030T101500Z-abc1234
    python scripts/compare_runs.py A B --all          also list identical keys
    python scripts/compare_runs.py A B --json         machine-readable
    python scripts/compare_runs.py A B --strict       exit 1 if any 'invariant' key differs

Differences are labelled. invariant: counts, verify findings, booleans (a difference here deserves a look).
timing, contention, identity, size: expected to move between runs and machines.
A run without run-manifest.json is a reference recorded before run ids existed.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ticketgraph.runs import compare_runs  # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("a")
    ap.add_argument("b")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    report = compare_runs(args.a, args.b)
    if args.json:
        print(json.dumps(report, indent=1, sort_keys=True))
    else:
        print("run A:", args.a)
        print("run B:", args.b)
        for field, v in report["manifest"].items():
            print(f"  {field:14s} A={v['a']}  B={v['b']}")
        for r in report["rows"]:
            if r["same"] and not args.all:
                continue
            print(f"  [{r['kind']:10s}] {r['key']}: {r['a']!r}  ->  {r['b']!r}" if not r["same"]
                  else f"  [same      ] {r['key']}: {r['a']!r}")
        s = report["summary"]
        print(f"{s['keys_compared']} keys compared, {s['identical']} identical, differences: {s['differences_by_kind']}")
    if args.strict and report["summary"]["differences_by_kind"]["invariant"]:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
