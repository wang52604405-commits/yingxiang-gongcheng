# -*- coding: utf-8 -*-
"""One-time full desktop/cloud photo reconciliation.

The legacy backfill intentionally skipped photos that originally came from the
mini program and trusted the local ``backfilled`` cache forever.  After a cloud
record loss/migration this can leave the desktop inventory larger than the
mobile library indefinitely.

This compatibility patch keeps ``mobile_sync.py`` stable while making the
installed 2.92 server process do one authoritative rescan of every local photo.
Existing cloud rows remain idempotent; mobile-origin rows that already exist
return ``photo_uuid_conflict`` when replayed through the desktop endpoint and
are treated as verified.  Missing rows are recreated from the durable desktop
copy as preview-only desktop records.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import mobile_sync

RECONCILE_REVISION = "desktop-full-inventory-v1-20260910"
MIN_BACKFILL_BATCH = 25


def _iter_all_backfill_candidates(self, inventory=None):
    ownership = self._project_ownership_status()
    if not ownership.get("ok"):
        return
    project_identity = mobile_sync._engineering_project_identity(
        self.engineering_project_reader() or {}
    )
    mobile_sync.ensure_all_photo_uuids(self.manager)
    for project in self.manager.list_projects(include_other=True):
        code = str(project.get("project_code") or "").strip()
        if not code:
            continue
        data = self.manager.get_project(code)
        fields = data.get("source_fields") or {}
        is_other = bool(fields.get("_other_image"))
        hierarchy = self.manager.project_hierarchy(data)
        for photo in data.get("photos", []):
            if inventory is not None:
                inventory["local_photo_count"] += 1
                category = "other" if is_other else str(photo.get("category") or "construction")
                inventory["categories"][category] = inventory["categories"].get(category, 0) + 1
            photo_uuid = mobile_sync._canonical_uuid(photo.get("photo_uuid"))
            if not photo_uuid:
                if inventory is not None:
                    inventory["invalid_uuid_count"] += 1
                continue
            mobile_origin = bool(
                photo.get("mobile_compressed_200k") or photo.get("mobile_original_received")
            )
            if mobile_origin and inventory is not None:
                inventory["mobile_origin_count"] += 1
            filename = Path(str(photo.get("filename") or "")).name
            source = self.manager._photos_dir(code) / filename
            if not filename or not source.is_file():
                if inventory is not None:
                    inventory["missing_file_count"] += 1
                continue
            target = {
                "project_id": project_identity["local_project_id"],
                "local_project_id": project_identity["local_project_id"],
                "project_ref": project_identity["project_ref"],
                "project_owner_account_id": project_identity["owner_account_id"],
                "scope": "other" if is_other else "engineering",
                "category": "" if is_other else str(photo.get("category") or "construction"),
                "unit_code": "" if is_other else str(
                    hierarchy.get("unit_code") or data.get("display_project_code") or code
                ),
                "process_name": "" if is_other else str(photo.get("process_name") or ""),
                "other_node_code": code if is_other else "",
            }
            yield {
                "project_code": code,
                "photo": photo,
                "photo_uuid": photo_uuid,
                "source": source,
                "target": target,
                "mobile_origin": mobile_origin,
            }


def _prepare_one_time_reconcile(self):
    state = self._read_state()
    if state.get("backfill_reconcile_revision") == RECONCILE_REVISION:
        return
    # Only reset backfill bookkeeping.  Inbox/ACK/delete state is independent
    # and must never be touched by a historical inventory reconciliation.
    state["backfilled"] = {}
    state["backfill_fingerprints"] = {}
    state["backfill_errors"] = {}
    state["backfill_scan_cursor"] = ""
    state["backfill_last_uuid"] = ""
    state["backfill_inventory"] = {}
    state["backfill_reconcile_revision"] = RECONCILE_REVISION
    state["backfill_reconcile_started_at"] = datetime.now().isoformat(timespec="seconds")
    self._write_state(state)


def _sync_backfill_full(self):
    ownership = self._project_ownership_status()
    if not ownership.get("ok"):
        return {**ownership, "uploaded": 0}
    _prepare_one_time_reconcile(self)
    state = self._read_state()
    identity = self._state_identity()
    generation = self._cloud_generation()
    project_ref = ownership.get("project_ref")

    def still_current():
        return (
            self._state_identity() == identity
            and self._cloud_generation() == generation
            and self._project_ownership_status().get("project_ref") == project_ref
        )

    if state.get("backfill_paused"):
        return {
            "ok": True,
            "paused": True,
            "uploaded": 0,
            "inventory": state.get("backfill_inventory", {}),
        }

    inventory = {
        "local_photo_count": 0,
        "categories": {},
        "mobile_origin_count": 0,
        "missing_file_count": 0,
        "invalid_uuid_count": 0,
        "reconcile_revision": RECONCILE_REVISION,
    }
    candidates = list(self._iter_backfill_candidates(inventory))
    fingerprints = {}
    for candidate in candidates:
        try:
            fingerprints[candidate["photo_uuid"]] = self._backfill_source_fingerprint(candidate)
        except OSError:
            fingerprints[candidate["photo_uuid"]] = ""

    uploaded = attempted = verified = 0
    mobile_existing = 0

    def finish(result):
        if not still_current():
            return {
                "ok": False,
                "code": "account_changed_during_sync",
                "error": "账号或工程已切换，本轮已停止",
                "retryable": True,
                "uploaded": uploaded,
            }
        current = self._read_state()
        known = current.get("backfilled", {})
        errors = current.get("backfill_errors", {})
        checks = current.get("backfill_fingerprints", {})
        keys = set(fingerprints)
        permanent = {
            key
            for key in keys
            if isinstance(errors.get(key), dict)
            and errors[key].get("permanent")
            and fingerprints[key]
            and errors[key].get("source_fingerprint") == fingerprints[key]
            and (
                errors[key].get("code") == "local_preview_invalid"
                or errors[key].get("validation_revision")
                == current.get("snapshot_revision", "")
            )
        }
        inventory.update(
            {
                "project_ref": project_ref,
                "candidate_count": len(candidates),
                "server_confirmed_count": sum(key in known for key in keys),
                "current_verified_count": sum(
                    bool(key in known and fingerprints[key] and checks.get(key) == fingerprints[key])
                    for key in keys
                ),
                "pending_count": sum(key not in known and key not in permanent for key in keys),
                "permanent_error_count": len(permanent),
                "error_count": sum(key in errors for key in keys),
                "mobile_existing_count": mobile_existing,
                "checked_at": datetime.now().isoformat(timespec="seconds"),
                "cycle_attempted": attempted,
                "cycle_uploaded": uploaded,
                "cycle_verified": verified,
            }
        )
        if inventory["pending_count"] == 0:
            inventory["reconcile_completed_at"] = datetime.now().isoformat(timespec="seconds")
        current["backfill_inventory"] = inventory
        self._write_state(current)
        return {**result, "uploaded": uploaded, "inventory": inventory}

    cursor = str(state.get("backfill_scan_cursor") or state.get("backfill_last_uuid") or "")
    position = next(
        (index + 1 for index, item in enumerate(candidates) if item["photo_uuid"] == cursor),
        0,
    )
    candidates = candidates[position:] + candidates[:position]

    for candidate in candidates:
        if not still_current():
            return finish({"ok": False})
        if attempted + verified >= self.backfill_limit:
            break
        photo_uuid = candidate["photo_uuid"]
        photo = candidate["photo"]
        fingerprint = fingerprints[photo_uuid]
        if (
            fingerprint
            and state["backfilled"].get(photo_uuid)
            and state["backfill_fingerprints"].get(photo_uuid) == fingerprint
        ):
            continue
        previous_error = state["backfill_errors"].get(photo_uuid)
        if (
            fingerprint
            and isinstance(previous_error, dict)
            and previous_error.get("permanent")
            and previous_error.get("source_fingerprint") == fingerprint
            and (
                previous_error.get("code") == "local_preview_invalid"
                or previous_error.get("validation_revision")
                == state.get("snapshot_revision", "")
            )
        ):
            continue
        state = self._read_state()
        if state.get("backfill_paused") or self._stop_event.is_set():
            return finish(
                {
                    "ok": True,
                    "paused": bool(state.get("backfill_paused")),
                    "stopped": self._stop_event.is_set(),
                }
            )
        try:
            preview = mobile_sync.prepare_jpeg_view_copy(candidate["source"], self.cache_dir)
        except Exception as exc:
            attempted += 1
            state["backfill_errors"][photo_uuid] = {
                "permanent": True,
                "source_fingerprint": fingerprint,
                "error": str(exc)[:300],
                "code": "local_preview_invalid",
                "updated_at": datetime.now().isoformat(timespec="seconds"),
            }
            state["backfill_scan_cursor"] = photo_uuid
            self._write_state(state)
            continue
        if not still_current():
            return finish({"ok": False})
        state = self._read_state()
        if state["backfilled"].get(photo_uuid) == preview["sha256"]:
            state["backfill_fingerprints"][photo_uuid] = fingerprint
            state["backfill_scan_cursor"] = photo_uuid
            self._write_state(state)
            verified += 1
            continue

        metadata = {
            "photo_uuid": photo_uuid,
            **candidate["target"],
            "desktop_machine_id": self._desktop_machine_id(),
            "title": str(photo.get("title") or ""),
            "photo_date": str(photo.get("photo_date") or ""),
            "photographer": str(photo.get("photographer") or ""),
            "uploaded_by": str(photo.get("uploaded_by") or ""),
            "photographer_account_id": str(photo.get("photographer_account_id") or ""),
            "uploaded_by_account_id": str(photo.get("uploaded_by_account_id") or ""),
            "client_captured_at": mobile_sync._iso_local_time(str(photo.get("upload_time") or "")),
            "orientation": preview.get("exif_orientation", 1),
            "width": preview["width"],
            "height": preview["height"],
            "sha256": preview["sha256"],
        }
        attempted += 1
        result = self.cloud.desktop_backfill_photo(preview["path"], metadata)
        if not still_current():
            return finish({"ok": False})
        state = self._read_state()
        if not result.get("ok"):
            try:
                http_status = int(result.get("http_status") or 0)
            except (TypeError, ValueError):
                http_status = 0
            code = str(result.get("code") or "")
            # A mobile-origin photo already present in the cloud cannot be replayed
            # as source=desktop because server source identity is immutable.  The
            # 409 proves that UUID already exists under this owner, so it is a
            # successful reconciliation for this local mobile-origin copy.
            if candidate.get("mobile_origin") and http_status == 409 and code == "photo_uuid_conflict":
                state["backfilled"][photo_uuid] = preview["sha256"]
                state["backfill_fingerprints"][photo_uuid] = fingerprint
                state["backfill_scan_cursor"] = photo_uuid
                state["backfill_last_uuid"] = photo_uuid
                state["backfill_updated_at"] = datetime.now().isoformat(timespec="seconds")
                state["backfill_errors"].pop(photo_uuid, None)
                self._write_state(state)
                verified += 1
                mobile_existing += 1
                continue
            photo_validation_error = (
                http_status in {400, 409, 413, 415, 422}
                or (
                    http_status == 404
                    and code in {"unit_not_found", "other_node_not_found"}
                )
            )
            if photo_validation_error and not result.get("network_error"):
                state["backfill_errors"][photo_uuid] = {
                    "permanent": True,
                    "source_fingerprint": fingerprint,
                    "validation_revision": state.get("snapshot_revision", ""),
                    "preview_sha256": preview["sha256"],
                    "http_status": http_status,
                    "code": code[:80],
                    "error": str(result.get("error") or "云端预览校验失败")[:300],
                    "updated_at": datetime.now().isoformat(timespec="seconds"),
                }
                state["backfill_scan_cursor"] = photo_uuid
                self._write_state(state)
                continue
            return finish(result)

        state["backfilled"][photo_uuid] = preview["sha256"]
        state["backfill_fingerprints"][photo_uuid] = fingerprint
        state["backfill_scan_cursor"] = photo_uuid
        state["backfill_last_uuid"] = photo_uuid
        state["backfill_updated_at"] = datetime.now().isoformat(timespec="seconds")
        state["backfill_errors"].pop(photo_uuid, None)
        self._write_state(state)
        uploaded += 1

    return finish({"ok": True})


def apply_patch():
    cls = mobile_sync.DesktopMobileSync
    if getattr(cls, "_full_inventory_reconcile_patch", False):
        return
    original_init = cls.__init__

    def patched_init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        self.backfill_limit = max(MIN_BACKFILL_BATCH, int(self.backfill_limit or 0))

    cls.__init__ = patched_init
    cls._iter_backfill_candidates = _iter_all_backfill_candidates
    cls._sync_backfill = _sync_backfill_full
    cls._full_inventory_reconcile_patch = True
    mobile_sync.DEFAULT_BACKFILL_LIMIT = max(
        MIN_BACKFILL_BATCH, int(getattr(mobile_sync, "DEFAULT_BACKFILL_LIMIT", 0) or 0)
    )


apply_patch()
