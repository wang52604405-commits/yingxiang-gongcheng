# -*- coding: utf-8 -*-
"""正式安装包发布的网络重试与原子切换契约。"""

from __future__ import annotations

import subprocess
import tempfile
import hashlib
import json
import unittest
from pathlib import Path
from unittest.mock import patch

import publish_update


class ReleaseTransportTest(unittest.TestCase):
    def test_transport_failure_retries_then_succeeds(self):
        failed = subprocess.CompletedProcess(["ssh"], 255, "", "connection timed out")
        passed = subprocess.CompletedProcess(["ssh"], 0, "ok", "")
        with patch.object(
            publish_update.subprocess,
            "run",
            side_effect=[failed, passed],
        ) as runner, patch.object(publish_update.time, "sleep") as pause:
            result = publish_update._run_with_transport_retry(
                ["ssh", "example.invalid"],
                timeout=90,
            )

        self.assertEqual(result.returncode, 0)
        self.assertEqual(runner.call_count, 2)
        pause.assert_called_once_with(2)

    def test_remote_command_failure_is_not_retried(self):
        failed = subprocess.CompletedProcess(["ssh"], 1, "", "file missing")
        with patch.object(
            publish_update.subprocess,
            "run",
            return_value=failed,
        ) as runner, patch.object(publish_update.time, "sleep") as pause:
            result = publish_update._run_with_transport_retry(
                ["ssh", "example.invalid"],
                timeout=90,
            )

        self.assertEqual(result.returncode, 1)
        runner.assert_called_once()
        pause.assert_not_called()

    def test_upload_supports_old_scp_timeouts_and_a_temporary_target(self):
        passed = subprocess.CompletedProcess(["scp"], 0, "", "")
        with patch.object(
            publish_update,
            "_run_with_transport_retry",
            return_value=passed,
        ) as runner:
            publish_update.scp_upload(Path("installer.exe"), "/tmp/.installer.uploading")

        command = runner.call_args.args[0]
        self.assertNotIn("-O", command)
        self.assertIn("ServerAliveInterval=10", command)
        self.assertEqual(runner.call_args.kwargs["timeout"], 1200)
        self.assertTrue(command[-1].endswith(":/tmp/.installer.uploading"))

    def test_publish_promotes_only_after_hash_verification(self):
        source = Path(__file__).resolve().parents[1] / "publish_update.py"
        text = source.read_text(encoding="utf-8")
        upload_start = text.index("def upload_installer()")
        sync_start = text.index("def sync_website_download()", upload_start)
        upload = text[upload_start:sync_start]
        self.assertLess(upload.index("remote_hash ="), upload.index('ssh_cmd(["mv"'))
        self.assertIn('f"{REMOTE_UPDATES}/.{REMOTE_EXE_NAME}.uploading"', upload)

    def test_capacity_check_is_read_only_and_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            installer = Path(tmp) / "installer.exe"
            installer.write_bytes(b"new-package")
            for capacity in ("invalid", "Filesystem 1024-blocks Used Available Capacity Mounted on\n/dev/test 100 99 1 99% /"):
                with self.subTest(capacity=capacity), patch.object(
                    publish_update, "INSTALLER", installer
                ), patch.object(publish_update, "DRY_RUN", False), patch.object(
                    publish_update, "ssh_cmd", side_effect=[
                        subprocess.CompletedProcess([], 0, "200", ""),
                        subprocess.CompletedProcess([], 0, capacity, ""),
                    ]
                ) as remote:
                    with self.assertRaises(SystemExit):
                        publish_update.check_remote_capacity()
                    self.assertEqual(remote.call_count, 2)
                    self.assertEqual(remote.call_args.args[0], ["df", "-Pk", publish_update.REMOTE_UPDATES])
                    self.assertNotIn("rm ", str(remote.call_args_list))

    def test_capacity_check_reserves_shared_filesystem_space_for_both_copies(self):
        with tempfile.TemporaryDirectory() as tmp:
            installer = Path(tmp) / "installer.exe"
            installer.write_bytes(b"new-package")
            capacity = "Filesystem 1024-blocks Used Available Capacity Mounted on\n/dev/test 1000000 1 999999 1% /"
            with patch.object(publish_update, "INSTALLER", installer), patch.object(
                publish_update, "DRY_RUN", False
            ), patch.object(publish_update, "ssh_cmd", side_effect=[
                subprocess.CompletedProcess([], 0, "200", ""),
                subprocess.CompletedProcess([], 0, capacity, ""),
                subprocess.CompletedProcess([], 0, capacity, ""),
            ]) as remote:
                publish_update.check_remote_capacity()
            self.assertEqual(remote.call_args_list[-1].args[0], ["df", "-Pk", publish_update.REMOTE_SITE_DOWNLOAD])

    def test_backup_uses_an_exclusive_directory_without_overwriting_history(self):
        backup = "/var/www/updates/installer-backup-example/album-installer.exe"
        with patch.object(publish_update, "DRY_RUN", False), patch.object(
            publish_update, "ssh_cmd", side_effect=[
                subprocess.CompletedProcess([], 0, "", ""),
                subprocess.CompletedProcess([], 0, backup + "\n", ""),
            ]
        ) as remote:
            self.assertEqual(publish_update.backup_remote_installer(), backup)
        script = remote.call_args.args[0][2]
        self.assertIn("mktemp -d", script)
        self.assertNotIn("rm ", script)

    def test_low_capacity_stops_main_before_any_publish_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            installer = Path(tmp) / "installer.exe"
            installer.write_bytes(b"new-package")
            with patch.object(publish_update, "INSTALLER", installer), patch.object(
                publish_update, "current_remote_version", return_value="old"
            ), patch.object(publish_update, "_local_version", return_value="new"), patch.multiple(
                publish_update.build_all, step1_pyinstaller=lambda: True,
                step2_manifest=lambda: True, step3_inno=lambda: True,
                step4_verify_no_key=lambda: True,
            ), patch.object(publish_update, "check_remote_capacity", side_effect=SystemExit("capacity")), patch.object(
                publish_update, "backup_remote_installer"
            ) as backup, patch.object(publish_update, "upload_installer") as upload, patch.object(
                publish_update, "write_remote_version"
            ) as version, patch.object(publish_update, "ssh_cmd") as remote:
                with self.assertRaisesRegex(SystemExit, "capacity"):
                    publish_update.main()
            backup.assert_not_called()
            upload.assert_not_called()
            version.assert_not_called()
            remote.assert_not_called()

    def test_public_verification_rejects_stale_manifest_and_transport_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            installer = Path(tmp) / "installer.exe"
            installer.write_bytes(b"new-package")
            expected = {"version": "new", "sha256": hashlib.sha256(installer.read_bytes()).hexdigest(), "size": installer.stat().st_size}
            for payload, code in ((expected, 0), ({**expected, "version": "old"}, 0), ({**expected, "sha256": "0" * 64}, 0), ({**expected, "size": 0}, 0), (expected, 22)):
                with self.subTest(payload=payload, code=code), patch.object(
                    publish_update, "INSTALLER", installer
                ), patch.object(publish_update, "_local_version", return_value="new"), patch.object(
                    publish_update.subprocess, "run", return_value=subprocess.CompletedProcess([], code, json.dumps(payload), "")
                ):
                    if code == 0 and payload == expected:
                        publish_update.verify_remote()
                    else:
                        with self.assertRaisesRegex(SystemExit, "验证未通过"):
                            publish_update.verify_remote()


if __name__ == "__main__":
    unittest.main()
