"""桌面端 HTTPS 证书链兼容层。

Windows 客户电脑可能安装了单位代理或安全软件的根证书。嵌入式 Python
若只使用自身的 CA 包，便会错误地把这类已经受 Windows 信任的证书判为
不可信。这里优先使用 Windows 原生证书库，仍然严格校验证书、主机名和
吊销状态；任何情况下都不允许退化为“忽略证书错误”。
"""

from __future__ import annotations

import ssl
import urllib.request

try:  # 打包时作为正式依赖一并带入；开发环境缺失时安全退回。
    import truststore as _truststore
except ImportError:  # pragma: no cover - 取决于开发环境依赖是否已安装
    _truststore = None

try:  # 公开 CA 的补充兜底，避免旧系统漏掉近年的根证书。
    import certifi as _certifi
except ImportError:  # pragma: no cover - 取决于开发环境依赖是否已安装
    _certifi = None


def trusted_ssl_context() -> ssl.SSLContext:
    """返回严格验证的 TLS 上下文，优先采用操作系统证书库。"""
    if _truststore is not None:
        try:
            # truststore 0.10+ 在 Windows 通过 CryptoAPI 查询系统信任库。
            return _truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        except Exception:
            # 证书库组件故障时，继续使用公开根证书，而不是关闭校验。
            pass
    if _certifi is not None:
        try:
            return ssl.create_default_context(cafile=_certifi.where())
        except Exception:
            pass
    return ssl.create_default_context()


def build_secure_opener(*handlers):
    """构造使用严格 TLS 校验的 urllib opener。"""
    https_handler = urllib.request.HTTPSHandler(context=trusted_ssl_context())
    return urllib.request.build_opener(*handlers, https_handler)


def secure_urlopen(request, timeout=15):
    """发起经过 Windows 证书库验证的 HTTP(S) 请求。"""
    return build_secure_opener().open(request, timeout=timeout)
