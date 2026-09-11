from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class DesktopPortalContractTest(unittest.TestCase):
    def test_top_right_website_and_miniprogram_actions_are_present(self):
        html = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
        self.assertIn('id="officialWebsiteBtn"', html)
        self.assertIn('href="https://shuiliyingxiang.cn/"', html)
        self.assertIn('id="miniProgramPortalBtn"', html)
        self.assertIn('id="miniProgramPopover"', html)
        self.assertIn('aria-controls="miniProgramPopover"', html)
        self.assertIn('src="/assets/miniprogram_qr.png"', html)
        self.assertIn("event.key === 'Escape'", html)

    def test_miniprogram_code_asset_is_shipped(self):
        from PIL import Image

        image = ROOT / "assets" / "miniprogram_qr.png"
        self.assertTrue(image.is_file())
        self.assertGreater(image.stat().st_size, 10_000)
        with Image.open(image) as decoded:
            decoded.load()
            self.assertEqual(decoded.size, (430, 430))

        site_image = ROOT / "website" / "assets" / "miniprogram_qr.png"
        self.assertTrue(site_image.is_file())
        with Image.open(site_image) as decoded:
            decoded.load()
            self.assertEqual(decoded.size, (430, 430))

    def test_website_displays_the_same_miniprogram_code_without_cropping(self):
        html = (ROOT / "website" / "index.html").read_text(encoding="utf-8")
        css = (ROOT / "website" / "assets" / "style.css").read_text(encoding="utf-8")
        self.assertIn('src="assets/miniprogram_qr.png"', html)
        self.assertIn("mini-program-site-code", html)
        self.assertIn('href="#mini-program"', html)
        self.assertIn(">微信小程序<", html)
        self.assertIn("object-fit:contain", css)

    def test_lan_login_exposes_a_separate_project_staff_entry(self):
        html = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
        asset = next((ROOT / "assets").glob("app-A*.js")).read_text(encoding="utf-8")
        self.assertIn('id="gateStaffName"', html)
        self.assertIn('id="gateStaffPhone"', html)
        self.assertIn('id="gateStaffEnterBtn"', html)
        self.assertIn("项目人员入口", html)
        self.assertIn('/api/cloud/project-staff-entry', asset)

    def test_top_actions_share_one_style_and_exception_queue_moves_to_sidebar(self):
        html = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
        asset = next((ROOT / "assets").glob("app-A*.js")).read_text(encoding="utf-8")
        self.assertIn('id="batchPrintQuickBtn" class="top-tool-btn"', html)
        self.assertIn('id="actionsMenuBtn" class="top-tool-btn"', html)
        self.assertIn('id="settingsMenuBtn" class="top-settings-btn top-tool-btn"', html)
        self.assertIn('id="unclassifiedQueueBtn" class="side-unclassified-link"', html)
        self.assertNotIn('>待分类影像</a>\n        <button type="button" id="globalUploadBtn"', html)
        self.assertIn('$("#batchPrintQuickBtn")?.addEventListener', asset)
        self.assertIn('node.type === "contract"', asset)

    def test_batch_print_keeps_the_supervision_category_reachable(self):
        """顶栏“批量打印”只带一个类别入口，模态框必须能切到监理。"""
        html = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
        asset = next((ROOT / "assets").glob("app-A*.js")).read_text(encoding="utf-8")

        self.assertIn('id="batchPrintCategoryToggle"', html)
        self.assertIn('data-batch-category="construction"', html)
        self.assertIn('data-batch-category="supervision"', html)
        self.assertIn("syncBatchPrintCategoryButtons", asset)
        # 切到监理后必须重渲染列表，否则选了“监理”却还在打印施工单元。
        self.assertIn("state.batchSelectedUnits = new Set();", asset)

    def test_removed_actions_menu_entries_are_not_bound_again(self):
        """操作菜单里的施工/监理打印已删除；再绑定会抛 TypeError 并中断整个初始化脚本。"""
        html = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
        asset = next((ROOT / "assets").glob("app-A*.js")).read_text(encoding="utf-8")

        self.assertNotIn("menuPrintConstructionBtn", html)
        self.assertNotIn("menuPrintSupervisionBtn", html)
        self.assertNotIn("$('#menuPrintConstructionBtn')", asset)
        self.assertNotIn('$("#menuPrintConstructionBtn")', asset)
        self.assertNotIn('$("#menuPrintSupervisionBtn")', asset)

    def test_every_selector_dereferenced_without_a_guard_exists_in_the_page(self):
        """初始化脚本对不存在的元素直接取属性会抛错，必须逐个对得上。"""
        import re

        html = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
        asset = next((ROOT / "assets").glob("app-A*.js")).read_text(encoding="utf-8")
        present = set(re.findall(r'id="([A-Za-z0-9_-]+)"', html))

        guarded = set()
        for match in re.finditer(r'\$\("#([A-Za-z0-9_-]+)"\)\.([A-Za-z_]+)', asset):
            missing = match.group(1)
            if missing in present:
                continue
            line_start = asset.rfind("\n", 0, match.start()) + 1
            line_end = asset.find("\n", match.start())
            source_line = asset[line_start:line_end]
            if "?." in source_line:
                continue
            if f'if ($("#{missing}"))' in source_line:
                continue
            guarded.add(missing)

        # 这些元素只在与后端返回的开关联动时才解引用，页面里本来就不该有。
        allowed = {
            "packageFile",
            "packageFileLabel",
            "unitImageActiveTitle",
            "unitImageActiveWrap",
            "unitImageEntrances",
            "updateDevActions",
            "updateRetryActions",
            "uploadModalDetailBtn",
        }
        self.assertEqual(guarded - allowed, set())


if __name__ == "__main__":
    unittest.main()
