"""Real Chromium -> isolated HTTP application -> temporary files.
Cloud/OCR/membership providers are test doubles; real session, CRUD, templates,
files, browser events and PDF rendering are exercised. Never uses production data.
"""
from __future__ import annotations
import argparse, contextlib, hashlib, io, json, logging, os, sys, tempfile, threading, time, traceback
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlencode
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--out-dir',required=True);parser.add_argument('--round',type=int,default=1)
    args=parser.parse_args();out=Path(args.out_dir).resolve();out.mkdir(parents=True,exist_ok=True)
    report={'round':args.round,'checks':[],'timings_ms':{},'print_variants':[],
        'isolation':'temporary files; no production access; external cloud/OCR/membership providers mocked',
        'scope':'desktop browser and PDFs, not physical printing, real WeChat operations, or customer WAN'}
    with tempfile.TemporaryDirectory(prefix='album-browser-gate-') as tmp:
        root=Path(tmp);os.environ['ALBUM_DATA_DIR']=str(root/'data');os.environ['ALBUM_OTHER_IMAGES_TEMPLATE_DIR']=str(root/'absent')
        import app as a
        from PIL import Image,ImageDraw
        from werkzeug.security import generate_password_hash
        from werkzeug.serving import make_server
        from playwright.sync_api import sync_playwright
        import fitz
        logging.getLogger('werkzeug').setLevel(logging.ERROR)
        a.app.config.update(TESTING=True)
        project=a.default_engineering_project()
        project.update(id='default',project_name='性能验收工程',project_code='TEST',delete_password_hash=generate_password_hash('TestDelete2026!'),engineering_settings=json.loads(json.dumps(a.DEFAULT_ENGINEERING_SETTINGS)),other_images={'nodes':[]})
        a.write_engineering_projects({'active_id':'default','projects':[project]});m=a.manager
        def seed(code,name,count=0):
            d={'project_code':code,'display_project_code':code,'project_name':name,'engineering_project_id':'default',
               'project_order':int(code.split('-')[-1]) if code.split('-')[-1].isdigit() else 1,
               'source_fields':{'工程项目ID':'default','合同工程名称':'性能验收合同','单位工程名称':'验收单位','单位工程编码':'TEST-1','分部工程名称':'验收分部','分部工程编码':'TEST-1-01','单元工程名称':name,'单元工程编码':code},'processes':['开挖','验收'],'photos':[]}
            m._photos_dir(code).mkdir(parents=True);m._originals_dir(code).mkdir(parents=True);counters={}
            for i in range(count):
                cat='construction';process=''
                if code=='U-MAIN' and i>=150:
                    cat='supervision' if i>=158 else 'construction';process='' if i>=158 else '开挖'
                key=(cat,process);counters[key]=counters.get(key,0)+1
                pid=m._archive_id_for_photo(d,{'process_name':process},cat,counters[key]);pc=m._process_code(d,process) if process else ''
                filename=m._photo_filename(cat,pid,'.jpg',pc);size=(320,240) if i%2==0 else (240,320)
                image=Image.new('RGB',size,(70+(i*13)%110,105+(i*7)%100,130+(i*3)%80));draw=ImageDraw.Draw(image)
                draw.rectangle((12,12,size[0]-12,size[1]-12),outline='white',width=3);draw.text((24,24),f'{code} / {i+1}',fill='white')
                buf=io.BytesIO();image.save(buf,'JPEG',quality=90);raw=buf.getvalue()
                (m._photos_dir(code)/filename).write_bytes(raw);(m._originals_dir(code)/filename).write_bytes(raw);m._ensure_thumbnail(code,filename)
                d['photos'].append({'id':pid,'photo_uuid':f'{code}-uuid-{i}','filename':filename,'original_backup':filename,'original_name':f'{code}-现场{i}.jpg','category':cat,'title':f'现场记录{i+1}','photo_date':'2026-09-14','upload_time':'2026-09-14 08:00:00','uploaded_by':'验收员','photographer':'验收员','description':'原始说明','orientation':'landscape' if i%2==0 else 'portrait','rotation':0,'process_name':process,'process_code':pc})
            m._write_metadata(code,d)
        seed('U-MAIN','底板主测试单元',164);seed('U-DEST','目标墙身单元',2);seed('U-PRINT','打印验收单元',5)
        for i in range(133):seed(f'U-{i+1:04d}','末尾定位单元' if i==132 else f'空单元{i+1}')
        before_hash={x['photo_uuid']:hashlib.sha256((m._originals_dir('U-MAIN')/x['original_backup']).read_bytes()).hexdigest() for x in m.get_photos('U-MAIN')}
        sample=root/'2026-09-14-新增现场.jpg';Image.new('RGB',(320,240),(85,125,150)).save(sample,'JPEG')
        with contextlib.ExitStack() as stack:
            for name,value in [('ensure_photo_optimizer_started',None),('sync_cloud_preview_async',None),('_watermark_meta_for_upload',None),('is_member_user',True)]:
                stack.enter_context(patch.object(a,name,return_value=value))
            service=stack.enter_context(patch.object(a,'desktop_mobile_sync_service'));service.return_value.enqueue_photo_delete.return_value={'ok':True,'queued':True}
            server=make_server('127.0.0.1',0,a.app,threaded=True);threading.Thread(target=server.serve_forever,daemon=True).start();origin=f'http://127.0.0.1:{server.server_port}'
            with sync_playwright() as pw:
                browser=pw.chromium.launch();sizes=[(1600,900),(1366,768),(1280,800),(1600,1000),(1024,768)];w,h=sizes[(args.round-1)%5]
                context=browser.new_context(viewport={'width':w,'height':h},device_scale_factor=1.25 if args.round==4 else 1,accept_downloads=True)
                context.add_init_script("localStorage.setItem('album-guide-login-done','1');localStorage.setItem('album-guide-workspace-v2-done','1');window.print=()=>{window.__printRequested=true;};")
                def routes(route):
                    url=route.request.url
                    if not url.startswith(origin):return route.abort()
                    if '/api/cloud/check-update' in url:return route.fulfill(json={'ok':True,'has_update':False})
                    if '/api/cloud/status' in url:return route.fulfill(json={'ok':True,'logged_in':False,'project_ownership':{'state':'logged_out'}})
                    return route.continue_()
                context.route('**/*',routes)
                response=context.request.post(origin+'/api/auth/login',data={'username':'隔离验收员'});assert response.status==200,response.text()
                page=context.new_page();page.set_default_timeout(15000);errors=[];requests=[];answers=[]
                page.on('pageerror',lambda e:errors.append(str(e)));page.on('request',lambda r:requests.append(r.url))
                page.on('dialog',lambda d:d.accept(answers.pop(0) if answers else 'TestDelete2026!') if d.type=='prompt' else d.accept())
                def check(name):report['checks'].append(name);print('PASS',name,flush=True)
                def ready(code):page.wait_for_function('(code)=>state.selectedCode===code && !!document.querySelector("#photoSectionsHost .photos")',arg=code)
                def editor(index=0):
                    page.locator('#photoSectionsHost [data-edit-photo]').nth(index).click();page.locator('#photoEditModal.open').wait_for()
                def load_all():
                    for _ in range(20):
                        sentinel=page.locator('[data-photo-sentinel]')
                        if not sentinel.count():break
                        sentinel.scroll_into_view_if_needed();page.wait_for_timeout(150)
                try:
                    t=time.perf_counter();page.goto(origin,wait_until='domcontentloaded');page.locator('#constructionModuleGrid [data-part]').first.wait_for();page.wait_for_timeout(1800)
                    report['timings_ms']['workspace_ready']=(time.perf_counter()-t)*1000;check('real authenticated workspace loads')
                    page.locator('#constructionModuleGrid [data-part]').first.click();page.wait_for_function('()=>document.querySelectorAll("#unitRows [data-unit-code]").length===136')
                    page.locator('#unitListSearchInput').fill('末尾定位');assert page.locator('#unitRows [data-unit-code]').count()==1
                    page.locator('#unitListSearchInput').fill('');page.locator('#unitUploadFilter').select_option('uploaded');assert page.locator('#unitRows [data-unit-code]').count()==3
                    page.locator('#unitUploadFilter').select_option('empty');assert page.locator('#unitRows [data-unit-code]').count()==133
                    page.locator('#unitUploadFilter').select_option('all');check('complete search and uploaded/empty filters reach all 136 units')
                    unit_requests=lambda:len([x for x in requests if '/api/units?' in x])
                    nreq=unit_requests();page.locator('[data-unit-code="U-MAIN"]').click();ready('U-MAIN')
                    page.locator('#backPartBtn').click();page.wait_for_function('()=>state.viewMode==="part"');assert unit_requests()==nreq
                    check('return to unchanged part reuses all cached units')
                    page.locator('[data-unit-code="U-MAIN"]').click();ready('U-MAIN')
                    assert page.locator('#unitGalleryCount').inner_text()=='150 张';assert page.evaluate('()=>state.photos.length')==164
                    assert page.locator('#photoSectionsHost .photo').count()<=72;page.screenshot(path=str(out/'gallery-first.png'))
                    check('DOM batches while complete 164 records remain available');load_all();assert page.locator('#photoSectionsHost .photo').count()==150
                    check('scrolling loads the last photo after more than five batches')
                    page.locator('#gallerySelectBtn').click();page.locator('#selectAllCurrentPhotosBtn').click();assert page.locator('#photoSelectionCount').inner_text()=='已选 150 张'
                    page.locator('#printSelectedPhotosBtn').click();page.locator('#printSetupModal.open').wait_for()
                    ids=page.evaluate('()=>new URL(state.printSourceUrl,location.origin).searchParams.get("ids") || ""');assert len(ids.split(','))==150
                    page.screenshot(path=str(out/'print-options.png'));page.locator('#closePrintSetupBtn').click();page.locator('#selectAllCurrentPhotosBtn').click()
                    page.locator('#photoSectionsHost .photo').nth(2).click();page.locator('#photoSectionsHost .photo').nth(130).click(modifiers=['Shift'])
                    assert page.locator('#photoSelectionCount').inner_text()=='已选 129 张';page.locator('#photoSectionsHost .photo').nth(130).press('Space')
                    assert page.locator('#photoSelectionCount').inner_text()=='已选 128 张';page.locator('#cancelPhotoSelectionBtn').click()
                    check('select-all/print include 150 photos; shift and keyboard work across batches')
                    old_order=page.evaluate('()=>activeGalleryPhotos().map(p=>p.photo_uuid)')
                    with page.expect_response(lambda r:'/reorder-list' in r.url and r.request.method=='POST'):
                        page.locator('#photoSectionsHost .photo').nth(130).drag_to(page.locator('#photoSectionsHost .photo').nth(129),target_position={'x':5,'y':5})
                    page.wait_for_function('(old)=>JSON.stringify(activeGalleryPhotos().map(p=>p.photo_uuid))!==JSON.stringify(old)',arg=old_order)
                    order=page.evaluate('()=>activeGalleryPhotos().map(p=>p.photo_uuid)');assert sorted(order)==sorted(old_order)
                    assert page.evaluate('()=>state.photos.filter(p=>p.category==="supervision").length')==6
                    check('appended-photo drag changes saved order without loss or crossing groups');load_all();editor(130)
                    selected_uuid=page.evaluate('()=>currentEditingPhoto().photo_uuid');page.locator('#photoEditTitleInput').fill('已核对的现场记录');page.locator('#photoEditDescriptionInput').fill('五轮验收保存说明')
                    t=time.perf_counter();page.locator('#photoEditForm button[type=submit]').click();page.locator('#photoEditModal.open').wait_for(state='hidden')
                    report['timings_ms']['edit_roundtrip']=(time.perf_counter()-t)*1000
                    assert page.evaluate('(id)=>state.photos.find(p=>p.photo_uuid===id).title',selected_uuid)=='已核对的现场记录';assert page.locator('#photoSectionsHost .photo').count()>130
                    check('late-photo save preserves rendered extent and exact text')
                    page.locator('#unitCategorySupervisionBtn').click();assert page.locator('#unitGalleryCount').inner_text()=='6 张'
                    page.locator('#unitCategoryConstructionBtn').click();page.locator('[data-gallery-process="开挖"]').click();assert page.locator('#unitGalleryCount').inner_text()=='8 张'
                    answers.append('基坑开挖');page.locator('[data-process-rename="开挖"]').click();page.locator('[data-gallery-process="基坑开挖"]').wait_for();assert page.locator('#unitGalleryCount').inner_text()=='8 张'
                    page.locator('#addProcessBtn').click();page.locator('#addProcessNameInput').fill('临时空工序');page.locator('#addProcessForm button[type=submit]').click();page.locator('[data-gallery-process="临时空工序"]').wait_for()
                    page.locator('[data-process-delete="临时空工序"]').click();page.locator('[data-gallery-process="临时空工序"]').wait_for(state='detached')
                    check('category switches and process rename/add/empty-delete preserve counts')
                    n=len(m.get_photos('U-MAIN'));page.locator('[data-process-delete="基坑开挖"]').click();page.wait_for_timeout(300)
                    assert len(m.get_photos('U-MAIN'))==n and page.locator('[data-gallery-process="基坑开挖"]').count()==1
                    check('occupied process deletion is rejected safely')
                    page.locator('[data-gallery-process=""]').click();page.locator('#galleryUploadBtn').click();page.locator('#uploadModalFiles').set_input_files(str(sample))
                    page.locator('#uploadModalForm input[type=date]').fill('2026-09-14');page.locator('#uploadModalForm button[type=submit]').click()
                    page.wait_for_function('(n)=>state.photos.length===n',arg=n+1,timeout=30000)
                    if page.locator('#uploadChoiceModal.open').count():page.locator('#closeUploadChoiceBtn').click()
                    check('real file-input upload saves files and records before completion')
                    page.locator('[data-gallery-process=""]').click();editor();moving=page.evaluate('()=>currentEditingPhoto().photo_uuid')
                    page.locator('#movePhotoBtn').click();page.locator('#photoMoveModal.open').wait_for();page.locator('#photoMoveTargetSelect').select_option('U-MAIN')
                    page.wait_for_function('()=>!document.querySelector("#photoMoveProcessSelect").disabled');page.locator('#photoMoveProcessSelect').select_option('基坑开挖')
                    page.screenshot(path=str(out/'move-dialog.png'));page.locator('#confirmPhotoMoveBtn').click();page.locator('#photoMoveModal.open').wait_for(state='hidden');ready('U-MAIN')
                    assert next(p for p in m.get_photos('U-MAIN') if p['photo_uuid']==moving)['process_name']=='基坑开挖'
                    page.locator('[data-gallery-process="基坑开挖"]').click();pid=next(p for p in m.get_photos('U-MAIN') if p['photo_uuid']==moving)['id']
                    page.locator(f'#photoSectionsHost [data-edit-photo="{pid}"]').click();page.locator('#movePhotoBtn').click();page.locator('#photoMoveModal.open').wait_for()
                    page.locator('#photoMoveTargetSelect').select_option('U-DEST');page.wait_for_function('()=>!document.querySelector("#photoMoveProcessSelect").disabled')
                    page.locator('#photoMoveProcessSelect').select_option('验收');page.locator('#confirmPhotoMoveBtn').click();page.locator('#photoMoveModal.open').wait_for(state='hidden');ready('U-MAIN')
                    moved=next(p for p in m.get_photos('U-DEST') if p['photo_uuid']==moving);assert moved['process_name']=='验收'
                    assert hashlib.sha256((m._originals_dir('U-DEST')/moved['original_backup']).read_bytes()).hexdigest()==before_hash[moving]
                    check('same-unit and cross-unit moves preserve UUID and original image hash')
                    page.locator('[data-gallery-process=""]').click();page.locator('#gallerySelectBtn').click();page.locator('#photoSectionsHost .photo').nth(0).click();page.locator('#photoSectionsHost .photo').nth(1).click()
                    deleted=page.evaluate('()=>activeGalleryPhotos().filter(p=>state.selectedPrintPhotos[printSelectionKey(p.category,p.id)]).map(p=>p.photo_uuid)');before=[p['photo_uuid'] for p in m.get_photos('U-MAIN')]
                    page.locator('#deleteSelectedCurrentPhotosBtn').click();page.wait_for_function('()=>!state.photoSelectionMode')
                    assert set(before)-{p['photo_uuid'] for p in m.get_photos('U-MAIN')}==set(deleted);check('bulk-delete removes exactly selected UUIDs after renumbering')
                    def delay(route):time.sleep(.25);route.continue_()
                    page.route('**/api/photos/U-MAIN',delay);page.evaluate('()=>{loadProject("U-MAIN");openOverview();}');page.wait_for_timeout(500)
                    assert page.evaluate('()=>state.viewMode')=='overview';page.unroute('**/api/photos/U-MAIN',delay);check('late responses cannot override navigation intent')
                    pp=context.new_page();pp.on('pageerror',lambda e:errors.append(str(e)))
                    for layout in ('portrait','landscape'):
                        for style,count in [('one',1),('two',2),('four',4),('custom',5)]:
                            for mode in ('inline','separate'):
                                key=f'{style}-{layout}-{mode}';query=urlencode({'style':style,'layout':layout,'page_size':count,'caption_mode':mode,'auto_fill':1,'caption_position':'bottom'})
                                resp=pp.goto(origin+'/print/construction/U-PRINT?'+query,wait_until='networkidle');assert resp.status==200
                                pp.emulate_media(media='print');pp.wait_for_function('()=>Array.from(document.images).every(i=>i.complete&&i.naturalWidth>0)')
                                geom=pp.evaluate('''()=>{let issues=[];for(const p of document.querySelectorAll('.page')){let pr=p.getBoundingClientRect();for(const el of p.querySelectorAll('.photo-item')){let r=el.getBoundingClientRect();if(r.left<pr.left-1||r.top<pr.top-1||r.right>pr.right+1||r.bottom>pr.bottom+1)issues.push('outside-page');}}return {pages:document.querySelectorAll('.page').length,photos:document.querySelectorAll('.photo-item').length,inline:document.querySelectorAll('.photo-caption').length,labels:document.querySelectorAll('.caption-sheet').length,issues};}''')
                                assert geom['issues']==[],(key,geom);assert geom['photos']==5,(key,geom)
                                assert (geom['labels']>0 and geom['inline']==0) if mode=='separate' else geom['inline']==5,(key,geom)
                                pdf=pp.pdf(prefer_css_page_size=True,print_background=True)
                                with fitz.open(stream=pdf,filetype='pdf') as doc:
                                    assert len(doc)==geom['pages'],(key,len(doc),geom)
                                    doc[0].get_pixmap(matrix=fitz.Matrix(.7,.7)).save(out/(key+'.png'))
                                    if mode=='separate':doc[-1].get_pixmap(matrix=fitz.Matrix(.7,.7)).save(out/(key+'-labels.png'))
                                (out/(key+'.pdf')).write_bytes(pdf);report['print_variants'].append({'variant':key,**geom})
                    pp.close();check('16 print modes: both orientations, 1/2/4/custom, inline/separate; no PDF spill pages')
                    for code in ('U-MAIN','U-DEST'):
                        for p in m.get_photos(code):
                            if p['photo_uuid'] in before_hash:
                                assert hashlib.sha256((m._originals_dir(code)/p['original_backup']).read_bytes()).hexdigest()==before_hash[p['photo_uuid']]
                    assert not errors,errors;check('all retained originals unchanged; no uncaught browser errors')
                    report.update(status='passed',browser=browser.version,viewport={'width':w,'height':h},uncaught_errors=errors)
                except Exception:
                    report.update(status='failed',error=traceback.format_exc(),uncaught_errors=errors)
                    with contextlib.suppress(Exception):page.screenshot(path=str(out/'failure.png'))
                    raise
                finally:
                    (out/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');browser.close();server.shutdown()
    print(json.dumps(report,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
