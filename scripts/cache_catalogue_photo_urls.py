#!/usr/bin/env python3
"""Cache existing Denmart product-photo URLs as stable, local WEBP assets.

This utility does not invent product artwork or search by fuzzy product names. It
caches only a product's saved HTTP(S) image_url or an exact-name curated source.
Run from the project root with internet access before rebuilding/deploying:

  python scripts/cache_catalogue_photo_urls.py backup.sqlite --output-db denmart-images.sqlite

For a cautious Open Food Facts lookup of missing products, add
  --discover-openfoodfacts --discovery-limit 600

The resulting DB points at /static/catalogue/products/by-barcode/<barcode>.webp.
Commit that folder with the source before uploading the resulting DB. Failed or
invalid downloads leave the original URL untouched. Discovery only accepts strong
name/brand/pack-size matches and reports how many products it could actually cache.
"""
from __future__ import annotations
import argparse, hashlib, re, shutil, sqlite3, sys, time, uuid
from io import BytesIO
from pathlib import Path
from urllib.parse import urlencode
from difflib import SequenceMatcher

import requests
from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from services.product_images import real_product_image_url

MAX_BYTES = 10 * 1024 * 1024
USER_AGENT = "DenmartPhotoCache/1.0 (product image caching)"


def key_for(row):
    barcode = re.sub(r"[^A-Za-z0-9_-]", "", str(row["barcode"] or ""))
    if barcode:
        return barcode
    stable = " ".join(f"{row['name'] or ''} {row['brand'] or ''}".split()).casefold()
    return "name-" + hashlib.sha256(stable.encode("utf-8")).hexdigest()[:20]


def normalized(value):
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").casefold()).strip()


def size_tokens(value):
    return set(re.findall(r"\b\d+(?:\.\d+)?\s?(?:ml|cl|l|g|kg|mg|pcs|pc|pack|packs|s)\b", normalized(value)))


def discover_openfoodfacts(row):
    """Return (image URL, attribution URL) only for a strong product match."""
    import requests
    target_name = normalized(row["name"])
    target_brand = normalized(row["brand"])
    target_sizes = size_tokens(row["name"] + " " + str(row["pack_size"] if "pack_size" in row.keys() else ""))
    if not target_name:
        return None
    query = str(row["name"] or "").strip()
    if row["brand"] and normalized(row["brand"]) not in target_name:
        query = str(row["brand"]).strip() + " " + query
    params = {
        "search_terms": query, "search_simple": 1, "action": "process",
        "json": 1, "page_size": 8,
        "fields": "product_name,product_name_en,brands,quantity,image_front_url,image_front_small_url,code",
    }
    try:
        response = requests.get(
            "https://world.openfoodfacts.org/cgi/search.pl?" + urlencode(params),
            headers={"User-Agent": USER_AGENT}, timeout=(5, 15),
        )
        response.raise_for_status()
        payload = response.json()
    except Exception:
        return None

    best = None
    best_score = 0.0
    for item in payload.get("products", []) or []:
        pname = normalized(item.get("product_name") or item.get("product_name_en"))
        pbrand = normalized(item.get("brands"))
        quantity = normalized(item.get("quantity"))
        combined = " ".join(x for x in (pname, pbrand, quantity) if x)
        if not pname:
            continue
        if target_sizes and not target_sizes.issubset(size_tokens(combined)):
            continue
        if target_brand and len(target_brand) > 2 and target_brand not in pbrand and target_brand not in pname:
            continue
        target_core = target_name
        score = SequenceMatcher(None, target_core, pname).ratio()
        target_words = set(target_core.split()) - {"fresh", "product", "pack", "packaging", "supermarket"}
        candidate_words = set(combined.split())
        overlap = len(target_words & candidate_words) / max(1, len(target_words))
        score = max(score, overlap)
        # Require both strong name similarity and any explicit size/brand constraints.
        if score >= 0.78 and score > best_score:
            image_url = item.get("image_front_url") or item.get("image_front_small_url") or ""
            if str(image_url).startswith(("https://", "http://")):
                best = (image_url, "https://world.openfoodfacts.org/product/" + str(item.get("code") or ""))
                best_score = score
    return best


def download_photo(url):
    if not str(url or "").startswith(("https://", "http://")):
        return None
    try:
        with requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=(5, 18), stream=True) as response:
            response.raise_for_status()
            ctype = (response.headers.get("Content-Type") or "").lower()
            if "image/" not in ctype:
                return None
            chunks, size = [], 0
            for chunk in response.iter_content(65536):
                if not chunk:
                    continue
                size += len(chunk)
                if size > MAX_BYTES:
                    return None
                chunks.append(chunk)
        if not chunks:
            return None
        im = Image.open(BytesIO(b"".join(chunks)))
        im = ImageOps.exif_transpose(im)
        if im.width < 100 or im.height < 100:
            return None
        if im.mode not in ("RGB", "RGBA"):
            im = im.convert("RGBA" if "transparency" in im.info else "RGB")
        im.thumbnail((1200, 1200), Image.Resampling.LANCZOS)
        out = BytesIO()
        im.save(out, "WEBP", quality=88, method=6)
        return out.getvalue()
    except Exception:
        return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("database", help="SQLite backup to process; input is never overwritten")
    parser.add_argument("--output-db", default="denmart-images.sqlite", help="separate repaired SQLite output")
    parser.add_argument("--delay", type=float, default=0.15, help="delay between downloads in seconds")
    parser.add_argument("--discover-openfoodfacts", action="store_true", help="search Open Food Facts for strong exact product matches when saved photos are unavailable")
    parser.add_argument("--discovery-limit", type=int, default=600, help="maximum missing products to search when discovery is enabled")
    args = parser.parse_args()
    source = Path(args.database).resolve()
    output = Path(args.output_db).resolve()
    if not source.is_file():
        raise SystemExit(f"Input database not found: {source}")
    if source == output:
        raise SystemExit("Output must be a different file so the original backup stays safe.")
    output.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, output)
    cache = ROOT / "static" / "catalogue" / "products" / "by-barcode"
    cache.mkdir(parents=True, exist_ok=True)

    con = sqlite3.connect(str(output))
    con.row_factory = sqlite3.Row
    product_cols = {r[1] for r in con.execute("PRAGMA table_info(products)")}
    if not {"id", "name", "brand", "barcode", "image_url"}.issubset(product_cols):
        raise SystemExit("This SQLite file does not contain the expected Denmart products schema.")
    image_cols = {r[1] for r in con.execute("PRAGMA table_info(product_images)")}
    if not image_cols:
        raise SystemExit("This SQLite file is missing the product_images table.")

    rows = con.execute("SELECT id,name,brand,barcode,pack_size,image_url FROM products ORDER BY name").fetchall()
    stats = {"products": len(rows), "cached": 0, "already_local": 0, "unavailable": 0, "no_source": 0, "discovery_attempted": 0, "discovered": 0}
    for row in rows:
        original = str(row["image_url"] or "").strip()
        source_url = original if original.startswith(("https://", "http://")) else real_product_image_url(row["name"])
        attribution_url = source_url
        filename = key_for(row) + ".webp"
        dest = cache / filename
        local_url = "/static/catalogue/products/by-barcode/" + filename
        data = None
        if dest.is_file() and dest.stat().st_size > 0:
            stats["already_local"] += 1
        else:
            if source_url:
                data = download_photo(source_url)
            if not data and args.discover_openfoodfacts and stats["discovery_attempted"] < max(0, args.discovery_limit):
                stats["discovery_attempted"] += 1
                found = discover_openfoodfacts(row)
                if found:
                    discovered_url, product_page = found
                    discovered_data = download_photo(discovered_url)
                    if discovered_data:
                        data = discovered_data
                        source_url = discovered_url
                        attribution_url = product_page or discovered_url
                        stats["discovered"] += 1
                # Open Food Facts asks clients to avoid aggressive request rates.
                time.sleep(max(1.0, args.delay))
            if data:
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(data)
                stats["cached"] += 1
            else:
                if source_url:
                    stats["unavailable"] += 1
                else:
                    stats["no_source"] += 1
                continue

        con.execute("UPDATE products SET image_url=? WHERE id=?", (local_url, row["id"]))
        existing = con.execute(
            "SELECT id FROM product_images WHERE product_id=? ORDER BY is_primary DESC, sort_order ASC LIMIT 1",
            (row["id"],),
        ).fetchone()
        source_type = "OPENFOODFACTS_CACHED_PHOTO" if "world.openfoodfacts.org" in str(attribution_url or "") else "LOCAL_CACHED_PHOTO"
        license_note = "Cached locally from " + str(attribution_url or source_url) + "; verify and retain source/usage rights appropriate to commercial use."
        if source_type == "OPENFOODFACTS_CACHED_PHOTO":
            license_note += " Open Food Facts attribution/license requirements apply; confirm current terms before commercial use."
        if existing:
            con.execute(
                "UPDATE product_images SET image_url=?,thumbnail_url=?,alt_text=?,source_type=?,license_info=?,sort_order=0,is_primary=1 WHERE id=?",
                (local_url, local_url, row["name"], source_type, license_note, existing["id"]),
            )
        else:
            con.execute(
                "INSERT INTO product_images (id,product_id,image_url,thumbnail_url,alt_text,source_type,license_info,sort_order,is_primary,created_at) VALUES (?,?,?,?,?,?,?,?,?,datetime('now'))",
                (str(uuid.uuid4()), row["id"], local_url, local_url, row["name"], source_type, license_note, 0, 1),
            )
    con.commit()
    check = con.execute("PRAGMA integrity_check").fetchone()[0]
    con.close()
    print({**stats, "output_db": str(output), "cache_dir": str(cache), "integrity_check": check})
    if check != "ok":
        raise SystemExit("Output database integrity check failed.")

if __name__ == "__main__":
    main()
