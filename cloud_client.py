# -*- coding: utf-8 -*-
"""
客户端云账号模块：连接授权中心服务器，完成登录、本机激活与离线缓冲。

- 登录成功后自动上报本机机器 ID 并写入授权码（license.dat），
  之后走现有 Ed25519 本地验签逻辑；
- 服务器不可达时提供离线缓冲（默认 7 天）；
- 服务器明确拒绝（吊销/停用）时立即锁定。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import tls_compat

CLOUD_CONFIG_NAME = "cloud_config.json"
CLOUD_ACCOUNT_NAME = "cloud_account.json"
PRODUCT_CONFIG_CACHE_NAME = "product_config_cache.json"
ERROR_QUEUE_NAME = "client_error_queue.json"
DEFAULT_SERVER_URL = "https://api.shuiliyingxiang.cn"  # 已备案的正式 HTTPS 域名
LEGACY_SERVER_HOSTS = {"47.95.221.66"}
LOCAL_SERVER_HOSTS = {"127.0.0.1", "localhost", "::1"}
OFFLINE_GRACE_SECONDS = 7 * 24 * 3600
APP_VERSION = "A20260901-2.84"  # 与桌面启动器版本一致，用于检查更新

DEFAULT_PRODUCT_CONFIG = {
    "config_version": 1,
    "pricing": {"monthly_price": 39, "lifetime_price": 399, "price_label": "原价"},
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


def _allow_insecure_localhost() -> bool:
    return str(os.environ.get("ALBUM_ALLOW_INSECURE_LOCALHOST") or "").strip().lower() in {
        "1",
        "true",
        "yes",
    }


def _validate_outbound_url(value: str, *, base_only: bool = False) -> str:
    raw = str(value or "").strip()
    parts = urllib.parse.urlsplit(raw)
    if not parts.hostname or parts.username or parts.password:
        raise ValueError("云服务器地址无效")
    hostname = parts.hostname.lower().rstrip(".")
    if parts.scheme == "http":
        if hostname not in {"127.0.0.1", "localhost", "::1"} or not _allow_insecure_localhost():
            raise ValueError("远程云服务器必须使用 HTTPS；HTTP 只允许显式启用的本机开发环境")
    elif parts.scheme != "https":
        raise ValueError("云服务器地址必须使用 HTTPS")
    if base_only and (parts.query or parts.fragment or parts.path not in {"", "/"}):
        raise ValueError("云服务器基础地址不能包含路径、参数或片段")
    return raw.rstrip("/") if base_only else raw


def _normalize_server_base(value: str) -> str:
    """迁移旧公网地址，同时保留显式允许的本机联调地址。"""
    raw = str(value or "").strip().rstrip("/")
    parts = urllib.parse.urlsplit(raw)
    hostname = str(parts.hostname or "").lower().rstrip(".")
    if hostname in LEGACY_SERVER_HOSTS:
        return DEFAULT_SERVER_URL
    if parts.scheme == "http" and hostname in LOCAL_SERVER_HOSTS and _allow_insecure_localhost():
        return raw
    if parts.scheme == "https" and hostname and not parts.username and not parts.password:
        return raw
    return DEFAULT_SERVER_URL


class _NoCredentialRedirect(urllib.request.HTTPRedirectHandler):
    """所有携带账号信息的请求均拒绝自动重定向。"""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # pragma: no cover
        return None


def _open_no_redirect(request, timeout=15):
    return tls_compat.build_secure_opener(_NoCredentialRedirect()).open(
        request, timeout=timeout
    )


def _get_json(url, timeout=15):
    try:
        url = _validate_outbound_url(url)
    except ValueError as exc:
        return {"ok": False, "error": str(exc), "code": "insecure_server_url"}
    req = urllib.request.Request(url, method="GET")
    try:
        with _open_no_redirect(req, timeout=timeout) as resp:
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
    configured = str(
        cfg.get("server_url")
        or os.environ.get("ALBUM_CLOUD_URL")
        or DEFAULT_SERVER_URL
    ).rstrip("/")
    normalized = _normalize_server_base(configured)
    # 旧版保存过 HTTP/HTTPS 公网 IP；统一迁移到备案域名，不触碰业务数据。
    if normalized != configured:
        if cfg.get("server_url"):
            repaired = dict(cfg)
            repaired["server_url"] = normalized
            try:
                _write_json(cloud_config_path(), repaired)
            except OSError:
                pass
    return normalized


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
    desktop_sync_token = str(stored.pop("desktop_sync_token", "") or "")
    stored.pop("token_protected", None)
    stored.pop("desktop_sync_token_protected", None)
    protected = _dpapi_protect(token)
    if protected:
        stored["token_protected"] = protected
        stored["token_storage"] = "windows_dpapi"
    elif token:
        # 非 Windows 开发环境兜底；正式 Windows 客户端始终走 DPAPI。
        stored["token"] = token
        stored["token_storage"] = "portable_fallback"
    sync_protected = _dpapi_protect(desktop_sync_token)
    if sync_protected:
        stored["desktop_sync_token_protected"] = sync_protected
        stored["desktop_sync_token_storage"] = "windows_dpapi"
    else:
        # desktop_sync_token 具有本机桌面同步权限，绝不以明文回退。
        # DPAPI 暂不可用时下次可用普通账号令牌重新 /api/activate 获取。
        stored.pop("desktop_sync_token_storage", None)
    _write_json(cloud_account_path(), stored)


def _read_cloud_account() -> dict:
    stored = _read_json(cloud_account_path()) or {}
    if not isinstance(stored, dict):
        return {}
    # 全新安装没有账号文件时必须保持“未登录”。此前会继续补入 server 字段，
    # 使空账号字典变为 truthy，最终把未注册用户误判为已登录。
    if not stored:
        return {}
    account = dict(stored)
    protected = str(account.pop("token_protected", "") or "")
    sync_protected = str(account.pop("desktop_sync_token_protected", "") or "")
    legacy_sync_token = str(account.pop("desktop_sync_token", "") or "")
    if protected:
        account["token"] = _dpapi_unprotect(protected)
    if sync_protected:
        account["desktop_sync_token"] = _dpapi_unprotect(sync_protected)
    elif legacy_sync_token:
        account["desktop_sync_token"] = legacy_sync_token
    stored_server = str(stored.get("server") or "").strip().rstrip("/")
    normalized_server = _normalize_server_base(stored_server or server_url())
    account["server"] = normalized_server
    if stored_server and normalized_server != stored_server:
        # 直接改写原始持久化字典，避免 DPAPI 临时解密失败时丢失密文令牌。
        repaired = dict(stored)
        repaired["server"] = normalized_server
        try:
            _write_json(cloud_account_path(), repaired)
        except OSError:
            pass
    # 自动把旧版明文令牌迁移到 DPAPI，不影响现有登录状态。
    if account.get("token") and os.name == "nt" and stored.get("token"):
        try:
            _write_cloud_account(account)
        except OSError:
            pass
    elif account.get("desktop_sync_token") and os.name == "nt" and stored.get("desktop_sync_token"):
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
    try:
        url = _validate_outbound_url(url)
    except ValueError as exc:
        return {"ok": False, "error": str(exc), "code": "insecure_server_url"}
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with _open_no_redirect(req, timeout=15) as resp:
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
    server_account = result.get("account") if isinstance(result.get("account"), dict) else {}
    account_id = str(server_account.get("id") or "").strip()
    if not account_id:
        return {
            "ok": False,
            "error": "服务器未返回稳定账号编号，已拒绝建立可能串号的同步会话",
        }
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
        "account_id": account_id,
        "username": str(server_account.get("username") or username),
        "token": token,
        "desktop_sync_token": str(activated.get("desktop_sync_token") or ""),
        "server": base,
        "activated_at": int(time.time()),
        "is_member": is_member,
        "auth_generation": secrets.token_hex(16),
    }
    _write_cloud_account(account)
    threading.Thread(target=lambda: (product_config(force=True), flush_error_queue()), daemon=True).start()
    return {
        "ok": True,
        "account": str(server_account.get("username") or username),
        "account_id": account_id,
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
        refreshed_sync_token = str(result.get("desktop_sync_token") or "")
        if refreshed_sync_token:
            account["desktop_sync_token"] = refreshed_sync_token
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
        "account_id": str(account.get("account_id") or ""),
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
        with _open_no_redirect(req, timeout=15) as resp:
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
    try:
        url = _validate_outbound_url(url)
    except ValueError as exc:
        return {"ok": False, "error": str(exc), "code": "insecure_server_url"}
    req = urllib.request.Request(url, method="GET")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with _open_no_redirect(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            return json.loads(exc.read().decode("utf-8"))
        except Exception:
            return {"ok": False, "error": f"服务器错误（{exc.code}）"}
    except Exception as exc:
        return {"ok": False, "error": f"无法连接授权服务器：{exc}"}


# ---------------------------------------------------------------------------
# 移动端 / 桌面端影像同步 API v1

_DESKTOP_SYNC_TOKEN_REFRESH_LOCK = threading.Lock()
_LEGACY_ACCOUNT_IDENTITY_LOCK = threading.Lock()


def _repair_legacy_account_identity(account: dict) -> dict:
    """用现有普通账号令牌从 /api/me 无感补齐旧版缺失的 account_id。"""
    current = dict(account or {})
    if str(current.get("account_id") or "").strip():
        return current
    token = str(current.get("token") or "")
    if not token:
        return current
    with _LEGACY_ACCOUNT_IDENTITY_LOCK:
        # 其它同步线程可能已经完成修复，优先使用磁盘上的新值。
        latest = _read_cloud_account()
        if str(latest.get("account_id") or "").strip():
            return latest
        token = str(latest.get("token") or token)
        try:
            base = _validate_outbound_url(
                str(latest.get("server") or current.get("server") or server_url()),
                base_only=True,
            )
        except ValueError:
            return latest or current
        result = _get_json_auth(f"{base}/api/me", token)
        server_account = result.get("account") if isinstance(result, dict) else None
        if not isinstance(server_account, dict):
            return latest or current
        account_id = str(server_account.get("id") or "").strip()
        if not account_id:
            return latest or current
        repaired = dict(latest or current)
        repaired["account_id"] = account_id
        repaired["username"] = str(
            server_account.get("username") or repaired.get("username") or ""
        ).strip()
        repaired["server"] = base
        repaired.setdefault("auth_generation", secrets.token_hex(16))
        _write_cloud_account(repaired)
        return repaired


def _refresh_desktop_sync_token() -> str:
    """用普通账号令牌续激活，取得绑定当前机器的桌面同步令牌。"""
    if not _DESKTOP_SYNC_TOKEN_REFRESH_LOCK.acquire(blocking=False):
        return ""
    try:
        current = _read_cloud_account()
        existing = str(current.get("desktop_sync_token") or "")
        if existing:
            return existing
        # sync() 只把普通账号令牌发给既有 /api/activate，不会把它混入
        # desktop/v1；成功响应会经 DPAPI 保存 desktop_sync_token。
        sync()
        refreshed = _read_cloud_account()
        return str(refreshed.get("desktop_sync_token") or "")
    finally:
        _DESKTOP_SYNC_TOKEN_REFRESH_LOCK.release()

def _cloud_auth_context():
    """返回桌面同步的服务器地址与令牌。

    优先使用由 /api/activate 下发、绑定当前机器且限制 desktop_sync
    scope 的 DPAPI 密文令牌；普通账号令牌只允许调用 /api/activate
    刷新专用令牌，绝不回退用于 desktop/v1。
    同步状态和日志都不保存任何令牌。
    """
    account = _read_cloud_account()
    if not account:
        return None, None, {"ok": False, "logged_in": False, "error": "未登录云账号"}
    account = _repair_legacy_account_identity(account)
    account_id = str(account.get("account_id") or "").strip()
    if not account_id:
        return None, None, {
            "ok": False,
            "logged_in": True,
            "code": "account_identity_pending",
            "error": "正在联网确认账号编号，请保持联网后重试",
            "retryable": True,
        }
    try:
        base = _validate_outbound_url(
            str(account.get("server") or server_url()), base_only=True
        )
    except ValueError as exc:
        return None, None, {
            "ok": False,
            "logged_in": True,
            "code": "insecure_server_url",
            "error": str(exc),
            "retryable": False,
        }
    account_token = str(account.get("token") or "")
    sync_token = str(account.get("desktop_sync_token") or "")
    if not sync_token and account_token:
        sync_token = _refresh_desktop_sync_token()
    if not sync_token:
        return None, None, {
            "ok": False,
            "logged_in": True,
            "code": "desktop_sync_token_required",
            "error": "本机桌面同步凭证尚未刷新，请联网后重试激活",
            "retryable": True,
        }
    # 普通账号/微信令牌绝不进入 desktop/v1 或相对原图下载请求。
    return base, sync_token, None


def desktop_sync_identity() -> str:
    """返回不含令牌的同步账号标识，用于隔离本地游标。"""
    account = _read_cloud_account()
    if not account:
        return ""
    account = _repair_legacy_account_identity(account)
    account_id = str(account.get("account_id") or "").strip()
    if not account_id:
        return ""
    identity = "|".join([
        str(account.get("server") or server_url()).rstrip("/"),
        account_id,
    ])
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]


def desktop_sync_identity_for_account(account_id: str) -> str:
    """为已归属工程计算稳定账号分区；不读取或返回任何登录令牌。"""
    account_id = str(account_id or "").strip()
    if not account_id:
        return ""
    account = _read_cloud_account()
    if str(account.get("account_id") or "").strip() == account_id:
        base = str(account.get("server") or server_url()).rstrip("/")
    else:
        base = str(server_url()).rstrip("/")
    try:
        base = _normalize_server_base(base)
    except ValueError:
        return ""
    identity = "|".join([base, account_id])
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]


def desktop_sync_account_id() -> str:
    """返回服务器不可变 account.id；旧账号文件联网后会自动补齐。"""
    account = _read_cloud_account()
    if account:
        account = _repair_legacy_account_identity(account)
    return str(account.get("account_id") or "").strip()


def desktop_sync_account_username() -> str:
    """返回服务器确认过的账号名，仅用于向用户显示当前绑定归属。"""
    account = _read_cloud_account()
    return str(account.get("username") or "").strip()


def desktop_sync_generation() -> str:
    account = _read_cloud_account()
    return str(account.get("auth_generation") or "").strip()


def _cloud_api_json(path: str, method: str = "GET", payload=None, query=None, timeout: int = 20):
    base, token, error = _cloud_auth_context()
    if error:
        return error
    query_text = urllib.parse.urlencode(query or {}, doseq=True)
    url = f"{base}{path}"
    if query_text:
        url += ("&" if "?" in url else "?") + query_text
    body = None
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=body, headers=headers, method=method.upper())
    try:
        with _open_no_redirect(req, timeout=timeout) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            if isinstance(result, dict):
                result.setdefault("http_status", int(getattr(resp, "status", 200) or 200))
                return result
            return {"ok": False, "error": "服务器返回数据格式不正确"}
    except urllib.error.HTTPError as exc:
        try:
            result = json.loads(exc.read().decode("utf-8"))
        except Exception:
            result = {"ok": False, "error": f"服务器错误（{exc.code}）"}
        if not isinstance(result, dict):
            result = {"ok": False, "error": f"服务器错误（{exc.code}）"}
        result.setdefault("ok", False)
        result.setdefault("http_status", exc.code)
        result.setdefault("retryable", exc.code >= 500 or exc.code == 429)
        return result
    except Exception as exc:
        return {
            "ok": False,
            "error": f"无法连接影像同步服务器：{exc}",
            "network_error": True,
            "retryable": True,
        }


def desktop_project_snapshot(snapshot: dict) -> dict:
    """事务式上传当前工程的完整层级快照。"""
    return _cloud_api_json(
        "/api/desktop/v1/project-snapshot",
        method="POST",
        payload=snapshot,
        timeout=30,
    )


def desktop_project_members(project_id: str, desktop_machine_id: str) -> dict:
    """读取当前归档工程的成员；服务器仍以 owner + 归档机做最终鉴权。"""
    return _cloud_api_json(
        "/api/desktop/v1/project-members",
        query={
            "project_id": str(project_id or "").strip(),
            "desktop_machine_id": str(desktop_machine_id or "").strip(),
        },
    )


def desktop_project_invites(project_id: str, desktop_machine_id: str) -> dict:
    """读取邀请状态；已生成的邀请码明文不会由列表接口再次返回。"""
    return _cloud_api_json(
        "/api/desktop/v1/project-invites",
        query={
            "project_id": str(project_id or "").strip(),
            "desktop_machine_id": str(desktop_machine_id or "").strip(),
        },
    )


def desktop_create_project_invite(
    project_id: str,
    role: str,
    desktop_machine_id: str,
) -> dict:
    return _cloud_api_json(
        "/api/desktop/v1/project-invites",
        method="POST",
        payload={
            "project_id": str(project_id or "").strip(),
            "role": str(role or "capturer").strip(),
            "desktop_machine_id": str(desktop_machine_id or "").strip(),
        },
    )


def desktop_revoke_project_invite(
    invite_id,
    project_id: str,
    desktop_machine_id: str,
) -> dict:
    quoted = urllib.parse.quote(str(invite_id or ""), safe="")
    return _cloud_api_json(
        f"/api/desktop/v1/project-invites/{quoted}",
        method="DELETE",
        payload={
            "project_id": str(project_id or "").strip(),
            "desktop_machine_id": str(desktop_machine_id or "").strip(),
        },
    )


def desktop_update_project_member(
    member_account_id,
    project_id: str,
    role: str,
    desktop_machine_id: str,
) -> dict:
    quoted = urllib.parse.quote(str(member_account_id or ""), safe="")
    return _cloud_api_json(
        f"/api/desktop/v1/project-members/{quoted}",
        method="PATCH",
        payload={
            "project_id": str(project_id or "").strip(),
            "role": str(role or "").strip(),
            "desktop_machine_id": str(desktop_machine_id or "").strip(),
        },
    )


def desktop_remove_project_member(
    member_account_id,
    project_id: str,
    desktop_machine_id: str,
) -> dict:
    quoted = urllib.parse.quote(str(member_account_id or ""), safe="")
    return _cloud_api_json(
        f"/api/desktop/v1/project-members/{quoted}",
        method="DELETE",
        payload={
            "project_id": str(project_id or "").strip(),
            "desktop_machine_id": str(desktop_machine_id or "").strip(),
        },
    )


def desktop_wechat_binding(desktop_machine_id: str) -> dict:
    return _cloud_api_json(
        "/api/desktop/v1/wechat-binding",
        query={"desktop_machine_id": str(desktop_machine_id or "")},
    )


def desktop_unbind_wechat(password: str, desktop_machine_id: str) -> dict:
    return _cloud_api_json(
        "/api/desktop/v1/wechat-binding",
        method="DELETE",
        payload={
            "password": str(password or ""),
            "desktop_machine_id": str(desktop_machine_id or ""),
        },
    )


def desktop_inbox(cursor: str = "", limit: int = 50, desktop_machine_id: str = "") -> dict:
    """拉取尚未导入本机的手机影像。"""
    return _cloud_api_json(
        "/api/desktop/v1/inbox",
        query={
            "cursor": str(cursor or ""),
            "limit": max(1, min(100, int(limit or 50))),
            "desktop_machine_id": str(desktop_machine_id or ""),
        },
        timeout=30,
    )


def desktop_ack_photo(
    photo_uuid: str,
    local_project_code: str,
    local_photo_id: str,
    desktop_machine_id: str = "",
) -> dict:
    """回执本机已完成归档；服务器端以 photo_uuid 幂等处理。"""
    quoted = urllib.parse.quote(str(photo_uuid or ""), safe="")
    return _cloud_api_json(
        f"/api/desktop/v1/photos/{quoted}/ack",
        method="POST",
        payload={
            "local_project_code": str(local_project_code or ""),
            "local_photo_id": str(local_photo_id or ""),
            "desktop_machine_id": str(desktop_machine_id or ""),
        },
    )


def desktop_delete_photo(
    photo_uuid: str,
    local_project_code: str,
    local_photo_id: str,
    desktop_machine_id: str = "",
) -> dict:
    """发送一条明确的本机照片删除事件；服务器仅做可恢复软删除。"""
    quoted = urllib.parse.quote(str(photo_uuid or ""), safe="")
    return _cloud_api_json(
        f"/api/desktop/v1/photos/{quoted}/delete",
        method="POST",
        payload={
            "local_project_code": str(local_project_code or ""),
            "local_photo_id": str(local_photo_id or ""),
            "desktop_machine_id": str(desktop_machine_id or ""),
        },
    )


def _mobile_download_host_allowlist(base_host: str = "") -> set:
    """签名下载地址只允许当前 API 主机、阿里云 OSS 或显式白名单。"""
    configured = _read_json(cloud_config_path()) or {}
    values = configured.get("mobile_download_hosts") or []
    if isinstance(values, str):
        values = values.split(",")
    env_values = str(os.environ.get("ALBUM_MOBILE_DOWNLOAD_HOSTS") or "").split(",")
    hosts = {
        str(value or "").strip().lower().rstrip(".")
        for value in list(values if isinstance(values, list) else []) + env_values
        if str(value or "").strip()
    }
    if base_host:
        hosts.add(str(base_host).strip().lower().rstrip("."))
    return hosts


def _safe_mobile_download_request(raw_url: str, base: str, token: str):
    """构造不会向第三方泄露 Bearer 的下载请求。"""
    raw_url = str(raw_url or "").strip()
    if not raw_url:
        raise ValueError("影像下载地址为空")
    base = _validate_outbound_url(str(base or ""), base_only=True)
    base_parts = urllib.parse.urlsplit(str(base).rstrip("/") + "/")
    if base_parts.scheme not in {"http", "https"} or not base_parts.hostname:
        raise ValueError("影像同步服务器地址无效")
    parts = urllib.parse.urlsplit(raw_url)
    headers = {}
    if not parts.scheme and not parts.netloc:
        # 相对路径必须结果与 API 完全同源，只有这种请求才携带账号令牌。
        url = urllib.parse.urljoin(str(base).rstrip("/") + "/", raw_url)
        target = urllib.parse.urlsplit(url)
        base_port = base_parts.port or (443 if base_parts.scheme == "https" else 80)
        target_port = target.port or (443 if target.scheme == "https" else 80)
        if (
            target.scheme != base_parts.scheme
            or (target.hostname or "").lower() != (base_parts.hostname or "").lower()
            or target_port != base_port
        ):
            raise ValueError("相对影像地址超出当前服务器同源范围")
        headers["Authorization"] = f"Bearer {token}"
        return urllib.request.Request(url, method="GET", headers=headers)

    # ``//host/path`` 会绕过普通相对路径判断，明确拒绝。
    if parts.scheme != "https" or not parts.hostname:
        raise ValueError("签名影像地址必须使用 HTTPS")
    hostname = parts.hostname.lower().rstrip(".")
    allowlist = _mobile_download_host_allowlist(base_parts.hostname or "")
    is_aliyun_oss = hostname == "aliyuncs.com" or hostname.endswith(".aliyuncs.com")
    if hostname not in allowlist and not is_aliyun_oss:
        raise ValueError("签名影像地址不在受信任主机白名单")
    # 签名 URL 自带短时效凭证，绝不附加桌面账号 Bearer。
    return urllib.request.Request(raw_url, method="GET")


class _NoDownloadRedirect(urllib.request.HTTPRedirectHandler):
    """下载不自动跟随重定向，避免令牌或签名参数跨主机泄露。"""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # pragma: no cover - urllib callback
        return None


def _desktop_download_bytes_with_context(
    download_url: str,
    base: str,
    token: str,
    max_bytes: int = 50 * 1024 * 1024,
    timeout: int = 30,
) -> dict:
    """使用显式同步上下文安全下载原图。

    只有解析后与 ``base`` 完全同源的相对地址才携带 Bearer；
    绝对 HTTPS 签名地址不携带 Bearer，且所有重定向均拒绝。该入口
    也供隔离 staging E2E 复用，避免测试适配器重新实现一套
    可能泄漏令牌的下载逻辑。
    """
    try:
        req = _safe_mobile_download_request(download_url, base, token)
    except ValueError as exc:
        return {"ok": False, "error": str(exc), "retryable": False}
    try:
        opener = tls_compat.build_secure_opener(_NoDownloadRedirect())
        with opener.open(req, timeout=timeout) as resp:
            content_length = int(resp.headers.get("Content-Length") or 0)
            if content_length > max_bytes:
                return {"ok": False, "error": "手机原图超过当前下载上限", "retryable": False}
            data = resp.read(max_bytes + 1)
        if len(data) > max_bytes:
            return {"ok": False, "error": "手机原图超过当前下载上限", "retryable": False}
        return {"ok": True, "data": data}
    except urllib.error.HTTPError as exc:
        return {
            "ok": False,
            "error": f"影像下载失败（{exc.code}）",
            "http_status": exc.code,
            "retryable": exc.code >= 500 or exc.code in {403, 429},
        }
    except Exception as exc:
        return {
            "ok": False,
            "error": f"影像下载失败：{exc}",
            "network_error": True,
            "retryable": True,
        }


def desktop_download_bytes(download_url: str, max_bytes: int = 50 * 1024 * 1024) -> dict:
    """下载短期中转的手机原图，超过服务器/客户端上限立即拒绝。"""
    base, token, error = _cloud_auth_context()
    if error:
        return error
    return _desktop_download_bytes_with_context(download_url, base, token, max_bytes)


def desktop_backfill_photo(file_path, metadata: dict) -> dict:
    """上传现有电脑照片的 100KB JPEG 预览，不读写本地原图。"""
    base, token, error = _cloud_auth_context()
    if error:
        return error
    path = Path(file_path)
    try:
        raw = path.read_bytes()
    except OSError as exc:
        return {"ok": False, "error": f"无法读取查看副本：{exc}", "retryable": False}
    if not raw or len(raw) > 102400:
        return {"ok": False, "error": "云端预览必须为 1~102400 字节", "retryable": False}

    boundary = "----AlbumDesktopSync" + secrets.token_hex(16)
    chunks = []
    for key, value in (metadata or {}).items():
        if value is None:
            continue
        chunks.extend([
            f"--{boundary}\r\n".encode("ascii"),
            f'Content-Disposition: form-data; name="{str(key)}"\r\n\r\n'.encode("utf-8"),
            str(value).encode("utf-8"),
            b"\r\n",
        ])
    chunks.extend([
        f"--{boundary}\r\n".encode("ascii"),
        b'Content-Disposition: form-data; name="file"; filename="preview.jpg"\r\n',
        b"Content-Type: image/jpeg\r\n\r\n",
        raw,
        b"\r\n",
        f"--{boundary}--\r\n".encode("ascii"),
    ])
    req = urllib.request.Request(
        f"{base}/api/desktop/v1/backfill-photo",
        data=b"".join(chunks),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with _open_no_redirect(req, timeout=45) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            return result if isinstance(result, dict) else {"ok": False, "error": "服务器返回数据格式不正确"}
    except urllib.error.HTTPError as exc:
        try:
            result = json.loads(exc.read().decode("utf-8"))
        except Exception:
            result = {"ok": False, "error": f"服务器错误（{exc.code}）"}
        if not isinstance(result, dict):
            result = {"ok": False, "error": f"服务器错误（{exc.code}）"}
        result.setdefault("ok", False)
        result.setdefault("http_status", exc.code)
        result.setdefault("retryable", exc.code >= 500 or exc.code == 429)
        return result
    except Exception as exc:
        return {
            "ok": False,
            "error": f"查看副本上传失败：{exc}",
            "network_error": True,
            "retryable": True,
        }

