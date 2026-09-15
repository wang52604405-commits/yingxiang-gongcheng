# -*- coding: utf-8 -*-
"""服务器部署材料的静态安全/兼容契约。无需连接生产服务器。"""

from __future__ import annotations

import re
import importlib.util
import tarfile
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import deploy_auth


ROOT = Path(__file__).resolve().parents[1]
DEPLOY = ROOT / "server" / "deploy"


class ServerDeployContractTest(unittest.TestCase):
    def read(self, name: str) -> str:
        return (DEPLOY / name).read_text(encoding="utf-8")

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
        preflight_end = deployer.index("def production_health", preflight_start)
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

    def test_deploy_prunes_old_snapshots_and_never_touches_daily_backups(self):
        deployer = (ROOT / "deploy_auth.py").read_text(encoding="utf-8")
        self.assertIn("BACKUP_RETAIN_COUNT = 2", deployer)

        empty = SimpleNamespace(returncode=0, stdout="prune_done\n", stderr="")
        with patch.object(deploy_auth, "ssh", return_value=empty) as remote:
            deploy_auth.prune_remote_snapshots()
        script = remote.call_args[0][0]

        self.assertIn(
            "for root in /opt/album-auth/backups /opt/album-auth/releases", script
        )
        self.assertIn("-name 'deploy-*'", script)
        # 每日数据库备份目录不在清理范围内。
        self.assertNotIn("backups/database", script)

    def test_prune_remote_snapshots_reports_only_removed_deploy_dirs(self):
        output = SimpleNamespace(
            returncode=0,
            stdout=(
                "已清理 /opt/album-auth/backups/deploy-20260809-005530\n"
                "prune_done\n"
            ),
            stderr="",
        )
        with patch.object(deploy_auth, "ssh", return_value=output) as remote:
            removed = deploy_auth.prune_remote_snapshots()

        self.assertEqual(
            removed, ["已清理 /opt/album-auth/backups/deploy-20260809-005530"]
        )
        script = remote.call_args[0][0]
        self.assertIn("head -n -2", script)
        self.assertNotIn("backups/database", script)

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

    def test_prune_and_space_guard_run_after_the_wechat_preflight(self):
        deployer = (ROOT / "deploy_auth.py").read_text(encoding="utf-8")
        preflight_call = deployer.index("    require_mobile_environment()")
        prune_call = deployer.index("= prune_remote_snapshots()")
        guard_call = deployer.index("free_kb = require_free_space()")
        first_remote_write = deployer.index('    ssh(f"mkdir -p')

        self.assertLess(preflight_call, prune_call)
        self.assertLess(prune_call, guard_call)
        self.assertLess(guard_call, first_remote_write)

    def test_github_deploy_checks_the_whole_push_for_server_changes(self):
        workflow = (ROOT / ".github" / "workflows" / "deploy.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("github.event.before", workflow)
        self.assertIn("$env:GITHUB_SHA", workflow)
        self.assertIn("deploy_auth\\.py", workflow)
        self.assertIn("\\.github/workflows/deploy\\.yml", workflow)
        self.assertIn("[IO.File]::AppendAllText", workflow)
        self.assertIn("[Text.UTF8Encoding]::new($false)", workflow)
        self.assertNotIn("git diff --name-only HEAD^ HEAD", workflow)

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
        self.assertTrue(all(not name.startswith(("/", "..")) for name in archived))

        deployer = (ROOT / "deploy_auth.py").read_text(encoding="utf-8")
        self.assertIn("sha256sum -c -", deployer)
        self.assertIn("ServerAliveInterval=10", deployer)
        self.assertIn("timeout=120", deployer)
        self.assertIn("attempts: int = 3", deployer)

    def test_scp_file_retries_a_transient_disconnect(self):
        failed = SimpleNamespace(returncode=1, stdout="", stderr="lost connection")
        passed = SimpleNamespace(returncode=0, stdout="", stderr="")
        with patch.object(
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
        self.assertIn("ALBUM_BACKUP_RETENTION_DAYS=7", cron)
        self.assertIn("PRAGMA quick_check;", self.read("backup.sh"))

    def test_failed_deploy_has_verified_exact_tree_rollback(self):
        deployer = (ROOT / "deploy_auth.py").read_text(encoding="utf-8")
        self.assertIn("rsync -a --delete --", deployer)
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

    def test_manual_rollback_never_silently_reverts_the_database(self):
        rollback = self.read("rollback.sh")
        self.assertIn('"$root_real"/deploy-*', rollback)
        self.assertIn("py_compile", rollback)
        self.assertIn("数据库未回退", rollback)
        self.assertNotRegex(rollback, r"sqlite3.+\.restore")


if __name__ == "__main__":
    unittest.main()
