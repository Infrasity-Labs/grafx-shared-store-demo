"""Create vectors for the evaluation questions and the workflow's incoming tickets.

Same model and settings as scripts/make_vectors.py, which made the ticket vectors. It writes only new
files and never touches ticket_vectors.jsonl or question_vectors.json:

    fixtures/eval_vectors.json        {"questions": {id: vector}, "incoming": {ticket id: vector}}
    fixtures/eval_vectors_meta.json   model, versions, and how far this run's vectors for the original
                                      13 questions are from the ones saved earlier

Needs: pip install -r requirements-vectors.txt
"""
import json
import sys
from pathlib import Path

import sentence_transformers
import torch
from sentence_transformers import SentenceTransformer

FIX = Path(__file__).resolve().parent.parent / "fixtures"
MODEL = "sentence-transformers/all-MiniLM-L6-v2"


def main():
    model = SentenceTransformer(MODEL, device="cpu")
    questions = json.loads((FIX / "eval_questions.json").read_text())["questions"]
    incoming = json.loads((FIX / "incoming_tickets.json").read_text())
    qv = model.encode([q["text"] for q in questions], normalize_embeddings=True, show_progress_bar=False)
    iv = model.encode([f"{t['subject']}. {t['body']}" for t in incoming], normalize_embeddings=True,
                      show_progress_bar=False)

    # Reproducibility check against vectors made earlier with the same model.
    old_q = json.loads((FIX / "question_vectors.json").read_text())
    old_items = json.loads((FIX / "questions.json").read_text())
    items = old_items["keyword"] + old_items["phrase"]
    again = model.encode([i["text"] for i in items], normalize_embeddings=True, show_progress_bar=False)
    worst = max(abs(float(a) - b) for i, v in zip(items, again) for a, b in zip(v, old_q[i["id"]]))

    (FIX / "eval_vectors.json").write_text(json.dumps({
        "questions": {q["id"]: [round(float(x), 5) for x in v] for q, v in zip(questions, qv)},
        "incoming": {str(t["id"]): [round(float(x), 5) for x in v] for t, v in zip(incoming, iv)},
    }) + "\n")
    meta = {
        "model": MODEL,
        "dimension": int(qv.shape[1]),
        "normalized": True,
        "rounded_decimals": 5,
        "sentence_transformers": sentence_transformers.__version__,
        "torch": torch.__version__,
        "python": sys.version.split()[0],
        "texts_encoded": len(questions) + len(incoming),
        "max_abs_diff_vs_saved_question_vectors": round(worst, 6),
        "note": "Saved question vectors were made with the versions in vectors_meta.json.",
    }
    (FIX / "eval_vectors_meta.json").write_text(json.dumps(meta, indent=1) + "\n")
    print(meta)


if __name__ == "__main__":
    main()
