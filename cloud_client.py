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
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

CLOUD_CONFIG_NAME = "cloud_config.json"
CLOUD_ACCOUNT_NAME = "cloud_account.json"
DEFAULT_SERVER_URL = "https://api.example.com"  # 部署后改为你的域名
OFFLINE_GRACE_SECONDS = 7 * 24 * 3600
APP_VERSION = "A20260807-2.13"  # 与桌面启动器版本一致，用于检查更新


def _get_json(url):
    req = urllib.request.Request(url, method="GET")
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


def _data_dir() -> Path:
    return Path(os.environ.get("ALBUM_DATA_DIR", r"D:\工程影像资料")).expanduser()


def cloud_config_path() -> Path:
    return _data_dir() / CLOUD_CONFIG_NAME


def cloud_account_path() -> Path:
    return _data_dir() / CLOUD_ACCOUNT_NAME


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
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


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
    licensing.write_installed_license(code)  # 本地验签并写入 license.dat
    # is_member：账号有有效授权即会员（无限使用、无水印）；否则免费版（300张+水印）
    is_member = bool(activated.get("is_member")) or bool((activated.get("license") or {}).get("has_license"))
    account = {
        "username": username,
        "token": token,
        "server": base,
        "activated_at": int(time.time()),
        "is_member": is_member,
    }
    _write_json(cloud_account_path(), account)
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

    account = _read_json(cloud_account_path()) or {}
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
        _write_json(cloud_account_path(), account)
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

    account = _read_json(cloud_account_path()) or {}
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
    """当前会员状态：登录的账号有有效授权=会员（无限、无水印）；否则免费版（300张+水印）。

    未登录或服务器未部署时按免费版处理（保守），登录后按账号等级。
    返回 {"is_member": bool, "member_tier": "free"|"member", "account": str}
    """
    account = _read_json(cloud_account_path()) or {}
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


def register(account: str, password: str, code: str, invite_code: str = ""):
    """注册账号（用手机/QQ/邮箱），可填邀请码。"""
    base = server_url()
    payload = {"username": account, "password": password, "code": code}
    if invite_code:
        payload["invite_code"] = invite_code.strip().upper()
    return _post_json(f"{base}/api/register", payload)


def invite_status(token: str = ""):
    """查询我的邀请码、已邀请人数、已奖励月数。"""
    base = server_url()
    account = _read_json(cloud_account_path()) or {}
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
