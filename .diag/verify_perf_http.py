"""Isolated full-Flask timing and print HTML equivalence; synthetic files only."""
from pathlib import Path
import ast, base64, hashlib, io, json, os, shutil, statistics, sys, tempfile, time
from unittest.mock import patch
R=Path.cwd(); out=R/'perf-artifacts'; out.mkdir(exist_ok=True)
sys.path.insert(0,str(R))
temp=tempfile.TemporaryDirectory(prefix='album-http-perf-')
os.environ['ALBUM_DATA_DIR']=str(Path(temp.name)/'desktop')
os.environ['ALBUM_SERVER_DATA']=str(Path(temp.name)/'server')
os.environ['ALBUM_SERVER_DB']=str(Path(temp.name)/'server/server.db')
import app
from PIL import Image
from werkzeug.datastructures import FileStorage
base_text=(R/'.diag/perf-base-app.py').read_text(encoding='utf-8')
base_class=next(n for n in ast.parse(base_text).body if isinstance(n,ast.ClassDef) and n.name=='AlbumManager')
namespace=dict(app.__dict__)
exec(compile(ast.Module(body=[base_class],type_ignores=[]),'<baseline-manager>','exec'),namespace)
Base=namespace['AlbumManager']
before=Base(Path(temp.name)/'baseline')
buf=io.BytesIO(); Image.new('RGB',(320,200),(75,120,135)).save(buf,'JPEG'); image=buf.getvalue()
with patch.object(app,'manager',before):
 before.create_project('PERF','底板性能验证单元')
 files=[FileStorage(stream=io.BytesIO(image),filename=f'照片{i}.jpg') for i in range(120)]
 before.add_photos('PERF',files,photo_date='2026-09-01',title='底板照片',photographer='性能测试')
shutil.copytree(before.root,Path(temp.name)/'candidate')
after=app.AlbumManager(Path(temp.name)/'candidate')
client=app.app.test_client()
with client.session_transaction() as s:s['username']='性能验证'
def hashes(m):
 return {str(p.relative_to(m.root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in m.root.rglob('*.jpg')}
original_before=hashes(before); original_after=hashes(after)
timings={}; pid=before.get_photos('PERF')[0]['id']
for label,m in [('baseline',before),('updated',after)]:
 times=[]
 with patch.object(app,'manager',m):
  for i in range(24):
   start=time.perf_counter()
   resp=client.patch(f'/api/photos/PERF/{pid}',json={'title':f'编辑{i}','photo_date':'2026-09-01','photographer':'性能验证','description':f'说明{i}','process_name':'','orientation':'landscape','rotation':0})
   elapsed=(time.perf_counter()-start)*1000
   assert resp.status_code==200,(label,resp.status_code,resp.get_data(as_text=True)[:300])
   assert len(resp.get_json()['photos'])==120
   times.append(elapsed)
 ys=sorted(times)
 timings[label]={'p50_ms':round(statistics.median(times),3),'p95_ms':round(ys[-2],3),'samples':len(times)}
assert before.get_project('PERF')==after.get_project('PERF')
assert original_before==hashes(before) and original_after==hashes(after)
with patch.object(app,'manager',after):
 after.create_project('PRINT','打印验证单元')
 files=[]
 for i in range(4):
  mem=io.BytesIO(); Image.new('RGB',(320 if i%2==0 else 200,200 if i%2==0 else 320),(65+i*35,100,130)).save(mem,'JPEG')
  files.append(FileStorage(stream=io.BytesIO(mem.getvalue()),filename=f'校核{i}.jpg'))
 after.add_photos('PRINT',files,photo_date='2026-09-01',title='打印校核照片',photographer='测试')
shutil.copytree(after._project_dir('PRINT'),before._project_dir('PRINT'))
variants=[]
with patch.object(app,'is_member_user',return_value=True),patch.object(app,'app_license_status',return_value={'upload_locked':False}):
 for style in ['one','two','four','custom']:
  for layout in ['portrait','landscape']:
   for mode in ['inline','separate']:
    name=f'{style}-{layout}-{mode}'
    url=f'/print/construction/PRINT?style={style}&layout={layout}&caption_mode={mode}&auto_fill=1&page_size=3&photo_preset=custom&photo_width_cm=1&photo_height_cm=1&caption_position=bottom&caption_fields=title,id,part_name,photo_date,photographer'
    with patch.object(app,'manager',before):r1=client.get(url)
    with patch.object(app,'manager',after):r2=client.get(url)
    assert r1.status_code==200 and r2.status_code==200,(name,r1.status_code,r2.status_code)
    h1=r1.get_data(as_text=True);h2=r2.get_data(as_text=True)
    assert h1==h2, f'Print HTML changed: {name}'
    import re, urllib.parse
    def embed(match):
     url=match.group(2)
     if url.startswith('/photos/'):
      fname=urllib.parse.unquote(urllib.parse.urlsplit(url).path.split('/')[-1])
      payload=(after._photos_dir('PRINT')/fname).read_bytes()
      url='data:image/jpeg;base64,'+base64.b64encode(payload).decode()
     return match.group(1)+url+match.group(3)
    html=re.sub(r'(<img\b[^>]*\bsrc=")([^"]*)(")',embed,h2)
    (out/(name+'.html')).write_text(html,encoding='utf-8')
    variants.append(name)
with patch.object(app,'is_member_user',return_value=False),patch.object(app.cloud_client,'product_config',return_value={'free':{'batch_print_enabled':False}}):
 assert app.batch_print_permission_response()[1]==403
result={'scope':'Isolated Windows full Flask test-client requests with synthetic 120-photo unit; not production PC timings',
        'http_edit_ms':timings,'persisted_metadata_equal':True,'original_and_daily_image_hashes_unchanged':True,
        'print_html_identical_variants':variants,'free_batch_denial_retained':True}
(out/'http-and-print.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(result,ensure_ascii=False,indent=2))
temp.cleanup()
