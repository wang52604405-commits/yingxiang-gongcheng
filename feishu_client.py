# -*- coding: utf-8 -*-
"""飞书多维表格客户端：照片台账自动同步（token 缓存 + 读写记录）"""
from __future__ import annotations

import json
import mimetypes
import os
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

FEISHU_CONFIG_NAME = "feishu_config.json"
FEISHU_DEFAULTS_NAME = "feishu_defaults.json"
BASE_URL = "https://open.feishu.cn/open-apis"

_token_cache = {"token": None, "exp": 0}


def _config_path() -> Path:
    data = os.environ.get("ALBUM_DATA_DIR", r"D:\工程影像资料")
    return Path(data).expanduser() / FEISHU_CONFIG_NAME


def _defaults_path() -> Path:
    if getattr(sys, "frozen", False):
        base = Path(sys.executable).resolve().parent
        p = base / "assets" / FEISHU_DEFAULTS_NAME
        if p.exists():
            return p
    p = Path(__file__).resolve().parent / "assets" / FEISHU_DEFAULTS_NAME
    return p if p.exists() else None


def load_config() -> dict:
    cfg = {}
    dp = _defaults_path()
    if dp and dp.exists():
        try:
            cfg = json.loads(dp.read_text(encoding="utf-8-sig"))
        except Exception:
            cfg = {}
    path = _config_path()
    if path.exists():
        try:
            cfg.update(json.loads(path.read_text(encoding="utf-8-sig")))
        except Exception:
            pass
    for key in ("app_id", "app_secret", "app_token", "table_id"):
        env_val = os.environ.get("FEISHU_" + key.upper(), "")
        if env_val:
            cfg[key] = env_val
    cfg.setdefault("enabled", False)
    if not cfg.get("enabled") and cfg.get("app_id") and cfg.get("app_secret") \
            and cfg.get("app_token") and cfg.get("table_id"):
        cfg["enabled"] = True
    if not cfg.get("share_url") and cfg.get("app_token"):
        cfg["share_url"] = "https://feishu.cn/base/" + cfg["app_token"]
    return cfg


def save_config(cfg: dict) -> None:
    path = _config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


def _request(method, path, data=None, token=None):
    body = json.dumps(data).encode("utf-8") if data is not None else None
    req = urllib.request.Request(BASE_URL + path, data=body, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read().decode("utf-8"))
        except Exception:
            return {"code": e.code, "msg": e.reason}
    except Exception as e:
        return {"code": -1, "msg": str(e)}


def _multipart_request(path, fields, file_path, token):
    """Upload one file to Feishu without adding a third-party HTTP dependency."""
    boundary = "----EngineeringAlbum" + uuid.uuid4().hex
    chunks = []
    for key, value in (fields or {}).items():
        chunks.extend([
            f"--{boundary}\r\n".encode("utf-8"),
            f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode("utf-8"),
            str(value).encode("utf-8"), b"\r\n",
        ])
    filename = Path(file_path).name
    mime_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    chunks.extend([
        f"--{boundary}\r\n".encode("utf-8"),
        (f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n').encode("utf-8"),
        f"Content-Type: {mime_type}\r\n\r\n".encode("utf-8"),
        Path(file_path).read_bytes(), b"\r\n",
        f"--{boundary}--\r\n".encode("utf-8"),
    ])
    req = urllib.request.Request(BASE_URL + path, data=b"".join(chunks), method="POST")
    req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    req.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read().decode("utf-8"))
        except Exception:
            return {"code": e.code, "msg": e.reason}
    except Exception as e:
        return {"code": -1, "msg": str(e)}


def get_token(cfg: dict):
    if _token_cache["token"] and time.time() < _token_cache["exp"]:
        return _token_cache["token"]
    r = _request("POST", "/auth/v3/tenant_access_token/internal", {
        "app_id": cfg.get("app_id", ""),
        "app_secret": cfg.get("app_secret", ""),
    })
    token = r.get("tenant_access_token")
    if token:
        _token_cache["token"] = token
        _token_cache["exp"] = time.time() + (int(r.get("expire") or 7200) - 300)
    return token


def is_configured(cfg: dict = None) -> bool:
    cfg = cfg or load_config()
    return bool(cfg.get("enabled") and cfg.get("app_id") and cfg.get("app_secret")
                and cfg.get("app_token") and cfg.get("table_id"))


_DATE_FIELDS = {"拍摄时间"}


def _feishu_field_value(key: str, value):
    """把字段值转成飞书多维表格 API 格式：文本 -> 字符串，日期 -> 毫秒。"""
    if value is None:
        return None
    # Attachment fields must retain Feishu's [{"file_token": ...}] structure.
    if isinstance(value, list) and value and isinstance(value[0], dict):
        return value
    if key in _DATE_FIELDS:
        return int(value) if str(value).isdigit() else None
    return str(value)


def add_record(fields: dict, cfg: dict = None) -> dict:
    """往台账表追加一条记录；失败返回 {"ok": False, "error": ...}"""
    cfg = cfg or load_config()
    if not is_configured(cfg):
        return {"ok": False, "error": "飞书未配置或未启用"}
    token = get_token(cfg)
    if not token:
        return {"ok": False, "error": "飞书 token 获取失败"}
    payload_fields = {}
    for key, value in (fields or {}).items():
        formatted = _feishu_field_value(key, value)
        if formatted is not None:
            payload_fields[key] = formatted
    r = _request("POST",
                 "/bitable/v1/apps/%s/tables/%s/records" % (cfg["app_token"], cfg["table_id"]),
                 {"fields": payload_fields}, token)
    if r.get("code") == 0:
        record = (r.get("data") or {}).get("record") or {}
        return {"ok": True, "record_id": str(record.get("record_id") or "")}
    return {"ok": False, "error": "%s: %s" % (r.get("code"), r.get("msg"))}


def update_record(record_id: str, fields: dict, cfg: dict = None) -> dict:
    cfg = cfg or load_config()
    if not is_configured(cfg):
        return {"ok": False, "error": "飞书未配置或未启用"}
    token = get_token(cfg)
    if not token:
        return {"ok": False, "error": "飞书 token 获取失败"}
    payload_fields = {}
    for key, value in (fields or {}).items():
        formatted = _feishu_field_value(key, value)
        if formatted is not None:
            payload_fields[key] = formatted
    r = _request("PUT", "/bitable/v1/apps/%s/tables/%s/records/%s" % (
        cfg["app_token"], cfg["table_id"], record_id), {"fields": payload_fields}, token)
    if r.get("code") == 0:
        return {"ok": True}
    return {"ok": False, "error": "%s: %s" % (r.get("code"), r.get("msg"))}


def get_table_fields(cfg: dict = None) -> dict:
    cfg = cfg or load_config()
    if not is_configured(cfg):
        return {"ok": False, "error": "飞书未配置或未启用"}
    token = get_token(cfg)
    if not token:
        return {"ok": False, "error": "飞书 token 获取失败"}
    r = _request("GET", "/bitable/v1/apps/%s/tables/%s/fields" % (
        cfg["app_token"], cfg["table_id"]), token=token)
    if r.get("code") == 0:
        return {"ok": True, "items": (r.get("data") or {}).get("items") or []}
    return {"ok": False, "error": "%s: %s" % (r.get("code"), r.get("msg"))}


def ensure_photo_attachment_field(cfg: dict = None) -> dict:
    """Return the attachment field used for local-photo previews, creating it once."""
    cfg = cfg or load_config()
    result = get_table_fields(cfg)
    if not result.get("ok"):
        return result
    for field in result.get("items") or []:
        if field.get("field_name") == "照片文件" and field.get("type") == 17:
            return {"ok": True, "field": field}
    token = get_token(cfg)
    r = _request("POST", "/bitable/v1/apps/%s/tables/%s/fields" % (
        cfg["app_token"], cfg["table_id"]), {"field_name": "照片文件", "type": 17}, token)
    if r.get("code") == 0:
        return {"ok": True, "field": (r.get("data") or {}).get("field") or {}}
    return {"ok": False, "error": "%s: %s" % (r.get("code"), r.get("msg"))}


def upload_photo_attachment(photo_path, cfg: dict = None) -> dict:
    cfg = cfg or load_config()
    path = Path(photo_path)
    if not path.exists():
        return {"ok": False, "error": "本地照片文件不存在"}
    token = get_token(cfg)
    if not token:
        return {"ok": False, "error": "飞书 token 获取失败"}
    r = _multipart_request("/drive/v1/medias/upload_all", {
        "file_name": path.name,
        "parent_type": "bitable_image",
        "parent_node": cfg["app_token"],
        "size": path.stat().st_size,
        "extra": json.dumps({"drive_route_token": cfg["app_token"]}, ensure_ascii=False),
    }, path, token)
    token_value = (r.get("data") or {}).get("file_token")
    if r.get("code") == 0 and token_value:
        return {"ok": True, "file_token": token_value}
    return {"ok": False, "error": "%s: %s" % (r.get("code"), r.get("msg"))}


def upsert_photo_record(fields: dict, photo_path, cfg: dict = None) -> dict:
    """Keep one Feishu row (including its attachment) in sync with one local photo."""
    cfg = cfg or load_config()
    rows_result = list_records(page_size=500, cfg=cfg)
    if not rows_result.get("ok"):
        return rows_result
    project_code = str((fields or {}).get("项目编码") or "").strip()
    photo_id = str((fields or {}).get("照片编号") or "").strip()
    record_id = next((str(row.get("record_id") or "") for row in rows_result.get("rows") or []
                      if str(row.get("项目编码") or "").strip() == project_code
                      and str(row.get("照片编号") or "").strip() == photo_id), "")
    had_record = bool(record_id)
    text_result = update_record(record_id, fields, cfg) if record_id else add_record(fields, cfg)
    if not text_result.get("ok"):
        return text_result
    # A record is useful even if an attachment upload is temporarily unavailable.
    if not record_id:
        record_id = str(text_result.get("record_id") or "")
    if not record_id:
        refreshed = list_records(page_size=500, cfg=cfg)
        record_id = next((str(row.get("record_id") or "") for row in refreshed.get("rows") or []
                          if str(row.get("项目编码") or "").strip() == project_code
                          and str(row.get("照片编号") or "").strip() == photo_id), "")
    attachment_field = ensure_photo_attachment_field(cfg)
    if not attachment_field.get("ok"):
        return {"ok": True, "attachment_ok": False, "attachment_error": attachment_field.get("error", "无法创建照片附件列")}
    uploaded = upload_photo_attachment(photo_path, cfg)
    if not uploaded.get("ok"):
        return {"ok": True, "attachment_ok": False, "attachment_error": uploaded.get("error", "照片上传失败")}
    attached = update_record(record_id, {"照片文件": [{"file_token": uploaded["file_token"]}]}, cfg)
    if not attached.get("ok"):
        return {"ok": True, "attachment_ok": False, "attachment_error": attached.get("error", "照片附件写入失败")}
    return {"ok": True, "attachment_ok": True, "updated": had_record}


def list_records(page_size=100, cfg: dict = None) -> dict:
    cfg = cfg or load_config()
    if not is_configured(cfg):
        return {"ok": False, "error": "飞书未配置或未启用"}
    token = get_token(cfg)
    if not token:
        return {"ok": False, "error": "飞书 token 获取失败"}
    r = _request("GET",
                 "/bitable/v1/apps/%s/tables/%s/records?page_size=%d" % (cfg["app_token"], cfg["table_id"], page_size),
                 token=token)
    if r.get("code") == 0:
        items = (r.get("data") or {}).get("items") or []
        rows = []
        for it in items:
            f = it.get("fields") or {}
            def _text(key):
                v = f.get(key)
                if isinstance(v, list):
                    if v and isinstance(v[0], dict):
                        return str(v[0].get("text") or "")
                    if v and isinstance(v[0], (int, float, str)):
                        return str(v[0])
                    return ""
                return str(v) if v is not None else ""
            rows.append({
                "record_id": it.get("record_id", ""),
                "项目编码": _text("项目编码"),
                "单位工程": _text("单位工程"),
                "分部工程": _text("分部工程"),
                "单元工程": _text("单元工程"),
                "照片编号": _text("照片编号"),
                "题名": _text("题名"),
                "拍摄者": _text("拍摄者"),
                "拍摄时间": _text("拍摄时间"),
                "照片说明": _text("照片说明"),
                "缩略图链接": _text("缩略图链接"),
            })
        return {"ok": True, "rows": rows, "total": len(rows)}
    return {"ok": False, "error": "%s: %s" % (r.get("code"), r.get("msg"))}
