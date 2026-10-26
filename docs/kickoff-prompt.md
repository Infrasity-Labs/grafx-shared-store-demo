# Claude Code kickoff prompt: Okto Grafx use case repo

You are building the repo `grafx-shared-store-longrun-demo` from the plan in `okto-grafx-use-case-repo-plan.md`. Read the whole plan first, then work in the phases below. Grafx needs no LLM and no API key, so nothing here should need a secret. If you ever need a key, stop and ask, and never print or store one.

## Rules for the whole job

1. Every number, output and screenshot in the repo comes from a real run on this machine. Never invent or estimate a result. If a step cannot run, say so in the README and in `docs/VERIFIED.md`.
2. Grafx is pre-alpha. Pin the exact version you install in `requirements.txt` and write it in `docs/VERIFIED.md` with today's date.
3. Check every function name and argument against the real docs before using it. Clone `https://github.com/OktoLabsAI/okto-grafx` read-only into a folder outside this repo and read `README.md`, `docs/GETTING_STARTED.md`, `docs/OPERATIONS.md`, `docs/FULL_TEXT_SEARCH.md`, `docs/HYBRID_SEARCH.md`, `docs/SYSTEM_TIME_HISTORY.md`, `docs/BACKUP_RESTORE.md`, `docs/LOGICAL_TRANSFER.md`, `docs/HTML_SNAPSHOTS.md`, `docs/CLI.md` and `examples/cli-consumer/README.md`. If the installed version differs from the docs, trust the installed version and note it.
4. Use only Cypher the docs list as supported. Do not copy Grafx source code into this repo.
5. No em dashes anywhere in the repo. Short sentences, plain words, no marketing language.
6. Use only invented data. No real customer names, emails or tickets.
7. Commit after each step with a clear message. Do not push to any remote until told to.
8. Keep a running task list and tick each item only after its check passes.

## Phase A: set up and prove Grafx works (stop and report when done)

1. Check Python is 3.11, 3.12 or 3.13, and Node is 20 or newer. If Python is older, tell the user and stop.
2. Create a virtual environment inside the repo folder, install `okto-grafx`, and run the install check from the Grafx getting started page (version print, `oktografx --help`).
3. Run the complete durable example from the Getting Started page on a temporary folder. It must pass, including `verify`.
4. Create the repo skeleton from section 9 of the plan: `ticketgraph/`, `fixtures/`, `demo-state/`, `docs/`, `scripts/`, `node/`, `tests/`, `.github/workflows/validate.yml`, `run_demo.py`, `requirements.txt`, `.gitignore` (ignore `.venv/`, the live store folder and any `.env`).
5. Report: Grafx version installed, Python and Node versions, the result of the example, and the embedding plan from Phase B step 2. Then wait for the user to reply "go".

## Phase B: build and run the ten steps (after "go")

For each step: write the code, run it for real, save the output under `demo-state/`, add a test that checks the saved output, commit.

1. **Setup.** Create the store with the schema (Customer, Ticket, Article, Product and the links between them), turn on identity indexes, commit history and system history, and run `verify`. Save the output.
2. **Fixtures and first load.** Write the invented fixture files: 40 articles, 25 customers, 5 products and 500 tickets (200 for this step, 300 for step 3). For vectors, install a small local embedding model (for example a `sentence-transformers` model), create the vectors once, save them in `fixtures/`, and write the model name and version in the README. Grafx does not create vectors. If the model cannot be installed here, stop and ask. Load the first 200 tickets in one process and check `txn.report.durable` on every commit.
3. **Two writers at once.** Run Importer A and Importer B as separate processes loading the other 300 tickets. Catch `GrafxWriteConflict`, retry as the Operations doc describes, and count every conflict. Never replay a commit that is already durable. Check final counts against the fixtures.
4. **Snapshot reads.** The Searcher opens a read snapshot, an importer commits, and the old snapshot must still show the old counts while a new read shows the new ones. Save both outputs.
5. **Kill and recover.** Start an importer, kill it with SIGKILL in the middle of a write transaction, reopen the store, follow the documented recovery and `verify` steps, then check that committed tickets are present and the unfinished batch is absent. Save the recovery report. If recovery behaves differently from the docs, record exactly what happened and tell the user.
6. **Full-text search.** Create the text index and run ten keyword questions and three exact phrase questions. Save the results.
7. **Hybrid search.** Run the same ten questions as hybrid search with the stored vectors and graph evidence, and save the result next to the text-only result. Report honestly how many top results changed. Do not tune the questions to make hybrid look better.
8. **Time travel.** Correct one article through a normal write. Use `system_as_of`, `system_versions` and `system_diff` to show the article before and after. Save the output.
9. **Backup and restore.** Take a backup, stop all original processes, restore into a new folder with `confirm_original_offline=True`, and run `verify` on the restored store. Then run a logical export and import into a second store and compare counts. Save sizes and results.
10. **Close-out.** Write the HTML snapshot of one customer's tickets, add a Node script that reads the schema through the `oktografx` CLI as in the Grafx example, and build `demo-state/closeout-result.json` with every item from section 8 of the plan, including the time each step took.

## Phase C: finish the repo

1. Write `run_demo.py` with `--steps`, `--start` and `--dry-run`. A dry run must print every command and need no Grafx install.
2. Write the README in the Nexus and Pulse order named in section 9 of the plan, using only numbers from `closeout-result.json`. Add a hero image and an architecture diagram as SVG files. Add the limits from section 10, written in plain words.
3. Write `docs/walkthrough.md`, one short prompt-style note per step, and `docs/VERIFIED.md`.
4. Write `.github/workflows/validate.yml` to run the checks in section 9: unit tests, a short real run of steps 1 to 4 on a temporary folder, link and JSON checks, compile check, Node check and the dry run.
5. Add a license for the demo code only, and link to the Grafx license without copying it.
6. Run every check locally from a fresh clone in a temporary folder. Fix what fails.
7. Scan the whole repo for em dashes, for anything that looks like a key or token, and for absolute paths from this machine. Remove them.
8. Final report: what was built, the real numbers from the scoreboard, anything that did not behave as the docs say, and anything that needs a decision. Do not push.

## When to stop and ask

- Python or Node is too old, or Grafx will not install.
- The embedding model cannot be installed.
- Recovery in step 5 fails or the store does not verify.
- Any result contradicts the Grafx docs.
- You are about to claim something you did not measure.
