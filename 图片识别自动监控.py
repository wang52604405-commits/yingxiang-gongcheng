# -*- coding: utf-8 -*-
"""
图片识别自动监控（全局后台服务）

原理：监听"收件箱"文件夹，一旦出现新图片，自动执行：
  OCR 文字识别 + SHA-256/感知哈希指纹 + 图片信息，
并把结果追加写入 识别结果.md。任何聊天窗口里的图片拖进收件箱即可被识别。

启动：
  python 图片识别自动监控.py              # 前台运行
  pythonw 图片识别自动监控.py             # 后台运行（无窗口）
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import 图片识别工具 as pic  # noqa: E402
from PIL import Image  # noqa: E402

INBOX = Path(r"C:\Users\Administrator\Desktop\tts\图片识别收件箱")
EXTRA_WATCH = Path(r"C:\Users\Administrator\.codex\attachments")
REPORT = INBOX / "识别结果.md"
STATE = INBOX / "已处理.json"
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tif", ".tiff"}
SCAN_INTERVAL = 2.0


def _load_state():
    try:
        if STATE.exists():
            return json.loads(STATE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {"files": {}}


def _save_state(state):
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def _ocr_engine():
    if not hasattr(_ocr_engine, "_engine"):
        from rapidocr_onnxruntime import RapidOCR

        _ocr_engine._engine = RapidOCR()
    return _ocr_engine._engine


def analyze_image(path: Path):
    result = {
        "文件": str(path),
        "时间": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    try:
        img = pic.open_image(path)
        result["尺寸"] = f"{img.size[0]} x {img.size[1]} 像素"
        result["格式"] = str(Image.open(path).format)
    except Exception as exc:
        result["读取失败"] = str(exc)
        return result
    fp = pic.fingerprints(path)
    result["SHA-256"] = fp["sha256"]
    result["dHash"] = fp["dhash"]
    result["aHash"] = fp["ahash"]
    exif = pic.read_exif(path)
    if exif:
        result["元数据"] = "；".join(f"{k}={v}" for k, v in exif.items())
    try:
        ocr = _ocr_engine()(str(path))
        result["OCR文字"] = pic.clean_ocr_lines(ocr[0]) if ocr and ocr[0] else []
    except Exception as exc:
        result["OCR失败"] = str(exc)
    return result


def append_report(entry: dict):
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "",
        f"## {entry['时间']}  {Path(entry['文件']).name}",
        "",
    ]
    ocr_lines = entry.pop("OCR文字", None)
    for key, value in entry.items():
        lines.append(f"- **{key}**: {value}")
    if ocr_lines is not None:
        lines.append("")
        lines.append("**识别到的文字：**")
        if ocr_lines:
            for t in ocr_lines:
                lines.append(f"> {t}")
        else:
            lines.append("> （未识别到文字）")
    lines.append("")
    with REPORT.open("a", encoding="utf-8") as f:
        f.write("\n".join(lines))


def main():
    for d in (INBOX, EXTRA_WATCH):
        d.mkdir(parents=True, exist_ok=True)
    state = _load_state()
    print(f"图片识别监控已启动，收件箱：{INBOX}")
    print("把图片放进收件箱，自动识别并写入 识别结果.md")
    # 预热 OCR 模型
    try:
        _ocr_engine()
        print("OCR 模型已就绪")
    except Exception as exc:
        print(f"OCR 模型初始化失败：{exc}，文字识别暂不可用")
    while True:
        try:
            candidates = []
            for d in (INBOX, EXTRA_WATCH):
                for p in d.iterdir():
                    if p.is_file() and p.suffix.lower() in IMAGE_EXTS:
                        candidates.append(p)
            for p in candidates:
                key = f"{p}::{p.stat().st_size}"
                if state["files"].get(key):
                    continue
                print(f"[新图片] {p.name}，正在识别...")
                entry = analyze_image(p)
                append_report(entry)
                state["files"][key] = entry["时间"]
                _save_state(state)
                print(f"[完成] 结果已写入 {REPORT.name}")
        except Exception as exc:
            print(f"[监控异常] {exc}")
        time.sleep(SCAN_INTERVAL)


if __name__ == "__main__":
    main()
