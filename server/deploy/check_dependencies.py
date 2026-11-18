#!/usr/bin/env python3
"""Validate the existing interpreter without installing or changing any package."""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import subprocess
import sys


class DependencyCheckError(RuntimeError):
    pass


def check_dependencies(requirements: Path) -> dict:
    # pip is already part of the live venv. Its bundled parser avoids installing
    # another package merely to decide whether deployment is safe.
    try:
        from pip._vendor.packaging.requirements import InvalidRequirement, Requirement
        from pip._vendor.packaging.utils import canonicalize_name
        from pip._vendor.packaging.version import InvalidVersion, Version
    except ImportError as exc:
        raise DependencyCheckError("当前解释器缺少依赖校验工具，停止发布") from exc

    source = requirements.read_bytes()
    try:
        lines = source.decode("utf-8-sig").splitlines()
    except UnicodeError as exc:
        raise DependencyCheckError("依赖清单必须使用 UTF-8，停止发布") from exc
    checked = 0
    for number, raw in enumerate(lines, 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        # Includes, options, continuations and URLs need a separately reviewed
        # dependency rollout. Never fall back to executing pip install.
        if line.startswith("-") or "\\" in line:
            raise DependencyCheckError(f"依赖清单第 {number} 行使用了不支持的格式，停止发布")
        try:
            requirement = Requirement(line)
            active = requirement.marker is None or requirement.marker.evaluate()
        except (InvalidRequirement, ValueError) as exc:
            raise DependencyCheckError(f"依赖清单第 {number} 行无法可靠校验，停止发布") from exc
        if not active:
            continue
        if requirement.url or requirement.extras:
            raise DependencyCheckError(f"依赖清单第 {number} 行需要独立依赖更新，停止发布")
        name = canonicalize_name(requirement.name)
        try:
            installed = importlib.metadata.version(requirement.name)
        except importlib.metadata.PackageNotFoundError as exc:
            raise DependencyCheckError(f"当前环境缺少 {name}，停止发布；本流程不会安装依赖") from exc
        try:
            satisfies = requirement.specifier.contains(Version(installed), prereleases=True)
        except InvalidVersion as exc:
            raise DependencyCheckError(f"当前环境的 {name} 版本无法可靠校验，停止发布") from exc
        if not satisfies:
            raise DependencyCheckError(f"当前环境的 {name} 不满足版本要求，停止发布；本流程不会更新依赖")
        checked += 1
    if not checked:
        raise DependencyCheckError("依赖清单没有当前环境可校验的依赖，停止发布")

    def installed_versions():
        versions = {}
        for distribution in importlib.metadata.distributions():
            name = canonicalize_name(distribution.metadata.get("Name") or "")
            if not name or name in versions:
                raise DependencyCheckError("当前环境有缺失或重复的包元数据，停止发布")
            versions[name] = distribution.version
        return dict(sorted(versions.items()))

    before = installed_versions()
    environment = {**os.environ, "PIP_DISABLE_PIP_VERSION_CHECK": "1", "PIP_NO_CACHE_DIR": "1", "PYTHONDONTWRITEBYTECODE": "1"}
    result = subprocess.run(
        [sys.executable, "-B", "-m", "pip", "--disable-pip-version-check", "--no-cache-dir", "check"],
        capture_output=True, text=True, env=environment, timeout=120,
    )
    if result.returncode:
        # Do not echo arbitrary installed metadata or subprocess output into CI.
        raise DependencyCheckError("当前环境存在缺失或冲突的间接依赖，停止发布；本流程不会修复依赖")
    after = installed_versions()
    if before != after:
        raise DependencyCheckError("校验期间依赖环境发生变化，停止发布")
    report = {
        "interpreter": sys.executable,
        "python_version": sys.version.split()[0],
        "requirements_sha256": hashlib.sha256(source).hexdigest(),
        "checked_requirements": checked,
        "installed_versions": after,
    }
    encoded = json.dumps(report, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return {**report, "sha256": hashlib.sha256(encoded).hexdigest()}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--requirements", required=True, type=Path)
    parser.add_argument("--snapshot", type=Path, help="Optional new evidence file; existing files are never overwritten")
    args = parser.parse_args(argv)
    try:
        report = check_dependencies(args.requirements)
        if args.snapshot is not None:
            # The deploy backup directory is created with mode 0700. Exclusive
            # creation also refuses existing files and symlinks.
            descriptor = os.open(args.snapshot, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as output:
                json.dump(report, output, ensure_ascii=False, indent=2, sort_keys=True)
                output.write("\n")
        print(f"DEPENDENCIES_UNCHANGED distributions={len(report['installed_versions'])} sha256={report['sha256']}")
        return 0
    except (DependencyCheckError, OSError, subprocess.SubprocessError):
        # Dependency failures are intentionally fatal before code/config changes.
        error = sys.exc_info()[1]
        print(str(error) if isinstance(error, DependencyCheckError) else "无法完成依赖只读校验或保存校验凭据，停止发布", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
