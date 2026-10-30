# Observations about Grafx itself

Things this repo learned about Grafx 0.0.8 that are properties of the product, not of the demo code. They are listed here instead of being worked around quietly. Each one names the evidence. Nothing here is a complaint: Grafx is pre-alpha and its docs say so.

Re-check this list whenever the pin in `requirements.txt` changes. `scripts/check_repo.py` fails if this file does not mention the pinned version.

## Platform

1. **macOS refuses physical backup and logical export.** Both publish a directory with `renameat2` (Linux) or `MoveFileExW` (Windows) and raise `GrafxUnsupportedOperation` elsewhere (`okto_grafx/backup.py`, `_promote`). Evidence: `demo-state/macos-arm64/step09_backup_restore.json` and `runs/20261029T190205Z-a5ad197-dirty/step09_backup_restore.json`. Step 9 is therefore only a live check on Linux, which is why `integration.yml` runs it on `ubuntu-latest`.

## Search

2. **Graph evidence re-ranks. It does not retrieve.** In `search_hybrid` the candidate set is the union of the lexical and the vector candidates (`okto_grafx/engine/hybrid.py`, the `ids = set.union(*sources)` block). The graph step only adds a score to rows already in that set (`graph_weight / (rrf_k + depth + 1)`), unless `graph_filter=True`, which can only remove rows. A neighbour that neither the text index nor the vector index proposed can never appear, however well connected it is. `candidate_k` therefore decides how much the graph can do. See [retrieval-evaluation.md](retrieval-evaluation.md).
3. **Graph seeds are native record ids, and relations must join the search table to itself.** `graph_seeds` takes Grafx's internal integer record ids, not application ids, and every relation in `graph_relations` must be `Ticket` to `Ticket` here. The demo maps ids through system history (`searcher.ticket_directory`). That works because history is on. It is an extra step for anyone who wants seeds from a query.
4. **There is no built-in way to get seeds from a query.** Grafx scores graph evidence from seeds you pass. Using the top lexical hits (what this repo does) is an application choice, and the evaluation shows it can amplify a wrong top hit.

## Writes and recovery

5. **Write conflicts are detected per partition, not per row.** The error reads "This transaction read or wrote a partition that another commit wrote after its snapshot was taken" (`okto_grafx/engine/txn_manager.py`). Writers that never touch the same record still conflict. In `runs/20261029T190205Z-a5ad197-dirty/scenario_workload_disjoint-small.json` two writers on private hot rows had 14 conflicts in 94 attempts, and four writers on private hot rows 77 in 237 (`scenario_workload_disjoint-4w-small.json`). Plan retry budgets for that, not for "different rows never collide".
6. **A relationship is not unique.** Creating the same relationship twice succeeds, so retrying a committed batch that carries links duplicates them. A duplicate primary key on a node is refused (`GrafxQueryError`, code `query_error`) and writes nothing. Evidence: `duplicate_link_probe` in `runs/20261029T190205Z-a5ad197-dirty/scenario_resume.json`. This is why the resumable importer keeps its own checkpoints. See [application-recovery.md](application-recovery.md).
7. **After SIGKILL the recovery report said `clean` in every case recorded here**: step 5, the two kills of the resumable importer (inside a transaction, and right after a commit was acknowledged) and the workload recovery probes (`runs/20261029T190205Z-a5ad197-dirty/scenario_resume.json`, `state_after.recovery_report`). Grafx does not report which application job was interrupted. That knowledge has to live in the data.

## History and transfer

8. **Commit history is lost in a logical import.** After `export_graph(..., history="current-only")` and `import_graph`, the new store answers `commit_history()` with `GrafxUnsupportedOperation: Commit history is not enabled in this snapshot`. The row content is identical (same content digest), the identity is new, and the history of the original (the two versions of the corrected article) does not come along. A physical restore keeps all of it. Step 9 now records both (`integrity.history_restored`, `integrity.history_fork`, `integrity.history_survives_physical_restore`, `integrity.history_survives_logical_import`). This was first seen in a development run on macOS in which the atomic directory publish was replaced by a plain rename so that step 9 could execute at all. That run is not evidence and was not kept. The Linux run in `integration.yml` records it for real; no Linux run of the new step 9 has happened on this machine.
9. **`export_graph` refuses a store with system history unless `history="current-only"`.** From the first verification, still true.
10. **A read-only open needs a checkpoint-complete store** (`oktografx schema` after commits). The demo calls `checkpoint()` first, as the Operations doc says.

## Query language

11. Used and working in 0.0.8 (no claim about other versions): `MERGE` of a relationship (run twice it left one relationship), `SET a.v = a.v + 1`, variable-length paths (`[:R*1..2]`), `WHERE x.id IN $list` with a parameter list, `count(DISTINCT ...)`, `ORDER BY ... SKIP ... LIMIT`, `executemany`. `DELETE` of a node with relationships is refused; `DETACH DELETE` is needed.
