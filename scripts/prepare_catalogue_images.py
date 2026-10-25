#!/usr/bin/env python3
"""Build a fast, durable cache of verified product photos for Denmart.

This runs during deployment/build, never inside a customer page request. It:
* honours verified real photos already bundled by the priority-photo cache;
* reuses database-stored WEBP data URLs so photos survive later Render deploys;
* caches remotely sourced photographs as same-origin WEBP files;
* stores a compact durable DB copy where practical;
* rejects ambiguous source URLs reused across different catalogue products;
* never creates bottle-shaped, generic or other fake product artwork.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from io import BytesIO
from pathlib import Path
from urllib.parse import unquote

import requests
from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import app  # noqa: E402
from extensions import db  # noqa: E402
from models import Product, ProductImage  # noqa: E402
from bootstrap import bootstrap_database  # noqa: E402
from services.product_images import real_product_image_url, is_data_image_url  # noqa: E402

CACHE_DIR = ROOT / "static" / "catalogue" / "products" / "by-barcode"
ROOT_MANIFEST_PATH = ROOT / "catalogue" / "catalogue-image-manifest.json"
STATIC_MANIFEST_PATH = ROOT / "static" / "catalogue" / "catalogue-image-manifest.json"
SOURCES_PATH = ROOT / "data" / "catalogue_image_sources.json"
INDEX_PATH = ROOT / "data" / "catalogue_product_index.json"
PRIORITY_PATH = ROOT / "data" / "catalogue_image_priority.json"
USER_AGENT = "DenmartCatalogueBuilder/2026.10"
MAX_DOWNLOAD_BYTES = 8 * 1024 * 1024
MAX_DATABASE_COPY_BYTES = 450_000
TIMEOUT = float(os.getenv("PRODUCT_IMAGE_BUILD_TIMEOUT", "6"))
MAX_WORKERS = max(1, min(10, int(os.getenv("PRODUCT_IMAGE_BUILD_WORKERS", "8"))))


def clean(value) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def safe_key(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]", "", str(value or ""))


def key_for(product) -> str:
    barcode = safe_key(getattr(product, "barcode", ""))
    if barcode:
        return barcode
    identity = clean(f"{getattr(product, 'name', '')}|{getattr(product, 'brand', '')}").casefold()
    return "name-" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:20]


def load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def norm_photo(data: bytes) -> bytes | None:
    """Normalize a genuine source image into a compact, white-backed WEBP square."""
    try:
        with Image.open(BytesIO(data)) as src:
            src = ImageOps.exif_transpose(src)
            if getattr(src, "is_animated", False):
                src.seek(0)
            src = src.convert("RGBA")
            if src.width < 80 or src.height < 80:
                return None
            src.thumbnail((720, 720), Image.Resampling.LANCZOS)
            canvas = Image.new("RGBA", (720, 720), (255, 255, 255, 255))
            canvas.alpha_composite(src, ((720 - src.width) // 2, (720 - src.height) // 2))
            out = BytesIO()
            canvas.convert("RGB").save(out, format="WEBP", quality=82, method=4)
            return out.getvalue()
    except Exception:
        return None


def decode_data_image(value: str) -> bytes | None:
    raw = str(value or "").strip()
    if not is_data_image_url(raw) or "," not in raw:
        return None
    try:
        return norm_photo(base64.b64decode(raw.split(",", 1)[1], validate=False))
    except Exception:
        return None


def static_path(url: str) -> Path | None:
    """Resolve a same-origin /static/ path without permitting traversal."""
    value = str(url or "").strip()
    if not value.startswith("/static/") or ".." in value.split("?", 1)[0].split("/"):
        return None
    relative = unquote(value.split("?", 1)[0]).removeprefix("/static/")
    root = (ROOT / "static").resolve()
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    return candidate if candidate.is_file() and candidate.stat().st_size > 0 else None


def static_manifest_photo(product, static_manifest: dict) -> tuple[str, str, str] | None:
    entry = (static_manifest.get("products") or {}).get(str(product.id), {})
    if not isinstance(entry, dict) or entry.get("type") != "photo":
        return None
    url = clean(entry.get("url"))
    if not url.startswith("/static/") and entry.get("file"):
        url = "/static/catalogue/products/" + clean(entry.get("file")).lstrip("/")
    path = static_path(url)
    if not path:
        return None
    return url, clean(entry.get("source_url")), clean(entry.get("source_kind") or "VERIFIED_CATALOGUE_PHOTO")


def source_maps():
    """Load curated URLs but remove URLs assigned to several different SKUs."""
    payload = load_json(SOURCES_PATH, {})
    by_id = {str(k): str(v) for k, v in (payload.get("by_product_id") or {}).items()
             if str(v).startswith(("http://", "https://"))}
    by_barcode = {str(k): str(v) for k, v in (payload.get("by_barcode") or {}).items()
                  if str(v).startswith(("http://", "https://"))}
    index = (load_json(INDEX_PATH, {}).get("products") or {})
    id_by_barcode = {str(v.get("barcode") or ""): str(pid) for pid, v in index.items() if v.get("barcode")}
    rank = {}
    for i, item in enumerate(load_json(PRIORITY_PATH, {}).get("priority_products", []), 1):
        pid = str(item.get("product_id") or "")
        if pid:
            rank[pid] = int(item.get("rank", i))
    owners: dict[str, set[str]] = defaultdict(set)
    for pid, url in by_id.items():
        owners[url].add(pid)
    for barcode, url in by_barcode.items():
        owners[url].add(id_by_barcode.get(barcode, "barcode:" + barcode))
    # A source reused across different SKUs is ambiguous, even if one appears earlier
    # in the priority list. Leave it for a verified barcode/name lookup instead.
    allowed_owner = {url: next(iter(ids)) for url, ids in owners.items() if len(ids) == 1}
    clean_by_id = {pid: url for pid, url in by_id.items() if allowed_owner.get(url) == pid}
    clean_by_barcode = {}
    for barcode, url in by_barcode.items():
        pid = id_by_barcode.get(barcode, "barcode:" + barcode)
        if allowed_owner.get(url) == pid:
            clean_by_barcode[barcode] = url
    return clean_by_id, clean_by_barcode


def remote_from_license(license_info: str) -> str:
    value = clean(license_info)
    if value.startswith(("https://", "http://")):
        return value.split()[0].rstrip("·;, ")
    match = re.search(r"(?:Cached locally from|Source(?: URL)?[:=]?)\s+(https?://\S+)", value, re.I)
    if match:
        return match.group(1).rstrip("·;, )]")
    return ""


def source_for(product, image_rows, by_id, by_barcode, remote_owner_counts):
    """Return a source descriptor, preferring any persisted image bytes over a URL."""
    current = clean(product.image_url)
    # Admin uploads and existing runtime WEBP cache entries are durable image bytes.
    if is_data_image_url(current):
        return {"kind": "database_data_image", "value": current, "source_url": ""}

    rows = image_rows.get(str(product.id), [])
    # The runtime photo proxy saves successful downloads to PostgreSQL. Reuse that
    # saved image before attempting its original CDN URL on every rebuild.
    for row in rows:
        value = clean(row.image_url)
        if getattr(row, "source_type", "") == "denmart-offline-cache" and is_data_image_url(value):
            return {"kind": "database_data_image", "value": value,
                    "source_url": remote_from_license(row.license_info)}
    for row in rows:
        value = clean(row.image_url)
        if is_data_image_url(value):
            return {"kind": "database_data_image", "value": value,
                    "source_url": remote_from_license(row.license_info)}

    # A local product upload/file is safe only if the exact file is actually present.
    if current.startswith("/static/") and static_path(current):
        return {"kind": "local_file", "value": current, "source_url": ""}
    for row in rows:
        value = clean(row.image_url)
        if value.startswith("/static/") and static_path(value):
            return {"kind": "local_file", "value": value,
                    "source_url": remote_from_license(row.license_info)}

    # Ignore external URLs shared by different product rows; those mappings caused
    # wrong sizes/flavours to display another item's pack photo.
    if current.startswith(("https://", "http://")) and remote_owner_counts.get(current, 1) <= 1:
        return {"kind": "remote_url", "value": current, "source_url": current}
    for row in rows:
        value = clean(row.image_url)
        if value.startswith(("https://", "http://")) and remote_owner_counts.get(value, 1) <= 1:
            return {"kind": "remote_url", "value": value, "source_url": value}
        recovered = remote_from_license(row.license_info)
        if recovered and remote_owner_counts.get(recovered, 1) <= 1:
            return {"kind": "remote_url", "value": recovered, "source_url": recovered}

    barcode = clean(product.barcode)
    if str(product.id) in by_id:
        url = by_id[str(product.id)]
        if remote_owner_counts.get(url, 1) <= 1:
            return {"kind": "remote_url", "value": url, "source_url": url}
    if barcode in by_barcode:
        url = by_barcode[barcode]
        if remote_owner_counts.get(url, 1) <= 1:
            return {"kind": "remote_url", "value": url, "source_url": url}
    curated = real_product_image_url(product.name)
    if curated and remote_owner_counts.get(curated, 1) <= 1:
        return {"kind": "remote_url", "value": curated, "source_url": curated}
    return None


def download_image(url: str):
    try:
        response = requests.get(
            url, timeout=(min(2.5, TIMEOUT), TIMEOUT), allow_redirects=True, stream=True,
            headers={"User-Agent": USER_AGENT, "Accept": "image/avif,image/webp,image/jpeg,image/png,image/*,*/*;q=0.7"},
        )
        response.raise_for_status()
        content_type = str(response.headers.get("Content-Type", "")).lower()
        if not content_type.startswith("image/"):
            response.close()
            return None
        chunks, size = [], 0
        for chunk in response.iter_content(64 * 1024):
            if not chunk:
                continue
            size += len(chunk)
            if size > MAX_DOWNLOAD_BYTES:
                response.close()
                return None
            chunks.append(chunk)
        response.close()
        return norm_photo(b"".join(chunks)) if chunks else None
    except Exception:
        return None


def write_local_photo(product, image_bytes: bytes) -> str:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    dest = CACHE_DIR / (key_for(product) + ".webp")
    dest.write_bytes(image_bytes)
    revision = hashlib.sha256(image_bytes).hexdigest()[:10]
    return "/static/catalogue/products/by-barcode/" + dest.name + "?v=" + revision


def persist_photo(product, image_rows, image_bytes, final_url, source_url, source_kind):
    product.image_url = final_url
    rows = image_rows.get(str(product.id), [])
    # Keep every existing gallery/upload row. Add/update a primary local URL instead
    # of deleting user-managed images as the previous cache script did.
    primary = next((row for row in rows if row.image_url == final_url and row.source_type != "denmart-offline-cache"), None)
    if primary is None:
        primary = next((row for row in rows if row.source_type in {"LOCAL_CACHED_PHOTO", "VERIFIED_CATALOGUE_PHOTO"}), None)
    for row in rows:
        if row is not primary and row.is_primary:
            row.is_primary = False
    if primary is None:
        primary = ProductImage(product_id=product.id, image_url=final_url, thumbnail_url=final_url,
                               alt_text=clean(product.name)[:240], source_type=source_kind,
                               license_info=source_url or "Local product image retained from Denmart database.",
                               sort_order=0, is_primary=True)
        db.session.add(primary)
        rows.append(primary)
        image_rows[str(product.id)] = rows
    else:
        primary.image_url = final_url
        primary.thumbnail_url = final_url
        primary.alt_text = clean(product.name)[:240]
        primary.source_type = source_kind
        primary.license_info = source_url or "Local product image retained from Denmart database."
        primary.sort_order = 0
        primary.is_primary = True

    # Save a compact durable WEBP copy in PostgreSQL. This is what makes images stay
    # available when a new Render build does not have the previous build's static files.
    if len(image_bytes) <= MAX_DATABASE_COPY_BYTES:
        cached = "data:image/webp;base64," + base64.b64encode(image_bytes).decode("ascii")
        provenance = source_url or ("database upload / cached image" if source_kind == "database_data_image" else "local photo")
        durable = next((row for row in rows if row.source_type == "denmart-offline-cache" and row.license_info == provenance), None)
        if durable is None:
            durable = ProductImage(product_id=product.id, image_url=cached, thumbnail_url=cached,
                                   alt_text=clean(product.name)[:220] + " · saved product photo",
                                   source_type="denmart-offline-cache", license_info=provenance,
                                   sort_order=1000, is_primary=False)
            db.session.add(durable)
            rows.append(durable)
            image_rows[str(product.id)] = rows
        else:
            durable.image_url = cached
            durable.thumbnail_url = cached


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--discover", action="store_true", help="compatibility flag; active discovery occurs in the prioritized photo-cache script")
    parser.add_argument("--download-limit", type=int, default=int(os.getenv("PRODUCT_IMAGE_BUILD_DOWNLOAD_LIMIT", "250")), help="maximum external URLs fetched during this build")
    parser.add_argument("--workers", type=int, default=MAX_WORKERS)
    args = parser.parse_args()

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    by_id, by_barcode = source_maps()
    static_manifest = load_json(STATIC_MANIFEST_PATH, {"products": {}})
    priority_rank = {str(item.get("product_id")): int(item.get("rank", i + 1))
                     for i, item in enumerate(load_json(PRIORITY_PATH, {}).get("priority_products", []))
                     if item.get("product_id")}

    with app.app_context():
        bootstrap_database()
        products = Product.query.order_by(Product.name).all()
        rows_all = ProductImage.query.order_by(ProductImage.is_primary.desc(), ProductImage.sort_order, ProductImage.created_at).all()
        image_rows = defaultdict(list)
        for row in rows_all:
            image_rows[str(row.product_id)].append(row)

        # Count URLs across all DB records so one shared product photo cannot silently
        # be assigned to several differently sized/ flavoured products.
        remote_owner_ids = defaultdict(set)
        for product in products:
            value = clean(product.image_url)
            if value.startswith(("https://", "http://")):
                remote_owner_ids[value].add(str(product.id))
        for row in rows_all:
            value = clean(row.image_url)
            if value.startswith(("https://", "http://")):
                remote_owner_ids[value].add(str(row.product_id))
        remote_owner_counts = {url: len(ids) for url, ids in remote_owner_ids.items()}

        ordered = sorted(products, key=lambda p: (priority_rank.get(str(p.id), 100000), clean(p.name).casefold(), str(p.id)))
        stats = {"total": len(products), "photo": 0, "cached_from_database": 0, "downloaded": 0,
                 "bundled": 0, "unavailable": 0, "ambiguous_sources_skipped": 0, "downloads_attempted": 0}
        manifest = {"version": "2026-10-25-real-photo-cache-v2", "image_prefix": "/static/catalogue/products/", "products": {}}
        jobs = []
        source_urls_reserved = set()

        for product in ordered:
            pid = str(product.id)
            local_key = key_for(product)
            stable_path = CACHE_DIR / (local_key + ".webp")
            existing_static = static_manifest_photo(product, static_manifest)
            if existing_static:
                url, source_url, source_kind = existing_static
                path = static_path(url)
                image_bytes = norm_photo(path.read_bytes()) if path else None
                if image_bytes:
                    stats["bundled"] += 1
                    jobs.append({"product": product, "image_bytes": image_bytes, "final_url": url,
                                 "source_url": source_url, "source_kind": source_kind, "pid": pid})
                    continue

            source = source_for(product, image_rows, by_id, by_barcode, remote_owner_counts)
            if source and source.get("kind") in {"database_data_image", "local_file"}:
                if source["kind"] == "database_data_image":
                    image_bytes = decode_data_image(source["value"])
                    stats["cached_from_database"] += bool(image_bytes)
                    source_kind = "DATABASE_CACHED_PHOTO"
                else:
                    path = static_path(source["value"])
                    image_bytes = norm_photo(path.read_bytes()) if path else None
                    source_kind = "LOCAL_CACHED_PHOTO"
                if image_bytes:
                    final_url = source["value"] if source["kind"] == "local_file" and source["value"].startswith("/static/catalogue/products/") else write_local_photo(product, image_bytes)
                    jobs.append({"product": product, "image_bytes": image_bytes, "final_url": final_url,
                                 "source_url": source.get("source_url", ""), "source_kind": source_kind, "pid": pid})
                    continue

            if source and source.get("kind") == "remote_url":
                url = source["value"]
                if url in source_urls_reserved or remote_owner_counts.get(url, 1) > 1:
                    stats["ambiguous_sources_skipped"] += 1
                    source = None
                elif stats["downloads_attempted"] >= max(0, args.download_limit):
                    source = None
                else:
                    source_urls_reserved.add(url)
                    stats["downloads_attempted"] += 1
                    jobs.append({"product": product, "source_url_to_download": url,
                                 "source_url": url, "source_kind": "REAL_SOURCE_PHOTO", "pid": pid})
                    continue

            # Drop only known stale UUID placeholders, not uploads or valid remote URLs.
            current = clean(product.image_url)
            if current.startswith("/static/catalogue/products/") and not static_path(current):
                leaf = current.split("?", 1)[0].rsplit("/", 1)[-1]
                if re.fullmatch(r"[0-9a-fA-F-]{36}\.webp", leaf):
                    product.image_url = ""
            stats["unavailable"] += 1
            manifest["products"][pid] = {"name": product.name, "brand": product.brand or "", "barcode": product.barcode or "",
                                          "url": clean(product.image_url), "type": "pending_real_photo", "source_url": "", "file": ""}

        # External downloads run concurrently. The storefront itself never performs this
        # work, so it remains fast while a deployment warms the verified-photo catalogue.
        workers = max(1, min(12, int(args.workers or MAX_WORKERS)))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(download_image, job["source_url_to_download"]): job for job in jobs if job.get("source_url_to_download")}
            for future in as_completed(futures):
                job = futures[future]
                image_bytes = future.result()
                if image_bytes:
                    product = job["product"]
                    job["image_bytes"] = image_bytes
                    job["final_url"] = write_local_photo(product, image_bytes)
                    job["source_kind"] = "LOCAL_CACHED_PHOTO"
                    stats["downloaded"] += 1
                else:
                    job["failed"] = True
                    stats["unavailable"] += 1

        # Persist image rows in one short transaction after network work has completed.
        for job in jobs:
            product = job["product"]
            pid = job["pid"]
            image_bytes = job.get("image_bytes")
            if job.get("failed") or not image_bytes:
                manifest["products"][pid] = {"name": product.name, "brand": product.brand or "", "barcode": product.barcode or "",
                                              "url": clean(product.image_url), "type": "pending_real_photo", "source_url": job.get("source_url", ""), "file": ""}
                continue
            final_url = job["final_url"]
            source_url = clean(job.get("source_url"))
            source_kind = clean(job.get("source_kind") or "LOCAL_CACHED_PHOTO")
            persist_photo(product, image_rows, image_bytes, final_url, source_url, source_kind)
            relative = final_url.split("?", 1)[0].removeprefix("/static/catalogue/products/") if final_url.startswith("/static/catalogue/products/") else ""
            manifest["products"][pid] = {"name": product.name, "brand": product.brand or "", "barcode": product.barcode or "",
                                          "url": final_url, "type": "photo", "source_url": source_url, "source_kind": source_kind,
                                          "file": relative}
            stats["photo"] += 1

        db.session.commit()
        ROOT_MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
        ROOT_MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
        print(json.dumps(stats, indent=2))


if __name__ == "__main__":
    main()
