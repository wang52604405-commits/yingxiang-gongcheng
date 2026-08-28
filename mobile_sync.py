# -*- coding: utf-8 -*-
"""桌面端与微信小程序的影像同步。

这个模块只处理本机数据的安全映射：

* 给旧照片惰性补充永久 ``photo_uuid``，写入前备份 metadata；
* 上传完整的工程层级快照；
* 把服务器短期中转的手机 JPEG/PNG 原图幂等导入正确单元；
* 为现有电脑照片生成不超过 100KB 的长期云端预览，永不改写原图。

网络故障在后台静默保留进度，下一个 30 秒周期重试。
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import shutil
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, Iterable, Optional, Tuple

import professional_templates


MAX_PREVIEW_BYTES = 102400
MAX_ORIGINAL_PHOTO_BYTES = 50 * 1024 * 1024
# 旧名仅保留给已有调用方；现在它表示长期云端预览上限，不是原图上限。
MAX_MOBILE_PHOTO_BYTES = MAX_PREVIEW_BYTES
DEFAULT_SYNC_INTERVAL_SECONDS = 30
DEFAULT_INBOX_LIMIT = 50
DEFAULT_BACKFILL_LIMIT = 10
TARGET_PROJECT_DISPLAY_NAME = "邯郸市永年区洺河龙泉缓洪工程"


def _atomic_write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def _timestamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S-%f")


def _canonical_uuid(value) -> str:
    try:
        return str(uuid.UUID(str(value or "").strip()))
    except (ValueError, TypeError, AttributeError):
        return ""


def _engineering_project_identity(project: dict) -> dict:
    project = project if isinstance(project, dict) else {}
    local_project_id = str(project.get("id") or "default").strip() or "default"
    owner_account_id = str(project.get("cloud_owner_id") or "").strip()
    project_ref = str(
        project.get("cloud_project_ref")
        or project.get("project_ref")
        or ""
    ).strip()
    if not project_ref and owner_account_id:
        project_ref = f"{owner_account_id}:{local_project_id}"
    return {
        "local_project_id": local_project_id,
        "owner_account_id": owner_account_id,
        "project_ref": project_ref,
    }


def _new_photo_uuid(seen=None) -> str:
    seen = seen if seen is not None else set()
    while True:
        candidate = str(uuid.uuid4())
        if candidate not in seen:
            return candidate


def _backup_metadata(metadata_path: Path) -> Optional[Path]:
    if not metadata_path.exists():
        return None
    backup_dir = metadata_path.parent / "_mobile_sync_backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    target = backup_dir / f"metadata-before-photo-uuid-{_timestamp()}.json"
    shutil.copy2(metadata_path, target)
    return target


def ensure_project_photo_uuids(manager, project_code: str, seen=None) -> dict:
    """为一个 metadata 中的照片惰性补充稳定 UUID。

    只在确实需要迁移时写文件，并在写入前备份 metadata。照片文件
    不会被打开或改写。
    """
    seen = seen if seen is not None else set()
    with manager._project_write_lock(project_code):
        data = manager._read_metadata(project_code)
        changed = 0
        for photo in data.get("photos", []):
            if not isinstance(photo, dict):
                continue
            current = _canonical_uuid(photo.get("photo_uuid"))
            if not current or current in seen:
                current = _new_photo_uuid(seen)
                photo["photo_uuid"] = current
                changed += 1
            else:
                # 统一 UUID 大小写，不改变其身份。
                if photo.get("photo_uuid") != current:
                    photo["photo_uuid"] = current
                    changed += 1
            seen.add(current)
        backup = None
        if changed:
            backup = _backup_metadata(manager._metadata_path(project_code))
            manager._write_metadata(project_code, data)
        return {
            "project_code": str(project_code),
            "changed": changed,
            "backup": str(backup) if backup else "",
        }


def ensure_all_photo_uuids(manager) -> dict:
    seen = set()
    changed = 0
    backups = []
    for project in manager.list_projects(include_other=True):
        code = str(project.get("project_code") or "").strip()
        if not code:
            continue
        result = ensure_project_photo_uuids(manager, code, seen=seen)
        changed += int(result.get("changed") or 0)
        if result.get("backup"):
            backups.append(result["backup"])
    return {"changed": changed, "backups": backups}


def _node_code(prefix: str, *parts) -> str:
    identity = "|".join(str(part or "").strip() for part in parts)
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}-{digest}"


def _normalize_other_tree(nodes) -> list:
    result = []
    for node in nodes if isinstance(nodes, list) else []:
        if not isinstance(node, dict):
            continue
        code = str(node.get("code") or node.get("node_code") or "").strip()
        if not code:
            continue
        result.append({
            "node_code": code,
            "name": str(node.get("name") or code).strip(),
            "children": _normalize_other_tree(node.get("children") or []),
        })
    return result


def build_project_snapshot(
    manager,
    engineering_project: dict,
    other_images: dict,
    desktop_machine_id: str = "",
) -> dict:
    """构建服务器可事务替换的完整工程快照。"""
    project = engineering_project if isinstance(engineering_project, dict) else {}
    identity = _engineering_project_identity(project)
    project_id = identity["local_project_id"]
    project_payload = {
        "id": project_id,
        "local_project_id": project_id,
        "project_ref": identity["project_ref"],
        "owner_account_id": identity["owner_account_id"],
        "project_name": str(project.get("project_name") or "默认工程").strip(),
        "project_code": str(project.get("project_code") or project_id).strip(),
        "owner": str(project.get("owner") or "").strip(),
        "contractor": str(project.get("contractor") or "").strip(),
        "supervisor": str(project.get("supervisor") or "").strip(),
        "location": str(project.get("location") or "").strip(),
        "start_date": str(project.get("start_date") or "").strip(),
        "description": str(project.get("description") or "").strip(),
        "industry": str(project.get("industry") or "水利工程").strip(),
        "project_type": str(project.get("project_type") or "").strip(),
        "region": str(project.get("region") or "").strip(),
        "template_version": str(
            project.get("template_version")
            or professional_templates.catalog().get("version")
            or "V1.0"
        ).strip(),
    }

    contract_groups: Dict[Tuple[str, str], dict] = {}
    for item in manager.list_projects(include_other=True):
        code = str(item.get("project_code") or "").strip()
        if not code:
            continue
        data = manager.get_project(code)
        fields = data.get("source_fields") or {}
        if fields.get("_other_image"):
            continue
        hierarchy = manager.project_hierarchy(data)
        contract_name = str(hierarchy.get("contract_name") or "").strip()
        if contract_name in {"", "未填写", "未填写合同工程", "默认工程"}:
            contract_name = project_payload["project_name"]
        unit_project_name = hierarchy.get("unit_project_name") or "未分组单位工程"
        unit_project_code = hierarchy.get("unit_project_code") or _node_code(
            "DW", project_id, contract_name, unit_project_name
        )
        part_name = hierarchy.get("part_name") or "未分组分部工程"
        part_code = hierarchy.get("part_code") or _node_code(
            "FB", project_id, contract_name, unit_project_code, part_name
        )
        unit_code = hierarchy.get("unit_code") or data.get("display_project_code") or code
        contract_code = str(fields.get("合同工程编码") or "").strip() or _node_code(
            "HT", project_id, contract_name
        )

        contract_key = (contract_code, contract_name)
        contract = contract_groups.setdefault(contract_key, {
            "code": contract_code,
            "name": contract_name,
            "unit_projects": {},
        })
        unit_key = (unit_project_code, unit_project_name)
        unit_project = contract["unit_projects"].setdefault(unit_key, {
            "code": unit_project_code,
            "name": unit_project_name,
            "parts": {},
        })
        part_key = (part_code, part_name)
        part = unit_project["parts"].setdefault(part_key, {
            "code": part_code,
            "name": part_name,
            "units": [],
        })
        processes = data.get("processes") or []
        if not isinstance(processes, list):
            processes = [part.strip() for part in str(processes).split("、") if part.strip()]
        part["units"].append({
            "unit_code": str(unit_code).strip(),
            "internal_project_code": code,
            "name": str(hierarchy.get("unit_name") or data.get("project_name") or unit_code).strip(),
            "division_type": str(data.get("division_type") or "unit").strip(),
            "processes": [str(value).strip() for value in processes if str(value).strip()],
            "project_order": data.get("project_order"),
        })

    tree = []
    for contract in contract_groups.values():
        unit_projects = []
        for unit_project in contract.pop("unit_projects").values():
            parts = []
            for part in unit_project.pop("parts").values():
                part["units"].sort(key=lambda unit: (
                    int(unit.get("project_order")) if str(unit.get("project_order") or "").isdigit() else 10**12,
                    unit.get("unit_code", ""),
                ))
                for unit in part["units"]:
                    unit.pop("project_order", None)
                parts.append(part)
            unit_project["parts"] = parts
            unit_projects.append(unit_project)
        contract["unit_projects"] = unit_projects
        tree.append(contract)

    body = {
        "desktop_machine_id": str(desktop_machine_id or "").strip(),
        "project": project_payload,
        "tree": tree,
        "other_tree": _normalize_other_tree((other_images or {}).get("nodes") or []),
        "requirements": professional_templates.requirements(
            project_payload.get("industry", "水利工程"),
            project_payload.get("project_type", ""),
        ),
        "requirement_summary": professional_templates.plan_summary(
            project_payload.get("industry", "水利工程"),
            project_payload.get("project_type", ""),
        ),
    }
    content_hash = hashlib.sha256(
        json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return {
        "snapshot_id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"engineering-image:{project_id}:{content_hash}")),
        # 真正的单调整数 revision 由 DesktopMobileSync 结合本地已同步
        # 状态填入；内容哈希仅用于判断层级是否改变。
        "revision": 0,
        "_content_hash": content_hash,
        **body,
    }


def _validate_preview_jpeg(raw: bytes, expected_sha256: str = "") -> dict:
    if not raw or len(raw) > MAX_PREVIEW_BYTES:
        raise ValueError("云端预览图必须为 1~102400 字节")
    actual_sha256 = hashlib.sha256(raw).hexdigest()
    expected = str(expected_sha256 or "").strip().lower()
    if expected and actual_sha256 != expected:
        raise ValueError("云端预览图完整性校验失败")
    from PIL import Image, ImageOps

    with Image.open(io.BytesIO(raw)) as image:
        if image.format != "JPEG":
            raise ValueError("云端预览图不是 JPEG")
        image.verify()
    with Image.open(io.BytesIO(raw)) as image:
        exif_orientation = int(image.getexif().get(0x0112) or 1)
        displayed = ImageOps.exif_transpose(image)
        displayed.load()
        width, height = displayed.size
    return {
        "sha256": actual_sha256,
        "width": width,
        "height": height,
        "exif_orientation": exif_orientation if 1 <= exif_orientation <= 8 else 1,
    }


def _validate_original_image(
    raw: bytes,
    expected_sha256: str,
    expected_size: int = 0,
    claimed_mime: str = "",
    max_bytes: int = MAX_ORIGINAL_PHOTO_BYTES,
) -> dict:
    limit = max(1, min(MAX_ORIGINAL_PHOTO_BYTES, int(max_bytes or MAX_ORIGINAL_PHOTO_BYTES)))
    if not raw or len(raw) > limit:
        raise ValueError(f"手机原图必须为 1~{limit} 字节")
    try:
        claimed_size = int(expected_size or 0)
    except (TypeError, ValueError):
        raise ValueError("手机原图大小字段无效")
    if claimed_size <= 0:
        raise ValueError("手机原图缺少有效大小")
    if claimed_size != len(raw):
        raise ValueError("手机原图大小校验失败")
    expected = str(expected_sha256 or "").strip().lower()
    if not re.fullmatch(r"[0-9a-f]{64}", expected):
        raise ValueError("手机原图缺少有效 SHA-256")
    actual = hashlib.sha256(raw).hexdigest()
    if actual != expected:
        raise ValueError("手机原图完整性校验失败")

    from PIL import Image, ImageOps

    with Image.open(io.BytesIO(raw)) as image:
        image_format = str(image.format or "").upper()
        if image_format not in {"JPEG", "PNG"}:
            raise ValueError("手机原图只支持静态 JPEG/PNG")
        if getattr(image, "is_animated", False):
            raise ValueError("手机原图不支持动图")
        image.verify()
    with Image.open(io.BytesIO(raw)) as image:
        exif_orientation = int(image.getexif().get(0x0112) or 1)
        displayed = ImageOps.exif_transpose(image)
        displayed.load()
        width, height = displayed.size
    mime_type = "image/jpeg" if image_format == "JPEG" else "image/png"
    claimed = str(claimed_mime or "").strip().lower()
    if claimed and claimed not in {mime_type, "image/jpg" if mime_type == "image/jpeg" else mime_type}:
        raise ValueError("手机原图类型与文件内容不一致")
    return {
        "sha256": actual,
        "size_bytes": len(raw),
        "width": width,
        "height": height,
        "exif_orientation": exif_orientation if 1 <= exif_orientation <= 8 else 1,
        "mime_type": mime_type,
        "extension": ".jpg" if image_format == "JPEG" else ".png",
    }


def _validate_existing_original_path(
    path: Path,
    expected_sha256: str,
    expected_size: int,
    claimed_mime: str = "",
    max_bytes: int = MAX_ORIGINAL_PHOTO_BYTES,
) -> dict:
    """流式核验已归档原图；不因 metadata 中存在 UUID 就推定文件安全。"""
    path = Path(path)
    limit = max(1, min(MAX_ORIGINAL_PHOTO_BYTES, int(max_bytes or MAX_ORIGINAL_PHOTO_BYTES)))
    expected = str(expected_sha256 or "").strip().lower()
    if not re.fullmatch(r"[0-9a-f]{64}", expected):
        raise ValueError("本地手机原图缺少有效 SHA-256")
    try:
        size = int(expected_size or 0)
    except (TypeError, ValueError):
        raise ValueError("本地手机原图大小字段无效")
    if size <= 0 or size > limit:
        raise ValueError("本地手机原图大小超出允许范围")
    if not path.is_file() or path.is_symlink():
        raise ValueError("本地手机原图文件不存在")
    if path.stat().st_size != size:
        raise ValueError("本地手机原图大小与服务器记录不一致")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while True:
            block = stream.read(1024 * 1024)
            if not block:
                break
            digest.update(block)
    if digest.hexdigest() != expected:
        raise ValueError("本地手机原图 SHA-256 与服务器记录不一致")

    from PIL import Image, ImageOps

    with Image.open(path) as image:
        image_format = str(image.format or "").upper()
        if image_format not in {"JPEG", "PNG"} or getattr(image, "is_animated", False):
            raise ValueError("本地手机原图不是静态 JPEG/PNG")
        image.verify()
    with Image.open(path) as image:
        exif_orientation = int(image.getexif().get(0x0112) or 1)
        displayed = ImageOps.exif_transpose(image)
        displayed.load()
        width, height = displayed.size
    mime_type = "image/jpeg" if image_format == "JPEG" else "image/png"
    claimed = str(claimed_mime or "").strip().lower()
    if claimed == "image/jpg":
        claimed = "image/jpeg"
    if claimed and claimed != mime_type:
        raise ValueError("本地手机原图格式与服务器记录不一致")
    suffix = path.suffix.lower()
    if image_format == "JPEG" and suffix not in {".jpg", ".jpeg"}:
        raise ValueError("本地 JPEG 原图扩展名不一致")
    if image_format == "PNG" and suffix != ".png":
        raise ValueError("本地 PNG 原图扩展名不一致")
    # 解码期间若文件被其它进程替换/改写，最终摘要必须仍与服务器一致。
    if path.stat().st_size != size:
        raise ValueError("本地手机原图在校验期间发生变化")
    final_digest = hashlib.sha256()
    with path.open("rb") as stream:
        while True:
            block = stream.read(1024 * 1024)
            if not block:
                break
            final_digest.update(block)
    if final_digest.hexdigest() != expected:
        raise ValueError("本地手机原图在校验期间发生变化")
    return {
        "sha256": expected,
        "size_bytes": size,
        "width": width,
        "height": height,
        "exif_orientation": exif_orientation if 1 <= exif_orientation <= 8 else 1,
        "mime_type": mime_type,
        "extension": ".jpg" if image_format == "JPEG" else ".png",
    }


def _encode_jpeg_under_budget(image, max_bytes: int = MAX_PREVIEW_BYTES) -> bytes:
    """最长边 1920 起步，优先保留可用的最高 JPEG 质量。"""
    from PIL import Image

    if image.mode not in {"RGB", "L"}:
        if "A" in image.getbands():
            background = Image.new("RGB", image.size, "white")
            background.paste(image, mask=image.getchannel("A"))
            image = background
        else:
            image = image.convert("RGB")
    if max(image.size) > 1920:
        image.thumbnail((1920, 1920), Image.LANCZOS)
    working = image
    while True:
        def encoded(quality: int) -> bytes:
            output = io.BytesIO()
            working.save(
                output,
                "JPEG",
                quality=quality,
                optimize=True,
                progressive=True,
                subsampling=2,
            )
            return output.getvalue()

        low_payload = encoded(30)
        if len(low_payload) <= max_bytes:
            best = low_payload
            low, high = 31, 90
            while low <= high:
                middle = (low + high) // 2
                candidate = encoded(middle)
                if len(candidate) <= max_bytes:
                    best = candidate
                    low = middle + 1
                else:
                    high = middle - 1
            return best
        if max(working.size) <= 320:
            raise ValueError("无法在不超过 100KB 的前提下生成 JPEG 预览")
        resized = working.copy()
        resized.thumbnail(
            (max(240, int(working.width * 0.85)), max(240, int(working.height * 0.85))),
            Image.LANCZOS,
        )
        if resized.size == working.size:
            raise ValueError("无法继续压缩 JPEG 查看副本")
        working = resized


def prepare_jpeg_view_copy(source: Path, cache_dir: Path) -> dict:
    """生成长期云端预览；若原文件已是 <=100KB JPEG，直接复用。"""
    source = Path(source)
    stat = source.stat()
    from PIL import Image, ImageOps

    with Image.open(source) as opened:
        source_format = opened.format
        width, height = opened.size
        exif_orientation = int(opened.getexif().get(0x0112) or 1)
        opened.verify()
    if (
        source_format == "JPEG"
        and 0 < stat.st_size <= MAX_PREVIEW_BYTES
        and max(width, height) <= 1920
    ):
        raw_sha = hashlib.sha256(source.read_bytes()).hexdigest()
        return {
            "path": source,
            "sha256": raw_sha,
            "size_bytes": stat.st_size,
            "width": width,
            "height": height,
            "exif_orientation": exif_orientation if 1 <= exif_orientation <= 8 else 1,
            "reused_source": True,
        }

    key = hashlib.sha256(
        f"{source.resolve()}|{stat.st_mtime_ns}|{stat.st_size}|jpeg100k-v2".encode("utf-8")
    ).hexdigest()
    cache_dir.mkdir(parents=True, exist_ok=True)
    target = cache_dir / f"{key}.jpg"
    if not target.exists():
        with Image.open(source) as opened:
            image = ImageOps.exif_transpose(opened)
            image.load()
            raw = _encode_jpeg_under_budget(image)
        temporary = target.with_suffix(".jpg.tmp")
        temporary.write_bytes(raw)
        os.replace(temporary, target)
    raw = target.read_bytes()
    details = _validate_preview_jpeg(raw)
    return {
        "path": target,
        "sha256": details["sha256"],
        "size_bytes": len(raw),
        "width": details["width"],
        "height": details["height"],
        "exif_orientation": 1,
        "reused_source": False,
    }


def _iso_local_time(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if "T" in text:
        return text
    match = re.match(r"^(20\d{2}-\d{2}-\d{2})\s+(\d{2}:\d{2}:\d{2})$", text)
    return f"{match.group(1)}T{match.group(2)}+08:00" if match else text


def update_engineering_project_display_name(
    engineering_projects_path,
    project_info_path,
    new_name: str = TARGET_PROJECT_DISPLAY_NAME,
    project_id: str = "default",
    expected_current_name: str = "",
    dry_run: bool = False,
) -> dict:
    """显式、可备份地更新当前工程显示名。

    函数从不在导入或测试时自动运行；调用者必须显式传入文件路径。
    ``dry_run=True`` 只返回变更预览，不创建备份也不写入。
    """
    projects_path = Path(engineering_projects_path)
    info_path = Path(project_info_path)
    desired = str(new_name or "").strip()
    if not desired:
        raise ValueError("工程显示名不能为空")
    info = {}
    if info_path.exists():
        raw_info = json.loads(info_path.read_text(encoding="utf-8"))
        info = raw_info if isinstance(raw_info, dict) else {}
    projects_existed = projects_path.exists()
    if projects_existed:
        projects = json.loads(projects_path.read_text(encoding="utf-8"))
        if not isinstance(projects, dict) or not isinstance(projects.get("projects"), list):
            raise ValueError("工程元数据格式不正确")
        target = next(
            (item for item in projects["projects"] if isinstance(item, dict) and str(item.get("id")) == str(project_id)),
            None,
        )
        if target is None:
            raise ValueError(f"找不到工程：{project_id}")
    else:
        # 早期资料目录只有 albums，尚未生成工程根元数据。显式调用本
        # 函数时可安全创建根记录；dry-run 仍完全不写盘。
        target = {
            "id": str(project_id),
            "project_name": str(info.get("project_name") or "默认工程").strip(),
            "project_code": str(info.get("project_code") or project_id).strip(),
            "owner": str(info.get("owner") or "").strip(),
            "contractor": str(info.get("contractor") or "").strip(),
            "supervisor": str(info.get("supervisor") or "").strip(),
            "location": str(info.get("location") or "").strip(),
            "start_date": str(info.get("start_date") or "").strip(),
            "description": str(info.get("description") or "").strip(),
        }
        projects = {"active_id": str(project_id), "projects": [target]}
    before = str(target.get("project_name") or "").strip()
    if expected_current_name and before != str(expected_current_name).strip():
        raise ValueError("工程名称已发生变化，为避免覆盖已取消更新")
    if before == desired:
        return {"ok": True, "changed": False, "before": before, "after": desired, "dry_run": dry_run}

    target["project_name"] = desired
    info["project_name"] = desired
    preview = {
        "ok": True,
        "changed": True,
        "before": before,
        "after": desired,
        "dry_run": dry_run,
        "engineering_projects_existed": projects_existed,
    }
    if dry_run:
        return preview

    backup_dir = projects_path.parent / "mobile-sync-backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = _timestamp()
    project_backup = backup_dir / f"{projects_path.stem}-{stamp}{projects_path.suffix}"
    if projects_existed:
        shutil.copy2(projects_path, project_backup)
    else:
        project_backup = None
    info_backup = None
    if info_path.exists():
        info_backup = backup_dir / f"{info_path.stem}-{stamp}{info_path.suffix}"
        shutil.copy2(info_path, info_backup)
    _atomic_write_json(projects_path, projects)
    _atomic_write_json(info_path, info)
    preview.update({
        "project_backup": str(project_backup) if project_backup else "",
        "project_info_backup": str(info_backup) if info_backup else "",
    })
    return preview


class DesktopMobileSync:
    """单进程单实例桌面同步器。"""

    def __init__(
        self,
        manager,
        cloud,
        engineering_project_reader: Callable[[], dict],
        other_images_reader: Callable[[], dict],
        state_path,
        cache_dir,
        interval_seconds: int = DEFAULT_SYNC_INTERVAL_SECONDS,
        inbox_limit: int = DEFAULT_INBOX_LIMIT,
        backfill_limit: int = DEFAULT_BACKFILL_LIMIT,
        machine_id_reader: Optional[Callable[[], str]] = None,
    ):
        self.manager = manager
        self.cloud = cloud
        self.engineering_project_reader = engineering_project_reader
        self.other_images_reader = other_images_reader
        self.state_path = Path(state_path)
        self.cache_dir = Path(cache_dir)
        self.interval_seconds = max(5, int(interval_seconds or DEFAULT_SYNC_INTERVAL_SECONDS))
        self.inbox_limit = max(1, min(100, int(inbox_limit or DEFAULT_INBOX_LIMIT)))
        self.backfill_limit = max(1, int(backfill_limit or DEFAULT_BACKFILL_LIMIT))
        self.machine_id_reader = machine_id_reader or (lambda: "")
        self._state_lock = threading.Lock()
        self._cycle_lock = threading.Lock()
        self._start_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread = None
        self._startup_snapshot_pending = True
        self._active_state_identity = ""
        self.last_result = {"ok": True, "state": "idle"}

    def _cloud_account_id(self) -> str:
        reader = getattr(self.cloud, "desktop_sync_account_id", None)
        try:
            return str(reader() or "").strip() if callable(reader) else ""
        except Exception:
            return ""

    def _cloud_generation(self) -> str:
        reader = getattr(self.cloud, "desktop_sync_generation", None)
        try:
            return str(reader() or "").strip() if callable(reader) else ""
        except Exception:
            return ""

    def _project_ownership_status(self) -> dict:
        account_id = self._cloud_account_id()
        project = self.engineering_project_reader() or {}
        identity = _engineering_project_identity(project)
        owner_id = str(project.get("cloud_owner_id") or "").strip()
        if not account_id:
            return {
                "ok": False,
                "code": "account_identity_required",
                "error": "请重新登录云账号以建立稳定账号编号",
                "account_id": "",
                "owner_id": owner_id,
                **identity,
            }
        if not owner_id:
            return {
                "ok": False,
                "code": "project_owner_unclaimed",
                "error": "当前本地工程尚未绑定云账号，请先确认归属",
                "account_id": account_id,
                "owner_id": "",
                **identity,
            }
        if owner_id != account_id:
            return {
                "ok": False,
                "code": "project_owner_mismatch",
                "error": "当前本地工程属于另一云账号，已停止同步以防串号",
                "account_id": account_id,
                "owner_id": owner_id,
                **identity,
            }
        return {
            "ok": True,
            "account_id": account_id,
            "owner_id": owner_id,
            "project_id": identity["local_project_id"],
            **identity,
        }

    def _state_identity(self) -> str:
        identity_reader = getattr(self.cloud, "desktop_sync_identity", None)
        try:
            account_identity = str(identity_reader() or "").strip() if callable(identity_reader) else ""
        except Exception:
            account_identity = ""
        machine_identity = self._desktop_machine_id() or "unknown-machine"
        # 未登录状态也使用独立分区，绝不能看到上一个账号的 pending。
        return f"{account_identity or '__logged_out__'}|{machine_identity}"

    @staticmethod
    def _normalized_scope_state(data: dict, identity: str) -> dict:
        state = dict(data) if isinstance(data, dict) else {}
        state["version"] = 2
        state["account_identity"] = identity
        state.setdefault("inbox_cursor", "")
        state.setdefault("snapshot_revision", "")
        state.setdefault("backfill_paused", False)
        if not isinstance(state.get("backfilled"), dict):
            state["backfilled"] = {}
        if not isinstance(state.get("backfill_errors"), dict):
            state["backfill_errors"] = {}
        if not isinstance(state.get("ack_pending"), dict):
            state["ack_pending"] = {}
        if not isinstance(state.get("cleanup_pending"), dict):
            state["cleanup_pending"] = {}
        if not isinstance(state.get("delete_pending"), dict):
            state["delete_pending"] = {}
        # v1 初版只记录 cleanup_pending。它同样代表服务器尚未完成
        # ACK 全流程，升级后并入更通用的 ack_pending。
        for photo_uuid, local in state["cleanup_pending"].items():
            if isinstance(local, dict):
                state["ack_pending"].setdefault(photo_uuid, dict(local))
        state["_scope_identity"] = identity
        return state

    def _read_state_document_unlocked(self, current_identity: str) -> dict:
        try:
            raw = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            raw = {}
        if not isinstance(raw, dict):
            raw = {}
        if isinstance(raw.get("scopes"), dict):
            scopes = {
                str(key): dict(value)
                for key, value in raw["scopes"].items()
                if str(key) and isinstance(value, dict)
            }
            return {
                "version": 2,
                "active_identity": str(raw.get("active_identity") or ""),
                "scopes": scopes,
            }

        # 旧版单层状态原位迁移到它原本的账号+机器分区。若旧文件还
        # 没写 account_identity，才归到当前分区。
        legacy_identity = str(raw.get("account_identity") or current_identity).strip()
        scopes = {legacy_identity: dict(raw)} if raw and legacy_identity else {}
        return {"version": 2, "active_identity": legacy_identity, "scopes": scopes}

    def _read_state(self) -> dict:
        return self._read_state_for_identity(self._state_identity())

    def _read_state_for_identity(self, identity: str) -> dict:
        identity = str(identity or "").strip()
        with self._state_lock:
            document = self._read_state_document_unlocked(identity)
            scope = document["scopes"].get(identity, {})
            return self._normalized_scope_state(scope, identity)

    def _mutate_state_for_identity(self, identity: str, callback):
        """在一个锁周期内修改指定账号+机器分区，避免网络线程覆盖删除事件。"""
        identity = str(identity or "").strip()
        if not identity:
            raise ValueError("同步状态分区不能为空")
        with self._state_lock:
            document = self._read_state_document_unlocked(identity)
            state = self._normalized_scope_state(
                document.setdefault("scopes", {}).get(identity, {}), identity
            )
            result = callback(state)
            state.pop("_scope_identity", None)
            document["version"] = 2
            document["active_identity"] = identity
            document["scopes"][identity] = state
            _atomic_write_json(self.state_path, document)
            return result

    def _state_identity_for_account(self, account_id: str) -> str:
        """得到指定云账号在本机的确定分区；登出时也不落入 logged-out。"""
        account_id = str(account_id or "").strip()
        if not account_id:
            return ""
        current_account_id = self._cloud_account_id()
        if current_account_id == account_id:
            current = self._state_identity()
            if not current.startswith("__logged_out__|"):
                return current
        reader = getattr(self.cloud, "desktop_sync_identity_for_account", None)
        try:
            account_identity = str(reader(account_id) or "").strip() if callable(reader) else ""
        except Exception:
            account_identity = ""
        if not account_identity:
            return ""
        return f"{account_identity}|{self._desktop_machine_id() or 'unknown-machine'}"

    def _write_state(self, state: dict) -> None:
        supplied = dict(state or {})
        identity = str(supplied.pop("_scope_identity", "") or self._state_identity())
        normalized = self._normalized_scope_state(supplied, identity)
        normalized.pop("_scope_identity", None)
        with self._state_lock:
            document = self._read_state_document_unlocked(identity)
            # delete_pending 只允许通过 _mutate_state_for_identity 原子增删。
            # 快照、收件箱等网络步骤常在请求前读取 state、请求后再写回；
            # 若此间用户删除照片，旧副本绝不能覆盖刚持久化的删除事件。
            persisted_scope = self._normalized_scope_state(
                document.setdefault("scopes", {}).get(identity, {}), identity
            )
            normalized["delete_pending"] = dict(
                persisted_scope.get("delete_pending") or {}
            )
            document["version"] = 2
            document["active_identity"] = identity
            document.setdefault("scopes", {})[identity] = normalized
            _atomic_write_json(self.state_path, document)

    def set_backfill_paused(self, paused: bool) -> dict:
        state = self._read_state()
        state["backfill_paused"] = bool(paused)
        state["updated_at"] = datetime.now().isoformat(timespec="seconds")
        self._write_state(state)
        return {"ok": True, "paused": bool(paused)}

    def pause_backfill(self) -> dict:
        return self.set_backfill_paused(True)

    def resume_backfill(self) -> dict:
        return self.set_backfill_paused(False)

    def status(self) -> dict:
        state = self._read_state()
        ownership = self._project_ownership_status()
        if not ownership.get("account_id") and ownership.get("owner_id"):
            owner_identity = self._state_identity_for_account(ownership["owner_id"])
            if owner_identity:
                state = self._read_state_for_identity(owner_identity)
        return {
            "ok": True,
            "running": bool(self._thread and self._thread.is_alive()),
            "backfill_paused": bool(state.get("backfill_paused")),
            "snapshot_revision": str(state.get("snapshot_revision") or ""),
            "inbox_cursor": str(state.get("inbox_cursor") or ""),
            "backfilled_count": len(state.get("backfilled") or {}),
            "ack_pending_count": len(state.get("ack_pending") or {}),
            "cleanup_pending_count": len(state.get("cleanup_pending") or {}),
            "delete_pending_count": len(state.get("delete_pending") or {}),
            "last_result": dict(self.last_result),
            "project_ownership": ownership,
        }

    def account_transition(self, callback):
        """在同步周期边界内切换登录账号，杜绝一个周期混用两套令牌。"""
        with self._cycle_lock:
            result = callback()
            if isinstance(result, dict) and result.get("ok"):
                self._active_state_identity = ""
                self._startup_snapshot_pending = True
            return result

    def _desktop_machine_id(self) -> str:
        try:
            return str(self.machine_id_reader() or "").strip()
        except Exception:
            return ""

    def _ensure_account_identity(self) -> None:
        identity = self._state_identity()
        if self._active_state_identity == identity:
            return
        # 每个账号+机器读取自己的完整状态；切换时只要求该分区重新
        # 发送一次启动快照，绝不清空其它账号的 ACK、游标或回填进度。
        self._active_state_identity = identity
        self._startup_snapshot_pending = True

    def _sync_snapshot(self) -> dict:
        snapshot = build_project_snapshot(
            self.manager,
            self.engineering_project_reader(),
            self.other_images_reader(),
            desktop_machine_id=self._desktop_machine_id(),
        )
        state = self._read_state()
        content_hash = str(snapshot.pop("_content_hash", ""))
        previous_hash = str(state.get("snapshot_content_hash") or "")
        previous_revision = int(state.get("snapshot_revision") or 0)
        if not self._startup_snapshot_pending and previous_hash == content_hash:
            return {"ok": True, "skipped": True, "revision": previous_revision}
        if previous_hash == content_hash and previous_revision > 0:
            revision = previous_revision
        else:
            # 百分之一秒精度仍远低于服务器 10^12 上限，并且在本地
            # 状态丢失后也大概率高于历史 revision。
            revision = max(previous_revision + 1, int(time.time() * 100))
        snapshot["revision"] = revision
        result = self.cloud.desktop_project_snapshot(snapshot)
        if result.get("ok"):
            result_project = result.get("project") if isinstance(result.get("project"), dict) else {}
            project_ref = str(
                result.get("project_ref")
                or result_project.get("project_ref")
                or snapshot.get("project", {}).get("project_ref")
                or ""
            ).strip()
            state["snapshot_revision"] = revision
            state["snapshot_content_hash"] = content_hash
            state["snapshot_id"] = snapshot["snapshot_id"]
            state["project_ref"] = project_ref
            state["snapshot_synced_at"] = datetime.now().isoformat(timespec="seconds")
            self._write_state(state)
            self._startup_snapshot_pending = False
        return result

    def enqueue_photo_delete(
        self,
        photo_uuid: str,
        local_project_code: str,
        local_photo_id: str,
        *,
        project_id: str = "",
        cloud_account_id: str = "",
    ) -> dict:
        """持久化一条明确删除事件；本地删除永不等待网络。"""
        photo_uuid = _canonical_uuid(photo_uuid)
        if not photo_uuid:
            return {
                "ok": True,
                "queued": False,
                "code": "photo_uuid_missing",
                "message": "本地照片没有云端 UUID，不发送任何删除请求",
            }
        project = self.engineering_project_reader() or {}
        owner_id = str(
            cloud_account_id or project.get("cloud_owner_id") or ""
        ).strip()
        if not owner_id:
            return {
                "ok": True,
                "queued": False,
                "code": "project_owner_unclaimed",
                "message": "工程尚未绑定云账号，删除仅在本机生效",
            }
        current_account_id = self._cloud_account_id()
        if current_account_id and current_account_id != owner_id:
            return {
                "ok": True,
                "queued": False,
                "code": "project_owner_mismatch",
                "message": "当前登录账号不是工程所属账号，未发送云端删除",
            }
        identity = self._state_identity_for_account(owner_id)
        if not identity:
            return {
                "ok": True,
                "queued": False,
                "code": "account_partition_unavailable",
                "message": "无法安全确定所属账号分区，未发送云端删除",
            }
        timestamp = datetime.now().isoformat(timespec="seconds")

        def enqueue(state):
            pending = state.setdefault("delete_pending", {})
            previous = pending.get(photo_uuid) if isinstance(pending.get(photo_uuid), dict) else {}
            ack_after_delete = bool(
                previous.get("ack_after_delete")
                or photo_uuid in state.setdefault("ack_pending", {})
                or photo_uuid in state.setdefault("cleanup_pending", {})
            )
            event_id = str(previous.get("event_id") or uuid.uuid4())
            pending[photo_uuid] = {
                **previous,
                "event_id": event_id,
                "account_id": owner_id,
                "project_id": str(project_id or project.get("id") or "default"),
                "local_project_code": str(local_project_code or "").strip(),
                "local_photo_id": str(local_photo_id or "").strip(),
                "queued_at": str(previous.get("queued_at") or timestamp),
                "updated_at": timestamp,
                "attempts": int(previous.get("attempts") or 0),
                "ack_after_delete": ack_after_delete,
            }
            # 本地照片已经明确删除，旧 ACK 再也无法通过文件校验；删除事件
            # 接管该 UUID，避免 ACK 竞态永久占用 pending。
            state.setdefault("ack_pending", {}).pop(photo_uuid, None)
            state.setdefault("cleanup_pending", {}).pop(photo_uuid, None)
            state["cloud_account_id"] = owner_id
            return event_id, len(pending)

        event_id, pending_count = self._mutate_state_for_identity(identity, enqueue)
        wake_started = False
        if current_account_id == owner_id:
            try:
                threading.Thread(
                    target=self.run_once,
                    name="desktop-mobile-delete-sync",
                    daemon=True,
                ).start()
                wake_started = True
            except Exception:
                # 入队已持久化；线程创建失败时由固定周期继续重试。
                wake_started = False
        return {
            "ok": True,
            "queued": True,
            "photo_uuid": photo_uuid,
            "event_id": event_id,
            "pending_count": pending_count,
            "wake_started": wake_started,
        }

    def _handoff_ack_to_delete(self, photo_uuid: str, local: dict) -> bool:
        """本地已删时由显式删除事件接管 ACK，避免再次校验已删除文件。"""
        identity = self._state_identity()

        def handoff(state):
            entry = (state.get("delete_pending") or {}).get(photo_uuid)
            if not isinstance(entry, dict):
                return False
            entry["ack_after_delete"] = True
            entry["local_project_code"] = str(
                entry.get("local_project_code") or local.get("project_code") or ""
            )
            entry["local_photo_id"] = str(
                entry.get("local_photo_id") or local.get("photo_id") or ""
            )
            entry["updated_at"] = datetime.now().isoformat(timespec="seconds")
            state.setdefault("ack_pending", {}).pop(photo_uuid, None)
            state.setdefault("cleanup_pending", {}).pop(photo_uuid, None)
            return True

        return bool(self._mutate_state_for_identity(identity, handoff))

    def _sync_delete_pending(self) -> dict:
        """逐条发送显式删除；失败只留队，不阻断快照、收件箱或回填。"""
        identity = self._state_identity()
        state = self._read_state_for_identity(identity)
        items = list((state.get("delete_pending") or {}).items())
        current_account_id = self._cloud_account_id()
        attempted = 0
        deleted = 0
        failed = 0
        last_error = ""
        for photo_uuid, entry in items:
            if not isinstance(entry, dict):
                continue
            event_id = str(entry.get("event_id") or "")
            entry_account_id = str(entry.get("account_id") or "").strip()
            if not current_account_id or entry_account_id != current_account_id:
                result = {
                    "ok": False,
                    "error": "删除事件所属账号与当前登录账号不一致",
                    "retryable": False,
                }
            else:
                attempted += 1
                try:
                    result = self.cloud.desktop_delete_photo(
                        photo_uuid,
                        str(entry.get("local_project_code") or ""),
                        str(entry.get("local_photo_id") or ""),
                        self._desktop_machine_id(),
                    )
                except Exception as exc:
                    result = {"ok": False, "error": str(exc), "retryable": True}
            result = dict(result or {})
            ack_required = bool(entry.get("ack_after_delete"))
            if result.get("ok") and ack_required and result.get("deleted_at"):
                try:
                    ack = self.cloud.desktop_ack_photo(
                        photo_uuid,
                        str(entry.get("local_project_code") or ""),
                        str(entry.get("local_photo_id") or ""),
                        self._desktop_machine_id(),
                    )
                except Exception as exc:
                    ack = {"ok": False, "error": str(exc), "retryable": True}
                ack = dict(ack or {})
                if not ack.get("ok") or ack.get("cleanup_pending") or (
                    ack.get("cleanup_status") == "cleanup_pending"
                ):
                    result = {
                        "ok": False,
                        "error": str(ack.get("error") or "删除已同步，等待服务器清理原图"),
                        "retryable": True,
                    }

            if result.get("ok"):
                def finish(persisted):
                    current = (persisted.get("delete_pending") or {}).get(photo_uuid)
                    if isinstance(current, dict) and str(current.get("event_id") or "") == event_id:
                        persisted["delete_pending"].pop(photo_uuid, None)
                self._mutate_state_for_identity(identity, finish)
                deleted += 1
                continue

            failed += 1
            last_error = str(result.get("error") or "删除请求失败")[:300]

            def record_failure(persisted):
                current = (persisted.get("delete_pending") or {}).get(photo_uuid)
                if not isinstance(current, dict) or str(current.get("event_id") or "") != event_id:
                    return
                current["attempts"] = int(current.get("attempts") or 0) + 1
                current["last_error"] = last_error
                current["updated_at"] = datetime.now().isoformat(timespec="seconds")
            self._mutate_state_for_identity(identity, record_failure)
        remaining = len(
            (self._read_state_for_identity(identity).get("delete_pending") or {})
        )
        return {
            "ok": True,
            "attempted": attempted,
            "deleted": deleted,
            "failed": failed,
            "remaining": remaining,
            "last_error": last_error,
        }

    def _find_photo_uuid(self, photo_uuid: str) -> Optional[dict]:
        target = str(photo_uuid or "").strip()
        if not target:
            return None
        for project in self.manager.list_projects(include_other=True):
            code = str(project.get("project_code") or "").strip()
            if not code:
                continue
            data = self.manager.get_project(code)
            for photo in data.get("photos", []):
                if str(photo.get("photo_uuid") or "").strip() == target:
                    return {
                        "project_code": code,
                        "photo_id": str(photo.get("id") or ""),
                        "photo": photo,
                    }
        return None

    def _resolve_inbox_target(self, item: dict) -> Tuple[str, str, str]:
        scope = str(item.get("scope") or "").strip()
        projects = self.manager.list_projects(include_other=True)
        if scope == "other":
            node_code = str(item.get("other_node_code") or "").strip()
            for project in projects:
                code = str(project.get("project_code") or "").strip()
                if code != node_code:
                    continue
                data = self.manager.get_project(code)
                if (data.get("source_fields") or {}).get("_other_image"):
                    return code, "construction", ""
            raise ValueError("手机指定的其它影像目录在电脑端不存在")
        if scope != "engineering":
            raise ValueError("手机影像范围无效")
        unit_code = str(item.get("unit_code") or "").strip()
        category = str(item.get("category") or "").strip()
        if category not in {"construction", "supervision"}:
            raise ValueError("手机影像分类无效")
        for project in projects:
            code = str(project.get("project_code") or "").strip()
            data = self.manager.get_project(code)
            if (data.get("source_fields") or {}).get("_other_image"):
                continue
            hierarchy = self.manager.project_hierarchy(data)
            candidates = {
                code,
                str(data.get("display_project_code") or "").strip(),
                str(hierarchy.get("unit_code") or "").strip(),
            }
            if unit_code not in candidates:
                continue
            process_name = str(item.get("process_name") or "").strip()
            allowed = [str(value).strip() for value in (data.get("processes") or []) if str(value).strip()]
            if process_name and process_name not in allowed:
                raise ValueError("手机指定的工序在电脑端不存在")
            return code, category, process_name
        raise ValueError("手机指定的单元工程在电脑端不存在")

    def _import_inbox_item(self, item: dict, original_max_bytes: int) -> dict:
        ownership = self._project_ownership_status()
        if not ownership.get("ok"):
            raise ValueError(ownership.get("error") or "本地工程云账号归属不一致")
        photo_uuid = _canonical_uuid(item.get("photo_uuid"))
        if not photo_uuid:
            raise ValueError("手机影像 UUID 无效")
        target_machine_id = str(item.get("target_machine_id") or "").strip()
        current_machine_id = self._desktop_machine_id()
        if not current_machine_id:
            raise ValueError("当前电脑缺少稳定机器编号，已拒绝导入")
        if target_machine_id != current_machine_id:
            raise ValueError("原图不属于当前电脑，已拒绝导入")
        current_project = self.engineering_project_reader() or {}
        identity = _engineering_project_identity(current_project)
        current_project_id = identity["local_project_id"]
        current_project_ref = identity["project_ref"]
        item_project_ref = str(item.get("project_ref") or "").strip()
        item_local_project_id = str(item.get("local_project_id") or "").strip()
        item_project_id = str(item.get("project_id") or "").strip()
        item_owner_id = str(
            item.get("project_owner_account_id")
            or item.get("owner_account_id")
            or ""
        ).strip()
        if item_owner_id and identity["owner_account_id"] and item_owner_id != identity["owner_account_id"]:
            raise ValueError("原图属于另一工程账号，已拒绝导入")
        if item_project_ref:
            project_matches = bool(current_project_ref) and item_project_ref == current_project_ref
        elif item_local_project_id:
            project_matches = item_local_project_id == current_project_id
        else:
            # 兼容旧服务器只返回本地 project_id，以及新服务器把 canonical
            # project_ref 同时放在 project_id 的过渡期。
            project_matches = item_project_id in {current_project_id, current_project_ref}
        if not project_matches:
            raise ValueError("原图不属于当前工程，已拒绝导入")
        expected_sha = str(item.get("original_sha256") or "").strip().lower()
        try:
            expected_size = int(item.get("original_size_bytes") or 0)
        except (TypeError, ValueError):
            raise ValueError("手机原图大小字段无效")
        expected_mime = str(item.get("original_mime_type") or "").strip().lower()
        if expected_mime == "image/jpg":
            expected_mime = "image/jpeg"
        if expected_mime not in {"image/jpeg", "image/png"}:
            raise ValueError("手机原图缺少有效 JPEG/PNG 类型")
        download_url = str(item.get("original_download_url") or item.get("download_url") or "")
        existing = self._find_photo_uuid(photo_uuid)
        if existing:
            filename = Path(str((existing.get("photo") or {}).get("filename") or "")).name
            local_path = self.manager._photos_dir(existing["project_code"]) / filename
            try:
                local_details = _validate_existing_original_path(
                    local_path,
                    expected_sha,
                    expected_size,
                    expected_mime,
                    original_max_bytes,
                )
                return {
                    "ok": True,
                    "duplicate": True,
                    **existing,
                    "original_sha256": local_details["sha256"],
                    "original_size_bytes": local_details["size_bytes"],
                    "original_mime_type": local_details["mime_type"],
                }
            except Exception:
                # metadata 中有 UUID 但正式文件缺失/损坏时，绝不能直接
                # ACK。先重新下载服务器原图并修复同一条本地记录。
                pass

        downloaded = self.cloud.desktop_download_bytes(
            download_url,
            original_max_bytes,
        )
        if not downloaded.get("ok"):
            return downloaded
        raw = downloaded.get("data") or b""
        details = _validate_original_image(
            raw,
            str(item.get("original_sha256") or ""),
            expected_size=expected_size,
            claimed_mime=expected_mime,
            max_bytes=original_max_bytes,
        )

        if existing:
            repair = getattr(self.manager, "repair_mobile_original", None)
            if not callable(repair):
                raise ValueError("本地手机原图缺失或损坏，当前版本无法安全修复；已保留服务器原图")
            repair(
                existing["project_code"],
                photo_uuid,
                raw,
                details,
                str(item.get("original_filename") or "").strip(),
            )
            stored = self._find_photo_uuid(photo_uuid)
            if not stored:
                raise ValueError("手机原图修复后无法按 UUID 定位，已保留服务器原图")
            filename = Path(str((stored.get("photo") or {}).get("filename") or "")).name
            repaired_path = self.manager._photos_dir(stored["project_code"]) / filename
            verified = _validate_existing_original_path(
                repaired_path,
                expected_sha,
                expected_size,
                expected_mime,
                original_max_bytes,
            )
            return {
                "ok": True,
                "duplicate": True,
                "repaired": True,
                **stored,
                "original_sha256": verified["sha256"],
                "original_size_bytes": verified["size_bytes"],
                "original_mime_type": verified["mime_type"],
            }

        project_code, category, process_name = self._resolve_inbox_target(item)

        from werkzeug.datastructures import FileStorage

        filename = f"mobile-{photo_uuid}{details['extension']}"
        captured_at = str(item.get("client_captured_at") or "").strip()
        photo_date = str(item.get("photo_date") or "").strip() or captured_at[:10]
        per_file_meta = {
            filename: {
                "photo_uuid": photo_uuid,
                "title": str(item.get("title") or "").strip(),
                "photo_date": photo_date,
                "preserve_mobile_original": True,
                "mobile_original_received": True,
                "source_original_name": str(item.get("original_filename") or "").strip(),
                "client_captured_at": captured_at,
                "sha256": details["sha256"],
                "pixel_width": details["width"],
                "pixel_height": details["height"],
                "photographer_account_id": str(
                    item.get("photographer_account_id")
                    or ""
                ).strip(),
                "uploaded_by_account_id": str(
                    item.get("uploaded_by_account_id")
                    or item.get("uploader_account_id")
                    or item.get("account_id")
                    or ""
                ).strip(),
                "project_owner_account_id": str(
                    item.get("project_owner_account_id")
                    or item.get("owner_account_id")
                    or identity["owner_account_id"]
                    or ""
                ).strip(),
                "capture_source": str(item.get("capture_source") or "mobile").strip(),
            }
        }
        raw_orientation = str(item.get("orientation") or "").strip().lower()
        if raw_orientation in {"landscape", "portrait"}:
            display_orientation = raw_orientation
        else:
            display_orientation = "portrait" if details["height"] > details["width"] else "landscape"
        added = self.manager.add_photos(
            project_code,
            [FileStorage(stream=io.BytesIO(raw), filename=filename, content_type=details["mime_type"])],
            category=category,
            title=str(item.get("title") or "").strip(),
            photo_date=photo_date,
            photographer=str(item.get("photographer") or "").strip(),
            uploaded_by=str(item.get("uploaded_by") or "微信小程序").strip(),
            orientation=display_orientation,
            process_name=process_name,
            per_file_meta=per_file_meta,
        )
        if not added:
            raise ValueError("手机影像导入失败")
        # add_photos 会按桌面端现有规则重排显示编号；回执前重新用永久
        # UUID 定位，不把导入前的可变编号当主键。
        stored = self._find_photo_uuid(photo_uuid)
        if not stored:
            raise ValueError("手机影像已写入但无法按 UUID 定位")
        result = {
            "ok": True,
            "duplicate": False,
            "project_code": stored["project_code"],
            "photo_id": stored["photo_id"],
            "photo": stored["photo"],
            "original_sha256": details["sha256"],
            "original_size_bytes": details["size_bytes"],
            "original_mime_type": details["mime_type"],
        }
        return result

    def _queue_ack(self, photo_uuid: str, local: dict) -> None:
        """在发网络 ACK 前先持久化本地重试意图。"""
        state = self._read_state()
        pending = state.setdefault("ack_pending", {})
        previous = pending.get(photo_uuid) if isinstance(pending.get(photo_uuid), dict) else {}
        pending[photo_uuid] = {
            **previous,
            "local_project_code": str(local.get("project_code") or ""),
            "local_photo_id": str(local.get("photo_id") or ""),
            "original_sha256": str(local.get("original_sha256") or previous.get("original_sha256") or ""),
            "original_size_bytes": int(local.get("original_size_bytes") or previous.get("original_size_bytes") or 0),
            "original_mime_type": str(local.get("original_mime_type") or previous.get("original_mime_type") or ""),
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        }
        self._write_state(state)

    def _verified_ack_local(self, photo_uuid: str, local: dict) -> dict:
        existing = self._find_photo_uuid(photo_uuid)
        if not existing:
            raise ValueError("待回执手机原图的本地 metadata 不存在")
        photo = existing.get("photo") or {}
        filename = Path(str(photo.get("filename") or "")).name
        path = self.manager._photos_dir(existing["project_code"]) / filename
        expected_sha = str(local.get("original_sha256") or photo.get("sha256") or "")
        expected_size = int(
            local.get("original_size_bytes")
            or photo.get("mobile_original_size_bytes")
            or photo.get("stored_bytes")
            or 0
        )
        details = _validate_existing_original_path(
            path,
            expected_sha,
            expected_size,
            str(local.get("original_mime_type") or ""),
            MAX_ORIGINAL_PHOTO_BYTES,
        )
        return {
            "project_code": existing["project_code"],
            "photo_id": existing["photo_id"],
            "photo": photo,
            "original_sha256": details["sha256"],
            "original_size_bytes": details["size_bytes"],
            "original_mime_type": details["mime_type"],
        }

    def _record_ack_local_failure(self, photo_uuid: str, error: Exception) -> None:
        state = self._read_state()
        pending = state.setdefault("ack_pending", {})
        entry = pending.get(photo_uuid) if isinstance(pending.get(photo_uuid), dict) else {}
        entry.update({
            "local_validation_failed": True,
            "last_error": str(error)[:300],
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        })
        pending[photo_uuid] = entry
        self._write_state(state)

    def _record_ack_result(self, photo_uuid: str, local: dict, ack: dict) -> None:
        state = self._read_state()
        ack_pending = state.setdefault("ack_pending", {})
        cleanup_pending = state.setdefault("cleanup_pending", {})
        cleanup_waiting = bool(
            ack.get("cleanup_pending")
            or ack.get("cleanup_status") == "cleanup_pending"
        )
        if ack.get("ok") and not cleanup_waiting:
            # 只有服务器确认归档且原图清理不再 pending，ACK 才真正完成。
            ack_pending.pop(photo_uuid, None)
            cleanup_pending.pop(photo_uuid, None)
        else:
            previous = ack_pending.get(photo_uuid) if isinstance(ack_pending.get(photo_uuid), dict) else {}
            entry = {
                **previous,
                "local_project_code": str(local.get("project_code") or ""),
                "local_photo_id": str(local.get("photo_id") or ""),
                "updated_at": datetime.now().isoformat(timespec="seconds"),
            }
            if ack.get("error"):
                entry["last_error"] = str(ack.get("error"))[:300]
            ack_pending[photo_uuid] = entry
            if cleanup_waiting:
                cleanup_pending[photo_uuid] = dict(entry)
        self._write_state(state)

    def _ack_import(self, photo_uuid: str, local: dict) -> dict:
        # 如果服务器已经提交 ACK 但响应在网络中丢失，这条记录保证下个
        # 周期仍用相同 UUID 和本地编号进行幂等重试。
        if self._handoff_ack_to_delete(photo_uuid, local):
            return {
                "ok": True,
                "ack_sent": False,
                "delete_pending": True,
                "cleanup_pending": True,
            }
        self._queue_ack(photo_uuid, local)
        try:
            verified = self._verified_ack_local(photo_uuid, local)
        except Exception as exc:
            self._record_ack_local_failure(photo_uuid, exc)
            return {
                "ok": False,
                "error": str(exc),
                "local_validation_failed": True,
                "retryable": True,
                "ack_sent": False,
            }
        self._queue_ack(photo_uuid, verified)
        ack = self.cloud.desktop_ack_photo(
            photo_uuid,
            verified["project_code"],
            verified["photo_id"],
            self._desktop_machine_id(),
        )
        ack = dict(ack or {})
        ack["ack_sent"] = True
        self._record_ack_result(photo_uuid, verified, ack)
        return ack

    def _retry_ack_pending(self) -> dict:
        state = self._read_state()
        items = list((state.get("ack_pending") or {}).items())
        retried = 0
        invalid_local = 0
        for photo_uuid, local in items:
            ack = self._ack_import(photo_uuid, {
                "project_code": str(local.get("local_project_code") or ""),
                "photo_id": str(local.get("local_photo_id") or ""),
                "original_sha256": str(local.get("original_sha256") or ""),
                "original_size_bytes": local.get("original_size_bytes") or 0,
                "original_mime_type": str(local.get("original_mime_type") or ""),
            })
            retried += 1 if ack.get("ack_sent") else 0
            invalid_local += 1 if ack.get("local_validation_failed") else 0
            if not ack.get("ok"):
                # 原图已经在本地安全归档；回执失败不影响新照片同步，
                # ack_pending 仍在，下一个周期继续幂等重试。
                continue
        remaining = len((self._read_state().get("ack_pending") or {}))
        return {
            "ok": True,
            "retried": retried,
            "invalid_local": invalid_local,
            "remaining": remaining,
        }

    def _retry_cleanup_pending(self) -> dict:
        """兼容初版调用名；现在会重试全部 ACK pending。"""
        return self._retry_ack_pending()

    def _sync_inbox(self) -> dict:
        ownership = self._project_ownership_status()
        if not ownership.get("ok"):
            return {
                **ownership,
                "imported": 0,
                "duplicates": 0,
                "ack_retried": 0,
                "ack_pending": len((self._read_state().get("ack_pending") or {})),
            }
        pending_retry = self._retry_ack_pending()
        state = self._read_state()
        result = self.cloud.desktop_inbox(
            state.get("inbox_cursor", ""),
            self.inbox_limit,
            self._desktop_machine_id(),
        )
        if not result.get("ok"):
            return result
        try:
            original_max_bytes = int(
                result.get("original_max_bytes")
                or result.get("max_original_bytes")
                or MAX_ORIGINAL_PHOTO_BYTES
            )
        except (TypeError, ValueError):
            original_max_bytes = MAX_ORIGINAL_PHOTO_BYTES
        original_max_bytes = max(1, min(MAX_ORIGINAL_PHOTO_BYTES, original_max_bytes))
        imported = 0
        duplicates = 0
        skipped_deleted = 0
        for item in result.get("items") or []:
            photo_uuid = str(item.get("photo_uuid") or "").strip()
            if photo_uuid in (self._read_state().get("delete_pending") or {}):
                # 显式删除尚未送达时，绝不能把同一张待归档照片重新导回本机。
                skipped_deleted += 1
                item_cursor = str(item.get("cursor") or "").strip()
                if item_cursor:
                    state = self._read_state()
                    state["inbox_cursor"] = item_cursor
                    self._write_state(state)
                continue
            try:
                local = self._import_inbox_item(item, original_max_bytes)
            except Exception as exc:
                return {"ok": False, "error": str(exc), "retryable": True, "imported": imported}
            if not local.get("ok"):
                return {**local, "imported": imported}
            ack = self._ack_import(photo_uuid, local)
            if not ack.get("ok"):
                return {**ack, "imported": imported}
            imported += 0 if local.get("duplicate") else 1
            duplicates += 1 if local.get("duplicate") else 0
            item_cursor = str(item.get("cursor") or "").strip()
            if item_cursor:
                state = self._read_state()
                state["inbox_cursor"] = item_cursor
                self._write_state(state)
        next_cursor = str(result.get("next_cursor") or "").strip()
        if next_cursor:
            state = self._read_state()
            state["inbox_cursor"] = next_cursor
            self._write_state(state)
        return {
            "ok": True,
            "imported": imported,
            "duplicates": duplicates,
            "skipped_deleted": skipped_deleted,
            "ack_retried": pending_retry["retried"],
            "ack_local_invalid": pending_retry["invalid_local"],
            "ack_pending": len((self._read_state().get("ack_pending") or {})),
            "cleanup_retried": pending_retry["retried"],
            "cleanup_pending": len((self._read_state().get("cleanup_pending") or {})),
        }

    def _iter_backfill_candidates(self) -> Iterable[dict]:
        ownership = self._project_ownership_status()
        if not ownership.get("ok"):
            return
        project_identity = _engineering_project_identity(
            self.engineering_project_reader() or {}
        )
        ensure_all_photo_uuids(self.manager)
        for project in self.manager.list_projects(include_other=True):
            code = str(project.get("project_code") or "").strip()
            if not code:
                continue
            data = self.manager.get_project(code)
            fields = data.get("source_fields") or {}
            is_other = bool(fields.get("_other_image"))
            hierarchy = self.manager.project_hierarchy(data)
            for photo in data.get("photos", []):
                photo_uuid = _canonical_uuid(photo.get("photo_uuid"))
                if not photo_uuid or photo.get("mobile_compressed_200k") or photo.get("mobile_original_received"):
                    continue
                filename = Path(str(photo.get("filename") or "")).name
                source = self.manager._photos_dir(code) / filename
                if not filename or not source.exists():
                    continue
                target = {
                    "project_id": project_identity["local_project_id"],
                    "local_project_id": project_identity["local_project_id"],
                    "project_ref": project_identity["project_ref"],
                    "project_owner_account_id": project_identity["owner_account_id"],
                    "scope": "other" if is_other else "engineering",
                    "category": "" if is_other else str(photo.get("category") or "construction"),
                    "unit_code": "" if is_other else str(hierarchy.get("unit_code") or data.get("display_project_code") or code),
                    "process_name": "" if is_other else str(photo.get("process_name") or ""),
                    "other_node_code": code if is_other else "",
                }
                yield {
                    "project_code": code,
                    "photo": photo,
                    "photo_uuid": photo_uuid,
                    "source": source,
                    "target": target,
                }

    def _sync_backfill(self) -> dict:
        ownership = self._project_ownership_status()
        if not ownership.get("ok"):
            return {**ownership, "uploaded": 0}
        state = self._read_state()
        if state.get("backfill_paused"):
            return {"ok": True, "paused": True, "uploaded": 0}
        uploaded = 0
        for candidate in self._iter_backfill_candidates():
            if uploaded >= self.backfill_limit:
                break
            photo_uuid = candidate["photo_uuid"]
            photo = candidate["photo"]
            try:
                preview = prepare_jpeg_view_copy(candidate["source"], self.cache_dir)
            except Exception as exc:
                # 损坏的某张照片不应阻断所有其它照片。
                state = self._read_state()
                state.setdefault("backfill_errors", {})[photo_uuid] = str(exc)[:300]
                self._write_state(state)
                continue
            state = self._read_state()
            if state.setdefault("backfilled", {}).get(photo_uuid) == preview["sha256"]:
                continue
            previous_error = state.setdefault("backfill_errors", {}).get(photo_uuid)
            if (
                isinstance(previous_error, dict)
                and previous_error.get("permanent")
                and previous_error.get("preview_sha256") == preview["sha256"]
            ):
                continue
            metadata = {
                "photo_uuid": photo_uuid,
                **candidate["target"],
                "desktop_machine_id": self._desktop_machine_id(),
                "title": str(photo.get("title") or ""),
                "photo_date": str(photo.get("photo_date") or ""),
                "photographer": str(photo.get("photographer") or ""),
                "uploaded_by": str(photo.get("uploaded_by") or ""),
                "photographer_account_id": str(photo.get("photographer_account_id") or ""),
                "uploaded_by_account_id": str(photo.get("uploaded_by_account_id") or ""),
                "client_captured_at": _iso_local_time(str(photo.get("upload_time") or "")),
                "orientation": preview.get("exif_orientation", 1),
                "width": preview["width"],
                "height": preview["height"],
                "sha256": preview["sha256"],
            }
            result = self.cloud.desktop_backfill_photo(preview["path"], metadata)
            if not result.get("ok"):
                try:
                    http_status = int(result.get("http_status") or 0)
                except (TypeError, ValueError):
                    http_status = 0
                # 单张图片或元数据的永久校验错误只隔离该照片。认证、
                # 网络、限流和服务器错误仍中止本轮，留待下一周期重试。
                if http_status in {400, 409, 413, 415, 422} and not result.get("network_error"):
                    state = self._read_state()
                    state.setdefault("backfill_errors", {})[photo_uuid] = {
                        "permanent": True,
                        "preview_sha256": preview["sha256"],
                        "http_status": http_status,
                        "code": str(result.get("code") or "")[:80],
                        "error": str(result.get("error") or "云端预览校验失败")[:300],
                        "updated_at": datetime.now().isoformat(timespec="seconds"),
                    }
                    self._write_state(state)
                    continue
                return {**result, "uploaded": uploaded}
            state = self._read_state()
            state.setdefault("backfilled", {})[photo_uuid] = preview["sha256"]
            state["backfill_last_uuid"] = photo_uuid
            state["backfill_updated_at"] = datetime.now().isoformat(timespec="seconds")
            state.setdefault("backfill_errors", {}).pop(photo_uuid, None)
            self._write_state(state)
            uploaded += 1
        return {"ok": True, "uploaded": uploaded}

    def run_once(self) -> dict:
        if not self._cycle_lock.acquire(blocking=False):
            return {"ok": True, "busy": True}
        try:
            try:
                self._ensure_account_identity()
                ownership = self._project_ownership_status()
                if not ownership.get("ok"):
                    self.last_result = {
                        "ok": False,
                        "stage": "ownership",
                        **ownership,
                    }
                    return self.last_result
                cycle_identity = self._state_identity()
                cycle_generation = self._cloud_generation()
                deletes = self._sync_delete_pending()
                snapshot = self._sync_snapshot()
                if not snapshot.get("ok"):
                    self.last_result = {
                        "ok": False,
                        "stage": "snapshot",
                        "deletes": deletes,
                        **snapshot,
                    }
                    return self.last_result
                if (
                    self._state_identity() != cycle_identity
                    or self._cloud_generation() != cycle_generation
                ):
                    self.last_result = {
                        "ok": False,
                        "stage": "account_transition",
                        "code": "account_changed_during_sync",
                        "error": "账号在同步过程中发生变化，本轮已中止",
                        "retryable": True,
                    }
                    return self.last_result
                inbox = self._sync_inbox()
                if not inbox.get("ok"):
                    self.last_result = {"ok": False, "stage": "inbox", **inbox}
                    return self.last_result
                if (
                    self._state_identity() != cycle_identity
                    or self._cloud_generation() != cycle_generation
                ):
                    self.last_result = {
                        "ok": False,
                        "stage": "account_transition",
                        "code": "account_changed_during_sync",
                        "error": "账号在同步过程中发生变化，本轮已中止",
                        "retryable": True,
                    }
                    return self.last_result
                backfill = self._sync_backfill()
                if not backfill.get("ok"):
                    self.last_result = {"ok": False, "stage": "backfill", **backfill}
                    return self.last_result
                self.last_result = {
                    "ok": True,
                    "deletes": deletes,
                    "snapshot": snapshot,
                    "inbox": inbox,
                    "backfill": backfill,
                }
                return self.last_result
            except Exception as exc:
                # 后台同步不能影响桌面端正常使用；保留简短状态供诊断，
                # 不弹窗、不打印密钥或影像信息，下周期自动重试。
                self.last_result = {"ok": False, "stage": "internal", "error": str(exc)[:300], "retryable": True}
                return self.last_result
        finally:
            self._cycle_lock.release()

    def _run_forever(self) -> None:
        self.run_once()  # 启动后立即同步，不等第一个 30 秒。
        while not self._stop_event.wait(self.interval_seconds):
            self.run_once()

    def start(self):
        with self._start_lock:
            if self._thread and self._thread.is_alive():
                return self._thread
            self._stop_event.clear()
            self._thread = threading.Thread(
                target=self._run_forever,
                name="desktop-mobile-sync",
                daemon=True,
            )
            self._thread.start()
            return self._thread

    def stop(self, timeout: float = 2.0) -> None:
        self._stop_event.set()
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(max(0.0, float(timeout)))
