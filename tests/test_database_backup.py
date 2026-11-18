"""Run daily backups against temporary SQLite databases and stubbed system commands."""
from __future__ import annotations

import hashlib
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


@unittest.skipIf(os.name == "nt" or not shutil.which("bash"), "requires POSIX backup shell")
class DatabaseBackupSafetyTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="album-daily-backup-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "live.db"
        with sqlite3.connect(self.source) as conn:
            conn.execute("CREATE TABLE photos(id INTEGER PRIMARY KEY, title TEXT)")
            conn.execute("INSERT INTO photos VALUES(1, 'new business record')")
        self.backups = self.root / "backups"
        self.backups.mkdir()
        self.history = self.backups / "server-20000101T000000Z.db"
        self.history.write_bytes(b"irreplaceable historical backup")
        old = time.time() - 60 * 86400
        os.utime(self.history, (old, old))
        self.mock_bin = self.root / "commands"
        self.mock_bin.mkdir()
        self.command("id", "print('0')")
        self.command("date", "print('20261118T030000Z')")
        self.command("df", "import os; print('Filesystem 1024-blocks Used Available Capacity Mounted on'); print('/test 999999999 1 '+os.environ.get('TEST_AVAILABLE_KB','999999998')+' 1% /')")
        self.command("install", "import pathlib,sys; p=pathlib.Path(sys.argv[-1]); p.mkdir(parents=True,exist_ok=True); p.chmod(0o700)")
        self.command("sqlite3", """import os, pathlib, shlex, sqlite3, sys
from urllib.parse import quote
path, command = sys.argv[1:3]
if command.startswith('.backup '):
    target = shlex.split(command)[1]
    with sqlite3.connect('file:'+quote(path,safe='/')+'?mode=ro',uri=True) as source, sqlite3.connect(target) as destination:
        source.backup(destination)
elif command == 'PRAGMA quick_check;' and os.environ.get('TEST_CORRUPT_BACKUP'):
    print('injected integrity failure')
else:
    with sqlite3.connect('file:'+quote(path,safe='/')+'?mode=ro',uri=True) as conn:
        for row in conn.execute(command): print(row[0])
""")
        source = (ROOT / "server/deploy/backup.sh").read_text(encoding="utf-8")
        source = source.replace("BACKUP_DIR=/opt/album-auth/backups/database", f'BACKUP_DIR="{self.backups}"')
        self.script = self.root / "backup.sh"
        self.script.write_text(source, encoding="utf-8")
        self.before = self.fingerprint(self.source)

    def command(self, name, body):
        path = self.mock_bin / name
        path.write_text(f"#!{sys.executable}\n{body}\n", encoding="utf-8")
        path.chmod(0o700)

    @staticmethod
    def fingerprint(path):
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def run_backup(self, **extra):
        env = {**os.environ, "PATH": str(self.mock_bin) + os.pathsep + os.environ["PATH"], "ALBUM_BACKUP_DB": str(self.source), **extra}
        return subprocess.run(["bash", str(self.script)], env=env, capture_output=True, text=True, timeout=20)

    def assert_preserved(self):
        self.assertEqual(self.history.read_bytes(), b"irreplaceable historical backup")
        self.assertEqual(self.fingerprint(self.source), self.before)

    def test_success_preserves_expired_history_and_same_second_backups(self):
        for _ in range(2):
            result = self.run_backup(ALBUM_BACKUP_RETENTION_DAYS="7")
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        created = list(self.backups.glob("server-*/server.db"))
        self.assertEqual(len(created), 2, "same-second retries must create separate backups")
        for path in created:
            with sqlite3.connect(path) as conn:
                self.assertEqual(conn.execute("SELECT * FROM photos").fetchall(), [(1, "new business record")])
                self.assertEqual(conn.execute("PRAGMA quick_check").fetchone()[0], "ok")
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assert_preserved()

    def test_capacity_failure_cannot_remove_history_or_create_partial_backup(self):
        for value in ("0", "unknown"):
            with self.subTest(available=value):
                result = self.run_backup(TEST_AVAILABLE_KB=value)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(list(self.backups.iterdir()), [self.history])
                self.assert_preserved()

    def test_integrity_failure_keeps_history_and_cleans_only_its_temporary_output(self):
        result = self.run_backup(TEST_CORRUPT_BACKUP="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(list(self.backups.iterdir()), [self.history])
        self.assert_preserved()


if __name__ == "__main__":
    unittest.main()
