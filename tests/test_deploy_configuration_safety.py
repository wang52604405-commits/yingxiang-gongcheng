"""Production upgrades preserve existing configuration and stop on differences."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import call, patch

import deploy_auth


class DeploymentConfigurationSafetyTest(unittest.TestCase):
    @unittest.skipIf(os.name == "nt", "requires ordinary POSIX symlinks")
    def test_readonly_fingerprints_reject_changed_files_and_link_without_rewriting(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            targets = [root / name for name in ("dropin", "nginx", "cron", "staged-nginx")]
            for index, target in enumerate(targets):
                target.write_bytes(f"configuration-{index}".encode())
            link = root / "enabled"
            link.symlink_to(targets[1])
            expected = {
                "files": [{"path": str(target), "sha256": hashlib.sha256(target.read_bytes()).hexdigest()} for target in targets],
                "link": str(link), "link_target": str(targets[1]),
            }

            def verify():
                return subprocess.run(
                    [sys.executable, "-B", "-c", deploy_auth.VERIFY_CONFIGURATION_SCRIPT, json.dumps(expected)],
                    capture_output=True, text=True,
                )

            before = [(target.read_bytes(), target.stat().st_mtime_ns) for target in targets]
            self.assertEqual(verify().returncode, 0)
            self.assertEqual([(target.read_bytes(), target.stat().st_mtime_ns) for target in targets], before)
            for target in targets:
                original = target.read_bytes()
                target.write_bytes(b"different configuration")
                rejected = verify()
                self.assertNotEqual(rejected.returncode, 0)
                self.assertIn(str(target), rejected.stderr)
                self.assertEqual(target.read_bytes(), b"different configuration")
                target.write_bytes(original)
            link.unlink()
            link.symlink_to(targets[0])
            self.assertNotEqual(verify().returncode, 0)
            self.assertEqual(os.readlink(link), str(targets[0]))
            link.unlink()
            self.assertNotEqual(verify().returncode, 0)
            self.assertFalse(link.exists())

    def test_preflight_compares_live_and_staged_templates_and_loaded_service(self):
        success = SimpleNamespace(returncode=0, stdout="", stderr="")
        with patch.object(deploy_auth, "ssh_python", return_value=success) as script, patch.object(
            deploy_auth, "ssh", return_value=success,
        ) as remote:
            deploy_auth.require_existing_service_configuration("/staged/deploy")
        self.assertEqual(script.call_args.args[0], deploy_auth.VERIFY_CONFIGURATION_SCRIPT)
        expected = json.loads(script.call_args.args[1])
        self.assertEqual(len(expected["files"]), 6)
        for name, target in (
            ("album-auth-mobile-v1.conf", deploy_auth.DROPIN_TARGET),
            ("nginx-domain.conf", deploy_auth.DOMAIN_NGINX_TARGET),
            ("album-auth-backup.cron", deploy_auth.BACKUP_CRON_TARGET),
        ):
            digest = hashlib.sha256((deploy_auth.REPO / "server/deploy" / name).read_bytes()).hexdigest()
            self.assertIn({"path": target, "sha256": digest}, expected["files"])
            self.assertIn({"path": "/staged/deploy/" + name, "sha256": digest}, expected["files"])
        self.assertEqual(expected["link_target"], deploy_auth.DOMAIN_NGINX_TARGET)
        command = remote.call_args.args[0]
        self.assertIn("NeedDaemonReload --value", command)
        self.assertIn("EnvironmentFiles --value", command)
        self.assertIn("--worker-class gthread -w 1 --threads 4 --timeout 300", command)
        self.assertIn("nginx -t", command)
        with patch.object(deploy_auth, "ssh_python", return_value=success), patch.object(
            deploy_auth, "ssh", return_value=SimpleNamespace(returncode=1),
        ), self.assertRaises(SystemExit):
            deploy_auth.require_existing_service_configuration()

    def test_live_configuration_mismatch_stops_before_first_remote_write(self):
        with patch.object(deploy_auth, "SSH_KEY", Path(__file__)), patch.object(
            deploy_auth, "require_mobile_environment",
        ), patch.object(deploy_auth, "require_free_space", return_value=8 * 1024 * 1024), patch.object(
            deploy_auth, "require_existing_service_configuration", side_effect=SystemExit("configuration differs"),
        ), patch.object(deploy_auth, "ssh") as remote, patch.object(deploy_auth, "scp_file") as upload:
            with self.assertRaises(SystemExit):
                deploy_auth.main()
        remote.assert_not_called()
        upload.assert_not_called()

    def test_successful_code_upgrade_preserves_configuration_without_reloading_it(self):
        commands = []
        success = SimpleNamespace(returncode=0, stdout="", stderr="")

        def remote(command, check=True):
            commands.append(command)
            if command == "date +%Y%m%d-%H%M%S":
                return SimpleNamespace(returncode=0, stdout="20261118-020000", stderr="")
            return success

        with patch.object(deploy_auth, "SSH_KEY", Path(__file__)), patch.object(
            deploy_auth, "require_mobile_environment",
        ), patch.object(deploy_auth, "require_free_space", return_value=8 * 1024 * 1024), patch.object(
            deploy_auth, "require_existing_service_configuration",
        ) as configurations, patch.object(deploy_auth, "ssh", side_effect=remote), patch.object(
            deploy_auth, "ssh_python", return_value=success,
        ), patch.object(deploy_auth, "scp_file"), patch.object(
            deploy_auth, "production_health", return_value=(True, "healthy"),
        ), patch.object(deploy_auth, "remote_free_space_kb", return_value=8 * 1024 * 1024):
            self.assertEqual(deploy_auth.main(), 0)
        configurations.assert_has_calls([
            call(), call("/opt/album-auth/releases/deploy-20261118-020000/server/deploy"),
        ])
        self.assertEqual(configurations.call_count, 2)
        self.assertTrue(any("systemctl restart album-auth" in command for command in commands))
        for command in commands:
            self.assertNotIn("/etc/", command)
            self.assertNotIn("daemon-reload", command)
            self.assertNotIn("reload nginx", command)
            self.assertNotIn("ln -s", command)


if __name__ == "__main__":
    unittest.main()
