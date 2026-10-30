# Verified

| Item | Value |
|---|---|
| Date | 2026-10-26 |
| Okto Grafx | 0.0.8 (`okto-grafx==0.0.8`, from PyPI) |
| Main record | Linux container, Python 3.12.14, Node v22.23.4, on an Apple silicon laptop (Docker Desktop). Store on the container's own disk. |
| Extra record | macOS (Darwin, arm64), Python 3.12.14, Node v26.8.1. Kept in `demo-state/macos-arm64/`. |
| Newer local record | Run `20261029T190205Z-a5ad197-dirty`: macOS 26.3 arm64, Python 3.12.14, Node v26.8.1. All ten steps (step 9 refused, as on macOS before) and every scenario. Kept in `runs/20261029T190205Z-a5ad197-dirty/`; its manifest says the working tree was uncommitted ("dirty") on top of commit a5ad197. |
| Embedding model | `sentence-transformers/all-MiniLM-L6-v2`, sentence-transformers 6.2.0, torch 2.14.1 for the ticket vectors. The evaluation question vectors were made later with torch 2.15.0 and reproduced the earlier question vectors to 5e-06 (`fixtures/eval_vectors_meta.json`). |

Only this version was verified. Grafx is pre-alpha. Another version may behave differently.

## What was and was not run

- All ten steps ran in the Linux container (2026-10-26) and passed their checks. Outputs are in `demo-state/`. That is the **reference**.
- All ten steps ran again in the Linux container on 2026-10-29 as `runs/20261029T191341Z-a5ad197-dirty/` (`scripts/run_in_docker.sh`, Docker Desktop on an Apple silicon laptop). Step 9 there records the new content digests: the original, the physical restore and the logical fork have the same digest over 3,240 rows in 10 tables, the history of article 25 (two versions, 88 commit entries) is identical after a physical restore, the physical restore keeps the database identity, and the logical import gets a new identity and keeps no commit history.
- On macOS, steps 1 to 8 and 10 ran and passed twice (`demo-state/macos-arm64/` and `runs/20261029T190205Z-a5ad197-dirty/`). Step 9 was refused by Grafx on that host (see below).
- The scenarios (retrieval evaluation, resumable import, support workflow, workloads) ran on macOS, in `runs/20261029T190205Z-a5ad197-dirty/`, and again on macOS into the Linux run folder `runs/20261029T191341Z-a5ad197-dirty/` so that one folder holds the ten Linux steps and the scenarios. They do not need Linux. `scripts/assert_full_run.py` passed 51 of 51 checks on that folder, with step 9 required to work.
- Windows was not run.
- The `validate` workflow (`.github/workflows/validate.yml`) has run on GitHub Actions. A reviewer of 2026-10-29 reported that its latest run completed successfully. That run record lives on the repository's Actions tab and is not copied here, so this repo does not re-check it. An earlier version of this page said the workflow had not run on GitHub. That was out of date.
- The `integration` workflow (`.github/workflows/integration.yml`) is new. It has **not run on GitHub yet**. Its commands were run by hand: `run_demo.py` in the Linux container, then `run_scenarios.py all` and `scripts/assert_full_run.py` against the same run folder (51 of 51 checks passed). The first hand run, on macOS only, passed 45 of 45 checks with step 9 expected to be refused.
- The workflow actions are referenced by tag (`@v4`, `@v5`), not pinned to commit SHAs, because no trustworthy local source for the SHAs was available.

## Where Grafx behaved differently from what we expected

These are findings from the real runs. None contradicts the Grafx docs, but some contradicted the plan for this repo.

1. **macOS refuses physical backup and logical export.** Both end in a directory publish that needs `renameat2` on Linux or `MoveFileExW` on Windows. On macOS the call raised `GrafxUnsupportedOperation: This platform has no supported atomic no-replace directory publication.` The Grafx backup doc says unsupported hosts refuse. The plan had assumed Linux and macOS would both work. Step 9 is therefore recorded from Linux.
2. **A read-only open needs a checkpoint-complete store.** `oktografx schema` on a store that had commits after its last checkpoint refused with `read_only_consistency`. The Operations doc describes this. The demo calls `checkpoint()` first.
3. **Export of a store with system history needs `history="current-only"`.** The default `history="refuse"` raises. The history itself is not exported.
4. **Hybrid graph evidence only follows relationships from the search table to itself.** For that reason the demo adds a `Ticket` to `Ticket` table named `Related`.
5. **The docs describe 0.0.5 and 0.0.6 development revisions.** The installed 0.0.8 matched every API used here. Where the installed signature and the docs differed in detail (for example `export_graph` has a `history` argument that the main example omits), the installed version was used.
6. **Conflict counts vary.** Step 3 counted 6 conflicts on macOS and 7 in Linux in the reference runs, and 12 in `runs/20261029T190205Z-a5ad197-dirty/`. This depends on timing.

Later findings, with their evidence, are in [PRODUCT-OBSERVATIONS.md](PRODUCT-OBSERVATIONS.md).

## Version-specific limits

The limits of Grafx 0.0.8 that this repo works around or depends on. When the pin changes, each row says how to see whether it still holds.

| Limit on 0.0.8 | How a run shows it | Recorded in |
|---|---|---|
| macOS refuses physical backup and logical export | Step 9 records `physical_backup.supported: false` on macOS. `assert_full_run.py` expects that on macOS and expects success on Linux and Windows. | `demo-state/macos-arm64/step09_backup_restore.json`, `runs/20261029T190205Z-a5ad197-dirty/step09_backup_restore.json` |
| Export of a store with system history needs `history="current-only"`, and a logical import keeps no history | Step 9 records `integrity.history_survives_logical_import`, and `assert_full_run.py` (Linux) fails if it turns true, so a change is noticed | `runs/20261029T191341Z-a5ad197-dirty/step09_backup_restore.json` (`history_survives_logical_import: false`, `history_survives_physical_restore: true`) |
| Hybrid graph evidence only re-ranks candidates the text or vector index proposed, and its relations must join the table to itself | The evaluation records graph results next to plain hybrid | `runs/20261029T190205Z-a5ad197-dirty/scenario_eval.json` |
| Write conflicts are per partition | Workloads record conflicts for writers on private records | `runs/20261029T190205Z-a5ad197-dirty/scenario_workload_disjoint-small.json` |
| A relationship can be created twice | `duplicate_link_probe` | `runs/20261029T190205Z-a5ad197-dirty/scenario_resume.json` |
| A read-only open needs a checkpoint-complete store | Step 10 calls `checkpoint()` first; without it `oktografx schema` refuses with `read_only_consistency` | `demo-state/` step 10 |

After a Grafx bump: change `requirements.txt`, run `python run_demo.py && python run_scenarios.py all` on Linux (or let `integration.yml` do it), read any failed check, compare with the previous run using `python scripts/compare_runs.py`, then update this file and [PRODUCT-OBSERVATIONS.md](PRODUCT-OBSERVATIONS.md). `scripts/check_repo.py` fails until both name the new version.

## Not measured

- Whether the graph makes search better in general. On the labelled evaluation it did not improve on plain hybrid search. The labels were computed from the fixtures and not reviewed by a person ([retrieval-evaluation.md](retrieval-evaluation.md)).
- Speed against any other database. No comparison was run.
- Behavior on a network share, on Windows, with more than 4 writers, or with stores larger than a few MB. The large workload configs exist and have never been run.
- Crashes other than SIGKILL of one process.
