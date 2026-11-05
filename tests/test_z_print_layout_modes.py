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
            'data-print-style="sidelabel"',
            'data-print-style="one"',
            'data-print-style="two"',
            'data-print-style="four"',
            'data-print-style="custom"',
            "侧签 · 两行",
        ):
            self.assertIn(marker, html)
        self.assertIn('data-print-style="sidelabel"', html)
        self.assertIn('selectPrintStyle("sidelabel")', js)
        self.assertIn("照片号", print_html)
        self.assertIn("修筑", print_html)
        self.assertIn("拍摄时间", print_html)
        self.assertIn("摄影者", print_html)
        self.assertIn("地点", print_html)
        self.assertIn('class="side-row"', print_html)
        self.assertIn("grid-template-columns: {{ side_photo_w }}mm {{ side_slip_w }}mm;", print_html)
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

    def test_side_label_is_portrait_two_up_with_paper_slip_fields(self):
        with self.appmod.app.test_request_context("/?style=sidelabel&layout=landscape&page_size=4"):
            self.assertEqual(self.appmod.print_layout_from_request(), "portrait")
            self.assertEqual(self.appmod.print_page_size_from_request(), 2)
            settings = self.appmod.print_settings_from_request()
        self.assertEqual(settings["print_style"], "sidelabel")
        self.assertFalse(settings["print_show_page_title"])

        photos = self.photos(3)
        photos[0].update({
            "id": "UNIT-SY080",
            "title": "阀门井",
            "photo_date": "2023-11-03",
            "photographer": "姜伟",
            "description": "",
            "process_name": "",
            "orientation": "landscape",
            "url": "/photos/sample.jpg",
        })
        photos[1].update({
            "id": "UNIT-SY008",
            "title": "浇筑",
            "process_name": "混凝土",
            "photo_date": "2025-03-30",
            "url": "/photos/sample-2.jpg",
        })
        pages = self.appmod.layout_side_label_pages(photos, {"location": "北陈村"})
        self.assertEqual(len(pages), 2)
        self.assertEqual([len(page) for page in pages], [2, 1])
        first, second = pages[0]
        metrics = self.appmod.side_label_metrics()
        self.assertAlmostEqual(first["_photo_w"] / first["_caption_w"], 2.0, delta=0.02)
        self.assertAlmostEqual(first["_photo_w"], metrics["photo_w"])
        self.assertAlmostEqual(first["_caption_w"], metrics["slip_w"])
        self.assertEqual(first["_h"], first["_caption_h"])
        self.assertLess(first["_h"], first["_photo_w"])
        self.assertEqual(first["_top"], second["_top"] - first["_block_h"] - metrics["row_gap_mm"])
        self.assertLess(first["_top"] + first["_block_h"], second["_top"])
        self.assertLessEqual(first["_w"], metrics["page_w"] + 0.05)
        self.assertEqual(first["_side_label"]["photo_no"], "80")
        self.assertEqual(first["_side_label"]["description"], "阀门井")
        self.assertEqual(first["_side_label"]["construction"], "")
        self.assertEqual(first["_side_label"]["shot_at"], "2023.11.3")
        self.assertEqual(first["_side_label"]["photographer"], "姜伟")
        self.assertEqual(first["_side_label"]["place"], "北陈村")
        self.assertEqual(second["_side_label"]["photo_no"], "8")
        self.assertEqual(second["_side_label"]["construction"], "混凝土")
        self.assertEqual(second["_side_label"]["shot_at"], "2025.3.30")

        with self.appmod.app.test_request_context("/?style=sidelabel"):
            rendered = self.appmod.render_template(
                "print.html",
                project={"project_code": "P", "project_name": "工程", "code": "P", "name": "工程"},
                photos=photos,
                project_groups=[{"level": "", "pages": [
                    {"unit_name": "单元", "items": pages[0], "print_page_number": 1},
                    {"unit_name": "单元", "items": pages[1], "print_page_number": 2},
                ]}],
                category="construction",
                category_label="施工单元影像",
                print_layout="portrait",
                print_page_size=2,
                print_settings=settings,
                watermark_text="",
            )
        self.assertIn("size: A4 portrait", rendered)
        self.assertEqual(rendered.count('class="side-row"'), 3)
        for field in ("照片号", "说明", "修筑", "拍摄时间", "摄影者", "地点"):
            self.assertIn(field, rendered)
        self.assertIn("阀门井", rendered)
        self.assertIn("2023.11.3", rendered)
        self.assertIn("姜伟", rendered)
        self.assertIn("北陈村", rendered)
        self.assertIn("slip-build-lines", rendered)
        self.assertIn(f'{metrics["photo_w"]}mm {metrics["slip_w"]}mm', rendered)
        self.assertNotIn("装订边25mm", rendered)


if __name__ == "__main__":
    unittest.main()
