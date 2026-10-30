"""Tests for the opt-in workload mode: pure helpers, config validation, integrity checks, one tiny run."""
import json
import random
import tempfile
import unittest
from pathlib import Path

from okto_grafx import connect

from ticketgraph.workload import (
    apply_overrides, batch_operation, check_integrity, committed_entry, create_store, load_config,
    percentile, plan_batch, run_workload, summarize, validate_config,
)

ROOT = Path(__file__).resolve().parent.parent

BASE = {"name": "t", "writers": 2, "readers": 1, "records_per_writer": 20, "batch_size": 5,
        "contention": "shared", "hot_records": 3}


class PercentileTests(unittest.TestCase):
    def test_empty_gives_none(self):
        self.assertIsNone(percentile([], 50))
        self.assertEqual(summarize([]), {"count": 0, "min": None, "p50": None, "p95": None,
                                         "p99": None, "max": None, "mean": None})

    def test_single_element(self):
        self.assertEqual(percentile([7], 0), 7)
        self.assertEqual(percentile([7], 99), 7)
        self.assertEqual(summarize([0.007])["p95"], 7.0)

    def test_nearest_rank(self):
        values = list(range(1, 11))
        self.assertEqual(percentile(values, 0), 1)
        self.assertEqual(percentile(values, 50), 5)
        self.assertEqual(percentile(values, 95), 10)
        self.assertEqual(percentile(values, 100), 10)
        self.assertEqual(percentile(list(reversed(values)), 10), 1)

    def test_out_of_range(self):
        with self.assertRaises(ValueError):
            percentile([1], 101)

    def test_summary_in_milliseconds(self):
        s = summarize([0.001, 0.002, 0.003])
        self.assertEqual((s["count"], s["min"], s["p50"], s["max"], s["mean"]), (3, 1.0, 2.0, 3.0, 2.0))


class ConfigTests(unittest.TestCase):
    def test_defaults(self):
        cfg = validate_config(BASE)
        self.assertEqual((cfg["links_per_record"], cfg["max_attempts"], cfg["seed"]), (1, 12, 0))

    def test_missing_stop_condition(self):
        cfg = {k: v for k, v in BASE.items() if k != "records_per_writer"}
        with self.assertRaisesRegex(ValueError, "exactly one"):
            validate_config(cfg)

    def test_both_stop_conditions(self):
        with self.assertRaisesRegex(ValueError, "both were given"):
            validate_config(dict(BASE, duration_seconds=5))

    def test_duration_only(self):
        cfg = {k: v for k, v in BASE.items() if k != "records_per_writer"}
        self.assertEqual(validate_config(dict(cfg, duration_seconds=2))["duration_seconds"], 2)

    def test_bad_contention(self):
        with self.assertRaisesRegex(ValueError, "contention"):
            validate_config(dict(BASE, contention="medium"))

    def test_bad_values(self):
        for change, text in [({"writers": 0}, "writers"), ({"readers": -1}, "readers"),
                             ({"batch_size": True}, "batch_size"), ({"records_per_writer": 21}, "multiple"),
                             ({"links_per_record": 4}, "links_per_record"), ({"bogus": 1}, "unknown")]:
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, text):
                validate_config(dict(BASE, **change))

    def test_missing_required(self):
        with self.assertRaisesRegex(ValueError, "'hot_records' is required"):
            validate_config({k: v for k, v in BASE.items() if k != "hot_records"})

    def test_large_guard(self):
        big = dict(BASE, writers=8, records_per_writer=30000, batch_size=50)
        with self.assertRaisesRegex(ValueError, "--allow-large"):
            validate_config(big)
        self.assertEqual(validate_config(big, allow_large=True)["writers"], 8)

    def test_overrides(self):
        cfg = apply_overrides(BASE, ["writers=4", "name=x", "records_per_writer=none", "duration_seconds=1.5"])
        self.assertEqual((cfg["writers"], cfg["name"], cfg["duration_seconds"]), (4, "x", 1.5))
        self.assertNotIn("records_per_writer", cfg)
        with self.assertRaises(ValueError):
            apply_overrides(BASE, ["nokeyvalue"])

    def test_shipped_configs_load(self):
        paths = sorted((ROOT / "workloads").glob("*.json"))
        self.assertGreaterEqual(len(paths), 6)
        for path in paths:
            with self.subTest(path=path.name):
                cfg = load_config(path)
                self.assertTrue(cfg["description"])
                self.assertEqual(cfg["name"], path.stem)


def commit_plans(store, config, plans_by_writer):
    """Write the planned batches into the store (as the workers do) and return writer-result dicts."""
    results = []
    with connect(store) as db:
        for writer, plans in plans_by_writer.items():
            committed = []
            for plan in plans:
                with db.begin("write") as txn:
                    batch_operation(plan, writer)(txn)
                committed.append(committed_entry(plan))
            results.append({"writer": writer, "committed": committed})
    return results


class IntegrityTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.store = Path(self._tmp.name) / "store"
        self.config = validate_config(dict(BASE, links_per_record=2))
        create_store(self.store, self.config)
        plans = {}
        for writer in (1, 2):
            rng = random.Random(writer)
            plans[writer] = [plan_batch(self.config, writer, b, rng) for b in range(2)]
        self.writers = commit_plans(self.store, self.config, plans)
        self.readers = [{"partial_batch_observations": 0, "errors": {}}]

    def run_check(self):
        return check_integrity(self.store, self.writers, self.readers, self.config)

    def failing(self, result):
        return sorted(name for name, ok in result["checks"].items() if not ok)

    def test_positive(self):
        result = self.run_check()
        self.assertTrue(result["ok"], result["checks"])
        self.assertEqual(result["numbers"]["stored_records"], 20)
        self.assertEqual(result["numbers"]["stored_links"], 40)

    def test_deleted_record_is_detected(self):
        rid = self.writers[0]["committed"][0]["first_id"]
        with connect(self.store) as db:
            with db.begin("write") as txn:
                txn.execute("MATCH (r:WRecord {id: $id}) DETACH DELETE r", {"id": rid})
        result = self.run_check()
        self.assertFalse(result["ok"])
        self.assertIn("record_count", self.failing(result))
        self.assertIn("record_ids", self.failing(result))
        self.assertEqual(result["numbers"]["missing_record_ids"], 1)

    def test_lost_update_is_detected(self):
        with connect(self.store) as db:
            with db.begin("write") as txn:
                txn.execute("MATCH (h:WHot {id: 1}) SET h.version = h.version + 1")
        result = self.run_check()
        self.assertFalse(result["ok"])
        self.assertIn("hot_versions", self.failing(result))
        self.assertIn("hot_version_sum", self.failing(result))
        self.assertNotIn("record_count", self.failing(result))

    def test_partial_batch_observation_fails(self):
        self.readers = [{"partial_batch_observations": 1, "errors": {}}]
        self.assertEqual(self.failing(self.run_check()), ["no_partial_batches"])

    def test_reader_errors_fail(self):
        self.readers = [{"partial_batch_observations": 0, "errors": {"GrafxError": 2}}]
        self.assertEqual(self.failing(self.run_check()), ["no_reader_errors"])

    def test_wrong_link_is_detected(self):
        entry = self.writers[0]["committed"][0]
        entry["links"][0] = [entry["links"][0][0], 99]
        self.assertIn("link_pairs", self.failing(self.run_check()))


class EndToEndTests(unittest.TestCase):
    def test_tiny_run(self):
        config = dict(BASE, hot_records=2, seed=3)
        with tempfile.TemporaryDirectory() as tmp:
            result = run_workload(config, Path(tmp))
        integrity = result["integrity"]
        self.assertTrue(integrity["ok"], integrity)
        failed = result["failed_or_exhausted"]["batches"]
        self.assertEqual(result["throughput"]["batches_committed"] + failed, 8)
        self.assertEqual(integrity["numbers"]["stored_records"], result["throughput"]["records_committed"])
        self.assertEqual(result["commit_latency_ms"]["count"], result["throughput"]["batches_committed"])
        self.assertGreaterEqual(result["conflicts"]["attempts_total"], 8)
        self.assertEqual(len(result["pids"]["writers"]), 2)
        self.assertEqual(result["recovery"]["outcome"], "ok")
        self.assertIn("SIGKILL", result["recovery"]["what"])
        json.dumps(result)


if __name__ == "__main__":
    unittest.main()
