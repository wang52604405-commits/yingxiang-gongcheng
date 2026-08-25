# -*- coding: utf-8 -*-
"""微信原图分片上传的受控临时文件区。

业务归属和幂等状态由 SQLite 记录；本模块只负责在配置根目录
内原子落片、逐片校验组装和可追踪清理。
"""

from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
import uuid
from pathlib import Path


class ChunkFileError(RuntimeError):
    pass


class ChunkFileStore:
    def __init__(self, root: Path, spool_bytes: int):
        self.root = Path(root).resolve()
        self.spool_bytes = max(1024, int(spool_bytes))
        self.root.mkdir(parents=True, exist_ok=True)

    def session_dir(self, account_id: int, session_id: int) -> Path:
        account = int(account_id)
        session = int(session_id)
        if account < 1 or session < 1:
            raise ChunkFileError("分片会话路径无效")
        target = (self.root / str(account) / str(session)).resolve()
        try:
            target.relative_to(self.root)
        except ValueError as exc:
            raise ChunkFileError("分片会话路径越界") from exc
        return target

    def chunk_path(self, account_id: int, session_id: int, index: int) -> Path:
        chunk_index = int(index)
        if chunk_index < 0:
            raise ChunkFileError("分片索引无效")
        return self.session_dir(account_id, session_id) / f"{chunk_index:06d}.part"

    def read_request_to_temporary(
        self,
        account_id: int,
        session_id: int,
        index: int,
        source,
        expected_size: int,
    ) -> dict:
        directory = self.session_dir(account_id, session_id)
        directory.mkdir(parents=True, exist_ok=True)
        temporary = directory / f".{int(index):06d}.{uuid.uuid4().hex}.tmp"
        digest = hashlib.sha256()
        total = 0
        try:
            with temporary.open("xb") as output:
                while True:
                    chunk = source.read(min(1024 * 1024, int(expected_size) + 1 - total))
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > int(expected_size):
                        raise ChunkFileError("分片大小超过当前索引的预期值")
                    digest.update(chunk)
                    output.write(chunk)
        except Exception as exc:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
            if isinstance(exc, ChunkFileError):
                raise
            if isinstance(exc, OSError):
                raise ChunkFileError("分片临时文件写入失败") from exc
            raise
        if total != int(expected_size):
            temporary.unlink(missing_ok=True)
            raise ChunkFileError("分片大小与当前索引的预期值不一致")
        return {"temporary": temporary, "size_bytes": total, "sha256": digest.hexdigest()}

    def install(self, account_id: int, session_id: int, index: int, temporary: Path) -> Path:
        destination = self.chunk_path(account_id, session_id, index)
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.replace(temporary, destination)
        except OSError as exc:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
            raise ChunkFileError("分片临时文件落盘失败") from exc
        return destination

    def assemble(self, account_id: int, session_id: int, chunks, expected_total: int):
        output = tempfile.SpooledTemporaryFile(max_size=self.spool_bytes, mode="w+b")
        overall = hashlib.sha256()
        total = 0
        try:
            for row in chunks:
                path = self.chunk_path(account_id, session_id, row["chunk_index"])
                per_chunk = hashlib.sha256()
                size = 0
                with path.open("rb") as source:
                    while True:
                        data = source.read(1024 * 1024)
                        if not data:
                            break
                        size += len(data)
                        total += len(data)
                        if total > int(expected_total):
                            raise ChunkFileError("组装后原图大小超出声明")
                        per_chunk.update(data)
                        overall.update(data)
                        output.write(data)
                if size != int(row["size_bytes"]) or per_chunk.hexdigest() != row["sha256"]:
                    raise ChunkFileError("分片文件校验失败，请重新上传")
            if total != int(expected_total):
                raise ChunkFileError("组装后原图大小与声明不一致")
            output.seek(0)
            return output, overall.hexdigest()
        except Exception as exc:
            output.close()
            if isinstance(exc, ChunkFileError):
                raise
            if isinstance(exc, OSError):
                raise ChunkFileError("分片文件缺失或读取失败，请重新上传") from exc
            raise

    def discard_temporary(self, temporary) -> None:
        if not temporary:
            return
        try:
            Path(temporary).unlink(missing_ok=True)
        except OSError:
            pass

    def cleanup(self, account_id: int, session_id: int) -> None:
        target = self.session_dir(account_id, session_id)
        if target == self.root:
            raise ChunkFileError("拒绝清理分片根目录")
        try:
            target.relative_to(self.root)
            if target.exists():
                shutil.rmtree(target)
        except (OSError, ValueError) as exc:
            raise ChunkFileError("分片临时文件清理失败") from exc
