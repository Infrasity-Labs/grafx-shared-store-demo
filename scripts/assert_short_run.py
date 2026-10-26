"""CI check: the short real run of steps 1 to 4 left the expected outputs. Usage: assert_short_run.py STATE_DIR"""
import json
import sys
from pathlib import Path

state = Path(sys.argv[1])


def result(name):
    return json.loads((state / name).read_text())["result"]


assert result("step01_setup.json")["verify_findings"] == 0
assert result("step02_first_load.json")["tickets_loaded"] == 200
r3 = result("step03_two_writers.json")
assert r3["counts_after"]["tickets"] == r3["fixture_ticket_count"] == 500, r3
assert r3["lost_commits"] == 0 and r3["unexpected_ids"] == 0 and r3["all_durable"]
r4 = result("step04_snapshot_reads.json")
assert r4["old_snapshot_unchanged"] and r4["new_read_saw_commit"]
print("short run ok: conflicts", r3["conflicts_total"])
