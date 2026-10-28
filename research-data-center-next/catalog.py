"""Transactional, metadata-only catalog storage using the Python standard library."""
from __future__ import annotations

import argparse
import csv
import io
import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "1.0"
KINDS = ("dataset", "model", "feature", "annotation", "collection", "artifact")
STATUSES = ("documented", "verified", "partial", "missing", "restricted")
TEXT_FIELDS = (
    "name", "server", "category", "description", "path", "owner", "access",
    "source_url", "source_ref", "verified_at", "notes",
)
COUNT_FIELDS = ("size_bytes", "file_count", "record_count")
CSV_FIELDS = (
    "id", "name", "kind", "server", "category", "description", "path", "owner",
    "formats", "tags", "size_bytes", "file_count", "record_count", "status",
    "access", "source_url", "source_ref", "verified_at", "notes", "metadata", "storage", "physical_inventory",
)


class CatalogError(ValueError):
    """Invalid catalog content or query."""


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


def validate_document(document: Any) -> dict[str, Any]:
    """Validate the whole snapshot before any database write; keep unknown fields."""
    if not isinstance(document, dict):
        raise CatalogError("Catalog must be a JSON object.")
    if document.get("schema_version") != SCHEMA_VERSION:
        raise CatalogError(f"schema_version must be {SCHEMA_VERSION!r}.")
    if not isinstance(document.get("assets"), list):
        raise CatalogError("assets must be a list.")
    if not isinstance(document.get("scope", {}), dict):
        raise CatalogError("scope must be an object.")
    if not isinstance(document.get("sources", []), list):
        raise CatalogError("sources must be a list.")
    if not isinstance(document.get("generated_at", ""), str):
        raise CatalogError("generated_at must be a string.")
    # A JSON round trip creates an independent tree and rejects NaN/Infinity.
    try:
        result = json.loads(_json(document))
    except (ValueError, TypeError, OverflowError) as exc:
        raise CatalogError("Catalog must contain valid JSON values.") from exc
    result.setdefault("scope", {})
    result.setdefault("sources", [])
    result.setdefault("generated_at", "")
    seen: set[str] = set()
    for index, asset in enumerate(result["assets"]):
        prefix = f"assets[{index}]"
        if not isinstance(asset, dict):
            raise CatalogError(f"{prefix} must be an object.")
        asset_id = asset.get("id")
        if (not isinstance(asset_id, str) or not asset_id.strip()
                or len(asset_id) > 512 or any(ord(c) < 32 for c in asset_id)):
            raise CatalogError(f"{prefix}.id must be a non-empty string of at most 512 characters.")
        if asset_id in seen:
            raise CatalogError(f"Duplicate asset id: {asset_id}")
        seen.add(asset_id)
        if asset.get("kind") not in KINDS:
            raise CatalogError(f"{prefix}.kind must be one of {', '.join(KINDS)}.")
        asset.setdefault("status", "documented")
        if asset["status"] not in STATUSES:
            raise CatalogError(f"{prefix}.status must be one of {', '.join(STATUSES)}.")
        for field in TEXT_FIELDS:
            asset.setdefault(field, "")
            if asset[field] is None:
                asset[field] = ""
            if not isinstance(asset[field], str):
                raise CatalogError(f"{prefix}.{field} must be a string or null.")
        if not asset["name"].strip():
            raise CatalogError(f"{prefix}.name must be non-empty.")
        for field in ("formats", "tags"):
            asset.setdefault(field, [])
            if (not isinstance(asset[field], list)
                    or not all(isinstance(item, str) for item in asset[field])):
                raise CatalogError(f"{prefix}.{field} must be a list of strings.")
        for field in COUNT_FIELDS:
            asset.setdefault(field, None)
            value = asset[field]
            if value is not None and (type(value) is not int or value < 0):
                raise CatalogError(f"{prefix}.{field} must be a non-negative integer or null.")
        asset.setdefault("metadata", {})
        if not isinstance(asset["metadata"], dict):
            raise CatalogError(f"{prefix}.metadata must be an object.")
    return result


def import_catalog(document: Any, db_path: str | Path) -> dict[str, Any]:
    """Atomically replace one metadata snapshot; never touch any source path."""
    validated = validate_document(document)
    assets = validated.pop("assets")
    rows = [(
        asset["id"], ordinal, asset["name"], asset["kind"], asset["server"],
        asset["status"], asset["category"], _json(asset).casefold(), _json(asset),
    ) for ordinal, asset in enumerate(assets)]
    target = Path(db_path).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    imported_at = datetime.now(timezone.utc).isoformat()
    with closing(sqlite3.connect(str(target), timeout=15)) as connection:
        try:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("""CREATE TABLE IF NOT EXISTS catalog_meta (
                singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                document_json TEXT NOT NULL, imported_at TEXT NOT NULL
            )""")
            connection.execute("""CREATE TABLE IF NOT EXISTS assets (
                id TEXT PRIMARY KEY, ordinal INTEGER NOT NULL UNIQUE,
                name TEXT NOT NULL, kind TEXT NOT NULL, server TEXT NOT NULL,
                status TEXT NOT NULL, category TEXT NOT NULL,
                search_text TEXT NOT NULL, document_json TEXT NOT NULL
            )""")
            for field in ("kind", "server", "status", "category"):
                connection.execute(f"CREATE INDEX IF NOT EXISTS idx_assets_{field} ON assets ({field})")
            connection.execute("DELETE FROM assets")
            connection.executemany("INSERT INTO assets VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
            connection.execute("""INSERT INTO catalog_meta VALUES (1, ?, ?)
                ON CONFLICT(singleton) DO UPDATE SET
                document_json = excluded.document_json, imported_at = excluded.imported_at""",
                (_json(validated), imported_at))
            connection.commit()
        except Exception:
            connection.rollback()
            raise
    return {"total": len(assets), "db": str(target), "imported_at": imported_at}


def open_catalog(db_path: str | Path) -> sqlite3.Connection:
    """Open an existing catalog read-only, including at the SQLite layer."""
    target = Path(db_path).expanduser().resolve()
    connection = sqlite3.connect(target.as_uri() + "?mode=ro", uri=True, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only = ON")
    return connection


def read_metadata(connection: sqlite3.Connection) -> dict[str, Any]:
    row = connection.execute("SELECT document_json, imported_at FROM catalog_meta WHERE singleton = 1").fetchone()
    if row is None:
        raise CatalogError("No catalog snapshot has been imported.")
    result = json.loads(row["document_json"])
    result["imported_at"] = row["imported_at"]
    return result


def get_summary(connection: sqlite3.Connection) -> dict[str, Any]:
    metadata = read_metadata(connection)
    result: dict[str, Any] = {
        "total": connection.execute("SELECT COUNT(*) FROM assets").fetchone()[0],
        "schema_version": metadata.get("schema_version", SCHEMA_VERSION),
        "sources": metadata.get("sources", []), "scope": metadata.get("scope", {}),
        "generated_at": metadata.get("generated_at", ""), "imported_at": metadata["imported_at"],
    }
    for field in ("kind", "server", "status", "category"):
        result[f"by_{field}"] = dict(connection.execute(
            f"SELECT {field}, COUNT(*) FROM assets GROUP BY {field} ORDER BY {field}"))
    result["categories"] = list(result["by_category"])
    return result


def query_assets(connection: sqlite3.Connection, *, q: str = "", kind: str = "",
                 server: str = "", status: str = "", category: str = "",
                 page: int = 1, page_size: int = 30) -> dict[str, Any]:
    if type(page) is not int or not 1 <= page <= 1_000_000:
        raise CatalogError("page must be an integer between 1 and 1000000.")
    if type(page_size) is not int or not 1 <= page_size <= 200:
        raise CatalogError("page_size must be an integer between 1 and 200.")
    if not isinstance(q, str) or len(q) > 500:
        raise CatalogError("q must be at most 500 characters.")
    clauses, values = [], []
    for field, value in (("kind", kind), ("server", server), ("status", status), ("category", category)):
        if not isinstance(value, str) or len(value) > 512:
            raise CatalogError(f"{field} must be at most 512 characters.")
        if value:
            clauses.append(f"{field} = ?")
            values.append(value)
    # Literal substring matching: %, _, quotes and SQL syntax are all ordinary text.
    for term in q.casefold().split():
        clauses.append("instr(search_text, ?) > 0")
        values.append(term)
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    total = connection.execute("SELECT COUNT(*) FROM assets" + where, values).fetchone()[0]
    rows = connection.execute("SELECT document_json FROM assets" + where + " ORDER BY ordinal LIMIT ? OFFSET ?",
                              values + [page_size, (page - 1) * page_size])
    return {"items": [json.loads(row[0]) for row in rows], "total": total, "page": page, "page_size": page_size}


def get_asset(connection: sqlite3.Connection, asset_id: str) -> dict[str, Any] | None:
    row = connection.execute("SELECT document_json FROM assets WHERE id = ?", (asset_id,)).fetchone()
    return json.loads(row[0]) if row else None


def export_catalog(connection: sqlite3.Connection) -> dict[str, Any]:
    # Preserve the original document fields, including user-supplied extension fields.
    row = connection.execute("SELECT document_json FROM catalog_meta WHERE singleton = 1").fetchone()
    if row is None:
        raise CatalogError("No catalog snapshot has been imported.")
    document = json.loads(row[0])
    document["assets"] = [json.loads(row[0]) for row in connection.execute(
        "SELECT document_json FROM assets ORDER BY ordinal")]
    return document


def csv_safe(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, (list, dict)):
        value = _json(value)
    if isinstance(value, str) and value:
        stripped = value.lstrip()
        if value[0] in "\t\r\n" or (stripped and stripped[0] in "=+-@"):
            return "'" + value
    return value


def export_csv(connection: sqlite3.Connection) -> str:
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(CSV_FIELDS)
    for row in connection.execute("SELECT document_json FROM assets ORDER BY ordinal"):
        asset = json.loads(row[0])
        writer.writerow([csv_safe(asset.get(field)) for field in CSV_FIELDS])
    return output.getvalue()


def main() -> int:
    parser = argparse.ArgumentParser(description="Import a metadata snapshot without reading or changing source files.")
    commands = parser.add_subparsers(dest="command", required=True)
    importer = commands.add_parser("import", help="Atomically replace the catalog metadata snapshot")
    importer.add_argument("--input", required=True, type=Path)
    importer.add_argument("--db", default="var/catalog.sqlite3", type=Path)
    summary = commands.add_parser("summary", help="Inspect the imported metadata snapshot")
    summary.add_argument("--db", default="var/catalog.sqlite3", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "import":
            document = json.loads(args.input.read_text(encoding="utf-8-sig"))
            result = import_catalog(document, args.db)
        else:
            with closing(open_catalog(args.db)) as connection:
                result = get_summary(connection)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (OSError, sqlite3.Error, ValueError) as exc:
        parser.exit(1, f"Catalog error: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
