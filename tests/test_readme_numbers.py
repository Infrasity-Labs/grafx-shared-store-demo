"""Numbers in the README and docs must be the numbers in the recorded JSON."""
import json
import re
import unittest
from pathlib import Path

from ticketgraph import render

ROOT = Path(__file__).resolve().parent.parent
README = (ROOT / "README.md").read_text(encoding="utf-8")


def board():
    return json.loads((ROOT / "demo-state" / "closeout-result.json").read_text())


def step(n, name):
    return json.loads((ROOT / "demo-state" / name).read_text())["result"]


def thousands(n):
    return f"{n:,}"


class ReferenceTable(unittest.TestCase):
    """The 'Grafx in Action' table cites demo-state/closeout-result.json."""

    def test_tickets_and_commits(self):
        t = board()["tickets"]
        self.assertIn(f"{t['step2_loaded']} in step 2 and {t['step3_loaded']} in step 3. The store held "
                      f"{t['core_count_in_store_after_step3']}, and the fixture has {t['core_fixture_count']}.", README)

    def test_conflicts(self):
        w = board()["writers"]
        by = w["conflicts_by_importer"]
        self.assertIn(f"{w['conflicts_total']} total: Importer A {by['A']}, Importer B {by['B']}.", README)

    def test_snapshot(self):
        s = board()["stale_snapshot"]
        self.assertIn(f"It showed {s['old_snapshot_tickets_before']} tickets before and after another process "
                      f"committed {s['new_read_tickets'] - s['old_snapshot_tickets_before']} more. "
                      f"A new read showed {s['new_read_tickets']}.", README)

    def test_crash(self):
        c = board()["crash"]
        self.assertIn(f"{c['committed_tickets_found']} of {c['committed_expected']} committed tickets found. "
                      f"{c['unfinished_batch_found']} of 10 unfinished tickets found.", README)
        self.assertIn(f"Recovery outcome: `{c['recovery_outcome']}`", README)

    def test_replayed_records(self):
        r = step(5, "step05_kill_and_recover.json")["recovery_report"]
        self.assertIn(f"{r['records_replayed']} committed records were replayed", README)

    def test_search(self):
        t = board()["text_search"]
        self.assertIn(f"{t['keyword_with_hits']} of {t['keyword_questions']} keyword questions and "
                      f"{t['phrase_with_hits']} of {t['phrase_questions']} phrase questions returned hits.", README)
        h = board()["hybrid"]
        self.assertIn(f"The top result changed for {h['top1_changed_with_graph']} of {h['questions']} questions with "
                      f"graph evidence, and for {h['top1_changed_no_graph']} of {h['questions']} without it. "
                      f"The top 5 set changed for {h['top5_set_changed_with_graph']} of {h['questions']}.", README)

    def test_backup_and_export(self):
        b = board()["backup_restore"]
        self.assertIn(f"{b['backup_files']} files, {thousands(b['backup_payload_bytes'])} bytes.", README)
        self.assertIn(f"{thousands(b['logical_rows_exported'])} rows out and {thousands(b['logical_rows_imported'])} in.", README)

    def test_seconds_row(self):
        secs = board()["seconds_by_step"]
        row = "| Seconds | " + " | ".join(f"{secs[str(n)]:.1f}" for n in range(1, 11)) + " |"
        self.assertIn(row, README)

    def test_conclusion_conflicts(self):
        self.assertIn(f"the {board()['writers']['conflicts_total']} write conflicts were retried", README)


class GeneratedBlocks(unittest.TestCase):
    """Tables that are rendered from a recorded run must equal what that run recorded."""

    def test_every_generated_block_matches_its_run(self):
        runs_root = ROOT / "runs"
        blocks = 0
        for path in [ROOT / "README.md"] + sorted((ROOT / "docs").glob("*.md")):
            text = path.read_text(encoding="utf-8")
            found = render.BLOCK.findall(text)
            blocks += len(found)
            for m in render.BLOCK.finditer(text):
                self.assertTrue((runs_root / m["run"]).is_dir(), f"{path.name}: run {m['run']} is not in runs/")
            self.assertEqual(render.render_file(path, runs_root), [], path.name)
        self.assertGreaterEqual(blocks, 4, "README and docs should carry generated tables")

    def test_readme_names_the_run_it_quotes(self):
        for m in render.BLOCK.finditer(README):
            self.assertIn(m["run"], README)


if __name__ == "__main__":
    unittest.main()
