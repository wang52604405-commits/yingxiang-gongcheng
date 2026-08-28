# -*- coding: utf-8 -*-
from __future__ import annotations

import hashlib
import json
import os
import runpy
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEPLOY_SCRIPT = ROOT / "server" / "deploy" / "deploy-staging.sh"
STAGING_UNIT = ROOT / "server" / "deploy" / "album-auth-staging.service"
VALIDATOR = ROOT / "validate_mobile_migration.py"
REQUIREMENTS = ROOT / "server" / "requirements.txt"
PRODUCTION_DEPLOY = ROOT / "deploy_auth.py"
STAGING_E2E = ROOT / "tests" / "run_mobile_staging_e2e.py"


def utf8_environment() -> dict[str, str]:
    environment = dict(os.environ)
    environment["PYTHONUTF8"] = "1"
    environment["PYTHONIOENCODING"] = "utf-8"
    return environment


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class StagingIsolationTests(unittest.TestCase):
    def test_systemd_unit_uses_dedicated_identity_fixed_paths_and_sandbox(self):
        unit = STAGING_UNIT.read_text(encoding="utf-8")
        self.assertIn("User=album-auth-staging", unit)
        self.assertIn("Group=album-auth-staging", unit)
        self.assertNotIn("User=www-data", unit)
        self.assertIn("ExecStartPre=/usr/bin/bash", unit)
        exec_start = next(line for line in unit.splitlines() if line.startswith("ExecStart="))
        self.assertTrue(exec_start.startswith("ExecStart=/usr/bin/env "))
        for assignment in (
            "ALBUM_SERVER_ENVIRONMENT=staging",
            "ALBUM_SERVER_INSTANCE_ID=album-auth-staging",
            "ALBUM_SERVER_DATA=/var/lib/album-auth-staging",
            "ALBUM_SERVER_DB=/var/lib/album-auth-staging/staging.db",
            "ALBUM_SERVER_PRIVATE_KEY=/etc/album-auth-staging/private_key.pem",
            "ALBUM_MOBILE_STORAGE_DIR=/var/lib/album-auth-staging/mobile_objects",
            "ALBUM_MOBILE_CHUNK_DIR=/var/lib/album-auth-staging/mobile_chunks",
        ):
            self.assertIn(assignment, exec_start)
        self.assertIn('Environment="ALBUM_SERVER_ENVIRONMENT=staging"', unit)
        self.assertIn('Environment="ALBUM_SERVER_INSTANCE_ID=album-auth-staging"', unit)
        for directive in (
            "NoNewPrivileges=true",
            "ProtectSystem=strict",
            "ProtectHome=true",
            "ProtectProc=invisible",
            "CapabilityBoundingSet=",
            "InaccessiblePaths=-/opt/album-auth -/etc/album-auth -/var/lib/album-auth",
            "ReadOnlyPaths=/opt/album-auth-staging /etc/album-auth-staging",
            "ReadWritePaths=/var/lib/album-auth-staging",
            "UMask=0027",
        ):
            self.assertIn(directive, unit)

    def test_e2e_refuses_unverified_writes_and_unsafe_project_paths(self):
        module = runpy.run_path(str(STAGING_E2E))
        api = module["Api"]("http://127.0.0.1:18080")
        with self.assertRaisesRegex(module["E2EFailure"], "拒绝发送写请求"):
            api.request("POST", "/api/register", json={})

        self.assertEqual(module["safe_internal_project_code"]("YNLQ-2024_01"), "YNLQ-2024_01")
        for unsafe in ("../production", "a/b", "a\\b", ".", "name.", "工程"):
            with self.assertRaises(module["E2EFailure"]):
                module["safe_internal_project_code"](unsafe)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "inside"
            root.mkdir()
            with self.assertRaisesRegex(module["E2EFailure"], "越出"):
                module["resolve_contained"](root, "..", "outside")

        source = STAGING_E2E.read_text(encoding="utf-8")
        self.assertIn("api.verify_isolated_staging()", source)
        self.assertIn("cloud_client._desktop_download_bytes_with_context", source)
        self.assertIn('mobile_token = second_login["token"]', source)

    def test_deploy_script_contains_fail_closed_linux_guards(self):
        script = DEPLOY_SCRIPT.read_text(encoding="utf-8")
        for required in (
            "SERVICE_USER=album-auth-staging",
            "部署锁权限必须为 root:root 600",
            "set -o noclobber",
            "flock -n 9",
            "reject_symlink_if_present",
            "reject_hardlink_if_present",
            "assert_tree_has_no_links \"$SRC_DIR\"",
            "部署源码必须位于 staging 安装目录之外",
            "DropInPaths",
            "FragmentPath",
            "staging unit 存在硬链接",
            "staging unit 与正式 unit 指向同一 inode",
            "findmnt",
            "source_path=\"${BASH_REMATCH[1]}\"",
            "mktemp \"$BACKUP_DIR/staging-",
            "chmod 600 \"$backup_path\"",
            "ca-certificates curl openssl python3-venv rsync sqlite3 util-linux",
            "openssl genpkey -algorithm Ed25519",
            "mobile_chunks",
            "-m py_compile \"${python_modules[@]}\"",
            "systemd-analyze verify",
            "staging-policy.env",
            "STAGING_WECHAT_APP_ID",
            "PRODUCTION_WECHAT_APP_ID",
            "STAGING_OSS_ORIGINAL_BUCKET",
            "STAGING_OSS_PREVIEW_BUCKET",
            "PRODUCTION_OSS_BUCKETS",
            "assert_safe_database_if_present",
            "staging.db 属主必须为 $SERVICE_USER:$SERVICE_GROUP",
            "staging.db 不得允许组/其它用户写入",
            "runtime-check 必须以独立 staging 用户运行",
            "runtime-check 进程不得继承 www-data 组",
            "staging 源码目录残留 data/ 内容；请先人工隔离，脚本不会删除",
            "chmod g+rX,o-rwx",
        ):
            self.assertIn(required, script)
        self.assertNotIn("systemctl restart album-auth\n", script)
        requirements = REQUIREMENTS.read_text(encoding="utf-8")
        self.assertIn("gunicorn>=25.1,<27", requirements)

    def test_production_deployer_passes_private_validation_copy_root(self):
        deployer = PRODUCTION_DEPLOY.read_text(encoding="utf-8")
        self.assertIn('validation_root = f"{release_root}/migration-validation"', deployer)
        self.assertIn('ssh(f"install -d -m 0700 {backup} {backup}/server")', deployer)
        self.assertIn('ssh(f"install -d -m 0700 {validation_root}")', deployer)
        self.assertIn('f"--copy-root {validation_root} "', deployer)
        self.assertIn("os.umask(0o077)", deployer)
        self.assertIn("os.chmod(target, 0o600)", deployer)
        self.assertNotIn('validation_copy = f"{release_root}/migration-validation.sqlite3"', deployer)

    def _embedded_env_validator(self) -> str:
        script = DEPLOY_SCRIPT.read_text(encoding="utf-8")
        marker = "python3 - \"$SERVER_ENV\" \"$MOBILE_ENV\" \"$POLICY_ENV\" <<'PY'\n"
        self.assertIn(marker, script)
        return script.split(marker, 1)[1].split("\nPY\n", 1)[0]

    def _run_env_validator(
        self,
        directory: Path,
        mobile: str | None,
        policy: str = (
            "STAGING_WECHAT_APP_ID=\n"
            "PRODUCTION_WECHAT_APP_ID=\n"
            "STAGING_OSS_ORIGINAL_BUCKET=\n"
            "STAGING_OSS_PREVIEW_BUCKET=\n"
            "PRODUCTION_OSS_BUCKETS=\n"
        ),
    ) -> subprocess.CompletedProcess[str]:
        server = directory / "server.env"
        mobile_path = directory / "mobile.env"
        policy_path = directory / "staging-policy.env"
        server.write_text("ALBUM_SERVER_SECRET=" + "a" * 64 + "\n", encoding="utf-8")
        if mobile is not None:
            mobile_path.write_text(mobile, encoding="utf-8")
        policy_path.write_text(policy, encoding="utf-8")
        return subprocess.run(
            [
                sys.executable,
                "-c",
                self._embedded_env_validator(),
                str(server),
                str(mobile_path),
                str(policy_path),
            ],
            cwd=ROOT,
            env=utf8_environment(),
            capture_output=True,
            text=True,
            encoding="utf-8",
        )

    def test_environment_validator_rejects_path_appid_and_bucket_escape(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            valid = self._run_env_validator(directory, None)
            self.assertEqual(valid.returncode, 0, valid.stderr)

            forbidden_path = self._run_env_validator(
                directory,
                "ALBUM_SERVER_DB=/opt/album-auth/data/server.db\n",
            )
            self.assertNotEqual(forbidden_path.returncode, 0)
            self.assertIn("不允许变量", forbidden_path.stderr)

            unpinned_app = self._run_env_validator(
                directory,
                "ALBUM_WECHAT_APP_ID=wxabcdef123456\nALBUM_WECHAT_MOCK_ENABLED=1\n",
            )
            self.assertNotEqual(unpinned_app.returncode, 0)
            self.assertIn("未被 staging-policy.env 精确批准", unpinned_app.stderr)

            production_app = self._run_env_validator(
                directory,
                "ALBUM_WECHAT_APP_ID=wxabcdef123456\nALBUM_WECHAT_MOCK_ENABLED=1\n",
                (
                    "STAGING_WECHAT_APP_ID=wxabcdef123456\n"
                    "PRODUCTION_WECHAT_APP_ID=wxabcdef123456\n"
                    "STAGING_OSS_ORIGINAL_BUCKET=\n"
                    "STAGING_OSS_PREVIEW_BUCKET=\n"
                    "PRODUCTION_OSS_BUCKETS=\n"
                ),
            )
            self.assertNotEqual(production_app.returncode, 0)
            self.assertIn("与正式 AppID 相同", production_app.stderr)

            production_named_buckets = self._run_env_validator(
                directory,
                (
                    "ALBUM_MOBILE_STORAGE_BACKEND=oss\n"
                    "ALBUM_OSS_REGION=cn-beijing\n"
                    "ALBUM_OSS_ORIGINAL_BUCKET=engineering-original\n"
                    "ALBUM_OSS_PREVIEW_BUCKET=engineering-preview\n"
                ),
                (
                    "STAGING_WECHAT_APP_ID=\n"
                    "PRODUCTION_WECHAT_APP_ID=\n"
                    "STAGING_OSS_ORIGINAL_BUCKET=engineering-original\n"
                    "STAGING_OSS_PREVIEW_BUCKET=engineering-preview\n"
                    "PRODUCTION_OSS_BUCKETS=engineering-production-original,engineering-production-preview\n"
                ),
            )
            self.assertNotEqual(production_named_buckets.returncode, 0)
            self.assertIn("缺少 staging/test 标记", production_named_buckets.stderr)

            approved_staging = self._run_env_validator(
                directory,
                (
                    "ALBUM_WECHAT_APP_ID=wxabcdef123456\n"
                    "ALBUM_WECHAT_MOCK_ENABLED=1\n"
                    "ALBUM_MOBILE_STORAGE_BACKEND=oss\n"
                    "ALBUM_OSS_REGION=cn-beijing\n"
                    "ALBUM_OSS_ENDPOINT=https://oss-cn-beijing.aliyuncs.com\n"
                    "ALBUM_OSS_ORIGINAL_BUCKET=engineering-staging-original\n"
                    "ALBUM_OSS_PREVIEW_BUCKET=engineering-staging-preview\n"
                ),
                (
                    "STAGING_WECHAT_APP_ID=wxabcdef123456\n"
                    "PRODUCTION_WECHAT_APP_ID=wxproduction12345\n"
                    "STAGING_OSS_ORIGINAL_BUCKET=engineering-staging-original\n"
                    "STAGING_OSS_PREVIEW_BUCKET=engineering-staging-preview\n"
                    "PRODUCTION_OSS_BUCKETS=engineering-production-original,engineering-production-preview\n"
                ),
            )
            self.assertEqual(approved_staging.returncode, 0, approved_staging.stderr)

            production_bucket = self._run_env_validator(
                directory,
                (
                    "ALBUM_MOBILE_STORAGE_BACKEND=oss\n"
                    "ALBUM_OSS_ORIGINAL_BUCKET=engineering-staging-original\n"
                    "ALBUM_OSS_PREVIEW_BUCKET=engineering-staging-preview\n"
                ),
                (
                    "STAGING_WECHAT_APP_ID=\n"
                    "PRODUCTION_WECHAT_APP_ID=\n"
                    "STAGING_OSS_ORIGINAL_BUCKET=engineering-staging-original\n"
                    "STAGING_OSS_PREVIEW_BUCKET=engineering-staging-preview\n"
                    "PRODUCTION_OSS_BUCKETS=engineering-staging-original,engineering-production-preview\n"
                ),
            )
            self.assertNotEqual(production_bucket.returncode, 0)
            self.assertIn("与正式 Bucket 相同", production_bucket.stderr)

    def _create_source_database(self, source: Path) -> None:
        environment = utf8_environment()
        environment.update(
            {
                "ALBUM_SERVER_SECRET": "b" * 64,
                "ALBUM_SERVER_DATA": str(source.parent),
                "ALBUM_SERVER_DB": str(source),
                "ALBUM_SERVER_PRIVATE_KEY": str(source.parent / "unused-key.pem"),
            }
        )
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "import os; os.umask(0o077); from server import db; db.init_db()",
            ],
            cwd=ROOT,
            env=environment,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_validator_uses_exclusive_copy_root_and_never_writes_secret(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source_root = root / "stable-backup"
            copy_root = root / "validation-root"
            destination_parent = copy_root / "run-1"
            source_root.mkdir()
            copy_root.mkdir()
            destination_parent.mkdir()
            if os.name != "nt":
                source_root.chmod(0o700)
                copy_root.chmod(0o700)
                destination_parent.chmod(0o700)
            source = source_root / "backup.sqlite3"
            destination = destination_parent / "migration.sqlite3"
            self._create_source_database(source)
            source_hash = file_sha256(source)
            sentinel = destination_parent / ".server_secret"
            sentinel.write_text("do-not-touch", encoding="ascii")
            sentinel_hash = file_sha256(sentinel)

            result = subprocess.run(
                [
                    sys.executable,
                    str(VALIDATOR),
                    "--source",
                    str(source),
                    "--copy",
                    str(destination),
                    "--copy-root",
                    str(copy_root),
                    "--expected-accounts",
                    "0",
                ],
                cwd=ROOT,
                env=utf8_environment(),
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertTrue(payload["ok"])
            self.assertIn("project_members", payload["mobile_tables"])
            self.assertIn("project_invitations", payload["mobile_tables"])
            self.assertEqual(
                payload["shared_project_invariants"],
                {
                    "projects": 0,
                    "owner_members": 0,
                    "projects_without_owner": 0,
                    "invalid_project_owner_ids": 0,
                },
            )
            self.assertEqual(payload["source_sha256"], source_hash)
            self.assertEqual(file_sha256(source), source_hash)
            self.assertEqual(file_sha256(sentinel), sentinel_hash)
            self.assertTrue(destination.is_file())
            if os.name != "nt":
                self.assertEqual(destination.stat().st_mode & 0o777, 0o600)

            before = destination.read_bytes()
            repeated = subprocess.run(
                [
                    sys.executable,
                    str(VALIDATOR),
                    "--source",
                    str(source),
                    "--copy",
                    str(destination),
                    "--copy-root",
                    str(copy_root),
                ],
                cwd=ROOT,
                env=utf8_environment(),
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            self.assertNotEqual(repeated.returncode, 0)
            self.assertEqual(destination.read_bytes(), before)

    def test_validator_requires_copy_root_and_rejects_escape(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source_root = root / "source"
            copy_root = root / "allowed"
            source_root.mkdir()
            copy_root.mkdir()
            if os.name != "nt":
                source_root.chmod(0o700)
                copy_root.chmod(0o700)
            source = source_root / "backup.sqlite3"
            self._create_source_database(source)

            missing_root = subprocess.run(
                [
                    sys.executable,
                    str(VALIDATOR),
                    "--source",
                    str(source),
                    "--copy",
                    str(root / "missing-root.sqlite3"),
                ],
                cwd=ROOT,
                env=utf8_environment(),
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            self.assertNotEqual(missing_root.returncode, 0)
            self.assertIn("--copy-root", missing_root.stderr)

            escaped = subprocess.run(
                [
                    sys.executable,
                    str(VALIDATOR),
                    "--source",
                    str(source),
                    "--copy",
                    str(root / "outside.sqlite3"),
                    "--copy-root",
                    str(copy_root),
                ],
                cwd=ROOT,
                env=utf8_environment(),
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            self.assertNotEqual(escaped.returncode, 0)
            self.assertIn("必须严格位于", escaped.stderr)
            self.assertFalse((root / "outside.sqlite3").exists())

    def test_validator_rejects_hardlinked_source_backup(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source_root = root / "source"
            copy_root = root / "allowed"
            source_root.mkdir()
            copy_root.mkdir()
            if os.name != "nt":
                source_root.chmod(0o700)
                copy_root.chmod(0o700)
            source = source_root / "backup.sqlite3"
            linked_source = source_root / "linked-backup.sqlite3"
            destination = copy_root / "migration.sqlite3"
            self._create_source_database(source)
            try:
                os.link(source, linked_source)
            except OSError as exc:  # pragma: no cover - filesystem capability
                self.skipTest(f"当前文件系统不支持硬链接：{exc}")
            result = subprocess.run(
                [
                    sys.executable,
                    str(VALIDATOR),
                    "--source",
                    str(linked_source),
                    "--copy",
                    str(destination),
                    "--copy-root",
                    str(copy_root),
                ],
                cwd=ROOT,
                env=utf8_environment(),
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("硬链接", result.stderr)
            self.assertFalse(destination.exists())


if __name__ == "__main__":
    unittest.main()
