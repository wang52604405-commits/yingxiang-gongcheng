# -*- coding: utf-8 -*-
"""
授权模块（Ed25519 非对称签名，防 keygen 版）

安全模型：
- 客户端程序（工程影像管理平台.exe / album_server.exe）只内置公钥，只能验签；
- 私钥只放在开发者机器（E:\\use\\keys\\private_key.pem），由授权码生成器调用；
- 即使客户端被完整反编译，也拿不到私钥，无法伪造授权码。

对外接口保持兼容：machine_id / generate_license / decode_license /
verify_license / read_installed_license / write_installed_license /
trial_status / license_status 等，调用方无需修改。
"""

import base64
import hashlib
import json
import os
import platform
import re
import socket
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path


APP_CODE = "HDYX"
LICENSE_VALID_DAYS = 90
LICENSE_TYPE_TERM = "term"
LICENSE_TYPE_LIFETIME = "lifetime"
LIFETIME_LICENSE_PRICE = 129
TRIAL_VALID_DAYS = 30

# 客户端内置公钥（DER，base64）。私钥绝不进入客户端代码与安装包。
PUBLIC_KEY_DER_B64 = "MCowBQYDK2VwAyEAgB/dyJASznDMzb1hQe1B+9X+hn1/rD7VA7TZyD2zeZU="

# 私钥文件名：只与“授权码生成器”放在一起，不进安装包。
PRIVATE_KEY_NAME = "private_key.pem"


def app_root():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def license_path():
    return Path(os.environ.get("ALBUM_LICENSE_FILE", app_root() / "license.dat")).expanduser()


def trial_path():
    return Path(os.environ.get("ALBUM_TRIAL_FILE", app_root() / "trial.json")).expanduser()


def _safe_text(value):
    return re.sub(r"\s+", " ", str(value or "").strip())


def raw_machine_fingerprint():
    parts = [
        platform.node(),
        socket.gethostname(),
        str(uuid.getnode()),
        platform.system(),
        platform.machine(),
    ]
    return "|".join(_safe_text(part).lower() for part in parts)


def machine_id():
    digest = hashlib.sha256(raw_machine_fingerprint().encode("utf-8")).hexdigest().upper()
    return f"{APP_CODE}-{digest[:4]}-{digest[4:8]}-{digest[8:12]}-{digest[12:16]}"


def _canonical_json(data):
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _b64u(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _b64u_decode(value: str) -> bytes:
    value = _safe_text(value)
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _public_key():
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    key = serialization.load_der_public_key(base64.b64decode(PUBLIC_KEY_DER_B64))
    if not isinstance(key, Ed25519PublicKey):
        raise ValueError("内置公钥类型错误")
    return key


def _private_key_path():
    """私钥查找顺序：生成器 exe 目录 -> 源码目录 -> 工作目录。"""
    bases = []
    if getattr(sys, "frozen", False):
        bases.append(Path(sys.executable).resolve().parent)
    bases.append(Path(__file__).resolve().parent)
    bases.append(app_root())
    for base in bases:
        candidate = base / PRIVATE_KEY_NAME
        if candidate.exists():
            return candidate
    return None


def _private_key():
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    path = _private_key_path()
    if path is None:
        raise ValueError(
            f"未找到私钥文件 {PRIVATE_KEY_NAME}，请确认它与授权码生成器放在同一目录"
        )
    key = serialization.load_pem_private_key(path.read_bytes(), password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise ValueError("私钥文件类型错误")
    return key


def _parse_utc(value):
    value = _safe_text(value)
    if not value:
        raise ValueError("授权码缺少到期时间")
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise ValueError("授权码到期时间无效") from exc


def default_owner():
    """授权所属人：优先从生成器目录 gen_config.json 读取，默认空。"""
    try:
        base = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
        cfg = json.loads((base / "gen_config.json").read_text(encoding="utf-8"))
        return _safe_text(cfg.get("owner"))
    except Exception:
        return ""


def generate_license(machine, owner=None, license_type=LICENSE_TYPE_TERM, valid_days=LICENSE_VALID_DAYS):
    """用 Ed25519 私钥签发授权码（仅授权码生成器调用）。"""
    issued_at = datetime.now(timezone.utc)
    license_type = _safe_text(license_type).lower() or LICENSE_TYPE_TERM
    if license_type not in {LICENSE_TYPE_TERM, LICENSE_TYPE_LIFETIME}:
        raise ValueError("授权类型无效")
    valid_days = int(valid_days or LICENSE_VALID_DAYS)

    payload = {
        "app": APP_CODE,
        "machine_id": _safe_text(machine).upper(),
        "owner": _safe_text(owner) or default_owner(),
        "issued_at": issued_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "license_type": license_type,
        "valid_days": 0 if license_type == LICENSE_TYPE_LIFETIME else valid_days,
        "version": 2,
    }
    if license_type == LICENSE_TYPE_LIFETIME:
        payload["lifetime_price"] = LIFETIME_LICENSE_PRICE
    else:
        expires_at = issued_at + timedelta(days=valid_days)
        payload["expires_at"] = expires_at.strftime("%Y-%m-%dT%H:%M:%SZ")

    signature = _b64u(_private_key().sign(_canonical_json(payload)))
    signed = {
        "payload": payload,
        "signature": signature,
    }
    raw = json.dumps(signed, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_license(code):
    """解析并用公钥验签。验签失败抛 ValueError。"""
    code = _safe_text(code)
    if not code:
        raise ValueError("授权码不能为空")
    padded = code + "=" * (-len(code) % 4)
    try:
        raw = base64.urlsafe_b64decode(padded.encode("ascii"))
        data = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise ValueError("授权码格式无效") from exc
    payload = data.get("payload") or {}
    signature = _safe_text(data.get("signature"))
    if not payload or not signature:
        raise ValueError("授权码内容不完整")

    from cryptography.exceptions import InvalidSignature

    try:
        _public_key().verify(_b64u_decode(signature), _canonical_json(payload))
    except InvalidSignature as exc:
        raise ValueError("授权码签名无效") from exc

    if payload.get("app") != APP_CODE:
        raise ValueError("授权码不适用于本软件")
    return payload


def verify_license(code, expected_machine=None):
    payload = decode_license(code)
    expected = _safe_text(expected_machine or machine_id()).upper()
    actual = _safe_text(payload.get("machine_id")).upper()
    if actual != expected:
        raise ValueError("授权码与本机机器 ID 不匹配")

    license_type = _safe_text(payload.get("license_type")).lower() or LICENSE_TYPE_TERM
    if license_type == LICENSE_TYPE_LIFETIME:
        payload["license_type"] = LICENSE_TYPE_LIFETIME
        payload["valid_days"] = 0
        payload["expires_at"] = ""
        payload.setdefault("lifetime_price", LIFETIME_LICENSE_PRICE)
        return payload

    payload["license_type"] = LICENSE_TYPE_TERM
    if payload.get("expires_at"):
        expiry = _parse_utc(payload.get("expires_at"))
    else:
        issued_at = _parse_utc(payload.get("issued_at"))
        expiry = issued_at + timedelta(days=LICENSE_VALID_DAYS)
        payload["expires_at"] = expiry.strftime("%Y-%m-%dT%H:%M:%SZ")
        payload["valid_days"] = LICENSE_VALID_DAYS
    if datetime.now(timezone.utc) > expiry:
        raise ValueError("授权码已到期，请重新授权")
    return payload


def read_installed_license():
    path = license_path()
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8").strip()


def write_installed_license(code):
    payload = verify_license(code)
    path = license_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(code.strip(), encoding="utf-8")
    return payload


def _trial_anchor_files():
    """试用期起始时间存放的多个位置（删掉一个不会重置试用期）。"""
    paths = []
    app_dir = app_root()
    paths.append(app_dir / "trial.json")  # 安装目录（卸载会删，但其它锚点仍在）
    data_dir = Path(os.environ.get("ALBUM_DATA_DIR", "")).expanduser()
    if data_dir and data_dir.is_absolute() and data_dir != app_dir:
        paths.append(data_dir / ".trial_anchor")  # 数据目录（重装不删）
    roaming = Path(os.environ.get("APPDATA", "")).expanduser()
    if roaming and roaming.is_absolute():
        paths.append(roaming / "工程影像管理平台" / "trial.anchor")  # 用户数据目录（重装不删）
    seen = set()
    result = []
    for path in paths:
        key = str(path).lower()
        if key not in seen:
            seen.add(key)
            result.append(path)
    return result


def _read_trial_anchor(path):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        started = _parse_utc(_safe_text(data.get("started_at")))
        max_seen = _parse_utc(_safe_text(data.get("max_seen"))) if data.get("max_seen") else None
        return started, max_seen
    except Exception:
        return None, None


def _write_trial_anchor(path, started, max_seen):
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "started_at": started.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "max_seen": max_seen.strftime("%Y-%m-%dT%H:%M:%SZ"),
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return True
    except Exception:
        return False


def _read_trial_registry():
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\工程影像管理平台\Trial") as key:
            started_raw, _ = winreg.QueryValueEx(key, "started_at")
            max_raw, _ = winreg.QueryValueEx(key, "max_seen")
        started = _parse_utc(_safe_text(started_raw))
        max_seen = _parse_utc(_safe_text(max_raw)) if max_raw else None
        return started, max_seen
    except Exception:
        return None, None


def _write_trial_registry(started, max_seen):
    try:
        import winreg

        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, r"Software\工程影像管理平台\Trial", 0, winreg.KEY_WRITE) as key:
            winreg.SetValueEx(key, "started_at", 0, winreg.REG_SZ, started.strftime("%Y-%m-%dT%H:%M:%SZ"))
            winreg.SetValueEx(key, "max_seen", 0, winreg.REG_SZ, max_seen.strftime("%Y-%m-%dT%H:%M:%SZ"))
        return True
    except Exception:
        return False


def trial_status():
    now = datetime.now(timezone.utc)
    anchors = []
    for path in _trial_anchor_files():
        started, max_seen = _read_trial_anchor(path)
        if started is not None:
            anchors.append((started, max_seen))
    reg_started, reg_max_seen = _read_trial_registry()
    if reg_started is not None:
        anchors.append((reg_started, reg_max_seen))

    if not anchors:
        # 第一次运行：从现在开始计时，并把起始时间写进所有位置
        started = now
        max_seen = now
    else:
        # 取所有锚点里最早的起始时间（改/删单个文件无法重置）
        started = min(item[0] for item in anchors)
        seen_times = [item[1] for item in anchors if item[1] is not None]
        max_seen = max([now] + seen_times)

    # 有效当前时间 = 真实时钟 与 历史记录到的最大时间 取大值（防止把系统时间往回拨）
    effective_now = max(now, max_seen)
    for path in _trial_anchor_files():
        _write_trial_anchor(path, started, effective_now)
    _write_trial_registry(started, effective_now)

    expires = started + timedelta(days=TRIAL_VALID_DAYS)
    remaining = max(0, (expires.date() - effective_now.date()).days)
    active = effective_now <= expires
    return {
        "trial_started_at": started.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "trial_expires_at": expires.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "trial_valid_days": TRIAL_VALID_DAYS,
        "trial_days_remaining": remaining,
        "trial_period_active": active,
        "trial_file": str(trial_path()),
    }


def license_status():
    current_machine = machine_id()
    code = read_installed_license()
    trial = trial_status()
    if not code:
        result = {
            "ok": False,
            "machine_id": current_machine,
            "message": f"试用期剩余 {trial['trial_days_remaining']} 天" if trial["trial_period_active"] else "试用期已到期",
            "license_file": str(license_path()),
            "has_license": False,
            "expired": not trial["trial_period_active"],
        }
        result.update(trial)
        return result
    try:
        payload = verify_license(code, current_machine)
        is_lifetime = payload.get("license_type") == LICENSE_TYPE_LIFETIME
        result = {
            "ok": True,
            "machine_id": current_machine,
            "owner": payload.get("owner", ""),
            "issued_at": payload.get("issued_at", ""),
            "expires_at": payload.get("expires_at", ""),
            "license_type": payload.get("license_type", LICENSE_TYPE_TERM),
            "is_lifetime": is_lifetime,
            "lifetime_price": payload.get("lifetime_price", LIFETIME_LICENSE_PRICE),
            "valid_days": payload.get("valid_days", LICENSE_VALID_DAYS),
            "message": "终身授权有效" if is_lifetime else "授权有效",
            "license_file": str(license_path()),
            "has_license": True,
            "expired": False,
        }
        result.update(trial)
        return result
    except ValueError as exc:
        result = {
            "ok": False,
            "machine_id": current_machine,
            "message": str(exc),
            "license_file": str(license_path()),
            "has_license": True,
            "expired": "到期" in str(exc),
        }
        result.update(trial)
        return result
