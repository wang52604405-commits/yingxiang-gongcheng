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

    def test_public_registration_hash_opens_registration_and_login_returns_main(self):
        root = Path(__file__).resolve().parents[1]
        page = (root / "server" / "templates" / "member_center.html").read_text(encoding="utf-8")
        self.assertIn('function showAccountPanel(panel, updateHash = true)', page)
        self.assertIn('location.hash === "#register" ? "register"', page)
        self.assertIn('history.replaceState(null, "", location.pathname);', page)
        self.assertIn('window.scrollTo(0, 0);', page)

    def test_member_center_free_plan_shows_one_thousand_photos(self):
        root = Path(__file__).resolve().parents[1]
        page = (root / "server" / "templates" / "member_center.html").read_text(encoding="utf-8")
        self.assertIn('id="freeLimitText">1000</span> 张照片', page)
        self.assertNotIn('id="freeLimitText">300</span>', page)
        self.assertIn("photo_limit || 1000", page)
        self.assertNotIn("photo_limit || 300", page)

    def test_registration_success_opens_the_software_login(self):
        root = Path(__file__).resolve().parents[1]
        pages = [
            (root / "server" / "templates" / "member_center.html").read_text(encoding="utf-8"),
            (root / "server" / "templates" / "cloud.html").read_text(encoding="utf-8"),
        ]
        for page in pages:
            self.assertIn('window.location.assign("http://127.0.0.1:5088/")', page)
            self.assertNotIn("注册成功，用刚才的账号登录即可。", page)

    def test_website_tutorial_covers_desktop_mini_program_and_first_use(self):
        root = Path(__file__).resolve().parents[1]
        page = (root / "website" / "usage.html").read_text(encoding="utf-8")
        for expected in (
            "桌面端 + 微信小程序",
            "新建独立工程",
            "导入项目划分",
            "修改照片编号规则",
            "小程序完整流程",
            "同步与隔离",
            "月费会员最多 2 个，终身会员最多 3 个",
        ):
            self.assertIn(expected, page)


if __name__ == "__main__":
    unittest.main()
