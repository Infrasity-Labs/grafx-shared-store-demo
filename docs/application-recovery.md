# Application recovery

Step 5 shows what Grafx does when a writer is killed: the committed batches are there, the unfinished one is not, and `verify` is clean. That is **database recovery**. It says nothing about what the writer should do when it is started again. This page covers that second half, which Grafx does not do for you.

Run it:

```sh
python run_scenarios.py resume          # about 10 seconds, writes scenario_resume.json into runs/<run id>/
python -m ticketgraph.resume_demo --out resume.json    # the same, one file, temp store
```

## Who is responsible for what

| Grafx (database) | `ticketgraph` (application) |
|---|---|
| A commit is atomic: a batch's tickets, links and checkpoint row are all there or none are. | Knowing which batches are done: one `Checkpoint` row per batch, written in the same transaction as the batch. |
| A commit reported `durable` survives SIGKILL of the writer. | Resuming: a restarted importer reads its job's checkpoints and skips the batches that are done. |
| A transaction that never committed is gone after the store is reopened. | Not duplicating relationships: Grafx accepts the same relationship twice, so a committed batch must never be replayed. |
| A duplicate primary key is refused and the refused transaction writes nothing. | Refusing a changed input: a checkpoint carries a digest of its batch's ticket ids. |

## What the scenario does

The job loads 100 tickets in 10 batches of 10, after one static batch (products, customers, articles). `ticketgraph/resumable.py` is the importer. It kills itself with SIGKILL at a chosen point, so the interruption is real and happens at an exact place.

| Phase | What happens | State after |
|---|---|---|
| 1 | Killed inside batch 3's transaction, after its writes, before the commit. | Batches 0 to 2 committed. Batch 3 absent. |
| 2 | Restarted. Skips 0 to 2. Killed right after batch 6's commit was acknowledged as durable. | Batches 0 to 6 committed, although the importer never got to note it. |
| 3 | Restarted. Skips 0 to 6. Commits 7 to 9. | All 100 tickets. |
| 4 | Started again on the finished job. | Nothing changes. |
| 5 | A control importer loads the same rows in one uninterrupted run into a second store. | The resumed store and the control have the same content digest. |

After phase 4 the scenario also **probes what the database does not protect**, inside a transaction it rolls back: it writes one committed batch's links a second time (Grafx accepts them, the count goes from 100 to 110) and, separately, replays a whole committed batch (Grafx refuses it on the duplicate ticket id and writes nothing).

The recorded result shows, for every phase, the exit code (`-9` for the two kills), the importer's own event log (which batches it skipped and committed, where it killed itself), the reopened store's recovery report and counts, and finally the comparison with the fixture: ticket ids, subject, body, priority and status of every ticket, the endpoints of every `Opened`, `Mentions` and `About` relationship, no duplicate relationships, and the checkpoint list.

## What this does not cover

- Only the importer is made resumable. The ten steps keep their own simpler importer.
- One interrupted process at a time. Two importers resuming the same job at once is not tested; the job name is the lock a real application would need.
- A crash in the middle of a *batch* never leaves half a batch, because a batch is one transaction. A job that needs several transactions per unit of work would need a checkpoint per transaction.
- Time-based failures (a hung process, a full disk) are not simulated. SIGKILL is.
