# -*- coding: utf-8 -*-
"""服务器部署材料的静态安全/兼容契约。无需连接生产服务器。"""

from __future__ import annotations

import re
import importlib.util
import tarfile
import tempfile
import unittest
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import deploy_auth


ROOT = Path(__file__).resolve().parents[1]
DEPLOY = ROOT / "server" / "deploy"


class ServerDeployContractTest(unittest.TestCase):
    def read(self, name: str) -> str:
        return (DEPLOY / name).read_text(encoding="utf-8")

    def powershell_run_bodies(self, workflow: str) -> list[str]:
        lines = workflow.splitlines()
        bodies: list[str] = []
        index = 0
        while index < len(lines):
            if re.match(r"\s+shell:\s+powershell\s*$", lines[index]):
                cursor = index + 1
                while cursor < len(lines) and not re.match(r"\s+(?:- name:|run:)", lines[cursor]):
                    cursor += 1
                matched = re.match(r"(\s+)run:\s*\|\s*$", lines[cursor]) if cursor < len(lines) else None
                if matched:
                    indent = len(matched.group(1))
                    cursor += 1
                    body: list[str] = []
                    while cursor < len(lines):
                        line = lines[cursor]
                        if line.strip() == "" or (len(line) - len(line.lstrip(" "))) > indent:
                            body.append(line)
                            cursor += 1
                            continue
                        break
                    bodies.append("\n".join(body))
            index += 1
        return bodies

    def test_systemd_loads_secrets_only_from_restricted_environment_file(self):
        service = self.read("album-auth.service")
        self.assertIn(
            "EnvironmentFile=/etc/album-auth/album-auth.env",
            service,
        )
        self.assertNotRegex(service, r"(?m)^Environment=")
        self.assertNotIn("ALBUM_SERVER_SECRET=", service)
        self.assertNotIn("ALBUM_MAIL_PASS=", service)
        self.assertIn("NoNewPrivileges=true", service)
        self.assertIn("ProtectSystem=strict", service)
        self.assertIn("ReadWritePaths=/opt/album-auth/data", service)

    def test_production_dropin_overrides_legacy_named_dropins(self):
        deployer = (ROOT / "deploy_auth.py").read_text(encoding="utf-8")
        dropin = self.read("album-auth-mobile-v1.conf")
        self.assertIn(
            'DROPIN_TARGET = "/etc/systemd/system/album-auth.service.d/zz-mobile-v1.conf"',
            deployer,
        )
        self.assertIn("EnvironmentFile=-/etc/album-auth/mobile.env", dropin)
        self.assertIn("EnvironmentFiles --value", deployer)

    def test_production_deploy_requires_wechat_secrets_before_any_remote_write(self):
        deployer = (ROOT / "deploy_auth.py").read_text(encoding="utf-8")
        env_path = "/etc/album-auth/mobile.env"
        preflight_start = deployer.index("def require_mobile_environment()")
        preflight_end = deployer.index("\ndef ", preflight_start + len("def "))
        preflight = deployer[preflight_start:preflight_end]

        self.assertIn(f'test -s {{env_path}}', preflight)
        self.assertIn(
            "grep -Eq '^ALBUM_WECHAT_APP_ID=.+$' {env_path}",
            preflight,
        )
        self.assertIn(
            "grep -Eq '^ALBUM_WECHAT_APP_SECRET=.+$' {env_path}",
            preflight,
        )
        self.assertNotIn("cat ", preflight)
        self.assertNotIn("source ", preflight)
        self.assertNotIn("print(", preflight)

        preflight_call = deployer.index("    require_mobile_environment()")
        first_remote_write = deployer.index('    ssh(f"mkdir -p')
        self.assertLess(preflight_call, first_remote_write)

    def test_wechat_secret_preflight_is_silent_and_fails_closed(self):
        expected_command = (
            "test -s /etc/album-auth/mobile.env && "
            "grep -Eq '^ALBUM_WECHAT_APP_ID=.+$' /etc/album-auth/mobile.env && "
            "grep -Eq '^ALBUM_WECHAT_APP_SECRET=.+$' /etc/album-auth/mobile.env"
        )
        failed = SimpleNamespace(
            returncode=1,
            stdout="must-not-be-reported",
            stderr="must-not-be-reported",
        )
        with patch.object(deploy_auth, "ssh", return_value=failed) as remote_check:
            with self.assertRaises(SystemExit) as context:
                deploy_auth.require_mobile_environment()

        remote_check.assert_called_once_with(expected_command, check=False)
        self.assertNotIn("must-not-be-reported", str(context.exception))

        passed = SimpleNamespace(returncode=0, stdout="", stderr="")
        with patch.object(deploy_auth, "ssh", return_value=passed) as remote_check:
            self.assertIsNone(deploy_auth.require_mobile_environment())
        remote_check.assert_called_once_with(expected_command, check=False)

    def test_deploy_preserves_all_existing_snapshots(self):
        deployer = (ROOT / "deploy_auth.py").read_text(encoding="utf-8")
        self.assertNotIn("prune_remote_snapshots", deployer)
        self.assertNotIn("rm -rf", deployer)
        self.assertNotIn("head -n -", deployer)

    def test_deploy_refuses_to_start_when_free_space_is_below_the_guard(self):
        too_low = SimpleNamespace(returncode=0, stdout="1024\n", stderr="")
        with patch.object(deploy_auth, "ssh", return_value=too_low):
            with self.assertRaises(SystemExit) as context:
                deploy_auth.require_free_space()
        self.assertIn("可用空间", str(context.exception))

        unknown = SimpleNamespace(returncode=0, stdout="", stderr="")
        with patch.object(deploy_auth, "ssh", return_value=unknown):
            with self.assertRaises(SystemExit):
                deploy_auth.require_free_space()

        healthy_kb = 8 * 1024 * 1024
        healthy = SimpleNamespace(returncode=0, stdout=f"{healthy_kb}\n", stderr="")
        with patch.object(deploy_auth, "ssh", return_value=healthy):
            self.assertEqual(deploy_auth.require_free_space(), healthy_kb)

    def test_low_disk_stops_before_any_snapshot_write_or_deletion(self):
        low = SimpleNamespace(returncode=0, stdout="1024\n", stderr="")
        with patch.object(deploy_auth, "SSH_KEY", Path(__file__)), patch.object(
            deploy_auth, "require_mobile_environment"
        ), patch.object(deploy_auth, "ssh", return_value=low) as remote:
            with self.assertRaises(SystemExit):
                deploy_auth.main()
        remote.assert_called_once_with("df -Pk / | awk 'NR==2 {print $4}'", check=False)

    def test_space_guard_runs_before_any_remote_write(self):
        deployer = (ROOT / "deploy_auth.py").read_text(encoding="utf-8")
        preflight_call = deployer.index("    require_mobile_environment()")
        guard_call = deployer.index("free_kb = require_free_space()")
        first_remote_write = deployer.index('    ssh(f"mkdir -p')

        self.assertLess(preflight_call, guard_call)
        self.assertLess(guard_call, first_remote_write)

    def _failed_production_deploy_commands(self, failure: str) -> list[str]:
        commands: list[str] = []

        def remote(command, check=True):
            commands.append(command)
            if command == "date +%Y%m%d-%H%M%S":
                return SimpleNamespace(returncode=0, stdout="20261118-010000", stderr="")
            if "&& printf present;" in command:
                return SimpleNamespace(returncode=0, stdout="present", stderr="")
            if failure == "replacement" and command.startswith("cp -a /opt/album-auth/releases/"):
                return SimpleNamespace(returncode=1, stdout="", stderr="injected replacement failure")
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        success = SimpleNamespace(returncode=0, stdout="", stderr="")
        with patch.object(deploy_auth, "SSH_KEY", Path(__file__)), patch.object(
            deploy_auth, "require_mobile_environment"
        ), patch.object(deploy_auth, "require_free_space", return_value=8 * 1024 * 1024), patch.object(
            deploy_auth, "require_existing_service_configuration",
            side_effect=[None, SystemExit("configuration mismatch")] if failure == "configuration" else None,
        ), patch.object(
            deploy_auth, "ssh", side_effect=remote
        ), patch.object(deploy_auth, "ssh_python", return_value=success), patch.object(
            deploy_auth, "scp_file"
        ), patch.object(deploy_auth, "production_health", return_value=(True, "healthy")):
            with self.assertRaises(SystemExit):
                deploy_auth.main()
        return commands

    def test_staged_configuration_mismatch_stops_before_code_or_service_changes(self):
        commands = self._failed_production_deploy_commands("configuration")
        self.assertTrue(any(command.startswith("test ! -e /opt/album-auth/backups/deploy-") for command in commands))
        self.assertFalse(any(command.startswith("cp -a /opt/album-auth/releases/") for command in commands))
        self.assertFalse(any("systemctl restart" in command for command in commands))
        self.assertFalse(any("systemctl daemon-reload" in command for command in commands))
        self.assertFalse(any("systemctl reload nginx" in command for command in commands))

    def test_replacement_failure_rolls_back_only_managed_files(self):
        commands = self._failed_production_deploy_commands("replacement")
        rollback = next(command for command in commands if command.startswith('test "$(readlink -f'))
        self.assertIn("/runtime/.snapshot-ready", rollback)
        self.assertIn("/server/app.py", rollback)
        self.assertIn("/runtime/municipal_rules.py", rollback)
        self.assertNotIn("rsync", rollback)
        self.assertNotIn("/data/", rollback)
        self.assertNotIn("server.db", rollback)
        self.assertNotIn("/etc/", rollback)
        self.assertNotIn("daemon-reload", rollback)
        self.assertNotIn("reload nginx", rollback)

    @unittest.skipIf(sys.platform == "win32" or not shutil.which("bash"), "requires POSIX shell")
    def test_code_rollback_preserves_new_database_photos_and_unknown_files(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            backup, live = root / "backup", root / "live"
            backup.mkdir()
            (backup / "app.py").write_text("previous code", encoding="utf-8")
            (backup / "data").mkdir()
            (backup / "data/server.db").write_bytes(b"stale database")
            (live / "data/mobile_objects").mkdir(parents=True)
            (live / "data/server.db").write_bytes(b"new business records")
            (live / "data/mobile_objects/new.jpg").write_bytes(b"new original photo")
            (live / "operator-file").write_bytes(b"preserve")
            (live / "app.py").write_text("failed code", encoding="utf-8")
            (live / "new-release.py").write_text("new managed file", encoding="utf-8")
            command = deploy_auth.managed_files_rollback_command(
                str(backup), str(live), ["app.py", "new-release.py"]
            )
            subprocess.run(["bash", "-c", command], check=True)
            self.assertEqual((live / "app.py").read_text(encoding="utf-8"), "previous code")
            self.assertFalse((live / "new-release.py").exists())
            self.assertEqual((live / "data/server.db").read_bytes(), b"new business records")
            self.assertEqual((live / "data/mobile_objects/new.jpg").read_bytes(), b"new original photo")
            self.assertEqual((live / "operator-file").read_bytes(), b"preserve")

    def test_rollback_rejects_paths_outside_the_release_files(self):
        for name in ("../server.db", "/etc/passwd", "C:/Windows/system.ini", "C:server.db", r"..\server.db", ""):
            with self.subTest(name=name), self.assertRaises(ValueError):
                deploy_auth.managed_files_rollback_command("backup", "live", [name])

    def test_github_deploy_checks_changes_since_the_last_successful_release(self):
        workflow = (ROOT / ".github" / "workflows" / "deploy.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("/actions/runs?branch=main&status=success&per_page=100", workflow)
        self.assertIn("$before = $successful[0].head_sha", workflow)
        self.assertNotIn("github.event.before", workflow)
        self.assertIn("$env:GITHUB_SHA", workflow)
        self.assertIn("deploy_auth\\.py", workflow)
        self.assertIn("\\.github/workflows/deploy\\.yml", workflow)
        self.assertIn("[IO.File]::AppendAllText", workflow)
        self.assertIn("[Text.UTF8Encoding]::new($false)", workflow)
        self.assertNotIn("git diff --name-only", workflow)
        self.assertIn("api.github.com/repos/${{ github.repository }}/compare/", workflow)
        self.assertIn("$env:GITHUB_TOKEN", workflow)
        self.assertIn("GITHUB_TOKEN: ${{ github.token }}", workflow)
        self.assertIn("workflow_dispatch", workflow)
        self.assertIn("Unable to compare the pushed range; deploying server fail-safe.", workflow)

        validate, self_hosted = workflow.split("  deploy-auth:", 1)
        self.assertEqual(validate.count("actions/checkout@v7"), 1)
        self.assertNotIn("actions/checkout", self_hosted)
        archive_url = "https://github.com/${{ github.repository }}/archive/${{ github.sha }}.zip"
        self.assertEqual(self_hosted.count(archive_url), 3)
        self.assertEqual(self_hosted.count("curl.exe -fsSL --ssl-no-revoke"), 5)
        download_steps = re.findall(
            r"- name: 下载本次提交的源码\n        shell: powershell\n        run: \|\n((?:          .*\n)+)",
            workflow,
        )
        self.assertEqual(len(download_steps), 3)
        self.assertEqual(len(set(download_steps)), 1)
        self.assertIn("throw 'GITHUB_WORKSPACE is not set'", download_steps[0])
        self.assertIn("throw 'RUNNER_TEMP is not set'", download_steps[0])
        # Windows PowerShell 5.x reads the generated script as the ANSI code page.
        # A UTF-8 lead byte can swallow the closing quote, so every inline body stays ASCII.
        bodies = self.powershell_run_bodies(workflow)
        self.assertGreaterEqual(len(bodies), 3)
        for body in bodies:
            self.assertTrue(body.isascii(), body)
        downloads = [body for body in bodies if archive_url in body]
        self.assertEqual(len(downloads), 3)
        self.assertEqual(len(set(downloads)), 1)
        download = downloads[0]
        self.assertIn("curl.exe -fsSL --ssl-no-revoke -o $zipPath $url", download)
        self.assertIn("throw 'Failed to download the source zip'", download)
        self.assertIn("throw 'Windows tar.exe was not found'", download)
        self.assertNotIn("未设置", workflow)
        codepoints = re.findall(r"\[char\]0x([0-9A-F]{4})", download)
        self.assertEqual(
            "".join(chr(int(point, 16)) for point in codepoints),
            "安装脚本",
        )
        self.assertIn("[string]::Concat([char]0x5B89, [char]0x88C5, [char]0x811A, [char]0x672C, '.iss')", download)
        self.assertEqual(workflow.count("HTTPS_PROXY: http://127.0.0.1:7897"), 3)
        self.assertEqual(workflow.count("HTTP_PROXY: http://127.0.0.1:7897"), 3)
        self.assertEqual(workflow.count("ALL_PROXY: http://127.0.0.1:7897"), 3)
        self.assertEqual(workflow.count("NO_PROXY: 127.0.0.1,localhost"), 3)

        match = re.search(r"Select-String '([^']+)'", workflow)
        self.assertIsNotNone(match)
        changed = re.compile(match.group(1))
        for path in (
            "server/app.py",
            "deploy_auth.py",
            "validate_mobile_migration.py",
            ".github/workflows/deploy.yml",
        ):
            self.assertRegex(path, changed)
        for path in ("prepare_release_version.py", "app.py", "website/index.html"):
            self.assertIsNone(changed.search(path))

    def test_production_payload_is_one_whitelisted_verified_archive(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / "payload.tar.gz"
            members = deploy_auth.build_release_archive(
                target,
                ROOT / "validate_mobile_migration.py",
            )
            with tarfile.open(target, "r:gz") as archive:
                archived = archive.getnames()

        self.assertEqual(archived, members)
        self.assertIn("server/app.py", archived)
        self.assertIn("server/deploy/album-auth-backup.cron", archived)
        self.assertIn("server/templates/admin.html", archived)
        self.assertIn("validate_mobile_migration.py", archived)
        self.assertIn("municipal_rules.py", archived)
        self.assertIn("professional_templates.py", archived)
        self.assertIn("assets/professional_templates.json", archived)
        self.assertTrue(all(not name.startswith(("/", "..")) for name in archived))
        deployer = (ROOT / "deploy_auth.py").read_text(encoding="utf-8")
        self.assertIn("/opt/album-auth/{name}", deployer)
        self.assertIn("backup}/runtime/{name}", deployer)

        deployer = (ROOT / "deploy_auth.py").read_text(encoding="utf-8")
        self.assertIn("sha256sum -c -", deployer)
        self.assertIn("ServerAliveInterval=10", deployer)
        self.assertIn("timeout=120", deployer)
        self.assertIn("attempts: int = 3", deployer)

    def test_packaged_municipal_runtime_loads_without_the_source_checkout(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir)
            archive_path = target / "payload.tar.gz"
            deploy_auth.build_release_archive(archive_path, ROOT / "validate_mobile_migration.py")
            isolated = target / "isolated"
            isolated.mkdir()
            with tarfile.open(archive_path, "r:gz") as archive:
                for name in ("municipal_rules.py", "highway_rules.py", "professional_templates.py", "assets/professional_templates.json"):
                    destination = isolated / name
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    with archive.extractfile(name) as content:
                        destination.write_bytes(content.read())
            loaded = subprocess.run(
                [sys.executable, "-I", "-c", (
                    "import sys; sys.path.insert(0, sys.argv[1]); "
                    "import municipal_rules, professional_templates; "
                    "assert professional_templates.municipal_template_document(); "
                    "assert professional_templates.catalog()"
                ), str(isolated)],
                cwd=target, capture_output=True, text=True,
            )
            self.assertEqual(loaded.returncode, 0, loaded.stderr)

    def test_scp_file_retries_a_transient_disconnect(self):
        failed = SimpleNamespace(returncode=1, stdout="", stderr="lost connection")
        passed = SimpleNamespace(returncode=0, stdout="", stderr="")
        with patch.object(deploy_auth, "SERVER_HOST", "root@203.0.113.10"), patch.object(
            deploy_auth.subprocess,
            "run",
            side_effect=[failed, passed],
        ) as transfer, patch.object(deploy_auth.time, "sleep") as pause:
            result = deploy_auth.scp_file(Path("payload.tar.gz"), "/tmp/payload.tar.gz")

        self.assertEqual(result.returncode, 0)
        self.assertEqual(transfer.call_count, 2)
        pause.assert_called_once_with(2)

    def test_successful_production_deploy_dispatches_exact_wechat_source(self):
        deploy_workflow = (ROOT / ".github" / "workflows" / "deploy.yml").read_text(
            encoding="utf-8"
        )
        wechat_workflow = (
            ROOT / ".github" / "workflows" / "wechat-devtools-release.yml"
        ).read_text(encoding="utf-8")

        self.assertIn("trigger-wechat-release:", deploy_workflow)
        self.assertIn("needs: deploy", deploy_workflow)
        self.assertIn("actions: write", deploy_workflow)
        self.assertIn("createWorkflowDispatch", deploy_workflow)
        self.assertIn("source_sha: context.sha", deploy_workflow)
        self.assertIn("source_sha:", wechat_workflow)
        self.assertIn("ref: ${{ inputs.source_sha || github.sha }}", wechat_workflow)
        self.assertIn("SOURCE_COMMIT: ${{ inputs.source_sha || github.sha }}", wechat_workflow)
        self.assertNotIn("workflow_run:", wechat_workflow)

    def test_nginx_https_keeps_legacy_http_api_without_redirect(self):
        http = self.read("nginx-http.conf")
        https = self.read("nginx.conf")
        self.assertRegex(http, r"listen\s+80;")
        self.assertRegex(https, r"listen\s+443\s+ssl;")
        self.assertEqual(http.count("proxy_pass http://127.0.0.1:8000;"), 1)
        self.assertEqual(https.count("proxy_pass http://127.0.0.1:8000;"), 1)
        self.assertNotRegex(http + https, r"return\s+30[18]")
        self.assertIn("/.well-known/acme-challenge/", http)
        self.assertIn(
            "/etc/letsencrypt/live/__PUBLIC_IP__/fullchain.pem",
            https,
        )

    def test_deploy_is_backup_first_and_does_not_rewrite_a_secret_into_unit(self):
        deploy = self.read("deploy.sh")
        self.assertIn(".backup '$BACKUP_DIR/server.db'", deploy)
        self.assertIn("PRAGMA quick_check;", deploy)
        self.assertIn("EnvironmentFile", self.read("album-auth.service"))
        self.assertIn('chmod 640 "$ENV_FILE"', deploy)
        self.assertIn("从旧 service 迁移", deploy)
        self.assertNotIn("sed -i 's|ALBUM_SERVER_SECRET", deploy)
        self.assertIn("trap rollback ERR", deploy)
        self.assertIn("me_status", deploy)
        self.assertIn("product_status", deploy)

    def test_daily_backup_schedule_points_to_the_deployed_script(self):
        cron = self.read("album-auth-backup.cron")
        self.assertIn("/opt/album-auth/server/deploy/backup.sh", cron)
        self.assertNotIn("/opt/album-auth/deploy/backup.sh", cron)
        # Keep the installed cron byte-compatible; this legacy environment
        # variable is ignored by the non-pruning backup script.
        self.assertIn("ALBUM_BACKUP_RETENTION_DAYS=7", cron)
        self.assertNotIn("RETENTION_DAYS", self.read("backup.sh"))
        self.assertNotIn("-delete", self.read("backup.sh"))
        self.assertIn("PRAGMA quick_check;", self.read("backup.sh"))

    def test_failed_deploy_verifies_code_rollback_without_restoring_business_data(self):
        deployer = (ROOT / "deploy_auth.py").read_text(encoding="utf-8")
        self.assertNotIn("rsync -a --delete --", deployer)
        self.assertIn("readlink -f", deployer)
        self.assertIn("production_health", deployer)
        self.assertIn("自动回滚执行失败，需要按备份人工恢复", deployer)
        self.assertIn("自动回滚后的健康检查失败", deployer)

    def test_ip_certificate_flow_is_staged_short_lived_and_auto_reloaded(self):
        https = self.read("enable-https-ip.sh")
        for required in (
            "--staging",
            "--preferred-profile shortlived",
            "--webroot",
            "--ip-address",
            "snap.certbot.renew.timer",
            "renewal-hooks/deploy",
            "renew --dry-run --cert-name",
        ):
            self.assertIn(required, https)
        self.assertRegex(https, re.compile(r"parts\s*<\s*\(5, 4\)"))
        self.assertIn('http_status="$(curl', https)
        self.assertIn('https_status="$(curl', https)
        self.assertIn("HTTP_CHANGED=1", https)
        self.assertIn("HTTPS_CHANGED=1", https)
        self.assertIn("nginx-http-with-acme.conf", https)
        self.assertIn("album-auth-ip-https", https)

    def test_acme_injection_preserves_existing_memory_and_update_routes(self):
        helper_path = DEPLOY / "inject_acme_location.py"
        spec = importlib.util.spec_from_file_location("inject_acme_location", helper_path)
        self.assertIsNotNone(spec)
        module = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(module)
        original = """server {
    listen 80;
    server_name api.example.invalid;
    location /memory/ { proxy_pass http://127.0.0.1:5199/; }
    location /update/ { alias /opt/album-auth/data/updates/; }
    location / { proxy_pass http://127.0.0.1:8000; }
}
"""
        rendered = module.inject_acme_location(original)
        self.assertIn("/.well-known/acme-challenge/", rendered)
        self.assertIn("location /memory/", rendered)
        self.assertIn("proxy_pass http://127.0.0.1:5199/", rendered)
        self.assertIn("location /update/", rendered)
        self.assertIn("alias /opt/album-auth/data/updates/", rendered)
        self.assertIn("proxy_pass http://127.0.0.1:8000", rendered)
        self.assertEqual(module.inject_acme_location(rendered), rendered)

    def test_manual_rollback_does_not_swap_business_directories_or_install_dependencies(self):
        rollback = self.read("rollback.sh")
        self.assertIn('"$HELPER" prepare', rollback)
        self.assertIn('"$HELPER" recover', rollback)
        self.assertIn("check_dependencies.py", rollback)
        self.assertNotIn('"$VENV/bin/pip"', rollback)
        self.assertNotRegex(rollback, r"\bpip\b.*\binstall\b")
        self.assertNotIn('mv "$CODE_DIR"', rollback)
        self.assertNotIn('cp -a "$target_real/server"', rollback)
        self.assertNotRegex(rollback, r"sqlite3.+\.restore")


if __name__ == "__main__":
    unittest.main()
