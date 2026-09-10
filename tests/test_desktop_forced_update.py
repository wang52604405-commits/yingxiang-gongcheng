# -*- coding: utf-8 -*-
"""桌面端强制自动更新的后台状态机、前端契约与安装边界测试。"""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch


class _FakeResponse(io.BytesIO):
    def __init__(self, payload: bytes, *, status=200, headers=None):
        super().__init__(payload)
        self.status = status
        self.headers = headers or {}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.close()
        return False


class DesktopForcedUpdateTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="album-forced-update-")
        os.environ.setdefault("ALBUM_DATA_DIR", cls.temp.name)
        os.environ.setdefault("ALBUM_TRIAL_FILE", str(Path(cls.temp.name) / "trial.json"))
        os.environ.setdefault("ALBUM_LICENSE_FILE", str(Path(cls.temp.name) / "license.dat"))
        import app as desktop_app

        cls.desktop = desktop_app

    def manager(self, root: Path):
        return self.desktop.DesktopUpdateManager(root / "status.json")

    def manifest(self, payload=b"verified installer"):
        return {
            "version": "A20991231-9.99",
            "url": "https://api.shuiliyingxiang.cn/update/album-installer.exe",
            "sha256": hashlib.sha256(payload).hexdigest(),
            "size": len(payload),
        }

    def test_manifest_requires_https_size_and_sha256(self):
        valid = {
            "ok": True,
            "has_update": True,
            "latest_version": "A20991231-9.99",
            "download_url": "https://api.shuiliyingxiang.cn/update/album-installer.exe",
            "sha256": "a" * 64,
            "size": 123,
        }
        normalized = self.desktop.DesktopUpdateManager._validate_manifest(valid)
        self.assertEqual(normalized["size"], 123)
        for changes in (
            {"download_url": "http://example.invalid/update.exe"},
            {"sha256": ""},
            {"size": 0},
        ):
            invalid = {**valid, **changes}
            with self.assertRaises(self.desktop.DesktopUpdateError):
                self.desktop.DesktopUpdateManager._validate_manifest(invalid)

    def test_start_is_immediate_and_idempotent_while_active(self):
        with tempfile.TemporaryDirectory(prefix="album-update-state-") as temp_dir:
            manager = self.manager(Path(temp_dir))
            fake_thread = MagicMock()
            with patch.object(self.desktop.threading, "Thread", return_value=fake_thread) as thread_cls:
                first = manager.start()
                second = manager.start()
            self.assertTrue(first["started"])
            self.assertFalse(second["started"])
            self.assertEqual(first["job_id"], second["job_id"])
            self.assertEqual(thread_cls.call_count, 1)
            fake_thread.start.assert_called_once_with()
            persisted = json.loads((Path(temp_dir) / "status.json").read_text(encoding="utf-8"))
            self.assertEqual(persisted["state"], "checking")

    def test_fresh_process_recovers_interrupted_download_and_expires_install(self):
        now = int(self.desktop.time.time() * 1000)
        with tempfile.TemporaryDirectory(prefix="album-update-recovery-") as temp_dir:
            root = Path(temp_dir)
            status_path = root / "status.json"
            base = {
                "job_id": "old-job",
                "mandatory": True,
                "current_version": self.desktop.cloud_client.APP_VERSION,
                "latest_version": "A20991231-9.99",
                "downloaded_bytes": 50,
                "total_bytes": 100,
                "percent": 50,
                "message": "",
                "error": "",
                "retryable": False,
            }
            status_path.write_text(json.dumps({**base, "state": "downloading", "updated_at": now}), encoding="utf-8")
            interrupted = self.desktop.DesktopUpdateManager(status_path).public_status()
            self.assertEqual(interrupted["state"], "failed")
            self.assertTrue(interrupted["retryable"])

            status_path.write_text(json.dumps({**base, "state": "installing", "updated_at": now}), encoding="utf-8")
            recent_install = self.desktop.DesktopUpdateManager(status_path).public_status()
            self.assertEqual(recent_install["state"], "installing")

            status_path.write_text(
                json.dumps({
                    **base,
                    "state": "installing",
                    "updated_at": now - self.desktop.UPDATE_INSTALL_STALE_MS - 1,
                }),
                encoding="utf-8",
            )
            expired_install = self.desktop.DesktopUpdateManager(status_path).public_status()
            self.assertEqual(expired_install["state"], "failed")
            self.assertTrue(expired_install["retryable"])

    def test_new_binary_does_not_inherit_old_version_active_state(self):
        with tempfile.TemporaryDirectory(prefix="album-update-version-reset-") as temp_dir:
            status_path = Path(temp_dir) / "status.json"
            status_path.write_text(
                json.dumps({
                    "state": "installing",
                    "job_id": "old-job",
                    "current_version": "A20260101-1.1",
                    "latest_version": self.desktop.cloud_client.APP_VERSION,
                    "total_bytes": 100,
                    "updated_at": int(self.desktop.time.time() * 1000),
                }),
                encoding="utf-8",
            )
            status = self.desktop.DesktopUpdateManager(status_path).public_status()
            self.assertEqual(status["state"], "installed")
            self.assertEqual(status["current_version"], self.desktop.cloud_client.APP_VERSION)

    def test_download_resumes_in_temp_and_verifies_size_and_sha(self):
        payload = b"0123456789" * 2048
        manifest = self.manifest(payload)
        with tempfile.TemporaryDirectory(prefix="album-update-download-") as temp_dir:
            root = Path(temp_dir)
            manager = self.manager(root)
            manager._status.update({"job_id": "job", "state": "downloading"})
            manager.worker = MagicMock()
            manager.worker.is_alive.return_value = True
            update_dir = root / "工程影像管理平台更新"
            update_dir.mkdir()
            partial = update_dir / f"album-update-{manifest['sha256'][:16]}.exe.part"
            split = 4096
            partial.write_bytes(payload[:split])
            response = _FakeResponse(
                payload[split:],
                status=206,
                headers={"Content-Range": f"bytes {split}-{len(payload) - 1}/{len(payload)}"},
            )
            with patch.object(self.desktop.tempfile, "gettempdir", return_value=temp_dir), patch.object(
                self.desktop.tls_compat, "secure_urlopen", return_value=response
            ) as urlopen:
                target = manager._download_package("job", manifest)
            self.assertEqual(target.read_bytes(), payload)
            self.assertTrue(str(target).startswith(str(root.resolve())))
            request_obj = urlopen.call_args.args[0]
            self.assertEqual(request_obj.get_header("Range"), f"bytes={split}-")
            status = manager.public_status()
            self.assertEqual(status["state"], "verifying")
            self.assertEqual(status["downloaded_bytes"], len(payload))
            self.assertNotIn("url", status)
            self.assertNotIn("path", json.dumps(status, ensure_ascii=False).lower())

    def test_bad_hash_is_deleted_and_retryable_failure_is_public(self):
        payload = b"B" * 32
        expected = b"A" * 32
        manifest = self.manifest(expected)
        with tempfile.TemporaryDirectory(prefix="album-update-bad-hash-") as temp_dir:
            manager = self.manager(Path(temp_dir))
            manager._status.update({"job_id": "job", "state": "downloading"})
            with patch.object(self.desktop.tempfile, "gettempdir", return_value=temp_dir), patch.object(
                self.desktop.tls_compat,
                "secure_urlopen",
                return_value=_FakeResponse(payload, status=200),
            ):
                with self.assertRaisesRegex(self.desktop.DesktopUpdateError, "完整性校验失败"):
                    manager._download_package("job", manifest)
            leftovers = list((Path(temp_dir) / "工程影像管理平台更新").glob("*.part"))
            self.assertEqual(leftovers, [])

    def test_worker_marks_installing_before_starting_detached_helper(self):
        payload = b"verified installer"
        manifest = self.manifest(payload)
        cloud_manifest = {
            "ok": True,
            "has_update": True,
            "latest_version": manifest["version"],
            "download_url": manifest["url"],
            "sha256": manifest["sha256"],
            "size": manifest["size"],
        }
        with tempfile.TemporaryDirectory(prefix="album-update-worker-") as temp_dir:
            root = Path(temp_dir)
            installer = root / "installer.exe"
            installer.write_bytes(payload)
            manager = self.manager(root)
            manager._status.update({"job_id": "job", "state": "checking"})

            def assert_installing(job_id, checked_manifest, checked_installer):
                self.assertEqual(job_id, "job")
                self.assertEqual(checked_manifest, manifest)
                self.assertEqual(checked_installer, installer)
                self.assertEqual(manager.public_status()["state"], "installing")

            with patch.object(self.desktop.cloud_client, "check_update", return_value=cloud_manifest), patch.object(
                manager, "_download_package", return_value=installer
            ), patch.object(manager, "_launch_installer", side_effect=assert_installing) as launch:
                manager._run("job")
            launch.assert_called_once()
            self.assertEqual(manager.public_status()["state"], "installing")

    def test_worker_failure_exposes_retry_without_internal_details(self):
        cloud_manifest = {
            "ok": True,
            "has_update": True,
            "latest_version": "A20991231-9.99",
            "download_url": "https://api.shuiliyingxiang.cn/update/album-installer.exe",
            "sha256": "a" * 64,
            "size": 123,
        }
        with tempfile.TemporaryDirectory(prefix="album-update-worker-fail-") as temp_dir:
            manager = self.manager(Path(temp_dir))
            manager._status.update({"job_id": "job", "state": "checking"})
            with patch.object(self.desktop.cloud_client, "check_update", return_value=cloud_manifest), patch.object(
                manager,
                "_download_package",
                side_effect=self.desktop.DesktopUpdateError("安装包完整性校验失败，请重新下载"),
            ):
                manager._run("job")
            status = manager.public_status()
            self.assertEqual(status["state"], "failed")
            self.assertTrue(status["retryable"])
            self.assertEqual(status["error"], "安装包完整性校验失败，请重新下载")
            self.assertNotIn(str(Path(temp_dir)), json.dumps(status, ensure_ascii=False))

    def test_install_helper_uses_argument_list_and_exact_process_scope(self):
        payload = b"installer"
        manifest = self.manifest(payload)
        with tempfile.TemporaryDirectory(prefix="album-update-helper-") as temp_dir:
            root = Path(temp_dir)
            powershell = root / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
            powershell.parent.mkdir(parents=True)
            powershell.write_bytes(b"")
            installer = root / "download with spaces.exe"
            installer.write_bytes(payload)
            manager = self.manager(root)
            with patch.dict(os.environ, {"SystemRoot": str(root)}), patch.object(
                self.desktop.subprocess, "Popen"
            ) as popen:
                manager._launch_installer("job123", manifest, installer)
            command = popen.call_args.args[0]
            self.assertIsInstance(command, list)
            self.assertIn(str(installer.resolve()), command)
            self.assertNotIn("shell", popen.call_args.kwargs)
            helper = next(root.glob("album-update-helper-*.ps1")).read_text(encoding="utf-8-sig")
            self.assertIn("ExecutablePath", helper)
            self.assertIn("OrdinalIgnoreCase", helper)
            self.assertIn("album_server.exe", helper)
            self.assertIn("工程影像管理平台.exe", helper)
            self.assertNotIn("taskkill", helper.lower())
            success_path = helper.split("} catch {\n    $publicMessage", 1)[0]
            self.assertIn("Start-Process", success_path)
            self.assertIn("正在打开新版本", success_path)
            self.assertIn("旧程序仍活着", helper)
            self.assertNotIn("'/CLOSEAPPLICATIONS'", helper)

    def test_api_contract_uses_manual_download_for_every_client(self):
        client = self.desktop.app.test_client()
        update = {
            "ok": True,
            "has_update": True,
            "latest_version": "A20991231-9.99",
            "download_url": "https://api.shuiliyingxiang.cn/update/album-installer.exe",
            "sha256": "a" * 64,
            "size": 123,
        }
        with patch.object(self.desktop.cloud_client, "check_update", return_value=update), patch.object(
            self.desktop.sys, "frozen", True, create=True
        ):
            check = client.get("/api/cloud/check-update").get_json()
            apply_response = client.post("/api/cloud/apply-update")
        self.assertFalse(check["mandatory"])
        self.assertFalse(check["auto_update_supported"])
        self.assertTrue(check["manual_update_only"])
        self.assertEqual(check["manual_download_url"], "/api/cloud/download-update")
        self.assertEqual(apply_response.status_code, 410)
        self.assertFalse(apply_response.get_json()["supported"])
        self.assertIn("manual_download_url", apply_response.get_json())

    def test_installed_api_never_starts_background_install(self):
        client = self.desktop.app.test_client()
        manager = MagicMock()
        with patch.object(self.desktop.sys, "frozen", True, create=True), patch.object(
            self.desktop, "desktop_update_manager", return_value=manager
        ):
            response = client.post("/api/cloud/apply-update")
        self.assertEqual(response.status_code, 410)
        self.assertTrue(response.get_json()["manual_update_only"])
        manager.start.assert_not_called()

    def test_tray_check_update_only_opens_the_local_state_machine(self):
        import desktop_launcher

        tray = desktop_launcher.TrayApp.__new__(desktop_launcher.TrayApp)
        tray.data_dir = "D:/test-data"
        tray.local_url = "http://127.0.0.1:5088"
        tray.notify = MagicMock()
        with patch.object(desktop_launcher, "is_port_open", return_value=True), patch.object(
            desktop_launcher, "local_server_version", return_value=desktop_launcher.APP_VERSION
        ), patch.object(desktop_launcher, "open_local_browser") as open_browser, patch.object(
            desktop_launcher, "ensure_server"
        ) as ensure_server, patch.object(desktop_launcher, "fetch_remote_version") as fetch_remote, patch.object(
            desktop_launcher, "download_update"
        ) as legacy_download, patch.object(desktop_launcher, "terminate_stale_server") as terminate:
            tray.check_update()
        open_browser.assert_called_once_with("http://127.0.0.1:5088/?check_update=1")
        ensure_server.assert_not_called()
        fetch_remote.assert_not_called()
        legacy_download.assert_not_called()
        terminate.assert_not_called()

        with patch.object(desktop_launcher, "terminate_stale_server") as legacy_terminate, patch.object(
            desktop_launcher.subprocess, "Popen"
        ) as legacy_popen:
            ok, message = desktop_launcher.download_update(
                "https://example.invalid/update.exe",
                "A20991231-9.99",
            )
        self.assertFalse(ok)
        self.assertIn("软件页面", message)
        legacy_terminate.assert_not_called()
        legacy_popen.assert_not_called()

    def test_launcher_only_terminates_server_from_its_own_directory(self):
        import desktop_launcher

        with tempfile.TemporaryDirectory(prefix="album-launcher-scope-") as temp_dir:
            root = Path(temp_dir)
            own_dir = root / "installed"
            other_dir = root / "other"
            own_dir.mkdir()
            other_dir.mkdir()
            with patch.object(desktop_launcher, "listener_pid", return_value=123), patch.object(
                desktop_launcher, "app_dir", return_value=own_dir
            ), patch.object(
                desktop_launcher, "process_executable_path", return_value=other_dir / desktop_launcher.SERVER_EXE_NAME
            ), patch.object(desktop_launcher.subprocess, "run") as run:
                self.assertFalse(desktop_launcher.terminate_stale_server())
            run.assert_not_called()

            with patch.object(desktop_launcher, "listener_pid", return_value=123), patch.object(
                desktop_launcher, "app_dir", return_value=own_dir
            ), patch.object(
                desktop_launcher, "process_executable_path", return_value=own_dir / desktop_launcher.SERVER_EXE_NAME
            ), patch.object(desktop_launcher, "is_port_open", return_value=False), patch.object(
                desktop_launcher.subprocess, "run"
            ) as run:
                self.assertTrue(desktop_launcher.terminate_stale_server())
            command = run.call_args.args[0]
            self.assertEqual(command, ["taskkill", "/PID", "123", "/F"])
            self.assertNotIn("/T", command)

    def test_frontend_and_release_contracts_are_wired(self):
        root = Path(__file__).resolve().parents[1]
        html = (root / "templates" / "index.html").read_text(encoding="utf-8")
        asset_match = re.search(r'src="/assets/(app-A\d{8}-\d+\.\d+\.js)"', html)
        self.assertIsNotNone(asset_match, "index.html 必须引用带版本指纹的主脚本")
        javascript = (root / "assets" / asset_match.group(1)).read_text(encoding="utf-8")
        publish = (root / "publish_update.py").read_text(encoding="utf-8")
        self.assertIn('id="updateOverlay"', html)
        self.assertIn('id="checkUpdateBtn"', html)
        self.assertIn('id="updateNoticeDot"', html)
        self.assertLess(html.index('id="settingsMenuBtn"'), html.index('data-project-settings-tab="device"'))
        self.assertLess(html.index('data-project-settings-tab="device"'), html.index('id="checkUpdateBtn"'))
        self.assertIn('id="downloadUpdateLink"', html)
        self.assertIn("function setUpdateAvailable", javascript)
        self.assertIn("function renderManualUpdate", javascript)
        self.assertIn('$("#updateTitle").textContent = "发现新版本，建议立即更新"', javascript)
        self.assertIn("renderManualUpdate(data);", javascript)
        self.assertIn('setUpdateAvailable(true)', javascript)
        update_function = javascript[javascript.index("async function checkForUpdate"):javascript.index("async function ensureAuthenticated")]
        self.assertNotIn("confirm(", update_function)
        self.assertNotIn("startMandatoryUpdate", update_function)
        self.assertNotIn("apply-update", update_function)
        self.assertIn('"mandatory": False', publish)
        self.assertIn('"manual_update_only": True', publish)

    def test_install_and_deploy_scripts_never_kill_by_global_name_or_foreign_port(self):
        root = Path(__file__).resolve().parents[1]
        inno = (root / "安装脚本.iss").read_text(encoding="utf-8")
        deploy = (root / "deploy_prod.ps1").read_text(encoding="utf-8")
        legacy_installer = (root / "installer_win10.py").read_text(encoding="utf-8")
        self.assertIn("CloseApplications=no", inno)
        self.assertIn("ALBUM_UPDATE_INSTALL_DIR", inno)
        self.assertIn("ALBUM_UPDATE_OLD_DIR", inno)
        self.assertIn("ExecutablePath", inno)
        self.assertIn("ValueData: \"{code:GetDataDir}\"", inno)
        self.assertIn("RegQueryStringValue(HKCU, 'Software\\工程影像管理平台', 'DataDir'", inno)
        self.assertIn("CachedDataDir: String", inno)
        self.assertIn("if CachedDataDir <> '' then", inno)
        self.assertIn("RegDeleteKeyIncludingSubkeys(", inno)
        self.assertIn("Uninstall\\工程影像管理平台", inno)
        self.assertIn("DeleteFile(ExpandConstant('{app}\\卸载工程影像管理平台.ps1'))", inno)
        self.assertLess(
            inno.index("RegQueryStringValue(HKCU, 'Software\\工程影像管理平台', 'DataDir', CachedDataDir)"),
            inno.index("ShellExec('open', OldUnins"),
        )
        self.assertLess(
            inno.index("RegQueryStringValue(HKCU, 'Software\\工程影像管理平台', 'InstallDir', OldDir)"),
            inno.index("StopInstalledAppProcesses(OldDir)"),
        )
        self.assertIn("CompareText(NormalizeDirectory(OldDir), NormalizeDirectory(ExpandConstant('{app}')))", inno)
        self.assertNotIn("taskkill /IM", inno)
        self.assertEqual(inno.count("Flags: nowait postinstall skipifsilent"), 1)
        self.assertEqual(inno.count("Flags: nowait skipifnotsilent"), 1)
        self.assertIn("Test-IsInstalledAppProcess", deploy)
        self.assertNotIn("Get-Process album_server", deploy)
        self.assertIn("目标安装目录之外的程序占用", deploy)
        self.assertIn("正在退出，等待端口表刷新", deploy)
        self.assertNotIn('PID $listenerPid：无法读取进程信息"\n            throw', deploy)
        self.assertIn("stop_installed_app_processes(target)", legacy_installer)
        self.assertNotIn('ExecutablePath -like "$InstallDir\\*"', legacy_installer)

    def test_inno_embedded_powershell_has_valid_syntax(self):
        root = Path(__file__).resolve().parents[1]
        inno = (root / "安装脚本.iss").read_text(encoding="utf-8-sig")
        start = inno.index("  PS := ")
        end = inno.index("  if not Exec", start)
        literals = re.findall(r"'((?:''|[^'])*)'", inno[start:end])
        powershell_source = "".join(value.replace("''", "'") for value in literals)
        powershell = (
            Path(os.environ.get("SystemRoot") or r"C:\Windows")
            / "System32"
            / "WindowsPowerShell"
            / "v1.0"
            / "powershell.exe"
        )
        environment = os.environ.copy()
        environment["INNO_UPDATE_PS"] = powershell_source
        parser = (
            "$tokens=$null;$errors=$null;"
            "[System.Management.Automation.Language.Parser]::ParseInput("
            "$env:INNO_UPDATE_PS,[ref]$tokens,[ref]$errors)|Out-Null;"
            "if($errors.Count){$errors|ForEach-Object{Write-Error $_.Message};exit 1}"
        )
        result = subprocess.run(
            [str(powershell), "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", parser],
            env=environment,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)


if __name__ == "__main__":
    unittest.main()
