"""The CI assertions themselves: they must fail when the run is wrong, and must not read the reference."""
import contextlib
import io
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import assert_full_run as afr  # noqa: E402

LINUX = {"platform": "Linux-6.1-x86_64"}


def good_step9():
    version = {"revision": 1, "body_sha256": "x", "system_from_csn": 1, "system_to_csn": 2}
    return {
        "physical_backup": {"supported": True}, "logical_transfer": {"supported": True},
        "processes_alive_at_restore": 0, "restored_verify_findings": 0, "restored_counts_match": True,
        "restored_same_uuid": True, "logical_rows_exported": 10, "logical_rows_imported": 10,
        "fork_counts_match": True, "fork_verify_findings": 0, "fork_new_uuid": True,
        "integrity": {"restored_digest_matches": True, "restored_differing_tables": [], "tables_compared": 10,
                      "history_survives_physical_restore": True, "fork_digest_matches": True,
                      "fork_differing_tables": [], "history_survives_logical_import": False,
                      "history_original": {"article_versions": [version, version]},
                      "history_restored": {"article_versions": [version, version]}}}


class Step9Assertions(unittest.TestCase):
    def failed(self, r9, manifest=LINUX):
        c = afr.Checks()
        afr.check_step9(r9, manifest, c)
        return [name for _, name, ok, _ in c.rows if not ok]

    def test_a_good_linux_result_passes(self):
        self.assertEqual(self.failed(good_step9()), [])

    def test_a_digest_mismatch_after_restore_fails(self):
        r = good_step9()
        r["integrity"]["restored_digest_matches"] = False
        r["integrity"]["restored_differing_tables"] = ["Ticket"]
        self.assertEqual(self.failed(r), ["restore: content digest identical in all 10 tables"])

    def test_lost_history_after_restore_fails(self):
        r = good_step9()
        r["integrity"]["history_survives_physical_restore"] = False
        self.assertEqual(self.failed(r), ["restore: system history survives"])

    def test_a_refusal_on_linux_is_a_failure_but_on_macos_it_is_expected(self):
        refused = {"physical_backup": {"supported": False}, "logical_transfer": {"supported": False},
                   "integrity": {"content_digest_original": "x"}}
        self.assertTrue(self.failed(refused, LINUX))
        self.assertEqual(self.failed(refused, {"platform": "macOS-26-arm64"}), [])

    def test_a_crash_instead_of_a_recorded_refusal_fails_on_macos(self):
        broken = {"physical_backup": {"supported": True}, "logical_transfer": {"supported": True},
                  "integrity": {"content_digest_original": "x"}}
        self.assertTrue(self.failed(broken, {"platform": "macOS-26-arm64"}))


class Reference(unittest.TestCase):
    def run_main(self, path):
        with contextlib.redirect_stdout(io.StringIO()):
            return afr.main([str(path)])

    def test_refuses_the_committed_reference(self):
        self.assertEqual(self.run_main(ROOT / "demo-state"), 2)
        self.assertEqual(self.run_main(ROOT / "demo-state" / "macos-arm64"), 2)

    def test_a_folder_without_a_manifest_fails(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(self.run_main(d), 1)


if __name__ == "__main__":
    unittest.main()
