# -*- coding: utf-8 -*-
"""给已有照片批量识别横/竖方向（不借助 AI，按像素判断）。"""
import os
import sys

os.environ["ALBUM_DATA_DIR"] = r"D:\工程影像资料"
sys.path.insert(0, r"E:\use")
import app as album_app


def main():
    manager = album_app.AlbumManager(album_app.ALBUMS_DIR)
    scanned = 0
    portrait = 0
    updated_projects = 0
    for project_dir in album_app.ALBUMS_DIR.iterdir():
        if not project_dir.is_dir() or project_dir.name.startswith("_"):
            continue
        meta_path = project_dir / "metadata.json"
        if not meta_path.exists():
            continue
        try:
            data = manager._read_metadata(project_dir.name)
        except Exception:
            continue
        photos_dir = manager._photos_dir(project_dir.name)
        changed = False
        for photo in data.get("photos", []):
            path = photos_dir / (photo.get("filename") or "")
            if not path.exists():
                continue
            scanned += 1
            detected = album_app.detect_photo_orientation(path)
            if detected == "portrait":
                portrait += 1
            if detected and photo.get("orientation") != detected:
                photo["orientation"] = detected
                photo["orientation_label"] = album_app.PHOTO_ORIENTATION_LABELS[detected]
                changed = True
        if changed:
            manager._write_metadata(project_dir.name, data)
            updated_projects += 1
    print(f"扫描照片 {scanned} 张，识别为竖版 {portrait} 张，更新单元 {updated_projects} 个")


if __name__ == "__main__":
    main()
