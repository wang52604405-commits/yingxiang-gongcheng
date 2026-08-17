# -*- coding: utf-8 -*-
"""一键构建：PyInstaller -> 防篡改清单 -> Inno 安装器 -> 纯净交付包。

用法：
  python build_all.py
  或双击 build.bat（内部调用本脚本）。
改完代码后跑一次，约 2~3 分钟出最终安装包 + 交付包。
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

USE = Path(__file__).resolve().parent
ISCC = Path(r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe")
PRIVATE_KEY = Path(
    os.environ.get(
        "ALBUM_SIGN_KEY",
        USE / "服务器访问-工程影像管理平台" / "release_guard_private_key.pem",
    )
)
INSTALLER = USE / "客户可发送安装包-Win10" / "发给客户" / "安装程序.exe"
DIST_DIR = USE / "dist" / "工程影像管理平台"


def run(cmd, **kw):
    print(f"\n>>> {' '.join(str(c) for c in cmd)}")
    return subprocess.call(cmd, **kw)


def step1_pyinstaller():
    print("\n[1/5] PyInstaller build onedir ...")
    code = run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "正式版.spec"], cwd=USE)
    return code == 0


def step0_assets():
    """重新压缩前端 JS/CSS 为 .gz，保证服务端 gzip 通道与源文件一致（避免旧 gz 被客户端一年缓存）。"""
    import gzip as _gzip
    targets = sorted((USE / "assets").glob("*.js")) + sorted((USE / "assets").glob("*.css"))
    for name in targets:
        with _gzip.open(USE / "assets" / f"{name.name}.gz", "wb", compresslevel=6) as g:
            g.write(name.read_bytes())
    print(f"  [OK] 已重新压缩 {len(targets)} 个前端资源（.gz）")
    return True


def step2_manifest():
    print("\n[2/5] Rebuild tamper guard manifest ...")
    code = run([sys.executable, "tamper_guard.py", "build", str(DIST_DIR), "--key", str(PRIVATE_KEY)], cwd=USE)
    if code != 0:
        return False
    # 防呆：签名后立即用内置公钥自校验，密钥不匹配时中止发布，
    # 避免再次出现“装上了却因防篡改校验失败无法启动”的问题。
    try:
        import tamper_guard
        ok, problems = tamper_guard.verify_installation(DIST_DIR, force=True)
        if not ok:
            print(f"  [FAIL] 防篡改清单自校验未通过：{problems}")
            return False
        print("  [OK] 防篡改清单自校验通过（密钥与内置公钥匹配）")
    except Exception as exc:
        print(f"  [FAIL] 防篡改自校验异常：{exc}")
        return False
    return True


def step3_inno():
    print("\n[3/5] Compile Inno Setup installer ...")
    code = run([str(ISCC), "安装脚本.iss"], cwd=USE)
    return code == 0


def step4_verify_no_key():
    print("\n[4/5] Verify installer has no private key ...")
    if not PRIVATE_KEY.exists():
        # 私钥不在当前目录（GitHub Actions checkout 无 keys/，被 gitignore 排除）时跳过
        print("  [SKIP] 私钥不在本目录，跳过对比")
        return True
    key = PRIVATE_KEY.read_bytes()
    data = INSTALLER.read_bytes()
    ok = key not in data
    print("  [OK] no private key in installer" if ok else "  [FAIL] private key embedded in installer!")
    return ok


def step5_delivery():
    print("\n[5/5] Build clean delivery zip ...")
    code = run([sys.executable, "make_delivery.py"], cwd=USE)
    return code == 0


def main() -> int:
    if not ISCC.exists():
        print(f"[ERR] Inno Setup 未安装: {ISCC}")
        return 1
    steps = [step0_assets, step1_pyinstaller, step2_manifest, step3_inno, step4_verify_no_key, step5_delivery]
    for step in steps:
        if not step():
            print(f"\n[BUILD FAILED] 步骤失败: {step.__name__}")
            return 1
    print("\n============================================")
    print(" ALL DONE!")
    print(f" Installer : {INSTALLER}")
    print(f" Delivery  : {USE / '客户可发送安装包-Win10' / '工程影像管理平台-正式版交付包-纯净版.zip'}")
    print("============================================")
    return 0


if __name__ == "__main__":
    sys.exit(main())
