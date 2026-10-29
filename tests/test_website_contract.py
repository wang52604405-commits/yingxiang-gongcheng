# -*- coding: utf-8 -*-
"""宣传网站的页面、内容、资源和发布边界契约。"""

from __future__ import annotations

import unittest
import zipfile
from html.parser import HTMLParser
from pathlib import Path
from xml.etree import ElementTree as ET

import deploy_website


ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "website"
PAGES = ("index.html", "product.html", "usage.html", "download.html", "contact.html")


class _LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.hrefs: list[str] = []
        self.ids: set[str] = set()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if values.get("href"):
            self.hrefs.append(str(values["href"]))
        if values.get("src"):
            self.hrefs.append(str(values["src"]))
        if values.get("id"):
            self.ids.add(str(values["id"]))


class WebsiteContractTest(unittest.TestCase):
    def test_five_pages_and_all_local_assets_are_complete(self):
        deploy_website.validate_site(SITE)

    def test_primary_messages_and_preserved_links(self):
        index = (SITE / "index.html").read_text(encoding="utf-8")
        usage = (SITE / "usage.html").read_text(encoding="utf-8")
        download = (SITE / "download.html").read_text(encoding="utf-8")
        contact = (SITE / "contact.html").read_text(encoding="utf-8")
        pages = index + usage + download + contact

        self.assertIn("现场影像", index)
        self.assertIn("下载 Windows 版", index)
        self.assertIn('class="cta nav-download"', index)
        self.assertIn(">下载<", index)
        self.assertIn("适用于 Windows 10 / 11", index + download)
        self.assertIn("工程影像管理平台-使用教程.docx", usage + download)
        self.assertIn("/download/工程影像管理平台-安装程序.exe", index + download)
        self.assertIn("17737397395", contact)
        self.assertIn("544711855@qq.com", contact)
        self.assertIn("1000", usage + download)
        self.assertIn("https://shuiliyingxiang.cn/member#register", usage)
        self.assertNotIn("300 张", pages)
        self.assertNotIn("自动检查更新", pages)
        self.assertIn("免费 1000 张", index)
        product = (SITE / "product.html").read_text(encoding="utf-8")
        self.assertNotIn("field_", index + product)
        self.assertNotIn("data-tilt", index + product)
        self.assertNotIn('id="aurora"', index + product)
        self.assertIn("ui_main.png", index)
        self.assertIn("四大专业", index)

    def test_internal_links_point_at_real_pages_and_anchors(self):
        parsed = {}
        for name in PAGES:
            parser = _LinkParser()
            parser.feed((SITE / name).read_text(encoding="utf-8"))
            parsed[name] = parser
        for name, parser in parsed.items():
            for raw in parser.hrefs:
                target = raw.split("?", 1)[0]
                if not target or target.startswith(("http://", "https://", "tel:", "mailto:", "/")):
                    continue
                page_name, _, anchor = target.partition("#")
                page_name = page_name or name
                destination = (SITE / page_name).resolve()
                self.assertTrue(destination.is_file(), f"{name} 指向不存在的页面或文件：{raw}")
                if anchor:
                    self.assertIn(anchor, parsed[page_name].ids, f"{name} 的锚点不存在：{raw}")

    def test_tutorial_docx_uses_the_live_product_facts(self):
        tutorial = SITE / "tutorial" / "工程影像管理平台-使用教程.docx"
        with zipfile.ZipFile(tutorial) as bundle:
            root = ET.fromstring(bundle.read("word/document.xml"))
        text = "".join(
            node.text or ""
            for node in root.iter("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t")
        )
        for expected in (
            "1000",
            "39 元",
            "399 元",
            "500",
            "https://shuiliyingxiang.cn/member#register",
            "/license",
            "手动下载",
            "月费会员最多 2 个，终身会员最多 3 个",
            "登录密码",
            "工程删除密码",
        ):
            self.assertIn(expected, text)
        self.assertNotIn("300 张", text)
        self.assertNotIn("自动检查更新", text)

    def test_site_source_never_contains_the_server_download_directory(self):
        self.assertFalse((SITE / "download").exists())


if __name__ == "__main__":
    unittest.main()
