"""Create the stored vectors once. The demo itself never loads this model.

Needs: pip install -r requirements-vectors.txt  (sentence-transformers, torch)
"""
import json
import resource
import sys
from pathlib import Path

import sentence_transformers
import torch
from sentence_transformers import SentenceTransformer

FIX = Path(__file__).resolve().parent.parent / "fixtures"
MODEL = "sentence-transformers/all-MiniLM-L6-v2"


def load(name):
    return [json.loads(line) for line in (FIX / name).read_text().splitlines()]


def main():
    model = SentenceTransformer(MODEL, device="cpu")
    tickets = []
    for f in ("tickets.jsonl", "tickets_late.jsonl", "tickets_crash.jsonl"):
        tickets += load(f)
    texts = [f"{t['subject']}. {t['body']}" for t in tickets]
    vecs = model.encode(texts, batch_size=64, normalize_embeddings=True, show_progress_bar=False)
    with open(FIX / "ticket_vectors.jsonl", "w") as out:
        for t, v in zip(tickets, vecs):
            out.write(json.dumps({"id": t["id"], "v": [round(float(x), 5) for x in v]}) + "\n")
    q = json.loads((FIX / "questions.json").read_text())
    items = q["keyword"] + q["phrase"]
    qv = model.encode([i["text"] for i in items], normalize_embeddings=True)
    (FIX / "question_vectors.json").write_text(json.dumps(
        {i["id"]: [round(float(x), 5) for x in v] for i, v in zip(items, qv)}) + "\n")
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    meta = {
        "model": MODEL,
        "dimension": int(vecs.shape[1]),
        "normalized": True,
        "rounded_decimals": 5,
        "sentence_transformers": sentence_transformers.__version__,
        "torch": torch.__version__,
        "python": sys.version.split()[0],
        "texts_encoded": len(texts) + len(items),
        "peak_rss_mb": round(peak / (1024 * 1024), 1),  # macOS reports bytes
    }
    (FIX / "vectors_meta.json").write_text(json.dumps(meta, indent=1) + "\n")
    print(meta)


if __name__ == "__main__":
    main()
