"""Auditor: verify, history and backup. Uses its own handle."""
import difflib
import re

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


def sentences(text):
    return [s for s in re.split(r"(?<=[.!?])\s+", text.strip()) if s]


def article_audit(db, article_id):
    """What changed in an article's last version, read only from system history.

    Needs nothing from whoever made the change: it looks up the article's versions, takes the last two,
    and compares them with system_as_of and system_diff.
    """
    newest = latest_commit(db)
    current = article_row(db.system_as_of(newest, tables=("Article",)), article_id)
    versions = db.system_versions("Article", current.record_id).versions
    if len(versions) < 2:
        return {"article_id": article_id, "versions": len(versions), "changed": False}
    previous, last = versions[-2], versions[-1]
    before = article_row(db.system_as_of(previous.system_from, tables=("Article",)), article_id)
    after = article_row(db.system_as_of(last.system_from, tables=("Article",)), article_id)
    diff = db.system_diff(previous.system_from, last.system_from, tables=("Article",))
    old_s, new_s = sentences(before.values[2]), sentences(after.values[2])
    return {
        "article_id": article_id,
        "versions": len(versions),
        "changed": True,
        "previous_version_csn": previous.system_from.sequence,
        "current_version_csn": last.system_from.sequence,
        "revision_before": before.values[3],
        "revision_after": after.values[3],
        "sentences_added": [s for s in new_s if s not in old_s],
        "sentences_removed": [s for s in old_s if s not in new_s],
        "diff_operations": [r.operation for r in diff.rows],
        "diff_properties_changed": sorted({p.name for r in diff.rows for p in r.properties}),
    }
