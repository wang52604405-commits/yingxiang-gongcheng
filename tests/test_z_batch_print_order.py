# -*- coding: utf-8 -*-
"""批量打印必须严格按客户勾选顺序出页。

历史 bug：服务端把 units/processes 先转 set 再 sorted()，
页序变成按编码字母排序，客户看到的就是“错页”。
"""
from __future__ import annotations

import importlib
import io
import os
import tempfile
import unittest


class BatchPrintOrderTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="album-batch-order-")
        os.environ.setdefault("ALBUM_DATA_DIR", cls.temp.name)
        cls.appmod = importlib.import_module("app")
        cls.client = cls.appmod.app.test_client()

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    @staticmethod
    def _jpg(name):
        from PIL import Image
        from werkzeug.datastructures import FileStorage

        buffer = io.BytesIO()
        Image.new("RGB", (60, 40), (40, 120, 150)).save(buffer, "JPEG")
        buffer.seek(0)
        return FileStorage(stream=buffer, filename=name, content_type="image/jpeg")

    def _seed(self, code, name):
        manager = self.appmod.manager
        manager.create_project(code, name)
        manager.add_photos(code, [self._jpg(f"{code}.jpg")], category="construction")

    def test_helper_keeps_first_seen_order_and_drops_duplicates(self):
        codes = self.appmod.ordered_unique_codes("C-3, C-1 ,C-2,C-1,, C-3")
        self.assertEqual(codes, ["C-3", "C-1", "C-2"])

    def test_helper_concatenates_multiple_arguments_in_order(self):
        codes = self.appmod.ordered_unique_codes("B,A", "C,B")
        self.assertEqual(codes, ["B", "A", "C"])

    def test_batch_print_follows_selection_order_not_alphabetical(self):
        # 刻意让“勾选顺序”和“字母顺序”完全相反，这样任何排序都会暴露。
        seeded = [("Z-UNIT-3", "三号单元"), ("Z-UNIT-1", "一号单元"), ("Z-UNIT-2", "二号单元")]
        for code, name in seeded:
            self._seed(code, name)

        selection = [code for code, _ in seeded]
        self.assertNotEqual(selection, sorted(selection), "测试数据必须让勾选顺序 != 字母顺序")

        response = self.client.get(
            "/print/construction/batch?units=" + ",".join(selection)
        )
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True)[:400])
        html = response.get_data(as_text=True)

        positions = []
        for code, name in seeded:
            index = html.find(name)
            self.assertGreaterEqual(index, 0, f"打印页里没有出现 {name}")
            positions.append(index)

        self.assertEqual(
            positions, sorted(positions),
            "批量打印页序必须与勾选顺序一致，不能按编码字母排序",
        )

    def test_batch_print_does_not_duplicate_units_listed_twice(self):
        self._seed("DUP-UNIT", "重复单元")
        response = self.client.get(
            "/print/construction/batch?units=DUP-UNIT,DUP-UNIT"
        )
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertEqual(html.count("重复单元"), 1, "同一单元重复勾选不应重复出册")


if __name__ == "__main__":
    unittest.main()
