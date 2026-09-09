# -*- coding: utf-8 -*-
from __future__ import annotations

import importlib
import os
import tempfile
import unittest
from pathlib import Path


class PrintLayoutSourceContractTest(unittest.TestCase):
    def test_visible_print_ui_is_orientation_caption_mode_and_four_layout_choices(self):
        root = Path(__file__).resolve().parents[1]
        html = (root / "templates" / "index.html").read_text(encoding="utf-8")
        print_html = (root / "templates" / "print.html").read_text(encoding="utf-8")
        js_files = sorted((root / "assets").glob("app-A*.js"))
        css_files = sorted((root / "assets").glob("app-A*.css"))
        self.assertEqual(len(js_files), 1)
        self.assertEqual(len(css_files), 1)
        js = js_files[0].read_text(encoding="utf-8")
        css = css_files[0].read_text(encoding="utf-8")

        for marker in (
            'data-print-layout="landscape"',
            'data-print-layout="portrait"',
            'data-print-caption-mode="inline"',
            'data-print-caption-mode="separate"',
            'data-print-style="one"',
            'data-print-style="two"',
            'data-print-style="four"',
            'data-print-style="custom"',
        ):
            self.assertIn(marker, html)
        self.assertNotIn("竖版 · 上下双图", html)
        self.assertNotIn("横版 · 左右双图", html)
        self.assertIn("print-segment-group", css)
        self.assertIn('params.set("caption_mode"', js)
        self.assertIn('auto_fill: "1"', js)
        self.assertIn('caption_mode == "separate"', print_html)
        self.assertIn('class="page caption-sheet"', print_html)
        self.assertIn('caption_mode != "separate" and item.detail_rows', print_html)


class PrintLayoutGeometryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Import lazily and in an isolated data directory; this module is named
        # test_z_* so existing product tests establish their own environment first.
        cls.temp = tempfile.TemporaryDirectory(prefix="album-print-grid-")
        os.environ.setdefault("ALBUM_DATA_DIR", cls.temp.name)
        cls.appmod = importlib.import_module("app")

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    @staticmethod
    def photos(count):
        return [
            {
                "id": f"SYDY{index:03d}",
                "orientation": "landscape",
                "rotation": 0,
                "detail_rows": [
                    {"label": "题名", "value": "测试照片"},
                    {"label": "编号", "value": f"SYDY{index:03d}"},
                    {"label": "施工部位", "value": "测试单元"},
                    {"label": "拍摄时间", "value": "2026-09-09"},
                ],
            }
            for index in range(1, count + 1)
        ]

    def settings(self, caption_mode="inline"):
        return {
            "print_margin_top_mm": 6,
            "print_margin_right_mm": 6,
            "print_margin_bottom_mm": 6,
            "print_margin_left_mm": 6,
            "print_horizontal_gap_mm": 3,
            "print_vertical_gap_mm": 3,
            "print_caption_position": "bottom",
            "print_caption_mode": caption_mode,
            "print_caption_size_mm": 7.5,
            "print_show_page_title": True,
            "print_single_alignment": "center",
            "print_auto_fill": True,
        }

    def assert_inside_page(self, layout, page_size, items, settings):
        paper_w, paper_h = (210.0, 297.0) if layout == "portrait" else (297.0, 210.0)
        page_w = paper_w - settings["print_margin_left_mm"] - settings["print_margin_right_mm"]
        page_h = paper_h - settings["print_margin_top_mm"] - settings["print_margin_bottom_mm"] - 7.0
        for item in items:
            self.assertGreater(item["_photo_w"], 0)
            self.assertGreater(item["_h"], 0)
            self.assertGreaterEqual(item["_left"], -0.2)
            self.assertGreaterEqual(item["_top"], -0.2)
            self.assertLessEqual(item["_left"] + item["_w"], page_w + 0.6)
            self.assertLessEqual(item["_top"] + item["_block_h"], page_h + 0.6)

    def test_layout_preset_does_not_override_independent_paper_direction(self):
        with self.appmod.app.test_request_context("/?style=two&layout=portrait"):
            self.assertEqual(self.appmod.print_layout_from_request(), "portrait")
            self.assertEqual(self.appmod.print_page_size_from_request(), 2)
        with self.appmod.app.test_request_context("/?style=four&layout=landscape"):
            self.assertEqual(self.appmod.print_layout_from_request(), "landscape")
            self.assertEqual(self.appmod.print_page_size_from_request(), 4)

    def test_one_two_four_fit_both_landscape_and_portrait_with_inline_labels(self):
        for layout in ("landscape", "portrait"):
            for page_size in (1, 2, 4):
                settings = self.settings("inline")
                pages = self.appmod.layout_fixed_photo_pages(
                    self.photos(page_size), layout, page_size, 185, 123, settings
                )
                self.assertEqual(len(pages), 1)
                self.assertEqual(len(pages[0]), page_size)
                self.assert_inside_page(layout, page_size, pages[0], settings)
                self.assertTrue(all(item["_caption_h"] > 0 for item in pages[0]))

    def test_separate_caption_mode_gives_the_photo_the_whole_cell(self):
        for layout in ("landscape", "portrait"):
            settings = self.settings("separate")
            pages = self.appmod.layout_fixed_photo_pages(self.photos(2), layout, 2, 185, 123, settings)
            self.assertEqual(len(pages), 1)
            self.assertTrue(all(item["_caption_h"] == 0 for item in pages[0]))
            self.assert_inside_page(layout, 2, pages[0], settings)

    def test_custom_count_is_centered_by_cell_allocator_and_never_overflows(self):
        settings = self.settings("inline")
        pages = self.appmod.layout_fixed_photo_pages(self.photos(5), "portrait", 5, 260, 172, settings)
        self.assertEqual(len(pages), 1)
        self.assertEqual(len(pages[0]), 5)
        self.assert_inside_page("portrait", 5, pages[0], settings)
        # Different slots must occupy different fixed cells rather than piling up at top-left.
        positions = {(item["_left"], item["_top"]) for item in pages[0]}
        self.assertEqual(len(positions), 5)


if __name__ == "__main__":
    unittest.main()
