# -*- coding: utf-8 -*-
"""多专业工程影像采集模板读取服务。

模板保持为数据文件，桌面端只保存工程专业、工程类型、地区和模板版本；
具体采集清单由模板动态生成，便于后续按地区、业主或项目覆盖。
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
TEMPLATE_PATH = BASE_DIR / "assets" / "professional_templates.json"

INDUSTRY_ALIASES = {
    "水利": "水利工程",
    "房建": "房屋建筑工程",
    "市政": "市政工程",
    "电力": "电力工程",
}


@lru_cache(maxsize=1)
def load_template_db() -> dict:
    try:
        raw = json.loads(TEMPLATE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raw = {"version": "V1.0", "templates": []}
    templates = [
        item
        for item in raw.get("templates", [])
        if isinstance(item, dict) and str(item.get("enabled", "是")) != "否"
    ]
    raw["templates"] = templates
    raw["count"] = len(templates)
    return raw


def _norm(value: str) -> str:
    normalized = str(value or "").strip()
    return INDUSTRY_ALIASES.get(normalized, normalized)


def catalog() -> dict:
    template_db = load_template_db()
    grouped: dict[str, set[str]] = {"水利工程": set()}
    for item in template_db["templates"]:
        grouped.setdefault(_norm(item.get("industry")), set()).add(
            str(item.get("project_type") or "通用工程").strip()
        )
    # 当前水利项目沿用用户现有项目划分，不强制套用通用照片清单。
    grouped.setdefault("水利工程", set()).add("水利工程（沿用项目划分）")
    return {
        "version": str(template_db.get("version") or "V1.0"),
        "industries": [
            {"name": industry, "project_types": sorted(types)}
            for industry, types in grouped.items()
            if industry
        ],
    }


def requirements(industry: str, project_type: str = "") -> list[dict]:
    normalized_industry = _norm(industry)
    normalized_project_type = str(project_type or "").strip()
    if normalized_industry == "水利工程":
        return []
    rows = [
        item
        for item in load_template_db()["templates"]
        if _norm(item.get("industry")) == normalized_industry
    ]
    if normalized_project_type:
        exact = [
            item
            for item in rows
            if str(item.get("project_type") or "").strip() == normalized_project_type
        ]
        if exact:
            rows = exact
    return [dict(item) for item in rows]


def plan_summary(industry: str, project_type: str = "") -> dict:
    rows = requirements(industry, project_type)
    counts = {"required": 0, "conditional": 0, "recommended": 0}
    for row in rows:
        key = str(row.get("required_type") or "recommended")
        counts[key] = counts.get(key, 0) + 1
    return {
        "total": len(rows),
        "required": counts.get("required", 0),
        "conditional": counts.get("conditional", 0),
        "recommended": counts.get("recommended", 0),
        "template_version": str(load_template_db().get("version") or "V1.0"),
    }
