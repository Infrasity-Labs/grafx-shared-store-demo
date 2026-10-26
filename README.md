# grafx-shared-store-longrun-demo

![One folder. Several processes.](docs/images/banner.svg)

One folder. Several processes. Nothing lost, and every change can be looked up.

A small support desk keeps its tickets, customers, products and help articles in one Okto Grafx folder. Two importers write at once, a searcher reads while they write, one importer is killed with SIGKILL, and an auditor shows what a corrected article said before. Every number below comes from a real run that is saved in `demo-state/`.

[About Okto Grafx](#about-okto-grafx) · [Limits](#limits) · [The Problem](#the-problem) · [How It Works](#how-it-works) · [Grafx in Action](#grafx-in-action) · [Architecture](#architecture) · [Repository Structure](#repository-structure) · [Prerequisites](#prerequisites) · [Quickstart](#quickstart) · [The Ten Steps](#the-ten-steps) · [Where to Find Artifacts](#where-to-find-artifacts) · [Conclusion](#conclusion)

## About Okto Grafx

[Okto Grafx](https://github.com/OktoLabsAI/okto-grafx) is a graph database that runs inside a Python program. There is no server to start. The database is a folder of files on a local disk, and any Python process that can open the folder can read and write it.

- Install with `pip install okto-grafx`. Import `okto_grafx`. Use the `oktografx` command for scripts and tools.
- It needs Python 3.11, 3.12 or 3.13 on a local disk.
- Queries use a bounded part of Cypher, not all of it.
- It is pre-alpha. This repo pins version **0.0.8**.

This repo is not made by the Grafx team. It is a worked example that uses Grafx the way its docs describe.

## Limits

Read these first.

- **Pre-alpha.** Everything here was verified on Grafx 0.0.8 only. See [docs/VERIFIED.md](docs/VERIFIED.md).
- **Embedded and Python only.** No server, no login, no encryption, no copies on other machines. Keep the folder on a local disk, not a network share.
- **Bounded Cypher.** Every query in this repo is one the Grafx docs list as supported.
- **History is opt-in and records system time only.** It has no valid-time support. History from before it was turned on does not exist.
- **Restore needs the originals stopped.** A restored backup has the same database identity as the original, so both must not run together.
- **Step 9 needs Linux or Windows.** On macOS, Grafx refuses to publish a backup or a logical export. This repo runs all ten steps in a Linux container for that reason. The macOS run is kept in `demo-state/macos-arm64/` and shows the refusal.
- **Linux and macOS only for the kill test.** Step 5 uses SIGKILL. Windows is untested.
- **No speed claims.** The demo times each step on one machine. It makes no comparison with Ladybug or Neo4j.
- **License.** Grafx uses Elastic License 2.0 plus an addendum, so it is source-available and not OSI open source. See the [Grafx license](https://github.com/OktoLabsAI/okto-grafx/blob/main/LICENSE). This repo does not copy Grafx source. The demo code has its own license (MIT, see [LICENSE](LICENSE)).

## The Problem

An embedded database is easy to start and hard to trust. People who look at one ask:

1. Can two programs use the same store at the same time?
2. What if one is killed halfway through a write?
3. Can I see what a record said last week?
4. Can I back it up and get it back?

This repo answers each one with a run you can repeat, not with a claim.

## How It Works

The app is a small Python package, `ticketgraph/`, with no web framework. Four roles run as separate processes on the same folder.

| Role | Does | Runs as |
|---|---|---|
| Importer A and Importer B | Load tickets and link them to customers, articles and products | Two Python processes |
| Searcher | Reads snapshots, runs keyword, phrase and hybrid search | A Python process |
| Auditor | Runs `verify`, reads history, takes backups | A Python process with its own handle |
| Maintainer (you) | Starts the processes, kills one in step 5, corrects an article in step 8 | A terminal |

All data is invented: 5 products, 25 customers, 40 articles and 500 core tickets, plus 40 extra tickets for steps 4 and 5. No real names, emails or tickets.

Grafx stores and searches vectors but does not create them. The vectors were made once with `sentence-transformers/all-MiniLM-L6-v2` (384 numbers per text, sentence-transformers 6.2.0, torch 2.14.1) and saved in `fixtures/`. The model is about 87 MB on disk, and the peak memory measured while making the 553 vectors was 591 MB. Running the demo does not need the model or torch. See `scripts/make_vectors.py`.

## Grafx in Action

These numbers are copied from [`demo-state/closeout-result.json`](demo-state/closeout-result.json). The run was in a Linux container (Python 3.12.14, Node v22.23.4) on an Apple silicon laptop, with the store on the container's own disk.

| Question | Result |
|---|---|
| Were all tickets loaded? | 200 in step 2 and 300 in step 3. The store held 500, and the fixture has 500. |
| Did every commit report `durable`? | Yes, in both steps. |
| Write conflicts in step 3 | 7 total: Importer A 0, Importer B 7. All were retried. No commit was lost. |
| Did an old read snapshot stay old? | Yes. It showed 500 tickets before and after another process committed 10 more. A new read showed 510. |
| After SIGKILL inside a write transaction | 20 of 20 committed tickets found. 0 of 10 unfinished tickets found. `verify` had 0 findings. Recovery outcome: `clean`. |
| Keyword and phrase search | 10 of 10 keyword questions and 3 of 3 phrase questions returned hits. |
| Hybrid search | The top result changed for 7 of 10 questions with graph evidence, and for 5 of 10 without it. The top 5 set changed for 9 of 10. See the note below. |
| Corrected article | Revision 1 became revision 2. `system_as_of`, `system_versions` and `system_diff` show both. |
| Backup and restore | 49 files, 29,031,556 bytes. The restore passed `verify` with 0 findings, the counts matched and the identity was the same. |
| Logical export and import | 3,240 rows out and 3,240 in. Counts matched, `verify` had 0 findings, and the new store has a new identity. |

Time taken by each step on that run, in seconds:

| Step | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 |
|---|---|---|---|---|---|---|---|---|---|---|
| Seconds | 0.5 | 2.2 | 5.9 | 1.6 | 2.4 | 4.4 | 1.7 | 2.0 | 9.0 | 0.6 |

**Notes on the numbers**

- The conflict count changes from run to run. It depends on how the two processes interleave. An earlier run on macOS counted 6 (A 1, B 5).
- The hybrid number says the ranking is different. It does not say the ranking is better. We did not measure relevance. The questions were written before any search ran and were not changed. Most tickets are built from shared sentences, so many tickets are near duplicates.
- In the hybrid run, graph evidence uses `Related` edges between tickets of the same product. The seeds are the 3 lowest ticket ids of the question's product. That rule was fixed before any search ran.
- The HTML snapshot in step 10 shows one customer's 14 tickets. Grafx draws whole tables, so the demo copies that customer's rows into a small separate store first and draws that store.
- The step 8 correction is invented text about an invented product.

## Architecture

![Architecture](docs/images/architecture.svg)

Grafx keeps the whole database in one folder. Each process opens it directly. Readers see a snapshot. Writers are checked for conflicts when they commit, and a conflict is marked as retryable. A commit is safe on disk when `txn.report.durable` is true.

## Repository Structure

```
.
├── README.md
├── LICENSE                    demo code only
├── requirements.txt           pins okto-grafx==0.0.8
├── requirements-vectors.txt   only for scripts/make_vectors.py
├── run_demo.py                --steps, --start, --dry-run
├── ticketgraph/               the app
│   ├── schema.py              tables and store setup
│   ├── importer.py            Importer A and B
│   ├── retry.py               conflict retry loop
│   ├── searcher.py            snapshot reads, text and hybrid search
│   ├── auditor.py             history and the article correction
│   ├── steps.py               the ten steps
│   └── scoreboard.py          builds closeout-result.json
├── fixtures/                  invented data, stored vectors, questions
├── demo-state/                recorded outputs of the real run
│   ├── step01_setup.json ... step10_closeout.json
│   ├── closeout-result.json   the scoreboard
│   ├── customer-1-tickets.html
│   └── macos-arm64/           the macOS run (step 9 refused)
├── docs/
│   ├── walkthrough.md         one short note per step
│   ├── VERIFIED.md            versions, date, what behaved differently
│   ├── kickoff-prompt.md      the prompt this repo was built from
│   └── images/                banner and architecture SVGs
├── node/read_schema.mjs       reads the schema through the oktografx CLI
├── scripts/                   fixtures, vectors, Docker run, repo checks
├── docker/Dockerfile          Linux run
├── tests/                     unit tests and recorded-output checks
├── okto-grafx-use-case-repo-plan.md
└── .github/workflows/validate.yml
```

## Prerequisites

- Python 3.11, 3.12 or 3.13, and Node 20 or newer.
- Linux for all ten steps. On macOS, use Docker for step 9 (see below). Windows is untested.
- No API key. No account. Nothing in this repo needs a secret.

## Quickstart

```sh
python3.12 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt

python run_demo.py --dry-run          # prints every command, runs nothing
python -m unittest discover tests     # unit tests and recorded-output checks
python run_demo.py                    # all ten steps, writes to ./live-store and ./demo-state
```

Run only some steps with `--steps 3 5 8`, or from one step on with `--start 5`. Steps build on each other, so a later step needs the store from the earlier ones.

On macOS, or any host without a Linux disk, run everything in a container:

```sh
./scripts/run_in_docker.sh
```

To change the vectors, run `pip install -r requirements-vectors.txt` and then `python scripts/make_vectors.py`. This downloads the embedding model once.

## The Ten Steps

Each step saves its output in `demo-state/`. The note for each one is in [docs/walkthrough.md](docs/walkthrough.md).

| Step | What happens | Output file |
|---|---|---|
| 1 | Create the store with the schema. Turn on identity indexes, commit history and system history. Run `verify`. | `step01_setup.json` |
| 2 | One importer loads 40 articles, 25 customers, 5 products and 200 tickets. It checks `durable` on every commit. | `step02_first_load.json` |
| 3 | Importer A and Importer B load 300 tickets at once. Conflicts are caught, retried and counted. | `step03_two_writers.json` |
| 4 | The Searcher holds a read snapshot while an importer commits. The old snapshot stays old. | `step04_snapshot_reads.json` |
| 5 | An importer is killed with SIGKILL inside a write transaction. The store is reopened and checked. | `step05_kill_and_recover.json` |
| 6 | Ten keyword questions and three exact phrase questions run against ticket text. | `step06_full_text.json` |
| 7 | The same ten questions run as hybrid search with stored vectors and graph evidence. | `step07_hybrid.json` |
| 8 | One article is corrected. The Auditor shows it before and after. | `step08_time_travel.json` |
| 9 | Backup, stop all processes, restore, `verify`. Then logical export and import into a second store. | `step09_backup_restore.json` |
| 10 | HTML snapshot of one customer's tickets. A Node script reads the schema through the CLI. The scoreboard is built. | `step10_closeout.json`, `closeout-result.json` |

Two details that are easy to miss:

- In step 5 the kill happens while the importer holds an open write transaction, after two batches of 10 tickets were committed. The recovery report said `clean` and that 433 committed records were replayed. The 20 committed tickets were present and none of the unfinished 10 were.
- In step 10 the CLI needs a store whose last checkpoint is complete. The demo calls `checkpoint()` before the Node script runs, as the Grafx operations doc says to do.

## Where to Find Artifacts

| What | Where |
|---|---|
| Scoreboard | `demo-state/closeout-result.json` |
| Raw output of each step | `demo-state/stepNN_*.json` |
| Recovery report from the kill test | `demo-state/step05_kill_and_recover.json` |
| Side-by-side text and hybrid results | `demo-state/step07_hybrid.json` |
| Article before, after and diff | `demo-state/step08_time_travel.json` |
| HTML picture of one customer's tickets | `demo-state/customer-1-tickets.html` |
| macOS run | `demo-state/macos-arm64/` |
| Versions and date verified | `docs/VERIFIED.md` |

## Conclusion

On Grafx 0.0.8, two programs wrote to one folder at once, and the 7 write conflicts were retried with no lost commit. A read snapshot stayed stable while another process committed. A process killed with SIGKILL inside a transaction left no half-written tickets, and the store verified clean after it was reopened. A corrected article could be looked up as it was and as it is. A backup restored into a new folder and verified, and a logical export imported into a second store with matching counts.

That is one run on one machine on a pre-alpha version. Treat it as a worked example, not a benchmark or a certification. Read the [Grafx docs](https://github.com/OktoLabsAI/okto-grafx/tree/main/docs) before you depend on any of it.

Related demos from Okto Labs: [Pulse](https://github.com/OktoLabsAI/pulse-brownfield-feature-demo) and [Nexus](https://github.com/OktoLabsAI/nexus-brownfield-handoff-demo).
