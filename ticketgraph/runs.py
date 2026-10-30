"""Run identity: ids, manifests and run comparison.

Every complete execution gets a run id and a run-manifest.json next to its outputs. Reference results
(demo-state/) and new results (runs/<run id>/) live in different places, and nothing writes into a
folder that already holds a different run.
"""
import datetime
import json
import os
import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path

from .common import ROOT

MANIFEST = "run-manifest.json"
FAILURE = "failure.json"
RUN_ID_PATTERN = re.compile(r"^[0-9]{8}T[0-9]{6}Z-[0-9a-f]{7}(-dirty)?$|^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


def git_commit(root=ROOT):
    """{"sha", "dirty", "source"}. Order: DEMO_COMMIT_SHA (set by the Docker run), git, unknown."""
    env = os.environ.get("DEMO_COMMIT_SHA")
    if env:
        return {"sha": env, "dirty": os.environ.get("DEMO_GIT_DIRTY") == "1", "source": "environment"}
    if shutil.which("git"):
        try:
            sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, check=True).stdout.strip()
            dirty = bool(subprocess.run(["git", "status", "--porcelain"], cwd=root, capture_output=True, text=True,
                                        check=True).stdout.strip())
            return {"sha": sha, "dirty": dirty, "source": "git"}
        except (subprocess.CalledProcessError, OSError):
            pass
    return {"sha": None, "dirty": None, "source": "unknown"}


def new_run_id(commit=None, now=None):
    now = now or datetime.datetime.now(datetime.timezone.utc)
    commit = commit if commit is not None else git_commit()
    short = (commit["sha"] or "0000000")[:7]
    return f"{now.strftime('%Y%m%dT%H%M%SZ')}-{short}" + ("-dirty" if commit.get("dirty") else "")


def check_run_id(run_id):
    if not RUN_ID_PATTERN.match(run_id) or ".." in run_id:
        raise ValueError(f"bad run id {run_id!r}: use letters, digits, dot, dash, underscore (max 64)")
    return run_id


def sanitize_args(args):
    """Command-line arguments with absolute paths reduced to <path>/name, so manifests hold no machine paths."""
    out = []
    for a in args:
        if a.startswith("/") or re.match(r"^[A-Za-z]:\\\\", a):
            out.append("<path>/" + Path(a).name)
        else:
            out.append(a)
    return out


def node_version():
    node = shutil.which("node")
    if not node:
        return None
    try:
        return subprocess.run([node, "--version"], capture_output=True, text=True, check=True).stdout.strip()
    except (subprocess.CalledProcessError, OSError):
        return None


def pinned_grafx():
    path = ROOT / "requirements.txt"
    for line in path.read_text().splitlines():
        if line.startswith("okto-grafx=="):
            return line.split("==", 1)[1].strip()
    return None


def build_manifest(run_id, label, config, grafx_version):
    return {
        "run_id": run_id,
        "label": label,
        "status": "running",
        "started_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "finished_at": None,
        "grafx_version": grafx_version,
        "grafx_pinned_in_requirements": pinned_grafx(),
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "machine": platform.machine(),
        "in_container": Path("/.dockerenv").exists(),
        "node": node_version(),
        "commit": git_commit(),
        "config": config,
    }


def write_manifest(state_dir, manifest):
    Path(state_dir, MANIFEST).write_text(json.dumps(manifest, indent=1, sort_keys=True) + "\n", encoding="utf-8")


def load_manifest(state_dir):
    path = Path(state_dir, MANIFEST)
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def start_or_resume(state_dir, run_id, label, config, grafx_version):
    """Create the manifest, or continue an existing one of the SAME run. Refuses a folder of another run."""
    state_dir = Path(state_dir)
    existing = load_manifest(state_dir)
    if existing is not None:
        if existing["run_id"] != run_id:
            raise RuntimeError(f"{state_dir.name} holds run {existing['run_id']}, not {run_id}. "
                               "Use a new --run-id or --state-dir.")
        existing["status"] = "running"
        existing["finished_at"] = None
        existing["config"]["resumed_with"] = config
        write_manifest(state_dir, existing)
        return existing
    leftovers = sorted(p.name for p in state_dir.glob("step*.json")) if state_dir.exists() else []
    if leftovers:
        raise RuntimeError(f"{state_dir.name} already holds recorded outputs ({leftovers[0]} ...) from a run that has "
                           "no manifest, probably the committed reference. Refusing to overwrite it. "
                           "Choose another --state-dir, or pass --force-overwrite.")
    manifest = build_manifest(run_id, label, config, grafx_version)
    state_dir.mkdir(parents=True, exist_ok=True)
    write_manifest(state_dir, manifest)
    return manifest


def status_after(prior, complete_now):
    """Status once an invocation ends without failing. A run that was complete stays complete when a
    later invocation only adds to it (for example one more scenario)."""
    return "complete" if complete_now or prior == "complete" else "partial"


def finish(state_dir, status):
    manifest = load_manifest(state_dir)
    manifest["status"] = status
    manifest["finished_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    write_manifest(state_dir, manifest)


# ---------------------------------------------------------------- comparing two runs
TIMING = re.compile(r"(seconds|elapsed)")
CONTENTION = re.compile(r"conflict")
IDENTITY = re.compile(r"(^|[._\\[])(pids?|database_uuid)([._\\]]|$)|(^|_)csn(s)?$|_csn(\.|$)|(^|\.)pids?\.")
SIZE = re.compile(r"bytes")


def classify(key):
    """How much a difference in this key should worry you."""
    if TIMING.search(key):
        return "timing"
    if CONTENTION.search(key):
        return "contention"
    if IDENTITY.search(key):
        return "identity"
    if SIZE.search(key):
        return "size"
    return "invariant"


def flatten(value, prefix=""):
    out = {}
    if isinstance(value, dict):
        for k in sorted(value):
            out.update(flatten(value[k], f"{prefix}.{k}" if prefix else str(k)))
    elif isinstance(value, list) and all(not isinstance(v, (dict, list)) for v in value):
        out[prefix] = value
    elif isinstance(value, list):
        for i, v in enumerate(value):
            out.update(flatten(v, f"{prefix}[{i}]"))
    else:
        out[prefix] = value
    return out


def load_scoreboard(state_dir):
    path = Path(state_dir, "closeout-result.json")
    if not path.exists():
        raise FileNotFoundError(f"{state_dir} has no closeout-result.json")
    return json.loads(path.read_text(encoding="utf-8"))


def compare_runs(dir_a, dir_b):
    """Compare two runs by their scoreboards. Returns rows and a summary."""
    a, b = flatten(load_scoreboard(dir_a)), flatten(load_scoreboard(dir_b))
    rows = []
    for key in sorted(set(a) | set(b)):
        if key.startswith("run."):
            continue
        va, vb = a.get(key, "<missing>"), b.get(key, "<missing>")
        rows.append({"key": key, "a": va, "b": vb, "same": va == vb, "kind": classify(key)})
    differing = [r for r in rows if not r["same"]]
    summary = {
        "keys_compared": len(rows),
        "identical": len(rows) - len(differing),
        "differences_by_kind": {k: sum(1 for r in differing if r["kind"] == k)
                                for k in ("invariant", "contention", "timing", "identity", "size")},
    }
    ma, mb = load_manifest(dir_a), load_manifest(dir_b)
    manifest = {}
    for field in ("run_id", "label", "grafx_version", "python", "platform", "machine", "node", "in_container"):
        manifest[field] = {"a": (ma or {}).get(field, "<no manifest: reference run recorded before run ids>"),
                           "b": (mb or {}).get(field, "<no manifest: reference run recorded before run ids>")}
    manifest["commit"] = {"a": ((ma or {}).get("commit") or {}).get("sha", "<unknown>"),
                          "b": ((mb or {}).get("commit") or {}).get("sha", "<unknown>")}
    return {"manifest": manifest, "summary": summary, "rows": rows}
