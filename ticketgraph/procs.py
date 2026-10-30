"""Run a ticketgraph module as a separate process and collect what it printed."""
import subprocess
import sys

from .common import ROOT


def run_module(*args, expect=(0,)):
    """python -m ARGS. Returns (returncode, combined output). Raises if the code is not in expect."""
    proc = subprocess.run([sys.executable, "-m", *args], cwd=ROOT, stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT, text=True)
    if proc.returncode not in expect:
        raise RuntimeError(f"python -m {' '.join(args)} exited with {proc.returncode}:\n{proc.stdout}")
    return proc.returncode, proc.stdout


def run_modules_together(commands, expect=None):
    """Start several `python -m` commands at once and wait for all. commands: list of arg lists.

    expect: list of allowed return-code tuples, one per command (default (0,)).
    Returns a list of (returncode, output).
    """
    expect = expect or [(0,)] * len(commands)
    procs = [subprocess.Popen([sys.executable, "-m", *args], cwd=ROOT, stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT, text=True) for args in commands]
    results = []
    for proc, args, allowed in zip(procs, commands, expect):
        out, _ = proc.communicate()
        if proc.returncode not in allowed:
            raise RuntimeError(f"python -m {' '.join(args)} exited with {proc.returncode}:\n{out}")
        results.append((proc.returncode, out))
    return results
