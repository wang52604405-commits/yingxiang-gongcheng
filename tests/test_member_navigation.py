# -*- coding: utf-8 -*-
from pathlib import Path
import unittest


class DesktopMemberNavigationContractTest(unittest.TestCase):
    def test_desktop_navigation_uses_public_member_pages_only(self):
        root = Path(__file__).resolve().parents[1]
        html = (root / "templates" / "index.html").read_text(encoding="utf-8")
        js_files = sorted((root / "assets").glob("app-A*.js"))
        self.assertEqual(len(js_files), 1)
        js = js_files[0].read_text(encoding="utf-8")

        self.assertIn("https://shuiliyingxiang.cn/member#register", html)
        self.assertIn('target="_blank"', html)
        self.assertIn('rel="noopener noreferrer"', html)
        self.assertNotIn('href="/license?register=1"', html)

        self.assertIn('window.open("https://shuiliyingxiang.cn/member#register", "_blank", "noopener")', js)
        self.assertIn('window.open("https://shuiliyingxiang.cn/member", "_blank", "noopener")', js)
        self.assertNotIn('window.open("/license", "_blank")', js)

    def test_registration_login_and_license_backends_are_unchanged(self):
        root = Path(__file__).resolve().parents[1]
        app = (root / "app.py").read_text(encoding="utf-8")
        # The desktop UI no longer posts registration itself, but the existing
        # backend contracts remain present and untouched for compatibility.
        self.assertIn('@app.route("/api/cloud/register", methods=["POST"])', app)
        self.assertIn('@app.route("/api/cloud/login", methods=["POST"])', app)
        self.assertIn('/api/license/status', app)


if __name__ == "__main__":
    unittest.main()
