# Okto Grafx Use Case Repo: Shared Store Plan

Repo name: `grafx-shared-store-longrun-demo`. Tagline: "One folder. Several processes. Nothing lost, and every change can be looked up."

## 1. What Okto Grafx is

Grafx is a graph database that runs inside a Python program. There is no server to start. The whole database is a folder of files on a local disk, and any Python process that can open the folder can read and write it.

- Install with `pip install okto-grafx`, import as `okto_grafx`, and use the `oktografx` command for scripts and tools.
- It needs Python 3.11, 3.12 or 3.13 on a local Windows or POSIX filesystem.
- Queries use a bounded subset of Cypher, not full Cypher.
- It is pre-alpha (0.0.8 on `main` at the time of writing), and Pulse and Neuron use it as their graph store.
- The license is Elastic License 2.0 plus a SaaS/Branding Addendum, so it is source-available and not OSI open source.

## 2. What it does and where the repo shows it

| Feature | What it does | Where the repo shows it |
|---|---|---|
| Several processes on one store | Readers see a consistent snapshot, writers are checked for conflicts when they commit, and `GrafxWriteConflict` is marked retryable | Steps 3 and 4 |
| Durable commits and fail-closed recovery | `txn.report.durable` says a commit is safe on disk; after a crash the store is recovered and checked with `verify` before use | Step 5 |
| Full-text search | Native BM25 over declared text properties, with exact phrase search | Step 6 |
| Hybrid search | Weighted rank fusion of text and vector results plus graph evidence, all on one snapshot | Step 7 |
| System-time history | Opt-in history of every row change, with `system_as_of`, `system_versions` and `system_diff` | Step 8 |
| Backup, restore, logical export and import | A checked physical backup restored into a new folder, and a logical transfer between stores | Step 9 |
| HTML graph snapshot and JSON CLI | An offline HTML picture of a subgraph, and a read-only CLI a Node program can call | Step 10 |

## 3. Why we picked these features

- **They answer the questions people ask about an embedded database.** Can two programs use it at once? What if one is killed halfway? Can I see what a record looked like last week? Steps 3 to 5 and 8 answer those with runs, not claims.
- **They match what Grafx says it is for.** Its own comparison page recommends it for a Python local-first application with independent direct-file readers and writers, so the scenario is exactly that.
- **Each one leaves evidence.** A conflict count, a recovery report, a diff and a verify result are all plain output that a script can check.

Left out on purpose:
- Speed comparisons with Ladybug or Neo4j. The Grafx comparison page says no benchmarks were run, so the repo makes no speed claim against either.
- The README latency table. It is one sample on Windows through Pulse 0.3.3 and the README says it is not a general latency promise.
- Anything Grafx does not have: a network server, MCP server, authentication, encryption, replication or high availability. The README states these up front and so does this repo.

## 4. The scenario in one paragraph

A small support team keeps its tickets, customers, products and help articles in one Grafx folder. Two importer programs load new tickets at the same time, a search program answers questions while they write, and an auditor program watches history. In the middle of the run an importer is killed, the store is recovered, and the team checks that every committed ticket is there and nothing half-written is. Later a help article is corrected, and the auditor shows what it said before, what it says now and when it changed. The run ends with a backup, a restore and a scoreboard.

The app is a small Python package, `ticketgraph/`, with no web framework. It is built with Claude Code in the ten steps below. Grafx is a database and not an agent memory, so the demo is run by processes and scripts, and Claude Code is the builder.

## 5. The cast

| Who | Does | How it runs |
|---|---|---|
| Importer A and Importer B | Each loads a batch of tickets and links them to customers and articles | Two separate Python processes on the same folder |
| Searcher | Answers keyword, phrase and hybrid questions | A separate process that only reads |
| Auditor | Runs `verify`, reads history, takes backups | A separate process with its own handle |
| Maintainer (you) | Starts the processes, kills one in step 5, corrects an article in step 8 | A terminal |

Roles are separated by process, because the point of Grafx is that independent programs can share one store directly.

## 6. The ten steps

| Step | What happens | Shows |
|---|---|---|
| 1 | Install a pinned version, create the store, define the schema, turn on identity indexes, commit history and system history, run `verify` | Setup |
| 2 | One importer loads 40 articles, 25 customers and 200 tickets from a fixture file and checks `durable` on each commit | Durable commits |
| 3 | Importer A and Importer B load 300 more tickets at once. Conflicts are caught, retried and counted, and the final counts are checked against the fixture | Concurrent writers |
| 4 | The Searcher opens a read snapshot, an importer commits, and the old snapshot still shows the old counts while a new read shows the new ones | Snapshot reads |
| 5 | The Maintainer kills Importer B with SIGKILL in the middle of a transaction. The store is reopened, recovered and verified; committed tickets are present and the unfinished batch is absent | Crash safety |
| 6 | Ten keyword questions and three exact phrase questions run against ticket text | Full-text search |
| 7 | The same ten questions run as hybrid search using stored vectors and a link to the customer's product, and the two result lists are saved side by side | Hybrid search |
| 8 | The Maintainer corrects one help article. The Auditor shows the article as it was and as it is, using `system_as_of`, `system_versions` and `system_diff` | Time travel |
| 9 | The Auditor takes a backup, the original processes are stopped, and the backup is restored into a new folder and verified. A logical export and import is run into a second store | Backup and restore |
| 10 | The close-out script writes an HTML snapshot of one customer's tickets, a Node script reads the schema through the CLI, and the scoreboard is built | Scoreboard |

`run_demo.py` replays any set of steps (`--steps 3 5 8`, `--start`, `--dry-run`). A dry run prints every command and needs no Grafx install.

## 7. The data

- **Articles, customers, products**: written by us as small fixture files, clearly labelled as invented. No real customer data.
- **Tickets**: 500 short invented tickets in a fixture file, each with a subject, a body, a customer and an article it mentions.
- **Vectors**: Grafx stores and searches vectors but does not create them. The vectors are made once with an embedding model the Maintainer picks, saved in the fixture, and the repo names the model used. Running the demo needs no embedding service.
- **Hybrid search** works on one node table, so tickets are the search table and the customer, article and product links are used as graph evidence.

## 8. The scoreboard

`demo-state/closeout-result.json` is built from the recorded step outputs:

- tickets loaded, and whether the final count matches the fixture
- write conflicts raised and retried, and whether any commit was lost
- the stale snapshot check from step 4
- the crash check from step 5: committed tickets found, unfinished batch found (target zero), and the `verify` result
- search results for the 13 keyword and phrase questions, and how many of the 10 hybrid questions returned a different top result than text alone
- the article diff from step 8
- backup size, restore result and `verify` after restore
- time taken by each step on the machine used

The README prints these numbers from the real run and nothing else.

## 9. Repo layout and automated checks

Layout: `ticketgraph/` (importer, searcher, auditor), `fixtures/`, `demo-state/` (recorded outputs, close-out file, HTML snapshot, screenshots), `docs/` (walkthrough, one prompt per step, `VERIFIED.md`, hero and architecture SVGs), `scripts/`, `node/` (the CLI reader), `tests/`, `.github/workflows/validate.yml`, `run_demo.py`, `requirements.txt` with the pinned `okto-grafx` version, and an env example. The README follows the [Nexus](https://github.com/OktoLabsAI/nexus-brownfield-handoff-demo) and [Pulse](https://github.com/OktoLabsAI/pulse-brownfield-feature-demo) order: banner, About, The Problem, How It Works, Grafx in Action, Architecture, Repository Structure, Prerequisites, Quickstart, the ten steps, Where to Find Artifacts, Conclusion.

Checks on every push: unit tests for the importer retry loop and the scoreboard builder on recorded outputs, a short real run of steps 1 to 4 on a temporary folder, link and JSON checks, a compile check, a Node check, and a dry run of all ten steps. `docs/VERIFIED.md` states the Grafx version and date the commands were verified.

## 10. Limits the README states up front

- Grafx is pre-alpha, so the repo pins one version and says it was verified on that version only.
- It is embedded and Python only, with no server, no authentication or encryption, and no replication. It needs a local filesystem, not a network share.
- Cypher support is a bounded subset, so every query in the repo is one the docs list as supported.
- History is opt-in and records system time only. It has no valid-time or bitemporal support, and history before it was turned on does not exist.
- Restoring a backup needs the original participants stopped, because the restore carries the same database identity.
- The kill test in step 5 uses SIGKILL, so the repo documents Linux and macOS, and treats Windows as untested.
- The README performance table is one Windows sample and is not repeated here. No speed comparison with Ladybug or Neo4j is claimed.
- Because the license is Elastic License 2.0 plus an addendum, the demo repo links to it, does not copy Grafx source into the repo, and chooses its own license for the demo code only.

Sources: [Okto Grafx repository](https://github.com/OktoLabsAI/okto-grafx), [Pulse demo](https://github.com/OktoLabsAI/pulse-brownfield-feature-demo), [Nexus demo](https://github.com/OktoLabsAI/nexus-brownfield-handoff-demo).
