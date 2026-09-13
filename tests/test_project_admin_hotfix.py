# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


class ProjectAdminHotfixTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="album-project-admin-hotfix-")
        os.environ["ALBUM_DATA_DIR"] = cls.temp.name
        os.environ["ALBUM_TRIAL_FILE"] = str(Path(cls.temp.name) / "trial.json")
        os.environ["ALBUM_LICENSE_FILE"] = str(Path(cls.temp.name) / "license.dat")
        import app as desktop_app
        cls.desktop = desktop_app
        cls.client = desktop_app.app.test_client()

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_admin_entry_has_full_write_access(self):
        ownership = {
            "state": "matched",
            "local_project_id": "owner-local-project",
            "project_ref": "42:owner-local-project",
        }
        verified = {
            "ok": True,
            "project": {
                "project_ref": "42:owner-local-project",
                "project_name": "Shared Project",
            },
            "member": {"display_name": "Admin User", "role": "admin"},
        }
        with patch.object(
            self.desktop, "current_project_cloud_ownership", return_value=ownership
        ), patch.object(
            self.desktop.licensing, "machine_id", return_value="ARCHIVE-PC"
        ), patch.object(
            self.desktop.cloud_client,
            "desktop_verify_project_member",
            return_value=verified,
        ):
            entered = self.client.post(
                "/api/cloud/project-staff-entry",
                json={"display_name": "Admin User", "phone": "13800138001"},
            )
        self.assertEqual(entered.status_code, 200, entered.get_json())
        self.assertEqual(entered.get_json()["user"]["role"], "project_admin")
        writable = self.client.post(
            "/api/engineering-settings",
            json={"settings": {"print_page_size": 4}},
        )
        self.assertEqual(writable.status_code, 200, writable.get_json())


if __name__ == "__main__":
    unittest.main()
