# -*- coding: utf-8 -*-
"""在 SQLite 备份副本上验证微信小程序 V1 的增量迁移。

该脚本永远不直接迁移传入的源文件：必须另给 ``--copy`` 和显式的
``--copy-root`` 安全根目录，脚本排他创建 0600 副本，再只对副本建新表/索引并
核对旧业务表行数与数据库完整性。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import sqlite3
import stat
from pathlib import Path


LEGACY_TABLES = (
    "accounts",
    "licenses",
    "machines",
    "invites",
    "cloud_projects",
    "cloud_thumbs",
    "mail_codes",
    "product_settings",
    "client_error_logs",
)

MOBILE_TABLES = (
    "wechat_bindings",
    "cloud_engineering_projects",
    "cloud_units",
    "mobile_batches",
    "cloud_photos",
    "mobile_jobs",
    "desktop_sync_cursors",
    "mobile_upload_sessions",
    "mobile_upload_chunks",
)


# 允许读取经过 SQLite backup API 生成的 /opt/album-auth/backups 副本，
# 但绝不允许把在线代码、配置或活动数据库当作验证输入/输出。
LIVE_ROOTS = (
    Path("/opt/album-auth/server"),
    Path("/opt/album-auth/data"),
    Path("/etc/album-auth"),
    Path("/var/lib/album-auth"),
    Path("/opt/album-auth-staging/server"),
    Path("/etc/album-auth-staging"),
    Path("/var/lib/album-auth-staging"),
)


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _reject_live_path(path: Path, label: str) -> None:
    if os.name == "nt":
        return
    for raw_root in LIVE_ROOTS:
        root = raw_root.resolve()
        if _is_within(path, root):
            raise SystemExit(f"{label} 落入在线目录，拒绝操作：{path}")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while True:
            block = stream.read(1024 * 1024)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def _secure_copy(source: Path, destination: Path, copy_root: Path) -> str:
    """只读打开稳定备份，并以 O_EXCL/0600 创建迁移副本。"""
    source_lstat = source.lstat()
    if source.is_symlink() or not stat.S_ISREG(source_lstat.st_mode):
        raise SystemExit(f"源备份必须是普通非链接文件：{source}")
    if source_lstat.st_nlink != 1:
        raise SystemExit(f"源备份存在硬链接，无法证明与在线库隔离：{source}")
    if os.name != "nt":
        source_mode = stat.S_IMODE(source_lstat.st_mode)
        if source_lstat.st_uid != os.geteuid() or source_mode & 0o077:
            raise SystemExit(
                f"源备份必须归当前用户独占且权限为 0600：{source}（{source_mode:04o}）"
            )
    for suffix in ("-wal", "-shm"):
        sidecar = Path(str(source) + suffix)
        if sidecar.exists() and sidecar.stat().st_size:
            raise SystemExit(f"源备份仍有 SQLite {suffix}，不是稳定 backup 副本：{sidecar}")

    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    resolved_parent = destination.parent.resolve()
    if not _is_within(resolved_parent, copy_root):
        raise SystemExit(f"--copy 父目录越出 --copy-root：{resolved_parent}")
    cursor = copy_root
    for part in resolved_parent.relative_to(copy_root).parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise SystemExit(f"--copy 路径包含符号链接：{cursor}")

    before_hash = _sha256(source)
    source_flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    destination_flags = (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_NOFOLLOW", 0)
    )
    source_fd = os.open(source, source_flags)
    destination_fd = None
    try:
        opened = os.fstat(source_fd)
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_dev != source_lstat.st_dev
            or opened.st_ino != source_lstat.st_ino
        ):
            raise SystemExit("源备份在打开期间被替换，拒绝迁移")
        destination_fd = os.open(destination, destination_flags, 0o600)
        with os.fdopen(source_fd, "rb", closefd=False) as source_stream, os.fdopen(
            destination_fd, "wb", closefd=False
        ) as destination_stream:
            while True:
                block = source_stream.read(1024 * 1024)
                if not block:
                    break
                destination_stream.write(block)
            destination_stream.flush()
            os.fsync(destination_stream.fileno())
    except Exception:
        if destination_fd is not None:
            try:
                os.close(destination_fd)
            except OSError:
                pass
            destination_fd = None
        destination.unlink(missing_ok=True)
        raise
    finally:
        os.close(source_fd)
        if destination_fd is not None:
            os.close(destination_fd)

    os.chmod(destination, 0o600)
    after_hash = _sha256(source)
    if before_hash != after_hash:
        destination.unlink(missing_ok=True)
        raise SystemExit("复制期间源备份内容发生变化，已删除不可信副本")
    if _sha256(destination) != before_hash:
        destination.unlink(missing_ok=True)
        raise SystemExit("迁移副本与源备份 SHA-256 不一致")
    return before_hash


def _counts(database: Path, tables) -> dict[str, int]:
    connection = sqlite3.connect(database)
    try:
        existing = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        return {
            table: int(connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])
            for table in tables
            if table in existing
        }
    finally:
        connection.close()


def _integrity(database: Path) -> tuple[str, list[tuple]]:
    connection = sqlite3.connect(database)
    try:
        integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
        foreign_key_errors = [tuple(row) for row in connection.execute("PRAGMA foreign_key_check")]
        return integrity, foreign_key_errors
    finally:
        connection.close()


def main() -> int:
    os.umask(0o077)
    parser = argparse.ArgumentParser(description="在独立副本验证移动端增量数据库迁移")
    parser.add_argument("--source", required=True, help="由 SQLite backup 生成的稳定备份文件")
    parser.add_argument("--copy", required=True, help="用于迁移测试的新副本路径，必须尚不存在")
    parser.add_argument(
        "--copy-root",
        required=True,
        help="允许创建迁移副本的专用安全根目录；--copy 必须严格位于其下",
    )
    parser.add_argument("--expected-accounts", type=int)
    parser.add_argument("--expected-projects", type=int)
    parser.add_argument("--expected-thumbs", type=int)
    args = parser.parse_args()

    source_input = Path(args.source).expanduser()
    destination_input = Path(args.copy).expanduser()
    copy_root_input = Path(args.copy_root).expanduser()
    if source_input.is_symlink():
        raise SystemExit(f"源备份不得是符号链接：{source_input}")
    if destination_input.is_symlink():
        raise SystemExit(f"--copy 不得是符号链接：{destination_input}")
    if copy_root_input.is_symlink():
        raise SystemExit(f"--copy-root 不得是符号链接：{copy_root_input}")
    source = source_input.resolve()
    destination = destination_input.resolve()
    copy_root = copy_root_input.resolve()
    if not source.is_file():
        raise SystemExit(f"源备份不存在：{source}")
    if source == destination:
        raise SystemExit("--copy 不能与 --source 相同；拒绝直接迁移源备份")
    if not copy_root.is_dir() or copy_root.is_symlink():
        raise SystemExit(f"--copy-root 必须是已存在的普通目录：{copy_root}")
    if destination == copy_root or not _is_within(destination, copy_root):
        raise SystemExit(f"--copy 必须严格位于 --copy-root 下：{destination}")
    _reject_live_path(source, "--source")
    _reject_live_path(copy_root, "--copy-root")
    _reject_live_path(destination, "--copy")
    if os.name != "nt":
        root_stat = copy_root.stat()
        root_mode = stat.S_IMODE(root_stat.st_mode)
        if root_stat.st_uid != os.geteuid() or root_mode & 0o077:
            raise SystemExit(
                f"--copy-root 必须归当前用户独占且权限为 0700："
                f"{copy_root}（{root_mode:04o}）"
            )
    if destination.exists():
        raise SystemExit(f"测试副本已存在，拒绝覆盖：{destination}")

    source_sha256 = _secure_copy(source, destination, copy_root)
    before = _counts(destination, LEGACY_TABLES)
    integrity_before, foreign_keys_before = _integrity(destination)
    if integrity_before != "ok":
        raise SystemExit(f"源备份完整性检查失败：{integrity_before}")

    expected = {
        "accounts": args.expected_accounts,
        "cloud_projects": args.expected_projects,
        "cloud_thumbs": args.expected_thumbs,
    }
    mismatches = {
        key: {"expected": value, "actual": before.get(key)}
        for key, value in expected.items()
        if value is not None and before.get(key) != value
    }
    if mismatches:
        raise SystemExit("源备份数量不符合预期：" + json.dumps(mismatches, ensure_ascii=False))

    secret_path = destination.parent / ".server_secret"
    if secret_path.is_symlink():
        raise SystemExit(f"迁移目录存在 .server_secret 符号链接：{secret_path}")
    secret_before = (
        (secret_path.stat().st_size, _sha256(secret_path))
        if secret_path.is_file() and not secret_path.is_symlink()
        else None
    )
    # server.config 导入时若没有显式 secret，会在 DATA_DIR 写 .server_secret。
    # 验证器只注入进程内一次性 secret，不让迁移测试产生或改写任何凭据文件。
    os.environ["ALBUM_SERVER_SECRET"] = secrets.token_hex(32)
    os.environ["ALBUM_SERVER_DB"] = str(destination)
    os.environ["ALBUM_SERVER_DATA"] = str(destination.parent)
    os.environ["ALBUM_SERVER_PRIVATE_KEY"] = str(copy_root / ".migration-key-not-used")
    from server import db  # 环境变量设置后再导入配置

    db.init_db()
    after = _counts(destination, LEGACY_TABLES)
    mobile = _counts(destination, MOBILE_TABLES)

    integrity, foreign_key_errors = _integrity(destination)
    secret_after = (
        (secret_path.stat().st_size, _sha256(secret_path))
        if secret_path.is_file() and not secret_path.is_symlink()
        else None
    )
    if secret_after != secret_before:
        raise SystemExit("迁移验证意外创建或改写了 .server_secret")
    if _sha256(source) != source_sha256:
        raise SystemExit("迁移期间源备份内容发生变化")

    if before != after:
        raise SystemExit(
            "旧业务表数量发生变化："
            + json.dumps({"before": before, "after": after}, ensure_ascii=False)
        )
    if set(mobile) != set(MOBILE_TABLES):
        raise SystemExit("移动端表未完整创建：" + json.dumps(mobile, ensure_ascii=False))
    # 旧库可能已有历史外键孤儿记录。本验证器不擅自修复旧数据，只要求
    # 增量迁移不增加、删除或改变这些历史问题。
    if integrity != "ok" or foreign_key_errors != foreign_keys_before:
        raise SystemExit(
            "数据库完整性检查失败："
            + json.dumps(
                {
                    "integrity": integrity,
                    "foreign_key_errors_before": foreign_keys_before[:20],
                    "foreign_key_errors_after": foreign_key_errors[:20],
                },
                ensure_ascii=False,
            )
        )

    print(
        json.dumps(
            {
                "ok": True,
                "source": str(source),
                "source_sha256": source_sha256,
                "copy": str(destination),
                "copy_root": str(copy_root),
                "copy_mode": f"{stat.S_IMODE(destination.stat().st_mode):04o}",
                "legacy_counts_unchanged": after,
                "mobile_tables": mobile,
                "integrity": integrity,
                "preexisting_foreign_key_errors_unchanged": foreign_key_errors,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
