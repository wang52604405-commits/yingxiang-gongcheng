# -*- coding: utf-8 -*-
"""一键出交付包：把最新的安装程序、签名用 exe、修复过的服务器代码打进纯净交付包 zip。

用法（由 build.bat 调用，也可单独跑）：
  python make_delivery.py
"""

from __future__ import annotations

import os
import hashlib
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

USE = Path(__file__).resolve().parent
DEST_ROOT = USE / "客户可发送安装包-Win10"
STAGING = Path(tempfile.mkdtemp(prefix="album_delivery_"))
INSTALLER = DEST_ROOT / "发给客户" / "安装程序.exe"
SERVER = USE / "server"
SIGNING_DIR = USE / "dist" / "工程影像管理平台"

# 纯净包内容：若存在历史交付包目录则复用；新环境可从零生成。
BASE = USE / "工程影像管理平台-正式版交付包"


def main() -> int:
    if not INSTALLER.exists():
        print(f"[ERR] 缺安装程序: {INSTALLER}")
        return 1

    # 1. 复制历史基础目录；首次构建时创建标准目录骨架。
    if BASE.exists():
        shutil.copytree(BASE, STAGING, dirs_exist_ok=True)
    for rel in (
        "1-安装包-发给客户",
        "2-代码签名/待签名-安装包内程序",
        "3-服务器部署/server/templates",
    ):
        (STAGING / rel).mkdir(parents=True, exist_ok=True)

    # 2. 更新安装程序
    target_installer = STAGING / "1-安装包-发给客户" / "安装程序.exe"
    shutil.copy2(INSTALLER, target_installer)

    # 3. 更新待签名程序（用最新构建的 exe）
    for name in ("工程影像管理平台.exe", "album_server.exe"):
        src = SIGNING_DIR / name
        if src.exists():
            dst = STAGING / "2-代码签名" / "待签名-安装包内程序" / name
            if dst.parent.exists():
                shutil.copy2(src, dst)

    # 4. 同步服务器代码，不复制数据库、缓存或任何凭据。
    server_target = STAGING / "3-服务器部署" / "server"
    shutil.copytree(
        SERVER,
        server_target,
        dirs_exist_ok=True,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "data", "*.db", "*.pem"),
    )

    installer_sha256 = hashlib.sha256(INSTALLER.read_bytes()).hexdigest()
    (STAGING / "版本与校验.txt").write_text(
        "工程影像管理平台交付包\n"
        f"安装程序 SHA256: {installer_sha256}\n"
        "说明：安装包、服务器代码和校验值均来自同一次构建。\n",
        encoding="utf-8",
    )

    # 5. 防私钥：彻底清除任何残留 pem / 授权工具目录
    for item in STAGING.rglob("*.pem"):
        item.unlink()
    tool_dir = STAGING / "4-授权工具-自己保留"
    if tool_dir.exists():
        shutil.rmtree(tool_dir, ignore_errors=True)

    # 6. 打 zip
    out = DEST_ROOT / "工程影像管理平台-正式版交付包-纯净版.zip"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for path in sorted(STAGING.rglob("*")):
            if path.is_file():
                z.write(path, path.relative_to(STAGING).as_posix())

    # 7. 校验无私钥
    with zipfile.ZipFile(out) as z:
        pems = [i.filename for i in z.infolist() if "pem" in i.filename.lower()]
    if pems:
        print(f"[ERR] 交付包仍含私钥: {pems}")
        shutil.rmtree(STAGING, ignore_errors=True)
        return 1

    shutil.rmtree(STAGING, ignore_errors=True)
    print(f"[OK] 纯净交付包已生成: {out}")
    print(f"[OK] 大小: {out.stat().st_size / 1024 / 1024:.1f} MB，不含私钥")
    return 0


if __name__ == "__main__":
    sys.exit(main())
