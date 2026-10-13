#!/usr/bin/env python3
"""Build a local cache of verified catalogue photos during deployment.

Only exact curated product URLs, explicit product image URLs, and verified prior
photos count as photographs. Legacy records are reconnected by exact barcode/name/
brand identity. Ambiguous shared URLs are not assigned to a random SKU, and the build
never writes generated placeholder artwork into the product-photo cache.
"""

from __future__ import annotations

import argparse
import base64
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
from functools import lru_cache
import os
import re
import sys
from io import BytesIO
from pathlib import Path
from urllib.parse import urlparse

import requests
from PIL import Image, ImageOps

# Make imports work when invoked as `python scripts/prepare_catalogue_images.py`.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import app  # noqa: E402
from extensions import db  # noqa: E402
from models import Product, ProductImage, Category  # noqa: E402
from bootstrap import bootstrap_database  # noqa: E402
from services.product_images import (  # noqa: E402
    local_product_image_url, LOCAL_PREFIX, real_product_image_url,
    legacy_catalogue_record, legacy_catalogue_source_url,
)

CACHE_DIR = ROOT / "static" / "catalogue" / "products"
MANIFEST_PATH = ROOT / "static" / "catalogue" / "catalogue-image-manifest.json"
LEGACY_CACHE_DIR = ROOT / "catalogue" / "products"
LEGACY_MANIFEST_PATH = ROOT / "catalogue" / "catalogue-image-manifest.json"
SOURCES_PATH = ROOT / "data" / "catalogue_image_sources.json"
USER_AGENT = "DenmartCatalogueBuilder/2026.09"
MAX_DOWNLOAD_BYTES = 8 * 1024 * 1024
TIMEOUT = float(os.getenv("PRODUCT_IMAGE_BUILD_TIMEOUT", "15"))

def safe_id(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]", "", str(value or ""))


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def source_maps():
    if not SOURCES_PATH.exists():
        return {}, {}
    try:
        payload = json.loads(SOURCES_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}, {}
    by_id = {str(k): str(v) for k, v in (payload.get("by_product_id") or {}).items() if str(v).startswith(("http://", "https://"))}
    by_barcode = {str(k): str(v) for k, v in (payload.get("by_barcode") or {}).items() if str(v).startswith(("http://", "https://"))}
    return by_id, by_barcode


def normalize_photo(data: bytes) -> bytes:
    with Image.open(BytesIO(data)) as src:
        src = ImageOps.exif_transpose(src).convert("RGBA")
        # Keep a clean square with white background and preserve the whole pack.
        src.thumbnail((720, 720), Image.Resampling.LANCZOS)
        canvas = Image.new("RGBA", (800, 800), (255, 255, 255, 255))
        canvas.alpha_composite(src, ((800 - src.width) // 2, (800 - src.height) // 2))
        out = BytesIO()
        canvas.convert("RGB").save(out, format="WEBP", quality=90, method=6)
        return out.getvalue()


def download_image(url: str):
    try:
        response = requests.get(
            url,
            timeout=TIMEOUT,
            allow_redirects=True,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
            },
            stream=True,
        )
        response.raise_for_status()
        chunks = []
        total = 0
        for chunk in response.iter_content(chunk_size=128 * 1024):
            if not chunk:
                continue
            total += len(chunk)
            if total > MAX_DOWNLOAD_BYTES:
                return None
            chunks.append(chunk)
        data = b"".join(chunks)
        return normalize_photo(data) if data else None
    except Exception:
        return None


def data_url_image(url: str):
    raw = str(url or "").strip()
    if not raw.startswith("data:image/") or "," not in raw:
        return None
    try:
        return normalize_photo(base64.b64decode(raw.split(",", 1)[1]))
    except Exception:
        return None


def source_candidates_for(product, by_id, by_barcode):
    """Build ordered image candidates without assuming a stale ID means identity.

    Exact legacy identity and exact-name sources come before generic barcode maps.
    All candidates are then checked against every product that might use a URL, so
    a shared bottle-size or model image cannot silently become another SKU's photo.
    """
    current = normalize_text(product.image_url or "")
    saved = normalize_text(getattr(product, "_denmart_saved_image_url", "") or "")
    candidates = []

    # Data URLs came from a direct product edit; keep them at the highest priority.
    for value in (current, saved):
        if value.startswith("data:image/") and value not in candidates:
            candidates.append(value)

    # Recover sources using exact barcode + full name + brand identity, then use
    # curated full-name mapping only when its URL is unambiguous across SKUs.
    legacy_source = legacy_catalogue_source_url(product)
    if legacy_source and legacy_source not in candidates:
        candidates.append(legacy_source)
    named_source = real_product_image_url(product.name)
    if named_source and named_source not in candidates:
        candidates.append(named_source)

    # Keep any previously saved direct URLs as fallbacks, but check URL ownership
    # against all candidates before serving or caching them.
    for value in (current, saved):
        if value.startswith(("http://", "https://")) and value not in candidates:
            candidates.append(value)

    # A barcode is a strong lookup key but the source table has some URLs reused
    # for many unrelated products. Keep it only as a later candidate; URL ownership
    # validation below decides whether this exact source can safely be reused.
    barcode = normalize_text(product.barcode or "")
    if barcode and barcode in by_barcode:
        value = by_barcode[barcode]
        if value and value not in candidates:
            candidates.append(value)

    # Do not trust by_product_id blindly: the source map was built against older
    # product UUIDs, and catalogue imports changed those IDs. Exact legacy identity
    # recovery above is the safe bridge between the two versions.
    return candidates


def _pack_hint(text: str) -> str:
    value = normalize_text(text).lower().replace(" ", "")
    match = re.search(r"(?<![a-z0-9])(\d+(?:[.,]\d+)?)(ml|l|kg|g|pcs|pc|pack|s)(?![a-z])", value)
    if not match:
        return ""
    number, unit = match.group(1).replace(",", "."), match.group(2)
    if unit == "l" and number.startswith("0"):
        unit = "ml"
        try: number = str(int(float(number) * 1000))
        except Exception: pass
    return number + unit


def _product_image_identity(product):
    """Fields that must be identical before a repeated image may be shared."""
    return (
        normalize_text(product.name).casefold(),
        normalize_text(product.brand or "").casefold(),
        normalize_text(product.pack_size or product.unit or "").casefold(),
    )


def _select_source_owners(products, candidate_sources):
    """Return URL owners and ambiguous URLs, respecting candidate priority.

    A URL explicitly assigned to one product outranks the same URL appearing only
    as a low-priority fallback for another product. If two products claim the same
    URL at the same priority, they must be identical SKUs or the URL must identify
    exactly one pack size; otherwise it is rejected for those products.
    """
    groups = {}
    for product in products:
        product_id = str(product.id)
        for rank, source in enumerate(candidate_sources.get(product_id, ())):
            if source:
                members = groups.setdefault(source, {})
                members.setdefault(product_id, (product, rank))
    owners, ambiguous = {}, set()
    for source, member_map in groups.items():
        best_rank = min(rank for _, rank in member_map.values())
        members = [product for product, rank in member_map.values() if rank == best_rank]
        if len(members) == 1:
            owners[source] = (str(members[0].id),)
            continue
        identities = {_product_image_identity(item) for item in members}
        if len(identities) == 1:
            owners[source] = tuple(str(item.id) for item in members)
            continue
        url_parts = urlparse(source)
        hint = _pack_hint(url_parts.path + " " + url_parts.query)
        exact = [item for item in members if hint and _pack_hint(" ".join((item.name or "", item.pack_size or "", item.unit or ""))) == hint]
        if len(exact) == 1:
            owners[source] = (str(exact[0].id),)
        else:
            ambiguous.add(source)
    return owners, ambiguous


def _record_matches_product(record, product):
    if not record or normalize_text(record.get("name", "")).casefold() != normalize_text(product.name).casefold():
        return False
    prior_barcode = normalize_text(record.get("barcode", ""))
    current_barcode = normalize_text(product.barcode or "")
    if prior_barcode and current_barcode and prior_barcode != current_barcode:
        return False
    prior_brand = normalize_text(record.get("brand", "")).casefold()
    current_brand = normalize_text(product.brand or "").casefold()
    if prior_brand and current_brand and prior_brand != current_brand:
        return False
    return True


# Hashes of the old generated silhouette/placeholder cards in this repository. Those
# files were labelled as "photo" by an old manifest even though they are not photos.
# Never restore them as if they were real product images.
KNOWN_GENERATED_LEGACY_SHA256 = {
    "894ebdfe7e966c117c053458a143e27e3bd99fa61968ab54815dafe7342156c7",
    "0ce45bb681b88a9503251966a30b6c641269734701d232411e9dcb63849b5810",
    "e3c03cdf463f23ed733864bb0c13aafd0521ed164a6ea59a046af883b14c6987",
    "5d806cb145b80c50d9d5d600eb642fc2482a99f62c84cf01eb6c9a2bd39853ae",
    "e3e693bb254e9d36f7d0638768d42fc6cf875e9a6175ebd6990826de34126239",
    "b9f20b81993eb599adb195fe764ac746a7c731c1b85e8ee81571c1a5dacbee13",
    "999424366122b7bd061e9bd657f5588587f2cdd08cbbcb5638e35fb7ef0b6fff",
    "d683cdab61dc871622ada9bc8a8115e9fe7352a46597ab5569e13dd04110a1bc",
    "437138c35003d9c27ec4cfed64f744da4e09be5e2328844b5da47ca457a9c446",
    "e1543508242c4d2cd81bf310a091a1bd4f82bf370d9f7873ecda79760f9e9bf0",
}

def persist_primary(product, local_url, source_type, source_url="", license_info=""):
    product.image_url = local_url
    # The cache has one canonical image per product. Remove stale external/secondary
    # records so old hotlinks cannot be accidentally selected by another part of the app.
    ProductImage.query.filter_by(product_id=product.id).delete(synchronize_session=False)
    info = license_info or "Local Denmart catalogue image."
    if source_url:
        info = f"Cached locally from {source_url} · {info}"
    db.session.add(ProductImage(
            product_id=product.id,
            image_url=local_url,
            thumbnail_url=local_url,
            alt_text=product.name,
            source_type=source_type,
            license_info=info,
            sort_order=0,
            is_primary=True,
        ))



@lru_cache(maxsize=1)
def legacy_photo_manifest():
    try:
        payload = json.loads(LEGACY_MANIFEST_PATH.read_text(encoding="utf-8"))
        return payload.get("products", {}) if isinstance(payload, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def _safe_cached_photo(record, product, base_dir):
    """Load a previously cached photo only if identity agrees and it is not one of
    the known generated legacy silhouette cards."""
    if not _record_matches_product(record, product) or record.get("type") != "photo":
        return None
    filename = str(record.get("file") or f"{getattr(product, 'id', '')}.webp")
    if Path(filename).name != filename or not filename.lower().endswith(".webp"):
        return None
    path = base_dir / filename
    if not path.is_file():
        return None
    try:
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() in KNOWN_GENERATED_LEGACY_SHA256:
            return None
        return normalize_photo(raw)
    except Exception:
        return None


def legacy_photo_bytes(product):
    """Recover a genuine old photo across changed UUIDs using barcode + exact name."""
    record = legacy_catalogue_record(product)
    if not record:
        return None
    return _safe_cached_photo(record, product, LEGACY_CACHE_DIR)


def prior_static_photo_bytes(product, previous_manifest):
    """Recover a previous deployment's cached image across the old batch layout.

    Older manifests stored files as ``<batch>/<barcode>.webp`` and sometimes kept
    the manifest status as pending even after the file had been generated. If the
    manifest identity matches this exact product and the file is a valid non-known
    placeholder image, carry it forward into the current flat-ID cache layout.
    """
    record = (previous_manifest or {}).get(str(product.id)) or {}
    if not _record_matches_product(record, product):
        return None
    filename = str(record.get("file") or f"{getattr(product, 'id', '')}.webp").strip()
    if not filename or Path(filename).is_absolute() or Path(filename).suffix.lower() != ".webp":
        return None
    base = CACHE_DIR.resolve()
    path = (CACHE_DIR / filename).resolve()
    try:
        path.relative_to(base)
    except ValueError:
        return None
    if not path.is_file():
        return None
    try:
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() in KNOWN_GENERATED_LEGACY_SHA256:
            return None
        return normalize_photo(raw)
    except Exception:
        return None


def read_manifest(path):
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        products = payload.get("products", {}) if isinstance(payload, dict) else {}
        return products if isinstance(products, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}

def download_unique_sources(sources):
    """Download only source-owner URLs in parallel to avoid slow serial builds."""
    http_sources = sorted({str(source) for source in sources if str(source).startswith(("http://", "https://"))})
    result = {}
    if not http_sources:
        return result
    with ThreadPoolExecutor(max_workers=min(4, len(http_sources))) as executor:
        pending = {executor.submit(download_image, source): source for source in http_sources}
        for future in as_completed(pending):
            source = pending[future]
            try:
                result[source] = future.result()
            except Exception:
                result[source] = None
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--discover", action="store_true", help="Use only exact, pre-curated product image source URLs.")
    parser.parse_args()

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    by_id, by_barcode = source_maps()
    previous_manifest = read_manifest(MANIFEST_PATH)

    with app.app_context():
        bootstrap_database()
        products = Product.query.order_by(Product.name).all()
        product_ids = [str(product.id) for product in products]
        if product_ids:
            try:
                saved_images = (ProductImage.query.filter(ProductImage.product_id.in_(product_ids))
                                .order_by(ProductImage.is_primary.desc(), ProductImage.sort_order, ProductImage.created_at).all())
                product_by_id = {str(item.id): item for item in products}
                for saved in saved_images:
                    product = product_by_id.get(str(saved.product_id))
                    if product is not None and not getattr(product, "_denmart_saved_image_url", ""):
                        product._denmart_saved_image_url = str(saved.image_url or "").strip()
            except Exception:
                print("Warning: could not preload ProductImage records; continuing with explicit Product.image_url and curated sources.")

        candidates_by_id = {
            str(product.id): source_candidates_for(product, by_id, by_barcode)
            for product in products
        }
        source_owners, ambiguous_sources = _select_source_owners(products, candidates_by_id)
        product_sources = {}
        for product in products:
            product_id = str(product.id)
            for candidate in candidates_by_id.get(product_id, ()):
                if candidate not in ambiguous_sources and product_id in source_owners.get(candidate, ()):
                    product_sources[product_id] = candidate
                    break
        owner_sources = sorted(set(product_sources.values()))
        source_cache = download_unique_sources(owner_sources)
        for product_id, source in product_sources.items():
            if source and source.startswith("data:image/") and source in source_owners and source not in source_cache:
                source_cache[source] = data_url_image(source)

        content_owners = {}
        manifest = {
            "version": "2026-10-13-real-photo-cache-v3-identity-recovery",
            "image_prefix": LOCAL_PREFIX,
            "products": {},
        }
        stats = {
            "total": 0, "photo": 0, "duplicate": 0, "ambiguous_source": 0,
            "source_unavailable": 0, "missing_source": 0,
            "unique_sources": len(source_cache), "cache_hits": 0,
            "legacy_fake_assets_rejected": len(KNOWN_GENERATED_LEGACY_SHA256),
        }

        for product in products:
            stats["total"] += 1
            filename = f"{safe_id(product.id)}.webp"
            destination = CACHE_DIR / filename
            local_url = local_product_image_url(product.id, "webp")
            source = product_sources.get(str(product.id), "")
            photo_data = prior_static_photo_bytes(product, previous_manifest)
            used_prior_photo = bool(photo_data)
            if not photo_data:
                photo_data = legacy_photo_bytes(product)

            image_type = ""
            duplicate_of = ""
            identity = _product_image_identity(product)

            # Preserve a previously downloaded genuine photo first, but never reuse
            # the old generated cards whose historical manifest said "photo".
            if photo_data:
                pass
            elif source and source in ambiguous_sources:
                image_type = "ambiguous_source"
                stats["ambiguous_source"] += 1
            elif source and str(product.id) not in source_owners.get(source, ()):
                owner_ids = source_owners.get(source, ())
                duplicate_of = owner_ids[0] if owner_ids else ""
                image_type = "duplicate"
                stats["duplicate"] += 1
            elif source and source in source_cache:
                photo_data = source_cache.get(source)
                if photo_data:
                    stats["cache_hits"] += 1
            if not photo_data and not image_type:
                image_type = "source_unavailable" if source else "missing_source"
                stats[image_type] += 1

            if photo_data:
                digest = hashlib.sha256(photo_data).hexdigest()
                existing_owner = content_owners.get(digest)
                if existing_owner and existing_owner[1] != identity:
                    photo_data = None
                    duplicate_of = existing_owner[0]
                    image_type = "duplicate"
                    stats["duplicate"] += 1
                else:
                    content_owners[digest] = (str(product.id), identity)
                    destination.write_bytes(photo_data)
                    image_type = "photo"
                    stats["photo"] += 1
            else:
                # No fake placeholder is written. Keep the original unique source URL
                # in the manifest so the public page may load it directly if online.
                try:
                    destination.unlink(missing_ok=True)
                except Exception:
                    pass

            manifest_record = {
                "name": product.name,
                "brand": product.brand or "",
                "barcode": product.barcode or "",
                "url": local_url,
                "type": image_type or "missing_source",
                "duplicate_of": duplicate_of,
                "source_url": source if source and source.startswith(("http://", "https://")) and not duplicate_of and source not in ambiguous_sources else "",
                "file": filename,
            }
            if used_prior_photo:
                prior_record = previous_manifest.get(str(product.id)) or {}
                manifest_record["source_url"] = str(prior_record.get("source_url") or manifest_record["source_url"] or "")
            manifest["products"][str(product.id)] = manifest_record

        MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
        MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
        print(json.dumps(stats, indent=2))


if __name__ == "__main__":
    main()
