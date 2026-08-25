# -*- coding: utf-8 -*-
"""发布前契约检查：版本一致、关键私钥存在且与客户端内置公钥匹配。

版本一致性覆盖：desktop / cloud / legacy_installer / inno 四文件，
以及前端 assets 指纹（index.html 引用的 app-A{版本}.js/.css）。
若服务器 version.json 可达，会阻止把较旧版本覆盖到较新服务器；服务器
版本落后于本地是正常发布场景，记录后继续执行。
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

import tamper_guard


ROOT = Path(__file__).resolve().parent
VERSION_RE = re.compile(r"A\d{8}-\d+\.\d+")
# 前端资源文件名：index.html 中引用的 app-A<版本>.js/.css（同时校验 .gz 是否齐）
ASSET_RE = re.compile(r"app-(A\d{8}-\d+\.\d+)\.(?:js|css)")
# 服务器发布清单路径：与 desktop_launcher.UPDATE_URL 保持一致
UPDATE_URL = os.environ.get("ALBUM_UPDATE_URL", "http://47.95.221.66/update/version.json")
ONLINE_TIMEOUT = 8


def read_version(path: Path, marker: str) -> str:
    text = path.read_text(encoding="utf-8")
    for line in text.splitlines():
        if marker in line:
            match = VERSION_RE.search(line)
            if match:
                return match.group(0)
    raise SystemExit(f"无法从 {path.name} 读取版本号")


def read_asset_fingerprint(index_html: Path) -> str:
    """从 index.html 提取引用的前端资产版本；不存在或格式异常即失败。"""
    text = index_html.read_text(encoding="utf-8")
    names = ASSET_RE.findall(text)
    if not names:
        raise SystemExit("index.html 中未找到版本化前端资产引用")
    if len(set(names)) != 1:
        raise SystemExit(f"index.html 引用了多个版本的资产: {names}")
    return names[0]


def verify_assets_present(fingerprint: str) -> None:
    """确认 fingerprint 对应的 js/css 及其 .gz 预压缩文件都存在。"""
    assets = ROOT / "assets"
    for ext in (".js", ".css"):
        for suffix in (ext, ext + ".gz"):
            target = assets / f"app-{fingerprint}{suffix}"
            if not target.is_file():
                raise SystemExit(f"缺少前端资产文件: {target.name}")


def read_remote_version() -> str:
    """读取服务器 version.json；失败返回空串（表示线上未知，不强制）。"""
    try:
        with urllib.request.urlopen(UPDATE_URL, timeout=ONLINE_TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return str(data.get("version") or "")
    except (urllib.error.URLError, OSError, ValueError):
        return ""


def version_key(value: str) -> tuple[int, int, int]:
    """将 AYYYYMMDD-主版本.次版本转换为可比较的版本序列。"""
    match = re.fullmatch(r"A(\d{8})-(\d+)\.(\d+)", value)
    if not match:
        raise ValueError(f"无效版本号: {value}")
    return tuple(int(part) for part in match.groups())


def main() -> int:
    versions = {
        "desktop": read_version(ROOT / "desktop_launcher.py", "APP_VERSION"),
        "cloud": read_version(ROOT / "cloud_client.py", "APP_VERSION"),
        "legacy_installer": read_version(ROOT / "installer_win10.py", "APP_VERSION"),
        "inno": read_version(ROOT / "安装脚本.iss", "AppVersion="),
    }
    if len(set(versions.values())) != 1:
        raise SystemExit(f"发布版本不一致: {versions}")

    # 前端资产指纹必须先确认，再校验其文件齐全
    fingerprint = read_asset_fingerprint(ROOT / "templates" / "index.html")
    if fingerprint != next(iter(versions.values())):
        raise SystemExit(f"前端资产指纹({fingerprint})与代码版本({next(iter(versions.values()))})不一致")
    verify_assets_present(fingerprint)

    # 线上服务器版本对比：禁止回退，允许正常的“本地新版覆盖线上旧版”。
    remote = read_remote_version()
    if remote:
        try:
            if version_key(remote) > version_key(versions["desktop"]):
                raise SystemExit(
                    f"服务器线上版本({remote})高于本地({versions['desktop']})，禁止回退发布"
                )
        except ValueError:
            raise SystemExit(f"服务器线上版本格式异常: {remote}")

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

    print(f"发布契约通过: {versions['desktop']}（前端指纹 {fingerprint}）")
    if remote:
        if remote == versions["desktop"]:
            print(f"服务器线上确认: {remote}")
        else:
            print(f"服务器将从 {remote} 升级至 {versions['desktop']}")
    else:
        print("服务器线上不可达，校验降级跳过（本地五项一致）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
