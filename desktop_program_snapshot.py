"""Exclusive desktop program snapshots. Business data and unknown install files are excluded."""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import sys
import uuid

TARGETS = ("album_server.exe", "工程影像管理平台.exe", "guard_manifest.dat", "_internal")
RESERVE_BYTES = 256 * 1024 * 1024
MANIFEST = "program-manifest.json"
MANIFEST_HASH = "program-manifest.sha256"


class SnapshotError(RuntimeError):
    pass


def _absolute(raw: Path) -> Path:
    raw = Path(raw)
    if ".." in raw.parts:
        raise SnapshotError("Parent-directory components are not allowed")
    return raw.absolute()


def _linked(info) -> bool:
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & 0x400)


def _directories(path: Path, *, missing: bool = False) -> Path:
    for item in reversed((path, *path.parents)):
        try:
            info = item.lstat()
        except FileNotFoundError:
            if missing:
                return item.parent
            raise SnapshotError(f"Missing directory: {item}")
        if _linked(info) or not stat.S_ISDIR(info.st_mode):
            raise SnapshotError(f"Linked/reparse/non-directory path refused: {item}")
    return path


def _within(child: Path, parent: Path) -> bool:
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


def _separate(first: Path, second: Path) -> None:
    if _within(first, second) or _within(second, first):
        raise SnapshotError("Program, business-data and replacement roots must not overlap")


def _roots(install: Path, data: Path, snapshot: Path):
    install, data, snapshot = map(_absolute, (install, data, snapshot))
    if install.parent == install:
        raise SnapshotError("A filesystem root cannot be the program directory")
    _directories(install)
    _directories(data)
    _separate(install, data)
    _separate(snapshot, data)
    if _within(install, snapshot):
        raise SnapshotError("Snapshot cannot contain the install root")
    if _within(snapshot, install):
        relative = snapshot.relative_to(install)
        if len(relative.parts) < 2 or relative.parts[0] != ".deployment-snapshots":
            raise SnapshotError("An internal snapshot must be below .deployment-snapshots")
    elif snapshot.parent != install.parent:
        raise SnapshotError("An external snapshot must be a dedicated install sibling")
    nearest = _directories(snapshot, missing=True)
    if install.drive.casefold() != nearest.drive.casefold() or install.stat().st_dev != nearest.stat().st_dev:
        raise SnapshotError("Snapshot and program must share a filesystem for reversible moves")
    return install, data, snapshot


def _identity(path: Path) -> dict:
    info = path.stat()
    return {"path": str(path), "device": info.st_dev, "inode": info.st_ino}


def _hash(path: Path, before) -> str:
    digest = hashlib.sha256()
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(descriptor, "rb") as source:
        opened = os.fstat(source.fileno())
        if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
            raise SnapshotError("Program changed while opening snapshot source")
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
        after = os.fstat(source.fileno())
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise SnapshotError("Program changed while reading snapshot source")
    return digest.hexdigest()


def _inventory(root: Path, *, complete: bool) -> dict:
    _directories(root)
    records = {}

    def visit(path: Path):
        info = path.lstat()
        if _linked(info):
            raise SnapshotError(f"Linked/reparse program target refused: {path}")
        name = path.relative_to(root).as_posix()
        if stat.S_ISDIR(info.st_mode):
            if name != "_internal" and not name.startswith("_internal/"):
                raise SnapshotError(f"Unexpected program directory: {path}")
            records[name] = {"kind": "directory"}
            for child in sorted(path.iterdir()):
                visit(child)
        elif stat.S_ISREG(info.st_mode) and info.st_nlink == 1:
            if name == "_internal":
                raise SnapshotError("_internal must be a directory")
            records[name] = {"kind": "file", "size": info.st_size, "sha256": _hash(path, info), "mode": stat.S_IMODE(info.st_mode)}
        else:
            raise SnapshotError(f"Hardlinked or special program target refused: {path}")

    for name in TARGETS:
        path = root / name
        try:
            path.lstat()
        except FileNotFoundError:
            if complete:
                raise SnapshotError(f"Incomplete program: {name}")
            continue
        visit(path)
    if complete and not any(name.startswith("_internal/") and item["kind"] == "file" for name, item in records.items()):
        raise SnapshotError("Empty program _internal tree")
    return records


def _size(records: dict) -> int:
    return sum(item.get("size", 0) for item in records.values())


def _capacity(root: Path, required: int) -> None:
    if shutil.disk_usage(root).free < required + RESERVE_BYTES:
        raise SnapshotError("Insufficient space; existing program and all snapshots have been retained")


def _copy_targets(source: Path, destination: Path, records: dict) -> None:
    destination.mkdir(mode=0o700)
    for name in TARGETS:
        if name not in records:
            continue
        if name == "_internal":
            shutil.copytree(source / name, destination / name, symlinks=True)
        else:
            shutil.copy2(source / name, destination / name, follow_symlinks=False)
    if _inventory(destination, complete=True) != records:
        raise SnapshotError("Copied program differs from verified source")


def _exclusive_json(path: Path, document: dict) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        json.dump(document, stream, ensure_ascii=False, sort_keys=True)
        stream.flush()
        os.fsync(stream.fileno())


def _plain_bytes(path: Path) -> bytes:
    info = path.lstat()
    if _linked(info) or not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise SnapshotError("Snapshot manifest is linked or invalid")
    return path.read_bytes()


@contextlib.contextmanager
def _lock(install: Path):
    directory = install / ".deployment-snapshots"
    _directories(directory, missing=True)
    directory.mkdir(mode=0o700, exist_ok=True)
    lock = directory / ".program-transaction.lock"
    descriptor = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.close(descriptor)
        yield
    finally:
        lock.unlink()


def create(install: Path, data: Path, snapshot: Path, version: str, replacement: Path) -> dict:
    install, data, snapshot = _roots(install, data, snapshot)
    if not version or len(version) > 128 or any(ord(character) < 32 for character in version):
        raise SnapshotError("A verified previous version is required")
    replacement = _absolute(replacement)
    _directories(replacement)
    for other in (install, data, snapshot):
        _separate(replacement, other)
    with _lock(install):
        records = _inventory(install, complete=True)
        incoming = _inventory(replacement, complete=True)
        _capacity(install, 2 * _size(records) + _size(incoming))
        _directories(snapshot.parent, missing=True)
        snapshot.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        snapshot.mkdir(mode=0o700)  # No reuse, truncation or overwrite, including dangling links.
        _copy_targets(install, snapshot / "program", records)
        if _inventory(install, complete=True) != records:
            raise SnapshotError("Installed program changed while creating snapshot")
        document = {"schema": 1, "version": version, "install": _identity(install), "data": _identity(data), "targets": list(TARGETS), "files": records}
        _exclusive_json(snapshot / MANIFEST, document)
        checksum = hashlib.sha256((snapshot / MANIFEST).read_bytes()).hexdigest()
        with (snapshot / MANIFEST_HASH).open("x", encoding="ascii") as output:
            output.write(checksum)
    return {"ok": True, "action": "create", "version": version, "snapshot": str(snapshot)}


def verify(install: Path, data: Path, snapshot: Path) -> dict:
    install, data, snapshot = _roots(install, data, snapshot)
    _directories(snapshot)
    content = _plain_bytes(snapshot / MANIFEST)
    if hashlib.sha256(content).hexdigest().encode("ascii") != _plain_bytes(snapshot / MANIFEST_HASH):
        raise SnapshotError("Snapshot manifest SHA-256 differs")
    document = json.loads(content)
    if not isinstance(document, dict) or document.get("schema") != 1 or document.get("targets") != list(TARGETS):
        raise SnapshotError("Snapshot schema or program target allowlist differs")
    if document.get("install") != _identity(install) or document.get("data") != _identity(data):
        raise SnapshotError("Snapshot belongs to another install or business-data root")
    if not isinstance(document.get("version"), str) or not document["version"]:
        raise SnapshotError("Snapshot previous version is missing")
    actual = _inventory(snapshot / "program", complete=True)
    if actual != document.get("files"):
        raise SnapshotError("Snapshot hashes or program file inventory differ")
    return {"ok": True, "action": "verify", "version": document["version"], "snapshot": str(snapshot)}


def _move(source: Path, destination: Path):
    try:
        destination.lstat()
    except FileNotFoundError:
        os.rename(source, destination)
    else:
        raise SnapshotError(f"Refusing to overwrite retained program evidence: {destination}")


def restore(install: Path, data: Path, snapshot: Path) -> dict:
    install, data, snapshot = _roots(install, data, snapshot)
    with _lock(install):
        result = verify(install, data, snapshot)
        saved = _inventory(snapshot / "program", complete=True)
        current = _inventory(install, complete=False)  # Partial failed replacements are allowed; linked targets are not.
        _capacity(install, _size(saved))
        identifier = uuid.uuid4().hex
        stage = snapshot / ("restore-stage-" + identifier)
        failed = snapshot / ("failed-program-" + identifier)
        interrupted = snapshot / ("interrupted-restore-" + identifier)
        _copy_targets(snapshot / "program", stage, saved)
        if _inventory(install, complete=False) != current:
            raise SnapshotError("Live program changed while staging restore; no program was moved")
        failed.mkdir(mode=0o700)
        interrupted.mkdir(mode=0o700)
        _exclusive_json(failed / "program-inventory.json", {"files": current})
        changes = []
        try:
            for name in TARGETS:
                change = {"name": name, "displaced": False, "installed": False}
                changes.append(change)
                try:
                    (install / name).lstat()
                except FileNotFoundError:
                    pass
                else:
                    _move(install / name, failed / name)
                    change["displaced"] = True
                _move(stage / name, install / name)
                change["installed"] = True
            if _inventory(install, complete=True) != saved:
                raise SnapshotError("Restored program did not match saved program")
        except (OSError, SnapshotError) as error:
            recovery_errors = []
            for change in reversed(changes):
                name = change["name"]
                try:
                    if change["installed"]:
                        _move(install / name, interrupted / name)
                    if change["displaced"]:
                        _move(failed / name, install / name)
                except (OSError, SnapshotError) as recovery_error:
                    recovery_errors.append(str(recovery_error))
            try:
                if _inventory(install, complete=False) != current:
                    recovery_errors.append("Live program differs after reversing restore")
            except (OSError, SnapshotError) as recovery_error:
                recovery_errors.append(str(recovery_error))
            message = "Program restore failed; " + ("recovery also failed, inspect retained evidence" if recovery_errors else "previous live program was put back")
            raise SnapshotError(f"{message}: {snapshot}; {error}") from error
        return {**result, "action": "restore", "failed_program": str(failed)}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("create", "verify", "restore"))
    parser.add_argument("--install-root", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--version")
    parser.add_argument("--replacement-root", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.action == "create":
            if not args.version or args.replacement_root is None:
                raise SnapshotError("create requires --version and --replacement-root")
            result = create(args.install_root, args.data_root, args.snapshot, args.version, args.replacement_root)
        else:
            result = (verify if args.action == "verify" else restore)(args.install_root, args.data_root, args.snapshot)
        print(json.dumps(result, ensure_ascii=True))
        return 0
    except (OSError, ValueError, SnapshotError) as error:
        print("Program snapshot stopped: " + ascii(str(error)), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
