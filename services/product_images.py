"""Exact-product image resolution for the public catalogue.

The resolver is deliberately conservative: it only stores an image when the
source data has a strong name/brand/barcode match. It prefers openly reusable
product databases and Wikimedia Commons; it does not copy random retailer
images or silently use category stock art for branded products.
"""

from functools import lru_cache
from urllib.parse import urlencode
import re

import requests
from flask import current_app


GENERIC_TERMS = {
    "pack", "piece", "pcs", "unit", "box", "bottle", "bag", "tin", "jar", "can",
    "set", "s", "kg", "g", "mg", "ml", "l", "litre", "liter", "x", "size",
}
GENERIC_BRANDS = {"various", "fresh produce", "fresh meat", "fresh fish"}


def _tokens(value: str):
    return [t for t in re.findall(r"[a-z0-9]+", (value or "").lower()) if len(t) > 1]


def _core_tokens(value: str):
    return set(_tokens(value)) - GENERIC_TERMS


def _score(query_name: str, query_brand: str, candidate_name: str, candidate_brand: str):
    q_core = _core_tokens(query_name)
    c_core = _core_tokens(candidate_name)
    if not q_core or not c_core:
        return 0.0

    overlap = len(q_core & c_core) / max(1, len(q_core))
    q_norm = " ".join(_tokens(query_name))
    c_norm = " ".join(_tokens(candidate_name))
    phrase = 0.18 if q_norm and (q_norm == c_norm or q_norm in c_norm or c_norm in q_norm) else 0.0

    brand_bonus = 0.0
    if query_brand and query_brand.lower() not in GENERIC_BRANDS:
        qb = " ".join(_tokens(query_brand))
        cb = " ".join(_tokens(candidate_brand or ""))
        if not qb:
            return 0.0
        if qb == cb:
            brand_bonus = 0.30
        elif qb in cb or cb in qb:
            brand_bonus = 0.22
        else:
            return 0.0

    score = overlap * 0.64 + phrase + brand_bonus
    return min(1.0, score)


def _request_json(url, *, params=None):
    response = requests.get(
        url,
        params=params,
        timeout=float(current_app.config.get("PRODUCT_IMAGE_LOOKUP_TIMEOUT", 5)),
        headers={"User-Agent": "Denmart/18 exact-product-photo-resolver"},
    )
    response.raise_for_status()
    return response.json()


def _search_openfacts(name: str, brand: str, barcode: str):
    # Barcode is the strongest identity signal, so use it before fuzzy search.
    if barcode:
        for base in (
            "https://world.openfoodfacts.org/api/v2/product/",
            "https://world.openbeautyfacts.org/api/v2/product/",
            "https://world.openproductsfacts.org/api/v2/product/",
        ):
            try:
                payload = _request_json(base + str(barcode).strip(), params={
                    "fields": "code,product_name,brands,image_front_url,image_url"
                })
                product = payload.get("product") or {}
                image = product.get("image_front_url") or product.get("image_url")
                if image and str(image).startswith("https://"):
                    score = _score(name, brand, product.get("product_name") or name, product.get("brands") or brand)
                    if score >= 0.48:
                        return score, str(image), {
                            "source_type": "OPEN_FACTS_BARCODE",
                            "license_info": "Open product database image; verify the specific image's reuse terms before paid campaigns.",
                            "candidate": product,
                        }
            except Exception:
                continue

    params = {
        "search_terms": f"{brand} {name}".strip(),
        "search_simple": "1",
        "action": "process",
        "json": "1",
        "page_size": "20",
        "fields": "product_name,brands,image_front_url,image_url,code",
        "sort_by": "relevance",
    }
    for endpoint, source_type in (
        (current_app.config.get("PRODUCT_IMAGE_LOOKUP_URL", "https://world.openfoodfacts.org/cgi/search.pl"), "OPEN_FOOD_FACTS"),
        ("https://world.openbeautyfacts.org/cgi/search.pl", "OPEN_BEAUTY_FACTS"),
        ("https://world.openproductsfacts.org/cgi/search.pl", "OPEN_PRODUCTS_FACTS"),
    ):
        try:
            payload = _request_json(endpoint, params=params)
        except Exception:
            continue
        best = None
        for candidate in payload.get("products") or []:
            image = candidate.get("image_front_url") or candidate.get("image_url")
            if not image or not str(image).startswith("https://"):
                continue
            score = _score(name, brand, candidate.get("product_name") or "", candidate.get("brands") or "")
            # Strong named-brand matches only; brandless goods can pass on name quality.
            threshold = 0.60 if brand and brand.lower() not in GENERIC_BRANDS else 0.58
            if score >= threshold and (best is None or score > best[0]):
                best = (
                    score,
                    str(image),
                    {
                        "source_type": source_type,
                        "license_info": "Open product database image; verify the specific image's reuse terms before paid campaigns.",
                        "candidate": candidate,
                    },
                )
        if best:
            return best
    return None


@lru_cache(maxsize=2048)
def _search_commons(query: str, brand: str):
    """Find a strongly matching Wikimedia Commons image when product DBs miss."""
    search = " ".join(x for x in [brand, query] if x).strip()
    if not search:
        return None
    params = {
        "action": "query",
        "generator": "search",
        "gsrsearch": search,
        "gsrnamespace": "6",
        "gsrlimit": "12",
        "prop": "imageinfo",
        "iiprop": "url|extmetadata",
        "iiurlwidth": "1000",
        "format": "json",
        "origin": "*",
    }
    try:
        payload = _request_json("https://commons.wikimedia.org/w/api.php", params=params)
    except Exception:
        return None
    best = None
    for page in (payload.get("query") or {}).get("pages", {}).values():
        infos = page.get("imageinfo") or []
        if not infos:
            continue
        info = infos[0]
        image = info.get("thumburl") or info.get("url")
        if not image or not str(image).startswith("https://"):
            continue
        title = str(page.get("title") or "")
        score = _score(query, brand, title, brand)
        # Commons is a fallback for products/brands that have a genuinely useful image there.
        if score >= 0.58 and (best is None or score > best[0]):
            meta = info.get("extmetadata") or {}
            license_name = ((meta.get("LicenseShortName") or {}).get("value") or "Wikimedia Commons")[:300]
            best = (
                score,
                str(image),
                {
                    "source_type": "WIKIMEDIA_COMMONS",
                    "license_info": f"Wikimedia Commons · {license_name}",
                    "candidate": {"title": title, "url": info.get("descriptionurl")},
                },
            )
    return best


@lru_cache(maxsize=2048)
def lookup_exact_image(name: str, brand: str = "", barcode: str = "", search_keywords: str = ""):
    """Return (score, URL, metadata) for a strong exact/near-exact match."""
    name = (name or "").strip()
    brand = (brand or "").strip()
    barcode = re.sub(r"\D", "", str(barcode or ""))
    result = _search_openfacts(name, brand, barcode)
    if result:
        return result

    # Search useful aliases/keywords only when they increase product identity.
    fallback_query = " ".join(x for x in [brand, name, search_keywords] if x).strip()
    return _search_commons(fallback_query or name, brand)


def resolve_product_image(product):
    """Return a trusted exact-match image URL, or None when no strong match exists."""
    if product.image_url and str(product.image_url).strip():
        return product.image_url
    result = lookup_exact_image(
        product.name,
        product.brand or "",
        getattr(product, "barcode", "") or "",
        getattr(product, "search_keywords", "") or "",
    )
    if not result:
        return None
    return result[1]


def resolve_product_image_with_metadata(product):
    if product.image_url and str(product.image_url).strip():
        return product.image_url, {
            "source_type": "EXISTING",
            "license_info": "Existing product image retained.",
        }
    result = lookup_exact_image(
        product.name,
        product.brand or "",
        getattr(product, "barcode", "") or "",
        getattr(product, "search_keywords", "") or "",
    )
    if not result:
        return None, None
    return result[1], result[2]
