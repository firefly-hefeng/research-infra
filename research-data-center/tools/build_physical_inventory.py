#!/usr/bin/env python3
"""Aggregate a private, no-follow source manifest into a small public inventory.

No source directories or link targets are opened. Only the manifest and baseline
catalog are read. SQLite scratch tables keep inode/path deduplication off the
Python heap; neither scratch data nor individual manifest filenames are exported.
"""

import argparse
from collections import Counter
from datetime import datetime, timedelta, timezone
import gzip
import hashlib
import json
import os
from pathlib import Path
import posixpath
import re
import sqlite3
import tempfile


PUBLIC_ROOTS = ("/data/datasets", "/data/models")
KINDS = {"file", "directory", "symlink"}
COUNT_FIELDS = (
    "file_count", "directory_count", "symlink_count", "apparent_file_bytes",
    "unique_file_bytes", "allocated_file_bytes", "unique_inodes",
    "unique_file_inodes", "external_absolute_symlink_count",
)
LIMITATIONS = [
    "统计来自指定时间的源文件系统清单，不是实时状态，也不是 CPFS 迁移或完整性核验回执。",
    "每个登记目录只统计其严格后代；目录自身不计入内容。嵌套登记范围可重叠，不能把条目容量或数量相加。",
    "公共根及全库总量直接遍历清单独立汇总，不由登记条目相加；同路径多条说明复用一份物理统计。",
    "不跟随任何符号链接。域外绝对链接仅公开数量，不公开目标；相对链接也不解析、不计入所指内容。",
    "unique_inodes 按 (dev, ino) 对全部目录、普通文件和符号链接去重；unique_file_inodes 只计普通文件。",
    "apparent_file_bytes 按普通文件路径累加；unique_file_bytes 按普通文件 inode 去重。",
    "allocated_file_bytes 为唯一普通文件 inode 的源文件系统 st_blocks × 512，不含目录/链接块，不是 CPFS 占用预测。",
    "扩展名仅用于文件构成统计，不据此推断资源身份、研究样本数、内容格式有效性或使用许可。",
    "清单不是原子快照。observed_at 由采集记录提供；扫描是否完整及扫描期间变化应结合私有审计回执判断。",
    "未在清单直接观察到的登记入口统计为 null；已观察的空目录统计为 0。非目录入口不展开链接内容。",
    "同一 inode 的大小或分配块发生冲突时保留首条观察并计入 inode_observation_conflicts；存在冲突的容量不能解释为一致时点精确值。",
]


class InventoryError(ValueError):
    """An invalid input; messages deliberately omit private manifest filenames."""


def observed_time(value):
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError):
        raise InventoryError("observed_at must be an ISO 8601 timestamp") from None
    if parsed.utcoffset() is None:
        raise InventoryError("observed_at must include a timezone")
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def mtime_iso(value):
    if value is None:
        return None
    seconds, nanoseconds = divmod(value, 1_000_000_000)
    try:
        stamp = datetime(1970, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=seconds)
    except (OverflowError, ValueError):
        raise InventoryError("manifest mtime_ns is outside supported timestamp range") from None
    return stamp.strftime("%Y-%m-%dT%H:%M:%S") + f".{nanoseconds:09d}Z"


def public_root(path):
    return next((root for root in PUBLIC_ROOTS if path == root or path.startswith(root + "/")), None)


def absolute_path(value):
    if not isinstance(value, str) or not value.startswith("/") or "\0" in value:
        raise InventoryError("catalog contains an invalid absolute path")
    if any(part in (".", "..") for part in value.split("/")) or "//" in value:
        raise InventoryError("catalog paths must be normalized")
    clean = value.rstrip("/")
    if public_root(clean) is None:
        raise InventoryError("baseline catalog contains a path outside the two source public roots")
    return clean


def catalog_paths(catalog):
    assets = catalog.get("assets") if isinstance(catalog, dict) else None
    if not isinstance(assets, list):
        raise InventoryError("catalog must contain an assets array")
    counts = Counter()
    for asset in assets:
        if not isinstance(asset, dict):
            raise InventoryError("catalog asset must be an object")
        counts[absolute_path(asset.get("path"))] += 1
    return counts


def integer(row, name, line_number, minimum=None):
    value = row.get(name)
    if isinstance(value, bool) or not isinstance(value, int) or (minimum is not None and value < minimum):
        raise InventoryError(f"manifest line {line_number}: invalid {name}")
    return value


def parse_row(row, line_number):
    if not isinstance(row, dict) or row.get("root") not in PUBLIC_ROOTS:
        raise InventoryError(f"manifest line {line_number}: unexpected root")
    root = row["root"]
    relative = row.get("relative_path")
    if relative in ("", "."):
        relative = ""
    if not isinstance(relative, str) or relative.startswith("/") or "\0" in relative:
        raise InventoryError(f"manifest line {line_number}: invalid relative_path")
    if relative and any(part in ("", ".", "..") for part in relative.split("/")):
        raise InventoryError(f"manifest line {line_number}: relative_path is not normalized")
    kind = row.get("kind")
    if kind not in KINDS:
        raise InventoryError(f"manifest line {line_number}: unsupported kind")
    if not relative and kind != "directory":
        raise InventoryError(f"manifest line {line_number}: root must be a plain directory")
    target = row.get("target")
    if kind == "symlink" and not isinstance(target, str):
        raise InventoryError(f"manifest line {line_number}: symlink target is missing")
    return {
        "root": root, "relative_path": relative, "path": root + ("/" + relative if relative else ""),
        "kind": kind, "dev": integer(row, "dev", line_number, 0),
        "ino": integer(row, "ino", line_number, 0),
        "size": integer(row, "size", line_number, 0),
        "blocks": integer(row, "blocks", line_number, 0),
        "mtime_ns": integer(row, "mtime_ns", line_number), "target": target,
    }


def extension(path):
    name = posixpath.basename(path)
    if "." not in name.lstrip(".") or name.endswith("."):
        return "[no extension]"
    suffix = "." + name.rsplit(".", 1)[1].lower()
    # Never publish unusual suffix text that could contain paths/control characters.
    return suffix if re.fullmatch(r"\.[a-z0-9_-]{1,16}", suffix) else "[other extension]"


class Aggregate:
    def __init__(self):
        self.file_count = 0
        self.directory_count = 0
        self.symlink_count = 0
        self.apparent_file_bytes = 0
        self.external_absolute_symlink_count = 0
        self.newest_mtime_ns = None
        self.extensions = Counter()

    def add(self, row):
        kind = row["kind"]
        if kind == "file":
            self.file_count += 1
            self.apparent_file_bytes += row["size"]
            self.extensions[extension(row["relative_path"])] += 1
        elif kind == "directory":
            self.directory_count += 1
        else:
            self.symlink_count += 1
            target = row["target"]
            if target.startswith("/") and public_root(posixpath.normpath(target)) is None:
                self.external_absolute_symlink_count += 1
        value = row["mtime_ns"]
        if self.newest_mtime_ns is None or value > self.newest_mtime_ns:
            self.newest_mtime_ns = value

    def finish(self, inode_stats):
        unique, files, file_bytes, allocated_bytes, conflicts = inode_stats
        return {
            "file_count": self.file_count, "directory_count": self.directory_count,
            "symlink_count": self.symlink_count, "apparent_file_bytes": self.apparent_file_bytes,
            "unique_file_bytes": file_bytes, "allocated_file_bytes": allocated_bytes,
            "unique_inodes": unique, "unique_file_inodes": files,
            "extension_counts": dict(sorted(self.extensions.items(), key=lambda pair: (-pair[1], pair[0]))[:12]),
            "external_absolute_symlink_count": self.external_absolute_symlink_count,
            "newest_mtime": mtime_iso(self.newest_mtime_ns),
            "inode_observation_conflicts": conflicts,
        }


def manifest_sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def build_inventory(manifest, catalog, observed_at, temp_dir=None):
    """Return public aggregates; scratch rows are deleted even after failure."""
    timestamp = observed_time(observed_at)
    manifest = Path(manifest)
    initial_stat = manifest.stat()
    initial_signature = (initial_stat.st_dev, initial_stat.st_ino, initial_stat.st_size, initial_stat.st_mtime_ns)
    path_counts = catalog_paths(catalog)
    roots = {root: index + 1 for index, root in enumerate(PUBLIC_ROOTS)}
    buckets = dict(roots)
    for path in sorted(path_counts):
        if path not in buckets:
            buckets[path] = len(buckets) + 1
    aggregates = {bucket: Aggregate() for bucket in {0, *buckets.values()}}
    entry_kinds = {}
    root_entries = Counter()
    manifest_records = 0
    with tempfile.TemporaryDirectory(prefix="rdc-physical-", dir=temp_dir) as scratch:
        connection = sqlite3.connect(str(Path(scratch) / "dedup.sqlite"))
        try:
            connection.executescript("""
                PRAGMA journal_mode=OFF;
                PRAGMA synchronous=OFF;
                PRAGMA temp_store=FILE;
                PRAGMA cache_size=-32768;
                CREATE TABLE entries(root TEXT, relative_path TEXT, PRIMARY KEY(root, relative_path)) WITHOUT ROWID;
                CREATE TABLE inodes(bucket INTEGER, dev TEXT, ino TEXT, kind TEXT,
                    size INTEGER, allocated INTEGER, conflicts INTEGER DEFAULT 0,
                    PRIMARY KEY(bucket, dev, ino)) WITHOUT ROWID;
            """)
            insert = """INSERT INTO inodes(bucket,dev,ino,kind,size,allocated) VALUES(?,?,?,?,?,?)
                ON CONFLICT(bucket,dev,ino) DO UPDATE SET conflicts=1
                WHERE inodes.kind!=excluded.kind OR inodes.size!=excluded.size OR inodes.allocated!=excluded.allocated"""
            pending = []
            with gzip.open(manifest, "rt", encoding="utf-8") as stream:
                for line_number, line in enumerate(stream, 1):
                    if not line.strip():
                        continue
                    try:
                        value = json.loads(line)
                    except (ValueError, UnicodeError):
                        raise InventoryError(f"manifest line {line_number}: invalid JSON") from None
                    row = parse_row(value, line_number)
                    try:
                        connection.execute("INSERT INTO entries VALUES(?,?)", (row["root"], row["relative_path"]))
                    except sqlite3.IntegrityError:
                        raise InventoryError(f"manifest line {line_number}: duplicate path record") from None
                    manifest_records += 1
                    root_entries[row["root"]] += 1
                    if row["path"] in path_counts:
                        entry_kinds[row["path"]] = row["kind"]
                    # Root metadata, if present, is not part of the root's contents.
                    if not row["relative_path"]:
                        continue
                    members = {0, roots[row["root"]]}
                    parent = posixpath.dirname(row["path"])
                    while parent == row["root"] or parent.startswith(row["root"] + "/"):
                        if parent in buckets:
                            members.add(buckets[parent])
                        if parent == row["root"]:
                            break
                        parent = posixpath.dirname(parent)
                    for bucket in members:
                        aggregates[bucket].add(row)
                        pending.append((bucket, str(row["dev"]), str(row["ino"]), row["kind"],
                                        row["size"] if row["kind"] == "file" else 0,
                                        row["blocks"] * 512 if row["kind"] == "file" else 0))
                    if len(pending) >= 10_000:
                        connection.executemany(insert, pending)
                        connection.commit()
                        pending.clear()
            if pending:
                connection.executemany(insert, pending)
            connection.commit()
            inode_stats = {row[0]: row[1:] for row in connection.execute("""
                SELECT bucket,COUNT(*),SUM(CASE WHEN kind='file' THEN 1 ELSE 0 END),
                SUM(size),SUM(allocated),SUM(conflicts) FROM inodes GROUP BY bucket
            """)}
        finally:
            connection.close()
    results = {bucket: aggregate.finish(inode_stats.get(bucket, (0, 0, 0, 0, 0)))
               for bucket, aggregate in aggregates.items()}
    paths = {}
    for path, count in sorted(path_counts.items()):
        stats = dict(results[buckets[path]])
        kind = entry_kinds.get(path)
        # A public root is implicit in this collector's manifest; never imply a
        # missing registered child is an empty directory based on the old catalog.
        found = kind is not None or path in roots and root_entries[path] > 0
        if not found:
            for field in COUNT_FIELDS:
                stats[field] = None
            stats.update(extension_counts={}, newest_mtime=None, inode_observation_conflicts=None)
        stats.update(entry_observed=found, entry_kind=kind or ("directory" if found and path in roots else None),
                     catalog_record_count=count)
        paths[path] = stats
    root_results = {root: results[bucket] for root, bucket in roots.items()}
    source_digest = manifest_sha256(manifest)
    final_stat = manifest.stat()
    if initial_signature != (final_stat.st_dev, final_stat.st_ino, final_stat.st_size, final_stat.st_mtime_ns):
        raise InventoryError("manifest changed while aggregating; retry with a completed stable manifest")
    return {
        "schema_version": "1.0", "observed_at": timestamp, "source": "source_manifest",
        "source_manifest_sha256": source_digest,
        "roots": root_results, "paths": paths, "totals": results[0],
        "summary": {
            "catalog_records": sum(path_counts.values()), "registered_paths": len(path_counts),
            "paths_with_multiple_records": sum(count > 1 for count in path_counts.values()),
            "manifest_records": manifest_records,
            "observed_registered_paths": sum(item["entry_observed"] for item in paths.values()),
            "unobserved_registered_paths": sum(not item["entry_observed"] for item in paths.values()),
            "root_manifest_records": {root: root_entries[root] for root in PUBLIC_ROOTS},
            "source_scan_complete": None,
        },
        "definitions": {
            "scope": "strict_descendants_without_following_symlinks",
            "unique_inodes": "distinct_dev_ino_all_entry_kinds",
            "unique_file_inodes": "distinct_dev_ino_regular_files_only",
            "allocated_file_bytes": "unique_regular_file_source_st_blocks_times_512_not_cpfs_prediction",
            "external_absolute_symlink_count": "absolute_target_outside_both_public_roots_lexically",
            "newest_mtime": "maximum_descendant_lstat_mtime_utc_not_scan_time",
            "extension_counts": "top_12_final_suffixes_by_regular_file_path_count",
            "inode_observation_conflicts": "same_inode_with_conflicting_kind_size_or_blocks_first_observation_retained",
        },
        "limitations": LIMITATIONS,
    }


def write_public_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".physical-", suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o644)
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return hashlib.sha256(data).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True, help="private source-files.jsonl.gz")
    parser.add_argument("--catalog", type=Path, required=True, help="baseline catalog with old source paths")
    parser.add_argument("--observed-at", required=True, help="actual source scan time, ISO 8601 with timezone")
    parser.add_argument("--output", type=Path, required=True, help="public physical-inventory.json")
    parser.add_argument("--temp-dir", type=Path, help="private scratch directory with space for SQLite deduplication")
    args = parser.parse_args()
    try:
        with args.catalog.open(encoding="utf-8") as stream:
            catalog = json.load(stream)
        result = build_inventory(args.manifest, catalog, args.observed_at, args.temp_dir)
        digest = write_public_json(args.output, result)
    except (InventoryError, OSError, sqlite3.Error, ValueError, EOFError, OverflowError) as exc:
        # Do not echo gzip/OS exception messages, which can include private paths.
        parser.exit(1, f"physical inventory failed: {str(exc) if isinstance(exc, InventoryError) else type(exc).__name__}\n")
    print(json.dumps({"output": str(args.output), "sha256": digest,
                      "registered_paths": result["summary"]["registered_paths"],
                      "manifest_records": result["summary"]["manifest_records"]}))


if __name__ == "__main__":
    main()
