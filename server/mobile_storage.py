# -*- coding: utf-8 -*-
"""移动影像私有对象存储抽象。

生产使用阿里云 OSS SDK v2；本地与测试使用受控目录。调用方只保存对象键，
不会把 AccessKey、AppSecret 或本地绝对路径写入数据库。
"""

from __future__ import annotations

import os
import shutil
import uuid
from datetime import timedelta
from pathlib import Path, PurePosixPath
from urllib.parse import urlparse

from . import config


class StorageError(RuntimeError):
    """对象存储不可用或配置不完整。"""


def _validate_key(key: str) -> str:
    value = str(key or "").replace("\\", "/").strip()
    path = PurePosixPath(value)
    if (
        not value
        or value.startswith("/")
        or path.is_absolute()
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise StorageError("对象键不安全")
    return value


class LocalObjectStorage:
    backend = "local"

    def __init__(self, root: Path):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def path_for(self, key: str) -> Path:
        safe_key = _validate_key(key)
        path = (self.root / Path(*PurePosixPath(safe_key).parts)).resolve()
        try:
            path.relative_to(self.root)
        except ValueError as exc:
            raise StorageError("对象键越界") from exc
        return path

    def put_bytes(self, key: str, data: bytes, content_type: str) -> None:
        del content_type
        path = self.path_for(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        try:
            temporary.write_bytes(data)
            os.replace(temporary, path)
        except OSError as exc:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
            raise StorageError("本地对象存储写入失败") from exc

    def put_stream(self, key: str, stream, size_bytes: int, content_type: str) -> None:
        del content_type
        path = self.path_for(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        try:
            stream.seek(0)
            with temporary.open("wb") as target:
                shutil.copyfileobj(stream, target, length=1024 * 1024)
            if temporary.stat().st_size != int(size_bytes):
                raise StorageError("原图流长度与已验证长度不一致")
            os.replace(temporary, path)
        except StorageError:
            temporary.unlink(missing_ok=True)
            raise
        except OSError as exc:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
            raise StorageError("本地对象存储写入失败") from exc

    def delete(self, key: str) -> None:
        try:
            self.path_for(key).unlink(missing_ok=True)
        except OSError as exc:
            raise StorageError("本地对象删除失败") from exc

    def get_bytes(self, key: str, max_bytes: int) -> bytes:
        try:
            with self.path_for(key).open("rb") as stream:
                data = stream.read(max_bytes + 1)
        except OSError as exc:
            raise StorageError("本地对象读取失败") from exc
        if len(data) > max_bytes:
            raise StorageError("对象大小超过读取限制")
        return data

    def signed_url(self, key: str, expires_seconds: int) -> str:
        del key, expires_seconds
        # 本地地址由 mobile_api 生成带时效签名的受控下载 URL。
        return ""


class OssObjectStorage:
    backend = "oss"

    def __init__(
        self,
        region: str,
        preview_bucket: str,
        original_bucket: str,
        endpoint: str = "",
    ):
        if not region or not preview_bucket or not original_bucket:
            raise StorageError("OSS 地域、永久预览 Bucket 或原图中转 Bucket 未配置")
        if preview_bucket == original_bucket:
            raise StorageError("原图中转 Bucket 必须与永久预览 Bucket 分离")
        try:
            import alibabacloud_oss_v2 as oss
            from alibabacloud_credentials.client import Client as CredentialClient
        except ImportError as exc:
            raise StorageError("未安装阿里云 OSS SDK v2") from exc

        # Default Credential Provider Chain 会优先取安全的外部配置，并可在 ECS
        # 上通过 IMDSv2 自动刷新实例 RAM 角色的 STS 凭据。
        credential_client = CredentialClient()

        def load_credentials():
            credential = credential_client.get_credential()
            return oss.types.Credentials(
                credential.get_access_key_id(),
                credential.get_access_key_secret(),
                credential.get_security_token() or None,
            )

        cfg = oss.config.load_default()
        cfg.credentials_provider = oss.credentials.CredentialsProviderFunc(load_credentials)
        cfg.region = region
        if endpoint:
            cfg.endpoint = endpoint
        self.oss = oss
        self.client = oss.Client(cfg)
        self.preview_bucket = preview_bucket
        self.original_bucket = original_bucket

    def bucket_for(self, key: str) -> str:
        safe_key = _validate_key(key)
        return (
            self.original_bucket
            if "/photos/" in f"/{safe_key}" and "/previews/" not in f"/{safe_key}"
            else self.preview_bucket
        )

    def put_bytes(self, key: str, data: bytes, content_type: str) -> None:
        safe_key = _validate_key(key)
        bucket = self.bucket_for(safe_key)
        try:
            self.client.put_object(
                self.oss.PutObjectRequest(
                    bucket=bucket,
                    key=safe_key,
                    body=data,
                    content_type=content_type,
                    server_side_encryption="AES256",
                )
            )
        except Exception as exc:
            raise StorageError("OSS 上传失败") from exc

    def put_stream(self, key: str, stream, size_bytes: int, content_type: str) -> None:
        del size_bytes
        safe_key = _validate_key(key)
        bucket = self.bucket_for(safe_key)
        try:
            stream.seek(0)
            self.client.put_object(
                self.oss.PutObjectRequest(
                    bucket=bucket,
                    key=safe_key,
                    body=stream,
                    content_type=content_type,
                    server_side_encryption="AES256",
                )
            )
        except Exception as exc:
            raise StorageError("OSS 上传失败") from exc

    def delete(self, key: str) -> None:
        safe_key = _validate_key(key)
        bucket = self.bucket_for(safe_key)
        try:
            self.client.delete_object(
                self.oss.DeleteObjectRequest(bucket=bucket, key=safe_key)
            )
        except Exception as exc:
            raise StorageError("OSS 对象删除失败") from exc

    def get_bytes(self, key: str, max_bytes: int) -> bytes:
        safe_key = _validate_key(key)
        bucket = self.bucket_for(safe_key)
        body = None
        try:
            result = self.client.get_object(
                self.oss.GetObjectRequest(bucket=bucket, key=safe_key)
            )
            body = result.body
            data = body.read(max_bytes + 1)
        except Exception as exc:
            raise StorageError("OSS 对象读取失败") from exc
        finally:
            close = getattr(body, "close", None)
            if close:
                close()
        if len(data) > max_bytes:
            raise StorageError("对象大小超过读取限制")
        return data

    def signed_url(self, key: str, expires_seconds: int) -> str:
        safe_key = _validate_key(key)
        bucket = self.bucket_for(safe_key)
        try:
            result = self.client.presign(
                self.oss.GetObjectRequest(bucket=bucket, key=safe_key),
                # 原图与预览按对象键签发各自私有 Bucket 的短时地址。
                expires=timedelta(seconds=expires_seconds),
            )
            url = str(result.url or "")
            if urlparse(url).scheme.lower() != "https":
                raise StorageError("OSS 下载地址必须使用 HTTPS")
            return url
        except StorageError:
            raise
        except Exception as exc:
            raise StorageError("OSS 下载地址生成失败") from exc


def create_storage():
    backend = str(config.MOBILE_STORAGE_BACKEND or "local").lower()
    if backend == "local":
        return LocalObjectStorage(config.MOBILE_STORAGE_DIR)
    if backend == "oss":
        return OssObjectStorage(
            config.OSS_REGION,
            config.OSS_PREVIEW_BUCKET,
            config.OSS_ORIGINAL_BUCKET,
            config.OSS_ENDPOINT,
        )
    raise StorageError(f"不支持的移动端对象存储类型: {backend}")
