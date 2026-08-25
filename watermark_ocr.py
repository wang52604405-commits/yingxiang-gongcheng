# -*- coding: utf-8 -*-
"""桌面端水印 OCR 兼容入口。

公开函数名保持不变，真正的 OCR、日期解析和字段提取统一由
``server.mobile_recognition`` 实现。这样桌面端与服务器不会因复制规则
而逐渐产生不同的识别结果。
"""

from __future__ import annotations

from server import mobile_recognition as _shared

__all__ = ["ocr_lines", "extract_fields", "recognize_watermark"]


def ocr_lines(image_bytes) -> list:
    """识别图片文字行；失败时与旧版一样返回空列表。"""
    return _shared.ocr_lines(image_bytes, strict=False)


def extract_fields(lines) -> dict:
    """从 OCR 文字行提取日期、施工区域、施工内容和工程名。"""
    return _shared.extract_fields(lines)


def recognize_watermark(image_bytes) -> dict:
    """一键识别：OCR + 结构化解析，异常不中断桌面上传。"""
    return _shared.recognize_watermark(image_bytes, strict=False)
