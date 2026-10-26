"""Repo checks: JSON files, relative links, em dashes, key-like strings, machine paths, compile."""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKIP_DIRS = {".venv", ".git", "live-store", "node_modules", "__pycache__"}
TEXT_SUFFIXES = {".py", ".md", ".json", ".jsonl", ".mjs", ".yml", ".yaml", ".svg", ".html", ".txt", ".sh",
                 ".example", ""}
EM_DASH = chr(0x2014)
KEY_PATTERNS = [r"sk-[A-Za-z0-9]{20,}", r"AKIA[0-9A-Z]{16}", r"ghp_[A-Za-z0-9]{30,}", r"xox[bp]-[A-Za-z0-9-]{10,}",
                r"hf_[A-Za-z0-9]{30,}", r"-----BEGIN [A-Z ]*PRIVATE KEY-----"]
MACHINE_PATHS = ["/Users/", "/home/runner/", "C:\\\\Users"]


def files():
    for path in sorted(ROOT.rglob("*")):
        if path.is_file() and not (set(path.relative_to(ROOT).parts) & SKIP_DIRS):
            yield path


def main():
    problems = []
    for path in files():
        rel = path.relative_to(ROOT)
        if path.suffix not in TEXT_SUFFIXES and path.name not in {"Dockerfile", "LICENSE"}:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if EM_DASH in text:
            problems.append(f"{rel}: em dash")
        for pat in KEY_PATTERNS:
            if re.search(pat, text):
                problems.append(f"{rel}: looks like a key ({pat})")
        for marker in MACHINE_PATHS:
            if marker in text and path.name != "check_repo.py":
                problems.append(f"{rel}: machine path {marker}")
        if path.suffix == ".json":
            try:
                json.loads(text)
            except ValueError as error:
                problems.append(f"{rel}: bad JSON ({error})")
        if path.suffix == ".jsonl":
            for n, line in enumerate(text.splitlines(), 1):
                try:
                    json.loads(line)
                except ValueError:
                    problems.append(f"{rel}:{n}: bad JSON line")
                    break
        if path.suffix == ".py":
            try:
                compile(text, str(rel), "exec")
            except SyntaxError as error:
                problems.append(f"{rel}: does not compile ({error})")
        if path.suffix == ".md":
            for target in re.findall(r"\]\(([^)#\s]+)(?:#[^)]*)?\)", text):
                if re.match(r"^[a-z]+:", target):
                    continue
                if not (path.parent / target).resolve().exists():
                    problems.append(f"{rel}: broken link {target}")
    if problems:
        print("\n".join(problems))
        print(f"{len(problems)} problem(s)")
        return 1
    print("repo checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
