import hashlib, json, os
from pathlib import Path

ROOTS = [
    Path(r"D:\工程影像资料\albums"),
    Path(os.environ.get("ALBUM_DATA_DIR", "")) / "albums" if os.environ.get("ALBUM_DATA_DIR") else Path("__missing__"),
]
UNIT = "YNLQ-2024-SG-1-01-001"

def sha(path):
    h=hashlib.sha256()
    with open(path,'rb') as f:
        for chunk in iter(lambda:f.read(1024*1024), b''):
            h.update(chunk)
    return h.hexdigest()

def ahash(path):
    try:
        from PIL import Image, ImageOps
        with Image.open(path) as im:
            im=ImageOps.exif_transpose(im).convert('L').resize((8,8))
            px=list(im.getdata()); avg=sum(px)/len(px)
            bits=''.join('1' if p>=avg else '0' for p in px)
            return f"{int(bits,2):016x}"
    except Exception as exc:
        return f"ERR:{type(exc).__name__}"

seen=set()
for root in ROOTS:
    try: key=str(root.resolve()).lower()
    except Exception: key=str(root).lower()
    if key in seen or not root.is_dir(): continue
    seen.add(key)
    unit=root/UNIT
    meta=unit/'metadata.json'
    if not meta.is_file():
        print('ROOT_NO_UNIT='+str(root)); continue
    data=json.loads(meta.read_text(encoding='utf-8-sig'))
    print('ROOT='+str(root))
    print('PROJECT_NAME='+str(data.get('project_name') or ''))
    photos=data.get('photos') or []
    print('PHOTO_COUNT='+str(len(photos)))
    for p in photos:
        if str(p.get('id') or '').upper().endswith('SY001') or 'Q21' in str(p.get('title') or ''):
            print('META='+json.dumps({k:p.get(k) for k in ['id','photo_uuid','filename','title','photo_date','process_name','original_name','original_backup','capture_source','mobile_original_name','mobile_original_size_bytes','sha256','stored_bytes','upload_time']}, ensure_ascii=True))
            fn=Path(str(p.get('filename') or '')).name
            if fn:
                f=unit/'photos'/fn
                t=unit/'photos'/('thumb_'+Path(fn).stem+'.webp')
                for label,path in [('FILE',f),('THUMB',t)]:
                    if path.is_file(): print(f"{label}="+json.dumps({'path':str(path),'size':path.stat().st_size,'mtime_ns':path.stat().st_mtime_ns,'sha256':sha(path),'ahash':ahash(path)},ensure_ascii=True))
                    else: print(f"{label}_MISSING={path}")
    candidates=[]
    for sub in ['_originals','_mobile_sync_backups','photos']:
        base=unit/sub
        if not base.is_dir(): continue
        for f in base.rglob('*'):
            if f.is_file() and f.suffix.lower() in {'.jpg','.jpeg','.png','.webp'}:
                try:
                    candidates.append({'sub':sub,'name':f.name,'size':f.stat().st_size,'mtime_ns':f.stat().st_mtime_ns,'sha256':sha(f),'ahash':ahash(f)})
                except Exception as exc:
                    candidates.append({'sub':sub,'name':f.name,'error':type(exc).__name__})
    print('CANDIDATES='+json.dumps(candidates,ensure_ascii=True))
