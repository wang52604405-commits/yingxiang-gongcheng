import tempfile
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
