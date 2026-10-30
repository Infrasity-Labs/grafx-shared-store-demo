"""End-to-end runs of the scenarios with real processes and real SIGKILLs. About a minute.

Skipped unless GRAFX_E2E=1. The full integration workflow (.github/workflows/integration.yml) runs the same
scenarios through run_scenarios.py and checks them with scripts/assert_full_run.py.
"""
import os
import tempfile
import unittest
from pathlib import Path

from ticketgraph import evaluate, resume_demo, workflow

E2E = os.environ.get("GRAFX_E2E") == "1"


@unittest.skipUnless(E2E, "set GRAFX_E2E=1 to run the end-to-end scenarios")
class Scenarios(unittest.TestCase):
    def test_resume_demo(self):
        with tempfile.TemporaryDirectory() as d:
            result = resume_demo.run(workdir=Path(d) / "w")
        self.assertTrue(result["ok"], result["final_verification"])
        self.assertEqual([p["returncode"] for p in result["phases"]], [-9, -9, 0, 0])

    def test_workflow_with_faults(self):
        with tempfile.TemporaryDirectory() as d:
            result = workflow.run(workdir=Path(d) / "w")
        self.assertTrue(result["ok"], result["checks"])
        self.assertTrue(result["decisions"]["3001"]["graph_changed_decision"])
        self.assertFalse(result["decisions"]["3002"]["graph_changed_decision"])

    def test_evaluation_is_deterministic_and_scores_every_strategy(self):
        with tempfile.TemporaryDirectory() as d:
            first = evaluate.run(workdir=Path(d) / "a")
            second = evaluate.run(workdir=Path(d) / "b")
        self.assertEqual(first["strategies"], second["strategies"])
        self.assertEqual(set(first["strategies"]), set(evaluate.STRATEGIES))


if __name__ == "__main__":
    unittest.main()
