# -*- coding: utf-8 -*-
"""
旧照片缩略图回填脚本（一次性工具，可反复运行）

用法：
  python backfill_thumbs.py                # 扫描默认数据目录 D:\\工程影像资料
  set ALBUM_DATA_DIR=D:\\工程影像资料 && python backfill_thumbs.py

为每个项目里还没有缩略图的照片补生成 WebP 缩略图，不影响原图。
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app import AlbumManager, ALBUMS_DIR  # noqa: E402


def main() -> int:
    root = Path(os.environ.get("ALBUM_DATA_DIR", r"D:\工程影像资料")).expanduser()
    albums_dir = root / "albums"
    if not albums_dir.exists():
        print(f"未找到数据目录: {albums_dir}")
        return 1

    manager = AlbumManager(albums_dir)
    total_missing = 0
    total_ok = 0
    total_failed = 0
    for project_dir in sorted(albums_dir.iterdir()):
        if not project_dir.is_dir() or project_dir.name.startswith("_"):
            continue
        metadata_path = project_dir / "metadata.json"
        if not metadata_path.exists():
            continue
        try:
            with metadata_path.open("r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        project_code = data.get("project_code") or project_dir.name
        photos = data.get("photos") or []
        missing = 0
        for photo in photos:
            filename = str(photo.get("filename") or "").strip()
            if not filename:
                continue
            thumb_name = manager._thumb_filename(filename)
            if (project_dir / "photos" / thumb_name).exists():
                continue
            missing += 1
            if manager._ensure_thumbnail(project_code, filename):
                total_ok += 1
            else:
                total_failed += 1
        if missing:
            total_missing += missing
            print(f"{project_code}: 补生成 {missing} 张缩略图")
    print(
        f"完成：共扫描到缺失缩略图 {total_missing} 张，"
        f"成功 {total_ok}，失败 {total_failed}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
