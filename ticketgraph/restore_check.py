"""What survives a backup and restore, and what survives a logical export and import.

Used by step 9. content_digest (digest.py) answers "is the content identical". The history helpers here
answer "does the system history come along". Physical restore gives back the same files, so the same
database identity and the same history. A logical import writes the rows into a NEW database: new
identity, and with history="current-only" no history.
"""
import hashlib

from okto_grafx.errors import GrafxError

from . import auditor


def commit_entries(db):
    entries, after = [], None
    while True:
        page = db.commit_history(after=after, limit=100)
        entries.extend(page.entries)
        if not page.has_more or not page.entries:
            return entries
        after = page.entries[-1].identity


def _error(error):
    return {"error_type": type(error).__name__, "message": str(error).split(" [code=")[0],
            "code": getattr(error, "code", None)}


def history_fingerprint(db, article_id=25):
    """Commit sequence numbers and the versions of one article, read from the store's own history.

    A store that has no commit history or no system history (a logical import with history
    "current-only") answers with the Grafx error instead of raising: that answer is the finding.
    """
    out = {"article_id": article_id, "commit_csns": None, "article_versions": None}
    try:
        entries = commit_entries(db)
        out["commit_csns"] = [e.identity.sequence for e in entries]
    except GrafxError as error:
        out["commit_history_error"] = _error(error)
        return out
    try:
        newest = entries[-1].identity
        row = auditor.article_row(db.system_as_of(newest, tables=("Article",)), article_id)
        versions = db.system_versions("Article", row.record_id).versions
        out["article_versions"] = [{
            "revision": v.values[3],
            "body_sha256": hashlib.sha256(v.values[2].encode("utf-8")).hexdigest(),
            "system_from_csn": v.system_from.sequence,
            "system_to_csn": v.system_to.sequence if v.system_to is not None else None,
        } for v in versions]
    except GrafxError as error:
        out["system_history_error"] = _error(error)
    return out


def summarise(fingerprint):
    csns = fingerprint["commit_csns"]
    out = {"article_id": fingerprint["article_id"], "article_versions": fingerprint["article_versions"],
           "commit_entries": len(csns) if csns is not None else None}
    if csns:
        out.update({"first_commit_csn": csns[0], "last_commit_csn": csns[-1],
                    "commit_csns_sha256": hashlib.sha256(",".join(map(str, csns)).encode()).hexdigest()})
    for key in ("commit_history_error", "system_history_error"):
        if key in fingerprint:
            out[key] = fingerprint[key]
    return out


def history_preserved(original, other):
    """True if every commit of the original is still in the other store, in order, and the article's
    versions (revisions, body hashes and the commits that made them) are identical."""
    a, b = original["commit_csns"], other["commit_csns"]
    if a is None or b is None or original["article_versions"] is None or other["article_versions"] is None:
        return False
    return b[:len(a)] == a and original["article_versions"] == other["article_versions"]
