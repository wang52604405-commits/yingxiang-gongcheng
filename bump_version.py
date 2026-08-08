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
import re
import sys
from pathlib import Path

USE = Path(__file__).resolve().parent

DESKTOP = USE / "desktop_launcher.py"
CLOUD = USE / "cloud_client.py"
ISS = USE / "安装脚本.iss"

SSH_KEY = Path.home() / ".ssh" / "id_ed25519_album"
SERVER_HOST = "root@47.95.221.66"
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

    # 安装脚本.iss: 三处（AppVersion / AppVerName / 注册表 Version）
    iss = ISS.read_text(encoding="utf-8")
    iss = _replace_version(iss, r'AppVersion=A\d{8}-\d+\.\d+',
                           f"AppVersion={new_ver}", ISS.name)
    iss = _replace_version(iss, r'AppVerName=工程影像管理平台 A\d{8}-\d+\.\d+',
                           f"AppVerName=工程影像管理平台 {new_ver}", ISS.name)
    iss = _replace_version(iss, r'ValueName: "Version"; ValueData: "A\d{8}-\d+\.\d+"',
                           f'ValueName: "Version"; ValueData: "{new_ver}"', ISS.name)
    ISS.write_text(iss, encoding="utf-8")


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
