"""Apply explicit mobile edits; deleted originals go to a recoverable local vault."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path

def apply_change(sync, change, identity):
    current = sync._project_ownership_status()
    if not current.get("ok") or current.get("project_ref") != identity["project_ref"] or current.get("account_id") != identity.get("account_id"):
        raise ValueError("工程已切换，本轮修改同步停止")
    photo_uuid = str(change.get("photo_uuid") or "")
    import uuid
    if str(uuid.UUID(photo_uuid)) != photo_uuid:
        raise ValueError("照片标识无效")
    found = sync._find_photo_uuid(photo_uuid)
    if not found:
        return
    manager = sync.manager
    code = found["project_code"]
    if change.get("action") == "delete":
        bucket = hashlib.sha256(identity["project_ref"].encode()).hexdigest()[:20]
        trash = sync.state_path.parent / "mobile_photo_trash" / bucket / photo_uuid
        with manager._project_write_lock(code):
            data = manager.get_project(code)
            photo = next((p for p in data.get("photos",[]) if p.get("photo_uuid") == photo_uuid),None)
            if not photo:
                raise ValueError("照片正在移动，请下轮重试")
            filename = str(photo.get("filename") or "")
            if not filename or Path(filename).name != filename:
                raise ValueError("照片文件路径无效")
            sources = [manager._photos_dir(code) / filename]
            thumb = getattr(manager,"_thumb_filename",None)
            if callable(thumb): sources.append(manager._photos_dir(code) / thumb(filename))
            original = str(photo.get("original_backup") or "")
            if original:
                if Path(original).name != original: raise ValueError("原图备份路径无效")
                sources.append(manager._original_path(code,original))
            trash.mkdir(parents=True,exist_ok=True)
            manifest = trash / "record.json"
            if not manifest.exists():
                manifest.write_text(json.dumps({"project_code":code,"photo":photo,"event_id":change["id"]},ensure_ascii=False),encoding="utf-8")
            moved=[]
            try:
                for index,source in enumerate(sources):
                    target=trash / (str(index)+"-"+source.name)
                    if source.exists():
                        if target.exists(): raise ValueError("回收备份冲突，未删除原图")
                        os.replace(source,target)
                        moved.append((source,target))
                data["photos"]=[p for p in data.get("photos",[]) if p.get("photo_uuid") != photo_uuid]
                manager._write_metadata(code,data)
            except Exception:
                for source,target in reversed(moved):
                    if target.exists() and not source.exists(): os.replace(target,source)
                raise
        return
    if change.get("action") != "edit": raise ValueError("未知照片修改类型")
    values=change.get("payload") or {}
    assignment=values.get("assignment") or {}
    if assignment:
        target,category,process=sync._resolve_inbox_target({"scope":values.get("scope"),"category":values.get("category"),**assignment})
        if target != code:
            manager.move_photo(code,found["photo_id"],target,category,process)
            found=sync._find_photo_uuid(photo_uuid)
            code=found["project_code"]
        elif "process_name" in assignment:
            manager.update_photo(code,found["photo_id"],process_name=process)
    manager.update_photo(code,found["photo_id"],title=values.get("title",""),photo_date=values.get("photo_date",""))
    with manager._project_write_lock(code):
        data=manager.get_project(code)
        for photo in data.get("photos",[]):
            if photo.get("photo_uuid")==photo_uuid: photo["mobile_classification_pending"]=False
        manager._write_metadata(code,data)

def sync_changes(sync):
    fetch=getattr(sync.cloud,"desktop_photo_changes",None)
    if not callable(fetch): return {"ok":True,"applied":0}
    identity=sync._project_ownership_status()
    if not identity.get("ok"):return identity
    project_id=identity["local_project_id"]
    state=sync._read_state();cursor=(state.get("photo_change_cursors") or {}).get(project_id,0)
    response=fetch(project_id,cursor,sync._desktop_machine_id())
    if not response.get("ok"):return response
    applied=0
    try:
        for change in response.get("changes",[]):
            apply_change(sync,change,identity)
            state=sync._read_state()
            state.setdefault("photo_change_cursors",{})[project_id]=int(change["id"])
            sync._write_state(state)
            applied+=1
        return {"ok":True,"applied":applied}
    except Exception as exc:
        return {"ok":False,"error":str(exc),"applied":applied,"retryable":True}
