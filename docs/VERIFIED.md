# Verified

| Item | Value |
|---|---|
| Date | 2026-10-26 |
| Okto Grafx | 0.0.8 (`okto-grafx==0.0.8`, from PyPI) |
| Main record | Linux container, Python 3.12.14, Node v22.23.4, on an Apple silicon laptop (Docker Desktop). Store on the container's own disk. |
| Extra record | macOS (Darwin, arm64), Python 3.12.14, Node v26.8.1. Kept in `demo-state/macos-arm64/`. |
| Embedding model | `sentence-transformers/all-MiniLM-L6-v2`, sentence-transformers 6.2.0, torch 2.14.1 |

Only this version was verified. Grafx is pre-alpha. Another version may behave differently.

## What was and was not run

- All ten steps ran in the Linux container and passed their checks. Outputs are in `demo-state/`.
- On macOS, steps 1 to 8 and 10 ran and passed. Step 9 was refused by Grafx on that host (see below).
- Windows was not run.
- The GitHub Actions workflow in `.github/workflows/validate.yml` has not run on GitHub. Its commands were run by hand from a fresh clone.

## Where Grafx behaved differently from what we expected

These are findings from the real runs. None contradicts the Grafx docs, but some contradicted the plan for this repo.

1. **macOS refuses physical backup and logical export.** Both end in a directory publish that needs `renameat2` on Linux or `MoveFileExW` on Windows. On macOS the call raised `GrafxUnsupportedOperation: This platform has no supported atomic no-replace directory publication.` The Grafx backup doc says unsupported hosts refuse. The plan had assumed Linux and macOS would both work. Step 9 is therefore recorded from Linux.
2. **A read-only open needs a checkpoint-complete store.** `oktografx schema` on a store that had commits after its last checkpoint refused with `read_only_consistency`. The Operations doc describes this. The demo calls `checkpoint()` first.
3. **Export of a store with system history needs `history="current-only"`.** The default `history="refuse"` raises. The history itself is not exported.
4. **Hybrid graph evidence only follows relationships from the search table to itself.** For that reason the demo adds a `Ticket` to `Ticket` table named `Related`.
5. **The docs describe 0.0.5 and 0.0.6 development revisions.** The installed 0.0.8 matched every API used here. Where the installed signature and the docs differed in detail (for example `export_graph` has a `history` argument that the main example omits), the installed version was used.
6. **Conflict counts vary.** Step 3 counted 6 conflicts on macOS and 7 in Linux. This depends on timing.

## Not measured

- Whether hybrid results are more relevant than text results. Only the number of changed results was counted.
- Speed against any other database. No comparison was run.
- Behavior on a network share, on Windows, or with more than two writers.
