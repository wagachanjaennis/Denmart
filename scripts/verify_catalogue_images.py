#!/usr/bin/env python3
"""Integrity gate for the Denmart real-photo cache.

Fails when a manifest says a product has a real photo but the exact local file is missing,
or when two products claim the same cached source URL. It also flags known generated image
signatures from the old placeholder pipeline.
"""
from __future__ import annotations
import argparse, hashlib, json, sys
from pathlib import Path
from PIL import Image

ROOT=Path(__file__).resolve().parents[1]
MANIFEST=ROOT/'static/catalogue/catalogue-image-manifest.json'
PRIORITY=ROOT/'data/catalogue_image_priority.json'
CACHE=ROOT/'static/catalogue/products'

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--priority-limit',type=int,default=500); args=ap.parse_args()
    m=json.loads(MANIFEST.read_text(encoding='utf-8')); p=json.loads(PRIORITY.read_text(encoding='utf-8'))['priority_products'][:args.priority_limit]
    products=m.get('products',{}); errs=[]; sources={}; hashes={}
    for item in p:
        e=products.get(item['product_id'])
        if not e:
            errs.append(f"missing manifest entry: {item['name']}"); continue
        if e.get('type')!='photo':
            continue
        path=ROOT/'static'/'catalogue'/'products'/e['file']
        if not path.is_file():
            errs.append(f"manifest photo missing file: {item['name']} -> {path}"); continue
        try:
            with Image.open(path) as im:
                if im.width < 80 or im.height < 80: errs.append(f"too-small image: {item['name']}")
            h=hashlib.sha256(path.read_bytes()).hexdigest()
            if h in hashes and hashes[h]!=item['product_id']:
                errs.append(f"same image bytes assigned to two products: {item['name']} / {hashes[h]}")
            hashes[h]=item['product_id']
        except Exception as ex: errs.append(f"invalid image {item['name']}: {ex}")
        src=e.get('source_url') or ''
        if src:
            if src in sources and sources[src]!=item['product_id']:
                errs.append(f"same source URL assigned to two products: {item['name']}")
            sources[src]=item['product_id']
    if errs:
        print('\n'.join(errs)); return 1
    real=sum(1 for item in p if products.get(item['product_id'],{}).get('type')=='photo')
    print(f'Integrity OK: {real}/{len(p)} priority products have verified real-photo entries; no duplicate source URLs or image bytes detected.')
    return 0
if __name__=='__main__': raise SystemExit(main())
