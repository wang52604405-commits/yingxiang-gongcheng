# -*- coding: utf-8 -*-
"""通过本机 SSH 隧道验收隔离 staging 的移动影像 API 闭环。

该脚本故意只允许访问 loopback 地址，且所有桌面导入都写入临时目录；
活动工程只读，用来构建 888 单元快照和读取一张真实样图。
它不是微信 Android/iPhone 真机 E2E，不覆盖权限弹窗、杀进程恢复或弱网系统行为。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import secrets
import sys
import tempfile
import time
import uuid
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import requests
from PIL import Image


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))


PROJECT_NAME = "邯郸市永年区洺河龙泉缓洪工程"
CHUNK_BYTES = 4 * 1024 * 1024
MAX_PREVIEW_BYTES = 102400
SAFE_INTERNAL_PROJECT_CODE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")


class E2EFailure(RuntimeError):
    pass


def require(condition, message):
    if not condition:
        raise E2EFailure(message)


class Api:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/") + "/"
        self._isolated_staging_verified = False

    def verify_isolated_staging(self):
        """在任何写请求前验明远端实例；不接受“看起来像” staging。"""
        response = self.request("GET", "/api/instance", expected=(200,))
        try:
            payload = response.json()
        except ValueError as exc:
            raise E2EFailure("staging 实例哨兵未返回 JSON") from exc
        require(payload.get("ok") is True, "staging 实例哨兵未返回 ok")
        require(payload.get("environment") == "staging", "拒绝向非 staging 环境写入")
        require(
            payload.get("instance_id") == "album-auth-staging",
            "拒绝向非 album-auth-staging 实例写入",
        )
        self._isolated_staging_verified = True
        return payload

    def request(self, method, path, *, token="", expected=(200,), **kwargs):
        method = str(method or "GET").upper()
        if method not in {"GET", "HEAD", "OPTIONS"} and not self._isolated_staging_verified:
            raise E2EFailure("尚未验明隔离 staging 实例，拒绝发送写请求")
        headers = dict(kwargs.pop("headers", {}) or {})
        if token:
            headers["Authorization"] = f"Bearer {token}"
        target_url = urljoin(self.base_url, str(path or "").lstrip("/"))
        if token:
            base_parts = urlsplit(self.base_url)
            target_parts = urlsplit(target_url)
            require(
                (target_parts.scheme, target_parts.hostname, target_parts.port)
                == (base_parts.scheme, base_parts.hostname, base_parts.port),
                "拒绝向非 staging 同源地址发送 Bearer",
            )
        response = requests.request(
            method,
            target_url,
            headers=headers,
            timeout=kwargs.pop("timeout", 120),
            allow_redirects=False,
            **kwargs,
        )
        if response.status_code not in set(expected):
            try:
                detail = response.json()
            except ValueError:
                detail = response.text[:300]
            raise E2EFailure(
                f"{method} {path} 返回 {response.status_code}，预期 {expected}：{detail}"
            )
        return response

    def json(self, method, path, *, token="", expected=(200,), payload=None):
        response = self.request(
            method,
            path,
            token=token,
            expected=expected,
            json=payload,
        )
        data = response.json()
        require(isinstance(data, dict) and data.get("ok"), f"{path} 未返回 ok")
        return data, response.status_code


def safe_internal_project_code(value) -> str:
    """桌面工程内部码只能是一个可移植、无路径语义的目录名。"""
    code = str(value or "")
    require(bool(SAFE_INTERNAL_PROJECT_CODE.fullmatch(code)), "internal_project_code 不是安全单目录名")
    require(code not in {".", ".."} and not code.endswith((".", " ")), "internal_project_code 不安全")
    return code


def resolve_contained(root: Path, *parts: str, must_exist: bool = False) -> Path:
    """解析路径后仍必须严格位于 root 内，可阻断符号链接越界。"""
    resolved_root = Path(root).resolve(strict=must_exist)
    candidate = resolved_root.joinpath(*parts).resolve(strict=must_exist)
    try:
        relative = candidate.relative_to(resolved_root)
    except ValueError as exc:
        raise E2EFailure(f"路径越出受控目录：{candidate}") from exc
    require(relative.parts not in {(), (".",)}, "受控路径不能等于根目录")
    return candidate


def count_snapshot(snapshot):
    contracts = snapshot.get("tree") or []
    unit_projects = [item for contract in contracts for item in contract.get("unit_projects", [])]
    parts = [item for unit in unit_projects for item in unit.get("parts", [])]
    units = [item for part in parts for item in part.get("units", [])]
    processes = [name for unit in units for name in unit.get("processes", [])]
    return {
        "contracts": len(contracts),
        "unit_projects": len(unit_projects),
        "parts": len(parts),
        "units": len(units),
        "processes": len(processes),
    }, units


def make_large_jpeg(path: Path) -> dict:
    """生成真实可解码且大于微信单次上传限制的 JPEG。"""
    import numpy as np

    rng = np.random.default_rng(20260825)
    pixels = rng.integers(0, 256, size=(3000, 4200, 3), dtype=np.uint8)
    Image.fromarray(pixels, "RGB").save(
        path,
        "JPEG",
        quality=95,
        optimize=False,
        subsampling=0,
    )
    size = path.stat().st_size
    require(size > 10 * 1024 * 1024, f"分片样图只有 {size} 字节，未超过 10MiB")
    require(size <= 50 * 1024 * 1024, f"分片样图 {size} 字节，超过 50MiB")
    return {
        "path": path,
        "size": size,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "width": 4200,
        "height": 3000,
        "mime": "image/jpeg",
    }


def photo_details(path: Path) -> dict:
    raw = path.read_bytes()
    with Image.open(path) as image:
        image.load()
        width, height = image.size
        mime = "image/png" if image.format == "PNG" else "image/jpeg"
    return {
        "path": path,
        "raw": raw,
        "size": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "width": width,
        "height": height,
        "mime": mime,
    }


def upload_direct(api, token, batch_id, photo_uuid, photo, title):
    form = {
        "photo_uuid": photo_uuid,
        "client_captured_at": "2026-08-25T09:41:00+08:00",
        "orientation": "1",
        "width": str(photo["width"]),
        "height": str(photo["height"]),
        "sha256": photo["sha256"],
        "original_size_bytes": str(photo["size"]),
        "original_filename": photo["path"].name,
        "original_mime_type": photo["mime"],
        "title": title,
        "photo_date": "2026-08-25",
    }
    response = api.request(
        "POST",
        f"/api/mobile/v1/batches/{batch_id}/photos",
        token=token,
        expected=(200, 201),
        data=form,
        files={"file": (photo["path"].name, photo["raw"], photo["mime"])},
        timeout=180,
    )
    payload = response.json()
    require(payload.get("ok"), "直传原图失败")
    return payload["photo"]


def upload_chunked(api, token, batch_id, photo_uuid, photo, title):
    total_chunks = math.ceil(photo["size"] / CHUNK_BYTES)
    metadata = {
        "photo_uuid": photo_uuid,
        "client_captured_at": "2026-08-25T09:42:00+08:00",
        "orientation": 1,
        "width": photo["width"],
        "height": photo["height"],
        "sha256": photo["sha256"],
        "original_size_bytes": photo["size"],
        "original_filename": photo["path"].name,
        "original_mime_type": photo["mime"],
        "title": title,
        "photo_date": "2026-08-25",
        "chunk_size_bytes": CHUNK_BYTES,
        "total_chunks": total_chunks,
    }
    initialized, _ = api.json(
        "POST",
        f"/api/mobile/v1/batches/{batch_id}/chunked-uploads/init",
        token=token,
        expected=(200, 201),
        payload=metadata,
    )
    require(initialized["upload"]["uploaded_chunks"] == [], "新分片会话不应已有分片")

    with photo["path"].open("rb") as stream:
        first = stream.read(CHUNK_BYTES)
    first_sha = hashlib.sha256(first).hexdigest()
    first_response = api.request(
        "PUT",
        f"/api/mobile/v1/batches/{batch_id}/chunked-uploads/{photo_uuid}/chunks/0",
        token=token,
        expected=(200, 201),
        data=first,
        headers={"Content-Type": "application/octet-stream", "X-Chunk-SHA256": first_sha},
    ).json()
    require(first_response.get("ok"), "首片上传失败")

    # 重复首片必须幂等；随后通过 status 恢复进度，模拟小程序中断后续传。
    repeated = api.request(
        "PUT",
        f"/api/mobile/v1/batches/{batch_id}/chunked-uploads/{photo_uuid}/chunks/0",
        token=token,
        expected=(200,),
        data=first,
        headers={"Content-Type": "application/octet-stream", "X-Chunk-SHA256": first_sha},
    ).json()
    require(repeated.get("idempotent") is True, "重复首片没有幂等返回")
    status, _ = api.json(
        "GET",
        f"/api/mobile/v1/batches/{batch_id}/chunked-uploads/{photo_uuid}",
        token=token,
    )
    uploaded = set(status["upload"]["uploaded_chunks"])
    require(uploaded == {0}, f"恢复进度不正确：{uploaded}")

    with photo["path"].open("rb") as stream:
        for index in range(total_chunks):
            chunk = stream.read(CHUNK_BYTES)
            if index in uploaded:
                continue
            response = api.request(
                "PUT",
                f"/api/mobile/v1/batches/{batch_id}/chunked-uploads/{photo_uuid}/chunks/{index}",
                token=token,
                expected=(200, 201),
                data=chunk,
                headers={
                    "Content-Type": "application/octet-stream",
                    "X-Chunk-SHA256": hashlib.sha256(chunk).hexdigest(),
                },
                timeout=120,
            ).json()
            require(response.get("ok"), f"第 {index} 片上传失败")

    finalized, status_code = api.json(
        "POST",
        f"/api/mobile/v1/batches/{batch_id}/chunked-uploads/{photo_uuid}/finalize",
        token=token,
        expected=(200, 201),
        payload={
            "sha256": photo["sha256"],
            "original_size_bytes": photo["size"],
            "total_chunks": total_chunks,
        },
    )
    require(status_code in {200, 201}, "分片完成返回异常")
    return finalized["photo"], total_chunks


class StagingCloud:
    def __init__(self, api: Api, token: str, machine_id: str, account_id: str):
        self.api = api
        self.token = token
        self.machine_id = machine_id
        self.account_id = str(account_id or "").strip()

    def desktop_sync_identity(self):
        return f"isolated-staging-e2e:{self.account_id}"

    def desktop_sync_account_id(self):
        return self.account_id

    def desktop_sync_generation(self):
        return f"isolated-staging-e2e:{self.account_id}"

    def desktop_inbox(self, cursor="", limit=50, desktop_machine_id=""):
        payload, _ = self.api.json(
            "GET",
            "/api/desktop/v1/inbox"
            f"?cursor={cursor}&limit={limit}&desktop_machine_id={desktop_machine_id}",
            token=self.token,
        )
        return payload

    def desktop_download_bytes(self, download_url, max_bytes=50 * 1024 * 1024):
        # 直接复用正式桌面端的安全下载边界：相对同源地址
        # 才携带 Bearer；绝对 HTTPS 地址经白名单校验且不带
        # Bearer；任何重定向均拒绝。
        import cloud_client

        return cloud_client._desktop_download_bytes_with_context(
            download_url,
            self.api.base_url.rstrip("/"),
            self.token,
            max_bytes,
            timeout=180,
        )

    def desktop_ack_photo(
        self, photo_uuid, local_project_code, local_photo_id, desktop_machine_id=""
    ):
        payload, _ = self.api.json(
            "POST",
            f"/api/desktop/v1/photos/{photo_uuid}/ack",
            token=self.token,
            payload={
                "local_project_code": local_project_code,
                "local_photo_id": local_photo_id,
                "desktop_machine_id": desktop_machine_id,
            },
        )
        return payload


def run(args):
    parts = urlsplit(args.base_url)
    require(parts.scheme == "http", "隔离联调只允许本机 HTTP 隧道")
    require(parts.hostname in {"127.0.0.1", "localhost", "::1"}, "拒绝访问非本机地址")
    require(args.confirm_isolated_staging, "必须显式确认 isolated staging")
    active_root = Path(args.active_root).resolve()
    sample_path = Path(args.sample).resolve()
    require((active_root / "albums").is_dir(), "活动工程 albums 不存在")
    require(sample_path.is_file(), "真实样图不存在")

    api = Api(args.base_url)
    # 这是第一个远程请求。Api 本身也会 fail closed，在此哨兵
    # 精确匹配前拒绝所有 POST/PUT/PATCH/DELETE。
    api.verify_isolated_staging()
    stamp = uuid.uuid4().hex[:12]
    username = f"staging_e2e_{stamp}"
    password = "E2E-" + secrets.token_urlsafe(18)
    machine_id = f"STAGING-E2E-{stamp.upper()}"
    app_id = "wx-isolated-staging"
    wechat_code = f"e2e-{stamp}"

    with tempfile.TemporaryDirectory(prefix="engineering-mobile-e2e-") as temp_name:
        temp = Path(temp_name)
        # 在导入桌面应用模块前隔离其全局数据与服务器配置副作用。
        os.environ["ALBUM_DATA_DIR"] = str(temp / "app-data")
        os.environ["ALBUM_SERVER_DATA"] = str(temp / "server-import-data")
        os.environ["ALBUM_SERVER_DB"] = str(temp / "server-import-data" / "unused.db")
        os.environ["ALBUM_SERVER_SECRET"] = secrets.token_hex(32)
        # 命令行已同时验证 loopback 和显式 staging 哨兵；只在这个隔离
        # 进程内允许桌面下载器访问本机 HTTP，生产默认仍严格要求 HTTPS。
        os.environ["ALBUM_ALLOW_INSECURE_LOCALHOST"] = "1"

        from app import AlbumManager
        import mobile_sync

        active_manager = AlbumManager(active_root / "albums")
        project = {
            "id": "default",
            "project_name": PROJECT_NAME,
            "project_code": "YNLQ",
        }
        snapshot = mobile_sync.build_project_snapshot(
            active_manager,
            project,
            {"nodes": []},
            desktop_machine_id=machine_id,
        )
        snapshot.pop("_content_hash", None)
        snapshot["revision"] = int(time.time())
        counts, units = count_snapshot(snapshot)
        require(counts["units"] == args.expected_units, f"快照单元数不是 {args.expected_units}：{counts}")
        require(units, "快照没有单元")
        unit = units[0]
        unit_code = unit["unit_code"]
        internal_project_code = safe_internal_project_code(unit["internal_project_code"])

        api.json("POST", "/api/register", payload={"username": username, "password": password})
        login, _ = api.json("POST", "/api/login", payload={"username": username, "password": password})
        account_token = login["token"]
        account_id = str((login.get("account") or {}).get("id") or "").strip()
        require(account_id, "桌面登录未返回不可变 account_id")
        project["cloud_owner_id"] = account_id
        project["cloud_owner_username"] = username
        activated, _ = api.json(
            "POST",
            "/api/activate",
            token=account_token,
            payload={"machine_id": machine_id},
        )
        desktop_token = activated["desktop_sync_token"]
        api.json(
            "POST",
            "/api/desktop/v1/project-snapshot",
            token=desktop_token,
            payload=snapshot,
        )

        first_login, _ = api.json(
            "POST",
            "/api/mobile/v1/auth/wechat-login",
            payload={"code": wechat_code, "app_id": app_id},
        )
        require(first_login.get("binding_required") is True, "首次微信登录应要求绑定")
        bound, _ = api.json(
            "POST",
            "/api/mobile/v1/auth/wechat-bind",
            payload={
                "binding_ticket": first_login["binding_ticket"],
                "username": username,
                "password": password,
            },
        )
        second_login, _ = api.json(
            "POST",
            "/api/mobile/v1/auth/wechat-login",
            payload={"code": wechat_code, "app_id": app_id},
        )
        require(second_login.get("binding_required") is not True, "已绑定账号仍要求重新绑定")
        # 绑定后必须真正换用第二次登录签发的 token，同时
        # 验收“登录即自动拉取账号、工程和 888 单元层级”。
        mobile_token = second_login["token"]
        second_account = second_login.get("account") or {}
        bootstrap = second_login.get("bootstrap") or {}
        bootstrap_account = bootstrap.get("account") or {}
        bound_account = bound.get("account") or {}
        require(
            second_account.get("id") == bound_account.get("id")
            and second_account.get("username") == username,
            "第二次登录拉取的账号与绑定账号不一致",
        )
        require(bootstrap_account.get("id") == second_account.get("id"), "bootstrap 账号不一致")
        projects = bootstrap.get("projects") or []
        require(len(projects) == 1, "登录未自动拉取唯一工程")
        require(
            projects[0].get("project_id") == "default"
            and projects[0].get("project_name") == PROJECT_NAME,
            "登录拉取的工程不正确",
        )
        require(
            int((bootstrap.get("hierarchy_summary") or {}).get("engineering_unit") or 0)
            == args.expected_units,
            "bootstrap 没有拉取完整单元层级摘要",
        )
        pulled_tree, _ = api.json(
            "GET", "/api/mobile/v1/projects/default/tree", token=mobile_token
        )
        require(pulled_tree.get("project", {}).get("project_name") == PROJECT_NAME, "层级所属工程不正确")
        require(len(pulled_tree.get("units") or []) == args.expected_units, "登录后未拉取完整 888 单元层级")

        sample = photo_details(sample_path)
        auto_uuid = str(uuid.uuid4())
        auto_batch_id = api.json(
            "POST",
            "/api/mobile/v1/batches",
            token=mobile_token,
            expected=(200, 201),
            payload={
                "client_batch_id": str(uuid.uuid4()),
                "project_id": "default",
                "scope": "engineering",
                "category": "construction",
                "mode": "auto",
            },
        )[0]["batch"]["batch_id"]
        auto_photo = upload_direct(
            api, mobile_token, auto_batch_id, auto_uuid, sample, "真实水印样图"
        )
        require(auto_photo["preview_size_bytes"] <= MAX_PREVIEW_BYTES, "服务器预览超过 100KB")
        auto_preview_url = auto_photo["download_url"]
        preview = api.request("GET", auto_preview_url, expected=(200,)).content
        require(preview.startswith(b"\xff\xd8") and len(preview) <= MAX_PREVIEW_BYTES, "预览不是 <=100KB JPEG")

        started = time.monotonic()
        analysis, analysis_code = api.json(
            "POST",
            f"/api/mobile/v1/batches/{auto_batch_id}/analyze",
            token=mobile_token,
            expected=(200, 202),
            payload={},
        )
        require(analysis_code == 202, "首次 OCR 没有快速返回 202")
        require(time.monotonic() - started < 20, "OCR 请求没有快速受理")
        deadline = time.monotonic() + args.analysis_timeout
        while True:
            batch_payload, _ = api.json(
                "GET",
                f"/api/mobile/v1/batches/{auto_batch_id}",
                token=mobile_token,
            )
            if batch_payload["batch"]["status"] == "needs_review":
                break
            require(time.monotonic() < deadline, "OCR 批次未在期限内进入 needs_review")
            time.sleep(2)
        api.json(
            "PATCH",
            f"/api/mobile/v1/batches/{auto_batch_id}/assignments",
            token=mobile_token,
            payload={
                "assignments": [
                    {
                        "photo_uuid": auto_uuid,
                        "unit_code": unit_code,
                        "process_name": "",
                        "title": "真实水印样图",
                        "photo_date": "2026-08-25",
                    }
                ]
            },
        )
        api.json("POST", f"/api/mobile/v1/batches/{auto_batch_id}/commit", token=mobile_token, payload={})

        large = make_large_jpeg(temp / "chunked-original.jpg")
        large["raw"] = None
        chunk_uuid = str(uuid.uuid4())
        chunk_batch_id = api.json(
            "POST",
            "/api/mobile/v1/batches",
            token=mobile_token,
            expected=(200, 201),
            payload={
                "client_batch_id": str(uuid.uuid4()),
                "project_id": "default",
                "scope": "engineering",
                "category": "construction",
                "mode": "direct",
                "assignment": {"unit_code": unit_code, "process_name": ""},
            },
        )[0]["batch"]["batch_id"]
        chunk_photo, chunk_count = upload_chunked(
            api, mobile_token, chunk_batch_id, chunk_uuid, large, "分片续传样图"
        )
        require(chunk_photo["preview_size_bytes"] <= MAX_PREVIEW_BYTES, "分片图预览超过 100KB")
        api.json("POST", f"/api/mobile/v1/batches/{chunk_batch_id}/commit", token=mobile_token, payload={})

        inbox, _ = api.json(
            "GET",
            f"/api/desktop/v1/inbox?desktop_machine_id={machine_id}&limit=10",
            token=desktop_token,
        )
        by_uuid = {item["photo_uuid"]: item for item in inbox["items"]}
        require({auto_uuid, chunk_uuid}.issubset(by_uuid), "桌面队列没有收到两张原图")
        originals = {
            auto_uuid: {"sha256": sample["sha256"], "size": sample["size"], "raw": sample["raw"]},
            chunk_uuid: {"sha256": large["sha256"], "size": large["size"], "raw": large["path"].read_bytes()},
        }
        original_urls = {key: by_uuid[key]["original_download_url"] for key in originals}

        active_albums_root = (active_root / "albums").resolve(strict=True)
        source_metadata = resolve_contained(
            active_albums_root,
            internal_project_code,
            "metadata.json",
            must_exist=True,
        )
        require(source_metadata.is_file(), f"找不到单元 metadata：{internal_project_code}")
        desktop_albums_root = temp / "desktop" / "albums"
        desktop_albums_root.mkdir(parents=True)
        local_album = resolve_contained(desktop_albums_root, internal_project_code)
        local_album.mkdir(parents=True)
        metadata = json.loads(source_metadata.read_text(encoding="utf-8"))
        metadata["photos"] = []
        (local_album / "metadata.json").write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        desktop_manager = AlbumManager(temp / "desktop" / "albums")
        cloud = StagingCloud(api, desktop_token, machine_id, account_id)
        synchronizer = mobile_sync.DesktopMobileSync(
            desktop_manager,
            cloud,
            engineering_project_reader=lambda: project,
            other_images_reader=lambda: {"nodes": []},
            state_path=temp / "desktop" / "mobile-sync-state.json",
            cache_dir=temp / "desktop" / "mobile-cache",
            machine_id_reader=lambda: machine_id,
        )
        sync_result = synchronizer._sync_inbox()
        require(sync_result.get("ok") and sync_result.get("imported") == 2, f"桌面导入失败：{sync_result}")

        local_data = desktop_manager.get_project(internal_project_code)
        local_by_uuid = {item.get("photo_uuid"): item for item in local_data.get("photos", [])}
        for photo_uuid, expected in originals.items():
            require(photo_uuid in local_by_uuid, f"本地 metadata 缺少 {photo_uuid}")
            stored_path = desktop_manager._photos_dir(internal_project_code) / local_by_uuid[photo_uuid]["filename"]
            stored = stored_path.read_bytes()
            require(len(stored) == expected["size"], "桌面原图大小不精确")
            require(hashlib.sha256(stored).hexdigest() == expected["sha256"], "桌面原图 SHA 不精确")
            require(stored == expected["raw"], "桌面原图字节不精确")
            detail, _ = api.json(
                "GET", f"/api/mobile/v1/photos/{photo_uuid}", token=mobile_token
            )
            require(detail["photo"]["status"] == "desktop_imported", "手机状态未变为电脑已归档")
            require(detail["photo"]["original_cleanup_status"] == "deleted", "服务器原图中转未清理")
            deleted = cloud.desktop_download_bytes(original_urls[photo_uuid])
            require(
                not deleted.get("ok") and deleted.get("http_status") == 404,
                "桌面 ACK 后原图中转地址仍可下载",
            )

        # 结束前重新读取 photo detail 获取新签名，不复用上传阶段
        # 可能已过期的预览 URL。
        fresh_preview_urls = []
        for photo_uuid in originals:
            refreshed, _ = api.json(
                "GET", f"/api/mobile/v1/photos/{photo_uuid}", token=mobile_token
            )
            refreshed_photo = refreshed["photo"]
            require(refreshed_photo["status"] == "desktop_imported", "刷新详情后归档状态不正确")
            preview_url = str(refreshed_photo.get("download_url") or "")
            require(preview_url, "刷新详情后没有永久预览地址")
            fresh_preview_urls.append(preview_url)

        # 原图清理后，两张永久预览仍必须可查看。
        for preview_url in fresh_preview_urls:
            remaining = api.request("GET", preview_url, expected=(200,)).content
            require(remaining.startswith(b"\xff\xd8") and len(remaining) <= MAX_PREVIEW_BYTES, "ACK 后预览丢失")

        return {
            "ok": True,
            "snapshot": counts,
            "login_auto_bootstrap": True,
            "direct_original_bytes": sample["size"],
            "chunk_original_bytes": large["size"],
            "chunk_count": chunk_count,
            "desktop_imported": 2,
            "original_sha_exact": True,
            "relay_original_deleted": True,
            "permanent_previews_under_100kb": 2,
            "test_scope": "staging_server_api_and_desktop_sync_not_wechat_device",
        }


def main():
    parser = argparse.ArgumentParser(
        description="隔离 staging 服务器 API+桌面同步验收（非微信真机 E2E）"
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:18080")
    parser.add_argument("--active-root", required=True)
    parser.add_argument("--sample", required=True)
    parser.add_argument("--expected-units", type=int, default=888)
    parser.add_argument("--analysis-timeout", type=int, default=300)
    parser.add_argument("--confirm-isolated-staging", action="store_true")
    args = parser.parse_args()
    result = run(args)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
