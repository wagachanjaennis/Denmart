#!/usr/bin/env python3
"""Build a permanent catalogue image cache for Denmart.

Run during the Render build, not from a customer request.  The script:
1. reads product identities from the authoritative database;
2. imports previously discovered source URLs from data/catalogue_image_sources.json;
3. downloads/normalizes strong source images once;
4. stores a stable local image URL in products.image_url and product_images;
5. creates a deterministic product-specific image when no exact photo is available;
6. writes an image manifest used by the service worker and audit tooling.

Missing external photos never become blanks or unrelated products. A generated
visual is explicitly labelled as generated rather than masquerading as a photo.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
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
from services.product_images import local_product_image_url, LOCAL_PREFIX  # noqa: E402

CACHE_DIR = ROOT / "static" / "catalogue" / "products"
MANIFEST_PATH = ROOT / "static" / "catalogue" / "catalogue-image-manifest.json"
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
    if current.startswith(("http://", "https://")):
        return current
    if current.startswith("data:image/"):
        return current
    if str(product.id) in by_id:
        return by_id[str(product.id)]
    barcode = normalize_text(product.barcode or "")
    return by_barcode.get(barcode)


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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--discover", action="store_true", help="Reserved for future external discovery; current build only imports stored sources.")
    args = parser.parse_args()
    if args.discover:
        print("Image discovery mode requested: using only stored source URLs for this deterministic build.")

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    (ROOT / "data").mkdir(parents=True, exist_ok=True)
    by_id, by_barcode = source_maps()

    with app.app_context():
        bootstrap_database()
        products = Product.query.order_by(Product.name).all()
        manifest = {
            "version": "2026-09-21-local-v1",
            "image_prefix": LOCAL_PREFIX,
            "products": {},
        }
        stats = {"total": 0, "photo": 0, "generated": 0, "cached": 0, "existing": 0}
        for product in products:
            stats["total"] += 1
            filename = f"{safe_id(product.id)}.webp"
            destination = CACHE_DIR / filename
            local_url = local_product_image_url(product.id, "webp")
            source = source_for(product, by_id, by_barcode)
            photo_data = None
            source_type = "LOCAL_GENERATED"
            license_info = "Generated from the exact product name/brand identity; not a photograph."
            if source and source.startswith("data:image/"):
                photo_data = data_url_image(source)
            elif source and source.startswith(("http://", "https://")):
                # Stored product sources are the only external URLs considered by the build.
                # If the source is temporarily unavailable, keep the bundled local asset.
                photo_data = download_image(source)
            if photo_data:
                destination.write_bytes(photo_data)
                stats["photo"] += 1
                stats["cached"] += 1
                source_type = "LOCAL_CACHED_PHOTO"
                license_info = "Downloaded and normalized during the Denmart build; retain source/usage rights appropriate to your commercial use."
            elif destination.exists() and destination.stat().st_size > 0:
                stats["existing"] += 1
                source_type = "LOCAL_CACHE"
                license_info = "Denmart-bundled local catalogue image."
            else:
                destination.write_bytes(generated_product_card(product))
                stats["generated"] += 1
            persist_primary(product, local_url, source_type, source_url=(source if source and source.startswith(("http://", "https://")) else ""), license_info=license_info)
            manifest["products"][str(product.id)] = {
                "name": product.name,
                "brand": product.brand or "",
                "barcode": product.barcode or "",
                "url": local_url,
                "type": "photo" if source_type in {"LOCAL_CACHED_PHOTO", "LOCAL_CACHE"} else "generated",
                "source_url": source if source and source.startswith(("http://", "https://")) else "",
                "file": filename,
            }
        db.session.commit()
        MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
        MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
        print(json.dumps(stats, indent=2))


if __name__ == "__main__":
    main()
