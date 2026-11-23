from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tarfile
import tempfile
import time
import unittest

from host.backup import (
    BackupError,
    _check_paths,
    _directory_path,
    _safe_backup_file,
    _verify_archive,
    prune_backups,
)


class HostBackupSafetyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def _make_archive(self, archive_path: Path, *, add_unlisted: bool = False):
        databases = self.root / ("db-src-" + str(time.time_ns()))
        databases.mkdir()
        entries = []
        for name in ("accounts.sqlite3", "forum.sqlite3", "streamiov-data.sqlite3"):
            path = databases / name
            connection = sqlite3.connect(path)
            try:
                connection.execute("CREATE TABLE marker(value TEXT)")
                connection.execute("INSERT INTO marker(value) VALUES(?)", (name,))
                connection.commit()
                connection.execute("PRAGMA integrity_check")
            finally:
                connection.close()
            raw = path.read_bytes()
            entries.append({"name": name, "size": len(raw), "sha256": hashlib.sha256(raw).hexdigest()})
        manifest = {"format": "streamiov-host-backup", "version": 1, "created_at": "2026-11-23T00:00:00+00:00", "databases": entries}
        manifest_path = databases / "manifest.json"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        with tarfile.open(archive_path, "w:gz") as archive:
            archive.add(manifest_path, arcname="manifest.json")
            for entry in entries:
                archive.add(databases / entry["name"], arcname="databases/" + entry["name"])
            if add_unlisted:
                extra = databases / "extra.txt"
                extra.write_text("not in manifest", encoding="utf-8")
                archive.add(extra, arcname="../escape.txt")
        return manifest

    def test_verified_archive_checks_hashes_and_sqlite_integrity(self):
        archive_path = self.root / "snapshot.tar.gz"
        expected = self._make_archive(archive_path)
        output = self.root / "verified"
        manifest, manifest_hash = _verify_archive(archive_path, output)
        self.assertEqual(manifest["format"], "streamiov-host-backup")
        self.assertEqual(len(manifest["databases"]), 3)
        self.assertEqual(len(manifest_hash), 64)
        self.assertTrue((output / "accounts.sqlite3").is_file())

    def test_unlisted_archive_path_is_rejected_without_extraction(self):
        archive_path = self.root / "snapshot-with-extra.tar.gz"
        self._make_archive(archive_path, add_unlisted=True)
        output = self.root / "verified-extra"
        with self.assertRaises(BackupError):
            _verify_archive(archive_path, output)
        self.assertFalse((self.root / "escape.txt").exists())

    def test_backup_path_traversal_and_symlink_are_rejected(self):
        backup_dir = self.root / "backups"
        backup_dir.mkdir()
        with self.assertRaises(BackupError):
            _safe_backup_file(backup_dir, "../../etc/passwd")
        name = "streamiov-host-20261123T000000Z-deadbeef.tar.gz.age"
        target = self.root / "outside"
        target.write_text("secret", encoding="utf-8")
        (backup_dir / name).symlink_to(target)
        with self.assertRaises(BackupError):
            _safe_backup_file(backup_dir, name)

    def test_backup_directory_rejects_symlinked_parent_before_creation(self):
        target = self.root / "real-target"
        target.mkdir()
        link = self.root / "linked-parent"
        try:
            link.symlink_to(target, target_is_directory=True)
        except (NotImplementedError, OSError):
            self.skipTest("directory symlinks are unavailable on this platform")
        with self.assertRaises(BackupError):
            _directory_path(link / "backups", create=True, private=True)
        self.assertFalse((target / "backups").exists())

    @unittest.skipIf(os.name == "nt", "POSIX directory mode bits are not portable on Windows")
    def test_private_backup_directory_is_enforced_as_0700(self):
        path = _directory_path(self.root / "private-backups", create=True, private=True)
        self.assertEqual(path.stat().st_mode & 0o777, 0o700)

    def test_live_and_backup_directories_must_be_separate(self):
        data = self.root / "data"
        backups = data / "backups"
        data.mkdir()
        with self.assertRaises(BackupError):
            _check_paths(data.resolve(), backups.resolve())

    def test_retention_never_deletes_the_last_verified_backup(self):
        backup_dir = self.root / "retention"
        backup_dir.mkdir()
        name = "streamiov-host-20260101T000000Z-deadbeef.tar.gz.age"
        path = backup_dir / name
        path.write_bytes(b"encrypted-backup")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        (backup_dir / (name + ".meta.json")).write_text(json.dumps({
            "backup_file": name, "created_at": "2026-01-01T00:00:00+00:00",
            "ciphertext_sha256": digest, "status": "encrypted_pending_restore_verification"
        }), encoding="utf-8")
        (backup_dir / (name + ".verified.json")).write_text(json.dumps({
            "backup_file": name, "ciphertext_sha256": digest, "status": "verified"
        }), encoding="utf-8")
        result = prune_backups(backup_dir, keep_days=1, now=1_800_000_000)
        self.assertEqual(result["deleted"], [])
        self.assertTrue(path.exists())
        self.assertEqual(result["reason"], "last_verified_backup_protected")


if __name__ == "__main__":
    unittest.main()
