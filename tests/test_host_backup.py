import contextlib
import io
import json
import os
import sqlite3
import stat
import tempfile
import unittest
from pathlib import Path

from host.backup import (BackupError, BackupScheduler, create_backup, list_backups,
                         load_backup_policy, prune_backups, restore_backup, verify_backup)
from host.server import main


def make_database(path: Path, value: str) -> None:
    connection = sqlite3.connect(path)
    try:
        connection.execute("CREATE TABLE marker (value TEXT NOT NULL)")
        connection.execute("INSERT INTO marker (value) VALUES (?)", (value,))
        connection.commit()
    finally:
        connection.close()


def read_database(path: Path) -> str:
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        return connection.execute("SELECT value FROM marker").fetchone()[0]
    finally:
        connection.close()


class CoreBackupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.data = self.root / "data"
        self.data.mkdir(mode=0o700)

    def test_backup_records_only_known_databases_and_secret(self):
        make_database(self.data / "accounts.sqlite3", "accounts")
        make_database(self.data / "events.sqlite3", "events")
        make_database(self.data / "wishbox.sqlite3", "wishbox")
        make_database(self.data / "music.sqlite3", "music")
        (self.data / "oauth-token.key").write_text("key-material\n", encoding="utf-8")
        os.chmod(self.data / "oauth-token.key", 0o600)
        legacy = self.data / "db"
        legacy.mkdir()
        make_database(legacy / "legacy.sqlite3", "legacy")
        result = create_backup(self.data)
        backup_dir = Path(result["path"])
        self.assertTrue(result["ok"])
        self.assertEqual(verify_backup(backup_dir)["name"], backup_dir.name)
        names = {item["path"] for item in result["manifest"]["files"] if item["present"]}
        self.assertEqual(names, {
            "databases/accounts.sqlite3",
            "databases/events.sqlite3",
            "databases/wishbox.sqlite3",
            "databases/music.sqlite3",
            "secrets/oauth-token.key",
        })
        self.assertEqual(list_backups(self.data / "backups")[0]["ok"], True)
        self.assertEqual(read_database(backup_dir / "databases/events.sqlite3"), "events")

    def test_empty_data_directory_backs_up_cleanly(self):
        result = create_backup(self.data)
        backup_dir = Path(result["path"])
        report = verify_backup(backup_dir)
        self.assertEqual(report["files"], [{"path": item["path"], "present": False}
                                           for item in result["manifest"]["files"]])
        music = next(item for item in report["files"] if item["path"] == "databases/music.sqlite3")
        self.assertFalse(music["present"])

    def test_tampered_database_is_rejected(self):
        make_database(self.data / "accounts.sqlite3", "accounts")
        backup_dir = Path(create_backup(self.data)["path"])
        database = backup_dir / "databases/accounts.sqlite3"
        database.write_bytes(database.read_bytes() + b"tamper")
        with self.assertRaises(BackupError):
            verify_backup(backup_dir)

    def test_tampered_music_database_is_rejected(self):
        make_database(self.data / "music.sqlite3", "music")
        backup_dir = Path(create_backup(self.data)["path"])
        database = backup_dir / "databases/music.sqlite3"
        database.write_bytes(database.read_bytes() + b"tamper")
        with self.assertRaises(BackupError):
            verify_backup(backup_dir)

    def test_manifest_may_not_omit_required_paths(self):
        backup_dir = Path(create_backup(self.data)["path"])
        manifest_path = backup_dir / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["files"] = manifest["files"][:-1]
        manifest_path.write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")
        with self.assertRaises(BackupError):
            verify_backup(backup_dir)

    def test_absent_music_database_is_reported_and_not_restored(self):
        make_database(self.data / "accounts.sqlite3", "accounts")
        backup_dir = Path(create_backup(self.data)["path"])
        report = verify_backup(backup_dir)
        music = next(item for item in report["files"] if item["path"] == "databases/music.sqlite3")
        self.assertFalse(music["present"])
        target = self.root / "restored-missing-music"
        restore = restore_backup(backup_dir, target)
        self.assertNotIn("music.sqlite3", restore["restored_files"])
        self.assertFalse((target / "music.sqlite3").exists())

    def test_restore_round_trips_into_empty_directory(self):
        make_database(self.data / "accounts.sqlite3", "original")
        make_database(self.data / "music.sqlite3", "music-original")
        (self.data / "oauth-token.key").write_text("secret\n", encoding="utf-8")
        os.chmod(self.data / "oauth-token.key", 0o600)
        backup_dir = Path(create_backup(self.data)["path"])
        target = self.root / "restored"
        report = restore_backup(backup_dir, target)
        self.assertEqual(report["restored_files"], ["accounts.sqlite3", "music.sqlite3", "oauth-token.key"])
        self.assertEqual(read_database(target / "accounts.sqlite3"), "original")
        self.assertEqual(read_database(target / "music.sqlite3"), "music-original")
        key = target / "oauth-token.key"
        self.assertEqual(key.read_text(encoding="utf-8"), "secret\n")
        self.assertEqual(stat.S_IMODE(key.stat().st_mode), 0o600)

    def test_restore_requires_force_and_removes_stale_sidecars(self):
        make_database(self.data / "accounts.sqlite3", "backup-value")
        backup_dir = Path(create_backup(self.data)["path"])
        target = self.root / "restored"
        target.mkdir(mode=0o700)
        make_database(target / "accounts.sqlite3", "existing-value")
        (target / "accounts.sqlite3-wal").write_bytes(b"stale")
        with self.assertRaises(BackupError):
            restore_backup(backup_dir, target)
        restore_backup(backup_dir, target, force=True)
        self.assertEqual(read_database(target / "accounts.sqlite3"), "backup-value")
        self.assertFalse((target / "accounts.sqlite3-wal").exists())

    def test_prune_keeps_newest_valid_backups_and_preserves_invalid_entries(self):
        for _ in range(4):
            create_backup(self.data)
        backups = self.data / "backups"
        invalid = backups / "streamiov-host-invalid"
        invalid.mkdir(mode=0o700)
        expected = sorted((entry for entry in list_backups(backups) if entry["ok"]),
                          key=lambda entry: (entry["created_at"], entry["name"]), reverse=True)
        report = prune_backups(backups, 2)
        self.assertEqual(set(report["kept"]), {entry["name"] for entry in expected[:2]})
        self.assertEqual(set(report["deleted"]), {entry["name"] for entry in expected[2:]})
        self.assertEqual(report["invalid"], [invalid.name])
        self.assertTrue(invalid.is_dir())
        for name in report["deleted"]:
            self.assertFalse((backups / name).exists())
        for name in report["kept"]:
            self.assertTrue(verify_backup(backups / name)["ok"])

    def test_prune_rejects_unsafe_retention(self):
        with self.assertRaises(BackupError):
            prune_backups(self.data / "backups", 0)

    def test_host_cli_exposes_create_list_verify_and_restore(self):
        make_database(self.data / "accounts.sqlite3", "cli-value")
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(main(["--data-dir", str(self.data), "--backup-create"]), 0)
        created = json.loads(output.getvalue())
        self.assertTrue(created["ok"])
        backup_dir = Path(created["path"])
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(main(["--data-dir", str(self.data), "--backup-list"]), 0)
        listed = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual(listed[0]["name"], created["name"])
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(main(["--data-dir", str(self.data), "--backup-verify", str(backup_dir)]), 0)
        self.assertTrue(json.loads(output.getvalue())["ok"])
        target = self.root / "cli-restored"
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(main(["--data-dir", str(target), "--backup-restore", str(backup_dir)]), 0)
        self.assertEqual(json.loads(output.getvalue())["restored_files"], ["accounts.sqlite3"])
        self.assertEqual(read_database(target / "accounts.sqlite3"), "cli-value")

    def test_host_cli_prunes_backups(self):
        make_database(self.data / "accounts.sqlite3", "cli-prune-value")
        for _ in range(3):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(main(["--data-dir", str(self.data), "--backup-create"]), 0)
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(main(["--data-dir", str(self.data), "--backup-prune", "--backup-keep", "1"]), 0)
        report = json.loads(output.getvalue())
        self.assertEqual(report["keep"], 1)
        self.assertEqual(len(report["kept"]), 1)
        self.assertEqual(len(report["deleted"]), 2)
        self.assertEqual(len(list_backups(self.data / "backups")), 1)

    def test_schedule_policy_is_bounded_and_rejects_unsafe_roots(self):
        policy = load_backup_policy()
        self.assertTrue(policy["enabled"])
        self.assertEqual(policy["keep"], 3)
        self.assertIsNone(policy["error"])
        unsafe = self.root / "unsafe-policy.json"
        unsafe.write_text(json.dumps({
            "schedule": {"enabled": True, "interval_minutes": 60, "keep": 3, "backup_root": "../outside"}
        }), encoding="utf-8")
        self.assertIsNotNone(load_backup_policy(unsafe)["error"])

    def test_scheduler_verifies_prunes_and_keeps_bounded_state(self):
        make_database(self.data / "accounts.sqlite3", "scheduled")
        policy = {
            "enabled": True, "interval_seconds": 60, "keep": 2,
            "backup_root": "scheduled-backups", "error": None,
        }
        scheduler = BackupScheduler(self.data, policy=policy)
        for moment in (1000, 1100, 1200, 1300):
            report = scheduler.run_once(force=True, at=moment)
            self.assertTrue(report["ok"])
            self.assertTrue(report["verified"])
        status = scheduler.status()
        self.assertTrue(status["ok"])
        self.assertEqual(status["state"]["run_count"], 4)
        self.assertEqual(status["state"]["failure_count"], 0)
        self.assertEqual(len(list_backups(self.data / "scheduled-backups")), 2)
        state_file = self.data / "scheduled-backups" / "backup-schedule.json"
        self.assertEqual(stat.S_IMODE(state_file.stat().st_mode), 0o600)
        not_due = scheduler.run_once(at=1301)
        self.assertFalse(not_due["ran"])
        self.assertEqual(not_due["reason"], "not_due")

    def test_host_cli_reports_and_runs_the_local_backup_schedule(self):
        make_database(self.data / "accounts.sqlite3", "schedule-cli")
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(main(["--data-dir", str(self.data), "--backup-schedule-status"]), 0)
        status = json.loads(output.getvalue())
        self.assertTrue(status["ok"])
        self.assertTrue(status["policy"]["enabled"])
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(main(["--data-dir", str(self.data), "--backup-schedule-run"]), 0)
        report = json.loads(output.getvalue())
        self.assertTrue(report["ok"])
        self.assertTrue(report["ran"])
        self.assertTrue(verify_backup(self.data / "backups" / report["backup"])["ok"])


if __name__ == "__main__":
    unittest.main()
