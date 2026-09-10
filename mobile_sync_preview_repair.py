# -*- coding: utf-8 -*-
"""Repair Pillow preview verification failures during desktop/cloud reconciliation.

Production diagnostics on 2026-09-10 found historical backfill rows permanently
blocked by Pillow's "verify must be called directly after open" error.  The
repair keeps already confirmed UUIDs, retries only that known-bad validation
failure, and replaces preview generation with a verify-first implementation.
"""

from __future__ import annotations

import hashlib
import os
from datetime import datetime
from pathlib import Path

import mobile_sync
import mobile_sync_reconcile

REPAIR_REVISION = "preview-verify-first-v1-20260910"
LEGACY_VERIFY_ERROR = "verify must be called directly after open"


def prepare_jpeg_view_copy_verify_first(source: Path, cache_dir: Path) -> dict:
    """Generate the long-lived JPEG preview while calling Pillow.verify first."""
    source = Path(source)
    stat = source.stat()
    from PIL import Image, ImageOps

    # Pillow 12+ requires verify() to be the first image-decoding operation after
    # Image.open().  Do not read EXIF or dimensions from this handle first.
    with Image.open(source) as opened:
        opened.verify()

    # Re-open after verify to inspect metadata and, when needed, decode pixels.
    with Image.open(source) as opened:
        source_format = opened.format
        width, height = opened.size
        exif_orientation = int(opened.getexif().get(0x0112) or 1)

    if (
        source_format == "JPEG"
        and 0 < stat.st_size <= mobile_sync.MAX_PREVIEW_BYTES
        and max(width, height) <= 1920
    ):
        raw_sha = hashlib.sha256(source.read_bytes()).hexdigest()
        return {
            "path": source,
            "sha256": raw_sha,
            "size_bytes": stat.st_size,
            "width": width,
            "height": height,
            "exif_orientation": exif_orientation if 1 <= exif_orientation <= 8 else 1,
            "reused_source": True,
        }

    key = hashlib.sha256(
        f"{source.resolve()}|{stat.st_mtime_ns}|{stat.st_size}|jpeg100k-v3-verify-first".encode("utf-8")
    ).hexdigest()
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    target = cache_dir / f"{key}.jpg"
    if not target.exists():
        with Image.open(source) as opened:
            image = ImageOps.exif_transpose(opened)
            image.load()
            raw = mobile_sync._encode_jpeg_under_budget(image)
        temporary = target.with_suffix(".jpg.tmp")
        temporary.write_bytes(raw)
        os.replace(temporary, target)
    raw = target.read_bytes()
    details = mobile_sync._validate_preview_jpeg(raw)
    return {
        "path": target,
        "sha256": details["sha256"],
        "size_bytes": len(raw),
        "width": details["width"],
        "height": details["height"],
        "exif_orientation": 1,
        "reused_source": False,
    }


def _prepare_targeted_retry(self):
    """Clear only the known Pillow-order false failures, preserving good work."""
    state = self._read_state()
    if state.get("backfill_preview_repair_revision") == REPAIR_REVISION:
        return

    errors = state.get("backfill_errors") or {}
    removed = 0
    for photo_uuid, entry in list(errors.items()):
        if not isinstance(entry, dict):
            continue
        if str(entry.get("code") or "") != "local_preview_invalid":
            continue
        if LEGACY_VERIFY_ERROR not in str(entry.get("error") or "").lower():
            continue
        errors.pop(photo_uuid, None)
        removed += 1

    # Keep all confirmed UUID/fingerprint data.  Reset only the scan cursor so
    # previously blocked candidates become reachable immediately.
    state["backfill_errors"] = errors
    state["backfill_scan_cursor"] = ""
    state["backfill_last_uuid"] = ""
    state["backfill_inventory"] = {}
    state["backfill_preview_repair_revision"] = REPAIR_REVISION
    state["backfill_preview_repair_removed"] = removed
    state["backfill_preview_repair_at"] = datetime.now().isoformat(timespec="seconds")
    self._write_state(state)


def apply_patch():
    if getattr(mobile_sync.DesktopMobileSync, "_preview_verify_repair_patch", False):
        return
    mobile_sync.prepare_jpeg_view_copy = prepare_jpeg_view_copy_verify_first
    # _sync_backfill_full resolves this global each cycle, so replacing it here
    # changes only the one-time preparation step and leaves the reconciler intact.
    mobile_sync_reconcile._prepare_one_time_reconcile = _prepare_targeted_retry
    mobile_sync.DesktopMobileSync._preview_verify_repair_patch = True


apply_patch()
