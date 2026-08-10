# -*- coding: utf-8 -*-
"""飞书多维表格客户端：照片台账自动同步（token 缓存 + 读写记录）"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
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


def add_record(fields: dict, cfg: dict = None) -> dict:
    """往台账表追加一条记录；失败返回 {"ok": False, "error": ...}"""
    cfg = cfg or load_config()
    if not is_configured(cfg):
        return {"ok": False, "error": "飞书未配置或未启用"}
    token = get_token(cfg)
    if not token:
        return {"ok": False, "error": "飞书 token 获取失败"}
    r = _request("POST",
                 "/bitable/v1/apps/%s/tables/%s/records" % (cfg["app_token"], cfg["table_id"]),
                 {"fields": fields}, token)
    if r.get("code") == 0:
        return {"ok": True}
    return {"ok": False, "error": "%s: %s" % (r.get("code"), r.get("msg"))}


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
            rows.append({
                "record_id": it.get("record_id", ""),
                "项目编码": f.get("项目编码", [{}])[0].get("text") if isinstance(f.get("项目编码"), list) else f.get("项目编码", ""),
                "单元工程": f.get("单元工程", ""),
                "照片编号": f.get("照片编号", ""),
                "题名": f.get("题名", ""),
                "拍摄者": f.get("拍摄者", ""),
                "拍摄时间": f.get("拍摄时间", ""),
                "照片说明": f.get("照片说明", ""),
                "缩略图链接": f.get("缩略图链接", ""),
            })
        return {"ok": True, "rows": rows, "total": len(rows)}
    return {"ok": False, "error": "%s: %s" % (r.get("code"), r.get("msg"))}
