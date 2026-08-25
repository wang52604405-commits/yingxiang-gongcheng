# -*- coding: utf-8 -*-
"""服务器配置：全部支持环境变量覆盖，便于生产部署。"""

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

# 非敏感的运行实例标识，仅用来让自动化验收在任何写入前确认
# 它连接的确实是隔离 staging。正式环境默认值故意与 staging
# systemd unit 里的硬编码值不同。
SERVER_ENVIRONMENT = os.environ.get("ALBUM_SERVER_ENVIRONMENT", "production").strip().lower()
SERVER_INSTANCE_ID = os.environ.get("ALBUM_SERVER_INSTANCE_ID", "album-auth-production").strip()
if SERVER_ENVIRONMENT not in {"production", "staging", "development", "test"}:
    raise RuntimeError("ALBUM_SERVER_ENVIRONMENT 不在允许的环境标识中")
if not SERVER_INSTANCE_ID or len(SERVER_INSTANCE_ID) > 128 or not all(
    character.isalnum() or character in {"-", "_", "."}
    for character in SERVER_INSTANCE_ID
):
    raise RuntimeError("ALBUM_SERVER_INSTANCE_ID 必须是非敏感的安全实例名")

# 微信小程序登录。AppSecret 只允许通过环境变量注入；代码和数据库均不保存
# 临时 code 或明文密码。测试环境必须显式开启 mock，生产默认关闭。
WECHAT_APP_ID = os.environ.get("ALBUM_WECHAT_APP_ID", "").strip()
WECHAT_APP_SECRET = os.environ.get("ALBUM_WECHAT_APP_SECRET", "").strip()
WECHAT_BIND_TICKET_MAX_AGE = int(
    os.environ.get("ALBUM_WECHAT_BIND_TICKET_MAX_AGE", "600")
)
WECHAT_MOCK_ENABLED = os.environ.get("ALBUM_WECHAT_MOCK_ENABLED", "0").strip() == "1"

# 移动端对象存储。手机上传的是待电脑归档的原字节 JPEG/PNG；云端另生成
# 永久 JPEG 预览。原图只作短期中转，绝不通过移动端图库返回。
MOBILE_MAX_ORIGINAL_BYTES = 50 * 1024 * 1024
MOBILE_MAX_REQUEST_BYTES = MOBILE_MAX_ORIGINAL_BYTES + 1024 * 1024
MOBILE_UPLOAD_SPOOL_BYTES = 4 * 1024 * 1024
MOBILE_DIRECT_UPLOAD_MAX_BYTES = 10 * 1024 * 1024
MOBILE_CHUNK_BYTES = 4 * 1024 * 1024
MOBILE_CHUNK_TTL_SECONDS = max(
    3600, min(7 * 24 * 3600, int(os.environ.get("ALBUM_MOBILE_CHUNK_TTL_SECONDS", "86400")))
)
MOBILE_CHUNK_MAX_ACTIVE_PER_ACCOUNT = max(
    1, min(32, int(os.environ.get("ALBUM_MOBILE_CHUNK_MAX_ACTIVE_PER_ACCOUNT", "8")))
)
MOBILE_CHUNK_MAX_ACTIVE_GLOBAL = max(
    8, min(512, int(os.environ.get("ALBUM_MOBILE_CHUNK_MAX_ACTIVE_GLOBAL", "64")))
)
MOBILE_CHUNK_MAX_RESERVED_PER_ACCOUNT = max(
    MOBILE_MAX_ORIGINAL_BYTES,
    int(os.environ.get("ALBUM_MOBILE_CHUNK_MAX_RESERVED_PER_ACCOUNT", str(200 * 1024 * 1024))),
)
MOBILE_CHUNK_MAX_RESERVED_GLOBAL = max(
    MOBILE_CHUNK_MAX_RESERVED_PER_ACCOUNT,
    int(os.environ.get("ALBUM_MOBILE_CHUNK_MAX_RESERVED_GLOBAL", str(2 * 1024 * 1024 * 1024))),
)
MOBILE_ANALYSIS_STALE_SECONDS = max(
    60,
    min(
        3600,
        int(os.environ.get("ALBUM_MOBILE_ANALYSIS_STALE_SECONDS", "300")),
    ),
)
MOBILE_MAX_ORIGINAL_PIXELS = max(
    1_000_000,
    min(80_000_000, int(os.environ.get("ALBUM_MOBILE_MAX_ORIGINAL_PIXELS", "60000000"))),
)
MOBILE_MAX_ORIGINAL_EDGE = max(
    1920,
    min(20_000, int(os.environ.get("ALBUM_MOBILE_MAX_ORIGINAL_EDGE", "12000"))),
)
MOBILE_PREVIEW_MAX_BYTES = 102400
MOBILE_PREVIEW_MAX_EDGE = 1920
# 兼容共享识别模块及旧调用点；该值现在只代表永久云预览，而非手机原图。
MOBILE_MAX_IMAGE_BYTES = MOBILE_PREVIEW_MAX_BYTES
MOBILE_MAX_IMAGE_EDGE = MOBILE_PREVIEW_MAX_EDGE
MOBILE_STORAGE_BACKEND = os.environ.get(
    "ALBUM_MOBILE_STORAGE_BACKEND", "local"
).strip().lower()
MOBILE_STORAGE_DIR = Path(
    os.environ.get("ALBUM_MOBILE_STORAGE_DIR", DATA_DIR / "mobile_objects")
)
MOBILE_CHUNK_DIR = Path(
    os.environ.get("ALBUM_MOBILE_CHUNK_DIR", DATA_DIR / "mobile_chunks")
)
MOBILE_DOWNLOAD_URL_TTL = max(
    60, min(3600, int(os.environ.get("ALBUM_MOBILE_DOWNLOAD_URL_TTL", "600")))
)
OSS_REGION = os.environ.get("ALBUM_OSS_REGION", "cn-beijing").strip()
OSS_BUCKET = os.environ.get("ALBUM_OSS_BUCKET", "").strip()
OSS_PREVIEW_BUCKET = os.environ.get("ALBUM_OSS_PREVIEW_BUCKET", OSS_BUCKET).strip()
OSS_ORIGINAL_BUCKET = os.environ.get("ALBUM_OSS_ORIGINAL_BUCKET", "").strip()
OSS_ENDPOINT = os.environ.get("ALBUM_OSS_ENDPOINT", "").strip()

APP_CODE = "HDYX"
DEFAULT_MACHINE_LIMIT = 3   # 每账号默认可绑定电脑数
OFFLINE_GRACE_DAYS = 7      # 客户端离线缓冲天数（客户端侧实现）

# 默认产品策略。管理员可在后台修改并写入 product_settings；客户端会缓存，
# 因此这些值既是首次部署默认值，也是服务器短暂不可达时的安全兜底。
DEFAULT_PRODUCT_CONFIG = {
    "config_version": 1,
    "pricing": {
        "monthly_price": 39,
        "lifetime_price": 399,
        "price_label": "原价",
    },
    "free": {
        "photo_limit": 300,
        "watermark_enabled": False,
        "upload_expiry_enabled": False,
    },
    "invite": {
        "enabled": True,
        "milestone": 10,
        "reward_days": 30,
        "qualification": "activated_unique_device",
    },
    "cloud_preview": {
        "enabled": True,
        "requires_member": False,
        "beta_free_access": True,
        "thumb_max_side": 720,
        "thumb_quality": 76,
        "max_thumbs_per_project": 240,
        "max_projects_per_sync": 200,
        "max_thumb_b64": 600000,
    },
    "logging": {
        "enabled": True,
        "max_message": 2000,
        "max_stack": 12000,
        "max_context": 8000,
        "retention_days": 90,
        "max_records": 5000,
    },
}

# 首次启动自动创建管理员（生产环境建议用 CLI 创建后清除环境变量）
ADMIN_USERNAME = os.environ.get("ALBUM_ADMIN_USER", "")
ADMIN_PASSWORD = os.environ.get("ALBUM_ADMIN_PASS", "")
