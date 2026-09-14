from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "templates" / "index.html"
APP = ROOT / "app.py"
TEST = ROOT / "tests" / "test_process_photo_transfer.py"
WORKFLOW = ROOT / ".github" / "workflows" / "chatgpt-process-photo-transfer-20260914.yml"
SELF = Path(__file__).resolve()


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected exactly one match, got {count}: {old[:120]!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def patch_frontend() -> None:
    html = TEMPLATE.read_text(encoding="utf-8")
    match = re.search(r'<script\s+defer\s+src="/assets/(app-A[^"]+\.js)"></script>', html)
    if not match:
        raise RuntimeError("cannot locate versioned desktop JS asset from templates/index.html")
    js_path = ROOT / "assets" / match.group(1)
    if not js_path.is_file():
        raise RuntimeError(f"desktop JS asset does not exist: {js_path}")

    replace_once(
        js_path,
        '      state.moveTargets = (data.projects || []).filter((project) => projectCode(project) && projectCode(project) !== state.selectedCode);',
        '''      const allTargets = (data.projects || []).filter((project) => projectCode(project));
      state.moveTargets = [
        ...allTargets.filter((project) => projectCode(project) === state.selectedCode),
        ...allTargets.filter((project) => projectCode(project) !== state.selectedCode)
      ];''',
    )
    replace_once(
        js_path,
        '''      const targetProcess = $("#photoMoveProcessSelect")?.value || "";
      if (!targetCode) return showNotice("请选择目标单元。", true);''',
        '''      const targetProcess = $("#photoMoveProcessSelect")?.value || "";
      const sourceProcess = String(photo.process_name || "").trim();
      if (!targetCode) return showNotice("请选择目标单元。", true);
      if (targetCode === sourceCode && targetProcess === sourceProcess) {
        return showNotice("照片已经在当前工序，无需移动。", true);
      }''',
    )

    replace_once(TEMPLATE, 'id="movePhotoBtn">移动到其它单元</button>', 'id="movePhotoBtn">移动到工序/单元</button>')
    replace_once(TEMPLATE, '<h3 id="photoMoveTitle">移动照片到其它单元</h3>', '<h3 id="photoMoveTitle">移动照片到工序或其它单元</h3>')
    replace_once(
        TEMPLATE,
        '<p>永久照片 UUID、题名、日期和原图备份都会保留；目标单元会按自身规则重新编号。</p>',
        '<p>同一单元可在工序之间直接传递；跨单元移动时永久照片 UUID、题名、日期和原图备份都会保留，并按目标单元规则重新编号。</p>',
    )
    replace_once(TEMPLATE, '<label>搜索目标单元<input id="photoMoveSearchInput"', '<label>搜索单元<input id="photoMoveSearchInput"')


def patch_backend() -> None:
    text = APP.read_text(encoding="utf-8")
    anchor = '''            self._renumber_after_change(data["project_code"], data)
            return data

    def move_photo(self, source_project_code, photo_id, target_project_code, category="", target_process_name=""):
'''
    if text.count(anchor) != 1:
        raise RuntimeError(f"app.py: manager insertion anchor count is {text.count(anchor)}")
    method = '''            self._renumber_after_change(data["project_code"], data)
            return data

    def delete_process(self, project_code, process_name):
        """删除空工序，并清理文件已不存在的历史残留照片记录。"""
        name = str(process_name or "").strip()
        if not name:
            raise ValueError("工序名称不能为空")
        with self._project_write_lock(project_code):
            data = self.get_project(project_code)
            processes = [
                str(item or "").strip()
                for item in (data.get("processes") or [])
                if str(item or "").strip()
            ]
            if name not in processes:
                raise LookupError("工序不存在")

            photos_dir = self._photos_dir(project_code)
            kept = []
            blockers = []
            stale_removed = 0
            for photo in list(data.get("photos") or []):
                if str(photo.get("process_name") or "").strip() != name:
                    kept.append(photo)
                    continue
                filename = Path(str(photo.get("filename") or "")).name
                if filename and (photos_dir / filename).is_file():
                    kept.append(photo)
                    blockers.append(photo)
                else:
                    # 文件已经被删掉时，这条 metadata 只是历史残留；不能继续阻塞工序删除。
                    stale_removed += 1

            if stale_removed:
                data["photos"] = kept

            if blockers:
                if stale_removed:
                    self._renumber_after_change(project_code, data)
                category_counts = {"施工": 0, "监理": 0}
                for photo in blockers:
                    label = "监理" if self._normalize_category(photo.get("category")) == "supervision" else "施工"
                    category_counts[label] += 1
                detail = "，".join(
                    f"{label}{count}张" for label, count in category_counts.items() if count
                )
                raise ValueError(f"工序「{name}」下还有照片（{detail}），请先移走或删除后再删除工序")

            processes.remove(name)
            data["processes"] = processes
            self._renumber_after_change(project_code, data)
            return data, stale_removed

    def move_photo(self, source_project_code, photo_id, target_project_code, category="", target_process_name=""):
'''
    text = text.replace(anchor, method, 1)

    route_pattern = re.compile(
        r'@app\.route\("/api/photos/<path:project_code>/processes/<path:process_name>", methods=\["DELETE"\]\)\n'
        r'def api_delete_process\(project_code, process_name\):.*?'
        r'(?=\n\n\n@app\.route\("/api/photos/<path:project_code>/<photo_id>/move", methods=\["POST"\]\))',
        re.S,
    )
    replacement = '''@app.route("/api/photos/<path:project_code>/processes/<path:process_name>", methods=["DELETE"])
def api_delete_process(project_code, process_name):
    """删除空工序；自动清理文件已不存在、但仍残留在 metadata 中的照片记录。"""
    user, error = login_required_json()
    if error:
        return error
    try:
        data, stale_removed = manager.delete_process(project_code, process_name)
        return jsonify({
            "ok": True,
            "processes": data["processes"],
            "photos": manager.get_photos(project_code),
            "stale_removed": stale_removed,
        })
    except LookupError as exc:
        return json_error(str(exc), 404)
    except ValueError as exc:
        return json_error(str(exc), 400)
    except Exception as exc:
        return json_error(str(exc), 500)
'''
    text, count = route_pattern.subn(replacement, text, count=1)
    if count != 1:
        raise RuntimeError(f"app.py: delete-process route replacement count is {count}")
    text = text.replace(
        '    """跨单元移动照片；保留永久 UUID、题名、日期、原图备份和拍摄信息。"""',
        '    """跨单元或同一单元工序间移动照片；保留永久 UUID、题名、日期、原图备份和拍摄信息。"""',
        1,
    )
    APP.write_text(text, encoding="utf-8")


def write_tests() -> None:
    TEST.write_text(
        '''# -*- coding: utf-8 -*-
from __future__ import annotations

import io
import re
import tempfile
import unittest
import urllib.parse
from pathlib import Path
from unittest.mock import patch

from PIL import Image
from werkzeug.datastructures import FileStorage


class ProcessPhotoTransferTest(unittest.TestCase):
    def setUp(self):
        import app as desktop_app

        self.desktop = desktop_app
        self.temp = tempfile.TemporaryDirectory(prefix="album-process-transfer-")
        self.manager = desktop_app.AlbumManager(Path(self.temp.name))
        self.manager_patch = patch.object(desktop_app, "manager", self.manager)
        self.match_patch = patch.object(desktop_app, "project_matches_engineering", return_value=True)
        self.manager_patch.start()
        self.match_patch.start()
        self.project_code = "PROC-MOVE-001"
        self.manager._write_metadata(
            self.project_code,
            {
                "project_code": self.project_code,
                "display_project_code": self.project_code,
                "project_name": "工序照片移动测试单元",
                "engineering_project_id": "test-project",
                "processes": ["钢筋安装", "混凝土浇筑"],
                "photos": [],
                "source_fields": {},
            },
        )
        self.client = desktop_app.app.test_client()
        with self.client.session_transaction() as session:
            session["username"] = "工序测试员"

    def tearDown(self):
        self.match_patch.stop()
        self.manager_patch.stop()
        self.temp.cleanup()

    @staticmethod
    def jpg_file(name: str) -> FileStorage:
        memory = io.BytesIO()
        Image.new("RGB", (96, 72), (36, 108, 126)).save(memory, "JPEG", quality=90)
        memory.seek(0)
        return FileStorage(stream=memory, filename=name, content_type="image/jpeg")

    def test_same_unit_photo_can_move_between_processes(self):
        added = self.manager.add_photos(
            self.project_code,
            [self.jpg_file("process-a.jpg")],
            category="construction",
            photo_date="2026-09-14",
            process_name="钢筋安装",
        )[0]
        original_uuid = added["photo_uuid"]
        moved = self.manager.move_photo(
            self.project_code,
            added["id"],
            self.project_code,
            category="construction",
            target_process_name="混凝土浇筑",
        )
        self.assertEqual(moved["photo_uuid"], original_uuid)
        self.assertEqual(moved["process_name"], "混凝土浇筑")
        self.assertEqual(moved["process_code"], "GY002")
        photos = self.manager.get_photos(self.project_code)
        self.assertEqual(len(photos), 1)
        self.assertEqual(photos[0]["process_name"], "混凝土浇筑")

    def test_delete_process_prunes_stale_deleted_photo_metadata(self):
        added = self.manager.add_photos(
            self.project_code,
            [self.jpg_file("stale.jpg")],
            category="construction",
            photo_date="2026-09-14",
            process_name="钢筋安装",
        )[0]
        data = self.manager.get_project(self.project_code)
        photo = next(item for item in data["photos"] if item["photo_uuid"] == added["photo_uuid"])
        photo_path = self.manager._photos_dir(self.project_code) / photo["filename"]
        photo_path.unlink()
        thumb = self.manager._photos_dir(self.project_code) / self.manager._thumb_filename(photo["filename"])
        thumb.unlink(missing_ok=True)

        encoded = urllib.parse.quote("钢筋安装", safe="")
        response = self.client.delete(f"/api/photos/{self.project_code}/processes/{encoded}")
        self.assertEqual(response.status_code, 200, response.get_json())
        payload = response.get_json()
        self.assertEqual(payload["stale_removed"], 1)
        self.assertNotIn("钢筋安装", payload["processes"])
        self.assertEqual(self.manager.get_project(self.project_code)["photos"], [])

    def test_real_remaining_photo_still_blocks_process_delete_with_category_count(self):
        self.manager.add_photos(
            self.project_code,
            [self.jpg_file("real.jpg")],
            category="supervision",
            photo_date="2026-09-14",
            process_name="钢筋安装",
        )
        encoded = urllib.parse.quote("钢筋安装", safe="")
        response = self.client.delete(f"/api/photos/{self.project_code}/processes/{encoded}")
        self.assertEqual(response.status_code, 400, response.get_json())
        self.assertIn("监理1张", response.get_json()["error"])
        self.assertIn("钢筋安装", self.manager.get_project(self.project_code)["processes"])

    def test_desktop_move_dialog_exposes_current_unit_for_process_transfer(self):
        root = Path(__file__).resolve().parents[1]
        html = (root / "templates" / "index.html").read_text(encoding="utf-8")
        asset = re.search(r'<script\\s+defer\\s+src="/assets/(app-A[^"]+\\.js)"></script>', html)
        self.assertIsNotNone(asset)
        js = (root / "assets" / asset.group(1)).read_text(encoding="utf-8")
        self.assertIn('projectCode(project) === state.selectedCode', js)
        self.assertNotIn('projectCode(project) && projectCode(project) !== state.selectedCode', js)
        self.assertIn('targetCode === sourceCode && targetProcess === sourceProcess', js)
        self.assertIn('移动照片到工序或其它单元', html)
        self.assertIn('id="movePhotoBtn">移动到工序/单元</button>', html)


if __name__ == "__main__":
    unittest.main()
''',
        encoding="utf-8",
    )


def main() -> None:
    patch_frontend()
    patch_backend()
    write_tests()
    # One-shot helper files should not remain in the product branch after they do their job.
    if WORKFLOW.exists():
        WORKFLOW.unlink()
    if SELF.exists():
        SELF.unlink()


if __name__ == "__main__":
    main()
