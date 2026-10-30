# Walkthrough

One short note per step. Each has the prompt you could give Claude Code, what it should build, and the check that proves it. Outputs of the reference run are in `demo-state/`; a new run writes the same files to `runs/<run id>/`.

The repo was built with Claude Code from [kickoff-prompt.md](kickoff-prompt.md). Grafx is a database, not an agent memory, so Claude Code is the builder and the demo itself is plain Python processes.

## Step 1: Setup

**Prompt:** "Create the store with Customer, Ticket, Article, Product and their links. Turn on identity indexes, commit history and system history. Run verify."

**Build:** `ticketgraph/schema.py`. System history must be enabled after the tables exist and after identity indexes and commit history, so the order matters.

**Check:** `verify("all")` has no findings. Output: `step01_setup.json`.

## Step 2: First load

**Prompt:** "Load 40 articles, 25 customers, 5 products and 200 tickets from the fixtures in one process. Check `txn.report.durable` on every commit."

**Build:** `ticketgraph/importer.py`. Tickets go in batches of 10. Each batch also writes its links.

**Check:** 200 tickets, all commits durable. Output: `step02_first_load.json`.

## Step 3: Two writers at once

**Prompt:** "Run Importer A and Importer B as separate processes on the other 300 tickets. Catch `GrafxWriteConflict`, retry, count every conflict. Never replay a durable commit."

**Build:** `ticketgraph/retry.py`, the conflict-only recipe from the Grafx Operations doc, with a counter. Both processes wait on a start file so they begin together.

**Check:** the store holds exactly the fixture's ticket ids, nothing lost, nothing extra. Output: `step03_two_writers.json`.

## Step 4: Snapshot reads

**Prompt:** "Open a read snapshot in the Searcher. Let an importer commit. Show that the old snapshot still has the old counts and a new read has the new ones."

**Build:** `ticketgraph/searcher.py snapshot`. The two processes talk through signal files.

**Check:** old snapshot unchanged, new read saw the commit. Output: `step04_snapshot_reads.json`.

## Step 5: Kill and recover

**Prompt:** "Start an importer. Kill it with SIGKILL in the middle of a write transaction. Reopen, follow the documented recovery, run verify, and check what survived."

**Build:** the importer takes `--hold-last MARKER SECONDS`. It commits 2 batches, then opens the third transaction, writes a marker file and waits. The orchestrator sees the marker and sends SIGKILL.

**Check:** 20 of 20 committed tickets are present, 0 of 10 unfinished tickets are, `verify` is clean. Output: `step05_kill_and_recover.json`.

## Step 6: Full-text search

**Prompt:** "Create the text index. Run ten keyword questions and three exact phrase questions."

**Build:** `create_text_index` on `Ticket(subject, body)` and `search_text`, with `phrase=True` for phrases. Questions are in `fixtures/questions.json`. Step 6 also adds the `Related` edges that step 7 uses.

**Check:** every question has hits, and phrase results report `phrase_verified`. Output: `step06_full_text.json`.

## Step 7: Hybrid search

**Prompt:** "Run the same ten questions as hybrid search with the stored vectors and graph evidence. Save the result next to the text-only result. Report honestly how many top results changed. Do not tune the questions."

**Build:** `search_hybrid` with weighted rank fusion. Two variants: with graph evidence and without.

**Check:** the text-only column equals step 6. The counts of changed results are computed, not typed. Output: `step07_hybrid.json`.

## Step 8: Time travel

**Prompt:** "Correct one article through a normal write. Show it before and after with `system_as_of`, `system_versions` and `system_diff`."

**Build:** `ticketgraph/auditor.py`. It records the newest commit, writes the correction, then reads both points.

**Check:** revision 1 and revision 2 both readable, two versions that join with no gap, one `updated` row in the diff. Output: `step08_time_travel.json`.

## Step 9: Backup and restore

**Prompt:** "Take a backup. Stop all original processes. Restore into a new folder with `confirm_original_offline=True` and verify. Then export and import into a second store and compare counts."

**Build:** `create_backup`, `restore_backup`, `export_graph(history="current-only")`, `import_graph`. This step needs Linux or Windows.

**Check:** no demo process alive at restore, `verify` clean, counts equal, same identity after restore, new identity after import. Output: `step09_backup_restore.json`.

## Step 10: Close-out

**Prompt:** "Write an HTML snapshot of one customer's tickets. Add a Node script that reads the schema through the `oktografx` CLI. Build the scoreboard."

**Build:** `node/read_schema.mjs` runs `python -m okto_grafx.cli schema PATH --json` without a shell. `ticketgraph/scoreboard.py` reads only the saved step outputs.

**Check:** the snapshot has no script tags, the Node script lists all 10 tables, and `closeout-result.json` matches a fresh build. Output: `step10_closeout.json`.

## Beyond the ten steps

The steps above stay as individual demonstrations. These scenarios build on them. Each runs from `run_scenarios.py`, writes one JSON file into the run folder and has its own page.

- **Retrieval evaluation** (`python run_scenarios.py eval`): lexical, hybrid and hybrid-plus-graph search scored against labelled questions, without a product id. [retrieval-evaluation.md](retrieval-evaluation.md)
- **Application recovery** (`resume`): an importer killed before a commit and after a commit acknowledgement, restarted until it finishes, checked against the fixture and an uninterrupted control. [application-recovery.md](application-recovery.md)
- **Support workflow** (`workflow`): intake, triage with a graph-driven decision, maintainer, auditor, killed twice and restarted. [support-workflow.md](support-workflow.md)
- **Workloads** (`workload`): opt-in concurrency configurations with latency percentiles, conflicts and integrity checks. [workloads.md](workloads.md)

Step 9 also records content digests of the original, the restored store and the logical import, and whether system history survived each. The runs are named, and can be compared, as described in [artifacts-and-runs.md](artifacts-and-runs.md).
