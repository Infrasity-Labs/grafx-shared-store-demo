"""The triage decision rule, on hand-made evidence."""
import unittest

from ticketgraph import triage


def evidence(products, incident=None):
    return triage.Evidence("p", (1, 2), tuple((i, f"P{i}") for i in products), incident,
                           "name" if incident else None, (1, 2))


class Decide(unittest.TestCase):
    def test_one_product_is_routine(self):
        self.assertEqual(triage.decide(evidence([1])), {"action": "routine", "escalate": False, "incident_id": None})

    def test_two_products_escalate_even_without_an_incident(self):
        d = triage.decide(evidence([1, 2]))
        self.assertTrue(d["escalate"])
        self.assertEqual(d["action"], "routine")

    def test_incident_attaches_and_escalates_when_it_spans_products(self):
        self.assertEqual(triage.decide(evidence([1, 4, 5], incident=3)),
                         {"action": "attach_to_incident", "escalate": True, "incident_id": 3})

    def test_incident_in_one_product_attaches_without_escalating(self):
        self.assertEqual(triage.decide(evidence([1], incident=3)),
                         {"action": "attach_to_incident", "escalate": False, "incident_id": 3})


if __name__ == "__main__":
    unittest.main()
