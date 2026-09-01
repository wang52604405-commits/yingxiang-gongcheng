# -*- coding: utf-8 -*-
"""宣传网站的页面、内容、资源和发布边界契约。"""

from __future__ import annotations

import unittest
from pathlib import Path

import deploy_website


ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "website"


class WebsiteContractTest(unittest.TestCase):
    def test_five_pages_and_all_local_assets_are_complete(self):
        deploy_website.validate_site(SITE)

    def test_primary_messages_and_preserved_links(self):
        index = (SITE / "index.html").read_text(encoding="utf-8")
        usage = (SITE / "usage.html").read_text(encoding="utf-8")
        download = (SITE / "download.html").read_text(encoding="utf-8")
        contact = (SITE / "contact.html").read_text(encoding="utf-8")

        self.assertIn("四大专业工程影像，一套系统管到底", index)
        for text in ("现场拍", "自动归", "快速查", "一键出"):
            self.assertIn(text, index)
        self.assertIn("工程影像管理平台-使用教程.docx", usage + download)
        self.assertIn("/download/工程影像管理平台-安装程序.exe", download)
        self.assertIn("17737397395", contact)
        self.assertIn("544711855@qq.com", contact)

    def test_site_source_never_contains_the_server_download_directory(self):
        self.assertFalse((SITE / "download").exists())


if __name__ == "__main__":
    unittest.main()
