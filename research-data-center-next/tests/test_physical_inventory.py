"""Private manifests yield public aggregates without duplicate-path inflation."""
import gzip
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


PROJECT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("physical_inventory", PROJECT / "tools" / "build_physical_inventory.py")
inventory = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(inventory)
OBSERVED = "2026-10-27T03:04:05+08:00"


def row(path, kind, inode, size=0, blocks=0, target=None, root="/data/datasets", mtime=1_700_000_000_000_000_000):
    result = dict(root=root, relative_path=path, kind=kind, dev=1, ino=inode,
                  mode=0, uid=1000, gid=1000, size=size, blocks=blocks,
                  nlink=2, mtime_ns=mtime, ctime_ns=mtime)
    if target is not None:
        result["target"] = target
    return result


def baseline(paths):
    return {"assets": [{"id": f"asset-{index}", "kind": "dataset", "path": path}
                       for index, path in enumerate(paths)]}


class PhysicalInventoryTests(unittest.TestCase):
    def build(self, rows, paths):
        with tempfile.TemporaryDirectory() as scratch:
            manifest = Path(scratch) / "private.jsonl.gz"
            with gzip.open(manifest, "wt", encoding="utf-8") as stream:
                for entry in rows:
                    stream.write(json.dumps(entry) + "\n")
            return inventory.build_inventory(manifest, baseline(paths), OBSERVED, scratch)

    def test_nested_entries_hardlinks_and_global_roots_are_independently_aggregated(self):
        records = [row("a", "directory", 100), row("a/direct.wav", "file", 200, 10, 1),
                   row("a/sub", "directory", 101), row("a/sub/shared.wav", "file", 200, 10, 1),
                   row("a/sub/other.json", "file", 201, 4, 1),
                   row("a/link", "symlink", 300, target="/private/patient-records"),
                   row("a/sub/internal", "symlink", 301, target="/data/models/m"),
                   row("m", "directory", 400, root="/data/models"),
                   row("m/model.bin", "file", 201, 4, 1, root="/data/models")]
        result = self.build(records, ["/data/datasets/a", "/data/datasets/a/sub", "/data/models/m"])
        parent = result["paths"]["/data/datasets/a"]
        child = result["paths"]["/data/datasets/a/sub"]
        self.assertEqual((parent["file_count"], parent["directory_count"], parent["symlink_count"]), (3, 1, 2))
        self.assertEqual((child["file_count"], child["directory_count"]), (2, 0))
        self.assertEqual(parent["apparent_file_bytes"], 24)
        self.assertEqual(parent["unique_file_bytes"], 14)
        self.assertEqual(parent["allocated_file_bytes"], 1024)
        self.assertEqual((parent["unique_inodes"], parent["unique_file_inodes"]), (5, 2))
        self.assertEqual(result["roots"]["/data/datasets"]["directory_count"], 2)
        self.assertEqual(result["totals"]["file_count"], 4)
        self.assertEqual(result["totals"]["unique_file_bytes"], 14)  # cross-root hardlink once
        self.assertEqual(result["totals"]["unique_inodes"], 7)
        self.assertEqual(parent["extension_counts"], {".wav": 2, ".json": 1})

    def test_eight_ids_at_one_path_share_one_aggregate(self):
        result = self.build([row("shared", "directory", 1), row("shared/x.npy", "file", 2, 7, 1)],
                            ["/data/datasets/shared"] * 8)
        self.assertEqual(len(result["paths"]), 1)
        self.assertEqual(result["paths"]["/data/datasets/shared"]["catalog_record_count"], 8)
        self.assertEqual(result["summary"]["catalog_records"], 8)
        self.assertEqual(result["summary"]["paths_with_multiple_records"], 1)
        self.assertEqual(result["totals"]["file_count"], 1)

    def test_links_are_not_followed_and_private_names_or_targets_are_not_published(self):
        records = [row("a", "directory", 1),
                   row("a/confidential-link-name", "symlink", 2, target="/private/secret-absolute"),
                   row("a/relative-secret", "symlink", 3, target="../../../private/secret-relative"),
                   row("a/internal-link", "symlink", 4, target="/data/models/known"),
                   row("a/confidential-file-name.wav", "file", 5, 10, 1)]
        result = self.build(records, ["/data/datasets/a"])
        stats = result["paths"]["/data/datasets/a"]
        self.assertEqual(stats["file_count"], 1)
        self.assertEqual(stats["symlink_count"], 3)
        self.assertEqual(stats["external_absolute_symlink_count"], 1)
        serialized = json.dumps(result)
        for private_text in ("confidential", "secret-absolute", "secret-relative", "internal-link"):
            self.assertNotIn(private_text, serialized)

    def test_missing_is_unknown_empty_is_zero_and_directory_itself_is_excluded(self):
        result = self.build([row("empty", "directory", 1, mtime=1_900_000_000_000_000_000)],
                            ["/data/datasets/empty", "/data/datasets/missing"])
        empty = result["paths"]["/data/datasets/empty"]
        missing = result["paths"]["/data/datasets/missing"]
        self.assertTrue(empty["entry_observed"])
        self.assertEqual(empty["unique_inodes"], 0)
        self.assertIsNone(empty["newest_mtime"])
        self.assertFalse(missing["entry_observed"])
        self.assertIsNone(missing["file_count"])
        self.assertIsNone(missing["unique_file_bytes"])
        self.assertEqual(result["observed_at"], "2026-10-26T19:04:05Z")
        self.assertEqual(result["roots"]["/data/datasets"]["newest_mtime"], "2030-03-17T17:46:40.000000000Z")

    def test_root_row_is_excluded_and_bad_scope_or_duplicates_fail(self):
        result = self.build([row(".", "directory", 1), row("a", "directory", 2)], ["/data/datasets"])
        self.assertEqual(result["totals"]["directory_count"], 1)
        self.assertEqual(result["paths"]["/data/datasets"]["directory_count"], 1)
        for records in ([row("../outside", "file", 1)], [row("x", "special", 1)],
                        [row("x", "file", 1), row("x", "file", 1)]):
            with self.assertRaises(inventory.InventoryError):
                self.build(records, ["/data/datasets/a"])

    def test_conflicting_inode_observations_are_explicit_and_first_size_is_retained(self):
        result = self.build([row("a", "directory", 1), row("a/first.bin", "file", 2, 10, 1),
                             row("a/second.bin", "file", 2, 20, 2)], ["/data/datasets/a"])
        stats = result["paths"]["/data/datasets/a"]
        self.assertEqual(stats["unique_file_bytes"], 10)
        self.assertEqual(stats["inode_observation_conflicts"], 1)


if __name__ == "__main__":
    unittest.main()
