"""Check the recorded step outputs in demo-state/. These tests need no Grafx install."""
import json
import unittest
from pathlib import Path

STATE = Path(__file__).resolve().parent.parent / "demo-state"


def step(name):
    path = STATE / name
    if not path.exists():
        raise unittest.SkipTest(f"{name} not recorded yet")
    return json.loads(path.read_text())["result"]


class Step1(unittest.TestCase):
    def test_setup(self):
        r = step("step01_setup.json")
        self.assertEqual(r["verify_findings"], 0)
        self.assertEqual(len(r["tables"]), 10)
        self.assertTrue(r["identity_indexes"] and r["commit_history"])
        self.assertEqual(sorted(r["tables"]), sorted(r["system_history_tables"]))


class Step2(unittest.TestCase):
    def test_first_load(self):
        r = step("step02_first_load.json")
        self.assertEqual(r["tickets_loaded"], 200)
        self.assertTrue(r["all_durable"])
        self.assertEqual((r["counts"]["articles"], r["counts"]["customers"], r["counts"]["products"]), (40, 25, 5))
        self.assertEqual(r["counts"]["tickets"], 200)


class Step3(unittest.TestCase):
    def test_two_writers(self):
        r = step("step03_two_writers.json")
        self.assertEqual(r["tickets_loaded"], 300)
        self.assertEqual(r["counts_after"]["tickets"], r["fixture_ticket_count"])
        self.assertEqual(r["lost_commits"], 0)
        self.assertEqual(r["unexpected_ids"], 0)
        self.assertTrue(r["all_durable"])
        self.assertEqual(r["conflicts_total"], sum(r["conflicts_by_importer"].values()))
        self.assertEqual(r["verify_findings"], 0)
        self.assertEqual(len(set(r["pids"].values())), 2, "two separate processes")


class Step4(unittest.TestCase):
    def test_snapshot(self):
        r = step("step04_snapshot_reads.json")
        self.assertTrue(r["old_snapshot_unchanged"])
        self.assertTrue(r["new_read_saw_commit"])
        self.assertEqual(r["new_read"]["tickets"] - r["old_after"]["tickets"], r["late_tickets_loaded"])


class Step5(unittest.TestCase):
    def test_crash(self):
        r = step("step05_kill_and_recover.json")
        self.assertEqual(r["signal"], "SIGKILL")
        self.assertEqual(r["killed_returncode"], -9)
        self.assertEqual(r["committed_found"], r["committed_expected"])
        self.assertEqual(r["unfinished_found"], 0)
        self.assertEqual(r["verify_findings"], 0)
        self.assertEqual(r["opened_links_for_crash_tickets"], r["committed_expected"])


class Step6(unittest.TestCase):
    def test_text_search(self):
        r = step("step06_full_text.json")
        self.assertEqual((len(r["keyword"]), len(r["phrase"])), (10, 3))
        self.assertEqual(r["verify_findings"], 0)
        for q in r["keyword"] + r["phrase"]:
            self.assertTrue(q["hits"], q["query"])
        for q in r["phrase"]:
            self.assertEqual(q["regime"], "phrase_verified")


class Step7(unittest.TestCase):
    def test_hybrid(self):
        r = step("step07_hybrid.json")
        self.assertEqual(r["questions"], 10)
        rows = r["side_by_side"]
        self.assertEqual(r["top1_changed_with_graph"], sum(x["top1_changed_with_graph"] for x in rows))
        self.assertEqual(r["top1_changed_no_graph"], sum(x["top1_changed_no_graph"] for x in rows))
        text = step("step06_full_text.json")["keyword"]
        for row, t in zip(rows, text):
            self.assertEqual(row["text_top5"], [h["ticket_id"] for h in t["hits"]], "same questions as step 6")
        for q in r["hybrid_results"]:
            self.assertEqual(q["regime"], "complete")


class Step8(unittest.TestCase):
    def test_time_travel(self):
        r = step("step08_time_travel.json")
        self.assertEqual(r["as_of_before"]["revision"], 1)
        self.assertEqual(r["as_of_after"]["revision"], 2)
        self.assertNotEqual(r["as_of_before"]["body"], r["as_of_after"]["body"])
        self.assertEqual(len(r["versions"]), 2)
        self.assertIsNone(r["versions"][-1]["system_to"])
        self.assertEqual(r["versions"][0]["system_to"], r["versions"][1]["system_from"])
        self.assertEqual(r["diff_rows"][0]["operation"], "updated")
        self.assertEqual(r["verify_findings"], 0)


class Step9(unittest.TestCase):
    def test_backup_restore(self):
        r = step("step09_backup_restore.json")
        self.assertTrue(r["physical_backup"]["supported"], "recorded on Linux, where backup is supported")
        self.assertEqual(r["processes_alive_at_restore"], 0)
        self.assertEqual(r["restored_verify_findings"], 0)
        self.assertTrue(r["restored_counts_match"] and r["restored_same_uuid"])
        self.assertTrue(r["fork_counts_match"] and r["fork_new_uuid"])
        self.assertEqual(r["fork_verify_findings"], 0)
        self.assertEqual(r["logical_rows_exported"], r["logical_rows_imported"])
        self.assertGreater(r["backup_payload_bytes"], 0)


class Step10(unittest.TestCase):
    def test_closeout(self):
        r = step("step10_closeout.json")
        self.assertGreater(r["html_bytes"], 0)
        self.assertTrue((STATE / r["html_snapshot"]).exists())
        self.assertNotIn("<script", (STATE / r["html_snapshot"]).read_text().lower())
        names = {t["name"] for t in r["node_cli_schema"]["tables"]}
        self.assertEqual(names, {"Product", "Customer", "Article", "Ticket", "Opened", "Mentions",
                                 "About", "Covers", "Uses", "Related"})


if __name__ == "__main__":
    unittest.main()
