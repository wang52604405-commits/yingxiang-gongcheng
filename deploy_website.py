# -*- coding: utf-8 -*-
"""Safely validate and deploy the static marketing website.

The installer and unknown website files are excluded. Previous managed content,
including both tutorial locations, and failed content are retained in a new backup.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
import tarfile
import tempfile
import uuid
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath


ROOT = Path(__file__).resolve().parent
SITE = ROOT / "website"
PAGES = ("index.html", "product.html", "usage.html", "download.html", "contact.html")
SSH_KEY = Path(
    os.environ.get(
        "ALBUM_SSH_KEY",
        ROOT / "服务器访问-工程影像管理平台" / "server_key",
    )
)
# 有 ALBUM_SERVER_HOST 时用它。Actions 没配 Secret 时变量是空字符串，仍用原来的默认主机。
_configured_host = os.environ.get("ALBUM_SERVER_HOST", "").strip()
SERVER_HOST = (
    "root@47.95.221.66"
    if not _configured_host or "YOUR_SERVER" in _configured_host.upper()
    else _configured_host
)
REMOTE_ROOT = "/var/www/shuiliyingxiang"
TUTORIAL_NAME = "工程影像管理平台-使用教程.docx"
INSTALLER_NAME = "工程影像管理平台-安装程序.exe"
VERSION_SLOT = '<span class="published-version" data-published-version></span>'


class _AssetParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.references: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag in {"img", "script"} and values.get("src"):
            self.references.append(str(values["src"]))
        if tag == "link" and values.get("href"):
            self.references.append(str(values["href"]))


def validate_site(site: Path = SITE) -> None:
    # Do not re-publish retired screenshots, legacy page copies or private backups.
    # New screenshots require an explicit review and an updated allowlist.
    approved_assets = {
        "favicon.svg", "miniprogram_qr.png", "style.css", "restructure.css", "site.js",
        "demo-h5-03-home.jpg", "demo-h5-06-library.jpg", "demo-h5-12-process.jpg",
        "demo-desktop-municipal-division.jpg", "demo-desktop-municipal-location.jpg",
    }
    approved_roots = {*PAGES, "site-content.json", "README.md", "assets", "tutorial"}
    for child in site.iterdir():
        if child.name not in approved_roots or child.is_symlink():
            raise SystemExit(f"官网发布目录含未审查文件：{child.name}")
    for asset in (site / "assets").rglob("*"):
        if not asset.is_file() or asset.is_symlink() or asset.relative_to(site / "assets").as_posix() not in approved_assets:
            raise SystemExit(f"官网素材未通过隐私审查：{asset.name}")
    for resource in (site / "tutorial").rglob("*"):
        if not resource.is_file() or resource.is_symlink() or resource.relative_to(site / "tutorial").as_posix() != TUTORIAL_NAME:
            raise SystemExit(f"教程目录含未审查文件：{resource.name}")
    missing = [name for name in PAGES if not (site / name).is_file()]
    if missing:
        raise SystemExit(f"宣传网站缺少页面：{', '.join(missing)}")

    all_text = ""
    for page_name in PAGES:
        page = site / page_name
        text = page.read_text(encoding="utf-8")
        all_text += text
        parser = _AssetParser()
        parser.feed(text)
        for raw_reference in parser.references:
            reference = raw_reference.split("?", 1)[0].split("#", 1)[0]
            if not reference or reference.startswith(("http://", "https://", "/")):
                continue
            target = (page.parent / reference).resolve()
            if site.resolve() not in target.parents or not target.is_file():
                raise SystemExit(f"{page_name} 的本地资源不存在：{raw_reference}")

    for profession in ("水利", "房建", "市政", "电力"):
        if profession not in all_text:
            raise SystemExit(f"宣传网站未体现专业：{profession}")
    if f"/download/{INSTALLER_NAME}" not in all_text:
        raise SystemExit("宣传网站安装包地址发生变化")
    tutorial = site / "tutorial" / TUTORIAL_NAME
    if not tutorial.is_file() or tutorial.stat().st_size < 1000:
        raise SystemExit("宣传网站缺少使用教程文件")
    if f"/download/{TUTORIAL_NAME}" not in all_text:
        raise SystemExit("宣传网站使用教程地址发生变化")
    if re.search(r"aos|vanilla-tilt|data-tilt", all_text, re.IGNORECASE):
        raise SystemExit("页面仍引用过量滚动或倾斜动画")
    if "assets/site.js" not in all_text or "nav-toggle" not in all_text:
        raise SystemExit("宣传网站缺少移动导航")
    if "300 张" in all_text or "自动检查更新" in all_text:
        raise SystemExit("宣传网站仍写着过期的免费张数或自动更新")


def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8")
    if result.returncode:
        raise SystemExit(f"命令失败：{' '.join(command[:3])}\n{result.stderr}")
    return result


def _ssh(command: str) -> subprocess.CompletedProcess[str]:
    return _run(
        [
            "ssh",
            "-o",
            "BatchMode=yes",
            "-o",
            "ConnectTimeout=10",
            "-i",
            str(SSH_KEY),
            SERVER_HOST,
            command,
        ]
    )


def _published_version() -> str:
    """Read the installer version customers can actually download."""
    try:
        result = subprocess.run(
            [
                "curl",
                "-fsSL",
                "--max-time",
                "12",
                "https://api.shuiliyingxiang.cn/update/version.json",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=20,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    if result.returncode:
        return ""
    try:
        version = str(json.loads(result.stdout).get("version") or "")
    except (TypeError, ValueError):
        return ""
    if re.fullmatch(r"A\d{8}-\d+\.\d+", version):
        return version
    return ""


def _stamp_published_version(site: Path) -> str:
    version = _published_version()
    replacement = VERSION_SLOT
    if version:
        replacement = (
            '<span class="published-version" data-published-version>'
            f" · 版本 {version}</span>"
        )
    for name in PAGES:
        page = site / name
        page.write_text(
            page.read_text(encoding="utf-8").replace(VERSION_SLOT, replacement),
            encoding="utf-8",
        )
    return version


def build_allocation_script(stage: str, backup: str) -> str:
    """Create exclusive transaction directories before uploading any payload."""
    return (
        "set -Eeuo pipefail; umask 077; "
        f"mkdir -m 0700 -- {shlex.quote(stage)}; "
        f"mkdir -p -- {shlex.quote(PurePosixPath(backup).parent.as_posix())}; "
        f"mkdir -m 0700 -- {shlex.quote(backup)}"
    )


def build_remote_script(stage: str, backup: str, archive: str, root: str = REMOTE_ROOT) -> str:
    """Bash transaction over a fixed set of website paths; retain every displaced item."""
    managed = (*PAGES, "site-content.json", "assets", "tutorial")
    published = (*PAGES, "site-content.json", "assets")
    managed_q = " ".join(shlex.quote(name) for name in managed)
    published_q = " ".join(shlex.quote(name) for name in published)
    pages_q = " ".join(shlex.quote(name) for name in PAGES)
    return f"""set -Eeuo pipefail
umask 077
ROOT={shlex.quote(root)}
STAGE={shlex.quote(stage)}
BACKUP={shlex.quote(backup)}
ARCHIVE={shlex.quote(archive)}
TUTORIAL_NAME={shlex.quote(TUTORIAL_NAME)}
INSTALLER_NAME={shlex.quote(INSTALLER_NAME)}
MANAGED=({managed_q})
PUBLISHED=({published_q})
SITE="$STAGE/site"
test -d "$ROOT" && test ! -L "$ROOT"
test -d "$ROOT/download" && test ! -L "$ROOT/download"
test -s "$ROOT/download/$INSTALLER_NAME"
mkdir -m 0700 -- "$SITE" "$BACKUP/original" "$BACKUP/displaced" "$BACKUP/failed"
tar -xzf "$ARCHIVE" -C "$SITE"
for name in {pages_q} site-content.json; do test -s "$SITE/$name"; done
test -s "$SITE/assets/style.css" && test -s "$SITE/assets/site.js"
test -s "$SITE/tutorial/$TUTORIAL_NAME"
test -z "$(find "$SITE" -type l -print -quit)"
grep -q '四大专业' "$SITE/index.html"
: > "$BACKUP/present.txt"
for name in "${{MANAGED[@]}}"; do
    if [ -e "$ROOT/$name" ] || [ -L "$ROOT/$name" ]; then
        cp -a -- "$ROOT/$name" "$BACKUP/original/$name"
        printf '%s\\n' "$name" >> "$BACKUP/present.txt"
    fi
done
if [ -e "$ROOT/download/$TUTORIAL_NAME" ] || [ -L "$ROOT/download/$TUTORIAL_NAME" ]; then
    cp -a -- "$ROOT/download/$TUTORIAL_NAME" "$BACKUP/original/download-tutorial"
    printf '%s\\n' download-tutorial >> "$BACKUP/present.txt"
fi
touch "$BACKUP/snapshot-ready"
rollback() {{
    status=$?
    trap - ERR
    recovery_failed=0
    for name in "${{MANAGED[@]}}"; do
        if [ -e "$ROOT/$name" ] || [ -L "$ROOT/$name" ]; then
            if ! mv -- "$ROOT/$name" "$BACKUP/failed/$name"; then
                recovery_failed=1
                continue
            fi
        fi
        if grep -Fxq -- "$name" "$BACKUP/present.txt"; then
            cp -a -- "$BACKUP/original/$name" "$ROOT/$name" || recovery_failed=1
        fi
    done
    download_cleared=1
    if [ -e "$ROOT/download/$TUTORIAL_NAME" ] || [ -L "$ROOT/download/$TUTORIAL_NAME" ]; then
        mv -- "$ROOT/download/$TUTORIAL_NAME" "$BACKUP/failed/download-tutorial" || download_cleared=0
    fi
    if [ "$download_cleared" -eq 1 ]; then
        if grep -Fxq download-tutorial "$BACKUP/present.txt"; then
            cp -a -- "$BACKUP/original/download-tutorial" "$ROOT/download/$TUTORIAL_NAME" || recovery_failed=1
        fi
    else
        recovery_failed=1
    fi
    if [ "$recovery_failed" -ne 0 ]; then
        printf '%s\\n' "Website rollback incomplete; retained evidence: $BACKUP" >&2
    else
        printf '%s\\n' "Website publish failed; previous managed content restored: $BACKUP" >&2
    fi
    exit "$status"
}}
trap rollback ERR
for name in "${{PUBLISHED[@]}}"; do
    if [ -e "$ROOT/$name" ] || [ -L "$ROOT/$name" ]; then
        mv -- "$ROOT/$name" "$BACKUP/displaced/$name"
    fi
    cp -a -- "$SITE/$name" "$ROOT/$name"
done
if [ -e "$ROOT/tutorial" ] || [ -L "$ROOT/tutorial" ]; then
    mv -- "$ROOT/tutorial" "$BACKUP/displaced/tutorial"
fi
if [ -e "$ROOT/download/$TUTORIAL_NAME" ] || [ -L "$ROOT/download/$TUTORIAL_NAME" ]; then
    mv -- "$ROOT/download/$TUTORIAL_NAME" "$BACKUP/displaced/download-tutorial"
fi
cp -a -- "$SITE/tutorial/$TUTORIAL_NAME" "$ROOT/download/$TUTORIAL_NAME"
for name in "${{PUBLISHED[@]}}"; do chown -R www-data:www-data "$ROOT/$name"; done
chown www-data:www-data "$ROOT/download/$TUTORIAL_NAME"
test -s "$ROOT/download/$INSTALLER_NAME" && test -s "$ROOT/download/$TUTORIAL_NAME"
curl -fsSL --max-time 15 --output "$BACKUP/health-index.html" -H 'Host: shuiliyingxiang.cn' http://127.0.0.1/
grep -q '四大专业' "$BACKUP/health-index.html"
trap - ERR
printf '%s\\n' "$BACKUP"
"""


def deploy() -> None:
    validate_site()
    if not SSH_KEY.is_file():
        raise SystemExit(f"缺少服务器 SSH 私钥：{SSH_KEY}")

    identifier = uuid.uuid4().hex
    remote_stage = f"/var/tmp/album-site-{identifier}"
    remote_archive = f"{remote_stage}/payload.tar.gz"
    remote_backup = f"/var/backups/shuiliyingxiang/pre-site-{identifier}"

    with tempfile.TemporaryDirectory(prefix="album-site-release-") as temp_dir:
        staged_site = Path(temp_dir) / "site"
        shutil.copytree(SITE, staged_site)
        version = _stamp_published_version(staged_site)
        if version:
            print(f"已写入当前安装包版本：{version}")
        else:
            print("没有读到安装包版本，页面只保留 Windows 说明")
        archive = Path(temp_dir) / "website.tar.gz"
        with tarfile.open(archive, "w:gz") as bundle:
            for name in (*PAGES, "site-content.json", "assets", "tutorial"):
                bundle.add(staged_site / name, arcname=name)
        allocation = build_allocation_script(remote_stage, remote_backup)
        _ssh("bash -c " + shlex.quote(allocation))
        _run(
            [
                "scp",
                "-q",
                "-o",
                "BatchMode=yes",
                "-o",
                "ConnectTimeout=10",
                "-i",
                str(SSH_KEY),
                str(archive),
                f"{SERVER_HOST}:{remote_archive}",
            ]
        )

    remote_script = build_remote_script(remote_stage, remote_backup, remote_archive)
    result = _ssh("bash -c " + shlex.quote(remote_script))
    print("宣传网站部署完成，服务器备份：" + result.stdout.strip())


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args()
    if args.validate_only:
        validate_site()
        print("宣传网站静态契约通过")
        return
    deploy()


if __name__ == "__main__":
    main()
