# -*- coding: utf-8 -*-
"""
防篡改自校验（tamper_guard）—— 防“AI 逆向 / 一键修改”第一道防线

原理：
  1. 发布前用开发机 Ed25519 私钥对程序文件清单（exe、模板、资源）做 SHA-256 + 签名，
     生成 guard_manifest.dat 放进程序目录；
  2. 程序启动时用内置公钥验签，并逐个比对文件哈希；
  3. 任何人（包括用 AI 工具）改动被保护文件后，校验失败，程序拒绝启动。

私钥只在开发机（E:\\use\\keys\\private_key.pem），绝不分发；篡改者无法重新签名，
只能被拦截。这是提高破解成本的第一道防线，不是绝对不可破解；配合代码签名和
PyArmor 字节码混淆效果更好。

用法：
  python tamper_guard.py build 程序目录 --key 私钥路径   # 生成防篡改清单
  python tamper_guard.py verify 程序目录                 # 校验清单

注意：
  - 开发模式（源码直接运行、未打包 exe）不校验，不影响调试；
  - 紧急恢复：设置环境变量 ALBUM_SKIP_GUARD=1 可临时跳过校验（仅应急）。
"""

import argparse
import base64
import hashlib
import json
import os
import sys
import time
from pathlib import Path

try:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
except Exception:  # pragma: no cover - 构建机/客户端都自带 cryptography
    Ed25519PrivateKey = Ed25519PublicKey = None


MANIFEST_NAME = "guard_manifest.dat"
# 内置公钥（DER base64）的混淆存储：XOR(密钥 tg24) + base64，避免被一键搜索定位
_PUB_X = "OSRdQzY2a3A/VWRDNR53dTYxU3IbC1RZWyZ1BzhQdU49EX9VREgGehpWRwEWK3FtQAV+YRNTRgYhUgYJ"
_XOR_KEY = b"tg24"
_MANIFEST_X = "ExJTRhA4X1UaDlRRBxMcUBUT"  # guard_manifest.dat 的混淆名


def _ux(value: str) -> str:
    data = base64.b64decode(value)
    return bytes(b ^ _XOR_KEY[i % len(_XOR_KEY)] for i, b in enumerate(data)).decode()


def _public_key() -> Ed25519PublicKey:
    if Ed25519PublicKey is None:
        raise RuntimeError("缺少 cryptography 库")
    der = base64.b64decode(_ux(_PUB_X))
    return serialization.load_der_public_key(der)


def _canonical(payload) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def manifest_path(root: Path) -> Path:
    return root / _ux(_MANIFEST_X)


def _protected_files(root: Path):
    """收集需要保护的文件（相对路径，正斜杠）。"""
    rels = []
    for name in ("album_server.exe", "工程影像管理平台.exe"):
        if (root / name).is_file():
            rels.append(name)
    internal = root / "_internal"
    for sub in ("templates", "assets"):
        folder = internal / sub
        if folder.is_dir():
            for path in sorted(folder.rglob("*")):
                if path.is_file():
                    rels.append(str(path.relative_to(root)).replace("\\", "/"))
    return sorted(rels)


def build_manifest(root, private_key_pem, out=None):
    root = Path(root)
    if Ed25519PrivateKey is None:
        raise RuntimeError("缺少 cryptography 库")
    private_key = serialization.load_pem_private_key(Path(private_key_pem).read_bytes(), password=None)
    files = {}
    for rel in _protected_files(root):
        files[rel] = _sha256(root / rel)
    payload = {
        "version": 1,
        "created": time.strftime("%Y-%m-%d %H:%M:%S"),
        "files": files,
    }
    canonical = _canonical(payload)
    signature = private_key.sign(canonical)
    out_path = Path(out) if out else manifest_path(root)
    out_path.write_text(
        base64.b64encode(canonical).decode("ascii") + "\n" + base64.b64encode(signature).decode("ascii"),
        encoding="ascii",
    )
    return len(files)


def verify_installation(root=None, strict=True, force=False):
    """校验程序文件完整性。返回 (是否通过, 问题列表)。开发模式默认通过。"""
    if not force and not getattr(sys, "frozen", False):
        return True, []
    if not force and os.environ.get("ALBUM_SKIP_GUARD") == "1":
        return True, []
    root = Path(root or Path(sys.executable).resolve().parent)
    manifest = manifest_path(root)
    if not manifest.exists():
        return False, ["缺少防篡改清单，程序文件可能被修改过。"]
    try:
        payload_b64, signature_b64 = manifest.read_text(encoding="ascii").splitlines()[:2]
        payload = json.loads(base64.b64decode(payload_b64))
        _public_key().verify(base64.b64decode(signature_b64), _canonical(payload))
    except Exception as exc:
        return False, [f"防篡改清单验签失败（{exc}）。"]
    problems = []
    for rel, expected in (payload.get("files") or {}).items():
        path = root / rel
        if not path.exists():
            problems.append(f"文件缺失：{rel}")
        elif _sha256(path) != expected:
            problems.append(f"文件被修改：{rel}")
    return (not problems), problems


def main():
    parser = argparse.ArgumentParser(description="防篡改清单工具")
    sub = parser.add_subparsers(dest="cmd", required=True)

    build = sub.add_parser("build", help="生成防篡改清单（发布前执行）")
    build.add_argument("root", help="程序目录（如 E:\\use\\dist\\工程影像管理平台）")
    build.add_argument("--key", default=r"E:\use\keys\private_key.pem", help="Ed25519 私钥路径")

    verify = sub.add_parser("verify", help="校验程序目录")
    verify.add_argument("root", help="程序目录")
    args = parser.parse_args()

    if args.cmd == "build":
        count = build_manifest(args.root, args.key)
        print(f"已生成防篡改清单：{manifest_path(Path(args.root))}（{count} 个文件）")
    elif args.cmd == "verify":
        ok, problems = verify_installation(Path(args.root), force=True)
        if ok:
            print("完整性校验通过。")
        else:
            print("完整性校验未通过：")
            for item in problems:
                print(" -", item)
            sys.exit(1)


if __name__ == "__main__":
    main()
