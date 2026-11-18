# -*- coding: utf-8 -*-
"""公路土建影像规则。质量划分、位置、影像工序和组卷互相独立。

核对资料：交通运输部发布公告，北京市交通委公开 JTG F80/1—2017
扫描本正文第 1、3 页及附录 A 第 141—144 页。不是检验评定引擎。
"""
from __future__ import annotations

import hashlib
import json
import math

INDUSTRY_NAME = "公路工程"
INDUSTRY_CODE = "highway"
RULE_VERSION = "H2026.11-1"
STANDARD = "JTG F80/1—2017"
PROJECT_TYPES = (
    "公路综合土建", "路基工程", "路面工程", "桥梁工程", "涵洞工程",
    "隧道工程", "交通安全设施", "绿化工程", "声屏障工程",
)
INDUSTRY_ALIASES = {"公路", INDUSTRY_NAME, INDUSTRY_CODE}
SCOPE_TEXT = (
    "本版按 JTG F80/1—2017 支持各等级公路新建与改扩建的土建工程划分。"
    "工程类型是软件检索分类，不等于单位工程层级；涵洞通常归路基工程内，"
    "特大斜拉桥、特大悬索桥须核对附录 A 表 A-2。"
    "交通机电、房屋附属设施、养护工程不直接套用本版土建规则，应核对各自适用标准。"
)
DIVISION_NOTICE = (
    "按第 3.1.1、3.1.2 条及附录 A，在施工准备阶段确定单位、分部、分项划分。"
    "合同段是管理范围，不替代质量层级。导入实际批准的划分及原编码，软件不自动生成、"
    "重排或强制某种全国统一编码，也不将照片清单生成质量划分。"
    "附录 A 对小桥及达到小桥标准的通道按座或处划分分部，涵洞、砌筑防护按路段，"
    "排水还要结合数量、特点和施工程序。各行条件须按对应适用范围核对，"
    "软件不将某个示例长度作为全部工程的固定限值。"
)
PHOTO_NOTICE = (
    "第 3.1.3 条要求隐蔽工程在隐蔽前检查合格，不等于规定了全国统一照片张数或拍摄方向。"
    "拍摄内容、方向、频次及资料关联按适用专项规范、合同和项目影像方案配置；"
    "本版不预置未经核验的强制拍摄清单，照片不代替检验记录及签认。"
)
PRECHECK_STATEMENT = "本检查仅核对软件影像资料完整性，不等于公路工程质量检验评定合格、档案验收通过或已经移交。"
HASH_LIMITATION_TEXT = "哈希只核对文件字节一致性，不证明现场事实、拍摄时间、位置或坐标真实。"
TRANSFER_TIMING_TEXT = "公路项目归档范围、组卷和移交时间按适用公路档案规定及项目接收要求核定，不套用城建档案时限。"
IMPORT_HEADERS = (
    "合同或标段名称", "单位工程名称", "单位工程编码", "分部工程名称", "分部工程编码",
    "子分部工程名称", "子分部工程编码", "分项工程名称", "分项工程编码",
    "起点桩号", "终点桩号", "左右幅", "结构部位", "划分依据", "备注",
)
REQUIRED_HEADERS = ("单位工程名称", "单位工程编码", "分部工程名称", "分部工程编码", "分项工程名称", "分项工程编码")
SOURCES = (
    {"title": "交通运输部公告 2017 年第 62 号", "url": "https://xxgk.mot.gov.cn/jigou/glj/202006/t20200623_3312669.html", "scope": "标准发布，自 2018-05-01 施行"},
    {"title": "北京市交通委公开 JTG F80/1—2017 全文", "url": "https://jtw.beijing.gov.cn/yhyshj/bzgf/202111/P020211101360311553635.pdf", "scope": "第 1.0.2、3.1.1—3.1.3 条及附录 A"},
    {"title": "国家标准馆 JTG F80/1-2017", "url": "https://www.ndls.org.cn/standard/detail/6f2d7f3a125c1a68d34437d6b53bacdd", "scope": "适用范围与标准信息核对"},
)


class HighwayRuleError(ValueError):
    def __init__(self, code, message, errors=None):
        self.code = code
        self.errors = list(errors or [])
        super().__init__(message)


def is_highway_name(value):
    return str(value or "").strip() in INDUSTRY_ALIASES


def canonical_project_type(value):
    name = str(value or "").strip()
    if not name:
        raise HighwayRuleError("project_type_required", "请选择公路土建工程类型。")
    if name not in PROJECT_TYPES:
        raise HighwayRuleError("unsupported_project_type", "未支持的公路类型；机电、养护和房屋附属设施不能直接套用公路土建规则。")
    return name


def preserve_code_text(value):
    """不编号、不补零；Excel 数字已丢失的前导零无法猜测恢复。"""
    if value is None:
        return ""
    if isinstance(value, float):
        if not math.isfinite(value):
            return ""
        if value.is_integer():
            return str(int(value))
    return str(value)


def division_identity(fields):
    """完整原码路径。名称修订不改变身份，代码不清洗、不截断、不折叠大小写。

    应传入 validate_import_records 规范化后的字段；空子分部保留占位，
    避免拼接分隔符或缺失层级导致路径碰撞。
    """
    return tuple(preserve_code_text(fields.get(key)) for key in (
        "合同或标段名称", "单位工程编码", "分部工程编码", "子分部工程编码", "分项工程编码",
    ))


def storage_code(fields, engineering_project_id):
    """仅内部目录身份使用的稳定 ID，不替代或修改批准编码。

    JSON 固定结构/编码/分隔规则；不包含可编辑的工程名称或规则版本。
    SHA-256 截取 128 位，生成跨平台安全且有界的目录名。
    """
    payload = {"engineering_project_id": preserve_code_text(engineering_project_id),
               "division_identity": division_identity(fields)}
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "GL-" + hashlib.sha256(encoded).hexdigest()[:32]


def validate_import_records(records):
    """纯函数整批预检，出错不返回部分记录；调用方通过后才能写入。

    名称和编码必填是软件定位照片的输入要求，不声称规范规定编码格式。
    子分部不是全国默认层级，只有项目明确依据时作为扩展保留。
    """
    normalized, errors = [], []
    item_paths = set()
    identities = {}
    for row_number, raw in enumerate(records or [], start=2):
        if not isinstance(raw, dict):
            errors.append({"row": row_number, "message": "记录必须是字段表。"})
            continue
        fields = {str(k or "").strip().lstrip("\ufeff").replace(" ", ""): preserve_code_text(v) for k, v in raw.items() if k}
        if not any(value.strip() for value in fields.values()):
            continue
        for level in ("单位", "分部", "子分部", "分项"):
            alias = level + "工程编号"
            canonical = level + "工程编码"
            if fields.get(alias) and fields.get(canonical) and fields[alias] != fields[canonical]:
                errors.append({"row": row_number, "message": f"{alias}与{canonical}不一致。"})
            if not fields.get(canonical) and fields.get(alias):
                fields[canonical] = fields[alias]
        if any(k.startswith("单元工程") for k in fields):
            errors.append({"row": row_number, "message": "不能把水利单元工程字段当作公路分项工程，请提供公路批准划分表。"})
        if any(fields.get(k) for k in ("子单位工程名称", "子单位工程编码", "子分项工程名称", "子分项工程编码")):
            errors.append({"row": row_number, "message": "本版未支持子单位或子分项扩展，请核定映射后再导入，不能静默压平。"})
        missing = [key for key in REQUIRED_HEADERS if not fields.get(key, "").strip()]
        if missing:
            errors.append({"row": row_number, "message": "缺少：" + "、".join(missing)})
        if fields.get("子分部工程名称") or fields.get("子分部工程编码"):
            if not all(fields.get(k, "").strip() for k in ("子分部工程名称", "子分部工程编码", "划分依据")):
                errors.append({"row": row_number, "message": "子分部是项目扩展，请成对填写名称、编码并注明划分依据。"})
        code = fields.get("分项工程编码", "")
        path = division_identity(fields)
        if code and path in item_paths:
            errors.append({"row": row_number, "message": "合同、单位、分部、子分部及分项原码完整路径重复，请核对划分表；不同父路径允许使用相同分项原码。"})
        item_paths.add(path)
        # 同一父级内相同编码不得静默对应两个名称；不同父级允许局部编号相同。
        parent = (fields.get("合同或标段名称", ""),)
        for level in ("单位", "分部", "子分部"):
            c, n = fields.get(level + "工程编码", ""), fields.get(level + "工程名称", "")
            if c:
                key = parent + (level, c)
                if key in identities and identities[key] != n:
                    errors.append({"row": row_number, "message": f"同一上级的{level}工程编码对应不同名称。"})
                identities[key] = n
                parent = key
        fields.update({"节点类型": "item", "工程专业": INDUSTRY_NAME})
        normalized.append(fields)
    if not normalized and not errors:
        errors.append({"row": 0, "message": "没有可导入的公路分项记录。"})
    if errors:
        message = "公路划分预检未通过：" + "；".join(f"第{e['row']}行：{e['message']}" if e['row'] else e['message'] for e in errors)
        raise HighwayRuleError("invalid_division", message, errors)
    return normalized


def template_document():
    return {
        "industry": INDUSTRY_NAME, "industry_code": INDUSTRY_CODE, "rule_version": RULE_VERSION,
        "standard": STANDARD, "project_types": list(PROJECT_TYPES),
        "hierarchy": ["单位工程", "分部工程", "分项工程"],
        "management_level": "合同或标段", "optional_project_extension": "子分部工程（须注明项目划分依据）",
        "import_headers": list(IMPORT_HEADERS), "required_headers": list(REQUIRED_HEADERS),
        "scope": SCOPE_TEXT, "division_notice": DIVISION_NOTICE, "photo_notice": PHOTO_NOTICE,
        "checklist_status": "project_config", "requirements": [], "sources": [dict(s) for s in SOURCES],
        "precheck_statement": PRECHECK_STATEMENT, "hash_limitation": HASH_LIMITATION_TEXT,
        "transfer_timing": TRANSFER_TIMING_TEXT,
    }


def precheck_photos(photos, *, expect_concealment=False, local_profile=""):
    issues, originals, seen, before_cover = [], 0, {}, 0
    for photo in photos:
        archive = photo.get("archive") if isinstance(photo.get("archive"), dict) else {}
        original = archive.get("original") if isinstance(archive.get("original"), dict) else {}
        times = archive.get("times") if isinstance(archive.get("times"), dict) else {}
        gps = archive.get("gps") if isinstance(archive.get("gps"), dict) else {}
        photo_id = str(photo.get("id") or photo.get("photo_uuid") or "")
        def issue(severity, message):
            issues.append({"severity": severity, "photo_id": photo_id, "message": message})
        if not str(times.get("confirmed_capture") or photo.get("photo_date") or "").strip():
            issue("medium", "缺少人员确认的拍摄日期，上传时间不能代替拍摄日期。")
        if not str(archive.get("location_text") or gps.get("manual_place") or "").strip():
            issue("medium", "缺少地点或桩号、结构部位说明，请核实填写，不编造坐标。")
        if not str(photo.get("photographer") or "").strip():
            issue("medium", "缺少拍摄者。")
        if not str(photo.get("title") or "").strip():
            issue("low", "缺少题名，请人工确认。")
        digest = str(original.get("sha256") or "").strip()
        if original.get("status") == "preserved" and digest:
            originals += 1
            if digest in seen:
                issue("low", "与另一照片摄入哈希相同，仅提示，不自动删除。")
            seen[digest] = photo_id
        else:
            issue("high", "缺少保留原片或摄入哈希；预览、压缩和水印副本不能冒充原片。")
        if archive.get("concealment") == "before_cover":
            before_cover += 1
            acceptance = archive.get("acceptance") if isinstance(archive.get("acceptance"), dict) else {}
            if not (acceptance.get("record_no") or acceptance.get("title")):
                issue("medium", "该影像标为隐蔽前，但未关联检查记录。请按项目要求补充；照片本身不证明检查合格。")
    if expect_concealment and not before_cover:
        issues.append({"severity": "high", "message": "项目要求核查隐蔽前影像，但本次资料没有该标记；此项为项目核查条件，不是全国统一拍摄张数要求。"})
    if local_profile:
        issues.append({"severity": "info", "message": "尚未自动验证指定地方或接收单位规则，请人工核对：" + str(local_profile)})
    passed = bool(photos) and not any(i["severity"] == "high" for i in issues)
    return {"result": "预检通过" if passed else "预检未通过", "archivable": passed and originals == len(photos),
            "statement": PRECHECK_STATEMENT, "hash_limitation": HASH_LIMITATION_TEXT,
            "transfer_timing": TRANSFER_TIMING_TEXT, "photo_count": len(photos), "original_count": originals, "issues": issues}
