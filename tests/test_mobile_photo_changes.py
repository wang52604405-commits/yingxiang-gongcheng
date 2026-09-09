import json
import tempfile
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from tests.test_mobile_sync import FakeManager
from mobile_photo_changes import apply_change

class MobilePhotoChangesTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)
        self.manager=FakeManager(self.root/"albums")
        self.photo_uuid=str(uuid.uuid4())
        self.manager.add_project("UNIT-A","单元",photos=[{"id":"001","photo_uuid":self.photo_uuid,"filename":"original.jpg","title":"原题名","photo_date":"2026-09-01"}])
        self.original=self.manager._photos_dir("UNIT-A")/"original.jpg"
        self.original.write_bytes(b"exact original bytes must survive")
        self.identity={"ok":True,"project_ref":"1:P1","account_id":"1","local_project_id":"P1"}
        def find(value):
            for code,data in self.manager.projects.items():
                for photo in data.get("photos",[]):
                    if photo.get("photo_uuid")==value:return {"project_code":code,"photo_id":photo["id"],"photo":photo}
        def update(code,photo_id,**values):
            data=self.manager.get_project(code)
            for photo in data["photos"]:
                if photo["id"]==photo_id:photo.update(values)
            self.manager._write_metadata(code,data)
        self.manager.update_photo=update
        self.sync=SimpleNamespace(manager=self.manager,state_path=self.root/"state.json",_find_photo_uuid=find,_project_ownership_status=lambda:self.identity,_resolve_inbox_target=lambda value:("UNIT-A","construction",""))
    def tearDown(self):self.temp.cleanup()
    def test_delete_keeps_exact_original_in_recovery_folder_and_is_idempotent(self):
        event={"id":1,"photo_uuid":self.photo_uuid,"action":"delete"}
        apply_change(self.sync,event,self.identity)
        self.assertEqual(self.manager.get_project("UNIT-A")["photos"],[])
        self.assertFalse(self.original.exists())
        copies=list((self.root/"mobile_photo_trash").rglob("0-original.jpg"))
        self.assertEqual(len(copies),1)
        self.assertEqual(copies[0].read_bytes(),b"exact original bytes must survive")
        apply_change(self.sync,event,self.identity)
        self.assertEqual(copies[0].read_bytes(),b"exact original bytes must survive")
    def test_metadata_failure_rolls_original_back(self):
        with patch.object(self.manager,"_write_metadata",side_effect=OSError("disk full")):
            with self.assertRaises(OSError):apply_change(self.sync,{"id":2,"photo_uuid":self.photo_uuid,"action":"delete"},self.identity)
        self.assertTrue(self.original.exists())
        self.assertEqual(self.original.read_bytes(),b"exact original bytes must survive")
        self.assertEqual(len(self.manager.get_project("UNIT-A")["photos"]),1)
    def test_edit_changes_only_metadata_and_cross_account_action_is_rejected(self):
        apply_change(self.sync,{"id":3,"photo_uuid":self.photo_uuid,"action":"edit","payload":{"title":"手机修改","photo_date":"2026-09-10"}},self.identity)
        self.assertEqual(self.manager.get_project("UNIT-A")["photos"][0]["title"],"手机修改")
        self.assertEqual(self.original.read_bytes(),b"exact original bytes must survive")
        old=dict(self.identity);self.identity={**old,"ok":False,"account_id":"2"}
        with self.assertRaises(ValueError):apply_change(self.sync,{"id":4,"photo_uuid":self.photo_uuid,"action":"delete"},old)
        self.assertTrue(self.original.exists())
