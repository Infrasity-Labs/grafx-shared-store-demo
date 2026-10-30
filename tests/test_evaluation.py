"""The retrieval evaluation: labels follow their stated rule, retrieval sees no ground truth, scoring is right."""
import ast
import importlib.util
import json
import unittest
from pathlib import Path

from ticketgraph import evaluate, metrics, retrieval
from ticketgraph.common import FIXTURES, load_eval_qrels, load_eval_questions, load_eval_vectors, read_jsonl

ROOT = Path(__file__).resolve().parent.parent


def make_fixtures_module():
    spec = importlib.util.spec_from_file_location("make_fixtures", ROOT / "scripts" / "make_fixtures.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class NoLeakage(unittest.TestCase):
    """retrieval.py is the only code a strategy runs. It must not even name a label or a ground-truth field."""

    FORBIDDEN = ("qrel", "label", "intent", "product_id", "article_id", "relevant", "expected", "fixtures", "target")

    def names(self):
        tree = ast.parse((ROOT / "ticketgraph" / "retrieval.py").read_text())
        found = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                found.add(node.id)
            elif isinstance(node, ast.Attribute):
                found.add(node.attr)
            elif isinstance(node, ast.arg):
                found.add(node.arg)
            elif isinstance(node, ast.keyword) and node.arg:
                found.add(node.arg)
            elif isinstance(node, ast.Import):
                found.update(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                found.add(node.module or "")
                found.update(a.name for a in node.names)
        return {n.lower() for n in found}

    def test_retrieval_names_no_ground_truth_field(self):
        for name in self.names():
            for bad in self.FORBIDDEN:
                self.assertNotIn(bad, name, f"retrieval.py mentions {name!r}")

    def test_strategy_entry_points_take_only_query_text_and_vector(self):
        import inspect
        self.assertEqual(list(inspect.signature(retrieval.lexical).parameters), ["db", "directory", "text", "k"])
        self.assertEqual(list(inspect.signature(retrieval.hybrid).parameters),
                         ["db", "directory", "text", "vector", "k", "graph", "candidate_k", "exclude"])
        self.assertEqual(list(inspect.signature(evaluate.run_strategy).parameters),
                         ["db", "directory", "name", "text", "vector", "graph_weight"])

    def test_questions_file_carries_no_labels_for_retrieval(self):
        for q in load_eval_questions():
            self.assertEqual(set(q), {"id", "text", "intent"})


class LabelsFollowTheRule(unittest.TestCase):
    def setUp(self):
        self.mf = make_fixtures_module()
        self.tickets = read_jsonl(FIXTURES / "tickets.jsonl")

    def test_qrels_file_equals_the_rule_applied_to_the_fixtures(self):
        self.assertEqual(load_eval_qrels(), json.loads(json.dumps(self.mf.qrels(self.tickets))))

    def test_incident_graph_file_equals_the_rule_applied_to_the_fixtures(self):
        self.assertEqual(json.loads((FIXTURES / "incident_graph.json").read_text()),
                         json.loads(json.dumps(self.mf.incident_graph(self.tickets))))

    def test_questions_file_matches_the_script(self):
        want = [{"id": q, "text": t, "intent": i} for q, t, i, _ in self.mf.EVAL_QUESTIONS]
        self.assertEqual(load_eval_questions(), want)

    def test_every_question_has_relevant_tickets_and_articles(self):
        for qid, row in load_eval_qrels().items():
            self.assertTrue(row["tickets"], qid)
            self.assertTrue(row["articles"], qid)
            self.assertEqual(row["intent"] == "feature", len(row["articles"]) == 1, qid)

    def test_feature_labels_are_the_tickets_generated_from_that_feature(self):
        by_article = {}
        for t in self.tickets:
            by_article.setdefault(t["article_id"], set()).add(t["id"])
        for qid, row in load_eval_qrels().items():
            want = set().union(*(by_article[a] for a in row["articles"]))
            self.assertEqual(set(row["tickets"]), want, qid)

    def test_incidents_cover_several_features_and_never_share_one(self):
        doc = json.loads((FIXTURES / "incident_graph.json").read_text())
        article_product = {a["id"]: a["product_id"] for a in read_jsonl(FIXTURES / "articles.jsonl")}
        seen, crossing = set(), 0
        for incident in doc["incidents"]:
            self.assertGreaterEqual(len(incident["features"]), 3, incident["name"])
            self.assertFalse(seen & set(incident["features"]))
            seen |= set(incident["features"])
            crossing += len({article_product[a] for a in incident["features"]}) >= 2
        self.assertEqual(crossing, 3, "three incidents cross products, the rates and tax feed one stays in Marrow Billing")

    def test_graph_links_connect_real_tickets_and_misfiled_ones_leave_the_incident(self):
        doc = json.loads((FIXTURES / "incident_graph.json").read_text())
        article_of = {t["id"]: t["article_id"] for t in self.tickets}
        features = {i["id"]: set(i["features"]) for i in doc["incidents"]}
        for link in doc["links"]:
            self.assertIn(link["a"], article_of)
            self.assertIn(link["b"], article_of)
            inside = article_of[link["b"]] in features[link["incident"]]
            self.assertEqual(link["kind"] == "same_incident", inside, link)
            if link["kind"] == "same_incident":
                self.assertNotEqual(article_of[link["a"]], article_of[link["b"]], "links join different features")
        self.assertTrue(any(l["kind"] == "misfiled" for l in doc["links"]), "the graph must contain wrong links")

    def test_no_question_is_copied_from_a_ticket(self):
        subjects = {t["subject"].lower() for t in self.tickets}
        sentences = set()
        for t in self.tickets:
            for part in t["body"].replace("Also, ", "").split(". "):
                sentences.add(part.strip(" .").lower())
        for q in load_eval_questions():
            text = q["text"].lower()
            self.assertNotIn(text, sentences, q["id"])
            self.assertFalse(any(text in s for s in subjects), q["id"])

    def test_every_question_and_incoming_ticket_has_a_vector(self):
        vectors = load_eval_vectors()
        for q in load_eval_questions():
            self.assertEqual(len(vectors["questions"][q["id"]]), 384, q["id"])
        for t in json.loads((FIXTURES / "incoming_tickets.json").read_text()):
            self.assertEqual(len(vectors["incoming"][str(t["id"])]), 384)


class Scoring(unittest.TestCase):
    def test_article_ranking_votes_by_rank(self):
        ranking = evaluate.article_ranking([10, 11, 12], {10: 1, 11: 2, 12: 2})
        self.assertEqual(ranking, [1, 2], "article 1: 1/1 beats article 2: 1/2 + 1/3")
        self.assertEqual(evaluate.article_ranking([10, 11, 12, 13], {10: 1, 11: 2, 12: 2, 13: 2}), [2, 1],
                         "1/2 + 1/3 + 1/4 beats 1/1")
        self.assertEqual(evaluate.article_ranking([10], {}), [])

    def test_score_run_means_per_group(self):
        questions = [{"id": "a", "intent": "feature"}, {"id": "b", "intent": "incident"}]
        qrels = {"a": {"tickets": [1], "articles": [7]}, "b": {"tickets": [9], "articles": [7]}}
        results = {"a": {"hits": [{"ticket_id": 1}, {"ticket_id": 2}]}, "b": {"hits": [{"ticket_id": 2}]}}
        per_query, summary = evaluate.score_run(results, qrels, {1: 7, 2: 8}, questions)
        self.assertEqual(per_query["a"]["mrr"], 1.0)
        self.assertEqual(per_query["b"]["mrr"], 0.0)
        self.assertAlmostEqual(summary["all"]["tickets"]["mrr"], 0.5)
        self.assertEqual(summary["feature"]["questions"], 1)
        self.assertAlmostEqual(summary["feature"]["articles"]["recall@3"], 1.0)
        self.assertAlmostEqual(summary["incident"]["articles"]["recall@3"], 0.0, msg="ticket 2 mentions article 8")

    def test_compare_graph_labels_improved_worse_and_unchanged(self):
        questions = [{"id": q, "text": q, "intent": "feature"} for q in "abc"]
        qrels = {q: {"tickets": [1]} for q in "abc"}
        tickets = {i: {"subject": f"t{i}"} for i in (1, 2, 3)}

        def res(*ids, seeds=()):
            return {"hits": [{"ticket_id": i} for i in ids], "seeds": list(seeds)}
        base = {"a": res(2, 1), "b": res(1, 2), "c": res(1)}
        graph = {"a": res(1, 2), "b": res(2, 1), "c": res(1)}
        out = evaluate.compare_graph(base, graph, qrels, questions, tickets)
        self.assertEqual(out["counts"], {"improved": 1, "unchanged": 1, "worse": 1})
        self.assertEqual([r["id"] for r in out["largest_gains"]], ["a"])
        self.assertEqual([r["id"] for r in out["largest_losses"]], ["b"])


class RecordedEvaluation(unittest.TestCase):
    """If an evaluation is recorded under runs/, its numbers must be what scoring the stored rankings gives."""

    def test_recorded_metrics_equal_a_recomputation_from_the_recorded_rankings(self):
        files = sorted((ROOT / "runs").glob("*/scenario_eval.json")) if (ROOT / "runs").exists() else []
        if not files:
            self.skipTest("no recorded evaluation")
        qrels = load_eval_qrels()
        for path in files:
            result = json.loads(path.read_text())["result"]
            for name, per_query in result["per_query"].items():
                rows = []
                for qid, row in per_query.items():
                    rel = set(qrels[qid]["tickets"])
                    self.assertAlmostEqual(metrics.ndcg_at_k(row["ranked_top10"], rel, 10), row["ndcg@10"], places=9)
                    self.assertAlmostEqual(metrics.precision_at_k(row["ranked_top10"], rel, 10), row["precision@10"])
                    rows.append(row["ndcg@10"])
                self.assertAlmostEqual(sum(rows) / len(rows), result["strategies"][name]["all"]["tickets"]["ndcg@10"],
                                       places=9, msg=f"{path.parent.name} {name}")


if __name__ == "__main__":
    unittest.main()
