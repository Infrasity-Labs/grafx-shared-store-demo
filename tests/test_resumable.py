"""Resumable import: interruption points, idempotence, refusal of a changed input."""
import os
import signal
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from okto_grafx import connect

from ticketgraph import resumable, restore_check
from ticketgraph.appschema import committed_units, ensure_app_schema
from ticketgraph.common import FIXTURES, load_vectors, read_jsonl
from ticketgraph.schema import create_store


class Killed(BaseException):
    """Stands in for SIGKILL in-process: it propagates through the importer like a dead process would."""


def fake_kill(pid, sig):
    assert pid == os.getpid() and sig == signal.SIGKILL
    raise Killed


class CrashPointParsing(unittest.TestCase):
    def test_parse(self):
        self.assertIsNone(resumable.CrashPoint.parse(None).kind)
        point = resumable.CrashPoint.parse("after_commit:6")
        self.assertEqual((point.kind, point.batch), ("after_commit", 6))
        with self.assertRaises(ValueError):
            resumable.CrashPoint.parse("during:1")

    def test_only_the_named_point_fires(self):
        point = resumable.CrashPoint.parse("before_commit:2")
        with mock.patch("os.kill", fake_kill):
            point.fire("before_commit", 1, lambda *a, **k: None)
            point.fire("after_commit", 2, lambda *a, **k: None)
            with self.assertRaises(Killed):
                point.fire("before_commit", 2, lambda *a, **k: None)

    def test_ids_digest_depends_on_the_ids_in_order(self):
        a = [{"id": 1}, {"id": 2}]
        self.assertEqual(resumable.ids_digest(a), resumable.ids_digest([{"id": 1}, {"id": 2}]))
        self.assertNotEqual(resumable.ids_digest(a), resumable.ids_digest([{"id": 2}, {"id": 1}]))


class Importing(unittest.TestCase):
    rows = read_jsonl(FIXTURES / "tickets.jsonl")[:30]

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Path(self.tmp.name) / "s"
        create_store(self.store)
        with connect(self.store) as db:
            ensure_app_schema(db)
        self.vectors = load_vectors()

    def tearDown(self):
        self.tmp.cleanup()

    def run_import(self, crash=None, rows=None):
        with connect(self.store) as db:
            return resumable.run_import(db, "j", rows or self.rows, 10, self.vectors,
                                        crash=resumable.CrashPoint.parse(crash))

    def state(self):
        with connect(self.store) as db:
            tickets = db.execute("MATCH (t:Ticket) RETURN count(*)").rows[0][0]
            opened = db.execute("MATCH ()-[r:Opened]->() RETURN count(*)").rows[0][0]
            return tickets, opened, sorted(committed_units(db, "j"))

    def test_crash_before_commit_leaves_nothing_of_that_batch_and_resume_finishes(self):
        with mock.patch("os.kill", fake_kill), self.assertRaises(Killed):
            self.run_import("before_commit:1")
        self.assertEqual(self.state(), (10, 10, ["batch-00000", "static"]))
        stats = self.run_import()
        self.assertEqual(stats["skipped"], [0])
        self.assertEqual(stats["committed"], ["batch-00001", "batch-00002"])
        self.assertEqual(self.state(), (30, 30, ["batch-00000", "batch-00001", "batch-00002", "static"]))

    def test_crash_after_commit_ack_is_not_redone(self):
        with mock.patch("os.kill", fake_kill), self.assertRaises(Killed):
            self.run_import("after_commit:1")
        self.assertEqual(self.state()[0], 20, "batch 1 is committed although the importer never noticed")
        stats = self.run_import()
        self.assertEqual(stats["skipped"], [0, 1])
        self.assertEqual(self.state()[:2], (30, 30), "no duplicate tickets or links")

    def test_rerun_of_a_finished_job_changes_nothing(self):
        self.run_import()
        before = self.state()
        stats = self.run_import()
        self.assertEqual(stats["committed"], [])
        self.assertEqual(self.state(), before)

    def test_changed_input_is_refused(self):
        self.run_import()
        shifted = read_jsonl(FIXTURES / "tickets.jsonl")[1:31]
        with self.assertRaises(RuntimeError) as ctx:
            self.run_import(rows=shifted)
        self.assertIn("different input", str(ctx.exception))
        self.assertEqual(self.state()[0], 30)


class RestoreCheckComparison(unittest.TestCase):
    def fingerprint(self, csns, versions):
        return {"article_id": 1, "commit_csns": csns, "article_versions": versions}

    def test_history_preserved_needs_same_prefix_and_same_versions(self):
        v = [{"revision": 1}, {"revision": 2}]
        orig = self.fingerprint([1, 2, 3], v)
        self.assertTrue(restore_check.history_preserved(orig, self.fingerprint([1, 2, 3, 4], v)))
        self.assertFalse(restore_check.history_preserved(orig, self.fingerprint([1, 2], v)))
        self.assertFalse(restore_check.history_preserved(orig, self.fingerprint([1, 2, 3], v[:1])))
        self.assertFalse(restore_check.history_preserved(orig, self.fingerprint(None, None)))


if __name__ == "__main__":
    unittest.main()
