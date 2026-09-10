# -*- coding: utf-8 -*-
"""Prepare a unique desktop release version inside the CI workspace.

The repository keeps a stable source snapshot, while every production desktop
release must publish a version strictly newer than the current update channel.
This script reads the online version, increments it, updates every build-time
version marker, and renames the fingerprinted desktop web assets so the release
contract remains internally consistent.

It intentionally changes only the checked-out CI workspace. The production
workflow runs it before release verification, build and publish.
"""

from __future__ import annotations

import json
import os
import re
import urllib.request
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
UPDATE_URL = os.environ.get(
    "ALBUM_UPDATE_URL", "https://api.shuiliyingxiang.cn/update/version.json"
)
VERSION_RE = re.compile(r"A(\d{8})-(\d+)\.(\d+)")
ASSET_RE = re.compile(r"app-(A\d{8}-\d+\.\d+)\.(js|css)")


def _read_remote_version() -> str:
    try:
        with urllib.request.urlopen(UPDATE_URL, timeout=8) as response:
            payload = json.loads(response.read().decode("utf-8"))
        value = str(payload.get("version") or "").strip()
        return value if VERSION_RE.fullmatch(value) else ""
    except Exception:
        return ""


def _source_version() -> str:
    text = (ROOT / "desktop_launcher.py").read_text(encoding="utf-8-sig")
    match = re.search(r'APP_VERSION\s*=\s*"(A\d{8}-\d+\.\d+)"', text)
    if not match:
        raise SystemExit("desktop_launcher.py 中未找到 APP_VERSION")
    return match.group(1)


def _version_key(value: str) -> tuple[int, int, int]:
    match = VERSION_RE.fullmatch(value or "")
    if not match:
        return (0, 0, 0)
    return tuple(int(part) for part in match.groups())


def _next_version(remote: str, source: str) -> str:
    forced = str(os.environ.get("ALBUM_RELEASE_VERSION") or "").strip()
    if forced:
        if not VERSION_RE.fullmatch(forced):
            raise SystemExit(f"ALBUM_RELEASE_VERSION 格式无效: {forced}")
        if remote and _version_key(forced) <= _version_key(remote):
            raise SystemExit(f"指定发布版本 {forced} 不高于线上版本 {remote}")
        return forced

    today = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y%m%d")
    remote_match = VERSION_RE.fullmatch(remote or "")
    source_match = VERSION_RE.fullmatch(source or "")
    major = max(
        int(remote_match.group(2)) if remote_match else 0,
        int(source_match.group(2)) if source_match else 0,
        2,
    )

    if remote_match and remote_match.group(1) == today:
        minor = int(remote_match.group(3)) + 1
    elif source_match and source_match.group(1) == today and (
        not remote_match or _version_key(source) > _version_key(remote)
    ):
        minor = int(source_match.group(3))
    else:
        minor = 1

    candidate = f"A{today}-{major}.{minor}"
    if remote and _version_key(candidate) <= _version_key(remote):
        # Handles a future-dated or unexpectedly advanced remote manifest safely.
        candidate = f"A{remote_match.group(1)}-{int(remote_match.group(2))}.{int(remote_match.group(3)) + 1}"
    return candidate


def _replace_versions(path: Path, new_version: str) -> None:
    raw = path.read_text(encoding="utf-8-sig")
    updated = VERSION_RE.sub(new_version, raw)
    if updated == raw:
        raise SystemExit(f"{path.name} 中没有可更新的版本号")
    path.write_text(updated, encoding="utf-8")


def _prepare_assets(new_version: str) -> None:
    index = ROOT / "templates" / "index.html"
    html = index.read_text(encoding="utf-8-sig")
    matches = ASSET_RE.findall(html)
    fingerprints = {version for version, _ext in matches}
    if len(fingerprints) != 1:
        raise SystemExit(f"index.html 资产版本异常: {sorted(fingerprints)}")
    old_version = next(iter(fingerprints))

    for ext in ("js", "css"):
        for suffix in (f".{ext}", f".{ext}.gz"):
            source = ROOT / "assets" / f"app-{old_version}{suffix}"
            target = ROOT / "assets" / f"app-{new_version}{suffix}"
            if not source.is_file():
                raise SystemExit(f"缺少待重命名资产: {source.name}")
            if target.exists():
                target.unlink()
            source.replace(target)

    html = html.replace(f"app-{old_version}.js", f"app-{new_version}.js")
    html = html.replace(f"app-{old_version}.css", f"app-{new_version}.css")
    index.write_text(html, encoding="utf-8")


def main() -> int:
    source = _source_version()
    remote = _read_remote_version()
    new_version = _next_version(remote, source)

    for relative in (
        "desktop_launcher.py",
        "cloud_client.py",
        "installer_win10.py",
        "安装脚本.iss",
    ):
        _replace_versions(ROOT / relative, new_version)
    _prepare_assets(new_version)

    print(f"source_version={source}")
    print(f"remote_version={remote or 'unknown'}")
    print(f"release_version={new_version}")

    github_env = os.environ.get("GITHUB_ENV")
    if github_env:
        with open(github_env, "a", encoding="utf-8") as handle:
            handle.write(f"ALBUM_RELEASE_VERSION={new_version}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
