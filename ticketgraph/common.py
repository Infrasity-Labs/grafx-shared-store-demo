"""Shared helpers: fixture paths, loading, JSON output."""
import dataclasses
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "fixtures"


def read_jsonl(path):
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def load_vectors():
    """Ticket id -> stored 384-number vector."""
    return {row["id"]: row["v"] for row in read_jsonl(FIXTURES / "ticket_vectors.jsonl")}


def load_questions():
    return json.loads((FIXTURES / "questions.json").read_text(encoding="utf-8"))


def load_question_vectors():
    return json.loads((FIXTURES / "question_vectors.json").read_text(encoding="utf-8"))


def to_plain(obj):
    """Turn Grafx report objects into plain JSON-safe values."""
    if obj is None or isinstance(obj, (bool, int, float, str)):
        return obj
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {f.name: to_plain(getattr(obj, f.name)) for f in dataclasses.fields(obj)}
    if isinstance(obj, dict):
        return {str(k): to_plain(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set, frozenset)):
        return [to_plain(v) for v in obj]
    if isinstance(obj, Path):
        return obj.name
    if isinstance(obj, bytes):
        return obj.hex()
    return str(obj)


def dump_json(path, data):
    Path(path).write_text(json.dumps(to_plain(data), indent=1, sort_keys=True) + "\n", encoding="utf-8")
