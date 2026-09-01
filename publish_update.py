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
import hashlib
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import build_all  # 复用 step1-4

SSH_KEY = Path(os.environ.get(
    "ALBUM_SSH_KEY",
    build_all.USE / "服务器访问-工程影像管理平台" / "server_key",
))
SERVER_HOST = os.environ.get("ALBUM_SERVER_HOST", "root@47.95.221.66")
REMOTE_UPDATES = "/var/www/updates"
# 官网下载目录与自动更新通道使用同一份正式安装包，避免下载页落后于软件更新。
REMOTE_SITE_DOWNLOAD = "/var/www/shuiliyingxiang/download"
# 远程更新文件固定使用 ASCII 名称，避免 Windows scp 与 Linux shell 的中文路径编码不一致。
REMOTE_EXE_NAME = "album-installer.exe"
PUBLIC_UPDATE_BASE = os.environ.get(
    "ALBUM_UPDATE_BASE", "https://api.shuiliyingxiang.cn/update"
).rstrip("/")

INSTALLER = build_all.INSTALLER  # 客户可发送安装包-Win10/发给客户/安装程序.exe

SSH_OPTIONS = [
    "-o", "BatchMode=yes",
    "-o", "ConnectTimeout=10",
    "-o", "ConnectionAttempts=3",
    "-o", "ServerAliveInterval=10",
    "-o", "ServerAliveCountMax=3",
]


def _is_transport_failure(result: subprocess.CompletedProcess) -> bool:
    return result.returncode == 255


def _run_with_transport_retry(
    cmd: list[str],
    *,
    timeout: int,
    attempts: int = 3,
) -> subprocess.CompletedProcess:
    """只对 SSH 传输层错误重试；远端业务命令失败立即返回。"""
    last_result = subprocess.CompletedProcess(cmd, 255, "", "transport unavailable")
    for attempt in range(1, attempts + 1):
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            result = subprocess.CompletedProcess(
                cmd,
                255,
                "",
                f"transport timed out after {timeout} seconds",
            )
        last_result = result
        if not _is_transport_failure(result) or attempt == attempts:
            return result
        delay = 2 ** attempt
        print(f"  ! SSH 网络中断，第 {attempt}/{attempts} 次，{delay} 秒后重试")
        time.sleep(delay)
    return last_result


def ssh_cmd(args: list[str], check=True) -> subprocess.CompletedProcess:
    """在本机执行 ssh 到服务器跑命令。"""
    cmd = ["ssh", *SSH_OPTIONS, "-i", str(SSH_KEY), SERVER_HOST, *args]
    result = _run_with_transport_retry(cmd, timeout=90)
    if check and result.returncode != 0:
        raise SystemExit(f"SSH 失败: {args}\n{result.stderr}")
    return result


def scp_upload(source: str | Path, destination: str) -> subprocess.CompletedProcess:
    """上传到远端临时文件；长安装包允许重试且绝不直接覆盖正式文件。"""
    cmd = [
        "scp",
        "-O",
        "-q",
        *SSH_OPTIONS,
        "-i", str(SSH_KEY),
        str(source),
        f"{SERVER_HOST}:{destination}",
    ]
    result = _run_with_transport_retry(cmd, timeout=1200)
    if result.returncode != 0:
        raise SystemExit(f"上传失败（已重试）：{result.stderr}")
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
    remote_tmp = f"{REMOTE_UPDATES}/.{REMOTE_EXE_NAME}.uploading"
    print(f"\n[上传] {INSTALLER.name} ({INSTALLER.stat().st_size/1024/1024:.1f} MB)")
    if DRY_RUN:
        print("[DRY_RUN] 跳过上传")
        return
    scp_upload(INSTALLER, remote_tmp)
    expected = hashlib.sha256(INSTALLER.read_bytes()).hexdigest()
    remote_hash = ssh_cmd(["sha256sum", remote_tmp]).stdout.split()[0].lower()
    if remote_hash != expected:
        ssh_cmd(["rm", "-f", remote_tmp], check=False)
        raise SystemExit("上传后的安装包 SHA-256 校验失败，已拒绝发布")
    ssh_cmd(["mv", remote_tmp, f"{REMOTE_UPDATES}/{REMOTE_EXE_NAME}"])
    print(f"[OK] 已上传到 {REMOTE_UPDATES}/{REMOTE_EXE_NAME}")


def sync_website_download() -> None:
    """把更新通道中的正式包同步到官网固定下载链接。"""
    remote_source = f"{REMOTE_UPDATES}/{REMOTE_EXE_NAME}"
    remote_target = f"{REMOTE_SITE_DOWNLOAD}/工程影像管理平台-安装程序.exe"
    if DRY_RUN:
        print(f"[DRY_RUN] 跳过官网同步: {remote_target}")
        return
    ssh_cmd(["install", "-d", REMOTE_SITE_DOWNLOAD])
    ssh_cmd(["cp", remote_source, remote_target])
    ssh_cmd(["chown", "www-data:www-data", remote_target])
    print(f"[OK] 官网下载链接已同步: {remote_target}")


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
        "url": f"{PUBLIC_UPDATE_BASE}/{REMOTE_EXE_NAME}",
        "download_url": f"{PUBLIC_UPDATE_BASE}/{REMOTE_EXE_NAME}",
        "note": note,
        "changelog": [item.strip() for item in note.splitlines() if item.strip()],
        "sha256": hashlib.sha256(INSTALLER.read_bytes()).hexdigest(),
        "size": INSTALLER.stat().st_size,
        # 更新从 A20260829-2.75 起统一由客户端红点提醒，用户下载后自行
        # 覆盖安装；发布清单绝不再把任何版本标记为强制自动安装。
        "mandatory": False,
        "manual_update_only": True,
        "auto_update_supported": False,
    }
    print(f"[version.json] 将更新为 {new_version}，note: {note!r}")
    if DRY_RUN:
        return
    import json as _json
    fd, tmp = tempfile.mkstemp(suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            _json.dump(payload, f, ensure_ascii=False, indent=2)
        # 备份旧 version.json，先上传临时文件再原子替换。
        ssh_cmd(["cp", f"{REMOTE_UPDATES}/version.json",
                 f"{REMOTE_UPDATES}/version.json.bak"], check=False)
        remote_tmp = f"{REMOTE_UPDATES}/.version.json.uploading"
        scp_upload(tmp, remote_tmp)
        ssh_cmd(["mv", remote_tmp, f"{REMOTE_UPDATES}/version.json"])
        ssh_cmd(["cp", f"{REMOTE_UPDATES}/version.json", "/opt/album-auth/data/version.json"])
    finally:
        os.unlink(tmp)
    print(f"[OK] version.json 已更新 -> {new_version}")


def verify_remote() -> None:
    """curl 服务器 version.json 验证。"""
    import json as _json
    try:
        result = subprocess.run(
            ["curl", "-s", "-m", "10", f"{PUBLIC_UPDATE_BASE}/version.json"],
            capture_output=True, text=True, encoding="utf-8")
        data = _json.loads(result.stdout)
        print("\n=== 服务器 version.json 当前内容 ===")
        print(_json.dumps(data, ensure_ascii=False, indent=2))
        print("=====================================")
    except Exception as exc:
        print(f"[!] 验证失败: {exc}")


def main() -> int:
    old_remote = current_remote_version()
    print(f"[信息] 服务器当前版本: {old_remote or '（无）'}")
    print(f"[信息] 本机构建版本: {_local_version()}")

    # 1-4 步构建。SKIP_BUILD=1 时跳过 PyInstaller+签名（deploy_prod.ps1 已构建 dist），
    # 但 Inno 仍要跑——把 dist 打成安装程序，产物在当前目录（可能是 checkout 的 _work）
    steps = [
        ("PyInstaller", build_all.step1_pyinstaller),
        ("防篡改签名", build_all.step2_manifest),
        ("Inno 安装包", build_all.step3_inno),
        ("验无私钥", build_all.step4_verify_no_key),
    ]
    if os.environ.get("SKIP_BUILD"):
        steps = steps[2:]  # 跳过 PyInstaller + 签名，保留 Inno 打安装包
    for name, fn in steps:
        print(f"\n[{name}] ...")
        if not fn():
            print(f"\n[BUILD FAILED] 步骤失败: {name}")
            return 1

    # Inno 生成后再校验安装程序存在
    if not INSTALLER.exists():
        print(f"[ERR] 安装程序未生成: {INSTALLER}")
        return 1

    # 上传前备份旧版
    backup = backup_remote_installer()
    if backup:
        print(f"[备份] 服务器旧安装包 -> {backup}")

    # 上传 + 更新 version.json
    upload_installer()
    sync_website_download()
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
