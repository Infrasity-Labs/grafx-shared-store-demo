# Model review of eval_qrels.json (DRAFT, model-labelled, not human)

Labeler: claude-sonnet-5-5 (omp subagent). Data was produced by Claude models (same vendor family): not independent. A person must spot-check.

## Counts
- 36 questions: 16 ok (f01-f05, f07-f10, f13-f17, f19, f21), 20 need a change (f06, f11, f12, f18, f20, f22, f23, f24, i01-i12).
- Proposed: 172 removals, 20 additions (10 each for i04, i05: refund tickets "the refund email never reached the customer").
- "Remove" means neither of the ticket's two symptom sentences relates to the question. Tickets graded weak are kept.
- Same-problem (f) questions: the key is mostly sound. Where it is not, the feature has symptoms the question does not describe (e.g. f12 "not redelivered" vs "delivered five times", f20 currency symbol vs exchange rate).
- Incident (i) questions: the key is much looser. Roughly a fifth to a half of the listed tickets have no connection to the question text (i06, i09, i04, i05, i07 worst).

## Systematic problems in how the key is built
1. Labels are per feature (article_id), not per symptom. Each feature has three different symptoms and the key treats all three as relevant to any question about the feature. A question matches one symptom (e.g. "api credential rejected" matches 1 of 3 api key symptoms; 6 of 14 listed tickets do not match).
2. Incident questions: the key takes every ticket of every feature of an invented incident. The ticket text never mentions an outage. A feature's symptoms (api key "last used time", dunning "wrong company name", storage "charged for extra storage", invoice export "times out") often have nothing to do with the outage-style question. Incident membership is asserted only by the script.
3. Incident questions are phrased around one symptom (e.g. i06 "emails delayed by an hour" matches only "alert emails arrive an hour late"), yet i01-i03, i04-i06, i07-i09 and i10-i12 each share one identical key per incident. Three questions per incident get the same relevance set regardless of wording.
4. Incident 4 (rates and tax feed) has all tickets (47) in one product (Marrow Billing, product 2). A same-product baseline recovers that key, so graph/product evidence cannot be distinguished from product match there. The other incidents span 2-3 products (inc. 3: products 1 and 5).
5. Boilerplate: every ticket body is opener + symptom + "Also" + symptom (163 of 500 repeat the same symptom twice) + a stock ask. The same ask/opener sentences appear across features, so lexical overlap on boilerplate is not a relevance signal. The key does not use text, so this does not enter the labels, but it affects how meaningful retrieval scores are.
6. Articles: each article states only one symptom plus generic steps ("Check the account status first..."). The key lists whole-feature articles; for incident questions (3 articles each) only the article whose symptom matches really answers it. Not itemized per question; article judgements are at feature level only.
7. Missing relevant items are rare: the word-overlap scan and manual check found missing items only for i04/i05 (refund email not reached). i12 "invoice numbers" may also match credit note "number skips a value"; not added (ambiguous).

## Checked
- eval_qrels.json equals the rule in scripts/make_fixtures.py applied to fixtures/tickets.jsonl (verified by script).
- Every ticket in tickets.jsonl parses to two symptoms of its recorded feature; no symptom text is shared between features.

## Least certain
f02 (folder vs sync stall), f21 (sign in on second computer), i02, i06, i09, i12, i03, i04 (weak dunning/alert), i10 (currency symbol), f16 (biometric weak). See each note.
