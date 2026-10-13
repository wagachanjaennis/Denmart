#!/usr/bin/env python3
"""Build a local cache of verified catalogue photos during deployment.

Only exact curated product URLs, explicit product image URLs, and existing verified
product photos count as photographs. Shared pack-size photos are not reused across
SKUs. Generic placeholders are cached for file integrity but are never displayed as
real product images by the public image helper.
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
from PIL import Image, ImageDraw, ImageFont, ImageOps

# Make imports work when invoked as `python scripts/prepare_catalogue_images.py`.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import app  # noqa: E402
from extensions import db  # noqa: E402
from models import Product, ProductImage, Category  # noqa: E402
from bootstrap import bootstrap_database  # noqa: E402
from services.product_images import local_product_image_url, LOCAL_PREFIX, real_product_image_url  # noqa: E402

CACHE_DIR = ROOT / "static" / "catalogue" / "products"
MANIFEST_PATH = ROOT / "static" / "catalogue" / "catalogue-image-manifest.json"
LEGACY_CACHE_DIR = ROOT / "catalogue" / "products"
LEGACY_MANIFEST_PATH = ROOT / "catalogue" / "catalogue-image-manifest.json"
SOURCES_PATH = ROOT / "data" / "catalogue_image_sources.json"
USER_AGENT = "DenmartCatalogueBuilder/2026.09"
MAX_DOWNLOAD_BYTES = 8 * 1024 * 1024
TIMEOUT = float(os.getenv("PRODUCT_IMAGE_BUILD_TIMEOUT", "15"))

PALETTES = [
    ((248, 249, 247), (32, 89, 71), (232, 241, 237)),
    ((247, 248, 252), (68, 73, 133), (237, 237, 248)),
    ((250, 247, 246), (132, 67, 46), (244, 235, 231)),
    ((248, 249, 246), (105, 91, 39), (241, 239, 224)),
    ((247, 249, 251), (56, 89, 121), (231, 239, 247)),
]


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


def font(size: int, bold: bool = False):
    paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
    ]
    for p in paths:
        try:
            return ImageFont.truetype(p, size)
        except Exception:
            continue
    return ImageFont.load_default()


def palette(product):
    digest = hashlib.sha1(f"{product.brand}|{product.name}".encode("utf-8")).digest()
    return PALETTES[digest[0] % len(PALETTES)]


def wrap_lines(text: str, width=25, max_lines=3):
    words = normalize_text(text).split()
    lines, line = [], ""
    for word in words:
        candidate = f"{line} {word}".strip()
        if line and len(candidate) > width:
            lines.append(line)
            line = word
        else:
            line = candidate
    if line:
        lines.append(line)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        if not lines[-1].endswith("…"):
            lines[-1] = lines[-1][: max(1, width - 1)] + "…"
    return lines


def generated_product_card(product) -> bytes:
    """Create a product-specific image, never a generic stock photo."""
    bg, ink, panel = palette(product)
    im = Image.new("RGB", (800, 800), bg)
    draw = ImageDraw.Draw(im)
    draw.rounded_rectangle((28, 28, 772, 772), radius=44, fill=(255, 255, 255), outline=panel, width=4)
    draw.ellipse((610, 80, 730, 200), fill=panel)
    draw.ellipse((75, 590, 230, 745), fill=panel)

    # A clean catalogue silhouette, intentionally neutral rather than impersonating a photo.
    draw.rounded_rectangle((295, 190, 505, 555), radius=35, fill=ink)
    draw.rounded_rectangle((326, 147, 474, 220), radius=24, fill=ink)
    draw.rounded_rectangle((325, 315, 475, 470), radius=20, fill=(255, 255, 255))
    draw.rounded_rectangle((347, 350, 453, 388), radius=16, fill=panel)
    draw.rounded_rectangle((347, 405, 430, 440), radius=16, fill=panel)

    brand = normalize_text(product.brand or "DENMART").upper()[:30]
    title = wrap_lines(product.name, 24, 3)
    pack = normalize_text(product.pack_size or product.unit or "").upper()[:34]
    draw.text((400, 82), brand, anchor="ma", fill=ink, font=font(22, True))
    y = 615
    for line in title:
        draw.text((400, y), line, anchor="ma", fill=(34, 45, 44), font=font(25, True))
        y += 31
    if pack:
        draw.text((400, 748), pack, anchor="ma", fill=(108, 122, 119), font=font(18, True))
    out = BytesIO()
    im.save(out, format="WEBP", quality=88, method=6)
    return out.getvalue()


def placeholder_product_card(product=None) -> bytes:
    """Create a neutral placeholder when no exact real product photo is available."""
    im = Image.new("RGB", (800, 800), (245, 247, 246))
    draw = ImageDraw.Draw(im)
    draw.rounded_rectangle((35, 35, 765, 765), radius=48, fill=(255, 255, 255), outline=(180, 190, 186), width=6)
    draw.rounded_rectangle((270, 190, 530, 545), radius=38, fill=(239, 243, 241), outline=(155, 166, 162), width=6)
    draw.ellipse((355, 255, 445, 345), fill=(190, 200, 196))
    draw.arc((335, 315, 465, 430), 0, 180, fill=(190, 200, 196), width=12)
    draw.text((400, 610), "PRODUCT PHOTO", anchor="mm", fill=(76, 91, 85), font=font(26, True))
    draw.text((400, 655), "PLACEHOLDER", anchor="mm", fill=(76, 91, 85), font=font(24, True))
    out = BytesIO()
    im.save(out, format="WEBP", quality=88, method=6)
    return out.getvalue()


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


def source_for(product, by_id, by_barcode):
    current = normalize_text(product.image_url or "")
    if current.startswith(("http://", "https://", "data:image/")):
        return current
    saved = normalize_text(getattr(product, "_denmart_saved_image_url", "") or "")
    if saved.startswith(("http://", "https://", "data:image/")):
        return saved
    barcode = normalize_text(product.barcode or "")
    if str(product.id) in by_id:
        return by_id[str(product.id)]
    if barcode and barcode in by_barcode:
        return by_barcode[barcode]
    # Fall back to explicit exact-product mappings; never search by guess.
    return real_product_image_url(product.name)


def _pack_hint(text: str) -> str:
    value = normalize_text(text).lower().replace(" ", "")
    match = re.search(r"(?<!\d)(\d+(?:[.,]\d+)?)(ml|l|kg|g|pcs|pc|pack|s)", value)
    if not match:
        return ""
    number, unit = match.group(1).replace(",", "."), match.group(2)
    if unit == "l" and number.startswith("0"):
        unit = "ml"
        try: number = str(int(float(number) * 1000))
        except Exception: pass
    return number + unit


def _select_source_owners(products, sources):
    groups = {}
    for product in products:
        source = sources.get(str(product.id))
        if source:
            groups.setdefault(source, []).append(product)
    owners = {}
    for source, members in groups.items():
        if len(members) == 1:
            owners[source] = str(members[0].id)
            continue
        url_hint = urlparse(source).path + " " + urlparse(source).query
        hint = _pack_hint(url_hint)
        exact = [item for item in members if hint and _pack_hint(item.name) == hint]
        # If the source filename identifies a pack size, assign it only to the matching SKU.
        # Otherwise select one representative and leave other sizes awaiting their own exact photo.
        chosen = exact[0] if exact else sorted(members, key=lambda item: item.name.casefold())[0]
        owners[source] = str(chosen.id)
    return owners


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


def legacy_photo_bytes(product_id: str):
    record = legacy_photo_manifest().get(str(product_id)) or {}
    if record.get("type") != "photo":
        return None
    filename = str(record.get("file") or f"{product_id}.webp")
    if Path(filename).name != filename or not filename.lower().endswith(".webp"):
        return None
    path = LEGACY_CACHE_DIR / filename
    if not path.is_file():
        return None
    try:
        return normalize_photo(path.read_bytes())
    except Exception:
        return None


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
    source_cache = {}

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
        product_sources = {str(product.id): source_for(product, by_id, by_barcode) for product in products}
        source_owners = _select_source_owners(products, product_sources)
        owner_sources = [source for source, owner_id in source_owners.items() if owner_id]
        source_cache = download_unique_sources(owner_sources)
        for product_id, source in product_sources.items():
            if source and source.startswith("data:image/") and source in source_owners and source not in source_cache:
                product_data = data_url_image(source)
                source_cache[source] = product_data
        content_owners = {}
        manifest = {
            "version": "2026-10-13-real-photo-cache-v2",
            "image_prefix": LOCAL_PREFIX,
            "products": {},
        }
        stats = {"total": 0, "photo": 0, "placeholder": 0, "duplicate": 0, "unique_sources": len(source_cache), "cache_hits": 0}
        for product in products:
            stats["total"] += 1
            filename = f"{safe_id(product.id)}.webp"
            destination = CACHE_DIR / filename
            local_url = local_product_image_url(product.id, "webp")
            source = product_sources.get(str(product.id), "")
            photo_data = None
            duplicate_of = ""

            if source and source_owners.get(source) != str(product.id):
                duplicate_of = source_owners.get(source, "")
            elif source and source in source_cache:
                photo_data = source_cache[source]
                if photo_data:
                    stats["cache_hits"] += 1

            # If an older deployment already had a verified local photo, retain it
            # when the original CDN is temporarily unavailable.
            if not photo_data and not duplicate_of:
                photo_data = legacy_photo_bytes(product.id)

            # Never repeat one pack's photo on another differently named SKU.
            if photo_data and not duplicate_of:
                digest = hashlib.sha256(photo_data).hexdigest()
                if digest in content_owners:
                    duplicate_of = content_owners[digest]
                else:
                    content_owners[digest] = str(product.id)

            if duplicate_of:
                destination.write_bytes(placeholder_product_card(product))
                image_type = "duplicate"
                stats["duplicate"] += 1
            elif photo_data:
                destination.write_bytes(photo_data)
                image_type = "photo"
                stats["photo"] += 1
            else:
                destination.write_bytes(placeholder_product_card(product))
                image_type = "placeholder"
                stats["placeholder"] += 1

            manifest["products"][str(product.id)] = {
                "name": product.name,
                "brand": product.brand or "",
                "barcode": product.barcode or "",
                "url": local_url,
                "type": image_type,
                "duplicate_of": duplicate_of,
                "source_url": source if source and source.startswith(("http://", "https://")) else "",
                "file": filename,
            }

        MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
        MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
        print(json.dumps(stats, indent=2))


if __name__ == "__main__":
    main()
