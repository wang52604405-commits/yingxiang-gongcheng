# -*- coding: utf-8 -*-
"""多专业工程影像采集模板读取服务。

模板保持为数据文件。市政规则以 municipal_rules 为唯一来源，
桌面、服务端和小程序都读这里，不再各写一份中文清单。
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

import municipal_rules
import highway_rules


BASE_DIR = Path(__file__).resolve().parent
TEMPLATE_PATH = BASE_DIR / "assets" / "professional_templates.json"

INDUSTRY_ALIASES = {
    "公路": "公路工程",
    "highway": "公路工程",
    "水利": "水利工程",
    "房建": "房屋建筑工程",
    "房屋建筑": "房屋建筑工程",
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
    raw["municipal_rule_version"] = municipal_rules.RULE_VERSION
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
    grouped.setdefault("水利工程", set()).add("水利工程（沿用项目划分）")
    grouped[highway_rules.INDUSTRY_NAME] = set(highway_rules.PROJECT_TYPES)
    for subtype in municipal_rules.SUBTYPES:
        grouped.setdefault(municipal_rules.INDUSTRY_NAME, set()).add(subtype["name"])
    return {
        "version": str(template_db.get("version") or "V1.0"),
        "municipal_rule_version": municipal_rules.RULE_VERSION,
        "industries": [
            {
                "name": industry,
                "project_types": sorted(types),
                "subtypes": municipal_rules.subtype_catalog() if industry == municipal_rules.INDUSTRY_NAME else [],
            }
            for industry, types in grouped.items()
            if industry
        ],
    }


def requirements(industry: str, project_type: str = "") -> list[dict]:
    normalized_industry = _norm(industry)
    normalized_project_type = str(project_type or "").strip()
    if normalized_industry == highway_rules.INDUSTRY_NAME:
        if normalized_project_type:
            highway_rules.canonical_project_type(normalized_project_type)
        return []
    if normalized_industry == "水利工程":
        return []
    if normalized_industry == municipal_rules.INDUSTRY_NAME:
        rows = [
            item
            for item in load_template_db()["templates"]
            if _norm(item.get("industry")) == municipal_rules.INDUSTRY_NAME
        ]
        if normalized_project_type:
            canonical = municipal_rules.canonical_project_type(normalized_project_type)
            normalized_project_type = canonical
        return municipal_rules.filter_requirements(rows, normalized_project_type)
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
    normalized_industry = _norm(industry)
    checklist_status = "ready"
    support_note = ""
    try:
        rows = requirements(industry, project_type)
    except municipal_rules.MunicipalRuleError as exc:
        if normalized_industry == municipal_rules.INDUSTRY_NAME and exc.code == "project_type_required":
            rows = []
            checklist_status = "type_required"
            support_note = str(exc)
        else:
            raise
    if normalized_industry == municipal_rules.INDUSTRY_NAME and project_type:
        found = municipal_rules.subtype_by_name(project_type)
        if found and found["photo_checklist"] != "curated":
            checklist_status = "project_config"
            support_note = found.get("support_note", "")
            rows = []
    if normalized_industry == highway_rules.INDUSTRY_NAME:
        checklist_status = "project_config"
        support_note = "拍摄内容按合同及批准的项目方案配置。"
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
        "rule_version": highway_rules.RULE_VERSION if normalized_industry == highway_rules.INDUSTRY_NAME else municipal_rules.RULE_VERSION if normalized_industry == municipal_rules.INDUSTRY_NAME else "",
        "checklist_status": checklist_status,
        "support_note": support_note,
        "rule_notice": "公路土建按 JTG F80/1-2017 及批准划分管理，照片不代替质量检验和验收文件。" if normalized_industry == highway_rules.INDUSTRY_NAME else "软件建议不能当成国家强制。隐蔽前现场影像的依据是 GB 55032-2022 第3.3.4条第4款，照片不代替验收文件。",
    }


def municipal_template_document() -> dict:
    return {
        "rule_version": municipal_rules.RULE_VERSION,
        "industry": municipal_rules.INDUSTRY_NAME,
        "industry_code": municipal_rules.INDUSTRY_CODE,
        "transfer_timing": municipal_rules.TRANSFER_TIMING_TEXT,
        "concealment_clause": municipal_rules.CONCEALMENT_CLAUSE,
        "concealment_text": municipal_rules.CONCEALMENT_TEXT,
        "hash_limitation": municipal_rules.HASH_LIMITATION_TEXT,
        "precheck_statement": municipal_rules.PRECHECK_STATEMENT,
        "local_profiles_enabled": [],
        "subtypes": municipal_rules.subtype_catalog(),
        "import_headers": list(municipal_rules.MUNICIPAL_IMPORT_HEADERS),
        "phases": municipal_rules.PHASES,
        "concealment_states": municipal_rules.CONCEALMENT_STATES,
    }
