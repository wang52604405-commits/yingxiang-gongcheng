# -*- coding: utf-8 -*-
"""正式安装包发布的网络重试与原子切换契约。"""

from __future__ import annotations

import subprocess
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

    def test_upload_uses_legacy_scp_timeouts_and_a_temporary_target(self):
        passed = subprocess.CompletedProcess(["scp"], 0, "", "")
        with patch.object(
            publish_update,
            "_run_with_transport_retry",
            return_value=passed,
        ) as runner:
            publish_update.scp_upload(Path("installer.exe"), "/tmp/.installer.uploading")

        command = runner.call_args.args[0]
        self.assertIn("-O", command)
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


if __name__ == "__main__":
    unittest.main()
