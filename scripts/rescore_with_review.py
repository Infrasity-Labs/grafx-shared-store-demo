"""Re-score the retrieval evaluation with a reviewed answer key and compare it with the generated key.

The generated key (fixtures/eval_qrels.json) is computed from how the fixtures were made, not by a person. A reviewer
(a model or a human) can write a review file with, per question id, "remove" and "add" lists of ticket ids, as
fixtures/eval_qrels_model_review.json does. This script applies such a review to the ticket lists, runs the whole
evaluation again on a fresh store (it does not read the recorded runs), and writes both result sets side by side.
Articles are not changed. Nothing here edits a fixture.

Usage:
  python scripts/rescore_with_review.py [--review fixtures/eval_qrels_model_review.json] [--out OUT.json] [--workdir DIR]

The ranking is deterministic, so the "generated key" rows reproduce the recorded evaluation exactly.
"""
import argparse
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ticketgraph import common, evaluate  # noqa: E402

STRATEGIES = ("lexical", "hybrid", "hybrid_graph")


def apply_review(qrels, review):
    """Return a copy of qrels with each question's tickets changed by the review's remove and add lists."""
    revised = {}
    for qid, row in qrels.items():
        r = review.get(qid, {})
        removed = {x["id"] for x in r.get("remove", [])}
        added = {x["id"] for x in r.get("add", [])}
        revised[qid] = dict(row)
        revised[qid]["tickets"] = sorted((set(row["tickets"]) - removed) | added)
    return revised


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--review", default=str(ROOT / "fixtures" / "eval_qrels_model_review.json"))
    ap.add_argument("--out", default=None)
    ap.add_argument("--workdir", default=None)
    a = ap.parse_args()

    review = json.loads(Path(a.review).read_text(encoding="utf-8"))
    generated = common.load_eval_qrels()
    revised = apply_review(generated, review)
    work = Path(a.workdir) if a.workdir else Path(tempfile.mkdtemp(prefix="grafx-rescore-"))

    out = {
        "review_file": Path(a.review).name,
        "review_labeler": review.get("labeler"),
        "review_labeled_at": review.get("labeled_at"),
        "relevant_tickets_per_question": {
            "generated key": round(sum(len(v["tickets"]) for v in generated.values()) / len(generated), 2),
            "reviewed key": round(sum(len(v["tickets"]) for v in revised.values()) / len(revised), 2),
        },
        "results": {},
    }
    for name, qrels in (("generated key", generated), ("reviewed key", revised)):
        evaluate.load_eval_qrels = lambda q=qrels: q
        result = evaluate.run(workdir=work / name.replace(" ", "-"), out=None)
        out["results"][name] = {s: result["strategies"][s]["all"]["tickets"] for s in STRATEGIES}
        print("== " + name)
        for s in STRATEGIES:
            t = out["results"][name][s]
            print("  %-13s nDCG@10 %.3f  P@10 %.3f  R@10 %.3f  MRR %.3f" % (s, t["ndcg@10"], t["precision@10"], t["recall@10"], t["mrr"]))
    order = {name: sorted(STRATEGIES, key=lambda s: -rows[s]["ndcg@10"]) for name, rows in out["results"].items()}
    out["ranking_by_ndcg@10"] = order
    out["same_ranking"] = order["generated key"] == order["reviewed key"]
    print("ranking by nDCG@10:", order, "| same:", out["same_ranking"])
    if a.out:
        Path(a.out).write_text(json.dumps(out, indent=1, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
