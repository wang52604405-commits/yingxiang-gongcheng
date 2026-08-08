# -*- coding: utf-8 -*-
"""发布新版本到更新通道：构建安装包 -> 上传阿里云 -> 更新 version.json。

流程：
  1. 复用 build_all 前 4 步构建安装程序（PyInstaller -> 签名 -> Inno -> 验无私钥）
  2. scp 上传安装包到服务器 /var/www/updates/（上传前备份旧版）
  3. 更新服务器 version.json（version / url / note）

note（客户看到的更新说明）来源：
  - 环境变量 UPDATE_NOTE（GitHub Actions 传 git 提交信息）
  - 否则取 git log 最近一条提交信息

用法（在 E:\\use 目录，git 仓库内）：
  python publish_update.py
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import build_all  # 复用 step1-4

SSH_KEY = Path.home() / ".ssh" / "id_ed25519_album"
SERVER_HOST = "root@47.95.221.66"
REMOTE_UPDATES = "/var/www/updates"
REMOTE_EXE_NAME = "工程影像管理平台-安装程序.exe"

INSTALLER = build_all.INSTALLER  # 客户可发送安装包-Win10/发给客户/安装程序.exe


def ssh_cmd(args: list[str], check=True) -> subprocess.CompletedProcess:
    """在本机执行 ssh 到服务器跑命令。"""
    cmd = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8",
           "-i", str(SSH_KEY), SERVER_HOST, *args]
    result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    if check and result.returncode != 0:
        raise SystemExit(f"SSH 失败: {args}\n{result.stderr}")
    return result


def current_remote_version() -> str:
    """读服务器 version.json 的当前版本（失败返回空串）。"""
    try:
        r = ssh_cmd(["cat", f"{REMOTE_UPDATES}/version.json"], check=False)
        if r.returncode == 0:
            import json
            return json.loads(r.stdout).get("version", "")
    except Exception:
        pass
    return ""


def backup_remote_installer() -> str:
    """备份服务器旧安装包，返回备份文件名。"""
    old = f"{REMOTE_UPDATES}/{REMOTE_EXE_NAME}"
    r = ssh_cmd(["test", "-f", old], check=False)
    if r.returncode != 0:
        return ""
    backup = f"{old}.bak-{current_remote_version() or 'unknown'}"
    if DRY_RUN:
        return backup
    ssh_cmd(["cp", old, backup])
    return backup


DRY_RUN = os.environ.get("DRY_RUN") == "1"


def upload_installer() -> None:
    """scp 上传本地安装包到服务器（中文文件名）。"""
    cmd = ["scp", "-q", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8",
           "-i", str(SSH_KEY), str(INSTALLER),
           f"{SERVER_HOST}:{REMOTE_UPDATES}/{REMOTE_EXE_NAME}"]
    print(f"\n[上传] {INSTALLER.name} ({INSTALLER.stat().st_size/1024/1024:.1f} MB)")
    if DRY_RUN:
        print("[DRY_RUN] 跳过上传")
        return
    result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    if result.returncode != 0:
        raise SystemExit(f"上传失败: {result.stderr}")
    print(f"[OK] 已上传到 {REMOTE_UPDATES}/{REMOTE_EXE_NAME}")


def get_note() -> str:
    """取更新说明：环境变量 UPDATE_NOTE 优先，否则 git log 最近一条。"""
    note = os.environ.get("UPDATE_NOTE", "").strip()
    if note:
        return note
    try:
        result = subprocess.run(
            ["git", "log", "-1", "--format=%s"], capture_output=True, text=True,
            encoding="utf-8", cwd=build_all.USE)
        return result.stdout.strip() or "功能更新"
    except Exception:
        return "功能更新"


def write_remote_version(new_version: str, note: str) -> None:
    """用临时文件 + scp 覆盖服务器 version.json。"""
    payload = {
        "app": "工程影像管理平台",
        "version": new_version,
        "url": f"http://47.95.221.66/update/{REMOTE_EXE_NAME}",
        "note": note,
    }
    print(f"[version.json] 将更新为 {new_version}，note: {note!r}")
    if DRY_RUN:
        return
    import json as _json
    fd, tmp = tempfile.mkstemp(suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            _json.dump(payload, f, ensure_ascii=False, indent=2)
        # 备份旧 version.json
        ssh_cmd(["cp", f"{REMOTE_UPDATES}/version.json",
                 f"{REMOTE_UPDATES}/version.json.bak"], check=False)
        cmd = ["scp", "-q", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8",
               "-i", str(SSH_KEY), tmp,
               f"{SERVER_HOST}:{REMOTE_UPDATES}/version.json"]
        result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
        if result.returncode != 0:
            raise SystemExit(f"version.json 上传失败: {result.stderr}")
    finally:
        os.unlink(tmp)
    print(f"[OK] version.json 已更新 -> {new_version}")


def verify_remote() -> None:
    """curl 服务器 version.json 验证。"""
    import json as _json
    try:
        result = subprocess.run(
            ["curl", "-s", "-m", "10", "http://47.95.221.66/update/version.json"],
            capture_output=True, text=True, encoding="utf-8")
        data = _json.loads(result.stdout)
        print("\n=== 服务器 version.json 当前内容 ===")
        print(_json.dumps(data, ensure_ascii=False, indent=2))
        print("=====================================")
    except Exception as exc:
        print(f"[!] 验证失败: {exc}")


def main() -> int:
    if not INSTALLER.exists():
        print(f"[ERR] 缺安装程序: {INSTALLER}")
        return 1

    old_remote = current_remote_version()
    print(f"[信息] 服务器当前版本: {old_remote or '（无）'}")
    print(f"[信息] 本机构建版本: {_local_version()}")

    # 1-4 步构建。SKIP_BUILD=1 时跳过 PyInstaller（GitHub Actions 里 deploy_prod.ps1 已构建 dist）
    steps = [
        ("PyInstaller", build_all.step1_pyinstaller),
        ("防篡改签名", build_all.step2_manifest),
        ("Inno 安装包", build_all.step3_inno),
        ("验无私钥", build_all.step4_verify_no_key),
    ]
    if os.environ.get("SKIP_BUILD"):
        steps = steps[2:]  # 跳过 PyInstaller + 签名，直接用现成 dist 打安装包
    for name, fn in steps:
        print(f"\n[{name}] ...")
        if not fn():
            print(f"\n[BUILD FAILED] 步骤失败: {name}")
            return 1

    # 上传前备份旧版
    backup = backup_remote_installer()
    if backup:
        print(f"[备份] 服务器旧安装包 -> {backup}")

    # 上传 + 更新 version.json
    upload_installer()
    note = get_note()
    new_ver = _local_version()
    write_remote_version(new_ver, note)

    verify_remote()
    print("\n[完成] 新版本已发布。客户启动时将自动提示更新。")
    return 0


def _local_version() -> str:
    """从 desktop_launcher.py 读构建版本。"""
    import re as _re
    text = (build_all.USE / "desktop_launcher.py").read_text(encoding="utf-8")
    m = _re.search(r'APP_VERSION = "([^"]+)"', text)
    return m.group(1) if m else "unknown"


if __name__ == "__main__":
    sys.exit(main())
