"""Website transactions against disposable files with fake ownership/HTTP commands."""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import deploy_website as website


class WebsiteDeployPortableTest(unittest.TestCase):
    def test_remote_allocation_uses_posix_paths_on_every_publisher_host(self):
        script = website.build_allocation_script("/var/tmp/album-site-unique", "/var/backups/shuiliyingxiang/pre-site-unique")
        self.assertIn("mkdir -p -- /var/backups/shuiliyingxiang;", script)
        self.assertNotIn("\\", script)

    def test_deploy_allocates_before_scp_uses_bash_and_packages_only_managed_source(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "source"
            source.mkdir()
            for name in (*website.PAGES, "site-content.json", "assets/style.css", "assets/site.js", "tutorial/" + website.TUTORIAL_NAME, "download/installer.exe", "operator-file"):
                path = source / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"fixture")
            calls = []
            archived = []

            def remote(command):
                calls.append(("ssh", command))
                return SimpleNamespace(stdout="exclusive-backup", returncode=0)

            def transfer(command):
                calls.append(("scp", command))
                with tarfile.open(command[-2], "r:gz") as archive:
                    archived.extend(archive.getnames())
                return SimpleNamespace(stdout="", returncode=0)

            with patch.object(website, "SITE", source), patch.object(website, "SSH_KEY", source / "index.html"), patch.object(website, "validate_site"), patch.object(website, "_published_version", return_value=""), patch.object(website, "_ssh", side_effect=remote), patch.object(website, "_run", side_effect=transfer):
                website.deploy()
            self.assertEqual([kind for kind, _ in calls], ["ssh", "scp", "ssh"])
            self.assertTrue(calls[0][1].startswith("bash -c "))
            self.assertTrue(calls[2][1].startswith("bash -c "))
            self.assertNotIn("operator-file", archived)
            self.assertFalse(any(name == "download" or name.startswith("download/") for name in archived))
            self.assertIn("tutorial/" + website.TUTORIAL_NAME, archived)
            self.assertIn("/payload.tar.gz", calls[1][1][-1])


@unittest.skipIf(os.name == "nt" or not shutil.which("bash"), "requires local POSIX Bash")
class WebsiteDeploySafetyTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.root = self.base / "宣传网站 public"
        self.stage = self.base / "exclusive-stage"
        self.backup = self.base / "backups/exclusive-backup"
        self.source = self.base / "source"
        self.commands = self.base / "mock-commands"
        self.root.mkdir()
        self.source.mkdir()
        self.commands.mkdir()
        for name in (*website.PAGES, "site-content.json"):
            self.write(self.root / name, b"old " + name.encode())
            self.write(self.source / name, ("四大专业 new " + name).encode())
        self.write(self.root / "assets/style.css", b"old style")
        self.write(self.root / "assets/site.js", b"old script")
        self.write(self.root / "assets/untracked/nested-font.bin", b"old untracked asset")
        self.write(self.source / "assets/style.css", b"new style")
        self.write(self.source / "assets/site.js", b"new script")
        self.write(self.root / "tutorial/nested/unknown.docx", b"untracked nested tutorial")
        self.write(self.root / "tutorial/.private-note", b"original hidden tutorial content")
        self.write(self.root / "tutorial" / website.TUTORIAL_NAME, b"old public tutorial")
        self.write(self.root / "download" / website.TUTORIAL_NAME, b"old download tutorial")
        self.write(self.source / "tutorial" / website.TUTORIAL_NAME, b"new official tutorial")
        self.write(self.root / "download" / website.INSTALLER_NAME, b"published installer must not change")
        self.write(self.root / "download/operator-file", b"unknown download must stay")
        self.write(self.root / "unknown/nested-user-file", b"unknown public content must stay")
        self.before = self.bytes(self.root)
        self.write(self.commands / "chown", b"#!/bin/sh\nexit 0\n")
        self.write(self.commands / "curl", "#!/bin/sh\nif [ \"${FAIL_HEALTH:-0}\" = 1 ]; then exit 22; fi\nwhile [ \"$#\" -gt 0 ]; do if [ \"$1\" = --output ]; then shift; output=$1; fi; shift; done\nprintf '四大专业' > \"$output\"\n".encode())
        real_cp = shutil.which("cp")
        self.write(self.commands / "cp", (
            "#!/bin/sh\nfor value do destination=$value; done\n"
            "if [ \"${FAIL_COPY_DEST:-}\" = \"$destination\" ] && [ ! -e \"$FAIL_MARKER\" ]; then\n"
            "printf failed > \"$FAIL_MARKER\"; exit 73\nfi\n"
            f"exec '{real_cp}' \"$@\"\n"
        ).encode())
        for command in self.commands.iterdir():
            command.chmod(0o700)
        self.environment = {**os.environ, "PATH": str(self.commands) + os.pathsep + os.environ["PATH"], "FAIL_MARKER": str(self.base / "copy-failed-once")}
        allocation = website.build_allocation_script(str(self.stage), str(self.backup))
        subprocess.run(["bash", "-c", allocation], check=True, env=self.environment)
        self.archive = self.stage / "payload.tar.gz"
        with tarfile.open(self.archive, "w:gz") as archive:
            for item in self.source.iterdir():
                archive.add(item, arcname=item.name)

    @staticmethod
    def write(path: Path, content: bytes):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)

    @staticmethod
    def bytes(root: Path):
        return {path.relative_to(root).as_posix(): path.read_bytes() for path in root.rglob("*") if path.is_file()}

    def publish(self, **environment):
        script = website.build_remote_script(str(self.stage), str(self.backup), str(self.archive), str(self.root))
        return subprocess.run(["bash", "-c", script], env={**self.environment, **environment}, capture_output=True, text=True, encoding="utf-8", timeout=20)

    def assert_unmanaged_unchanged(self):
        for relative in (f"download/{website.INSTALLER_NAME}", "download/operator-file", "unknown/nested-user-file"):
            self.assertEqual((self.root / relative).read_bytes(), self.before[relative])

    def test_success_retains_complete_tutorials_assets_and_untracked_content(self):
        result = self.publish()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.root / "tutorial").exists())
        self.assertEqual((self.root / "download" / website.TUTORIAL_NAME).read_bytes(), b"new official tutorial")
        self.assertEqual((self.backup / "original/tutorial/nested/unknown.docx").read_bytes(), b"untracked nested tutorial")
        self.assertEqual((self.backup / "displaced/tutorial/.private-note").read_bytes(), b"original hidden tutorial content")
        self.assertEqual((self.backup / "original/download-tutorial").read_bytes(), b"old download tutorial")
        self.assertEqual((self.backup / "displaced/download-tutorial").read_bytes(), b"old download tutorial")
        self.assertEqual((self.backup / "original/assets/untracked/nested-font.bin").read_bytes(), b"old untracked asset")
        self.assertEqual((self.backup / "displaced/assets/untracked/nested-font.bin").read_bytes(), b"old untracked asset")
        self.assertTrue((self.backup / "snapshot-ready").is_file())
        self.assertTrue(self.archive.is_file())
        self.assert_unmanaged_unchanged()

    def test_health_failure_restores_every_old_byte_and_retains_failed_content(self):
        result = self.publish(FAIL_HEALTH="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("previous managed content restored", result.stderr)
        self.assertEqual(self.bytes(self.root), self.before)
        self.assertEqual((self.backup / "failed/download-tutorial").read_bytes(), b"new official tutorial")
        self.assertEqual((self.backup / "failed/assets/style.css").read_bytes(), b"new style")
        self.assertEqual((self.backup / "displaced/tutorial/nested/unknown.docx").read_bytes(), b"untracked nested tutorial")
        self.assert_unmanaged_unchanged()

    def test_partial_copy_failure_restores_old_content_without_deleting_any_evidence(self):
        result = self.publish(FAIL_COPY_DEST=str(self.root / "assets"))
        self.assertEqual(result.returncode, 73, result.stderr)
        self.assertEqual(self.bytes(self.root), self.before)
        self.assertTrue((self.backup / "failed/index.html").is_file())
        self.assertTrue((self.backup / "original/tutorial/.private-note").is_file())
        self.assert_unmanaged_unchanged()

    def test_previously_absent_paths_are_retired_to_failed_evidence_on_rollback(self):
        for name in ("contact.html", "tutorial"):
            path = self.root / name
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()
        (self.root / "download" / website.TUTORIAL_NAME).unlink()
        before = self.bytes(self.root)
        result = self.publish(FAIL_HEALTH="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.bytes(self.root), before)
        self.assertTrue((self.backup / "failed/contact.html").is_file())
        self.assertTrue((self.backup / "failed/download-tutorial").is_file())

    def test_backup_failure_stops_before_any_public_content_changes(self):
        result = self.publish(FAIL_COPY_DEST=str(self.backup / "original/tutorial"))
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.bytes(self.root), self.before)
        self.assertFalse((self.backup / "snapshot-ready").exists())
        self.assertEqual(list((self.backup / "displaced").iterdir()), [])

    def test_existing_stage_or_backup_is_never_reused_or_overwritten(self):
        self.write(self.backup / "operator-evidence", b"keep backup")
        allocation = website.build_allocation_script(str(self.stage), str(self.backup))
        result = subprocess.run(["bash", "-c", allocation], env=self.environment, capture_output=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((self.backup / "operator-evidence").read_bytes(), b"keep backup")
        second_stage = self.base / "another-stage"
        allocation = website.build_allocation_script(str(second_stage), str(self.backup))
        result = subprocess.run(["bash", "-c", allocation], env=self.environment, capture_output=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((self.backup / "operator-evidence").read_bytes(), b"keep backup")

    def test_symlinked_old_tutorial_is_retained_without_touching_its_target(self):
        shutil.rmtree(self.root / "tutorial")
        external = self.base / "external-originals"
        self.write(external / "photo.jpg", b"external original must not change")
        (self.root / "tutorial").symlink_to(external, target_is_directory=True)
        result = self.publish()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.backup / "original/tutorial").is_symlink())
        self.assertTrue((self.backup / "displaced/tutorial").is_symlink())
        self.assertEqual((external / "photo.jpg").read_bytes(), b"external original must not change")


if __name__ == "__main__":
    unittest.main()
