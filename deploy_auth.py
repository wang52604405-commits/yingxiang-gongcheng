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
from pathlib import Path

SSH_KEY = Path.home() / ".ssh" / "id_ed25519_album"
SERVER_HOST = "root@47.95.221.66"
REMOTE_SERVER_DIR = "/opt/album-auth/server"
REMOTE_TEMPLATES = f"{REMOTE_SERVER_DIR}/templates"

REPO = Path(__file__).resolve().parent

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
    print("[1/4] 上传代码文件")
    for fname in CODE_FILES:
        src = REPO / "server" / fname
        if src.exists():
            run(["scp", "-q", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8",
                 "-i", str(SSH_KEY), str(src), f"{SERVER_HOST}:{REMOTE_SERVER_DIR}/"])
            print(f"  + {fname}")

    print("[2/4] 上传模板")
    for fname in TEMPLATE_FILES:
        src = REPO / "server" / "templates" / fname
        if src.exists():
            run(["scp", "-q", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8",
                 "-i", str(SSH_KEY), str(src), f"{SERVER_HOST}:{REMOTE_TEMPLATES}/"])
            print(f"  + templates/{fname}")

    print("[3/4] 备份 + 重启 + 健康检查")
    stamp = ssh("date +%Y%m%d-%H%M%S").stdout.strip()
    backup = f"/opt/album-auth/backup-{stamp}"
    ssh(f"mkdir -p {backup}")
    ssh(f"cp {REMOTE_SERVER_DIR}/app.py {REMOTE_SERVER_DIR}/db.py {REMOTE_SERVER_DIR}/config.py "
        f"{REMOTE_SERVER_DIR}/mailer.py {backup}/ 2>/dev/null; true")
    ssh(f"cp -r {REMOTE_SERVER_DIR}/templates {backup}/templates 2>/dev/null; true")
    ssh("systemctl restart album-auth && sleep 3")
    health = ssh("curl -s -o /dev/null -w %{http_code} http://127.0.0.1:8000/api/me",
                 check=False).stdout.strip()
    if health != "401":
        raise SystemExit(f"健康检查失败：HTTP {health}（应为 401）")
    print(f"  部署成功：backup={backup} health=401")
    print("[4/4] 授权中心部署完成")
    return 0


if __name__ == "__main__":
    sys.exit(main())
