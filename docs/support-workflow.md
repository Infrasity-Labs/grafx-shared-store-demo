# The support workflow

The ten steps ask "can Grafx do this?". This workflow asks "why use it for this?": one small support desk job, done by several independent processes on one shared folder, where a graph relationship changes what the desk does. It is plain Python. No model, no agent framework, no web interface.

```sh
python run_scenarios.py workflow                          # temp store built from the fixtures, about 25 seconds
python -m ticketgraph.workflow --out workflow.json        # the same, one file
python -m ticketgraph.workflow --store live-store/graph --out workflow.json   # on the store steps 1 to 3 or more left
python -m ticketgraph.workflow --no-faults --out w.json   # one clean pass, nobody is killed
```

With `--store` the workflow runs on an existing demo store; the missing application tables (`appschema.py`), the incident graph and the text index are added to it first. Without it, a fresh store is built with the same schema and the same fixtures.

## The story

Two tickets arrive. Both were written for this demo (`fixtures/incoming_tickets.json`); they were chosen to show one case where the graph matters and one where it does not, not drawn at random.

| Stage | Process | What it does |
|---|---|---|
| Ticket ingestion | `intake` x2, at once | Persist the ticket, link the customer, and link the **product taken from the customer's account** (the ticket does not say). |
| Knowledge retrieval | `triage` x2, at once | Hybrid search for similar tickets, using the ticket's own text and vector. Suggest the article that the similar tickets mention. |
| Incident correlation | same | Follow `InIncident` and `SameIncident` from the similar tickets to the incident they belong to, and to every product that incident touched. |
| Decision | same | Escalate when the evidence shows 2 or more products affected. Write the decision, the suggested articles and the incident link in one transaction. |
| Knowledge update | `maintain` | For a ticket that joined an incident, add a note drawn from the incident to the suggested article. |
| Audit | `audit`, a separate process | Read the article's last two versions from system history only, and report what changed. |
| Recovery | the whole workflow, restarted | Described below. |

## The graph changes a decision

Both pipelines apply the same rule (`ticketgraph/triage.py`). They differ in evidence.

Ticket 3001, "Login fails on all our devices", from the recorded run `20261029T190205Z-a5ad197-dirty` (`scenario_workflow.json`):

- **Text and vector evidence only**: the five most similar tickets are all sign-in tickets of one product (Tidewater Sync). One product: *routine*.
- **With graph correlation**: at least two of those tickets are triaged members of the incident "Identity service outage". Following the incident reaches tickets of other products: Tidewater Sync, Cobalt Gateway (API keys), Fennel Mobile (biometric login), and Marrow Billing. Several products: *attach to the incident, escalate*. The ticket is set to `high` and `escalated`, and the maintainer later adds a note about the incident to the sign-in article.

Ticket 3002, "Report layout question": both pipelines see one product (Lantern Reports) and no incident. *Routine* either way. The graph changed one decision of two, and `checks` in the JSON record both facts.

**Marrow Billing is wrong.** It entered the evidence through one of the 8 deliberately wrong links in the fixture (ticket 256 to ticket 429), which the workflow cannot tell from a good link. The other three products are reachable through genuine incident links. The decision to escalate would have been the same without Marrow Billing, but the product list shown to a person would have been wrong. `diagnostics` in the JSON lists the wrong links that touched each decision's evidence, using the fixture's own `misfiled` flag after the fact. The evaluation in [retrieval-evaluation.md](retrieval-evaluation.md) is the measured view of the same effect.

## Recovery

The maintainer is killed twice, and each time the whole workflow is started again with the same command:

| Pass | Fault | After the pass |
|---|---|---|
| 1 | Maintainer SIGKILLed inside its transaction, before the commit. | Article still revision 1. Intake and triage rows committed. |
| 2 | Intake and triage find their checkpoints and skip. Maintainer commits, then is SIGKILLed right after the commit was acknowledged. | Article is revision 2 although the maintainer never reported it. |
| 3 | Everything finds its checkpoint and skips. The audit runs. | Article is still revision 2. Nothing doubled. |

Every write stage carries its own `Checkpoint` row in the same transaction (see [application-recovery.md](application-recovery.md)). The final checks: each new ticket exists once with one `Opened` and one `About` link, one `Triage` row per ticket, the article was enriched exactly once, the audit found exactly that change, `verify` is clean, and four roles ran as separate processes.

## Evidence

`trace` in `scenario_workflow.json` is the ordered event log of every process (pid, actor, stage, commit sequence number, skips, the two `sigkill_self` events). `decisions` has, for each ticket, both pipelines' evidence, the similar tickets with and without the graph boost, and the suggested articles. `audit` has the sentences added to the article, read from system history by a process that did not make the change. `passes` has the state of the store after each pass.

## Limits

- Two tickets, one incident rule, one escalation rule. It shows a mechanism, not how often a graph helps a real desk.
- The incident graph is invented and partly wrong on purpose. In a real desk someone has to maintain such links.
- The triage rule uses the graph by explicit queries over `InIncident` and `SameIncident`. It does not use Grafx's hybrid graph evidence for the decision (it shows that ranking too, in `similar_tickets_hybrid_with_graph_boost`).
