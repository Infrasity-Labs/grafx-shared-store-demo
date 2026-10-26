"""Conflict-only retry loop, following the recipe in the Grafx Operations doc.

Rules it keeps:
- Only a GrafxWriteConflict that is retryable and not committed is retried.
- A commit that is already durable is never replayed.
- Any other error is raised as it is.
"""
import random
import time

from okto_grafx.errors import GrafxWriteConflict


def write_with_conflict_retry(db, operation, attempts=12, pause=time.sleep, on_conflict=None):
    """Run operation(txn) in a write transaction. Return (report, conflicts)."""
    if attempts < 1:
        raise ValueError("attempts must be positive")
    conflicts = 0
    for attempt in range(attempts):
        txn = None
        cleanup_complete = False
        try:
            try:
                with db.begin("write") as txn:
                    operation(txn)
            finally:
                if txn is not None and txn.active:
                    txn.rollback()
                cleanup_complete = True
            return txn.report, conflicts
        except GrafxWriteConflict as error:
            details = error.details or {}
            already_durable = (
                details.get("committed")
                or details.get("durable")
                or (txn is not None and txn.report is not None and txn.report.durable)
            )
            if (not cleanup_complete or already_durable
                    or not details.get("retryable", error.retryable)
                    or attempt + 1 == attempts):
                raise
            conflicts += 1
            if on_conflict is not None:
                on_conflict(attempt + 1, error)
            pause(random.uniform(0, min(0.05 * 2**attempt, 0.5)))
