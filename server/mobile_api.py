# -*- coding: utf-8 -*-
"""工程影像微信小程序与桌面同步 API v1。

该模块只依赖现有账号令牌，并把所有 SQL 查询显式限定到 account_id。移动端
照片使用永久 photo_uuid；桌面编号和本地文件名变化不会改变云端身份。
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import secrets
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import warnings
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone

from flask import Blueprint, jsonify, request, send_file, url_for
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from PIL import Image, ImageOps, UnidentifiedImageError
from werkzeug.exceptions import RequestEntityTooLarge
from werkzeug.datastructures import FileStorage
from werkzeug.security import check_password_hash

from . import config, db, mobile_recognition
from .mobile_chunks import ChunkFileError, ChunkFileStore
from .mobile_storage import LocalObjectStorage, StorageError, create_storage


DEFAULT_PROJECT_NAME = "邯郸市永年区洺河龙泉缓洪工程"
SCOPES = {"engineering", "other"}
CATEGORIES = {"construction", "supervision"}
MODES = {"direct", "auto"}
BATCH_UPLOADABLE_STATUSES = {"local_ready", "server_saved"}
ACCOUNT_BIND_INTENT_MAX_AGE = 10 * 60
ACCOUNT_BIND_INTENT_SALT = "wechat-account-bind-intent"
UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)
PROJECT_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,100}$")
PROJECT_ROLES = {"owner", "admin", "capturer", "viewer"}
CAPTURE_ROLES = {"owner", "admin", "capturer"}
MANAGE_MEMBER_ROLES = {"owner", "admin"}
INVITABLE_ROLES = {"admin", "capturer", "viewer"}
PROJECT_INVITE_TTL_SECONDS = 7 * 24 * 60 * 60
PROJECT_INVITE_CODE_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"
JPEG_1M_TRANSFER_PROFILE = "jpeg_1m"
_PHOTO_UPLOAD_LOCKS = {}
_PHOTO_UPLOAD_LOCKS_GUARD = threading.Lock()
_CHUNK_SESSION_LOCKS = {}
_CHUNK_SESSION_LOCKS_GUARD = threading.Lock()
ANALYSIS_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="mobile-ocr")


@contextmanager
def _photo_upload_lock(account_id: int, photo_uuid: str):
    """单 worker 多线程下按照片 UUID 串行，避免幂等对象键相互覆盖。"""
    key = (int(account_id), str(photo_uuid))
    with _PHOTO_UPLOAD_LOCKS_GUARD:
        entry = _PHOTO_UPLOAD_LOCKS.get(key)
        if entry is None:
            entry = [threading.Lock(), 0]
            _PHOTO_UPLOAD_LOCKS[key] = entry
        entry[1] += 1
        lock = entry[0]
    lock.acquire()
    try:
        yield
    finally:
        lock.release()
        with _PHOTO_UPLOAD_LOCKS_GUARD:
            entry[1] -= 1
            if entry[1] == 0:
                _PHOTO_UPLOAD_LOCKS.pop(key, None)


@contextmanager
def _chunk_session_lock(account_id: int, photo_uuid: str, operation="session"):
    key = (int(account_id), str(photo_uuid), str(operation))
    with _CHUNK_SESSION_LOCKS_GUARD:
        entry = _CHUNK_SESSION_LOCKS.get(key)
        if entry is None:
            entry = [threading.Lock(), 0]
            _CHUNK_SESSION_LOCKS[key] = entry
        entry[1] += 1
        lock = entry[0]
    lock.acquire()
    try:
        yield
    finally:
        lock.release()
        with _CHUNK_SESSION_LOCKS_GUARD:
            entry[1] -= 1
            if entry[1] == 0:
                _CHUNK_SESSION_LOCKS.pop(key, None)


class ApiProblem(Exception):
    def __init__(
        self, code: str, message: str, status: int = 400, retryable: bool = False
    ):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.retryable = retryable


def _require_batch_uploadable(status: str) -> None:
    """仅未识别、未提交的批次可添加照片，防止状态回退。"""
    value = str(status or "")
    if value in BATCH_UPLOADABLE_STATUSES:
        return
    if value in {"desktop_pending", "desktop_imported"}:
        raise ApiProblem("batch_committed", "批次已提交，不能继续添加照片", 409)
    if value == "analyzing":
        raise ApiProblem("batch_analyzing", "批次正在自动识别，请稍后重试", 409)
    raise ApiProblem("batch_closed", "批次已进入确认阶段，不能再添加照片", 409)


def _json(value, fallback):
    if isinstance(value, (dict, list)):
        return value
    try:
        parsed = json.loads(value or "")
        return parsed if isinstance(parsed, type(fallback)) else fallback
    except (TypeError, ValueError):
        return fallback


def _dumps(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _future_timestamp(timestamp: str, seconds: int) -> str:
    try:
        base = datetime.strptime(timestamp, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except (TypeError, ValueError):
        base = datetime.now(timezone.utc)
    return (base + timedelta(seconds=int(seconds))).strftime("%Y-%m-%dT%H:%M:%SZ")


def _safe_text(value, maximum: int = 200) -> str:
    return str(value or "").strip()[:maximum]


def _safe_filename(value, fallback="") -> str:
    text = str(value or fallback or "").replace("\\", "/").replace("\x00", "")
    leaf = re.sub(r"[\x00-\x1f\x7f]+", "_", text.rsplit("/", 1)[-1])
    if leaf.strip() in {"", ".", ".."}:
        leaf = "original"
    return _safe_text(leaf, 260)


def _integer(value, default: int = 0, minimum: int = 0, maximum: int = 10**9) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


def _uuid(value, field: str) -> str:
    text = str(value or "").strip().lower()
    try:
        normalized = str(uuid.UUID(text))
    except (ValueError, AttributeError, TypeError) as exc:
        raise ApiProblem("invalid_uuid", f"{field} 必须是有效 UUID") from exc
    if not UUID_RE.fullmatch(normalized):
        raise ApiProblem("invalid_uuid", f"{field} 必须是有效 UUID")
    return normalized


def _sha256(value, field: str = "sha256") -> str:
    text = str(value or "").strip().lower()
    if not re.fullmatch(r"[0-9a-f]{64}", text):
        raise ApiProblem("sha256_required", f"{field} 必须是 64 位 SHA-256")
    return text


def _strict_integer(value, field: str, minimum: int, maximum: int | None = None) -> int:
    if isinstance(value, bool):
        raise ApiProblem("invalid_integer", f"{field} 必须是整数")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ApiProblem("invalid_integer", f"{field} 必须是整数") from exc
    if parsed < minimum or (maximum is not None and parsed > maximum):
        raise ApiProblem("invalid_integer", f"{field} 超出允许范围")
    return parsed


def _project_id(value) -> str:
    text = str(value or "").strip()
    if not PROJECT_ID_RE.fullmatch(text):
        raise ApiProblem("invalid_project_id", "工程 ID 格式不正确")
    return text


def _project_ref(owner_account_id: int, project_id: str) -> str:
    return f"{int(owner_account_id)}:{_project_id(project_id)}"


def _parse_project_ref(value, current_account_id: int) -> tuple[int, str, bool]:
    """解析 ownerId:localProjectId；旧 owner 客户端仍可发送裸本地 ID。"""

    text = str(value or "").strip()
    owner_text, separator, local_project_id = text.partition(":")
    if separator and owner_text.isdigit() and int(owner_text) > 0:
        return int(owner_text), _project_id(local_project_id), False
    return int(current_account_id), _project_id(text), True


def _project_permissions(role: str) -> dict:
    normalized = str(role or "")
    return {
        "can_view": normalized in PROJECT_ROLES,
        "can_capture": normalized in CAPTURE_ROLES,
        "can_manage_members": normalized in MANAGE_MEMBER_ROLES,
    }


def _transfer_profile(*values) -> str:
    """解析新版传输契约；空值专门保留给升级前已落盘的旧队列。"""

    profile = ""
    for value in values:
        profile = _safe_text(value, 40).lower()
        if profile:
            break
    if not profile:
        return ""
    if profile != JPEG_1M_TRANSFER_PROFILE:
        raise ApiProblem("invalid_transfer_profile", "影像传输规格不受支持")
    return profile


def _machine_id(value) -> str:
    return _safe_text(value, 160).upper()


def _require_active_machine(conn, account_id: int, machine_id: str) -> str:
    normalized = _machine_id(machine_id)
    if not normalized:
        raise ApiProblem(
            "desktop_machine_required", "必须由已绑定的工程电脑请求原图", 403
        )
    row = conn.execute(
        "SELECT 1 FROM machines WHERE account_id = ? AND machine_id = ? AND active = 1",
        (account_id, normalized),
    ).fetchone()
    if not row:
        raise ApiProblem(
            "desktop_machine_not_bound", "该电脑未绑定当前账号或已被解绑", 403
        )
    return normalized


def _photo_date(value) -> str:
    text = _safe_text(value, 10)
    if not text:
        return ""
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError as exc:
        raise ApiProblem("invalid_photo_date", "照片日期必须为 YYYY-MM-DD") from exc


def _page_args():
    cursor = _integer(request.args.get("cursor"), 0, 0)
    limit = _integer(request.args.get("limit"), 30, 1, 100)
    return cursor, limit


def _account_payload(user: dict) -> dict:
    return {
        "id": int(user["id"]),
        "username": user["username"],
        "display_name": user.get("display_name", ""),
        "role": user.get("role", "user"),
    }


def _project_payload(row) -> dict:
    item = dict(row)
    owner_account_id = int(
        item.get("project_owner_account_id") or item.get("account_id") or 0
    )
    local_project_id = item["project_id"]
    project_ref = _project_ref(owner_account_id, local_project_id)
    access_role = str(item.get("access_role") or "owner")
    permissions = _project_permissions(access_role)
    member_count = int(item.get("member_count") or 1)
    return {
        "id": project_ref,
        "project_id": project_ref,
        "project_ref": project_ref,
        "local_project_id": local_project_id,
        "owner_account_id": owner_account_id,
        "project_code": item["project_code"],
        "project_name": item["project_name"],
        "snapshot_id": item["snapshot_id"],
        "revision": int(item["revision"] or 0),
        "desktop_machine_id": item.get("desktop_machine_id", ""),
        "active": bool(item["active"]),
        "updated_at": item["updated_at"],
        "metadata": _json(item.get("metadata_json"), {}),
        "access_role": access_role,
        "member_count": member_count,
        **permissions,
        "membership": {
            "role": access_role,
            "member_count": member_count,
            "joined_at": item.get("joined_at", ""),
            "permissions": permissions,
        },
    }


def _requirement_payload(row) -> dict:
    item = dict(row)
    return {
        "template_code": item.get("template_code", ""),
        "industry": item.get("industry", ""),
        "project_type": item.get("project_type", ""),
        "phase": item.get("phase", ""),
        "division": item.get("division", ""),
        "subdivision": item.get("subdivision", ""),
        "item": item.get("item", ""),
        "process": item.get("process", ""),
        "photo_requirement_name": item.get("requirement_name", ""),
        "required_type": item.get("required_type", "recommended"),
        "condition": item.get("condition_text", ""),
        "min_photo_count": int(item.get("min_photo_count") or 0),
        "recommended_photo_count": int(item.get("recommended_count") or 0),
        "shot_types": item.get("shot_types", ""),
        "timing": item.get("timing", ""),
        "before_concealment_required": (
            "是" if int(item.get("before_concealment") or 0) else "否"
        ),
        "gps_required": "是" if int(item.get("gps_required") or 0) else "否",
        "exif_required": "是" if int(item.get("exif_required") or 0) else "否",
        "description_template": item.get("description_template", ""),
        "standard_source": item.get("standard_source", ""),
        "template_version": item.get("template_version", "V1.0"),
    }


def _assignment_from_row(row) -> dict:
    return _json(dict(row).get("assignment_json"), {})


def _photo_payload(row, download_url="", *, conn=None) -> dict:
    item = dict(row)
    assignment = _json(item.pop("assignment_json", "{}"), {})
    if conn is not None:
        assignment = _hydrate_assignment(conn, item, assignment)
    match = _json(item.pop("match_json", "{}"), {})
    preview_sha = item.get("preview_sha256") or item["sha256"]
    preview_size = int(item.get("preview_size_bytes") or item["size_bytes"])
    preview_width = int(item.get("preview_width") or item["width"] or 0)
    preview_height = int(item.get("preview_height") or item["height"] or 0)
    owner_account_id = int(
        item.get("project_owner_account_id") or item.get("account_id") or 0
    )
    local_project_id = item["project_id"]
    project_ref = _project_ref(owner_account_id, local_project_id)
    project_code = item.get("project_code", "")
    project_name = item.get("project_name", "")
    if conn is not None and (not project_code or not project_name):
        project_row = conn.execute(
            "SELECT project_code, project_name FROM cloud_engineering_projects "
            "WHERE account_id = ? AND project_id = ?",
            (owner_account_id, local_project_id),
        ).fetchone()
        if project_row:
            project_code = project_row["project_code"]
            project_name = project_row["project_name"]
    payload = {
        "cursor": int(item["id"]),
        "photo_uuid": item["photo_uuid"],
        "batch_id": item["batch_id"],
        "project_id": project_ref,
        "project_ref": project_ref,
        "local_project_id": local_project_id,
        "owner_account_id": owner_account_id,
        "project_code": project_code,
        "project_name": project_name,
        "source": item["source"],
        "scope": item["scope"],
        "category": item["category"],
        "assignment": assignment,
        "hierarchy": {
            "contract_code": assignment.get("contract_code", ""),
            "contract_name": assignment.get("contract_name", ""),
            "unit_project_code": assignment.get("unit_project_code", ""),
            "unit_project_name": assignment.get("unit_project_name", ""),
            "part_code": assignment.get("part_code", ""),
            "part_name": assignment.get("part_name", ""),
            "unit_code": assignment.get("unit_code", ""),
            "unit_name": assignment.get("unit_name", ""),
            "process_code": assignment.get("process_code", ""),
            "process_name": assignment.get("process_name", ""),
            "other_node_code": assignment.get("other_node_code", ""),
            "other_node_name": assignment.get("other_node_name", ""),
        },
        "contract_code": assignment.get("contract_code", ""),
        "contract_name": assignment.get("contract_name", ""),
        "unit_project_code": assignment.get("unit_project_code", ""),
        "unit_project_name": assignment.get("unit_project_name", ""),
        "part_code": assignment.get("part_code", ""),
        "part_name": assignment.get("part_name", ""),
        "unit_code": assignment.get("unit_code", ""),
        "unit_name": assignment.get("unit_name", ""),
        "process_code": assignment.get("process_code", ""),
        "process_name": assignment.get("process_name", ""),
        "other_node_code": assignment.get("other_node_code", ""),
        "other_node_name": assignment.get("other_node_name", ""),
        "requirement": (
            {
                "template_code": item.get("requirement_code", ""),
                "photo_requirement_name": item.get("requirement_name", ""),
            }
            if item.get("requirement_code")
            else None
        ),
        "requirement_code": item.get("requirement_code", ""),
        "requirement_name": item.get("requirement_name", ""),
        "title": item["title"],
        "photo_date": item["photo_date"],
        "photographer": item.get("photographer", ""),
        "photographer_account_id": int(
            item.get("photographer_account_id") or 0
        ),
        "uploaded_by": item.get("uploaded_by", ""),
        "uploaded_by_account_id": int(
            item.get("uploaded_by_account_id") or item.get("account_id") or 0
        ),
        "capture_source": item.get("capture_source", ""),
        "client_captured_at": item["client_captured_at"],
        "orientation": int(item["orientation"] or 1),
        "width": preview_width,
        "height": preview_height,
        "sha256": preview_sha,
        "size_bytes": preview_size,
        "mime_type": "image/jpeg",
        "preview_sha256": preview_sha,
        "preview_size_bytes": preview_size,
        "preview_width": preview_width,
        "preview_height": preview_height,
        "status": item["status"],
        "match": match,
        "match_candidates": match.get("candidates", []),
        "error": {
            "code": item["error_code"],
            "message": item["error_message"],
        }
        if item["error_code"] or item["error_message"]
        else None,
        "created_at": item["created_at"],
        "updated_at": item["updated_at"],
        "desktop_imported_at": item["desktop_imported_at"],
        "local_project_code": item.get("local_project_code", ""),
        "local_photo_id": item.get("local_photo_id", ""),
        "deleted_at": item.get("deleted_at", ""),
        "original_cleanup_status": item.get("original_cleanup_status", ""),
        "archive": {
            "status": item["status"],
            "target_machine_id": item.get("target_machine_id", ""),
            "desktop_imported_at": item["desktop_imported_at"],
            "local_project_code": item.get("local_project_code", ""),
            "local_photo_id": item.get("local_photo_id", ""),
        },
    }
    if download_url:
        payload["download_url"] = download_url
    return payload


def _tree_from_rows(rows) -> list[dict]:
    nodes = {}
    ordered = []
    for row in rows:
        raw = dict(row)
        node = {
            "code": raw["node_code"],
            "node_code": raw["node_code"],
            "parent_code": raw["parent_code"],
            "type": raw["node_type"],
            "node_type": raw["node_type"],
            "name": raw["name"],
            "sort_order": int(raw["sort_order"] or 0),
            "metadata": _json(raw["metadata_json"], {}),
            "children": [],
        }
        nodes[raw["node_code"]] = node
        ordered.append(node)
    roots = []
    for node in ordered:
        parent = nodes.get(node["parent_code"])
        if parent:
            parent["children"].append(node)
        else:
            roots.append(node)
    return roots


def _node_code(node: dict, node_type: str, parent: str, index: int) -> str:
    raw = (
        node.get("node_code")
        or node.get("unit_code")
        or node.get("code")
        or node.get("internal_project_code")
    )
    if raw:
        return _safe_text(raw, 160)
    name = _safe_text(node.get("name") or node.get("title"), 200)
    digest = hashlib.sha1(f"{parent}|{node_type}|{name}|{index}".encode("utf-8")).hexdigest()[:16]
    return f"{node_type}:{digest}"


def _flatten_snapshot(tree, other_tree):
    result = []

    def add(node, scope, node_type, parent, index, children_key="children"):
        if isinstance(node, str):
            node = {"name": node}
        if not isinstance(node, dict):
            return
        code = _node_code(node, node_type, parent, index)
        name = _safe_text(
            node.get("name")
            or node.get("unit_name")
            or node.get("project_name")
            or node.get("title"),
            300,
        )
        excluded = {
            "children", "unit_projects", "parts", "units", "processes",
            "node_code", "unit_code", "code", "name", "title",
        }
        metadata = {key: value for key, value in node.items() if key not in excluded}
        result.append(
            {
                "scope": scope,
                "node_code": code,
                "parent_code": parent,
                "node_type": node_type,
                "name": name,
                "sort_order": _integer(node.get("sort_order"), index, 0, 10**7),
                "metadata": metadata,
            }
        )
        children = node.get(children_key) or []
        for child_index, child in enumerate(children):
            add(child, scope, "node", code, child_index)

    for contract_index, contract in enumerate(tree or []):
        if not isinstance(contract, dict):
            continue
        contract_code = _node_code(contract, "contract", "", contract_index)
        add({**contract, "node_code": contract_code}, "engineering", "contract", "", contract_index, "__none__")
        for unit_index, unit_project in enumerate(contract.get("unit_projects") or contract.get("children") or []):
            unit_project = unit_project if isinstance(unit_project, dict) else {"name": unit_project}
            unit_project_code = _node_code(unit_project, "unit_project", contract_code, unit_index)
            add({**unit_project, "node_code": unit_project_code}, "engineering", "unit_project", contract_code, unit_index, "__none__")
            for part_index, part in enumerate(unit_project.get("parts") or unit_project.get("children") or []):
                part = part if isinstance(part, dict) else {"name": part}
                part_code = _node_code(part, "part", unit_project_code, part_index)
                add({**part, "node_code": part_code}, "engineering", "part", unit_project_code, part_index, "__none__")
                for leaf_index, unit in enumerate(part.get("units") or part.get("children") or []):
                    unit = unit if isinstance(unit, dict) else {"name": unit}
                    unit_code = _node_code(unit, "unit", part_code, leaf_index)
                    add({**unit, "node_code": unit_code}, "engineering", "unit", part_code, leaf_index, "__none__")
                    for process_index, process in enumerate(unit.get("processes") or []):
                        process = process if isinstance(process, dict) else {"name": process}
                        process_name = _safe_text(process.get("name"), 200)
                        process_code = f"{unit_code}::process::{hashlib.sha1(process_name.encode('utf-8')).hexdigest()[:12]}"
                        add({**process, "node_code": process_code}, "engineering", "process", unit_code, process_index, "__none__")

    def add_other(node, parent, index):
        if isinstance(node, str):
            node = {"name": node}
        if not isinstance(node, dict):
            return
        code = _node_code(node, "other", parent, index)
        add({**node, "node_code": code}, "other", "other", parent, index, "__none__")
        for child_index, child in enumerate(node.get("children") or []):
            add_other(child, code, child_index)

    for other_index, other_node in enumerate(other_tree or []):
        add_other(other_node, "", other_index)
    return result


def _exchange_wechat_code(code: str, app_id: str) -> dict:
    code = _safe_text(code, 256)
    app_id = _safe_text(app_id, 128)
    if not code or not app_id:
        raise ApiProblem("wechat_code_required", "缺少微信登录 code 或 app_id")
    if config.WECHAT_MOCK_ENABLED:
        digest = hashlib.sha256(f"{app_id}|{code}".encode("utf-8")).hexdigest()
        return {"openid": f"mock_{digest[:32]}", "unionid": ""}
    if not config.WECHAT_APP_ID or not config.WECHAT_APP_SECRET:
        raise ApiProblem("wechat_not_configured", "微信登录尚未配置", 503, True)
    if app_id != config.WECHAT_APP_ID:
        raise ApiProblem("wechat_app_mismatch", "微信小程序 app_id 不匹配", 403)
    query = urllib.parse.urlencode(
        {
            "appid": config.WECHAT_APP_ID,
            "secret": config.WECHAT_APP_SECRET,
            "js_code": code,
            "grant_type": "authorization_code",
        }
    )
    try:
        with urllib.request.urlopen(
            "https://api.weixin.qq.com/sns/jscode2session?" + query, timeout=8
        ) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, urllib.error.URLError, ValueError) as exc:
        raise ApiProblem("wechat_unavailable", "微信登录服务暂时不可用", 503, True) from exc
    if payload.get("errcode") or not payload.get("openid"):
        raise ApiProblem("wechat_code_invalid", "微信登录凭证无效或已过期", 401)
    return {"openid": str(payload["openid"]), "unionid": str(payload.get("unionid") or "")}


def _assignment_node(
    conn,
    account_id: int,
    project_id: str,
    scope: str,
    node_code: str,
    node_type: str = "",
    *,
    active_only: bool,
):
    clauses = [
        "account_id = ?",
        "project_id = ?",
        "scope = ?",
        "node_code = ?",
    ]
    params = [account_id, project_id, scope, node_code]
    if node_type:
        clauses.append("node_type = ?")
        params.append(node_type)
    if active_only:
        clauses.append("active = 1")
    return conn.execute(
        "SELECT * FROM cloud_units WHERE " + " AND ".join(clauses), params
    ).fetchone()


def _engineering_assignment(
    conn,
    account_id: int,
    project_id: str,
    assignment: dict,
    *,
    active_only: bool,
    strict: bool,
    require_process: bool = False,
) -> dict | None:
    unit_code = _safe_text(assignment.get("unit_code"), 160)
    if not unit_code:
        if strict:
            raise ApiProblem("assignment_required", "请选择单元工程")
        return None
    unit = _assignment_node(
        conn,
        account_id,
        project_id,
        "engineering",
        unit_code,
        "unit",
        active_only=active_only,
    )
    if not unit:
        if strict:
            raise ApiProblem("unit_not_found", "单元工程不存在或已停用", 404)
        return None

    part = _assignment_node(
        conn,
        account_id,
        project_id,
        "engineering",
        unit["parent_code"],
        "part",
        active_only=active_only,
    )
    unit_project = (
        _assignment_node(
            conn,
            account_id,
            project_id,
            "engineering",
            part["parent_code"],
            "unit_project",
            active_only=active_only,
        )
        if part
        else None
    )
    contract = (
        _assignment_node(
            conn,
            account_id,
            project_id,
            "engineering",
            unit_project["parent_code"],
            "contract",
            active_only=active_only,
        )
        if unit_project
        else None
    )
    if strict and (not part or not unit_project or not contract):
        raise ApiProblem(
            "unit_hierarchy_incomplete",
            "该单元工程缺少合同、单位工程或分部工程层级，请先从电脑重新同步",
            409,
        )

    process_code = _safe_text(assignment.get("process_code"), 160)
    process_name = _safe_text(assignment.get("process_name"), 200)
    process = None
    if process_code:
        process = _assignment_node(
            conn,
            account_id,
            project_id,
            "engineering",
            process_code,
            "process",
            active_only=active_only,
        )
        if process and process["parent_code"] != unit_code:
            process = None
    elif process_name:
        active_clause = "AND active = 1 " if active_only else ""
        process = conn.execute(
            "SELECT * FROM cloud_units WHERE account_id = ? AND project_id = ? "
            "AND scope = 'engineering' AND node_type = 'process' AND parent_code = ? "
            "AND name = ? " + active_clause + "ORDER BY id LIMIT 1",
            (account_id, project_id, unit_code, process_name),
        ).fetchone()
    if (process_code or process_name) and not process:
        if strict:
            raise ApiProblem("process_not_found", "工序不存在或已停用", 404)
        # 旧记录展示时，无法从工程树确认的工序不是可信补全值。返回空值，
        # 由 hydrate 的非空合并保留照片原有历史文本。
        process_code = ""
        process_name = ""
    elif process:
        process_code = process["node_code"]
        process_name = process["name"]
    if strict and require_process and not process:
        active_process = conn.execute(
            "SELECT 1 FROM cloud_units WHERE account_id = ? AND project_id = ? "
            "AND scope = 'engineering' AND node_type = 'process' "
            "AND parent_code = ? AND active = 1 LIMIT 1",
            (account_id, project_id, unit_code),
        ).fetchone()
        if active_process:
            raise ApiProblem("process_required", "该单元工程必须选择工序")

    def code(row):
        return row["node_code"] if row else ""

    def name(row):
        return row["name"] if row else ""

    return {
        "contract_code": code(contract),
        "contract_name": name(contract),
        "unit_project_code": code(unit_project),
        "unit_project_name": name(unit_project),
        "part_code": code(part),
        "part_name": name(part),
        "unit_code": unit["node_code"],
        "unit_name": unit["name"],
        "process_code": process_code,
        "process_name": process_name,
    }


def _hydrate_assignment(conn, row, assignment: dict) -> dict:
    """为旧照片按服务器工程树补齐可信名称；树缺失时保留历史 JSON。"""

    item = dict(row)
    assignment = dict(assignment or {})
    owner_account_id = int(
        item.get("project_owner_account_id") or item.get("account_id") or 0
    )
    if item.get("scope") == "engineering":
        resolved = _engineering_assignment(
            conn,
            owner_account_id,
            item.get("project_id", ""),
            assignment,
            active_only=False,
            strict=False,
        )
        if not resolved:
            return assignment
        # 工程树可能只同步了单元而缺少部分祖先。仅让非空、已解析字段覆盖，
        # 避免用解析失败产生的空字符串抹掉旧照片已有的合同/单位/分部名称。
        trusted = {key: value for key, value in resolved.items() if value}
        return {**assignment, **trusted}
    other_node_code = _safe_text(assignment.get("other_node_code"), 160)
    if not other_node_code:
        return assignment
    node = _assignment_node(
        conn,
        owner_account_id,
        item.get("project_id", ""),
        "other",
        other_node_code,
        active_only=False,
    )
    if not node:
        return assignment
    return {
        **assignment,
        "other_node_code": node["node_code"],
        "other_node_name": node["name"],
    }


def _validate_assignment(
    conn,
    account_id: int,
    project_id: str,
    scope: str,
    assignment,
    *,
    require_process: bool = False,
) -> dict:
    assignment = assignment if isinstance(assignment, dict) else {}
    if scope == "engineering":
        return _engineering_assignment(
            conn,
            account_id,
            project_id,
            assignment,
            active_only=True,
            strict=True,
            require_process=require_process,
        )
    other_node_code = _safe_text(assignment.get("other_node_code"), 160)
    if not other_node_code:
        raise ApiProblem("assignment_required", "请选择其它影像目录")
    node = _assignment_node(
        conn,
        account_id,
        project_id,
        "other",
        other_node_code,
        active_only=True,
    )
    if not node:
        raise ApiProblem("other_node_not_found", "其它影像目录不存在或已停用", 404)
    return {
        "other_node_code": node["node_code"],
        "other_node_name": node["name"],
    }


def _read_image_upload(
    file_storage,
    claimed_sha: str,
    *,
    max_bytes: int,
    max_pixels: int,
    max_edge: int,
    preview_only: bool = False,
    require_jpeg: bool = False,
    require_claimed_sha: bool = True,
):
    if not file_storage:
        raise ApiProblem("file_required", "缺少图片文件")
    stream = tempfile.SpooledTemporaryFile(
        max_size=config.MOBILE_UPLOAD_SPOOL_BYTES, mode="w+b"
    )
    digest = hashlib.sha256()
    total = 0
    try:
        while True:
            chunk = file_storage.stream.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > max_bytes:
                limit_label = (
                    f"{max_bytes // (1024 * 1024)}MB"
                    if max_bytes >= 1024 * 1024
                    else f"{max_bytes // 1024}KB"
                )
                raise ApiProblem(
                    "preview_too_large" if preview_only else "original_too_large",
                    f"图片不能超过 {limit_label}",
                    413,
                )
            digest.update(chunk)
            stream.write(chunk)
    except Exception:
        stream.close()
        raise
    if not total:
        stream.close()
        raise ApiProblem("empty_image", "图片内容为空")
    claimed = str(claimed_sha or "").strip().lower()
    if claimed and not re.fullmatch(r"[0-9a-f]{64}", claimed):
        stream.close()
        raise ApiProblem("sha256_required", "缺少有效的图片 SHA-256")
    actual = digest.hexdigest()
    if require_claimed_sha and not claimed:
        stream.close()
        raise ApiProblem("sha256_required", "缺少有效的图片 SHA-256")
    if claimed and claimed != actual:
        stream.close()
        raise ApiProblem("sha256_mismatch", "图片校验值不一致，请重新上传", 422, True)

    stream.seek(0)
    signature = stream.read(16)
    is_jpeg = signature.startswith(b"\xff\xd8")
    is_png = signature.startswith(b"\x89PNG\r\n\x1a\n")
    if preview_only and not is_jpeg:
        stream.close()
        raise ApiProblem("preview_jpeg_required", "电脑端查看副本必须是 JPEG", 415)
    if require_jpeg and not is_jpeg:
        stream.close()
        raise ApiProblem(
            "archive_jpeg_required", "新版归档影像必须是 JPEG", 415
        )
    if not preview_only and not (is_jpeg or is_png):
        stream.close()
        raise ApiProblem(
            "unsupported_original_format",
            "原图仅支持静态 JPEG 或 PNG，不支持 HEIC、WebP、GIF 或其它格式",
            415,
        )

    try:
        stream.seek(0)
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(stream) as image:
                expected_format = "JPEG" if is_jpeg else "PNG"
                if image.format != expected_format:
                    raise ApiProblem("invalid_image", "图片扩展格式与实际内容不一致", 422)
                if bool(getattr(image, "is_animated", False)) or int(
                    getattr(image, "n_frames", 1) or 1
                ) != 1:
                    raise ApiProblem("animated_image_rejected", "不支持动图", 415)
                width, height = image.size
                if width < 1 or height < 1:
                    raise ApiProblem("invalid_dimensions", "图片尺寸不受支持", 422)
                if max(width, height) > max_edge or width * height > max_pixels:
                    raise ApiProblem(
                        "image_dimensions_exceeded",
                        "图片像素尺寸超过服务器安全上限",
                        422,
                    )
                image.verify()
            stream.seek(0)
            with Image.open(stream) as image:
                image.load()
    except ApiProblem:
        stream.close()
        raise
    except (
        UnidentifiedImageError,
        OSError,
        ValueError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
    ) as exc:
        stream.close()
        raise ApiProblem("invalid_image", "图片损坏或无法完整解码", 422) from exc
    stream.seek(0)
    image_format = "JPEG" if is_jpeg else "PNG"
    return {
        "stream": stream,
        "sha256": actual,
        "size_bytes": total,
        "width": width,
        "height": height,
        "format": image_format,
        "extension": ".jpg" if image_format == "JPEG" else ".png",
        "mime_type": "image/jpeg" if image_format == "JPEG" else "image/png",
    }


def _jpeg_bytes(image, quality: int) -> bytes:
    output = io.BytesIO()
    image.save(
        output,
        "JPEG",
        quality=quality,
        optimize=True,
        progressive=False,
        subsampling="4:2:0",
    )
    return output.getvalue()


def _make_preview(original) -> dict:
    """从已完整验证的原图生成最高可用质量的永久 JPEG 预览。"""
    original["stream"].seek(0)
    with Image.open(original["stream"]) as opened:
        oriented = ImageOps.exif_transpose(opened)
        if oriented.mode in {"RGBA", "LA"} or (
            oriented.mode == "P" and "transparency" in oriented.info
        ):
            rgba = oriented.convert("RGBA")
            image = Image.new("RGB", rgba.size, "white")
            image.paste(rgba, mask=rgba.getchannel("A"))
        else:
            image = oriented.convert("RGB")

    resampling = getattr(Image, "Resampling", Image).LANCZOS
    image.thumbnail(
        (config.MOBILE_PREVIEW_MAX_EDGE, config.MOBILE_PREVIEW_MAX_EDGE),
        resampling,
    )
    while True:
        lowest = _jpeg_bytes(image, 30)
        if len(lowest) <= config.MOBILE_PREVIEW_MAX_BYTES:
            best_data = lowest
            best_quality = 30
            low, high = 31, 90
            while low <= high:
                quality = (low + high) // 2
                candidate = _jpeg_bytes(image, quality)
                if len(candidate) <= config.MOBILE_PREVIEW_MAX_BYTES:
                    best_data = candidate
                    best_quality = quality
                    low = quality + 1
                else:
                    high = quality - 1
            width, height = image.size
            image.close()
            return {
                "data": best_data,
                "sha256": hashlib.sha256(best_data).hexdigest(),
                "size_bytes": len(best_data),
                "width": width,
                "height": height,
                "quality": best_quality,
            }

        width, height = image.size
        smaller = (max(1, int(width * 0.85)), max(1, int(height * 0.85)))
        if smaller == image.size:
            image.close()
            raise ApiProblem("preview_generation_failed", "无法生成合规的预览图", 422)
        resized = image.resize(smaller, resampling)
        image.close()
        image = resized


def register_mobile_api(
    app, require_user, token_for, now_fn=None, rate_limited_fn=None
) -> None:
    """把移动端与桌面同步蓝图挂到既有 Flask 应用。"""

    blueprint = Blueprint("mobile_api", __name__)
    storage = create_storage()
    chunk_store = ChunkFileStore(
        config.MOBILE_CHUNK_DIR, config.MOBILE_UPLOAD_SPOOL_BYTES
    )
    ticket_serializer = URLSafeTimedSerializer(config.SECRET_KEY)
    now = now_fn or _utc_now

    def fail(problem: ApiProblem):
        payload = {"ok": False, "code": problem.code, "error": problem.message}
        if problem.retryable:
            payload["retryable"] = True
        return jsonify(payload), problem.status

    @blueprint.errorhandler(ApiProblem)
    def handle_api_problem(problem):
        return fail(problem)

    @blueprint.errorhandler(RequestEntityTooLarge)
    def handle_request_too_large(_problem):
        return fail(
            ApiProblem(
                "request_too_large",
                "上传请求超过服务器 51MB 安全上限",
                413,
            )
        )

    def user():
        current = require_user()
        if not current:
            raise ApiProblem("unauthorized", "未登录或登录已过期", 401)
        if (
            request.path.startswith("/api/mobile/v1/")
            and current.get("_token_scope") == "desktop_sync"
        ):
            raise ApiProblem(
                "mobile_scope_required", "电脑同步令牌无权访问微信端接口", 403
            )
        return current

    def require_desktop_client(current, requested_machine_id=""):
        """桌面原图接口拒绝微信令牌，并绑定 desktop_sync 令牌的机器。"""
        scope = str(current.get("_token_scope") or "legacy")
        requested = _machine_id(requested_machine_id)
        if scope != "desktop_sync":
            raise ApiProblem(
                "desktop_sync_token_required",
                "电脑同步接口必须使用本机激活后签发的专用令牌",
                403,
            )
        claimed = _machine_id(current.get("_token_machine_id"))
        if not requested or requested != claimed:
            raise ApiProblem(
                "desktop_token_machine_mismatch",
                "电脑同步令牌与请求机器不一致",
                403,
            )
        return requested

    def json_body():
        value = request.get_json(silent=True)
        if not isinstance(value, dict):
            raise ApiProblem("invalid_json", "请求内容必须为 JSON 对象")
        return value

    def project_record_for_owner(conn, owner_account_id, local_project_id):
        row = conn.execute(
            "SELECT * FROM cloud_engineering_projects WHERE account_id = ? "
            "AND project_id = ? AND active = 1",
            (int(owner_account_id), local_project_id),
        ).fetchone()
        if not row:
            raise ApiProblem("project_not_found", "工程不存在或无权访问", 404)
        return dict(row)

    def project_for(conn, account_id, project_reference, allowed_roles=None):
        owner_account_id, local_project_id, _legacy = _parse_project_ref(
            project_reference, account_id
        )
        row = conn.execute(
            "SELECT p.*, pm.role AS access_role, pm.joined_at, "
            "(SELECT COUNT(*) FROM project_members total_members "
            " WHERE total_members.project_owner_account_id = p.account_id "
            " AND total_members.project_id = p.project_id "
            " AND total_members.status = 'active') AS member_count "
            "FROM cloud_engineering_projects p JOIN project_members pm "
            "ON pm.project_owner_account_id = p.account_id "
            "AND pm.project_id = p.project_id "
            "WHERE p.account_id = ? AND p.project_id = ? AND p.active = 1 "
            "AND pm.member_account_id = ? AND pm.status = 'active'",
            (owner_account_id, local_project_id, int(account_id)),
        ).fetchone()
        if not row:
            # 不区分工程不存在和无成员关系，避免枚举其它账号的工程。
            raise ApiProblem("project_not_found", "工程不存在或无权访问", 404)
        project = dict(row)
        if allowed_roles and project["access_role"] not in set(allowed_roles):
            raise ApiProblem("project_permission_denied", "当前项目角色无此权限", 403)
        project["project_owner_account_id"] = int(project["account_id"])
        return project

    def project_for_desktop(conn, current, local_project_id, desktop_machine_id):
        project = project_record_for_owner(conn, current["id"], local_project_id)
        machine_id = _require_active_machine(
            conn, current["id"], desktop_machine_id
        )
        if _machine_id(project.get("desktop_machine_id")) != machine_id:
            raise ApiProblem(
                "wrong_desktop_machine", "该工程由另一台工程电脑统一归档", 403
            )
        project["project_owner_account_id"] = int(current["id"])
        return project

    def member_payload(row, current_account_id=0):
        item = dict(row)
        role = str(item.get("role") or "viewer")
        return {
            "account_id": int(item["member_account_id"]),
            "username": item.get("username", ""),
            "display_name": item.get("display_name", ""),
            "role": role,
            "joined_at": item.get("joined_at", ""),
            "is_me": int(item["member_account_id"]) == int(current_account_id or 0),
            "permissions": _project_permissions(role),
        }

    def expire_project_invitations(conn):
        conn.execute(
            "UPDATE project_invitations SET status = 'expired', updated_at = ? "
            "WHERE status = 'pending' AND expires_at <= ?",
            (now(), now()),
        )

    def project_members_rows(conn, owner_account_id, local_project_id):
        return conn.execute(
            "SELECT pm.*, a.username, a.display_name FROM project_members pm "
            "JOIN accounts a ON a.id = pm.member_account_id "
            "WHERE pm.project_owner_account_id = ? AND pm.project_id = ? "
            "AND pm.status = 'active' "
            "ORDER BY CASE pm.role WHEN 'owner' THEN 0 WHEN 'admin' THEN 1 "
            "WHEN 'capturer' THEN 2 ELSE 3 END, pm.joined_at, pm.id",
            (owner_account_id, local_project_id),
        ).fetchall()

    def normalize_invite_code(value) -> str:
        return re.sub(r"[^A-Za-z0-9]", "", str(value or "")).upper()

    def invite_code_hash(value) -> str:
        code = normalize_invite_code(value)
        if len(code) != 10:
            raise ApiProblem("project_invite_invalid", "邀请码无效或已过期", 404)
        return hashlib.sha256(code.encode("ascii")).hexdigest()

    def project_invitation_payload(conn, invitation_row, *, raw_code=""):
        invitation = dict(invitation_row)
        owner_account_id = int(invitation["project_owner_account_id"])
        local_project_id = invitation["project_id"]
        project = project_record_for_owner(
            conn, owner_account_id, local_project_id
        )
        member_count = int(
            conn.execute(
                "SELECT COUNT(*) AS total FROM project_members "
                "WHERE project_owner_account_id = ? AND project_id = ? "
                "AND status = 'active'",
                (owner_account_id, local_project_id),
            ).fetchone()["total"]
        )
        project["project_owner_account_id"] = owner_account_id
        project["access_role"] = invitation["role"]
        project["member_count"] = member_count
        inviter = conn.execute(
            "SELECT username, display_name FROM accounts WHERE id = ?",
            (invitation["created_by_account_id"],),
        ).fetchone()
        payload = {
            "invite_id": int(invitation["id"]),
            "role": invitation["role"],
            "status": invitation["status"],
            "expires_at": invitation["expires_at"],
            "project": _project_payload(project),
            "inviter_name": (
                (inviter["display_name"] or inviter["username"]) if inviter else ""
            ),
        }
        if raw_code:
            payload["code"] = raw_code
        return payload

    def create_project_invitation(
        conn, current, project, role, *, expires_in=PROJECT_INVITE_TTL_SECONDS
    ):
        role = _safe_text(role, 20)
        if role not in INVITABLE_ROLES:
            raise ApiProblem("invalid_project_role", "邀请角色无效")
        actor_role = str(project.get("access_role") or "owner")
        if actor_role == "admin" and role == "admin":
            raise ApiProblem(
                "project_permission_denied", "只有负责人可以邀请管理员", 403
            )
        pending_count = int(
            conn.execute(
                "SELECT COUNT(*) AS total FROM project_invitations WHERE "
                "project_owner_account_id = ? AND project_id = ? AND status = 'pending'",
                (project["account_id"], project["project_id"]),
            ).fetchone()["total"]
        )
        if pending_count >= 50:
            raise ApiProblem("project_invite_limit", "当前工程待使用邀请码过多", 409)
        raw_code = ""
        code_hash = ""
        for _attempt in range(10):
            raw_code = "".join(
                secrets.choice(PROJECT_INVITE_CODE_ALPHABET) for _ in range(10)
            )
            code_hash = hashlib.sha256(raw_code.encode("ascii")).hexdigest()
            if not conn.execute(
                "SELECT 1 FROM project_invitations WHERE invite_code_hash = ?",
                (code_hash,),
            ).fetchone():
                break
        else:
            raise ApiProblem("project_invite_failed", "邀请码生成失败，请重试", 503, True)
        timestamp = now()
        cur = conn.execute(
            "INSERT INTO project_invitations "
            "(project_owner_account_id, project_id, invite_code_hash, role, status, "
            "created_by_account_id, created_at, updated_at, expires_at) "
            "VALUES (?, ?, ?, ?, 'pending', ?, ?, ?, ?)",
            (
                project["account_id"],
                project["project_id"],
                code_hash,
                role,
                current["id"],
                timestamp,
                timestamp,
                _future_timestamp(timestamp, int(expires_in)),
            ),
        )
        row = conn.execute(
            "SELECT * FROM project_invitations WHERE id = ?", (cur.lastrowid,)
        ).fetchone()
        return project_invitation_payload(conn, row, raw_code=raw_code)

    def capture_requirement_for(conn, account_id, project_id, raw_requirement):
        if not isinstance(raw_requirement, dict):
            return {}
        template_code = _safe_text(raw_requirement.get("template_code"), 80)
        if not template_code:
            return {}
        row = conn.execute(
            "SELECT * FROM cloud_project_requirements WHERE account_id = ? "
            "AND project_id = ? AND template_code = ? AND active = 1",
            (account_id, project_id, template_code),
        ).fetchone()
        if not row:
            raise ApiProblem(
                "requirement_not_found",
                "所选专业采集规则不存在或已更新，请刷新清单后重试",
                404,
            )
        return {
            "template_code": row["template_code"],
            "photo_requirement_name": row["requirement_name"],
            "required_type": row["required_type"],
            "min_photo_count": int(row["min_photo_count"] or 0),
        }

    def batch_for(conn, account_id, batch_id, *, require_capture=False):
        row = conn.execute(
            "SELECT * FROM mobile_batches WHERE id = ? AND account_id = ?",
            (batch_id, account_id),
        ).fetchone()
        if not row:
            raise ApiProblem("batch_not_found", "上传批次不存在", 404)
        batch = dict(row)
        owner_account_id = int(
            batch.get("project_owner_account_id") or batch["account_id"]
        )
        project_for(
            conn,
            account_id,
            _project_ref(owner_account_id, batch["project_id"]),
            CAPTURE_ROLES if require_capture else PROJECT_ROLES,
        )
        return batch

    def signed_download_url(
        row, *, original: bool = False, viewer_account_id: int = 0
    ) -> str:
        item = dict(row)
        owner_account_id = int(
            item.get("project_owner_account_id") or item.get("account_id") or 0
        )
        if original:
            if item.get("original_cleanup_status") == "deleted":
                return ""
            key = item.get("original_storage_key", "")
            if not key and item.get("original_cleanup_status") == "legacy_shared":
                key = item.get("storage_key", "")
            salt = "desktop-original-download"
            endpoint = "mobile_api.local_original_file"
        else:
            key = item.get("preview_storage_key") or item.get("storage_key", "")
            salt = "mobile-photo-download"
            endpoint = "mobile_api.local_photo_file"
        if not key:
            return ""
        # 手机预览统一走 API 同域代理，微信后台只需配置
        # api.shuiliyingxiang.cn；私有 OSS 主机不再成为小程序合法域名阻塞项。
        # 原图只供电脑拉取，OSS 后端仍使用短时直签以避免服务器转发大文件。
        if storage.backend == "oss" and original:
            try:
                return storage.signed_url(key, config.MOBILE_DOWNLOAD_URL_TTL)
            except StorageError as exc:
                raise ApiProblem(
                    "storage_unavailable",
                    "图片下载地址暂时不可用，请稍后重试",
                    503,
                    True,
                ) from exc
        token = ticket_serializer.dumps(
            {
                "uploader_account_id": int(item["account_id"]),
                "project_owner_account_id": owner_account_id,
                "project_id": item["project_id"],
                "photo_uuid": item["photo_uuid"],
                "target_machine_id": item.get("target_machine_id", "") if original else "",
                "viewer_account_id": 0 if original else int(viewer_account_id or 0),
            },
            salt=salt,
        )
        return url_for(
            endpoint,
            photo_uuid=item["photo_uuid"],
            token=token,
            _external=False,
        )

    def preview_download_url(row, viewer_account_id=0) -> str:
        return signed_download_url(
            row, original=False, viewer_account_id=viewer_account_id
        )

    def hydrated_photo_payload(row, viewer_account_id=0) -> dict:
        payload_conn = db.connect()
        try:
            return _photo_payload(
                row,
                preview_download_url(row, viewer_account_id),
                conn=payload_conn,
            )
        finally:
            payload_conn.close()

    def original_download_url(row) -> str:
        return signed_download_url(row, original=True)

    def desktop_photo_payload(conn, row) -> dict:
        item = dict(row)
        payload = _photo_payload(row, conn=conn)
        payload["project_ref"] = _project_ref(
            int(item.get("project_owner_account_id") or item["account_id"]),
            item["project_id"],
        )
        # 桌面端本地工程查找继续使用原有 project_id；canonical 引用单独返回。
        payload["project_id"] = item["project_id"]
        payload["local_project_id"] = item["project_id"]
        original_sha = item.get("original_sha256", "")
        original_size = int(item.get("original_size_bytes") or 0)
        url = original_download_url(row)
        payload.update(
            {
                "width": int(item.get("width") or 0),
                "height": int(item.get("height") or 0),
                "sha256": original_sha,
                "size_bytes": original_size,
                "mime_type": item.get("original_mime_type") or "image/jpeg",
                "original_sha256": original_sha,
                "original_size_bytes": original_size,
                "original_filename": item.get("original_filename", ""),
                "original_mime_type": item.get("original_mime_type") or "image/jpeg",
                "target_machine_id": item.get("target_machine_id", ""),
                "download_url": url,
                "original_download_url": url,
                "original_available": bool(url),
            }
        )
        return payload

    def batch_payload(conn, batch_row) -> dict:
        batch = dict(batch_row)
        owner_account_id = int(
            batch.get("project_owner_account_id") or batch["account_id"]
        )
        project_reference = _project_ref(owner_account_id, batch["project_id"])
        photos = conn.execute(
            "SELECT * FROM cloud_photos WHERE account_id = ? AND batch_id = ? ORDER BY id",
            (batch["account_id"], batch["id"]),
        ).fetchall()
        status_counts = {}
        photo_items = []
        for photo in photos:
            status_counts[photo["status"]] = status_counts.get(photo["status"], 0) + 1
            photo_items.append(
                _photo_payload(
                    photo,
                    preview_download_url(photo, batch["account_id"]),
                    conn=conn,
                )
            )
        return {
            "id": int(batch["id"]),
            "batch_id": int(batch["id"]),
            "client_batch_id": batch["client_batch_id"],
            "project_id": project_reference,
            "project_ref": project_reference,
            "local_project_id": batch["project_id"],
            "owner_account_id": owner_account_id,
            "scope": batch["scope"],
            "category": batch["category"],
            "mode": batch["mode"],
            "transfer_profile": batch.get("transfer_profile", ""),
            "target_machine_id": batch.get("target_machine_id", ""),
            "assignment": _json(batch["assignment_json"], {}),
            "requirement": (
                {
                    "template_code": batch.get("requirement_code", ""),
                    "photo_requirement_name": batch.get("requirement_name", ""),
                }
                if batch.get("requirement_code")
                else None
            ),
            "status": batch["status"],
            "error": {"code": batch["error_code"], "message": batch["error_message"]}
            if batch["error_code"] or batch["error_message"]
            else None,
            "progress": {
                "total": len(photos),
                "server_saved": sum(
                    count
                    for key, count in status_counts.items()
                    if key not in {"failed", "local_ready", "uploading"}
                ),
                "needs_review": status_counts.get("needs_review", 0),
                "desktop_pending": status_counts.get("desktop_pending", 0),
                "desktop_imported": status_counts.get("desktop_imported", 0),
                "failed": status_counts.get("failed", 0),
            },
            "photos": photo_items,
            "created_at": batch["created_at"],
            "updated_at": batch["updated_at"],
        }

    def insert_photo(
        *, current_user, photo_uuid, project_id, scope, category, assignment,
        title, photo_date, client_captured_at, orientation, source, batch_id,
        file_storage, claimed_sha, claimed_size="", target_machine_id="",
        original_filename="", photographer="", uploaded_by="", upload_max_bytes=None,
        project_owner_account_id=0, capture_source="", transfer_profile=""
    ):
        is_mobile_original = source == "mobile"
        normalized_transfer_profile = (
            _transfer_profile(transfer_profile) if is_mobile_original else ""
        )
        mobile_upload_max_bytes = int(
            upload_max_bytes or config.MOBILE_MAX_ORIGINAL_BYTES
        )
        if normalized_transfer_profile == JPEG_1M_TRANSFER_PROFILE:
            mobile_upload_max_bytes = min(
                mobile_upload_max_bytes, config.MOBILE_JPEG_1M_MAX_BYTES
            )
        owner_account_id = int(project_owner_account_id or current_user["id"])
        actor_name = _safe_text(
            current_user.get("display_name") or current_user.get("username") or "",
            100,
        )
        raw_capture_source = str(capture_source or "").strip().lower()
        normalized_capture_source = (
            raw_capture_source
            if is_mobile_original and raw_capture_source in {"camera", "album"}
            else ("" if is_mobile_original else "desktop")
        )
        resolved_photographer = (
            actor_name
            if is_mobile_original and normalized_capture_source == "camera"
            else ("" if is_mobile_original else _safe_text(photographer, 100))
        )
        resolved_uploaded_by = (
            actor_name
            if is_mobile_original
            else _safe_text(uploaded_by or actor_name, 100)
        )
        uploaded = _read_image_upload(
            file_storage,
            claimed_sha,
            max_bytes=(
                mobile_upload_max_bytes
                if is_mobile_original
                else config.MOBILE_PREVIEW_MAX_BYTES
            ),
            max_pixels=(
                config.MOBILE_MAX_ORIGINAL_PIXELS
                if is_mobile_original
                else config.MOBILE_PREVIEW_MAX_EDGE ** 2
            ),
            max_edge=(
                config.MOBILE_MAX_ORIGINAL_EDGE
                if is_mobile_original
                else config.MOBILE_PREVIEW_MAX_EDGE
            ),
            preview_only=not is_mobile_original,
            require_jpeg=(
                is_mobile_original
                and normalized_transfer_profile == JPEG_1M_TRANSFER_PROFILE
            ),
            # 普通微信原图直传由服务端流式计算 SHA-256。这样 10MB 内照片
            # 不必先在手机主线程做一次全文件 JavaScript 哈希；分片协议仍在
            # init/finalize 阶段强制带 SHA-256，以保证断点续传的完整性。
            require_claimed_sha=not is_mobile_original,
        )
        try:
            if str(claimed_size or "").strip():
                try:
                    expected_size = int(claimed_size)
                except (TypeError, ValueError) as exc:
                    raise ApiProblem("invalid_original_size", "图片大小字段无效") from exc
                if expected_size != uploaded["size_bytes"]:
                    raise ApiProblem(
                        "original_size_mismatch", "图片大小与实际上传内容不一致", 422, True
                    )
            if is_mobile_original:
                preview = _make_preview(uploaded)
                original_key = (
                    f"accounts/{current_user['id']}/projects/{project_id}/photos/"
                    f"{photo_uuid}{uploaded['extension']}"
                )
                original_sha = uploaded["sha256"]
                original_size = uploaded["size_bytes"]
                original_mime = uploaded["mime_type"]
                cleanup_status = "pending"
            else:
                uploaded["stream"].seek(0)
                preview_data = uploaded["stream"].read()
                preview = {
                    "data": preview_data,
                    "sha256": uploaded["sha256"],
                    "size_bytes": uploaded["size_bytes"],
                    "width": uploaded["width"],
                    "height": uploaded["height"],
                    "quality": 0,
                }
                original_key = ""
                original_sha = ""
                original_size = 0
                original_mime = ""
                cleanup_status = "not_applicable"

            preview_key = (
                f"accounts/{current_user['id']}/projects/{project_id}/previews/"
                f"{photo_uuid}.jpg"
            )
            identity_sha = original_sha if is_mobile_original else preview["sha256"]

            def same_existing(existing) -> bool:
                existing_identity = (
                    existing["original_sha256"]
                    if is_mobile_original
                    else existing["preview_sha256"] or existing["sha256"]
                )
                return (
                    int(existing["account_id"]) == int(current_user["id"])
                    and int(
                        existing["project_owner_account_id"]
                        or existing["account_id"]
                    )
                    == owner_account_id
                    and existing_identity == identity_sha
                    and existing["project_id"] == project_id
                    and existing["source"] == source
                    and (
                        source != "mobile"
                        or int(existing["batch_id"] or 0) == int(batch_id or 0)
                    )
                )

            def reject_or_return(existing):
                if same_existing(existing):
                    return existing, True
                raise ApiProblem(
                    "photo_uuid_conflict",
                    "该照片 UUID 已用于其它图片、工程或上传批次",
                    409,
                )

            with _photo_upload_lock(owner_account_id, photo_uuid):
                requirement_code = ""
                requirement_name = ""
                # 第一次短连接只做账号/归属/幂等校验；对象存储网络 I/O 期间不持有
                # SQLite 写事务，登录、回执和队列状态不会被 50MB 上传阻塞。
                check_conn = db.connect()
                try:
                    existing = check_conn.execute(
                        "SELECT * FROM cloud_photos WHERE project_owner_account_id = ? "
                        "AND photo_uuid = ?",
                        (owner_account_id, photo_uuid),
                    ).fetchone()
                    if existing:
                        return reject_or_return(existing)
                    project = project_for(
                        check_conn,
                        current_user["id"],
                        _project_ref(owner_account_id, project_id),
                        CAPTURE_ROLES,
                    )
                    target = _machine_id(
                        target_machine_id or project["desktop_machine_id"]
                    )
                    if is_mobile_original:
                        if not target:
                            raise ApiProblem(
                                "project_desktop_not_bound",
                                "请先在原电脑同步工程，再从手机上传原图",
                                409,
                            )
                        _require_active_machine(
                            check_conn, owner_account_id, target
                        )
                        frozen_batch = check_conn.execute(
                            "SELECT project_owner_account_id, project_id, target_machine_id, "
                            "status, requirement_code, requirement_name FROM mobile_batches "
                            "WHERE id = ? AND account_id = ?",
                            (batch_id, current_user["id"]),
                        ).fetchone()
                        if (
                            not frozen_batch
                            or int(frozen_batch["project_owner_account_id"] or 0)
                            != owner_account_id
                            or frozen_batch["project_id"] != project_id
                            or _machine_id(frozen_batch["target_machine_id"]) != target
                        ):
                            raise ApiProblem(
                                "batch_target_conflict",
                                "上传批次的目标电脑不一致，请重新创建批次",
                                409,
                        )
                        _require_batch_uploadable(frozen_batch["status"])
                        requirement_code = str(frozen_batch["requirement_code"] or "")
                        requirement_name = str(frozen_batch["requirement_name"] or "")
                    normalized_assignment = (
                        _validate_assignment(
                            check_conn,
                            owner_account_id,
                            project_id,
                            scope,
                            assignment,
                            require_process=(
                                normalized_transfer_profile
                                == JPEG_1M_TRANSFER_PROFILE
                            ),
                        )
                        if assignment
                        or normalized_transfer_profile == JPEG_1M_TRANSFER_PROFILE
                        else {}
                    )
                finally:
                    check_conn.close()

                wrote_keys = []
                try:
                    if original_key:
                        wrote_keys.append(original_key)
                        storage.put_stream(
                            original_key,
                            uploaded["stream"],
                            uploaded["size_bytes"],
                            uploaded["mime_type"],
                        )
                    wrote_keys.append(preview_key)
                    storage.put_bytes(preview_key, preview["data"], "image/jpeg")
                except StorageError as exc:
                    for key in reversed(wrote_keys):
                        try:
                            storage.delete(key)
                        except StorageError:
                            pass
                    raise ApiProblem(
                        "storage_unavailable",
                        "图片存储暂时不可用，请稍后重试",
                        503,
                        True,
                    ) from exc

                conn = db.connect()
                preserve_written_objects = False
                try:
                    conn.execute("BEGIN IMMEDIATE")
                    existing = conn.execute(
                        "SELECT * FROM cloud_photos WHERE project_owner_account_id = ? "
                        "AND photo_uuid = ?",
                        (owner_account_id, photo_uuid),
                    ).fetchone()
                    if existing:
                        # 单 worker 进程内不应走到这里；若运维误启多 worker，不能
                        # 删除另一请求已经引用的同名对象。
                        preserve_written_objects = True
                        conn.rollback()
                        return reject_or_return(existing)

                    if is_mobile_original:
                        current_batch = conn.execute(
                            "SELECT project_owner_account_id, project_id, target_machine_id, "
                            "scope, category, transfer_profile, assignment_json, status, "
                            "requirement_code, requirement_name FROM mobile_batches "
                            "WHERE id = ? AND account_id = ?",
                            (batch_id, current_user["id"]),
                        ).fetchone()
                        if (
                            not current_batch
                            or int(current_batch["project_owner_account_id"] or 0)
                            != owner_account_id
                            or current_batch["project_id"] != project_id
                            or _machine_id(current_batch["target_machine_id"]) != target
                            or current_batch["scope"] != scope
                            or current_batch["category"] != category
                        ):
                            raise ApiProblem(
                                "batch_target_conflict",
                                "上传批次的目标电脑不一致，请重新创建批次",
                                409,
                            )
                        _require_batch_uploadable(current_batch["status"])
                        project_for(
                            conn,
                            current_user["id"],
                            _project_ref(owner_account_id, project_id),
                            CAPTURE_ROLES,
                        )
                        _require_active_machine(
                            conn, owner_account_id, target
                        )
                        current_transfer_profile = _transfer_profile(
                            current_batch["transfer_profile"],
                            normalized_transfer_profile,
                        )
                        if current_transfer_profile == JPEG_1M_TRANSFER_PROFILE:
                            if uploaded["mime_type"] != "image/jpeg":
                                raise ApiProblem(
                                    "archive_jpeg_required",
                                    "归档传输图必须为 JPEG 格式",
                                    415,
                                )
                            if uploaded["size_bytes"] > config.MOBILE_JPEG_1M_MAX_BYTES:
                                raise ApiProblem(
                                    "original_too_large",
                                    "图片不能超过 1MB",
                                    413,
                                )
                        current_assignment = _json(
                            current_batch["assignment_json"], {}
                        )
                        # 对象存储 I/O 期间 PATCH archive-info 可能已经补齐层级。
                        # 最终写事务必须采用当前批次 assignment，不能让迟到上传
                        # 以 I/O 前的旧快照落库；反向顺序则由 PATCH 同步已有照片。
                        normalized_assignment = (
                            _validate_assignment(
                                conn,
                                owner_account_id,
                                project_id,
                                scope,
                                current_assignment,
                                require_process=(
                                    current_transfer_profile
                                    == JPEG_1M_TRANSFER_PROFILE
                                ),
                            )
                            if current_assignment
                            or current_transfer_profile
                            == JPEG_1M_TRANSFER_PROFILE
                            else {}
                        )
                        requirement_code = str(current_batch["requirement_code"] or "")
                        requirement_name = str(current_batch["requirement_name"] or "")

                    timestamp = now()
                    status = (
                        "desktop_imported" if source == "desktop" else "server_saved"
                    )
                    values = {
                        "account_id": current_user["id"],
                        "project_owner_account_id": owner_account_id,
                        "batch_id": batch_id,
                        "photo_uuid": photo_uuid,
                        "project_id": project_id,
                        "source": source,
                        "scope": scope,
                        "category": category,
                        "assignment_json": _dumps(normalized_assignment),
                        "requirement_code": requirement_code,
                        "requirement_name": requirement_name,
                        "title": _safe_text(title, 200),
                        "photo_date": _photo_date(photo_date),
                        "photographer": resolved_photographer,
                        "photographer_account_id": (
                            int(current_user["id"])
                            if is_mobile_original
                            and normalized_capture_source == "camera"
                            else 0
                        ),
                        "uploaded_by": resolved_uploaded_by,
                        "uploaded_by_account_id": int(current_user["id"]),
                        "capture_source": normalized_capture_source,
                        "client_captured_at": _safe_text(client_captured_at, 40),
                        "orientation": _integer(orientation, 1, 1, 8),
                        "width": uploaded["width"],
                        "height": uploaded["height"],
                        "original_filename": _safe_filename(
                            original_filename,
                            getattr(file_storage, "filename", ""),
                        ),
                        "sha256": preview["sha256"],
                        "size_bytes": preview["size_bytes"],
                        "storage_key": preview_key,
                        "original_sha256": original_sha,
                        "original_size_bytes": original_size,
                        "original_mime_type": original_mime,
                        "original_storage_key": original_key,
                        "preview_sha256": preview["sha256"],
                        "preview_size_bytes": preview["size_bytes"],
                        "preview_width": preview["width"],
                        "preview_height": preview["height"],
                        "preview_quality": preview["quality"],
                        "preview_storage_key": preview_key,
                        "target_machine_id": target,
                        "original_cleanup_status": cleanup_status,
                        "status": status,
                        "created_at": timestamp,
                        "updated_at": timestamp,
                        "desktop_imported_at": timestamp if source == "desktop" else "",
                    }
                    cur = conn.execute(
                        "INSERT INTO cloud_photos (account_id, batch_id, photo_uuid, "
                        "project_owner_account_id, project_id, "
                        "source, scope, category, assignment_json, requirement_code, "
                        "requirement_name, title, photo_date, photographer, "
                        "photographer_account_id, uploaded_by, uploaded_by_account_id, "
                        "capture_source, "
                        "client_captured_at, orientation, width, height, original_filename, "
                        "sha256, size_bytes, mime_type, storage_key, original_sha256, "
                        "original_size_bytes, original_mime_type, original_storage_key, "
                        "preview_sha256, preview_size_bytes, preview_width, preview_height, "
                        "preview_quality, preview_storage_key, target_machine_id, "
                        "original_cleanup_status, status, created_at, updated_at, "
                        "desktop_imported_at) VALUES (:account_id, :batch_id, :photo_uuid, "
                        ":project_owner_account_id, :project_id, :source, :scope, :category, "
                        ":assignment_json, "
                        ":requirement_code, :requirement_name, :title, :photo_date, "
                        ":photographer, :photographer_account_id, :uploaded_by, "
                        ":uploaded_by_account_id, :capture_source, "
                        ":client_captured_at, :orientation, :width, :height, "
                        ":original_filename, :sha256, :size_bytes, 'image/jpeg', :storage_key, "
                        ":original_sha256, :original_size_bytes, :original_mime_type, "
                        ":original_storage_key, :preview_sha256, :preview_size_bytes, "
                        ":preview_width, :preview_height, :preview_quality, :preview_storage_key, "
                        ":target_machine_id, :original_cleanup_status, :status, :created_at, "
                        ":updated_at, :desktop_imported_at)",
                        values,
                    )
                    if batch_id:
                        conn.execute(
                            "UPDATE mobile_batches SET status = 'server_saved', updated_at = ?, "
                            "error_code = '', error_message = '' WHERE id = ? AND account_id = ?",
                            (timestamp, batch_id, current_user["id"]),
                        )
                    # 必须在 commit 前取到完整返回行。commit 之后不再做任何
                    # 可抛异常的数据库读取，避免「行已提交却删了对象」。
                    inserted = conn.execute(
                        "SELECT * FROM cloud_photos WHERE id = ?", (cur.lastrowid,)
                    ).fetchone()
                    if not inserted:
                        raise RuntimeError("照片记录写入后无法读取")
                    conn.commit()
                    preserve_written_objects = True
                    return inserted, False
                except Exception:
                    conn.rollback()
                    if not preserve_written_objects:
                        for key in reversed(wrote_keys):
                            try:
                                storage.delete(key)
                            except StorageError:
                                pass
                    raise
                finally:
                    conn.close()
        finally:
            uploaded["stream"].close()

    def chunk_session_for(conn, account_id: int, batch_id: int, photo_uuid: str):
        row = conn.execute(
            "SELECT * FROM mobile_upload_sessions WHERE account_id = ? "
            "AND batch_id = ? AND photo_uuid = ?",
            (account_id, batch_id, photo_uuid),
        ).fetchone()
        if not row:
            raise ApiProblem("chunk_upload_not_found", "分片上传会话不存在", 404)
        return row

    def chunk_upload_payload(conn, session_row) -> dict:
        item = dict(session_row)
        uploaded = conn.execute(
            "SELECT chunk_index, sha256, size_bytes FROM mobile_upload_chunks "
            "WHERE session_id = ? ORDER BY chunk_index",
            (item["id"],),
        ).fetchall()
        return {
            "upload_id": int(item["id"]),
            "batch_id": int(item["batch_id"]),
            "photo_uuid": item["photo_uuid"],
            "status": item["status"],
            "total_size_bytes": int(item["total_size_bytes"]),
            "chunk_size_bytes": int(item["chunk_size_bytes"]),
            "total_chunks": int(item["total_chunks"]),
            "uploaded_chunks": [int(row["chunk_index"]) for row in uploaded],
            "uploaded_bytes": sum(int(row["size_bytes"]) for row in uploaded),
            "expires_at": item["expires_at"],
            "cleanup_status": item.get("cleanup_status", ""),
            "cleanup_error": item.get("cleanup_error", ""),
            "error": (
                {
                    "code": item["error_code"],
                    "message": item["error_message"],
                }
                if item["error_code"] or item["error_message"]
                else None
            ),
        }

    def comparable_chunk_metadata(value) -> dict:
        """把升级前缺少 profile 的会话与新版显式空 profile 视为同一请求。"""

        metadata = dict(_json(value, {}))
        metadata["transfer_profile"] = _transfer_profile(
            metadata.pop("transfer_profile", ""),
            metadata.pop("compression_profile", ""),
        )
        return metadata

    def cleanup_chunk_session_files(account_id: int, session_id: int) -> bool:
        """清理分片目录并持久记录结果，失败时留给后续清扫重试。"""
        cleanup_error = ""
        cleaned = False
        try:
            chunk_store.cleanup(account_id, session_id)
            cleaned = True
        except ChunkFileError as exc:
            cleanup_error = _safe_text(str(exc), 500)

        conn = db.connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "UPDATE mobile_upload_sessions SET cleanup_status = ?, "
                "cleanup_error = ?, updated_at = ? WHERE id = ? AND account_id = ?",
                (
                    "cleaned" if cleaned else "pending",
                    cleanup_error,
                    now(),
                    int(session_id),
                    int(account_id),
                ),
            )
            conn.commit()
        finally:
            conn.close()
        return cleaned

    def matching_session_photo(conn, session_row):
        session = dict(session_row)
        photo = conn.execute(
            "SELECT * FROM cloud_photos WHERE account_id = ? AND photo_uuid = ?",
            (session["account_id"], session["photo_uuid"]),
        ).fetchone()
        if not photo:
            return None
        if (
            photo["source"] == "mobile"
            and int(photo["batch_id"] or 0) == int(session["batch_id"])
            and int(photo["project_owner_account_id"] or photo["account_id"])
            == int(session["project_owner_account_id"] or session["account_id"])
            and photo["project_id"] == session["project_id"]
            and _machine_id(photo["target_machine_id"])
            == _machine_id(session["target_machine_id"])
            and photo["original_sha256"] == session["original_sha256"]
            and int(photo["original_size_bytes"] or 0)
            == int(session["total_size_bytes"])
        ):
            return photo
        raise ApiProblem(
            "photo_uuid_conflict",
            "该照片 UUID 已用于其它图片、工程或上传批次",
            409,
        )

    def require_chunk_batch_context(batch_row, session_row) -> None:
        if (
            int(batch_row["id"]) != int(session_row["batch_id"])
            or int(
                batch_row["project_owner_account_id"] or batch_row["account_id"]
            )
            != int(
                session_row["project_owner_account_id"] or session_row["account_id"]
            )
            or batch_row["project_id"] != session_row["project_id"]
            or _machine_id(batch_row["target_machine_id"])
            != _machine_id(session_row["target_machine_id"])
        ):
            raise ApiProblem(
                "batch_target_conflict",
                "分片上传会话与批次工程或目标电脑不一致",
                409,
            )

    def expire_chunk_sessions(limit: int = 100) -> None:
        """惰性回收过期会话；每个 UUID 与上传/组装共用同一进程锁。"""
        attempted_cleanup_ids = set()
        conn = db.connect()
        try:
            rows = conn.execute(
                "SELECT account_id, id, photo_uuid FROM mobile_upload_sessions "
                "WHERE status IN ('active', 'finalizing') AND expires_at <= ? "
                "ORDER BY expires_at LIMIT ?",
                (now(), int(limit)),
            ).fetchall()
        finally:
            conn.close()
        for candidate in rows:
            account_id = int(candidate["account_id"])
            session_id = int(candidate["id"])
            photo_uuid = candidate["photo_uuid"]
            should_cleanup = False
            with _chunk_session_lock(account_id, photo_uuid):
                cleanup_conn = db.connect()
                try:
                    cleanup_conn.execute("BEGIN IMMEDIATE")
                    current_row = cleanup_conn.execute(
                        "SELECT status, expires_at FROM mobile_upload_sessions "
                        "WHERE id = ? AND account_id = ?",
                        (session_id, account_id),
                    ).fetchone()
                    if (
                        current_row
                        and current_row["status"] in {"active", "finalizing"}
                        and current_row["expires_at"] <= now()
                    ):
                        timestamp = now()
                        cleanup_conn.execute(
                            "UPDATE mobile_upload_sessions SET status = 'expired', "
                            "error_code = 'chunk_upload_expired', "
                            "error_message = '分片上传会话已过期，请重新开始', "
                            "cleanup_status = 'pending', cleanup_error = '', "
                            "updated_at = ? WHERE id = ? AND account_id = ?",
                            (timestamp, session_id, account_id),
                        )
                        cleanup_conn.execute(
                            "DELETE FROM mobile_upload_chunks WHERE session_id = ?",
                            (session_id,),
                        )
                        should_cleanup = True
                    cleanup_conn.commit()
                finally:
                    cleanup_conn.close()
                if should_cleanup:
                    attempted_cleanup_ids.add(session_id)
                    cleanup_chunk_session_files(account_id, session_id)

        # 清理失败不会丢掉状态；后续任何流量都会重试，并且 pending 仍占
        # 临时空间配额，避免持续失败时把磁盘无限撑大。
        retry_conn = db.connect()
        try:
            retry_rows = retry_conn.execute(
                "SELECT account_id, id, photo_uuid FROM mobile_upload_sessions "
                "WHERE cleanup_status = 'pending' ORDER BY updated_at, id LIMIT ?",
                (int(limit),),
            ).fetchall()
        finally:
            retry_conn.close()
        for candidate in retry_rows:
            account_id = int(candidate["account_id"])
            session_id = int(candidate["id"])
            if session_id in attempted_cleanup_ids:
                continue
            with _chunk_session_lock(account_id, candidate["photo_uuid"]):
                pending_conn = db.connect()
                try:
                    still_pending = pending_conn.execute(
                        "SELECT cleanup_status FROM mobile_upload_sessions "
                        "WHERE id = ? AND account_id = ?",
                        (session_id, account_id),
                    ).fetchone()
                finally:
                    pending_conn.close()
                if still_pending and still_pending["cleanup_status"] == "pending":
                    cleanup_chunk_session_files(account_id, session_id)

    def fail_chunk_session(session_row, code: str, message: str) -> None:
        session = dict(session_row)
        conn = db.connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            changed = conn.execute(
                "UPDATE mobile_upload_sessions SET status = 'failed', error_code = ?, "
                "error_message = ?, cleanup_status = 'pending', cleanup_error = '', "
                "updated_at = ? WHERE id = ? AND account_id = ? "
                "AND status != 'completed'",
                (
                    _safe_text(code, 80),
                    _safe_text(message, 500),
                    now(),
                    session["id"],
                    session["account_id"],
                ),
            )
            if changed.rowcount:
                conn.execute(
                    "DELETE FROM mobile_upload_chunks WHERE session_id = ?",
                    (session["id"],),
                )
            conn.commit()
        finally:
            conn.close()
        if changed.rowcount:
            cleanup_chunk_session_files(session["account_id"], session["id"])

    sweep_state = {"next_at": 0.0}
    sweep_guard = threading.Lock()

    @blueprint.before_request
    def periodically_sweep_chunk_sessions():
        """有请求流量时至多每 30 秒回收一次；空闲期也不会继续增长。"""
        monotonic_now = time.monotonic()
        with sweep_guard:
            if monotonic_now < sweep_state["next_at"]:
                return None
            sweep_state["next_at"] = monotonic_now + 30.0
        try:
            expire_chunk_sessions()
        except Exception as exc:
            warnings.warn(f"分片临时目录清扫失败，将在后续请求重试: {exc}")
        return None

    def bootstrap_payload(conn, current_user) -> dict:
        projects = conn.execute(
            "SELECT p.*, pm.role AS access_role, pm.joined_at, "
            "(SELECT COUNT(*) FROM project_members total_members "
            " WHERE total_members.project_owner_account_id = p.account_id "
            " AND total_members.project_id = p.project_id "
            " AND total_members.status = 'active') AS member_count "
            "FROM cloud_engineering_projects p JOIN project_members pm "
            "ON pm.project_owner_account_id = p.account_id "
            "AND pm.project_id = p.project_id "
            "WHERE pm.member_account_id = ? AND pm.status = 'active' "
            "AND p.active = 1 ORDER BY p.updated_at DESC, p.id DESC",
            (current_user["id"],),
        ).fetchall()
        counts = conn.execute(
            "SELECT photos.status, COUNT(*) AS total FROM cloud_photos photos "
            "JOIN project_members pm "
            "ON pm.project_owner_account_id = photos.project_owner_account_id "
            "AND pm.project_id = photos.project_id "
            "WHERE photos.account_id = ? AND pm.member_account_id = ? "
            "AND pm.status = 'active' AND photos.source = 'mobile' "
            "AND photos.deleted_at = '' GROUP BY photos.status",
            (current_user["id"], current_user["id"]),
        ).fetchall()
        chunk_counts = conn.execute(
            "SELECT sessions.status, COUNT(*) AS total, "
            "COALESCE(SUM(sessions.total_size_bytes), 0) AS reserved_bytes "
            "FROM mobile_upload_sessions sessions JOIN project_members pm "
            "ON pm.project_owner_account_id = sessions.project_owner_account_id "
            "AND pm.project_id = sessions.project_id "
            "WHERE sessions.account_id = ? AND pm.member_account_id = ? "
            "AND pm.status = 'active' AND (sessions.status IN ('active', 'finalizing') "
            "OR sessions.cleanup_status = 'pending') GROUP BY sessions.status",
            (current_user["id"], current_user["id"]),
        ).fetchall()
        hierarchy_rows = conn.execute(
            "SELECT u.scope, u.node_type, COUNT(*) AS total FROM cloud_units u "
            "JOIN project_members pm ON pm.project_owner_account_id = u.account_id "
            "AND pm.project_id = u.project_id WHERE pm.member_account_id = ? "
            "AND pm.status = 'active' AND u.active = 1 GROUP BY u.scope, u.node_type",
            (current_user["id"],),
        ).fetchall()
        recent = conn.execute(
            "SELECT photos.* FROM cloud_photos photos JOIN project_members pm "
            "ON pm.project_owner_account_id = photos.project_owner_account_id "
            "AND pm.project_id = photos.project_id WHERE pm.member_account_id = ? "
            "AND pm.status = 'active' AND photos.deleted_at = '' "
            "ORDER BY photos.id DESC LIMIT 10",
            (current_user["id"],),
        ).fetchall()
        project_items = [_project_payload(row) for row in projects]
        hierarchy = {
            f"{row['scope']}_{row['node_type']}": int(row["total"])
            for row in hierarchy_rows
        }
        return {
            "account": _account_payload(current_user),
            "server_time": now(),
            "current_project": project_items[0] if project_items else None,
            "projects": project_items,
            "hierarchy_summary": hierarchy,
            "queue": {row["status"]: int(row["total"]) for row in counts},
            "chunk_queue": {
                row["status"]: {
                    "total": int(row["total"]),
                    "reserved_bytes": int(row["reserved_bytes"]),
                }
                for row in chunk_counts
            },
            "recent_uploads": [
                _photo_payload(
                    row,
                    preview_download_url(row, current_user["id"]),
                    conn=conn,
                )
                for row in recent
            ],
            "upload_contract": {
                "original_formats": ["JPEG", "PNG"],
                "original_max_bytes": config.MOBILE_MAX_ORIGINAL_BYTES,
                "direct_upload_max_bytes": config.MOBILE_DIRECT_UPLOAD_MAX_BYTES,
                "chunk_size_bytes": config.MOBILE_CHUNK_BYTES,
                "chunk_session_ttl_seconds": config.MOBILE_CHUNK_TTL_SECONDS,
                "chunk_max_active_per_account": config.MOBILE_CHUNK_MAX_ACTIVE_PER_ACCOUNT,
                "chunk_max_reserved_per_account": config.MOBILE_CHUNK_MAX_RESERVED_PER_ACCOUNT,
                "preview_mime_type": "image/jpeg",
                "preview_max_bytes": config.MOBILE_PREVIEW_MAX_BYTES,
                "preferred_transfer_profile": JPEG_1M_TRANSFER_PROFILE,
                "transfer_profiles": {
                    JPEG_1M_TRANSFER_PROFILE: {
                        "mime_type": "image/jpeg",
                        "max_bytes": config.MOBILE_JPEG_1M_MAX_BYTES,
                        "direct_upload": True,
                    }
                },
            },
            "desktop_binding_required": any(
                not item.get("desktop_machine_id") for item in project_items
            ),
        }

    def binding_for_account(conn, account, binding: dict):
        """校验并保存账号与微信的一对一绑定；调用方负责事务和提交。"""
        app_id = _safe_text(binding.get("app_id"), 128)
        openid = _safe_text(binding.get("openid"), 256)
        unionid = _safe_text(binding.get("unionid"), 256)
        if not app_id or not openid:
            raise ApiProblem("binding_intent_invalid", "绑定凭证无效", 401)

        occupied = conn.execute(
            "SELECT account_id FROM wechat_bindings WHERE app_id = ? AND openid = ?",
            (app_id, openid),
        ).fetchone()
        if occupied and int(occupied["account_id"]) != int(account["id"]):
            raise ApiProblem("wechat_already_bound", "该微信已绑定其它账号", 409)
        account_binding = conn.execute(
            "SELECT id, app_id, openid FROM wechat_bindings "
            "WHERE account_id = ? ORDER BY id LIMIT 1",
            (account["id"],),
        ).fetchone()
        if account_binding and (
            account_binding["app_id"] != app_id
            or account_binding["openid"] != openid
        ):
            raise ApiProblem(
                "account_already_bound",
                "该桌面端账号已绑定其它微信；如需更换，请先在电脑端“账号与会员”中解绑",
                409,
            )

        idempotent = bool(account_binding)
        timestamp = now()
        conn.execute(
            "INSERT INTO wechat_bindings (account_id, app_id, openid, unionid, created_at, last_login_at) "
            "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(app_id, openid) DO UPDATE SET "
            "last_login_at = excluded.last_login_at, unionid = excluded.unionid",
            (account["id"], app_id, openid, unionid, timestamp, timestamp),
        )
        stored_binding = conn.execute(
            "SELECT id FROM wechat_bindings WHERE account_id = ?",
            (account["id"],),
        ).fetchone()
        if not stored_binding:
            raise ApiProblem("binding_failed", "微信绑定未保存，请重试", 500, True)
        return stored_binding, idempotent

    def mobile_login_payload(conn, account, binding_id: int, **extra) -> dict:
        return {
            "ok": True,
            **extra,
            "token": token_for(
                account["id"],
                scope="mobile",
                binding_id=binding_id,
                mobile_auth_version=account.get("mobile_auth_version", 0),
            ),
            "account": _account_payload(account),
            "bootstrap": bootstrap_payload(conn, account),
        }

    @blueprint.post("/api/mobile/v1/auth/account-login")
    def account_login():
        """先验证桌面账号；只签发十分钟绑定意图，不创建绑定或手机令牌。"""
        if rate_limited_fn and rate_limited_fn():
            raise ApiProblem("rate_limited", "操作过于频繁，请稍后再试", 429, True)
        data = json_body()
        username = _safe_text(data.get("username"), 64)
        password = str(data.get("password") or "")
        app_id = _safe_text(data.get("app_id"), 128)
        exchange = _exchange_wechat_code(data.get("code"), app_id)

        conn = db.connect()
        try:
            row = conn.execute(
                "SELECT * FROM accounts WHERE username = ?", (username,)
            ).fetchone()
            if not row or not check_password_hash(row["password_hash"], password):
                raise ApiProblem("account_credentials_invalid", "账号或密码错误", 401)
            account = dict(row)
            if account["status"] != "active":
                raise ApiProblem("account_disabled", "账号已被停用", 403)

            # 先做一次冲突预检以便立即反馈；确认接口会在写事务内再次校验，
            # 防止两次请求之间发生换绑竞态。
            occupied = conn.execute(
                "SELECT account_id FROM wechat_bindings WHERE app_id = ? AND openid = ?",
                (app_id, exchange["openid"]),
            ).fetchone()
            if occupied and int(occupied["account_id"]) != int(account["id"]):
                raise ApiProblem("wechat_already_bound", "该微信已绑定其它账号", 409)
            account_binding = conn.execute(
                "SELECT app_id, openid FROM wechat_bindings "
                "WHERE account_id = ? ORDER BY id LIMIT 1",
                (account["id"],),
            ).fetchone()
            if account_binding and (
                account_binding["app_id"] != app_id
                or account_binding["openid"] != exchange["openid"]
            ):
                raise ApiProblem(
                    "account_already_bound",
                    "该桌面端账号已绑定其它微信；如需更换，请先在电脑端“账号与会员”中解绑",
                    409,
                )

            intent = ticket_serializer.dumps(
                {
                    "purpose": "account-first-wechat-bind",
                    "account_id": int(account["id"]),
                    "mobile_auth_version": int(account.get("mobile_auth_version") or 0),
                    "app_id": app_id,
                    "openid": exchange["openid"],
                    "unionid": exchange["unionid"],
                    "nonce": uuid.uuid4().hex,
                },
                salt=ACCOUNT_BIND_INTENT_SALT,
            )
            return jsonify(
                {
                    "ok": True,
                    "binding_required": True,
                    "binding_intent": intent,
                    "binding_intent_expires_in": ACCOUNT_BIND_INTENT_MAX_AGE,
                    "account": _account_payload(account),
                }
            )
        finally:
            conn.close()

    @blueprint.post("/api/mobile/v1/auth/wechat-bind-confirm")
    def wechat_bind_confirm():
        """明确确认短期绑定意图；绑定落库后才签发 mobile 令牌。"""
        if rate_limited_fn and rate_limited_fn():
            raise ApiProblem("rate_limited", "操作过于频繁，请稍后再试", 429, True)
        data = json_body()
        intent = str(data.get("binding_intent") or "")
        try:
            binding = ticket_serializer.loads(
                intent,
                salt=ACCOUNT_BIND_INTENT_SALT,
                max_age=ACCOUNT_BIND_INTENT_MAX_AGE,
            )
        except SignatureExpired as exc:
            raise ApiProblem(
                "binding_intent_expired", "绑定确认已过期，请重新登录", 401
            ) from exc
        except BadSignature as exc:
            raise ApiProblem("binding_intent_invalid", "绑定确认无效", 401) from exc
        if not isinstance(binding, dict) or binding.get("purpose") != "account-first-wechat-bind":
            raise ApiProblem("binding_intent_invalid", "绑定确认无效", 401)
        try:
            account_id = int(binding.get("account_id") or 0)
            intent_auth_version = int(binding.get("mobile_auth_version") or 0)
        except (TypeError, ValueError) as exc:
            raise ApiProblem("binding_intent_invalid", "绑定确认无效", 401) from exc
        if account_id <= 0:
            raise ApiProblem("binding_intent_invalid", "绑定确认无效", 401)

        conn = db.connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM accounts WHERE id = ?", (account_id,)
            ).fetchone()
            if not row:
                raise ApiProblem("binding_intent_invalid", "绑定确认无效", 401)
            account = dict(row)
            if account["status"] != "active":
                raise ApiProblem("account_disabled", "账号已被停用", 403)
            if intent_auth_version != int(account.get("mobile_auth_version") or 0):
                raise ApiProblem(
                    "binding_intent_stale", "账号绑定状态已变化，请重新登录", 401
                )
            stored_binding, idempotent = binding_for_account(conn, account, binding)
            conn.commit()
            return jsonify(
                mobile_login_payload(
                    conn,
                    account,
                    stored_binding["id"],
                    idempotent=idempotent,
                )
            )
        finally:
            conn.close()

    @blueprint.post("/api/mobile/v1/auth/wechat-login")
    def wechat_login():
        if rate_limited_fn and rate_limited_fn():
            raise ApiProblem("rate_limited", "操作过于频繁，请稍后再试", 429, True)
        data = json_body()
        app_id = _safe_text(data.get("app_id"), 128)
        exchange = _exchange_wechat_code(data.get("code"), app_id)
        conn = db.connect()
        try:
            row = conn.execute(
                "SELECT a.*, w.id AS binding_id FROM wechat_bindings w "
                "JOIN accounts a ON a.id = w.account_id "
                "WHERE w.app_id = ? AND w.openid = ?",
                (app_id, exchange["openid"]),
            ).fetchone()
            if row:
                account = dict(row)
                if account["status"] != "active":
                    raise ApiProblem("account_disabled", "账号已被停用", 403)
                conn.execute(
                    "UPDATE wechat_bindings SET last_login_at = ? WHERE app_id = ? AND openid = ?",
                    (now(), app_id, exchange["openid"]),
                )
                conn.commit()
                return jsonify(
                    mobile_login_payload(conn, account, account["binding_id"])
                )
        finally:
            conn.close()
        ticket = ticket_serializer.dumps(
            {"app_id": app_id, "openid": exchange["openid"], "unionid": exchange["unionid"]},
            salt="wechat-bind",
        )
        return jsonify({"ok": True, "binding_required": True, "binding_ticket": ticket})

    @blueprint.post("/api/mobile/v1/auth/wechat-bind")
    def wechat_bind():
        if rate_limited_fn and rate_limited_fn():
            raise ApiProblem("rate_limited", "操作过于频繁，请稍后再试", 429, True)
        data = json_body()
        ticket = str(data.get("binding_ticket") or "")
        try:
            binding = ticket_serializer.loads(
                ticket,
                salt="wechat-bind",
                max_age=config.WECHAT_BIND_TICKET_MAX_AGE,
            )
        except SignatureExpired as exc:
            raise ApiProblem("binding_ticket_expired", "绑定凭证已过期，请重新登录", 401) from exc
        except BadSignature as exc:
            raise ApiProblem("binding_ticket_invalid", "绑定凭证无效", 401) from exc
        username = _safe_text(data.get("username"), 64)
        password = str(data.get("password") or "")
        conn = db.connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM accounts WHERE username = ?", (username,)
            ).fetchone()
            if not row or not check_password_hash(row["password_hash"], password):
                raise ApiProblem("account_credentials_invalid", "账号或密码错误", 401)
            account = dict(row)
            if account["status"] != "active":
                raise ApiProblem("account_disabled", "账号已被停用", 403)
            stored_binding, _idempotent = binding_for_account(conn, account, binding)
            conn.commit()
            return jsonify(mobile_login_payload(conn, account, stored_binding["id"]))
        finally:
            conn.close()

    @blueprint.get("/api/mobile/v1/bootstrap")
    def bootstrap():
        current = user()
        conn = db.connect()
        try:
            return jsonify({"ok": True, **bootstrap_payload(conn, current)})
        finally:
            conn.close()

    @blueprint.get("/api/mobile/v1/projects")
    def projects():
        current = user()
        conn = db.connect()
        try:
            rows = conn.execute(
                "SELECT p.*, pm.role AS access_role, pm.joined_at, "
                "(SELECT COUNT(*) FROM project_members total_members "
                " WHERE total_members.project_owner_account_id = p.account_id "
                " AND total_members.project_id = p.project_id "
                " AND total_members.status = 'active') AS member_count "
                "FROM cloud_engineering_projects p JOIN project_members pm "
                "ON pm.project_owner_account_id = p.account_id "
                "AND pm.project_id = p.project_id "
                "WHERE pm.member_account_id = ? AND pm.status = 'active' "
                "AND p.active = 1 ORDER BY p.project_name, p.project_id",
                (current["id"],),
            ).fetchall()
            return jsonify({"ok": True, "projects": [_project_payload(row) for row in rows]})
        finally:
            conn.close()

    @blueprint.get("/api/mobile/v1/projects/<project_id>/members")
    def mobile_project_members(project_id):
        current = user()
        conn = db.connect()
        try:
            project = project_for(conn, current["id"], project_id, PROJECT_ROLES)
            rows = project_members_rows(
                conn, int(project["account_id"]), project["project_id"]
            )
            return jsonify(
                {
                    "ok": True,
                    "project": _project_payload(project),
                    "members": [
                        member_payload(row, current["id"]) for row in rows
                    ],
                }
            )
        finally:
            conn.close()

    @blueprint.get("/api/mobile/v1/projects/<project_id>/invites")
    def mobile_project_invites(project_id):
        current = user()
        conn = db.connect()
        try:
            project = project_for(
                conn, current["id"], project_id, MANAGE_MEMBER_ROLES
            )
            expire_project_invitations(conn)
            conn.commit()
            rows = conn.execute(
                "SELECT * FROM project_invitations WHERE project_owner_account_id = ? "
                "AND project_id = ? AND status = 'pending' ORDER BY id DESC",
                (project["account_id"], project["project_id"]),
            ).fetchall()
            return jsonify(
                {
                    "ok": True,
                    "project": _project_payload(project),
                    "invites": [
                        project_invitation_payload(conn, row) for row in rows
                    ],
                }
            )
        finally:
            conn.close()

    @blueprint.post("/api/mobile/v1/projects/<project_id>/invites")
    def mobile_create_project_invite(project_id):
        current = user()
        if rate_limited_fn and rate_limited_fn():
            raise ApiProblem("rate_limited", "操作过于频繁，请稍后再试", 429, True)
        data = json_body()
        conn = db.connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            project = project_for(
                conn, current["id"], project_id, MANAGE_MEMBER_ROLES
            )
            expire_project_invitations(conn)
            invite = create_project_invitation(
                conn, current, project, data.get("role") or "capturer"
            )
            conn.commit()
            return jsonify({"ok": True, "invite": invite}), 201
        finally:
            conn.close()

    @blueprint.post("/api/mobile/v1/project-invites/preview")
    def mobile_preview_project_invite():
        current = user()
        if rate_limited_fn and rate_limited_fn():
            raise ApiProblem("rate_limited", "操作过于频繁，请稍后再试", 429, True)
        data = json_body()
        code = normalize_invite_code(data.get("code"))
        code_hash = invite_code_hash(code)
        conn = db.connect()
        try:
            row = conn.execute(
                "SELECT * FROM project_invitations WHERE invite_code_hash = ? "
                "AND status = 'pending' AND expires_at > ?",
                (code_hash, now()),
            ).fetchone()
            if not row:
                raise ApiProblem(
                    "project_invite_invalid", "邀请码无效或已过期", 404
                )
            existing = conn.execute(
                "SELECT 1 FROM project_members WHERE project_owner_account_id = ? "
                "AND project_id = ? AND member_account_id = ? AND status = 'active'",
                (
                    row["project_owner_account_id"],
                    row["project_id"],
                    current["id"],
                ),
            ).fetchone()
            invite = project_invitation_payload(conn, row)
            invite["already_joined"] = bool(existing)
            return jsonify(
                {
                    "ok": True,
                    "invite": invite,
                    "already_member": bool(existing),
                }
            )
        finally:
            conn.close()

    @blueprint.post("/api/mobile/v1/project-invites/join")
    def mobile_join_project_invite():
        current = user()
        if rate_limited_fn and rate_limited_fn():
            raise ApiProblem("rate_limited", "操作过于频繁，请稍后再试", 429, True)
        data = json_body()
        code_hash = invite_code_hash(data.get("code"))
        conn = db.connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            invitation = conn.execute(
                "SELECT * FROM project_invitations WHERE invite_code_hash = ?",
                (code_hash,),
            ).fetchone()
            if not invitation:
                raise ApiProblem(
                    "project_invite_invalid", "邀请码无效、已使用或已过期", 404
                )
            existing = conn.execute(
                "SELECT * FROM project_members WHERE project_owner_account_id = ? "
                "AND project_id = ? AND member_account_id = ?",
                (
                    invitation["project_owner_account_id"],
                    invitation["project_id"],
                    current["id"],
                ),
            ).fetchone()
            timestamp = now()
            already_member = bool(existing and existing["status"] == "active")
            idempotent = bool(
                invitation["status"] == "accepted"
                and int(invitation["accepted_by_account_id"] or 0)
                == int(current["id"])
                and already_member
            )
            if not idempotent and (
                invitation["status"] != "pending"
                or invitation["expires_at"] <= timestamp
            ):
                raise ApiProblem(
                    "project_invite_invalid", "邀请码无效、已使用或已过期", 404
                )
            if not idempotent:
                if not already_member:
                    conn.execute(
                        "INSERT INTO project_members "
                        "(project_owner_account_id, project_id, member_account_id, role, status, "
                        "invited_by_account_id, joined_at, updated_at, removed_at, "
                        "removed_by_account_id) VALUES (?, ?, ?, ?, 'active', ?, ?, ?, '', 0) "
                        "ON CONFLICT(project_owner_account_id, project_id, member_account_id) "
                        "DO UPDATE SET role = excluded.role, status = 'active', "
                        "invited_by_account_id = excluded.invited_by_account_id, "
                        "joined_at = excluded.joined_at, updated_at = excluded.updated_at, "
                        "removed_at = '', removed_by_account_id = 0",
                        (
                            invitation["project_owner_account_id"],
                            invitation["project_id"],
                            current["id"],
                            invitation["role"],
                            invitation["created_by_account_id"],
                            timestamp,
                            timestamp,
                        ),
                    )
                changed = conn.execute(
                    "UPDATE project_invitations SET status = 'accepted', "
                    "accepted_by_account_id = ?, accepted_at = ?, updated_at = ? "
                    "WHERE id = ? AND status = 'pending'",
                    (current["id"], timestamp, timestamp, invitation["id"]),
                )
                if changed.rowcount != 1:
                    raise ApiProblem(
                        "project_invite_invalid", "邀请码已被使用", 409
                    )
            conn.commit()
            project = project_for(
                conn,
                current["id"],
                _project_ref(
                    invitation["project_owner_account_id"],
                    invitation["project_id"],
                ),
                PROJECT_ROLES,
            )
            project_payload = _project_payload(project)
            return jsonify(
                {
                    "ok": True,
                    "project": project_payload,
                    "membership": project_payload["membership"],
                    "bootstrap": bootstrap_payload(conn, current),
                    "idempotent": idempotent,
                    "already_member": already_member,
                }
            )
        finally:
            conn.close()

    @blueprint.patch(
        "/api/mobile/v1/projects/<project_id>/members/<int:member_account_id>"
    )
    def mobile_update_project_member(project_id, member_account_id):
        current = user()
        data = json_body()
        requested_role = _safe_text(data.get("role"), 20)
        if requested_role not in {"admin", "capturer", "viewer"}:
            raise ApiProblem("invalid_project_role", "成员角色无效")
        conn = db.connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            project = project_for(
                conn, current["id"], project_id, MANAGE_MEMBER_ROLES
            )
            actor_role = project["access_role"]
            target = conn.execute(
                "SELECT * FROM project_members WHERE project_owner_account_id = ? "
                "AND project_id = ? AND member_account_id = ? AND status = 'active'",
                (project["account_id"], project["project_id"], member_account_id),
            ).fetchone()
            if not target:
                raise ApiProblem("project_member_not_found", "工程成员不存在", 404)
            if target["role"] == "owner":
                raise ApiProblem(
                    "project_owner_protected", "负责人不能在当前版本中变更角色", 409
                )
            if actor_role == "admin" and (
                target["role"] == "admin" or requested_role == "admin"
            ):
                raise ApiProblem(
                    "project_permission_denied", "管理员不能调整其他管理员", 403
                )
            timestamp = now()
            conn.execute(
                "UPDATE project_members SET role = ?, updated_at = ? WHERE id = ?",
                (requested_role, timestamp, target["id"]),
            )
            conn.commit()
            row = conn.execute(
                "SELECT pm.*, a.username, a.display_name FROM project_members pm "
                "JOIN accounts a ON a.id = pm.member_account_id WHERE pm.id = ?",
                (target["id"],),
            ).fetchone()
            return jsonify(
                {"ok": True, "member": member_payload(row, current["id"])}
            )
        finally:
            conn.close()

    @blueprint.delete(
        "/api/mobile/v1/projects/<project_id>/members/<int:member_account_id>"
    )
    def mobile_remove_project_member(project_id, member_account_id):
        current = user()
        conn = db.connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            project = project_for(
                conn, current["id"], project_id, MANAGE_MEMBER_ROLES
            )
            target = conn.execute(
                "SELECT * FROM project_members WHERE project_owner_account_id = ? "
                "AND project_id = ? AND member_account_id = ? AND status = 'active'",
                (project["account_id"], project["project_id"], member_account_id),
            ).fetchone()
            if not target:
                conn.rollback()
                return jsonify({"ok": True, "idempotent": True})
            if target["role"] == "owner":
                raise ApiProblem(
                    "project_owner_protected", "负责人不能退出或被移除", 409
                )
            if project["access_role"] == "admin" and target["role"] == "admin":
                raise ApiProblem(
                    "project_permission_denied", "管理员不能移除其他管理员", 403
                )
            timestamp = now()
            conn.execute(
                "UPDATE project_members SET status = 'removed', removed_at = ?, "
                "removed_by_account_id = ?, updated_at = ? WHERE id = ?",
                (timestamp, current["id"], timestamp, target["id"]),
            )
            conn.commit()
            return jsonify({"ok": True, "idempotent": False})
        finally:
            conn.close()

    @blueprint.get("/api/mobile/v1/projects/<project_id>/requirements")
    def project_requirements(project_id):
        current = user()
        required_type = _safe_text(request.args.get("required_type"), 32)
        conn = db.connect()
        try:
            project = project_for(conn, current["id"], project_id, PROJECT_ROLES)
            owner_account_id = int(project["account_id"])
            local_project_id = project["project_id"]
            sql = (
                "SELECT * FROM cloud_project_requirements WHERE account_id = ? "
                "AND project_id = ? AND active = 1"
            )
            params = [owner_account_id, local_project_id]
            if required_type in {"required", "conditional", "recommended"}:
                sql += " AND required_type = ?"
                params.append(required_type)
            sql += " ORDER BY phase, division, subdivision, item, process, id"
            rows = conn.execute(sql, params).fetchall()
            counts = {"required": 0, "conditional": 0, "recommended": 0}
            for row in rows:
                key = str(row["required_type"] or "recommended")
                counts[key] = counts.get(key, 0) + 1
            return jsonify(
                {
                    "ok": True,
                    "project": _project_payload(project),
                    "summary": {"total": len(rows), **counts},
                    "requirements": [_requirement_payload(row) for row in rows],
                }
            )
        finally:
            conn.close()

    def project_tree_response(project_id, scope):
        current = user()
        conn = db.connect()
        try:
            project = project_for(conn, current["id"], project_id, PROJECT_ROLES)
            owner_account_id = int(project["account_id"])
            local_project_id = project["project_id"]
            rows = conn.execute(
                "SELECT * FROM cloud_units WHERE account_id = ? AND project_id = ? "
                "AND scope = ? AND active = 1 ORDER BY sort_order, id",
                (owner_account_id, local_project_id, scope),
            ).fetchall()
            leaves = [
                {
                    "unit_code": row["node_code"],
                    "name": row["name"],
                    "parent_code": row["parent_code"],
                    "metadata": _json(row["metadata_json"], {}),
                }
                for row in rows
                if row["node_type"] == "unit"
            ]
            return jsonify(
                {
                    "ok": True,
                    "project": _project_payload(project),
                    "tree": _tree_from_rows(rows),
                    "units": leaves,
                }
            )
        finally:
            conn.close()

    @blueprint.get("/api/mobile/v1/projects/<project_id>/tree")
    def project_tree(project_id):
        return project_tree_response(project_id, "engineering")

    @blueprint.get("/api/mobile/v1/projects/<project_id>/other-tree")
    def project_other_tree(project_id):
        return project_tree_response(project_id, "other")

    @blueprint.get("/api/mobile/v1/photos")
    def photos():
        current = user()
        cursor, limit = _page_args()
        project_reference = str(request.args.get("project_id") or "").strip()
        scope = _safe_text(request.args.get("scope"), 20)
        category = _safe_text(request.args.get("category"), 20)
        unit_code = _safe_text(request.args.get("unit_code"), 160)
        other_node_code = _safe_text(request.args.get("other_node_code"), 160)
        if scope and scope not in SCOPES:
            raise ApiProblem("invalid_scope", "影像范围无效")
        if category and category not in CATEGORIES:
            raise ApiProblem("invalid_category", "照片类别无效")
        if scope == "other" and category:
            raise ApiProblem("invalid_category", "其它影像不使用施工或监理分类")
        if unit_code and other_node_code:
            raise ApiProblem("invalid_destination_filter", "工程部位和其它影像目录不能同时筛选")
        if unit_code and scope == "other":
            raise ApiProblem("invalid_destination_filter", "其它影像不能按工程部位筛选")
        if other_node_code and scope == "engineering":
            raise ApiProblem("invalid_destination_filter", "工程影像不能按其它影像目录筛选")
        # 手机影像库是“最近查看”时间线：首屏从最新 ID 向旧记录翻页。
        # cursor=0/缺省均代表首屏；后续 cursor 是上一页末尾（最小）的 ID。
        # 桌面 inbox 仍使用独立的 id > cursor 正向增量语义。
        conn = db.connect()
        try:
            project = project_for(
                conn, current["id"], project_reference, PROJECT_ROLES
            )
            owner_account_id = int(project["account_id"])
            local_project_id = project["project_id"]
        finally:
            conn.close()
        clauses = [
            "project_owner_account_id = ?",
            "project_id = ?",
            "deleted_at = ''",
        ]
        params = [owner_account_id, local_project_id]
        if scope:
            clauses.append("scope = ?")
            params.append(scope)
        if category:
            clauses.append("category = ?")
            params.append(category)
        if unit_code:
            clauses.append("json_extract(assignment_json, '$.unit_code') = ?")
            params.append(unit_code)
        if other_node_code:
            clauses.append("json_extract(assignment_json, '$.other_node_code') = ?")
            params.append(other_node_code)
        conn = db.connect()
        try:
            project_for(conn, current["id"], project_reference, PROJECT_ROLES)
            total = int(
                conn.execute(
                    "SELECT COUNT(*) AS total FROM cloud_photos WHERE "
                    + " AND ".join(clauses),
                    tuple(params),
                ).fetchone()["total"]
            )
            page_clauses = list(clauses)
            page_params = list(params)
            if cursor:
                page_clauses.append("id < ?")
                page_params.append(cursor)
            rows = conn.execute(
                "SELECT * FROM cloud_photos WHERE " + " AND ".join(page_clauses) +
                " ORDER BY id DESC LIMIT ?",
                (*page_params, limit + 1),
            ).fetchall()
            page = rows[:limit]
            return jsonify(
                {
                    "ok": True,
                    "photos": [
                        _photo_payload(
                            row,
                            preview_download_url(row, current["id"]),
                            conn=conn,
                        )
                        for row in page
                    ],
                    "next_cursor": str(page[-1]["id"]) if len(rows) > limit and page else "",
                    "total": total,
                }
            )
        finally:
            conn.close()

    @blueprint.get("/api/mobile/v1/photos/<photo_uuid>")
    def photo_detail(photo_uuid):
        current = user()
        photo_uuid = _uuid(photo_uuid, "photo_uuid")
        conn = db.connect()
        try:
            requested_project = str(request.args.get("project_id") or "").strip()
            params = [photo_uuid, current["id"]]
            project_clause = ""
            if requested_project:
                project = project_for(
                    conn, current["id"], requested_project, PROJECT_ROLES
                )
                project_clause = (
                    "AND photos.project_owner_account_id = ? "
                    "AND photos.project_id = ? "
                )
                params.extend((int(project["account_id"]), project["project_id"]))
            rows = conn.execute(
                "SELECT photos.* FROM cloud_photos photos JOIN project_members pm "
                "ON pm.project_owner_account_id = photos.project_owner_account_id "
                "AND pm.project_id = photos.project_id "
                "WHERE photos.photo_uuid = ? AND pm.member_account_id = ? "
                "AND pm.status = 'active' AND photos.deleted_at = '' "
                + project_clause
                + "ORDER BY photos.id LIMIT 2",
                params,
            ).fetchall()
            if not rows:
                raise ApiProblem("photo_not_found", "照片不存在", 404)
            if len(rows) > 1:
                raise ApiProblem(
                    "project_reference_required",
                    "照片标识在多个共享工程中重复，请指定工程",
                    409,
                )
            row = rows[0]
            return jsonify(
                {
                    "ok": True,
                    "photo": _photo_payload(
                        row,
                        preview_download_url(row, current["id"]),
                        conn=conn,
                    ),
                }
            )
        finally:
            conn.close()

    @blueprint.get("/api/mobile/v1/files/<photo_uuid>")
    def local_photo_file(photo_uuid):
        photo_uuid = _uuid(photo_uuid, "photo_uuid")
        try:
            signed = ticket_serializer.loads(
                request.args.get("token", ""),
                salt="mobile-photo-download",
                max_age=config.MOBILE_DOWNLOAD_URL_TTL,
            )
        except SignatureExpired as exc:
            raise ApiProblem("download_url_expired", "下载地址已过期", 401) from exc
        except BadSignature as exc:
            raise ApiProblem("download_url_invalid", "下载地址无效", 401) from exc
        if signed.get("photo_uuid") != photo_uuid:
            raise ApiProblem("download_url_invalid", "下载地址无效", 401)
        conn = db.connect()
        try:
            row = conn.execute(
                "SELECT photos.preview_storage_key, photos.storage_key "
                "FROM cloud_photos photos JOIN project_members pm "
                "ON pm.project_owner_account_id = photos.project_owner_account_id "
                "AND pm.project_id = photos.project_id "
                "WHERE photos.account_id = ? AND photos.project_owner_account_id = ? "
                "AND photos.project_id = ? AND photos.photo_uuid = ? "
                "AND photos.deleted_at = '' AND pm.member_account_id = ? "
                "AND pm.status = 'active'",
                (
                    int(signed.get("uploader_account_id") or 0),
                    int(signed.get("project_owner_account_id") or 0),
                    str(signed.get("project_id") or ""),
                    photo_uuid,
                    int(signed.get("viewer_account_id") or 0),
                ),
            ).fetchone()
        finally:
            conn.close()
        if not row:
            raise ApiProblem("photo_not_found", "照片不存在", 404)
        key = row["preview_storage_key"] or row["storage_key"]
        try:
            if isinstance(storage, LocalObjectStorage):
                path = storage.path_for(key)
                if not path.is_file():
                    raise ApiProblem("object_missing", "图片文件暂时不可用", 404, True)
                return send_file(path, mimetype="image/jpeg", conditional=True, max_age=60)
            raw = storage.get_bytes(key, config.MOBILE_PREVIEW_MAX_BYTES)
        except ApiProblem:
            raise
        except StorageError as exc:
            raise ApiProblem(
                "object_unavailable", "图片文件暂时不可用，请稍后重试", 503, True
            ) from exc
        return send_file(
            io.BytesIO(raw),
            mimetype="image/jpeg",
            conditional=True,
            max_age=60,
            download_name=f"{photo_uuid}.jpg",
        )

    @blueprint.get("/api/desktop/v1/files/<photo_uuid>/original")
    def local_original_file(photo_uuid):
        current = user()
        if not isinstance(storage, LocalObjectStorage):
            raise ApiProblem("local_storage_disabled", "本地图片代理未启用", 404)
        photo_uuid = _uuid(photo_uuid, "photo_uuid")
        try:
            signed = ticket_serializer.loads(
                request.args.get("token", ""),
                salt="desktop-original-download",
                max_age=config.MOBILE_DOWNLOAD_URL_TTL,
            )
        except SignatureExpired as exc:
            raise ApiProblem("download_url_expired", "原图下载地址已过期", 401) from exc
        except BadSignature as exc:
            raise ApiProblem("download_url_invalid", "原图下载地址无效", 401) from exc
        if signed.get("photo_uuid") != photo_uuid:
            raise ApiProblem("download_url_invalid", "原图下载地址无效", 401)
        signed_machine_id = require_desktop_client(
            current, signed.get("target_machine_id")
        )
        owner_account_id = int(signed.get("project_owner_account_id") or 0)
        uploader_account_id = int(signed.get("uploader_account_id") or 0)
        if owner_account_id != int(current["id"]):
            raise ApiProblem("download_url_invalid", "原图下载地址无效", 401)
        conn = db.connect()
        try:
            _require_active_machine(conn, current["id"], signed_machine_id)
            row = conn.execute(
                "SELECT original_storage_key, original_mime_type, storage_key, "
                "target_machine_id, "
                "original_cleanup_status FROM cloud_photos "
                "WHERE account_id = ? AND project_owner_account_id = ? "
                "AND project_id = ? AND photo_uuid = ? AND deleted_at = ''",
                (
                    uploader_account_id,
                    owner_account_id,
                    str(signed.get("project_id") or ""),
                    photo_uuid,
                ),
            ).fetchone()
        finally:
            conn.close()
        if not row:
            raise ApiProblem("photo_not_found", "照片不存在", 404)
        if _machine_id(row["target_machine_id"]) != signed_machine_id:
            raise ApiProblem("wrong_desktop_machine", "该原图属于另一台工程电脑", 403)
        key = row["original_storage_key"]
        if not key and row["original_cleanup_status"] == "legacy_shared":
            key = row["storage_key"]
        if not key or row["original_cleanup_status"] == "deleted":
            raise ApiProblem("original_not_available", "原图已归档并完成中转清理", 404)
        path = storage.path_for(key)
        if not path.is_file():
            raise ApiProblem("object_missing", "原图中转文件暂时不可用", 404, True)
        return send_file(
            path,
            mimetype=row["original_mime_type"] or "application/octet-stream",
            conditional=True,
            max_age=0,
        )

    @blueprint.post("/api/mobile/v1/batches")
    def create_batch():
        current = user()
        data = json_body()
        client_batch_id = _uuid(data.get("client_batch_id"), "client_batch_id")
        project_reference = str(data.get("project_id") or "").strip()
        scope = _safe_text(data.get("scope"), 20)
        category = _safe_text(data.get("category"), 20)
        mode = _safe_text(data.get("mode"), 20)
        transfer_profile = _transfer_profile(
            data.get("transfer_profile"), data.get("compression_profile")
        )
        if scope not in SCOPES:
            raise ApiProblem("invalid_scope", "影像范围无效")
        if mode not in MODES:
            raise ApiProblem("invalid_mode", "上传方式无效")
        if scope == "engineering" and category not in CATEGORIES:
            raise ApiProblem("invalid_category", "工程影像必须选择施工或监理")
        if scope == "other":
            category = ""
        conn = db.connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            project = project_for(
                conn, current["id"], project_reference, CAPTURE_ROLES
            )
            project_owner_account_id = int(project["account_id"])
            project_id = project["project_id"]
            target_machine_id = _machine_id(project["desktop_machine_id"])
            if not target_machine_id:
                raise ApiProblem(
                    "project_desktop_not_bound",
                    "请先在原电脑同步工程，再从手机创建上传批次",
                    409,
                )
            assignment = data.get("assignment") if isinstance(data.get("assignment"), dict) else {}
            require_complete_assignment = (
                mode == "direct" or transfer_profile == JPEG_1M_TRANSFER_PROFILE
            )
            if require_complete_assignment:
                assignment = _validate_assignment(
                    conn,
                    project_owner_account_id,
                    project_id,
                    scope,
                    assignment,
                    require_process=(
                        transfer_profile == JPEG_1M_TRANSFER_PROFILE
                    ),
                )
            elif assignment:
                assignment = _validate_assignment(
                    conn, project_owner_account_id, project_id, scope, assignment
                )
            requirement = capture_requirement_for(
                conn, project_owner_account_id, project_id, data.get("requirement")
            )
            if requirement and scope != "engineering":
                raise ApiProblem(
                    "invalid_requirement_scope",
                    "专业采集规则只能用于工程影像",
                )
            existing = conn.execute(
                "SELECT * FROM mobile_batches WHERE account_id = ? AND client_batch_id = ?",
                (current["id"], client_batch_id),
            ).fetchone()
            if existing:
                same_request = (
                    int(
                        existing["project_owner_account_id"]
                        or existing["account_id"]
                    )
                    == project_owner_account_id
                    and existing["project_id"] == project_id
                    and existing["scope"] == scope
                    and existing["category"] == category
                    and existing["mode"] == mode
                    and existing["transfer_profile"] == transfer_profile
                    and _json(existing["assignment_json"], {}) == assignment
                    and existing["requirement_code"]
                    == requirement.get("template_code", "")
                    and existing["requirement_name"]
                    == requirement.get("photo_requirement_name", "")
                    and _machine_id(existing["target_machine_id"])
                    == target_machine_id
                )
                if not same_request:
                    raise ApiProblem(
                        "batch_id_conflict",
                        "该客户端批次 ID 已用于其它工程或上传配置",
                        409,
                    )
                conn.rollback()
                return jsonify(
                    {"ok": True, "idempotent": True, "batch": batch_payload(conn, existing)}
                )
            try:
                _require_active_machine(
                    conn, project_owner_account_id, target_machine_id
                )
            except ApiProblem as exc:
                raise ApiProblem(
                    "project_desktop_not_active",
                    "工程原电脑已解绑，请先在电脑端重新同步工程",
                    409,
                ) from exc
            timestamp = now()
            cur = conn.execute(
                "INSERT INTO mobile_batches (account_id, client_batch_id, "
                "project_owner_account_id, project_id, scope, "
                "category, mode, transfer_profile, assignment_json, "
                "requirement_code, requirement_name, "
                "target_machine_id, status, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'local_ready', ?, ?)",
                (
                    current["id"], client_batch_id, project_owner_account_id,
                    project_id, scope, category, mode, transfer_profile,
                    _dumps(assignment), requirement.get("template_code", ""),
                    requirement.get("photo_requirement_name", ""), target_machine_id,
                    timestamp, timestamp,
                ),
            )
            conn.commit()
            row = conn.execute("SELECT * FROM mobile_batches WHERE id = ?", (cur.lastrowid,)).fetchone()
            return jsonify({"ok": True, "idempotent": False, "batch": batch_payload(conn, row)}), 201
        finally:
            conn.close()

    @blueprint.get("/api/mobile/v1/batches")
    def list_batches():
        current = user()
        cursor, limit = _page_args()
        conn = db.connect()
        try:
            rows = conn.execute(
                "SELECT b.* FROM mobile_batches b JOIN project_members pm "
                "ON pm.project_owner_account_id = b.project_owner_account_id "
                "AND pm.project_id = b.project_id "
                "WHERE b.account_id = ? AND b.id > ? "
                "AND pm.member_account_id = ? AND pm.status = 'active' "
                "ORDER BY b.id LIMIT ?",
                (current["id"], cursor, current["id"], limit + 1),
            ).fetchall()
            page = rows[:limit]
            return jsonify(
                {
                    "ok": True,
                    "batches": [batch_payload(conn, row) for row in page],
                    "next_cursor": str(page[-1]["id"]) if len(rows) > limit and page else "",
                }
            )
        finally:
            conn.close()

    @blueprint.get("/api/mobile/v1/batches/<int:batch_id>")
    def batch_detail(batch_id):
        current = user()
        # 小程序只轮询批次也能触发运行期心跳超时恢复，不依赖额外 job 请求。
        recover_stale_analysis_jobs()
        conn = db.connect()
        try:
            row = batch_for(conn, current["id"], batch_id)
            return jsonify({"ok": True, "batch": batch_payload(conn, row)})
        finally:
            conn.close()

    @blueprint.patch("/api/mobile/v1/batches/<int:batch_id>/archive-info")
    def update_batch_archive_info(batch_id):
        """补齐已创建批次的可信归档层级，并同步尚未投递的已有照片。"""

        current = user()
        data = json_body()
        assignment = data.get("assignment")
        if not isinstance(assignment, dict):
            raise ApiProblem("invalid_assignment", "归档信息格式不正确")
        conn = db.connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            batch = batch_for(
                conn, current["id"], batch_id, require_capture=True
            )
            if batch["status"] in {"desktop_pending", "desktop_imported"}:
                raise ApiProblem(
                    "batch_committed", "批次已提交电脑归档，不能再修改归档信息", 409
                )
            if batch["status"] == "analyzing":
                raise ApiProblem(
                    "batch_analyzing", "批次正在自动识别，请稍后再修改归档信息", 409
                )
            normalized = _validate_assignment(
                conn,
                int(batch["project_owner_account_id"] or batch["account_id"]),
                batch["project_id"],
                batch["scope"],
                assignment,
                require_process=(
                    batch.get("transfer_profile", "")
                    == JPEG_1M_TRANSFER_PROFILE
                ),
            )
            photo_rows = conn.execute(
                "SELECT id, assignment_json FROM cloud_photos "
                "WHERE account_id = ? AND batch_id = ? "
                "AND status NOT IN ('desktop_pending', 'desktop_imported')",
                (current["id"], batch_id),
            ).fetchall()
            batch_changed = _json(batch["assignment_json"], {}) != normalized
            changed_photo_ids = [
                int(photo["id"])
                for photo in photo_rows
                if _json(photo["assignment_json"], {}) != normalized
            ]
            changed = batch_changed or bool(changed_photo_ids)
            if changed:
                timestamp = now()
                encoded = _dumps(normalized)
                if batch_changed:
                    conn.execute(
                        "UPDATE mobile_batches SET assignment_json = ?, updated_at = ? "
                        "WHERE id = ? AND account_id = ?",
                        (encoded, timestamp, batch_id, current["id"]),
                    )
                if changed_photo_ids:
                    conn.executemany(
                        "UPDATE cloud_photos SET assignment_json = ?, updated_at = ? "
                        "WHERE id = ? AND account_id = ? "
                        "AND status NOT IN ('desktop_pending', 'desktop_imported')",
                        (
                            (encoded, timestamp, photo_id, current["id"])
                            for photo_id in changed_photo_ids
                        ),
                    )
                conn.commit()
            else:
                conn.rollback()
            row = batch_for(conn, current["id"], batch_id, require_capture=True)
            return jsonify(
                {
                    "ok": True,
                    "idempotent": not changed,
                    "batch": batch_payload(conn, row),
                }
            )
        finally:
            conn.close()

    @blueprint.post("/api/mobile/v1/batches/<int:batch_id>/photos")
    def upload_batch_photo(batch_id):
        current = user()
        conn = db.connect()
        try:
            batch = batch_for(
                conn, current["id"], batch_id, require_capture=True
            )
            _require_batch_uploadable(batch["status"])
            assignment = _json(batch["assignment_json"], {})
        finally:
            conn.close()
        row, idempotent = insert_photo(
            current_user=current,
            photo_uuid=_uuid(request.form.get("photo_uuid"), "photo_uuid"),
            project_id=batch["project_id"],
            scope=batch["scope"],
            category=batch["category"],
            assignment=assignment,
            title=request.form.get("title", ""),
            photo_date=request.form.get("photo_date", ""),
            client_captured_at=request.form.get("client_captured_at", ""),
            orientation=request.form.get("orientation", 1),
            source="mobile",
            batch_id=batch_id,
            file_storage=request.files.get("file"),
            claimed_sha=request.form.get("sha256", ""),
            claimed_size=(
                request.form.get("original_size_bytes")
                or request.form.get("original_size")
                or ""
            ),
            target_machine_id=batch["target_machine_id"],
            original_filename=request.form.get("original_filename", ""),
            upload_max_bytes=config.MOBILE_DIRECT_UPLOAD_MAX_BYTES,
            project_owner_account_id=batch.get("project_owner_account_id")
            or batch["account_id"],
            capture_source=request.form.get("capture_source", ""),
            transfer_profile=_transfer_profile(
                request.form.get("transfer_profile"),
                request.form.get("compression_profile"),
                batch.get("transfer_profile", ""),
            ),
        )
        return jsonify(
            {
                "ok": True,
                "idempotent": idempotent,
                "photo": hydrated_photo_payload(row, current["id"]),
            }
        ), (200 if idempotent else 201)

    @blueprint.post(
        "/api/mobile/v1/batches/<int:batch_id>/chunked-uploads/init"
    )
    def init_chunk_upload(batch_id):
        current = user()
        data = json_body()
        photo_uuid = _uuid(data.get("photo_uuid"), "photo_uuid")
        original_sha = _sha256(data.get("sha256"), "sha256")
        total_size = _strict_integer(
            data.get("original_size_bytes"),
            "original_size_bytes",
            1,
        )
        requested_transfer_profile = _transfer_profile(
            data.get("transfer_profile"), data.get("compression_profile")
        )
        chunk_size = _strict_integer(
            data.get("chunk_size_bytes"), "chunk_size_bytes", 1
        )
        if chunk_size != config.MOBILE_CHUNK_BYTES:
            raise ApiProblem(
                "chunk_size_invalid",
                f"分片大小必须为 {config.MOBILE_CHUNK_BYTES} 字节",
                422,
            )
        total_chunks = _strict_integer(data.get("total_chunks"), "total_chunks", 1)
        expected_chunks = (total_size + chunk_size - 1) // chunk_size
        if total_chunks != expected_chunks:
            raise ApiProblem(
                "chunk_count_mismatch", "分片总数与原图大小不一致", 422
            )
        original_filename = _safe_filename(data.get("original_filename"), "original")
        metadata = {
            "client_captured_at": _safe_text(data.get("client_captured_at"), 40),
            "orientation": _strict_integer(data.get("orientation", 1), "orientation", 1, 8),
            "width": _strict_integer(
                data.get("width", 0), "width", 0, config.MOBILE_MAX_ORIGINAL_EDGE
            ),
            "height": _strict_integer(
                data.get("height", 0), "height", 0, config.MOBILE_MAX_ORIGINAL_EDGE
            ),
            "title": _safe_text(data.get("title"), 200),
            "photo_date": _photo_date(data.get("photo_date", "")),
            "capture_source": (
                str(data.get("capture_source") or "").strip().lower()
                if str(data.get("capture_source") or "").strip().lower()
                in {"camera", "album"}
                else ""
            ),
            "transfer_profile": requested_transfer_profile,
        }
        expire_chunk_sessions()
        with _chunk_session_lock(current["id"], photo_uuid):
            conn = db.connect()
            reset_session_id = None
            try:
                conn.execute("BEGIN IMMEDIATE")
                batch = batch_for(
                    conn, current["id"], batch_id, require_capture=True
                )
                _require_batch_uploadable(batch["status"])
                transfer_profile = _transfer_profile(
                    requested_transfer_profile,
                    batch.get("transfer_profile", ""),
                )
                transfer_max_bytes = (
                    config.MOBILE_JPEG_1M_MAX_BYTES
                    if transfer_profile == JPEG_1M_TRANSFER_PROFILE
                    else config.MOBILE_MAX_ORIGINAL_BYTES
                )
                if total_size > transfer_max_bytes:
                    raise ApiProblem(
                        "original_too_large",
                        "新版归档 JPEG 不能超过 1MB"
                        if transfer_profile == JPEG_1M_TRANSFER_PROFILE
                        else "原图不能超过 50MB",
                        413,
                    )
                metadata["transfer_profile"] = transfer_profile
                owner_account_id = int(
                    batch.get("project_owner_account_id") or batch["account_id"]
                )
                target_machine_id = _require_active_machine(
                    conn, owner_account_id, batch["target_machine_id"]
                )
                existing = conn.execute(
                    "SELECT * FROM mobile_upload_sessions WHERE account_id = ? "
                    "AND photo_uuid = ?",
                    (current["id"], photo_uuid),
                ).fetchone()
                wanted_metadata = _dumps(metadata)
                existing_photo = conn.execute(
                    "SELECT * FROM cloud_photos WHERE project_owner_account_id = ? "
                    "AND photo_uuid = ?",
                    (owner_account_id, photo_uuid),
                ).fetchone()
                if existing_photo and not existing:
                    if not (
                        existing_photo["source"] == "mobile"
                        and int(existing_photo["account_id"]) == int(current["id"])
                        and int(existing_photo["batch_id"] or 0) == int(batch_id)
                        and int(
                            existing_photo["project_owner_account_id"]
                            or existing_photo["account_id"]
                        )
                        == owner_account_id
                        and existing_photo["project_id"] == batch["project_id"]
                        and _machine_id(existing_photo["target_machine_id"])
                        == target_machine_id
                        and existing_photo["original_sha256"] == original_sha
                        and int(existing_photo["original_size_bytes"] or 0)
                        == total_size
                    ):
                        raise ApiProblem(
                            "photo_uuid_conflict",
                            "该照片 UUID 已用于其它原图、工程或上传批次",
                            409,
                        )
                    timestamp = now()
                    cur = conn.execute(
                        "INSERT INTO mobile_upload_sessions (account_id, batch_id, "
                        "photo_uuid, project_owner_account_id, project_id, "
                        "target_machine_id, original_sha256, "
                        "total_size_bytes, chunk_size_bytes, total_chunks, original_filename, "
                        "metadata_json, status, cleanup_status, created_at, updated_at, "
                        "expires_at, completed_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, "
                        "'completed', 'cleaned', ?, ?, ?, ?)",
                        (
                            current["id"],
                            batch_id,
                            photo_uuid,
                            owner_account_id,
                            batch["project_id"],
                            target_machine_id,
                            original_sha,
                            total_size,
                            chunk_size,
                            total_chunks,
                            original_filename,
                            wanted_metadata,
                            timestamp,
                            timestamp,
                            _future_timestamp(
                                timestamp, config.MOBILE_CHUNK_TTL_SECONDS
                            ),
                            timestamp,
                        ),
                    )
                    conn.commit()
                    row = conn.execute(
                        "SELECT * FROM mobile_upload_sessions WHERE id = ?",
                        (cur.lastrowid,),
                    ).fetchone()
                    return jsonify(
                        {
                            "ok": True,
                            "idempotent": True,
                            "upload": chunk_upload_payload(conn, row),
                            "photo": _photo_payload(
                                existing_photo,
                                preview_download_url(existing_photo, current["id"]),
                                conn=conn,
                            ),
                        }
                    )
                if existing:
                    same_request = (
                        int(existing["batch_id"]) == int(batch_id)
                        and int(
                            existing["project_owner_account_id"]
                            or existing["account_id"]
                        )
                        == owner_account_id
                        and existing["project_id"] == batch["project_id"]
                        and _machine_id(existing["target_machine_id"])
                        == target_machine_id
                        and existing["original_sha256"] == original_sha
                        and int(existing["total_size_bytes"]) == total_size
                        and int(existing["chunk_size_bytes"]) == chunk_size
                        and int(existing["total_chunks"]) == total_chunks
                        and existing["original_filename"] == original_filename
                        and comparable_chunk_metadata(existing["metadata_json"])
                        == comparable_chunk_metadata(metadata)
                    )
                    if not same_request:
                        raise ApiProblem(
                            "photo_uuid_conflict",
                            "该照片 UUID 已用于其它原图、工程或上传批次",
                            409,
                        )
                    matching = matching_session_photo(conn, existing)
                    if matching:
                        timestamp = now()
                        conn.execute(
                            "UPDATE mobile_upload_sessions SET status = 'completed', "
                            "error_code = '', error_message = '', completed_at = CASE "
                            "WHEN completed_at = '' THEN ? ELSE completed_at END, "
                            "cleanup_status = 'pending', cleanup_error = '', updated_at = ? "
                            "WHERE id = ?",
                            (timestamp, timestamp, existing["id"]),
                        )
                        conn.execute(
                            "DELETE FROM mobile_upload_chunks WHERE session_id = ?",
                            (existing["id"],),
                        )
                        conn.commit()
                        cleanup_chunk_session_files(current["id"], existing["id"])
                        row = conn.execute(
                            "SELECT * FROM mobile_upload_sessions WHERE id = ?",
                            (existing["id"],),
                        ).fetchone()
                        return jsonify(
                            {
                                "ok": True,
                                "idempotent": True,
                                "upload": chunk_upload_payload(conn, row),
                                "photo": _photo_payload(
                                    matching,
                                    preview_download_url(matching, current["id"]),
                                    conn=conn,
                                ),
                            }
                        )
                    if existing["status"] in {"active", "finalizing"}:
                        if existing["status"] == "active":
                            timestamp = now()
                            conn.execute(
                                "UPDATE mobile_upload_sessions SET updated_at = ?, "
                                "expires_at = ? WHERE id = ? AND status = 'active'",
                                (
                                    timestamp,
                                    _future_timestamp(
                                        timestamp, config.MOBILE_CHUNK_TTL_SECONDS
                                    ),
                                    existing["id"],
                                ),
                            )
                            conn.commit()
                            existing = conn.execute(
                                "SELECT * FROM mobile_upload_sessions WHERE id = ?",
                                (existing["id"],),
                            ).fetchone()
                        else:
                            conn.rollback()
                        return jsonify(
                            {
                                "ok": True,
                                "idempotent": True,
                                "upload": chunk_upload_payload(conn, existing),
                            }
                        )
                    if existing["status"] == "completed":
                        raise ApiProblem(
                            "chunk_upload_inconsistent",
                            "分片会话已完成但照片记录不存在，请更换照片 UUID",
                            409,
                        )
                    reset_session_id = int(existing["id"])

                if reset_session_id and existing["cleanup_status"] != "cleaned":
                    conn.execute(
                        "UPDATE mobile_upload_sessions SET cleanup_status = 'pending', "
                        "cleanup_error = '', updated_at = ? WHERE id = ? AND account_id = ?",
                        (now(), reset_session_id, current["id"]),
                    )
                    conn.execute(
                        "DELETE FROM mobile_upload_chunks WHERE session_id = ?",
                        (reset_session_id,),
                    )
                    conn.commit()
                    if not cleanup_chunk_session_files(
                        current["id"], reset_session_id
                    ):
                        raise ApiProblem(
                            "chunk_cleanup_pending",
                            "旧分片临时文件正在回收，请稍后重试",
                            503,
                            True,
                        )
                    # 文件清理期间数据库锁已释放；重新确认批次仍允许上传，
                    # 防止并发提交后把终态批次重新打开。
                    conn.execute("BEGIN IMMEDIATE")
                    batch = batch_for(
                        conn, current["id"], batch_id, require_capture=True
                    )
                    _require_batch_uploadable(batch["status"])
                    owner_account_id = int(
                        batch.get("project_owner_account_id") or batch["account_id"]
                    )
                    target_machine_id = _require_active_machine(
                        conn, owner_account_id, batch["target_machine_id"]
                    )
                    existing = conn.execute(
                        "SELECT * FROM mobile_upload_sessions WHERE id = ? "
                        "AND account_id = ? AND photo_uuid = ?",
                        (reset_session_id, current["id"], photo_uuid),
                    ).fetchone()
                    if not existing:
                        raise ApiProblem(
                            "chunk_upload_not_found", "分片上传会话不存在", 404
                        )

                quota_params = [current["id"]]
                exclude = ""
                if reset_session_id:
                    exclude = " AND id != ?"
                    quota_params.append(reset_session_id)
                account_quota = conn.execute(
                    "SELECT COUNT(*) AS active_count, "
                    "COALESCE(SUM(total_size_bytes), 0) AS reserved_bytes "
                    "FROM mobile_upload_sessions WHERE account_id = ? "
                    "AND (status IN ('active', 'finalizing') "
                    "OR cleanup_status = 'pending')" + exclude,
                    quota_params,
                ).fetchone()
                global_params = []
                global_exclude = ""
                if reset_session_id:
                    global_exclude = " AND id != ?"
                    global_params.append(reset_session_id)
                global_quota = conn.execute(
                    "SELECT COUNT(*) AS active_count, "
                    "COALESCE(SUM(total_size_bytes), 0) AS reserved_bytes "
                    "FROM mobile_upload_sessions WHERE "
                    "(status IN ('active', 'finalizing') OR cleanup_status = 'pending')"
                    + global_exclude,
                    global_params,
                ).fetchone()
                if (
                    int(account_quota["active_count"])
                    >= config.MOBILE_CHUNK_MAX_ACTIVE_PER_ACCOUNT
                    or int(account_quota["reserved_bytes"]) + total_size
                    > config.MOBILE_CHUNK_MAX_RESERVED_PER_ACCOUNT
                    or int(global_quota["active_count"])
                    >= config.MOBILE_CHUNK_MAX_ACTIVE_GLOBAL
                    or int(global_quota["reserved_bytes"]) + total_size
                    > config.MOBILE_CHUNK_MAX_RESERVED_GLOBAL
                ):
                    raise ApiProblem(
                        "chunk_quota_exceeded",
                        "分片临时空间已满，请完成或取消现有上传后重试",
                        429,
                        True,
                    )

                timestamp = now()
                expires_at = _future_timestamp(
                    timestamp, config.MOBILE_CHUNK_TTL_SECONDS
                )
                if reset_session_id:
                    conn.execute(
                        "DELETE FROM mobile_upload_chunks WHERE session_id = ?",
                        (reset_session_id,),
                    )
                    conn.execute(
                        "UPDATE mobile_upload_sessions SET batch_id = ?, "
                        "project_owner_account_id = ?, project_id = ?, "
                        "target_machine_id = ?, original_sha256 = ?, total_size_bytes = ?, "
                        "chunk_size_bytes = ?, total_chunks = ?, original_filename = ?, "
                        "metadata_json = ?, status = 'active', error_code = '', "
                        "error_message = '', cleanup_status = '', cleanup_error = '', "
                        "updated_at = ?, expires_at = ?, completed_at = '' "
                        "WHERE id = ? AND account_id = ?",
                        (
                            batch_id,
                            owner_account_id,
                            batch["project_id"],
                            target_machine_id,
                            original_sha,
                            total_size,
                            chunk_size,
                            total_chunks,
                            original_filename,
                            wanted_metadata,
                            timestamp,
                            expires_at,
                            reset_session_id,
                            current["id"],
                        ),
                    )
                    session_id = reset_session_id
                else:
                    cur = conn.execute(
                        "INSERT INTO mobile_upload_sessions (account_id, batch_id, "
                        "photo_uuid, project_owner_account_id, project_id, "
                        "target_machine_id, original_sha256, "
                        "total_size_bytes, chunk_size_bytes, total_chunks, original_filename, "
                        "metadata_json, status, created_at, updated_at, expires_at) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?)",
                        (
                            current["id"],
                            batch_id,
                            photo_uuid,
                            owner_account_id,
                            batch["project_id"],
                            target_machine_id,
                            original_sha,
                            total_size,
                            chunk_size,
                            total_chunks,
                            original_filename,
                            wanted_metadata,
                            timestamp,
                            timestamp,
                            expires_at,
                        ),
                    )
                    session_id = int(cur.lastrowid)
                conn.commit()
                row = conn.execute(
                    "SELECT * FROM mobile_upload_sessions WHERE id = ?", (session_id,)
                ).fetchone()
                return jsonify(
                    {
                        "ok": True,
                        "idempotent": False,
                        "upload": chunk_upload_payload(conn, row),
                    }
                ), 201
            finally:
                conn.close()

    @blueprint.get(
        "/api/mobile/v1/batches/<int:batch_id>/chunked-uploads/<photo_uuid>"
    )
    def get_chunk_upload(batch_id, photo_uuid):
        current = user()
        photo_uuid = _uuid(photo_uuid, "photo_uuid")
        expire_chunk_sessions()
        conn = db.connect()
        try:
            session = chunk_session_for(conn, current["id"], batch_id, photo_uuid)
            return jsonify(
                {"ok": True, "upload": chunk_upload_payload(conn, session)}
            )
        finally:
            conn.close()

    @blueprint.put(
        "/api/mobile/v1/batches/<int:batch_id>/chunked-uploads/"
        "<photo_uuid>/chunks/<int:chunk_index>"
    )
    def put_upload_chunk(batch_id, photo_uuid, chunk_index):
        current = user()
        photo_uuid = _uuid(photo_uuid, "photo_uuid")
        claimed_chunk_sha = _sha256(
            request.headers.get("X-Chunk-SHA256"), "X-Chunk-SHA256"
        )
        temporary = None
        with _chunk_session_lock(current["id"], photo_uuid):
            conn = db.connect()
            try:
                session = chunk_session_for(conn, current["id"], batch_id, photo_uuid)
                if session["status"] != "active":
                    raise ApiProblem(
                        "chunk_upload_not_active",
                        "分片上传会话已结束，请重新初始化",
                        409,
                    )
                if session["expires_at"] <= now():
                    raise ApiProblem(
                        "chunk_upload_expired", "分片上传会话已过期，请重新开始", 409
                    )
                batch = batch_for(
                    conn, current["id"], batch_id, require_capture=True
                )
                require_chunk_batch_context(batch, session)
                _require_batch_uploadable(batch["status"])
                _require_active_machine(
                    conn,
                    int(
                        session["project_owner_account_id"]
                        or session["account_id"]
                    ),
                    session["target_machine_id"],
                )
                total_chunks = int(session["total_chunks"])
                if chunk_index < 0 or chunk_index >= total_chunks:
                    raise ApiProblem("chunk_index_invalid", "分片索引超出范围", 422)
                chunk_size = int(session["chunk_size_bytes"])
                expected_size = (
                    chunk_size
                    if chunk_index < total_chunks - 1
                    else int(session["total_size_bytes"])
                    - chunk_size * (total_chunks - 1)
                )
                existing = conn.execute(
                    "SELECT * FROM mobile_upload_chunks WHERE session_id = ? "
                    "AND chunk_index = ?",
                    (session["id"], chunk_index),
                ).fetchone()
                if existing:
                    if (
                        existing["sha256"] != claimed_chunk_sha
                        or int(existing["size_bytes"]) != expected_size
                    ):
                        raise ApiProblem(
                            "chunk_conflict",
                            "该分片索引已上传不同内容",
                            409,
                        )
                    return jsonify(
                        {
                            "ok": True,
                            "idempotent": True,
                            "upload_id": int(session["id"]),
                            "photo_uuid": photo_uuid,
                            "chunk_index": chunk_index,
                            "sha256": existing["sha256"],
                            "size_bytes": int(existing["size_bytes"]),
                            "uploaded_chunks": chunk_upload_payload(conn, session)[
                                "uploaded_chunks"
                            ],
                        }
                    )
                if request.content_length is not None and int(request.content_length) != expected_size:
                    raise ApiProblem(
                        "chunk_size_mismatch",
                        "分片大小与当前索引的预期值不一致",
                        422,
                    )
                try:
                    received = chunk_store.read_request_to_temporary(
                        current["id"],
                        session["id"],
                        chunk_index,
                        request.stream,
                        expected_size,
                    )
                    temporary = received["temporary"]
                except ChunkFileError as exc:
                    raise ApiProblem("chunk_size_mismatch", str(exc), 422, True) from exc
                if received["sha256"] != claimed_chunk_sha:
                    chunk_store.discard_temporary(temporary)
                    temporary = None
                    raise ApiProblem(
                        "chunk_sha256_mismatch",
                        "分片校验值不一致，请重新上传该片",
                        422,
                        True,
                    )

                conn.execute("BEGIN IMMEDIATE")
                session = chunk_session_for(conn, current["id"], batch_id, photo_uuid)
                if session["status"] != "active" or session["expires_at"] <= now():
                    raise ApiProblem(
                        "chunk_upload_not_active", "分片上传会话已结束", 409
                    )
                batch = batch_for(
                    conn, current["id"], batch_id, require_capture=True
                )
                require_chunk_batch_context(batch, session)
                _require_batch_uploadable(batch["status"])
                _require_active_machine(
                    conn,
                    int(
                        session["project_owner_account_id"]
                        or session["account_id"]
                    ),
                    session["target_machine_id"],
                )
                existing = conn.execute(
                    "SELECT * FROM mobile_upload_chunks WHERE session_id = ? "
                    "AND chunk_index = ?",
                    (session["id"], chunk_index),
                ).fetchone()
                if existing:
                    chunk_store.discard_temporary(temporary)
                    temporary = None
                    if existing["sha256"] != claimed_chunk_sha:
                        raise ApiProblem(
                            "chunk_conflict", "该分片索引已上传不同内容", 409
                        )
                    conn.rollback()
                    return jsonify(
                        {
                            "ok": True,
                            "idempotent": True,
                            "upload_id": int(session["id"]),
                            "photo_uuid": photo_uuid,
                            "chunk_index": chunk_index,
                            "sha256": existing["sha256"],
                            "size_bytes": int(existing["size_bytes"]),
                            "uploaded_chunks": chunk_upload_payload(conn, session)[
                                "uploaded_chunks"
                            ],
                        }
                    )
                destination = chunk_store.install(
                    current["id"], session["id"], chunk_index, temporary
                )
                temporary = None
                try:
                    timestamp = now()
                    conn.execute(
                        "INSERT INTO mobile_upload_chunks (session_id, chunk_index, "
                        "sha256, size_bytes, created_at) VALUES (?, ?, ?, ?, ?)",
                        (
                            session["id"],
                            chunk_index,
                            claimed_chunk_sha,
                            expected_size,
                            timestamp,
                        ),
                    )
                    conn.execute(
                        "UPDATE mobile_upload_sessions SET updated_at = ?, expires_at = ? "
                        "WHERE id = ?",
                        (
                            timestamp,
                            _future_timestamp(
                                timestamp, config.MOBILE_CHUNK_TTL_SECONDS
                            ),
                            session["id"],
                        ),
                    )
                    conn.commit()
                except Exception:
                    conn.rollback()
                    try:
                        destination.unlink(missing_ok=True)
                    except OSError:
                        pass
                    raise
                session = conn.execute(
                    "SELECT * FROM mobile_upload_sessions WHERE id = ?", (session["id"],)
                ).fetchone()
                payload = chunk_upload_payload(conn, session)
                return jsonify(
                    {
                        "ok": True,
                        "idempotent": False,
                        "upload_id": int(session["id"]),
                        "photo_uuid": photo_uuid,
                        "chunk_index": chunk_index,
                        "sha256": claimed_chunk_sha,
                        "size_bytes": expected_size,
                        "uploaded_chunks": payload["uploaded_chunks"],
                    }
                ), 201
            finally:
                if temporary is not None:
                    chunk_store.discard_temporary(temporary)
                conn.close()

    @blueprint.post(
        "/api/mobile/v1/batches/<int:batch_id>/chunked-uploads/"
        "<photo_uuid>/finalize"
    )
    def finalize_chunk_upload(batch_id, photo_uuid):
        current = user()
        photo_uuid = _uuid(photo_uuid, "photo_uuid")
        data = json_body()
        final_sha = _sha256(data.get("sha256"), "sha256")
        final_size = _strict_integer(
            data.get("original_size_bytes"),
            "original_size_bytes",
            1,
        )
        if final_size > config.MOBILE_MAX_ORIGINAL_BYTES:
            raise ApiProblem("original_too_large", "原图不能超过 50MB", 413)
        final_chunks = _strict_integer(data.get("total_chunks"), "total_chunks", 1)
        with _chunk_session_lock(current["id"], photo_uuid):
            assembled = None
            photo_inserted = False
            conn = db.connect()
            try:
                conn.execute("BEGIN IMMEDIATE")
                session = chunk_session_for(conn, current["id"], batch_id, photo_uuid)
                if (
                    final_sha != session["original_sha256"]
                    or final_size != int(session["total_size_bytes"])
                    or final_chunks != int(session["total_chunks"])
                ):
                    raise ApiProblem(
                        "chunk_finalize_mismatch",
                        "完成参数与初始化的原图信息不一致",
                        422,
                    )
                existing_photo = matching_session_photo(conn, session)
                if existing_photo:
                    timestamp = now()
                    conn.execute(
                        "UPDATE mobile_upload_sessions SET status = 'completed', "
                        "error_code = '', error_message = '', completed_at = CASE "
                        "WHEN completed_at = '' THEN ? ELSE completed_at END, "
                        "cleanup_status = 'pending', cleanup_error = '', updated_at = ? "
                        "WHERE id = ?",
                        (timestamp, timestamp, session["id"]),
                    )
                    conn.execute(
                        "DELETE FROM mobile_upload_chunks WHERE session_id = ?",
                        (session["id"],),
                    )
                    conn.commit()
                    cleanup_chunk_session_files(current["id"], session["id"])
                    row = conn.execute(
                        "SELECT * FROM mobile_upload_sessions WHERE id = ?",
                        (session["id"],),
                    ).fetchone()
                    return jsonify(
                        {
                            "ok": True,
                            "idempotent": True,
                            "photo": _photo_payload(
                                existing_photo,
                                preview_download_url(existing_photo, current["id"]),
                                conn=conn,
                            ),
                            "upload": chunk_upload_payload(conn, row),
                        }
                    )
                if session["status"] == "completed":
                    raise ApiProblem(
                        "chunk_upload_inconsistent",
                        "分片会话已完成但照片记录不存在，请更换照片 UUID",
                        409,
                    )
                if session["status"] not in {"active", "finalizing"}:
                    raise ApiProblem(
                        "chunk_upload_not_active", "分片上传会话已结束，请重新初始化", 409
                    )
                if session["expires_at"] <= now():
                    raise ApiProblem(
                        "chunk_upload_expired", "分片上传会话已过期，请重新开始", 409
                    )
                batch = batch_for(
                    conn, current["id"], batch_id, require_capture=True
                )
                require_chunk_batch_context(batch, session)
                _require_batch_uploadable(batch["status"])
                _require_active_machine(
                    conn,
                    int(
                        session["project_owner_account_id"]
                        or session["account_id"]
                    ),
                    session["target_machine_id"],
                )
                chunks = conn.execute(
                    "SELECT * FROM mobile_upload_chunks WHERE session_id = ? "
                    "ORDER BY chunk_index",
                    (session["id"],),
                ).fetchall()
                if [int(row["chunk_index"]) for row in chunks] != list(
                    range(final_chunks)
                ):
                    raise ApiProblem(
                        "chunks_incomplete", "原图分片尚未全部上传", 409, True
                    )
                timestamp = now()
                conn.execute(
                    "UPDATE mobile_upload_sessions SET status = 'finalizing', "
                    "updated_at = ?, expires_at = ? WHERE id = ?",
                    (
                        timestamp,
                        _future_timestamp(timestamp, config.MOBILE_CHUNK_TTL_SECONDS),
                        session["id"],
                    ),
                )
                conn.commit()
            finally:
                conn.close()

            try:
                try:
                    assembled, assembled_sha = chunk_store.assemble(
                        current["id"], session["id"], chunks, final_size
                    )
                except ChunkFileError as exc:
                    fail_chunk_session(session, "chunk_assembly_failed", str(exc))
                    raise ApiProblem(
                        "chunk_assembly_failed", str(exc), 422, True
                    ) from exc
                if assembled_sha != final_sha:
                    fail_chunk_session(
                        session,
                        "sha256_mismatch",
                        "组装后的原图校验值不一致，请重新上传",
                    )
                    raise ApiProblem(
                        "sha256_mismatch",
                        "组装后的原图校验值不一致，请重新上传",
                        422,
                        True,
                    )
                metadata = _json(session["metadata_json"], {})
                try:
                    photo, _ = insert_photo(
                        current_user=current,
                        photo_uuid=photo_uuid,
                        project_id=session["project_id"],
                        scope=batch["scope"],
                        category=batch["category"],
                        assignment=_json(batch["assignment_json"], {}),
                        title=metadata.get("title", ""),
                        photo_date=metadata.get("photo_date", ""),
                        client_captured_at=metadata.get("client_captured_at", ""),
                        orientation=metadata.get("orientation", 1),
                        source="mobile",
                        batch_id=batch_id,
                        file_storage=FileStorage(
                            stream=assembled,
                            filename=session["original_filename"],
                            name="file",
                        ),
                        claimed_sha=final_sha,
                        claimed_size=final_size,
                        target_machine_id=session["target_machine_id"],
                        original_filename=session["original_filename"],
                        upload_max_bytes=config.MOBILE_MAX_ORIGINAL_BYTES,
                        project_owner_account_id=(
                            session["project_owner_account_id"]
                            or batch["project_owner_account_id"]
                            or current["id"]
                        ),
                        capture_source=metadata.get("capture_source", ""),
                        transfer_profile=metadata.get("transfer_profile", ""),
                    )
                    photo_inserted = True
                except ApiProblem as exc:
                    fail_chunk_session(session, exc.code, exc.message)
                    raise
                except Exception as exc:
                    fail_chunk_session(
                        session, "chunk_finalize_failed", "原图入库失败，请重新上传"
                    )
                    raise ApiProblem(
                        "chunk_finalize_failed",
                        "原图入库失败，请重新上传",
                        503,
                        True,
                    ) from exc
                finally:
                    if assembled is not None:
                        assembled.close()
                        assembled = None

                complete_conn = db.connect()
                try:
                    complete_conn.execute("BEGIN IMMEDIATE")
                    complete_session = chunk_session_for(
                        complete_conn, current["id"], batch_id, photo_uuid
                    )
                    timestamp = now()
                    complete_conn.execute(
                        "UPDATE mobile_upload_sessions SET status = 'completed', "
                        "error_code = '', error_message = '', cleanup_status = 'pending', "
                        "cleanup_error = '', completed_at = ?, updated_at = ? "
                        "WHERE id = ?",
                        (timestamp, timestamp, complete_session["id"]),
                    )
                    complete_conn.execute(
                        "DELETE FROM mobile_upload_chunks WHERE session_id = ?",
                        (complete_session["id"],),
                    )
                    complete_conn.commit()
                finally:
                    complete_conn.close()
                cleanup_chunk_session_files(current["id"], session["id"])
                payload_conn = db.connect()
                try:
                    final_session = payload_conn.execute(
                        "SELECT * FROM mobile_upload_sessions WHERE id = ?",
                        (session["id"],),
                    ).fetchone()
                    upload_payload = chunk_upload_payload(
                        payload_conn, final_session
                    )
                finally:
                    payload_conn.close()
                return jsonify(
                    {
                        "ok": True,
                        "idempotent": False,
                        "photo": hydrated_photo_payload(photo, current["id"]),
                        "upload": upload_payload,
                    }
                ), 201
            except ApiProblem:
                raise
            except Exception as exc:
                if photo_inserted:
                    raise ApiProblem(
                        "chunk_finalize_response_uncertain",
                        "原图已安全保存，请重试完成请求以确认结果",
                        503,
                        True,
                    ) from exc
                raise

    @blueprint.post(
        "/api/mobile/v1/batches/<int:batch_id>/chunked-uploads/"
        "<photo_uuid>/abort"
    )
    def abort_chunk_upload(batch_id, photo_uuid):
        current = user()
        photo_uuid = _uuid(photo_uuid, "photo_uuid")
        with _chunk_session_lock(current["id"], photo_uuid):
            conn = db.connect()
            try:
                conn.execute("BEGIN IMMEDIATE")
                session = chunk_session_for(conn, current["id"], batch_id, photo_uuid)
                idempotent = session["status"] in {"aborted", "completed"}
                cleanup_needed = session["cleanup_status"] != "cleaned"
                if session["status"] != "completed":
                    conn.execute(
                        "UPDATE mobile_upload_sessions SET status = 'aborted', "
                        "error_code = '', error_message = '', cleanup_status = 'pending', "
                        "cleanup_error = '', updated_at = ? WHERE id = ?",
                        (now(), session["id"]),
                    )
                    cleanup_needed = True
                    conn.execute(
                        "DELETE FROM mobile_upload_chunks WHERE session_id = ?",
                        (session["id"],),
                    )
                conn.commit()
            finally:
                conn.close()
            if cleanup_needed:
                cleanup_chunk_session_files(current["id"], session["id"])
            payload_conn = db.connect()
            try:
                row = payload_conn.execute(
                    "SELECT * FROM mobile_upload_sessions WHERE id = ?", (session["id"],)
                ).fetchone()
                payload = chunk_upload_payload(payload_conn, row)
            finally:
                payload_conn.close()
            return jsonify(
                {"ok": True, "idempotent": idempotent, "upload": payload}
            )

    def analysis_job_payload(row) -> dict:
        item = dict(row)
        return {
            "job_id": int(item["id"]),
            "batch_id": int(item["batch_id"] or 0),
            "type": item["job_type"],
            "status": item["status"],
            "result": _json(item["result_json"], {}),
            "error": (
                {"code": item["error_code"], "message": item["error_text"]}
                if item["error_code"] or item["error_text"]
                else None
            ),
            "created_at": item["created_at"],
            "updated_at": item["updated_at"],
        }

    def recover_stale_analysis_jobs(*, force: bool = False) -> None:
        cutoff = _future_timestamp(now(), -config.MOBILE_ANALYSIS_STALE_SECONDS)
        conn = db.connect()
        try:
            if force:
                # create_app 时本进程尚未提交任何任务，数据库里的运行态必然
                # 来自已退出的旧进程；立即降级，不让重启后的客户端空等 TTL。
                stale = conn.execute(
                    "SELECT * FROM mobile_jobs WHERE job_type = 'analyze' "
                    "AND status IN ('queued', 'running')"
                ).fetchall()
            else:
                stale = conn.execute(
                    "SELECT * FROM mobile_jobs WHERE job_type = 'analyze' "
                    "AND status = 'running' AND updated_at < ?",
                    (cutoff,),
                ).fetchall()
            if not stale:
                return
            # 常规批次轮询先只读；确实存在候选后才拿短写锁，并在锁内重查
            # 心跳，避免高频 GET 无谓阻塞上传/回执。
            conn.execute("BEGIN IMMEDIATE")
            if force:
                stale = conn.execute(
                    "SELECT * FROM mobile_jobs WHERE job_type = 'analyze' "
                    "AND status IN ('queued', 'running')"
                ).fetchall()
            else:
                stale = conn.execute(
                    "SELECT * FROM mobile_jobs WHERE job_type = 'analyze' "
                    "AND status = 'running' AND updated_at < ?",
                    (cutoff,),
                ).fetchall()
            if not stale:
                conn.rollback()
                return
            timestamp = now()
            for job in stale:
                conn.execute(
                    "UPDATE mobile_jobs SET status = 'failed', "
                    "error_code = 'analysis_interrupted', "
                    "error_text = '服务器重启或识别超时，已转人工确认', updated_at = ? "
                    "WHERE id = ? AND status IN ('queued', 'running')",
                    (timestamp, job["id"]),
                )
                conn.execute(
                    "UPDATE cloud_photos SET status = 'needs_review', "
                    "error_code = 'analysis_interrupted', "
                    "error_message = '自动识别中断，请手动确认', updated_at = ? "
                    "WHERE account_id = ? AND batch_id = ? AND status = 'analyzing'",
                    (timestamp, job["account_id"], job["batch_id"]),
                )
                conn.execute(
                    "UPDATE mobile_batches SET status = 'needs_review', "
                    "error_code = 'analysis_interrupted', "
                    "error_message = '自动识别中断，请手动确认', updated_at = ? "
                    "WHERE account_id = ? AND id = ? AND status = 'analyzing'",
                    (timestamp, job["account_id"], job["batch_id"]),
                )
            conn.commit()
        finally:
            conn.close()

    def keep_analysis_job_alive(
        account_id: int, job_id: int, stop_event: threading.Event
    ) -> None:
        """独立刷新运行租约，单张 OCR 很慢时也不会被轮询误判中断。"""
        interval = max(
            0.1,
            min(30.0, float(config.MOBILE_ANALYSIS_STALE_SECONDS) / 3.0),
        )
        while not stop_event.is_set():
            heartbeat = None
            try:
                heartbeat = db.connect()
                heartbeat.execute(
                    "UPDATE mobile_jobs SET updated_at = ? WHERE id = ? "
                    "AND account_id = ? AND status = 'running'",
                    (now(), job_id, account_id),
                )
                heartbeat.commit()
            except Exception as exc:
                warnings.warn(f"识别任务心跳写入失败，将继续重试: {exc}")
            finally:
                if heartbeat is not None:
                    heartbeat.close()
            if stop_event.wait(interval):
                break

    def degrade_analysis_job(account_id: int, batch_id: int, job_id: int, _exc) -> None:
        conn = db.connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            timestamp = now()
            conn.execute(
                "UPDATE cloud_photos SET status = 'needs_review', "
                "error_code = 'analysis_failed', "
                "error_message = '自动识别失败，请手动选择归属', updated_at = ? "
                "WHERE account_id = ? AND batch_id = ? AND status = 'analyzing'",
                (timestamp, account_id, batch_id),
            )
            conn.execute(
                "UPDATE mobile_batches SET status = 'needs_review', "
                "error_code = 'analysis_failed', "
                "error_message = '自动识别失败，请手动选择归属', updated_at = ? "
                "WHERE account_id = ? AND id = ? AND status = 'analyzing'",
                (timestamp, account_id, batch_id),
            )
            conn.execute(
                "UPDATE mobile_jobs SET status = 'failed', "
                "error_code = 'analysis_failed', error_text = ?, updated_at = ? "
                "WHERE id = ? AND account_id = ? AND status IN ('queued', 'running')",
                (
                    "自动识别失败，请手动确认",
                    timestamp,
                    job_id,
                    account_id,
                ),
            )
            conn.commit()
        finally:
            conn.close()

    def execute_analysis_job(account_id: int, batch_id: int, job_id: int) -> None:
        heartbeat_stop = threading.Event()
        heartbeat_thread = None
        try:
            conn = db.connect()
            try:
                conn.execute("BEGIN IMMEDIATE")
                job = conn.execute(
                    "SELECT * FROM mobile_jobs WHERE id = ? AND account_id = ? "
                    "AND batch_id = ? AND job_type = 'analyze'",
                    (job_id, account_id, batch_id),
                ).fetchone()
                batch = conn.execute(
                    "SELECT * FROM mobile_batches WHERE id = ? AND account_id = ?",
                    (batch_id, account_id),
                ).fetchone()
                if (
                    not job
                    or job["status"] not in {"queued", "running"}
                    or not batch
                    or batch["status"] != "analyzing"
                ):
                    conn.rollback()
                    return
                timestamp = now()
                conn.execute(
                    "UPDATE mobile_jobs SET status = 'running', updated_at = ? WHERE id = ?",
                    (timestamp, job_id),
                )
                conn.commit()
                heartbeat_thread = threading.Thread(
                    target=keep_analysis_job_alive,
                    args=(account_id, job_id, heartbeat_stop),
                    name=f"mobile-ocr-heartbeat-{job_id}",
                    daemon=True,
                )
                heartbeat_thread.start()
                photos = conn.execute(
                    "SELECT * FROM cloud_photos WHERE account_id = ? AND batch_id = ? "
                    "AND status = 'analyzing' ORDER BY id",
                    (account_id, batch_id),
                ).fetchall()
                project_owner_account_id = int(
                    batch["project_owner_account_id"] or batch["account_id"]
                )
                project = project_for(
                    conn,
                    account_id,
                    _project_ref(project_owner_account_id, batch["project_id"]),
                    CAPTURE_ROLES,
                )
                unit_rows = conn.execute(
                    "SELECT * FROM cloud_units WHERE account_id = ? AND project_id = ? "
                    "AND scope = 'engineering' AND active = 1 ORDER BY sort_order, id",
                    (project_owner_account_id, batch["project_id"]),
                ).fetchall()
                candidates = mobile_recognition.candidates_from_cloud_rows(
                    project, unit_rows
                )
            finally:
                conn.close()

            results = []
            confidence_counts = {"high": 0, "medium": 0, "low": 0}
            failed_count = 0
            with mobile_recognition.ANALYZE_LOCK:
                for photo in photos:
                    try:
                        use_original = bool(photo["original_storage_key"]) and photo[
                            "original_cleanup_status"
                        ] not in {"deleted", "not_applicable"}
                        recognition_key = (
                            photo["original_storage_key"]
                            if use_original
                            else photo["preview_storage_key"] or photo["storage_key"]
                        )
                        recognition_limit = (
                            config.MOBILE_MAX_ORIGINAL_BYTES
                            if use_original
                            else config.MOBILE_PREVIEW_MAX_BYTES
                        )
                        image_bytes = storage.get_bytes(
                            recognition_key, recognition_limit
                        )
                        fields = mobile_recognition.recognize_watermark(
                            image_bytes, strict=True
                        )
                        if batch["scope"] == "engineering":
                            matched = mobile_recognition.match_photo(
                                filename=photo["original_filename"],
                                relative_path="",
                                ocr_fields=fields,
                                candidates=candidates,
                                limit=5,
                            )
                        else:
                            matched = {
                                "unit_code": "",
                                "project_code": "",
                                "project_name": "",
                                "confidence": "low",
                                "confidence_label": "低",
                                "ambiguous": False,
                                "score": 0,
                                "reasons": ["其它影像需确认目录"],
                                "alternatives": [],
                                "candidates": [],
                            }
                        confidence = matched["confidence"]
                        confidence_counts[confidence] += 1
                        assignment = _json(photo["assignment_json"], {})
                        if (
                            batch["scope"] == "engineering"
                            and confidence == "high"
                            and not matched.get("ambiguous")
                            and matched.get("unit_code")
                            and not assignment
                        ):
                            assignment = {
                                "unit_code": matched["unit_code"],
                                "process_name": "",
                            }
                        results.append(
                            {
                                "id": photo["id"],
                                "assignment": assignment,
                                "title": photo["title"] or fields.get("title", ""),
                                "photo_date": photo["photo_date"]
                                or fields.get("photo_date", ""),
                                "match": {
                                    **matched,
                                    "ocr": fields,
                                    "manual_review_required": True,
                                },
                                "error_code": "",
                                "error_message": "",
                            }
                        )
                    except Exception:
                        failed_count += 1
                        confidence_counts["low"] += 1
                        results.append(
                            {
                                "id": photo["id"],
                                "assignment": _json(photo["assignment_json"], {}),
                                "title": photo["title"],
                                "photo_date": photo["photo_date"],
                                "match": {
                                    "confidence": "low",
                                    "confidence_label": "低",
                                    "ambiguous": False,
                                    "score": 0,
                                    "reasons": ["自动识别失败，请手动选择归属"],
                                    "alternatives": [],
                                    "candidates": [],
                                    "ocr": {},
                                    "manual_review_required": True,
                                },
                                "error_code": "analysis_failed",
                                "error_message": "自动识别失败，请手动选择归属",
                            }
                        )
                    finally:
                        # 每完成一张就刷新心跳；只有真正停滞的任务才会被重启恢复
                        # 逻辑转为人工确认，长批次不会因总时长较长被误判。
                        heartbeat = db.connect()
                        try:
                            heartbeat.execute(
                                "UPDATE mobile_jobs SET updated_at = ? WHERE id = ? "
                                "AND account_id = ? AND status = 'running'",
                                (now(), job_id, account_id),
                            )
                            heartbeat.commit()
                        finally:
                            heartbeat.close()

            conn = db.connect()
            try:
                conn.execute("BEGIN IMMEDIATE")
                current_batch = conn.execute(
                    "SELECT status FROM mobile_batches WHERE id = ? AND account_id = ?",
                    (batch_id, account_id),
                ).fetchone()
                if not current_batch or current_batch["status"] != "analyzing":
                    conn.execute(
                        "UPDATE mobile_jobs SET status = 'failed', "
                        "error_code = 'analysis_superseded', "
                        "error_text = '批次状态已前进，识别结果未覆盖终态', updated_at = ? "
                        "WHERE id = ? AND account_id = ? AND status IN ('queued', 'running')",
                        (now(), job_id, account_id),
                    )
                    conn.commit()
                    return
                timestamp = now()
                for result_item in results:
                    conn.execute(
                        "UPDATE cloud_photos SET status = 'needs_review', "
                        "assignment_json = ?, title = ?, photo_date = ?, match_json = ?, "
                        "error_code = ?, error_message = ?, updated_at = ? "
                        "WHERE id = ? AND account_id = ? AND status = 'analyzing'",
                        (
                            _dumps(result_item["assignment"]),
                            _safe_text(result_item["title"], 200),
                            _photo_date(result_item["photo_date"]),
                            _dumps(result_item["match"]),
                            result_item["error_code"],
                            result_item["error_message"],
                            timestamp,
                            result_item["id"],
                            account_id,
                        ),
                    )
                result = {
                    "photo_count": len(photos),
                    "matched_count": confidence_counts["high"],
                    "confidence": confidence_counts,
                    "failed_count": failed_count,
                    "manual_review_required": True,
                    "ocr_available": True,
                }
                conn.execute(
                    "UPDATE mobile_jobs SET status = ?, result_json = ?, error_code = ?, "
                    "error_text = ?, updated_at = ? WHERE id = ? AND account_id = ? "
                    "AND status IN ('queued', 'running')",
                    (
                        "completed" if failed_count < len(photos) else "failed",
                        _dumps(result),
                        "analysis_partial_failure" if failed_count else "",
                        "部分照片识别失败，已转人工确认" if failed_count else "",
                        timestamp,
                        job_id,
                        account_id,
                    ),
                )
                conn.execute(
                    "UPDATE mobile_batches SET status = 'needs_review', error_code = ?, "
                    "error_message = ?, updated_at = ? WHERE id = ? AND account_id = ? "
                    "AND status = 'analyzing'",
                    (
                        "analysis_partial_failure" if failed_count else "",
                        "部分照片识别失败，请手动确认" if failed_count else "",
                        timestamp,
                        batch_id,
                        account_id,
                    ),
                )
                conn.commit()
            finally:
                conn.close()
        except Exception as exc:
            degrade_analysis_job(account_id, batch_id, job_id, exc)
        finally:
            heartbeat_stop.set()
            if heartbeat_thread is not None:
                heartbeat_thread.join(timeout=2.0)

    @blueprint.post("/api/mobile/v1/batches/<int:batch_id>/analyze")
    def analyze_batch(batch_id):
        current = user()
        recover_stale_analysis_jobs()
        conn = db.connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            batch = batch_for(
                conn, current["id"], batch_id, require_capture=True
            )
            latest_job = conn.execute(
                "SELECT * FROM mobile_jobs WHERE account_id = ? AND batch_id = ? "
                "AND job_type = 'analyze' ORDER BY id DESC LIMIT 1",
                (current["id"], batch_id),
            ).fetchone()
            if batch["status"] == "analyzing":
                if not latest_job or latest_job["status"] not in {"queued", "running"}:
                    timestamp = now()
                    conn.execute(
                        "UPDATE cloud_photos SET status = 'needs_review', "
                        "error_code = 'analysis_interrupted', "
                        "error_message = '识别任务状态丢失，请手动确认', updated_at = ? "
                        "WHERE account_id = ? AND batch_id = ? AND status = 'analyzing'",
                        (timestamp, current["id"], batch_id),
                    )
                    conn.execute(
                        "UPDATE mobile_batches SET status = 'needs_review', "
                        "error_code = 'analysis_interrupted', "
                        "error_message = '识别任务状态丢失，请手动确认', updated_at = ? "
                        "WHERE id = ? AND account_id = ? AND status = 'analyzing'",
                        (timestamp, batch_id, current["id"]),
                    )
                    conn.commit()
                    repaired = batch_for(conn, current["id"], batch_id)
                    return jsonify(
                        {
                            "ok": True,
                            "idempotent": True,
                            "job": analysis_job_payload(latest_job)
                            if latest_job
                            else None,
                            "batch": batch_payload(conn, repaired),
                        }
                    )
                conn.rollback()
                return jsonify(
                    {
                        "ok": True,
                        "idempotent": True,
                        "job": analysis_job_payload(latest_job),
                        "batch": batch_payload(conn, batch),
                    }
                ), 202
            if batch["status"] == "needs_review":
                conn.rollback()
                return jsonify(
                    {
                        "ok": True,
                        "idempotent": True,
                        "job": analysis_job_payload(latest_job) if latest_job else None,
                        "batch": batch_payload(conn, batch),
                    }
                )
            if batch["status"] != "server_saved":
                raise ApiProblem(
                    "batch_not_analyzable",
                    "批次已进入归档阶段，不能重新识别",
                    409,
                )
            active_uploads = conn.execute(
                "SELECT COUNT(*) AS total FROM mobile_upload_sessions "
                "WHERE account_id = ? AND batch_id = ? "
                "AND status IN ('active', 'finalizing')",
                (current["id"], batch_id),
            ).fetchone()["total"]
            if int(active_uploads):
                raise ApiProblem(
                    "batch_uploads_incomplete",
                    "批次仍有原图分片未完成，不能开始识别",
                    409,
                    True,
                )
            photos = conn.execute(
                "SELECT id FROM cloud_photos WHERE account_id = ? AND batch_id = ? "
                "AND status = 'server_saved' ORDER BY id",
                (current["id"], batch_id),
            ).fetchall()
            if not photos:
                raise ApiProblem("batch_empty", "批次中没有可识别照片")
            timestamp = now()
            cur = conn.execute(
                "INSERT INTO mobile_jobs (account_id, batch_id, job_type, status, "
                "created_at, updated_at) VALUES (?, ?, 'analyze', 'queued', ?, ?)",
                (current["id"], batch_id, timestamp, timestamp),
            )
            job_id = int(cur.lastrowid)
            conn.execute(
                "UPDATE mobile_batches SET status = 'analyzing', updated_at = ? "
                "WHERE id = ? AND account_id = ? AND status = 'server_saved'",
                (timestamp, batch_id, current["id"]),
            )
            conn.execute(
                "UPDATE cloud_photos SET status = 'analyzing', updated_at = ? "
                "WHERE account_id = ? AND batch_id = ? AND status = 'server_saved'",
                (timestamp, current["id"], batch_id),
            )
            conn.commit()
            try:
                ANALYSIS_EXECUTOR.submit(
                    execute_analysis_job, current["id"], batch_id, job_id
                )
            except RuntimeError as exc:
                degrade_analysis_job(current["id"], batch_id, job_id, exc)
            job = conn.execute(
                "SELECT * FROM mobile_jobs WHERE id = ?", (job_id,)
            ).fetchone()
            batch = batch_for(
                conn, current["id"], batch_id, require_capture=True
            )
            response_payload = {
                "ok": True,
                "idempotent": False,
                "job": analysis_job_payload(job),
                "batch": batch_payload(conn, batch),
            }
        finally:
            conn.close()
        return jsonify(response_payload), 202

    @blueprint.get("/api/mobile/v1/jobs/<int:job_id>")
    def analysis_job_detail(job_id):
        current = user()
        recover_stale_analysis_jobs()
        conn = db.connect()
        try:
            job = conn.execute(
                "SELECT * FROM mobile_jobs WHERE id = ? AND account_id = ? "
                "AND job_type = 'analyze' AND batch_id IS NOT NULL",
                (job_id, current["id"]),
            ).fetchone()
            if not job:
                raise ApiProblem("job_not_found", "识别任务不存在", 404)
            batch = batch_for(conn, current["id"], job["batch_id"])
            return jsonify(
                {
                    "ok": True,
                    "job": analysis_job_payload(job),
                    "batch": batch_payload(conn, batch),
                }
            )
        finally:
            conn.close()

    @blueprint.patch("/api/mobile/v1/batches/<int:batch_id>/assignments")
    def assign_batch(batch_id):
        current = user()
        data = json_body()
        assignments = data.get("assignments")
        if not isinstance(assignments, list):
            assignments = [data]
        if not assignments:
            raise ApiProblem("assignments_required", "缺少照片归属信息")
        conn = db.connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            batch = batch_for(
                conn, current["id"], batch_id, require_capture=True
            )
            if batch["status"] in {"desktop_pending", "desktop_imported"}:
                raise ApiProblem(
                    "batch_committed", "批次已提交电脑归档，不能再修改归属", 409
                )
            if batch["status"] == "analyzing":
                raise ApiProblem("batch_analyzing", "批次正在自动识别，请稍后再修改", 409)
            for item in assignments:
                if not isinstance(item, dict):
                    raise ApiProblem("invalid_assignment", "照片归属格式不正确")
                photo_uuid = _uuid(item.get("photo_uuid"), "photo_uuid")
                photo = conn.execute(
                    "SELECT * FROM cloud_photos WHERE account_id = ? AND batch_id = ? AND photo_uuid = ?",
                    (current["id"], batch_id, photo_uuid),
                ).fetchone()
                if not photo:
                    raise ApiProblem("photo_not_found", "批次中的照片不存在", 404)
                if photo["status"] in {"desktop_pending", "desktop_imported"}:
                    raise ApiProblem(
                        "photo_committed", "照片已提交电脑归档，不能再修改归属", 409
                    )
                target = item.get("assignment") if isinstance(item.get("assignment"), dict) else item
                normalized = _validate_assignment(
                    conn,
                    int(
                        batch["project_owner_account_id"] or batch["account_id"]
                    ),
                    batch["project_id"],
                    batch["scope"],
                    target,
                    require_process=(
                        batch.get("transfer_profile", "")
                        == JPEG_1M_TRANSFER_PROFILE
                    ),
                )
                conn.execute(
                    "UPDATE cloud_photos SET assignment_json = ?, title = ?, photo_date = ?, "
                    "status = 'needs_review', error_code = '', error_message = '', updated_at = ? "
                    "WHERE id = ? AND account_id = ?",
                    (
                        _dumps(normalized),
                        _safe_text(item.get("title", photo["title"]), 200),
                        _photo_date(item.get("photo_date", photo["photo_date"])),
                        now(), photo["id"], current["id"],
                    ),
                )
            conn.execute(
                "UPDATE mobile_batches SET status = 'needs_review', updated_at = ?, "
                "error_code = '', error_message = '' WHERE id = ? AND account_id = ?",
                (now(), batch_id, current["id"]),
            )
            conn.commit()
            row = batch_for(conn, current["id"], batch_id)
            return jsonify({"ok": True, "batch": batch_payload(conn, row)})
        finally:
            conn.close()

    @blueprint.post("/api/mobile/v1/batches/<int:batch_id>/commit")
    def commit_batch(batch_id):
        current = user()
        conn = db.connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            batch = batch_for(
                conn, current["id"], batch_id, require_capture=True
            )
            if batch["status"] in {"desktop_pending", "desktop_imported"}:
                conn.rollback()
                return jsonify(
                    {
                        "ok": True,
                        "idempotent": True,
                        "batch": batch_payload(conn, batch),
                    }
                )
            active_uploads = conn.execute(
                "SELECT COUNT(*) AS total FROM mobile_upload_sessions "
                "WHERE account_id = ? AND batch_id = ? "
                "AND status IN ('active', 'finalizing')",
                (current["id"], batch_id),
            ).fetchone()["total"]
            if int(active_uploads):
                raise ApiProblem(
                    "batch_uploads_incomplete",
                    "批次仍有原图分片未完成，请完成或取消后再提交",
                    409,
                    True,
                )
            photos = conn.execute(
                "SELECT * FROM cloud_photos WHERE account_id = ? AND batch_id = ? ORDER BY id",
                (current["id"], batch_id),
            ).fetchall()
            if not photos:
                raise ApiProblem("batch_empty", "批次中没有照片")
            if batch["status"] == "analyzing":
                raise ApiProblem("batch_analyzing", "批次正在自动识别，请稍后再提交", 409)
            for photo in photos:
                # 已投递和已归档状态只能前进，不因客户端重试回退。
                if photo["status"] in {"desktop_pending", "desktop_imported"}:
                    continue
                normalized = _validate_assignment(
                    conn,
                    int(
                        batch["project_owner_account_id"] or batch["account_id"]
                    ),
                    batch["project_id"], batch["scope"],
                    _json(photo["assignment_json"], {}),
                    require_process=(
                        batch.get("transfer_profile", "")
                        == JPEG_1M_TRANSFER_PROFILE
                    ),
                )
                conn.execute(
                    "UPDATE cloud_photos SET assignment_json = ?, status = 'desktop_pending', "
                    "updated_at = ? WHERE id = ? AND account_id = ?",
                    (_dumps(normalized), now(), photo["id"], current["id"]),
                )
            timestamp = now()
            conn.execute(
                "UPDATE mobile_batches SET status = 'desktop_pending', committed_at = ?, "
                "updated_at = ?, error_code = '', error_message = '' "
                "WHERE id = ? AND account_id = ?",
                (timestamp, timestamp, batch_id, current["id"]),
            )
            conn.commit()
            row = batch_for(conn, current["id"], batch_id)
            return jsonify({"ok": True, "idempotent": False, "batch": batch_payload(conn, row)})
        finally:
            conn.close()

    @blueprint.get("/api/desktop/v1/wechat-binding")
    def desktop_wechat_binding():
        current = user()
        desktop_machine_id = require_desktop_client(
            current,
            request.args.get("desktop_machine_id") or request.args.get("machine_id"),
        )
        conn = db.connect()
        try:
            _require_active_machine(conn, current["id"], desktop_machine_id)
            row = conn.execute(
                "SELECT id, app_id, created_at, last_login_at FROM wechat_bindings "
                "WHERE account_id = ? ORDER BY id LIMIT 1",
                (current["id"],),
            ).fetchone()
            return jsonify(
                {
                    "ok": True,
                    "bound": bool(row),
                    "binding": (
                        {
                            "app_id": row["app_id"],
                            "created_at": row["created_at"],
                            "last_login_at": row["last_login_at"],
                        }
                        if row
                        else None
                    ),
                }
            )
        finally:
            conn.close()

    @blueprint.delete("/api/desktop/v1/wechat-binding")
    def desktop_unbind_wechat():
        current = user()
        data = json_body()
        desktop_machine_id = require_desktop_client(
            current,
            data.get("desktop_machine_id") or data.get("machine_id"),
        )
        password = str(data.get("password") or "")
        if not password:
            raise ApiProblem("password_required", "请输入当前桌面账号的登录密码")
        conn = db.connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            _require_active_machine(conn, current["id"], desktop_machine_id)
            account = conn.execute(
                "SELECT password_hash FROM accounts WHERE id = ?",
                (current["id"],),
            ).fetchone()
            if not account or not check_password_hash(account["password_hash"], password):
                raise ApiProblem("account_credentials_invalid", "账号密码错误", 401)
            binding = conn.execute(
                "SELECT id FROM wechat_bindings WHERE account_id = ? ORDER BY id LIMIT 1",
                (current["id"],),
            ).fetchone()
            if binding:
                conn.execute(
                    "DELETE FROM wechat_bindings WHERE id = ? AND account_id = ?",
                    (binding["id"], current["id"]),
                )
                conn.execute(
                    "UPDATE accounts SET mobile_auth_version = "
                    "COALESCE(mobile_auth_version, 0) + 1 WHERE id = ?",
                    (current["id"],),
                )
            conn.commit()
            return jsonify(
                {
                    "ok": True,
                    "idempotent": not bool(binding),
                    "message": "微信已解绑，旧手机登录已立即失效"
                    if binding
                    else "当前账号未绑定微信",
                }
            )
        finally:
            conn.close()

    @blueprint.post("/api/desktop/v1/project-snapshot")
    def desktop_project_snapshot():
        current = user()
        data = json_body()
        snapshot_id = _uuid(data.get("snapshot_id"), "snapshot_id")
        revision = _integer(data.get("revision"), 0, 0, 10**12)
        project = data.get("project") if isinstance(data.get("project"), dict) else {}
        project_id = _project_id(
            project.get("id") or project.get("project_id") or project.get("project_code") or data.get("project_id")
        )
        project_code = _safe_text(project.get("project_code") or project_id, 100)
        project_name = _safe_text(project.get("project_name") or project.get("name") or DEFAULT_PROJECT_NAME, 300)
        desktop_machine_id = _machine_id(
            data.get("desktop_machine_id") or data.get("client_id")
        )
        desktop_machine_id = require_desktop_client(current, desktop_machine_id)
        tree = data.get("tree") if isinstance(data.get("tree"), list) else []
        other_tree = data.get("other_tree") if isinstance(data.get("other_tree"), list) else []
        requirements_supplied = isinstance(data.get("requirements"), list)
        requirements = data.get("requirements") if requirements_supplied else []
        if len(requirements) > 5000:
            raise ApiProblem("too_many_requirements", "专业采集规则超过单工程 5000 条上限")
        nodes = _flatten_snapshot(tree, other_tree)
        conn = db.connect()
        try:
            _require_active_machine(conn, current["id"], desktop_machine_id)
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute(
                "SELECT * FROM cloud_engineering_projects WHERE account_id = ? AND project_id = ?",
                (current["id"], project_id),
            ).fetchone()
            if existing and revision < int(existing["revision"] or 0):
                raise ApiProblem("stale_revision", "工程快照版本早于服务器版本", 409)
            existing_archive_machine = _machine_id(
                existing["desktop_machine_id"] if existing else ""
            )
            if (
                existing_archive_machine
                and existing_archive_machine != desktop_machine_id
            ):
                raise ApiProblem(
                    "project_archive_machine_conflict",
                    "该工程已绑定另一台归档电脑，请先在原电脑解除绑定",
                    409,
                )
            timestamp = now()
            metadata = (
                _json(existing["metadata_json"], {})
                if existing
                else {}
            )
            metadata.update({
                key: value
                for key, value in project.items()
                if key not in {"id", "project_id", "project_code", "project_name", "name"}
            })
            metadata["unit_count"] = sum(
                1 for node in nodes if node["node_type"] == "unit"
            )
            metadata["process_count"] = sum(
                1 for node in nodes if node["node_type"] == "process"
            )
            metadata["other_node_count"] = sum(
                1 for node in nodes if node["scope"] == "other"
            )
            if requirements_supplied:
                metadata["requirement_count"] = len(
                    [
                        item
                        for item in requirements
                        if isinstance(item, dict)
                        and _safe_text(item.get("template_code"), 80)
                    ]
                )
                metadata["requirement_summary"] = (
                    data.get("requirement_summary")
                    if isinstance(data.get("requirement_summary"), dict)
                    else {}
                )
            conn.execute(
                "INSERT INTO cloud_engineering_projects (account_id, project_id, project_code, "
                "project_name, snapshot_id, revision, desktop_machine_id, metadata_json, active, "
                "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?) "
                "ON CONFLICT(account_id, project_id) "
                "DO UPDATE SET project_code = excluded.project_code, project_name = excluded.project_name, "
                "snapshot_id = excluded.snapshot_id, revision = excluded.revision, "
                "desktop_machine_id = excluded.desktop_machine_id, "
                "metadata_json = excluded.metadata_json, active = 1, updated_at = excluded.updated_at",
                (
                    current["id"], project_id, project_code, project_name, snapshot_id,
                    revision, desktop_machine_id, _dumps(metadata), timestamp, timestamp,
                ),
            )
            # 每个桌面工程天然拥有一个不可移除的 owner 成员。旧账号在首次同步
            # 快照时也会补齐这条关系，移动端随后即可用 canonical 工程引用访问。
            conn.execute(
                "INSERT INTO project_members "
                "(project_owner_account_id, project_id, member_account_id, role, status, "
                "invited_by_account_id, joined_at, updated_at, removed_at, "
                "removed_by_account_id) VALUES (?, ?, ?, 'owner', 'active', ?, ?, ?, '', 0) "
                "ON CONFLICT(project_owner_account_id, project_id, member_account_id) "
                "DO UPDATE SET role = 'owner', status = 'active', updated_at = excluded.updated_at, "
                "removed_at = '', removed_by_account_id = 0",
                (
                    current["id"],
                    project_id,
                    current["id"],
                    current["id"],
                    timestamp,
                    timestamp,
                ),
            )
            conn.execute(
                "UPDATE cloud_units SET active = 0, updated_at = ? WHERE account_id = ? AND project_id = ?",
                (timestamp, current["id"], project_id),
            )
            for node in nodes:
                conn.execute(
                    "INSERT INTO cloud_units (account_id, project_id, scope, node_code, parent_code, "
                    "node_type, name, sort_order, metadata_json, active, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?) "
                    "ON CONFLICT(account_id, project_id, scope, node_code) DO UPDATE SET "
                    "parent_code = excluded.parent_code, node_type = excluded.node_type, name = excluded.name, "
                    "sort_order = excluded.sort_order, metadata_json = excluded.metadata_json, "
                    "active = 1, updated_at = excluded.updated_at",
                    (
                        current["id"], project_id, node["scope"], node["node_code"],
                        node["parent_code"], node["node_type"], node["name"], node["sort_order"],
                        _dumps(node["metadata"]), timestamp,
                    ),
                )
            if requirements_supplied:
                conn.execute(
                    "UPDATE cloud_project_requirements SET active = 0, updated_at = ? "
                    "WHERE account_id = ? AND project_id = ?",
                    (timestamp, current["id"], project_id),
                )
                for requirement in requirements:
                    if not isinstance(requirement, dict):
                        continue
                    template_code = _safe_text(requirement.get("template_code"), 80)
                    if not template_code:
                        continue

                    def yes_value(key, default=False):
                        value = requirement.get(key)
                        if value is None:
                            return 1 if default else 0
                        return (
                            1
                            if str(value).strip().lower()
                            in {"1", "true", "yes", "是", "y"}
                            else 0
                        )

                    required_type = _safe_text(
                        requirement.get("required_type") or "recommended", 32
                    )
                    if required_type not in {"required", "conditional", "recommended"}:
                        required_type = "recommended"
                    conn.execute(
                        "INSERT INTO cloud_project_requirements "
                        "(account_id, project_id, template_code, industry, project_type, "
                        "phase, division, subdivision, item, process, requirement_name, "
                        "required_type, condition_text, min_photo_count, recommended_count, "
                        "shot_types, timing, before_concealment, gps_required, exif_required, "
                        "description_template, standard_source, template_version, active, updated_at) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, "
                        "?, ?, ?, 1, ?) "
                        "ON CONFLICT(account_id, project_id, template_code) DO UPDATE SET "
                        "industry=excluded.industry, project_type=excluded.project_type, "
                        "phase=excluded.phase, division=excluded.division, "
                        "subdivision=excluded.subdivision, item=excluded.item, "
                        "process=excluded.process, requirement_name=excluded.requirement_name, "
                        "required_type=excluded.required_type, condition_text=excluded.condition_text, "
                        "min_photo_count=excluded.min_photo_count, "
                        "recommended_count=excluded.recommended_count, "
                        "shot_types=excluded.shot_types, timing=excluded.timing, "
                        "before_concealment=excluded.before_concealment, "
                        "gps_required=excluded.gps_required, exif_required=excluded.exif_required, "
                        "description_template=excluded.description_template, "
                        "standard_source=excluded.standard_source, "
                        "template_version=excluded.template_version, active=1, "
                        "updated_at=excluded.updated_at",
                        (
                            current["id"],
                            project_id,
                            template_code,
                            _safe_text(requirement.get("industry"), 80),
                            _safe_text(requirement.get("project_type"), 120),
                            _safe_text(requirement.get("phase"), 120),
                            _safe_text(requirement.get("division"), 160),
                            _safe_text(requirement.get("subdivision"), 160),
                            _safe_text(requirement.get("item"), 160),
                            _safe_text(requirement.get("process"), 160),
                            _safe_text(requirement.get("photo_requirement_name"), 200),
                            required_type,
                            _safe_text(requirement.get("condition"), 300),
                            _integer(requirement.get("min_photo_count"), 1, 0, 999),
                            _integer(
                                requirement.get("recommended_photo_count"), 1, 0, 999
                            ),
                            _safe_text(requirement.get("shot_types"), 200),
                            _safe_text(requirement.get("timing"), 200),
                            yes_value("before_concealment_required"),
                            yes_value("gps_required"),
                            yes_value("exif_required", True),
                            _safe_text(requirement.get("description_template"), 500),
                            _safe_text(requirement.get("standard_source"), 500),
                            _safe_text(
                                requirement.get("template_version") or "V1.0", 40
                            ),
                            timestamp,
                        ),
                    )
            requirement_count = int(
                conn.execute(
                    "SELECT COUNT(*) AS total FROM cloud_project_requirements "
                    "WHERE account_id = ? AND project_id = ? AND active = 1",
                    (current["id"], project_id),
                ).fetchone()["total"]
            )
            if requirements_supplied:
                metadata["requirement_count"] = requirement_count
                conn.execute(
                    "UPDATE cloud_engineering_projects SET metadata_json = ? "
                    "WHERE account_id = ? AND project_id = ?",
                    (_dumps(metadata), current["id"], project_id),
                )
            client_id = desktop_machine_id or "default"
            conn.execute(
                "INSERT INTO desktop_sync_cursors (account_id, client_id, snapshot_id, "
                "snapshot_revision, updated_at) VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(account_id, client_id) DO UPDATE SET snapshot_id = excluded.snapshot_id, "
                "snapshot_revision = excluded.snapshot_revision, updated_at = excluded.updated_at",
                (current["id"], client_id, snapshot_id, revision, timestamp),
            )
            conn.commit()
            return jsonify(
                {
                    "ok": True,
                    "project_id": project_id,
                    "project_ref": _project_ref(current["id"], project_id),
                    "local_project_id": project_id,
                    "owner_account_id": int(current["id"]),
                    "snapshot_id": snapshot_id,
                    "revision": revision,
                    "desktop_machine_id": desktop_machine_id,
                    "unit_count": sum(1 for node in nodes if node["node_type"] == "unit"),
                    "process_count": sum(1 for node in nodes if node["node_type"] == "process"),
                    "other_node_count": sum(1 for node in nodes if node["scope"] == "other"),
                    "requirement_count": requirement_count,
                }
            )
        finally:
            conn.close()

    def desktop_project_context(conn, current, project_id, desktop_machine_id):
        local_project_id = _project_id(project_id)
        project = project_for_desktop(
            conn, current, local_project_id, desktop_machine_id
        )
        project["access_role"] = "owner"
        project["member_count"] = int(
            conn.execute(
                "SELECT COUNT(*) AS total FROM project_members "
                "WHERE project_owner_account_id = ? AND project_id = ? "
                "AND status = 'active'",
                (current["id"], local_project_id),
            ).fetchone()["total"]
        )
        owner_membership = conn.execute(
            "SELECT joined_at FROM project_members WHERE project_owner_account_id = ? "
            "AND project_id = ? AND member_account_id = ? AND status = 'active'",
            (current["id"], local_project_id, current["id"]),
        ).fetchone()
        project["joined_at"] = owner_membership["joined_at"] if owner_membership else ""
        return project

    @blueprint.get("/api/desktop/v1/project-members")
    def desktop_project_members():
        current = user()
        project_id = request.args.get("project_id")
        desktop_machine_id = require_desktop_client(
            current,
            request.args.get("desktop_machine_id") or request.args.get("machine_id"),
        )
        conn = db.connect()
        try:
            project = desktop_project_context(
                conn, current, project_id, desktop_machine_id
            )
            rows = project_members_rows(
                conn, current["id"], project["project_id"]
            )
            return jsonify(
                {
                    "ok": True,
                    "project": _project_payload(project),
                    "members": [member_payload(row, current["id"]) for row in rows],
                }
            )
        finally:
            conn.close()

    @blueprint.get("/api/desktop/v1/project-invites")
    def desktop_project_invites():
        current = user()
        project_id = request.args.get("project_id")
        desktop_machine_id = require_desktop_client(
            current,
            request.args.get("desktop_machine_id") or request.args.get("machine_id"),
        )
        conn = db.connect()
        try:
            project = desktop_project_context(
                conn, current, project_id, desktop_machine_id
            )
            expire_project_invitations(conn)
            conn.commit()
            rows = conn.execute(
                "SELECT * FROM project_invitations WHERE project_owner_account_id = ? "
                "AND project_id = ? AND status = 'pending' ORDER BY id DESC",
                (current["id"], project["project_id"]),
            ).fetchall()
            return jsonify(
                {
                    "ok": True,
                    "project": _project_payload(project),
                    # 邀请码明文只在创建响应出现；列表绝不返回散列或旧明文。
                    "invites": [project_invitation_payload(conn, row) for row in rows],
                }
            )
        finally:
            conn.close()

    @blueprint.post("/api/desktop/v1/project-invites")
    def desktop_create_project_invite():
        current = user()
        data = json_body()
        desktop_machine_id = require_desktop_client(
            current,
            data.get("desktop_machine_id") or data.get("machine_id"),
        )
        conn = db.connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            project = desktop_project_context(
                conn, current, data.get("project_id"), desktop_machine_id
            )
            expire_project_invitations(conn)
            invitation = create_project_invitation(
                conn, current, project, data.get("role") or "capturer"
            )
            conn.commit()
            return jsonify({"ok": True, "invite": invitation}), 201
        finally:
            conn.close()

    @blueprint.delete("/api/desktop/v1/project-invites/<int:invite_id>")
    def desktop_revoke_project_invite(invite_id):
        current = user()
        data = json_body()
        desktop_machine_id = require_desktop_client(
            current,
            data.get("desktop_machine_id") or data.get("machine_id"),
        )
        conn = db.connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            project = desktop_project_context(
                conn, current, data.get("project_id"), desktop_machine_id
            )
            expire_project_invitations(conn)
            invitation = conn.execute(
                "SELECT * FROM project_invitations WHERE id = ? "
                "AND project_owner_account_id = ? AND project_id = ?",
                (invite_id, current["id"], project["project_id"]),
            ).fetchone()
            if not invitation:
                raise ApiProblem("project_invite_not_found", "工程邀请不存在", 404)
            if invitation["status"] == "accepted":
                raise ApiProblem("project_invite_used", "该邀请码已被使用", 409)
            idempotent = invitation["status"] != "pending"
            if not idempotent:
                timestamp = now()
                conn.execute(
                    "UPDATE project_invitations SET status = 'revoked', revoked_at = ?, "
                    "updated_at = ? WHERE id = ? AND status = 'pending'",
                    (timestamp, timestamp, invite_id),
                )
            conn.commit()
            return jsonify(
                {
                    "ok": True,
                    "invite_id": invite_id,
                    "status": "revoked",
                    "idempotent": idempotent,
                }
            )
        finally:
            conn.close()

    @blueprint.patch("/api/desktop/v1/project-members/<int:member_account_id>")
    def desktop_update_project_member(member_account_id):
        current = user()
        data = json_body()
        requested_role = _safe_text(data.get("role"), 20)
        if requested_role not in {"admin", "capturer", "viewer"}:
            raise ApiProblem("invalid_project_role", "成员角色无效")
        desktop_machine_id = require_desktop_client(
            current,
            data.get("desktop_machine_id") or data.get("machine_id"),
        )
        conn = db.connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            project = desktop_project_context(
                conn, current, data.get("project_id"), desktop_machine_id
            )
            target = conn.execute(
                "SELECT * FROM project_members WHERE project_owner_account_id = ? "
                "AND project_id = ? AND member_account_id = ? AND status = 'active'",
                (current["id"], project["project_id"], member_account_id),
            ).fetchone()
            if not target:
                raise ApiProblem("project_member_not_found", "工程成员不存在", 404)
            if target["role"] == "owner":
                raise ApiProblem(
                    "project_owner_protected", "负责人不能在当前版本中变更角色", 409
                )
            conn.execute(
                "UPDATE project_members SET role = ?, updated_at = ? WHERE id = ?",
                (requested_role, now(), target["id"]),
            )
            conn.commit()
            row = conn.execute(
                "SELECT pm.*, a.username, a.display_name FROM project_members pm "
                "JOIN accounts a ON a.id = pm.member_account_id WHERE pm.id = ?",
                (target["id"],),
            ).fetchone()
            return jsonify(
                {
                    "ok": True,
                    "project": _project_payload(project),
                    "member": member_payload(row, current["id"]),
                }
            )
        finally:
            conn.close()

    @blueprint.delete("/api/desktop/v1/project-members/<int:member_account_id>")
    def desktop_remove_project_member(member_account_id):
        current = user()
        data = json_body()
        desktop_machine_id = require_desktop_client(
            current,
            data.get("desktop_machine_id") or data.get("machine_id"),
        )
        conn = db.connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            project = desktop_project_context(
                conn, current, data.get("project_id"), desktop_machine_id
            )
            target = conn.execute(
                "SELECT * FROM project_members WHERE project_owner_account_id = ? "
                "AND project_id = ? AND member_account_id = ? AND status = 'active'",
                (current["id"], project["project_id"], member_account_id),
            ).fetchone()
            if not target:
                conn.rollback()
                return jsonify({"ok": True, "idempotent": True})
            if target["role"] == "owner":
                raise ApiProblem(
                    "project_owner_protected", "负责人不能退出或被移除", 409
                )
            timestamp = now()
            conn.execute(
                "UPDATE project_members SET status = 'removed', removed_at = ?, "
                "removed_by_account_id = ?, updated_at = ? WHERE id = ?",
                (timestamp, current["id"], timestamp, target["id"]),
            )
            conn.commit()
            return jsonify({"ok": True, "idempotent": False})
        finally:
            conn.close()

    @blueprint.get("/api/desktop/v1/inbox")
    def desktop_inbox():
        current = user()
        cursor, limit = _page_args()
        desktop_machine_id = _machine_id(
            request.args.get("desktop_machine_id") or request.args.get("machine_id")
        )
        desktop_machine_id = require_desktop_client(current, desktop_machine_id)
        conn = db.connect()
        try:
            desktop_machine_id = _require_active_machine(
                conn, current["id"], desktop_machine_id
            )
            machine_clause = "AND target_machine_id = ? "
            params = [current["id"], desktop_machine_id]
            params.extend((cursor, limit + 1))
            rows = conn.execute(
                "SELECT * FROM cloud_photos WHERE project_owner_account_id = ? "
                "AND source = 'mobile' "
                "AND status = 'desktop_pending' AND deleted_at = '' " + machine_clause +
                "AND id > ? ORDER BY id LIMIT ?",
                params,
            ).fetchall()
            page = rows[:limit]
            return jsonify(
                {
                    "ok": True,
                    "items": [desktop_photo_payload(conn, row) for row in page],
                    "next_cursor": str(page[-1]["id"]) if len(rows) > limit and page else "",
                    "desktop_machine_id": desktop_machine_id,
                    "original_max_bytes": config.MOBILE_MAX_ORIGINAL_BYTES,
                    "max_original_bytes": config.MOBILE_MAX_ORIGINAL_BYTES,
                }
            )
        finally:
            conn.close()

    @blueprint.post("/api/desktop/v1/photos/<photo_uuid>/delete")
    def desktop_delete_photo(photo_uuid):
        """接收桌面端明确的单照片删除事件，只写软删除标记。"""

        current = user()
        photo_uuid = _uuid(photo_uuid, "photo_uuid")
        data = json_body()
        desktop_machine_id = require_desktop_client(
            current,
            data.get("desktop_machine_id") or data.get("machine_id"),
        )
        local_project_code = _safe_text(data.get("local_project_code"), 160)
        local_photo_id = _safe_text(data.get("local_photo_id"), 160)

        conn = db.connect()
        try:
            desktop_machine_id = _require_active_machine(
                conn, current["id"], desktop_machine_id
            )
            conn.execute("BEGIN IMMEDIATE")
            photo = conn.execute(
                "SELECT * FROM cloud_photos WHERE project_owner_account_id = ? "
                "AND photo_uuid = ?",
                (current["id"], photo_uuid),
            ).fetchone()
            if not photo:
                # 负责人的共享工程内不存在即视为已删除；不跨 owner 查询。
                conn.commit()
                return jsonify(
                    {
                        "ok": True,
                        "idempotent": True,
                        "photo_uuid": photo_uuid,
                        "status": "deleted",
                    }
                )

            target_machine_id = _machine_id(photo["target_machine_id"])
            stored_project_code = _safe_text(photo["local_project_code"], 160)
            stored_photo_id = _safe_text(photo["local_photo_id"], 160)
            legacy_target = target_machine_id in {"", "DEFAULT"}
            if legacy_target:
                if (
                    not local_project_code
                    or not local_photo_id
                    or local_project_code != stored_project_code
                    or local_photo_id != stored_photo_id
                ):
                    raise ApiProblem(
                        "legacy_photo_identity_mismatch",
                        "旧照片必须同时匹配电脑端工程编号和照片编号",
                        403,
                    )
            elif target_machine_id != desktop_machine_id:
                raise ApiProblem(
                    "wrong_desktop_machine", "该照片属于另一台工程电脑", 403
                )

            deleted_by_machine_id = _machine_id(photo["deleted_by_machine_id"])
            if photo["deleted_at"]:
                if deleted_by_machine_id != desktop_machine_id:
                    raise ApiProblem(
                        "wrong_desktop_machine", "该照片已由另一台工程电脑删除", 403
                    )
                conn.commit()
                return jsonify(
                    {
                        "ok": True,
                        "idempotent": True,
                        "photo_uuid": photo_uuid,
                        "status": "deleted",
                        "deleted_at": photo["deleted_at"],
                        "deleted_by_machine_id": desktop_machine_id,
                    }
                )

            status = str(photo["status"] or "")
            if status == "desktop_pending":
                # 照片已经落到本机、但 ACK 尚未到达服务器时，桌面端必须携带
                # 两个本地永久标识。若服务器已有其中任一标识，还必须逐项一致。
                if not local_project_code or not local_photo_id:
                    raise ApiProblem(
                        "pending_photo_identity_required",
                        "待归档照片删除必须携带电脑端工程编号和照片编号",
                        409,
                    )
                if (
                    (stored_project_code and stored_project_code != local_project_code)
                    or (stored_photo_id and stored_photo_id != local_photo_id)
                ):
                    raise ApiProblem(
                        "pending_photo_identity_mismatch",
                        "电脑端工程编号或照片编号与服务器记录不一致",
                        409,
                    )
            elif status != "desktop_imported":
                raise ApiProblem(
                    "photo_not_deletable",
                    "照片尚未在该电脑落地，不能从手机影像库删除",
                    409,
                )

            timestamp = now()
            conn.execute(
                "UPDATE cloud_photos SET deleted_at = ?, deleted_by_machine_id = ?, "
                "deleted_by_account_id = ? WHERE id = ? "
                "AND project_owner_account_id = ? AND deleted_at = ''",
                (
                    timestamp,
                    desktop_machine_id,
                    current["id"],
                    photo["id"],
                    current["id"],
                ),
            )
            conn.commit()
            return jsonify(
                {
                    "ok": True,
                    "idempotent": False,
                    "photo_uuid": photo_uuid,
                    "status": "deleted",
                    "deleted_at": timestamp,
                    "deleted_by_machine_id": desktop_machine_id,
                }
            )
        finally:
            conn.close()

    @blueprint.post("/api/desktop/v1/photos/<photo_uuid>/ack")
    def desktop_ack(photo_uuid):
        current = user()
        photo_uuid = _uuid(photo_uuid, "photo_uuid")
        data = json_body()
        local_project_code = _safe_text(data.get("local_project_code"), 160)
        local_photo_id = _safe_text(data.get("local_photo_id"), 160)
        desktop_machine_id = _machine_id(
            data.get("desktop_machine_id") or data.get("machine_id")
        )
        desktop_machine_id = require_desktop_client(current, desktop_machine_id)
        if not local_project_code or not local_photo_id:
            raise ApiProblem("ack_fields_required", "缺少电脑端工程编号或照片编号")
        conn = db.connect()
        idempotent = False
        try:
            desktop_machine_id = _require_active_machine(
                conn, current["id"], desktop_machine_id
            )
            conn.execute("BEGIN IMMEDIATE")
            photo = conn.execute(
                "SELECT * FROM cloud_photos WHERE project_owner_account_id = ? "
                "AND photo_uuid = ?",
                (current["id"], photo_uuid),
            ).fetchone()
            if not photo:
                raise ApiProblem("photo_not_found", "照片不存在", 404)
            target_machine_id = _machine_id(photo["target_machine_id"])
            if target_machine_id not in {"", "DEFAULT"} and (
                not desktop_machine_id or desktop_machine_id != target_machine_id
            ):
                raise ApiProblem("wrong_desktop_machine", "该原图属于另一台工程电脑", 403)
            if photo["status"] == "desktop_imported":
                if (
                    photo["local_project_code"] == local_project_code
                    and photo["local_photo_id"] == local_photo_id
                ):
                    idempotent = True
                    conn.commit()
                else:
                    raise ApiProblem("ack_conflict", "照片已由另一条本地记录回执", 409)
            elif photo["status"] != "desktop_pending":
                raise ApiProblem("photo_not_pending", "照片尚未进入电脑待归档状态", 409)
            else:
                timestamp = now()
                conn.execute(
                    "UPDATE cloud_photos SET status = 'desktop_imported', local_project_code = ?, "
                    "local_photo_id = ?, desktop_imported_at = ?, updated_at = ? "
                    "WHERE id = ? AND project_owner_account_id = ?",
                    (
                        local_project_code, local_photo_id, timestamp, timestamp,
                        photo["id"], current["id"],
                    ),
                )
                if photo["batch_id"]:
                    remaining = conn.execute(
                        "SELECT COUNT(*) AS total FROM cloud_photos WHERE account_id = ? "
                        "AND batch_id = ? AND status != 'desktop_imported'",
                        (photo["account_id"], photo["batch_id"]),
                    ).fetchone()["total"]
                    if int(remaining) == 0:
                        conn.execute(
                            "UPDATE mobile_batches SET status = 'desktop_imported', updated_at = ? "
                            "WHERE account_id = ? AND id = ?",
                            (timestamp, photo["account_id"], photo["batch_id"]),
                        )
                conn.commit()
        finally:
            conn.close()

        original_key = photo["original_storage_key"]
        preview_key = photo["preview_storage_key"] or photo["storage_key"]
        cleanup_status = photo["original_cleanup_status"]
        cleanup_error = ""
        deleted_at = photo["original_deleted_at"]
        if not original_key:
            cleanup_status = "not_applicable"
        elif original_key == preview_key or cleanup_status == "legacy_shared":
            cleanup_status = "legacy_shared"
        elif cleanup_status != "deleted":
            try:
                storage.delete(original_key)
                cleanup_status = "deleted"
                deleted_at = now()
            except StorageError as exc:
                # 回执已在上一个短事务持久化；删除失败不得让电脑重复导入照片。
                cleanup_status = "cleanup_pending"
                cleanup_error = _safe_text(exc, 500)

        cleanup_conn = db.connect()
        try:
            cleanup_conn.execute("BEGIN IMMEDIATE")
            cleanup_conn.execute(
                "UPDATE cloud_photos SET original_cleanup_status = ?, "
                "original_cleanup_error = ?, original_deleted_at = ?, updated_at = ? "
                "WHERE id = ? AND project_owner_account_id = ? "
                "AND status = 'desktop_imported'",
                (
                    cleanup_status,
                    cleanup_error,
                    deleted_at,
                    now(),
                    photo["id"],
                    current["id"],
                ),
            )
            cleanup_conn.commit()
        finally:
            cleanup_conn.close()
        return jsonify(
            {
                "ok": True,
                "idempotent": idempotent,
                "photo_uuid": photo_uuid,
                "status": "desktop_imported",
                "cleanup_status": cleanup_status,
                "cleanup_pending": cleanup_status == "cleanup_pending",
            }
        )

    @blueprint.post("/api/desktop/v1/backfill-photo")
    def desktop_backfill_photo():
        current = user()
        project_id = _project_id(request.form.get("project_id"))
        desktop_machine_id = require_desktop_client(
            current,
            request.form.get("desktop_machine_id") or request.form.get("machine_id"),
        )
        machine_conn = db.connect()
        try:
            project_for_desktop(
                machine_conn, current, project_id, desktop_machine_id
            )
        finally:
            machine_conn.close()
        scope = _safe_text(request.form.get("scope"), 20)
        category = _safe_text(request.form.get("category"), 20)
        if scope not in SCOPES:
            raise ApiProblem("invalid_scope", "影像范围无效")
        if scope == "engineering" and category not in CATEGORIES:
            raise ApiProblem("invalid_category", "工程影像必须选择施工或监理")
        if scope == "other":
            category = ""
        assignment = {
            "unit_code": request.form.get("unit_code", ""),
            "process_name": request.form.get("process_name", ""),
        } if scope == "engineering" else {
            "other_node_code": request.form.get("other_node_code", "")
        }
        row, idempotent = insert_photo(
            current_user=current,
            photo_uuid=_uuid(request.form.get("photo_uuid"), "photo_uuid"),
            project_id=project_id,
            scope=scope,
            category=category,
            assignment=assignment,
            title=request.form.get("title", ""),
            photo_date=request.form.get("photo_date", ""),
            client_captured_at=request.form.get("client_captured_at", ""),
            orientation=request.form.get("orientation", 1),
            source="desktop",
            batch_id=None,
            file_storage=request.files.get("file"),
            claimed_sha=request.form.get("sha256", ""),
            claimed_size=(
                request.form.get("preview_size")
                or request.form.get("size_bytes")
                or ""
            ),
            target_machine_id=desktop_machine_id,
            original_filename=request.form.get("original_filename", ""),
            photographer=request.form.get("photographer", ""),
            uploaded_by=request.form.get("uploaded_by", ""),
            project_owner_account_id=current["id"],
            capture_source="desktop",
        )
        return jsonify(
            {
                "ok": True,
                "idempotent": idempotent,
                "photo": hydrated_photo_payload(row, current["id"]),
            }
        ), (200 if idempotent else 201)

    # 单进程重启后，历史 queued/running 任务不会永久卡在 analyzing。
    recover_stale_analysis_jobs(force=True)
    app.register_blueprint(blueprint)
