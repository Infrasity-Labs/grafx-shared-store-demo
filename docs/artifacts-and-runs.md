# Runs, reference results and comparing them

## Two kinds of results

| Where | What it is | Written by |
|---|---|---|
| `demo-state/` | The **reference**: the Linux container run of 2026-10-26, and `demo-state/macos-arm64/` for macOS. Recorded before run ids existed. Never overwritten by a normal run. | Once, by hand. |
| `runs/<run id>/` | **New results**: one folder per execution, with a manifest. | `run_demo.py`, `run_scenarios.py`, `scripts/run_in_docker.sh`, the integration workflow. |

`run_demo.py` writes to `runs/<run id>/` by default and refuses to write into a folder that holds `step*.json` files but no manifest (the reference), unless you pass `--force-overwrite`. It also refuses a folder that belongs to a different run id.

## A run

```sh
python run_demo.py                                   # run id from the UTC time and the short commit
python run_demo.py --run-id my-check --label local   # your own id
python run_scenarios.py all --run-id my-check        # same id: the scenarios join the same folder
python run_demo.py --start 5 --run-id my-check       # continue a run
```

The run id looks like `20261030T101500Z-a5ad197`, with `-dirty` added if the working tree had uncommitted changes. CI uses `ci-<github run id>-<attempt>`.

`run-manifest.json` holds: run id and label, status (`running`, `partial`, `complete`, `failed`), start and finish time, Grafx version and the pin in `requirements.txt`, Python, platform, machine, whether it ran in a container, Node version, the commit (`sha`, `dirty`, and where it came from: `git`, the Docker build, or `unknown`) and the arguments the run was started with, with absolute paths reduced to `<path>/name`.

Every step output carries the run id. `closeout-result.json` has a `run` block (run id, manifest file, label, Grafx version, platform, Python, commit, the step files it summarises), and the scoreboard builder refuses step files that belong to a different run than the manifest. A failed step leaves `failure.json` (step, error, traceback).

The reference runs have no manifest. The scoreboard of such a folder has no `run` block, and the compare tool says "reference run recorded before run ids". Their commit is not known and is not guessed.

## Comparing two runs

```sh
python scripts/compare_runs.py demo-state runs/<run id>
python scripts/compare_runs.py runs/<a> runs/<b> --strict     # exit 1 if an invariant differs
```

It prints both manifests side by side and every scoreboard key that differs, labelled:

- **invariant**: counts, `verify` findings, booleans. A difference deserves a look.
- **contention**, **timing**, **identity**, **size**: expected to move between runs and machines (conflict counts, seconds, process ids, database ids, commit sequence numbers, byte counts).

Use it to compare Grafx versions: run `python run_demo.py` on each pin, then compare the two folders.

## Promoting a run to a reference

Nothing does this automatically. Copy the folder by hand and say so in [VERIFIED.md](VERIFIED.md). The Linux container reference in `demo-state/` stays the dated reference until all ten steps have been re-run on Linux and recorded that way.
