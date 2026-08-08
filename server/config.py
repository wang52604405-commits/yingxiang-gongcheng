# -*- coding: utf-8 -*-
"""服务器配置：全部支持环境变量覆盖，便于生产部署。
（自动部署验证标记 2）"""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("ALBUM_SERVER_DATA", BASE_DIR / "data"))
DB_PATH = Path(
    os.environ.get("ALBUM_SERVER_DB", DATA_DIR / "server.db")
)

# 授权私钥：只放在服务器上（生产环境建议 /etc/album-auth/private_key.pem，chmod 600）
PRIVATE_KEY_PATH = Path(
    os.environ.get("ALBUM_SERVER_PRIVATE_KEY", BASE_DIR / "private_key.pem")
)

# 会话令牌密钥（生产环境务必改成强随机值；占位值会被下面检查拦截）
_PLACEHOLDER_SECRETS = {"dev-only-secret-change-me", "请改成强随机字符串", "change-me"}
_SECRET_KEY = os.environ.get("ALBUM_SERVER_SECRET", "")


def _load_or_create_secret_key() -> str:
    """令牌密钥：优先环境变量，其次持久化随机值；占位/过短则直接拒绝启动，
    防止默认密钥被公开利用伪造管理员令牌。"""
    if _SECRET_KEY:
        if len(_SECRET_KEY) < 16 or _SECRET_KEY in _PLACEHOLDER_SECRETS:
            raise RuntimeError(
                "ALBUM_SERVER_SECRET 不可用（占位值或过短），请设置强随机密钥。"
                "生成命令：openssl rand -hex 32"
            )
        return _SECRET_KEY
    key_path = DATA_DIR / ".server_secret"
    try:
        if key_path.exists():
            secret = key_path.read_text(encoding="ascii").strip()
            if len(secret) >= 16 and secret not in _PLACEHOLDER_SECRETS:
                return secret
    except OSError:
        pass
    secret = os.urandom(32).hex()
    try:
        key_path.parent.mkdir(parents=True, exist_ok=True)
        key_path.write_text(secret, encoding="ascii")
    except OSError:
        pass
    return secret


SECRET_KEY = _load_or_create_secret_key()
TOKEN_MAX_AGE = 30 * 24 * 3600  # 令牌有效期 30 天

APP_CODE = "HDYX"
DEFAULT_MACHINE_LIMIT = 3   # 每账号默认可绑定电脑数
OFFLINE_GRACE_DAYS = 7      # 客户端离线缓冲天数（客户端侧实现）

# 首次启动自动创建管理员（生产环境建议用 CLI 创建后清除环境变量）
ADMIN_USERNAME = os.environ.get("ALBUM_ADMIN_USER", "")
ADMIN_PASSWORD = os.environ.get("ALBUM_ADMIN_PASS", "")
