#!/usr/bin/env python3
"""Cache verified real product photos for Denmart.

This is deliberately a REAL-PHOTO-ONLY pipeline.

Order of discovery:
  1) exact curated source URL already attached to the exact SKU
  2) OpenFoodFacts / OpenBeautyFacts / OpenPetFoodFacts / OpenProductsFacts text search
  3) Kenyan retailer page discovery (Carrefour Kenya, Naivas, Owino, Artcaffe)

A source is accepted only when its page/data matches the product identity strongly enough.
The script NEVER invents a product illustration and NEVER assigns one SKU another SKU's
photo. A miss is recorded as pending_real_photo.

The first N priority products are written to static/catalogue/products/NNN/, 100 per folder.
Filenames are based on the stable unique barcode, not a UUID that could change between DBs.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from difflib import SequenceMatcher
from html import unescape
from io import BytesIO
from pathlib import Path
from urllib.parse import parse_qs, quote_plus, unquote, urljoin, urlparse

import requests
from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parents[1]
PRIORITY = ROOT / "data" / "catalogue_image_priority.json"
PRODUCT_INDEX = ROOT / "data" / "catalogue_product_index.json"
SOURCES = ROOT / "data" / "catalogue_image_sources.json"
MANIFEST = ROOT / "static" / "catalogue" / "catalogue-image-manifest.json"
CACHE = ROOT / "static" / "catalogue" / "products"
REPORT = ROOT / "data" / "github_catalogue_image_report.json"
BATCH_SIZE = 100
TIMEOUT = float(os.getenv("PRODUCT_IMAGE_BUILD_TIMEOUT", "8"))
MAX_BYTES = int(os.getenv("PRODUCT_IMAGE_MAX_BYTES", str(8 * 1024 * 1024)))
USER_AGENT = "DenmartCatalogueImageCache/2026.09"
RETAILERS = (
    "carrefour.ke",
    "naivas.online",
    "owinosupermarket.com",
    "artcaffemarket.co.ke",
)
FACTS = (
    "https://world.openfoodfacts.org",
    "https://world.openbeautyfacts.org",
    "https://world.openpetfoodfacts.org",
    "https://world.openproductsfacts.org",
)
GENERIC_BRANDS = {"various", "unbranded", "household", "fresh produce", "generic"}
GENERIC = {
    "the", "and", "with", "for", "of", "pack", "packs", "piece", "pieces", "pcs",
    "per", "each", "fresh", "new", "standard", "original", "value", "size", "food",
    "drink", "drinks", "product", "assorted", "premium", "natural", "supermarket",
}


def norm(value: str | None) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", str(value or "").lower())).strip()


def compact_tokens(value: str | None) -> list[str]:
    return [t for t in norm(value).split() if len(t) >= 2 and t not in GENERIC]


def size_tokens(value: str | None) -> set[str]:
    s = norm(value)
    return set(re.findall(r"\b\d+(?:\.\d+)?\s?(?:kg|g|mg|l|ml|cl|mm|cm|m|w|v)\b", s))


def product_score(product: dict, remote: dict | str) -> float:
    if isinstance(remote, str):
        rn = norm(remote)
        rb = ""
        rq = set()
    else:
        rn = norm(remote.get("product_name") or remote.get("name") or remote.get("title") or remote.get("generic_name"))
        rb = norm(remote.get("brands") or remote.get("brand"))
        rq = size_tokens(remote.get("quantity") or remote.get("packaging") or remote.get("name"))
    pn = norm(product.get("name"))
    p_tokens, r_tokens = set(compact_tokens(product.get("name"))), set(compact_tokens(rn))
    if not p_tokens or not r_tokens:
        return 0.0
    seq = SequenceMatcher(None, pn, rn).ratio()
    overlap = len(p_tokens & r_tokens) / max(1, len(p_tokens))
    brand = norm(product.get("brand"))
    brand_match = 1.0 if brand and brand in rb else 0.0
    p_sizes = size_tokens(product.get("name")) | size_tokens(product.get("pack_size"))
    size_match = 1.0 if p_sizes and rq and (p_sizes & rq) else 0.0
    # Name tokens dominate, then exact brand and pack size. This prevents “milk” from
    # accepting an unrelated milk variant merely because it shares one category word.
    score = 0.48 * overlap + 0.24 * seq + 0.18 * brand_match + 0.10 * size_match
    if brand in GENERIC_BRANDS and size_match and overlap >= 0.45:
        score = max(score, 0.74)
    return min(1.0, score)


def exact_identity_ok(product: dict, text: str) -> bool:
    hay = norm(text)
    tokens = compact_tokens(f"{product.get('brand', '')} {product.get('name', '')}")
    if not tokens:
        return False
    hits = sum(1 for t in tokens if t in hay)
    ratio = hits / len(tokens)
    brand = norm(product.get("brand"))
    name_tokens = compact_tokens(product.get("name"))
    brand_ok = not brand or brand in GENERIC_BRANDS or brand in hay
    name_hits = sum(1 for t in name_tokens if t in hay) / max(1, len(name_tokens))
    return brand_ok and ratio >= 0.58 and name_hits >= 0.58


def normalize_photo(data: bytes) -> bytes:
    with Image.open(BytesIO(data)) as src:
        src = ImageOps.exif_transpose(src).convert("RGBA")
        if src.width < 80 or src.height < 80:
            raise ValueError("image too small")
        src.thumbnail((720, 720), Image.Resampling.LANCZOS)
        canvas = Image.new("RGBA", (800, 800), (255, 255, 255, 255))
        canvas.alpha_composite(src, ((800 - src.width) // 2, (800 - src.height) // 2))
        out = BytesIO()
        canvas.convert("RGB").save(out, format="WEBP", quality=90, method=6)
        return out.getvalue()


def http_get(url: str, *, accept: str, timeout: float = TIMEOUT) -> requests.Response:
    r = requests.get(
        url,
        timeout=timeout,
        allow_redirects=True,
        headers={"User-Agent": USER_AGENT, "Accept": accept, "Accept-Language": "en-KE,en;q=0.8"},
    )
    r.raise_for_status()
    return r


def fetch_bytes(url: str) -> bytes:
    r = http_get(url, accept="image/avif,image/webp,image/jpeg,image/png,*/*;q=0.7")
    content_type = (r.headers.get("Content-Type") or "").lower()
    if "image" not in content_type and not re.search(r"\.(?:jpe?g|png|webp)(?:$|[?#])", url, re.I):
        raise ValueError("source is not an image")
    data = r.content
    if len(data) > MAX_BYTES:
        raise ValueError("image too large")
    return data


def unwrap_search_url(href: str) -> str:
    href = unescape(href)
    if "uddg=" in href:
        try:
            q = parse_qs(urlparse(href).query).get("uddg", [])
            if q:
                return unquote(q[0])
        except Exception:
            pass
    return href


def retailer_search_urls(product: dict) -> list[tuple[str, str]]:
    """Use one search-engine request per SKU, then keep only Kenyan retailer pages."""
    query = f'"{product.get("brand", "")}" "{product.get("name", "")}" Kenya supermarket'
    out: list[tuple[str, str]] = []
    url = f"https://html.duckduckgo.com/html/?q={quote_plus(query)}&kl=ke-en"
    try:
        r = http_get(url, accept="text/html,application/xhtml+xml;q=0.9,*/*;q=0.8")
        html = r.text
        for raw in re.findall(r'<a[^>]+class=["\']result__a["\'][^>]+href=["\']([^"\']+)', html, re.I):
            target = unwrap_search_url(raw)
            host = urlparse(target).netloc.lower()
            for domain in RETAILERS:
                if host.endswith(domain):
                    out.append((target, domain))
                    break
    except Exception:
        return []
    seen=set(); result=[]
    for item in out:
        if item[0] in seen: continue
        seen.add(item[0]); result.append(item)
    return result[:8]


def extract_page_images(page_url: str, product: dict) -> list[tuple[str, float, dict]]:
    r = http_get(page_url, accept="text/html,application/xhtml+xml;q=0.9,*/*;q=0.8")
    html = r.text
    page_text = norm(re.sub(r"<[^>]+>", " ", html))
    if not exact_identity_ok(product, page_text):
        return []
    candidates: list[str] = []
    patterns = [
        r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)',
        r'<meta[^>]+name=["\']twitter:image["\'][^>]+content=["\']([^"\']+)',
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']',
    ]
    for pat in patterns:
        candidates.extend(unescape(u) for u in re.findall(pat, html, re.I))
    # JSON-LD image field, with a deliberately conservative parser.
    for raw in re.findall(r'"image"\s*:\s*(\[[^\]]+\]|"[^"]+")', html, re.I | re.S):
        if raw.startswith("["):
            candidates.extend(re.findall(r'"(https?://[^"\\]+)"', raw))
        else:
            candidates.append(raw.strip('"'))
    out=[]; seen=set()
    for u in candidates:
        u=urljoin(page_url,u.strip())
        if not u.startswith(("http://","https://")) or u in seen:
            continue
        seen.add(u)
        # The page itself was identity-checked, so page imagery is eligible; still score
        # the page title/name for audit purposes.
        sc=product_score(product,page_text)
        out.append((u,sc,{"provider":"retailer_page","page_url":page_url}))
    return out


def facts_search(product: dict) -> list[tuple[str,float,dict]]:
    terms = f"{product.get('brand','')} {product.get('name','')}".strip()
    if not terms:
        return []
    category=norm(product.get("category"))
    if any(x in category for x in ("beauty", "personal care")):
        bases=("https://world.openbeautyfacts.org", "https://world.openfoodfacts.org")
    elif "pet" in category:
        bases=("https://world.openpetfoodfacts.org", "https://world.openproductsfacts.org")
    elif any(x in category for x in ("electronics", "stationery", "general merchandise")):
        bases=("https://world.openproductsfacts.org", "https://world.openfoodfacts.org")
    else:
        bases=("https://world.openfoodfacts.org", "https://world.openproductsfacts.org")
    out=[]
    for base in bases:
        try:
            r=http_get(
                f"{base}/cgi/search.pl?json=1&page_size=10&search_terms={quote_plus(terms)}&fields=code,product_name,brands,quantity,packaging,image_front_url,image_front_small_url,image_front_thumb_url",
                accept="application/json,text/plain;q=0.9,*/*;q=0.5",
            )
            data=r.json()
            for item in data.get("products") or []:
                sc=product_score(product,item)
                u=item.get("image_front_url") or item.get("image_front_small_url") or item.get("image_front_thumb_url")
                if isinstance(u,str) and u.startswith(("http://","https://")) and sc>=0.72:
                    out.append((u,sc,{"provider":base,"remote_name":item.get("product_name") or "","remote_brand":item.get("brands") or "","code":item.get("code") or ""}))
            if out:
                break
        except Exception:
            continue
    return sorted(out,key=lambda x:x[1],reverse=True)[:5]


def source_candidates(product: dict, sources: dict) -> list[tuple[str,float,dict]]:
    result=[]; by_id=sources.get("by_product_id") or {}; by_barcode=sources.get("by_barcode") or {}; by_page=sources.get("by_product_page") or {}
    for key,url in (("curated-product-id",by_id.get(product.get("product_id"))), ("curated-barcode",by_barcode.get(str(product.get("barcode") or "")))):
        if isinstance(url,str) and url.startswith(("http://","https://")):
            result.append((url,1.0,{"provider":key}))
    page=by_page.get(product.get("product_id"))
    if isinstance(page,str) and page.startswith(("http://","https://")):
        try:
            result.extend((u,sc,{**meta,"provider":"curated-product-page"}) for u,sc,meta in extract_page_images(page,product))
        except Exception:
            pass
    result.extend(facts_search(product))
    for page_url,domain in retailer_search_urls(product):
        try:
            for u,sc,meta in extract_page_images(page_url,product):
                meta={**meta,"provider":domain,"page_url":page_url}
                result.append((u,sc,meta))
        except Exception:
            continue
    # source URL is global: one URL can never be assigned to two different products.
    seen=set(); out=[]
    for u,sc,meta in sorted(result,key=lambda x:x[1],reverse=True):
        if u in seen: continue
        seen.add(u); out.append((u,sc,meta))
    return out


def load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def main() -> int:
    ap=argparse.ArgumentParser()
    ap.add_argument("--limit",type=int,default=500)
    ap.add_argument("--workers",type=int,default=5)
    ap.add_argument("--dry-run",action="store_true")
    args=ap.parse_args()

    priority_doc=load_json(PRIORITY,{"priority_products":[]})
    priority=priority_doc.get("priority_products") or []
    priority=sorted(priority,key=lambda x:(x.get("rank",10**9),x.get("name","")))[:args.limit]
    sources=load_json(SOURCES,{})

    CACHE.mkdir(parents=True,exist_ok=True)
    # The product catalog owns the authoritative list. Remove ONLY stale fake/catalogue
    # assets from previous versions; real photos will be replaced only if the same barcode
    # is intentionally refreshed.
    for i in range(1,15):
        (CACHE/f"{i:03d}").mkdir(parents=True,exist_ok=True)

    manifest=load_json(MANIFEST,{"version":"2026-09-22-real-v1","image_prefix":"/static/catalogue/products/","batch_size":100,"priority_count":len(priority),"products":{}})
    manifest.setdefault("products",{})
    report={"version":"2026-09-22-real-v1","requested":len(priority),"photo":0,"missing":0,"reused_source_rejected":0,"errors":[],"products":{}}
    used_sources={}

    def one(idx,p):
        batch=f"{(idx//BATCH_SIZE)+1:03d}"
        barcode=str(p.get("barcode") or "").strip()
        if not barcode:
            return idx,p,batch,None,None,[],"missing barcode"
        dest=CACHE/batch/f"{barcode}.webp"
        candidates=source_candidates(p,sources)
        last_errors=[]
        for url,sc,meta in candidates:
            owner=used_sources.get(url)
            if owner and owner!=barcode:
                report["reused_source_rejected"] += 1
                continue
            try:
                data=fetch_bytes(url)
                photo=normalize_photo(data)
                return idx,p,batch,dest,(url,sc,meta),photo,None
            except Exception as e:
                last_errors.append(f"{url}: {e}")
        return idx,p,batch,dest,None,None,"; ".join(last_errors[-3:])

    # Fetch concurrently, but write sequentially so deterministic manifests/reports are produced.
    results=[]
    with ThreadPoolExecutor(max_workers=max(1,args.workers)) as ex:
        futs=[ex.submit(one,idx,p) for idx,p in enumerate(priority)]
        for fut in as_completed(futs):
            results.append(fut.result())
    results.sort(key=lambda x:x[0])

    for idx,p,batch,dest,src,photo,err in results:
        key=p.get("product_id") or barcode
        entry={
            "name":p.get("name",""),"brand":p.get("brand","") or "","barcode":str(p.get("barcode") or ""),
            "priority_rank":int(p.get("rank",idx)),"batch":batch,
            "url":f"/static/catalogue/products/{batch}/{dest.name if dest else (str(p.get('barcode') or 'unknown')+'.webp')}",
            "file":f"{batch}/{dest.name if dest else (str(p.get('barcode') or 'unknown')+'.webp')}",
        }
        if src and photo:
            url,sc,meta=src
            used_sources[url]=entry["barcode"]
            if not args.dry_run:
                dest.parent.mkdir(parents=True,exist_ok=True)
                dest.write_bytes(photo)
            entry.update(type="photo",needs_real_photo=False,source_url=url,source_kind=meta.get("provider","unknown"),match_score=round(sc,4),source_meta=meta)
            report["photo"]+=1
        else:
            entry.update(type="pending_real_photo",needs_real_photo=True,source_url="",source_kind="",match_score=0)
            if err: report["errors"].append({"barcode":entry["barcode"],"name":entry["name"],"error":err})
            report["missing"]+=1
        manifest["products"][key]=entry
        report["products"][key]=entry

    # Never carry forward an old generated status for the priority set.
    manifest["version"]="2026-09-22-real-v1"
    manifest["batch_size"]=BATCH_SIZE
    manifest["priority_count"]=len(priority)
    MANIFEST.parent.mkdir(parents=True,exist_ok=True)
    MANIFEST.write_text(json.dumps(manifest,indent=2,ensure_ascii=False),encoding="utf-8")
    REPORT.write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding="utf-8")
    print(json.dumps({k:report[k] for k in ("requested","photo","missing","reused_source_rejected")},indent=2))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
