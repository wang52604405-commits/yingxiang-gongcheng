"""Restore application code only, without importing a backup or touching business data.

The caller stops/restarts the service and checks health. prepare saves both sets of
allowlisted files in an exclusive directory; apply/recover verify those saved bytes.
Deployment controls, service configuration, databases and all media stay in place.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import tempfile
from pathlib import Path


SERVER_FILES = (
    "app.py", "admin_ops.py", "config.py", "db.py", "mailer.py", "mobile_api.py",
    "mobile_storage.py", "mobile_recognition.py", "mobile_chunks.py", "__init__.py",
    "requirements.txt", "templates/admin.html", "templates/cloud.html",
    "templates/member_center.html",
)
RUNTIME_FILES = (
    "municipal_rules.py", "professional_templates.py", "assets/professional_templates.json",
)
MANAGED_FILES = tuple(f"server/{name}" for name in SERVER_FILES) + RUNTIME_FILES
REQUIRED_FILES = tuple(f"server/{name}" for name in SERVER_FILES)
MANIFEST = "prepared.json"


class RollbackError(RuntimeError):
    pass


def _absolute(path: Path) -> Path:
    path = Path(path)
    if ".." in path.parts:
        raise RollbackError(f"拒绝含上级目录的路径：{path}")
    return path.absolute()


def _directory(path: Path) -> None:
    for directory in reversed((path, *path.parents)):
        try:
            mode = directory.lstat().st_mode
        except FileNotFoundError as error:
            raise RollbackError(f"目录不存在：{directory}") from error
        if not stat.S_ISDIR(mode) or stat.S_ISLNK(mode):
            raise RollbackError(f"目录必须是真实目录，不能是链接：{directory}")


def _path(root: Path, relative: str, *, create_parent: bool = False, directory_mode: int = 0o700) -> Path:
    """Check each component without resolving through symlinks, including absent files."""
    _directory(root)
    path = root / relative
    cursor = root
    for part in Path(relative).parts[:-1]:
        cursor /= part
        try:
            mode = cursor.lstat().st_mode
        except FileNotFoundError:
            if not create_parent:
                return path
            cursor.mkdir(mode=directory_mode)
            cursor.chmod(directory_mode)
            mode = cursor.lstat().st_mode
        if not stat.S_ISDIR(mode) or stat.S_ISLNK(mode):
            raise RollbackError(f"拒绝链接或非目录路径：{cursor}")
    return path


def _read(root: Path, relative: str) -> tuple[bytes, int, int, int] | None:
    path = _path(root, relative)
    try:
        before = path.lstat()
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
        raise RollbackError(f"文件必须是无硬链接的普通文件：{path}")
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(descriptor, "rb") as stream:
        opened = os.fstat(stream.fileno())
        if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
            raise RollbackError(f"读取期间文件发生变化：{path}")
        content = stream.read()
        after = os.fstat(stream.fileno())
    if (after.st_size, after.st_mtime_ns) != (before.st_size, before.st_mtime_ns):
        raise RollbackError(f"读取期间文件发生变化：{path}")
    return content, stat.S_IMODE(before.st_mode), before.st_uid, before.st_gid


def _exclusive(root: Path, relative: str, content: bytes) -> None:
    path = _path(root, relative, create_parent=True)
    with path.open("xb") as stream:
        os.chmod(path, 0o600)
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())


def _roots(app_root: Path, state: Path) -> tuple[Path, Path]:
    app_root, state = _absolute(app_root), _absolute(state)
    _directory(app_root / "server")
    _directory(app_root / "backups")
    if state.parent != app_root / "backups" or not state.name.startswith("pre-rollback-"):
        raise RollbackError("回退前快照必须是 backups 下直接的 pre-rollback-* 目录")
    return app_root, state


def prepare(app_root: Path, backup: Path, state: Path) -> Path:
    app_root, state = _roots(app_root, state)
    backup = _absolute(backup)
    if backup.parent != app_root / "backups" or not backup.name.startswith("deploy-"):
        raise RollbackError("只允许 backups 下直接的 deploy-* 备份")
    _directory(backup / "server")
    # Older deploy.sh snapshots have no record of absent root modules. Guessing
    # absence could remove required modules, so require an explicitly complete set.
    if _read(backup, "runtime/.snapshot-ready") is None:
        raise RollbackError("备份缺少 runtime/.snapshot-ready，无法确认根运行文件是否完整；请先核实备份")

    current, target = {}, {}
    for name in MANAGED_FILES:
        current[name] = _read(app_root, name)
        source = name if name.startswith("server/") else f"runtime/{name}"
        target[name] = _read(backup, source)
    for name in REQUIRED_FILES:
        if current[name] is None or target[name] is None:
            raise RollbackError(f"代码备份不完整，缺少：{name}")
    if current["server/requirements.txt"][0] != target["server/requirements.txt"][0]:
        raise RollbackError("备份依赖清单与当前版本不同；不会自动安装依赖，请先核实兼容性")
    for name, entry in target.items():
        if entry is not None and name.endswith(".py"):
            compile(entry[0], name, "exec")  # Parse only; never import/execute backup code.

    state.mkdir(mode=0o700)  # Exclusive: a collision must never overwrite saved code.
    manifest = {"version": 1, "app_root": str(app_root), "current": {}, "target": {}}
    for group, entries in (("current", current), ("target", target)):
        for name, entry in entries.items():
            metadata = None
            if entry is not None:
                content, mode, uid, gid = entry
                _exclusive(state, f"{group}/{name}", content)
                metadata = {"sha256": hashlib.sha256(content).hexdigest(), "mode": mode, "uid": uid, "gid": gid}
            manifest[group][name] = metadata
    _exclusive(state, MANIFEST, json.dumps(manifest, ensure_ascii=False).encode("utf-8"))
    return state


def restore(app_root: Path, state: Path, group: str) -> None:
    app_root, state = _roots(app_root, state)
    _directory(state)
    document = _read(state, MANIFEST)
    if document is None:
        raise RollbackError("回退前快照尚未准备完成，拒绝修改代码")
    manifest = json.loads(document[0])
    if not isinstance(manifest, dict) or manifest.get("version") != 1 or manifest.get("app_root") != str(app_root):
        raise RollbackError("快照版本或目标目录不匹配")
    if group not in ("current", "target") or not isinstance(manifest.get(group), dict) or set(manifest[group]) != set(MANAGED_FILES):
        raise RollbackError("快照白名单不完整或包含额外路径")

    # Validate the entire operation before the first mutation.
    contents = {}
    for name, metadata in manifest[group].items():
        _read(app_root, name)  # Reject linked destinations, even when removing a file.
        entry = _read(state, f"{group}/{name}")
        if metadata is None:
            if entry is not None:
                raise RollbackError(f"缺失记录与快照文件冲突：{name}")
        elif (
            not isinstance(metadata, dict) or entry is None
            or hashlib.sha256(entry[0]).hexdigest() != metadata.get("sha256")
            or not isinstance(metadata.get("mode"), int)
            or metadata["mode"] & ~0o777
            or not isinstance(metadata.get("uid"), int) or metadata["uid"] < 0
            or not isinstance(metadata.get("gid"), int) or metadata["gid"] < 0
        ):
            raise RollbackError(f"快照文件校验失败：{name}")
        contents[name] = entry

    for name, entry in contents.items():
        path = _path(app_root, name, create_parent=entry is not None, directory_mode=0o755)
        if entry is None:
            path.unlink(missing_ok=True)
            continue
        descriptor, temporary = tempfile.mkstemp(prefix=".code-rollback-", dir=path.parent)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(entry[0])
                stream.flush()
                os.fsync(stream.fileno())
            metadata = manifest[group][name]
            if hasattr(os, "chown"):
                os.chown(temporary, metadata["uid"], metadata["gid"])
            os.chmod(temporary, metadata["mode"])
            os.replace(temporary, path)
        finally:
            Path(temporary).unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "apply", "recover"))
    parser.add_argument("--app-root", type=Path, default=Path("/opt/album-auth"))
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--backup", type=Path)
    args = parser.parse_args()
    try:
        if args.action == "prepare":
            if args.backup is None:
                parser.error("prepare requires --backup")
            prepare(args.app_root, args.backup, args.state)
        else:
            restore(args.app_root, args.state, "target" if args.action == "apply" else "current")
    except (OSError, ValueError, SyntaxError, RollbackError) as error:
        raise SystemExit(f"代码回退已停止：{error}") from error


if __name__ == "__main__":
    main()
