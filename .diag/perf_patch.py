from pathlib import Path
p=Path('app.py');s=p.read_text(encoding='utf-8')
a=s.index('        if not path.exists():',s.index('    def _read_metadata('));b=s.index('        data.setdefault("project_code"',a)
s=s[:a]+'''        for attempt in range(6):
            try:
                with path.open("r", encoding="utf-8") as f:
                    data = json.load(f)
                break
            except PermissionError:
                # Atomic replacement on Windows can briefly deny a new reader.
                # A busy existing file is never an empty/new photo collection.
                if attempt == 5:
                    raise
                time.sleep(0.01 * (attempt + 1))
            except FileNotFoundError:
                if signature is not None:
                    if attempt == 5:
                        raise
                    time.sleep(0.01 * (attempt + 1))
                    continue
                return {"project_code": key, "project_name": key, "keywords": "", "source_fields": {}, "photos": []}
            except json.JSONDecodeError as exc:
                raise ValueError("单元资料记录无法解析，已保留原文件，请核查或从备份恢复") from exc
        if not isinstance(data, dict) or not isinstance(data.get("photos", []), list):
            raise ValueError("单元资料记录格式异常，已保留原文件")
'''+s[b:];p.write_text(s,encoding='utf-8',newline='\n')
p=Path('assets/app-A20260910-2.92.js');s=p.read_text(encoding='utf-8')
old='''        if (!cached) await loadPartPage(part, 1);
''';new='''        if (!cached) await loadPartPage(part, 1);
        else await revalidatePart(part);
''';assert s.count(old)==1;s=s.replace(old,new)
anchor='    async function loadPartPage(part, page = 1) {';assert s.count(anchor)==1
s=s.replace(anchor,'''    async function revalidatePart(part) {
      const context = navigationContext();
      const revision = await apiJson("/api/revision");
      if (!revision.authenticated || state.selectedPart !== part || state.viewMode !== "part" || navigationContext() !== context) return;
      if (Number(revision.revision || 0) !== Number(part.loadedRevision || 0)) {
        state.revision = Number(revision.revision || 0);
        await loadPartPage(part, 1, { silent: true });
        scheduleSummaryRefresh();
      }
    }

    async function loadPartPage(part, page = 1, options = {}) {''')
a=s.index('    async function loadPartPage(');b=s.index('    function renderPart()',a);block=s[a:b];block=block.replace('      part.loading = true;','      part.loading = !(options.silent && part.projects?.length);',1);s=s[:a]+block+s[b:]
old='''      if (state.selectedPart) {
        renderPart();
        setView("part");
      } else {
        openOverview("construction");
      }
    });''';new='''      if (state.selectedPart) {
        renderPart();
        setView("part");
        revalidatePart(state.selectedPart).catch((error) => showNotice(error.message, true));
      } else {
        openOverview("construction");
      }
    });''';assert s.count(old)==1;s=s.replace(old,new);p.write_text(s,encoding='utf-8',newline='\n')
p=Path('tests/test_z_performance_navigation.py');s=p.read_text(encoding='utf-8')
old="raw=json.loads(m._metadata_path('U1').read_text(encoding='utf-8'));self.assertEqual(len(raw['photos']),24)";new="raw=m.get_project('U1');self.assertEqual(len(raw['photos']),24)";assert s.count(old)==1;s=s.replace(old,new)
extra='''
    def test_transient_reader_conflict_returns_full_records_not_empty_defaults(self):
        self.seed('U1',24);m=self.manager;m.invalidate_projects_cache()
        path=m._metadata_path('U1');real=Path.open;attempts=[]
        def busy(p,*args,**kwargs):
            if p==path:
                attempts.append(1)
                if len(attempts)<3:raise PermissionError('Windows reader conflict')
            return real(p,*args,**kwargs)
        with patch.object(Path,'open',busy):data=m.get_project('U1')
        self.assertEqual(len(data['photos']),24);self.assertEqual(len(attempts),3)

    def test_unreadable_or_corrupt_metadata_never_turns_into_empty_collection(self):
        self.seed('U1',24);m=self.manager;m.invalidate_projects_cache()
        path=m._metadata_path('U1');before=path.read_bytes();real=Path.open;attempts=[]
        def busy(p,*args,**kwargs):
            if p==path:
                attempts.append(1);raise PermissionError('persistent denial')
            return real(p,*args,**kwargs)
        with patch.object(Path,'open',busy):
            with self.assertRaises(PermissionError):m.get_project('U1')
        self.assertEqual(len(attempts),6);self.assertEqual(path.read_bytes(),before)
        path.write_text('{broken-record',encoding='utf-8');m.invalidate_projects_cache()
        with self.assertRaises(ValueError):m.get_project('U1')
        self.assertEqual(path.read_text(encoding='utf-8'),'{broken-record')
'''
assert "if __name__=='__main__':unittest.main()" in s;s=s.replace("if __name__=='__main__':unittest.main()",extra+"\nif __name__=='__main__':unittest.main()");p.write_text(s,encoding='utf-8',newline='\n')
p=Path('tests/run_performance_browser.py');s=p.read_text(encoding='utf-8')
old="                    page.locator('#uploadModalForm input[type=date]').fill('2026-09-14');";new="                    page.locator('#uploadModalForm summary').click();page.locator('#uploadModalForm input[type=date]').fill('2026-09-14');";assert s.count(old)==1;s=s.replace(old,new)
old="                    if '/api/cloud/status' in url:return route.fulfill(json={'ok':True,'logged_in':False,'project_ownership':{'state':'logged_out'}})"
new=old+"""
                    if '/api/cloud/project-members' in url:return route.fulfill(json={'ok':True,'members':[],'membership':{'role':'owner'}})
                    if '/api/cloud/project-invites' in url:return route.fulfill(json={'ok':True,'invites':[]})
                    if '/api/cloud/product-config' in url:return route.fulfill(json={'ok':True,'product':{}})
                    if '/api/cloud/invite-status' in url:return route.fulfill(json={'ok':True,'logged_in':False})""";assert s.count(old)==1;s=s.replace(old,new)
old="                    check('return to unchanged part reuses all cached units')"
new=old+"""
                    page.locator('[data-unit-code="U-MAIN"]').click();ready('U-MAIN')
                    m.copy_construction_to_supervision('U-DEST')
                    page.locator('#backPartBtn').click()
                    page.wait_for_function('()=>state.selectedPart.projects.find(p=>p.project_code==="U-DEST")?.photo_count===4')
                    page.wait_for_timeout(450)
                    check('cached return revalidates another client mutation without hiding the list')""";assert s.count(old)==1;s=s.replace(old,new)
old="                    pp=context.new_page();pp.on('pageerror',lambda e:errors.append(str(e)))"
new="""                    page.locator('#settingsMenuBtn').click();page.locator('#projectInfoModal.open').wait_for()
                    for tab in ('info','division','members','upload','print','account','device'):
                        page.locator(f'[data-project-settings-tab="{tab}"]').click()
                        assert page.locator(f'[data-project-settings-tab="{tab}"].active').count()==1
                        panels=page.locator('[data-project-settings-panel].active')
                        assert panels.count()>0 and panels.first.is_visible()
                        page.screenshot(path=str(out/f'settings-{tab}.png'))
                    page.locator('#closeProjectInfoBtn').click();check('all seven settings tabs remain accessible in the existing theme (cloud display fixtures only)')
                    pp=context.new_page();pp.on('pageerror',lambda e:errors.append(str(e)))""";assert s.count(old)==1;s=s.replace(old,new);p.write_text(s,encoding='utf-8',newline='\n')
