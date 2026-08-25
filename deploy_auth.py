# -*- coding: utf-8 -*-
"""授权中心自动部署：上传 server/ 代码到阿里云并重启。

流程：
  1. 上传代码、迁移验证器和 systemd drop-in 到独立灰度目录
  2. 用 SQLite backup API 在线备份运行中的数据库
  3. 仅在新副本上验证移动端增量迁移与旧表行数
  4. 安装依赖，通过 drop-in 将 Gunicorn 收敛为 1 worker + 4 threads
  5. 替换代码、重启并检查旧接口与移动端接口

安全：不含私钥 / 邮箱授权码（服务器用 systemd 环境变量注入，
配置在 /etc/systemd/system/album-auth.service，不受本脚本影响）。
私钥由服务器 /etc/album-auth/private_key.pem 提供，本脚本不触碰。

用法：python deploy_auth.py
"""

from __future__ import annotations

import subprocess
import sys
import os
import base64
import shlex
from pathlib import Path

REPO = Path(__file__).resolve().parent
SSH_KEY = Path(os.environ.get(
    "ALBUM_SSH_KEY",
    REPO / "服务器访问-工程影像管理平台" / "server_key",
))
SERVER_HOST = os.environ.get("ALBUM_SERVER_HOST", "root@47.95.221.66")
REMOTE_SERVER_DIR = "/opt/album-auth/server"
REMOTE_PYTHON = "/opt/album-auth/venv/bin/python"
SERVICE_NAME = "album-auth"
DROPIN_TARGET = "/etc/systemd/system/album-auth.service.d/10-mobile-v1.conf"
EXPECTED_ACCOUNTS = int(os.environ.get("ALBUM_EXPECTED_ACCOUNTS", "32"))

# 要上传的代码文件（不含私钥/敏感文件）
CODE_FILES = [
    "app.py",
    "config.py",
    "db.py",
    "mailer.py",
    "mobile_api.py",
    "mobile_storage.py",
    "mobile_recognition.py",
    "mobile_chunks.py",
    "requirements.txt",
    "__init__.py",
    "README.md",
]
TEMPLATE_FILES = ["admin.html", "cloud.html", "member_center.html"]


BACKUP_LIVE_DB_SCRIPT = r"""
import os
import sqlite3
import subprocess
import sys
from pathlib import Path
from urllib.parse import quote

os.umask(0o077)
target = Path(sys.argv[1]).resolve()
service_name = sys.argv[2]
default_database = Path(sys.argv[3])
pid = subprocess.check_output(
    ["systemctl", "show", "--property=MainPID", "--value", service_name],
    text=True,
).strip()
if not pid or pid == "0":
    raise SystemExit(f"{service_name} 未运行，无法可靠读取线上数据库配置")

raw_environment = Path(f"/proc/{pid}/environ").read_bytes()
environment = {}
for entry in raw_environment.split(b"\0"):
    key, separator, value = entry.partition(b"=")
    if separator:
        environment[key.decode("utf-8", "surrogateescape")] = value.decode(
            "utf-8", "surrogateescape"
        )

working_directory = Path(os.readlink(f"/proc/{pid}/cwd"))
configured_database = environment.get("ALBUM_SERVER_DB", "").strip()
if configured_database:
    source = Path(configured_database)
elif environment.get("ALBUM_SERVER_DATA", "").strip():
    source = Path(environment["ALBUM_SERVER_DATA"]) / "server.db"
else:
    source = default_database
if not source.is_absolute():
    source = working_directory / source
source = source.resolve()

if not source.is_file():
    raise SystemExit(f"线上数据库不存在：{source}")
if target.exists():
    raise SystemExit(f"备份目标已存在，拒绝覆盖：{target}")
target.parent.mkdir(parents=True, exist_ok=True)

source_uri = "file:" + quote(str(source), safe="/:") + "?mode=ro"
source_connection = sqlite3.connect(source_uri, uri=True, timeout=30)
target_connection = sqlite3.connect(target, timeout=30)
try:
    source_connection.execute("PRAGMA query_only = ON")
    source_connection.backup(target_connection, pages=256, sleep=0.05)
    target_connection.commit()
    integrity = target_connection.execute("PRAGMA integrity_check").fetchone()[0]
    if integrity != "ok":
        raise SystemExit(f"SQLite 备份完整性检查失败：{integrity}")
finally:
    target_connection.close()
    source_connection.close()
os.chmod(target, 0o600)
print(f"SQLite 在线备份完成：{source} -> {target}")
"""

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


def ssh_python(source: str, *args: str, check=True):
    """以 base64 传输短 Python 程序，避免远端 shell 引号改变脚本内容。"""
    encoded = base64.b64encode(source.encode("utf-8")).decode("ascii")
    launcher = f"import base64;exec(base64.b64decode({encoded!r}))"
    command = " ".join(
        [REMOTE_PYTHON, "-c", shlex.quote(launcher)]
        + [shlex.quote(str(argument)) for argument in args]
    )
    return ssh(command, check=check)


def main() -> int:
    if not SSH_KEY.exists():
        print(f"[ERR] 缺 SSH 私钥: {SSH_KEY}")
        return 1
    stamp = ssh("date +%Y%m%d-%H%M%S").stdout.strip()
    release_root = f"/opt/album-auth/releases/deploy-{stamp}"
    stage_server = f"{release_root}/server"
    stage_templates = f"{stage_server}/templates"
    backup = f"/opt/album-auth/backups/deploy-{stamp}"
    live_db_backup = f"{backup}/live-db.sqlite3"
    validation_root = f"{release_root}/migration-validation"
    validation_copy = f"{validation_root}/database.sqlite3"
    stage_validator = f"{release_root}/validate_mobile_migration.py"
    stage_dropin = f"{release_root}/10-mobile-v1.conf"
    validator_source = REPO / "validate_mobile_migration.py"
    dropin_source = REPO / "server" / "deploy" / "album-auth-mobile-v1.conf"
    if not validator_source.is_file() or not dropin_source.is_file():
        print("[ERR] 缺少迁移验证器或 systemd drop-in 模板")
        return 1

    print("[1/8] 先备份线上代码并创建灰度目录")
    ssh(f"mkdir -p {stage_templates}")
    ssh(f"install -d -m 0700 {backup} {backup}/server")
    ssh(f"install -d -m 0700 {validation_root}")
    ssh(f"cp -a {REMOTE_SERVER_DIR}/. {backup}/server/")

    print("[2/8] 上传代码、迁移验证器和服务 drop-in 到灰度目录")
    for fname in CODE_FILES:
        src = REPO / "server" / fname
        if src.exists():
            run(["scp", "-q", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8",
                 "-i", str(SSH_KEY), str(src), f"{SERVER_HOST}:{stage_server}/"])
            print(f"  + {fname}")
    for source, destination in (
        (validator_source, stage_validator),
        (dropin_source, stage_dropin),
    ):
        run([
            "scp", "-q", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8",
            "-i", str(SSH_KEY), str(source), f"{SERVER_HOST}:{destination}",
        ])
        print(f"  + {source.name}")

    print("[3/8] 上传模板并执行灰度静态检查")
    for fname in TEMPLATE_FILES:
        src = REPO / "server" / "templates" / fname
        if src.exists():
            run(["scp", "-q", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8",
                 "-i", str(SSH_KEY), str(src), f"{SERVER_HOST}:{stage_templates}/"])
            print(f"  + templates/{fname}")
    compile_targets = " ".join(f"server/{name}" for name in CODE_FILES if name.endswith(".py"))
    ssh(
        f"cd {release_root} && {REMOTE_PYTHON} -m py_compile "
        f"{compile_targets} validate_mobile_migration.py"
    )

    print("[4/8] 用 SQLite backup API 备份线上库，并只在新副本验证迁移")
    backup_result = ssh_python(
        BACKUP_LIVE_DB_SCRIPT,
        live_db_backup,
        SERVICE_NAME,
        f"{REMOTE_SERVER_DIR}/data/server.db",
    )
    print("  " + backup_result.stdout.strip())
    validation_result = ssh(
        f"cd {release_root} && PYTHONPATH={release_root} {REMOTE_PYTHON} "
        f"{stage_validator} --source {live_db_backup} --copy {validation_copy} "
        f"--copy-root {validation_root} "
        f"--expected-accounts {EXPECTED_ACCOUNTS}"
    )
    print("  迁移副本验证通过：旧业务表数量未变化，移动端表完整")

    print("[5/8] 在替换代码前安装并校验新增依赖")
    ssh(
        f"{REMOTE_PYTHON} -m pip install --disable-pip-version-check "
        f"-r {stage_server}/requirements.txt"
    )

    print("[6/8] 安装单 worker 服务 drop-in（不改现有环境变量和密钥）")
    dropin_state = ssh(
        f"if test -f {DROPIN_TARGET}; then "
        f"cp -a {DROPIN_TARGET} {backup}/previous-mobile-v1.conf && printf present; "
        "else printf absent; fi"
    ).stdout.strip()
    if dropin_state not in {"present", "absent"}:
        raise SystemExit(f"无法确认原 systemd drop-in 状态：{dropin_state!r}")

    def restore_code_and_service() -> None:
        if dropin_state == "present":
            restore_dropin = (
                f"cp -a {backup}/previous-mobile-v1.conf {DROPIN_TARGET}"
            )
        else:
            restore_dropin = f"rm -f {DROPIN_TARGET}"
        ssh(
            f"cp -a {backup}/server/. {REMOTE_SERVER_DIR}/ && "
            f"{restore_dropin} && systemctl daemon-reload && "
            f"systemctl restart {SERVICE_NAME}",
            check=False,
        )

    install_dropin = ssh(
        f"install -d -m 0755 /etc/systemd/system/{SERVICE_NAME}.service.d && "
        f"install -m 0644 {stage_dropin} {DROPIN_TARGET} && "
        "systemctl daemon-reload",
        check=False,
    )
    if install_dropin.returncode != 0:
        restore_code_and_service()
        raise SystemExit(f"systemd drop-in 安装失败，已恢复原配置：{install_dropin.stderr}")

    print("[7/8] 替换代码、重启并检查旧接口和移动端接口")
    replacement = ssh(
        f"cp -a {stage_server}/. {REMOTE_SERVER_DIR}/ && "
        f"systemctl restart {SERVICE_NAME} && sleep 3",
        check=False,
    )
    if replacement.returncode != 0:
        restore_code_and_service()
        raise SystemExit(f"服务重启失败，已回滚代码与 drop-in：{replacement.stderr}")
    legacy_health = ssh(
        "curl -s -o /dev/null -w %{http_code} http://127.0.0.1:8000/api/me",
        check=False,
    ).stdout.strip()
    mobile_health = ssh(
        "curl -s -o /dev/null -w %{http_code} http://127.0.0.1:8000/api/mobile/v1/projects",
        check=False,
    ).stdout.strip()
    if legacy_health != "401" or mobile_health != "401":
        restore_code_and_service()
        raise SystemExit(
            f"健康检查失败：legacy={legacy_health} mobile={mobile_health}，"
            "已自动回滚线上代码与 systemd drop-in"
        )
    print(
        f"  部署成功：backup={backup} database_backup={live_db_backup} "
        f"legacy=401 mobile=401"
    )
    print("[8/8] 授权中心部署完成")
    return 0


if __name__ == "__main__":
    sys.exit(main())
