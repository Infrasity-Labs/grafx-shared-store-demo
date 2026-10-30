"""Run ids, manifests, refusing to overwrite, scoreboard-to-run linkage and run comparison."""
import json
import tempfile
import unittest
from pathlib import Path

from ticketgraph import runs, scoreboard

ROOT = Path(__file__).resolve().parent.parent


def write(dirpath, name, result, run_id=None, elapsed=1.0):
    doc = {"elapsed_seconds": elapsed, "result": result}
    if run_id:
        doc["run_id"] = run_id
    (Path(dirpath) / name).write_text(json.dumps(doc))


class RunIds(unittest.TestCase):
    def test_run_id_from_time_and_commit(self):
        import datetime
        now = datetime.datetime(2026, 10, 30, 12, 0, 5, tzinfo=datetime.timezone.utc)
        self.assertEqual(runs.new_run_id({"sha": "abcdef0123", "dirty": False}, now), "20261030T120005Z-abcdef0")
        self.assertEqual(runs.new_run_id({"sha": "abcdef0123", "dirty": True}, now), "20261030T120005Z-abcdef0-dirty")
        self.assertEqual(runs.new_run_id({"sha": None, "dirty": None}, now), "20261030T120005Z-0000000")

    def test_run_id_validation(self):
        runs.check_run_id("20261030T120005Z-abcdef0")
        runs.check_run_id("release-check_1")
        for bad in ("", "../x", "a/b", "x" * 80, "has space"):
            with self.assertRaises(ValueError):
                runs.check_run_id(bad)

    def test_absolute_paths_do_not_reach_the_manifest(self):
        self.assertEqual(runs.sanitize_args(["--steps", "1", "--workdir", "/tmp/some/where"]),
                         ["--steps", "1", "--workdir", "<path>/where"])


class Manifest(unittest.TestCase):
    def test_start_then_resume_same_run_and_refuse_another(self):
        with tempfile.TemporaryDirectory() as d:
            m = runs.start_or_resume(d, "r1", "t", {"steps": [1]}, "0.0.8")
            self.assertEqual((m["run_id"], m["status"], m["grafx_version"]), ("r1", "running", "0.0.8"))
            for field in ("python", "platform", "machine", "commit", "started_at", "grafx_pinned_in_requirements"):
                self.assertIn(field, m)
            runs.finish(d, "complete")
            self.assertEqual(runs.load_manifest(d)["status"], "complete")
            runs.start_or_resume(d, "r1", "t", {"steps": [5]}, "0.0.8")
            self.assertEqual(runs.load_manifest(d)["config"]["resumed_with"], {"steps": [5]})
            with self.assertRaises(RuntimeError):
                runs.start_or_resume(d, "r2", "t", {}, "0.0.8")

    def test_refuses_a_folder_with_recorded_outputs_and_no_manifest(self):
        with tempfile.TemporaryDirectory() as d:
            write(d, "step01_setup.json", {})
            with self.assertRaises(RuntimeError) as ctx:
                runs.start_or_resume(d, "r1", "t", {}, "0.0.8")
            self.assertIn("reference", str(ctx.exception))

    def test_committed_reference_is_untouchable_by_default(self):
        with self.assertRaises(RuntimeError):
            runs.start_or_resume(ROOT / "demo-state", "new-run", "t", {}, "0.0.8")

    def test_a_complete_run_stays_complete_when_a_later_invocation_adds_to_it(self):
        self.assertEqual(runs.status_after(None, False), "partial")
        self.assertEqual(runs.status_after("partial", False), "partial")
        self.assertEqual(runs.status_after("complete", False), "complete")
        self.assertEqual(runs.status_after("partial", True), "complete")

    def test_pinned_version_is_read_from_requirements(self):
        self.assertEqual(runs.pinned_grafx(), "0.0.8")


class ScoreboardNamesItsRun(unittest.TestCase):
    def state(self, d, run_id, step_run_id):
        runs.start_or_resume(d, run_id, "t", {}, "0.0.8")
        write(d, "step02_first_load.json", {"tickets_loaded": 3, "all_durable": True}, step_run_id)
        write(d, "step03_two_writers.json", {
            "tickets_loaded": 4, "fixture_ticket_count": 7, "counts_after": {"tickets": 7},
            "conflicts_by_importer": {"A": 1}, "conflicts_total": 1, "all_durable": True, "lost_commits": 0},
            step_run_id)

    def test_scoreboard_carries_the_run_reference(self):
        with tempfile.TemporaryDirectory() as d:
            self.state(d, "r1", "r1")
            board = scoreboard.build(d)
        self.assertEqual(board["run"]["run_id"], "r1")
        self.assertEqual(board["run"]["manifest"], "run-manifest.json")
        self.assertEqual(board["run"]["step_files"], ["step02_first_load.json", "step03_two_writers.json"])

    def test_scoreboard_refuses_steps_from_another_run(self):
        with tempfile.TemporaryDirectory() as d:
            self.state(d, "r1", "other")
            with self.assertRaises(ValueError):
                scoreboard.build(d)

    def test_reference_without_manifest_has_no_run_key(self):
        with tempfile.TemporaryDirectory() as d:
            write(d, "step02_first_load.json", {"tickets_loaded": 3, "all_durable": True})
            self.assertNotIn("run", scoreboard.build(d))


class Compare(unittest.TestCase):
    def test_compare_labels_differences(self):
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            (Path(a) / "closeout-result.json").write_text(json.dumps(
                {"writers": {"conflicts_total": 7, "lost_commits": 0}, "seconds_by_step": {"1": 0.5},
                 "crash": {"verify_findings": 0}}))
            (Path(b) / "closeout-result.json").write_text(json.dumps(
                {"writers": {"conflicts_total": 5, "lost_commits": 1}, "seconds_by_step": {"1": 0.7},
                 "crash": {"verify_findings": 0}, "extra": 1}))
            report = runs.compare_runs(a, b)
        kinds = {r["key"]: r["kind"] for r in report["rows"] if not r["same"]}
        self.assertEqual(kinds, {"writers.conflicts_total": "contention", "writers.lost_commits": "invariant",
                                 "seconds_by_step.1": "timing", "extra": "invariant"})
        self.assertEqual(report["summary"]["differences_by_kind"]["invariant"], 2)
        self.assertEqual(report["manifest"]["run_id"]["a"][:12], "<no manifest")

    def test_classify_booleans_named_after_identity_are_still_invariants(self):
        self.assertEqual(runs.classify("backup_restore.restored_same_uuid"), "invariant")
        self.assertEqual(runs.classify("backup_restore.fork_new_uuid"), "invariant")
        self.assertEqual(runs.classify("crash.killed_pid"), "identity")
        self.assertEqual(runs.classify("backup_restore.restored_dir_bytes"), "size")

    def test_the_two_committed_reference_runs_compare(self):
        report = runs.compare_runs(ROOT / "demo-state", ROOT / "demo-state" / "macos-arm64")
        self.assertGreater(report["summary"]["keys_compared"], 20)


if __name__ == "__main__":
    unittest.main()
