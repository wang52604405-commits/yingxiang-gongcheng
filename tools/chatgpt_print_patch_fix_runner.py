# -*- coding: utf-8 -*-
from pathlib import Path
import subprocess
import sys

path = Path("tools/chatgpt_print_patch_20260909.py")
text = path.read_text(encoding="utf-8")
old_end = "}\n\n\ndef print_layout_from_request'''"
new_end = "}'''"
if old_end not in text:
    raise SystemExit("style replacement terminator not found")
text = text.replace(old_end, new_end, 1)
old_call = '''    r'PRINT_STYLE_DEFAULTS = \\{.*?\\n\\}\\n\\n\\ndef print_layout_from_request',
    style_defaults,
    "print style defaults",
)'''
new_call = '''    r'PRINT_STYLE_DEFAULTS = \\{.*?\\n\\}\\n\\n\\ndef print_settings_from_request',
    style_defaults + "\\n\\n\\ndef print_settings_from_request",
    "print style defaults",
)'''
if old_call not in text:
    raise SystemExit("style regex call not found")
text = text.replace(old_call, new_call, 1)
path.write_text(text, encoding="utf-8")
subprocess.run([sys.executable, str(path)], check=True)

# Paper direction is independent of the 1/2/4 layout preset. New presets deliberately
# do not bake in a direction, so request parsing must tolerate a style without one.
app_path = Path("app.py")
app_text = app_path.read_text(encoding="utf-8")
old_layout = '''    default_layout = (
        style_defaults["print_layout"]
        if style_defaults
        else read_engineering_settings().get("print_layout", "landscape")
    )
'''
new_layout = '''    saved_layout = read_engineering_settings().get("print_layout", "landscape")
    default_layout = (
        style_defaults.get("print_layout", saved_layout)
        if style_defaults
        else saved_layout
    )
'''
if old_layout not in app_text:
    raise SystemExit("print_layout_from_request contract not found")
app_text = app_text.replace(old_layout, new_layout, 1)
app_path.write_text(app_text, encoding="utf-8")

# Two older regression assertions intentionally described the superseded print UX.
# Update only those contracts: the new requirement is a fixed A4 grid whose captions
# stay inside each cell, and exactly four visible layout choices.
test_path = Path("tests/test_product_core.py")
test = test_path.read_text(encoding="utf-8")
old_ui = '''        self.assertEqual(html.count('class="print-style-schematic"'), 6)\n        self.assertIn('ps-paper ps-landscape ps-grid4', html)\n        self.assertIn('ps-paper ps-portrait ps-stack2', html)\n        self.assertIn('ps-paper ps-landscape ps-pair2', html)\n'''
new_ui = '''        self.assertEqual(html.count('class="print-style-schematic"'), 4)\n        self.assertIn('data-print-layout="landscape"', html)\n        self.assertIn('data-print-layout="portrait"', html)\n        self.assertIn('data-print-caption-mode="separate"', html)\n        self.assertIn('ps-paper ps-landscape ps-grid4', html)\n        self.assertIn('ps-paper ps-landscape ps-pair2', html)\n        self.assertIn('ps-paper ps-landscape ps-single', html)\n'''
if old_ui not in test:
    raise SystemExit("legacy UX print-card contract not found")
test = test.replace(old_ui, new_ui, 1)
old_geometry = '''        self.assertEqual(len(pages), 2, "说明区不足时应自动分页，不能把文字压进照片")\n        self.assertGreaterEqual(pages[0][0]["_caption_h"], 11.0)\n\n        groups = [\n            {"project_code": "U-1", "project_name": "一号单元", "level": "单元照片", "pages": [pages[0], pages[1]]},\n            {"project_code": "U-2", "project_name": "二号单元", "level": "工序照片", "pages": [[detailed_photo]]},\n        ]\n        numbered = self.desktop.assign_unique_print_page_numbers(groups)\n        all_pages = [page for group in numbered for page in group["pages"]]\n        self.assertEqual([page["print_page_number"] for page in all_pages], [1, 2, 3])\n        self.assertEqual([page["unit_page_number"] for page in all_pages], [1, 2, 1])\n'''
new_geometry = '''        self.assertEqual(len(pages), 1, "四宫格必须固定留在同一张 A4 内，标签只能压缩照片可用区，不能把下一张挤出页面")\n        self.assertEqual(len(pages[0]), 4)\n        self.assertGreaterEqual(pages[0][0]["_caption_h"], 7.5)\n        for item in pages[0]:\n            self.assertLessEqual(item["_top"] + item["_block_h"], 195.5)\n\n        groups = [\n            {"project_code": "U-1", "project_name": "一号单元", "level": "单元照片", "pages": [pages[0]]},\n            {"project_code": "U-2", "project_name": "二号单元", "level": "工序照片", "pages": [[detailed_photo]]},\n        ]\n        numbered = self.desktop.assign_unique_print_page_numbers(groups)\n        all_pages = [page for group in numbered for page in group["pages"]]\n        self.assertEqual([page["print_page_number"] for page in all_pages], [1, 2])\n        self.assertEqual([page["unit_page_number"] for page in all_pages], [1, 1])\n'''
if old_geometry not in test:
    raise SystemExit("legacy caption-overflow contract not found")
test = test.replace(old_geometry, new_geometry, 1)
test_path.write_text(test, encoding="utf-8")

# Extend the generated print-specific suite with request-layer direction checks.
ztest_path = Path("tests/test_z_print_layout_modes.py")
ztest = ztest_path.read_text(encoding="utf-8")
anchor = '''    def test_one_two_four_fit_both_landscape_and_portrait_with_inline_labels(self):\n'''
addition = '''    def test_layout_preset_does_not_override_independent_paper_direction(self):
        with self.appmod.app.test_request_context("/?style=two&layout=portrait"):
            self.assertEqual(self.appmod.print_layout_from_request(), "portrait")
            self.assertEqual(self.appmod.print_page_size_from_request(), 2)
        with self.appmod.app.test_request_context("/?style=four&layout=landscape"):
            self.assertEqual(self.appmod.print_layout_from_request(), "landscape")
            self.assertEqual(self.appmod.print_page_size_from_request(), 4)

'''
if anchor not in ztest:
    raise SystemExit("print-specific test insertion anchor not found")
ztest = ztest.replace(anchor, addition + anchor, 1)
ztest_path.write_text(ztest, encoding="utf-8")
