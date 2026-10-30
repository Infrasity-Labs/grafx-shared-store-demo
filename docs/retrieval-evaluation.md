# Retrieval evaluation

**Question:** does hybrid search find more of the right tickets than text search, and does graph evidence add anything on top? Step 7 only counted how often the top result *changed*. That says the ranking is different, not better. This evaluation scores the rankings against labels.

```sh
python run_scenarios.py eval                       # about 30 seconds, writes scenario_eval.json into runs/<run id>/
python -m ticketgraph.evaluate --out eval.json     # the same, one file, temp store
```

The tables below are generated from `runs/20261029T190205Z-a5ad197-dirty/scenario_eval.json` (run `20261029T190205Z-a5ad197-dirty`, macOS, Grafx 0.0.8) and checked against it by `tests/test_readme_numbers.py`. The run is deterministic: two runs on the same pin gave identical metrics (`tests/test_scenarios_e2e.py`).

## What was measured

**Store.** A fresh store with the 500 core tickets, their stored vectors, the `Related` same-product edges of step 6, and the recorded incident graph described below.

**Questions.** 36 questions in [`fixtures/eval_questions.json`](../fixtures/eval_questions.json): 24 "same problem" questions (the person wants tickets about the same problem) and 12 "same outage" questions (the person wants every ticket caused by the same outage). The texts were written by hand before any search ran and were not changed after seeing results. None is copied from a ticket (`tests/test_evaluation.py` checks that). Their vectors were made with the same model as the ticket vectors (`scripts/make_eval_vectors.py`; it reproduced the earlier question vectors to within 5e-06, the rounding).

**Labels, and exactly how they were produced.** Nobody labelled anything by hand. [`scripts/make_fixtures.py`](../scripts/make_fixtures.py) computes [`fixtures/eval_qrels.json`](../fixtures/eval_qrels.json) from the generation structure of the fixtures, which exists independently of any search:

- Every ticket was generated from one feature and records it as `article_id`.
- A "same problem" question is relevant to the tickets of one feature, and to that feature's article.
- A "same outage" question is relevant to the tickets of every feature of one of four **invented** incidents (identity service outage, email provider degradation, storage backend migration, rates and tax feed outage), and to those features' articles. Incidents are defined once in the script, before any search.

**These labels were not reviewed by a second person or a domain expert.** They are labels by construction on invented data. The tests only check that the files equal what the rule produces and that the rule is applied consistently. Treat the question "were these the right relevance judgements" as open.

**A model reviewed the key (draft, not a person).** On 2026-10-30 a model (`claude-sonnet-5-5`, run as a subagent, same vendor family as the models that made this data) read each question against the ticket and article text and wrote [`fixtures/eval_qrels_model_review.json`](../fixtures/eval_qrels_model_review.json) with a report in [`fixtures/eval_qrels_model_review.REPORT.md`](../fixtures/eval_qrels_model_review.REPORT.md). `fixtures/eval_qrels.json` was not changed. What it found:

- 16 of 36 questions look fine and 20 need changes (172 proposed removals, 20 proposed additions).
- The key labels by feature (`article_id`), but each feature has three different symptoms, and all three count as relevant to any question about that feature. Example: 6 of the 14 tickets listed for `f11` ("api credential rejected as invalid") are about key rotation or the last-used column, not rejected keys.
- For the incident questions the ticket text never mentions an outage, and the three questions of one incident share one identical key whatever their wording.
- Incident 4 has all 47 tickets in one product, so a same-product baseline recovers that key.

Does it change the result? [`scripts/rescore_with_review.py`](../scripts/rescore_with_review.py) applies the proposed changes and runs the whole evaluation again on a fresh store (output: [`fixtures/eval_qrels_model_review.sensitivity.json`](../fixtures/eval_qrels_model_review.sensitivity.json)). The "generated key" rows reproduce the recorded numbers exactly. nDCG@10, all 36 questions:

| Strategy | Generated key | Model-reviewed key |
|---|---|---|
| Lexical | 0.668 | 0.656 |
| Hybrid | 0.851 | 0.847 |
| Hybrid + graph | 0.789 | 0.781 |

The order is the same under both keys (hybrid, then hybrid + graph, then lexical), so the conclusion does not depend on the changes the model proposed. That is a sensitivity check against one model's opinion. It is **not** the manual validation the review asked for. On 2026-10-30 Yuvi read the review's summary and its examples and found no problems; nobody has gone through all 36 questions line by line or decided which of the proposed removals and additions are right.

**The graph.** [`fixtures/incident_graph.json`](../fixtures/incident_graph.json) records what a triage engineer might have done: they looked at a seeded random half of each incident's tickets (83 tickets), attached each to its incident, and linked it to two tickets of a *different* feature of the same incident (`SameIncident`, 160 links). One in ten of them also drew one *wrong* link to a ticket outside the incident (8 links, `kind: misfiled`). The links have a clear meaning ("same outage"), they join different symptoms, and they are partial and partly wrong, as hand-made links are. The old step-6 `Related` edges (each ticket to the two previous tickets of the same product) are kept as an ablation.

**A caveat that matters.** The incident definition is also the source of the "same outage" labels, so a perfect link set would let a graph recover those labels by construction. The links are deliberately incomplete and noisy so that the experiment measures how much a ranker actually gets from such links, not whether links can encode the answer.

**Strategies.** All score the same questions. A strategy receives the question text and its vector, nothing else.

| Strategy | What it does |
|---|---|
| Lexical only | `search_text` on subject and body, subject weighted 2.0 |
| Hybrid | `search_hybrid`, text plus stored vectors, rank fusion, `candidate_k=100` |
| Hybrid + graph | Hybrid, plus graph evidence over `SameIncident` links: both directions, 2 hops, weight 0.5. **Seeds are the top 3 lexical hits for the same question**, which are known at query time. |
| Ablation | The same, over the old same-product `Related` edges |

No product id, article id, incident id, question intent or label reaches a strategy. The old design passed the correct `product_id` of each question to pick graph seeds. That is gone. `tests/test_evaluation.py` parses `ticketgraph/retrieval.py` and fails if it names any such field, and checks the entry-point signatures. The labels are read only after retrieval, to score.

The graph weight (0.5) and the number of seeds (3) were fixed before the first run and were not tuned. A weight sweep is reported below as sensitivity only.

**Metrics** (`ticketgraph/metrics.py`, binary relevance, hand-computed test values in `tests/test_metrics.py`): Precision@K, Recall@K, MRR (cutoff 10) and nDCG@K, averaged over questions. Relevant sets are large (5 to 52 tickets), so Recall@10 cannot reach 1.0: the table header gives the best any ranking could do.

## Results

<!-- generated:eval-full run=20261029T190205Z-a5ad197-dirty -->
**All 36 questions** (best possible Recall@10 for any ranking: 0.602)

| Strategy | P@5 | P@10 | R@10 | R@20 | MRR | nDCG@10 |
|---|---|---|---|---|---|---|
| Lexical only | 0.694 | 0.636 | 0.416 | 0.587 | 0.737 | 0.668 |
| Hybrid (lexical + vector) | 0.856 | 0.828 | 0.514 | 0.691 | 0.897 | 0.851 |
| Hybrid + graph (incident links) | 0.789 | 0.781 | 0.485 | 0.683 | 0.808 | 0.789 |
| Ablation: hybrid + graph over same-product edges | 0.783 | 0.750 | 0.473 | 0.688 | 0.834 | 0.772 |

**24 same-problem questions** (best possible Recall@10 for any ranking: 0.789)

| Strategy | P@5 | P@10 | R@10 | R@20 | MRR | nDCG@10 |
|---|---|---|---|---|---|---|
| Lexical only | 0.758 | 0.688 | 0.561 | 0.760 | 0.762 | 0.723 |
| Hybrid (lexical + vector) | 0.900 | 0.838 | 0.677 | 0.871 | 0.912 | 0.876 |
| Hybrid + graph (incident links) | 0.825 | 0.775 | 0.636 | 0.853 | 0.840 | 0.804 |
| Ablation: hybrid + graph over same-product edges | 0.825 | 0.758 | 0.625 | 0.872 | 0.876 | 0.799 |

**12 same-outage questions** (best possible Recall@10 for any ranking: 0.230)

| Strategy | P@5 | P@10 | R@10 | R@20 | MRR | nDCG@10 |
|---|---|---|---|---|---|---|
| Lexical only | 0.567 | 0.533 | 0.126 | 0.241 | 0.686 | 0.559 |
| Hybrid (lexical + vector) | 0.767 | 0.808 | 0.186 | 0.331 | 0.867 | 0.802 |
| Hybrid + graph (incident links) | 0.717 | 0.792 | 0.183 | 0.344 | 0.746 | 0.758 |
| Ablation: hybrid + graph over same-product edges | 0.700 | 0.733 | 0.169 | 0.321 | 0.750 | 0.718 |

Question by question, nDCG@10 of hybrid + graph against plain hybrid:

| Questions | Improved | Unchanged | Worse |
|---|---|---|---|
| All 36 | 4 | 16 | 16 |
| 24 same-problem | 2 | 12 | 10 |
| 12 same-outage | 2 | 4 | 6 |
<!-- /generated -->

Sensitivity of the graph weight (nDCG@10; the weight used above is 0.5):

<!-- generated:eval-sweep run=20261029T190205Z-a5ad197-dirty -->
| Graph weight | All 36 | 24 same-problem | 12 same-outage |
|---|---|---|---|
| none (plain hybrid) | 0.851 | 0.876 | 0.802 |
| 0.25 | 0.820 | 0.843 | 0.774 |
| 0.5 | 0.789 | 0.804 | 0.758 |
| 1.0 | 0.771 | 0.774 | 0.765 |
| 2.0 | 0.729 | 0.705 | 0.776 |
<!-- /generated -->

## What the numbers say

- **Hybrid beat lexical on every metric and every group.** All 36 questions: nDCG@10 0.851 against 0.668. This is the result that supports the case for hybrid search, on this data.
- **Graph evidence did not improve on plain hybrid.** Over all 36 questions it lowered every headline metric a little (nDCG@10 0.851 to 0.789). Question by question it improved 4, left 16 unchanged and made 16 worse. On the 12 same-outage questions, where the links should matter most, it improved 2, left 4 unchanged and made 6 worse. Recall@20 on those questions rose from 0.331 to 0.344, and MRR fell from 0.867 to 0.746.
- **No weight tested beat plain hybrid overall.** Over all 36 questions a lower weight is closer to plain hybrid and a higher one is worse. On the 12 same-outage questions the sweep is flat (0.774, 0.758, 0.765 and 0.776 at weights 0.25, 0.5, 1.0 and 2.0) and all of it is below plain hybrid (0.802).
- **The old same-product edges did no better.** The ablation's nDCG@10 is 0.772, against 0.789 for the incident links and 0.851 for plain hybrid.
- With 36 questions and no significance test, small differences (for example Recall@20 0.331 against 0.344) are not evidence of anything. The drop in nDCG@10 (0.062) and MRR (0.089) is larger, and graph evidence made 16 questions worse against 4 better, but 36 questions on one invented fixture is still a small sample.

## Where the graph helped, and where it did not

All of this is read from `per_query` and `graph_comparison` in the recorded JSON. "Relevant" means relevant under the labels above.

**Helped**

- *"folder upload frozen near the end"* (same problem: sync stall). nDCG@10 +0.236, first relevant result moved from rank 7 to rank 5. The three seeds were photo-upload tickets, which are **not** relevant to this question. They belong to the same storage-migration incident as the sync-stall feature, so five relevant sync-stall tickets entered the top 10 and five other tickets left it. The graph score is the only difference between the hybrid run and the graph run, so those five came in through graph distance. The graph worked here through a wrong seed that happened to sit in the right incident, not through a good one.
- *"notification emails delayed by an hour"* (same outage). nDCG@10 +0.091. The seeds were relevant alert-rule tickets, and their links brought two relevant dunning-email tickets (another feature of the same incident) into the top 10. This is the intended use of the links.

**Mixed**

- *"two versions of a file created after being offline"*. nDCG@10 +0.068, from a reordering (first relevant result from rank 2 to rank 1). The only ticket that entered the top 10 (invoice export) is not relevant, and one relevant ticket left.

**Hurt**

- *"refund is stuck and has not arrived"* (same problem). nDCG@10 -0.469, first relevant result moved from rank 1 to rank 4. The lexical top 3 were photo-upload tickets ("upload queue is stuck"). Using them as seeds boosted them into the top 10 and pushed three relevant refund tickets out. **Graph evidence from a wrong seed amplifies the mistake.**
- *"currency symbol on invoice is wrong"* (same problem). nDCG@10 -0.401. The seeds were relevant. Their incident links brought five invoice-tax tickets, which belong to the same incident but to a different feature, and pushed five relevant currency tickets out. The same links that help a same-outage question hurt a same-problem question: the graph cannot know which intent the person has.
- *"transactional emails are not being delivered"* (same outage). nDCG@10 -0.359. The top lexical hits were webhook-retry tickets ("not retried", "delivered five times"), so the seeds were wrong and the relevant dunning-email tickets left the top 10.

## Limits of this evaluation

- Invented data, near-duplicate tickets (each feature has three symptoms), one embedding model, one Grafx version, 36 questions, labels by construction and not human-reviewed. It supports statements about this fixture and the way graph evidence is configured here. It does not support "graph search is better or worse" in general.
- The seeds come from lexical search. A different seed rule (for example the top hybrid hits, or an entity the user names) was not tried and could give a different answer.
- `candidate_k` bounds what the graph can do, because Grafx's graph evidence only re-ranks rows that the text or vector index already proposed. See [PRODUCT-OBSERVATIONS.md](PRODUCT-OBSERVATIONS.md).
- The article-level numbers in the JSON (articles ranked by the tickets above them) are reported for completeness and are not discussed here.
