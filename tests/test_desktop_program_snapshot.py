"""Real temporary-file program recovery; binaries are bytes, never executed."""
from __future__ import annotations

import contextlib
import io
import json
import os
from pathlib import Path
import shutil
import sqlite3
import stat
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import desktop_program_snapshot as snapshot


class DesktopProgramSnapshotTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        root = Path(self.temporary.name)
        self.install, self.data, self.replacement = root / "install", root / "business-data", root / "build"
        for directory in (self.install, self.data, self.replacement):
            directory.mkdir()
        self.saved = self.install / ".deployment-snapshots/test"
        self.program(self.install, b"previous")
        self.program(self.replacement, b"new release")
        self.database = self.data / "records.db"
        with sqlite3.connect(self.database) as connection:
            connection.execute("CREATE TABLE records (id INTEGER PRIMARY KEY, value TEXT)")
            connection.execute("INSERT INTO records VALUES (1, 'original')")
        for name in ("originals/photo.jpg", "previews/photo.jpg", "mobile_chunks/upload.part", "mobile_sync_state.json", "config/user.json"):
            self.write(self.data / name, b"business " + name.encode())
        for name in ("license.dat", "mobile_sync_state.json", "config/user.json", "logs/server.log", "operator-file", "data/legacy.jpg"):
            self.write(self.install / name, b"excluded " + name.encode())
        self.capacity = patch.object(snapshot.shutil, "disk_usage", return_value=SimpleNamespace(free=10 * 1024**3))
        self.capacity.start()
        self.addCleanup(self.capacity.stop)

    @staticmethod
    def write(path: Path, content: bytes):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)

    def program(self, root: Path, version: bytes):
        for name in snapshot.TARGETS[:-1]:
            self.write(root / name, version + b" " + name.encode())
        self.write(root / "_internal/runtime.dll", version + b" dll")
        self.write(root / "_internal/assets/interface.js", version + b" assets")
        (root / "_internal/empty").mkdir(parents=True, exist_ok=True)

    def create(self):
        return snapshot.create(self.install, self.data, self.saved, "A20261117-4.4", self.replacement)

    def business(self):
        return {
            (str(root), str(path.relative_to(root))): path.read_bytes()
            for root in (self.install, self.data)
            for path in root.rglob("*") if path.is_file()
            and not (root == self.install and (path.relative_to(root).parts[0] in snapshot.TARGETS or path.relative_to(root).parts[0] == ".deployment-snapshots"))
        }

    def add_data(self, number):
        with sqlite3.connect(self.database) as connection:
            connection.execute("INSERT INTO records VALUES (?, 'new')", (number,))
        self.write(self.data / f"originals/new-{number}.jpg", f"new original {number}".encode())
        self.write(self.install / "mobile_sync_state.json", f"new state {number}".encode())

    def assert_rows(self, expected):
        with sqlite3.connect(self.database) as connection:
            self.assertEqual(connection.execute("SELECT id FROM records ORDER BY id").fetchall(), [(number,) for number in expected])

    def test_complete_restore_retains_failed_program_and_all_new_business_bytes(self):
        old = snapshot._inventory(self.install, complete=True)
        result = self.create()
        self.assertEqual(result["version"], "A20261117-4.4")
        self.program(self.install, b"failed new release")
        self.write(self.install / "_internal/new-file.dll", b"failed extra DLL")
        failed = snapshot._inventory(self.install, complete=True)
        self.add_data(2)
        before = self.business()
        restored = snapshot.restore(self.install, self.data, self.saved)
        self.assertEqual(snapshot._inventory(self.install, complete=True), old)
        self.assertEqual(snapshot._inventory(Path(restored["failed_program"]), complete=True), failed)
        self.assertEqual(self.business(), before)
        self.assert_rows([1, 2])
        self.assertFalse((self.saved / "program/license.dat").exists())
        self.assertFalse((self.saved / "program/mobile_sync_state.json").exists())
        self.assertFalse((self.saved / "program/data").exists())

    def test_missing_or_partial_failed_install_can_be_restored(self):
        old = snapshot._inventory(self.install, complete=True)
        self.create()
        (self.install / snapshot.TARGETS[0]).rename(self.saved / "externally-displaced-executable")
        (self.install / "_internal").rename(self.saved / "externally-displaced-internal")
        self.write(self.install / "_internal/partial.dll", b"partial copied new release")
        self.add_data(2)
        before = self.business()
        snapshot.restore(self.install, self.data, self.saved)
        self.assertEqual(snapshot._inventory(self.install, complete=True), old)
        self.assertEqual(self.business(), before)

    def test_partial_restore_failure_reverses_only_program_moves(self):
        self.create()
        self.program(self.install, b"failed new release")
        current = snapshot._inventory(self.install, complete=True)
        original_move = snapshot._move
        calls = 0

        def failing_move(source, destination):
            nonlocal calls
            calls += 1
            if calls == 4:
                self.add_data(2)
                raise OSError("injected partial restore failure")
            return original_move(source, destination)

        with patch.object(snapshot, "_move", side_effect=failing_move):
            with self.assertRaisesRegex(snapshot.SnapshotError, "previous live program was put back"):
                snapshot.restore(self.install, self.data, self.saved)
        self.assertEqual(snapshot._inventory(self.install, complete=True), current)
        self.assert_rows([1, 2])
        self.assertEqual((self.data / "originals/new-2.jpg").read_bytes(), b"new original 2")
        self.assertEqual((self.install / "mobile_sync_state.json").read_bytes(), b"new state 2")

    def test_restore_and_recovery_failure_keep_all_program_evidence_and_business_data(self):
        self.create()
        self.program(self.install, b"failed new release")
        original_move = snapshot._move
        calls = 0

        def failing_move(source, destination):
            nonlocal calls
            calls += 1
            if calls in (4, 5):
                if calls == 4:
                    self.add_data(2)
                raise OSError("injected move failure")
            return original_move(source, destination)

        with patch.object(snapshot, "_move", side_effect=failing_move):
            with self.assertRaisesRegex(snapshot.SnapshotError, "recovery also failed"):
                snapshot.restore(self.install, self.data, self.saved)
        self.assert_rows([1, 2])
        self.assertEqual((self.data / "originals/new-2.jpg").read_bytes(), b"new original 2")
        evidence = list(self.saved.glob("failed-program-*"))
        self.assertTrue(any((path / snapshot.TARGETS[1]).is_file() for path in evidence))
        self.assertEqual(snapshot.verify(self.install, self.data, self.saved)["version"], "A20261117-4.4")

    def test_manifest_or_payload_corruption_stops_before_program_mutation(self):
        self.create()
        current = snapshot._inventory(self.install, complete=True)
        for relative in ("program/_internal/runtime.dll", snapshot.MANIFEST, snapshot.MANIFEST_HASH):
            with self.subTest(relative=relative):
                path = self.saved / relative
                original = path.read_bytes()
                path.write_bytes(b"corrupt")
                with self.assertRaises((snapshot.SnapshotError, ValueError)):
                    snapshot.restore(self.install, self.data, self.saved)
                self.assertEqual(snapshot._inventory(self.install, complete=True), current)
                path.write_bytes(original)

    def test_snapshot_create_never_reuses_an_existing_directory(self):
        self.create()
        original = (self.saved / snapshot.MANIFEST).read_bytes()
        with self.assertRaises(FileExistsError):
            self.create()
        self.assertEqual((self.saved / snapshot.MANIFEST).read_bytes(), original)

    def test_source_changes_during_capture_leave_no_ready_manifest(self):
        original_copy = snapshot._copy_targets

        def change_source(source, destination, records):
            original_copy(source, destination, records)
            self.write(self.install / "_internal/added-during-copy.dll", b"changed")

        with patch.object(snapshot, "_copy_targets", side_effect=change_source):
            with self.assertRaisesRegex(snapshot.SnapshotError, "changed while creating"):
                self.create()
        self.assertFalse((self.saved / snapshot.MANIFEST).exists())

    def test_capacity_checks_run_before_snapshot_copy_and_before_restore_moves(self):
        before = snapshot._inventory(self.install, complete=True)
        with patch.object(snapshot.shutil, "disk_usage", return_value=SimpleNamespace(free=0)):
            with self.assertRaisesRegex(snapshot.SnapshotError, "Insufficient space"):
                self.create()
        self.assertFalse(self.saved.exists())
        self.create()
        saved_entries = set(self.saved.iterdir())
        with patch.object(snapshot.shutil, "disk_usage", return_value=SimpleNamespace(free=0)):
            with self.assertRaisesRegex(snapshot.SnapshotError, "Insufficient space"):
                snapshot.restore(self.install, self.data, self.saved)
        self.assertEqual(set(self.saved.iterdir()), saved_entries)
        self.assertEqual(snapshot._inventory(self.install, complete=True), before)

    def test_restore_refuses_live_program_changes_before_first_move(self):
        self.create()
        original_copy = snapshot._copy_targets

        def change_live_program(source, destination, records):
            original_copy(source, destination, records)
            self.write(self.install / "_internal/concurrent.dll", b"another process changed code")

        with patch.object(snapshot, "_copy_targets", side_effect=change_live_program), patch.object(snapshot, "_move") as move:
            with self.assertRaisesRegex(snapshot.SnapshotError, "no program was moved"):
                snapshot.restore(self.install, self.data, self.saved)
        move.assert_not_called()

    def test_cross_filesystem_snapshot_is_refused_before_copy(self):
        control = self.install / ".deployment-snapshots"
        control.mkdir()
        original_stat = Path.stat

        def different_device(path, *args, **kwargs):
            info = original_stat(path, *args, **kwargs)
            if path == control:
                return SimpleNamespace(st_dev=info.st_dev + 1, st_mode=info.st_mode, st_file_attributes=getattr(info, "st_file_attributes", 0))
            return info

        with patch.object(Path, "stat", different_device):
            with self.assertRaisesRegex(snapshot.SnapshotError, "share a filesystem"):
                self.create()
        self.assertFalse(self.saved.exists())

    def test_root_overlap_unrelated_snapshot_or_different_data_root_is_rejected(self):
        for data, target, replacement in (
            (self.install / "data", self.saved, self.replacement),
            (self.data, self.install / "_internal/backup", self.replacement),
            (self.data, self.data / "backup", self.replacement),
            (self.data, self.saved, self.install),
        ):
            with self.subTest(data=data, target=target), self.assertRaises(snapshot.SnapshotError):
                snapshot.create(self.install, data, target, "old", replacement)
        self.create()
        other = self.data.parent / "different-data"
        other.mkdir()
        with self.assertRaisesRegex(snapshot.SnapshotError, "another install"):
            snapshot.verify(self.install, other, self.saved)

    def test_restore_lock_is_exclusive_and_not_removed_when_owned_by_another_call(self):
        self.create()
        lock = self.install / ".deployment-snapshots/.program-transaction.lock"
        lock.write_bytes(b"existing transaction")
        with self.assertRaises(FileExistsError):
            snapshot.restore(self.install, self.data, self.saved)
        self.assertEqual(lock.read_bytes(), b"existing transaction")

    def test_hardlinked_program_is_rejected_without_touching_business_data(self):
        source = self.install / "_internal/runtime.dll"
        os.link(source, self.install / "_internal/hardlink.dll")
        before = self.business()
        with self.assertRaises(snapshot.SnapshotError):
            self.create()
        self.assertEqual(self.business(), before)

    @unittest.skipIf(os.name == "nt", "Windows symlink permissions vary; separate junction test covers Windows")
    def test_symlinked_targets_and_parent_directories_are_rejected(self):
        source = self.install / snapshot.TARGETS[0]
        source.unlink()
        source.symlink_to(self.data / "records.db")
        with self.assertRaises(snapshot.SnapshotError):
            self.create()
        source.unlink()
        self.program(self.install, b"previous")
        link = self.install.parent / "linked-install"
        link.symlink_to(self.install, target_is_directory=True)
        with self.assertRaises(snapshot.SnapshotError):
            snapshot.create(link, self.data, self.saved, "old", self.replacement)

    @unittest.skipUnless(os.name == "nt", "Windows junction/reparse behavior")
    def test_windows_junction_inside_program_is_rejected(self):
        junction = self.install / "_internal/junction"
        result = subprocess.run(["cmd", "/c", "mklink", "/J", str(junction), str(self.data)], capture_output=True, text=True)
        if result.returncode:
            self.skipTest("Junction creation unavailable")
        with self.assertRaises(snapshot.SnapshotError):
            self.create()

    def test_reparse_attribute_is_rejected_even_without_symlink_mode(self):
        self.assertTrue(snapshot._linked(SimpleNamespace(st_mode=stat.S_IFDIR, st_file_attributes=0x400)))

    def test_cli_isolated_json_contract_preserves_manifest_version(self):
        arguments = ["--install-root", str(self.install), "--data-root", str(self.data), "--snapshot", str(self.saved)]
        self.create()
        with contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(snapshot.main(["verify", *arguments]), 0)
        document = json.loads(output.getvalue())
        self.assertTrue(document["ok"])
        self.assertEqual(document["version"], "A20261117-4.4")
        helper = Path(snapshot.__file__).resolve()
        run = subprocess.run([sys.executable, "-I", str(helper), "verify", *arguments], capture_output=True, text=True, timeout=30)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(json.loads(run.stdout)["version"], document["version"])

    def test_cli_cp1252_console_supports_chinese_paths_for_all_actions(self):
        root = self.install.parent
        translated_install, translated_data = root / "安装程序", root / "工程资料"
        self.install.rename(translated_install)
        self.data.rename(translated_data)
        self.install, self.data = translated_install, translated_data
        self.saved = self.install / ".deployment-snapshots/发布前备份"
        if shutil.disk_usage(self.install).free < 512 * 1024**2:
            self.skipTest("Subprocess capacity guard requires free test disk space")
        helper = Path(snapshot.__file__).resolve()
        common = ["--install-root", str(self.install), "--data-root", str(self.data), "--snapshot", str(self.saved)]
        environment = {**os.environ, "PYTHONIOENCODING": "cp1252"}
        for action in ("create", "verify", "restore"):
            arguments = [sys.executable, "-I", str(helper), action, *common]
            if action == "create":
                arguments += ["--version", "A20261117-4.4", "--replacement-root", str(self.replacement)]
            result = subprocess.run(arguments, env=environment, capture_output=True, encoding="ascii", timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)["version"], "A20261117-4.4")
        # A failing call must also return an ASCII error, without a console encoding crash.
        failed = subprocess.run([sys.executable, "-I", str(helper), "create", *common, "--version", "old", "--replacement-root", str(self.replacement)], env=environment, capture_output=True, encoding="ascii", timeout=30)
        self.assertNotEqual(failed.returncode, 0)
        self.assertNotIn("UnicodeEncodeError", failed.stderr)


if __name__ == "__main__":
    unittest.main()
