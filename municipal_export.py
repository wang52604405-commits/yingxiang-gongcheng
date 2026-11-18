# -*- coding: utf-8 -*-
"""市政照片组、目录和预检包。照片组不替代工程划分树。"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import zipfile
from pathlib import Path

import municipal_rules


def _groups_path(data_dir: Path, project_id: str) -> Path:
    return Path(data_dir) / "archive_groups" / f"{project_id}.json"


def read_groups(data_dir: Path, project_id: str) -> dict:
    path = _groups_path(data_dir, project_id)
    if not path.exists():
        return {"groups": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"groups": []}
    groups = data.get("groups") if isinstance(data, dict) else []
    return {"groups": groups if isinstance(groups, list) else []}


def write_groups(data_dir: Path, project_id: str, data: dict) -> dict:
    path = _groups_path(data_dir, project_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"groups": data.get("groups") if isinstance(data.get("groups"), list) else []}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def upsert_group(data_dir: Path, project_id: str, group_id: str, title: str, photo_refs: list[dict]) -> dict:
    data = read_groups(data_dir, project_id)
    groups = [item for item in data["groups"] if str(item.get("id") or "") != group_id]
    groups.append(
        {
            "id": group_id,
            "title": str(title or "照片组").strip()[:80] or "照片组",
            "photo_refs": photo_refs,
        }
    )
    return write_groups(data_dir, project_id, {"groups": groups})


def _catalog_row(photo: dict, leaf: dict) -> list[str]:
    archive = photo.get("archive") if isinstance(photo.get("archive"), dict) else {}
    times = archive.get("times") if isinstance(archive.get("times"), dict) else {}
    spatial = photo.get("spatial") if isinstance(photo.get("spatial"), dict) else {}
    original = archive.get("original") if isinstance(archive.get("original"), dict) else {}
    acceptance = archive.get("acceptance") if isinstance(archive.get("acceptance"), dict) else {}
    return [
        str(photo.get("photo_uuid") or ""),
        str(photo.get("id") or ""),
        str(photo.get("title") or ""),
        str(times.get("confirmed_capture") or photo.get("photo_date") or ""),
        str(times.get("exif_original") or ""),
        str(times.get("uploaded_at") or photo.get("upload_time") or ""),
        str(photo.get("photographer") or ""),
        str(archive.get("location_text") or ""),
        str(archive.get("phase") or ""),
        str(archive.get("concealment") or ""),
        str(archive.get("process_event") or photo.get("process_name") or ""),
        str(archive.get("template_code") or ""),
        str(leaf.get("batch_code") or leaf.get("item_code") or leaf.get("unit_code") or ""),
        str(leaf.get("batch_name") or leaf.get("item_name") or leaf.get("unit_name") or ""),
        json.dumps(spatial, ensure_ascii=False),
        str(acceptance.get("record_no") or ""),
        str(original.get("status") or ""),
        str(original.get("sha256") or ""),
        str(original.get("size_bytes") or ""),
        str(original.get("warning") or ""),
        str(leaf.get("contract_name") or ""),
        str(leaf.get("unit_project_code") or ""),
        str(leaf.get("part_code") or ""),
        str(leaf.get("sub_part_code") or ""),
        str(leaf.get("item_code") or ""),
        str(leaf.get("batch_code") or ""),
        str(photo.get("project_code") or ""),
    ]


CATALOG_HEADERS = [
    "照片UUID",
    "显示编号",
    "题名",
    "确认拍摄日期",
    "EXIF原值",
    "上传时间",
    "拍摄者",
    "地点",
    "阶段",
    "隐蔽状态",
    "工序事件",
    "模板编号",
    "划分编码",
    "划分名称",
    "空间定位",
    "验收记录号",
    "原件状态",
    "摄入哈希",
    "摄入字节",
    "原件警告",
    "合同或标段", "单位工程编码", "分部工程编码", "子分部工程编码", "分项工程编码", "检验批编码", "内部归档标识",
]


def build_package(group_title: str, photos: list[dict], originals: dict[str, bytes], *, expect_concealment: bool = False, local_profile: str = "", rules=municipal_rules) -> bytes:
    """originals 的键是 photo_uuid，值必须是摄入原字节。压缩预览不得放进原片目录。"""
    report = rules.precheck_photos(
        photos, expect_concealment=expect_concealment, local_profile=local_profile
    )
    used = set()
    manifest_files = []
    catalog = io.StringIO()
    writer = csv.writer(catalog)
    writer.writerow(CATALOG_HEADERS)
    memory = io.BytesIO()
    with zipfile.ZipFile(memory, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for photo in photos:
            archive = photo.get("archive") if isinstance(photo.get("archive"), dict) else {}
            original = archive.get("original") if isinstance(archive.get("original"), dict) else {}
            leaf = photo.get("leaf") if isinstance(photo.get("leaf"), dict) else {}
            writer.writerow(_catalog_row(photo, leaf))
            photo_uuid = str(photo.get("photo_uuid") or "")
            raw = originals.get(photo_uuid)
            status = str(original.get("status") or "")
            recorded = str(original.get("sha256") or "")
            if status == "preserved" and raw:
                digest = hashlib.sha256(raw).hexdigest()
                if recorded and digest != recorded:
                    report["issues"].append({
                        "severity": "high",
                        "photo_id": photo_uuid,
                        "message": "包内字节与摄入哈希不一致，不能标成可归档原片。",
                    })
                    report["result"] = "预检未通过"
                    report["archivable"] = False
                    continue
                filename = municipal_rules.unique_export_name(
                    original.get("filename") or f"{photo_uuid}.jpg", used
                )
                path = f"原片/{filename}"
                bundle.writestr(path, raw)
                manifest_files.append({
                    "role": "original",
                    "path": path,
                    "photo_uuid": photo_uuid,
                    "sha256": digest,
                    "size_bytes": len(raw),
                })
            else:
                report["issues"].append({
                    "severity": "high",
                    "photo_id": photo_uuid,
                    "message": "这张照片没有单独的原件字节，未写入原片目录。",
                })
                report["result"] = "预检未通过"
                report["archivable"] = False
        original_rows = [item for item in manifest_files if item["role"] == "original"]
        if len(original_rows) != report["original_count"] and report["original_count"]:
            report["issues"].append({
                "severity": "high",
                "message": "目录中的可归档原片数量和包内原片数量不一致。",
            })
            report["result"] = "预检未通过"
            report["archivable"] = False
        bundle.writestr("目录.csv", catalog.getvalue().encode("utf-8-sig"))
        bundle.writestr(
            "利用副本/说明.txt",
            "打印相册、水印图和压缩预览是利用副本，不在原片目录，不能当作归档原片。\n".encode("utf-8"),
        )
        manifest = {
            "package_kind": f"{rules.INDUSTRY_CODE}_photo_arrangement",
            "group_title": group_title,
            "rule_version": rules.RULE_VERSION,
            "not_a_transfer": True,
            "not_an_acceptance": True,
            "fonds_number": "",
            "archive_number": "",
            "statement": rules.PRECHECK_STATEMENT,
            "hash_limitation": rules.HASH_LIMITATION_TEXT,
            "transfer_timing": rules.TRANSFER_TIMING_TEXT,
            "catalog_count": len(photos),
            "original_count": len(original_rows),
            "files": manifest_files,
            "precheck": report,
        }
        bundle.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8"))
        bundle.writestr("预检报告.json", json.dumps(report, ensure_ascii=False, indent=2).encode("utf-8"))
    memory.seek(0)
    return memory.getvalue()
