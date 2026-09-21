#!/usr/bin/env python3
"""Prepare a portable SQLite backup plus its bundled local catalogue assets.

This utility is intentionally dependency-light so it can be run against a backup
file before deployment. It assigns every product a deterministic same-origin image
URL and creates the matching WEBP asset under static/catalogue/products/.
"""
from __future__ import annotations
import json, re, sqlite3, uuid, hashlib, sys
from io import BytesIO
from pathlib import Path
from datetime import datetime, timezone
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ROOT / 'data' / 'catalogue_image_sources.json'
ASSET_ROOT = ROOT / 'static' / 'catalogue' / 'products'
MANIFEST = ROOT / 'static' / 'catalogue' / 'catalogue-image-manifest.json'
PREFIX = '/static/catalogue/products/'

PALETTES = [
    ((248,249,247),(32,89,71),(232,241,237)),
    ((247,248,252),(68,73,133),(237,237,248)),
    ((250,247,246),(132,67,46),(244,235,231)),
    ((248,249,246),(105,91,39),(241,239,224)),
    ((247,249,251),(56,89,121),(231,239,247)),
]

def font(size, bold=False):
    for p in [
        '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf' if bold else '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
        '/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf' if bold else '/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf',
    ]:
        try: return ImageFont.truetype(p,size)
        except Exception: pass
    return ImageFont.load_default()

def wrap(text, width=24, max_lines=3):
    words=re.sub(r'\s+',' ',str(text or '')).strip().split(); lines=[]; line=''
    for w in words:
        c=f'{line} {w}'.strip()
        if line and len(c)>width: lines.append(line); line=w
        else: line=c
    if line: lines.append(line)
    if len(lines)>max_lines:
        lines=lines[:max_lines]; lines[-1]=lines[-1][:max(1,width-1)]+'…'
    return lines

def asset_bytes(name, brand, pack, category):
    seed=f'{brand}|{name}|{category}'.encode(); d=hashlib.sha1(seed).digest(); bg,ink,panel=PALETTES[d[0]%len(PALETTES)]
    im=Image.new('RGB',(800,800),bg); dr=ImageDraw.Draw(im)
    dr.rounded_rectangle((28,28,772,772),radius=44,fill=(255,255,255),outline=panel,width=4)
    dr.ellipse((615,70,730,185),fill=panel); dr.ellipse((72,600,225,753),fill=panel)
    # Neutral product silhouette: deliberately not a fake brand photo.
    dr.rounded_rectangle((292,188,508,554),radius=36,fill=ink)
    dr.rounded_rectangle((324,145,476,222),radius=25,fill=ink)
    dr.rounded_rectangle((326,313,474,470),radius=18,fill=(255,255,255))
    dr.rounded_rectangle((347,350,453,388),radius=16,fill=panel)
    dr.rounded_rectangle((347,405,429,438),radius=16,fill=panel)
    dr.text((400,84),re.sub(r'\s+',' ',str(brand or 'DENMART')).upper()[:30],anchor='ma',fill=ink,font=font(22,True))
    y=614
    for line in wrap(name): dr.text((400,y),line,anchor='ma',fill=(34,45,44),font=font(25,True)); y+=31
    pack=str(pack or category or '').strip().upper()[:34]
    if pack: dr.text((400,748),pack,anchor='ma',fill=(108,122,119),font=font(18,True))
    out=BytesIO(); im.save(out,'WEBP',quality=88,method=6); return out.getvalue()

def read_sources():
    try: p=json.loads(SOURCES.read_text(encoding='utf-8'))
    except Exception: return {},{}
    return p.get('by_product_id',{}),p.get('by_barcode',{})

def main():
    if len(sys.argv)!=2: raise SystemExit('Usage: python scripts/cache_sqlite_backup.py /path/to/backup.sqlite')
    dbpath=Path(sys.argv[1]);
    if not dbpath.exists(): raise SystemExit(f'Backup not found: {dbpath}')
    ASSET_ROOT.mkdir(parents=True,exist_ok=True); MANIFEST.parent.mkdir(parents=True,exist_ok=True)
    byid,bybarcode=read_sources()
    con=sqlite3.connect(dbpath); con.row_factory=sqlite3.Row
    products=con.execute('select * from products order by name').fetchall()
    manifest={'version':'2026-09-21-local-v1','image_prefix':PREFIX,'products':{}}
    stats={'total':len(products),'generated':0,'preserved_source_urls':0,'product_images_upserted':0}
    now=datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
    for p in products:
        pid=p['id']; filename=f"{re.sub(r'[^A-Za-z0-9_-]','',pid)}.webp"; dest=ASSET_ROOT/filename; url=PREFIX+filename
        if not dest.exists() or dest.stat().st_size==0:
            category=''
            if p['category_id']:
                r=con.execute('select name from categories where id=?',(p['category_id'],)).fetchone(); category=r['name'] if r else ''
            dest.write_bytes(asset_bytes(p['name'],p['brand'],p['pack_size'] or p['unit'],category)); stats['generated']+=1
        source=(p['image_url'] or '').strip()
        if not source.startswith(('http://','https://','data:image/')):
            source=byid.get(pid,'') or bybarcode.get(str(p['barcode'] or ''),'')
        if source.startswith(('http://','https://')): stats['preserved_source_urls']+=1
        con.execute('update products set image_url=?, updated_at=? where id=?',(url,now,pid))
        # Make the local URL the single canonical image reference.
        con.execute('delete from product_images where product_id=?',(pid,))
        existing=None
        lic='Generated from the exact product name/brand identity; not a photograph.'
        st='LOCAL_GENERATED'
        if source.startswith(('http://','https://')):
            lic=f'Build-time source recorded for local caching: {source} · Exact-source rights should be retained/verified for commercial use.'
            st='LOCAL_CACHE_SOURCE_PENDING'
        if existing:
            con.execute('update product_images set thumbnail_url=?,alt_text=?,source_type=?,license_info=?,sort_order=0,is_primary=1 where id=?',(url,p['name'],st,lic,existing['id']))
        else:
            con.execute('insert into product_images (id,product_id,image_url,thumbnail_url,alt_text,source_type,license_info,sort_order,is_primary,created_at) values (?,?,?,?,?,?,?,?,?,?)',
                         (str(uuid.uuid4()),pid,url,url,p['name'],st,lic,0,1,now))
        stats['product_images_upserted']+=1
        manifest['products'][pid]={'name':p['name'],'brand':p['brand'] or '', 'barcode':p['barcode'] or '', 'url':url,'file':filename,
                                   'type':'generated','source_url':source if source.startswith(('http://','https://')) else ''}
    con.commit(); con.execute('pragma foreign_keys=on'); con.execute('pragma integrity_check').fetchone(); con.commit(); con.close()
    MANIFEST.write_text(json.dumps(manifest,indent=2,ensure_ascii=False),encoding='utf-8')
    print(json.dumps(stats,indent=2))

if __name__=='__main__': main()
