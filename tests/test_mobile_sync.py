# -*- coding: utf-8 -*-
"""桌面端移动同步的回归测试。"""

from __future__ import annotations

import hashlib
import io
import json
import tempfile
import threading
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from PIL import Image

import mobile_sync
import cloud_client


class FakeManager:
    """仅实现 mobile_sync 需要的 AlbumManager 契约。"""

    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.projects = {}
        self.locks = {}
        self.repairs = []

    def add_project(self, code, name, source_fields=None, photos=None, processes=None, division_type="unit", persist=True):
        data = {
            "project_code": code,
            "display_project_code": str((source_fields or {}).get("单元工程编码") or code),
            "project_name": name,
            "source_fields": dict(source_fields or {}),
            "division_type": division_type,
            "processes": list(processes or []),
            "photos": list(photos or []),
        }
        self.projects[code] = json.loads(json.dumps(data, ensure_ascii=False))
        if persist:
            self._write_metadata(code, data)
        return data

    def _project_write_lock(self, project_code):
        return self.locks.setdefault(project_code, threading.RLock())

    def _project_dir(self, project_code):
        return self.root / project_code

    def _metadata_path(self, project_code):
        return self._project_dir(project_code) / "metadata.json"

    def _photos_dir(self, project_code):
        return self._project_dir(project_code) / "photos"

    def _read_metadata(self, project_code):
        return json.loads(json.dumps(self.projects[project_code], ensure_ascii=False))

    def _write_metadata(self, project_code, data):
        self.projects[project_code] = json.loads(json.dumps(data, ensure_ascii=False))
        self._photos_dir(project_code).mkdir(parents=True, exist_ok=True)
        self._metadata_path(project_code).write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def get_project(self, project_code):
        return self._read_metadata(project_code)

    def list_projects(self, include_other=False):
        result = []
        for code, data in self.projects.items():
            is_other = bool((data.get("source_fields") or {}).get("_other_image"))
            if is_other and not include_other:
                continue
            result.append({
                "project_code": code,
                "project_name": data.get("project_name", code),
                "is_other_image": is_other,
            })
        return result

    def project_hierarchy(self, data):
        fields = data.get("source_fields") or {}
        return {
            "contract_name": fields.get("合同工程名称", ""),
            "unit_project_name": fields.get("单位工程名称", ""),
            "unit_project_code": fields.get("单位工程编码", ""),
            "part_name": fields.get("分部工程名称", ""),
            "part_code": fields.get("分部工程编码", ""),
            "unit_name": fields.get("单元工程名称", data.get("project_name", "")),
            "unit_code": fields.get("单元工程编码", data.get("display_project_code", data["project_code"])),
        }

    def add_photos(
        self,
        project_code,
        files,
        category="construction",
        title="",
        photo_date="",
        photographer="",
        uploaded_by="",
        orientation="landscape",
        process_name="",
        per_file_meta=None,
        **_kwargs,
    ):
        with self._project_write_lock(project_code):
            data = self._read_metadata(project_code)
            added = []
            for storage in files:
                raw = storage.stream.read()
                meta = (per_file_meta or {}).get(storage.filename, {})
                photo_id = f"SY{len(data['photos']) + 1:03d}"
                extension = Path(storage.filename).suffix.lower() or ".jpg"
                filename = f"construction-{photo_id}{extension}"
                target = self._photos_dir(project_code) / filename
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(raw)
                item = {
                    "id": photo_id,
                    "photo_uuid": meta.get("photo_uuid"),
                    "filename": filename,
                    "category": category,
                    "title": meta.get("title") or title,
                    "photo_date": meta.get("photo_date") or photo_date,
                    "photographer": photographer,
                    "uploaded_by": uploaded_by,
                    "photographer_account_id": str(meta.get("photographer_account_id") or ""),
                    "uploaded_by_account_id": str(meta.get("uploaded_by_account_id") or ""),
                    "project_owner_account_id": str(meta.get("project_owner_account_id") or ""),
                    "capture_source": str(meta.get("capture_source") or ""),
                    "orientation": orientation,
                    "process_name": process_name,
                    "mobile_compressed_200k": bool(meta.get("mobile_compressed_200k")),
                    "mobile_original_received": bool(meta.get("mobile_original_received")),
                    "mobile_original_name": meta.get("source_original_name", storage.filename),
                    "client_captured_at": meta.get("client_captured_at", ""),
                    "sha256": meta.get("sha256", ""),
                    "stored_bytes": len(raw),
                }
                data["photos"].append(item)
                added.append(dict(item))
            self._write_metadata(project_code, data)
            return added

    def repair_mobile_original(self, project_code, photo_uuid, raw, details, original_name=""):
        with self._project_write_lock(project_code):
            data = self._read_metadata(project_code)
            photo = next(
                item for item in data["photos"]
                if str(item.get("photo_uuid") or "") == str(photo_uuid)
            )
            target = self._photos_dir(project_code) / Path(photo["filename"]).name
            temporary = target.with_suffix(target.suffix + ".mobile-repair.tmp")
            temporary.write_bytes(raw)
            temporary.replace(target)
            photo.update({
                "sha256": details["sha256"],
                "stored_bytes": len(raw),
                "mobile_original_size_bytes": len(raw),
                "mobile_original_received": True,
                "mobile_original_name": original_name or photo.get("mobile_original_name", ""),
            })
            self._write_metadata(project_code, data)
            self.repairs.append((project_code, photo_uuid, details["sha256"]))
            return dict(photo)


class FakeCloud:
    def __init__(
        self,
        raw=b"",
        items=None,
        fail_snapshots=0,
        ack_results=None,
        inbox_batches=None,
        backfill_results=None,
        delete_results=None,
        identity="fake-account",
    ):
        self.raw = raw
        self.items = list(items or [])
        self.inbox_batches = [list(batch) for batch in inbox_batches] if inbox_batches is not None else None
        self.fail_snapshots = fail_snapshots
        self.snapshot_calls = 0
        self.acks = []
        self.backfills = []
        self.deletes = []
        self.inbox_machine_ids = []
        self.ack_results = list(ack_results or [])
        self.backfill_results = list(backfill_results or [])
        self.delete_results = list(delete_results or [])
        self.identity = identity

    def desktop_sync_identity(self):
        return self.identity

    def desktop_sync_identity_for_account(self, account_id):
        return str(account_id or "")

    def desktop_sync_account_id(self):
        return self.identity

    def desktop_sync_generation(self):
        return f"generation:{self.identity}"

    def desktop_project_snapshot(self, snapshot):
        self.snapshot_calls += 1
        if self.snapshot_calls <= self.fail_snapshots:
            return {"ok": False, "network_error": True, "retryable": True, "error": "offline"}
        self.snapshot = snapshot
        return {"ok": True}

    def desktop_inbox(self, cursor="", limit=50, desktop_machine_id=""):
        self.inbox_machine_ids.append(desktop_machine_id)
        items = (
            self.inbox_batches.pop(0)
            if self.inbox_batches
            else ([] if self.inbox_batches is not None else list(self.items))
        )
        return {
            "ok": True,
            "items": items,
            "next_cursor": "cursor-next" if items else cursor,
            "original_max_bytes": mobile_sync.MAX_ORIGINAL_PHOTO_BYTES,
            "max_original_bytes": mobile_sync.MAX_ORIGINAL_PHOTO_BYTES,
        }

    def desktop_download_bytes(self, _url, max_bytes=50 * 1024 * 1024):
        if len(self.raw) > max_bytes:
            return {"ok": False, "error": "too large"}
        return {"ok": True, "data": self.raw}

    def desktop_ack_photo(self, photo_uuid, local_project_code, local_photo_id, desktop_machine_id=""):
        self.acks.append((photo_uuid, local_project_code, local_photo_id, desktop_machine_id, self.identity))
        if self.ack_results:
            return self.ack_results.pop(0)
        return {"ok": True, "cleanup_status": "deleted", "cleanup_pending": False}

    def desktop_delete_photo(self, photo_uuid, local_project_code, local_photo_id, desktop_machine_id=""):
        self.deletes.append(
            (photo_uuid, local_project_code, local_photo_id, desktop_machine_id, self.identity)
        )
        if self.delete_results:
            return self.delete_results.pop(0)
        return {"ok": True, "idempotent": False}

    def desktop_backfill_photo(self, path, metadata):
        raw = Path(path).read_bytes()
        self.backfills.append((raw, dict(metadata), Path(path)))
        if self.backfill_results:
            return self.backfill_results.pop(0)
        return {"ok": True}


def jpeg_bytes(size=(800, 600), quality=82):
    output = io.BytesIO()
    Image.new("RGB", size, (52, 116, 148)).save(output, "JPEG", quality=quality)
    return output.getvalue()


def noisy_jpeg_bytes(size=(1800, 1200), quality=98):
    output = io.BytesIO()
    Image.effect_noise(size, 72).convert("RGB").save(output, "JPEG", quality=quality)
    return output.getvalue()


class DesktopMobileSyncTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="album-mobile-sync-")
        self.root = Path(self.temp.name)
        self.manager = FakeManager(self.root / "albums")
        self.project = {
            "id": "default",
            "project_name": mobile_sync.TARGET_PROJECT_DISPLAY_NAME,
            "project_code": "YNLQ",
            "cloud_owner_id": "fake-account",
            "cloud_owner_username": "test-user",
        }

    def tearDown(self):
        self.temp.cleanup()

    def service(self, cloud, **kwargs):
        return mobile_sync.DesktopMobileSync(
            self.manager,
            cloud,
            lambda: dict(self.project),
            lambda: {"nodes": []},
            self.root / "state.json",
            self.root / "cache",
            machine_id_reader=lambda: "MACHINE-A",
            **kwargs,
        )

    def add_unit(self, code="YNLQ-001-01-001", photos=None, processes=None):
        return self.manager.add_project(
            code,
            "左岸连接堤",
            source_fields={
                "合同工程名称": "洺河龙泉缓洪工程",
                "单位工程名称": "龙泉河单位工程",
                "单位工程编码": "YNLQ-001",
                "分部工程名称": "左岸连接工程",
                "分部工程编码": "YNLQ-001-01",
                "单元工程名称": "左岸连接堤",
                "单元工程编码": code,
            },
            photos=photos,
            processes=processes,
            division_type="process" if processes else "unit",
        )

    def test_lazy_uuid_migration_is_stable_backed_up_and_does_not_touch_photo(self):
        raw = jpeg_bytes()
        photo = {"id": "SY001", "filename": "construction-SY001.jpg", "category": "construction"}
        self.add_unit(photos=[photo])
        source = self.manager._photos_dir("YNLQ-001-01-001") / photo["filename"]
        source.write_bytes(raw)
        before_hash = hashlib.sha256(source.read_bytes()).hexdigest()

        first = mobile_sync.ensure_all_photo_uuids(self.manager)
        first_uuid = self.manager.get_project("YNLQ-001-01-001")["photos"][0]["photo_uuid"]
        second = mobile_sync.ensure_all_photo_uuids(self.manager)

        self.assertEqual(first["changed"], 1)
        self.assertEqual(second["changed"], 0)
        self.assertEqual(first_uuid, str(uuid.UUID(first_uuid)))
        self.assertTrue(Path(first["backups"][0]).exists())
        self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), before_hash)

    def test_full_888_ynlq_snapshot_preserves_processes_and_other_tree(self):
        # 真实首版规模：888 个 YNLQ 单元。
        self.manager.projects.clear()
        for index in range(1, 889):
            code = f"YNLQ-001-01-{index:03d}"
            self.manager.add_project(
                code,
                f"单元{index:03d}",
                source_fields={
                    "合同工程名称": "洺河龙泉缓洪工程",
                    "单位工程名称": "龙泉河单位工程",
                    "单位工程编码": "YNLQ-001",
                    "分部工程名称": "左岸连接工程",
                    "分部工程编码": "YNLQ-001-01",
                    "单元工程名称": f"单元{index:03d}",
                    "单元工程编码": code,
                },
                processes=["普通混凝土备仓", "普通混凝土浇筑"] if index == 1 else [],
                division_type="process" if index == 1 else "unit",
                persist=False,
            )
        other = {"nodes": [{"code": "QTYX-001", "name": "会议影像", "children": []}]}
        snapshot = mobile_sync.build_project_snapshot(
            self.manager, self.project, other, desktop_machine_id="MACHINE-A"
        )
        units = [
            unit
            for contract in snapshot["tree"]
            for unit_project in contract["unit_projects"]
            for part in unit_project["parts"]
            for unit in part["units"]
        ]
        self.assertEqual(snapshot["project"]["project_name"], mobile_sync.TARGET_PROJECT_DISPLAY_NAME)
        self.assertEqual(snapshot["project"]["id"], "default")
        self.assertEqual(snapshot["project"]["local_project_id"], "default")
        self.assertEqual(snapshot["project"]["owner_account_id"], "fake-account")
        self.assertEqual(snapshot["project"]["project_ref"], "fake-account:default")
        self.assertEqual(snapshot["desktop_machine_id"], "MACHINE-A")
        self.assertEqual(len(units), 888)
        self.assertTrue(all(unit["unit_code"].startswith("YNLQ-") for unit in units))
        self.assertEqual(units[0]["processes"], ["普通混凝土备仓", "普通混凝土浇筑"])
        self.assertEqual(snapshot["other_tree"][0]["node_code"], "QTYX-001")
        self.assertNotIn("photo_inventory_complete", snapshot)
        self.assertNotIn("photo_uuids", snapshot)

    def test_snapshot_never_infers_photo_deletion_or_assigns_inventory_uuids(self):
        self.add_unit(photos=[{
            "id": "SY001",
            "filename": "construction-SY001.jpg",
            "category": "construction",
        }])
        cloud = FakeCloud()
        result = self.service(cloud)._sync_snapshot()
        self.assertTrue(result["ok"])
        self.assertNotIn("photo_uuids", cloud.snapshot)
        self.assertNotIn("photo_inventory_complete", cloud.snapshot)
        self.assertFalse(
            self.manager.get_project("YNLQ-001-01-001")["photos"][0].get("photo_uuid")
        )

    def test_explicit_delete_queue_survives_offline_then_clears_after_success(self):
        photo_uuid = str(uuid.uuid4())
        cloud = FakeCloud(delete_results=[
            {"ok": False, "network_error": True, "retryable": True, "error": "offline"},
            {"ok": True, "idempotent": False},
        ])
        service = self.service(cloud)
        with patch.object(mobile_sync.threading, "Thread") as wake:
            queued = service.enqueue_photo_delete(
                photo_uuid,
                "YNLQ-001-01-001",
                "SY001",
                project_id="default",
                cloud_account_id="fake-account",
            )
        self.assertTrue(queued["queued"])
        wake.assert_called_once()
        wake.return_value.start.assert_called_once()
        self.assertEqual(service.status()["delete_pending_count"], 1)

        first = service.run_once()
        self.assertTrue(first["ok"], "删除请求失败不得阻断其它同步阶段")
        self.assertEqual(first["deletes"]["failed"], 1)
        self.assertEqual(service.status()["delete_pending_count"], 1)
        second = service.run_once()
        self.assertTrue(second["ok"])
        self.assertEqual(second["deletes"]["deleted"], 1)
        self.assertEqual(service.status()["delete_pending_count"], 0)
        self.assertEqual(len(cloud.deletes), 2)
        self.assertTrue(all(item[3] == "MACHINE-A" for item in cloud.deletes))

    def test_delete_without_uuid_never_queues_or_calls_cloud(self):
        cloud = FakeCloud()
        service = self.service(cloud)
        with patch.object(mobile_sync.threading, "Thread") as wake:
            result = service.enqueue_photo_delete(
                "", "YNLQ-001-01-001", "SY001", cloud_account_id="fake-account"
            )
        self.assertFalse(result["queued"])
        self.assertEqual(result["code"], "photo_uuid_missing")
        self.assertEqual(service.status()["delete_pending_count"], 0)
        self.assertEqual(cloud.deletes, [])
        wake.assert_not_called()

    def test_logged_out_delete_is_saved_in_owner_partition_not_logged_out_partition(self):
        photo_uuid = str(uuid.uuid4())
        cloud = FakeCloud(identity="")
        service = self.service(cloud)
        queued = service.enqueue_photo_delete(
            photo_uuid,
            "YNLQ-001-01-001",
            "SY001",
            cloud_account_id="fake-account",
        )
        self.assertTrue(queued["queued"])
        document = json.loads((self.root / "state.json").read_text(encoding="utf-8"))
        self.assertIn("fake-account|MACHINE-A", document["scopes"])
        self.assertNotIn("__logged_out__|MACHINE-A", document["scopes"])
        self.assertIn(photo_uuid, document["scopes"]["fake-account|MACHINE-A"]["delete_pending"])

        cloud.identity = "fake-account"
        synced = service.run_once()
        self.assertTrue(synced["ok"])
        self.assertEqual(synced["deletes"]["deleted"], 1)
        self.assertEqual(service.status()["delete_pending_count"], 0)

    def test_delete_supersedes_ack_pending_for_same_local_photo(self):
        photo_uuid = str(uuid.uuid4())
        service = self.service(FakeCloud())
        state = service._read_state()
        state["ack_pending"][photo_uuid] = {
            "local_project_code": "YNLQ-001-01-001",
            "local_photo_id": "SY001",
        }
        state["cleanup_pending"][photo_uuid] = dict(state["ack_pending"][photo_uuid])
        service._write_state(state)
        with patch.object(mobile_sync.threading, "Thread"):
            service.enqueue_photo_delete(
                photo_uuid,
                "YNLQ-001-01-001",
                "SY001",
                cloud_account_id="fake-account",
            )
        persisted = service._read_state()
        self.assertNotIn(photo_uuid, persisted["ack_pending"])
        self.assertNotIn(photo_uuid, persisted["cleanup_pending"])
        self.assertIn(photo_uuid, persisted["delete_pending"])
        self.assertTrue(persisted["delete_pending"][photo_uuid]["ack_after_delete"])

    def test_stale_general_state_write_cannot_erase_new_delete_event(self):
        photo_uuid = str(uuid.uuid4())
        service = self.service(FakeCloud())
        stale = service._read_state()
        with patch.object(mobile_sync.threading, "Thread"):
            service.enqueue_photo_delete(
                photo_uuid,
                "YNLQ-001-01-001",
                "SY001",
                cloud_account_id="fake-account",
            )

        # 模拟快照网络请求结束后，把请求前读取的旧 state 写回。
        stale["snapshot_revision"] = 2026082801
        service._write_state(stale)
        persisted = service._read_state()
        self.assertEqual(persisted["snapshot_revision"], 2026082801)
        self.assertIn(photo_uuid, persisted["delete_pending"])

    def test_ack_race_is_handed_to_delete_queue_then_cleans_server_original(self):
        photo_uuid = str(uuid.uuid4())
        cloud = FakeCloud(
            delete_results=[{
                "ok": True,
                "idempotent": False,
                "deleted_at": "2026-08-28 12:00:00",
            }],
            ack_results=[{
                "ok": True,
                "cleanup_status": "deleted",
                "cleanup_pending": False,
            }],
        )
        service = self.service(cloud)
        with patch.object(mobile_sync.threading, "Thread"):
            service.enqueue_photo_delete(
                photo_uuid,
                "YNLQ-001-01-001",
                "SY001",
                cloud_account_id="fake-account",
            )
        # 模拟本地落盘后、普通 ACK 入队前发生删除；此处文件已经不存在。
        handed_off = service._ack_import(photo_uuid, {
            "project_code": "YNLQ-001-01-001",
            "photo_id": "SY001",
        })
        self.assertTrue(handed_off["ok"])
        self.assertTrue(handed_off["delete_pending"])
        self.assertEqual(cloud.acks, [])
        self.assertTrue(
            service._read_state()["delete_pending"][photo_uuid]["ack_after_delete"]
        )

        result = service.run_once()
        self.assertTrue(result["ok"])
        self.assertEqual(result["deletes"]["deleted"], 1)
        self.assertEqual(service.status()["delete_pending_count"], 0)
        self.assertEqual(len(cloud.deletes), 1)
        self.assertEqual(len(cloud.acks), 1)
        self.assertEqual(cloud.acks[0][0:3], (photo_uuid, "YNLQ-001-01-001", "SY001"))

    def test_mobile_original_over_200k_is_exact_idempotent_and_cleanup_retries(self):
        self.add_unit()
        raw = noisy_jpeg_bytes()
        self.assertGreater(len(raw), 200 * 1024)
        self.assertLessEqual(len(raw), mobile_sync.MAX_ORIGINAL_PHOTO_BYTES)
        photo_uuid = str(uuid.uuid4())
        item = {
            "photo_uuid": photo_uuid,
            "project_id": "default",
            "scope": "engineering",
            "category": "construction",
            "unit_code": "YNLQ-001-01-001",
            "process_name": "",
            "title": "基槽验收",
            "photo_date": "2026-08-25",
            "photographer": "现场张工",
            "uploaded_by": "zhangsan",
            "orientation": "landscape",
            "original_download_url": "/download/original",
            "original_sha256": hashlib.sha256(raw).hexdigest(),
            "original_size_bytes": len(raw),
            "original_filename": "IMG_20260825_090000.jpg",
            "original_mime_type": "image/jpeg",
            "target_machine_id": "MACHINE-A",
            "cursor": "1",
        }
        cloud = FakeCloud(
            raw=raw,
            # 服务端第一次已经提交 desktop_imported，所以后续 inbox 不再
            # 返回这张照片；只能依靠本地先落盘的 ack_pending 重试。
            inbox_batches=[[item], [], []],
            ack_results=[
                {"ok": False, "network_error": True, "retryable": True, "error": "ACK 响应丢失"},
                {"ok": True, "idempotent": True, "cleanup_status": "cleanup_pending", "cleanup_pending": True},
                {"ok": True, "idempotent": True, "cleanup_status": "deleted", "cleanup_pending": False},
            ],
        )
        service = self.service(cloud)

        first = service._sync_inbox()
        persisted_after_first = service._read_state()
        second = service._sync_inbox()
        third = service._sync_inbox()
        data = self.manager.get_project("YNLQ-001-01-001")
        stored = self.manager._photos_dir("YNLQ-001-01-001") / data["photos"][0]["filename"]

        self.assertFalse(first["ok"])
        self.assertEqual(first["imported"], 0, "响应丢失时本地已导入但尚未计作完整同步")
        self.assertEqual(second["imported"], 0)
        self.assertEqual(third["imported"], 0)
        self.assertEqual(len(data["photos"]), 1)
        self.assertEqual(stored.read_bytes(), raw, "手机原图必须原字节落盘")
        self.assertTrue(data["photos"][0]["mobile_original_received"])
        self.assertEqual(data["photos"][0]["photo_uuid"], photo_uuid)
        self.assertEqual(data["photos"][0]["photographer"], "现场张工")
        self.assertEqual(data["photos"][0]["uploaded_by"], "zhangsan")
        self.assertEqual(len(cloud.acks), 3, "响应丢失与清理 pending 都必须幂等重发 ACK")
        self.assertTrue(all(ack[3] == "MACHINE-A" for ack in cloud.acks))
        self.assertIn(photo_uuid, persisted_after_first.get("ack_pending", {}))
        self.assertEqual(
            persisted_after_first["ack_pending"][photo_uuid]["local_project_code"],
            "YNLQ-001-01-001",
        )
        # 第三轮已清空磁盘状态；通过第二轮返回值证明 cleanup pending 仍保留。
        self.assertEqual(second["ack_pending"], 1)
        self.assertEqual(second["cleanup_pending"], 1)
        self.assertEqual(third["ack_pending"], 0)
        self.assertEqual(third["cleanup_pending"], 0)
        self.assertEqual(cloud.inbox_machine_ids, ["MACHINE-A", "MACHINE-A", "MACHINE-A"])

    def test_team_member_photo_uses_canonical_project_and_keeps_actor_audit(self):
        self.add_unit()
        self.project.update({
            "cloud_owner_id": "42",
            "cloud_project_ref": "42:default",
        })
        raw = noisy_jpeg_bytes(size=(1200, 800))
        photo_uuid = str(uuid.uuid4())
        item = {
            "photo_uuid": photo_uuid,
            "project_id": "default",
            "project_ref": "42:default",
            "local_project_id": "default",
            "owner_account_id": 42,
            "account_id": 77,
            "photographer_account_id": 78,
            "uploaded_by_account_id": 77,
            "capture_source": "camera",
            "scope": "engineering",
            "category": "construction",
            "unit_code": "YNLQ-001-01-001",
            "photographer": "现场李工",
            "uploaded_by": "成员王工",
            "original_download_url": "/download/original",
            "original_sha256": hashlib.sha256(raw).hexdigest(),
            "original_size_bytes": len(raw),
            "original_filename": "team-camera.jpg",
            "original_mime_type": "image/jpeg",
            "target_machine_id": "MACHINE-A",
        }
        cloud = FakeCloud(raw=raw, items=[item], identity="42")

        result = self.service(cloud)._sync_inbox()

        self.assertEqual(result["imported"], 1)
        stored = self.manager.get_project("YNLQ-001-01-001")["photos"][0]
        self.assertEqual(stored["photo_uuid"], photo_uuid)
        self.assertEqual(stored["photographer"], "现场李工")
        self.assertEqual(stored["uploaded_by"], "成员王工")
        self.assertEqual(stored["photographer_account_id"], "78")
        self.assertEqual(stored["uploaded_by_account_id"], "77")
        self.assertEqual(stored["project_owner_account_id"], "42")
        self.assertEqual(stored["capture_source"], "camera")

    def test_team_member_photo_never_infers_photographer_from_uploader_and_rejects_other_project(self):
        self.add_unit()
        self.project.update({
            "cloud_owner_id": "42",
            "cloud_project_ref": "42:default",
        })
        raw = jpeg_bytes()
        base = {
            "photo_uuid": str(uuid.uuid4()),
            "project_id": "default",
            "project_ref": "42:default",
            "local_project_id": "default",
            "owner_account_id": 42,
            "account_id": 77,
            "photographer_account_id": 0,
            "uploaded_by_account_id": 77,
            "capture_source": "album",
            "scope": "engineering",
            "category": "construction",
            "unit_code": "YNLQ-001-01-001",
            "original_download_url": "/download/original",
            "original_sha256": hashlib.sha256(raw).hexdigest(),
            "original_size_bytes": len(raw),
            "original_filename": "team-album.jpg",
            "original_mime_type": "image/jpeg",
            "target_machine_id": "MACHINE-A",
        }
        cloud = FakeCloud(raw=raw, items=[base], identity="42")
        imported = self.service(cloud)._sync_inbox()
        self.assertEqual(imported["imported"], 1)
        stored = self.manager.get_project("YNLQ-001-01-001")["photos"][0]
        self.assertEqual(stored["photographer_account_id"], "")
        self.assertEqual(stored["uploaded_by_account_id"], "77")

        rejected_cloud = FakeCloud(raw=raw, items=[{
            **base,
            "photo_uuid": str(uuid.uuid4()),
            "project_ref": "43:default",
            "owner_account_id": 43,
        }], identity="42")
        rejected = self.service(rejected_cloud)._sync_inbox()
        self.assertFalse(rejected["ok"])
        self.assertIn("另一工程账号", rejected["error"])
        self.assertEqual(len(self.manager.get_project("YNLQ-001-01-001")["photos"]), 1)

    def test_mobile_original_bad_sha_and_wrong_machine_are_rejected(self):
        self.add_unit()
        raw = noisy_jpeg_bytes(size=(1200, 800))
        base = {
            "photo_uuid": str(uuid.uuid4()),
            "project_id": "default",
            "scope": "engineering",
            "category": "construction",
            "unit_code": "YNLQ-001-01-001",
            "original_download_url": "/download/original",
            "original_size_bytes": len(raw),
            "original_filename": "original.jpg",
            "original_mime_type": "image/jpeg",
            "target_machine_id": "MACHINE-A",
        }
        bad_sha_cloud = FakeCloud(raw=raw, items=[{**base, "original_sha256": "0" * 64}])
        bad_sha = self.service(bad_sha_cloud)._sync_inbox()
        self.assertFalse(bad_sha["ok"])
        self.assertIn("完整性", bad_sha["error"])
        self.assertEqual(self.manager.get_project("YNLQ-001-01-001")["photos"], [])
        self.assertEqual(bad_sha_cloud.acks, [])

        wrong_machine_cloud = FakeCloud(raw=raw, items=[{
            **base,
            "photo_uuid": str(uuid.uuid4()),
            "original_sha256": hashlib.sha256(raw).hexdigest(),
            "target_machine_id": "MACHINE-B",
        }])
        wrong_machine = self.service(wrong_machine_cloud)._sync_inbox()
        self.assertFalse(wrong_machine["ok"])
        self.assertIn("当前电脑", wrong_machine["error"])
        self.assertEqual(wrong_machine_cloud.acks, [])

        missing_machine_cloud = FakeCloud(raw=raw, items=[{
            **base,
            "photo_uuid": str(uuid.uuid4()),
            "original_sha256": hashlib.sha256(raw).hexdigest(),
            "target_machine_id": "",
        }])
        missing_machine = self.service(missing_machine_cloud)._sync_inbox()
        self.assertFalse(missing_machine["ok"])
        self.assertIn("当前电脑", missing_machine["error"])
        self.assertEqual(missing_machine_cloud.acks, [])

    def test_account_machine_scoped_state_keeps_ack_without_cross_account_send(self):
        self.add_unit()
        raw = noisy_jpeg_bytes(size=(1200, 800))
        photo_uuid = str(uuid.uuid4())
        item = {
            "photo_uuid": photo_uuid,
            "project_id": "default",
            "scope": "engineering",
            "category": "construction",
            "unit_code": "YNLQ-001-01-001",
            "original_download_url": "/download/original",
            "original_sha256": hashlib.sha256(raw).hexdigest(),
            "original_size_bytes": len(raw),
            "original_filename": "account-a-original.jpg",
            "original_mime_type": "image/jpeg",
            "target_machine_id": "MACHINE-A",
            "cursor": "account-a-cursor",
        }
        cloud = FakeCloud(
            raw=raw,
            identity="account-A",
            inbox_batches=[[item]],
            ack_results=[{
                "ok": False,
                "network_error": True,
                "retryable": True,
                "error": "服务器已提交，但 ACK 响应丢失",
            }],
        )
        self.project["cloud_owner_id"] = "account-A"
        service = self.service(cloud)
        service._ensure_account_identity()

        first = service._sync_inbox()
        self.assertFalse(first["ok"])
        account_a_state = service._read_state()
        self.assertIn(photo_uuid, account_a_state["ack_pending"])
        self.assertEqual(len(cloud.acks), 1)
        self.assertEqual(cloud.acks[0][4], "account-A")

        # 切到 B：读取全新的独立分区，不能看到或发送 A 的 ACK。
        cloud.identity = "account-B"
        service._ensure_account_identity()
        account_b_state = service._read_state()
        self.assertEqual(account_b_state["ack_pending"], {})
        account_b_state.update({
            "inbox_cursor": "B-CURSOR",
            "snapshot_revision": 2026082501,
            "backfilled": {"B-PHOTO": "B-HASH"},
        })
        service._write_state(account_b_state)
        before_b = len(cloud.acks)
        b_result = service._sync_inbox()
        self.assertFalse(b_result["ok"])
        self.assertEqual(b_result["code"], "project_owner_mismatch")
        self.assertEqual(len(cloud.acks), before_b, "B 账号绝不能发送 A 的 pending ACK")

        # 切回 A：即使 inbox 已不再返回 desktop_imported 项，本地分区仍
        # 能用原 UUID 和 local ids 重发，清理完成后才移除。
        cloud.identity = "account-A"
        cloud.ack_results.append({
            "ok": True,
            "idempotent": True,
            "cleanup_status": "deleted",
            "cleanup_pending": False,
        })
        service._ensure_account_identity()
        a_retry = service._sync_inbox()
        self.assertTrue(a_retry["ok"])
        self.assertEqual(a_retry["ack_retried"], 1)
        self.assertEqual(service._read_state()["ack_pending"], {})
        self.assertEqual(cloud.acks[-1][4], "account-A")
        self.assertEqual(cloud.acks[-1][0:3], cloud.acks[0][0:3])

        cloud.identity = "account-B"
        service._ensure_account_identity()
        restored_b = service._read_state()
        self.assertEqual(restored_b["inbox_cursor"], "B-CURSOR")
        self.assertEqual(restored_b["snapshot_revision"], 2026082501)
        self.assertEqual(restored_b["backfilled"], {"B-PHOTO": "B-HASH"})
        self.assertEqual(restored_b["ack_pending"], {})

        document = json.loads((self.root / "state.json").read_text(encoding="utf-8"))
        self.assertIn("account-A|MACHINE-A", document["scopes"])
        self.assertIn("account-B|MACHINE-A", document["scopes"])

    def test_legacy_single_scope_cleanup_state_migrates_without_loss(self):
        legacy_uuid = str(uuid.uuid4())
        legacy = {
            "version": 1,
            "account_identity": "fake-account|MACHINE-A",
            "inbox_cursor": "LEGACY-CURSOR",
            "snapshot_revision": 88,
            "backfilled": {"OLD-PHOTO": "OLD-HASH"},
            "cleanup_pending": {
                legacy_uuid: {
                    "local_project_code": "YNLQ-001-01-001",
                    "local_photo_id": "SY001",
                }
            },
        }
        (self.root / "state.json").write_text(
            json.dumps(legacy, ensure_ascii=False), encoding="utf-8"
        )
        service = self.service(FakeCloud())

        migrated = service._read_state()
        self.assertIn(legacy_uuid, migrated["ack_pending"])
        self.assertIn(legacy_uuid, migrated["cleanup_pending"])
        self.assertEqual(migrated["inbox_cursor"], "LEGACY-CURSOR")
        self.assertEqual(migrated["snapshot_revision"], 88)
        self.assertEqual(migrated["backfilled"], {"OLD-PHOTO": "OLD-HASH"})
        service._write_state(migrated)
        document = json.loads((self.root / "state.json").read_text(encoding="utf-8"))
        scoped = document["scopes"]["fake-account|MACHINE-A"]
        self.assertIn(legacy_uuid, scoped["ack_pending"])
        self.assertEqual(scoped["inbox_cursor"], "LEGACY-CURSOR")

    def test_mobile_png_original_is_imported_with_exact_sha_and_extension(self):
        self.add_unit()
        output = io.BytesIO()
        Image.effect_noise((1000, 720), 66).convert("RGB").save(output, "PNG")
        raw = output.getvalue()
        expected_sha = hashlib.sha256(raw).hexdigest()
        photo_uuid = str(uuid.uuid4())
        cloud = FakeCloud(raw=raw, items=[{
            "photo_uuid": photo_uuid,
            "project_id": "default",
            "scope": "engineering",
            "category": "supervision",
            "unit_code": "YNLQ-001-01-001",
            "original_download_url": "/download/original",
            "original_sha256": expected_sha,
            "original_size_bytes": len(raw),
            "original_filename": "IMG_20260825_100000.png",
            "original_mime_type": "image/png",
            "target_machine_id": "MACHINE-A",
            "cursor": "2",
        }])

        result = self.service(cloud)._sync_inbox()
        self.assertEqual(result["imported"], 1)
        photo = self.manager.get_project("YNLQ-001-01-001")["photos"][0]
        stored = self.manager._photos_dir("YNLQ-001-01-001") / photo["filename"]
        self.assertEqual(stored.suffix.lower(), ".png")
        self.assertEqual(stored.read_bytes(), raw)
        self.assertEqual(hashlib.sha256(stored.read_bytes()).hexdigest(), expected_sha)
        self.assertEqual(photo["photo_uuid"], photo_uuid)

    def test_pending_ack_repairs_deleted_or_tampered_local_original_before_ack(self):
        for damage in ("deleted", "tampered"):
            with self.subTest(damage=damage):
                case_root = self.root / f"repair-{damage}"
                manager = FakeManager(case_root / "albums")
                code = f"YNLQ-001-01-{901 if damage == 'deleted' else 902}"
                manager.add_project(
                    code,
                    f"原图修复-{damage}",
                    source_fields={
                        "合同工程名称": "洺河龙泉缓洪工程",
                        "单位工程名称": "龙泉河单位工程",
                        "单位工程编码": "YNLQ-001",
                        "分部工程名称": "左岸连接工程",
                        "分部工程编码": "YNLQ-001-01",
                        "单元工程名称": f"原图修复-{damage}",
                        "单元工程编码": code,
                    },
                )
                raw = noisy_jpeg_bytes(size=(1250, 850))
                expected_sha = hashlib.sha256(raw).hexdigest()
                photo_uuid = str(uuid.uuid4())
                item = {
                    "photo_uuid": photo_uuid,
                    "project_id": "default",
                    "scope": "engineering",
                    "category": "construction",
                    "unit_code": code,
                    "original_download_url": "/download/original",
                    "original_sha256": expected_sha,
                    "original_size_bytes": len(raw),
                    "original_filename": f"{damage}.jpg",
                    "original_mime_type": "image/jpeg",
                    "target_machine_id": "MACHINE-A",
                    "cursor": "repair-cursor",
                }
                cloud = FakeCloud(
                    raw=raw,
                    items=[item],
                    ack_results=[
                        {
                            "ok": False,
                            "network_error": True,
                            "retryable": True,
                            "error": "首次 ACK 未收到响应",
                        },
                        {
                            "ok": True,
                            "idempotent": True,
                            "cleanup_status": "deleted",
                            "cleanup_pending": False,
                        },
                    ],
                )
                service = mobile_sync.DesktopMobileSync(
                    manager,
                    cloud,
                    lambda: dict(self.project),
                    lambda: {"nodes": []},
                    case_root / "state.json",
                    case_root / "cache",
                    machine_id_reader=lambda: "MACHINE-A",
                )

                first = service._sync_inbox()
                self.assertFalse(first["ok"])
                photo = manager.get_project(code)["photos"][0]
                stored = manager._photos_dir(code) / photo["filename"]
                self.assertEqual(stored.read_bytes(), raw)
                if damage == "deleted":
                    stored.unlink()
                else:
                    stored.write_bytes(b"X" * len(raw))

                second = service._sync_inbox()
                self.assertTrue(second["ok"])
                self.assertEqual(second["ack_local_invalid"], 1)
                self.assertEqual(second["duplicates"], 1)
                self.assertEqual(len(cloud.acks), 2, "损坏文件不得触发 pending ACK")
                self.assertEqual(len(manager.repairs), 1)
                self.assertEqual(stored.read_bytes(), raw)
                self.assertEqual(hashlib.sha256(stored.read_bytes()).hexdigest(), expected_sha)
                self.assertEqual(service._read_state()["ack_pending"], {})

    def test_backfill_reuses_small_jpeg_compresses_large_copy_and_can_pause_resume(self):
        small = jpeg_bytes()
        small_path = self.root / "small.jpg"
        small_path.write_bytes(small)
        small_preview = mobile_sync.prepare_jpeg_view_copy(small_path, self.root / "cache-direct")
        self.assertTrue(small_preview["reused_source"])
        self.assertEqual(small_preview["path"], small_path)
        self.assertEqual(small_preview["sha256"], hashlib.sha256(small).hexdigest())

        large_path = self.root / "large.jpg"
        Image.effect_noise((2000, 1400), 70).convert("RGB").save(large_path, "JPEG", quality=100)
        original_hash = hashlib.sha256(large_path.read_bytes()).hexdigest()
        large_preview = mobile_sync.prepare_jpeg_view_copy(large_path, self.root / "cache-direct")
        self.assertFalse(large_preview["reused_source"])
        self.assertLessEqual(large_preview["size_bytes"], mobile_sync.MAX_PREVIEW_BYTES)
        self.assertEqual(hashlib.sha256(large_path.read_bytes()).hexdigest(), original_hash)

        # 字节虽小但像素过大的 JPEG 也不能直接复用，手机长期预览最长边
        # 必须不超过 1920px。
        wide_path = self.root / "wide-but-small.jpg"
        Image.new("RGB", (3200, 640), (28, 96, 122)).save(
            wide_path, "JPEG", quality=45, optimize=True
        )
        self.assertLessEqual(wide_path.stat().st_size, mobile_sync.MAX_PREVIEW_BYTES)
        wide_hash = hashlib.sha256(wide_path.read_bytes()).hexdigest()
        wide_preview = mobile_sync.prepare_jpeg_view_copy(wide_path, self.root / "cache-direct")
        self.assertFalse(wide_preview["reused_source"])
        self.assertLessEqual(wide_preview["size_bytes"], mobile_sync.MAX_PREVIEW_BYTES)
        self.assertLessEqual(max(wide_preview["width"], wide_preview["height"]), 1920)
        self.assertEqual(hashlib.sha256(wide_path.read_bytes()).hexdigest(), wide_hash)

        photo_uuid = str(uuid.uuid4())
        photo = {
            "id": "SY001",
            "photo_uuid": photo_uuid,
            "filename": "construction-SY001.jpg",
            "category": "construction",
            "orientation": "landscape",
        }
        self.add_unit(photos=[photo])
        source = self.manager._photos_dir("YNLQ-001-01-001") / photo["filename"]
        source.write_bytes(small)
        cloud = FakeCloud()
        service = self.service(cloud, backfill_limit=1)
        service.pause_backfill()
        self.assertTrue(service._sync_backfill()["paused"])
        self.assertEqual(len(cloud.backfills), 0)
        service.resume_backfill()
        result = service._sync_backfill()
        self.assertEqual(result["uploaded"], 1)
        self.assertEqual(cloud.backfills[0][0], small)
        self.assertLessEqual(len(cloud.backfills[0][0]), mobile_sync.MAX_PREVIEW_BYTES)
        self.assertEqual(cloud.backfills[0][1]["desktop_machine_id"], "MACHINE-A")

    def test_backfill_permanent_photo_error_is_recorded_and_next_photo_continues(self):
        first_uuid = str(uuid.uuid4())
        second_uuid = str(uuid.uuid4())
        self.add_unit(photos=[
            {
                "id": "SY001",
                "photo_uuid": first_uuid,
                "filename": "construction-SY001.jpg",
                "category": "construction",
            },
            {
                "id": "SY002",
                "photo_uuid": second_uuid,
                "filename": "construction-SY002.jpg",
                "category": "construction",
            },
        ])
        first_source = self.manager._photos_dir("YNLQ-001-01-001") / "construction-SY001.jpg"
        second_source = self.manager._photos_dir("YNLQ-001-01-001") / "construction-SY002.jpg"
        first_source.write_bytes(jpeg_bytes(size=(700, 500)))
        second_source.write_bytes(jpeg_bytes(size=(710, 510)))
        hashes_before = [
            hashlib.sha256(first_source.read_bytes()).hexdigest(),
            hashlib.sha256(second_source.read_bytes()).hexdigest(),
        ]
        cloud = FakeCloud(backfill_results=[
            {
                "ok": False,
                "http_status": 422,
                "code": "invalid_image",
                "error": "单张预览校验失败",
                "retryable": False,
            },
            {"ok": True},
        ])
        service = self.service(cloud, backfill_limit=10)

        result = service._sync_backfill()
        state = service._read_state()
        self.assertTrue(result["ok"])
        self.assertEqual(result["uploaded"], 1)
        self.assertEqual(len(cloud.backfills), 2, "永久错误不能挡住后一张照片")
        self.assertTrue(state["backfill_errors"][first_uuid]["permanent"])
        self.assertEqual(state["backfilled"].get(second_uuid), hashlib.sha256(second_source.read_bytes()).hexdigest())
        self.assertEqual(
            [
                hashlib.sha256(first_source.read_bytes()).hexdigest(),
                hashlib.sha256(second_source.read_bytes()).hexdigest(),
            ],
            hashes_before,
            "回填始终只读本地原图",
        )

        # 相同预览的永久错误不会每 30 秒重复发送；网络/5xx 则仍中止。
        self.assertEqual(service._sync_backfill()["uploaded"], 0)
        self.assertEqual(len(cloud.backfills), 2)
        retry_state = self.root / "network-state.json"
        network_cloud = FakeCloud(backfill_results=[{
            "ok": False,
            "http_status": 503,
            "error": "temporary unavailable",
            "retryable": True,
        }])
        network_service = mobile_sync.DesktopMobileSync(
            self.manager,
            network_cloud,
            lambda: dict(self.project),
            lambda: {"nodes": []},
            retry_state,
            self.root / "network-cache",
            machine_id_reader=lambda: "MACHINE-A",
        )
        stopped = network_service._sync_backfill()
        self.assertFalse(stopped["ok"])
        self.assertEqual(stopped["http_status"], 503)
        self.assertEqual(len(network_cloud.backfills), 1)

    def test_network_failure_is_silent_and_next_30_second_cycle_retries(self):
        self.add_unit()
        cloud = FakeCloud(fail_snapshots=1)
        service = self.service(cloud)
        self.assertEqual(service.interval_seconds, 30)
        first = service.run_once()
        second = service.run_once()
        self.assertFalse(first["ok"])
        self.assertTrue(first["retryable"])
        self.assertTrue(second["ok"])
        self.assertEqual(cloud.snapshot_calls, 2)

    def test_project_name_change_requires_explicit_safe_call_and_backup(self):
        projects_path = self.root / "engineering_projects.json"
        info_path = self.root / "project_info.json"
        projects_path.write_text(json.dumps({
            "active_id": "default",
            "projects": [{"id": "default", "project_name": "旧工程", "project_code": "YNLQ"}],
        }, ensure_ascii=False), encoding="utf-8")
        info_path.write_text(json.dumps({"project_name": "旧工程", "project_code": "YNLQ"}, ensure_ascii=False), encoding="utf-8")

        preview = mobile_sync.update_engineering_project_display_name(
            projects_path, info_path, expected_current_name="旧工程", dry_run=True
        )
        self.assertTrue(preview["changed"])
        self.assertIn("旧工程", projects_path.read_text(encoding="utf-8"))
        result = mobile_sync.update_engineering_project_display_name(
            projects_path, info_path, expected_current_name="旧工程"
        )
        self.assertTrue(Path(result["project_backup"]).exists())
        self.assertEqual(
            json.loads(projects_path.read_text(encoding="utf-8"))["projects"][0]["project_name"],
            mobile_sync.TARGET_PROJECT_DISPLAY_NAME,
        )

        missing_projects = self.root / "legacy" / "engineering_projects.json"
        missing_info = self.root / "legacy" / "project_info.json"
        legacy_preview = mobile_sync.update_engineering_project_display_name(
            missing_projects, missing_info, dry_run=True
        )
        self.assertEqual(legacy_preview["before"], "默认工程")
        self.assertFalse(legacy_preview["engineering_projects_existed"])
        self.assertFalse(missing_projects.exists(), "dry-run 不得创建工程元数据")
        self.assertFalse(missing_info.exists(), "dry-run 不得创建工程信息")

    def test_download_token_is_same_origin_only_and_signed_url_is_allowlisted(self):
        class Response:
            status = 200
            headers = {"Content-Length": "4"}

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self, _limit=-1):
                return b"JPEG"

        class Opener:
            def __init__(self):
                self.requests = []

            def open(self, request, timeout=0):
                self.requests.append((request, timeout))
                return Response()

        opener = Opener()
        auth = ("https://api.shuiliyingxiang.cn", "desktop-secret-token", None)
        with patch.object(cloud_client, "_cloud_auth_context", return_value=auth), patch.object(
            cloud_client.urllib.request, "build_opener", return_value=opener
        ):
            relative = cloud_client.desktop_download_bytes("/api/mobile-photo/test?ticket=1")
            signed = cloud_client.desktop_download_bytes(
                "https://bucket.oss-cn-beijing.aliyuncs.com/object.jpg?signature=short-lived"
            )
            rejected_http = cloud_client.desktop_download_bytes(
                "http://bucket.oss-cn-beijing.aliyuncs.com/object.jpg"
            )
            rejected_host = cloud_client.desktop_download_bytes("https://evil.example/object.jpg")
            rejected_network_path = cloud_client.desktop_download_bytes("//evil.example/object.jpg")

        self.assertTrue(relative["ok"])
        relative_request = opener.requests[0][0]
        self.assertEqual(relative_request.full_url, "https://api.shuiliyingxiang.cn/api/mobile-photo/test?ticket=1")
        self.assertEqual(relative_request.get_header("Authorization"), "Bearer desktop-secret-token")
        self.assertTrue(signed["ok"])
        signed_request = opener.requests[1][0]
        self.assertIsNone(signed_request.get_header("Authorization"), "OSS 签名 URL 不得携带桌面令牌")
        self.assertFalse(rejected_http["ok"])
        self.assertFalse(rejected_host["ok"])
        self.assertFalse(rejected_network_path["ok"])
        self.assertEqual(len(opener.requests), 2, "被拒绝的主机不得发起网络请求")

    def test_desktop_sync_token_is_dpapi_protected_refreshed_and_not_mixed(self):
        account_path = self.root / "cloud_account.json"
        protected_values = {}

        def protect(value):
            cipher = f"cipher-{len(protected_values) + 1}"
            protected_values[cipher] = value
            return cipher

        with patch.object(cloud_client, "cloud_account_path", return_value=account_path), patch.object(
            cloud_client, "_dpapi_protect", side_effect=protect
        ), patch.object(
            cloud_client, "_dpapi_unprotect", side_effect=lambda value: protected_values.get(value, "")
        ):
            cloud_client._write_cloud_account({
                "username": "desktop-user",
                "server": "https://api.shuiliyingxiang.cn",
                "token": "ordinary-account-token",
                "desktop_sync_token": "machine-bound-sync-token",
            })
            stored_text = account_path.read_text(encoding="utf-8")
            self.assertNotIn("ordinary-account-token", stored_text)
            self.assertNotIn("machine-bound-sync-token", stored_text)
            stored = json.loads(stored_text)
            self.assertIn("token_protected", stored)
            self.assertIn("desktop_sync_token_protected", stored)
            self.assertNotIn("desktop_sync_token", stored)
            restored = cloud_client._read_cloud_account()
            self.assertEqual(restored["token"], "ordinary-account-token")
            self.assertEqual(restored["desktop_sync_token"], "machine-bound-sync-token")

        account = {
            "account_id": "account-123",
            "username": "desktop-user",
            "server": "https://api.shuiliyingxiang.cn",
            "token": "ordinary-account-token",
            "desktop_sync_token": "machine-bound-sync-token",
        }

        class JsonResponse:
            status = 200

            def __init__(self, request, requests):
                requests.append(request)

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return b'{"ok":true}'

        requests = []

        def urlopen(request, timeout=0):
            return JsonResponse(request, requests)

        with patch.object(cloud_client, "_read_cloud_account", return_value=account), patch.object(
            cloud_client, "_open_no_redirect", side_effect=urlopen
        ):
            self.assertTrue(cloud_client.desktop_project_snapshot({"snapshot_id": "test"})["ok"])
            self.assertTrue(cloud_client.fetch_preview_projects()["ok"])
        self.assertEqual(
            requests[0].get_header("Authorization"),
            "Bearer machine-bound-sync-token",
            "desktop/v1 只能优先使用本机同步令牌",
        )

        self.assertEqual(
            requests[1].get_header("Authorization"),
            "Bearer ordinary-account-token",
            "旧云预览 API 仍使用普通账号令牌",
        )

        old_account = {**account, "desktop_sync_token": ""}
        refreshed_account = {**account, "desktop_sync_token": "refreshed-machine-token"}
        with patch.object(
            cloud_client,
            "_read_cloud_account",
            side_effect=[old_account, old_account, refreshed_account],
        ), patch.object(cloud_client, "sync", return_value={"ok": True, "synced": True}) as refresh:
            _base, refreshed, error = cloud_client._cloud_auth_context()
        self.assertIsNone(error)
        self.assertEqual(refreshed, "refreshed-machine-token")
        refresh.assert_called_once()

        with patch.object(
            cloud_client,
            "_read_cloud_account",
            side_effect=[old_account, old_account, old_account],
        ), patch.object(
            cloud_client,
            "sync",
            return_value={"ok": False, "error": "activate unavailable"},
        ) as failed_refresh:
            _base, unsafe_fallback, refresh_error = cloud_client._cloud_auth_context()
        self.assertIsNone(unsafe_fallback, "普通账号令牌不得回退用于 desktop/v1")
        self.assertEqual(refresh_error["code"], "desktop_sync_token_required")
        failed_refresh.assert_called_once()

        team_calls = []

        def team_api(path, method="GET", payload=None, query=None, timeout=20):
            team_calls.append((path, method, payload, query, timeout))
            return {"ok": True}

        with patch.object(cloud_client, "_cloud_api_json", side_effect=team_api):
            cloud_client.desktop_project_members("local-project", "MACHINE-A")
            cloud_client.desktop_project_invites("local-project", "MACHINE-A")
            cloud_client.desktop_create_project_invite("local-project", "capturer", "MACHINE-A")
            cloud_client.desktop_update_project_member("member/7", "local-project", "viewer", "MACHINE-A")
            cloud_client.desktop_remove_project_member("member/7", "local-project", "MACHINE-A")
            cloud_client.desktop_revoke_project_invite("invite/9", "local-project", "MACHINE-A")

        self.assertEqual(team_calls[0][0:2], ("/api/desktop/v1/project-members", "GET"))
        self.assertEqual(team_calls[0][3]["desktop_machine_id"], "MACHINE-A")
        self.assertEqual(team_calls[1][0], "/api/desktop/v1/project-invites")
        self.assertEqual(team_calls[2][1], "POST")
        self.assertEqual(team_calls[2][2]["role"], "capturer")
        self.assertEqual(team_calls[3][0], "/api/desktop/v1/project-members/member%2F7")
        self.assertEqual(team_calls[3][1], "PATCH")
        self.assertEqual(team_calls[4][1], "DELETE")
        self.assertEqual(team_calls[5][0], "/api/desktop/v1/project-invites/invite%2F9")
        self.assertEqual(team_calls[5][1], "DELETE")

        strict_error_calls = []
        with patch.object(cloud_client, "_read_cloud_account", return_value=old_account), patch.object(
            cloud_client, "_refresh_desktop_sync_token", return_value=""
        ), patch.object(
            cloud_client.urllib.request,
            "urlopen",
            side_effect=lambda *_args, **_kwargs: strict_error_calls.append("urlopen"),
        ), patch.object(
            cloud_client.urllib.request,
            "build_opener",
            side_effect=lambda *_args, **_kwargs: strict_error_calls.append("opener"),
        ):
            strict_results = [
                cloud_client.desktop_project_snapshot({"snapshot_id": "strict"}),
                cloud_client.desktop_inbox(desktop_machine_id="MACHINE-A"),
                cloud_client.desktop_ack_photo(str(uuid.uuid4()), "YNLQ-001", "SY001", "MACHINE-A"),
                cloud_client.desktop_delete_photo(str(uuid.uuid4()), "YNLQ-001", "SY001", "MACHINE-A"),
                cloud_client.desktop_download_bytes("/api/mobile/v1/original"),
                cloud_client.desktop_backfill_photo(self.root / "not-read-without-token.jpg", {}),
            ]
        self.assertTrue(all(item.get("code") == "desktop_sync_token_required" for item in strict_results))
        self.assertEqual(strict_error_calls, [], "所有 desktop/v1 调用点都必须在联网前拒绝普通令牌")

        written_accounts = []
        with patch.object(
            cloud_client,
            "_post_json",
            side_effect=[
                {"ok": True, "token": "login-token", "account": {"id": "account-123", "username": "desktop-user"}},
                {"ok": True, "desktop_sync_token": "login-machine-token", "is_member": False},
            ],
        ) as login_post, patch.object(
            cloud_client, "_write_cloud_account", side_effect=lambda value: written_accounts.append(dict(value))
        ), patch("licensing.machine_id", return_value="MACHINE-A"), patch.object(
            cloud_client.threading, "Thread"
        ):
            self.assertTrue(cloud_client.login("desktop-user", "safe-password")["ok"])
        self.assertEqual(written_accounts[-1]["desktop_sync_token"], "login-machine-token")
        self.assertEqual(login_post.call_args_list[1].args[2], "login-token")

        written_accounts.clear()
        with patch.object(cloud_client, "_read_cloud_account", return_value=account), patch.object(
            cloud_client,
            "_post_json",
            return_value={"ok": True, "desktop_sync_token": "renewed-machine-token"},
        ) as sync_post, patch.object(
            cloud_client, "_write_cloud_account", side_effect=lambda value: written_accounts.append(dict(value))
        ), patch("licensing.machine_id", return_value="MACHINE-A"):
            self.assertTrue(cloud_client.sync()["ok"])
        self.assertEqual(written_accounts[-1]["desktop_sync_token"], "renewed-machine-token")
        self.assertEqual(sync_post.call_args.args[2], "ordinary-account-token")

        sanitized = cloud_client._sanitize({
            "desktop_sync_token": "never-log-this-token",
            "message": "desktop_sync_token=never-log-this-token",
        })
        self.assertEqual(sanitized["desktop_sync_token"], "[REDACTED]")
        self.assertNotIn("never-log-this-token", json.dumps(sanitized))

    def test_legacy_server_url_migrates_without_breaking_explicit_local_staging(self):
        config_path = self.root / "cloud_config.json"
        account_path = self.root / "cloud_account.json"
        config_path.write_text(
            json.dumps({"server_url": "http://47.95.221.66"}), encoding="utf-8"
        )
        account_path.write_text(
            json.dumps({
                "username": "desktop-user",
                "server": "https://47.95.221.66",
                "token_protected": "keep-this-ciphertext",
            }),
            encoding="utf-8",
        )
        with patch.object(cloud_client, "cloud_config_path", return_value=config_path), patch.object(
            cloud_client, "cloud_account_path", return_value=account_path
        ), patch.object(cloud_client, "_dpapi_unprotect", return_value=""):
            self.assertEqual(cloud_client.server_url(), cloud_client.DEFAULT_SERVER_URL)
            account = cloud_client._read_cloud_account()

        self.assertEqual(account["server"], cloud_client.DEFAULT_SERVER_URL)
        repaired_account = json.loads(account_path.read_text(encoding="utf-8"))
        self.assertEqual(repaired_account["server"], cloud_client.DEFAULT_SERVER_URL)
        self.assertEqual(repaired_account["token_protected"], "keep-this-ciphertext")

        config_path.write_text(
            json.dumps({"server_url": "http://127.0.0.1:18080"}), encoding="utf-8"
        )
        with patch.object(cloud_client, "cloud_config_path", return_value=config_path), patch.dict(
            cloud_client.os.environ, {"ALBUM_ALLOW_INSECURE_LOCALHOST": "1"}
        ):
            self.assertEqual(cloud_client.server_url(), "http://127.0.0.1:18080")

    def test_legacy_logged_in_account_backfills_stable_id_without_relogin(self):
        legacy = {
            "username": "desktop-user",
            "server": cloud_client.DEFAULT_SERVER_URL,
            "token": "ordinary-account-token",
            "desktop_sync_token": "machine-bound-sync-token",
        }
        persisted = []
        with patch.object(
            cloud_client, "_read_cloud_account", return_value=dict(legacy)
        ), patch.object(
            cloud_client,
            "_get_json_auth",
            return_value={
                "ok": True,
                "account": {"id": 38, "username": "desktop-user"},
            },
        ) as request_me, patch.object(
            cloud_client,
            "_write_cloud_account",
            side_effect=lambda value: persisted.append(dict(value)),
        ):
            repaired = cloud_client._repair_legacy_account_identity(legacy)

        self.assertEqual(repaired["account_id"], "38")
        self.assertEqual(repaired["token"], "ordinary-account-token")
        self.assertEqual(repaired["desktop_sync_token"], "machine-bound-sync-token")
        self.assertEqual(persisted[-1]["account_id"], "38")
        request_me.assert_called_once_with(
            f"{cloud_client.DEFAULT_SERVER_URL}/api/me", "ordinary-account-token"
        )


if __name__ == "__main__":
    unittest.main()
