# -*- coding: utf-8 -*-
"""授权中心自动部署：上传 server/ 代码到阿里云并重启。

流程：上传灰度代码 -> 在线备份 -> 只迁移副本 -> 安装依赖 ->
单 worker 服务配置 -> 替换代码 -> 本机/备案域名健康检查。

安全：不含私钥 / 邮箱授权码（服务器的 systemd unit 只引用受限的
/etc/album-auth/album-auth.env，本脚本不上传、不读取也不改写该文件）。
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
# 线上遗留的 no-control-socket.conf 会按字典序在数字前缀之后加载。
# 使用 zz 前缀才能保证移动端要求的单 worker/gthread 配置最终生效。
DROPIN_TARGET = "/etc/systemd/system/album-auth.service.d/zz-mobile-v1.conf"
DOMAIN_NGINX_TARGET = "/etc/nginx/sites-available/album-auth-domain"
DOMAIN_NGINX_LINK = "/etc/nginx/sites-enabled/album-auth-domain"
BACKUP_CRON_TARGET = "/etc/cron.d/album-auth-backup"
MOBILE_ENV_PATH = "/etc/album-auth/mobile.env"
_EXPECTED_ACCOUNTS_RAW = os.environ.get("ALBUM_EXPECTED_ACCOUNTS", "").strip()
EXPECTED_ACCOUNTS = int(_EXPECTED_ACCOUNTS_RAW) if _EXPECTED_ACCOUNTS_RAW else None

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
DEPLOY_FILES = [
    "album-auth-backup.cron",
    "album-auth.service",
    "album-auth-mobile-v1.conf",
    "backup.sh",
    "deploy.sh",
    "enable-https-ip.sh",
    "inject_acme_location.py",
    "nginx-http.conf",
    "nginx.conf",
    "nginx-domain.conf",
    "rollback.sh",
]


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


def require_mobile_environment() -> None:
    """在任何生产写操作前确认正式微信配置存在，但绝不读取或回显值。"""
    env_path = shlex.quote(MOBILE_ENV_PATH)
    result = ssh(
        f"test -s {env_path} && "
        f"grep -Eq '^ALBUM_WECHAT_APP_ID=.+$' {env_path} && "
        f"grep -Eq '^ALBUM_WECHAT_APP_SECRET=.+$' {env_path}",
        check=False,
    )
    if result.returncode != 0:
        raise SystemExit(
            "正式微信登录配置缺失或为空，已在修改生产环境前停止部署："
            f"请安全配置 {MOBILE_ENV_PATH} 中的 AppID 和 AppSecret"
        )


def production_health(*, include_https: bool = False) -> tuple[bool, str]:
    """同时验证服务、nginx 和关键旧/新接口；不读取任何凭据。"""
    checks = {
        "service": ssh(f"systemctl is-active {SERVICE_NAME}", check=False).stdout.strip(),
        "nginx": "ok" if ssh("nginx -t", check=False).returncode == 0 else "failed",
        "me": ssh(
            "curl -sS --max-time 15 -o /dev/null -w '%{http_code}' "
            "http://127.0.0.1:8000/api/me",
            check=False,
        ).stdout.strip(),
        "product": ssh(
            "curl -sS --max-time 15 -o /dev/null -w '%{http_code}' "
            "http://127.0.0.1:8000/api/product-config",
            check=False,
        ).stdout.strip(),
        "mobile": ssh(
            "curl -sS --max-time 15 -o /dev/null -w '%{http_code}' "
            "http://127.0.0.1:8000/api/mobile/v1/projects",
            check=False,
        ).stdout.strip(),
    }
    expected = {
        "service": "active",
        "nginx": "ok",
        "me": "401",
        "product": "200",
        "mobile": "401",
    }
    if include_https:
        for name, path, code in (
            ("https_me", "/api/me", "401"),
            ("https_product", "/api/product-config", "200"),
            ("https_mobile", "/api/mobile/v1/projects", "401"),
        ):
            checks[name] = ssh(
                "curl -sS --max-time 15 --resolve "
                "api.shuiliyingxiang.cn:443:127.0.0.1 -o /dev/null "
                f"-w '%{{http_code}}' https://api.shuiliyingxiang.cn{path}",
                check=False,
            ).stdout.strip()
            expected[name] = code
    ok = all(checks.get(name) == value for name, value in expected.items())
    detail = " ".join(f"{name}={checks.get(name) or 'none'}" for name in expected)
    return ok, detail


def main() -> int:
    if not SSH_KEY.exists():
        print(f"[ERR] 缺 SSH 私钥: {SSH_KEY}")
        return 1
    validator_source = REPO / "validate_mobile_migration.py"
    dropin_source = REPO / "server" / "deploy" / "album-auth-mobile-v1.conf"
    domain_nginx_source = REPO / "server" / "deploy" / "nginx-domain.conf"
    if not validator_source.is_file() or not dropin_source.is_file() or not domain_nginx_source.is_file():
        print("[ERR] 缺少迁移验证器、systemd drop-in 或正式域名 nginx 模板")
        return 1

    # 此处之前仅做本地文件检查；以下远程检查也是只读。任何 mkdir、备份、
    # 依赖安装、服务或 nginx 变更都必须等微信密钥文件通过检查后才能发生。
    require_mobile_environment()

    stamp = ssh("date +%Y%m%d-%H%M%S").stdout.strip()
    release_root = f"/opt/album-auth/releases/deploy-{stamp}"
    stage_server = f"{release_root}/server"
    stage_templates = f"{stage_server}/templates"
    stage_deploy = f"{stage_server}/deploy"
    backup = f"/opt/album-auth/backups/deploy-{stamp}"
    live_db_backup = f"{backup}/live-db.sqlite3"
    validation_root = f"{release_root}/migration-validation"
    validation_copy = f"{validation_root}/database.sqlite3"
    stage_validator = f"{release_root}/validate_mobile_migration.py"
    stage_dropin = f"{stage_deploy}/album-auth-mobile-v1.conf"
    stage_domain_nginx = f"{stage_deploy}/nginx-domain.conf"
    stage_backup_cron = f"{stage_deploy}/album-auth-backup.cron"

    print("[1/9] 先备份线上代码并创建灰度目录")
    ssh(f"mkdir -p {stage_templates} {stage_deploy}")
    ssh(f"install -d -m 0700 {backup} {backup}/server")
    ssh(f"install -d -m 0700 {validation_root}")
    ssh(f"cp -a {REMOTE_SERVER_DIR}/. {backup}/server/")
    domain_nginx_state = ssh(
        f"if test -f {DOMAIN_NGINX_TARGET}; then "
        f"cp -a {DOMAIN_NGINX_TARGET} {backup}/previous-domain-nginx.conf && printf present; "
        "else printf absent; fi"
    ).stdout.strip()
    if domain_nginx_state not in {"present", "absent"}:
        raise SystemExit(f"无法确认正式域名 nginx 状态：{domain_nginx_state!r}")
    backup_cron_state = ssh(
        f"if test -f {BACKUP_CRON_TARGET}; then "
        f"cp -a {BACKUP_CRON_TARGET} {backup}/previous-backup.cron && printf present; "
        "else printf absent; fi"
    ).stdout.strip()
    if backup_cron_state not in {"present", "absent"}:
        raise SystemExit(f"无法确认自动备份计划状态：{backup_cron_state!r}")

    print("[2/9] 上传代码、迁移验证器和服务 drop-in 到灰度目录")
    for fname in CODE_FILES:
        src = REPO / "server" / fname
        if src.exists():
            run(["scp", "-q", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8",
                 "-i", str(SSH_KEY), str(src), f"{SERVER_HOST}:{stage_server}/"])
            print(f"  + {fname}")
    for fname in DEPLOY_FILES:
        src = REPO / "server" / "deploy" / fname
        if src.exists():
            run(["scp", "-q", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8",
                 "-i", str(SSH_KEY), str(src), f"{SERVER_HOST}:{stage_deploy}/"])
            print(f"  + deploy/{fname}")
    for source, destination in ((validator_source, stage_validator),):
        run([
            "scp", "-q", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8",
            "-i", str(SSH_KEY), str(source), f"{SERVER_HOST}:{destination}",
        ])
        print(f"  + {source.name}")

    print("[3/9] 上传模板并执行灰度静态检查")
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

    print("[4/9] 用 SQLite backup API 备份线上库，并只在新副本验证迁移")
    backup_result = ssh_python(
        BACKUP_LIVE_DB_SCRIPT,
        live_db_backup,
        SERVICE_NAME,
        f"{REMOTE_SERVER_DIR}/data/server.db",
    )
    print("  " + backup_result.stdout.strip())
    expected_accounts_arg = (
        f"--expected-accounts {EXPECTED_ACCOUNTS}" if EXPECTED_ACCOUNTS is not None else ""
    )
    validation_result = ssh(
        f"cd {release_root} && PYTHONPATH={release_root} {REMOTE_PYTHON} "
        f"{stage_validator} --source {live_db_backup} --copy {validation_copy} "
        f"--copy-root {validation_root} "
        f"{expected_accounts_arg}"
    )
    print("  迁移副本验证通过：旧业务表数量未变化，移动端表完整")
    # 验证副本只用于本次迁移证明；稳定的 live-db.sqlite3 仍作为发布备份保留。
    ssh(f"rm -f -- {validation_copy} && rmdir -- {validation_root}")

    print("[5/9] 在替换代码前安装并校验新增依赖")
    ssh(
        f"{REMOTE_PYTHON} -m pip install --disable-pip-version-check "
        f"-r {stage_server}/requirements.txt"
    )

    print("[6/9] 安装单 worker 服务 drop-in（不改现有环境变量和密钥）")
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
        if domain_nginx_state == "present":
            restore_domain_nginx = (
                f"cp -a {backup}/previous-domain-nginx.conf {DOMAIN_NGINX_TARGET} && "
                f"ln -sfn {DOMAIN_NGINX_TARGET} {DOMAIN_NGINX_LINK}"
            )
        else:
            restore_domain_nginx = f"rm -f {DOMAIN_NGINX_TARGET} {DOMAIN_NGINX_LINK}"
        if backup_cron_state == "present":
            restore_backup_cron = f"cp -a {backup}/previous-backup.cron {BACKUP_CRON_TARGET}"
        else:
            restore_backup_cron = f"rm -f {BACKUP_CRON_TARGET}"
        restored = ssh(
            f"test \"$(readlink -f -- {backup}/server)\" = \"{backup}/server\" && "
            f"test \"$(readlink -f -- {REMOTE_SERVER_DIR})\" = \"{REMOTE_SERVER_DIR}\" && "
            f"rsync -a --delete -- {backup}/server/ {REMOTE_SERVER_DIR}/ && "
            f"{restore_dropin} && {restore_domain_nginx} && {restore_backup_cron} && "
            f"systemctl daemon-reload && systemctl restart {SERVICE_NAME} && "
            "nginx -t && systemctl reload nginx",
            check=False,
        )
        if restored.returncode != 0:
            raise SystemExit(
                "自动回滚执行失败，需要按备份人工恢复："
                f"backup={backup} detail={restored.stderr.strip()[:300]}"
            )
        rollback_ok, rollback_detail = production_health(
            include_https=(domain_nginx_state == "present")
        )
        if not rollback_ok:
            raise SystemExit(
                "自动回滚后的健康检查失败，需要按备份人工恢复："
                f"backup={backup} {rollback_detail}"
            )

    install_dropin = ssh(
        f"install -d -m 0755 /etc/systemd/system/{SERVICE_NAME}.service.d && "
        f"install -m 0644 {stage_dropin} {DROPIN_TARGET} && "
        "systemctl daemon-reload && "
        f"systemctl show {SERVICE_NAME} -p ExecStart --value | "
        "grep -F -- '-w 1 --threads 4 --timeout 300' >/dev/null && "
        f"systemctl show {SERVICE_NAME} -p EnvironmentFiles --value | "
        "grep -F -- '/etc/album-auth/mobile.env' >/dev/null",
        check=False,
    )
    if install_dropin.returncode != 0:
        restore_code_and_service()
        raise SystemExit(f"systemd drop-in 安装失败，已恢复原配置：{install_dropin.stderr}")

    print("[7/9] 替换代码、重启并检查旧接口和移动端接口")
    replacement = ssh(
        f"cp -a {stage_server}/. {REMOTE_SERVER_DIR}/ && "
        f"systemctl restart {SERVICE_NAME} && sleep 3",
        check=False,
    )
    if replacement.returncode != 0:
        restore_code_and_service()
        raise SystemExit(f"服务重启失败，已回滚代码与 drop-in：{replacement.stderr}")
    local_ok, local_detail = production_health()
    if not local_ok:
        restore_code_and_service()
        raise SystemExit(
            f"健康检查失败：{local_detail}；已完成并验证代码与服务回滚"
        )

    print("[8/9] 安装已备案域名 nginx 配置和自动备份计划")
    nginx_install = ssh(
        f"install -m 0644 {stage_domain_nginx} {DOMAIN_NGINX_TARGET} && "
        f"install -m 0644 {stage_backup_cron} {BACKUP_CRON_TARGET} && "
        f"ln -sfn {DOMAIN_NGINX_TARGET} {DOMAIN_NGINX_LINK} && "
        "nginx -t && systemctl reload nginx",
        check=False,
    )
    if nginx_install.returncode != 0:
        restore_code_and_service()
        raise SystemExit(f"正式域名 nginx 安装失败，已回滚：{nginx_install.stderr}")
    public_ok, public_detail = production_health(include_https=True)
    if not public_ok:
        restore_code_and_service()
        raise SystemExit(
            f"备案域名健康检查失败：{public_detail}；已完成并验证回滚"
        )
    print(
        f"  部署成功：backup={backup} database_backup={live_db_backup} "
        f"{public_detail}"
    )
    print("[9/9] 授权中心部署完成")
    return 0


if __name__ == "__main__":
    sys.exit(main())
