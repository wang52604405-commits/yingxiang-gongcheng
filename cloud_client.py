# -*- coding: utf-8 -*-
"""
客户端云账号模块：连接授权中心服务器，完成登录、本机激活与离线缓冲。

- 登录成功后自动上报本机机器 ID 并写入授权码（license.dat），
  之后走现有 Ed25519 本地验签逻辑；
- 服务器不可达时提供离线缓冲（默认 7 天）；
- 服务器明确拒绝（吊销/停用）时立即锁定。
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

CLOUD_CONFIG_NAME = "cloud_config.json"
CLOUD_ACCOUNT_NAME = "cloud_account.json"
PRODUCT_CONFIG_CACHE_NAME = "product_config_cache.json"
ERROR_QUEUE_NAME = "client_error_queue.json"
DEFAULT_SERVER_URL = "http://47.95.221.66"  # 内测服务器；域名启用后由云配置切换
OFFLINE_GRACE_SECONDS = 7 * 24 * 3600
APP_VERSION = "A20260809-2.39"  # 与桌面启动器版本一致，用于检查更新

DEFAULT_PRODUCT_CONFIG = {
    "config_version": 1,
    "pricing": {"monthly_price": 15, "lifetime_price": 169, "price_label": "内测会员价"},
    "free": {"photo_limit": 300, "watermark_enabled": False, "upload_expiry_enabled": False},
    "invite": {"enabled": True, "milestone": 10, "reward_days": 30},
    "cloud_preview": {
        "enabled": True,
        "requires_member": False,
        "beta_free_access": True,
        "thumb_max_side": 720,
        "thumb_quality": 76,
        "max_thumb_bytes": 99 * 1024,
        "max_thumbs_per_project": 240,
        "max_projects_per_sync": 200,
        "max_thumb_b64": 140000,
    },
    "logging": {"enabled": True, "max_message": 2000, "max_stack": 12000, "max_context": 8000},
}


def _get_json(url, timeout=15):
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            return json.loads(exc.read().decode("utf-8"))
        except Exception:
            return {"ok": False, "error": f"服务器错误（{exc.code}）"}
    except Exception as exc:
        return {"ok": False, "error": f"无法连接授权服务器：{exc}"}


def _data_dir() -> Path:
    default_dir = Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local")) / "工程影像管理平台" / "data"
    return Path(os.environ.get("ALBUM_DATA_DIR", str(default_dir))).expanduser()


def cloud_config_path() -> Path:
    return _data_dir() / CLOUD_CONFIG_NAME


def cloud_account_path() -> Path:
    return _data_dir() / CLOUD_ACCOUNT_NAME


def product_config_cache_path() -> Path:
    return _data_dir() / PRODUCT_CONFIG_CACHE_NAME


def error_queue_path() -> Path:
    return _data_dir() / ERROR_QUEUE_NAME


def server_url() -> str:
    cfg = _read_json(cloud_config_path()) or {}
    return str(
        cfg.get("server_url")
        or os.environ.get("ALBUM_CLOUD_URL")
        or DEFAULT_SERVER_URL
    ).rstrip("/")


def _read_json(path: Path):
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    return None


def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(path.name + ".tmp")
    temp_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp_path, path)


def _dpapi_protect(value: str) -> str:
    """使用当前 Windows 用户的 DPAPI 加密；密文无法在其他账号/电脑解开。"""
    if os.name != "nt" or not value:
        return ""
    try:
        import ctypes
        from ctypes import wintypes

        class DataBlob(ctypes.Structure):
            _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]

        raw = value.encode("utf-8")
        buffer = ctypes.create_string_buffer(raw)
        source = DataBlob(len(raw), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte)))
        target = DataBlob()
        if not ctypes.windll.crypt32.CryptProtectData(
            ctypes.byref(source), "工程影像云账号", None, None, None, 0x01, ctypes.byref(target)
        ):
            return ""
        try:
            encrypted = ctypes.string_at(target.pbData, target.cbData)
            import base64 as _base64
            return _base64.b64encode(encrypted).decode("ascii")
        finally:
            ctypes.windll.kernel32.LocalFree(target.pbData)
    except Exception:
        return ""


def _dpapi_unprotect(value: str) -> str:
    if os.name != "nt" or not value:
        return ""
    try:
        import base64 as _base64
        import ctypes
        from ctypes import wintypes

        class DataBlob(ctypes.Structure):
            _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]

        raw = _base64.b64decode(value)
        buffer = ctypes.create_string_buffer(raw)
        source = DataBlob(len(raw), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte)))
        target = DataBlob()
        if not ctypes.windll.crypt32.CryptUnprotectData(
            ctypes.byref(source), None, None, None, None, 0x01, ctypes.byref(target)
        ):
            return ""
        try:
            return ctypes.string_at(target.pbData, target.cbData).decode("utf-8")
        finally:
            ctypes.windll.kernel32.LocalFree(target.pbData)
    except Exception:
        return ""


def _write_cloud_account(account: dict) -> None:
    stored = dict(account or {})
    token = str(stored.pop("token", "") or "")
    protected = _dpapi_protect(token)
    if protected:
        stored["token_protected"] = protected
        stored["token_storage"] = "windows_dpapi"
    elif token:
        # 非 Windows 开发环境兜底；正式 Windows 客户端始终走 DPAPI。
        stored["token"] = token
        stored["token_storage"] = "portable_fallback"
    _write_json(cloud_account_path(), stored)


def _read_cloud_account() -> dict:
    stored = _read_json(cloud_account_path()) or {}
    if not isinstance(stored, dict):
        return {}
    account = dict(stored)
    protected = str(account.pop("token_protected", "") or "")
    if protected:
        account["token"] = _dpapi_unprotect(protected)
    # 自动把旧版明文令牌迁移到 DPAPI，不影响现有登录状态。
    if account.get("token") and os.name == "nt" and stored.get("token"):
        try:
            _write_cloud_account(account)
        except OSError:
            pass
    return account


def _deep_merge(base: dict, override: dict) -> dict:
    result = json.loads(json.dumps(base, ensure_ascii=False))
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def product_config(force: bool = False) -> dict:
    """取得服务器产品策略；一小时内用缓存，断网时长期回退最近成功配置。"""
    cached = _read_json(product_config_cache_path()) or {}
    cached_product = cached.get("product") if isinstance(cached.get("product"), dict) else {}
    fetched_at = int(cached.get("fetched_at") or 0)
    if not force and cached_product and time.time() - fetched_at < 3600:
        return _deep_merge(DEFAULT_PRODUCT_CONFIG, cached_product)
    result = _get_json(f"{server_url()}/api/product-config", timeout=5)
    if result.get("ok") and isinstance(result.get("product"), dict):
        merged = _deep_merge(DEFAULT_PRODUCT_CONFIG, result["product"])
        try:
            _write_json(product_config_cache_path(), {
                "fetched_at": int(time.time()),
                "server": server_url(),
                "product": merged,
            })
        except OSError:
            pass
        return merged
    fallback = _deep_merge(DEFAULT_PRODUCT_CONFIG, cached_product)
    try:
        _write_json(product_config_cache_path(), {
            "fetched_at": int(time.time()),
            "server": server_url(),
            "source": "offline_fallback",
            "product": fallback,
        })
    except OSError:
        pass
    return fallback


def _post_json(url: str, payload: dict, token: str = ""):
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            return json.loads(exc.read().decode("utf-8"))
        except Exception:
            return {"ok": False, "error": f"服务器错误（{exc.code}）"}
    except Exception as exc:
        return {"ok": False, "error": f"无法连接授权服务器：{exc}"}


_SENSITIVE_TERMS = (
    "password", "passwd", "pwd", "token", "secret", "authorization",
    "license_code", "private_key", "photo", "image", "thumb_b64", "content",
)


def _redact_text(value, limit: int) -> str:
    text = str(value or "")
    text = re.sub(r"(?i)Bearer\s+[A-Za-z0-9._~+/=-]+", "Bearer [REDACTED]", text)
    text = re.sub(
        r"(?i)(password|passwd|pwd|token|secret|license_code)\s*[:=]\s*[^\s,;]+",
        r"\1=[REDACTED]",
        text,
    )
    text = re.sub(r"data:image/[^;]+;base64,[A-Za-z0-9+/=]+", "[IMAGE_REMOVED]", text)
    return text[:limit]


def _sanitize(value, depth: int = 0):
    if depth > 4:
        return "[DEPTH_LIMIT]"
    if isinstance(value, dict):
        result = {}
        for key, item in list(value.items())[:50]:
            key_text = str(key)[:80]
            if any(term in key_text.lower() for term in _SENSITIVE_TERMS):
                result[key_text] = "[REDACTED]"
            else:
                result[key_text] = _sanitize(item, depth + 1)
        return result
    if isinstance(value, (list, tuple)):
        return [_sanitize(item, depth + 1) for item in list(value)[:30]]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return _redact_text(value, 1200)


def _error_payload(source: str, error, context=None, severity: str = "error", stack: str = "") -> dict:
    try:
        import licensing
        machine_id = licensing.machine_id()
    except Exception:
        machine_id = ""
    return {
        "source": _redact_text(source or "desktop", 80),
        "severity": severity if severity in {"info", "warning", "error", "critical"} else "error",
        "error_type": type(error).__name__ if isinstance(error, BaseException) else "ClientError",
        "message": _redact_text(error, 2000),
        "stack": _redact_text(stack, 12000),
        "context": _sanitize(context or {}),
        "app_version": APP_VERSION,
        "machine_id": machine_id,
        "client_time": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }


def _send_error_payload(payload: dict) -> bool:
    account = _read_cloud_account()
    base = str(account.get("server") or server_url()).rstrip("/")
    token = str(account.get("token") or "")
    result = _post_json(f"{base}/api/client-errors", payload, token)
    return bool(result.get("ok"))


def _read_error_queue() -> list:
    data = _read_json(error_queue_path()) or {}
    items = data.get("items") if isinstance(data, dict) else []
    return [item for item in items if isinstance(item, dict)][-200:]


def _write_error_queue(items: list) -> None:
    _write_json(error_queue_path(), {"items": list(items)[-200:]})


def flush_error_queue() -> int:
    items = _read_error_queue()
    if not items:
        return 0
    sent = 0
    remaining = []
    for index, item in enumerate(items):
        if _send_error_payload(item):
            sent += 1
        else:
            remaining = items[index:]
            break
    try:
        if remaining:
            _write_error_queue(remaining)
        elif error_queue_path().exists():
            error_queue_path().unlink()
    except OSError:
        pass
    return sent


def report_error(source: str, error, context=None, severity: str = "error", stack: str = "", background: bool = True):
    """脱敏上报错误；失败时最多保留 200 条本地队列，下次联网自动补报。"""
    payload = _error_payload(source, error, context, severity, stack)

    def worker():
        try:
            flush_error_queue()
            if _send_error_payload(payload):
                return
            queue = _read_error_queue()
            queue.append(payload)
            _write_error_queue(queue)
        except Exception:
            try:
                queue = _read_error_queue()
                queue.append(payload)
                _write_error_queue(queue)
            except Exception:
                pass

    if background:
        threading.Thread(target=worker, daemon=True).start()
        return {"ok": True, "queued": True}
    worker()
    return {"ok": True}


def login(username: str, password: str):
    """登录服务器并激活本机。成功则写入 license.dat 和本地账号记录。"""
    import licensing

    if not username or not password:
        return {"ok": False, "error": "请输入账号和密码"}
    base = server_url()
    result = _post_json(f"{base}/api/login", {"username": username, "password": password})
    if not result.get("ok"):
        return {"ok": False, "error": result.get("error", "登录失败")}
    token = result.get("token", "")
    machine_id = licensing.machine_id()
    activated = _post_json(
        f"{base}/api/activate", {"machine_id": machine_id}, token
    )
    if not activated.get("ok"):
        return {
            "ok": False,
            "error": activated.get("error", "本机激活失败，请联系管理员"),
        }
    code = activated.get("license_code", "")
    if code:
        licensing.write_installed_license(code)  # 会员才有授权码，本地验签并写入 license.dat
    # is_member：账号有有效权益即会员（无限使用）；否则免费版（300 张、无产品水印）。
    is_member = bool(activated.get("is_member")) or bool((activated.get("license") or {}).get("has_license"))
    account = {
        "username": username,
        "token": token,
        "server": base,
        "activated_at": int(time.time()),
        "is_member": is_member,
    }
    _write_cloud_account(account)
    threading.Thread(target=lambda: (product_config(force=True), flush_error_queue()), daemon=True).start()
    return {
        "ok": True,
        "account": username,
        "is_member": is_member,
        "license": activated.get("license"),
    }


def logout():
    if cloud_account_path().exists():
        try:
            cloud_account_path().unlink()
        except OSError:
            pass
    return {"ok": True}


def sync():
    """定时/启动时调用：续签授权；服务器明确拒绝则锁定；网络不可达走离线缓冲。"""
    import licensing

    account = _read_cloud_account()
    if not account:
        return {"ok": True, "logged_in": False}
    base = str(account.get("server") or server_url()).rstrip("/")
    token = str(account.get("token") or "")
    result = _post_json(
        f"{base}/api/activate", {"machine_id": licensing.machine_id()}, token
    )
    if result.get("ok"):
        code = result.get("license_code", "")
        if code:
            licensing.write_installed_license(code)
        account["activated_at"] = int(time.time())
        account["is_member"] = bool(result.get("is_member")) or bool((result.get("license") or {}).get("has_license"))
        _write_cloud_account(account)
        return {"ok": True, "synced": True}
    if "ok" in result:
        # 服务器明确拒绝：吊销/停用/到期
        return {
            "ok": False,
            "error": result.get("error", "授权已被服务器拒绝"),
            "offline_expired": True,
        }
    # 网络不可达：检查离线缓冲
    last = int(account.get("activated_at") or 0)
    elapsed = time.time() - last
    if elapsed > OFFLINE_GRACE_SECONDS:
        return {
            "ok": False,
            "error": "已连续 7 天无法连接授权服务器，请联网后重新激活",
            "offline_expired": True,
        }
    return {
        "ok": True,
        "synced": False,
        "offline_remaining": max(0, int(OFFLINE_GRACE_SECONDS - elapsed)),
        "error": result.get("error", ""),
    }


def status():
    """授权状态：本地 license 状态 + 云账号信息 + 离线缓冲。"""
    import licensing

    account = _read_cloud_account()
    synced = sync()
    license_status = licensing.license_status()
    mem = membership_status()
    return {
        "ok": True,
        "logged_in": bool(account),
        "account": account.get("username", ""),
        "server": account.get("server") or server_url(),
        "is_member": mem["is_member"],
        "member_tier": mem["member_tier"],
        "license": license_status,
        "cloud": synced,
    }


def membership_status():
    """当前会员状态：登录账号有有效权益即会员；否则为 300 张免费版。

    未登录或服务器未部署时按免费版处理（保守），登录后按账号等级。
    返回 {"is_member": bool, "member_tier": "free"|"member", "account": str}
    """
    account = _read_cloud_account()
    is_member = bool(account.get("is_member"))
    return {
        "is_member": is_member,
        "member_tier": "member" if is_member else "free",
        "account": account.get("username", ""),
        "logged_in": bool(account),
    }


def send_code(account: str):
    """发送注册验证码（基础版：服务器生成返回给客户端）。"""
    base = server_url()
    return _post_json(f"{base}/api/send-code", {"account": account})


def register(account: str, password: str, code: str, invite_code: str = "", email: str = ""):
    """注册账号（用手机/QQ/邮箱），可填邀请码与邮箱。"""
    base = server_url()
    payload = {"username": account, "password": password, "code": code}
    if email:
        payload["email"] = email.strip()
    if invite_code:
        payload["invite_code"] = invite_code.strip().upper()
    return _post_json(f"{base}/api/register", payload)


def forgot_password(account: str):
    """找回密码：向账号绑定邮箱发送验证码。"""
    base = server_url()
    return _post_json(f"{base}/api/forgot-password", {"account": account})


def reset_password(account: str, code: str, new_password: str):
    """用验证码重置密码。"""
    base = server_url()
    return _post_json(
        f"{base}/api/reset-password",
        {"account": account, "code": code, "new_password": new_password},
    )


def invite_status(token: str = ""):
    """查询我的邀请码、已邀请人数、已奖励月数。"""
    base = server_url()
    account = _read_cloud_account()
    token = token or str(account.get("token") or "")
    req = urllib.request.Request(f"{base}/api/invite-status", method="GET")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            return json.loads(exc.read().decode("utf-8"))
        except Exception:
            return {"ok": False, "error": f"服务器错误（{exc.code}）"}
    except Exception as exc:
        return {"ok": False, "error": f"无法连接授权服务器：{exc}"}


def check_update(current: str = ""):
    """检查更新：比较本地版本与服务器最新版本。"""
    base = server_url()
    cur = current or APP_VERSION
    return _get_json(f"{base}/api/check-update?current={urllib.parse.quote(cur)}")


# 云预览同步：单次最多同步的照片数/缩略图大小限制
CLOUD_SYNC_MAX_PROJECTS = 200
CLOUD_SYNC_MAX_THUMBS_PER_PROJECT = 240
CLOUD_THUMB_MAX_B64 = 140_000
CLOUD_THUMB_MAX_BYTES = 99 * 1024


def cloud_preview_limits() -> dict:
    cloud = product_config().get("cloud_preview", {})
    return {
        "enabled": bool(cloud.get("enabled", True)),
        "thumb_max_side": max(320, int(cloud.get("thumb_max_side") or 720)),
        "thumb_quality": max(40, int(cloud.get("thumb_quality") or 76)),
        "max_thumb_bytes": max(40_000, min(99 * 1024, int(cloud.get("max_thumb_bytes") or CLOUD_THUMB_MAX_BYTES))),
        "max_projects": max(1, int(cloud.get("max_projects_per_sync") or CLOUD_SYNC_MAX_PROJECTS)),
        "max_thumbs_per_project": max(1, int(cloud.get("max_thumbs_per_project") or CLOUD_SYNC_MAX_THUMBS_PER_PROJECT)),
        "max_thumb_b64": max(60_000, min(140_000, int(cloud.get("max_thumb_b64") or CLOUD_THUMB_MAX_B64))),
    }


def sync_projects(projects: list) -> dict:
    """把本机项目缩略图+编号同步到服务器云预览（按登录账号隔离）。

    projects: [{project_code, project_name, unit_name, part_name,
                thumbs: [{photo_name, thumb_b64}]}]
    未登录云账号时静默跳过（返回 ok=False, logged_in=False）。
    """
    account = _read_cloud_account()
    if not account:
        return {"ok": False, "logged_in": False, "error": "未登录云账号"}
    base = str(account.get("server") or server_url()).rstrip("/")
    token = str(account.get("token") or "")
    limits = cloud_preview_limits()
    if not limits["enabled"]:
        return {"ok": False, "error": "云预览当前已由管理员暂停"}
    prepared = []
    for project in projects[:limits["max_projects"]]:
        item = dict(project)
        thumbs = item.get("thumbs") if isinstance(item.get("thumbs"), list) else []
        item["thumbs"] = thumbs[:limits["max_thumbs_per_project"]]
        prepared.append(item)
    payload = {"projects": prepared}
    return _post_json(f"{base}/api/cloud/sync", payload, token)


def fetch_preview_projects() -> dict:
    """拉取当前账号的云预览项目列表（公网登录后查看用）。"""
    account = _read_cloud_account()
    if not account:
        return {"ok": False, "logged_in": False, "error": "未登录云账号"}
    base = str(account.get("server") or server_url()).rstrip("/")
    token = str(account.get("token") or "")
    return _get_json_auth(f"{base}/api/cloud/projects", token)


def _get_json_auth(url: str, token: str = ""):
    req = urllib.request.Request(url, method="GET")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            return json.loads(exc.read().decode("utf-8"))
        except Exception:
            return {"ok": False, "error": f"服务器错误（{exc.code}）"}
    except Exception as exc:
        return {"ok": False, "error": f"无法连接授权服务器：{exc}"}
