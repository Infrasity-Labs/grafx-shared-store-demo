"""The scoreboard builder must use recorded outputs only."""
import json
import tempfile
import unittest
from pathlib import Path

from ticketgraph import scoreboard

STATE = Path(__file__).resolve().parent.parent / "demo-state"


def write(dirpath, name, result, elapsed=1.0):
    (Path(dirpath) / name).write_text(json.dumps({"elapsed_seconds": elapsed, "result": result}))


class Builder(unittest.TestCase):
    def test_small_synthetic_run(self):
        with tempfile.TemporaryDirectory() as d:
            write(d, "step02_first_load.json", {"tickets_loaded": 3, "all_durable": True})
            write(d, "step03_two_writers.json", {
                "tickets_loaded": 4, "fixture_ticket_count": 7, "counts_after": {"tickets": 7},
                "conflicts_by_importer": {"A": 1, "B": 2}, "conflicts_total": 3,
                "all_durable": True, "lost_commits": 0}, elapsed=2.5)
            board = scoreboard.build(d)
        self.assertTrue(board["tickets"]["core_count_matches_fixture"])
        self.assertEqual(board["writers"]["conflicts_total"], 3)
        self.assertEqual(board["seconds_by_step"], {"2": 1.0, "3": 2.5})
        self.assertNotIn("crash", board, "nothing is reported for a step that was not recorded")

    def test_count_mismatch_is_reported_as_false(self):
        with tempfile.TemporaryDirectory() as d:
            write(d, "step02_first_load.json", {"tickets_loaded": 3, "all_durable": True})
            write(d, "step03_two_writers.json", {
                "tickets_loaded": 4, "fixture_ticket_count": 8, "counts_after": {"tickets": 7},
                "conflicts_by_importer": {}, "conflicts_total": 0, "all_durable": True, "lost_commits": 1})
            self.assertFalse(scoreboard.build(d)["tickets"]["core_count_matches_fixture"])

    def test_recorded_closeout_matches_a_fresh_build(self):
        path = STATE / "closeout-result.json"
        if not path.exists():
            self.skipTest("no recorded run")
        self.assertEqual(json.loads(path.read_text()), json.loads(json.dumps(scoreboard.build(STATE))))


if __name__ == "__main__":
    unittest.main()
