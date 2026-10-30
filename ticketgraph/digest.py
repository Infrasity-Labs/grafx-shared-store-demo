"""Content digests of a whole store: every node property and every relationship's endpoints.

Row counts alone do not show that two stores hold the same data. content_digest hashes the content
in an order that does not depend on how the rows were written, so a store, its physical restore and
its logical import can be compared. Native record ids and system-history timestamps are NOT part of
the digest: they are physical identity, not content.
"""
import hashlib
import json

from okto_grafx.domain.model.value import VectorValue


def _plain(value):
    if isinstance(value, VectorValue):
        return [round(float(x), 5) for x in value.values]
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        return round(value, 9)
    return str(value)


def _sha(lines):
    h = hashlib.sha256()
    for line in lines:
        h.update(json.dumps(line, sort_keys=True, separators=(",", ":")).encode("utf-8"))
        h.update(b"\n")
    return h.hexdigest()


def _table_defs(db, tables):
    defs = {t.name: t for t in db.catalog.catalog.tables()}
    names = sorted(defs) if tables is None else sorted(tables)
    return [defs[n] for n in names]


def node_rows(db, table):
    """Every row of a node table as a list of values, ordered by primary key."""
    columns = [c.name for c in table.columns]
    sql = "MATCH (n:%s) RETURN %s ORDER BY n.%s" % (
        table.name, ", ".join(f"n.{c}" for c in columns), table.primary_key)
    return [[_plain(v) for v in row] for row in db.execute(sql).rows]


def rel_pairs(db, table, node_defs):
    """Every relationship of a table as (from key, to key), sorted. Duplicates are kept."""
    src, dst = node_defs[table.from_table], node_defs[table.to_table]
    sql = "MATCH (a:%s)-[r:%s]->(b:%s) RETURN a.%s, b.%s" % (
        src.name, table.name, dst.name, src.primary_key, dst.primary_key)
    return sorted([_plain(v) for v in row] for row in db.execute(sql).rows)


def content_digest(db, tables=None):
    """{"overall": hex, "tables": {name: {"kind", "rows", "digest"}}} for the chosen tables (default all)."""
    defs = _table_defs(db, tables)
    node_defs = {t.name: t for t in defs if t.kind == "node"}
    if any(t.kind == "rel" and (t.from_table not in node_defs or t.to_table not in node_defs) for t in defs):
        node_defs = {t.name: t for t in _table_defs(db, None) if t.kind == "node"}
    out = {}
    for table in defs:
        rows = node_rows(db, table) if table.kind == "node" else rel_pairs(db, table, node_defs)
        out[table.name] = {"kind": table.kind, "rows": len(rows), "digest": _sha(rows)}
    overall = _sha([[name, out[name]["rows"], out[name]["digest"]] for name in sorted(out)])
    return {"overall": overall, "tables": out}


def differing_tables(a, b):
    """Names of tables whose digest differs between two content_digest results (or exist in only one)."""
    names = set(a["tables"]) | set(b["tables"])
    return sorted(n for n in names if a["tables"].get(n, {}).get("digest") != b["tables"].get(n, {}).get("digest"))
