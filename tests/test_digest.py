"""Content digests: order independent, sensitive to one changed property or relationship, and the
physical-copy / logical-rebuild comparison that step 9 relies on (checked here without backup, which macOS refuses)."""
import shutil
import tempfile
import unittest
from pathlib import Path

from okto_grafx import connect

from ticketgraph import digest, restore_check
from ticketgraph.schema import create_store

TICKET = ("CREATE (:Ticket {id: $id, subject: $s, body: 'b', priority: 'low', status: 'open', embedding: $e})")


def vec(x):
    return [x] + [0.0] * 383


def populate(db, order, subject_of=lambda i: f"subject {i}"):
    with db.begin("write") as txn:
        txn.execute("CREATE (:Product {id: 1, name: 'p', summary: 's'})")
        txn.execute("CREATE (:Customer {id: 1, name: 'c'})")
        txn.execute("CREATE (:Article {id: 1, title: 't', body: 'a', revision: 1})")
        for i in order:
            txn.execute(TICKET, {"id": i, "s": subject_of(i), "e": vec(i / 10)})
        for i in order:
            txn.execute("MATCH (c:Customer {id: 1}), (t:Ticket {id: $id}) CREATE (c)-[:Opened]->(t)", {"id": i})


class Digest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def store(self, name, order=(1, 2, 3), **kw):
        path = self.root / name
        create_store(path)
        with connect(path) as db:
            populate(db, order, **kw)
        return path

    def digest_of(self, path, **kw):
        with connect(path) as db:
            return digest.content_digest(db, **kw)

    def test_same_content_in_another_insertion_order_has_the_same_digest(self):
        self.assertEqual(self.digest_of(self.store("a", (1, 2, 3)))["overall"],
                         self.digest_of(self.store("b", (3, 1, 2)))["overall"])

    def test_one_changed_property_changes_only_its_table(self):
        a = self.digest_of(self.store("a"))
        b = self.digest_of(self.store("b", subject_of=lambda i: "changed" if i == 2 else f"subject {i}"))
        self.assertNotEqual(a["overall"], b["overall"])
        self.assertEqual(digest.differing_tables(a, b), ["Ticket"])

    def test_a_missing_or_extra_relationship_is_detected_even_when_counts_are_swapped(self):
        a = self.store("a")
        b = self.store("b")
        with connect(b) as db:
            with db.begin("write") as txn:
                txn.execute("MATCH ()-[r:Opened]->(t:Ticket {id: 3}) DELETE r")
                txn.execute("MATCH (c:Customer {id: 1}), (t:Ticket {id: 2}) CREATE (c)-[:Opened]->(t)")
        da, db_ = self.digest_of(a), self.digest_of(b)
        self.assertEqual(da["tables"]["Opened"]["rows"], db_["tables"]["Opened"]["rows"], "same count")
        self.assertEqual(digest.differing_tables(da, db_), ["Opened"], "different endpoints")

    def test_table_selection(self):
        d = self.digest_of(self.store("a"), tables=["Ticket", "Opened"])
        self.assertEqual(sorted(d["tables"]), ["Opened", "Ticket"])

    def test_physical_copy_keeps_identity_digest_and_history_a_logical_rebuild_does_not(self):
        original = self.store("orig")
        with connect(original) as db:
            db.checkpoint()
        copy = self.root / "copy"
        shutil.copytree(original, copy)
        with connect(original) as a, connect(copy) as b:
            self.assertEqual(a.identity.database_uuid, b.identity.database_uuid)
            self.assertEqual(digest.content_digest(a)["overall"], digest.content_digest(b)["overall"])
            fa, fb = restore_check.history_fingerprint(a, 1), restore_check.history_fingerprint(b, 1)
            self.assertTrue(restore_check.history_preserved(fa, fb))
        rebuilt = self.root / "rebuilt"
        create_store(rebuilt)
        with connect(rebuilt) as db:  # a different commit sequence: it was written by someone else
            with db.begin("write") as txn:
                txn.execute("CREATE (:Customer {id: 99, name: 'scratch'})")
            with db.begin("write") as txn:
                txn.execute("MATCH (c:Customer {id: 99}) DELETE c")
            populate(db, (1, 2, 3))
        with connect(original) as a, connect(rebuilt) as b:
            self.assertNotEqual(a.identity.database_uuid, b.identity.database_uuid)
            self.assertEqual(digest.content_digest(a)["overall"], digest.content_digest(b)["overall"],
                             "same content, written again")
            self.assertFalse(restore_check.history_preserved(restore_check.history_fingerprint(a, 1),
                                                             restore_check.history_fingerprint(b, 1)),
                             "a rebuilt store has its own history")


if __name__ == "__main__":
    unittest.main()
