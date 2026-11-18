"""Exercise the read-only dependency gate without contacting any server."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import deploy_auth


ROOT = Path(__file__).resolve().parents[1]
CHECKER = ROOT / "server" / "deploy" / "check_dependencies.py"


class InstalledDependencySafetyTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="album-dependency-check-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.site = self.root / "site"
        self.site.mkdir()
        self.requirements = self.root / "requirements.txt"
        self.snapshot = self.root / "dependency-versions.json"
        self.install_metadata("album-dependency-fixture", "1.2.3")

    def install_metadata(self, name, version, requires=()):
        directory = self.site / f"{name.replace('-', '_')}-{version}.dist-info"
        directory.mkdir()
        metadata = f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n"
        metadata += "".join(f"Requires-Dist: {value}\n" for value in requires)
        (directory / "METADATA").write_text(metadata, encoding="utf-8")

    def run_checker(self, requirements, *, snapshot=False):
        self.requirements.write_text(requirements, encoding="utf-8")
        environment = {
            **os.environ,
            "PYTHONPATH": str(self.site),
            "PYTHONDONTWRITEBYTECODE": "1",
            "PIP_DISABLE_PIP_VERSION_CHECK": "1",
            "PIP_NO_CACHE_DIR": "1",
        }
        command = [sys.executable, "-B", str(CHECKER), "--requirements", str(self.requirements)]
        if snapshot:
            command += ["--snapshot", str(self.snapshot)]
        before = {path.relative_to(self.site): path.read_bytes() for path in self.site.rglob("*") if path.is_file()}
        result = subprocess.run(command, env=environment, capture_output=True, text=True, encoding="utf-8", timeout=45)
        after = {path.relative_to(self.site): path.read_bytes() for path in self.site.rglob("*") if path.is_file()}
        self.assertEqual(after, before, "The gate must not change installed distributions")
        return result

    def test_actual_versions_and_active_markers_pass_without_installing(self):
        result = self.run_checker(
            '# unchanged, unpinned packages still need an installed version\n'
            'album-dependency-fixture>=1,<2\n'
            'pip\n'
            'album-never-installed; python_version < "1"\n',
            snapshot=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        report = json.loads(self.snapshot.read_text(encoding="utf-8"))
        self.assertEqual(report["installed_versions"]["album-dependency-fixture"], "1.2.3")
        self.assertEqual(report["checked_requirements"], 2)
        self.assertEqual(report["requirements_sha256"], hashlib.sha256(self.requirements.read_bytes()).hexdigest())
        self.assertIn(report["sha256"], result.stdout)
        if os.name != "nt":
            self.assertEqual(self.snapshot.stat().st_mode & 0o777, 0o600)

    def test_missing_or_incompatible_installed_version_stops(self):
        for requirement, expected in (("album-never-installed>=1", "缺少"), ("album-dependency-fixture>=2", "不满足版本要求")):
            with self.subTest(requirement=requirement):
                result = self.run_checker(requirement, snapshot=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(expected, result.stderr)
                self.assertFalse(self.snapshot.exists())

    def test_missing_transitive_distribution_stops_even_when_direct_version_satisfies(self):
        self.install_metadata("album-broken-fixture", "1.0", ("album-never-installed>=1",))
        result = self.run_checker("album-broken-fixture==1.0", snapshot=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("间接依赖", result.stderr)
        self.assertFalse(self.snapshot.exists())

    def test_unsupported_or_malformed_requirements_fail_closed_without_echoing_urls(self):
        for requirement in (
            "-r /another/requirements.txt", "--index-url https://example.invalid/secret-token",
            "album-dependency-fixture @ https://example.invalid/secret-token.whl",
            "album-dependency-fixture[unknown]", 'pip; python_version >>> "3"',
            "album-dependency-fixture\\", "# comments only\n",
        ):
            with self.subTest(requirement=requirement):
                result = self.run_checker(requirement, snapshot=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(self.snapshot.exists())
                self.assertNotIn("secret-token", result.stdout + result.stderr)

    def test_evidence_snapshot_never_overwrites_an_existing_file(self):
        self.snapshot.write_text("preserve previous evidence", encoding="utf-8")
        result = self.run_checker("album-dependency-fixture==1.2.3", snapshot=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.snapshot.read_text(encoding="utf-8"), "preserve previous evidence")

    def test_deployment_gate_failure_precedes_config_or_live_code_changes(self):
        commands = []

        def remote(command, check=True):
            commands.append(command)
            if "check_dependencies.py" in command:
                raise SystemExit("injected incompatible live dependency")
            if command == "date +%Y%m%d-%H%M%S":
                return SimpleNamespace(returncode=0, stdout="20261118-020000", stderr="")
            if "&& printf present;" in command:
                return SimpleNamespace(returncode=0, stdout="present", stderr="")
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        with patch.object(deploy_auth, "SSH_KEY", Path(__file__)), patch.object(
            deploy_auth, "require_mobile_environment"
        ), patch.object(deploy_auth, "require_free_space", return_value=8 * 1024 * 1024), patch.object(
            deploy_auth, "ssh", side_effect=remote
        ), patch.object(deploy_auth, "ssh_python", return_value=SimpleNamespace(stdout="backup ok")), patch.object(
            deploy_auth, "build_release_archive", return_value=[]
        ), patch.object(deploy_auth, "scp_file"), patch.object(Path, "read_bytes", return_value=b"payload"):
            with self.assertRaisesRegex(SystemExit, "incompatible live dependency"):
                deploy_auth.main()
        joined = "\n".join(commands)
        self.assertIn("--snapshot /opt/album-auth/backups/deploy-20261118-020000/dependency-versions.json", joined)
        self.assertNotIn("pip install", joined)
        self.assertNotIn("systemctl daemon-reload", joined)
        self.assertNotIn("systemctl restart", joined)
        self.assertNotIn("cp -a /opt/album-auth/releases/", joined)
        self.assertNotIn("install -m 0644", joined)

    def test_release_requires_both_safety_helpers(self):
        self.assertIn("check_dependencies.py", deploy_auth.DEPLOY_FILES)
        self.assertIn("code_rollback.py", deploy_auth.DEPLOY_FILES)
        with tempfile.TemporaryDirectory() as directory, patch.object(deploy_auth, "REPO", Path(directory)):
            with self.assertRaisesRegex(SystemExit, "安全校验文件"):
                deploy_auth.build_release_archive(Path(directory) / "payload.tar.gz", CHECKER)


if __name__ == "__main__":
    unittest.main()
