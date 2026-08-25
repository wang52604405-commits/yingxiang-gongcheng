# -*- coding: utf-8 -*-
"""水印 OCR 与工程划分匹配的共享核心。

权重、置信阈值和歧义判定与桌面端 v2.64 保持一致。模块不依赖 Flask 或
SQLite，桌面端和服务器均可传入同一种候选结构复用。
"""

from __future__ import annotations

import io
import re
import threading
from pathlib import Path


ANALYZE_LOCK = threading.Lock()
_ENGINE = None
_ENGINE_LOCK = threading.Lock()

_DATE_RE = re.compile(
    r"(\d{4})\s*(?:年|[-/.年])\s*(\d{1,2})\s*(?:月|[-/.月])\s*(\d{1,2})\s*(?:日)?"
    r"|(\d{8})"
)
_ENGINEERING_MARKERS = re.compile(
    r"桩号|里程|K\s*\d\s*\+|钻孔|施工|部位|段落|方量|混凝土|浇筑|喷浆|注浆|"
    r"开挖|回填|挡墙|护坡|盖梁|墩|桩基|结构|验收|放样|测量|长度|深度|标高"
)
_LOCATION_MARKERS = re.compile(r"省|市|区|县|镇|乡|村|路|街|道|纬|经|°")


def _get_engine():
    global _ENGINE
    if _ENGINE is None:
        with _ENGINE_LOCK:
            if _ENGINE is None:
                from rapidocr_onnxruntime import RapidOCR

                _ENGINE = RapidOCR()
    return _ENGINE


def _clean_line(text):
    text = str(text or "").strip()
    return re.sub(r"^[\s\-—–·.|_]+|[\s\-—–·.|_]+$", "", text)


def _parse_date(text):
    for match in _DATE_RE.finditer(str(text or "")):
        if match.group(4):
            raw = match.group(4)
            return f"{raw[:4]}-{raw[4:6]}-{raw[6:8]}"
        try:
            return f"{int(match.group(1)):04d}-{int(match.group(2)):02d}-{int(match.group(3)):02d}"
        except (TypeError, ValueError):
            continue
    return ""


def _label_value(lines, *labels):
    pattern = "|".join(re.escape(label) for label in labels)
    for line in lines:
        compact = re.sub(r"\s+", "", str(line or ""))
        match = re.search(rf"(?:{pattern})[:：]?(.+)", compact)
        if match:
            candidate = _clean_line(match.group(1))
            if candidate and "请输入" not in candidate:
                return candidate[:100]
    return ""


def _pick_title(lines):
    construction_content = _label_value(lines, "施工内容")
    if construction_content:
        return construction_content[:60]
    fallback = _label_value(lines, "施工部位", "备注")
    if fallback:
        return fallback[:60]
    for line in lines:
        if "请输入" not in line and _ENGINEERING_MARKERS.search(line) and not _DATE_RE.search(line):
            return _clean_line(line)[:60]
    for line in lines:
        if _LOCATION_MARKERS.search(line) and not _DATE_RE.search(line):
            return _clean_line(line)[:60]
    return ""


def ocr_lines(image_bytes: bytes, strict: bool = False) -> list[str]:
    try:
        import numpy as np
        from PIL import Image

        with Image.open(io.BytesIO(image_bytes)) as image:
            image.load()
            array = np.array(image.convert("RGB"))
        result, _ = _get_engine()(array)
        lines = [_clean_line(text) for _box, text, _score in (result or [])]
        unique = []
        for line in (line for line in lines if line):
            if not unique or line != unique[-1]:
                unique.append(line)
        return unique
    except Exception:
        if strict:
            raise
        return []


def extract_fields(lines) -> dict:
    lines = [str(line or "").strip() for line in (lines or []) if str(line or "").strip()]
    photo_date = next((_parse_date(line) for line in lines if _parse_date(line)), "")
    construction_area = _label_value(lines, "施工区域")
    construction_content = _label_value(lines, "施工内容")
    title = construction_content or _pick_title(lines)
    project_name = ""
    known = re.compile(r"施工区域|施工内容|施工部位|拍摄时间|天气|地点|经度|纬度|备注")
    for line in lines:
        compact = re.sub(r"\s+", "", line)
        if compact and not known.search(compact) and not _DATE_RE.search(compact):
            if len(compact) >= 4 and re.search(r"工程|项目|标段", compact):
                project_name = compact[:100]
                break
    return {
        "photo_date": photo_date,
        "title": title,
        "construction_area": construction_area,
        "construction_content": construction_content,
        "project_name": project_name,
        "watermark_text": "\n".join(lines),
    }


def recognize_watermark(image_bytes: bytes, strict: bool = False) -> dict:
    return extract_fields(ocr_lines(image_bytes, strict=strict))


def normalize_match_text(value):
    return re.sub(r"[\s\-_.()（）【】\[\]{}?？]+", "", str(value or "").lower())


def match_signal_score(signal, candidate, source_kind, field_kind):
    """与桌面端 `_match_signal_score` 同权重。"""
    signal_key = normalize_match_text(signal)
    candidate_key = normalize_match_text(candidate)
    if not signal_key or not candidate_key or len(candidate_key) < 2:
        return 0
    exact = signal_key == candidate_key
    contained = candidate_key in signal_key or (
        len(signal_key) >= 4 and signal_key in candidate_key
    )
    if not exact and not contained:
        return 0
    unit_weights = {
        "area": (980, 860),
        "folder": (920, 780),
        "filename": (880, 740),
        "project": (620, 500),
        "content": (360, 260),
    }
    hierarchy_weights = {
        "area": (430, 330),
        "folder": (380, 290),
        "filename": (320, 240),
        "project": (260, 190),
        "content": (120, 80),
    }
    exact_score, contains_score = (
        unit_weights if field_kind == "unit" else hierarchy_weights
    ).get(source_kind, (0, 0))
    return exact_score if exact else contains_score + min(60, len(candidate_key) * 3)


def match_photo(filename="", relative_path="", ocr_fields=None, candidates=None, limit=5):
    """按桌面端规则返回高/中/低置信候选。"""
    ocr_fields = ocr_fields or {}
    folder = str(Path(str(relative_path or "").replace("\\", "/")).parent).replace("\\", "/")
    if folder in {"", "."}:
        folder = ""
    signals = [
        ("area", "施工区域", ocr_fields.get("construction_area", "")),
        ("folder", "文件夹", folder),
        ("filename", "文件名", Path(filename or "").stem),
        ("project", "水印工程名", ocr_fields.get("project_name", "")),
        ("content", "施工内容", ocr_fields.get("construction_content") or ocr_fields.get("title", "")),
    ]
    ranked = []
    for candidate in candidates or []:
        fields = candidate.get("source_fields") or {}
        unit_values = [
            candidate.get("project_code", ""),
            candidate.get("display_project_code", ""),
            candidate.get("project_name", ""),
            fields.get("单元工程编码", ""),
            fields.get("单元工程名称", ""),
        ]
        hierarchy_values = [
            fields.get("分部工程编码", ""), fields.get("分部工程名称", ""),
            fields.get("单位工程编码", ""), fields.get("单位工程名称", ""),
            fields.get("合同工程名称", ""), candidate.get("keywords", ""),
        ]
        score = 0
        reasons = []
        for source_kind, source_label, signal in signals:
            best_score, best_value, best_kind = 0, "", ""
            for value in unit_values:
                item_score = match_signal_score(signal, value, source_kind, "unit")
                if item_score > best_score:
                    best_score, best_value, best_kind = item_score, value, "unit"
            for value in hierarchy_values:
                item_score = match_signal_score(signal, value, source_kind, "hierarchy")
                if item_score > best_score:
                    best_score, best_value, best_kind = item_score, value, "hierarchy"
            if best_score:
                score += best_score
                reasons.append(
                    f"{source_label}匹配{'单元' if best_kind == 'unit' else '上级划分'}“{best_value}”"
                )
        if score:
            ranked.append({"candidate": candidate, "score": score, "reasons": reasons})
    ranked.sort(key=lambda item: (item["score"], len(item["reasons"])), reverse=True)
    top = ranked[0] if ranked else None
    top_score = top["score"] if top else 0
    second_score = ranked[1]["score"] if len(ranked) > 1 else 0
    ambiguous = bool(top and second_score and top_score - second_score < max(80, int(top_score * 0.12)))
    if top_score >= 850 and not ambiguous:
        confidence, label = "high", "高"
    elif top_score >= 560 and not ambiguous:
        confidence, label = "medium", "中"
    else:
        confidence, label = "low", "低"
    alternatives = []
    for item in ranked[: max(1, int(limit or 5))]:
        candidate = item["candidate"]
        fields = candidate.get("source_fields") or {}
        alternatives.append(
            {
                "unit_code": candidate.get("unit_code") or candidate.get("project_code", ""),
                "project_code": candidate.get("project_code", ""),
                "display_project_code": candidate.get("display_project_code")
                or fields.get("单元工程编码")
                or candidate.get("project_code", ""),
                "name": fields.get("单元工程名称") or candidate.get("project_name", ""),
                "project_name": candidate.get("project_name", ""),
                "unit_name": fields.get("单位工程名称", ""),
                "part_name": fields.get("分部工程名称", ""),
                "score": item["score"],
                "reasons": item["reasons"],
            }
        )
    selected = top["candidate"] if top else {}
    return {
        "unit_code": selected.get("unit_code") or selected.get("project_code", ""),
        "project_code": selected.get("project_code", ""),
        "project_name": selected.get("project_name", ""),
        "confidence": confidence,
        "confidence_label": label,
        "ambiguous": ambiguous,
        "score": top_score,
        "reasons": top.get("reasons", []) if top else ["未找到可匹配的项目划分"],
        "alternatives": alternatives,
        "candidates": alternatives,
    }


def candidates_from_cloud_rows(project, rows):
    """把 cloud_units 平铺行转换成桌面匹配器使用的候选结构。"""
    project = dict(project)
    values = [dict(row) for row in rows]
    by_code = {item["node_code"]: item for item in values}
    candidates = []
    for unit in values:
        if unit["node_type"] != "unit":
            continue
        ancestors = {}
        parent_code = unit.get("parent_code", "")
        while parent_code and parent_code in by_code:
            parent = by_code[parent_code]
            ancestors[parent["node_type"]] = parent
            parent_code = parent.get("parent_code", "")
        metadata = unit.get("metadata_json", {})
        if isinstance(metadata, str):
            try:
                import json

                metadata = json.loads(metadata or "{}")
            except (TypeError, ValueError):
                metadata = {}
        part = ancestors.get("part", {})
        unit_project = ancestors.get("unit_project", {})
        contract = ancestors.get("contract", {})
        candidates.append(
            {
                "unit_code": unit["node_code"],
                "project_code": metadata.get("internal_project_code") or unit["node_code"],
                "display_project_code": unit["node_code"],
                "project_name": unit["name"],
                "keywords": metadata.get("keywords", ""),
                "source_fields": {
                    "单元工程编码": unit["node_code"],
                    "单元工程名称": unit["name"],
                    "分部工程编码": part.get("node_code", ""),
                    "分部工程名称": part.get("name", ""),
                    "单位工程编码": unit_project.get("node_code", ""),
                    "单位工程名称": unit_project.get("name", ""),
                    "合同工程名称": contract.get("name") or project.get("project_name", ""),
                },
            }
        )
    return candidates
