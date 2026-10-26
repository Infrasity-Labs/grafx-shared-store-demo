"""Auditor: verify, history and backup. Uses its own handle."""
from okto_grafx import CommitId, connect

from .common import to_plain
from .retry import write_with_conflict_retry


def latest_commit(db):
    return db.commit_history().entries[-1].identity


def article_row(graph, article_id):
    for row in graph.rows:
        if row.values[0] == article_id:
            return row
    return None


def correct_article(db, article_id, new_body):
    """The Maintainer's normal write. Returns the CommitId of the correction."""
    def operation(txn):
        txn.execute("MATCH (a:Article {id: $id}) SET a.body = $body, a.revision = 2",
                    {"id": article_id, "body": new_body})
    report, conflicts = write_with_conflict_retry(db, operation)
    assert report.durable
    return CommitId(db.identity.database_uuid, report.csn), conflicts


def time_travel(db, article_id, new_body):
    before_commit = latest_commit(db)
    changed, _ = correct_article(db, article_id, new_body)
    before = article_row(db.system_as_of(before_commit, tables=("Article",)), article_id)
    after = article_row(db.system_as_of(changed, tables=("Article",)), article_id)
    versions = db.system_versions("Article", before.record_id)
    diff = db.system_diff(before_commit, changed, tables=("Article",))
    return {
        "article_id": article_id,
        "before_commit_csn": before_commit.sequence,
        "correction_csn": changed.sequence,
        "as_of_before": {"body": before.values[2], "revision": before.values[3]},
        "as_of_after": {"body": after.values[2], "revision": after.values[3]},
        "versions": [{"system_from": to_plain(v.system_from), "system_to": to_plain(v.system_to),
                      "revision": v.values[3]} for v in versions.versions],
        "diff_rows": [{"operation": r.operation,
                       "properties": [{"name": p.name, "before": p.before, "after": p.after}
                                      for p in r.properties]} for r in diff.rows],
    }
