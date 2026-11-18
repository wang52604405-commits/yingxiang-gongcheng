"""Scoped parent identity must preserve exact approved code strings."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
os.environ.setdefault('ALBUM_DATA_DIR', tempfile.mkdtemp(prefix='scoped-parent-test-'))
import app
import mobile_sync
from server import mobile_api


class ScopedParentIdentityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.project = {'id':'exact-parents','project_code':'EXACT','project_name':'公路试验','industry':'公路工程','project_type':'公路综合土建'}
        patcher=patch.object(app,'current_engineering_project',lambda *a,**k:dict(self.project))
        patcher.start(); self.addCleanup(patcher.stop)
        self.manager=app.AlbumManager(Path(self.temp.name))

    def row(self, unit='U', part='P', sub='S', contract='C'):
        return {'合同或标段名称':contract,'单位工程编码':unit,'单位工程名称':'单位',
                '分部工程编码':part,'分部工程名称':'分部','子分部工程编码':sub,'子分部工程名称':'子分部',
                '分项工程编码':'001','分项工程名称':'分项','划分依据':'批准表'}

    def test_whitespace_case_and_delimiters_do_not_merge_cloud_parents(self):
        rows=[self.row('U'),self.row(' U '),self.row('u'),self.row(part=' P '),self.row(sub=' S '),self.row(contract=' C ')]
        self.manager.import_highway_records(rows)
        snapshot=mobile_sync.build_project_snapshot(self.manager,self.project,{'nodes':[]})
        nodes=mobile_api._flatten_snapshot(snapshot['tree'],[])
        leaves=[n for n in nodes if n['node_type']=='item']
        self.assertEqual(len(leaves),len(rows))
        self.assertEqual(len({n['parent_code'] for n in leaves}),len(rows))
        self.assertEqual(len(nodes),len({n['node_code'] for n in nodes}))
        displays={n['metadata'].get('display_code') for n in nodes}
        for code in ('U',' U ','u',' P ',' S '): self.assertIn(code,displays)
        self.assertNotEqual(mobile_sync._scoped_node_code('X','a|b','c'), mobile_sync._scoped_node_code('X','a','b|c'))
        self.assertNotEqual(mobile_sync._scoped_node_code('X','U'), mobile_sync._scoped_node_code('X',' U '))

    def test_legacy_hash_behavior_unchanged(self):
        self.assertEqual(mobile_sync._node_code('X',' U '),mobile_sync._node_code('X','U'))

if __name__=='__main__': unittest.main()
