"""The application layer that sits on top of the demo schema: incidents, triage decisions, checkpoints.

The ten demo steps do not use it. The retrieval evaluation, the resumable import and the support
workflow do. It is added with DDL on an existing store, so it works on a fresh store and on the
store the ten steps leave behind.
"""
import json

from .common import FIXTURES
from .retry import write_with_conflict_retry

# (table, DDL). Order matters: relationship tables come after the nodes they join.
APP_DDL = [
    ("Incident", "CREATE NODE TABLE Incident(id INT64, name STRING, root_cause STRING, PRIMARY KEY(id))"),
    # One row per unit of application work (an import batch, a workflow stage). It is written in the
    # SAME transaction as the work it describes, so the row exists exactly when that work is committed.
    ("Checkpoint", "CREATE NODE TABLE Checkpoint(key STRING, job STRING, unit STRING, rows INT64, "
                   "digest STRING, PRIMARY KEY(key))"),
    ("Triage", "CREATE NODE TABLE Triage(id INT64, ticket_id INT64, decision STRING, incident_id INT64, "
               "products STRING, rationale STRING, PRIMARY KEY(id))"),
    ("InIncident", "CREATE REL TABLE InIncident(FROM Ticket TO Incident)"),
    ("SameIncident", "CREATE REL TABLE SameIncident(FROM Ticket TO Ticket)"),
    ("TriageOf", "CREATE REL TABLE TriageOf(FROM Triage TO Ticket)"),
    ("Suggests", "CREATE REL TABLE Suggests(FROM Triage TO Article)"),
    ("JoinsIncident", "CREATE REL TABLE JoinsIncident(FROM Triage TO Incident)"),
]
APP_TABLES = tuple(name for name, _ in APP_DDL)


def table_names(db):
    return {t.name for t in db.catalog.catalog.tables()}


def ensure_app_schema(db):
    """Create the application tables that are missing. Returns the names it created."""
    have = table_names(db)
    missing = [(name, ddl) for name, ddl in APP_DDL if name not in have]
    if missing:
        def operation(txn):
            for _name, ddl in missing:
                txn.execute(ddl)
        report, _ = write_with_conflict_retry(db, operation)
        assert report.durable
    return [name for name, _ in missing]


def ensure_ticket_text_index(db):
    """Create the ticket_text index unless it exists. Returns True if it was created."""
    if "ticket_text" in db.attached_indexes:
        return False
    from .searcher import create_ticket_text_index
    create_ticket_text_index(db)
    return True


# ------------------------------------------------------------------ checkpoints
CHECKPOINT_SQL = ("CREATE (:Checkpoint {key: $key, job: $job, unit: $unit, rows: $rows, digest: $digest})")


def checkpoint_params(key, job, unit, rows, digest=""):
    return {"key": key, "job": job, "unit": unit, "rows": rows, "digest": digest}


def write_checkpoint(txn, key, job, unit, rows, digest=""):
    """Record a checkpoint inside the caller's transaction."""
    txn.execute(CHECKPOINT_SQL, checkpoint_params(key, job, unit, rows, digest))


def checkpoint_exists(db, key):
    return bool(db.execute("MATCH (c:Checkpoint {key: $key}) RETURN c.key", {"key": key}).rows)


def committed_units(db, job):
    """unit name -> (rows, digest) for every committed checkpoint of a job."""
    rows = db.execute("MATCH (c:Checkpoint {job: $job}) RETURN c.unit, c.rows, c.digest ORDER BY c.unit",
                      {"job": job}).rows
    return {r[0]: (r[1], r[2]) for r in rows}


# ------------------------------------------------------------------ incident graph
def incident_graph_document():
    return json.loads((FIXTURES / "incident_graph.json").read_text(encoding="utf-8"))


def load_incident_graph(db):
    """Incidents, the tickets triaged into them and the recorded ticket-to-ticket links.

    One transaction writes all of it together with a Checkpoint row named incident-graph:done, so a
    crash leaves either nothing or everything. If the checkpoint exists nothing is loaded again. The
    core tickets must already be in the store.
    """
    doc = incident_graph_document()
    summary = {"incidents": len(doc["incidents"]), "members": len(doc["members"]), "links": len(doc["links"])}
    if checkpoint_exists(db, "incident-graph:done"):
        return dict(summary, loaded=False)

    def operation(txn):
        txn.executemany("CREATE (:Incident {id: $id, name: $name, root_cause: $root_cause})", doc["incidents"])
        txn.executemany("MATCH (t:Ticket {id: $ticket}), (i:Incident {id: $incident}) CREATE (t)-[:InIncident]->(i)",
                        doc["members"])
        txn.executemany("MATCH (x:Ticket {id: $a}), (y:Ticket {id: $b}) CREATE (x)-[:SameIncident]->(y)",
                        doc["links"])
        write_checkpoint(txn, "incident-graph:done", "incident-graph", "done", len(doc["links"]))

    report, _ = write_with_conflict_retry(db, operation)
    assert report.durable
    return dict(summary, loaded=True)
