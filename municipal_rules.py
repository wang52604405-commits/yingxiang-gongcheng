# -*- coding: utf-8 -*-
"""市政工程影像的单一规则源。

工程质量划分、空间定位、工序事件、档案组卷是四套独立维度。
本模块只固化已经读到的国家规章和强制通规，以及产品建议。
未核验的地方接收标准不默认启用，也不把软件建议写成国家强制。
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path


RULE_VERSION = "M2026.11-1"
TEMPLATE_FILE_VERSION = "V1.0"
INDUSTRY_NAME = "市政工程"
INDUSTRY_CODE = "municipal"

# 2026 年第 61 号令已读条文，只在帮助和预检说明里引用，不做成提醒系统。
TRANSFER_TIMING_TEXT = (
    "建设单位在竣工验收备案前移交工程档案；备案后形成的材料，在备案后三个月内移交。"
    "影像不代替验收文件，导出完成也不等于已经移交或验收通过。"
)
CONCEALMENT_CLAUSE = "GB 55032-2022 第3.3.4条第4款"
CONCEALMENT_TEXT = (
    "隐蔽工程在隐蔽前应留存现场影像资料，并形成验收文件，经验收合格后方可继续施工。"
    "照片不能代替验收记录或监理签认。"
)
HASH_LIMITATION_TEXT = (
    "哈希只说明这份字节与摄入时记录的一致，不证明现场事实、拍摄时间或坐标真实。"
)
PRECHECK_STATEMENT = "预检通过不等于城建档案机构验收通过，也不等于已经移交。"

INDUSTRY_ALIASES = {
    "市政": INDUSTRY_NAME,
    "市政工程": INDUSTRY_NAME,
    "municipal": INDUSTRY_NAME,
}

# 稳定代码不随中文文案变化。前六类保留既有拍摄清单；构筑物只有划分骨架。
SUBTYPES = (
    {
        "code": "road",
        "name": "城镇道路",
        "photo_checklist": "curated",
        "aliases": ("道路", "道路工程", "城镇道路工程", "市政道路"),
    },
    {
        "code": "bridge",
        "name": "城市桥梁",
        "photo_checklist": "curated",
        "aliases": ("桥梁", "桥梁工程", "城市桥梁工程"),
    },
    {
        "code": "water_supply",
        "name": "给水管道",
        "photo_checklist": "curated",
        "aliases": ("给水", "给水管", "给水工程", "给水管道工程"),
    },
    {
        "code": "drainage",
        "name": "排水管道",
        "photo_checklist": "curated",
        "aliases": ("排水", "排水管", "排水工程", "排水管道工程", "雨水", "污水"),
    },
    {
        "code": "utility_tunnel",
        "name": "综合管廊",
        "photo_checklist": "curated",
        "aliases": ("管廊", "综合管廊工程"),
    },
    {
        "code": "lighting",
        "name": "道路照明与交通设施",
        "photo_checklist": "curated",
        "aliases": ("照明", "道路照明", "交通设施", "照明与交通"),
    },
    {
        "code": "structure",
        "name": "给水排水构筑物",
        "photo_checklist": "project_config",
        "aliases": ("构筑物", "给排水构筑物", "给水排水构筑物工程", "泵站", "水池"),
        "support_note": (
            "划分骨架来自 GB 55032-2022 附录 C。没有单独的全国强制拍摄清单，"
            "不能把泵站、水池套进井段模板；拍摄节点按批准的项目方案配置。"
        ),
    },
)

MUNICIPAL_IMPORT_HEADERS = (
    "合同或标段名称",
    "单位工程名称",
    "单位工程编码",
    "子单位工程名称",
    "子单位工程编码",
    "分部工程名称",
    "分部工程编码",
    "子分部工程名称",
    "子分部工程编码",
    "分项工程名称",
    "分项工程编码",
    "关键词",
)

# GB 55032-2022 附录 C 的质量划分骨架。用户导入后可改，不按照片清单自动生成。
# 墩、跨、井段是空间实例，不写成全国固定分部名称。
DIVISION_SKELETON = {
    "城镇道路": {
        "divisions": [
            {"name": "路基", "items": ["清表", "开挖", "软基处理", "填筑"]},
            {"name": "基层", "items": ["结构层施工"]},
            {"name": "面层", "items": ["沥青混合料面层", "沥青贯入式与表面处治面层", "水泥混凝土面层", "铺砌式面层"]},
            {"name": "广场与停车场", "items": ["广场与停车场"]},
            {"name": "人行道", "items": ["人行道"]},
            {"name": "人行地道结构", "items": ["人行地道结构"]},
            {"name": "挡土墙", "items": ["挡土墙"]},
            {"name": "附属构筑物", "items": ["路缘石", "雨水口", "护栏"]},
        ]
    },
    "城市桥梁": {
        "divisions": [
            {"name": "地基与基础", "items": ["地基与基础"]},
            {"name": "墩台", "items": ["墩台"]},
            {"name": "盖梁", "items": ["盖梁"]},
            {"name": "支座", "items": ["支座"]},
            {"name": "索塔", "items": ["索塔"], "optional_note": "仅实际有索塔的桥型启用，简支梁桥不强制"},
            {"name": "锚碇", "items": ["锚碇"], "optional_note": "仅实际有锚碇的桥型启用，简支梁桥不强制"},
            {"name": "桥跨承重结构", "items": ["桥跨承重结构"]},
            {"name": "顶进箱涵", "items": ["顶进箱涵"], "optional_note": "仅顶进施工时启用"},
            {"name": "桥面系", "items": ["桥面系"]},
            {"name": "附属结构", "items": ["附属结构"]},
            {"name": "装饰与装修", "items": ["装饰与装修"]},
            {"name": "引道", "items": ["引道"]},
        ]
    },
    "给水管道": {
        "divisions": [
            {"name": "土石方", "items": ["沟槽开挖", "验槽"]},
            {"name": "预制管开槽施工主体结构", "items": ["管道基础", "下管与接口"]},
            {"name": "不开槽施工主体结构", "items": ["工作井", "顶管", "定向钻"], "optional_note": "仅实际采用不开槽工艺时启用"},
            {"name": "附属构筑物", "items": ["井室", "支墩"]},
            {"name": "给水管道功能性试验", "items": ["水压试验", "冲洗消毒"], "note": "不施加到雨水、污水管道"},
        ]
    },
    "排水管道": {
        "divisions": [
            {"name": "土石方", "items": ["沟槽开挖", "验槽"]},
            {"name": "预制管开槽施工主体结构", "items": ["管道基础", "下管与接口"]},
            {"name": "不开槽施工主体结构", "items": ["工作井", "顶管"], "optional_note": "仅实际采用不开槽工艺时启用"},
            {"name": "附属构筑物", "items": ["检查井"]},
            {"name": "排水管道功能性试验", "items": ["闭水试验", "闭气试验"], "note": "按实际试验方法启用，不施加到给水管道"},
        ]
    },
    "综合管廊": {
        "divisions": [
            {"name": "基坑与基础", "items": ["基坑", "基础"]},
            {"name": "管廊主体", "items": ["管廊主体"]},
            {"name": "附属设施", "items": ["附属设施"]},
        ]
    },
    "道路照明与交通设施": {
        "divisions": [
            {"name": "基础与杆件", "items": ["基础", "杆件"]},
            {"name": "设备与线缆", "items": ["线缆", "设备"]},
        ]
    },
    "给水排水构筑物": {
        "divisions": [
            {"name": "地基与基础", "items": ["地基与基础"]},
            {"name": "主体结构", "items": ["主体结构"]},
            {"name": "附属构筑物", "items": ["附属构筑物"]},
            {"name": "进出水管渠", "items": ["进出水管渠"]},
        ]
    },
}

SPATIAL_FIELDS = {
    "road": (
        {"key": "road_name", "label": "道路名称"},
        {"key": "stake_start", "label": "起点桩号", "preserve_text": True},
        {"key": "stake_end", "label": "讫点桩号", "preserve_text": True},
        {"key": "chainage_note", "label": "断链说明"},
        {"key": "side", "label": "左右幅或车道"},
    ),
    "bridge": (
        {"key": "bridge_name", "label": "桥名"},
        {"key": "pier_no", "label": "墩台号", "preserve_text": True},
        {"key": "span_no", "label": "跨号", "preserve_text": True},
        {"key": "member_no", "label": "构件号", "preserve_text": True},
    ),
    "water_supply": (
        {"key": "pipe_system", "label": "管道系统"},
        {"key": "well_from", "label": "起点井号", "preserve_text": True},
        {"key": "well_to", "label": "讫点井号", "preserve_text": True},
        {"key": "segment_note", "label": "井段说明"},
    ),
    "drainage": (
        {"key": "pipe_system", "label": "管道系统"},
        {"key": "well_from", "label": "起点井号", "preserve_text": True},
        {"key": "well_to", "label": "讫点井号", "preserve_text": True},
        {"key": "segment_note", "label": "井段说明"},
    ),
    "utility_tunnel": (
        {"key": "tunnel_name", "label": "管廊名称"},
        {"key": "cabin", "label": "舱室"},
        {"key": "stake_start", "label": "桩号", "preserve_text": True},
        {"key": "zone", "label": "分区"},
    ),
    "lighting": (
        {"key": "road_name", "label": "道路名称"},
        {"key": "stake_start", "label": "桩号", "preserve_text": True},
        {"key": "pole_no", "label": "杆号或设备号", "preserve_text": True},
    ),
    "structure": (
        {"key": "structure_name", "label": "构筑物名称"},
        {"key": "structure_part", "label": "部位"},
    ),
}

PHASES = {"before": "施工前", "during": "施工中", "after": "竣工后", "activity": "重要活动"}
CONCEALMENT_STATES = {"none": "不适用", "before_cover": "隐蔽前", "after_cover": "覆盖后"}
GPS_STATES = {"present", "denied", "absent", ""}
ORIGINAL_STATES = {"preserved", "derived", "missing"}


class MunicipalRuleError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def is_municipal_name(industry: str) -> bool:
    return INDUSTRY_ALIASES.get(str(industry or "").strip(), str(industry or "").strip()) == INDUSTRY_NAME


def subtype_by_name(name: str) -> dict | None:
    text = str(name or "").strip()
    if not text:
        return None
    for item in SUBTYPES:
        if text == item["name"] or text == item["code"] or text in item["aliases"]:
            return item
    return None


def canonical_project_type(project_type: str) -> str:
    found = subtype_by_name(project_type)
    if not found:
        raise MunicipalRuleError(
            "unknown_project_type",
            "工程类型不在市政模板中。请从城镇道路、城市桥梁、给水管道、排水管道、综合管廊、道路照明与交通设施、给水排水构筑物中选择，不能自动改成第一项或整份拍摄清单。",
        )
    return found["name"]


def subtype_code(project_type: str) -> str:
    found = subtype_by_name(project_type)
    return found["code"] if found else ""


def subtype_catalog() -> list[dict]:
    rows = []
    for item in SUBTYPES:
        rows.append(
            {
                "code": item["code"],
                "name": item["name"],
                "photo_checklist": item["photo_checklist"],
                "support_note": item.get("support_note", ""),
                "spatial_fields": list(SPATIAL_FIELDS[item["code"]]),
                "divisions": DIVISION_SKELETON[item["name"]]["divisions"],
            }
        )
    return rows


def _concealment_row(row: dict) -> bool:
    """只认模板里单独标出的隐蔽前，不把「覆土前、试验时或完成后」这类批量时机当成强制。"""
    if str(row.get("rule_id") or "") == "GB55032-3.3.4-4":
        return True
    if str(row.get("rule_level") or "") == "product_default":
        return False
    return str(row.get("before_concealment_required") or "") == "是"


def present_requirement(row: dict) -> dict:
    """修正批量标注。只有隐蔽前留影像引用已读的强制条款，其余保持软件建议。"""
    item = dict(row)
    if not is_municipal_name(item.get("industry", "")):
        return item
    concealment = _concealment_row(item)
    item["rule_version"] = RULE_VERSION
    item["legacy_required_type"] = str(item.get("required_type") or "")
    if concealment:
        item["rule_level"] = "national_mandatory"
        item["rule_id"] = "GB55032-3.3.4-4"
        item["rule_clause"] = CONCEALMENT_CLAUSE
        item["required_type"] = "required"
        item["before_concealment_required"] = "是"
        item["rule_nature"] = CONCEALMENT_TEXT
        item["standard_source"] = CONCEALMENT_CLAUSE
    else:
        item["rule_level"] = "product_default"
        item["rule_id"] = "product-" + str(item.get("template_code") or "")
        item["rule_clause"] = ""
        if item.get("required_type") == "required":
            item["required_type"] = "recommended"
        item["rule_nature"] = "软件建议，项目可调整。不是国家强制必拍目录，也不代表城建馆验收通过。"
        item["standard_source"] = (
            "产品采集建议。归档整理可参考推荐性标准 GB/T 50328-2014（2019年版）和 DA/T 50-2014；"
            "本条没有逐条核成强制条文。"
        )
    return item


def filter_requirements(rows: list[dict], project_type: str) -> list[dict]:
    if not str(project_type or "").strip():
        raise MunicipalRuleError("project_type_required", "请先选择市政工程类型，不能把六类拍摄清单一次全部套上。")
    canonical = canonical_project_type(project_type)
    found = subtype_by_name(canonical)
    if found and found["photo_checklist"] != "curated":
        return []
    matched = [
        present_requirement(row)
        for row in rows
        if is_municipal_name(row.get("industry", ""))
        and str(row.get("project_type") or "").strip() == canonical
    ]
    if not matched:
        raise MunicipalRuleError(
            "project_type_has_no_checklist",
            f"「{canonical}」没有可套用的拍摄清单。给水排水构筑物按项目配置，不能改用其他类型的清单。",
        )
    return matched


def local_profile_note(profile: str) -> str:
    text = str(profile or "").strip()
    if not text:
        return ""
    return (
        f"已填写地方资料标识「{text}」，但未核验的地方接收标准不会自动启用，"
        "也不套用像素、张数或每公里固定数量。"
    )


def preserve_code_text(value) -> str:
    """井号、桩号按原文本保存。数值单元格不能把 W01 收成 W1。"""
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    text = str(value).strip()
    return text


def sanitize_spatial(payload, project_type: str = "") -> dict:
    raw = payload if isinstance(payload, dict) else {}
    allowed = {field["key"] for fields in SPATIAL_FIELDS.values() for field in fields}
    if project_type:
        found = subtype_by_name(project_type)
        if found:
            allowed = {field["key"] for field in SPATIAL_FIELDS[found["code"]]}
    cleaned = {}
    for key, value in raw.items():
        if key not in allowed:
            continue
        cleaned[key] = preserve_code_text(value)[:120]
    return cleaned


def sanitize_archive(payload) -> dict:
    raw = payload if isinstance(payload, dict) else {}
    phase = str(raw.get("phase") or "").strip()
    if phase not in PHASES:
        phase = ""
    concealment = str(raw.get("concealment") or "").strip()
    if concealment not in CONCEALMENT_STATES:
        concealment = ""
    gps = raw.get("gps") if isinstance(raw.get("gps"), dict) else {}
    gps_status = str(gps.get("status") or "").strip()
    if gps_status not in GPS_STATES:
        gps_status = ""
    times = raw.get("times") if isinstance(raw.get("times"), dict) else {}
    original = raw.get("original") if isinstance(raw.get("original"), dict) else {}
    original_status = str(original.get("status") or "").strip()
    if original_status not in ORIGINAL_STATES:
        original_status = ""
    acceptance = raw.get("acceptance") if isinstance(raw.get("acceptance"), dict) else {}
    digest = str(original.get("sha256") or "").strip().lower()
    if digest and not re.fullmatch(r"[0-9a-f]{64}", digest):
        digest = ""
    return {
        "template_code": str(raw.get("template_code") or "").strip()[:80],
        "template_version": str(raw.get("template_version") or RULE_VERSION).strip()[:40],
        "phase": phase,
        "concealment": concealment,
        "process_event": str(raw.get("process_event") or "").strip()[:80],
        "location_text": str(raw.get("location_text") or "").strip()[:200],
        "acceptance": {
            "record_type": str(acceptance.get("record_type") or "").strip()[:40],
            "record_no": str(acceptance.get("record_no") or "").strip()[:80],
            "title": str(acceptance.get("title") or "").strip()[:120],
        },
        "times": {
            "exif_original": str(times.get("exif_original") or "").strip()[:40],
            "confirmed_capture": str(times.get("confirmed_capture") or "").strip()[:40],
            "correction_reason": str(times.get("correction_reason") or "").strip()[:200],
            "uploaded_at": str(times.get("uploaded_at") or "").strip()[:40],
        },
        "gps": {
            "status": gps_status,
            "latitude": str(gps.get("latitude") or "").strip()[:40],
            "longitude": str(gps.get("longitude") or "").strip()[:40],
            "manual_place": str(gps.get("manual_place") or "").strip()[:200],
        },
        "original": {
            "sha256": digest,
            "size_bytes": int(original.get("size_bytes") or 0) if str(original.get("size_bytes") or "").isdigit() else 0,
            "filename": Path(str(original.get("filename") or "")).name[:180],
            "mime": str(original.get("mime") or "").strip()[:80],
            "source": str(original.get("source") or "").strip()[:40],
            "status": original_status,
            "warning": str(original.get("warning") or "").strip()[:200],
        },
    }


def safe_export_name(value: str, fallback: str = "photo") -> str:
    leaf = Path(str(value or "")).name.replace("\x00", "")
    leaf = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", leaf).strip(" .")
    if leaf in {"", ".", ".."}:
        leaf = fallback
    return leaf[:120]


def unique_export_name(name: str, used: set[str]) -> str:
    candidate = safe_export_name(name)
    if candidate not in used:
        used.add(candidate)
        return candidate
    stem = Path(candidate).stem
    suffix = Path(candidate).suffix
    index = 2
    while True:
        renamed = f"{stem}-{index}{suffix}"
        if renamed not in used:
            used.add(renamed)
            return renamed
        index += 1


def intake_original_record(raw: bytes, filename: str, source: str, derived: bool) -> dict:
    payload = bytes(raw or b"")
    if not payload:
        return {
            "sha256": "",
            "size_bytes": 0,
            "filename": safe_export_name(filename),
            "mime": "",
            "source": source,
            "status": "missing",
            "warning": "没有摄入字节，不能把预览或压缩图标成原片。",
        }
    return {
        "sha256": hashlib.sha256(payload).hexdigest(),
        "size_bytes": len(payload),
        "filename": safe_export_name(filename),
        "mime": "",
        "source": source,
        "status": "derived" if derived else "preserved",
        "warning": "上传文件已是压缩或叠字副本，缺可归档原片。" if derived else "",
    }


def precheck_photos(photos: list[dict], *, expect_concealment: bool = False, local_profile: str = "") -> dict:
    issues = []
    originals = 0
    seen_hash = {}
    concealment_images = 0
    for photo in photos:
        archive = photo.get("archive") if isinstance(photo.get("archive"), dict) else {}
        original = archive.get("original") if isinstance(archive.get("original"), dict) else {}
        title = str(photo.get("title") or "").strip()
        photo_id = str(photo.get("id") or photo.get("photo_uuid") or "").strip()
        times = archive.get("times") if isinstance(archive.get("times"), dict) else {}
        confirmed = str(times.get("confirmed_capture") or photo.get("photo_date") or "").strip()
        uploaded = str(times.get("uploaded_at") or photo.get("upload_time") or "").strip()
        if uploaded and confirmed and uploaded[:10] == confirmed[:10] and str(times.get("exif_original") or "") == "":
            pass
        if not confirmed:
            issues.append({"severity": "medium", "photo_id": photo_id, "message": "缺少人员确认的拍摄日期。上传时间不能代替拍摄日期。"})
        if not str(archive.get("location_text") or "").strip() and not str((archive.get("gps") or {}).get("manual_place") or "").strip():
            issues.append({"severity": "medium", "photo_id": photo_id, "message": "缺少地点。GPS 拒绝时可以手填地点，不能编造坐标。"})
        if not str(photo.get("photographer") or "").strip():
            issues.append({"severity": "medium", "photo_id": photo_id, "message": "缺少拍摄者。"})
        if not title:
            issues.append({"severity": "low", "photo_id": photo_id, "message": "题名仍为空，导出前需要人工确认。"})
        status = str(original.get("status") or "")
        if status == "preserved" and original.get("sha256"):
            originals += 1
            previous = seen_hash.get(original["sha256"])
            if previous:
                issues.append({"severity": "low", "photo_id": photo_id, "message": f"与 {previous} 摄入哈希相同，只提示，不自动删除。"})
            else:
                seen_hash[original["sha256"]] = photo_id or title
        else:
            issues.append({
                "severity": "high",
                "photo_id": photo_id,
                "message": "缺可归档原片。压缩图、预览和水印图是利用副本，不能标成可归档原片。",
            })
        if archive.get("concealment") == "before_cover":
            concealment_images += 1
            acceptance = archive.get("acceptance") if isinstance(archive.get("acceptance"), dict) else {}
            if not str(acceptance.get("record_no") or acceptance.get("title") or "").strip():
                issues.append({
                    "severity": "high",
                    "code": "GB55032-3.3.4-4",
                    "photo_id": photo_id,
                    "message": CONCEALMENT_TEXT + " 这里还没有关联验收记录。点击合格不能代替验收文件。",
                })
    if expect_concealment and concealment_images == 0:
        issues.append({
            "severity": "high",
            "code": "GB55032-3.3.4-4",
            "message": "隐蔽前没有现场影像。" + CONCEALMENT_CLAUSE + "。" + CONCEALMENT_TEXT,
        })
    note = local_profile_note(local_profile)
    if note:
        issues.append({"severity": "info", "message": note})
    archivable = originals == len(photos) and originals > 0 and not any(item["severity"] == "high" for item in issues)
    result = "预检通过" if not any(item["severity"] == "high" for item in issues) else "预检未通过"
    if not photos:
        result = "预检未通过"
        archivable = False
    return {
        "result": result,
        "archivable": archivable,
        "statement": PRECHECK_STATEMENT,
        "hash_limitation": HASH_LIMITATION_TEXT,
        "transfer_timing": TRANSFER_TIMING_TEXT,
        "photo_count": len(photos),
        "original_count": originals,
        "issues": issues,
    }


def skeleton_rows(project_type: str, contract_name: str = "") -> list[dict]:
    canonical = canonical_project_type(project_type)
    rows = []
    order = 1
    for division in DIVISION_SKELETON[canonical]["divisions"]:
        division_code = f"{subtype_code(canonical)}-{order:02d}"
        item_index = 1
        for item_name in division["items"]:
            rows.append(
                {
                    "合同或标段名称": contract_name,
                    "单位工程名称": canonical,
                    "单位工程编码": subtype_code(canonical),
                    "子单位工程名称": "",
                    "子单位工程编码": "",
                    "分部工程名称": division["name"],
                    "分部工程编码": division_code,
                    "子分部工程名称": "",
                    "子分部工程编码": "",
                    "分项工程名称": item_name,
                    "分项工程编码": f"{division_code}-{item_index:03d}",
                    "关键词": division.get("optional_note") or division.get("note") or "",
                }
            )
            item_index += 1
        order += 1
    return rows
