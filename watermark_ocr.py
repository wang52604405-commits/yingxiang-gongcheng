# -*- coding: utf-8 -*-
"""水印相机水印文字识别。

上传照片时调用 RapidOCR 读取烧录在图片里的水印文字（日期时间、地点、备注），
补全照片题名与日期。全程异常安全：OCR 失败返回空结果，绝不中断上传。
"""

from __future__ import annotations

import io
import re
import threading

_ENGINE = None
_ENGINE_LOCK = threading.Lock()

# 日期时间：2025年09月30日 14:30:25 / 2025-09-30 / 2025/09/30 / 2025.09.30 / 20250930
_DATE_RE = re.compile(
    r"(\d{4})\s*(?:年|[-/.年])\s*(\d{1,2})\s*(?:月|[-/.月])\s*(\d{1,2})\s*(?:日)?"
    r"|(\d{8})"
)
# 工程特征词：这些行最可能是值得写进题名的备注
_ENGINEERING_MARKERS = re.compile(
    r"桩号|里程|K\s*\d\s*\+|钻孔|施工|部位|段落|方量|混凝土|浇筑|喷浆|注浆|"
    r"开挖|回填|挡墙|护坡|盖梁|墩|桩基|结构|验收|放样|测量|长度|深度|标高"
)
# 地点行特征
_LOCATION_MARKERS = re.compile(r"省|市|区|县|镇|乡|村|路|街|道|纬|经|°|°")


def _get_engine():
    global _ENGINE
    if _ENGINE is None:
        with _ENGINE_LOCK:
            if _ENGINE is None:
                from rapidocr_onnxruntime import RapidOCR

                _ENGINE = RapidOCR()
    return _ENGINE


def _parse_date(text):
    """从文本里解析出 YYYY-MM-DD，找不到返回空串。"""
    for match in _DATE_RE.finditer(str(text or "")):
        if match.group(4):
            raw = match.group(4)
            return f"{raw[:4]}-{raw[4:6]}-{raw[6:8]}"
        year, month, day = match.group(1), match.group(2), match.group(3)
        try:
            return f"{int(year):04d}-{int(month):02d}-{int(day):02d}"
        except (TypeError, ValueError):
            continue
    return ""


def _clean_line(text):
    """去掉行首尾的分隔/空白噪音。"""
    text = str(text or "").strip()
    text = re.sub(r"^[\s\-—–·.|_]+|[\s\-—–·.|_]+$", "", text)
    return text


def _label_value(lines, *labels):
    """读取水印键值字段，兼容 OCR 把中文标签识别成带空格的形式。"""
    label_pattern = "|".join(re.escape(label) for label in labels)
    for line in lines:
        compact = re.sub(r"\s+", "", str(line or ""))
        match = re.search(rf"(?:{label_pattern})[:：]?(.+)", compact)
        if not match:
            continue
        candidate = _clean_line(match.group(1))
        if candidate and "请输入" not in candidate:
            return candidate[:100]
    return ""


def _pick_title(lines):
    """施工内容是题名；没有施工内容时才使用兼容字段兜底。"""
    construction_content = _label_value(lines, "施工内容")
    if construction_content:
        return construction_content[:60]
    fallback = _label_value(lines, "施工部位", "备注")
    if fallback:
        return fallback[:60]
    for line in lines:
        if "请输入" in line:
            continue
        if _ENGINEERING_MARKERS.search(line) and not _DATE_RE.search(line):
            return _clean_line(line)[:60]
    for line in lines:
        if _LOCATION_MARKERS.search(line) and not _DATE_RE.search(line):
            return _clean_line(line)[:60]
    return ""


def ocr_lines(image_bytes) -> list:
    """识别图片字节里的文本行，按从上到下返回去重后的文本列表。失败返回空列表。"""
    try:
        import numpy as np
        from PIL import Image

        image = Image.open(io.BytesIO(image_bytes))
        image.load()
        array = np.array(image.convert("RGB"))
        engine = _get_engine()
        result, _ = engine(array)
        lines = [_clean_line(text) for _box, text, _score in (result or [])]
        lines = [line for line in lines if line]
        # 去重（保留顺序），并合并同位置重复行
        seen = []
        for line in lines:
            if not seen or line != seen[-1]:
                seen.append(line)
        return seen
    except Exception:
        return []


def extract_fields(lines) -> dict:
    """从水印解析施工区域、施工内容、工程名、日期等结构化字段。"""
    lines = [str(line or "").strip() for line in (lines or [])]
    lines = [line for line in lines if line]
    date = ""
    for line in lines:
        date = _parse_date(line)
        if date:
            break
    construction_area = _label_value(lines, "施工区域")
    construction_content = _label_value(lines, "施工内容")
    title = construction_content or _pick_title(lines)
    project_name = ""
    known_labels = re.compile(r"施工区域|施工内容|施工部位|拍摄时间|天气|地点|经度|纬度|备注")
    for line in lines:
        compact = re.sub(r"\s+", "", line)
        if not compact or known_labels.search(compact) or _DATE_RE.search(compact):
            continue
        if len(compact) >= 4 and re.search(r"工程|项目|标段", compact):
            project_name = compact[:100]
            break
    return {
        "photo_date": date,
        "title": title,
        "construction_area": construction_area,
        "construction_content": construction_content,
        "project_name": project_name,
        "watermark_text": "\n".join(lines),
    }


def recognize_watermark(image_bytes) -> dict:
    """一键识别：OCR + 解析，任何异常都返回空字段。"""
    try:
        return extract_fields(ocr_lines(image_bytes))
    except Exception:
        return {
            "photo_date": "",
            "title": "",
            "construction_area": "",
            "construction_content": "",
            "project_name": "",
            "watermark_text": "",
        }
