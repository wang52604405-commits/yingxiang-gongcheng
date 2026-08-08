# -*- coding: utf-8 -*-
"""发布前契约检查：版本一致、关键私钥存在且与客户端内置公钥匹配。"""

from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path

import tamper_guard


ROOT = Path(__file__).resolve().parent
VERSION_RE = re.compile(r"A\d{8}-\d+\.\d+")


def read_version(path: Path, marker: str) -> str:
    text = path.read_text(encoding="utf-8")
    for line in text.splitlines():
        if marker in line:
            match = VERSION_RE.search(line)
            if match:
                return match.group(0)
    raise SystemExit(f"无法从 {path.name} 读取版本号")


def main() -> int:
    versions = {
        "desktop": read_version(ROOT / "desktop_launcher.py", "APP_VERSION"),
        "cloud": read_version(ROOT / "cloud_client.py", "APP_VERSION"),
        "legacy_installer": read_version(ROOT / "installer_win10.py", "APP_VERSION"),
        "inno": read_version(ROOT / "安装脚本.iss", "AppVersion="),
    }
    if len(set(versions.values())) != 1:
        raise SystemExit(f"发布版本不一致: {versions}")

    sign_key = Path(os.environ.get("ALBUM_SIGN_KEY", "")).expanduser()
    ssh_key = Path(os.environ.get("ALBUM_SSH_KEY", "")).expanduser()
    if not sign_key.is_file():
        raise SystemExit("缺少 ALBUM_SIGN_KEY 或文件不可读")
    if not ssh_key.is_file():
        raise SystemExit("缺少 ALBUM_SSH_KEY 或文件不可读")

    with tempfile.TemporaryDirectory(prefix="album-release-key-check-") as temp_dir:
        root = Path(temp_dir)
        (root / "album_server.exe").write_bytes(b"release-key-contract")
        tamper_guard.build_manifest(root, sign_key)
        ok, problems = tamper_guard.verify_installation(root, force=True)
        if not ok:
            raise SystemExit("防篡改私钥与客户端公钥不匹配: " + "; ".join(problems))

    print(f"发布契约通过: {next(iter(versions.values()))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
