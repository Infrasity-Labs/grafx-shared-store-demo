# Workloads: more writers, more records, shared records

The default demo is small on purpose: two writers, 530 tickets, one reader. This page describes the opt-in workload mode, which varies the number of writers and readers, the number of records and links, the batch size, and whether the writers touch the same records.

```sh
python run_scenarios.py workload                              # the four small configs, about 1 minute
python run_scenarios.py workload --config shared-hot-small    # one config by name
python -m ticketgraph.workload --config workloads/disjoint-small.json --out wl.json \
    --override writers=3 --override records_per_writer=600    # your own shape, one file
```

Nothing here runs unless you ask. CI runs the four small configs (`integration.yml`). The two large configs are never run by the repo; you choose to.

## What a workload does

It builds its own fresh store (`WRecord`, `WHot`, `WLink`; it does not touch the ticket schema), then starts writer and reader processes together. A writer batch is one write transaction that creates `batch_size` records, their links to hot rows, and a read-modify-write of every hot row it linked to (`version = version + 1`). Readers loop on read snapshots until the writers finish. **Contention** is set by the hot rows: in `disjoint` each writer has private hot rows, in `shared` all writers read-modify-write the same pool of `hot_records` rows. Retries use the conflict-only loop of `ticketgraph/retry.py` with a budget of `max_attempts`; a batch that uses up its budget is counted as failed and is not retried further.

Each config is a JSON file in [`workloads/`](../workloads) whose `description` says what it is meant to show. The module docstring of `ticketgraph/workload.py` lists every key.

| Config | Purpose |
|---|---|
| `disjoint-small` | 2 writers, private hot rows. Low contention on records. |
| `disjoint-4w-small` | 4 writers, private hot rows. The baseline for the next two at the same writer count. |
| `shared-wide-small` | 4 writers, one pool of 50 hot rows. Moderate record contention. |
| `shared-hot-small` | 4 writers, one pool of 2 hot rows, 2 links per record. High record contention. |
| `disjoint-large`, `shared-large` | 8 writers, 4 readers, 80,000 records each. Opt-in, never run or recorded by this repo. |

## What it records

Commit latency (one committed attempt: the statements, the read-modify-write and the commit), batch latency (a committed batch from first attempt to commit, backoff included), read latency, each as p50, p95, p99, min, max, mean and count (nearest-rank percentiles, milliseconds). Throughput. Attempts, conflicts, conflict rate, batches that needed a retry, the retry histogram, failed or exhausted batches and their error types. Store size before and after. Recovery: the time to reopen the store after a SIGKILL of a process that held an open write transaction, at that store size, with the recovery report.

**Integrity is checked after every workload** against what the writers say they committed: record count and the exact set of record ids (nothing lost, nothing extra), every link and its endpoints, each hot row's `version` equals the number of committed batches that touched it (a lost update would show here), no reader ever saw a partial batch (every count seen was a multiple of the batch size), no reader error, `verify("all")` clean. A workload whose integrity fails exits non-zero.

## A recorded run

Run `20261029T190205Z-a5ad197-dirty`, macOS arm64 laptop, Grafx 0.0.8 (the versions of everything else are in `run-manifest.json`). One run of each config; not a benchmark.

<!-- generated:workloads run=20261029T190205Z-a5ad197-dirty -->
| Workload | Writers / readers | Contention | Records/s | Conflicts / attempts | Failed batches | Commit p50 / p95 / p99 (ms) | Read p95 (ms) | Reopen after SIGKILL (s) | Integrity |
|---|---|---|---|---|---|---|---|---|---|
| disjoint-4w-small | 4 / 1 | disjoint, 5 hot | 288.53 | 77 / 237 | 0 | 30.79 / 70.971 / 139.069 | 14.003 | 0.0649 | ok |
| disjoint-small | 2 / 1 | disjoint, 5 hot | 317.67 | 14 / 94 | 0 | 28.617 / 57.664 / 79.133 | 8.018 | 0.0435 | ok |
| shared-hot-small | 4 / 1 | shared, 2 hot | 152.42 | 117 / 271 | 6 | 63.859 / 106.346 / 137.511 | 12.049 | 0.0998 | ok |
| shared-wide-small | 4 / 1 | shared, 50 hot | 236.16 | 70 / 229 | 2 | 37.262 / 72.38 / 83.326 | 14.079 | 0.0571 | ok |
<!-- /generated -->

What it shows, and nothing beyond it:

- Integrity held in all four, including the ones where batches failed: committed work was exactly accounted for.
- Writers on **private** hot rows still had conflicts (`disjoint-small`: 14 of 94 attempts; `disjoint-4w-small`: 77 of 237). Grafx detects conflicts per partition, not per row ([PRODUCT-OBSERVATIONS.md](PRODUCT-OBSERVATIONS.md)). More writers brought more conflicts even with no shared record.
- Sharing two hot rows (`shared-hot-small`) gave the most conflicts (117 of 271 attempts), the highest commit p50 and p95, the most batches that used up their 12 attempts (6; `shared-wide-small` 2, both disjoint configs 0) and the lowest throughput. Sharing 50 hot rows (`shared-wide-small`) had a conflict count close to the 4-writer disjoint case (70 of 229 against 77 of 237).
- Other runs of the same configs on this machine during development, not recorded, gave 14 to 19 conflicts for `disjoint-small`. Conflict counts depend on process timing. Compare shapes, not single numbers.

What it does not show: how Grafx scales. The stores are a few MB, the runs last seconds, there is one machine and one run per config. No claim about larger stores, more writers, other disks or other versions follows from these numbers. Use the same commands on the shape you care about and compare runs with `scripts/compare_runs.py`.
