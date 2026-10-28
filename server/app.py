# -*- coding: utf-8 -*-
"""
工程影像管理平台 — 账号与授权中心服务器

启动：
  python -m server.app                          # 开发模式，127.0.0.1:5000
  ALBUM_SERVER_HOST=0.0.0.0 ALBUM_SERVER_PORT=80 python -m server.app

创建管理员：
  python -m server.app create-admin --username admin --password 强密码

接口：
  POST /api/register            注册客户账号
  POST /api/login               登录（返回 Bearer 令牌）
  GET  /api/me                  当前账号信息
  POST /api/activate            绑定本机并签发授权码（客户端调用）
  GET  /api/admin/accounts      管理后台：账号+授权+机器列表
  POST /api/admin/license       开通/修改授权
  POST /api/admin/revoke        吊销授权（全部机器下线）
  POST /api/admin/unbind        解绑某台机器
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import random
import re
import string
import sys
import time as _time
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from flask import Flask, g, jsonify, render_template, request, send_file, send_from_directory
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from werkzeug.exceptions import HTTPException
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import check_password_hash, generate_password_hash

from . import config, db

# 简单内存限流：每 IP 每窗口最多允许的次数，防止暴力破解/灌账号
_rate_hits = defaultdict(list)
RATE_WINDOW = 60          # 窗口 60 秒
RATE_LIMIT = 20           # 窗口内最多 20 次


def _rate_limited():
    """按请求 IP 计数；超限返回 True。"""
    ip = str(request.remote_addr or "unknown")
    now = _time.time()
    hits = [t for t in _rate_hits[ip] if now - t < RATE_WINDOW]
    if len(hits) >= RATE_LIMIT:
        return True
    hits.append(now)
    _rate_hits[ip] = hits
    return False


# 验证码 TTL。存储用数据库（gunicorn 多 worker 共享），不用进程内存
CODE_TTL = 600


def _save_code(code_key: str, code: str) -> None:
    """保存验证码到数据库（多 worker 共享）。"""
    conn = db.connect()
    try:
        conn.execute(
            "INSERT INTO mail_codes (code_key, code, expires_at) VALUES (?, ?, ?) "
            "ON CONFLICT(code_key) DO UPDATE SET code = excluded.code, "
            "expires_at = excluded.expires_at, created_at = datetime('now', 'localtime')",
            (code_key, code, int(_time.time()) + CODE_TTL),
        )
        conn.commit()
    finally:
        conn.close()


def _consume_code(code_key: str, code: str) -> bool:
    """校验并一次性消费验证码；正确且未过期返回 True。"""
    conn = db.connect()
    try:
        row = conn.execute(
            "SELECT code, expires_at FROM mail_codes WHERE code_key = ?", (code_key,)
        ).fetchone()
        if not row:
            return False
        conn.execute("DELETE FROM mail_codes WHERE code_key = ?", (code_key,))
        conn.commit()
        if str(row["code"]) != code:
            return False
        if int(row["expires_at"]) < int(_time.time()):
            return False
        return True
    finally:
        conn.close()
# 邀请码字符集：去易混字符（0/O、1/I/L）
INVITE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
INVITE_CODE_LEN = 8
INVITE_MILESTONE = 10   # 每邀请 10 人，邀请人续期 1 个月
REWARD_MONTH_DAYS = 30


def _deep_merge(base: dict, override: dict) -> dict:
    result = json.loads(json.dumps(base, ensure_ascii=False))
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _normalized_product_config(value=None) -> dict:
    """合并默认值并把后台可编辑数值限制在安全范围内。"""
    product = _deep_merge(config.DEFAULT_PRODUCT_CONFIG, value or {})
    pricing = product["pricing"]
    pricing["monthly_price"] = max(1, min(9999, int(pricing.get("monthly_price") or 39)))
    pricing["lifetime_price"] = max(1, min(99999, int(pricing.get("lifetime_price") or 399)))
    pricing["price_label"] = str(pricing.get("price_label") or "原价")[:40]
    mini_program = product["mini_program"]
    raw_limit = mini_program.get("free_upload_limit", 500)
    parsed_limit = int(500 if raw_limit is None else raw_limit)
    # 100 是旧版本的小程序默认额度；产品策略升级后自动迁移为 500。
    # 0 和其它管理员明确设置的数值仍保持原意。
    if parsed_limit == 100:
        parsed_limit = 500
    mini_program["free_upload_limit"] = max(0, min(100000, parsed_limit))
    free = product["free"]
    free["photo_limit"] = max(0, min(100000, int(free.get("photo_limit") or 300)))
    free["batch_print_enabled"] = bool(free.get("batch_print_enabled", False))
    # 免费版 300 张为完整可用额度，不叠加产品水印。
    free["watermark_enabled"] = False
    free["upload_expiry_enabled"] = bool(free.get("upload_expiry_enabled", False))
    invite = product["invite"]
    invite["enabled"] = bool(invite.get("enabled", True))
    invite["milestone"] = max(1, min(1000, int(invite.get("milestone") or 10)))
    invite["reward_days"] = max(0, min(3650, int(invite.get("reward_days") or 30)))
    invite["qualification"] = "activated_unique_device"
    cloud = product["cloud_preview"]
    cloud["enabled"] = bool(cloud.get("enabled", True))
    cloud["requires_member"] = bool(cloud.get("requires_member", False))
    cloud["beta_free_access"] = bool(cloud.get("beta_free_access", True))
    cloud["thumb_max_side"] = max(320, min(1600, int(cloud.get("thumb_max_side") or 720)))
    cloud["thumb_quality"] = max(40, min(92, int(cloud.get("thumb_quality") or 76)))
    cloud["max_thumbs_per_project"] = max(1, min(1000, int(cloud.get("max_thumbs_per_project") or 240)))
    cloud["max_projects_per_sync"] = max(1, min(500, int(cloud.get("max_projects_per_sync") or 200)))
    cloud["max_thumb_b64"] = max(100000, min(2000000, int(cloud.get("max_thumb_b64") or 600000)))
    logging_cfg = product["logging"]
    logging_cfg["enabled"] = bool(logging_cfg.get("enabled", True))
    logging_cfg["max_message"] = max(200, min(10000, int(logging_cfg.get("max_message") or 2000)))
    logging_cfg["max_stack"] = max(1000, min(50000, int(logging_cfg.get("max_stack") or 12000)))
    logging_cfg["max_context"] = max(500, min(20000, int(logging_cfg.get("max_context") or 8000)))
    logging_cfg["retention_days"] = max(7, min(365, int(logging_cfg.get("retention_days") or 90)))
    logging_cfg["max_records"] = max(500, min(50000, int(logging_cfg.get("max_records") or 5000)))
    product["config_version"] = max(1, int(product.get("config_version") or 1))
    return product


def _product_config(conn=None) -> dict:
    own_conn = conn is None
    conn = conn or db.connect()
    try:
        row = conn.execute(
            "SELECT value_json FROM product_settings WHERE setting_key = 'public'"
        ).fetchone()
        saved = {}
        if row:
            try:
                saved = json.loads(row["value_json"])
            except (TypeError, ValueError):
                saved = {}
        return _normalized_product_config(saved)
    finally:
        if own_conn:
            conn.close()


def _save_product_config(value: dict, admin_id: int) -> dict:
    current = _product_config()
    merged = _normalized_product_config(_deep_merge(current, value or {}))
    merged["config_version"] = int(current.get("config_version") or 1) + 1
    conn = db.connect()
    try:
        conn.execute(
            "INSERT INTO product_settings (setting_key, value_json, updated_at, updated_by) "
            "VALUES ('public', ?, ?, ?) ON CONFLICT(setting_key) DO UPDATE SET "
            "value_json = excluded.value_json, updated_at = excluded.updated_at, "
            "updated_by = excluded.updated_by",
            (json.dumps(merged, ensure_ascii=False), _now(), admin_id),
        )
        conn.commit()
    finally:
        conn.close()
    return merged


def _hash_identifier(value: str) -> str:
    raw = (str(value or "").strip() + "|" + config.SECRET_KEY).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _generate_invite_code(conn):
    """生成不重复的 8 位邀请码。"""
    for _ in range(50):
        code = "".join(random.choice(INVITE_ALPHABET) for _ in range(INVITE_CODE_LEN))
        exists = conn.execute(
            "SELECT 1 FROM accounts WHERE invite_code = ?", (code,)
        ).fetchone()
        if not exists:
            return code
    return "INV" + str(int(_time.time()))[-5:]


def _grant_or_extend_license(conn, account_id: int, days: int):
    """给账号追加 term 授权 days 天：已有授权则从当前到期时间往后延，否则新建。"""
    existing = conn.execute(
        "SELECT * FROM licenses WHERE account_id = ? ORDER BY id DESC LIMIT 1",
        (account_id,),
    ).fetchone()
    now = datetime.now(timezone.utc)
    if existing and existing["active"]:
        if existing["license_type"] == "lifetime":
            return  # 终身授权无需续期
        base = now
        if existing["expires_at"]:
            try:
                base = _parse_utc(existing["expires_at"])
                if base < now:
                    base = now
            except ValueError:
                base = now
        expires_at = (base + timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
        conn.execute(
            "UPDATE licenses SET valid_days = ?, expires_at = ?, active = 1, "
            "issued_at = ? WHERE id = ?",
            (max(int(existing["valid_days"] or 0), days), expires_at, _now(), existing["id"]),
        )
    else:
        expires_at = (now + timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
        conn.execute(
            "INSERT INTO licenses (account_id, license_type, valid_days, machine_limit, "
            "issued_at, expires_at, active) VALUES (?, 'term', ?, ?, ?, ?, 1)",
            (account_id, days, config.DEFAULT_MACHINE_LIMIT, _now(), expires_at),
        )


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_utc(value: str):
    """解析带 Z 后缀的 UTC 时间。Python 3.10 的 fromisoformat 不认 Z，
    用 strptime 显式解析并标记为 UTC，避免到期校验被静默跳过。"""
    return datetime.strptime(str(value), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def _version_key(value: str):
    """按数字段比较 A20260808-2.21，避免仅用不等号把旧版本误判为更新。"""
    numbers = [int(part) for part in re.findall(r"\d+", str(value or ""))]
    return tuple(numbers) if numbers else (0,)


def _b64u(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _b64u_decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _canonical(payload: dict) -> bytes:
    return json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


class LicenseSigner:
    """用服务器私钥签发 Ed25519 授权码（客户端内置公钥验签，格式兼容）。"""

    def __init__(self, path):
        self.path = path
        self._key = None

    def _load(self):
        if self._key is None:
            from cryptography.hazmat.primitives import serialization

            if not self.path.exists():
                raise RuntimeError(f"未找到授权私钥: {self.path}")
            self._key = serialization.load_pem_private_key(
                self.path.read_bytes(), password=None
            )
        return self._key

    def sign(self, payload: dict) -> str:
        canon = _canonical(payload)
        sig = self._load().sign(canon)
        signed = {"payload": payload, "signature": _b64u(sig)}
        raw = json.dumps(signed, ensure_ascii=False, separators=(",", ":")).encode(
            "utf-8"
        )
        return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


signer = LicenseSigner(config.PRIVATE_KEY_PATH)
serializer = URLSafeTimedSerializer(config.SECRET_KEY)


def _error(message: str, code: int = 400):
    return jsonify({"ok": False, "error": message}), code


def _token_for(
    user_id: int,
    scope: str = "desktop",
    machine_id: str = "",
    binding_id: int = 0,
    mobile_auth_version: int = 0,
) -> str:
    """签发带客户端作用域的账号令牌。

    旧版令牌只有 uid，解析时按 legacy 桌面端兼容；新版微信令牌
    显式标记 mobile，不能访问电脑原图接口。
    """
    payload = {"uid": user_id, "scope": str(scope or "desktop")}
    conn = db.connect()
    try:
        access = conn.execute("SELECT version FROM admin_account_access WHERE account_id=?", (user_id,)).fetchone()
        payload["access_version"] = access["version"] if access else 0
    finally:
        conn.close()
    normalized_machine_id = str(machine_id or "").strip().upper()
    if normalized_machine_id:
        payload["machine_id"] = normalized_machine_id
    if str(scope or "") == "mobile":
        payload["binding_id"] = int(binding_id or 0)
        payload["mobile_auth_version"] = int(mobile_auth_version or 0)
    return serializer.dumps(payload, salt="album-auth")


def _user_from_token(token: str):
    if not token:
        return None
    try:
        data = serializer.loads(
            token, max_age=config.TOKEN_MAX_AGE, salt="album-auth"
        )
    except (BadSignature, SignatureExpired):
        return None
    conn = db.connect()
    try:
        row = conn.execute(
            "SELECT * FROM accounts WHERE id = ?", (data.get("uid"),)
        ).fetchone()
        if not row:
            return None
        user = dict(row)
        access = conn.execute("SELECT version FROM admin_account_access WHERE account_id=?", (user["id"],)).fetchone()
        if user["status"] != "active" or data.get("access_version", 0) != (access["version"] if access else 0):
            return None
        token_scope = str(data.get("scope") or "legacy")
        if token_scope == "mobile":
            binding_id = int(data.get("binding_id") or 0)
            raw_token_version = data.get("mobile_auth_version")
            token_version = int(raw_token_version if raw_token_version is not None else -1)
            if (
                binding_id <= 0
                or token_version != int(user.get("mobile_auth_version") or 0)
            ):
                return None
            binding = conn.execute(
                "SELECT 1 FROM wechat_bindings WHERE id = ? AND account_id = ?",
                (binding_id, user["id"]),
            ).fetchone()
            if not binding:
                return None
            user["_token_binding_id"] = binding_id
        user["_token_scope"] = token_scope
        user["_token_machine_id"] = str(data.get("machine_id") or "").strip().upper()
        return user
    finally:
        conn.close()


def _require_user():
    auth = request.headers.get("Authorization", "")
    token = auth[7:] if auth.startswith("Bearer ") else ""
    user = _user_from_token(token)
    if not user or user["status"] != "active":
        return None
    g.activity_user = user
    return user


def _require_admin():
    user = _require_user()
    if (
        not user
        or user["role"] != "admin"
        or user.get("_token_scope") not in {"legacy", "desktop"}
    ):
        return None
    return user


def _account_license(conn, account_id: int):
    return conn.execute(
        "SELECT * FROM licenses WHERE account_id = ? ORDER BY id DESC LIMIT 1",
        (account_id,),
    ).fetchone()


def _has_active_membership(conn, account_id: int) -> bool:
    lic = _account_license(conn, account_id)
    if not lic or not bool(lic["active"]):
        return False
    if lic["license_type"] == "lifetime":
        return True
    expires_at = str(lic["expires_at"] or "")
    if not expires_at:
        return bool(int(lic["valid_days"] or 0) > 0)
    try:
        return datetime.now(timezone.utc) <= _parse_utc(expires_at)
    except ValueError:
        return False


def _cloud_access_allowed(conn, account_id: int) -> bool:
    cloud = _product_config(conn).get("cloud_preview", {})
    if not cloud.get("enabled", True):
        return False
    if not cloud.get("requires_member", False) or cloud.get("beta_free_access", False):
        return True
    return _has_active_membership(conn, account_id)


def _qualify_invite(conn, invitee_account_id: int, machine_id: str) -> None:
    """首次绑定独立设备后确认邀请有效；同一设备不能为多次邀请计奖。"""
    invite_cfg = _product_config(conn).get("invite", {})
    if not invite_cfg.get("enabled", True):
        return
    relation = conn.execute(
        "SELECT * FROM invites WHERE invitee_account_id = ?",
        (invitee_account_id,),
    ).fetchone()
    if not relation or str(relation["status"] or "pending") == "qualified":
        return
    device_hash = _hash_identifier(machine_id.upper())
    duplicate = conn.execute(
        "SELECT 1 FROM invites WHERE inviter_id = ? AND device_hash = ? "
        "AND status = 'qualified' AND invitee_account_id <> ?",
        (relation["inviter_id"], device_hash, invitee_account_id),
    ).fetchone()
    if duplicate:
        conn.execute(
            "UPDATE invites SET status = 'rejected', device_hash = ? "
            "WHERE invitee_account_id = ?",
            (device_hash, invitee_account_id),
        )
        return
    conn.execute(
        "UPDATE invites SET status = 'qualified', qualified_at = ?, device_hash = ? "
        "WHERE invitee_account_id = ?",
        (_now(), device_hash, invitee_account_id),
    )
    count_row = conn.execute(
        "SELECT COUNT(*) AS n FROM invites WHERE inviter_id = ? AND status = 'qualified'",
        (relation["inviter_id"],),
    ).fetchone()
    milestone = max(1, int(invite_cfg.get("milestone") or 10))
    target = int(count_row["n"]) // milestone
    inviter = conn.execute(
        "SELECT invite_reward_months FROM accounts WHERE id = ?",
        (relation["inviter_id"],),
    ).fetchone()
    already = int(inviter["invite_reward_months"] or 0) if inviter else 0
    if target > already:
        reward_days = max(0, int(invite_cfg.get("reward_days") or 30))
        if reward_days:
            _grant_or_extend_license(
                conn, relation["inviter_id"], (target - already) * reward_days
            )
        conn.execute(
            "UPDATE accounts SET invite_reward_months = ? WHERE id = ?",
            (target, relation["inviter_id"]),
        )


def _machine_count(conn, account_id: int):
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM machines WHERE account_id = ? AND active = 1",
        (account_id,),
    ).fetchone()
    return int(row["n"])


def _license_status_for(account: dict, machine_id: str = ""):
    conn = db.connect()
    try:
        lic = _account_license(conn, account["id"])
        machines = conn.execute(
            "SELECT machine_id, bound_at, last_seen FROM machines "
            "WHERE account_id = ? AND active = 1 ORDER BY bound_at",
            (account["id"],),
        ).fetchall()
        return {
            "account": account["username"],
            "role": account["role"],
            "has_license": lic is not None and bool(lic["active"]),
            "license_type": dict(lic).get("license_type") if lic else "",
            "expires_at": dict(lic).get("expires_at") if lic else "",
            "machine_limit": dict(lic).get("machine_limit") if lic else config.DEFAULT_MACHINE_LIMIT,
            "machine_count": _machine_count(conn, account["id"]),
            "machines": [dict(m) for m in machines],
            "bound_this_machine": machine_id in {m["machine_id"] for m in machines},
        }
    finally:
        conn.close()


def _sign_for(account: dict, machine_id: str, license_row) -> str:
    lic = dict(license_row)
    payload = {
        "app": config.APP_CODE,
        "account": account["username"],
        "machine_id": machine_id.upper(),
        "license_type": lic["license_type"],
        "issued_at": lic["issued_at"],
        "expires_at": lic["expires_at"] or "",
        "valid_days": int(lic["valid_days"] or 0),
        "version": 3,
    }
    return signer.sign(payload)


_SENSITIVE_KEYS = {
    "password", "passwd", "pwd", "token", "authorization", "license_code",
    "secret", "private_key", "thumb_b64", "image", "photo", "content",
}


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


def _sanitize_telemetry(value, limit: int, depth: int = 0):
    if depth > 4:
        return "[DEPTH_LIMIT]"
    if isinstance(value, dict):
        cleaned = {}
        for key, item in list(value.items())[:50]:
            key_text = str(key)[:80]
            if key_text.lower() in _SENSITIVE_KEYS or any(
                term in key_text.lower() for term in ("password", "token", "secret", "photo", "image", "b64")
            ):
                cleaned[key_text] = "[REDACTED]"
            else:
                cleaned[key_text] = _sanitize_telemetry(item, limit, depth + 1)
        return cleaned
    if isinstance(value, (list, tuple)):
        return [_sanitize_telemetry(item, limit, depth + 1) for item in list(value)[:30]]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return _redact_text(value, limit)


def _store_client_error(payload: dict, user=None) -> int:
    product = _product_config()
    log_cfg = product.get("logging", {})
    if not log_cfg.get("enabled", True):
        return 0
    max_message = int(log_cfg.get("max_message") or 2000)
    max_stack = int(log_cfg.get("max_stack") or 12000)
    max_context = int(log_cfg.get("max_context") or 8000)
    message = _redact_text(payload.get("message"), max_message)
    stack = _redact_text(payload.get("stack"), max_stack)
    error_type = _redact_text(payload.get("error_type"), 160)
    source = _redact_text(payload.get("source") or "desktop", 80)
    severity = str(payload.get("severity") or "error").lower()
    if severity not in {"info", "warning", "error", "critical"}:
        severity = "error"
    context = _sanitize_telemetry(payload.get("context") or {}, 1200)
    context_json = json.dumps(context, ensure_ascii=False)[:max_context]
    fingerprint_seed = "|".join((source, error_type, message[:500], stack.splitlines()[-1] if stack else ""))
    fingerprint = hashlib.sha256(fingerprint_seed.encode("utf-8", "replace")).hexdigest()[:32]
    machine_id = _redact_text(payload.get("machine_id"), 160)
    machine_hash = _hash_identifier(machine_id) if machine_id else ""
    request_ip_hash = _hash_identifier(request.remote_addr or "")
    conn = db.connect()
    try:
        cur = conn.execute(
            "INSERT INTO client_error_logs "
            "(account_id, fingerprint, source, severity, error_type, message, stack, "
            "context_json, app_version, machine_id, client_time, request_ip) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                user.get("id") if user else None,
                fingerprint,
                source,
                severity,
                error_type,
                message,
                stack,
                context_json,
                _redact_text(payload.get("app_version"), 80),
                machine_hash,
                _redact_text(payload.get("client_time"), 80),
                request_ip_hash,
            ),
        )
        log_id = int(cur.lastrowid or 0)
        if log_id and log_id % 50 == 0:
            retention_days = max(7, min(int(log_cfg.get("retention_days") or 90), 365))
            max_records = max(500, min(int(log_cfg.get("max_records") or 5000), 50000))
            conn.execute(
                "DELETE FROM client_error_logs WHERE created_at < datetime('now', ?) ",
                (f"-{retention_days} days",),
            )
            conn.execute(
                "DELETE FROM client_error_logs WHERE id NOT IN "
                "(SELECT id FROM client_error_logs ORDER BY id DESC LIMIT ?)",
                (max_records,),
            )
        conn.commit()
        return log_id
    finally:
        conn.close()


def _valid_thumbnail_b64(value: str, max_length: int) -> bool:
    if not value or len(value) > max_length:
        return False
    try:
        raw = base64.b64decode(value, validate=True)
    except Exception:
        return False
    if not raw or len(raw) > int(max_length * 0.76):
        return False
    return (
        (raw.startswith(b"RIFF") and raw[8:12] == b"WEBP")
        or raw.startswith(b"\xff\xd8\xff")
        or raw.startswith(b"\x89PNG\r\n\x1a\n")
    )


def create_app():
    app = Flask(__name__)
    # gunicorn 仅监听 127.0.0.1，唯一上游是单层本机 nginx；因此只信任一跳
    # X-Forwarded-*，让按 IP 限流看到真实客户端而不是所有人共用 127.0.0.1。
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
    app.config["SECRET_KEY"] = config.SECRET_KEY
    app.config["MAX_CONTENT_LENGTH"] = config.MOBILE_MAX_REQUEST_BYTES
    app.json.ensure_ascii = False

    db.init_db()
    from .admin_ops import register_admin_ops
    register_admin_ops(app, _require_admin, _user_from_token)
    if config.ADMIN_USERNAME and config.ADMIN_PASSWORD:
        _ensure_admin(config.ADMIN_USERNAME, config.ADMIN_PASSWORD)

    @app.errorhandler(Exception)
    def handle_unexpected_error(exc):
        status = int(exc.code) if isinstance(exc, HTTPException) else 500
        if isinstance(exc, HTTPException):
            return _error(exc.description or "请求错误", status)
        try:
            auth = request.headers.get("Authorization", "")
            token = auth[7:] if auth.startswith("Bearer ") else ""
            user = _user_from_token(token) if token else None
            _store_client_error({
                "source": "server_api",
                "severity": "critical",
                "error_type": type(exc).__name__,
                "message": str(exc),
                "stack": __import__("traceback").format_exc(),
                "context": {"method": request.method, "path": request.path, "status": status},
                "app_version": "server",
                "client_time": _now(),
            }, user=user)
        except Exception:
            app.logger.exception("记录服务器异常失败")
        app.logger.exception("未处理的服务器异常")
        return _error("服务器内部错误，错误编号已反馈到后台", 500)

    @app.before_request
    def restrict_desktop_sync_token_scope():
        """机器限定令牌只是桌面同步能力，不是第二个全权账号令牌。"""
        auth = request.headers.get("Authorization", "")
        token = auth[7:] if auth.startswith("Bearer ") else ""
        if not token:
            return None
        try:
            claims = serializer.loads(
                token, max_age=config.TOKEN_MAX_AGE, salt="album-auth"
            )
        except (BadSignature, SignatureExpired):
            return None
        if claims.get("scope") == "desktop_sync" and not request.path.startswith(
            "/api/desktop/v1/"
        ):
            return (
                jsonify(
                    {
                        "ok": False,
                        "code": "desktop_sync_scope_forbidden",
                        "error": "电脑同步令牌仅能访问 /api/desktop/v1",
                    }
                ),
                403,
            )
        if claims.get("scope") == "mobile" and request.path.startswith("/api/cloud/"):
            return (
                jsonify(
                    {
                        "ok": False,
                        "code": "mobile_scope_forbidden",
                        "error": "微信端令牌无权访问旧版云预览接口",
                    }
                ),
                403,
            )
        return None

    @app.get("/")
    def index():
        return render_template("member_center.html")

    @app.get("/favicon.ico")
    def favicon():
        return "", 204

    @app.get("/cloud-preview")
    def cloud_preview_page():
        return render_template("cloud.html")

    @app.get("/admin")
    def admin_index():
        return render_template("admin.html")

    @app.get("/api/product-config")
    def product_config():
        """客户端公共产品策略；不包含服务器密钥、支付或管理员配置。"""
        return jsonify({"ok": True, "product": _product_config(), "server_time": _now()})

    @app.get("/api/instance")
    def instance_sentinel():
        """公开的非敏感实例哨兵；隔离 E2E 必须先校验它再发写请求。"""
        return jsonify(
            {
                "ok": True,
                "environment": config.SERVER_ENVIRONMENT,
                "instance_id": config.SERVER_INSTANCE_ID,
            }
        )

    @app.post("/api/client-errors")
    def client_errors():
        """接收桌面端和浏览器错误。请求体严限 64KB，敏感字段会再次脱敏。"""
        if request.content_length and request.content_length > 64 * 1024:
            return _error("错误日志内容过大", 413)
        data = request.get_json(silent=True) or {}
        if not isinstance(data, dict):
            return _error("错误日志格式不正确")
        auth = request.headers.get("Authorization", "")
        token = auth[7:] if auth.startswith("Bearer ") else ""
        user = _user_from_token(token) if token else None
        log_id = _store_client_error(data, user=user)
        return jsonify({"ok": True, "log_id": log_id})

    @app.post("/api/send-code")
    def send_code():
        """注册验证码（基础版）：生成 6 位验证码存内存返回给客户端，TTL 600 秒。"""
        if _rate_limited():
            return _error("操作过于频繁，请稍后再试", 429)
        data = request.get_json(silent=True) or {}
        account = str(data.get("account") or "").strip()
        if not (3 <= len(account) <= 64):
            return _error("账号长度需在 3~64 个字符之间")
        code = str(random.randint(100000, 999999))
        _save_code(f"reg:{account}", code)
        return jsonify({
            "ok": True,
            "code": code,
            "expires_in": CODE_TTL,
            "note": "基础版：验证码由服务器生成并返回（未接短信服务商）。",
        })

    @app.post("/api/register")
    def register():
        if _rate_limited():
            return _error("操作过于频繁，请稍后再试", 429)
        data = request.get_json(silent=True) or {}
        username = str(data.get("username") or "").strip()
        password = str(data.get("password") or "")
        invite_code = str(data.get("invite_code") or "").strip().upper()
        display_name = str(data.get("display_name") or "").strip()
        email = str(data.get("email") or "").strip()
        if not (3 <= len(username) <= 64) or any(ch.isspace() for ch in username):
            return _error("账号长度需在 3~64 个字符之间（可用手机号/QQ/邮箱）")
        if len(password) < 8 or not re.search(r"[A-Za-z]", password) or not re.search(r"\d", password):
            return _error("登录密码至少 8 位，并同时包含字母和数字")
        if email and not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
            return _error("邮箱格式不正确")
        # 免验证码注册（用户名+密码直接注册）

        conn = db.connect()
        try:
            exists = conn.execute(
                "SELECT 1 FROM accounts WHERE username = ?", (username,)
            ).fetchone()
            if exists:
                return _error("账号已存在")

            # 邀请码（可选）：查邀请人，写入 invites 表，并触发 10 人/月 续期奖励
            inviter = None
            invite_cfg = _product_config(conn).get("invite", {})
            if invite_code and invite_cfg.get("enabled", True):
                inviter = conn.execute(
                    "SELECT * FROM accounts WHERE invite_code = ?", (invite_code,)
                ).fetchone()
                if not inviter:
                    return _error("邀请码无效，请核对后重试")

            new_code = _generate_invite_code(conn)
            cur = conn.execute(
                "INSERT INTO accounts (username, password_hash, display_name, role, status, invite_code, inviter_id, email) "
                "VALUES (?, ?, ?, 'user', 'active', ?, ?, ?)",
                (username, generate_password_hash(password), display_name, new_code,
                 inviter["id"] if inviter else 0, email),
            )
            new_account_id = cur.lastrowid

            if inviter:
                # 先记为待确认；被邀请人首次在软件中绑定独立设备后才计为有效邀请。
                conn.execute(
                    "INSERT OR IGNORE INTO invites "
                    "(inviter_id, invitee_account_id, status, ip_hash) VALUES (?, ?, 'pending', ?)",
                    (inviter["id"], new_account_id, _hash_identifier(request.remote_addr or "")),
                )

            conn.commit()
            return jsonify({
                "ok": True,
                "account": {"username": username, "invite_code": new_code},
                "invited_by": inviter["username"] if inviter else "",
                "invite_status": "pending" if inviter else "",
                "delete_password_notice": "登录密码与工程删除密码用途不同，请在软件中单独设置并妥善保存工程删除密码。",
            })
        finally:
            conn.close()

    @app.post("/api/forgot-password")
    def forgot_password():
        """找回密码：按账号查绑定邮箱，发验证码到邮箱。"""
        if _rate_limited():
            return _error("操作过于频繁，请稍后再试", 429)
        data = request.get_json(silent=True) or {}
        account = str(data.get("account") or "").strip()
        if not (3 <= len(account) <= 64):
            return _error("请输入正确的账号")
        conn = db.connect()
        try:
            row = conn.execute(
                "SELECT id, username, email FROM accounts WHERE username = ?", (account,)
            ).fetchone()
        finally:
            conn.close()
        if not row:
            return _error("账号不存在")
        email = str(row["email"] or "").strip()
        if not email:
            return _error("该账号未绑定邮箱，无法通过邮箱找回。请联系管理员重置密码")
        code = str(random.randint(100000, 999999))
        _save_code(f"reset:{account}", code)
        try:
            from . import mailer
            mailer.send_code_email(email, code)
        except ValueError as exc:
            return _error(str(exc))
        except Exception as exc:
            return _error(f"邮件发送失败：{exc}")
        return jsonify({
            "ok": True,
            "email": email[:3] + "***" + email[email.find("@"):],
            "expires_in": CODE_TTL,
        })

    @app.post("/api/reset-password")
    def reset_password():
        """用验证码重置密码。"""
        if _rate_limited():
            return _error("操作过于频繁，请稍后再试", 429)
        data = request.get_json(silent=True) or {}
        account = str(data.get("account") or "").strip()
        code = str(data.get("code") or "").strip()
        new_password = str(data.get("new_password") or "")
        if len(new_password) < 8 or not re.search(r"[A-Za-z]", new_password) or not re.search(r"\d", new_password):
            return _error("新密码至少 8 位，并同时包含字母和数字")
        if not _consume_code(f"reset:{account}", code):
            return _error("验证码错误或已过期，请重新获取", 400)
        conn = db.connect()
        try:
            cur = conn.execute(
                "UPDATE accounts SET password_hash = ?, mobile_auth_version=COALESCE(mobile_auth_version,0)+1 "
                "WHERE username = ? AND status = 'active'",
                (generate_password_hash(new_password), account),
            )
            if cur.rowcount == 0:
                return _error("账号不存在或已停用")
            conn.execute(
                "INSERT INTO admin_account_access VALUES "
                "((SELECT id FROM accounts WHERE username=?),1) "
                "ON CONFLICT(account_id) DO UPDATE SET version=version+1",
                (account,),
            )
            conn.commit()
        finally:
            conn.close()
        return jsonify({"ok": True, "message": "密码已重置，请用新密码登录"})

    @app.post("/api/login")
    def login():
        if _rate_limited():
            return _error("操作过于频繁，请稍后再试", 429)
        data = request.get_json(silent=True) or {}
        username = str(data.get("username") or "").strip()
        password = str(data.get("password") or "")
        conn = db.connect()
        try:
            row = conn.execute(
                "SELECT * FROM accounts WHERE username = ?", (username,)
            ).fetchone()
        finally:
            conn.close()
        if not row or not check_password_hash(row["password_hash"], password):
            return _error("账号或密码错误", 401)
        account = dict(row)
        if account["status"] != "active":
            return _error("账号已被停用", 403)
        return jsonify(
            {
                "ok": True,
                "token": _token_for(account["id"]),
                "account": {
                    "id": int(account["id"]),
                    "username": account["username"],
                    "display_name": account["display_name"],
                    "role": account["role"],
                },
            }
        )

    @app.get("/api/invite-status")
    def invite_status():
        user = _require_user()
        if not user:
            return _error("未登录或登录已过期", 401)
        conn = db.connect()
        try:
            row = conn.execute(
                "SELECT invite_code, invite_reward_months FROM accounts WHERE id = ?",
                (user["id"],),
            ).fetchone()
            invite_code = row["invite_code"] if row else ""
            reward_months = int(row["invite_reward_months"] or 0) if row else 0
            count_row = conn.execute(
                "SELECT COUNT(*) AS registered_count, "
                "SUM(CASE WHEN status = 'qualified' THEN 1 ELSE 0 END) AS qualified_count, "
                "SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END) AS pending_count "
                "FROM invites WHERE inviter_id = ?", (user["id"],)
            ).fetchone()
            registered_count = int(count_row["registered_count"] or 0)
            qualified_count = int(count_row["qualified_count"] or 0)
            pending_count = int(count_row["pending_count"] or 0)
            invite_cfg = _product_config(conn).get("invite", {})
        finally:
            conn.close()
        milestone = max(1, int(invite_cfg.get("milestone") or 10))
        next_milestone = milestone - (qualified_count % milestone)
        return jsonify({
            "ok": True,
            "invite_code": invite_code,
            "registered_count": registered_count,
            "qualified_count": qualified_count,
            "pending_count": pending_count,
            "reward_months": reward_months,
            "next_milestone": next_milestone,  # 还差几人到下一个里程碑
            "milestone": milestone,
            "reward_days": int(invite_cfg.get("reward_days") or 30),
            "qualification": "注册并首次登录软件，且使用未重复的设备",
        })

    @app.get("/api/check-update")
    def check_update():
        current = str(request.args.get("current") or "").strip()
        version_file = config.DATA_DIR / "version.json"
        info = {}
        if version_file.exists():
            try:
                import json as _json

                info = _json.loads(version_file.read_text(encoding="utf-8"))
            except Exception:
                info = {}
        latest = str(info.get("version") or "")
        has_update = bool(latest and _version_key(latest) > _version_key(current))
        changelog = info.get("changelog") or []
        if not changelog and info.get("note"):
            changelog = [str(info.get("note"))]
        return jsonify({
            "ok": True,
            "latest_version": latest,
            "changelog": changelog,
            "fixes": info.get("fixes") or [],
            "download_url": info.get("download_url") or info.get("url") or "",
            "sha256": str(info.get("sha256") or ""),
            "size": int(info.get("size") or 0),
            "has_update": has_update,
            "mandatory": bool(info.get("mandatory", True)) if has_update else False,
        })

    @app.post("/api/admin/version")
    def admin_version():
        if not _require_admin():
            return _error("需要管理员权限", 403)
        data = request.get_json(silent=True) or {}
        version = str(data.get("version") or "").strip()
        if not version:
            return _error("缺少版本号")
        info = {
            "version": version,
            "changelog": [str(x) for x in (data.get("changelog") or [])],
            "fixes": [str(x) for x in (data.get("fixes") or [])],
            "download_url": str(data.get("download_url") or "").strip(),
            "sha256": str(data.get("sha256") or "").strip().lower(),
            "size": max(0, int(data.get("size") or 0)),
            "mandatory": bool(data.get("mandatory", True)),
        }
        config.DATA_DIR.mkdir(parents=True, exist_ok=True)
        import json as _json

        (config.DATA_DIR / "version.json").write_text(
            _json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return jsonify({"ok": True, "info": info})

    @app.get("/download/update/<path:filename>")
    def download_update(filename):
        updates_dir = config.DATA_DIR / "updates"
        return send_from_directory(updates_dir, filename, as_attachment=True)

    @app.get("/api/me")
    def me():
        user = _require_user()
        if not user:
            return _error("未登录或登录已过期", 401)
        return jsonify(
            {
                "ok": True,
                "account": {
                    "id": int(user["id"]),
                    "username": user["username"],
                    "display_name": user["display_name"],
                    "role": user["role"],
                },
                "license": _license_status_for(user),
            }
        )

    @app.post("/api/activate")
    def activate():
        user = _require_user()
        if not user:
            return _error("未登录或登录已过期", 401)
        if user.get("_token_scope") not in {"legacy", "desktop"}:
            return _error("当前令牌不能激活电脑", 403)
        data = request.get_json(silent=True) or {}
        machine_id = str(data.get("machine_id") or "").strip().upper()
        if not machine_id:
            return _error("缺少机器 ID")

        conn = db.connect()
        try:
            lic = _account_license(conn, user["id"])
            is_member = _has_active_membership(conn, user["id"])

            # 免费版账号（无授权/到期）也能激活绑定本机，走免费版限制；会员才签发授权码
            machine_limit = int(lic["machine_limit"] or config.DEFAULT_MACHINE_LIMIT) if lic else config.DEFAULT_MACHINE_LIMIT
            bound = conn.execute(
                "SELECT id FROM machines WHERE account_id = ? AND machine_id = ?",
                (user["id"], machine_id),
            ).fetchone()
            if bound:
                conn.execute(
                    "UPDATE machines SET last_seen = ?, active = 1 WHERE id = ?",
                    (_now(), bound["id"]),
                )
            else:
                count = _machine_count(conn, user["id"])
                if count >= machine_limit:
                    return _error(
                        f"本账号已绑定 {count} 台电脑，达到上限 {machine_limit} 台，"
                        "请联系管理员解绑或升级",
                        403,
                    )
                conn.execute(
                    "INSERT INTO machines (account_id, machine_id, bound_at, last_seen) "
                    "VALUES (?, ?, ?, ?)",
                    (user["id"], machine_id, _now(), _now()),
                )
            _qualify_invite(conn, user["id"], machine_id)
            conn.commit()
            code = _sign_for(user, machine_id, lic) if is_member else ""
            return jsonify(
                {
                    "ok": True,
                    "license_code": code,
                    "desktop_sync_token": _token_for(
                        user["id"], scope="desktop_sync", machine_id=machine_id
                    ),
                    "is_member": is_member,
                    "license": _license_status_for(user, machine_id),
                }
            )
        finally:
            conn.close()

    # ------------------------------------------------------------ 管理后台

    @app.get("/api/admin/accounts")
    def admin_accounts():
        if not _require_admin():
            return _error("需要管理员权限", 403)
        conn = db.connect()
        try:
            rows = conn.execute("SELECT * FROM accounts ORDER BY id").fetchall()
            result = []
            for row in rows:
                account = dict(row)
                account.pop("password_hash", None)
                audit = conn.execute("SELECT status,note,created_at FROM admin_account_audit WHERE account_id=? ORDER BY id DESC LIMIT 1", (account["id"],)).fetchone()
                account["last_status_change"] = dict(audit) if audit else None
                # 邀请关系：谁通过该账号邀请码注册的（被邀请人列表）
                invitees = conn.execute(
                    "SELECT a.username, i.status, i.qualified_at FROM invites i JOIN accounts a ON a.id = i.invitee_account_id "
                    "WHERE i.inviter_id = ? ORDER BY i.created_at",
                    (account["id"],),
                ).fetchall()
                invitee_items = [dict(r) for r in invitees]
                # 该账号是被谁邀请的
                inviter_name = ""
                if account.get("inviter_id"):
                    inv_row = conn.execute(
                        "SELECT username FROM accounts WHERE id = ?", (account["inviter_id"],)
                    ).fetchone()
                    if inv_row:
                        inviter_name = inv_row["username"]
                result.append(
                    {
                        "account": account,
                        "license": _license_status_for(account),
                        "invite_code": account.get("invite_code", ""),
                        "invitees": invitee_items,
                        "invited_by": inviter_name,
                        "invite_count": len(invitee_items),
                        "invite_qualified_count": sum(1 for item in invitee_items if item.get("status") == "qualified"),
                    }
                )
            return jsonify({"ok": True, "accounts": result})
        finally:
            conn.close()

    @app.post("/api/admin/product-config")
    def admin_product_config():
        admin = _require_admin()
        if not admin:
            return _error("需要管理员权限", 403)
        data = request.get_json(silent=True) or {}
        if not isinstance(data, dict):
            return _error("配置格式不正确")
        product = _save_product_config(data.get("product") or data, admin["id"])
        return jsonify({"ok": True, "product": product})

    @app.get("/api/admin/errors")
    def admin_errors():
        if not _require_admin():
            return _error("需要管理员权限", 403)
        try:
            limit = max(1, min(200, int(request.args.get("limit") or 100)))
        except (TypeError, ValueError):
            limit = 100
        resolved = str(request.args.get("resolved") or "").strip()
        query = str(request.args.get("q") or "").strip()[:100]
        clauses = []
        params = []
        if resolved in {"0", "1"}:
            clauses.append("e.resolved = ?")
            params.append(int(resolved))
        if query:
            clauses.append("(e.message LIKE ? OR e.error_type LIKE ? OR e.source LIKE ? OR a.username LIKE ?)")
            like = f"%{query}%"
            params.extend([like, like, like, like])
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        conn = db.connect()
        try:
            rows = conn.execute(
                "SELECT e.*, COALESCE(a.username, '') AS username FROM client_error_logs e "
                "LEFT JOIN accounts a ON a.id = e.account_id" + where +
                " ORDER BY e.id DESC LIMIT ?",
                (*params, limit),
            ).fetchall()
            errors = []
            for row in rows:
                item = dict(row)
                try:
                    item["context"] = json.loads(item.pop("context_json") or "{}")
                except (TypeError, ValueError):
                    item["context"] = {}
                if item.get("machine_id"):
                    item["machine_id"] = str(item["machine_id"])[:12]
                item.pop("request_ip", None)
                errors.append(item)
            summary = conn.execute(
                "SELECT COUNT(*) AS total, "
                "SUM(CASE WHEN resolved = 0 THEN 1 ELSE 0 END) AS unresolved, "
                "SUM(CASE WHEN severity = 'critical' AND resolved = 0 THEN 1 ELSE 0 END) AS critical "
                "FROM client_error_logs"
            ).fetchone()
            return jsonify({"ok": True, "errors": errors, "summary": dict(summary)})
        finally:
            conn.close()

    @app.post("/api/admin/errors/<int:error_id>/resolve")
    def admin_resolve_error(error_id):
        if not _require_admin():
            return _error("需要管理员权限", 403)
        data = request.get_json(silent=True) or {}
        resolved = 1 if data.get("resolved", True) else 0
        note = _redact_text(data.get("note"), 1000)
        conn = db.connect()
        try:
            cur = conn.execute(
                "UPDATE client_error_logs SET resolved = ?, resolved_at = ?, resolution_note = ? "
                "WHERE id = ?",
                (resolved, _now() if resolved else "", note, error_id),
            )
            conn.commit()
            if cur.rowcount == 0:
                return _error("错误记录不存在", 404)
            return jsonify({"ok": True})
        finally:
            conn.close()

    @app.post("/api/admin/license")
    def admin_license():
        if not _require_admin():
            return _error("需要管理员权限", 403)
        data = request.get_json(silent=True) or {}
        account_id = int(data.get("account_id") or 0)
        license_type = str(data.get("license_type") or "term").strip().lower()
        if license_type not in {"term", "lifetime"}:
            return _error("授权类型无效")
        valid_days = max(0, int(data.get("valid_days") or 0))
        machine_limit = max(1, int(data.get("machine_limit") or config.DEFAULT_MACHINE_LIMIT))
        conn = db.connect()
        try:
            account = conn.execute(
                "SELECT * FROM accounts WHERE id = ?", (account_id,)
            ).fetchone()
            if not account:
                return _error("账号不存在", 404)
            issued_at = _now()
            expires_at = ""
            if license_type == "term" and valid_days > 0:
                expires_at = (
                    datetime.now(timezone.utc) + timedelta(days=valid_days)
                ).strftime("%Y-%m-%dT%H:%M:%SZ")
            existing = _account_license(conn, account_id)
            if existing:
                conn.execute(
                    "UPDATE licenses SET license_type = ?, valid_days = ?, "
                    "machine_limit = ?, issued_at = ?, expires_at = ?, active = 1 "
                    "WHERE id = ?",
                    (license_type, valid_days, machine_limit, issued_at, expires_at, existing["id"]),
                )
            else:
                conn.execute(
                    "INSERT INTO licenses (account_id, license_type, valid_days, "
                    "machine_limit, issued_at, expires_at, active) "
                    "VALUES (?, ?, ?, ?, ?, ?, 1)",
                    (account_id, license_type, valid_days, machine_limit, issued_at, expires_at),
                )
            conn.commit()
            return jsonify(
                {
                    "ok": True,
                    "license": _license_status_for(dict(account)),
                }
            )
        finally:
            conn.close()

    @app.post("/api/admin/revoke")
    def admin_revoke():
        if not _require_admin():
            return _error("需要管理员权限", 403)
        data = request.get_json(silent=True) or {}
        account_id = int(data.get("account_id") or 0)
        conn = db.connect()
        try:
            conn.execute(
                "UPDATE licenses SET active = 0 WHERE account_id = ?", (account_id,)
            )
            conn.execute(
                "UPDATE machines SET active = 0 WHERE account_id = ?", (account_id,)
            )
            conn.commit()
            return jsonify({"ok": True})
        finally:
            conn.close()

    @app.post("/api/admin/unbind")
    def admin_unbind():
        if not _require_admin():
            return _error("需要管理员权限", 403)
        data = request.get_json(silent=True) or {}
        account_id = int(data.get("account_id") or 0)
        machine_id = str(data.get("machine_id") or "").strip().upper()
        conn = db.connect()
        try:
            conn.execute(
                "UPDATE machines SET active = 0 "
                "WHERE account_id = ? AND machine_id = ?",
                (account_id, machine_id),
            )
            conn.commit()
            return jsonify({"ok": True})
        finally:
            conn.close()

    # ------------------------------------------------------------ 云预览（公网查看）

    @app.post("/api/cloud/sync")
    def cloud_sync():
        """客户端推送缩略图+编号（登录后按账号隔离存储）。"""
        user = _require_user()
        if not user:
            return _error("未登录或登录已过期", 401)
        if user.get("_token_scope") == "desktop_sync":
            return _error("电脑同步令牌仅能访问 /api/desktop/v1", 403)
        data = request.get_json(silent=True) or {}
        projects = data.get("projects") if isinstance(data.get("projects"), list) else []
        cloud_cfg = _product_config().get("cloud_preview", {})
        max_projects = int(cloud_cfg.get("max_projects_per_sync") or 200)
        max_thumbs = int(cloud_cfg.get("max_thumbs_per_project") or 240)
        max_thumb_b64 = int(cloud_cfg.get("max_thumb_b64") or 600000)
        if len(projects) > max_projects:
            return _error("单次同步项目数超限")
        conn = db.connect()
        try:
            if not _cloud_access_allowed(conn, user["id"]):
                return _error("当前账号未开通云预览权益", 403)
            for proj in projects:
                code = str(proj.get("project_code") or "").strip()
                if not code:
                    continue
                # upsert 项目
                exists = conn.execute(
                    "SELECT id FROM cloud_projects WHERE account_id = ? AND project_code = ?",
                    (user["id"], code),
                ).fetchone()
                if exists:
                    proj_id = exists["id"]
                    conn.execute(
                        "UPDATE cloud_projects SET project_name = ?, unit_name = ?, "
                        "part_name = ?, thumb_count = ?, synced_at = ? WHERE id = ?",
                        (str(proj.get("project_name") or "")[:200],
                         str(proj.get("unit_name") or "")[:200],
                         str(proj.get("part_name") or "")[:200],
                         int(proj.get("thumb_count") or 0), _now(), proj_id),
                    )
                else:
                    cur = conn.execute(
                        "INSERT INTO cloud_projects (account_id, project_code, project_name, "
                        "unit_name, part_name, thumb_count, synced_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (user["id"], code, str(proj.get("project_name") or "")[:200],
                         str(proj.get("unit_name") or "")[:200],
                         str(proj.get("part_name") or "")[:200],
                         int(proj.get("thumb_count") or 0), _now()),
                    )
                    proj_id = cur.lastrowid
                # 缩略图增量同步（photo_name + 模糊缩略图 base64）
                thumbs = proj.get("thumbs")
                if isinstance(thumbs, list):
                    synced_names = []
                    for idx, thumb in enumerate(thumbs[:max_thumbs]):
                        name = str(thumb.get("photo_name") or "").strip()
                        b64 = str(thumb.get("thumb_b64") or "").strip()
                        if not name or len(name) > 260 or not _valid_thumbnail_b64(b64, max_thumb_b64):
                            continue
                        synced_names.append(name)
                        texists = conn.execute(
                            "SELECT id FROM cloud_thumbs WHERE project_id = ? AND photo_name = ?",
                            (proj_id, name),
                        ).fetchone()
                        if texists:
                            conn.execute(
                                "UPDATE cloud_thumbs SET thumb_b64 = ?, order_index = ?, synced_at = ? WHERE id = ?",
                                (b64, idx, _now(), texists["id"]),
                            )
                        else:
                            conn.execute(
                                "INSERT INTO cloud_thumbs (project_id, photo_name, thumb_b64, order_index, synced_at) "
                                "VALUES (?, ?, ?, ?, ?)",
                                (proj_id, name, b64, idx, _now()),
                            )
                    if synced_names:
                        placeholders = ",".join("?" for _ in synced_names)
                        conn.execute(
                            f"DELETE FROM cloud_thumbs WHERE project_id = ? AND photo_name NOT IN ({placeholders})",
                            (proj_id, *synced_names),
                        )
                    else:
                        conn.execute("DELETE FROM cloud_thumbs WHERE project_id = ?", (proj_id,))
                    conn.execute(
                        "UPDATE cloud_projects SET thumb_count = ? WHERE id = ?",
                        (len(synced_names), proj_id),
                    )
            conn.commit()
            return jsonify({
                "ok": True,
                "limits": {
                    "max_projects": max_projects,
                    "max_thumbs_per_project": max_thumbs,
                    "max_thumb_b64": max_thumb_b64,
                },
            })
        finally:
            conn.close()

    @app.get("/api/cloud/projects")
    def cloud_projects():
        """当前账号的项目列表（编号+名称+缩略图数）。"""
        user = _require_user()
        if not user:
            return _error("未登录或登录已过期", 401)
        conn = db.connect()
        try:
            if not _cloud_access_allowed(conn, user["id"]):
                return _error("当前账号未开通云预览权益", 403)
            rows = conn.execute(
                "SELECT id, project_code, project_name, unit_name, part_name, thumb_count, synced_at "
                "FROM cloud_projects WHERE account_id = ? ORDER BY project_code",
                (user["id"],),
            ).fetchall()
            return jsonify({
                "ok": True,
                "projects": [dict(r) for r in rows],
            })
        finally:
            conn.close()

    @app.get("/api/cloud/thumbs")
    def cloud_thumbs():
        """当前账号某项目的缩略图列表（模糊图 base64 + 照片名）。"""
        user = _require_user()
        if not user:
            return _error("未登录或登录已过期", 401)
        project_id = int(request.args.get("project_id") or 0)
        conn = db.connect()
        try:
            if not _cloud_access_allowed(conn, user["id"]):
                return _error("当前账号未开通云预览权益", 403)
            owns = conn.execute(
                "SELECT id FROM cloud_projects WHERE id = ? AND account_id = ?",
                (project_id, user["id"]),
            ).fetchone()
            if not owns:
                return _error("项目不存在", 404)
            thumbs = conn.execute(
                "SELECT photo_name, thumb_b64, order_index FROM cloud_thumbs "
                "WHERE project_id = ? ORDER BY order_index, id",
                (project_id,),
            ).fetchall()
            return jsonify({
                "ok": True,
                "thumbs": [dict(t) for t in thumbs],
            })
        finally:
            conn.close()

    @app.post("/api/cloud/clear")
    def cloud_clear():
        """客户端可选：清除某个项目的云预览（保留编号，清缩略图）。"""
        user = _require_user()
        if not user:
            return _error("未登录或登录已过期", 401)
        if user.get("_token_scope") == "desktop_sync":
            return _error("电脑同步令牌仅能访问 /api/desktop/v1", 403)
        data = request.get_json(silent=True) or {}
        project_id = int(data.get("project_id") or 0)
        conn = db.connect()
        try:
            if not _cloud_access_allowed(conn, user["id"]):
                return _error("当前账号未开通云预览权益", 403)
            conn.execute(
                "DELETE FROM cloud_thumbs WHERE project_id = ? AND project_id IN "
                "(SELECT id FROM cloud_projects WHERE id = ? AND account_id = ?)",
                (project_id, project_id, user["id"]),
            )
            conn.execute(
                "UPDATE cloud_projects SET thumb_count = 0 WHERE id = ? AND account_id = ?",
                (project_id, user["id"]),
            )
            conn.commit()
            return jsonify({"ok": True})
        finally:
            conn.close()

    # 移动端与桌面同步使用独立蓝图，只复用现有账号令牌。新表、新路由均为
    # additive，不改变旧版桌面客户端依赖的任何接口。
    from .mobile_api import register_mobile_api

    register_mobile_api(app, _require_user, _token_for, _now, _rate_limited)

    return app


def _ensure_admin(username: str, password: str) -> None:
    conn = db.connect()
    try:
        exists = conn.execute(
            "SELECT 1 FROM accounts WHERE username = ?", (username,)
        ).fetchone()
        if not exists:
            conn.execute(
                "INSERT INTO accounts (username, password_hash, display_name, role, status) "
                "VALUES (?, ?, ?, 'admin', 'active')",
                (username, generate_password_hash(password), "管理员"),
            )
            conn.commit()
            # Windows CI and legacy consoles may still default to cp1252. Keep
            # startup logging ASCII-only so creating an admin can never abort
            # an otherwise valid server boot because of console encoding.
            print(f"[OK] Admin account created: {ascii(username)}")
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="账号与授权中心")
    parser.add_argument("--host", default=os.environ.get("ALBUM_SERVER_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("ALBUM_SERVER_PORT", "5000")))
    sub = parser.add_subparsers(dest="cmd")
    p_admin = sub.add_parser("create-admin", help="创建管理员账号")
    p_admin.add_argument("--username", required=True)
    p_admin.add_argument("--password", required=True)
    args = parser.parse_args()
    if args.cmd == "create-admin":
        db.init_db()
        _ensure_admin(args.username, args.password)
        return
    app = create_app()
    app.run(host=args.host, port=args.port, debug=False)


if __name__ == "__main__":
    main()
