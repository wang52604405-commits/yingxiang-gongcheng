# -*- coding: utf-8 -*-
"""版本号递增脚本：自动生成下一个版本号，并同步到三处代码。

版本格式：A{8位日期}-{主}.{子}，如 A20260808-2.14。
递增规则：子版本 +1；日期取当天（跨天自动用新日期）。

用法：
  python bump_version.py           # 生成并写入，打印新版本号
  python bump_version.py --print   # 只打印不改写（用于 dry-run）
"""

from __future__ import annotations

import datetime
import os
import re
import sys
from pathlib import Path

USE = Path(__file__).resolve().parent

DESKTOP = USE / "desktop_launcher.py"
CLOUD = USE / "cloud_client.py"
INSTALLER = USE / "installer_win10.py"
ISS = USE / "安装脚本.iss"
ASSETS = USE / "assets"
INDEX_HTML = USE / "templates" / "index.html"
ASSET_RE = re.compile(r"app-(A\d{8}-\d+\.\d+)\.(css|js)")

SSH_KEY = Path(os.environ.get(
    "ALBUM_SSH_KEY",
    USE / "服务器访问-工程影像管理平台" / "server_key",
))
SERVER_HOST = os.environ.get("ALBUM_SERVER_HOST", "root@47.95.221.66")
REMOTE_VERSION_JSON = "/var/www/updates/version.json"

VER_RE = re.compile(r"A(\d{8})-(\d+)\.(\d+)")


def read_remote_version() -> str:
    """从服务器 version.json 读线上版本；失败返回空串。"""
    try:
        import json
        import subprocess
        cmd = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8",
               "-i", str(SSH_KEY), SERVER_HOST,
               "cat", REMOTE_VERSION_JSON]
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", timeout=20)
        if r.returncode == 0:
            return json.loads(r.stdout).get("version", "")
    except Exception:
        pass
    return ""


def read_current_version() -> str:
    """优先用服务器线上版本（保证每次 push 单调递增）；
    服务器不可达时退回本机 desktop_launcher.py。"""
    remote = read_remote_version()
    if remote:
        return remote
    text = DESKTOP.read_text(encoding="utf-8")
    m = VER_RE.search(text)
    if not m:
        raise SystemExit(f"无法从 {DESKTOP.name} 解析版本号")
    return m.group(0)


def next_version(current: str) -> str:
    """A{今天}-{主}.{子+1}。"""
    m = VER_RE.fullmatch(current)
    if not m:
        raise SystemExit(f"非法版本号: {current!r}")
    date_part, major, minor = m.groups()
    today = datetime.date.today().strftime("%Y%m%d")
    return f"A{today}-{major}.{int(minor) + 1}"


def _replace_version(text: str, pattern: str, new_ver: str, label: str) -> str:
    """替换版本号；若已是新版本则原样返回，未匹配才报错。"""
    replaced = re.sub(pattern, new_ver, text)
    if replaced == text and new_ver not in text:
        raise SystemExit(f"{label} 未匹配到版本行（且不含 {new_ver}）")
    return replaced


def _sync_asset_fingerprint(new_ver: str) -> None:
    """unify 前端资源文件名与 index.html 引用到 new_ver，保证缓存指纹随版本漂移。

    assets 目录内可能有多个历史指纹文件，统一只保留当前 new_ver 一份，
    并把 index.html 引用改到新指纹，避免旧指纹被浏览器长期缓存而加载旧代码。
    """
    keep = f"app-{new_ver}"
    # 1) 把当前可用的源码 .js/.css 重命名到 new_ver（若已是即跳过）
    for ext in (".js", ".css"):
        src = next((f for f in ASSETS.glob(f"app-A*.{ext}") if ASSET_RE.search(f.name)), None)
        if src and ASSET_RE.search(src.name).group(1) != new_ver:
            src.rename(ASSETS / f"{keep}{ext}")
        body = ASSETS / f"{keep}{ext}"
        if body.is_file():
            gz = ASSETS / f"{body.name}.gz"
            if not gz.exists():
                import gzip as _gz
                with _gz.open(gz, "wb", compresslevel=6) as g:
                    g.write(body.read_bytes())
    # 2) 删除所有其它旧指纹文件（.js/.css/.gz），只保留 current
    for f in (
        list(ASSETS.glob("app-A*.js"))
        + list(ASSETS.glob("app-A*.js.gz"))
        + list(ASSETS.glob("app-A*.css"))
        + list(ASSETS.glob("app-A*.css.gz"))
    ):
        m = ASSET_RE.search(f.name)
        if m and m.group(1) != new_ver:
            try:
                f.unlink()
            except FileNotFoundError:
                continue


def write_version(new_ver: str) -> None:
    # desktop_launcher.py: 整行替换 APP_VERSION = "A..."
    dt = DESKTOP.read_text(encoding="utf-8")
    DESKTOP.write_text(
        _replace_version(dt, r'APP_VERSION = "A\d{8}-\d+\.\d+"',
                         f'APP_VERSION = "{new_ver}"', DESKTOP.name),
        encoding="utf-8")

    # cloud_client.py: 整行替换 APP_VERSION = "A..."（保留行尾注释）
    cc = CLOUD.read_text(encoding="utf-8")
    CLOUD.write_text(
        _replace_version(cc, r'APP_VERSION = "A\d{8}-\d+\.\d+"',
                         f'APP_VERSION = "{new_ver}"', CLOUD.name),
        encoding="utf-8")

    # installer_win10.py: 整行替换 APP_VERSION = "A..."
    ins = INSTALLER.read_text(encoding="utf-8")
    INSTALLER.write_text(
        _replace_version(ins, r'APP_VERSION = "A\d{8}-\d+\.\d+"',
                         f'APP_VERSION = "{new_ver}"', INSTALLER.name),
        encoding="utf-8")

    # 安装脚本.iss: 三处（AppVersion / AppVerName / 注册表 Version）
    iss = ISS.read_text(encoding="utf-8")
    iss = _replace_version(iss, r'AppVersion=A\d{8}-\d+\.\d+',
                           f"AppVersion={new_ver}", ISS.name)
    iss = _replace_version(iss, r'AppVerName=工程影像管理平台 A\d{8}-\d+\.\d+',
                           f"AppVerName=工程影像管理平台 {new_ver}", ISS.name)
    iss = _replace_version(iss, r'ValueName: "Version"; ValueData: "A\d{8}-\d+\.\d+"',
                           f'ValueName: "Version"; ValueData: "{new_ver}"', ISS.name)
    ISS.write_text(iss, encoding="utf-8")

    # 前端 assets 指纹 + index.html 引用
    _sync_asset_fingerprint(new_ver)
    html = INDEX_HTML.read_text(encoding="utf-8")
    html = re.sub(ASSET_RE, lambda m: f"app-{new_ver}." + m.group(2), html)
    INDEX_HTML.write_text(html, encoding="utf-8")


def main() -> int:
    only_print = "--print" in sys.argv
    current = read_current_version()
    new_ver = next_version(current)
    print(f"当前版本: {current}")
    print(f"新版本  : {new_ver}")
    if not only_print:
        write_version(new_ver)
        print("已写入 desktop_launcher.py / cloud_client.py / 安装脚本.iss")
    return 0


if __name__ == "__main__":
    sys.exit(main())
