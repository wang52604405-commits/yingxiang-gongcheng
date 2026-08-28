#!/usr/bin/env python3
"""向既有 nginx 的 HTTP server block 增加 ACME location，保留其余配置。"""

from __future__ import annotations

import re
import sys
from pathlib import Path


ACME_LOCATION = """

    # Certbot IP 证书 webroot；保留本 server 中所有既有业务 location。
    location ^~ /.well-known/acme-challenge/ {
        root /var/www/letsencrypt;
        default_type text/plain;
        try_files $uri =404;
    }
"""


def inject_acme_location(source: str) -> str:
    if "well-known/acme-challenge" in source:
        return source
    for match in re.finditer(r"\bserver\s*\{", source):
        brace = source.find("{", match.start())
        depth = 0
        end = None
        for index in range(brace, len(source)):
            if source[index] == "{":
                depth += 1
            elif source[index] == "}":
                depth -= 1
                if depth == 0:
                    end = index + 1
                    break
        if end is None:
            continue
        block = source[match.start() : end]
        if re.search(r"\blisten\s+(?:\[::\]:)?80\b", block):
            return source[: brace + 1] + ACME_LOCATION + source[brace + 1 :]
    raise ValueError("线上 nginx 配置中未找到 listen 80 的 server block")


def main() -> int:
    if len(sys.argv) != 3:
        print("用法：inject_acme_location.py <源配置> <输出配置>", file=sys.stderr)
        return 2
    source_path = Path(sys.argv[1])
    target_path = Path(sys.argv[2])
    try:
        rendered = inject_acme_location(source_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1
    target_path.write_text(rendered, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
