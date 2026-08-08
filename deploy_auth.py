# -*- coding: utf-8 -*-
"""授权中心自动部署：上传 server/ 代码到阿里云并重启。

流程：
  1. scp 上传 server/ 的代码文件到 /opt/album-auth/server/
  2. 备份旧版（server/ 下被替换的文件）
  3. 重启 album-auth 服务
  4. 健康检查（/api/me 返回 401 即服务已起）

安全：不含私钥 / 邮箱授权码（服务器用 systemd 环境变量注入，
配置在 /etc/systemd/system/album-auth.service，不受本脚本影响）。
私钥由服务器 /etc/album-auth/private_key.pem 提供，本脚本不触碰。

用法：python deploy_auth.py
"""

from __future__ import annotations

import subprocess
import sys
import os
from pathlib import Path

REPO = Path(__file__).resolve().parent
SSH_KEY = Path(os.environ.get(
    "ALBUM_SSH_KEY",
    REPO / "服务器访问-工程影像管理平台" / "server_key",
))
SERVER_HOST = os.environ.get("ALBUM_SERVER_HOST", "root@47.95.221.66")
REMOTE_SERVER_DIR = "/opt/album-auth/server"

# 要上传的代码文件（不含私钥/敏感文件）
CODE_FILES = ["app.py", "config.py", "db.py", "mailer.py", "requirements.txt", "__init__.py", "README.md"]
TEMPLATE_FILES = ["admin.html", "cloud.html", "member_center.html"]

def run(cmd, check=True):
    result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    if check and result.returncode != 0:
        raise SystemExit(f"命令失败: {' '.join(str(c) for c in cmd)}\n{result.stderr}")
    return result


def ssh(cmd_str: str, check=True):
    """执行单条 ssh 命令（单行，避免 Windows 换行问题）。"""
    result = subprocess.run(
        ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", "-i", str(SSH_KEY),
         SERVER_HOST, cmd_str],
        capture_output=True, text=True, encoding="utf-8",
    )
    if check and result.returncode != 0:
        raise SystemExit(f"SSH 失败: {cmd_str[:80]}\n{result.stderr}")
    return result


def main() -> int:
    if not SSH_KEY.exists():
        print(f"[ERR] 缺 SSH 私钥: {SSH_KEY}")
        return 1
    stamp = ssh("date +%Y%m%d-%H%M%S").stdout.strip()
    release_root = f"/opt/album-auth/releases/deploy-{stamp}"
    stage_server = f"{release_root}/server"
    stage_templates = f"{stage_server}/templates"
    backup = f"/opt/album-auth/backups/deploy-{stamp}"

    print("[1/5] 先备份线上代码并创建灰度目录")
    ssh(f"mkdir -p {stage_templates} {backup}/server")
    ssh(f"cp -a {REMOTE_SERVER_DIR}/. {backup}/server/")

    print("[2/5] 上传代码到灰度目录")
    for fname in CODE_FILES:
        src = REPO / "server" / fname
        if src.exists():
            run(["scp", "-q", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8",
                 "-i", str(SSH_KEY), str(src), f"{SERVER_HOST}:{stage_server}/"])
            print(f"  + {fname}")

    print("[3/5] 上传模板并执行灰度静态检查")
    for fname in TEMPLATE_FILES:
        src = REPO / "server" / "templates" / fname
        if src.exists():
            run(["scp", "-q", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8",
                 "-i", str(SSH_KEY), str(src), f"{SERVER_HOST}:{stage_templates}/"])
            print(f"  + templates/{fname}")
    ssh(f"cd {release_root} && /opt/album-auth/venv/bin/python -m py_compile server/app.py server/config.py server/db.py server/mailer.py")

    print("[4/5] 替换代码、重启并健康检查")
    ssh(f"cp -a {stage_server}/. {REMOTE_SERVER_DIR}/ && systemctl restart album-auth && sleep 3")
    health = ssh("curl -s -o /dev/null -w %{http_code} http://127.0.0.1:8000/api/me",
                 check=False).stdout.strip()
    if health != "401":
        ssh(f"cp -a {backup}/server/. {REMOTE_SERVER_DIR}/ && systemctl restart album-auth", check=False)
        raise SystemExit(f"健康检查失败：HTTP {health}，已自动回滚线上代码")
    print(f"  部署成功：backup={backup} health=401")
    print("[5/5] 授权中心部署完成")
    return 0


if __name__ == "__main__":
    sys.exit(main())
