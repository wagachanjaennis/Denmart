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
import hashlib
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
    return sorted(out,key=lambda x:x[1],reverse=True)[:2]


def source_candidates(product: dict, sources: dict, curated_owner: dict[str, str] | None = None) -> list[tuple[str,float,dict]]:
    """Prefer exact curated photos; discover alternatives only when safe to do so.

    If one URL was attached to several different SKUs, it is rejected for every SKU;
    each pack size must find its own photo instead of inheriting an ambiguous match.
    """
    result=[]
    by_id=sources.get("by_product_id") or {}
    by_barcode=sources.get("by_barcode") or {}
    by_page=sources.get("by_product_page") or {}
    pid=str(product.get("product_id") or "")
    direct=(by_id.get(pid), by_barcode.get(str(product.get("barcode") or "")))
    for url in direct:
        if not isinstance(url,str) or not url.startswith(("http://","https://")):
            continue
        if curated_owner is not None and curated_owner.get(url) != pid:
            continue
        if not any(existing[0] == url for existing in result):
            result.append((url,1.0,{"provider":"curated-exact-product-source"}))
    if result:
        return result

    page=by_page.get(pid)
    if isinstance(page,str) and page.startswith(("http://","https://")):
        try:
            page_images=extract_page_images(page,product)
            if page_images:
                return [(u,sc,{**meta,"provider":"curated-product-page"}) for u,sc,meta in page_images]
        except Exception:
            pass

    # Open Food Facts-family text search verifies name/brand/pack size. Only fall back
    # to retailer page crawling if the facts catalogs return no credible candidate.
    result=facts_search(product)
    if result:
        return result
    for page_url,domain in retailer_search_urls(product)[:3]:
        try:
            for u,sc,meta in extract_page_images(page_url,product):
                meta={**meta,"provider":domain,"page_url":page_url}
                result.append((u,sc,meta))
        except Exception:
            continue
    seen=set(); out=[]
    for u,sc,meta in sorted(result,key=lambda x:x[1],reverse=True):
        if u in seen: continue
        seen.add(u); out.append((u,sc,meta))
    return out[:3]


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
    product_index=load_json(PRODUCT_INDEX,{"products":{}}).get("products") or {}
    rank_by_id={str(item.get("product_id")):int(item.get("rank",i+1))
                for i,item in enumerate(load_json(PRIORITY,{"priority_products":[]}).get("priority_products",[]))
                if item.get("product_id")}
    barcode_to_id={str(item.get("barcode") or ""):str(pid) for pid,item in product_index.items() if item.get("barcode")}
    source_owners={}
    for pid,url in (sources.get("by_product_id") or {}).items():
        if str(url).startswith(("http://","https://")):
            source_owners.setdefault(str(url),set()).add(str(pid))
    for barcode,url in (sources.get("by_barcode") or {}).items():
        if str(url).startswith(("http://","https://")):
            source_owners.setdefault(str(url),set()).add(barcode_to_id.get(str(barcode),"barcode:"+str(barcode)))
    # Only use a curated URL when it belongs to exactly one SKU. Reused photos were
    # the source of wrong pack-size images (e.g. a 500 ml bottle shown for 2 L).
    curated_owner={url:next(iter(owners)) for url,owners in source_owners.items() if len(owners)==1}

    CACHE.mkdir(parents=True,exist_ok=True)
    # The product catalog owns the authoritative list. Remove ONLY stale fake/catalogue
    # assets from previous versions; real photos will be replaced only if the same barcode
    # is intentionally refreshed.
    for i in range(1,15):
        (CACHE/f"{i:03d}").mkdir(parents=True,exist_ok=True)

    manifest=load_json(MANIFEST,{"version":"2026-09-22-real-v1","image_prefix":"/static/catalogue/products/","batch_size":100,"priority_count":len(priority),"products":{}})
    manifest.setdefault("products",{})
    # Purge stale references to illustration files or photos that are no longer shipped.
    # The manifest may retain old IDs, but they are never treated as real unless the file exists.
    for stale_id, stale_entry in list(manifest["products"].items()):
        if not isinstance(stale_entry, dict) or stale_entry.get("type") != "photo":
            continue
        stale_url = str(stale_entry.get("url") or "").strip()
        if not stale_url.startswith("/static/") and stale_entry.get("file"):
            stale_url = "/static/catalogue/products/" + str(stale_entry.get("file") or "").lstrip("/")
        rel = stale_url.split("?", 1)[0].removeprefix("/static/") if stale_url.startswith("/static/") else ""
        stale_path = (ROOT / "static" / rel).resolve() if rel else None
        try:
            shipped = bool(stale_path and stale_path.is_file() and stale_path.stat().st_size > 0 and stale_path.is_relative_to((ROOT / "static").resolve()))
        except Exception:
            shipped = False
        if not shipped:
            stale_entry.update(type="pending_real_photo", needs_real_photo=True, url="", file="")
    report={"version":"2026-10-25-real-v3","requested":len(priority),"photo":0,"missing":0,"reused_source_rejected":0,"reused_image_rejected":0,"errors":[],"products":{}}
    def one(idx,p):
        batch=f"{(idx//BATCH_SIZE)+1:03d}"
        barcode=str(p.get("barcode") or "").strip()
        if not barcode:
            return idx,p,batch,None,None,[],"missing barcode"
        dest=CACHE/batch/f"{barcode}.webp"
        candidates=source_candidates(p,sources,curated_owner)
        last_errors=[]
        for url,sc,meta in candidates:
            try:
                data=fetch_bytes(url)
                photo=normalize_photo(data)
                return idx,p,batch,dest,(url,sc,meta),photo,None
            except Exception as e:
                last_errors.append(f"{url}: {e}")
        # A dead curated URL should not prevent trying verified product databases.
        # Do this fallback only after the exact curated source failed, avoiding extra
        # external search requests when the supplied product photo already works.
        if candidates and all((meta.get("provider") or "").startswith("curated-") for _, _, meta in candidates):
            for url,sc,meta in facts_search(p):
                try:
                    photo=normalize_photo(fetch_bytes(url))
                    if photo:
                        return idx,p,batch,dest,(url,sc,meta),photo,None
                except Exception as e:
                    last_errors.append(f"{url}: {e}")
            for page_url,domain in retailer_search_urls(p)[:2]:
                try:
                    found=extract_page_images(page_url,p)[:2]
                except Exception:
                    found=[]
                for url,sc,meta in found:
                    try:
                        photo=normalize_photo(fetch_bytes(url))
                        if photo:
                            return idx,p,batch,dest,(url,sc,{**meta,"provider":domain}),photo,None
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

    used_sources={}
    used_photo_hashes={}
    for idx,p,batch,dest,src,photo,err in results:
        key=p.get("product_id") or str(p.get("barcode") or "unknown")
        if src and photo:
            candidate_url=src[0]
            owner_key=str(p.get("product_id") or p.get("barcode") or "unknown")
            owner=used_sources.get(candidate_url)
            if owner and owner!=owner_key:
                report["reused_source_rejected"] += 1
                src=None; photo=None
                err=f"Source URL already assigned to another SKU ({owner}); refusing duplicate product photo."
            else:
                image_hash=hashlib.sha256(photo).hexdigest()
                image_owner=used_photo_hashes.get(image_hash)
                if image_owner and image_owner!=owner_key:
                    report["reused_image_rejected"] += 1
                    src=None; photo=None
                    err=f"Normalized photo bytes already assigned to another SKU ({image_owner}); refusing duplicate product photo."
                else:
                    used_sources[candidate_url]=owner_key
                    used_photo_hashes[image_hash]=owner_key
        entry={
            "name":p.get("name",""),"brand":p.get("brand","") or "","barcode":str(p.get("barcode") or ""),
            "priority_rank":int(p.get("rank",idx)),"batch":batch,
            "url":f"/static/catalogue/products/{batch}/{dest.name if dest else (str(p.get('barcode') or 'unknown')+'.webp')}?v={hashlib.sha256(photo).hexdigest()[:10]}" if src and photo else f"/static/catalogue/products/{batch}/{dest.name if dest else (str(p.get('barcode') or 'unknown')+'.webp')}",
            "file":f"{batch}/{dest.name if dest else (str(p.get('barcode') or 'unknown')+'.webp')}",
        }
        if src and photo:
            url,sc,meta=src
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
    manifest["version"]="2026-10-25-real-v3"
    manifest["batch_size"]=BATCH_SIZE
    manifest["priority_count"]=len(priority)
    MANIFEST.parent.mkdir(parents=True,exist_ok=True)
    MANIFEST.write_text(json.dumps(manifest,indent=2,ensure_ascii=False),encoding="utf-8")
    REPORT.write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding="utf-8")
    print(json.dumps({k:report[k] for k in ("requested","photo","missing","reused_source_rejected","reused_image_rejected")},indent=2))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
