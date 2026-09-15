from pathlib import Path

path = Path('app.py')
text = path.read_text(encoding='utf-8')

old = '''    THUMB_SUFFIX = "thumb_"\n    THUMB_MAX_SIDE = 480\n    THUMB_QUALITY = 80\n'''
new = '''    THUMB_SUFFIX = "thumb_"\n    THUMB_MAX_SIDE = 480\n    THUMB_QUALITY = 80\n    # v2: 缩略图名保留原图扩展名，并记录源文件签名。显示编号（如 SY001）\n    # 会在删除/重排后被复用，绝不能再把编号文件名当作永久缓存身份。\n    THUMB_CACHE_VERSION = 2\n'''
if old not in text:
    raise SystemExit('thumb constants anchor not found')
text = text.replace(old, new, 1)

start = text.index('    def _thumb_filename(self, filename):\n')
end = text.index('    def _encode_jpeg_to_budget(self, image, target_bytes):\n', start)
replacement = r'''    def _thumb_filename(self, filename):
        # 保留原图扩展名，避免同一显示编号先后使用 JPG/PNG 时共用一个缓存文件。
        # 例：construction-...-SY001.jpg -> thumb_construction-...-SY001.jpg.webp
        name = Path(str(filename)).name
        return f"{self.THUMB_SUFFIX}{name}.webp"

    def _originals_dir(self, project_code):
        """每个单元独立保存永久原图；随工程备份移动，不参与日常列表扫描。"""
        return self._project_dir(project_code) / "_originals"

    def _original_path(self, project_code, filename):
        return self._originals_dir(project_code) / Path(str(filename)).name

    def _find_original(self, project_code, thumb_filename):
        """根据缩略图名反查原图；兼容 v1 不含原图扩展名的旧缩略图名。"""
        name = Path(str(thumb_filename)).name
        if not name.startswith(self.THUMB_SUFFIX):
            return None
        payload = name[len(self.THUMB_SUFFIX):]
        if payload.lower().endswith('.webp'):
            payload = payload[:-5]
        photos_dir = self._photos_dir(project_code)
        # v2 缩略图把原图完整文件名编码在 thumb 名内，可以精确定位，不猜扩展名。
        exact = photos_dir / Path(payload).name
        if exact.suffix.lower() in IMAGE_EXTENSIONS and exact.is_file():
            return exact
        # v1 兼容：thumb_<stem>.webp，只能按 stem 回查已有图片。
        legacy_stem = Path(payload).stem
        candidates = [
            candidate for ext in sorted(IMAGE_EXTENSIONS)
            if (candidate := photos_dir / f"{legacy_stem}{ext}").is_file()
        ]
        # 同 stem 出现多个扩展名时不能猜，避免把 A 照片的缩略图套到 B 照片。
        return candidates[0] if len(candidates) == 1 else None

    def _thumbnail_source_signature(self, original):
        stat = original.stat()
        identity = (
            f"{self.THUMB_CACHE_VERSION}:{original.name}:"
            f"{stat.st_mtime_ns}:{stat.st_size}:{getattr(stat, 'st_ino', 0)}"
        )
        return hashlib.sha256(identity.encode('utf-8')).hexdigest()[:24]

    def _thumbnail_signature_path(self, thumb_path):
        return thumb_path.with_name(thumb_path.name + '.source')

    def _ensure_thumbnail(self, project_code, filename):
        """保证缩略图与当前源文件一致；旧缓存或源文件变化时自动重建。"""
        try:
            from PIL import Image, ImageOps
        except Exception:
            return False

        temp_path = None
        signature_temp = None
        try:
            photos_dir = self._photos_dir(project_code)
            name = Path(str(filename)).name
            if name.startswith(self.THUMB_SUFFIX):
                thumb_name = name
                original = self._find_original(project_code, thumb_name)
            else:
                thumb_name = self._thumb_filename(name)
                original = photos_dir / name
            if original is None or not original.is_file():
                return False
            thumb_path = photos_dir / thumb_name
            signature_path = self._thumbnail_signature_path(thumb_path)
            source_signature = self._thumbnail_source_signature(original)
            if thumb_path.is_file():
                try:
                    if signature_path.read_text(encoding='ascii').strip() == source_signature:
                        return True
                except (OSError, UnicodeError):
                    pass
                # 旧缩略图没有签名，或同编号源文件已被替换：必须重建，不能继续显示旧图。

            with Image.open(original) as img:
                img = ImageOps.exif_transpose(img)
                img.thumbnail((self.THUMB_MAX_SIDE, self.THUMB_MAX_SIDE), Image.LANCZOS)
                if img.mode not in ("RGB", "L"):
                    img = img.convert("RGB")
                thumb_path.parent.mkdir(parents=True, exist_ok=True)
                temp_path = thumb_path.with_name(f".{thumb_path.name}.{uuid.uuid4().hex}.tmp")
                img.save(temp_path, "WEBP", quality=self.THUMB_QUALITY, method=4)
                os.replace(temp_path, thumb_path)
                temp_path = None
            signature_temp = signature_path.with_name(
                f".{signature_path.name}.{uuid.uuid4().hex}.tmp"
            )
            signature_temp.write_text(source_signature, encoding='ascii')
            os.replace(signature_temp, signature_path)
            signature_temp = None
            return True
        except Exception:
            return False
        finally:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)
            if signature_temp is not None:
                signature_temp.unlink(missing_ok=True)

'''
text = text[:start] + replacement + text[end:]

old_route = r'''@app.route("/thumbs/<path:project_code>/<filename>")
def thumb_file(project_code, filename):
    safe_name = _safe_media_name(filename)
    if not safe_name:
        return "not found", 404
    if not safe_name.startswith(manager.THUMB_SUFFIX):
        safe_name = manager._thumb_filename(safe_name)
    thumb_path = manager._photos_dir(project_code) / safe_name
    if not thumb_path.exists():
        manager._ensure_thumbnail(project_code, safe_name)
    if not thumb_path.exists():
        return "not found", 404
    resp = send_from_directory(manager._photos_dir(project_code), safe_name)
    resp.mimetype = "image/webp"
    # 缩略图按文件名固定不变，可长期缓存
    resp.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    return resp
'''
new_route = r'''@app.route("/thumbs/<path:project_code>/<filename>")
def thumb_file(project_code, filename):
    safe_name = _safe_media_name(filename)
    if not safe_name:
        return "not found", 404
    if not safe_name.startswith(manager.THUMB_SUFFIX):
        safe_name = manager._thumb_filename(safe_name)
    # 即使缩略图已经存在，也必须核对源文件签名；SY001 等显示编号会被复用。
    if not manager._ensure_thumbnail(project_code, safe_name):
        return "not found", 404
    thumb_path = manager._photos_dir(project_code) / safe_name
    if not thumb_path.is_file():
        return "not found", 404
    resp = send_from_directory(manager._photos_dir(project_code), safe_name)
    resp.mimetype = "image/webp"
    # _photo_item 会给正常图库 URL 带源文件版本号，只有这种 URL 才可 immutable。
    # 兼容旧页面/最近上传等无版本 URL 时必须重新验证，不能把复用编号缓存一年。
    if str(request.args.get("v") or "").strip():
        resp.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    else:
        resp.headers["Cache-Control"] = "no-cache, max-age=0, must-revalidate"
    return resp
'''
if old_route not in text:
    raise SystemExit('thumb route anchor not found')
text = text.replace(old_route, new_route, 1)

path.write_text(text, encoding='utf-8')

Path('tests/test_thumbnail_consistency.py').write_text(r'''import tempfile
import time
import unittest
from pathlib import Path

from PIL import Image

import app


class ThumbnailConsistencyTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='album-thumb-consistency-')
        self.manager = app.AlbumManager(Path(self.temp.name) / 'albums')
        self.code = 'UNIT-001'
        self.photos = self.manager._photos_dir(self.code)
        self.photos.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        self.temp.cleanup()

    def _write_jpg(self, path, color, size=(120, 80)):
        Image.new('RGB', size, color).save(path, 'JPEG', quality=95)

    def _center(self, path):
        with Image.open(path) as image:
            image = image.convert('RGB')
            return image.getpixel((image.width // 2, image.height // 2))

    def test_thumbnail_name_keeps_original_extension(self):
        self.assertEqual(
            self.manager._thumb_filename('construction-UNIT-001-SY001.jpg'),
            'thumb_construction-UNIT-001-SY001.jpg.webp',
        )
        self.assertNotEqual(
            self.manager._thumb_filename('same.jpg'),
            self.manager._thumb_filename('same.png'),
        )

    def test_reused_display_filename_rebuilds_thumbnail(self):
        original = self.photos / 'construction-UNIT-001-SY001.jpg'
        self._write_jpg(original, (220, 20, 20))
        self.assertTrue(self.manager._ensure_thumbnail(self.code, original.name))
        thumb = self.photos / self.manager._thumb_filename(original.name)
        first = self._center(thumb)
        time.sleep(0.01)
        # 模拟删除/重排后 SY001 被新照片复用。
        self._write_jpg(original, (20, 40, 220), size=(121, 81))
        self.assertTrue(self.manager._ensure_thumbnail(self.code, original.name))
        second = self._center(thumb)
        self.assertGreater(first[0], first[2])
        self.assertGreater(second[2], second[0])
        self.assertTrue(self.manager._thumbnail_signature_path(thumb).is_file())

    def test_legacy_unsigned_thumbnail_is_not_trusted(self):
        original = self.photos / 'construction-UNIT-001-SY001.jpg'
        self._write_jpg(original, (20, 180, 40))
        legacy = self.photos / 'thumb_construction-UNIT-001-SY001.webp'
        Image.new('RGB', (60, 40), (220, 20, 20)).save(legacy, 'WEBP')
        self.assertFalse(self.manager._thumbnail_signature_path(legacy).exists())
        self.assertTrue(self.manager._ensure_thumbnail(self.code, legacy.name))
        pixel = self._center(legacy)
        self.assertGreater(pixel[1], pixel[0])
        self.assertTrue(self.manager._thumbnail_signature_path(legacy).is_file())

    def test_legacy_ambiguous_extension_refuses_to_guess(self):
        jpg = self.photos / 'same.jpg'
        png = self.photos / 'same.png'
        self._write_jpg(jpg, (1, 2, 3))
        Image.new('RGB', (120, 80), (4, 5, 6)).save(png, 'PNG')
        self.assertIsNone(self.manager._find_original(self.code, 'thumb_same.webp'))


if __name__ == '__main__':
    unittest.main()
''', encoding='utf-8')
print('PATCH_APPLIED')
