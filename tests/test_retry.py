"""Unit tests for the conflict retry loop. A fake database stands in for Grafx."""
import unittest
from types import SimpleNamespace

from okto_grafx.errors import GrafxWriteConflict

from ticketgraph.retry import write_with_conflict_retry


class FakeTxn:
    def __init__(self, db):
        self.db = db
        self.active = True
        self.report = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc_type is not None:
            self.active = False
            return False
        error = self.db.next_error()
        if error is not None:
            raise error  # commit refused, transaction left active
        self.active = False
        self.report = SimpleNamespace(csn=len(self.db.commits) + 1, durable=True)
        self.db.commits.append(self.report)
        return False

    def rollback(self):
        self.active = False


class FakeDb:
    def __init__(self, errors):
        self.errors = list(errors)
        self.commits = []
        self.begins = 0

    def next_error(self):
        return self.errors.pop(0) if self.errors else None

    def begin(self, mode):
        assert mode == "write"
        self.begins += 1
        return FakeTxn(self)


class RetryLoop(unittest.TestCase):
    def test_retries_conflict_then_commits_once(self):
        db = FakeDb([GrafxWriteConflict("a"), GrafxWriteConflict("b")])
        seen, pauses = [], []
        report, conflicts = write_with_conflict_retry(
            db, lambda txn: seen.append(1), pause=pauses.append, on_conflict=lambda n, e: seen.append("c"))
        self.assertEqual(conflicts, 2)
        self.assertEqual(len(db.commits), 1, "exactly one commit")
        self.assertTrue(report.durable)
        self.assertEqual(len(pauses), 2)
        self.assertTrue(all(0 <= p <= 0.5 for p in pauses))

    def test_operation_runs_again_on_a_fresh_transaction(self):
        db = FakeDb([GrafxWriteConflict("a")])
        calls = []
        write_with_conflict_retry(db, lambda txn: calls.append(txn), pause=lambda s: None)
        self.assertEqual(len(calls), 2)
        self.assertIsNot(calls[0], calls[1])

    def test_gives_up_after_attempt_budget(self):
        db = FakeDb([GrafxWriteConflict("x")] * 5)
        with self.assertRaises(GrafxWriteConflict):
            write_with_conflict_retry(db, lambda txn: None, attempts=3, pause=lambda s: None)
        self.assertEqual(db.begins, 3)
        self.assertEqual(db.commits, [])

    def test_never_replays_a_durable_commit(self):
        for details in ({"committed": True}, {"durable": True}):
            db = FakeDb([GrafxWriteConflict("late", **details)])
            with self.assertRaises(GrafxWriteConflict):
                write_with_conflict_retry(db, lambda txn: None, pause=lambda s: None)
            self.assertEqual(db.begins, 1, details)

    def test_non_retryable_flag_is_respected(self):
        db = FakeDb([GrafxWriteConflict("no", retryable=False)])
        with self.assertRaises(GrafxWriteConflict):
            write_with_conflict_retry(db, lambda txn: None, pause=lambda s: None)
        self.assertEqual(db.begins, 1)

    def test_other_errors_propagate(self):
        db = FakeDb([ValueError("boom")])
        with self.assertRaises(ValueError):
            write_with_conflict_retry(db, lambda txn: None, pause=lambda s: None)
        self.assertEqual(db.begins, 1)

    def test_attempts_must_be_positive(self):
        with self.assertRaises(ValueError):
            write_with_conflict_retry(FakeDb([]), lambda txn: None, attempts=0)


if __name__ == "__main__":
    unittest.main()
