"""Manual code rollback in disposable directories; no service/network/dependency changes."""

from __future__ import annotations

from contextlib import closing
import importlib.util
import json
import os
import shutil
import sqlite3
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "server/deploy/code_rollback.py"
SPEC = importlib.util.spec_from_file_location("code_rollback_tested", HELPER)
rollback = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(rollback)


class ManualCodeRollbackTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.app = Path(self.temporary.name) / "app"
        self.backup = self.app / "backups/deploy-old"
        self.state = self.app / "backups/pre-rollback-test"
        for name in rollback.REQUIRED_FILES:
            content = b"Flask==3.0.3\n" if name.endswith("requirements.txt") else b"VERSION = 'current'\n"
            self.write(self.app / name, content)
            self.write(self.backup / name, content.replace(b"current", b"previous"))
        self.write(self.app / "municipal_rules.py", b"VERSION = 'current'\n")
        self.write(self.app / "professional_templates.py", b"VERSION = 'current'\n")
        self.write(self.backup / "runtime/professional_templates.py", b"VERSION = 'previous'\n")
        self.write(self.backup / "runtime/.snapshot-ready", b"")
        self.database = self.app / "server/data/server.db"
        self.database.parent.mkdir(parents=True)
        with closing(sqlite3.connect(self.database)) as connection, connection:
            connection.execute("CREATE TABLE records (id INTEGER PRIMARY KEY, text TEXT)")
            connection.execute("INSERT INTO records VALUES (1, 'original')")
        self.assert_connection_closed(connection)
        for name in (
            "server/data/mobile_objects/original.jpg", "server/data/previews/image.jpg",
            "server/data/mobile_chunks/upload.part", "data/mobile_objects/other-original.jpg",
            "server/operator-file", "server/deploy/local-config", "assets/operator-file",
        ):
            self.write(self.app / name, ("keep " + name).encode())
        self.write(self.backup / "server/data/server.db", b"stale database that must never be restored")
        self.write(self.backup / "server/data/mobile_objects/original.jpg", b"stale image")
        self.original_business = self.business_bytes()

    @staticmethod
    def write(path: Path, content: bytes):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)

    def assert_connection_closed(self, connection):
        with self.assertRaises(sqlite3.ProgrammingError):
            connection.execute("SELECT 1")

    def business_bytes(self):
        return {
            str(path.relative_to(self.app)): path.read_bytes()
            for prefix in ("server/data", "data", "server/operator-file", "server/deploy/local-config", "assets/operator-file")
            for path in ([self.app / prefix] if (self.app / prefix).is_file() else (self.app / prefix).rglob("*"))
            if path.is_file()
        }

    def add_business_record(self, number: int):
        with closing(sqlite3.connect(self.database)) as connection, connection:
            connection.execute("INSERT INTO records VALUES (?, ?)", (number, f"new-{number}"))
        self.assert_connection_closed(connection)
        self.write(self.app / f"server/data/mobile_objects/new-{number}.jpg", f"original-{number}".encode())

    def assert_records(self, expected):
        with closing(sqlite3.connect(self.database)) as connection, connection:
            self.assertEqual(connection.execute("SELECT id FROM records ORDER BY id").fetchall(), [(value,) for value in expected])
        self.assert_connection_closed(connection)

    def test_success_then_recovery_preserves_new_rows_originals_previews_and_chunks(self):
        rollback.prepare(self.app, self.backup, self.state)
        self.assertFalse((self.state / "current/server/data").exists())
        self.add_business_record(2)
        before = self.business_bytes()
        rollback.restore(self.app, self.state, "target")
        self.assertEqual((self.app / "server/app.py").read_bytes(), b"VERSION = 'previous'\n")
        self.assertFalse((self.app / "municipal_rules.py").exists())  # Explicit absence in complete runtime snapshot.
        self.assertEqual(self.business_bytes(), before)
        self.assert_records([1, 2])
        self.add_business_record(3)
        before_recovery = self.business_bytes()
        rollback.restore(self.app, self.state, "current")
        self.assertEqual((self.app / "server/app.py").read_bytes(), b"VERSION = 'current'\n")
        self.assertEqual((self.app / "municipal_rules.py").read_bytes(), b"VERSION = 'current'\n")
        self.assertEqual(self.business_bytes(), before_recovery)
        self.assert_records([1, 2, 3])

    def test_partial_code_switch_can_recover_without_reverting_business_writes(self):
        rollback.prepare(self.app, self.backup, self.state)
        replace = os.replace
        calls = 0

        def fail_during_switch(source, destination):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("injected code write failure")
            return replace(source, destination)

        with patch.object(rollback.os, "replace", side_effect=fail_during_switch):
            with self.assertRaises(OSError):
                rollback.restore(self.app, self.state, "target")
        self.add_business_record(2)
        before = self.business_bytes()
        rollback.restore(self.app, self.state, "current")
        self.assertEqual((self.app / "server/app.py").read_bytes(), b"VERSION = 'current'\n")
        self.assertEqual(self.business_bytes(), before)
        self.assert_records([1, 2])

    def test_corrupt_target_or_recovery_snapshot_fails_before_any_code_write(self):
        rollback.prepare(self.app, self.backup, self.state)
        for group in ("target", "current"):
            with self.subTest(group=group):
                path = self.state / group / "server/app.py"
                saved = path.read_bytes()
                path.write_bytes(b"tampered")
                before = (self.app / "server/app.py").read_bytes()
                with self.assertRaises(rollback.RollbackError):
                    rollback.restore(self.app, self.state, group)
                self.assertEqual((self.app / "server/app.py").read_bytes(), before)
                self.assertEqual(self.business_bytes(), self.original_business)
                path.write_bytes(saved)

    def test_ambiguous_legacy_backup_and_dependency_change_fail_before_capture(self):
        marker = self.backup / "runtime/.snapshot-ready"
        marker.unlink()
        with self.assertRaisesRegex(rollback.RollbackError, "snapshot-ready"):
            rollback.prepare(self.app, self.backup, self.state)
        self.assertFalse(self.state.exists())
        marker.touch()
        (self.backup / "server/requirements.txt").write_bytes(b"another-dependency==1\n")
        with self.assertRaisesRegex(rollback.RollbackError, "依赖清单"):
            rollback.prepare(self.app, self.backup, self.state)
        self.assertFalse(self.state.exists())

    def test_incomplete_application_backup_is_not_treated_as_intentional_absence(self):
        (self.backup / "server/mailer.py").unlink()
        with self.assertRaisesRegex(rollback.RollbackError, "server/mailer.py"):
            rollback.prepare(self.app, self.backup, self.state)
        self.assertFalse(self.state.exists())
        self.assertTrue((self.app / "server/mailer.py").exists())

    @unittest.skipIf(os.name == "nt", "POSIX file ownership and directory permissions")
    def test_restored_code_preserves_ownership_and_new_directories_are_traversable(self):
        target = self.backup / "runtime/assets/professional_templates.json"
        self.write(target, b"{}")
        target.chmod(0o640)
        (self.app / "assets/operator-file").unlink()
        (self.app / "assets").rmdir()
        rollback.prepare(self.app, self.backup, self.state)
        original = target.stat()
        manifest = json.loads((self.state / rollback.MANIFEST).read_bytes())
        metadata = manifest["target"]["assets/professional_templates.json"]
        self.assertEqual((metadata["uid"], metadata["gid"], metadata["mode"]), (original.st_uid, original.st_gid, 0o640))
        with patch.object(rollback.os, "chown", wraps=os.chown) as ownership:
            rollback.restore(self.app, self.state, "target")
        ownership.assert_any_call(unittest.mock.ANY, original.st_uid, original.st_gid)
        restored = (self.app / "assets/professional_templates.json").stat()
        self.assertEqual((restored.st_uid, restored.st_gid, stat.S_IMODE(restored.st_mode)), (original.st_uid, original.st_gid, 0o640))
        self.assertEqual(stat.S_IMODE((self.app / "assets").stat().st_mode), 0o755)
        self.assertEqual(stat.S_IMODE(self.state.stat().st_mode), 0o700)

    def test_backup_code_is_parsed_without_being_executed(self):
        sentinel = self.app / "must-not-exist"
        (self.backup / "server/app.py").write_text(f"from pathlib import Path\nPath({str(sentinel)!r}).write_text('executed')\n", encoding="utf-8")
        rollback.prepare(self.app, self.backup, self.state)
        self.assertFalse(sentinel.exists())
        rollback.restore(self.app, self.state, "target")
        self.assertFalse(sentinel.exists())

    def test_existing_snapshot_and_injected_manifest_path_are_rejected(self):
        rollback.prepare(self.app, self.backup, self.state)
        manifest_path = self.state / rollback.MANIFEST
        original = manifest_path.read_bytes()
        with self.assertRaises(FileExistsError):
            rollback.prepare(self.app, self.backup, self.state)
        self.assertEqual(manifest_path.read_bytes(), original)
        manifest = json.loads(original)
        manifest["target"]["server/data/server.db"] = None
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaisesRegex(rollback.RollbackError, "白名单"):
            rollback.restore(self.app, self.state, "target")
        self.assertEqual(self.business_bytes(), self.original_business)

    @unittest.skipIf(os.name == "nt", "symlink creation needs privileges on Windows")
    def test_symlinked_backup_code_and_destination_directories_fail_closed(self):
        source = self.backup / "server/app.py"
        source.unlink()
        source.symlink_to(self.app / "server/app.py")
        with self.assertRaises(rollback.RollbackError):
            rollback.prepare(self.app, self.backup, self.state)
        source.unlink()
        source.write_bytes(b"VERSION = 'previous'\n")
        rollback.prepare(self.app, self.backup, self.state)
        outside = Path(self.temporary.name) / "outside"
        outside.mkdir()
        shutil.rmtree(self.app / "server/templates")
        (self.app / "server/templates").symlink_to(outside, target_is_directory=True)
        with self.assertRaises(rollback.RollbackError):
            rollback.restore(self.app, self.state, "target")
        self.assertEqual((self.app / "server/app.py").read_bytes(), b"VERSION = 'current'\n")

    def test_hardlinked_snapshot_code_is_rejected(self):
        source = self.backup / "server/app.py"
        source.unlink()
        os.link(self.app / "server/app.py", source)
        with self.assertRaises(rollback.RollbackError):
            rollback.prepare(self.app, self.backup, self.state)

    @unittest.skipIf(os.name == "nt" or not shutil.which("bash"), "requires POSIX shell")
    def test_shell_success_and_failed_health_use_only_mock_services(self):
        for healthy in (True, False):
            with self.subTest(healthy=healthy):
                self._shell_case(healthy)

    @unittest.skipIf(os.name == "nt" or not shutil.which("bash"), "requires POSIX shell")
    def test_shell_reports_recovery_failure_and_preserves_new_business_writes(self):
        self._shell_case(False, recovery_fails=True)

    def _shell_case(self, healthy: bool, *, recovery_fails: bool = False):
        scripts = self.app / "server/deploy"
        scripts.mkdir(parents=True, exist_ok=True)
        shutil.copy2(HELPER, scripts / HELPER.name)
        self.write(scripts / "check_dependencies.py", b"# mock dependency check: no package manager or network\n")
        text = (ROOT / "server/deploy/rollback.sh").read_text(encoding="utf-8")
        text = text.replace("APP_DIR=/opt/album-auth", f"APP_DIR='{self.app}'")
        self.write(scripts / "rollback.sh", text.encode())
        python = self.app / "venv/bin/python"
        self.write(python, f"#!/bin/sh\nexec '{sys.executable}' \"$@\"\n".encode())
        python.chmod(0o700)
        commands = self.app / "fake-commands"
        commands.mkdir(exist_ok=True)
        corrupt_snapshot = (
            f"; [p.write_bytes(b'tampered') for p in Path('{self.app}/backups').glob('pre-rollback-*/current/server/app.py')]"
            if recovery_fails else ""
        )
        service_script = (
            "#!/bin/sh\n"
            "if [ \"$1\" = start ]; then\n"
            f"'{sys.executable}' -c \"import sqlite3; from pathlib import Path; p=Path('{self.database}'); c=sqlite3.connect(p); c.execute('INSERT OR IGNORE INTO records VALUES (2, \\\"during-service\\\")'); c.commit(); c.close(); (p.parent/'during-service.jpg').write_bytes(b'new original'){corrupt_snapshot}\"\n"
            "fi\nexit 0\n"
        )
        fake = {
            "id": "#!/bin/sh\necho 0\n",
            "systemctl": service_script,
            "sleep": "#!/bin/sh\nexit 0\n",
            "date": f"#!/bin/sh\necho {'success' if healthy else 'failed-health'}\n",
            "curl": ("#!/bin/sh\ncase \"$*\" in *api/me*) printf 401;; *) printf 200;; esac\n" if healthy else "#!/bin/sh\nprintf 500\n"),
        }
        for name, body in fake.items():
            self.write(commands / name, body.encode())
            (commands / name).chmod(0o700)
        environment = dict(os.environ, PATH=str(commands) + os.pathsep + os.environ["PATH"])
        result = subprocess.run(["bash", str(scripts / "rollback.sh"), str(self.backup)], env=environment, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode == 0, healthy, result.stdout + result.stderr)
        self.assertIn(b"previous" if healthy or recovery_fails else b"current", (self.app / "server/app.py").read_bytes())
        if recovery_fails:
            self.assertIn("恢复回退前代码失败", result.stderr)
            self.assertNotIn("已恢复回退前代码", result.stderr)
        self.assert_records([1, 2])
        self.assertEqual((self.database.parent / "during-service.jpg").read_bytes(), b"new original")
        for name, content in self.original_business.items():
            if name != "server/data/server.db":
                self.assertEqual((self.app / name).read_bytes(), content)
        # Reset only managed code between the two temporary shell cases.
        if healthy:
            rollback.restore(self.app, self.app / "backups/pre-rollback-success", "current")


if __name__ == "__main__":
    unittest.main()
