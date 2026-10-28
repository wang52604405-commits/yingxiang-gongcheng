# -*- coding: utf-8 -*-
"""Safely validate and deploy the static marketing website.

The server's download/ directory is deliberately excluded from both promotion
and rollback. Existing installers and tutorials therefore remain untouched.
"""

from __future__ import annotations

import argparse
import os
import re
import shlex
import subprocess
import tarfile
import tempfile
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path


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
    if "/download/工程影像管理平台-安装程序.exe" not in all_text:
        raise SystemExit("宣传网站安装包地址发生变化")
    if re.search(r"aos|vanilla-tilt|data-tilt", all_text, re.IGNORECASE):
        raise SystemExit("页面仍引用过量滚动或倾斜动画")
    if "assets/site.js" not in all_text or "nav-toggle" not in all_text:
        raise SystemExit("宣传网站缺少移动导航")


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


def deploy() -> None:
    validate_site()
    if not SSH_KEY.is_file():
        raise SystemExit(f"缺少服务器 SSH 私钥：{SSH_KEY}")

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    remote_archive = f"/var/tmp/album-site-{timestamp}.tar.gz"
    remote_stage = f"/var/tmp/album-site-{timestamp}"
    remote_backup = f"/var/backups/shuiliyingxiang/pre-site-{timestamp}"

    with tempfile.TemporaryDirectory(prefix="album-site-release-") as temp_dir:
        archive = Path(temp_dir) / "website.tar.gz"
        with tarfile.open(archive, "w:gz") as bundle:
            for item in SITE.iterdir():
                if item.name == "download":
                    continue
                bundle.add(item, arcname=item.name)
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

    root = shlex.quote(REMOTE_ROOT)
    archive_q = shlex.quote(remote_archive)
    stage = shlex.quote(remote_stage)
    backup = shlex.quote(remote_backup)
    pages = " ".join(shlex.quote(name) for name in PAGES)
    remote_script = (
        "set -eu; "
        f"mkdir -p {stage} {backup}; tar -xzf {archive_q} -C {stage}; "
        f"for f in {pages}; do test -s {stage}/$f; done; "
        f"test -s {stage}/assets/style.css; test -s {stage}/assets/site.js; "
        f"grep -q '四大专业' {stage}/index.html; "
        f"for f in {pages} site-content.json assets; do "
        f"if test -e {root}/$f; then cp -a {root}/$f {backup}/; fi; done; "
        f"rollback() {{ rm -rf {root}/assets; rm -f "
        + " ".join(f"{root}/{name}" for name in PAGES)
        + f" {root}/site-content.json; cp -a {backup}/. {root}/; }}; "
        f"trap 'rollback' ERR; cp -a {stage}/. {root}/; "
        f"chown -R www-data:www-data {root}/assets "
        + " ".join(f"{root}/{name}" for name in PAGES)
        + f" {root}/site-content.json; "
        "curl -fsSL --max-time 15 -H 'Host: shuiliyingxiang.cn' "
        "http://127.0.0.1/ | grep -q '四大专业'; "
        "trap - ERR; "
        f"rm -rf {stage}; rm -f {archive_q}; "
        f"printf '%s\\n' {backup}"
    )
    result = _ssh(remote_script)
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
